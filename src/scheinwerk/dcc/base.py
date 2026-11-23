"""What every DCC adapter provides (spec §13.1)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class DCCAdapter(Protocol):
    name: str
    extensions: tuple[str, ...]

    def current_file(self) -> Path | None: ...
    def open(self, path: Path) -> None: ...
    def save_as(self, path: Path) -> None: ...
    def main_window(self) -> QWidget | None: ...
