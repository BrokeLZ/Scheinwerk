"""Pointer, entry, payload, root and structure USD layers, written as plain text: no pxr
needed (spec §9.2)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.fileio import write_text

if TYPE_CHECKING:
    from scheinwerk.core.entities import Entity

# Asset layers in payload.usd: mtl over geo, then any other layer A-Z (spec §9.3).
ASSET_LAYER_ORDER = ("mtl", "geo")

# File-relative path from any shot or sequence root layer to the project's structure layer.
STRUCTURE_FROM_ROOT = "../../../../../shared/usd/structure.usd"

# Asset groups under /world by category; other categories and none go to props (§9.2).
ASSET_GROUPS = {"char": "chars", "prop": "props", "env": "env"}


def _structure() -> str:
    """Everything spatial under /world: Xform groups that hold assets and fx (kind group,
    so assets below them stay models), Scopes for cameras and lights. /Render (render
    settings) is not spatial and stays outside."""
    group = '    def Xform "{}" (\n        kind = "group"\n    )\n    {{\n    }}\n'
    scope = '    def Scope "{}"\n    {{\n    }}\n'
    body = "\n".join(
        [*(group.format(n) for n in ("chars", "props", "env", "fx")),
         *(scope.format(n) for n in ("cameras", "lights"))]
    )  # fmt: skip
    world = f'def Xform "world" (\n    kind = "group"\n)\n{{\n{body}}}\n'
    return f'#usda 1.0\n\n{world}\ndef Scope "Render"\n{{\n}}\n'


STRUCTURE = _structure()


def write_pointer(
    path: Path, target_rel: str, *, fps: float, default_prim: str | None = None
) -> None:
    """`default_prim` only for asset layers: shot and sequence pointers are sublayered."""
    _check_relative(target_rel)
    lines = _metadata(fps, default_prim=default_prim)
    write_text(path, _layer(lines + [f"    subLayers = [@{target_rel}@]"]))


def write_root_layer(
    path: Path, sublayers: list[str], *, fps: float, frames: tuple[int, int] | None = None
) -> None:
    """Shot and sequence root layers and an asset's payload.usd. Sublayers strongest first."""
    for layer in sublayers:
        _check_relative(layer)
    lines = _metadata(fps, frames=frames)
    if sublayers:
        lines += ["    subLayers = [", ",\n".join(f"        @{s}@" for s in sublayers), "    ]"]
    else:
        lines.append("    subLayers = []")
    write_text(path, _layer(lines))


def write_component(path: Path, asset: str, *, fps: float) -> None:
    """The asset entry layer: the component prim, its payload ./payload.usd."""
    header = _layer(_metadata(fps, default_prim=asset))
    write_text(
        path,
        f"{header}\n"
        f'def Xform "{asset}" (\n'
        '    kind = "component"\n'
        f'    assetInfo = {{string name = "{asset}"}}\n'
        f"    payload = @./payload.usd@</{asset}>\n"
        ")\n"
        "{\n"
        "}\n",
    )


def write_structure(path: Path) -> None:
    """The project's shot hierarchy. Written only when missing: a project may change it."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, STRUCTURE)


def write_entity_layers(entity: Entity) -> None:
    """Rewrite an entity's entry/root layers from the layers that have a pointer (§9.2).

    A sequence root layer that didn't exist before is added to every shot root layer of
    the sequence.
    """
    usd = entity.path / "publish" / "_usd"
    names = [d.name for d in entity.project.scan(usd) if (d / f"{d.name}.usd").is_file()]
    layers = [f"./{n}/{n}.usd" for n in _ordered(entity, names)]
    fps = entity.fps
    if entity.type == "asset":
        write_root_layer(usd / "payload.usd", layers, fps=fps)
        write_component(usd / f"{entity.name}.usd", entity.name, fps=fps)
        return

    write_structure(entity.project.root / "shared" / "usd" / "structure.usd")
    root = usd / f"{entity.name}.usd"
    if entity.type == "shot":
        seq_root = entity.path.parent / "_seq" / "publish" / "_usd" / f"{entity.sequence}.usd"
        weakest = (
            f"../../../_seq/publish/_usd/{entity.sequence}.usd"
            if seq_root.is_file()
            else STRUCTURE_FROM_ROOT
        )
        write_root_layer(root, [*layers, weakest], fps=fps, frames=entity.frames)
        return

    created = not root.is_file()
    write_root_layer(root, [*layers, STRUCTURE_FROM_ROOT], fps=fps)
    if created:
        for shot in entity.project.shots(entity.name):
            if (shot.path / "publish" / "_usd" / f"{shot.name}.usd").is_file():
                write_entity_layers(shot)


def asset_prim_path(asset: Entity) -> str:
    """Where a shot references an asset: /world/<group>/<asset> (spec §9.2)."""
    return f"/world/{ASSET_GROUPS.get(asset.category or '', 'props')}/{asset.name}"


def read_pointer(path: Path) -> str | None:
    """The first sublayer of a pointer layer, as written: `./v003/hero_geo_v003.usd`."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(r"subLayers\s*=\s*\[\s*@([^@]+)@", text)
    return match[1] if match else None


# --- helpers ----------------------------------------------------------------


def _ordered(entity: Entity, names: list[str]) -> list[str]:
    order = list(
        ASSET_LAYER_ORDER if entity.type == "asset" else entity.project.setting("usd_layer_order")
    )
    return sorted(names, key=lambda n: (order.index(n) if n in order else len(order), n))


def _fps(fps: float) -> str:
    """Like the JSON value: 24, 23.976 (24.0 becomes 24)."""
    return str(int(fps)) if float(fps).is_integer() else repr(float(fps))


def _metadata(
    fps: float, *, default_prim: str | None = None, frames: tuple[int, int] | None = None
) -> list[str]:
    # USD rescales a layer whose timeCodesPerSecond differs from the layer including it,
    # and a layer without one counts as 24 (spec §9.2 item 5).
    lines = [f'    defaultPrim = "{default_prim}"'] if default_prim else []
    lines += [f"    framesPerSecond = {_fps(fps)}", f"    timeCodesPerSecond = {_fps(fps)}"]
    if frames is not None:
        lines += [f"    startTimeCode = {frames[0]}", f"    endTimeCode = {frames[1]}"]
    return lines


def _layer(metadata: list[str]) -> str:
    return "\n".join(["#usda 1.0", "(", *metadata, ")"]) + "\n"


def _check_relative(layer: str) -> None:
    # Nothing persisted may contain an absolute path (spec §2.4).
    if not layer.startswith(("./", "../")) or "\\" in layer or ":" in layer:
        raise ScheinwerkError(f"USD layer paths must be file-relative (./ or ../), got {layer!r}.")
