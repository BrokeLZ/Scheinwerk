"""Houdini integration (spec §13.2). Runs inside Houdini only: it imports `hou`.

In parameter expressions (Python):  import scheinwerk.dcc.houdini as sw
    sw.cache("sim")                       …/<task>/cache/sim
    sw.publish_path("pants", "abc")       …/publish/pants/v003/hero_pants_v003.abc
    sw.usd_path("lgt")                    …/publish/_usd/lgt/v004/sq010_0010_lgt_v004.usd
    sw.media_path("render_beauty", "exr") …/media/render_beauty/v002/…_v002.1001.exr
    sw.shots()                            [("sq010_0010", (1001, 1096)), …]

Every path decision is a core call; this module only reads the scene and the nodes.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path, PurePosixPath

import hou

from scheinwerk.core.context import Context
from scheinwerk.core.entities import Entity, Task
from scheinwerk.core.env import cleared_env, env_for
from scheinwerk.core.errors import NotFound, ScheinwerkError
from scheinwerk.core.hooks import run_hook
from scheinwerk.core.project import Project
from scheinwerk.core.publish import finalize
from scheinwerk.core.templates import format_version, parse_version, validate_name
from scheinwerk.core.versions import Product, Version, file_sequences

log = logging.getLogger("scheinwerk.houdini")

EXTENSIONS = ("hip", "hipnc", "hiplc")
SHOT_OPTION = "SW_SHOT"  # context option naming the target shot in a sequence scene


# --- the open scene --------------------------------------------------------------


def current_file() -> Path | None:
    return None if hou.hipFile.isNewFile() else Path(hou.hipFile.path())


def context(path: Path | None = None) -> Context | None:
    """Context of `path` (default: the open scene); None outside a project or entity."""
    path = path or current_file()
    if path is None:
        return None
    try:
        return Context.from_path(path)
    except ScheinwerkError:
        return None


def _project_and_context() -> tuple[Project, Context]:
    ctx = context()
    if ctx is None:
        raise ScheinwerkError("This scene isn't saved inside a Scheinwerk asset or shot.")
    return Project.find(ctx.root), ctx


def _task() -> Task:
    project, ctx = _project_and_context()
    if not (ctx.dept and ctx.task):
        raise ScheinwerkError("This scene isn't saved inside a task (<dept>/<task>/work).")
    return project.entity_at(ctx).department(ctx.dept).task(ctx.task)


def _shot_option() -> str:
    if not hou.hasContextOption(SHOT_OPTION):
        return ""
    return str(hou.contextOption(SHOT_OPTION)).strip()


def target_entity(shot: str | None = None) -> Entity:
    """Where publishes and renders go: the scene's entity. In a sequence scene, the shot
    given here, else the one in the SW_SHOT context option (spec §13.2.7)."""
    project, ctx = _project_and_context()
    entity = project.entity_at(ctx)
    if entity.type != "sequence":
        return entity
    shot = shot or _shot_option()
    if not shot:
        raise ScheinwerkError(
            f"This is a scene of sequence {entity.name}: choose the shot to publish to "
            f"(the node's Shot menu, or the {SHOT_OPTION} context option)."
        )
    target = Entity(project, "shot", shot, sequence=entity.name)
    if not target.path.is_dir():
        raise NotFound(f"Shot {shot} doesn't exist in sequence {entity.name}.")
    return target


# --- environment (spec §7.2) and scene callbacks --------------------------------------


def apply_env(path: Path | None = None) -> Context | None:
    """Set SW_* and JOB from `path` (default: the open scene), in Houdini and os.environ
    (hou.putenv alone doesn't reach Python or child processes such as husk)."""
    ctx = context(path)
    env = env_for(ctx) if ctx else cleared_env()
    if ctx:
        env["JOB"] = env["SW_ROOT"]
    for key, value in env.items():
        hou.putenv(key, value)
        os.environ[key] = value
    return ctx


def set_frame_range(frames: tuple[int, int]) -> None:
    hou.playbar.setFrameRange(frames[0], frames[1])
    hou.playbar.setPlaybackRange(frames[0], frames[1])


def check_frame_range(ctx: Context) -> None:
    """If the entity's frame range differs from the scene's, ask before applying it."""
    frames = Project.find(ctx.root).entity_at(ctx).frames
    scene = tuple(int(f) for f in hou.playbar.frameRange())
    if frames is None or scene == frames or not hou.isUIAvailable():
        return
    choice = hou.ui.displayMessage(
        f"The scene's frame range is {scene[0]}-{scene[1]}, "
        f"but {ctx.entity} is {frames[0]}-{frames[1]}.",
        buttons=(f"Use {frames[0]}-{frames[1]}", "Keep"),
        default_choice=0,
        close_choice=1,
        title="Scheinwerk",
    )
    if choice == 0:
        set_frame_range(frames)


def _on_hip_event(event_type: hou.hipFileEventType) -> None:
    try:
        if event_type == hou.hipFileEventType.AfterClear:
            apply_env(None)
        elif event_type in (hou.hipFileEventType.AfterLoad, hou.hipFileEventType.AfterSave):
            before = os.environ.get("SW_ENTITY_DIR", "")
            ctx = apply_env()
            loaded = event_type == hou.hipFileEventType.AfterLoad
            if ctx and (loaded or os.environ.get("SW_ENTITY_DIR") != before):
                check_frame_range(ctx)  # on load, or a save-as into another entity
    except Exception:
        log.exception("Scheinwerk scene callback failed")  # never break loading or saving


_started = False


def startup() -> None:
    """Called from pythonrc.py when Houdini starts. Safe to call twice."""
    global _started
    if _started:
        return
    _started = True
    hou.hipFile.addEventCallback(_on_hip_event)
    apply_env()


# --- menu and shelf actions --------------------------------------------------------


def save_next_version() -> Path:
    """Save the scene as the task's next workfile version (spec §13.2.3), then run the
    post_save hook. Keeps the scene's extension (.hip, .hipnc, .hiplc)."""
    task = _task()
    suffix = current_file().suffix.lstrip(".")
    path = task.next_workfile(suffix if suffix in EXTENSIONS else "hip")
    # "/" on every OS: Houdini pastes the path unescaped into event scripts' kwargs
    hou.hipFile.save(path.as_posix())
    run_hook("post_save", path=path, context=Context.from_path(path))
    return path


def context_path() -> str:
    """The open scene's path relative to the project root, e.g. for notes or chat."""
    project, _ = _project_and_context()
    return project.rel(current_file())


def _ui(action, done: str) -> None:
    try:
        result = action()
    except ScheinwerkError as exc:
        hou.ui.displayMessage(str(exc), severity=hou.severityType.Error, title="Scheinwerk")
        return
    hou.ui.setStatusMessage(done.format(result))


def ui_save_next_version() -> None:
    _ui(lambda: save_next_version().name, "Saved {}")


def ui_copy_context_path() -> None:
    def copy() -> str:
        from PySide6.QtWidgets import QApplication

        text = context_path()
        QApplication.clipboard().setText(text)
        return text

    _ui(copy, "Copied {}")


def browser_widget():
    """The Scheinwerk browser for the Python panel, opened at the open scene."""
    from scheinwerk.gui.browser import Browser

    return Browser(current_file())


def ui_open_browser() -> None:
    """Open the browser panel in a floating pane."""
    tab = hou.ui.curDesktop().createFloatingPaneTab(hou.paneTabType.PythonPanel)
    tab.setActiveInterface(hou.pypanel.interfaceByName("scheinwerk"))


# --- expression helpers (spec §13.2.4) ---------------------------------------------


def _frame(frames: bool) -> int | None:
    return int(round(hou.frame())) if frames else None


def _path(product: Product, ext: str, version: int | None, frames: bool) -> str:
    number = version or product.highest() or 1
    return product.file_path(number, ext, _frame(frames)).as_posix()


def cache(name: str) -> str:
    """The task's cache folder for `name` (free-form, not versioned)."""
    return (_task().cache_dir / name).as_posix()


def publish_path(
    product: str,
    ext: str,
    version: int | None = None,
    frames: bool = False,
    shot: str | None = None,
) -> str:
    """A product file in the highest version (or `version`); `frames` adds the frame."""
    entity = target_entity(shot)
    return _path(Product(entity.project, entity.path / "publish" / product), ext, version, frames)


def usd_path(layer: str, version: int | None = None, shot: str | None = None) -> str:
    entity = target_entity(shot)
    return _path(
        Product(entity.project, entity.path / "publish" / "_usd" / layer), "usd", version, False
    )


def media_path(
    name: str, ext: str, version: int | None = None, frames: bool = True, shot: str | None = None
) -> str:
    entity = target_entity(shot)
    return _path(Product(entity.project, entity.path / "media" / name), ext, version, frames)


def shots() -> list[tuple[str, tuple[int, int] | None]]:
    """Shots of the scene's sequence (sequence or shot scene) with their frame ranges."""
    project, ctx = _project_and_context()
    if ctx.sequence is None:
        return []
    return [(s.name, s.frames) for s in project.shots(ctx.sequence)]


def shot_menu() -> list[str]:
    """For a Shot menu parm: "" means the SW_SHOT context option, then every shot."""
    items = ["", f"(context option {SHOT_OPTION})"]
    try:
        found = shots()
    except ScheinwerkError:
        found = []  # unsaved scene: a menu must not raise
    for name, frames in found:
        items += [name, f"{name}  {frames[0]}-{frames[1]}" if frames else name]
    return items


def set_shot(shot: str) -> None:
    """Choose the target shot of a sequence scene (sets the SW_SHOT context option)."""
    hou.setContextOption(SHOT_OPTION, shot)


def layers_below(layer: str, shot: str | None = None) -> list[str]:
    """Pointer layers weaker than `layer` in usd_layer_order that exist, strongest first,
    as `$JOB/…` paths for a Sublayer LOP (spec §13.2.8: load what's below, publish yours)."""
    entity = target_entity(shot)
    order = entity.project.setting("usd_layer_order")
    below = order[order.index(layer) + 1 :] if layer in order else []
    usd = entity.path / "publish" / "_usd"
    return [
        "$JOB/" + entity.project.rel(usd / name / f"{name}.usd")
        for name in below
        if (usd / name / f"{name}.usd").is_file()
    ]


# --- the writing HDAs: sw_publish_sop, sw_publish_lop, sw_render ------------------------
# Their parameters are described in docs/usage.md ("Building the HDAs"). The kind is told
# apart by its name parm: product (SOP), layer (LOP) or render_name (render). The two
# publish HDAs have a `target` menu: publish (products, finalized) or cache (the scene's
# task cache, <task>/cache/<name>/v###/, never finalized: caches are free-form, spec §4).

TARGET_PUBLISH, TARGET_CACHE = 0, 1  # the publish HDAs' `target` menu


def is_cache(node: hou.Node) -> bool:
    """Whether a publish HDA writes into the task cache instead of publishing."""
    return bool(node.parm("target")) and node.evalParm("target") == TARGET_CACHE


RANGE_CURRENT, RANGE_SHOT, RANGE_CUSTOM = 0, 1, 2  # the HDAs' `range` menu


def _node_entity(node: hou.Node) -> Entity:
    """The entity a node writes for: caching, the scene's own (its task's cache); else
    the scene's, or in a sequence scene the chosen shot."""
    if is_cache(node):
        return _task().entity
    shot = node.evalParm("shot") if node.parm("shot") else ""
    return target_entity(shot or None)


def _hda(node: hou.Node) -> tuple[Product, str, bool]:
    """(product, extension, one file per frame) for an HDA node. Refuses a missing or
    invalid name, so nothing is ever reserved, written or finalized without one."""
    entity = _node_entity(node)
    if node.parm("layer"):
        parm, kind, ext, frames = "layer", "layer", "usd", False
        name = node.evalParm("layer")
        folder = _task().cache_dir if is_cache(node) else entity.path / "publish" / "_usd"
    elif node.parm("render_name"):
        parm, kind, ext, frames = "render_name", "media", "exr", True
        name = node.evalParm("render_name") and f"render_{node.evalParm('render_name')}"
        folder = entity.path / "media"
    else:
        parm, kind, ext = "product", "product", node.evalParm("ext")
        name = node.evalParm("product")
        frames = node.evalParm("range") != RANGE_CURRENT
        folder = _task().cache_dir if is_cache(node) else entity.path / "publish"
    if not name.strip():
        raise ScheinwerkError(f"{node.path()}: set the {parm.replace('_', ' ')} first.")
    validate_name(kind, name)
    return Product(entity.project, folder / name), ext, frames


def hda_version(node: hou.Node) -> int:
    """The node's version parm (at least 1)."""
    return max(1, node.evalParm("version"))


def hda_range(node: hou.Node) -> tuple[int, int]:
    """Frames an HDA writes: the current frame, the shot's range (an entity without
    one: the scene's range) or the node's own frame_range."""
    mode = node.evalParm("range")
    if mode == RANGE_CUSTOM:
        return tuple(node.evalParmTuple("frame_range"))
    if mode == RANGE_SHOT:
        frames = _node_entity(node).frames
        return frames or tuple(int(f) for f in hou.playbar.frameRange())
    frame = int(round(hou.frame()))
    return frame, frame


def hda_output(node: hou.Node) -> str:
    """The file the node writes, for its output parm (evaluated per frame)."""
    product, ext, frames = _hda(node)
    return product.file_path(hda_version(node), ext, _frame(frames)).as_posix()


def hda_name_menu(node: hou.Node) -> list[str]:
    """For the name parm's menu: the entity's existing products, USD layers or renders
    (`render_*` media, shown without the prefix)."""
    try:
        entity = _node_entity(node)
    except ScheinwerkError:
        return []  # unsaved scene: a menu must not raise
    if is_cache(node):
        names = [f.name for f in entity.project.scan(_task().cache_dir)]
    elif node.parm("layer"):
        names = [p.name for p in entity.products(usd=True)]
    elif node.parm("render_name"):
        names = [m.name[7:] for m in entity.media() if m.name.startswith("render_")]
    else:
        names = [p.name for p in entity.products(usd=False)]
    return [item for name in names for item in (name, name)]


def hda_name_changed(node: hou.Node) -> None:
    """Name parm callback: switch to that product's highest version (1 if it's new)."""
    try:
        product, _, _ = _hda(node)
    except ScheinwerkError:
        return  # empty or half-typed name: the buttons refuse it
    node.parm("version").set(product.highest() or 1)


def _show(exc: ScheinwerkError) -> None:
    """A button's error as a message box; headless (tests, hython) it is raised."""
    if not hou.isUIAvailable():
        raise exc
    hou.ui.displayMessage(str(exc), severity=hou.severityType.Error, title="Scheinwerk")


def hda_new_version(node: hou.Node) -> None:
    """ "New version" button: switch to the number after the highest existing v### (1 if
    none). Creates nothing; Export makes the folder."""
    try:
        product, _, _ = _hda(node)
    except ScheinwerkError as exc:
        _show(exc)
        return
    node.parm("version").set((product.highest() or 0) + 1)


def hda_execute(node: hou.Node) -> None:
    """Export/Render button: check the node, create its version folder (the USD ROP doesn't
    make missing folders), then press the inner ROP's Render button."""
    try:
        product, ext, _ = _hda(node)
        rop = next((c for c in node.children() if c.parm("execute")), None)
        if rop is None:
            raise ScheinwerkError(f"{node.path()} has no ROP inside it.")
    except ScheinwerkError as exc:
        _show(exc)
        return
    product.file_path(hda_version(node), ext).parent.mkdir(parents=True, exist_ok=True)
    rop.parm("execute").pressButton()
    _refresh_info(node)


def publish_choose(node: hou.Node) -> None:
    """Choose… button of the publish HDAs: pick an existing product (or USD layer) of an
    entity this scene publishes to; sets the name (and in a sequence scene the shot) and
    switches to its highest version. Typing a new name still works without it."""
    from scheinwerk.gui.pick import pick

    try:
        project, ctx = _project_and_context()
    except ScheinwerkError as exc:
        _show(exc)
        return
    own = project.entity_at(ctx)
    allowed = project.shots(own.name) if own.type == "sequence" else [own]
    usd = node.parm("layer") is not None
    name_parm = "layer" if usd else "product"
    shot = node.evalParm("shot") if node.parm("shot") else ""
    choice = pick(
        current_file(),
        usd,
        entity=shot or ("" if own.type == "sequence" else own.name),
        product=node.evalParm(name_parm),
        parent=hou.qt.mainWindow() if hou.isUIAvailable() else None,
        allowed=allowed,
    )
    if choice is None:
        return
    if node.parm("shot") and own.type == "sequence":
        node.parm("shot").set(choice.entity.name)
    if choice.product is not None:  # else: only the shot was chosen, keep the typed name
        node.parm(name_parm).set(choice.product.name)
    hda_name_changed(node)
    _refresh_info(node)


def _files(version: Version) -> str:
    files = version.files()
    text = f"{len(files)} file{'' if len(files) == 1 else 's'}"
    groups = file_sequences(files)
    if len(files) > 1 and len(groups) == 1 and groups[0].frames:
        text += " {}-{}".format(*groups[0].frames)
    return text


def hda_info(node: hou.Node) -> str:
    """The Info box: the product's latest (and for USD current) version, and what the
    node's version will do.
    Never raises: a parm expression must show text, not an error."""
    try:
        product, ext, _ = _hda(node)
        number = hda_version(node)
    except ScheinwerkError as exc:
        return str(exc)
    if is_cache(node):
        label = "Cache"
    else:
        label = "Layer" if product.usd else "Media" if product.is_media else "Product"
    action = node.parm("execute").parmTemplate().label() if node.parm("execute") else "Export"
    lines = [f"{label:<9}{product.name}  ({len(product.versions())} versions on disk)"]
    latest = product.latest()
    if latest is None:
        lines.append("Latest   none yet")
    else:
        info = latest.info or {}
        when = info.get("created", "")[:16].replace("T", " ")
        details = [format_version(latest.number), _files(latest), when, info.get("user", "")]
        lines.append("Latest   " + " | ".join(d for d in details if d))
        note = [f'"{info["comment"]}"'] if info.get("comment") else []
        note += [f"from {PurePosixPath(info['source']).name}"] if info.get("source") else []
        if note:
            lines.append("         " + "  ".join(note))
    if product.usd:
        current = product.current()
        shown = format_version(current.number) if current else "none"
        lines.append(f"Current  {shown}  (the version the layer's pointer uses)")
    folder = product.file_path(number, ext).parent
    version = Version(product.project, folder)
    if not folder.is_dir():
        state = f"is new: {action} creates it"
    elif version.empty:
        state = f"exists, empty: {action} writes into it"
    else:
        state = f"exists ({_files(version)}): {action} overwrites it"
    lines.append(f"Version  {format_version(number)} {state}")
    return "\n".join(lines)


def _refresh_info(node: hou.Node) -> None:
    """Re-evaluate the Info box after files changed on disk (Houdini can't see that)."""
    parm = node.parm("info")
    with contextlib.suppress(AttributeError, hou.OperationFailed):  # no Info box / expression
        parm.setExpression(parm.expression(), parm.expressionLanguage())


def hda_post_render(node: hou.Node) -> None:
    """Post-render script of the inner ROP: finalize the version (version.json, and for a
    USD layer the pointer and root layer). A cache is never finalized."""
    if is_cache(node):
        return
    product, ext, _ = _hda(node)
    version = hda_version(node)
    main = product.file_path(version, ext).name if ext == "usd" else None
    finalize(
        product.path / format_version(version),
        source=current_file(),
        comment=node.evalParm("comment") if node.parm("comment") else "",
        main_file=main,
        dcc="houdini",
    )


# --- the importing HDAs: sw_import_sop, sw_import_lop ---------------------------------
# Parms: entity (empty = the scene's), product or layer, version (latest/current or a
# v###), file (SOP) or mode + primpath (LOP). The inner File SOP / Sublayer / Reference
# LOP read their path from the HDA's `path` parm (Python expression import_path).

LATEST, CURRENT = "latest", "current"  # version menu: newest with files / the USD pointer
MODE_AUTO, MODE_REFERENCE, MODE_SUBLAYER = 0, 1, 2  # sw_import_lop's `mode` menu


def _import_entity(node: hou.Node) -> Entity:
    project, ctx = _project_and_context()
    name = node.evalParm("entity").strip()
    return project.entity(name) if name else project.entity_at(ctx)


def import_choose(node: hou.Node) -> None:
    """Choose… button: pick entity, product (or USD layer) and version in the browser
    (gui/pick.py) and write them into the node."""
    from scheinwerk.gui.pick import pick

    try:
        project, ctx = _project_and_context()
    except ScheinwerkError as exc:
        _show(exc)
        return
    usd = node.parm("layer") is not None
    name_parm = "layer" if usd else "product"
    choice = pick(
        current_file(),
        usd,
        entity=node.evalParm("entity"),
        product=node.evalParm(name_parm),
        version=node.evalParm("version"),
        parent=hou.qt.mainWindow() if hou.isUIAvailable() else None,
    )
    if choice is None:
        return
    entity = choice.entity
    if entity == project.entity_at(ctx):
        key = ""  # the scene's own: stays right if the scene is copied to another entity
    else:
        key = f"seq:{entity.name}" if entity.type == "sequence" else entity.name
    node.parm("entity").set(key)
    node.parm(name_parm).set(choice.product.name if choice.product else "")
    latest = CURRENT if usd else LATEST
    node.parm("version").set(format_version(choice.version) if choice.version else latest)
    if node.parm("file"):
        node.parm("file").set("")
    _refresh_info(node)


def _import_product(node: hou.Node) -> Product:
    entity = _import_entity(node)
    name = node.evalParm("product").strip()
    if not name:
        raise ScheinwerkError(f"{node.path()}: choose a product first.")
    product = Product(entity.project, entity.path / "publish" / name)
    if not product.path.is_dir():
        raise NotFound(f"{entity.name} has no product {name!r}.")
    return product


def _import_layer(node: hou.Node) -> tuple[Entity, Product | None]:
    """(entity, layer); no layer = the entity's entry/root layer with every layer in it."""
    entity = _import_entity(node)
    name = node.evalParm("layer").strip()
    if not name:
        return entity, None
    layer = Product(entity.project, entity.path / "publish" / "_usd" / name)
    if not layer.path.is_dir():
        raise NotFound(f"{entity.name} has no USD layer {name!r}.")
    return entity, layer


def _chosen_version(node: hou.Node, product: Product) -> Version:
    """The node's version choice: latest = the newest version with files, or a v###."""
    choice = node.evalParm("version").strip() or LATEST
    if choice in (LATEST, CURRENT):
        version = product.latest()
        if version is None:
            raise NotFound(f"{product.name} has no version with files yet.")
        return version
    number = parse_version(choice)
    version = Version(product.project, product.path / format_version(number or 0))
    if number is None or not version.path.is_dir():
        raise NotFound(f"{product.name} has no version {choice!r}.")
    return version


def import_product_menu(node: hou.Node) -> list[str]:
    """sw_import_sop: the chosen entity's products; sw_import_lop: its USD layers, with
    the entry/root layer first."""
    try:
        entity = _import_entity(node)
    except ScheinwerkError:
        return []
    if node.parm("layer"):
        items = ["", f"(all layers: {entity.name}.usd)"]
        return items + [i for p in entity.products(usd=True) for i in (p.name, p.name)]
    return [i for p in entity.products(usd=False) for i in (p.name, p.name)]


def import_version_menu(node: hou.Node) -> list[str]:
    """latest (or for USD: current = the pointer's version), then every version."""
    try:
        if node.parm("layer"):
            _, product = _import_layer(node)
            first = [CURRENT, "current (the pointer)"]
        else:
            product = _import_product(node)
            first = [LATEST, "latest"]
    except ScheinwerkError:
        return [LATEST, "latest"]
    if product is None:
        return [CURRENT, "current (the pointer)"]
    items = list(first)
    for v in product.versions():
        comment = (v.info or {}).get("comment", "")
        label = format_version(v.number) + (
            " (empty)" if v.empty else f"  {comment}" if comment else ""
        )
        items += [format_version(v.number), label]
    return items


def import_file_menu(node: hou.Node) -> list[str]:
    """sw_import_sop: the files of the chosen version (a numbered sequence is one entry)."""
    try:
        version = _chosen_version(node, _import_product(node))
    except ScheinwerkError:
        return []
    return [i for g in file_sequences(version.files()) for i in (g.label, g.label)]


def import_path(node: hou.Node) -> str:
    """sw_import_sop: the file to load at the current frame (for the inner File SOP)."""
    version = _chosen_version(node, _import_product(node))
    groups = file_sequences(version.files())
    if not groups:
        raise NotFound(f"{version.path} is empty.")
    choice = node.evalParm("file").strip()
    group = next((g for g in groups if g.label == choice), groups[0])
    return group.path_at(int(round(hou.frame()))).as_posix()


def import_usd_path(node: hou.Node) -> str:
    """sw_import_lop: the layer file: the entry/root layer, a layer's pointer (current) or
    the main file of one version."""
    entity, layer = _import_layer(node)
    if layer is None:
        path = entity.path / "publish" / "_usd" / f"{entity.name}.usd"
    elif (node.evalParm("version").strip() or CURRENT) == CURRENT:
        path = layer.pointer
    else:
        version = _chosen_version(node, layer)
        path = layer.file_path(version.number, "usd")
        if not path.is_file():  # not the recommended name: the version's only USD file
            usd = [p for p in version.files() if p.suffix in (".usd", ".usda", ".usdc")]
            path = usd[0] if len(usd) == 1 else path
    if not path.is_file():
        raise NotFound(f"{path} doesn't exist yet: publish the layer first.")
    return path.as_posix()


def import_mode(node: hou.Node) -> int:
    """For the inner Switch LOP: 0 = sublayer, 1 = reference. Auto references an asset
    (its entry layer has a defaultPrim) and sublayers a shot or sequence layer."""
    mode = node.evalParm("mode")
    if mode == MODE_AUTO:
        try:
            mode = MODE_REFERENCE if _import_entity(node).type == "asset" else MODE_SUBLAYER
        except ScheinwerkError:
            mode = MODE_SUBLAYER
    return 1 if mode == MODE_REFERENCE else 0


def import_prim(node: hou.Node) -> str:
    """Default prim path for a reference: /<entity name>."""
    try:
        return f"/{_import_entity(node).name}"
    except ScheinwerkError:
        return "/import"


def import_info(node: hou.Node) -> str:
    """The Info box of an import HDA. Never raises: a parm expression must show text."""
    try:
        if node.parm("layer"):
            path = Path(import_usd_path(node))
            entity, layer = _import_layer(node)
            mode = "reference" if import_mode(node) else "sublayer"
            lines = [f"Entity   {entity.name} ({entity.type})", f"Mode     {mode}"]
            if layer is None:
                lines.append(f"Layer    all layers ({path.name})")
            else:
                current = layer.current()
                shown = format_version(current.number) if current else "-"
                lines.append(f"Layer    {layer.name}  current {shown}")
            lines.append(f"File     {path.name}")
            return "\n".join(lines)
        product = _import_product(node)
        version = _chosen_version(node, product)
        info = version.info or {}
        lines = [
            f"Entity   {_import_entity(node).name}",
            f"Product  {product.name}  {format_version(version.number)}"
            f" of {len(product.versions())}",
            f"File     {Path(import_path(node)).name}",
        ]
        if info.get("comment") or info.get("created"):
            when = info.get("created", "")[:16].replace("T", " ")
            lines.append(
                "         "
                + "  ".join(x for x in (when, info.get("user", ""), info.get("comment", "")) if x)
            )
        return "\n".join(lines)
    except ScheinwerkError as exc:
        return str(exc)


def import_reload(node: hou.Node) -> None:
    """Reload button: re-read the disk (a new latest version, re-exported files)."""
    for child in node.children():
        if child.parm("reload"):
            child.parm("reload").pressButton()
    _refresh_info(node)


# --- adapter (spec §13.1) --------------------------------------------------------------


class HoudiniAdapter:
    name = "houdini"
    extensions = EXTENSIONS

    def current_file(self) -> Path | None:
        return current_file()

    def open(self, path: Path) -> None:
        hou.hipFile.load(path.as_posix())

    def save_as(self, path: Path) -> None:
        hou.hipFile.save(path.as_posix())

    def main_window(self):
        return hou.qt.mainWindow()


ADAPTER = HoudiniAdapter()
