"""Projects: finding, creating, config and scanning (spec §2.3, §4, §8.1, §10)."""

from __future__ import annotations

import copy
import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from scheinwerk.core.entities import Entity, check_frames
from scheinwerk.core.errors import (
    AlreadyExists,
    InvalidName,
    NotFound,
    NotInProject,
    ScheinwerkError,
)
from scheinwerk.core.fileio import check_free, exists_ci, read_json, write_json
from scheinwerk.core.hooks import post_create
from scheinwerk.core.templates import shot_sequence, validate_name

MARKER = "scheinwerk.json"

# Everything in scheinwerk.json except schema and name (spec §8.1).
DEFAULTS: dict = {
    "fps": 24,
    "resolution": [1920, 1080],
    "frame_start": 1001,
    "departments": {
        "asset": {
            "mdl": ["main"],
            "tex": ["main"],
            "lookdev": ["main"],
            "rig": ["main"],
            "fx": ["main"],
        },
        "sequence": {"layout": ["main"], "lgt": ["main"]},
        "shot": {
            "layout": ["main"],
            "anim": ["main"],
            "fx": ["main"],
            "lgt": ["main"],
            "comp": ["main"],
        },
    },
    "usd_layer_order": ["lgt", "fx", "anim", "layout"],
    "ignore": ["backup", "*.blend1", "*.autosave", ".DS_Store", "._*", "Thumbs.db", "@eaDir", "*~"],
    "templates": {},
}

# Always offered when creating an asset, next to the categories that exist (spec §5.2).
DEFAULT_CATEGORIES = ("char", "prop", "env")

# Folders Project.create makes next to scheinwerk.json.
LAYOUT = ("assets", "shots", "shared/hooks", "shared/templates", "io/in", "io/out")

# Folder contents that mark an asset (as opposed to a category), besides a template department.
ASSET_MARKERS = ("entity.json", "publish", "media")


