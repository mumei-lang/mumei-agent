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
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from agent.verification_attempt import (
    EVENT_KINDS,
    MAX_COUNTER,
    MAX_EVENTS,
    MAX_JSON_DEPTH,
    MAX_JSON_NUMBER_CHARS,
    MAX_STDOUT_BYTES,
    AttemptEvent,
    AttemptOutput,
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


STDOUT = b"FAKE_PRIVATE_STDOUT_NOT_EVIDENCE"


def output_snapshot(attempt=None, stdout=STDOUT):
    return AttemptOutput(
        record(*PREFIXES["exited"]) if attempt is None else attempt,
        stdout,
        hashlib.sha256(stdout).hexdigest(),
    )


@pytest.mark.parametrize("state", PREFIXES)
@pytest.mark.parametrize("stdout", [b"", STDOUT], ids=["empty", "private"])
def test_output_requires_an_exited_record_not_just_a_terminal_state(state, stdout):
    attempt = record(*PREFIXES[state])
    if state == "exited":
        assert output_snapshot(attempt, stdout).attempt is attempt
    else:
        with pytest.raises(ValueError, match="exited attempt record"):
            output_snapshot(attempt, stdout)


@pytest.mark.parametrize("cancel_requested", [False, True])
@pytest.mark.parametrize("exit_code", [-MAX_COUNTER - 1, -1, 0, 1, MAX_COUNTER])
@pytest.mark.parametrize("elapsed_ms", [0, 2, 9])
def test_output_exit_is_not_success_and_does_not_acknowledge_cancel(
    cancel_requested, exit_code, elapsed_ms
):
    events = (
        (START, AttemptEvent("cancel_requested", 0)) if cancel_requested else (START,)
    )
    attempt = record(*events, AttemptEvent("exited", elapsed_ms, exit_code))
    snapshot = output_snapshot(attempt)
    assert snapshot.attempt.state == "exited"
    assert snapshot.attempt.events[-1].exit_code == exit_code
    assert not {"result", "success", "accepted", "evidence", "proved"} & (
        snapshot.to_dict().keys() | vars(snapshot).keys()
    )


@pytest.mark.parametrize(
    "stdout",
    [b"", b"\xff\x00", b"{", b'{"success":true,"success":false}', STDOUT],
    ids=["empty", "binary", "invalid-json", "duplicate-json", "private"],
)
def test_output_bytes_are_opaque_not_utf8_json_or_evidence(stdout):
    snapshot = output_snapshot(stdout=stdout)
    assert snapshot.stdout is stdout
    assert snapshot.to_dict()["stdout"] == {
        "sha256": hashlib.sha256(stdout).hexdigest(),
        "size_bytes": len(stdout),
    }


@pytest.mark.parametrize("size", [0, 1, MAX_STDOUT_BYTES - 1, MAX_STDOUT_BYTES])
def test_output_byte_bound_includes_empty_and_exact_limit(size):
    assert len(output_snapshot(stdout=b"x" * size).stdout) == size


def test_output_oversize_is_rejected_not_truncated_or_hashed(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("oversize stdout must be rejected before hashing")

    monkeypatch.setattr(hashlib, "sha256", forbidden)
    with pytest.raises(ValueError, match="bounded immutable bytes"):
        AttemptOutput(
            record(*PREFIXES["exited"]), b"x" * (MAX_STDOUT_BYTES + 1), "a" * 64
        )


@pytest.mark.parametrize(
    "value", [None, STDOUT.decode(), bytearray(STDOUT), memoryview(STDOUT), (), True]
)
def test_output_rejects_non_bytes_without_echoing_payload(value):
    with pytest.raises(ValueError) as error:
        AttemptOutput(record(*PREFIXES["exited"]), value, "a" * 64)
    assert STDOUT.decode() not in str(error.value)


@pytest.mark.parametrize(
    "digest",
    [None, True, "", "a" * 63, "a" * 65, "G" * 64, "A" * 64, STDOUT.decode(), "a" * 64],
)
def test_output_requires_exact_lowercase_and_matching_sha256(digest):
    with pytest.raises(ValueError) as error:
        AttemptOutput(record(*PREFIXES["exited"]), STDOUT, digest)
    assert STDOUT.decode() not in str(error.value)


def test_output_from_prepared_checks_external_attempt_number_and_manifest_binding():
    prepared = prepared_source()
    current = AttemptRecord.from_prepared(prepared, 7).record(START)
    reported = current.record(AttemptEvent("exited", 3, 0))
    current = current.reconcile(reported)
    snapshot = AttemptOutput.from_prepared(
        prepared, 7, current, STDOUT, hashlib.sha256(STDOUT).hexdigest()
    )
    assert snapshot.attempt is current
    assert (
        snapshot.attempt.request_fingerprint
        == prepared.to_dict()["request_fingerprint"]
    )
    for conflicting in (
        replace(current, request_fingerprint="b" * 64),
        replace(current, attempt_number=8),
        replace(current, timeout_ms=11),
    ):
        with pytest.raises(ValueError, match="binding mismatch"):
            AttemptOutput.from_prepared(
                prepared, 7, conflicting, STDOUT, hashlib.sha256(STDOUT).hexdigest()
            )
    other = prepared_source(
        policy=PlannerPolicy(allowed_permissions=frozenset(), timeout_ms=11)
    )
    with pytest.raises(ValueError, match="binding mismatch"):
        AttemptOutput.from_prepared(
            other, 7, current, STDOUT, hashlib.sha256(STDOUT).hexdigest()
        )


@pytest.mark.parametrize(
    "number", [None, False, True, 0, -1, 1.0, "1", MAX_COUNTER + 1]
)
def test_output_from_prepared_requires_a_bounded_external_attempt_number(number):
    with pytest.raises(ValueError):
        AttemptOutput.from_prepared(
            prepared_source(),
            number,
            record(*PREFIXES["exited"]),
            STDOUT,
            hashlib.sha256(STDOUT).hexdigest(),
        )


def test_output_from_prepared_does_not_accept_an_unspecified_permission_policy():
    with pytest.raises(ValueError, match="explicit permission policy"):
        AttemptOutput.from_prepared(
            prepared_source(policy=PlannerPolicy()),
            1,
            record(*PREFIXES["exited"]),
            STDOUT,
            hashlib.sha256(STDOUT).hexdigest(),
        )


@pytest.mark.parametrize("value", [None, {}, STDOUT, "a" * 64, True])
def test_output_rejects_non_records_in_constructor_and_binding(value):
    digest = hashlib.sha256(STDOUT).hexdigest()
    with pytest.raises(ValueError):
        AttemptOutput(value, STDOUT, digest)
    with pytest.raises(ValueError):
        AttemptOutput.from_prepared(prepared_source(), 1, value, STDOUT, digest)
    with pytest.raises(ValueError):
        AttemptOutput.from_prepared(
            value, 1, record(*PREFIXES["exited"]), STDOUT, digest
        )


def test_output_exact_types_reject_subclasses_without_running_overrides():
    class HostileBytes(bytes):
        def __len__(self):
            pytest.fail("bytes subclass length must not run")

    class HostileDigest(str):
        def __str__(self):
            pytest.fail("digest subclass string conversion must not run")

    class HostileRecord(AttemptRecord):
        @property
        def state(self):
            pytest.fail("record subclass state must not run")

    class HostileOutput(AttemptOutput):
        def __eq__(self, other):
            pytest.fail("output subclass equality must not run")

    attempt = record(*PREFIXES["exited"])
    digest = hashlib.sha256(STDOUT).hexdigest()
    for args in (
        (attempt, HostileBytes(STDOUT), digest),
        (attempt, STDOUT, HostileDigest(digest)),
        (HostileRecord("a" * 64, 1, 10, attempt.events), STDOUT, digest),
    ):
        with pytest.raises(ValueError):
            AttemptOutput(*args)
    with pytest.raises(ValueError):
        output_snapshot().reconcile(HostileOutput(attempt, STDOUT, digest))


def test_output_manifest_is_canonical_detached_and_body_free(capsys):
    snapshot = output_snapshot()
    manifest = snapshot.to_dict()
    assert set(manifest) == {
        "schema_version",
        "attempt",
        "stdout",
        "output_fingerprint",
    }
    assert manifest["schema_version"] == "mumei.verifier-output/v1"
    unsigned = {
        key: value for key, value in manifest.items() if key != "output_fingerprint"
    }
    assert (
        manifest["output_fingerprint"]
        == hashlib.sha256(
            json.dumps(
                unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
    )
    assert STDOUT.decode() not in repr(snapshot) + json.dumps(manifest)
    assert SOURCE.decode() not in repr(snapshot) + json.dumps(manifest)
    assert set(vars(snapshot)) == {"attempt", "stdout", "expected_stdout_sha256"}
    manifest["attempt"]["events"].clear()
    manifest["stdout"]["sha256"] = "b" * 64
    assert snapshot.attempt.state == "exited"
    assert snapshot.to_dict() == output_snapshot().to_dict()
    with pytest.raises(FrozenInstanceError):
        snapshot.stdout = b""
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_fingerprint", "b" * 64),
        ("attempt_number", 2),
        ("timeout_ms", 11),
        ("events", (START, AttemptEvent("exited", 4, 0))),
        ("events", (START, AttemptEvent("exited", 3, 1))),
        ("events", (START, CANCEL, AttemptEvent("exited", 3, 0))),
    ],
)
def test_output_reconcile_and_fingerprint_cover_every_attempt_binding(field, value):
    current = output_snapshot()
    changed = output_snapshot(replace(current.attempt, **{field: value}))
    assert (
        current.to_dict()["output_fingerprint"]
        != changed.to_dict()["output_fingerprint"]
    )
    for left, right in ((current, changed), (changed, current)):
        with pytest.raises(ValueError, match="output report conflict"):
            left.reconcile(right)


@pytest.mark.parametrize("left", [b"", b"a", b"b", b"aa"])
@pytest.mark.parametrize("right", [b"", b"a", b"b", b"aa"])
def test_output_reconciliation_is_exactly_idempotent_not_last_writer_wins(left, right):
    current, incoming = output_snapshot(stdout=left), output_snapshot(stdout=right)
    before = current.to_dict(), incoming.to_dict()
    if left == right:
        assert current.reconcile(incoming) is current
        assert incoming.reconcile(current) is incoming
    else:
        assert before[0]["output_fingerprint"] != before[1]["output_fingerprint"]
        with pytest.raises(ValueError, match="output report conflict"):
            current.reconcile(incoming)
    assert (current.to_dict(), incoming.to_dict()) == before


@pytest.mark.parametrize(
    "incoming", [None, True, STDOUT, {}, (), "FAKE_PRIVATE_INCOMING"]
)
def test_output_reconcile_rejects_non_outputs_without_payload_echo(incoming):
    with pytest.raises(ValueError) as error:
        output_snapshot().reconcile(incoming)
    assert "FAKE_PRIVATE" not in str(error.value)


def test_output_preparation_and_reconciliation_need_no_io_clock_or_evidence(
    monkeypatch, capsys
):
    prepared = prepared_source()
    reported = (
        AttemptRecord.from_prepared(prepared, 1)
        .record(START)
        .record(AttemptEvent("exited", 3, 0))
    )

    def forbidden(*args, **kwargs):
        pytest.fail(
            "output snapshots must not execute, parse bodies or query authority"
        )

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
        (json, "loads"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    snapshot = AttemptOutput.from_prepared(
        prepared, 1, reported, STDOUT, hashlib.sha256(STDOUT).hexdigest()
    )
    assert snapshot.reconcile(replace(snapshot)) is snapshot
    snapshot.to_dict()
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


def test_output_reconciliation_compares_raw_bytes_even_with_equal_metadata(monkeypatch):
    class SameDigest:
        def hexdigest(self):
            return "a" * 64

    monkeypatch.setattr(hashlib, "sha256", lambda *args: SameDigest())
    left = output_snapshot(stdout=b"a")
    right = output_snapshot(stdout=b"b")
    assert left.to_dict() == right.to_dict()
    with pytest.raises(ValueError, match="output report conflict"):
        left.reconcile(right)


def test_output_different_source_snapshot_cannot_reuse_an_attempt():
    prepared = prepared_source()
    changed_source = b"FAKE_DIFFERENT_SOURCE"
    changed = replace(
        prepared,
        source=changed_source,
        expected_source_sha256=hashlib.sha256(changed_source).hexdigest(),
    )
    reported = (
        AttemptRecord.from_prepared(prepared, 1)
        .record(START)
        .record(AttemptEvent("exited", 3, 0))
    )
    with pytest.raises(ValueError, match="binding mismatch"):
        AttemptOutput.from_prepared(
            changed, 1, reported, STDOUT, hashlib.sha256(STDOUT).hexdigest()
        )


def test_output_binding_rejects_hostile_report_and_prepared_subclasses_without_access():
    from agent.verification_planner import PreparedSourceRequest

    class HostileRecord(AttemptRecord):
        def __getattribute__(self, name):
            pytest.fail("report subclass attributes must not be read")

    class HostilePrepared(PreparedSourceRequest):
        def __getattribute__(self, name):
            pytest.fail("prepared subclass attributes must not be read")

    prepared = prepared_source()
    hostile = object.__new__(HostileRecord)
    digest = hashlib.sha256(STDOUT).hexdigest()
    with pytest.raises(ValueError):
        AttemptOutput(hostile, STDOUT, digest)
    with pytest.raises(ValueError):
        AttemptOutput.from_prepared(prepared, 1, hostile, STDOUT, digest)
    with pytest.raises(ValueError):
        AttemptOutput.from_prepared(
            object.__new__(HostilePrepared), 1, record(), STDOUT, digest
        )


@pytest.mark.parametrize("timeout", [1, MAX_COUNTER])
def test_output_max_attempt_counter_and_minimum_deadline_remain_metadata(timeout):
    attempt = (
        AttemptRecord("a" * 64, MAX_COUNTER, timeout)
        .record(START)
        .record(AttemptEvent("exited", timeout - 1, 0))
    )
    snapshot = output_snapshot(attempt)
    assert snapshot.attempt is attempt
    assert snapshot.reconcile(replace(snapshot)) is snapshot


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b' {"items":[true,false,null,"text",{"nested":[]}]}\r\n',
        '{"日本語":"値","emoji":"😀"}'.encode(),
        b'{"escaped":"\\"\\\\{}[]","control":"\\u0000"}',
        b'{"scalar":"\\ud83d\\ude00"}',
        b'{"e\\u0301":1,"\\u00e9":2}',
    ],
    ids=[
        "empty-object",
        "nested-values",
        "utf8",
        "escaped-structure",
        "surrogate-pair",
        "no-unicode-normalization",
    ],
)
def test_output_json_decode_preserves_supported_objects(body):
    output = output_snapshot(stdout=body)
    before = output.to_dict()
    assert output.decode_json_object() == json.loads(body)
    assert output.to_dict() == before and output.stdout is body


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b" \t\n",
        b"null",
        b"true",
        b"42",
        b'"text"',
        b"[]",
        b"{}{}",
        b"{} log",
        b"log {}",
        b"```json\n{}\n```",
        b"{",
        b"}",
        b"{]",
        b'{"a":1,}',
        b'{"a":}',
        b"{a:1}",
        b'{"a":/*comment*/1}',
        b'{"a":"\x00"}',
        b'{"a":"\\x41"}',
        b'{"a":"\\u12"}',
        b'{"a":"unterminated}',
        b'{"a":01}',
        b'{"a":+1}',
        b'{"a":.1}',
        b'{"a":1.}',
        b'{"a":1e}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b"\xef\xbb\xbf{}",
        b'{"a":"\xff"}',
        b"\xff{}",
        b"\xff\xfe{\x00}\x00",
        b"\x00\x00\xfe\xff\x00\x00\x00{",
        b'{"a":"\\ud800"}',
        b'{"a":"\\udfff"}',
        b'{"\\ud800":1}',
        b'{"a":["\\ud800"]}',
        b'{"a":"\\ud800\\ud800"}',
    ],
    ids=[
        "empty",
        "whitespace",
        "null",
        "bool",
        "number",
        "string",
        "array",
        "two-objects",
        "trailing-log",
        "leading-log",
        "markdown",
        "missing-close",
        "extra-close",
        "wrong-close",
        "trailing-comma",
        "missing-value",
        "bare-key",
        "comment",
        "raw-nul",
        "bad-escape",
        "short-unicode",
        "unterminated-string",
        "leading-zero",
        "plus-number",
        "missing-integer",
        "missing-fraction",
        "missing-exponent",
        "nan",
        "infinity",
        "negative-infinity",
        "bom",
        "invalid-utf8-value",
        "invalid-utf8-prefix",
        "utf16",
        "utf32",
        "unpaired-high",
        "unpaired-low",
        "unpaired-key",
        "unpaired-array-value",
        "two-high-surrogates",
    ],
)
def test_output_json_decode_rejects_unsupported_transport_without_chained_payload(body):
    snapshot = output_snapshot(stdout=body)
    before = snapshot.to_dict()
    with pytest.raises(ValueError) as error:
        snapshot.decode_json_object()
    assert str(error.value) == "stdout is not a supported bounded JSON object"
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert snapshot.to_dict() == before and snapshot.stdout is body


