"""Bounded host-reported attempts and opaque output, not execution or Evidence.

Records cannot authorize a tool, prove observation freshness or establish that
a process was stopped. No default verification path consumes these records.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace

from agent.verification_planner import PreparedSourceRequest

MAX_COUNTER = (1 << 63) - 1
MAX_EVENTS = 3
MAX_STDOUT_BYTES = 64 * 1024
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
