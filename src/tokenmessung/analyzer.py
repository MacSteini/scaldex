from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable

LARGE_TEXT_BYTES = 20_000
TOOL_SANITY = {
    "schema_version": 1,
    "run_isolation_reporting": True,
    "separated_warning_sections": True,
    "aggregated_command_output_counted": True,
}
CRITICAL_WARNING_PREFIXES = (
    "incomplete_pair:",
    "missing_batch_id",
    "mixed_batch_ids",
    "missing_subject_fingerprint",
    "mixed_subject_fingerprints",
    "missing_run_config_fingerprint",
    "mixed_run_config_fingerprints",
    "unexpected_task_repeat_set",
    "missing_turn_completed_usage",
    "invalid_final_json",
    "malformed_relevant_files",
    "nonzero_exit_code",
    "missing_expected_files",
    "missing_expected_relevant_files",
    "non_repo_relative_relevant_files",
)
INTEGRITY_WARNING_PREFIXES = (
    "missing_batch_id",
    "mixed_batch_ids",
    "missing_subject_fingerprint",
    "mixed_subject_fingerprints",
    "missing_run_config_fingerprint",
    "mixed_run_config_fingerprints",
    "unexpected_task_repeat_set",
)

RISKY_FULL_READ_PATTERNS = [
    re.compile(r"\bcat\b"),
    re.compile(r"\bsed\b\s+(-n\s+)?['\"]?1,\$p?['\"]?"),
    re.compile(r"python\d?(\.\d+)?\s+-c\s+.*read\(\)"),
]

TARGETED_PATTERNS = [
    re.compile(r"\brg\b"),
    re.compile(r"\bgrep\b"),
    re.compile(r"\bfind\b"),
    re.compile(r"\bls\b"),
    re.compile(r"\bwc\b"),
    re.compile(r"\bsed\s+-n\b"),
    re.compile(r"\bhead\b"),
    re.compile(r"\btail\b"),
]

WARNING_DESCRIPTIONS = {
    "agents_found_relevant_file_later": "The instruction package reached the expected relevant file later than the control run.",
    "command_count_increased": "The instruction package needed more shell commands than the control run.",
    "command_output_bytes_increased": "The instruction-package run exposed materially more command output text than the control run.",
    "incomplete_pair": "At least one agents/control run pair is missing, so the comparison is incomplete.",
    "invalid_final_json": "A Codex run did not produce valid structured final JSON.",
    "large_subject": "The tested subject package is larger than 32 KiB, so instruction/package size may materially affect input tokens.",
    "low_sample_size": "This is a smoke result based on fewer than 3 paired runs; use --repeats 3 or more for a decision-grade measurement.",
    "large_text_events_increased": "The instruction-package run produced more large text events over the configured threshold.",
    "missing_expected_files": "A run did not mention all expected files.",
    "missing_expected_relevant_files": "A run did not include all expected files in final relevant_files.",
    "missing_batch_id": "Run metadata is missing the batch id, so this report cannot prove all rows came from one benchmark invocation.",
    "mixed_batch_ids": "The result folder contains runs from different benchmark invocations.",
    "missing_subject_fingerprint": "Run metadata is missing the subject fingerprint, so this report cannot prove a single subject state was measured.",
    "mixed_subject_fingerprints": "The result folder contains runs measured against different subject/ contents.",
    "missing_run_config_fingerprint": "Run metadata is missing the run configuration fingerprint.",
    "mixed_run_config_fingerprints": "The result folder contains runs created with different benchmark configurations.",
    "missing_turn_completed_usage": "A run did not expose authoritative turn.completed usage; fallback usage parsing was used.",
    "malformed_relevant_files": "A run produced final JSON without a valid relevant_files string array.",
    "non_repo_relative_relevant_files": "A run emitted absolute, home-relative, URL, or parent-directory paths in final relevant_files; use repo-relative paths only.",
    "nonzero_exit_code": "A Codex run exited with a non-zero status.",
    "risky_full_reads_increased": "The instruction package caused more risky full-file reads than the control run.",
    "subject_contains_codex": "The tested subject includes a .codex/ directory, so this measures a full Codex instruction package, not only AGENTS.md.",
    "subject_contains_codex_bin": "The tested subject includes .codex/bin/ helper scripts; they may be discovered even when they are not needed for the task.",
    "subject_contains_codex_skills": "The tested subject includes .codex/skills/; skills can add useful behaviour but also increase discoverable instruction material.",
    "subject_contains_codex_tooling": "The tested subject includes .codex/config/tooling/; validator/tooling config is included in the measured package.",
    "total_observed_tokens_increased": "Total observed tokens were higher for the instruction-package run.",
    "unexpected_task_repeat_set": "The observed task/repeat set does not match the run configuration recorded for this batch.",
    "wall_time_increased": "The instruction-package run took materially longer than the control run.",
}

WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def walk(obj: Any) -> Iterable[Any]:
    yield obj
    if isinstance(obj, dict):
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


def text_bytes(value: str) -> int:
    return len(value.encode("utf-8", errors="replace"))


def get_commands(event: Any) -> list[str]:
    commands: list[str] = []
    for node in walk(event):
        if isinstance(node, dict):
            command = node.get("command")
            if isinstance(command, str):
                commands.append(command)
    return commands


def classify_text_bytes(event: Any) -> tuple[int, int, int, int]:
    stdout_bytes = stderr_bytes = assistant_bytes = other_bytes = 0
    for node in walk(event):
        if not isinstance(node, dict):
            continue
        item_type = node.get("type")
        for key in ("stdout", "stderr", "aggregated_output", "text", "output"):
            value = node.get(key)
            if not isinstance(value, str):
                continue
            size = text_bytes(value)
            if key in ("stdout", "aggregated_output"):
                stdout_bytes += size
            elif key == "stderr":
                stderr_bytes += size
            elif item_type == "agent_message":
                assistant_bytes += size
            else:
                other_bytes += size
    return stdout_bytes, stderr_bytes, assistant_bytes, other_bytes


