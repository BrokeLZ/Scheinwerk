"""Pointer and root USD layers, written as plain text: no pxr needed (spec §9.2)."""

from __future__ import annotations

import re
from pathlib import Path

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.fileio import write_text


def write_pointer(path: Path, target_rel: str, default_prim: str) -> None:
    _check_relative(target_rel)
    write_text(
        path,
        f'#usda 1.0\n(\n    defaultPrim = "{default_prim}"\n    subLayers = [@{target_rel}@]\n)\n',
    )


def write_root_layer(path: Path, sublayers: list[str], default_prim: str | None = None) -> None:
    """Sublayers strongest first. Shot and sequence root layers have no defaultPrim."""
    for layer in sublayers:
        _check_relative(layer)
    lines = ["#usda 1.0", "("]
    if default_prim:
        lines.append(f'    defaultPrim = "{default_prim}"')
    if sublayers:
        lines += ["    subLayers = [", ",\n".join(f"        @{s}@" for s in sublayers), "    ]"]
    else:
        lines.append("    subLayers = []")
    lines.append(")")
    write_text(path, "\n".join(lines) + "\n")


def read_pointer(path: Path) -> str | None:
    """The first sublayer of a pointer layer, as written: `./v003/hero_asset_v003.usd`."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(r"subLayers\s*=\s*\[\s*@([^@]+)@", text)
    return match[1] if match else None


def _check_relative(layer: str) -> None:
    # Nothing persisted may contain an absolute path (spec §2.4).
    if not layer.startswith(("./", "../")) or "\\" in layer or ":" in layer:
        raise ScheinwerkError(f"USD layer paths must be file-relative (./ or ../), got {layer!r}.")
