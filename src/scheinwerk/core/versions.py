"""Products, USD layers and media, and their v### folders (spec §5.4, §10)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from scheinwerk.core.context import Context
from scheinwerk.core.errors import InvalidName
from scheinwerk.core.fileio import read_json
from scheinwerk.core.templates import (
    format_product_file,
    format_product_stem,
    format_version,
    parse_version,
    validate_name,
)
from scheinwerk.core.usd_pointer import read_pointer

if TYPE_CHECKING:
    from scheinwerk.core.project import Project


@dataclass(frozen=True)
class Version:
    project: Project = field(repr=False)
    path: Path

    @property
    def number(self) -> int:
        return parse_version(self.path.name)

    @property
    def info(self) -> dict | None:
        """version.json, if present and valid. Never required (spec §8.3)."""
        return read_json(self.path / "version.json")

    def files(self) -> list[Path]:
        """Everything in the folder except version.json and ignored entries."""
        return [
            p for p in self.project.scan(self.path, dirs_only=False) if p.name != "version.json"
        ]

    @property
    def empty(self) -> bool:
        return not self.files()


@dataclass(frozen=True)
class Product:
    """A versioned folder: `publish/<name>`, `publish/_usd/<layer>` or `media/<name>`."""

    project: Project = field(repr=False)
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def usd(self) -> bool:
        return self.path.parent.name == "_usd"

    @property
    def is_media(self) -> bool:
        return self.path.parent.name == "media"

    @property
    def kind(self) -> str:
        """The name kind for validation: "layer", "media" or "product"."""
        return "layer" if self.usd else "media" if self.is_media else "product"

    @property
    def valid(self) -> bool:
        try:
            validate_name(self.kind, self.name)
        except InvalidName:
            return False
        return True

    @property
    def pointer(self) -> Path | None:
        return self.path / f"{self.name}.usd" if self.usd else None

    def versions(self) -> list[Version]:
        """v### folders, newest first, empty ones included."""
        found = [Version(self.project, d) for d in self.project.scan(self.path)]
        return sorted((v for v in found if v.number is not None), key=lambda v: -v.number)

    def latest(self) -> Version | None:
        """Highest version that has files in it (spec §5.4)."""
        return next((v for v in self.versions() if not v.empty), None)

    def current(self) -> Version | None:
        """USD only: the version the pointer layer references."""
        target = read_pointer(self.pointer) if self.usd else None
        if not target:
            return None
        folder = PurePosixPath(target).parts[0]
        return (
            Version(self.project, self.path / folder) if parse_version(folder) is not None else None
        )

    def highest(self) -> int | None:
        """The highest v### number, empty folders included: the version a DCC node writes
        to until a new one is made (spec §13.2)."""
        return max((v.number for v in self.versions()), default=None)

    def file_path(self, version: int, ext: str, frame: int | None = None) -> Path:
        """`…/v002/hero_pants_v002[.1001].ext`, whether or not it exists."""
        entity = Context.from_path(self.path).entity
        name = format_product_file(entity, self.name, version, ext, frame)
        return self.path / format_version(version) / name

    def next_version_path(self) -> Path:
        """Create the next v### folder and return the file path in it without extension:
        `…/base_model/v002/hero_base_model_v002` (spec §5.3). Nothing else is created."""
        entity = Context.from_path(self.path).entity
        folder = self.next_version_dir()
        return folder / format_product_stem(entity, self.name, parse_version(folder.name))

    def next_version_dir(self) -> Path:
        """Create and return the next v### folder. Never reuses an existing one."""
        validate_name(self.kind, self.name)
        number = max((v.number for v in self.versions()), default=0) + 1
        while True:
            folder = self.path / f"v{number:03d}"
            try:
                folder.mkdir(parents=True)
                return folder
            except FileExistsError:
                number += 1  # someone else got there first


@dataclass(frozen=True)
class FileGroup:
    """One file, or a numbered sequence shown as `name.####.ext` (spec §12.1, Media view)."""

    label: str
    paths: tuple[Path, ...]
    frames: tuple[int, int] | None = None

    @property
    def count(self) -> int:
        return len(self.paths)

    @property
    def missing(self) -> int:
        return self.frames[1] - self.frames[0] + 1 - self.count if self.frames else 0


_FRAME = re.compile(r"(?P<head>.+)\.(?P<frame>[0-9]+)\.(?P<ext>[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?)")


def file_sequences(paths: list[Path]) -> list[FileGroup]:
    """Group `name.<frame>.<ext>` files into sequences; other files stay single. Sorted by label."""
    sequences: dict[str, list[tuple[int, Path]]] = {}
    groups = []
    for path in paths:
        match = _FRAME.fullmatch(path.name)
        if match:
            label = f"{match['head']}.{'#' * len(match['frame'])}.{match['ext']}"
            sequences.setdefault(label, []).append((int(match["frame"]), path))
        else:
            groups.append(FileGroup(path.name, (path,)))
    for label, items in sequences.items():
        items.sort()
        groups.append(FileGroup(label, tuple(p for _, p in items), (items[0][0], items[-1][0])))
    return sorted(groups, key=lambda g: g.label)
