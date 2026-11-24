"""Project health checks behind `sw doctor` (spec §11)."""

from __future__ import annotations

import pytest

from scheinwerk.core.doctor import Issue, check
from scheinwerk.core.project import Project
from tests.conftest import touch


@pytest.fixture
def hero(proj: Project):
    hero = proj.create_asset("hero")
    hero.create_department("mdl")
    return hero


def found(proj: Project) -> list[tuple[str, str, str]]:
    return [(i.kind, proj.rel(i.path), i.detail) for i in check(proj)]


def test_clean_project(proj: Project, hero) -> None:
    touch(hero.path / "publish/pants/v001/x.abc")
    touch(hero.path / "mdl/main/work/notes.txt")  # unmanaged is fine
    assert check(proj) == []


def test_invalid_names(proj: Project, hero) -> None:
    touch(proj.root / "assets/Hero_Old/entity.json")
    (proj.root / "assets/Props/chair").mkdir(parents=True)  # category
    (proj.root / "shots/SQ1/oops").mkdir(parents=True)
    (hero.path / "Old").mkdir()
    (hero.path / "mdl/Blockout").mkdir()
    (hero.path / "publish/Pants Final").mkdir(parents=True)
    (hero.path / "publish/_usd/Geo").mkdir(parents=True)
    (hero.path / "media/my-render").mkdir(parents=True)
    assert found(proj) == [
        ("invalid name", "assets/Hero_Old", ""),
        ("invalid name", "assets/Props", ""),
        ("invalid name", "assets/hero/Old", ""),
        ("invalid name", "assets/hero/mdl/Blockout", ""),
        ("invalid name", "assets/hero/media/my-render", ""),
        ("invalid name", "assets/hero/publish/Pants Final", ""),
        ("invalid name", "assets/hero/publish/_usd/Geo", ""),
        ("invalid name", "shots/SQ1", ""),
        ("invalid name", "shots/SQ1/oops", ""),
    ]


def test_conflict_copies(proj: Project, hero) -> None:
    touch(hero.path / "mdl/main/work/hero_mdl_main_v003_Conflict.hip")
    touch(proj.root / "shared/hooks/notify (Conflict 2026-11-22).py")
    touch(hero.path / "mdl/main/work/._hero_Conflict.hip")  # ignored
    assert found(proj) == [
        ("conflict copy", "assets/hero/mdl/main/work/hero_mdl_main_v003_Conflict.hip", ""),
        ("conflict copy", "shared/hooks/notify (Conflict 2026-11-22).py", ""),
    ]


@pytest.mark.parametrize(
    ("name", "content", "detail"),
    [
        ("x.usda", b"subLayers = [@/Users/lorenz/show/geo.usd@]", "/Users/lorenz/show/geo.usd"),
        ("x.usd", b"PXR-USDC\x00\x01/Volumes/Drive/tex.exr\x00\x07", "/Volumes/Drive/tex.exr"),
        ("comp.nk", b'Read {\n file "C:/proj/plate.%04d.exr"\n}', "C:/proj/plate.%04d.exr"),
        ("comp.nk", b"Read {\n file D:\\proj\\plate.exr\n}", "D:\\proj\\plate.exr"),
        ("x.usda", b"asset path = @\\\\nas\\show\\x.usd@", "\\\\nas\\show\\x.usd"),
    ],
)
def test_absolute_paths(proj: Project, hero, name: str, content: bytes, detail: str) -> None:
    touch(hero.path / "publish/_usd/geo/v001" / name, content)
    assert found(proj) == [("absolute path", f"assets/hero/publish/_usd/geo/v001/{name}", detail)]


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("x.usda", b"subLayers = [@./v003/hero_geo_v003.usd@]"),
        ("x.usda", b'string url = "https://example.com/x"'),
        ("x.usda", b'uniform token info:id = "UsdPreviewSurface"'),
        ("comp.nk", b'file "[getenv SW_ROOT]/shots/sq010/x.exr"'),
        ("x.hip", b"/Users/lorenz/x.usd"),  # .hip isn't checked
    ],
)
def test_no_false_positives(proj: Project, hero, name: str, content: bytes) -> None:
    touch(hero.path / "publish/_usd/geo/v001" / name, content)
    assert check(proj) == []


