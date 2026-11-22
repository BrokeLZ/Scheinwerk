"""Path -> context and back (spec §6)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePath

from scheinwerk.core.errors import ParseError
from scheinwerk.core.project import find_root, read_config
from scheinwerk.core.templates import format_version, format_workfile, parse_version, parse_workfile

TASK_AREAS = ("work", "cache")
ENTITY_AREAS = ("publish", "media")
_ENTITY_LEVEL = (*ENTITY_AREAS, "entity.json")  # things that sit directly in an entity folder


@dataclass(frozen=True)
class Context:
    root: Path  # absolute, runtime only
    entity_type: str  # "asset" | "shot" | "sequence"
    entity: str  # "hero" | "sq010_0010" | "sq010"
    category: str | None  # assets only
    sequence: str | None  # shots and sequences
    dept: str | None
    task: str | None
    area: str | None  # "work" | "cache" | "publish" | "media"
    product: str | None  # product, USD layer or media name
    usd: bool  # True if under publish/_usd/
    version: int | None
    ext: str | None

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> Context | None:
        """Parse any path, existing or not. None outside a project, ParseError outside an entity."""
        path = Path(path).absolute()
        root = find_root(path)
        if root is None:
            return None
        parts = path.relative_to(root).parts
        return cls(root=root, **_parse(root, parts))

    def path(self) -> Path:
        """The path this context describes. Inverse of from_path for paths the core generates."""
        if self.entity_type == "asset":
            p = self.root / "assets"
            if self.category:
                p /= self.category
            p /= self.entity
        elif self.entity_type == "shot":
            p = self.root / "shots" / self.sequence / self.entity
        else:
            p = self.root / "shots" / self.entity / "_seq"

        if self.area in ENTITY_AREAS:
            p /= self.area
            if self.usd:
                p /= "_usd"
                if self.product is None:
                    return p / f"{self.entity}.usd" if self.ext == "usd" else p
            if self.product is None:
                return p
            p /= self.product
            if self.version is not None:
                return p / format_version(self.version)
            if self.usd and self.ext == "usd":
                return p / f"{self.product}.usd"  # pointer layer
            return p

        for part in (self.dept, self.task, self.area):
            if part is None:
                return p
            p /= part
        if self.area == "work" and self.version is not None and self.ext:
            return p / format_workfile(self.entity, self.dept, self.task, self.version, self.ext)
        return p


def _parse(root: Path, parts: tuple[str, ...]) -> dict:
    where = PurePath(*parts).as_posix() if parts else "The project root"
    not_entity = ParseError(f"{where} is not inside an asset, sequence or shot.")

    if len(parts) < 2 or parts[0] not in ("assets", "shots"):
        raise not_entity
    if parts[0] == "assets":
        category, rest = _split_category(root, parts[1:])
        fields = {"entity_type": "asset", "entity": rest[0], "category": category, "sequence": None}
        tail = rest[1:]
    else:
        seq = parts[1]
        if len(parts) == 2 or parts[2] == "_seq":  # the sequence folder itself counts as _seq
            fields = {"entity_type": "sequence", "entity": seq}
            tail = parts[3:]
        else:
            fields = {"entity_type": "shot", "entity": parts[2]}
            tail = parts[3:]
        fields |= {"category": None, "sequence": seq}
    return fields | _parse_tail(fields["entity"], tail)


def _split_category(root: Path, a: tuple[str, ...]) -> tuple[str | None, tuple[str, ...]]:
    """Split the parts after `assets/` into (category, parts from the asset on)."""
    # Deep paths: where an area keyword sits decides. Area words are reserved,
    # so this works for custom departments too.
    if len(a) > 1 and a[1] in _ENTITY_LEVEL or len(a) > 3 and a[3] in TASK_AREAS:
        return None, a
    if len(a) > 2 and a[2] in _ENTITY_LEVEL or len(a) > 4 and a[4] in TASK_AREAS:
        return a[0], a[1:]
    # Shallow paths: spec rule, is parts[2] a department of the template?
    if len(a) == 1 or a[1] in _template_departments(root):
        return None, a
    return a[0], a[1:]


def _template_departments(root: Path) -> set[str]:
    departments = read_config(root).get("departments", {})
    return {dept for per_type in departments.values() for dept in per_type}


def _parse_tail(entity: str, tail: tuple[str, ...]) -> dict:
    """Parse what comes after the entity folder."""
    out: dict = {
        "dept": None,
        "task": None,
        "area": None,
        "product": None,
        "usd": False,
        "version": None,
        "ext": None,
    }
    if not tail or tail[0] == "entity.json":
        return out

    if tail[0] in ENTITY_AREAS:
        out["area"] = tail[0]
        rest = tail[1:]
        if tail[0] == "publish" and rest[:1] == ("_usd",):
            out["usd"] = True
            rest = rest[1:]
            if len(rest) == 1 and "." in rest[0]:  # entry/root layer; names never contain "."
                out["ext"] = _ext(rest[0])
                return out
        if not rest:
            return out
        out["product"], rest = rest[0], rest[1:]
        if not rest:
            return out
        version = parse_version(rest[0])
        if version is not None:
            out["version"] = version
            if len(rest) > 1:
                out["ext"] = _ext(rest[-1])
        elif out["usd"] and rest == (f"{out['product']}.usd",):
            out["ext"] = "usd"  # pointer layer
        return out

    out["dept"] = tail[0]
    out["task"] = tail[1] if len(tail) > 1 else None
    if len(tail) > 2 and tail[2] in TASK_AREAS:
        out["area"] = tail[2]
        if tail[2] == "work" and len(tail) == 4:  # work/ is flat; cache/ is free-form
            out["ext"] = _ext(tail[3])
            parsed = parse_workfile(tail[3], entity, out["dept"], out["task"])
            if parsed:
                out["version"], out["ext"] = parsed
    return out


def _ext(filename: str) -> str | None:
    return PurePath(filename).suffix[1:] or None
