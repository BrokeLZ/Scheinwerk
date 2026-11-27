"""Machine-local user settings (spec §8.4). Never stored inside a project."""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

from scheinwerk.core.fileio import read_json, write_json

DEFAULT_SETTINGS: dict = {
    "schema": 1,
    "recent_projects": [],
    "dcc": {},
    "gui": {"last_view": "scenefiles", "geometry": None},
    "library": None,
    "tools": {},
}
MAX_RECENT = 10


def user_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Scheinwerk"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else Path.home() / "AppData" / "Roaming") / "Scheinwerk"
    return Path.home() / ".config" / "scheinwerk"


def settings_path() -> Path:
    return user_dir() / "settings.json"


def load_settings() -> dict:
    """settings.json merged over the defaults. Missing or broken file -> defaults."""
    data = copy.deepcopy(DEFAULT_SETTINGS)
    stored = read_json(settings_path()) or {}
    gui = {**data["gui"], **(stored.get("gui") or {})}
    data.update(stored)
    data["gui"] = gui
    return data


def save_settings(data: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, data)


def add_recent_project(root: Path) -> None:
    """Put `root` first in recent_projects (absolute paths are fine here: machine-local)."""
    data = load_settings()
    entry = str(root)
    data["recent_projects"] = [entry, *[p for p in data["recent_projects"] if p != entry]][
        :MAX_RECENT
    ]
    save_settings(data)


def set_library(root: Path) -> None:
    """Make `root` this machine's library (spec §17.2). Absolute: machine-local."""
    data = load_settings()
    data["library"] = str(root.absolute())
    save_settings(data)


def app_for(settings: dict, ext: str) -> str | None:
    """The configured application for an extension, or None for the OS default."""
    entry = (settings.get("dcc") or {}).get(ext) or {}
    return entry.get("exe") or None
