"""Detection: what was dropped -> ingest plans (spec §17.5 Detection).

Every value detection decides lands in a plan (a JSON-able dict, spec §17.10) that the user can
change before `ingest` runs it. Image facts (channels, bit depth, size) come from a `probe`
callable, so the rules are testable without hoiiotool.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.settings import user_dir
from scheinwerk.core.textures import ImageInfo
from scheinwerk.library.ids import variant_from_token
from scheinwerk.library.root import DEFAULTS, Library

IMAGES = {".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".tx", ".hdr", ".tga", ".bmp",
          ".psd", ".dpx", ".sgi", ".rgb", ".pnm", ".ppm", ".iff"}  # fmt: skip
UNSUPPORTED = {".webp", ".jxl", ".heic", ".heif", ".jp2", ".j2k", ".avif", ".gif"}
MODELS = {".fbx", ".obj", ".gltf", ".glb", ".abc", ".usd", ".usda", ".usdc", ".usdz"}
METAL_THRESHOLD = 0.2

ROLE_TOKENS = {
    **dict.fromkeys(("basecolor", "albedo", "col", "color", "colour"), "basecolor"),
    **dict.fromkeys(("diffuse", "diff"), "diffuse"),
    **dict.fromkeys(("normal", "nrm", "nor", "norm"), "normal"),
    **dict.fromkeys(("rough", "roughness"), "roughness"),
    **dict.fromkeys(("gloss", "glossiness"), "glossiness"),
    **dict.fromkeys(("metal", "metallic", "metalness"), "metalness"),
    **dict.fromkeys(("spec", "specular"), "specular"),
    **dict.fromkeys(("disp", "displacement", "height"), "height"),
    **dict.fromkeys(("ao", "occlusion"), "ao"),
    **dict.fromkeys(("opacity", "alpha", "mask"), "opacity"),
    **dict.fromkeys(("emissive", "emission"), "emission"),
    "arm": "arm",
    "orm": "orm",
}
TWO_TOKEN_ROLES = {("base", "color"): "basecolor", ("base", "colour"): "basecolor",
                   ("ambient", "occlusion"): "ao"}  # fmt: skip
CONVENTIONS = {"gl": "gl", "opengl": "gl", "dx": "dx", "directx": "dx"}
FORMAT_TOKENS = {"jpg", "jpeg", "png", "exr", "tif", "tiff", "hdr", "tga"}
RESOLUTIONS = {"512", "1024", "2048", "4096", "8192", "16384"}
# Packed maps: channel -> role (Poly Haven `arm`, Unreal-style `orm`).
PACKED = {"arm": {0: "ao", 1: "roughness", 2: "metalness"},
          "orm": {0: "ao", 1: "roughness", 2: "metalness"}}  # fmt: skip
COLOUR_SOURCE_ROLES = {"basecolor", "diffuse", "specular", "emission", "color", "hdri"}
ROLE_ORDER = ["basecolor", "diffuse", "specular", "glossiness", "metalness", "roughness",
              "specular_level", "normal", "height", "ao", "opacity", "emission", "color", "data",
              "hdri"]  # fmt: skip
FORMAT_PREFERENCE = [".exr", ".tif", ".tiff", ".png", ".tga", ".jpg", ".jpeg"]
_UDIM = re.compile(r"(.+)\.(1[0-9]{3})")
_SPLIT = re.compile(r"[_\-.\s]+")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


# --- names --------------------------------------------------------------------------------


def tokens(stem: str) -> list[str]:
    """`Metal032_4K-JPG_NormalGL` -> Metal032, 4K, JPG, Normal, GL."""
    return [t for part in _SPLIT.split(stem) for t in _CAMEL.split(part) if t]


def _ignored(token: str) -> bool:
    t = token.lower()
    return (
        t in FORMAT_TOKENS
        or t in RESOLUTIONS
        or re.fullmatch(r"[0-9]+k", t) is not None
        or re.fullmatch(r"lod[0-9]+", t) is not None
        or variant_from_token(t) is not None
    )


def _resolution(toks: list[str]) -> int:
    for t in (t.lower() for t in toks):
        if re.fullmatch(r"[0-9]+k", t):
            return int(t[:-1]) * 1024
        if t in RESOLUTIONS:
            return int(t)
    return 0


@dataclass(frozen=True)
class NameInfo:
    role: str | None  # also `arm`/`orm` for packed maps
    base: str  # lowercase, the name part that groups the maps of one set
    display: list[str]  # the base tokens as written, for the display name
    convention: str | None  # normal maps: gl / dx
    variant: str | None
    resolution: int  # 0 when the name has none


def parse_name(stem: str) -> NameInfo:
    toks = tokens(stem)
    low = [t.lower() for t in toks]
    role, at = None, len(toks)
    for i, t in enumerate(low):  # the last role token wins (Q1)
        if i + 1 < len(low) and (t, low[i + 1]) in TWO_TOKEN_ROLES:
            role, at = TWO_TOKEN_ROLES[(t, low[i + 1])], i
        elif t in ROLE_TOKENS and not (i > 0 and (low[i - 1], t) in TWO_TOKEN_ROLES):
            role, at = ROLE_TOKENS[t], i
    before = [t for t in toks[:at] if not _ignored(t)]
    if role is None:
        before = [t for t in toks if not _ignored(t)]
    convention = next((CONVENTIONS[t] for t in low if t in CONVENTIONS), None)
    variant = next((v for t in low if (v := variant_from_token(t))), None)
    return NameInfo(role, "_".join(t.lower() for t in before), before, convention, variant,
                    _resolution(toks))  # fmt: skip


def display_name(stem: str) -> str:
    """`Rusty_Metal_02_4K` -> `Rusty Metal 02`: resolution, format and variant tokens dropped."""
    return _display([t for t in tokens(stem) if not _ignored(t)])


def _display(toks: list[str]) -> str:
    return " ".join(t[:1].upper() + t[1:] if t.islower() else t for t in toks)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


# --- files -> maps ------------------------------------------------------------------------


@dataclass
class Map:
    """One image, or one UDIM map (all its tiles)."""

    path: Path  # the file, or `name.<UDIM>.ext`
    files: list[Path]  # the file, or every tile
    name: NameInfo
    variant: str
    info: ImageInfo | None = None

    @property
    def key(self) -> str:
        return str(self.path)


@dataclass
class Detected:
    entries: list[dict] = field(default_factory=list)
    unused: list[dict] = field(default_factory=list)

    def as_json(self) -> dict:
        return {"entries": self.entries, "unused": self.unused}


def _maps(images: list[tuple[Path, str | None]]) -> list[Map]:
    """Images (with the variant of their folder, if any) -> maps; UDIM tiles become one map."""
    maps: dict[Path, Map] = {}
    for path, folder_variant in sorted(images, key=lambda t: str(t[0])):
        m = _UDIM.fullmatch(path.stem)
        stem = m[1] if m else path.stem
        key = path.with_name(f"{stem}.<UDIM>{path.suffix}") if m else path
        if key in maps:
            maps[key].files.append(path)
            continue
        name = parse_name(stem)
        maps[key] = Map(key, [path], name, name.variant or folder_variant or "main")
    return list(maps.values())


def _pick(candidates: list[Map]) -> tuple[Map, list[Map]]:
    """One map per role and variant: GL normals before unmarked before DX (Q3), then the
    highest resolution, then the better format."""

    def rank(m: Map) -> tuple:
        conv = {"gl": 0, None: 1, "dx": 2}[m.name.convention]
        fmt = m.path.suffix.lower()
        order = FORMAT_PREFERENCE.index(fmt) if fmt in FORMAT_PREFERENCE else 99
        return (conv, -m.name.resolution, order, len(m.path.parts), str(m.path))

    ranked = sorted(candidates, key=rank)
    return ranked[0], ranked[1:]


def _entry(type_: str, name: str) -> dict:
    return {
        "schema": 1,
        "type": type_,
        "name": name,
        "target": {"item": None, "variant": None},
        "variants": {},
        "skipped": [],
        "workflow": None,
        "metal_threshold": None,
        "size_m": None,
        "displacement": None,
        "scale": None,
        "categories": [],
        "tags": [],
        "credits": "",
        "license": "",
        "source_url": "",
        "status": "ready",
        "messages": [],
    }


def _file(m: Map, role: str, srgb: str, linear: str, channel: int | None = None,
          invert: bool = False) -> dict:  # fmt: skip
    if role in COLOUR_SOURCE_ROLES:
        space = linear if m.info and m.info.is_float else srgb
    else:
        space = "raw"
    return {
        "path": str(m.path),
        "role": role,
        "color_space": space,
        "flip_green": role == "normal" and m.name.convention == "dx",
        "invert": invert,
        "channel": channel,
    }


def _sort_files(files: list[dict]) -> list[dict]:
    return sorted(files, key=lambda f: (ROLE_ORDER.index(f["role"]), f["path"], f["channel"] or 0))


def _texture_set(group: list[Map], srgb: str, linear: str) -> dict:
    entry = _entry("texture_set", _display(group[0].name.display))
    variants: dict[str, dict[str, Map]] = {}
    packed: dict[str, list[Map]] = {}
    for variant in sorted({m.variant for m in group}):
        by_role: dict[str, list[Map]] = {}
        for m in (m for m in group if m.variant == variant):
            by_role.setdefault(m.name.role, []).append(m)
        chosen = {}
        for role, candidates in by_role.items():
            if role in PACKED:
                packed[variant] = candidates
                continue
            best, rest = _pick(candidates)
            chosen[role] = best
            entry["skipped"] += [str(r.path) for r in rest]
        variants[variant] = chosen
    roles = {r for chosen in variants.values() for r in chosen}
    roles |= {r for maps in packed.values() for m in maps for r in PACKED[m.name.role].values()}
    spec_gloss = bool(roles & {"specular", "glossiness"}) and not roles & {"metalness", "roughness"}
    entry["workflow"] = "spec_gloss" if spec_gloss else "metal_rough"
    if spec_gloss:
        entry["metal_threshold"] = METAL_THRESHOLD
        entry["status"] = "warning"
        entry["messages"].append(
            f"A spec/gloss set: it is converted to metal/rough (metal threshold "
            f"{METAL_THRESHOLD}, an approximation). Check the preview."
        )
    for variant, chosen in variants.items():
        files = []
        for role, m in chosen.items():
            if not spec_gloss:  # Q4: diffuse -> basecolor, spec -> specular_level, gloss -> rough
                if role == "diffuse":
                    if "basecolor" in chosen:
                        entry["skipped"].append(str(m.path))
                        continue
                    role = "basecolor"
                elif role == "specular":
                    role = "specular_level"
                elif role == "glossiness":
                    if "roughness" in chosen:
                        entry["skipped"].append(str(m.path))
                        continue
                    files.append(_file(m, "roughness", srgb, linear, invert=True))
                    continue
            files.append(_file(m, role, srgb, linear))
        have = {f["role"] for f in files}
        for m in packed.get(variant, []):  # Q2: only the roles not there as separate files
            used = False
            for channel, role in PACKED[m.name.role].items():
                if role not in have:
                    files.append(_file(m, role, srgb, linear, channel=channel))
                    have.add(role)
                    used = True
            if not used:
                entry["skipped"].append(str(m.path))
        if any(f["role"] == "normal" and not _map_of(group, f).name.convention for f in files):
            entry["messages"].append(
                "The normal map's name says neither GL nor DX: assumed OpenGL. "
                "Set flip_green if it is DirectX."
            )
        entry["variants"][variant] = _sort_files(files)
    return entry


def _map_of(group: list[Map], f: dict) -> Map:
    return next(m for m in group if str(m.path) == f["path"])


def _is_hdri(group: list[Map]) -> bool:
    return all(m.info and m.info.is_float and m.info.width == 2 * m.info.height for m in group)


def _single(group: list[Map], srgb: str, linear: str) -> dict:
    """HDRI (float, 2:1) or texture (colour or data: by the role in its name, else one channel
    is data), variants allowed, the best map of each variant (as in a set)."""
    first = group[0]
    info = first.info or ImageInfo(0, 0, 3, "uint8")
    hdri = _is_hdri(group)
    if hdri:
        role = "hdri"
    elif first.name.role:
        role = "color" if first.name.role in COLOUR_SOURCE_ROLES else "data"
    else:
        role = "data" if info.channels == 1 else "color"
    entry = _entry("hdri" if hdri else "texture", _display(first.name.display) or "Untitled")
    for variant in sorted({m.variant for m in group}):
        best, rest = _pick([m for m in group if m.variant == variant])
        entry["variants"][variant] = [_file(best, role, srgb, linear)]
        entry["skipped"] += [str(m.path) for m in rest]
    return entry


_METRES = re.compile(r"\s*([0-9.]+)\s*m?\s*")
_AREA = re.compile(r"\s*([0-9.]+)\s*x\s*([0-9.]+)\s*m?\s*")


def _quixel(path: Path) -> dict | None:
    """A Quixel Bridge `<id>.json`: its id, display name, scan area and displacement height."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("meta"), list):
        return None
    if not (isinstance(data.get("id"), str) and isinstance(data.get("name"), str)):
        return None
    meta = {m.get("key"): m.get("value") for m in data["meta"] if isinstance(m, dict)}
    area = _AREA.fullmatch(str(meta.get("scanArea") or ""))
    height = _METRES.fullmatch(str(meta.get("height") or ""))
    try:
        size = [float(area[1]), float(area[2])] if area else None
        height_m = float(height[1]) if height else None
    except ValueError:
        size = height_m = None
    return {
        "file": path,
        "id": data["id"].lower(),
        "name": " ".join(data["name"].split()),
        "size_m": size if size and min(size) > 0 else None,
        "height_m": height_m if height_m and height_m > 0 else None,
    }


