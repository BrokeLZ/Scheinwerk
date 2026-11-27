"""Finding the external tools: hoiiotool, husk, hython (spec §17.2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scheinwerk.core.errors import NotFound
from scheinwerk.core.tools import find_tool, houdini_installs
from tests.conftest import touch

MAC_RES = "Frameworks/Houdini.framework/Versions/Current/Resources"


def mac_install(apps: Path, version: str, tools=("hoiiotool", "husk", "hython")) -> Path:
    bin_ = apps / f"Houdini{version}" / MAC_RES / "bin"
    for t in tools:
        touch(bin_ / t)
    return bin_


def win_install(apps: Path, version: str, tools=("hoiiotool", "husk", "hython")) -> Path:
    bin_ = apps / f"Houdini {version}" / "bin"
    for t in tools:
        touch(bin_ / f"{t}.exe")
    return bin_


def test_newest_houdini_21_0_on_macos(tmp_path: Path) -> None:
    mac_install(tmp_path, "21.0.440")
    newest = mac_install(tmp_path, "21.0.596")
    mac_install(tmp_path, "21.0.1003")  # numerically newest: 1003 > 596
    mac_install(tmp_path, "22.0.405")  # not 21.0
    assert (
        houdini_installs(tmp_path, "darwin")[0] == tmp_path / "Houdini21.0.1003" / MAC_RES / "bin"
    )
    assert newest in houdini_installs(tmp_path, "darwin")
    assert all("22.0" not in str(p) for p in houdini_installs(tmp_path, "darwin"))


def test_windows_layout(tmp_path: Path) -> None:
    bin_ = win_install(tmp_path, "21.0.596")
    found = find_tool("hoiiotool", settings={}, env={}, apps=tmp_path, platform="win32")
    assert found == bin_ / "hoiiotool.exe"


def test_order_setting_then_hfs_then_install_then_path(tmp_path: Path) -> None:
    installed = mac_install(tmp_path / "apps", "21.0.596")
    hfs = tmp_path / "hfs"
    touch(hfs / "bin" / "hoiiotool")
    own = touch(tmp_path / "own" / "oiiotool")
    # PATH lookup is the real OS's: Windows needs the .exe
    on_path = touch(tmp_path / "path" / ("oiiotool.exe" if sys.platform == "win32" else "oiiotool"))
    on_path.chmod(0o755)
    kwargs = {"apps": tmp_path / "apps", "platform": "darwin"}

    def find(settings: dict, env: dict) -> Path:
        return find_tool("hoiiotool", settings=settings, env=env, **kwargs)

    assert find({"tools": {"hoiiotool": str(own)}}, {"HFS": str(hfs)}) == own
    assert find({}, {"HFS": str(hfs)}) == hfs / "bin" / "hoiiotool"
    assert find({}, {}) == installed / "hoiiotool"
    path_env = {"PATH": str(tmp_path / "path")}
    found = find_tool(
        "hoiiotool", settings={}, env=path_env, apps=tmp_path / "none", platform="darwin"
    )
    assert found.resolve() == on_path.resolve()  # oiiotool stands in for hoiiotool


def test_a_setting_that_points_nowhere_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(NotFound, match="tools"):
        find_tool(
            "husk",
            settings={"tools": {"husk": str(tmp_path / "gone")}},
            env={},
            apps=tmp_path,
            platform="darwin",
        )


def test_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFound, match="hoiiotool"):
        find_tool("hoiiotool", settings={}, env={"PATH": ""}, apps=tmp_path, platform="darwin")


def test_unknown_tool(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        find_tool("maya", settings={}, env={}, apps=tmp_path, platform="darwin")
