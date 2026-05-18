# Local Tokenmessung Test

Use this file for a local smoke test before spending money on larger runs.

## Prepare

1. Open a terminal in this project folder.
2. Create `subject/`.
3. Put the instruction package you want to measure into `subject/`.
   This folder needs `AGENTS.md`. If your setup depends on `.codex/` or other support files, put them in `subject/` too.

## Run A Smoke Test

```sh
mkdir -p subject
python3 run_tokenmessung.py --model gpt-5.4
```

If the tool asks for a key, enter your Codex API key at the hidden prompt.
Tokenmessung does not write that key into reports, history, or config files.
That is why you may need to enter it again in a new terminal run unless you set `CODEX_API_KEY` yourself.

## Read The Result

- Console: shows the verdict, quality gate, next action, and report paths.
- `tokenmessung-run/RESULT.md`: main human-readable report.
- `tokenmessung-run/CODEX_HANDOFF.md`: short follow-up brief for Codex.
- `tokenmessung-run/result.json`: machine-readable report.

## Replay A Result Without Spending Money

```sh
python3 run_tokenmessung.py --print-result tokenmessung-run/result.json
```

Replay needs an existing `result.json`. If that path does not exist yet, run a smoke test first or point `--print-result` at another Tokenmessung report.

## Compare Current And Older Runs

When you run the tool again, Tokenmessung archives the previous compact report in `tokenmessung-history/`.
Only run this command after `tokenmessung-history/` exists.

```sh
PYTHONPATH=src python3 -m tokenmessung bench summarize tokenmessung-history tokenmessung-run --out tokenmessung-summary
```

Read `tokenmessung-summary/TOKENMESSUNG_SUMMARY.md` for the combined view.

## Notes

- Default mode measures the whole `subject/` package.
- Use `--subject-mode agents-md` only for a diagnostic AGENTS-only run.
- The default run is a low-cost smoke run with one task pair.
- Use `--all-tasks` only when you intentionally want the full task set.
- Raw audit data lives under `tokenmessung-run/raw/`.
