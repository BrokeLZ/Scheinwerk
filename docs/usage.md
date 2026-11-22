# Using Scheinwerk

The practical guide: how to install, run and use every part of Scheinwerk. The *why* and the exact rules live in [spec.md](spec.md). This file says *how*.

This guide grows with the code. A section that says *not yet available* describes something from a later phase (spec §16).

---

## Contents

1. [Install](#install)
2. [Development](#development)
3. [Concepts in five minutes](#concepts-in-five-minutes)
4. [CLI (`sw`)](#cli-sw)
5. [GUI](#gui)
6. [DCC integrations](#dcc-integrations)
7. [Sync (Synology Drive)](#sync-synology-drive)
8. [Troubleshooting](#troubleshooting)

---

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It fetches Python 3.11 by itself.

```bash
git clone https://github.com/BrokeLZ/Scheinwerk.git
cd Scheinwerk
uv sync                  # core + CLI + dev tools
uv sync --extra gui      # also installs PySide6 for the GUI
```

From inside the repo, run any command with `uv run`, for example `uv run sw --help`.

## Development

| Task | Command |
| --- | --- |
| Install / update the environment | `uv sync` (add `--extra gui` for PySide6) |
| Run all tests | `uv run pytest` |
| Run core tests, stop at first failure | `uv run pytest tests/core -x` |
| Run one test | `uv run pytest tests/core/test_stdlib_only.py::test_core_imports_only_stdlib` |
| Lint | `uv run ruff check .` |
| Lint and auto-fix | `uv run ruff check . --fix` |
| Format | `uv run ruff format .` |
| CLI | `uv run sw --help` |

A change is done when `uv run pytest` and `uv run ruff check .` both pass.

**CI.** Every push and pull request runs lint, format check and tests on macOS and Windows with Python 3.11 (`.github/workflows/ci.yml`). Results are on the repo's *Actions* tab on GitHub.

**Python version.** The repo pins 3.11 in `.python-version`, because Houdini 21 runs Python 3.11. Don't use newer syntax or stdlib APIs.

**Repo layout.**

```text
src/scheinwerk/core/   stdlib-only pipeline logic
src/scheinwerk/cli.py  the `sw` command
src/scheinwerk/gui/    PySide6 browser (Phase 3)
src/scheinwerk/dcc/    DCC adapters (Phase 4+)
integrations/          files DCCs load at startup (Phase 4+)
tests/                 pytest, real throwaway projects in tmp_path
docs/                  spec.md (contract) and usage.md (this guide)
```

## Concepts in five minutes

- A **project** is any folder with a `scheinwerk.json` in it. Tools find the project by walking up from wherever you are, like git finds `.git`.
- **Entities** are what you work on: **assets** (`assets/[category/]hero`), **shots** (`shots/sq010/sq010_0010`) and **sequences** (`shots/sq010/_seq`).
- Each entity has **departments** (`mdl`, `lgt`, …) and each department has **tasks** (default `main`). Scene files live in `<dept>/<task>/work/`.
- **Workfiles** are named `{entity}_{dept}_{task}_v###.{ext}`, for example `sq010_0010_lgt_main_v012.hip`. One version counter per task, shared by all DCCs.
  - The name must match its folders exactly. `hero_mdl_main_v003_final.hip`, `villain_mdl_main_v003.hip` inside `hero/mdl/main/work/`, or `….HIP` in uppercase are **unmanaged**: still listed, but they don't count as versions. Rename them to the template to bring them back in.
  - Keep `work/` flat. Files in subfolders of `work/` are not workfiles.
- **Products** are versioned exports at entity level: `publish/<product>/v###/`. USD layers go to `publish/_usd/<layer>/v###/` and have a small **pointer layer** that points at the current version.
- **Media** (renders, playblasts) go to `media/<name>/v###/`.
- **Names** are lowercase `a-z`, `0-9` and `_`, never starting with `_`. Reserved words can't be used as names: `publish`, `media`, `work`, `cache`, `assets`, `shots`, `shared`, `io`, `entity`. Sequences are letters then digits (`sq010`). Shots are `<sequence>_####` (`sq010_0010`).
- **Custom departments** (not in the project template) work, but under an asset *without* a category, tools only recognise them once you're inside a task's `work/` or `cache/` folder. Assets in a category don't have this limit.
- **The path is the context.** Any file's location tells Scheinwerk which project, entity, department, task, product and version it belongs to. Nothing else is stored.

Full layout: [spec §4](spec.md#4-on-disk-layout).

## CLI (`sw`)

*Not yet available. Arrives in Phase 2.* Today `sw` only supports `--help` and `--version`.

The planned command list is in [spec §11](spec.md#11-cli-sw). Each command will be documented here with examples as it lands.

## GUI

*Not yet available. Arrives in Phase 3.*

## DCC integrations

*Not yet available.* Houdini arrives in Phase 4, Nuke in Phase 5, Blender in Phase 6.

Until then, any DCC works by hand: create folders and names following the conventions above, and save or export through the DCC's own dialog.

## Sync (Synology Drive)

- Exclude `cache/` folders from sync with a Synology Drive file filter. Caches are large and never referenced downstream.
- Scheinwerk writes pointer layers and `version.json` last and atomically, so the other machine never sees a pointer to a version that hasn't synced yet.
- Synology conflict copies (`…_Conflict…`) are not hidden. `sw doctor` (Phase 2) will report them.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `uv: command not found` | Install uv (link above), then open a new terminal. |
| Tests use the wrong Python | Run through `uv run`, which uses the repo's 3.11 environment. `uv sync` recreates it. |
