"""The Houdini integration inside real Houdini (hython). Slow, so opt-in:

    uv run pytest -m houdini

Uses every Houdini found (or SW_HYTHON=/path/to/hython). Installs the package into a
temporary HOUDINI_PACKAGE_DIR, never into your Houdini preferences.
"""

from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path

import pytest

from scheinwerk.core.fileio import write_json
from scheinwerk.core.install import package_data

REPO = Path(__file__).resolve().parents[2]
PATTERNS = (
    "/Applications/Houdini/Houdini*/Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython",
    "C:/Program Files/Side Effects Software/Houdini */bin/hython.exe",
    "/opt/hfs*/bin/hython",
)


def hythons() -> list[str]:
    if os.environ.get("SW_HYTHON"):
        return [os.environ["SW_HYTHON"]]
    # absolute patterns: Path.glob only takes relative ones
    return sorted(p for pattern in PATTERNS for p in glob.glob(pattern))  # noqa: PTH207


pytestmark = pytest.mark.houdini


@pytest.mark.skipif(not hythons(), reason="no Houdini installed")
@pytest.mark.parametrize(
    "hython", hythons(), ids=lambda p: Path(p).parts[3] if "Applications" in p else p
)
def test_integration_in_houdini(hython: str, tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    packages.mkdir()
    write_json(packages / "scheinwerk.json", package_data(REPO))
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
    env["HOUDINI_PACKAGE_DIR"] = str(packages)
    result = subprocess.run(
        [hython, str(REPO / "tests/houdini/hython_checks.py"), str(tmp_path), str(REPO)],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    assert "ALL OK" in result.stdout, result.stdout[-3000:] + result.stderr[-3000:]
