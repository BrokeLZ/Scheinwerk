"""Running ingest plans and rebuilds (spec §17.3–§17.5, §17.10).

FakeTools stands in for hoiiotool (it writes placeholder outputs and records what it was asked),
so the layout and version.json are checked everywhere; one test runs the real tool.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.textures import ImageInfo, Recipe, ToolInfo
from scheinwerk.core.tools import find_tool
from scheinwerk.library import detect as d
from scheinwerk.library.ingest import HoiioTools, ingest, rebuild
from scheinwerk.library.items import find_item
from scheinwerk.library.root import Library
from tests.conftest import touch

SRGB, LIN = "sRGB - Texture", "Linear Rec.709 (sRGB)"
RGB8 = ImageInfo(2048, 2048, 3, "uint8")


class FakeTools:
    def __init__(
        self,
        infos: dict | None = None,
        peak: float = 10.0,
        fail: str = "",
        fail_thumbs: bool = False,
    ) -> None:
        self.info = ToolInfo(
            "2.5.18.0",
            "studio-config.ocio",
            ["ACEScg", SRGB, LIN, "Raw"],
            {"sRGB - Display": ["Un-tone-mapped", "ACES 1.0 - SDR Video"]},
            "sRGB - Display",
        )
        self.infos, self.peak_value, self.fail, self.fail_thumbs = (
            infos or {},
            peak,
            fail,
            fail_thumbs,
        )
        self.recipes: list[Recipe] = []
        self.thumbs: list[tuple] = []

    def probe(self, path: Path) -> ImageInfo:
        return self.infos.get(path.name, RGB8)

    def peak(self, path: Path, from_space: str, to_space: str) -> float:
        return self.peak_value

    def process(self, recipe: Recipe) -> None:
        assert all(s.is_file() for s in recipe.sources), recipe.sources
        if self.fail and self.fail in recipe.output.name:
            raise ScheinwerkError("hoiiotool failed (1): boom")
        recipe.output.parent.mkdir(parents=True, exist_ok=True)
        recipe.output.write_bytes(b"map")
        self.recipes.append(recipe)

    def thumbnail(self, src, out, space, view, box, exact=False) -> None:
        if self.fail_thumbs:
            raise ScheinwerkError("hoiiotool failed (1): no thumbs")
        out.write_bytes(b"jpg")
        self.thumbs.append((src.name, out.name, space, view, box, exact))


def plan_of(paths: list[Path], tools: FakeTools | None = None, **changes) -> dict:
    tools = tools or FakeTools()
    [entry] = d.detect(paths, tools.probe, SRGB, LIN).entries
    entry.update(changes)
    return entry


def info(version) -> dict:
    return json.loads((version.path / "version.json").read_text(encoding="utf-8"))


@pytest.fixture
def wall(tmp_path: Path) -> Path:
    folder = tmp_path / "dl" / "wall"
    for name in ("wall_Color_4k.png", "wall_NormalDX_4k.png", "wall_Rough_4k.png"):
        touch(folder / name, name.encode())
    return folder


# --- a new texture set --------------------------------------------------------------------


def test_new_texture_set(lib: Library, wall: Path) -> None:
    tools = FakeTools()
    plan = plan_of(
        [wall],
        tools,
        categories=["Stone/Wall"],
        tags=["Old"],
        credits="ambientCG",
        license="CC0",
        size_m=[2.0, 2.0],
    )
    version = ingest(lib, plan, tools, comment="first")
    item = version.item
    assert item.type == "texture_set" and item.id.startswith("wall_") and version.number == 1
    meta = item.meta
    assert (meta["name"], meta["categories"], meta["tags"]) == ("Wall", ["stone/wall"], ["old"])
    assert (meta["credits"], meta["license"], meta["size_m"]) == ("ambientCG", "CC0", [2.0, 2.0])
    v = "v001"
    assert sorted(p.name for p in (version.path / "source").iterdir()) == [
        "wall_Color_4k.png",
        "wall_NormalDX_4k.png",
        "wall_Rough_4k.png",
    ]
    assert sorted(p.name for p in (version.path / "textures").iterdir()) == [
        f"{item.id}_main_basecolor_{v}.exr",
        f"{item.id}_main_normal_{v}.tx",
        f"{item.id}_main_roughness_{v}.tx",
    ]
    data = info(version)
    assert data["origin"] == "ingest" and data["comment"] == "first"
    assert data["variants"] == {"main": {"version": 1}}
    assert data["ocio"] == {"config": "studio-config.ocio", "working_space": "ACEScg"}
    assert data["tools"] == {"hoiiotool": "2.5.18.0"}
    assert data["workflow"] == "metal_rough" and data["metal_threshold"] is None
    assert data["resolution"] == [2048, 2048] and data["udim"] is False
    assert data["scale"] is None
    entries = {e["role"]: e for e in data["files"]}
    assert entries["basecolor"] == {
        "variant": "main",
        "source": ["source/wall_Color_4k.png"],
        "output": f"textures/{item.id}_main_basecolor_{v}.exr",
        "role": "basecolor",
        "from_space": SRGB,
        "to_space": "ACEScg",
        "data_type": "half",
        "flip_green": False,
        "invert": False,
    }
    assert entries["normal"]["flip_green"] is True and entries["normal"]["to_space"] == "raw"
    assert entries["roughness"]["data_type"] == "uint8"
    assert set(data["sha256"]) == {
        "source/wall_Color_4k.png",
        "source/wall_NormalDX_4k.png",
        "source/wall_Rough_4k.png",
    }
    assert data["sha256"]["source/wall_Color_4k.png"] == d.sha256(wall / "wall_Color_4k.png")
    assert tools.thumbs == []  # texture-set previews are Karma renders (step L4)
    assert (wall / "wall_Color_4k.png").read_bytes() == b"wall_Color_4k.png"  # untouched


def test_paths_in_version_json_are_relative(lib: Library, wall: Path) -> None:
    version = ingest(lib, plan_of([wall]), FakeTools())
    text = (version.path / "version.json").read_text(encoding="utf-8")
    assert str(wall) not in text and str(lib.root) not in text


def test_spec_gloss_set(lib: Library, tmp_path: Path) -> None:
    folder = tmp_path / "sg"
    for n in ("w_diffuse.png", "w_spec.png", "w_gloss.png", "w_normal_gl.png"):
        touch(folder / n)
    tools = FakeTools()
    version = ingest(lib, plan_of([folder], tools, metal_threshold=0.3), tools)
    by_role = {r.role: r for r in tools.recipes}
    assert [s.name for s in by_role["basecolor"].sources] == ["w_diffuse.png", "w_spec.png"]
    assert by_role["basecolor"].metal_threshold == 0.3
    assert [s.name for s in by_role["metalness"].sources] == ["w_spec.png"]
    assert by_role["metalness"].from_space == SRGB and by_role["metalness"].to_space == "raw"
    assert by_role["roughness"].invert and [s.name for s in by_role["roughness"].sources] == [
        "w_gloss.png"
    ]
    assert set(by_role) == {"basecolor", "metalness", "roughness", "normal"}
    data = info(version)
    assert data["workflow"] == "spec_gloss" and data["metal_threshold"] == 0.3


def test_packed_channels(lib: Library, tmp_path: Path) -> None:
    folder = tmp_path / "ph"
    for n in ("rusty_diff_4k.jpg", "rusty_nor_gl_4k.png", "rusty_arm_4k.jpg"):
        touch(folder / n)
    tools = FakeTools()
    version = ingest(lib, plan_of([folder], tools), tools)
    packed = {e["role"]: e["channel"] for e in info(version)["files"] if "channel" in e}
    assert packed == {"ao": 0, "roughness": 1, "metalness": 2}
    assert sorted(p.name for p in (version.path / "source").iterdir()) == [
        "rusty_arm_4k.jpg",
        "rusty_diff_4k.jpg",
        "rusty_nor_gl_4k.png",
    ]  # copied once


# --- hdri and texture ---------------------------------------------------------------------


@pytest.mark.parametrize(("peak", "dtype"), [(3000.0, "half"), (95000.0, "float")])
def test_hdri(lib: Library, tmp_path: Path, peak: float, dtype: str) -> None:
    src = touch(tmp_path / "kloppenheim_06_4k.exr")
    tools = FakeTools({src.name: ImageInfo(8192, 4096, 3, "float")}, peak=peak)
    version = ingest(lib, plan_of([src], tools), tools)
    item = version.item
    assert item.type == "hdri" and item.name == "Kloppenheim 06"
    [entry] = info(version)["files"]
    assert entry["output"] == f"{item.id}_main_v001.exr" and entry["data_type"] == dtype
    assert entry["from_space"] == LIN
    assert tools.thumbs == [
        (
            f"{item.id}_main_v001.exr",
            "thumb_main.jpg",
            "ACEScg",
            ("sRGB - Display", "ACES 1.0 - SDR Video"),
            (1024, 512),
            True,
        )
    ]


def test_data_texture(lib: Library, tmp_path: Path) -> None:
    src = touch(tmp_path / "brick.png")
    tools = FakeTools({"brick.png": ImageInfo(512, 512, 1, "uint16")})
    version = ingest(lib, plan_of([src], tools), tools)
    [entry] = info(version)["files"]
    assert entry["output"] == f"{version.item.id}_main_v001.tx"
    assert entry["role"] == "data" and entry["data_type"] == "uint16"
    assert tools.thumbs[0][2] == "raw" and tools.thumbs[0][4:] == ((512, 512), False)


def test_udim_texture(lib: Library, tmp_path: Path) -> None:
    for t in (1001, 1002):
        touch(tmp_path / "u" / f"skin.{t}.png")
    tools = FakeTools()
    version = ingest(lib, plan_of([tmp_path / "u"], tools), tools)
    item_id = version.item.id
    assert sorted(p.name for p in version.path.glob("*.exr")) == [
        f"{item_id}_main_v001.1001.exr",
        f"{item_id}_main_v001.1002.exr",
    ]
    [entry] = info(version)["files"]
    assert entry["source"] == ["source/skin.<UDIM>.png"]
    assert entry["output"] == f"{item_id}_main_v001.<UDIM>.exr"
    assert info(version)["udim"] is True


# --- variants and existing items ----------------------------------------------------------


def test_variants_get_their_own_source_folders(lib: Library, tmp_path: Path) -> None:
    for v in ("Var1", "Var2"):
        touch(tmp_path / "plant" / v / "plant_Albedo.png")
        touch(tmp_path / "plant" / v / "plant_Normal_gl.png")
    version = ingest(lib, plan_of([tmp_path / "plant"]), FakeTools())
    assert sorted(p.name for p in (version.path / "source").iterdir()) == ["var01", "var02"]
    assert info(version)["variants"] == {"var01": {"version": 1}, "var02": {"version": 1}}


def test_add_a_variant_keeps_the_others(lib: Library, wall: Path, tmp_path: Path) -> None:
    first = ingest(lib, plan_of([wall]), FakeTools())
    winter = tmp_path / "winter"
    for n in ("snow_Color.png", "snow_Normal_gl.png"):
        touch(winter / n)
    plan = plan_of([winter], target={"item": first.item.id, "variant": "winter"})
    second = ingest(lib, plan, FakeTools())
    assert second.item == first.item and second.number == 2
    assert info(second)["variants"] == {"main": {"version": 1}, "winter": {"version": 2}}
    assert {e["variant"] for e in info(second)["files"]} == {"winter"}
    assert first.item.meta["name"] == "Wall"  # the new files' name doesn't rename the item


def test_new_version_of_a_variant(lib: Library, wall: Path) -> None:
    first = ingest(lib, plan_of([wall]), FakeTools())
    second = ingest(
        lib, plan_of([wall], target={"item": first.item.id, "variant": None}), FakeTools()
    )
    assert info(second)["variants"] == {"main": {"version": 2}}


def test_target_type_must_match(lib: Library, wall: Path, tmp_path: Path) -> None:
    hdri = touch(tmp_path / "sky.exr")
    tools = FakeTools({"sky.exr": ImageInfo(64, 32, 3, "float")})
    sky = ingest(lib, plan_of([hdri], tools), tools)
    with pytest.raises(ScheinwerkError, match="hdri"):
        ingest(lib, plan_of([wall], target={"item": sky.item.id, "variant": None}), FakeTools())


# --- refusals and failures ----------------------------------------------------------------


def test_needs_input_is_refused_before_anything_is_written(lib: Library, wall: Path) -> None:
    with pytest.raises(ScheinwerkError, match="needs input"):
        ingest(lib, plan_of([wall], status="needs_input", messages=["pick a role"]), FakeTools())
    assert lib.items() == []


def test_missing_files_are_refused_before_anything_is_written(lib: Library, wall: Path) -> None:
    plan = plan_of([wall])
    (wall / "wall_Rough_4k.png").unlink()
    with pytest.raises(ScheinwerkError, match="wall_Rough_4k.png"):
        ingest(lib, plan, FakeTools())
    assert lib.items() == []


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"type": "model"}, "step L4"),
        ({"variants": {}}, "no files"),
        ({"variants": {"Main": []}}, "variant"),
        ({"schema": 2}, "schema"),
    ],
)
def test_bad_plans(lib: Library, wall: Path, change: dict, error: str) -> None:
    with pytest.raises(ScheinwerkError, match=error):
        ingest(lib, plan_of([wall], **change), FakeTools())


def test_bad_role_in_plan(lib: Library, wall: Path) -> None:
    plan = plan_of([wall])
    plan["variants"]["main"][0]["role"] = "bark"
    with pytest.raises(ScheinwerkError, match="bark"):
        ingest(lib, plan, FakeTools())


def test_failed_map_leaves_an_incomplete_version(lib: Library, wall: Path) -> None:
    with pytest.raises(ScheinwerkError, match="boom"):
        ingest(lib, plan_of([wall]), FakeTools(fail="roughness"))
    [item] = lib.items()
    assert item.latest() is None and item.versions()[0].finalized is False


def test_failed_thumbnail_does_not_block(lib: Library, tmp_path: Path) -> None:
    src = touch(tmp_path / "brick.png")
    version = ingest(lib, plan_of([src]), FakeTools(fail_thumbs=True))
    assert version.finalized and not (version.path / "thumb_main.jpg").exists()


# --- rebuild ------------------------------------------------------------------------------


def spec_gloss_item(lib: Library, tmp_path: Path):
    folder = tmp_path / "sg"
    for n in ("w_diffuse.png", "w_spec.png", "w_gloss.png"):
        touch(folder / n)
    return ingest(lib, plan_of([folder]), FakeTools())


def test_rebuild_with_another_threshold(lib: Library, tmp_path: Path) -> None:
    first = spec_gloss_item(lib, tmp_path)
    tools = FakeTools()
    second = rebuild(first.item, tools, metal_threshold=0.5)
    assert second.number == 2
    assert not (second.path / "source").exists()  # nothing copied
    data = info(second)
    assert data["origin"] == "rebuild" and data["source_version"] == 1
    assert data["metal_threshold"] == 0.5
    assert data["variants"] == {"main": {"version": 2}}
    base = next(e for e in data["files"] if e["role"] == "basecolor")
    assert base["source"] == ["../v001/source/w_diffuse.png", "../v001/source/w_spec.png"]
    assert base["output"].endswith("_main_basecolor_v002.exr")
    assert {r.metal_threshold for r in tools.recipes if r.role in ("basecolor", "metalness")} == {
        0.5
    }
    third = rebuild(first.item, FakeTools())  # a rebuild of a rebuild finds the originals
    assert info(third)["source_version"] == 1
    assert next(e for e in info(third)["files"] if e["role"] == "metalness")["source"] == [
        "../v001/source/w_spec.png"
    ]


def test_rebuild_keeps_variants_held_elsewhere(lib: Library, wall: Path, tmp_path: Path) -> None:
    first = ingest(lib, plan_of([wall]), FakeTools())
    touch(tmp_path / "snow" / "snow_Color.png")
    touch(tmp_path / "snow" / "snow_Normal_gl.png")
    ingest(
        lib,
        plan_of([tmp_path / "snow"], target={"item": first.item.id, "variant": "winter"}),
        FakeTools(),
    )
    third = rebuild(first.item, FakeTools())  # rebuilds v002, which holds only `winter`
    assert info(third)["variants"] == {"main": {"version": 1}, "winter": {"version": 3}}


def test_rebuild_an_older_version(lib: Library, wall: Path) -> None:
    first = ingest(lib, plan_of([wall]), FakeTools())
    ingest(lib, plan_of([wall], target={"item": first.item.id, "variant": None}), FakeTools())
    third = rebuild(first.item, FakeTools(), version=1)
    assert info(third)["source_version"] == 1 and third.number == 3


def test_rebuild_needs_a_finalized_version_with_files(lib: Library, wall: Path) -> None:
    first = ingest(lib, plan_of([wall]), FakeTools())
    first.item.next_version_dir()
    with pytest.raises(ScheinwerkError, match="incomplete"):
        rebuild(first.item, FakeTools(), version=2)


# --- the real tool ------------------------------------------------------------------------


def _tool() -> Path | None:
    try:
        return find_tool("hoiiotool")
    except Exception:  # noqa: BLE001
        return None


@pytest.mark.skipif(_tool() is None, reason="hoiiotool not installed")
def test_real_ingest(lib: Library, tmp_path: Path) -> None:
    tools = HoiioTools(_tool())
    folder = tmp_path / "rusty"
    folder.mkdir()
    for name, pattern, ch, fmt in (
        ("rusty_metal_02_diff_1k.png", "checker:color1=0.6,0.3,0.1:color2=0.3,0.3,0.3", 3, "uint8"),
        ("rusty_metal_02_nor_dx_1k.png", "constant:color=0.5,0.6,1", 3, "uint8"),
        ("rusty_metal_02_arm_1k.png", "constant:color=1,0.5,0", 3, "uint8"),
    ):
        tools.run(["--pattern", pattern, "64x64", ch, "-d", fmt, "-o", folder / name])
    [plan] = d.detect(
        [folder], tools.probe, tools.info.srgb_texture, tools.info.linear_rec709
    ).entries
    version = ingest(lib, plan, tools)
    textures = version.path / "textures"
    names = sorted(p.name for p in textures.iterdir())
    item_id = version.item.id
    assert names == sorted(
        f"{item_id}_main_{r}_v001.{x}"
        for r, x in (
            ("basecolor", "exr"),
            ("normal", "tx"),
            ("ao", "tx"),
            ("roughness", "tx"),
            ("metalness", "tx"),
        )
    )
    assert tools.probe(textures / f"{item_id}_main_basecolor_v001.exr").format == "half"
    rough = tools.probe(textures / f"{item_id}_main_roughness_v001.tx")
    assert (rough.channels, rough.format) == (1, "uint8")
    assert find_item(lib, "Rusty Metal 02") == version.item
    shutil.rmtree(folder)  # the library holds its own copies
    assert (version.path / "source" / "rusty_metal_02_diff_1k.png").is_file()
