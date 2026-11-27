"""Items, their versions and variants, item.json and version.json (spec §17.3, §17.4).

The folder tree is the truth: nothing here caches; every call reads the disk again.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from random import Random

from scheinwerk.core.errors import AlreadyExists, InvalidName, NotFound
from scheinwerk.core.fileio import check_free, read_json, write_json
from scheinwerk.core.templates import format_version, parse_version
from scheinwerk.core.version_dirs import next_version_dir, version_dirs
from scheinwerk.library.ids import (
    clean_category,
    clean_tag,
    is_item_id,
    new_item_id,
    validate_variant,
)
from scheinwerk.library.root import TYPES, Library

ITEM_JSON = "item.json"
VERSION_JSON = "version.json"


@dataclass(frozen=True)
class Item:
    library: Library = field(repr=False)
    path: Path

    @property
    def type(self) -> str:
        return self.path.parent.name

    @property
    def id(self) -> str:
        return self.path.name

    @property
    def valid(self) -> bool:
        """The folder name is an item id (spec §17.3). Invalid ones are listed, flagged."""
        return is_item_id(self.id)

    @property
    def meta(self) -> dict:
        """item.json, or {} when it is missing or broken (missing keys read as no info)."""
        return read_json(self.path / ITEM_JSON) or {}

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or self.id)

    @property
    def categories(self) -> list[str]:
        return list(self.meta.get("categories") or [])

    @property
    def tags(self) -> list[str]:
        return list(self.meta.get("tags") or [])

    @property
    def added(self) -> str:
        """When the first finalized version was made (ISO text, sorts by time); '' if none."""
        first = next((v for v in reversed(self.versions()) if v.finalized), None)
        return str((first.info or {}).get("created") or "") if first else ""

    def versions(self) -> list[LibraryVersion]:
        """v### folders, newest first, incomplete ones included."""
        return [LibraryVersion(self, d) for d in version_dirs(self.path)]

    def latest(self) -> LibraryVersion | None:
        """The highest finalized version (spec §17.3)."""
        return next((v for v in self.versions() if v.finalized), None)

    def version(self, number: int) -> LibraryVersion:
        path = self.path / format_version(number)
        if not path.is_dir():
            raise NotFound(f"{self.id} has no {format_version(number)}.")
        return LibraryVersion(self, path)

    def next_version_dir(self) -> Path:
        """Create the next v### folder. It stays incomplete until finalize()."""
        return next_version_dir(self.path)


@dataclass(frozen=True)
class LibraryVersion:
    item: Item = field(repr=False)
    path: Path

    @property
    def number(self) -> int:
        return parse_version(self.path.name)

    @property
    def info(self) -> dict | None:
        return read_json(self.path / VERSION_JSON)

    @property
    def finalized(self) -> bool:
        """version.json exists and is valid. Incomplete versions are never offered."""
        return self.info is not None

    def variants(self) -> dict[str, int]:
        """Every variant this version offers -> the version number holding its files."""
        entries = (self.info or {}).get("variants") or {}
        return {
            name: entry["version"]
            for name, entry in entries.items()
            if isinstance(entry, dict) and isinstance(entry.get("version"), int)
        }

    def variant_dir(self, variant: str) -> Path:
        variants = self.variants()
        if variant not in variants:
            raise NotFound(
                f"{self.item.id} {self.path.name} has no variant {variant!r}"
                f" (it has: {', '.join(variants) or 'none'})."
            )
        return self.item.path / format_version(variants[variant])

    def thumbnail(self, variant: str) -> Path:
        """Where the variant's preview is (it may not exist yet, spec §17.7)."""
        return self.variant_dir(variant) / f"thumb_{variant}.jpg"

    def variant_problems(self) -> dict[str, str]:
        """Variant name -> what is wrong with it; empty when all are fine."""
        problems = {}
        for name, entry in ((self.info or {}).get("variants") or {}).items():
            version = entry.get("version") if isinstance(entry, dict) else None
            if not _variant_name_ok(name):
                problems[name] = "invalid variant name"
            elif not isinstance(version, int) or version < 1:
                problems[name] = "names no version"
            elif version > self.number:
                newer = format_version(version)
                problems[name] = f"points at {newer}, which is newer than this version"
            elif version != self.number:
                holder = self.item.path / format_version(version)
                if not (holder / VERSION_JSON).is_file():
                    problems[name] = f"points at {format_version(version)}, which is incomplete"
        return dict(sorted(problems.items()))


def _variant_name_ok(name: str) -> bool:
    try:
        validate_variant(name)
    except InvalidName:
        return False
    return True


