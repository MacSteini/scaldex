from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analyzer import decision_summary, explain_warning, human_bytes


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


def what_to_do_now(decision: dict[str, Any], *, synthetic: bool = False) -> str:
    if synthetic:
        return "Use this only for Tokenmessung development or CI checks. It does not measure your AGENTS.md or .codex package."
    next_action = decision.get("next_action")
    scope = decision.get("scope", "task")
    if next_action == "eligible_for_decision_run":
        if scope == "result_set":
            return "Run the same task set with --repeats 3 before trusting the result as decision-grade evidence."
        return "Run this same task with --repeats 3 before trusting the result as decision-grade evidence."
    if next_action == "stop_fix_quality_or_task_behavior":
        return "Stop here. Fix the quality, expected-file, structured-output, warning, or path issue before spending more money."
    if next_action == "record_decision_grade_win":
        if scope == "result_set":
            return "Keep this as decision-grade evidence, then summarize all decision-grade task reports before making a global claim."
        return "Keep this report as a decision-grade win, then compare it with other decision-grade task reports before making a global claim."
    if next_action == "do_not_claim_efficiency":
        if scope == "result_set":
            return "Do not claim efficiency from this result set. Inspect the task-level reports before changing the package or rerunning paid tests."
        return "Do not claim efficiency from this task. Inspect the task behavior before changing the package or rerunning paid tests."
    return "Inspect the report before deciding whether another paid run is justified."


def print_result(result: dict[str, object], *, compare_history_command: str | None = None) -> None:
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
    if isinstance(artifacts, dict):
        print(f"Human report: {artifacts.get('result_md')}")
        print(f"Machine report: {artifacts.get('result_json')}")
        if artifacts.get("codex_handoff_md"):
            print(f"Codex handoff: {artifacts.get('codex_handoff_md')}")
    if compare_history_command:
        print(f"Compare history: {compare_history_command}")
    print()
