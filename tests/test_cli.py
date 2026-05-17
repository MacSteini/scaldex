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
            code, payload = self.run_cli(["bench", "summarize", str(base), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(Path(payload["summary_json"]).exists())
            self.assertTrue(Path(payload["summary_md"]).exists())


if __name__ == "__main__":
    unittest.main()
