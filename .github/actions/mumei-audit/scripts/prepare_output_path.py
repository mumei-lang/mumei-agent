#!/usr/bin/env python3
"""Prepare an audit output path without following checkout-controlled symlinks."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare_output_path.py PATH")
    path = Path(sys.argv[1])
    probe = Path(path.anchor) if path.is_absolute() else Path.cwd()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts[:-1]:
        probe = probe / part
        if probe.is_symlink():
            raise SystemExit(f"refusing symlink output directory component: {probe}")
        if probe.exists() and not probe.is_dir():
            raise SystemExit(f"output directory component is not a directory: {probe}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
