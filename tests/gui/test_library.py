"""The library browser (spec §17.11): smoke tests with a stub job queue (no subprocesses)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QLineEdit

from scheinwerk.core.textures import ImageInfo
from scheinwerk.gui.library.browse import HAS_PREVIEW
from scheinwerk.gui.library.ingest import SKIP, IngestView
from scheinwerk.gui.library.jobs import Job
from scheinwerk.gui.library.window import LibraryBrowser
from scheinwerk.library import detect as d
from scheinwerk.library.root import Library
from tests.conftest import touch
from tests.library.conftest import make_item

MAIN = {"variants": {"main": {"version": 1}}, "created": "2026-01-01T00:00:00+00:00"}


class StubQueue:
    """Records jobs; tests finish them by hand."""

    def __init__(self) -> None:
        self.jobs: list[Job] = []

    def submit(self, args, on_done=None, on_start=None) -> Job:
        job = Job([str(a) for a in args], on_done, on_start)
        self.jobs.append(job)
        return job

    def cancel(self, job: Job) -> bool:
        return False

    def finish(self, job: Job, code: int = 0, out: str = "", err: str = "") -> None:
        if job.on_start:
            job.on_start(job)
        job.code, job.out, job.err = code, out, err
        if job.on_done:
            job.on_done(job)


def thumb(path: Path) -> None:
    image = QImage(64, 32, QImage.Format.Format_RGB32)
    image.fill(QColor(128, 64, 32))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


@pytest.fixture
def stocked(tmp_path: Path) -> Library:
    lib = Library.create(tmp_path / "library")
    rust = make_item(
        lib,
        "texture_set",
        "rust_a1b2c3",
        {1: MAIN},
        name="Rusty Metal",
        categories=["metal/painted"],
        tags=["rust"],
    )
    make_item(
        lib,
        "hdri",
        "sky_d4e5f6",
        {1: {**MAIN, "variants": {"main": {"version": 1}, "no_sun": {"version": 1}}}},
        name="Kloppenheim",
        categories=["sky"],
        tags=["sun"],
    )
    make_item(lib, "model", "draft_g7h8i9", {1: None}, name="Draft")
    thumb(lib.root / "hdri/sky_d4e5f6/v001/thumb_main.jpg")
    assert rust.is_dir()
    return lib


@pytest.fixture
def window(qapp, stocked: Library):
    queue = StubQueue()
    w = LibraryBrowser(stocked, queue, spaces=["ACEScg", "sRGB - Texture"])
    w.show()
    yield w
    w.close()


def grid_names(w: LibraryBrowser) -> list[str]:
    g = w.browse.grid
    return [g.item(i).data(Qt.ItemDataRole.UserRole).id for i in range(g.count())]


# --- browse --------------------------------------------------------------------------------


def test_grid_lists_everything_by_name(window: LibraryBrowser) -> None:
    assert grid_names(window) == ["draft_g7h8i9", "sky_d4e5f6", "rust_a1b2c3"]
    labels = [window.browse.grid.item(i).text() for i in range(3)]
    assert "(incomplete)" in labels[0] and "·2" in labels[1]  # the variant badge


def test_filters(window: LibraryBrowser) -> None:
    window.browse.types.setCurrentIndex(1)  # HDRIs
    assert grid_names(window) == ["sky_d4e5f6"]
    window.browse.types.setCurrentIndex(0)
    window.search.setText("rusty")
    assert grid_names(window) == ["rust_a1b2c3"]
    window.search.clear()
    tree = window.browse.categories
    metal = next(
        tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == "metal"
    )
    metal.setSelected(True)  # a parent category shows its children's items
    assert grid_names(window) == ["rust_a1b2c3"]
    tree.clearSelection()
    window.browse.has_variants.setChecked(True)
    assert grid_names(window) == ["sky_d4e5f6"]


def test_thumbnails_load(window: LibraryBrowser, qapp) -> None:
    for _ in range(5):
        qapp.processEvents()
    g = window.browse.grid
    icons = {
        g.item(i).data(Qt.ItemDataRole.UserRole).id: bool(g.item(i).data(HAS_PREVIEW))
        for i in range(g.count())
    }
    assert icons == {"draft_g7h8i9": False, "sky_d4e5f6": True, "rust_a1b2c3": False}


def test_detail_edits_item_json(window: LibraryBrowser, stocked: Library) -> None:
    window.browse.select("texture_set/rust_a1b2c3")
    panel = window.browse.detail.widget()
    edits = panel.findChildren(QLineEdit)
    name, categories, tags, description = edits[:4]
    description.setText("Peeling paint")
    description.editingFinished.emit()
    tags.setText("rust, worn")
    tags.editingFinished.emit()
    meta = json.loads((stocked.root / "texture_set/rust_a1b2c3/item.json").read_text("utf-8"))
    assert meta["description"] == "Peeling paint" and meta["tags"] == ["rust", "worn"]
    assert name.text() == "Rusty Metal" and categories.text() == "metal/painted"


def test_rebuild_and_drops_go_through_jobs(window: LibraryBrowser, tmp_path: Path) -> None:
    item = next(i for i in window.browse.items if i.id == "sky_d4e5f6")
    window.browse._rebuild(item)
    assert window.queue.jobs[-1].args == ["lib", "rebuild", "sky_d4e5f6"]
    window.browse._dropped(item, [tmp_path / "x.exr"])
    assert window.stack.currentWidget() is window.ingest
    assert window.queue.jobs[-1].args == ["lib", "detect", "--json", str(tmp_path / "x.exr")]


# --- ingest --------------------------------------------------------------------------------


def plan(tmp_path: Path) -> dict:
    folder = tmp_path / "wall"
    for n in ("wall_Color.png", "wall_Normal_DX.png", "wall_Rough.png", "wall_preview.jpg"):
        touch(folder / n)
    probe = lambda p: ImageInfo(64, 64, 3, "uint8")  # noqa: E731
    return d.detect([folder], probe, "sRGB - Texture", "Linear Rec.709 (sRGB)").as_json()


def test_detect_job_fills_the_entries(window: LibraryBrowser, tmp_path: Path) -> None:
    window.ingest_paths([tmp_path / "wall"])
    job = window.queue.jobs[-1]
    assert job.args[:3] == ["lib", "detect", "--json"]
    assert "Detecting" in window.ingest.info.text()
    window.queue.finish(job, out=json.dumps(plan(tmp_path)))
    assert [e.plan["name"] for e in window.ingest.entries] == ["Wall"]
    assert window.ingest.list.item(0).text() == "Wall\ntexture_set   ready"


def test_edit_and_submit_a_plan(window: LibraryBrowser, tmp_path: Path) -> None:
    view: IngestView = window.ingest
    view.add_plans(plan(tmp_path)["entries"])
    entry = view.entries[0]
    panel = view.detail.widget()
    name = panel.findChildren(QLineEdit)[0]
    name.setText("Old Wall")
    name.textEdited.emit("Old Wall")
    preview = next(f for f in entry.plan["skipped"] if f.endswith("wall_preview.jpg"))
    view._set_role(entry, None, {"path": preview, "role": SKIP}, "ao")  # bring a skipped file in
    assert any(f["role"] == "ao" for f in entry.plan["variants"]["main"])
    view.submit(entry)
    job = window.queue.jobs[-1]
    assert job.args[:3] == ["lib", "ingest", "--plan"] and job.args[-1] == "--yes"
    sent = json.loads(Path(job.args[3]).read_text(encoding="utf-8"))
    assert sent["name"] == "Old Wall"
    assert entry.status == "queued"
    window.queue.finish(job, out="texture_set/wall_x1y2z3 v001  Old Wall\n")
    assert entry.status == "done" and entry.item == "texture_set/wall_x1y2z3"


def test_failed_entry_can_be_submitted_again(window: LibraryBrowser, tmp_path: Path) -> None:
    view = window.ingest
    view.add_plans(plan(tmp_path)["entries"])
    entry = view.entries[0]
    view.submit(entry)
    window.queue.finish(window.queue.jobs[-1], code=1, err="sw: error: Wall: hoiiotool failed\n")
    assert entry.status == "failed" and entry.error == "Wall: hoiiotool failed"
    view.submit(entry)
    assert entry.status == "queued"


def test_ingest_all_skips_needs_input_and_done(window: LibraryBrowser, tmp_path: Path) -> None:
    view = window.ingest
    plans = plan(tmp_path)["entries"]
    view.add_plans([plans[0], {**plans[0], "name": "B", "status": "needs_input"}])
    view.ingest_all()
    assert len([j for j in window.queue.jobs if j.args[1] == "ingest"]) == 1


def test_target_from_a_drop_on_an_item(window: LibraryBrowser, tmp_path: Path) -> None:
    view = window.ingest
    view.add_plans(plan(tmp_path)["entries"], target={"item": "rust_a1b2c3", "variant": "winter"})
    assert view.entries[0].plan["target"] == {"item": "rust_a1b2c3", "variant": "winter"}


def test_no_library_offers_set_up(qapp, user_dir) -> None:
    w = LibraryBrowser(queue=StubQueue(), spaces=[])
    assert hasattr(w, "setup_box") and not hasattr(w, "browse")
    w.close()
