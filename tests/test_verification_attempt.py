"""Host-observation contracts only: no runner, authority or Evidence consumer."""

import builtins
import hashlib
import importlib
import itertools
import json
import os
import socket
import subprocess
import time
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from agent.verification_attempt import (
    EVENT_KINDS,
    MAX_COUNTER,
    MAX_EVENTS,
    AttemptEvent,
    AttemptRecord,
)
from agent.verification_planner import (
    SOURCE_INPUT_FORMAT,
    AdapterDescriptor,
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
    RuntimeObservation,
)

FINGERPRINT = "a" * 64
SOURCE = b"FAKE_PRIVATE_SOURCE_NOT_EVIDENCE"
PROFILE = "mumei.test/v1"
CONTRACT = ResultContract(
    PROFILE, "deductive_proof", "unbounded", "mumei.source-model/v1", "assumed"
)


def prepared_source(*, policy=None, registry=None):
    if registry is None:
        registry = AdapterRegistry()
        registry.register(
            AdapterDescriptor(
                "fixture",
                "1.0.0",
                frozenset({PROFILE}),
                frozenset({CONTRACT.method}),
                result_contracts=(CONTRACT,),
                input_formats=frozenset({SOURCE_INPUT_FORMAT}),
                required_permissions=frozenset(),
            )
        )
    return registry.prepare_source(
        RouteRequirements(
            PROFILE,
            CONTRACT.method,
            result_contract=CONTRACT,
            input_format=SOURCE_INPUT_FORMAT,
        ),
        policy
        if policy is not None
        else PlannerPolicy(allowed_permissions=frozenset(), timeout_ms=10),
        (RuntimeObservation("fixture", "available", "1.0.0"),),
        SOURCE,
        hashlib.sha256(SOURCE).hexdigest(),
    )


def record(*events, **kwargs):
    return AttemptRecord(FINGERPRINT, 1, 10, tuple(events), **kwargs)


START = AttemptEvent("started", 0)
CANCEL = AttemptEvent("cancel_requested", 2)
PREFIXES = {
    "ready": (),
    "running": (START,),
    "cancelling": (START, CANCEL),
    "exited": (START, AttemptEvent("exited", 3, 0)),
    "failed": (START, AttemptEvent("failed", 3)),
    "timed_out": (START, AttemptEvent("timed_out", 10)),
    "cancelled": (START, CANCEL, AttemptEvent("cancelled", 3)),
}
ALLOWED = {
    ("ready", "started"),
    ("running", "cancel_requested"),
    ("running", "exited"),
    ("running", "failed"),
    ("running", "timed_out"),
    ("cancelling", "exited"),
    ("cancelling", "failed"),
    ("cancelling", "timed_out"),
    ("cancelling", "cancelled"),
}


@pytest.mark.parametrize("state", PREFIXES)
@pytest.mark.parametrize("kind", sorted(EVENT_KINDS))
def test_complete_state_event_transition_matrix(state, kind):
    initial = record(*PREFIXES[state])
    elapsed = 0 if kind == "started" else (10 if kind == "timed_out" else 3)
    event = AttemptEvent(kind, elapsed, 0 if kind == "exited" else None)
    if (state, kind) not in ALLOWED:
        with pytest.raises(ValueError):
            initial.record(event)
    else:
        result = initial.record(event)
        expected = {"started": "running", "cancel_requested": "cancelling"}.get(
            kind, kind
        )
        assert result.state == expected
        assert result.is_terminal == (
            expected not in {"ready", "running", "cancelling"}
        )
        assert initial.events == PREFIXES[state]
        assert result.events == (*initial.events, event)


@pytest.mark.parametrize(
    "code", [-(1 << 63), -9, -1, 0, 1, 127, 255, 0xC0000005, MAX_COUNTER]
)
def test_exit_codes_are_process_observations_not_verification_success(code):
    result = record(START, AttemptEvent("exited", 9, code))
    data = result.to_dict()
    assert result.state == "exited" and result.is_terminal
    assert data["events"][-1]["exit_code"] == code
    for key in ("success", "proved", "accepted", "evidence", "authorization", "grade"):
        assert f'"{key}"' not in json.dumps(data)


