"""Descriptor-only fixtures: no verifier adoption, probes or evidence acceptance."""

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from agent.verification_planner import (
    AdapterDescriptor,
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
    RuntimeObservation,
)

PROFILE = "mumei.pure-i64-comparison/v1"
REQUEST = RouteRequirements(PROFILE, "deductive_proof", frozenset({"lia"}))


def adapter(adapter_id="fixture", **kwargs):
    return replace(
        AdapterDescriptor(
            adapter_id,
            "1.0.0",
            frozenset({PROFILE}),
            frozenset({"deductive_proof"}),
            frozenset({"lia"}),
        ),
        **kwargs,
    )


def observed(adapter_id="fixture", **kwargs):
    return replace(RuntimeObservation(adapter_id, "available", "4.13.0"), **kwargs)


def plan(descriptor=None, policy=None, observation=None, request=REQUEST):
    registry = AdapterRegistry()
    registry.register(descriptor or adapter())
    return registry.plan(
        request, policy or PlannerPolicy(), (observation or observed(),)
    )


def reasons(result, adapter_id="fixture"):
    return next(
        item.reasons for item in result.decisions if item.adapter_id == adapter_id
    )


def test_single_selection_and_effective_budget_never_promote_a_grade():
    result = plan(
        adapter(max_timeout_ms=900, max_memory_mb=128),
        PlannerPolicy(timeout_ms=2000, memory_mb=256),
    )
    assert result.selected.adapter_id == "fixture"
    assert (result.selected.timeout_ms, result.selected.memory_mb) == (900, 128)
    assert result.selected.observed_tool_version == "4.13.0"
    assert reasons(result) == ("selected_priority",)
    assert result.fallback_from is None
    data = json.dumps(result.to_dict())
    for field in ("proved", "verified", "grade", "command", "endpoint", "environment"):
        assert f'"{field}"' not in data


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"enabled": False}, "disabled"),
        ({"protocol_version": "other/v2"}, "protocol_mismatch"),
        ({"profiles": frozenset({"other/v1"})}, "unsupported_semantic_profile"),
        ({"methods": frozenset({"finite_execution"})}, "unsupported_evidence_method"),
        ({"logic_fragments": frozenset()}, "unsupported_logic_fragments"),
        ({"targets": frozenset({"x86_64-unknown-linux-gnu"})}, "target_unknown"),
        ({"location": "remote"}, "location_not_allowed"),
        ({"location": "container"}, "location_not_allowed"),
    ],
)
def test_incompatible_adapters_are_explained_and_not_selected(changes, reason):
    result = plan(adapter(**changes))
    assert result.selected is None
    assert reason in reasons(result)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"availability": "unknown"}, "availability_unknown"),
        ({"availability": "missing"}, "tool_missing"),
        ({"tool_version": None}, "tool_version_unknown"),
        ({"tool_version": "4.12.0"}, "tool_version_mismatch"),
    ],
)
def test_preflight_unknowns_and_pinned_versions_fail_closed(changes, reason):
    result = plan(
        policy=PlannerPolicy(tool_version_pins=(("fixture", "4.13.0"),)),
        observation=observed(**changes),
    )
    assert result.selected is None
    assert reason in reasons(result)


def test_registration_is_not_availability_or_trust_and_disabled_is_user_controlled():
    registry = AdapterRegistry()
    registry.register(adapter())
    result = registry.plan(REQUEST, PlannerPolicy())
    assert result.selected is None
    assert set(reasons(result)) == {"availability_unknown", "tool_version_unknown"}
    result = plan(policy=PlannerPolicy(disabled_adapters=frozenset({"fixture"})))
    assert reasons(result) == ("disabled",)


def test_priority_and_lexical_ties_are_independent_of_registration_order():
    descriptors = [
        adapter("z", priority=5),
        adapter("a", priority=5),
        adapter("low", priority=0),
    ]
    results = []
    for ordered in (descriptors, list(reversed(descriptors))):
        registry = AdapterRegistry()
        for descriptor in ordered:
            registry.register(descriptor)
        results.append(
            registry.plan(
                REQUEST, PlannerPolicy(), tuple(observed(d.adapter_id) for d in ordered)
            )
        )
    assert results[0] == results[1]
    assert results[0].selected.adapter_id == "a"
    assert reasons(results[0], "z") == ("compatible_not_selected",)


def test_explicit_selection_wins_priority_without_parallel_selection():
    registry = AdapterRegistry()
    registry.register(adapter("chosen"))
    registry.register(adapter("higher", priority=99))
    result = registry.plan(
        REQUEST,
        PlannerPolicy(selected_adapter="chosen"),
        (observed("chosen"), observed("higher")),
    )
    assert result.selected.adapter_id == "chosen"
    assert reasons(result, "chosen") == ("selected_explicit",)
    assert reasons(result, "higher") == ("compatible_not_selected",)


