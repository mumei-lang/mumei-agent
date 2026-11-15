"""Tests for agent.adapter_probe — C11 declared availability probes."""

import sys
import threading

import pytest

from agent.adapter_probe import (
    AdapterProbeHistory,
    AdapterProbeOutcome,
    AdapterProbeRequest,
    MAX_PROBE_HISTORY,
    MAX_PLAN_ROUNDS,
    PROBE_SCHEMA,
    observe_probes,
    plan_with_probes,
    probe_request_for,
    probe_requests_for,
    probe_retry_requests,
    probe_requests_for,
    run_probe,
)
from agent.verification_planner import RuntimeObservation


def _req(**kw):
    argv = kw.pop(
        "argv",
        (sys.executable, "-c", "import sys; sys.exit(0)"),
    )
    return AdapterProbeRequest(
        "zendingsol.host.lean_scaffold",
        argv,
        timeout_ms=kw.pop("timeout_ms", 30_000),
        stamp=kw.pop("stamp", 1),
        **kw,
    )


def test_exit_zero_observes_available():
    out = run_probe(_req())
    assert out.observation == RuntimeObservation(
        "zendingsol.host.lean_scaffold",
        availability="available",
        stamp=1,
    )
    assert out.result.outcome == "exited"
    assert out.result.exit_code == 0


def test_nonzero_exit_observes_missing():
    out = run_probe(
        _req(argv=(sys.executable, "-c", "import sys; sys.exit(3)"))
    )
    assert out.observation.availability == "missing"
    assert out.result.outcome == "exited"
    assert out.result.exit_code == 3


def test_spawn_failure_observes_missing():
    out = run_probe(_req(argv=("/nonexistent-probe-binary",)))
    assert out.observation.availability == "missing"
    assert out.result.outcome == "failed"


def test_timeout_observes_unknown():
    out = run_probe(
        _req(
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(10)",
            ),
            timeout_ms=150,
        )
    )
    assert out.observation.availability == "unknown"
    assert out.result.outcome == "timed_out"


def test_fingerprint_binds_adapters():
    a = _req(stamp=1).execution_request().request_fingerprint
    b = _req(stamp=2).execution_request().request_fingerprint
    assert a != b and len(a) == 64


def test_outcome_to_dict_round_trip():
    out = run_probe(_req())
    d = out.to_dict()
    assert d["schema_version"] == PROBE_SCHEMA
    assert d["observation"]["availability"] == "available"
    assert d["observation"]["adapter_id"] == "zendingsol.host.lean_scaffold"


def test_request_validation():
    with pytest.raises(ValueError):
        AdapterProbeRequest(
            "zendingsol.host.lean_scaffold",
            (),  # empty argv
            timeout_ms=1_000,
            stamp=1,
        )
    with pytest.raises(ValueError):
        AdapterProbeRequest(
            "zendingsol.host.lean_scaffold",
            ("x",),
            timeout_ms=0,
            stamp=1,
        )
    with pytest.raises(ValueError):
        AdapterProbeRequest(
            "zendingsol.host.lean_scaffold",
            ("x",),
            timeout_ms=1_000,
            stamp=0,
        )
    with pytest.raises(ValueError):
        AdapterProbeRequest(
            "zendingsol.host.lean_scaffold",
            ("x",),
            timeout_ms=1_000,
            stamp=1,
            memory_bound_mb=0,
        )
    with pytest.raises(ValueError):
        AdapterProbeRequest(
            "not a label",
            ("x",),
            timeout_ms=1_000,
            stamp=1,
        )


def test_run_probe_rejects_bad_inputs():
    with pytest.raises(ValueError):
        run_probe(object())
    with pytest.raises(ValueError):
        run_probe(_req(), cancel_event=object())


def test_cancel_event_passthrough():
    ev = threading.Event()
    out = run_probe(_req(), cancel_event=ev)
    assert out.observation.availability == "available"



def test_declared_tool_version_reaches_observation():
    out = run_probe(_req(tool_version="4.0.0"))
    assert out.observation.tool_version == "4.0.0"


def test_tool_version_validation():
    with pytest.raises(ValueError):
        _req(tool_version="not a version!")
    with pytest.raises(ValueError):
        _req(tool_version=7)


