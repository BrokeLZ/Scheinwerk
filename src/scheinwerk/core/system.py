"""Open files and reveal them in Finder/Explorer: one helper per OS (CLAUDE.md rule 6)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scheinwerk.core.errors import NotFound, ScheinwerkError


def open_command(
    path: Path, app: str | None = None, *, platform: str = sys.platform
) -> list[str] | None:
    """The command that opens `path` (with `app`, else the OS default). None = os.startfile."""
    _check(path)
    if platform == "darwin":
        return ["open", "-a", app, str(path)] if app else ["open", str(path)]
    if platform == "win32":
        return [app, str(path)] if app else None
    return [app, str(path)] if app else ["xdg-open", str(path)]


def reveal_command(path: Path, *, platform: str = sys.platform) -> list[str]:
    """The command that shows `path` selected in the file browser."""
    _check(path)
    if platform == "darwin":
        return ["open", "-R", str(path)]
    if platform == "win32":
        return ["explorer", f"/select,{path}"]
    return ["xdg-open", str(path.parent)]


def open_path(path: Path, app: str | None = None) -> None:
    command = open_command(path, app)
    try:
        if command is None:
            os.startfile(path)  # type: ignore[attr-defined]  # Windows only
        else:
            subprocess.Popen(command)
    except OSError as exc:
        raise ScheinwerkError(f"Couldn't open {path}: {exc}") from exc


def reveal(path: Path) -> None:
    try:
        subprocess.Popen(reveal_command(path))
    except OSError as exc:
        raise ScheinwerkError(f"Couldn't reveal {path}: {exc}") from exc


def _check(path: Path) -> None:
    if not path.exists():
        raise NotFound(f"{path} does not exist.")
