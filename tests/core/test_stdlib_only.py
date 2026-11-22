"""Rule 1: importing scheinwerk.core must not pull in any non-stdlib module."""

from __future__ import annotations

import subprocess
import sys

CHECK = """
import importlib, pkgutil, sys
before = set(sys.modules)
import scheinwerk.core as core
for m in pkgutil.iter_modules(core.__path__, "scheinwerk.core."):
    importlib.import_module(m.name)
new = {name.split(".")[0] for name in set(sys.modules) - before}
print("\\n".join(sorted(new - set(sys.stdlib_module_names) - {"scheinwerk"})))
"""


def test_core_imports_only_stdlib() -> None:
    # Fresh interpreter, so pytest's own imports don't count.
    result = subprocess.run(
        [sys.executable, "-I", "-c", CHECK], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"non-stdlib imports: {result.stdout}"