def usage_from_event(event: dict[str, Any]) -> dict[str, int]:
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}
    candidates: list[dict[str, Any]] = []
    direct = event.get("usage")
    if isinstance(direct, dict):
        candidates.append(direct)
    if event.get("type") != "turn.completed":
        for node in walk(event):
            if isinstance(node, dict) and isinstance(node.get("usage"), dict):
                candidates.append(node["usage"])
    for candidate in candidates:
        for key in usage:
            value = candidate.get(key)
            if isinstance(value, int):
                usage[key] += value
    return usage


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def load_json_checked(path: Path, default: Any) -> tuple[Any, bool]:
    if not path.exists():
        return default, False
    try:
        return json.loads(path.read_text(encoding="utf-8")), True
    except json.JSONDecodeError:
        return default, False


def final_relevant_files(final: Any) -> tuple[list[str], bool]:
    if not isinstance(final, dict):
        return [], False
    value = final.get("relevant_files")
    if not isinstance(value, list):
        return [], True
    files = [item for item in value if isinstance(item, str)]
    return files, len(files) != len(value)


def is_repo_relative_relevant_file(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if not normalized or normalized.startswith("/") or normalized.startswith("~"):
        return False
    if "://" in normalized or WINDOWS_ABSOLUTE_PATH_RE.match(value):
        return False
    return ".." not in normalized.split("/")


def normalize_relevant_file(value: str, workdir: Path | None) -> str:
    normalized = value.replace("\\", "/")
    if not workdir or not Path(normalized).is_absolute():
        return normalized
    try:
        return Path(normalized).resolve().relative_to(workdir.resolve()).as_posix()
    except ValueError:
        return normalized


def parse_run(run_dir: Path, large_text_bytes: int = LARGE_TEXT_BYTES) -> dict[str, Any]:
    meta = load_json(run_dir / "meta.json", {})
    subject_audit = meta.get("subject_audit", {})
    run_isolation = meta.get("run_isolation", {})
    run_config = meta.get("run_config", {})
    task = meta.get("task", {})
    expected_files = task.get("expected_files", [])
    expected_terms = task.get("expected_terms", [])
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}
    fallback_usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}
    saw_turn_completed_usage = False
    commands: list[str] = []
    stdout_bytes = stderr_bytes = assistant_bytes = other_bytes = 0
    large_text_events = 0
    first_expected_event_index: int | None = None
    all_text_fragments: list[str] = []
    analysis_warnings: list[str] = []

    jsonl_path = run_dir / "codex.jsonl"
    if jsonl_path.exists():
        for index, line in enumerate(jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_usage = usage_from_event(event)
            if event.get("type") == "turn.completed":
                saw_turn_completed_usage = True
                for key, value in event_usage.items():
                    usage[key] += value
            else:
                for key, value in event_usage.items():
                    fallback_usage[key] += value
            commands.extend(get_commands(event))
            event_stdout, event_stderr, event_assistant, event_other = classify_text_bytes(event)
            stdout_bytes += event_stdout
            stderr_bytes += event_stderr
            assistant_bytes += event_assistant
            other_bytes += event_other
            if max(event_stdout, event_stderr, event_assistant, event_other) >= large_text_bytes:
                large_text_events += 1
            line_text = json.dumps(event, ensure_ascii=False)
            all_text_fragments.append(line_text)
            if first_expected_event_index is None and any(expected in line_text for expected in expected_files):
                first_expected_event_index = index

    if not saw_turn_completed_usage:
        usage = fallback_usage
        analysis_warnings.append("missing_turn_completed_usage")

    final, final_valid = load_json_checked(run_dir / "final.json", {})
    if not final_valid:
        analysis_warnings.append("invalid_final_json")
    relevant_files, malformed_relevant_files = final_relevant_files(final)
    if final_valid and malformed_relevant_files:
        analysis_warnings.append("malformed_relevant_files")
    workdir_value = meta.get("workdir")
    workdir = Path(workdir_value) if isinstance(workdir_value, str) and workdir_value else None
    normalized_relevant_files = [normalize_relevant_file(path, workdir) for path in relevant_files]
    expected_relevant_files_found = [path for path in expected_files if path in normalized_relevant_files]
    raw_non_repo_relative_relevant_files = [path for path in relevant_files if not is_repo_relative_relevant_file(path)]
    non_repo_relative_relevant_files = [
        path for path in normalized_relevant_files if not is_repo_relative_relevant_file(path)
    ]
    if expected_files and len(expected_relevant_files_found) != len(expected_files):
        analysis_warnings.append("missing_expected_relevant_files")
    if non_repo_relative_relevant_files:
        analysis_warnings.append("non_repo_relative_relevant_files")
    final_text = json.dumps(final, ensure_ascii=False)
    all_text = "\n".join(all_text_fragments) + "\n" + final_text + "\n" + "\n".join(commands)
    expected_files_found = [path for path in expected_files if path in all_text]
    expected_terms_found = [term for term in expected_terms if term in all_text]
    final_expected_files_found = [path for path in expected_files if path in final_text]
    final_expected_terms_found = [term for term in expected_terms if term in final_text]
    risky_full_reads = sum(1 for command in commands if any(pattern.search(command) for pattern in RISKY_FULL_READ_PATTERNS))
    targeted_steps = sum(1 for command in commands if any(pattern.search(command) for pattern in TARGETED_PATTERNS))
    exit_code = (run_dir / "exit_code.txt").read_text(encoding="utf-8").strip() if (run_dir / "exit_code.txt").exists() else ""
    if exit_code and exit_code != "0":
        analysis_warnings.append("nonzero_exit_code")
    time_meta = load_json(run_dir / "time.json", {})
    total_observed_tokens = usage["input_tokens"] + usage["output_tokens"] + usage["reasoning_output_tokens"]
    non_cached_input_tokens = max(usage["input_tokens"] - usage["cached_input_tokens"], 0)
    success = (
        final_valid
        and bool(expected_files)
        and len(final_expected_files_found) == len(expected_files)
        and len(expected_relevant_files_found) == len(expected_files)
        and not non_repo_relative_relevant_files
        and bool(final_expected_terms_found)
    )
    if expected_files and len(expected_files_found) != len(expected_files):
        analysis_warnings.append("missing_expected_files")

    return {
        "run_id": meta.get("run_id", run_dir.name),
        "batch_id": meta.get("batch_id", ""),
        "subject_fingerprint": meta.get("subject_fingerprint", subject_audit.get("fingerprint", "") if isinstance(subject_audit, dict) else ""),
        "run_config_fingerprint": meta.get("run_config_fingerprint", ""),
        "expected_task_ids": ";".join(run_config.get("task_ids", [])) if isinstance(run_config, dict) and isinstance(run_config.get("task_ids"), list) else "",
        "expected_repeats": run_config.get("repeats", "") if isinstance(run_config, dict) else "",
        "expected_run_count": run_config.get("expected_run_count", "") if isinstance(run_config, dict) else "",
        "task_id": meta.get("task_id", ""),
        "variant": meta.get("variant", ""),
        "repeat": meta.get("repeat", ""),
        "run_order": meta.get("run_order", ""),
        "model": meta.get("model", ""),
        "codex_version": meta.get("codex_version", ""),
        "python_version": meta.get("python_version", ""),
        "fixture_commit": meta.get("fixture_commit", ""),
        "agents_file_bytes": meta.get("agents_file_bytes", 0),
        "subject_mode": meta.get("subject_mode", ""),
        "agents_source_file_count": meta.get("agents_source_file_count", 0),
        "subject_total_bytes": subject_audit.get("total_bytes", meta.get("agents_file_bytes", 0)) if isinstance(subject_audit, dict) else meta.get("agents_file_bytes", 0),
        "subject_warning_count": len(subject_audit.get("warnings", [])) if isinstance(subject_audit, dict) and isinstance(subject_audit.get("warnings"), list) else 0,
        "subject_warnings": ";".join(subject_audit.get("warnings", [])) if isinstance(subject_audit, dict) and isinstance(subject_audit.get("warnings"), list) else "",
        "subject_largest_files": json.dumps(subject_audit.get("largest_files", [])[:5], ensure_ascii=False) if isinstance(subject_audit, dict) else "[]",
        "isolated_codex_home": run_isolation.get("isolated_codex_home", "") if isinstance(run_isolation, dict) else "",
        "ignore_user_config": run_isolation.get("ignore_user_config", "") if isinstance(run_isolation, dict) else "",
        "ignore_rules": run_isolation.get("ignore_rules", "") if isinstance(run_isolation, dict) else "",
        "home_codex_excluded": run_isolation.get("home_codex_excluded", "") if isinstance(run_isolation, dict) else "",
        "exit_code": exit_code,
        "wall_seconds": time_meta.get("wall_seconds", ""),
        "input_tokens": usage["input_tokens"],
        "cached_input_tokens": usage["cached_input_tokens"],
        "non_cached_input_tokens": non_cached_input_tokens,
        "output_tokens": usage["output_tokens"],
        "reasoning_output_tokens": usage["reasoning_output_tokens"],
        "total_observed_tokens": total_observed_tokens,
        "command_count": len(commands),
        "targeted_steps": targeted_steps,
        "risky_full_reads": risky_full_reads,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "assistant_text_bytes": assistant_bytes,
        "other_text_bytes": other_bytes,
        "large_text_events_over_20kb": large_text_events,
        "expected_files_count": len(expected_files),
        "expected_files_found_count": len(expected_files_found),
        "expected_files_found": ";".join(expected_files_found),
        "final_relevant_files_count": len(normalized_relevant_files),
        "final_relevant_files": ";".join(normalized_relevant_files),
        "expected_relevant_files_found_count": len(expected_relevant_files_found),
        "expected_relevant_files_found": ";".join(expected_relevant_files_found),
        "repo_relative_relevant_files_only": not raw_non_repo_relative_relevant_files,
        "non_repo_relative_relevant_files_count": len(non_repo_relative_relevant_files),
        "non_repo_relative_relevant_files": ";".join(non_repo_relative_relevant_files),
        "raw_non_repo_relative_relevant_files_count": len(raw_non_repo_relative_relevant_files),
        "raw_non_repo_relative_relevant_files": ";".join(raw_non_repo_relative_relevant_files),
        "expected_terms_found": ";".join(expected_terms_found),
        "first_expected_file_event_index": first_expected_event_index if first_expected_event_index is not None else "",
        "success": success,
        "confidence": final.get("confidence", "") if isinstance(final, dict) else "",
        "analysis_warnings": ";".join(analysis_warnings),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("No rows to write")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: list[dict[str, Any]], deltas: list[dict[str, Any]], analysis_warnings: list[str]) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_variant[str(row["variant"])].append(row)
    summary: dict[str, Any] = {
        "runs": len(rows),
        "variants": {},
        "analysis_warnings": sorted(set(analysis_warnings)),
        "integrity": {
            "batch_ids": nonempty_unique(rows, "batch_id"),
            "subject_fingerprints": nonempty_unique(rows, "subject_fingerprint"),
            "run_config_fingerprints": nonempty_unique(rows, "run_config_fingerprint"),
        },
    }
    numeric_keys = [
        "input_tokens",
        "cached_input_tokens",
        "non_cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_observed_tokens",
        "wall_seconds",
        "command_count",
        "targeted_steps",
        "risky_full_reads",
        "stdout_bytes",
        "stderr_bytes",
        "large_text_events_over_20kb",
        "expected_files_found_count",
        "final_relevant_files_count",
        "expected_relevant_files_found_count",
        "non_repo_relative_relevant_files_count",
        "first_expected_file_event_index",
        "subject_total_bytes",
        "agents_source_file_count",
    ]
    for variant, variant_rows in sorted(by_variant.items()):
        successes = sum(1 for row in variant_rows if row["success"])
        metrics: dict[str, Any] = {"runs": len(variant_rows), "successes": successes, "success_rate": successes / len(variant_rows)}
        for key in numeric_keys:
            values = [float(row[key]) for row in variant_rows if row.get(key) not in ("", None)]
            metrics[f"median_{key}"] = median(values) if values else 0
        summary["variants"][variant] = metrics
    paired_metrics: dict[str, float] = {}
    if deltas:
        for key in deltas[0]:
            if key.startswith("delta_"):
                values = [float(row[key]) for row in deltas if row.get(key) not in ("", None)]
                paired_metrics[f"median_{key}"] = median(values) if values else 0.0
    summary["paired_median_deltas"] = paired_metrics
    return summary


def paired_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        try:
            repeat = int(row["repeat"])
        except (TypeError, ValueError):
            continue
        pairs[(str(row["task_id"]), repeat)][str(row["variant"])] = row
    delta_keys = [
        "non_cached_input_tokens",
        "total_observed_tokens",
        "wall_seconds",
        "stdout_bytes",
        "stderr_bytes",
        "command_count",
        "risky_full_reads",
        "large_text_events_over_20kb",
    ]
    optional_delta_keys = ["first_expected_file_event_index"]
    deltas: list[dict[str, Any]] = []
    for (task_id, repeat), pair in sorted(pairs.items()):
        if "agents" not in pair or "control" not in pair:
            continue
        row: dict[str, Any] = {"task_id": task_id, "repeat": repeat}
        for key in delta_keys:
            row[f"delta_{key}_agents_minus_control"] = float(pair["agents"][key]) - float(pair["control"][key])
        for key in optional_delta_keys:
            agents_value = pair["agents"].get(key)
            control_value = pair["control"].get(key)
            if agents_value not in ("", None) and control_value not in ("", None):
                row[f"delta_{key}_agents_minus_control"] = float(agents_value) - float(control_value)
            else:
                row[f"delta_{key}_agents_minus_control"] = ""
        row["agents_success"] = pair["agents"]["success"]
        row["control_success"] = pair["control"]["success"]
        deltas.append(row)
    return deltas


def incomplete_pair_warnings(rows: list[dict[str, Any]]) -> list[str]:
    pairs: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in rows:
        try:
            repeat = int(row["repeat"])
        except (TypeError, ValueError):
            continue
        pairs[(str(row["task_id"]), repeat)].add(str(row["variant"]))
    warnings = []
    for (task_id, repeat), variants in sorted(pairs.items()):
        if variants != {"agents", "control"}:
            warnings.append(f"incomplete_pair:{task_id}:r{repeat}")
    return warnings


def nonempty_unique(rows: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(row.get(key, "")) for row in rows if row.get(key) not in ("", None)})