def _use_metadata(entry: dict, info: dict) -> None:
    """Fill an entry from a metadata file found next to its maps (spec §17.5 Metadata)."""
    entry["name"] = info["name"] or entry["name"]
    if entry["type"] in ("texture", "texture_set"):
        entry["size_m"] = info["size_m"]
        has_height = any(f["role"] == "height" for fs in entry["variants"].values() for f in fs)
        if has_height and info["height_m"]:
            entry["displacement"] = {"mid": 0.5, "height_m": info["height_m"]}
    entry["messages"].append(f"Name and size from {info['file'].name} (Quixel).")


def _batch(
    files: list[tuple[Path, str | None]],
    probe: Callable[[Path], ImageInfo],
    srgb: str,
    linear: str,
    out: Detected,
) -> None:
    """Entries from the files of one folder (or the loose files that were dropped)."""
    images, others = [], []
    for path, variant in files:
        ext = path.suffix.lower()
        if ext in MODELS:
            out.unused.append({"path": str(path), "reason": "models are ingested from step L4 on"})
        elif ext in UNSUPPORTED:
            out.unused.append({"path": str(path), "reason": "unsupported image format"})
        elif ext in IMAGES:
            images.append((path, variant))
        else:
            others.append(path)
    maps = []
    for m in _maps(images):
        try:
            m.info = probe(m.files[0])
        except ScheinwerkError as exc:
            out.unused.append({"path": str(m.path), "reason": f"can't be read: {exc}"})
            continue
        maps.append(m)
    groups: dict[str, list[Map]] = {}
    for m in maps:
        groups.setdefault(m.name.base if m.name.role else f"\0{m.name.base}", []).append(m)
    sets = [g for g in groups.values() if len({m.name.role for m in g if m.name.role}) >= 2]
    singles = [g for g in groups.values() if g not in sets]
    named = [g for g in singles if any(m.name.role for m in g)]  # maps named after a role
    owners = [_texture_set(g, srgb, linear) for g in sets] + [
        _single(g, srgb, linear) for g in named
    ]  # the entries that previews and other files next to them belong to
    entries = list(owners)
    leftovers = [*others]
    for g in singles:
        if g in named:
            continue
        if owners and not _is_hdri(g):
            leftovers += [m.path for m in g]  # previews and such, dropped with the maps
        else:
            entries.append(_single(g, srgb, linear))
    sidecars = [q for p in others if p.suffix.lower() == ".json" and (q := _quixel(p))]
    for group, entry in zip([*sets, *named], owners, strict=True):
        match = [q for q in sidecars if q["id"] == group[0].name.base]
        if not match and len(owners) == 1 and len(sidecars) == 1:
            match = sidecars  # Quixel atlases: folder and json `qieuu2`, maps `qieuu_…`
        if len(match) == 1:
            _use_metadata(entry, match[0])
    if len(owners) == 1:
        owners[0]["skipped"] += [str(p) for p in leftovers]
    else:
        reason = "not part of any entry"
        out.unused += [{"path": str(p), "reason": reason} for p in leftovers]
    for e in entries:
        e["skipped"] = sorted(set(e["skipped"]))
    out.entries += entries


