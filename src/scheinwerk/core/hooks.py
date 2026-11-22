"""Hooks: plain functions in project and user .py files (spec §14)."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from scheinwerk.core import settings

HOOK_NAMES = ("post_create", "post_save", "post_publish")

log = logging.getLogger("scheinwerk.hooks")


def hook_files(root: Path | None) -> list[Path]:
    """Project hooks first, then user hooks. Files starting with `_` are skipped."""
    folders = ([root / "shared" / "hooks"] if root else []) + [settings.user_dir() / "hooks"]
    return [
        f for folder in folders for f in sorted(folder.glob("*.py")) if not f.name.startswith("_")
    ]


def run_hook(name: str, **kwargs: object) -> None:
    """Call `name(**kwargs)` in every hook file that defines it.

    The project is taken from the `context` keyword. Errors inside hooks are
    logged and never block the action.
    """
    if name not in HOOK_NAMES:
        raise ValueError(f"unknown hook: {name!r}")
    context = kwargs.get("context")
    root = getattr(context, "root", None)
    for index, file in enumerate(hook_files(root)):
        try:
            spec = importlib.util.spec_from_file_location(f"_sw_hook_{index}_{file.stem}", file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            func = getattr(module, name, None)
            if callable(func):
                func(**kwargs)
        except Exception:
            log.exception("Hook %s in %s failed", name, file)


def post_create(kind: str, path: Path) -> None:
    from scheinwerk.core.context import Context

    run_hook("post_create", kind=kind, path=path, context=Context.from_path(path))
