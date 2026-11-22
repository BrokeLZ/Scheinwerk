"""Standalone window around the browser. DCCs embed `Browser` directly instead."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from scheinwerk.core.settings import load_settings, save_settings
from scheinwerk.gui.browser import Browser


class Window(QWidget):
    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Scheinwerk")
        self.browser = Browser(path, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        geometry = load_settings()["gui"].get("geometry")
        if isinstance(geometry, list) and len(geometry) == 4:
            self.setGeometry(*geometry)
        else:
            self.resize(1280, 800)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        settings = load_settings()
        g = self.geometry()
        settings["gui"] = {
            **settings["gui"],
            "last_view": self.browser.view,
            "geometry": [g.x(), g.y(), g.width(), g.height()],
        }
        save_settings(settings)
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    """`scheinwerk-gui [path]` / `sw gui [path]`."""
    args = sys.argv[1:] if argv is None else argv
    app = QApplication.instance() or QApplication([sys.argv[0], *args])
    app.setApplicationName("Scheinwerk")
    window = Window(Path(args[0]).absolute() if args else None)
    window.show()
    return app.exec()
