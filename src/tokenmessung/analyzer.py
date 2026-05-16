from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable

LARGE_TEXT_BYTES = 20_000

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
        for key in ("stdout", "stderr", "text", "output"):
            value = node.get(key)
            if not isinstance(value, str):
                continue
            size = text_bytes(value)
            if key == "stdout":
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


def parse_run(run_dir: Path, large_text_bytes: int = LARGE_TEXT_BYTES) -> dict[str, Any]:
    meta = load_json(run_dir / "meta.json", {})
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
    success = final_valid and bool(expected_files) and len(final_expected_files_found) == len(expected_files) and bool(final_expected_terms_found)
    if expected_files and len(expected_files_found) != len(expected_files):
        analysis_warnings.append("missing_expected_files")

    return {
        "run_id": meta.get("run_id", run_dir.name),
        "task_id": meta.get("task_id", ""),
        "variant": meta.get("variant", ""),
        "repeat": meta.get("repeat", ""),
        "run_order": meta.get("run_order", ""),
        "model": meta.get("model", ""),
        "codex_version": meta.get("codex_version", ""),
        "python_version": meta.get("python_version", ""),
        "fixture_commit": meta.get("fixture_commit", ""),
        "agents_file_bytes": meta.get("agents_file_bytes", 0),
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
    summary: dict[str, Any] = {"runs": len(rows), "variants": {}, "analysis_warnings": sorted(set(analysis_warnings))}
    numeric_keys = [
        "input_tokens",
        "cached_input_tokens",
        "non_cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_observed_tokens",
        "command_count",
        "targeted_steps",
        "risky_full_reads",
        "stdout_bytes",
        "stderr_bytes",
        "large_text_events_over_20kb",
        "expected_files_found_count",
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
                paired_metrics[f"median_{key}"] = median(float(row[key]) for row in deltas)
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
    delta_keys = ["non_cached_input_tokens", "total_observed_tokens", "stdout_bytes", "stderr_bytes", "command_count", "risky_full_reads"]
    deltas: list[dict[str, Any]] = []
    for (task_id, repeat), pair in sorted(pairs.items()):
        if "agents" not in pair or "control" not in pair:
            continue
        row: dict[str, Any] = {"task_id": task_id, "repeat": repeat}
        for key in delta_keys:
            row[f"delta_{key}_agents_minus_control"] = float(pair["agents"][key]) - float(pair["control"][key])
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


def analyze_results(results: Path, large_text_bytes: int = LARGE_TEXT_BYTES) -> dict[str, Path]:
    rows = [parse_run(meta.parent, large_text_bytes=large_text_bytes) for meta in sorted(results.glob("*/meta.json"))]
    if not rows:
        raise FileNotFoundError(f"No run metadata found under {results}")
    rows.sort(key=lambda row: (str(row["task_id"]), int(row["repeat"]), str(row["variant"])))
    deltas = paired_deltas(rows)
    warnings = incomplete_pair_warnings(rows)
    for row in rows:
        if row.get("analysis_warnings"):
            warnings.extend(str(row["analysis_warnings"]).split(";"))
    summary = aggregate(rows, deltas, warnings)
    summary_csv = results / "summary.csv"
    summary_json = results / "summary.json"
    deltas_csv = results / "paired-deltas.csv"
    write_csv(summary_csv, rows)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if deltas:
        write_csv(deltas_csv, deltas)
    else:
        deltas_csv.write_text("", encoding="utf-8")
    return {"summary_csv": summary_csv, "summary_json": summary_json, "paired_deltas_csv": deltas_csv}
