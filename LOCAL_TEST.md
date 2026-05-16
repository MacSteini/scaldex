# Local Token Test

1. Create any disposable folder.
2. Copy this tool into that folder.
3. Create `subject/` and place your `AGENTS.md` plus optional support files there.
4. Run:

```sh
mkdir -p subject
# Put AGENTS.md and optional support files in subject/ now.
python3 run_tokenmessung.py --model gpt-5.4
```

The script asks for `CODEX_API_KEY` when unset. It writes results to `tokenmessung-run/`; delete the whole folder when done.
