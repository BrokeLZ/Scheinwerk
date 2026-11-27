"""L0 spike 6 — MaterialX image and triplanar nodes in Karma 21, normal maps under triplanar
(spec §17.8, `sw_texture_set`).

A box whose UVs are deliberately not aligned with the triplanar projections gets a constant
normal map tilted 30 deg towards +u (and one towards +v). The shading normal is written out as
colour (n * 0.5 + 0.5) and compared with the tilt each face should get from its projection.
Methods:
  naive   triplanarprojection_vector3 of the normal map -> normalmap (UV tangent)
  hmtlx   SideFX's hmtlxpbrtextureset, projection Tri-Planar, bump style Normal
  kma     Karma's kma_hextiled_triplanar_normal (hex tiling off)
  axes    one image + normalmap per projection axis, with that axis' tangent and bitangent,
          blended by the normal (what sw_texture_set would build)

Run in hython:  hython spike/l0/s06_triplanar.py
"""

from __future__ import annotations

import math

from common import Log, husk, oiio, pixel, write
from usdtext import header

log = Log("s06_triplanar")
d = log.dir

# --- textures ------------------------------------------------------------------------------------
oiio(
    [
        "--pattern",
        "fill:topleft=0,1,0:topright=1,1,0:bottomleft=0,0,0:bottomright=1,0,0",
        "256x256",
        3,
        "-d",
        "float",
        "-otex",
        d / "grad.exr",
    ],
    log,
)  # R = u, G = v
t = math.radians(30)
enc_u = (math.sin(t) * 0.5 + 0.5, 0.5, math.cos(t) * 0.5 + 0.5)
enc_v = (0.5, math.sin(t) * 0.5 + 0.5, math.cos(t) * 0.5 + 0.5)
for name, enc in (("nrm_u", enc_u), ("nrm_v", enc_v)):
    oiio(
        [
            "--pattern",
            "constant:color=" + ",".join(f"{c:.4f}" for c in enc),
            "64x64",
            3,
            "-d",
            "uint16",
            "-otex",
            d / f"{name}.tx",
        ],
        log,
    )

# --- box: per face a corner, u edge and v edge (cross(u, v) = outward normal) -------------------
FACES = {
    "+X": ((1, -1, 1), (0, 0, -1), (0, 1, 0)),
    "+Y": ((-1, 1, 1), (1, 0, 0), (0, 0, -1)),
    "+Z": ((-1, -1, 1), (1, 0, 0), (0, 1, 0)),
    "-X": ((-1, -1, -1), (0, 0, 1), (0, 1, 0)),
    "-Y": ((-1, -1, -1), (1, 0, 0), (0, 0, 1)),
    "-Z": ((1, -1, -1), (-1, 0, 0), (0, 1, 0)),
}


def add(a, b, s=1.0):
    return tuple(x + s * y for x, y in zip(a, b, strict=True))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


pts, nrms, sts = [], [], []
for corner, u, v in FACES.values():
    n = cross(u, v)
    for p in (corner, add(corner, u, 2), add(add(corner, u, 2), v, 2), add(corner, v, 2)):
        pts.append(p)
        nrms.append(n)
    sts += [(0, 0), (1, 0), (1, 1), (0, 1)]
BOX = f"""def Mesh "box" (
    prepend apiSchemas = ["MaterialBindingAPI"]
)
{{
    int[] faceVertexCounts = [4, 4, 4, 4, 4, 4]
    int[] faceVertexIndices = {list(range(24))}
    point3f[] points = {pts}
    normal3f[] normals = {nrms} (interpolation = "faceVarying")
    texCoord2f[] primvars:st = {sts} (interpolation = "faceVarying")
    uniform token subdivisionScheme = "none"
    rel material:binding = </M>
}}
""".replace("[(", "[(").replace("), (", "), (")


