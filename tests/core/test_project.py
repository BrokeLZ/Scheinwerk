"""Projects: create, find, scan and create entities (spec §2.3, §4, §8.1, §10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scheinwerk.core.errors import (
    AlreadyExists,
    InvalidName,
    NotFound,
    NotInProject,
    ScheinwerkError,
)
from scheinwerk.core.project import DEFAULTS, Project
from tests.conftest import touch

# --- create / find ----------------------------------------------------------


def test_create_writes_config_and_top_folders(tmp_path: Path) -> None:
    p = Project.create(tmp_path / "show", "show")
    data = json.loads((tmp_path / "show/scheinwerk.json").read_text(encoding="utf-8"))
    assert data == {"schema": 1, "name": "show", **DEFAULTS}
    assert p.root == tmp_path / "show"
    assert p.config == data
    for sub in ["assets", "shots", "shared/hooks", "shared/templates", "io/in", "io/out"]:
        assert (p.root / sub).is_dir(), sub


def test_create_with_settings(tmp_path: Path) -> None:
    p = Project.create(tmp_path / "show", "show", fps=25, frame_start=1)
    assert (p.config["fps"], p.config["frame_start"]) == (25, 1)


def test_create_rejects_unknown_settings(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        Project.create(tmp_path / "show", "show", colour="red")


def test_create_in_existing_folder_keeps_files(tmp_path: Path) -> None:
    keep = touch(tmp_path / "show/notes.txt", b"mine")
    Project.create(tmp_path / "show", "show")
    assert keep.read_bytes() == b"mine"


def test_create_refuses_existing_project(project: Path) -> None:
    before = (project / "scheinwerk.json").read_bytes()
    with pytest.raises(AlreadyExists):
        Project.create(project, "again")
    assert (project / "scheinwerk.json").read_bytes() == before


def test_create_refuses_nested_project(project: Path) -> None:
    with pytest.raises(ScheinwerkError, match="nested"):
        Project.create(project / "io/sub", "sub")


@pytest.mark.parametrize("name", ["My Show", "_show", "publish"])
def test_create_validates_name(tmp_path: Path, name: str) -> None:
    with pytest.raises(InvalidName):
        Project.create(tmp_path / "show", name)


def test_find(project: Path, tmp_path: Path) -> None:
    assert Project.find(project / "shots/sq010/sq010_0010/lgt").root == project
    assert Project.find(tmp_path / "elsewhere") is None


def test_rel_and_abs(proj: Project) -> None:
    assert proj.rel(proj.root / "assets" / "hero") == "assets/hero"
    assert proj.abs("assets/hero") == proj.root / "assets" / "hero"
    with pytest.raises(NotInProject):
        proj.rel(proj.root.parent / "elsewhere")
    with pytest.raises(ScheinwerkError):
        proj.abs(str(proj.root / "assets"))  # absolute, not root-relative


@pytest.mark.parametrize(
    ("name", "ignored"),
    [
        (".DS_Store", True),
        ("._hero.hip", True),
        ("Thumbs.db", True),
        ("@eaDir", True),
        ("hero_mdl_main_v003.blend1", True),
        ("x.autosave", True),
        ("hero.hip~", True),
        ("backup", True),
        ("backups", False),
        ("hero_mdl_main_v003_Conflict.hip", False),  # shown so `sw doctor` can report it
        ("hero", False),
    ],
)
def test_ignored(proj: Project, name: str, ignored: bool) -> None:
    assert proj.ignored(name) is ignored


def test_ignore_comes_from_config(tmp_path: Path) -> None:
    p = Project.create(tmp_path / "show", "show", ignore=["*.tmp"])
    assert p.ignored("x.tmp")
    assert not p.ignored(".DS_Store")


# --- scanning ---------------------------------------------------------------


def test_assets_with_and_without_category(proj: Project) -> None:
    proj.create_asset("hero")
    proj.create_asset("chair", category="prop")
    proj.create_asset("villain", category="char")
    assert [(a.category, a.name) for a in proj.assets()] == [
        (None, "hero"),
        ("char", "villain"),
        ("prop", "chair"),
    ]
    assert proj.categories() == ["char", "prop"]


def test_hand_made_asset_folders(proj: Project) -> None:
    root = proj.root / "assets"
    (root / "tree/publish").mkdir(parents=True)  # publish/ marks an asset
    (root / "rock/mdl").mkdir(parents=True)  # so does a template department
    touch(root / "lamp/entity.json", b'{"schema": 1}')
    (root / "env/forest").mkdir(parents=True)  # no marker: env is a category
    (root / "vehicle").mkdir()  # empty folder: a (new) category
    (root / "backup/old").mkdir(parents=True)  # ignored
    touch(root / ".DS_Store")
    touch(root / "readme.txt")
    assert [(a.category, a.name) for a in proj.assets()] == [
        (None, "lamp"),
        (None, "rock"),
        (None, "tree"),
        ("env", "forest"),
    ]
    assert proj.categories() == ["env", "vehicle"]


def test_invalid_names_are_listed_and_flagged(proj: Project) -> None:
    touch(proj.root / "assets/Hero_Old/entity.json")
    (proj.root / "shots/SQ_bad").mkdir(parents=True)
    (proj.root / "shots/sq010/oops").mkdir(parents=True)
    assert [(a.name, a.valid) for a in proj.assets()] == [("Hero_Old", False)]
    assert [(s.name, s.valid) for s in proj.sequences()] == [("SQ_bad", False), ("sq010", True)]
    assert [(s.name, s.valid) for s in proj.shots()] == [("oops", False)]


def test_sequences_and_shots(proj: Project) -> None:
    proj.create_shot("sq020_0010")
    proj.create_shot("sq010_0020")
    proj.create_shot("sq010_0010")
    (proj.root / "shots/sq010/_seq/lgt").mkdir(parents=True)  # not a shot
    assert [s.name for s in proj.sequences()] == ["sq010", "sq020"]
    assert [s.name for s in proj.shots()] == ["sq010_0010", "sq010_0020", "sq020_0010"]
    assert [s.name for s in proj.shots("sq010")] == ["sq010_0010", "sq010_0020"]
    assert proj.shots("sq999") == []


def test_entity_paths(proj: Project) -> None:
    assert proj.create_asset("hero").path == proj.root / "assets/hero"
    assert proj.create_asset("chair", category="prop").path == proj.root / "assets/prop/chair"
    assert proj.create_sequence("sq010").path == proj.root / "shots/sq010/_seq"
    shot = proj.create_shot("sq010_0010")
    assert (shot.type, shot.sequence, shot.path) == (
        "shot",
        "sq010",
        proj.root / "shots/sq010/sq010_0010",
    )


# --- creating entities ------------------------------------------------------


def test_create_asset_writes_entity_json(proj: Project) -> None:
    hero = proj.create_asset("hero")
    assert json.loads((hero.path / "entity.json").read_text(encoding="utf-8")) == {"schema": 1}


@pytest.mark.parametrize("name", ["Hero", "_hero", "publish", "mdl", "lgt"])  # dept names too
def test_create_asset_invalid(proj: Project, name: str) -> None:
    with pytest.raises(InvalidName):
        proj.create_asset(name)


@pytest.mark.parametrize("category", ["Char", "fx", "work"])
def test_create_asset_invalid_category(proj: Project, category: str) -> None:
    with pytest.raises(InvalidName):
        proj.create_asset("hero", category=category)


def test_asset_names_are_unique_across_categories(proj: Project) -> None:
    proj.create_asset("hero", category="char")
    with pytest.raises(AlreadyExists):
        proj.create_asset("hero", category="prop")
    with pytest.raises(AlreadyExists):
        proj.create_asset("hero")


def test_asset_collision_is_case_insensitive(proj: Project) -> None:
    touch(proj.root / "assets/Hero/entity.json")  # made by hand
    with pytest.raises(AlreadyExists):
        proj.create_asset("hero")


def test_asset_cannot_go_into_another_asset(proj: Project) -> None:
    proj.create_asset("hero")
    with pytest.raises(InvalidName, match="not a category"):
        proj.create_asset("sword", category="hero")


def test_asset_cannot_take_a_category_name(proj: Project) -> None:
    proj.create_category("char")
    with pytest.raises(AlreadyExists):
        proj.create_asset("char")


def test_create_category(proj: Project) -> None:
    assert proj.create_category("char") == proj.root / "assets/char"
    assert proj.categories() == ["char"]
    with pytest.raises(AlreadyExists):
        proj.create_category("char")
    with pytest.raises(InvalidName):
        proj.create_category("mdl")


def test_create_shot_with_frames(proj: Project) -> None:
    shot = proj.create_shot("sq010_0010", frames=(1001, 1096))
    data = json.loads((shot.path / "entity.json").read_text(encoding="utf-8"))
    assert data == {"schema": 1, "frames": [1001, 1096]}
    assert shot.frames == (1001, 1096)
    assert [s.name for s in proj.sequences()] == ["sq010"]  # created on the fly


def test_create_shot_without_frames(proj: Project) -> None:
    shot = proj.create_shot("sq010_0010")
    assert json.loads((shot.path / "entity.json").read_text(encoding="utf-8")) == {"schema": 1}
    assert shot.frames is None


@pytest.mark.parametrize("name", ["sq010", "sq010_010", "SQ010_0010", "0010"])
def test_create_shot_invalid(proj: Project, name: str) -> None:
    with pytest.raises(InvalidName):
        proj.create_shot(name)


def test_create_shot_rejects_reversed_frames(proj: Project) -> None:
    with pytest.raises(ScheinwerkError):
        proj.create_shot("sq010_0010", frames=(1096, 1001))
    assert not (proj.root / "shots/sq010/sq010_0010").exists()


def test_duplicates_rejected(proj: Project) -> None:
    proj.create_shot("sq010_0010")
    with pytest.raises(AlreadyExists):
        proj.create_shot("sq010_0010")
    with pytest.raises(AlreadyExists):
        proj.create_sequence("sq010")


def test_create_sequence_invalid(proj: Project) -> None:
    with pytest.raises(InvalidName):
        proj.create_sequence("seq_a")


# --- frames -----------------------------------------------------------------


def test_sequence_frames_come_from_shots(proj: Project) -> None:
    proj.create_shot("sq010_0010", frames=(1001, 1096))
    proj.create_shot("sq010_0020", frames=(1097, 1200))
    proj.create_shot("sq010_0030")  # no range: skipped
    seq = proj.entity("sq010")
    assert seq.frames == (1001, 1200)
    with pytest.raises(ScheinwerkError):
        seq.set_frames(1, 2)


def test_set_frames_keeps_other_keys(proj: Project) -> None:
    shot = proj.create_shot("sq010_0010")
    (shot.path / "entity.json").write_text(
        '{"schema": 1, "fps": 25, "note": "mine"}', encoding="utf-8"
    )
    shot.set_frames(1001, 1050)
    data = json.loads((shot.path / "entity.json").read_text(encoding="utf-8"))
    assert data == {"schema": 1, "fps": 25, "note": "mine", "frames": [1001, 1050]}


def test_asset_frames(proj: Project) -> None:
    hero = proj.create_asset("hero")
    assert hero.frames is None
    hero.set_frames(1, 100)
    assert hero.frames == (1, 100)


# --- resolving entities by name (spec §11) ----------------------------------


def test_entity_by_name(proj: Project) -> None:
    proj.create_asset("hero", category="char")
    proj.create_shot("sq010_0010")
    assert (proj.entity("hero").type, proj.entity("hero").category) == ("asset", "char")
    assert proj.entity("sq010").type == "sequence"
    assert proj.entity("sq010_0010").type == "shot"
    assert proj.entity("shot:sq010_0010").name == "sq010_0010"


def test_entity_ambiguous_needs_prefix(proj: Project) -> None:
    proj.create_asset("sq010")  # a legal asset name
    proj.create_sequence("sq010")
    with pytest.raises(ScheinwerkError, match="asset:sq010"):
        proj.entity("sq010")
    assert proj.entity("asset:sq010").type == "asset"
    assert proj.entity("seq:sq010").type == "sequence"


def test_entity_not_found(proj: Project) -> None:
    with pytest.raises(NotFound):
        proj.entity("ghost")
    with pytest.raises(NotFound):
        proj.entity("thing:hero")