@pytest.mark.parametrize("kind", sorted(EVENT_KINDS - {"exited"}))
@pytest.mark.parametrize("code", [False, 0, 1, "FAKE_PRIVATE_OUTPUT_DO_NOT_ECHO"])
def test_non_exit_events_cannot_carry_outputs_or_exit_codes(kind, code):
    with pytest.raises(ValueError):
        AttemptEvent(kind, 0, code)


@pytest.mark.parametrize(
    "code",
    [
        None,
        False,
        True,
        0.0,
        "FAKE_PRIVATE_OUTPUT_DO_NOT_ECHO",
        -(1 << 63) - 1,
        MAX_COUNTER + 1,
    ],
)
def test_exited_requires_exact_bounded_integer_code(code):
    with pytest.raises(ValueError):
        AttemptEvent("exited", 1, code)


@pytest.mark.parametrize(
    "kind", [None, False, 1, [], {}, "success", "FAKE_PRIVATE_OUTPUT_DO_NOT_ECHO"]
)
def test_unknown_event_kinds_are_static_errors_without_payload_echo(kind):
    with pytest.raises(ValueError) as error:
        AttemptEvent(kind, 0)
    assert "FAKE_PRIVATE_OUTPUT_DO_NOT_ECHO" not in str(error.value)


@pytest.mark.parametrize(
    "value",
    [None, False, True, -1, 1.5, "FAKE_PRIVATE_OUTPUT_DO_NOT_ECHO", MAX_COUNTER + 1],
)
def test_elapsed_counters_are_exact_nonnegative_bounded_integers(value):
    with pytest.raises(ValueError):
        AttemptEvent("failed", value)


@pytest.mark.parametrize("field", ["attempt_number", "timeout_ms"])
@pytest.mark.parametrize(
    "value",
    [None, False, True, -1, 0, 0.5, "FAKE_PRIVATE_OUTPUT_DO_NOT_ECHO", MAX_COUNTER + 1],
)
def test_attempt_numbers_and_budgets_require_positive_bounded_integers(field, value):
    with pytest.raises(ValueError):
        replace(record(), **{field: value})


@pytest.mark.parametrize(
    "value",
    [
        None,
        False,
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "z" * 64,
        "FAKE_PRIVATE_OUTPUT_DO_NOT_ECHO",
    ],
)
def test_fingerprint_is_canonical_digest_not_an_arbitrary_id_channel(value):
    with pytest.raises(ValueError):
        replace(record(), request_fingerprint=value)


@pytest.mark.parametrize(
    "value",
    [None, [], [START], (None,), ({"kind": "started"},), (START,) * (MAX_EVENTS + 1)],
)
def test_histories_are_bounded_immutable_typed_events(value):
    with pytest.raises(ValueError):
        replace(record(), events=value)


@pytest.mark.parametrize("value", [1, 10, MAX_COUNTER])
def test_start_defines_elapsed_zero(value):
    with pytest.raises(ValueError):
        record(AttemptEvent("started", value))


@pytest.mark.parametrize("kind", ["exited", "failed", "cancelled"])
def test_backwards_elapsed_reports_cannot_become_terminal(kind):
    with pytest.raises(ValueError):
        record(START, CANCEL, AttemptEvent(kind, 1, 0 if kind == "exited" else None))


@pytest.mark.parametrize("elapsed", [0, 9, 10, 11, MAX_COUNTER])
def test_timeout_and_exit_use_disjoint_deadline_boundaries(elapsed):
    running = record(START)
    if elapsed < 10:
        assert running.record(AttemptEvent("exited", elapsed, 0)).state == "exited"
        with pytest.raises(ValueError):
            running.record(AttemptEvent("timed_out", elapsed))
    else:
        assert running.record(AttemptEvent("timed_out", elapsed)).state == "timed_out"
        with pytest.raises(ValueError):
            running.record(AttemptEvent("exited", elapsed, 0))


def test_cancel_request_is_not_acknowledgement_and_exit_race_is_explicit():
    pending = record(START).record(CANCEL)
    assert pending.state == "cancelling" and not pending.is_terminal
    assert pending.record(AttemptEvent("cancelled", 2)).state == "cancelled"
    assert pending.record(AttemptEvent("exited", 2, 0)).state == "exited"
    assert pending.record(AttemptEvent("timed_out", 10)).state == "timed_out"


