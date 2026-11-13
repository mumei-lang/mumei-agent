"""Bounded host-reported attempts and opaque output, not execution or Evidence.

Records cannot authorize a tool, prove observation freshness or establish that
a process was stopped. No default verification path consumes these records.
"""

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field, replace
from decimal import Context, Decimal

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
TERMINAL_STATES = frozenset({"exited", "failed", "timed_out", "cancelled"})
_TRANSITIONS = {
    ("ready", "started"): "running",
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
    freshness proof or authentication.
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


@dataclass(frozen=True)
class AttemptOutput:
    """Host-supplied stdout snapshot, not parsed Evidence or a success claim.

    Only repr/to_dict omit the body; explicit access to stdout exposes it.
    Hosts own stream limits, completeness, origin and canonical-record storage.
    """

    attempt: AttemptRecord
    stdout: bytes = field(repr=False)
    expected_stdout_sha256: str

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

    @classmethod
    def from_prepared(
        cls,
        prepared: PreparedSourceRequest,
        attempt_number: int,
        report: AttemptRecord,
        stdout: bytes,
        expected_stdout_sha256: str,
    ) -> "AttemptOutput":
        bound = AttemptRecord.from_prepared(prepared, attempt_number).reconcile(report)
        return cls(bound, stdout, expected_stdout_sha256)

    def reconcile(self, incoming: "AttemptOutput") -> "AttemptOutput":
        """Keep one canonical snapshot; duplicates are idempotent, not fresh."""
        if type(incoming) is not AttemptOutput:
            raise ValueError("output reconciliation requires an output snapshot")
        if self.attempt != incoming.attempt or self.stdout != incoming.stdout:
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
        fingerprint = hashlib.sha256(
            json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
        return {**manifest, "output_fingerprint": fingerprint}
