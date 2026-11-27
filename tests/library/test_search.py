"""Search, filters and the category tree (spec §17.9, §17.11)."""

from __future__ import annotations

import pytest

from scheinwerk.library.root import Library
from scheinwerk.library.search import category_counts, search, tag_counts
from tests.library.conftest import make_item

MAIN = {"variants": {"main": {"version": 1}}}


@pytest.fixture
def stocked(lib: Library) -> Library:
    make_item(
        lib,
        "texture_set",
        "rust_a1b2c3",
        {1: MAIN},
        name="Rusty Metal 02",
        categories=["metal/painted", "architecture/industrial"],
        tags=["rust", "worn"],
        credits="ambientCG",
        description="Peeling paint",
    )
    make_item(
        lib,
        "texture_set",
        "steel_d4e5f6",
        {1: MAIN},
        name="Brushed Steel",
        categories=["metal"],
        tags=["clean"],
    )
    make_item(
        lib,
        "model",
        "oak_k3f9q2",
        {1: MAIN, 2: {"variants": {"main": {"version": 1}, "winter": {"version": 2}}}},
        name="Oak",
        categories=["vegetation/trees"],
        tags=["tree"],
    )
    make_item(
        lib,
        "hdri",
        "sky_g7h8i9",
        {1: MAIN},
        name="Kloppenheim 06",
        categories=["sky/clear"],
        tags=["sun"],
    )
    make_item(lib, "model", "draft_j1k2l3", {1: None}, name="Draft Bush")
    return lib


def ids(items) -> list[str]:
    return [i.id for i in items]


def test_everything_sorted_by_name(stocked: Library) -> None:
    assert ids(search(stocked)) == [
        "steel_d4e5f6",
        "draft_j1k2l3",
        "sky_g7h8i9",
        "oak_k3f9q2",
        "rust_a1b2c3",
    ]


def test_type(stocked: Library) -> None:
    assert ids(search(stocked, type_="model")) == ["draft_j1k2l3", "oak_k3f9q2"]


def test_category_includes_children(stocked: Library) -> None:
    assert ids(search(stocked, category="metal")) == ["steel_d4e5f6", "rust_a1b2c3"]
    assert ids(search(stocked, category="metal/painted")) == ["rust_a1b2c3"]
    assert ids(search(stocked, category="Metal / Painted")) == ["rust_a1b2c3"]  # cleaned
    assert ids(search(stocked, category="metal/pain")) == []  # whole segments only


def test_tags_all_of_them(stocked: Library) -> None:
    assert ids(search(stocked, tags=["rust"])) == ["rust_a1b2c3"]
    assert ids(search(stocked, tags=["rust", "worn"])) == ["rust_a1b2c3"]
    assert ids(search(stocked, tags=["rust", "clean"])) == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("rusty", ["rust_a1b2c3"]),  # display name, any case
        ("a1b2", ["rust_a1b2c3"]),  # id
        ("winter", ["oak_k3f9q2"]),  # variant names of the latest version
        ("industrial", ["rust_a1b2c3"]),  # categories
        ("sun", ["sky_g7h8i9"]),  # tags
        ("peeling", ["rust_a1b2c3"]),  # description
        ("ambientcg", ["rust_a1b2c3"]),  # credits
        ("metal paint", ["rust_a1b2c3"]),  # every word must match
        ("metal tree", []),
        ("  ", ["steel_d4e5f6", "draft_j1k2l3", "sky_g7h8i9", "oak_k3f9q2", "rust_a1b2c3"]),
    ],
)
def test_free_text(stocked: Library, text: str, found: list[str]) -> None:
    assert ids(search(stocked, text=text)) == found


def test_filters_combine(stocked: Library) -> None:
    assert ids(search(stocked, type_="texture_set", category="metal", text="steel")) == [
        "steel_d4e5f6"
    ]


def test_category_counts_include_parents(stocked: Library) -> None:
    assert category_counts(search(stocked)) == {
        "architecture": 1,
        "architecture/industrial": 1,
        "metal": 2,
        "metal/painted": 1,
        "sky": 1,
        "sky/clear": 1,
        "vegetation": 1,
        "vegetation/trees": 1,
    }


def test_tag_counts(stocked: Library) -> None:
    assert tag_counts(search(stocked, type_="texture_set")) == {"clean": 1, "rust": 1, "worn": 1}
