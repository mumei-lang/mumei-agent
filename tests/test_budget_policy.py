"""Tests for retry budget policies."""
from __future__ import annotations

from agent.budget_policy import (
    ActionClassLimit,
    BudgetPolicy,
    classify_action_class,
    compute_policy_fingerprint,
    evaluate_budget,
)
from agent.budget_metrics import aggregate_metrics
from agent.strategies.retry_history import RetryAttempt, RetryHistory


def _history_with_attempts(count: int, *, action_class: str = "llm_fix") -> RetryHistory:
    history = RetryHistory()
    for index in range(count):
        history.add(
            RetryAttempt(
                attempt_number=index + 1,
                source_code=f"source-{index}",
                error_log=f"error-{index}",
                report_data={"failure_type": "postcondition_violated", "counterexample": {"x": index}},
                diagnosis={},
                action_class=action_class,
                tokens_used=100,
                solver_time_seconds=0.5,
                spec_drift_score=0.1,
            )
        )
    return history


def test_policy_fingerprint_is_stable_and_sensitive() -> None:
    policy = BudgetPolicy()
    assert compute_policy_fingerprint(policy) == compute_policy_fingerprint(BudgetPolicy())
    assert compute_policy_fingerprint(policy) != compute_policy_fingerprint(
        BudgetPolicy(max_attempts=6)
    )


def test_budget_exhaustion_returns_structured_manual_review_summary() -> None:
    policy = BudgetPolicy(max_attempts=1)
    history = _history_with_attempts(1)

    decision = evaluate_budget(
        policy,
        history,
        {"failure_type": "postcondition_violated", "counterexample": {"x": 9}},
    )

    assert decision.allowed is False
    assert decision.summary["status"] == "manual_review_required"
    assert decision.summary["reason"] == "max_attempts_exhausted"
    assert decision.summary["total_attempts"] == 1


def test_repeated_counterexample_signature_is_blocked() -> None:
    history = RetryHistory()
    report = {"failure_type": "postcondition_violated", "counterexample": {"x": 1}}
    history.add(
        RetryAttempt(
            attempt_number=1,
            source_code="source",
            error_log="error",
            report_data=report,
            diagnosis={},
        )
    )

    decision = evaluate_budget(BudgetPolicy(), history, report)

    assert decision.allowed is False
    assert decision.reason == "repeated_counterexample_signature"
    assert decision.summary["counterexample_signature"] == history.counterexample_signature(report)


def test_action_class_limit_is_enforced() -> None:
    policy = BudgetPolicy(
        action_class_limits={"lean_escalation": ActionClassLimit(max_attempts=1)}
    )
    history = _history_with_attempts(1, action_class="lean_escalation")

    decision = evaluate_budget(
        policy,
        history,
        {"z3_result_class": "unknown"},
        proposed_action_class="lean_escalation",
    )

    assert decision.allowed is False
    assert decision.reason == "action_class_attempts_exhausted"


def test_classify_action_class_routes_lean_and_effects() -> None:
    assert classify_action_class({"z3_result_class": "unknown"}) == "lean_escalation"
    assert classify_action_class({"violation_type": "effect_mismatch"}) == "effect_fix"


def test_aggregate_metrics_from_history() -> None:
    metrics = aggregate_metrics(_history_with_attempts(2))

    assert metrics.attempts_to_success == 2
    assert metrics.tokens_to_success == 200
    assert metrics.solver_seconds_to_success == 1.0
    assert metrics.spec_drift_score == 0.1
