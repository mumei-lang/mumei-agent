#!/usr/bin/env python3
"""Resolve an output path inside the caller workspace without following unsafe links."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare_workspace_output_path.py WORKSPACE PATH")
    workspace = Path(sys.argv[1]).resolve()
    raw = Path(sys.argv[2])
    candidate = raw if raw.is_absolute() else workspace / raw
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(workspace):
        raise SystemExit(f"output path escapes the caller workspace: {raw}")
    print(resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
