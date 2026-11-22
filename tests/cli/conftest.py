from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from scheinwerk.cli import main


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def json(self) -> object:
        return json.loads(self.out)

    @property
    def lines(self) -> list[str]:
        return self.out.splitlines()


@pytest.fixture
def sw(capsys: pytest.CaptureFixture[str]) -> Callable[..., Result]:
    """Run `sw` in-process: sw("new", "asset", "hero")."""

    def run(*args: str | Path) -> Result:
        try:
            code = main([str(a) for a in args])
        except SystemExit as exc:  # argparse usage errors
            code = exc.code
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return run


@pytest.fixture
def inside(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run from the project root, like a user who cd'd into it."""
    monkeypatch.chdir(project)
    return project
