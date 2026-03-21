"""Tests for prompt template builders."""
from agent.prompts import effect_mismatch, effect_propagation, precondition
from agent.prompts.report_formatter import (
    format_counterexample,
    format_violated_constraints,
    format_unsat_core,
    format_suggestion,
    format_span,
    format_data_flow,
)


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
