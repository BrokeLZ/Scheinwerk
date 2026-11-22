"""Entities, departments, tasks and workfiles. Thin and path-backed: nothing cached (spec §10).

Asset, Shot and Sequence are one class, `Entity`, told apart by `type`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from scheinwerk.core.errors import InvalidName, NotFound, ScheinwerkError
from scheinwerk.core.fileio import check_free, copy_new, read_json, write_json
from scheinwerk.core.hooks import post_create
from scheinwerk.core.templates import (
    format_workfile,
    parse_workfile,
    validate_extension,
    validate_name,
)
from scheinwerk.core.versions import Product

if TYPE_CHECKING:
    from scheinwerk.core.project import Project

ENTITY_AREAS = ("publish", "media")


def check_frames(start: int, end: int) -> None:
    if start > end:
        raise ScheinwerkError(f"Frame range {start}-{end} ends before it starts.")


def _valid(kind: str, name: str, seq: str | None = None) -> bool:
    try:
        validate_name(kind, name, seq=seq)
    except InvalidName:
        return False
    return True


def _template_order(template: list[str], found: list[str]) -> list[str]:
    """Template entries in template order, then everything else A-Z."""
    return [n for n in template if n in found] + sorted(n for n in found if n not in template)


@dataclass(frozen=True)
class Entity:
    project: Project = field(repr=False)
    type: str  # "asset" | "shot" | "sequence"
    name: str
    category: str | None = None
    sequence: str | None = None

    @property
    def path(self) -> Path:
        root = self.project.root
        if self.type == "asset":
            return (
                root / "assets" / self.category / self.name
                if self.category
                else root / "assets" / self.name
            )
        if self.type == "shot":
            return root / "shots" / self.sequence / self.name
        return root / "shots" / self.name / "_seq"

    @property
    def valid(self) -> bool:
        return _valid(self.type, self.name, self.sequence if self.type == "shot" else None)

    # --- frames -------------------------------------------------------------

    @property
    def frames(self) -> tuple[int, int] | None:
        if self.type == "sequence":
            ranges = [s.frames for s in self.project.shots(self.name) if s.frames]
            return (min(r[0] for r in ranges), max(r[1] for r in ranges)) if ranges else None
        frames = (read_json(self.path / "entity.json") or {}).get("frames")
        if (
            isinstance(frames, list)
            and len(frames) == 2
            and all(isinstance(f, int) for f in frames)
        ):
            return (frames[0], frames[1])
        return None

    def set_frames(self, start: int, end: int) -> None:
        if self.type == "sequence":
            raise ScheinwerkError("A sequence's frame range comes from its shots.")
        check_frames(start, end)
        data = read_json(self.path / "entity.json") or {"schema": 1}
        data["frames"] = [start, end]
        write_json(self.path / "entity.json", data)

    # --- departments --------------------------------------------------------

    def departments(self) -> list[Department]:
        found = [d.name for d in self.project.scan(self.path) if d.name not in ENTITY_AREAS]
        template = list(self.project.department_template(self.type))
        return [Department(self, n) for n in _template_order(template, found)]

    def department(self, name: str) -> Department:
        return Department(self, name)

    def create_department(self, name: str, tasks: tuple[str, ...] = ("main",)) -> Department:
        validate_name("dept", name)
        if self.type != "sequence" and not self.path.is_dir():  # _seq is made on demand
            raise NotFound(f"{self.path} does not exist.")
        path = self.path / name
        check_free(path)
        path.mkdir(parents=True)
        post_create("dept", path)
        dept = Department(self, name)
        for task in tasks:
            dept.create_task(task)
        return dept

    # --- products and media -------------------------------------------------

    def products(self, usd: bool | None = None) -> list[Product]:
        """USD layers first, then other products, each A-Z. `usd` filters."""
        publish = self.path / "publish"
        layers = (
            []
            if usd is False
            else [Product(self.project, d) for d in self.project.scan(publish / "_usd")]
        )
        others = (
            []
            if usd is True
            else [Product(self.project, d) for d in self.project.scan(publish) if d.name != "_usd"]
        )
        return layers + others

    def media(self) -> list[Product]:
        return [Product(self.project, d) for d in self.project.scan(self.path / "media")]

    def create_product(self, name: str) -> Product:
        return self._create_versioned("product", self.path / "publish" / name)

    def create_media(self, name: str) -> Product:
        return self._create_versioned("media", self.path / "media" / name)

    def _create_versioned(self, kind: str, path: Path) -> Product:
        validate_name(kind, path.name)
        check_free(path)
        path.mkdir(parents=True)
        post_create(kind, path)
        return Product(self.project, path)


@dataclass(frozen=True)
class Department:
    entity: Entity
    name: str

    @property
    def path(self) -> Path:
        return self.entity.path / self.name

    @property
    def template_tasks(self) -> list[str]:
        return self.entity.project.department_template(self.entity.type).get(self.name, [])

    @property
    def custom(self) -> bool:
        return self.name not in self.entity.project.department_template(self.entity.type)

    @property
    def valid(self) -> bool:
        return _valid("dept", self.name)

    def tasks(self) -> list[Task]:
        found = [d.name for d in self.entity.project.scan(self.path)]
        return [Task(self, n) for n in _template_order(self.template_tasks, found)]

    def task(self, name: str) -> Task:
        return Task(self, name)

    def create_task(self, name: str) -> Task:
        validate_name("task", name)
        if not self.path.is_dir():
            raise NotFound(f"{self.path} does not exist: create the department first.")
        path = self.path / name
        check_free(path)
        (path / "work").mkdir(parents=True)
        (path / "cache").mkdir()
        post_create("task", path)
        return Task(self, name)


@dataclass(frozen=True)
class Workfile:
    path: Path
    version: int
    ext: str


@dataclass(frozen=True)
class Task:
    department: Department
    name: str

    @property
    def entity(self) -> Entity:
        return self.department.entity

    @property
    def path(self) -> Path:
        return self.department.path / self.name

    @property
    def work_dir(self) -> Path:
        return self.path / "work"

    @property
    def cache_dir(self) -> Path:
        return self.path / "cache"

    @property
    def custom(self) -> bool:
        return self.name not in self.department.template_tasks

    @property
    def valid(self) -> bool:
        return _valid("task", self.name)

    def _entries(self) -> list[Path]:
        return self.entity.project.scan(self.work_dir, dirs_only=False)

    def workfiles(self) -> list[Workfile]:
        """Managed workfiles, newest first (same version: by extension)."""
        found = []
        for path in self._entries():
            parsed = path.is_file() and parse_workfile(
                path.name, self.entity.name, self.department.name, self.name
            )
            if parsed:
                found.append(Workfile(path, *parsed))
        return sorted(found, key=lambda w: (-w.version, w.ext))

    def unmanaged(self) -> list[Path]:
        """Everything else in work/ (files and folders), shown but never touched."""
        managed = {w.path for w in self.workfiles()}
        return [p for p in self._entries() if p not in managed]

    def latest_workfile(self, ext: str | None = None) -> Workfile | None:
        return next((w for w in self.workfiles() if ext in (None, w.ext)), None)

    def next_workfile(self, ext: str | None = None) -> Path:
        """Path of the next version, without extension if `ext` is None (the DCC adds it on
        Save As). Shared counter across all extensions (spec §5.4)."""
        if ext is not None:
            validate_extension(ext)
        version = max((w.version for w in self.workfiles()), default=0) + 1
        name = format_workfile(self.entity.name, self.department.name, self.name, version, ext)
        return self.work_dir / name

    def _copy_to_next(self, src: Path, ext: str) -> Path:
        dest = self.next_workfile(ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy_new(src, dest)
        return dest

    def new_version_from(self, workfile: Workfile) -> Path:
        return self._copy_to_next(workfile.path, workfile.ext)

    def new_empty_workfile(self, ext: str) -> Path:
        validate_extension(ext)
        template = self.entity.project.root / "shared" / "templates" / f"empty.{ext}"
        if not template.is_file():
            raise NotFound(
                f"No template for .{ext}: save an empty scene as shared/templates/empty.{ext}."
            )
        return self._copy_to_next(template, ext)
