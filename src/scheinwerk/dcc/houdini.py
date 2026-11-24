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
from scheinwerk.core.usd_pointer import (
    ASSET_LAYER_ORDER,
    asset_prim_path,
    layers_below,
    write_structure,
)
from scheinwerk.core.versions import Product, Version, file_sequences

log = logging.getLogger("scheinwerk.houdini")

EXTENSIONS = ("hip", "hipnc", "hiplc")
SHOT_OPTION = "SW_SHOT"  # context option naming the target shot in a sequence scene
SEQ_TARGET = "_seq"  # as a shot: the sequence itself (spec §13.2.7)


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
    given here, else the one in the SW_SHOT context option; `_seq` is the sequence itself
    (spec §13.2.7)."""
    project, ctx = _project_and_context()
    entity = project.entity_at(ctx)
    if entity.type != "sequence":
        return entity
    shot = shot or _shot_option()
    if shot == SEQ_TARGET:
        return entity
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


def set_fps(fps: float) -> None:
    """Change the scene's fps, keeping keys and the frame range on their frames."""
    hou.setFps(fps, modify_frame_count=False, preserve_keyframes=True, preserve_frame_start=True)


def fps_matches(fps: float) -> bool:
    return abs(hou.fps() - fps) < 1e-3


def _fps_text(fps: float) -> str:
    return f"{fps:g}"


def check_frame_range(ctx: Context) -> None:
    """If the entity's frame range or fps differs from the scene's, ask before applying
    them. The fps matters: the USD ROP writes the scene's fps into every layer (spec
    §13.2.2)."""
    entity = Project.find(ctx.root).entity_at(ctx)
    frames, fps = entity.frames, entity.fps
    scene = tuple(int(f) for f in hou.playbar.frameRange())
    wrong_frames = frames is not None and scene != frames
    if not (wrong_frames or not fps_matches(fps)) or not hou.isUIAvailable():
        return
    have, want = [], []
    if not fps_matches(fps):
        have.append(f"{_fps_text(hou.fps())} fps")
        want.append(f"{_fps_text(fps)} fps")
    if wrong_frames:
        have.append(f"{scene[0]}-{scene[1]}")
        want.append(f"{frames[0]}-{frames[1]}")
    choice = hou.ui.displayMessage(
        f"The scene is {', '.join(have)}, but {ctx.entity} is {', '.join(want)}.",
        buttons=(f"Use {', '.join(want)}", "Keep"),
        default_choice=0,
        close_choice=1,
        title="Scheinwerk",
    )
    if choice == 0:
        if not fps_matches(fps):
            set_fps(fps)
        if wrong_frames:
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


# Houdini's default paths of Camera and Light LOPs -> theirs in the shot structure (§9.2).
WORLD_PATHS = {"/cameras/$OS": "/world/cameras/$OS", "/lights/$OS": "/world/lights/$OS"}


def on_created(node: hou.Node) -> None:
    """scripts/OnCreated.py: move a new Camera or Light LOP under /world. Only the exact
    defaults change, so a path the user set (or a pasted node's) stays. Never raises."""
    try:
        parm = node.parm("primpath") if isinstance(node, hou.LopNode) else None
        if parm is not None and not parm.keyframes():
            new = WORLD_PATHS.get(parm.unexpandedString())
            if new:
                parm.set(new)
    except hou.Error:
        log.exception("Scheinwerk: OnCreated failed for %s", node.path())


def save_next_version() -> Path:
    """Save the scene as the task's next workfile version (spec §13.2.3), then run the
    post_save hook. Keeps the scene's extension (.hip, .hipnc, .hiplc)."""
    task = _task()
    suffix = current_file().suffix.lstrip(".")
    path = task.next_workfile(suffix if suffix in EXTENSIONS else "hip")
    ADAPTER.save_as(path)
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

    return Browser(current_file(), adapter=ADAPTER)


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
    """For a Shot menu parm: "" means the SW_SHOT context option, then in a sequence scene
    `_seq` (the sequence itself) and every shot."""
    items = ["", f"(context option {SHOT_OPTION})"]
    ctx = context()
    if ctx is not None and ctx.entity_type == "sequence":
        items += [SEQ_TARGET, "(the sequence itself)"]
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


