"""Runs inside hython (see test_houdini.py): export with the HDAs from
integrations/houdini/otls, loaded through the package. Prints ALL OK at the end."""

import json
import sys
from pathlib import Path

import hou
from pxr import Sdf, Usd, UsdGeom

import scheinwerk.dcc.houdini as sw
from scheinwerk.core.project import Project

tmp = Path(sys.argv[1])

project = Project.create(tmp / "show", "show")
hero = project.create_asset("hero", category="char")
hero.create_department("lookdev")
project.create_shot("sq010_0010", frames=(1001, 1002))
project.entity("sq010").create_department("lgt")
hou.hipFile.save((hero.path / "lookdev/main/work/hero_lookdev_main_v001.hip").as_posix())
sw.set_frame_range((1001, 1003))
hou.setFrame(1001)


def create(parent, type_name, input_node):
    # exact: an unfinished hand-built sw_publish_sop::1.0 must not win
    node = parent.createNode(type_name, exact_type_name=True)
    node.setInput(0, input_node)
    return node


def names(folder):
    return sorted(p.name for p in folder.iterdir())


# --- sw_publish_sop
geo = hou.node("/obj").createNode("geo")
sop = create(geo, "sw_publish_sop", geo.createNode("box"))
assert sop.parm("shot").menuItems() == ("",)  # menu script runs (no shots in an asset scene)
assert sop.evalParm("version") == 1 and sop.parm("range").evalAsString() == "shot"

# no product: neither the buttons nor the inner ROP itself write or reserve anything
sop.parm("new_version").pressButton()
sop.parm("execute").pressButton()
sop.node("export").parm("execute").pressButton()
assert not (hero.path / "publish").exists(), names(hero.path / "publish")

# shot range (an asset without frames: the scene's 1001-1003), one file per frame
sop.parm("product").set("box")
sop.parm("comment").set("first")
sop.parm("execute").pressButton()
v1 = hero.path / "publish/box/v001"
assert names(v1) == [f"hero_box_v001.{f}.bgeo.sc" for f in (1001, 1002, 1003)] + ["version.json"], (
    names(v1)
)
info = json.loads((v1 / "version.json").read_text(encoding="utf-8"))
assert info["comment"] == "first" and info["source"].endswith("hero_lookdev_main_v001.hip"), info
assert sop.displayNode().geometry().points(), "the input must pass through"

# current frame: one file without a frame number; New Version picks v002, Export creates it
assert "Latest   v001 | 3 files 1001-1003" in sop.evalParm("info"), sop.evalParm("info")
sop.parm("range").set("current")
sop.parm("ext").set("abc")
sop.parm("new_version").pressButton()
assert sop.evalParm("version") == 2 and not (hero.path / "publish/box/v002").exists()
assert "v002 is new: Export creates it" in sop.evalParm("info"), sop.evalParm("info")
sop.parm("execute").pressButton()
assert names(hero.path / "publish/box/v002") == ["hero_box_v002.abc", "version.json"]

# custom range
sop.parm("range").set("custom")
for parm, frame in zip(sop.parmTuple("frame_range"), (1002, 1003), strict=True):
    parm.setExpression(str(frame))  # as typing over the $FSTART/$FEND defaults in the UI does
sop.parm("ext").set("bgeo.sc")
sop.parm("new_version").pressButton()
sop.parm("execute").pressButton()
assert names(hero.path / "publish/box/v003") == [
    "hero_box_v003.1002.bgeo.sc",
    "hero_box_v003.1003.bgeo.sc",
    "version.json",
]

# the product menu offers existing products; picking one switches to its highest version
other = create(geo, "sw_publish_sop", geo.createNode("box"))
assert other.parm("product").menuItems() == ("box",)
other.parm("product").set("box")
other.parm("product").pressButton()  # runs the callback, as picking from the menu does
assert other.evalParm("version") == 3

