"""L0 spike 4 — DomeLight orientation (spec §17.8): what does Houdini 21's Dome Light LOP author,
and which hand-written DomeLight looks the same in Karma?

A lat-long map with four colour quarters (u: red, green, blue, yellow) and a white top band is
seen through six cameras (+X -X +Y -Y +Z -Z); every way of authoring the light is compared with
the Dome Light LOP.

Run in hython:  hython spike/l0/s04_domelight.py
"""

from __future__ import annotations

import hou

from common import Log, husk, oiio, pixel, write

log = Log("s04_domelight")
d = log.dir

tex = d / "quarters.exr"
oiio(
    [
        "--pattern",
        "constant:color=0,0,0",
        "512x256",
        3,
        "-d",
        "half",
        "--fill:color=1,0,0",
        "64x256+0+0",
        "--fill:color=1,0,0",
        "64x256+448+0",
        "--fill:color=0,1,0",
        "128x256+64+0",
        "--fill:color=0,0,1",
        "128x256+192+0",
        "--fill:color=1,1,0",
        "128x256+320+0",
        "--fill:color=1,1,1",
        "512x24+0+0",
        "-oenv",
        tex,
    ],
    log,
)
log(
    "Texture: red centred on u=0 (and 1), green on u=0.25, blue on u=0.5, yellow on u=0.75; "
    "top rows white (= the pole)."
)

# camera looks down -Z; rotations that make it look along each axis
DIRS = {
    "-Z": (0, 0, 0),
    "+Z": (0, 180, 0),
    "+X": (0, -90, 0),
    "-X": (0, 90, 0),
    "+Y": (90, 0, 0),
}  # -Y is left out: at the pole all colours meet


def cameras(up: str) -> str:
    out = []
    for name, rot in DIRS.items():
        r = rot
        if up == "Z":  # same world directions in a Z-up stage: rotate everything +90 about X
            r = (rot[0] + 90, rot[1], rot[2]) if name not in ("+Y", "-Y") else rot
        cam = name.replace("+", "p").replace("-", "n")
        out.append(f"""def Camera "cam_{cam}"
{{
    float focalLength = 50
    float horizontalAperture = 36
    float verticalAperture = 36
    float3 xformOp:rotateXYZ = {r}
    uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
}}
""")
    return "\n".join(out)


COLOURS = {
    "red": (1, 0, 0),
    "green": (0, 1, 0),
    "blue": (0, 0, 1),
    "yellow": (1, 1, 0),
    "white": (1, 1, 1),
    "black": (0, 0, 0),
}


def name_of(rgb: list[float]) -> str:
    if not rgb:
        return "?"
    return min(
        COLOURS, key=lambda k: sum((a - b) ** 2 for a, b in zip(COLOURS[k], rgb[:3], strict=False))
    )


def look(label: str, light_text: str, up: str = "Y", engine: str = "cpu") -> dict[str, str]:
    usd = write(
        d / f"{label}.usda",
        f'#usda 1.0\n(\n    upAxis = "{up}"\n)\n\n' + light_text + "\n" + cameras(up),
    )
    seen = {}
    for name in DIRS:
        cam = name.replace("+", "p").replace("-", "n")
        img = d / f"{label}_{engine}_{cam}.exr"
        husk(usd, img, log, engine, (33, 33), ["-p", "4", "-c", f"/cam_{cam}"])
        seen[name] = name_of(pixel(img, 16, 16)) if img.exists() else "fail"
    log.note(f"{label} [{engine}, upAxis {up}]", "  ".join(f"{k}:{v}" for k, v in seen.items()))
    return seen


VIS = "    bool karma:light:renderlightgeo = 1\n"

# --- 1. what the LOPs author ----------------------------------------------------------------------
log("## What Houdini authors")
lop_text = {}
for node_type in ("domelight::3.0", "domelight::2.0"):
    n = hou.node("/stage").createNode(node_type)
    parm = n.parm("xn__inputstexturefile_r3ah") or n.parm("xn__inputstexturefile_kya")
    parm.set(tex.as_posix())
    stage = n.stage()
    prim = next(p for p in stage.Traverse() if "DomeLight" in p.GetTypeName())
    attrs = {
        a.GetName(): str(a.Get())
        for a in prim.GetAttributes()
        if a.GetName() in ("poleAxis",) or "xformOp" in a.GetName()
    }
    up = stage.GetMetadata("upAxis")
    log.note(
        f"{node_type}: prim",
        f"{prim.GetPath()} type={prim.GetTypeName()} {attrs} stage upAxis={up}",
    )
    layer = stage.Flatten()
    lop_prim = layer.GetPrimAtPath(prim.GetPath())
    text = layer.ExportToString()
    body = text[text.index('def Xform "world"') :]
    body = body.replace(
        "    {\n            custom rel filters",
        "    {\n" + VIS + "            custom rel filters",
        1,
    )
    lop_text[node_type] = body if lop_prim else ""
    log.note(f"{node_type}: renderlightgeo authored", "karma:light:renderlightgeo" in text)

# --- 2. compare -----------------------------------------------------------------------------------------
log("\n## Directions (centre colour seen looking along each world axis)")
ref = {}
for engine in ("cpu", "xpu"):
    ref[engine] = look("lop_domelight3", lop_text["domelight::3.0"], "Y", engine)
look("lop_domelight2", lop_text["domelight::2.0"], "Y")


def plain(type_name: str, extra: str = "") -> str:
    return (
        f'def {type_name} "sky"\n{{\n    asset inputs:texture:file = @./quarters.exr@\n'
        f"{extra}{VIS}}}\n"
    )


cases = [
    (
        "DomeLight_1 poleAxis=scene",
        plain("DomeLight_1", '    uniform token poleAxis = "scene"\n'),
        "Y",
    ),
    ("DomeLight_1 poleAxis=Y", plain("DomeLight_1", '    uniform token poleAxis = "Y"\n'), "Y"),
    ("DomeLight_1 no poleAxis", plain("DomeLight_1"), "Y"),
    ("DomeLight (legacy type)", plain("DomeLight"), "Y"),
]
for label, text, up in cases:
    for engine in ("cpu", "xpu"):
        got = look(
            label.replace(" ", "_").replace("=", "").replace("(", "").replace(")", ""),
            text,
            up,
            engine,
        )
        log.check(f"  {label} [{engine}] looks like the Dome Light LOP", got == ref[engine])

log("\nReading: the image centre (u=0.5, blue) faces +Z, u=0.25 faces +X, the seam (u=0) faces -Z")
log("(what a default camera sees), the top row is +Y.")
log.close()
