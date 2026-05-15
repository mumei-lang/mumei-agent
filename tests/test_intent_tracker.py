"""Tests for specification intent tracking."""

from agent.config import AgentConfig
from agent.intent_tracker import IntentTracker


def test_intent_drift_preserved():
    """Intent is preserved when constraints are unchanged."""
    original = {"requires": "x >= 0", "ensures": "result >= 0"}
    refined = {"requires": "x >= 0", "ensures": "result >= 0"}

    tracker = IntentTracker(AgentConfig())
    result = tracker.track_intent_drift(original, refined)

    assert result.intent_preserved
    assert result.drift_score == 1.0


def test_intent_drift_weakened():
    """Intent is weakened when a constraint is removed."""
    original = {"requires": "x >= 0 && x < 100", "ensures": "result >= 0"}
    refined = {"requires": "x >= 0", "ensures": "result >= 0"}

    tracker = IntentTracker(AgentConfig())
    result = tracker.track_intent_drift(original, refined)

    assert not result.intent_preserved
    assert result.drift_score < 1.0
    assert any(change.change_type == "weakened" for change in result.changes)


def test_intent_drift_strengthened_is_partially_preserved():
    original = {"requires": "x >= 0", "ensures": "result >= 0"}
    refined = {"requires": "x >= 0 && x < 100", "ensures": "result >= 0"}

    result = IntentTracker(AgentConfig()).track_intent_drift(original, refined)

    assert result.intent_preserved
    assert result.drift_score == 0.9
    assert any(change.intent_impact == "strengthened" for change in result.changes)


def test_intent_violation_when_field_removed():
    original = {"requires": "x >= 0", "ensures": "result >= 0"}
    refined = {"requires": "x >= 0"}

    result = IntentTracker(AgentConfig()).track_intent_drift(original, refined)

    assert not result.intent_preserved
    assert any(change.intent_impact == "violated" for change in result.changes)
    assert result.warnings


def test_nested_atom_intent_drift():
    original = {
        "atoms": [
            {
                "name": "safe_add",
                "requires": "a >= 0 && b >= 0",
                "ensures": "result >= 0",
            }
        ]
    }
    refined = {
        "atoms": [
            {
                "name": "safe_add",
                "requires": "a >= 0",
                "ensures": "result >= 0",
            }
        ]
    }

    result = IntentTracker(AgentConfig()).track_intent_drift(original, refined)

    assert any(change.field == "atoms.safe_add.requires" for change in result.changes)
    assert not result.intent_preserved


def test_compare_effects_weakened():
    tracker = IntentTracker(AgentConfig())

    change = tracker.compare_constraints("effects", ["Log", "FileWrite"], ["Log"])

    assert change.change_type == "weakened"
    assert change.intent_impact == "weakened"
