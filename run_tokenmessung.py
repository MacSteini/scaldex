#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "src"))

from tokenmessung.fixture import create_fixture  # noqa: E402
from tokenmessung.runner import run_benchmark  # noqa: E402
from tokenmessung.schemas import TASKS  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Codex AGENTS token benchmark.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--subject-dir", type=Path, default=Path("subject"))
    parser.add_argument("--run-dir", type=Path, default=Path("tokenmessung-run"))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--all-tasks", action="store_true")
    parser.add_argument("--heartbeat-seconds", type=float, default=10.0)
    parser.add_argument("--max-run-seconds", type=float, default=300.0)
    return parser


def status(message: str) -> None:
    print(f"[tokenmessung] {message}", file=sys.stderr, flush=True)


def ensure_api_key() -> str:
    if os.environ.get("CODEX_API_KEY"):
        return "env"
    key = getpass.getpass("CODEX_API_KEY: ")
    if not key:
        raise SystemExit("CODEX_API_KEY is required.")
    os.environ["CODEX_API_KEY"] = key
    return "prompt"


def render_progress(event: dict[str, object]) -> None:
    event_name = event.get("event")
    if event_name == "benchmark_start":
        status(f"Benchmark startet: {event.get('total_runs')} Runs, {event.get('repeats')} Repeat(s), {event.get('task_count')} Tasks.")
    elif event_name == "run_start":
        status(
            "Run {run_order}/{total_runs} startet: {task_id} [{variant}] Repeat {repeat}.".format(
                run_order=event.get("run_order"),
                total_runs=event.get("total_runs"),
                task_id=event.get("task_id"),
                variant=event.get("variant"),
                repeat=event.get("repeat"),
            )
        )
    elif event_name == "run_heartbeat":
        status(f"Run {event.get('run_id')} läuft seit {event.get('elapsed_seconds')}s.")
    elif event_name == "run_timeout":
        status(f"Run {event.get('run_id')} nach {event.get('max_run_seconds')}s beendet.")
    elif event_name == "run_done":
        status(
            "Run {run_order}/{total_runs} fertig: {task_id} [{variant}], Exit {exit_code}, {wall_seconds}s.".format(
                run_order=event.get("run_order"),
                total_runs=event.get("total_runs"),
                task_id=event.get("task_id"),
                variant=event.get("variant"),
                exit_code=event.get("exit_code"),
                wall_seconds=event.get("wall_seconds"),
            )
        )
    elif event_name == "analysis_start":
        status("Analyse startet.")
    elif event_name == "analysis_done":
        status("Analyse fertig.")


def format_delta(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.1f}"


def print_result(result: dict[str, object]) -> None:
    primary = result.get("primary_delta", {})
    quality = result.get("quality", {})
    warnings = result.get("warnings", [])
    artifacts = result.get("artifacts", {})
    percent = primary.get("percent") if isinstance(primary, dict) else None
    percent_text = "n/a" if percent is None else f"{float(percent):+.1f}%"
    print("\n=== Tokenmessung Ergebnis ===")
    print(f"Verdict: {result.get('verdict', 'unknown')}")
    if isinstance(primary, dict):
        print(f"Non-cached input delta: {format_delta(primary.get('agents_minus_control'))} ({percent_text})")
    if isinstance(quality, dict):
        print(f"Quality: agents {quality.get('agents_success_rate', 'n/a')} / control {quality.get('control_success_rate', 'n/a')}")
    if warnings:
        print("Warnings: " + ", ".join(str(warning) for warning in warnings))
    else:
        print("Warnings: none")
    if isinstance(artifacts, dict):
        print(f"Human report: {artifacts.get('result_md')}")
        print(f"Machine report: {artifacts.get('result_json')}")
    print()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.all_tasks and args.task_ids:
        raise SystemExit("Use either --all-tasks or --task-id, not both.")
    root = Path.cwd().resolve()
    subject_dir = (root / args.subject_dir).resolve()
    if not (subject_dir / "AGENTS.md").is_file():
        raise SystemExit(f"Missing required file: {subject_dir / 'AGENTS.md'}")
    status(f"Subject geprüft: {subject_dir}")

    run_dir = (root / args.run_dir).resolve()
    raw_dir = run_dir / "raw"
    fixture_dir = raw_dir / "fixture"
    results_dir = raw_dir / "results"
    workspaces_dir = raw_dir / "workspaces"

    key_source = ensure_api_key()
    status("API-Key aus Umgebung erkannt." if key_source == "env" else "API-Key lokal eingegeben.")
    task_ids = None if args.all_tasks else (args.task_ids or [TASKS[0]["id"]])
    if task_ids is None:
        status("Task-Auswahl: alle Tasks.")
    else:
        status(f"Task-Auswahl: {', '.join(task_ids)}.")
    status(f"Fixture wird erstellt: {fixture_dir}")
    create_fixture(fixture_dir, force=True)
    planned_task_count = len(TASKS) if task_ids is None else len(task_ids)
    status(f"Fixture fertig. Geplante Runs: {args.repeats * planned_task_count * 2}")
    started = time.monotonic()
    outputs = run_benchmark(
        fixture_dir,
        None,
        args.model,
        args.repeats,
        results_dir,
        seed=args.seed,
        agents_dir=subject_dir,
        workspace_root=workspaces_dir,
        progress=render_progress,
        heartbeat_interval=args.heartbeat_seconds,
        max_run_seconds=args.max_run_seconds,
        task_ids=task_ids,
        analysis_dir=run_dir,
    )
    result = json.loads(outputs["result_json"].read_text(encoding="utf-8"))
    result["run_config"] = {
        "all_tasks": args.all_tasks,
        "heartbeat_seconds": args.heartbeat_seconds,
        "max_run_seconds": args.max_run_seconds,
        "model": args.model,
        "repeats": args.repeats,
        "seed": args.seed,
        "subject_dir": str(subject_dir),
        "task_ids": task_ids,
    }
    result["artifacts"]["raw_dir"] = str(raw_dir)
    outputs["result_json"].write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status(f"Report fertig nach {round(time.monotonic() - started, 1)}s: {outputs['result_md']}")
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
