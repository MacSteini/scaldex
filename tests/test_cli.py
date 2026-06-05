from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scaldex.cli import main


@contextmanager
def cwd(path: Path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


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
        with patch("scaldex.cli.doctor", return_value=checks):
            code, payload = self.run_cli(["bench", "doctor", "--json"])
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
        with patch("scaldex.cli.doctor", return_value=checks):
            code, _payload = self.run_cli(["bench", "doctor", "--require-api-key", "--json"])
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
        with patch("scaldex.cli.doctor", return_value=checks):
            code, payload = self.run_cli(["bench", "doctor", "--require-api-key", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["codex_api_key_present"])

    def test_doctor_prints_human_summary_by_default(self) -> None:
        checks = {
            "python": "3.14.5",
            "git": True,
            "codex": True,
            "codex_version": "codex-cli test",
            "codex_api_key_present": False,
            "supports_json": True,
            "supports_output_schema": True,
            "supports_ignore_user_config": True,
            "supports_ignore_rules": True,
        }
        with patch("scaldex.cli.doctor", return_value=checks):
            code, text = self.run_cli_text(["bench", "doctor"])
        self.assertEqual(code, 0)
        self.assertIn("=== scaldex doctor ===", text)
        self.assertIn("Ready for paid benchmark runs: yes", text)
        self.assertIn("Codex API key: not set; scaldex will ask at the hidden prompt", text)
        self.assertIn("What to do now:", text)

    def test_top_level_args_delegate_to_high_level_runner(self) -> None:
        with patch("scaldex.cli.app_main", return_value=0) as app_main:
            self.assertEqual(main(["--model", "model"]), 0)
        app_main.assert_called_once_with(["--model", "model"])

    def test_public_help_uses_high_level_runner(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(output), redirect_stderr(error):
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("scaldex --model gpt-5.5", help_text)
        self.assertIn("scaldex --print-result scaldex-run/result.json", help_text)
        self.assertNotIn("fixture", help_text)

    def test_utility_help_hides_internal_fixture_and_raw_benchmark_commands(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(output), redirect_stderr(error):
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        root_help = output.getvalue()
        self.assertNotIn("fixture", root_help)
        self.assertNotIn("bench run", root_help)

        output = io.StringIO()
        error = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(output), redirect_stderr(error):
            main(["bench", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("summarize", help_text)
        self.assertIn("doctor", help_text)
        self.assertNotIn("fixture", help_text)
        self.assertNotIn("run        Run a paid benchmark", help_text)
        self.assertNotIn("analyze", help_text)
        self.assertNotIn("synthesize", help_text)
        self.assertNotIn("synthetic", help_text.lower())

        output = io.StringIO()
        error = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(output), redirect_stderr(error):
            main(["result", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("Replay existing result reports without running Codex.", output.getvalue())
        self.assertIn("show", output.getvalue())
        self.assertIn("Show an existing result.json as the standard scaldex result", output.getvalue())

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
            self.assertIn("=== scaldex summary ===", text)
            self.assertIn("Can claim global efficiency:", text)
            self.assertIn("What to do now:", text)
            self.assertIn("Human summary:", text)

    def test_bench_summarize_missing_input_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with self.assertRaises(SystemExit) as ctx:
                main(["bench", "summarize", str(base / "missing-history"), "--out", str(base / "out")])
            self.assertIn("Cannot summarise results: Result input not found", str(ctx.exception))

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
            self.assertIn("=== scaldex result ===", text)
            self.assertIn("Result\n", text)
            self.assertIn("Verdict: effective", text)
            self.assertIn("What this means:", text)
            self.assertIn("What to do now:", text)
            self.assertIn("Codex handoff:", text)
            self.assertIn("- For Codex-assisted follow-up, use:", text)
            self.assertIn("- Provide with: the measured subject/ package and a clear task.", text)
            self.assertIn("- Purpose:", text)
            self.assertIn("- Boundary:", text)
            self.assertIn("What was compared", text)
            self.assertIn("agents means the run with your measured instruction package installed.", text)
            self.assertIn("control means the same task run without that package and without your global ~/.codex config.", text)
            self.assertIn("Primary metric: agents used 10 fewer non-cached input tokens than control (-10.0%).", text)
            self.assertIn("Secondary context only: agents median 90, control median 100; this is not the decision metric.", text)
            self.assertIn("Both sides completed all required runs successfully: agents success rate 100% (1.0), control success rate 100% (1.0).", text)
            self.assertIn("This run excluded your global ~/.codex config, so the subject package was measured in isolation.", text)
            self.assertIn("Report identity: batch batch-test; subject fingerprint subject-test; run config fingerprint config-test.", text)
            self.assertIn("Path integrity: final relevant files normalise to repo-relative paths, so Codex can compare reports safely.", text)

    def test_result_show_prints_quality_blocker_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = base / "result.json"
            result.write_text(
                json.dumps(
                    {
                        "verdict": "not_effective",
                        "primary_delta": {"agents_minus_control": 384, "percent": 3.2, "agents_median": 12365, "control_median": 11981},
                        "quality": {"agents_success_rate": 0.0, "control_success_rate": 1.0},
                        "benchmark_warnings": ["missing_expected_files", "missing_expected_relevant_files"],
                        "final_relevant_files": {
                            "normalized_repo_relative_only": True,
                            "missing_expected_paths": ["packages/export-cli/src/index.ts"],
                        },
                        "reliability": {"level": "low", "paired_runs": 1, "warnings": ["low_sample_size"]},
                        "subject": {"mode": "package", "source_file_count": 1, "total_bytes": 9, "warnings": []},
                        "decision": {
                            "next_action": "stop_fix_quality_or_task_behavior",
                            "scope": "task",
                            "explanation": "fixture explanation",
                        },
                    }
                ),
                encoding="utf-8",
            )
            code, text = self.run_cli_text(["result", "show", str(result)])
            self.assertEqual(code, 0)
            self.assertIn("Quality gate failed: an agents/control success rate of 1.0 means every run passed the task checks", text)
            self.assertIn("Blocker: at least one side failed the task quality checks", text)
            self.assertIn("Blocker warnings: missing_expected_files", text)
            self.assertIn("Missing expected relevant_files entries: `packages/export-cli/src/index.ts`.", text)

    def test_result_show_prints_human_next_steps_for_all_actions(self) -> None:
        cases = [
            ("eligible_for_decision_run", "Run this same task with --repeats 3 before trusting the result"),
            ("stop_fix_quality_or_task_behavior", "Stop before spending more money"),
            ("record_decision_grade_win", "Keep this win and compare it with other decision-grade task reports"),
            ("do_not_claim_efficiency", "Do not claim efficiency. Inspect task behaviour"),
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
                self.assertIn("- Purpose:", text)
                self.assertIn("- Boundary:", text)

    def test_result_show_prefers_local_handoff_sibling_over_stale_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = base / "history" / "result.json"
            local_handoff = result.parent / "CODEX_HANDOFF.md"
            local_report = result.parent / "RESULT.md"
            result.parent.mkdir()
            local_handoff.write_text("# scaldex codex instruction\n", encoding="utf-8")
            local_report.write_text("# scaldex result\n", encoding="utf-8")
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
            with cwd(base):
                code, text = self.run_cli_text(["result", "show", "history/result.json"])
            self.assertEqual(code, 0)
            self.assertIn("- For Codex-assisted follow-up, use: history/CODEX_HANDOFF.md", text)
            self.assertIn("- Provide with: the measured subject/ package and a clear task.", text)
            self.assertIn("- Human report: history/RESULT.md", text)
            self.assertNotIn(str(local_handoff.resolve()), text)
            self.assertNotIn(str(local_report.resolve()), text)
            self.assertNotIn(str(stale_handoff), text)

    def test_result_show_missing_result_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "result.json"
            with self.assertRaises(SystemExit) as ctx:
                main(["result", "show", str(missing)])
            self.assertIn("Missing result file", str(ctx.exception))
            self.assertIn("Run a smoke test to create a result.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
