from __future__ import annotations

import json
from pathlib import Path
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


def result_row(path: Path, result: dict[str, Any]) -> dict[str, Any]:
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
    return {
        "source": str(path),
        "task_id": task_id_for_result(result),
        "verdict": result.get("verdict", "unknown"),
        "decision_grade": bool(decision.get("decision_grade", float(reliability.get("paired_runs", 0) or 0) >= 3)),
        "paired_runs": reliability.get("paired_runs", 0),
        "next_action": decision.get("next_action", ""),
        "agents_quality": quality.get("agents_success_rate", 0),
        "control_quality": quality.get("control_success_rate", 0),
        "delta_non_cached_input_tokens": primary.get("agents_minus_control", 0),
        "delta_percent": primary.get("percent"),
        "agents_variant_median": primary.get("agents_median", 0),
        "control_variant_median": primary.get("control_median", 0),
        "benchmark_warnings": benchmark_warnings,
        "normalized_repo_relative_relevant_files_only": bool(final_relevant.get("normalized_repo_relative_only")),
        "subject_fingerprint": integrity.get("subject_fingerprint", ""),
        "run_config_fingerprint": integrity.get("run_config_fingerprint", ""),
        "subject_files": subject.get("source_file_count", 0),
        "subject_bytes": subject.get("total_bytes", 0),
    }


def quality_ok(row: dict[str, Any]) -> bool:
    return (
        float(row.get("agents_quality", 0) or 0) == 1.0
        and float(row.get("control_quality", 0) or 0) == 1.0
        and not row.get("benchmark_warnings")
        and bool(row.get("normalized_repo_relative_relevant_files_only"))
    )


def build_multi_summary(paths: list[Path]) -> dict[str, Any]:
    rows = [result_row(path, load_result_json(path)) for path in paths]
    task_grades: dict[str, set[bool]] = {}
    for row in rows:
        task_grades.setdefault(str(row["task_id"]), set()).add(bool(row["decision_grade"]))
    warnings: list[str] = []
    subject_fingerprints = sorted({str(row.get("subject_fingerprint", "")) for row in rows if row.get("subject_fingerprint")})
    if len(subject_fingerprints) != 1:
        warnings.append("mixed_or_missing_subject_fingerprints")
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
    return {
        "global_token_efficiency_claim_allowed": global_allowed,
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


def write_multi_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Tokenmessung Multi-Task Summary",
        "",
        f"Global token efficiency claim allowed: **{summary['global_token_efficiency_claim_allowed']}**",
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
    lines.extend(
        [
            "",
            "## Tasks",
            "",
            "| Task | Grade | Verdict | Quality | Delta | Normalized paths | Warnings |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in summary["tasks"]:
        grade = "decision" if row["decision_grade"] else "smoke"
        quality = f"{row['agents_quality']} / {row['control_quality']}"
        delta = f"{row['delta_non_cached_input_tokens']} ({fmt_percent(row['delta_percent'])})"
        warnings_text = ", ".join(row["benchmark_warnings"]) if row["benchmark_warnings"] else "none"
        lines.append(
            "| {task} | {grade} | {verdict} | {quality} | {delta} | {paths} | {warnings} |".format(
                task=row["task_id"],
                grade=grade,
                verdict=row["verdict"],
                quality=quality,
                delta=delta,
                paths=row["normalized_repo_relative_relevant_files_only"],
                warnings=warnings_text,
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

