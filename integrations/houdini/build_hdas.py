"""Build the Scheinwerk HDAs into otls/ (run with hython).

    hython integrations/houdini/build_hdas.py [hda ...]      (default: all seven)

sw_publish_sop, sw_publish_lop, sw_asset_start, sw_shot_start, sw_render, sw_import_sop,
sw_import_lop. They are plain node networks (no Python SOPs or LOPs), so they can be opened
and changed by hand afterwards (docs/usage.md, "Building the HDAs"). Running this again
rebuilds them from scratch and replaces hand edits.
"""

from __future__ import annotations

import sys
from pathlib import Path

import hou

OTLS = Path(__file__).resolve().parent / "otls"
IMPORT = "import scheinwerk.dcc.houdini as sw"
SW = '__import__("scheinwerk.dcc.houdini", fromlist=["x"])'  # one-line form for expressions
PY = hou.scriptLanguage.Python


# --- parameter templates (the same setup as the publish HDAs) ---------------------------


def menu_string(name: str, label: str, menu_fn: str, default: str = "", callback: str = ""):
    """A text field with a menu of existing names (menu script on two lines)."""
    t = hou.StringParmTemplate(
        name,
        label,
        1,
        default_value=(default,),
        item_generator_script=f'{IMPORT}\nreturn sw.{menu_fn}(kwargs["node"])',
        item_generator_script_language=PY,
        menu_type=hou.menuType.StringReplace,
    )
    if callback:
        t.setScriptCallback(f'{IMPORT}; sw.{callback}(kwargs["node"])')
        t.setScriptCallbackLanguage(PY)
    return t


def button(name: str, label: str, fn: str, disable_when: str = ""):
    t = hou.ButtonParmTemplate(name, label)
    t.setScriptCallback(f'{IMPORT}; sw.{fn}(kwargs["node"])')
    t.setScriptCallbackLanguage(PY)
    if disable_when:
        t.setConditional(hou.parmCondType.DisableWhen, disable_when)
    return t


def expression(name: str, label: str, code: str, **kwargs):
    """A string parm whose default is a Python expression (`code` uses SW)."""
    return hou.StringParmTemplate(
        name,
        label,
        1,
        default_value=(code,),
        default_expression=(code,),
        default_expression_language=(PY,),
        **kwargs,
    )


def info(code: str, always: str):
    """Read-only multi-line Info box. `always` is a conditional that is always true."""
    t = expression("info", "Info", code)
    t.setTags({"editor": "1", "editorlines": "4-7"})
    t.setConditional(hou.parmCondType.DisableWhen, always)
    return t


def versioning(name_parm: str, ext: bool, range_default: int) -> list:
    """[ext,] range, frame_range, version, new_version: as on the hand-built publish HDAs."""
    parms = []
    if ext:
        parms.append(
            hou.StringParmTemplate(
                "ext", "Extension", 1, default_value=("bgeo.sc",),
                menu_items=("bgeo.sc", "vdb", "abc", "obj"), menu_type=hou.menuType.Normal,
            )
        )  # fmt: skip
    rng = hou.MenuParmTemplate(
        "range", "Frame Range", menu_items=("current", "shot", "custom"),
        menu_labels=("Current Frame", "Shot Range", "Custom Range"), default_value=range_default,
    )  # fmt: skip
    frames = hou.IntParmTemplate(
        "frame_range", "Start/End", 2, default_value=(0, 0),
        default_expression=("$FSTART", "$FEND"),
        default_expression_language=(hou.scriptLanguage.Hscript,) * 2,
        naming_scheme=hou.parmNamingScheme.Base1,
    )  # fmt: skip
    frames.setConditional(hou.parmCondType.HideWhen, "{ range != custom }")
    version = hou.IntParmTemplate(
        "version", "Version", 1, default_value=(1,), min=1, max=999, min_is_strict=True
    )
    empty = f'{{ {name_parm} == "" }}'
    new = button("new_version", "New Version", "hda_new_version", empty)
    return [*parms, rng, frames, version, new]


# --- building -------------------------------------------------------------------------


