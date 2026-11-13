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
    MAX_ATTEMPTS,
    MAX_COUNTER,
    MAX_EVENTS,
    MAX_JSON_DEPTH,
    MAX_JSON_NUMBER_CHARS,
    MAX_STDOUT_BYTES,
    STREAM_KINDS,
    AttemptCancelRequest,
    AttemptEvent,
    AttemptEvidenceCandidate,
    AttemptExecutionRequest,
    AttemptOutput,
    AttemptRecord,
    AttemptSequence,
    AttemptSequenceStore,
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


def output_snapshot(attempt=None, stdout=STDOUT, **kwargs):
    return AttemptOutput(
        record(*PREFIXES["exited"]) if attempt is None else attempt,
        stdout,
        hashlib.sha256(stdout).hexdigest(),
        **kwargs,
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
    assert set(vars(snapshot)) == {
        "attempt",
        "stdout",
        "expected_stdout_sha256",
        "stream",
        "complete",
    }
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


def test_output_json_decode_nonfinite_decimal_fallback_is_rejected(monkeypatch):
    from decimal import Context
    import agent.verification_attempt as attempt_module

    monkeypatch.setattr(attempt_module, "Context", lambda: Context(traps=[]))
    with pytest.raises(ValueError) as error:
        output_snapshot(stdout=b'{"n":1e999999999999999999999999}').decode_json_object()
    assert error.value.__context__ is None


@pytest.mark.parametrize("error_type", [ValueError, RecursionError, ArithmeticError])
def test_output_json_decode_hides_decoder_errors_without_chaining(
    error_type, monkeypatch
):
    def failing_decoder(*args, **kwargs):
        raise error_type("FAKE_PRIVATE_DECODER_PAYLOAD")

    monkeypatch.setattr(json, "loads", failing_decoder)
    with pytest.raises(ValueError) as error:
        output_snapshot(stdout=b"{}").decode_json_object()
    assert "FAKE_PRIVATE" not in str(error.value)
    assert error.value.__context__ is None and error.value.__cause__ is None


def test_output_json_decode_does_not_normalize_identity_or_merge_equivalent_trees():
    current = output_snapshot(stdout=b'{"x":1}')
    incoming = output_snapshot(stdout=b' {"x": 1}\n')
    assert current.decode_json_object() == incoming.decode_json_object()
    assert (
        current.to_dict()["output_fingerprint"]
        != incoming.to_dict()["output_fingerprint"]
    )
    with pytest.raises(ValueError, match="output report conflict"):
        current.reconcile(incoming)


@pytest.mark.parametrize("exit_code", [-1, 0, 1, MAX_COUNTER])
def test_output_json_decode_is_not_success_classification_for_any_exit_code(exit_code):
    attempt = record(START, AttemptEvent("exited", 3, exit_code))
    snapshot = output_snapshot(attempt, b'{"result":"established"}')
    assert snapshot.decode_json_object()["result"] == "established"
    assert "result" not in snapshot.to_dict()
    assert snapshot.attempt.events[-1].exit_code == exit_code


def sequence_record(state, ordinal=1):
    return AttemptRecord(FINGERPRINT, ordinal, 10, PREFIXES[state])


def test_sequence_from_prepared_starts_empty_without_retaining_private_source():
    prepared = prepared_source()
    sequence = AttemptSequence.from_prepared(prepared)
    assert sequence.current is None
    assert sequence.attempts == ()
    assert sequence.request_fingerprint == prepared.to_dict()["request_fingerprint"]
    assert sequence.timeout_ms == prepared.plan.selected.timeout_ms
    assert SOURCE.decode() not in repr(sequence) + json.dumps(sequence.to_dict())
    assert not hasattr(sequence, "source") and not hasattr(sequence, "plan")
    assert set(sequence.to_dict()) == {
        "schema_version",
        "request_fingerprint",
        "timeout_ms",
        "attempts",
    }
    assert sequence.to_dict()["schema_version"] == "mumei.verifier-attempt-sequence/v1"


@pytest.mark.parametrize("value", [None, {}, FINGERPRINT, record()])
def test_sequence_from_prepared_rejects_non_prepared_values(value):
    with pytest.raises(ValueError):
        AttemptSequence.from_prepared(value)


def test_sequence_from_prepared_requires_explicit_permission_metadata():
    with pytest.raises(ValueError):
        AttemptSequence.from_prepared(prepared_source(policy=PlannerPolicy()))


@pytest.mark.parametrize("policy_timeout", [1, 10, 30_000, MAX_COUNTER])
@pytest.mark.parametrize("adapter_timeout", [1, 5, 30_000, MAX_COUNTER])
def test_sequence_binds_selected_timeout_not_unclamped_policy(
    policy_timeout, adapter_timeout
):
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
            max_timeout_ms=adapter_timeout,
        )
    )
    prepared = prepared_source(
        policy=PlannerPolicy(
            allowed_permissions=frozenset(), timeout_ms=policy_timeout
        ),
        registry=registry,
    )
    sequence = AttemptSequence.from_prepared(prepared).begin_attempt()
    assert sequence.timeout_ms == min(policy_timeout, adapter_timeout)
    assert sequence.current == AttemptRecord.from_prepared(prepared, 1)


@pytest.mark.parametrize("state", PREFIXES)
def test_sequence_begin_requires_a_terminal_predecessor(state):
    prior = sequence_record(state)
    current = AttemptSequence(FINGERPRINT, 10, (prior,))
    before = current.to_dict()
    if prior.is_terminal:
        following = current.begin_attempt()
        assert following.current == AttemptRecord(FINGERPRINT, 2, 10)
        assert following.attempts[0] is prior
        assert following.current.state == "ready"
    else:
        with pytest.raises(ValueError):
            current.begin_attempt()
    assert current.to_dict() == before


@pytest.mark.parametrize("first", PREFIXES)
@pytest.mark.parametrize("second", PREFIXES)
def test_sequence_constructor_enforces_logical_nonoverlap(first, second):
    records = (sequence_record(first), sequence_record(second, 2))
    if records[0].is_terminal:
        assert AttemptSequence(FINGERPRINT, 10, records).current is records[1]
    else:
        with pytest.raises(ValueError):
            AttemptSequence(FINGERPRINT, 10, records)


@pytest.mark.parametrize("count", range(MAX_ATTEMPTS + 1))
def test_sequence_capacity_and_contiguous_reservations(count):
    sequence = AttemptSequence(FINGERPRINT, 10)
    records = []
    for ordinal in range(1, count + 1):
        reserved = sequence.begin_attempt()
        assert reserved.current == AttemptRecord(FINGERPRINT, ordinal, 10)
        report = reserved.current.record(START).record(AttemptEvent("failed", 3))
        sequence = reserved.reconcile_report(report)
        records.append(report)
        assert reserved.current.state == "ready"
    assert sequence.attempts == tuple(records)
    assert sequence.current == (records[-1] if records else None)
    if count == MAX_ATTEMPTS:
        with pytest.raises(ValueError):
            sequence.begin_attempt()
    else:
        assert sequence.begin_attempt().current.attempt_number == count + 1


def test_sequence_constructor_rejects_overflow_without_truncation():
    attempts = tuple(sequence_record("failed", n) for n in range(1, MAX_ATTEMPTS + 2))
    with pytest.raises(ValueError):
        AttemptSequence(FINGERPRINT, 10, attempts)
    assert len(attempts) == MAX_ATTEMPTS + 1


@pytest.mark.parametrize("numbers", [(2,), (MAX_COUNTER,), (1, 1), (1, 3), (2, 1)])
def test_sequence_constructor_rejects_nonconsecutive_or_repeated_ordinals(numbers):
    with pytest.raises(ValueError):
        AttemptSequence(
            FINGERPRINT, 10, tuple(sequence_record("failed", n) for n in numbers)
        )


@pytest.mark.parametrize("ordinal", [1, 2, MAX_ATTEMPTS])
@pytest.mark.parametrize("field", ["request_fingerprint", "timeout_ms"])
def test_sequence_constructor_checks_every_record_binding(ordinal, field):
    records = [sequence_record("failed", n) for n in range(1, MAX_ATTEMPTS + 1)]
    changes = {field: "b" * 64 if field == "request_fingerprint" else 11}
    records[ordinal - 1] = replace(records[ordinal - 1], **changes)
    with pytest.raises(ValueError):
        AttemptSequence(FINGERPRINT, 10, tuple(records))


@pytest.mark.parametrize("known_state", PREFIXES)
@pytest.mark.parametrize("incoming_state", PREFIXES)
def test_sequence_report_reconciliation_preserves_known_prefix(
    known_state, incoming_state
):
    known = sequence_record(known_state)
    incoming = sequence_record(incoming_state)
    sequence = AttemptSequence(FINGERPRINT, 10, (known,))
    before = sequence.to_dict()
    if incoming.events[: len(known.events)] == known.events:
        result = sequence.reconcile_report(incoming)
        if incoming == known:
            assert result is sequence
        else:
            assert result.current is incoming
            assert result is not sequence
    else:
        with pytest.raises(ValueError):
            sequence.reconcile_report(incoming)
    assert sequence.to_dict() == before