# --- sw_publish_lop: USD layer, pointer and entry layer, stage passed through
stage = hou.node("/stage")
sphere = stage.createNode("sphere")
sphere.parm("ty").setExpression("$F - 1001")  # animated, to see time samples
lop = create(stage, "sw_publish_lop", sphere)
usd = hero.path / "publish/_usd"
assert lop.evalParm("version") == 1 and lop.parm("range").evalAsString() == "current"
lop.parm("execute").pressButton()  # no layer: nothing happens
assert not usd.exists()
assert lop.parm("layer").menuItems() == ("geo", "mtl")  # hints before any publish
assert lop.parm("layer").menuLabels() == ("geo (new)", "mtl (new)")
lop.parm("layer").set("asset")
lop.parm("new_version").pressButton()
assert lop.evalParm("version") == 1 and not usd.exists()
lop.parm("execute").pressButton()
assert names(usd / "asset/v001") == ["hero_asset_v001.usd", "version.json"]
assert "@./v001/hero_asset_v001.usd@" in (usd / "asset/asset.usd").read_text(encoding="utf-8")
assert "@./asset/asset.usd@" in (usd / "payload.usd").read_text(encoding="utf-8")
assert 'kind = "component"' in (usd / "hero.usd").read_text(encoding="utf-8")
assert lop.stage().GetPrimAtPath("/sphere1"), "the stage must pass through"
assert "Current  v001" in lop.evalParm("info"), lop.evalParm("info")
assert lop.parm("layer").menuItems() == ("geo", "mtl", "asset")

# a frame range: still one .usd, with time samples over the range
lop.parm("range").set("custom")
for parm, frame in zip(lop.parmTuple("frame_range"), (1001, 1003), strict=True):
    parm.setExpression(str(frame))
lop.parm("new_version").pressButton()
lop.parm("execute").pressButton()
assert names(usd / "asset/v002") == ["hero_asset_v002.usd", "version.json"]
layer = Usd.Stage.Open(str(usd / "asset/v002/hero_asset_v002.usd"))
assert (layer.GetStartTimeCode(), layer.GetEndTimeCode()) == (1001, 1003)
assert "@./v002/hero_asset_v002.usd@" in (usd / "asset/asset.usd").read_text(encoding="utf-8")

# --- sw_render: Karma, one .exr per frame
cam = stage.createNode("camera")
cam.setInput(0, stage.createNode("sphere"))
cam.parmTuple("t").set((0, 0, 5))
settings = stage.createNode("karmarenderproperties")
settings.setInput(0, cam)
render = create(stage, "sw_render", settings)
assert render.evalParm("render_name") == "" and render.parm("range").evalAsString() == "shot"
render.parm("execute").pressButton()  # no name: nothing happens
assert not (hero.path / "media").exists()
render.parm("render_name").set("beauty")
render.parm("execute").pressButton()
media = hero.path / "media/render_beauty/v001"
assert names(media) == [f"hero_render_beauty_v001.{f}.exr" for f in (1001, 1002, 1003)] + [
    "version.json"
], names(media)
assert render.parm("render_name").menuItems() == ("beauty",)
assert "Latest   v001 | 3 files 1001-1003" in render.evalParm("info"), render.evalParm("info")

# --- Write To: Task cache. Versioned, never finalized, read back with Load from Disk
cache_dir = hero.path / "lookdev/main/cache"
cache = create(geo, "sw_publish_sop", geo.createNode("box"))
assert cache.parm("target").evalAsString() == "publish"  # the default
cache.parm("target").set("cache")
assert cache.parm("product").menuItems() == ()  # caches of this task, not products
cache.parm("execute").pressButton()  # no name: nothing happens
assert names(cache_dir) == []
cache.parm("product").set("sim")
cache.parm("execute").pressButton()
assert names(cache_dir / "sim/v001") == [f"hero_sim_v001.{f}.bgeo.sc" for f in (1001, 1002, 1003)]
assert not (hero.path / "publish/sim").exists()  # caches never become products
assert cache.parm("product").menuItems() == ("sim",)
assert "Cache    sim" in cache.evalParm("info"), cache.evalParm("info")
cache.parm("load").set(1)
assert cache.node("load_from_disk").evalParm("input") == 1
assert len(cache.geometry().points()) == 8, "read the box back from disk"
cache.parm("new_version").pressButton()
assert cache.evalParm("version") == 2 and "v002 is new" in cache.evalParm("info")

