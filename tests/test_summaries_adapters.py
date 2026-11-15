"""Declared adapter descriptors for the summary-derivation routes."""

import hashlib
import json

import pytest

from agent.adapter_probe import AdapterProbeHistory
from agent.ts_interprocedural import PROFILE as TS_SUMMARY_PROFILE
from agent.sol_interprocedural import PROFILE as SOL_SUMMARY_PROFILE
from agent.summaries_adapters import (
    SUMMARY_DERIVATION,
    go_summaries_adapter,
    rust_summaries_adapter,
    plan_summary_route,
    summary_descriptors,
    sol_summaries_adapter,
    summary_registry,
    ts_summaries_adapter,
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
        "agent.sol-summaries",
        "agent.ts-summaries",
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


def test_ts_summaries_descriptor_is_valid_and_in_process():
    descriptor = ts_summaries_adapter()
    assert descriptor.adapter_id == "agent.ts-summaries"
    assert TS_SUMMARY_PROFILE in descriptor.profiles
    assert descriptor.required_permissions == frozenset({"filesystem.read"})
    registry = summary_registry()
    result = registry.plan(
        summary_requirements(TS_SUMMARY_PROFILE),
        PlannerPolicy(allowed_permissions=_PERMISSIONS),
        (
            RuntimeObservation(
                "agent.ts-summaries", "available", "1.0.0"
            ),
        ),
    )
    assert result.selected.adapter_id == "agent.ts-summaries"


def test_sol_summaries_descriptor_is_valid_and_in_process():
    descriptor = sol_summaries_adapter()
    assert descriptor.adapter_id == "agent.sol-summaries"
    assert SOL_SUMMARY_PROFILE in descriptor.profiles
    assert descriptor.required_permissions == frozenset({"filesystem.read"})
    registry = summary_registry()
    result = registry.plan(
        summary_requirements(SOL_SUMMARY_PROFILE),
        PlannerPolicy(allowed_permissions=_PERMISSIONS),
        (
            RuntimeObservation(
                "agent.sol-summaries", "available", "1.0.0"
            ),
        ),
    )
    assert result.selected.adapter_id == "agent.sol-summaries"


def test_mcp_summaries_plan_selects_under_declared_pin(tmp_path):
    from agent import mcp_server

    out = json.loads(
        mcp_server.summaries_plan(
            GO_SUMMARY_PROFILE, 11, tool_version="1.0.0"
        )
    )
    assert out["status"] == "ok"
    assert out["schema_version"] == "mumei.summaries-plan/v1"
    assert out["plan"]["selected"]["adapter_id"] == "agent.go-summaries"
    assert out["histories"][0]["schema_version"] == (
        "mumei.adapter-probe-history/v1"
    )


def test_mcp_summaries_plan_resumes_histories(tmp_path):
    from agent import mcp_server

    first = json.loads(
        mcp_server.summaries_plan(
            GO_SUMMARY_PROFILE, 11, tool_version="1.0.0"
        )
    )
    histories_file = tmp_path / "histories.json"
    histories_file.write_text(json.dumps(first["histories"]))
    second = json.loads(
        mcp_server.summaries_plan(
            GO_SUMMARY_PROFILE,
            11,
            tool_version="1.0.0",
            histories_path=str(histories_file),
        )
    )
    hist = [
        h for h in second["histories"]
        if h["adapter_id"] == "agent.go-summaries"
    ]
    assert [o["attempt_number"] for o in hist[0]["outcomes"]] == [1, 2]


def test_mcp_summaries_plan_unpinned_selects_nothing():
    from agent import mcp_server

    out = json.loads(mcp_server.summaries_plan(GO_SUMMARY_PROFILE, 11))
    assert out["status"] == "ok"
    assert out["plan"]["selected"] is None
    go = [
        d for d in out["plan"]["decisions"]
        if d["adapter_id"] == "agent.go-summaries"
    ]
    assert "tool_version_unknown" in go[0]["reasons"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"profile": ""},
        {"profile": "a\nb"},
        {"profile": GO_SUMMARY_PROFILE, "stamp": 0},
        {"profile": GO_SUMMARY_PROFILE, "stamp": "11"},
        {"profile": GO_SUMMARY_PROFILE, "stamp": 11, "tool_version": "a\nb"},
        {"profile": GO_SUMMARY_PROFILE, "stamp": 11, "rounds": 0},
        {"profile": GO_SUMMARY_PROFILE, "stamp": 11, "max_parallel": 0},
        {
            "profile": GO_SUMMARY_PROFILE,
            "stamp": 11,
            "histories_path": "bad\npath",
        },
    ],
)
def test_mcp_summaries_plan_rejects_bad_declarations(kwargs):
    from agent import mcp_server

    kwargs.setdefault("profile", GO_SUMMARY_PROFILE)
    kwargs.setdefault("stamp", 11)
    out = json.loads(mcp_server.summaries_plan(**kwargs))
    assert out["status"] == "error"


