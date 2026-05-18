from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tokenmessung.multisummary import build_multi_summary, discover_result_jsons, format_multi_summary_console, summarize_results


def write_result(
    path: Path,
    task_id: str,
    *,
    verdict: str = "effective",
    paired_runs: int = 3,
    agents_quality: float = 1.0,
    control_quality: float = 1.0,
    warnings: list[str] | None = None,
    subject_fingerprint: str = "subject-a",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    warnings = warnings or []
    path.write_text(
        json.dumps(
            {
                "verdict": verdict,
                "context": {"task_ids": [task_id]},
                "primary_delta": {
                    "agents_minus_control": -100,
                    "percent": -10.0,
                    "agents_median": 900,
                    "control_median": 1000,
                },
                "quality": {
                    "agents_success_rate": agents_quality,
                    "control_success_rate": control_quality,
                },
                "benchmark_warnings": warnings,
                "final_relevant_files": {"normalized_repo_relative_only": True},
                "reliability": {"paired_runs": paired_runs},
                "decision": {
                    "decision_grade": paired_runs >= 3,
                    "next_action": "record_decision_grade_win" if paired_runs >= 3 and verdict == "effective" else "eligible_for_decision_run",
                },
                "integrity": {
                    "subject_fingerprint": subject_fingerprint,
                    "run_config_fingerprint": f"config-{task_id}",
                },
                "subject": {"source_file_count": 1, "total_bytes": 10},
            }
        ),
        encoding="utf-8",
    )


def write_multi_task_result(path: Path, task_ids: list[str], *, paired_runs: int = 3, subject_mode: str = "package") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    deltas = path.parent / "paired-deltas.csv"
    deltas.write_text(
        "task_id,repeat,delta_non_cached_input_tokens_agents_minus_control,agents_success,control_success\n"
        + "".join(
            f"{task_id},{repeat},-100,True,True\n"
            for task_id in task_ids
            for repeat in range(1, paired_runs + 1)
        ),
        encoding="utf-8",
    )
    path.write_text(
        json.dumps(
            {
                "verdict": "effective",
                "context": {"task_ids": task_ids, "model": "synthetic" if subject_mode == "synthetic" else "gpt-test"},
                "primary_delta": {
                    "agents_minus_control": -100,
                    "percent": -10.0,
                    "agents_median": 900,
                    "control_median": 1000,
                },
                "quality": {
                    "agents_success_rate": 1.0,
                    "control_success_rate": 1.0,
                },
                "benchmark_warnings": [],
                "final_relevant_files": {"normalized_repo_relative_only": True},
                "reliability": {"paired_runs": paired_runs * len(task_ids)},
                "decision": {"decision_grade": True, "next_action": "record_decision_grade_win"},
                "integrity": {
                    "subject_fingerprint": "subject-a",
                    "run_config_fingerprint": "config-multi",
                },
                "subject": {"mode": subject_mode, "source_file_count": 1, "total_bytes": 10},
                "artifacts": {"paired_deltas_csv": str(deltas)},
            }
        ),
        encoding="utf-8",
    )


class MultiSummaryTests(unittest.TestCase):
    def test_discovers_result_jsons_from_files_and_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            direct = base / "direct-result.json"
            nested = base / "runs" / "task" / "result.json"
            write_result(direct, "login_test_failure")
            write_result(nested, "export_cli_location")
            paths = discover_result_jsons([direct, base / "runs"])
            self.assertEqual(paths, sorted([direct.resolve(), nested.resolve()]))

    def test_build_multi_summary_allows_global_claim_for_three_of_four_effective_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tasks = ["login_test_failure", "export_cli_location", "feature_x_plan", "release_scope_audit"]
            paths = []
            for index, task in enumerate(tasks):
                result_path = base / task / "result.json"
                write_result(result_path, task, verdict="effective" if index < 3 else "not_effective")
                paths.append(result_path)
            summary = build_multi_summary(paths)
            self.assertTrue(summary["global_token_efficiency_claim_allowed"])
            self.assertEqual(summary["global_decision"], "claim_global_token_efficiency")
            self.assertEqual(summary["global_blockers"], [])
            self.assertEqual(summary["effective_decision_grade_task_count"], 3)
            self.assertEqual(summary["decision_grade_task_count"], 4)

    def test_build_multi_summary_blocks_mixed_fingerprints_and_mixed_grades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            smoke = base / "smoke" / "result.json"
            decision = base / "decision" / "result.json"
            write_result(smoke, "login_test_failure", paired_runs=1, subject_fingerprint="subject-a")
            write_result(decision, "login_test_failure", paired_runs=3, subject_fingerprint="subject-b")
            summary = build_multi_summary([smoke, decision])
            self.assertFalse(summary["global_token_efficiency_claim_allowed"])
            self.assertEqual(summary["global_decision"], "do_not_claim_global_efficiency")
            self.assertIn("effective_decision_grade_tasks_below_threshold:1/3", summary["global_blockers"])
            self.assertIn("mixed_or_missing_subject_fingerprints", summary["global_blockers"])
            self.assertIn("mixed_or_missing_subject_fingerprints", summary["warnings"])
            self.assertIn("mixed_smoke_and_decision_grade_results", summary["warnings"])
            self.assertEqual(summary["mixed_grade_tasks"], ["login_test_failure"])

    def test_multi_task_result_is_split_by_task_and_paired_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result_path = base / "run" / "result.json"
            write_multi_task_result(result_path, ["login_test_failure", "export_cli_location"], paired_runs=2, subject_mode="synthetic")
            summary = build_multi_summary([result_path])
            self.assertEqual([row["task_id"] for row in summary["tasks"]], ["login_test_failure", "export_cli_location"])
            self.assertEqual([row["paired_runs"] for row in summary["tasks"]], [2, 2])
            self.assertEqual([row["decision_grade"] for row in summary["tasks"]], [False, False])
            self.assertIn("synthetic_results_only", summary["warnings"])
            self.assertFalse(summary["global_token_efficiency_claim_allowed"])

    def test_summarize_results_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result_path = base / "run" / "result.json"
            out = base / "out"
            write_result(result_path, "login_test_failure")
            outputs = summarize_results([base], out)
            self.assertTrue(outputs["summary_json"].exists())
            self.assertTrue(outputs["summary_md"].exists())
            payload = json.loads(outputs["summary_json"].read_text(encoding="utf-8"))
            self.assertEqual(payload["tasks"][0]["task_id"], "login_test_failure")
            report = outputs["summary_md"].read_text(encoding="utf-8")
            self.assertIn("# Tokenmessung Multi-Task Summary", report)
            self.assertIn("Can claim global efficiency:", report)
            self.assertIn("Global decision: **do_not_claim_global_efficiency**", report)
            self.assertIn("Plain explanation:", report)
            self.assertIn("What to do now:", report)
            self.assertIn("## Global Blockers", report)
            self.assertIn("decision_grade_tasks_incomplete:1/4", report)
            self.assertIn("login_test_failure", report)

    def test_format_multi_summary_console_explains_synthetic_demo_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result_path = base / "run" / "result.json"
            write_multi_task_result(result_path, ["login_test_failure"], paired_runs=2, subject_mode="synthetic")
            summary = build_multi_summary([result_path])
            text = format_multi_summary_console(summary)
            self.assertIn("=== Tokenmessung Summary ===", text)
            self.assertIn("developer/CI synthetic fixture", text)
            self.assertIn("not to claim real token efficiency", text)
            self.assertIn("What to do now:", text)


if __name__ == "__main__":
    unittest.main()
