"""Path -> context parsing and its inverse (spec §6).

The `project` fixture only writes scheinwerk.json, so every path below does not
exist on disk. That covers rule §6.2.8 (parsing works for paths that don't exist yet).

Cases marked PROPOSED fill a gap in the spec and need sign-off.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from scheinwerk.core.context import Context
from scheinwerk.core.errors import ParseError

BLANK = {
    "category": None,
    "sequence": None,
    "dept": None,
    "task": None,
    "area": None,
    "product": None,
    "usd": False,
    "version": None,
    "ext": None,
}


def make(root: Path, **fields: object) -> Context:
    return Context(root=root, **{**BLANK, **fields})


A = {"entity_type": "asset", "entity": "hero"}
CA = {**A, "category": "char"}
SEQ = {"entity_type": "sequence", "entity": "sq010", "sequence": "sq010"}
SH = {"entity_type": "shot", "entity": "sq010_0010", "sequence": "sq010"}
MDL = {"dept": "mdl", "task": "main"}
LGT = {"dept": "lgt", "task": "main"}
PUB = {"area": "publish"}
USD = {"area": "publish", "usd": True}
MEDIA = {"area": "media"}

# Paths the core generates. Each must parse to the expected context, and
# context.path() must give back the exact same path (§6.2 round trip).
ROUND_TRIP = [
    # asset, no category
    ("assets/hero", A),
    ("assets/hero/mdl", {**A, "dept": "mdl"}),
    ("assets/hero/mdl/main", {**A, **MDL}),
    ("assets/hero/mdl/main/work", {**A, **MDL, "area": "work"}),
    ("assets/hero/mdl/main/cache", {**A, **MDL, "area": "cache"}),
    (
        "assets/hero/mdl/main/work/hero_mdl_main_v001.hip",
        {**A, **MDL, "area": "work", "version": 1, "ext": "hip"},
    ),
    (
        "assets/hero/mdl/blockout/work/hero_mdl_blockout_v002.blend",  # custom task
        {**A, "dept": "mdl", "task": "blockout", "area": "work", "version": 2, "ext": "blend"},
    ),
    ("assets/hero/publish", {**A, **PUB}),
    ("assets/hero/publish/pants_drape_base", {**A, **PUB, "product": "pants_drape_base"}),
    (
        "assets/hero/publish/pants_drape_base/v001",
        {**A, **PUB, "product": "pants_drape_base", "version": 1},
    ),
    ("assets/hero/publish/_usd", {**A, **USD}),
    ("assets/hero/publish/_usd/hero.usd", {**A, **USD, "ext": "usd"}),  # entry layer
    ("assets/hero/publish/_usd/asset", {**A, **USD, "product": "asset"}),
    ("assets/hero/publish/_usd/asset/asset.usd", {**A, **USD, "product": "asset", "ext": "usd"}),
    ("assets/hero/publish/_usd/asset/v003", {**A, **USD, "product": "asset", "version": 3}),
    ("assets/hero/media", {**A, **MEDIA}),
    ("assets/hero/media/turntable", {**A, **MEDIA, "product": "turntable"}),
    ("assets/hero/media/turntable/v002", {**A, **MEDIA, "product": "turntable", "version": 2}),
    # asset with category
    ("assets/char/hero", CA),
    (
        "assets/char/hero/mdl/main/work/hero_mdl_main_v012.hip",
        {**CA, **MDL, "area": "work", "version": 12, "ext": "hip"},
    ),
    ("assets/char/hero/publish/_usd/asset/v003", {**CA, **USD, "product": "asset", "version": 3}),
    (
        "assets/char/hero/media/turntable/v002",
        {**CA, **MEDIA, "product": "turntable", "version": 2},
    ),
    # sequence (_seq)
    ("shots/sq010/_seq", SEQ),
    (
        "shots/sq010/_seq/lgt/main/work/sq010_lgt_main_v007.hip",
        {**SEQ, **LGT, "area": "work", "version": 7, "ext": "hip"},
    ),
    ("shots/sq010/_seq/publish/cam/v001", {**SEQ, **PUB, "product": "cam", "version": 1}),
    ("shots/sq010/_seq/media/previz/v001", {**SEQ, **MEDIA, "product": "previz", "version": 1}),
    # shot
    ("shots/sq010/sq010_0010", SH),
    (
        "shots/sq010/sq010_0010/lgt/main/work/sq010_0010_lgt_main_v012.hip",
        {**SH, **LGT, "area": "work", "version": 12, "ext": "hip"},
    ),
    (
        "shots/sq010/sq010_0010/lgt/main/work/sq010_0010_lgt_main_v1000.hip",
        {**SH, **LGT, "area": "work", "version": 1000, "ext": "hip"},
    ),
    ("shots/sq010/sq010_0010/lgt/main/cache", {**SH, **LGT, "area": "cache"}),
    (
        "shots/sq010/sq010_0010/publish/fx_pyro/v002",
        {**SH, **PUB, "product": "fx_pyro", "version": 2},
    ),
    ("shots/sq010/sq010_0010/publish/_usd/sq010_0010.usd", {**SH, **USD, "ext": "usd"}),  # root
    (
        "shots/sq010/sq010_0010/publish/_usd/lgt/lgt.usd",
        {**SH, **USD, "product": "lgt", "ext": "usd"},
    ),
    ("shots/sq010/sq010_0010/publish/_usd/lgt/v004", {**SH, **USD, "product": "lgt", "version": 4}),
    (
        "shots/sq010/sq010_0010/media/render_beauty/v004",
        {**SH, **MEDIA, "product": "render_beauty", "version": 4},
    ),
    (
        "shots/sq010/sq010_0010/media/render_beauty/v1000",
        {**SH, **MEDIA, "product": "render_beauty", "version": 1000},
    ),
]


@pytest.mark.parametrize(("rel", "expected"), ROUND_TRIP, ids=[r for r, _ in ROUND_TRIP])
def test_parse(project: Path, rel: str, expected: dict) -> None:
    assert Context.from_path(project / rel) == make(project, **expected)


@pytest.mark.parametrize("rel", [r for r, _ in ROUND_TRIP])
def test_round_trip(project: Path, rel: str) -> None:
    path = project / rel
    assert Context.from_path(path).path() == path


# Paths that parse but whose exact filename a Context can't carry, so path()
# is not their inverse.
PARSE_ONLY = [
    # Files inside version folders: version from the folder, ext from the file.
    (
        "assets/hero/publish/_usd/asset/v003/hero_asset_v003.usd",
        {**A, **USD, "product": "asset", "version": 3, "ext": "usd"},
    ),
    (
        "shots/sq010/sq010_0010/media/render_beauty/v004/sq010_0010_render_beauty_v004.1001.exr",
        {**SH, **MEDIA, "product": "render_beauty", "version": 4, "ext": "exr"},
    ),
    # Filename is not trusted (§6.2.7): the folder says v001, the name says v009.
    (
        "assets/hero/publish/pants/v001/villain_pants_v009.abc",
        {**A, **PUB, "product": "pants", "version": 1, "ext": "abc"},
    ),
    # PROPOSED: ext is the last suffix only.
    (
        "shots/sq010/sq010_0010/publish/fx_pyro/v002/sq010_0010_fx_pyro_v002.1001.bgeo.sc",
        {**SH, **PUB, "product": "fx_pyro", "version": 2, "ext": "sc"},
    ),
    # PROPOSED: unmanaged files in work/ parse with version None (so "unmanaged" ==
    # `ctx.version is None`), ext from the file.
    (
        "assets/hero/mdl/main/work/villain_mdl_main_v003.hip",
        {**A, **MDL, "area": "work", "ext": "hip"},
    ),
    ("assets/hero/mdl/main/work/reference.jpg", {**A, **MDL, "area": "work", "ext": "jpg"}),
    # Readers accept v\d{3,}; path() would write v001.
    (
        "assets/hero/mdl/main/work/hero_mdl_main_v0001.hip",
        {**A, **MDL, "area": "work", "version": 1, "ext": "hip"},
    ),
    # cache/ is free-form: nothing below it is parsed.
    (
        "shots/sq010/sq010_0010/fx/main/cache/pyro/v003/pyro.1001.bgeo.sc",
        {**SH, "dept": "fx", "task": "main", "area": "cache"},
    ),
    # Unknown things are shown, not rejected: parse what is recognisable.
    ("assets/hero/publish/pants/latest/x.abc", {**A, **PUB, "product": "pants"}),
    ("assets/hero/publish/pants/v01", {**A, **PUB, "product": "pants"}),
    ("assets/hero/mdl/main/scratch/x.txt", {**A, **MDL}),
    # Custom department (not in the template) under a categorised asset.
    (
        "assets/char/hero/groom/main/work/hero_groom_main_v001.hip",
        {**CA, "dept": "groom", "task": "main", "area": "work", "version": 1, "ext": "hip"},
    ),
    # PROPOSED: shot names aren't validated while parsing (`sw doctor` reports them).
    (
        "shots/sq010/sq020_0010/lgt/main",
        {"entity_type": "shot", "entity": "sq020_0010", "sequence": "sq010", **LGT},
    ),
]


@pytest.mark.parametrize(("rel", "expected"), PARSE_ONLY, ids=[r for r, _ in PARSE_ONLY])
def test_parse_only(project: Path, rel: str, expected: dict) -> None:
    assert Context.from_path(project / rel) == make(project, **expected)


def test_file_in_version_folder_path_is_the_version_folder(project: Path) -> None:
    version_dir = project / "assets/hero/publish/_usd/asset/v003"
    assert Context.from_path(version_dir / "hero_asset_v003.usd").path() == version_dir


# --- §6.2.3 optional category -------------------------------------------------


@pytest.mark.parametrize("rel", ["assets/hero/entity.json", "assets/char/hero/entity.json"])
def test_entity_json_marks_the_asset(project: Path, rel: str) -> None:
    ctx = Context.from_path(project / rel)
    assert ctx.entity == "hero"
    assert ctx.category == ("char" if "char" in rel else None)
    assert ctx.area is None


def test_department_name_in_third_place_means_no_category(project: Path) -> None:
    # Spec rule as written: parts[2] is a department, so parts[1] is the asset.
    ctx = Context.from_path(project / "assets/char/fx")
    assert (ctx.category, ctx.entity, ctx.dept) == (None, "char", "fx")


# PROPOSED: in deep paths, the position of an area keyword decides the category,
# so a custom department under an asset without category still parses. The spec
# rule alone would read this as category "hero", asset "groom".
def test_custom_department_without_category(project: Path) -> None:
    ctx = Context.from_path(project / "assets/hero/groom/main/work/hero_groom_main_v001.hip")
    assert ctx == make(project, **A, dept="groom", task="main", area="work", version=1, ext="hip")


# PROPOSED: the sequence folder itself is the sequence; path() points at _seq.
def test_sequence_folder(project: Path) -> None:
    ctx = Context.from_path(project / "shots/sq010")
    assert ctx == make(project, **SEQ)
    assert ctx.path() == project / "shots/sq010/_seq"


# --- root and non-entity paths ----------------------------------------------


def test_outside_project_is_none(tmp_path: Path) -> None:
    assert Context.from_path(tmp_path / "elsewhere/assets/hero") is None


# PROPOSED: inside a project but not inside an entity -> ParseError.
@pytest.mark.parametrize(
    "rel", ["", "scheinwerk.json", "assets", "shots", "shared/hooks/x.py", "io/in/plate.exr", "foo"]
)
def test_not_an_entity_raises(project: Path, rel: str) -> None:
    with pytest.raises(ParseError):
        Context.from_path(project / rel)


def test_existing_path_parses_the_same(project: Path) -> None:
    work = project / "assets/hero/mdl/main/work"
    work.mkdir(parents=True)
    workfile = work / "hero_mdl_main_v001.hip"
    workfile.write_bytes(b"")
    assert Context.from_path(workfile) == make(
        project, **A, **MDL, area="work", version=1, ext="hip"
    )


def test_root_is_found_by_walking_up(project: Path) -> None:
    ctx = Context.from_path(project / "shots/sq010/sq010_0010/lgt/main/work")
    assert ctx.root == project


def test_accepts_str(project: Path) -> None:
    assert Context.from_path(str(project / "assets/hero")) == make(project, **A)


def test_relative_path_uses_cwd(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(project.parent)
    assert Context.from_path(Path(project.name) / "assets/hero") == make(project, **A)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path syntax")
def test_windows_backslashes(project: Path) -> None:
    raw = str(project) + "\\assets\\hero\\mdl\\main\\work\\hero_mdl_main_v001.hip"
    assert Context.from_path(raw) == make(project, **A, **MDL, area="work", version=1, ext="hip")


def test_context_is_frozen(project: Path) -> None:
    ctx = make(project, **A)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.entity = "villain"  # type: ignore[misc]


def test_path_builds_next_version_paths(project: Path) -> None:
    # Building a context by hand for a file that doesn't exist yet.
    ctx = make(project, **SH, **LGT, area="work", version=13, ext="hip")
    assert (
        ctx.path() == project / "shots/sq010/sq010_0010/lgt/main/work/sq010_0010_lgt_main_v013.hip"
    )
