"""Tests for agent.adapter_probe — C11 declared availability probes."""

import sys
import threading
import time

import pytest

from agent.adapter_probe import (
    AdapterProbeOutcome,
    AdapterProbeRequest,
    MAX_PLAN_ROUNDS,
    PROBE_SCHEMA,
    observe_probes,
    plan_with_probes,
    probe_request_for,
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


from agent.adapter_probe import probe_requests_for
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


def test_observe_probes_rejects_bad_parallel_bound():
    for bad in (0, -1, 1.5, True, "2"):
        with pytest.raises(ValueError, match="parallelism bound"):
            observe_probes((_req(),), max_parallel=bad)


def test_observe_probes_parallel_preserves_request_order():
    import dataclasses as _dc

    slow = _dc.replace(
        _req(
            argv=(
                sys.executable,
                "-c",
                "import time, sys; time.sleep(0.4); sys.exit(0)",
            )
        ),
        adapter_id="slow.probe",
    )
    fast = _dc.replace(
        _req(
            argv=(
                sys.executable,
                "-c",
                "import time, sys; time.sleep(0.4); sys.exit(2)",
            )
        ),
        adapter_id="fast.probe",
    )
    start = time.monotonic()
    obs = observe_probes((slow, fast), max_parallel=2)
    elapsed = time.monotonic() - start
    # Request order survives completion order: the slow probe
    # answers first even though it finishes last.
    assert [o.adapter_id for o in obs] == ["slow.probe", "fast.probe"]
    assert [o.availability for o in obs] == ["available", "missing"]
    # Both probes sleep 0.4s: sequential execution takes ~0.9s+
    # including spawn, so a regression to serial order fails here.
    assert elapsed < 0.75


def test_observe_probes_parallel_single_request():
    obs = observe_probes((_req(),), max_parallel=4)
    assert len(obs) == 1
    assert obs[0].availability == "available"


class _ConcurrencyStubRunner:
    """Runner stand-in that records peak concurrent `run` calls."""

    class _Result:
        def normalized(self):
            import types as _t

            return _t.SimpleNamespace(outcome="exited", exit_code=0)

    def __init__(self):
        self._lock = threading.Lock()
        self.inflight = 0
        self.max_seen = 0

    def run(self, execution_request, argv, cancel_event=None, memory_bound_mb=None):
        with self._lock:
            self.inflight += 1
            self.max_seen = max(self.max_seen, self.inflight)
        try:
            time.sleep(0.05)
        finally:
            with self._lock:
                self.inflight -= 1
        return self._Result()


def test_observe_probes_memory_bound_batch_runs_sequentially():
    import dataclasses as _dc

    # preexec_fn carries the memory bound and is unsafe under
    # threads: a batch carrying a memory-bound probe must stay
    # sequential even when max_parallel allows concurrency.
    bound = _dc.replace(_req(), adapter_id="bound.probe", memory_bound_mb=64)
    plain_a = _dc.replace(_req(), adapter_id="plain.a")
    plain_b = _dc.replace(_req(), adapter_id="plain.b")

    runner = _ConcurrencyStubRunner()
    obs = observe_probes((bound, plain_a, plain_b), runner=runner, max_parallel=3)
    assert [o.adapter_id for o in obs] == ["bound.probe", "plain.a", "plain.b"]
    assert runner.max_seen == 1


def test_observe_probes_unbound_batch_runs_in_parallel():
    import dataclasses as _dc

    a = _dc.replace(_req(), adapter_id="a.probe")
    b = _dc.replace(_req(), adapter_id="b.probe")

    runner = _ConcurrencyStubRunner()
    obs = observe_probes((a, b), runner=runner, max_parallel=2)
    assert [o.adapter_id for o in obs] == ["a.probe", "b.probe"]
    assert runner.max_seen == 2


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
    for bad in (0, -1, 1.5, True, "2"):
        with pytest.raises(ValueError, match="parallelism bound"):
            plan_with_probes(
                registry, _route(), PlannerPolicy(), stamp=1,
                max_parallel=bad,
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
