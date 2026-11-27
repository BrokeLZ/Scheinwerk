"""Detection: dropped files -> ingest plans (spec §17.5, spike/l2/detection-proposal.md)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scheinwerk.core.textures import ImageInfo
from scheinwerk.library import detect as d
from scheinwerk.library.root import Library
from tests.conftest import touch
from tests.library.conftest import make_item

SRGB, LIN = "sRGB - Texture", "Linear Rec.709 (sRGB)"
RGB8 = ImageInfo(4096, 4096, 3, "uint8")


class Probe:
    """Fake image probe: per file name, default 4k RGB 8-bit."""

    def __init__(self, **infos: ImageInfo) -> None:
        self.infos = infos

    def __call__(self, path: Path) -> ImageInfo:
        return self.infos.get(path.name, RGB8)


def run(paths, probe=None, library=None, **kw) -> d.Detected:
    return d.detect([Path(p) for p in paths], probe or Probe(), SRGB, LIN, library=library, **kw)


def files(folder: Path, *names: str) -> list[Path]:
    return [touch(folder / n) for n in names]


def roles(entry: dict, variant: str = "main") -> dict[str, str]:
    return {Path(f["path"]).name: f["role"] for f in entry["variants"][variant]}


# --- names --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stem", "tokens"),
    [
        ("Metal032_4K-JPG_NormalGL", ["Metal032", "4K", "JPG", "Normal", "GL"]),
        ("rusty_metal_02_nor_gl_4k", ["rusty", "metal", "02", "nor", "gl", "4k"]),
        ("Aset_rock_4K_AmbientOcclusion", ["Aset", "rock", "4K", "Ambient", "Occlusion"]),
        ("oak_Var3_LOD0_Albedo", ["oak", "Var3", "LOD0", "Albedo"]),
        ("my wall.v2", ["my", "wall", "v2"]),
    ],
)
def test_tokens(stem: str, tokens: list[str]) -> None:
    assert d.tokens(stem) == tokens


@pytest.mark.parametrize(
    ("stem", "role", "base", "convention"),
    [
        ("Metal032_4K-JPG_Color", "basecolor", "metal032", None),
        ("Metal032_4K-JPG_NormalGL", "normal", "metal032", "gl"),
        ("Metal032_4K-JPG_NormalDX", "normal", "metal032", "dx"),
        ("Metal032_4K-JPG_Displacement", "height", "metal032", None),
        ("Metal032_4K-JPG_Roughness", "roughness", "metal032", None),
        ("Metal032_4K-JPG_Metalness", "metalness", "metal032", None),
        ("rusty_metal_02_diff_4k", "diffuse", "rusty_metal_02", None),  # Q1: the last role wins
        ("rusty_metal_02_metal_4k", "metalness", "rusty_metal_02", None),
        ("rusty_metal_02_nor_dx_4k", "normal", "rusty_metal_02", "dx"),
        ("rusty_metal_02_arm_4k", "arm", "rusty_metal_02", None),
        ("Aset_rock_4K_Albedo", "basecolor", "aset_rock", None),
        ("Aset_rock_4K_AmbientOcclusion", "ao", "aset_rock", None),
        ("wall_Base_Color", "basecolor", "wall", None),
        ("wall_BaseColor", "basecolor", "wall", None),
        ("wall_Gloss", "glossiness", "wall", None),
        ("wall_Specular", "specular", "wall", None),
        ("wall_Opacity", "opacity", "wall", None),
        ("wall_emissive", "emission", "wall", None),
        ("wall_ORM", "orm", "wall", None),
        ("wall_normal_opengl", "normal", "wall", "gl"),
        ("wall_normal_directx", "normal", "wall", "dx"),
        ("Aset_rock_4K_Cavity", None, "aset_rock_cavity", None),
        ("Metal032", None, "metal032", None),
        ("collection_photo", None, "collection_photo", None),  # `col` matches whole tokens only
        ("oak_Var3_LOD0_Albedo", "basecolor", "oak", None),
        ("kloppenheim_06_puresky_4k", None, "kloppenheim_06_puresky", None),
    ],
)
def test_parse_name(stem: str, role: str | None, base: str, convention: str | None) -> None:
    info = d.parse_name(stem)
    assert (info.role, info.base, info.convention) == (role, base, convention)


@pytest.mark.parametrize(
    ("stem", "variant"),
    [("oak_Var3_Albedo", "var03"), ("oak_variation12_Normal", "var12"), ("oak_Albedo", None)],
)
def test_variant_token(stem: str, variant: str | None) -> None:
    assert d.parse_name(stem).variant == variant


@pytest.mark.parametrize(
    ("stem", "name"),
    [
        ("Rusty_Metal_02_4K", "Rusty Metal 02"),
        ("rusty_metal_02", "Rusty Metal 02"),
        ("Metal032_4K-JPG", "Metal032"),
        ("kloppenheim_06_puresky_4k", "Kloppenheim 06 Puresky"),
        ("oak_Var3", "Oak"),
        ("brick", "Brick"),
    ],
)
def test_display_name(stem: str, name: str) -> None:
    assert d.display_name(stem) == name


# --- one folder -> entries ----------------------------------------------------------------


def test_ambientcg_folder(tmp_path: Path) -> None:
    folder = tmp_path / "Metal032_4K-JPG"
    files(
        folder,
        "Metal032_4K-JPG_Color.jpg",
        "Metal032_4K-JPG_NormalGL.jpg",
        "Metal032_4K-JPG_NormalDX.jpg",
        "Metal032_4K-JPG_Roughness.jpg",
        "Metal032_4K-JPG_Metalness.jpg",
        "Metal032_4K-JPG_Displacement.jpg",
        "Metal032.png",
        "Metal032_4K-JPG.usdc",
        "Metal032_4K-JPG.mtlx",
    )
    result = run([folder])
    [entry] = result.entries
    assert [Path(u["path"]).name for u in result.unused] == ["Metal032_4K-JPG.usdc"]  # a model
    assert entry["type"] == "texture_set" and entry["name"] == "Metal032"
    assert entry["workflow"] == "metal_rough" and entry["status"] == "ready"
    assert roles(entry) == {
        "Metal032_4K-JPG_Color.jpg": "basecolor",
        "Metal032_4K-JPG_NormalGL.jpg": "normal",
        "Metal032_4K-JPG_Roughness.jpg": "roughness",
        "Metal032_4K-JPG_Metalness.jpg": "metalness",
        "Metal032_4K-JPG_Displacement.jpg": "height",
    }
    skipped = {Path(p).name for p in entry["skipped"]}  # Q3: DX skipped when GL is there
    assert skipped == {"Metal032_4K-JPG_NormalDX.jpg", "Metal032.png", "Metal032_4K-JPG.mtlx"}


def test_colour_spaces_flags_and_defaults(tmp_path: Path) -> None:
    folder = tmp_path / "set"
    files(folder, "wall_Color.png", "wall_Normal_DX.png", "wall_Rough.png")
    probe = Probe(**{"wall_Color.png": RGB8})
    [entry] = run([folder], probe).entries
    by_name = {Path(f["path"]).name: f for f in entry["variants"]["main"]}
    assert by_name["wall_Color.png"]["color_space"] == SRGB
    assert by_name["wall_Normal_DX.png"] | {"path": ""} == {
        "path": "",
        "role": "normal",
        "color_space": "raw",
        "flip_green": True,
        "invert": False,
        "channel": None,
    }
    assert by_name["wall_Rough.png"]["color_space"] == "raw"


def test_float_colour_maps_are_linear(tmp_path: Path) -> None:
    folder = tmp_path / "set"
    files(folder, "wall_Color.exr", "wall_Normal.png")
    [entry] = run([folder], Probe(**{"wall_Color.exr": ImageInfo(64, 64, 3, "half")})).entries
    assert entry["variants"]["main"][0]["color_space"] == LIN


def test_normal_without_convention_assumes_gl_and_says_so(tmp_path: Path) -> None:
    folder = tmp_path / "Aset_rock"
    files(folder, "Aset_rock_4K_Albedo.jpg", "Aset_rock_4K_Normal.jpg", "Aset_rock_4K_Cavity.jpg")
    [entry] = run([folder]).entries
    assert entry["status"] == "ready"
    assert any("OpenGL" in m for m in entry["messages"])
    assert {Path(p).name for p in entry["skipped"]} == {"Aset_rock_4K_Cavity.jpg"}


def test_poly_haven_diff_is_basecolor_and_arm_fills_the_gaps(tmp_path: Path) -> None:
    # Q4: diffuse with roughness is metal/rough; Q2: arm unpacks only missing roles
    folder = tmp_path / "rusty"
    files(
        folder,
        "rusty_metal_02_diff_4k.jpg",
        "rusty_metal_02_rough_4k.jpg",
        "rusty_metal_02_nor_gl_4k.exr",
        "rusty_metal_02_arm_4k.jpg",
    )
    [entry] = run([folder]).entries
    assert entry["name"] == "Rusty Metal 02" and entry["workflow"] == "metal_rough"
    got = {(Path(f["path"]).name, f["role"], f["channel"]) for f in entry["variants"]["main"]}
    assert got == {
        ("rusty_metal_02_diff_4k.jpg", "basecolor", None),
        ("rusty_metal_02_rough_4k.jpg", "roughness", None),
        ("rusty_metal_02_nor_gl_4k.exr", "normal", None),
        ("rusty_metal_02_arm_4k.jpg", "ao", 0),
        ("rusty_metal_02_arm_4k.jpg", "metalness", 2),
    }


def test_packed_map_not_needed_is_skipped(tmp_path: Path) -> None:
    folder = tmp_path / "w"
    files(folder, "w_Color.png", "w_AO.png", "w_Roughness.png", "w_Metallic.png", "w_ORM.png")
    [entry] = run([folder]).entries
    assert {Path(p).name for p in entry["skipped"]} == {"w_ORM.png"}


@pytest.mark.parametrize(
    ("names", "workflow", "expected"),
    [
        (
            ["w_diffuse.png", "w_spec.png", "w_gloss.png", "w_normal.png"],
            "spec_gloss",
            {
                "w_diffuse.png": "diffuse",
                "w_spec.png": "specular",
                "w_gloss.png": "glossiness",
                "w_normal.png": "normal",
            },
        ),
        (
            ["w_diffuse.png", "w_spec.png", "w_roughness.png"],
            "metal_rough",
            {
                "w_diffuse.png": "basecolor",
                "w_spec.png": "specular_level",
                "w_roughness.png": "roughness",
            },
        ),
        (
            ["w_albedo.png", "w_gloss.png", "w_normal.png"],
            "spec_gloss",
            {"w_albedo.png": "basecolor", "w_gloss.png": "glossiness", "w_normal.png": "normal"},
        ),
        (
            ["w_basecolor.png", "w_gloss.png", "w_metal.png"],
            "metal_rough",
            {
                "w_basecolor.png": "basecolor",
                "w_gloss.png": "roughness",
                "w_metal.png": "metalness",
            },
        ),
    ],
)
def test_workflow(tmp_path: Path, names, workflow, expected) -> None:
    folder = tmp_path / "w"
    files(folder, *names)
    [entry] = run([folder]).entries
    assert entry["workflow"] == workflow
    assert roles(entry) == expected
    if workflow == "spec_gloss":
        assert entry["status"] == "warning" and entry["metal_threshold"] == 0.2
        assert any("spec/gloss" in m for m in entry["messages"])
    else:
        assert entry["metal_threshold"] is None
    gloss = [f for f in entry["variants"]["main"] if Path(f["path"]).stem == "w_gloss"]
    if gloss and workflow == "metal_rough":
        assert gloss[0]["invert"] is True  # gloss -> roughness


def test_highest_resolution_wins_for_the_same_role(tmp_path: Path) -> None:
    folder = tmp_path / "w"
    files(folder, "w_Color_2k.png", "w_Color_4k.png", "w_Normal_4k.png")
    [entry] = run([folder]).entries
    assert roles(entry) == {"w_Color_4k.png": "basecolor", "w_Normal_4k.png": "normal"}
    assert {Path(p).name for p in entry["skipped"]} == {"w_Color_2k.png"}


def test_hdri_and_texture(tmp_path: Path) -> None:
    folder = tmp_path / "skies"
    files(
        folder, "kloppenheim_06_4k.exr", "kloppenheim_06_puresky_4k.exr", "sky_8k.jpg", "brick.png"
    )
    probe = Probe(
        **{
            "kloppenheim_06_4k.exr": ImageInfo(8192, 4096, 3, "float"),
            "kloppenheim_06_puresky_4k.exr": ImageInfo(8192, 4096, 3, "half"),
            "sky_8k.jpg": ImageInfo(8192, 4096, 3, "uint8"),
            "brick.png": ImageInfo(512, 512, 1, "uint8"),
        }
    )
    entries = {e["name"]: e for e in run([folder], probe).entries}
    assert {n: (e["type"], roles(e)) for n, e in entries.items()} == {
        "Kloppenheim 06": ("hdri", {"kloppenheim_06_4k.exr": "hdri"}),
        "Kloppenheim 06 Puresky": ("hdri", {"kloppenheim_06_puresky_4k.exr": "hdri"}),
        "Sky": ("texture", {"sky_8k.jpg": "color"}),
        "Brick": ("texture", {"brick.png": "data"}),
    }
    assert entries["Kloppenheim 06"]["variants"]["main"][0]["color_space"] == LIN
    assert entries["Sky"]["variants"]["main"][0]["color_space"] == SRGB


def test_megascans_variant_folders(tmp_path: Path) -> None:
    root = tmp_path / "plant"
    for v in ("Var1", "Var2"):
        files(root / v, f"plant_{v}_Albedo.png", f"plant_{v}_Normal.png")
    [entry] = run([root]).entries
    assert entry["type"] == "texture_set" and entry["name"] == "Plant"
    assert sorted(entry["variants"]) == ["var01", "var02"]
    assert roles(entry, "var02") == {
        "plant_Var2_Albedo.png": "basecolor",
        "plant_Var2_Normal.png": "normal",
    }


def test_variant_tokens_in_names_make_one_texture(tmp_path: Path) -> None:
    files(tmp_path / "f", "oak_Var1_Albedo.png", "oak_Var2_Albedo.png")
    [entry] = run([tmp_path / "f"]).entries
    assert entry["type"] == "texture" and sorted(entry["variants"]) == ["var01", "var02"]


def test_udim_tiles_are_one_map(tmp_path: Path) -> None:
    folder = tmp_path / "u"
    files(
        folder,
        "skin_Color.1001.png",
        "skin_Color.1002.png",
        "skin_Normal.1001.png",
        "skin_Normal.1002.png",
    )
    [entry] = run([folder]).entries
    paths = sorted(Path(f["path"]).name for f in entry["variants"]["main"])
    assert paths == ["skin_Color.<UDIM>.png", "skin_Normal.<UDIM>.png"]


def test_twenty_sets_in_one_folder_and_in_subfolders(tmp_path: Path) -> None:
    for i in range(3):
        files(tmp_path / "loose", f"set{i}_Color.png", f"set{i}_Normal.png")
        files(tmp_path / "nested" / f"set{i}", f"set{i}_Color.png", f"set{i}_Normal.png")
    assert len(run([tmp_path / "loose"]).entries) == 3
    assert len(run([tmp_path / "nested"]).entries) == 3


def test_loose_files_and_unused(tmp_path: Path) -> None:
    a, b = files(tmp_path, "w_Color.png", "w_Normal.png")
    photo, notes, model = files(tmp_path, "photo.webp", "notes.txt", "tree.fbx")
    result = run([a, b, photo, notes, model])
    [entry] = result.entries
    assert entry["type"] == "texture_set"
    assert [Path(p).name for p in entry["skipped"]] == ["notes.txt"]  # dropped with the set
    unused = {Path(u["path"]).name: u["reason"] for u in result.unused}
    assert unused == {
        "photo.webp": "unsupported image format",
        "tree.fbx": "models are ingested from step L4 on",
    }


def test_an_hdri_next_to_a_set_is_its_own_entry(tmp_path: Path) -> None:
    files(tmp_path, "w_Color.png", "w_Normal.png", "sky.exr")
    result = run([tmp_path], Probe(**{"sky.exr": ImageInfo(64, 32, 3, "float")}))
    assert sorted(e["type"] for e in result.entries) == ["hdri", "texture_set"]


def test_two_sets_and_a_stray_image(tmp_path: Path) -> None:
    files(tmp_path, "a_Color.png", "a_Normal.png", "b_Color.png", "b_Normal.png", "preview.jpg")
    result = run([tmp_path])
    assert len(result.entries) == 2
    assert [Path(u["path"]).name for u in result.unused] == ["preview.jpg"]


def test_zip(tmp_path: Path) -> None:
    archive = tmp_path / "Metal032_4K-JPG.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Metal032_4K-JPG_Color.jpg", b"")
        z.writestr("Metal032_4K-JPG_NormalGL.jpg", b"")
    [entry] = run([archive], unzip_dir=tmp_path / "unzipped").entries
    assert entry["name"] == "Metal032"
    assert all(
        (tmp_path / "unzipped") in Path(f["path"]).parents for f in entry["variants"]["main"]
    )


def test_same_files_ingested_before_warn(tmp_path: Path, lib: Library) -> None:
    folder = tmp_path / "w"
    files(folder, "w_Color.png", "w_Normal.png")
    (folder / "w_Color.png").write_bytes(b"pixels")
    sha = d.sha256(folder / "w_Color.png")
    make_item(
        lib,
        "texture_set",
        "wall_a1b2c3",
        {1: {"variants": {"main": {"version": 1}}, "sha256": {"source/w_Color.png": sha}}},
    )
    [entry] = run([folder], library=lib).entries
    assert entry["status"] == "warning"
    assert any("wall_a1b2c3" in m for m in entry["messages"])


def test_plan_shape(tmp_path: Path) -> None:
    files(tmp_path / "w", "w_Color.png", "w_Normal_gl.png")
    [entry] = run([tmp_path / "w"]).entries
    assert set(entry) == {
        "schema",
        "type",
        "name",
        "target",
        "variants",
        "skipped",
        "workflow",
        "metal_threshold",
        "size_m",
        "displacement",
        "scale",
        "categories",
        "tags",
        "credits",
        "license",
        "source_url",
        "status",
        "messages",
    }
    assert entry["target"] == {"item": None, "variant": None}
    assert entry["schema"] == 1 and entry["scale"] is None