def test_plan_selects_adapter_after_successful_probe():
    from agent.verification_planner import (
        AdapterDescriptor,
        AdapterRegistry,
        PlannerPolicy,
        RouteRequirements,
    )

    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            "zendingsol.host.lean_scaffold",
            "0.1.0",
            frozenset({"zendingsol.host.lean_scaffold/v0"}),
            frozenset({"deductive_proof"}),
        )
    )
    request = RouteRequirements(
        "zendingsol.host.lean_scaffold/v0",
        "deductive_proof",
        frozenset(),
    )
    out = run_probe(_req(tool_version="4.0.0"))
    plan = registry.plan(request, PlannerPolicy(), (out.observation,))
    assert plan.selected is not None



from agent.verification_planner import (
    AdapterDescriptor,
    PROTOCOL_VERSION,
)
from agent.adapter_probe import probe_request_for


def _manifest(**kw):
    base = {
        "schema_version": PROTOCOL_VERSION,
        "adapter_id": "zendingsol.host.lean_scaffold",
        "adapter_version": "0.1.0",
        "profiles": ["zendingsol.host.lean_scaffold/v0"],
        "methods": ["deductive_proof"],
        "max_timeout_ms": 5_000,
        "max_memory_mb": 256,
        "probe_argv": ["lean", "--version"],
    }
    base.update(kw)
    return base


def test_manifest_probe_argv_parsed_and_serialized():
    d = AdapterDescriptor.from_manifest(_manifest())
    assert d.probe_argv == ("lean", "--version")
    assert d.to_dict()["probe_argv"] == ["lean", "--version"]


def test_manifest_probe_argv_absent_stays_none():
    m = _manifest()
    del m["probe_argv"]
    d = AdapterDescriptor.from_manifest(m)
    assert d.probe_argv is None
    assert d.to_dict()["probe_argv"] is None


def test_manifest_probe_argv_rejects_bad_shapes():
    for bad in ([], ["ok", ""], "lean --version", 7):
        with pytest.raises(ValueError):
            AdapterDescriptor.from_manifest(
                _manifest(probe_argv=bad)
            )


def test_probe_request_binds_declared_budgets():
    d = AdapterDescriptor.from_manifest(_manifest())
    req = probe_request_for(d, stamp=7)
    assert req.adapter_id == d.adapter_id
    assert req.argv == ("lean", "--version")
    assert req.timeout_ms == 5_000
    assert req.memory_bound_mb == 256
    assert req.stamp == 7


def test_probe_request_requires_declaration():
    m = _manifest()
    del m["probe_argv"]
    d = AdapterDescriptor.from_manifest(m)
    with pytest.raises(ValueError, match="not declared"):
        probe_request_for(d, stamp=1)
    with pytest.raises(ValueError):
        probe_request_for(object(), stamp=1)


def test_probe_request_runs_declared_command():
    d = AdapterDescriptor.from_manifest(
        _manifest(
            probe_argv=[
                sys.executable, "-c",
                "import sys; sys.exit(0)",
            ]
        )
    )
    out = run_probe(probe_request_for(d, stamp=9))
    assert out.observation.availability == "available"
    assert out.observation.stamp == 9



def test_probe_request_passes_declared_tool_version():
    d = AdapterDescriptor.from_manifest(_manifest())
    req = probe_request_for(d, stamp=7, tool_version="4.0.0")
    assert req.tool_version == "4.0.0"
    with pytest.raises(ValueError):
        probe_request_for(d, stamp=7, tool_version="bad version!")


from agent.verification_planner import (
    AdapterRegistry,
    PlannerPolicy,
    RouteRequirements,
)


def _registry(**kw):
    registry = AdapterRegistry()
    registry.register(AdapterDescriptor.from_manifest(_manifest(**kw)))
    return registry


def _route():
    return RouteRequirements(
        "zendingsol.host.lean_scaffold/v0",
        "deductive_proof",
        frozenset(),
    )


def test_probe_requests_pick_observation_excluded_candidates():
    registry = _registry()
    plan = registry.plan(_route(), PlannerPolicy(), ())
    assert plan.selected is None
    reqs = probe_requests_for(registry, _route(), PlannerPolicy(), stamp=3)
    assert len(reqs) == 1
    assert reqs[0].argv == ("lean", "--version")
    assert reqs[0].stamp == 3
    assert reqs[0].timeout_ms == 5_000


def test_probe_requests_skip_undeclared_probe():
    m = _manifest()
    del m["probe_argv"]
    registry = AdapterRegistry()
    registry.register(AdapterDescriptor.from_manifest(m))
    assert (
        probe_requests_for(registry, _route(), PlannerPolicy(), stamp=1)
        == ()
    )


