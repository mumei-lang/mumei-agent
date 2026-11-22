import hashlib
import json
import shutil
import socket
import sys
import threading
from dataclasses import replace

import pytest

import agent.attempt_schedule as attempt_schedule
from agent.attempt_runner import (
    AttemptRunner,
    memory_bound_enforceable,
    network_isolation_enforceable,
)
from agent.attempt_schedule import (
    MAX_SCHEDULE_ATTEMPTS,
    NOT_DISPATCHED,
    SCHEDULE_SCHEMA_VERSION,
    AttemptScheduleResult,
    DispatchEnforcement,
    ScheduledAttemptEntry,
    _adapter_environment,
    run_attempt_schedule,
)
from agent.verification_planner import (
    SOURCE_INPUT_FORMAT,
    AdapterDescriptor,
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
    RuntimeObservation,
    VerdictMarker,
)

PY = shutil.which("python3", path="/usr/bin:/bin") or sys.executable
SOURCE = b"FAKE_PRIVATE_SOURCE_NOT_EVIDENCE"
PROFILE = "mumei.test/v1"
CONTRACT = ResultContract(
    PROFILE, "deductive_proof", "unbounded", "mumei.source-model/v1", "assumed"
)


def argv(code):
    return (PY, "-c", f"import sys; sys.exit({code})")


def environment_probe(present):
    return argv(
        "0 if ('MUMEI_TEST_FAKE_SENTINEL' in __import__('os').environ) "
        f"is {present} else 1"
    )


def network_probe(port):
    return (
        PY,
        "-c",
        "import socket,sys\n"
        "try:\n"
        f" s=socket.create_connection(('127.0.0.1',{port}), timeout=3)\n"
        "except OSError:\n"
        " sys.exit(1)\n"
        "else:\n"
        " s.close(); sys.exit(0)\n",
    )


def descriptor(adapter_id, priority=0, **overrides):
    required_permissions = overrides.pop(
        "required_permissions", frozenset()
    )
    return AdapterDescriptor(
        adapter_id,
        "1.0.0",
        frozenset({PROFILE}),
        frozenset({CONTRACT.method}),
        priority=priority,
        result_contracts=(CONTRACT,),
        input_formats=frozenset({SOURCE_INPUT_FORMAT}),
        required_permissions=required_permissions,
        **overrides,
    )


def registry_with(*ids):
    registry = AdapterRegistry()
    for adapter_id in ids:
        registry.register(descriptor(adapter_id, priority=0))
    return registry


def request():
    return RouteRequirements(
        PROFILE,
        CONTRACT.method,
        result_contract=CONTRACT,
        input_format=SOURCE_INPUT_FORMAT,
    )


def policy(**kwargs):
    kwargs.setdefault("allowed_permissions", frozenset())
    kwargs.setdefault("timeout_ms", 10_000)
    return PlannerPolicy(**kwargs)


def observations(*ids):
    return tuple(
        RuntimeObservation(adapter_id, "available", "1.0.0", stamp=index + 1)
        for index, adapter_id in enumerate(ids)
    )


def schedule(registry, ids, argv_map, **kwargs):
    kwargs.setdefault("observations", observations(*ids))
    return run_attempt_schedule(
        registry,
        request(),
        kwargs.pop("policy", policy()),
        SOURCE,
        hashlib.sha256(SOURCE).hexdigest(),
        lambda adapter_id: argv_map.get(adapter_id),
        **kwargs,
    )


def schedule_with_runner_stub(monkeypatch, registry, ids, argv_map, **kwargs):
    runner = AttemptRunner()
    actual_run = runner.run
    received = []

    def run_stub(request, child_argv, **run_kwargs):
        received.append(dict(run_kwargs))
        run_kwargs["memory_bound_mb"] = None
        run_kwargs["isolate_network"] = False
        run_kwargs["isolate_filesystem_write"] = False
        run_kwargs["isolate_filesystem_read"] = False
        run_kwargs["isolate_process_spawn"] = False
        return actual_run(request, child_argv, **run_kwargs)

    monkeypatch.setattr(runner, "run", run_stub)
    result = schedule(
        registry,
        ids,
        argv_map,
        runner=runner,
        **kwargs,
    )
    return result, received


def test_first_adapter_success_selects_without_fallback():
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"alpha": argv(0), "beta": argv(0)})
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "alpha"
    assert len(result.entries) == 1
    assert result.entries[0].terminal_state == "exited"
    assert result.entries[0].exit_code == 0
    doc = result.to_dict()
    assert doc["schema_version"] == SCHEDULE_SCHEMA_VERSION
    assert SOURCE.decode() not in json.dumps(doc) + repr(result)


def test_schedule_scrubs_environment_without_environment_permission(monkeypatch):
    monkeypatch.setenv("MUMEI_TEST_FAKE_SENTINEL", "not-a-secret-sentinel")
    registry = registry_with("alpha")

    result = schedule(
        registry,
        ("alpha",),
        {"alpha": environment_probe(False)},
    )

    assert result.outcome == "selected"
    assert result.entries[0].exit_code == 0


def test_schedule_inherits_environment_when_permission_is_allowed(monkeypatch):
    monkeypatch.setenv("MUMEI_TEST_FAKE_SENTINEL", "not-a-secret-sentinel")
    registry = AdapterRegistry()
    registry.register(
        descriptor(
            "alpha",
            required_permissions=frozenset({"environment.read"}),
        )
    )

    result = schedule(
        registry,
        ("alpha",),
        {"alpha": environment_probe(True)},
        policy=policy(allowed_permissions=frozenset({"environment.read"})),
    )

    assert result.outcome == "selected"
    assert result.entries[0].exit_code == 0


def test_schedule_helper_scrubs_environment_when_permissions_are_undeclared(
    monkeypatch,
):
    monkeypatch.setenv("MUMEI_TEST_FAKE_SENTINEL", "not-a-secret-sentinel")
    registry = AdapterRegistry()
    registry.register(
        descriptor(
            "alpha",
            required_permissions=frozenset({"environment.read"}),
        )
    )
    plan = registry.plan(
        request(),
        policy(allowed_permissions=None),
        observations("alpha"),
    )
    environment = _adapter_environment(plan)
    assert environment is not None
    assert "MUMEI_TEST_FAKE_SENTINEL" not in environment
    assert set(environment) <= {"PATH", "SYSTEMROOT"}