@pytest.mark.parametrize(
    "body",
    [
        b'{"a":1,"a":2}',
        b'{"a":1,"\\u0061":2}',
        b'{"a":null,"a":null}',
        b'{"nested":{"a":1,"a":2}}',
        b'{"nested":[{"a":1,"a":2}]}',
        b'{"a":{},"a":[]}',
        b'{"a":1,"b":2,"a":3}',
    ],
    ids=[
        "root",
        "escaped-key",
        "equal-values",
        "nested-object",
        "array-object",
        "different-types",
        "separated",
    ],
)
def test_output_json_decode_rejects_duplicate_decoded_keys_at_every_level(body):
    with pytest.raises(ValueError):
        output_snapshot(stdout=body).decode_json_object()


@pytest.mark.parametrize("depth", [1, 2, MAX_JSON_DEPTH - 1, MAX_JSON_DEPTH])
@pytest.mark.parametrize("container", ["array", "object"])
def test_output_json_decode_nesting_bound_is_exact(depth, container):
    body = b"null"
    for _ in range(depth - 1):
        body = b"[" + body + b"]" if container == "array" else b'{"x":' + body + b"}"
    body = b'{"x":' + body + b"}"
    assert isinstance(output_snapshot(stdout=body).decode_json_object(), dict)


@pytest.mark.parametrize("container", ["array", "object"])
def test_output_json_decode_excess_nesting_is_rejected_before_parser(
    container, monkeypatch
):
    body = b"null"
    for _ in range(MAX_JSON_DEPTH):
        body = b"[" + body + b"]" if container == "array" else b'{"x":' + body + b"}"
    snapshot = output_snapshot(stdout=b'{"x":' + body + b"}")
    monkeypatch.setattr(
        json,
        "loads",
        lambda *args, **kwargs: pytest.fail(
            "depth must be bounded before JSON parsing"
        ),
    )
    with pytest.raises(ValueError):
        snapshot.decode_json_object()