def test_mcp_summaries_plan_redacts_histories_path(tmp_path):
    from agent import mcp_server

    bad = tmp_path / "unique-checkout-dir" / "histories.json"
    bad.mkdir(parents=True)
    out = json.loads(
        mcp_server.summaries_plan(
            GO_SUMMARY_PROFILE, 11, histories_path=str(bad)
        )
    )
    assert out["status"] == "error"
    assert str(bad) not in out["error"]
    assert bad.name in out["error"]


def test_mcp_summaries_plan_reports_malformed_histories(tmp_path):
    from agent import mcp_server

    bad = tmp_path / "histories.json"
    bad.write_text("{not json")
    out = json.loads(
        mcp_server.summaries_plan(
            GO_SUMMARY_PROFILE, 11, histories_path=str(bad)
        )
    )
    assert out["status"] == "error"


def test_mcp_ts_summaries_emits_manifest(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    from agent import mcp_server

    src = tmp_path / "f.ts"
    src.write_text("function f(x: number): number { return x; }")
    out = json.loads(mcp_server.ts_summaries(str(src)))
    assert out["status"] == "ok"
    assert out["manifest"]["schema_version"] == (
        "mumei.ts-scalar-parameter-deps/v1"
    )
    assert out["manifest"]["functions"][0]["name"] == "f"


def test_mcp_rust_summaries_emits_manifest(tmp_path):
    from agent import mcp_server

    src = tmp_path / "f.rs"
    src.write_text("fn f(x: u64) -> u64 { x }")
    out = json.loads(mcp_server.rust_summaries(str(src)))
    assert out["status"] == "ok"
    assert out["manifest"]["schema_version"] == (
        "mumei.rust-scalar-parameter-deps/v1"
    )


def test_mcp_sol_summaries_emits_manifest(tmp_path):
    from agent import mcp_server

    src = tmp_path / "c.sol"
    src.write_text(
        "contract C { function f(uint x) public returns (uint) "
        "{ return x; } }"
    )
    out = json.loads(mcp_server.sol_summaries(str(src)))
    assert out["status"] == "ok"
    assert out["manifest"]["schema_version"] == (
        "mumei.sol-scalar-parameter-deps/v1"
    )


@pytest.mark.parametrize("tool", ["ts_summaries", "rust_summaries", "sol_summaries"])
def test_mcp_summaries_tools_validate_source_path(tmp_path, tool):
    from agent import mcp_server

    fn = getattr(mcp_server, tool)
    assert json.loads(fn(""))["status"] == "error"
    assert json.loads(fn("a\nb"))["status"] == "error"
    assert json.loads(fn(str(tmp_path / "missing.src")))["status"] == "error"


@pytest.mark.parametrize("tool", ["ts_summaries", "rust_summaries"])
def test_mcp_summaries_tools_reject_oversize(tmp_path, tool):
    pytest.importorskip("tree_sitter_typescript") if tool == "ts_summaries" else None
    from agent import mcp_server

    big = tmp_path / "big.src"
    big.write_bytes(b"x" * (64 * 1024 + 1))
    out = json.loads(getattr(mcp_server, tool)(str(big)))
    assert out["status"] == "error"
    assert str(big) not in out["error"]


def test_mcp_ts_summaries_check_reusable(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    from agent import mcp_server
    import agent.ts_interprocedural as ts

    src = tmp_path / "f.ts"
    src.write_text("function f(x: number): number { return x; }")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            ts.summarize_typescript(
                "function f(x: number): number { return x; }"
            ).to_dict()
        )
    )
    out = json.loads(
        mcp_server.ts_summaries_check(str(src), str(manifest))
    )
    assert out["status"] == "ok"
    check = out["check"]
    assert check["schema_version"] == "mumei.ts-summary-check/v1"
    assert check["context_match"] is True
    assert check["reusable"] == ["f"]
    assert check["stale"] == [] and check["missing"] == []


