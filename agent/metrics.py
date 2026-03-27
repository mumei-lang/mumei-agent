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
    rule_based_attempts: int = 0
    rule_based_successes: int = 0
    by_violation_type: dict[str, ViolationMetrics] = field(default_factory=dict)

    def record_rule_based_attempt(self, violation_type: str = "unknown") -> None:
        """Record a rule-based fix attempt.

        Only increments ``rule_based_attempts``.  The caller is responsible
        for calling :meth:`record_attempt` / :meth:`record_success` at the
        appropriate point so that ``total_attempts`` accurately reflects
        whether the overall fix attempt (rule-based or LLM) succeeded.
        """
        self.rule_based_attempts += 1

    def record_rule_based_success(self, violation_type: str = "unknown") -> None:
        """Record a successful rule-based fix.

        Also records a general attempt + success so that
        ``total_attempts`` and ``successes`` stay consistent.
        """
        self.rule_based_successes += 1
        self.record_attempt(violation_type)
        self.record_success(violation_type)

    @property
    def rule_based_success_rate(self) -> float:
        """Return the success rate for rule-based fixes."""
        if self.rule_based_attempts == 0:
            return 0.0
        return self.rule_based_successes / self.rule_based_attempts

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
            "rule_based_attempts": self.rule_based_attempts,
            "rule_based_successes": self.rule_based_successes,
            "by_violation_type": {
                vtype: {"attempts": m.attempts, "successes": m.successes}
                for vtype, m in self.by_violation_type.items()
            },
        }

    def to_json(self) -> str:
        """Return metrics as a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=2)
