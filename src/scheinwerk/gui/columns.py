"""The building blocks: a titled column with type-to-filter, and the detail panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Property, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

DATA = Qt.ItemDataRole.UserRole
KEY = Qt.ItemDataRole.UserRole + 1


@dataclass
class Row:
    """One line in a column. `key` identifies it across reloads (selection memory)."""

    label: str
    data: object = None
    key: str = ""
    dim: bool = False
    tooltip: str = ""
    children: list[Row] = field(default_factory=list)


class _Tree(QTreeWidget):
    """Forwards typing to the filter field and file drops to the column."""

    def __init__(self, column: Column) -> None:
        super().__init__()
        self._column = column
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(14)
        self.setUniformRowHeights(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setDragDropMode(QTreeWidget.DragDropMode.DropOnly)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        if self._column.handle_filter_key(event):
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._column.accepts_drops and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        item = self.itemAt(event.position().toPoint())
        if paths:
            self._column.filesDropped.emit(item.data(0, DATA) if item else None, paths)
            event.acceptProposedAction()


class Column(QWidget):
    """Title, tree and a filter that appears when you type (Esc clears it)."""

    selectionChanged = Signal()
    activated = Signal(object)  # double-click: item data
    menuRequested = Signal(object, QPoint)  # item data (None = empty space), global pos
    filesDropped = Signal(object, list)  # item data (None = empty space), [Path]

    def __init__(self, title: str | None = None, *, accepts_drops: bool = False) -> None:
        super().__init__()
        self.setObjectName("column")
        self.accepts_drops = accepts_drops
        self._dim = QColor()
        self._restoring = False

        self.title = QLabel(title or "")
        self.title.setObjectName("columnTitle")
        self.title.setVisible(title is not None)
        self.tree = _Tree(self)
        self.filter = QLineEdit()
        self.filter.setObjectName("filter")
        self.filter.setPlaceholderText("filter")
        self.filter.setClearButtonEnabled(True)
        self.filter.hide()
        self.filter.textChanged.connect(self._apply_filter)

        frame = QFrame()
        frame.setObjectName("columnFrame")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(self.tree)
        inner.addWidget(self.filter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(frame)

        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda item, _: self.activated.emit(item.data(0, DATA)))
        self.tree.customContextMenuRequested.connect(self._menu)

    # Colour for dimmed rows, set from theme.qss: Column { qproperty-dimColor: #...; }
    def _get_dim(self) -> QColor:
        return self._dim

    def _set_dim(self, color: QColor) -> None:
        self._dim = QColor(color)

    dimColor = Property(QColor, _get_dim, _set_dim)  # noqa: N815 (Qt property name)

    # --- content --------------------------------------------------------------

    def set_title(self, title: str) -> None:
        self.title.setText(title)

    def set_rows(self, rows: list[Row], select: str | None = None) -> None:
        """Replace the content and select `select` (a key) if it is there, without signalling."""
        self._restoring = True
        self.tree.clear()
        self.tree.setRootIsDecorated(any(r.children for r in rows))
        for row in rows:
            item = self._item(row)
            self.tree.addTopLevelItem(item)
            for child in row.children:
                item.addChild(self._item(child))
            item.setExpanded(True)
        self._apply_filter(self.filter.text())
        if select:
            self.select_key(select)
        self._restoring = False

    def _item(self, row: Row) -> QTreeWidgetItem:
        item = QTreeWidgetItem([row.label])
        item.setData(0, DATA, row.data)
        item.setData(0, KEY, row.key)
        if row.tooltip:
            item.setToolTip(0, row.tooltip)
        if row.dim and self._dim.isValid():
            item.setForeground(0, self._dim)
        if row.dim:
            font = item.font(0)
            font.setItalic(True)
            item.setFont(0, font)
        return item

    def _items(self) -> list[QTreeWidgetItem]:
        found = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            found.append(top)
            found += [top.child(j) for j in range(top.childCount())]
        return found

    def select_key(self, key: str | None) -> bool:
        for item in self._items():
            if key and item.data(0, KEY) == key and not item.isHidden():
                self.tree.setCurrentItem(item)
                return True
        return False

    def current_item(self) -> QTreeWidgetItem | None:
        items = self.tree.selectedItems()
        return items[0] if items else None

    def current_data(self) -> object:
        item = self.current_item()
        return item.data(0, DATA) if item else None

    def current_key(self) -> str | None:
        item = self.current_item()
        return item.data(0, KEY) if item else None

    def all_data(self) -> list[object]:
        return [item.data(0, DATA) for item in self._items()]

    # --- signals ----------------------------------------------------------------

    def _selection_changed(self) -> None:
        if not self._restoring:
            self.selectionChanged.emit()

    def _menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            self.tree.clearSelection()
        else:
            self.tree.setCurrentItem(item)  # the menu acts on what was right-clicked
        self.menuRequested.emit(
            item.data(0, DATA) if item else None, self.tree.viewport().mapToGlobal(pos)
        )

    # --- type-to-filter -----------------------------------------------------------

    def handle_filter_key(self, event: QKeyEvent) -> bool:
        key, text = event.key(), event.text()
        if key == Qt.Key.Key_Escape and self.filter.isVisible():
            self.filter.clear()
            self.filter.hide()
            return True
        if key == Qt.Key.Key_Backspace and self.filter.text():
            self.filter.setText(self.filter.text()[:-1])
            return True
        blocked = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        if text and text.isprintable() and not text.isspace() and not event.modifiers() & blocked:
            self.filter.show()
            self.filter.setText(self.filter.text() + text)
            return True
        return False

    def _apply_filter(self, text: str) -> None:
        needle = text.lower()
        self.filter.setVisible(bool(text) or self.filter.hasFocus())
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            visible_children = 0
            for j in range(top.childCount()):
                child = top.child(j)
                match = needle in child.text(0).lower()
                child.setHidden(not match)
                visible_children += match
            top.setHidden(
                bool(needle) and not visible_children and needle not in top.text(0).lower()
            )


class Detail(QLabel):
    """Read-only `label  value` lines below the middle columns."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("detail")
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setWordWrap(True)

    def set_fields(self, title: str, fields: list[tuple[str, str]]) -> None:
        width = max((len(k) for k, _ in fields), default=0) + 2
        lines = [title, ""] + [f"{k:<{width}}{v}" for k, v in fields]
        self.setText("\n".join(lines) if fields else title)
