"""sw lib detect, ingest, rebuild (spec §17.10). hoiiotool is replaced by FakeTools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scheinwerk import cli_lib
from scheinwerk.core.textures import ImageInfo
from scheinwerk.library.root import Library
from tests.conftest import touch
from tests.library.test_ingest import FakeTools


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch) -> FakeTools:
    fake = FakeTools({"sky.exr": ImageInfo(64, 32, 3, "float")})
    monkeypatch.setattr(cli_lib.HoiioTools, "find", classmethod(lambda cls: fake))
    return fake


@pytest.fixture
def lib(sw, tmp_path: Path) -> Library:
    assert sw("lib", "init", tmp_path / "library").code == 0
    return Library.open(tmp_path / "library")


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    folder = tmp_path / "dl"
    for name in (
        "wall_Color.png",
        "wall_Normal_DX.png",
        "wall_Rough.png",
        "wall_preview.jpg",
        "sky.exr",
        "photo.webp",
    ):
        touch(folder / name)
    touch(folder / "sg" / "w_diffuse.png")
    touch(folder / "sg" / "w_spec.png")
    touch(folder / "sg" / "w_gloss.png")
    return folder


def test_detect_text(sw, lib, tools, downloads: Path) -> None:
    r = sw("lib", "detect", downloads)
    assert r.code == 0, r.err
    out = r.out
    assert "hdri  Sky  ready" in out
    assert "texture_set  Wall  ready" in out
    assert "texture_set  W  warning" in out and "spec/gloss" in out
    assert "main  normal  wall_Normal_DX.png  raw  flip green" in out
    assert "skipped  wall_preview.jpg" in out  # dropped with the one set in its folder
    assert "not used  photo.webp  (unsupported image format)" in out


def test_detect_json_is_a_plan_list(sw, lib, tools, downloads: Path) -> None:
    data = sw("lib", "detect", downloads, "--json").json
    assert sorted(e["name"] for e in data["entries"]) == ["Sky", "W", "Wall"]
    assert data["unused"][0]["reason"]


def test_ingest_files(sw, lib, tools, downloads: Path) -> None:
    r = sw(
        "lib",
        "ingest",
        downloads / "wall_Color.png",
        downloads / "wall_Normal_DX.png",
        "--category",
        "stone/wall",
        "--tag",
        "old",
        "--size",
        "2",
        "1.5",
        "-m",
        "first",
    )
    assert r.code == 0, r.err
    [item] = lib.items()
    assert r.lines[-1].startswith(f"texture_set/{item.id} v001  Wall")
    assert item.categories == ["stone/wall"] and item.tags == ["old"]
    assert item.meta["size_m"] == [2.0, 1.5]
    assert item.latest().info["comment"] == "first"


def test_warnings_need_yes(sw, lib, tools, downloads: Path) -> None:
    r = sw("lib", "ingest", downloads / "sg")
    assert r.code == 1 and "--yes" in r.err and lib.items() == []
    assert "spec/gloss" in r.out
    assert sw("lib", "ingest", downloads / "sg", "--yes").code == 0
    assert len(lib.items()) == 1


def test_name_item_variant_need_one_entry(sw, lib, tools, downloads: Path) -> None:
    r = sw("lib", "ingest", downloads, "--name", "X", "--yes")
    assert r.code == 1 and "one entry" in r.err and lib.items() == []


def test_ingest_as_a_variant_of_an_item(sw, lib, tools, downloads: Path, tmp_path: Path) -> None:
    sw("lib", "ingest", downloads / "wall_Color.png", downloads / "wall_Rough.png")
    [item] = lib.items()
    touch(tmp_path / "snow" / "snow_Color.png", b"snow colour")  # new bytes: not a duplicate
    touch(tmp_path / "snow" / "snow_Rough.png", b"snow rough")
    r = sw("lib", "ingest", tmp_path / "snow", "--item", item.id, "--variant", "winter")
    assert r.code == 0, r.err
    assert item.latest().variants() == {"main": 1, "winter": 2}


def test_type_and_name_overrides(sw, lib, tools, downloads: Path) -> None:
    r = sw("lib", "ingest", downloads / "wall_preview.jpg", "--type", "hdri", "--name", "Pano")
    assert r.code == 1 and "float" in r.err  # an 8-bit image can't be an HDRI
    r = sw("lib", "ingest", downloads / "wall_preview.jpg", "--name", "Preview Card")
    assert r.code == 0, r.err
    assert lib.items()[0].name == "Preview Card"


def test_ingest_plan_file(sw, lib, tools, downloads: Path, tmp_path: Path) -> None:
    data = sw(
        "lib", "detect", downloads / "wall_Color.png", downloads / "wall_Rough.png", "--json"
    ).json
    plan = data["entries"][0]
    plan["name"] = "Edited Wall"
    plan["variants"]["main"][1]["invert"] = True
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    r = sw("lib", "ingest", "--plan", plan_file)
    assert r.code == 0, r.err
    [item] = lib.items()
    assert item.name == "Edited Wall"
    rough = next(e for e in item.latest().info["files"] if e["role"] == "roughness")
    assert rough["invert"] is True
    plan_file.write_text(json.dumps(data), encoding="utf-8")  # detect's whole output works too
    assert sw("lib", "ingest", "--plan", plan_file).code == 0


def test_ingest_needs_files_or_a_plan(sw, lib, tools) -> None:
    assert sw("lib", "ingest").code == 2


def test_rebuild(sw, lib, tools, downloads: Path) -> None:
    sw("lib", "ingest", downloads / "sg", "--yes")
    [item] = lib.items()
    r = sw("lib", "rebuild", item.id, "--metal-threshold", "0.35")
    assert r.code == 0, r.err
    assert r.lines[-1].startswith(f"texture_set/{item.id} v002")
    assert item.latest().info["metal_threshold"] == 0.35


def test_failures_are_reported_and_the_rest_continue(sw, lib, tools, downloads: Path) -> None:
    tools.fail = "roughness"
    r = sw("lib", "ingest", downloads, "--yes")
    assert r.code == 1
    assert "boom" in r.err
    finished = [i for i in lib.items() if i.latest()]
    assert sorted(i.type for i in finished) == ["hdri"]
