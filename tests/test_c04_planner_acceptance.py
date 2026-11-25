"""C04 planner acceptance regressions.

These tests pin the issue-level planner contract as one matrix. They use
synthetic adapters only: scheduling records dispatch observations, never
proof truth, Evidence acceptance or grade promotion.
"""

from __future__ import annotations

import hashlib
import shutil
import sys

import pytest

from agent.attempt_schedule import run_attempt_schedule
from agent.verification_planner import (
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
    RuntimeObservation,
    SettingSpec,
)

PROFILE = "mumei.c04-acceptance/v1"
METHOD = "deductive_proof"
INPUT_FORMAT = "mumei.source-text/v1"
SOURCE = b"atom c04_acceptance\n  ensures: true\n"
SOURCE_SHA256 = hashlib.sha256(SOURCE).hexdigest()
PY = shutil.which("python3", path="/usr/bin:/bin") or sys.executable


def contract() -> ResultContract:
    return ResultContract(
        PROFILE,
        METHOD,
        "unbounded",
        "exact_model",
        "assumed",
    )


def request() -> RouteRequirements:
    return RouteRequirements(
        PROFILE,
        METHOD,
        input_format=INPUT_FORMAT,
        result_contract=contract(),
    )


def manifest(adapter_id: str, **overrides) -> dict:
    document = {
        "schema_version": "mumei.verifier-adapter/v1",
        "adapter_id": adapter_id,
        "adapter_version": "1.0.0",
        "profiles": [PROFILE],
        "methods": [METHOD],
        "result_contracts": [contract().to_dict()],
        "input_formats": [INPUT_FORMAT],
        "required_permissions": [],
    }
    document.update(overrides)
    return document


def register(registry: AdapterRegistry, *documents: dict) -> None:
    for document in documents:
        registry.register_manifest(document)


def policy(**overrides) -> PlannerPolicy:
    values = {
        "timeout_ms": 5_000,
        "memory_mb": 64,
        "allowed_permissions": frozenset(),
    }
    values.update(overrides)
    return PlannerPolicy(**values)


def available(*adapter_ids: str) -> tuple[RuntimeObservation, ...]:
    return tuple(
        RuntimeObservation(adapter_id, "available", "1.0.0", index + 1)
        for index, adapter_id in enumerate(adapter_ids)
    )


def schedule(
    registry: AdapterRegistry,
    argv_for,
    *,
    planner_policy: PlannerPolicy | None = None,
    observations: tuple[RuntimeObservation, ...] = (),
    max_attempts: int = 4,
):
    return run_attempt_schedule(
        registry,
        request(),
        planner_policy or policy(),
        SOURCE,
        SOURCE_SHA256,
        argv_for,
        observations=observations,
        max_attempts=max_attempts,
    )


def exit_zero() -> tuple[str, ...]:
    return (PY, "-c", "raise SystemExit(0)")


def exit_three() -> tuple[str, ...]:
    return (PY, "-c", "raise SystemExit(3)")


def test_manifest_registration_and_explicit_replacement_are_declarative():
    registry = AdapterRegistry()
    register(registry, manifest("alpha", priority=1))
    replacement = manifest(
        "alpha",
        adapter_version="1.1.0",
        priority=9,
        setting_specs=[
            {
                "name": "search_depth",
                "kind": "integer",
                "default": 2,
                "minimum": 1,
                "maximum": 8,
            }
        ],
    )
    registry.register_manifest(replacement, replace=True)

    selected = registry.plan(
        request(),
        policy(selected_adapter="alpha"),
        available("alpha"),
    )

    assert selected.selected is not None
    assert selected.selected.adapter_version == "1.1.0"
    assert selected.selected.adapter_settings == (("search_depth", 2),)
    assert selected.decisions[0].reasons == ("selected_explicit",)

    second = registry.plan(
        request(),
        policy(adapter_settings=(("alpha", (("search_depth", 5),)),)),
        available("alpha"),
    )
    assert second.selected is not None
    assert second.selected.adapter_settings == (("search_depth", 5),)
    assert second.selected.configuration_fingerprint is not None

    with pytest.raises(ValueError, match="replacement must be explicit"):
        registry.register_manifest(manifest("alpha"))


@pytest.mark.parametrize(
    ("observation", "expected_reason"),
    [
        (RuntimeObservation("alpha", "missing", "1.0.0", 1), "tool_missing"),
        (RuntimeObservation("alpha", "unknown", "1.0.0", 1), "availability_unknown"),
        (RuntimeObservation("alpha", "available", None, 1), "tool_version_unknown"),
    ],
)
def test_unavailable_explicit_selection_fails_with_reasons_without_substitution(
    observation, expected_reason
):
    registry = AdapterRegistry()
    register(registry, manifest("alpha"), manifest("beta", priority=9))

    plan = registry.plan(
        request(),
        policy(selected_adapter="alpha"),
        (observation, RuntimeObservation("beta", "available", "1.0.0", 2)),
    )

    assert plan.selected is None
    reasons = {decision.adapter_id: decision.reasons for decision in plan.decisions}
    assert expected_reason in reasons["alpha"]
    assert reasons["beta"] == ("explicit_selection_blocks_automatic_route",)


def test_unsupported_explicit_selection_fails_closed_without_substitution():
    unsupported = manifest("alpha", input_formats=["mumei.other-input/v1"])
    registry = AdapterRegistry()
    register(registry, unsupported, manifest("beta", priority=9))

    plan = registry.plan(
        request(),
        policy(selected_adapter="alpha"),
        available("alpha", "beta"),
    )

    assert plan.selected is None
    reasons = {decision.adapter_id: decision.reasons for decision in plan.decisions}
    assert "unsupported_input_format" in reasons["alpha"]
    assert reasons["beta"] == ("explicit_selection_blocks_automatic_route",)


