# Contributing

Contributions are welcome when they keep scaldex focused, measurable and safe to run.

## Useful contributions

- Bug reports with the exact command, expected result and observed result.
- Small fixes that preserve the public CLI contract.
- Documentation improvements that make setup, measurement or result interpretation clearer.
- Tests for benchmark analysis, summaries, CLI behaviour and report generation.

## Before changing behaviour

Open an issue or discussion first when a change would alter:

- the public `scaldex` command
- generated report names or locations
- task scoring or quality gates
- the paid benchmark cost model
- the global efficiency-claim threshold

Do not run paid Codex benchmarks for routine development or pull requests unless a maintainer explicitly approves that cost.

## Local checks

Install the development extras in a local virtual environment:

```sh
python3 -m venv ../.venv
source ../.venv/bin/activate
python -m pip install -e '.[dev]'
```

Run no-cost checks before submitting a change:

```sh
python -m pytest -p no:cacheprovider
python -m compileall run_scaldex.py src tests
python run_scaldex.py --help
python -c 'import sys; from scaldex.cli import main; raise SystemExit(main(sys.argv[1:]))' bench doctor
git diff --check
```

Use result replay and existing report summaries for documentation or output checks whenever possible. They do not spend API money.

## Pull requests

Keep pull requests focused on one change. Include:

- what changed
- why it changed
- which no-cost checks passed
- whether a maintainer approved any paid benchmark

Do not include API keys, private repository paths, generated benchmark history or local `subject/` packages.

## Security

Please report security issues privately instead of publishing exploit details in an issue.
