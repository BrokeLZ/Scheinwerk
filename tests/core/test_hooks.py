"""Hooks (spec §14)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from scheinwerk.core.context import Context
from scheinwerk.core.hooks import run_hook
from scheinwerk.core.project import Project
from scheinwerk.core.publish import finalize, next_publish
from tests.conftest import touch

LOGGER = """
import pathlib

LOG = pathlib.Path({log!r})

def _write(line):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\\n")

def post_create(kind, path, context):
    _write(f"{tag} create {{kind}} {{path.name}} {{context.entity}}")

def post_publish(version_dir, context):
    _write(f"{tag} publish {{version_dir.name}} {{context.product}}")

def post_save(path, context):
    _write(f"{tag} save {{path.name}}")
"""


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return tmp_path / "hooks.log"


def add_hook(folder: Path, name: str, log: Path, tag: str) -> None:
    touch(folder / name, LOGGER.format(log=str(log), tag=tag).encode("utf-8"))


def lines(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_post_create(proj: Project, log: Path) -> None:
    add_hook(proj.root / "shared/hooks", "log.py", log, "p")
    proj.create_shot("sq010_0010")
    hero = proj.create_asset("hero")
    hero.create_department("mdl")
    hero.create_product("pants")
    assert lines(log) == [
        "p create sequence sq010 sq010",
        "p create shot sq010_0010 sq010_0010",
        "p create asset hero hero",
        "p create dept mdl hero",
        "p create task main hero",
        "p create product pants hero",
    ]


def test_project_hooks_run_before_user_hooks(proj: Project, user_dir: Path, log: Path) -> None:
    add_hook(user_dir / "hooks", "a.py", log, "user")
    add_hook(proj.root / "shared/hooks", "z.py", log, "project")
    proj.create_asset("hero")
    assert lines(log) == ["project create asset hero hero", "user create asset hero hero"]


def test_post_publish(proj: Project, log: Path) -> None:
    add_hook(proj.root / "shared/hooks", "log.py", log, "p")
    vdir = next_publish(proj.create_asset("hero"), "pants")
    log.unlink()
    finalize(vdir)
    assert lines(log) == ["p publish v001 pants"]


def test_post_save_called_directly(proj: Project, log: Path) -> None:
    add_hook(proj.root / "shared/hooks", "log.py", log, "p")
    path = proj.root / "assets/hero/mdl/main/work/hero_mdl_main_v002.hip"
    run_hook("post_save", path=path, context=Context.from_path(path))
    assert lines(log) == ["p save hero_mdl_main_v002.hip"]


def test_broken_hook_is_logged_and_never_blocks(
    proj: Project, log: Path, caplog: pytest.LogCaptureFixture
) -> None:
    touch(
        proj.root / "shared/hooks/a_broken.py",
        b"def post_create(**kw):\n    raise RuntimeError('boom')\n",
    )
    touch(proj.root / "shared/hooks/b_syntax.py", b"def (:\n")
    add_hook(proj.root / "shared/hooks", "c_log.py", log, "p")
    with caplog.at_level(logging.ERROR, logger="scheinwerk.hooks"):
        hero = proj.create_asset("hero")
    assert hero.path.is_dir()
    assert lines(log) == ["p create asset hero hero"]
    assert "a_broken.py" in caplog.text and "b_syntax.py" in caplog.text


def test_underscore_files_and_missing_functions_are_skipped(proj: Project, log: Path) -> None:
    add_hook(proj.root / "shared/hooks", "_private.py", log, "private")
    touch(proj.root / "shared/hooks/other.py", b"def something_else():\n    pass\n")
    proj.create_asset("hero")
    assert lines(log) == []


def test_unknown_hook_name() -> None:
    with pytest.raises(ValueError):
        run_hook("pre_everything")
