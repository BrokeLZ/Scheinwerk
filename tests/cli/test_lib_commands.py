"""sw lib init, ls, meta, path (spec §17.10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scheinwerk.core import settings
from scheinwerk.core.project import Project
from scheinwerk.library.root import Library
from tests.library.conftest import make_item

MAIN = {"variants": {"main": {"version": 1}}}


@pytest.fixture
def lib(sw, tmp_path: Path) -> Library:
    assert sw("lib", "init", tmp_path / "library").code == 0
    return Library.open(tmp_path / "library")


# --- init ---------------------------------------------------------------------------------


def test_init_creates_library_workshop_and_setting(sw, tmp_path: Path) -> None:
    r = sw("lib", "init", tmp_path / "library")
    assert r.code == 0, r.err
    root = tmp_path / "library"
    assert (root / "library.json").is_file()
    workshop = Project.find(root / "_workshop")
    assert workshop.config["name"] == "library_workshop"
    assert workshop.department_template("asset") == {
        "mdl": ["main", "speedtree"],
        "lookdev": ["main"],
        "tex": ["main"],
    }
    assert workshop.department_template("shot") == {}
    assert settings.load_settings()["library"] == str(root)
    assert str(root) in r.out


def test_init_name(sw, tmp_path: Path) -> None:
    assert sw("lib", "init", tmp_path / "lib", "--name", "studio").code == 0
    assert Library.open(tmp_path / "lib").name == "studio"


def test_init_on_an_existing_library_only_stores_the_setting(sw, lib: Library) -> None:
    settings.save_settings({**settings.load_settings(), "library": None})
    (lib.root / "library.json").write_text('{"schema": 1, "name": "kept"}', encoding="utf-8")
    r = sw("lib", "init", lib.root)
    assert r.code == 0, r.err
    assert "existing library" in r.out
    assert Library.open(lib.root).name == "kept"  # nothing rewritten
    assert settings.load_settings()["library"] == str(lib.root)


def test_init_refuses_a_folder_inside_a_project(sw, project: Path) -> None:
    r = sw("lib", "init", project / "shared" / "lib")
    assert r.code == 1 and "inside the project" in r.err
    assert not (project / "shared" / "lib" / "library.json").exists()


def test_commands_need_a_library(sw) -> None:
    r = sw("lib", "ls")
    assert r.code == 1 and "sw lib init" in r.err


# --- ls -----------------------------------------------------------------------------------


@pytest.fixture
def stocked(lib: Library) -> Library:
    make_item(
        lib,
        "texture_set",
        "rust_a1b2c3",
        {1: MAIN},
        name="Rusty Metal 02",
        categories=["metal/painted"],
        tags=["rust"],
    )
    make_item(
        lib,
        "model",
        "oak_k3f9q2",
        {1: MAIN, 2: {"variants": {"main": {"version": 1}, "winter": {"version": 2}}}, 3: None},
        name="Oak",
        categories=["vegetation/trees"],
    )
    make_item(lib, "model", "draft_j1k2l3", {1: None}, name="Draft")
    (lib.root / "model" / "Bad Folder").mkdir()
    (lib.root / "stuff").mkdir()
    return lib


def test_ls(sw, stocked: Library) -> None:
    r = sw("lib", "ls")
    assert r.code == 0, r.err
    assert r.lines == [
        "model/Bad Folder  Bad Folder  [invalid id, no finalized version]",
        "model/draft_j1k2l3  Draft  [no finalized version]",
        "model/oak_k3f9q2  Oak  v002  main, winter  [incomplete v003]",
        "texture_set/rust_a1b2c3  Rusty Metal 02  v001  main",
        "stuff  [unknown]",
    ]


def test_ls_filters(sw, stocked: Library) -> None:
    assert sw("lib", "ls", "texture_set").lines == [
        "texture_set/rust_a1b2c3  Rusty Metal 02  v001  main"
    ]
    assert sw("lib", "ls", "--category", "vegetation").lines == [
        "model/oak_k3f9q2  Oak  v002  main, winter  [incomplete v003]"
    ]
    assert sw("lib", "ls", "--tag", "rust", "--search", "metal").lines == [
        "texture_set/rust_a1b2c3  Rusty Metal 02  v001  main"
    ]
    assert sw("lib", "ls", "--search", "nothing").lines == []
    assert sw("lib", "ls", "vdb").code == 2  # argparse choices


def test_ls_json(sw, stocked: Library) -> None:
    data = sw("lib", "ls", "model", "--search", "oak", "--json").json
    assert data == {
        "items": [
            {
                "type": "model",
                "id": "oak_k3f9q2",
                "name": "Oak",
                "valid": True,
                "path": "model/oak_k3f9q2",
                "latest": 2,
                "variants": {"main": 1, "winter": 2},
                "incomplete": [3],
                "categories": ["vegetation/trees"],
                "tags": [],
            }
        ]
    }


# --- meta ---------------------------------------------------------------------------------


def test_meta_edits_and_prints(sw, stocked: Library) -> None:
    r = sw(
        "lib",
        "meta",
        "rust_a1b2c3",
        "--name",
        "Rusty Metal",
        "--add-category",
        "Architecture/Industrial",
        "--add-tag",
        "worn",
        "--add-tag",
        "old",
        "--remove-tag",
        "rust",
    )
    assert r.code == 0, r.err
    data = json.loads((stocked.root / "texture_set/rust_a1b2c3/item.json").read_text("utf-8"))
    assert data["name"] == "Rusty Metal"
    assert data["categories"] == ["architecture/industrial", "metal/painted"]
    assert data["tags"] == ["old", "worn"]
    assert "architecture/industrial" in r.out


def test_meta_by_unique_name_and_json(sw, stocked: Library) -> None:
    data = sw("lib", "meta", "oak", "--json").json
    assert data["id"] == "oak_k3f9q2" and data["name"] == "Oak"


def test_meta_unknown_item(sw, stocked: Library) -> None:
    r = sw("lib", "meta", "birch")
    assert r.code == 1 and "No library item" in r.err


# --- path ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "out"),
    [
        (["oak_k3f9q2"], "model/oak_k3f9q2/v002"),
        (["oak_k3f9q2", "--usd"], "model/oak_k3f9q2/v002/oak_k3f9q2.usd"),
        (["oak_k3f9q2", "--version", "1", "--usd"], "model/oak_k3f9q2/v001/oak_k3f9q2.usd"),
        (["oak_k3f9q2", "--variant", "main"], "model/oak_k3f9q2/v001"),
        (["oak_k3f9q2", "--variant", "winter"], "model/oak_k3f9q2/v002"),
        (["oak_k3f9q2", "--usd", "--env"], "$SW_LIBRARY/model/oak_k3f9q2/v002/oak_k3f9q2.usd"),
        (["Rusty Metal 02"], "texture_set/rust_a1b2c3/v001"),
    ],
)
def test_path(sw, stocked: Library, args: list[str], out: str) -> None:
    r = sw("lib", "path", *args)
    assert r.code == 0, r.err
    assert r.lines == [out]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["oak_k3f9q2", "--version", "3"], "incomplete"),
        (["oak_k3f9q2", "--version", "9"], "no v009"),
        (["oak_k3f9q2", "--variant", "summer"], "no variant 'summer'"),
        (["rust_a1b2c3", "--usd"], "only models"),
        (["draft_j1k2l3"], "no finalized version"),
    ],
)
def test_path_errors(sw, stocked: Library, args: list[str], error: str) -> None:
    r = sw("lib", "path", *args)
    assert r.code == 1 and error in r.err, r.err
