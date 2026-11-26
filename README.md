# Scheinwerk

A lightweight, file-based VFX pipeline for one artist on macOS and Windows.

- **On-disk conventions** for folders, names and versions. The folder tree is the truth: no database, no server.
- A **stdlib-only Python core** that knows those conventions and runs inside hython, Nuke, Blender and plain Python 3.11.
- A **CLI** (`sw`) and a **PySide6 GUI** built on the core.
- Thin, optional **DCC integrations**: Houdini 21 first, then Nuke, then Blender.

Any DCC works without a plugin: Scheinwerk hands out the next path and you save or export through the DCC's own dialog.

> **Status:** Phases 1 (core), 2 (`sw` CLI) and 3 (GUI) are done: projects can be set up and used through `sw` or the browser (`sw gui`), see [the usage guide](docs/usage.md). Phase 4 (Houdini integration) is in progress: the package, menu, browser panel and HDAs work, see [Houdini](docs/usage.md#houdini). Roadmap: [docs/spec.md §16](docs/spec.md#16-roadmap).

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

Try it in a scratch folder:

```bash
mkdir /tmp/myshow && cd /tmp/myshow
uv run --project /path/to/Scheinwerk sw init
uv run --project /path/to/Scheinwerk sw new asset char/hero
uv run --project /path/to/Scheinwerk sw ls
```

Or install `sw` once with `uv tool install --editable /path/to/Scheinwerk` and just type `sw`. More detail, including the GUI extra and lint commands, is in [docs/usage.md](docs/usage.md#install).
