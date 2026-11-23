"""The product / USD layer picker used by the import HDAs (gui/pick.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from scheinwerk.core.project import Project
from scheinwerk.core.publish import finalize, next_usd
from scheinwerk.gui import dialogs
from scheinwerk.gui.pick import PickDialog, pick
from tests.conftest import touch


@pytest.fixture
def scene(proj: Project) -> Path:
    hero = proj.create_asset("hero", category="char")
    hero.create_department("lookdev")
    for v in ("v001", "v002"):
        touch(hero.path / f"publish/pants/{v}/hero_pants_{v}.abc")
    touch(hero.path / "publish/cloth/v001/hero_cloth_v001.abc")
    layer = next_usd(hero, "asset")
    touch(layer / "hero_asset_v001.usd", b"#usda 1.0\n")
    finalize(layer)
    shot = proj.create_shot("sq010_0010")
    touch(shot.path / "publish/cam/v001/sq010_0010_cam_v001.abc")
    return touch(hero.path / "lookdev/main/work/hero_lookdev_main_v001.hip")


def test_opens_on_the_scene_and_follows_latest(qapp, scene: Path) -> None:
    dialog = PickDialog(scene, usd=False)
    assert dialog.browser.view == "products"
    assert dialog.browser.entity().name == "hero"
    assert dialog.follow.isChecked() and not dialog.whole.isVisible()
    dialog.browser.cols[0].select_key("pants")
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    choice = dialog.choice
    assert (choice.entity.name, choice.product.name, choice.version) == ("hero", "pants", None)


def test_pins_the_selected_version(qapp, scene: Path) -> None:
    dialog = PickDialog(scene, usd=False, entity="hero", product="pants")
    dialog.follow.setChecked(False)
    dialog.browser.cols[1].select_key("v001")
    dialog.accept()
    assert dialog.choice.version == 1


def test_preselects_the_nodes_choice(qapp, scene: Path) -> None:
    dialog = PickDialog(scene, usd=False, entity="sq010_0010", product="cam", version="v001")
    assert dialog.browser.mode == "shots"
    assert (dialog.browser.entity().name, dialog.browser.product().name) == ("sq010_0010", "cam")
    assert dialog.browser.version().number == 1 and not dialog.follow.isChecked()


def test_lists_only_the_matching_kind(qapp, scene: Path) -> None:
    products = PickDialog(scene, usd=False)
    assert [p.name for p in products.browser.cols[0].all_data() if p] == ["cloth", "pants"]
    layers = PickDialog(scene, usd=True, product="asset")
    assert [p.name for p in layers.browser.cols[0].all_data() if p] == ["asset"]


def test_usd_whole_entity_or_one_layer(qapp, scene: Path) -> None:
    whole = PickDialog(scene, usd=True)
    assert whole.whole.isChecked()
    whole.accept()
    assert (whole.choice.entity.name, whole.choice.product) == ("hero", None)
    one = PickDialog(scene, usd=True, product="asset")
    assert not one.whole.isChecked()
    one.accept()
    assert one.choice.product.name == "asset" and one.choice.version is None


@pytest.mark.parametrize("column", [0, 1, 2])  # product, version, file
def test_double_click_picks(qapp, scene: Path, column: int) -> None:
    from scheinwerk.gui import actions

    dialog = PickDialog(scene, usd=False, entity="hero", product="pants")
    dialog.follow.setChecked(False)
    dialog.browser.cols[1].select_key("v001")
    data = dialog.browser.cols[column].current_data()
    assert data is not None
    actions.activate(dialog.browser, column, data)
    assert dialog.result() == dialog.DialogCode.Accepted
    assert (dialog.choice.product.name, dialog.choice.version) == ("pants", 1)


def test_pick_function(qapp, scene: Path) -> None:
    def go() -> None:
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(10, go)
            return
        dialog.browser.cols[0].select_key("pants")
        dialog.accept()

    QTimer.singleShot(0, go)
    assert pick(scene, usd=False).product.name == "pants"
    QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
    assert pick(scene, usd=False) is None


def test_publish_mode(qapp, scene: Path, proj: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    shown = []
    monkeypatch.setattr(dialogs, "error", lambda parent, exc: shown.append(str(exc)))
    hero = proj.entity("hero")
    dialog = PickDialog(scene, usd=False, entity="hero", product="pants", allowed=[hero])
    assert dialog.windowTitle() == "Choose a product to publish to"
    assert dialog.follow.isHidden() and dialog.whole.isHidden()
    dialog.follow.setChecked(False)  # hidden, and ignored when publishing
    dialog.accept()
    assert (dialog.choice.product.name, dialog.choice.version) == ("pants", None)
    other = PickDialog(scene, usd=False, entity="sq010_0010", product="cam", allowed=[hero])
    other.accept()
    assert other.choice is None and "publishes to hero, not to sq010_0010" in shown[0]


def test_publish_to_a_shot_without_products(qapp, scene: Path, proj: Project) -> None:
    """A sequence scene publishing a new product into a shot that has none (or only USD
    layers): choosing the shot is enough."""
    seq_scene = touch(proj.root / "shots/sq010/_seq/lgt/main/work/sq010_lgt_main_v001.hip")
    empty = proj.create_shot("sq010_0020")
    layers_only = proj.create_shot("sq010_0030")
    layer = next_usd(layers_only, "lgt")
    touch(layer / "sq010_0030_lgt_v001.usd", b"#usda 1.0\n")
    finalize(layer)
    shots = proj.shots("sq010")
    for shot in (empty, layers_only):
        dialog = PickDialog(seq_scene, usd=False, entity=shot.name, allowed=shots)
        assert dialog.browser.product() is None
        dialog.accept()
        assert (dialog.choice.entity, dialog.choice.product) == (shot, None)
    usd = PickDialog(seq_scene, usd=True, entity="sq010_0020", allowed=shots)
    usd.accept()
    assert (usd.choice.entity.name, usd.choice.product) == ("sq010_0020", None)


def test_rows_stay_light_under_a_host_style(qapp, scene: Path) -> None:
    """Houdini's Qt style paints item-view rows itself (dark) wherever our theme leaves
    them transparent. Stand in for it and check a row is drawn in the theme's colour."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QProxyStyle, QStyle

    dark = QColor(43, 43, 43)

    class HostStyle(QProxyStyle):
        def drawPrimitive(self, element, option, painter, widget=None):  # noqa: N802
            rows = (
                QStyle.PrimitiveElement.PE_PanelItemViewRow,
                QStyle.PrimitiveElement.PE_PanelItemViewItem,
            )
            if element in rows:
                painter.fillRect(option.rect, dark)
                return
            super().drawPrimitive(element, option, painter, widget)

    dialog = PickDialog(scene, usd=False)
    tree = dialog.browser.entities.tree
    host = HostStyle()
    tree.setStyle(host)
    dialog.resize(900, 400)
    dialog.show()
    qapp.processEvents()
    unselected = next(i for i in dialog.browser.entities._items() if not i.isSelected())
    rect = tree.visualItemRect(unselected)
    image = tree.viewport().grab().toImage()
    for x in (2, rect.width() // 2):  # the branch area and the row
        assert image.pixelColor(x, rect.center().y()) != dark, x
    dialog.close()
