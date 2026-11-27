"""L0 spike 7 — headless hython: fbx / gltf / glb / obj / abc -> USD (spec §17.6, external models).

Makes small test files (a textured box) with Houdini's own exporters and a hand-written glTF,
then tries the import routes: USD file-format plugins (Usd.Stage.Open on the file), LOPs + USD
ROP, and SOP loaders. Reports meshes, materials, texture paths, units, up axis and timings.

Run in hython:  hython spike/l0/s07_model_import.py
"""

from __future__ import annotations

import base64
import json
import struct
import time

import hou
from pxr import Sdf, Usd, UsdGeom, UsdShade

from common import Log, oiio, write

log = Log("s07_model_import")
d = log.dir
src = d / "src"
src.mkdir()
oiio(
    [
        "--pattern",
        "checker:color1=1,0,0:color2=1,1,1",
        "64x64",
        3,
        "-d",
        "uint8",
        "-o",
        src / "box_basecolor.png",
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
        "-o",
        src / "box_normal.png",
    ],
    log,
)

# --- 1. sources -----------------------------------------------------------------------------------
log("## Sources")
obj = hou.node("/obj").createNode("geo", "model")
box = obj.createNode("box")
box.parm("sizex").set(2)  # 2 m wide
uv = obj.createNode("uvproject")
uv.setInput(0, box)
matnet = hou.node("/mat")
shader = matnet.createNode("principledshader::2.0", "bark")
shader.parm("basecolor_useTexture").set(1)
shader.parm("basecolor_texture").set((src / "box_basecolor.png").as_posix())
mat = obj.createNode("material")
mat.setInput(0, uv)
mat.parm("shop_materialpath1").set(shader.path())
mat.setDisplayFlag(True)
mat.setRenderFlag(True)


def export(rop_type: str, parm: str, path, extra: dict | None = None) -> bool:
    try:
        rop = hou.node("/out").createNode(rop_type)
        for k, v in {**(extra or {}), parm: path.as_posix()}.items():
            if rop.parm(k) is not None:
                rop.parm(k).set(v)
        rop.render()
        return path.exists()
    except hou.Error as e:
        log.check(f"export {path.name}", False, str(e)[:300])
        return False


log.check(
    "fbx via ROP FBX",
    export("filmboxfbx", "sopoutput", src / "box.fbx", {"startnode": obj.path(), "exportkind": 0}),
)
log.check(
    "gltf via ROP glTF",
    export("gltf", "file", src / "box_rop.gltf", {"objpath": obj.path(), "usesoppath": 0}),
)
log.check(
    "glb via ROP glTF",
    export("gltf", "file", src / "box_rop.glb", {"objpath": obj.path(), "usesoppath": 0}),
)
log.check(
    "abc via ROP Alembic",
    export("alembic", "filename", src / "box.abc", {"root": "/obj", "objects": obj.path()}),
)
geo = mat.geometry()
try:
    geo.saveToFile((src / "box.obj").as_posix())
    log.check("obj via hou.Geometry.saveToFile", (src / "box.obj").exists())
except hou.Error as e:
    log.check("obj via hou.Geometry.saveToFile", False, e)