# --- shader network text ----------------------------------------------------------------------------
def node(name: str, node_id: str, out_type: str, **inputs) -> str:
    lines = [f'    def Shader "{name}"', "    {", f'        uniform token info:id = "{node_id}"']
    for key, (typ, val) in inputs.items():
        if isinstance(val, str) and val.startswith("<"):
            lines.append(f"        {typ} inputs:{key}.connect = {val}")
        elif typ == "asset":
            lines.append(
                f'        asset inputs:{key} = @{val}@ (\n            colorSpace = "raw"\n        )'
            )
        elif typ == "string":
            lines.append(f'        string inputs:{key} = "{val}"')
        else:
            lines.append(f"        {typ} inputs:{key} = {val}")
    lines += [f"        {out_type} outputs:out", "    }"]
    return "\n".join(lines)


def out(name: str) -> str:
    return f"</M/{name}.outputs:out>"


def material(body: list[str], result: str, kind: str = "vector3") -> str:
    """Emission = result (a vector3 normal -> n*0.5+0.5, or a colour as is)."""
    tail = []
    col = result
    if kind == "vector3":
        tail = [
            node("tocol", "ND_convert_vector3_color3", "color3f", **{"in": ("float3", result)}),
            node(
                "half",
                "ND_multiply_color3FA",
                "color3f",
                in1=("color3f", out("tocol")),
                in2=("float", 0.5),
            ),
            node(
                "remap",
                "ND_add_color3FA",
                "color3f",
                in1=("color3f", out("half")),
                in2=("float", 0.5),
            ),
        ]
        col = out("remap")
    surf = node(
        "surf",
        "ND_standard_surface_surfaceshader",
        "token",
        base=("float", 0),
        specular=("float", 0),
        emission=("float", 1),
        emission_color=("color3f", col),
    )
    return (
        'def Material "M"\n{\n    token outputs:mtlx:surface.connect = </M/surf.outputs:out>\n'
        + "\n".join([*body, *tail, surf])
        + "\n}\n"
    )


def pos_scaled() -> list[str]:
    """Object position * 0.25 + 0.5, so the face centre is mid-texture (no wrap)."""
    return [
        node("P", "ND_position_vector3", "float3", space=("string", "object")),
        node(
            "Ps", "ND_multiply_vector3FA", "float3", in1=("float3", out("P")), in2=("float", 0.25)
        ),
        node("Pc", "ND_add_vector3FA", "float3", in1=("float3", out("Ps")), in2=("float", 0.5)),
    ]


def tri(name: str, typ: str, file: str, signature: str, **extra) -> str:
    return node(
        name,
        f"ND_triplanarprojection_{signature}",
        typ,
        filex=("asset", file),
        filey=("asset", file),
        filez=("asset", file),
        position=("float3", out("Pc")),
        upaxis=("int", 1),
        blend=("float", 0.0),
        **extra,
    )


def m_uvproj() -> str:
    return material(
        [*pos_scaled(), tri("tri", "color3f", "./grad.exr", "color3")], out("tri"), "color3"
    )


def m_kma_uv() -> str:
    return material(
        [
            *pos_scaled(),
            node(
                "k",
                "kma_hextiled_triplanar_color",
                "color4f",
                file=("asset", "./grad.exr"),
                rand_rot=("float", 0.0),
                rand_scale=("float", 0.0),
                contrast=("float", 0.0),
                blend=("float", 0.02),
                position=("float3", out("Pc")),
            ).replace("color4f outputs:out", "color4f outputs:out"),
            node("k3", "ND_convert_color4_color3", "color3f", **{"in": ("color4f", out("k"))}),
        ],
        out("k3"),
        "color3",
    )


def m_naive(file: str) -> str:
    return material(
        [
            *pos_scaled(),
            tri("tri", "float3", file, "vector3"),
            node(
                "nm",
                "ND_normalmap_float",
                "float3",
                **{"in": ("float3", out("tri"))},
                scale=("float", 1.0),
            ),
        ],
        out("nm"),
    )