@pytest.mark.parametrize(
    "token",
    [
        "9007199254740993",
        "-9007199254740993",
        "9" * MAX_JSON_NUMBER_CHARS,
        "-" + "9" * (MAX_JSON_NUMBER_CHARS - 1),
        "0.12345678901234567890123456789",
        "-0.0",
        "1e400",
        "1e-400",
        "1." + "0" * (MAX_JSON_NUMBER_CHARS - 3) + "1",
    ],
)
def test_output_json_decode_numbers_preserve_precision_without_float_or_context_changes(
    token,
):
    snapshot = output_snapshot(stdout=('{"n":' + token + "}").encode())
    with localcontext() as context:
        context.prec = 2
        context.clear_flags()
        before = context.flags.copy()
        number = snapshot.decode_json_object()["n"]
        assert context.flags == before
    expected = (
        Decimal(token) if any(marker in token for marker in ".eE") else int(token)
    )
    assert number == expected and type(number) is type(expected)
    if token == "-0.0":
        assert number.is_signed()


@pytest.mark.parametrize(
    "token",
    [
        "9" * (MAX_JSON_NUMBER_CHARS + 1),
        "-" + "9" * MAX_JSON_NUMBER_CHARS,
        "0." + "1" * (MAX_JSON_NUMBER_CHARS - 1),
        "1e" + "9" * 30,
        "1e-" + "9" * 30,
    ],
    ids=[
        "long-positive",
        "long-negative",
        "long-fraction",
        "unrepresentable-exponent",
        "unrepresentable-negative-exponent",
    ],
)
def test_output_json_decode_rejects_unsupported_number_bounds(token):
    with pytest.raises(ValueError) as error:
        output_snapshot(stdout=('{"n":' + token + "}").encode()).decode_json_object()
    assert error.value.__context__ is None


