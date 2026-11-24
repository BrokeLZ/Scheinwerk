"""Pointer, entry, payload, root and structure layer text (spec §9.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.usd_pointer import (
    STRUCTURE,
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
    path = tmp_path / "shared/usd/structure.usd"
    write_structure(path)
    assert text(path) == STRUCTURE
    assert STRUCTURE.startswith('#usda 1.0\n\ndef Xform "world" (\n    kind = "group"\n)\n')
    for prim in ('def Xform "assets"', 'def Xform "env"', 'def Xform "fx"'):
        assert prim in STRUCTURE
    for scope in ("cameras", "lights", "Render"):
        assert f'def Scope "{scope}"\n{{\n}}\n' in STRUCTURE
    assert "framesPerSecond" not in STRUCTURE  # no time samples, no time metadata


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
