"""The texture processor (spec §17.5): turns originals into tiled, mipmapped maps with hoiiotool.

Project-free: the library uses it now, project `textures` products later. Each output map is
one `Recipe` (= one `files` entry of version.json) and one hoiiotool call. It writes only the
output it is given and never touches the originals.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scheinwerk.core.errors import InvalidName, NotFound, ScheinwerkError

COLOUR_ROLES = frozenset({"hdri", "color", "basecolor", "emission"})
DATA_ROLES = frozenset(
    {"data", "normal", "roughness", "metalness", "specular_level", "height", "ao", "opacity"}
)
SCALAR_ROLES = frozenset({"roughness", "metalness", "specular_level", "height", "ao", "opacity"})
HALF_MAX = 65504.0
DIELECTRIC = 0.04  # reflectance of non-metals, where metalness starts (spec §17.5)
PREVIEW_VIEW = "ACES 1.0 - SDR Video"  # tone-maps, so HDRIs don't clip (spec §17.7)
FLOAT_TYPES = ("half", "float")

# Names of the two colour spaces the processor needs, as different OCIO configs spell them.
_SRGB_TEXTURE = ("sRGB - Texture", "srgb_texture", "Utility - sRGB - Texture", "sRGB")
_LINEAR_REC709 = ("Linear Rec.709 (sRGB)", "lin_rec709", "Utility - Linear - sRGB", "linear")


# --- what the tool and the images are -----------------------------------------------------


@dataclass(frozen=True)
class ToolInfo:
    version: str
    ocio_config: str  # file name of the OCIO config in use
    color_spaces: list[str]
    displays: dict[str, list[str]]  # display -> views, defaults first
    default_display: str

    @property
    def srgb_texture(self) -> str:
        return self._pick(_SRGB_TEXTURE, "an sRGB texture")

    @property
    def linear_rec709(self) -> str:
        return self._pick(_LINEAR_REC709, "a linear Rec.709")

    def _pick(self, names: tuple[str, ...], what: str) -> str:
        found = next((n for n in names if n in self.color_spaces), None)
        if found is None:
            raise NotFound(f"The OCIO config {self.ocio_config} has no {what} colour space.")
        return found

    def preview_view(self) -> tuple[str, str]:
        """The default display, with the ACES SDR view when the config has it (spec §17.7)."""
        views = self.displays.get(self.default_display, [])
        view = PREVIEW_VIEW if PREVIEW_VIEW in views else (views[0] if views else "")
        return self.default_display, view


def _quoted(text: str) -> list[str]:
    return re.findall(r'"([^"]*)"', text)


def parse_tool_info(help_text: str) -> ToolInfo:
    """Read `hoiiotool --help`: version, OCIO config, colour spaces, displays and views."""
    version = re.search(r"OpenImageIO ([0-9][0-9.]*)", help_text)
    config = re.search(r"color config: (.+)", help_text)
    spaces = re.search(r"Known color spaces: (.+)", help_text)
    displays: dict[str, list[str]] = {}
    default = ""
    line = re.search(r"Known displays: (.+)", help_text)
    for match in re.finditer(r'"([^"]+)"(\*?) \(views: ([^)]*)\)', line[1] if line else ""):
        views = _quoted(match[3])
        starred = re.search(r'"([^"]+)"\*', match[3])
        if starred:  # the default view first
            views.remove(starred[1])
            views.insert(0, starred[1])
        displays[match[1]] = views
        if match[2] and not default:
            default = match[1]
    return ToolInfo(
        version=version[1] if version else "",
        ocio_config=PurePosixPath(config[1].strip().replace("\\", "/")).name if config else "",
        color_spaces=_quoted(spaces[1]) if spaces else [],
        displays=displays,
        default_display=default or next(iter(displays), ""),
    )


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    channels: int
    format: str  # uint8, uint16, half, float, …

    @property
    def is_float(self) -> bool:
        return self.format in FLOAT_TYPES or self.format == "double"


def parse_image_info(line: str) -> ImageInfo:
    """`a.png :  256 x  256, 3 channel, uint8 png` -> ImageInfo."""
    m = re.search(r":\s*([0-9]+) x\s*([0-9]+), ([0-9]+) channel, ([a-z0-9]+)", line)
    if not m:
        raise ScheinwerkError(f"Can't read the image information: {line.strip()}")
    return ImageInfo(int(m[1]), int(m[2]), int(m[3]), m[4])


def parse_stats_max(text: str) -> float:
    """The highest `Stats Max` value of all channels (integer images scaled to 0..1)."""
    m = re.search(r"Stats Max:([^\n]*)", text)
    if not m:
        raise ScheinwerkError("hoiiotool printed no statistics.")
    values, _, scale = m[1].partition("(of ")
    div = float(scale.rstrip(") \n")) if scale else 1.0
    numbers = [float(v) for v in re.findall(r"-?[0-9.]+(?:e[-+]?[0-9]+)?", values)]
    return max(numbers) / div


# --- what to write ------------------------------------------------------------------------


def output_type(role: str, source: ImageInfo, peak: float | None = None) -> str:
    """Colour roles: half (an HDRI brighter than half can hold: float). Data roles keep the
    source's bit depth: 8/16-bit integer stays integer, float stays float (spec §17.5)."""
    if role in COLOUR_ROLES:
        return "float" if role == "hdri" and peak is not None and peak > HALF_MAX else "half"
    if source.format in ("uint8", "uint16", "half", "float"):
        return source.format
    return "float" if source.is_float else "uint16"


