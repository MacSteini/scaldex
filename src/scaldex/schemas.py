from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TASKS: list[dict[str, Any]] = [
    {
        "id": "login_test_failure",
        "prompt": (
            "Finde heraus, warum der Login-Test fehlschlägt. Ändere keine Dateien. "
            "Gib die wahrscheinlich relevante Datei, Ursache und minimale Fix-Idee aus."
        ),
        "expected_files": [
            "services/auth/src/login.ts",
            "apps/web/tests/login.spec.ts",
        ],
        "expected_terms": ["passwordPolicy", "minLength", "LoginError.InvalidCredentials"],
    },
    {
        "id": "export_cli_location",
        "prompt": (
            "Erkläre, wo die Export-CLI implementiert ist. Ändere keine Dateien. "
            "Nenne die relevanten Dateien und die wichtigste Einstiegstelle."
        ),
        "expected_files": [
            "packages/export-cli/src/index.ts",
            "packages/export-cli/src/commands/export.ts",
        ],
        "expected_terms": ["runExportCommand", "registerExportCli"],
    },
    {
        "id": "feature_x_plan",
        "prompt": (
            "Plane eine Änderung an Feature X. Ändere keine Dateien. Finde die relevanten "
            "Subsysteme und gib einen knappen Implementierungsplan aus."
        ),
        "expected_files": [
            "services/feature-x/src/engine.ts",
            "apps/admin/src/features/feature-x/FeatureXPanel.tsx",
        ],
        "expected_terms": ["FeatureXEngine", "FeatureXPanel"],
    },
    {
        "id": "release_scope_audit",
        "prompt": (
            "Führe einen Release-Scope-Audit durch. Ändere keine Dateien. Finde die "
            "relevanten Manifest-, Changelog- und Build-Artefakt-Hinweise und nenne Risiken."
        ),
        "expected_files": [
            "release/manifest.json",
            "CHANGELOG.md",
            "packages/export-cli/package.json",
        ],
        "expected_terms": ["releaseScope", "export-cli", "auth-service"],
    },
]


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "relevant_files": {"type": "array", "items": {"type": "string"}},
        "root_cause_or_location": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["answer", "relevant_files", "root_cause_or_location", "confidence"],
    "additionalProperties": False,
}


def write_default_inputs(base: Path) -> tuple[Path, Path]:
    tasks_path = base / "tasks.json"
    schema_path = base / "output_schema.json"
    tasks_path.write_text(json.dumps(TASKS, indent=2) + "\n", encoding="utf-8")
    schema_path.write_text(json.dumps(OUTPUT_SCHEMA, indent=2) + "\n", encoding="utf-8")
    return tasks_path, schema_path
