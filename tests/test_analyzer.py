from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tokenmessung.analyzer import analyze_results, build_result, human_bytes, paired_deltas, parse_run


def write_run(base: Path, run_id: str, variant: str, tokens: int, *, include_usage: bool = True, valid_final: bool = True, exit_code: str = "0") -> None:
    run = base / run_id
    run.mkdir()
    task = {
        "id": "login_test_failure",
        "expected_files": ["services/auth/src/login.ts"],
        "expected_terms": ["passwordPolicy"],
    }
    meta = {
        "run_id": run_id,
        "task_id": "login_test_failure",
        "task": task,
        "variant": variant,
        "repeat": 1,
        "run_order": 1 if variant == "control" else 2,
        "model": "test-model",
        "fixture_commit": "abc",
        "agents_file_bytes": 10,
        "subject_mode": "package",
        "agents_source_file_count": 3,
        "subject_audit": {
            "mode": "package",
            "source_type": "dir",
            "path": "subject",
            "file_count": 3,
            "total_bytes": 40000,
            "largest_files": [{"path": ".codex/instructions.md", "bytes": 30000}],
            "warnings": ["large_subject"] if variant == "agents" else [],
        },
        "run_isolation": {
            "ephemeral": True,
            "ignore_user_config": True,
            "ignore_rules": True,
            "isolated_codex_home": True,
            "home_codex_excluded": True,
        },
    }
    (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "bash -lc 'rg passwordPolicy services/auth/src/login.ts'", "stdout": "services/auth/src/login.ts passwordPolicy"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "bash -lc 'cat logs/app.log'", "stdout": "x" * 21000}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "bash -lc 'rg noisy logs/app.log'", "aggregated_output": "y" * 22000}},
        {"type": "unknown.future", "payload": {"usage": {"input_tokens": 1}}},
    ]
    if include_usage:
        events.insert(3, {"type": "turn.completed", "usage": {"input_tokens": tokens, "cached_input_tokens": 100, "output_tokens": 20, "reasoning_output_tokens": 5}})
    (run / "codex.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    if valid_final:
        (run / "final.json").write_text(
            json.dumps(
                {
                    "answer": "see services/auth/src/login.ts",
                    "relevant_files": ["services/auth/src/login.ts"],
                    "root_cause_or_location": "passwordPolicy",
                    "confidence": "high",
                }
            ),
            encoding="utf-8",
        )
    else:
        (run / "final.json").write_text("{not-json", encoding="utf-8")
    (run / "exit_code.txt").write_text(f"{exit_code}\n", encoding="utf-8")
    (run / "time.json").write_text(json.dumps({"wall_seconds": 1.5}), encoding="utf-8")


class AnalyzerTests(unittest.TestCase):
    def test_parse_run_extracts_usage_and_context_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "r1", "control", 1000)
            row = parse_run(base / "r1")
            self.assertEqual(row["input_tokens"], 1000)
            self.assertEqual(row["cached_input_tokens"], 100)
            self.assertEqual(row["non_cached_input_tokens"], 900)
            self.assertEqual(row["targeted_steps"], 2)
            self.assertEqual(row["risky_full_reads"], 1)
            self.assertGreaterEqual(row["stdout_bytes"], 43000)
            self.assertEqual(row["large_text_events_over_20kb"], 2)
            self.assertEqual(row["subject_total_bytes"], 40000)
            self.assertTrue(row["home_codex_excluded"])
            self.assertTrue(row["success"])

    def test_analyze_results_writes_summary_and_paired_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "control", "control", 1000)
            write_run(base, "agents", "agents", 700)
            paths = analyze_results(base)
            for path in paths.values():
                self.assertTrue(path.exists())
            result = json.loads(paths["result_json"].read_text(encoding="utf-8"))
            self.assertEqual(result["verdict"], "effective")
            self.assertEqual(result["subject"]["mode"], "package")
            self.assertEqual(result["subject"]["total_size"], "39.1 KiB")
            self.assertEqual(result["subject"]["largest_files"][0]["size"], "29.3 KiB")
            self.assertTrue(result["isolation"]["home_codex_excluded"])
            self.assertIn("large_subject", result["warnings"])
            self.assertNotIn("large_subject", result["benchmark_warnings"])
            self.assertEqual(result["reliability"]["level"], "low")
            self.assertIn("low_sample_size", result["reliability"]["warnings"])
            self.assertEqual(result["tool_sanity"]["schema_version"], 1)
            self.assertTrue(result["tool_sanity"]["aggregated_command_output_counted"])
            self.assertIn("warning_details", result)
            result_md = paths["result_md"].read_text(encoding="utf-8")
            self.assertTrue(result_md.startswith("# Tokenmessung Result"))
            self.assertIn("## Tool Sanity", result_md)
            self.assertIn("Aggregated command output counted: True", result_md)
            rows = [parse_run(base / "control"), parse_run(base / "agents")]
            deltas = paired_deltas(rows)
            self.assertEqual(deltas[0]["delta_non_cached_input_tokens_agents_minus_control"], -300)

    def test_parse_run_reports_analysis_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "bad", "control", 1000, include_usage=False, valid_final=False, exit_code="1")
            row = parse_run(base / "bad")
            warnings = set(row["analysis_warnings"].split(";"))
            self.assertIn("missing_turn_completed_usage", warnings)
            self.assertIn("invalid_final_json", warnings)
            self.assertIn("nonzero_exit_code", warnings)

    def test_summary_contains_success_rates_and_pair_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "control", "control", 1000)
            paths = analyze_results(base)
            summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
            self.assertEqual(summary["variants"]["control"]["success_rate"], 1.0)
            self.assertIn("incomplete_pair:login_test_failure:r1", summary["analysis_warnings"])
            result = json.loads(paths["result_json"].read_text(encoding="utf-8"))
            self.assertEqual(result["verdict"], "not_effective")

    def test_build_result_reports_mixed_when_secondary_metrics_regress(self) -> None:
        summary = {
            "runs": 2,
            "analysis_warnings": [],
            "variants": {
                "agents": {
                    "success_rate": 1.0,
                    "median_non_cached_input_tokens": 800,
                    "median_total_observed_tokens": 20000,
                    "median_wall_seconds": 30,
                },
                "control": {
                    "success_rate": 1.0,
                    "median_non_cached_input_tokens": 1000,
                    "median_total_observed_tokens": 10000,
                    "median_wall_seconds": 10,
                },
            },
            "paired_median_deltas": {
                "median_delta_non_cached_input_tokens_agents_minus_control": -200,
                "median_delta_total_observed_tokens_agents_minus_control": 10000,
                "median_delta_wall_seconds_agents_minus_control": 20,
                "median_delta_stdout_bytes_agents_minus_control": 25000,
                "median_delta_stderr_bytes_agents_minus_control": 0,
                "median_delta_command_count_agents_minus_control": 5,
                "median_delta_risky_full_reads_agents_minus_control": 0,
                "median_delta_large_text_events_over_20kb_agents_minus_control": 1,
                "median_delta_first_expected_file_event_index_agents_minus_control": 4,
            },
        }
        result = build_result(summary, [{"task_id": "x"}], [{"model": "m", "codex_version": "c", "fixture_commit": "f", "task_id": "t", "repeat": 1}])
        self.assertEqual(result["verdict"], "mixed")
        self.assertIn("total_observed_tokens_increased", result["warnings"])
        self.assertIn("total_observed_tokens_increased", result["benchmark_warnings"])
        self.assertIn("command_output_bytes_increased", result["benchmark_warnings"])
        self.assertIn("large_text_events_increased", result["benchmark_warnings"])
        self.assertIn("agents_found_relevant_file_later", result["warnings"])

    def test_reliability_is_normal_after_three_pairs(self) -> None:
        summary = {
            "runs": 6,
            "analysis_warnings": [],
            "variants": {
                "agents": {"success_rate": 1.0, "median_non_cached_input_tokens": 800},
                "control": {"success_rate": 1.0, "median_non_cached_input_tokens": 1000},
            },
            "paired_median_deltas": {
                "median_delta_non_cached_input_tokens_agents_minus_control": -200,
            },
        }
        result = build_result(summary, [{"task_id": "x"}, {"task_id": "x"}, {"task_id": "x"}], [{"task_id": "t", "repeat": 1}])
        self.assertEqual(result["reliability"]["level"], "normal")
        self.assertEqual(result["reliability"]["warnings"], [])

    def test_build_result_reports_not_effective_when_primary_metric_regresses(self) -> None:
        summary = {
            "runs": 2,
            "analysis_warnings": [],
            "variants": {
                "agents": {"success_rate": 1.0, "median_non_cached_input_tokens": 1200},
                "control": {"success_rate": 1.0, "median_non_cached_input_tokens": 1000},
            },
            "paired_median_deltas": {
                "median_delta_non_cached_input_tokens_agents_minus_control": 200,
            },
        }
        result = build_result(summary, [{"task_id": "x"}], [{"task_id": "t", "repeat": 1}])
        self.assertEqual(result["verdict"], "not_effective")

    def test_human_bytes_formats_sizes(self) -> None:
        self.assertEqual(human_bytes(999), "999 B")
        self.assertEqual(human_bytes(228074), "222.7 KiB")
        self.assertEqual(human_bytes(5 * 1024 * 1024), "5.0 MiB")


if __name__ == "__main__":
    unittest.main()
