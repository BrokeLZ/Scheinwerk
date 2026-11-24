"""Runs inside hython (see test_houdini.py). Plain asserts; prints ALL OK at the end.

scheinwerk must come from the package (HOUDINI_PACKAGE_DIR), not from PYTHONPATH.
"""

import json
import os
import sys
from pathlib import Path

import hou

tmp = Path(sys.argv[1])
repo = Path(sys.argv[2])

# --- package and startup ---------------------------------------------------------
import scheinwerk.dcc.houdini as sw  # noqa: E402

assert Path(sw.__file__).resolve().is_relative_to(repo), sw.__file__
assert sw._started, "pythonrc.py didn't run"
assert any(Path(p).resolve() == repo / "integrations/houdini" for p in hou.houdiniPath()), (
    hou.houdiniPath()
)

from scheinwerk.core.project import Project  # noqa: E402
from scheinwerk.core.publish import finalize, next_usd  # noqa: E402

project = Project.create(tmp / "show", "show")
root = project.root
hero = project.create_asset("hero", category="char")
hero.create_department("mdl")
project.create_shot("sq010_0010", frames=(1001, 1010))
project.create_shot("sq010_0020", frames=(1011, 1020))
project.entity("sq010").create_department("lgt")
(root / "shared/hooks/log.py").write_text(
    "def post_save(path, context):\n"
    f"    open({str(tmp / 'hook.log')!r}, 'a').write(path.name + '\\n')\n",
    encoding="utf-8",
)

# --- environment on save / load ----------------------------------------------------
work = hero.path / "mdl/main/work"
hou.hipFile.save(str(work / "hero_mdl_main_v001.hip"))
assert os.environ["SW_ENTITY"] == "hero" and os.environ["SW_DEPT"] == "mdl"
assert os.environ["JOB"] == root.as_posix()
assert hou.text.expandString("$JOB") == root.as_posix()
assert hou.text.expandString("$SW_CACHE") == (work.parent / "cache").as_posix()

# --- save next version ------------------------------------------------------------
new = sw.save_next_version()
assert new == work / "hero_mdl_main_v002.hip" and new.is_file()
assert sw.current_file() == new
assert (tmp / "hook.log").read_text(encoding="utf-8") == "hero_mdl_main_v002.hip\n"
assert sw.context_path() == "assets/char/hero/mdl/main/work/hero_mdl_main_v002.hip"

# --- expression helpers ------------------------------------------------------------
assert sw.cache("sim") == (work.parent / "cache/sim").as_posix()
pants = hero.path / "publish/pants"
assert sw.publish_path("pants", "abc") == (pants / "v001/hero_pants_v001.abc").as_posix()
(pants / "v003").mkdir(parents=True)
assert sw.publish_path("pants", "abc").endswith("v003/hero_pants_v003.abc")
hou.setFrame(1001)
assert sw.publish_path("pants", "bgeo.sc", frames=True).endswith("hero_pants_v003.1001.bgeo.sc")
assert sw.media_path("render_beauty", "exr").endswith("v001/hero_render_beauty_v001.1001.exr")
assert sw.usd_path("asset").endswith("_usd/asset/v001/hero_asset_v001.usd")

# --- HDA functions, on nodes with the HDAs' parameters ------------------------------


def node_with(parms):
    node = hou.node("/obj").createNode("null")
    group = node.parmTemplateGroup()
    for name, value in parms.items():
        if isinstance(value, tuple):  # frame_range: frame_range1, frame_range2
            group.append(
                hou.IntParmTemplate(
                    name, name, 2, default_value=value, naming_scheme=hou.parmNamingScheme.Base1
                )
            )
        elif isinstance(value, int):
            group.append(hou.IntParmTemplate(name, name, 1, default_value=(value,)))
        else:
            group.append(hou.StringParmTemplate(name, name, 1, default_value=(value,)))
    node.setParmTemplateGroup(group)
    return node


sop = node_with(
    {
        "product": "fx_sim",
        "ext": "bgeo.sc",
        "range": sw.RANGE_SHOT,
        "frame_range": (1001, 1005),
        "version": 1,
        "comment": "first",
        "shot": "",
    }
)
assert sw.hda_output(sop).endswith("fx_sim/v001/hero_fx_sim_v001.1001.bgeo.sc")
fx_sim = hero.path / "publish/fx_sim"
sw.hda_new_version(sop)  # nothing on disk: 1, and New Version creates no folder
assert sop.evalParm("version") == 1 and not fx_sim.exists()
sw.hda_new_version(sop)  # still nothing on disk: still 1
assert sop.evalParm("version") == 1
(fx_sim / "v001").mkdir(parents=True)
(fx_sim / "v001/hero_fx_sim_v001.1001.bgeo.sc").write_bytes(b"")
sw.hda_new_version(sop)
assert sop.evalParm("version") == 2 and not (fx_sim / "v002").exists()
out = Path(sw.hda_output(sop))
out.parent.mkdir(parents=True, exist_ok=True)  # what Export does before the ROP runs
out.write_bytes(b"")
assert sop.parm("comment") is not None
sw.hda_post_render(sop)
info = json.loads((out.parent / "version.json").read_text(encoding="utf-8"))
assert info["comment"] == "first" and info["dcc"] == "houdini", info
assert info["source"] == "assets/char/hero/mdl/main/work/hero_mdl_main_v002.hip", info