def library(name: str) -> Path:
    """Indie saves .hdalc, Apprentice .hdanc, commercial .hda."""
    category = hou.licenseCategory()
    ext = {
        hou.licenseCategoryType.Indie: "hdalc",
        hou.licenseCategoryType.Apprentice: "hdanc",
    }.get(category, "hda")
    return OTLS / f"{name}.{ext}"


def tool_xml(category: str) -> str:
    """The TAB menu entry: under Scheinwerk, not Houdini's default Digital Assets."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <tool name="$HDA_DEFAULT_TOOL" label="$HDA_LABEL" icon="$HDA_ICON">
    <toolMenuContext name="viewer">
      <contextNetType>{category.upper()}</contextNetType>
    </toolMenuContext>
    <toolMenuContext name="network">
      <contextOpType>$HDA_TABLE_AND_NAME</contextOpType>
    </toolMenuContext>
    <toolSubmenu>Scheinwerk</toolSubmenu>
    <script scriptType="python"><![CDATA[import {category.lower()}toolutils

{category.lower()}toolutils.genericTool(kwargs, '$HDA_NAME')]]></script>
  </tool>
</shelfDocument>
"""


def save_asset(subnet, name: str, label: str, icon: str, parms: list, inputs: tuple[int, int]):
    path = library(name)
    for old in OTLS.glob(f"{name}.hda*"):  # rebuild from scratch
        hou.hda.uninstallFile(old.as_posix())
        old.unlink()
    node = subnet.createDigitalAsset(
        name=name,
        hda_file_name=path.as_posix(),
        description=label,
        min_num_inputs=inputs[0],
        max_num_inputs=inputs[1],
        ignore_external_references=True,
    )
    definition = node.type().definition()
    definition.addSection("Tools.shelf", tool_xml(node.type().category().name()))
    group = hou.ParmTemplateGroup(parms)
    definition.setParmTemplateGroup(group)
    definition.setIcon(icon)
    definition.save(path.as_posix(), template_node=node)
    print("built", path)


def chs(node, parm: str, source: str) -> None:
    node.parm(parm).setExpression(f'chs("../{source}")', hou.exprLanguage.Hscript)


def wire_export(rop, path_parm: str) -> None:
    """The inner ROP: path from ../output, frames from ../range, finalize after rendering."""
    chs(rop, path_parm, "output")
    rop.parm("trange").setExpression('ch("../range") != 0', hou.exprLanguage.Hscript)
    for index, parm in enumerate(("f1", "f2")):
        rop.parm(parm).setExpression(
            f"{SW}.hda_range(hou.pwd().parent())[{index}]", hou.exprLanguage.Python
        )
    rop.parm("tpostrender").set(1)
    rop.parm("lpostrender").set("python")
    rop.parm("postrender").set(f"{IMPORT}; sw.hda_post_render(hou.pwd().parent())")


def publish_parms(name_parm: str, ext: bool, range_default: int, usd: bool = False) -> list:
    """Write To, the name, versioning, Shot/Comment (publishing only), Load from Disk,
    Output, Export and Info. `usd`: sw_publish_lop, which also publishes USD products.
    New menu entries go last: a scene stores the entry's index."""
    items, labels = ["publish", "cache"], ["Publish (products)", "Task cache (not published)"]
    if usd:
        labels[0] = "Publish (USD layer)"
        items.append("product")
        labels.append("Publish (USD product, e.g. a part of a layer)")
    target = hou.MenuParmTemplate(
        "target", "Write To", menu_items=items, menu_labels=labels, default_value=0
    )
    shot = hou.StringParmTemplate(
        "shot", "Shot", 1, default_value=("",),
        item_generator_script=f"{IMPORT}\nreturn sw.shot_menu()",
        item_generator_script_language=PY, menu_type=hou.menuType.Normal,
    )  # fmt: skip
    comment = hou.StringParmTemplate("comment", "Comment", 1, default_value=("",))
    for parm in (shot, comment):
        parm.setConditional(hou.parmCondType.HideWhen, "{ target == cache }")
    empty = f'{{ {name_parm} == "" }}'
    choose = button("choose", "Choose…", "publish_choose", "{ target == cache }")
    return [
        target,
        choose,
        menu_string(name_parm, "Name", "hda_name_menu", callback="hda_name_changed"),
        *versioning(name_parm, ext, range_default),
        shot,
        comment,
        hou.ToggleParmTemplate("load", "Load from Disk", default_value=False),
        expression("output", "Output", f"{SW}.hda_output(hou.pwd())"),
        button("execute", "Export", "hda_execute", empty),
        hou.SeparatorParmTemplate("info_sep"),
        info(f"{SW}.hda_info(hou.pwd())", "{ version > -1 }"),
    ]