@pytest.mark.parametrize("known_state", ["exited", "failed", "timed_out", "cancelled"])
@pytest.mark.parametrize("incoming_state", PREFIXES)
def test_sequence_late_reports_cannot_rewrite_an_old_terminal(
    known_state, incoming_state
):
    known = sequence_record(known_state)
    sequence = AttemptSequence(FINGERPRINT, 10, (known,)).begin_attempt()
    incoming = sequence_record(incoming_state)
    before = sequence.to_dict()
    if incoming == known:
        assert sequence.reconcile_report(incoming) is sequence
    else:
        with pytest.raises(ValueError):
            sequence.reconcile_report(incoming)
    assert sequence.to_dict() == before


@pytest.mark.parametrize("ordinal", [1, 2, MAX_ATTEMPTS, MAX_COUNTER])
def test_sequence_reports_never_reserve_unseen_ordinals(ordinal):
    report = sequence_record("failed", ordinal)
    empty = AttemptSequence(FINGERPRINT, 10)
    with pytest.raises(ValueError):
        empty.reconcile_report(report)
    if ordinal != 1:
        with pytest.raises(ValueError):
            empty.begin_attempt().reconcile_report(report)


@pytest.mark.parametrize("state", PREFIXES)
@pytest.mark.parametrize("field", ["request_fingerprint", "timeout_ms"])
def test_sequence_reports_cannot_rebind_a_reserved_attempt(state, field):
    sequence = AttemptSequence(FINGERPRINT, 10).begin_attempt()
    incoming = sequence_record(state)
    incoming = replace(
        incoming, **{field: "b" * 64 if field == "request_fingerprint" else 9}
    )
    with pytest.raises(ValueError):
        sequence.reconcile_report(incoming)
    assert sequence.current.state == "ready"


@pytest.mark.parametrize("value", [None, [], {}, record(), "FAKE_PRIVATE_SEQUENCE"])
def test_sequence_requires_an_exact_immutable_tuple(value):
    with pytest.raises(ValueError) as error:
        AttemptSequence(FINGERPRINT, 10, value)
    assert "FAKE_PRIVATE_SEQUENCE" not in str(error.value)


@pytest.mark.parametrize("value", [None, [], {}, START, "FAKE_PRIVATE_SEQUENCE"])
def test_sequence_requires_exact_records_in_constructor_and_reports(value):
    sequence = AttemptSequence(FINGERPRINT, 10).begin_attempt()
    for operation in (
        lambda: AttemptSequence(FINGERPRINT, 10, (value,)),
        lambda: sequence.reconcile_report(value),
    ):
        with pytest.raises(ValueError) as error:
            operation()
        assert "FAKE_PRIVATE_SEQUENCE" not in str(error.value)


def test_sequence_rejects_subclasses_without_consulting_their_behavior():
    class HostileTuple(tuple):
        def __iter__(self):
            pytest.fail("untrusted tuple behavior was called")

        def __len__(self):
            pytest.fail("untrusted tuple behavior was called")

    class HostileRecord(AttemptRecord):
        def __getattribute__(self, name):
            pytest.fail("untrusted record behavior was called")

    with pytest.raises(ValueError):
        AttemptSequence(FINGERPRINT, 10, HostileTuple())
    hostile = object.__new__(HostileRecord)
    with pytest.raises(ValueError):
        AttemptSequence(FINGERPRINT, 10, (hostile,))
    with pytest.raises(ValueError):
        AttemptSequence(FINGERPRINT, 10).begin_attempt().reconcile_report(hostile)


def test_sequence_rejects_primitive_subclasses_before_custom_behavior():
    class HostileString(str):
        def __str__(self):
            pytest.fail("custom fingerprint behavior was called")

    class HostileInt(int):
        def __le__(self, other):
            pytest.fail("custom timeout behavior was called")

    with pytest.raises(ValueError):
        AttemptSequence(HostileString(FINGERPRINT), 10)
    with pytest.raises(ValueError):
        AttemptSequence(FINGERPRINT, HostileInt(10))


@pytest.mark.parametrize(
    "value", [None, 0, False, "a" * 63, "A" * 64, "FAKE_PRIVATE_SEQUENCE"]
)
def test_sequence_rejects_invalid_fingerprints_without_echo(value):
    with pytest.raises(ValueError) as error:
        AttemptSequence(value, 10)
    assert str(error.value) == "invalid prepared request fingerprint"


@pytest.mark.parametrize(
    "value", [None, False, True, 0, -1, MAX_COUNTER + 1, "FAKE_PRIVATE_SEQUENCE"]
)
def test_sequence_rejects_invalid_timeout_without_echo(value):
    with pytest.raises(ValueError) as error:
        AttemptSequence(FINGERPRINT, value)
    assert str(error.value) == "invalid bounded attempt counter"


@pytest.mark.parametrize("timeout", [1, 10, MAX_COUNTER])
def test_sequence_keeps_the_same_reported_budget_for_every_attempt(timeout):
    sequence = AttemptSequence(FINGERPRINT, timeout)
    for _ in range(MAX_ATTEMPTS):
        reserved = sequence.begin_attempt()
        terminal = reserved.current.record(START).record(
            AttemptEvent("failed", MAX_COUNTER)
        )
        sequence = reserved.reconcile_report(terminal)
    assert all(attempt.timeout_ms == timeout for attempt in sequence.attempts)
    assert all(
        attempt.events[-1].elapsed_ms == MAX_COUNTER for attempt in sequence.attempts
    )


def test_sequence_is_immutable_and_serialization_is_detached():
    sequence = AttemptSequence(
        FINGERPRINT, 10, (sequence_record("exited"),)
    ).begin_attempt()
    before = sequence.to_dict()
    data = sequence.to_dict()
    data["attempts"][0]["events"][1]["exit_code"] = 42
    data["attempts"].clear()
    data["request_fingerprint"] = "b" * 64
    assert sequence.to_dict() == before
    assert json.loads(json.dumps(before)) == before
    with pytest.raises(FrozenInstanceError):
        sequence.attempts = ()


@pytest.mark.parametrize("code", [-1, 0, 1])
def test_sequence_does_not_select_success_or_invalidate_old_output(code):
    prepared = prepared_source()
    initial = AttemptSequence.from_prepared(prepared).begin_attempt()
    exited = initial.current.record(START).record(AttemptEvent("exited", 3, code))
    sequence = initial.reconcile_report(exited)
    stdout = b'{"result":"established"}'
    output = AttemptOutput.from_prepared(
        prepared, 1, exited, stdout, hashlib.sha256(stdout).hexdigest()
    )
    before = output.to_dict()
    following = sequence.begin_attempt()
    assert following.current.state == "ready"
    assert sequence.current.state == "exited"
    assert sequence.reconcile_report(exited) is sequence
    assert output.to_dict() == before and output.stdout == stdout
    assert all(
        key not in following.to_dict()
        for key in ("result", "accepted", "winner", "grade", "stdout")
    )


def test_sequence_does_not_claim_global_uniqueness_or_atomic_branch_arbitration():
    initial = AttemptSequence(FINGERPRINT, 10).begin_attempt()
    left = initial.reconcile_report(sequence_record("exited"))
    right = initial.reconcile_report(sequence_record("failed"))
    assert left != right
    assert left.begin_attempt().current == right.begin_attempt().current
    with pytest.raises(ValueError):
        left.reconcile_report(right.current)
    assert initial.current.state == "ready"


def test_sequence_is_passive_without_io_clocks_plugins_or_evidence(monkeypatch, capsys):
    prepared = prepared_source()

    def forbidden(*args, **kwargs):
        pytest.fail("attempt sequence must remain passive metadata")

    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"),
            (Path, "open"),
            (Path, "read_bytes"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (importlib, "import_module"),
            (time, "monotonic"),
            (time, "time"),
        ):
            patch.setattr(owner, name, forbidden)
        sequence = AttemptSequence.from_prepared(prepared)
        reserved = sequence.begin_attempt()
        terminal = reserved.current.record(START).record(AttemptEvent("timed_out", 10))
        current = reserved.reconcile_report(terminal).begin_attempt()
        assert current.reconcile_report(terminal) is current
        assert current.current.state == "ready"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("current_ordinal", range(1, MAX_ATTEMPTS + 1))
@pytest.mark.parametrize("output_ordinal", range(1, MAX_ATTEMPTS + 2))
@pytest.mark.parametrize("state", PREFIXES)
def test_sequence_output_binding_checks_current_state_and_ordinal(
    current_ordinal, output_ordinal, state
):
    previous = tuple(sequence_record("exited", n) for n in range(1, current_ordinal))
    sequence = AttemptSequence(
        FINGERPRINT, 10, (*previous, sequence_record(state, current_ordinal))
    )
    output = output_snapshot(sequence_record("exited", output_ordinal), b"\xff")
    before = sequence.to_dict(), output.to_dict()
    if state == "exited" and current_ordinal == output_ordinal:
        assert sequence.check_output_binding(output) is None
    else:
        with pytest.raises(
            ValueError, match="^output does not match the current sequence record$"
        ):
            sequence.check_output_binding(output)
    assert (sequence.to_dict(), output.to_dict()) == before


