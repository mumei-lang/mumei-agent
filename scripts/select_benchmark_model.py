"""Select the highest-performing LLM model from benchmark history."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HISTORY_PATH = Path(__file__).resolve().parents[1] / "docs" / "BENCHMARK_HISTORY.md"
DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_OLLAMA_MODELS = (
    "qwen3.5:4b",
    "qwen3.5:0.8b",
    "qwen2.5-coder:1.5b",
    "qwen2.5-coder:7b",
    "bonsai-1bit-qwen",
)


@dataclass(frozen=True)
class BenchmarkRow:
    date: str
    model: str
    success_rate: float
    avg_code_length: float
    avg_time_seconds: float
    order: int


def _split_markdown_row(line: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line.strip().strip("|"):
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def parse_history_rows(history_path: Path = DEFAULT_HISTORY_PATH) -> list[BenchmarkRow]:
    if not history_path.exists():
        return []

    rows: list[BenchmarkRow] = []
    header: list[str] | None = None
    generation_section_seen = False
    in_generation_section = False
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_generation_section = line == "## Generation Benchmark Runs"
            generation_section_seen = generation_section_seen or in_generation_section
            header = None
            continue
        if generation_section_seen and not in_generation_section:
            continue
        if not line.startswith("|"):
            header = None
            continue

        cells = _split_markdown_row(line)
        normalized = [cell.lower() for cell in cells]
        if {"date", "model", "success rate"}.issubset(set(normalized)):
            header = normalized
            continue
        if header is None or all(set(cell) <= {"-"} for cell in cells):
            continue

        try:
            date_idx = header.index("date")
            model_idx = header.index("model")
            success_idx = header.index("success rate")
        except ValueError:
            continue

        try:
            success_rate = float(cells[success_idx])
        except (IndexError, ValueError):
            continue

        def _optional_float(column_names: tuple[str, ...], default: float) -> float:
            for name in column_names:
                if name not in header:
                    continue
                try:
                    return float(cells[header.index(name)])
                except (IndexError, ValueError):
                    return default
            return default

        avg_code_length = _optional_float(("avg code length",), float("inf"))
        avg_time_seconds = _optional_float(("avg time (s)", "avg time seconds"), float("inf"))
        if "avg time (ms)" in header:
            avg_time_seconds = _optional_float(("avg time (ms)",), float("inf")) / 1000.0

        rows.append(
            BenchmarkRow(
                date=cells[date_idx],
                model=cells[model_idx],
                success_rate=success_rate,
                avg_code_length=avg_code_length,
                avg_time_seconds=avg_time_seconds,
                order=len(rows),
            )
        )
    return rows


def _model_allowlist(models: str | None) -> set[str]:
    if not models:
        return set(DEFAULT_OLLAMA_MODELS)
    return {model.strip() for model in models.split(",") if model.strip()}


def select_model(
    history_path: Path = DEFAULT_HISTORY_PATH,
    *,
    fallback: str = DEFAULT_MODEL,
    profile: str | None = None,
    ollama_models: str | None = None,
) -> str:
    rows = parse_history_rows(history_path)
    if profile == "ollama-local":
        allowed_models = _model_allowlist(ollama_models)
        rows = [row for row in rows if row.model in allowed_models]
    if not rows:
        return fallback

    # Policy: maximize success rate, then prefer shorter generated code,
    # then lower average runtime. Ties fall back to the most recent row
    # (date, then insertion order) so the newest measurement wins.
    best = max(
        rows,
        key=lambda row: (
            row.success_rate,
            -row.avg_code_length,
            -row.avg_time_seconds,
            row.date,
            row.order,
        ),
    )
    return best.model or fallback


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument("--fallback", default=DEFAULT_MODEL)
    parser.add_argument("--profile", choices=("ollama-local", "remote"))
    parser.add_argument(
        "--ollama-models",
        default=",".join(DEFAULT_OLLAMA_MODELS),
        help="Comma-separated models eligible for ollama-local selection.",
    )
    args = parser.parse_args()
    print(
        select_model(
            args.history,
            fallback=args.fallback,
            profile=args.profile,
            ollama_models=args.ollama_models,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