LOAD_SLOTS = 12  # Sublayer LOP files: the structure or sequence layer plus the layers


def load_slots(sublayer, function: str) -> None:
    """Fill a Sublayer LOP's files from `sw.<function>(node, index)`, "" = unused."""
    sublayer.parm("num_files").set(LOAD_SLOTS)
    for index in range(1, LOAD_SLOTS + 1):
        call = f"{SW}.{function}(hou.pwd().parent(), {index})"
        sublayer.parm(f"filepath{index}").setExpression(call, hou.exprLanguage.Python)
        sublayer.parm(f"enable{index}").setExpression(f'{call} != ""', hou.exprLanguage.Python)


def build_publish_sop() -> None:
    geo = hou.node("/obj").createNode("geo")
    net = geo.createNode("subnet", "sw_publish_sop")
    source = net.indirectInputs()[0]
    export = net.createNode("rop_geometry", "export")
    export.setInput(0, source)
    wire_export(export, "sopoutput")
    load = net.createNode("file", "load")
    chs(load, "file", "output")
    switch = net.createNode("switch", "load_from_disk")
    switch.setInput(0, source)
    switch.setInput(1, load)
    switch.parm("input").setExpression('ch("../load")', hou.exprLanguage.Hscript)
    out = net.createNode("null", "OUT")
    out.setInput(0, switch)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    net.layoutChildren()
    parms = publish_parms("product", ext=True, range_default=1)
    save_asset(net, "sw_publish_sop", "Scheinwerk Publish", "SOP_filecache", parms, (1, 1))


def build_publish_lop() -> None:
    net = hou.node("/stage").createNode("subnet", "sw_publish_lop")
    source = net.indirectInputs()[0]
    # the USD ROP writes whatever fps the stage's root layer carries, not the scene's:
    # set the target entity's fps on what is written (spec §9.2 item 5)
    fps = net.createNode("configurelayer", "fps")
    fps.setInput(0, source)
    for toggle, value in (
        ("setframespersecond", "framespersecond"),
        ("settimepersecond", "timepersecond"),
    ):
        fps.parm(toggle).set(1)
        fps.parm(value).setExpression(f"{SW}.hda_fps(hou.pwd().parent())", hou.exprLanguage.Python)
    export = net.createNode("usd_rop", "export")
    export.setInput(0, fps)
    wire_export(export, "lopoutput")  # Use Relative Paths stays on (the default)
    # one file per layer or part: a SOP Create's layer (merged or added as a sublayer) is
    # flattened in, never saved next to it under a node path (obj/.../sopnet/OUT.usd)
    export.parm("flattensoplayers").set(1)
    export.parm("defaultprim").setExpression(
        f"{SW}.hda_default_prim(hou.pwd().parent())", hou.exprLanguage.Python
    )
    # Load from Disk. A layer: the written file on the published layers below it. A part
    # (USD product, task cache): the layers below behind a Layer Break, the file referenced
    # on top at its root prim, so a layer it is merged into writes only the reference.
    load = net.createNode("sublayer", "load")
    load_slots(load, "hda_load_file")
    load_break = net.createNode("layerbreak", "load_break")
    load_break.setInput(0, load)
    part = net.createNode("reference::2.0", "load_part")
    part.setInput(0, load_break)
    chs(part, "primpath1", "rootprim")
    chs(part, "filepath1", "output")
    part.parm("filerefprim1").set("")  # Reference Specific Primitive: the same root prim
    chs(part, "filerefprimpath1", "rootprim")
    switch = net.createNode("switch", "load_from_disk")
    for index, node in enumerate((source, load, part)):
        switch.setInput(index, node)
    switch.parm("input").setExpression(
        'ch("../load") * (1 + (ch("../target") != 0))', hou.exprLanguage.Hscript
    )
    # Layer Break After: always for a layer (the shot's root layer stacks it again); an
    # option for a part, off by default: it is merged into a layer further down
    brk = net.createNode("layerbreak", "break")
    brk.setInput(0, switch)
    after = net.createNode("switch", "layer_break_after")
    after.setInput(0, switch)
    after.setInput(1, brk)
    after.parm("input").setExpression(
        'ch("../target") == 0 || ch("../layer_break")', hou.exprLanguage.Hscript
    )
    output = net.node("output0") or net.createNode("output", "output0")
    output.setInput(0, after)
    output.setDisplayFlag(True)
    net.layoutChildren()
    parms = publish_parms("layer", ext=False, range_default=0, usd=True)
    root = expression("rootprim", "Root Prim", f"{SW}.hda_root_default(hou.pwd())")
    root.setHelp(
        "Everything the part authors lives under this prim (default /<name>). Load from "
        "Disk references it here; place it with Graft Branches (e.g. under /world/env), "
        "and the layer it is grafted into writes that reference."
    )
    root.setConditional(hou.parmCondType.HideWhen, "{ target == publish }")
    layer_break = hou.ToggleParmTemplate("layer_break", "Layer Break After", default_value=False)
    layer_break.setHelp(
        "A layer always breaks. A part usually merges into a layer below, so it doesn't."
    )
    layer_break.setConditional(hou.parmCondType.HideWhen, "{ target == publish }")
    at = parms.index(next(p for p in parms if p.name() == "load")) + 1
    parms[at:at] = [layer_break]
    name_at = parms.index(next(p for p in parms if p.name() == "layer")) + 1
    parms[name_at:name_at] = [root]
    save_asset(net, "sw_publish_lop", "Scheinwerk Publish USD", "LOP_subnet", parms, (1, 1))


