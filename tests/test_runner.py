from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tokenmessung.fixture import create_fixture
from tokenmessung.runner import copy_fixture, install_agents_dir, install_agents_file, remove_control_instructions, run_one, selected_tasks, synthesize_benchmark, validate_benchmark_inputs


class FakeProcess:
    def __init__(self, waits: list[int | str] | None = None) -> None:
        self.waits = waits or [0]
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        value = self.waits.pop(0)
        if value == "timeout":
            raise subprocess.TimeoutExpired("codex", timeout)
        self.returncode = int(value)
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class RunnerVariantTests(unittest.TestCase):
    def test_control_variant_removes_instruction_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            (fixture / ".codex").mkdir()
            (fixture / ".codex" / "config.toml").write_text("model = 'x'\n", encoding="utf-8")
            (fixture / ".codex-project").mkdir()
            (fixture / "AGENTS.override.md").write_text("# Override\n", encoding="utf-8")
            workdir = base / "work"
            copy_fixture(fixture, workdir)
            remove_control_instructions(workdir)
            self.assertFalse((workdir / "AGENTS.md").exists())
            self.assertFalse((workdir / "AGENTS.override.md").exists())
            self.assertFalse((workdir / ".codex").exists())
            self.assertFalse((workdir / ".codex-project").exists())

    def test_agents_variant_installs_supplied_agents_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            workdir = base / "work"
            agents_file = base / "custom-AGENTS.md"
            agents_file.write_text("# Custom\n", encoding="utf-8")
            copy_fixture(fixture, workdir)
            install_agents_file(workdir, agents_file)
            self.assertEqual((workdir / "AGENTS.md").read_text(encoding="utf-8"), "# Custom\n")

    def test_agents_dir_installs_instruction_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            workdir = base / "work"
            subject = base / "subject"
            (subject / ".codex").mkdir(parents=True)
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            (subject / "AGENTS.override.md").write_text("# Override\n", encoding="utf-8")
            (subject / ".codex" / "instructions.md").write_text("# Support\n", encoding="utf-8")
            copy_fixture(fixture, workdir)
            install_agents_dir(workdir, subject)
            self.assertEqual((workdir / "AGENTS.md").read_text(encoding="utf-8"), "# Agents\n")
            self.assertEqual((workdir / "AGENTS.override.md").read_text(encoding="utf-8"), "# Override\n")
            self.assertTrue((workdir / ".codex" / "instructions.md").exists())

    def test_validate_rejects_invalid_repeats_before_paid_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            agents_file = fixture / "AGENTS.md"
            with self.assertRaises(ValueError):
                validate_benchmark_inputs(fixture, agents_file, 0)

    def test_validate_rejects_missing_or_conflicting_agents_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            agents_file = fixture / "AGENTS.md"
            with self.assertRaises(ValueError):
                validate_benchmark_inputs(fixture, None, 1, require_api_key=False)
            with self.assertRaises(ValueError):
                validate_benchmark_inputs(fixture, agents_file, 1, require_api_key=False, agents_dir=fixture)

    def test_validate_rejects_non_git_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = base / "not-git"
            fixture.mkdir()
            agents_file = base / "AGENTS.md"
            agents_file.write_text("# Agents\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_benchmark_inputs(fixture, agents_file, 1, require_api_key=False)

    def test_validate_accepts_agents_dir_with_agents_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            subject = base / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            with patch("tokenmessung.runner.codex_exec_capabilities", return_value={"supports_json": True, "supports_output_schema": True, "supports_ignore_user_config": True, "supports_ignore_rules": True}):
                validate_benchmark_inputs(fixture, None, 1, require_api_key=False, agents_dir=subject)

    def test_validate_rejects_missing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            agents_file = fixture / "AGENTS.md"
            with patch.dict("os.environ", {}, clear=True), patch("tokenmessung.runner.codex_exec_capabilities", return_value={"supports_json": True, "supports_output_schema": True, "supports_ignore_user_config": True, "supports_ignore_rules": True}):
                with self.assertRaises(EnvironmentError):
                    validate_benchmark_inputs(fixture, agents_file, 1)

    def test_synthesize_benchmark_creates_complete_paired_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "synthetic"
            paths = synthesize_benchmark(out, repeats=2, seed=1)
            self.assertTrue(paths["summary_csv"].exists())
            self.assertEqual(len(list(out.glob("*/meta.json"))), 16)
            self.assertTrue((out / "paired-deltas.csv").read_text(encoding="utf-8"))

    def test_run_one_records_cleanup_default_and_keep(self) -> None:
        class FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = base / "fixture"
            fixture.mkdir()
            (fixture / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            agents_file = fixture / "AGENTS.md"
            task = {"id": "task", "prompt": "prompt", "expected_files": [], "expected_terms": []}
            with patch("tokenmessung.runner.subprocess.run", return_value=FakeResult()), patch("tokenmessung.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess()), patch("tokenmessung.runner.fixture_commit", return_value="abc"), patch("tokenmessung.runner.codex_version", return_value="codex-test"):
                run_one(fixture=fixture, agents_file=agents_file, agents_dir=None, model="model", out=base / "results", task=task, variant="agents", repeat=1, run_order=1)
                removed_meta = (base / "results" / "task__agents__r1" / "meta.json").read_text(encoding="utf-8")
                self.assertIn('"workdir_cleanup": "removed"', removed_meta)
                run_one(fixture=fixture, agents_file=agents_file, agents_dir=None, model="model", out=base / "keep", task=task, variant="agents", repeat=1, run_order=1, keep_workdirs=True)
                kept_meta = (base / "keep" / "task__agents__r1" / "meta.json").read_text(encoding="utf-8")
                self.assertIn('"workdir_cleanup": "kept"', kept_meta)

    def test_workspace_root_contains_and_cleans_workspaces(self) -> None:
        class FakeResult:
            returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = base / "fixture"
            fixture.mkdir()
            agents_file = fixture / "AGENTS.md"
            agents_file.write_text("# Agents\n", encoding="utf-8")
            workspace_root = base / "workspaces"
            task = {"id": "task", "prompt": "prompt", "expected_files": [], "expected_terms": []}
            with patch("tokenmessung.runner.subprocess.run", return_value=FakeResult()), patch("tokenmessung.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess()), patch("tokenmessung.runner.fixture_commit", return_value="abc"), patch("tokenmessung.runner.codex_version", return_value="codex-test"):
                run_one(
                    fixture=fixture,
                    agents_file=agents_file,
                    agents_dir=None,
                    model="model",
                    out=base / "results",
                    task=task,
                    variant="agents",
                    repeat=1,
                    run_order=1,
                    workspace_root=workspace_root,
                )
            self.assertTrue(workspace_root.exists())
            self.assertFalse((workspace_root / "task__agents__r1").exists())

    def test_run_one_progress_events_stay_out_of_artifacts(self) -> None:
        class FakeResult:
            returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = base / "fixture"
            fixture.mkdir()
            agents_file = fixture / "AGENTS.md"
            agents_file.write_text("# Agents\n", encoding="utf-8")
            events: list[dict[str, object]] = []
            task = {"id": "task", "prompt": "prompt", "expected_files": [], "expected_terms": []}
            with patch("tokenmessung.runner.subprocess.run", return_value=FakeResult()), patch("tokenmessung.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess(["timeout", 0])), patch("tokenmessung.runner.fixture_commit", return_value="abc"), patch("tokenmessung.runner.codex_version", return_value="codex-test"):
                run_one(
                    fixture=fixture,
                    agents_file=agents_file,
                    agents_dir=None,
                    model="model",
                    out=base / "results",
                    task=task,
                    variant="agents",
                    repeat=1,
                    run_order=1,
                    progress=events.append,
                    heartbeat_interval=0.01,
                    total_runs=1,
                )
            event_names = [event["event"] for event in events]
            self.assertEqual(event_names, ["run_start", "run_heartbeat", "run_done"])
            run_dir = base / "results" / "task__agents__r1"
            artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in (run_dir / name for name in ("meta.json", "codex.jsonl", "stderr.log", "exit_code.txt", "time.json")))
            self.assertNotIn("run_heartbeat", artifact_text)
            self.assertNotIn("[tokenmessung]", artifact_text)
            self.assertFalse((run_dir / "output_schema.json").exists())
            self.assertFalse((run_dir / "codex-home").exists())

    def test_run_one_timeout_records_nonzero_exit(self) -> None:
        class FakeResult:
            returncode = 0

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = base / "fixture"
            fixture.mkdir()
            agents_file = fixture / "AGENTS.md"
            agents_file.write_text("# Agents\n", encoding="utf-8")
            events: list[dict[str, object]] = []
            task = {"id": "task", "prompt": "prompt", "expected_files": [], "expected_terms": []}
            with patch("tokenmessung.runner.subprocess.run", return_value=FakeResult()), patch("tokenmessung.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess(["timeout", 0])), patch("tokenmessung.runner.fixture_commit", return_value="abc"), patch("tokenmessung.runner.codex_version", return_value="codex-test"):
                run_one(
                    fixture=fixture,
                    agents_file=agents_file,
                    agents_dir=None,
                    model="model",
                    out=base / "results",
                    task=task,
                    variant="agents",
                    repeat=1,
                    run_order=1,
                    progress=events.append,
                    heartbeat_interval=0.01,
                    max_run_seconds=0.0,
                )
            run_dir = base / "results" / "task__agents__r1"
            self.assertEqual((run_dir / "exit_code.txt").read_text(encoding="utf-8"), "124\n")
            self.assertIn("run_timeout", [event["event"] for event in events])

    def test_selected_tasks_filters_known_ids(self) -> None:
        tasks = selected_tasks(["login_test_failure"])
        self.assertEqual([task["id"] for task in tasks], ["login_test_failure"])
        with self.assertRaises(ValueError):
            selected_tasks(["missing"])


if __name__ == "__main__":
    unittest.main()
