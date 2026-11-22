"""Small prompts. They collect input only; the caller passes it to one core call."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.settings import settings_path
from scheinwerk.core.templates import parse_frames, step_name


def _field(widget: QWidget) -> QWidget:
    """The input inside a row: the widget itself, or the `field` inside a row with a + button."""
    if isinstance(widget, (QLineEdit, QComboBox)):
        return widget
    return widget.findChild(QComboBox, "field") or widget.findChild(QLineEdit, "field")


def _form(
    parent: QWidget, title: str, rows: list[tuple[str, QWidget]], focus: int = 0
) -> list[str] | None:
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
        _field(rows[focus][1]).setFocus()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    fields = [_field(w) for _, w in rows]
    return [f.currentText() if isinstance(f, QComboBox) else f.text() for f in fields]


def _line(text: str = "", placeholder: str = "") -> QLineEdit:
    edit = QLineEdit(text)
    edit.setPlaceholderText(placeholder)
    edit.setMinimumWidth(320)
    edit.end(False)
    return edit


def _combo(items: list[str], current: str = "", placeholder: str = "") -> QComboBox:
    """A dropdown you can also type into."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(items)
    combo.setCurrentText(current)
    combo.lineEdit().setPlaceholderText(placeholder)
    combo.setMinimumWidth(320)
    return combo


def _with_steps(field: QLineEdit | QComboBox, suggest: Callable[[], str], what: str) -> QWidget:
    """`field` with - and + buttons that step its number down/up by 10 (sq010 -> sq020).
    On an empty field (or one without a number) either button fills in `suggest()`."""
    field.setObjectName("field")
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(field, 1)

    def text() -> str:
        return field.currentText() if isinstance(field, QComboBox) else field.text()

    def step(delta: int) -> None:
        try:
            new = step_name(text(), delta) or suggest()
        except ScheinwerkError as exc:
            error(row, exc)
            return
        if isinstance(field, QComboBox):
            field.setCurrentText(new)
        else:
            field.setText(new)

    for label, delta, name in (("-", -1, "minusButton"), ("+", 1, "plusButton")):
        button = QPushButton(label)
        button.setObjectName(name)
        button.setToolTip(f"{'previous' if delta < 0 else 'next'} {what}")
        button.setAutoDefault(False)  # Enter still means OK
        button.clicked.connect(lambda _checked=False, d=delta: step(d))
        layout.addWidget(button)
    return row


def ask_text(
    parent: QWidget, title: str, label: str, default: str = "", hint: str = ""
) -> str | None:
    values = _form(parent, title, [(label, _line(default, hint))])
    return (values[0].strip() or None) if values else None


def _frames_or_none(text: str) -> tuple[int, int] | None:
    return parse_frames(text) if text.strip() else None


def ask_asset(
    parent: QWidget, categories: list[str], category: str | None = None
) -> tuple[str | None, str] | None:
    """(category or None, name). The category list can be typed into; empty = no category."""
    rows = [
        ("Category", _combo(categories, category or "", "none")),
        ("Name", _line("", "hero")),
    ]
    values = _form(parent, "New asset", rows, focus=1)
    if values is None:
        return None
    return values[0].strip() or None, values[1].strip()


def ask_sequence(parent: QWidget, next_name: Callable[[], str]) -> str | None:
    edit = _line("", next_name())
    values = _form(parent, "New sequence", [("Name", _with_steps(edit, next_name, "name"))])
    return (values[0].strip() or None) if values else None


def ask_shot(
    parent: QWidget,
    sequences: list[str],
    sequence: str | None,
    next_sequence: Callable[[], str],
    next_shot: Callable[[str], str],
) -> tuple[str, tuple[int, int] | None] | None:
    """(`<sequence>_<shot>`, frames or None). `next_shot(seq)` returns a full shot name."""
    seq_combo = _combo(sequences, sequence or "", next_sequence())
    shot_edit = _line("", "0010")

    def fill_shot() -> str:
        seq = seq_combo.currentText().strip()
        if not seq:
            raise ScheinwerkError("Choose or type a sequence first.")
        return next_shot(seq)[len(seq) + 1 :]

    rows = [
        ("Sequence", _with_steps(seq_combo, next_sequence, "sequence")),
        ("Shot", _with_steps(shot_edit, fill_shot, "shot number")),
        ("Frames", _line("", "1001-1096 (optional)")),
    ]
    values = _form(parent, "New shot", rows, focus=1)
    if values is None:
        return None
    seq, shot, frames = (v.strip() for v in values)
    return f"{seq}_{shot}", _frames_or_none(frames)


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