def build_asset_start() -> None:
    """The asset skeleton: the Xform /<asset> (the only transformable prim), Scopes
    /<asset>/geo/{render,proxy} with purposes and /<asset>/mtl (spec §9.3). Prim paths
    come from the read-only `asset` parm."""
    net = hou.node("/stage").createNode("subnet", "sw_asset_start")
    root = '/`chs("../asset")`'
    previous = None
    for node_name, paths, prim_type in (
        ("asset", root, "UsdGeomXform"),
        ("geo", f"{root}/geo {root}/geo/render {root}/geo/proxy", "UsdGeomScope"),
        ("mtl", f"{root}/mtl", "UsdGeomScope"),
    ):
        prim = net.createNode("primitive", node_name)
        prim.parm("primpath").set(paths)
        prim.parm("primtype").set(prim_type)
        if previous is not None:
            prim.setInput(0, previous)
        previous = prim
    for purpose in ("render", "proxy"):
        configure = net.createNode("configureprimitive", f"{purpose}_purpose")
        configure.setInput(0, previous)
        configure.parm("primpattern").set(f"{root}/geo/{purpose}")
        configure.parm("setpurpose").set(1)
        configure.parm("purpose").set(purpose)
        previous = configure
    output = net.node("output0") or net.createNode("output", "output0")
    output.setInput(0, previous)
    output.setDisplayFlag(True)
    net.layoutChildren()
    asset = expression("asset", "Asset", f"{SW}.start_asset(hou.pwd())")
    asset.setConditional(hou.parmCondType.DisableWhen, '{ asset == "" } { asset != "" }')
    asset.setHelp("The scene's asset. Asset Start only works in an asset's scene.")
    icon = hou.nodeType(hou.lopNodeTypeCategory(), "primitive").icon()
    save_asset(net, "sw_asset_start", "Scheinwerk Asset Start", icon, [asset], (0, 0))


