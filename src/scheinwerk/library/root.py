"""The library root and `library.json` (spec §17.2, §17.3)."""

from __future__ import annotations

import copy
import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from scheinwerk.core.errors import AlreadyExists, InvalidName, NotFound
from scheinwerk.core.fileio import read_json, write_json
from scheinwerk.core.settings import load_settings

if TYPE_CHECKING:
    from scheinwerk.library.items import Item

MARKER = "library.json"
WORKSHOP = "_workshop"
WORKSHOP_PROJECT = "library_workshop"
# The workshop project's department template (spec §17.2): no sequences or shots.
WORKSHOP_DEPARTMENTS = {
    "asset": {"mdl": ["main", "speedtree"], "lookdev": ["main"], "tex": ["main"]},
    "sequence": {},
    "shot": {},
}
TYPES = ("hdri", "texture", "texture_set", "model")
DEFAULTS = {
    "name": "library",
    "working_space": "ACEScg",
    "ignore": ["backup", ".DS_Store", "._*", "Thumbs.db", "@eaDir", "*~"],
}


@dataclass(frozen=True)
class Library:
    root: Path
    config: dict = field(repr=False, compare=False)

    @classmethod
    def open(cls, root: str | os.PathLike[str]) -> Library:
        root = Path(root).absolute()
        data = read_json(root / MARKER)
        if data is None:
            raise NotFound(f"{root} is not a library: it has no valid {MARKER}.")
        return cls(root, {**copy.deepcopy(DEFAULTS), **data})

    @classmethod
    def create(cls, folder: str | os.PathLike[str], name: str = DEFAULTS["name"]) -> Library:
        """Write library.json in `folder` (created if missing). The workshop project is made
        by the caller (`sw lib init`): the library package never touches projects."""
        folder = Path(folder).absolute()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", name):
            raise InvalidName(f"Invalid library name {name!r}: use lowercase a-z, 0-9 and _.")
        if (folder / MARKER).exists():
            raise AlreadyExists(f"{folder} is already a library.")
        folder.mkdir(parents=True, exist_ok=True)
        config = {"schema": 1, **copy.deepcopy(DEFAULTS), "name": name}
        write_json(folder / MARKER, config)
        return cls(folder, config)

    @property
    def name(self) -> str:
        return self.config["name"]

    @property
    def working_space(self) -> str:
        return self.config["working_space"]

    @property
    def workshop(self) -> Path:
        return self.root / WORKSHOP

    def ignored(self, name: str) -> bool:
        return any(fnmatch.fnmatchcase(name, p) for p in self.config["ignore"])

    def scan(self, folder: Path, *, dirs_only: bool = True) -> list[Path]:
        """Entries of `folder` minus ignored ones, sorted by name. Missing folder -> []."""
        try:
            entries = list(folder.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return []
        keep = (e for e in entries if not self.ignored(e.name) and (not dirs_only or e.is_dir()))
        return sorted(keep, key=lambda e: e.name)

    def unknown(self) -> list[Path]:
        """Root entries that are neither a type folder, library.json nor the workshop."""
        known = {*TYPES, MARKER, WORKSHOP}
        return [e for e in self.scan(self.root, dirs_only=False) if e.name not in known]

    def items(self, type_: str | None = None) -> list[Item]:
        from scheinwerk.library.items import Item

        types = TYPES if type_ is None else (type_,)
        if type_ is not None and type_ not in TYPES:
            raise InvalidName(f"Unknown item type {type_!r}: one of {', '.join(TYPES)}.")
        return [Item(self, d) for t in types for d in self.scan(self.root / t)]


def configured_library() -> Library:
    """This machine's library: the user setting `library` (spec §17.2)."""
    root = load_settings().get("library")
    if not root:
        raise NotFound("No library is set up on this machine: run `sw lib init <folder>`.")
    if not (Path(root) / MARKER).is_file():
        raise NotFound(f"The library set up on this machine is missing: {root}")
    return Library.open(root)
