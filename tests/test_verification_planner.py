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
    SettingSpec,
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


SPECS = (
    SettingSpec("cache", "boolean", False),
    SettingSpec("rounds", "integer", 3, minimum=1, maximum=10),
    SettingSpec(
        "strategy", "choice", "balanced", choices=frozenset({"balanced", "eager"})
    ),
)


def configured(**changes):
    return adapter(setting_specs=SPECS, **changes)


def configured_policy(values=(), **changes):
    return PlannerPolicy(adapter_settings=(("fixture", values),), **changes)


def test_setting_defaults_and_overrides_resolve_only_approved_effective_projection():
    defaults = plan(configured()).selected
    explicit = plan(configured(), configured_policy((("rounds", 3),))).selected
    assert dict(defaults.adapter_settings) == {
        "cache": False,
        "rounds": 3,
        "strategy": "balanced",
    }
    assert defaults.configuration_fingerprint == explicit.configuration_fingerprint
    assert len(defaults.configuration_fingerprint) == 64
    result = plan(configured(), configured_policy((("rounds", 8), ("cache", True))))
    data = result.to_dict()
    assert data["selected"]["adapter_settings"] == {
        "cache": True,
        "rounds": 8,
        "strategy": "balanced",
    }
    assert (
        data["selected"]["configuration_fingerprint"]
        != defaults.configuration_fingerprint
    )
    assert "adapter_settings" not in data["policy"]
    assert json.loads(json.dumps(data))["selected"] == data["selected"]


@pytest.mark.parametrize("value", [-10, 0, 10])
def test_declared_integer_endpoints_and_negative_values_are_not_reinterpreted(value):
    spec = SettingSpec("offset", "integer", value, minimum=-10, maximum=10)
    assert plan(adapter(setting_specs=(spec,))).selected.adapter_settings == (
        ("offset", value),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "text"},
        {"kind": []},
        {"default": "true"},
        {"default": 1},
        {"minimum": 0},
        {"choices": frozenset({"yes"})},
        {"choices": []},
    ],
)
def test_invalid_boolean_schema_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(SPECS[0], **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"minimum": None},
        {"maximum": None},
        {"minimum": True},
        {"maximum": 1.0},
        {"minimum": 11},
        {"minimum": -(2**63) - 1},
        {"maximum": 2**63},
        {"default": True},
        {"default": 0},
        {"default": 11},
        {"default": "3"},
        {"choices": frozenset({"small"})},
    ],
)
def test_invalid_integer_schema_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(SPECS[1], **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"choices": frozenset()},
        {"choices": {"balanced"}},
        {"choices": frozenset({1})},
        {"choices": frozenset({"x" * 65})},
        {"choices": frozenset({f"c{i}" for i in range(33)})},
        {"default": "missing"},
        {"default": True},
        {"minimum": 0},
    ],
)
def test_invalid_choice_schema_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(SPECS[2], **changes)


@pytest.mark.parametrize(
    "name",
    [
        "api_key",
        "token",
        "secret",
        "password",
        "credentials",
        "auth",
        "authorization",
        "endpoint",
        "url",
        "path",
        "command",
        "argv",
        "args",
        "env",
        "header",
        "executable",
        "",
        "UpperCase",
        "dotted.name",
        "hyphen-name",
        "x" * 65,
    ],
)
def test_obvious_sensitive_or_invocation_channels_and_invalid_names_are_rejected(name):
    with pytest.raises(ValueError):
        replace(SPECS[0], name=name)


@pytest.mark.parametrize(
    "specs",
    [
        list(SPECS),
        ("bad",),
        (SPECS[0], SPECS[0]),
        tuple(SettingSpec(f"s{i}", "boolean", False) for i in range(33)),
    ],
)
def test_descriptor_schemas_are_immutable_unique_and_bounded(specs):
    with pytest.raises(ValueError):
        adapter(setting_specs=specs)


