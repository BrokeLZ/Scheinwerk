"""Environment variables from a context (spec §7.2)."""

from __future__ import annotations

from pathlib import Path

from scheinwerk.core.context import Context
from scheinwerk.core.env import env_for

KEYS = {
    "SW_ROOT",
    "SW_ENTITY_TYPE",
    "SW_ENTITY",
    "SW_SEQ",
    "SW_DEPT",
    "SW_TASK",
    "SW_TASK_DIR",
    "SW_CACHE",
    "SW_ENTITY_DIR",
}


def test_shot_workfile(project: Path) -> None:
    ctx = Context.from_path(
        project / "shots/sq010/sq010_0010/lgt/main/work/sq010_0010_lgt_main_v012.hip"
    )
    root = project.as_posix()
    assert env_for(ctx) == {
        "SW_ROOT": root,
        "SW_ENTITY_TYPE": "shot",
        "SW_ENTITY": "sq010_0010",
        "SW_SEQ": "sq010",
        "SW_DEPT": "lgt",
        "SW_TASK": "main",
        "SW_TASK_DIR": f"{root}/shots/sq010/sq010_0010/lgt/main",
        "SW_CACHE": f"{root}/shots/sq010/sq010_0010/lgt/main/cache",
        "SW_ENTITY_DIR": f"{root}/shots/sq010/sq010_0010",
    }


def test_keys_that_dont_apply_are_empty(project: Path) -> None:
    # Always every key, so an integration overwrites values left over from the last file.
    env = env_for(Context.from_path(project / "assets/char/hero/publish/pants/v001"))
    assert set(env) == KEYS
    assert (env["SW_SEQ"], env["SW_DEPT"], env["SW_TASK"], env["SW_TASK_DIR"], env["SW_CACHE"]) == (
        "",
        "",
        "",
        "",
        "",
    )
    assert env["SW_ENTITY_DIR"] == f"{project.as_posix()}/assets/char/hero"


def test_sequence(project: Path) -> None:
    env = env_for(Context.from_path(project / "shots/sq010/_seq/lgt/main/work"))
    assert (env["SW_ENTITY_TYPE"], env["SW_ENTITY"], env["SW_SEQ"]) == (
        "sequence",
        "sq010",
        "sq010",
    )
    assert env["SW_ENTITY_DIR"] == f"{project.as_posix()}/shots/sq010/_seq"


def test_forward_slashes_on_every_os(project: Path) -> None:
    env = env_for(Context.from_path(project / "assets/hero/mdl/main/work"))
    assert all("\\" not in value for value in env.values())
