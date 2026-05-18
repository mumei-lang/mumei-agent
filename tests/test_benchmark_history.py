"""Tests for scripts.update_benchmark_history."""
from __future__ import annotations

import json

from scripts.select_benchmark_model import parse_history_rows, select_model
from scripts.update_benchmark_history import update_history


def test_update_history_appends_benchmark_rows(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    history = tmp_path / "BENCHMARK_HISTORY.md"
    benchmark.write_text(
        json.dumps({
            "results": [
                {
                    "model": "qwen3.5:4b",
                    "success_rate": 0.667,
                    "avg_code_length": 1234.56,
                },
                {
                    "model": "model|with-pipe",
                    "success_rate": "0.5",
                    "avg_code_length": "42",
                },
            ]
        }),
        encoding="utf-8",
    )

    assert update_history(benchmark, history, date="2026-05-02") == 2
    text = history.read_text(encoding="utf-8")
    assert "| 2026-05-02 | qwen3.5:4b | 0.667 | 1234.6 |" in text
    assert "| 2026-05-02 | model\\|with-pipe | 0.500 | 42.0 |" in text


def test_update_history_keeps_latest_rows(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    history = tmp_path / "BENCHMARK_HISTORY.md"
    benchmark.write_text(
        json.dumps({
            "results": [
                {
                    "model": "new-model",
                    "success_rate": 1,
                    "avg_code_length": 10,
                }
            ]
        }),
        encoding="utf-8",
    )
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length |",
            "|------|-------|--------------|-----------------|",
            "| 2026-04-30 | old-a | 0.100 | 1.0 |",
            "| 2026-05-01 | old-b | 0.200 | 2.0 |",
        ]) + "\n",
        encoding="utf-8",
    )

    update_history(benchmark, history, date="2026-05-02", max_rows=2)
    text = history.read_text(encoding="utf-8")
    assert "old-a" not in text
    assert "| 2026-05-01 | old-b | 0.200 | 2.0 |" in text
    assert "| 2026-05-02 | new-model | 1.000 | 10.0 |" in text


def test_parse_history_rows_unescapes_pipe_cells(tmp_path):
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length |",
            "|------|-------|--------------|-----------------|",
            "| 2026-05-01 | model\\|with-pipe | 0.750 | 24.0 |",
        ]) + "\n",
        encoding="utf-8",
    )

    rows = parse_history_rows(history)
    assert len(rows) == 1
    assert rows[0].model == "model|with-pipe"
    assert rows[0].success_rate == 0.75
    assert rows[0].avg_code_length == 24.0


def test_select_model_prefers_success_then_shorter_code(tmp_path):
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length |",
            "|------|-------|--------------|-----------------|",
            "| 2026-05-01 | verbose-model | 0.900 | 500.0 |",
            "| 2026-05-02 | concise-model | 0.900 | 100.0 |",
            "| 2026-05-03 | lower-success | 0.800 | 10.0 |",
        ]) + "\n",
        encoding="utf-8",
    )

    assert select_model(history, fallback="fallback") == "concise-model"


def test_select_model_uses_fallback_without_rows(tmp_path):
    assert select_model(tmp_path / "missing.md", fallback="fallback-model") == "fallback-model"