def test_direct_construction_cannot_bypass_transition_validation():
    for events in (
        (CANCEL,),
        (START, START),
        (START, CANCEL, CANCEL),
        (START, AttemptEvent("cancelled", 1)),
    ):
        with pytest.raises(ValueError):
            record(*events)


def test_binding_retains_only_fingerprint_budget_and_host_attempt_number():
    prepared = prepared_source()
    result = AttemptRecord.from_prepared(prepared, 7)
    assert result.request_fingerprint == prepared.to_dict()["request_fingerprint"]
    assert result.attempt_number == 7 and result.timeout_ms == 10
    assert result.state == "ready" and not result.is_terminal
    assert result.to_dict() == {
        "schema_version": "mumei.verifier-attempt/v1",
        "request_fingerprint": result.request_fingerprint,
        "attempt_number": 7,
        "timeout_ms": 10,
        "state": "ready",
        "events": [],
    }
    assert SOURCE.decode() not in repr(result) + json.dumps(result.to_dict())
    assert "source" not in vars(result) and "plan" not in vars(result)


@pytest.mark.parametrize(
    "value", [None, {}, "FAKE_PRIVATE_OUTPUT_DO_NOT_ECHO", object()]
)
def test_binding_rejects_non_prepared_values_without_implicit_conversions(value):
    with pytest.raises(ValueError):
        AttemptRecord.from_prepared(value, 1)


def test_binding_requires_explicit_permission_policy_but_never_authenticates_it():
    with pytest.raises(ValueError):
        AttemptRecord.from_prepared(prepared_source(policy=PlannerPolicy()), 1)
    # The host still owns uniqueness, authority and current preflight.
    prepared = prepared_source()
    assert AttemptRecord.from_prepared(prepared, 1) == AttemptRecord.from_prepared(
        prepared, 1
    )
    assert AttemptRecord.from_prepared(prepared, 1) != AttemptRecord.from_prepared(
        prepared, 2
    )


def test_records_are_immutable_and_json_is_detached():
    result = record(START)
    with pytest.raises(FrozenInstanceError):
        result.events = ()
    with pytest.raises(FrozenInstanceError):
        START.elapsed_ms = 9
    data = result.to_dict()
    data["events"][0]["kind"] = "success"
    assert result.state == "running"
    assert json.loads(json.dumps(result.to_dict())) == result.to_dict()


def test_counter_endpoints_and_minimum_budget_are_representable():
    result = AttemptRecord(FINGERPRINT, MAX_COUNTER, MAX_COUNTER)
    assert (
        result.record(START).record(AttemptEvent("timed_out", MAX_COUNTER)).is_terminal
    )
    assert (
        replace(result, timeout_ms=1)
        .record(START)
        .record(AttemptEvent("exited", 0, 0))
        .is_terminal
    )


