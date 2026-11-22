"""The real dialogs, accepted or cancelled by a timer (regression: fields read after deletion)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QFormLayout, QWidget

from scheinwerk.gui import dialogs


@pytest.fixture
def parent(qapp) -> QWidget:
    widget = QWidget()
    widget.show()
    yield widget
    widget.close()


def answer(fill: dict[int, str] | None = None, *, accept: bool = True) -> None:
    """When the next modal dialog opens: type into its fields (by row), then OK/Cancel.

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
            fields = [
                form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
                for row in range(form.rowCount())
                if form.itemAt(row, QFormLayout.ItemRole.FieldRole) is not None
            ]
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
    answer({0: "sq010_0010", 1: "1001-1096"})
    assert dialogs.ask_shot(parent) == ("sq010_0010", (1001, 1096))
    answer({0: "sq010_0020"})
    assert dialogs.ask_shot(parent) == ("sq010_0020", None)
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
