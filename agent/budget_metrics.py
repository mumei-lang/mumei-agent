"""Metrics aggregation for retry budget feedback."""
from __future__ import annotations

from dataclasses import dataclass

from agent.strategies.retry_history import RetryHistory


@dataclass
class BudgetMetrics:
    attempts_to_success: int
    tokens_to_success: int
    solver_seconds_to_success: float
    spec_drift_score: float


def aggregate_metrics(history: RetryHistory) -> BudgetMetrics:
    """Aggregate metrics from retry history."""
    return BudgetMetrics(
        attempts_to_success=len(history.attempts),
        tokens_to_success=history.total_tokens(),
        solver_seconds_to_success=history.total_solver_time_seconds(),
        spec_drift_score=history.max_spec_drift_score(),
    )