def m_hmtlx(file: str) -> str:
    return material(
        [
            node(
                "ts",
                "ND_hmtlxpbrtextureset",
                "float3",
                projection=("int", 1),
                bump_style=("int", 1),
                bump_normal_file=("asset", file),
                bump_scale=("float", 1.0),
                triplanar_upaxis=("int", 1),
                triplanar_blend=("float", 0.0),
            ).replace("float3 outputs:out", "float3 outputs:normal")
        ],
        "</M/ts.outputs:normal>",
    )


def m_kma(file: str) -> str:
    return material(
        [
            node(
                "k",
                "kma_hextiled_triplanar_normal",
                "float3",
                file=("asset", file),
                rand_rot=("float", 0.0),
                rand_scale=("float", 0.0),
                contrast=("float", 0.0),
                height=("float", 1.0),
                blend=("float", 0.02),
            )
        ],
        out("k"),
    )


# per projection axis (MaterialX triplanarprojection, up axis Y): which position components are
# u and v -> tangent and bitangent of that projection
AXES = {"x": ((0, 0, 1), (0, 1, 0)), "y": ((1, 0, 0), (0, 0, 1)), "z": ((1, 0, 0), (0, 1, 0))}
UV_OF = {"x": (2, 1), "y": (0, 2), "z": (0, 1)}


MIKKT = (
    0  # Karma-only input of ND_normalmap: 1 = MikkTSpace from the mesh, ignores tangent/bitangent
)


def m_axes(file: str, mode: str = "const") -> str:
    body = [
        *pos_scaled(),
        node("N", "ND_normal_vector3", "float3", space=("string", "world")),
        node("Na", "ND_absval_vector3", "float3", **{"in": ("float3", out("N"))}),
        node("W", "ND_power_vector3FA", "float3", in1=("float3", out("Na")), in2=("float", 8.0)),
    ]
    acc = None
    for i, (axis, (tan, bit)) in enumerate(AXES.items()):
        ui, vi = UV_OF[axis]
        body += [
            node(
                f"u{axis}",
                "ND_extract_vector3",
                "float",
                **{"in": ("float3", out("Pc"))},
                index=("int", ui),
            ),
            node(
                f"v{axis}",
                "ND_extract_vector3",
                "float",
                **{"in": ("float3", out("Pc"))},
                index=("int", vi),
            ),
            node(
                f"uv{axis}",
                "ND_combine2_vector2",
                "float2",
                in1=("float", out(f"u{axis}")),
                in2=("float", out(f"v{axis}")),
            ),
            node(
                f"img{axis}",
                "ND_image_vector3",
                "float3",
                file=("asset", file),
                texcoord=("float2", out(f"uv{axis}")),
            ),
        ]
        if mode == "manual":  # tangent-space -> world by hand: T*x + B*y + N*z
            body += [
                node(
                    f"dec{axis}",
                    "ND_multiply_vector3FA",
                    "float3",
                    in1=("float3", out(f"img{axis}")),
                    in2=("float", 2.0),
                ),
                node(
                    f"ts{axis}",
                    "ND_subtract_vector3FA",
                    "float3",
                    in1=("float3", out(f"dec{axis}")),
                    in2=("float", 1.0),
                ),
            ]
            for c in range(3):
                body.append(
                    node(
                        f"c{c}{axis}",
                        "ND_extract_vector3",
                        "float",
                        **{"in": ("float3", out(f"ts{axis}"))},
                        index=("int", c),
                    )
                )
            body += [
                node(
                    f"tx{axis}",
                    "ND_multiply_vector3FA",
                    "float3",
                    in1=("float3", tan),
                    in2=("float", out(f"c0{axis}")),
                ),
                node(
                    f"by{axis}",
                    "ND_multiply_vector3FA",
                    "float3",
                    in1=("float3", bit),
                    in2=("float", out(f"c1{axis}")),
                ),
                node(
                    f"nz{axis}",
                    "ND_multiply_vector3FA",
                    "float3",
                    in1=("float3", out("N")),
                    in2=("float", out(f"c2{axis}")),
                ),
                node(
                    f"s1{axis}",
                    "ND_add_vector3",
                    "float3",
                    in1=("float3", out(f"tx{axis}")),
                    in2=("float3", out(f"by{axis}")),
                ),
                node(
                    f"nm{axis}",
                    "ND_add_vector3",
                    "float3",
                    in1=("float3", out(f"s1{axis}")),
                    in2=("float3", out(f"nz{axis}")),
                ),
            ]
        else:
            t_in, b_in = ("float3", tan), ("float3", bit)
            if mode == "connected":
                body += [
                    node(f"T{axis}", "ND_constant_vector3", "float3", value=("float3", tan)),
                    node(f"B{axis}", "ND_constant_vector3", "float3", value=("float3", bit)),
                ]
                t_in, b_in = ("float3", out(f"T{axis}")), ("float3", out(f"B{axis}"))
            body.append(
                node(
                    f"nm{axis}",
                    "ND_normalmap_float",
                    "float3",
                    **{"in": ("float3", out(f"img{axis}"))},
                    scale=("float", 1.0),
                    normal=("float3", out("N")),
                    tangent=t_in,
                    bitangent=b_in,
                    karma_mikkt=("int", MIKKT),
                )
            )
        body += [
            node(
                f"w{axis}",
                "ND_extract_vector3",
                "float",
                **{"in": ("float3", out("W"))},
                index=("int", i),
            ),
            node(
                f"wn{axis}",
                "ND_multiply_vector3FA",
                "float3",
                in1=("float3", out(f"nm{axis}")),
                in2=("float", out(f"w{axis}")),
            ),
        ]
        if acc is None:
            acc = f"wn{axis}"
        else:
            body.append(
                node(
                    f"sum{axis}",
                    "ND_add_vector3",
                    "float3",
                    in1=("float3", out(acc)),
                    in2=("float3", out(f"wn{axis}")),
                )
            )
            acc = f"sum{axis}"
    body.append(node("nrm", "ND_normalize_vector3", "float3", **{"in": ("float3", out(acc))}))
    return material(body, out("nrm"))


