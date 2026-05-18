# Tokenmessung Public UX Plan

## Current State

- Tokenmessung has a working measurement core: paired agents/control runs, batch IDs, subject fingerprints, run configuration fingerprints, quality gates, normalized repo-relative `relevant_files`, and paired median non-cached input deltas.
- The current user experience is no longer just raw metrics, but the decision narrative still needs to be explicit enough for a first-time user or fresh Codex agent.
- End-user documentation is intentionally deferred until the operational UX is stable.
- Do not run paid Codex benchmarks during this sequence unless the user approves them later.

## Target State

- Console output tells the user the next safe action without requiring manual report interpretation.
- `RESULT.md` starts with a compact decision summary before detailed metrics.
- Existing result files from a run set can produce a local summary without new API calls.
- Each result includes a Codex-ready handoff brief so users can feed the measurement into a follow-up agent.
- Each decision explains what happened, why it matters, and what the next action should be.
- Existing `result.json` files can print console decisions again without new paid runs.
- Re-running the default root runner preserves compact previous reports for later summaries.
- This plan specifies a future smart runner but does not build it yet.
- Public README/end-user documentation remains last.

## Sequential Checklist

| Step | Status | Goal | Success Measurement | Audit |
| --- | --- | --- | --- | --- |
| 0 | done | Create this root plan. | `PUBLIC_UX_PLAN.md` exists and lists all steps. | No secrets, no private benchmark artefacts, no measurement logic changes. |
| 1 | done | Add console `Next action`. | Console prints whether to stop, run decision-grade, record win, or reject efficiency. | Tests cover all action categories; decisions do not use unpaired medians. |
| 2 | done | Add `RESULT.md` Decision Summary. | First report lines show decision, next action, quality gate, warnings, and claim status. | Benchmark and subject warnings remain separated; integrity failures stay not effective. |
| 3 | done | Add local multi-task summary. | Existing `result.json` files can produce `TOKENMESSUNG_SUMMARY.md` and `tokenmessung-summary.json` without API calls. | Mixed fingerprints and mixed smoke/decision-grade inputs are explicit. |
| 4 | done | Add decision reasons and Codex handoff. | Reports include `Reason`; analysis writes `CODEX_HANDOFF.md`. | Handoff repeats primary-metric and quality-gate rules; no optimisation is automatic. |
| 5 | done | Preserve compact previous reports. | Default reruns archive compact reports before replacing `tokenmessung-run/`. | Archive excludes raw workspaces and secrets; summaries can use preserved `result.json`. |
| 6 | done | Specify future smart runner only. | Root plan contains `tokenmessung evaluate --subject-dir ... --model ... --budget-runs ...` behaviour and stop rules. | No auto-run implementation or paid-run trigger added. |
| 7 | done | Defer end-user documentation. | README is not created until operational UX is stable. | Later README examples must match final CLI behaviour. |
| 8 | done | Add human-readable decision storyline. | Console, `RESULT.md`, `result.json`, and `CODEX_HANDOFF.md` explain the decision in plain language. | No verdict or benchmark math changes; fresh-agent handoff remains non-automatic. |
| 9 | done | Add result replay for end users. | Users can show existing `result.json` files via `run_tokenmessung.py --print-result` and `tokenmessung result show`. | No API key, subject audit, run reset, or paid benchmark occurs in replay mode. |
| 10 | done | Remove synthetic demo from end-user UX. | Public help and local user flow focus on real smoke runs, replay, and summaries. | Internal synthetic fixtures remain test-only; no measurement logic changed. |
| 11 | done | Add Codex-first output contract. | CLI and `CODEX_HANDOFF.md` tell Codex exactly what to do and what not to claim. | Human report remains readable; no measurement logic changed. |

