"""Bounded host-reported attempts and opaque output, not execution or Evidence.

Records cannot authorize a tool, prove observation freshness or establish that
a process was stopped. No default verification path consumes these records.
"""

import errno
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from decimal import Context, Decimal
from pathlib import Path

from agent.verification_planner import PreparedSourceRequest

MAX_COUNTER = (1 << 63) - 1
MAX_EVENTS = 3
MAX_ATTEMPTS = 16
MAX_STDOUT_BYTES = 64 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NUMBER_CHARS = 128
EVENT_KINDS = frozenset(
    {"started", "cancel_requested", "exited", "failed", "timed_out", "cancelled"}
)
STREAM_KINDS = frozenset({"stdout", "stderr"})
TERMINAL_STATES = frozenset({"exited", "failed", "timed_out", "cancelled"})
EVIDENCE_CHECK_OUTCOMES = frozenset({"valid", "failed", "cancelled"})
_TRANSITIONS = {
    ("ready", "started"): "running",
    ("ready", "cancelled"): "cancelled",
    ("running", "cancel_requested"): "cancelling",
    ("running", "exited"): "exited",
    ("running", "failed"): "failed",
    ("running", "timed_out"): "timed_out",
    ("cancelling", "exited"): "exited",
    ("cancelling", "failed"): "failed",
    ("cancelling", "timed_out"): "timed_out",
    ("cancelling", "cancelled"): "cancelled",
}


def _counter(value: int, *, positive: bool = False) -> None:
    if type(value) is not int or not (int(positive) <= value <= MAX_COUNTER):
        raise ValueError("invalid bounded attempt counter")


def _fingerprint(value: str) -> None:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid prepared request fingerprint")


def _json_depth(text: str) -> None:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds transport bound")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("invalid JSON nesting")
    if depth or quoted:
        raise ValueError("incomplete JSON structure")


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json_integer(token: str) -> int:
    if len(token) > MAX_JSON_NUMBER_CHARS:
        raise ValueError("JSON number exceeds transport bound")
    return int(token)


def _json_decimal(token: str) -> Decimal:
    if len(token) > MAX_JSON_NUMBER_CHARS:
        raise ValueError("JSON number exceeds transport bound")
    number = Decimal(token, context=Context())
    if not number.is_finite():
        raise ValueError("nonfinite JSON number")
    return number


def _json_constant(token: str) -> None:
    raise ValueError("non-JSON numeric constant")


@dataclass(frozen=True)
class AttemptEvent:
    kind: str
    elapsed_ms: int
    exit_code: int | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in EVENT_KINDS:
            raise ValueError("unsupported attempt event")
        _counter(self.elapsed_ms)
        if self.kind == "exited":
            if (
                type(self.exit_code) is not int
                or not -MAX_COUNTER - 1 <= self.exit_code <= MAX_COUNTER
            ):
                raise ValueError("exited event requires a bounded integer exit code")
        elif self.exit_code is not None:
            raise ValueError("only exited events carry exit codes")

    def to_dict(self) -> dict:
        result = {"kind": self.kind, "elapsed_ms": self.elapsed_ms}
        if self.exit_code is not None:
            result["exit_code"] = self.exit_code
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptEvent":
        """Rebuild a declared event snapshot; constructors re-validate it.

        The snapshot is a host declaration: restoration re-checks every
        invariant the constructor enforces but trusts nothing else — a
        foreign schema, unknown keys or a malformed event are static
        errors, not recovered history."""
        if type(data) is not dict:
            raise ValueError("attempt event requires a declared snapshot")
        allowed = {"kind", "elapsed_ms", "exit_code"}
        if set(data) - allowed or not {"kind", "elapsed_ms"} <= set(data):
            raise ValueError("attempt event snapshot has unknown or missing keys")
        return cls(data["kind"], data["elapsed_ms"], data.get("exit_code"))


