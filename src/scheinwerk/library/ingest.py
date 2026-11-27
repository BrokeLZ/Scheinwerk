"""Running an ingest plan, and rebuilding a version from its originals (spec §17.4, §17.5).

A plan (from detect, maybe edited) is checked completely before anything is written. Then: the
item (new, or the target), the next version folder, the originals copied into `source/`, one
hoiiotool call per map, previews, and version.json last. A failure before that leaves an
incomplete version (shown flagged, never offered), and the originals are never touched.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol

from scheinwerk.core.errors import InvalidName, NotFound, ScheinwerkError
from scheinwerk.core.fileio import copy_new, write_json
from scheinwerk.core.textures import (
    ImageInfo,
    Recipe,
    ToolInfo,
    extension,
    output_type,
    peak,
    probe,
    process,
    run_tool,
    thumbnail,
    tool_info,
)
from scheinwerk.core.tools import find_tool
from scheinwerk.library.detect import expand, sha256
from scheinwerk.library.ids import validate_variant
from scheinwerk.library.items import (
    ITEM_JSON,
    Item,
    LibraryVersion,
    create_item,
    finalize,
    find_item,
    update_meta,
)
from scheinwerk.library.root import Library

SET_ROLES = {"basecolor", "diffuse", "specular", "glossiness", "metalness", "roughness",
             "specular_level", "normal", "height", "ao", "opacity", "emission"}  # fmt: skip
ROLES = {"texture_set": SET_ROLES, "hdri": {"hdri"}, "texture": {"color", "data"}}
EXTRA_META = ("description", "credits", "license", "source_url", "size_m", "displacement")
THUMB_BOX = {"hdri": ((1024, 512), True), "texture": ((512, 512), False)}
_TILE = re.compile(r"\.(1[0-9]{3})\.[^.]+$")


class Tools(Protocol):
    """What ingest needs from the texture tool (hoiiotool, or a fake in tests)."""

    info: ToolInfo

    def probe(self, path: Path) -> ImageInfo: ...
    def peak(self, path: Path, from_space: str, to_space: str) -> float: ...
    def process(self, recipe: Recipe) -> None: ...
    def thumbnail(self, src, out, space, view, box, exact=False) -> None: ...


class HoiioTools:
    """The real thing: Houdini's hoiiotool (spec §17.5)."""

    def __init__(self, tool: Path) -> None:
        self.tool = tool
        self._info: ToolInfo | None = None

    @classmethod
    def find(cls) -> HoiioTools:
        return cls(find_tool("hoiiotool"))

    @property
    def info(self) -> ToolInfo:
        if self._info is None:
            self._info = tool_info(self.tool)
        return self._info

    def run(self, args: list) -> str:
        return run_tool(self.tool, args)

    def probe(self, path: Path) -> ImageInfo:
        return probe(path, self.tool)

    def peak(self, path: Path, from_space: str, to_space: str) -> float:
        return peak(path, self.tool, from_space, to_space)

    def process(self, recipe: Recipe) -> None:
        process(recipe, self.tool, self.info.linear_rec709)

    def thumbnail(self, src, out, space, view, box, exact=False) -> None:
        thumbnail(src, out, self.tool, space, view, box, exact)


# --- checking a plan ----------------------------------------------------------------------


