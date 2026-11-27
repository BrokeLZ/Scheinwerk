"""L0 spike 1 — texture tools (spec §17.5): which exist, which flags do what we need.

Run with any Python 3.11:  python spike/l0/s01_textures.py
"""

from __future__ import annotations

import re

from common import EXE, Log, close, hfs, info, oiio, pixel, run, stats, tool

log = Log("s01_textures")
d = log.dir
log(f"HFS: {hfs()}")

# --- 1. what exists -------------------------------------------------------------------
log("\n## Tools in $HFS/bin")
for name in (
    "hoiiotool",
    "imaketx",
    "iconvert",
    "maketx",
    "oiiotool",
    "husk",
    "hython",
    "ocioconvert",
    "ociocheck",
    "usdcat",
    "usdrecord",
):
    log.note(f"exists {name}{EXE}", tool(name).exists())

help_text = oiio(["--help"]).stdout
for key, pat in [
    ("oiio version", r"OpenImageIO ([\d.]+)"),
    ("ocio version", r"OpenColorIO ([\d.]+)"),
    ("default ocio config", r"color config: (.+)"),
    ("input formats", r"Input formats supported: (.+)"),
    ("output formats", r"Output formats supported: (.+)"),
]:
    m = re.search(pat, help_text)
    log.note(key, m.group(1).strip() if m else "?")
spaces = re.search(r"Known color spaces: (.+)", help_text)
log.note("colour spaces", spaces.group(1) if spaces else "?")
displays = re.search(r"Known displays: (.+)", help_text)
log.note("displays", displays.group(1) if displays else "?")

# --- 2. inputs (made with hoiiotool itself) --------------------------------------------
P = "--pattern"
oiio([P, "constant:color=0.5,0.25,0.75", "256x256", 3, "-d", "uint8", "-o", d / "col8.png"], log)
oiio([P, "constant:color=0.5,0.25,0.75", "256x256", 3, "-d", "uint16", "-o", d / "col16.png"], log)
oiio([P, "constant:color=0.3", "256x256", 1, "-d", "uint8", "-o", d / "rough8.png"], log)
oiio([P, "constant:color=0.3", "256x256", 1, "-d", "uint16", "-o", d / "rough16.png"], log)
oiio([P, "constant:color=0.7", "256x256", 1, "-d", "uint8", "-o", d / "gloss8.png"], log)
oiio([P, "constant:color=0.6,0.4,1.0", "256x256", 3, "-d", "uint8", "-o", d / "nrm_dx.png"], log)
# HDRI 2:1 float with a 'sun' brighter than the half maximum (65504)
oiio(
    [
        P,
        "constant:color=0.5,0.5,0.5",
        "1024x512",
        3,
        "-d",
        "float",
        "--fill:color=100000,90000,80000",
        "8x8+500+100",
        "-o",
        d / "hdri.exr",
    ],
    log,
)
for tile, col in ((1001, "1,0,0"), (1002, "0,1,0")):
    oiio([P, f"constant:color={col}", "128x128", 3, "-d", "uint8", "-o", d / f"udim.{tile}.png"])
# spec/gloss: diffuse red; specular: left half dielectric 4 %, right half gold-ish metal
oiio([P, "constant:color=0.8,0.2,0.2", "256x256", 3, "-d", "uint8", "-o", d / "sg_diffuse.png"])
oiio(
    [
        P,
        "constant:color=0.2235,0.2235,0.2235",
        "256x256",
        3,
        "-d",
        "uint8",  # sRGB of ~0.04
        "--fill:color=0.95,0.8,0.4",
        "128x256+128+0",
        "-o",
        d / "sg_spec.png",
    ],
    log,
)


def to_lin(srgb: float) -> float:
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


