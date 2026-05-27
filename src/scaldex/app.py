from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scaldex.fixture import create_fixture  # noqa: E402
from scaldex.analyzer import TOOL_SANITY, explain_warning, human_bytes, write_codex_handoff_markdown  # noqa: E402
from scaldex.result_console import load_result_json, print_result  # noqa: E402
from scaldex.runner import GENERATED_MARKER, audit_subject_source, new_batch_id, run_benchmark  # noqa: E402
from scaldex.schemas import TASKS  # noqa: E402


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scaldex",
        description="Measure whether a Codex instruction package helps or hurts token usage.",
        epilog=(
            "Typical flow:\n"
            "  1. Put AGENTS.md and any support files in subject/.\n"
            "  2. Run a low-cost smoke test: scaldex --model gpt-5.4\n"
            "  3. Read 'What this means' and 'What to do now' as the human control layer.\n"
            "  4. For Codex-assisted follow-up, use scaldex-run/CODEX_HANDOFF.md.\n"
            "  5. Run --repeats 3 only when the handoff or terminal output tells you to.\n"
            "  6. Replay an existing report without spending money: scaldex --print-result scaldex-run/result.json\n\n"
            "scaldex never stores your Codex API key in generated reports. If CODEX_API_KEY is not already set,\n"
            "the tool asks for it at a hidden prompt for each paid command."
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument("--model", help="Codex model for paid benchmark runs. Required unless --print-result is used.")
    parser.add_argument("--subject-dir", type=Path, default=Path("subject"), help="Folder containing the instruction package to measure.")
    parser.add_argument("--run-dir", type=Path, default=Path("scaldex-run"), help="Output folder for the current run report.")
    parser.add_argument("--repeats", type=int, default=1, help="Paired repeats per selected task. Use 1 for smoke, 3+ for decision-grade evidence.")
    parser.add_argument("--seed", type=int, default=1, help="Seed for deterministic task ordering.")
    parser.add_argument("--task-id", action="append", dest="task_ids", help="Task to run. Repeat this option for multiple selected tasks.")
    parser.add_argument("--all-tasks", action="store_true", help="Run every built-in task. This increases paid Codex runs.")
    parser.add_argument("--heartbeat-seconds", type=float, default=10.0, help="Seconds between progress heartbeat messages.")
    parser.add_argument("--max-run-seconds", type=float, default=300.0, help="Maximum seconds before one Codex run is stopped.")
    parser.add_argument("--subject-mode", choices=("package", "agents-md"), default="package", help="Measure the whole package or AGENTS.md only.")
    parser.add_argument("--history-dir", type=Path, default=Path("scaldex-history"), help="Folder for compact archived reports from previous default runs.")
    parser.add_argument("--no-archive-previous-result", action="store_true", help="Do not archive the previous generated run before replacing --run-dir.")
    parser.add_argument("--print-result", type=Path, help="Print an existing result.json without an API key, subject audit, or paid Codex run.")
    return parser


def status(message: str) -> None:
    print(f"[scaldex] {message}", file=sys.stderr, flush=True)


def ensure_api_key() -> str:
    if os.environ.get("CODEX_API_KEY"):
        return "env"
    key = getpass.getpass("[scaldex] Enter Codex API Key: ")
    if not key:
        raise SystemExit("CODEX_API_KEY is required.")
    os.environ["CODEX_API_KEY"] = key
    return "prompt"


def tool_sanity_text() -> str:
    return (
        "Tool sanity: "
        f"schema v{TOOL_SANITY['schema_version']}; "
        f"isolation reporting={'on' if TOOL_SANITY['run_isolation_reporting'] else 'off'}; "
        f"separated warnings={'on' if TOOL_SANITY['separated_warning_sections'] else 'off'}; "
        f"aggregated command output={'on' if TOOL_SANITY['aggregated_command_output_counted'] else 'off'}."
    )


def paths_nested(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def validate_output_layout(root: Path, subject_dir: Path, run_dir: Path, history_dir: Path) -> None:
    if run_dir == root:
        raise SystemExit("Refusing to use the current folder itself as --run-dir.")
    if history_dir == root:
        raise SystemExit("Refusing to use the current folder itself as --history-dir.")
    if paths_nested(subject_dir, run_dir):
        raise SystemExit("Refusing to nest subject/ and --run-dir because cleanup or generated files would make measurements unsafe.")
    if paths_nested(subject_dir, history_dir):
        raise SystemExit("Refusing to place scaldex history inside subject/ because it would pollute future measurements.")
    if paths_nested(run_dir, history_dir):
        raise SystemExit("Refusing to nest --run-dir and --history-dir because archiving or cleanup would be unsafe.")


def reset_run_dir(run_dir: Path, root: Path) -> None:
    default_run_dir = (root / "scaldex-run").resolve()
    if run_dir.exists() and run_dir != default_run_dir and any(run_dir.iterdir()) and not (run_dir / GENERATED_MARKER).exists():
        raise SystemExit(f"Refusing to replace non-scaldex --run-dir without {GENERATED_MARKER}: {run_dir}")
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / GENERATED_MARKER).write_text("generated by scaldex\n", encoding="utf-8")


def safe_slug(value: str) -> str:
    slug = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in value.strip())
    return slug.strip("-") or "run"