def test_mcp_ts_summaries_check_marks_stale_and_missing(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    from agent import mcp_server
    import agent.ts_interprocedural as ts

    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            ts.summarize_typescript(
                "function f(x: number): number { return x; }\n"
                "function g(x: number): number { return x; }"
            ).to_dict()
        )
    )
    src = tmp_path / "f.ts"
    src.write_text(
        "function f(y: number): number { return y; }"
    )
    out = json.loads(
        mcp_server.ts_summaries_check(str(src), str(manifest))
    )
    assert out["status"] == "ok"
    check = out["check"]
    assert check["context_match"] is False
    assert check["stale"] == ["f"]
    assert check["missing"] == ["g"]


def test_mcp_rust_summaries_check_reusable(tmp_path):
    from agent import mcp_server
    import agent.rust_interprocedural as rust

    src_text = "fn f(x: u64) -> u64 { x }"
    src = tmp_path / "f.rs"
    src.write_text(src_text)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(rust.summarize_rust(src_text).to_dict())
    )
    out = json.loads(
        mcp_server.rust_summaries_check(str(src), str(manifest))
    )
    assert out["status"] == "ok"
    assert out["check"]["context_match"] is True
    assert out["check"]["reusable"] == ["f"]


def test_mcp_sol_summaries_check_reusable(tmp_path):
    from agent import mcp_server
    import agent.sol_interprocedural as sol

    src_text = (
        "contract C { function f(uint x) public returns (uint) "
        "{ return x; } }"
    )
    src = tmp_path / "c.sol"
    src.write_text(src_text)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(src_text).to_dict())
    )
    out = json.loads(
        mcp_server.sol_summaries_check(str(src), str(manifest))
    )
    assert out["status"] == "ok"
    assert out["check"]["context_match"] is True


def test_mcp_ts_summaries_reuse_drops_missing(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    from agent import mcp_server
    import agent.ts_interprocedural as ts

    declared_set = ts.summarize_typescript(
        "function f(x: number): number { return x; }\n"
        "function g(x: number): number { return x; }"
    )
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(declared_set.to_dict()))
    src = tmp_path / "f.ts"
    src.write_text("function f(x: number): number { return x; }")
    out = json.loads(
        mcp_server.ts_summaries_reuse(str(src), str(manifest))
    )
    assert out["status"] == "ok"
    merged = out["manifest"]
    assert merged["schema_version"] == declared_set.to_dict()[
        "schema_version"
    ]
    assert merged["context_key"] != declared_set.context_key
    assert [f["name"] for f in merged["functions"]] == ["f"]
    assert merged["functions"][0] == declared_set.to_dict()[
        "functions"
    ][0]


def test_mcp_ts_summaries_reuse_derives_fresh_for_stale(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    from agent import mcp_server
    import agent.ts_interprocedural as ts

    declared_set = ts.summarize_typescript(
        "function f(x: number): number { return x; }"
    )
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(declared_set.to_dict()))
    src = tmp_path / "f.ts"
    src.write_text("function f(y: number): number { return y; }")
    out = json.loads(
        mcp_server.ts_summaries_reuse(str(src), str(manifest))
    )
    assert out["status"] == "ok"
    merged = out["manifest"]
    fresh = ts.summarize_typescript(src.read_text())
    assert merged["functions"][0] == fresh.to_dict()["functions"][0]
    assert merged["functions"][0] != declared_set.to_dict()[
        "functions"
    ][0]


def test_mcp_rust_summaries_reuse_merges(tmp_path):
    from agent import mcp_server
    import agent.rust_interprocedural as rust

    src_text = "fn f(x: u64) -> u64 { x }"
    src = tmp_path / "f.rs"
    src.write_text(src_text)
    declared_set = rust.summarize_rust(src_text)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(declared_set.to_dict()))
    out = json.loads(
        mcp_server.rust_summaries_reuse(str(src), str(manifest))
    )
    assert out["status"] == "ok"
    merged = out["manifest"]
    assert merged["context_key"] == declared_set.to_dict()[
        "context_key"
    ]
    assert [f["name"] for f in merged["functions"]] == ["f"]