lop_cache = create(stage, "sw_publish_lop", sphere)
lop_cache.parm("target").set("cache")
lop_cache.parm("layer").set("look")
lop_cache.parm("execute").pressButton()
assert names(cache_dir / "look/v001") == ["hero_look_v001.usd"]
assert not (usd / "look").exists()
assert "look" not in (usd / "payload.usd").read_text(encoding="utf-8")
lop_cache.parm("load").set(1)
assert lop_cache.node("load_from_disk").evalParm("input") == 1
assert lop_cache.stage().GetPrimAtPath("/sphere1"), "the cached layer is loaded back"

# Load from Disk also reads a published version back
lop.parm("load").set(1)
assert lop.stage().GetPrimAtPath("/sphere1")

# --- sw_import_sop: the latest version by default, a pinned one, any format
imp = geo.createNode("sw_import_sop", exact_type_name=True)
assert imp.parm("product").menuItems() == ("box",)  # empty entity: this scene's hero
imp.parm("product").set("box")
hou.setFrame(1002)
assert imp.evalParm("path").endswith("box/v003/hero_box_v003.1002.bgeo.sc"), imp.evalParm("path")
assert len(imp.geometry().points()) == 8
assert imp.parm("version").menuItems()[:2] == ("latest", "v003")
imp.parm("version").set("v002")
assert imp.evalParm("path").endswith("hero_box_v002.abc")
assert imp.parm("file").menuItems() == ("hero_box_v002.abc",)
assert imp.geometry().prims(), "the File SOP reads Alembic"
assert "Product  box  v002 of 3" in imp.evalParm("info"), imp.evalParm("info")
imp.parm("reload").pressButton()
hou.setFrame(1001)

# Choose…: the picker's choice lands in the parms (the dialog itself needs a UI, so a
# stand-in answers here; tests/gui/test_pick.py tests the dialog)
from scheinwerk.core.versions import Product  # noqa: E402
from scheinwerk.gui import pick as pick_module  # noqa: E402

answers = []


def fake_pick(scene, usd, entity="", product="", version="", parent=None, allowed=None):
    answers.append((usd, entity, product, version))
    seen_allowed[:] = [e.name for e in allowed] if allowed is not None else ["(import)"]
    return replies.pop(0)


seen_allowed = []


pick_module.pick = fake_pick
shot = project.entity("sq010_0010")
replies = [
    pick_module.Choice(shot, Product(project, shot.path / "publish/cam"), 1),
    pick_module.Choice(hero, Product(project, hero.path / "publish/box"), None),
]
chooser = geo.createNode("sw_import_sop", exact_type_name=True)
chooser.parm("choose").pressButton()
assert [chooser.evalParm(p) for p in ("entity", "product", "version")] == [
    "sq010_0010",
    "cam",
    "v001",
]
chooser.parm("choose").pressButton()
assert answers[1] == (False, "sq010_0010", "cam", "v001"), answers  # opens on the node's choice
assert [chooser.evalParm(p) for p in ("entity", "product", "version")] == ["", "box", "latest"]

# Choose… on a publish HDA: only this scene's entity, the name and its highest version
publisher = create(geo, "sw_publish_sop", geo.createNode("box"))
replies = [pick_module.Choice(hero, Product(project, hero.path / "publish/box"), None)]
publisher.parm("choose").pressButton()
assert seen_allowed == ["hero"] and answers[-1][1] == "hero"
assert (publisher.evalParm("product"), publisher.evalParm("version")) == ("box", 3)

# --- sw_import_lop: reference an asset's entry layer, sublayer one layer
geo_layer = stage.createNode("sphere")
geo_layer.parm("primpath").set("/hero/geo")
pub = create(stage, "sw_publish_lop", geo_layer)
pub.parm("layer").set("geo")
pub.parm("execute").pressButton()
il = stage.createNode("sw_import_lop", exact_type_name=True)
replies = [pick_module.Choice(hero, None, None)]
il.parm("choose").pressButton()
assert (il.evalParm("entity"), il.evalParm("layer"), il.evalParm("version")) == ("", "", "current")
assert answers[-1][0] is True  # the USD picker
assert il.evalParm("path").endswith("publish/_usd/hero.usd")  # empty layer: all layers
assert il.evalParm("primpath") == "/hero" and il.node("mode").evalParm("input") == 1
assert il.stage().GetPrimAtPath("/hero/geo"), "the asset is referenced at /hero"
assert il.parm("layer").menuItems()[:2] == ("", "asset")
il.parm("layer").set("asset")
il.parm("mode").set("sublayer")
assert il.evalParm("path").endswith("_usd/asset/asset.usd")  # current = the pointer
assert il.stage().GetPrimAtPath("/sphere1")
il.parm("version").set("v001")
assert il.evalParm("path").endswith("asset/v001/hero_asset_v001.usd")
assert il.parm("version").menuItems()[:3] == ("current", "v002", "v001")
assert "Layer    asset  current v002" in il.evalParm("info"), il.evalParm("info")