def integrity_warnings(rows: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    checks = [
        ("batch_id", "missing_batch_id", "mixed_batch_ids"),
        ("subject_fingerprint", "missing_subject_fingerprint", "mixed_subject_fingerprints"),
        ("run_config_fingerprint", "missing_run_config_fingerprint", "mixed_run_config_fingerprints"),
    ]
    for key, missing_code, mixed_code in checks:
        if any(not row.get(key) for row in rows):
            warnings.append(missing_code)
            continue
        if len(nonempty_unique(rows, key)) != 1:
            warnings.append(mixed_code)

    expected_task_sets = nonempty_unique(rows, "expected_task_ids")
    expected_repeats = nonempty_unique(rows, "expected_repeats")
    expected_run_counts = nonempty_unique(rows, "expected_run_count")
    if len(expected_task_sets) == 1 and len(expected_repeats) == 1 and len(expected_run_counts) == 1:
        expected_tasks = {task_id for task_id in expected_task_sets[0].split(";") if task_id}
        try:
            repeat_count = int(float(expected_repeats[0]))
            expected_run_count = int(float(expected_run_counts[0]))
        except ValueError:
            warnings.append("unexpected_task_repeat_set")
        else:
            actual_tasks = {str(row.get("task_id", "")) for row in rows if row.get("task_id")}
            actual_repeats = {int(row["repeat"]) for row in rows if str(row.get("repeat", "")).isdigit()}
            expected_repeat_values = set(range(1, repeat_count + 1))
            if len(rows) != expected_run_count or actual_tasks != expected_tasks or actual_repeats != expected_repeat_values:
                warnings.append("unexpected_task_repeat_set")
    else:
        warnings.append("unexpected_task_repeat_set")
    return sorted(set(warnings))


def number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def human_bytes(value: Any) -> str:
    size = number(value)
    units = ["B", "KiB", "MiB", "GiB"]
    unit_index = 0
    while abs(size) >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def warning_label(warning: str) -> str:
    if warning.startswith("incomplete_pair:"):
        return "incomplete_pair"
    return warning


def explain_warning(warning: str) -> str:
    return WARNING_DESCRIPTIONS.get(warning_label(warning), "Review this warning in the raw analysis output.")


def warning_details(warnings: list[Any]) -> list[dict[str, str]]:
    return [{"code": str(warning), "message": explain_warning(str(warning))} for warning in warnings]


def percent_delta(delta: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return delta / baseline * 100


def median_delta(summary: dict[str, Any], key: str) -> float:
    return number(summary.get("paired_median_deltas", {}).get(f"median_delta_{key}_agents_minus_control"))


def variant_median(summary: dict[str, Any], variant: str, key: str) -> float:
    return number(summary.get("variants", {}).get(variant, {}).get(f"median_{key}"))


def success_rate(summary: dict[str, Any], variant: str) -> float:
    return number(summary.get("variants", {}).get(variant, {}).get("success_rate"))


def has_critical_warnings(warnings: list[str]) -> bool:
    return any(any(warning.startswith(prefix) for prefix in CRITICAL_WARNING_PREFIXES) for warning in warnings)


def has_integrity_warnings(warnings: list[str]) -> bool:
    return any(any(warning.startswith(prefix) for prefix in INTEGRITY_WARNING_PREFIXES) for warning in warnings)


def quality_gate_passed(result: dict[str, Any]) -> bool:
    quality = result.get("quality", {})
    final_relevant = result.get("final_relevant_files", {})
    benchmark_warnings = result.get("benchmark_warnings", [])
    return (
        isinstance(quality, dict)
        and number(quality.get("agents_success_rate")) == 1.0
        and number(quality.get("control_success_rate")) == 1.0
        and not benchmark_warnings
        and isinstance(final_relevant, dict)
        and bool(final_relevant.get("normalized_repo_relative_only"))
    )


def decision_grade(result: dict[str, Any]) -> bool:
    reliability = result.get("reliability", {})
    return isinstance(reliability, dict) and number(reliability.get("paired_runs")) >= 3


def decision_summary(result: dict[str, Any]) -> dict[str, Any]:
    quality_ok = quality_gate_passed(result)
    is_decision_grade = decision_grade(result)
    if is_decision_grade:
        next_action = "record_decision_grade_win" if result.get("verdict") == "effective" and quality_ok else "do_not_claim_efficiency"
    else:
        next_action = "eligible_for_decision_run" if quality_ok else "stop_fix_quality_or_task_behavior"
    return {
        "decision": {
            "eligible_for_decision_run": "smoke_passed",
            "stop_fix_quality_or_task_behavior": "smoke_blocked",
            "record_decision_grade_win": "decision_grade_effective",
            "do_not_claim_efficiency": "decision_grade_not_effective",
        }[next_action],
        "next_action": next_action,
        "quality_gate_passed": quality_ok,
        "decision_grade": is_decision_grade,
        "primary_metric_basis": "paired_median_non_cached_input_delta",
        "global_claim_eligibility": "single-task only / not enough evidence",
        "uses_unpaired_variant_medians_for_decision": False,
    }


def build_result(summary: dict[str, Any], deltas: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    warnings = list(summary.get("analysis_warnings", []))
    control_non_cached = variant_median(summary, "control", "non_cached_input_tokens")
    agents_non_cached = variant_median(summary, "agents", "non_cached_input_tokens")
    non_cached_delta = median_delta(summary, "non_cached_input_tokens")
    total_delta = median_delta(summary, "total_observed_tokens")
    wall_delta = median_delta(summary, "wall_seconds")
    stdout_delta = median_delta(summary, "stdout_bytes")
    stderr_delta = median_delta(summary, "stderr_bytes")
    command_delta = median_delta(summary, "command_count")
    risky_delta = median_delta(summary, "risky_full_reads")
    large_text_delta = median_delta(summary, "large_text_events_over_20kb")
    first_expected_delta = median_delta(summary, "first_expected_file_event_index")
    agents_success = success_rate(summary, "agents")
    control_success = success_rate(summary, "control")

    secondary_warnings: list[str] = []
    control_total = variant_median(summary, "control", "total_observed_tokens")
    control_wall = variant_median(summary, "control", "wall_seconds")
    control_command_output = variant_median(summary, "control", "stdout_bytes") + variant_median(summary, "control", "stderr_bytes")
    command_output_delta = stdout_delta + stderr_delta
    if total_delta > max(1000.0, control_total * 0.10):
        secondary_warnings.append("total_observed_tokens_increased")
    if wall_delta > max(5.0, control_wall * 0.20):
        secondary_warnings.append("wall_time_increased")
    if command_delta > 0:
        secondary_warnings.append("command_count_increased")
    if command_output_delta > max(float(LARGE_TEXT_BYTES), control_command_output * 0.10):
        secondary_warnings.append("command_output_bytes_increased")
    if risky_delta > 0:
        secondary_warnings.append("risky_full_reads_increased")
    if large_text_delta > 0:
        secondary_warnings.append("large_text_events_increased")
    if first_expected_delta > 3:
        secondary_warnings.append("agents_found_relevant_file_later")

    subject_rows = [row for row in rows if row.get("variant") == "agents"]
    subject_warning_values = sorted({warning for row in subject_rows for warning in str(row.get("subject_warnings", "")).split(";") if warning})
    non_repo_relative_relevant_files = sorted(
        {
            path
            for row in rows
            for path in str(row.get("non_repo_relative_relevant_files", "")).split(";")
            if path
        }
    )
    raw_non_repo_relative_relevant_files = sorted(
        {
            path
            for row in rows
            for path in str(row.get("raw_non_repo_relative_relevant_files", "")).split(";")
            if path
        }
    )
    missing_expected_relevant_files = sorted(
        {
            path
            for row in rows
            for path in str(row.get("expected_files_found", "")).split(";")
            if path and path not in str(row.get("expected_relevant_files_found", "")).split(";")
        }
    )
    reliability_warnings = ["low_sample_size"] if len(deltas) < 3 else []
    reliability_level = "low" if reliability_warnings else "normal"
    benchmark_warnings = warnings + secondary_warnings

    if not deltas or has_critical_warnings(warnings) or agents_success < control_success or non_cached_delta >= 0:
        verdict = "not_effective"
    elif secondary_warnings:
        verdict = "mixed"
    else:
        verdict = "effective"

    model = rows[0].get("model", "") if rows else ""
    codex_version = rows[0].get("codex_version", "") if rows else ""
    fixture_commit = rows[0].get("fixture_commit", "") if rows else ""
    task_ids = sorted({str(row.get("task_id", "")) for row in rows if row.get("task_id")})
    repeats = sorted({int(row["repeat"]) for row in rows if str(row.get("repeat", "")).isdigit()})
    integrity_summary = summary.get("integrity", {}) if isinstance(summary.get("integrity", {}), dict) else {}
    batch_ids = integrity_summary.get("batch_ids", []) if isinstance(integrity_summary, dict) else []
    subject_fingerprints = integrity_summary.get("subject_fingerprints", []) if isinstance(integrity_summary, dict) else []
    run_config_fingerprints = integrity_summary.get("run_config_fingerprints", []) if isinstance(integrity_summary, dict) else []
    first_subject_row = subject_rows[0] if subject_rows else {}
    try:
        largest_files = json.loads(str(first_subject_row.get("subject_largest_files", "[]")))
    except json.JSONDecodeError:
        largest_files = []
    readable_largest_files = []
    for item in largest_files:
        if isinstance(item, dict):
            readable = dict(item)
            readable["size"] = human_bytes(readable.get("bytes", 0))
            readable_largest_files.append(readable)

    result = {
        "verdict": verdict,
        "primary_metric": "non_cached_input_tokens",
        "primary_delta": {
            "agents_minus_control": non_cached_delta,
            "delta_basis": "paired_median_of_repeat_deltas",
            "percent": percent_delta(non_cached_delta, control_non_cached),
            "agents_median": agents_non_cached,
            "control_median": control_non_cached,
            "variant_median_delta": agents_non_cached - control_non_cached,
        },
        "quality": {
            "agents_success_rate": agents_success,
            "control_success_rate": control_success,
        },
        "final_relevant_files": {
            "repo_relative_only": not raw_non_repo_relative_relevant_files,
            "normalized_repo_relative_only": not non_repo_relative_relevant_files,
            "non_repo_relative_paths": non_repo_relative_relevant_files,
            "raw_non_repo_relative_paths": raw_non_repo_relative_relevant_files,
            "missing_expected_paths": missing_expected_relevant_files,
        },
        "secondary": {
            "total_observed_tokens_delta": total_delta,
            "wall_seconds_delta": wall_delta,
            "stdout_bytes_delta": stdout_delta,
            "stderr_bytes_delta": stderr_delta,
            "command_count_delta": command_delta,
            "risky_full_reads_delta": risky_delta,
            "large_text_events_over_20kb_delta": large_text_delta,
            "first_expected_file_event_index_delta": first_expected_delta,
        },
        "warnings": warnings + secondary_warnings + subject_warning_values,
        "warning_details": warning_details(warnings + secondary_warnings + subject_warning_values),
        "benchmark_warnings": benchmark_warnings,
        "benchmark_warning_details": warning_details(benchmark_warnings),
        "analysis_warnings": warnings,
        "secondary_warnings": secondary_warnings,
        "subject_warnings": subject_warning_values,
        "reliability": {
            "level": reliability_level,
            "paired_runs": len(deltas),
            "warnings": reliability_warnings,
            "warning_details": warning_details(reliability_warnings),
        },
        "tool_sanity": dict(TOOL_SANITY),
        "integrity": {
            "status": "failed" if has_integrity_warnings(warnings) else "ok",
            "batch_id": batch_ids[0] if len(batch_ids) == 1 else "",
            "batch_ids": batch_ids,
            "subject_fingerprint": subject_fingerprints[0] if len(subject_fingerprints) == 1 else "",
            "subject_fingerprints": subject_fingerprints,
            "run_config_fingerprint": run_config_fingerprints[0] if len(run_config_fingerprints) == 1 else "",
            "run_config_fingerprints": run_config_fingerprints,
        },
        "context": {
            "runs": summary.get("runs", 0),
            "model": model,
            "codex_version": codex_version,
            "fixture_commit": fixture_commit,
            "task_ids": task_ids,
            "repeats": repeats,
        },
        "isolation": {
            "isolated_codex_home": bool(first_subject_row.get("isolated_codex_home")),
            "ignore_user_config": bool(first_subject_row.get("ignore_user_config")),
            "ignore_rules": bool(first_subject_row.get("ignore_rules")),
            "home_codex_excluded": bool(first_subject_row.get("home_codex_excluded")),
        },
        "subject": {
            "mode": first_subject_row.get("subject_mode", ""),
            "source_file_count": first_subject_row.get("agents_source_file_count", 0),
            "total_bytes": first_subject_row.get("subject_total_bytes", 0),
            "total_size": human_bytes(first_subject_row.get("subject_total_bytes", 0)),
            "warnings": subject_warning_values,
            "warning_details": warning_details(subject_warning_values),
            "largest_files": readable_largest_files,
        },
    }
    result["decision"] = decision_summary(result)
    return result


def format_number(value: Any) -> str:
    numeric = number(value)
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.1f}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def format_warning_list(warnings: Any) -> str:
    if not warnings:
        return "none"
    if isinstance(warnings, list):
        return ", ".join(str(warning) for warning in warnings) if warnings else "none"
    return str(warnings)


def write_result_markdown(path: Path, result: dict[str, Any]) -> None:
    primary = result["primary_delta"]
    quality = result["quality"]
    secondary = result["secondary"]
    final_relevant = result.get("final_relevant_files", {})
    decision = result.get("decision", {})
    benchmark_warnings = result.get("benchmark_warnings", result["warnings"])
    subject = result.get("subject", {})
    reliability = result.get("reliability", {})
    isolation = result.get("isolation", {})
    integrity = result.get("integrity", {})
    tool_sanity = result.get("tool_sanity", {})
    artifacts = result.get("artifacts", {})
    raw_results_dir = artifacts.get("raw_results_dir", "raw/") if isinstance(artifacts, dict) else "raw/"
    lines = [
        "# Tokenmessung Result",
        "",
        f"Verdict: **{result['verdict']}**",
        "",
        "## Decision Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Decision | {decision.get('decision', 'n/a') if isinstance(decision, dict) else 'n/a'} |",
        f"| Next action | {decision.get('next_action', 'n/a') if isinstance(decision, dict) else 'n/a'} |",
        f"| Primary metric | {decision.get('primary_metric_basis', 'paired_median_non_cached_input_delta') if isinstance(decision, dict) else 'paired_median_non_cached_input_delta'} |",
        f"| Quality gate | {'passed' if isinstance(decision, dict) and decision.get('quality_gate_passed') else 'failed'} |",
        f"| Warnings | {format_warning_list(benchmark_warnings)} |",
        f"| Global claim eligibility | {decision.get('global_claim_eligibility', 'single-task only / not enough evidence') if isinstance(decision, dict) else 'single-task only / not enough evidence'} |",
        "",
        "Variant medians are secondary context; the decision uses paired median non-cached input delta plus quality gates.",
        "",
        "## Scorecard",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Paired median non-cached input delta | {format_number(primary['agents_minus_control'])} ({format_percent(primary['percent'])}) |",
        f"| Delta basis | {primary.get('delta_basis', 'paired_median_of_repeat_deltas')} |",
        f"| Agents variant median non-cached input | {format_number(primary['agents_median'])} |",
        f"| Control variant median non-cached input | {format_number(primary['control_median'])} |",
        f"| Unpaired variant median delta | {format_number(primary.get('variant_median_delta', 0))} |",
        f"| Agents success rate | {quality['agents_success_rate']:.2f} |",
        f"| Control success rate | {quality['control_success_rate']:.2f} |",
        f"| Repo-relative `relevant_files` only | {final_relevant.get('repo_relative_only', False) if isinstance(final_relevant, dict) else False} |",
        f"| Total observed token delta | {format_number(secondary['total_observed_tokens_delta'])} |",
        f"| Wall time delta | {format_number(secondary['wall_seconds_delta'])}s |",
        f"| Command output delta | {human_bytes(secondary.get('stdout_bytes_delta', 0) + secondary.get('stderr_bytes_delta', 0))} ({format_number(secondary.get('stdout_bytes_delta', 0) + secondary.get('stderr_bytes_delta', 0))} bytes) |",
        f"| Large text event delta | {format_number(secondary.get('large_text_events_over_20kb_delta', 0))} |",
        f"| Command count delta | {format_number(secondary['command_count_delta'])} |",
        f"| First relevant file event delta | {format_number(secondary.get('first_expected_file_event_index_delta', 0))} |",
        f"| Subject mode | {subject.get('mode', 'n/a') if isinstance(subject, dict) else 'n/a'} |",
        f"| Subject files | {format_number(subject.get('source_file_count', 0) if isinstance(subject, dict) else 0)} |",
        f"| Subject size | {human_bytes(subject.get('total_bytes', 0) if isinstance(subject, dict) else 0)} ({format_number(subject.get('total_bytes', 0) if isinstance(subject, dict) else 0)} bytes) |",
        f"| Paired runs | {format_number(reliability.get('paired_runs', 0) if isinstance(reliability, dict) else 0)} |",
        f"| Reliability | {reliability.get('level', 'n/a') if isinstance(reliability, dict) else 'n/a'} |",
        f"| Batch ID | {integrity.get('batch_id', 'n/a') if isinstance(integrity, dict) else 'n/a'} |",
        f"| Subject fingerprint | {integrity.get('subject_fingerprint', 'n/a') if isinstance(integrity, dict) else 'n/a'} |",
        f"| Run config fingerprint | {integrity.get('run_config_fingerprint', 'n/a') if isinstance(integrity, dict) else 'n/a'} |",
        f"| Home `~/.codex/` excluded | {isolation.get('home_codex_excluded', False) if isinstance(isolation, dict) else False} |",
        "",
        "## Interpretation",
        "",
    ]
    if result["verdict"] == "effective":
        lines.append("The measured instruction package reduced non-cached input tokens without failing the quality checks.")
    elif result["verdict"] == "mixed":
        lines.append("The measured instruction package improved the primary token metric, but one or more secondary metrics got worse.")
    else:
        lines.append("The measured instruction package did not produce a reliable improvement in this run.")
    if isinstance(reliability, dict) and reliability.get("warnings"):
        lines.append("")
        lines.append("This result is a smoke measurement. Repeat it before treating the verdict as stable.")
    lines.extend(["", "## Tool Sanity", ""])
    if isinstance(tool_sanity, dict):
        lines.append(f"- Schema version: {tool_sanity.get('schema_version', 'n/a')}")
        lines.append(f"- Run isolation reporting: {tool_sanity.get('run_isolation_reporting', False)}")
        lines.append(f"- Separated warning sections: {tool_sanity.get('separated_warning_sections', False)}")
        lines.append(f"- Aggregated command output counted: {tool_sanity.get('aggregated_command_output_counted', False)}")
    lines.extend(["", "## Final Relevant Files", ""])
    if isinstance(final_relevant, dict):
        lines.append(f"- Repo-relative only: {final_relevant.get('repo_relative_only', False)}")
        lines.append(f"- Normalized repo-relative only: {final_relevant.get('normalized_repo_relative_only', False)}")
        non_relative_paths = final_relevant.get("non_repo_relative_paths", [])
        if non_relative_paths:
            lines.extend(f"- Non-repo-relative path after normalisation: `{path}`" for path in non_relative_paths)
        raw_non_relative_paths = final_relevant.get("raw_non_repo_relative_paths", [])
        if raw_non_relative_paths:
            lines.extend(f"- Raw non-repo-relative path: `{path}`" for path in raw_non_relative_paths)
        missing_expected_paths = final_relevant.get("missing_expected_paths", [])
        if missing_expected_paths:
            lines.extend(f"- Missing expected relevant file: `{path}`" for path in missing_expected_paths)
    lines.extend(["", "## Integrity", ""])
    if isinstance(integrity, dict):
        lines.append(f"- Status: {integrity.get('status', 'n/a')}")
        lines.append(f"- Batch ID: `{integrity.get('batch_id') or 'n/a'}`")
        lines.append(f"- Subject fingerprint: `{integrity.get('subject_fingerprint') or 'n/a'}`")
        lines.append(f"- Run config fingerprint: `{integrity.get('run_config_fingerprint') or 'n/a'}`")
        if len(integrity.get("batch_ids", [])) > 1:
            lines.append(f"- Observed batch IDs: `{', '.join(integrity.get('batch_ids', []))}`")
        if len(integrity.get("subject_fingerprints", [])) > 1:
            lines.append(f"- Observed subject fingerprints: `{', '.join(integrity.get('subject_fingerprints', []))}`")
        if len(integrity.get("run_config_fingerprints", [])) > 1:
            lines.append(f"- Observed run config fingerprints: `{', '.join(integrity.get('run_config_fingerprints', []))}`")
    lines.extend(["", "## Subject", ""])
    if isinstance(subject, dict):
        lines.append(f"- Mode: `{subject.get('mode', 'n/a')}`")
        lines.append(f"- Files: {format_number(subject.get('source_file_count', 0))}")
        lines.append(f"- Size: {human_bytes(subject.get('total_bytes', 0))} ({format_number(subject.get('total_bytes', 0))} bytes)")
        subject_warnings = subject.get("warnings", [])
        if subject_warnings:
            lines.extend(f"- Subject warning `{warning}`: {explain_warning(str(warning))}" for warning in subject_warnings)
        else:
            lines.append("- Subject warnings: none")
        largest_files = subject.get("largest_files", [])
        if largest_files:
            lines.extend(["", "Largest subject files:", ""])
            lines.extend(f"- `{item.get('path')}`: {human_bytes(item.get('bytes', 0))} ({format_number(item.get('bytes', 0))} bytes)" for item in largest_files[:5] if isinstance(item, dict))
    lines.extend(["", "## Isolation", ""])
    if isinstance(isolation, dict):
        lines.append(f"- Isolated per-run `CODEX_HOME`: {isolation.get('isolated_codex_home', False)}")
        lines.append(f"- User config ignored: {isolation.get('ignore_user_config', False)}")
        lines.append(f"- External rules ignored: {isolation.get('ignore_rules', False)}")
        lines.append(f"- Home `~/.codex/` excluded from the measured instruction source: {isolation.get('home_codex_excluded', False)}")
    lines.extend(["", "## Benchmark Warnings", ""])
    if benchmark_warnings:
        lines.extend(f"- `{warning}`: {explain_warning(str(warning))}" for warning in benchmark_warnings)
    else:
        lines.append("- None")
    if isinstance(reliability, dict) and reliability.get("warnings"):
        lines.extend(["", "## Reliability", ""])
        lines.extend(f"- `{warning}`: {explain_warning(str(warning))}" for warning in reliability.get("warnings", []))
    lines.extend(["", "## Raw Data", "", f"Detailed run artefacts are kept under `{raw_results_dir}` for audit and debugging."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze_results(results: Path, large_text_bytes: int = LARGE_TEXT_BYTES, output_dir: Path | None = None) -> dict[str, Path]:
    rows = [parse_run(meta.parent, large_text_bytes=large_text_bytes) for meta in sorted(results.glob("*/meta.json"))]
    if not rows:
        raise FileNotFoundError(f"No run metadata found under {results}")
    output = output_dir or results
    output.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda row: (str(row["task_id"]), int(row["repeat"]), str(row["variant"])))
    deltas = paired_deltas(rows)
    warnings = integrity_warnings(rows) + incomplete_pair_warnings(rows)
    for row in rows:
        if row.get("analysis_warnings"):
            warnings.extend(str(row["analysis_warnings"]).split(";"))
    summary = aggregate(rows, deltas, warnings)
    result = build_result(summary, deltas, rows)
    summary_csv = output / "summary.csv"
    summary_json = output / "summary.json"
    deltas_csv = output / "paired-deltas.csv"
    result_json = output / "result.json"
    result_md = output / "RESULT.md"
    write_csv(summary_csv, rows)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if deltas:
        write_csv(deltas_csv, deltas)
    else:
        deltas_csv.write_text("", encoding="utf-8")
    result["artifacts"] = {
        "result_json": str(result_json),
        "result_md": str(result_md),
        "summary_csv": str(summary_csv),
        "summary_json": str(summary_json),
        "paired_deltas_csv": str(deltas_csv),
        "raw_results_dir": str(results),
    }
    result_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_result_markdown(result_md, result)
    return {
        "summary_csv": summary_csv,
        "summary_json": summary_json,
        "paired_deltas_csv": deltas_csv,
        "result_json": result_json,
        "result_md": result_md,
    }
