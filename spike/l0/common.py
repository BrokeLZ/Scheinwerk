"""Shared helpers for the L0 spike scripts (spec §17.12). Throwaway code, not part of Scheinwerk.

Every script runs on its own and writes into spike/l0/out/<os>/<script>/, plus a
<script>.md log of what it found. Scripts that need `pxr`/`hou`/OpenImageIO run in hython;
the others run in any Python 3.11.

Houdini is found through $SW_SPIKE_HFS, then $HFS (set inside hython), then the default
install folders (newest 21.0.*).
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OS = {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), platform.system().lower())
OUT_ROOT = HERE / "out" / OS
EXE = ".exe" if OS == "windows" else ""


def _candidates() -> list[Path]:
    if OS == "macos":
        apps = sorted(Path("/Applications/Houdini").glob("Houdini21.0.*"))
        return [a / "Frameworks/Houdini.framework/Versions/Current/Resources" for a in apps]
    if OS == "windows":
        base = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Side Effects Software"
        return sorted(base.glob("Houdini 21.0.*"))
    return sorted(Path("/opt").glob("hfs21.0*"))


def hfs() -> Path:
    for key in ("SW_SPIKE_HFS", "HFS"):
        if os.environ.get(key):
            return Path(os.environ[key])
    found = [c for c in _candidates() if (c / "bin" / f"hython{EXE}").exists()]
    if not found:
        sys.exit("Houdini 21 not found: set SW_SPIKE_HFS to the Houdini install folder ($HFS)")
    return found[-1]


def tool(name: str) -> Path:
    return hfs() / "bin" / f"{name}{EXE}"


class Log:
    """Collects findings; prints them and writes <out>/<name>.md when closed."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.dir = OUT_ROOT / name
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.lines: list[str] = [f"# {name} ({OS}, {time.strftime('%Y-%m-%d %H:%M')})", ""]
        self.results: dict[str, object] = {}

    def __call__(self, text: str = "") -> None:
        print(text, flush=True)
        self.lines.append(text)

    def check(self, key: str, ok: bool, detail: object = "") -> bool:
        self(f"- [{'OK' if ok else 'FAIL'}] {key}: {detail}")
        self.results[key] = {"ok": bool(ok), "detail": str(detail)}
        return ok

    def note(self, key: str, value: object) -> None:
        self(f"- {key}: {value}")
        self.results[key] = value if isinstance(value, (int, float, bool)) else str(value)

    def block(self, title: str, text: str) -> None:
        self(f"\n<details><summary>{title}</summary>\n\n```text\n{text.strip()}\n```\n</details>\n")

    def close(self) -> None:
        (OUT_ROOT / f"{self.name}.md").write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        (OUT_ROOT / f"{self.name}.json").write_text(
            json.dumps(self.results, indent=2) + "\n", encoding="utf-8"
        )


def run(
    args: list[object],
    log: Log | None = None,
    env: dict | None = None,
    cwd=None,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """Run a tool, never raise; logs the command line and failures."""
    args = [str(a) for a in args]
    full_env = None
    if env is not None:
        full_env = dict(os.environ)
        full_env.update(env)
    t = time.time()
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, env=full_env, cwd=cwd, timeout=timeout
        )
    except Exception as e:  # noqa: BLE001
        p = subprocess.CompletedProcess(args, 1, "", repr(e))
    p.seconds = round(time.time() - t, 2)  # type: ignore[attr-defined]
    if log is not None and p.returncode != 0:
        log.block(
            f"exit {p.returncode}: {Path(args[0]).name} {' '.join(args[1:])[:200]}",
            (p.stdout + "\n" + p.stderr)[-3000:],
        )
    return p


def oiio(args: list[object], log: Log | None = None) -> subprocess.CompletedProcess:
    return run([tool("hoiiotool"), *args], log)


def stats(path: Path) -> dict[str, list[float]]:
    """Per-channel Min/Max/Avg of an image's top level, via hoiiotool --stats."""
    p = oiio(["--stats", path])
    out: dict[str, list[float]] = {}
    for key in ("Min", "Max", "Avg"):
        m = re.search(rf"^\s*Stats {key}:\s*(.+)$", p.stdout, re.M)
        if m:
            values, _, scale = m.group(1).partition("(of ")
            div = float(scale.rstrip(") ")) if scale else 1.0
            out[key.lower()] = [
                float(v) / div for v in re.findall(r"-?[\d.]+(?:e[-+]?\d+)?|-?inf|nan", values)
            ]
    return out


def pixel(path: Path, x: int, y: int) -> list[float]:
    """One pixel's values (0..1 for integer images), via --cut + --stats."""
    tmp = path.with_name(f"_px_{path.stem}_{x}_{y}.exr")
    oiio([path, "--cut", f"1x1+{x}+{y}", "-d", "float", "-o", tmp])
    return stats(tmp).get("avg", [])


def info(path: Path) -> str:
    out = oiio(["--info", "-v", "-a", path]).stdout
    return "\n".join(line for line in out.splitlines() if not line.startswith("Reading "))


def close(a: list[float], b: list[float], tol: float = 0.01) -> bool:
    return len(a) >= len(b) and all(abs(x - y) <= tol for x, y in zip(a, b, strict=False))


def husk(
    usd: Path,
    out: Path,
    log: Log,
    engine: str = "cpu",
    res=(64, 64),
    extra=(),
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    renderer = {"cpu": "BRAY_HdKarma", "xpu": "BRAY_HdKarmaXPU"}[engine]
    p = run(
        [
            tool("husk"),
            "-R",
            renderer,
            "-r",
            res[0],
            res[1],
            "-o",
            out,
            "--make-output-path",
            *extra,
            usd,
        ],
        log,
        env=env,
    )
    return p


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