# --- a sequence scene publishes to the shot picked in the Shot menu
hou.hipFile.save(
    (project.root / "shots/sq010/_seq/lgt/main/work/sq010_lgt_main_v001.hip").as_posix()
)
assert "sq010_0010" in sop.parm("shot").menuItems()
sop.parm("shot").set("sq010_0010")
sop.parm("range").set("shot")
sop.parm("version").set(1)
sop.parm("execute").pressButton()
shot_box = project.root / "shots/sq010/sq010_0010/publish/box/v001"
assert names(shot_box) == [
    "sq010_0010_box_v001.1001.bgeo.sc",
    "sq010_0010_box_v001.1002.bgeo.sc",
    "version.json",
], names(shot_box)

# Choose… in a sequence scene: one of its shots, which also sets Shot
new_shot = project.create_shot("sq010_0020", frames=(1001, 1001))
replies = [pick_module.Choice(shot, Product(project, shot.path / "publish/box"), None)]
publisher.parm("choose").pressButton()
assert seen_allowed == ["sq010_0010", "sq010_0020"], seen_allowed  # the shots of sq010
assert (publisher.evalParm("shot"), publisher.evalParm("product")) == ("sq010_0010", "box")
assert publisher.evalParm("version") == 1  # sq010_0010's box: v001 from the export above

# a shot without any products: only the shot is chosen, the typed name stays
for node, name_parm in ((publisher, "product"), (create(stage, "sw_publish_lop", sphere), "layer")):
    node.parm(name_parm).set("fresh")
    replies = [pick_module.Choice(new_shot, None, None)]
    node.parm("choose").pressButton()
    assert (node.evalParm("shot"), node.evalParm(name_parm), node.evalParm("version")) == (
        "sq010_0020",
        "fresh",
        1,
    ), node.path()
    node.parm("execute").pressButton()
publish = project.root / "shots/sq010/sq010_0020/publish"
assert names(publish / "fresh/v001") == ["sq010_0020_fresh_v001.1001.bgeo.sc", "version.json"]
assert names(publish / "_usd/fresh/v001") == ["sq010_0020_fresh_v001.usd", "version.json"]

# --- an asset from Asset Start: geo, then mtl, from one scene, with Publish All USD
hou.hipFile.clear(suppress_save_prompt=True)
hou.hipFile.save((hero.path / "lookdev/main/work/hero_lookdev_main_v002.hip").as_posix())
stage = hou.node("/stage")
start = stage.createNode("sw_asset_start", exact_type_name=True)
assert start.evalParm("asset") == "hero"
s = start.stage()
assert s.GetPrimAtPath("/hero").GetTypeName() == "Xform" and not s.GetPrimAtPath("/hero").GetKind()
for scope in ("/hero/geo", "/hero/geo/render", "/hero/geo/proxy", "/hero/mtl"):
    assert s.GetPrimAtPath(scope).GetTypeName() == "Scope", scope
for purpose in ("render", "proxy"):
    prim = s.GetPrimAtPath(f"/hero/geo/{purpose}")
    assert UsdGeom.Imageable(prim).GetPurposeAttr().Get() == purpose, purpose
