# scaldex built-in tasks

scaldex tasks are small benchmark scenarios, not your project. They use controlled prompts to test whether an instruction package helps Codex behave efficiently without losing quality.

Run one task first. Use `--all-tasks` only when you intentionally want the full paid task set.

## `login_test_failure`

Purpose: debugging behaviour.

Codex must explain why a login test fails and identify the likely production cause without changing files.

Expected signals:

- `services/auth/src/login.ts`
- `apps/web/tests/login.spec.ts`
- relevant terms such as `passwordPolicy`, `minLength` and `LoginError.InvalidCredentials`

Use this task when you want to test whether your package helps Codex debug narrowly instead of reading broad logs or generated output.

## `export_cli_location`

Purpose: location lookup behaviour.

Codex must explain where the export CLI lives and name the entry point.

Expected signals:

- `packages/export-cli/src/index.ts`
- `packages/export-cli/src/commands/export.ts`
- relevant terms such as `runExportCommand` and `registerExportCli`

Use this task when you want to test fast path-finding, command discovery and entry-point identification.

## `feature_x_plan`

Purpose: feature-planning behaviour.

Codex must plan a Feature X change by finding the relevant service and UI files before proposing the implementation.

Expected signals:

- `services/feature-x/src/engine.ts`
- `apps/admin/src/features/feature-x/FeatureXPanel.tsx`
- relevant terms such as `FeatureXEngine` and `FeatureXPanel`

Use this task when you want to test whether your package supports focused planning without broad repository reading.

## `release_scope_audit`

Purpose: release-audit behaviour.

Codex must identify release-scope files, changelog context and package metadata before naming risks.

Expected signals:

- `release/manifest.json`
- `CHANGELOG.md`
- `packages/export-cli/package.json`
- relevant terms such as `releaseScope`, `export-cli` and `auth-service`

Use this task when you want to test audit discipline, release-scope discovery and repo-relative `relevant_files`.

## Choosing a task

Start with the task closest to the behaviour you care about:

- debugging: `login_test_failure`
- finding code locations: `export_cli_location`
- planning changes: `feature_x_plan`
- auditing release scope: `release_scope_audit`

If the smoke result is clean, run the same task with `--repeats 3`. Only consider broader claims after three or more decision-grade tasks.