@pytest.mark.parametrize(
    (
        "required_permissions",
        "allowed_permissions",
        "network_enforceable",
        "filesystem_enforceable",
        "expected_environment",
        "expected_network",
        "expected_filesystem",
    ),
    [
        (
            frozenset(),
            frozenset(),
            True,
            True,
            "minimal",
            "isolated",
            "isolated",
        ),
        (
            frozenset(),
            frozenset(),
            False,
            False,
            "minimal",
            "unenforced",
            "unenforced",
        ),
        (
            frozenset({"environment.read", "network.connect"}),
            frozenset({"environment.read", "network.connect"}),
            True,
            True,
            "inherited",
            "permitted",
            "isolated",
        ),
        (
            frozenset(),
            frozenset({"network.connect"}),
            True,
            True,
            "minimal",
            "isolated",
            "isolated",
        ),
        (
            frozenset(),
            frozenset({"filesystem.write"}),
            True,
            True,
            "minimal",
            "isolated",
            "isolated",
        ),
        (
            frozenset({"filesystem.write"}),
            frozenset({"filesystem.write"}),
            True,
            True,
            "minimal",
            "isolated",
            "permitted",
        ),
    ],
    ids=[
        "undeclared-and-enforceable",
        "undeclared-and-unenforceable",
        "environment-and-network-declared-and-allowed",
        "network-allowed-but-not-declared",
        "filesystem-allowed-but-not-declared",
        "filesystem-declared-and-allowed",
    ],
)
def test_schedule_records_and_dispatches_effective_enforcement(
    monkeypatch,
    required_permissions,
    allowed_permissions,
    network_enforceable,
    filesystem_enforceable,
    expected_environment,
    expected_network,
    expected_filesystem,
):
    registry = AdapterRegistry()
    registry.register(
        descriptor("alpha", required_permissions=required_permissions)
    )
    requested_isolation = []
    real_dispatch = attempt_schedule.dispatch_attempt

    def record_dispatch(sequence, child_argv, **kwargs):
        requested_isolation.append(
            (
                kwargs["isolate_network"],
                kwargs["isolate_filesystem_write"],
                kwargs["isolate_process_spawn"],
                kwargs["isolate_filesystem_read"],
            )
        )
        kwargs["isolate_network"] = False
        kwargs["isolate_filesystem_write"] = False
        kwargs["isolate_process_spawn"] = False
        kwargs["isolate_filesystem_read"] = False
        return real_dispatch(sequence, child_argv, **kwargs)

    monkeypatch.setattr(attempt_schedule, "dispatch_attempt", record_dispatch)
    monkeypatch.setattr(
        attempt_schedule,
        "network_isolation_enforceable",
        lambda: network_enforceable,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "filesystem_write_isolation_enforceable",
        lambda: filesystem_enforceable,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "filesystem_read_isolation_enforceable",
        lambda: True,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "process_spawn_isolation_enforceable",
        lambda: True,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "memory_bound_enforceable",
        lambda: False,
    )
    result, runner_calls = schedule_with_runner_stub(
        monkeypatch,
        registry,
        ("alpha",),
        {"alpha": argv(0)},
        policy=policy(allowed_permissions=allowed_permissions),
    )

    assert result.outcome == "selected"
    enforcement = result.entries[0].to_dict()["enforcement"]
    assert enforcement == {
        "environment": expected_environment,
        "network": expected_network,
        "filesystem_write": expected_filesystem,
        "filesystem_read": "isolated",
        "process_spawn": "isolated",
        "memory_bound_mb": None,
    }
    assert requested_isolation == [
        (
            enforcement["network"] == "isolated",
            enforcement["filesystem_write"] == "isolated",
            enforcement["process_spawn"] == "isolated",
            enforcement["filesystem_read"] == "isolated",
        )
    ]
    assert len(runner_calls) == 1
    assert runner_calls[0]["memory_bound_mb"] == enforcement["memory_bound_mb"]
    if enforcement["environment"] == "inherited":
        assert runner_calls[0]["environment"] is None
    else:
        assert runner_calls[0]["environment"] is not None
        assert set(runner_calls[0]["environment"]) <= {"PATH", "SYSTEMROOT"}


@pytest.mark.parametrize(
    ("required_permissions", "allowed_permissions", "enforceable", "expected"),
    [
        (
            frozenset({"process.spawn"}),
            frozenset({"process.spawn"}),
            True,
            "permitted",
        ),
        (frozenset(), frozenset(), True, "isolated"),
        (frozenset(), frozenset(), False, "unenforced"),
    ],
    ids=["declared-and-allowed", "isolated", "unenforced"],
)
def test_schedule_records_process_spawn_enforcement(
    monkeypatch,
    required_permissions,
    allowed_permissions,
    enforceable,
    expected,
):
    registry = AdapterRegistry()
    registry.register(
        descriptor("alpha", required_permissions=required_permissions)
    )
    monkeypatch.setattr(
        attempt_schedule, "network_isolation_enforceable", lambda: True
    )
    monkeypatch.setattr(
        attempt_schedule,
        "filesystem_write_isolation_enforceable",
        lambda: True,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "filesystem_read_isolation_enforceable",
        lambda: True,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "process_spawn_isolation_enforceable",
        lambda: enforceable,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "memory_bound_enforceable",
        lambda: False,
    )
    result, runner_calls = schedule_with_runner_stub(
        monkeypatch,
        registry,
        ("alpha",),
        {"alpha": argv(0)},
        policy=policy(allowed_permissions=allowed_permissions),
    )

    enforcement = result.entries[0].to_dict()["enforcement"]
    forwarded_isolation = runner_calls[0]["isolate_process_spawn"]
    assert enforcement["process_spawn"] == expected
    assert forwarded_isolation is (expected == "isolated")
    assert enforcement == {
        "environment": "minimal",
        "network": "isolated",
        "filesystem_write": "isolated",
        "filesystem_read": "isolated",
        "process_spawn": expected,
        "memory_bound_mb": None,
    }


