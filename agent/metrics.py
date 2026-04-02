"""Metrics tracking for heal and generate runs."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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
    pattern_attempts: int = 0
    pattern_successes: int = 0
    elapsed_seconds: float = 0.0
    challenge_name: str = ""
    llm_tokens_used: int = 0
    by_violation_type: dict[str, ViolationMetrics] = field(default_factory=dict)

    def record_tokens(self, count: int) -> None:
        """Record LLM tokens consumed."""
        self.llm_tokens_used += count

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

        .. warning::

            This method calls :meth:`record_attempt` and
            :meth:`record_success` internally.  Callers must **not** call
            those methods separately for the same fix event, or the
            counts will be double-incremented.
        """
        self.rule_based_successes += 1
        self.record_attempt(violation_type)
        self.record_success(violation_type)

    def record_pattern_attempt(self, violation_type: str = "unknown") -> None:
        """Record a pattern-based fix attempt.

        Must be called **before** the outcome is known (i.e. before
        ``try_pattern_fix``), so that ``pattern_attempts`` always
        includes both successes and failures.
        """
        self.pattern_attempts += 1

    def record_pattern_success(self, violation_type: str = "unknown") -> None:
        """Record a successful pattern-based fix.

        Also records a general attempt + success so that
        ``total_attempts`` and ``successes`` stay consistent.

        .. note::

            The caller must have already called
            :meth:`record_pattern_attempt` for this event, so
            ``pattern_attempts`` is **not** incremented here.
        """
        self.pattern_successes += 1
        self.record_attempt(violation_type)
        self.record_success(violation_type)

    @property
    def pattern_success_rate(self) -> float:
        """Return the success rate for pattern-based fixes."""
        if self.pattern_attempts == 0:
            return 0.0
        return self.pattern_successes / self.pattern_attempts

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
            "pattern_attempts": self.pattern_attempts,
            "pattern_successes": self.pattern_successes,
            "elapsed_seconds": self.elapsed_seconds,
            "challenge_name": self.challenge_name,
            "llm_tokens_used": self.llm_tokens_used,
            "by_violation_type": {
                vtype: {"attempts": m.attempts, "successes": m.successes}
                for vtype, m in self.by_violation_type.items()
            },
        }

    @classmethod
    def from_file(cls, path: Path) -> Metrics:
        """Load metrics from a JSON file.

        Args:
            path: Path to a ``metrics.json`` file produced by
                  :meth:`to_dict` / :meth:`to_json`.

        Returns:
            A :class:`Metrics` instance populated from the file.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        by_vtype: dict[str, ViolationMetrics] = {}
        for vtype, vdata in data.get("by_violation_type", {}).items():
            by_vtype[vtype] = ViolationMetrics(
                attempts=vdata.get("attempts", 0),
                successes=vdata.get("successes", 0),
            )
        return cls(
            total_attempts=data.get("total_attempts", 0),
            successes=data.get("successes", 0),
            rule_based_attempts=data.get("rule_based_attempts", 0),
            rule_based_successes=data.get("rule_based_successes", 0),
            pattern_attempts=data.get("pattern_attempts", 0),
            pattern_successes=data.get("pattern_successes", 0),
            elapsed_seconds=data.get("elapsed_seconds", 0.0),
            challenge_name=data.get("challenge_name", ""),
            llm_tokens_used=data.get("llm_tokens_used", 0),
            by_violation_type=by_vtype,
        )

    def to_json(self) -> str:
        """Return metrics as a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=2)