@pytest.mark.parametrize(
    "settings",
    [
        [],
        ([],),
        (("fixture", []),),
        (("fixture", ([],)),),
        (("fixture", (("cache", True, False),)),),
        (("fixture", (("cache", True), ("cache", False))),),
        (("fixture", ()), ("fixture", ())),
        (("fixture", (("cache", {}),)),),
        (("fixture", (("api_key", "unused"),)),),
        (("fixture", tuple((f"s{i}", True) for i in range(33))),),
    ],
)
def test_malformed_override_collections_are_rejected(settings):
    with pytest.raises(ValueError):
        PlannerPolicy(adapter_settings=settings)


@pytest.mark.parametrize(
    "values",
    [
        (("unknown", True),),
        (("cache", 1),),
        (("cache", "true"),),
        (("rounds", True),),
        (("rounds", 0),),
        (("rounds", 11),),
        (("rounds", "3"),),
        (("strategy", "other"),),
        (("strategy", True),),
    ],
)
def test_unknown_or_invalid_override_never_becomes_a_route_or_fallback(values):
    with pytest.raises(ValueError):
        plan(configured(), configured_policy(values, allow_fallback=True))


def test_unknown_adapter_and_legacy_undeclared_option_are_not_wildcards():
    with pytest.raises(ValueError):
        plan(configured(), PlannerPolicy(adapter_settings=(("unknown", ()),)))
    with pytest.raises(ValueError):
        plan(adapter(), configured_policy((("cache", True),)))


def test_invalid_disabled_adapter_setting_is_not_silently_ignored():
    with pytest.raises(ValueError):
        plan(configured(enabled=False), configured_policy((("rounds", 0),)))


def test_fallback_resolves_its_own_settings_without_borrowing_from_selected_adapter():
    registry = AdapterRegistry()
    registry.register(configured(enabled=False))
    registry.register(adapter("other", setting_specs=(replace(SPECS[1], default=6),)))
    policy = configured_policy(
        (("rounds", 9),), selected_adapter="fixture", allow_fallback=True
    )
    observations = (observed(), observed("other"))
    result = registry.plan(REQUEST, policy, observations)
    assert result.fallback_from == "fixture"
    assert result.selected.adapter_id == "other"
    assert result.selected.adapter_settings == (("rounds", 6),)
    overridden = replace(
        policy,
        adapter_settings=policy.adapter_settings + (("other", (("rounds", 7),)),),
    )
    assert registry.plan(
        REQUEST, overridden, observations
    ).selected.adapter_settings == (("rounds", 7),)
    assert (
        registry.plan(
            REQUEST, replace(policy, allow_fallback=False), observations
        ).selected
        is None
    )


def test_settings_do_not_weaken_exact_result_contract_requirement():
    registry = AdapterRegistry()
    registry.register(
        configured(
            result_contracts=(replace(CONTRACT, correspondence_status="unverified"),)
        )
    )
    registry.register(
        adapter("other", setting_specs=SPECS, result_contracts=(CONTRACT,))
    )
    result = registry.plan(
        constrained_request(),
        configured_policy(selected_adapter="fixture", allow_fallback=True),
        (observed(), observed("other")),
    )
    assert result.selected.adapter_id == "other"
    assert result.selected.result_contract == CONTRACT


@pytest.mark.parametrize(
    "changes,observation,policy",
    [
        ({"enabled": False}, observed(), PlannerPolicy()),
        ({"protocol_version": "other/v2"}, observed(), PlannerPolicy()),
        ({"location": "remote"}, observed(), PlannerPolicy()),
        ({}, observed(availability="missing"), PlannerPolicy()),
        ({}, observed(), PlannerPolicy(tool_version_pins=(("fixture", "4.12.0"),))),
        ({}, observed(), PlannerPolicy(disabled_adapters=frozenset({"fixture"}))),
    ],
)
def test_configured_candidates_still_obey_all_preflight_filters(
    changes, observation, policy
):
    assert plan(configured(**changes), policy, observation).selected is None


