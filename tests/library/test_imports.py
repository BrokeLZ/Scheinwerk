"""Spec §17.9: library/ imports only the standard library and project-free core modules,
never project, context or entities (not even through another core module)."""

from __future__ import annotations

import subprocess
import sys

CHECK = """
import importlib, pkgutil, sys
before = set(sys.modules)
import scheinwerk.library as library
for m in pkgutil.iter_modules(library.__path__, "scheinwerk.library."):
    importlib.import_module(m.name)
new = set(sys.modules) - before
third_party = {n.split(".")[0] for n in new} - set(sys.stdlib_module_names) - {"scheinwerk"}
project_bound = {"scheinwerk.core." + n for n in ("project", "context", "entities")} & new
print("\\n".join(sorted(third_party | project_bound)))
"""


def test_library_imports_only_stdlib_and_project_free_core() -> None:
    # Fresh interpreter, so pytest's own imports don't count.
    result = subprocess.run(
        [sys.executable, "-I", "-c", CHECK], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"forbidden imports: {result.stdout}"