# the Info box: latest version with its details, and what the node's version will do
text = sw.hda_info(sop)
assert "Latest   v002" in text and '"first"' in text and "hero_mdl_main_v002.hip" in text, text
assert "v002 exists (1 file): Export overwrites it" in text, text
sop.parm("version").set(3)
assert "v003 is new: Export creates it" in sw.hda_info(sop), sw.hda_info(sop)
sop.parm("version").set(2)
fresh = node_with({"product": "nothing_yet", "ext": "abc", "range": 0, "version": 1, "shot": ""})
assert "Latest   none yet" in sw.hda_info(fresh), sw.hda_info(fresh)

# name menu: existing products (no USD layers, no media); picking one sets its version
assert sw.hda_name_menu(sop) == ["fx_sim", "fx_sim", "pants", "pants"]
sop.parm("product").set("pants")
sw.hda_name_changed(sop)
assert sop.evalParm("version") == 3  # pants has an (empty) v003
sop.parm("product").set("brand_new")
sw.hda_name_changed(sop)
assert sop.evalParm("version") == 1
sop.parm("product").set("fx_sim")
sw.hda_name_changed(sop)
assert sop.evalParm("version") == 2

# frame range: current frame (one file, no frame number), shot range, custom range
playbar = tuple(int(f) for f in hou.playbar.frameRange())
assert sw.hda_range(sop) == playbar  # an asset without frames: the scene's range
sop.parm("range").set(sw.RANGE_CURRENT)
assert sw.hda_range(sop) == (1001, 1001)
assert sw.hda_output(sop).endswith("fx_sim/v002/hero_fx_sim_v002.bgeo.sc")
sop.parm("range").set(sw.RANGE_CUSTOM)
assert sw.hda_range(sop) == (1001, 1005)
assert sw.hda_output(sop).endswith("hero_fx_sim_v002.1001.bgeo.sc")

# no product (or an invalid one): nothing is reserved, written or finalized
for name in ("", "Bad Name"):
    blank = node_with({"product": name, "ext": "bgeo.sc", "range": 0, "version": 1, "shot": ""})
    for action in (sw.hda_output, sw.hda_new_version, sw.hda_execute, sw.hda_post_render):
        try:
            action(blank)
            raise AssertionError(f"{action.__name__} accepted product {name!r}")
        except sw.ScheinwerkError:
            pass
    assert sw.hda_name_menu(blank) == ["fx_sim", "fx_sim", "pants", "pants"]
    sw.hda_name_changed(blank)  # quietly does nothing
    assert "product" in sw.hda_info(blank)  # explains instead of raising
assert sorted(p.name for p in (hero.path / "publish").iterdir()) == ["fx_sim", "pants"]

# LOP: a range still writes one .usd (time samples); the Info box shows the pointer
lop = node_with(
    {
        "layer": "asset",
        "range": sw.RANGE_CUSTOM,
        "frame_range": (1001, 1005),
        "version": 1,
        "comment": "look",
        "shot": "",
    }
)
assert sw.hda_name_menu(lop) == []  # no USD layers yet
sw.hda_new_version(lop)
usd = Path(sw.hda_output(lop))
assert usd.name == "hero_asset_v001.usd", usd
assert sw.hda_range(lop) == (1001, 1005)
usd.parent.mkdir(parents=True)
usd.write_text("#usda 1.0\n", encoding="utf-8")
sw.hda_post_render(lop)
pointer = (hero.path / "publish/_usd/asset/asset.usd").read_text(encoding="utf-8")
assert "@./v001/hero_asset_v001.usd@" in pointer, pointer
assert sw.hda_name_menu(lop) == ["asset", "asset"]
assert "Current  v001" in sw.hda_info(lop) and "Layer    asset" in sw.hda_info(lop), sw.hda_info(
    lop
)
lop.parm("layer").set("lgt")
sw.hda_name_changed(lop)
assert lop.evalParm("version") == 1 and "Current  none" in sw.hda_info(lop), sw.hda_info(lop)

# render: always one file per frame, even for the current frame; menu without "render_"
render = node_with({"render_name": "beauty", "range": 0, "version": 1, "comment": "", "shot": ""})
assert sw.hda_output(render).endswith("media/render_beauty/v001/hero_render_beauty_v001.1001.exr")
(hero.path / "media/render_beauty/v001").mkdir(parents=True)
(hero.path / "media/playblast/v001").mkdir(parents=True)  # not a render: not in the menu
assert sw.hda_name_menu(render) == ["beauty", "beauty"]
assert "Media    render_beauty" in sw.hda_info(render), sw.hda_info(render)