# --- folders, zips, duplicates ------------------------------------------------------------


def _hidden(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in DEFAULTS["ignore"])


def _map_bases(files: list[Path]) -> set[str]:
    """The base names of the images here that are named after a role."""
    names = (parse_name(f.stem) for f in files if f.suffix.lower() in IMAGES)
    return {n.base for n in names if n.role}


def _all_files(folder: Path) -> list[Path]:
    return sorted(f for f in folder.rglob("*") if f.is_file() and not any(
        _hidden(p) for p in f.relative_to(folder).parts))  # fmt: skip


def _walk(folder: Path, batches: list[list[tuple[Path, str | None]]]) -> None:
    """One batch per folder; `Var1/`-style subfolders join their parent's batch as variants.
    Under a folder whose own images are named after roles, a subfolder joins it too when it has
    no other maps (Quixel's `Thumbs/2k/` copies, `previews/`); one with other maps stays apart."""
    batch: list[tuple[Path, str | None]] = []
    subfolders: list[Path] = []
    for entry in sorted(folder.iterdir()):
        if _hidden(entry.name):
            continue
        if entry.is_dir():
            variant = variant_from_token(entry.name)
            if variant:
                batch += [(f, variant) for f in sorted(entry.iterdir())
                          if f.is_file() and not _hidden(f.name)]  # fmt: skip
            else:
                subfolders.append(entry)
        elif entry.is_file():
            batch.append((entry, None))
    bases = _map_bases([f for f, variant in batch if variant is None])
    for sub in subfolders:
        inside = _all_files(sub) if bases else []
        if inside and _map_bases(inside) <= bases:
            batch += [(f, None) for f in inside]
        else:
            _walk(sub, batches)
    if batch:
        batches.append(batch)


