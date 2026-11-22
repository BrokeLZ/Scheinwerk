"""Finding a project and reading its config (spec §2.3, §8.1)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from scheinwerk.core.errors import ScheinwerkError

MARKER = "scheinwerk.json"


def find_root(path: str | os.PathLike[str]) -> Path | None:
    """Walk up from `path` (which need not exist) to the folder holding scheinwerk.json."""
    start = Path(path).absolute()
    for folder in (start, *start.parents):
        if (folder / MARKER).is_file():
            return folder
    return None


def read_config(root: Path) -> dict:
    try:
        return json.loads((root / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScheinwerkError(f"Can't read {root / MARKER}: {exc}") from exc
