"""Naming rules and filename templates (spec §5)."""

from __future__ import annotations

import re

from scheinwerk.core.errors import InvalidName

RESERVED_WORDS = frozenset(
    {"publish", "media", "work", "cache", "assets", "shots", "shared", "io", "entity"}
)
KINDS = frozenset(
    {
        "project",
        "category",
        "asset",
        "sequence",
        "shot",
        "dept",
        "task",
        "product",
        "media",
        "layer",
    }
)

# [0-9] rather than \d: \d also matches non-ASCII digits.
_NAME = r"[a-z0-9][a-z0-9_]*"
_SEQUENCE = r"[a-z]+[0-9]+"
_SHOT_SUFFIX = r"_[0-9]{4}"
_VERSION = r"v([0-9]{3,})"


def validate_name(kind: str, name: str, *, seq: str | None = None) -> None:
    """Raise InvalidName unless `name` is a valid `kind` name.

    For shots, `seq` is the sequence the shot must belong to. Without it, the
    name only has to look like `<sequence>_####`.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown name kind: {kind!r}")
    if name in RESERVED_WORDS:
        raise InvalidName(f"{name!r} is a reserved word and can't be used as a {kind} name.")
    if not re.fullmatch(_NAME, name):
        raise InvalidName(
            f"Invalid {kind} name {name!r}: use lowercase a-z, 0-9 and _, not starting with _."
        )
    if kind == "sequence" and not re.fullmatch(_SEQUENCE, name):
        raise InvalidName(f"Invalid sequence name {name!r}: expected letters then digits (sq010).")
    if kind == "shot":
        prefix = re.escape(seq) if seq else _SEQUENCE
        if not re.fullmatch(prefix + _SHOT_SUFFIX, name):
            expected = f"{seq}_####" if seq else "<sequence>_####"
            raise InvalidName(f"Invalid shot name {name!r}: expected {expected} (sq010_0010).")


def shot_sequence(shot: str) -> str:
    """The sequence a shot name belongs to: `sq010_0010` -> `sq010`."""
    match = re.fullmatch(f"({_SEQUENCE}){_SHOT_SUFFIX}", shot)
    if not match:
        raise InvalidName(f"Invalid shot name {shot!r}: expected <sequence>_#### (sq010_0010).")
    return match[1]


def format_version(version: int) -> str:
    return f"v{version:03d}"


def parse_version(text: str) -> int | None:
    """`v012` -> 12. Accepts 3 or more digits. Anything else -> None."""
    match = re.fullmatch(_VERSION, text)
    return int(match[1]) if match else None


def format_workfile(entity: str, dept: str, task: str, version: int, ext: str) -> str:
    return f"{entity}_{dept}_{task}_{format_version(version)}.{ext}"


def parse_workfile(filename: str, entity: str, dept: str, task: str) -> tuple[int, str] | None:
    """(version, ext) if `filename` is the managed workfile name for these folders, else None.

    entity/dept/task come from the folders. A name whose prefix disagrees with
    them is unmanaged: the folders are the truth (spec §6.2.7).
    """
    prefix = re.escape(f"{entity}_{dept}_{task}_")
    match = re.fullmatch(prefix + _VERSION + r"\.([a-z0-9]+)", filename)
    return (int(match[1]), match[2]) if match else None


def validate_extension(ext: str) -> None:
    """Workfile extensions are lowercase letters/digits without the dot: `hip`, `nk`, `blend`."""
    if not re.fullmatch(r"[a-z0-9]+", ext):
        raise InvalidName(
            f"Invalid extension {ext!r}: use lowercase letters and digits without the dot (hip)."
        )


def parse_frames(text: str) -> tuple[int, int]:
    """`1001-1096` -> (1001, 1096). Whitespace around the parts is allowed."""
    match = re.fullmatch(r"\s*([0-9]+)\s*-\s*([0-9]+)\s*", text)
    if not match:
        raise InvalidName(f"Invalid frame range {text!r}: expected START-END such as 1001-1096.")
    return int(match[1]), int(match[2])