# an empty layer or render name refuses everything too
for parms in ({"layer": ""}, {"render_name": ""}):
    blank = node_with({**parms, "range": 0, "version": 1, "shot": ""})
    for action in (sw.hda_output, sw.hda_new_version, sw.hda_execute, sw.hda_post_render):
        try:
            action(blank)
            raise AssertionError(f"{action.__name__} accepted {parms}")
        except sw.ScheinwerkError:
            pass

# --- a sequence scene publishing to shots -----------------------------------------
seq_work = root / "shots/sq010/_seq/lgt/main/work"
hou.hipFile.save(str(seq_work / "sq010_lgt_main_v001.hip"))
assert os.environ["SW_ENTITY_TYPE"] == "sequence" and os.environ["SW_SEQ"] == "sq010"
assert sw.shots() == [("sq010_0010", (1001, 1010)), ("sq010_0020", (1011, 1020))]
menu = sw.shot_menu()
assert menu[2:6] == ["_seq", "(the sequence itself)", "sq010_0010", "sq010_0010  1001-1010"]
try:
    sw.publish_path("cam", "abc")
    raise AssertionError("a sequence scene needs a shot")
except sw.ScheinwerkError:
    pass
sw.set_shot("sq010_0020")
assert "/shots/sq010/sq010_0020/publish/cam/" in sw.publish_path("cam", "abc")
assert "/sq010_0010/" in sw.publish_path("cam", "abc", shot="sq010_0010")
shot_node = node_with({"layer": "lgt", "range": 0, "version": 1, "shot": "sq010_0010"})
assert "/sq010_0010/publish/_usd/lgt/v001/sq010_0010_lgt_v001.usd" in sw.hda_output(shot_node)
shot_sop = node_with({"product": "cam", "ext": "abc", "range": 1, "version": 1, "shot": ""})
assert sw.hda_range(shot_sop) == (1011, 1020)  # the SW_SHOT option's shot (sq010_0020)
shot_sop.parm("shot").set("sq010_0010")
assert sw.hda_range(shot_sop) == (1001, 1010)
fx = next_usd(project.entity("sq010_0020"), "fx")
(fx / "sq010_0020_fx_v001.usd").write_text("#usda 1.0\n", encoding="utf-8")
finalize(fx)
assert not hasattr(sw, "layers_below")  # Shot Start loads layers (spec §13.2.8)

# _seq: the sequence itself, for sequence-wide products
assert sw.target_entity("_seq").type == "sequence"
assert "/shots/sq010/_seq/publish/rig/" in sw.publish_path("rig", "abc", shot="_seq")
seq_node = node_with({"layer": "lgt", "range": 0, "version": 1, "shot": "_seq"})
assert "/sq010/_seq/publish/_usd/lgt/v001/sq010_lgt_v001.usd" in sw.hda_output(seq_node)

# fps: the USD ROP writes the scene's fps, so a USD publish refuses a mismatch
assert sw.fps_matches(24) and not sw.fps_matches(25)
data = json.loads((project.root / "shots/sq010/sq010_0010/entity.json").read_text("utf-8"))
(project.root / "shots/sq010/sq010_0010/entity.json").write_text(
    json.dumps({**data, "fps": 25}), encoding="utf-8"
)
assert "set the scene to 25 fps" in sw._fps_problem(shot_node)
assert sw._fps_problem(seq_node) == ""  # the sequence keeps the project's 24
try:
    sw._export(shot_node)
    raise AssertionError("published with the wrong fps")
except sw.ScheinwerkError:
    pass
anim = hou.node("/obj").createNode("null")
anim.parm("tx").setKeyframe(hou.Keyframe(5, hou.frameToTime(1010)))
sw.set_fps(25)
assert hou.fps() == 25 and sw._fps_problem(shot_node) == ""
assert [round(hou.timeToFrame(k.time())) for k in anim.parm("tx").keyframes()] == [1010]
sw.set_fps(24)

# --- frame range and clearing ------------------------------------------------------
sw.set_frame_range((1011, 1020))
assert tuple(hou.playbar.frameRange()) == (1011, 1020)
hou.hipFile.clear(suppress_save_prompt=True)
assert os.environ["SW_ROOT"] == "" and sw.current_file() is None
assert sw.ADAPTER.current_file() is None and sw.ADAPTER.extensions == ("hip", "hipnc", "hiplc")

# --- the browser opens scenes in this session (spec §12.2) --------------------------
sw.ADAPTER.open(work / "hero_mdl_main_v001.hip")
assert sw.current_file() == work / "hero_mdl_main_v001.hip"
assert os.environ["SW_ENTITY"] == "hero"  # the load callback ran
assert sw.browser_widget  # the panel passes ADAPTER (gui needs Qt, checked in tests/gui)
try:
    sw.ADAPTER.open(work / "missing.hip")
    raise AssertionError("opened a missing file")
except sw.ScheinwerkError as exc:
    assert "missing.hip" in str(exc), exc

print("ALL OK", hou.applicationVersionString())
