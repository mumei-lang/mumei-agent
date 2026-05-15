"""Tests for prompt template builders."""
from agent.prompts import (
    effect_mismatch,
    effect_propagation,
    precondition,
    division_by_zero,
    linearity,
    invariant,
    postcondition,
    spec_code_mapping,
    temporal_effect,
)
from agent.prompts.report_formatter import (
    format_counterexample,
    format_violated_constraints,
    format_unsat_core,
    format_structured_unsat_core,
    format_suggestion,
    format_span,
    format_data_flow,
    format_actionable_fix_hint,
    format_for_initial_generate,
    is_contextual_suggestion,
    format_error_diff,
)
from agent.prompts.examples.formatter import format_examples


SAMPLE_SOURCE = """
atom write_log(msg: Nat)
    effects: [Log];
    requires: msg >= 0;
    ensures: result == msg;
    body: {
        perform FileWrite.write(msg);
        msg
    };
"""

SAMPLE_ERROR_LOG = "Verification Error: Effect not declared"


def test_effect_mismatch_prompt():
    report = {
        "atom": "write_log",
        "violation_type": "effect_mismatch",
        "effect_violation": {
            "declared_effects": ["Log"],
            "required_effect": "FileWrite",
            "source_operation": "FileWrite.write",
            "resolution_paths": [
                {"strategy": "propagation", "description": "Add FileWrite to effects"},
                {"strategy": "isolation", "description": "Remove the write call"},
            ],
        },
    }
    result = effect_mismatch.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "write_log" in result
    assert "FileWrite" in result
    assert "Option A" in result
    assert "Option B" in result


def test_spec_code_mapping_prompt():
    result = spec_code_mapping.build_mapping_prompt(
        {"name": "safe_div", "requires": "b != 0"},
        "atom safe_div(a: i64, b: i64) -> i64\n    requires: b != 0;",
        {"status": "ok"},
    )

    assert spec_code_mapping.SPEC_CODE_MAPPING_SYSTEM_PROMPT
    assert "safe_div" in result
    assert "spec_type" in result
    assert "code_location" in result


def test_effect_mismatch_prompt_with_span_and_suggestion():
    report = {
        "atom": "write_log",
        "violation_type": "effect_mismatch",
        "effect_violation": {
            "declared_effects": ["Log"],
            "required_effect": "FileWrite",
            "source_operation": "FileWrite.write",
            "resolution_paths": [],
        },
        "span": {"file": "test.mm", "line": 5, "col": 1},
        "suggestion": "Add FileWrite to the effects list",
    }
    result = effect_mismatch.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "test.mm:5:1" in result
    assert "Add FileWrite to the effects list" in result


def test_effect_propagation_prompt():
    report = {
        "violation_type": "effect_propagation",
        "effect_violation": {
            "caller": "main_handler",
            "callee": "write_log",
            "caller_effects": ["Log"],
            "callee_effects": ["Log", "FileWrite"],
            "missing_effects": ["FileWrite"],
            "resolution_paths": [],
        },
    }
    result = effect_propagation.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "main_handler" in result
    assert "write_log" in result
    assert "FileWrite" in result


def test_effect_propagation_prompt_with_span():
    report = {
        "violation_type": "effect_propagation",
        "effect_violation": {
            "caller": "main_handler",
            "callee": "write_log",
            "caller_effects": ["Log"],
            "callee_effects": ["Log", "FileWrite"],
            "missing_effects": ["FileWrite"],
            "resolution_paths": [],
        },
        "span": {"file": "app.mm", "line": 10, "col": 3},
    }
    result = effect_propagation.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "app.mm:10:3" in result


def test_precondition_prompt():
    report = {
        "status": "failed",
        "atom": "safe_divide",
        "reason": "Division by zero possible",
        "counterexample": {"a": "0", "b": "0"},
    }
    result = precondition.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "requires" in result
    assert "Z3 Counter-example: a=0, b=0" in result


