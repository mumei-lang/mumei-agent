"""Tests for scripts.update_benchmark_history."""
from __future__ import annotations

import json

from scripts.select_benchmark_model import (
    DEFAULT_HISTORY_PATH,
    parse_history_rows,
    select_model,
)
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
                    "avg_time_seconds": 1.25,
                },
                {
                    "model": "model|with-pipe",
                    "success_rate": "0.5",
                    "avg_code_length": "42",
                    "avg_time_seconds": "2",
                },
            ]
        }),
        encoding="utf-8",
    )

    assert update_history(benchmark, history, date="2026-05-02") == 2
    text = history.read_text(encoding="utf-8")
    assert "| 2026-05-02 | qwen3.5:4b | 0.667 | 1234.6 | 1.250 |" in text
    assert "| 2026-05-02 | model\\|with-pipe | 0.500 | 42.0 | 2.000 |" in text


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
                    "avg_time_seconds": 0.5,
                }
            ]
        }),
        encoding="utf-8",
    )
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-04-30 | old-a | 0.100 | 1.0 | 1.000 |",
            "| 2026-05-01 | old-b | 0.200 | 2.0 | 2.000 |",
        ]) + "\n",
        encoding="utf-8",
    )

    update_history(benchmark, history, date="2026-05-02", max_rows=2)
    text = history.read_text(encoding="utf-8")
    assert "old-a" not in text
    assert "| 2026-05-01 | old-b | 0.200 | 2.0 | 2.000 |" in text
    assert "| 2026-05-02 | new-model | 1.000 | 10.0 | 0.500 |" in text


def test_update_history_preserves_other_benchmark_sections(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    history = tmp_path / "BENCHMARK_HISTORY.md"
    benchmark.write_text(
        json.dumps({
            "results": [
                {
                    "model": "new-model",
                    "success_rate": 1,
                    "avg_code_length": 10,
                    "avg_time_seconds": 0.5,
                }
            ]
        }),
        encoding="utf-8",
    )
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "## Recommended model policy",
            "",
            "- Keep this policy note.",
            "",
            "## Generation Benchmark Runs",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-05-01 | old-model | 0.200 | 2.0 | 2.000 |",
            "",
            "## SV-COMP Style Benchmarks",
            "",
            "| Date | Model | Success Rate | Avg Time (ms) | Category |",
            "|------|-------|--------------|---------------|----------|",
            "| 2026-05-01 | svcomp-model | 0.900 | 100 | svcomp |",
        ]) + "\n",
        encoding="utf-8",
    )

    update_history(benchmark, history, date="2026-05-02")
    text = history.read_text(encoding="utf-8")

    assert "- Keep this policy note." in text
    assert "| 2026-05-02 | new-model | 1.000 | 10.0 | 0.500 |" in text
    assert "| 2026-05-01 | svcomp-model | 0.900 | 100 | svcomp |" in text


def test_parse_history_rows_unescapes_pipe_cells(tmp_path):
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-05-01 | model\\|with-pipe | 0.750 | 24.0 | 1.500 |",
        ]) + "\n",
        encoding="utf-8",
    )

    rows = parse_history_rows(history)
    assert len(rows) == 1
    assert rows[0].model == "model|with-pipe"
    assert rows[0].success_rate == 0.75
    assert rows[0].avg_code_length == 24.0
    assert rows[0].avg_time_seconds == 1.5


def test_parse_history_rows_accepts_legacy_four_column_table(tmp_path):
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length |",
            "|------|-------|--------------|-----------------|",
            "| 2026-05-01 | legacy-model | 0.750 | 24.0 |",
        ]) + "\n",
        encoding="utf-8",
    )

    rows = parse_history_rows(history)

    assert rows[0].model == "legacy-model"
    assert rows[0].avg_time_seconds == float("inf")


