<!-- markdownlint-disable MD033 MD041 -->

<div align="center">

![scaldex](https://github.com/macsteini/scaldex/blob/main/img/banner.png?raw=true)

![GitHub Release](https://img.shields.io/github/v/release/macsteini/scaldex?label=Release&color=blue)
[![Python: >=3.11](https://img.shields.io/badge/Python-%3E%3D3.11-blue)](#requirements)
[![CLI: scaldex](https://img.shields.io/badge/CLI-scaldex-blue)](#install-from-github-source)
[![Licence: AGPL-3.0-only](https://img.shields.io/badge/Licence-AGPL_3.0_only-blue)](LICENCE "Project licence")

</div>

# scaldex

scaldex measures whether a Codex instruction package saves or costs tokens without visibly degrading task quality.

Use it when you optimise `AGENTS.md`, `AGENTS.override.md` or support files and folders referenced by those instructions. scaldex gives you a task-level result that you can inspect yourself or hand to Codex for evidence-based follow-up.

scaldex runs each benchmark task in two isolated variants:

- `agents`: Codex runs with the instruction package you are measuring.
- `control`: Codex runs without that package and without your global `~/.codex` config.

scaldex does not edit your instructions. It measures, reports and writes evidence.

## Requirements

- Python 3.11 or newer.
- Git on `PATH`. scaldex uses Git internally for temporary benchmark snapshots; your measured package does not need to be a Git repository.
- Codex CLI on `PATH` with `codex exec` support.
- A Codex API key for paid benchmark runs.

`scaldex bench doctor`, `scaldex bench inspect-subject`, result replay and report summaries do not spend API money. Benchmark commands spend API money.

## Install from GitHub source

Download or clone the scaldex project from GitHub, then open a terminal in the downloaded `scaldex` folder. This is the folder that contains `README.md`, `pyproject.toml` and `run_scaldex.py`.

Install the `scaldex` command:

```sh
python3 -m pip install -e .
```

Check your local setup without spending API money:

```sh
scaldex bench doctor
```

If you do not want to install the command yet, stay in the downloaded `scaldex` folder and use the wrapper instead:

```sh
python3 run_scaldex.py --help
```

The examples below use the installed `scaldex` command. With the wrapper, replace `scaldex` with `python3 run_scaldex.py`.

## Update from GitHub source

For a Git checkout, run `git pull` in the scaldex source folder. For a downloaded archive, replace the old source folder with the new one.

If you installed the `scaldex` command, run this again in the updated folder:

```sh
python3 -m pip install -e .
```

Editable installs read code from the source folder, but reinstalling keeps command entry points, package metadata and dependencies aligned. If the source folder moved to a new path, reinstall from the new folder.

If you only use the wrapper, update or replace the source folder and run this no-cost check from the updated folder:

```sh
python3 run_scaldex.py --help
```

## First measurement

Create a `subject/` folder for the instruction package you want to measure:

```text
subject/
  AGENTS.md
  xyz/
```

`subject/` is the package under test. Keep it separate from the scaldex project folder. It must contain `AGENTS.md` or `AGENTS.override.md`.

Support files and folders are optional. You can use names such as `.codex/`, `xyz/` or anything else your instruction entry file references.

Inspect the package before spending API money:

```sh
scaldex bench inspect-subject --subject-dir subject
```

By default, scaldex measures the whole `subject/` package. Use `--subject-mode agents-md` only when you intentionally want to measure the entry file without its support material.

Run one smoke benchmark first:

```sh
scaldex --model gpt-5.5 --subject-dir subject --task-id login_test_failure --repeats 1
```

This starts two paid Codex runs: one `control` run and one `agents` run.

After the run, read `What this means` and `What to do now` in the terminal output. `scaldex-run/RESULT.md` contains the same human-readable interpretation and next-step guidance.

The run folder contains:

- `scaldex-run/RESULT.md`: human-readable report.
- `scaldex-run/CODEX_HANDOFF.md`: Codex-facing follow-up brief.
- `scaldex-run/result.json`: machine-readable report.

## What to do with the result

You have three safe paths:

- read `RESULT.md` and improve the instruction package manually
- give `CODEX_HANDOFF.md` and the measured contents of `subject/` to Codex with a clear optimisation request
- stop changing the package and collect stronger decision-grade evidence when scaldex tells you to

`CODEX_HANDOFF.md` is a brief, not a self-contained request. If you want Codex-assisted follow-up, give Codex the handoff, the measured contents of `subject/` and an explicit task. The [Codex instruction workflow guide](docs/CODEX-INSTRUCTION-WORKFLOW.md) includes a copy-paste prompt.

Do not improve the measured package from a smoke win alone. Smoke evidence only tells you whether a decision-grade run is worth the cost.

## Learn more

- [Codex instruction workflow](docs/CODEX-INSTRUCTION-WORKFLOW.md): how scaldex, Codex and the end user work together.
- [Measurement model](docs/MEASUREMENT-MODEL.md): metrics, quality gates, smoke evidence, decision-grade evidence and global claims.
- [Built-in task guide](docs/BUILT-IN-TASKS.md): task selection and the eight v1.0 benchmark workflows.
- [Contributing guide](CONTRIBUTING.md "Contributing guide"): development checks and contribution boundaries.

## Licence

This project uses [AGPL-3.0-only](LICENCE "Project licence"). You may use, change and distribute it under the licence terms.

The project name, branding and public presentation are not granted as trade marks or endorsements by the software licence. See the [project notice](NOTICE "Project notice") for trade mark, service, API-key and benchmark-evidence boundaries.
