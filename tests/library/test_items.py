"""Items, versions, variants, item.json and version.json (spec §17.3, §17.4)."""

from __future__ import annotations

import json
import random

import pytest

from scheinwerk.core.errors import AlreadyExists, InvalidName, NotFound
from scheinwerk.library.items import Item, create_item, finalize, find_item, update_meta
from scheinwerk.library.root import Library
from tests.library.conftest import make_item

MAIN = {"variants": {"main": {"version": 1}}}


# --- scanning -----------------------------------------------------------------------------


def test_items_by_type_and_flags(lib: Library) -> None:
    make_item(lib, "model", "oak_k3f9q2", {1: MAIN})
    make_item(lib, "hdri", "sky_a1b2c3", {1: MAIN})
    (lib.root / "model" / "Not An Id").mkdir()
    (lib.root / "model" / "loose.txt").write_text("", encoding="utf-8")  # files aren't items
    items = lib.items()
    assert [(i.type, i.id, i.valid) for i in items] == [
        ("hdri", "sky_a1b2c3", True),
        ("model", "Not An Id", False),
        ("model", "oak_k3f9q2", True),
    ]
    assert [i.id for i in lib.items("hdri")] == ["sky_a1b2c3"]
    with pytest.raises(InvalidName):
        lib.items("vdb")


def test_versions_latest_and_incomplete(lib: Library) -> None:
    make_item(lib, "model", "oak_k3f9q2", {1: MAIN, 2: MAIN, 3: None})
    item = lib.items()[0]
    assert [(v.number, v.finalized) for v in item.versions()] == [(3, False), (2, True), (1, True)]
    assert item.latest().number == 2  # highest finalized, not the incomplete v003
    assert item.version(3).finalized is False
    with pytest.raises(NotFound):
        item.version(9)


def test_broken_version_json_is_incomplete(lib: Library) -> None:
    folder = make_item(lib, "model", "oak_k3f9q2", {1: MAIN, 2: None})
    (folder / "v002" / "version.json").write_text("{broken", encoding="utf-8")
    assert lib.items()[0].latest().number == 1


def test_item_without_finalized_versions(lib: Library) -> None:
    make_item(lib, "model", "oak_k3f9q2", {1: None})
    assert lib.items()[0].latest() is None


def test_metadata_reads_and_defaults(lib: Library) -> None:
    make_item(
        lib,
        "texture_set",
        "rust_a1b2c3",
        {1: MAIN},
        name="Rusty Metal 02",
        categories=["metal/painted"],
        tags=["rust"],
    )
    make_item(lib, "model", "oak_k3f9q2", {1: MAIN})  # no item.json at all
    rust, oak = lib.items()
    assert (oak.name, oak.categories, oak.tags) == ("oak_k3f9q2", [], [])
    assert (rust.name, rust.categories, rust.tags) == (
        "Rusty Metal 02",
        ["metal/painted"],
        ["rust"],
    )


# --- variants -----------------------------------------------------------------------------


def test_variants_point_at_the_version_holding_their_files(lib: Library) -> None:
    make_item(
        lib,
        "model",
        "oak_k3f9q2",
        {
            1: MAIN,
            2: {"variants": {"main": {"version": 1}, "winter": {"version": 2}}},
        },
    )
    v2 = lib.items()[0].latest()
    assert v2.variants() == {"main": 1, "winter": 2}
    assert v2.variant_dir("main") == lib.root / "model/oak_k3f9q2/v001"
    assert v2.variant_dir("winter") == lib.root / "model/oak_k3f9q2/v002"
    assert v2.thumbnail("winter") == lib.root / "model/oak_k3f9q2/v002/thumb_winter.jpg"
    with pytest.raises(NotFound):
        v2.variant_dir("summer")


def test_variant_problems_are_reported(lib: Library) -> None:
    make_item(
        lib,
        "model",
        "oak_k3f9q2",
        {
            1: None,
            2: {
                "variants": {
                    "main": {"version": 1},
                    "a": {"version": 3},
                    "Bad": {"version": 2},
                    "b": {},
                }
            },
        },
    )
    problems = lib.items()[0].version(2).variant_problems()
    assert problems == {
        "Bad": "invalid variant name",
        "a": "points at v003, which is newer than this version",
        "b": "names no version",
        "main": "points at v001, which is incomplete",
    }


# --- creating and finalizing --------------------------------------------------------------


