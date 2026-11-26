"""Runs inside hython (see test_houdini.py): export with the HDAs from
integrations/houdini/otls, loaded through the package. Prints ALL OK at the end."""

import json
import sys
from pathlib import Path

import hou
from pxr import Sdf, Usd, UsdGeom

import scheinwerk.dcc.houdini as sw
from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.fileio import read_json, write_json
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

# a failed export finalizes nothing (no version.json, the pointer stays) and says so
(usd / "asset/v003/hero_asset_v003.usd").mkdir(parents=True)  # the ROP can't write there
try:
    sw.publish_all_usd([(lop, 3)])
    raise AssertionError("a failed export must raise")
except ScheinwerkError as exc:
    assert "failed" in str(exc) and "nothing was finalized" in str(exc), exc
assert not (usd / "asset/v003/version.json").exists()
assert "@./v002/hero_asset_v002.usd@" in (usd / "asset/asset.usd").read_text(encoding="utf-8")
lop.parm("version").set(2)

# --- sw_render: Karma, one .exr per frame
cam = stage.createNode("camera")
cam.setInput(0, stage.createNode("sphere"))
cam.parmTuple("t").set((0, 0, 5))
settings = stage.createNode("karmarenderproperties")
settings.setInput(0, cam)
render = create(stage, "sw_render", settings)
assert render.evalParm("render_name") == "" and render.parm("range").evalAsString() == "shot"
# render settings and pass come from the stage; the ROP points at them
rop = render.node("render")
assert render.evalParm("rendersettings") == ""  # automatic: the stage's own settings
assert "/Render/rendersettings" in render.parm("rendersettings").menuItems()
assert rop.evalParm("rendersettings") == "/Render/rendersettings"
named = stage.createNode("karmarenderproperties")  # any prim name, e.g. the node's
named.setInput(0, cam)
named.parm("primpath").set("/Render/karmarendersettings")
render.setInput(0, named)
assert rop.evalParm("rendersettings") == "/Render/karmarendersettings"
render.setInput(0, settings)
assert render.parm("renderpass").menuItems()[0] == "" and rop.evalParm("renderpass") == ""
# the engine follows the settings prim: the ROP's delegate decides what husk runs
assert rop.evalParm("renderer") == "BRAY_HdKarma"
settings.parm("engine").set("xpu")
assert rop.evalParm("renderer") == "BRAY_HdKarmaXPU", rop.evalParm("renderer")
settings.parm("engine").set("cpu")
assert rop.evalParm("renderer") == "BRAY_HdKarma"
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
assert lop_cache.evalParm("rootprim") == "/look"  # a part: a prim of its own, /<name>
assert "prims outside /look: /sphere1" in lop_cache.evalParm("info"), lop_cache.evalParm("info")
lop_cache.parm("rootprim").set("/sphere1")
assert "outside" not in lop_cache.evalParm("info"), lop_cache.evalParm("info")
lop_cache.parm("load").set(1)
assert lop_cache.node("load_from_disk").evalParm("input") == 2  # referenced, not stacked
ref = lop_cache.stage().GetPrimAtPath("/sphere1")
assert ref.GetTypeName() == "Sphere", "the cache is loaded back"
arcs = [a for s in ref.GetPrimStack() for a in s.referenceList.GetAddedOrExplicitItems()]
assert arcs and arcs[0].primPath == "/sphere1", arcs

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
# v003 is the failed export from above: there, but never finalized or made current
assert il.parm("version").menuItems()[:4] == ("current", "v003", "v002", "v001")
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
assert start.evalParm("renderproxy") == 1, "on by default for the scene's asset"
start.parm("renderproxy").set(0)  # an asset without a proxy
assert not start.stage().GetPrimAtPath("/hero/geo/render")
assert start.stage().GetPrimAtPath("/hero/geo").GetTypeName() == "Scope"
start.parm("renderproxy").revertToDefaults()
assert start.stage().GetPrimAtPath("/hero/geo/proxy")
body = stage.createNode("sphere")
body.setInput(0, start)
body.parm("primpath").set("/hero/geo/render/body")
pub_geo = create(stage, "sw_publish_lop", body)
pub_geo.parm("layer").set("geo")  # geo/v001 exists from above: Publish All makes v002
assert pub_geo.node("layer_break_after").evalParm("input") == 1, "a layer always breaks"
assert "Warning" not in pub_geo.evalParm("info")
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
assert loaded == [
    "Frames: 1001-1002",
    "Loaded (strongest first):",
    "shared/usd/structure.usd",
], loaded
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
pub_lgt.parm("layer").set("light")  # not in usd_layer_order: would sort below layout
assert "light isn't in usd_layer_order" in pub_lgt.evalParm("info"), pub_lgt.evalParm("info")
pub_lgt.parm("layer").set("lgt")
assert "usd_layer_order" not in pub_lgt.evalParm("info")
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

