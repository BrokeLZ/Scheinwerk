from __future__ import annotations

import json
from pathlib import Path

import pytest

from scheinwerk.library.root import Library


@pytest.fixture
def lib(tmp_path: Path) -> Library:
    return Library.create(tmp_path / "library")


def write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_item(
    lib: Library, type_: str, item_id: str, versions: dict[int, dict | None], **meta: object
) -> Path:
    """An item folder by hand: item.json from `meta`, and v### folders whose value is the
    version.json content (None = incomplete: no version.json)."""
    folder = lib.root / type_ / item_id
    folder.mkdir(parents=True)
    if meta:
        write_json(folder / "item.json", {"schema": 1, **meta})
    for number, info in versions.items():
        vdir = folder / f"v{number:03d}"
        vdir.mkdir()
        if info is not None:
            write_json(vdir / "version.json", {"schema": 1, **info})
    return folder