def test_create_item(lib: Library) -> None:
    item = create_item(lib, "texture_set", "Rusty Metal 02", rng=random.Random(3))
    assert item.type == "texture_set" and item.id.startswith("rusty_metal_02_")
    data = json.loads((item.path / "item.json").read_text(encoding="utf-8"))
    assert data == {"schema": 1, "name": "Rusty Metal 02", "categories": [], "tags": []}
    assert item.versions() == []


def test_create_item_uid_unique_across_types(lib: Library) -> None:
    first = create_item(lib, "model", "Oak", rng=random.Random(5))
    second = create_item(lib, "hdri", "Sky", rng=random.Random(5))
    assert first.id.split("_")[-1] != second.id.split("_")[-1]


def test_create_item_bad_type_or_name(lib: Library) -> None:
    with pytest.raises(InvalidName):
        create_item(lib, "vdb", "Smoke")
    with pytest.raises(InvalidName):
        create_item(lib, "model", "!!!")


def test_finalize_writes_version_json_last(lib: Library) -> None:
    item = create_item(lib, "hdri", "Sky")
    vdir = item.next_version_dir()
    assert vdir.name == "v001" and not item.version(1).finalized
    finalize(item.version(1), {"origin": "ingest", "variants": {"main": {"version": 1}}})
    info = item.version(1).info
    assert info["schema"] == 1 and info["origin"] == "ingest"
    assert item.latest().number == 1


def test_finalize_refuses_bad_variants_and_finalized_versions(lib: Library) -> None:
    item = create_item(lib, "hdri", "Sky")
    item.next_version_dir()
    v1 = item.version(1)
    with pytest.raises(InvalidName, match="variants"):
        finalize(v1, {"origin": "ingest"})
    with pytest.raises(InvalidName, match="newer"):
        finalize(v1, {"variants": {"main": {"version": 2}}})
    finalize(v1, {"variants": {"main": {"version": 1}}})
    with pytest.raises(AlreadyExists):
        finalize(v1, {"variants": {"main": {"version": 1}}})


def test_next_version_counts_incomplete_ones(lib: Library) -> None:
    folder = make_item(lib, "model", "oak_k3f9q2", {1: MAIN, 2: None})
    item = Item(lib, folder)
    assert item.next_version_dir().name == "v003"


# --- item.json edits ----------------------------------------------------------------------


def test_update_meta(lib: Library) -> None:
    item = create_item(lib, "texture_set", "Rusty Metal 02")
    (item.path / "item.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "name": "Rusty Metal 02",
                "categories": ["metal"],
                "tags": ["rust"],
                "credits": "ambientCG",
                "mine": True,
            }
        ),
        encoding="utf-8",
    )
    update_meta(
        item,
        name="Rusty Metal",
        add_categories=["Metal / Painted", "metal"],
        remove_categories=["metal"],
        add_tags=["Worn Out", "rust"],
        remove_tags=[],
    )
    data = json.loads((item.path / "item.json").read_text(encoding="utf-8"))
    assert data == {
        "schema": 1,
        "name": "Rusty Metal",
        "categories": ["metal/painted"],
        "tags": ["rust", "worn_out"],
        "credits": "ambientCG",
        "mine": True,
    }


def test_update_meta_on_an_item_without_item_json(lib: Library) -> None:
    folder = make_item(lib, "model", "oak_k3f9q2", {1: MAIN})
    update_meta(Item(lib, folder), add_tags=["tree"])
    data = json.loads((folder / "item.json").read_text(encoding="utf-8"))
    assert data == {"schema": 1, "name": "oak_k3f9q2", "categories": [], "tags": ["tree"]}


def test_update_meta_refuses_an_empty_name(lib: Library) -> None:
    item = create_item(lib, "hdri", "Sky")
    with pytest.raises(InvalidName):
        update_meta(item, name="  ")


# --- finding items by id or name ----------------------------------------------------------


def test_find_item(lib: Library) -> None:
    make_item(lib, "model", "oak_k3f9q2", {1: MAIN}, name="Oak")
    make_item(lib, "model", "oak_x9y8z7", {1: MAIN}, name="Oak")
    make_item(lib, "hdri", "sky_a1b2c3", {1: MAIN}, name="Kloppenheim 06")
    assert find_item(lib, "oak_k3f9q2").id == "oak_k3f9q2"
    assert find_item(lib, "kloppenheim 06").id == "sky_a1b2c3"  # display name, any case
    with pytest.raises(NotFound, match="oak_k3f9q2.*oak_x9y8z7"):
        find_item(lib, "Oak")  # the name isn't unique: the matches are listed
    with pytest.raises(NotFound):
        find_item(lib, "birch")
