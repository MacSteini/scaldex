# Local Token Test

1. Create any disposable folder.
2. Copy this tool into that folder.
3. Create `subject/` and place your complete instruction package there: `AGENTS.md` plus every support file it needs.
4. Run:

```sh
mkdir -p subject
# Put AGENTS.md and optional support files in subject/ now.
python3 run_tokenmessung.py --model gpt-5.4
```

Default mode measures the whole `subject/` package. Use `--subject-mode agents-md` only as a diagnostic AGENTS-only run. The default is a low-cost smoke run with one task pair. Use `--all-tasks` only for the full run. Read `tokenmessung-run/RESULT.md` first; raw audit data is under `tokenmessung-run/raw/`.
