"""Finding the external tools the library runs: hoiiotool, husk, hython (spec §17.2)."""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

from scheinwerk.core.errors import NotFound
from scheinwerk.core.settings import load_settings

# Names to look for on PATH; oiiotool is the same program as Houdini's hoiiotool.
TOOLS = {"hoiiotool": ("hoiiotool", "oiiotool"), "husk": ("husk",), "hython": ("hython",)}
HOUDINI = "21.0"
_MAC_RES = Path("Frameworks/Houdini.framework/Versions/Current/Resources")


def _default_apps(platform: str) -> Path:
    if platform == "win32":
        return Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Side Effects Software"
    if platform == "darwin":
        return Path("/Applications/Houdini")
    return Path("/opt")


def houdini_installs(apps: Path | None = None, platform: str = sys.platform) -> list[Path]:
    """The bin folders of every Houdini 21.0.* in `apps` (the OS's install folder), newest
    first (21.0.1003 is newer than 21.0.596)."""
    apps = apps or _default_apps(platform)
    if platform == "win32":
        pattern, sub = rf"Houdini {re.escape(HOUDINI)}\.([0-9]+)", Path("bin")
    elif platform == "darwin":
        pattern, sub = rf"Houdini{re.escape(HOUDINI)}\.([0-9]+)", _MAC_RES / "bin"
    else:
        pattern, sub = rf"hfs{re.escape(HOUDINI)}\.([0-9]+)", Path("bin")
    try:
        found = [
            (int(m[1]), d / sub) for d in apps.iterdir() if (m := re.fullmatch(pattern, d.name))
        ]
    except (FileNotFoundError, NotADirectoryError):
        return []
    return [p for _, p in sorted(found, reverse=True) if p.is_dir()]


def find_tool(
    name: str,
    *,
    settings: Mapping | None = None,
    env: Mapping[str, str] | None = None,
    apps: Path | None = None,
    platform: str = sys.platform,
) -> Path:
    """The user setting `tools`, else `$HFS/bin`, else the newest Houdini 21.0 install, else
    `PATH` (spec §17.2)."""
    if name not in TOOLS:
        raise ValueError(f"unknown tool: {name!r}")
    settings = load_settings() if settings is None else settings
    env = os.environ if env is None else env
    exe = ".exe" if platform == "win32" else ""

    own = (settings.get("tools") or {}).get(name)
    if own:
        if not Path(own).is_file():
            raise NotFound(f"The user setting tools.{name} points at {own}, which isn't there.")
        return Path(own)
    folders = ([Path(env["HFS"]) / "bin"] if env.get("HFS") else []) + houdini_installs(
        apps, platform
    )
    for folder in folders:
        if (folder / f"{name}{exe}").is_file():
            return folder / f"{name}{exe}"
    for candidate in TOOLS[name]:
        found = shutil.which(candidate, path=env.get("PATH", ""))
        if found:
            return Path(found)
    raise NotFound(
        f"{name} not found: install Houdini {HOUDINI}, or set its path in the user setting "
        f"tools.{name}."
    )
