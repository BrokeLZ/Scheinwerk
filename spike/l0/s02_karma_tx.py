"""L0 spike 2 — do Karma CPU and XPU use .tx mipmaps and the `colorSpace` metadata? (spec §17.5)

Run in hython:  hython spike/l0/s02_karma_tx.py
Needs s01_textures to have run (uses its textures).
"""

from __future__ import annotations

import OpenImageIO as oiio_py

from common import OUT_ROOT, Log, close, husk, oiio, run, stats, tool, write
from usdtext import emission_material, header, image_node, ortho_camera, persp_camera, plane

log = Log("s02_karma_tx")
d = log.dir
tex = OUT_ROOT / "s01_textures"
if not (tex / "col.exr").exists():
    raise SystemExit("run s01_textures.py first")


def avg_rgb(path) -> list[float]:
    buf = oiio_py.ImageBuf(str(path))
    st = oiio_py.ImageBufAlgo.computePixelStats(buf)
    return [round(v, 4) for v in st.avg[:3]]


def render(
    name: str, file: str, cs: str | None, engine: str, res: int = 16, persp: bool = False
) -> list[float] | None:
    # perspective: the 2x2 plane fills the frame (36 mm aperture, 50 mm lens, 2.7 units away)
    cam = (
        persp_camera("cam", (0, 0, 2.7), (0, 0, 0), 50, 36) if persp else ortho_camera(width=1.5)
    )  # inside the 2x2 plane: no edge pixels
    usd = write(
        d / f"{name}.usda",
        header() + cam + plane("plane", "/M") + emission_material("M", image_node(file, cs)),
    )
    out = d / f"{name}_{engine}.exr"
    p = husk(usd, out, log, engine, (res, res), ["-p", "4"])
    if p.returncode != 0 or not out.exists():
        return None
    return avg_rgb(out)


# --- 1. a texture whose MIP levels differ: level 0 red, all smaller levels green -------------
MIP_WRITER = """
import sys, OpenImageIO as oiio
path = sys.argv[1]
out = oiio.ImageOutput.create(path)
level, w = 0, 256
while w >= 1:
    s = oiio.ImageSpec(w, w, 3, "half")
    s.tile_width = s.tile_height = 64
    s.attribute("textureformat", "Plain Texture")
    buf = oiio.ImageBuf(s)
    oiio.ImageBufAlgo.fill(buf, (1, 0, 0) if level == 0 else (0, 1, 0))
    assert out.open(path, s, "Create" if level == 0 else "AppendMIPLevel"), out.geterror()
    assert out.write_image(buf.get_pixels(oiio.HALF)), out.geterror()
    level, w = level + 1, w // 2
out.close()
"""


def write_mip_test(path) -> None:
    """Tiled half EXR with hand-made MIP levels: level 0 red, the rest green.

    Written by a child hython: inside this process OIIO only flushes the file at exit.
    """
    script = write(d / "_mipwriter.py", MIP_WRITER)
    run([tool("hython"), script, path], log)


log("## MIP maps: level 0 red, smaller levels green")
log("A minified render that comes out green read the file's own MIP levels.")
write_mip_test(d / "mip_test.exr")
oiio([d / "mip_test.exr", "-a", "-d", "uint8", "-o", d / "mip_test.tx"], log)  # same levels, TIFF
oiio(["--pattern", "constant:color=1,0,0", "256x256", 3, "-d", "uint8", "-o", d / "red.png"], log)
for name in ("mip_test.exr", "mip_test.tx", "red.png"):
    levels = [ln for ln in oiio(["--info", "-v", d / name]).stdout.splitlines() if "MIP" in ln]
    log.note(f"{name} levels", levels[0].strip() if levels else "none (scanline, no MIPs)")
    for engine in ("cpu", "xpu"):
        for persp in (True, False):
            cam = "persp" if persp else "ortho"
            small = render(f"mip_{name}_{cam}_small", f"./{name}", "raw", engine, 8, persp)
            big = render(f"mip_{name}_{cam}_big", f"./{name}", "raw", engine, 1024, persp)
            if name == "red.png":
                log.note(
                    f"{engine} {cam} {name} (no MIPs in file): minified / magnified",
                    f"{small} / {big}",
                )
                continue
            log.check(
                f"{engine} {cam} {name}: minified uses the file's small MIPs (green)",
                small is not None and small[1] > 0.8,
                small,
            )
            log.check(
                f"{engine} {cam} {name}: magnified uses level 0 (red)",
                big is not None and big[0] > 0.9,
                big,
            )

