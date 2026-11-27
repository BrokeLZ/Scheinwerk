# CLAUDE.md — Scheinwerk

Scheinwerk is a lightweight, file-based VFX pipeline for one artist (macOS + Windows): a stdlib-only Python core, a `sw` CLI, a PySide6 GUI, and thin optional DCC integrations (Houdini 21 first, then Nuke, then Blender).

**`docs/spec.md` is the single source of truth.** Read it at the start of every session. If code and spec disagree, the spec wins. If the spec looks wrong or incomplete, stop and ask. Don't silently deviate. When a decision changes, update the spec in the same commit as the code.

## Current phase

> Phase 5 — Asset library, step L3: library GUI (see spec §17.12). The standalone window is in; the Houdini panel is still open. L2's code is done; its done-test (real downloads, checked in Karma) runs through the GUI. L1 is done; L0 is done on macOS, its Windows run is still open (`spike/l0/`). Phases 1 (Core), 2 (CLI) and 3 (GUI) are done; Phase 4 (Houdini) is parked (spec §16). Update this line when a step or phase is done.

Work on one phase at a time. Don't build ahead (no GUI code during the core phase, no Houdini code during the GUI phase).

## Commands

```bash
uv sync                      # core + dev tools
uv sync --extra gui          # + PySide6
uv run pytest                # all tests
uv run pytest tests/core -x  # core only, stop at first failure
uv run ruff check . && uv run ruff format .
uv run sw --help             # CLI
uv run scheinwerk-gui        # GUI
```

## Layout

```text
src/scheinwerk/core/   stdlib only: templates, project, context, entities, versions, publish, env, hooks, usd_pointer, fileio, doctor, settings, system, install, errors, version_dirs, tools, textures (texture processor)
src/scheinwerk/library/   asset library (spec §17), stdlib only, never imports project/context/entities
src/scheinwerk/cli.py  argparse `sw` command (cli_lib.py: `sw lib`)
src/scheinwerk/gui/    PySide6 widgets, actions, theme.qss (gui/library/: the library browser)
src/scheinwerk/dcc/    adapters (houdini, nuke, blender)
src/scheinwerk/resources/templates/   default empty workfiles copied into new projects
integrations/          files the DCCs load at startup (Houdini package, Nuke init/menu, Blender extension)
tests/                 pytest, real projects in tmp_path
docs/spec.md           the contract
spike/l0/              throwaway L0 spike scripts and findings (not part of the package)
```

Dependency direction: `core` ← `cli` ← `gui` ← `dcc`. Never the other way round.

## Non-negotiable rules

1. **`core/` and `library/` import only the Python standard library.** No Qt, no `hou`/`nuke`/`bpy`, no `pxr`, no third-party packages. A test enforces this.
2. **Never persist an absolute path inside a project.** Stored paths (JSON, generated USD, anything written to disk) are root-relative POSIX strings with `/`, or file-relative (USD), or env-relative (`$SW_ROOT/...`). Absolute paths are allowed only at runtime and in machine-local user settings. Published files reference only other published files (never `work/` or `cache/`), and every USD layer core writes carries the entity's fps (spec §9.2).
3. **The folder tree is the truth.** Don't cache tree state, don't add registries or indexes, don't add JSON fields the spec doesn't define. Rescan instead.
4. **Context comes from the path.** Use `Context.from_path()`. Never pass state around that the path could provide, and never trust filename prefixes for context (folders only).
5. **Python 3.11.** No syntax or stdlib APIs newer than 3.11.
6. **Cross-platform by default.** Use `pathlib`. No `os.path` string juggling, no hard-coded separators, no shell calls for file operations. Reveal and open-file go through one helper per OS.
7. **Atomic writes** for every JSON and pointer/root USD layer: write `*.tmp` in the same folder, then `os.replace`. Pointer layers are always written last.
8. **Never delete or move user files.** Ingest copies. `doctor` reports and only renames with an explicit `--fix` flag. No cleanup features unless the spec asks for them.
9. **Names follow spec §5:** lowercase `a-z0-9_`, no leading `_` (reserved), 3-digit versions, readers accept `v\d{3,}`.
10. **Unknown things are shown, not hidden or rejected.** Unmanaged files, custom departments and unparsable folders appear in listings, flagged.

## Code style

- Small modules, plain functions and frozen dataclasses. No class hierarchies, metaclasses, plugin frameworks or event buses.
- Type hints everywhere (`from __future__ import annotations`). Docstrings only where the *why* isn't obvious.
- Core raises `ScheinwerkError` subclasses with user-readable messages. It never prints, logs to stdout, or calls `sys.exit`. The CLI and GUI turn errors into output.
- The GUI holds no logic: every menu action is one core call. All actions live in right-click menus built from `gui/actions.py`. No button rows (exception: the library browser's Ingest view, spec §17.11).
- No hard-coded colours or fonts in widget code. Everything goes in `gui/theme.qss`.
- Prefer fewer lines over clever abstractions. If something needs a new concept, ask first.

## Testing

- Write or update the tests **before** the implementation for anything in `core/`. Show me the test cases for new template/parsing rules before implementing them.
- Tests build real throwaway projects in `tmp_path`. Don't mock the filesystem.
- Required coverage for core: format ⇄ parse round-trips, optional asset category, `_seq` parsing, version counting (shared across extensions, gaps, v1000+, empty version folders), atomic writes, pointer/root layer text, ignore patterns, unmanaged files.
- Use Windows-style edge cases where relevant (case-insensitive collisions, path separators). CI runs on macOS and Windows.
- A task is done when `uv run pytest` and `uv run ruff check .` both pass.

## Ask before you…

- add any dependency (core: never; GUI/dev: ask),
- add or rename a JSON field, template, reserved name or env var,
- change the on-disk layout or naming rules,
- write anything that deletes, moves or overwrites existing files,
- start work belonging to a later phase.

## DCC work (later phases)

- Don't guess DCC APIs. Target Houdini 21 (Python 3.11, PySide6), current Nuke, current Blender. If unsure about an API, say so and ask me for docs or a test in the DCC.
- DCC code lives in `dcc/` (adapter + helpers) and `integrations/` (startup files). It calls the core. It never reimplements path logic.
- Integrations derive context from the open file on every load/save-as and set the env vars from spec §7.2.
- Houdini USD output always uses the *Use Relative Paths* output processor.

## Documentation

`docs/usage.md` is the user guide: how to install, run and use everything (CLI commands with examples, GUI, DCC integrations, workflows, dev commands). `README.md` is the short entry point.

- Every change the user can notice (a new or changed CLI command, flag, GUI action, integration step, env var, dev command, setup step) updates `docs/usage.md` **in the same commit**.
- Write for the user, not the code: what to type, what happens, an example. Link to `docs/spec.md` for rules instead of repeating them.
- When a phase lands, replace its *Not yet available* note with real instructions and update the status line in `README.md`.

## Commits

Small, one concern each, imperative subject (`core: parse optional asset category`). Spec changes go in the same commit as the code that needs them.
