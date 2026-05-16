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

            def fake_run_benchmark(*args: object, **kwargs: object) -> dict[str, Path]:
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
                results = root / "tokenmessung-run" / "results"
                results.mkdir(parents=True, exist_ok=True)
                summary = results / "summary.json"
                summary.write_text(json.dumps({"runs": 0}), encoding="utf-8")
                summary_csv = results / "summary.csv"
                summary_csv.write_text("run_id\n", encoding="utf-8")
                deltas = results / "paired-deltas.csv"
                deltas.write_text("task_id\n", encoding="utf-8")
                return {"summary_json": summary, "summary_csv": summary_csv, "paired_deltas_csv": deltas}

            output = io.StringIO()
            error = io.StringIO()
            with Cwd(root), redirect_stdout(output), redirect_stderr(error), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch.object(module, "create_fixture"), patch.object(module, "run_benchmark", side_effect=fake_run_benchmark):
                code = module.main(["--model", "model"])
            self.assertEqual(code, 0)
            self.assertIn("Run 1/2 startet", error.getvalue())
            self.assertNotIn("sk-test-secret", error.getvalue())
            for path in (root / "tokenmessung-run").rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8")
                    self.assertNotIn("sk-test-secret", text)
                    self.assertNotIn("[tokenmessung]", text)

    def test_all_tasks_disables_low_cost_default(self) -> None:
        module = load_root_runner()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

            def fake_run_benchmark(*args: object, **kwargs: object) -> dict[str, Path]:
                self.assertIsNone(kwargs["task_ids"])
                results = root / "tokenmessung-run" / "results"
                results.mkdir(parents=True, exist_ok=True)
                summary = results / "summary.json"
                summary.write_text(json.dumps({"runs": 0}), encoding="utf-8")
                summary_csv = results / "summary.csv"
                summary_csv.write_text("run_id\n", encoding="utf-8")
                deltas = results / "paired-deltas.csv"
                deltas.write_text("task_id\n", encoding="utf-8")
                return {"summary_json": summary, "summary_csv": summary_csv, "paired_deltas_csv": deltas}

            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch.object(module, "create_fixture"), patch.object(module, "run_benchmark", side_effect=fake_run_benchmark):
                self.assertEqual(module.main(["--model", "model", "--all-tasks"]), 0)


if __name__ == "__main__":
    unittest.main()
