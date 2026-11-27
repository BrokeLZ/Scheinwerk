"""v### folders in any folder (spec §5.4): counting and creating versions.

Project-free, so the library (spec §17.9) shares it with products.
"""

from __future__ import annotations

from pathlib import Path

from scheinwerk.core.templates import format_version, parse_version


def version_dirs(folder: Path) -> list[Path]:
    """The v### folders in `folder`, newest first, empty ones included. Missing folder -> []."""
    try:
        entries = [e for e in folder.iterdir() if e.is_dir()]
    except (FileNotFoundError, NotADirectoryError):
        return []
    found = [(n, e) for e in entries if (n := parse_version(e.name)) is not None]
    return [e for _, e in sorted(found, key=lambda t: -t[0])]


def highest_version(folder: Path) -> int | None:
    """The highest v### number in `folder`, empty folders included."""
    dirs = version_dirs(folder)
    return parse_version(dirs[0].name) if dirs else None


def next_version_dir(folder: Path) -> Path:
    """Create and return `folder`/v### with the highest number + 1 (v001 when there is none).
    Never reuses an existing folder: if the name is taken meanwhile, the next one is tried."""
    number = (highest_version(folder) or 0) + 1
    while True:
        path = folder / format_version(number)
        try:
            path.mkdir(parents=True)
            return path
        except FileExistsError:
            number += 1
