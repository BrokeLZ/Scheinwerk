"""Products, USD layers, media and their v### folders (spec §5.4, §10)."""

from __future__ import annotations

import pytest

from scheinwerk.core.entities import Entity
from scheinwerk.core.errors import AlreadyExists, InvalidName
from scheinwerk.core.project import Project
from scheinwerk.core.versions import Product, file_sequences
from tests.conftest import touch


@pytest.fixture
def hero(proj: Project) -> Entity:
    return proj.create_asset("hero")


@pytest.fixture
def pants(proj: Project, hero: Entity) -> Product:
    return Product(proj, hero.path / "publish/pants")


def test_new_product_starts_at_v001(pants: Product) -> None:
    assert pants.versions() == []
    assert pants.latest() is None
    assert pants.next_version_dir() == pants.path / "v001"
    assert (pants.path / "v001").is_dir()


@pytest.mark.parametrize(
    ("have", "expected"),
    [
        (["v001", "v002"], "v003"),
        (["v001", "v005"], "v006"),  # gaps
        (["v999"], "v1000"),
        (["v1000"], "v1001"),
    ],
)
def test_next_version_dir(pants: Product, have: list[str], expected: str) -> None:
    for v in have:
        touch(pants.path / v / "x.abc")
    assert pants.next_version_dir().name == expected


def test_empty_folders_count_for_numbering_but_not_latest(pants: Product) -> None:
    touch(pants.path / "v001/x.abc")
    (pants.path / "v002").mkdir()
    touch(pants.path / "v003/version.json", b"{}")  # only version.json: still empty
    touch(pants.path / "v004/.DS_Store")  # only ignored files: still empty
    assert pants.latest().number == 1
    assert pants.next_version_dir().name == "v005"


def test_next_version_dir_skips_taken_names(pants: Product) -> None:
    # Another export grabbed v004 between scan and mkdir (here: a stray file).
    touch(pants.path / "v003/x.abc")
    touch(pants.path / "v004")
    assert pants.next_version_dir().name == "v005"


def test_versions_newest_first_and_only_version_folders(pants: Product) -> None:
    for v in ["v001", "v010", "v002"]:
        touch(pants.path / v / "x.abc")
    for other in ["latest", "v01", "backup"]:
        (pants.path / other).mkdir()
    touch(pants.path / "v003")  # a file, not a folder
    assert [v.number for v in pants.versions()] == [10, 2, 1]


def test_version_info_and_files(pants: Product) -> None:
    v = pants.path / "v001"
    touch(v / "b.abc")
    touch(v / "a.abc")
    touch(v / ".DS_Store")
    version = pants.versions()[0]
    assert version.info is None
    assert [p.name for p in version.files()] == ["a.abc", "b.abc"]
    touch(v / "version.json", b'{"schema": 1, "comment": "hi"}')
    assert version.info == {"schema": 1, "comment": "hi"}
    assert [p.name for p in version.files()] == ["a.abc", "b.abc"]
    touch(v / "version.json", b"{broken")
    assert version.info is None


@pytest.mark.parametrize("name", ["Pants", "_pants", "work"])
def test_invalid_product_name(proj: Project, hero: Entity, name: str) -> None:
    with pytest.raises(InvalidName):
        Product(proj, hero.path / "publish" / name).next_version_dir()


def test_kinds(proj: Project, hero: Entity) -> None:
    layer = Product(proj, hero.path / "publish/_usd/asset")
    media = Product(proj, hero.path / "media/turntable")
    pants = Product(proj, hero.path / "publish/pants")
    assert (layer.usd, layer.is_media, layer.pointer) == (True, False, layer.path / "asset.usd")
    assert (media.usd, media.is_media, media.pointer) == (False, True, None)
    assert (pants.usd, pants.is_media, pants.pointer) == (False, False, None)