def test_precondition_prompt_with_violated_constraints():
    report = {
        "status": "failed",
        "atom": "safe_divide",
        "reason": "Division by zero possible",
        "counterexample": {"b": "0"},
        "semantic_feedback": {
            "violated_constraints": [
                {
                    "param": "b",
                    "type": "i64",
                    "constraint": "b != 0",
                    "explanation": "Divisor must not be zero",
                    "sub_constraints": [
                        {"constraint": "b >= 0", "satisfied": True},
                        {"constraint": "b != 0", "satisfied": False},
                    ],
                }
            ],
        },
        "span": {"file": "math.mm", "line": 3, "col": 1},
        "suggestion": "Add requires: b != 0",
    }
    result = precondition.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "Z3 Counter-example: b=0" in result
    assert "Param 'b' (type i64)" in result
    assert "b != 0" in result
    assert "Divisor must not be zero" in result
    assert "[SATISFIED] b >= 0" in result
    assert "[VIOLATED] b != 0" in result
    assert "math.mm:3:1" in result
    assert "Add requires: b != 0" in result


# --- report_formatter unit tests ---

def test_format_counterexample():
    assert format_counterexample({"counterexample": {"a": "0", "b": "0"}}) == "Z3 Counter-example: a=0, b=0"
    assert format_counterexample({}) == ""
    assert format_counterexample({"counterexample": None}) == ""


def test_format_violated_constraints():
    report = {
        "semantic_feedback": {
            "violated_constraints": [
                {"param": "x", "type": "i64", "constraint": "x > 0", "explanation": "Must be positive"},
            ],
        },
    }
    result = format_violated_constraints(report)
    assert "Param 'x'" in result
    assert "x > 0" in result
    assert "Must be positive" in result


def test_format_unsat_core():
    report = {
        "semantic_feedback": {
            "conflicting_constraints": ["x > 10", "x < 5"],
            "raw_unsat_core": ["(> x 10)", "(< x 5)"],
        },
    }
    result = format_unsat_core(report)
    assert "x > 10" in result
    assert "x < 5" in result
    assert "Raw unsat core" in result


def test_format_suggestion():
    assert format_suggestion({"suggestion": "Fix requires"}) == "Suggestion: Fix requires"
    assert format_suggestion({}) == ""


def test_format_span():
    assert format_span({"span": {"file": "a.mm", "line": 1, "col": 2}}) == "Location: a.mm:1:2"
    assert format_span({}) == ""


def test_format_data_flow():
    report = {
        "semantic_feedback": {
            "data_flow": [
                {"expression": "a + b", "value": "0"},
                {"expression": "result", "value": "0"},
            ],
        },
    }
    result = format_data_flow(report)
    assert "a + b" in result
    assert "result" in result


# --- P2: New violation type prompt tests ---

def test_division_by_zero_prompt():
    report = {
        "failure_type": "division_by_zero",
        "atom": "safe_divide",
        "semantic_feedback": {
            "counter_example": {"dividend": "10", "divisor": "0"},
        },
        "counterexample": {"a": "10", "b": "0"},
    }
    result = division_by_zero.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "division-by-zero" in result
    assert "divisor" in result
    assert "requires" in result.lower()


def test_linearity_prompt():
    report = {
        "failure_type": "linearity_violated",
        "atom": "use_twice",
        "semantic_feedback": {
            "violations": [
                {"description": "Variable 'x' used after move"},
            ],
        },
    }
    result = linearity.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "linearity" in result.lower()
    assert "clone" in result.lower() or "restructure" in result.lower()


def test_invariant_prompt():
    report = {
        "failure_type": "invariant_violated",
        "atom": "check_bounds",
        "semantic_feedback": {
            "conflicting_constraints": ["x > 10", "x < 5"],
            "raw_unsat_core": ["(> x 10)", "(< x 5)"],
        },
    }
    result = invariant.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "invariant" in result.lower()
    assert "x > 10" in result
    assert "x < 5" in result


