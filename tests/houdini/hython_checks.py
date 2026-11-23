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
        if isinstance(value, int):
            group.append(hou.IntParmTemplate(name, name, 1, default_value=(value,)))
        else:
            group.append(hou.StringParmTemplate(name, name, 1, default_value=(value,)))
    node.setParmTemplateGroup(group)
    return node


sop = node_with(
    {
        "product": "fx_sim",
        "ext": "bgeo.sc",
        "frames": 1,
        "version": 0,
        "comment": "first",
        "shot": "",
    }
)
assert sw.hda_output(sop).endswith("fx_sim/v001/hero_fx_sim_v001.1001.bgeo.sc")
sw.hda_new_version(sop)
sw.hda_new_version(sop)
assert sop.evalParm("version") == 2
out = Path(sw.hda_output(sop))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b"")
assert sop.parm("comment") is not None
sw.hda_post_render(sop)
info = json.loads((out.parent / "version.json").read_text(encoding="utf-8"))
assert info["comment"] == "first" and info["dcc"] == "houdini", info
assert info["source"] == "assets/char/hero/mdl/main/work/hero_mdl_main_v002.hip", info

lop = node_with({"layer": "asset", "version": 0, "comment": "look", "shot": ""})
sw.hda_new_version(lop)
usd = Path(sw.hda_output(lop))
assert usd.name == "hero_asset_v001.usd", usd
usd.write_text("#usda 1.0\n", encoding="utf-8")
sw.hda_post_render(lop)
pointer = (hero.path / "publish/_usd/asset/asset.usd").read_text(encoding="utf-8")
assert "@./v001/hero_asset_v001.usd@" in pointer, pointer

render = node_with({"render_name": "beauty", "version": 0, "comment": "", "shot": ""})
assert sw.hda_output(render).endswith("media/render_beauty/v001/hero_render_beauty_v001.1001.exr")

# --- a sequence scene publishing to shots -----------------------------------------
seq_work = root / "shots/sq010/_seq/lgt/main/work"
hou.hipFile.save(str(seq_work / "sq010_lgt_main_v001.hip"))
assert os.environ["SW_ENTITY_TYPE"] == "sequence" and os.environ["SW_SEQ"] == "sq010"
assert sw.shots() == [("sq010_0010", (1001, 1010)), ("sq010_0020", (1011, 1020))]
assert sw.shot_menu()[2:4] == ["sq010_0010", "sq010_0010  1001-1010"]
try:
    sw.publish_path("cam", "abc")
    raise AssertionError("a sequence scene needs a shot")
except sw.ScheinwerkError:
    pass
sw.set_shot("sq010_0020")
assert "/shots/sq010/sq010_0020/publish/cam/" in sw.publish_path("cam", "abc")
assert "/sq010_0010/" in sw.publish_path("cam", "abc", shot="sq010_0010")
shot_node = node_with({"layer": "lgt", "version": 0, "comment": "", "shot": "sq010_0010"})
assert "/sq010_0010/publish/_usd/lgt/v001/sq010_0010_lgt_v001.usd" in sw.hda_output(shot_node)
fx = next_usd(project.entity("sq010_0020"), "fx")
(fx / "sq010_0020_fx_v001.usd").write_text("#usda 1.0\n", encoding="utf-8")
finalize(fx)
assert sw.layers_below("lgt") == ["$JOB/shots/sq010/sq010_0020/publish/_usd/fx/fx.usd"]
assert sw.layers_below("layout") == []

# --- frame range and clearing ------------------------------------------------------
sw.set_frame_range((1011, 1020))
assert tuple(hou.playbar.frameRange()) == (1011, 1020)
hou.hipFile.clear(suppress_save_prompt=True)
assert os.environ["SW_ROOT"] == "" and sw.current_file() is None
assert sw.ADAPTER.current_file() is None and sw.ADAPTER.extensions == ("hip", "hipnc", "hiplc")

print("ALL OK", hou.applicationVersionString())
