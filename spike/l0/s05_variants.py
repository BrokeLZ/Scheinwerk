"""L0 spike 5 — a library component whose `variant` set switches payloads across version folders
(spec §17.3), referenced by search path, as PointInstancer prototypes and as native instances.

Run in hython:  hython spike/l0/s05_variants.py
"""

from __future__ import annotations

import hou
from pxr import Ar, Sdf, Usd, UsdGeom

from common import Log, husk, pixel, write
from usdtext import header, persp_camera

log = Log("s05_variants")
d = log.dir
lib = d / "library"
ID = "oak_k3f9q2"
item = lib / "model" / ID


def geo_layer(var: str, height: float, model_variants: bool) -> str:
    """geo layer of one variant: /<id>/geo/render/trunk, optional `model` variant set."""
    trunk = f"""            def Mesh "trunk"
            {{
                int[] faceVertexCounts = [4]
                int[] faceVertexIndices = [0, 1, 2, 3]
                point3f[] points = [(-0.3, 0, 0), (0.3, 0, 0), (0.3, {height}, 0), (-0.3, {height}, 0)]
            }}"""
    vset = ""
    if model_variants:
        vset = """    variants = {
        string model = "full"
    }
    prepend variantSets = "model"
"""
        body = f"""    variantSet "model" = {{
        "full" {{
            def Scope "geo"
            {{
                def Scope "render"
                {{
{trunk}
                }}
            }}
        }}
        "lite" {{
            def Scope "geo"
            {{
                def Scope "render"
                {{
                    def Mesh "lite_card"
                    {{
                        int[] faceVertexCounts = [3]
                        int[] faceVertexIndices = [0, 1, 2]
                        point3f[] points = [(-0.3, 0, 0), (0.3, 0, 0), (0, {height}, 0)]
                    }}
                }}
            }}
        }}
    }}
"""
        return (
            header(f'    defaultPrim = "{ID}"\n') + f'def Xform "{ID}" (\n{vset})\n{{\n{body}}}\n'
        )
    return (
        header(f'    defaultPrim = "{ID}"\n')
        + f'''def Xform "{ID}"
{{
    def Scope "geo"
    {{
        def Scope "render"
        {{
{trunk}
        }}
    }}
}}
'''
    )


def mtl_layer(var: str, rgb: tuple) -> str:
    return (
        header(f'    defaultPrim = "{ID}"\n')
        + f'''over "{ID}"
{{
    over "geo" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {{
        rel material:binding = </{ID}/mtl/{var}>
    }}
    def Scope "mtl"
    {{
        def Material "{var}"
        {{
            token outputs:mtlx:surface.connect = </{ID}/mtl/{var}/surf.outputs:out>
            def Shader "surf"
            {{
                uniform token info:id = "ND_standard_surface_surfaceshader"
                float inputs:base = 0
                float inputs:specular = 0
                float inputs:emission = 1
                color3f inputs:emission_color = {rgb}
                token outputs:out
            }}
        }}
    }}
}}
'''
    )


def payload(var: str) -> str:
    return header(
        f"    subLayers = [\n        @./{ID}_{var}_mtl.usd@,\n        @./{ID}_{var}_geo.usd@\n    ]\n"
    )


def component(variants: dict[str, str]) -> str:
    """{id}.usd: kind, assetInfo, variant set `variant` whose variants are payloads."""
    body = "\n".join(
        f'        "{v}" (\n            prepend payload = @{p}@</{ID}>\n        ) {{\n        }}'
        for v, p in variants.items()
    )
    return (
        header(f'    defaultPrim = "{ID}"\n')
        + f'''def Xform "{ID}" (
    kind = "component"
    assetInfo = {{string name = "{ID}"}}
    variants = {{
        string variant = "main"
    }}
    prepend variantSets = "variant"
)
{{
    variantSet "variant" = {{
{body}
    }}
}}
'''
    )


# v001: main.  v002: adds winter, keeps main from v001 (not copied)
v1, v2 = item / "v001", item / "v002"
write(v1 / f"{ID}_main_geo.usd", geo_layer("main", 1.0, model_variants=True))
write(v1 / f"{ID}_main_mtl.usd", mtl_layer("main", (0, 1, 0)))
write(v1 / "payload_main.usd", payload("main"))
write(v1 / f"{ID}.usd", component({"main": "./payload_main.usd"}))
write(v2 / f"{ID}_winter_geo.usd", geo_layer("winter", 2.0, model_variants=False))
write(v2 / f"{ID}_winter_mtl.usd", mtl_layer("winter", (1, 1, 1)))
write(v2 / "payload_winter.usd", payload("winter"))
write(
    v2 / f"{ID}.usd",
    component({"main": "../v001/payload_main.usd", "winter": "./payload_winter.usd"}),
)
log.block("v002 component", (v2 / f"{ID}.usd").read_text())