def check_plan(library: Library, plan: dict) -> Item | None:
    """Everything that can be wrong with a plan, before anything is written. Returns the
    target item (None: a new one)."""
    if plan.get("schema") != 1:
        raise ScheinwerkError(f"Unknown plan schema {plan.get('schema')!r} (expected 1).")
    type_ = plan.get("type")
    if type_ == "model":
        raise ScheinwerkError("Models are ingested from step L4 on.")
    if type_ not in ROLES:
        raise InvalidName(f"Unknown item type {type_!r} in the plan.")
    if plan.get("status") == "needs_input":
        why = "; ".join(plan.get("messages") or []) or "see the plan"
        raise ScheinwerkError(f"{plan.get('name')!r} needs input first: {why}")
    variants = plan.get("variants") or {}
    for name in variants:
        validate_variant(name)
    if not any(variants.values()):
        raise ScheinwerkError(f"{plan.get('name')!r} has no files to ingest.")
    target = (plan.get("target") or {}).get("item")
    if (plan.get("target") or {}).get("variant") and len(variants) != 1:
        raise ScheinwerkError("A plan for one variant of an item must have exactly one variant.")
    for files in variants.values():
        for f in files:
            if f.get("role") not in ROLES[type_]:
                raise InvalidName(
                    f"{f.get('role')!r} is not a {type_} role ({Path(f['path']).name})."
                )
            if not expand(f["path"]) or not all(p.is_file() for p in expand(f["path"])):
                raise NotFound(f"{f['path']} is missing.")
    if (plan.get("target") or {}).get("variant"):
        validate_variant(plan["target"]["variant"])
    if target is None:
        return None
    item = find_item(library, target)
    if item.type != type_:
        raise ScheinwerkError(f"{item.id} is a {item.type}, not a {type_}.")
    return item


# --- recipes ------------------------------------------------------------------------------


class _Builder:
    """Turns plan files into recipes for one version folder."""

    def __init__(self, item: Item, vdir: Path, tools: Tools, working: str) -> None:
        self.item, self.vdir, self.tools, self.working = item, vdir, tools, working
        self.v = vdir.name

    def output(self, variant: str, role: str, data_type: str, tile: str | None) -> Path:
        udim = f".{tile}" if tile else ""
        ext = extension(data_type)
        if self.item.type == "texture_set":
            return self.vdir / "textures" / f"{self.item.id}_{variant}_{role}_{self.v}{udim}.{ext}"
        return self.vdir / f"{self.item.id}_{variant}_{self.v}{udim}.{ext}"

    def recipes(self, variant: str, role: str, sources: list[str], spaces: tuple[str, str],
                *, invert=False, flip=False, channel=None, threshold=None,
                data_type: str | None = None) -> list[Recipe]:  # fmt: skip
        """One recipe per UDIM tile (or one). `sources`: absolute paths or <UDIM> patterns."""
        first = expand(sources[0])
        tiles = [m[1] if (m := _TILE.search(p.name)) else None for p in first]
        out = []
        for tile in tiles:
            files = tuple(_tile(Path(s), tile) for s in sources)
            if data_type is None:
                info = self.tools.probe(files[0])
                pk = self.tools.peak(files[0], *spaces) if role == "hdri" else None
                data_type = output_type(role, info, pk)
            out.append(
                Recipe(
                    files,
                    self.output(variant, role, data_type, tile),
                    role,
                    spaces[0],
                    spaces[1],
                    data_type,
                    flip,
                    invert,
                    threshold,
                    channel,
                )
            )
        return out


def _tile(path: Path, tile: str | None) -> Path:
    return path.with_name(path.name.replace("<UDIM>", tile)) if tile else path


def _plan_recipes(b: _Builder, plan: dict, variant: str, files: list[dict]) -> list[Recipe]:
    working, spec_gloss = b.working, plan.get("workflow") == "spec_gloss"
    threshold = plan.get("metal_threshold") or 0.2
    by_role = {f["role"]: f for f in files}
    out: list[Recipe] = []

    def colour(f: dict) -> tuple[str, str]:
        return f["color_space"], working

    for f in files:
        role = f["role"]
        if role in ("hdri", "color", "basecolor", "emission"):
            if spec_gloss and role == "basecolor" and "diffuse" in by_role:
                continue  # the diffuse map is the base colour
            out += b.recipes(variant, role, [f["path"]], colour(f))
        elif role == "diffuse":  # spec/gloss only (detect makes it basecolor otherwise)
            spec = by_role.get("specular")
            if spec:
                out += b.recipes(
                    variant, "basecolor", [f["path"], spec["path"]], colour(f), threshold=threshold
                )
            else:
                out += b.recipes(variant, "basecolor", [f["path"]], colour(f))
        elif role == "specular":
            out += b.recipes(
                variant, "metalness", [f["path"]], (f["color_space"], "raw"), threshold=threshold
            )
        elif role == "glossiness":
            out += b.recipes(variant, "roughness", [f["path"]], ("raw", "raw"), invert=True)
        else:
            out += b.recipes(
                variant,
                role,
                [f["path"]],
                ("raw", "raw"),
                invert=f.get("invert", False),
                flip=f.get("flip_green", False),
                channel=f.get("channel"),
            )
    return out