def test_entity_products_and_media(hero: Entity) -> None:
    for rel in ["publish/pants/v001", "publish/cam", "publish/_usd/asset/v001", "publish/_usd/geo"]:
        (hero.path / rel).mkdir(parents=True)
    touch(hero.path / "publish/_usd/hero.usd")  # entry layer file, not a layer
    (hero.path / "media/turntable").mkdir(parents=True)
    (hero.path / "media/render").mkdir()
    assert [(p.name, p.usd) for p in hero.products()] == [
        ("asset", True),
        ("geo", True),
        ("cam", False),
        ("pants", False),
    ]
    assert [p.name for p in hero.products(usd=True)] == ["asset", "geo"]
    assert [p.name for p in hero.products(usd=False)] == ["cam", "pants"]
    assert [p.name for p in hero.media()] == ["render", "turntable"]


def test_create_product(hero: Entity) -> None:
    product = hero.create_product("pants")
    assert product.path == hero.path / "publish/pants"
    assert product.path.is_dir()
    with pytest.raises(AlreadyExists):
        hero.create_product("pants")
    with pytest.raises(InvalidName):
        hero.create_product("_usd")


def test_current_usd_version(proj: Project, hero: Entity) -> None:
    layer = Product(proj, hero.path / "publish/_usd/asset")
    assert layer.current() is None
    touch(layer.path / "v002/hero_asset_v002.usd")
    touch(
        layer.path / "asset.usd",
        b'#usda 1.0\n(\n    defaultPrim = "hero"\n'
        b"    subLayers = [@./v002/hero_asset_v002.usd@]\n)\n",
    )
    assert layer.current().number == 2
    assert Product(proj, hero.path / "publish/pants").current() is None


# --- media and file summaries -----------------------------------------------


def test_create_media(hero: Entity) -> None:
    media = hero.create_media("turntable")
    assert media.path == hero.path / "media/turntable"
    assert media.is_media and media.path.is_dir()
    with pytest.raises(AlreadyExists):
        hero.create_media("turntable")
    with pytest.raises(InvalidName):
        hero.create_media("Turn Table")


def test_file_sequences(tmp_path) -> None:
    names = [f"sq010_0010_render_beauty_v004.{f}.exr" for f in (1001, 1002, 1003, 1005)]
    names += ["cache.0001.bgeo.sc", "cache.0002.bgeo.sc", "preview.mov", "notes.v2.txt"]
    paths = [tmp_path / n for n in names]
    groups = file_sequences(paths)
    assert [(g.label, g.frames, g.count, g.missing) for g in groups] == [
        ("cache.####.bgeo.sc", (1, 2), 2, 0),
        ("notes.v2.txt", None, 1, 0),
        ("preview.mov", None, 1, 0),
        ("sq010_0010_render_beauty_v004.####.exr", (1001, 1005), 4, 1),
    ]
    assert groups[3].paths[0].name == "sq010_0010_render_beauty_v004.1001.exr"


def test_single_numbered_file_is_still_a_sequence(tmp_path) -> None:
    [group] = file_sequences([tmp_path / "plate.1001.exr"])
    assert (group.label, group.frames, group.count) == ("plate.####.exr", (1001, 1001), 1)


# --- next version path (folder + file name, no extension) ----------------------


def test_next_version_path_creates_the_folder(proj: Project, hero: Entity) -> None:
    product = Product(proj, hero.path / "publish/base_model")
    touch(product.path / "v001/hero_base_model_v001.abc")
    path = product.next_version_path()
    assert path == product.path / "v002/hero_base_model_v002"
    assert path.parent.is_dir()
    assert not path.exists()
    assert product.next_version_path().parent.name == "v003"  # each call reserves one


def test_next_version_path_kinds(proj: Project, hero: Entity) -> None:
    layer = Product(proj, hero.path / "publish/_usd/asset")
    assert layer.next_version_path().name == "hero_asset_v001"
    shot = proj.create_shot("sq010_0010")
    media = Product(proj, shot.path / "media/render_beauty")
    assert media.next_version_path().name == "sq010_0010_render_beauty_v001"
    cam = Product(proj, proj.entity("sq010").path / "publish/cam")
    assert cam.next_version_path().name == "sq010_cam_v001"


def test_next_version_path_invalid_name_creates_nothing(proj: Project, hero: Entity) -> None:
    product = Product(proj, hero.path / "publish/Base Model")
    with pytest.raises(InvalidName):
        product.next_version_path()
    assert not product.path.exists()
