"""Module-ablation profiles and summary metrics for NLAH-style harness runs."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

HarnessProfileName = Literal[
    "basic",
    "stateful",
    "verifier",
    "self_evolution",
    "lean_fallback",
    "full",
]

HARNESS_MODULES = (
    "artifact_contract",
    "verification_gate",
    "stateful_handoff",
    "retry_classifier",
    "intent_fidelity",
    "multi_candidate_search",
    "lean_fallback",
    "self_evolution",
)

HARNESS_PROFILES: dict[HarnessProfileName, dict[str, bool]] = {
    "basic": {
        "artifact_contract": True,
        "verification_gate": False,
        "stateful_handoff": False,
        "retry_classifier": True,
        "intent_fidelity": False,
        "multi_candidate_search": False,
        "lean_fallback": False,
        "self_evolution": False,
    },
    "stateful": {
        "artifact_contract": True,
        "verification_gate": False,
        "stateful_handoff": True,
        "retry_classifier": True,
        "intent_fidelity": False,
        "multi_candidate_search": False,
        "lean_fallback": False,
        "self_evolution": False,
    },
    "verifier": {
        "artifact_contract": True,
        "verification_gate": True,
        "stateful_handoff": False,
        "retry_classifier": True,
        "intent_fidelity": True,
        "multi_candidate_search": False,
        "lean_fallback": False,
        "self_evolution": False,
    },
    "self_evolution": {
        "artifact_contract": True,
        "verification_gate": True,
        "stateful_handoff": True,
        "retry_classifier": True,
        "intent_fidelity": True,
        "multi_candidate_search": True,
        "lean_fallback": False,
        "self_evolution": True,
    },
    "lean_fallback": {
        "artifact_contract": True,
        "verification_gate": True,
        "stateful_handoff": True,
        "retry_classifier": True,
        "intent_fidelity": True,
        "multi_candidate_search": False,
        "lean_fallback": True,
        "self_evolution": False,
    },
    "full": {
        "artifact_contract": True,
        "verification_gate": True,
        "stateful_handoff": True,
        "retry_classifier": True,
        "intent_fidelity": True,
        "multi_candidate_search": True,
        "lean_fallback": True,
        "self_evolution": True,
    },
}

_VALID_INTENT_FIDELITY_STATUSES = {
    "unknown",
    "passed",
    "failed",
    "drifted",
    "untested",
}


def harness_profile_names() -> tuple[HarnessProfileName, ...]:
    """Return supported harness profile names in CLI order."""
    return tuple(HARNESS_PROFILES)


def module_flags_for_profile(profile: str | None) -> dict[str, bool]:
    """Resolve a harness profile to a complete module flag map."""
    if profile is None:
        profile = "basic"
    if profile not in HARNESS_PROFILES:
        valid = ", ".join(harness_profile_names())
        raise ValueError(f"unknown harness profile {profile!r}; expected one of: {valid}")
    return dict(HARNESS_PROFILES[profile])  # type: ignore[index]


def _enabled(flags: Mapping[str, bool], module: str) -> bool:
    return bool(flags.get(module, False))


def _success_rate(passed: int, total: int) -> float:
    return passed / total if total else 0.0


def _retry_class(value: str | None) -> str:
    return value or "none"


def _intent_status(value: str | None) -> str:
    if value in _VALID_INTENT_FIDELITY_STATUSES:
        return value
    return "unknown"


@dataclass
class HarnessMetricRecord:
    """One stage/module observation for module-ablation analysis."""

    stage: str
    module: str
    module_enabled: bool
    artifact_contract_passed: bool | None = None
    verification_gate: bool | None = None
    handoff_count: int = 0
    retry_class: str = "none"
    intent_fidelity_status: str = "unknown"
    tokens_to_success: int = 0
    solver_seconds_to_success: float = 0.0
    spec_drift_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "module": self.module,
            "module_enabled": self.module_enabled,
            "artifact_contract_passed": self.artifact_contract_passed,
            "verification_gate": self.verification_gate,
            "handoff_count": self.handoff_count,
            "retry_class": self.retry_class,
            "intent_fidelity_status": self.intent_fidelity_status,
            "tokens_to_success": self.tokens_to_success,
            "solver_seconds_to_success": self.solver_seconds_to_success,
            "spec_drift_score": self.spec_drift_score,
        }


@dataclass
class HarnessMetrics:
    """Accumulates harness module flags and stage/module outcomes."""

    profile: str = "basic"
    module_flags: dict[str, bool] = field(default_factory=dict)
    records: list[HarnessMetricRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.module_flags:
            self.module_flags = module_flags_for_profile(self.profile)
        else:
            resolved = module_flags_for_profile(self.profile)
            resolved.update({k: bool(v) for k, v in self.module_flags.items() if k in resolved})
            self.module_flags = resolved

    @classmethod
    def from_profile(cls, profile: str | None) -> "HarnessMetrics":
        return cls(profile=profile or "basic")

    @property
    def multi_candidate_search_enabled(self) -> bool:
        return _enabled(self.module_flags, "multi_candidate_search")

    @property
    def lean_fallback_enabled(self) -> bool:
        return _enabled(self.module_flags, "lean_fallback")

    def apply_to_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Attach harness profile metadata to a generated spec."""
        updated = dict(spec)
        updated["harness_profile"] = self.profile
        updated["harness_modules"] = dict(self.module_flags)
        updated["enable_multi_candidate_search"] = self.multi_candidate_search_enabled
        return updated

    def record_stage(
        self,
        stage: str,
        *,
        module: str | None = None,
        artifact_contract_passed: bool | None = None,
        verification_gate: bool | None = None,
        handoff_count: int = 0,
        retry_class: str | None = None,
        intent_fidelity_status: str | None = None,
        tokens_to_success: int = 0,
        solver_seconds_to_success: float = 0.0,
        spec_drift_score: float = 0.0,
    ) -> HarnessMetricRecord:
        module_name = module or stage
        record = HarnessMetricRecord(
            stage=stage,
            module=module_name,
            module_enabled=_enabled(self.module_flags, module_name),
            artifact_contract_passed=artifact_contract_passed,
            verification_gate=verification_gate,
            handoff_count=max(0, int(handoff_count)),
            retry_class=_retry_class(retry_class),
            intent_fidelity_status=_intent_status(intent_fidelity_status),
            tokens_to_success=max(0, int(tokens_to_success)),
            solver_seconds_to_success=max(0.0, float(solver_seconds_to_success)),
            spec_drift_score=max(0.0, float(spec_drift_score)),
        )
        self.records.append(record)
        return record

    def record_result(
        self,
        stage: str,
        success: bool,
        *,
        retry_class: str | None = None,
        attempts: int = 0,
        tokens_to_success: int = 0,
        solver_seconds_to_success: float = 0.0,
        spec_drift_score: float = 0.0,
    ) -> None:
        self.record_stage(
            stage,
            module="artifact_contract",
            artifact_contract_passed=success,
            handoff_count=attempts,
            retry_class=retry_class,
            tokens_to_success=tokens_to_success,
            solver_seconds_to_success=solver_seconds_to_success,
            spec_drift_score=spec_drift_score,
        )
        self.record_stage(
            stage,
            module="verification_gate",
            verification_gate=success,
            retry_class=retry_class,
            tokens_to_success=tokens_to_success,
            solver_seconds_to_success=solver_seconds_to_success,
            spec_drift_score=spec_drift_score,
        )
        self.record_stage(
            stage,
            module="intent_fidelity",
            intent_fidelity_status="passed" if success else "failed",
            retry_class=retry_class,
            tokens_to_success=tokens_to_success,
            solver_seconds_to_success=solver_seconds_to_success,
            spec_drift_score=spec_drift_score,
        )

    def aggregate_metrics(self) -> dict[str, Any]:
        by_stage: dict[str, dict[str, Any]] = {}
        by_module: dict[str, dict[str, Any]] = {}
        retry_classes: dict[str, int] = {}
        intent_fidelity: dict[str, int] = {}

        for record in self.records:
            for bucket in (by_stage.setdefault(record.stage, _empty_bucket()),
                           by_module.setdefault(record.module, _empty_bucket())):
                _accumulate(bucket, record)
            retry_classes[record.retry_class] = retry_classes.get(record.retry_class, 0) + 1
            intent_fidelity[record.intent_fidelity_status] = (
                intent_fidelity.get(record.intent_fidelity_status, 0) + 1
            )

        for bucket in [*by_stage.values(), *by_module.values()]:
            _finalize_bucket(bucket)

        return {
            "profile": self.profile,
            "module_enabled": dict(self.module_flags),
            "records": [record.to_dict() for record in self.records],
            "by_stage": by_stage,
            "by_module": by_module,
            "retry_class": retry_classes,
            "intent_fidelity_status": intent_fidelity,
        }

    def aggregate_metrics_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.aggregate_metrics(), indent=indent, ensure_ascii=False)


