"""Atomic writes and copies that never overwrite (CLAUDE.md rules 7 and 8)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from scheinwerk.core.errors import AlreadyExists


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 with LF endings via `<name>.tmp` + os.replace. Skips identical content."""
    data = text.encode("utf-8")
    try:
        if path.read_bytes() == data:
            return  # no rewrite, no sync churn
    except OSError:
        pass
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)  # os.replace: atomic on the same volume


def write_json(path: Path, data: dict) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict | None:
    """The JSON object in `path`, or None if it is missing or not a valid object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def copy_new(src: Path, dest: Path) -> None:
    """Copy `src` to `dest`, which must not exist yet. Never overwrites."""
    try:
        out = dest.open("xb")
    except FileExistsError as exc:
        raise AlreadyExists(f"{dest} already exists.") from exc
    with out, src.open("rb") as inp:
        shutil.copyfileobj(inp, out)
    shutil.copystat(src, dest)


def exists_ci(folder: Path, name: str) -> bool:
    """Case-insensitive, so `hero` and `Hero` can't both exist (Windows/macOS file systems)."""
    try:
        return any(e.name.lower() == name.lower() for e in folder.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return False


def check_free(path: Path) -> None:
    """Raise AlreadyExists if `path` (in any letter case) is taken."""
    if exists_ci(path.parent, path.name):
        raise AlreadyExists(f"{path} already exists.")
