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

    summarize_parser = bench_subparsers.add_parser("summarize", help="Summarize existing result.json reports without running Codex.")
    summarize_parser.add_argument("inputs", nargs="+", type=Path)
    summarize_parser.add_argument("--out", required=True, type=Path)
    summarize_parser.add_argument("--json", action="store_true", help="Print machine-readable output paths instead of the human summary.")

    doctor_parser = bench_subparsers.add_parser("doctor", help="Check local scaldex/Codex prerequisites.")
    doctor_parser.add_argument("--require-api-key", action="store_true")

    result_parser = subparsers.add_parser("result")
    result_subparsers = result_parser.add_subparsers(dest="result_command", required=True)
    result_show = result_subparsers.add_parser("show")
    result_show.add_argument("result_json", type=Path)
    return parser


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
            raise SystemExit(f"Cannot summarize results: {exc}") from exc
        if args.json:
            print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
        else:
            summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
            print(format_multi_summary_console(summary, paths))
        return 0
    if args.command == "bench" and args.bench_command == "doctor":
        checks = doctor()
        print(json.dumps(checks, indent=2, sort_keys=True))
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
