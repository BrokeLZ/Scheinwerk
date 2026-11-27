"""Item ids, slugs, categories, tags and variant names (spec §17.3, §17.4, §17.5)."""

from __future__ import annotations

import random

import pytest

from scheinwerk.core.errors import InvalidName
from scheinwerk.library import ids

# --- slug ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Rusty Metal 02", "rusty_metal_02"),
        ("oak", "oak"),
        ("  Oak  Sapling ", "oak_sapling"),
        ("Kloppenheim-06 (4K)", "kloppenheim_06_4k"),
        ("Grüne Wiese", "grune_wiese"),
        ("Café Façade", "cafe_facade"),
        ("__hidden__", "hidden"),
        ("a--b__c", "a_b_c"),
        ("Straße", "strasse"),
    ],
)
def test_slug(name: str, slug: str) -> None:
    assert ids.slug(name) == slug


def test_slug_is_cut_to_40_without_a_trailing_underscore() -> None:
    name = "a" * 39 + " b and more"
    assert ids.slug(name) == "a" * 39  # cut at 40 would end in "_"
    assert len(ids.slug("x" * 100)) == 40


@pytest.mark.parametrize("name", ["", "   ", "___", "日本", "!!!"])
def test_slug_of_nothing_usable_is_refused(name: str) -> None:
    with pytest.raises(InvalidName):
        ids.slug(name)


# --- item ids -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item_id", ["oak_k3f9q2", "rusty_metal_02_a1b2c3", "x_000000", "2k_sky_zzzzzz"]
)
def test_valid_item_ids(item_id: str) -> None:
    assert ids.is_item_id(item_id)


@pytest.mark.parametrize(
    "item_id",
    [
        "oak",
        "Oak_k3f9q2",
        "_oak_k3f9q2",
        "oak_k3f9q",
        "oak_k3f9q23",
        "oak-k3f9q2",
        "oak_K3F9Q2",
        "v001",
        "oak__k3f9q2x",
        "_k3f9q2",
        "oak_k3f9q_",
    ],
)
def test_invalid_item_ids(item_id: str) -> None:
    assert not ids.is_item_id(item_id)


def test_split_item_id() -> None:
    assert ids.split_item_id("rusty_metal_02_a1b2c3") == ("rusty_metal_02", "a1b2c3")


def test_new_item_id() -> None:
    item_id = ids.new_item_id("Rusty Metal 02", taken=set(), rng=random.Random(1))
    assert ids.is_item_id(item_id)
    assert item_id.startswith("rusty_metal_02_")


def test_uid_unique_across_the_library_retries_on_collision() -> None:
    first = ids.new_item_id("Oak", taken=set(), rng=random.Random(7))
    uid = ids.split_item_id(first)[1]
    # the same uid on any other item (any type, any slug) is taken: the next draw is used
    again = ids.new_item_id("Birch", taken={f"pine_{uid}"}, rng=random.Random(7))
    assert ids.split_item_id(again)[1] != uid


def test_default_rng_is_secrets() -> None:
    a = ids.new_item_id("Oak", taken=set())
    b = ids.new_item_id("Oak", taken=set())
    assert ids.is_item_id(a) and a != b


# --- categories and tags ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "clean"),
    [
        ("metal/painted", "metal/painted"),
        ("Metal Painted", "metal_painted"),
        (" Vegetation / Trees ", "vegetation/trees"),
        ("architecture/industrial/", "architecture/industrial"),
        ("/metal", "metal"),
    ],
)
def test_clean_category(text: str, clean: str) -> None:
    assert ids.clean_category(text) == clean


@pytest.mark.parametrize("text", ["", "/", "metal//painted", "metal/ /x"])
def test_bad_category(text: str) -> None:
    with pytest.raises(InvalidName):
        ids.clean_category(text)


def test_category_with_parents() -> None:
    assert ids.with_parents("vegetation/trees/oak") == [
        "vegetation",
        "vegetation/trees",
        "vegetation/trees/oak",
    ]
    assert ids.with_parents("metal") == ["metal"]


@pytest.mark.parametrize(("text", "clean"), [("rust", "rust"), ("Worn Out", "worn_out")])
def test_clean_tag(text: str, clean: str) -> None:
    assert ids.clean_tag(text) == clean


@pytest.mark.parametrize("text", ["", "a/b", "___"])
def test_bad_tag(text: str) -> None:
    with pytest.raises(InvalidName):
        ids.clean_tag(text)


# --- variants -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["main", "winter", "var01", "no_sun"])
def test_valid_variant(name: str) -> None:
    ids.validate_variant(name)


@pytest.mark.parametrize("name", ["", "Main", "_x", "with space", "a-b"])
def test_invalid_variant(name: str) -> None:
    with pytest.raises(InvalidName):
        ids.validate_variant(name)


@pytest.mark.parametrize(
    ("token", "variant"),
    [
        ("var1", "var01"),
        ("Var12", "var12"),
        ("variation3", "var03"),
        ("var007", "var07"),
        ("var100", "var100"),
        ("variant", None),
        ("var", None),
        ("various", None),
    ],
)
def test_variant_from_token(token: str, variant: str | None) -> None:
    assert ids.variant_from_token(token) == variant