# --- parts: USD products, published on their own, referenced into a layer -------------
# at 25 fps (the shot's entity.json override): every layer written must carry it
write_json(shot.path / "entity.json", {**read_json(shot.path / "entity.json"), "fps": 25})
sw.set_fps(25)
# the part is built under a prim of its own, /terrain_base/{mesh,material}
terrain = stage.createNode("cube")
terrain.setInput(0, main_start)  # built on Shot Start, like any part
terrain.parm("primpath").set("/terrain_base/mesh")
material = stage.createNode("primitive")
material.setInput(0, terrain)
material.parm("primpath").set("/terrain_base/material")
material.parm("primtype").set("UsdGeomScope")
part = create(stage, "sw_publish_lop", material)
part.parm("target").set("product")
part.parm("layer").set("terrain_base")
assert part.evalParm("rootprim") == "/terrain_base"  # default: a prim of its own
assert part.evalParm("layer_break") == 0, "a part merges into a layer: no break by default"
assert part.node("layer_break_after").evalParm("input") == 0
info = part.evalParm("info")
assert info.startswith("Product  terrain_base") and "Warning" not in info, info
stray = stage.createNode("cube")
stray.setInput(0, material)
stray.parm("primpath").set("/world/props/stray")
part.setInput(0, stray)
assert "prims outside /terrain_base: /world" in part.evalParm("info"), part.evalParm("info")
part.setInput(0, material)
part.parm("execute").pressButton()
part_dir = shot.path / "publish/terrain_base/v001"
part_file = part_dir / "sq010_0010_terrain_base_v001.usd"
assert names(part_dir) == [part_file.name, "version.json"]
part_layer = Sdf.Layer.FindOrOpen(str(part_file))
assert (part_layer.framesPerSecond, part_layer.timeCodesPerSecond) == (25, 25)
assert part_layer.defaultPrim == "terrain_base"  # referenced without a prim path too
assert [str(x.path) for x in part_layer.rootPrims if x.name != "HoudiniLayerInfo"] == [
    "/terrain_base"
], "only the part: Shot Start's layers stay out"
assert not (shot_usd / "terrain_base").exists()  # no pointer, not in the root layer
assert "terrain_base" not in (shot_usd / "sq010_0010.usd").read_text(encoding="utf-8")
(shot.path / "publish/plate_ref/v001").mkdir(parents=True)  # a non-USD product
(shot.path / "publish/plate_ref/v001/sq010_0010_plate_ref_v001.abc").write_bytes(b"")
items = part.parm("layer").menuItems()  # the shot's USD products, not layers or hints
assert "terrain_base" in items and "layout" not in items and "lgt" not in items, items
assert "plate_ref" not in items, items
# Load from Disk: the layers below behind a break, the part referenced on top
part.parm("load").set(1)
assert part.node("load_from_disk").evalParm("input") == 2
loaded = part.stage()
assert loaded.GetPrimAtPath("/terrain_base/mesh").GetTypeName() == "Cube"
assert loaded.GetPrimAtPath("/world/chars"), "the layers below are there to look at"
part.parm("layer_break").set(1)
assert part.node("layer_break_after").evalParm("input") == 1
part.parm("layer_break").set(0)
# grafted under /world/env into the layout: one reference arc, nothing below, the fps
graft = stage.createNode("graftbranches")
graft.setInput(0, main_start)
graft.setInput(1, part)
graft.parm("primpath").set("/world/env")
graft.parm("srcprimpath1").set("/terrain_base")
pub_layout2 = create(stage, "sw_publish_lop", graft)
pub_layout2.parm("layer").set("layout")
assert "Warning" not in pub_layout2.evalParm("info"), pub_layout2.evalParm("info")
pub_layout2.parm("new_version").pressButton()
pub_layout2.parm("execute").pressButton()
layout2 = Sdf.Layer.FindOrOpen(str(shot_usd / "layout/v002/sq010_0010_layout_v002.usd"))
assert list(layout2.subLayerPaths) == [], list(layout2.subLayerPaths)
spec = layout2.GetPrimAtPath("/world/env/terrain_base")
arcs = [(a.assetPath, str(a.primPath)) for a in spec.referenceList.GetAddedOrExplicitItems()]
expected = "../../../terrain_base/v001/sq010_0010_terrain_base_v001.usd"
assert arcs == [(expected, "/terrain_base")], arcs
assert not layout2.GetPrimAtPath("/world/env/terrain_base/mesh"), "referenced, not copied"
assert not layout2.GetPrimAtPath("/world/fx"), "Shot Start's layers stay out"
assert (layout2.framesPerSecond, layout2.timeCodesPerSecond) == (25, 25)
pointer = shot_usd / "layout/layout.usd"
assert "./v002/" in pointer.read_text(encoding="utf-8")
Sdf.Layer.FindOrOpen(str(pointer)).Reload()  # this session opened it at v001 above
shot_stage = Usd.Stage.Open(str(shot_usd / "sq010_0010.usd"))
assert shot_stage.GetPrimAtPath("/world/env/terrain_base/mesh").GetTypeName() == "Cube"
assert shot_stage.GetPrimAtPath("/world/env/terrain_base/material")

