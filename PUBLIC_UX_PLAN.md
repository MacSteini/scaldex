# Tokenmessung Public UX Plan

## Current State

- Tokenmessung has a working measurement core: paired agents/control runs, batch IDs, subject fingerprints, run configuration fingerprints, quality gates, normalized repo-relative `relevant_files`, and paired median non-cached input deltas.
- The current user experience is still too operationally manual: users must infer whether to stop, proceed to decision-grade runs, or reject a global claim from multiple report fields.
- End-user documentation is intentionally deferred until the operational UX is stable.
- No paid Codex benchmark runs are allowed during this implementation sequence unless explicitly approved later.

## Target State

- Console output tells the user the next safe action without requiring manual report interpretation.
- `RESULT.md` starts with a compact decision summary before detailed metrics.
- Existing result files from multiple runs can be summarized locally without new API calls.
- A future smart runner is specified but not implemented.
- Public README/end-user documentation remains last.

## Sequential Checklist

| Step | Status | Goal | Success Measurement | Audit |
| --- | --- | --- | --- | --- |
| 0 | done | Create this root plan. | `PUBLIC_UX_PLAN.md` exists and lists all steps. | No secrets, no private benchmark artefacts, no measurement logic changes. |
| 1 | done | Add console `Next action`. | Console says whether to stop, run decision-grade, record win, or reject efficiency. | Tests cover all action categories; decisions do not use unpaired medians. |
| 2 | done | Add `RESULT.md` Decision Summary. | First report lines show decision, next action, quality gate, warnings, and claim status. | Benchmark and subject warnings remain separated; integrity failures stay not effective. |
| 3 | done | Add local multi-task summary. | Existing `result.json` files can produce `TOKENMESSUNG_SUMMARY.md` and `tokenmessung-summary.json` without API calls. | Mixed fingerprints and mixed smoke/decision-grade inputs are explicit. |
| 4 | done | Specify future smart runner only. | Root plan contains `tokenmessung evaluate --subject-dir ... --model ... --budget-runs ...` behavior and stop rules. | No auto-run implementation or paid-run trigger added. |
| 5 | in_progress | Defer end-user documentation. | README is not created until operational UX is stable. | Later README examples must match final CLI behavior. |

## Verification After Each Step

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py`
- For report/analyzer changes:
  - `PYTHONPATH=src python3 -m tokenmessung bench synthesize --out /private/tmp/tokenmessung-synth-clean --repeats 2 --seed 1`
  - `PYTHONPATH=src python3 -m tokenmessung bench analyze --results /private/tmp/tokenmessung-synth-clean`

## Audit Notes

### Step 0

- Status: done
- Measurement:
  - Root plan file created.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
- Audit:
  - Measurement code was not modified.
  - No README was added.
  - No API keys, local secrets, or raw benchmark artefacts were added.

### Step 1

- Status: done
- Measurement:
  - `result.json` now includes an additive `decision` object.
  - Console output now includes `Next action`.
  - `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
  - `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
  - `PYTHONPATH=src python3 -m tokenmessung bench synthesize --out /private/tmp/tokenmessung-synth-clean --repeats 2 --seed 1` passed.
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
  - `PYTHONPATH=src python3 -m tokenmessung bench synthesize --out /private/tmp/tokenmessung-synth-clean --repeats 2 --seed 1` passed.
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
  - `PYTHONPATH=src python3 -m tokenmessung bench synthesize --out /private/tmp/tokenmessung-synth-clean --repeats 2 --seed 1` passed.
  - `PYTHONPATH=src python3 -m tokenmessung bench analyze --results /private/tmp/tokenmessung-synth-clean` passed.
  - `PYTHONPATH=src python3 -m tokenmessung bench summarize /private/tmp/tokenmessung-synth-clean --out /private/tmp/tokenmessung-multi-summary` passed.
- Audit:
  - Summarize mode makes no Codex or API call.
  - Tests cover folder/file discovery, global claim threshold, mixed subject fingerprints, and mixed smoke/decision-grade inputs.
  - Global efficiency claim requires at least 3 effective decision-grade tasks across the expected task set.

### Step 4

- Status: in_progress
- Measurement:
  - Pending.
- Audit:
  - Pending.

## Future Smart Runner Specification

- Status: done.
- Intended future command shape: `tokenmessung evaluate --subject-dir ... --model ... --budget-runs ...`.
- This is specification-only. No implementation exists in this step.

### Intended Command

```sh
tokenmessung evaluate --subject-dir ./Agent --model gpt-5.4 --budget-runs 12
```

### Required Behavior

- Resolve and audit the subject once before any paid run.
- Display the maximum possible paid run count before starting.
- Run every configured task first with `repeats=1`.
- Stop a task after smoke when:
  - agents/control quality is not 1.0/1.0,
  - benchmark warnings are present,
  - normalized repo-relative `relevant_files` is false,
  - integrity status is failed.
- Run `repeats=3` only for smoke-passing tasks and only while `--budget-runs` still allows it.
- Never claim global token efficiency unless the multi-task summary rule allows it.
- Persist every per-task `result.json` in a non-overwriting run folder so `bench summarize` can evaluate all tasks afterward.

### Required Stop Rules

- Stop before starting if planned smoke runs exceed `--budget-runs`.
- Stop before decision-grade runs if no task passed smoke.
- Stop on mixed `subject_fingerprint` or mixed `run_config_fingerprint`.
- Stop on missing authoritative usage data, invalid final JSON, nonzero exit code, missing expected files, or missing expected relevant files.
- Stop when the user did not explicitly approve the displayed paid-run plan.

### Non-Goals

- Do not implement automatic AGENTS.md optimization.
- Do not integrate CodeBurn or any external cost dashboard.
- Do not hide raw path violations; normalized quality and raw path reporting must both remain visible.
- Do not replace `run_tokenmessung.py` until the evaluate command is proven by local tests and explicit approval.

### Step 4 Audit

- `PYTHONPATH=src python3 -m unittest discover -s tests` passed.
- `python3 -m py_compile run_tokenmessung.py src/tokenmessung/*.py tests/*.py` passed.
- No `evaluate` command was implemented.
- No paid-run automation was added.
- The specification requires explicit approval before any future paid-run plan.

## Documentation Policy

- Do not create public end-user documentation yet.
- Keep `LOCAL_TEST.md` as the current local reference.
- Write a public README only after console decisions, report summary, and multi-task summary are stable.
