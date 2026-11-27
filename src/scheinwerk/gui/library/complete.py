"""Suggestions while typing metadata: values already used in the library (spec §17.11)."""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QModelIndex, Qt
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


def suggest(edit: QLineEdit, words: list[str], is_list: bool = False) -> QLineEdit:
    """Attach suggestions to `edit`. Choosing one counts as an edit (`textEdited` fires)."""
    if words:
        completer = _Completer(words, edit, is_list)
        edit.setCompleter(completer)
        completer.activated.connect(lambda _w: edit.textEdited.emit(edit.text()))
    return edit
