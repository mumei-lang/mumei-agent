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

    def test_picks_last_zero_param_when_multiple_are_zero(self) -> None:
        """When both params are 0, pick the last one (likely the divisor)."""
        report = {
            "failure_type": "division_by_zero",
            "atom": "unsafe_div",
            "semantic_feedback": {
                "counter_example": {"dividend": "0", "divisor": "0"},
            },
            "counterexample": {"a": "0", "b": "0"},
        }
        result = try_rule_based_fix(_DIV_SOURCE_TRUE, report)
        assert result is not None
        assert "b != 0" in result

    def test_uses_explicit_divisor_key(self) -> None:
        """When semantic CE has explicit 'divisor' key, prefer it."""
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
                "counter_example": {"dividend": "0", "divisor": "0"},
            },
            "counterexample": {"x": "0", "y": "0"},
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        # Both x and y are 0, but semantic has "divisor" key → picks last zero = y
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


# ---------------------------------------------------------------------------
# Postcondition violated tests
# ---------------------------------------------------------------------------

class TestFixPostconditionViolated:
    """Tests for the postcondition_violated rule-based fix."""

    def test_wraps_body_with_guard(self) -> None:
        """Body expression is wrapped with ``if expr >= 0`` guard."""
        source = """\
atom bad_sub(a: i64, b: i64)
    requires: true;
    ensures: result >= 0;
    body: {
        a - b
    };
"""
        report = {
            "failure_type": "postcondition_violated",
            "atom": "bad_sub",
            "counterexample": {"a": "3", "b": "10"},
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        assert "__tmp" in result
        assert ">= 0" in result

    def test_returns_none_when_ensures_not_result_ge_0(self) -> None:
        """If ensures doesn't contain ``result >= 0``, return None."""
        source = """\
atom foo(a: i64)
    requires: true;
    ensures: result == a;
    body: {
        a
    };
"""
        report = {
            "failure_type": "postcondition_violated",
            "atom": "foo",
        }
        result = try_rule_based_fix(source, report)
        assert result is None

    def test_returns_none_when_atom_missing(self) -> None:
        """Missing atom name in report → None."""
        report = {
            "failure_type": "postcondition_violated",
        }
        result = try_rule_based_fix("atom x() body: 1;", report)
        assert result is None


# ---------------------------------------------------------------------------
# Invariant violated tests
# ---------------------------------------------------------------------------

class TestFixInvariantViolated:
    """Tests for the invariant_violated rule-based fix."""

    def test_adds_bounds_check(self) -> None:
        """Adds bounds check for field constraint violation."""
        source = """\
atom update_count(count: i64, delta: i64)
    requires: true;
    ensures: result >= 0;
    body: {
        count = count + delta;
    };
"""
        report = {
            "violation_type": "invariant_violated",
            "atom": "update_count",
            "semantic_feedback": {
                "violated_constraints": [
                    {"field": "count", "constraint": "count >= 0"},
                ],
            },
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        assert "if" in result
        assert ">= 0" in result

    def test_does_not_match_equality_comparison(self) -> None:
        """Regex must not match ``==`` as an assignment."""
        source = """\
atom update_count(count: i64, delta: i64)
    requires: true;
    ensures: result >= 0;
    body: {
        if count == 0 { return delta; };
        count = count + delta;
    };
"""
        report = {
            "violation_type": "invariant_violated",
            "atom": "update_count",
            "semantic_feedback": {
                "violated_constraints": [
                    {"field": "count", "constraint": "count >= 0"},
                ],
            },
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        # The == comparison line must be untouched
        assert "if count == 0 { return delta; };" in result
        # The assignment should be wrapped
        assert "if count + delta >= 0" in result

    def test_returns_none_when_no_constraints(self) -> None:
        """No violated_constraints → None."""
        report = {
            "violation_type": "invariant_violated",
            "atom": "foo",
            "semantic_feedback": {},
        }
        result = try_rule_based_fix("atom foo() body: 1;", report)
        assert result is None


# ---------------------------------------------------------------------------
# Linearity violated tests
# ---------------------------------------------------------------------------

class TestFixLinearityViolated:
    """Tests for the linearity_violated rule-based fix."""

    def test_comments_out_duplicate_use(self) -> None:
        """Second usage of linear resource is commented out."""
        source = """\
atom use_resource(conn: Connection)
    requires: true;
    ensures: true;
    body: {
        send(conn);
        close(conn);
    };
"""
        report = {
            "violation_type": "linearity_violated",
            "semantic_feedback": {
                "resource": "conn",
            },
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        assert "// " in result
        assert "linearity fix" in result

    def test_extracts_resource_from_message(self) -> None:
        """Resource name extracted from message if not in semantic_feedback."""
        source = """\
atom use_buf(buf: Buffer)
    requires: true;
    ensures: true;
    body: {
        read(buf);
        write(buf);
    };
"""
        report = {
            "violation_type": "linearity_violated",
            "message": "linear resource 'buf' used more than once",
            "semantic_feedback": {},
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        assert "// " in result

    def test_does_not_count_requires_clause_reference(self) -> None:
        """Resource in requires clause must not be counted as a body usage."""
        source = """\
atom use_conn(conn: Connection)
    requires: conn != null;
    ensures: true;
    body: {
        send(conn);
    };
"""
        report = {
            "violation_type": "linearity_violated",
            "atom": "use_conn",
            "semantic_feedback": {
                "resource": "conn",
            },
        }
        # Only one body usage — should return None (no duplicate to comment out)
        result = try_rule_based_fix(source, report)
        assert result is None

    def test_returns_none_when_no_resource_name(self) -> None:
        """No resource name extractable → None."""
        report = {
            "violation_type": "linearity_violated",
            "semantic_feedback": {},
        }
        result = try_rule_based_fix("atom foo() body: 1;", report)
        assert result is None


class TestFixLinearityViolatedViaFailureType:
    """Ensure linearity_violated is reachable via failure_type (not just violation_type)."""

    def test_failure_type_linearity_violated(self) -> None:
        """Reports with failure_type (not violation_type) should still trigger the fix."""
        source = """\
atom use_resource(conn: Connection)
    requires: true;
    ensures: true;
    body: {
        send(conn);
        close(conn);
    };
"""
        report = {
            "failure_type": "linearity_violated",
            "atom": "use_resource",
            "semantic_feedback": {
                "resource": "conn",
            },
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        assert "// " in result
        assert "linearity fix" in result


class TestFixPostconditionViolatedViaViolationType:
    """Ensure postcondition_violated is reachable via violation_type."""

    def test_violation_type_postcondition_violated(self) -> None:
        """Reports with violation_type (not failure_type) should still trigger the fix."""
        source = """\
atom bad_sub(a: i64, b: i64)
    requires: true;
    ensures: result >= 0;
    body: {
        a - b
    };
"""
        report = {
            "violation_type": "postcondition_violated",
            "atom": "bad_sub",
            "counterexample": {"a": "3", "b": "10"},
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        assert "__tmp" in result
        assert ">= 0" in result


class TestInvariantViolatedMultiAtom:
    """Ensure _fix_invariant_violated scopes to the target atom."""

    def test_does_not_modify_other_atom(self) -> None:
        """Assignment in a different atom with same field name is not modified."""
        source = """\
atom other(count: i64, delta: i64)
    requires: true;
    ensures: true;
    body: {
        count = count + delta;
    };

atom update_count(count: i64, delta: i64)
    requires: true;
    ensures: result >= 0;
    body: {
        count = count + delta;
    };
"""
        report = {
            "violation_type": "invariant_violated",
            "atom": "update_count",
            "semantic_feedback": {
                "violated_constraints": [
                    {"field": "count", "constraint": "count >= 0"},
                ],
            },
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        # The first atom's assignment should be untouched
        other_section = result[:result.index("atom update_count")]
        assert "if" not in other_section
        # The target atom's assignment should be wrapped
        target_section = result[result.index("atom update_count"):]
        assert "if" in target_section
        assert ">= 0" in target_section


class TestLinearityViolatedMultiAtom:
    """Ensure _fix_linearity_violated scopes to the target atom."""

    def test_does_not_comment_out_other_atom(self) -> None:
        """Usage in a different atom should not be commented out."""
        source = """\
atom other(conn: Connection)
    requires: true;
    ensures: true;
    body: {
        send(conn);
    };

atom use_resource(conn: Connection)
    requires: true;
    ensures: true;
    body: {
        send(conn);
        close(conn);
    };
"""
        report = {
            "violation_type": "linearity_violated",
            "atom": "use_resource",
            "semantic_feedback": {
                "resource": "conn",
            },
        }
        result = try_rule_based_fix(source, report)
        assert result is not None
        # The first atom should be untouched
        other_section = result[:result.index("atom use_resource")]
        assert "//" not in other_section
        # The target atom should have a comment
        target_section = result[result.index("atom use_resource"):]
        assert "linearity fix" in target_section


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
