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
from typing import Any

from .analyzer import analyze_results
from .schemas import OUTPUT_SCHEMA, TASKS


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


def validate_benchmark_inputs(fixture: Path, agents_file: Path, repeats: int, require_api_key: bool = True) -> None:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if not fixture.exists():
        raise FileNotFoundError(f"Fixture does not exist: {fixture}")
    if not fixture_is_git_repo(fixture):
        raise ValueError(f"Fixture is not a Git repository: {fixture}")
    fixture_commit(fixture)
    if not agents_file.is_file():
        raise FileNotFoundError(f"AGENTS file does not exist: {agents_file}")
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
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(["git", "add", "."], cwd=workdir, check=True)
    subprocess.run(
        ["git", "-c", "user.name=tokenmessung", "-c", "user.email=tokenmessung@example.invalid", "commit", "-q", "-m", "run snapshot"],
        cwd=workdir,
        check=True,
    )


def remove_control_instructions(workdir: Path) -> None:
    for relative in ("AGENTS.md", ".codex", ".codex-project"):
        target = workdir / relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def install_agents_file(workdir: Path, agents_file: Path) -> None:
    shutil.copy2(agents_file, workdir / "AGENTS.md")


def write_output_schema(run_dir: Path) -> Path:
    schema_path = run_dir / "output_schema.json"
    schema_path.write_text(json.dumps(OUTPUT_SCHEMA, indent=2) + "\n", encoding="utf-8")
    return schema_path


def run_one(
    *,
    fixture: Path,
    agents_file: Path,
    model: str,
    out: Path,
    task: dict[str, Any],
    variant: str,
    repeat: int,
    run_order: int,
    keep_workdirs: bool = False,
) -> None:
    run_id = f"{task['id']}__{variant}__r{repeat}"
    run_dir = out / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    workspace_parent = Path(tempfile.mkdtemp(prefix=f"tokenmessung-{run_id}-"))
    workdir = workspace_parent / "repo"
    copy_fixture(fixture, workdir)
    if variant == "control":
        remove_control_instructions(workdir)
    elif variant == "agents":
        install_agents_file(workdir, agents_file)
    else:
        raise ValueError(f"Unknown variant: {variant}")

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
        "agents_file": str(agents_file),
        "agents_file_bytes": agents_file.stat().st_size,
        "workdir": str(workdir),
        "workspace_parent": str(workspace_parent),
        "codex_home": str(codex_home),
        "codex_version": codex_version(),
        "python_version": sys.version.split()[0],
        "codex_command": command,
        "keep_workdirs": keep_workdirs,
        "workdir_cleanup": "pending",
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    started = time.monotonic()
    try:
        with jsonl_path.open("w", encoding="utf-8") as jsonl, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.run(command, cwd=workdir, env=env, text=True, stdout=jsonl, stderr=stderr)
        exit_code_path.write_text(f"{process.returncode}\n", encoding="utf-8")
    finally:
        ended = time.monotonic()
        time_path.write_text(json.dumps({"wall_seconds": ended - started}, indent=2) + "\n", encoding="utf-8")
        if keep_workdirs:
            meta["workdir_cleanup"] = "kept"
        else:
            shutil.rmtree(workspace_parent, ignore_errors=True)
            meta["workdir_cleanup"] = "removed" if not workspace_parent.exists() else "failed"
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def run_benchmark(fixture: Path, agents_file: Path, model: str, repeats: int, out: Path, seed: int | None = None, keep_workdirs: bool = False) -> dict[str, Path]:
    validate_benchmark_inputs(fixture, agents_file, repeats)
    out.mkdir(parents=True, exist_ok=True)
    randomizer = random.Random(seed)
    run_order = 0
    for repeat in range(1, repeats + 1):
        for task in TASKS:
            variants = ["control", "agents"]
            randomizer.shuffle(variants)
            for variant in variants:
                run_order += 1
                run_one(
                    fixture=fixture,
                    agents_file=agents_file,
                    model=model,
                    out=out,
                    task=task,
                    variant=variant,
                    repeat=repeat,
                    run_order=run_order,
                    keep_workdirs=keep_workdirs,
                )
    return analyze_results(out)


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
        "codex_version": "synthetic",
        "python_version": sys.version.split()[0],
        "codex_command": [],
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
