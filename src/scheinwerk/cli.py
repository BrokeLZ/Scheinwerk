"""The `sw` command. Commands are added in Phase 2 (spec §11)."""

from __future__ import annotations

import argparse

from scheinwerk import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sw", description="Scheinwerk: file-based VFX pipeline.")
    parser.add_argument("--version", action="version", version=f"sw {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
