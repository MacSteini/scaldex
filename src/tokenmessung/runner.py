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
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
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
    started = time.monotonic()
    with jsonl_path.open("w", encoding="utf-8") as jsonl, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.run(command, cwd=workdir, env=env, text=True, stdout=jsonl, stderr=stderr)
    ended = time.monotonic()
    exit_code_path.write_text(f"{process.returncode}\n", encoding="utf-8")
    time_path.write_text(json.dumps({"wall_seconds": ended - started}, indent=2) + "\n", encoding="utf-8")


def run_benchmark(fixture: Path, agents_file: Path, model: str, repeats: int, out: Path, seed: int | None = None) -> dict[str, Path]:
    if "CODEX_API_KEY" not in os.environ:
        raise EnvironmentError("CODEX_API_KEY is required for benchmark runs")
    if not fixture.exists():
        raise FileNotFoundError(f"Fixture does not exist: {fixture}")
    if not agents_file.is_file():
        raise FileNotFoundError(f"AGENTS file does not exist: {agents_file}")
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
                )
    return analyze_results(out)


def doctor() -> dict[str, Any]:
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "git": shutil.which("git") is not None,
        "codex": shutil.which("codex") is not None,
        "codex_version": codex_version(),
        "codex_api_key_present": bool(os.environ.get("CODEX_API_KEY")),
        "supports_json": False,
        "supports_output_schema": False,
        "supports_ignore_user_config": False,
        "supports_ignore_rules": False,
    }
    if checks["codex"]:
        try:
            help_text = command_output(["codex", "exec", "--help"])
            checks["supports_json"] = "--json" in help_text
            checks["supports_output_schema"] = "--output-schema" in help_text
            checks["supports_ignore_user_config"] = "--ignore-user-config" in help_text
            checks["supports_ignore_rules"] = "--ignore-rules" in help_text
        except subprocess.CalledProcessError:
            pass
    return checks
