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
    assert next_usd(hero, "asset") == hero.path / "publish/_usd/asset/v001"


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


def publish_layer(entity: Entity, layer: str, files: tuple[str, ...] | None = None) -> Path:
    vdir = next_usd(entity, layer)
    for name in files or (f"{entity.name}_{layer}_{vdir.name}.usd",):
        touch(vdir / name)
    return vdir


def test_usd_finalize_writes_pointer_and_entry_layer(hero: Entity) -> None:
    vdir = publish_layer(hero, "asset")
    finalize(vdir)
    usd = hero.path / "publish/_usd"
    assert text(usd / "asset/asset.usd") == (
        '#usda 1.0\n(\n    defaultPrim = "hero"\n'
        "    subLayers = [@./v001/hero_asset_v001.usd@]\n)\n"
    )
    assert text(usd / "hero.usd") == (
        '#usda 1.0\n(\n    defaultPrim = "hero"\n    subLayers = [\n'
        "        @./asset/asset.usd@\n    ]\n)\n"
    )
    assert info(vdir)["schema"] == 1


def test_new_version_moves_the_pointer(proj: Project, hero: Entity) -> None:
    finalize(publish_layer(hero, "asset"))
    finalize(publish_layer(hero, "asset"))
    layer = Product(proj, hero.path / "publish/_usd/asset")
    assert layer.current().number == 2


def test_shot_root_layer_order(shot: Entity) -> None:
    # usd_layer_order = lgt, fx, anim, layout; others after it A-Z.
    for layer in ["layout", "zzz", "lgt", "cfx", "fx"]:
        finalize(publish_layer(shot, layer))
    root = text(shot.path / "publish/_usd/sq010_0010.usd")
    assert "defaultPrim" not in root
    assert root == (
        "#usda 1.0\n(\n    subLayers = [\n"
        "        @./lgt/lgt.usd@,\n"
        "        @./fx/fx.usd@,\n"
        "        @./layout/layout.usd@,\n"
        "        @./cfx/cfx.usd@,\n"
        "        @./zzz/zzz.usd@\n"
        "    ]\n)\n"
    )


def test_asset_layers_use_the_same_order(hero: Entity) -> None:
    for layer in ["mtl", "geo", "fx"]:
        finalize(publish_layer(hero, layer))
    root = text(hero.path / "publish/_usd/hero.usd")
    assert root.index("./fx/") < root.index("./geo/") < root.index("./mtl/")


def test_sequence_root_layer(proj: Project) -> None:
    seq = proj.create_sequence("sq010")
    finalize(publish_layer(seq, "lgt"))
    usd = proj.root / "shots/sq010/_seq/publish/_usd"
    assert "subLayers = [@./v001/sq010_lgt_v001.usd@]" in text(usd / "lgt/lgt.usd")
    assert "defaultPrim" not in text(usd / "sq010.usd")


def test_main_file_prefers_recommended_name(hero: Entity) -> None:
    vdir = publish_layer(hero, "asset", ("geo.usd", "hero_asset_v001.usd", "mtl.usdc"))
    finalize(vdir)
    assert "@./v001/hero_asset_v001.usd@" in text(hero.path / "publish/_usd/asset/asset.usd")


@pytest.mark.parametrize("name", ["layer.usda", "layer.usdc"])
def test_single_usd_file_any_suffix(hero: Entity, name: str) -> None:
    finalize(publish_layer(hero, "asset", (name,)))
    assert f"@./v001/{name}@" in text(hero.path / "publish/_usd/asset/asset.usd")


def test_ambiguous_main_file_writes_nothing(hero: Entity) -> None:
    vdir = publish_layer(hero, "asset", ("a.usd", "b.usd"))
    with pytest.raises(ScheinwerkError, match="main_file"):
        finalize(vdir)
    assert not (vdir / "version.json").exists()
    assert not (hero.path / "publish/_usd/asset/asset.usd").exists()
    finalize(vdir, main_file="b.usd")
    assert "@./v001/b.usd@" in text(hero.path / "publish/_usd/asset/asset.usd")


def test_main_file_missing(hero: Entity) -> None:
    vdir = publish_layer(hero, "asset", ("a.usd",))
    with pytest.raises(NotFound):
        finalize(vdir, main_file="nope.usd")


def test_no_usd_file(hero: Entity) -> None:
    vdir = publish_layer(hero, "asset", ("notes.txt",))
    with pytest.raises(NotFound):
        finalize(vdir)


def test_set_current_rolls_back(proj: Project, hero: Entity) -> None:
    v1 = publish_layer(hero, "asset")
    finalize(v1)
    finalize(publish_layer(hero, "asset"))
    set_current(v1)
    layer = Product(proj, hero.path / "publish/_usd/asset")
    assert layer.current().number == 1
    assert "@./asset/asset.usd@" in text(hero.path / "publish/_usd/hero.usd")


def test_set_current_needs_usd(hero: Entity) -> None:
    vdir = next_publish(hero, "pants")
    with pytest.raises(ParseError):
        set_current(vdir)


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
