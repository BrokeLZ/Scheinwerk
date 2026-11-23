"""Choosing a product or USD layer for an import or publish node (spec §13.2.6).

The browser in its Products view, as a dialog: pick an asset or shot and a product or
layer. Importing: follow the latest version or pin the selected one. Publishing: only the
entities the scene may publish to are accepted, and no version is chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from scheinwerk.core.entities import Entity
from scheinwerk.core.errors import ScheinwerkError
from scheinwerk.core.templates import parse_version
from scheinwerk.core.versions import Product
from scheinwerk.gui import dialogs
from scheinwerk.gui.browser import Browser, load_theme


@dataclass(frozen=True)
class Choice:
    entity: Entity
    product: Product | None  # None: importing, the whole entry layer; publishing, a new name
    version: int | None  # None: follow the latest version (USD: the pointer)


class PickDialog(QDialog):
    def __init__(
        self,
        scene: Path,
        usd: bool,
        entity: str = "",
        product: str = "",
        version: str = "",
        parent: QWidget | None = None,
        allowed: list[Entity] | None = None,
    ) -> None:
        """`allowed`: publishing into one of these entities (None: importing, anything)."""
        super().__init__(parent)
        self.usd = usd
        self.allowed = allowed
        kind = "USD layer" if usd else "product"
        verb = " to publish to" if allowed is not None else ""
        self.setWindowTitle(f"Choose a {kind}{verb}")
        self.setStyleSheet(load_theme())
        self.resize(1100, 650)
        self.browser = Browser(scene)
        self.browser.picking = True
        self.browser.picked.connect(self.accept)
        self.browser.product_filter = (lambda p: p.usd) if usd else (lambda p: not p.usd)
        for button in self.browser.view_buttons.buttons():
            button.hide()
        self.browser.project_box.hide()
        self.browser.set_view("products")
        pinned = parse_version(version) if version else None
        target = self._entity(entity)
        key = (("usd:" if usd else "") + product) if product else None
        self.browser.preselect(target, key, version if pinned else None)

        self.follow = QCheckBox(
            "Use the layer's current version (its pointer)"
            if usd
            else "Always load the latest version"
        )
        self.follow.setChecked(pinned is None)
        self.follow.setVisible(allowed is None)
        self.whole = QCheckBox("All layers of the entity (its entry layer)")
        self.whole.setChecked(usd and not product and allowed is None)
        self.whole.setVisible(usd and allowed is None)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.browser, 1)
        layout.addWidget(self.whole)
        layout.addWidget(self.follow)
        layout.addWidget(buttons)
        self.choice: Choice | None = None

    def _entity(self, name: str) -> Entity | None:
        if not name or self.browser.project is None:
            return None
        try:
            return self.browser.project.entity(name)
        except ScheinwerkError:
            return None

    def _check(self) -> Choice:
        entity = self.browser.entity()
        if entity is None:
            raise ScheinwerkError("Choose an asset, shot or sequence.")
        if self.allowed is not None and entity not in self.allowed:
            names = ", ".join(e.name for e in self.allowed) or "nothing"
            raise ScheinwerkError(f"This scene publishes to {names}, not to {entity.name}.")
        if self.usd and self.whole.isChecked():
            return Choice(entity, None, None)
        product = self.browser.product()
        if product is None:
            if self.allowed is not None:
                return Choice(entity, None, None)  # publishing: a shot without products yet
            raise ScheinwerkError("Choose a USD layer." if self.usd else "Choose a product.")
        if product.usd != self.usd:
            raise ScheinwerkError(
                f"{product.name} is a product, not a USD layer."
                if self.usd
                else f"{product.name} is a USD layer: use Scheinwerk Import USD for it."
            )
        if self.follow.isChecked() or self.allowed is not None:
            return Choice(entity, product, None)
        version = self.browser.version()
        if version is None:
            raise ScheinwerkError(f"{product.name} has no version to pin.")
        return Choice(entity, product, version.number)

    def accept(self) -> None:
        try:
            self.choice = self._check()
        except ScheinwerkError as exc:
            dialogs.error(self, exc)
            return
        super().accept()


def pick(
    scene: Path,
    usd: bool,
    entity: str = "",
    product: str = "",
    version: str = "",
    parent: QWidget | None = None,
    allowed: list[Entity] | None = None,
) -> Choice | None:
    """Show the picker; the choice, or None if cancelled. `allowed`: publishing mode."""
    dialog = PickDialog(scene, usd, entity, product, version, parent, allowed)
    return dialog.choice if dialog.exec() == QDialog.DialogCode.Accepted else None
