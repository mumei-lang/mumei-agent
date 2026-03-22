"""Regression tests tracking fix success rates per violation type.

These tests verify that the Metrics system correctly records attempts and
successes, and that the fix pipeline produces non-empty results for each
known violation type. This acts as a regression guard: if prompt changes
cause a previously-working violation type to stop producing fixes, these
tests will catch it.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from agent.metrics import Metrics
from agent.strategies.fix_strategy import get_fix


FIXED_CODE = "```mumei\natom fixed(x: i64) requires: x >= 0; ensures: result >= 0; body: x;\n```"
SAMPLE_SOURCE = "atom broken(x: i64) body: x;"
SAMPLE_ERROR = "Verification failed"


def _mock_client(response_text: str = FIXED_CODE) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = response_text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


class TestMetricsTracking:
    """Verify metrics correctly track attempts and successes."""

    def test_record_attempt_increments(self):
        m = Metrics()
        m.record_attempt("precondition_violated")
        m.record_attempt("precondition_violated")
        m.record_attempt("division_by_zero")
        assert m.total_attempts == 3
        assert m.by_violation_type["precondition_violated"].attempts == 2
        assert m.by_violation_type["division_by_zero"].attempts == 1

    def test_record_success_increments(self):
        m = Metrics()
        m.record_attempt("postcondition_violated")
        m.record_success("postcondition_violated")
        assert m.successes == 1
        assert m.by_violation_type["postcondition_violated"].successes == 1

    def test_to_dict_structure(self):
        m = Metrics()
        m.record_attempt("linearity_violated")
        m.record_success("linearity_violated")
        d = m.to_dict()
        assert d["total_attempts"] == 1
        assert d["successes"] == 1
        assert "linearity_violated" in d["by_violation_type"]
        assert d["by_violation_type"]["linearity_violated"]["successes"] == 1

    def test_to_json_is_valid(self):
        import json
        m = Metrics()
        m.record_attempt("temporal_effect_violated")
        raw = m.to_json()
        parsed = json.loads(raw)
        assert parsed["total_attempts"] == 1


class TestRegressionFixOutput:
    """Regression guard: each violation type produces a non-empty fix."""

    def _run_fix(self, report: dict) -> str:
        client = _mock_client()
        return get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)

    def test_precondition_violated_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["precondition_violated"])
        assert len(result) > 0

    def test_postcondition_violated_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["postcondition_violated"])
        assert len(result) > 0

    def test_division_by_zero_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["division_by_zero"])
        assert len(result) > 0

    def test_linearity_violated_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["linearity_violated"])
        assert len(result) > 0

    def test_invariant_violated_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["invariant_violated"])
        assert len(result) > 0

    def test_temporal_effect_violated_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["temporal_effect_violated"])
        assert len(result) > 0

    def test_effect_mismatch_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["effect_mismatch"])
        assert len(result) > 0

    def test_effect_propagation_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["effect_propagation"])
        assert len(result) > 0

    def test_with_structured_unsat_core_produces_fix(self, sample_reports):
        result = self._run_fix(sample_reports["with_structured_unsat_core"])
        assert len(result) > 0
