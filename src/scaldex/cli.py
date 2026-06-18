from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .app import main as app_main
from .analyzer import explain_warning, human_bytes
from .multisummary import format_multi_summary_console, summarize_results
from .result_console import display_path, load_result_json, print_result
from .runner import audit_subject_source, doctor, find_instruction_entry_file, reject_subject_symlink_path


def build_utility_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scaldex",
        description="Run scaldex utility commands for existing reports and local prerequisite checks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bench_parser = subparsers.add_parser("bench")
    bench_subparsers = bench_parser.add_subparsers(dest="bench_command", required=True, metavar="COMMAND")

    summarize_parser = bench_subparsers.add_parser("summarize", help="Summarise existing result.json reports without running Codex.")
    summarize_parser.add_argument("inputs", nargs="+", type=Path)
    summarize_parser.add_argument("--out", required=True, type=Path)
    summarize_parser.add_argument("--json", action="store_true", help="Print machine-readable output paths instead of the human summary.")

    doctor_parser = bench_subparsers.add_parser("doctor", help="Check local scaldex/Codex prerequisites.")
    doctor_parser.add_argument("--require-api-key", action="store_true")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable prerequisite details.")

    inspect_parser = bench_subparsers.add_parser("inspect-subject", help="Inspect a subject package without running Codex.")
    inspect_parser.add_argument("--subject-dir", type=Path, default=Path("subject"), help="Folder containing the instruction package to inspect.")
    inspect_parser.add_argument("--subject-mode", choices=("package", "agents-md"), default="package", help="Inspect the whole package or only the instruction entry file.")
    inspect_parser.add_argument("--json", action="store_true", help="Print machine-readable subject audit details.")

    result_parser = subparsers.add_parser(
        "result",
        help="Replay existing result reports without running Codex.",
        description="Replay existing result reports without running Codex.",
    )
    result_subparsers = result_parser.add_subparsers(dest="result_command", required=True)
    result_show = result_subparsers.add_parser("show", help="Show an existing result.json as the standard scaldex result output.")
    result_show.add_argument("result_json", type=Path, help="Path to an existing scaldex result.json file.")
    return parser


def format_doctor_console(checks: dict[str, object], *, require_api_key: bool = False) -> str:
    capabilities = [
        bool(checks.get("supports_json")),
        bool(checks.get("supports_output_schema")),
        bool(checks.get("supports_ignore_user_config")),
        bool(checks.get("supports_ignore_rules")),
    ]
    required_ok = bool(checks.get("git")) and bool(checks.get("codex")) and all(capabilities)
    api_key_present = bool(checks.get("codex_api_key_present"))
    ready = required_ok and (api_key_present or not require_api_key)
    lines = [
        "",
        "=== scaldex doctor ===",
        f"Ready for paid benchmark runs: {'yes' if ready else 'no'}",
        f"Codex CLI: {'found' if checks.get('codex') else 'missing'} ({checks.get('codex_version') or 'version unavailable'})",
        f"Git: {'found' if checks.get('git') else 'missing'}",
        f"Python: {checks.get('python', 'unknown')}",
        f"Codex API key: {'available in this shell' if api_key_present else 'not set; scaldex will ask at the hidden prompt when you run a paid benchmark'}",
        f"Required Codex exec capabilities: {'available' if all(capabilities) else 'missing'}",
    ]
    if require_api_key and not api_key_present:
        lines.append("What to do now: set CODEX_API_KEY or run without --require-api-key if you only want to check local tooling.")
    elif ready:
        lines.append("What to do now: run a smoke benchmark when you are ready to spend API money.")
    else:
        lines.append("What to do now: install or update the missing local prerequisites before running a paid benchmark.")
    lines.append("")
    return "\n".join(lines)


def display_input_path(raw: Path, resolved: Path) -> str:
    if not raw.is_absolute():
        return str(raw)
    return display_path(str(resolved)) or str(raw)