# ortho camera head-on to each visible face: position, rotation, screen right, screen up
CAMS = {
    "+X": ((5, 0, 0), (0, 90, 0), (0, 0, -1), (0, 1, 0)),
    "+Y": ((0, 5, 0), (-90, 0, 0), (1, 0, 0), (0, 0, -1)),
    "+Z": ((0, 0, 5), (0, 0, 0), (1, 0, 0), (0, 1, 0)),
}


def cams() -> str:
    return "".join(
        f"""def Camera "cam_{k[1]}"
{{
    token projection = "orthographic"
    float horizontalAperture = 10
    float verticalAperture = 10
    double3 xformOp:translate = {pos}
    float3 xformOp:rotateXYZ = {rot}
    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
}}
"""
        for k, (pos, rot, _r, _u) in CAMS.items()
    )


def render(
    label: str, mat: str, face: str, engine: str
) -> tuple[list[float], list[float], list[float]]:
    usd = write(d / f"{label}.usda", header() + BOX + mat + cams())
    img = d / f"{label}_{face[1]}_{engine}.exr"
    husk(usd, img, log, engine, (33, 33), ["-p", "4", "-c", f"/cam_{face[1]}"])
    if not img.exists():
        return [], [], []
    return pixel(img, 16, 16), pixel(img, 20, 16), pixel(img, 16, 12)


def axis_name(vec) -> str:
    names = {
        (1, 0, 0): "+X",
        (-1, 0, 0): "-X",
        (0, 1, 0): "+Y",
        (0, -1, 0): "+Y"[0:0] + "-Y",
        (0, 0, 1): "+Z",
        (0, 0, -1): "-Z",
    }
    r = tuple(int(round(c)) for c in vec)
    return names.get(r, str(tuple(round(c, 2) for c in vec)))


