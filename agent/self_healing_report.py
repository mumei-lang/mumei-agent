"""Self-healing report helpers."""
from __future__ import annotations

from agent.strategies.retry_history import RetryHistory


def _solver_seconds_from_report(report: dict) -> float:
    raw = (
        report.get("solver_seconds")
        or report.get("solver_time_seconds")
        or report.get("z3_check_time_seconds")
        or 0.0
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _retry_history_to_dict(history: RetryHistory) -> dict:
    return {
        "attempts": [
            {
                "attempt_number": attempt.attempt_number,
                "report_data": attempt.report_data,
                "diagnosis": attempt.diagnosis,
                "action_class": attempt.action_class,
                "tokens_used": attempt.tokens_used,
                "solver_time_seconds": attempt.solver_time_seconds,
                "spec_drift_score": attempt.spec_drift_score,
            }
            for attempt in history.attempts
        ],
    }


def _spec_drift_from_report(report: dict) -> float:
    raw = (
        report.get("spec_drift_score")
        or report.get("semantic_delta")
        or report.get("intent_drift_score")
        or 0.0
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0