def test_probe_requests_skip_structural_exclusions():
    registry = _registry()
    other = RouteRequirements(
        "zendingsol.host.lean_scaffold/v0",
        "bounded_model_checking",  # not a declared method
        frozenset(),
    )
    assert (
        probe_requests_for(registry, other, PlannerPolicy(), stamp=1)
        == ()
    )


def test_probe_requests_skip_selected_adapter():
    registry = _registry()
    observed = RuntimeObservation(
        "zendingsol.host.lean_scaffold",
        availability="available",
        tool_version="4.0.0",
        stamp=2,
    )
    plan = registry.plan(_route(), PlannerPolicy(), (observed,))
    assert plan.selected is not None
    assert (
        probe_requests_for(
            registry, _route(), PlannerPolicy(), (observed,), stamp=3
        )
        == ()
    )


def test_probe_requests_validation():
    registry = _registry()
    with pytest.raises(ValueError):
        probe_requests_for(object(), _route(), PlannerPolicy(), stamp=1)
    with pytest.raises(ValueError):
        probe_requests_for(registry, object(), PlannerPolicy(), stamp=1)
    with pytest.raises(ValueError):
        probe_requests_for(registry, _route(), object(), stamp=1)
    with pytest.raises(ValueError):
        probe_requests_for(registry, _route(), PlannerPolicy(), stamp=0)


def test_observe_probes_runs_each_request():
    obs = observe_probes(
        (
            _req(argv=(sys.executable, "-c", "import sys; sys.exit(0)")),
            _req(argv=(sys.executable, "-c", "import sys; sys.exit(2)")),
        )
    )
    assert [o.availability for o in obs] == ["available", "missing"]
    assert all(o.stamp == 1 for o in obs)


def test_observe_probes_empty_tuple():
    assert observe_probes(()) == ()


def test_observe_probes_rejects_non_tuple():
    with pytest.raises(ValueError, match="request tuple"):
        observe_probes([_req()])


def test_observe_probes_rejects_bad_cancel_event():
    with pytest.raises(ValueError, match="cancellation"):
        observe_probes((), cancel_event=object())


def test_observe_probes_feeds_replan():
    """Round-trip: schedule → observe → plan sees the observation."""
    registry = _registry(
        probe_argv=[sys.executable, "-c", "import sys; sys.exit(0)"]
    )
    policy = PlannerPolicy()
    assert registry.plan(_route(), policy, ()).selected is None
    reqs = probe_requests_for(
        registry, _route(), policy, stamp=1, tool_version="4.0.0"
    )
    assert len(reqs) == 1
    obs = observe_probes(reqs)
    plan2 = registry.plan(_route(), policy, obs)
    assert plan2.selected is not None
    assert (
        plan2.selected.adapter_id == "zendingsol.host.lean_scaffold"
    )


def test_observe_probes_missing_keeps_excluded():
    registry = _registry(probe_argv=["/nonexistent-probe-binary"])
    policy = PlannerPolicy()
    reqs = probe_requests_for(registry, _route(), policy, stamp=1)
    obs = observe_probes(reqs)
    assert obs[0].availability == "missing"
    assert registry.plan(_route(), policy, obs).selected is None


def test_probe_history_records_outcomes():
    req = _req()
    hist = AdapterProbeHistory.start(req)
    assert hist.attempt_count == 0
    out = run_probe(req)
    hist = hist.record(req, out)
    assert hist.attempt_count == 1
    assert hist.outcomes[0].outcome == "exited"
    req2 = _req(attempt_number=2)
    hist = hist.record(req2, run_probe(req2))
    assert hist.attempt_count == 2


def test_probe_history_rejects_fingerprint_mismatch():
    hist = AdapterProbeHistory.start(_req())
    other = _req(argv=(sys.executable, "-c", "pass"))
    with pytest.raises(ValueError, match="fingerprint"):
        hist.record(other, run_probe(other))


def test_probe_history_rejects_adapter_mismatch():
    hist = AdapterProbeHistory.start(_req())
    other = AdapterProbeRequest(
        "zendingsol.host.other",
        (sys.executable, "-c", "pass"),
        timeout_ms=30_000,
        stamp=1,
    )
    with pytest.raises(ValueError, match="adapter"):
        hist.record(other, run_probe(other))


