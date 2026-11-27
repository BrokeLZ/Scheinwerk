# ruff: noqa: E501  (tool output pasted as-is)
"""The texture processor (spec §17.5): recipes -> hoiiotool command lines, and real runs.

The command-line tests need nothing installed. The `real` tests run Houdini's hoiiotool and
are skipped where it isn't installed (CI).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scheinwerk.core import textures as tx
from scheinwerk.core.errors import InvalidName, NotFound, ScheinwerkError
from scheinwerk.core.tools import find_tool

HELP = """oiiotool -- simple image processing operations
OpenImageIO 2.5.18.0 http://www.openimageio.org

Usage: oiiotool [filename|command]...
OpenColorIO 2.4.1, color config: /HFS/packages/ocio/houdini-config-v2.1.0_aces-v1.3_ocio-v2.3.ocio
Known color spaces: "ACES2065-1", "ACEScg", "Linear Rec.709 (sRGB)" (linear), "sRGB - Texture", "Raw"
Known looks: "ACES 1.3 Reference Gamut Compression"
Known displays: "sRGB - Display"* (views: "Un-tone-mapped"*, "ACES 1.0 - SDR Video", "Raw"), "P3-D65 - Display" (views: "Un-tone-mapped"*, "Raw") (* = default)
"""


# --- parsing tool output ------------------------------------------------------------------


def test_tool_info() -> None:
    info = tx.parse_tool_info(HELP)
    assert info.version == "2.5.18.0"
    assert info.ocio_config == "houdini-config-v2.1.0_aces-v1.3_ocio-v2.3.ocio"
    assert info.color_spaces == [
        "ACES2065-1",
        "ACEScg",
        "Linear Rec.709 (sRGB)",
        "sRGB - Texture",
        "Raw",
    ]
    assert info.displays == {
        "sRGB - Display": ["Un-tone-mapped", "ACES 1.0 - SDR Video", "Raw"],
        "P3-D65 - Display": ["Un-tone-mapped", "Raw"],
    }
    assert info.default_display == "sRGB - Display"
    assert info.srgb_texture == "sRGB - Texture"
    assert info.linear_rec709 == "Linear Rec.709 (sRGB)"


def test_preview_view_prefers_aces_sdr_video() -> None:
    info = tx.parse_tool_info(HELP)
    assert info.preview_view() == ("sRGB - Display", "ACES 1.0 - SDR Video")
    plain = tx.parse_tool_info(HELP.replace('"ACES 1.0 - SDR Video", ', ""))
    assert plain.preview_view() == ("sRGB - Display", "Un-tone-mapped")


def test_other_config_names() -> None:
    info = tx.parse_tool_info(
        HELP.replace("sRGB - Texture", "srgb_texture").replace(
            "Linear Rec.709 (sRGB)", "lin_rec709"
        )
    )
    assert (info.srgb_texture, info.linear_rec709) == ("srgb_texture", "lin_rec709")
    with pytest.raises(NotFound, match="sRGB"):
        _ = tx.parse_tool_info(HELP.replace("sRGB - Texture", "xyz")).srgb_texture


@pytest.mark.parametrize(
    ("line", "info"),
    [
        ("a.png :  256 x  256, 3 channel, uint8 png", tx.ImageInfo(256, 256, 3, "uint8")),
        (
            "b.tx  : 4096 x 4096, 1 channel, uint16 tiff (+mipmap)",
            tx.ImageInfo(4096, 4096, 1, "uint16"),
        ),
        ("c.exr : 8192 x 4096, 4 channel, half openexr", tx.ImageInfo(8192, 4096, 4, "half")),
        ("d.hdr : 2048 x 1024, 3 channel, float hdr", tx.ImageInfo(2048, 1024, 3, "float")),
    ],
)
def test_parse_image_info(line: str, info: tx.ImageInfo) -> None:
    assert tx.parse_image_info(line) == info


def test_image_info_props() -> None:
    assert tx.ImageInfo(2048, 1024, 3, "float").is_float
    assert not tx.ImageInfo(2048, 1024, 3, "uint8").is_float


def test_parse_stats_max() -> None:
    out = "    Stats Min: 0.0 0.0 0.0 (float)\n    Stats Max: 95657.18 90567.42 81508.0 (float)\n"
    assert tx.parse_stats_max(out) == 95657.18
    assert tx.parse_stats_max("Stats Max: 255 128 0 (of 255)") == 1.0


# --- output type and container ------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "fmt", "peak", "expected"),
    [
        ("basecolor", "uint8", None, "half"),
        ("color", "uint16", None, "half"),
        ("emission", "float", None, "half"),
        ("hdri", "float", 3000.0, "half"),
        ("hdri", "half", 65504.0, "half"),
        ("hdri", "float", 95657.0, "float"),
        ("roughness", "uint8", None, "uint8"),
        ("normal", "uint16", None, "uint16"),
        ("height", "float", None, "float"),
        ("height", "half", None, "half"),
        ("data", "uint32", None, "uint16"),
    ],
)
def test_output_type(role: str, fmt: str, peak: float | None, expected: str) -> None:
    assert tx.output_type(role, tx.ImageInfo(64, 64, 3, fmt), peak) == expected


def test_extension() -> None:
    assert [tx.extension(t) for t in ("half", "float", "uint8", "uint16")] == [
        "exr",
        "exr",
        "tx",
        "tx",
    ]


# --- command lines ------------------------------------------------------------------------


def rec(role: str, out: str = "out.exr", **kw) -> tx.Recipe:
    """A recipe with sources given relative to "." (entry() paths stay as they are)."""
    defaults = {"from_space": "sRGB - Texture", "to_space": "ACEScg", "data_type": "half"}
    if role in tx.DATA_ROLES:
        defaults = {"from_space": "raw", "to_space": "raw", "data_type": "uint8"}
    sources = kw.pop("sources", (Path("src.png"),))
    return tx.Recipe(sources=tuple(sources), output=Path(out), role=role, **{**defaults, **kw})


LIN = "Linear Rec.709 (sRGB)"


def cmd(recipe: tx.Recipe, channels: int = 3) -> list[str]:
    return tx.command(recipe, channels, LIN)


def test_colour_role() -> None:
    assert cmd(rec("basecolor")) == [
        "src.png",
        "--colorconvert",
        "sRGB - Texture",
        "ACEScg",
        "-d",
        "half",
        "-otex",
        "out.exr",
    ]


def test_colour_role_drops_alpha_and_expands_grey() -> None:
    assert cmd(rec("basecolor"), 4)[1:3] == ["--ch", "R,G,B"]
    assert cmd(rec("basecolor"), 1)[1:3] == ["--ch", "0,0,0"]


def test_hdri_is_a_latlong_env_map() -> None:
    r = rec("hdri", from_space=LIN, data_type="float")
    assert cmd(r) == ["src.png", "--colorconvert", LIN, "ACEScg", "-d", "float", "-oenv", "out.exr"]


def test_scalar_data_role_keeps_one_channel() -> None:
    assert cmd(rec("roughness", "r.tx")) == ["src.png", "--ch", "0", "-d", "uint8", "-otex", "r.tx"]
    assert cmd(rec("roughness", "r.tx"), 1) == ["src.png", "-d", "uint8", "-otex", "r.tx"]


def test_packed_map_channel() -> None:
    # Poly Haven `arm`: AO in R, roughness in G, metalness in B
    assert cmd(rec("roughness", "r.tx", channel=1)) == [
        "src.png",
        "--ch",
        "1",
        "-d",
        "uint8",
        "-otex",
        "r.tx",
    ]
    assert rec("metalness", "m.tx", channel=2).entry(Path())["channel"] == 2
    assert "channel" not in rec("roughness", "r.tx").entry(Path())


def test_gloss_to_roughness() -> None:
    assert cmd(rec("roughness", "r.tx", invert=True), 1) == [
        "src.png",
        "--invert",
        "-d",
        "uint8",
        "-otex",
        "r.tx",
    ]


def test_normal_flip_green() -> None:
    assert cmd(rec("normal", "n.tx", flip_green=True), 4) == [
        "src.png",
        "--ch",
        "R,G,B",
        "--invert:chbegin=1:chend=2",
        "-d",
        "uint8",
        "-otex",
        "n.tx",
    ]


def test_data_texture_keeps_its_channels() -> None:
    assert cmd(rec("data", "d.tx"), 4) == ["src.png", "-d", "uint8", "-otex", "d.tx"]


def test_spec_gloss_metalness() -> None:
    r = rec(
        "metalness",
        "m.tx",
        sources=(Path("spec.png"),),
        metal_threshold=0.2,
        from_space="sRGB - Texture",
    )  # the specular map's colour space
    assert cmd(r) == [
        "spec.png",
        "--colorconvert",
        "sRGB - Texture",
        LIN,
        "--maxchan",
        "--subc",
        "0.04",
        "--divc",
        "0.16",
        "--clamp:min=0:max=1",
        "-d",
        "uint8",
        "-otex",
        "m.tx",
    ]


def test_spec_gloss_metalness_spec_space_is_from_space() -> None:
    r = rec(
        "metalness",
        "m.tx",
        sources=(Path("spec.png"),),
        metal_threshold=0.2,
        from_space="sRGB - Texture",
    )
    assert "sRGB - Texture" in cmd(r)


def test_spec_gloss_basecolor() -> None:
    r = rec("basecolor", sources=(Path("diff.png"), Path("spec.png")), metal_threshold=0.25)
    assert cmd(r) == [
        "diff.png",
        "--colorconvert",
        "sRGB - Texture",
        LIN,
        "--label",
        "diff",
        "spec.png",
        "--colorconvert",
        "sRGB - Texture",
        LIN,
        "--label",
        "spec",
        "spec",
        "--maxchan",
        "--subc",
        "0.04",
        "--divc",
        "0.21",
        "--clamp:min=0:max=1",
        "--ch",
        "0,0,0",
        "--label",
        "metal",
        "spec",
        "diff",
        "--sub",
        "metal",
        "--mul",
        "diff",
        "--add",
        "--colorconvert",
        LIN,
        "ACEScg",
        "-d",
        "half",
        "-otex",
        "out.exr",
    ]


@pytest.mark.parametrize(
    ("recipe", "error"),
    [
        (rec("bark"), "role"),
        (rec("basecolor", "out.tx"), ".exr"),
        (rec("roughness", "r.exr"), ".tx"),
        (rec("roughness", "r.tx", to_space="ACEScg"), "raw"),
        (rec("basecolor", sources=(Path("a.png"), Path("b.png"))), "one source"),
        (
            rec("metalness", "m.tx", sources=(Path("a.png"), Path("b.png")), metal_threshold=0.2),
            "one source",
        ),
        (rec("hdri", data_type="uint8", out="h.tx"), "half or float"),
        (rec("normal", "n.tx", channel=1), "channel"),
        (rec("basecolor", sources=(Path("d.png"), Path("s.png")), metal_threshold=0.03), "0.04"),
    ],
)
def test_bad_recipes(recipe: tx.Recipe, error: str) -> None:
    with pytest.raises(InvalidName, match=error):
        cmd(recipe)


def test_recipe_as_version_json_entry(tmp_path: Path) -> None:
    r = tx.Recipe(
        sources=(tmp_path / "source/a.png",),
        output=tmp_path / "textures/x_main_basecolor_v001.exr",
        role="basecolor",
        from_space="sRGB - Texture",
        to_space="ACEScg",
        data_type="half",
    )
    assert r.entry(tmp_path) == {
        "source": ["source/a.png"],
        "output": "textures/x_main_basecolor_v001.exr",
        "role": "basecolor",
        "from_space": "sRGB - Texture",
        "to_space": "ACEScg",
        "data_type": "half",
        "flip_green": False,
        "invert": False,
    }


@pytest.mark.parametrize(
    ("size", "box", "fitted"),
    [
        ((3000, 1000), (512, 512), (512, 171)),
        ((4096, 8192), (512, 512), (256, 512)),
        ((100, 50), (512, 512), (100, 50)),
        ((8192, 4096), (1024, 512), (1024, 512)),
    ],
)
def test_fit_size_keeps_aspect_never_enlarges(size, box, fitted) -> None:
    assert tx.fit_size(*size, box) == fitted


def test_thumbnail_command() -> None:
    assert tx.thumbnail_command(
        Path("x.exr"),
        Path("t.jpg"),
        3,
        "ACEScg",
        ("sRGB - Display", "ACES 1.0 - SDR Video"),
        (512, 171),
    ) == [
        "x.exr",
        "--ociodisplay:from=ACEScg",
        "sRGB - Display",
        "ACES 1.0 - SDR Video",
        "--resize:filter=lanczos3",
        "512x171",
        "-d",
        "uint8",
        "-o",
        "t.jpg",
    ]
    data = tx.thumbnail_command(
        Path("r.tx"), Path("t.jpg"), 1, "raw", ("sRGB - Display", "Un-tone-mapped"), (512, 512)
    )
    assert data[:3] == ["r.tx", "--ch", "0,0,0"] and "--ociodisplay:from=raw" not in data


# --- real hoiiotool -----------------------------------------------------------------------


def _tool() -> Path | None:
    try:
        return find_tool("hoiiotool")
    except NotFound:
        return None


real = pytest.mark.skipif(_tool() is None, reason="hoiiotool not installed")


@pytest.fixture
def tool() -> Path:
    return _tool()


def make(tool: Path, path: Path, pattern: str, size: str, channels: int, fmt: str) -> Path:
    tx.run_tool(tool, ["--pattern", pattern, size, str(channels), "-d", fmt, "-o", path])
    return path


@real
def test_real_tool_info(tool: Path) -> None:
    info = tx.tool_info(tool)
    assert info.version.startswith("2.")
    assert info.srgb_texture and info.linear_rec709


@real
def test_real_colour_map(tool: Path, tmp_path: Path) -> None:
    src = make(tool, tmp_path / "c.png", "constant:color=0.5,0.25,0.75,1", "64x64", 4, "uint8")
    info = tx.tool_info(tool)
    r = tx.Recipe((src,), tmp_path / "out/c.exr", "basecolor", info.srgb_texture, "ACEScg", "half")
    tx.process(r, tool, info.linear_rec709)
    out = tx.probe(r.output, tool)
    assert out == tx.ImageInfo(64, 64, 3, "half")
    assert tx.is_mipmapped(r.output, tool)


@real
def test_real_data_map_and_flip(tool: Path, tmp_path: Path) -> None:
    src = make(tool, tmp_path / "n.png", "constant:color=0.6,0.4,1.0", "64x64", 3, "uint8")
    r = tx.Recipe((src,), tmp_path / "n.tx", "normal", "raw", "raw", "uint8", flip_green=True)
    tx.process(r, tool, "")
    assert tx.probe(r.output, tool) == tx.ImageInfo(64, 64, 3, "uint8")
    assert tx.peak(r.output, tool) == pytest.approx(1.0, abs=0.01)


@real
def test_real_hdri_peak_and_float(tool: Path, tmp_path: Path) -> None:
    src = make(tool, tmp_path / "h.exr", "constant:color=0.5,0.5,0.5", "128x64", 3, "float")
    tx.run_tool(tool, [src, "--fill:color=100000,90000,80000", "4x4+60+10", "-o", src])
    info = tx.tool_info(tool)
    peak = tx.peak(src, tool, info.linear_rec709, "ACEScg")
    assert peak > 65504
    kind = tx.output_type("hdri", tx.probe(src, tool), peak)
    r = tx.Recipe((src,), tmp_path / "out/h.exr", "hdri", info.linear_rec709, "ACEScg", kind)
    tx.process(r, tool, info.linear_rec709)
    assert tx.probe(r.output, tool).format == "float"
    assert tx.peak(r.output, tool) > 65504


@real
def test_real_spec_gloss(tool: Path, tmp_path: Path) -> None:
    info = tx.tool_info(tool)
    diff = make(tool, tmp_path / "d.png", "constant:color=0.8,0.2,0.2", "32x32", 3, "uint8")
    spec = make(tool, tmp_path / "s.png", "constant:color=0.95,0.8,0.4", "32x32", 3, "uint8")
    metal = tx.Recipe(
        (spec,),
        tmp_path / "m.tx",
        "metalness",
        info.srgb_texture,
        "raw",
        "uint8",
        metal_threshold=0.2,
    )
    tx.process(metal, tool, info.linear_rec709)
    assert tx.peak(metal.output, tool) == pytest.approx(1.0, abs=0.01)  # a metal
    base = tx.Recipe(
        (diff, spec),
        tmp_path / "b.exr",
        "basecolor",
        info.srgb_texture,
        "ACEScg",
        "half",
        metal_threshold=0.2,
    )
    tx.process(base, tool, info.linear_rec709)
    assert tx.probe(base.output, tool).format == "half"


@real
def test_real_failure_is_a_scheinwerk_error(tool: Path, tmp_path: Path) -> None:
    r = tx.Recipe(
        (tmp_path / "missing.png",), tmp_path / "o.tx", "roughness", "raw", "raw", "uint8"
    )
    with pytest.raises(ScheinwerkError, match="missing.png"):
        tx.process(r, tool, "")


@real
def test_real_thumbnail(tool: Path, tmp_path: Path) -> None:
    info = tx.tool_info(tool)
    src = make(tool, tmp_path / "w.exr", "constant:color=0.2,0.3,0.4", "1200x400", 3, "half")
    out = tmp_path / "thumb.jpg"
    tx.thumbnail(src, out, tool, "ACEScg", info.preview_view(), (512, 512))  # fits in
    assert tx.probe(out, tool) == tx.ImageInfo(512, 171, 3, "uint8")
