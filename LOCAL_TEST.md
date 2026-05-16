# Local Token Test

Run this outside the project directory.

```sh
export TOOL_DIR="/Users/steini/Documents/Coding/Tokenmessung/Tokenmessung"
export TEST_DIR="$HOME/tokenmessung-real-test"
export MODEL="gpt-5.4"
export AGENTS_FILE="/path/to/your/AGENTS.md"
mkdir -p "$TEST_DIR"
cd "$TOOL_DIR"
read -rsp 'CODEX_API_KEY: ' CODEX_API_KEY; echo; export CODEX_API_KEY
PYTHONPATH=src python3 -m tokenmessung fixture create --out "$TEST_DIR/fixture" --force
PYTHONPATH=src python3 -m tokenmessung bench doctor --require-api-key
PYTHONPATH=src python3 -m tokenmessung bench run --fixture "$TEST_DIR/fixture" --agents-file "$AGENTS_FILE" --model "$MODEL" --repeats 1 --out "$TEST_DIR/results" --seed 1
ls "$TEST_DIR/results"/summary.json "$TEST_DIR/results"/summary.csv "$TEST_DIR/results"/paired-deltas.csv
unset CODEX_API_KEY
```

Do not paste the API key into chat or write it to a file.
