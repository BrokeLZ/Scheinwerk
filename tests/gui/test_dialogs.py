"""The real dialogs, accepted or cancelled by a timer (regression: fields read after deletion)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QPushButton,
    QWidget,
)

from scheinwerk.gui import dialogs


@pytest.fixture
def parent(qapp) -> QWidget:
    widget = QWidget()
    widget.show()
    yield widget
    widget.close()


def answer(
    fill: dict[int, str] | None = None,
    *,
    accept: bool = True,
    clicks: list[tuple[int, str]] = (),
) -> None:
    """When the next modal dialog opens: click buttons ((row, "+" or "-"), in order), type
    into fields (by row), then OK/Cancel.

    Waits for the dialog to appear, and closes it even if filling fails, so a broken
    test fails instead of hanging.
    """

    def go() -> None:
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(10, go)
            return
        ok = accept
        try:
            form = dialog.layout()
            rows = [
                form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
                for row in range(form.rowCount())
                if form.itemAt(row, QFormLayout.ItemRole.FieldRole) is not None
            ]
            for index, sign in clicks:
                name = "plusButton" if sign == "+" else "minusButton"
                rows[index].findChild(QPushButton, name).click()
            fields = [dialogs._field(w) or w for w in rows]
            for index, text in (fill or {}).items():
                field = fields[index]
                if isinstance(field, QComboBox):
                    field.setCurrentText(text)
                else:
                    field.setText(text)
        except Exception:
            ok = False
            raise
        finally:
            dialog.accept() if ok else dialog.reject()

    QTimer.singleShot(0, go)


def test_ask_text(parent: QWidget) -> None:
    answer()
    assert dialogs.ask_text(parent, "New asset", "Name", "char/") == "char/"
    answer({0: "  hero  "})
    assert dialogs.ask_text(parent, "New asset", "Name") == "hero"
    answer({0: "hero"}, accept=False)
    assert dialogs.ask_text(parent, "New asset", "Name") is None


def test_ask_shot_and_frames(parent: QWidget) -> None:
    def ask() -> tuple:
        return dialogs.ask_shot(parent, ["sq010"], "sq010", lambda: "sq020", lambda s: f"{s}_0010")

    answer({1: "0010", 2: "1001-1096"})
    assert ask() == ("sq010_0010", (1001, 1096))
    answer({1: "0020"})
    assert ask() == ("sq010_0020", None)
    answer()
    assert dialogs.ask_frames(parent, (1, 24)) == (1, 24)


def test_ask_finalize(parent: QWidget) -> None:
    answer({0: "new comment"})
    assert dialogs.ask_finalize(parent, "old", [], None) == ("new comment", None)
    answer({1: "b.usd"})
    assert dialogs.ask_finalize(parent, "c", ["a.usd", "b.usd"], "a.usd") == ("c", "b.usd")


def test_ask_new_project(parent: QWidget, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / "MyShow"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(folder))
    answer()
    assert dialogs.ask_new_project(parent) == (folder, "myshow")


def test_ask_asset(parent: QWidget) -> None:
    answer({1: "hero"})
    assert dialogs.ask_asset(parent, ["char", "prop", "env"], "char") == ("char", "hero")
    answer({0: "vehicle", 1: "car"})  # a new category can be typed
    assert dialogs.ask_asset(parent, ["char", "prop", "env"]) == ("vehicle", "car")
    answer({0: "", 1: "tree"})  # empty = no category
    assert dialogs.ask_asset(parent, ["char"], "char") == (None, "tree")


def test_asset_category_list(parent: QWidget) -> None:
    seen = []

    def go() -> None:
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(10, go)
            return
        combo = dialog.findChild(QComboBox)
        seen.extend(combo.itemText(i) for i in range(combo.count()))
        dialog.reject()

    QTimer.singleShot(0, go)
    dialogs.ask_asset(parent, ["char", "prop", "env", "vehicle"])
    assert seen == ["char", "prop", "env", "vehicle"]


def test_ask_sequence_steps(parent: QWidget) -> None:
    def ask() -> str | None:
        return dialogs.ask_sequence(parent, lambda: "sq010")

    answer(clicks=[(0, "+")])  # empty: the suggestion
    assert ask() == "sq010"
    answer(clicks=[(0, "+"), (0, "+"), (0, "+")])  # keeps counting
    assert ask() == "sq030"
    answer(clicks=[(0, "+"), (0, "+"), (0, "+"), (0, "-")])
    assert ask() == "sq020"
    answer({0: "sq100"})
    assert ask() == "sq100"


def test_ask_shot_steps(parent: QWidget) -> None:
    def ask(sequence: str | None) -> tuple:
        return dialogs.ask_shot(
            parent, ["sq010", "sq020"], sequence, lambda: "sq030", lambda s: f"{s}_0040"
        )

    answer(clicks=[(1, "+")])  # sequence preset, empty shot: next free number
    assert ask("sq020") == ("sq020_0040", None)
    answer(clicks=[(1, "+"), (1, "+"), (1, "-"), (1, "-"), (1, "-")])  # 0040 0050 0040 0030 0020
    assert ask("sq020") == ("sq020_0020", None)
    answer(clicks=[(0, "+"), (0, "+"), (1, "+")], fill={2: "1001-1050"})  # sq020 -> sq030 -> sq040
    assert ask("sq020") == ("sq040_0040", (1001, 1050))
    answer(clicks=[(0, "+")])  # no preset: the suggestion
    answer_shot = dialogs.ask_shot(parent, [], None, lambda: "sq030", lambda s: f"{s}_0010")
    assert answer_shot == ("sq030_", None)  # shot number left empty: core will reject it