## Verification After Each Step

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py`
- Internal fixture generation is covered by runner unit tests; it is not part of the public CLI flow.

## Audit Notes

### Step 0

- Status: done
- Measurement:
  - Root plan file created.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
- Audit:
  - Measurement code was not modified.
  - The change did not add a README.
  - The change did not add API keys, local secrets, or raw benchmark artefacts.

### Step 1

- Status: done
- Measurement:
  - `result.json` now includes an additive `decision` object.
  - Console output now includes `Next action`.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
  - Internal synthetic fixture generation was covered by runner unit tests.
  - `PYTHONPATH=src python3 -m tokenmessung bench analyze --results /private/tmp/tokenmessung-synth-clean` passed.
- Audit:
  - Unit tests cover `eligible_for_decision_run`, `stop_fix_quality_or_task_behavior`, `record_decision_grade_win`, and `do_not_claim_efficiency`.
  - Decision logic records `uses_unpaired_variant_medians_for_decision: false`.
  - Existing verdict and paired primary metric logic remain unchanged.

### Step 2

- Status: done
- Measurement:
  - `RESULT.md` now starts with a `Decision Summary`.
  - The summary includes decision, next action, primary metric, quality gate, warnings, and global claim eligibility.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
  - Internal synthetic fixture generation was covered by runner unit tests.
  - `PYTHONPATH=src python3 -m tokenmessung bench analyze --results /private/tmp/tokenmessung-synth-clean` passed.
- Audit:
  - Decision Summary states variant medians are secondary context.
  - Benchmark warnings shown in the summary remain separate from subject warnings in the detailed sections.
  - Existing integrity and quality failures still force `not_effective` through existing verdict logic.

### Step 3

- Status: done
- Measurement:
  - Added local `tokenmessung bench summarize INPUT... --out OUT` mode.
  - Summary writes `tokenmessung-summary.json` and `TOKENMESSUNG_SUMMARY.md`.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
  - Internal synthetic fixture generation was covered by runner unit tests.
  - `PYTHONPATH=src python3 -m tokenmessung bench analyze --results /private/tmp/tokenmessung-synth-clean` passed.
  - `PYTHONPATH=src python3 -m tokenmessung bench summarize /private/tmp/tokenmessung-synth-clean --out /private/tmp/tokenmessung-multi-summary` passed.
- Audit:
  - Summarize mode makes no Codex or API call.
  - Tests cover folder/file discovery, global claim threshold, mixed subject fingerprints, and mixed smoke/decision-grade inputs.
  - Global efficiency claim requires at least 3 effective decision-grade tasks across the expected task set.

### Step 4

- Status: done
- Measurement:
  - `RESULT.md` Decision Summary now includes `Reason`.
  - `result.json` decision data now includes a machine-readable `reason`.
  - Analysis writes `CODEX_HANDOFF.md` for direct follow-up use in Codex.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
  - Internal synthetic fixture generation was covered by runner unit tests.
  - `PYTHONPATH=src python3 -m tokenmessung bench analyze --results /private/tmp/tokenmessung-product-ux-probe` passed.
  - `PYTHONPATH=src python3 -m tokenmessung bench summarize /private/tmp/tokenmessung-product-ux-probe --out /private/tmp/tokenmessung-product-ux-summary` passed.
- Audit:
  - Codex handoff states that paired median non-cached input delta is the primary decision metric.
  - Handoff treats failed quality gates and benchmark warnings as blockers.
  - Handoff does not trigger paid reruns or automatic optimisation.

### Step 5

- Status: done
- Measurement:
  - Root runner archives compact previous reports into `tokenmessung-history/` before replacing the default run folder.
  - Archived compact reports include `RESULT.md`, `CODEX_HANDOFF.md`, `result.json`, `summary.csv`, `summary.json`, and `paired-deltas.csv` when present.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
- Audit:
  - Archive excludes raw workspaces and raw Codex JSONL output.
  - Archive preserves `result.json` files that `tokenmessung bench summarize` can consume later.
  - Custom non-generated run folders remain protected from replacement.

### Step 6

- Status: done
- Measurement:
  - The section below specifies future `tokenmessung evaluate --subject-dir ... --model ... --budget-runs ...` behaviour.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
- Audit:
  - The change did not build an `evaluate` command.
  - The change did not add paid-run automation.
  - The specification requires explicit approval before any future paid-run plan.

### Step 7

- Status: done
- Measurement:
  - The change did not create a README.
  - `LOCAL_TEST.md` remains the only short local reference.
- Audit:
  - End-user documentation remains deferred until the operational UX is stable.
  - Later README examples must match final CLI behaviour.

### Step 8

- Status: done
- Measurement:
  - `result.json` decision data now includes `explanation` and `scope`.
  - Console output now includes `Decision explanation`.
  - `RESULT.md` Decision Summary includes a plain-language explanation.
  - `CODEX_HANDOFF.md` now includes `Human Reading`: what happened, why it matters, and what to do next.
  - Multi-task/result-set reports no longer describe the evidence as only "this task".
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
  - Internal synthetic fixture generation was covered by runner unit tests.
  - `PYTHONPATH=src python3 -m tokenmessung bench analyze --results /private/tmp/tokenmessung-storyline-probe` passed.
  - `PYTHONPATH=src python3 -m tokenmessung bench summarize /private/tmp/tokenmessung-storyline-probe --out /private/tmp/tokenmessung-storyline-summary` passed.
  - `.codex/bin/validate` passed.
- Audit:
  - Verdict, quality gate, and paired primary metric logic remain unchanged.
  - Handoff remains advisory and does not start paid runs.
  - Fresh-agent handoff tells the reader not to use variant medians as the decision metric.

### Step 9

- Status: done
- Measurement:
  - Added `run_tokenmessung.py --print-result RESULT_JSON`.
  - Added `tokenmessung result show RESULT_JSON`.
  - Console rendering now lives in reusable result-console code shared by real runs and replay.
  - Replay prints the same `=== Tokenmessung Result ===` decision view as a real run.
  - Replay requires no model, no API key, no subject directory, no fixture, and no run folder reset.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
  - Internal synthetic fixture generation was covered by runner unit tests.
  - `PYTHONPATH=src python3 -m tokenmessung bench analyze --results /private/tmp/tokenmessung-replay-probe` passed.
  - `PYTHONPATH=src python3 -m tokenmessung bench summarize /private/tmp/tokenmessung-replay-probe --out /private/tmp/tokenmessung-replay-summary` passed.
  - `PYTHONPATH=src python3 -m tokenmessung result show /private/tmp/tokenmessung-replay-probe/result.json` passed.
  - `python3 run_tokenmessung.py --print-result /private/tmp/tokenmessung-replay-probe/result.json` passed.
- Audit:
  - Measurement math, verdicts, quality gates, and history archive structure remain unchanged.
  - Replay only reads existing run and history files.
  - Mixed replay/benchmark mode fails fast to avoid accidental paid-run expectations.

### Step 10

- Status: done
- Measurement:
  - `tokenmessung bench --help` no longer exposes synthetic fixture generation.
  - `LOCAL_TEST.md` describes only the real enduser flow: prepare `subject/`, run a smoke test, read the terminal decision, replay existing reports, and summarize real reports.
  - Console result output now uses `What this means` and `What to do now` instead of requiring users to interpret technical action codes.
- Audit:
  - Synthetic fixture generation remains available only as internal test support.
  - Public help and local user guidance do not present synthetic data as a user feature.
  - Verdict rules, paired metric calculations, and quality gates remain unchanged.

### Step 11

- Status: done
- Measurement:
  - Console output now includes a human-facing `Codex handoff` block with file path, purpose, and safety boundary.
  - `CODEX_HANDOFF.md` now starts as `Tokenmessung Codex Instruction` and gives Codex a requested action, evidence grade, primary metric, quality gates, allowed actions, forbidden actions, files to inspect, and expected output.
  - Replay prefers local sibling report files next to the loaded `result.json`, so archived handoff files are safe to pass to Codex.
- Audit:
  - Smoke results forbid optimisation and global efficiency claims.
  - Quality blockers remain blockers even when token deltas look good.
  - Variant medians remain secondary context and are not used as the decision metric.

### Step 12

- Status: done
- Measurement:
  - Console output now uses readable sections: `Result`, `Next step`, `Codex handoff`, `What was compared`, `Evidence`, `Audit checks`, and `Report files`.
  - The terminal explains `agents` and `control` directly before their metrics appear.
  - Token delta, quality, fingerprints, isolation, path integrity, reliability, and tool sanity now render as explanatory sentences instead of raw key-value rows.
  - `RESULT.md` includes a glossary for `agents`, `control`, `paired delta`, `fingerprint`, and normalized repo-relative `relevant_files`.
- Audit:
  - `result.json`, verdict rules, history behaviour, and `CODEX_HANDOFF.md` contract remain unchanged.
  - The terminal remains for human understanding; Codex action remains delegated through `CODEX_HANDOFF.md`.
  - Technical fields still exist in machine-readable artefacts for automation and audits.

## Future Smart Runner Specification

- Status: done.
- Intended future command shape: `tokenmessung evaluate --subject-dir ... --model ... --budget-runs ...`.
- This is specification-only. No implementation exists in this step.

### Intended Command

```sh
tokenmessung evaluate --subject-dir ./Agent --model gpt-5.4 --budget-runs 12
```

### Required Behaviour

- Resolve and audit the subject once before any paid run.
- Display the highest possible paid run count before starting.
- Run every configured task first with `repeats=1`.
- Stop a task after smoke when:
  - agents/control quality is not 1.0/1.0,
  - benchmark warnings are present,
  - normalized repo-relative `relevant_files` is false,
  - integrity status fails.
- Run `repeats=3` only for smoke-passing tasks and only while `--budget-runs` still allows it.
- Never claim global token efficiency unless the multi-task summary rule allows it.
- Persist every per-task `result.json` in a non-overwriting run folder so `bench summarize` can assess all tasks afterward.

### Required Stop Rules

- Stop before starting if planned smoke runs exceed `--budget-runs`.
- Stop before decision-grade runs if no task passed smoke.
- Stop on mixed `subject_fingerprint` or mixed `run_config_fingerprint`.
- Stop on missing authoritative usage data, invalid final JSON, nonzero exit code, missing expected files, or missing expected relevant files.
- Stop when the user did not explicitly approve the displayed paid-run plan.

### Non-Goals

- Do not build automatic AGENTS.md optimization.
- Do not integrate CodeBurn or any external cost dashboard.
- Do not hide raw path violations; normalized quality and raw path reporting must both remain visible.
- Do not replace `run_tokenmessung.py` until local tests and explicit approval prove the future command.

## Documentation Policy

- Do not create public end-user documentation yet.
- Keep `LOCAL_TEST.md` as the current local reference.
- Write a public README only after console decisions, report summary, and multi-task summary are stable.
