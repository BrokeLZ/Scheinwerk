"""The Ingest view (spec §17.11): dropped files -> entries -> edited plans -> `sw lib ingest`.

Detection and ingest run as `sw lib detect --json` / `sw lib ingest --plan` jobs. The view only
shows and edits plans (JSON dicts); nothing is written until an entry is submitted.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from scheinwerk.gui.library.jobs import Job, JobQueue

SET_ROLES = [
    "basecolor",
    "diffuse",
    "specular",
    "glossiness",
    "metalness",
    "roughness",
    "specular_level",
    "normal",
    "height",
    "ao",
    "opacity",
    "emission",
]
ROLES = {"texture_set": SET_ROLES, "hdri": ["hdri"], "texture": ["color", "data"], "model": []}
SKIP = "(skip)"
STATUS_TEXT = {
    "ready": "ready",
    "warning": "⚠ warning",
    "needs_input": "needs input",
    "queued": "queued",
    "processing": "processing…",
    "done": "done ✓",
    "failed": "failed",
}
SUBMITTABLE = ("ready", "warning", "failed")
ICON = QSize(56, 56)


@dataclass
class Entry:
    plan: dict
    status: str = ""  # ready / warning / needs_input / queued / processing / done / failed
    error: str = ""
    item: str = ""  # `type/id` once done
    job: Job | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.status = self.status or self.plan.get("status") or "ready"

    @property
    def busy(self) -> bool:
        return self.status in ("queued", "processing")


def _source_icon(plan: dict) -> QIcon:
    """A small picture of the first source Qt can read (png, jpg, tif); else none."""
    for files in plan.get("variants", {}).values():
        for f in files:
            path = f["path"].replace("<UDIM>", "1001")
            reader = QImageReader(path)
            if reader.canRead():
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(ICON, Qt.AspectRatioMode.KeepAspectRatio))
                image = reader.read()
                if not image.isNull():
                    return QIcon(QPixmap.fromImage(image))
    return QIcon()


def _split(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


class IngestView(QWidget):
    showItem = Signal(str)  # `type/id` of a finished entry
    ingested = Signal()  # an entry finished: Browse should reload

    def __init__(
        self, queue: JobQueue, spaces: list[str], item_ids: callable, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ingestView")
        self.queue = queue
        self.spaces = spaces
        self.item_ids = item_ids
        self.entries: list[Entry] = []
        self.unused: list[dict] = []
        self.detecting = 0
        self._filling = False

        top = QHBoxLayout()
        self.info = QLabel("")
        self.info.setObjectName("ingestInfo")
        top.addWidget(self.info, 1)
        for label, slot in (
            ("Add files…", self.add_files),
            ("Add folder…", self.add_folder),
            ("Ingest all", self.ingest_all),
        ):
            button = QPushButton(label)
            button.setObjectName("topButton")
            button.clicked.connect(lambda _c=False, s=slot: s())
            top.addWidget(button)

        self.list = QListWidget()
        self.list.setObjectName("entryList")
        self.list.setIconSize(ICON)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._show_detail)
        self.list.itemDoubleClicked.connect(self._open_done)

        self.detail = QScrollArea()
        self.detail.setObjectName("entryDetail")
        self.detail.setWidgetResizable(True)
        self.detail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.list)
        split.addWidget(self.detail)
        split.setSizes([380, 900])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        self._show_detail()

    # --- adding --------------------------------------------------------------------------

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files")
        if paths:
            self.add_paths([Path(p) for p in paths])

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder")
        if folder:
            self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path], target: dict | None = None) -> None:
        """Detect in the background; the entries appear when it is done."""
        self.detecting += 1
        self._update_info()
        self.queue.submit(
            ["lib", "detect", "--json", *map(str, paths)],
            on_done=lambda job: self._detected(job, target),
        )

    def _detected(self, job: Job, target: dict | None) -> None:
        self.detecting -= 1
        if not job.ok:
            self._update_info(f"Detection failed: {job.error}")
            return
        result = json.loads(job.out)
        self.add_plans(result.get("entries", []), result.get("unused", []), target)

    def add_plans(
        self, plans: list[dict], unused: list[dict] = (), target: dict | None = None
    ) -> None:
        for plan in plans:
            if target:
                plan["target"] = dict(target)
            self.entries.append(Entry(plan))
        self.unused += list(unused)
        self._fill()
        if plans:
            self.list.setCurrentRow(len(self.entries) - len(plans))
        self._update_info()

    def _update_info(self, extra: str = "") -> None:
        parts = []
        if self.detecting:
            parts.append("Detecting…")
        if self.unused:
            parts.append(f"{len(self.unused)} files not used")
        if extra:
            parts.append(extra)
        self.info.setText("   ".join(parts) or "Drop files, folders or zips here.")
        self.info.setToolTip(
            "\n".join(f"{Path(u['path']).name}: {u['reason']}" for u in self.unused)
        )

    # --- the list ------------------------------------------------------------------------

    def _fill(self) -> None:
        selected = {id(e) for e in self.selected()}
        self._filling = True
        self.list.clear()
        for entry in self.entries:
            plan = entry.plan
            item = QListWidgetItem(
                _source_icon(plan), f"{plan['name']}\n{plan['type']}   {STATUS_TEXT[entry.status]}"
            )
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(entry.error or "\n".join(plan.get("messages") or []))
            self.list.addItem(item)
            item.setSelected(id(entry) in selected)
        self._filling = False

    def _refresh_row(self, entry: Entry) -> None:
        row = self.entries.index(entry)
        item = self.list.item(row)
        if item is not None:
            item.setText(
                f"{entry.plan['name']}\n{entry.plan['type']}   {STATUS_TEXT[entry.status]}"
            )
            item.setToolTip(entry.error or "\n".join(entry.plan.get("messages") or []))

    def selected(self) -> list[Entry]:
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def _open_done(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry.status == "done" and entry.item:
            self.showItem.emit(entry.item)

    # --- submitting ----------------------------------------------------------------------

    def ingest_all(self) -> None:
        for entry in self.entries:
            if entry.status in ("ready", "warning"):
                self.submit(entry)

    def submit(self, entry: Entry) -> None:
        if entry.busy or entry.status == "done" or entry.status == "needs_input":
            return
        folder = Path(tempfile.mkdtemp(prefix="sw_ingest_"))
        plan_file = folder / "plan.json"
        plan_file.write_text(json.dumps(entry.plan, indent=2), encoding="utf-8")
        entry.status, entry.error = "queued", ""
        entry.job = self.queue.submit(
            ["lib", "ingest", "--plan", str(plan_file), "--yes"],
            on_done=lambda job, e=entry: self._ingested(e, job),
            on_start=lambda _job, e=entry: self._set_status(e, "processing"),
        )
        self._refresh_row(entry)
        self._show_detail()

    def _set_status(self, entry: Entry, status: str) -> None:
        entry.status = status
        self._refresh_row(entry)

    def _ingested(self, entry: Entry, job: Job) -> None:
        entry.job = None
        if job.ok:
            last = (job.out.strip().splitlines() or [""])[-1]
            entry.status, entry.item = "done", last.split(" ")[0]
            self.ingested.emit()
        else:
            entry.status, entry.error = "failed", job.error
        self._refresh_row(entry)
        if entry in self.selected():
            self._show_detail()

    def remove(self, entry: Entry) -> None:
        if entry.busy and not (entry.job and self.queue.cancel(entry.job)):
            return
        self.entries.remove(entry)
        self._fill()
        self._show_detail()

    # --- the detail panel ----------------------------------------------------------------

    def _show_detail(self) -> None:
        if self._filling:
            return
        chosen = self.selected()
        if len(chosen) > 1:
            panel = self._shared_editor(chosen)
        elif chosen:
            panel = self._editor(chosen[0])
        else:
            panel = QLabel("Select an entry to see and change what detection decided.")
            panel.setObjectName("detail")
            panel.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail.setWidget(panel)

    def _line(self, value: str, setter, placeholder: str = "") -> QLineEdit:
        edit = QLineEdit(value)
        edit.setObjectName("field")
        edit.setPlaceholderText(placeholder)
        edit.textEdited.connect(setter)
        return edit

    def _editor(self, entry: Entry) -> QWidget:
        plan = entry.plan
        locked = entry.busy or entry.status == "done"
        panel = QWidget()
        panel.setObjectName("entryPanel")
        form = QFormLayout(panel)
        form.setContentsMargins(16, 12, 16, 12)

        def changed() -> None:
            self._refresh_row(entry)

        title = QLabel(f"{plan['type']}   {STATUS_TEXT[entry.status]}")
        title.setObjectName("columnTitle")
        form.addRow(title)
        for message in [*plan.get("messages", []), *([entry.error] if entry.error else [])]:
            note = QLabel(message)
            note.setObjectName("entryMessage")
            note.setWordWrap(True)
            form.addRow(note)
        if entry.status == "done":
            note = QLabel(f"Ingested as {entry.item}. Double-click the entry to show it.")
            note.setObjectName("entryMessage")
            form.addRow(note)

        name = self._line(plan["name"], lambda t: (plan.update(name=t), changed()))
        form.addRow("Name", name)
        form.addRow("Target", self._target_editor(plan))
        form.addRow(self._files_table(entry))
        if plan["type"] == "texture_set":
            form.addRow("Workflow", self._workflow_editor(plan))
            form.addRow("Size (m)", self._size_editor(plan))
            form.addRow("Displacement", self._displacement_editor(plan))
        for key, label, hint in (
            ("categories", "Categories", "metal/painted, architecture"),
            ("tags", "Tags", "rust, worn"),
        ):
            form.addRow(
                label,
                self._line(
                    ", ".join(plan.get(key) or []),
                    lambda t, k=key: plan.update({k: _split(t)}),
                    hint,
                ),
            )
        for key, label in (
            ("credits", "Credits"),
            ("license", "License"),
            ("source_url", "Source URL"),
        ):
            form.addRow(
                label, self._line(plan.get(key) or "", lambda t, k=key: plan.update({k: t}))
            )

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        remove = QPushButton("Remove")
        remove.setObjectName("panelButton")
        remove.clicked.connect(lambda: self.remove(entry))
        go = QPushButton("Ingest")
        go.setObjectName("panelButton")
        go.clicked.connect(lambda: self.submit(entry))
        go.setEnabled(entry.status in SUBMITTABLE)
        remove.setEnabled(not entry.busy)
        buttons.addWidget(remove)
        buttons.addWidget(go)
        form.addRow(buttons)
        panel.setEnabled(True)
        for child in panel.findChildren(QWidget):
            if locked and child not in (remove, go) and not isinstance(child, QLabel):
                child.setEnabled(False)
        return panel

    def _target_editor(self, plan: dict) -> QWidget:
        target = plan.setdefault("target", {"item": None, "variant": None})
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        mode = QComboBox()
        mode.setObjectName("fieldBox")
        mode.addItems(["New item", "New version of item", "Variant of item"])
        mode.setCurrentIndex(0 if not target.get("item") else 2 if target.get("variant") else 1)
        item = QComboBox()
        item.setObjectName("fieldBox")
        item.setEditable(True)
        item.addItems(self.item_ids())
        item.setCurrentText(target.get("item") or "")
        variant = QLineEdit(target.get("variant") or "")
        variant.setObjectName("field")
        variant.setPlaceholderText("variant name")

        def apply() -> None:
            m = mode.currentIndex()
            item.setVisible(m > 0)
            variant.setVisible(m == 2)
            target["item"] = item.currentText().strip() or None if m > 0 else None
            target["variant"] = variant.text().strip() or None if m == 2 else None

        mode.currentIndexChanged.connect(lambda _i: apply())
        item.currentTextChanged.connect(lambda _t: apply())
        variant.textEdited.connect(lambda _t: apply())
        for w in (mode, item, variant):
            row.addWidget(w)
        apply()
        return box

    def _files_table(self, entry: Entry) -> QWidget:
        plan = entry.plan
        roles = ROLES.get(plan["type"], [])
        rows = [(v, f) for v, files in plan["variants"].items() for f in files]
        rows += [(None, {"path": p, "role": SKIP}) for p in plan.get("skipped") or []]
        headers = ["Variant", "File", "Role", "Colour space", "Flip G", "Invert", "Channel"]
        table = QTableWidget(len(rows), len(headers))
        table.setObjectName("filesTable")
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for r, (variant, f) in enumerate(rows):
            name = QLabel(Path(f["path"]).name)
            name.setToolTip(f["path"])
            table.setCellWidget(r, 0, QLabel(variant or ""))
            table.setCellWidget(r, 1, name)
            role = QComboBox()
            role.setObjectName("fieldBox")
            role.addItems([*roles, SKIP])
            role.setCurrentText(f["role"])
            role.currentTextChanged.connect(
                lambda text, v=variant, f=f: self._set_role(entry, v, f, text)
            )
            table.setCellWidget(r, 2, role)
            if variant is None:
                continue
            space = QComboBox()
            space.setObjectName("fieldBox")
            space.addItems(sorted({*self.spaces, "raw", f["color_space"]}))
            space.setCurrentText(f["color_space"])
            space.currentTextChanged.connect(lambda t, f=f: f.update(color_space=t))
            table.setCellWidget(r, 3, space)
            for col, key in ((4, "flip_green"), (5, "invert")):
                check = QCheckBox()
                check.setChecked(bool(f.get(key)))
                check.toggled.connect(lambda on, f=f, k=key: f.update({k: on}))
                cell = QWidget()
                centre = QHBoxLayout(cell)
                centre.setContentsMargins(0, 0, 0, 0)
                centre.setAlignment(Qt.AlignmentFlag.AlignCenter)
                centre.addWidget(check)
                table.setCellWidget(r, col, cell)
            channel = QComboBox()
            channel.setObjectName("fieldBox")
            channel.addItems(["-", "R", "G", "B"])
            channel.setCurrentIndex(0 if f.get("channel") is None else f["channel"] + 1)
            channel.currentIndexChanged.connect(
                lambda i, f=f: f.update(channel=None if i == 0 else i - 1)
            )
            table.setCellWidget(r, 6, channel)
        header = table.horizontalHeader()
        for col in range(len(headers)):
            mode = (
                QHeaderView.ResizeMode.Stretch
                if col == 1
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(col, mode)
        table.resizeRowsToContents()
        height = header.height() + sum(table.rowHeight(r) for r in range(len(rows)))
        table.setFixedHeight(min(height + 2 * table.frameWidth() + 4, 480))
        return table

    def _set_role(self, entry: Entry, variant: str | None, f: dict, role: str) -> None:
        """Change a role; `(skip)` moves a file to skipped, a role brings a skipped one in."""
        plan = entry.plan
        if variant is not None and role == SKIP:
            plan["variants"][variant].remove(f)
            plan.setdefault("skipped", []).append(f["path"])
        elif variant is None and role != SKIP:
            plan["skipped"].remove(f["path"])
            first = next(iter(plan["variants"]), "main")
            plan["variants"].setdefault(first, []).append(
                {
                    "path": f["path"],
                    "role": role,
                    "color_space": "raw",
                    "flip_green": False,
                    "invert": False,
                    "channel": None,
                }
            )
        else:
            f["role"] = role
            return
        self._show_detail()

    def _workflow_editor(self, plan: dict) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        workflow = QComboBox()
        workflow.setObjectName("fieldBox")
        workflow.addItems(["metal_rough", "spec_gloss"])
        workflow.setCurrentText(plan.get("workflow") or "metal_rough")
        threshold = QDoubleSpinBox()
        threshold.setRange(0.05, 1.0)
        threshold.setSingleStep(0.05)
        threshold.setPrefix("metal threshold ")
        threshold.setValue(plan.get("metal_threshold") or 0.2)

        def apply() -> None:
            spec = workflow.currentText() == "spec_gloss"
            threshold.setEnabled(spec)
            plan["workflow"] = workflow.currentText()
            plan["metal_threshold"] = threshold.value() if spec else None

        workflow.currentTextChanged.connect(lambda _t: apply())
        threshold.valueChanged.connect(lambda _v: apply())
        row.addWidget(workflow)
        row.addWidget(threshold)
        apply()
        return box

    def _size_editor(self, plan: dict) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        size = plan.get("size_m") or [0.0, 0.0]
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
            plan["size_m"] = [w, h] if w > 0 and h > 0 else None

        for spin in spins:
            spin.valueChanged.connect(lambda _v: apply())
        return box

    def _displacement_editor(self, plan: dict) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        disp = plan.get("displacement") or {"mid": 0.5, "height_m": 0.0}
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
            h = height.value()
            plan["displacement"] = {"mid": mid.value(), "height_m": h} if h > 0 else None

        mid.valueChanged.connect(lambda _v: apply())
        height.valueChanged.connect(lambda _v: apply())
        row.addWidget(mid)
        row.addWidget(height)
        return box

    def _shared_editor(self, entries: list[Entry]) -> QWidget:
        """Several entries selected: the fields they share, set for all (spec §17.11)."""
        panel = QFrame()
        panel.setObjectName("entryPanel")
        form = QFormLayout(panel)
        form.setContentsMargins(16, 12, 16, 12)
        title = QLabel(f"{len(entries)} entries: set for all of them")
        title.setObjectName("columnTitle")
        form.addRow(title)

        def first(key: str) -> object:
            values = [e.plan.get(key) for e in entries]
            return values[0] if all(v == values[0] for v in values) else None

        for key, label in (("categories", "Categories"), ("tags", "Tags")):
            current = first(key)
            form.addRow(
                label,
                self._line(
                    ", ".join(current or []),
                    lambda t, k=key: [e.plan.update({k: _split(t)}) for e in entries],
                    "different" if current is None else "",
                ),
            )
        for key, label in (
            ("credits", "Credits"),
            ("license", "License"),
            ("source_url", "Source URL"),
        ):
            current = first(key)
            form.addRow(
                label,
                self._line(
                    current or "",
                    lambda t, k=key: [e.plan.update({k: t}) for e in entries],
                    "different" if current is None else "",
                ),
            )
        go = QPushButton("Ingest selected")
        go.setObjectName("panelButton")
        go.clicked.connect(lambda: [self.submit(e) for e in entries])
        form.addRow(go)
        return panel