def test_fingerprint_is_independent_of_schema_choice_and_override_order():
    a = plan(configured(), configured_policy((("rounds", 4), ("cache", True))))
    b = plan(
        adapter(setting_specs=tuple(reversed(SPECS))),
        configured_policy((("cache", True), ("rounds", 4))),
    )
    assert a.selected.configuration_fingerprint == b.selected.configuration_fingerprint
    assert a.to_dict()["selected"] == b.to_dict()["selected"]


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "default",
        "choice",
        "adapter",
        "tool",
        "identity",
        "location",
        "budget",
        "profile",
        "contract",
    ],
)
def test_fingerprint_binds_approved_schema_effective_settings_and_selected_context(
    change,
):
    descriptor, policy, observation, request = (
        configured(),
        PlannerPolicy(),
        observed(),
        REQUEST,
    )
    original = plan(
        descriptor, policy, observation, request
    ).selected.configuration_fingerprint
    if change == "schema":
        descriptor = replace(
            descriptor,
            setting_specs=(replace(SPECS[1], maximum=11), SPECS[0], SPECS[2]),
        )
    elif change == "default":
        descriptor = replace(
            descriptor,
            setting_specs=(replace(SPECS[0], default=True), SPECS[1], SPECS[2]),
        )
    elif change == "choice":
        descriptor = replace(
            descriptor,
            setting_specs=(
                *SPECS[:2],
                replace(SPECS[2], choices=SPECS[2].choices | {"lazy"}),
            ),
        )
    elif change == "adapter":
        descriptor = replace(descriptor, adapter_version="1.0.1")
    elif change == "tool":
        observation = replace(observation, tool_version="4.13.1")
    elif change == "identity":
        descriptor = replace(descriptor, adapter_id="other")
        observation = observed("other")
    elif change == "location":
        descriptor = replace(descriptor, location="container")
        policy = replace(policy, allowed_locations=frozenset({"container"}))
    elif change == "budget":
        policy = replace(policy, timeout_ms=100)
    elif change == "profile":
        request = replace(request, profile="user.other/v1")
        descriptor = replace(descriptor, profiles=frozenset({request.profile}))
    else:
        request = constrained_request()
        descriptor = replace(descriptor, result_contracts=(CONTRACT,))
    changed = plan(
        descriptor, policy, observation, request
    ).selected.configuration_fingerprint
    assert changed != original


def test_fingerprint_uses_effective_not_requested_budget():
    a = plan(configured(max_timeout_ms=100), PlannerPolicy(timeout_ms=500))
    b = plan(configured(max_timeout_ms=100), PlannerPolicy(timeout_ms=1000))
    assert a.selected.configuration_fingerprint == b.selected.configuration_fingerprint


def test_schema_replacement_invalidates_old_override_instead_of_silently_defaulting():
    registry = AdapterRegistry()
    registry.register(configured())
    policy = configured_policy((("rounds", 8),))
    assert registry.plan(REQUEST, policy, (observed(),)).selected is not None
    registry.register(
        adapter(setting_specs=(replace(SPECS[1], maximum=5),)), replace=True
    )
    with pytest.raises(ValueError):
        registry.plan(REQUEST, policy, (observed(),))


def test_legacy_json_has_no_silent_configuration_fields():
    data = plan().to_dict()
    assert "configuration_fingerprint" not in data["selected"]
    assert "adapter_settings" not in data["selected"]
    assert plan().selected.configuration_fingerprint is None


def test_rejected_raw_value_is_neither_logged_serialized_fingerprinted_nor_repr_echoed(
    monkeypatch, capsys
):
    sentinel = "FAKE_SETTING_DO_NOT_ECHO"

    def forbidden(*args, **kwargs):
        pytest.fail("invalid setting must not reach the fingerprint")

    monkeypatch.setattr("agent.verification_planner.hashlib.sha256", forbidden)
    policy = configured_policy((("strategy", sentinel),))
    assert sentinel not in repr(policy)
    with pytest.raises(ValueError) as error:
        plan(configured(), policy)
    assert sentinel not in str(error.value)
    output = capsys.readouterr()
    assert sentinel not in output.out + output.err


def test_settings_planning_is_pure_and_never_promotes_approval(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("settings planning must remain metadata-only")

    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    data = plan(configured(), configured_policy((("cache", True),))).to_dict()
    for key in (
        "proved",
        "verified",
        "grade",
        "environment",
        "command",
        "acceptance",
        "permission",
    ):
        assert f'"{key}"' not in json.dumps(data)
