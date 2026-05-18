from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analyzer import codex_forbidden_action, codex_requested_action, decision_summary, explain_warning, human_bytes


def format_delta(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.1f}"


def load_result_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(
            f"Missing result file: {path}\n"
            "Pass an existing tokenmessung-run/result.json, or run a smoke test first to create one."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid result JSON: {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid result JSON: expected object in {path}")
    return payload


ARTIFACT_FILENAMES = {
    "result_md": "RESULT.md",
    "result_json": "result.json",
    "codex_handoff_md": "CODEX_HANDOFF.md",
    "summary_csv": "summary.csv",
    "summary_json": "summary.json",
    "paired_deltas_csv": "paired-deltas.csv",
}


def artifact_path(result: dict[str, object], key: str, result_dir: Path | None = None) -> str | None:
    filename = ARTIFACT_FILENAMES.get(key)
    if result_dir is not None and filename:
        sibling = result_dir / filename
        if sibling.is_file():
            return str(sibling)
    artifacts = result.get("artifacts", {})
    if isinstance(artifacts, dict):
        raw = artifacts.get(key)
        if isinstance(raw, str) and raw:
            return raw
    if result_dir is not None and filename:
        return str(result_dir / filename)
    return None


def what_to_do_now(decision: dict[str, Any], *, synthetic: bool = False) -> str:
    if synthetic:
        return "Use this only for Tokenmessung development or CI checks. It does not measure your AGENTS.md or .codex package."
    next_action = decision.get("next_action")
    scope = decision.get("scope", "task")
    if next_action == "eligible_for_decision_run":
        if scope == "result_set":
            return "Give the Codex handoff to Codex, or run the same task set with --repeats 3 before trusting the result."
        return "Give the Codex handoff to Codex, or run this same task with --repeats 3 before trusting the result."
    if next_action == "stop_fix_quality_or_task_behavior":
        return "Give the Codex handoff to Codex to fix quality, expected-file, structured-output, warning, or path issues before spending more money."
    if next_action == "record_decision_grade_win":
        if scope == "result_set":
            return "Give the Codex handoff to Codex to record this evidence and check global claim eligibility."
        return "Give the Codex handoff to Codex to compare this win with other decision-grade task reports before making a global claim."
    if next_action == "do_not_claim_efficiency":
        if scope == "result_set":
            return "Give the Codex handoff to Codex to inspect task-level behaviour before changing the package or rerunning paid tests."
        return "Give the Codex handoff to Codex to inspect task behaviour before changing the package or rerunning paid tests."
    return "Inspect the report before deciding whether another paid run is justified."


def print_result(result: dict[str, object], *, compare_history_command: str | None = None, result_dir: Path | None = None) -> None:
    primary = result.get("primary_delta", {})
    quality = result.get("quality", {})
    benchmark_warnings = result.get("benchmark_warnings", result.get("warnings", []))
    artifacts = result.get("artifacts", {})
    subject = result.get("subject", {})
    final_relevant = result.get("final_relevant_files", {})
    reliability = result.get("reliability", {})
    tool_sanity = result.get("tool_sanity", {})
    integrity = result.get("integrity", {})
    decision = result.get("decision", {})
    if not isinstance(decision, dict) or not decision:
        decision = decision_summary(result)
        result["decision"] = decision
    synthetic = isinstance(subject, dict) and subject.get("mode") == "synthetic"
    display_explanation = (
        "This is synthetic Tokenmessung test data. It is useful for development checks only, not as real benchmark evidence."
        if synthetic
        else decision.get("explanation", "unknown")
    )
    percent = primary.get("percent") if isinstance(primary, dict) else None
    percent_text = "n/a" if percent is None else f"{float(percent):+.1f}%"
    print("\n=== Tokenmessung Result ===")
    print(f"Result type: {'developer/CI synthetic fixture' if synthetic else 'real benchmark report'}")
    print(f"Verdict: {result.get('verdict', 'unknown')}")
    print(f"What this means: {display_explanation}")
    print(f"What to do now: {what_to_do_now(decision, synthetic=synthetic)}")
    codex_handoff = artifact_path(result, "codex_handoff_md", result_dir)
    print("Codex instruction:")
    if codex_handoff:
        print(f"Give this to Codex: {codex_handoff}")
    else:
        print("Give this to Codex: CODEX_HANDOFF.md was not found beside this result.")
    print(f"Codex should: {codex_requested_action(result)}")
    print(f"Codex must not: {codex_forbidden_action(result)}")
    isolation = result.get("isolation", {})
    if isinstance(isolation, dict):
        print(f"Isolation: ~/.codex excluded = {isolation.get('home_codex_excluded', False)}")
    if isinstance(subject, dict):
        print(f"Subject: {subject.get('mode', 'n/a')} / {format_delta(subject.get('source_file_count'))} files / {human_bytes(subject.get('total_bytes'))} ({format_delta(subject.get('total_bytes'))} bytes)")
        if subject.get("mode") == "synthetic":
            print("Report note: synthetic Tokenmessung test data; development and CI checks only.")
    if isinstance(integrity, dict):
        print(f"Batch: {integrity.get('batch_id', 'n/a')}")
        print(f"Subject fingerprint: {integrity.get('subject_fingerprint', 'n/a')}")
        print(f"Run config fingerprint: {integrity.get('run_config_fingerprint', 'n/a')}")
    if isinstance(primary, dict):
        print(f"Paired median non-cached input delta: {format_delta(primary.get('agents_minus_control'))} ({percent_text})")
        print(
            "Variant medians: agents {agents} / control {control}".format(
                agents=format_delta(primary.get("agents_median")),
                control=format_delta(primary.get("control_median")),
            )
        )
    if isinstance(quality, dict):
        print(f"Quality: agents {quality.get('agents_success_rate', 'n/a')} / control {quality.get('control_success_rate', 'n/a')}")
    if isinstance(final_relevant, dict):
        print(f"Repo-relative relevant_files only: {final_relevant.get('repo_relative_only', False)}")
        print(f"Normalized repo-relative relevant_files only: {final_relevant.get('normalized_repo_relative_only', False)}")
    if isinstance(reliability, dict):
        paired_runs = reliability.get("paired_runs", "n/a")
        level = reliability.get("level", "n/a")
        print(f"Reliability: {level} ({paired_runs} paired run(s))")
        for warning in reliability.get("warnings", []):
            print(f"- {warning}: {explain_warning(str(warning))}")
    if isinstance(tool_sanity, dict):
        print(
            "Tool sanity: schema v{schema}; isolation reporting={isolation}; separated warnings={warnings}; aggregated output={output}".format(
                schema=tool_sanity.get("schema_version", "n/a"),
                isolation=tool_sanity.get("run_isolation_reporting", False),
                warnings=tool_sanity.get("separated_warning_sections", False),
                output=tool_sanity.get("aggregated_command_output_counted", False),
            )
        )
    if benchmark_warnings:
        print("Benchmark warnings:")
        for warning in benchmark_warnings:
            print(f"- {warning}: {explain_warning(str(warning))}")
    else:
        print("Benchmark warnings: none")
    if isinstance(subject, dict):
        subject_warnings = subject.get("warnings", [])
        if subject_warnings:
            print(f"Subject notes: {len(subject_warnings)} note(s); see RESULT.md for details.")
    print("Report files:")
    print(f"- Human report: {artifact_path(result, 'result_md', result_dir)}")
    print(f"- Machine report: {artifact_path(result, 'result_json', result_dir)}")
    if codex_handoff:
        print(f"- Codex handoff: {codex_handoff}")
    if compare_history_command:
        print(f"Compare history: {compare_history_command}")
    print()