@pytest.mark.parametrize(
    ("required_permissions", "allowed_permissions", "enforceable", "expected"),
    [
        (
            frozenset({"filesystem.read"}),
            frozenset({"filesystem.read"}),
            True,
            "permitted",
        ),
        (
            frozenset(),
            frozenset(),
            True,
            "isolated",
        ),
        (
            frozenset(),
            frozenset(),
            False,
            "unenforced",
        ),
    ],
    ids=["permitted", "isolated", "unenforced"],
)
def test_schedule_records_filesystem_read_enforcement(
    monkeypatch,
    required_permissions,
    allowed_permissions,
    enforceable,
    expected,
):
    registry = AdapterRegistry()
    registry.register(
        descriptor("alpha", required_permissions=required_permissions)
    )
    monkeypatch.setattr(
        attempt_schedule, "network_isolation_enforceable", lambda: True
    )
    monkeypatch.setattr(
        attempt_schedule,
        "filesystem_write_isolation_enforceable",
        lambda: True,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "filesystem_read_isolation_enforceable",
        lambda: enforceable,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "process_spawn_isolation_enforceable",
        lambda: True,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "memory_bound_enforceable",
        lambda: False,
    )
    result, runner_calls = schedule_with_runner_stub(
        monkeypatch,
        registry,
        ("alpha",),
        {"alpha": argv(0)},
        policy=policy(allowed_permissions=allowed_permissions),
    )

    enforcement = result.entries[0].to_dict()["enforcement"]
    forwarded_isolation = runner_calls[0]["isolate_filesystem_read"]
    assert enforcement["filesystem_read"] == expected
    assert forwarded_isolation is (expected == "isolated")
    assert enforcement == {
        "environment": "minimal",
        "network": "isolated",
        "filesystem_write": "isolated",
        "filesystem_read": expected,
        "process_spawn": "isolated",
        "memory_bound_mb": None,
    }


@pytest.mark.parametrize(
    ("host_bound", "memory_enforceable", "expected"),
    [
        (64, False, 64),
        (None, True, "plan"),
        (None, False, None),
    ],
    ids=["host-bound", "plan-bound", "memory-unavailable"],
)
def test_schedule_records_and_dispatches_memory_bound(
    monkeypatch, host_bound, memory_enforceable, expected
):
    registry = registry_with("alpha")
    monkeypatch.setattr(
        attempt_schedule,
        "network_isolation_enforceable",
        lambda: False,
    )
    monkeypatch.setattr(
        attempt_schedule,
        "memory_bound_enforceable",
        lambda: memory_enforceable,
    )
    result, runner_calls = schedule_with_runner_stub(
        monkeypatch,
        registry,
        ("alpha",),
        {"alpha": argv(0)},
        policy=policy(memory_mb=128),
        memory_bound_mb=host_bound,
    )

    expected_bound = (
        result.plans[0].selected.memory_mb if expected == "plan" else expected
    )
    enforcement = result.entries[0].to_dict()["enforcement"]
    if expected == "plan":
        assert expected_bound is not None
    assert enforcement["memory_bound_mb"] == expected_bound
    assert runner_calls[0]["memory_bound_mb"] == enforcement["memory_bound_mb"]


@pytest.mark.parametrize(
    (
        "required_permissions",
        "allowed_permissions",
        "enforceable",
        "expected_isolation",
    ),
    [
        (
            frozenset({"filesystem.write"}),
            frozenset({"filesystem.write"}),
            True,
            False,
        ),
        (frozenset(), frozenset({"filesystem.write"}), True, True),
        (frozenset(), frozenset(), True, True),
        (frozenset(), frozenset(), False, False),
    ],
    ids=[
        "declared-and-allowed",
        "allowed-not-declared",
        "no-permissions",
        "boundary-unavailable",
    ],
)
def test_schedule_computes_filesystem_write_isolation_from_permissions(
    monkeypatch,
    required_permissions,
    allowed_permissions,
    enforceable,
    expected_isolation,
):
    registry = AdapterRegistry()
    registry.register(
        descriptor("alpha", required_permissions=required_permissions)
    )
    requested_isolation = []
    real_dispatch = attempt_schedule.dispatch_attempt

    def record_dispatch(sequence, child_argv, **kwargs):
        requested_isolation.append(kwargs["isolate_filesystem_write"])
        kwargs["isolate_filesystem_write"] = False
        kwargs["isolate_network"] = False
        kwargs["isolate_process_spawn"] = False
        kwargs["isolate_filesystem_read"] = False
        return real_dispatch(sequence, child_argv, **kwargs)

    monkeypatch.setattr(attempt_schedule, "dispatch_attempt", record_dispatch)
    monkeypatch.setattr(
        attempt_schedule,
        "filesystem_write_isolation_enforceable",
        lambda: enforceable,
    )
    result = schedule(
        registry,
        ("alpha",),
        {"alpha": argv(0)},
        policy=policy(allowed_permissions=allowed_permissions),
    )

    assert result.outcome == "selected"
    assert requested_isolation == [expected_isolation]


def test_network_isolation_predicate_treats_unspecified_policy_as_denied():
    registry = AdapterRegistry()
    registry.register(
        descriptor(
            "alpha",
            required_permissions=frozenset({"network.connect"}),
        )
    )
    plan = registry.plan(
        request(),
        policy(allowed_permissions=None),
        observations("alpha"),
    )

    assert plan.selected is not None
    assert plan.selected.required_permissions is None
    assert attempt_schedule._network_isolated(plan) is True


def test_filesystem_write_isolation_predicate_rejects_disallowed_permission():
    # Explicit permission mismatches are filtered before dispatch, so
    # exercise the enforcement predicate with a plan snapshot.
    registry = AdapterRegistry()
    registry.register(
        descriptor("alpha", required_permissions=frozenset())
    )
    plan = registry.plan(
        request(),
        policy(allowed_permissions=frozenset()),
        observations("alpha"),
    )
    assert plan.selected is not None
    plan = replace(
        plan,
        selected=replace(
            plan.selected,
            required_permissions=frozenset({"filesystem.write"}),
        ),
    )

    assert attempt_schedule._filesystem_write_isolated(plan) is True


def test_filesystem_write_isolation_fails_closed_for_unspecified_permissions():
    registry = AdapterRegistry()
    registry.register(descriptor("alpha", required_permissions=None))
    plan = registry.plan(
        request(),
        policy(allowed_permissions=None),
        observations("alpha"),
    )

    assert plan.selected is not None
    assert plan.selected.required_permissions is None
    assert attempt_schedule._filesystem_write_isolated(plan) is True