def test_postcondition_prompt():
    report = {
        "failure_type": "postcondition_violated",
        "atom": "add_positive",
        "counterexample": {"x": "0"},
    }
    result = postcondition.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "postcondition" in result.lower()
    assert "ensures" in result.lower()


def test_temporal_effect_prompt():
    report = {
        "failure_type": "temporal_effect_violated",
        "atom": "bad_file_usage",
    }
    result = temporal_effect.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "temporal" in result.lower()
    assert "open" in result.lower()
    assert "close" in result.lower()


# --- P3: Few-shot example tests ---

def test_format_examples_basic():
    examples = [
        {"before": "old code", "after": "new code", "explanation": "why"},
    ]
    result = format_examples(examples)
    assert "# Example fix 1:" in result
    assert "## Before:" in result
    assert "old code" in result
    assert "## After:" in result
    assert "new code" in result
    assert "## Explanation:" in result
    assert "why" in result


def test_format_examples_max_limit():
    examples = [
        {"before": f"code{i}", "after": f"fixed{i}", "explanation": f"reason{i}"}
        for i in range(5)
    ]
    result = format_examples(examples, max_examples=2)
    assert "# Example fix 1:" in result
    assert "# Example fix 2:" in result
    assert "code2" not in result  # third example should be excluded


def test_format_examples_empty():
    assert format_examples([]) == ""


def test_precondition_prompt_contains_examples():
    report = {"status": "failed", "atom": "test"}
    result = precondition.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "# Example fix" in result
    assert "requires: b != 0" in result


def test_effect_mismatch_prompt_contains_examples():
    report = {
        "atom": "write_log",
        "violation_type": "effect_mismatch",
        "effect_violation": {
            "declared_effects": ["Log"],
            "required_effect": "FileWrite",
            "source_operation": "FileWrite.write",
            "resolution_paths": [],
        },
    }
    result = effect_mismatch.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "# Example fix" in result


def test_division_by_zero_prompt_contains_examples():
    report = {
        "failure_type": "division_by_zero",
        "semantic_feedback": {"counter_example": {"dividend": "1", "divisor": "0"}},
    }
    result = division_by_zero.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "# Example fix" in result


def test_postcondition_prompt_contains_examples():
    report = {"failure_type": "postcondition_violated", "atom": "f"}
    result = postcondition.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "# Example fix" in result
    assert "ensures: result > 0" in result


def test_temporal_effect_prompt_contains_examples():
    report = {"failure_type": "temporal_effect_violated", "atom": "f"}
    result = temporal_effect.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "# Example fix" in result
    assert "File.open" in result


# --- structured_unsat_core tests ---

def test_format_structured_unsat_core():
    report = {
        "semantic_feedback": {
            "structured_unsat_core": [
                {
                    "constraint_type": "requires",
                    "param": None,
                    "type_name": None,
                    "field": None,
                    "description": "Precondition (requires)",
                },
                {
                    "constraint_type": "refined_type",
                    "param": "n",
                    "type_name": "Nat",
                    "field": None,
                    "description": "n must be non-negative",
                },
                {
                    "constraint_type": "struct_field",
                    "param": None,
                    "type_name": "Point",
                    "field": "x",
                    "description": "x must be in range",
                },
            ],
        },
    }
    result = format_structured_unsat_core(report)
    assert "- [requires]" in result
    assert "Precondition (requires)" in result
    assert "- [refined_type] param 'n', type Nat:" in result
    assert "n must be non-negative" in result
    assert "- [struct_field] type Point, field 'x':" in result
    assert "x must be in range" in result


def test_format_structured_unsat_core_empty():
    assert format_structured_unsat_core({}) == ""
    assert format_structured_unsat_core({"semantic_feedback": {}}) == ""
    assert format_structured_unsat_core({"semantic_feedback": {"structured_unsat_core": []}}) == ""


