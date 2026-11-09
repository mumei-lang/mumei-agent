"""Bounded host-reported attempts and opaque output, not execution or Evidence.

Records cannot authorize a tool, prove observation freshness or establish that
a process was stopped. No default verification path consumes these records.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from decimal import Context, Decimal

from agent.verification_planner import PreparedSourceRequest

MAX_COUNTER = (1 << 63) - 1
MAX_EVENTS = 3
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


def _json_depth(data: bytes) -> None:
    depth = 0
    quoted = escaped = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds transport bound")
        elif byte in (93, 125):
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
        if type(self.request_fingerprint) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.request_fingerprint
        ):
            raise ValueError("invalid prepared request fingerprint")
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
            _json_depth(self.stdout)
            payload = json.loads(
                self.stdout.decode("utf-8"),
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
