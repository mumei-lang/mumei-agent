"""Tests for structured verification thought logs."""
from __future__ import annotations

from agent.proliferate import _jsonify_result
from agent.thought_log import ThoughtProcess, VerificationStep


def test_verification_step_to_dict_omits_none_fields() -> None:
    step = VerificationStep(
        step_number=1,
        timestamp="2026-05-03T10:00:00+00:00",
        action="initial_verify",
        z3_result={"violation_type": "postcondition_violated"},
        verification_success=False,
        fix_strategy=None,
    )

    data = step.to_dict()

    assert data["step_number"] == 1
    assert data["action"] == "initial_verify"
    assert data["z3_result"] == {"violation_type": "postcondition_violated"}
    assert data["verification_success"] is False
    assert "fix_strategy" not in data
    assert "fix_description" not in data


def test_thought_process_add_step_auto_numbers() -> None:
    thought = ThoughtProcess(
        target_file="std/demo.mm",
        started_at="2026-05-03T10:00:00+00:00",
    )

    first = thought.add_step(action="initial_verify")
    second = thought.add_step(action="llm_fix", fix_strategy="llm")

    assert first.step_number == 1
    assert second.step_number == 2
    assert len(thought.steps) == 2


def test_thought_process_to_dict_serializes_steps() -> None:
    thought = ThoughtProcess(
        target_file="std/demo.mm",
        started_at="2026-05-03T10:00:00+00:00",
        final_success=True,
        total_attempts=2,
    )
    thought.add_step(
        action="initial_verify",
        z3_result={"counterexample": {"x": -1}},
        verification_success=False,
    )
    thought.add_step(
        action="re_verify",
        z3_result={"status": "ok"},
        verification_success=True,
        re_verify_success=True,
    )

    data = thought.to_dict()

    assert data["target_file"] == "std/demo.mm"
    assert data["final_success"] is True
    assert data["total_attempts"] == 2
    assert [s["step_number"] for s in data["steps"]] == [1, 2]
    assert data["steps"][0]["z3_result"] == {"counterexample": {"x": -1}}
    assert data["steps"][1]["re_verify_success"] is True


def test_jsonify_result_preserves_thought_process_dict() -> None:
    thought_process = {
        "target_file": "std/demo.mm",
        "started_at": "2026-05-03T10:00:00+00:00",
        "final_success": True,
        "total_attempts": 1,
        "steps": [
            {
                "step_number": 1,
                "timestamp": "2026-05-03T10:00:01+00:00",
                "action": "initial_verify",
                "verification_success": True,
            }
        ],
    }

    out = _jsonify_result(
        {"success": True, "thought_process": thought_process}
    )

    assert out["thought_process"] == thought_process


def test_jsonify_result_serializes_thought_process_object() -> None:
    thought = ThoughtProcess(
        target_file="std/demo.mm",
        started_at="2026-05-03T10:00:00+00:00",
    )
    thought.final_success = True
    thought.total_attempts = 1
    thought.add_step(action="initial_verify", verification_success=True)

    out = _jsonify_result({"success": True, "thought_process": thought})

    assert out["thought_process"] == thought.to_dict()
