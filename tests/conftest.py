from __future__ import annotations

import json
from pathlib import Path

import pytest

from scheinwerk.core import hooks
from scheinwerk.core.project import DEFAULTS, Project


@pytest.fixture(autouse=True)
def user_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never load hooks from the real machine-local settings folder during tests."""
    folder = tmp_path_factory.mktemp("userdir")
    monkeypatch.setattr(hooks, "user_dir", lambda: folder)
    return folder


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An empty project: just the folder and its scheinwerk.json. Returns the root."""
    root = tmp_path / "testproject"
    root.mkdir()
    config = {"schema": 1, "name": "testproject", **DEFAULTS}
    (root / "scheinwerk.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return root


@pytest.fixture
def proj(project: Path) -> Project:
    return Project.find(project)


def touch(path: Path, content: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