def inspect_subject(subject_dir: Path, subject_mode: str) -> dict[str, object]:
    subject_arg = subject_dir.expanduser()
    subject_guard_path = subject_arg if subject_arg.is_absolute() else Path.cwd() / subject_arg
    subject_guard_display = display_input_path(subject_arg, subject_guard_path)
    try:
        reject_subject_symlink_path(subject_guard_path, subject_guard_display)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    resolved_subject = (subject_arg if subject_arg.is_absolute() else Path.cwd() / subject_arg).resolve()
    subject_display = display_input_path(subject_arg, resolved_subject)
    entry_file = find_instruction_entry_file(resolved_subject)
    if entry_file is None:
        raise SystemExit(f"Missing required file: {subject_display}/AGENTS.md or {subject_display}/AGENTS.override.md")
    agents_file = entry_file if subject_mode == "agents-md" else None
    agents_dir = resolved_subject if subject_mode == "package" else None
    try:
        audit = audit_subject_source(agents_file, agents_dir, subject_mode=subject_mode)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    audit = dict(audit)
    audit["path"] = subject_display
    audit["entry_file"] = entry_file.name
    audit["entry_path"] = f"{subject_display.rstrip('/')}/{entry_file.name}"
    audit["paid_run_started"] = False
    return audit


def format_subject_inspection(audit: dict[str, object]) -> str:
    warnings = audit.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    largest_files = audit.get("largest_files", [])
    lines = [
        "",
        "=== scaldex subject inspection ===",
        "Paid benchmark runs: no",
        "Codex API key required: no",
        f"Subject: {audit.get('path', 'subject')}",
        f"Entry file: {audit.get('entry_file', 'n/a')}",
        f"Mode: {audit.get('mode', 'n/a')}",
        "Included files: {files}".format(files=audit.get("file_count", 0)),
        "Included size: {size} ({bytes} bytes)".format(size=human_bytes(audit.get("total_bytes", 0)), bytes=audit.get("total_bytes", 0)),
        f"Subject fingerprint: {audit.get('fingerprint', 'n/a')}",
    ]
    if isinstance(largest_files, list) and largest_files:
        lines.append("Largest files:")
        for item in largest_files[:5]:
            if isinstance(item, dict):
                path = item.get("path", "n/a")
                size = item.get("bytes", 0)
                lines.append(f"- {path}: {human_bytes(size)} ({size} bytes)")
    if warnings:
        lines.append("Subject warnings:")
        for warning in warnings:
            lines.append(f"- {warning}: {explain_warning(str(warning))}")
    else:
        lines.append("Subject warnings: none")
    lines.append("What to do now: choose this subject mode for a paid smoke run only when this is the package shape you want to measure.")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    return build_utility_parser()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"bench", "result"}:
        return app_main(argv)
    parser = build_utility_parser()
    args = parser.parse_args(argv)
    if args.command == "bench" and args.bench_command == "summarize":
        try:
            paths = summarize_results(args.inputs, args.out)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(f"Cannot summarise results: {exc}") from exc
        if args.json:
            print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
        else:
            summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
            print(format_multi_summary_console(summary, paths))
        return 0
    if args.command == "bench" and args.bench_command == "doctor":
        checks = doctor()
        if args.json:
            print(json.dumps(checks, indent=2, sort_keys=True))
        else:
            print(format_doctor_console(checks, require_api_key=args.require_api_key))
        required = ["git", "codex", "supports_json", "supports_output_schema", "supports_ignore_user_config", "supports_ignore_rules"]
        if args.require_api_key:
            required.append("codex_api_key_present")
        return 0 if all(checks.get(key) for key in required) else 1
    if args.command == "bench" and args.bench_command == "inspect-subject":
        audit = inspect_subject(args.subject_dir, args.subject_mode)
        if args.json:
            print(json.dumps(audit, indent=2, sort_keys=True))
        else:
            print(format_subject_inspection(audit))
        return 0
    if args.command == "result" and args.result_command == "show":
        result_path = args.result_json.resolve()
        print_result(load_result_json(result_path), result_dir=result_path.parent)
        return 0
    parser.error("Unhandled command")
    return 2