# SOP Create with Save Path into work/: the part would sublayer that file, so it refuses
soil = stage.createNode("sopcreate", "soil")
soil.node("sopnet/create").createNode("box").setDisplayFlag(True)
soil.parm("enable_savepath").set(1)
soil.parm("savepath").set((shot.path / "lgt/main/work/usd/soil.usd").as_posix())
soil_part = create(stage, "sw_publish_lop", soil)
soil_part.parm("target").set("product")
soil_part.parm("layer").set("soil")
info = soil_part.evalParm("info")
assert "unpublished" in info and "lgt/main/work/usd/soil.usd" in info, info
try:
    sw.publish_all_usd([(soil_part, 1)])
    raise AssertionError("a part that sublayers a work/ file must not publish")
except ScheinwerkError as exc:
    assert "work/usd/soil.usd" in str(exc), exc
assert not (shot.path / "publish/soil").exists()
# without Save Path, in any SOP Create mode: one file, the SOP layer flattened into it
soil.parm("enable_savepath").set(0)
for number, mode in enumerate(("merge", "off", "on"), start=1):
    soil.parm("copycontents").set(mode)  # merge / add as sublayer / copy into new layer
    soil_part.parm("version").set(number)
    sw.publish_all_usd([(soil_part, number)])
    folder = shot.path / f"publish/soil/v{number:03d}"
    main = f"sq010_0010_soil_v{number:03d}.usd"
    assert sorted(str(f.relative_to(folder)) for f in folder.rglob("*") if f.is_file()) == [
        main,
        "version.json",
    ], (mode, list(folder.rglob("*")))
    soil_layer = Sdf.Layer.FindOrOpen(str(folder / main))
    assert not list(soil_layer.subLayerPaths) and soil_layer.GetPrimAtPath("/soil"), mode

