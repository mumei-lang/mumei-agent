"""Unit tests for agent.strategies.rule_based_fix."""
from __future__ import annotations

from agent.strategies.rule_based_fix import try_rule_based_fix


# ---------------------------------------------------------------------------
# Sample Mumei source strings
# ---------------------------------------------------------------------------

_DIV_SOURCE_TRUE = """\
atom unsafe_div(a: i64, b: i64)
    requires: true;
    ensures: result == a / b;
    body: a / b;
"""

_DIV_SOURCE_EXISTING_REQ = """\
atom unsafe_div(a: i64, b: i64)
    requires: a > 0;
    ensures: result == a / b;
    body: a / b;
"""

_EFFECT_SOURCE = """\
atom write_log(msg: Str)
    effects: [Log]
    requires: true;
    ensures: true;
    body: { perform FileWrite.write(msg) }
"""

_EFFECT_NO_DECL_SOURCE = """\
atom write_log(msg: Str)
    requires: true;
    ensures: true;
    body: { perform FileWrite.write(msg) }
"""

_PROPAGATION_SOURCE = """\
atom write_log(msg: Str)
    effects: [Log, FileWrite]
    requires: true;
    ensures: true;
    body: { perform FileWrite.write(msg) }

atom main_handler(msg: Str)
    effects: [Log]
    requires: true;
    ensures: true;
    body: { write_log(msg) }
"""

_PRECONDITION_SOURCE = """\
atom safe_divide(a: i64, b: i64)
    requires: true;
    ensures: result == a / b;
    body: a / b;
"""


# ---------------------------------------------------------------------------
# Division by zero tests
# ---------------------------------------------------------------------------