@pytest.mark.parametrize("ordinal", [1, 8, MAX_ATTEMPTS])
@pytest.mark.parametrize("change", ["request", "timeout", "elapsed", "code", "history"])
def test_sequence_output_binding_requires_the_exact_known_history(ordinal, change):
    known = sequence_record("exited", ordinal)
    previous = tuple(sequence_record("failed", n) for n in range(1, ordinal))
    sequence = AttemptSequence(FINGERPRINT, 10, (*previous, known))
    alternate = {
        "request": lambda: replace(known, request_fingerprint="b" * 64),
        "timeout": lambda: replace(known, timeout_ms=11),
        "elapsed": lambda: replace(known, events=(START, AttemptEvent("exited", 4, 0))),
        "code": lambda: replace(known, events=(START, AttemptEvent("exited", 3, 1))),
        "history": lambda: replace(
            known, events=(START, CANCEL, AttemptEvent("exited", 3, 0))
        ),
    }[change]()
    with pytest.raises(ValueError):
        sequence.check_output_binding(output_snapshot(alternate))
    assert sequence.current is known


def test_sequence_output_binding_requires_explicit_reconciliation_first():
    prepared = prepared_source()
    reserved = AttemptSequence.from_prepared(prepared).begin_attempt()
    report = reserved.current.record(START).record(AttemptEvent("exited", 3, 0))
    output = AttemptOutput.from_prepared(
        prepared, 1, report, b"{}", hashlib.sha256(b"{}").hexdigest()
    )
    for sequence in (AttemptSequence.from_prepared(prepared), reserved):
        with pytest.raises(ValueError):
            sequence.check_output_binding(output)
    reconciled = reserved.reconcile_report(report)
    assert reconciled.check_output_binding(output) is None
    copied = replace(output, attempt=replace(report))
    assert reconciled.check_output_binding(copied) is None
    with pytest.raises(ValueError):
        reconciled.begin_attempt().check_output_binding(output)
    assert reconciled.check_output_binding(output) is None
    assert reserved.current.state == "ready"


@pytest.mark.parametrize(
    "value", [None, True, 0, {}, [], record(), "FAKE_PRIVATE_BINDING"]
)
def test_sequence_output_binding_rejects_non_snapshots_without_echo(value):
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    with pytest.raises(ValueError) as error:
        sequence.check_output_binding(value)
    assert str(error.value) == "output does not match the current sequence record"


def test_sequence_output_binding_rejects_subclasses_before_custom_behavior():
    class HostileOutput(AttemptOutput):
        def __getattribute__(self, name):
            pytest.fail("custom output behavior was called")

    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    with pytest.raises(ValueError):
        sequence.check_output_binding(object.__new__(HostileOutput))


def test_sequence_output_binding_does_not_resolve_stdout_conflicts():
    attempt = sequence_record("exited")
    sequence = AttemptSequence(FINGERPRINT, 10, (attempt,))
    left, right = output_snapshot(attempt, b"{}"), output_snapshot(attempt, b"[]")
    assert sequence.check_output_binding(left) is None
    assert sequence.check_output_binding(right) is None
    with pytest.raises(ValueError, match="output report conflict"):
        left.reconcile(right)


def test_sequence_output_binding_has_no_io_decode_or_clock_effects(monkeypatch, capsys):
    attempt = sequence_record("exited")
    sequence = AttemptSequence(FINGERPRINT, 10, (attempt,))
    output = output_snapshot(attempt, b"FAKE_PRIVATE_BINDING_BODY")
    before = sequence.to_dict(), output.to_dict()

    def forbidden(*args, **kwargs):
        pytest.fail("output binding must remain passive exact metadata comparison")

    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"),
            (Path, "open"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (time, "monotonic"),
            (time, "time"),
            (AttemptOutput, "decode_json_object"),
            (json, "loads"),
        ):
            patch.setattr(owner, name, forbidden)
        assert sequence.check_output_binding(output) is None
        with pytest.raises(ValueError):
            sequence.begin_attempt().check_output_binding(output)
    assert (sequence.to_dict(), output.to_dict()) == before
    assert capsys.readouterr() == ("", "")


def exited_sequence_and_output(prepared, body=b"{}", code=0):
    """Reconcile one exited attempt and bind a snapshot to it."""
    reserved = AttemptSequence.from_prepared(prepared).begin_attempt()
    report = reserved.current.record(START).record(AttemptEvent("exited", 3, code))
    sequence = reserved.reconcile_report(report)
    output = AttemptOutput.from_prepared(
        prepared, 1, report, body, hashlib.sha256(body).hexdigest()
    )
    return sequence, output


@pytest.mark.parametrize("code", [-1, 0, 1])
def test_sequence_result_selection_binds_current_exited_output(code):
    sequence, output = exited_sequence_and_output(prepared_source(), code=code)
    before = sequence.to_dict(), output.to_dict()
    selected = sequence.select_result(output)
    assert selected is not sequence
    assert selected.selected_result == (
        1,
        output.to_dict()["output_fingerprint"],
    )
    assert sequence.selected_result is None
    data = selected.to_dict()
    assert data["selected_result"] == {
        "attempt_number": 1,
        "output_fingerprint": output.to_dict()["output_fingerprint"],
    }
    assert "stdout" not in data and "result" not in data
    assert (sequence.to_dict(), output.to_dict()) == before


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
@pytest.mark.parametrize("ordinal", range(1, MAX_ATTEMPTS + 1))
def test_sequence_result_selection_only_binds_the_current_attempt(count, ordinal):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    bound = (
        attempts[ordinal - 1]
        if ordinal <= count
        else sequence_record("exited", ordinal)
    )
    output = output_snapshot(bound, b"body-%d" % ordinal)
    if ordinal == count:
        selected = sequence.select_result(output)
        assert selected.selected_result == (
            count,
            output.to_dict()["output_fingerprint"],
        )
        assert sequence.selected_result is None
    else:
        with pytest.raises(ValueError):
            sequence.select_result(output)
        assert sequence.selected_result is None


@pytest.mark.parametrize("state", PREFIXES)
@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
@pytest.mark.parametrize("ordinal", range(0, MAX_ATTEMPTS + 2))
def test_sequence_selected_result_constructor_matrix(state, count, ordinal):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count)) + (
        (sequence_record(state, count),) if count else ()
    )
    marker = (ordinal, "b" * 64)
    if state == "exited" and ordinal == count and count:
        sequence = AttemptSequence(FINGERPRINT, 10, attempts, marker)
        assert sequence.selected_result == marker
    else:
        with pytest.raises(ValueError):
            AttemptSequence(FINGERPRINT, 10, attempts, marker)


@pytest.mark.parametrize(
    "marker",
    [
        "result",
        1,
        [1, "b" * 64],
        {"attempt_number": 1, "output_fingerprint": "b" * 64},
        (1,),
        (1, "b" * 64, 1),
        ("1", "b" * 64),
        (1, 0),
        (1, "B" * 64),
        (1, "b" * 63),
        (1, "b" * 65),
        (1, "g" * 64),
    ],
)
def test_sequence_selected_result_rejects_invalid_metadata(marker):
    attempts = (sequence_record("exited"),)
    with pytest.raises(ValueError, match="^invalid selected result metadata$"):
        AttemptSequence(FINGERPRINT, 10, attempts, marker)