def extension(data_type: str) -> str:
    """OpenEXR for half/float, TIFF `.tx` for 8/16-bit (TIFF has no half, spec §17.5)."""
    return "exr" if data_type in FLOAT_TYPES else "tx"


@dataclass(frozen=True)
class Recipe:
    """One output map: how it is made from its originals. Mirrors a version.json `files`
    entry (spec §17.4). `metal_threshold` is set only for maps made by the spec/gloss →
    metal/rough conversion: `metalness` from the specular map, `basecolor` from diffuse and
    specular (in that order)."""

    sources: tuple[Path, ...]
    output: Path
    role: str
    from_space: str
    to_space: str
    data_type: str
    flip_green: bool = False
    invert: bool = False
    metal_threshold: float | None = None
    channel: int | None = None  # one channel of a packed map (Poly Haven arm, ORM)

    def entry(self, version_dir: Path) -> dict:
        """The version.json `files` entry, paths relative to the version folder."""

        def rel(p: Path) -> str:  # sources may sit in an earlier version: ../v001/source/…
            return Path(os.path.relpath(p, version_dir)).as_posix()

        data = {
            "source": [rel(s) for s in self.sources],
            "output": rel(self.output),
            "role": self.role,
            "from_space": self.from_space,
            "to_space": self.to_space,
            "data_type": self.data_type,
            "flip_green": self.flip_green,
            "invert": self.invert,
        }
        if self.channel is not None:
            data["channel"] = self.channel
        return data


def _check(r: Recipe) -> None:
    if r.role not in COLOUR_ROLES | DATA_ROLES:
        raise InvalidName(f"Unknown map role {r.role!r}.")
    want = extension(r.data_type)
    if r.output.suffix.lower() != f".{want}":
        raise InvalidName(f"A {r.data_type} map is written as .{want}, not {r.output.name}.")
    if r.role in COLOUR_ROLES and r.data_type not in FLOAT_TYPES:
        raise InvalidName(f"{r.role} maps are written as half or float, not {r.data_type}.")
    if r.role in DATA_ROLES and r.to_space != "raw":
        raise InvalidName(f"{r.role} is data: its colour space is raw, not {r.to_space}.")
    if r.channel is not None and r.role not in SCALAR_ROLES:
        raise InvalidName(f"Only single-value maps can come from one channel, not {r.role}.")
    if r.metal_threshold is not None and r.metal_threshold <= DIELECTRIC:
        raise InvalidName(f"metal_threshold must be above {DIELECTRIC}.")
    spec_gloss_base = r.role == "basecolor" and r.metal_threshold is not None
    if spec_gloss_base and len(r.sources) != 2:
        raise InvalidName("A spec/gloss basecolor needs two sources: diffuse, then specular.")
    if not spec_gloss_base and len(r.sources) != 1:
        raise InvalidName(f"A {r.role} map needs one source, not {len(r.sources)}.")


def _num(value: float) -> str:
    return f"{value:.6g}"


def _to_rgb(channels: int) -> list[str]:
    return ["--ch", "0,0,0"] if channels == 1 else ["--ch", "R,G,B"] if channels > 3 else []


def _metalness(threshold: float) -> list[str]:
    """Linear specular -> metalness: 0 at 4 % reflectance, 1 at the threshold (spec §17.5)."""
    return [
        "--maxchan",
        "--subc",
        _num(DIELECTRIC),
        "--divc",
        _num(threshold - DIELECTRIC),
        "--clamp:min=0:max=1",
    ]