def _unzip(archive: Path, into: Path) -> Path:
    """Extract once into `into/<name>_<hash>` (machine-local, outside the library)."""
    folder = into / f"{archive.stem}_{sha256(archive)[:8]}"
    if not folder.is_dir():
        with zipfile.ZipFile(archive) as z:
            z.extractall(folder)  # extractall drops absolute and `..` member paths
    return folder


def _known_hashes(library: Library) -> dict[str, str]:
    """sha256 -> `type/id vNNN` for every original recorded in the library."""
    known = {}
    for item in library.items():
        for version in item.versions():
            for digest in ((version.info or {}).get("sha256") or {}).values():
                known.setdefault(digest, f"{item.type}/{item.id} {version.path.name}")
    return known


def _check_duplicates(entry: dict, known: dict[str, str]) -> None:
    paths = {p for files in entry["variants"].values() for f in files for p in _expand(f["path"])}
    hits = sorted({known[h] for p in paths if (h := sha256(p)) in known})
    if hits:
        entry["messages"].append(f"These files were ingested before: {', '.join(hits)}.")
        if entry["status"] == "ready":
            entry["status"] = "warning"


def _expand(path: str) -> list[Path]:
    """A map's files: the file, or every tile of a `<UDIM>` pattern."""
    p = Path(path)
    if "<UDIM>" not in p.name:
        return [p]
    head, tail = p.name.split("<UDIM>")
    return sorted(f for f in p.parent.iterdir() if re.fullmatch(
        re.escape(head) + "1[0-9]{3}" + re.escape(tail), f.name))  # fmt: skip


