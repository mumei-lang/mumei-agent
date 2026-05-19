"""Retry budget policy for self-healing and Lean escalation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.strategies.retry_history import RetryHistory


@dataclass
class ActionClassLimit:
    max_attempts: int = 3
    max_tokens: int = 5000
    max_lean_escalations: int = 1


@dataclass
class BudgetPolicy:
    max_attempts: int = 5
    max_tokens: int = 10000
    max_solver_time_ms: int = 30000
    max_semantic_delta: float = 0.5
    action_class_limits: dict[str, ActionClassLimit] = field(default_factory=dict)


@dataclass
class BudgetDecision:
    allowed: bool
    reason: str = ""
    action_class: str = "llm_fix"
    summary: dict[str, Any] = field(default_factory=dict)


def compute_policy_fingerprint(policy: BudgetPolicy) -> str:
    """Compute SHA256 fingerprint of budget policy for certificate tracking."""
    payload = _policy_to_json(policy)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_budget_policy(path: str | None) -> BudgetPolicy:
    if not path:
        return BudgetPolicy()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return budget_policy_from_dict(data)


def budget_policy_from_dict(data: dict[str, Any]) -> BudgetPolicy:
    action_class_limits = {
        str(name): ActionClassLimit(
            max_attempts=int(limit.get("max_attempts", 3)),
            max_tokens=int(limit.get("max_tokens", 5000)),
            max_lean_escalations=int(limit.get("max_lean_escalations", 1)),
        )
        for name, limit in dict(data.get("action_class_limits", {})).items()
    }
    return BudgetPolicy(
        max_attempts=int(data.get("max_attempts", 5)),
        max_tokens=int(data.get("max_tokens", 10000)),
        max_solver_time_ms=int(data.get("max_solver_time_ms", 30000)),
        max_semantic_delta=float(data.get("max_semantic_delta", 0.5)),
        action_class_limits=action_class_limits,
    )


def classify_action_class(report_data: dict[str, Any], *, repeated_signature: bool = False) -> str:
    if repeated_signature:
        return "manual_review"
    reason = str(report_data.get("escalation_reason") or "").lower()
    z3_class = str(report_data.get("z3_result_class") or "").lower()
    if "lean" in reason or z3_class in {"unknown", "timeout", "resource_limit"}:
        return "lean_escalation"
    violation = str(
        report_data.get("violation_type") or report_data.get("failure_type", "")
    ).lower()
    if "effect" in violation:
        return "effect_fix"
    if "precondition" in violation:
        return "precondition_strengthening"
    if "postcondition" in violation:
        return "postcondition_fix"
    return "llm_fix"


def evaluate_budget(
    policy: BudgetPolicy,
    history: RetryHistory,
    report_data: dict[str, Any],
    *,
    proposed_action_class: str | None = None,
) -> BudgetDecision:
    action_class = proposed_action_class or classify_action_class(
        report_data,
        repeated_signature=history.same_counterexample_signature_seen(report_data),
    )
    attempts_used = len(history.attempts)
    tokens_used = history.total_tokens()
    solver_time_ms_used = int(history.total_solver_time_seconds() * 1000)
    spec_drift = history.max_spec_drift_score()
    counts = history.attempts_by_action_class()
    projected_class_attempts = counts.get(action_class, 0) + 1
    limit = policy.action_class_limits.get(action_class)

    summary = build_failure_summary(
        policy,
        history,
        report_data,
        action_class=action_class,
        reason="",
    )

    if action_class == "manual_review":
        summary["reason"] = "repeated_counterexample_signature"
        return BudgetDecision(False, "repeated_counterexample_signature", action_class, summary)
    if attempts_used >= policy.max_attempts:
        summary["reason"] = "max_attempts_exhausted"
        return BudgetDecision(False, "max_attempts_exhausted", action_class, summary)
    if tokens_used >= policy.max_tokens:
        summary["reason"] = "max_tokens_exhausted"
        return BudgetDecision(False, "max_tokens_exhausted", action_class, summary)
    if solver_time_ms_used >= policy.max_solver_time_ms:
        summary["reason"] = "max_solver_time_exhausted"
        return BudgetDecision(False, "max_solver_time_exhausted", action_class, summary)
    if spec_drift > policy.max_semantic_delta:
        summary["reason"] = "semantic_delta_exceeded"
        return BudgetDecision(False, "semantic_delta_exceeded", action_class, summary)
    if limit is not None:
        if projected_class_attempts > limit.max_attempts:
            summary["reason"] = "action_class_attempts_exhausted"
            return BudgetDecision(False, "action_class_attempts_exhausted", action_class, summary)
        if history.tokens_by_action_class().get(action_class, 0) >= limit.max_tokens:
            summary["reason"] = "action_class_tokens_exhausted"
            return BudgetDecision(False, "action_class_tokens_exhausted", action_class, summary)
        if (
            action_class == "lean_escalation"
            and counts.get("lean_escalation", 0) >= limit.max_lean_escalations
        ):
            summary["reason"] = "lean_escalations_exhausted"
            return BudgetDecision(False, "lean_escalations_exhausted", action_class, summary)

    return BudgetDecision(True, action_class=action_class, summary=summary)


def build_failure_summary(
    policy: BudgetPolicy,
    history: RetryHistory,
    report_data: dict[str, Any],
    *,
    action_class: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "manual_review_required",
        "reason": reason,
        "policy_fingerprint": compute_policy_fingerprint(policy),
        "total_attempts": len(history.attempts),
        "attempts_by_action_class": history.attempts_by_action_class(),
        "tokens_used": history.total_tokens(),
        "solver_time_ms_used": int(history.total_solver_time_seconds() * 1000),
        "spec_drift_score": history.max_spec_drift_score(),
        "last_failure_type": report_data.get("failure_type") or report_data.get("violation_type"),
        "counterexample_signature": history.counterexample_signature(report_data),
        "recommended_action_class": action_class,
    }


def _policy_to_json(policy: BudgetPolicy) -> str:
    return json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"))