def test_mcp_sol_summaries_reuse_merges(tmp_path):
    from agent import mcp_server
    import agent.sol_interprocedural as sol

    src_text = (
        "contract C { function f(uint x) public returns (uint) "
        "{ return x; } }"
    )
    src = tmp_path / "c.sol"
    src.write_text(src_text)
    declared_set = sol.summarize_solidity(src_text)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(declared_set.to_dict()))
    out = json.loads(
        mcp_server.sol_summaries_reuse(str(src), str(manifest))
    )
    assert out["status"] == "ok"
    assert [f["name"] for f in out["manifest"]["functions"]] == ["C.f"]


def test_mcp_ts_summaries_accept_accepts_declared(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    from agent import mcp_server
    import agent.ts_interprocedural as ts

    src_text = "function f(x: number): number { return x; }"
    src = tmp_path / "f.ts"
    src.write_text(src_text)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(ts.summarize_typescript(src_text).to_dict())
    )
    out = json.loads(
        mcp_server.ts_summaries_accept(str(src), str(manifest), "f")
    )
    assert out["status"] == "ok"
    accept = out["accept"]
    assert accept["schema_version"] == "mumei.ts-summary-accept/v1"
    assert accept["accepted"] is True
    assert accept["context_match"] is True
    assert accept["summary"]["name"] == "f"


def test_mcp_ts_summaries_accept_rejects_context_mismatch(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    from agent import mcp_server
    import agent.ts_interprocedural as ts

    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            ts.summarize_typescript(
                "function f(x: number): number { return x; }"
            ).to_dict()
        )
    )
    src = tmp_path / "f.ts"
    src.write_text(
        "function f(x: number): number { return x; }\n"
        "function g(x: number): number { return x; }"
    )
    out = json.loads(
        mcp_server.ts_summaries_accept(str(src), str(manifest), "f")
    )
    assert out["status"] == "ok"
    accept = out["accept"]
    assert accept["accepted"] is False
    assert accept["reason"] == "context_mismatch"


def test_mcp_rust_summaries_accept_bare_member_name(tmp_path):
    from agent import mcp_server
    import agent.rust_interprocedural as rust

    src_text = "fn f(x: u64) -> u64 { x }"
    src = tmp_path / "f.rs"
    src.write_text(src_text)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(rust.summarize_rust(src_text).to_dict())
    )
    out = json.loads(
        mcp_server.rust_summaries_accept(str(src), str(manifest), "f")
    )
    assert out["status"] == "ok"
    assert out["accept"]["accepted"] is True
    out = json.loads(
        mcp_server.rust_summaries_accept(
            str(src), str(manifest), "missing"
        )
    )
    assert out["accept"]["reason"] == "unknown_function"


def test_mcp_sol_summaries_accept_accepts_declared(tmp_path):
    from agent import mcp_server
    import agent.sol_interprocedural as sol

    src_text = (
        "contract C { function f(uint x) public returns (uint) "
        "{ return x; } }"
    )
    src = tmp_path / "c.sol"
    src.write_text(src_text)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(src_text).to_dict())
    )
    out = json.loads(
        mcp_server.sol_summaries_accept(str(src), str(manifest), "C.f")
    )
    assert out["status"] == "ok"
    assert out["accept"]["accepted"] is True
    assert out["accept"]["summary"]["name"] == "C.f"
    # Bare member name resolves via the fallback.
    out = json.loads(
        mcp_server.sol_summaries_accept(str(src), str(manifest), "f")
    )
    assert out["accept"]["accepted"] is True


@pytest.mark.parametrize(
    "tool", ["ts_summaries_accept", "rust_summaries_accept", "sol_summaries_accept"]
)
def test_mcp_summaries_accept_validates_function(tmp_path, tool):
    from agent import mcp_server

    src = tmp_path / "s.src"
    src.write_text("x")
    manifest = tmp_path / "m.json"
    manifest.write_text("{}")
    fn = getattr(mcp_server, tool)
    assert json.loads(fn(str(src), str(manifest), ""))[
        "status"
    ] == "error"
    assert json.loads(fn(str(src), str(manifest), "a\nb"))[
        "status"
    ] == "error"