@pytest.mark.parametrize("left", [b"{}", b"[]", b""])
@pytest.mark.parametrize("right", [b"{}", b"[]", b""])
def test_sequence_result_selection_is_idempotent_only_for_the_same_output(
    left, right
):
    sequence, first = exited_sequence_and_output(prepared_source(), body=left)
    selected = sequence.select_result(first)
    second = output_snapshot(first.attempt, right)
    if left == right:
        assert selected.select_result(second) is selected
    else:
        with pytest.raises(
            ValueError, match="^attempt sequence already has a selected result$"
        ):
            selected.select_result(second)
    assert selected.selected_result == (
        1,
        first.to_dict()["output_fingerprint"],
    )


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
def test_sequence_result_selection_closes_reservation(count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    selected = sequence.select_result(
        output_snapshot(attempts[-1], b"chosen")
    )
    before = selected.to_dict()
    with pytest.raises(
        ValueError, match="^a selected result closes the attempt sequence$"
    ):
        selected.begin_attempt()
    assert selected.to_dict() == before
    assert len(selected.attempts) == count


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
def test_sequence_result_selection_requires_a_current_exited_record(count):
    attempts = tuple(
        sequence_record("exited" if n < count else "failed", n)
        for n in range(1, count + 1)
    )
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    output = output_snapshot(sequence_record("exited", count or 1), b"x")
    with pytest.raises(ValueError):
        sequence.select_result(output)
    assert sequence.selected_result is None


def test_sequence_result_selection_requires_explicit_reconciliation():
    prepared = prepared_source()
    reserved = AttemptSequence.from_prepared(prepared).begin_attempt()
    report = reserved.current.record(START).record(AttemptEvent("exited", 3, 0))
    output = AttemptOutput.from_prepared(
        prepared, 1, report, b"{}", hashlib.sha256(b"{}").hexdigest()
    )
    for sequence in (AttemptSequence.from_prepared(prepared), reserved):
        with pytest.raises(ValueError):
            sequence.select_result(output)
    reconciled = reserved.reconcile_report(report)
    assert reconciled.select_result(output).selected_result is not None
    assert reserved.current.state == "ready"


@pytest.mark.parametrize(
    "value", [None, True, 0, {}, [], record(), "FAKE_PRIVATE_RESULT"]
)
def test_sequence_result_selection_rejects_non_snapshots_without_echo(value):
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    with pytest.raises(
        ValueError, match="^output does not match the current sequence record$"
    ):
        sequence.select_result(value)
    assert sequence.selected_result is None


def test_sequence_result_selection_rejects_subclasses_before_custom_behavior():
    class HostileOutput(AttemptOutput):
        def __getattribute__(self, name):
            pytest.fail("custom output behavior was called")

    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    with pytest.raises(ValueError):
        sequence.select_result(object.__new__(HostileOutput))


def test_sequence_result_selection_does_not_arbitrate_independent_sequences():
    first = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    second = AttemptSequence(FINGERPRINT, 10, (sequence_record("failed"),))
    output = output_snapshot(first.current, b"one")
    selected = first.select_result(output)
    assert selected.selected_result is not None
    assert second.selected_result is None
    foreign = AttemptRecord("b" * 64, 1, 10, PREFIXES["exited"])
    other = AttemptSequence("b" * 64, 10, (foreign,))
    assert other.selected_result is None


def test_sequence_result_selection_keeps_terminal_reports_idempotent():
    sequence, output = exited_sequence_and_output(prepared_source())
    selected = sequence.select_result(output)
    assert selected.reconcile_report(output.attempt) is selected
    with pytest.raises(ValueError):
        selected.reconcile_report(sequence_record("exited", 2))
    assert selected.selected_result is not None


def test_sequence_result_selection_is_not_truth_or_acceptance():
    prepared = prepared_source()
    for body in (b"{}", b"[]", b"", b"not json", b'{"success":true}'):
        sequence, output = exited_sequence_and_output(prepared, body=body)
        selected = sequence.select_result(output)
        data = selected.to_dict()
        assert data["selected_result"]["attempt_number"] == 1
        assert json.dumps(data)
        for forbidden in ("accept", "grade", "verified", "winner", "truth"):
            assert forbidden not in data


def test_sequence_result_selection_serialization_is_detached_and_body_free():
    sequence, output = exited_sequence_and_output(
        prepared_source(), body=b"FAKE_PRIVATE_RESULT_BODY"
    )
    selected = sequence.select_result(output)
    before = selected.to_dict()
    data = selected.to_dict()
    data["selected_result"]["output_fingerprint"] = "0" * 64
    data["selected_result"].clear()
    assert selected.to_dict() == before
    assert json.loads(json.dumps(before)) == before
    encoded = json.dumps(before)
    assert "FAKE_PRIVATE_RESULT_BODY" not in encoded
    with pytest.raises(FrozenInstanceError):
        selected.selected_result = None


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
@pytest.mark.parametrize("ordinal", range(1, MAX_ATTEMPTS + 1))
def test_sequence_result_selection_matrix_over_attempt_positions(count, ordinal):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    outputs = {
        n: output_snapshot(attempts[n - 1], b"body-%d" % n)
        for n in range(1, count + 1)
    }
    selected = sequence.select_result(outputs[count])
    if ordinal <= count:
        competing = outputs[ordinal]
    else:
        competing = output_snapshot(attempts[count - 1], b"alt-%d" % ordinal)
    if ordinal == count:
        assert selected.select_result(competing) is selected
    else:
        with pytest.raises(ValueError):
            selected.select_result(competing)
    assert selected.selected_result == (
        count,
        outputs[count].to_dict()["output_fingerprint"],
    )


def test_sequence_result_selection_is_passive_without_io_clock_or_decode(
    monkeypatch, capsys
):
    sequence, output = exited_sequence_and_output(
        prepared_source(), body=b"FAKE_PRIVATE_SELECTED_BODY"
    )
    before = sequence.to_dict(), output.to_dict()

    def forbidden(*args, **kwargs):
        pytest.fail("result selection must remain passive exact metadata")

    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"),
            (Path, "open"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (time, "monotonic"),
            (time, "time"),
            (AttemptOutput, "decode_json_object"),
            (AttemptOutput, "reconcile"),
        ):
            patch.setattr(owner, name, forbidden)
        selected = sequence.select_result(output)
        assert selected.select_result(output) is selected
        with pytest.raises(ValueError):
            selected.begin_attempt()
    assert (sequence.to_dict(), output.to_dict()) == before
    assert capsys.readouterr() == ("", "")


def test_store_publish_starts_empty_and_exposes_only_the_canonical_value():
    store = AttemptSequenceStore()
    assert store.current is None
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    assert store.publish(sequence) is sequence
    assert store.current is sequence


@pytest.mark.parametrize(
    "value", [None, True, 0, {}, [], record(), "FAKE_PRIVATE_RESULT"]
)
def test_store_publish_rejects_non_sequences_without_echo(value):
    store = AttemptSequenceStore()
    with pytest.raises(
        ValueError, match="^canonical publication requires an attempt sequence$"
    ):
        store.publish(value)
    assert store.current is None


@pytest.mark.parametrize("state", PREFIXES)
@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
def test_store_publish_matrix_accepts_any_valid_value(state, count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count)) + (
        (sequence_record(state, count),) if count else ()
    )
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    store = AttemptSequenceStore()
    assert store.publish(sequence) is sequence
    assert store.current is sequence
    assert store.publish(sequence) is sequence


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
def test_store_publish_is_idempotent_only_for_equal_values(count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    first = AttemptSequence(FINGERPRINT, 10, attempts)
    equal = AttemptSequence(FINGERPRINT, 10, attempts)
    store = AttemptSequenceStore()
    store.publish(first)
    assert store.publish(equal) is first
    if count:
        other = AttemptSequence(
            FINGERPRINT, 10, (*attempts[:-1], sequence_record("failed", count))
        )
    else:
        other = AttemptSequence("b" * 64, 10, ())
    with pytest.raises(
        ValueError, match="^canonical sequence publication conflict$"
    ):
        store.publish(other)
    assert store.current is first


def test_store_compare_and_set_requires_a_published_value():
    store = AttemptSequenceStore()
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    with pytest.raises(
        ValueError, match="^canonical sequence compare failed$"
    ):
        store.compare_and_set(sequence, sequence)
    assert store.current is None


@pytest.mark.parametrize(
    "value", [None, True, 0, {}, [], record(), "FAKE_PRIVATE_RESULT"]
)
def test_store_compare_and_set_rejects_non_sequences_without_echo(value):
    store = AttemptSequenceStore()
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    store.publish(sequence)
    for expected, updated in ((value, sequence), (sequence, value)):
        with pytest.raises(
            ValueError,
            match="^canonical compare-and-set requires attempt sequences$",
        ):
            store.compare_and_set(expected, updated)
    assert store.current is sequence


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
def test_store_compare_and_set_detects_expected_mismatch(count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    stored = AttemptSequence(FINGERPRINT, 10, attempts)
    stale = AttemptSequence(
        FINGERPRINT, 10, attempts[:-1] if count else (sequence_record("exited"),)
    )
    store = AttemptSequenceStore()
    store.publish(stored)
    with pytest.raises(ValueError, match="^canonical sequence compare failed$"):
        store.compare_and_set(stale, stale)
    assert store.current is stored


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
def test_store_compare_and_set_is_idempotent_for_equal_updates(count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    stored = AttemptSequence(FINGERPRINT, 10, attempts)
    store = AttemptSequenceStore()
    store.publish(stored)
    assert store.compare_and_set(stored, stored) is stored
    assert store.current is stored


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
def test_store_compare_and_set_accepts_report_extensions(count):
    attempts = tuple(
        sequence_record("exited" if n < count else "running", n)
        for n in range(1, count + 1)
    )
    stored = AttemptSequence(FINGERPRINT, 10, attempts)
    report = attempts[-1].record(
        AttemptEvent("exited", PREFIXES["running"][-1].elapsed_ms + 1, 0)
    )
    updated = stored.reconcile_report(report)
    store = AttemptSequenceStore()
    store.publish(stored)
    assert store.compare_and_set(stored, updated) is updated
    assert store.current is updated
    assert updated.current.state == "exited"


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS))
def test_store_compare_and_set_accepts_new_reservations(count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    stored = AttemptSequence(FINGERPRINT, 10, attempts)
    updated = stored.begin_attempt()
    store = AttemptSequenceStore()
    store.publish(stored)
    assert store.compare_and_set(stored, updated) is updated
    assert store.current is updated


def test_store_compare_and_set_accepts_result_selection():
    sequence, output = exited_sequence_and_output(prepared_source())
    updated = sequence.select_result(output)
    store = AttemptSequenceStore()
    store.publish(sequence)
    assert store.compare_and_set(sequence, updated) is updated
    assert store.current.selected_result == updated.selected_result


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
def test_store_compare_and_set_rejects_changed_bindings(count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    stored = AttemptSequence(FINGERPRINT, 10, attempts)
    store = AttemptSequenceStore()
    store.publish(stored)
    foreign = AttemptSequence(
        "b" * 64,
        10,
        tuple(
            AttemptRecord("b" * 64, n, 10, PREFIXES["exited"])
            for n in range(1, count + 1)
        ),
    )
    retimed = AttemptSequence(
        FINGERPRINT,
        20,
        tuple(
            AttemptRecord(FINGERPRINT, n, 20, PREFIXES["exited"])
            for n in range(1, count + 1)
        ),
    )
    for updated in (foreign, retimed):
        with pytest.raises(
            ValueError,
            match="^updated sequence does not extend the canonical lineage$",
        ):
            store.compare_and_set(stored, updated)
    assert store.current is stored


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
def test_store_compare_and_set_rejects_removed_records(count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    stored = AttemptSequence(FINGERPRINT, 10, attempts)
    shortened = AttemptSequence(FINGERPRINT, 10, attempts[:-1])
    store = AttemptSequenceStore()
    store.publish(stored)
    with pytest.raises(
        ValueError, match="^updated sequence does not extend the canonical lineage$"
    ):
        store.compare_and_set(stored, shortened)
    assert store.current is stored


@pytest.mark.parametrize("ordinal", range(1, 5))
def test_store_compare_and_set_rejects_replaced_records(ordinal):
    attempts = tuple(sequence_record("exited", n) for n in range(1, 5))
    stored = AttemptSequence(FINGERPRINT, 10, attempts)
    replaced = (
        *attempts[: ordinal - 1],
        sequence_record("failed", ordinal),
        *attempts[ordinal:],
    )
    updated = AttemptSequence(FINGERPRINT, 10, replaced)
    store = AttemptSequenceStore()
    store.publish(stored)
    with pytest.raises(
        ValueError, match="^updated sequence does not extend the canonical lineage$"
    ):
        store.compare_and_set(stored, updated)
    assert store.current is stored


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
def test_store_compare_and_set_rejects_diverged_branches(count):
    attempts = tuple(
        sequence_record("exited" if n < count else "running", n)
        for n in range(1, count + 1)
    )
    stored = AttemptSequence(FINGERPRINT, 10, attempts)
    elapsed = PREFIXES["running"][-1].elapsed_ms + 1
    exited = stored.reconcile_report(
        attempts[-1].record(AttemptEvent("exited", elapsed, 0))
    )
    failed = stored.reconcile_report(
        attempts[-1].record(AttemptEvent("failed", elapsed))
    )
    store = AttemptSequenceStore()
    store.publish(stored)
    store.compare_and_set(stored, exited)
    with pytest.raises(ValueError, match="^canonical sequence compare failed$"):
        store.compare_and_set(stored, failed)
    with pytest.raises(
        ValueError, match="^updated sequence does not extend the canonical lineage$"
    ):
        store.compare_and_set(exited, failed)
    assert store.current is exited


def test_store_compare_and_set_keeps_selected_lineages_closed():
    sequence, output = exited_sequence_and_output(prepared_source())
    stored = sequence.select_result(output)
    store = AttemptSequenceStore()
    store.publish(stored)
    assert store.compare_and_set(stored, stored) is stored
    changed = AttemptSequence(
        stored.request_fingerprint,
        stored.timeout_ms,
        stored.attempts,
        (1, "b" * 64),
    )
    with pytest.raises(
        ValueError, match="^updated sequence does not extend the canonical lineage$"
    ):
        store.compare_and_set(stored, changed)
    assert store.current is stored


def test_store_linearizes_competing_extensions_from_one_prefix():
    stored = AttemptSequence(FINGERPRINT, 10, ())
    left = stored.begin_attempt()
    right = stored.begin_attempt()
    assert left == right
    diverged = replace(
        right, attempts=(sequence_record("exited", 1),)
    )
    store = AttemptSequenceStore()
    store.publish(stored)
    store.compare_and_set(stored, left)
    with pytest.raises(ValueError, match="^canonical sequence compare failed$"):
        store.compare_and_set(stored, diverged)
    assert store.current is left


def test_stores_do_not_arbitrate_each_other():
    first = AttemptSequenceStore()
    second = AttemptSequenceStore()
    a = AttemptSequence(FINGERPRINT, 10, (sequence_record("exited"),))
    b = AttemptSequence("b" * 64, 10, ())
    first.publish(a)
    second.publish(b)
    assert first.current is a
    assert second.current is b


def test_store_holds_values_without_source_or_stdout_bodies():
    sequence, output = exited_sequence_and_output(
        prepared_source(), body=b"FAKE_PRIVATE_STORED_BODY"
    )
    stored = sequence.select_result(output)
    store = AttemptSequenceStore()
    store.publish(stored)
    encoded = json.dumps(store.current.to_dict())
    assert "FAKE_PRIVATE_STORED_BODY" not in encoded
    assert SOURCE.decode() not in encoded
    assert store.current is stored


def test_store_operations_do_not_mutate_either_value():
    sequence, output = exited_sequence_and_output(prepared_source())
    updated = sequence.select_result(output)
    before = sequence.to_dict(), updated.to_dict()
    store = AttemptSequenceStore()
    store.publish(sequence)
    store.compare_and_set(sequence, updated)
    assert (sequence.to_dict(), updated.to_dict()) == before


def test_store_is_passive_without_io_clock_or_decode(monkeypatch, capsys):
    sequence, output = exited_sequence_and_output(
        prepared_source(), body=b"FAKE_PRIVATE_STORE_BODY"
    )
    updated = sequence.select_result(output)

    def forbidden(*args, **kwargs):
        pytest.fail("canonical publication must remain passive exact metadata")

    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"),
            (Path, "open"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (time, "monotonic"),
            (time, "time"),
            (AttemptOutput, "decode_json_object"),
            (AttemptOutput, "reconcile"),
        ):
            patch.setattr(owner, name, forbidden)
        store = AttemptSequenceStore()
        store.publish(sequence)
        store.compare_and_set(sequence, updated)
        store.compare_and_set(updated, updated)
    assert store.current is updated
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
@pytest.mark.parametrize("stamp", [None, 1, 2, MAX_COUNTER])
def test_report_stamp_constructor_matrix(count, stamp):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    if count or stamp is None:
        sequence = AttemptSequence(FINGERPRINT, 10, attempts, None, stamp)
        assert sequence.report_stamp == stamp
    else:
        with pytest.raises(
            ValueError, match="^attempt report stamp requires a reserved attempt$"
        ):
            AttemptSequence(FINGERPRINT, 10, attempts, None, stamp)


@pytest.mark.parametrize(
    "stamp", [True, "1", 0, -1, 1.5, b"1", MAX_COUNTER + 1, (1,), [1]]
)
def test_report_stamp_rejects_invalid_metadata(stamp):
    attempts = (sequence_record("exited"),)
    with pytest.raises(ValueError, match="^invalid attempt report stamp$"):
        AttemptSequence(FINGERPRINT, 10, attempts, None, stamp)


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
def test_reconcile_stamped_reports_extend_the_lineage(count):
    attempts = tuple(
        sequence_record("exited" if n < count else "running", n)
        for n in range(1, count + 1)
    )
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    report = attempts[-1].record(AttemptEvent("exited", 1, 0))
    stamped = sequence.reconcile_report(report, report_stamp=1)
    assert stamped.report_stamp == 1
    assert stamped.current.state == "exited"
    assert sequence.report_stamp is None
    again = stamped.reconcile_report(report, report_stamp=2)
    assert again.report_stamp == 2
    assert again.attempts == stamped.attempts
    assert stamped.reconcile_report(report, report_stamp=1) is stamped


@pytest.mark.parametrize("first", [1, 2, 100])
@pytest.mark.parametrize("later", [1, 2, 100])
def test_reconcile_rejects_stale_report_stamps(first, later):
    attempts = (sequence_record("running"),)
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    report = attempts[0].record(AttemptEvent("exited", 1, 0))
    stamped = sequence.reconcile_report(report, report_stamp=first)
    if later < first:
        with pytest.raises(
            ValueError, match="^attempt report stamp is not fresh$"
        ):
            stamped.reconcile_report(report, report_stamp=later)
    elif later == first:
        assert stamped.reconcile_report(report, report_stamp=later) is stamped
    else:
        advanced = stamped.reconcile_report(report, report_stamp=later)
        assert advanced.report_stamp == later
    assert stamped.report_stamp == first


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
def test_reconcile_reused_stamp_rejects_changed_content(count):
    attempts = tuple(
        sequence_record("exited" if n < count else "running", n)
        for n in range(1, count + 1)
    )
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    first_report = attempts[-1].record(CANCEL)
    stamped = sequence.reconcile_report(first_report, report_stamp=7)
    assert stamped.reconcile_report(first_report, report_stamp=7) is stamped
    second_report = first_report.record(AttemptEvent("exited", 3, 0))
    with pytest.raises(
        ValueError, match="^attempt report stamp is not fresh$"
    ):
        stamped.reconcile_report(second_report, report_stamp=7)
    adopted = sequence.reconcile_report(second_report, report_stamp=7)
    assert adopted.report_stamp == 7
    assert stamped.report_stamp == 7
    assert stamped.current.state == "cancelling"


@pytest.mark.parametrize(
    "stamp", [True, "1", 0, -1, 1.5, b"1", MAX_COUNTER + 1, (1,), [1]]
)
def test_reconcile_rejects_invalid_stamp_values(stamp):
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("running"),))
    report = sequence_record("exited")
    with pytest.raises(ValueError, match="^invalid attempt report stamp$"):
        sequence.reconcile_report(report, report_stamp=stamp)
    assert sequence.report_stamp is None


def test_reconcile_stamped_then_unstamped_is_rejected():
    attempts = (sequence_record("running"),)
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    stamped = sequence.reconcile_report(
        attempts[0].record(AttemptEvent("exited", 1, 0)), report_stamp=1
    )
    with pytest.raises(
        ValueError, match="^attempt report requires a report stamp$"
    ):
        stamped.reconcile_report(stamped.current)
    assert stamped.report_stamp == 1


def test_reconcile_unstamped_then_stamped_adopts_stamping():
    attempts = (sequence_record("running"),)
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    stamped = sequence.reconcile_report(
        attempts[0].record(AttemptEvent("exited", 1, 0)), report_stamp=3
    )
    assert stamped.report_stamp == 3
    with pytest.raises(
        ValueError, match="^attempt report stamp is not fresh$"
    ):
        stamped.reconcile_report(stamped.current, report_stamp=1)
    assert stamped.reconcile_report(stamped.current, report_stamp=4).report_stamp == 4


def test_report_stamps_are_delivery_counters_not_clocks():
    attempts = (sequence_record("running"),)
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    report = attempts[0].record(AttemptEvent("exited", 1, 0))
    stamped = sequence.reconcile_report(report, report_stamp=1)
    advanced = stamped.reconcile_report(report, report_stamp=MAX_COUNTER)
    assert advanced.report_stamp == MAX_COUNTER
    with pytest.raises(ValueError, match="^invalid attempt report stamp$"):
        advanced.reconcile_report(report, report_stamp=MAX_COUNTER + 1)


def test_report_stamp_survives_begin_and_select():
    sequence, output = exited_sequence_and_output(prepared_source())
    stamped = sequence.reconcile_report(output.attempt, report_stamp=5)
    assert stamped.report_stamp == 5
    reserved = stamped.begin_attempt()
    assert reserved.report_stamp == 5
    assert stamped.select_result(output).report_stamp == 5
    with pytest.raises(
        ValueError, match="^attempt report requires a report stamp$"
    ):
        stamped.reconcile_report(stamped.current)


def test_report_stamp_serialization_is_metadata_only():
    sequence, output = exited_sequence_and_output(
        prepared_source(), body=b"FAKE_PRIVATE_STAMPED_BODY"
    )
    stamped = sequence.reconcile_report(output.attempt, report_stamp=42)
    data = stamped.to_dict()
    assert data["report_stamp"] == 42
    data["report_stamp"] = 7
    assert stamped.to_dict()["report_stamp"] == 42
    encoded = json.dumps(stamped.to_dict())
    assert "FAKE_PRIVATE_STAMPED_BODY" not in encoded
    assert "stdout" not in data
    with pytest.raises(FrozenInstanceError):
        stamped.report_stamp = 7


@pytest.mark.parametrize("count", range(1, MAX_ATTEMPTS + 1))
def test_store_lineage_rejects_report_stamp_regression(count):
    attempts = tuple(sequence_record("exited", n) for n in range(1, count + 1))
    stamped = AttemptSequence(FINGERPRINT, 10, attempts, None, 5)
    regressed = AttemptSequence(FINGERPRINT, 10, attempts, None, 4)
    unstamped = AttemptSequence(FINGERPRINT, 10, attempts)
    advanced = AttemptSequence(FINGERPRINT, 10, attempts, None, 6)
    store = AttemptSequenceStore()
    store.publish(stamped)
    for updated in (regressed, unstamped):
        with pytest.raises(
            ValueError,
            match="^updated sequence does not extend the canonical lineage$",
        ):
            store.compare_and_set(stamped, updated)
    assert store.compare_and_set(stamped, advanced) is advanced
    assert store.current.report_stamp == 6


def test_report_stamps_do_not_cross_independent_sequences():
    first = AttemptSequence(FINGERPRINT, 10, (sequence_record("running"),))
    foreign = AttemptRecord("b" * 64, 1, 10, PREFIXES["running"])
    second = AttemptSequence("b" * 64, 10, (foreign,))
    report = first.current.record(AttemptEvent("exited", 1, 0))
    stamped = first.reconcile_report(report, report_stamp=9)
    assert stamped.report_stamp == 9
    assert second.report_stamp is None
    other_report = AttemptRecord("b" * 64, 1, 10, PREFIXES["exited"])
    assert second.reconcile_report(other_report).report_stamp is None


def test_stamped_reconcile_is_passive_without_io_or_clock(monkeypatch, capsys):
    attempts = (sequence_record("running"),)
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    report = attempts[0].record(AttemptEvent("exited", 1, 0))
    before = sequence.to_dict(), report.to_dict()

    def forbidden(*args, **kwargs):
        pytest.fail("report stamps must remain passive exact metadata")

    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"),
            (Path, "open"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (time, "monotonic"),
            (time, "time"),
            (AttemptOutput, "decode_json_object"),
            (AttemptOutput, "reconcile"),
        ):
            patch.setattr(owner, name, forbidden)
        stamped = sequence.reconcile_report(report, report_stamp=1)
        advanced = stamped.reconcile_report(report, report_stamp=2)
        assert advanced.reconcile_report(report, report_stamp=2) is advanced
        with pytest.raises(ValueError):
            advanced.reconcile_report(report, report_stamp=1)
    assert (sequence.to_dict(), report.to_dict()) == before
    assert capsys.readouterr() == ("", "")


def test_execution_request_rejects_invalid_metadata():
    for kwargs in (
        {"request_fingerprint": "a" * 63},
        {"request_fingerprint": "A" * 64},
        {"request_fingerprint": "g" * 64},
        {"request_fingerprint": 1},
        {"request_fingerprint": FINGERPRINT, "attempt_number": 0},
        {"request_fingerprint": FINGERPRINT, "attempt_number": True},
        {"request_fingerprint": FINGERPRINT, "attempt_number": MAX_COUNTER + 1},
        {"request_fingerprint": FINGERPRINT, "attempt_number": 1, "timeout_ms": 0},
        {"request_fingerprint": FINGERPRINT, "attempt_number": 1, "timeout_ms": True},
        {
            "request_fingerprint": FINGERPRINT,
            "attempt_number": 1,
            "timeout_ms": MAX_COUNTER + 1,
        },
    ):
        with pytest.raises(ValueError):
            AttemptExecutionRequest(
                kwargs.get("request_fingerprint", FINGERPRINT),
                kwargs.get("attempt_number", 1),
                kwargs.get("timeout_ms", 10),
            )
    request = AttemptExecutionRequest(FINGERPRINT, MAX_COUNTER, MAX_COUNTER)
    assert request.attempt_number == MAX_COUNTER


def test_cancel_request_rejects_invalid_metadata():
    for fingerprint, number in (
        ("a" * 63, 1),
        ("A" * 64, 1),
        ("g" * 64, 1),
        (1, 1),
        (FINGERPRINT, 0),
        (FINGERPRINT, True),
        (FINGERPRINT, MAX_COUNTER + 1),
    ):
        with pytest.raises(ValueError):
            AttemptCancelRequest(fingerprint, number)
    request = AttemptCancelRequest(FINGERPRINT, MAX_COUNTER)
    assert request.attempt_number == MAX_COUNTER


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
def test_request_execution_state_matrix(count):
    attempts = tuple(
        sequence_record("exited", n) for n in range(1, count)
    ) + ((sequence_record("ready", count),) if count else ())
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    if count == 0:
        with pytest.raises(
            ValueError, match="^attempt execution requires a reserved attempt$"
        ):
            sequence.request_execution()
        return
    request = sequence.request_execution()
    assert request.request_fingerprint == FINGERPRINT
    assert request.attempt_number == count
    assert request.timeout_ms == 10
    assert sequence.request_execution() == request


@pytest.mark.parametrize("state", PREFIXES)
def test_request_execution_requires_a_ready_current(state):
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record(state),))
    if state == "ready":
        assert sequence.request_execution().attempt_number == 1
    else:
        with pytest.raises(
            ValueError, match="^attempt execution requires a ready attempt$"
        ):
            sequence.request_execution()


