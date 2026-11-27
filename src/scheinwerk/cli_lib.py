"""`sw lib …`: the asset library commands (spec §17.10). Registered by cli.py."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from scheinwerk.core.errors import NotFound, ScheinwerkError
from scheinwerk.core.project import Project, find_root
from scheinwerk.core.settings import set_library
from scheinwerk.core.templates import format_version
from scheinwerk.library.detect import detect, expand
from scheinwerk.library.ingest import HoiioTools, ingest, rebuild
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


# --- detect / ingest / rebuild ---------------------------------------------------------------


def _print_entry(entry: dict) -> None:
    target = (entry.get("target") or {}).get("item")
    head = [entry["type"], entry["name"], entry["status"]]
    if target:
        head.append(f"-> {target}" + (f" as {entry['target']['variant']}"
                                      if entry["target"].get("variant") else ""))  # fmt: skip
    print("  ".join(head))
    for variant, files in entry["variants"].items():
        for f in files:
            flags = [f["color_space"]]
            flags += ["flip green"] if f.get("flip_green") else []
            flags += ["invert"] if f.get("invert") else []
            flags += [f"channel {f['channel']}"] if f.get("channel") is not None else []
            print("  ".join(["", variant, f["role"], Path(f["path"]).name, *flags]))
    for path in entry.get("skipped") or []:
        print(f"  skipped  {Path(path).name}")
    for message in entry.get("messages") or []:
        print(f"  ! {message}")


def _print_unused(unused: list[dict]) -> None:
    for u in unused:
        print(f"not used  {Path(u['path']).name}  ({u['reason']})")


def _detect(library: Library, tools: HoiioTools, paths: list[str]):
    info = tools.info
    return detect([Path(p) for p in paths], tools.probe, info.srgb_texture, info.linear_rec709,
                  library=library)  # fmt: skip


def cmd_detect(args: argparse.Namespace) -> None:
    library = configured_library()
    result = _detect(library, HoiioTools.find(), args.paths)
    if args.json:
        _print_json(result.as_json())
        return
    for entry in result.entries:
        _print_entry(entry)
    _print_unused(result.unused)


def _retype(entry: dict, type_: str, tools: HoiioTools) -> None:
    """--type for a single image: texture <-> hdri."""
    if entry["type"] == "texture_set" or type_ == "texture_set":
        raise ScheinwerkError("--type works on single images (hdri, texture), not texture sets.")
    for files in entry["variants"].values():
        for f in files:
            info = tools.probe(expand(f["path"])[0])
            if type_ == "hdri":
                if not info.is_float:
                    raise ScheinwerkError(f"{Path(f['path']).name} isn't a float image: "
                                          "it can't be an HDRI.")  # fmt: skip
                f["role"], f["color_space"] = "hdri", tools.info.linear_rec709
            else:
                f["role"] = "data" if info.channels == 1 else "color"
                if f["role"] == "data":
                    f["color_space"] = "raw"
    entry["type"] = type_


def _load_plans(path: str) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScheinwerkError(f"Can't read the plan {path}: {exc}") from None
    return data["entries"] if isinstance(data, dict) and "entries" in data else [data]


def cmd_ingest(args: argparse.Namespace) -> int:
    if not args.plan and not args.paths:
        args.parser.error("give files, folders or zips, or --plan")
    library = configured_library()
    tools = HoiioTools.find()
    if args.plan:
        entries = _load_plans(args.plan)
    else:
        result = _detect(library, tools, args.paths)
        entries = result.entries
        _print_unused(result.unused)
    if not entries:
        raise ScheinwerkError("Nothing to ingest.")
    one = {"--name": args.name, "--type": args.type, "--item": args.item,
           "--variant": args.variant}  # fmt: skip
    given = [k for k, v in one.items() if v]
    if given and len(entries) != 1:
        raise ScheinwerkError(
            f"{', '.join(given)} need exactly one entry, but there are {len(entries)}: "
            "ingest them one at a time, or edit the plans (sw lib detect --json)."
        )
    for entry in entries:
        if args.type:
            _retype(entry, args.type, tools)
        if args.name:
            entry["name"] = args.name
        if args.item or args.variant:
            entry["target"] = {"item": args.item or (entry.get("target") or {}).get("item"),
                               "variant": args.variant}  # fmt: skip
        entry["categories"] = [*entry.get("categories", []), *(args.category or [])]
        entry["tags"] = [*entry.get("tags", []), *(args.tag or [])]
        if args.size:
            entry["size_m"] = list(args.size)
        if args.scale is not None:
            entry["scale"] = args.scale
        _print_entry(entry)
    blocked = [e["name"] for e in entries if e.get("status") == "needs_input"]
    if blocked:
        raise ScheinwerkError(f"Needs input: {', '.join(blocked)}. Edit the plan and use --plan.")
    warned = [e["name"] for e in entries if e.get("status") == "warning"]
    if warned and not args.yes:
        raise ScheinwerkError(f"Warnings for {', '.join(warned)}: check them, then run again "
                              "with --yes.")  # fmt: skip
    failed = 0
    for entry in entries:
        try:
            version = ingest(library, entry, tools, comment=args.message)
        except ScheinwerkError as exc:
            print(f"sw: error: {entry['name']}: {exc}", file=sys.stderr)
            failed += 1
            continue
        item = version.item
        print(f"{item.type}/{item.id} {version.path.name}  {item.name}")
    return 1 if failed else 0


def cmd_rebuild(args: argparse.Namespace) -> None:
    library = configured_library()
    item = find_item(library, args.item)
    version = rebuild(item, HoiioTools.find(), args.version, args.metal_threshold, args.message)
    print(f"{item.type}/{item.id} {version.path.name}  {item.name}")


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

    q = add("detect", cmd_detect, "show what ingest would make of files (writes nothing)",
            (json_only,))  # fmt: skip
    q.add_argument("paths", nargs="+", metavar="files|folder|zip")

    q = add("ingest", cmd_ingest, "ingest files, folders or zips as library items")
    q.add_argument("paths", nargs="*", metavar="files|folder|zip")
    q.add_argument("--plan", help="run the plan(s) in this JSON file (as printed by detect)")
    q.add_argument("--type", choices=("hdri", "texture"), help="single images: force the type")
    q.add_argument("--name", help="display name")
    q.add_argument("--item", help="a new version of this item instead of a new item")
    q.add_argument("--variant", help="as this variant (other variants are kept)")
    q.add_argument("--category", action="append", metavar="C")
    q.add_argument("--tag", action="append", metavar="T")
    q.add_argument("--size", nargs=2, type=float, metavar=("W", "H"),
                   help="real-world size the maps cover, in metres")  # fmt: skip
    q.add_argument("--scale", type=float, help="models: scale on top of the file's units")
    q.add_argument("-m", "--message", default="", help="comment")
    q.add_argument("--yes", action="store_true", help="ingest entries that have warnings")

    q = add("rebuild", cmd_rebuild, "make a new version from a version's originals")
    q.add_argument("item", help="item id, or its display name when unique")
    q.add_argument("--version", type=int, help="rebuild this version (default: the latest)")
    q.add_argument("--metal-threshold", type=float, help="spec/gloss sets: the new threshold")
    q.add_argument("-m", "--message", default="", help="comment")