def archive_previous_result(run_dir: Path, history_dir: Path) -> Path | None:
    result_json = run_dir / "result.json"
    if not result_json.is_file() or not (run_dir / GENERATED_MARKER).exists():
        return None
    try:
        result = json.loads(result_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        result = {}
    context = result.get("context", {}) if isinstance(result, dict) else {}
    integrity = result.get("integrity", {}) if isinstance(result, dict) else {}
    task_ids = context.get("task_ids", []) if isinstance(context, dict) else []
    if isinstance(task_ids, list) and task_ids:
        task_slug = safe_slug("-".join(str(task_id) for task_id in task_ids))
    else:
        task_slug = "unknown-task"
    batch = str(integrity.get("batch_id", "")) if isinstance(integrity, dict) else ""
    batch_slug = safe_slug(batch[:8] or "no-batch")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_base = history_dir / f"{timestamp}-{task_slug}-{batch_slug}"
    archive_dir = archive_base
    suffix = 2
    while archive_dir.exists():
        archive_dir = history_dir / f"{archive_base.name}-{suffix}"
        suffix += 1
    archive_dir.mkdir(parents=True, exist_ok=False)
    copied: list[str] = []
    for name in ("RESULT.md", "CODEX_HANDOFF.md", "result.json", "summary.csv", "summary.json", "paired-deltas.csv"):
        source = run_dir / name
        if source.is_file():
            shutil.copy2(source, archive_dir / name)
            copied.append(name)
    (archive_dir / GENERATED_MARKER).write_text("archived by scaldex\n", encoding="utf-8")
    (archive_dir / "archive.json").write_text(
        json.dumps({"source_run_dir": str(run_dir), "copied_files": copied}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return archive_dir


def history_compare_command(root: Path, run_dir: Path, history_dir: Path) -> str | None:
    if not history_dir.exists():
        return None
    try:
        history_text = str(history_dir.relative_to(root))
    except ValueError:
        history_text = str(history_dir)
    try:
        run_text = str(run_dir.relative_to(root))
    except ValueError:
        run_text = str(run_dir)
    return f"scaldex bench summarize {history_text} {run_text} --out scaldex-summary"


def render_progress(event: dict[str, object]) -> None:
    event_name = event.get("event")
    if event_name == "benchmark_start":
        status(f"Benchmark starting: {event.get('total_runs')} runs, {event.get('repeats')} repeat(s), {event.get('task_count')} task(s).")
    elif event_name == "run_start":
        status(
            "Run {run_order}/{total_runs} starting: {task_id} [{variant}] repeat {repeat}.".format(
                run_order=event.get("run_order"),
                total_runs=event.get("total_runs"),
                task_id=event.get("task_id"),
                variant=event.get("variant"),
                repeat=event.get("repeat"),
            )
        )
    elif event_name == "run_heartbeat":
        status(f"Run {event.get('run_id')} has been running for {event.get('elapsed_seconds')}s.")
    elif event_name == "run_timeout":
        status(f"Run {event.get('run_id')} stopped after {event.get('max_run_seconds')}s.")
    elif event_name == "run_done":
        status(
            "Run {run_order}/{total_runs} complete: {task_id} [{variant}], exit {exit_code}, {wall_seconds}s.".format(
                run_order=event.get("run_order"),
                total_runs=event.get("total_runs"),
                task_id=event.get("task_id"),
                variant=event.get("variant"),
                exit_code=event.get("exit_code"),
                wall_seconds=event.get("wall_seconds"),
            )
        )
    elif event_name == "analysis_start":
        status("Analysis starting.")
    elif event_name == "analysis_done":
        status("Analysis complete.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_result is not None:
        if args.model or args.task_ids or args.all_tasks:
            raise SystemExit("Use --print-result by itself; it does not run benchmarks.")
        root = Path.cwd().resolve()
        result_path = (root / args.print_result).resolve() if not args.print_result.is_absolute() else args.print_result.resolve()
        result = load_result_json(result_path)
        run_dir = result_path.parent
        history_dir = (root / args.history_dir).resolve()
        print_result(result, compare_history_command=history_compare_command(root, run_dir, history_dir), result_dir=run_dir)
        return 0
    if not args.model:
        raise SystemExit("--model is required unless --print-result is used.")
    if args.all_tasks and args.task_ids:
        raise SystemExit("Use either --all-tasks or --task-id, not both.")
    root = Path.cwd().resolve()
    subject_arg = args.subject_dir.expanduser()
    subject_dir = (subject_arg if subject_arg.is_absolute() else root / subject_arg).resolve()
    if not (subject_dir / "AGENTS.md").is_file():
        raise SystemExit(f"Missing required file: {subject_dir / 'AGENTS.md'}")
    status(f"Subject checked: {subject_dir}")
    agents_file = None
    agents_dir = None
    if args.subject_mode == "package":
        agents_dir = subject_dir
    else:
        agents_file = subject_dir / "AGENTS.md"
    subject_audit = audit_subject_source(agents_file, agents_dir, subject_mode=args.subject_mode)
    batch_id = new_batch_id()
    status(
        "Subject audit: {mode}, {files} file(s), size {size}.".format(
            mode=subject_audit["mode"],
            files=subject_audit["file_count"],
            size=f"{human_bytes(subject_audit['total_bytes'])} ({subject_audit['total_bytes']} bytes)",
        )
    )
    largest_files = subject_audit.get("largest_files", [])
    if largest_files:
        top = ", ".join(f"{item['path']} ({human_bytes(item['bytes'])}, {item['bytes']} bytes)" for item in largest_files[:3])
        status(f"Largest subject files: {top}.")
    warnings = subject_audit.get("warnings", [])
    if warnings:
        status("Subject warnings:")
        for warning in warnings:
            status(f"- {warning}: {explain_warning(str(warning))}")

    run_dir = (root / args.run_dir).resolve()
    history_dir = (root / args.history_dir).resolve()
    validate_output_layout(root, subject_dir, run_dir, history_dir)
    raw_dir = run_dir / "raw"
    fixture_dir = raw_dir / "fixture"
    results_dir = raw_dir / "results"
    workspaces_dir = raw_dir / "workspaces"
    task_ids = None if args.all_tasks else (args.task_ids or [TASKS[0]["id"]])
    planned_task_count = len(TASKS) if task_ids is None else len(task_ids)
    planned_runs = args.repeats * planned_task_count * 2
    status(tool_sanity_text())
    status(f"Batch ID: {batch_id}")
    status(f"Subject fingerprint: {subject_audit.get('fingerprint', 'n/a')}")
    status(f"Planned paid Codex runs: {planned_runs} ({planned_task_count} task(s) x {args.repeats} repeat(s) x 2 variants).")

    key_source = ensure_api_key()
    status("API key detected in environment." if key_source == "env" else "API key entered locally.")
    status("Run isolation: dedicated CODEX_HOME per run; ~/.codex is not measured as an instruction source.")
    archived = None
    if run_dir.exists():
        if not args.no_archive_previous_result:
            archived = archive_previous_result(run_dir, history_dir)
            if archived is not None:
                status(f"Archived previous compact report: {archived}")
        status(f"Replacing previous run folder: {run_dir}")
    reset_run_dir(run_dir, root)
    if task_ids is None:
        status("Task selection: all tasks.")
    else:
        status(f"Task selection: {', '.join(task_ids)}.")
    status(f"Creating fixture: {fixture_dir}")
    create_fixture(fixture_dir, force=True)
    status(f"Fixture ready. Planned runs: {planned_runs}")
    started = time.monotonic()
    outputs = run_benchmark(
        fixture_dir,
        agents_file,
        args.model,
        args.repeats,
        results_dir,
        seed=args.seed,
        agents_dir=agents_dir,
        workspace_root=workspaces_dir,
        progress=render_progress,
        heartbeat_interval=args.heartbeat_seconds,
        max_run_seconds=args.max_run_seconds,
        task_ids=task_ids,
        analysis_dir=run_dir,
        subject_mode=args.subject_mode,
        batch_id=batch_id,
    )
    result = json.loads(outputs["result_json"].read_text(encoding="utf-8"))
    result["run_config"] = {
        "all_tasks": args.all_tasks,
        "heartbeat_seconds": args.heartbeat_seconds,
        "max_run_seconds": args.max_run_seconds,
        "model": args.model,
        "repeats": args.repeats,
        "seed": args.seed,
        "subject_mode": args.subject_mode,
        "subject_dir": str(subject_dir),
        "task_ids": task_ids,
    }
    result["artifacts"]["raw_dir"] = str(raw_dir)
    outputs["result_json"].write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_codex_handoff_markdown(outputs["codex_handoff_md"], result)
    status(f"Report ready after {round(time.monotonic() - started, 1)}s: {outputs['result_md']}")
    print_result(result, compare_history_command=history_compare_command(root, run_dir, history_dir) if archived is not None else None, result_dir=run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
