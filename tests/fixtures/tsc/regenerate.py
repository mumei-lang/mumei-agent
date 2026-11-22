"""Regenerate the pinned TypeScript compiler envelopes in this directory."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE_NAMES = {
    "bom_source": ".ts",
    "block_scope_shadowing": ".ts",
    "builtin_math": ".ts",
    "class_closure": ".ts",
    "export_local": ".ts",
    "function_overloads": ".ts",
    "function_param_call": ".ts",
    "import_source": ".ts",
    "intrinsic_globals": ".ts",
    "mapped_property": ".ts",
    "member_access": ".ts",
    "state_write_operators": ".ts",
    "tsx_fragment": ".tsx",
    "type_error": ".ts",
}


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: regenerate.py /path/to/tools/ts-bindings")
    node = shutil.which("node")
    if node is None:
        raise SystemExit("node is required to regenerate TypeScript fixtures")

    helper = Path(sys.argv[1]).resolve() / "helper.js"
    fixture_dir = Path(__file__).resolve().parent
    for name, extension in FIXTURE_NAMES.items():
        source = fixture_dir / f"{name}{extension}"
        result = subprocess.run(
            [node, str(helper), str(source)],
            capture_output=True,
            check=True,
        )
        destination = fixture_dir / f"{name}.envelope.json"
        destination.write_bytes(result.stdout)
        print(f"captured {destination.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
