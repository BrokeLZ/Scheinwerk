"""Right-click menus, double-click and drops (spec §12.2). Every entry is one core call."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMenu

from scheinwerk.core.entities import Department, Entity, Task, Workfile
from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.project import DEFAULTS, Project
from scheinwerk.core.publish import USD_SUFFIXES, finalize, ingest, set_current
from scheinwerk.core.settings import app_for
from scheinwerk.core.system import open_path, reveal
from scheinwerk.core.templates import parse_fps, parse_resolution
from scheinwerk.core.versions import FileGroup, Product, Version
from scheinwerk.gui import dialogs

if TYPE_CHECKING:
    from scheinwerk.gui.browser import Browser

DEFAULT_EXTENSIONS = ("hip", "nk", "blend")


def _add(menu: QMenu, label: str, func: Callable[[], object] | None) -> None:
    action = menu.addAction(label)
    if func is None:
        action.setEnabled(False)
    else:
        action.triggered.connect(lambda _checked=False: func())  # drop Qt's `checked`


def _copy(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


def _existing(path: Path) -> Path:
    """`path`, or its nearest existing parent (a sequence's _seq may not exist yet)."""
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def _path_actions(b: Browser, menu: QMenu, path: Path | None, relative: bool = True) -> None:
    menu.addSeparator()
    _add(menu, "Copy path", (lambda: _copy(str(path))) if path else None)
    if relative:
        _add(menu, "Copy relative path", (lambda: _copy(b.project.rel(path))) if path else None)
    _add(menu, "Reveal", (lambda: b.run(reveal, _existing(path))) if path else None)


# --- top bar ------------------------------------------------------------------


def new_project(b: Browser) -> None:
    location = b.project.root.parent if b.project else None
    answer = dialogs.ask_new_project(b, location, DEFAULTS)
    if not answer:
        return
    where, name, fps, resolution, frame_start = answer

    def create() -> Project:
        if not where:
            raise ScheinwerkError("Choose a location for the project folder.")
        return Project.create(
            Path(where) / name,
            name,
            fps=parse_fps(fps),
            resolution=list(parse_resolution(resolution)),
            frame_start=frame_start,
        )

    project = b.run(create)
    if project:
        b.set_project(project.root)


def open_project(b: Browser) -> None:
    folder = dialogs.pick_folder(b, "Choose a project folder (or any folder inside one)")
    if folder is None:
        return
    project = Project.find(folder)
    if project is None:
        dialogs.error(b, ScheinwerkError(f"No scheinwerk.json in {folder} or above."))
    else:
        b.set_project(project.root)


# --- entity column --------------------------------------------------------------


def entity_menu(b: Browser, data: object) -> QMenu:
    menu = QMenu(b)
    p = b.project
    if p is None:
        _add(menu, "No project open", None)
        return menu
    category, sequence = b.entity_context(data)  # the right-clicked item

    def new_asset() -> None:
        answer = dialogs.ask_asset(b, p.category_choices(), category)
        if answer:
            cat, name = answer
            b.entity_key = f"asset:{name}"
            b.run(p.create_asset, name, cat)

    def new_category() -> None:
        name = dialogs.ask_text(b, "New category", "Name", hint="char")
        if name:
            b.entity_key = f"cat:{name}"
            b.run(p.create_category, name)

    def new_sequence() -> None:
        name = dialogs.ask_sequence(b, p.next_sequence_name)
        if name:
            b.entity_key = f"seqgroup:{name}"
            b.run(p.create_sequence, name)

    def new_shot() -> None:
        sequences = [s.name for s in p.sequences()]
        answer = b.run(
            dialogs.ask_shot, b, sequences, sequence, p.next_sequence_name, p.next_shot_name
        )
        if answer:
            b.entity_key = f"shot:{answer[0]}"
            b.run(p.create_shot, *answer)

    def set_frames(entity: Entity) -> None:
        frames = b.run(dialogs.ask_frames, b, entity.frames)
        if frames:
            b.run(entity.set_frames, *frames)

    if b.mode == "assets":
        _add(menu, "New asset…", new_asset)
        _add(menu, "New category…", new_category)
    else:
        _add(menu, "New sequence…", new_sequence)
        _add(menu, "New shot…", new_shot)
    can_frame = isinstance(data, Entity) and data.type != "sequence"
    _add(menu, "Set frame range…", (lambda: set_frames(data)) if can_frame else None)

    path = None
    if isinstance(data, Entity):
        path = data.path
    elif isinstance(data, tuple):
        path = p.root / ("assets" if data[0] == "category" else "shots") / data[1]
    _path_actions(b, menu, path)
    return menu


# --- columns 2-4 --------------------------------------------------------------------


def column_menu(b: Browser, i: int, data: object) -> QMenu:
    menu = QMenu(b)
    if b.entity() is None:
        _add(menu, "Select an asset or shot first", None)
        return menu
    if b.view == "scenefiles":
        (_department_menu, _task_menu, _file_menu)[i](b, menu, data)
    else:
        (_product_menu, _version_menu, _group_menu)[i](b, menu, data)
    return menu


def _department_menu(b: Browser, menu: QMenu, data: object) -> None:
    entity = b.entity()

    def new_department() -> None:
        existing = {d.name for d in entity.departments()}
        template = b.project.department_template(entity.type)
        answer = dialogs.ask_department(b, [n for n in template if n not in existing])
        if answer and answer[0]:
            name, create_main = answer
            b.remember(0, name)
            b.run(entity.create_department, name, ("main",) if create_main else ())

    _add(menu, "New department…", new_department)
    _path_actions(b, menu, data.path if isinstance(data, Department) else None, relative=False)


def _task_menu(b: Browser, menu: QMenu, data: object) -> None:
    dept = b.department()

    def new_task() -> None:
        name = dialogs.ask_text(b, "New task", "Name", hint="blockout")
        if name:
            b.remember(1, name)
            b.run(dept.create_task, name)

    _add(menu, "New task…", new_task if dept else None)
    _path_actions(b, menu, data.path if isinstance(data, Task) else None, relative=False)


def _extensions(b: Browser, task: Task) -> list[str]:
    templates = b.project.root / "shared" / "templates"
    from_templates = {
        p.name.split(".", 1)[1]
        for p in b.project.scan(templates, dirs_only=False)
        if p.name.startswith("empty.")
    }
    exts = set(DEFAULT_EXTENSIONS) | set(b.settings.get("dcc") or {}) | from_templates
    exts |= {w.ext for w in task.workfiles()}
    return sorted(exts)


def _open(b: Browser, path: Path, ext: str | None = None) -> None:
    b.run(open_path, path, app_for(b.settings, ext) if ext else None)


def _file_menu(b: Browser, menu: QMenu, data: object) -> None:
    task = b.task()
    if isinstance(data, Workfile):
        _add(menu, "Open", lambda: _open(b, data.path, data.ext))
        sub = menu.addMenu("Open with")
        for entry in (b.settings.get("dcc") or {}).values():
            if entry.get("exe"):
                _add(
                    sub,
                    entry.get("name") or entry["exe"],
                    lambda e=entry["exe"]: b.run(open_path, data.path, e),
                )
        _add(sub, "System default", lambda: b.run(open_path, data.path))

        def bump() -> None:
            new = b.run(task.new_version_from, data)
            if new:
                b.remember(2, new.name)
                b.reload()

        _add(menu, "New version from this", bump)
        _path_actions(b, menu, data.path)
        menu.addSeparator()
    elif isinstance(data, Path):  # unmanaged
        _add(menu, "Open", lambda: b.run(open_path, data))
        _path_actions(b, menu, data)
        menu.addSeparator()
    if task is None:
        _add(menu, "Select a task first", None)
        return
    exts = _extensions(b, task)
    templates = b.project.root / "shared" / "templates"

    def new_empty(ext: str) -> None:
        new = b.run(task.new_empty_workfile, ext)
        if new:
            b.remember(2, new.name)
            b.reload()

    sub = menu.addMenu("New empty workfile")
    for ext in exts:
        has_template = (templates / f"empty.{ext}").is_file()
        _add(
            sub,
            f".{ext}" + ("" if has_template else "  (no template)"),
            (lambda e=ext: new_empty(e)) if has_template else None,
        )
    _add(menu, "Copy next version path", lambda: _copy(str(task.next_workfile())))
    _add(menu, "Ingest file(s)…", lambda: _ingest(b, task))


def _ingest(b: Browser, target: Task | Product, files: list[Path] | None = None) -> None:
    files = files if files is not None else dialogs.pick_files(b)
    if files:
        b.run(ingest, files, target)


def _product_menu(b: Browser, menu: QMenu, data: object) -> None:
    entity = b.entity()
    media = b.view == "media"
    product = data if isinstance(data, Product) else None

    def new() -> None:
        kind = "media" if media else "product"
        name = dialogs.ask_text(
            b, f"New {kind}", "Name", hint="render_beauty" if media else "pants_drape"
        )
        if name:
            b.remember(0, name)
            b.run(entity.create_media if media else entity.create_product, name)

    _add(menu, "New media…" if media else "New product…", new)
    _add(menu, "Ingest file(s)…", (lambda: _ingest(b, product)) if product else None)
    _path_actions(b, menu, product.path if product else None, relative=False)


def _usd_files(version: Version) -> list[str]:
    return sorted(p.name for p in version.files() if p.suffix in USD_SUFFIXES and p.is_file())


def _version_menu(b: Browser, menu: QMenu, data: object) -> None:
    product = b.product()
    if product is None:
        _add(menu, "Select a product first", None)
        return

    def copy_next() -> None:
        path = b.run(product.next_version_path)  # creates the v### folder
        if path:
            _copy(str(path))
            b.remember(1, path.parent.name)
            b.reload()  # show and select the new (still empty) version

    _add(menu, "Copy next version path", copy_next)
    if not isinstance(data, Version):
        return
    menu.addSeparator()

    def do_finalize() -> None:
        usd = _usd_files(data) if product.usd else []
        current = product.current() if product.usd else None
        default = next((n for n in usd if n.startswith(f"{b.entity().name}_{product.name}_")), None)
        if current and current.number == data.number:
            default = None
        answer = dialogs.ask_finalize(b, (data.info or {}).get("comment", ""), usd, default)
        if answer:
            comment, main = answer
            b.run(finalize, data.path, comment=comment, main_file=main)

    _add(menu, "Open folder", lambda: b.run(open_path, data.path))
    _add(menu, "Finalize / Edit comment…", do_finalize)
    if product and product.usd:
        _add(menu, "Set as current", lambda: b.run(set_current, data.path))
    _path_actions(b, menu, data.path)


def _group_menu(b: Browser, menu: QMenu, data: object) -> None:
    if not isinstance(data, FileGroup):
        _add(menu, "Select a file first", None)
        return
    first = data.paths[0]
    _add(menu, "Open", lambda: b.run(open_path, first))
    _path_actions(b, menu, first)


# --- double-click and drops -------------------------------------------------------


def activate(b: Browser, i: int, data: object) -> None:
    """Double-click: open a workfile or file, reveal a version (spec §12.2)."""
    if isinstance(data, Workfile):
        _open(b, data.path, data.ext)
    elif isinstance(data, Path):
        b.run(open_path, data)
    elif isinstance(data, Version):
        b.run(reveal, data.path)
    elif isinstance(data, FileGroup):
        b.run(open_path, data.paths[0])


def drop(b: Browser, i: int, data: object, files: list[Path]) -> None:
    """Files dropped on a task -> next workfile versions; on a product/media -> next version."""
    if b.view == "scenefiles":
        target = data if isinstance(data, Task) else b.task() if i == 2 else None
        if i == 0 or target is None:
            dialogs.error(b, FileNotFoundError("Drop files onto a task or into the Files column."))
            return
    else:
        target = data if isinstance(data, Product) else b.product() if i > 0 else None
        if target is None:
            dialogs.error(b, FileNotFoundError("Drop files onto a product or media name."))
            return
    _ingest(b, target, files)