# --- 2. colorSpace metadata ----------------------------------------------------------------------
log("\n## colorSpace metadata on inputs:file (MaterialX ND_image_color3, emission only)")
import PyOpenColorIO as OCIO  # noqa: E402

cfg = OCIO.GetCurrentConfig()
scene_linear = cfg.getColorSpace("scene_linear").getName()
log.note("OCIO config", f"{cfg.getName()} ($OCIO={__import__('os').environ.get('OCIO')})")
log.note("scene_linear role (= Karma's rendering space)", scene_linear)
ref_file = d / "ref_scene_linear.exr"
oiio(
    [
        tex / "col8.png",
        "--colorconvert",
        "sRGB - Texture",
        scene_linear,
        "-d",
        "float",
        "-o",
        ref_file,
    ],
    log,
)
ref = stats(ref_file)["avg"]
acescg_raw = stats(tex / "ref_acescg.exr")["avg"]
log.note("expected in rendering space for sRGB(128,64,191)", [round(v, 4) for v in ref])
raw = [128 / 255, 64 / 255, 191 / 255]
# linear Rec.709 version of the same colour, half EXR
lin = d / "col_lin709.exr"
oiio(
    [
        tex / "col8.png",
        "--colorconvert",
        "sRGB - Texture",
        "Linear Rec.709 (sRGB)",
        "-d",
        "half",
        "-otex",
        lin,
    ],
    log,
)
col8_tx = d / "col8.tx"
oiio([tex / "col8.png", "-otex", col8_tx], log)  # uint8 TIFF .tx, no conversion
for name in ("col8.png", "col.exr", "col_exr.tx"):
    (d / name).write_bytes((tex / name).read_bytes())

cases = [
    # file, colorSpace, expected, what it shows
    ("./col8.png", "sRGB - Texture", ref, "8-bit sRGB, OCIO name"),
    ("./col8.png", "srgb_texture", ref, "8-bit sRGB, MaterialX name"),
    ("./col8.png", None, None, "8-bit, no metadata (Karma's guess)"),
    ("./col8.tx", "sRGB - Texture", ref, "uint8 .tx, OCIO name"),
    ("./col8.tx", "raw", raw, "uint8 .tx as data ('raw')"),
    ("./col8.tx", "Raw", raw, "uint8 .tx as data ('Raw', OCIO name)"),
    ("./col8.tx", None, None, "uint8 .tx, no metadata (Karma's guess)"),
    ("./col.exr", "ACEScg", ref, "half ACEScg .exr, OCIO name"),
    ("./col.exr", "acescg", ref, "half ACEScg .exr, MaterialX name"),
    ("./col.exr", "raw", acescg_raw, "half ACEScg .exr, raw (no conversion)"),
    ("./col.exr", None, None, "half ACEScg .exr, no metadata (file says oiio:ColorSpace=ACEScg)"),
    ("./col_exr.tx", "ACEScg", ref, "half EXR inside a .tx name"),
    ("./col_lin709.exr", "Linear Rec.709 (sRGB)", ref, "half lin709, OCIO name"),
    ("./col_lin709.exr", "lin_rec709", ref, "half lin709, MaterialX name"),
    ("./col_lin709.exr", None, None, "half lin709, no metadata"),
]
for i, (file, cs, want, what) in enumerate(cases):
    for engine in ("cpu", "xpu"):
        got = render(f"cs{i:02d}", file, cs, engine)
        if want is None:
            log.note(f"{engine} {what} [{cs}]", got)
        else:
            log.check(
                f"{engine} {what} [{cs}]",
                got is not None and close(got, want, 0.004),
                f"{got} want {[round(v, 4) for v in want]}",
            )

# --- 3. what Houdini itself writes for mtlximage's file colour space -------------------------
log("\n## How Houdini 21 authors mtlximage 'filecolorspace'")
try:
    import hou

    lib = hou.node("/stage").createNode("materiallibrary")
    img = lib.createNode("mtlximage", "img")
    img.parm("file").set("$HIP/x.tx")
    img.parm("filecolorspace").set("ACEScg")
    surf = lib.createNode("mtlxstandard_surface", "surf")
    surf.setNamedInput("base_color", img, 0)
    lib.cook(force=True)
    layer = lib.stage().ExportToString()
    lines = [ln for ln in layer.splitlines() if "file" in ln or "colorSpace" in ln]
    log.block("authored lines", "\n".join(lines))
    log.note("Houdini writes colorSpace metadata", any("colorSpace" in ln for ln in lines))
    log.note(
        "Houdini expands $HIP in the authored file value",
        any("$HIP" not in ln and "x.tx" in ln for ln in lines),
    )
except Exception as e:  # noqa: BLE001
    log.check("mtlximage authoring", False, e)

log.close()
