from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scaldex.analyzer import analyze_results, build_result, decision_summary, human_bytes, paired_deltas, parse_run, write_codex_handoff_markdown


def write_run(
    base: Path,
    run_id: str,
    variant: str,
    tokens: int,
    *,
    include_usage: bool = True,
    valid_final: bool = True,
    exit_code: str = "0",
    batch_id: str = "batch-test",
    subject_fingerprint: str = "subject-test",
    run_config_fingerprint: str = "config-test",
    expected_run_count: int = 2,
    relevant_files: list[str] | None = None,
    workdir: Path | None = None,
) -> None:
    run = base / run_id
    run.mkdir()
    task = {
        "id": "login_test_failure",
        "expected_files": ["services/auth/src/login.ts"],
        "expected_terms": ["passwordPolicy"],
    }
    meta = {
        "run_id": run_id,
        "batch_id": batch_id,
        "subject_fingerprint": subject_fingerprint,
        "run_config": {
            "model": "test-model",
            "task_ids": ["login_test_failure"],
            "repeats": 1,
            "seed": 1,
            "subject_mode": "package",
            "fixture_commit": "abc",
            "variants": ["agents", "control"],
            "expected_run_count": expected_run_count,
        },
        "run_config_fingerprint": run_config_fingerprint,
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
            "fingerprint": subject_fingerprint,
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
        "workdir": str(workdir) if workdir is not None else "",
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
        final_relevant_files = relevant_files if relevant_files is not None else ["services/auth/src/login.ts"]
        (run / "final.json").write_text(
            json.dumps(
                {
                    "answer": "see services/auth/src/login.ts",
                    "relevant_files": final_relevant_files,
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
    def test_codex_handoff_contract_covers_all_next_actions(self) -> None:
        cases = [
            ("eligible_for_decision_run", "Tell the user to run this decision-grade command", "Do not optimize AGENTS.md/.codex yet"),
            ("stop_fix_quality_or_task_behavior", "Analyze the listed quality or integrity blockers", "Do not treat token reductions as wins"),
            ("record_decision_grade_win", "Record this report as decision-grade evidence", "Do not make a global efficiency claim"),
            ("do_not_claim_efficiency", "Analyze task-specific behaviour", "Do not claim token efficiency"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for next_action, requested, forbidden in cases:
                result = {
                    "verdict": "effective",
                    "primary_delta": {"agents_minus_control": -10, "percent": -10.0},
                    "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
                    "final_relevant_files": {
                        "repo_relative_only": False,
                        "normalized_repo_relative_only": True,
                        "raw_non_repo_relative_paths": ["/private/tmp/workspace/repo/services/auth/src/login.ts"],
                    },
                    "decision": {
                        "decision": "fixture",
                        "next_action": next_action,
                        "reason": "fixture_reason",
                        "explanation": "fixture explanation",
                        "decision_grade": next_action in ("record_decision_grade_win", "do_not_claim_efficiency"),
                        "quality_gate_passed": next_action != "stop_fix_quality_or_task_behavior",
                        "global_claim_eligibility": "single-task only / not enough evidence",
                    },
                    "reliability": {"paired_runs": 3 if next_action in ("record_decision_grade_win", "do_not_claim_efficiency") else 1},
                    "integrity": {"subject_fingerprint": "subject", "run_config_fingerprint": "config", "batch_id": "batch"},
                    "context": {"task_ids": ["login_test_failure"]},
                    "benchmark_warnings": [] if next_action != "stop_fix_quality_or_task_behavior" else ["missing_expected_files"],
                    "subject": {"total_bytes": 10, "source_file_count": 1},
                    "run_config": {"model": "gpt-test", "subject_dir": "subject", "task_ids": ["login_test_failure"], "subject_mode": "package"},
                }
                path = base / f"{next_action}.md"
                write_codex_handoff_markdown(path, result)
                text = path.read_text(encoding="utf-8")
                self.assertIn("# scaldex codex instruction", text)
                self.assertIn("Role: You are Codex analyzing a scaldex benchmark result.", text)
                self.assertIn("## Requested Action", text)
                self.assertIn(requested, text)
                self.assertIn("## Primary Metric", text)
                self.assertIn("paired_median_non_cached_input_delta", text)
                self.assertIn("variant medians are secondary context only", text)
                self.assertIn("## Quality Gates", text)
                self.assertIn("Raw non-repo-relative paths before normalisation: `1 path(s); omitted from this handoff to avoid leaking local workspace paths`", text)
                self.assertNotIn("/private/tmp/workspace", text)
                self.assertIn("## Allowed Actions", text)
                self.assertIn("## Forbidden Actions", text)
                self.assertIn(forbidden, text)
                self.assertIn("## Files To Inspect Next", text)
                self.assertIn("## Output Expected From Codex", text)

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
            self.assertEqual(row["expected_relevant_files_found_count"], 1)
            self.assertTrue(row["repo_relative_relevant_files_only"])
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
            self.assertEqual(result["primary_delta"]["delta_basis"], "paired_median_of_repeat_deltas")
            self.assertIn("variant_median_delta", result["primary_delta"])
            self.assertEqual(result["subject"]["mode"], "package")
            self.assertEqual(result["subject"]["total_size"], "39.1 KiB")
            self.assertEqual(result["subject"]["largest_files"][0]["size"], "29.3 KiB")
            self.assertTrue(result["isolation"]["home_codex_excluded"])
            self.assertIn("large_subject", result["warnings"])
            self.assertNotIn("large_subject", result["benchmark_warnings"])
            self.assertEqual(result["reliability"]["level"], "low")
            self.assertIn("low_sample_size", result["reliability"]["warnings"])
            self.assertEqual(result["decision"]["next_action"], "eligible_for_decision_run")
            self.assertEqual(result["decision"]["decision"], "smoke_passed")
            self.assertIn("smoke run is clean", result["decision"]["explanation"])
            self.assertEqual(result["decision"]["scope"], "task")
            self.assertEqual(result["decision"]["global_claim_eligibility"], "single-task only / not enough evidence")
            self.assertTrue(result["decision"]["quality_gate_passed"])
            self.assertFalse(result["decision"]["uses_unpaired_variant_medians_for_decision"])
            self.assertEqual(result["tool_sanity"]["schema_version"], 1)
            self.assertTrue(result["tool_sanity"]["aggregated_command_output_counted"])
            self.assertTrue(result["final_relevant_files"]["repo_relative_only"])
            self.assertEqual(result["integrity"]["status"], "ok")
            self.assertEqual(result["integrity"]["batch_id"], "batch-test")
            self.assertEqual(result["integrity"]["subject_fingerprint"], "subject-test")
            self.assertEqual(result["integrity"]["run_config_fingerprint"], "config-test")
            self.assertIn("warning_details", result)
            result_md = paths["result_md"].read_text(encoding="utf-8")
            self.assertTrue(result_md.startswith("# scaldex result"))
            self.assertIn("## Decision Summary", result_md)
            self.assertIn("| Next action | eligible_for_decision_run |", result_md)
            self.assertIn("| Reason | smoke_passed_needs_decision_grade |", result_md)
            self.assertIn("| Explanation | This smoke run is clean", result_md)
            self.assertIn("| Quality gate | passed |", result_md)
            self.assertIn("| Global claim eligibility | single-task only / not enough evidence |", result_md)
            self.assertIn("## Glossary", result_md)
            self.assertIn("`agents`: the run with the measured `AGENTS.md`/`.codex` package installed.", result_md)
            self.assertIn("`control`: the same task run without that measured instruction package.", result_md)
            self.assertIn("`paired delta`: the agents result minus the matching control result", result_md)
            self.assertIn("`fingerprint`: an ID for the measured subject or run settings", result_md)
            self.assertIn("`normalized repo-relative relevant_files`: final file paths were normalized", result_md)
            self.assertIn("Variant medians are secondary context", result_md)
            self.assertIn("Paired median non-cached input delta", result_md)
            self.assertIn("Unpaired variant median delta", result_md)
            self.assertIn("## Tool Sanity", result_md)
            self.assertIn("## Final Relevant Files", result_md)
            self.assertIn("## Integrity", result_md)
            self.assertIn("Aggregated command output counted: True", result_md)
            handoff_md = paths["codex_handoff_md"].read_text(encoding="utf-8")
            self.assertIn("# scaldex codex instruction", handoff_md)
            self.assertIn("Role: You are Codex analyzing a scaldex benchmark result.", handoff_md)
            self.assertIn("## Requested Action", handoff_md)
            self.assertIn("## Decision Status", handoff_md)
            self.assertIn("- Next action code: `eligible_for_decision_run`", handoff_md)
            self.assertIn("- Reason: `smoke_passed_needs_decision_grade`", handoff_md)
            self.assertIn("- Explanation: This smoke run is clean", handoff_md)
            self.assertIn("## Primary Metric", handoff_md)
            self.assertIn("- Primary metric: `paired_median_non_cached_input_delta`", handoff_md)
            self.assertIn("variant medians are secondary context only", handoff_md)
            self.assertIn("## Quality Gates", handoff_md)
            self.assertIn("- Quality gate: `passed`", handoff_md)
            self.assertIn("## Allowed Actions", handoff_md)
            self.assertIn("## Forbidden Actions", handoff_md)
            self.assertIn("Do not optimize AGENTS.md/.codex yet", handoff_md)
            self.assertIn("## Files To Inspect Next", handoff_md)
            self.assertIn("## Output Expected From Codex", handoff_md)
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

    def test_analyzer_flags_non_repo_relative_relevant_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "control", "control", 1000)
            write_run(base, "agents", "agents", 700, relevant_files=["/tmp/repo/services/auth/src/login.ts"])
            paths = analyze_results(base)
            result = json.loads(paths["result_json"].read_text(encoding="utf-8"))
            self.assertEqual(result["verdict"], "not_effective")
            self.assertEqual(result["decision"]["next_action"], "stop_fix_quality_or_task_behavior")
            self.assertFalse(result["final_relevant_files"]["repo_relative_only"])
            self.assertIn("/tmp/repo/services/auth/src/login.ts", result["final_relevant_files"]["non_repo_relative_paths"])
            self.assertIn("/tmp/repo/services/auth/src/login.ts", result["final_relevant_files"]["raw_non_repo_relative_paths"])
            self.assertIn("non_repo_relative_relevant_files", result["benchmark_warnings"])
            agents_row = parse_run(base / "agents")
            self.assertFalse(agents_row["repo_relative_relevant_files_only"])
            self.assertIn("non_repo_relative_relevant_files", agents_row["analysis_warnings"])

    def test_analyzer_normalises_workspace_absolute_relevant_files_for_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "workspace" / "repo"
            repo.mkdir(parents=True)
            absolute_relevant = str(repo / "services/auth/src/login.ts")
            write_run(base, "control", "control", 1000, relevant_files=[absolute_relevant], workdir=repo)
            write_run(base, "agents", "agents", 700, workdir=repo)
            paths = analyze_results(base)
            result = json.loads(paths["result_json"].read_text(encoding="utf-8"))
            self.assertEqual(result["verdict"], "effective")
            self.assertFalse(result["final_relevant_files"]["repo_relative_only"])
            self.assertTrue(result["final_relevant_files"]["normalized_repo_relative_only"])
            self.assertIn(absolute_relevant, result["final_relevant_files"]["raw_non_repo_relative_paths"])
            self.assertNotIn("missing_expected_relevant_files", result["benchmark_warnings"])
            self.assertNotIn("non_repo_relative_relevant_files", result["benchmark_warnings"])
            control_row = parse_run(base / "control")
            self.assertTrue(control_row["success"])
            self.assertEqual(control_row["final_relevant_files"], "services/auth/src/login.ts")
            self.assertEqual(control_row["expected_relevant_files_found_count"], 1)
            self.assertEqual(control_row["raw_non_repo_relative_relevant_files_count"], 1)

    def test_analyzer_flags_missing_expected_relevant_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "control", "control", 1000)
            write_run(base, "agents", "agents", 700, relevant_files=["services/auth/src/other.ts"])
            paths = analyze_results(base)
            result = json.loads(paths["result_json"].read_text(encoding="utf-8"))
            self.assertEqual(result["verdict"], "not_effective")
            self.assertEqual(result["decision"]["next_action"], "stop_fix_quality_or_task_behavior")
            self.assertIn("missing_expected_relevant_files", result["benchmark_warnings"])
            self.assertIn("services/auth/src/login.ts", result["final_relevant_files"]["missing_expected_paths"])

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

    def test_analyzer_flags_mixed_integrity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "control", "control", 1000, batch_id="batch-a", subject_fingerprint="subject-a", run_config_fingerprint="config-a")
            write_run(base, "agents", "agents", 700, batch_id="batch-b", subject_fingerprint="subject-b", run_config_fingerprint="config-b")
            paths = analyze_results(base)
            summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
            self.assertIn("mixed_batch_ids", summary["analysis_warnings"])
            self.assertIn("mixed_subject_fingerprints", summary["analysis_warnings"])
            self.assertIn("mixed_run_config_fingerprints", summary["analysis_warnings"])
            result = json.loads(paths["result_json"].read_text(encoding="utf-8"))
            self.assertEqual(result["verdict"], "not_effective")
            self.assertEqual(result["integrity"]["status"], "failed")

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
                    "median_stdout_bytes": 25000,
                    "median_stderr_bytes": 0,
                },
                "control": {
                    "success_rate": 1.0,
                    "median_non_cached_input_tokens": 1000,
                    "median_total_observed_tokens": 10000,
                    "median_wall_seconds": 10,
                    "median_stdout_bytes": 0,
                    "median_stderr_bytes": 0,
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

    def test_command_output_warning_requires_relative_regression(self) -> None:
        summary = {
            "runs": 6,
            "analysis_warnings": [],
            "variants": {
                "agents": {
                    "success_rate": 1.0,
                    "median_non_cached_input_tokens": 900,
                    "median_total_observed_tokens": 10000,
                    "median_wall_seconds": 10,
                    "median_stdout_bytes": 356000,
                    "median_stderr_bytes": 0,
                },
                "control": {
                    "success_rate": 1.0,
                    "median_non_cached_input_tokens": 1000,
                    "median_total_observed_tokens": 10000,
                    "median_wall_seconds": 10,
                    "median_stdout_bytes": 332000,
                    "median_stderr_bytes": 0,
                },
            },
            "paired_median_deltas": {
                "median_delta_non_cached_input_tokens_agents_minus_control": -100,
                "median_delta_total_observed_tokens_agents_minus_control": 0,
                "median_delta_wall_seconds_agents_minus_control": 0,
                "median_delta_stdout_bytes_agents_minus_control": 24000,
                "median_delta_stderr_bytes_agents_minus_control": 0,
                "median_delta_command_count_agents_minus_control": 0,
                "median_delta_risky_full_reads_agents_minus_control": 0,
                "median_delta_large_text_events_over_20kb_agents_minus_control": 0,
                "median_delta_first_expected_file_event_index_agents_minus_control": 0,
            },
        }
        result = build_result(summary, [{"task_id": "x"}, {"task_id": "x"}, {"task_id": "x"}], [{"task_id": "t", "repeat": 1}])
        self.assertNotIn("command_output_bytes_increased", result["benchmark_warnings"])

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
        self.assertEqual(result["decision"]["next_action"], "record_decision_grade_win")
        self.assertEqual(result["decision"]["decision"], "decision_grade_effective")
        self.assertEqual(result["decision"]["reason"], "primary_delta_negative_quality_passed")
        self.assertIn("Decision-grade evidence", result["decision"]["explanation"])

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
        self.assertEqual(result["decision"]["reason"], "smoke_passed_needs_decision_grade")
        self.assertIn("repeat the same task", result["decision"]["explanation"])

    def test_decision_summary_reports_do_not_claim_for_decision_grade_failure(self) -> None:
        result = {
            "verdict": "not_effective",
            "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
            "benchmark_warnings": [],
            "final_relevant_files": {"normalized_repo_relative_only": True},
            "reliability": {"paired_runs": 3},
        }
        self.assertEqual(decision_summary(result)["next_action"], "do_not_claim_efficiency")
        self.assertEqual(decision_summary(result)["decision"], "decision_grade_not_effective")
        self.assertEqual(decision_summary(result)["reason"], "primary_delta_non_negative")
        self.assertIn("did not reduce", decision_summary(result)["explanation"])

    def test_decision_summary_uses_result_set_language_for_multi_task_results(self) -> None:
        result = {
            "verdict": "effective",
            "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
            "primary_delta": {"agents_minus_control": -100},
            "benchmark_warnings": [],
            "final_relevant_files": {"normalized_repo_relative_only": True},
            "reliability": {"paired_runs": 3},
            "context": {"task_ids": ["login_test_failure", "feature_x_plan"]},
        }
        decision = decision_summary(result)
        self.assertIn("for this result set", decision["explanation"])
        self.assertEqual(decision["scope"], "result_set")
        self.assertEqual(decision["global_claim_eligibility"], "multi-task result set / use summary eligibility rule")

    def test_decision_summary_reports_stop_for_smoke_quality_failure(self) -> None:
        result = {
            "verdict": "effective",
            "quality": {"agents_success_rate": 0.5, "control_success_rate": 1.0},
            "benchmark_warnings": [],
            "final_relevant_files": {"normalized_repo_relative_only": True},
            "reliability": {"paired_runs": 1},
        }
        self.assertEqual(decision_summary(result)["next_action"], "stop_fix_quality_or_task_behavior")
        self.assertEqual(decision_summary(result)["reason"], "quality_gate_failed")
        self.assertIn("Stop before spending more", decision_summary(result)["explanation"])

    def test_human_bytes_formats_sizes(self) -> None:
        self.assertEqual(human_bytes(999), "999 B")
        self.assertEqual(human_bytes(228074), "222.7 KiB")
        self.assertEqual(human_bytes(5 * 1024 * 1024), "5.0 MiB")


if __name__ == "__main__":
    unittest.main()
