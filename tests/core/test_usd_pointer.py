"""Pointer and root layer text (spec §9.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.usd_pointer import read_pointer, write_pointer, write_root_layer


def test_pointer_text(tmp_path: Path) -> None:
    path = tmp_path / "asset.usd"
    write_pointer(path, "./v003/hero_asset_v003.usd", "hero")
    assert path.read_text(encoding="utf-8") == (
        "#usda 1.0\n"
        "(\n"
        '    defaultPrim = "hero"\n'
        "    subLayers = [@./v003/hero_asset_v003.usd@]\n"
        ")\n"
    )


def test_asset_entry_layer_text(tmp_path: Path) -> None:
    path = tmp_path / "hero.usd"
    write_root_layer(path, ["./fx/fx.usd", "./geo/geo.usd"], default_prim="hero")
    assert path.read_text(encoding="utf-8") == (
        "#usda 1.0\n"
        "(\n"
        '    defaultPrim = "hero"\n'
        "    subLayers = [\n"
        "        @./fx/fx.usd@,\n"
        "        @./geo/geo.usd@\n"
        "    ]\n"
        ")\n"
    )


def test_shot_root_layer_has_no_default_prim(tmp_path: Path) -> None:
    path = tmp_path / "sq010_0010.usd"
    write_root_layer(path, ["./lgt/lgt.usd"])
    assert path.read_text(encoding="utf-8") == (
        "#usda 1.0\n(\n    subLayers = [\n        @./lgt/lgt.usd@\n    ]\n)\n"
    )


def test_root_layer_without_layers(tmp_path: Path) -> None:
    path = tmp_path / "x.usd"
    write_root_layer(path, [])
    assert path.read_text(encoding="utf-8") == "#usda 1.0\n(\n    subLayers = []\n)\n"


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
        write_pointer(tmp_path / "a.usd", target, "hero")
    with pytest.raises(ScheinwerkError):
        write_root_layer(tmp_path / "b.usd", [target])
    assert list(tmp_path.iterdir()) == []


def test_read_pointer(tmp_path: Path) -> None:
    path = tmp_path / "asset.usd"
    assert read_pointer(path) is None
    write_pointer(path, "./v003/hero_asset_v003.usd", "hero")
    assert read_pointer(path) == "./v003/hero_asset_v003.usd"
    path.write_text("garbage", encoding="utf-8")
    assert read_pointer(path) is None
