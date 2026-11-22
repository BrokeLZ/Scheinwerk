"""Naming rules and filename templates (spec §5).

Cases marked PROPOSED fill a gap in the spec and need sign-off.
"""

from __future__ import annotations

import pytest

from scheinwerk.core.errors import InvalidName, ScheinwerkError
from scheinwerk.core.templates import (
    format_version,
    format_workfile,
    parse_version,
    parse_workfile,
    shot_sequence,
    validate_name,
)

RESERVED = ["publish", "media", "work", "cache", "assets", "shots", "shared", "io", "entity"]
GENERIC_KINDS = ["category", "asset", "dept", "task", "product", "media", "layer"]


# --- §5.1 names -------------------------------------------------------------


@pytest.mark.parametrize("kind", GENERIC_KINDS)
@pytest.mark.parametrize("name", ["hero", "a", "pants_drape_base", "char2", "0001", "a_"])
def test_valid_names(kind: str, name: str) -> None:
    validate_name(kind, name)


@pytest.mark.parametrize("kind", GENERIC_KINDS)
@pytest.mark.parametrize(
    "name",
    [
        "",
        "Hero",  # uppercase (also avoids case-insensitive collisions on Windows/macOS)
        "HERO",
        "_hero",  # leading _ is reserved
        "_usd",
        "_seq",
        "he ro",
        " hero",
        "hä",  # umlaut
        "hé",
        "he-ro",
        "hero.v2",
        "hero/x",
        "hero\\x",
        "hero\n",  # must use fullmatch: `$` alone accepts a trailing newline
    ],
)
def test_invalid_names(kind: str, name: str) -> None:
    with pytest.raises(InvalidName):
        validate_name(kind, name)


@pytest.mark.parametrize("kind", [*GENERIC_KINDS, "sequence", "shot"])
@pytest.mark.parametrize("word", RESERVED)
def test_reserved_words_rejected(kind: str, word: str) -> None:
    with pytest.raises(InvalidName):
        validate_name(kind, word)


def test_invalid_name_error_is_user_readable() -> None:
    with pytest.raises(InvalidName, match="Hero") as exc:
        validate_name("asset", "Hero")
    assert isinstance(exc.value, ScheinwerkError)


# --- §5.2 entity patterns ---------------------------------------------------


@pytest.mark.parametrize("name", ["sq010", "s1", "seq0010", "ab12"])
def test_valid_sequence(name: str) -> None:
    validate_name("sequence", name)


@pytest.mark.parametrize("name", ["sq", "010", "sq010a", "sq_010", "sq010_0010", "Sq010"])
def test_invalid_sequence(name: str) -> None:
    with pytest.raises(InvalidName):
        validate_name("sequence", name)


@pytest.mark.parametrize(
    ("seq", "name"), [("sq010", "sq010_0010"), ("sq010", "sq010_9999"), ("s1", "s1_0000")]
)
def test_valid_shot(seq: str, name: str) -> None:
    validate_name("shot", name, seq=seq)


@pytest.mark.parametrize(
    ("seq", "name"),
    [
        ("sq010", "sq010_010"),  # 3 digits
        ("sq010", "sq010_00100"),  # 5 digits
        ("sq010", "sq020_0010"),  # belongs to another sequence
        ("sq01", "sq010_0010"),  # prefix match is not enough
        ("sq010", "sq010_0010a"),
        ("sq010", "sq010-0010"),
    ],
)
def test_invalid_shot(seq: str, name: str) -> None:
    with pytest.raises(InvalidName):
        validate_name("shot", name, seq=seq)


# PROPOSED: without `seq`, a shot name must look like <valid sequence>_<4 digits>.
# `sw new shot sq010_0010` needs this to create the sequence on the fly.
def test_shot_without_seq() -> None:
    validate_name("shot", "sq010_0010")
    for bad in ["0010", "sq010", "_0010", "sq_0010"]:
        with pytest.raises(InvalidName):
            validate_name("shot", bad)


