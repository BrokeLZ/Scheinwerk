"""Tiny USDA text builders shared by the hython spikes (the way core would write USD: plain text)."""

from __future__ import annotations


def header(extra: str = "", up: str = "Y") -> str:
    return (
        f'#usda 1.0\n(\n    upAxis = "{up}"\n    metersPerUnit = 1\n'
        f"    framesPerSecond = 24\n    timeCodesPerSecond = 24\n{extra})\n\n"
    )


def ortho_camera(path_name: str = "cam", z: float = 5.0, width: float = 1.0) -> str:
    # USD camera apertures are in tenths of a scene unit
    ap = width * 10
    return f'''def Camera "{path_name}"
{{
    token projection = "orthographic"
    float horizontalAperture = {ap}
    float verticalAperture = {ap}
    float2 clippingRange = (0.01, 1000)
    double3 xformOp:translate = (0, 0, {z})
    uniform token[] xformOpOrder = ["xformOp:translate"]
}}
'''


def persp_camera(name: str, pos, rot, focal: float = 18.0, aperture: float = 36.0) -> str:
    return f'''def Camera "{name}"
{{
    float focalLength = {focal}
    float horizontalAperture = {aperture}
    float verticalAperture = {aperture}
    float2 clippingRange = (0.01, 10000)
    double3 xformOp:translate = {tuple(pos)}
    float3 xformOp:rotateXYZ = {tuple(rot)}
    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
}}
'''


def plane(name: str, material: str | None, size: float = 1.0, uv: float = 1.0) -> str:
    s = size
    bind = f"    rel material:binding = <{material}>\n" if material else ""
    meta = ' (\n    prepend apiSchemas = ["MaterialBindingAPI"]\n)' if material else ""
    return f'''def Mesh "{name}"{meta}
{{
    int[] faceVertexCounts = [4]
    int[] faceVertexIndices = [0, 1, 2, 3]
    point3f[] points = [(-{s}, -{s}, 0), ({s}, -{s}, 0), ({s}, {s}, 0), (-{s}, {s}, 0)]
    normal3f[] normals = [(0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1)] (interpolation = "vertex")
    texCoord2f[] primvars:st = [(0, 0), ({uv}, 0), ({uv}, {uv}), (0, {uv})] (interpolation = "vertex")
    uniform token subdivisionScheme = "none"
{bind}}}
'''


def emission_material(name: str, image_shader: str, out_type: str = "color3f") -> str:
    """Unlit MaterialX standard_surface whose emission colour is the given image node."""
    return f'''def Material "{name}"
{{
    token outputs:mtlx:surface.connect = <surf.outputs:out>
    def Shader "surf"
    {{
        uniform token info:id = "ND_standard_surface_surfaceshader"
        float inputs:base = 0
        float inputs:specular = 0
        float inputs:emission = 1
        color3f inputs:emission_color.connect = <../img.outputs:out>
        token outputs:out
    }}
{image_shader}
}}
'''


def image_node(
    file: str, color_space: str | None, node_id: str = "ND_image_color3", name: str = "img"
) -> str:
    meta = f' (\n            colorSpace = "{color_space}"\n        )' if color_space else ""
    return f'''    def Shader "{name}"
    {{
        uniform token info:id = "{node_id}"
        asset inputs:file = @{file}@{meta}
        color3f outputs:out
    }}'''