def _entry(r: Recipe, variant: str, vdir: Path) -> dict:
    """The version.json `files` entry; UDIM tiles are written once, with <UDIM>."""
    entry = {"variant": variant, **r.entry(vdir)}
    for p in r.output, *r.sources:
        m = _TILE.search(p.name)
        if m:
            entry["output"] = _untile(entry["output"], m[1])
            entry["source"] = [_untile(s, m[1]) for s in entry["source"]]
            break
    return entry


def _untile(rel: str, tile: str) -> str:
    return re.sub(rf"\.{tile}(\.[^./]+)$", r".<UDIM>\1", rel)


def _rel(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


def _dedupe(entries: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in entries:
        key = (e["variant"], e["output"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def _make(b: _Builder, recipes: dict[str, list[Recipe]], tools: Tools) -> None:
    """Process every map, then the previews. A failed preview never blocks the version
    (spec §17.7): it is simply missing, and `sw lib thumb` makes it again later."""
    for rs in recipes.values():
        for r in rs:
            tools.process(r)
    if b.item.type in THUMB_BOX:
        box, exact = THUMB_BOX[b.item.type]
        for variant, rs in recipes.items():
            if not rs:
                continue
            r = rs[0]
            out = b.vdir / f"thumb_{variant}.jpg"
            try:
                tools.thumbnail(r.output, out, r.to_space, tools.info.preview_view(), box, exact)
            except ScheinwerkError:
                out.unlink(missing_ok=True)


# --- ingest -------------------------------------------------------------------------------


def _apply_meta(item: Item, plan: dict, new: bool) -> None:
    update_meta(item, add_categories=plan.get("categories") or [],
                add_tags=plan.get("tags") or [])  # fmt: skip
    data = dict(item.meta)
    for key in EXTRA_META:
        value = plan.get(key)
        if value not in (None, "", []) and (new or key not in data):
            data[key] = value
    write_json(item.path / ITEM_JSON, data)


def ingest(library: Library, plan: dict, tools: Tools, comment: str = "") -> LibraryVersion:
    """Run one plan: a new item, or a new version of the target item (spec §17.4)."""
    item = check_plan(library, plan)
    if library.working_space not in tools.info.color_spaces:
        raise NotFound(f"The OCIO config has no {library.working_space!r} colour space "
                       "(library.json working_space).")  # fmt: skip
    new = item is None
    if new:
        item = create_item(library, plan["type"], plan["name"])
    _apply_meta(item, plan, new)
    previous = item.latest()
    variants = dict(plan["variants"])
    single = (plan.get("target") or {}).get("variant")
    if single:
        variants = {single: next(iter(variants.values()))}

    vdir = item.next_version_dir()
    many = len(variants) > 1
    copied: dict[Path, Path] = {}
    plan_files: dict[str, list[dict]] = {}
    for variant, files in variants.items():
        plan_files[variant] = []
        for f in files:
            src = Path(f["path"])
            dest_dir = vdir / "source" / (variant if many else "")
            for tile in expand(f["path"]):
                if tile not in copied:
                    dest = dest_dir / tile.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    copy_new(tile, dest)
                    copied[tile] = dest
            plan_files[variant].append({**f, "path": str(dest_dir / src.name)})

    b = _Builder(item, vdir, tools, library.working_space)
    recipes = {v: _plan_recipes(b, plan, v, fs) for v, fs in plan_files.items()}
    _make(b, recipes, tools)

    first = next(r for rs in recipes.values() for r in rs)
    size = tools.probe(first.sources[0])
    info = {
        "comment": comment,
        "origin": "ingest",
        "variants": {
            name: {"version": number}
            for name, number in {
                **(previous.variants() if previous else {}),
                **dict.fromkeys(variants, LibraryVersion(item, vdir).number),
            }.items()
        },
        "ocio": {"config": tools.info.ocio_config, "working_space": library.working_space},
        "tools": {"hoiiotool": tools.info.version},
        "workflow": plan.get("workflow"),
        "metal_threshold": plan.get("metal_threshold")
        if plan.get("workflow") == "spec_gloss"
        else None,
        "resolution": [size.width, size.height],
        "udim": any("<UDIM>" in f["path"] for fs in variants.values() for f in fs),
        "scale": None,
        "files": _dedupe([_entry(r, v, vdir) for v, rs in recipes.items() for r in rs]),
        "sha256": {_rel(dest, vdir): sha256(dest) for dest in copied.values()},
    }
    version = LibraryVersion(item, vdir)
    finalize(version, info)
    return version


# --- rebuild ------------------------------------------------------------------------------


def rebuild(
    item: Item,
    tools: Tools,
    version: int | None = None,
    metal_threshold: float | None = None,
    comment: str = "",
) -> LibraryVersion:
    """A new version made again from the originals of `version` (default the latest), e.g.
    with another metal threshold. Copies nothing: the originals stay where they are."""
    base = item.version(version) if version else item.latest()
    if base is None:
        raise NotFound(f"{item.id} has no finalized version to rebuild.")
    old = base.info
    if old is None:
        raise ScheinwerkError(f"{item.id} {base.path.name} is incomplete: nothing to rebuild.")
    held = sorted(v for v, n in base.variants().items() if n == base.number)
    entries = [e for e in old.get("files") or [] if e.get("variant") in held]
    if not entries:
        raise ScheinwerkError(f"{item.id} {base.path.name} holds no maps of its own.")
    spec_gloss = old.get("workflow") == "spec_gloss"
    threshold = metal_threshold if metal_threshold is not None else old.get("metal_threshold")

    vdir = item.next_version_dir()
    b = _Builder(item, vdir, tools, item.library.working_space)
    recipes: dict[str, list[Recipe]] = {}
    for e in entries:
        sources = [os.path.normpath(base.path / s) for s in e["source"]]
        uses_threshold = spec_gloss and (
            e["role"] == "metalness" or (e["role"] == "basecolor" and len(sources) == 2)
        )
        recipes.setdefault(e["variant"], []).extend(b.recipes(
            e["variant"], e["role"], sources, (e["from_space"], e["to_space"]),
            invert=e.get("invert", False), flip=e.get("flip_green", False),
            channel=e.get("channel"), threshold=threshold if uses_threshold else None,
            data_type=e["data_type"]))  # fmt: skip
    _make(b, recipes, tools)

    source_version = old.get("source_version") or base.number
    keep = ("workflow", "resolution", "udim", "scale", "ocio")
    info = {
        "comment": comment,
        "origin": "rebuild",
        "source_version": source_version,
        "variants": {
            **{k: {"version": v} for k, v in base.variants().items()},
            **{v: {"version": LibraryVersion(item, vdir).number} for v in held},
        },  # fmt: skip
        **{k: old[k] for k in keep if k in old},
        "tools": {"hoiiotool": tools.info.version},
        "metal_threshold": threshold if spec_gloss else None,
        "files": _dedupe([_entry(r, v, vdir) for v, rs in recipes.items() for r in rs]),
        "sha256": {
            _rel(Path(os.path.normpath(base.path / k)), vdir): h
            for k, h in (old.get("sha256") or {}).items()
        },
    }
    new = LibraryVersion(item, vdir)
    finalize(new, info)
    return new