@pytest.mark.parametrize("registered", [True, False])
@pytest.mark.parametrize("fallback", [True, False])
def test_explicit_unavailable_is_never_silently_substituted(registered, fallback):
    registry = AdapterRegistry()
    registry.register(adapter("alternative"))
    if registered:
        registry.register(adapter("chosen", enabled=False))
    result = registry.plan(
        REQUEST,
        PlannerPolicy(selected_adapter="chosen", allow_fallback=fallback),
        (observed("alternative"),),
    )
    if fallback:
        assert result.selected.adapter_id == "alternative"
        assert result.fallback_from == "chosen"
        assert reasons(result, "alternative") == ("selected_fallback",)
    else:
        assert result.selected is None
        assert result.fallback_from is None
        assert reasons(result, "alternative") == (
            "explicit_selection_blocks_automatic_route",
        )
    assert ("disabled" if registered else "not_registered") in reasons(result, "chosen")


@pytest.mark.parametrize(
    "method",
    [
        "abstract_interpretation",
        "bounded_model_checking",
        "finite_execution",
        "static_heuristic",
        "identity_check",
    ],
)
def test_even_authorized_fallback_never_reduces_the_requested_method(method):
    result = plan(
        adapter(methods=frozenset({method})),
        PlannerPolicy(selected_adapter="missing", allow_fallback=True),
    )
    assert result.selected is None
    assert "unsupported_evidence_method" in reasons(result)


def test_target_and_location_constraints_are_explicit():
    descriptor = adapter(
        targets=frozenset({"x86_64-unknown-linux-gnu"}), location="remote"
    )
    request = replace(REQUEST, target_triple="aarch64-unknown-linux-gnu")
    result = plan(descriptor, request=request)
    assert set(reasons(result)) == {"unsupported_target", "location_not_allowed"}
    request = replace(REQUEST, target_triple="x86_64-unknown-linux-gnu")
    result = plan(
        descriptor,
        PlannerPolicy(allowed_locations=frozenset({"remote"})),
        request=request,
    )
    assert result.selected.location == "remote"


def test_custom_registration_replacement_and_full_requirement_subset():
    registry = AdapterRegistry()
    registry.register(adapter())
    with pytest.raises(ValueError):
        registry.register(adapter(priority=90))
    with pytest.raises(ValueError):
        registry.register(adapter(), replace="true")
    registry.register(
        adapter(logic_fragments=frozenset({"lia", "arrays"})), replace=True
    )
    request = replace(REQUEST, logic_fragments=frozenset({"lia", "arrays"}))
    assert registry.plan(request, PlannerPolicy(), (observed(),)).selected is not None
    custom = "user.own-semantics/v1"
    registry.register(adapter("custom", profiles=frozenset({custom})))
    result = registry.plan(
        replace(REQUEST, profile=custom), PlannerPolicy(), (observed("custom"),)
    )
    assert result.selected.adapter_id == "custom"


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.2, "100", None])
@pytest.mark.parametrize("field", ["timeout_ms", "memory_mb"])
def test_invalid_policy_budgets_are_rejected(value, field):
    with pytest.raises(ValueError):
        PlannerPolicy(**{field: value})


def test_invalid_metadata_fails_without_echoing_credential_like_input():
    sentinel = "https://fake:obviously-fake-password@example.invalid/?secret=FAKE"
    constructors = [
        lambda: adapter(adapter_id=sentinel),
        lambda: observed(tool_version=sentinel),
        lambda: PlannerPolicy(tool_version_pins=(("fixture", sentinel),)),
        lambda: replace(REQUEST, profile=sentinel),
    ]
    for constructor in constructors:
        with pytest.raises(ValueError) as error:
            constructor()
        assert sentinel not in str(error.value)


def test_duplicates_unknown_pins_and_unknown_observations_are_configuration_errors():
    registry = AdapterRegistry()
    registry.register(adapter())
    with pytest.raises(ValueError):
        registry.plan(REQUEST, PlannerPolicy(), (observed(), observed()))
    with pytest.raises(ValueError):
        registry.plan(REQUEST, PlannerPolicy(), (observed("unregistered"),))
    with pytest.raises(ValueError):
        registry.plan(REQUEST, PlannerPolicy(tool_version_pins=(("typo", "1"),)))
    with pytest.raises(ValueError):
        PlannerPolicy(tool_version_pins=(("fixture", "1"), ("fixture", "2")))