# a scatter of an asset's variants: Explore Variants (in its Explore Variants mode)
# references its input stage, which only exists in this scene. Refused before anything
# is written; Duplicate Variants copies them instead, and the part is one file.
variants_asset = tmp / "plant.usda"
variants_asset.write_text(
    """#usda 1.0
(
    defaultPrim = "plant"
)

def Xform "plant" (
    variants = {
        string model = "a"
    }
    prepend variantSets = "model"
)
{
    variantSet "model" = {
        "a" {
            def Cube "geo"
            {
            }

        }
        "b" {
            def Sphere "geo"
            {
            }

        }
    }
}
""",
    encoding="utf-8",
)
plant = stage.createNode("reference::2.0")
plant.parm("primpath1").set("/plant")
plant.parm("filepath1").set(variants_asset.as_posix())
explore = stage.createNode("explorevariants")
explore.setInput(0, plant)
explore.parm("primpattern").set("/plant")
explore.parm("mode").set("1")  # Explore Variants
spot = stage.createNode("cube")
spot.parm("primpath").set("/grass/spot")
scatter = stage.createNode("instancer")
scatter.setInput(0, spot)
scatter.setInput(1, explore)
scatter.parm("primpath").set("/grass/instances")
scatter.parm("transformsourcemode").set("prims")
scatter.parm("locationpattern").set("/grass/spot")
scatter.parm("protosourcemode").set("second")
scatter.parm("protopattern").set("/Variants")
grass = create(stage, "sw_publish_lop", scatter)
grass.parm("target").set("product")
grass.parm("layer").set("grass")
info = grass.evalParm("info")
assert "only exists in this scene" in info and "/grass/instances" in info, info
try:
    sw.publish_all_usd([(grass, 1)])
    raise AssertionError("a part referencing an in-memory layer must not publish")
except ScheinwerkError as exc:
    assert "only exists in this scene" in str(exc), exc
assert not (shot.path / "publish/grass").exists(), "refused before anything is written"
explore.parm("mode").set("0")  # Duplicate Variants: copies, each one referencing the file
explore.parm("primpath").set("/__variants")
scatter.parm("protopattern").set("/__variants/*/*")
assert "Warning" not in grass.evalParm("info"), grass.evalParm("info")
sw.publish_all_usd([(grass, 1)])
assert names(shot.path / "publish/grass/v001") == ["sq010_0010_grass_v001.usd", "version.json"]

# a task cache can be merged in to look at, but a published layer refuses it (spec §9.2)
rocks = stage.createNode("sphere")
rocks.parm("primpath").set("/rocks/geo")
cached = create(stage, "sw_publish_lop", rocks)
cached.parm("target").set("cache")
cached.parm("layer").set("rocks")
assert cached.evalParm("rootprim") == "/rocks"
cached.parm("execute").pressButton()
cached.parm("load").set(1)
merge2 = stage.createNode("merge")
merge2.setInput(0, main_start)
merge2.setInput(1, cached)
bad = create(stage, "sw_publish_lop", merge2)
bad.parm("layer").set("layout")
bad.parm("version").set(3)
info = bad.evalParm("info")
assert "unpublished" in info and "lgt/main/cache/rocks" in info, info
try:
    sw.publish_all_usd([(bad, 3)])
    raise AssertionError("a layer referencing a task cache must not publish")
except ScheinwerkError as exc:
    assert "cache/rocks" in str(exc), exc
assert not (shot_usd / "layout/v003").exists()

# --- Asset Start in a shot: a named component to build a part in -------------------------
comp = stage.createNode("sw_asset_start", exact_type_name=True)
assert comp.parm("mode").evalAsString() == "asset"  # the default: the scene's asset
comp.parm("mode").set("component")
comp.parm("mode").pressButton()  # runs the callback, as choosing from the menu does
comp.parm("name").set("rock")
s = comp.stage()
rock = s.GetPrimAtPath("/rock")
assert rock.GetTypeName() == "Xform" and Usd.ModelAPI(rock).GetKind() == "component"
for scope in ("/rock/geo", "/rock/mtl"):
    assert s.GetPrimAtPath(scope).GetTypeName() == "Scope", scope
