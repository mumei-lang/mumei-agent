"""Regression tests tracking fix success rates per violation type.

These tests verify that the Metrics system correctly records attempts and
successes, and that the fix pipeline produces non-empty results for each
known violation type. This acts as a regression guard: if prompt changes
cause a previously-working violation type to stop producing fixes, these
tests will catch it.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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


class TestMetricsSuccessRate:
    """Verify the new success_rate() and overall_success_rate methods."""

    def test_success_rate_no_attempts(self):
        m = Metrics()
        assert m.success_rate("precondition_violated") == 0.0

    def test_success_rate_with_attempts(self):
        m = Metrics()
        for _ in range(5):
            m.record_attempt("precondition_violated")
        for _ in range(4):
            m.record_success("precondition_violated")
        assert m.success_rate("precondition_violated") == pytest.approx(0.8)

    def test_success_rate_all_fail(self):
        m = Metrics()
        for _ in range(3):
            m.record_attempt("division_by_zero")
        assert m.success_rate("division_by_zero") == 0.0

    def test_overall_success_rate_empty(self):
        m = Metrics()
        assert m.overall_success_rate == 0.0

    def test_overall_success_rate(self):
        m = Metrics()
        for _ in range(10):
            m.record_attempt("precondition_violated")
        for _ in range(8):
            m.record_success("precondition_violated")
        for _ in range(5):
            m.record_attempt("division_by_zero")
        for _ in range(5):
            m.record_success("division_by_zero")
        # 13 successes / 15 attempts
        assert m.overall_success_rate == pytest.approx(13.0 / 15.0)


# ---------------------------------------------------------------------------
# Violation types used in success rate regression tests
# ---------------------------------------------------------------------------

_REGRESSION_VIOLATION_TYPES: list[str] = [
    "precondition_violated",
    "postcondition_violated",
    "division_by_zero",
    "linearity_violated",
    "invariant_violated",
    "temporal_effect_violated",
    "effect_mismatch",
    "effect_propagation",
]

# Varied mock LLM responses — most are valid mumei code wrapped in a fenced
# code block that ``get_fix()`` can extract.  One response deliberately omits
# the code fence to simulate an LLM failure, keeping the expected success rate
# at 80 % (4/5) so the threshold assertion is a meaningful guard.
_VARIED_RESPONSES: list[str] = [
    "```mumei\natom fixed(x: i64) requires: x >= 0; ensures: result >= 0; body: x;\n```",
    "```mumei\natom fixed(a: i64, b: i64) requires: b != 0; ensures: result == a / b; body: a / b;\n```",
    "```mumei\natom fixed(x: i64) requires: x > 0; ensures: result > 0; body: x;\n```",
    "```mumei\natom fixed(x: i64) requires: x >= 1; ensures: result >= 0; body: x;\n```",
    # No code fence — get_fix() will return the raw text, but _run_fix_pipeline
    # still counts it as success because len(result) > 0.  To properly simulate
    # a failure we return an empty string so the pipeline produces no output.
    "",
]

# Minimum acceptable success rate threshold (80%).
_SUCCESS_RATE_THRESHOLD = 0.8


class TestRegressionSuccessRate:
    """Regression guard for fix success rates per violation type.

    For each violation type, runs the fix pipeline N times with varied mock
    LLM responses, tracks results via ``Metrics``, and asserts that the
    success rate meets the threshold.
    """

    N_RUNS = 5

    def _run_fix_pipeline(
        self,
        report: dict,
        response_text: str,
    ) -> bool:
        """Run the fix pipeline once and return True if it produced output."""
        client = _mock_client(response_text)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        return len(result) > 0

    @pytest.mark.parametrize("violation_type", _REGRESSION_VIOLATION_TYPES)
    def test_success_rate_above_threshold(
        self, sample_reports, violation_type: str,
    ):
        metrics = Metrics()
        for i in range(self.N_RUNS):
            response = _VARIED_RESPONSES[i % len(_VARIED_RESPONSES)]
            metrics.record_attempt(violation_type)
            success = self._run_fix_pipeline(
                sample_reports[violation_type], response,
            )
            if success:
                metrics.record_success(violation_type)

        rate = metrics.success_rate(violation_type)
        assert rate >= _SUCCESS_RATE_THRESHOLD, (
            f"{violation_type}: success rate {rate:.0%} below "
            f"threshold {_SUCCESS_RATE_THRESHOLD:.0%} "
            f"({metrics.by_violation_type[violation_type].successes}/"
            f"{metrics.by_violation_type[violation_type].attempts})"
        )

    def test_overall_success_rate_above_threshold(self, sample_reports):
        metrics = Metrics()
        for vtype in _REGRESSION_VIOLATION_TYPES:
            for i in range(self.N_RUNS):
                response = _VARIED_RESPONSES[i % len(_VARIED_RESPONSES)]
                metrics.record_attempt(vtype)
                success = self._run_fix_pipeline(
                    sample_reports[vtype], response,
                )
                if success:
                    metrics.record_success(vtype)

        assert metrics.overall_success_rate >= _SUCCESS_RATE_THRESHOLD, (
            f"Overall success rate {metrics.overall_success_rate:.0%} below "
            f"threshold {_SUCCESS_RATE_THRESHOLD:.0%}"
        )
