"""Version counting on any folder (spec §5.4, §17.9): shared by products and the library."""

from __future__ import annotations

from pathlib import Path

import pytest

from scheinwerk.core.version_dirs import highest_version, next_version_dir, version_dirs
from tests.conftest import touch


def test_missing_folder_has_no_versions(tmp_path: Path) -> None:
    assert version_dirs(tmp_path / "nope") == []
    assert highest_version(tmp_path / "nope") is None


def test_version_dirs_newest_first_only_version_folders(tmp_path: Path) -> None:
    for name in ("v001", "v010", "v002", "notes", "v1", "V003", "_v004"):
        (tmp_path / name).mkdir()
    touch(tmp_path / "v005")  # a file, not a folder
    assert [p.name for p in version_dirs(tmp_path)] == ["v010", "v002", "v001"]


def test_v1000_and_up(tmp_path: Path) -> None:
    for name in ("v999", "v1000"):
        (tmp_path / name).mkdir()
    assert [p.name for p in version_dirs(tmp_path)] == ["v1000", "v999"]
    assert highest_version(tmp_path) == 1000
    assert next_version_dir(tmp_path).name == "v1001"


def test_first_version_creates_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "item"
    assert next_version_dir(folder) == folder / "v001"
    assert (folder / "v001").is_dir()


@pytest.mark.parametrize(
    ("have", "expected"),
    [([], "v001"), (["v001"], "v002"), (["v001", "v003"], "v004"), (["v007"], "v008")],
)
def test_next_is_highest_plus_one_gaps_kept(tmp_path: Path, have: list[str], expected: str) -> None:
    for name in have:
        (tmp_path / name).mkdir()
    assert next_version_dir(tmp_path).name == expected


def test_empty_folders_count(tmp_path: Path) -> None:
    (tmp_path / "v004").mkdir()  # empty: still taken
    assert highest_version(tmp_path) == 4
    assert next_version_dir(tmp_path).name == "v005"


def test_never_reuses_a_taken_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "v001").mkdir()
    # someone else creates v002 between the count and the mkdir
    import scheinwerk.core.version_dirs as vd

    real = vd.highest_version
    monkeypatch.setattr(vd, "highest_version", lambda f: (tmp_path / "v002").mkdir() or real(f) - 1)
    assert next_version_dir(tmp_path).name == "v003"
