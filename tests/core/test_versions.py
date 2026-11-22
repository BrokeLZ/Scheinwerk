"""Products, USD layers, media and their v### folders (spec §5.4, §10)."""

from __future__ import annotations

import pytest

from scheinwerk.core.entities import Entity
from scheinwerk.core.errors import AlreadyExists, InvalidName
from scheinwerk.core.project import Project
from scheinwerk.core.versions import Product
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