Ar.DefaultResolver.SetDefaultSearchPath([lib.as_posix()])
REF = f"model/{ID}/v002/{ID}.usd"
P = f"/{ID}"

# --- 1. the component itself -------------------------------------------------------------------
log("\n## The component, opened directly")
st = Usd.Stage.Open(str(v2 / f"{ID}.usd"))
prim = st.GetPrimAtPath(P)
vs = prim.GetVariantSets()
log.check(
    "variant set `variant` with main + winter",
    vs.GetVariantSet("variant").GetVariantNames() == ["main", "winter"],
    vs.GetVariantSet("variant").GetVariantNames(),
)
log.check("default main: trunk from v001", st.GetPrimAtPath(f"{P}/geo/render/trunk").IsValid())
layers = [lyr.identifier.replace("\\", "/").split("/model/")[-1] for lyr in st.GetUsedLayers()]
log.note("layers used with main", sorted(layers))
log.check(
    "nested `model` variant set (authored in the project) visible inside main",
    "model" in prim.GetVariantSets().GetNames(),
    prim.GetVariantSets().GetNames(),
)
with Usd.EditContext(st, st.GetSessionLayer()):  # never edit the library layer in memory
    vs.GetVariantSet("variant").SetVariantSelection("winter")
pts = UsdGeom.Mesh(st.GetPrimAtPath(f"{P}/geo/render/trunk")).GetPointsAttr().Get()
log.check("winter: trunk from v002 (height 2)", pts is not None and max(p[1] for p in pts) == 2.0)
log.check(
    "winter has no `model` set",
    "model" not in prim.GetVariantSets().GetNames(),
    prim.GetVariantSets().GetNames(),
)
kind = Usd.ModelAPI(prim).GetKind()
log.check("kind stays component", kind == "component", kind)

log("\n## Unloaded payloads")
st = Usd.Stage.Open(str(v2 / f"{ID}.usd"), Usd.Stage.LoadNone)
prim = st.GetPrimAtPath(P)
log.check(
    "`variant` choices visible with the payload unloaded",
    prim.GetVariantSets().GetVariantSet("variant").GetVariantNames() == ["main", "winter"],
)
log.note("variant sets visible unloaded", prim.GetVariantSets().GetNames())
log.check("geometry not loaded", not st.GetPrimAtPath(f"{P}/geo").IsValid())

# --- 2. referenced from a shot, variant chosen on the referencing prim ------------------------------
log("\n## From a shot (library-relative reference, selection on the referencing prim)")
shot = (
    d / "project" / "shots" / "sh010" / "publish" / "_usd" / "lay" / "v001" / "sh010_lay_v001.usda"
)
inst_points = "[(-1.5, 0, 0), (-0.5, 0, 0), (0.5, 0, 0), (1.5, 0, 0)]"
write(
    shot,
    header()
    + f"""def Xform "world"
{{
    def Xform "env"
    {{
        def "oak_01" (
            prepend references = @{REF}@
            variants = {{
                string variant = "winter"
            }}
        )
        {{
        }}
        def "oak_02" (
            prepend references = @{REF}@
        )
        {{
        }}
        def "oak_lite" (
            prepend references = @{REF}@
            variants = {{
                string model = "lite"
            }}
        )
        {{
        }}
        def PointInstancer "forest"
        {{
            point3f[] positions = {inst_points}
            int[] protoIndices = [0, 1, 0, 1]
            rel prototypes = [</world/env/forest/protos/main>, </world/env/forest/protos/winter>]
            def Scope "protos"
            {{
                def "main" (
                    prepend references = @{REF}@
                )
                {{
                }}
                def "winter" (
                    prepend references = @{REF}@
                    variants = {{
                        string variant = "winter"
                    }}
                )
                {{
                }}
            }}
        }}
        def "inst_a" (
            instanceable = true
            prepend references = @{REF}@
        )
        {{
        }}
        def "inst_b" (
            instanceable = true
            prepend references = @{REF}@
            variants = {{
                string variant = "winter"
            }}
        )
        {{
        }}
        def "inst_c" (
            instanceable = true
            prepend references = @{REF}@
            variants = {{
                string variant = "winter"
            }}
        )
        {{
        }}
    }}
}}
"""
    + persp_camera("cam", (0, 1, 6), (0, 0, 0), 35, 36),
)
st = Usd.Stage.Open(str(shot))


