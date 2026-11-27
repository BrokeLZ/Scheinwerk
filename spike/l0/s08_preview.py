"""L0 spike 8 — preview scene format and Karma preview renders (spec §17.7).

Proposal tested here: the preview scenes are plain .usda files shipped with Scheinwerk
(lights + render settings). For each preview a small wrapper layer sublayers the scene and adds
the item (model: reference + variant selection; texture set: a MaterialX material written as text
on a shader ball) and a camera that frames the bounds. husk renders it; hoiiotool applies the OCIO
display view and writes the JPEG.

Run in hython:  hython spike/l0/s08_preview.py
"""

from __future__ import annotations

import math
import time

import hou
from pxr import Usd, UsdGeom

from common import Log, husk, info, oiio, write
from usdtext import header

log = Log("s08_preview")
d = log.dir
lib = d / "library"
ID = "oak_k3f9q2"
SET = "rusty_metal_x7y8z9"

# --- the shipped scene (text) -------------------------------------------------------------------
STUDIO = (
    header()
    + """def Xform "preview"
{
    def DomeLight "env"
    {
        float inputs:intensity = 1.0
        color3f inputs:color = (0.8, 0.85, 1.0)
    }
    def DistantLight "key"
    {
        float inputs:intensity = 6
        float inputs:angle = 8
        float3 xformOp:rotateXYZ = (-40, 35, 0)
        uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
    }
    def DistantLight "rim"
    {
        float inputs:intensity = 3
        float3 xformOp:rotateXYZ = (-20, 200, 0)
        uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
    }
}

def Scope "Render"
{
    def RenderSettings "settings"
    {
        rel camera = </preview/cam>
        int2 resolution = (512, 512)
        int karma:global:pathtracedsamples = 32
        int karma:global:samplesperpixel = 32
    }
}
"""
)
scene = write(d / "resources" / "preview_studio.usda", STUDIO)
log.note("shipped scene", f"{scene.name}: {len(STUDIO)} bytes of text")

# --- a model item (tall trunk + crown, two variants) -------------------------------------------
ver = lib / "model" / ID / "v001"


def box(name: str, lo, hi, rgb) -> str:
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    p = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    f = [0, 3, 2, 1, 4, 5, 6, 7, 0, 1, 5, 4, 2, 3, 7, 6, 1, 2, 6, 5, 0, 4, 7, 3]
    return f'''            def Mesh "{name}"
            {{
                int[] faceVertexCounts = [4, 4, 4, 4, 4, 4]
                int[] faceVertexIndices = {f}
                point3f[] points = {p}
                color3f[] primvars:displayColor = [{rgb}]
                uniform token subdivisionScheme = "none"
            }}'''


for var, crown in (("main", "(0.1, 0.5, 0.1)"), ("winter", "(0.9, 0.9, 0.95)")):
    write(
        ver / f"{ID}_{var}_geo.usd",
        header(f'    defaultPrim = "{ID}"\n')
        + f'''def Xform "{ID}"
{{
    def Scope "geo"
    {{
        def Scope "render"
        {{
{box("trunk", (-0.15, 0, -0.15), (0.15, 3, 0.15), "(0.35, 0.2, 0.1)")}
{box("crown", (-1.2, 2.5, -1.2), (1.2, 5.5, 1.2), crown)}
        }}
    }}
}}
''',
    )
    write(ver / f"payload_{var}.usd", header(f"    subLayers = [@./{ID}_{var}_geo.usd@]\n"))
write(
    ver / f"{ID}.usd",
    header(f'    defaultPrim = "{ID}"\n')
    + f'''def Xform "{ID}" (
    kind = "component"
    variants = {{
        string variant = "main"
    }}
    prepend variantSets = "variant"
)
{{
    variantSet "variant" = {{
        "main" (
            prepend payload = @./payload_main.usd@</{ID}>
        ) {{
        }}
        "winter" (
            prepend payload = @./payload_winter.usd@</{ID}>
        ) {{
        }}
    }}
}}
''',
)


