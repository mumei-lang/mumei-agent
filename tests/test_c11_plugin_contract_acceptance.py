"""C11 plugin-contract acceptance regressions.

This file pins the issue-level matrix in one place. Synthetic adapters are
used throughout: scheduling is a host dispatch record, never proof truth,
Evidence acceptance or grade promotion.
"""

from __future__ import annotations

import hashlib

import pytest

from agent import core_evidence
from agent.core_evidence import check_evidence_representation
from agent.verification_attempt import (
    AttemptEvent,
    AttemptNormalizedResult,
    AttemptOutput,
    AttemptRecord,
)
from agent.verification_planner import (
    AdapterRegistry,
    PlannerPolicy,
    RuntimeObservation,
    SettingSpec,
)
from tests.test_c04_planner_acceptance import (
    INPUT_FORMAT,
    PY,
    available,
    contract,
    exit_three,
    exit_zero,
    manifest,
    policy,
    register,
    request,
    schedule,
)


def configured_manifest(adapter_id: str, **overrides) -> dict:
    values = {
        "setting_specs": [
            {
                "name": "rounds",
                "kind": "integer",
                "default": 1,
                "minimum": 1,
                "maximum": 8,
            }
        ]
    }
    values.update(overrides)
    return manifest(adapter_id, **values)


def reasons(plan, adapter_id):
    return {
        decision.adapter_id: decision.reasons for decision in plan.decisions
    }[adapter_id]


def test_user_adapter_registration_configuration_location_version_and_disable():
    registry = AdapterRegistry()
    register(
        registry,
        configured_manifest(
            "alpha", adapter_version="1.0.0", location="remote", priority=1
        ),
    )
    selected_policy = policy(
        selected_adapter="alpha",
        allowed_locations=frozenset({"remote"}),
        timeout_ms=500,
        memory_mb=32,
        adapter_settings=(("alpha", (("rounds", 4),)),),
        tool_version_pins=(("alpha", "1.0.0"),),
    )
    plan = registry.plan(
        request(), selected_policy, available("alpha")
    )

    assert plan.selected is not None
    assert plan.selected.adapter_id == "alpha"
    assert plan.selected.adapter_settings == (("rounds", 4),)
    assert plan.selected.location == "remote"
    assert plan.selected.input_format == INPUT_FORMAT
    assert plan.selected.result_contract == contract()
    assert plan.selected.timeout_ms <= 500
    assert plan.selected.memory_mb <= 32
    assert plan.selected.configuration_fingerprint is not None

    mismatch = registry.plan(
        request(),
        policy(
            selected_adapter="alpha",
            allowed_locations=frozenset({"remote"}),
            tool_version_pins=(("alpha", "1.0.1"),),
        ),
        available("alpha"),
    )
    assert mismatch.selected is None
    assert "tool_version_mismatch" in reasons(mismatch, "alpha")

    disabled = registry.plan(
        request(),
        policy(
            allowed_locations=frozenset({"remote"}),
            disabled_adapters=frozenset({"alpha"}),
        ),
        available("alpha"),
    )
    assert disabled.selected is None
    assert "disabled" in reasons(disabled, "alpha")


def test_invalid_settings_are_static_configuration_errors():
    registry = AdapterRegistry()
    register(registry, configured_manifest("alpha"))
    for value in (0, 9, "4"):
        with pytest.raises(ValueError):
            registry.plan(
                request(),
                policy(adapter_settings=(("alpha", (("rounds", value),)),)),
                available("alpha"),
            )
    with pytest.raises(ValueError):
        registry.plan(
            request(),
            policy(adapter_settings=(("alpha", (("unknown", 1),)),)),
            available("alpha"),
        )


def test_missing_tool_and_denied_fallback_are_not_successes():
    registry = AdapterRegistry()
    register(registry, manifest("alpha"), manifest("beta"))
    missing = schedule(
        registry,
        {"beta": exit_zero()}.get,
        observations=available("alpha", "beta"),
    )
    assert missing.entries[0].terminal_state == "not_dispatched"
    assert missing.selected_adapter_id == "beta"

    denied = schedule(
        registry,
        {"alpha": exit_three(), "beta": exit_zero()}.get,
        planner_policy=policy(selected_adapter="alpha"),
        observations=available("alpha", "beta"),
    )
    assert denied.outcome == "fallback_denied"
    assert denied.selected_adapter_id is None


