# scaldex v1.0.0 release checklist

Use this checklist before publishing v1.0.0.

## Release scope

- Product name is `scaldex`.
- Public CLI entry point is `scaldex`.
- Source-checkout wrapper is `python3 run_scaldex.py`.
- Public utility commands are:
  - `scaldex bench doctor`
  - `scaldex bench summarize`
  - `scaldex result show`
- Internal fixture and raw benchmark plumbing are not part of the public enduser flow.

## Required checks

Run from the product repository root:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m py_compile run_scaldex.py src/scaldex/*.py tests/*.py
python3 run_scaldex.py --help
PYTHONPATH=src python3 -m scaldex bench --help
PYTHONPATH=src python3 -m scaldex result --help
PYTHONPATH=src python3 -m scaldex bench doctor
git diff --check
```

Run from the control root:

```sh
.codex/bin/validate
```

## No-cost report checks

Use existing local reports only. Do not run paid Codex benchmarks for release validation unless explicitly approved.

```sh
python3 run_scaldex.py --print-result <path-to-existing-result.json>
PYTHONPATH=src python3 -m scaldex result show <path-to-existing-result.json>
PYTHONPATH=src python3 -m scaldex bench summarize <history-dir> <current-run-dir> --out <summary-dir>
```

Expected behaviour:

- Replay does not ask for an API key.
- Replay does not inspect or change `subject/`.
- Summary does not run Codex.
- Missing result paths fail with a clear recovery message.
- Handoff paths point to the report beside the replayed `result.json`.

## Paid run policy

For release readiness, paid runs are not the primary validation mechanism. Use them only to verify the live end-to-end path after local checks pass.

Recommended final release smoke limit:

```sh
scaldex --model gpt-5.4 --subject-dir subject --task-id login_test_failure --repeats 1
```

Do not run decision-grade repeats for release validation unless the release candidate itself changed measurement logic.

## Human-facing acceptance

- README explains what `agents` and `control` mean.
- README explains the cost model before decision-grade commands.
- README tells users to give `CODEX_HANDOFF.md` to Codex.
- Terminal output uses sentence-based explanations, not raw metric dumps.
- Quality failures name concrete blockers when data is available.
- `CODEX_HANDOFF.md` is a Codex-facing contract and does not leak raw absolute local paths.

## Machine-facing acceptance

- `result.json` remains machine-readable.
- `CODEX_HANDOFF.md` states requested action, forbidden actions, primary metric, quality gates, evidence grade, and output expected from Codex.
- Summary JSON distinguishes smoke from decision-grade evidence.
- Global efficiency claims require enough decision-grade task evidence.

## Release blockers

- MIT licence file is present before publishing.
- Do not publish with generated local `scaldex-run/`, `scaldex-history/`, or `subject/` folders in the repository.
- Do not publish with API keys or private local paths in tracked files.
- Do not claim global token efficiency from one task or smoke-only evidence.