def test_select_model_prefers_success_then_shorter_code(tmp_path):
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-05-01 | verbose-model | 0.900 | 500.0 | 3.000 |",
            "| 2026-05-02 | concise-model | 0.900 | 100.0 | 1.000 |",
            "| 2026-05-03 | lower-success | 0.800 | 10.0 | 0.100 |",
        ]) + "\n",
        encoding="utf-8",
    )

    assert select_model(history, fallback="fallback") == "concise-model"


def test_select_model_prefers_shorter_code_over_lower_runtime(tmp_path):
    # Isolates the tie-break priority: at equal success rate, the model with
    # shorter generated code must win even when it has a *higher* runtime.
    # Policy order is success_rate -> shorter code -> lower runtime.
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-05-01 | fast-but-verbose | 0.900 | 500.0 | 0.100 |",
            "| 2026-05-02 | concise-but-slow | 0.900 | 100.0 | 5.000 |",
        ]) + "\n",
        encoding="utf-8",
    )

    assert select_model(history, fallback="fallback") == "concise-but-slow"


def test_select_model_breaks_code_tie_by_lower_runtime(tmp_path):
    # When success rate and code length tie, lower runtime wins.
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-05-01 | slow-model | 0.900 | 100.0 | 5.000 |",
            "| 2026-05-02 | fast-model | 0.900 | 100.0 | 1.000 |",
        ]) + "\n",
        encoding="utf-8",
    )

    assert select_model(history, fallback="fallback") == "fast-model"


def test_select_model_ignores_non_generation_sections(tmp_path):
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "## Generation Benchmark Runs",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-05-01 | generation-winner | 0.800 | 100.0 | 1.000 |",
            "",
            "## SV-COMP Style Benchmarks",
            "",
            "| Date | Model | Success Rate | Avg Time (ms) | Category |",
            "|------|-------|--------------|---------------|----------|",
            "| 2026-05-02 | svcomp-winner | 0.990 | 100 | svcomp |",
        ]) + "\n",
        encoding="utf-8",
    )

    assert select_model(history, fallback="fallback") == "generation-winner"


def test_select_model_uses_fallback_without_rows(tmp_path):
    assert select_model(tmp_path / "missing.md", fallback="fallback-model") == "fallback-model"


def test_committed_history_is_consistent_with_documented_winner():
    # The recommended-model policy note in docs/BENCHMARK_HISTORY.md records
    # qwen3.5:4b as the current local winner. Guard against drift between the
    # narrative policy and what select_model actually computes from the
    # committed generation-benchmark rows.
    history_text = DEFAULT_HISTORY_PATH.read_text(encoding="utf-8")
    assert "`qwen3.5:4b`" in history_text
    assert select_model(DEFAULT_HISTORY_PATH, fallback="fallback") == "qwen3.5:4b"
    assert (
        select_model(
            DEFAULT_HISTORY_PATH,
            fallback="qwen3.5:4b",
            profile="ollama-local",
        )
        == "qwen3.5:4b"
    )


def test_select_model_filters_to_ollama_allowlist(tmp_path):
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-05-01 | gpt-4o-mini | 0.990 | 100.0 | 1.000 |",
            "| 2026-05-02 | qwen3.5:4b | 0.750 | 200.0 | 2.000 |",
        ]) + "\n",
        encoding="utf-8",
    )

    assert select_model(
        history,
        fallback="qwen3.5:4b",
        profile="ollama-local",
        ollama_models="qwen3.5:4b",
    ) == "qwen3.5:4b"


def test_select_model_falls_back_without_allowed_ollama_rows(tmp_path):
    history = tmp_path / "BENCHMARK_HISTORY.md"
    history.write_text(
        "\n".join([
            "# LLM Benchmark History",
            "",
            "| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |",
            "|------|-------|--------------|-----------------|-------------:|",
            "| 2026-05-01 | gpt-4o-mini | 0.990 | 100.0 | 1.000 |",
        ]) + "\n",
        encoding="utf-8",
    )

    assert select_model(
        history,
        fallback="qwen3.5:4b",
        profile="ollama-local",
        ollama_models="qwen3.5:4b",
    ) == "qwen3.5:4b"
