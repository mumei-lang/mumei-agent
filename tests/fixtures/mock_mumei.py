#!/usr/bin/env python3
"""Mock mumei binary for integration testing.

Mimics ``mumei verify --json [--report-dir DIR] <source_path>`` and
``mumei check <source_path>`` behaviour by inspecting the source file
content and returning pre-defined JSON reports.

Usage (as a drop-in replacement for the real ``mumei`` binary):

    python tests/fixtures/mock_mumei.py verify --json source.mm
    python tests/fixtures/mock_mumei.py check source.mm

The mock recognises "fixed" source patterns and returns success on the
second verification round so that the integration test can exercise the
full heal loop.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPORTS_DIR = Path(__file__).parent / "reports"

# ---------------------------------------------------------------------------
# Pattern detection helpers
# ---------------------------------------------------------------------------

# Markers that indicate a source file has been "fixed" by the LLM.
_FIXED_MARKERS: list[str] = [
    "requires: b != 0",
    "requires: x > 0",
    "requires: x >= 1",
    "ensures: result >= 0",
    "clone(x)",
    "requires: x >= 0 && x <= 10",
    "requires: x >= 0 && x < 5",
]


def _is_fixed(source: str) -> bool:
    """Return True if the source contains known 'fixed' markers.

    This checks generic markers first, then applies violation-specific
    heuristics for effect/temporal fixes that need more context.

    .. warning::
        These heuristics are tightly coupled to the current fixture files.
        When adding new ``.mm`` fixtures, verify that the markers and
        structural checks below still produce the correct results.
    """
    # Generic markers — any of these means the source is fixed.
    if any(marker in source for marker in _FIXED_MARKERS):
        return True

    # Effect propagation fix: main_handler gains the missing FileWrite effect.
    if "main_handler" in source and "effects: [Log, FileWrite]" in source:
        # Count how many atoms declare [Log, FileWrite] — in the fixed version
        # both write_log AND main_handler have it.
        count = source.count("effects: [Log, FileWrite]")
        if count >= 2:
            return True

    # Effect mismatch fix: write_log gains FileWrite in its own effects.
    # But only if there is no main_handler (to avoid conflict with propagation).
    if (
        "main_handler" not in source
        and "effects: [Log, FileWrite]" in source
        and "FileWrite.write" in source
    ):
        return True

    # Temporal effect fix: the *last* write appears BEFORE the *last* close
    # (correct ordering).  Using rfind instead of index so that fixtures with
    # multiple FileWrite.write / FileWrite.close pairs are handled correctly.
    if "FileWrite.write" in source and "FileWrite.close" in source:
        write_pos = source.rfind("FileWrite.write")
        close_pos = source.rfind("FileWrite.close")
        if write_pos < close_pos:
            return True

    return False


def _detect_violation_type(source: str) -> str | None:
    """Detect which violation type a fixture source represents.

    Detection uses two complementary strategies for each type:

    1. **Comment-based** — match human-readable keywords in the (lowered)
       source (e.g. ``"effect propagation"``).  This is the primary path and
       works as long as fixture files keep the ``// Fixture: …`` header.
    2. **Structural** — fall back to code-level heuristics when comments are
       absent or ambiguous.

    Order matters: more specific checks come first so that, for example,
    ``effect_propagation`` is detected before the more general
    ``effect_mismatch``.
    """
    lower = source.lower()
    # Order matters: more specific checks first.
    if "effect propagation" in lower or (
        "effects: [Log]" in source
        and "write_log" in source
        and "main_handler" in source
    ):
        return "effect_propagation"
    if "effect mismatch" in lower or (
        "effects: [Log]" in source and "FileWrite.write" in source
    ):
        return "effect_mismatch"
    if "temporal" in lower or (
        "FileWrite.close" in source and "FileWrite.write" in source
    ):
        return "temporal_effect_violated"
    if "linearity" in lower or ("let a = x" in source and "let b = x" in source):
        return "linearity_violated"
    if "invariant" in lower or ("x > 10" in source and "x < 5" in source):
        return "invariant_violated"
    if "postcondition" in lower or (
        "ensures: result > 0" in source and "body: x;" in source
    ):
        return "postcondition_violated"
    # precondition must be checked BEFORE division_by_zero because
    # precondition_violated.mm contains the phrase "division by zero" in a
    # comment.  The structural heuristic (requires: true + a / b) is unique to
    # the precondition fixture.
    if "precondition" in lower or (
        "requires: true" in source and "a / b" in source
    ):
        return "precondition_violated"
    if "division by zero" in lower or (
        "a / b" in source and "requires:" not in source
    ):
        return "division_by_zero"
    return None


def _load_report(violation_type: str) -> dict:
    """Load the canned report JSON for *violation_type*."""
    report_file = REPORTS_DIR / f"{violation_type}.json"
    if report_file.exists():
        return json.loads(report_file.read_text())
    # Fallback: minimal failure report
    return {
        "status": "failed",
        "failure_type": violation_type,
        "atom": "unknown",
    }


def _success_report() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------

def _handle_verify(args: list[str]) -> int:
    """Handle ``verify --json [--report-dir DIR] <source_path>``."""
    source_path: str | None = None
    report_dir: str | None = None
    json_mode = False
    i = 0
    while i < len(args):
        if args[i] == "--json":
            json_mode = True
        elif args[i] == "--report-dir":
            i += 1
            if i < len(args):
                report_dir = args[i]
        else:
            source_path = args[i]
        i += 1

    if source_path is None:
        print("mock_mumei: error: no source file specified", file=sys.stderr)
        return 2

    path = Path(source_path)
    if not path.exists():
        print(f"mock_mumei: error: file not found: {source_path}", file=sys.stderr)
        return 2

    source = path.read_text()

    # First, detect if the source matches a known violation pattern.
    vtype = _detect_violation_type(source)

    # If no violation detected, or the source looks "fixed", return success.
    if vtype is None or _is_fixed(source):
        report = _success_report()
        if json_mode:
            print(json.dumps(report))
        if report_dir:
            Path(report_dir).mkdir(parents=True, exist_ok=True)
            (Path(report_dir) / "report.json").write_text(json.dumps(report))
        return 0

    report = _load_report(vtype)
    if json_mode:
        print(json.dumps(report))
    if report_dir:
        Path(report_dir).mkdir(parents=True, exist_ok=True)
        (Path(report_dir) / "report.json").write_text(json.dumps(report))
    return 1


def _handle_check(args: list[str]) -> int:
    """Handle ``check <source_path>`` — always succeeds if the file exists."""
    source_path = args[0] if args else None
    if source_path is None:
        print("mock_mumei: error: no source file specified", file=sys.stderr)
        return 2
    if not Path(source_path).exists():
        print(f"mock_mumei: error: file not found: {source_path}", file=sys.stderr)
        return 2
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("mock_mumei: error: no subcommand", file=sys.stderr)
        return 2

    subcommand = args[0]
    rest = args[1:]

    if subcommand == "verify":
        return _handle_verify(rest)
    elif subcommand == "check":
        return _handle_check(rest)
    else:
        print(f"mock_mumei: error: unknown subcommand: {subcommand}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