# --- 3. colour conversion to half -------------------------------------------------------
log("\n## Colour role: sRGB 8-bit -> ACEScg half")
ref = d / "ref_acescg.exr"
oiio([d / "col8.png", "--colorconvert", "sRGB - Texture", "ACEScg", "-d", "float", "-o", ref], log)
expected = stats(ref)["avg"]
log.note("expected ACEScg of sRGB(128,64,191)", [round(v, 4) for v in expected])

tif = d / "col_tiff.tx"
oiio(
    [d / "col8.png", "--colorconvert", "sRGB - Texture", "ACEScg", "-d", "half", "-otex", tif], log
)
log.check(
    "-d half -otex x.tx gives half", "half" in info(tif).splitlines()[0], info(tif).splitlines()[0]
)

exr_tx = d / "col_exr.tx"
p = oiio(
    [
        d / "col8.png",
        "--colorconvert",
        "sRGB - Texture",
        "ACEScg",
        "-d",
        "half",
        "-otex:fileformatname=openexr",
        exr_tx,
    ],
    log,
)
i = info(exr_tx)
log.check(
    "-otex:fileformatname=openexr x.tx gives half EXR", "half openexr" in i, i.splitlines()[0]
)
log.check(
    "  ... is tiled + mipmapped",
    "MIP-map levels" in i and "tile size" in i,
    re.search(r"MIP-map levels: (.+)", i).group(1) if "MIP-map" in i else "",
)
log.check(
    "  ... records oiio:ColorSpace",
    'oiio:ColorSpace: "ACEScg"' in i,
    re.search(r"oiio:ColorSpace: (.+)", i).group(1) if "oiio:ColorSpace" in i else "none",
)
log.check("  ... values match", close(stats(exr_tx)["avg"], expected, 0.002), stats(exr_tx)["avg"])

exr = d / "col.exr"
oiio(
    [d / "col8.png", "--colorconvert", "sRGB - Texture", "ACEScg", "-d", "half", "-otex", exr], log
)
log.check(
    "-otex x.exr gives tiled half EXR (no modifier needed)",
    "half openexr" in info(exr) and "MIP-map" in info(exr),
    info(exr).splitlines()[0],
)

ex = d / "col16.exr"
oiio(
    [d / "col16.png", "--colorconvert", "sRGB - Texture", "ACEScg", "-d", "half", "-otex", ex], log
)
log.check(
    "16-bit sRGB source converts too", close(stats(ex)["avg"], expected, 0.003), stats(ex)["avg"]
)

# imaketx for comparison
im = d / "col_imaketx.tx"
p = run([tool("imaketx"), d / "col8.png", im, "-c", "sRGB - Texture", "ACEScg"], log)
log.note("imaketx default x.tx", info(im).splitlines()[0] if im.exists() else f"failed {p.stderr}")
im2 = d / "col_imaketx.exr"
run([tool("imaketx"), "-F", "OpenEXR", d / "col8.png", im2, "-c", "sRGB - Texture", "ACEScg"], log)
log.note("imaketx -F OpenEXR", info(im2).splitlines()[0] if im2.exists() else "failed")
if im.exists():
    log.note("imaketx default output values (8-bit after conversion = banding)", stats(im)["avg"])

# --- 4. data roles keep bit depth ---------------------------------------------------------
log("\n## Data roles: no conversion, bit depth kept")
for src in ("rough8.png", "rough16.png"):
    out = d / src.replace(".png", ".tx")
    oiio([d / src, "-otex", out], log)
    first = info(out).splitlines()[0]
    want = "uint8" if "8" in src else "uint16"
    log.check(f"{src} -> .tx stays {want}", want in first, first)
    log.check("  ... value unchanged", close(stats(out)["avg"], [0.3], 0.003), stats(out)["avg"])
raw = d / "rough_raw.tx"
oiio([d / "rough8.png", "--iscolorspace", "Raw", "-otex", raw], log)
log.note(
    "--iscolorspace Raw writes oiio:ColorSpace into a TIFF .tx", "oiio:ColorSpace" in info(raw)
)

