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
    in_table = False
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if line == "| Date | Model | Success Rate | Avg Code Length |":
            in_table = True
            continue
        if not in_table or line == "|------|-------|--------------|-----------------|":
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue

        cells = _split_markdown_row(line)
        if len(cells) != 4:
            continue
        try:
            success_rate = float(cells[2])
            avg_code_length = float(cells[3])
        except ValueError:
            continue
        rows.append(
            BenchmarkRow(
                date=cells[0],
                model=cells[1],
                success_rate=success_rate,
                avg_code_length=avg_code_length,
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

    best = max(
        rows,
        key=lambda row: (
            row.success_rate,
            -row.avg_code_length,
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
