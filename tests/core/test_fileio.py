"""Atomic writes and safe copies (spec §8, CLAUDE.md rules 7 and 8)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scheinwerk.core.errors import AlreadyExists
from scheinwerk.core.fileio import copy_new, read_json, write_json, write_text


def test_write_json_format(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    write_json(path, {"schema": 1, "comment": "grün", "frames": [1001, 1096]})
    assert path.read_bytes().decode("utf-8") == (
        '{\n  "schema": 1,\n  "comment": "grün",\n  "frames": [\n    1001,\n    1096\n  ]\n}\n'
    )


def test_line_endings_are_lf_on_every_os(tmp_path: Path) -> None:
    path = tmp_path / "x.usd"
    write_text(path, "a\nb\n")
    assert b"\r\n" not in path.read_bytes()


def test_no_tmp_file_left(tmp_path: Path) -> None:
    write_json(tmp_path / "x.json", {"schema": 1})
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_replaces_existing(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("old", encoding="utf-8")
    write_json(path, {"schema": 2})
    assert read_json(path) == {"schema": 2}


def test_failed_write_leaves_original(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    write_json(path, {"schema": 1})
    with pytest.raises(TypeError):
        write_json(path, {"bad": object()})
    assert read_json(path) == {"schema": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_stale_tmp_from_a_crash_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "x.json.tmp").write_text("garbage", encoding="utf-8")
    write_json(tmp_path / "x.json", {"schema": 1})
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_unchanged_content_is_not_rewritten(tmp_path: Path) -> None:
    # Saves sync churn on Synology Drive.
    path = tmp_path / "x.json"
    write_json(path, {"schema": 1})
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    write_json(path, {"schema": 1})
    assert path.stat().st_mtime_ns == 1_000_000_000


@pytest.mark.parametrize("content", [None, b"not json", b"[1, 2]"])
def test_read_json_missing_or_invalid_is_none(tmp_path: Path, content: bytes | None) -> None:
    path = tmp_path / "x.json"
    if content is not None:
        path.write_bytes(content)
    assert read_json(path) is None


def test_copy_new(tmp_path: Path) -> None:
    src = tmp_path / "a.hip"
    src.write_bytes(b"scene")
    dest = tmp_path / "b.hip"
    copy_new(src, dest)
    assert dest.read_bytes() == b"scene"
    assert src.read_bytes() == b"scene"


def test_copy_new_never_overwrites(tmp_path: Path) -> None:
    src = tmp_path / "a.hip"
    src.write_bytes(b"new")
    dest = tmp_path / "b.hip"
    dest.write_bytes(b"precious")
    with pytest.raises(AlreadyExists):
        copy_new(src, dest)
    assert dest.read_bytes() == b"precious"
