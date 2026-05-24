"""Metrics aggregation for retry budget feedback."""
from __future__ import annotations

import json
from dataclasses import dataclass

from agent.harness_metrics import HarnessMetrics
from agent.strategies.retry_history import RetryHistory


@dataclass
class BudgetMetrics:
    attempts_to_success: int
    tokens_to_success: int
    solver_seconds_to_success: float
    spec_drift_score: float
    harness_metrics: HarnessMetrics | None = None

    def aggregate_summary(self) -> dict:
        summary = {
            "attempts_to_success": self.attempts_to_success,
            "tokens_to_success": self.tokens_to_success,
            "solver_seconds_to_success": self.solver_seconds_to_success,
            "spec_drift_score": self.spec_drift_score,
        }
        if self.harness_metrics is not None:
            summary["harness_metrics"] = self.harness_metrics.aggregate_metrics()
        return summary

    def aggregate_summary_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.aggregate_summary(), indent=indent, ensure_ascii=False)


def aggregate_metrics(
    history: RetryHistory,
    harness_metrics: HarnessMetrics | None = None,
) -> BudgetMetrics:
    """Aggregate metrics from retry history."""
    return BudgetMetrics(
        attempts_to_success=len(history.attempts),
        tokens_to_success=history.total_tokens(),
        solver_seconds_to_success=history.total_solver_time_seconds(),
        spec_drift_score=history.max_spec_drift_score(),
        harness_metrics=harness_metrics,
    )
