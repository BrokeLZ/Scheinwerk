"""The Browse view (spec §17.11): filters | thumbnail grid | the selected item.

Every list is one core call (search, category_counts, tag_counts); metadata edits are
update_meta; rebuilds run as `sw lib rebuild` jobs. Thumbnails load a few at a time.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QImageReader, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSlider,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.system import reveal
from scheinwerk.gui.library.jobs import JobQueue
from scheinwerk.library.ids import DEFAULT_VARIANT
from scheinwerk.library.items import Item, update_meta
from scheinwerk.library.root import Library
from scheinwerk.library.search import category_counts, search, tag_counts

TYPES = [
    ("All", None),
    ("HDRIs", "hdri"),
    ("Textures", "texture"),
    ("Texture sets", "texture_set"),
    ("Models", "model"),
]
WORKFLOWS = [("Any workflow", None), ("metal/rough", "metal_rough"), ("spec/gloss", "spec_gloss")]
THUMBS_PER_TICK = 12
ITEM = Qt.ItemDataRole.UserRole
HAS_PREVIEW = Qt.ItemDataRole.UserRole + 1


def _pixmap(path: Path, size: QSize) -> QPixmap | None:
    reader = QImageReader(str(path))
    if not reader.canRead():
        return None
    full = reader.size()
    if full.isValid():
        reader.setScaledSize(full.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    return None if image.isNull() else QPixmap.fromImage(image)


def _main_thumbnail(item: Item) -> Path | None:
    latest = item.latest()
    if latest is None:
        return None
    variants = latest.variants()
    variant = DEFAULT_VARIANT if DEFAULT_VARIANT in variants else next(iter(variants), None)
    return latest.thumbnail(variant) if variant else None


class _Grid(QListWidget):
    filesDropped = Signal(object, list)  # Item or None, [Path]

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("libraryGrid")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setWordWrap(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        hit = self.itemAt(event.position().toPoint())
        if paths:
            self.filesDropped.emit(hit.data(ITEM) if hit else None, paths)
            event.acceptProposedAction()


class BrowseView(QWidget):
    ingestRequested = Signal(list, object)  # [Path], target dict or None

    def __init__(self, library: Library, queue: JobQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("browseView")
        self.library = library
        self.queue = queue
        self.text = ""
        self.items: list[Item] = []
        self._pending: list[QListWidgetItem] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._load_some_thumbnails)

        # left: type, categories, tags, filters
        self.types = QComboBox()
        self.types.setObjectName("fieldBox")
        for label, value in TYPES:
            self.types.addItem(label, value)
        self.types.currentIndexChanged.connect(lambda _i: self.reload())
        self.categories = QTreeWidget()
        self.categories.setObjectName("categoryTree")
        self.categories.setHeaderHidden(True)
        self.categories.itemSelectionChanged.connect(self.reload)
        self.tags = QListWidget()
        self.tags.setObjectName("tagList")
        self.tags.itemChanged.connect(lambda _i: self.reload())
        self.has_variants = QCheckBox("Has variants")
        self.udim = QCheckBox("UDIM")
        self.workflow = QComboBox()
        self.workflow.setObjectName("fieldBox")
        for label, value in WORKFLOWS:
            self.workflow.addItem(label, value)
        for check in (self.has_variants, self.udim):
            check.toggled.connect(lambda _on: self.reload())
        self.workflow.currentIndexChanged.connect(lambda _i: self.reload())
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        for title, widget in (
            ("Type", self.types),
            ("Categories", self.categories),
            ("Tags", self.tags),
        ):
            label = QLabel(title)
            label.setObjectName("columnTitle")
            left_layout.addWidget(label)
            left_layout.addWidget(widget, 1 if widget is not self.types else 0)
        filters = QLabel("Filters")
        filters.setObjectName("columnTitle")
        left_layout.addWidget(filters)
        for widget in (self.has_variants, self.udim, self.workflow):
            left_layout.addWidget(widget)

        # centre: grid, size, sort
        self.grid = _Grid()
        self.grid.itemSelectionChanged.connect(self._show_detail)
        self.grid.customContextMenuRequested.connect(self._menu)
        self.grid.filesDropped.connect(self._dropped)
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(96, 320)
        self.size.setValue(160)
        self.size.valueChanged.connect(self._resize_grid)
        self.sort = QComboBox()
        self.sort.setObjectName("fieldBox")
        self.sort.addItem("Sort by name", "name")
        self.sort.addItem("Sort by date added", "added")
        self.sort.currentIndexChanged.connect(lambda _i: self.reload())
        self.count = QLabel("")
        bottom = QHBoxLayout()
        bottom.addWidget(self.count, 1)
        bottom.addWidget(self.sort)
        bottom.addWidget(self.size)
        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.addWidget(self.grid, 1)
        centre_layout.addLayout(bottom)

        # right: detail
        self.detail = QScrollArea()
        self.detail.setObjectName("itemDetail")
        self.detail.setWidgetResizable(True)
        self.detail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(centre)
        split.addWidget(self.detail)
        split.setSizes([230, 800, 420])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.addWidget(split)
        self._resize_grid()
        self.reload()

    # --- filling -------------------------------------------------------------------------

    def set_text(self, text: str) -> None:
        self.text = text
        self.reload()

    def _type(self) -> str | None:
        return self.types.currentData()

    def _category(self) -> str | None:
        chosen = self.categories.selectedItems()
        return chosen[0].data(0, ITEM) if chosen else None

    def _tags(self) -> list[str]:
        return [
            self.tags.item(i).data(ITEM)
            for i in range(self.tags.count())
            if self.tags.item(i).checkState() == Qt.CheckState.Checked
        ]

    def reload(self, select: str | None = None, keep_detail: bool = False) -> None:
        """Rescan the library (no index, spec §17.9) and refill everything. `keep_detail`
        leaves the detail panel as it is (after an edit made in it)."""
        keep = select or self._selected_key()
        try:
            of_type = search(self.library, self._type())
            self.items = search(
                self.library,
                self._type(),
                self._category(),
                self._tags(),
                self.text,
                has_variants=True if self.has_variants.isChecked() else None,
                udim=True if self.udim.isChecked() else None,
                workflow=self.workflow.currentData(),
                sort=self.sort.currentData(),
            )
        except ScheinwerkError as exc:
            self.count.setText(str(exc))
            return
        self._fill_categories(category_counts(of_type))
        self._fill_tags(tag_counts(of_type))
        self._fill_grid(keep, keep_detail)

    def _fill_categories(self, counts: dict[str, int]) -> None:
        current = self._category()
        self.categories.blockSignals(True)
        self.categories.clear()
        nodes: dict[str, QTreeWidgetItem] = {}
        for category, n in counts.items():
            parent, _, leaf = category.rpartition("/")
            node = QTreeWidgetItem([f"{leaf}  ({n})"])
            node.setData(0, ITEM, category)
            (
                nodes[parent].addChild(node)
                if parent in nodes
                else self.categories.addTopLevelItem(node)
            )
            nodes[category] = node
            if category == current:
                node.setSelected(True)
        self.categories.expandAll()
        self.categories.blockSignals(False)

    def _fill_tags(self, counts: dict[str, int]) -> None:
        checked = set(self._tags())
        self.tags.blockSignals(True)
        self.tags.clear()
        for tag, n in counts.items():
            entry = QListWidgetItem(f"{tag}  ({n})")
            entry.setData(ITEM, tag)
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(
                Qt.CheckState.Checked if tag in checked else Qt.CheckState.Unchecked
            )
            self.tags.addItem(entry)
        self.tags.blockSignals(False)

    def _label(self, item: Item) -> str:
        latest = item.latest()
        variants = len(latest.variants()) if latest else 0
        badge = f"  ·{variants}" if variants > 1 else ""
        flag = "" if latest else "\n(incomplete)"
        return f"{item.name}{badge}{flag}"

    def _fill_grid(self, keep: str | None, keep_detail: bool = False) -> None:
        self.grid.blockSignals(True)
        self.grid.clear()
        self._pending = []
        blank = self._blank()
        for item in self.items:
            entry = QListWidgetItem(blank, self._label(item))
            entry.setData(ITEM, item)
            entry.setToolTip(f"{item.type}/{item.id}")
            entry.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.grid.addItem(entry)
            self._pending.append(entry)
            if keep and f"{item.type}/{item.id}" == keep:
                entry.setSelected(True)
                self.grid.scrollToItem(entry)
        self.grid.blockSignals(False)
        self.count.setText(f"{len(self.items)} items")
        self._timer.start(0)
        if not keep_detail:
            self._show_detail()

    def _square(self, picture: QPixmap | None) -> QIcon:
        """`picture` centred on a square of the grid's icon size, so every name sits at the
        same height; without one, a framed "no preview" (colours from the theme's palette)."""
        size = self.grid.iconSize()
        canvas = QPixmap(size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        if picture is None:
            painter.setPen(self.grid.palette().color(QPalette.ColorRole.Mid))
            painter.drawRect(canvas.rect().adjusted(8, 8, -9, -9))
            painter.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, "no preview")
        else:
            x = (size.width() - picture.width()) // 2
            y = (size.height() - picture.height()) // 2
            painter.drawPixmap(x, y, picture)
        painter.end()
        return QIcon(canvas)

    def _blank(self) -> QIcon:
        return self._square(None)

    def _load_some_thumbnails(self) -> None:
        size = self.grid.iconSize()
        for _ in range(THUMBS_PER_TICK):
            if not self._pending:
                self._timer.stop()
                return
            entry = self._pending.pop(0)
            thumb = _main_thumbnail(entry.data(ITEM))
            pixmap = _pixmap(thumb, size) if thumb and thumb.is_file() else None
            if pixmap is not None:
                entry.setIcon(self._square(pixmap))
                entry.setData(HAS_PREVIEW, True)

    def _resize_grid(self) -> None:
        side = self.size.value()
        self.grid.setIconSize(QSize(side, side))
        self.grid.setGridSize(QSize(side + 24, side + 52))
        blank = self._blank()
        self._pending = [self.grid.item(i) for i in range(self.grid.count())]
        for entry in self._pending:
            entry.setIcon(blank)
        self._timer.start(0)

    def _selected_key(self) -> str | None:
        item = self.selected()
        return f"{item.type}/{item.id}" if item else None

    def selected(self) -> Item | None:
        chosen = self.grid.selectedItems()
        return chosen[0].data(ITEM) if chosen else None

    def select(self, key: str) -> None:
        """Show `type/id` (e.g. an entry that was just ingested)."""
        self.types.setCurrentIndex(0)
        self.categories.clearSelection()
        self.reload(select=key)

    # --- the selected item ---------------------------------------------------------------

    def _show_detail(self) -> None:
        item = self.selected()
        if item is None:
            note = QLabel("Select an item.")
            note.setObjectName("detail")
            note.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.detail.setWidget(note)
            return
        self.detail.setWidget(self._item_panel(item))

    def _item_panel(self, item: Item) -> QWidget:
        panel = QWidget()
        panel.setObjectName("itemPanel")
        form = QFormLayout(panel)
        form.setContentsMargins(16, 12, 16, 12)
        latest = item.latest()
        preview = QLabel("no preview yet")
        preview.setObjectName("preview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumHeight(220)
        form.addRow(preview)
        variants = QComboBox()
        variants.setObjectName("fieldBox")
        variants.addItems(list(latest.variants()) if latest else [])

        def show_variant(name: str) -> None:
            thumb = latest.thumbnail(name) if latest and name else None
            pixmap = _pixmap(thumb, QSize(400, 400)) if thumb and thumb.is_file() else None
            if pixmap is None:
                preview.setPixmap(QPixmap())
                preview.setText("no preview yet")
            else:
                preview.setPixmap(pixmap)

        variants.currentTextChanged.connect(show_variant)
        show_variant(variants.currentText())
        form.addRow("Variant", variants)

        meta = item.meta
        form.addRow("Id", QLabel(f"{item.type}/{item.id}"))

        def save(**changes) -> None:
            try:
                update_meta(item, **changes)
            except ScheinwerkError as exc:
                QMessageBox.warning(self, "Library", str(exc))
                return
            self.reload(keep_detail=True)

        def line(value: str, on_done, hint: str = "") -> QLineEdit:
            edit = QLineEdit(value)
            edit.setObjectName("field")
            edit.setPlaceholderText(hint)
            edit.editingFinished.connect(lambda e=edit: on_done(e.text()))
            return edit

        form.addRow(
            "Name", line(item.name, lambda t: t.strip() and t != item.name and save(name=t))
        )

        def set_list(key: str, text: str) -> None:
            new = [t.strip() for t in text.split(",") if t.strip()]
            old = getattr(item, key)
            if new != old:
                save(**{f"add_{key}": new, f"remove_{key}": [o for o in old if o not in new]})

        form.addRow(
            "Categories", line(", ".join(item.categories), lambda t: set_list("categories", t))
        )
        form.addRow("Tags", line(", ".join(item.tags), lambda t: set_list("tags", t)))
        for key, label in (
            ("description", "Description"),
            ("credits", "Credits"),
            ("license", "License"),
            ("source_url", "Source URL"),
        ):
            form.addRow(
                label,
                line(
                    str(meta.get(key) or ""),
                    lambda t, k=key: t != (meta.get(k) or "") and save(fields={k: t}),
                ),
            )
        if item.type in ("texture", "texture_set"):
            form.addRow("Size (m)", self._size(item, meta, save))
            form.addRow("Displacement", self._displacement(meta, save))

        versions = QLabel(self._versions_text(item))
        versions.setObjectName("detail")
        versions.setWordWrap(True)
        versions.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        title = QLabel("Versions")
        title.setObjectName("columnTitle")
        form.addRow(title)
        form.addRow(versions)
        return panel

    def _size(self, item: Item, meta: dict, save) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        size = meta.get("size_m") or [0.0, 0.0]
        spins = []
        for i, prefix in enumerate(("w ", "h ")):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 10000.0)
            spin.setDecimals(3)
            spin.setPrefix(prefix)
            spin.setSpecialValueText("not set")
            spin.setValue(size[i])
            spins.append(spin)
            row.addWidget(spin)

        def apply() -> None:
            w, h = (s.value() for s in spins)
            value = [w, h] if w > 0 and h > 0 else None
            if value != meta.get("size_m"):
                save(fields={"size_m": value})

        for spin in spins:
            spin.editingFinished.connect(apply)
        return box

    def _displacement(self, meta: dict, save) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        disp = meta.get("displacement") or {"mid": 0.5, "height_m": 0.0}
        mid, height = QDoubleSpinBox(), QDoubleSpinBox()
        mid.setRange(0.0, 1.0)
        mid.setSingleStep(0.05)
        mid.setPrefix("mid ")
        mid.setValue(disp["mid"])
        height.setRange(0.0, 100.0)
        height.setDecimals(4)
        height.setPrefix("height ")
        height.setSuffix(" m")
        height.setSpecialValueText("not set")
        height.setValue(disp["height_m"])

        def apply() -> None:
            value = {"mid": mid.value(), "height_m": height.value()} if height.value() else None
            if value != meta.get("displacement"):
                save(fields={"displacement": value})

        mid.editingFinished.connect(apply)
        height.editingFinished.connect(apply)
        row.addWidget(mid)
        row.addWidget(height)
        return box

    def _versions_text(self, item: Item) -> str:
        latest = item.latest()
        lines = []
        for v in item.versions():
            info = v.info
            if info is None:
                lines.append(f"{v.path.name}  incomplete")
                continue
            mark = "  (latest)" if latest and v.number == latest.number else ""
            recipe = [info.get("origin") or ""]
            if info.get("workflow"):
                recipe.append(info["workflow"])
            if info.get("metal_threshold") is not None:
                recipe.append(f"threshold {info['metal_threshold']}")
            if info.get("resolution"):
                recipe.append("×".join(map(str, info["resolution"])))
            variants = ", ".join(f"{k} v{n:03d}" for k, n in v.variants().items())
            comment = f"\n    {info['comment']}" if info.get("comment") else ""
            lines.append(
                f"{v.path.name}{mark}  {'  '.join(r for r in recipe if r)}\n    {variants}{comment}"
            )
        return "\n".join(lines) or "no versions"

    # --- right-click and drops -----------------------------------------------------------

    def _menu(self, pos: QPoint) -> None:
        hit = self.grid.itemAt(pos)
        item = hit.data(ITEM) if hit else None
        menu = QMenu(self)

        def add(label: str, func=None) -> None:
            action = menu.addAction(label)
            if func is None:
                action.setEnabled(False)
            else:
                action.triggered.connect(lambda _c=False: func())

        if item is None:
            add("New library asset (workshop, step L4)")
        else:
            latest = item.latest()
            rel = None
            if latest:
                target = latest.path / f"{item.id}.usd" if item.type == "model" else latest.path
                rel = target.relative_to(self.library.root).as_posix()
            add("Copy library path", (lambda: self._copy(rel)) if rel else None)
            add(
                "Copy $SW_LIBRARY path", (lambda: self._copy(f"$SW_LIBRARY/{rel}")) if rel else None
            )
            add("Reveal", lambda: reveal(item.path))
            menu.addSeparator()
            add("Add variant from files…", lambda: self._files_for(item, variant=True))
            add("New version from files…", lambda: self._files_for(item, variant=False))
            add("Open in workshop (step L4)")
            add("Rebuild…", (lambda: self._rebuild(item)) if latest else None)
            add("Render previews again (step L4)")
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    @staticmethod
    def _copy(text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    def _files_for(self, item: Item, variant: bool) -> None:
        name = None
        if variant:
            name, ok = QInputDialog.getText(self, "Add variant", "Variant name:")
            if not ok or not name.strip():
                return
        paths, _ = QFileDialog.getOpenFileNames(self, f"Files for {item.name}")
        if paths:
            self.ingestRequested.emit(
                [Path(p) for p in paths],
                {"item": item.id, "variant": name.strip() if name else None},
            )

    def _dropped(self, item: Item | None, paths: list[Path]) -> None:
        target = {"item": item.id, "variant": None} if item else None
        self.ingestRequested.emit(paths, target)

    def _rebuild(self, item: Item) -> None:
        latest = item.latest()
        args = ["lib", "rebuild", item.id]
        if latest and (latest.info or {}).get("workflow") == "spec_gloss":
            value, ok = QInputDialog.getDouble(
                self,
                "Rebuild",
                "Metal threshold:",
                (latest.info or {}).get("metal_threshold") or 0.2,
                0.05,
                1.0,
                2,
            )
            if not ok:
                return
            args += ["--metal-threshold", f"{value}"]
        self.count.setText(f"Rebuilding {item.name}…")

        def done(job) -> None:
            if job.ok:
                self.reload(select=f"{item.type}/{item.id}")
            else:
                QMessageBox.warning(self, "Rebuild", job.error)

        self.queue.submit(args, on_done=done)
