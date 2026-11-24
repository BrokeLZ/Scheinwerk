"""Publishing: next version folders, finalize, USD pointers, ingest (spec §9)."""

from __future__ import annotations

import getpass
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from scheinwerk.core.context import Context
from scheinwerk.core.entities import Entity, Task
from scheinwerk.core.errors import NotFound, NotInProject, ParseError, ScheinwerkError
from scheinwerk.core.fileio import copy_new, read_json, write_json
from scheinwerk.core.hooks import run_hook
from scheinwerk.core.project import Project
from scheinwerk.core.templates import format_version, validate_extension
from scheinwerk.core.usd_pointer import write_entity_layers, write_pointer
from scheinwerk.core.versions import Product

USD_SUFFIXES = (".usd", ".usda", ".usdc")

PathLike = str | os.PathLike[str]


def next_publish(entity: Entity, name: str) -> Path:
    return Product(entity.project, entity.path / "publish" / name).next_version_dir()


def next_media(entity: Entity, name: str) -> Path:
    return Product(entity.project, entity.path / "media" / name).next_version_dir()


def next_usd(entity: Entity, layer: str) -> Path:
    return Product(entity.project, entity.path / "publish" / "_usd" / layer).next_version_dir()


def finalize(
    version_dir: PathLike,
    *,
    source: PathLike | None = None,
    comment: str = "",
    main_file: str | None = None,
    dcc: str | None = None,
    usd_files: Iterable[PathLike] | None = None,
) -> None:
    """Write version.json and, for USD, point the layer at this version (pointer last).

    `usd_files`: the published USD files a render used (spec §8.3). Re-finalizing (e.g. to
    edit the comment) keeps `created`, `user`, an earlier `source`/`usd_files` and any
    unknown keys.
    """
    ctx, project = _version_context(version_dir)
    vdir = ctx.path()
    main = _main_usd_file(ctx, main_file) if ctx.usd else None  # fail before writing anything
    used = None if usd_files is None else sorted({project.rel(f) for f in usd_files})

    data = read_json(vdir / "version.json") or {}
    data.setdefault("schema", 1)
    if source is not None:
        data["source"] = project.rel(source)
        source_ctx = _context_or_none(source)
        for key in ("dept", "task"):
            value = getattr(source_ctx, key, None)
            if value is not None:
                data[key] = value
    if dcc is not None:
        data["dcc"] = dcc
    data.setdefault("user", _user())
    data.setdefault("created", datetime.now().astimezone().isoformat(timespec="seconds"))
    data["comment"] = comment
    if used is not None:
        data["usd_files"] = used
    write_json(vdir / "version.json", data)

    if main is not None:
        _write_pointers(project, ctx, main)
    run_hook("post_publish", version_dir=vdir, context=ctx)


def set_current(usd_version_dir: PathLike, *, main_file: str | None = None) -> None:
    """Point the USD layer at this version ("Set as latest", rollback)."""
    ctx, project = _version_context(usd_version_dir)
    if not ctx.usd:
        raise ParseError(f"{ctx.path()} is not a USD version folder (publish/_usd/<layer>/v###).")
    _write_pointers(project, ctx, _main_usd_file(ctx, main_file))


def ingest(files: Iterable[PathLike], target: Task | Product) -> list[Path]:
    """Copy files in as new workfile versions (one each) or as one new product/media version.

    Everything is checked before anything is copied. Originals are never touched.
    """
    sources = [Path(f).absolute() for f in files]
    if not sources:
        raise ScheinwerkError("Nothing to ingest.")
    for src in sources:
        if not src.exists():
            raise NotFound(f"{src} does not exist.")
        if not src.is_file():
            raise ScheinwerkError(f"{src} is a folder: only files can be ingested.")

    if isinstance(target, Task):
        exts = []
        for src in sources:
            ext = src.suffix[1:].lower()
            if not ext:
                raise ScheinwerkError(f"{src.name} has no extension, so it can't be a workfile.")
            validate_extension(ext)
            exts.append(ext)
        target.work_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for src, ext in zip(sources, exts, strict=True):
            dest = target.next_workfile(ext)
            copy_new(src, dest)
            copied.append(dest)
        return copied

    names = [s.name for s in sources]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ScheinwerkError(f"Several files are called {', '.join(dupes)}: names must be unique.")
    vdir = target.next_version_dir()
    for src in sources:
        copy_new(src, vdir / src.name)
    return [vdir / src.name for src in sources]


# --- helpers ----------------------------------------------------------------


def _version_context(version_dir: PathLike) -> tuple[Context, Project]:
    path = Path(version_dir).absolute()
    ctx = Context.from_path(path)
    if ctx is None:
        raise NotInProject(f"{path} is not inside a Scheinwerk project.")
    if ctx.version is None or ctx.area not in ("publish", "media") or ctx.path() != path:
        raise ParseError(f"{path} is not a version folder (publish/<name>/v###).")
    if not path.is_dir():
        raise NotFound(f"{path} does not exist.")
    return ctx, Project.find(ctx.root)


def _context_or_none(path: PathLike) -> Context | None:
    try:
        return Context.from_path(path)
    except ParseError:
        return None  # inside the project but not in an entity (io/, shared/)


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # no user name in some service/container environments
        return ""


def _main_usd_file(ctx: Context, main_file: str | None) -> str:
    """The layer the pointer targets, relative to the version folder (POSIX)."""
    vdir = ctx.path()
    if main_file is not None:
        path = Path(main_file) if Path(main_file).is_absolute() else vdir / main_file
        if not path.is_file():
            raise NotFound(f"{path} does not exist.")
        try:
            return path.relative_to(vdir).as_posix()
        except ValueError:
            raise ScheinwerkError(f"main_file must be inside {vdir}.") from None
    files = sorted(p for p in vdir.iterdir() if p.is_file() and p.suffix in USD_SUFFIXES)
    if len(files) == 1:
        return files[0].name
    recommended = f"{ctx.entity}_{ctx.product}_{format_version(ctx.version)}"
    matches = [p for p in files if p.stem == recommended]
    if len(matches) == 1:
        return matches[0].name
    if not files:
        raise NotFound(f"No .usd file in {vdir}.")
    names = ", ".join(p.name for p in files)
    raise ScheinwerkError(
        f"{len(files)} USD files in {vdir.name} ({names}): say which is the main file "
        "(main_file, or --main in sw)."
    )


def _write_pointers(project: Project, ctx: Context, main: str) -> None:
    """Layer pointer, then the entry/root layers that list every layer pointer."""
    vdir = ctx.path()
    entity = project.entity_at(ctx)
    write_pointer(
        vdir.parent / f"{ctx.product}.usd",
        f"./{vdir.name}/{main}",
        fps=entity.fps,
        default_prim=entity.name if entity.type == "asset" else None,
    )
    write_entity_layers(entity)