def test_request_execution_is_pure_and_repeatable():
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("ready"),))
    before = sequence.to_dict()
    first = sequence.request_execution()
    second = sequence.request_execution()
    assert first == second
    assert first is not second
    assert sequence.to_dict() == before
    assert sequence.current.state == "ready"
    with pytest.raises(FrozenInstanceError):
        first.attempt_number = 2


def test_request_execution_rejects_a_closed_sequence():
    sequence, output = exited_sequence_and_output(prepared_source())
    closed = sequence.select_result(output)
    with pytest.raises(
        ValueError, match="^attempt execution requires a ready attempt$"
    ):
        closed.request_execution()


def test_request_execution_serialization_is_metadata_only():
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("ready"),))
    request = sequence.request_execution()
    data = request.to_dict()
    assert data == {
        "schema_version": "mumei.verifier-attempt-execution/v1",
        "request_fingerprint": FINGERPRINT,
        "attempt_number": 1,
        "timeout_ms": 10,
    }
    encoded = json.dumps(data)
    assert "stdout" not in encoded
    data["attempt_number"] = 9
    assert request.to_dict()["attempt_number"] == 1


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
def test_request_cancellation_state_matrix(count):
    attempts = tuple(
        sequence_record("exited", n) for n in range(1, count)
    ) + ((sequence_record("running", count),) if count else ())
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    if count == 0:
        with pytest.raises(
            ValueError, match="^attempt cancellation requires a reserved attempt$"
        ):
            sequence.request_cancellation()
        return
    request = sequence.request_cancellation()
    assert request.request_fingerprint == FINGERPRINT
    assert request.attempt_number == count
    assert sequence.request_cancellation() == request


