from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median
from typing import Any

from .schemas import TASKS


GLOBAL_TASK_THRESHOLD = 3


def load_result_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid result JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Result JSON must be an object: {path}")
    return value


def discover_result_jsons(inputs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        if item.is_file():
            paths.append(item)
        elif item.is_dir():
            paths.extend(sorted(item.rglob("result.json")))
        else:
            raise FileNotFoundError(f"Result input not found: {item}")
    unique = sorted({path.resolve() for path in paths})
    if not unique:
        raise FileNotFoundError("No result.json files found")
    return unique


def task_id_for_result(result: dict[str, Any]) -> str:
    context = result.get("context", {})
    task_ids = context.get("task_ids", []) if isinstance(context, dict) else []
    if isinstance(task_ids, list) and len(task_ids) == 1:
        return str(task_ids[0])
    if isinstance(task_ids, list) and task_ids:
        return ",".join(str(task_id) for task_id in task_ids)
    return "unknown"


def result_task_ids(result: dict[str, Any]) -> list[str]:
    context = result.get("context", {})
    task_ids = context.get("task_ids", []) if isinstance(context, dict) else []
    return [str(task_id) for task_id in task_ids] if isinstance(task_ids, list) else []


def load_paired_delta_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def result_artifact_path(result_path: Path, result: dict[str, Any], key: str) -> Path | None:
    artifacts = result.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return None
    raw = artifacts.get(key)
    if not isinstance(raw, str) or not raw:
        return None
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else result_path.parent / candidate.name


def result_row(path: Path, result: dict[str, Any], *, task_id: str | None = None, task_paired_rows: list[dict[str, str]] | None = None) -> dict[str, Any]:
    primary = result.get("primary_delta", {}) if isinstance(result.get("primary_delta", {}), dict) else {}
    quality = result.get("quality", {}) if isinstance(result.get("quality", {}), dict) else {}
    reliability = result.get("reliability", {}) if isinstance(result.get("reliability", {}), dict) else {}
    decision = result.get("decision", {}) if isinstance(result.get("decision", {}), dict) else {}
    final_relevant = result.get("final_relevant_files", {}) if isinstance(result.get("final_relevant_files", {}), dict) else {}
    integrity = result.get("integrity", {}) if isinstance(result.get("integrity", {}), dict) else {}
    subject = result.get("subject", {}) if isinstance(result.get("subject", {}), dict) else {}
    benchmark_warnings = result.get("benchmark_warnings", [])
    if not isinstance(benchmark_warnings, list):
        benchmark_warnings = [str(benchmark_warnings)]
    paired_runs = reliability.get("paired_runs", 0)
    agents_quality = quality.get("agents_success_rate", 0)
    control_quality = quality.get("control_success_rate", 0)
    delta = primary.get("agents_minus_control", 0)
    percent = primary.get("percent")
    if task_paired_rows is not None:
        paired_runs = len(task_paired_rows)
        if paired_runs:
            agents_quality = sum(1 for row in task_paired_rows if str(row.get("agents_success")) == "True") / paired_runs
            control_quality = sum(1 for row in task_paired_rows if str(row.get("control_success")) == "True") / paired_runs
            deltas = [
                float(row["delta_non_cached_input_tokens_agents_minus_control"])
                for row in task_paired_rows
                if row.get("delta_non_cached_input_tokens_agents_minus_control") not in ("", None)
            ]
            delta = median(deltas) if deltas else 0
            percent = None
    decision_grade = bool(decision.get("decision_grade", float(paired_runs or 0) >= 3))
    if task_paired_rows is not None:
        decision_grade = paired_runs >= 3
    result_task_count = len(result_task_ids(result))
    return {
        "source": str(path),
        "task_id": task_id or task_id_for_result(result),
        "verdict": result.get("verdict", "unknown"),
        "decision_grade": decision_grade,
        "paired_runs": paired_runs,
        "next_action": decision.get("next_action", ""),
        "agents_quality": agents_quality,
        "control_quality": control_quality,
        "delta_non_cached_input_tokens": delta,
        "delta_percent": percent,
        "agents_variant_median": primary.get("agents_median", 0),
        "control_variant_median": primary.get("control_median", 0),
        "benchmark_warnings": benchmark_warnings,
        "normalized_repo_relative_relevant_files_only": bool(final_relevant.get("normalized_repo_relative_only")),
        "subject_fingerprint": integrity.get("subject_fingerprint", ""),
        "run_config_fingerprint": integrity.get("run_config_fingerprint", ""),
        "subject_files": subject.get("source_file_count", 0),
        "subject_bytes": subject.get("total_bytes", 0),
        "subject_mode": subject.get("mode", ""),
        "synthetic": subject.get("mode", "") == "synthetic" or result.get("context", {}).get("model") == "synthetic",
        "source_report_task_count": result_task_count,
        "source_report_scope": "multi_task_report" if result_task_count > 1 else "single_task_report",
    }


def result_rows(path: Path, result: dict[str, Any]) -> list[dict[str, Any]]:
    task_ids = result_task_ids(result)
    paired_deltas_path = result_artifact_path(path, result, "paired_deltas_csv")
    paired_rows = load_paired_delta_rows(paired_deltas_path) if paired_deltas_path else []
    if len(task_ids) > 1 and paired_rows:
        rows: list[dict[str, Any]] = []
        for task_id in task_ids:
            rows.append(result_row(path, result, task_id=task_id, task_paired_rows=[row for row in paired_rows if row.get("task_id") == task_id]))
        return rows
    return [result_row(path, result)]


def quality_ok(row: dict[str, Any]) -> bool:
    return (
        float(row.get("agents_quality", 0) or 0) == 1.0
        and float(row.get("control_quality", 0) or 0) == 1.0
        and not row.get("benchmark_warnings")
        and bool(row.get("normalized_repo_relative_relevant_files_only"))
    )


def build_multi_summary(paths: list[Path]) -> dict[str, Any]:
    rows = [row for path in paths for row in result_rows(path, load_result_json(path))]
    task_grades: dict[str, set[bool]] = {}
    for row in rows:
        task_grades.setdefault(str(row["task_id"]), set()).add(bool(row["decision_grade"]))
    warnings: list[str] = []
    subject_fingerprints = sorted({str(row.get("subject_fingerprint", "")) for row in rows if row.get("subject_fingerprint")})
    if len(subject_fingerprints) != 1:
        warnings.append("mixed_or_missing_subject_fingerprints")
    if any(row.get("synthetic") for row in rows):
        warnings.append("synthetic_results_only")
    mixed_grade_tasks = sorted(task for task, grades in task_grades.items() if len(grades) > 1)
    if mixed_grade_tasks:
        warnings.append("mixed_smoke_and_decision_grade_results")
    decision_grade_rows = [row for row in rows if row["decision_grade"]]
    effective_tasks = {
        str(row["task_id"])
        for row in decision_grade_rows
        if row["verdict"] == "effective" and quality_ok(row)
    }
    measured_decision_tasks = {str(row["task_id"]) for row in decision_grade_rows}
    expected_task_count = len(TASKS)
    global_allowed = (
        len(effective_tasks) >= GLOBAL_TASK_THRESHOLD
        and len(measured_decision_tasks) >= expected_task_count
        and not warnings
    )
    global_blockers: list[str] = []
    if len(effective_tasks) < GLOBAL_TASK_THRESHOLD:
        global_blockers.append(
            f"effective_decision_grade_tasks_below_threshold:{len(effective_tasks)}/{GLOBAL_TASK_THRESHOLD}"
        )
    if len(measured_decision_tasks) < expected_task_count:
        global_blockers.append(
            f"decision_grade_tasks_incomplete:{len(measured_decision_tasks)}/{expected_task_count}"
        )
    global_blockers.extend(warnings)
    return {
        "global_token_efficiency_claim_allowed": global_allowed,
        "global_decision": "claim_global_token_efficiency" if global_allowed else "do_not_claim_global_efficiency",
        "global_blockers": global_blockers,
        "effective_decision_grade_task_count": len(effective_tasks),
        "decision_grade_task_count": len(measured_decision_tasks),
        "expected_task_count": expected_task_count,
        "subject_fingerprints": subject_fingerprints,
        "warnings": warnings,
        "mixed_grade_tasks": mixed_grade_tasks,
        "tasks": rows,
    }


def fmt_percent(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def fmt_delta(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.1f}"


def plain_global_explanation(summary: dict[str, Any]) -> str:
    if summary["global_token_efficiency_claim_allowed"]:
        return "You have enough decision-grade task evidence to claim global token efficiency for this measured subject."
    blockers = set(summary.get("global_blockers", []))
    if "synthetic_results_only" in blockers or "synthetic_results_only" in set(summary.get("warnings", [])):
        return "This is synthetic demo data. Use it to inspect the report format, not to claim real token efficiency."
    if any(str(blocker).startswith("decision_grade_tasks_incomplete:") for blocker in blockers):
        return "The summary does not yet contain decision-grade evidence for all expected tasks."
    if any(str(blocker).startswith("effective_decision_grade_tasks_below_threshold:") for blocker in blockers):
        return "Too few decision-grade tasks are effective, so a global efficiency claim would be misleading."
    return "The evidence set has blockers. Read the warnings and task table before making any claim."


def next_summary_action(summary: dict[str, Any]) -> str:
    if summary["global_token_efficiency_claim_allowed"]:
        return "Record this as a global decision-grade win and keep the summary with the release evidence."
    warnings = set(summary.get("warnings", []))
    if "synthetic_results_only" in warnings:
        return "For a real assessment, run paid smoke or decision-grade benchmarks against an actual subject package."
    if "mixed_or_missing_subject_fingerprints" in warnings:
        return "Do not compare these runs until all reports use the same subject fingerprint."
    if "mixed_smoke_and_decision_grade_results" in warnings:
        return "Separate smoke and decision-grade reports, or rerun the affected tasks consistently."
    return "Do not claim global efficiency yet; collect the missing decision-grade task reports or fix failed tasks first."


def yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def report_type_text(summary: dict[str, Any]) -> str:
    return "DEMO DATA ONLY (synthetic results)" if "synthetic_results_only" in summary.get("warnings", []) else "real benchmark reports"


def format_multi_summary_console(summary: dict[str, Any], paths: dict[str, Path] | None = None) -> str:
    lines = [
        "",
        "=== Tokenmessung Summary ===",
        f"Report type: {report_type_text(summary)}",
        f"Can claim global efficiency: {yes_no(summary['global_token_efficiency_claim_allowed'])}",
        f"Decision: {summary['global_decision']}",
        f"Why: {plain_global_explanation(summary)}",
        f"Next step: {next_summary_action(summary)}",
        "",
        "Evidence:",
        f"- Effective decision-grade tasks: {summary['effective_decision_grade_task_count']}/{GLOBAL_TASK_THRESHOLD} needed",
        f"- Decision-grade tasks observed: {summary['decision_grade_task_count']}/{summary['expected_task_count']} expected",
    ]
    warnings = summary.get("warnings", [])
    lines.append(f"- Warnings: {', '.join(str(warning) for warning in warnings) if warnings else 'none'}")
    if paths:
        lines.extend(
            [
                "",
                f"Human summary: {paths['summary_md']}",
                f"Machine summary: {paths['summary_json']}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def write_multi_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    synthetic = "synthetic_results_only" in summary.get("warnings", [])
    lines = [
        "# Tokenmessung Multi-Task Summary",
        "",
        f"Status: **{report_type_text(summary)}**",
        "",
        f"Can claim global efficiency: **{yes_no(summary['global_token_efficiency_claim_allowed'])}**",
        "",
        f"Why: {plain_global_explanation(summary)}",
        "",
        f"Next step: {next_summary_action(summary)}",
        "",
        "## What This Is",
        "",
        "This report combines existing `result.json` files. It does not run Codex and does not spend API money.",
        "",
        (
            "This report uses synthetic demo data. It does not measure your `AGENTS.md`, your `.codex/` package, or any real Codex run."
            if synthetic
            else "Use this summary to decide whether several task reports support a broader efficiency claim."
        ),
        "",
        "Do not use synthetic demo data as efficiency evidence." if synthetic else "Use the decision below as release evidence only when the quality gates pass.",
        "",
        "## Decision",
        "",
        f"Global decision: **{summary['global_decision']}**",
        "",
        f"Global token efficiency claim allowed: **{summary['global_token_efficiency_claim_allowed']}**",
        "",
        f"Plain explanation: {plain_global_explanation(summary)}",
        "",
        f"Next action: {next_summary_action(summary)}",
        "",
        "## Evidence",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Effective decision-grade tasks | {summary['effective_decision_grade_task_count']} |",
        f"| Decision-grade tasks observed | {summary['decision_grade_task_count']} |",
        f"| Expected task count | {summary['expected_task_count']} |",
        "",
        "## Warnings",
        "",
    ]
    warnings = summary.get("warnings", [])
    if warnings:
        lines.extend(f"- `{warning}`" for warning in warnings)
    else:
        lines.append("- None")
    blockers = summary.get("global_blockers", [])
    lines.extend(
        [
            "",
            "## Global Blockers",
            "",
        ]
    )
    if blockers:
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Tasks",
            "",
            "| Task | Evidence | Paired runs | Verdict | Quality | Token delta | Path check | Warnings | Source |",
            "| --- | --- | ---: | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in summary["tasks"]:
        grade = "decision-grade" if row["decision_grade"] else "smoke/demo"
        quality = f"{row['agents_quality']} / {row['control_quality']}"
        delta = f"{fmt_delta(row['delta_non_cached_input_tokens'])} ({fmt_percent(row['delta_percent'])})"
        warnings_text = ", ".join(row["benchmark_warnings"]) if row["benchmark_warnings"] else "none"
        source = Path(str(row["source"])).name
        if row.get("source_report_scope") == "multi_task_report":
            source = f"{source} (split from multi-task report)"
        lines.append(
            "| {task} | {grade} | {paired_runs} | {verdict} | {quality} | {delta} | {paths} | {warnings} | {source} |".format(
                task=row["task_id"],
                grade=grade,
                paired_runs=row["paired_runs"],
                verdict=row["verdict"],
                quality=quality,
                delta=delta,
                paths="ok" if row["normalized_repo_relative_relevant_files_only"] else "failed",
                warnings=warnings_text,
                source=source,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize_results(inputs: list[Path], out: Path) -> dict[str, Path]:
    paths = discover_result_jsons(inputs)
    summary = build_multi_summary(paths)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "tokenmessung-summary.json"
    md_path = out / "TOKENMESSUNG_SUMMARY.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_multi_summary_markdown(md_path, summary)
    return {"summary_json": json_path, "summary_md": md_path}