@pytest.mark.parametrize(
    ("required_permissions", "allowed_permissions", "expected_isolation"),
    [
        (
            frozenset({"process.spawn"}),
            frozenset({"process.spawn"}),
            False,
        ),
        (
            frozenset({"process.spawn"}),
            frozenset(),
            True,
        ),
        (
            frozenset(),
            frozenset({"process.spawn"}),
            True,
        ),
        (None, None, True),
    ],
    ids=[
        "declared-and-allowed",
        "declared-not-allowed",
        "allowed-not-declared",
        "permissions-unspecified",
    ],
)
def test_process_spawn_isolation_predicate_fails_closed(
    required_permissions, allowed_permissions, expected_isolation
):
    registry = AdapterRegistry()
    registry.register(descriptor("alpha", required_permissions=frozenset()))
    plan = registry.plan(
        request(),
        policy(allowed_permissions=frozenset()),
        observations("alpha"),
    )
    assert plan.selected is not None
    plan = replace(
        plan,
        selected=replace(
            plan.selected,
            required_permissions=required_permissions,
        ),
        policy=replace(
            plan.policy,
            allowed_permissions=allowed_permissions,
        ),
    )

    assert (
        attempt_schedule._process_spawn_isolated(plan)
        is expected_isolation
    )


@pytest.mark.parametrize(
    ("required_permissions", "allowed_permissions", "enforceable", "expected"),
    [
        (
            frozenset({"process.spawn"}),
            frozenset({"process.spawn"}),
            True,
            False,
        ),
        (frozenset(), frozenset({"process.spawn"}), True, True),
        (frozenset(), frozenset(), True, True),
        (frozenset(), frozenset(), False, False),
    ],
    ids=[
        "declared-and-allowed",
        "allowed-not-declared",
        "undeclared",
        "boundary-unavailable",
    ],
)
def test_schedule_gates_process_spawn_isolation(
    monkeypatch,
    required_permissions,
    allowed_permissions,
    enforceable,
    expected,
):
    registry = AdapterRegistry()
    registry.register(
        descriptor("alpha", required_permissions=required_permissions)
    )
    requested_isolation = []
    real_dispatch = attempt_schedule.dispatch_attempt

    def record_dispatch(sequence, child_argv, **kwargs):
        requested_isolation.append(kwargs["isolate_process_spawn"])
        kwargs["isolate_process_spawn"] = False
        kwargs["isolate_network"] = False
        kwargs["isolate_filesystem_write"] = False
        kwargs["isolate_filesystem_read"] = False
        return real_dispatch(sequence, child_argv, **kwargs)

    monkeypatch.setattr(attempt_schedule, "dispatch_attempt", record_dispatch)
    monkeypatch.setattr(
        attempt_schedule,
        "process_spawn_isolation_enforceable",
        lambda: enforceable,
    )
    result = schedule(
        registry,
        ("alpha",),
        {"alpha": argv(0)},
        policy=policy(allowed_permissions=allowed_permissions),
    )

    assert result.outcome == "selected"
    assert requested_isolation == [expected]


@pytest.mark.parametrize(
    ("required_permissions", "allowed_permissions", "expected_isolation"),
    [
        (
            frozenset({"filesystem.read"}),
            frozenset({"filesystem.read"}),
            False,
        ),
        (
            frozenset({"filesystem.read"}),
            frozenset(),
            True,
        ),
        (
            frozenset(),
            frozenset({"filesystem.read"}),
            True,
        ),
        (None, None, True),
    ],
    ids=[
        "declared-and-allowed",
        "declared-not-allowed",
        "allowed-not-declared",
        "permissions-unspecified",
    ],
)
def test_filesystem_read_isolation_predicate_fails_closed(
    required_permissions, allowed_permissions, expected_isolation
):
    registry = AdapterRegistry()
    registry.register(descriptor("alpha", required_permissions=frozenset()))
    plan = registry.plan(
        request(),
        policy(allowed_permissions=frozenset()),
        observations("alpha"),
    )
    assert plan.selected is not None
    plan = replace(
        plan,
        selected=replace(
            plan.selected,
            required_permissions=required_permissions,
        ),
        policy=replace(
            plan.policy,
            allowed_permissions=allowed_permissions,
        ),
    )

    assert (
        attempt_schedule._filesystem_read_isolated(plan)
        is expected_isolation
    )


@pytest.mark.parametrize(
    ("required_permissions", "allowed_permissions", "enforceable", "expected"),
    [
        (
            frozenset({"filesystem.read"}),
            frozenset({"filesystem.read"}),
            True,
            False,
        ),
        (frozenset(), frozenset({"filesystem.read"}), True, True),
        (frozenset(), frozenset(), True, True),
        (frozenset(), frozenset(), False, False),
    ],
    ids=[
        "declared-and-allowed",
        "allowed-not-declared",
        "undeclared",
        "boundary-unavailable",
    ],
)
def test_schedule_gates_filesystem_read_isolation(
    monkeypatch,
    required_permissions,
    allowed_permissions,
    enforceable,
    expected,
):
    registry = AdapterRegistry()
    registry.register(
        descriptor("alpha", required_permissions=required_permissions)
    )
    requested_isolation = []
    real_dispatch = attempt_schedule.dispatch_attempt

    def record_dispatch(sequence, child_argv, **kwargs):
        requested_isolation.append(kwargs["isolate_filesystem_read"])
        kwargs["isolate_filesystem_read"] = False
        kwargs["isolate_network"] = False
        kwargs["isolate_filesystem_write"] = False
        kwargs["isolate_process_spawn"] = False
        return real_dispatch(sequence, child_argv, **kwargs)

    monkeypatch.setattr(attempt_schedule, "dispatch_attempt", record_dispatch)
    monkeypatch.setattr(
        attempt_schedule,
        "filesystem_read_isolation_enforceable",
        lambda: enforceable,
    )
    result = schedule(
        registry,
        ("alpha",),
        {"alpha": argv(0)},
        policy=policy(allowed_permissions=allowed_permissions),
    )

    assert result.outcome == "selected"
    assert requested_isolation == [expected]


