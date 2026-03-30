"""Tests for the benchmark summary generator.

Validates discovery of metrics.json files, Markdown table generation,
and handling of empty results directories.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from examples.challenges.benchmark import (
    build_summary_rows,
    discover_results,
    generate_markdown_table,
    generate_summary,
    load_challenge_metrics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_metrics(results_dir: Path, name: str, data: dict) -> Path:
    """Write a metrics.json file under ``results_dir/name/``."""
    challenge_dir = results_dir / name
    challenge_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = challenge_dir / "metrics.json"
    metrics_path.write_text(json.dumps(data), encoding="utf-8")
    return metrics_path


SAMPLE_METRICS_PASSED = {
    "total_attempts": 3,
    "successes": 1,
    "rule_based_attempts": 0,
    "rule_based_successes": 0,
    "pattern_attempts": 0,
    "pattern_successes": 0,
    "elapsed_seconds": 12.5,
    "challenge_name": "safe_queue",
    "by_violation_type": {
        "generation": {"attempts": 3, "successes": 1},
    },
}

SAMPLE_METRICS_FAILED = {
    "total_attempts": 5,
    "successes": 0,
    "rule_based_attempts": 0,
    "rule_based_successes": 0,
    "pattern_attempts": 0,
    "pattern_successes": 0,
    "elapsed_seconds": 30.0,
    "challenge_name": "verified_json_validator",
    "by_violation_type": {
        "generation": {"attempts": 5, "successes": 0},
    },
}


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


class TestDiscoverResults:
    """Test discovery of metrics.json files."""

    def test_discover_finds_metrics(self, tmp_path: Path) -> None:
        """discover_results() finds metrics.json in subdirectories."""
        _write_metrics(tmp_path, "challenge_a", SAMPLE_METRICS_PASSED)
        _write_metrics(tmp_path, "challenge_b", SAMPLE_METRICS_FAILED)
        found = discover_results(tmp_path)
        assert len(found) == 2
        assert all(p.name == "metrics.json" for p in found)

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        """discover_results() returns empty list for empty directory."""
        found = discover_results(tmp_path)
        assert found == []

    def test_discover_ignores_non_matching(self, tmp_path: Path) -> None:
        """discover_results() ignores files not named metrics.json."""
        (tmp_path / "other.json").write_text("{}")
        found = discover_results(tmp_path)
        assert found == []


# ---------------------------------------------------------------------------
# Loading tests
# ---------------------------------------------------------------------------


class TestLoadChallengeMetrics:
    """Test loading Metrics from metrics.json files."""

    def test_load_metrics(self, tmp_path: Path) -> None:
        """load_challenge_metrics() correctly loads a metrics file."""
        path = _write_metrics(tmp_path, "test_challenge", SAMPLE_METRICS_PASSED)
        m = load_challenge_metrics(path)
        assert m.total_attempts == 3
        assert m.successes == 1
        assert m.elapsed_seconds == 12.5
        assert m.challenge_name == "safe_queue"

    def test_load_metrics_preserves_violation_types(self, tmp_path: Path) -> None:
        """load_challenge_metrics() preserves by_violation_type data."""
        path = _write_metrics(tmp_path, "test_challenge", SAMPLE_METRICS_PASSED)
        m = load_challenge_metrics(path)
        assert "generation" in m.by_violation_type
        assert m.by_violation_type["generation"].attempts == 3
        assert m.by_violation_type["generation"].successes == 1


# ---------------------------------------------------------------------------
# Summary row tests
# ---------------------------------------------------------------------------


class TestBuildSummaryRows:
    """Test summary row generation."""

    def test_builds_rows_from_results(self, tmp_path: Path) -> None:
        """build_summary_rows() generates correct rows."""
        _write_metrics(tmp_path, "safe_queue", SAMPLE_METRICS_PASSED)
        _write_metrics(tmp_path, "verified_json_validator", SAMPLE_METRICS_FAILED)
        rows = build_summary_rows(tmp_path)
        assert len(rows) == 2

        # Rows are sorted by directory name
        assert rows[0]["challenge"] == "safe_queue"
        assert rows[0]["status"] == "PASSED"
        assert rows[0]["attempts"] == 3
        assert rows[0]["elapsed"] == "12.5s"

        assert rows[1]["challenge"] == "verified_json_validator"
        assert rows[1]["status"] == "FAILED"
        assert rows[1]["attempts"] == 5

    def test_empty_results_dir(self, tmp_path: Path) -> None:
        """build_summary_rows() returns empty list for empty directory."""
        rows = build_summary_rows(tmp_path)
        assert rows == []

    def test_fallback_challenge_name_from_path(self, tmp_path: Path) -> None:
        """When challenge_name is empty, falls back to directory name."""
        data = {**SAMPLE_METRICS_PASSED, "challenge_name": ""}
        _write_metrics(tmp_path, "my_challenge", data)
        rows = build_summary_rows(tmp_path)
        assert len(rows) == 1
        assert rows[0]["challenge"] == "my_challenge"


# ---------------------------------------------------------------------------
# Markdown table tests
# ---------------------------------------------------------------------------


class TestGenerateMarkdownTable:
    """Test Markdown table generation."""

    def test_generates_table_with_rows(self) -> None:
        """generate_markdown_table() produces a properly formatted table."""
        rows = [
            {
                "challenge": "safe_queue",
                "status": "PASSED",
                "attempts": 3,
                "elapsed": "12.5s",
                "success_rate": "33%",
            },
            {
                "challenge": "verified_json_validator",
                "status": "FAILED",
                "attempts": 5,
                "elapsed": "30.0s",
                "success_rate": "0%",
            },
        ]
        table = generate_markdown_table(rows)
        assert "| Challenge |" in table
        assert "|-----------|" in table
        assert "safe_queue" in table
        assert "PASSED" in table
        assert "verified_json_validator" in table
        assert "FAILED" in table

    def test_empty_rows_message(self) -> None:
        """generate_markdown_table() returns message for empty rows."""
        table = generate_markdown_table([])
        assert "No challenge results found" in table

    def test_table_has_header_and_separator(self) -> None:
        """Table includes header row and separator."""
        rows = [
            {
                "challenge": "test",
                "status": "PASSED",
                "attempts": 1,
                "elapsed": "1.0s",
                "success_rate": "100%",
            },
        ]
        table = generate_markdown_table(rows)
        lines = table.strip().split("\n")
        assert len(lines) >= 3  # header + separator + at least 1 data row
        assert lines[0].startswith("| Challenge")
        assert lines[1].startswith("|---")


# ---------------------------------------------------------------------------
# Full summary tests
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    """Test full summary generation."""

    def test_summary_with_results(self, tmp_path: Path) -> None:
        """generate_summary() produces complete Markdown summary."""
        _write_metrics(tmp_path, "safe_queue", SAMPLE_METRICS_PASSED)
        _write_metrics(tmp_path, "verified_json_validator", SAMPLE_METRICS_FAILED)
        summary = generate_summary(tmp_path)
        assert "## Benchmark Summary" in summary
        assert "safe_queue" in summary
        assert "verified_json_validator" in summary
        assert "**Total**: 2 challenges, 1 passed" in summary

    def test_summary_empty_results(self, tmp_path: Path) -> None:
        """generate_summary() handles empty results directory."""
        summary = generate_summary(tmp_path)
        assert "## Benchmark Summary" in summary
        assert "No challenge results found" in summary
