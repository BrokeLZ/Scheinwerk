"""Run every L0 spike and collect the findings into out/<os>/REPORT.md.

    python spike/l0/run_all.py            (any Python 3.11, e.g. `uv run python ...`)
    hython spike/l0/run_all.py            (works too)
    python spike/l0/run_all.py s03 s05    (only some)

Houdini 21 is found automatically; set SW_SPIKE_HFS to its install folder if it isn't.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
import time

from common import HERE, OS, OUT_ROOT, hfs, tool

SCRIPTS = [  # (script, needs hython)
    ("s01_textures.py", False),
    ("s02_karma_tx.py", True),
    ("s03_search_path.py", False),
    ("s04_domelight.py", True),
    ("s05_variants.py", True),
    ("s06_triplanar.py", True),
    ("s07_model_import.py", True),
    ("s08_preview.py", True),
    ("s09_render_space.py", False),
]


def main() -> None:
    only = sys.argv[1:]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Houdini: {hfs()}\nOutput:  {OUT_ROOT}\n")
    runs = []
    for script, needs_hython in SCRIPTS:
        if only and not any(script.startswith(o) for o in only):
            continue
        exe = str(tool("hython")) if needs_hython else sys.executable
        print(f"--- {script} ({'hython' if needs_hython else 'python'})", flush=True)
        t = time.time()
        p = subprocess.run([exe, str(HERE / script)], cwd=HERE, capture_output=True, text=True)
        secs = time.time() - t
        log = OUT_ROOT / f"{script[:-3]}.console.txt"
        log.write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
        md = OUT_ROOT / f"{script[:-3]}.md"
        text = md.read_text(encoding="utf-8") if md.exists() else ""
        ok, fail = len(re.findall(r"\[OK\]", text)), len(re.findall(r"\[FAIL\]", text))
        runs.append((script, p.returncode, ok, fail, secs))
        print(f"    exit {p.returncode}, {ok} OK, {fail} FAIL, {secs:.0f}s", flush=True)
        if p.returncode != 0:
            print("    " + p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "")

    lines = [
        f"# L0 spike report — {OS}",
        "",
        f"- Houdini: `{hfs()}`",
        f"- Python: {platform.python_version()}",
        f"- Machine: {platform.platform()}",
        "",
        "| Script | Exit | OK | FAIL | Seconds |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [f"| {s} | {rc} | {ok} | {fail} | {secs:.0f} |" for s, rc, ok, fail, secs in runs]
    lines.append("")
    for script, _ in SCRIPTS:  # every log there is, also from earlier partial runs
        md = OUT_ROOT / f"{script[:-3]}.md"
        if md.exists():
            lines += ["", md.read_text(encoding="utf-8")]
        elif any(r[0] == script for r in runs):
            lines += ["", f"# {script[:-3]}", "", f"No log written: see {script[:-3]}.console.txt"]
    (OUT_ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport: {OUT_ROOT / 'REPORT.md'}")


if __name__ == "__main__":
    main()