def test_shot_sequence() -> None:
    assert shot_sequence("sq010_0010") == "sq010"
    assert shot_sequence("ab12_0001") == "ab12"
    with pytest.raises(InvalidName):
        shot_sequence("sq010")


# --- §5.3/§5.4 versions -----------------------------------------------------


@pytest.mark.parametrize(
    ("n", "text"), [(1, "v001"), (12, "v012"), (999, "v999"), (1000, "v1000"), (12345, "v12345")]
)
def test_format_version(n: int, text: str) -> None:
    assert format_version(n) == text


@pytest.mark.parametrize(
    ("text", "n"), [("v001", 1), ("v012", 12), ("v1000", 1000), ("v0001", 1), ("v000", 0)]
)
def test_parse_version(text: str, n: int) -> None:
    assert parse_version(text) == n


@pytest.mark.parametrize(
    "text",
    [
        "v01",
        "v1",
        "V001",  # uppercase is not a version folder
        "001",
        "v001a",
        "v 001",
        "v-001",
        "",
        "version001",
        "v001.usd",
        "v١٢٣",  # Arabic-Indic digits: `\d` would match these, [0-9] must not
    ],
)
def test_parse_version_rejects(text: str) -> None:
    assert parse_version(text) is None


@pytest.mark.parametrize("n", [1, 9, 10, 99, 100, 999, 1000, 12345])
def test_version_round_trip(n: int) -> None:
    assert parse_version(format_version(n)) == n


# --- §5.3 workfiles ---------------------------------------------------------

WORKFILES = [
    # (entity, dept, task, version, ext, filename)
    ("sq010_0010", "lgt", "main", 12, "hip", "sq010_0010_lgt_main_v012.hip"),
    ("sq010", "lgt", "main", 7, "hip", "sq010_lgt_main_v007.hip"),  # sequence workfile
    ("hero", "mdl", "main", 1, "blend", "hero_mdl_main_v001.blend"),
    ("hero", "mdl", "main", 1000, "nk", "hero_mdl_main_v1000.nk"),
    ("hero", "lookdev", "turntable_v2", 3, "hipnc", "hero_lookdev_turntable_v2_v003.hipnc"),
]


@pytest.mark.parametrize(("entity", "dept", "task", "version", "ext", "filename"), WORKFILES)
def test_format_workfile(
    entity: str, dept: str, task: str, version: int, ext: str, filename: str
) -> None:
    assert format_workfile(entity, dept, task, version, ext) == filename


@pytest.mark.parametrize(("entity", "dept", "task", "version", "ext", "filename"), WORKFILES)
def test_parse_workfile_round_trip(
    entity: str, dept: str, task: str, version: int, ext: str, filename: str
) -> None:
    assert parse_workfile(filename, entity, dept, task) == (version, ext)


def test_parse_workfile_accepts_extra_version_digits() -> None:
    # Readers accept v\d{3,} (§5.3), so v0001 is version 1.
    assert parse_workfile("hero_mdl_main_v0001.hip", "hero", "mdl", "main") == (1, "hip")


@pytest.mark.parametrize(
    "filename",
    [
        # Prefix disagrees with the folders: folders win, file is unmanaged (§6.2.7).
        "villain_mdl_main_v003.hip",
        "hero_rig_main_v003.hip",
        "hero_mdl_blockout_v003.hip",
        # Not the template.
        "hero_mdl_main_v03.hip",
        "hero_mdl_main.hip",
        "hero_mdl_main_v003",
        "hero_mdl_main_v003.",
        "hero_mdl_main_v003_final.hip",  # no comments in filenames
        "hero_mdl_main_v003.hip.bak",
        "hero_mdl_main_v003 (1).hip",
        "hero_mdl_main_v003_Conflict.hip",  # Synology conflict copy: shown as unmanaged
        "Hero_mdl_main_v003.hip",
        "hero_mdl_main_v003.HIP",  # PROPOSED: extensions are case-sensitive
    ],
)
def test_parse_workfile_unmanaged(filename: str) -> None:
    assert parse_workfile(filename, "hero", "mdl", "main") is None