def hand_gltf(path) -> None:
    """Minimal glTF 2.0: one quad, UVs, a material with basecolor + normal texture (Y-up, m)."""
    pos = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    idx = [0, 2, 1, 0, 3, 2]
    blob = (
        b"".join(struct.pack("<3f", *p) for p in pos)
        + b"".join(struct.pack("<2f", *t) for t in uvs)
        + b"".join(struct.pack("<H", i) for i in idx)
    )
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "leaf_card"}],
        "meshes": [
            {
                "name": "leaf_card",
                "primitives": [
                    {"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 2, "material": 0}
                ],
            }
        ],
        "materials": [
            {
                "name": "leaf_mat",
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0,
                    "roughnessFactor": 0.6,
                },
                "normalTexture": {"index": 1},
            }
        ],
        "textures": [{"source": 0}, {"source": 1}],
        "images": [{"uri": "box_basecolor.png"}, {"uri": "box_normal.png"}],
        "buffers": [
            {
                "byteLength": len(blob),
                "uri": "data:application/octet-stream;base64," + base64.b64encode(blob).decode(),
            }
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 48},
            {"buffer": 0, "byteOffset": 48, "byteLength": 32},
            {"buffer": 0, "byteOffset": 80, "byteLength": 12},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 4,
                "type": "VEC3",
                "min": [-1, 0, -1],
                "max": [1, 0, 1],
            },
            {"bufferView": 1, "componentType": 5126, "count": 4, "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": 6, "type": "SCALAR"},
        ],
    }
    write(path, json.dumps(doc, indent=1))


hand_gltf(src / "card_hand.gltf")
log.note("hand-written glTF", "card_hand.gltf (quad, basecolor + normal texture)")
log.note("source files", sorted(p.name for p in src.iterdir()))