def test_network_isolation_predicate_rejects_disallowed_permission():
    # Explicit permission mismatches are rejected before an attempt is
    # prepared, so exercise the dispatch predicate with a plan snapshot.
    registry = AdapterRegistry()
    registry.register(descriptor("alpha", required_permissions=frozenset()))
    plan = registry.plan(
        request(),
        policy(allowed_permissions=frozenset()),
        observations("alpha"),
    )
    assert plan.selected is not None
    plan = replace(
        plan,
        selected=replace(
            plan.selected,
            required_permissions=frozenset({"network.connect"}),
        ),
    )

    assert attempt_schedule._network_isolated(plan) is True


@pytest.mark.parametrize(
    (
        "environment",
        "network",
        "filesystem_write",
        "filesystem_read",
        "process_spawn",
        "memory_bound_mb",
    ),
    [
        ("scrubbed", "isolated", "isolated", "isolated", "isolated", None),
        ("minimal", "missing", "isolated", "isolated", "isolated", None),
        ("minimal", "isolated", "missing", "isolated", "isolated", None),
        ("minimal", "isolated", "isolated", "missing", "isolated", None),
        ("minimal", "isolated", "isolated", "isolated", "missing", None),
        ("minimal", "isolated", "isolated", "isolated", "isolated", 0),
        ("minimal", "isolated", "isolated", "isolated", "isolated", True),
        ("minimal", "isolated", "isolated", "isolated", "isolated", 1.0),
        (None, "isolated", "isolated", "isolated", "isolated", None),
    ],
)
def test_dispatch_enforcement_rejects_invalid_values(
    environment,
    network,
    filesystem_write,
    filesystem_read,
    process_spawn,
    memory_bound_mb,
):
    with pytest.raises(ValueError, match="invalid dispatch enforcement"):
        DispatchEnforcement(
            environment,
            network,
            filesystem_write,
            filesystem_read,
            process_spawn,
            memory_bound_mb,
        )


def test_schedule_entry_validates_and_serializes_enforcement():
    enforcement = DispatchEnforcement(
        "minimal", "isolated", "isolated", "isolated", "isolated", 64
    )
    entry = ScheduledAttemptEntry(
        ordinal=1,
        adapter_id="alpha",
        plan_fingerprint="a" * 64,
        request_fingerprint=None,
        terminal_state="exited",
        exit_code=0,
        enforcement=enforcement,
    )

    assert entry.to_dict()["enforcement"] == {
        "environment": "minimal",
        "network": "isolated",
        "filesystem_write": "isolated",
        "filesystem_read": "isolated",
        "process_spawn": "isolated",
        "memory_bound_mb": 64,
    }
    assert list(enforcement.to_dict()) == [
        "environment",
        "network",
        "filesystem_write",
        "filesystem_read",
        "process_spawn",
        "memory_bound_mb",
    ]
    with pytest.raises(ValueError, match="invalid schedule entry enforcement"):
        ScheduledAttemptEntry(
            ordinal=1,
            adapter_id="alpha",
            plan_fingerprint="a" * 64,
            request_fingerprint=None,
            terminal_state="exited",
            exit_code=0,
            enforcement={},
        )
    not_dispatched = ScheduledAttemptEntry(
        ordinal=1,
        adapter_id="alpha",
        plan_fingerprint="a" * 64,
        request_fingerprint=None,
        terminal_state=NOT_DISPATCHED,
        exit_code=None,
        enforcement=None,
    )
    assert not_dispatched.to_dict()["enforcement"] is None
    with pytest.raises(ValueError, match="not-dispatched"):
        ScheduledAttemptEntry(
            ordinal=1,
            adapter_id="alpha",
            plan_fingerprint="a" * 64,
            request_fingerprint=None,
            terminal_state=NOT_DISPATCHED,
            exit_code=None,
            enforcement=enforcement,
        )


@pytest.mark.skipif(
    not network_isolation_enforceable(),
    reason="network isolation requires an unprivileged network namespace",
)
def test_schedule_network_permission_controls_loopback_connection():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        probe = network_probe(port)

        undeclared_registry = AdapterRegistry()
        undeclared_registry.register(
            descriptor("alpha", required_permissions=frozenset())
        )
        undeclared = schedule(
            undeclared_registry,
            ("alpha",),
            {"alpha": probe},
            policy=policy(allowed_permissions=frozenset()),
        )

        declared_registry = AdapterRegistry()
        declared_registry.register(
            descriptor(
                "alpha",
                required_permissions=frozenset({"network.connect"}),
            )
        )
        declared = schedule(
            declared_registry,
            ("alpha",),
            {"alpha": probe},
            policy=policy(
                allowed_permissions=frozenset({"network.connect"})
            ),
        )

    assert undeclared.outcome == "exhausted"
    assert undeclared.selected_adapter_id is None
    assert undeclared.entries[0].terminal_state == "exited"
    assert undeclared.entries[0].exit_code != 0
    assert declared.outcome == "selected"
    assert declared.selected_adapter_id == "alpha"
    assert declared.entries[0].exit_code == 0


def test_failed_exit_falls_back_to_next_adapter():
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"alpha": argv(3), "beta": argv(0)})
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert [e.adapter_id for e in result.entries] == ["alpha", "beta"]
    assert result.entries[0].terminal_state == "exited"
    assert result.entries[0].exit_code == 3
    assert len(result.plans) == 2
    assert result.plans[1].fallback_from is None or result.plans[1].selected.adapter_id == "beta"
    # Each adapter attempt is its own reconciled sequence.
    assert len(result.sequences) == 2
    assert result.sequences[0].current.state == "exited"


def test_spawn_failure_and_timeout_fall_back():
    registry = registry_with("gone", "slow", "third")
    argvs = {
        "gone": ("definitely-missing-mumei-argv-target-xyz",),
        "slow": (PY, "-c", "import time; time.sleep(30)"),
        "third": argv(0),
    }
    result = schedule(
        registry,
        ("gone", "slow", "third"),
        argvs,
        policy=policy(timeout_ms=200),
    )
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "third"
    assert result.entries[0].terminal_state == "failed"
    assert result.entries[1].terminal_state == "timed_out"
    assert result.entries[2].terminal_state == "exited"


def test_all_candidates_fail_reports_exhausted():
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"alpha": argv(1), "beta": argv(2)})
    assert result.outcome == "exhausted"
    assert result.selected_adapter_id is None
    assert len(result.entries) == 2


