#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "src"))

from tokenmessung.fixture import create_fixture  # noqa: E402
from tokenmessung.runner import run_benchmark  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Codex AGENTS token benchmark.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--subject-dir", type=Path, default=Path("subject"))
    parser.add_argument("--run-dir", type=Path, default=Path("tokenmessung-run"))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    return parser


def ensure_api_key() -> None:
    if os.environ.get("CODEX_API_KEY"):
        return
    key = getpass.getpass("CODEX_API_KEY: ")
    if not key:
        raise SystemExit("CODEX_API_KEY is required.")
    os.environ["CODEX_API_KEY"] = key


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path.cwd().resolve()
    subject_dir = (root / args.subject_dir).resolve()
    if not (subject_dir / "AGENTS.md").is_file():
        raise SystemExit(f"Missing required file: {subject_dir / 'AGENTS.md'}")

    run_dir = (root / args.run_dir).resolve()
    fixture_dir = run_dir / "fixture"
    results_dir = run_dir / "results"
    workspaces_dir = run_dir / "workspaces"
    report_path = run_dir / "report.json"

    ensure_api_key()
    create_fixture(fixture_dir, force=True)
    outputs = run_benchmark(
        fixture_dir,
        None,
        args.model,
        args.repeats,
        results_dir,
        seed=args.seed,
        agents_dir=subject_dir,
        workspace_root=workspaces_dir,
    )
    summary = json.loads(outputs["summary_json"].read_text(encoding="utf-8"))
    report = {
        "model": args.model,
        "repeats": args.repeats,
        "seed": args.seed,
        "subject_dir": str(subject_dir),
        "fixture_dir": str(fixture_dir),
        "results_dir": str(results_dir),
        "workspaces_dir": str(workspaces_dir),
        "outputs": {key: str(value) for key, value in outputs.items()},
        "summary": summary,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), **report["outputs"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