def test_output_json_decode_large_string_is_not_nesting_and_limit_counts_bytes():
    text = ('\\"\\\\{}[]' * 2000) + "FAKE_PRIVATE_JSON"
    body = json.dumps({"value": text}).encode()
    assert output_snapshot(stdout=body).decode_json_object() == {"value": text}
    body = b'{"x":"' + b"a" * (MAX_STDOUT_BYTES - len(b'{"x":""}')) + b'"}'
    assert len(body) == MAX_STDOUT_BYTES
    assert (
        len(output_snapshot(stdout=body).decode_json_object()["x"])
        == MAX_STDOUT_BYTES - 8
    )


def test_output_json_decode_returns_fresh_private_tree_not_cached_or_authoritative(
    capsys,
):
    body = b'{"result":"established","path":"FAKE_PRIVATE_PATH","nested":[{"secret":"FAKE_PRIVATE_JSON"}]}'
    snapshot = output_snapshot(stdout=body)
    before = snapshot.to_dict()
    first = snapshot.decode_json_object()
    first["nested"][0]["secret"] = "changed"
    first["result"] = "changed"
    assert snapshot.decode_json_object()["result"] == "established"
    assert snapshot.decode_json_object()["nested"][0]["secret"] == "FAKE_PRIVATE_JSON"
    assert snapshot.to_dict() == before and snapshot.stdout is body
    assert "FAKE_PRIVATE" not in repr(snapshot) + json.dumps(snapshot.to_dict())
    assert not capsys.readouterr().out


def test_output_json_decode_invalid_body_is_absent_from_errors_and_traceback(capsys):
    import traceback

    for body in (
        b'{"FAKE_PRIVATE_JSON":',
        b'{"FAKE_PRIVATE_JSON":1,"FAKE_PRIVATE_JSON":2}',
        b'{"x":"FAKE_PRIVATE_JSON\\ud800"}',
    ):
        try:
            output_snapshot(stdout=body).decode_json_object()
        except ValueError as error:
            assert "FAKE_PRIVATE_JSON" not in str(error) + "".join(
                traceback.format_exception(error)
            )
            assert error.__context__ is None and error.__cause__ is None
        else:
            pytest.fail("invalid private JSON must not decode")
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


def test_output_json_decode_needs_no_io_clocks_plugins_authority_or_paths(monkeypatch):
    body = b'{"schema_version":"untrusted","success":true,"artifact_paths":["FAKE_PRIVATE_PATH"]}'
    snapshot = output_snapshot(stdout=body)

    def forbidden(*args, **kwargs):
        pytest.fail("JSON decode must not read paths, run tools or query authority")

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
    result = snapshot.decode_json_object()
    assert result["success"] is True and result["schema_version"] == "untrusted"
    assert "result" not in snapshot.to_dict()