def test_planning_never_reads_environment_files_or_executes_tools(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("planning must be pure")

    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert plan().selected is not None


CONTRACT = ResultContract(
    PROFILE,
    "deductive_proof",
    "unbounded",
    "user.source-model/v1",
    "assumed",
    assumptions=frozenset({"user.model-trust/v1"}),
)


def constrained_request(contract=CONTRACT):
    return RouteRequirements(
        contract.profile, contract.method, frozenset({"lia"}), result_contract=contract
    )


@pytest.mark.parametrize(
    ("method", "scope", "bounds"),
    [
        ("deductive_proof", "unbounded", frozenset()),
        ("bounded_model_checking", "bounded", frozenset({"user.depth-8/v1"})),
        ("finite_execution", "finite", frozenset({"user.cases-5/v1"})),
        ("identity_check", "identity_only", frozenset()),
    ],
)
@pytest.mark.parametrize("status", ["validated", "assumed", "unverified"])
def test_exact_result_contracts_select_without_accepting_their_claims(
    method, scope, bounds, status
):
    contract = replace(
        CONTRACT,
        method=method,
        scope=scope,
        bounds=bounds,
        correspondence_status=status,
    )
    result = plan(
        adapter(methods=frozenset({method}), result_contracts=(contract,)),
        request=constrained_request(contract),
    )
    assert result.selected.result_contract == contract
    assert result.to_dict()["selected"]["result_contract"] == contract.to_dict()
    assert result.to_dict()["request"]["result_contract"] == contract.to_dict()
    for key in ["result", "execution", "grade", "acceptance", "evidence"]:
        assert f'"{key}"' not in json.dumps(result.to_dict())


@pytest.mark.parametrize(
    "contract",
    [
        replace(CONTRACT, profile="user.other-profile/v1"),
        replace(
            CONTRACT,
            method="finite_execution",
            scope="finite",
            bounds=frozenset({"user.cases/v1"}),
        ),
        replace(CONTRACT, scope="bounded", bounds=frozenset({"user.depth/v1"})),
        replace(CONTRACT, scope="identity_only"),
        replace(CONTRACT, assumptions=frozenset()),
        replace(CONTRACT, assumptions=frozenset({"user.extra-trust/v1"})),
        replace(CONTRACT, assumptions=CONTRACT.assumptions | {"user.extra-trust/v1"}),
        replace(CONTRACT, correspondence_relation="user.other-relation/v1"),
        replace(CONTRACT, correspondence_status="validated"),
        replace(CONTRACT, correspondence_status="unverified"),
    ],
)
@pytest.mark.parametrize("allow_fallback", [False, True])
def test_priority_explicit_and_permitted_fallback_cannot_relax_result_contract(
    contract, allow_fallback
):
    descriptor = adapter(
        priority=999,
        profiles=frozenset({PROFILE, contract.profile}),
        methods=frozenset({"deductive_proof", contract.method}),
        result_contracts=(contract,),
    )
    result = plan(
        descriptor,
        PlannerPolicy(selected_adapter="fixture", allow_fallback=allow_fallback),
        request=constrained_request(),
    )
    assert result.selected is None
    assert "unsupported_result_contract" in reasons(result)


def test_no_contract_is_not_a_wildcard_and_unconstrained_legacy_payload_is_unchanged():
    result = plan(request=constrained_request())
    assert result.selected is None
    assert "result_contract_not_declared" in reasons(result)
    legacy = plan(adapter(result_contracts=(CONTRACT,)))
    assert legacy.selected is not None
    assert legacy.selected.result_contract is None
    assert "result_contract" not in legacy.to_dict()["request"]
    assert "result_contract" not in legacy.to_dict()["selected"]
    assert legacy.to_dict() == plan().to_dict()
    assert legacy.to_dict()["schema_version"] == "mumei.verification-plan/v1"


def test_contract_fields_cannot_be_borrowed_from_different_offers_or_adapters():
    wrong_relation = replace(CONTRACT, correspondence_relation="user.other/v1")
    wrong_assumptions = replace(CONTRACT, assumptions=frozenset())
    for offers in [
        (wrong_relation, wrong_assumptions),
        (wrong_assumptions, wrong_relation),
    ]:
        result = plan(adapter(result_contracts=offers), request=constrained_request())
        assert result.selected is None
    registry = AdapterRegistry()
    registry.register(adapter("a", result_contracts=(wrong_relation,)))
    registry.register(adapter("b", result_contracts=(wrong_assumptions,)))
    result = registry.plan(
        constrained_request(), PlannerPolicy(), (observed("a"), observed("b"))
    )
    assert result.selected is None


@pytest.mark.parametrize("allow_fallback", [False, True])
def test_explicit_missing_contract_falls_back_only_to_an_exact_offer_when_allowed(
    allow_fallback,
):
    registry = AdapterRegistry()
    registry.register(adapter("selected", priority=30))
    registry.register(
        adapter(
            "weaker",
            priority=20,
            result_contracts=(replace(CONTRACT, correspondence_status="unverified"),),
        )
    )
    registry.register(adapter("exact", priority=10, result_contracts=(CONTRACT,)))
    result = registry.plan(
        constrained_request(),
        PlannerPolicy(selected_adapter="selected", allow_fallback=allow_fallback),
        tuple(observed(x) for x in ["selected", "weaker", "exact"]),
    )
    assert result.request.result_contract == CONTRACT
    if allow_fallback:
        assert result.selected.adapter_id == "exact"
        assert result.fallback_from == "selected"
        assert result.selected.result_contract == CONTRACT
    else:
        assert result.selected is None
        assert result.fallback_from is None
    assert reasons(result, "weaker") == ("unsupported_result_contract",)


@pytest.mark.parametrize("scope", ["bounded", "finite"])
def test_bounds_are_complete_exact_identifiers_not_an_inferred_numeric_order(scope):
    contract = replace(
        CONTRACT, scope=scope, bounds=frozenset({"user.depth-8/v1", "user.width-64/v1"})
    )
    for bounds in [
        frozenset({"user.depth-4/v1", "user.width-64/v1"}),
        frozenset({"user.depth-16/v1", "user.width-64/v1"}),
        frozenset({"user.depth-8/v1"}),
        contract.bounds | {"user.other/v1"},
    ]:
        result = plan(
            adapter(result_contracts=(replace(contract, bounds=bounds),)),
            request=constrained_request(contract),
        )
        assert result.selected is None
    assert (
        plan(
            adapter(result_contracts=(contract,)), request=constrained_request(contract)
        ).selected
        is not None
    )


def test_contract_replacement_recomputes_eligibility_and_old_plans_remain_immutable():
    registry = AdapterRegistry()
    registry.register(adapter(result_contracts=(CONTRACT,)))
    initial = registry.plan(constrained_request(), PlannerPolicy(), (observed(),))
    registry.register(adapter(result_contracts=()), replace=True)
    assert (
        registry.plan(constrained_request(), PlannerPolicy(), (observed(),)).selected
        is None
    )
    assert initial.selected.result_contract == CONTRACT
    with pytest.raises(AttributeError):
        initial.selected.result_contract.scope = "identity_only"
    registry.register(adapter(result_contracts=(CONTRACT,)), replace=True)
    assert (
        registry.plan(constrained_request(), PlannerPolicy(), (observed(),)).selected
        is not None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "FAKE_PRIVATE"},
        {"scope": []},
        {"scope": None},
        {"method": "FAKE_PRIVATE"},
        {"method": []},
        {"profile": "https://FAKE_PRIVATE.invalid/?secret=FAKE"},
        {"bounds": []},
        {"assumptions": {"FAKE_PRIVATE"}},
        {"assumptions": frozenset({"https://FAKE_PRIVATE.invalid"})},
        {"bounds": frozenset({"user.limit/v1"})},
        {"scope": "bounded"},
        {"scope": "finite"},
        {"correspondence_status": "FAKE_PRIVATE"},
        {"correspondence_status": []},
        {"correspondence_relation": "/FAKE_PRIVATE"},
    ],
)
def test_invalid_contracts_fail_with_static_non_echoing_errors(changes):
    with pytest.raises(ValueError) as error:
        replace(CONTRACT, **changes)
    assert "FAKE_PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"result_contracts": [CONTRACT]},
        {"result_contracts": ("FAKE_PRIVATE",)},
        {"result_contracts": (CONTRACT, CONTRACT)},
        {"result_contracts": (replace(CONTRACT, profile="user.other/v1"),)},
        {"result_contracts": (replace(CONTRACT, method="abstract_interpretation"),)},
    ],
)
def test_descriptor_contracts_must_be_unique_immutable_and_inside_declared_capabilities(
    changes,
):
    with pytest.raises(ValueError) as error:
        adapter(**changes)
    assert "FAKE_PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "contract",
    [
        "FAKE_PRIVATE",
        replace(CONTRACT, profile="user.other/v1"),
        replace(CONTRACT, method="abstract_interpretation"),
    ],
)
def test_request_contract_profile_and_method_cannot_disagree_with_route(contract):
    with pytest.raises(ValueError) as error:
        replace(REQUEST, result_contract=contract)
    assert "FAKE_PRIVATE" not in str(error.value)


def test_deterministic_contract_serialization_uses_only_approved_labels_and_no_io(
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        pytest.fail("contract planning must remain metadata-only")

    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    contract = replace(CONTRACT, assumptions=frozenset({"user.z/v1", "user.a/v1"}))
    result = plan(
        adapter(result_contracts=(contract,)), request=constrained_request(contract)
    )
    data = result.to_dict()
    assert data["selected"]["result_contract"]["assumptions"] == [
        "user.a/v1",
        "user.z/v1",
    ]
    assert data["request"]["result_contract"] == data["selected"]["result_contract"]
    assert json.dumps(data) == json.dumps(result.to_dict())
