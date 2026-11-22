"""Departments, tasks and workfiles (spec §4, §5.3, §5.4, §10)."""

from __future__ import annotations

import pytest

from scheinwerk.core.entities import Entity, Task, Workfile
from scheinwerk.core.errors import AlreadyExists, InvalidName, NotFound
from scheinwerk.core.project import Project
from tests.conftest import touch


@pytest.fixture
def hero(proj: Project) -> Entity:
    return proj.create_asset("hero")


@pytest.fixture
def task(hero: Entity) -> Task:
    return hero.create_department("mdl").tasks()[0]


# --- departments and tasks --------------------------------------------------


def test_create_department_makes_tasks_with_work_and_cache(hero: Entity) -> None:
    dept = hero.create_department("mdl", tasks=("main", "blockout"))
    for t in ["main", "blockout"]:
        assert (hero.path / "mdl" / t / "work").is_dir()
        assert (hero.path / "mdl" / t / "cache").is_dir()
    assert [t.name for t in dept.tasks()] == ["main", "blockout"]  # template task first


@pytest.mark.parametrize("name", ["Mdl", "publish", "media", "_x"])
def test_create_department_invalid(hero: Entity, name: str) -> None:
    with pytest.raises(InvalidName):
        hero.create_department(name)


def test_create_department_twice(hero: Entity) -> None:
    hero.create_department("mdl")
    with pytest.raises(AlreadyExists):
        hero.create_department("mdl")
    with pytest.raises(AlreadyExists):
        hero.departments()[0].create_task("main")


def test_departments_template_order_then_custom(hero: Entity) -> None:
    for name in ["rig", "groom", "mdl"]:
        hero.create_department(name)
    (hero.path / "publish").mkdir()
    (hero.path / "media").mkdir()
    (hero.path / "backup").mkdir()  # ignored
    (hero.path / "Old").mkdir()  # shown, flagged
    depts = hero.departments()
    assert [(d.name, d.custom, d.valid) for d in depts] == [
        ("mdl", False, True),
        ("rig", False, True),
        ("Old", True, False),
        ("groom", True, True),
    ]


def test_sequence_departments_live_in_seq(proj: Project) -> None:
    seq = proj.create_sequence("sq010")
    lgt = seq.create_department("lgt")
    assert lgt.path == proj.root / "shots/sq010/_seq/lgt"
    assert (lgt.path / "main/work").is_dir()
    assert not lgt.custom
    assert seq.create_department("anim").custom  # not in the sequence template


def test_custom_tasks(hero: Entity) -> None:
    dept = hero.create_department("mdl")
    dept.create_task("blockout")
    dept.create_task("alt")
    assert [(t.name, t.custom) for t in dept.tasks()] == [
        ("main", False),
        ("alt", True),
        ("blockout", True),
    ]


def test_missing_entity_folder(proj: Project) -> None:
    ghost = Entity(proj, "asset", "ghost")
    with pytest.raises(NotFound):
        ghost.create_department("mdl")


# --- workfiles: version counting --------------------------------------------


def test_empty_task(task: Task) -> None:
    assert task.workfiles() == []
    assert task.latest_workfile() is None
    assert task.next_workfile("hip") == task.work_dir / "hero_mdl_main_v001.hip"
    assert not task.next_workfile("hip").exists()  # just a path


def test_counter_shared_across_extensions(task: Task) -> None:
    touch(task.work_dir / "hero_mdl_main_v001.hip")
    touch(task.work_dir / "hero_mdl_main_v002.nk")
    assert task.next_workfile("blend").name == "hero_mdl_main_v003.blend"


def test_gaps(task: Task) -> None:
    touch(task.work_dir / "hero_mdl_main_v001.hip")
    touch(task.work_dir / "hero_mdl_main_v005.hip")
    assert task.next_workfile("hip").name == "hero_mdl_main_v006.hip"


@pytest.mark.parametrize(("have", "next_"), [("v999", "v1000"), ("v1000", "v1001")])
def test_past_999(task: Task, have: str, next_: str) -> None:
    touch(task.work_dir / f"hero_mdl_main_{have}.hip")
    assert task.next_workfile("hip").name == f"hero_mdl_main_{next_}.hip"


def test_unmanaged_files_dont_count(task: Task) -> None:
    touch(task.work_dir / "hero_mdl_main_v001.hip")
    touch(task.work_dir / "villain_mdl_main_v050.hip")
    touch(task.work_dir / "hero_mdl_main_v040_final.hip")
    (task.work_dir / "old").mkdir()
    assert task.next_workfile("hip").name == "hero_mdl_main_v002.hip"
    assert [p.name for p in task.unmanaged()] == [
        "hero_mdl_main_v040_final.hip",
        "old",
        "villain_mdl_main_v050.hip",
    ]


def test_ignored_files_are_invisible(task: Task) -> None:
    touch(task.work_dir / "hero_mdl_main_v001.blend")
    touch(task.work_dir / "hero_mdl_main_v009.blend1")  # Blender backup, would parse as v009
    touch(task.work_dir / ".DS_Store")
    (task.work_dir / "backup").mkdir()
    assert [w.version for w in task.workfiles()] == [1]
    assert task.unmanaged() == []
    assert task.next_workfile("blend").name == "hero_mdl_main_v002.blend"


def test_workfiles_newest_first(task: Task) -> None:
    for name in ["v001.hip", "v003.nk", "v003.hip", "v002.blend"]:
        touch(task.work_dir / f"hero_mdl_main_{name}")
    assert [(w.version, w.ext) for w in task.workfiles()] == [
        (3, "hip"),
        (3, "nk"),
        (2, "blend"),
        (1, "hip"),
    ]
    assert task.latest_workfile() == Workfile(task.work_dir / "hero_mdl_main_v003.hip", 3, "hip")
    assert task.latest_workfile("blend").version == 2
    assert task.latest_workfile("ma") is None


@pytest.mark.parametrize("ext", [".hip", "HIP", "", "bgeo.sc"])
def test_next_workfile_rejects_bad_extension(task: Task, ext: str) -> None:
    with pytest.raises(InvalidName):
        task.next_workfile(ext)


def test_sequence_workfile_uses_sequence_name(proj: Project) -> None:
    task = proj.create_sequence("sq010").create_department("lgt").tasks()[0]
    assert task.next_workfile("hip").name == "sq010_lgt_main_v001.hip"


# --- workfiles: creating ----------------------------------------------------


def test_new_version_from(task: Task) -> None:
    src = touch(task.work_dir / "hero_mdl_main_v001.hip", b"scene v1")
    touch(task.work_dir / "hero_mdl_main_v002.nk")
    new = task.new_version_from(task.latest_workfile("hip"))
    assert new == task.work_dir / "hero_mdl_main_v003.hip"
    assert new.read_bytes() == b"scene v1"
    assert src.read_bytes() == b"scene v1"


def test_new_empty_workfile_from_template(proj: Project, task: Task) -> None:
    touch(proj.root / "shared/templates/empty.hip", b"TEMPLATE")
    new = task.new_empty_workfile("hip")
    assert new == task.work_dir / "hero_mdl_main_v001.hip"
    assert new.read_bytes() == b"TEMPLATE"


def test_new_empty_workfile_without_template(task: Task) -> None:
    with pytest.raises(NotFound, match="shared/templates/empty.hip"):
        task.new_empty_workfile("hip")
    assert list(task.work_dir.iterdir()) == []