def command(r: Recipe, channels: int, linear: str) -> list[str]:
    """The hoiiotool arguments for one recipe. `channels`: of the (first) source; `linear`:
    the config's linear Rec.709 space, for the spec/gloss maths."""
    _check(r)
    src = [str(s) for s in r.sources]
    out = ["-d", r.data_type, "-oenv" if r.role == "hdri" else "-otex", str(r.output)]
    if r.role == "basecolor" and r.metal_threshold is not None:
        diff, spec = src
        return [
            diff, *_to_rgb(channels), "--colorconvert", r.from_space, linear, "--label", "diff",
            spec, "--colorconvert", r.from_space, linear, "--label", "spec",
            "spec", *_metalness(r.metal_threshold), "--ch", "0,0,0", "--label", "metal",
            "spec", "diff", "--sub", "metal", "--mul", "diff", "--add",
            "--colorconvert", linear, r.to_space, *out,
        ]  # fmt: skip
    if r.role == "metalness" and r.metal_threshold is not None:
        convert = ["--colorconvert", r.from_space, linear]
        return [src[0], *_to_rgb(channels), *convert, *_metalness(r.metal_threshold), *out]
    if r.role in COLOUR_ROLES:
        return [src[0], *_to_rgb(channels), "--colorconvert", r.from_space, r.to_space, *out]
    args = [src[0]]
    if r.role in SCALAR_ROLES and (channels > 1 or r.channel):
        args += ["--ch", str(r.channel or 0)]
    if r.role == "normal" and channels > 3:
        args += ["--ch", "R,G,B"]
    if r.invert:
        args.append("--invert")
    if r.flip_green:
        args.append("--invert:chbegin=1:chend=2")
    return [*args, *out]


def fit_size(width: int, height: int, box: tuple[int, int]) -> tuple[int, int]:
    """The largest size within `box` with the image's aspect, never bigger than the image.
    (hoiiotool's --fit pads to the whole box instead.)"""
    scale = min(box[0] / width, box[1] / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def thumbnail_command(
    src: Path, out: Path, channels: int, space: str, view: tuple[str, str], size: tuple[int, int]
) -> list[str]:
    """A JPEG preview of `size`: through the display view unless the map is data (`raw`)."""
    args = [str(src), *_to_rgb(channels)]
    if space.lower() != "raw":
        args += [f"--ociodisplay:from={space}", *view]
    return [
        *args,
        "--resize:filter=lanczos3",
        f"{size[0]}x{size[1]}",
        "-d",
        "uint8",
        "-o",
        str(out),
    ]


# --- running hoiiotool --------------------------------------------------------------------


def run_tool(tool: Path, args: list) -> str:
    """Run hoiiotool; its output, or a ScheinwerkError with the tail of its messages."""
    p = subprocess.run([str(tool), *(str(a) for a in args)], capture_output=True, text=True)
    if p.returncode != 0:
        message = (p.stderr or p.stdout).strip().splitlines()
        raise ScheinwerkError(
            f"hoiiotool failed ({p.returncode}): " + " / ".join(message[-3:] or ["no message"])
        )
    return p.stdout


def tool_info(tool: Path) -> ToolInfo:
    return parse_tool_info(run_tool(tool, ["--help"]))


def probe(path: Path, tool: Path) -> ImageInfo:
    out = run_tool(tool, ["--info", path])
    line = next((ln for ln in out.splitlines() if " channel, " in ln), out)
    return parse_image_info(line)


def is_mipmapped(path: Path, tool: Path) -> bool:
    return "MIP-map levels" in run_tool(tool, ["--info", "-v", path])


def peak(
    path: Path, tool: Path, from_space: str | None = None, to_space: str | None = None
) -> float:
    """The brightest channel value, after converting to `to_space` when given."""
    convert = ["--colorconvert", from_space, to_space] if from_space and to_space else []
    return parse_stats_max(run_tool(tool, [path, *convert, "--printstats"]))


def process(r: Recipe, tool: Path, linear: str) -> None:
    """Write one map. Creates the output's folder; never touches the sources."""
    channels = probe(r.sources[0], tool).channels
    args = command(r, channels, linear)
    r.output.parent.mkdir(parents=True, exist_ok=True)
    run_tool(tool, args)


def thumbnail(
    src: Path,
    out: Path,
    tool: Path,
    space: str,
    view: tuple[str, str],
    box: tuple[int, int],
    exact: bool = False,
) -> None:
    """Preview of `src` fitted into `box` (or exactly `box`: HDRIs are 1024 × 512)."""
    info = probe(src, tool)
    size = box if exact else fit_size(info.width, info.height, box)
    out.parent.mkdir(parents=True, exist_ok=True)
    run_tool(tool, thumbnail_command(src, out, info.channels, space, view, size))
