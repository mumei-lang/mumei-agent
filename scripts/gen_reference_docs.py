#!/usr/bin/env python3
"""Generate or check the CLI and environment reference documents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.cli_reference import sync_reference_docs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated references are stale")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "docs",
        help="directory containing the reference files (default: docs)",
    )
    args = parser.parse_args()
    mismatches = sync_reference_docs(args.output_dir, check=args.check)
    if mismatches:
        print(
            "Generated reference documents are stale: "
            + ", ".join(mismatches)
            + ". Regenerate with `python scripts/gen_reference_docs.py`.",
            file=sys.stderr,
        )
        return 1
    if not args.check:
        print(f"Generated reference documents in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
