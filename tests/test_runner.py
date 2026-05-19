from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scaldex.fixture import create_fixture
from scaldex.runner import GENERATED_MARKER, audit_subject_source, copy_fixture, init_git_snapshot, install_agents_dir, install_agents_file, prepare_generated_dir, remove_control_instructions, run_benchmark, run_one, selected_tasks, subject_fingerprint, synthesize_benchmark, validate_benchmark_inputs


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

    def test_subject_audit_reports_package_size_and_codex_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subject = Path(tmp) / "subject"
            (subject / ".codex" / "skills" / "demo").mkdir(parents=True)
            (subject / ".codex" / "config" / "tooling").mkdir(parents=True)
            (subject / ".codex" / "bin").mkdir(parents=True)
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            (subject / ".codex" / "skills" / "demo" / "SKILL.md").write_text("x" * 33_000, encoding="utf-8")
            (subject / ".codex" / "config" / "tooling" / "config.txt").write_text("tooling\n", encoding="utf-8")
            (subject / ".codex" / "bin" / "validate").write_text("validate\n", encoding="utf-8")
            audit = audit_subject_source(None, subject, subject_mode="package")
            self.assertEqual(audit["mode"], "package")
            self.assertGreater(audit["total_bytes"], 32_000)
            self.assertIn("large_subject", audit["warnings"])
            self.assertIn("subject_contains_codex", audit["warnings"])
            self.assertIn("subject_contains_codex_skills", audit["warnings"])
            self.assertIn("subject_contains_codex_tooling", audit["warnings"])
            self.assertIn("subject_contains_codex_bin", audit["warnings"])
            self.assertEqual(len(audit["fingerprint"]), 64)

    def test_subject_fingerprint_is_stable_and_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subject = Path(tmp) / "subject"
            subject.mkdir()
            (subject / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            first = subject_fingerprint(None, subject)
            second = subject_fingerprint(None, subject)
            self.assertEqual(first, second)
            (subject / "AGENTS.md").write_text("# Agents changed\n", encoding="utf-8")
            self.assertNotEqual(first, subject_fingerprint(None, subject))

    def test_control_snapshot_is_clean_after_instruction_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            (fixture / ".codex").mkdir()
            (fixture / ".codex" / "instructions.md").write_text("# Support\n", encoding="utf-8")
            workdir = base / "work"
            copy_fixture(fixture, workdir)
            remove_control_instructions(workdir)
            init_git_snapshot(workdir)
            status = subprocess.run(["git", "status", "--short"], cwd=workdir, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(status.stdout.strip(), "")

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
            with patch("scaldex.runner.codex_exec_capabilities", return_value={"supports_json": True, "supports_output_schema": True, "supports_ignore_user_config": True, "supports_ignore_rules": True}):
                validate_benchmark_inputs(fixture, None, 1, require_api_key=False, agents_dir=subject)

    def test_validate_rejects_missing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            agents_file = fixture / "AGENTS.md"
            with patch.dict("os.environ", {}, clear=True), patch("scaldex.runner.codex_exec_capabilities", return_value={"supports_json": True, "supports_output_schema": True, "supports_ignore_user_config": True, "supports_ignore_rules": True}):
                with self.assertRaises(EnvironmentError):
                    validate_benchmark_inputs(fixture, agents_file, 1)

    def test_prepare_generated_dir_refuses_unmarked_nonempty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "user-file.txt").write_text("do not delete\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_generated_dir(out)
            self.assertTrue((out / "user-file.txt").exists())

    def test_prepare_generated_dir_replaces_marked_generated_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / GENERATED_MARKER).write_text("generated\n", encoding="utf-8")
            (out / "stale").mkdir()
            prepare_generated_dir(out)
            self.assertTrue((out / GENERATED_MARKER).exists())
            self.assertFalse((out / "stale").exists())

    def test_run_benchmark_cleans_marked_results_before_new_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out = base / "results"
            out.mkdir()
            (out / GENERATED_MARKER).write_text("generated\n", encoding="utf-8")
            stale = out / "old_task__agents__r1" / "meta.json"
            stale.parent.mkdir()
            stale.write_text("{}\n", encoding="utf-8")
            workspace_root = base / "workspaces"
            fixture = base / "fixture"
            agents_file = fixture / "AGENTS.md"
            task = {"id": "task", "prompt": "prompt", "expected_files": [], "expected_terms": []}

            def fake_run_one(**kwargs: object) -> None:
                self.assertFalse(stale.exists())
                run_dir = Path(kwargs["out"]) / f"{task['id']}__{kwargs['variant']}__r{kwargs['repeat']}"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text("{}\n", encoding="utf-8")

            with patch("scaldex.runner.validate_benchmark_inputs"), patch("scaldex.runner.fixture_commit", return_value="abc"), patch("scaldex.runner.audit_subject_source", return_value={"mode": "manual", "file_count": 1, "total_bytes": 1, "fingerprint": "subject", "warnings": []}), patch("scaldex.runner.selected_tasks", return_value=[task]), patch("scaldex.runner.run_one", side_effect=fake_run_one), patch("scaldex.runner.analyze_results", return_value={"result_json": out / "result.json"}):
                run_benchmark(fixture, agents_file, "model", 1, out, workspace_root=workspace_root)
            self.assertTrue((out / GENERATED_MARKER).exists())
            self.assertTrue((workspace_root / GENERATED_MARKER).exists())

    def test_run_benchmark_passes_same_batch_id_and_config_to_all_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out = base / "results"
            workspace_root = base / "workspaces"
            fixture = base / "fixture"
            agents_file = fixture / "AGENTS.md"
            task = {"id": "task", "prompt": "prompt", "expected_files": [], "expected_terms": []}
            seen: list[dict[str, object]] = []

            def fake_run_one(**kwargs: object) -> None:
                seen.append(kwargs)
                run_dir = Path(kwargs["out"]) / f"{task['id']}__{kwargs['variant']}__r{kwargs['repeat']}"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text("{}\n", encoding="utf-8")

            with patch("scaldex.runner.validate_benchmark_inputs"), patch("scaldex.runner.fixture_commit", return_value="abc"), patch("scaldex.runner.audit_subject_source", return_value={"mode": "manual", "file_count": 1, "total_bytes": 1, "fingerprint": "subject-fp", "warnings": []}), patch("scaldex.runner.selected_tasks", return_value=[task]), patch("scaldex.runner.run_one", side_effect=fake_run_one), patch("scaldex.runner.analyze_results", return_value={"result_json": out / "result.json"}):
                run_benchmark(fixture, agents_file, "model", 2, out, seed=7, workspace_root=workspace_root, batch_id="batch-fixed")
            self.assertEqual(len(seen), 4)
            self.assertEqual({item["batch_id"] for item in seen}, {"batch-fixed"})
            self.assertEqual({item["run_config_fingerprint"] for item in seen}, {seen[0]["run_config_fingerprint"]})
            self.assertEqual(seen[0]["run_config"]["expected_run_count"], 4)

    def test_synthesize_benchmark_creates_complete_paired_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "synthetic"
            paths = synthesize_benchmark(out, repeats=2, seed=1)
            self.assertTrue(paths["summary_csv"].exists())
            self.assertEqual(len(list(out.glob("*/meta.json"))), 16)
            self.assertTrue((out / "paired-deltas.csv").read_text(encoding="utf-8"))
            first_meta = json.loads(next(out.glob("*/meta.json")).read_text(encoding="utf-8"))
            second_out = Path(tmp) / "synthetic-again"
            synthesize_benchmark(second_out, repeats=2, seed=1)
            second_meta = json.loads(next(second_out.glob("*/meta.json")).read_text(encoding="utf-8"))
            self.assertEqual(first_meta["batch_id"], second_meta["batch_id"])
            self.assertEqual(first_meta["run_config_fingerprint"], second_meta["run_config_fingerprint"])

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
            with patch("scaldex.runner.subprocess.run", return_value=FakeResult()), patch("scaldex.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess()), patch("scaldex.runner.fixture_commit", return_value="abc"), patch("scaldex.runner.codex_version", return_value="codex-test"):
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
            with patch("scaldex.runner.subprocess.run", return_value=FakeResult()), patch("scaldex.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess()), patch("scaldex.runner.fixture_commit", return_value="abc"), patch("scaldex.runner.codex_version", return_value="codex-test"):
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
            with patch("scaldex.runner.subprocess.run", return_value=FakeResult()), patch("scaldex.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess(["timeout", 0])), patch("scaldex.runner.fixture_commit", return_value="abc"), patch("scaldex.runner.codex_version", return_value="codex-test"):
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
            self.assertNotIn("[scaldex]", artifact_text)
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
            with patch("scaldex.runner.subprocess.run", return_value=FakeResult()), patch("scaldex.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess(["timeout", 0])), patch("scaldex.runner.fixture_commit", return_value="abc"), patch("scaldex.runner.codex_version", return_value="codex-test"):
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
