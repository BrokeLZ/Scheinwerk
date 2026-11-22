"""Small prompts. They collect input only; the caller passes it to one core call."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from scheinwerk.core.settings import settings_path
from scheinwerk.core.templates import parse_frames


def _form(parent: QWidget, title: str, rows: list[tuple[str, QWidget]]) -> list[str] | None:
    """Show the fields; return their values on OK, None on Cancel.

    The values are read here, while the dialog exists: once this returns, Qt may
    delete the dialog and its fields, so callers must never touch the widgets.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    form = QFormLayout(dialog)
    for label, widget in rows:
        form.addRow(label, widget)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if rows:
        rows[0][1].setFocus()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return [w.currentText() if isinstance(w, QComboBox) else w.text() for _, w in rows]


def _line(text: str = "", placeholder: str = "") -> QLineEdit:
    edit = QLineEdit(text)
    edit.setPlaceholderText(placeholder)
    edit.setMinimumWidth(320)
    edit.end(False)
    return edit


def ask_text(
    parent: QWidget, title: str, label: str, default: str = "", hint: str = ""
) -> str | None:
    values = _form(parent, title, [(label, _line(default, hint))])
    return (values[0].strip() or None) if values else None


def _frames_or_none(text: str) -> tuple[int, int] | None:
    return parse_frames(text) if text.strip() else None


def ask_shot(parent: QWidget, default: str = "") -> tuple[str, tuple[int, int] | None] | None:
    rows = [("Name", _line(default, "sq010_0010")), ("Frames", _line("", "1001-1096 (optional)"))]
    values = _form(parent, "New shot", rows)
    if values is None:
        return None
    return values[0].strip(), _frames_or_none(values[1])


def ask_frames(parent: QWidget, current: tuple[int, int] | None) -> tuple[int, int] | None:
    text = f"{current[0]}-{current[1]}" if current else ""
    values = _form(parent, "Set frame range", [("Frames", _line(text, "1001-1096"))])
    return parse_frames(values[0]) if values else None


def ask_finalize(
    parent: QWidget, comment: str, main_files: list[str], default_main: str | None
) -> tuple[str, str | None] | None:
    """Comment, plus a main-file choice when a USD version has several .usd files."""
    rows: list[tuple[str, QWidget]] = [("Comment", _line(comment, "what changed"))]
    if len(main_files) > 1:
        combo = QComboBox()
        combo.addItems(main_files)
        if default_main in main_files:
            combo.setCurrentText(default_main)
        rows.append(("Main file", combo))
    values = _form(parent, "Finalize", rows)
    if values is None:
        return None
    return values[0], values[1] if len(values) > 1 else None


def ask_new_project(parent: QWidget) -> tuple[Path, str] | None:
    folder = QFileDialog.getExistingDirectory(parent, "Folder for the new project")
    if not folder:
        return None
    name = ask_text(parent, "New project", "Name", Path(folder).name.lower(), "myshow")
    return (Path(folder), name) if name else None


def pick_folder(parent: QWidget, title: str) -> Path | None:
    folder = QFileDialog.getExistingDirectory(parent, title)
    return Path(folder) if folder else None


def pick_files(parent: QWidget, title: str = "Ingest files") -> list[Path]:
    files, _ = QFileDialog.getOpenFileNames(parent, title)
    return [Path(f) for f in files]


def error(parent: QWidget, exc: Exception) -> None:
    QMessageBox.warning(parent, "Scheinwerk", str(exc))


HELP = """\
Right-click anything for its actions. There are no other buttons.

Double-click    open a workfile / reveal a version folder
Type            filter the focused column (Esc clears)
Drag files      onto a task: ingest as next workfile versions
                onto a product or media: ingest as the next version
F5              reload (also happens when the window gets focus)

Open uses the application set per extension in
{settings}
("dcc" section), otherwise the system default.

Full guide: docs/usage.md in the Scheinwerk repository."""


def show_help(parent: QWidget) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle("Scheinwerk help")
    box.setText(HELP.format(settings=settings_path()))
    label = box.findChild(QLabel, "qt_msgbox_label")
    if label is not None:
        label.setObjectName("helpText")
    box.exec()