def height(path: str) -> float | None:
    p = st.GetPrimAtPath(path)
    if not p.IsValid():
        return None
    return max(v[1] for v in UsdGeom.Mesh(p).GetPointsAttr().Get())


log.check(
    "oak_01 (winter selected in the shot) gets v002 geometry",
    height("/world/env/oak_01/geo/render/trunk") == 2.0,
)
log.check(
    "oak_02 (no selection) gets main from v001", height("/world/env/oak_02/geo/render/trunk") == 1.0
)
log.check(
    "a nested `model` selection in the shot works through the variant payload",
    st.GetPrimAtPath("/world/env/oak_lite/geo/render/lite_card").IsValid(),
)
log.check(
    "PointInstancer prototype main", height("/world/env/forest/protos/main/geo/render/trunk") == 1.0
)
log.check(
    "PointInstancer prototype winter",
    height("/world/env/forest/protos/winter/geo/render/trunk") == 2.0,
)
protos = st.GetPrototypes()
log.check(
    "native instancing: different selections give different prototypes (2 expected)",
    len(protos) == 2,
    [str(p.GetPath()) for p in protos],
)
log.note(
    "Sdf variant selection is per prim, so instances sharing a selection share a prototype", ""
)

# --- 3. husk ------------------------------------------------------------------------------------------
log("\n## husk render of the PointInstancer (main green, winter white)")
inst_only = write(
    d / "instancer_only.usda",
    header(f"    subLayers = [@{shot.as_posix()}@]\n")
    + """
over "world"
{
    over "env"
    {
        over "oak_01" (
            active = false
        )
        {
        }
        over "oak_02" (
            active = false
        )
        {
        }
        over "oak_lite" (
            active = false
        )
        {
        }
        over "inst_a" (
            active = false
        )
        {
        }
        over "inst_b" (
            active = false
        )
        {
        }
        over "inst_c" (
            active = false
        )
        {
        }
    }
}
""",
)
env = {"PXR_AR_DEFAULT_SEARCH_PATH": lib.as_posix()}
for engine in ("cpu", "xpu"):
    img = d / f"instancer_{engine}.exr"
    husk(inst_only, img, log, engine, (64, 64), ["-p", "4", "-c", "/cam"], env=env)
    if img.exists():
        # 64 px over 6.17 units at z=6: x=-1.5,-0.5,0.5,1.5 -> columns 16,27,37,48; y=0.5 -> row 37
        cols = [pixel(img, x, 37) for x in (16, 27, 37, 48)]
        log.note(f"{engine} instances left to right (low row)", cols)
        hi = [pixel(img, x, 26) for x in (16, 27, 37, 48)]  # y=1.6
        ok = (
            cols[0][1] > 0.5
            and cols[0][0] < 0.2
            and cols[1][0] > 0.5
            and cols[2][0] < 0.2
            and cols[3][0] > 0.5
        )
        log.check(f"{engine}: green, white, green, white", ok)
        log.note(f"{engine} high row (only winter trunks are tall)", hi)

# --- 4. Houdini: variant menus on LOPs --------------------------------------------------------------
log("\n## Houdini LOPs")
hou.hscript(f"setenv PXR_AR_DEFAULT_SEARCH_PATH = {lib.as_posix()}")
ref = hou.node("/stage").createNode("reference::2.0")
ref.parm("primpath1").set("/world/env/oak_01")
ref.parm("filepath1").set(REF)
sv = hou.node("/stage").createNode("setvariant")
sv.setInput(0, ref)
sv.parm("primpattern1").set("/world/env/oak_01")
names = [p.name() for p in sv.parms()]
vset_parm = sv.parm("variantset1")
vname_parm = sv.parm("variantname1")
log.note("setvariant parms", [n for n in names if "variant" in n][:8])
if vset_parm and vname_parm:
    vset_parm.set("variant")
    log.note("variant set menu", list(vset_parm.menuItems()))
    log.note("variant name menu", list(vname_parm.menuItems()))
    vname_parm.set("winter")
    s = sv.stage()
    log.check(
        "Set Variant LOP switches to winter (geometry from v002)",
        s.GetPrimAtPath("/world/env/oak_01/geo/render/trunk").IsValid()
        and max(
            v[1]
            for v in UsdGeom.Mesh(s.GetPrimAtPath("/world/env/oak_01/geo/render/trunk"))
            .GetPointsAttr()
            .Get()
        )
        == 2.0,
    )
log.note(
    "Sdf layer of v002 component has no absolute paths",
    "/Users" not in (v2 / f"{ID}.usd").read_text() and ":\\" not in (v2 / f"{ID}.usd").read_text(),
)
_ = Sdf
log.close()