# --- the writing HDAs: sw_publish_sop, sw_publish_lop, sw_render ------------------------
# Their parameters are described in docs/usage.md ("Building the HDAs"). The kind is told
# apart by its name parm: product (SOP), layer (LOP) or render_name (render). The two
# publish HDAs have a `target` menu: publish (products, finalized) or cache (the scene's
# task cache, <task>/cache/<name>/v###/, never finalized: caches are free-form, spec §4).

TARGET_PUBLISH, TARGET_CACHE = 0, 1  # the publish HDAs' `target` menu
ASSET_LAYERS = ("geo", "mtl")  # layers with prim conventions (spec §9.3)


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


def hda_load_files(node: hou.Node) -> list[Path]:
    """sw_publish_lop's Load from Disk, weakest first (as the Sublayer LOP lists them): the
    published layers below this one (mtl: the geo; a shot layer: the weaker layers and the
    structure), then the written file. So the stage doesn't lose what came before, and
    nothing upstream cooks (spec §13.2)."""
    entity = _node_entity(node)
    if entity.type != "asset":
        write_structure(entity.project.root / "shared" / "usd" / "structure.usd")
    below = layers_below(entity, node.evalParm("layer"))
    return [*reversed(below), Path(hda_output(node))]


def hda_load_file(node: hou.Node, index: int) -> str:
    """The load Sublayer LOP's file `index` (1-based), "" for an unused slot."""
    files = hda_load_files(node)
    return files[index - 1].as_posix() if index <= len(files) else ""


def hda_name_menu(node: hou.Node) -> list[str]:
    """For the name parm's menu: the entity's existing products, USD layers or renders
    (`render_*` media, shown without the prefix). USD layers start with the entity's
    standard layers in working order, `(new)` while unpublished: geo, mtl for an asset,
    usd_layer_order (weakest first) for a shot or sequence."""
    try:
        entity = _node_entity(node)
    except ScheinwerkError:
        return []  # unsaved scene: a menu must not raise
    if is_cache(node):
        names = [f.name for f in entity.project.scan(_task().cache_dir)]
    elif node.parm("layer"):
        names = [p.name for p in entity.products(usd=True)]
        order = (
            ASSET_LAYER_ORDER
            if entity.type == "asset"
            else entity.project.setting("usd_layer_order")
        )
        standard = list(reversed(order))
        labels = [f"{n} (new)" if n not in names else n for n in standard]
        rest = [n for n in names if n not in standard]
        return [i for pair in zip(standard + rest, labels + rest, strict=True) for i in pair]
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


def _fps_problem(node: hou.Node) -> str:
    """Why a USD publish would carry the wrong fps, or "" (the USD ROP writes the scene's
    fps into the layer, spec §9.2 item 5)."""
    if not node.parm("layer") or is_cache(node):
        return ""
    entity = _node_entity(node)
    if fps_matches(entity.fps):
        return ""
    return (
        f"The scene runs at {_fps_text(hou.fps())} fps, {entity.name} at "
        f"{_fps_text(entity.fps)}: set the scene to {_fps_text(entity.fps)} fps before "
        "publishing (Scheinwerk offers it when the scene is opened)."
    )


def _export(node: hou.Node) -> None:
    """Check the node, create its version folder (the USD ROP doesn't make missing
    folders), then press the inner ROP's Render button. Raises ScheinwerkError."""
    product, ext, _ = _hda(node)
    problem = _fps_problem(node)
    if problem:
        raise ScheinwerkError(problem)
    # by name first: that loads a locked HDA's contents, children() alone may not
    rop = node.node("export") or node.node("render")
    rop = rop or next((c for c in node.children() if c.parm("execute")), None)
    if rop is None:
        raise ScheinwerkError(f"{node.path()} has no ROP inside it.")
    product.file_path(hda_version(node), ext).parent.mkdir(parents=True, exist_ok=True)
    rop.parm("execute").pressButton()
    _refresh_info(node)


def hda_execute(node: hou.Node) -> None:
    """Export/Render button."""
    try:
        _export(node)
    except ScheinwerkError as exc:
        _show(exc)


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
    with contextlib.suppress(ScheinwerkError):
        problem = _fps_problem(node)
        if problem:
            lines.append(f"Warning  {problem}")
        outside = _prims_outside_asset(node)
        if outside:
            lines.append(f"Warning  prims outside /{_node_entity(node).name}: {', '.join(outside)}")
    return "\n".join(lines)