def test_invariant_prompt_with_structured_unsat_core():
    report = {
        "failure_type": "invariant_violated",
        "atom": "check_bounds",
        "semantic_feedback": {
            "conflicting_constraints": ["x > 10", "x < 5"],
            "raw_unsat_core": ["(> x 10)", "(< x 5)"],
            "structured_unsat_core": [
                {
                    "constraint_type": "requires",
                    "param": None,
                    "type_name": None,
                    "field": None,
                    "description": "Precondition (requires)",
                },
                {
                    "constraint_type": "refined_type",
                    "param": "x",
                    "type_name": "Nat",
                    "field": None,
                    "description": "x >= 0",
                },
            ],
        },
    }
    result = invariant.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "Structured Unsat Core" in result
    assert "[requires]" in result
    assert "[refined_type]" in result
    assert "param 'x'" in result


def test_precondition_prompt_with_structured_unsat_core():
    report = {
        "status": "failed",
        "atom": "test",
        "semantic_feedback": {
            "structured_unsat_core": [
                {
                    "constraint_type": "u64_nonneg",
                    "param": "n",
                    "type_name": None,
                    "field": None,
                    "description": "n >= 0 by type",
                },
            ],
        },
    }
    result = precondition.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "Structured Unsat Core" in result
    assert "[u64_nonneg]" in result


def test_postcondition_prompt_with_structured_unsat_core():
    report = {
        "failure_type": "postcondition_violated",
        "atom": "f",
        "semantic_feedback": {
            "structured_unsat_core": [
                {
                    "constraint_type": "quantifier",
                    "param": None,
                    "type_name": None,
                    "field": None,
                    "description": "forall x. x > 0",
                },
            ],
        },
    }
    result = postcondition.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "Structured Unsat Core" in result
    assert "[quantifier]" in result


def test_division_by_zero_prompt_with_structured_unsat_core():
    report = {
        "failure_type": "division_by_zero",
        "semantic_feedback": {
            "counter_example": {"dividend": "1", "divisor": "0"},
            "structured_unsat_core": [
                {
                    "constraint_type": "requires",
                    "param": "b",
                    "type_name": None,
                    "field": None,
                    "description": "b != 0",
                },
            ],
        },
    }
    result = division_by_zero.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "Structured Unsat Core" in result
    assert "[requires]" in result


# --- format_actionable_fix_hint tests ---

def test_actionable_fix_hint_division_by_zero():
    report = {
        "failure_type": "division_by_zero",
        "semantic_feedback": {
            "counter_example": {"dividend": "10", "divisor": "0"},
        },
    }
    result = format_actionable_fix_hint(report)
    assert "divisor" in result
    assert "zero" in result
    assert "requires" in result


def test_actionable_fix_hint_linearity_violated():
    report = {
        "failure_type": "linearity_violated",
        "semantic_feedback": {
            "violations": [
                {"description": "Variable 'x' used after move"},
            ],
        },
    }
    result = format_actionable_fix_hint(report)
    assert "Variable 'x' used after move" in result
    assert "clone" in result.lower() or "restructure" in result.lower()


def test_actionable_fix_hint_invariant_violated():
    report = {
        "failure_type": "invariant_violated",
        "semantic_feedback": {
            "conflicting_constraints": ["x > 10", "x < 5"],
        },
    }
    result = format_actionable_fix_hint(report)
    assert "`x > 10`" in result
    assert "`x < 5`" in result
    assert "contradictory" in result


def test_actionable_fix_hint_postcondition_violated():
    report = {
        "failure_type": "postcondition_violated",
        "counterexample": {"x": "0"},
    }
    result = format_actionable_fix_hint(report)
    assert "ensures" in result.lower()
    assert "x=0" in result


def test_actionable_fix_hint_temporal_effect():
    report = {"failure_type": "temporal_effect_violated"}
    result = format_actionable_fix_hint(report)
    assert "state" in result.lower()
    assert "order" in result.lower()


def test_actionable_fix_hint_effect_mismatch():
    report = {
        "violation_type": "effect_mismatch",
        "effect_violation": {
            "declared_effects": ["Log"],
            "required_effect": "FileWrite",
        },
    }
    result = format_actionable_fix_hint(report)
    assert "FileWrite" in result
    assert "declared" in result.lower()


