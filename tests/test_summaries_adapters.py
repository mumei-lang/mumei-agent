"""Declared adapter descriptors for the summary-derivation routes."""

import hashlib
import json

import pytest

from agent.adapter_probe import AdapterProbeHistory
from agent.summaries_adapters import (
    SUMMARY_DERIVATION,
    go_summaries_adapter,
    rust_summaries_adapter,
    plan_summary_route,
    summary_descriptors,
    summary_registry,
    summary_requirements,
)
from agent.go_interprocedural import PROFILE as GO_SUMMARY_PROFILE
from agent.rust_interprocedural import PROFILE as RUST_SUMMARY_PROFILE
from agent.verification_planner import (
    SOURCE_INPUT_FORMAT,
    AdapterRegistry,
    METHODS,
    PlannerPolicy,
    RuntimeObservation,
)


def test_summary_derivation_is_a_declared_method():
    assert SUMMARY_DERIVATION in METHODS


def test_go_summaries_descriptor_is_valid_and_complete():
    descriptor = go_summaries_adapter()
    assert descriptor.adapter_id == "agent.go-summaries"
    assert descriptor.methods == frozenset({SUMMARY_DERIVATION})
    assert descriptor.profiles == frozenset({GO_SUMMARY_PROFILE})
    assert descriptor.input_formats == frozenset({SOURCE_INPUT_FORMAT})
    assert descriptor.required_permissions == frozenset(
        {"filesystem.read", "process.spawn"}
    )
    assert descriptor.probe_argv is not None
    contract = descriptor.result_contracts[0]
    assert contract.profile == GO_SUMMARY_PROFILE
    assert contract.method == SUMMARY_DERIVATION
    assert contract.scope == "bounded"
    assert contract.correspondence_status == "assumed"


def test_summary_requirements_match_the_descriptor():
    request = summary_requirements(GO_SUMMARY_PROFILE)
    descriptor = go_summaries_adapter()
    assert request.input_format == SOURCE_INPUT_FORMAT
    assert request.result_contract in descriptor.result_contracts


def test_plan_selects_the_adapter_when_observed_available():
    registry = AdapterRegistry()
    descriptor = go_summaries_adapter()
    registry.register(descriptor)
    result = registry.plan(
        summary_requirements(GO_SUMMARY_PROFILE),
        PlannerPolicy(
            allowed_permissions=frozenset(
                {"filesystem.read", "process.spawn"}
            )
        ),
        (
            RuntimeObservation(
                "agent.go-summaries", "available", "1.0.0"
            ),
        ),
    )
    assert result.selected is not None
    assert result.selected.adapter_id == "agent.go-summaries"


def test_plan_excludes_the_adapter_when_unobserved():
    registry = AdapterRegistry()
    registry.register(go_summaries_adapter())
    result = registry.plan(
        summary_requirements(GO_SUMMARY_PROFILE),
        PlannerPolicy(),
        (),
    )
    assert result.selected is None
    decision = result.decisions[0]
    assert "availability_unknown" in decision.reasons
    assert "permission_requirements_not_declared" not in decision.reasons


def test_prepare_source_binds_the_summary_request():
    registry = AdapterRegistry()
    registry.register(go_summaries_adapter())
    prepared = registry.prepare_source(
        summary_requirements(GO_SUMMARY_PROFILE),
        PlannerPolicy(
            allowed_permissions=frozenset(
                {"filesystem.read", "process.spawn"}
            )
        ),
        (RuntimeObservation("agent.go-summaries", "available", "1.0.0"),),
        b"package main\n",
        hashlib.sha256(b"package main\n").hexdigest(),
    )
    assert prepared.plan.request.method == SUMMARY_DERIVATION
    assert prepared.source == b"package main\n"


def test_requirements_reject_foreign_profile():
    with pytest.raises(ValueError):
        summary_requirements("not a label!")


# --- probe-wired planning ----------------------------------------------------

_PERMISSIONS = frozenset({"filesystem.read", "process.spawn"})


def test_registry_holds_every_descriptor():
    registry = summary_registry()
    result = registry.plan(
        summary_requirements(GO_SUMMARY_PROFILE),
        PlannerPolicy(allowed_permissions=_PERMISSIONS),
        (RuntimeObservation("agent.go-summaries", "available", "1.0.0"),),
    )
    assert result.selected.adapter_id == "agent.go-summaries"
    assert [d.adapter_id for d in summary_descriptors()] == [
        "agent.go-summaries",
        "agent.rust-summaries",
    ]