@pytest.mark.parametrize("state", PREFIXES)
def test_request_cancellation_requires_a_running_current(state):
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record(state),))
    if state == "running":
        assert sequence.request_cancellation().attempt_number == 1
    else:
        with pytest.raises(
            ValueError, match="^attempt cancellation requires a running attempt$"
        ):
            sequence.request_cancellation()


def test_request_cancellation_is_pure_and_repeatable():
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("running"),))
    before = sequence.to_dict()
    first = sequence.request_cancellation()
    second = sequence.request_cancellation()
    assert first == second
    assert first is not second
    assert sequence.to_dict() == before
    assert sequence.current.state == "running"
    with pytest.raises(FrozenInstanceError):
        first.attempt_number = 2


def test_request_cancellation_cannot_be_declared_twice():
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("running"),))
    request = sequence.request_cancellation()
    assert request.attempt_number == 1
    cancelling = sequence.reconcile_report(sequence.current.record(CANCEL))
    assert cancelling.current.state == "cancelling"
    with pytest.raises(
        ValueError, match="^attempt cancellation requires a running attempt$"
    ):
        cancelling.request_cancellation()


def test_request_cancellation_serialization_is_metadata_only():
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("running"),))
    request = sequence.request_cancellation()
    data = request.to_dict()
    assert data == {
        "schema_version": "mumei.verifier-attempt-cancel/v1",
        "request_fingerprint": FINGERPRINT,
        "attempt_number": 1,
    }
    encoded = json.dumps(data)
    assert "stdout" not in encoded
    data["attempt_number"] = 9
    assert request.to_dict()["attempt_number"] == 1