def test_actionable_fix_hint_effect_propagation():
    report = {
        "violation_type": "effect_propagation",
        "effect_violation": {
            "caller": "main_handler",
            "callee": "write_log",
            "missing_effects": ["FileWrite"],
        },
    }
    result = format_actionable_fix_hint(report)
    assert "main_handler" in result
    assert "FileWrite" in result


def test_actionable_fix_hint_fallback():
    report = {}
    result = format_actionable_fix_hint(report)
    assert len(result) > 0  # should produce some output even with empty report


def test_actionable_fix_hint_with_suggestion():
    report = {"suggestion": "Add requires: b != 0"}
    result = format_actionable_fix_hint(report)
    assert "b != 0" in result


# --- format_for_initial_generate tests ---

def test_format_for_initial_generate_basic():
    spec = {
        "name": "fetch_data",
        "constraints": {"requires": "len(url) > 0", "ensures": "len(result) >= 0"},
        "effects": ["SecureHttpGet"],
        "inputs": [{"name": "url", "type": "String"}],
    }
    result = format_for_initial_generate(spec)
    assert "len(url) > 0" in result
    assert "len(result) >= 0" in result
    assert "SecureHttpGet" in result
    assert "url" in result
    assert "String" in result
    assert "requires" in result
    assert "ensures" in result


def test_format_for_initial_generate_no_constraints():
    spec = {"name": "simple_add", "params": [{"name": "a", "type": "i64"}]}
    result = format_for_initial_generate(spec)
    assert "Param `a`" in result
    assert "requires" in result  # general checklist item


# --- generate_atom prompt enhancement tests ---

def test_generate_atom_prompt_contains_common_mistakes():
    from agent.prompts import generate_atom
    result = generate_atom.build_prompt("{}", "", {})
    assert "Common mistakes" in result
    assert "Division by zero" in result
    assert "Mumei syntax only" in result
    assert "if cond { a } else { b }" in result
    assert ".unwrap()" in result
    assert "Linearity" in result


def test_generate_atom_prompt_includes_actionable_hints_on_retry():
    from agent.prompts import generate_atom
    report = {
        "failure_type": "division_by_zero",
        "semantic_feedback": {"counter_example": {"dividend": "1", "divisor": "0"}},
    }
    result = generate_atom.build_prompt("spec", "error", report)
    assert "Actionable fix instructions" in result


# --- division_by_zero and invariant examples tests ---

def test_division_by_zero_uses_own_examples():
    report = {
        "failure_type": "division_by_zero",
        "semantic_feedback": {"counter_example": {"dividend": "1", "divisor": "0"}},
    }
    result = division_by_zero.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "# Example fix" in result
    assert "average" in result or "safe_divide" in result


def test_invariant_uses_own_examples():
    report = {
        "failure_type": "invariant_violated",
        "semantic_feedback": {
            "conflicting_constraints": ["x > 10", "x < 5"],
            "raw_unsat_core": ["(> x 10)", "(< x 5)"],
        },
    }
    result = invariant.build_prompt(SAMPLE_SOURCE, SAMPLE_ERROR_LOG, report)
    assert "# Example fix" in result
    assert "check_range" in result or "bounded_increment" in result


# --- contextual suggestion tests ---

def test_is_contextual_suggestion_with_counterexample():
    assert is_contextual_suggestion("When counterexample a=0, b=0 the requires fails")


def test_is_contextual_suggestion_with_value_keyword():
    assert is_contextual_suggestion("The value of x must be positive")


def test_is_contextual_suggestion_with_equals():
    assert is_contextual_suggestion("The constraint x = 0 is violated")


def test_is_contextual_suggestion_with_because():
    assert is_contextual_suggestion("because the divisor can be zero")


def test_is_contextual_suggestion_with_when():
    assert is_contextual_suggestion("when x is negative the ensures fails")


def test_is_contextual_suggestion_with_specific():
    assert is_contextual_suggestion("The specific constraint a >= 0 is violated")


