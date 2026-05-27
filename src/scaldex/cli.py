from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .app import main as app_main
from .multisummary import format_multi_summary_console, summarize_results
from .result_console import load_result_json, print_result
from .runner import doctor


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
    if args.command == "result" and args.result_command == "show":
        result_path = args.result_json.resolve()
        print_result(load_result_json(result_path), result_dir=result_path.parent)
        return 0
    parser.error("Unhandled command")
    return 2
