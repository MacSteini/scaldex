# scaldex built-in tasks

scaldex tasks are small benchmark scenarios, not your project. They use controlled prompts to test whether an instruction package helps Codex behave efficiently without losing quality.

Run one task first. Use `--all-tasks` only when you intentionally want the full paid task set.

## How to read task outcomes

Each task is a narrow proxy for a real Codex workflow. scaldex needs repeatable evidence, so each prompt has expected files, expected terms and a quality gate.

A task can fail for these legitimate reasons:

- the instruction package adds too much reading or tool use
- the package points Codex at the wrong files
- Codex misses expected files or terms
- structured output, usage data or path integrity is not clean
- the measured instructions do not cover the workflow

That last case is important. If you wrote your package mainly for debugging, it may perform well on `login_test_failure` and poorly on `docs_update_scope`. That does not make the package useless. It shows that the package is workflow-specific.

For v1.0, scaldex treats the eight tasks as the core representative set:

- lookup and location finding
- debugging and test-failure analysis
- planning and small code-fix scope
- documentation and release scope
- noisy-repository navigation

These scenarios stay close to common Codex work, but they are not exhaustive. Use them to decide where an instruction package helps, where the package stays neutral or harmful, and where further optimisation needs task-specific evidence.

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

## `small_edit_fix`

Purpose: minimal-fix behaviour.

Codex must identify the smallest sensible code change for a failing discount test without changing files or proposing a broad refactor.

Expected signals:

- `services/billing/src/discount.ts`
- `services/billing/tests/discount.spec.ts`
- relevant terms such as `applyDiscount`, `percentOff` and `discountedTotal`

Use this task when you want to test whether your package keeps Codex focused on a narrow fix instead of widening the scope.

## `test_failure_with_logs`

Purpose: log-discipline behaviour.

Codex must explain a failing email test while large logs are present in the repository.

Expected signals:

- `services/notifications/src/email.ts`
- `services/notifications/tests/email.spec.ts`
- relevant terms such as `formatEmailSubject`, `subjectPrefix` and `Welcome`

Use this task when you want to test whether your package discourages broad log dumps and keeps debugging on the relevant source and test files.

## `docs_update_scope`

Purpose: documentation-scope behaviour.

Codex must plan the scope for documenting an export format option by finding both documentation and implementation references.

Expected signals:

- `docs/API-EXPORT.md`
- `packages/export-cli/src/commands/export.ts`
- relevant export-command terms such as `exportFormat` and `--format`

Use this task when you want to test whether your package finds the right documentation and code context before proposing docs work.

## `large_repo_noise`

Purpose: noisy-repository behaviour.

Codex must find the Search UI integration files while avoiding large, generated or irrelevant files.

Expected signals:

- `services/search/src/index.ts`
- `apps/web/src/search/SearchBox.tsx`
- relevant terms such as `SearchService`, `SearchBox` and `queryIndex`

Use this task when you want to stress-test whether your package remains focused in a repository with deliberate noise.

## Choosing a task

Start with the task closest to the behaviour you care about:

- debugging: `login_test_failure`
- finding code locations: `export_cli_location`
- planning changes: `feature_x_plan`
- auditing release scope: `release_scope_audit`
- minimal code fixes: `small_edit_fix`
- test failures with noisy logs: `test_failure_with_logs`
- documentation scope: `docs_update_scope`
- noisy repository navigation: `large_repo_noise`

If the smoke result is clean, run the same task with `--repeats 3`. Only consider broader claims after all eight built-in tasks have decision-grade reports and at least five are effective.
