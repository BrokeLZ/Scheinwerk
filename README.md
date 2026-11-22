# Scheinwerk

A lightweight, file-based VFX pipeline for one artist on macOS and Windows.

- **On-disk conventions** for folders, names and versions. The folder tree is the truth: no database, no server.
- A **stdlib-only Python core** that knows those conventions and runs inside hython, Nuke, Blender and plain Python 3.11.
- A **CLI** (`sw`) and a **PySide6 GUI** built on the core.
- Thin, optional **DCC integrations**: Houdini 21 first, then Nuke, then Blender.

Any DCC works without a plugin: Scheinwerk hands out the next path and you save or export through the DCC's own dialog.

> **Status:** Phase 1 (Core) is done: the core works from Python, see [the Python API guide](docs/usage.md#python-api). Phase 2 (the `sw` CLI) is next; `sw` has no subcommands yet. Roadmap: [docs/spec.md §16](docs/spec.md#16-roadmap).

## Documentation

| File | What's in it |
| --- | --- |
| [docs/usage.md](docs/usage.md) | **How to use Scheinwerk**: setup, CLI, GUI, DCC integrations, everyday workflows. Start here. |
| [docs/spec.md](docs/spec.md) | The specification: the contract the code follows. |
| [CLAUDE.md](CLAUDE.md) | Rules for working on the code (also read by Claude Code). |

## Quick start (development)

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.11 by itself if needed.

```bash
git clone https://github.com/BrokeLZ/Scheinwerk.git
cd Scheinwerk
uv sync
uv run pytest
uv run sw --help
```

More detail, including the GUI extra and lint commands, is in [docs/usage.md](docs/usage.md#development).
