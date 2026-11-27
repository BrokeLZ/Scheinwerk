"""Item ids, slugs, categories, tags and variant names (spec §17.3, §17.4, §17.5)."""

from __future__ import annotations

import re
import secrets
import unicodedata
from random import Random

from scheinwerk.core.errors import InvalidName

SLUG_MAX = 40
UID_LEN = 6
UID_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
DEFAULT_VARIANT = "main"

_ITEM_ID = re.compile(rf"([a-z0-9][a-z0-9_]*)_([a-z0-9]{{{UID_LEN}}})")
_NAME = re.compile(r"[a-z0-9][a-z0-9_]*")
_VARIANT_TOKEN = re.compile(r"var(?:iation)?([0-9]+)", re.IGNORECASE)
# letters NFKD doesn't split into a base letter + accent
_SPELLED = str.maketrans(
    {
        "ß": "ss",
        "æ": "ae",
        "Æ": "ae",
        "ø": "o",
        "Ø": "o",
        "œ": "oe",
        "Œ": "oe",
        "ł": "l",
        "Ł": "l",
        "đ": "d",
        "Đ": "d",
        "þ": "th",
    }
)


def _clean(text: str) -> str:
    """Lowercase a-z0-9 with single `_` between words, accents dropped; may be ''."""
    text = unicodedata.normalize("NFKD", text.translate(_SPELLED))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def slug(name: str) -> str:
    """The id part made from a display name: `Rusty Metal 02` -> `rusty_metal_02`."""
    cleaned = _clean(name)[:SLUG_MAX].rstrip("_")
    if not cleaned:
        raise InvalidName(f"{name!r} has no letters or digits to make an item id from.")
    return cleaned


def is_item_id(text: str) -> bool:
    return _ITEM_ID.fullmatch(text) is not None


def split_item_id(item_id: str) -> tuple[str, str]:
    """`oak_k3f9q2` -> (`oak`, `k3f9q2`)."""
    match = _ITEM_ID.fullmatch(item_id)
    if not match:
        raise InvalidName(f"{item_id!r} is not an item id (<name>_<6 characters a-z0-9>).")
    return match[1], match[2]


def new_item_id(name: str, taken: set[str], rng: Random | None = None) -> str:
    """`<slug>_<uid>` with a uid no item in `taken` (every item id in the library) has."""
    used = {m[2] for t in taken if (m := _ITEM_ID.fullmatch(t))}
    choice = rng.choice if rng is not None else secrets.choice
    base = slug(name)
    while True:
        uid = "".join(choice(UID_CHARS) for _ in range(UID_LEN))
        if uid not in used:
            return f"{base}_{uid}"


def clean_category(text: str) -> str:
    """`Vegetation / Trees` -> `vegetation/trees`. Every segment must keep a letter or digit."""
    parts = [_clean(p) for p in text.strip().strip("/").split("/")]
    if not all(parts):
        raise InvalidName(f"Invalid category {text!r}: every '/'-separated part needs a name.")
    return "/".join(parts)


def with_parents(category: str) -> list[str]:
    """`a/b/c` -> [`a`, `a/b`, `a/b/c`]: an item is in every parent of its categories."""
    parts = category.split("/")
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def clean_tag(text: str) -> str:
    """`Worn Out` -> `worn_out`. Tags are flat: no `/`."""
    cleaned = _clean(text)
    if "/" in text or not cleaned:
        raise InvalidName(f"Invalid tag {text!r}: use letters, digits and spaces, no '/'.")
    return cleaned


def validate_variant(name: str) -> None:
    if not _NAME.fullmatch(name):
        raise InvalidName(
            f"Invalid variant name {name!r}: use lowercase a-z, 0-9 and _, not starting with _."
        )


def variant_from_token(token: str) -> str | None:
    """Megascans-style `var1` / `variation3` -> `var01` / `var03`; anything else -> None."""
    match = _VARIANT_TOKEN.fullmatch(token)
    return f"var{int(match[1]):02d}" if match else None
