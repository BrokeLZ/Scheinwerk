"""`sw install houdini`: the package file in Houdini's preferences (spec §13.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scheinwerk.core.errors import AlreadyExists, NotFound
from scheinwerk.core.install import houdini_pref_dirs, install_houdini, uninstall_houdini

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def mac_home(tmp_path: Path) -> Path:
    for version in ("21.0", "22.0"):
        (tmp_path / "Library/Preferences/houdini" / version).mkdir(parents=True)
    (tmp_path / "Library/Preferences/houdini/notes").mkdir()  # not a version
    return tmp_path


def test_pref_dirs_per_os(mac_home: Path, tmp_path: Path) -> None:
    prefs = mac_home / "Library/Preferences/houdini"
    assert houdini_pref_dirs(mac_home, "darwin") == [prefs / "21.0", prefs / "22.0"]
    win = tmp_path / "win"
    (win / "Documents/houdini21.0").mkdir(parents=True)
    (win / "Documents/houdini_stuff").mkdir()
    assert houdini_pref_dirs(win, "win32") == [win / "Documents/houdini21.0"]
    linux = tmp_path / "linux"
    (linux / "houdini22.0").mkdir(parents=True)
    assert houdini_pref_dirs(linux, "linux") == [linux / "houdini22.0"]


def test_install_writes_one_package_per_version(mac_home: Path) -> None:
    written = install_houdini(REPO, mac_home, "darwin")
    prefs = mac_home / "Library/Preferences/houdini"
    assert written == [prefs / v / "packages/scheinwerk.json" for v in ("21.0", "22.0")]
    data = json.loads(written[0].read_text(encoding="utf-8"))
    assert data["env"][0] == {"SCHEINWERK": REPO.as_posix()}
    assert data["path"] == "$SCHEINWERK/integrations/houdini"


def test_install_again_updates_its_own_file(mac_home: Path, tmp_path: Path) -> None:
    old = tmp_path / "old_checkout"
    (old / "integrations/houdini").mkdir(parents=True)
    (old / "integrations/houdini/scheinwerk.json").write_bytes(
        (REPO / "integrations/houdini/scheinwerk.json").read_bytes()
    )
    install_houdini(old, mac_home, "darwin")
    [first, _] = install_houdini(REPO, mac_home, "darwin")
    assert json.loads(first.read_text(encoding="utf-8"))["env"][0]["SCHEINWERK"] == REPO.as_posix()


def test_install_never_touches_a_foreign_file(mac_home: Path) -> None:
    foreign = mac_home / "Library/Preferences/houdini/22.0/packages/scheinwerk.json"
    foreign.parent.mkdir()
    foreign.write_text('{"path": "mine"}', encoding="utf-8")
    with pytest.raises(AlreadyExists, match="scheinwerk.json"):
        install_houdini(REPO, mac_home, "darwin")
    assert foreign.read_text(encoding="utf-8") == '{"path": "mine"}'
    assert not (mac_home / "Library/Preferences/houdini/21.0/packages").exists()  # all or nothing


def test_no_houdini_preferences(tmp_path: Path) -> None:
    with pytest.raises(NotFound, match="Start Houdini once"):
        install_houdini(REPO, tmp_path, "darwin")


def test_uninstall_removes_only_its_own_files(mac_home: Path) -> None:
    written = install_houdini(REPO, mac_home, "darwin")
    foreign = written[1]
    foreign.write_text('{"path": "mine"}', encoding="utf-8")
    assert uninstall_houdini(mac_home, "darwin") == [written[0]]
    assert not written[0].exists()
    assert foreign.exists()
    assert uninstall_houdini(mac_home, "darwin") == []


def test_integration_files_are_valid_xml() -> None:
    import xml.etree.ElementTree as ET

    houdini = REPO / "integrations/houdini"
    for name in (
        "MainMenuCommon.xml",
        "toolbar/scheinwerk.shelf",
        "python_panels/scheinwerk.pypanel",
    ):
        ET.parse(houdini / name)  # raises on a typo
    assert (houdini / "python3.11libs/pythonrc.py").read_bytes() == (
        houdini / "python3.13libs/pythonrc.py"
    ).read_bytes()
