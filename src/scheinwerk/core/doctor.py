"""Project health checks behind `sw doctor`. Reports only: never changes a file (spec §11)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from scheinwerk.core.errors import InvalidName
from scheinwerk.core.project import Project
from scheinwerk.core.templates import validate_name

KINDS = ("invalid name", "conflict copy", "absolute path", "empty version")
CHECKED_SUFFIXES = (".usd", ".usda", ".nk")

# A drive letter, /Users/, /Volumes/ or a UNC path (spec §7.1), not glued to a preceding
# letter or digit (so `https://` and `./x/Users/` don't count), up to the next separator.
_ABSOLUTE = re.compile(
    rb"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|/Users/|/Volumes/|\\\\[A-Za-z0-9])"
    rb"[^\x00-\x20\"'@\]\)<>|]{0,200}"
)
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Issue:
    kind: str  # one of KINDS
    path: Path
    detail: str = ""


def check(project: Project) -> list[Issue]:
    issues = [
        *_invalid_names(project),
        *_conflict_copies(project),
        *_absolute_paths(project),
        *_empty_versions(project),
    ]
    return sorted(issues, key=lambda i: (KINDS.index(i.kind), i.path.as_posix()))


def _invalid_names(project: Project) -> Iterator[Issue]:
    for category in project.categories():
        try:
            validate_name("category", category)
        except InvalidName:
            yield Issue("invalid name", project.root / "assets" / category)
    entities = [*project.assets(), *project.sequences(), *project.shots()]
    for entity in entities:
        if not entity.valid:
            # A sequence's folder is shots/<seq>; its entity path is the _seq inside.
            yield Issue(
                "invalid name", entity.path.parent if entity.type == "sequence" else entity.path
            )
        for dept in entity.departments():
            if not dept.valid:
                yield Issue("invalid name", dept.path)
            for task in dept.tasks():
                if not task.valid:
                    yield Issue("invalid name", task.path)
        for product in [*entity.products(), *entity.media()]:
            if not product.valid:
                yield Issue("invalid name", product.path)


def _walk(project: Project, folder: Path) -> Iterator[Path]:
    """Every non-ignored entry below `folder`, skipping cache/ (WIP, never referenced)."""
    for entry in project.scan(folder, dirs_only=False):
        yield entry
        if entry.is_dir() and entry.name != "cache":
            yield from _walk(project, entry)


def _conflict_copies(project: Project) -> Iterator[Issue]:
    for entry in _walk(project, project.root):
        if "Conflict" in entry.name:
            yield Issue("conflict copy", entry)


def _absolute_paths(project: Project) -> Iterator[Issue]:
    for entry in _walk(project, project.root):
        if entry.suffix in CHECKED_SUFFIXES and entry.is_file():
            found = _find_absolute(entry)
            if found is not None:
                yield Issue("absolute path", entry, found)


def _find_absolute(path: Path) -> str | None:
    """First absolute path in the file, read in chunks so huge binary .usd files are fine."""
    carry = b""
    with path.open("rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            buffer = carry + chunk
            match = _ABSOLUTE.search(buffer)
            at_end = not chunk
            if match and (match.end() < len(buffer) or at_end):
                return match[0].decode("latin-1")
            if at_end:
                return None
            keep = min(match.start() if match else len(buffer), max(len(buffer) - 512, 0))
            carry = buffer[keep:]


def _empty_versions(project: Project) -> Iterator[Issue]:
    for entity in [*project.assets(), *project.sequences(), *project.shots()]:
        for product in [*entity.products(), *entity.media()]:
            for version in product.versions():
                if version.empty:
                    yield Issue("empty version", version.path)