body = stage.createNode("sphere")
body.setInput(0, start)
body.parm("primpath").set("/hero/geo/render/body")
pub_geo = create(stage, "sw_publish_lop", body)
pub_geo.parm("layer").set("geo")  # geo/v001 exists from above: Publish All makes v002
assert pub_geo.evalParm("layer_break") == 1 and "Warning" not in pub_geo.evalParm("info")
look = stage.createNode("primitive")
look.setInput(0, pub_geo)
look.parm("primpath").set("/hero/mtl/red")
look.parm("primtype").set("UsdGeomScope")
pub_mtl = create(stage, "sw_publish_lop", look)
pub_mtl.parm("layer").set("mtl")
stray = stage.createNode("cube")
stray.setInput(0, pub_geo)
stray.parm("primpath").set("/stray")
warned = create(stage, "sw_publish_lop", stray)
warned.parm("layer").set("mtl")
assert "prims outside /hero: /stray" in warned.evalParm("info"), warned.evalParm("info")
warned.bypass(True)  # Publish All skips bypassed nodes
assert sw.publish_all_plan() == [(pub_geo, 2), (pub_mtl, 1)]
sw.publish_all_usd()
assert names(usd / "geo/v002") == ["hero_geo_v002.usd", "version.json"]
assert names(usd / "mtl/v001") == ["hero_mtl_v001.usd", "version.json"]
payload = (usd / "payload.usd").read_text(encoding="utf-8")
assert payload.index("./mtl/") < payload.index("./geo/") < payload.index("./asset/"), payload
pub_mtl.parm("load").set(1)  # the mtl from disk, on the published geo below it
loaded = pub_mtl.stage()
assert loaded.GetPrimAtPath("/hero/geo/render/body").GetTypeName() == "Sphere"
assert loaded.GetPrimAtPath("/hero/mtl/red")
pub_mtl.parm("load").set(0)
mtl_layer = Sdf.Layer.FindOrOpen(str(usd / "mtl/v001/hero_mtl_v001.usd"))
assert mtl_layer.GetPrimAtPath("/hero/mtl/red")
assert not mtl_layer.GetPrimAtPath("/hero/geo/render/body")
asset = Usd.Stage.Open(str(usd / "hero.usd"))
assert asset.GetPrimAtPath("/hero").GetKind() == "component"
assert asset.GetPrimAtPath("/hero/geo/render/body") and asset.GetPrimAtPath("/hero/mtl/red")
unloaded = Usd.Stage.Open(str(usd / "hero.usd"), Usd.Stage.LoadNone)
assert not unloaded.GetPrimAtPath("/hero/geo"), "the asset's layers sit behind its payload"

# --- a shot: fx in one scene, layout and lighting in another, both from Shot Start
shot.create_department("fx")
shot.create_department("lgt")
shot_usd = shot.path / "publish/_usd"
hou.hipFile.clear(suppress_save_prompt=True)
hou.hipFile.save((shot.path / "fx/main/work/sq010_0010_fx_main_v001.hip").as_posix())
stage = hou.node("/stage")
fx_start = stage.createNode("sw_shot_start", exact_type_name=True)
assert fx_start.evalParm("load") == "sequence"
loaded = fx_start.evalParm("info").splitlines()
assert loaded == ["Loaded (strongest first):", "shared/usd/structure.usd"], loaded
for prim, kind in (
    ("/world/chars", "group"),
    ("/world/cameras", "group"),
    ("/world/lights", "group"),
):
    found = fx_start.stage().GetPrimAtPath(prim)
    assert (found.GetTypeName(), found.GetKind()) == ("Xform", kind), prim
assert fx_start.stage().GetPrimAtPath("/Render").GetTypeName() == "Scope"
ball = stage.createNode("sphere")
ball.setInput(0, fx_start)
ball.parm("primpath").set("/world/fx/ball")
pub_fx = create(stage, "sw_publish_lop", ball)
pub_fx.parm("layer").set("fx")
pub_fx.parm("execute").pressButton()
fx_layer = Sdf.Layer.FindOrOpen(str(shot_usd / "fx/v001/sq010_0010_fx_v001.usd"))
assert fx_layer.GetPrimAtPath("/world/fx/ball")
assert fx_layer.GetPrimAtPath("/world").specifier == Sdf.SpecifierOver  # structure not republished
assert not fx_layer.GetPrimAtPath("/world/cameras")