def create_item(library: Library, type_: str, name: str, rng: Random | None = None) -> Item:
    """A new, empty item with a fresh id (spec §17.3) and its item.json."""
    if type_ not in TYPES:
        raise InvalidName(f"Unknown item type {type_!r}: one of {', '.join(TYPES)}.")
    taken = {i.id for i in library.items()}
    path = library.root / type_ / new_item_id(name, taken, rng)
    check_free(path)
    path.mkdir(parents=True)
    write_json(path / ITEM_JSON, {"schema": 1, "name": name.strip(), "categories": [], "tags": []})
    return Item(library, path)


def finalize(version: LibraryVersion, info: dict) -> None:
    """Write version.json: the last write of a version, which makes it final (spec §17.4)."""
    if version.finalized:
        raise AlreadyExists(f"{version.item.id} {version.path.name} is already finalized.")
    variants = info.get("variants")
    if not isinstance(variants, dict) or not variants:
        raise InvalidName("A finalized version needs `variants`: at least one.")
    for name, entry in variants.items():
        validate_variant(name)
        number = entry.get("version") if isinstance(entry, dict) else None
        if not isinstance(number, int) or number < 1:
            raise InvalidName(f"Variant {name!r} names no version.")
        if number > version.number:
            raise InvalidName(f"Variant {name!r} points at a newer version ({number}).")
        holder = version.item.path / format_version(number)
        if number != version.number and not (holder / VERSION_JSON).is_file():
            raise NotFound(f"Variant {name!r} points at {holder.name}, which isn't finalized.")
    data = {"schema": 1, **info}
    data.setdefault("created", datetime.now().astimezone().isoformat(timespec="seconds"))
    data.setdefault("user", _user())
    write_json(version.path / VERSION_JSON, data)


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # no user name in some service/container environments
        return ""


def update_meta(
    item: Item,
    name: str | None = None,
    add_categories: list[str] = (),
    remove_categories: list[str] = (),
    add_tags: list[str] = (),
    remove_tags: list[str] = (),
    fields: dict | None = None,
) -> None:
    """Edit item.json (the only file edited after creation). Unknown keys are kept.
    Removals win over additions of the same value. `fields`: the other metadata (spec §17.4);
    an empty value removes the key."""
    data = {"schema": 1, **item.meta}
    for key, value in (fields or {}).items():
        value = _check_field(key, value)
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    if name is not None:
        if not name.strip():
            raise InvalidName("The display name can't be empty.")
        data["name"] = name.strip()
    data.setdefault("name", item.id)
    cats = set(data.get("categories") or []) | {clean_category(c) for c in add_categories}
    cats -= {clean_category(c) for c in remove_categories}
    tags = set(data.get("tags") or []) | {clean_tag(t) for t in add_tags}
    tags -= {clean_tag(t) for t in remove_tags}
    data["categories"], data["tags"] = sorted(cats), sorted(tags)
    write_json(item.path / ITEM_JSON, data)


TEXT_FIELDS = ("description", "credits", "license", "source_url")


def _check_field(key: str, value: object) -> object:
    """A cleaned item.json value, or None to remove it."""
    if value in (None, "", []):
        return None
    if key in TEXT_FIELDS:
        if not isinstance(value, str):
            raise InvalidName(f"{key} must be text.")
        return value.strip() or None
    if key == "size_m":
        ok = isinstance(value, (list, tuple)) and len(value) == 2
        if not ok or not all(isinstance(v, (int, float)) and v > 0 for v in value):
            raise InvalidName("size_m must be a width and a height in metres, both above 0.")
        return [float(v) for v in value]
    if key == "displacement":
        ok = isinstance(value, dict) and set(value) == {"mid", "height_m"}
        if not ok or not all(isinstance(v, (int, float)) for v in value.values()):
            raise InvalidName("displacement must have `mid` and `height_m` (numbers).")
        return {"mid": float(value["mid"]), "height_m": float(value["height_m"])}
    raise InvalidName(f"{key!r} is not an item.json field that can be set here.")


def find_item(library: Library, query: str) -> Item:
    """An item by id, or by display name (any case) when that name is unique."""
    items = library.items()
    by_id = [i for i in items if i.id == query]
    if len(by_id) == 1:
        return by_id[0]
    wanted = query.strip().casefold()
    by_name = [i for i in items if i.name.strip().casefold() == wanted]
    if len(by_name) == 1:
        return by_name[0]
    if by_name:
        ids = ", ".join(f"{i.type}/{i.id}" for i in by_name)
        raise NotFound(f"{len(by_name)} items are called {query!r}: {ids}. Use the id.")
    raise NotFound(f"No library item {query!r}.")