def test_mcp_ts_summaries_attempt_selects_exited_run(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    from agent import mcp_server

    src = tmp_path / "f.ts"
    src.write_text("function f(x: number): number { return x; }")
    out = json.loads(
        mcp_server.ts_summaries_attempt(str(src), 60000)
    )
    assert out["status"] == "ok"
    report = out["report"]
    assert (
        report["schema_version"]
        == "mumei.ts-summaries-attempt-report/v1"
    )
    assert report["normalized"]["outcome"] == "exited"
    assert report["normalized"]["exit_code"] == 0
    assert "candidate" in report
    assert report["sequence"]["selected_result"] is not None


def test_mcp_rust_summaries_attempt_selects_exited_run(tmp_path):
    from agent import mcp_server

    src = tmp_path / "f.rs"
    src.write_text("fn f(x: u64) -> u64 { x }")
    out = json.loads(
        mcp_server.rust_summaries_attempt(str(src), 60000)
    )
    assert out["status"] == "ok"
    report = out["report"]
    assert (
        report["schema_version"]
        == "mumei.rust-summaries-attempt-report/v1"
    )
    assert report["normalized"]["outcome"] == "exited"
    assert report["normalized"]["exit_code"] == 0
    assert "candidate" in report


def test_mcp_sol_summaries_attempt_selects_exited_run(tmp_path):
    from agent import mcp_server

    src = tmp_path / "c.sol"
    src.write_text(
        "contract C { function f(uint x) public returns (uint) "
        "{ return x; } }"
    )
    out = json.loads(
        mcp_server.sol_summaries_attempt(str(src), 60000)
    )
    assert out["status"] == "ok"
    report = out["report"]
    assert (
        report["schema_version"]
        == "mumei.sol-summaries-attempt-report/v1"
    )
    assert report["normalized"]["outcome"] == "exited"
    assert report["normalized"]["exit_code"] == 0
    assert "candidate" in report


@pytest.mark.parametrize(
    "tool",
    [
        "ts_summaries_attempt",
        "rust_summaries_attempt",
        "sol_summaries_attempt",
    ],
)
def test_mcp_summaries_attempt_validates_declared_args(tmp_path, tool):
    from agent import mcp_server

    fn = getattr(mcp_server, tool)
    src = tmp_path / "s.src"
    src.write_text("x")
    assert json.loads(fn("", 60000))["status"] == "error"
    assert json.loads(fn("a\nb", 60000))["status"] == "error"
    out = json.loads(fn(str(tmp_path / "missing"), 60000))
    assert out["status"] == "error"
    assert str(tmp_path) not in out["error"]
    for bad_timeout in (0, -1, "x", 1.5):
        assert json.loads(fn(str(src), bad_timeout))[
            "status"
        ] == "error"
    for bad_bound in (-1, "x"):
        assert json.loads(fn(str(src), 60000, bad_bound))[
            "status"
        ] == "error"


@pytest.mark.parametrize(
    "tool",
    [
        "ts_summaries_check",
        "rust_summaries_check",
        "sol_summaries_check",
        "ts_summaries_reuse",
        "rust_summaries_reuse",
        "sol_summaries_reuse",
    ],
)
def test_mcp_summaries_check_validates_declared_paths(tmp_path, tool):
    from agent import mcp_server

    fn = getattr(mcp_server, tool)
    assert json.loads(fn("", "m.json"))["status"] == "error"
    assert json.loads(fn("a\nb", "m.json"))["status"] == "error"
    assert json.loads(fn("s.ts", "a\nb"))["status"] == "error"
    assert (
        json.loads(fn(str(tmp_path / "missing"), "m.json"))["status"]
        == "error"
    )
    src = tmp_path / "s.src"
    src.write_text("x")
    out = json.loads(fn(str(src), str(tmp_path / "missing.json")))
    assert out["status"] == "error"
    assert str(tmp_path) not in out["error"]


@pytest.mark.parametrize(
    "tool",
    [
        "ts_summaries_check",
        "rust_summaries_check",
        "sol_summaries_check",
        "ts_summaries_reuse",
        "rust_summaries_reuse",
        "sol_summaries_reuse",
    ],
)
def test_mcp_summaries_check_rejects_malformed_manifest(tmp_path, tool):
    from agent import mcp_server

    src = tmp_path / "s.src"
    src.write_text("x")
    manifest = tmp_path / "m.json"
    manifest.write_text("{not json")
    out = json.loads(getattr(mcp_server, tool)(str(src), str(manifest)))
    assert out["status"] == "error"
