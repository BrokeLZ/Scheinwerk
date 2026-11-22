"""Products, USD layers and media, and their v### folders (spec §5.4, §10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from scheinwerk.core.fileio import read_json
from scheinwerk.core.templates import parse_version, validate_name
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

    def next_version_dir(self) -> Path:
        """Create and return the next v### folder. Never reuses an existing one."""
        validate_name("layer" if self.usd else "media" if self.is_media else "product", self.name)
        number = max((v.number for v in self.versions()), default=0) + 1
        while True:
            folder = self.path / f"v{number:03d}"
            try:
                folder.mkdir(parents=True)
                return folder
            except FileExistsError:
                number += 1  # someone else got there first