def _prims_outside_asset(node: hou.Node) -> list[str]:
    """Root prims of the incoming stage other than the asset's, for the asset layers geo
    and mtl (spec §9.3: everything an asset layer authors lives under /<asset>)."""
    if not node.parm("layer") or is_cache(node) or node.evalParm("layer") not in ASSET_LAYERS:
        return []
    entity = _node_entity(node)
    inputs = [i for i in node.inputs() if i is not None]
    if entity.type != "asset" or not inputs:
        return []
    stage = inputs[0].stage()
    if stage is None:
        return []
    names = [p.GetName() for p in stage.GetPseudoRoot().GetAllChildren()]
    return [f"/{n}" for n in names if n not in (entity.name, "HoudiniLayerInfo")]


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
        usd_files=used_usd_files(node) if node.parm("render_name") else None,
    )


def used_usd_files(node: hou.Node) -> list[Path]:
    """The published USD files the render's stage uses (payloads loaded, as Houdini loads
    them): every used layer inside a v### folder under publish/ (spec §8.3)."""
    source = node.node("source")
    stage = source.stage() if source is not None else None
    if stage is None:
        return []
    found = []
    for layer in stage.GetUsedLayers():
        if not layer.realPath:
            continue  # anonymous layers: the scene's own edits
        ctx = context(Path(layer.realPath))
        if ctx is not None and ctx.area == "publish" and ctx.version is not None:
            found.append(Path(layer.realPath))
    return found


# --- Publish All USD (spec §13.2.3) -------------------------------------------------


def _usd_publish_nodes() -> list[hou.Node]:
    """Every sw_publish_lop writing to Publish and not bypassed, upstream first."""
    kind = hou.nodeType(hou.lopNodeTypeCategory(), "sw_publish_lop")
    if kind is None:
        return []
    nodes = [n for n in kind.instances() if not n.isBypassed() and not is_cache(n)]
    paths = {n.path() for n in nodes}

    def upstream(node: hou.Node) -> int:  # an ancestor always has fewer of them
        return sum(1 for a in node.inputAncestors() if a.path() in paths)

    return sorted(nodes, key=lambda n: (upstream(n), n.path()))


def publish_all_plan() -> list[tuple[hou.Node, int]]:
    """(node, version) for Publish All USD. A version that already has files becomes a new
    one, so nothing published is overwritten. Raises for a node without a valid name."""
    plan: list[tuple[hou.Node, int]] = []
    taken: dict[Path, int] = {}  # two nodes publishing the same layer
    for node in _usd_publish_nodes():
        product, ext, _ = _hda(node)
        number = hda_version(node)
        version = Version(product.project, product.file_path(number, ext).parent)
        if version.path.is_dir() and not version.empty:
            number = (product.highest() or 0) + 1
        if product.path in taken:
            number = max(number, taken[product.path] + 1)
        taken[product.path] = number
        plan.append((node, number))
    return plan


def publish_all_usd(plan: list[tuple[hou.Node, int]] | None = None) -> list[hou.Node]:
    """Export every USD publish node of the scene in chain order; stops at the first error."""
    plan = publish_all_plan() if plan is None else plan
    for node, number in plan:
        node.parm("version").set(number)
    for node, _ in plan:
        _export(node)
    return [node for node, _ in plan]


def ui_publish_all_usd() -> None:
    try:
        plan = publish_all_plan()
    except ScheinwerkError as exc:
        _show(exc)
        return
    if not plan:
        hou.ui.displayMessage("This scene has no Publish USD nodes.", title="Scheinwerk")
        return
    lines = [f"{n.path()}   {n.evalParm('layer')} {format_version(v)}" for n, v in plan]
    choice = hou.ui.displayMessage(
        "Publish these USD layers, in this order?",
        buttons=("Publish", "Cancel"),
        default_choice=0,
        close_choice=1,
        details="\n".join(lines),
        details_expanded=True,
        title="Scheinwerk",
    )
    if choice == 0:
        _ui(lambda: len(publish_all_usd(plan)), "Published {} USD layers")


# --- Asset Start and Shot Start (spec §13.2.6) ---------------------------------------