def test_probe_history_rejects_foreign_outcome():
    hist = AdapterProbeHistory.start(_req())
    other = _req(argv=(sys.executable, "-c", "pass"))
    foreign = run_probe(other)
    with pytest.raises(ValueError, match="match request"):
        hist.record(_req(), foreign)


def test_probe_history_rejects_out_of_order_attempt():
    hist = AdapterProbeHistory.start(_req())
    req2 = _req(attempt_number=2)
    with pytest.raises(ValueError, match="ordinal"):
        hist.record(req2, run_probe(req2))
    req = _req()
    hist = hist.record(req, run_probe(req))
    with pytest.raises(ValueError, match="ordinal"):
        hist.record(req, run_probe(req))


def test_probe_history_bound():
    hist = AdapterProbeHistory.start(_req())
    for n in range(1, MAX_PROBE_HISTORY + 1):
        req = _req(attempt_number=n)
        hist = hist.record(req, run_probe(req))
    req = _req(attempt_number=MAX_PROBE_HISTORY + 1)
    with pytest.raises(ValueError, match="bound"):
        hist.record(req, run_probe(req))


def test_probe_history_validation():
    with pytest.raises(ValueError):
        AdapterProbeHistory.start(object())
    hist = AdapterProbeHistory.start(_req())
    with pytest.raises(ValueError):
        hist.record(_req(), object())
    with pytest.raises(ValueError):
        AdapterProbeHistory(
            "zendingsol.host.lean_scaffold", "nothex"
        )


def test_plan_with_probes_selects_after_probe():
    registry = _registry(
        probe_argv=[sys.executable, "-c", "import sys; sys.exit(0)"]
    )
    policy = PlannerPolicy()
    out = plan_with_probes(
        registry, _route(), policy, stamp=1, tool_version="4.0.0"
    )
    assert out.plan.selected is not None
    assert (
        out.plan.selected.adapter_id
        == "zendingsol.host.lean_scaffold"
    )
    assert [o.availability for o in out.observations] == [
        "available"
    ]


def test_plan_with_probes_missing_stays_excluded():
    registry = _registry(probe_argv=["/nonexistent-probe-binary"])
    out = plan_with_probes(
        registry, _route(), PlannerPolicy(), stamp=1
    )
    assert out.plan.selected is None
    assert [o.availability for o in out.observations] == ["missing"]


def test_plan_with_probes_already_selected_runs_nothing():
    registry = _registry()
    policy = PlannerPolicy()
    observed = (
        RuntimeObservation(
            "zendingsol.host.lean_scaffold",
            availability="available",
            tool_version="4.0.0",
            stamp=1,
        ),
    )
    out = plan_with_probes(
        registry, _route(), policy, observed, stamp=2
    )
    assert out.plan.selected is not None
    assert out.observations == ()


def test_plan_with_probes_no_requests_stops():
    m = _manifest()
    del m["probe_argv"]
    registry = AdapterRegistry()
    registry.register(AdapterDescriptor.from_manifest(m))
    out = plan_with_probes(
        registry, _route(), PlannerPolicy(), stamp=1
    )
    assert out.plan.selected is None
    assert out.observations == ()


def test_plan_with_probes_validation():
    registry = _registry()
    with pytest.raises(ValueError):
        plan_with_probes(object(), _route(), PlannerPolicy(), stamp=1)
    with pytest.raises(ValueError):
        plan_with_probes(registry, object(), PlannerPolicy(), stamp=1)
    with pytest.raises(ValueError):
        plan_with_probes(registry, _route(), object(), stamp=1)
    with pytest.raises(ValueError):
        plan_with_probes(registry, _route(), PlannerPolicy(), stamp=0)
    for bad in (0, -1, MAX_PLAN_ROUNDS + 1):
        with pytest.raises(ValueError):
            plan_with_probes(
                registry, _route(), PlannerPolicy(), stamp=1,
                rounds=bad,
            )


def test_plan_with_probes_reprobe_replaces_observation():
    """A second probe of the same adapter must not trip plan()'s
    duplicate-observation rejection."""
    registry = _registry(probe_argv=["/nonexistent-probe-binary"])
    out = plan_with_probes(
        registry, _route(), PlannerPolicy(), stamp=1, rounds=2
    )
    assert out.plan.selected is None
    # Deduped by adapter id so the result chains into plan().
    assert [o.availability for o in out.observations] == ["missing"]
    registry.plan(_route(), PlannerPolicy(), out.observations)