def _empty_bucket() -> dict[str, Any]:
    return {
        "records": 0,
        "enabled_records": 0,
        "artifact_contract_total": 0,
        "artifact_contract_passed": 0,
        "verification_gate_total": 0,
        "verification_gate_passed": 0,
        "handoff_count": 0,
        "tokens_to_success": 0,
        "solver_seconds_to_success": 0.0,
        "max_spec_drift_score": 0.0,
    }


def _accumulate(bucket: dict[str, Any], record: HarnessMetricRecord) -> None:
    bucket["records"] += 1
    if record.module_enabled:
        bucket["enabled_records"] += 1
    if record.artifact_contract_passed is not None:
        bucket["artifact_contract_total"] += 1
        if record.artifact_contract_passed:
            bucket["artifact_contract_passed"] += 1
    if record.verification_gate is not None:
        bucket["verification_gate_total"] += 1
        if record.verification_gate:
            bucket["verification_gate_passed"] += 1
    bucket["handoff_count"] += record.handoff_count
    bucket["tokens_to_success"] += record.tokens_to_success
    bucket["solver_seconds_to_success"] += record.solver_seconds_to_success
    bucket["max_spec_drift_score"] = max(
        bucket["max_spec_drift_score"],
        record.spec_drift_score,
    )


def _finalize_bucket(bucket: dict[str, Any]) -> None:
    bucket["artifact_contract_success_rate"] = _success_rate(
        bucket["artifact_contract_passed"],
        bucket["artifact_contract_total"],
    )
    bucket["verification_gate_success_rate"] = _success_rate(
        bucket["verification_gate_passed"],
        bucket["verification_gate_total"],
    )
