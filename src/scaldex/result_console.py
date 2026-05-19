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


def format_percent(value: object) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def load_result_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(
            f"Missing result file: {path}\n"
            "Run a smoke test to create a result.json, or pass the exact result.json file you want to replay."
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
        return "Use this only for scaldex development or CI checks. It does not measure your AGENTS.md or .codex package."
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


def handoff_purpose(decision: dict[str, Any]) -> str:
    next_action = decision.get("next_action")
    if next_action == "eligible_for_decision_run":
        return "Codex gets the exact decision-run request and should not optimize yet."
    if next_action == "stop_fix_quality_or_task_behavior":
        return "Codex gets the quality or output blockers to fix before any more paid runs."
    if next_action == "record_decision_grade_win":
        return "Codex gets a decision-grade win to record and compare against other reports."
    if next_action == "do_not_claim_efficiency":
        return "Codex gets the task result to diagnose why this did not prove efficiency."
    return "Codex gets the report context and should ask for missing evidence before acting."


def handoff_safety_boundary(decision: dict[str, Any]) -> str:
    next_action = decision.get("next_action")
    if next_action == "eligible_for_decision_run":
        return "Smoke evidence only; no AGENTS.md/.codex changes and no efficiency claim."
    if next_action == "stop_fix_quality_or_task_behavior":
        return "Quality or integrity blockers override token savings."
    if next_action == "record_decision_grade_win":
        return "No global claim unless enough decision-grade task reports support it."
    if next_action == "do_not_claim_efficiency":
        return "No efficiency claim and no broad rewrites."
    return "No claims from missing evidence and no decisions from variant medians alone."


def primary_metric_sentence(primary: dict[str, Any]) -> str:
    delta = primary.get("agents_minus_control")
    percent = format_percent(primary.get("percent"))
    try:
        numeric = float(delta)
    except (TypeError, ValueError):
        return "Primary metric: non-cached input token delta is unavailable in this report."
    amount = format_delta(abs(numeric))
    if numeric < 0:
        return f"Primary metric: agents used {amount} fewer non-cached input tokens than control ({percent})."
    if numeric > 0:
        return f"Primary metric: agents used {amount} more non-cached input tokens than control ({percent})."
    return f"Primary metric: agents and control used the same paired median non-cached input tokens ({percent})."


def variant_medians_sentence(primary: dict[str, Any]) -> str:
    return (
        "Secondary context only: agents median {agents}, control median {control}; "
        "this is not the decision metric."
    ).format(
        agents=format_delta(primary.get("agents_median")),
        control=format_delta(primary.get("control_median")),
    )


def quality_sentence(quality: dict[str, Any]) -> str:
    agents = quality.get("agents_success_rate", "n/a")
    control = quality.get("control_success_rate", "n/a")
    if agents == 1.0 and control == 1.0:
        return f"Both sides completed all required runs successfully: agents success rate 100% ({agents}), control success rate 100% ({control})."
    return f"Quality gate needs attention: agents success rate {agents}, control success rate {control}."


def subject_sentence(subject: dict[str, Any]) -> str:
    mode = subject.get("mode", "n/a")
    files = format_delta(subject.get("source_file_count"))
    size = human_bytes(subject.get("total_bytes"))
    bytes_text = format_delta(subject.get("total_bytes"))
    return f"Measured subject: {mode} with {files} file(s), {size} ({bytes_text} bytes)."


def isolation_sentence(isolation: dict[str, Any]) -> str:
    if isolation.get("home_codex_excluded", False):
        return "This run excluded your global ~/.codex config, so the subject package was measured in isolation."
    return "This run did not prove that global ~/.codex config was excluded; treat isolation as a blocker before comparing results."


def fingerprints_sentence(integrity: dict[str, Any]) -> str:
    subject_fp = integrity.get("subject_fingerprint", "n/a")
    config_fp = integrity.get("run_config_fingerprint", "n/a")
    batch = integrity.get("batch_id", "n/a")
    return (
        "Report identity: batch {batch}; subject fingerprint {subject}; run config fingerprint {config}. "
        "Use these IDs only when comparing or auditing reports."
    ).format(batch=batch, subject=subject_fp, config=config_fp)


def path_integrity_sentence(final_relevant: dict[str, Any]) -> str:
    normalized = final_relevant.get("normalized_repo_relative_only", False)
    raw = final_relevant.get("repo_relative_only", False)
    if normalized:
        return "Path integrity: final relevant files normalize to repo-relative paths, so Codex can compare reports safely."
    if raw:
        return "Path integrity: raw relevant files are repo-relative, but normalized path status is not confirmed."
    return "Path integrity needs attention: relevant_files may include absolute or non-repo-relative paths."


def reliability_sentence(reliability: dict[str, Any]) -> str:
    level = reliability.get("level", "n/a")
    paired_runs = reliability.get("paired_runs", "n/a")
    return f"Reliability: {level} evidence from {paired_runs} paired run(s)."


def tool_sanity_sentence(tool_sanity: dict[str, Any]) -> str:
    schema = tool_sanity.get("schema_version", "n/a")
    isolation = tool_sanity.get("run_isolation_reporting", False)
    warnings = tool_sanity.get("separated_warning_sections", False)
    output = tool_sanity.get("aggregated_command_output_counted", False)
    if isolation and warnings and output:
        return f"Internal report structure is complete: schema v{schema}, isolation reported, warnings separated, command output counted."
    return f"Internal report structure needs attention: schema v{schema}, isolation reported={isolation}, warnings separated={warnings}, command output counted={output}."


def print_result(result: dict[str, object], *, compare_history_command: str | None = None, result_dir: Path | None = None) -> None:
    primary = result.get("primary_delta", {})
    quality = result.get("quality", {})
    benchmark_warnings = result.get("benchmark_warnings", result.get("warnings", []))
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
        "This is synthetic scaldex test data. It is useful for development checks only, not as real benchmark evidence."
        if synthetic
        else decision.get("explanation", "unknown")
    )
    print("\n=== scaldex result ===")
    print("Result")
    print(f"Result type: {'developer/CI synthetic fixture' if synthetic else 'real benchmark report'}")
    print(f"Verdict: {result.get('verdict', 'unknown')}")
    print(f"What this means: {display_explanation}")
    print()
    print("Next step")
    print(f"What to do now: {what_to_do_now(decision, synthetic=synthetic)}")
    print()
    codex_handoff = artifact_path(result, "codex_handoff_md", result_dir)
    print("Codex handoff")
    if codex_handoff:
        print(f"- File to send: {codex_handoff}")
    else:
        print("- File to send: CODEX_HANDOFF.md was not found beside this result.")
    print(f"- Purpose: {handoff_purpose(decision)}")
    print(f"- Boundary: {handoff_safety_boundary(decision)}")
    print()
    print("What was compared")
    print("agents means the run with your measured AGENTS.md/.codex package installed.")
    print("control means the same task run without that package and without your global ~/.codex config.")
    isolation = result.get("isolation", {})
    if isinstance(subject, dict):
        print(subject_sentence(subject))
        if subject.get("mode") == "synthetic":
            print("Report note: synthetic scaldex test data; development and CI checks only.")
    if isinstance(integrity, dict):
        print(fingerprints_sentence(integrity))
    print()
    print("Evidence")
    if isinstance(primary, dict):
        print(primary_metric_sentence(primary))
        print(variant_medians_sentence(primary))
    if isinstance(quality, dict):
        print(quality_sentence(quality))
    if isinstance(reliability, dict):
        print(reliability_sentence(reliability))
        for warning in reliability.get("warnings", []):
            print(f"- {warning}: {explain_warning(str(warning))}")
    print()
    print("Audit checks")
    if isinstance(isolation, dict):
        print(isolation_sentence(isolation))
    if isinstance(final_relevant, dict):
        print(path_integrity_sentence(final_relevant))
    if isinstance(tool_sanity, dict):
        print(tool_sanity_sentence(tool_sanity))
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
    print()
    print("Report files:")
    print(f"- Human report: {artifact_path(result, 'result_md', result_dir)}")
    print(f"- Machine report: {artifact_path(result, 'result_json', result_dir)}")
    if codex_handoff:
        print(f"- Codex handoff: {codex_handoff}")
    if compare_history_command:
        print(f"Compare history: {compare_history_command}")
    print()