def start_asset(node: hou.Node) -> str:
    """sw_asset_start: the scene's asset, whose skeleton it builds."""
    project, ctx = _project_and_context()
    entity = project.entity_at(ctx)
    if entity.type != "asset":
        raise ScheinwerkError("Asset Start only works in an asset's scene.")
    return entity.name


def shot_start_layer_menu(node: hou.Node) -> list[str]:
    """sw_shot_start's `load`: the usd_layer_order layers, then the sequence root layer."""
    try:
        project, _ = _project_and_context()
        order = project.setting("usd_layer_order")
    except ScheinwerkError:
        order = []
    return [i for n in order for i in (n, n)] + ["sequence", "sequence (its root layer)"]


def shot_start_files(node: hou.Node) -> list[Path]:
    """What sw_shot_start loads, weakest first (as the Sublayer LOP lists them): the
    sequence root layer (when ticked and published) or else the structure layer, then the
    ticked layers that have a pointer, as in the shot root layer (spec §9.2)."""
    entity = target_entity(node.evalParm("shot") or None)
    if entity.type == "asset":
        raise ScheinwerkError("Shot Start only works in a shot's or sequence's scene.")
    ticked = node.evalParm("load").split()
    order = entity.project.setting("usd_layer_order")
    usd = entity.path / "publish" / "_usd"
    layers = [usd / n / f"{n}.usd" for n in order if n in ticked]
    structure = entity.project.root / "shared" / "usd" / "structure.usd"
    write_structure(structure)  # older projects (spec §9.2)
    seq_root = entity.path.parent / "_seq" / "publish" / "_usd" / f"{entity.sequence}.usd"
    use_seq = entity.type == "shot" and "sequence" in ticked and seq_root.is_file()
    return [seq_root if use_seq else structure, *reversed([p for p in layers if p.is_file()])]


def shot_start_file(node: hou.Node, index: int) -> str:
    """The Sublayer LOP's file `index` (1-based), "" for an unused slot."""
    files = shot_start_files(node)
    return files[index - 1].as_posix() if index <= len(files) else ""


def shot_start_info(node: hou.Node) -> str:
    """Info box: the loaded layers, strongest first. Never raises."""
    try:
        files = shot_start_files(node)
        project = target_entity(node.evalParm("shot") or None).project
    except ScheinwerkError as exc:
        return str(exc)
    return "\n".join(["Loaded (strongest first):", *(project.rel(f) for f in reversed(files))])


# --- sw_render's source (spec §13.2.6) ------------------------------------------------


def render_root(node: hou.Node) -> str:
    """Published shot: the target's root layer (<shot>.usd, or <seq>.usd for _seq)."""
    entity = _node_entity(node)
    if entity.type == "asset":
        raise ScheinwerkError("Published shot renders a shot or sequence, not an asset.")
    path = entity.path / "publish" / "_usd" / f"{entity.name}.usd"
    if not path.is_file():
        raise NotFound(f"{entity.name} has no published USD layers yet.")
    return path.as_posix()


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
    """Default prim path for a reference: /<entity> in an asset scene; in a shot or
    sequence scene an asset's group in the structure layer, /world/chars/hero (§9.2)."""
    try:
        _, ctx = _project_and_context()
        entity = _import_entity(node)
    except ScheinwerkError:
        return "/import"
    if ctx.entity_type == "asset" or entity.type != "asset":
        return f"/{entity.name}"
    return asset_prim_path(entity)


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
        """Load into this session. With a UI Houdini asks to save unsaved changes first,
        like File > Open; load warnings (e.g. missing assets) don't stop the load."""
        try:
            hou.hipFile.load(path.as_posix(), ignore_load_warnings=True)
        except hou.Error as exc:
            raise ScheinwerkError(f"Couldn't open {path.name}: {exc.instanceMessage()}") from exc

    def save_as(self, path: Path) -> None:
        """Save, then run the post_save hook."""
        try:
            # "/" on every OS: Houdini pastes the path unescaped into event scripts' kwargs
            hou.hipFile.save(path.as_posix())
        except hou.Error as exc:
            raise ScheinwerkError(f"Couldn't save {path.name}: {exc.instanceMessage()}") from exc
        run_hook("post_save", path=path, context=Context.from_path(path))

    def main_window(self):
        return hou.qt.mainWindow()


ADAPTER = HoudiniAdapter()
