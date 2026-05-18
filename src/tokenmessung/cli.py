from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyzer import analyze_results
from .fixture import create_fixture
from .multisummary import format_multi_summary_console, summarize_results
from .result_console import load_result_json, print_result
from .runner import doctor, run_benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tokenmessung")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fixture_parser = subparsers.add_parser("fixture")
    fixture_subparsers = fixture_parser.add_subparsers(dest="fixture_command", required=True)
    fixture_create = fixture_subparsers.add_parser("create")
    fixture_create.add_argument("--out", required=True, type=Path)
    fixture_create.add_argument("--force", action="store_true")

    bench_parser = subparsers.add_parser("bench")
    bench_subparsers = bench_parser.add_subparsers(dest="bench_command", required=True, metavar="COMMAND")

    run_parser = bench_subparsers.add_parser("run", help="Run a paid benchmark against a prepared fixture and AGENTS source.")
    run_parser.add_argument("--fixture", required=True, type=Path)
    agents_source = run_parser.add_mutually_exclusive_group(required=True)
    agents_source.add_argument("--agents-file", type=Path)
    agents_source.add_argument("--agents-dir", type=Path)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--repeats", type=int, default=5)
    run_parser.add_argument("--out", required=True, type=Path)
    run_parser.add_argument("--seed", type=int)
    run_parser.add_argument("--keep-workdirs", action="store_true")
    run_parser.add_argument("--workspace-root", type=Path)

    analyze_parser = bench_subparsers.add_parser("analyze", help="Analyze an existing raw benchmark result folder.")
    analyze_parser.add_argument("--results", required=True, type=Path)
    analyze_parser.add_argument("--large-text-bytes", type=int, default=20_000)

    summarize_parser = bench_subparsers.add_parser("summarize", help="Summarize existing result.json reports without running Codex.")
    summarize_parser.add_argument("inputs", nargs="+", type=Path)
    summarize_parser.add_argument("--out", required=True, type=Path)
    summarize_parser.add_argument("--json", action="store_true", help="Print machine-readable output paths instead of the human summary.")

    doctor_parser = bench_subparsers.add_parser("doctor", help="Check local Tokenmessung/Codex prerequisites.")
    doctor_parser.add_argument("--require-api-key", action="store_true")

    result_parser = subparsers.add_parser("result")
    result_subparsers = result_parser.add_subparsers(dest="result_command", required=True)
    result_show = result_subparsers.add_parser("show")
    result_show.add_argument("result_json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "fixture" and args.fixture_command == "create":
        path = create_fixture(args.out, force=args.force)
        print(json.dumps({"fixture": str(path)}, indent=2))
        return 0
    if args.command == "bench" and args.bench_command == "run":
        paths = run_benchmark(
            args.fixture,
            args.agents_file,
            args.model,
            args.repeats,
            args.out,
            seed=args.seed,
            keep_workdirs=args.keep_workdirs,
            agents_dir=args.agents_dir,
            workspace_root=args.workspace_root,
        )
        print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
        return 0
    if args.command == "bench" and args.bench_command == "analyze":
        paths = analyze_results(args.results, large_text_bytes=args.large_text_bytes)
        print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
        return 0
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
