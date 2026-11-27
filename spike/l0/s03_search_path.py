"""L0 spike 3 — library-relative USD paths through PXR_AR_DEFAULT_SEARCH_PATH (spec §17.2, §17.8).

Checks: Ar resolves `model/<id>/v001/<id>.usd`; Houdini LOPs load it; the USD ROP's *Use Relative
Paths* output processor leaves it alone; husk renders it (CPU + XPU) including file-relative
textures inside the library and a library-relative DomeLight texture; a Houdini package can set
the variable.

Run with any Python 3.11:  python spike/l0/s03_search_path.py
"""

from __future__ import annotations

import json
import os
import re

from common import Log, husk, oiio, pixel, run, tool, write
from usdtext import emission_material, header, image_node, persp_camera

log = Log("s03_search_path")
d = log.dir
lib = d / "library"
proj = d / "project"
ID = "oak_k3f9q2"
SKY = "sky_p0q1r2"

# --- a tiny library, written as text the way core would --------------------------------------
ver = lib / "model" / ID / "v001"
(ver / "textures").mkdir(parents=True)
oiio(
    [
        "--pattern",
        "constant:color=1,0,0",
        "64x64",
        3,
        "-d",
        "uint8",
        "-otex",
        ver / "textures" / f"{ID}_main_bark_basecolor_v001.tx",
    ],
    log,
)
write(
    ver / f"{ID}.usd",
    header(f'    defaultPrim = "{ID}"\n')
    + f'''def Xform "{ID}" (
    kind = "component"
    assetInfo = {{string name = "{ID}"}}
    payload = @./payload_main.usd@</{ID}>
)
{{
}}
''',
)
write(ver / "payload_main.usd", header("    subLayers = [@./" + ID + "_main_geo.usd@]\n"))
write(
    ver / f"{ID}_main_geo.usd",
    header()
    + f'''def Xform "{ID}"
{{
    def Mesh "card" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {{
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)]
        texCoord2f[] primvars:st = [(0, 0), (1, 0), (1, 1), (0, 1)] (interpolation = "vertex")
        rel material:binding = </{ID}/mtl/M>
    }}
    def Scope "mtl"
    {{
{emission_material("M", image_node(f"./textures/{ID}_main_bark_basecolor_v001.tx", "sRGB - Texture"))}
    }}
}}
''',
)
sky = lib / "hdri" / SKY / "v001" / f"{SKY}_main_v001.exr"
sky.parent.mkdir(parents=True)
oiio(["--pattern", "constant:color=0,0,1", "64x32", 3, "-d", "half", "-oenv", sky], log)
write(lib / "library.json", '{"schema": 1, "name": "library"}\n')

# a shot layer inside a project that references the library by search path
shot_dir = proj / "shots" / "sh010" / "publish" / "_usd" / "lay" / "v001"
MODEL = f"model/{ID}/v001/{ID}.usd"
SKYTEX = f"hdri/{SKY}/v001/{SKY}_main_v001.exr"
shot = write(
    shot_dir / "sh010_lay_v001.usda",
    header()
    + f"""def Xform "world"
{{
    def Xform "env"
    {{
        def "oak" (
            prepend references = @{MODEL}@
        )
        {{
        }}
    }}
    def Mesh "probe"
    {{
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [(-1.05, -0.3, 0), (-0.6, -0.3, 0), (-0.6, 0.3, 0), (-1.05, 0.3, 0)]
    }}
    def DomeLight "sky"
    {{
        asset inputs:texture:file = @{SKYTEX}@ (
            colorSpace = "ACEScg"
        )
    }}
}}
"""
    + persp_camera("cam", (0, 0, 3), (0, 0, 0), 50, 36),
)

ENV = {"PXR_AR_DEFAULT_SEARCH_PATH": lib.as_posix()}
log.note("library", lib.as_posix())
log.note("shot layer", shot.as_posix())