hou.hipFile.clear(suppress_save_prompt=True)
hou.hipFile.save((shot.path / "lgt/main/work/sq010_0010_lgt_main_v001.hip").as_posix())
hou.setFrame(1001)
stage = hou.node("/stage")
main_start = stage.createNode("sw_shot_start", exact_type_name=True)
main_start.parm("load").set("fx sequence")
assert "shots/sq010/sq010_0010/publish/_usd/fx/fx.usd" in main_start.evalParm("info")
assert main_start.stage().GetPrimAtPath("/world/fx/ball")
hero_in = create(stage, "sw_import_lop", main_start)
hero_in.parm("entity").set("hero")
assert hero_in.evalParm("primpath") == "/world/chars/hero"  # a char: matches the structure
assert hero_in.stage().GetPrimAtPath("/world/chars/hero/geo/render/body")
pub_layout = create(stage, "sw_publish_lop", hero_in)
pub_layout.parm("layer").set("layout")
cam = stage.createNode("camera")
cam.setInput(0, pub_layout)
assert cam.parm("primpath").unexpandedString() == "/world/cameras/$OS"  # scripts/OnCreated.py
light = stage.createNode("light::2.0")
assert light.parm("primpath").unexpandedString() == "/world/lights/$OS"
light.destroy()
cam.parmTuple("t").set((0, 0, 5))
settings = stage.createNode("karmarenderproperties")
settings.setInput(0, cam)
pub_lgt = create(stage, "sw_publish_lop", settings)
pub_lgt.parm("layer").set("lgt")
assert [n for n, _ in sw.publish_all_plan()] == [pub_layout, pub_lgt]
sw.publish_all_usd()
root = (shot_usd / "sq010_0010.usd").read_text(encoding="utf-8")
assert (
    root.index("./lgt/")
    < root.index("./fx/")
    < root.index("./layout/")
    < root.index("shared/usd/structure.usd")
), root
assert "    startTimeCode = 1001\n    endTimeCode = 1002\n" in root
layout_layer = Sdf.Layer.FindOrOpen(str(shot_usd / "layout/v001/sq010_0010_layout_v001.usd"))
refs = layout_layer.GetPrimAtPath("/world/chars/hero").referenceList.GetAddedOrExplicitItems()
assert refs and refs[0].assetPath.startswith("../"), refs  # file-relative, to hero.usd
lgt_layer = Sdf.Layer.FindOrOpen(str(shot_usd / "lgt/v001/sq010_0010_lgt_v001.usd"))
assert not lgt_layer.GetPrimAtPath("/world/chars/hero"), "layout isn't published again"
assert lgt_layer.GetPrimAtPath("/world/cameras/camera1")
pub_lgt.parm("load").set(1)  # lgt from disk on fx, layout and the structure
loaded = pub_lgt.stage()
for prim in ("/world/cameras/camera1", "/world/fx/ball", "/world/chars/hero", "/world/lights"):
    assert loaded.GetPrimAtPath(prim), prim
pub_lgt.parm("load").set(0)

# --- the final render, from the published shot; it records what it used
final = create(stage, "sw_render", pub_lgt)
final.parm("render_name").set("final")
final.parm("source").set("published")
final.parm("range").set("current")
final.parm("execute").pressButton()
final_dir = shot.path / "media/render_final/v001"
assert names(final_dir) == ["sq010_0010_render_final_v001.1001.exr", "version.json"]
used = json.loads((final_dir / "version.json").read_text(encoding="utf-8"))["usd_files"]
for rel in (
    "assets/char/hero/publish/_usd/geo/v002/hero_geo_v002.usd",
    "assets/char/hero/publish/_usd/mtl/v001/hero_mtl_v001.usd",
    "shots/sq010/sq010_0010/publish/_usd/fx/v001/sq010_0010_fx_v001.usd",
    "shots/sq010/sq010_0010/publish/_usd/layout/v001/sq010_0010_layout_v001.usd",
    "shots/sq010/sq010_0010/publish/_usd/lgt/v001/sq010_0010_lgt_v001.usd",
):
    assert rel in used, used
assert not any(u.endswith(("fx.usd", "sq010_0010.usd", "hero.usd", "payload.usd")) for u in used)

# --- TAB menu: every HDA under Scheinwerk, not Digital Assets --------------------------
tools = {t.name(): t.toolMenuLocations() for t in hou.shelves.tools().values()}
for name in (
    "sop_sw_publish_sop",
    "lop_sw_publish_lop",
    "lop_sw_asset_start",
    "lop_sw_shot_start",
    "lop_sw_render",
    "sop_sw_import_sop",
    "lop_sw_import_lop",
):
    assert tools.get(name) == ("Scheinwerk",), (name, tools.get(name))  # fmt: skip

print("ALL OK", hou.applicationVersionString())