def test_rust_summaries_descriptor_is_valid_and_in_process():
    descriptor = rust_summaries_adapter()
    assert descriptor.adapter_id == "agent.rust-summaries"
    assert descriptor.methods == frozenset({SUMMARY_DERIVATION})
    assert descriptor.profiles == frozenset({RUST_SUMMARY_PROFILE})
    # In-process tree-sitter derivation declares no spawn permission —
    # the probe_argv spawn belongs to the probe boundary itself.
    assert descriptor.required_permissions == frozenset(
        {"filesystem.read"}
    )
    assert descriptor.probe_argv is not None


def test_plan_summary_route_probes_and_selects():
    result = plan_summary_route(
        GO_SUMMARY_PROFILE,
        PlannerPolicy(allowed_permissions=_PERMISSIONS),
        stamp=7,
        tool_version="1.0.0",
    )
    assert result.plan.selected is not None
    assert result.plan.selected.adapter_id == "agent.go-summaries"
    observation = result.observations[0]
    assert observation.availability == "available"
    assert observation.tool_version == "1.0.0"
    history = result.histories[0]
    assert history.adapter_id == "agent.go-summaries"
    assert history.attempt_count >= 1


def test_plan_summary_route_stays_excluded_without_version():
    result = plan_summary_route(
        GO_SUMMARY_PROFILE,
        PlannerPolicy(allowed_permissions=_PERMISSIONS),
        stamp=7,
    )
    assert result.plan.selected is None
    decision = result.plan.decisions[0]
    assert "tool_version_unknown" in decision.reasons


def test_plan_summary_route_never_probes_structural_exclusion():
    result = plan_summary_route(
        GO_SUMMARY_PROFILE,
        PlannerPolicy(
            allowed_permissions=_PERMISSIONS,
            allowed_locations=frozenset({"remote"}),
        ),
        stamp=7,
    )
    assert result.plan.selected is None
    assert result.observations == ()
    assert result.histories == ()


def test_probe_history_record_round_trips():
    result = plan_summary_route(
        GO_SUMMARY_PROFILE,
        PlannerPolicy(allowed_permissions=_PERMISSIONS),
        stamp=7,
        tool_version="1.0.0",
    )
    history = result.histories[0]
    data = history.to_dict()
    assert data["schema_version"] == "mumei.adapter-probe-history/v1"
    assert data["adapter_id"] == history.adapter_id
    restored = AdapterProbeHistory.from_dict(data)
    assert restored == history


@pytest.mark.parametrize(
    "record",
    [
        {"schema_version": "other/v9"},
        {"schema_version": "mumei.adapter-probe-history/v1"},
        {
            "schema_version": "mumei.adapter-probe-history/v1",
            "adapter_id": "agent.go-summaries",
            "command_fingerprint": "x" * 64,
            "outcomes": "not-a-list",
        },
    ],
)
def test_probe_history_record_rejects_bad_declarations(record):
    with pytest.raises(ValueError):
        AdapterProbeHistory.from_dict(record)


def _plan_args(tmp_path, histories=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        profile=GO_SUMMARY_PROFILE,
        stamp=11,
        tool_version="1.0.0",
        rounds=1,
        max_parallel=1,
        histories=histories,
    )


def test_summaries_plan_route_emits_report(capsys, tmp_path):
    from agent.summaries_adapters import PLAN_PROFILE, main_plan

    assert main_plan(_plan_args(tmp_path)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == PLAN_PROFILE
    assert report["profile"] == GO_SUMMARY_PROFILE
    assert report["plan"]["selected"]["adapter_id"] == "agent.go-summaries"
    assert report["observations"][0]["availability"] == "available"
    history = report["histories"][0]
    assert history["adapter_id"] == "agent.go-summaries"
    assert history["outcomes"]


def test_summaries_plan_route_resumes_declared_histories(capsys, tmp_path):
    from agent.summaries_adapters import main_plan

    assert main_plan(_plan_args(tmp_path)) == 0
    first = json.loads(capsys.readouterr().out)
    histories_file = tmp_path / "histories.json"
    histories_file.write_text(json.dumps(first["histories"]))
    assert main_plan(_plan_args(tmp_path, histories=str(histories_file))) == 0
    second = json.loads(capsys.readouterr().out)
    first_count = len(first["histories"][0]["outcomes"])
    assert len(second["histories"][0]["outcomes"]) == first_count + 1
