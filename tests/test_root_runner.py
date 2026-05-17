from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


def load_root_runner():
    path = Path(__file__).resolve().parents[1] / "run_tokenmessung.py"
    spec = importlib.util.spec_from_file_location("run_tokenmessung", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_tokenmessung.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Cwd:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.previous = Path.cwd()

    def __enter__(self) -> None:
        os.chdir(self.path)

    def __exit__(self, *args: object) -> None:
        os.chdir(self.previous)


def write_fake_outputs(root: Path) -> dict[str, Path]:
    run_dir = root / "tokenmessung-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = run_dir / "summary.json"
    summary.write_text(json.dumps({"runs": 0}), encoding="utf-8")
    summary_csv = run_dir / "summary.csv"
    summary_csv.write_text("run_id\n", encoding="utf-8")
    deltas = run_dir / "paired-deltas.csv"
    deltas.write_text("task_id\n", encoding="utf-8")
    result_json = run_dir / "result.json"
    result_json.write_text(
        json.dumps(
            {
                "verdict": "effective",
                "primary_delta": {"agents_minus_control": -10, "percent": -10.0, "agents_median": 90, "control_median": 100},
                "quality": {"agents_success_rate": 1.0, "control_success_rate": 1.0},
                "subject": {"mode": "package", "source_file_count": 1, "total_bytes": 9, "total_size": "9 B", "warnings": []},
                "isolation": {"home_codex_excluded": True},
                "warnings": ["large_subject"],
                "benchmark_warnings": ["command_count_increased"],
                "reliability": {"level": "low", "paired_runs": 1, "warnings": ["low_sample_size"]},
                "tool_sanity": {
                    "schema_version": 1,
                    "run_isolation_reporting": True,
                    "separated_warning_sections": True,
                    "aggregated_command_output_counted": True,
                },
                "artifacts": {
                    "result_json": str(result_json),
                    "result_md": str(run_dir / "RESULT.md"),
                },
            }
        ),
        encoding="utf-8",
    )
    result_md = run_dir / "RESULT.md"
    result_md.write_text("# Tokenmessung Result\n", encoding="utf-8")
    return {"summary_json": summary, "summary_csv": summary_csv, "paired_deltas_csv": deltas, "result_json": result_json, "result_md": result_md}


class RootRunnerTests(unittest.TestCase):
    def test_missing_subject_agents_exits_cleanly(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            with Cwd(Path(tmp)):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--model", "model"])
        self.assertIn("Missing required file", str(ctx.exception))

    def test_api_key_is_not_written_to_generated_files(self) -> None:
        module = load_root_runner()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            stale = root / "tokenmessung-run" / "raw" / "results" / "old_task__agents__r1" / "meta.json"
            stale.parent.mkdir(parents=True)
            stale.write_text('{"run_id":"old"}\n', encoding="utf-8")

            def fake_run_benchmark(*args: object, **kwargs: object) -> dict[str, Path]:
                self.assertFalse(stale.exists())
                progress = kwargs.get("progress")
                if callable(progress):
                    progress({"event": "benchmark_start", "total_runs": 2, "repeats": 1, "task_count": 1})
                    progress({"event": "run_start", "run_order": 1, "total_runs": 2, "task_id": "login_test_failure", "variant": "control", "repeat": 1})
                    progress({"event": "run_heartbeat", "run_id": "login_test_failure__control__r1", "elapsed_seconds": 10.0})
                    progress({"event": "run_done", "run_order": 1, "total_runs": 2, "task_id": "login_test_failure", "variant": "control", "exit_code": 0, "wall_seconds": 11.0})
                    progress({"event": "analysis_start"})
                    progress({"event": "analysis_done"})
                self.assertEqual(kwargs["task_ids"], ["login_test_failure"])
                self.assertEqual(kwargs["max_run_seconds"], 300.0)
                self.assertEqual(kwargs["analysis_dir"], (root / "tokenmessung-run").resolve())
                self.assertEqual(kwargs["subject_mode"], "package")
                self.assertEqual(args[0], (root / "tokenmessung-run" / "raw" / "fixture").resolve())
                self.assertIsNone(args[1])
                self.assertEqual(args[4], (root / "tokenmessung-run" / "raw" / "results").resolve())
                self.assertEqual(kwargs["agents_dir"], (root / "subject").resolve())
                self.assertEqual(kwargs["workspace_root"], (root / "tokenmessung-run" / "raw" / "workspaces").resolve())
                return write_fake_outputs(root)

            output = io.StringIO()
            error = io.StringIO()
            with Cwd(root), redirect_stdout(output), redirect_stderr(error), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch.object(module, "create_fixture"), patch.object(module, "run_benchmark", side_effect=fake_run_benchmark):
                code = module.main(["--model", "model"])
            self.assertEqual(code, 0)
            self.assertIn("Run 1/2 startet", error.getvalue())
            self.assertIn("Subject-Audit", error.getvalue())
            self.assertNotIn("sk-test-secret", error.getvalue())
            self.assertIn("Verdict: effective", output.getvalue())
            self.assertIn("Paired median non-cached input delta", output.getvalue())
            self.assertIn("Variant medians: agents 90 / control 100", output.getvalue())
            self.assertIn("Isolation: ~/.codex excluded = True", output.getvalue())
            self.assertIn("Subject: package", output.getvalue())
            self.assertIn("Run-Isolation: eigenes CODEX_HOME pro Run", error.getvalue())
            self.assertIn("Vorheriger Run-Ordner wird ersetzt", error.getvalue())
            self.assertIn("Tool-Sanity: schema v1", error.getvalue())
            self.assertIn("Geplante bezahlte Codex-Runs: 2", error.getvalue())
            self.assertIn("Reliability: low (1 paired run(s))", output.getvalue())
            self.assertIn("Tool sanity: schema v1", output.getvalue())
            self.assertIn("command_count_increased: The instruction package needed more shell commands", output.getvalue())
            self.assertNotIn("large_subject: The tested subject package is larger than 32 KiB", output.getvalue())
            for path in (root / "tokenmessung-run").rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8")
                    self.assertNotIn("sk-test-secret", text)
                    self.assertNotIn("[tokenmessung]", text)

    def test_prompted_api_key_uses_prefixed_hidden_prompt(self) -> None:
        module = load_root_runner()
        with patch.dict("os.environ", {}, clear=True), patch.object(module.getpass, "getpass", return_value="sk-test-secret") as getpass_mock:
            self.assertEqual(module.ensure_api_key(), "prompt")
            self.assertEqual(os.environ.get("CODEX_API_KEY"), "sk-test-secret")
        getpass_mock.assert_called_once_with("[tokenmessung] CODEX_API_KEY: ")

    def test_refuses_run_dir_that_would_delete_subject(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "tokenmessung-run" / "subject"
            subject.mkdir(parents=True)
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--model", "model", "--subject-dir", "tokenmessung-run/subject"])
            self.assertIn("Refusing to place subject/ inside --run-dir", str(ctx.exception))

    def test_refuses_custom_unmarked_nonempty_run_dir(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            custom_run = root / "custom-run"
            custom_run.mkdir()
            (custom_run / "user-file.txt").write_text("do not delete\n", encoding="utf-8")
            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--model", "model", "--run-dir", "custom-run"])
            self.assertIn("Refusing to replace non-tokenmessung --run-dir", str(ctx.exception))
            self.assertTrue((custom_run / "user-file.txt").exists())

    def test_all_tasks_disables_low_cost_default(self) -> None:
        module = load_root_runner()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

            def fake_run_benchmark(*args: object, **kwargs: object) -> dict[str, Path]:
                self.assertIsNone(kwargs["task_ids"])
                return write_fake_outputs(root)

            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch.object(module, "create_fixture"), patch.object(module, "run_benchmark", side_effect=fake_run_benchmark):
                self.assertEqual(module.main(["--model", "model", "--all-tasks"]), 0)

    def test_agents_md_subject_mode_passes_only_agents_file(self) -> None:
        module = load_root_runner()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            (subject / ".codex").mkdir(parents=True)
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            (subject / ".codex" / "instructions.md").write_text("# Support\n", encoding="utf-8")

            def fake_run_benchmark(*args: object, **kwargs: object) -> dict[str, Path]:
                self.assertEqual(kwargs["subject_mode"], "agents-md")
                self.assertEqual(args[1], (root / "subject" / "AGENTS.md").resolve())
                self.assertIsNone(kwargs["agents_dir"])
                return write_fake_outputs(root)

            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch.object(module, "create_fixture"), patch.object(module, "run_benchmark", side_effect=fake_run_benchmark):
                self.assertEqual(module.main(["--model", "model", "--subject-mode", "agents-md"]), 0)


if __name__ == "__main__":
    unittest.main()