assert comp.evalParm("renderproxy") == 0, "off by default for a component"
assert not s.GetPrimAtPath("/rock/geo/render"), "render and proxy are optional, off"
comp.parm("renderproxy").set(1)
s = comp.stage()
for purpose in ("render", "proxy"):
    prim = s.GetPrimAtPath(f"/rock/geo/{purpose}")
    assert prim.GetTypeName() == "Scope", purpose
    assert UsdGeom.Imageable(prim).GetPurposeAttr().Get() == purpose, purpose

# --- Shot Start sets the shot's frame range on the stage (drives the playbar with
# Houdini's Stage Frame Range Drives Playbar), one range per shot branch of a _seq scene
project.create_shot("sq010_0030", frames=(1101, 1150))
project.create_shot("sq010_0040")  # no frames
hou.hipFile.clear(suppress_save_prompt=True)
hou.hipFile.save(
    (project.root / "shots/sq010/_seq/lgt/main/work/sq010_lgt_main_v002.hip").as_posix()
)
stage = hou.node("/stage")
branches = {}
for name in ("sq010_0010", "sq010_0030", "sq010_0040", "_seq"):
    start = stage.createNode("sw_shot_start", exact_type_name=True)
    start.parm("shot").set(name)
    edit = stage.createNode("sphere")
    edit.setInput(0, start)
    edit.parm("primpath").set(f"/world/fx/{name.strip('_')}")
    branches[name] = edit
s = branches["sq010_0010"].stage()
assert (s.GetStartTimeCode(), s.GetEndTimeCode()) == (1001, 1002), "the shot's frames"
s = branches["sq010_0030"].stage()
assert (s.GetStartTimeCode(), s.GetEndTimeCode()) == (1101, 1150), "its own branch, own range"
assert "Frames: 1101-1150" in branches["sq010_0030"].input(0).evalParm("info")
s = branches["sq010_0040"].stage()
assert not s.GetRootLayer().HasStartTimeCode(), "a shot without frames sets none"
assert "Frames: none set" in branches["sq010_0040"].input(0).evalParm("info")
s = branches["_seq"].stage()
assert (s.GetStartTimeCode(), s.GetEndTimeCode()) == (1001, 1150), "the sequence: all shots"
pick = stage.createNode("switch")
pick.setInput(0, branches["sq010_0010"])
pick.setInput(1, branches["sq010_0030"])
pick.parm("input").set(1)
assert pick.stage().GetStartTimeCode() == 1101, "a Switch passes the chosen shot's range"
# the range sits behind the Layer Break: a publish writes only its own render range
pub = create(stage, "sw_publish_lop", branches["sq010_0030"])
pub.parm("shot").set("sq010_0030")
pub.parm("layer").set("fx")
pub.parm("execute").pressButton()
fx = Sdf.Layer.FindOrOpen(
    str(project.root / "shots/sq010/sq010_0030/publish/_usd/fx/v001/sq010_0030_fx_v001.usd")
)
assert fx.GetPrimAtPath("/world/fx/sq010_0030") and not fx.GetPrimAtPath("/world/fx/sq010_0010")

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

# every Scheinwerk HDA is put down orange (the UI's colour) as a cloud
sop_net = hou.node("/obj").createNode("geo")
for category, type_name in (
    (sop_net, "sw_publish_sop"),
    (sop_net, "sw_import_sop"),
    (stage, "sw_publish_lop"),
    (stage, "sw_asset_start"),
    (stage, "sw_shot_start"),
    (stage, "sw_render"),
    (stage, "sw_import_lop"),
):
    node = category.createNode(type_name, exact_type_name=True)
    rgb = tuple(round(c, 3) for c in node.color().rgb())
    assert rgb == (1.0, 0.416, 0.0), (type_name, rgb)
    assert node.userData("nodeshape") == "cloud", (type_name, node.userData("nodeshape"))

print("ALL OK", hou.applicationVersionString())
