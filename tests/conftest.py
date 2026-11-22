from __future__ import annotations

import json
from pathlib import Path

import pytest

# The example config from spec §8.1.
DEFAULT_CONFIG = {
    "schema": 1,
    "name": "testproject",
    "fps": 24,
    "resolution": [1920, 1080],
    "frame_start": 1001,
    "departments": {
        "asset": {
            "mdl": ["main"],
            "tex": ["main"],
            "lookdev": ["main"],
            "rig": ["main"],
            "fx": ["main"],
        },
        "sequence": {"layout": ["main"], "lgt": ["main"]},
        "shot": {
            "layout": ["main"],
            "anim": ["main"],
            "fx": ["main"],
            "lgt": ["main"],
            "comp": ["main"],
        },
    },
    "usd_layer_order": ["lgt", "fx", "anim", "layout"],
    "ignore": ["backup", "*.blend1", "*.autosave", ".DS_Store", "._*", "Thumbs.db", "@eaDir", "*~"],
    "templates": {},
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An empty project: just the folder and its scheinwerk.json. Returns the root."""
    root = tmp_path / "testproject"
    root.mkdir()
    (root / "scheinwerk.json").write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    return root