def frame_camera(
    stage: Usd.Stage, prim: str, fov_deg: float = 30.0, yaw: float = 35, pitch: float = -15
) -> str:
    """A camera looking at the bounds from a 3/4 view, far enough to fit the bounding sphere."""
    rng = (
        UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
        .ComputeWorldBound(stage.GetPrimAtPath(prim))
        .ComputeAlignedRange()
    )
    c, size = rng.GetMidpoint(), rng.GetSize()
    radius = 0.5 * math.sqrt(sum(s * s for s in size))
    dist = radius / math.sin(math.radians(fov_deg / 2)) * 1.05
    yw, pt = math.radians(yaw), math.radians(pitch)
    pos = (
        c[0] + dist * math.sin(yw) * math.cos(pt),
        c[1] - dist * math.sin(pt),
        c[2] + dist * math.cos(yw) * math.cos(pt),
    )
    aperture = 36.0
    focal = aperture / (2 * math.tan(math.radians(fov_deg / 2)))
    return f"""    def Camera "cam"
    {{
        float focalLength = {focal:.4f}
        float horizontalAperture = {aperture}
        float verticalAperture = {aperture}
        float2 clippingRange = ({max(0.01, dist - radius * 2):.4f}, {dist + radius * 2:.4f})
        double3 xformOp:translate = ({pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f})
        float3 xformOp:rotateXYZ = ({pitch}, {yaw}, 0)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
    }}
"""


def to_jpeg(exr, jpg, size: str) -> bool:
    p = oiio(
        [
            exr,
            "--ch",
            "R,G,B,A",
            "--colorconvert",
            "Linear Rec.709 (sRGB)",
            "ACEScg",
            "--ociodisplay:from=ACEScg",
            "sRGB - Display",
            "ACES 1.0 - SDR Video",
            # over a mid-grey card, so thumbnails of objects aren't on black
            "--pattern",
            "constant:color=0.18,0.18,0.18,1",
            size,
            4,
            "--over",
            "--ch",
            "R,G,B",
            "-d",
            "uint8",
            "-o",
            jpg,
        ],
        log,
    )
    return p.returncode == 0 and jpg.exists()


# --- model previews -------------------------------------------------------------------------------
log("## Model previews (hython: bounds -> camera; husk renders)")
env = {"PXR_AR_DEFAULT_SEARCH_PATH": lib.as_posix()}
from pxr import Ar  # noqa: E402

Ar.DefaultResolver.SetDefaultSearchPath([lib.as_posix()])
for var in ("main", "winter"):
    wrapper_dir = d / "jobs"
    body = (
        header(f"    subLayers = [@{scene.as_posix()}@]\n")
        + f'''over "preview"
{{
    def "item" (
        prepend references = @model/{ID}/v001/{ID}.usd@
        variants = {{
            string variant = "{var}"
        }}
    )
    {{
    }}
'''
    )
    wrapper = write(wrapper_dir / f"preview_{ID}_{var}.usda", body + "}\n")
    t = time.time()
    st = Usd.Stage.Open(wrapper.as_posix())
    cam = frame_camera(st, "/preview/item")
    write(wrapper, body + cam + "}\n")
    log.note(f"{var}: bounds + camera in hython", f"{time.time() - t:.2f}s")
    for engine in ("cpu", "xpu"):
        exr = d / f"thumb_{var}_{engine}.exr"
        p = husk(wrapper, exr, log, engine, (512, 512), ["-s", "/Render/settings"], env=env)
        jpg = d / f"thumb_{var}_{engine}.jpg"
        ok = exr.exists() and to_jpeg(exr, jpg, "512x512")
        log.check(
            f"{var} [{engine}] 512x512 rendered in {getattr(p, 'seconds', '?')}s",
            ok,
            info(jpg).splitlines()[0] if ok else "",
        )

# --- texture set: shader ball with a MaterialX material written as text ------------------------------
log("\n## Texture set preview (material as text, shader ball)")
tex = lib / "texture_set" / SET / "v001" / "textures"
tex.mkdir(parents=True)
oiio(
    [
        "--pattern",
        "checker:width=32:height=32:color1=0.6,0.25,0.1:color2=0.3,0.3,0.32",
        "512x512",
        3,
        "-d",
        "half",
        "-otex",
        tex / f"{SET}_main_basecolor_v001.exr",
    ],
    log,
)
oiio(
    [
        "--pattern",
        "noise:type=uniform:min=0.3:max=0.8",
        "512x512",
        1,
        "-d",
        "uint8",
        "-otex",
        tex / f"{SET}_main_roughness_v001.tx",
    ],
    log,
)
oiio(
    [
        "--pattern",
        "checker:width=32:height=32:color1=1:color2=0",
        "512x512",
        1,
        "-d",
        "uint8",
        "-otex",
        tex / f"{SET}_main_metalness_v001.tx",
    ],
    log,
)
oiio(
    [
        "--pattern",
        "constant:color=0.5,0.5,1",
        "64x64",
        3,
        "-d",
        "uint8",
        "-otex",
        tex / f"{SET}_main_normal_v001.tx",
    ],
    log,
)