def test_permitted_fallback_preserves_contract_format_and_records_origin():
    incompatible = manifest("gamma", input_formats=["mumei.other-input/v1"], priority=10)
    registry = AdapterRegistry()
    register(registry, manifest("alpha"), manifest("beta", priority=9), incompatible)

    plan = registry.plan(
        request(),
        policy(selected_adapter="alpha", allow_fallback=True),
        (
            RuntimeObservation("alpha", "missing", "1.0.0", 1),
            RuntimeObservation("beta", "available", "1.0.0", 2),
            RuntimeObservation("gamma", "available", "1.0.0", 3),
        ),
    )

    assert plan.selected is not None
    assert plan.selected.adapter_id == "beta"
    assert plan.fallback_from == "alpha"
    assert plan.selected.result_contract == request().result_contract
    assert plan.selected.input_format == INPUT_FORMAT
    reasons = {decision.adapter_id: decision.reasons for decision in plan.decisions}
    assert reasons["beta"] == ("selected_fallback",)
    assert "unsupported_input_format" in reasons["gamma"]


def test_non_success_exit_is_a_tool_error_not_a_success_and_falls_back():
    registry = AdapterRegistry()
    register(registry, manifest("alpha"), manifest("beta"))
    result = schedule(
        registry,
        {"alpha": exit_three(), "beta": exit_zero()}.get,
        observations=available("alpha", "beta"),
    )

    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert result.entries[0].terminal_state == "exited"
    assert result.entries[0].exit_code == 3
    assert result.entries[1].adapter_id == "beta"


def test_missing_command_is_not_dispatched_and_falls_back():
    registry = AdapterRegistry()
    register(registry, manifest("alpha"), manifest("beta"))
    result = schedule(
        registry,
        {"beta": exit_zero()}.get,
        observations=available("alpha", "beta"),
    )

    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert result.entries[0].terminal_state == "not_dispatched"
    assert result.entries[1].adapter_id == "beta"


def test_timeout_is_a_tool_error_not_a_success_and_falls_back():
    registry = AdapterRegistry()
    register(registry, manifest("alpha", max_timeout_ms=200), manifest("beta"))
    result = schedule(
        registry,
        {
            "alpha": (PY, "-c", "import time; time.sleep(30)"),
            "beta": exit_zero(),
        }.get,
        observations=available("alpha", "beta"),
    )

    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert result.entries[0].terminal_state == "timed_out"


@pytest.mark.parametrize("outcome", ["failed", "inconclusive"])
def test_negative_self_report_is_not_a_success_and_falls_back(outcome):
    negative_manifest = manifest(
        "alpha",
        verdict_markers=[
            {"stream": "stdout", "contains": outcome.upper(), "outcome": outcome}
        ],
    )
    registry = AdapterRegistry()
    register(registry, negative_manifest, manifest("beta"))
    result = schedule(
        registry,
        {
            "alpha": (PY, "-c", f"print('{outcome.upper()}')"),
            "beta": exit_zero(),
        }.get,
        observations=available("alpha", "beta"),
    )

    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert result.entries[0].reported_outcome == outcome
    assert result.entries[0].exit_code == 0


def test_valid_self_report_does_not_rescue_a_non_success_exit():
    valid_manifest = manifest(
        "alpha",
        verdict_markers=[
            {"stream": "stdout", "contains": "VALID", "outcome": "valid"}
        ],
    )
    registry = AdapterRegistry()
    register(registry, valid_manifest, manifest("beta"))
    result = schedule(
        registry,
        {
            "alpha": (PY, "-c", "print('VALID'); raise SystemExit(3)"),
            "beta": exit_zero(),
        }.get,
        observations=available("alpha", "beta"),
    )

    assert result.selected_adapter_id == "beta"
    assert result.entries[0].reported_outcome == "valid"
    assert result.entries[0].exit_code == 3


def test_explicit_selection_denies_fallback_after_a_tool_error():
    registry = AdapterRegistry()
    register(registry, manifest("alpha"), manifest("beta"))
    result = schedule(
        registry,
        {"alpha": exit_three(), "beta": exit_zero()}.get,
        planner_policy=policy(selected_adapter="alpha"),
        observations=available("alpha", "beta"),
    )

    assert result.outcome == "fallback_denied"
    assert result.selected_adapter_id is None
    assert len(result.entries) == 1


def test_secret_or_invocation_setting_channels_are_rejected_statically():
    for forbidden in ("api_key", "command_template", "endpoint_url"):
        with pytest.raises(ValueError, match="setting channel is not permitted"):
            SettingSpec(forbidden, "boolean", False)


def test_schedule_output_is_a_dispatch_record_without_grade_or_claim_keys():
    registry = AdapterRegistry()
    register(registry, manifest("alpha"))
    result = schedule(
        registry,
        {"alpha": exit_zero()}.get,
        observations=available("alpha"),
    )
    document = result.to_dict()

    forbidden = {"grade", "seal_grade", "proof_status", "verification_status", "claim"}
    stack = [document]
    seen: set[str] = set()
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            seen.update(value)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    assert forbidden.isdisjoint(seen)
    assert document["outcome"] == "selected"
    assert document["evidence_check"] is None
    assert document["evidence_acceptance"] is None
