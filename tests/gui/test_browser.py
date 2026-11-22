"""The browser fills its columns from core and its actions call core (spec §12).

These are smoke tests: GUI behaviour is still checked by hand (spec §15).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QPushButton

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
    assert "New department…" in menu_labels(actions.column_menu(browser, 0, browser.department()))
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
    seen = {}

    def ask_asset(parent, categories, category):
        seen.update(categories=categories, category=category)
        return "prop", "lamp"

    monkeypatch.setattr(dialogs, "ask_asset", ask_asset)
    trigger(actions.entity_menu(browser, browser.entities.current_data()), "New asset…")
    assert seen == {"categories": ["char", "prop", "env"], "category": "char"}
    assert (show.root / "assets/prop/lamp/entity.json").is_file()
    assert browser.entity().name == "lamp"  # the new asset is selected

    monkeypatch.setattr(dialogs, "ask_department", lambda parent, choices: ("tex", True))
    trigger(actions.column_menu(browser, 0, None), "New department…")
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


def test_new_shot_passes_sequences_and_suggestions(
    browser: Browser, show: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = {}

    def ask_shot(parent, sequences, sequence, next_sequence, next_shot):
        seen.update(sequences=sequences, sequence=sequence)
        seen.update(next_sequence=next_sequence(), next_shot=next_shot("sq010"))
        return "sq010_0020", (1001, 1010)

    monkeypatch.setattr(dialogs, "ask_shot", ask_shot)
    browser.set_mode("shots")
    browser.entities.select_key("shot:sq010_0010")
    trigger(actions.entity_menu(browser, browser.entities.current_data()), "New shot…")
    assert seen == {
        "sequences": ["sq010"],
        "sequence": "sq010",
        "next_sequence": "sq020",
        "next_shot": "sq010_0020",
    }
    assert show.entity("sq010_0020").frames == (1001, 1010)
    assert browser.entity().name == "sq010_0020"


@pytest.mark.parametrize("clicked", [("sequence", "sq020"), "sq020_0010", "sq020"])
def test_new_shot_presets_the_right_clicked_sequence(
    browser: Browser, show: Project, monkeypatch: pytest.MonkeyPatch, clicked
) -> None:
    show.create_shot("sq020_0010")
    browser.set_mode("shots")
    browser.entities.select_key("shot:sq010_0010")  # something else is selected
    data = clicked if isinstance(clicked, tuple) else show.entity(clicked)
    seen = {}

    def ask_shot(parent, sequences, sequence, next_sequence, next_shot):
        seen["sequence"] = sequence
        return None

    monkeypatch.setattr(dialogs, "ask_shot", ask_shot)
    trigger(actions.entity_menu(browser, data), "New shot…")
    assert seen == {"sequence": "sq020"}


def test_right_click_selects_the_item(browser: Browser, show: Project) -> None:
    browser.set_mode("shots")
    column = browser.entities
    item = next(i for i in column._items() if i.text(0) == "sq010_0010")
    column.menuRequested.disconnect()  # don't open a real menu
    column._menu(column.tree.visualItemRect(item).center())
    assert browser.entity().name == "sq010_0010"


# --- always a selection ------------------------------------------------------------


def test_selecting_an_entity_selects_the_first_of_everything(
    browser: Browser, show: Project
) -> None:
    browser.memory["scenefiles"] = [None, None, None]
    browser.entities.select_key("asset:chair")  # no departments: columns stay empty
    assert (browser.department(), browser.task(), browser.workfile()) == (None, None, None)
    browser.entities.select_key("asset:hero")
    assert browser.department().name == "mdl"
    assert browser.task().name == "main"
    assert browser.workfile().path.name == "hero_mdl_main_v002.nk"  # newest first


def test_products_select_first_skipping_headers(browser: Browser) -> None:
    browser.set_view("products")
    assert browser.product().name == "asset"  # not the "USD layers" header
    assert browser.version().number == 2  # newest
    assert browser.cols[2].current_data() is not None


def test_first_entity_is_selected_on_start(qapp, show: Project) -> None:
    b = Browser(show.root)
    assert b.entity().name == "chair"  # first asset; category rows are skipped
    b.set_mode("shots")
    assert b.entity().name == "sq010"  # the sequence entry, not the sq010 header


def test_deselecting_puts_the_selection_back(browser: Browser) -> None:
    browser.cols[0].select_key("rig")
    browser.cols[0].tree.clearSelection()  # what Ctrl-click / empty-space clicks do
    assert browser.department().name == "rig"


def test_new_department_without_task(
    browser: Browser, show: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = {}

    def ask_department(parent, choices):
        seen["choices"] = choices
        return "groom", False

    monkeypatch.setattr(dialogs, "ask_department", ask_department)
    trigger(actions.column_menu(browser, 0, None), "New department…")
    assert seen["choices"] == ["tex", "lookdev", "fx"]  # template minus mdl and rig
    groom = show.root / "assets/char/hero/groom"
    assert groom.is_dir() and list(groom.iterdir()) == []
    assert browser.department().name == "groom"
    assert browser.task() is None


# --- project dropdown --------------------------------------------------------------


def box_items(browser: Browser) -> list[str]:
    box = browser.project_box
    return [box.itemText(i) or "---" for i in range(box.count())]


def test_top_bar_has_no_help_or_plus(browser: Browser) -> None:
    texts = {b.text() for b in browser.findChildren(QPushButton)}
    assert "?" not in texts and "+" not in texts
    assert box_items(browser) == ["testproject", "---", "Open existing project…", "New project…"]
    assert browser.project_box.currentText() == "testproject"


def choose(browser: Browser, text: str) -> None:
    index = browser.project_box.findText(text)
    browser.project_box.setCurrentIndex(index)
    browser.project_box.activated.emit(index)


def test_new_project_from_dropdown(
    browser: Browser, show: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = {}

    def ask(parent, location, defaults):
        seen.update(location=location, fps=defaults["fps"])
        return str(tmp_path / "jobs"), "short", "25", "2048x858", 1

    monkeypatch.setattr(dialogs, "ask_new_project", ask)
    choose(browser, "New project…")
    assert seen == {"location": show.root.parent, "fps": 24}
    config = Project.find(tmp_path / "jobs/short").config
    assert (config["fps"], config["resolution"], config["frame_start"]) == (25, [2048, 858], 1)
    assert browser.project.root == tmp_path / "jobs/short"
    assert box_items(browser)[:2] == ["short", "testproject"]


def test_new_project_bad_input_keeps_the_open_project(
    browser: Browser, show: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shown = []
    monkeypatch.setattr(dialogs, "error", lambda parent, exc: shown.append(str(exc)))
    monkeypatch.setattr(
        dialogs, "ask_new_project", lambda *a: (str(tmp_path), "short", "fast", "1920x1080", 1)
    )
    choose(browser, "New project…")
    assert "frame rate" in shown[0]
    assert not (tmp_path / "short").exists()
    assert browser.project.root == show.root
    assert browser.project_box.currentText() == "testproject"


def test_cancel_restores_the_dropdown(browser: Browser, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dialogs, "pick_folder", lambda *a: None)
    choose(browser, "Open existing project…")
    assert browser.project_box.currentText() == "testproject"


def test_open_existing_from_dropdown(
    browser: Browser, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = Project.create(tmp_path / "other", "other")
    (other.root / "assets").mkdir(exist_ok=True)
    monkeypatch.setattr(dialogs, "pick_folder", lambda *a: other.root / "assets")
    choose(browser, "Open existing project…")
    assert browser.project.root == other.root