# --- 1. Ar + composition + LOPs + USD ROP, in a child hython started with the variable ----------
CHILD = r"""
import json, os, sys
import hou
from pxr import Ar, Sdf, Usd, UsdShade
lib, shot, model, skytex, out = sys.argv[1:6]
r = {}
r["env"] = os.environ.get("PXR_AR_DEFAULT_SEARCH_PATH")
r["resolve model"] = str(Ar.GetResolver().Resolve(model))
r["resolve sky"] = str(Ar.GetResolver().Resolve(skytex))
st = Usd.Stage.Open(shot)
mesh = st.GetPrimAtPath("/world/env/oak/card")
r["stage composes model"] = mesh.IsValid()
r["unresolved"] = [str(p) for p in []]
mat = st.GetPrimAtPath("/world/env/oak/mtl/M/img")
if mat:
    a = mat.GetAttribute("inputs:file").Get()
    r["texture resolvedPath"] = a.resolvedPath
dome = st.GetPrimAtPath("/world/sky").GetAttribute("inputs:texture:file").Get()
r["dome resolvedPath"] = dome.resolvedPath

# LOPs: reference by search path, dome light with search-path texture, sublayer, then USD ROP
stage = hou.node("/stage")
ref = stage.createNode("reference::2.0")
ref.parm("primpath1").set("/world/env/oak")
ref.parm("filepath1").set(model)
dome_lop = stage.createNode("domelight::3.0")
dome_lop.setInput(0, ref)
dome_lop.parm("xn__inputstexturefile_r3ah").set(skytex)
ref2 = stage.createNode("reference::2.0")
ref2.setInput(0, dome_lop)
ref2.parm("primpath1").set("/world/env/oak_env")
ref2.parm("filepath1").set("$SW_LIBRARY/" + model)
rop = stage.createNode("usd_rop")
rop.setInput(0, ref2)
rop.parm("lopoutput").set(out)
rop.parm("enableoutputprocessor_simplerelativepaths").set(1)
r["lop composes model"] = bool(ref.stage()) and ref.stage().GetPrimAtPath("/world/env/oak/card").IsValid()
r["lop errors"] = list(ref.errors()) + list(ref2.errors())
rop.render()
r["rop errors"] = list(rop.errors())
text = open(out).read() if os.path.exists(out) else ""
r["written"] = [l.strip() for l in text.splitlines() if "@" in l]
print("RESULT" + json.dumps(r))
"""
child = write(d / "_child.py", CHILD)
out_layer = proj / "shots" / "sh010" / "publish" / "_usd" / "lgt" / "v001" / "sh010_lgt_v001.usda"


def child_run(env: dict) -> dict:
    p = run(
        [
            tool("hython"),
            child,
            lib.as_posix(),
            shot.as_posix(),
            MODEL,
            SKYTEX,
            out_layer.as_posix(),
        ],
        log,
        env=env,
    )
    m = re.search(r"RESULT(.+)", p.stdout)
    return json.loads(m.group(1)) if m else {"failed": p.stderr[-2000:]}


log("\n## hython with PXR_AR_DEFAULT_SEARCH_PATH and SW_LIBRARY set")
r = child_run({**ENV, "SW_LIBRARY": lib.as_posix()})
log.check(
    "Ar resolves model/<id>/v001/<id>.usd",
    lib.as_posix() in r.get("resolve model", "").replace("\\", "/"),
    r.get("resolve model"),
)
log.check(
    "Ar resolves hdri/.../x.exr (non-USD asset)",
    r.get("resolve sky", "") != "",
    r.get("resolve sky"),
)
log.check("Usd.Stage composes the referenced model", r.get("stage composes model"))
log.check(
    "file-relative texture inside the library resolves",
    bool(r.get("texture resolvedPath")),
    r.get("texture resolvedPath"),
)
log.check(
    "DomeLight texture by search path resolves",
    bool(r.get("dome resolvedPath")),
    r.get("dome resolvedPath"),
)
log.check(
    "Reference LOP loads the search-path file", r.get("lop composes model"), r.get("lop errors")
)
written = r.get("written", [])
log.block("USD ROP output (lines with asset paths), Use Relative Paths on", "\n".join(written))
log.check("ROP keeps the reference library-relative", any(f"@{MODEL}@" in ln for ln in written), "")
log.check(
    "ROP keeps the DomeLight texture library-relative",
    any(f"@{SKYTEX}@" in ln for ln in written),
    "",
)
envline = [ln for ln in written if "oak_env" in ln or ("../" in ln and ID in ln)]
log.note(
    "what $SW_LIBRARY/... becomes after the ROP",
    envline or [ln for ln in written if ID in ln and MODEL not in ln],
)

