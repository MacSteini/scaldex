from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tokenmessung.cli import main


class CliTests(unittest.TestCase):
    def run_cli(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def run_cli_text(self, argv: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, output.getvalue()

    def test_doctor_default_does_not_require_api_key(self) -> None:
        checks = {
            "git": True,
            "codex": True,
            "codex_api_key_present": False,
            "supports_json": True,
            "supports_output_schema": True,
            "supports_ignore_user_config": True,
            "supports_ignore_rules": True,
        }
        with patch("tokenmessung.cli.doctor", return_value=checks):
            code, payload = self.run_cli(["bench", "doctor"])
        self.assertEqual(code, 0)
        self.assertFalse(payload["codex_api_key_present"])

    def test_doctor_require_api_key_fails_when_missing(self) -> None:
        checks = {
            "git": True,
            "codex": True,
            "codex_api_key_present": False,
            "supports_json": True,
            "supports_output_schema": True,
            "supports_ignore_user_config": True,
            "supports_ignore_rules": True,
        }
        with patch("tokenmessung.cli.doctor", return_value=checks):
            code, _payload = self.run_cli(["bench", "doctor", "--require-api-key"])
        self.assertEqual(code, 1)

    def test_doctor_require_api_key_passes_when_present(self) -> None:
        checks = {
            "git": True,
            "codex": True,
            "codex_api_key_present": True,
            "supports_json": True,
            "supports_output_schema": True,
            "supports_ignore_user_config": True,
            "supports_ignore_rules": True,
        }
        with patch("tokenmessung.cli.doctor", return_value=checks):
            code, payload = self.run_cli(["bench", "doctor", "--require-api-key"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["codex_api_key_present"])

    def test_bench_run_requires_one_agents_source(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(output), redirect_stderr(error):
            main(["bench", "run", "--fixture", "fixture", "--model", "model", "--out", "results"])

    def test_bench_help_hides_synthetic_fixture_command(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(output), redirect_stderr(error):
            main(["bench", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("summarize", help_text)
        self.assertNotIn("synthesize", help_text)
        self.assertNotIn("synthetic", help_text.lower())

    def test_bench_run_rejects_conflicting_agents_sources(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(output), redirect_stderr(error):
            main(
                [
                    "bench",
                    "run",
                    "--fixture",
                    "fixture",
                    "--agents-file",
                    "AGENTS.md",
                    "--agents-dir",
                    "subject",
                    "--model",
                    "model",
                    "--out",
                    "results",
                ]
            )

    def test_bench_summarize_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = base / "run" / "result.json"
            out = base / "out"
            result.parent.mkdir()
            result.write_text(
                json.dumps(
                    {
                        "verdict": "effective",
                        "context": {"task_ids": ["login_test_failure"]},
                        "primary_delta": {"agents_minus_control": -1, "percent": -1.0, "agents_median": 9, "control_median": 10},
                        "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
                        "benchmark_warnings": [],
                        "final_relevant_files": {"normalized_repo_relative_only": True},
                        "reliability": {"paired_runs": 3},
                        "decision": {"decision_grade": True},
                        "integrity": {"subject_fingerprint": "subject-a", "run_config_fingerprint": "config-a"},
                        "subject": {"source_file_count": 1, "total_bytes": 10},
                    }
                ),
                encoding="utf-8",
            )
            code, payload = self.run_cli(["bench", "summarize", str(base), "--out", str(out), "--json"])
            self.assertEqual(code, 0)
            self.assertTrue(Path(payload["summary_json"]).exists())
            self.assertTrue(Path(payload["summary_md"]).exists())

    def test_bench_summarize_prints_human_summary_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = base / "run" / "result.json"
            out = base / "out"
            result.parent.mkdir()
            result.write_text(
                json.dumps(
                    {
                        "verdict": "effective",
                        "context": {"task_ids": ["login_test_failure"]},
                        "primary_delta": {"agents_minus_control": -1, "percent": -1.0, "agents_median": 9, "control_median": 10},
                        "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
                        "benchmark_warnings": [],
                        "final_relevant_files": {"normalized_repo_relative_only": True},
                        "reliability": {"paired_runs": 3},
                        "decision": {"decision_grade": True},
                        "integrity": {"subject_fingerprint": "subject-a", "run_config_fingerprint": "config-a"},
                        "subject": {"source_file_count": 1, "total_bytes": 10},
                    }
                ),
                encoding="utf-8",
            )
            code, text = self.run_cli_text(["bench", "summarize", str(base), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("=== Tokenmessung Summary ===", text)
            self.assertIn("Can claim global efficiency:", text)
            self.assertIn("What to do now:", text)
            self.assertIn("Human summary:", text)

    def test_bench_summarize_missing_input_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with self.assertRaises(SystemExit) as ctx:
                main(["bench", "summarize", str(base / "missing-history"), "--out", str(base / "out")])
            self.assertIn("Cannot summarize results: Result input not found", str(ctx.exception))

    def test_result_show_prints_existing_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = base / "result.json"
            result.write_text(
                json.dumps(
                    {
                        "verdict": "effective",
                        "primary_delta": {"agents_minus_control": -10, "percent": -10.0, "agents_median": 90, "control_median": 100},
                        "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
                        "benchmark_warnings": [],
                        "final_relevant_files": {"normalized_repo_relative_only": True},
                        "reliability": {"level": "low", "paired_runs": 1, "warnings": ["low_sample_size"]},
                        "subject": {"mode": "package", "source_file_count": 1, "total_bytes": 9, "warnings": []},
                        "isolation": {"home_codex_excluded": True},
                        "integrity": {"batch_id": "batch-test", "subject_fingerprint": "subject-test", "run_config_fingerprint": "config-test"},
                        "artifacts": {"result_json": str(result), "result_md": str(base / "RESULT.md"), "codex_handoff_md": str(base / "CODEX_HANDOFF.md")},
                    }
                ),
                encoding="utf-8",
            )
            code, text = self.run_cli_text(["result", "show", str(result)])
            self.assertEqual(code, 0)
            self.assertIn("=== Tokenmessung Result ===", text)
            self.assertIn("Verdict: effective", text)
            self.assertIn("What this means:", text)
            self.assertIn("What to do now:", text)
            self.assertIn("Codex instruction:", text)
            self.assertIn("Give this to Codex:", text)
            self.assertIn("Codex should:", text)
            self.assertIn("Codex must not:", text)

    def test_result_show_prints_human_next_steps_for_all_actions(self) -> None:
        cases = [
            ("eligible_for_decision_run", "Give the Codex handoff to Codex, or run this same task with --repeats 3"),
            ("stop_fix_quality_or_task_behavior", "Give the Codex handoff to Codex to fix quality"),
            ("record_decision_grade_win", "Give the Codex handoff to Codex to compare this win"),
            ("do_not_claim_efficiency", "Give the Codex handoff to Codex to inspect task behaviour"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for index, (next_action, expected) in enumerate(cases):
                result = base / f"result-{index}.json"
                result.write_text(
                    json.dumps(
                        {
                            "verdict": "effective",
                            "primary_delta": {"agents_minus_control": -10, "percent": -10.0, "agents_median": 90, "control_median": 100},
                            "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
                            "benchmark_warnings": [],
                            "final_relevant_files": {"normalized_repo_relative_only": True},
                            "reliability": {"level": "normal", "paired_runs": 3, "warnings": []},
                            "subject": {"mode": "package", "source_file_count": 1, "total_bytes": 9, "warnings": []},
                            "decision": {"next_action": next_action, "scope": "task", "explanation": "fixture explanation"},
                        }
                    ),
                    encoding="utf-8",
                )
                code, text = self.run_cli_text(["result", "show", str(result)])
                self.assertEqual(code, 0)
                self.assertIn("What to do now:", text)
                self.assertIn(expected, text)
                self.assertIn("Codex should:", text)
                self.assertIn("Codex must not:", text)

    def test_result_show_prefers_local_handoff_sibling_over_stale_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = base / "history" / "result.json"
            local_handoff = result.parent / "CODEX_HANDOFF.md"
            local_report = result.parent / "RESULT.md"
            result.parent.mkdir()
            local_handoff.write_text("# Tokenmessung Codex Instruction\n", encoding="utf-8")
            local_report.write_text("# Tokenmessung Result\n", encoding="utf-8")
            stale_handoff = base / "old" / "CODEX_HANDOFF.md"
            result.write_text(
                json.dumps(
                    {
                        "verdict": "effective",
                        "primary_delta": {"agents_minus_control": -10, "percent": -10.0, "agents_median": 90, "control_median": 100},
                        "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
                        "benchmark_warnings": [],
                        "final_relevant_files": {"normalized_repo_relative_only": True},
                        "reliability": {"level": "low", "paired_runs": 1, "warnings": ["low_sample_size"]},
                        "subject": {"mode": "package", "source_file_count": 1, "total_bytes": 9, "warnings": []},
                        "decision": {"next_action": "eligible_for_decision_run", "scope": "task", "explanation": "fixture explanation"},
                        "artifacts": {"codex_handoff_md": str(stale_handoff), "result_md": str(base / "old" / "RESULT.md"), "result_json": str(base / "old" / "result.json")},
                    }
                ),
                encoding="utf-8",
            )
            code, text = self.run_cli_text(["result", "show", str(result)])
            self.assertEqual(code, 0)
            self.assertIn(f"Give this to Codex: {local_handoff.resolve()}", text)
            self.assertIn(f"- Human report: {local_report.resolve()}", text)
            self.assertNotIn(str(stale_handoff), text)

    def test_result_show_missing_result_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "result.json"
            with self.assertRaises(SystemExit) as ctx:
                main(["result", "show", str(missing)])
            self.assertIn("Missing result file", str(ctx.exception))
            self.assertIn("run a smoke test first", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
