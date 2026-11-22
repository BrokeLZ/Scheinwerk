"""sw finalize, set-current, ingest, context, env, doctor (spec §11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import touch


@pytest.fixture
def hero(sw, inside: Path) -> Path:
    sw("new", "asset", "hero")
    sw("new", "dept", "hero", "mdl")
    return inside / "assets/hero"


def info(vdir: Path) -> dict:
    return json.loads((vdir / "version.json").read_text(encoding="utf-8"))


# --- finalize / set-current -------------------------------------------------


def test_finalize(sw, hero: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vdir = Path(sw("next-publish", "hero", "pants").out.strip())
    touch(vdir / "x.abc")
    src = hero / "mdl/main/work/hero_mdl_main_v003.hip"
    monkeypatch.chdir(vdir.parent)  # relative path argument
    r = sw("finalize", "v001", "-m", "first drape", "--source", src, "--relative")
    assert (r.code, r.out) == (0, "assets/hero/publish/pants/v001\n")
    data = info(vdir)
    assert (data["comment"], data["source"], data["dept"]) == (
        "first drape",
        "assets/hero/mdl/main/work/hero_mdl_main_v003.hip",
        "mdl",
    )


def test_finalize_usd_and_set_current(sw, hero: Path) -> None:
    v1 = Path(sw("next-usd", "hero", "asset").out.strip())
    touch(v1 / "a.usd")
    touch(v1 / "b.usd")
    r = sw("finalize", v1)
    assert r.code == 1
    assert "--main" in r.err  # the CLI names its own flag
    assert sw("finalize", v1, "--main", "b.usd").code == 0
    v2 = Path(sw("next-usd", "hero", "asset").out.strip())
    touch(v2 / "hero_asset_v002.usd")
    sw("finalize", v2)
    pointer = hero / "publish/_usd/asset/asset.usd"
    assert "./v002/" in pointer.read_text(encoding="utf-8")
    r = sw("set-current", v1, "--main", "b.usd", "--relative")
    assert r.out == "assets/hero/publish/_usd/asset/v001\n"
    assert "@./v001/b.usd@" in pointer.read_text(encoding="utf-8")


def test_finalize_not_a_version(sw, hero: Path) -> None:
    r = sw("finalize", hero / "publish")
    assert r.code == 1
    assert "not a version folder" in r.err


# --- ingest -----------------------------------------------------------------


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    folder = tmp_path / "downloads"
    touch(folder / "scene.hip", b"hip")
    touch(folder / "comp.nk", b"nk")
    touch(folder / "plate.exr", b"exr")
    return folder


def test_ingest_into_task(sw, hero: Path, downloads: Path) -> None:
    r = sw(
        "ingest", downloads / "scene.hip", downloads / "comp.nk", "hero", "mdl/main", "--relative"
    )
    assert r.lines == [
        "assets/hero/mdl/main/work/hero_mdl_main_v001.hip",
        "assets/hero/mdl/main/work/hero_mdl_main_v002.nk",
    ]
    assert (downloads / "scene.hip").exists()


def test_ingest_into_task_by_department(sw, hero: Path, downloads: Path) -> None:
    r = sw("ingest", downloads / "scene.hip", "hero", "mdl", "--relative")
    assert r.out == "assets/hero/mdl/main/work/hero_mdl_main_v001.hip\n"


def test_ingest_into_product_and_media(sw, hero: Path, downloads: Path) -> None:
    r = sw(
        "ingest",
        downloads / "plate.exr",
        downloads / "comp.nk",
        "hero",
        "--product",
        "ref",
        "--json",
        "--relative",
    )
    assert r.json == {
        "paths": ["assets/hero/publish/ref/v001/plate.exr", "assets/hero/publish/ref/v001/comp.nk"]
    }
    r = sw("ingest", downloads / "plate.exr", "hero", "--media", "plate", "--relative")
    assert r.out == "assets/hero/media/plate/v001/plate.exr\n"


def test_ingest_errors(sw, hero: Path, downloads: Path) -> None:
    assert sw("ingest", downloads / "scene.hip", "hero").code == 2  # no target
    assert sw("ingest", "hero", "mdl/main").code == 2  # no files
    assert sw("ingest", downloads / "ghost.hip", "hero", "mdl/main").code == 1


# --- context / env ----------------------------------------------------------


def test_context(sw, hero: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = hero / "mdl/main/work"
    monkeypatch.chdir(work)
    r = sw("context")
    assert r.lines == [
        f"root         {hero.parent.parent}",
        "entity_type  asset",
        "entity       hero",
        "category     -",
        "sequence     -",
        "dept         mdl",
        "task         main",
        "area         work",
        "product      -",
        "usd          no",
        "version      -",
        "ext          -",
    ]
    data = sw("context", work / "hero_mdl_main_v007.hip", "--json").json
    assert (data["root"], data["version"], data["ext"], data["usd"]) == (
        str(hero.parent.parent),
        7,
        "hip",
        False,
    )


def test_context_errors(sw, inside: Path, tmp_path: Path) -> None:
    assert "not inside an asset" in sw("context", inside / "shared").err
    assert "not inside a Scheinwerk project" in sw("context", tmp_path).err


def test_env_formats(sw, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "it's"
    folder.mkdir()
    monkeypatch.chdir(folder)
    sw("init", "show")
    sw("new", "asset", "hero")
    root = folder.as_posix()
    plain = sw("env", "assets/hero").lines
    assert plain[0] == f"SW_ROOT={root}"
    assert "SW_ENTITY=hero" in plain
    assert "SW_SEQ=" in plain
    zsh = sw("env", "assets/hero", "--shell", "zsh").lines
    assert zsh[0] == "export SW_ROOT='" + root.replace("'", "'\\''") + "'"
    assert sw("env", "assets/hero", "--shell", "bash").lines == zsh
    pwsh = sw("env", "assets/hero", "--shell", "pwsh").lines
    assert pwsh[0] == "$env:SW_ROOT = '" + root.replace("'", "''") + "'"
    assert sw("env", "assets/hero", "--json").json["SW_ENTITY_TYPE"] == "asset"


# --- doctor -----------------------------------------------------------------


def test_doctor_clean(sw, hero: Path) -> None:
    r = sw("doctor")
    assert (r.code, r.out) == (0, "No issues found.\n")


def test_doctor_reports(sw, hero: Path) -> None:
    touch(hero / "mdl/main/work/hero_mdl_main_v003_Conflict.hip")
    touch(hero / "publish/pants/v001/x.abc")
    (hero / "publish/pants/v002").mkdir()
    r = sw("doctor", "--relative")
    assert r.code == 1
    assert r.out == (
        "conflict copy  assets/hero/mdl/main/work/hero_mdl_main_v003_Conflict.hip\n"
        "empty version  assets/hero/publish/pants/v002\n"
        "2 issues\n"
    )
    data = sw("doctor", "--json", "--relative").json
    assert data["issues"][1] == {
        "kind": "empty version",
        "path": "assets/hero/publish/pants/v002",
        "detail": "",
    }
