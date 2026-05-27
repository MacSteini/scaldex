# scaldex

scaldex measures whether a Codex instruction package helps or hurts Codex token usage.

It compares the same benchmark task in two isolated variants:

- `agents`: Codex runs with your measured `AGENTS.md` and optional `.codex/` package.
- `control`: Codex runs without that package and without your global `~/.codex` config.

The primary decision metric is the paired median non-cached input token delta. Quality gates come first: failed runs, missing expected files, invalid structured output, missing usage data, or path-integrity warnings block efficiency claims even when tokens look lower.

scaldex is Codex-first. The terminal explains the result to a human, and every run writes `CODEX_HANDOFF.md` so you can give the measurement to Codex for the next action.

## What scaldex is for

Use scaldex when you want to answer:

- Does this `AGENTS.md` or `.codex/` package reduce token usage for Codex?
- Did the instruction package keep quality at 1.0 against control?
- Should I run a decision-grade repeat, stop and fix blockers, or avoid an efficiency claim?
- What exactly should I give Codex so it can interpret the measurement safely?

scaldex does not optimize your instructions automatically. It measures, reports, and produces a Codex handoff.

## Requirements

- Python 3.11 or newer
- Git
- Codex CLI available on `PATH`
- A Codex API key for paid benchmark runs

Check local prerequisites without spending API money:

```sh
scaldex bench doctor
```

For machine-readable prerequisite output:

```sh
scaldex bench doctor --json
```

## Install from a source checkout

From the repository root:

```sh
python3 -m pip install -e .
```

This installs the `scaldex` command. If you do not install the package, use the source-checkout wrapper instead:

```sh
python3 run_scaldex.py --help
```

## Prepare a subject package

Create a folder containing the instruction package you want to measure:

```sh
mkdir -p subject
```

Put `AGENTS.md` in `subject/`. If the package depends on `.codex/` or other support files, put those files in `subject/` too.

The default mode measures the whole `subject/` package. Use `--subject-mode agents-md` only for a diagnostic AGENTS-only run.

## Run a smoke benchmark

A smoke run is the low-cost first check. It runs one paired task: one `control` run and one `agents` run.

```sh
scaldex --model gpt-5.4 --subject-dir subject --task-id login_test_failure --repeats 1
```

If `CODEX_API_KEY` is not set, scaldex asks:

```text
Enter Codex API Key:
```

scaldex uses the key for that process. scaldex does not write it into reports, history, or config files. That is why you may need to enter it again in a new terminal run unless you set `CODEX_API_KEY` yourself.

## Read the result

The terminal output is the human control layer:

- `What this means` explains the verdict.
- `What to do now` tells you whether to stop, hand the report to Codex, run `--repeats 3`, or avoid an efficiency claim.
- `Codex handoff` tells you which file to give Codex and what Codex must not infer.
- `Evidence` explains the primary token metric, quality gate, and reliability.
- `Audit checks` explains isolation, path integrity, report sanity, and warnings.

The run folder contains:

- `scaldex-run/RESULT.md`: human-readable report
- `scaldex-run/CODEX_HANDOFF.md`: Codex instruction for the next action
- `scaldex-run/result.json`: machine-readable report

## Give the result to Codex

For follow-up work, give Codex this file:

```text
scaldex-run/CODEX_HANDOFF.md
```

Codex should follow the requested action in that file. Typical actions are:

- run a decision-grade repeat command
- stop and fix quality or output blockers
- record a decision-grade win
- avoid an efficiency claim and inspect task behaviour

Do not ask Codex to optimize `AGENTS.md` or `.codex/` from a smoke win alone. Smoke evidence only tells you whether a decision-grade run is worth the cost.

## Run decision-grade evidence only when invited

Use at least three paired repeats only when the smoke result says the task is eligible:

```sh
scaldex --model gpt-5.4 --subject-dir subject --task-id login_test_failure --repeats 3
```

Decision-grade evidence is still task-specific. Do not make a global efficiency claim from one task.

## Replay a result without spending money

Replay prints the same result view from an existing `result.json`. It does not ask for an API key and does not run Codex.

```sh
scaldex --print-result scaldex-run/result.json
```

The package CLI can also replay a report:

```sh
scaldex result show scaldex-run/result.json
```

## History and summaries

When a new default run replaces `scaldex-run/`, scaldex archives the previous compact report in `scaldex-history/`.

After you have history, summarize current and older reports without spending money:

```sh
scaldex bench summarize scaldex-history scaldex-run --out scaldex-summary
```

The summary prints a decision view in the terminal and writes:

- `scaldex-summary/SCALDEX_SUMMARY.md`
- `scaldex-summary/scaldex-summary.json`

scaldex allows a global efficiency claim only when enough decision-grade task reports support it. A single task, a smoke run, or a blocked quality gate is not enough.

## Built-in tasks

Use `--task-id` to choose one or more built-in benchmark tasks:

- `login_test_failure`
- `export_cli_location`
- `feature_x_plan`
- `release_scope_audit`

Use `--all-tasks` only when you intentionally want the full task set. It increases paid Codex runs.

## Cost model

Paid Codex run count is:

```text
selected tasks x repeats x 2 variants
```

Examples:

- one task, `--repeats 1`: 2 paid Codex runs
- one task, `--repeats 3`: 6 paid Codex runs
- four tasks, `--repeats 3`: 24 paid Codex runs

Start with smoke. Continue only when the terminal output or `CODEX_HANDOFF.md` tells you to run the next paid benchmark.

## Safety boundaries

- scaldex isolates runs with dedicated `CODEX_HOME` folders.
- scaldex excludes your global `~/.codex` config from the measured instruction source.
- scaldex keeps subject warnings separate from benchmark warnings.
- scaldex treats benchmark warnings as blockers for efficiency claims.
- scaldex does not store your Codex API key in generated reports.

## Licence

MIT