def test_max_attempts_bounds_the_schedule():
    registry = registry_with(*(f"a{i}" for i in range(MAX_SCHEDULE_ATTEMPTS + 2)))
    argvs = {f"a{i}": argv(1) for i in range(MAX_SCHEDULE_ATTEMPTS + 2)}
    result = schedule(
        registry,
        tuple(argvs),
        argvs,
        max_attempts=3,
    )
    assert result.outcome == "exhausted"
    assert len(result.entries) == 3
    assert len(result.plans) == 3


def test_explicit_selection_without_fallback_denies_replan():
    registry = registry_with("alpha", "beta")
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": argv(1), "beta": argv(0)},
        policy=policy(selected_adapter="alpha"),
    )
    assert result.outcome == "fallback_denied"
    assert result.fallback_permitted is False
    assert len(result.entries) == 1


def test_explicit_selection_with_fallback_replans():
    registry = registry_with("alpha", "beta")
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": argv(1), "beta": argv(0)},
        policy=policy(selected_adapter="alpha", allow_fallback=True),
    )
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"


def test_no_selected_adapter_reports_not_schedulable():
    registry = AdapterRegistry()
    registry.register(descriptor("other"))
    result = run_attempt_schedule(
        registry,
        request(),
        policy(),
        SOURCE,
        hashlib.sha256(SOURCE).hexdigest(),
        lambda adapter_id: argv(0),
        observations=(),  # no availability declared → nothing eligible
    )
    assert result.outcome == "not_schedulable"
    assert result.entries == ()


def test_undeclared_argv_records_not_dispatched_and_falls_back():
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"beta": argv(0)})
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert result.entries[0].terminal_state == "not_dispatched"
    assert result.entries[0].request_fingerprint is None
    assert result.entries[0].to_dict()["enforcement"] is None
    # No argv → nothing was ever reserved, so no sequence exists for it.
    assert len(result.sequences) == 1


def test_unstamped_observations_still_fall_back():
    # Unstamped declarations are not retained by the registry's stamped
    # record — the schedule must replay the caller's tuple at replan.
    registry = registry_with("alpha", "beta")
    unstamped = tuple(
        RuntimeObservation(adapter_id, "available", "1.0.0")
        for adapter_id in ("alpha", "beta")
    )
    result = run_attempt_schedule(
        registry, request(), policy(), SOURCE,
        hashlib.sha256(SOURCE).hexdigest(),
        lambda adapter_id: {"alpha": argv(1), "beta": argv(0)}.get(adapter_id),
        observations=unstamped,
    )
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert [e.adapter_id for e in result.entries] == ["alpha", "beta"]


def test_cancel_event_stops_not_dispatched_rounds_too():
    registry = registry_with("alpha", "beta")
    event = threading.Event()
    event.set()
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"beta": argv(0)},  # alpha has no declared argv
        cancel_event=event,
    )
    assert result.outcome == "cancelled"
    assert result.entries == ()
    assert len(result.plans) == 1


def test_cancel_event_stops_schedule_without_fallback():
    registry = registry_with("alpha", "beta")
    event = threading.Event()
    event.set()
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": argv(0), "beta": argv(0)},
        cancel_event=event,
    )
    # A pre-declared stop holds before the first spawn: nothing was ever
    # attempted, so no entry is recorded.
    assert result.outcome == "cancelled"
    assert result.entries == ()


def test_cancel_event_mid_run_records_killed_child_and_stops():
    registry = registry_with("alpha", "beta")
    event = threading.Event()
    timer = threading.Timer(0.3, event.set)
    timer.start()
    try:
        result = schedule(
            registry,
            ("alpha", "beta"),
            {"alpha": (PY, "-c", "import time; time.sleep(30)"), "beta": argv(0)},
            cancel_event=event,
        )
    finally:
        timer.cancel()
    # The record honestly reports the killed child as `exited`; the
    # schedule outcome is what names the host's stop decision.
    assert result.outcome == "cancelled"
    assert result.entries[-1].terminal_state in {"exited", "cancelled"}
    assert len(result.entries) == 1


def test_success_exit_codes_are_host_declared():
    registry = registry_with("alpha")
    result = schedule(
        registry,
        ("alpha",),
        {"alpha": argv(7)},
        success_exit_codes=frozenset({7}),
    )
    assert result.outcome == "selected"
    # And a default policy treats the same exit as failure.
    registry2 = registry_with("alpha")
    result2 = schedule(registry2, ("alpha",), {"alpha": argv(7)})
    assert result2.outcome == "exhausted"


def test_static_rejections():
    registry = registry_with("alpha")
    sha = hashlib.sha256(SOURCE).hexdigest()
    for bad in (
        lambda: run_attempt_schedule(None, request(), policy(), SOURCE, sha, lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, "x", policy(), SOURCE, sha, lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, request(), None, SOURCE, sha, lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, request(), policy(), b"", sha, lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, "z" * 64, lambda a: argv(0), observations=observations("alpha")),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha.upper(), lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, "echo"),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), runner=object()),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), observations=[]),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), max_attempts=0),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), max_attempts=MAX_SCHEDULE_ATTEMPTS + 1),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), max_attempts="3"),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), success_exit_codes={0}),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), success_exit_codes=frozenset({"0"})),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), cancel_event=object()),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), stdin_for="x"),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), stdin_for=lambda a: "not-bytes", observations=observations("alpha")),
    ):
        with pytest.raises(ValueError):
            bad()


def test_result_declaration_rules():
    registry = registry_with("alpha")
    result = schedule(registry, ("alpha",), {"alpha": argv(0)})
    with pytest.raises(ValueError, match="invalid schedule outcome"):
        AttemptScheduleResult(
            result.entries, result.plans, result.sequences, "alpha", "bogus", True, 1
        )
    with pytest.raises(ValueError, match="a selected schedule must name its adapter"):
        AttemptScheduleResult(
            result.entries, result.plans, result.sequences, None, "selected", True, 1
        )
    with pytest.raises(ValueError, match="exceed the declared bound"):
        AttemptScheduleResult(
            result.entries * 2, result.plans, result.sequences, "alpha", "selected", True, 1
        )


def test_descriptor_stays_fingerprint_only(capsys):
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"alpha": argv(9), "beta": argv(0)})
    doc = result.to_dict()
    text = json.dumps(doc) + repr(result)
    assert "FAKE_PRIVATE" not in text
    assert SOURCE.decode() not in text
    assert PY not in text
    # Request fingerprints bind each attempt to its prepared request.
    assert all(
        len(entry["request_fingerprint"]) == 64
        for entry in doc["attempts"]
        if entry["request_fingerprint"] is not None
    )


