"""The browser (spec §12). A plain QWidget so Houdini and Nuke can dock it.

Layout (mock-up): top bar / entity column | (col 2 | col 3) over the detail panel | col 4.
Every column is filled from one core call; selections are remembered per view.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from scheinwerk.core.context import Context
from scheinwerk.core.entities import Department, Entity, Task, Workfile
from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.project import Project
from scheinwerk.core.settings import add_recent_project, load_settings
from scheinwerk.core.versions import Product, Version, file_sequences
from scheinwerk.gui import actions, dialogs
from scheinwerk.gui.columns import Column, Detail, Row

VIEWS = ("scenefiles", "products", "media")
TITLES = {
    "scenefiles": ("Departments:", "Tasks:", "Files:", "Task detail"),
    "products": ("Products:", "Versions:", "Files:", "Version detail"),
    "media": ("Media:", "Versions:", "Files:", "Version detail"),
}
REFOCUS_RELOAD_SECONDS = 2.0
OPEN_PROJECT, NEW_PROJECT = "<open>", "<new>"  # project dropdown entries that are actions


def load_theme() -> str:
    return Path(__file__).with_name("theme.qss").read_text(encoding="utf-8")


def _frames(frames: tuple[int, int] | None) -> str:
    return f"{frames[0]}-{frames[1]}" if frames else "-"


class Browser(QWidget):
    picked = Signal()  # double-click while picking (see gui/pick.py)

    def __init__(self, path: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("browser")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)  # paint the QSS background
        self.setStyleSheet(load_theme())  # on the widget, not the app: never restyle a host DCC
        self.settings = load_settings()
        self.project: Project | None = None
        last = self.settings["gui"].get("last_view")
        self.view = last if last in VIEWS else "scenefiles"
        self.mode = "assets"
        self.entity_key: str | None = None
        self.memory: dict[str, list[str | None]] = {v: [None, None, None] for v in VIEWS}
        self.product_filter: Callable[[Product], bool] | None = None
        self._last_reload = 0.0
        self._watched: QObject | None = None
        self._build()
        self._connect()
        self.set_view(self.view)
        self.open_start(path)

    # --- layout -------------------------------------------------------------

    def _build(self) -> None:
        top = QWidget()
        top.setObjectName("topBar")
        bar = QHBoxLayout(top)
        self.view_buttons = QButtonGroup(self)
        switch = QWidget()
        switch.setObjectName("viewSwitch")
        switch_layout = QHBoxLayout(switch)
        switch_layout.setContentsMargins(0, 0, 0, 0)
        switch_layout.setSpacing(0)
        for view in VIEWS:
            button = QPushButton(view.capitalize())
            button.setObjectName("viewButton")
            button.setCheckable(True)
            button.setProperty("view", view)
            self.view_buttons.addButton(button)
            switch_layout.addWidget(button)
        self.project_box = QComboBox()
        self.project_box.setObjectName("projectBox")
        self.project_box.setMinimumWidth(200)
        self.project_box.setPlaceholderText("No project")
        self.reload_button = QPushButton("Reload")
        self.reload_button.setObjectName("topButton")
        bar.addStretch(1)
        bar.addWidget(switch)
        bar.addStretch(2)
        bar.addWidget(self.project_box)
        bar.addWidget(self.reload_button)

        line = QFrame()
        line.setObjectName("topLine")
        line.setFrameShape(QFrame.Shape.HLine)

        entity_panel = QWidget()
        entity_layout = QVBoxLayout(entity_panel)
        entity_layout.setContentsMargins(0, 0, 0, 0)
        toggle = QHBoxLayout()
        toggle.setSpacing(0)
        toggle.addStretch()
        self.mode_buttons = QButtonGroup(self)
        for mode in ("assets", "shots"):
            button = QPushButton(mode.capitalize())
            button.setObjectName("modeButton")
            button.setCheckable(True)
            button.setChecked(mode == self.mode)
            button.setProperty("mode", mode)
            self.mode_buttons.addButton(button)
            toggle.addWidget(button)
        toggle.addStretch()
        entity_layout.addLayout(toggle)
        self.entities = Column(selectable=lambda data: isinstance(data, Entity))
        entity_layout.addWidget(self.entities)

        self.cols = [Column("", accepts_drops=True) for _ in range(3)]
        self.detail = Detail()
        pair = QSplitter(Qt.Orientation.Horizontal)
        pair.addWidget(self.cols[0])
        pair.addWidget(self.cols[1])
        middle = QSplitter(Qt.Orientation.Vertical)
        middle.addWidget(pair)
        middle.addWidget(self.detail)
        middle.setSizes([500, 220])
        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(entity_panel)
        main.addWidget(middle)
        main.addWidget(self.cols[2])
        main.setSizes([240, 440, 520])
        main.setStretchFactor(2, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(top)
        layout.addWidget(line)
        layout.addWidget(main, 1)

    def _connect(self) -> None:
        self.view_buttons.buttonClicked.connect(lambda b: self.set_view(b.property("view")))
        self.mode_buttons.buttonClicked.connect(lambda b: self.set_mode(b.property("mode")))
        self.project_box.activated.connect(self._project_chosen)
        self.reload_button.clicked.connect(self.reload)
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_F5), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.reload)

        self.entities.selectionChanged.connect(self._entity_changed)
        self.entities.menuRequested.connect(
            lambda data, pos: actions.entity_menu(self, data).exec(pos)
        )
        for i, col in enumerate(self.cols):
            col.selectionChanged.connect(lambda i=i: self._column_changed(i))
            col.menuRequested.connect(
                lambda data, pos, i=i: actions.column_menu(self, i, data).exec(pos)
            )
            col.activated.connect(lambda data, i=i: actions.activate(self, i, data))
            col.filesDropped.connect(lambda data, paths, i=i: actions.drop(self, i, data, paths))

    # --- refresh when the window gets focus ----------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        window = self.window()
        if window is not self._watched:
            window.installEventFilter(self)
            self._watched = window

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.WindowActivate
            and time.monotonic() - self._last_reload > REFOCUS_RELOAD_SECONDS
        ):
            self.reload()
        return False

    # --- project / view / mode --------------------------------------------------

    def open_start(self, path: Path | None) -> None:
        """Open the project around `path`, else the most recent one that still exists."""
        if path is not None:
            project = Project.find(path)
            if project is None:
                dialogs.error(self, ScheinwerkError(f"{path} is not inside a Scheinwerk project."))
            else:
                self.select_context(path)
                self.set_project(project.root)
                return
        for recent in self.settings["recent_projects"]:
            if (Path(recent) / "scheinwerk.json").is_file():
                self.set_project(Path(recent))
                return
        self.set_project(None)

    def select_context(self, path: Path) -> None:
        """Pre-select the entity, department and task a path points at."""
        try:
            ctx = Context.from_path(path)
        except ScheinwerkError:
            return
        if ctx is None:
            return
        prefix = {"asset": "asset", "shot": "shot", "sequence": "seq"}[ctx.entity_type]
        self.mode = "assets" if ctx.entity_type == "asset" else "shots"
        self.entity_key = f"{prefix}:{ctx.entity}"
        self.memory["scenefiles"][:2] = [ctx.dept, ctx.task]
        for button in self.mode_buttons.buttons():
            button.setChecked(button.property("mode") == self.mode)

    def preselect(
        self, entity: Entity | None, product_key: str | None, version_key: str | None
    ) -> None:
        """Select an entity (switching Assets/Shots), then remembered product/version keys."""
        if entity is not None:
            prefix = {"asset": "asset", "shot": "shot", "sequence": "seq"}[entity.type]
            self.entity_key = f"{prefix}:{entity.name}"
            self.mode = "assets" if entity.type == "asset" else "shots"
            for button in self.mode_buttons.buttons():
                button.setChecked(button.property("mode") == self.mode)
        self.memory[self.view][:2] = [product_key, version_key]
        self.reload()

    def set_project(self, root: Path | None) -> None:
        self.project = Project.find(root) if root else None
        if self.project is not None:
            add_recent_project(self.project.root)
        self.settings = load_settings()
        self._fill_project_box()
        self.reload()

    def _fill_project_box(self) -> None:
        """Recent projects, then the two project actions (spec §12.1)."""
        box = self.project_box
        box.clear()
        for recent in self.settings["recent_projects"]:
            if (Path(recent) / "scheinwerk.json").is_file():
                box.addItem(Path(recent).name, recent)
                box.setItemData(box.count() - 1, recent, Qt.ItemDataRole.ToolTipRole)
        if box.count():
            box.insertSeparator(box.count())
        box.addItem("Open existing project…", OPEN_PROJECT)
        box.addItem("New project…", NEW_PROJECT)
        box.setCurrentIndex(box.findData(str(self.project.root)) if self.project else -1)

    def _project_chosen(self, index: int) -> None:
        data = self.project_box.itemData(index)
        if data == OPEN_PROJECT:
            actions.open_project(self)
        elif data == NEW_PROJECT:
            actions.new_project(self)
        else:
            self.set_project(Path(data))
            return
        self._fill_project_box()  # cancelled: show the open project again

    def set_view(self, view: str) -> None:
        self.view = view
        for button in self.view_buttons.buttons():
            button.setChecked(button.property("view") == view)
        for col, title in zip(self.cols, TITLES[view], strict=False):
            col.set_title(title)
        self._fill_from(0)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        for button in self.mode_buttons.buttons():
            button.setChecked(button.property("mode") == mode)
        self._fill_entities()

    def reload(self) -> None:
        self._last_reload = time.monotonic()
        if self.project is not None:
            self.project = Project.find(self.project.root)  # re-read scheinwerk.json
        self._fill_entities()

    # --- filling ----------------------------------------------------------------

    def _entity_row(self, e: Entity) -> Row:
        prefix = {"asset": "asset", "shot": "shot", "sequence": "seq"}[e.type]
        label = f"{e.name} (sequence)" if e.type == "sequence" else e.name
        tip = f"{self.project.rel(e.path)}\nframes {_frames(e.frames)}"
        if not e.valid:
            tip += "\ninvalid name"
        return Row(label, e, key=f"{prefix}:{e.name}", dim=not e.valid, tooltip=tip)

    def _entity_rows(self) -> list[Row]:
        p = self.project
        if p is None:
            return []
        if self.mode == "assets":
            assets = p.assets()
            rows = [self._entity_row(a) for a in assets if a.category is None]
            for cat in p.categories():
                children = [self._entity_row(a) for a in assets if a.category == cat]
                rows.append(Row(cat, ("category", cat), key=f"cat:{cat}", children=children))
            return rows
        return [
            Row(
                s.name,
                ("sequence", s.name),
                key=f"seqgroup:{s.name}",
                dim=not s.valid,
                children=[self._entity_row(s), *(self._entity_row(x) for x in p.shots(s.name))],
            )
            for s in p.sequences()
        ]

    def _fill_entities(self) -> None:
        self.entities.set_rows(self._entity_rows(), select=self.entity_key)
        self.entity_key = self.entities.current_key()
        self._fill_from(0)

    def _entity_changed(self) -> None:
        self.entity_key = self.entities.current_key()
        self._fill_from(0)

    def _column_changed(self, i: int) -> None:
        self.memory[self.view][i] = self.cols[i].current_key()
        self._fill_from(i + 1)

    def _fill_from(self, index: int) -> None:
        """Refill columns `index`.. from the selections to their left, restoring memory."""
        for i in range(index, 3):
            rows = self._rows(i)
            # The remembered row if it's there, else the first (spec §12.1).
            self.cols[i].set_rows(rows, select=self.memory[self.view][i])
        self._update_detail()

    def _rows(self, i: int) -> list[Row]:
        entity = self.entity()
        if entity is None:
            return []
        if self.view == "scenefiles":
            if i == 0:
                return [self._named_row(d, d.custom) for d in entity.departments()]
            dept = self.department()
            if i == 1:
                return [self._named_row(t, t.custom) for t in dept.tasks()] if dept else []
            task = self.task()
            if task is None:
                return []
            rows = [Row(w.path.name, w, key=w.path.name) for w in task.workfiles()]
            rows += [
                Row(
                    p.name,
                    p,
                    key=f"u:{p.name}",
                    dim=True,
                    tooltip="unmanaged: not a workfile name of this task",
                )
                for p in task.unmanaged()
            ]
            return rows
        if i == 0:
            products = entity.products() if self.view == "products" else entity.media()
            if self.product_filter is not None:  # the picker shows one kind only
                products = [p for p in products if self.product_filter(p)]
            rows = [self._product_row(p) for p in products]
            layers = [r for r, p in zip(rows, products, strict=True) if p.usd]
            others = [r for r, p in zip(rows, products, strict=True) if not p.usd]
            if not layers:
                return rows
            grouped = [Row("USD layers", None, key="grp:usd", children=layers)]
            if others:
                grouped.append(Row("Products", None, key="grp:products", children=others))
            return grouped
        product = self.product()
        if i == 1:
            if product is None:
                return []
            current = product.current()
            return [
                Row(
                    v.path.name + ("  (current)" if current and current.number == v.number else ""),
                    v,
                    key=v.path.name,
                    dim=v.empty,
                    tooltip=(v.info or {}).get("comment", "") or ("empty" if v.empty else ""),
                )
                for v in product.versions()
            ]
        version = self.version()
        if version is None:
            return []
        rows = []
        for group in file_sequences(version.files()):
            label = group.label
            if group.frames:
                label += f"  {_frames(group.frames)} ({group.count})"
                if group.missing:
                    label += f", {group.missing} missing"
            rows.append(Row(label, group, key=group.label))
        return rows

    def _named_row(self, item: Department | Task, custom: bool) -> Row:
        label = item.name + ("  (custom)" if custom else "")
        return Row(
            label, item, key=item.name, dim=not item.valid, tooltip=self.project.rel(item.path)
        )

    def _product_row(self, p: Product) -> Row:
        key = ("usd:" if p.usd else "") + p.name
        return Row(p.name, p, key=key, dim=not p.valid, tooltip=self.project.rel(p.path))

    def _update_detail(self) -> None:
        title = TITLES[self.view][3]
        entity = self.entity()
        if self.project is None:
            self.detail.set_fields("No project. Use + to create one or add an existing one.", [])
            return
        if entity is None:
            self.detail.set_fields(title, [])
            return
        rel = self.project.rel
        if self.view == "scenefiles":
            task, workfile = self.task(), self.workfile()
            latest = task.latest_workfile() if task else None
            fields = [("path", rel(workfile.path if workfile else (task or entity).path))]
            if task:
                fields.append(("latest", latest.path.name if latest else "-"))
            fields.append(("frames", _frames(entity.frames)))
            self.detail.set_fields(title, fields)
            return
        product, version = self.product(), self.version()
        if version is not None:
            info = version.info or {}
            fields = [("path", rel(version.path))]
            fields += [
                (k, str(info.get(k) or "-"))
                for k in ("source", "comment", "created", "user", "dcc")
            ]
            if product.usd:
                current = product.current()
                fields.append(
                    ("current", "yes" if current and current.number == version.number else "no")
                )
            fields.append(("files", str(len(version.files()))))
        elif product is not None:
            latest = product.latest()
            fields = [
                ("path", rel(product.path)),
                ("versions", str(len(product.versions()))),
                ("latest", latest.path.name if latest else "-"),
            ]
            if product.usd:
                current = product.current()
                fields.append(("current", current.path.name if current else "-"))
        else:
            fields = [("frames", _frames(entity.frames))]
        self.detail.set_fields(title, fields)

    # --- current selection --------------------------------------------------------

    def entity(self) -> Entity | None:
        data = self.entities.current_data()
        return data if isinstance(data, Entity) else None

    def entity_context(self, data: object = None) -> tuple[str | None, str | None]:
        """(category, sequence) of an entity-column item (default: the selection), for the
        New asset / New shot presets. A category or sequence folder counts as itself."""
        if data is None:
            data = self.entities.current_data()
        if isinstance(data, Entity):
            return data.category, data.sequence
        if isinstance(data, tuple):
            return (data[1], None) if data[0] == "category" else (None, data[1])
        return None, None

    def _current(self, i: int, kind: type) -> object:
        data = self.cols[i].current_data()
        return data if isinstance(data, kind) else None

    def department(self) -> Department | None:
        return self._current(0, Department) if self.view == "scenefiles" else None

    def task(self) -> Task | None:
        return self._current(1, Task) if self.view == "scenefiles" else None

    def workfile(self) -> Workfile | None:
        return self._current(2, Workfile) if self.view == "scenefiles" else None

    def product(self) -> Product | None:
        return self._current(0, Product) if self.view != "scenefiles" else None

    def version(self) -> Version | None:
        return self._current(1, Version) if self.view != "scenefiles" else None

    # --- running actions ------------------------------------------------------------

    def run(self, func, *args, **kwargs) -> object:
        """Call core; show its error in a dialog instead of raising. Reloads afterwards."""
        try:
            return func(*args, **kwargs)
        except (ScheinwerkError, OSError) as exc:
            dialogs.error(self, exc)
            return None
        finally:
            self.reload()

    def remember(self, column: int, key: str) -> None:
        """Select `key` in a column after the next reload (e.g. something just created)."""
        self.memory[self.view][column] = key
