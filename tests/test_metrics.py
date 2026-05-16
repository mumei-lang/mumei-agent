"""Tests for the new Metrics fields: elapsed_seconds, challenge_name, from_file()."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.metrics import Metrics


class TestMetricsNewFields:
    """Test elapsed_seconds and challenge_name fields."""

    def test_default_values(self) -> None:
        """New fields have correct defaults."""
        m = Metrics()
        assert m.elapsed_seconds == 0.0
        assert m.challenge_name == ""

    def test_set_elapsed_seconds(self) -> None:
        """elapsed_seconds can be set."""
        m = Metrics(elapsed_seconds=42.5)
        assert m.elapsed_seconds == 42.5

    def test_set_challenge_name(self) -> None:
        """challenge_name can be set."""
        m = Metrics(challenge_name="safe_queue")
        assert m.challenge_name == "safe_queue"

    def test_to_dict_includes_new_fields(self) -> None:
        """to_dict() includes elapsed_seconds and challenge_name."""
        m = Metrics(elapsed_seconds=10.3, challenge_name="bounded_queue")
        d = m.to_dict()
        assert d["elapsed_seconds"] == 10.3
        assert d["challenge_name"] == "bounded_queue"

    def test_to_dict_default_new_fields(self) -> None:
        """to_dict() includes defaults for new fields."""
        m = Metrics()
        d = m.to_dict()
        assert "elapsed_seconds" in d
        assert "challenge_name" in d
        assert d["elapsed_seconds"] == 0.0
        assert d["challenge_name"] == ""

    def test_to_json_includes_new_fields(self) -> None:
        """to_json() includes new fields in JSON output."""
        m = Metrics(elapsed_seconds=5.0, challenge_name="payment")
        parsed = json.loads(m.to_json())
        assert parsed["elapsed_seconds"] == 5.0
        assert parsed["challenge_name"] == "payment"


class TestMetricsLlmTokens:
    """Test llm_tokens_used field and record_tokens method."""

    def test_default_llm_tokens(self) -> None:
        """llm_tokens_used defaults to 0."""
        m = Metrics()
        assert m.llm_tokens_used == 0

    def test_record_tokens(self) -> None:
        """record_tokens() accumulates token count."""
        m = Metrics()
        m.record_tokens(100)
        m.record_tokens(50)
        assert m.llm_tokens_used == 150

    def test_to_dict_includes_llm_tokens(self) -> None:
        """to_dict() includes llm_tokens_used."""
        m = Metrics(llm_tokens_used=500)
        d = m.to_dict()
        assert d["llm_tokens_used"] == 500

    def test_to_json_includes_llm_tokens(self) -> None:
        """to_json() includes llm_tokens_used."""
        m = Metrics(llm_tokens_used=250)
        parsed = json.loads(m.to_json())
        assert parsed["llm_tokens_used"] == 250

    def test_from_file_roundtrip_llm_tokens(self, tmp_path: Path) -> None:
        """from_file() preserves llm_tokens_used."""
        m = Metrics(llm_tokens_used=1234)
        path = tmp_path / "metrics.json"
        path.write_text(m.to_json(), encoding="utf-8")
        loaded = Metrics.from_file(path)
        assert loaded.llm_tokens_used == 1234

    def test_from_file_missing_llm_tokens_defaults(self, tmp_path: Path) -> None:
        """from_file() defaults llm_tokens_used to 0 when missing."""
        path = tmp_path / "metrics.json"
        path.write_text("{}", encoding="utf-8")
        loaded = Metrics.from_file(path)
        assert loaded.llm_tokens_used == 0


class TestDensePropertyMetrics:
    """Test dense property compression and verification timing metrics."""

    def test_dense_property_verification_improvement_rate(self) -> None:
        """Dense verification timing records relative improvement."""
        metrics = Metrics()
        metrics.record_dense_property_compression(0.5)
        metrics.record_dense_property_verification_time(10.0, 7.5)
        metrics.record_verification_time(7.5, dense_properties=True)

        data = metrics.to_dict()

        assert data["dense_property_average_compression_ratio"] == 0.5
        assert data["dense_property_verification_improvement_rate"] == 0.25
        assert data["verification_times_seconds"] == [7.5]
        assert data["dense_verification_times_seconds"] == [7.5]

    def test_from_file_roundtrip_dense_property_metrics(self, tmp_path: Path) -> None:
        """from_file() preserves dense property timing fields."""
        metrics = Metrics()
        metrics.record_dense_property_compression(0.25)
        metrics.record_dense_property_verification_time(4.0, 3.0)
        metrics.record_verification_time(3.0, dense_properties=True)
        path = tmp_path / "metrics.json"
        path.write_text(metrics.to_json(), encoding="utf-8")

        loaded = Metrics.from_file(path)

        assert loaded.dense_property_compression_ratios == [0.25]
        assert loaded.dense_property_baseline_verification_seconds == 4.0
        assert loaded.dense_property_verification_seconds == 3.0
        assert loaded.dense_property_verification_improvement_rate == 0.25
        assert loaded.dense_verification_times_seconds == [3.0]


class TestMetricsFromFile:
    """Test Metrics.from_file() classmethod."""

    def test_from_file_basic(self, tmp_path: Path) -> None:
        """from_file() loads basic metrics from JSON."""
        m = Metrics(
            total_attempts=5,
            successes=3,
            elapsed_seconds=15.2,
            challenge_name="safe_arithmetic",
        )
        path = tmp_path / "metrics.json"
        path.write_text(m.to_json(), encoding="utf-8")

        loaded = Metrics.from_file(path)
        assert loaded.total_attempts == 5
        assert loaded.successes == 3
        assert loaded.elapsed_seconds == 15.2
        assert loaded.challenge_name == "safe_arithmetic"

    def test_from_file_with_violation_types(self, tmp_path: Path) -> None:
        """from_file() preserves by_violation_type data."""
        m = Metrics()
        m.record_attempt("precondition_violated")
        m.record_attempt("precondition_violated")
        m.record_success("precondition_violated")
        m.record_attempt("division_by_zero")
        m.elapsed_seconds = 20.0
        m.challenge_name = "test_challenge"

        path = tmp_path / "metrics.json"
        path.write_text(m.to_json(), encoding="utf-8")

        loaded = Metrics.from_file(path)
        assert loaded.total_attempts == 3
        assert loaded.successes == 1
        assert loaded.elapsed_seconds == 20.0
        assert loaded.challenge_name == "test_challenge"
        assert "precondition_violated" in loaded.by_violation_type
        assert loaded.by_violation_type["precondition_violated"].attempts == 2
        assert loaded.by_violation_type["precondition_violated"].successes == 1
        assert "division_by_zero" in loaded.by_violation_type
        assert loaded.by_violation_type["division_by_zero"].attempts == 1

    def test_from_file_rule_based_and_pattern(self, tmp_path: Path) -> None:
        """from_file() preserves rule_based and pattern fields."""
        m = Metrics(
            rule_based_attempts=2,
            rule_based_successes=1,
            pattern_attempts=3,
            pattern_successes=2,
        )
        path = tmp_path / "metrics.json"
        path.write_text(m.to_json(), encoding="utf-8")

        loaded = Metrics.from_file(path)
        assert loaded.rule_based_attempts == 2
        assert loaded.rule_based_successes == 1
        assert loaded.pattern_attempts == 3
        assert loaded.pattern_successes == 2

    def test_from_file_missing_fields_use_defaults(self, tmp_path: Path) -> None:
        """from_file() uses defaults for missing fields."""
        path = tmp_path / "metrics.json"
        path.write_text("{}", encoding="utf-8")

        loaded = Metrics.from_file(path)
        assert loaded.total_attempts == 0
        assert loaded.successes == 0
        assert loaded.elapsed_seconds == 0.0
        assert loaded.challenge_name == ""
        assert loaded.by_violation_type == {}

    def test_from_file_roundtrip(self, tmp_path: Path) -> None:
        """from_file(to_json()) produces an equivalent Metrics instance."""
        original = Metrics(
            total_attempts=10,
            successes=7,
            rule_based_attempts=2,
            rule_based_successes=1,
            pattern_attempts=3,
            pattern_successes=2,
            elapsed_seconds=45.67,
            challenge_name="roundtrip_test",
        )
        original.record_attempt("linearity_violated")
        original.record_success("linearity_violated")

        path = tmp_path / "metrics.json"
        path.write_text(m_json := original.to_json(), encoding="utf-8")

        loaded = Metrics.from_file(path)
        assert loaded.to_dict() == original.to_dict()