def detect(
    paths: list[Path],
    probe: Callable[[Path], ImageInfo],
    srgb: str,
    linear: str,
    library: Library | None = None,
    unzip_dir: Path | None = None,
) -> Detected:
    """Plans for everything in `paths` (files, folders, zips). Writes nothing except
    extracted zips (in `unzip_dir`, default the machine-local user folder)."""
    out = Detected()
    batches: list[list[tuple[Path, str | None]]] = []
    loose: list[tuple[Path, str | None]] = []
    for path in paths:
        path = Path(path).absolute()
        if path.is_dir():
            _walk(path, batches)
        elif path.suffix.lower() == ".zip":
            _walk(_unzip(path, unzip_dir or user_dir() / "unzipped"), batches)
        elif path.is_file():
            loose.append((path, None))
        else:
            out.unused.append({"path": str(path), "reason": "not found"})
    if loose:
        batches.append(loose)
    for batch in batches:
        _batch(batch, probe, srgb, linear, out)
    if library is not None:
        known = _known_hashes(library)
        for entry in out.entries:
            _check_duplicates(entry, known)
    out.entries.sort(key=lambda e: (e["name"].casefold(), e["type"]))
    return out


def expand(path: str) -> list[Path]:
    """Public: the files behind a plan path (UDIM patterns expanded)."""
    return _expand(path)
