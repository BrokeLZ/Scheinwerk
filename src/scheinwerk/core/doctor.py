"""Project health checks behind `sw doctor`. Reports only: never changes a file (spec §11)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from scheinwerk.core.errors import InvalidName
from scheinwerk.core.project import Project
from scheinwerk.core.templates import validate_name

KINDS = (
    "invalid name",
    "conflict copy",
    "absolute path",
    "empty version",
    "unpublished reference",
    "missing library item",
)
CHECKED_SUFFIXES = (".usd", ".usda", ".nk")
USD_SUFFIXES = (".usd", ".usda")

# A drive letter, /Users/, /Volumes/ or a UNC path (spec §7.1), not glued to a preceding
# letter or digit (so `https://` and `./x/Users/` don't count), up to the next separator.
_ABSOLUTE = re.compile(
    rb"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|/Users/|/Volumes/|\\\\[A-Za-z0-9])"
    rb"[^\x00-\x20\"'@\]\)<>|]{0,200}"
)
# A path through a task's work/ or cache/ folder (reserved names, so such a segment is always
# a task folder), from that segment on; the part before it is added by _find (spec §9.2).
_UNPUBLISHED = re.compile(rb"[/\\](?:work|cache)[/\\][^\x00-\x20\"'@\]\)<>|]{0,200}")
_PATH_BEFORE = re.compile(rb"[^\x00-\x20\"'@\[\(<>|=]{0,200}$")
_CHUNK = 1024 * 1024
# A library-relative path (`@model/<item id>/v004/…`, resolved through the search path) or a
# `$SW_LIBRARY/…` one (spec §17.8): <type>/<item id>/v###. Project paths in USD always start
# with ./ or ../, so they never match.
_LIBRARY_REF = re.compile(
    rb"(?:@|\$SW_LIBRARY/)([a-z0-9_]+/[a-z0-9][a-z0-9_]*_[a-z0-9]{6}/v[0-9]{3,})(?![0-9A-Za-z_])"
)


@dataclass(frozen=True)
class Issue:
    kind: str  # one of KINDS
    path: Path
    detail: str = ""


def check(project: Project, library: Path | None = None) -> list[Issue]:
    """`library`: this machine's library root (user setting), for library references."""
    issues = [
        *_invalid_names(project),
        *_conflict_copies(project),
        *_absolute_paths(project),
        *_empty_versions(project),
        *_unpublished_references(project),
        *_missing_library_items(project, library),
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
            found = _find(entry, _ABSOLUTE)
            if found is not None:
                yield Issue("absolute path", entry, found)


def _unpublished_references(project: Project) -> Iterator[Issue]:
    for entry in _walk(project, project.root):
        rel = entry.relative_to(project.root).parts
        if entry.suffix in USD_SUFFIXES and "publish" in rel and entry.is_file():
            found = _find(entry, _UNPUBLISHED, before=_PATH_BEFORE)
            if found is not None:
                yield Issue("unpublished reference", entry, found)


def _missing_library_items(project: Project, library: Path | None) -> Iterator[Issue]:
    """References to library versions that aren't finalized on this machine."""
    for entry in _walk(project, project.root):
        if entry.suffix in CHECKED_SUFFIXES and entry.is_file():
            for ref in sorted(_find_all(entry, _LIBRARY_REF)):
                if library is None:
                    yield Issue("missing library item", entry, f"{ref} (no library set up)")
                elif not (library / ref / "version.json").is_file():
                    yield Issue("missing library item", entry, ref)


def _find_all(path: Path, pattern: re.Pattern[bytes]) -> set[str]:
    """Every distinct first group of `pattern` in the file, read in overlapping chunks."""
    found, carry = set(), b""
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            buffer = carry + chunk
            found.update(m[1].decode("latin-1") for m in pattern.finditer(buffer))
            carry = buffer[-512:]
    return found


def _find(
    path: Path, pattern: re.Pattern[bytes], before: re.Pattern[bytes] | None = None
) -> str | None:
    """First match in the file, read in chunks so huge binary .usd files are fine. `before`
    extends the match to the left (matched against the text just before it)."""
    carry = b""
    with path.open("rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            buffer = carry + chunk
            match = pattern.search(buffer)
            at_end = not chunk
            if match and (match.end() < len(buffer) or at_end):
                start = match.start()
                if before is not None:
                    start -= len(before.search(buffer, max(start - 200, 0), start)[0])
                return buffer[start : match.end()].decode("latin-1")
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
