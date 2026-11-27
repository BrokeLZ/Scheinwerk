"""The library browser (spec §17.11): Browse and Ingest views under one top bar.

A plain QWidget (like the project browser) so Houdini can dock it later; `main()` opens it as
its own window (`sw lib gui`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.gui.browser import load_theme
from scheinwerk.gui.library.browse import BrowseView
from scheinwerk.gui.library.ingest import IngestView
from scheinwerk.gui.library.jobs import JobQueue
from scheinwerk.library.ingest import HoiioTools
from scheinwerk.library.root import Library, configured_library


def _color_spaces() -> list[str]:
    """The OCIO config's colour spaces, for the Ingest view's choices ([] without hoiiotool)."""
    try:
        return HoiioTools.find().info.color_spaces
    except ScheinwerkError:
        return []


class LibraryBrowser(QWidget):
    def __init__(
        self,
        library: Library | None = None,
        queue: JobQueue | None = None,
        spaces: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("browser")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(load_theme())
        self.setAcceptDrops(True)
        self.queue = queue or JobQueue(parent=self)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        if library is None:
            try:
                library = configured_library()
            except ScheinwerkError as exc:
                self._no_library(str(exc))
                return
        self._build(library, _color_spaces() if spaces is None else spaces)

    def _no_library(self, message: str) -> None:
        box = QWidget()
        layout = QVBoxLayout(box)
        note = QLabel(
            f"{message}\n\nChoose a folder to create a library in, or a synced "
            "library to use on this machine."
        )
        note.setObjectName("detail")
        note.setWordWrap(True)
        button = QPushButton("Set up a library…")
        button.setObjectName("topButton")
        button.clicked.connect(self._set_up)
        layout.addWidget(note)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.setup_box = box
        self.layout_.addWidget(box)

    def _set_up(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Library folder")
        if not folder:
            return

        def done(job) -> None:
            if not job.ok:
                self.setup_box.findChild(QLabel).setText(job.error)
                return
            self.setup_box.deleteLater()
            self._build(configured_library(), _color_spaces())

        self.queue.submit(["lib", "init", folder], on_done=done)

    def _build(self, library: Library, spaces: list[str]) -> None:
        self.library = library
        top = QHBoxLayout()
        top.setContentsMargins(12, 12, 12, 0)
        self.view_buttons = QButtonGroup(self)
        for index, label in enumerate(("Browse", "Ingest")):
            button = QPushButton(label)
            button.setObjectName("viewButton")
            button.setCheckable(True)
            self.view_buttons.addButton(button, index)
            top.addWidget(button)
        self.view_buttons.idClicked.connect(self.show_view)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("search …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda t: self.browse.set_text(t))
        top.addWidget(self.search, 2)
        reload = QPushButton("Reload")
        reload.setObjectName("topButton")
        reload.clicked.connect(lambda: self.browse.reload())
        top.addWidget(reload)

        self.browse = BrowseView(library, self.queue)
        self.ingest = IngestView(
            self.queue,
            spaces,
            lambda: [i.id for i in library.items()],
            known=lambda: self.browse.known,
        )
        self.browse.ingestRequested.connect(self.ingest_paths)
        self.ingest.showItem.connect(self.show_item)
        self.ingest.ingested.connect(lambda: self.browse.reload())
        self.stack = QStackedWidget()
        self.stack.addWidget(self.browse)
        self.stack.addWidget(self.ingest)
        self.layout_.addLayout(top)
        self.layout_.addWidget(self.stack, 1)
        self.show_view(0)

    def show_view(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.view_buttons.button(index).setChecked(True)
        self.search.setEnabled(index == 0)

    def ingest_paths(self, paths: list[Path], target: dict | None = None) -> None:
        self.show_view(1)
        self.ingest.add_paths(paths, target)

    def show_item(self, key: str) -> None:
        self.show_view(0)
        self.search.clear()
        self.browse.select(key)

    # drops anywhere outside the grid open the Ingest view (spec §17.11)
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasUrls() and hasattr(self, "ingest"):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.ingest_paths(paths)
            event.acceptProposedAction()


def main(argv: list[str] | None = None) -> int:
    """`sw lib gui`."""
    args = sys.argv[1:] if argv is None else argv
    app = QApplication.instance() or QApplication([sys.argv[0], *args])
    app.setApplicationName("Scheinwerk Library")
    window = LibraryBrowser()
    window.setWindowTitle("Scheinwerk Library")
    window.resize(1500, 920)
    window.show()
    return app.exec()
