"""Open and reveal: one helper per OS (CLAUDE.md rule 6).

The real launchers can't run in tests, so these check the command each OS gets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scheinwerk.core.errors import NotFound
from scheinwerk.core.system import open_command, reveal_command
from tests.conftest import touch


@pytest.fixture
def scene(tmp_path: Path) -> Path:
    return touch(tmp_path / "my show/hero_mdl_main_v001.hip")


def test_open_default_app(scene: Path) -> None:
    assert open_command(scene, platform="darwin") == ["open", str(scene)]
    assert open_command(scene, platform="win32") is None  # os.startfile
    assert open_command(scene, platform="linux") == ["xdg-open", str(scene)]


def test_open_with_app(scene: Path) -> None:
    app = "/Applications/Houdini FX.app"
    assert open_command(scene, app, platform="darwin") == ["open", "-a", app, str(scene)]
    exe = r"C:\Program Files\Nuke\Nuke.exe"
    assert open_command(scene, exe, platform="win32") == [exe, str(scene)]


def test_reveal(scene: Path) -> None:
    assert reveal_command(scene, platform="darwin") == ["open", "-R", str(scene)]
    assert reveal_command(scene, platform="win32") == ["explorer", f"/select,{scene}"]
    assert reveal_command(scene, platform="linux") == ["xdg-open", str(scene.parent)]


def test_missing_path(tmp_path: Path) -> None:
    with pytest.raises(NotFound):
        open_command(tmp_path / "ghost.hip", platform="darwin")
    with pytest.raises(NotFound):
        reveal_command(tmp_path / "ghost.hip", platform="darwin")
