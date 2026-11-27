"""L0 spike 9: how does Karma read colour textures with *your* OCIO config? (spec §17.5)

Run:  python spike/l0/s09_render_space.py   (or run_all.py s09; set OCIO to test another config)

Writes `out/<os>/s09_render_space/scene.usda`: unlit patches in a row, all the same saturated red
(sRGB 220, 40, 30), stored different ways. Karma shades in the config's `scene_linear`, and
husk writes the image converted to Linear Rec.709. A colour patch is *correct* when it shows the
red; a data patch (5, 8) when it shows the file's values untouched. The script computes both
for the config in use and compares every patch, after rendering with husk (CPU and XPU).

  0  8-bit sRGB .tx               no tag
  1  half .exr holding ACEScg     no tag
  2  half .exr holding lin Rec709 no tag
  3  half .exr holding ACEScg     tagged ACEScg
  4  half .exr holding lin Rec709 tagged Linear Rec.709
  5  8-bit sRGB .tx               tagged raw (data: correct = the file's values untouched)
  6  8-bit sRGB .tx               tagged sRGB - Texture
  7  8-bit sRGB .tx named *_srgb_tx.tx, no tag (an OCIO file rule by name)
  8  8-bit sRGB .tx               read by an ND_image_vector3 node (data, as SideFX advises)

Untagged patches show the config's file rules (by name, then by extension) or Karma's guess. In
Houdini, load the same scene.usda (Sublayer LOP) and look through /cam with Karma in the
viewport: the patches husk calls correct should look the same as each other.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from common import Log, close, hfs, husk, oiio, pixel, stats, write
from usdtext import header

log = Log("s09_render_space")
d = log.dir
SRGB, ACESCG, LIN = "sRGB - Texture", "ACEScg", "Linear Rec.709 (sRGB)"
RED = "0.863,0.157,0.118"  # sRGB (220, 40, 30): saturated, so a wrong gamut is easy to see
VECTOR = "vector3"  # not a tag: the patch reads the file with a vector3 image node

# --- the textures ---------------------------------------------------------------------------
src = d / "red8.png"
oiio(["--pattern", f"constant:color={RED}", "64x64", "3", "-d", "uint8", "-o", src], log)
oiio([src, "-otex", d / "red_srgb8.tx"], log)
oiio([src, "-otex", d / "red_srgb_tx.tx"], log)
for space, name in ((ACESCG, "red_acescg.exr"), (LIN, "red_lin709.exr")):
    oiio([src, "--colorconvert", SRGB, space, "-d", "half", "-otex", d / name], log)

PATCHES = [  # file, colorSpace tag, what it shows
    ("red_srgb8.tx", None, "8-bit sRGB .tx, no tag"),
    ("red_acescg.exr", None, "ACEScg half .exr, no tag"),
    ("red_lin709.exr", None, "Linear Rec.709 half .exr, no tag"),
    ("red_acescg.exr", ACESCG, "ACEScg half .exr, tagged ACEScg"),
    ("red_lin709.exr", LIN, "Linear Rec.709 half .exr, tagged Linear Rec.709"),
    ("red_srgb8.tx", "raw", "8-bit sRGB .tx, tagged raw"),
    ("red_srgb8.tx", SRGB, "8-bit sRGB .tx, tagged sRGB - Texture"),
    ("red_srgb_tx.tx", None, "8-bit sRGB .tx named *_srgb_tx*, no tag"),
    ("red_srgb8.tx", VECTOR, "8-bit .tx read by an ND_image_vector3 node (data)"),
]
DATA = {5, 8}  # patches that must keep the file's values untouched, as data maps need
W, GAP = 1.0, 0.1  # patch size and gap, in scene units
STEP = W + GAP
FULL_W, FULL_H = STEP * len(PATCHES), STEP
RES = (110 * len(PATCHES), 110)


def patch(i: int, file: str, cs: str | None) -> str:
    x0 = (i - (len(PATCHES) - 1) / 2) * STEP - W / 2
    x1, h = x0 + W, W / 2
    return f"""    def Mesh "patch{i}" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {{
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [({x0}, {-h}, 0), ({x1}, {-h}, 0), ({x1}, {h}, 0), ({x0}, {h}, 0)]
        normal3f[] normals = [(0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1)] (interpolation = "vertex")
        texCoord2f[] primvars:st = [(0, 0), (1, 0), (1, 1), (0, 1)] (interpolation = "vertex")
        uniform token subdivisionScheme = "none"
        rel material:binding = </scene/mtl/m{i}>
    }}
