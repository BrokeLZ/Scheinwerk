"""library.json, the library root, the configured library (spec §17.2, §17.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scheinwerk.core import settings
from scheinwerk.core.errors import AlreadyExists, NotFound
from scheinwerk.library.root import DEFAULTS, TYPES, WORKSHOP, Library, configured_library


def test_create_writes_library_json(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "lib")
    data = json.loads((tmp_path / "lib" / "library.json").read_text(encoding="utf-8"))
    assert data == {"schema": 1, **DEFAULTS}
    assert data["working_space"] == "ACEScg"
    assert lib.name == "library"
    assert lib.working_space == "ACEScg"


def test_create_in_an_existing_folder_with_other_files(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "notes.txt").write_text("hi", encoding="utf-8")
    Library.create(tmp_path / "lib", name="studio_lib")
    assert Library.open(tmp_path / "lib").name == "studio_lib"
    assert (tmp_path / "lib" / "notes.txt").exists()


def test_create_refuses_an_existing_library(lib: Library) -> None:
    with pytest.raises(AlreadyExists):
        Library.create(lib.root)


def test_create_refuses_an_invalid_name(tmp_path: Path) -> None:
    from scheinwerk.core.errors import InvalidName

    with pytest.raises(InvalidName):
        Library.create(tmp_path / "lib", name="My Lib")


def test_open_needs_library_json(tmp_path: Path) -> None:
    with pytest.raises(NotFound):
        Library.open(tmp_path)


def test_missing_keys_read_as_defaults_unknown_kept(tmp_path: Path) -> None:
    (tmp_path / "library.json").write_text('{"schema": 1, "mine": 2}', encoding="utf-8")
    lib = Library.open(tmp_path)
    assert lib.name == "library" and lib.working_space == "ACEScg"
    assert lib.config["mine"] == 2


def test_ignore_patterns(lib: Library) -> None:
    for name in ("model", "backup", ".DS_Store", "._model", "@eaDir", "x~"):
        (lib.root / name).mkdir()
    assert [p.name for p in lib.scan(lib.root)] == ["model"]


def test_unknown_root_entries_are_flagged(lib: Library) -> None:
    for name in ("model", "hdri", "_workshop", "stuff", "Texture"):
        (lib.root / name).mkdir()
    (lib.root / "readme.txt").write_text("", encoding="utf-8")
    assert [p.name for p in lib.unknown()] == ["Texture", "readme.txt", "stuff"]


def test_types() -> None:
    assert TYPES == ("hdri", "texture", "texture_set", "model")
    assert WORKSHOP == "_workshop"


# --- the configured library (user setting `library`) --------------------------------------


def test_no_library_configured() -> None:
    with pytest.raises(NotFound, match="sw lib init"):
        configured_library()


def test_configured_library(lib: Library) -> None:
    settings.set_library(lib.root)
    assert settings.load_settings()["library"] == str(lib.root)
    assert configured_library().root == lib.root


def test_configured_library_gone(tmp_path: Path) -> None:
    settings.set_library(tmp_path / "gone")
    with pytest.raises(NotFound, match="gone"):
        configured_library()
