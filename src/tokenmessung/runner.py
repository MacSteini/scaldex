from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .analyzer import analyze_results
from .schemas import OUTPUT_SCHEMA, TASKS

ProgressCallback = Callable[[dict[str, Any]], None]
PROCESS_TIMEOUT_EXIT_CODE = 124
IGNORED_SUBJECT_FILE_NAMES = {".DS_Store"}
IGNORED_SUBJECT_DIR_NAMES = {".git", "__pycache__"}
RUN_ISOLATION = {
    "ephemeral": True,
    "ignore_user_config": True,
    "ignore_rules": True,
    "isolated_codex_home": True,
    "home_codex_excluded": True,
}


def command_output(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip() or result.stderr.strip()


def codex_version() -> str:
    try:
        return command_output(["codex", "--version"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def fixture_commit(fixture: Path) -> str:
    return command_output(["git", "rev-parse", "HEAD"], cwd=fixture)


def fixture_is_git_repo(fixture: Path) -> bool:
    try:
        command_output(["git", "rev-parse", "--is-inside-work-tree"], cwd=fixture)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def codex_exec_help() -> str:
    return command_output(["codex", "exec", "--help"])


def codex_exec_capabilities() -> dict[str, bool]:
    try:
        help_text = codex_exec_help()
    except (FileNotFoundError, subprocess.CalledProcessError):
        help_text = ""
    return {
        "supports_json": "--json" in help_text,
        "supports_output_schema": "--output-schema" in help_text,
        "supports_ignore_user_config": "--ignore-user-config" in help_text,
        "supports_ignore_rules": "--ignore-rules" in help_text,
    }


def validate_benchmark_inputs(fixture: Path, agents_file: Path | None, repeats: int, require_api_key: bool = True, agents_dir: Path | None = None) -> None:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if (agents_file is None) == (agents_dir is None):
        raise ValueError("Provide exactly one of agents_file or agents_dir")
    if not fixture.exists():
        raise FileNotFoundError(f"Fixture does not exist: {fixture}")
    if not fixture_is_git_repo(fixture):
        raise ValueError(f"Fixture is not a Git repository: {fixture}")
    fixture_commit(fixture)
    if agents_file is not None and not agents_file.is_file():
        raise FileNotFoundError(f"AGENTS file does not exist: {agents_file}")
    if agents_dir is not None:
        if not agents_dir.is_dir():
            raise FileNotFoundError(f"AGENTS directory does not exist: {agents_dir}")
        if not (agents_dir / "AGENTS.md").is_file():
            raise FileNotFoundError(f"AGENTS directory must contain AGENTS.md: {agents_dir}")
    capabilities = codex_exec_capabilities()
    missing = [key for key, present in capabilities.items() if not present]
    if missing:
        raise EnvironmentError(f"codex exec is missing required capabilities: {', '.join(missing)}")
    if require_api_key and "CODEX_API_KEY" not in os.environ:
        raise EnvironmentError("CODEX_API_KEY is required for benchmark runs")


def copy_fixture(fixture: Path, workdir: Path) -> None:
    if workdir.exists():
        shutil.rmtree(workdir)
    ignore = shutil.ignore_patterns(".git")
    shutil.copytree(fixture, workdir, ignore=ignore)


def init_git_snapshot(workdir: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(["git", "add", "."], cwd=workdir, check=True)
    subprocess.run(
        ["git", "-c", "user.name=tokenmessung", "-c", "user.email=tokenmessung@example.invalid", "commit", "-q", "-m", "run snapshot"],
        cwd=workdir,
        check=True,
    )


def remove_control_instructions(workdir: Path) -> None:
    for relative in ("AGENTS.md", "AGENTS.override.md", ".codex", ".codex-project"):
        target = workdir / relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def install_agents_file(workdir: Path, agents_file: Path) -> None:
    shutil.copy2(agents_file, workdir / "AGENTS.md")


def install_agents_dir(workdir: Path, agents_dir: Path) -> None:
    for source in agents_dir.iterdir():
        if source.name == ".git":
            continue
        target = workdir / source.name
        if source.is_dir():
            if target.exists() and not target.is_dir():
                target.unlink()
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__"), dirs_exist_ok=True)
        else:
            if target.is_dir():
                shutil.rmtree(target)
            shutil.copy2(source, target)


def should_ignore_subject_path(path: Path) -> bool:
    if path.name in IGNORED_SUBJECT_FILE_NAMES:
        return True
    return any(part in IGNORED_SUBJECT_DIR_NAMES for part in path.parts)


def audit_subject_source(agents_file: Path | None, agents_dir: Path | None, subject_mode: str = "manual") -> dict[str, Any]:
    if agents_file is not None:
        size = agents_file.stat().st_size
        warnings = ["large_subject"] if size > 32_000 else []
        return {
            "mode": subject_mode,
            "source_type": "file",
            "path": str(agents_file),
            "file_count": 1,
            "total_bytes": size,
            "largest_files": [{"path": agents_file.name, "bytes": size}],
            "warnings": warnings,
        }
    assert agents_dir is not None
    total = 0
    files: list[dict[str, Any]] = []
    for path in agents_dir.rglob("*"):
        relative = path.relative_to(agents_dir)
        if should_ignore_subject_path(relative) or not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        files.append({"path": relative.as_posix(), "bytes": size})
    files.sort(key=lambda item: int(item["bytes"]), reverse=True)
    file_paths = {str(item["path"]) for item in files}
    top_level_dirs = {Path(path).parts[0] for path in file_paths if Path(path).parts}
    warnings: list[str] = []
    if total > 32_000:
        warnings.append("large_subject")
    if ".codex" in top_level_dirs:
        warnings.append("subject_contains_codex")
    if any(path.startswith(".codex/skills/") for path in file_paths):
        warnings.append("subject_contains_codex_skills")
    if any(path.startswith(".codex/config/tooling/") for path in file_paths):
        warnings.append("subject_contains_codex_tooling")
    if any(path.startswith(".codex/bin/") for path in file_paths):
        warnings.append("subject_contains_codex_bin")
    return {
        "mode": subject_mode,
        "source_type": "dir",
        "path": str(agents_dir),
        "file_count": len(files),
        "total_bytes": total,
        "largest_files": files[:10],
        "warnings": warnings,
    }


def agents_source_size(agents_file: Path | None, agents_dir: Path | None) -> int:
    return int(audit_subject_source(agents_file, agents_dir).get("total_bytes", 0))


def write_output_schema(run_dir: Path) -> Path:
    schema_path = run_dir / "output_schema.json"
    schema_path.write_text(json.dumps(OUTPUT_SCHEMA, indent=2) + "\n", encoding="utf-8")
    return schema_path


def selected_tasks(task_ids: list[str] | None = None) -> list[dict[str, Any]]:
    if not task_ids:
        return list(TASKS)
    by_id = {task["id"]: task for task in TASKS}
    missing = [task_id for task_id in task_ids if task_id not in by_id]
    if missing:
        raise ValueError(f"Unknown task id(s): {', '.join(missing)}")
    return [by_id[task_id] for task_id in task_ids]


def emit_progress(progress: ProgressCallback | None, event: dict[str, Any]) -> None:
    if progress is not None:
        progress(event)


def stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def wait_for_codex_process(
    process: subprocess.Popen[Any],
    *,
    run_id: str,
    started: float,
    progress: ProgressCallback | None,
    heartbeat_interval: float,
    max_run_seconds: float | None,
) -> int:
    while True:
        elapsed = time.monotonic() - started
        wait_timeout = heartbeat_interval
        if max_run_seconds is not None:
            remaining = max_run_seconds - elapsed
            if remaining <= 0:
                stop_process(process)
                emit_progress(progress, {"event": "run_timeout", "run_id": run_id, "elapsed_seconds": round(elapsed, 1), "max_run_seconds": max_run_seconds})
                return PROCESS_TIMEOUT_EXIT_CODE
            wait_timeout = min(heartbeat_interval, remaining)
        try:
            return process.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            if max_run_seconds is not None and elapsed >= max_run_seconds:
                stop_process(process)
                emit_progress(progress, {"event": "run_timeout", "run_id": run_id, "elapsed_seconds": round(elapsed, 1), "max_run_seconds": max_run_seconds})
                return PROCESS_TIMEOUT_EXIT_CODE
            emit_progress(
                progress,
                {
                    "event": "run_heartbeat",
                    "run_id": run_id,
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                },
            )


def run_one(
    *,
    fixture: Path,
    agents_file: Path | None,
    agents_dir: Path | None,
    model: str,
    out: Path,
    task: dict[str, Any],
    variant: str,
    repeat: int,
    run_order: int,
    keep_workdirs: bool = False,
    workspace_root: Path | None = None,
    progress: ProgressCallback | None = None,
    heartbeat_interval: float = 10.0,
    total_runs: int | None = None,
    max_run_seconds: float | None = None,
    subject_mode: str = "manual",
    subject_audit: dict[str, Any] | None = None,
) -> None:
    run_id = f"{task['id']}__{variant}__r{repeat}"
    run_dir = out / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    if workspace_root is None:
        workspace_parent = Path(tempfile.mkdtemp(prefix=f"tokenmessung-{run_id}-"))
    else:
        workspace_parent = workspace_root / run_id
        if workspace_parent.exists():
            shutil.rmtree(workspace_parent)
        workspace_parent.mkdir(parents=True)
    workdir = workspace_parent / "repo"
    copy_fixture(fixture, workdir)
    if variant == "control":
        remove_control_instructions(workdir)
    elif variant == "agents":
        if agents_dir is not None:
            install_agents_dir(workdir, agents_dir)
        elif agents_file is not None:
            install_agents_file(workdir, agents_file)
        else:
            raise ValueError("agents variant requires agents_file or agents_dir")
    else:
        raise ValueError(f"Unknown variant: {variant}")
    init_git_snapshot(workdir)

    schema_path = write_output_schema(run_dir)
    final_path = run_dir / "final.json"
    jsonl_path = run_dir / "codex.jsonl"
    stderr_path = run_dir / "stderr.log"
    time_path = run_dir / "time.json"
    exit_code_path = run_dir / "exit_code.txt"
    codex_home = run_dir / "codex-home"
    codex_home.mkdir()

    command = [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--cd",
        str(workdir),
        "--model",
        model,
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="never"',
        "-c",
        'model_reasoning_effort="medium"',
        "-c",
        'model_verbosity="low"',
        "--output-schema",
        str(schema_path),
        "-o",
        str(final_path),
        task["prompt"],
    ]

    effective_subject_audit = subject_audit or audit_subject_source(agents_file, agents_dir, subject_mode=subject_mode)
    meta = {
        "run_id": run_id,
        "task_id": task["id"],
        "task": task,
        "variant": variant,
        "repeat": repeat,
        "run_order": run_order,
        "model": model,
        "fixture": str(fixture),
        "fixture_commit": fixture_commit(fixture),
        "agents_source_type": "dir" if agents_dir is not None else "file",
        "agents_file": str(agents_file) if agents_file is not None else "",
        "agents_dir": str(agents_dir) if agents_dir is not None else "",
        "subject_mode": subject_mode,
        "agents_file_bytes": effective_subject_audit.get("total_bytes", 0),
        "agents_source_file_count": effective_subject_audit.get("file_count", 0),
        "subject_audit": effective_subject_audit,
        "workdir": str(workdir),
        "workspace_parent": str(workspace_parent),
        "workspace_root": str(workspace_root) if workspace_root is not None else "",
        "codex_home": str(codex_home),
        "run_isolation": RUN_ISOLATION,
        "codex_version": codex_version(),
        "python_version": sys.version.split()[0],
        "codex_command": command,
        "keep_workdirs": keep_workdirs,
        "workdir_cleanup": "pending",
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    emit_progress(
        progress,
        {
            "event": "run_start",
            "run_id": run_id,
            "task_id": task["id"],
            "variant": variant,
            "repeat": repeat,
            "run_order": run_order,
            "total_runs": total_runs,
        },
    )
    started = time.monotonic()
    exit_code: int | None = None
    try:
        with jsonl_path.open("w", encoding="utf-8") as jsonl, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(command, cwd=workdir, env=env, text=True, stdout=jsonl, stderr=stderr)
            try:
                exit_code = wait_for_codex_process(
                    process,
                    run_id=run_id,
                    started=started,
                    progress=progress,
                    heartbeat_interval=heartbeat_interval,
                    max_run_seconds=max_run_seconds,
                )
            except BaseException:
                stop_process(process)
                raise
        exit_code_path.write_text(f"{exit_code}\n", encoding="utf-8")
    finally:
        ended = time.monotonic()
        wall_seconds = ended - started
        time_path.write_text(json.dumps({"wall_seconds": wall_seconds}, indent=2) + "\n", encoding="utf-8")
        if keep_workdirs:
            meta["workdir_cleanup"] = "kept"
        else:
            shutil.rmtree(workspace_parent, ignore_errors=True)
            meta["workdir_cleanup"] = "removed" if not workspace_parent.exists() else "failed"
        schema_path.unlink(missing_ok=True)
        shutil.rmtree(codex_home, ignore_errors=True)
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        if exit_code is not None:
            emit_progress(
                progress,
                {
                    "event": "run_done",
                    "run_id": run_id,
                    "task_id": task["id"],
                    "variant": variant,
                    "repeat": repeat,
                    "run_order": run_order,
                    "total_runs": total_runs,
                    "exit_code": exit_code,
                    "wall_seconds": round(wall_seconds, 1),
                },
            )


def run_benchmark(
    fixture: Path,
    agents_file: Path | None,
    model: str,
    repeats: int,
    out: Path,
    seed: int | None = None,
    keep_workdirs: bool = False,
    agents_dir: Path | None = None,
    workspace_root: Path | None = None,
    progress: ProgressCallback | None = None,
    heartbeat_interval: float = 10.0,
    max_run_seconds: float | None = None,
    task_ids: list[str] | None = None,
    analysis_dir: Path | None = None,
    subject_mode: str = "manual",
) -> dict[str, Path]:
    validate_benchmark_inputs(fixture, agents_file, repeats, agents_dir=agents_dir)
    subject_audit = audit_subject_source(agents_file, agents_dir, subject_mode=subject_mode)
    out.mkdir(parents=True, exist_ok=True)
    if workspace_root is not None:
        workspace_root.mkdir(parents=True, exist_ok=True)
    tasks = selected_tasks(task_ids)
    randomizer = random.Random(seed)
    run_order = 0
    total_runs = repeats * len(tasks) * 2
    emit_progress(progress, {"event": "benchmark_start", "total_runs": total_runs, "repeats": repeats, "task_count": len(tasks)})
    for repeat in range(1, repeats + 1):
        for task in tasks:
            variants = ["control", "agents"]
            randomizer.shuffle(variants)
            for variant in variants:
                run_order += 1
                run_one(
                    fixture=fixture,
                    agents_file=agents_file,
                    agents_dir=agents_dir,
                    model=model,
                    out=out,
                    task=task,
                    variant=variant,
                    repeat=repeat,
                    run_order=run_order,
                    keep_workdirs=keep_workdirs,
                    workspace_root=workspace_root,
                    progress=progress,
                    heartbeat_interval=heartbeat_interval,
                    total_runs=total_runs,
                    max_run_seconds=max_run_seconds,
                    subject_mode=subject_mode,
                    subject_audit=subject_audit,
                )
    emit_progress(progress, {"event": "analysis_start", "results_dir": str(out)})
    outputs = analyze_results(out, output_dir=analysis_dir)
    emit_progress(progress, {"event": "analysis_done", "outputs": {key: str(value) for key, value in outputs.items()}})
    return outputs


def write_synthetic_run(run_dir: Path, task: dict[str, Any], variant: str, repeat: int, run_order: int, rng: random.Random) -> None:
    run_dir.mkdir(parents=True)
    base_tokens = 4600 + repeat * 73 + len(task["id"]) * 11 + rng.randint(0, 40)
    token_delta = 1300 + rng.randint(0, 120)
    input_tokens = base_tokens if variant == "control" else base_tokens - token_delta
    cached_input_tokens = 180 + rng.randint(0, 25)
    commands = [
        {"command": "bash -lc 'find . -maxdepth 3 -type f | sort'", "stdout": "\n".join(task["expected_files"])},
        {"command": f"bash -lc 'rg {task['expected_terms'][0]} .'", "stdout": " ".join(task["expected_files"] + task["expected_terms"])},
    ]
    if variant == "control":
        commands.append({"command": "bash -lc 'cat logs/app.log'", "stdout": "x" * 22_000})
    else:
        commands.append({"command": "bash -lc 'wc -c logs/app.log && sed -n 1,20p docs/subsystems.md'", "stdout": "245000 logs/app.log\nAuth export CLI Feature X release"})

    events: list[dict[str, Any]] = [{"type": "thread.started", "thread_id": f"synthetic-{run_dir.name}"}]
    for command in commands:
        events.append({"type": "item.completed", "item": {"type": "command_execution", **command}})
    events.append(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": 320 if variant == "control" else 260,
                "reasoning_output_tokens": 180 if variant == "control" else 140,
            },
        }
    )
    (run_dir / "codex.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    final = {
        "answer": f"Synthetic {variant} answer for {task['id']}: " + ", ".join(task["expected_files"]),
        "relevant_files": task["expected_files"],
        "root_cause_or_location": " ".join(task["expected_terms"]),
        "confidence": "high",
    }
    (run_dir / "final.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    (run_dir / "exit_code.txt").write_text("0\n", encoding="utf-8")
    (run_dir / "time.json").write_text(json.dumps({"wall_seconds": 1.0 + rng.random()}, indent=2) + "\n", encoding="utf-8")
    meta = {
        "run_id": run_dir.name,
        "task_id": task["id"],
        "task": task,
        "variant": variant,
        "repeat": repeat,
        "run_order": run_order,
        "model": "synthetic",
        "fixture_commit": "synthetic",
        "agents_file_bytes": 0,
        "subject_mode": "synthetic",
        "agents_source_file_count": 1,
        "subject_audit": {
            "mode": "synthetic",
            "source_type": "synthetic",
            "path": "synthetic-subject",
            "file_count": 1,
            "total_bytes": 2048,
            "largest_files": [{"path": "AGENTS.md", "bytes": 2048}],
            "warnings": [],
        },
        "codex_version": "synthetic",
        "python_version": sys.version.split()[0],
        "codex_command": [],
        "run_isolation": RUN_ISOLATION,
        "keep_workdirs": False,
        "workdir_cleanup": "synthetic",
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def synthesize_benchmark(out: Path, repeats: int, seed: int | None = None) -> dict[str, Path]:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rng = random.Random(seed)
    run_order = 0
    for repeat in range(1, repeats + 1):
        for task in TASKS:
            variants = ["control", "agents"]
            rng.shuffle(variants)
            for variant in variants:
                run_order += 1
                run_id = f"{task['id']}__{variant}__r{repeat}"
                write_synthetic_run(out / run_id, task, variant, repeat, run_order, rng)
    return analyze_results(out)


def doctor() -> dict[str, Any]:
    capabilities = codex_exec_capabilities()
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "git": shutil.which("git") is not None,
        "codex": shutil.which("codex") is not None,
        "codex_version": codex_version(),
        "codex_api_key_present": bool(os.environ.get("CODEX_API_KEY")),
        **capabilities,
    }
    return checks