"""


def material(i: int, file: str, cs: str | None) -> str:
    vector = cs == VECTOR  # data: a vector3 image node, converted to a colour for the emission
    meta = f' (\n                colorSpace = "{cs}"\n            )' if cs and not vector else ""
    node, out, src = (
        ("ND_image_vector3", "vector3f", "conv")
        if vector
        else ("ND_image_color3", "color3f", "img")
    )
    conv = f"""            def Shader "conv"
            {{
                uniform token info:id = "ND_convert_vector3_color3"
                vector3f inputs:in.connect = </scene/mtl/m{i}/img.outputs:out>
                color3f outputs:out
            }}
""" if vector else ""  # fmt: skip
    return f"""        def Material "m{i}"
        {{
            token outputs:mtlx:surface.connect = </scene/mtl/m{i}/surf.outputs:out>
            def Shader "surf"
            {{
                uniform token info:id = "ND_standard_surface_surfaceshader"
                float inputs:base = 0
                float inputs:specular = 0
                float inputs:emission = 1
                color3f inputs:emission_color.connect = </scene/mtl/m{i}/{src}.outputs:out>
                token outputs:out
            }}
            def Shader "img"
            {{
                uniform token info:id = "{node}"
                asset inputs:file = @./{file}@{meta}
                {out} outputs:out
            }}
{conv}        }}
"""


scene = (
    header('    renderSettingsPrimPath = "/Render/settings"\n')
    + 'def Xform "scene"\n{\n'
    + "".join(patch(i, f, cs) for i, (f, cs, _) in enumerate(PATCHES))
    + '    def Scope "mtl"\n    {\n'
    + "".join(material(i, f, cs) for i, (f, cs, _) in enumerate(PATCHES))
    + "    }\n}\n\n"
    + f"""def Camera "cam"
{{
    token projection = "orthographic"
    float horizontalAperture = {FULL_W * 10}
    float verticalAperture = {FULL_H * 10}
    float2 clippingRange = (0.01, 1000)
    double3 xformOp:translate = (0, 0, 5)
    uniform token[] xformOpOrder = ["xformOp:translate"]
}}

def Scope "Render"
{{
    def RenderSettings "settings"
    {{
        rel camera = </cam>
        int2 resolution = ({RES[0]}, {RES[1]})
        int karma:global:pathtracedsamples = 4
        int karma:global:samplesperpixel = 4
    }}
}}
"""
)
usd = write(d / "scene.usda", scene)
log.note("scene for Houdini", usd)
# the config husk uses: $OCIO, else the one Houdini ships (husk sets that itself)
config = Path(
    os.environ.get("OCIO") or next((hfs() / "packages" / "ocio").glob("houdini-config*.ocio"))
)
m = re.search(r"^\s*scene_linear:\s*(.+?)\s*$", config.read_text(encoding="utf-8"), re.M)
scene_linear = m.group(1) if m else LIN
log.note("OCIO config", config)
log.note("rendering space (scene_linear)", scene_linear)
# Karma shades in scene_linear, but husk writes the image converted to Linear Rec.709
# (oiio:ColorSpace = lin_rec709) whatever scene_linear is. So a correct colour patch shows the
# red in Linear Rec.709, and a correct data patch shows the file's values taken as scene_linear,
# converted to Linear Rec.709 (the same values when scene_linear is Linear Rec.709).
want_file, raw_file = d / "expected.exr", d / "expected_data.exr"
oiio(["--colorconfig", config, src, "--colorconvert", SRGB, LIN, "-d", "float", "-o", want_file],
     log)  # fmt: skip
oiio(["--colorconfig", config, src, "-d", "float", "--colorconvert", scene_linear, LIN,
      "-o", raw_file], log)  # fmt: skip
want = [round(v, 4) for v in stats(want_file)["avg"][:3]]
RAW = [round(v, 4) for v in stats(raw_file)["avg"][:3]]
log.note("correct colour patch (written in Linear Rec.709)", want)
log.note("correct data patch (written in Linear Rec.709)", RAW)


# --- render with husk and compare every patch with the correct value -----------------------
def centre(i: int) -> tuple[int, int]:
    return int((i + 0.5) * RES[0] / len(PATCHES)), RES[1] // 2


for engine in ("cpu", "xpu"):
    out = d / f"render_{engine}.exr"
    p = husk(usd, out, log, engine, RES, ["-s", "/Render/settings"])
    if p.returncode != 0 or not out.exists():
        log.check(f"{engine} render", False, "husk failed (see above)")
        continue
    values = [[round(v, 4) for v in pixel(out, *centre(i))[:3]] for i in range(len(PATCHES))]
    log(f"\n## husk {engine} (correct = {want})")
    for i, ((_, _, what), v) in enumerate(zip(PATCHES, values, strict=True)):
        target = RAW if i in DATA else want
        log.note(f"{engine} patch {i} {what}", f"{v} {'correct' if close(v, target) else 'WRONG'}")

log.close()
