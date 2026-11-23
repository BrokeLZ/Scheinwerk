"""Installing DCC integrations: the Houdini package file (spec §13.2).

Writes only into Houdini's machine-local preferences, never into a project.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from scheinwerk.core.errors import AlreadyExists, NotFound
from scheinwerk.core.fileio import read_json, write_json

PACKAGE = "scheinwerk.json"
TEMPLATE = Path("integrations") / "houdini" / PACKAGE
MARKER = "SCHEINWERK"  # the package's env variable: a file that sets it is ours


def documents_dir(home: Path | None = None) -> Path:
    """The Windows Documents folder: `home`/Documents when `home` is given, else the one
    registered for the user, which can be moved (e.g. to D:\\you\\Dokumente) and which
    Houdini follows. Falls back to ~/Documents."""
    if home is None and sys.platform == "win32":
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "Personal")
            return Path(os.path.expandvars(value))  # may be "%USERPROFILE%\Documents"
        except OSError:
            pass
    return (home or Path.home()) / "Documents"


def houdini_pref_dirs(home: Path | None = None, platform: str = sys.platform) -> list[Path]:
    """Houdini's per-version preference folders that exist (Houdini makes them on first start)."""
    if platform == "win32":
        base, pattern = documents_dir(home), r"houdini[0-9]+\.[0-9]+"
    elif platform == "darwin":
        home = home or Path.home()
        base, pattern = home / "Library" / "Preferences" / "houdini", r"[0-9]+\.[0-9]+"
    else:
        base = home or Path.home()
        pattern = r"houdini[0-9]+\.[0-9]+"
    if not base.is_dir():
        return []
    return sorted(d for d in base.iterdir() if d.is_dir() and re.fullmatch(pattern, d.name))


def _ours(path: Path) -> bool:
    data = read_json(path) or {}
    return any(isinstance(e, dict) and MARKER in e for e in data.get("env", []))


def package_data(repo: Path) -> dict:
    """The package template with SCHEINWERK pointing at `repo`."""
    data = read_json(repo / TEMPLATE)
    if data is None:
        raise NotFound(f"{repo / TEMPLATE} is missing: run this from a Scheinwerk checkout.")
    data["env"] = [{MARKER: repo.as_posix()} if MARKER in e else e for e in data["env"]]
    return data


def install_houdini(
    repo: Path, home: Path | None = None, platform: str = sys.platform
) -> list[Path]:
    """Write packages/scheinwerk.json into every Houdini preference folder, pointing at
    `repo`. All or nothing: refuses if any of them holds a scheinwerk.json we didn't write."""
    data = package_data(repo)
    dirs = houdini_pref_dirs(home, platform)
    if not dirs:
        raise NotFound("No Houdini preferences folder found. Start Houdini once, then try again.")
    targets = [d / "packages" / PACKAGE for d in dirs]
    for target in targets:
        if target.exists() and not _ours(target):
            raise AlreadyExists(f"{target} exists and wasn't written by Scheinwerk; leaving it.")
    for target in targets:
        target.parent.mkdir(exist_ok=True)
        write_json(target, data)
    return targets


def uninstall_houdini(home: Path | None = None, platform: str = sys.platform) -> list[Path]:
    """Remove the package files `install_houdini` wrote. Other files are left alone."""
    removed = []
    for folder in houdini_pref_dirs(home, platform):
        target = folder / "packages" / PACKAGE
        if target.is_file() and _ours(target):
            target.unlink()
            removed.append(target)
    return removed
