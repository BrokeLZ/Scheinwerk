"""Publishing, finalize, pointers and ingest (spec §8.3, §9)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from scheinwerk.core.entities import Entity
from scheinwerk.core.errors import NotFound, NotInProject, ParseError, ScheinwerkError
from scheinwerk.core.project import Project
from scheinwerk.core.publish import (
    finalize,
    ingest,
    next_media,
    next_publish,
    next_usd,
    set_current,
)
from scheinwerk.core.usd_pointer import STRUCTURE
from scheinwerk.core.versions import Product
from tests.conftest import touch


@pytest.fixture
def hero(proj: Project) -> Entity:
    return proj.create_asset("hero")


@pytest.fixture
def shot(proj: Project) -> Entity:
    return proj.create_shot("sq010_0010", frames=(1001, 1096))


def info(version_dir: Path) -> dict:
    return json.loads((version_dir / "version.json").read_text(encoding="utf-8"))


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- next_* -----------------------------------------------------------------


def test_next_publish(hero: Entity) -> None:
    assert next_publish(hero, "pants") == hero.path / "publish/pants/v001"
    assert next_publish(hero, "pants") == hero.path / "publish/pants/v002"
    assert (hero.path / "publish/pants/v002").is_dir()


def test_next_media_and_usd(hero: Entity, shot: Entity) -> None:
    assert next_media(shot, "render_beauty") == shot.path / "media/render_beauty/v001"
    assert next_usd(hero, "geo") == hero.path / "publish/_usd/geo/v001"


def test_next_publish_invalid_name(hero: Entity) -> None:
    with pytest.raises(ScheinwerkError):
        next_publish(hero, "Pants Final")


# --- finalize ---------------------------------------------------------------


def test_finalize_writes_version_json(proj: Project, hero: Entity) -> None:
    vdir = next_publish(hero, "pants")
    touch(vdir / "hero_pants_v001.abc")
    src = hero.path / "mdl/main/work/hero_mdl_main_v003.hip"
    finalize(vdir, source=src, comment="first", dcc="houdini")
    data = info(vdir)
    assert list(data) == ["schema", "source", "dept", "task", "dcc", "user", "created", "comment"]
    assert data["schema"] == 1
    assert data["source"] == "assets/hero/mdl/main/work/hero_mdl_main_v003.hip"
    assert (data["dept"], data["task"], data["dcc"], data["comment"]) == (
        "mdl",
        "main",
        "houdini",
        "first",
    )
    assert isinstance(data["user"], str)
    assert datetime.fromisoformat(data["created"]).utcoffset() is not None


def test_finalize_minimal(hero: Entity) -> None:
    vdir = next_publish(hero, "pants")
    finalize(vdir)
    assert set(info(vdir)) == {"schema", "user", "created", "comment"}


def test_finalize_source_outside_project(tmp_path: Path, hero: Entity) -> None:
    vdir = next_publish(hero, "pants")
    with pytest.raises(NotInProject):
        finalize(vdir, source=tmp_path / "downloads/x.hip")
    assert not (vdir / "version.json").exists()


def test_refinalize_keeps_created_source_and_unknown_keys(hero: Entity) -> None:
    vdir = next_publish(hero, "pants")
    finalize(vdir, source=hero.path / "mdl/main/work/hero_mdl_main_v003.hip", comment="a")
    data = info(vdir)
    data["created"] = "2026-01-01T10:00:00+01:00"
    data["custom"] = 42
    (vdir / "version.json").write_text(json.dumps(data), encoding="utf-8")
    finalize(vdir, comment="edited")
    after = info(vdir)
    assert after["comment"] == "edited"
    assert after["created"] == "2026-01-01T10:00:00+01:00"
    assert after["source"] == data["source"]
    assert after["custom"] == 42


@pytest.mark.parametrize(
    "rel",
    [
        "assets/hero/publish/pants",  # product, not a version
        "assets/hero/mdl/main/work/hero_mdl_main_v001.hip",
        "assets/hero/publish/pants/v001/x.abc",
    ],
)
def test_finalize_needs_a_version_folder(proj: Project, hero: Entity, rel: str) -> None:
    touch(proj.root / "assets/hero/publish/pants/v001/x.abc")
    with pytest.raises(ParseError):
        finalize(proj.root / rel)


def test_finalize_missing_folder(hero: Entity) -> None:
    with pytest.raises(NotFound):
        finalize(hero.path / "publish/pants/v007")


# --- USD --------------------------------------------------------------------

STRUCTURE_REL = "../../../../../shared/usd/structure.usd"


def publish_layer(entity: Entity, layer: str, files: tuple[str, ...] | None = None) -> Path:
    vdir = next_usd(entity, layer)
    for name in files or (f"{entity.name}_{layer}_{vdir.name}.usd",):
        touch(vdir / name)
    return vdir


def test_usd_finalize_writes_pointer_payload_and_component(hero: Entity) -> None:
    vdir = publish_layer(hero, "geo")
    finalize(vdir)
    usd = hero.path / "publish/_usd"
    assert text(usd / "geo/geo.usd") == (
        '#usda 1.0\n(\n    defaultPrim = "hero"\n'
        "    framesPerSecond = 24\n    timeCodesPerSecond = 24\n"
        "    subLayers = [@./v001/hero_geo_v001.usd@]\n)\n"
    )
    assert text(usd / "payload.usd") == (
        "#usda 1.0\n(\n    framesPerSecond = 24\n    timeCodesPerSecond = 24\n"
        "    subLayers = [\n        @./geo/geo.usd@\n    ]\n)\n"
    )
    entry = text(usd / "hero.usd")
    assert entry.startswith('#usda 1.0\n(\n    defaultPrim = "hero"\n')
    assert 'kind = "component"' in entry
    assert "payload = @./payload.usd@</hero>" in entry
    assert "subLayers" not in entry
    assert info(vdir)["schema"] == 1


def test_new_version_moves_the_pointer(proj: Project, hero: Entity) -> None:
    finalize(publish_layer(hero, "geo"))
    finalize(publish_layer(hero, "geo"))
    layer = Product(proj, hero.path / "publish/_usd/geo")
    assert layer.current().number == 2


def test_asset_layer_order(hero: Entity) -> None:
    # mtl, then geo, then any other asset layer A-Z (spec §9.3); usd_layer_order is ignored.
    for layer in ["fx", "geo", "cfx", "mtl", "lgt"]:
        finalize(publish_layer(hero, layer))
    payload = text(hero.path / "publish/_usd/payload.usd")
    order = ["./mtl/", "./geo/", "./cfx/", "./fx/", "./lgt/"]
    assert [payload.index(o) for o in order] == sorted(payload.index(o) for o in order)


def test_shot_root_layer(proj: Project, shot: Entity) -> None:
    # usd_layer_order = lgt, fx, anim, layout; others after it A-Z; structure last.
    for layer in ["layout", "zzz", "lgt", "cfx", "fx"]:
        finalize(publish_layer(shot, layer))
    usd = shot.path / "publish/_usd"
    assert text(usd / "sq010_0010.usd") == (
        "#usda 1.0\n(\n"
        "    framesPerSecond = 24\n    timeCodesPerSecond = 24\n"
        "    startTimeCode = 1001\n    endTimeCode = 1096\n"
        "    subLayers = [\n"
        "        @./lgt/lgt.usd@,\n"
        "        @./fx/fx.usd@,\n"
        "        @./layout/layout.usd@,\n"
        "        @./cfx/cfx.usd@,\n"
        "        @./zzz/zzz.usd@,\n"
        f"        @{STRUCTURE_REL}@\n"
        "    ]\n)\n"
    )
    assert "defaultPrim" not in text(usd / "lgt/lgt.usd")
    assert (usd / STRUCTURE_REL).resolve() == (proj.root / "shared/usd/structure.usd").resolve()


def test_root_layer_writes_a_missing_structure_layer(proj: Project, shot: Entity) -> None:
    structure = proj.root / "shared/usd/structure.usd"
    assert not structure.exists()  # an older project
    finalize(publish_layer(shot, "lgt"))
    assert text(structure) == STRUCTURE
    structure.write_text("#usda 1.0\n# mine\n", encoding="utf-8")
    finalize(publish_layer(shot, "lgt"))
    assert text(structure) == "#usda 1.0\n# mine\n"  # never overwritten


def test_shot_without_frames_has_no_time_range(proj: Project) -> None:
    shot = proj.create_shot("sq020_0010")
    finalize(publish_layer(shot, "lgt"))
    root = text(shot.path / "publish/_usd/sq020_0010.usd")
    assert "framesPerSecond = 24" in root
    assert "TimeCode =" not in root


def test_sequence_root_layer(proj: Project) -> None:
    seq = proj.create_sequence("sq010")
    finalize(publish_layer(seq, "lgt"))
    usd = proj.root / "shots/sq010/_seq/publish/_usd"
    assert "subLayers = [@./v001/sq010_lgt_v001.usd@]" in text(usd / "lgt/lgt.usd")
    assert "defaultPrim" not in text(usd / "lgt/lgt.usd")
    assert text(usd / "sq010.usd") == (
        "#usda 1.0\n(\n    framesPerSecond = 24\n    timeCodesPerSecond = 24\n"
        "    subLayers = [\n"
        "        @./lgt/lgt.usd@,\n"
        f"        @{STRUCTURE_REL}@\n"
        "    ]\n)\n"
    )


def test_new_sequence_root_is_added_to_shot_roots(proj: Project, shot: Entity) -> None:
    other = proj.create_shot("sq010_0020")  # never published: gets no root layer
    finalize(publish_layer(shot, "lgt"))
    root = shot.path / "publish/_usd/sq010_0010.usd"
    assert STRUCTURE_REL in text(root)
    finalize(publish_layer(proj.entity("seq:sq010"), "layout"))
    assert text(root).endswith(
        "        @./lgt/lgt.usd@,\n        @../../../_seq/publish/_usd/sq010.usd@\n    ]\n)\n"
    )
    assert STRUCTURE_REL not in text(root)  # the sequence root layer brings it
    assert not (other.path / "publish/_usd/sq010_0020.usd").exists()


def test_layers_use_the_entity_fps(proj: Project, hero: Entity, shot: Entity) -> None:
    data = json.loads(text(shot.path / "entity.json"))
    (shot.path / "entity.json").write_text(json.dumps({**data, "fps": 23.976}), encoding="utf-8")
    finalize(publish_layer(shot, "lgt"))
    finalize(publish_layer(hero, "geo"))
    for path in [shot.path / "publish/_usd/lgt/lgt.usd", shot.path / "publish/_usd/sq010_0010.usd"]:
        assert "    framesPerSecond = 23.976\n    timeCodesPerSecond = 23.976\n" in text(path)
    for name in ["geo/geo.usd", "payload.usd", "hero.usd"]:
        assert "    timeCodesPerSecond = 24\n" in text(hero.path / "publish/_usd" / name)


def test_project_fps(tmp_path: Path) -> None:
    p = Project.create(tmp_path / "show", "show", fps=25)
    seq = p.create_sequence("sq010")
    finalize(publish_layer(seq, "lgt"))
    assert "timeCodesPerSecond = 25" in text(seq.path / "publish/_usd/sq010.usd")


def test_set_frames_rewrites_the_shot_root_layer(proj: Project, shot: Entity) -> None:
    unpublished = proj.create_shot("sq010_0020")
    unpublished.set_frames(1001, 1010)
    assert not (unpublished.path / "publish").exists()
    finalize(publish_layer(shot, "lgt"))
    shot.set_frames(1001, 1050)
    assert "    startTimeCode = 1001\n    endTimeCode = 1050\n" in text(
        shot.path / "publish/_usd/sq010_0010.usd"
    )


def test_main_file_prefers_recommended_name(hero: Entity) -> None:
    vdir = publish_layer(hero, "geo", ("a.usd", "hero_geo_v001.usd", "hero_geo_v001.1001.usd"))
    finalize(vdir)
    assert "@./v001/hero_geo_v001.usd@" in text(hero.path / "publish/_usd/geo/geo.usd")


@pytest.mark.parametrize("name", ["layer.usda", "layer.usdc"])
def test_single_usd_file_any_suffix(hero: Entity, name: str) -> None:
    finalize(publish_layer(hero, "geo", (name,)))
    assert f"@./v001/{name}@" in text(hero.path / "publish/_usd/geo/geo.usd")


def test_ambiguous_main_file_writes_nothing(hero: Entity) -> None:
    vdir = publish_layer(hero, "geo", ("a.usd", "b.usd"))
    with pytest.raises(ScheinwerkError, match="main_file"):
        finalize(vdir)
    assert not (vdir / "version.json").exists()
    assert not (hero.path / "publish/_usd/geo/geo.usd").exists()
    assert not (hero.path / "publish/_usd/hero.usd").exists()
    finalize(vdir, main_file="b.usd")
    assert "@./v001/b.usd@" in text(hero.path / "publish/_usd/geo/geo.usd")


def test_main_file_missing(hero: Entity) -> None:
    vdir = publish_layer(hero, "geo", ("a.usd",))
    with pytest.raises(NotFound):
        finalize(vdir, main_file="nope.usd")


def test_no_usd_file(hero: Entity) -> None:
    vdir = publish_layer(hero, "geo", ("notes.txt",))
    with pytest.raises(NotFound):
        finalize(vdir)


def test_set_current_rolls_back(proj: Project, hero: Entity) -> None:
    v1 = publish_layer(hero, "geo")
    finalize(v1)
    finalize(publish_layer(hero, "geo"))
    set_current(v1)
    layer = Product(proj, hero.path / "publish/_usd/geo")
    assert layer.current().number == 1
    assert "@./geo/geo.usd@" in text(hero.path / "publish/_usd/payload.usd")


def test_set_current_needs_usd(hero: Entity) -> None:
    vdir = next_publish(hero, "pants")
    with pytest.raises(ParseError):
        set_current(vdir)


# --- usd_files (renders, spec §8.3) ------------------------------------------


def test_finalize_records_usd_files(proj: Project, hero: Entity, shot: Entity) -> None:
    geo = publish_layer(hero, "geo")
    lgt = publish_layer(shot, "lgt")
    vdir = next_media(shot, "render_beauty")
    used = [lgt / "sq010_0010_lgt_v001.usd", geo / "hero_geo_v001.usd", geo / "hero_geo_v001.usd"]
    finalize(vdir, usd_files=used)
    assert info(vdir)["usd_files"] == [
        "assets/hero/publish/_usd/geo/v001/hero_geo_v001.usd",
        "shots/sq010/sq010_0010/publish/_usd/lgt/v001/sq010_0010_lgt_v001.usd",
    ]
    finalize(vdir, comment="edited")  # re-finalizing without usd_files keeps them
    assert len(info(vdir)["usd_files"]) == 2
    finalize(vdir, usd_files=[])
    assert info(vdir)["usd_files"] == []


def test_usd_files_outside_the_project_are_refused(tmp_path: Path, shot: Entity) -> None:
    vdir = next_media(shot, "render_beauty")
    with pytest.raises(NotInProject):
        finalize(vdir, usd_files=[tmp_path / "elsewhere/x.usd"])
    assert not (vdir / "version.json").exists()


# --- ingest -----------------------------------------------------------------


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    folder = tmp_path / "downloads"
    touch(folder / "scene.HIP", b"hip")
    touch(folder / "comp.nk", b"nk")
    touch(folder / "noext", b"?")
    touch(folder / "a/plate.exr", b"a")
    touch(folder / "b/plate.exr", b"b")
    touch(folder / "ref.jpg", b"jpg")
    return folder


def test_ingest_into_task_one_version_each(hero: Entity, downloads: Path) -> None:
    task = hero.create_department("mdl").tasks()[0]
    touch(task.work_dir / "hero_mdl_main_v003.hip")
    new = ingest([downloads / "scene.HIP", downloads / "comp.nk"], task)
    assert [p.name for p in new] == ["hero_mdl_main_v004.hip", "hero_mdl_main_v005.nk"]
    assert new[0].read_bytes() == b"hip"
    assert (downloads / "scene.HIP").exists()  # copied, never moved


def test_ingest_into_product_one_version(proj: Project, hero: Entity, downloads: Path) -> None:
    product = Product(proj, hero.path / "publish/ref")
    new = ingest([downloads / "ref.jpg", downloads / "a/plate.exr"], product)
    assert new == [product.path / "v001/ref.jpg", product.path / "v001/plate.exr"]
    assert (downloads / "ref.jpg").exists()


def test_ingest_into_media(proj: Project, shot: Entity, downloads: Path) -> None:
    media = Product(proj, shot.path / "media/plate")
    assert ingest([downloads / "a/plate.exr"], media) == [media.path / "v001/plate.exr"]


def test_ingest_checks_everything_before_copying(
    proj: Project, hero: Entity, downloads: Path
) -> None:
    task = hero.create_department("mdl").tasks()[0]
    with pytest.raises(ScheinwerkError, match="extension"):
        ingest([downloads / "comp.nk", downloads / "noext"], task)
    assert task.workfiles() == []
    product = Product(proj, hero.path / "publish/plates")
    with pytest.raises(ScheinwerkError, match="plate.exr"):
        ingest([downloads / "a/plate.exr", downloads / "b/plate.exr"], product)
    assert not product.path.exists()


def test_ingest_rejects_missing_files_and_folders(hero: Entity, downloads: Path) -> None:
    task = hero.create_department("mdl").tasks()[0]
    with pytest.raises(NotFound):
        ingest([downloads / "ghost.hip"], task)
    with pytest.raises(ScheinwerkError, match="folder"):
        ingest([downloads / "a"], task)