# --- 5. normal flip + gloss invert -------------------------------------------------------
log("\n## Normal green flip, gloss invert")
nrm = d / "nrm_gl.tx"
oiio([d / "nrm_dx.png", "--mulc", "1,-1,1", "--addc", "0,1,0", "-otex", nrm], log)
log.check(
    "DX->GL flip_green (G' = 1-G), stays uint8",
    close(stats(nrm)["avg"], [0.6, 0.6, 1.0], 0.003) and "uint8" in info(nrm).splitlines()[0],
    f"{stats(nrm)['avg']} {info(nrm).splitlines()[0]}",
)
nrm2 = d / "nrm_gl_invert.tx"
oiio([d / "nrm_dx.png", "--invert:chbegin=1:chend=2", "-otex", nrm2], log)
log.check(
    "same with --invert:chbegin=1:chend=2",
    close(stats(nrm2)["avg"], [0.6, 0.6, 1.0], 0.003),
    stats(nrm2)["avg"],
)
rough = d / "rough_from_gloss.tx"
oiio([d / "gloss8.png", "--invert", "-otex", rough], log)
log.check(
    "gloss -> roughness with --invert",
    close(stats(rough)["avg"], [0.3], 0.003),
    stats(rough)["avg"],
)

# --- 6. HDRI: lat-long env map, half vs float --------------------------------------------
log("\n## HDRI")
peak = max(stats(d / "hdri.exr")["max"])
log.note("source peak (from --stats Max)", peak)
for dtype in ("half", "float"):
    out = d / f"hdri_{dtype}.exr"
    oiio(
        [
            d / "hdri.exr",
            "--colorconvert",
            "Linear Rec.709 (sRGB)",
            "ACEScg",
            "-d",
            dtype,
            "-oenv",
            out,
        ],
        log,
    )
    i = info(out)
    st = stats(out)
    log.note(
        f"-oenv {dtype}: {i.splitlines()[0]}",
        f"textureformat={re.search(r'textureformat: (.+)', i).group(1)} max={st['max']} "
        f"inf={'inf' in str(st['max'])}",
    )
out = d / "hdri_half_clamped.exr"
oiio(
    [
        d / "hdri.exr",
        "--colorconvert",
        "Linear Rec.709 (sRGB)",
        "ACEScg",
        "--clamp:max=65504",
        "-d",
        "half",
        "-oenv",
        out,
    ],
    log,
)
log.note("half after --clamp:max=65504", stats(out)["max"])

# --- 7. UDIM --------------------------------------------------------------------------------
log("\n## UDIM")
p = oiio([d / "udim.<UDIM>.png", "-otex", d / "udim_tok.<UDIM>.tx"])
log.check(
    "hoiiotool understands <UDIM> in file names",
    p.returncode == 0,
    f"exit {p.returncode} (crash = negative/134)",
)
p = oiio(["--frames", "1001,1002", d / "udim.#.png", "-otex", d / "udim_frames.#.tx"])
log.check(
    "--frames 1001,1002 with '#' wildcard handles UDIM tiles in one call",
    (d / "udim_frames.1002.tx").exists(),
    f"exit {p.returncode}",
)
for tile in (1001, 1002):
    oiio([d / f"udim.{tile}.png", "-otex", d / f"udim_tile.{tile}.tx"], log)
log.check("per-tile calls", all((d / f"udim_tile.{t}.tx").exists() for t in (1001, 1002)))