ball = d / "resources" / "shaderball.usd"
try:
    geo = hou.node("/obj").createNode("geo")
    sb = geo.createNode("testgeometry_shaderball::2.0")
    lop = hou.node("/stage").createNode("sopimport")
    lop.parm("soppath").set(sb.path())
    lop.parm("primpath").set("/preview/ball")
    rop = hou.node("/stage").createNode("usd_rop")
    rop.setInput(0, lop)
    rop.parm("lopoutput").set(ball.as_posix())
    rop.parm("savestyle").set("flattenstage")
    # note: SOP Import ignores primpath here; the prims come out under /shaderball
    rop.render()
    log.note(
        "shader ball exported from 'Test Geometry: Shader Ball'",
        f"{ball.stat().st_size // 1024} KB (usd)",
    )
except Exception as e:  # noqa: BLE001
    log.check("shader ball export", False, str(e)[:300])

size_m = 2.0
BALL_REF = ball.as_posix()


def img(name: str, role: str, typ: str, cs: str) -> str:
    ext = "exr" if role == "basecolor" else "tx"
    return f'''        def Shader "{name}"
        {{
            uniform token info:id = "ND_image_{typ}"
            asset inputs:file = @{SET}_main_{role}_v001.{ext}@ (
                colorSpace = "{cs}"
            )
            float2 inputs:texcoord.connect = </preview/mtl/set/uv.outputs:out>
            {"color3f" if typ == "color3" else ("float3" if typ == "vector3" else "float")} outputs:out
        }}'''


MAT = f"""over "preview"
{{
    def Scope "mtl"
    {{
        def Material "set"
        {{
            token outputs:mtlx:surface.connect = </preview/mtl/set/surf.outputs:out>
            def Shader "st"
            {{
                uniform token info:id = "ND_texcoord_vector2"
                float2 outputs:out
            }}
            def Shader "uv"
            {{
                uniform token info:id = "ND_multiply_vector2FA"
                float2 inputs:in1.connect = </preview/mtl/set/st.outputs:out>
                float inputs:in2 = {1.0 / size_m}
                float2 outputs:out
            }}
{img("bc", "basecolor", "color3", "ACEScg")}
{img("rough", "roughness", "float", "raw")}
{img("metal", "metalness", "float", "raw")}
{img("nrm", "normal", "vector3", "raw")}
            def Shader "nmap"
            {{
                uniform token info:id = "ND_normalmap_float"
                float3 inputs:in.connect = </preview/mtl/set/nrm.outputs:out>
                float3 outputs:out
            }}
            def Shader "surf"
            {{
                uniform token info:id = "ND_standard_surface_surfaceshader"
                color3f inputs:base_color.connect = </preview/mtl/set/bc.outputs:out>
                float inputs:specular_roughness.connect = </preview/mtl/set/rough.outputs:out>
                float inputs:metalness.connect = </preview/mtl/set/metal.outputs:out>
                float3 inputs:normal.connect = </preview/mtl/set/nmap.outputs:out>
                token outputs:out
            }}
        }}
    }}
    def "ball" (
        prepend apiSchemas = ["MaterialBindingAPI"]
        prepend references = @{BALL_REF}@</shaderball>
    )
    {{
        rel material:binding = </preview/mtl/set>
    }}
"""
if ball.exists():
    job = d / "jobs" / f"preview_{SET}_main.usda"
    body = header(f"    subLayers = [@{scene.as_posix()}@]\n") + MAT
    # textures resolve file-relative to the layer that authors them: write the wrapper next to them
    job = write(tex / "_preview_job.usda", body + "}\n")
    st = Usd.Stage.Open(job.as_posix())
    write(job, body + frame_camera(st, "/preview/ball", 30, 30, -20) + "}\n")
    for engine in ("cpu", "xpu"):
        exr = d / f"thumb_{SET}_{engine}.exr"
        p = husk(job, exr, log, engine, (512, 512), ["-s", "/Render/settings"])
        jpg = d / f"thumb_{SET}_{engine}.jpg"
        ok = exr.exists() and to_jpeg(exr, jpg, "512x512")
        log.check(f"texture set [{engine}] 512x512 in {getattr(p, 'seconds', '?')}s", ok)
    job.unlink()
    log("Note: the material's file paths are relative to the layer that authors them, so a")
    log("generated wrapper must either sit in the version folder (temporarily) or write")
    log("library-relative paths (resolved through the search path).")

log.close()
