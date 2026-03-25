"""Metrics tracking for heal and generate runs."""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ViolationMetrics:
    """Metrics for a single violation type."""

    attempts: int = 0
    successes: int = 0


@dataclass
class Metrics:
    """Accumulates per-violation-type fix success rates and generation metrics."""

    total_attempts: int = 0
    successes: int = 0
    by_violation_type: dict[str, ViolationMetrics] = field(default_factory=dict)

    def record_attempt(self, violation_type: str = "unknown") -> None:
        """Record a fix or generation attempt."""
        self.total_attempts += 1
        if violation_type not in self.by_violation_type:
            self.by_violation_type[violation_type] = ViolationMetrics()
        self.by_violation_type[violation_type].attempts += 1

    def record_success(self, violation_type: str = "unknown") -> None:
        """Record a successful fix or generation."""
        self.successes += 1
        if violation_type not in self.by_violation_type:
            self.by_violation_type[violation_type] = ViolationMetrics()
        self.by_violation_type[violation_type].successes += 1

    def success_rate(self, violation_type: str) -> float:
        """Return the success rate for *violation_type* (0.0 if no attempts)."""
        vm = self.by_violation_type.get(violation_type)
        if vm is None or vm.attempts == 0:
            return 0.0
        return vm.successes / vm.attempts

    @property
    def overall_success_rate(self) -> float:
        """Return the overall success rate across all violation types."""
        if self.total_attempts == 0:
            return 0.0
        return self.successes / self.total_attempts

    def to_dict(self) -> dict:
        """Convert metrics to a JSON-serializable dict."""
        return {
            "total_attempts": self.total_attempts,
            "successes": self.successes,
            "by_violation_type": {
                vtype: {"attempts": m.attempts, "successes": m.successes}
                for vtype, m in self.by_violation_type.items()
            },
        }

    def to_json(self) -> str:
        """Return metrics as a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=2)
