"""Suggestions while typing metadata: values already used in the library (spec §17.11)."""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QEvent, QModelIndex, QObject, Qt, QTimer
from PySide6.QtWidgets import QCompleter, QLineEdit

from scheinwerk.gui.browser import load_theme

_theme = cache(load_theme)


class _Completer(QCompleter):
    """Completes the whole text, or for a comma list only the part after the last comma."""

    def __init__(self, words: list[str], edit: QLineEdit, is_list: bool) -> None:
        super().__init__(words, edit)
        self.is_list = is_list
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterMode(Qt.MatchFlag.MatchContains)
        self.setModelSorting(QCompleter.ModelSorting.UnsortedModel)  # keep most used first
        self.popup().setObjectName("suggestions")
        self.popup().setStyleSheet(_theme())  # a popup has no parent to inherit it from

    def splitPath(self, path: str) -> list[str]:  # noqa: N802 (Qt API)
        return [path.rsplit(",", 1)[-1].strip()] if self.is_list else [path]

    def pathFromIndex(self, index: QModelIndex) -> str:  # noqa: N802
        word = super().pathFromIndex(index)
        if not self.is_list or "," not in self.widget().text():
            return word
        return f"{self.widget().text().rsplit(',', 1)[0]}, {word}"

    def show_all(self) -> None:
        """Open the list for what is typed so far (all of it when nothing is)."""
        edit = self.widget()
        if edit is not None and edit.isEnabled() and not edit.isReadOnly():
            self.setCompletionPrefix(self.splitPath(edit.text())[0])
            self.complete()


class _OpenOnClick(QObject):
    """Clicking into the field opens the suggestions without typing a first letter."""

    def __init__(self, completer: _Completer) -> None:
        super().__init__(completer.widget())
        self.completer = completer

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.MouseButtonPress:
            # after the click has focused it; dropped if the field is deleted first
            QTimer.singleShot(0, self.completer, self.completer.show_all)
        return False


def suggest(edit: QLineEdit, words: list[str], is_list: bool = False) -> QLineEdit:
    """Attach suggestions to `edit`. Choosing one counts as an edit (`textEdited` fires)."""
    if words:
        completer = _Completer(words, edit, is_list)
        edit.setCompleter(completer)
        completer.activated.connect(lambda _w: edit.textEdited.emit(edit.text()))
        edit.installEventFilter(_OpenOnClick(completer))
        if is_list:  # a comma starts the next value: offer everything again
            edit.textEdited.connect(lambda t: t.rstrip().endswith(",") and completer.show_all())
    return edit
