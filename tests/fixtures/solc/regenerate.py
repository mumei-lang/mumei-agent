"""Regenerate the pinned Solidity standard-JSON envelopes in this directory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ENVELOPE_PROFILE = "mumei.solc-standard-json-envelope/v1"
OUTPUT_SELECTION = {"*": {"*": ["metadata"], "": ["ast"]}}
FIXTURE_NAMES = (
    "overloaded",
    "inheritance_override",
    "require_builtin",
    "state_write",
    "compile_error",
    "import_source",
)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: regenerate.py /path/to/solc")
    solc = sys.argv[1]
    fixture_dir = Path(__file__).resolve().parent
    version = subprocess.run(
        [solc, "--version"], capture_output=True, check=True
    ).stdout.decode("utf-8")
    for name in FIXTURE_NAMES:
        source_name = f"{name}.sol"
        source = (fixture_dir / source_name).read_text(encoding="utf-8")
        sources = {source_name: {"content": source}}
        if name == "import_source":
            imported = (fixture_dir / "Imported.sol").read_text(encoding="utf-8")
            sources["Imported.sol"] = {"content": imported}
        standard_input = {
            "language": "Solidity",
            "sources": sources,
            "settings": {"outputSelection": OUTPUT_SELECTION},
        }
        result = subprocess.run(
            [solc, "--standard-json"],
            input=json.dumps(standard_input).encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"solc failed to compile {source_name}")
        output = json.loads(result.stdout.decode("utf-8"))
        envelope = {
            "profile": ENVELOPE_PROFILE,
            "solc_version_output": version,
            "input": standard_input,
            "output": output,
        }
        destination = fixture_dir / f"{name}.envelope.json"
        destination.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"captured {destination.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
