# Codex instruction workflow

This guide explains how scaldex fits into the workflow for improving Codex instructions.

## The AGENTS problem

Codex instruction files can help, stay neutral or make work more expensive.

An `AGENTS.md`, `AGENTS.override.md` or `.codex/` package may reduce tool use by telling Codex where to look and when to stop. The same package may also cost tokens if it adds too much context, points Codex at the wrong files or gives rules that do not match the task.

scaldex measures that trade-off. It does not decide whether your instructions are generally good. It checks whether the measured package helps Codex complete controlled task workflows with fewer non-cached input tokens and clean quality gates.

## Roles

- You provide the instruction package to measure.
- scaldex runs paired benchmark tasks and writes evidence.
- Codex can help interpret the evidence or propose instruction changes when you give it the handoff and a clear task.

The measured package lives in `subject/`:

```text
subject/
  AGENTS.md
  .codex/
```

Use `AGENTS.override.md` instead of `AGENTS.md` if that is your intended instruction entry point. Add any support files your Codex setup relies on. Keep generated scaldex report folders outside `subject/`.

## First measurement loop

Start with a smoke benchmark:

```sh
scaldex --model gpt-5.5 --subject-dir subject --task-id login_test_failure --repeats 1
```

This starts two paid Codex runs: one `control` run and one `agents` run.

After the run, read `What this means` and `What to do now` in the terminal output or in `scaldex-run/RESULT.md`.

## Three safe paths after a result

Manual follow-up:

- Read `scaldex-run/RESULT.md`.
- Check whether the task result was smoke or decision-grade.
- Make only changes that match the measured blocker or workflow.
- Rerun the same task after changing the instruction package.

Codex-assisted follow-up:

- Give Codex `scaldex-run/CODEX_HANDOFF.md`.
- Give Codex the measured instruction package if it needs to inspect or edit it.
- Tell Codex what it may do and that paid benchmark runs need explicit approval.

Evidence-first follow-up:

- If the smoke result is clean, run the same task with `--repeats 3` before treating the result as stable.
- If quality, path integrity, output structure or benchmark warnings block the result, fix the blocker before spending more runs.
- If the decision-grade result is not effective, do not claim efficiency for that task.

## Copy-paste prompt for Codex

Use this prompt when you want Codex to act on a scaldex handoff:

```text
I use a CLI tool called scaldex to measure whether my Codex instruction package saves non-cached input tokens without degrading task quality.

The file CODEX_HANDOFF.md contains scaldex's benchmark summary, requested action, allowed actions, forbidden actions, quality gates and evidence grade from my latest run.

Please read CODEX_HANDOFF.md and use it to help with my measured Codex instruction package.

First, state whether the result is smoke or decision-grade evidence. Then state the requested action from the handoff and any blockers.

If the handoff allows optimisation, inspect the measured instruction package I provide and propose minimal evidence-linked changes. Do not make broad rewrites.

If the handoff does not allow optimisation yet, tell me the exact next measurement or blocker-fix step instead.

Do not run paid benchmarks, recommend a paid rerun or claim token efficiency unless the handoff evidence supports that and I explicitly approve the paid run.
```

## Remeasure after changes

After changing the instruction package, rerun the same task first. Comparing the same task is cleaner than switching workflows immediately.

Use decision-grade evidence only when the smoke result or handoff says the task is eligible:

```sh
scaldex --model gpt-5.5 --subject-dir subject --task-id login_test_failure --repeats 3
```

Decision-grade evidence is still task-specific. A global efficiency claim needs all eight built-in tasks as decision-grade reports, at least five effective task results, clean quality gates and no integrity blockers.

For the scoring rules, read the [measurement model](MEASUREMENT-MODEL.md). For task selection, read the [built-in task guide](BUILT-IN-TASKS.md).