def test_requests_track_the_current_attempt_across_reports():
    sequence = AttemptSequence(FINGERPRINT, 10, (sequence_record("ready"),))
    execution = sequence.request_execution()
    started = sequence.reconcile_report(sequence.current.record(START))
    with pytest.raises(
        ValueError, match="^attempt execution requires a ready attempt$"
    ):
        started.request_execution()
    cancellation = started.request_cancellation()
    assert cancellation.attempt_number == execution.attempt_number == 1
    cancelled = started.reconcile_report(
        started.current.record(CANCEL).record(AttemptEvent("cancelled", 4))
    )
    resumed = cancelled.begin_attempt()
    assert resumed.request_execution().attempt_number == 2


def test_requests_are_independent_of_stamps_and_the_store():
    attempts = (sequence_record("running"),)
    stamped = AttemptSequence(FINGERPRINT, 10, attempts, None, 5)
    assert stamped.request_cancellation().attempt_number == 1
    store = AttemptSequenceStore()
    store.publish(stamped)
    assert store.current.request_cancellation() == AttemptCancelRequest(
        FINGERPRINT, 1
    )
    with pytest.raises(
        ValueError, match="^attempt execution requires a ready attempt$"
    ):
        store.current.request_execution()


def test_requests_are_passive_without_io_clock_or_spawn(monkeypatch, capsys):
    ready = AttemptSequence(FINGERPRINT, 10, (sequence_record("ready"),))
    running = AttemptSequence(FINGERPRINT, 10, (sequence_record("running"),))
    before = ready.to_dict(), running.to_dict()

    def forbidden(*args, **kwargs):
        pytest.fail("attempt requests must remain passive exact metadata")

    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"),
            (Path, "open"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (os, "kill"),
            (time, "monotonic"),
            (time, "time"),
        ):
            patch.setattr(owner, name, forbidden)
        assert ready.request_execution().attempt_number == 1
        assert running.request_cancellation().attempt_number == 1
    assert (ready.to_dict(), running.to_dict()) == before
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("stream", sorted(STREAM_KINDS))
@pytest.mark.parametrize("complete", [True, False])
def test_output_stream_collection_constructor_matrix(stream, complete):
    snapshot = output_snapshot(stream=stream, complete=complete)
    assert snapshot.stream == stream
    assert snapshot.complete is complete
    manifest = snapshot.to_dict()
    if complete:
        assert manifest["stdout"] == {
            "sha256": hashlib.sha256(STDOUT).hexdigest(),
            "size_bytes": len(STDOUT),
        }
    else:
        assert manifest["stdout"]["complete"] is False


@pytest.mark.parametrize(
    "stream",
    ["stderr", "STDOUT", "out", "", 1, True, b"stdout", None, ("stdout",)],
)
def test_output_stream_rejects_unsupported_names(stream):
    with pytest.raises(
        ValueError, match="^unsupported attempt output stream$"
    ):
        output_snapshot(stream=stream)


@pytest.mark.parametrize("complete", [0, 1, "true", "false", None, 1.0, b"1"])
def test_output_completeness_requires_an_exact_bool(complete):
    with pytest.raises(
        ValueError,
        match="^invalid attempt output completeness declaration$",
    ):
        output_snapshot(complete=complete)


@pytest.mark.parametrize("size", [0, 1, MAX_STDOUT_BYTES])
def test_output_incomplete_snapshots_stay_bounded_and_hashed(size):
    body = b"x" * size
    snapshot = output_snapshot(stdout=body, complete=False)
    assert snapshot.complete is False
    assert len(snapshot.stdout) == size
    assert (
        snapshot.expected_stdout_sha256 == hashlib.sha256(body).hexdigest()
    )
    with pytest.raises(ValueError, match="^stdout must be bounded"):
        AttemptOutput(
            record(*PREFIXES["exited"]),
            b"x" * (MAX_STDOUT_BYTES + 1),
            "a" * 64,
            "stdout",
            False,
        )


@pytest.mark.parametrize("left", [True, False])
@pytest.mark.parametrize("right", [True, False])
def test_output_reconcile_covers_completeness_claims(left, right):
    first = output_snapshot(complete=left)
    second = output_snapshot(complete=right)
    if left == right:
        assert first.reconcile(second) is first
    else:
        for pair in ((first, second), (second, first)):
            with pytest.raises(
                ValueError, match="attempt output report conflict"
            ):
                pair[0].reconcile(pair[1])


def test_output_default_manifest_and_fingerprint_are_unchanged():
    default = output_snapshot()
    explicit = output_snapshot(stream="stdout", complete=True)
    assert default == explicit
    assert default.to_dict() == explicit.to_dict()
    manifest = default.to_dict()
    assert "stream" not in manifest["stdout"]
    assert "complete" not in manifest["stdout"]
    changed = output_snapshot(complete=False)
    assert (
        changed.to_dict()["output_fingerprint"]
        != manifest["output_fingerprint"]
    )
    assert changed.to_dict()["stdout"]["complete"] is False