def _next_step(numbers: list[int], step: int = 10) -> int:
    return (max(numbers, default=0) // step + 1) * step


def find_root(path: str | os.PathLike[str]) -> Path | None:
    """Walk up from `path` (which need not exist) to the folder holding scheinwerk.json."""
    start = Path(path).absolute()
    for folder in (start, *start.parents):
        if (folder / MARKER).is_file():
            return folder
    return None


def read_config(root: Path) -> dict:
    config = read_json(root / MARKER)
    if config is None:
        raise ScheinwerkError(f"Can't read {root / MARKER}: missing or not valid JSON.")
    return config


@dataclass(frozen=True)
class Project:
    root: Path
    config: dict = field(compare=False, repr=False)

    # --- find / create ------------------------------------------------------

    @classmethod
    def find(cls, path: str | os.PathLike[str]) -> Project | None:
        root = find_root(path)
        return None if root is None else cls(root, read_config(root))

    @classmethod
    def create(cls, folder: str | os.PathLike[str], name: str, **settings: object) -> Project:
        folder = Path(folder).absolute()
        validate_name("project", name)
        unknown = sorted(set(settings) - set(DEFAULTS))
        if unknown:
            raise TypeError(f"unknown project settings: {', '.join(unknown)}")
        if (folder / MARKER).exists():
            raise AlreadyExists(f"{folder} is already a Scheinwerk project.")
        outer = find_root(folder)
        if outer is not None:
            raise ScheinwerkError(
                f"{folder} is inside the project {outer}: projects can't be nested."
            )
        config = {"schema": 1, "name": name, **copy.deepcopy(DEFAULTS), **settings}
        for sub in LAYOUT:
            (folder / sub).mkdir(parents=True, exist_ok=True)
        write_json(folder / MARKER, config)
        return cls(folder, config)

    # --- config -------------------------------------------------------------

    def setting(self, key: str) -> object:
        return self.config.get(key, DEFAULTS[key])

    def department_template(self, entity_type: str) -> dict[str, list[str]]:
        return self.setting("departments").get(entity_type, {})

    def department_names(self) -> set[str]:
        """Every department name in the template, for any entity type."""
        return {d for per_type in self.setting("departments").values() for d in per_type}

    def ignored(self, name: str) -> bool:
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self.setting("ignore"))

    def scan(self, folder: Path, *, dirs_only: bool = True) -> list[Path]:
        """Entries of `folder` minus ignored ones, sorted by name. Missing folder -> []."""
        try:
            entries = list(folder.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return []
        keep = (e for e in entries if not self.ignored(e.name) and (not dirs_only or e.is_dir()))
        return sorted(keep, key=lambda e: e.name)

    # --- paths --------------------------------------------------------------

    def rel(self, path: str | os.PathLike[str]) -> str:
        """Root-relative POSIX path, the only form ever stored in a project."""
        try:
            return Path(path).absolute().relative_to(self.root).as_posix()
        except ValueError:
            raise NotInProject(f"{path} is not inside the project {self.root}.") from None

    def abs(self, rel: str) -> Path:
        posix = PurePosixPath(rel.replace("\\", "/"))
        if posix.is_absolute() or Path(rel).is_absolute():
            raise ScheinwerkError(f"Expected a root-relative path, got {rel!r}.")
        return self.root.joinpath(*posix.parts)

    # --- scanning -----------------------------------------------------------

    def _is_asset_dir(self, folder: Path) -> bool:
        if any((folder / m).exists() for m in ASSET_MARKERS):
            return True
        departments = self.department_names()
        return any(c.name in departments for c in self.scan(folder))

    def assets(self) -> list[Entity]:
        found = []
        for folder in self.scan(self.root / "assets"):
            if self._is_asset_dir(folder):
                found.append(Entity(self, "asset", folder.name))
            else:
                found += [
                    Entity(self, "asset", a.name, category=folder.name) for a in self.scan(folder)
                ]
        return sorted(found, key=lambda e: (e.category or "", e.name))

    def categories(self) -> list[str]:
        return [f.name for f in self.scan(self.root / "assets") if not self._is_asset_dir(f)]

    def sequences(self) -> list[Entity]:
        return [
            Entity(self, "sequence", f.name, sequence=f.name)
            for f in self.scan(self.root / "shots")
        ]

    def shots(self, seq: str | None = None) -> list[Entity]:
        seqs = [seq] if seq else [s.name for s in self.scan(self.root / "shots")]
        return [
            Entity(self, "shot", f.name, sequence=s)
            for s in seqs
            for f in self.scan(self.root / "shots" / s)
            if f.name != "_seq"
        ]

    def entity(self, name: str) -> Entity:
        """Resolve a unique name; `asset:`, `shot:` or `seq:` picks the type (spec §11)."""
        prefix, _, bare = name.rpartition(":")
        types = {"": None, "asset": "asset", "shot": "shot", "seq": "sequence"}
        if prefix not in types:
            raise NotFound(f"Unknown prefix {prefix!r}: use asset:, shot: or seq:.")
        want = types[prefix]
        everything = [*self.assets(), *self.sequences(), *self.shots()]
        matches = [e for e in everything if e.name == bare and want in (None, e.type)]
        if not matches:
            raise NotFound(f"No asset, shot or sequence named {bare!r}.")
        if len(matches) > 1:
            short = {"asset": "asset", "shot": "shot", "sequence": "seq"}
            options = " or ".join(sorted({f"{short[e.type]}:{bare}" for e in matches}))
            raise ScheinwerkError(f"{bare!r} is ambiguous: use {options}.")
        return matches[0]

    # --- name suggestions (GUI "+" buttons) ----------------------------------

    def category_choices(self) -> list[str]:
        """The default categories, then any others that exist."""
        return list(dict.fromkeys([*DEFAULT_CATEGORIES, *self.categories()]))

    def next_sequence_name(self) -> str:
        """`sq010`, `sq020`, …: the next multiple of 10 above the highest `sq###`."""
        numbers = [
            int(m[1]) for s in self.sequences() if (m := re.fullmatch(r"sq([0-9]+)", s.name))
        ]
        return f"sq{_next_step(numbers):03d}"

    def next_shot_name(self, seq: str) -> str:
        """`sq010_0010`, `sq010_0020`, …: the next multiple of 10 in that sequence."""
        pattern = re.escape(seq) + r"_([0-9]{4})"
        numbers = [int(m[1]) for s in self.shots(seq) if (m := re.fullmatch(pattern, s.name))]
        number = _next_step(numbers)
        if number > 9999:
            raise ScheinwerkError(f"No shot numbers left in {seq} (shots have 4 digits).")
        return f"{seq}_{number:04d}"

    # --- creating -----------------------------------------------------------

    def _check_not_department(self, kind: str, name: str) -> None:
        if name in self.department_names():
            raise InvalidName(f"{name!r} is a department name and can't be a {kind} name.")

    def create_category(self, name: str) -> Path:
        validate_name("category", name)
        self._check_not_department("category", name)
        path = self.root / "assets" / name
        check_free(path)
        path.mkdir(parents=True)
        return path

    def create_asset(self, name: str, category: str | None = None) -> Entity:
        validate_name("asset", name)
        self._check_not_department("asset", name)
        parent = self.root / "assets"
        if category is not None:
            validate_name("category", category)
            self._check_not_department("category", category)
            parent /= category
            if parent.is_dir() and self._is_asset_dir(parent):
                raise InvalidName(f"{category!r} is an asset, not a category.")
        if any(a.name.lower() == name.lower() for a in self.assets()):
            raise AlreadyExists(f"An asset named {name!r} already exists.")
        path = parent / name
        check_free(path)
        path.mkdir(parents=True)
        write_json(path / "entity.json", {"schema": 1})
        post_create("asset", path)
        return Entity(self, "asset", name, category=category)

    def create_sequence(self, name: str) -> Entity:
        validate_name("sequence", name)
        path = self.root / "shots" / name
        check_free(path)
        path.mkdir(parents=True)
        post_create("sequence", path)
        return Entity(self, "sequence", name, sequence=name)

    def create_shot(self, name: str, frames: tuple[int, int] | None = None) -> Entity:
        validate_name("shot", name)
        if frames is not None:
            check_frames(*frames)
        seq = shot_sequence(name)
        if not exists_ci(self.root / "shots", seq):
            self.create_sequence(seq)
        path = self.root / "shots" / seq / name
        check_free(path)
        path.mkdir()
        data: dict = {"schema": 1}
        if frames is not None:
            data["frames"] = list(frames)
        write_json(path / "entity.json", data)
        post_create("shot", path)
        return Entity(self, "shot", name, sequence=seq)
