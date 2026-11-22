# Using Scheinwerk

The practical guide: how to install, run and use every part of Scheinwerk. The *why* and the exact rules live in [spec.md](spec.md). This file says *how*.

This guide grows with the code. A section that says *not yet available* describes something from a later phase (spec §16).

---

## Contents

1. [Install](#install)
2. [Development](#development)
3. [Concepts in five minutes](#concepts-in-five-minutes)
4. [Python API](#python-api)
5. [Workfile templates](#workfile-templates)
6. [Hooks](#hooks)
7. [CLI (`sw`)](#cli-sw)
8. [GUI](#gui)
9. [DCC integrations](#dcc-integrations)
10. [Sync (Synology Drive)](#sync-synology-drive)
11. [Troubleshooting](#troubleshooting)

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

- **Assets vs. categories.** Every asset Scheinwerk creates gets an `entity.json`. A folder under `assets/` without `entity.json`, `publish/`, `media/` or a department is treated as a category. If you make asset folders by hand, add an `entity.json` containing `{"schema": 1}` (or a department folder) so they aren't mistaken for categories.
- **Version folders** count up from the highest existing `v###`, even an empty one, so a number is never reused. Empty versions are skipped when looking for "latest".
- **USD.** Publishing a layer updates its pointer (`publish/_usd/<layer>/<layer>.usd`) and the entity's entry/root layer (`publish/_usd/<entity>.usd`), which lists every layer strongest first: `usd_layer_order` from `scheinwerk.json`, then the rest A–Z.

Full layout: [spec §4](spec.md#4-on-disk-layout).

## Python API

Until the CLI lands (Phase 2), the core is usable from any Python 3.11, including hython. It has no dependencies. Inside the repo use `uv run python`; elsewhere add `src/` to `PYTHONPATH`.

```python
from scheinwerk.core.project import Project
from scheinwerk.core.publish import finalize, ingest, next_publish, next_usd, set_current
from scheinwerk.core.context import Context

proj = Project.create("/path/to/myshow", "myshow")     # or Project.find(any_path_inside)

hero = proj.create_asset("hero", category="char")       # writes assets/char/hero/entity.json
shot = proj.create_shot("sq010_0010", frames=(1001, 1096))  # creates sq010 too
mdl = hero.create_department("mdl")                     # mdl/main/work + cache
task = mdl.task("main")

task.next_workfile("hip")        # …/work/hero_mdl_main_v001.hip  (path only, nothing created)
task.new_empty_workfile("hip")   # copies shared/templates/empty.hip there
task.new_version_from(task.latest_workfile())          # copy as next version

vdir = next_publish(hero, "pants_drape_base")           # creates publish/pants_drape_base/v001/
finalize(vdir, source=task.latest_workfile().path, comment="first drape")

vdir = next_usd(hero, "asset")   # publish/_usd/asset/v001/ — export the USD here, then:
finalize(vdir)                   # writes version.json, the pointer and hero.usd
set_current(vdir)                # roll the pointer back to this version later

ingest(["/Users/me/Downloads/scan.obj"], hero.create_product("scan"))  # copies, never moves

proj.entity("sq010_0010")        # look up by name; "asset:", "shot:", "seq:" if ambiguous
Context.from_path(vdir)          # what any path means: entity, dept, task, product, version…
```

All functions raise `scheinwerk.core.errors.ScheinwerkError` (or a subclass) with a message you can show as-is. Nothing in the core deletes, moves or overwrites your files. The full list of functions is in [spec §10](spec.md#10-core-api-scheinwerkcore).

## Workfile templates

"New empty workfile" copies `shared/templates/empty.<ext>` from the project. Scheinwerk can't make a valid empty `.hip` or `.blend` on its own, so save one from each DCC once:

| DCC | Save an empty scene as |
| --- | --- |
| Houdini | `shared/templates/empty.hip` (or `empty.hipnc`) |
| Nuke | `shared/templates/empty.nk` |
| Blender | `shared/templates/empty.blend` |

Without a template for an extension you get an error telling you which file to create.

## Hooks

Hooks are optional Python files that run after pipeline actions. Put them in `shared/hooks/` (per project) or in `hooks/` inside your user settings folder (`~/Library/Application Support/Scheinwerk/` on macOS, `%APPDATA%\Scheinwerk\` on Windows). Project hooks run first. Files starting with `_` are ignored.

Define any of these functions:

```python
# shared/hooks/notify.py
def post_create(kind, path, context):    # kind: asset, shot, sequence, dept, task, product
    ...

def post_publish(version_dir, context):  # after finalize
    ...

def post_save(path, context):            # after "Save next version" in a DCC (Phase 4+)
    ...
```

`path` and `version_dir` are `pathlib.Path`s; `context` is a `Context` (`context.entity`, `context.dept`, …). A hook that crashes is logged and skipped: it never blocks the action.

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
