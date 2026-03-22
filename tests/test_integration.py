"""Integration tests: verify agent can parse each violation type and produce fixes.

Each test feeds a sample report.json through the fix pipeline and asserts
that the resulting prompt contains violation-specific content and the LLM
response is properly extracted.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from agent.strategies.fix_strategy import get_fix, _build_prompt_for_report
from agent.prompts.report_formatter import (
    format_actionable_fix_hint,
    format_structured_unsat_core,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _mock_client(response_text: str) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = response_text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


FIXED_CODE = "```mumei\natom fixed(x: i64) requires: x >= 0; ensures: result >= 0; body: x;\n```"
SAMPLE_SOURCE = "atom broken(x: i64) body: x / 0;"
SAMPLE_ERROR = "Verification Error: division by zero"


# ---------------------------------------------------------------------------
# Integration: end-to-end parse → prompt → fix per violation type
# ---------------------------------------------------------------------------

class TestPreconditionViolated:
    def test_parse_and_fix(self, sample_reports):
        report = sample_reports["precondition_violated"]
        client = _mock_client(FIXED_CODE)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "fixed" in result
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "requires" in prompt.lower()

    def test_prompt_contains_counterexample(self, sample_reports):
        report = sample_reports["precondition_violated"]
        prompt = _build_prompt_for_report(SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "b=0" in prompt

    def test_actionable_hint(self, sample_reports):
        report = sample_reports["precondition_violated"]
        hint = format_actionable_fix_hint(report)
        assert "b != 0" in hint or "constraint" in hint.lower()


class TestPostconditionViolated:
    def test_parse_and_fix(self, sample_reports):
        report = sample_reports["postcondition_violated"]
        client = _mock_client(FIXED_CODE)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "fixed" in result
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "postcondition" in prompt.lower() or "ensures" in prompt.lower()


class TestDivisionByZero:
    def test_parse_and_fix(self, sample_reports):
        report = sample_reports["division_by_zero"]
        client = _mock_client(FIXED_CODE)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "fixed" in result
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "division-by-zero" in prompt or "divisor" in prompt

    def test_actionable_hint_mentions_divisor(self, sample_reports):
        report = sample_reports["division_by_zero"]
        hint = format_actionable_fix_hint(report)
        assert "zero" in hint.lower()
        assert "requires" in hint.lower()


class TestLinearityViolated:
    def test_parse_and_fix(self, sample_reports):
        report = sample_reports["linearity_violated"]
        client = _mock_client(FIXED_CODE)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "fixed" in result
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "linearity" in prompt.lower() or "linear" in prompt.lower()

    def test_actionable_hint_mentions_clone(self, sample_reports):
        report = sample_reports["linearity_violated"]
        hint = format_actionable_fix_hint(report)
        assert "clone" in hint.lower() or "restructure" in hint.lower()


class TestInvariantViolated:
    def test_parse_and_fix(self, sample_reports):
        report = sample_reports["invariant_violated"]
        client = _mock_client(FIXED_CODE)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "fixed" in result
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "invariant" in prompt.lower()

    def test_structured_unsat_core_included(self, sample_reports):
        report = sample_reports["invariant_violated"]
        suc = format_structured_unsat_core(report)
        assert "[requires]" in suc
        assert "[refined_type]" in suc


class TestTemporalEffectViolated:
    def test_parse_and_fix(self, sample_reports):
        report = sample_reports["temporal_effect_violated"]
        client = _mock_client(FIXED_CODE)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "fixed" in result
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "temporal" in prompt.lower()

    def test_actionable_hint_mentions_order(self, sample_reports):
        report = sample_reports["temporal_effect_violated"]
        hint = format_actionable_fix_hint(report)
        assert "order" in hint.lower() or "reorder" in hint.lower()


class TestEffectMismatch:
    def test_parse_and_fix(self, sample_reports):
        report = sample_reports["effect_mismatch"]
        client = _mock_client(FIXED_CODE)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "fixed" in result
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "effect violation" in prompt or "FileWrite" in prompt

    def test_actionable_hint_mentions_effect(self, sample_reports):
        report = sample_reports["effect_mismatch"]
        hint = format_actionable_fix_hint(report)
        assert "FileWrite" in hint


class TestEffectPropagation:
    def test_parse_and_fix(self, sample_reports):
        report = sample_reports["effect_propagation"]
        client = _mock_client(FIXED_CODE)
        result = get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        assert "fixed" in result
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "propagation" in prompt.lower() or "main_handler" in prompt

    def test_actionable_hint_mentions_missing_effects(self, sample_reports):
        report = sample_reports["effect_propagation"]
        hint = format_actionable_fix_hint(report)
        assert "FileWrite" in hint or "missing" in hint.lower()


class TestStructuredUnsatCore:
    """Integration tests for structured_unsat_core enrichment in fix pipeline."""

    def test_unsat_core_in_prompt(self, sample_reports):
        """Verify structured_unsat_core data flows through to the fix prompt."""
        report = sample_reports["with_structured_unsat_core"]
        client = _mock_client(FIXED_CODE)
        get_fix(client, "test-model", SAMPLE_SOURCE, SAMPLE_ERROR, report)
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        # The prompt should contain structured unsat core info
        assert "Structured Unsat Core" in prompt or "unsatisfiable" in prompt.lower()

    def test_format_structured_unsat_core(self, sample_reports):
        report = sample_reports["with_structured_unsat_core"]
        suc = format_structured_unsat_core(report)
        assert "[requires]" in suc
        assert "[ensures]" in suc
        assert "a >= 0 && a < 100" in suc