log("\n## hython without the variable (control)")
r0 = child_run({"PXR_AR_DEFAULT_SEARCH_PATH": ""})
log.check(
    "without it the model does not compose (proves the search path is what works)",
    not r0.get("stage composes model"),
    r0.get("resolve model"),
)

# --- 2. husk renders --------------------------------------------------------------------------------
log("\n## husk (search path for the reference, the model's own textures and the dome)")
for engine in ("cpu", "xpu"):
    for label, env in (("with", ENV), ("without", {"PXR_AR_DEFAULT_SEARCH_PATH": ""})):
        img = d / f"render_{engine}_{label}.exr"
        husk(shot, img, log, engine, (32, 32), ["-p", "8", "-c", "/cam"], env=env)
        if not img.exists():
            log.check(f"{engine} {label}: rendered", False)
            continue
        centre, corner = pixel(img, 16, 16), pixel(img, 4, 16)  # corner = grey diffuse probe
        if label == "with":
            log.check(
                f"{engine}: model with library texture (red) in the centre",
                centre[0] > 0.5 and centre[2] < 0.2,
                centre,
            )
            log.check(
                f"{engine}: dome texture by search path lights the probe blue",
                corner[2] > 0.2 and corner[0] < 0.05,
                corner,
            )
        else:
            log.note(f"{engine} without the variable: centre / corner", f"{centre} / {corner}")

# --- 3. a Houdini package that sets SW_LIBRARY and the search path -------------------------------
log("\n## Houdini package")
pkg_dir = d / "packages"
write(
    pkg_dir / "sw_spike.json",
    json.dumps(
        {
            "env": [
                {"SW_LIBRARY": lib.as_posix()},
                {"PXR_AR_DEFAULT_SEARCH_PATH": {"value": "$SW_LIBRARY", "method": "prepend"}},
            ]
        },
        indent=2,
    ),
)
PKG = (
    "import os, json\nfrom pxr import Ar\n"
    "print('RESULT' + json.dumps({'SW_LIBRARY': os.environ.get('SW_LIBRARY'),"
    " 'PXR': os.environ.get('PXR_AR_DEFAULT_SEARCH_PATH'),"
    f" 'resolve': str(Ar.GetResolver().Resolve('{MODEL}'))}}))\n"
)
pkg_child = write(d / "_pkg_child.py", PKG)
for label, pre in (("unset before", None), ("set before", "/some/other/path")):
    env = {"HOUDINI_PACKAGE_DIR": pkg_dir.as_posix()}
    if pre:
        env["PXR_AR_DEFAULT_SEARCH_PATH"] = pre
    p = run([tool("hython"), pkg_child], log, env=env)
    m = re.search(r"RESULT(.+)", p.stdout)
    res = json.loads(m.group(1)) if m else {"failed": p.stderr[-500:]}
    log.note(f"package, variable {label}", res)
    log.check(f"  ... resolves the model ({label})", lib.name in res.get("resolve", ""))
log.note("os.pathsep", os.pathsep)
log("Note: if the 'set before' value lost /some/other/path, a package 'prepend' replaces an")
log("existing OS value instead of prepending to it.")

log.close()
