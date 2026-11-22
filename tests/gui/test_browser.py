"""The browser fills its columns from core and its actions call core (spec §12).

These are smoke tests: GUI behaviour is still checked by hand (spec §15).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from scheinwerk.core.entities import Workfile
from scheinwerk.core.project import Project
from scheinwerk.core.publish import finalize, next_usd
from scheinwerk.gui import actions, dialogs
from scheinwerk.gui.browser import Browser
from tests.conftest import touch


@pytest.fixture
def show(proj: Project) -> Project:
    hero = proj.create_asset("hero", category="char")
    hero.create_department("mdl")
    rig = hero.create_department("rig", tasks=("main", "face"))
    work = hero.path / "mdl/main/work"
    touch(work / "hero_mdl_main_v001.hip")
    touch(work / "hero_mdl_main_v002.nk")
    touch(work / "notes.txt")
    proj.create_asset("chair")
    proj.create_shot("sq010_0010", frames=(1001, 1096))
    for _ in range(2):
        v = next_usd(hero, "asset")
        touch(v / f"hero_asset_{v.name}.usd")
        finalize(v, comment=f"look {v.name}")
    touch(hero.path / "publish/pants/v001/x.abc")
    for f in range(1001, 1004):
        touch(hero.path / f"media/turntable/v001/hero_turntable_v001.{f}.exr")
    assert rig.path.is_dir()
    return proj


@pytest.fixture
def browser(qapp, show: Project) -> Browser:
    b = Browser(show.root / "assets/char/hero/mdl/main/work")
    b.show()
    yield b
    b.close()


def labels(column) -> list[str]:
    return [item.text(0) for item in column._items() if not item.isHidden()]


def menu_labels(menu) -> list[str]:
    return [a.text() for a in menu.actions() if a.text()]


def test_starts_at_the_given_path(browser: Browser, show: Project) -> None:
    assert labels(browser.entities) == ["chair", "char", "hero"]
    assert browser.entity().name == "hero"
    assert labels(browser.cols[0]) == ["mdl", "rig"]
    assert browser.task().name == "main"  # mdl has one task: picked automatically
    assert labels(browser.cols[2]) == [
        "hero_mdl_main_v002.nk",
        "hero_mdl_main_v001.hip",
        "notes.txt",
    ]
    assert browser.cols[2]._items()[2].font(0).italic()  # unmanaged: dimmed
    assert "assets/char/hero/mdl/main" in browser.detail.text()
    assert str(show.root) in browser.project_box.currentData()


def test_shots_mode(browser: Browser) -> None:
    browser.set_mode("shots")
    assert labels(browser.entities) == ["sq010", "sq010 (sequence)", "sq010_0010"]


def test_products_view_and_memory(browser: Browser) -> None:
    browser.cols[0].select_key("rig")
    assert labels(browser.cols[1]) == ["main", "face  (custom)"]
    browser.set_view("products")
    assert labels(browser.cols[0]) == ["USD layers", "asset", "Products", "pants"]
    browser.cols[0].select_key("usd:asset")
    assert labels(browser.cols[1]) == ["v002  (current)", "v001"]
    browser.cols[1].select_key("v001")
    assert "look v001" in browser.detail.text()
    browser.set_view("media")
    browser.cols[0].select_key("turntable")
    browser.cols[1].select_key("v001")
    assert labels(browser.cols[2]) == ["hero_turntable_v001.####.exr  1001-1003 (3)"]
    browser.set_view("scenefiles")
    assert browser.department().name == "rig"  # remembered per view
    browser.set_view("products")
    assert browser.version().number == 1


def test_type_to_filter(browser: Browser, qapp) -> None:
    tree = browser.entities.tree
    for char in "her":
        tree.keyPressEvent(
            QKeyEvent(QKeyEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, char)
        )
    assert browser.entities.filter.text() == "her"
    assert labels(browser.entities) == ["char", "hero"]
    tree.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert labels(browser.entities) == ["chair", "char", "hero"]


def test_menus(browser: Browser) -> None:
    hero = browser.entity()
    assert menu_labels(actions.entity_menu(browser, hero)) == [
        "New asset…",
        "New category…",
        "Set frame range…",
        "Copy path",
        "Copy relative path",
        "Reveal",
    ]
    assert "New department" in menu_labels(actions.column_menu(browser, 0, browser.department()))
    workfile = browser.cols[2].all_data()[0]
    assert isinstance(workfile, Workfile)
    file_menu = menu_labels(actions.column_menu(browser, 2, workfile))
    assert file_menu[:3] == ["Open", "Open with", "New version from this"]
    assert {"New empty workfile", "Copy next version path", "Ingest file(s)…"} <= set(file_menu)
    browser.set_view("products")
    browser.cols[0].select_key("usd:asset")
    version = browser.cols[1].all_data()[0]
    assert menu_labels(actions.column_menu(browser, 1, version)) == [
        "Copy next version path",
        "Open folder",
        "Finalize / Edit comment…",
        "Set as current",
        "Copy path",
        "Copy relative path",
        "Reveal",
    ]


def trigger(menu, *path: str) -> None:
    for label in path[:-1]:
        menu = next(a.menu() for a in menu.actions() if a.text() == label)
    next(a for a in menu.actions() if a.text() == path[-1]).trigger()


def test_actions_call_core(
    browser: Browser, show: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: "prop/lamp")
    trigger(actions.entity_menu(browser, browser.entities.current_data()), "New asset…")
    assert (show.root / "assets/prop/lamp/entity.json").is_file()
    assert browser.entity().name == "lamp"  # the new asset is selected

    trigger(actions.column_menu(browser, 0, None), "New department", "tex")
    assert (show.root / "assets/prop/lamp/tex/main/work").is_dir()
    assert browser.department().name == "tex"
    assert browser.task().name == "main"

    touch(show.root / "shared/templates/empty.hip", b"T")
    trigger(actions.column_menu(browser, 2, None), "New empty workfile", ".hip")
    new = show.root / "assets/prop/lamp/tex/main/work/lamp_tex_main_v001.hip"
    assert new.read_bytes() == b"T"
    assert browser.workfile().path == new


def test_drop_ingests(browser: Browser, show: Project, tmp_path: Path) -> None:
    src = touch(tmp_path / "dl/old.hip", b"old")
    actions.drop(browser, 2, None, [src])
    assert (
        show.root / "assets/char/hero/mdl/main/work/hero_mdl_main_v003.hip"
    ).read_bytes() == b"old"
    assert src.exists()


def test_errors_show_a_dialog(browser: Browser, monkeypatch: pytest.MonkeyPatch) -> None:
    shown = []
    monkeypatch.setattr(dialogs, "error", lambda parent, exc: shown.append(str(exc)))
    monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: "Bad Name")
    trigger(actions.entity_menu(browser, None), "New category…")
    assert shown and "Invalid category name" in shown[0]


def test_no_project(qapp, tmp_path: Path) -> None:
    b = Browser(None)
    assert b.project is None
    assert "No project" in b.detail.text()
    assert menu_labels(actions.entity_menu(b, None)) == ["No project open"]


def test_mode_buttons_follow_set_mode(browser: Browser) -> None:
    browser.set_mode("shots")
    checked = [b.property("mode") for b in browser.mode_buttons.buttons() if b.isChecked()]
    assert checked == ["shots"]


def test_copy_next_version_path(browser: Browser, show: Project, qapp) -> None:
    browser.set_view("products")
    browser.cols[0].select_key("pants")
    menu = actions.column_menu(browser, 1, None)  # right-click on empty space in Versions
    assert menu_labels(menu) == ["Copy next version path"]
    trigger(menu, "Copy next version path")
    expected = show.root / "assets/char/hero/publish/pants/v002/hero_pants_v002"
    assert qapp.clipboard().text() == str(expected)
    assert expected.parent.is_dir()  # the folder is reserved
    assert browser.version().number == 2  # the new version is selected


def test_copy_next_media_path(browser: Browser, show: Project, qapp) -> None:
    browser.set_view("media")
    browser.cols[0].select_key("turntable")
    trigger(actions.column_menu(browser, 1, None), "Copy next version path")
    assert qapp.clipboard().text().endswith("turntable/v002/hero_turntable_v002")


def test_copy_next_workfile_path(browser: Browser, show: Project, qapp) -> None:
    trigger(actions.column_menu(browser, 2, None), "Copy next version path")
    work = show.root / "assets/char/hero/mdl/main/work"
    assert qapp.clipboard().text() == str(work / "hero_mdl_main_v003")
    assert sorted(p.name for p in work.iterdir())[-1] == "notes.txt"  # nothing created


def test_products_menu_has_no_next_version_entry(browser: Browser) -> None:
    browser.set_view("products")
    browser.cols[0].select_key("pants")
    labels_ = menu_labels(actions.column_menu(browser, 0, browser.product()))
    assert not any("next version" in label for label in labels_)
