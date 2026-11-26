"""Pointer, entry, payload, root and structure layer text (spec §9.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.project import Project
from scheinwerk.core.usd_pointer import (
    STRUCTURE,
    asset_prim_path,
    layers_below,
    read_pointer,
    write_component,
    write_pointer,
    write_root_layer,
    write_structure,
)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_asset_pointer_text(tmp_path: Path) -> None:
    path = tmp_path / "geo.usd"
    write_pointer(path, "./v003/hero_geo_v003.usd", fps=24, default_prim="hero")
    assert text(path) == (
        "#usda 1.0\n"
        "(\n"
        '    defaultPrim = "hero"\n'
        "    framesPerSecond = 24\n"
        "    timeCodesPerSecond = 24\n"
        "    subLayers = [@./v003/hero_geo_v003.usd@]\n"
        ")\n"
    )


def test_shot_pointer_has_no_default_prim(tmp_path: Path) -> None:
    path = tmp_path / "lgt.usd"
    write_pointer(path, "./v001/sq010_0010_lgt_v001.usd", fps=25)
    assert text(path) == (
        "#usda 1.0\n"
        "(\n"
        "    framesPerSecond = 25\n"
        "    timeCodesPerSecond = 25\n"
        "    subLayers = [@./v001/sq010_0010_lgt_v001.usd@]\n"
        ")\n"
    )


@pytest.mark.parametrize(
    ("fps", "written"), [(24, "24"), (24.0, "24"), (23.976, "23.976"), (29.97, "29.97")]
)
def test_fps_written_like_the_json_value(tmp_path: Path, fps: float, written: str) -> None:
    path = tmp_path / "x.usd"
    write_pointer(path, "./v001/x.usd", fps=fps)
    assert f"    framesPerSecond = {written}\n    timeCodesPerSecond = {written}\n" in text(path)


def test_component_entry_layer_text(tmp_path: Path) -> None:
    path = tmp_path / "hero.usd"
    write_component(path, "hero", fps=24)
    assert text(path) == (
        "#usda 1.0\n"
        "(\n"
        '    defaultPrim = "hero"\n'
        "    framesPerSecond = 24\n"
        "    timeCodesPerSecond = 24\n"
        ")\n"
        "\n"
        'def Xform "hero" (\n'
        '    kind = "component"\n'
        '    assetInfo = {string name = "hero"}\n'
        "    payload = @./payload.usd@</hero>\n"
        ")\n"
        "{\n"
        "}\n"
    )


def test_payload_layer_text(tmp_path: Path) -> None:
    path = tmp_path / "payload.usd"
    write_root_layer(path, ["./mtl/mtl.usd", "./geo/geo.usd"], fps=24)
    assert text(path) == (
        "#usda 1.0\n"
        "(\n"
        "    framesPerSecond = 24\n"
        "    timeCodesPerSecond = 24\n"
        "    subLayers = [\n"
        "        @./mtl/mtl.usd@,\n"
        "        @./geo/geo.usd@\n"
        "    ]\n"
        ")\n"
    )


def test_shot_root_layer_with_frames(tmp_path: Path) -> None:
    path = tmp_path / "sq010_0010.usd"
    write_root_layer(
        path,
        ["./lgt/lgt.usd", "./layout/layout.usd", "../../../_seq/publish/_usd/sq010.usd"],
        fps=24,
        frames=(1001, 1096),
    )
    assert text(path) == (
        "#usda 1.0\n"
        "(\n"
        "    framesPerSecond = 24\n"
        "    timeCodesPerSecond = 24\n"
        "    startTimeCode = 1001\n"
        "    endTimeCode = 1096\n"
        "    subLayers = [\n"
        "        @./lgt/lgt.usd@,\n"
        "        @./layout/layout.usd@,\n"
        "        @../../../_seq/publish/_usd/sq010.usd@\n"
        "    ]\n"
        ")\n"
    )


def test_root_layer_without_layers(tmp_path: Path) -> None:
    path = tmp_path / "x.usd"
    write_root_layer(path, [], fps=24)
    assert text(path) == (
        "#usda 1.0\n(\n    framesPerSecond = 24\n    timeCodesPerSecond = 24\n"
        "    subLayers = []\n)\n"
    )


def test_structure_layer_text(tmp_path: Path) -> None:
    # Everything spatial under /world, all Xforms with kind group (assets below them stay
    # models); render settings outside (spec §9.2).
    path = tmp_path / "shared/usd/structure.usd"
    write_structure(path)
    assert text(path) == STRUCTURE
    groups = "".join(
        f'\n    def Xform "{name}" (\n        kind = "group"\n    )\n    {{\n    }}\n'
        for name in ("chars", "props", "env", "fx", "cameras", "lights")
    )
    expected = (
        '#usda 1.0\n\ndef Xform "world" (\n    kind = "group"\n)\n{'
        + groups
        + '}\n\ndef Scope "Render"\n{\n}\n'
    )
    assert expected == STRUCTURE


@pytest.mark.parametrize(
    ("category", "prim"),
    [
        ("char", "/world/chars/hero"),
        ("prop", "/world/props/hero"),
        ("env", "/world/env/hero"),
        ("vehicles", "/world/props/hero"),  # any other category
        (None, "/world/props/hero"),  # no category
    ],
)
def test_asset_prim_path(proj: Project, category: str | None, prim: str) -> None:
    assert asset_prim_path(proj.create_asset("hero", category=category)) == prim


def test_structure_layer_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "structure.usd"
    path.write_text("#usda 1.0\n# changed by the user\n", encoding="utf-8")
    write_structure(path)
    assert text(path) == "#usda 1.0\n# changed by the user\n"


@pytest.mark.parametrize(
    "target",
    [
        "/Users/lorenz/x.usd",
        "C:/proj/x.usd",
        "v003/x.usd",  # must say ./ explicitly
        ".\\v003\\x.usd",
        "//server/share/x.usd",
    ],
)
def test_absolute_or_odd_paths_rejected(tmp_path: Path, target: str) -> None:
    with pytest.raises(ScheinwerkError):
        write_pointer(tmp_path / "a.usd", target, fps=24, default_prim="hero")
    with pytest.raises(ScheinwerkError):
        write_root_layer(tmp_path / "b.usd", [target], fps=24)
    assert list(tmp_path.iterdir()) == []


def test_read_pointer(tmp_path: Path) -> None:
    path = tmp_path / "geo.usd"
    assert read_pointer(path) is None
    write_pointer(path, "./v003/hero_geo_v003.usd", fps=25, default_prim="hero")
    assert read_pointer(path) == "./v003/hero_geo_v003.usd"
    path.write_text("garbage", encoding="utf-8")
    assert read_pointer(path) is None


def published(entity, *layers: str) -> None:
    for layer in layers:
        pointer = entity.path / "publish/_usd" / layer / f"{layer}.usd"
        pointer.parent.mkdir(parents=True)
        write_pointer(pointer, f"./v001/{entity.name}_{layer}_v001.usd", fps=24)


def test_layers_below_an_asset_layer(proj: Project) -> None:
    # What a version of `layer` sits on: the weaker published layers (asset order: mtl,
    # geo, then the rest A-Z), so loading mtl from disk also loads the geo (spec §13.2).
    hero = proj.create_asset("hero")
    usd = hero.path / "publish/_usd"
    assert layers_below(hero, "mtl") == []  # nothing published yet
    published(hero, "geo", "mtl", "groom")
    assert layers_below(hero, "mtl") == [usd / "geo/geo.usd", usd / "groom/groom.usd"]
    assert layers_below(hero, "geo") == [usd / "groom/groom.usd"]
    assert layers_below(hero, "groom") == []
    assert layers_below(hero, "zzz") == []  # a new layer: weakest, A-Z after groom


def test_layers_below_a_shot_layer_end_with_the_structure(proj: Project) -> None:
    shot = proj.create_shot("sq010_0010")
    usd = shot.path / "publish/_usd"
    structure = proj.root / "shared/usd/structure.usd"
    published(shot, "lgt", "anim", "cam", "layout")
    # usd_layer_order: lgt, fx, anim, cam, layout; fx is not published
    assert layers_below(shot, "lgt") == [
        usd / "anim/anim.usd",
        usd / "cam/cam.usd",
        usd / "layout/layout.usd",
        structure,
    ]
    assert layers_below(shot, "cam") == [usd / "layout/layout.usd", structure]
    assert layers_below(shot, "layout") == [structure]
    assert layers_below(shot, "extra") == [structure]  # not in the order: after it


def test_layers_below_a_shot_layer_end_with_the_sequence_root(proj: Project) -> None:
    shot = proj.create_shot("sq010_0010")
    seq = proj.entity("sq010")
    published(seq, "lgt")
    seq_root = seq.path / "publish/_usd/sq010.usd"
    seq_root.write_text("#usda 1.0\n", encoding="utf-8")
    published(shot, "anim")
    assert layers_below(shot, "lgt") == [shot.path / "publish/_usd/anim/anim.usd", seq_root]
    structure = proj.root / "shared/usd/structure.usd"
    assert layers_below(seq, "fx") == [structure]  # the sequence's lgt is stronger than fx
