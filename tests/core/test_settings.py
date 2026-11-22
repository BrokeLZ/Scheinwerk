"""Machine-local user settings (spec §8.4)."""

from __future__ import annotations

import json
from pathlib import Path

from scheinwerk.core.settings import (
    DEFAULT_SETTINGS,
    add_recent_project,
    app_for,
    load_settings,
    save_settings,
    settings_path,
)


def test_path(user_dir: Path) -> None:
    assert settings_path() == user_dir / "settings.json"


def test_defaults_when_missing_or_broken(user_dir: Path) -> None:
    assert load_settings() == DEFAULT_SETTINGS
    (user_dir / "settings.json").write_text("{broken", encoding="utf-8")
    assert load_settings() == DEFAULT_SETTINGS


def test_defaults_fill_missing_keys_and_unknown_keys_survive(user_dir: Path) -> None:
    (user_dir / "settings.json").write_text('{"schema": 1, "mine": 1}', encoding="utf-8")
    data = load_settings()
    assert data["recent_projects"] == []
    assert data["gui"] == {"last_view": "scenefiles", "geometry": None}
    save_settings(data)
    assert json.loads((user_dir / "settings.json").read_text(encoding="utf-8"))["mine"] == 1


def test_save_creates_the_folder(user_dir: Path) -> None:
    (user_dir / "settings.json").unlink(missing_ok=True)
    user_dir.rmdir()
    save_settings({**DEFAULT_SETTINGS, "recent_projects": ["/a"]})
    assert load_settings()["recent_projects"] == ["/a"]


def test_recent_projects_newest_first_no_duplicates(project: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    add_recent_project(other)
    add_recent_project(project)
    add_recent_project(other)
    assert load_settings()["recent_projects"] == [str(other), str(project)]


def test_recent_projects_capped(tmp_path: Path) -> None:
    for i in range(15):
        add_recent_project(tmp_path / f"p{i}")
    recent = load_settings()["recent_projects"]
    assert len(recent) == 10
    assert recent[0] == str(tmp_path / "p14")


def test_app_for_extension() -> None:
    settings = {"dcc": {"hip": {"name": "Houdini", "exe": "/Apps/Houdini.app"}}}
    assert app_for(settings, "hip") == "/Apps/Houdini.app"
    assert app_for(settings, "nk") is None
    assert app_for({"dcc": {"nk": {"name": "Nuke"}}}, "nk") is None