class TestFixDivisionByZero:
    """Tests for the division_by_zero rule-based fix."""

    def test_adds_requires_from_true(self) -> None:
        """Source with ``requires: true`` → adds ``b != 0``."""
        report = {
            "failure_type": "division_by_zero",
            "atom": "unsafe_div",
            "semantic_feedback": {
                "counter_example": {"dividend": "10", "divisor": "0"},
            },
            "counterexample": {"a": "10", "b": "0"},
        }
        result = try_rule_based_fix(_DIV_SOURCE_TRUE, report)
        assert result is not None
        assert "requires: b != 0;" in result

    def test_appends_to_existing_requires(self) -> None:
        """Source with ``requires: a > 0`` → appends ``&& b != 0``."""
        report = {
            "failure_type": "division_by_zero",
            "atom": "unsafe_div",
            "semantic_feedback": {
                "counter_example": {"dividend": "10", "divisor": "0"},
            },
            "counterexample": {"a": "10", "b": "0"},
        }
        result = try_rule_based_fix(_DIV_SOURCE_EXISTING_REQ, report)
        assert result is not None
        assert "requires: a > 0 && b != 0;" in result

    def test_uses_semantic_counter_example_divisor(self) -> None:
        """When semantic_feedback.counter_example has divisor=0, use that key."""
        source = """\
atom my_div(x: i64, y: i64)
    requires: true;
    ensures: result == x / y;
    body: x / y;
"""
        report = {
            "failure_type": "division_by_zero",
            "atom": "my_div",
            "semantic_feedback": {
                "counter_example": {"x": "10", "y": "0"},
            },
            "counterexample": {"x": "10", "y": "0"},
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        assert "y != 0" in result

    def test_returns_none_when_no_atom(self) -> None:
        """Missing atom name in report → None."""
        report = {
            "failure_type": "division_by_zero",
            "counterexample": {"b": "0"},
        }
        result = try_rule_based_fix(_DIV_SOURCE_TRUE, report)
        assert result is None


# ---------------------------------------------------------------------------
# Effect mismatch tests
# ---------------------------------------------------------------------------

class TestFixEffectMismatch:
    """Tests for the effect_mismatch rule-based fix."""

    def test_adds_effect_to_existing_list(self) -> None:
        """Existing ``effects: [Log]`` → ``effects: [Log, FileWrite]``."""
        report = {
            "violation_type": "effect_mismatch",
            "atom": "write_log",
            "effect_violation": {
                "declared_effects": ["Log"],
                "required_effect": "FileWrite",
            },
        }
        result = try_rule_based_fix(_EFFECT_SOURCE, report)
        assert result is not None
        assert "effects: [Log, FileWrite]" in result

    def test_adds_effects_line_when_missing(self) -> None:
        """No effects line → inserts ``effects: [FileWrite]``."""
        report = {
            "violation_type": "effect_mismatch",
            "atom": "write_log",
            "effect_violation": {
                "declared_effects": [],
                "required_effect": "FileWrite",
            },
        }
        result = try_rule_based_fix(_EFFECT_NO_DECL_SOURCE, report)
        assert result is not None
        assert "effects: [FileWrite]" in result

    def test_returns_none_when_effect_already_declared(self) -> None:
        """If required effect is already in the list → None."""
        report = {
            "violation_type": "effect_mismatch",
            "atom": "write_log",
            "effect_violation": {
                "declared_effects": ["Log"],
                "required_effect": "Log",
            },
        }
        result = try_rule_based_fix(_EFFECT_SOURCE, report)
        assert result is None


# ---------------------------------------------------------------------------
# Effect propagation tests
# ---------------------------------------------------------------------------

class TestFixEffectPropagation:
    """Tests for the effect_propagation rule-based fix."""

    def test_adds_missing_effects_to_caller(self) -> None:
        """Caller ``effects: [Log]`` → ``effects: [Log, FileWrite]``."""
        report = {
            "violation_type": "effect_propagation",
            "effect_violation": {
                "caller": "main_handler",
                "callee": "write_log",
                "caller_effects": ["Log"],
                "callee_effects": ["Log", "FileWrite"],
                "missing_effects": ["FileWrite"],
            },
        }
        result = try_rule_based_fix(_PROPAGATION_SOURCE, report)
        assert result is not None
        assert "effects: [Log, FileWrite]" in result
        # The first atom (write_log) should not be changed
        lines = result.split("\n")
        # Find the main_handler block — its effects line should have FileWrite
        in_main = False
        for line in lines:
            if "main_handler" in line:
                in_main = True
            if in_main and "effects:" in line:
                assert "FileWrite" in line
                break

    def test_returns_none_when_all_effects_present(self) -> None:
        """If caller already has all required effects → None."""
        report = {
            "violation_type": "effect_propagation",
            "effect_violation": {
                "caller": "main_handler",
                "missing_effects": [],
            },
        }
        result = try_rule_based_fix(_PROPAGATION_SOURCE, report)
        assert result is None


# ---------------------------------------------------------------------------
# Precondition tests
# ---------------------------------------------------------------------------

class TestFixPrecondition:
    """Tests for the precondition_violated rule-based fix."""

    def test_adds_simple_constraint(self) -> None:
        """Violated constraint ``b != 0`` → added to requires."""
        report = {
            "failure_type": "precondition_violated",
            "atom": "safe_divide",
            "counterexample": {"a": "10", "b": "0"},
            "semantic_feedback": {
                "violated_constraints": [
                    {
                        "param": "b",
                        "type": "i64",
                        "constraint": "b != 0",
                        "explanation": "Divisor must not be zero",
                    }
                ],
            },
        }
        result = try_rule_based_fix(_PRECONDITION_SOURCE, report)
        assert result is not None
        assert "b != 0" in result

    def test_skips_complex_constraint(self) -> None:
        """Non-simple constraint (e.g. function call) → None."""
        report = {
            "failure_type": "precondition_violated",
            "atom": "safe_divide",
            "semantic_feedback": {
                "violated_constraints": [
                    {
                        "param": "a",
                        "constraint": "is_valid(a)",
                    }
                ],
            },
        }
        result = try_rule_based_fix(_PRECONDITION_SOURCE, report)
        assert result is None

    def test_skips_already_present_constraint(self) -> None:
        """Constraint already in requires → no change → None."""
        source = """\
atom safe_divide(a: i64, b: i64)
    requires: b != 0;
    ensures: result == a / b;
    body: a / b;
"""
        report = {
            "failure_type": "precondition_violated",
            "atom": "safe_divide",
            "semantic_feedback": {
                "violated_constraints": [
                    {"param": "b", "constraint": "b != 0"},
                ],
            },
        }
        result = try_rule_based_fix(source, report)
        assert result is None


# ---------------------------------------------------------------------------
# Fallback / edge case tests
# ---------------------------------------------------------------------------

class TestMultiAtomBoundary:
    """Tests for multi-atom files where the target atom lacks a clause."""

    def test_effect_mismatch_does_not_modify_other_atom(self) -> None:
        """When target atom has no effects but a later atom does, insert — don't modify the other."""
        source = """\
atom foo(x: i64)
    requires: true;
    body: x;

atom bar(x: i64)
    effects: [Log]
    requires: true;
    body: x;
"""
        report = {
            "violation_type": "effect_mismatch",
            "atom": "foo",
            "effect_violation": {"required_effect": "IO"},
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        # foo should get a new effects line
        assert "effects: [IO]" in result
        # bar's effects should be unchanged
        bar_section = result[result.index("atom bar"):]
        assert "effects: [Log]" in bar_section

    def test_requires_does_not_cross_atom_boundary(self) -> None:
        """When target atom has no requires but a later atom does, return None."""
        source = """\
atom foo(x: i64)
    body: x;

atom bar(x: i64)
    requires: true;
    body: x;
"""
        report = {
            "failure_type": "division_by_zero",
            "atom": "foo",
            "counterexample": {"x": "0"},
        }
        result = try_rule_based_fix(source, report)
        # foo has no requires clause within its block → should return None
        assert result is None

    def test_effect_propagation_targets_correct_caller(self) -> None:
        """Effect propagation should modify the caller, not a later atom's effects."""
        source = """\
atom callee(x: i64)
    effects: [IO]
    requires: true;
    body: x;

atom caller(x: i64)
    requires: true;
    body: { callee(x) }

atom bystander(x: i64)
    effects: [Log]
    requires: true;
    body: x;
"""
        report = {
            "violation_type": "effect_propagation",
            "effect_violation": {
                "caller": "caller",
                "callee": "callee",
                "missing_effects": ["IO"],
            },
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        # caller should get a new effects line
        caller_section = result[result.index("atom caller"):result.index("atom bystander")]
        assert "effects: [IO]" in caller_section
        # bystander should be unchanged
        bystander_section = result[result.index("atom bystander"):]
        assert "effects: [Log]" in bystander_section


class TestEdgeCases:
    """Edge cases and fallback behavior."""

    def test_returns_none_for_unknown_failure(self) -> None:
        """Unrecognized failure_type → None."""
        report = {
            "failure_type": "some_unknown_failure",
            "atom": "foo",
        }
        result = try_rule_based_fix(_DIV_SOURCE_TRUE, report)
        assert result is None

    def test_returns_none_when_source_unparseable(self) -> None:
        """Malformed source with no atom declaration → returns None gracefully."""
        source = "this is not valid mumei code at all"
        report = {
            "failure_type": "division_by_zero",
            "atom": "nonexistent",
            "counterexample": {"b": "0"},
        }
        result = try_rule_based_fix(source, report)
        assert result is None

    def test_empty_report_returns_none(self) -> None:
        """Empty report dict → None."""
        result = try_rule_based_fix(_DIV_SOURCE_TRUE, {})
        assert result is None
