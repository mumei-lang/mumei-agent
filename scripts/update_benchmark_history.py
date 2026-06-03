"""Append LLM benchmark summaries to docs/BENCHMARK_HISTORY.md."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_BENCHMARK_PATH = Path("/tmp/proliferate/benchmark.json")
DEFAULT_HISTORY_PATH = Path(__file__).resolve().parents[1] / "docs" / "BENCHMARK_HISTORY.md"
DOCUMENT_HEADER = [
    "# LLM Benchmark History",
    "",
    "Time-series summary of proliferate LLM benchmark runs. The table is kept to the latest 50 rows.",
    "",
]
GENERATION_SECTION_HEADER = [
    "## Generation Benchmark Runs",
    "",
    "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
    "|------|-------|--------------|-----------------|-------------:|",
]
MAX_ROWS = 50


def _load_results(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results", []) if isinstance(data, dict) else []
    return [entry for entry in results if isinstance(entry, dict)]


def _format_rate(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "0.000"


def _format_length(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "0.0"


def _format_seconds(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "0.000"


def _escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _table_rows(history_path: Path) -> list[str]:
    if not history_path.exists():
        return []
    rows: list[str] = []
    in_table = False
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if line in {
            "| Date | Model | Success Rate | Avg Code Length |",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
        }:
            in_table = True
            continue
        if in_table and line.startswith("|------|-------|--------------|"):
            continue
        if in_table:
            if line.startswith("|"):
                if line.count("|") == 5:
                    rows.append(line[:-1].rstrip() + " | 0.000 |")
                else:
                    rows.append(line)
            elif rows:
                break
    return rows


def update_history(
    benchmark_path: Path = DEFAULT_BENCHMARK_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    *,
    date: str | None = None,
    max_rows: int = MAX_ROWS,
) -> int:
    results = _load_results(benchmark_path)
    run_date = date or datetime.now(UTC).date().isoformat()
    new_rows = [
        (
            f"| {run_date} | {_escape_cell(entry.get('model', 'unknown'))} | "
            f"{_format_rate(entry.get('success_rate'))} | "
            f"{_format_length(entry.get('avg_code_length'))} | "
            f"{_format_seconds(entry.get('avg_time_seconds'))} |"
        )
        for entry in results
    ]

    rows = (_table_rows(history_path) + new_rows)[-max_rows:]
    history_path.parent.mkdir(parents=True, exist_ok=True)
    generation_section = GENERATION_SECTION_HEADER + rows

    if not history_path.exists():
        lines = DOCUMENT_HEADER + generation_section
    else:
        existing = history_path.read_text(encoding="utf-8").splitlines()
        try:
            start = existing.index("## Generation Benchmark Runs")
        except ValueError:
            legacy_start = next(
                (
                    idx
                    for idx, line in enumerate(existing)
                    if line
                    in {
                        "| Date | Model | Success Rate | Avg Code Length |",
                        "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
                    }
                ),
                None,
            )
            if legacy_start is not None:
                section_start = legacy_start
                while section_start > 0 and existing[section_start - 1] == "":
                    section_start -= 1
                section_end = next(
                    (
                        idx
                        for idx in range(legacy_start + 1, len(existing))
                        if existing[idx].startswith("## ")
                    ),
                    len(existing),
                )
                suffix = existing[section_end:]
                lines = (
                    existing[:section_start]
                    + generation_section
                    + ([""] if suffix else [])
                    + suffix
                )
            else:
                insert_at = next(
                    (idx for idx, line in enumerate(existing) if line.startswith("## ")),
                    len(existing),
                )
                prefix = existing[:insert_at]
                suffix = existing[insert_at:]
                if prefix and prefix[-1] != "":
                    prefix.append("")
                lines = prefix + generation_section + ([""] if suffix else []) + suffix
        else:
            end = next(
                (
                    idx
                    for idx in range(start + 1, len(existing))
                    if existing[idx].startswith("## ")
                ),
                len(existing),
            )
            suffix = existing[end:]
            lines = (
                existing[:start]
                + generation_section
                + ([""] if suffix else [])
                + suffix
            )

    history_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return len(new_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument("--date")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS)
    args = parser.parse_args()

    appended = update_history(
        args.benchmark,
        args.history,
        date=args.date,
        max_rows=args.max_rows,
    )
    print(f"appended {appended} benchmark history row(s) to {args.history}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
