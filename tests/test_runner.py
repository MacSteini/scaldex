from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tokenmessung.fixture import create_fixture
from tokenmessung.runner import copy_fixture, install_agents_file, remove_control_instructions


class RunnerVariantTests(unittest.TestCase):
    def test_control_variant_removes_instruction_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = create_fixture(base / "fixture")
            (fixture / ".codex").mkdir()
            (fixture / ".codex" / "config.toml").write_text("model = 'x'\n", encoding="utf-8")
            (fixture / ".codex-project").mkdir()
            workdir = base / "work"
            copy_fixture(fixture, workdir)
            remove_control_instructions(workdir)
            self.assertFalse((workdir / "AGENTS.md").exists())
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


if __name__ == "__main__":
    unittest.main()
