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
    path = Path(__file__).resolve().parents[1] / "run_scaldex.py"
    spec = importlib.util.spec_from_file_location("run_scaldex", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_scaldex.py")
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
    run_dir = root / "scaldex-run"
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
                "integrity": {
                    "status": "ok",
                    "batch_id": "batch-test",
                    "subject_fingerprint": "subject-test",
                    "run_config_fingerprint": "config-test",
                },
                "artifacts": {
                    "result_json": str(result_json),
                    "result_md": str(run_dir / "RESULT.md"),
                    "codex_handoff_md": str(run_dir / "CODEX_HANDOFF.md"),
                },
            }
        ),
        encoding="utf-8",
    )
    result_md = run_dir / "RESULT.md"
    result_md.write_text("# scaldex result\n", encoding="utf-8")
    handoff_md = run_dir / "CODEX_HANDOFF.md"
    handoff_md.write_text("# scaldex codex instruction\n", encoding="utf-8")
    return {"summary_json": summary, "summary_csv": summary_csv, "paired_deltas_csv": deltas, "result_json": result_json, "result_md": result_md, "codex_handoff_md": handoff_md}


class RootRunnerTests(unittest.TestCase):
    def test_help_text_explains_common_enduser_flow(self) -> None:
        module = load_root_runner()
        help_text = module.build_parser().format_help()
        self.assertIn("Typical flow:", help_text)
        self.assertIn("--print-result scaldex-run/result.json", help_text)
        self.assertIn("CODEX_HANDOFF.md", help_text)
        self.assertIn("For Codex-assisted follow-up, use scaldex-run/CODEX_HANDOFF.md", help_text)
        self.assertIn("never stores your Codex API key", help_text)
        self.assertIn("What this means", help_text)
        self.assertIn("What to do now", help_text)
        self.assertIn("Use 1 for smoke, 3+", help_text)
        self.assertIn("for decision-grade evidence.", help_text)

    def test_missing_subject_agents_exits_cleanly(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            with Cwd(Path(tmp)):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--model", "model"])
        self.assertIn("Missing required file", str(ctx.exception))

    def test_print_result_replays_existing_result_without_subject_or_api_key(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_fake_outputs(root)
            before = {path.relative_to(root): path.read_text(encoding="utf-8") for path in root.rglob("*") if path.is_file()}
            output = io.StringIO()
            error = io.StringIO()
            with Cwd(root), redirect_stdout(output), redirect_stderr(error), patch.dict("os.environ", {}, clear=True), patch.object(module.getpass, "getpass", side_effect=AssertionError("API key prompt should not run")):
                self.assertEqual(module.main(["--print-result", str(outputs["result_json"])]), 0)
            after = {path.relative_to(root): path.read_text(encoding="utf-8") for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(error.getvalue(), "")
            self.assertIn("=== scaldex result ===", output.getvalue())
            self.assertIn("Verdict: effective", output.getvalue())
            self.assertIn("What this means:", output.getvalue())
            self.assertIn("What to do now:", output.getvalue())
            self.assertIn("Codex handoff:", output.getvalue())
            self.assertIn("- For Codex-assisted follow-up, use:", output.getvalue())
            self.assertIn("- Purpose:", output.getvalue())
            self.assertIn("- Boundary:", output.getvalue())
            self.assertIn("Human report:", output.getvalue())
            self.assertIn("Codex handoff:", output.getvalue())

    def test_print_result_reports_missing_file_cleanly(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            with Cwd(Path(tmp)), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--print-result", "missing-result.json"])
            self.assertIn("Missing result file", str(ctx.exception))

    def test_print_result_reports_invalid_json_cleanly(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "result.json"
            bad.write_text("{not json\n", encoding="utf-8")
            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--print-result", str(bad)])
            self.assertIn("Invalid result JSON", str(ctx.exception))

    def test_print_result_rejects_benchmark_options(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_fake_outputs(root)
            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--print-result", str(outputs["result_json"]), "--model", "model"])
            self.assertIn("Use --print-result by itself", str(ctx.exception))

    def test_api_key_is_not_written_to_generated_files(self) -> None:
        module = load_root_runner()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            stale = root / "scaldex-run" / "raw" / "results" / "old_task__agents__r1" / "meta.json"
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
                self.assertEqual(kwargs["analysis_dir"], (root / "scaldex-run").resolve())
                self.assertEqual(kwargs["subject_mode"], "package")
                self.assertEqual(args[0], (root / "scaldex-run" / "raw" / "fixture").resolve())
                self.assertIsNone(args[1])
                self.assertEqual(args[4], (root / "scaldex-run" / "raw" / "results").resolve())
                self.assertEqual(kwargs["agents_dir"], (root / "subject").resolve())
                self.assertEqual(kwargs["workspace_root"], (root / "scaldex-run" / "raw" / "workspaces").resolve())
                return write_fake_outputs(root)

            output = io.StringIO()
            error = io.StringIO()
            with Cwd(root), redirect_stdout(output), redirect_stderr(error), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch("scaldex.app.create_fixture"), patch("scaldex.app.run_benchmark", side_effect=fake_run_benchmark):
                code = module.main(["--model", "model"])
            self.assertEqual(code, 0)
            self.assertIn("Run 1/2 starting", error.getvalue())
            self.assertIn("Subject audit", error.getvalue())
            self.assertNotIn("sk-test-secret", error.getvalue())
            self.assertIn("Verdict: effective", output.getvalue())
            self.assertIn("Primary metric: agents used 10 fewer non-cached input tokens than control (-10.0%).", output.getvalue())
            self.assertIn("Secondary context only: agents median 90, control median 100; this is not the decision metric.", output.getvalue())
            self.assertIn("This run excluded your global ~/.codex config, so the subject package was measured in isolation.", output.getvalue())
            self.assertIn("Measured subject: package with 1 file(s)", output.getvalue())
            self.assertIn("Run isolation: dedicated CODEX_HOME per run", error.getvalue())
            self.assertIn("Replacing previous run folder", error.getvalue())
            self.assertIn("Tool sanity: schema v1", error.getvalue())
            self.assertIn("Planned paid Codex runs: 2", error.getvalue())
            self.assertIn("Batch ID:", error.getvalue())
            self.assertIn("Subject fingerprint:", error.getvalue())
            self.assertIn("Report identity: batch batch-test; subject fingerprint subject-test; run config fingerprint config-test.", output.getvalue())
            self.assertIn("Reliability: low evidence from 1 paired run(s).", output.getvalue())
            self.assertIn("What to do now:", output.getvalue())
            self.assertIn("What this means:", output.getvalue())
            self.assertIn("Codex handoff:", output.getvalue())
            self.assertIn("- For Codex-assisted follow-up, use:", output.getvalue())
            self.assertIn("- Purpose:", output.getvalue())
            self.assertIn("- Boundary:", output.getvalue())
            self.assertIn("What was compared", output.getvalue())
            self.assertIn("agents means the run with your measured instruction package installed.", output.getvalue())
            self.assertIn("control means the same task run without that package and without your global ~/.codex config.", output.getvalue())
            self.assertIn("Internal report structure is complete: schema v1, isolation reported, warnings separated, command output counted.", output.getvalue())
            self.assertIn("Codex handoff:", output.getvalue())
            self.assertIn("command_count_increased: The instruction package needed more shell commands", output.getvalue())
            self.assertNotIn("large_subject: The tested subject package is larger than 32 KiB", output.getvalue())
            for path in (root / "scaldex-run").rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8")
                    self.assertNotIn("sk-test-secret", text)
                    self.assertNotIn("[scaldex]", text)

    def test_prompted_api_key_uses_prefixed_hidden_prompt(self) -> None:
        module = load_root_runner()
        with patch.dict("os.environ", {}, clear=True), patch.object(module.getpass, "getpass", return_value="sk-test-secret") as getpass_mock:
            self.assertEqual(module.ensure_api_key(), "prompt")
            self.assertEqual(os.environ.get("CODEX_API_KEY"), "sk-test-secret")
        getpass_mock.assert_called_once_with("[scaldex] Enter Codex API Key: ")

    def test_refuses_run_dir_that_would_delete_subject(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "scaldex-run" / "subject"
            subject.mkdir(parents=True)
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--model", "model", "--subject-dir", "scaldex-run/subject"])
            self.assertIn("Refusing to nest subject/ and --run-dir", str(ctx.exception))

    def test_refuses_run_dir_inside_subject(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--model", "model", "--run-dir", "subject/scaldex-run"])
            self.assertIn("Refusing to nest subject/ and --run-dir", str(ctx.exception))

    def test_refuses_history_dir_inside_subject(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--model", "model", "--history-dir", "subject/scaldex-history"])
            self.assertIn("Refusing to place scaldex history inside subject/", str(ctx.exception))

    def test_refuses_history_dir_inside_run_dir(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    module.main(["--model", "model", "--history-dir", "scaldex-run/history"])
            self.assertIn("Refusing to nest --run-dir and --history-dir", str(ctx.exception))

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
            self.assertIn("Refusing to replace non-scaldex --run-dir", str(ctx.exception))
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

            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch("scaldex.app.create_fixture"), patch("scaldex.app.run_benchmark", side_effect=fake_run_benchmark):
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

            with Cwd(root), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch("scaldex.app.create_fixture"), patch("scaldex.app.run_benchmark", side_effect=fake_run_benchmark):
                self.assertEqual(module.main(["--model", "model", "--subject-mode", "agents-md"]), 0)

    def test_archives_previous_compact_report_before_replacing_run_dir(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "scaldex-run"
            previous.mkdir()
            (previous / module.GENERATED_MARKER).write_text("generated by scaldex\n", encoding="utf-8")
            outputs = write_fake_outputs(root)
            history = root / "scaldex-history"
            archive = module.archive_previous_result(previous, history)
            self.assertIsNotNone(archive)
            assert archive is not None
            self.assertTrue((archive / "result.json").is_file())
            self.assertTrue((archive / "RESULT.md").is_file())
            self.assertTrue((archive / "CODEX_HANDOFF.md").is_file())
            self.assertTrue((archive / "archive.json").is_file())
            payload = json.loads((archive / "archive.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["source_run_dir"], str(previous))
            self.assertIn("result.json", payload["copied_files"])
            self.assertEqual(json.loads((archive / "result.json").read_text(encoding="utf-8"))["integrity"]["batch_id"], "batch-test")
            self.assertEqual(outputs["result_json"].read_text(encoding="utf-8"), (archive / "result.json").read_text(encoding="utf-8"))

    def test_main_prints_history_compare_hint_after_archiving_previous_result(self) -> None:
        module = load_root_runner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = root / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            previous = root / "scaldex-run"
            previous.mkdir()
            (previous / module.GENERATED_MARKER).write_text("generated by scaldex\n", encoding="utf-8")
            write_fake_outputs(root)

            def fake_run_benchmark(*args: object, **kwargs: object) -> dict[str, Path]:
                return write_fake_outputs(root)

            output = io.StringIO()
            error = io.StringIO()
            with Cwd(root), redirect_stdout(output), redirect_stderr(error), patch.dict("os.environ", {"CODEX_API_KEY": "sk-test-secret"}, clear=True), patch("scaldex.app.create_fixture"), patch("scaldex.app.run_benchmark", side_effect=fake_run_benchmark):
                self.assertEqual(module.main(["--model", "model"]), 0)
            self.assertIn("Archived previous compact report", error.getvalue())
            self.assertIn("Compare history: scaldex bench summarize scaldex-history scaldex-run --out scaldex-summary", output.getvalue())


if __name__ == "__main__":
    unittest.main()