def test_cache_is_not_checked(proj: Project, hero) -> None:
    touch(hero.path / "mdl/main/cache/sim.usda", b"@/Users/lorenz/x.usd@")
    assert check(proj) == []


def test_match_across_read_chunks(proj: Project, hero) -> None:
    content = b" " * (1024 * 1024 - 3) + b"@/Users/lorenz/x.usd@"
    touch(hero.path / "publish/_usd/geo/v001/big.usda", content)
    assert [i.detail for i in check(proj)] == ["/Users/lorenz/x.usd"]


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        (
            b"asset file = @../../../../fx/main/cache/pyro/v001/x.$F4.vdb@",
            "../../../../fx/main/cache/pyro/v001/x.$F4.vdb",
        ),
        (b"PXR-USDC\x00\x02../../tex/main/work/wood.exr\x00", "../../tex/main/work/wood.exr"),
        (b"subLayers = [@..\\..\\lgt\\main\\work\\a.usd@]", "..\\..\\lgt\\main\\work\\a.usd"),
    ],
)
def test_unpublished_references(proj: Project, hero, content: bytes, detail: str) -> None:
    touch(hero.path / "publish/_usd/fx/v001/x.usda", content)
    assert found(proj) == [
        ("unpublished reference", "assets/hero/publish/_usd/fx/v001/x.usda", detail)
    ]


@pytest.mark.parametrize(
    "content",
    [
        b"subLayers = [@./v001/hero_geo_v001.usd@]",
        b"asset file = @../../../textures/v002/wood.exr@",
        b'string doc = "teamwork/ and network/ paths"',
        b"@../../../publish/cachet/v001/x.vdb@",
    ],
)
def test_published_references_are_fine(proj: Project, hero, content: bytes) -> None:
    touch(hero.path / "publish/_usd/fx/v001/x.usda", content)
    assert check(proj) == []


def test_unpublished_references_only_under_publish(proj: Project, hero) -> None:
    touch(
        hero.path / "mdl/main/work/scratch.usda", b"@../cache/x.vdb@"
    )  # a workfile, not published
    touch(hero.path / "media/render/v001/x.usda", b"@../../../mdl/main/work/x.usd@")
    touch(hero.path / "publish/_usd/fx/v001/notes.txt", b"../work/x")
    assert check(proj) == []


def test_empty_versions(proj: Project, hero) -> None:
    touch(hero.path / "publish/pants/v001/x.abc")
    (hero.path / "publish/pants/v002").mkdir()
    touch(hero.path / "publish/_usd/geo/v001/version.json", b"{}")
    (hero.path / "media/turntable/v001").mkdir(parents=True)
    shot = proj.create_shot("sq010_0010")
    (shot.path / "publish/cam/v001").mkdir(parents=True)
    assert found(proj) == [
        ("empty version", "assets/hero/media/turntable/v001", ""),
        ("empty version", "assets/hero/publish/_usd/geo/v001", ""),
        ("empty version", "assets/hero/publish/pants/v002", ""),
        ("empty version", "shots/sq010/sq010_0010/publish/cam/v001", ""),
    ]


def test_order_by_kind_then_path(proj: Project, hero) -> None:
    (hero.path / "publish/pants/v001").mkdir(parents=True)
    touch(hero.path / "publish/a.usda", b"@/Users/x@")
    touch(hero.path / "mdl/main/work/x_Conflict.hip")
    (hero.path / "Bad").mkdir()
    touch(hero.path / "publish/_usd/fx/v001/x.usda", b"@../../../../fx/main/cache/a.vdb@")
    kinds = [i.kind for i in check(proj)]
    assert kinds == [
        "invalid name",
        "conflict copy",
        "absolute path",
        "empty version",
        "unpublished reference",
    ]


def test_issue_is_a_plain_record(proj: Project) -> None:
    issue = Issue("empty version", proj.root / "x")
    assert issue.detail == ""