def _argv_spew(text, code=0):
    return (
        PY,
        "-c",
        f"import sys; sys.stdout.write({text!r}); sys.exit({code})",
    )


def _registry_with_marker(stream, text, outcome):
    registry = AdapterRegistry()
    registry.register(
        descriptor(
            "alpha",
            priority=10,
            verdict_markers=(VerdictMarker(stream, text, outcome),),
        )
    )
    registry.register(descriptor("beta", priority=1))
    return registry


def test_failed_marker_withholds_success_and_falls_back():
    registry = _registry_with_marker("stdout", "FAILED", "failed")
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": _argv_spew("FAILED\n"), "beta": argv(0)},
    )

    alpha, beta = result.entries
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert alpha.adapter_id == "alpha"
    assert alpha.terminal_state == "exited"
    assert alpha.exit_code == 0
    assert alpha.reported_outcome == "failed"
    assert beta.adapter_id == "beta"
    assert beta.reported_outcome is None


def test_inconclusive_marker_on_stderr_withholds_success_and_falls_back():
    registry = _registry_with_marker("stderr", "INCONCLUSIVE", "inconclusive")
    argv_err = (
        PY,
        "-c",
        "import sys; sys.stderr.write('INCONCLUSIVE')",
    )
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": argv_err, "beta": argv(0)},
    )

    alpha, beta = result.entries
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert alpha.adapter_id == "alpha"
    assert alpha.terminal_state == "exited"
    assert alpha.exit_code == 0
    assert alpha.reported_outcome == "inconclusive"
    assert beta.adapter_id == "beta"


def test_failed_marker_with_explicit_selection_denies_fallback_without_core_check(
    tmp_path,
):
    registry = _registry_with_marker("stdout", "FAILED", "failed")
    core = _core_stub(tmp_path)
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": _argv_spew("FAILED\n"), "beta": argv(0)},
        policy=policy(selected_adapter="alpha"),
        core_executable=core,
    )

    assert result.outcome == "fallback_denied"
    assert result.selected_adapter_id is None
    assert result.entries[0].reported_outcome == "failed"
    assert result.evidence_check is None


def test_valid_marker_allows_success_exit_to_select():
    registry = _registry_with_marker("stdout", "VALID", "valid")
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": _argv_spew("VALID\n"), "beta": argv(0)},
    )

    assert result.outcome == "selected"
    assert result.selected_adapter_id == "alpha"
    assert result.entries[0].reported_outcome == "valid"


def test_valid_marker_does_not_rescue_non_success_exit():
    registry = _registry_with_marker("stdout", "VALID", "valid")
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": _argv_spew("VALID\n", code=1), "beta": argv(0)},
    )

    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert result.entries[0].terminal_state == "exited"
    assert result.entries[0].exit_code == 1
    assert result.entries[0].reported_outcome == "valid"


def test_verdict_marker_reports_declared_outcome():
    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            "alpha",
            "1.0.0",
            frozenset({PROFILE}),
            frozenset({CONTRACT.method}),
            priority=0,
            result_contracts=(CONTRACT,),
            input_formats=frozenset({SOURCE_INPUT_FORMAT}),
            required_permissions=frozenset(),
            verdict_markers=(
                VerdictMarker("stdout", "VERIFIED", "valid"),
                VerdictMarker("stdout", "REFUTED", "failed"),
            ),
        )
    )
    result = schedule(
        registry, ["alpha"], {"alpha": _argv_spew("REFUTED\n")}
    )
    entry = result.entries[0]
    assert entry.terminal_state == "exited"
    assert entry.reported_outcome == "failed"


def test_verdict_marker_first_match_wins_and_no_match_is_null():
    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            "alpha",
            "1.0.0",
            frozenset({PROFILE}),
            frozenset({CONTRACT.method}),
            priority=0,
            result_contracts=(CONTRACT,),
            input_formats=frozenset({SOURCE_INPUT_FORMAT}),
            required_permissions=frozenset(),
            verdict_markers=(
                VerdictMarker("stdout", "OK", "valid"),
                VerdictMarker("stdout", "OKAY", "failed"),
            ),
        )
    )
    matched = schedule(
        registry, ["alpha"], {"alpha": _argv_spew("OKAY")}
    )
    assert matched.entries[0].reported_outcome == "valid"

    quiet = schedule(
        registry, ["alpha"], {"alpha": _argv_spew("nothing here")}
    )
    assert quiet.entries[0].reported_outcome is None


def test_verdict_marker_stderr_stream():
    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            "alpha",
            "1.0.0",
            frozenset({PROFILE}),
            frozenset({CONTRACT.method}),
            priority=0,
            result_contracts=(CONTRACT,),
            input_formats=frozenset({SOURCE_INPUT_FORMAT}),
            required_permissions=frozenset(),
            verdict_markers=(
                VerdictMarker("stderr", "UNSAT", "failed"),
            ),
        )
    )
    argv_err = (
        PY,
        "-c",
        "import sys; sys.stderr.write('UNSAT'); sys.exit(0)",
    )
    result = schedule(registry, ["alpha"], {"alpha": argv_err})
    assert result.entries[0].reported_outcome == "failed"


def test_verdict_marker_validation():
    import pytest as _pytest

    with _pytest.raises(ValueError):
        VerdictMarker("stdin", "x", "valid")
    with _pytest.raises(ValueError):
        VerdictMarker("stdout", "", "valid")
    with _pytest.raises(ValueError):
        VerdictMarker("stdout", "x", "bogus")
    with _pytest.raises(ValueError):
        AdapterDescriptor.from_manifest(
            {
                "schema_version": "mumei.verifier-adapter/v1",
                "adapter_id": "alpha",
                "adapter_version": "1.0.0",
                "profiles": [PROFILE],
                "methods": ["deductive_proof"],
                "verdict_markers": [{"stream": "stdout"}],
            }
        )

