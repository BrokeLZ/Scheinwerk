"""The `sw` command (spec §11).

Thin on purpose: parse arguments, call one core function, print the result.
Core errors become `sw: error: …` on stderr and exit code 1; usage errors exit 2.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from scheinwerk import __version__
from scheinwerk.core.context import Context
from scheinwerk.core.doctor import check
from scheinwerk.core.entities import Department, Entity, Task
from scheinwerk.core.env import env_for
from scheinwerk.core.errors import InvalidName, NotFound, NotInProject, ScheinwerkError
from scheinwerk.core.project import Project
from scheinwerk.core.publish import (
    finalize,
    ingest,
    next_media,
    next_publish,
    next_usd,
    set_current,
)
from scheinwerk.core.templates import parse_frames, validate_name
from scheinwerk.core.versions import Product

# --- helpers ----------------------------------------------------------------


def _project() -> Project:
    project = Project.find(Path.cwd())
    if project is None:
        raise NotInProject(
            f"Not inside a Scheinwerk project (no scheinwerk.json in {Path.cwd()} or above). "
            "Run `sw init` to make one."
        )
    return project


def _project_of(path: Path) -> Project:
    project = Project.find(path)
    if project is None:
        raise NotInProject(f"{path} is not inside a Scheinwerk project.")
    return project


def _fmt(args: argparse.Namespace, project: Project, path: Path) -> str:
    return project.rel(path) if getattr(args, "relative", False) else str(path)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def _emit(args: argparse.Namespace, project: Project, value: Path | list[Path]) -> None:
    """Print one path or several, honouring --relative and --json."""
    if isinstance(value, list):
        paths = [_fmt(args, project, p) for p in value]
        if args.json:
            _print_json({"paths": paths})
        else:
            for p in paths:
                print(p)
    elif args.json:
        _print_json({"path": _fmt(args, project, value)})
    else:
        print(_fmt(args, project, value))


def _task(entity: Entity, spec: str) -> Task:
    """`dept/task`, or just `dept` when the department has exactly one task."""
    dept_name, _, task_name = spec.partition("/")
    dept = entity.department(dept_name)
    if not dept.path.is_dir():
        raise NotFound(f"{entity.name} has no department {dept_name!r}.")
    if not task_name:
        tasks = dept.tasks()
        if len(tasks) != 1:
            names = ", ".join(t.name for t in tasks) or "none"
            raise ScheinwerkError(
                f"{dept_name} has several tasks ({names}): use {dept_name}/<task>."
                if tasks
                else f"{dept_name} has no tasks yet."
            )
        return tasks[0]
    task = dept.task(task_name)
    if not task.path.is_dir():
        raise NotFound(f"{entity.name}/{dept_name} has no task {task_name!r}.")
    return task


def _frame_range(text: str) -> tuple[int, int]:
    try:
        return parse_frames(text)
    except InvalidName as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _frames_text(frames: tuple[int, int] | None) -> str:
    return f"{frames[0]}-{frames[1]}" if frames else ""


def _tags(valid: bool = True, custom: bool = False) -> str:
    tags = (["custom"] if custom else []) + ([] if valid else ["invalid name"])
    return f"  [{', '.join(tags)}]" if tags else ""


def _join(*parts: str) -> str:
    return "  ".join(p for p in parts if p)


# --- init / new -------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> None:
    folder = Path.cwd()
    name = args.name or folder.name
    if not args.name:
        try:
            validate_name("project", name)
        except InvalidName:
            raise InvalidName(
                f"{name!r} can't be a project name. Pass one: sw init <name>"
            ) from None
    project = Project.create(folder, name)
    _emit(args, project, project.root)


def cmd_new(args: argparse.Namespace) -> None:
    project = _project()
    kind = args.kind
    if kind == "asset":
        category, _, name = args.name.rpartition("/")
        path = project.create_asset(name, category=category or None).path
    elif kind == "category":
        path = project.create_category(args.name)
    elif kind == "seq":
        project.create_sequence(args.name)
        path = project.root / "shots" / args.name
    elif kind == "shot":
        path = project.create_shot(args.name, frames=args.frames).path
    elif kind == "dept":
        entity = project.entity(args.entity)
        tasks = args.tasks or project.department_template(entity.type).get(args.dept) or ["main"]
        path = entity.create_department(args.dept, tasks=tuple(tasks)).path
    elif kind == "task":
        entity = project.entity(args.entity)
        dept = entity.department(args.dept)
        if not dept.path.is_dir():
            raise NotFound(f"{entity.name} has no department {args.dept!r}.")
        path = dept.create_task(args.task).path
    else:  # product
        path = project.entity(args.entity).create_product(args.name).path
    _emit(args, project, path)


# --- ls ---------------------------------------------------------------------


def _entity_json(args: argparse.Namespace, project: Project, e: Entity) -> dict:
    return {
        "type": e.type,
        "name": e.name,
        "category": e.category,
        "sequence": e.sequence,
        "valid": e.valid,
        "frames": list(e.frames) if e.frames else None,
        "path": _fmt(args, project, e.path),
    }


def _product_json(args: argparse.Namespace, project: Project, p: Product) -> dict:
    latest, current = p.latest(), p.current()
    return {
        "name": p.name,
        "usd": p.usd,
        "valid": p.valid,
        "path": _fmt(args, project, p.path),
        "versions": [v.number for v in p.versions()],
        "latest": latest.number if latest else None,
        "current": current.number if current else None,
    }


def _product_line(p: Product) -> str:
    versions = p.versions()
    if not versions:
        summary = "(no versions)"
    else:
        latest = p.latest()
        summary = f"latest {latest.path.name if latest else '-'}"
        if p.usd:
            current = p.current()
            summary += f", current {current.path.name if current else '-'}"
    return _join(f"  {p.name}", "[usd]" if p.usd else "", _tags(p.valid).strip(), summary)


def _ls_project(args: argparse.Namespace, project: Project) -> None:
    assets, categories, sequences = project.assets(), project.categories(), project.sequences()
    if args.json:
        _print_json(
            {
                "assets": [
                    {
                        "name": a.name,
                        "category": a.category,
                        "valid": a.valid,
                        "path": _fmt(args, project, a.path),
                    }
                    for a in assets
                ],
                "categories": categories,
                "sequences": [
                    {
                        "name": s.name,
                        "valid": s.valid,
                        "frames": list(s.frames) if s.frames else None,
                        "path": _fmt(args, project, s.path),
                        "shots": [
                            {
                                "name": shot.name,
                                "valid": shot.valid,
                                "frames": list(shot.frames) if shot.frames else None,
                                "path": _fmt(args, project, shot.path),
                            }
                            for shot in project.shots(s.name)
                        ],
                    }
                    for s in sequences
                ],
            }
        )
        return
    print("assets")
    used = {a.category for a in assets}
    empty = [c for c in categories if c not in used]
    for a in assets:
        name = f"{a.category}/{a.name}" if a.category else a.name
        print(f"  {name}{_tags(a.valid)}")
    for c in empty:
        print(f"  {c}/  (empty category)")
    if not assets and not empty:
        print("  (none)")
    print("shots")
    for s in sequences:
        print(_join(f"  {s.name}", _frames_text(s.frames)) + _tags(s.valid))
        for shot in project.shots(s.name):
            print(_join(f"    {shot.name}", _frames_text(shot.frames)) + _tags(shot.valid))
    if not sequences:
        print("  (none)")


def _ls_entity(args: argparse.Namespace, project: Project, e: Entity) -> None:
    departments, products, media = e.departments(), e.products(), e.media()
    if args.json:
        _print_json(
            {
                "entity": _entity_json(args, project, e),
                "departments": [
                    {
                        "name": d.name,
                        "custom": d.custom,
                        "valid": d.valid,
                        "path": _fmt(args, project, d.path),
                        "tasks": [_task_json(args, project, t) for t in d.tasks()],
                    }
                    for d in departments
                ],
                "products": [_product_json(args, project, p) for p in products],
                "media": [_product_json(args, project, p) for p in media],
            }
        )
        return
    where = {"asset": e.category, "shot": e.sequence}.get(e.type)
    print(_join(f"{e.name} ({e.type}{f' in {where}' if where else ''})", _frames_text(e.frames)))
    print("departments")
    for d in departments:
        print(f"  {d.name}{_tags(d.valid, d.custom)}")
        for t in d.tasks():
            print(f"    {t.name}{_tags(t.valid, t.custom)}")
    if not departments:
        print("  (none)")
    for title, items in (("products", products), ("media", media)):
        print(title)
        for p in items:
            print(_product_line(p))
        if not items:
            print("  (none)")


def _task_json(args: argparse.Namespace, project: Project, t: Task) -> dict:
    return {
        "name": t.name,
        "custom": t.custom,
        "valid": t.valid,
        "path": _fmt(args, project, t.path),
    }


def _ls_department(args: argparse.Namespace, project: Project, d: Department) -> None:
    if not d.path.is_dir():
        raise NotFound(f"{d.entity.name} has no department {d.name!r}.")
    tasks = d.tasks()
    if args.json:
        _print_json({"tasks": [_task_json(args, project, t) for t in tasks]})
        return
    for t in tasks:
        print(f"{t.name}{_tags(t.valid, t.custom)}")


def _ls_task(args: argparse.Namespace, project: Project, t: Task) -> None:
    workfiles, unmanaged = t.workfiles(), t.unmanaged()
    if args.json:
        _print_json(
            {
                "workfiles": [
                    {"path": _fmt(args, project, w.path), "version": w.version, "ext": w.ext}
                    for w in workfiles
                ],
                "unmanaged": [_fmt(args, project, p) for p in unmanaged],
            }
        )
        return
    for w in workfiles:
        print(w.path.name)
    if unmanaged:
        print("unmanaged")
        for p in unmanaged:
            print(f"  {p.name}")


def cmd_ls(args: argparse.Namespace) -> None:
    project = _project()
    if not args.entity:
        _ls_project(args, project)
        return
    entity = project.entity(args.entity)
    if not args.where:
        _ls_entity(args, project, entity)
    elif "/" in args.where:
        _ls_task(args, project, _task(entity, args.where))
    else:
        _ls_department(args, project, entity.department(args.where))


# --- next / latest / frames -------------------------------------------------


def cmd_next(args: argparse.Namespace) -> None:
    project = _project()
    task = _task(project.entity(args.entity), args.task)
    _emit(args, project, task.next_workfile(args.ext))


def _cmd_next_version(func: Callable[[Entity, str], Path]) -> Callable[[argparse.Namespace], None]:
    def run(args: argparse.Namespace) -> None:
        project = _project()
        _emit(args, project, func(project.entity(args.entity), args.name))

    return run


def cmd_latest(args: argparse.Namespace) -> None:
    project = _project()
    entity = project.entity(args.entity)
    if args.work:
        workfile = _task(entity, args.work).latest_workfile()
        if workfile is None:
            raise NotFound(f"No workfiles in {entity.name} {args.work} yet.")
        _emit(args, project, workfile.path)
        return
    if args.product:
        product = Product(project, entity.path / "publish" / args.product)
    elif args.usd:
        product = Product(project, entity.path / "publish" / "_usd" / args.usd)
    else:
        product = Product(project, entity.path / "media" / args.media)
    latest = product.latest()
    if latest is None:
        raise NotFound(f"{entity.name} has no version of {product.name} with files in it yet.")
    _emit(args, project, latest.path)


def cmd_frames(args: argparse.Namespace) -> None:
    entity = _project().entity(args.entity)
    if args.range:
        entity.set_frames(*args.range)
    frames = entity.frames
    if args.json:
        _print_json({"frames": list(frames) if frames else None})
    else:
        print(_frames_text(frames) or "(no frame range)")


# --- publish ----------------------------------------------------------------


def cmd_finalize(args: argparse.Namespace) -> None:
    vdir = Path(args.version_dir).absolute()
    finalize(vdir, source=args.source, comment=args.message, main_file=args.main)
    _emit(args, _project_of(vdir), vdir)


def cmd_set_current(args: argparse.Namespace) -> None:
    vdir = Path(args.version_dir).absolute()
    set_current(vdir, main_file=args.main)
    _emit(args, _project_of(vdir), vdir)


def cmd_ingest(args: argparse.Namespace) -> None:
    items = args.items
    by_name = args.product or args.media
    needed = 2 if by_name else 3
    if len(items) < needed:
        target = "--product/--media NAME" if by_name else "<dept>/<task>"
        args.parser.error(f"expected: sw ingest <files...> <entity> {target}")
    project = _project()
    if by_name:
        files, entity = items[:-1], project.entity(items[-1])
        area = entity.path / ("publish" if args.product else "media")
        target: Task | Product = Product(project, area / by_name)
    else:
        files, entity = items[:-2], project.entity(items[-2])
        target = _task(entity, items[-1])
    _emit(args, project, ingest(files, target))


# --- context / env / doctor -------------------------------------------------


def _context(path: str) -> Context:
    path = Path(path).absolute()
    ctx = Context.from_path(path)
    if ctx is None:
        raise NotInProject(f"{path} is not inside a Scheinwerk project.")
    return ctx


def cmd_context(args: argparse.Namespace) -> None:
    ctx = _context(args.path)
    fields = {**vars(ctx), "root": str(ctx.root)}
    if args.json:
        _print_json(fields)
        return
    for key, value in fields.items():
        shown = ("yes" if value else "no") if isinstance(value, bool) else value
        print(f"{key:<13}{'-' if shown is None else shown}")


def cmd_env(args: argparse.Namespace) -> None:
    env = env_for(_context(args.path))
    if args.json:
        _print_json(env)
        return
    for key, value in env.items():
        if args.shell in ("zsh", "bash"):
            print(f"export {key}='" + value.replace("'", "'\\''") + "'")
        elif args.shell == "pwsh":
            print(f"$env:{key} = '" + value.replace("'", "''") + "'")
        else:
            print(f"{key}={value}")


def cmd_doctor(args: argparse.Namespace) -> int:
    project = _project()
    issues = check(project)
    if args.json:
        _print_json(
            {
                "issues": [
                    {"kind": i.kind, "path": _fmt(args, project, i.path), "detail": i.detail}
                    for i in issues
                ]
            }
        )
    elif not issues:
        print("No issues found.")
    else:
        for i in issues:
            print(_join(i.kind, _fmt(args, project, i.path), i.detail))
        print(f"{len(issues)} issue{'s' if len(issues) != 1 else ''}")
    return 1 if issues else 0


def _has_pyside() -> bool:
    return importlib.util.find_spec("PySide6") is not None


def cmd_gui(args: argparse.Namespace) -> int:
    """Start the GUI as its own process: the CLI never imports GUI code (core <- cli <- gui)."""
    if not _has_pyside():
        raise ScheinwerkError(
            "The GUI needs PySide6. In the Scheinwerk repo run: uv sync --extra gui"
        )
    command = [sys.executable, "-m", "scheinwerk.gui"]
    if args.path:
        command.append(str(Path(args.path).absolute()))
    return subprocess.call(command)


# --- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sw",
        description="Scheinwerk: file-based VFX pipeline. Run inside a project folder, like git.",
    )
    parser.add_argument("--version", action="version", version=f"sw {__version__}")
    sub = parser.add_subparsers(title="commands", metavar="<command>")

    out = argparse.ArgumentParser(add_help=False)
    out.add_argument(
        "--relative", action="store_true", help="print paths relative to the project root"
    )
    out.add_argument("--json", action="store_true", help="print JSON")
    json_only = argparse.ArgumentParser(add_help=False)
    json_only.add_argument("--json", action="store_true", help="print JSON")

    def add(
        name: str, func: Callable, help: str, parents: tuple = (out,)
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help, description=help, parents=list(parents))
        p.set_defaults(func=func, parser=p)
        return p

    p = add("init", cmd_init, "make the current folder a project")
    p.add_argument("name", nargs="?", help="project name (default: the folder name)")

    p = sub.add_parser(
        "new", help="create an asset, category, sequence, shot, dept, task or product"
    )
    new = p.add_subparsers(title="what", metavar="<what>", required=True)

    def add_new(kind: str, help: str) -> argparse.ArgumentParser:
        q = new.add_parser(kind, help=help, description=help, parents=[out])
        q.set_defaults(func=cmd_new, parser=q, kind=kind)
        return q

    add_new("asset", "new asset").add_argument("name", help="hero, or category/hero")
    add_new("category", "new empty asset category").add_argument("name")
    add_new("seq", "new sequence").add_argument("name", help="sq010")
    q = add_new("shot", "new shot (creates its sequence if needed)")
    q.add_argument("name", help="sq010_0010")
    q.add_argument("--frames", type=_frame_range, help="frame range, e.g. 1001-1096")
    q = add_new("dept", "new department with its tasks")
    q.add_argument("entity")
    q.add_argument("dept")
    q.add_argument(
        "--tasks", nargs="+", help="task names (default: from the project template, else main)"
    )
    q = add_new("task", "new task in a department")
    q.add_argument("entity")
    q.add_argument("dept")
    q.add_argument("task")
    q = add_new("product", "new (empty) product")
    q.add_argument("entity")
    q.add_argument("name")

    p = add("ls", cmd_ls, "list entities, an entity, a department or a task")
    p.add_argument("entity", nargs="?")
    p.add_argument("where", nargs="?", metavar="dept[/task]")

    p = add("next", cmd_next, "print the next workfile path (creates nothing)")
    p.add_argument("entity")
    p.add_argument("task", metavar="dept[/task]")
    p.add_argument("--ext", required=True, help="file extension without the dot, e.g. hip")

    for name, func, what in (
        ("next-publish", next_publish, "product"),
        ("next-usd", next_usd, "USD layer"),
        ("next-media", next_media, "media"),
    ):
        p = add(name, _cmd_next_version(func), f"create and print the next {what} version folder")
        p.add_argument("entity")
        p.add_argument("name", metavar="layer" if what == "USD layer" else "name")

    p = add("latest", cmd_latest, "print the latest version folder or workfile")
    p.add_argument("entity")
    kind = p.add_mutually_exclusive_group(required=True)
    kind.add_argument("--product", metavar="NAME")
    kind.add_argument("--usd", metavar="LAYER")
    kind.add_argument("--media", metavar="NAME")
    kind.add_argument("--work", metavar="DEPT[/TASK]")

    p = add("frames", cmd_frames, "show or set an entity's frame range", parents=(json_only,))
    p.add_argument("entity")
    p.add_argument("range", nargs="?", type=_frame_range, help="START-END to set it")

    p = add(
        "finalize", cmd_finalize, "write version.json (and the USD pointer) for a version folder"
    )
    p.add_argument("version_dir")
    p.add_argument("-m", "--message", default="", help="comment")
    p.add_argument("--source", help="workfile it was exported from")
    p.add_argument("--main", help="main USD file when there are several")

    p = add("set-current", cmd_set_current, "point a USD layer at this version")
    p.add_argument("version_dir")
    p.add_argument("--main", help="main USD file when there are several")

    p = add(
        "ingest",
        cmd_ingest,
        "copy files in as new workfile versions or a new product/media version",
    )
    p.add_argument("items", nargs="+", metavar="files... entity [dept/task]")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--product", metavar="NAME")
    target.add_argument("--media", metavar="NAME")

    p = add("context", cmd_context, "show what a path means", parents=(json_only,))
    p.add_argument("path", nargs="?", default=".")

    p = add("env", cmd_env, "print the SW_* environment variables for a path", parents=(json_only,))
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--shell", choices=("zsh", "bash", "pwsh"), help="print as shell commands")

    add(
        "doctor",
        cmd_doctor,
        "report naming problems, conflict copies, absolute paths, empty versions",
    )

    p = add("gui", cmd_gui, "open the Scheinwerk browser", parents=())
    p.add_argument("path", nargs="?", help="open the project (and select what) this path points at")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="backslashreplace")  # odd file names never crash printing
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args) or 0
    except ScheinwerkError as exc:
        print(f"sw: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
