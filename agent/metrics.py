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
    latent_debug_attempts: int = 0
    latent_debug_successes: int = 0
    dense_property_attempts: int = 0
    dense_property_successes: int = 0
    dense_property_compression_ratios: list[float] = field(default_factory=list)
    verification_times_seconds: list[float] = field(default_factory=list)
    dense_verification_times_seconds: list[float] = field(default_factory=list)
    dense_property_baseline_verification_seconds: float = 0.0
    dense_property_verification_seconds: float = 0.0
    extraction_attempts: int = 0
    extraction_successes: int = 0
    new_spec_attempts: int = 0
    outside_decidable_fragment_warnings: int = 0
    z3_unknowns: int = 0
    first_pass_verification_attempts: int = 0
    first_pass_verification_successes: int = 0
    elapsed_seconds: float = 0.0
    challenge_name: str = ""
    llm_tokens_used: int = 0
    by_violation_type: dict[str, ViolationMetrics] = field(default_factory=dict)
    by_logic_fragment: dict[str, ViolationMetrics] = field(default_factory=dict)

    def record_tokens(self, count: int) -> None:
        """Record LLM tokens consumed."""
        self.llm_tokens_used += count

    def record_dense_property_attempt(self) -> None:
        """Record a dense property generation attempt."""
        self.dense_property_attempts += 1

    def record_dense_property_success(self) -> None:
        """Record a dense property generation that changed generated code."""
        self.dense_property_successes += 1

    def record_dense_property_compression(self, ratio: float) -> None:
        """Record how much dense property compression retained."""
        self.dense_property_compression_ratios.append(ratio)

    def record_verification_time(self, seconds: float, dense_properties: bool = False) -> None:
        """Record time spent verifying generated contracts."""
        self.verification_times_seconds.append(seconds)
        if dense_properties:
            self.dense_verification_times_seconds.append(seconds)

    def record_dense_property_verification_time(
        self,
        baseline_seconds: float,
        dense_seconds: float,
    ) -> None:
        """Record comparable baseline and dense contract verification timings."""
        self.dense_property_baseline_verification_seconds += baseline_seconds
        self.dense_property_verification_seconds += dense_seconds

    def record_extraction_attempt(self) -> None:
        """Record a natural-language spec extraction attempt."""
        self.extraction_attempts += 1

    def record_extraction_success(self) -> None:
        """Record a successful natural-language spec extraction."""
        self.extraction_successes += 1

    def record_new_spec(
        self,
        logic_fragment_tags: list[str] | tuple[str, ...] = (),
        *,
        outside_decidable_fragment: bool = False,
        z3_unknown: bool = False,
        first_pass_verified: bool | None = None,
    ) -> None:
        """Record P8-C metrics for a newly generated specification."""
        self.new_spec_attempts += 1
        if outside_decidable_fragment or logic_fragment_tags:
            self.outside_decidable_fragment_warnings += 1
        if z3_unknown:
            self.z3_unknowns += 1
        if first_pass_verified is not None:
            self.first_pass_verification_attempts += 1
            if first_pass_verified:
                self.first_pass_verification_successes += 1
        for tag in logic_fragment_tags:
            if tag not in self.by_logic_fragment:
                self.by_logic_fragment[tag] = ViolationMetrics()
            self.by_logic_fragment[tag].attempts += 1
            if first_pass_verified:
                self.by_logic_fragment[tag].successes += 1

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

    def record_latent_debug_attempt(self, violation_type: str = "unknown") -> None:
        """Record a latent-space debug attempt."""
        self.latent_debug_attempts += 1

    def record_latent_debug_success(self, violation_type: str = "unknown") -> None:
        """Record a successful latent-space debug fix."""
        self.latent_debug_successes += 1
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

    @property
    def latent_debug_success_rate(self) -> float:
        """Return the success rate for latent-space debug fixes."""
        if self.latent_debug_attempts == 0:
            return 0.0
        return self.latent_debug_successes / self.latent_debug_attempts

    @property
    def dense_property_usage_rate(self) -> float:
        """Return the rate at which dense property attempts changed code."""
        if self.dense_property_attempts == 0:
            return 0.0
        return self.dense_property_successes / self.dense_property_attempts

    @property
    def extraction_success_rate(self) -> float:
        """Return the success rate for natural-language spec extraction."""
        if self.extraction_attempts == 0:
            return 0.0
        return self.extraction_successes / self.extraction_attempts

    @property
    def dense_property_average_compression_ratio(self) -> float:
        """Return average retained predicate ratio after compression."""
        if not self.dense_property_compression_ratios:
            return 1.0
        return sum(self.dense_property_compression_ratios) / len(
            self.dense_property_compression_ratios,
        )

    @property
    def dense_property_verification_improvement_rate(self) -> float:
        """Return relative verification-time reduction for dense contracts."""
        baseline = self.dense_property_baseline_verification_seconds
        if baseline <= 0.0:
            return 0.0
        return (baseline - self.dense_property_verification_seconds) / baseline

    @property
    def outside_decidable_fragment_warning_rate(self) -> float:
        """Return the new-spec rate for outside_decidable_fragment warnings."""
        if self.new_spec_attempts == 0:
            return 0.0
        return self.outside_decidable_fragment_warnings / self.new_spec_attempts

    @property
    def z3_unknown_rate(self) -> float:
        """Return the new-spec rate for Z3 unknown outcomes."""
        if self.new_spec_attempts == 0:
            return 0.0
        return self.z3_unknowns / self.new_spec_attempts

    @property
    def first_pass_verification_success_rate(self) -> float:
        """Return the first-pass verification success rate for generated specs."""
        if self.first_pass_verification_attempts == 0:
            return 0.0
        return (
            self.first_pass_verification_successes
            / self.first_pass_verification_attempts
        )

    def logic_fragment_success_rate(self, tag: str) -> float:
        """Return the first-pass success rate for a logic fragment tag."""
        metrics = self.by_logic_fragment.get(tag)
        if metrics is None or metrics.attempts == 0:
            return 0.0
        return metrics.successes / metrics.attempts

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
            "latent_debug_attempts": self.latent_debug_attempts,
            "latent_debug_successes": self.latent_debug_successes,
            "latent_debug_success_rate": self.latent_debug_success_rate,
            "dense_property_attempts": self.dense_property_attempts,
            "dense_property_successes": self.dense_property_successes,
            "dense_property_usage_rate": self.dense_property_usage_rate,
            "dense_property_compression_ratios": self.dense_property_compression_ratios,
            "dense_property_average_compression_ratio": (
                self.dense_property_average_compression_ratio
            ),
            "verification_times_seconds": self.verification_times_seconds,
            "dense_verification_times_seconds": self.dense_verification_times_seconds,
            "dense_property_baseline_verification_seconds": (
                self.dense_property_baseline_verification_seconds
            ),
            "dense_property_verification_seconds": (
                self.dense_property_verification_seconds
            ),
            "dense_property_verification_improvement_rate": (
                self.dense_property_verification_improvement_rate
            ),
            "extraction_attempts": self.extraction_attempts,
            "extraction_successes": self.extraction_successes,
            "new_spec_attempts": self.new_spec_attempts,
            "outside_decidable_fragment_warnings": self.outside_decidable_fragment_warnings,
            "outside_decidable_fragment_warning_rate": self.outside_decidable_fragment_warning_rate,
            "z3_unknowns": self.z3_unknowns,
            "z3_unknown_rate": self.z3_unknown_rate,
            "first_pass_verification_attempts": self.first_pass_verification_attempts,
            "first_pass_verification_successes": self.first_pass_verification_successes,
            "first_pass_verification_success_rate": self.first_pass_verification_success_rate,
            "elapsed_seconds": self.elapsed_seconds,
            "challenge_name": self.challenge_name,
            "llm_tokens_used": self.llm_tokens_used,
            "by_violation_type": {
                vtype: {"attempts": m.attempts, "successes": m.successes}
                for vtype, m in self.by_violation_type.items()
            },
            "by_logic_fragment": {
                tag: {"attempts": m.attempts, "successes": m.successes}
                for tag, m in self.by_logic_fragment.items()
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
        by_logic_fragment: dict[str, ViolationMetrics] = {}
        for tag, tag_data in data.get("by_logic_fragment", {}).items():
            by_logic_fragment[tag] = ViolationMetrics(
                attempts=tag_data.get("attempts", 0),
                successes=tag_data.get("successes", 0),
            )
        return cls(
            total_attempts=data.get("total_attempts", 0),
            successes=data.get("successes", 0),
            rule_based_attempts=data.get("rule_based_attempts", 0),
            rule_based_successes=data.get("rule_based_successes", 0),
            pattern_attempts=data.get("pattern_attempts", 0),
            pattern_successes=data.get("pattern_successes", 0),
            latent_debug_attempts=data.get("latent_debug_attempts", 0),
            latent_debug_successes=data.get("latent_debug_successes", 0),
            dense_property_attempts=data.get("dense_property_attempts", 0),
            dense_property_successes=data.get("dense_property_successes", 0),
            dense_property_compression_ratios=data.get(
                "dense_property_compression_ratios", [],
            ),
            verification_times_seconds=data.get("verification_times_seconds", []),
            dense_verification_times_seconds=data.get(
                "dense_verification_times_seconds", [],
            ),
            dense_property_baseline_verification_seconds=data.get(
                "dense_property_baseline_verification_seconds", 0.0,
            ),
            dense_property_verification_seconds=data.get(
                "dense_property_verification_seconds", 0.0,
            ),
            extraction_attempts=data.get("extraction_attempts", 0),
            extraction_successes=data.get("extraction_successes", 0),
            new_spec_attempts=data.get("new_spec_attempts", 0),
            outside_decidable_fragment_warnings=data.get(
                "outside_decidable_fragment_warnings", 0
            ),
            z3_unknowns=data.get("z3_unknowns", 0),
            first_pass_verification_attempts=data.get(
                "first_pass_verification_attempts", 0
            ),
            first_pass_verification_successes=data.get(
                "first_pass_verification_successes", 0
            ),
            elapsed_seconds=data.get("elapsed_seconds", 0.0),
            challenge_name=data.get("challenge_name", ""),
            llm_tokens_used=data.get("llm_tokens_used", 0),
            by_violation_type=by_vtype,
            by_logic_fragment=by_logic_fragment,
        )

    def to_json(self) -> str:
        """Return metrics as a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=2)
