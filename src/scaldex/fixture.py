from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .schemas import write_default_inputs


def run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_fixture(out: Path, force: bool = False) -> Path:
    if out.exists():
        if not force:
            raise FileExistsError(f"Fixture path already exists: {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True)

    write(out / "package.json", json.dumps({"name": "codex-token-fixture", "private": True}, indent=2) + "\n")
    write(out / "CHANGELOG.md", "# Changelog\n\n## 1.4.0\n\n- Added releaseScope metadata for export-cli and auth-service.\n")
    write(
        out / "AGENTS.md",
        "\n".join(
            [
                "# Fixture AGENTS",
                "",
                "- Prefer `rg`, `find`, `wc`, and narrow `sed -n` reads.",
                "- Do not dump logs, JSONL files, minified assets, or generated folders.",
                "- Check file sizes before reading large files.",
                "",
            ]
        ),
    )

    write(
        out / "services/auth/src/login.ts",
        """export enum LoginError {
  InvalidCredentials = "LoginError.InvalidCredentials",
}

const passwordPolicy = {
  minLength: 12,
};

export function canLogin(password: string): boolean {
  return password.length >= passwordPolicy.minLength;
}

export function login(password: string): string {
  if (!canLogin(password)) {
    throw new Error(LoginError.InvalidCredentials);
  }
  return "ok";
}
""",
    )
    write(
        out / "apps/web/tests/login.spec.ts",
        """import { login } from "../../../services/auth/src/login";

test("accepts valid legacy demo password", () => {
  expect(login("demo-pass")).toBe("ok");
});
""",
    )
    write(
        out / "packages/export-cli/src/index.ts",
        """import { registerExportCli } from "./commands/export";

registerExportCli(process.argv.slice(2));
""",
    )
    write(
        out / "packages/export-cli/src/commands/export.ts",
        """export type ExportFormat = "json" | "csv";

export function runExportCommand(target: string, exportFormat: ExportFormat = "json"): string {
  return `export:${target}:${exportFormat}`;
}

export function registerExportCli(args: string[]): void {
  const target = args[0] ?? "default";
  const exportFormat = (args.includes("--format") ? args[args.indexOf("--format") + 1] : "json") as ExportFormat;
  runExportCommand(target, exportFormat);
}
""",
    )
    write(
        out / "packages/export-cli/package.json",
        json.dumps({"name": "@fixture/export-cli", "bin": {"fixture-export": "dist/index.js"}}, indent=2) + "\n",
    )
    write(
        out / "services/feature-x/src/engine.ts",
        """export class FeatureXEngine {
  planChange(flagName: string): string {
    return `feature-x:${flagName}`;
  }
}
""",
    )
    write(
        out / "apps/admin/src/features/feature-x/FeatureXPanel.tsx",
        """export function FeatureXPanel() {
  return <section data-feature="feature-x">Feature X</section>;
}
""",
    )
    write(
        out / "release/manifest.json",
        json.dumps(
            {
                "releaseScope": ["export-cli", "auth-service"],
                "generated": "build/release-bundle.js",
            },
            indent=2,
        )
        + "\n",
    )
    write(
        out / "services/billing/src/discount.ts",
        """export type Discount = {
  percentOff: number;
};

export function applyDiscount(total: number, discount: Discount): number {
  const discountedTotal = total - discount.percentOff;
  return Math.max(0, discountedTotal);
}
""",
    )
    write(
        out / "services/billing/tests/discount.spec.ts",
        """import { applyDiscount } from "../src/discount";

test("applies percent discount", () => {
  expect(applyDiscount(250, { percentOff: 20 })).toBe(200);
});
""",
    )
    write(
        out / "services/notifications/src/email.ts",
        """const subjectPrefix = "[Fixture]";

export function formatEmailSubject(title: string): string {
  return `${subjectPrefix} ${title.toLowerCase()}`;
}
""",
    )
    write(
        out / "services/notifications/tests/email.spec.ts",
        """import { formatEmailSubject } from "../src/email";

test("keeps welcome subject title case", () => {
  expect(formatEmailSubject("Welcome")).toBe("[Fixture] Welcome");
});
""",
    )
    write(
        out / "docs/API-EXPORT.md",
        """# Export API

The `fixture-export` command supports `--target`.

The next documentation update must describe the `--format` option and the `exportFormat` value passed to the command layer.
""",
    )
    write(
        out / "services/search/src/index.ts",
        """export class SearchService {
  queryIndex(query: string): string[] {
    return query.trim() ? [`result:${query}`] : [];
  }
}
""",
    )
    write(
        out / "apps/web/src/search/SearchBox.tsx",
        """import { SearchService } from "../../../services/search/src";

export function SearchBox() {
  const service = new SearchService();
  return <input aria-label="Search" data-results={service.queryIndex("demo").join(",")} />;
}
""",
    )

    write(out / "logs/app.log", "\n".join(f"2026-01-01T00:00:{i:02d}Z noisy login trace {i}" for i in range(5000)) + "\n")
    write(out / "logs/email-debug.log", "\n".join(f"2026-01-01T00:10:{i:02d}Z noisy email trace {i}" for i in range(5000)) + "\n")
    write(out / "data/events.jsonl", "\n".join(json.dumps({"event": "noise", "i": i, "payload": "x" * 120}) for i in range(4000)) + "\n")
    write(out / "dist/app.min.js", "function a(b){return b.map(function(c){return c+1})};" * 2500)
    write(out / "build/release-bundle.js", "var bundle=true;" * 3000)
    write(out / "coverage/lcov.info", "TN:\nSF:generated.ts\nDA:1,1\nend_of_record\n" * 1000)
    write(out / "vendor/generated/search-index.js", "var searchNoise=true;" * 5000)
    write(out / "docs/subsystems.md", "Auth, billing, notifications, export CLI, Feature X, search, and release subsystems are intentionally separated.\n")

    write_default_inputs(out)
    run_git(["init", "-q"], out)
    run_git(["add", "."], out)
    subprocess.run(
        ["git", "-c", "user.name=scaldex", "-c", "user.email=scaldex@example.invalid", "commit", "-q", "-m", "fixture snapshot"],
        cwd=out,
        check=True,
    )
    return out
