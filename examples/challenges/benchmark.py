#!/usr/bin/env python3
"""Benchmark Summary Generator for Zero-Human Challenge results.

Scans completed challenge results directories for ``metrics.json`` files,
aggregates them into a summary table, and generates Markdown output suitable
for pasting into ``ZERO_HUMAN_CHALLENGE.md``.

Usage:
    python -m examples.challenges.benchmark [--results-dir DIR] [--output FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.metrics import Metrics

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# Discovery & loading
# ---------------------------------------------------------------------------


def discover_results(results_dir: Path) -> list[Path]:
    """Return all ``metrics.json`` files under *results_dir*/``*/``."""
    return sorted(results_dir.glob("*/metrics.json"))


def load_challenge_metrics(metrics_path: Path) -> Metrics:
    """Load a :class:`Metrics` instance from a ``metrics.json`` file."""
    return Metrics.from_file(metrics_path)


# ---------------------------------------------------------------------------
# Summary row
# ---------------------------------------------------------------------------


def _challenge_name_from_path(metrics_path: Path) -> str:
    """Extract the challenge name from the parent directory."""
    return metrics_path.parent.name


def build_summary_rows(results_dir: Path) -> list[dict]:
    """Build a list of summary row dicts from all results in *results_dir*.

    Each row contains:
    - ``challenge``: challenge directory name
    - ``status``: ``PASSED`` or ``FAILED``
    - ``attempts``: total attempts
    - ``elapsed``: elapsed seconds (formatted)
    - ``success_rate``: overall success rate as percentage string
    """
    rows: list[dict] = []
    for metrics_path in discover_results(results_dir):
        m = load_challenge_metrics(metrics_path)
        challenge = m.challenge_name or _challenge_name_from_path(metrics_path)
        status = "PASSED" if m.successes > 0 else "FAILED"
        rate = m.overall_success_rate * 100
        rows.append({
            "challenge": challenge,
            "status": status,
            "attempts": m.total_attempts,
            "elapsed": f"{m.elapsed_seconds:.1f}s",
            "success_rate": f"{rate:.0f}%",
        })
    return rows


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------


def generate_markdown_table(rows: list[dict]) -> str:
    """Generate a Markdown table from summary rows.

    Returns an empty-results message when *rows* is empty.
    """
    if not rows:
        return "_No challenge results found._\n"

    lines: list[str] = [
        "| Challenge | Status | Attempts | Elapsed | Success Rate |",
        "|-----------|--------|----------|---------|--------------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['challenge']} "
            f"| {row['status']} "
            f"| {row['attempts']} "
            f"| {row['elapsed']} "
            f"| {row['success_rate']} |"
        )
    lines.append("")  # trailing newline
    return "\n".join(lines)


def generate_summary(results_dir: Path) -> str:
    """Generate the full benchmark summary Markdown."""
    rows = build_summary_rows(results_dir)
    header = "## Benchmark Summary\n\n"
    table = generate_markdown_table(rows)

    if rows:
        total = len(rows)
        passed = sum(1 for r in rows if r["status"] == "PASSED")
        footer = f"\n**Total**: {total} challenges, {passed} passed\n"
    else:
        footer = ""

    return header + table + footer


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate benchmark summary from Zero-Human Challenge results",
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default=None,
        help=(
            "Directory containing challenge result subdirectories "
            f"(default: {DEFAULT_RESULTS_DIR})"
        ),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir) if args.results_dir else DEFAULT_RESULTS_DIR

    if not results_dir.is_dir():
        print(f"Results directory does not exist: {results_dir}", file=sys.stderr)
        sys.exit(1)

    summary = generate_summary(results_dir)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(summary, encoding="utf-8")
        print(f"Summary written to {output_path}")
    else:
        print(summary)


if __name__ == "__main__":
    main()
