"""Environment variables for the open file (spec §7.2)."""

from __future__ import annotations

from dataclasses import replace

from scheinwerk.core.context import Context


def env_for(context: Context) -> dict[str, str]:
    """Every §7.2 variable except Houdini's JOB. Keys that don't apply are "".

    Paths use forward slashes on every OS: Houdini, Nuke and Blender all accept
    them, and they need no escaping in expressions.
    """
    entity = replace(
        context, dept=None, task=None, area=None, product=None, usd=False, version=None, ext=None
    )
    env = {
        "SW_ROOT": context.root.as_posix(),
        "SW_ENTITY_TYPE": context.entity_type,
        "SW_ENTITY": context.entity,
        "SW_SEQ": context.sequence or "",
        "SW_DEPT": context.dept or "",
        "SW_TASK": context.task or "",
        "SW_TASK_DIR": "",
        "SW_CACHE": "",
        "SW_ENTITY_DIR": entity.path().as_posix(),
    }
    if context.dept and context.task:
        task_dir = replace(entity, dept=context.dept, task=context.task).path()
        env["SW_TASK_DIR"] = task_dir.as_posix()
        env["SW_CACHE"] = (task_dir / "cache").as_posix()
    return env