@dataclass(frozen=True)
class AttemptRecord:
    """Immutable observation history; fingerprint/attempt number are not tokens.

    Elapsed counters are host reports relative to the recorded start, not clock
    readings. Hosts own attempt-number uniqueness and real runner enforcement.
    """

    request_fingerprint: str
    attempt_number: int
    timeout_ms: int
    events: tuple[AttemptEvent, ...] = ()

    def __post_init__(self) -> None:
        _fingerprint(self.request_fingerprint)
        _counter(self.attempt_number, positive=True)
        _counter(self.timeout_ms, positive=True)
        if type(self.events) is not tuple or len(self.events) > MAX_EVENTS:
            raise ValueError("attempt history must be bounded immutable events")
        self._state()

    @classmethod
    def from_prepared(
        cls, prepared: PreparedSourceRequest, attempt_number: int
    ) -> "AttemptRecord":
        if type(prepared) is not PreparedSourceRequest:
            raise ValueError("attempt binding requires a prepared source request")
        if prepared.plan.policy.allowed_permissions is None:
            raise ValueError("attempt binding requires an explicit permission policy")
        selected = prepared.plan.selected
        assert selected is not None
        return cls(
            prepared.to_dict()["request_fingerprint"],
            attempt_number,
            selected.timeout_ms,
        )

    def _state(self) -> str:
        state = "ready"
        elapsed = 0
        for event in self.events:
            if type(event) is not AttemptEvent:
                raise ValueError("invalid attempt event record")
            following = _TRANSITIONS.get((state, event.kind))
            if following is None:
                raise ValueError("invalid attempt lifecycle transition")
            if event.elapsed_ms < elapsed:
                raise ValueError("attempt elapsed counters must be monotonic")
            if event.kind == "started" and event.elapsed_ms != 0:
                raise ValueError("attempt start must define elapsed zero")
            if event.kind == "timed_out" and event.elapsed_ms < self.timeout_ms:
                raise ValueError("timeout observation precedes declared deadline")
            if event.kind == "exited" and event.elapsed_ms >= self.timeout_ms:
                raise ValueError("exit observation reaches declared deadline")
            state, elapsed = following, event.elapsed_ms
        return state

    @property
    def state(self) -> str:
        return self._state()

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def record(self, event: AttemptEvent) -> "AttemptRecord":
        return replace(self, events=(*self.events, event))

    def reconcile(self, incoming: "AttemptRecord") -> "AttemptRecord":
        """Extend this lineage only; identical reports are idempotent, not fresh.

        No branch wins implicitly. Hosts must retain/atomically update their
        current record; this does not authenticate reports or prevent replay.
        """
        if type(incoming) is not AttemptRecord:
            raise ValueError("reconciliation requires an attempt record")
        if (
            incoming.request_fingerprint != self.request_fingerprint
            or incoming.attempt_number != self.attempt_number
            or incoming.timeout_ms != self.timeout_ms
        ):
            raise ValueError("attempt report binding mismatch")
        if incoming.events[: len(self.events)] != self.events:
            raise ValueError("attempt report cannot rewind or replace history")
        return self if incoming.events == self.events else incoming

    def to_dict(self) -> dict:
        return {
            "schema_version": "mumei.verifier-attempt/v1",
            "request_fingerprint": self.request_fingerprint,
            "attempt_number": self.attempt_number,
            "timeout_ms": self.timeout_ms,
            "state": self.state,
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptRecord":
        """Rebuild a declared record snapshot; constructors re-validate it.

        The snapshot is a host declaration: restoration re-checks every
        invariant the constructor enforces but trusts nothing else — a
        foreign schema, unknown keys, a malformed event list or a declared
        `state` that disagrees with the replayed events are static errors,
        not recovered history."""
        if type(data) is not dict or data.get("schema_version") != "mumei.verifier-attempt/v1":
            raise ValueError("attempt record requires its declared snapshot schema")
        required = {
            "request_fingerprint",
            "attempt_number",
            "timeout_ms",
            "state",
            "events",
        }
        allowed = required | {"schema_version"}
        if set(data) - allowed or required - set(data):
            raise ValueError("attempt record snapshot has unknown or missing keys")
        events = data["events"]
        if type(events) is not list or len(events) > MAX_EVENTS:
            raise ValueError("attempt record snapshot requires a bounded event list")
        record = cls(
            data["request_fingerprint"],
            data["attempt_number"],
            data["timeout_ms"],
            tuple(AttemptEvent.from_dict(event) for event in events),
        )
        if record.state != data["state"]:
            raise ValueError("attempt record declared state disagrees with its events")
        return record


@dataclass(frozen=True)
class AttemptSequence:
    """Bounded sequential host records for one request, not a retry scheduler.

    Terminal metadata does not prove cleanup or prevent physical overlap.
    Hosts retain/atomically advance their canonical sequence and own execution,
    global numbering, replay protection and all result/Evidence decisions.
    A selected result is host-declared canonical metadata for the current
    record only: it is not truth, acceptance, a Core check receipt or a
    cross-sequence arbitration outcome. A report stamp is a host-declared
    monotonic counter detecting replays/reordering only: it is not a clock,
    freshness proof or authentication. Execution and cancellation requests
    declared from this value describe intent only: they never spawn, signal or
    confirm a process.
    """

    request_fingerprint: str
    timeout_ms: int
    attempts: tuple[AttemptRecord, ...] = ()
    selected_result: tuple[int, str] | None = None
    report_stamp: int | None = None

    def __post_init__(self) -> None:
        _fingerprint(self.request_fingerprint)
        _counter(self.timeout_ms, positive=True)
        if type(self.attempts) is not tuple or len(self.attempts) > MAX_ATTEMPTS:
            raise ValueError("attempt sequence must be bounded immutable records")
        for ordinal, attempt in enumerate(self.attempts, 1):
            if type(attempt) is not AttemptRecord:
                raise ValueError("attempt sequence requires exact attempt records")
            if (
                attempt.request_fingerprint != self.request_fingerprint
                or attempt.timeout_ms != self.timeout_ms
                or attempt.attempt_number != ordinal
            ):
                raise ValueError("attempt sequence binding or ordinal mismatch")
            if ordinal < len(self.attempts) and not attempt.is_terminal:
                raise ValueError(
                    "attempt sequence cannot contain nonterminal predecessors"
                )
        if self.selected_result is not None:
            if (
                type(self.selected_result) is not tuple
                or len(self.selected_result) != 2
                or type(self.selected_result[0]) is not int
                or type(self.selected_result[1]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", self.selected_result[1])
            ):
                raise ValueError("invalid selected result metadata")
            if not self.attempts or self.selected_result[0] != len(self.attempts):
                raise ValueError(
                    "selected result must reference the current attempt"
                )
            if self.attempts[-1].state != "exited":
                raise ValueError(
                    "selected result requires an exited current attempt"
                )
        if self.report_stamp is not None:
            if type(self.report_stamp) is not int or not (
                1 <= self.report_stamp <= MAX_COUNTER
            ):
                raise ValueError("invalid attempt report stamp")
            if not self.attempts:
                raise ValueError(
                    "attempt report stamp requires a reserved attempt"
                )

    @classmethod
    def from_prepared(cls, prepared: PreparedSourceRequest) -> "AttemptSequence":
        bound = AttemptRecord.from_prepared(prepared, 1)
        return cls(bound.request_fingerprint, bound.timeout_ms)

    @property
    def current(self) -> AttemptRecord | None:
        return self.attempts[-1] if self.attempts else None

    def begin_attempt(self) -> "AttemptSequence":
        """Reserve the next ready record; do not authorize or start a process."""
        if self.selected_result is not None:
            raise ValueError("a selected result closes the attempt sequence")
        attempt = AttemptRecord(
            self.request_fingerprint, len(self.attempts) + 1, self.timeout_ms
        )
        return replace(self, attempts=(*self.attempts, attempt))

    def withdraw_attempt(self) -> "AttemptSequence":
        """Withdraw the reserved-but-never-started attempt; it never ran.

        A ready record has no running process to signal, so withdrawal records
        the terminal `cancelled` outcome directly — no declared request and no
        observation round-trip, and intent and outcome collapse into one
        declaration. A running attempt still needs `request_cancellation`
        (delivering the signal and confirming the stop stay host duties); a
        terminal record is already finished and an empty sequence withdraws
        nothing. Withdrawal is a host decision only — it is not a crash, a
        timeout or an Evidence verdict, and it does not authorize the next
        attempt (a separate `begin_attempt` still reserves it).
        """
        current = self.current
        if current is None:
            raise ValueError("attempt withdrawal requires a reserved attempt")
        if current.state != "ready":
            raise ValueError("attempt withdrawal requires a ready attempt")
        withdrawn = current.record(AttemptEvent("cancelled", 0))
        return replace(self, attempts=(*self.attempts[:-1], withdrawn))

    def reconcile_report(
        self, incoming: AttemptRecord, report_stamp: int | None = None
    ) -> "AttemptSequence":
        """Extend a known report only; old terminal duplicates are idempotent.

        When supplied, `report_stamp` is a host-declared monotonic counter: it
        must strictly increase across distinct deliveries, a reused stamp only
        reconciles an identical report and a smaller stamp fails as stale.
        Stamps detect replays/reordering only; once a stamp is accepted every
        later report must carry one. Unstamped calls keep legacy behavior.
        """
        if type(incoming) is not AttemptRecord:
            raise ValueError("sequence reconciliation requires an attempt record")
        if report_stamp is not None and (
            type(report_stamp) is not int
            or not 1 <= report_stamp <= MAX_COUNTER
        ):
            raise ValueError("invalid attempt report stamp")
        if self.report_stamp is not None and report_stamp is None:
            raise ValueError("attempt report requires a report stamp")
        if (
            report_stamp is not None
            and self.report_stamp is not None
            and report_stamp < self.report_stamp
        ):
            raise ValueError("attempt report stamp is not fresh")
        if incoming.attempt_number > len(self.attempts):
            raise ValueError("attempt report has no reserved sequence ordinal")
        index = incoming.attempt_number - 1
        current = self.attempts[index]
        following = current.reconcile(incoming)
        if following is current:
            if report_stamp is None or report_stamp == self.report_stamp:
                return self
            return replace(self, report_stamp=report_stamp)
        if report_stamp is not None and report_stamp == self.report_stamp:
            raise ValueError("attempt report stamp is not fresh")
        result = replace(
            self,
            attempts=(*self.attempts[:index], following, *self.attempts[index + 1 :]),
        )
        if report_stamp is None:
            return result
        return replace(result, report_stamp=report_stamp)

    def reconcile(self, incoming: "AttemptSequence") -> "AttemptSequence":
        """Merge an independently-published candidate against this value.

        Two callers that each extended an older common prefix can diverge —
        publication serializes writes, not the histories behind them. The
        declared arbitration is lineage order only: an identical or
        prefix-shorter candidate keeps this value, a strict extension
        returns the candidate, and every true fork — different records at a
        shared ordinal, competing selected results, a stamp regression or a
        foreign request binding — fails closed. This arbitrates between
        VALUES; which side was the canonical store's own stays a host duty.
        """
        if type(incoming) is not AttemptSequence:
            raise ValueError(
                "sequence reconciliation requires an attempt sequence"
            )
        if incoming == self:
            return self
        if _is_lineage_extension(self, incoming):
            return incoming
        if _is_lineage_extension(incoming, self):
            return self
        raise ValueError("attempt sequences diverged")

    def request_execution(self) -> "AttemptExecutionRequest":
        """Declare the current reserved attempt runnable; does not start it.

        The request describes which record a host intends to execute; spawning
        a process, authorizing a tool and confirming a start remain host
        duties. A closed sequence cannot produce a new request.
        """
        current = self.current
        if current is None:
            raise ValueError("attempt execution requires a reserved attempt")
        if current.state != "ready":
            raise ValueError("attempt execution requires a ready attempt")
        return AttemptExecutionRequest(
            self.request_fingerprint, current.attempt_number, self.timeout_ms
        )

    def request_cancellation(self) -> "AttemptCancelRequest":
        """Declare the running attempt should stop; does not stop it.

        The request describes which running record a host intends to cancel;
        delivering the signal and confirming the stop remain host duties. A
        ready, already-cancelling or terminal record cannot produce one, so a
        cancellation intent cannot be declared twice or for nothing running.
        """
        current = self.current
        if current is None:
            raise ValueError("attempt cancellation requires a reserved attempt")
        if current.state != "running":
            raise ValueError("attempt cancellation requires a running attempt")
        return AttemptCancelRequest(
            self.request_fingerprint, current.attempt_number
        )

    def next_dispatch(self) -> "AttemptExecutionRequest | None":
        """The single outstanding dispatchable intent, or None; not a schedule.

        A `ready` current record yields its execution request; anything else —
        including nothing reserved, a running attempt still in flight and a
        terminal record — yields None. None does not mean nothing may run:
        an in-flight attempt continues and host-initiated cancellations are
        declared separately. Ordering between sequences stays a host duty.
        """
        current = self.current
        if current is None or current.state != "ready":
            return None
        return self.request_execution()

    def check_dispatch(
        self, request: "AttemptExecutionRequest | AttemptCancelRequest"
    ) -> None:
        """Require a declared request be deliverable against this value's state.

        An execution request must name the current ready record and a
        cancellation request the current running one; wrong types, foreign
        bindings, stale ordinals and unserved states are static errors. This
        checks the described boundary only — it never dispatches, delivers
        or confirms anything.
        """
        if type(request) is AttemptExecutionRequest:
            current = self.current
            if current is None or current.state != "ready":
                raise ValueError("attempt execution is not dispatchable")
            if (
                request.request_fingerprint != self.request_fingerprint
                or request.attempt_number != current.attempt_number
                or request.timeout_ms != self.timeout_ms
            ):
                raise ValueError("attempt dispatch binding mismatch")
            return
        if type(request) is AttemptCancelRequest:
            current = self.current
            if current is None or current.state != "running":
                raise ValueError("attempt cancellation is not dispatchable")
            if (
                request.request_fingerprint != self.request_fingerprint
                or request.attempt_number != current.attempt_number
            ):
                raise ValueError("attempt dispatch binding mismatch")
            return
        raise ValueError("attempt dispatch requires a declared request")

    def check_output_binding(self, output: "AttemptOutput") -> None:
        """Require this value's current record, without reconciling either input.

        This checks neither competing stdout snapshots nor global current state.
        Hosts still own output conflicts and atomic publication/completion.
        """
        if type(output) is not AttemptOutput or output.attempt != self.current:
            raise ValueError("output does not match the current sequence record")

    def select_result(self, output: "AttemptOutput") -> "AttemptSequence":
        """Declare one output the canonical result, closing the sequence.

        The output must still bind to this value's current record. Selection is
        a host declaration, not a Core check receipt, truth, acceptance or
        arbitration between independent sequences; an already selected result
        rejects competing snapshots and is idempotent only for the same output.
        """
        self.check_output_binding(output)
        marker = (
            output.attempt.attempt_number,
            output.to_dict()["output_fingerprint"],
        )
        if self.selected_result is not None:
            if self.selected_result == marker:
                return self
            raise ValueError("attempt sequence already has a selected result")
        return replace(self, selected_result=marker)

    def evidence_candidate(self) -> "AttemptEvidenceCandidate":
        """Describe the selected result as an Evidence handoff candidate.

        The returned value only names the declared canonical snapshot for a
        host to hand to Core: the fingerprint binds a manifest, not content
        correctness. It performs no normalization and asserts no acceptance —
        Core owns the meaning and acceptance of the original bytes.
        """
        if self.selected_result is None:
            raise ValueError("evidence candidate requires a selected result")
        return AttemptEvidenceCandidate(
            self.request_fingerprint,
            self.selected_result[0],
            self.selected_result[1],
        )

    def evidence_check(
        self, candidate: "AttemptEvidenceCandidate", outcome: str
    ) -> "AttemptEvidenceCheck":
        """Record a declared representation-check outcome for the candidate.

        `candidate` must equal this value's `evidence_candidate()` — a stale
        or foreign descriptor is a static error, not a recorded check. The
        declared `outcome` is one of `EVIDENCE_CHECK_OUTCOMES`: `"valid"`
        (Core returned the known v1 diagnostic for the delivered bytes),
        `"failed"` (the check produced no accepted diagnostic — an invalid
        representation, malformed diagnostic and spawn/I/O failure are
        indistinguishable by design) or `"cancelled"`.

        Recording is a host declaration, not acceptance: `"valid"` only means
        Core's representation check passed; truth, freshness, authenticity,
        correspondence and grade promotion stay unassessed host/Core duties.
        """
        if type(outcome) is not str or outcome not in EVIDENCE_CHECK_OUTCOMES:
            raise ValueError("invalid evidence check outcome")
        if (
            type(candidate) is not AttemptEvidenceCandidate
            or candidate != self.evidence_candidate()
        ):
            raise ValueError(
                "evidence check candidate does not match the selected result"
            )
        return AttemptEvidenceCheck(
            candidate.request_fingerprint,
            candidate.attempt_number,
            candidate.output_fingerprint,
            outcome,
        )

    def to_dict(self) -> dict:
        result = {
            "schema_version": "mumei.verifier-attempt-sequence/v1",
            "request_fingerprint": self.request_fingerprint,
            "timeout_ms": self.timeout_ms,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }
        if self.selected_result is not None:
            result["selected_result"] = {
                "attempt_number": self.selected_result[0],
                "output_fingerprint": self.selected_result[1],
            }
        if self.report_stamp is not None:
            result["report_stamp"] = self.report_stamp
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptSequence":
        """Rebuild a declared lineage snapshot; constructors re-validate it.

        The snapshot is a host declaration: restoration re-checks every
        invariant the constructor enforces — record bindings, ordinals,
        terminal predecessors, the selected-result reference and the
        report stamp — but trusts nothing else. A foreign schema, unknown
        keys, malformed members or a declared `state` that disagrees with
        replayed events are static errors, not recovered history. A
        restored `selected_result` still names a declared fingerprint the
        snapshot cannot re-bind to bytes; durability, canonical-store
        ownership and Evidence remain host duties."""
        if (
            type(data) is not dict
            or data.get("schema_version") != "mumei.verifier-attempt-sequence/v1"
        ):
            raise ValueError("attempt sequence requires its declared snapshot schema")
        required = {"request_fingerprint", "timeout_ms", "attempts"}
        allowed = required | {"schema_version", "selected_result", "report_stamp"}
        if set(data) - allowed or required - set(data):
            raise ValueError("attempt sequence snapshot has unknown or missing keys")
        attempts = data["attempts"]
        if type(attempts) is not list or len(attempts) > MAX_ATTEMPTS:
            raise ValueError("attempt sequence snapshot requires a bounded attempt list")
        selected = data.get("selected_result")
        if selected is not None:
            if type(selected) is not dict or set(selected) != {
                "attempt_number",
                "output_fingerprint",
            }:
                raise ValueError("attempt sequence snapshot has malformed selected result")
            selected = (selected["attempt_number"], selected["output_fingerprint"])
        return cls(
            data["request_fingerprint"],
            data["timeout_ms"],
            tuple(AttemptRecord.from_dict(attempt) for attempt in attempts),
            selected_result=selected,
            report_stamp=data.get("report_stamp"),
        )


def _is_lineage_extension(
    expected: AttemptSequence, updated: AttemptSequence
) -> bool:
    """Whether updated keeps every retained record and may only grow/select.

    Shared request binding, per-record equality or report extension and the
    selected-result closure are required; this is lineage order, not freshness.
    """
    if (
        expected.request_fingerprint != updated.request_fingerprint
        or expected.timeout_ms != updated.timeout_ms
        or len(updated.attempts) < len(expected.attempts)
        or expected.selected_result is not None
        or (
            expected.report_stamp is not None
            and (
                updated.report_stamp is None
                or updated.report_stamp < expected.report_stamp
            )
        )
    ):
        return False
    for prior, following in zip(expected.attempts, updated.attempts):
        try:
            prior.reconcile(following)
        except ValueError:
            return False
    return True


class AttemptSequenceStore:
    """In-process atomic publication point for one canonical lineage.

    Compare-and-set linearizes forks on this object only; it is not durable
    storage, cross-process locking, freshness or authentication. Hosts still
    own authority, boundary replay protection and all result/Evidence
    decisions. The store holds values, never source or stdout bodies.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: AttemptSequence | None = None

    @property
    def current(self) -> AttemptSequence | None:
        """The last published canonical value, or None before publication."""
        return self._current

    def publish(self, sequence: AttemptSequence) -> AttemptSequence:
        """Publish the first canonical value; equal re-publication is a no-op."""
        if type(sequence) is not AttemptSequence:
            raise ValueError("canonical publication requires an attempt sequence")
        with self._lock:
            if self._current is None:
                self._current = sequence
            elif self._current != sequence:
                raise ValueError("canonical sequence publication conflict")
            return self._current

    def compare_and_set(
        self, expected: AttemptSequence, updated: AttemptSequence
    ) -> AttemptSequence:
        """Atomically replace the canonical value with a lineage extension.

        `expected` must equal the stored value: a mismatch reports a fork and
        changes nothing. `updated` must preserve the lineage — same request
        binding, every retained record equal or a valid report extension, and
        no change after a selected result. Equal updates are idempotent.
        """
        if (
            type(expected) is not AttemptSequence
            or type(updated) is not AttemptSequence
        ):
            raise ValueError(
                "canonical compare-and-set requires attempt sequences"
            )
        with self._lock:
            if self._current != expected:
                raise ValueError("canonical sequence compare failed")
            if updated == expected or _is_lineage_extension(expected, updated):
                self._current = updated
            else:
                raise ValueError(
                    "updated sequence does not extend the canonical lineage"
                )
            return self._current


class FileAttemptSequenceStore:
    """File-backed canonical publication point for one lineage (opt-in).

    Same contract as `AttemptSequenceStore` — `publish` is first-wins and
    `compare_and_set` only accepts a lineage extension — but the canonical
    value persists as `mumei.verifier-attempt-sequence/v1` JSON so a host
    reinstates its own lineage across restarts via the same declared parse
    boundary `AttemptSequence.from_dict` enforces.

    Writers serialize on a sibling ``<path>.lock``: `fcntl.flock` on POSIX
    (same host, cross-process) or a process-local lock SHARED PER LOCK PATH
    where `fcntl` is not available — same-process instances still exclude
    each other, cross-process exclusion there needs POSIX `fcntl`. Writes
    are atomic (temp file in the same directory plus `os.replace` followed
    by a directory fsync, so the rename itself survives a power loss), so
    a crash mid-write cannot leave a partial snapshot; a missing file
    reads as unpublished and a malformed one fails closed.

    The `attempt_runner` publish helpers (`publish_dispatch`,
    `dispatch_and_publish`) accept only the in-process
    `AttemptSequenceStore` — their strict type check rejects this store,
    so wiring durable publication into the execution flow needs a
    host-side publish step; that integration is out of scope here.

    Still host duties, unchanged: which file is the canonical one, locking
    across hosts, freshness, authentication, backup policy and every
    result/Evidence decision. The store holds values, never source or
    stdout bodies.
    """

    # Fallback mutual exclusion must outlive a single instance: two stores
    # on one file share the lock keyed by the canonical lock path, so a
    # `fcntl`-less platform still serializes same-process writers.
    _path_locks: dict = {}
    _path_locks_guard = threading.Lock()

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_name(self._path.name + ".lock")

    @property
    def current(self) -> AttemptSequence | None:
        """The last published canonical value, or None before publication."""
        return self._read()

    def publish(self, sequence: AttemptSequence) -> AttemptSequence:
        """Publish the first canonical value; equal re-publication is a no-op."""
        if type(sequence) is not AttemptSequence:
            raise ValueError("canonical publication requires an attempt sequence")
        with self._locked():
            current = self._read()
            if current is None:
                self._write(sequence)
                return sequence
            if current != sequence:
                raise ValueError("canonical sequence publication conflict")
            return current

    def compare_and_set(
        self, expected: AttemptSequence, updated: AttemptSequence
    ) -> AttemptSequence:
        """Atomically replace the canonical value with a lineage extension.

        Same rules as the in-process store: `expected` must equal the stored
        value and `updated` must preserve the lineage. Equal updates are
        idempotent.
        """
        if (
            type(expected) is not AttemptSequence
            or type(updated) is not AttemptSequence
        ):
            raise ValueError(
                "canonical compare-and-set requires attempt sequences"
            )
        with self._locked():
            current = self._read()
            if current != expected:
                raise ValueError("canonical sequence compare failed")
            if updated != expected and not _is_lineage_extension(
                expected, updated
            ):
                raise ValueError(
                    "updated sequence does not extend the canonical lineage"
                )
            if updated != expected:
                self._write(updated)
            return updated if updated != expected else current

    def _read(self) -> AttemptSequence | None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return AttemptSequence.from_dict(json.loads(raw))

    def _write(self, sequence: AttemptSequence) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=self._path.name + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    sequence.to_dict(),
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
            # The rename needs a directory fsync to be durable: without
            # it a power loss can roll the entry back even though the
            # file content was fsynced, losing or reverting the
            # published lineage. Platforms that cannot fsync a
            # directory keep the file-level guarantee.
            try:
                dir_fd = os.open(self._path.parent, os.O_RDONLY)
            except OSError:
                dir_fd = None
            if dir_fd is not None:
                try:
                    # A filesystem that opens a directory can still
                    # refuse fsync on it (EINVAL/ENOTSUP/ENOSYS) — the
                    # rename already landed, so keep the file-level
                    # guarantee rather than fail a completed
                    # publication. A real I/O failure (EIO, EBADF, …)
                    # propagates: publication must not report durable
                    # success it did not get.
                    try:
                        os.fsync(dir_fd)
                    except OSError as e:
                        if e.errno not in (
                            errno.EINVAL,
                            errno.ENOTSUP,
                            errno.ENOSYS,
                        ):
                            raise
                finally:
                    os.close(dir_fd)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @contextmanager
    def _locked(self):
        with self._path_locks_guard:
            lock = self._path_locks.setdefault(
                str(self._lock_path.resolve()), threading.Lock()
            )
        with lock:
            try:
                import fcntl
            except ImportError:
                yield
                return
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock_path.open("a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class AttemptExecutionRequest:
    """Host-declared intent to run the described reserved attempt; not a spawn.

    This value only describes which record should be executed next. It does
    not start a process, authorize a tool, reserve resources, deliver the
    request to a runner or prove anything ran — dispatch and observation of
    the start remain host duties.
    """

    request_fingerprint: str
    attempt_number: int
    timeout_ms: int

    def __post_init__(self) -> None:
        _fingerprint(self.request_fingerprint)
        _counter(self.attempt_number, positive=True)
        _counter(self.timeout_ms, positive=True)

    def to_dict(self) -> dict:
        return {
            "schema_version": "mumei.verifier-attempt-execution/v1",
            "request_fingerprint": self.request_fingerprint,
            "attempt_number": self.attempt_number,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptExecutionRequest":
        """Rebuild a declared execution request; the constructor
        re-validates it. A foreign schema, unknown keys or malformed
        members are static errors."""
        if (
            type(data) is not dict
            or data.get("schema_version")
            != "mumei.verifier-attempt-execution/v1"
        ):
            raise ValueError(
                "execution request requires its declared record schema"
            )
        required = {"request_fingerprint", "attempt_number", "timeout_ms"}
        if set(data) != required | {"schema_version"}:
            raise ValueError(
                "execution request record has unknown or missing keys"
            )
        return cls(
            data["request_fingerprint"],
            data["attempt_number"],
            data["timeout_ms"],
        )


@dataclass(frozen=True)
class AttemptCancelRequest:
    """Host-declared intent to stop the described running attempt; not a kill.

    This value only describes which running record should be cancelled. It
    does not signal a process, confirm delivery, prove a stop or order itself
    against other requests — dispatch and stop observation remain host
    duties.
    """

    request_fingerprint: str
    attempt_number: int

    def __post_init__(self) -> None:
        _fingerprint(self.request_fingerprint)
        _counter(self.attempt_number, positive=True)

    def to_dict(self) -> dict:
        return {
            "schema_version": "mumei.verifier-attempt-cancel/v1",
            "request_fingerprint": self.request_fingerprint,
            "attempt_number": self.attempt_number,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptCancelRequest":
        """Rebuild a declared cancel request; the constructor
        re-validates it. A foreign schema, unknown keys or malformed
        members are static errors."""
        if (
            type(data) is not dict
            or data.get("schema_version")
            != "mumei.verifier-attempt-cancel/v1"
        ):
            raise ValueError(
                "cancel request requires its declared record schema"
            )
        required = {"request_fingerprint", "attempt_number"}
        if set(data) != required | {"schema_version"}:
            raise ValueError(
                "cancel request record has unknown or missing keys"
            )
        return cls(data["request_fingerprint"], data["attempt_number"])


@dataclass(frozen=True)
class AttemptEvidenceCandidate:
    """Detached handoff descriptor for a declared selected result; not Evidence.

    This value names which canonical snapshot a host proposes to submit for
    Core's normalization and acceptance check: a request fingerprint, the
    attempt ordinal and the output manifest fingerprint. It carries no bytes,
    makes no validity claim and grants no authority — hashing a manifest is
    not semantic correctness, and naming a candidate is not acceptance.
    """

    request_fingerprint: str
    attempt_number: int
    output_fingerprint: str

    def __post_init__(self) -> None:
        _fingerprint(self.request_fingerprint)
        _counter(self.attempt_number, positive=True)
        if type(self.output_fingerprint) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.output_fingerprint
        ):
            raise ValueError("invalid output fingerprint")

    def to_dict(self) -> dict:
        return {
            "schema_version": "mumei.verifier-evidence-candidate/v1",
            "request_fingerprint": self.request_fingerprint,
            "attempt_number": self.attempt_number,
            "output_fingerprint": self.output_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptEvidenceCandidate":
        """Rebuild a declared handoff descriptor; the constructor
        re-validates it.

        The descriptor is a host declaration: restoration re-checks the
        exact key set and schema, then the constructor re-checks every
        invariant. A foreign schema, unknown keys or malformed members
        are static errors — the value still carries no bytes and grants
        no authority."""
        if (
            type(data) is not dict
            or data.get("schema_version")
            != "mumei.verifier-evidence-candidate/v1"
        ):
            raise ValueError(
                "evidence candidate requires its declared record schema"
            )
        required = {
            "request_fingerprint",
            "attempt_number",
            "output_fingerprint",
        }
        if set(data) != required | {"schema_version"}:
            raise ValueError(
                "evidence candidate record has unknown or missing keys"
            )
        return cls(
            data["request_fingerprint"],
            data["attempt_number"],
            data["output_fingerprint"],
        )


@dataclass(frozen=True)
class AttemptEvidenceCheck:
    """Detached record of a declared representation-check outcome; not Evidence.

    Binds a host-declared check result to a handoff candidate: the request
    fingerprint, the attempt ordinal, the output manifest fingerprint and
    one declared `outcome` — `"valid"` (Core returned the known v1
    diagnostic for the delivered bytes), `"failed"` (the check produced
    no accepted diagnostic — an invalid representation, a malformed
    diagnostic and a spawn/I/O failure are indistinguishable by design)
    or `"cancelled"`.

    Recording is a host declaration, not acceptance: `"valid"` only means
    Core's representation check passed for the bytes the host delivered.
    The record carries no bytes, performs no check itself and asserts no
    truth, freshness, authenticity, correspondence or grade promotion —
    those remain unassessed host/Core duties.
    """

    request_fingerprint: str
    attempt_number: int
    output_fingerprint: str
    outcome: str

    def __post_init__(self) -> None:
        _fingerprint(self.request_fingerprint)
        _counter(self.attempt_number, positive=True)
        if type(self.output_fingerprint) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.output_fingerprint
        ):
            raise ValueError("invalid output fingerprint")
        if (
            type(self.outcome) is not str
            or self.outcome not in EVIDENCE_CHECK_OUTCOMES
        ):
            raise ValueError("invalid evidence check outcome")

    def to_dict(self) -> dict:
        return {
            "schema_version": "mumei.verifier-evidence-check/v1",
            "request_fingerprint": self.request_fingerprint,
            "attempt_number": self.attempt_number,
            "output_fingerprint": self.output_fingerprint,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptEvidenceCheck":
        """Rebuild a declared check record; the constructor re-validates it.

        The record is a host declaration: restoration re-checks the exact
        key set and schema, then the constructor re-checks every invariant
        (fingerprints, ordinal, declared outcome). A foreign schema,
        unknown keys or malformed members are static errors — the record
        still carries no bytes and asserts no acceptance."""
        if (
            type(data) is not dict
            or data.get("schema_version") != "mumei.verifier-evidence-check/v1"
        ):
            raise ValueError(
                "evidence check requires its declared record schema"
            )
        required = {
            "request_fingerprint",
            "attempt_number",
            "output_fingerprint",
            "outcome",
        }
        if set(data) != required | {"schema_version"}:
            raise ValueError(
                "evidence check record has unknown or missing keys"
            )
        return cls(
            data["request_fingerprint"],
            data["attempt_number"],
            data["output_fingerprint"],
            data["outcome"],
        )


@dataclass(frozen=True)
class AttemptNormalizedResult:
    """Detached normalization of one observed run; not a verdict or Evidence.

    Maps one observed terminal run into a stable detached shape — request
    binding, the terminal outcome, the observed elapsed counter and the
    bounded-output manifest — so hosts can consume every outcome uniformly
    without reading event histories or raw bytes. Normalization covers
    agent-side observations only: the stdout digest binds bytes, not
    meaning, an exit code is transport metadata, and `complete` records
    only that collection stayed within the bound. Acceptance, verdict
    interpretation and canonical publication remain host/Core duties.
    """

    request_fingerprint: str
    attempt_number: int
    timeout_ms: int
    outcome: str
    elapsed_ms: int
    exit_code: int | None
    stdout_size: int
    stdout_sha256: str
    complete: bool

    def __post_init__(self) -> None:
        _fingerprint(self.request_fingerprint)
        _counter(self.attempt_number, positive=True)
        _counter(self.timeout_ms, positive=True)
        if type(self.outcome) is not str or self.outcome not in TERMINAL_STATES:
            raise ValueError("attempt normalized result requires a terminal outcome")
        _counter(self.elapsed_ms)
        if self.outcome == "exited":
            if (
                type(self.exit_code) is not int
                or not -MAX_COUNTER - 1 <= self.exit_code <= MAX_COUNTER
            ):
                raise ValueError("normalized exit code requires a bounded integer")
        elif self.exit_code is not None:
            raise ValueError("only exited outcomes carry exit codes")
        _counter(self.stdout_size)
        if self.stdout_size > MAX_STDOUT_BYTES:
            raise ValueError("normalized stdout exceeds the byte bound")
        if type(self.stdout_sha256) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.stdout_sha256
        ):
            raise ValueError("invalid normalized stdout identity")
        if type(self.complete) is not bool:
            raise ValueError("invalid normalized completeness declaration")

    def to_dict(self) -> dict:
        manifest = {
            "schema_version": "mumei.verifier-run-result/v1",
            "request_fingerprint": self.request_fingerprint,
            "attempt_number": self.attempt_number,
            "timeout_ms": self.timeout_ms,
            "outcome": self.outcome,
            "elapsed_ms": self.elapsed_ms,
            "stdout": {
                "sha256": self.stdout_sha256,
                "size_bytes": self.stdout_size,
            },
        }
        if self.outcome == "exited":
            manifest["exit_code"] = self.exit_code
        if not self.complete:
            manifest["stdout"]["complete"] = False
        return manifest

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptNormalizedResult":
        """Rebuild a declared run-result record; the constructor
        re-validates it.

        The record is a host declaration: restoration re-checks the
        exact key set and schema — `exit_code` may appear only as the
        constructor allows (an `exited` outcome carries it, nothing
        else does), `stdout` holds exactly `sha256` + `size_bytes` plus
        an optional `complete: false`, and a foreign schema, unknown
        keys or malformed members are static errors."""
        if (
            type(data) is not dict
            or data.get("schema_version") != "mumei.verifier-run-result/v1"
        ):
            raise ValueError(
                "normalized result requires its declared record schema"
            )
        required = {
            "request_fingerprint",
            "attempt_number",
            "timeout_ms",
            "outcome",
            "elapsed_ms",
            "stdout",
        }
        if not required <= set(data) or not set(data) <= required | {
            "schema_version",
            "exit_code",
        }:
            raise ValueError(
                "normalized result record has unknown or missing keys"
            )
        if ("exit_code" in data) != (data.get("outcome") == "exited"):
            raise ValueError(
                "normalized result record carries exit_code only for"
                " exited outcomes"
            )
        stdout = data["stdout"]
        if (
            type(stdout) is not dict
            or not {"sha256", "size_bytes"} <= set(stdout)
            or not set(stdout) <= {"sha256", "size_bytes", "complete"}
        ):
            raise ValueError("normalized result record has malformed stdout")
        if "complete" in stdout and stdout["complete"] is not False:
            raise ValueError(
                "normalized result record carries an invalid completeness"
                " declaration"
            )
        return cls(
            data["request_fingerprint"],
            data["attempt_number"],
            data["timeout_ms"],
            data["outcome"],
            data["elapsed_ms"],
            data.get("exit_code"),
            stdout["size_bytes"],
            stdout["sha256"],
            stdout.get("complete", True),
        )


@dataclass(frozen=True)
class AttemptOutput:
    """Host-supplied stdout snapshot, not parsed Evidence or a success claim.

    Only repr/to_dict omit the body; explicit access to stdout exposes it.
    Hosts own stream limits, completeness, origin and canonical-record storage.
    `stream` names the declared stream the bytes came from and `complete`
    declares whether the capture is the whole stream; both are host claims,
    not proven observations — a declared `complete=True` does not establish
    completeness and `False` does not measure what was missed.
    """

    attempt: AttemptRecord
    stdout: bytes = field(repr=False)
    expected_stdout_sha256: str
    stream: str = "stdout"
    complete: bool = True

    def __post_init__(self) -> None:
        if type(self.attempt) is not AttemptRecord or self.attempt.state != "exited":
            raise ValueError("output requires an exited attempt record")
        if type(self.stdout) is not bytes or len(self.stdout) > MAX_STDOUT_BYTES:
            raise ValueError("stdout must be bounded immutable bytes")
        if type(self.expected_stdout_sha256) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.expected_stdout_sha256
        ):
            raise ValueError("invalid expected stdout identity")
        if hashlib.sha256(self.stdout).hexdigest() != self.expected_stdout_sha256:
            raise ValueError("stdout identity mismatch")
        if type(self.stream) is not str or self.stream not in STREAM_KINDS:
            raise ValueError("unsupported attempt output stream")
        if type(self.complete) is not bool:
            raise ValueError("invalid attempt output completeness declaration")

    @classmethod
    def from_prepared(
        cls,
        prepared: PreparedSourceRequest,
        attempt_number: int,
        report: AttemptRecord,
        stdout: bytes,
        expected_stdout_sha256: str,
        stream: str = "stdout",
        complete: bool = True,
    ) -> "AttemptOutput":
        bound = AttemptRecord.from_prepared(prepared, attempt_number).reconcile(report)
        return cls(bound, stdout, expected_stdout_sha256, stream, complete)

    def reconcile(self, incoming: "AttemptOutput") -> "AttemptOutput":
        """Keep one canonical snapshot; duplicates are idempotent, not fresh."""
        if type(incoming) is not AttemptOutput:
            raise ValueError("output reconciliation requires an output snapshot")
        if (
            self.attempt != incoming.attempt
            or self.stdout != incoming.stdout
            or self.stream != incoming.stream
            or self.complete != incoming.complete
        ):
            raise ValueError("attempt output report conflict")
        return self

    def decode_json_object(self) -> dict[str, object]:
        """Explicit private-body access, not a Core representation/acceptance gate.

        Return a fresh tree with exact int/Decimal numbers. Never log the tree or
        reserialize it as authoritative Evidence; Core must check original bytes.
        """
        payload = None
        try:
            text = self.stdout.decode("utf-8")
            _json_depth(text)
            payload = json.loads(
                text,
                object_pairs_hook=_json_pairs,
                parse_int=_json_integer,
                parse_float=_json_decimal,
                parse_constant=_json_constant,
            )
            pending = [payload]
            while pending:
                value = pending.pop()
                if type(value) is str:
                    value.encode("utf-8")
                elif type(value) is dict:
                    pending.extend(value.keys())
                    pending.extend(value.values())
                elif type(value) is list:
                    pending.extend(value)
        except (ValueError, UnicodeError, ArithmeticError, RecursionError):
            payload = None
        if type(payload) is not dict:
            raise ValueError("stdout is not a supported bounded JSON object")
        return payload

    def to_dict(self) -> dict:
        manifest = {
            "schema_version": "mumei.verifier-output/v1",
            "attempt": self.attempt.to_dict(),
            "stdout": {
                "sha256": self.expected_stdout_sha256,
                "size_bytes": len(self.stdout),
            },
        }
        if self.stream != "stdout":
            manifest["stdout"]["stream"] = self.stream
        if not self.complete:
            manifest["stdout"]["complete"] = False
        fingerprint = hashlib.sha256(
            json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
        return {**manifest, "output_fingerprint": fingerprint}