# --- 2. route A: USD file-format plugins -------------------------------------------------------------
def describe(stage: Usd.Stage) -> dict:
    meshes = [p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
    mats = [p for p in stage.Traverse() if p.IsA(UsdShade.Material)]
    assets = set()
    for p in stage.Traverse():
        for a in p.GetAttributes():
            v = a.Get()
            if isinstance(v, Sdf.AssetPath) and v.path:
                assets.add(v.path)
    shaders = {
        str(UsdShade.Shader(p).GetIdAttr().Get())
        for p in stage.Traverse()
        if p.IsA(UsdShade.Shader)
    }
    bound = sum(1 for m in meshes if UsdShade.MaterialBindingAPI(m).ComputeBoundMaterial()[0])
    bbox = (
        UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
        .ComputeWorldBound(stage.GetPseudoRoot())
        .ComputeAlignedRange()
    )
    return {
        "meshes": len(meshes),
        "mesh paths": [str(m.GetPath()) for m in meshes][:4],
        "materials": [str(m.GetPath()) for m in mats][:4],
        "bound meshes": bound,
        "shader ids": sorted(shaders)[:8],
        "asset paths": sorted(assets)[:6],
        "upAxis": UsdGeom.GetStageUpAxis(stage),
        "metersPerUnit": UsdGeom.GetStageMetersPerUnit(stage),
        "metersPerUnit authored": stage.HasAuthoredMetadata("metersPerUnit"),
        "upAxis authored": stage.HasAuthoredMetadata("upAxis"),
        "has st/uv primvar": any(
            UsdGeom.PrimvarsAPI(m).HasPrimvar("st") or UsdGeom.PrimvarsAPI(m).HasPrimvar("uv")
            for m in meshes
        ),
        "bbox size": [round(x, 3) for x in bbox.GetSize()] if not bbox.IsEmpty() else None,
        "defaultPrim": stage.GetDefaultPrim().GetPath().pathString
        if stage.GetDefaultPrim()
        else None,
    }


log("\n## Route A: Usd.Stage.Open on the file (Houdini's usdFbx / usdGltf / geo / abc plugins)")
for name in ("box.fbx", "box_rop.gltf", "box_rop.glb", "card_hand.gltf", "box.obj", "box.abc"):
    path = src / name
    if not path.exists():
        continue
    t = time.time()
    try:
        stage = Usd.Stage.Open(path.as_posix())
    except Exception as e:  # noqa: BLE001
        log.check(f"open {name}", False, str(e)[:300])
        continue
    info = describe(stage)
    log.check(f"open {name} ({time.time() - t:.2f}s)", info["meshes"] > 0, "")
    for k, v in info.items():
        log(f"    {k}: {v}")
    out = d / "export" / (path.stem + "_" + path.suffix[1:] + ".usda")
    out.parent.mkdir(exist_ok=True)
    stage.Export(out.as_posix())
    text = out.read_text()
    absolute = [
        ln.strip() for ln in text.splitlines() if "@/" in ln or ":/" in ln.split("@")[-2:][0]
    ]
    log(f"    exported to {out.name}: absolute asset paths in it: {absolute[:3] or 'none'}")
    fmt = Sdf.FileFormat.FindByExtension(path.suffix[1:])
    _ = fmt
    if "[" in "".join(info["asset paths"]):
        from pxr import Ar

        first = info["asset paths"][0]
        asset = Ar.GetResolver().OpenAsset(Ar.ResolvedPath(first))
        log(
            f"    package texture readable through Ar: {bool(asset)} "
            f"({asset.GetSize() if asset else 0} bytes) -> can be copied out for the processor"
        )

# --- 3. route B: LOPs (Reference LOP on the file) + USD ROP with relative paths --------------------
log("\n## Route B: Reference LOP on the source file -> USD ROP (Use Relative Paths)")
for name in ("box.fbx", "box_rop.glb", "card_hand.gltf", "box.obj"):
    path = src / name
    if not path.exists():
        continue
    ref = hou.node("/stage").createNode("reference::2.0")
    ref.parm("primpath1").set("/oak")
    ref.parm("filepath1").set(path.as_posix())
    rop = hou.node("/stage").createNode("usd_rop")
    rop.setInput(0, ref)
    out = d / "lop" / f"{path.stem}_{path.suffix[1:]}.usda"
    rop.parm("lopoutput").set(out.as_posix())
    try:
        rop.render()
        text = out.read_text()
        refs = [ln.strip() for ln in text.splitlines() if "@" in ln]
        log.check(f"{name}", True, refs[:3])
        log(
            "    the layer keeps a reference to the source file (contents not baked): "
            f"{any(name in r for r in refs)}"
        )
    except hou.Error as e:
        log.check(name, False, str(e)[:300])
    try:
        st = ref.stage()
        log(
            f"    composed under /oak: {describe(st)['meshes']} meshes, "
            f"materials {describe(st)['materials']}"
        )
    except Exception as e:  # noqa: BLE001
        log(f"    composed stage failed: {e}")

# --- 4. route C: SOP loaders -----------------------------------------------------------------------------
log("\n## Route C: SOP loaders")
for name in ("box.fbx", "box_rop.gltf", "card_hand.gltf", "box.obj", "box.abc"):
    path = src / name
    if not path.exists():
        continue
    g = hou.Geometry()
    try:
        g.loadFromFile(path.as_posix())
        attrs = [a.name() for a in g.primAttribs()] + [a.name() for a in g.vertexAttribs()]
        log.check(
            f"hou.Geometry.loadFromFile {name}",
            len(g.prims()) > 0,
            f"{len(g.prims())} prims, attribs {attrs[:10]}",
        )
    except hou.Error as e:
        log.check(f"hou.Geometry.loadFromFile {name}", False, str(e)[:200])
sop = hou.node("/obj").createNode("geo", "gltf_import")
gl = sop.createNode("gltf")
gl.parm("filename").set((src / "card_hand.gltf").as_posix())
try:
    gg = gl.geometry()
    log.check(
        "glTF SOP",
        len(gg.prims()) > 0,
        f"{len(gg.prims())} prims, prim attribs {[a.name() for a in gg.primAttribs()]}",
    )
except hou.Error as e:
    log.check("glTF SOP", False, str(e)[:200])
try:
    t = time.time()
    res = hou.hipFile.importFBX((src / "box.fbx").as_posix())
    node = res[0] if isinstance(res, tuple) else res
    kids = [c.type().name() for c in node.allSubChildren()][:12] if node else []
    log.check(f"hou.hipFile.importFBX ({time.time() - t:.2f}s)", node is not None, kids)
except Exception as e:  # noqa: BLE001
    log.check("hou.hipFile.importFBX", False, str(e)[:200])

log.close()