def test_plan_with_probes_replaces_initial_observation():
    """An adapter carrying a stale initial observation that is
    re-probed lands in `observed` exactly once."""
    registry = _registry(probe_argv=["/nonexistent-probe-binary"])
    stale = (
        RuntimeObservation(
            "zendingsol.host.lean_scaffold",
            availability="unknown",
            stamp=1,
        ),
    )
    out = plan_with_probes(
        registry, _route(), PlannerPolicy(), stale, stamp=2
    )
    assert out.plan.selected is None
    assert len(out.observations) == 1


def test_probe_retry_first_attempt_without_history():
    reqs = probe_retry_requests(
        _registry(), _route(), PlannerPolicy(), stamp=1
    )
    assert len(reqs) == 1
    assert reqs[0].attempt_number == 1


def test_probe_retry_emits_next_ordinal():
    registry = _registry()
    req = probe_requests_for(
        registry, _route(), PlannerPolicy(), stamp=1
    )[0]
    hist = AdapterProbeHistory.start(req)
    hist = hist.record(req, run_probe(req))
    reqs = probe_retry_requests(
        registry, _route(), PlannerPolicy(), (), (hist,), stamp=1
    )
    assert len(reqs) == 1
    assert reqs[0].attempt_number == 2
    # Each retry is a fresh declared request — the stamp advances
    # so the registry's replay detection accepts the new claim.
    assert reqs[0].stamp == 2


def test_probe_retry_stops_at_bound():
    registry = _registry()
    req = probe_requests_for(
        registry, _route(), PlannerPolicy(), stamp=1
    )[0]
    hist = AdapterProbeHistory.start(req)
    import dataclasses as _dc

    for n in range(1, MAX_PROBE_HISTORY + 1):
        req_n = _dc.replace(req, attempt_number=n)
        hist = hist.record(req_n, run_probe(req_n))
    assert (
        probe_retry_requests(
            registry, _route(), PlannerPolicy(), (), (hist,), stamp=1
        )
        == ()
    )


def test_probe_retry_rejects_stale_fingerprint():
    registry = _registry()
    other = _req(argv=(sys.executable, "-c", "pass"))
    hist = AdapterProbeHistory.start(other)
    with pytest.raises(ValueError, match="fingerprint"):
        probe_retry_requests(
            registry, _route(), PlannerPolicy(), (), (hist,), stamp=1
        )


def test_probe_retry_rejects_duplicate_history():
    hist = AdapterProbeHistory.start(_req())
    with pytest.raises(ValueError, match="duplicate"):
        probe_retry_requests(
            _registry(), _route(), PlannerPolicy(), (), (hist, hist),
            stamp=1,
        )


def test_probe_retry_validation():
    with pytest.raises(ValueError):
        probe_retry_requests(
            _registry(), _route(), PlannerPolicy(), stamp=1,
            max_attempts=0,
        )
    with pytest.raises(ValueError):
        probe_retry_requests(
            _registry(), _route(), PlannerPolicy(), (),
            histories=[AdapterProbeHistory.start(_req())], stamp=1,
        )


def test_probe_retry_replaces_observation_in_plan(tmp_path):
    """A retry keeps the stamp; its observation REPLACES the earlier
    attempt's for that adapter (never appended beside it)."""
    flag = tmp_path / "ready"
    argv = (
        sys.executable,
        "-c",
        f"import os,sys;sys.exit(0 if os.path.exists({str(flag)!r}) else 1)",
    )
    registry = _registry(probe_argv=list(argv))
    policy = PlannerPolicy()
    req = probe_requests_for(registry, _route(), policy, stamp=1)[0]
    miss = run_probe(req)
    assert miss.observation.availability == "missing"
    hist = AdapterProbeHistory.start(req).record(req, miss)
    retries = probe_retry_requests(
        registry,
        _route(),
        policy,
        (miss.observation,),
        (hist,),
        stamp=1,
        tool_version="4.0.0",
    )
    assert [r.attempt_number for r in retries] == [2]
    flag.touch()
    ok = run_probe(retries[0])
    assert ok.observation.availability == "available"
    # Replace, not append — a single latest observation plans cleanly.
    plan = registry.plan(_route(), policy, (ok.observation,))
    assert plan.selected is not None
    assert (
        plan.selected.adapter_id == "zendingsol.host.lean_scaffold"
    )