def test_recording_does_not_read_clocks_files_env_plugins_network_or_execute(
    monkeypatch, capsys
):
    prepared = prepared_source()

    def forbidden(*args, **kwargs):
        pytest.fail("attempt observations must remain pure metadata")

    for owner, name in (
        (builtins, "open"),
        (Path, "open"),
        (Path, "read_text"),
        (Path, "read_bytes"),
        (os, "getenv"),
        (socket, "socket"),
        (subprocess, "run"),
        (subprocess, "Popen"),
        (importlib, "import_module"),
        (time, "monotonic"),
        (time, "time"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    result = AttemptRecord.from_prepared(prepared, 1).record(START).record(CANCEL)
    result = result.record(AttemptEvent("cancelled", 2))
    assert result.state == "cancelled"
    with pytest.raises(ValueError) as error:
        result.record(AttemptEvent("exited", 3, 0))
    assert SOURCE.decode() not in str(error.value)
    json.dumps(result.to_dict())
    output = capsys.readouterr()
    assert SOURCE.decode() not in output.out + output.err


def test_tuple_subclasses_cannot_supply_mutable_or_executable_histories():
    class MutableEvents(tuple):
        def __len__(self):
            pytest.fail("custom history length must not be consulted")

        def __iter__(self):
            pytest.fail("custom history iteration must not be executed")

    with pytest.raises(ValueError):
        replace(record(), events=MutableEvents((START,)))


@pytest.mark.parametrize("field", ["kind", "request_fingerprint"])
def test_string_subclasses_cannot_override_closed_metadata_semantics(field):
    class CustomString(str):
        def __hash__(self):
            pytest.fail("custom metadata hashing must not be executed")

        def __eq__(self, other):
            pytest.fail("custom metadata equality must not be executed")

    with pytest.raises(ValueError):
        if field == "kind":
            AttemptEvent(CustomString("started"), 0)
        else:
            replace(record(), request_fingerprint=CustomString(FINGERPRINT))


@pytest.mark.parametrize("current_state", PREFIXES)
@pytest.mark.parametrize("incoming_state", PREFIXES)
def test_reconcile_complete_state_pair_matrix(current_state, incoming_state):
    current = record(*PREFIXES[current_state])
    incoming = record(*PREFIXES[incoming_state])
    before = current.to_dict(), incoming.to_dict()
    if incoming.events[: len(current.events)] != current.events:
        with pytest.raises(ValueError):
            current.reconcile(incoming)
    else:
        result = current.reconcile(incoming)
        assert result is (current if current.events == incoming.events else incoming)
        assert result.to_dict() == incoming.to_dict()
    assert before == (current.to_dict(), incoming.to_dict())


@pytest.mark.parametrize("current_state", PREFIXES)
@pytest.mark.parametrize("incoming_state", PREFIXES)
@pytest.mark.parametrize(
    ("field", "value"),
    [("request_fingerprint", "b" * 64), ("attempt_number", 2), ("timeout_ms", 9)],
)
def test_reconcile_checks_all_binding_fields_before_history(
    current_state, incoming_state, field, value
):
    current = replace(record(*PREFIXES[current_state]), **{field: value})
    incoming = record(*PREFIXES[incoming_state])
    with pytest.raises(ValueError, match="binding mismatch"):
        current.reconcile(incoming)


@pytest.mark.parametrize("state", PREFIXES)
def test_reconcile_identical_detached_reports_return_the_current_record(state):
    current = record(*PREFIXES[state])
    duplicate = replace(current)
    assert duplicate is not current
    assert current.reconcile(duplicate) is current
    assert current.reconcile(current) is current


@pytest.mark.parametrize(
    ("current_events", "incoming_events"),
    [
        ((START, CANCEL), (START, AttemptEvent("cancel_requested", 1))),
        ((START, CANCEL), (START, AttemptEvent("cancel_requested", 3))),
        ((START, CANCEL), (START, AttemptEvent("exited", 3, 0))),
        ((START, AttemptEvent("exited", 3, 0)), (START, AttemptEvent("exited", 3, 1))),
        ((START, AttemptEvent("exited", 3, 0)), (START, AttemptEvent("exited", 4, 0))),
        ((START, AttemptEvent("failed", 3)), (START, AttemptEvent("failed", 4))),
        (
            (START, AttemptEvent("timed_out", 10)),
            (START, AttemptEvent("timed_out", 11)),
        ),
        (
            (START, CANCEL, AttemptEvent("cancelled", 2)),
            (START, CANCEL, AttemptEvent("cancelled", 3)),
        ),
    ],
)
def test_reconcile_never_rewrites_existing_event_payloads(
    current_events, incoming_events
):
    current = record(*current_events)
    incoming = record(*incoming_events)
    for left, right in ((current, incoming), (incoming, current)):
        with pytest.raises(ValueError):
            left.reconcile(right)


@pytest.mark.parametrize(
    "state", [s for s in PREFIXES if s not in {"ready", "running"}]
)
def test_reconcile_cannot_skip_or_synthesize_missing_history(state):
    current = record(*PREFIXES[state])
    for size in range(len(current.events)):
        with pytest.raises(ValueError):
            current.reconcile(record(*current.events[:size]))
    assert record().reconcile(current) is current


@pytest.mark.parametrize("state", ["exited", "failed", "timed_out", "cancelled"])
def test_reconcile_out_of_order_delivery_only_advances_a_known_lineage(state):
    events = PREFIXES[state]
    reports = tuple(record(*events[:size]) for size in range(len(events) + 1))
    for deliveries in itertools.permutations(reports):
        current = record()
        for incoming in deliveries:
            if len(incoming.events) < len(current.events):
                with pytest.raises(ValueError):
                    current.reconcile(incoming)
            else:
                current = current.reconcile(incoming)
        assert current == reports[-1]


@pytest.mark.parametrize(
    "incoming",
    [None, False, 0, "FAKE_PRIVATE_REPORT", [], {}, object()],
    ids=["none", "bool", "int", "private-str", "list", "dict", "object"],
)
def test_reconcile_rejects_non_records_without_payload_echo(incoming):
    with pytest.raises(ValueError) as error:
        record().reconcile(incoming)
    assert "FAKE_PRIVATE_REPORT" not in str(error.value)


def test_reconcile_rejects_record_subclasses_without_running_custom_behavior():
    class CustomRecord(AttemptRecord):
        def __getattribute__(self, name):
            pytest.fail("incoming subclass behavior must not run")

    incoming = object.__new__(CustomRecord)
    with pytest.raises(ValueError):
        record().reconcile(incoming)


def test_reconcile_preserves_prepared_binding_and_does_not_accept_other_attempts():
    prepared = prepared_source()
    initial = AttemptRecord.from_prepared(prepared, 1)
    running = initial.record(START)
    exited = running.record(AttemptEvent("exited", 9, 0))
    assert (
        initial.reconcile(exited).request_fingerprint
        == prepared.to_dict()["request_fingerprint"]
    )
    assert running.reconcile(exited).state == "exited"
    with pytest.raises(ValueError):
        initial.reconcile(AttemptRecord.from_prepared(prepared, 2))
    other = prepared_source(
        policy=PlannerPolicy(allowed_permissions=frozenset(), timeout_ms=9)
    )
    with pytest.raises(ValueError):
        initial.reconcile(AttemptRecord.from_prepared(other, 1))


@pytest.mark.parametrize("code", [-(1 << 63), -1, 0, 1, MAX_COUNTER])
def test_reconcile_bounded_endpoints_and_exit_zero_still_have_no_success(code):
    initial = replace(record(), attempt_number=MAX_COUNTER, timeout_ms=MAX_COUNTER)
    exited = initial.record(START).record(AttemptEvent("exited", MAX_COUNTER - 1, code))
    assert initial.reconcile(exited) is exited
    assert exited.reconcile(replace(exited)) is exited
    assert set(exited.to_dict()) == {
        "schema_version",
        "request_fingerprint",
        "attempt_number",
        "timeout_ms",
        "state",
        "events",
    }
    assert exited.to_dict()["schema_version"] == "mumei.verifier-attempt/v1"


def test_reconcile_needs_no_io_clocks_authority_or_evidence(monkeypatch, capsys):
    initial = AttemptRecord.from_prepared(prepared_source(), 1)
    pending = initial.record(START).record(CANCEL)
    cancelled = pending.record(AttemptEvent("cancelled", MAX_COUNTER))
    exited = pending.record(AttemptEvent("exited", 3, 0))

    def forbidden(*args, **kwargs):
        pytest.fail("reconciliation must remain passive metadata")

    for owner, name in (
        (builtins, "open"),
        (Path, "open"),
        (Path, "read_text"),
        (Path, "read_bytes"),
        (os, "getenv"),
        (socket, "socket"),
        (subprocess, "run"),
        (subprocess, "Popen"),
        (importlib, "import_module"),
        (time, "monotonic"),
        (time, "time"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    assert initial.reconcile(pending).reconcile(cancelled) is cancelled
    assert pending.state == "cancelling" and not pending.is_terminal
    with pytest.raises(ValueError):
        cancelled.reconcile(exited)
    with pytest.raises(ValueError):
        exited.reconcile(cancelled)
    detached = cancelled.to_dict()
    detached["events"].clear()
    assert cancelled.state == "cancelled"
    assert SOURCE.decode() not in repr(cancelled) + json.dumps(cancelled.to_dict())
    output = capsys.readouterr()
    assert not output.out and not output.err


def test_reconcile_does_not_claim_global_branch_arbitration_or_replay_protection():
    common = record(START)
    zero = common.record(AttemptEvent("exited", 3, 0))
    nonzero = common.record(AttemptEvent("exited", 3, 1))
    assert common.reconcile(zero) is zero
    assert common.reconcile(nonzero) is nonzero
    for current, conflict in ((zero, nonzero), (nonzero, zero)):
        assert current.reconcile(replace(current)) is current
        with pytest.raises(ValueError):
            current.reconcile(conflict)
