"""Tests for prompt template builders."""
from agent.prompts import effect_mismatch, effect_propagation, precondition


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
    assert "safe_divide" in result
    assert "requires" in result
