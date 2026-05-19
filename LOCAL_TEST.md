# Local scaldex Test

Use this file to run scaldex against a real local `AGENTS.md` package and hand the result to Codex.

## Enduser Flow

1. Open a terminal in this project folder.
2. Create `subject/`.
3. Put the instruction package you want to measure into `subject/`.
   This folder needs `AGENTS.md`. If your setup depends on `.codex/` or other support files, put them in `subject/` too.

## Run A Smoke Test

```sh
mkdir -p subject
scaldex --model gpt-5.4
```

If the tool asks for a key, enter your Codex API key at the hidden prompt.
scaldex does not write that key into reports, history, or config files.
That is why you may need to enter it again in a new terminal run unless you set `CODEX_API_KEY` yourself.

## Give The Result To Codex

The main follow-up file is:

```text
scaldex-run/CODEX_HANDOFF.md
```

Give that file to Codex when you want help interpreting the measurement, deciding whether another paid run is useful, or optimizing the measured `AGENTS.md`/`.codex` package.

## Read The Terminal Output

- `What this means`: explains the result in plain language.
- `What to do now`: tells you whether to hand the result to Codex, stop, run `--repeats 3`, keep the report, or avoid an efficiency claim.
- `Codex handoff`: shows the file to send to Codex and summarizes its purpose and safety boundary.
- `What was compared`: explains `agents` and `control` directly in the terminal.
- `Evidence`: explains the primary token metric, quality gate, and reliability in sentences.
- `Audit checks`: explains isolation, path integrity, tool sanity, and warnings in sentences.

In scaldex output, `agents` means the run with your measured `AGENTS.md`/`.codex` package installed. `control` means the same task run without that package and without your global `~/.codex` config.

## Use The Report Files

- `scaldex-run/RESULT.md`: main human-readable report.
- `scaldex-run/CODEX_HANDOFF.md`: Codex-first instruction file for the next analysis or optimization step.
- `scaldex-run/result.json`: machine-readable report.

## Replay A Result Without Spending Money

```sh
scaldex --print-result scaldex-run/result.json
```

Replay needs an existing `result.json`. If that path does not exist yet, run a smoke test first or point `--print-result` at another scaldex report.

## Compare Current And Older Runs

When you run the tool again, scaldex archives the previous compact report in `scaldex-history/`.
Only run this command after `scaldex-history/` exists.

```sh
scaldex bench summarize scaldex-history scaldex-run --out scaldex-summary
```

The command prints the combined decision view in the terminal. It also writes `scaldex-summary/SCALDEX_SUMMARY.md` and `scaldex-summary/scaldex-summary.json` for later review or automation.

## Notes

- Default mode measures the whole `subject/` package.
- Use `--subject-mode agents-md` only for a diagnostic AGENTS-only run.
- The default run is a low-cost smoke run with one task pair.
- Use `--all-tasks` only when you intentionally want the full task set.
- Raw audit data lives under `scaldex-run/raw/`.
- In a source checkout without an installed console script, use `python3 run_scaldex.py` for the same top-level run/replay commands and `PYTHONPATH=src python3 -m scaldex` for utility commands.