def build_shot_start() -> None:
    """Loads the structure layer (or the sequence root layer) and the ticked published
    layers behind a Layer Break, so none of it is published again (spec §13.2.6)."""
    net = hou.node("/stage").createNode("subnet", "sw_shot_start")
    sublayer = net.createNode("sublayer", "load")
    load_slots(sublayer, "shot_start_file")
    brk = net.createNode("layerbreak", "break")
    brk.setInput(0, sublayer)
    output = net.node("output0") or net.createNode("output", "output0")
    output.setInput(0, brk)
    output.setDisplayFlag(True)
    net.layoutChildren()
    shot = hou.StringParmTemplate(
        "shot", "Shot", 1, default_value=("",),
        item_generator_script=f"{IMPORT}\nreturn sw.shot_menu()",
        item_generator_script_language=PY, menu_type=hou.menuType.Normal,
    )  # fmt: skip
    load = hou.StringParmTemplate(
        "load", "Load", 1, default_value=("sequence",),
        item_generator_script=f'{IMPORT}\nreturn sw.shot_start_layer_menu(kwargs["node"])',
        item_generator_script_language=PY, menu_type=hou.menuType.StringToggle,
    )  # fmt: skip
    load.setHelp("The layers published from other scenes, e.g. fx in the main scene.")
    reload = hou.ButtonParmTemplate("reload", "Reload")
    reload.setScriptCallback('hou.pwd().node("load").parm("reload").pressButton()')
    reload.setScriptCallbackLanguage(PY)
    parms = [
        shot,
        load,
        reload,
        hou.SeparatorParmTemplate("info_sep"),
        info(f"{SW}.shot_start_info(hou.pwd())", '{ load == "" } { load != "" }'),
    ]
    icon = hou.nodeType(hou.lopNodeTypeCategory(), "sublayer").icon()
    save_asset(net, "sw_shot_start", "Scheinwerk Shot Start", icon, parms, (0, 0))


def build_render() -> None:
    """Karma through a USD Render ROP, one husk run per frame. Source: the input (live
    stage) or the target's published root layer (spec §13.2.6)."""
    net = hou.node("/stage").createNode("subnet", "sw_render")
    source_in = net.indirectInputs()[0]
    published = net.createNode("sublayer", "published")
    published.parm("filepath1").setExpression(
        f"{SW}.render_root(hou.pwd().parent())", hou.exprLanguage.Python
    )
    source = net.createNode("switch", "source")
    source.setInput(0, source_in)
    source.setInput(1, published)
    source.parm("input").setExpression('ch("../source")', hou.exprLanguage.Hscript)
    rop = net.createNode("usdrender_rop", "render")
    rop.setInput(0, source)
    wire_export(rop, "outputimage")
    # the look comes from the stage (Karma Render Settings under /Render); the ROP points
    # at it, by the node's Render Settings or automatically (the published shot is
    # sublayered, which drops the default settings metadata, so it finds the prim). The
    # engine picks the delegate: husk ignores the setting.
    rop.parm("rendersettings").setExpression(
        f"{SW}.render_settings_path(hou.pwd().parent())", hou.exprLanguage.Python
    )
    chs(rop, "renderpass", "renderpass")
    rop.parm("renderer").setExpression(
        f"{SW}.render_delegate(hou.pwd().parent())", hou.exprLanguage.Python
    )
    output = net.node("output0") or net.createNode("output", "output0")
    output.setInput(0, source_in)
    output.setDisplayFlag(True)
    net.layoutChildren()
    shot = hou.StringParmTemplate(
        "shot", "Shot", 1, default_value=("",),
        item_generator_script=f"{IMPORT}\nreturn sw.shot_menu()",
        item_generator_script_language=PY, menu_type=hou.menuType.Normal,
    )  # fmt: skip
    source_menu = hou.MenuParmTemplate(
        "source", "Source", menu_items=("live", "published"),
        menu_labels=("Live stage (the input)", "Published shot"), default_value=0,
    )  # fmt: skip
    settings = menu_string("rendersettings", "Render Settings", "render_settings_menu")
    settings.setHelp(
        "The RenderSettings prim (Karma Render Settings LOP): engine, samples, "
        "motion blur, camera, AOVs. XPU or CPU follows its engine. Empty: automatic, the "
        "stage's own settings, else the first under /Render."
    )
    render_pass = menu_string("renderpass", "Render Pass", "render_pass_menu")
    render_pass.setHelp("Optional RenderPass prim. Empty: none.")
    empty = '{ render_name == "" }'
    parms = [
        menu_string("render_name", "Render Name", "hda_name_menu", callback="hda_name_changed"),
        source_menu,
        settings,
        render_pass,
        *versioning("render_name", ext=False, range_default=1),
        shot,
        hou.StringParmTemplate("comment", "Comment", 1, default_value=("",)),
        expression("output", "Output", f"{SW}.hda_output(hou.pwd())"),
        button("execute", "Render", "hda_execute", empty),
        hou.SeparatorParmTemplate("info_sep"),
        info(f"{SW}.hda_info(hou.pwd())", "{ version > -1 }"),
    ]
    icon = hou.nodeType(hou.lopNodeTypeCategory(), "usdrender_rop").icon()
    save_asset(net, "sw_render", "Scheinwerk Render", icon, parms, (1, 1))