def test_stdin_for_feeds_the_attempt_process():
    # A byte probe exits 0 only when the declared payload reaches stdin.
    registry = registry_with("alpha")
    probe = (
        PY,
        "-c",
        "import sys;"
        "sys.exit(0 if sys.stdin.buffer.read() == b'FEED' else 3)",
    )
    fed = schedule(
        registry,
        ("alpha",),
        {"alpha": probe},
        stdin_for=lambda adapter_id: b"FEED",
    )
    assert fed.outcome == "selected"
    unfed = schedule(registry, ("alpha",), {"alpha": probe})
    assert unfed.outcome == "exhausted"


def test_no_feed_closes_stdin_instead_of_inheriting():
    # With no declared feed the child's stdin is a closed pipe — the
    # probe sees EOF immediately rather than inheriting the parent's.
    registry = registry_with("alpha")
    probe = (
        PY,
        "-c",
        "import sys;"
        "sys.exit(0 if sys.stdin.buffer.read() == b'' else 5)",
    )
    result = schedule(registry, ("alpha",), {"alpha": probe})
    assert result.outcome == "selected"


@pytest.mark.skipif(
    not memory_bound_enforceable(),
    reason="memory bounds require a POSIX resource boundary",
)
def test_policy_memory_budget_caps_below_manifest_max():
    registry = AdapterRegistry()
    registry.register(descriptor("alpha", max_memory_mb=1024))
    probe = (
        PY,
        "-c",
        "x = bytearray(256 * 1024 * 1024); import sys; sys.exit(0)",
    )

    result = schedule(
        registry,
        ("alpha",),
        {"alpha": probe},
        policy=policy(memory_mb=64),
    )

    assert result.outcome != "selected"
    assert result.entries[0].terminal_state in {
        "exited",
        "failed",
        "timed_out",
    }


@pytest.mark.skipif(
    not memory_bound_enforceable(),
    reason="memory bounds require a POSIX resource boundary",
)
def test_manifest_memory_bound_caps_the_attempt_and_host_bound_overrides():
    # With a 1024 MiB policy budget, the plan's effective memory_mb is
    # capped by the manifest's max_memory_mb of 64 MiB.
    registry = AdapterRegistry()
    registry.register(descriptor("alpha", max_memory_mb=64))
    probe = (PY, "-c", "x = bytearray(256 * 1024 * 1024); import sys; sys.exit(0)")
    result = schedule(
        registry,
        ("alpha",),
        {"alpha": probe},
        policy=policy(memory_mb=1024),
    )
    assert result.outcome != "selected"
    assert result.entries[0].terminal_state in {"exited", "failed", "timed_out"}
    # An explicit host bound wins over the effective plan budget.
    result2 = schedule(
        registry,
        ("alpha",),
        {"alpha": probe},
        memory_bound_mb=1024,
        policy=policy(memory_mb=1024),
    )
    assert result2.outcome == "selected"

def test_manifest_memory_bound_skipped_without_posix_mechanism(monkeypatch):
    # A platform with no ``resource``/``prlimit``/``sh`` cannot enforce a
    # bound — the manifest fallback stays unenforced instead of breaking
    # the schedule (an explicit host bound still fails statically).
    monkeypatch.setattr(
        "agent.attempt_schedule.memory_bound_enforceable", lambda: False
    )
    registry = AdapterRegistry()
    registry.register(descriptor("alpha", max_memory_mb=64))
    probe = (PY, "-c", "import sys; sys.exit(0)")
    result = schedule(registry, ("alpha",), {"alpha": probe})
    assert result.outcome == "selected"

_CORE_DIAGNOSTIC = {
    "schema_version": "mumei.evidence-representation-check/v1",
    "evidence_schema_version": "mumei.verification-evidence/v1",
    "representation": "valid",
    "acceptance": "not_evaluated",
    "checks_not_performed": [
        "claim_truth",
        "file_identity",
        "freshness",
        "producer_authenticity",
        "semantic_correspondence",
        "artifact_semantics",
    ],
}


def _core_stub(tmp_path, exit_code=0):
    # Stub Core: `evidence check` drains stdin and emits the v1
    # diagnostic — or exits `exit_code` with no diagnostic.
    core = tmp_path / "mumei-stub"
    body = (
        "    printf %s '" + json.dumps(_CORE_DIAGNOSTIC) + "'\n    exit 0\n"
        if exit_code == 0
        else f"    exit {exit_code}\n"
    )
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
        "    cat > /dev/null\n"
        + body +
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return str(core)


def test_selected_attempt_records_evidence_check_and_acceptance(tmp_path):
    registry = registry_with("alpha")
    core = _core_stub(tmp_path)
    result = schedule(
        registry, ("alpha",), {"alpha": argv(0)}, core_executable=core
    )
    assert result.outcome == "selected"
    assert result.evidence_check is not None
    assert result.evidence_check.outcome == "valid"
    assert result.evidence_acceptance["accepted"] is True
    assert result.evidence_acceptance["schema_version"] == (
        "mumei.evidence-check-acceptance/v1"
    )
    # The selected sequence gained the canonical-result selection.
    assert result.sequences[-1].selected_result is not None
    doc = result.to_dict()
    assert doc["evidence_check"]["schema_version"] == (
        "mumei.verifier-evidence-check/v1"
    )
    assert doc["evidence_acceptance"]["accepted"] is True


def test_no_core_leaves_evidence_fields_absent():
    registry = registry_with("alpha")
    result = schedule(registry, ("alpha",), {"alpha": argv(0)})
    assert result.outcome == "selected"
    assert result.evidence_check is None
    assert result.evidence_acceptance is None
    doc = result.to_dict()
    assert doc["evidence_check"] is None
    assert doc["evidence_acceptance"] is None


def test_failed_check_records_outcome_without_acceptance(tmp_path):
    registry = registry_with("alpha")
    core = _core_stub(tmp_path, exit_code=1)
    result = schedule(
        registry, ("alpha",), {"alpha": argv(0)}, core_executable=core
    )
    assert result.outcome == "selected"
    assert result.evidence_check.outcome == "failed"
    assert result.evidence_acceptance["accepted"] is False


def test_unselected_attempt_runs_no_check(tmp_path):
    registry = registry_with("alpha")
    core = _core_stub(tmp_path)
    result = schedule(
        registry, ("alpha",), {"alpha": argv(1)},
        policy=policy(allow_fallback=False),
        core_executable=core,
    )
    assert result.outcome != "selected"
    assert result.evidence_check is None
    assert result.evidence_acceptance is None
