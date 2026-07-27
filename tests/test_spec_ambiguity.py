"""Tests for agent/spec_ambiguity.py (conservative ambiguity reporting).

An ambiguous requirement must be *reported*, never completed: the pipeline has
to say whether the requirement is missing outright or merely underspecified, and
must leave the extracted spec untouched either way.
"""
from __future__ import annotations

import copy

from agent.spec_ambiguity import (
    AMBIGUITY_CLASSES,
    classify_contract_gaps,
    classify_prose_ambiguity,
    classify_spec_ambiguity,
)


def _spec(**atom) -> dict:
    base = {
        "name": "withdraw_balance",
        "requires": "amount > 0",
        "ensures": "result >= 0",
    }
    base.update(atom)
    return {"module_name": "wallet", "atoms": [base]}


def test_unmentioned_subject_with_trivial_clause_is_a_missing_requirement():
    ambiguities = classify_contract_gaps(
        "The module exposes a deposit endpoint.",
        _spec(ensures="true"),
    )
    [ambiguity] = ambiguities
    assert ambiguity.classification == "missing_requirement"
    assert ambiguity.subject == "withdraw_balance.ensures"
    assert ambiguity.affects_contract is True
    assert "no requirement text mentions this atom" in ambiguity.evidence


def test_mentioned_subject_with_trivial_clause_stays_underspecified():
    """Described but not pinned down: intent exists, formalisation does not."""
    ambiguities = classify_contract_gaps(
        "Withdraw must keep the balance sane.",
        _spec(ensures=""),
    )
    [ambiguity] = ambiguities
    assert ambiguity.classification == "underspecified_intent"
    assert ambiguity.subject == "withdraw_balance.ensures"
    assert ambiguity.affects_contract is True


def test_concrete_clauses_produce_no_ambiguity():
    assert classify_contract_gaps("Withdraw must not overdraw.", _spec()) == []


def test_vague_prose_is_never_reported_as_missing():
    ambiguities = classify_prose_ambiguity(
        "The system must handle requests with appropriate limits when needed."
    )
    assert ambiguities
    assert {a.classification for a in ambiguities} == {"underspecified_intent"}
    # Prose vagueness leaves the contract itself intact.
    assert all(a.affects_contract is False for a in ambiguities)
    assert all(a.clarification for a in ambiguities)


def test_classification_never_completes_or_mutates_the_spec():
    spec = _spec(requires="", ensures="true")
    snapshot = copy.deepcopy(spec)
    ambiguities = classify_spec_ambiguity(
        "Withdraw should behave appropriately.", spec
    )

    assert spec == snapshot
    assert {a.classification for a in ambiguities} <= set(AMBIGUITY_CLASSES)
    # Both clauses stay ambiguous rather than being guessed at.
    assert {a.subject for a in ambiguities} >= {
        "withdraw_balance.requires",
        "withdraw_balance.ensures",
    }
    for ambiguity in ambiguities:
        assert ambiguity.classification in AMBIGUITY_CLASSES
        assert ambiguity.as_gap().startswith(
            f"spec ambiguity ({ambiguity.classification}): "
        )


def test_contract_gaps_are_reported_before_prose_vagueness():
    ambiguities = classify_spec_ambiguity(
        "Withdraw should keep an appropriate balance.", _spec(ensures="true")
    )
    assert ambiguities[0].affects_contract is True
    assert any(a.affects_contract is False for a in ambiguities)


def test_malformed_specs_are_ignored_rather_than_guessed():
    assert classify_contract_gaps("anything", None) == []
    assert classify_contract_gaps("anything", {"atoms": "nope"}) == []
    assert classify_contract_gaps("anything", {"atoms": [{"name": ""}]}) == []
    assert classify_prose_ambiguity("   ") == []