def import_parms(name_parm: str, name_label: str, version_default: str) -> list:
    version = menu_string("version", "Version", "import_version_menu", default=version_default)
    if name_parm == "layer":
        version.setConditional(hou.parmCondType.DisableWhen, '{ layer == "" }')
    entity = hou.StringParmTemplate("entity", "Entity", 1, default_value=("",))
    entity.setHelp("Empty: this scene's asset or shot. Use Choose… to pick another one.")
    return [
        button("choose", "Choose…", "import_choose"),
        entity,
        menu_string(name_parm, name_label, "import_product_menu"),
        version,
    ]


ALWAYS = '{ entity == "" } { entity != "" }'  # two OR-ed conditions: always true


def build_import_sop() -> None:
    geo = hou.node("/obj").createNode("geo")
    net = geo.createNode("subnet", "sw_import_sop")
    load = net.createNode("file", "load")
    chs(load, "file", "path")
    out = net.createNode("null", "OUT")
    out.setInput(0, load)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    net.layoutChildren()
    parms = [
        *import_parms("product", "Product", "latest"),
        menu_string("file", "File", "import_file_menu"),
        button("reload", "Reload", "import_reload"),
        expression("path", "Path", f"{SW}.import_path(hou.pwd())"),
        hou.SeparatorParmTemplate("info_sep"),
        info(f"{SW}.import_info(hou.pwd())", ALWAYS),
    ]
    save_asset(net, "sw_import_sop", "Scheinwerk Import", "SOP_file", parms, (0, 0))


def build_import_lop() -> None:
    net = hou.node("/stage").createNode("subnet", "sw_import_lop")
    source = net.indirectInputs()[0]
    sublayer = net.createNode("sublayer", "sublayer")
    sublayer.setInput(0, source)
    chs(sublayer, "filepath1", "path")
    reference = net.createNode("reference::2.0", "reference")
    reference.setInput(0, source)
    chs(reference, "filepath1", "path")
    chs(reference, "primpath1", "primpath")
    switch = net.createNode("switch", "mode")
    switch.setInput(0, sublayer)
    switch.setInput(1, reference)
    switch.parm("input").setExpression(
        f"{SW}.import_mode(hou.pwd().parent())", hou.exprLanguage.Python
    )
    output = net.node("output0") or net.createNode("output", "output0")
    output.setInput(0, switch)
    output.setDisplayFlag(True)
    net.layoutChildren()
    mode = hou.MenuParmTemplate(
        "mode", "Mode", menu_items=("auto", "reference", "sublayer"),
        menu_labels=("Auto (reference assets, sublayer shots)", "Reference", "Sublayer"),
        default_value=0,
    )  # fmt: skip
    parms = [
        *import_parms("layer", "Layer", "current"),
        mode,
        expression("primpath", "Primitive Path", f"{SW}.import_prim(hou.pwd())"),
        button("reload", "Reload", "import_reload"),
        expression("path", "Path", f"{SW}.import_usd_path(hou.pwd())"),
        hou.SeparatorParmTemplate("info_sep"),
        info(f"{SW}.import_info(hou.pwd())", ALWAYS),
    ]
    save_asset(net, "sw_import_lop", "Scheinwerk Import USD", "LOP_reference", parms, (0, 1))


BUILDERS = {
    "sw_publish_sop": build_publish_sop,
    "sw_publish_lop": build_publish_lop,
    "sw_asset_start": build_asset_start,
    "sw_shot_start": build_shot_start,
    "sw_render": build_render,
    "sw_import_sop": build_import_sop,
    "sw_import_lop": build_import_lop,
}

if __name__ == "__main__":
    for hda in sys.argv[1:] or BUILDERS:
        BUILDERS[hda]()
