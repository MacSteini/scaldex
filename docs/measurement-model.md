# scaldex measurement model

This document explains what scaldex measures and how it decides whether a result is useful.

## What gets measured

scaldex measures a Codex instruction package supplied through `--subject-dir`.

The subject directory must contain `AGENTS.md`, because Codex uses it as the instruction entry point. The directory may also contain `.codex/` and any other support files your setup needs. scaldex copies that package into the benchmark workspace for the `agents` variant.

scaldex creates a temporary benchmark fixture with small source files, tests, release metadata and intentionally noisy generated files. The fixture is not your project; it gives both variants the same controlled workspace.

## The two variants

Each selected task runs in paired variants:

- `agents`: the fixture plus your measured instruction package.
- `control`: the same fixture without your measured package and without your global `~/.codex` config.

Both variants run with:

- a dedicated per-run `CODEX_HOME`
- `--ignore-user-config`
- `--ignore-rules`
- read-only sandboxing
- the same output schema
- the same task prompt

That isolation is why the result compares the measured package against a clean control, not against your personal Codex setup.

## Subject fingerprint

Before a run starts, scaldex audits the subject package:

- counts included files
- counts bytes
- records the largest files
- creates a subject fingerprint from included paths and file contents
- warns about large packages or `.codex/` support folders

The fingerprint is an identity check. Use it when comparing reports to confirm that they measured the same package version.

## Primary metric

The primary metric is:

```text
paired median non-cached input token delta
```

In plain English: for each task repeat, scaldex subtracts the control run's non-cached input tokens from the matching agents run's non-cached input tokens. It then takes the median of those paired deltas.

Negative is better: `agents` used fewer non-cached input tokens than `control`.

Positive is worse: `agents` used more non-cached input tokens than `control`.

scaldex shows variant medians for context, but they are not the decision metric. Pairing matters because each repeat compares matching conditions.

## Quality gate

Token savings only count if quality stays intact.

The quality score is a success rate:

- `1.0` means 100% of required checks passed.
- `0.0` means 0% passed.
- Values between those numbers mean only some repeats passed.

A run fails the quality gate if either side misses required files, emits invalid structured output, lacks usage data, exits non-zero, produces unsafe `relevant_files`, or triggers benchmark warnings that block efficiency claims.

Quality blockers override token savings.

## Smoke vs decision-grade

A smoke run uses `--repeats 1`. Treat it as a cost check and route finder. A clean smoke can tell you that a task is worth repeating, but it does not provide stable evidence.

A decision-grade run uses `--repeats 3` or more. It costs more, but it gives enough paired repeats for task-level evidence.

One decision-grade task is still only one task. A global efficiency claim needs enough decision-grade task reports, and they must share the same subject fingerprint.

## Global claims

scaldex withholds global token-efficiency claims unless enough decision-grade tasks are effective and quality is clean.

The summary command checks this across existing reports:

```sh
scaldex bench summarize scaldex-history scaldex-run --out scaldex-summary
```

Do not claim global efficiency from:

- a smoke run
- one task
- mixed subject fingerprints
- failed quality gates
- missing expected files
- benchmark warnings
- unpaired variant medians alone

## Report files

Each run writes:

- `RESULT.md`: human-readable report.
- `CODEX_HANDOFF.md`: Codex-facing follow-up brief.
- `result.json`: machine-readable evidence.

Use `RESULT.md` if you want to inspect the result yourself. Use `CODEX_HANDOFF.md` if you want Codex-assisted interpretation or package improvement.