def test_timeout_is_a_tool_error_and_permitted_fallback_continues():
    registry = AdapterRegistry()
    register(registry, manifest("alpha", max_timeout_ms=200), manifest("beta"))
    result = schedule(
        registry,
        {
            "alpha": (PY, "-c", "import time; time.sleep(30)"),
            "beta": exit_zero(),
        }.get,
        planner_policy=policy(selected_adapter="alpha", allow_fallback=True),
        observations=available("alpha", "beta"),
    )
    assert result.entries[0].terminal_state == "timed_out"
    assert result.entries[1].adapter_id == "beta"
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"


def test_permitted_fallback_preserves_original_requirements():
    registry = AdapterRegistry()
    register(
        registry,
        manifest("alpha"),
        manifest("beta"),
        manifest("gamma", input_formats=["mumei.other-input/v1"], priority=9),
    )
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
    assert plan.selected.input_format == INPUT_FORMAT
    assert plan.selected.result_contract == contract()
    assert "unsupported_input_format" in reasons(plan, "gamma")


def snapshot(body=b"payload", complete=True):
    attempt = AttemptRecord(
        "a" * 64,
        1,
        1000,
        (AttemptEvent("started", 0), AttemptEvent("exited", 1, 0)),
    )
    return AttemptOutput(
        attempt,
        body,
        hashlib.sha256(body).hexdigest(),
        complete=complete,
    )


def test_malformed_and_conflicting_outputs_fail_closed():
    body = b"payload"
    with pytest.raises(ValueError, match="stdout identity mismatch"):
        AttemptOutput(snapshot().attempt, body, "0" * 64)

    output = snapshot(body)
    conflicting = AttemptOutput(
        output.attempt,
        b"other",
        hashlib.sha256(b"other").hexdigest(),
    )
    with pytest.raises(ValueError, match="attempt output report conflict"):
        output.reconcile(conflicting)

    with pytest.raises(ValueError, match="unknown or missing keys"):
        AttemptNormalizedResult.from_dict(
            {"schema_version": "mumei.verifier-run-result/v1"}
        )


def test_partial_output_never_reaches_core_or_acceptance(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("incomplete output reached Core I/O")

    monkeypatch.setattr(core_evidence, "_run_check", forbidden)
    with pytest.raises(
        core_evidence.CoreCheckFailed,
        match="^Core Evidence representation check failed$",
    ):
        check_evidence_representation(
            snapshot(complete=False),
            core_executable="/trusted/core",
            timeout_ms=100,
        )


def test_no_secret_channels_implicit_installs_unapproved_execution_or_egress():
    for forbidden in ("api_key", "command_template", "endpoint_url"):
        with pytest.raises(ValueError, match="setting channel is not permitted"):
            SettingSpec(forbidden, "boolean", False)

    registry = AdapterRegistry()
    for key in ("install_command", "download_url", "environment"):
        with pytest.raises(ValueError):
            registry.register_manifest(manifest("bad", **{key: "x"}))

    argv_manifest = manifest(
        "alpha", attempt_argv=[exit_zero()[0], "-c", "raise SystemExit(0)"]
    )
    registry = AdapterRegistry()
    register(registry, argv_manifest)
    result = schedule(registry, lambda adapter_id: None, observations=available("alpha"))
    assert result.entries[0].terminal_state == "not_dispatched"
    assert result.outcome == "exhausted"


def test_dispatch_records_do_not_claim_evidence_or_grade():
    registry = AdapterRegistry()
    register(registry, manifest("alpha"))
    result = schedule(registry, {"alpha": exit_zero()}.get, observations=available("alpha"))
    document = result.to_dict()
    keys = set()

    def walk(value):
        if isinstance(value, dict):
            keys.update(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
    assert {"grade", "proof_status", "verification_status", "claim"}.isdisjoint(keys)
    assert document["outcome"] == "selected"
    assert document["evidence_check"] is None
    assert document["evidence_acceptance"] is None
