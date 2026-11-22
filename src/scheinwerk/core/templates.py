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


def format_workfile(entity: str, dept: str, task: str, version: int, ext: str | None = None) -> str:
    """`hero_mdl_main_v003.hip`, or without `ext` just `hero_mdl_main_v003`."""
    stem = f"{entity}_{dept}_{task}_{format_version(version)}"
    return f"{stem}.{ext}" if ext else stem


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


def format_product_stem(entity: str, product: str, version: int) -> str:
    """`hero_base_model_v002`: the recommended product/media file name (spec §5.3) without
    frame and extension. Copied "next version" paths end in it; the DCC adds the rest."""
    return f"{entity}_{product}_{format_version(version)}"


def step_name(text: str, delta: int, step: int = 10) -> str | None:
    """Move the trailing number of `text` to the next (delta > 0) or previous (delta < 0)
    multiple of `step`, keeping prefix and digit count: `sq020` -> `sq030`, `0040` -> `0030`.
    Never below `step`. None if `text` doesn't end in a number."""
    match = re.fullmatch(r"(.*?)([0-9]+)", text.strip())
    if not match:
        return None
    prefix, digits = match[1], match[2]
    number = int(digits)
    stepped = (number // step + 1) * step if delta > 0 else ((number - 1) // step) * step
    return f"{prefix}{max(stepped, step):0{len(digits)}d}"


def parse_fps(text: str) -> int | float:
    """`24` -> 24, `23.976` -> 23.976. Whole numbers come back as int."""
    try:
        fps = float(text.strip())
    except ValueError:
        fps = 0.0
    if not fps > 0:
        raise InvalidName(f"Invalid frame rate {text!r}: expected a number such as 24 or 23.976.")
    return int(fps) if fps.is_integer() else fps


def parse_resolution(text: str) -> tuple[int, int]:
    """`1920x1080` -> (1920, 1080)."""
    match = re.fullmatch(r"\s*([0-9]+)\s*[xX]\s*([0-9]+)\s*", text)
    if not match or not int(match[1]) or not int(match[2]):
        raise InvalidName(f"Invalid resolution {text!r}: expected WIDTHxHEIGHT such as 1920x1080.")
    return int(match[1]), int(match[2])