# --- 8. spec/gloss -> metal/rough per-pixel maths -----------------------------------------
log("\n## spec/gloss -> metal/rough with hoiiotool only")
thr = 0.2
lin = "Linear Rec.709 (sRGB)"
cmd = [
    d / "sg_spec.png",
    "--colorconvert",
    "sRGB - Texture",
    lin,
    "--label",
    "specL",
    "--maxchan",
    "--subc",
    0.04,
    "--divc",
    thr - 0.04,
    "--clamp:min=0:max=1",
    "--label",
    "metal",
    "-d",
    "float",
    "-o",
    d / "sg_metal.exr",
    d / "sg_diffuse.png",
    "--colorconvert",
    "sRGB - Texture",
    lin,
    "--label",
    "diffL",
    "specL",
    "diffL",
    "--sub",  # specL - diffL
    "metal",
    "--ch",
    "0,0,0",
    "--mul",  # * m (as 3 channels)
    "diffL",
    "--add",  # + diffL
    "--colorconvert",
    lin,
    "ACEScg",
    "-o",
    d / "sg_basecolor.exr",
]
p = oiio(cmd, log)
log.check("command line runs", p.returncode == 0, f"{p.seconds}s")
m_left, m_right = pixel(d / "sg_metal.exr", 10, 10), pixel(d / "sg_metal.exr", 200, 10)
spec_r = [to_lin(v) for v in (0.95, 0.8, 0.4)]
m_exp = min(1.0, max(0.0, (max(spec_r) - 0.04) / (thr - 0.04)))
log.check("metalness: dielectric half ~0", close(m_left, [0.0], 0.02), m_left)
log.check("metalness: metal half", close(m_right, [m_exp], 0.01), f"{m_right} expected {m_exp:.3f}")
bc_left = pixel(d / "sg_basecolor.exr", 10, 10)
oiio(
    [
        P,
        "constant:color=0.8,0.2,0.2",
        "1x1",
        3,
        "-d",
        "uint8",
        "--colorconvert",
        "sRGB - Texture",
        "ACEScg",
        "-d",
        "float",
        "-o",
        d / "ref_diff.exr",
    ]
)
log.check(
    "basecolor on dielectric = diffuse in ACEScg",
    close(bc_left, stats(d / "ref_diff.exr")["avg"], 0.005),
    bc_left,
)
log.note(
    "basecolor on metal (diffuse blended to spec colour)", pixel(d / "sg_basecolor.exr", 200, 10)
)

# --- 9. previews -----------------------------------------------------------------------------
log("\n## Previews (display transform, fit, jpg)")
th = d / "thumb_texture.jpg"
p = oiio(
    [
        exr,
        "--ociodisplay:from=ACEScg",
        "sRGB - Display",
        "ACES 1.0 - SDR Video",
        "--fit:filter=lanczos3",
        "512x512",
        "-d",
        "uint8",
        "-o",
        th,
    ],
    log,
)
log.check(
    "texture thumb via --ociodisplay + --fit",
    th.exists(),
    info(th).splitlines()[0] if th.exists() else p.stderr[-300:],
)
th = d / "thumb_hdri.jpg"
p = oiio(
    [
        d / "hdri_float.exr",
        "--ociodisplay:from=ACEScg",
        "sRGB - Display",
        "ACES 1.0 - SDR Video",
        "--resize:filter=lanczos3",
        "1024x512",
        "-d",
        "uint8",
        "-o",
        th,
    ],
    log,
)
log.check(
    "hdri thumb 1024x512 (tone-mapped by the ACES view)",
    th.exists(),
    info(th).splitlines()[0] if th.exists() else "",
)
p = oiio(["--help"])
log.note("speed: 4k colour -> half .exr tx", "")
big = d / "big.png"
oiio([P, "noise:type=uniform:min=0:max=1", "4096x4096", 3, "-d", "uint8", "-o", big])
p = oiio([big, "--colorconvert", "sRGB - Texture", "ACEScg", "-d", "half", "-otex", d / "big.exr"])
log.note("  seconds", p.seconds)
p = run(
    [tool("imaketx"), "-F", "OpenEXR", big, d / "big_imaketx.exr", "-c", "sRGB - Texture", "ACEScg"]
)
log.note("  imaketx seconds", p.seconds)

log.close()