def test_is_contextual_suggestion_with_eg():
    assert is_contextual_suggestion("e.g. add requires: b != 0")


def test_is_contextual_suggestion_generic_template():
    # Generic template suggestions should NOT be contextual
    assert not is_contextual_suggestion("Add a requires clause")


def test_is_contextual_suggestion_empty():
    assert not is_contextual_suggestion("")


def test_is_contextual_suggestion_none():
    assert not is_contextual_suggestion("")


def test_actionable_fix_hint_contextual_suggestion_alongside_hints():
    """Contextual suggestion appears alongside other hints, not only as fallback."""
    report = {
        "failure_type": "postcondition_violated",
        "counterexample": {"x": "0"},
        "suggestion": "When counterexample x=0, the ensures clause result > 0 fails",
    }
    result = format_actionable_fix_hint(report)
    # Should contain both the postcondition hint AND the contextual suggestion
    assert "ensures" in result.lower()
    assert "contextual" in result.lower()
    assert "x=0" in result


def test_actionable_fix_hint_generic_suggestion_only_as_fallback():
    """Generic suggestion is only used when no other hints are available."""
    report = {
        "failure_type": "postcondition_violated",
        "counterexample": {"x": "0"},
        "suggestion": "Fix the postcondition",
    }
    result = format_actionable_fix_hint(report)
    # The postcondition-specific hint should be present
    assert "ensures" in result.lower()
    # The generic suggestion should NOT appear alongside (it's not contextual)
    assert "Fix the postcondition" not in result


def test_actionable_fix_hint_generic_suggestion_as_fallback_when_no_hints():
    """Generic suggestion is used as fallback when no other hints fire."""
    report = {"suggestion": "Fix the code"}
    result = format_actionable_fix_hint(report)
    assert "Fix the code" in result


# --- format_error_diff tests ---


def test_format_error_diff_unchanged():
    """Passing the same report for both prev and curr yields all UNCHANGED."""
    report = {
        "failure_type": "precondition_violated",
        "counterexample": {"a": "10", "b": "0"},
        "suggestion": "Add requires: b != 0",
        "semantic_feedback": {
            "violated_constraints": [
                {"param": "b", "constraint": "b != 0"},
            ],
        },
    }
    diff = format_error_diff(report, report)
    assert "UNCHANGED" in diff
    # No field should report a change
    for line in diff.splitlines():
        assert "CHANGED" not in line or "UNCHANGED" in line


def test_format_error_diff_changed():
    """Differing failure_type, counterexample, and suggestion produce CHANGED."""
    prev = {
        "failure_type": "precondition_violated",
        "counterexample": {"a": "10", "b": "0"},
        "suggestion": "Add requires: b != 0",
    }
    curr = {
        "failure_type": "postcondition_violated",
        "counterexample": {"x": "5"},
        "suggestion": "Fix ensures clause",
    }
    diff = format_error_diff(prev, curr)
    assert "failure_type: CHANGED" in diff
    assert "precondition_violated" in diff
    assert "postcondition_violated" in diff
    assert "counterexample: CHANGED" in diff
    assert "suggestion: CHANGED" in diff
    assert "Fix ensures clause" in diff


def test_format_error_diff_resolved_constraints():
    """Resolved violated_constraints appear as RESOLVED in the diff."""
    prev = {
        "failure_type": "precondition_violated",
        "semantic_feedback": {
            "violated_constraints": [
                {"param": "a", "constraint": "a > 0"},
                {"param": "b", "constraint": "b != 0"},
            ],
        },
    }
    curr = {
        "failure_type": "precondition_violated",
        "semantic_feedback": {
            "violated_constraints": [
                {"param": "b", "constraint": "b != 0"},
            ],
        },
    }
    diff = format_error_diff(prev, curr)
    assert "RESOLVED" in diff
    assert "a > 0" in diff
    # b != 0 is still violated, so it should not appear as RESOLVED or NEW
    assert "NEW" not in diff
