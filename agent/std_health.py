"""Phase 3-A — Proof health metrics for the mumei std library.

Measure the verification health of every ``.mm`` file under a mumei
``std/`` directory and emit a structured JSON / tabular report.

Key metrics
-----------
- ``total_files`` / ``verified_files`` / ``failed_files``
- ``total_atoms`` / ``verified_atoms`` / ``trusted_atoms``
- ``health_score``: 0.0 (nothing verified) → 1.0 (fully verified, no proof holes).
- ``todo_count``: number of TODO / FIXME / XXX / HACK markers in source.

The health score is used by :mod:`agent.proliferate` as a before/after
metric so operators can tell whether a proliferation cycle improved or
regressed std/.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from agent.mumei_client import MumeiClient

logger = logging.getLogger(__name__)

_ATOM_RE = re.compile(r"^\s*(?:trusted\s+|async\s+)?atom\s+(\w+)")
_TRUSTED_ATOM_RE = re.compile(r"^\s*trusted\s+atom\s+(\w+)")
_TODO_MARKER_RE = re.compile(
    r"//.*?\b(TODO|FIXME|XXX|HACK)\b",
    re.IGNORECASE,
)

# TODO penalty per marker — capped so a single noisy file can't drive the
# score below zero.  Total TODO penalty is bounded by ``_MAX_TODO_PENALTY``.
_TODO_PENALTY_PER_MARKER = 0.01
_MAX_TODO_PENALTY = 0.2


def _count_atoms(text: str) -> tuple[int, int]:
    """Return ``(total_atoms, trusted_atoms)`` for *text*."""
    total = 0
    trusted = 0
    for line in text.splitlines():
        if _ATOM_RE.match(line):
            total += 1
            if _TRUSTED_ATOM_RE.match(line):
                trusted += 1
    return total, trusted


def _count_todos(text: str) -> int:
    """Return the number of TODO / FIXME / XXX / HACK markers in *text*."""
    return sum(1 for line in text.splitlines() if _TODO_MARKER_RE.search(line))


def compute_health_score(
    total_atoms: int,
    verified_atoms: int,
    trusted_atoms: int,
    todo_count: int,
) -> float:
    """Compute the 0.0–1.0 std/ health score.

    Formula
    -------
    ``base = (verified_atoms - trusted_atoms) / total_atoms``
    (when ``total_atoms > 0``; otherwise 0.0).

    The base score is then reduced by up to ``_MAX_TODO_PENALTY`` based on
    TODO density, and finally clamped to ``[0.0, 1.0]``.

    This intentionally treats *trusted* atoms as half-verified-at-best:
    they are proofs-on-faith that Phase 2-C / 3 wants to eliminate.
    """
    if total_atoms <= 0:
        return 0.0

    numerator = max(0, verified_atoms - trusted_atoms)
    base = numerator / total_atoms

    todo_penalty = min(_MAX_TODO_PENALTY, todo_count * _TODO_PENALTY_PER_MARKER)
    score = base - todo_penalty

    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def measure_health(
    mumei_client: MumeiClient,
    std_dir: str | Path,
) -> dict[str, Any]:
    """Measure proof health across every ``.mm`` file under *std_dir*.

    Parameters
    ----------
    mumei_client:
        Client used to run ``mumei verify`` on each file.
    std_dir:
        Path to the std directory (e.g. ``mumei_repo/std``).

    Returns
    -------
    Dict with the fields documented in the module docstring.
    """
    std_path = Path(std_dir)
    if not std_path.exists():
        return {
            "total_files": 0,
            "verified_files": 0,
            "failed_files": 0,
            "total_atoms": 0,
            "verified_atoms": 0,
            "trusted_atoms": 0,
            "health_score": 0.0,
            "todo_count": 0,
            "details": [],
            "error": f"std_dir {std_path} does not exist",
        }

    details: list[dict[str, Any]] = []
    total_files = 0
    verified_files = 0
    failed_files = 0
    total_atoms = 0
    verified_atoms = 0
    trusted_atoms = 0
    todo_total = 0

    for mm_file in sorted(std_path.rglob("*.mm")):
        total_files += 1
        try:
            text = mm_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read %s: %s", mm_file, exc)
            failed_files += 1
            details.append(
                {
                    "file": str(mm_file.relative_to(std_path.parent)).replace("\\", "/"),
                    "verified": False,
                    "atoms": 0,
                    "trusted_atoms": 0,
                    "todos": 0,
                    "error": str(exc),
                }
            )
            continue

        atoms, trusted = _count_atoms(text)
        todos = _count_todos(text)
        total_atoms += atoms
        trusted_atoms += trusted
        todo_total += todos

        try:
            verify_result = mumei_client.verify(str(mm_file))
            verified = bool(verify_result.get("success", False))
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("verify failed for %s: %s", mm_file, exc)
            verified = False

        if verified:
            verified_files += 1
            # When a file verifies, count all of its atoms as verified
            # (trusted atoms still subtract separately).
            verified_atoms += atoms
        else:
            failed_files += 1

        details.append(
            {
                "file": str(mm_file.relative_to(std_path.parent)).replace("\\", "/"),
                "verified": verified,
                "atoms": atoms,
                "trusted_atoms": trusted,
                "todos": todos,
            }
        )

    health_score = compute_health_score(
        total_atoms=total_atoms,
        verified_atoms=verified_atoms,
        trusted_atoms=trusted_atoms,
        todo_count=todo_total,
    )

    return {
        "total_files": total_files,
        "verified_files": verified_files,
        "failed_files": failed_files,
        "total_atoms": total_atoms,
        "verified_atoms": verified_atoms,
        "trusted_atoms": trusted_atoms,
        "health_score": health_score,
        "todo_count": todo_total,
        "details": details,
    }


def _format_table(report: dict[str, Any]) -> str:
    """Render *report* as a human-readable table."""
    lines = [
        "std/ Proof Health Report",
        "========================",
        f"files:   {report['verified_files']}/{report['total_files']} verified "
        f"({report['failed_files']} failed)",
        f"atoms:   {report['verified_atoms']}/{report['total_atoms']} verified "
        f"({report['trusted_atoms']} trusted)",
        f"TODO:    {report['todo_count']} marker(s)",
        f"score:   {report['health_score']:.3f}",
        "",
        f"{'file':<40} {'verified':<10} {'atoms':>6} {'trusted':>8} {'todos':>6}",
        "-" * 72,
    ]
    for d in report["details"]:
        lines.append(
            f"{d['file']:<40} "
            f"{'yes' if d['verified'] else 'no':<10} "
            f"{d['atoms']:>6} {d['trusted_atoms']:>8} {d['todos']:>6}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser(parser: argparse.ArgumentParser) -> None:
    """Add health-specific arguments to *parser*."""
    parser.add_argument(
        "--mumei-repo",
        required=True,
        help="Path to the mumei repository (must contain std/)",
    )
    parser.add_argument(
        "--mumei-bin",
        default=None,
        help="Path to the mumei binary (default: MUMEI_BIN env or 'mumei')",
    )
    parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format (default: json)",
    )


def main(args: argparse.Namespace) -> None:
    """Entry point for the health subcommand."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Resolve the mumei binary.  AgentConfig is used only for its
    # mumei_bin default (MUMEI_BIN env) — no LLM API key is needed.
    from agent.config import AgentConfig

    config = AgentConfig()
    effective_mumei_bin = args.mumei_bin or config.mumei_bin
    client = MumeiClient(effective_mumei_bin)

    std_dir = Path(args.mumei_repo) / "std"
    report = measure_health(client, std_dir)

    if args.format == "table":
        print(_format_table(report))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    # Exit non-zero if any files failed (useful for CI gating).
    if report.get("failed_files", 0) > 0 or report.get("error"):
        sys.exit(2)