def test_output_from_prepared_declares_collection_metadata():
    prepared = prepared_source()
    sequence, _ = exited_sequence_and_output(prepared, body=STDOUT)
    report = sequence.current
    output = AttemptOutput.from_prepared(
        prepared,
        1,
        report,
        STDOUT,
        hashlib.sha256(STDOUT).hexdigest(),
        stream="stdout",
        complete=False,
    )
    assert output.stream == "stdout"
    assert output.complete is False
    with pytest.raises(
        ValueError, match="^unsupported attempt output stream$"
    ):
        AttemptOutput.from_prepared(
            prepared,
            1,
            report,
            STDOUT,
            hashlib.sha256(STDOUT).hexdigest(),
            stream="stderr",
        )


def test_output_completeness_is_a_declaration_not_a_proof():
    partial = output_snapshot(stdout=b"x" * 10, complete=False)
    full_claim = output_snapshot(stdout=b"x" * 10, complete=True)
    assert partial.stdout == full_claim.stdout
    assert partial.to_dict()["output_fingerprint"] != full_claim.to_dict()[
        "output_fingerprint"
    ]
    with pytest.raises(ValueError, match="attempt output report conflict"):
        partial.reconcile(full_claim)
    assert output_snapshot(stdout=b"", complete=True).complete is True


def test_selected_result_marks_incomplete_snapshots():
    prepared = prepared_source()
    sequence, output = exited_sequence_and_output(prepared, body=STDOUT)
    incomplete = AttemptOutput(
        output.attempt,
        STDOUT,
        hashlib.sha256(STDOUT).hexdigest(),
        "stdout",
        False,
    )
    selected = sequence.select_result(incomplete)
    assert selected.selected_result[1] == incomplete.to_dict()[
        "output_fingerprint"
    ]
    with pytest.raises(
        ValueError, match="attempt sequence already has a selected result"
    ):
        selected.select_result(output)


def test_output_stream_metadata_is_passive_without_io_or_clock(
    monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        pytest.fail("stream declarations must remain passive exact metadata")

    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"),
            (Path, "open"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (time, "monotonic"),
            (time, "time"),
        ):
            patch.setattr(owner, name, forbidden)
        snapshot = output_snapshot(stdout=b"partial", complete=False)
        assert snapshot.reconcile(snapshot) is snapshot
        snapshot.to_dict()
    assert snapshot.to_dict() == output_snapshot(
        stdout=b"partial", complete=False
    ).to_dict()
    assert capsys.readouterr() == ("", "")


def test_evidence_candidate_rejects_invalid_metadata():
    for kwargs in (
        {"request_fingerprint": "a" * 63},
        {"request_fingerprint": "G" * 64},
        {"request_fingerprint": 1},
        {"request_fingerprint": FINGERPRINT, "attempt_number": 0},
        {"request_fingerprint": FINGERPRINT, "attempt_number": True},
        {"request_fingerprint": FINGERPRINT, "attempt_number": MAX_COUNTER + 1},
        {
            "request_fingerprint": FINGERPRINT,
            "output_fingerprint": "z" * 64,
        },
        {"request_fingerprint": FINGERPRINT, "output_fingerprint": "a" * 63},
        {"request_fingerprint": FINGERPRINT, "output_fingerprint": 0},
        {"request_fingerprint": FINGERPRINT, "output_fingerprint": None},
    ):
        with pytest.raises(ValueError):
            AttemptEvidenceCandidate(
                kwargs.get("request_fingerprint", FINGERPRINT),
                kwargs.get("attempt_number", 1),
                kwargs.get("output_fingerprint", "b" * 64),
            )
    candidate = AttemptEvidenceCandidate(FINGERPRINT, 1, "b" * 64)
    assert candidate.output_fingerprint == "b" * 64


@pytest.mark.parametrize("count", range(0, MAX_ATTEMPTS + 1))
def test_evidence_candidate_requires_a_selected_result(count):
    attempts = tuple(
        sequence_record("exited" if n < count else "ready", n)
        for n in range(1, count + 1)
    )
    sequence = AttemptSequence(FINGERPRINT, 10, attempts)
    with pytest.raises(
        ValueError, match="^evidence candidate requires a selected result$"
    ):
        sequence.evidence_candidate()


def test_evidence_candidate_names_the_selected_result():
    sequence, output = exited_sequence_and_output(
        prepared_source(), body=b"{" + b'"a":1}'
    )
    selected = sequence.select_result(output)
    candidate = selected.evidence_candidate()
    assert candidate.request_fingerprint == sequence.request_fingerprint
    assert candidate.attempt_number == output.attempt.attempt_number
    assert candidate.output_fingerprint == output.to_dict()[
        "output_fingerprint"
    ]
    assert candidate == AttemptEvidenceCandidate(
        sequence.request_fingerprint,
        1,
        output.to_dict()["output_fingerprint"],
    )
    assert selected.evidence_candidate() == candidate
    assert selected.evidence_candidate() is not candidate


def test_evidence_candidate_binds_the_selected_attempt_ordinal():
    prepared = prepared_source()
    first = (
        AttemptSequence.from_prepared(prepared)
        .begin_attempt()
        .reconcile_report(
            AttemptRecord.from_prepared(prepared, 1).reconcile(
                AttemptRecord.from_prepared(prepared, 1)
                .record(START)
                .record(AttemptEvent("timed_out", 10))
            )
        )
        .begin_attempt()
    )
    report = first.current.record(START).record(AttemptEvent("exited", 2, 0))
    second = first.reconcile_report(report)
    output = AttemptOutput.from_prepared(
        prepared, 2, report, b"{}", hashlib.sha256(b"{}").hexdigest()
    )
    selected = second.select_result(output)
    candidate = selected.evidence_candidate()
    assert candidate.attempt_number == 2


def test_evidence_candidate_is_pure_and_body_free():
    sequence, output = exited_sequence_and_output(
        prepared_source(), body=b"FAKE_PRIVATE_EVIDENCE_BODY"
    )
    selected = sequence.select_result(output)
    before = selected.to_dict()
    candidate = selected.evidence_candidate()
    data = candidate.to_dict()
    assert data == {
        "schema_version": "mumei.verifier-evidence-candidate/v1",
        "request_fingerprint": sequence.request_fingerprint,
        "attempt_number": 1,
        "output_fingerprint": output.to_dict()["output_fingerprint"],
    }
    encoded = json.dumps(data)
    for forbidden in ("stdout", "FAKE_PRIVATE_EVIDENCE_BODY", "stream"):
        assert forbidden not in encoded
    data["attempt_number"] = 9
    assert candidate.to_dict()["attempt_number"] == 1
    assert selected.to_dict() == before
    with pytest.raises(FrozenInstanceError):
        candidate.attempt_number = 9


@pytest.mark.parametrize("code", [-1, 0, 1])
def test_evidence_candidate_covers_any_exit_code(code):
    sequence, output = exited_sequence_and_output(
        prepared_source(), code=code
    )
    candidate = sequence.select_result(output).evidence_candidate()
    assert candidate.attempt_number == 1


def test_evidence_candidate_survives_stamps_and_the_store():
    sequence, output = exited_sequence_and_output(prepared_source())
    stamped = sequence.reconcile_report(output.attempt, report_stamp=3)
    selected = stamped.select_result(output)
    candidate = selected.evidence_candidate()
    store = AttemptSequenceStore()
    store.publish(selected)
    assert store.current.evidence_candidate() == candidate
    assert selected.report_stamp == 3


def test_evidence_candidates_do_not_arbitrate_independent_sequences():
    prepared = prepared_source()
    sequence, output = exited_sequence_and_output(prepared)
    selected = sequence.select_result(output)
    foreign_record = AttemptRecord("b" * 64, 1, 10, PREFIXES["exited"])
    foreign_output = AttemptOutput(
        foreign_record,
        STDOUT,
        hashlib.sha256(STDOUT).hexdigest(),
    )
    foreign = AttemptSequence("b" * 64, 10, (foreign_record,))
    foreign_selected = foreign.select_result(foreign_output)
    assert (
        selected.evidence_candidate().request_fingerprint
        != foreign_selected.evidence_candidate().request_fingerprint
    )


def test_evidence_candidate_is_passive_without_io_or_decode(
    monkeypatch, capsys
):
    sequence, output = exited_sequence_and_output(prepared_source())
    selected = sequence.select_result(output)
    before = selected.to_dict(), output.to_dict()

    def forbidden(*args, **kwargs):
        pytest.fail("evidence candidates must remain passive exact metadata")

    with monkeypatch.context() as patch:
        for owner, name in (
            (builtins, "open"),
            (Path, "open"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (time, "monotonic"),
            (time, "time"),
            (AttemptOutput, "decode_json_object"),
        ):
            patch.setattr(owner, name, forbidden)
        assert selected.evidence_candidate().attempt_number == 1
    assert (selected.to_dict(), output.to_dict()) == before
    assert capsys.readouterr() == ("", "")
