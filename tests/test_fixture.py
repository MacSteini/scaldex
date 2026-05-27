from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scaldex.fixture import create_fixture


class FixtureTests(unittest.TestCase):
    def test_create_fixture_contains_expected_files_and_git_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = create_fixture(Path(tmp) / "fixture")
            expected = [
                "services/auth/src/login.ts",
                "apps/web/tests/login.spec.ts",
                "packages/export-cli/src/index.ts",
                "services/feature-x/src/engine.ts",
                "release/manifest.json",
                "services/billing/src/discount.ts",
                "services/billing/tests/discount.spec.ts",
                "services/notifications/src/email.ts",
                "services/notifications/tests/email.spec.ts",
                "docs/API-EXPORT.md",
                "services/search/src/index.ts",
                "apps/web/src/search/SearchBox.tsx",
                "vendor/generated/search-index.js",
                "tasks.json",
                "output_schema.json",
            ]
            for relative in expected:
                self.assertTrue((fixture / relative).exists(), relative)
            tasks = json.loads((fixture / "tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(len(tasks), 8)
            self.assertEqual(
                [task["id"] for task in tasks],
                [
                    "login_test_failure",
                    "export_cli_location",
                    "feature_x_plan",
                    "release_scope_audit",
                    "small_edit_fix",
                    "test_failure_with_logs",
                    "docs_update_scope",
                    "large_repo_noise",
                ],
            )
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=fixture, check=True, text=True, stdout=subprocess.PIPE)
            self.assertEqual(len(commit.stdout.strip()), 40)


if __name__ == "__main__":
    unittest.main()
