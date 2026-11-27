"""sw init, new, ls, next, latest, frames (spec §11)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scheinwerk.core import install
from tests.conftest import touch


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- general ----------------------------------------------------------------


def test_help_and_version(sw) -> None:
    assert sw("--help").code == 0
    assert sw("--version").out.startswith("sw ")


def test_outside_a_project(sw, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = sw("ls")
    assert r.code == 1
    assert r.out == ""
    assert r.err.startswith("sw: error: ")
    assert "sw init" in r.err


def test_usage_error_exits_2(sw, inside: Path) -> None:
    assert sw("new", "shot", "sq010_0010", "--frames", "1001").code == 2


# --- init -------------------------------------------------------------------


def test_init_uses_folder_name(sw, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "myshow"
    folder.mkdir()
    monkeypatch.chdir(folder)
    r = sw("init")
    assert (r.code, r.out) == (0, f"{folder}\n")
    assert read(folder / "scheinwerk.json")["name"] == "myshow"
    assert (folder / "assets").is_dir()


def test_init_with_name(sw, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "My Show"
    folder.mkdir()
    monkeypatch.chdir(folder)
    r = sw("init")
    assert r.code == 1
    assert "sw init <name>" in r.err
    assert sw("init", "myshow").code == 0
    assert read(folder / "scheinwerk.json")["name"] == "myshow"
    assert "already" in sw("init", "again").err


# --- new --------------------------------------------------------------------


def test_new_entities(sw, inside: Path) -> None:
    assert sw("new", "asset", "hero").out == f"{inside / 'assets' / 'hero'}\n"
    assert sw("new", "asset", "char/villain").out == f"{inside / 'assets' / 'char' / 'villain'}\n"
    assert sw("new", "category", "vehicle").out == f"{inside / 'assets' / 'vehicle'}\n"
    assert sw("new", "seq", "sq020").out == f"{inside / 'shots' / 'sq020'}\n"
    r = sw("new", "shot", "sq010_0010", "--frames", "1001-1096")
    assert r.out == f"{inside / 'shots' / 'sq010' / 'sq010_0010'}\n"
    assert read(inside / "shots/sq010/sq010_0010/entity.json")["frames"] == [1001, 1096]


def test_new_relative_and_json(sw, inside: Path) -> None:
    assert sw("new", "asset", "hero", "--relative").out == "assets/hero\n"
    assert sw("new", "seq", "sq010", "--json").json == {"path": str(inside / "shots" / "sq010")}
    assert sw("new", "shot", "sq010_0010", "--json", "--relative").json == {
        "path": "shots/sq010/sq010_0010"
    }


def test_new_dept_task_product(sw, inside: Path) -> None:
    sw("new", "asset", "hero")
    sw("new", "dept", "hero", "mdl")  # template tasks
    assert (inside / "assets/hero/mdl/main/work").is_dir()
    sw("new", "dept", "hero", "groom", "--tasks", "main", "alt")
    assert (inside / "assets/hero/groom/alt/cache").is_dir()
    r = sw("new", "task", "hero", "mdl", "blockout", "--relative")
    assert r.out == "assets/hero/mdl/blockout\n"
    assert sw("new", "product", "hero", "pants", "--relative").out == "assets/hero/publish/pants\n"


def test_new_errors(sw, inside: Path) -> None:
    sw("new", "asset", "hero")
    for args in [
        ("new", "asset", "hero"),  # exists
        ("new", "asset", "Hero2"),  # invalid
        ("new", "dept", "ghost", "mdl"),  # no such entity
        ("new", "task", "hero", "mdl", "main"),  # no such department
    ]:
        r = sw(*args)
        assert r.code == 1, args
        assert r.err.startswith("sw: error: "), args


# --- ls ---------------------------------------------------------------------


@pytest.fixture
def populated(sw, inside: Path) -> Path:
    sw("new", "asset", "hero")
    sw("new", "asset", "char/villain")
    sw("new", "category", "vehicle")
    sw("new", "shot", "sq010_0010", "--frames", "1001-1096")
    sw("new", "shot", "sq010_0020", "--frames", "1097-1200")
    touch(inside / "assets/Hero_Old/entity.json")
    return inside


def test_ls_project(sw, populated: Path) -> None:
    assert sw("ls").out == (
        "assets\n"
        "  Hero_Old  [invalid name]\n"
        "  hero\n"
        "  char/villain\n"
        "  vehicle/  (empty category)\n"
        "shots\n"
        "  sq010  1001-1200\n"
        "    sq010_0010  1001-1096\n"
        "    sq010_0020  1097-1200\n"
    )


def test_ls_empty_project(sw, inside: Path) -> None:
    assert sw("ls").out == "assets\n  (none)\nshots\n  (none)\n"


def test_ls_project_json(sw, populated: Path) -> None:
    data = sw("ls", "--json", "--relative").json
    assert data["assets"][2] == {
        "name": "villain",
        "category": "char",
        "valid": True,
        "path": "assets/char/villain",
    }
    assert data["categories"] == ["char", "vehicle"]
    seq = data["sequences"][0]
    assert (seq["name"], seq["frames"], seq["path"]) == ("sq010", [1001, 1200], "shots/sq010/_seq")
    assert [s["name"] for s in seq["shots"]] == ["sq010_0010", "sq010_0020"]


@pytest.fixture
def hero(sw, inside: Path) -> Path:
    sw("new", "asset", "hero")
    sw("new", "dept", "hero", "mdl")
    sw("new", "task", "hero", "mdl", "blockout")
    sw("new", "dept", "hero", "groom")
    pub = inside / "assets/hero/publish"
    touch(pub / "pants/v001/x.abc")
    (pub / "cam").mkdir()
    for v in ["v001", "v002"]:
        touch(pub / f"_usd/asset/{v}/hero_asset_{v}.usd")
    touch(
        pub / "_usd/asset/asset.usd",
        b'#usda 1.0\n(\n    defaultPrim = "hero"\n'
        b"    subLayers = [@./v001/hero_asset_v001.usd@]\n)\n",
    )
    touch(inside / "assets/hero/media/turntable/v003/t.mov")
    return inside / "assets/hero"


def test_ls_entity(sw, hero: Path) -> None:
    assert sw("ls", "hero").out == (
        "hero (asset)\n"
        "departments\n"
        "  mdl\n"
        "    main\n"
        "    blockout  [custom]\n"
        "  groom  [custom]\n"
        "    main  [custom]\n"
        "products\n"
        "  asset  [usd]  latest v002, current v001\n"
        "  cam  (no versions)\n"
        "  pants  latest v001\n"
        "media\n"
        "  turntable  latest v003\n"
    )


def test_ls_shot_header_shows_frames(sw, inside: Path) -> None:
    sw("new", "shot", "sq010_0010", "--frames", "1001-1096")
    assert sw("ls", "sq010_0010").lines[0] == "sq010_0010 (shot in sq010)  1001-1096"
    assert sw("ls", "sq010").lines[0] == "sq010 (sequence)  1001-1096"


def test_ls_department_and_task(sw, hero: Path) -> None:
    assert sw("ls", "hero", "mdl").out == "main\nblockout  [custom]\n"
    work = hero / "mdl/main/work"
    touch(work / "hero_mdl_main_v001.hip")
    touch(work / "hero_mdl_main_v002.nk")
    touch(work / "notes.txt")
    assert sw("ls", "hero", "mdl/main").out == (
        "hero_mdl_main_v002.nk\nhero_mdl_main_v001.hip\nunmanaged\n  notes.txt\n"
    )
    data = sw("ls", "hero", "mdl/main", "--json", "--relative").json
    assert data["workfiles"][0] == {
        "path": "assets/hero/mdl/main/work/hero_mdl_main_v002.nk",
        "version": 2,
        "ext": "nk",
    }
    assert data["unmanaged"] == ["assets/hero/mdl/main/work/notes.txt"]


def test_ls_entity_json(sw, hero: Path) -> None:
    data = sw("ls", "hero", "--json").json
    assert data["entity"]["type"] == "asset"
    assert [d["name"] for d in data["departments"]] == ["mdl", "groom"]
    assert data["departments"][0]["tasks"][1] == {
        "name": "blockout",
        "custom": True,
        "valid": True,
        "path": str(hero / "mdl" / "blockout"),
    }
    asset = data["products"][0]
    assert (asset["name"], asset["usd"], asset["latest"], asset["current"]) == (
        "asset",
        True,
        2,
        1,
    )


# --- next / latest ----------------------------------------------------------


def test_next(sw, hero: Path) -> None:
    work = hero / "mdl/main/work"
    assert (
        sw("next", "hero", "mdl/main", "--ext", "hip").out == f"{work / 'hero_mdl_main_v001.hip'}\n"
    )
    touch(work / "hero_mdl_main_v001.hip")
    r = sw("next", "hero", "groom", "--ext", "nk", "--relative")  # one task: picked
    assert r.out == "assets/hero/groom/main/work/hero_groom_main_v001.nk\n"
    assert not (hero / "groom/main/work/hero_groom_main_v001.nk").exists()  # path only


def test_next_task_errors(sw, hero: Path) -> None:
    assert "several tasks" in sw("next", "hero", "mdl", "--ext", "hip").err
    assert sw("next", "hero", "mdl/ghost", "--ext", "hip").code == 1
    assert sw("next", "hero", "mdl/main", "--ext", ".hip").code == 1


def test_next_publish_usd_media(sw, hero: Path) -> None:
    assert (
        sw("next-publish", "hero", "pants", "--relative").out == "assets/hero/publish/pants/v002\n"
    )
    assert (
        sw("next-usd", "hero", "asset", "--relative").out == "assets/hero/publish/_usd/asset/v003\n"
    )
    assert (
        sw("next-media", "hero", "turntable", "--relative").out
        == "assets/hero/media/turntable/v004\n"
    )
    assert (hero / "media/turntable/v004").is_dir()


def test_latest(sw, hero: Path) -> None:
    touch(hero / "mdl/main/work/hero_mdl_main_v004.hip")
    assert sw("latest", "hero", "--product", "pants", "--relative").out == (
        "assets/hero/publish/pants/v001\n"
    )
    assert sw("latest", "hero", "--usd", "asset", "--relative").out == (
        "assets/hero/publish/_usd/asset/v002\n"
    )
    assert sw("latest", "hero", "--media", "turntable", "--relative").out == (
        "assets/hero/media/turntable/v003\n"
    )
    assert sw("latest", "hero", "--work", "mdl/main", "--relative").out == (
        "assets/hero/mdl/main/work/hero_mdl_main_v004.hip\n"
    )


def test_latest_nothing_yet(sw, hero: Path) -> None:
    for args in [("--product", "cam"), ("--product", "ghost"), ("--work", "mdl/blockout")]:
        r = sw("latest", "hero", *args)
        assert (r.code, r.out) == (1, ""), args


def test_latest_needs_exactly_one_kind(sw, hero: Path) -> None:
    assert sw("latest", "hero").code == 2
    assert sw("latest", "hero", "--product", "a", "--media", "b").code == 2


# --- frames -----------------------------------------------------------------


def test_frames(sw, inside: Path) -> None:
    sw("new", "shot", "sq010_0010")
    assert sw("frames", "sq010_0010").out == "(no frame range)\n"
    assert sw("frames", "sq010_0010", "1001-1096").out == "1001-1096\n"
    assert sw("frames", "sq010_0010", "--json").json == {"frames": [1001, 1096]}
    assert sw("frames", "sq010").out == "1001-1096\n"
    assert sw("frames", "sq010", "1-2").code == 1
    assert sw("frames", "sq010_0010", "1096-1001").code == 1


# --- gui ----------------------------------------------------------------------


def test_gui_without_pyside(sw, inside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scheinwerk.cli._has_pyside", lambda: False)
    r = sw("gui")
    assert r.code == 1
    assert "uv sync --extra gui" in r.err


def test_gui_starts_its_own_process(sw, inside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr("scheinwerk.cli._has_pyside", lambda: True)
    monkeypatch.setattr("scheinwerk.cli.subprocess.call", lambda cmd: calls.append(cmd) or 0)
    assert sw("gui", "assets").code == 0
    assert calls[0][1:] == ["-m", "scheinwerk.gui", str(inside / "assets")]


def test_next_without_extension(sw, hero: Path) -> None:
    r = sw("next", "hero", "mdl/main", "--relative")
    assert r.out == "assets/hero/mdl/main/work/hero_mdl_main_v001\n"


def test_next_publish_file(sw, hero: Path) -> None:
    r = sw("next-publish", "hero", "pants", "--file", "--relative")
    assert r.out == "assets/hero/publish/pants/v002/hero_pants_v002\n"
    assert (hero / "publish/pants/v002").is_dir()
    r = sw("next-media", "hero", "turntable", "--file", "--relative")
    assert r.out == "assets/hero/media/turntable/v004/hero_turntable_v004\n"
    r = sw("next-usd", "hero", "asset", "--file", "--relative")
    assert r.out == "assets/hero/publish/_usd/asset/v003/hero_asset_v003\n"


# --- install ------------------------------------------------------------------------


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    if sys.platform == "darwin":
        prefs = home / "Library/Preferences/houdini/21.0"
    elif sys.platform == "win32":
        prefs = home / "Documents/houdini21.0"
    else:
        prefs = home / "houdini21.0"
    prefs.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    # on Windows the real Documents folder comes from the registry: keep it out of the test
    monkeypatch.setattr(install, "documents_dir", lambda h=None: (h or home) / "Documents")
    return prefs


def test_install_and_uninstall_houdini(sw, fake_home: Path) -> None:
    package = fake_home / "packages/scheinwerk.json"
    r = sw("install", "houdini")
    assert (r.code, r.out) == (0, f"{package}\n")
    repo = Path(__file__).resolve().parents[2]
    assert (
        json.loads(package.read_text(encoding="utf-8"))["env"][0]["SCHEINWERK"] == repo.as_posix()
    )
    assert sw("uninstall", "houdini").out == f"{package}\n"
    assert not package.exists()
    assert sw("uninstall", "houdini").out == "Nothing to remove.\n"


def test_install_houdini_with_the_library(sw, fake_home: Path, tmp_path: Path) -> None:
    assert sw("lib", "init", tmp_path / "library").code == 0
    assert sw("install", "houdini").code == 0
    env = json.loads((fake_home / "packages/scheinwerk.json").read_text(encoding="utf-8"))["env"]
    assert {"SW_LIBRARY": (tmp_path / "library").as_posix()} in env


def test_install_unknown_dcc(sw) -> None:
    assert sw("install", "maya").code == 2
