"""`sw lib …`: the asset library commands (spec §17.10). Registered by cli.py."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from scheinwerk.core.errors import NotFound, ScheinwerkError
from scheinwerk.core.project import Project, find_root
from scheinwerk.core.settings import set_library
from scheinwerk.core.templates import format_version
from scheinwerk.library.items import Item, LibraryVersion, find_item, update_meta
from scheinwerk.library.root import (
    MARKER,
    TYPES,
    WORKSHOP_DEPARTMENTS,
    WORKSHOP_PROJECT,
    Library,
    configured_library,
)
from scheinwerk.library.search import search


def _rel(library: Library, path: Path) -> str:
    return path.relative_to(library.root).as_posix()


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# --- init ---------------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> None:
    folder = Path(args.folder).absolute()
    outer = find_root(folder)
    if outer is not None:
        raise ScheinwerkError(f"{folder} is inside the project {outer}: a library can't be.")
    if (folder / MARKER).is_file():
        library = Library.open(folder)
        print(f"Using the existing library {library.root}")
    else:
        library = Library.create(folder, args.name)
        print(library.root)
    if not (library.workshop / "scheinwerk.json").is_file():
        Project.create(library.workshop, WORKSHOP_PROJECT, departments=WORKSHOP_DEPARTMENTS)
        print(library.workshop)
    set_library(library.root)


# --- ls -----------------------------------------------------------------------------------


def _item_json(library: Library, item: Item) -> dict:
    latest = item.latest()
    return {
        "type": item.type,
        "id": item.id,
        "name": item.name,
        "valid": item.valid,
        "path": _rel(library, item.path),
        "latest": latest.number if latest else None,
        "variants": latest.variants() if latest else {},
        "incomplete": _incomplete(item),
        "categories": item.categories,
        "tags": item.tags,
    }


def _incomplete(item: Item) -> list[int]:
    """Incomplete versions above the latest finalized one (an ingest that didn't finish)."""
    latest = item.latest()
    floor = latest.number if latest else 0
    return sorted(v.number for v in item.versions() if not v.finalized and v.number > floor)


def _item_line(item: Item) -> str:
    latest = item.latest()
    flags = [] if item.valid else ["invalid id"]
    if latest is None:
        flags.append("no finalized version")
    flags += [f"incomplete {format_version(n)}" for n in _incomplete(item) if latest]
    parts = [f"{item.type}/{item.id}", item.name]
    if latest:
        parts += [latest.path.name, ", ".join(latest.variants())]
    if flags:
        parts.append(f"[{', '.join(flags)}]")
    return "  ".join(p for p in parts if p)


def cmd_ls(args: argparse.Namespace) -> None:
    library = configured_library()
    items = search(library, args.type, args.category, args.tag or [], args.search)
    filtered = args.type or args.category or args.tag or args.search
    if args.json:
        _print_json({"items": [_item_json(library, i) for i in items]})
        return
    for item in sorted(items, key=lambda i: (i.type, i.id)):
        print(_item_line(item))
    if not filtered:
        for entry in library.unknown():
            print(f"{entry.name}  [unknown]")


# --- meta ---------------------------------------------------------------------------------


def cmd_meta(args: argparse.Namespace) -> None:
    library = configured_library()
    item = find_item(library, args.item)
    if _editing(args):
        update_meta(
            item,
            name=args.name,
            add_categories=args.add_category or [],
            remove_categories=args.remove_category or [],
            add_tags=args.add_tag or [],
            remove_tags=args.remove_tag or [],
        )
    meta = {"type": item.type, "id": item.id, **item.meta, "name": item.name}
    if args.json:
        _print_json(meta)
        return
    for key, value in meta.items():
        if key != "schema":
            print(f"{key}: {', '.join(value) if isinstance(value, list) else value}")


def _editing(args: argparse.Namespace) -> bool:
    return any(
        (
            args.name is not None,
            args.add_category,
            args.remove_category,
            args.add_tag,
            args.remove_tag,
        )
    )


# --- path ---------------------------------------------------------------------------------


def _version(item: Item, number: int | None) -> LibraryVersion:
    if number is None:
        latest = item.latest()
        if latest is None:
            raise NotFound(f"{item.id} has no finalized version yet.")
        return latest
    version = item.version(number)
    if not version.finalized:
        raise ScheinwerkError(f"{item.id} {version.path.name} is incomplete (no version.json).")
    return version


def cmd_path(args: argparse.Namespace) -> None:
    library = configured_library()
    item = find_item(library, args.item)
    version = _version(item, args.version)
    if args.usd:
        if item.type != "model":
            raise ScheinwerkError(f"{item.id} is a {item.type}: only models have USD.")
        path = version.path / f"{item.id}.usd"
    elif args.variant:
        path = version.variant_dir(args.variant)
    else:
        path = version.path
    rel = _rel(library, path)
    print(f"$SW_LIBRARY/{rel}" if args.env else rel)


# --- parser -------------------------------------------------------------------------------


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("lib", help="the asset library", description="The asset library.")
    lib = p.add_subparsers(title="library commands", metavar="<command>", required=True)
    json_only = argparse.ArgumentParser(add_help=False)
    json_only.add_argument("--json", action="store_true", help="print JSON")

    def add(name: str, func: Callable, help: str, parents=()) -> argparse.ArgumentParser:
        q = lib.add_parser(name, help=help, description=help, parents=list(parents))
        q.set_defaults(func=func, parser=q)
        return q

    q = add(
        "init",
        cmd_init,
        "create a library (and its workshop project) or use an existing one on this machine",
    )
    q.add_argument("folder")
    q.add_argument("--name", default="library", help="library name (new libraries only)")

    q = add("ls", cmd_ls, "list library items", (json_only,))
    q.add_argument("type", nargs="?", choices=TYPES)
    q.add_argument("--category", help="this category and the ones below it")
    q.add_argument("--tag", action="append", help="has this tag (repeat for several: all of them)")
    q.add_argument("--search", help="words to find in names, ids, variants, categories, tags…")

    q = add("meta", cmd_meta, "show or edit an item's name, categories and tags", (json_only,))
    q.add_argument("item", help="item id, or its display name when unique")
    q.add_argument("--name", help="new display name")
    for what in ("category", "tag"):
        q.add_argument(f"--add-{what}", action="append", metavar=what.upper())
        q.add_argument(f"--remove-{what}", action="append", metavar=what.upper())

    q = add("path", cmd_path, "print an item's library-relative path to paste")
    q.add_argument("item", help="item id, or its display name when unique")
    q.add_argument("--version", type=int, help="this version (default: the latest finalized)")
    q.add_argument("--variant", help="the folder holding this variant's files")
    q.add_argument("--usd", action="store_true", help="models: the component file")
    q.add_argument("--env", action="store_true", help="as $SW_LIBRARY/… (for non-USD parms)")