# --- 1. where u and v run on each face (triplanarprojection colour) ---------------------------------
def measure(label: str, make, engine: str, store: dict | None) -> None:
    for face, (_p, _r, right, up) in CAMS.items():
        c, r, u = render(label, make(), face, engine)
        if not c:
            log.check(f"{label} {engine} {face} rendered", False)
            continue
        du = [(r[0] - c[0]), (u[0] - c[0])]
        dv = [(r[1] - c[1]), (u[1] - c[1])]
        tu = tuple(du[0] * a + du[1] * b for a, b in zip(right, up, strict=True))
        tv = tuple(dv[0] * a + dv[1] * b for a, b in zip(right, up, strict=True))
        nu, nv = (math.sqrt(dot(x, x)) or 1 for x in (tu, tv))
        tu = tuple(x / nu for x in tu)
        tv = tuple(x / nv for x in tv)
        if store is not None:
            store[face] = (tu, tv)
        log.note(
            f"{label} {engine} {face}",
            f"u runs {axis_name(tu)}, v runs {axis_name(tv)}   "
            f"(mesh UV: u {axis_name(FACES[face][1])}, v {axis_name(FACES[face][2])})  "
            f"centre {[round(x, 3) for x in c[:3]]}",
        )


log("## Where u and v run on each face (colour projection of a u/v gradient)")
MTLX_UV: dict = {}
KMA_UV: dict = {}
for engine in ("cpu", "xpu"):
    measure("mtlx_triplanar", m_uvproj, engine, MTLX_UV if engine == "cpu" else None)
    measure("kma_triplanar_color", m_kma_uv, engine, KMA_UV if engine == "cpu" else None)

# --- 2. normal maps ---------------------------------------------------------------------------------
log("\n## Normal map tilted 30 deg towards +u / +v: tilt direction on each face")
log("correct = tilt along the u/v where the same node's colour projection runs (kma: its own)")
methods = {
    "naive": (m_naive, MTLX_UV),
    "hmtlx": (m_hmtlx, MTLX_UV),
    "kma": (m_kma, KMA_UV),
    "axes (normalmap, constant tangents)": (m_axes, MTLX_UV),
    "axes (normalmap, connected tangents)": (lambda f: m_axes(f, "connected"), MTLX_UV),
    "axes (manual T*x + B*y + N*z)": (lambda f: m_axes(f, "manual"), MTLX_UV),
}
ONLY = __import__("os").environ.get("SPIKE_ONLY")  # e.g. "manual" for a quick partial run
for method, (make, ref_uv) in methods.items():
    if ONLY and ONLY not in method:
        continue
    for engine in ("cpu", "xpu"):
        verdict = []
        for which, k in (("u", 0), ("v", 1)):
            tdir = {f: uv[k] for f, uv in ref_uv.items()}
            for face in CAMS:
                label = "".join(ch if ch.isalnum() else "_" for ch in method)
                c, _r, _u = render(f"{label}_{which}", make(f"./nrm_{which}.tx"), face, engine)
                if not c:
                    verdict.append(f"{face}{which}:fail")
                    continue
                n = [2 * x - 1 for x in c[:3]]
                fn = cross(FACES[face][1], FACES[face][2])
                tilt = add(n, fn, -dot(n, fn))
                tl = math.sqrt(dot(tilt, tilt))
                if tl < 0.05:
                    verdict.append(f"{face}{which}:flat")
                    continue
                tilt = tuple(x / tl for x in tilt)
                want = tdir.get(face)
                s = dot(tilt, want) if want else 0
                tag = "ok" if s > 0.9 else ("MIRRORED" if s < -0.9 else f"OFF({axis_name(tilt)})")
                verdict.append(f"{face}{which}:{tag}")
        good = all(v.endswith(":ok") for v in verdict)
        log.check(f"{method} [{engine}]", good, "  ".join(verdict))

log("\nnaive/hmtlx use the mesh's UV tangent: right only where UVs happen to match the projection.")
log.close()
