"""Bounded host-reported attempt observations, not execution or Evidence.

Records cannot authorize a tool, prove observation freshness or establish that
a process was stopped. No default verification path consumes these records.
"""

import re
from dataclasses import dataclass, replace

from agent.verification_planner import PreparedSourceRequest

MAX_COUNTER = (1 << 63) - 1
MAX_EVENTS = 3
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
        if not isinstance(self.kind, str) or self.kind not in EVENT_KINDS:
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
        if not isinstance(self.request_fingerprint, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.request_fingerprint
        ):
            raise ValueError("invalid prepared request fingerprint")
        _counter(self.attempt_number, positive=True)
        _counter(self.timeout_ms, positive=True)
        if not isinstance(self.events, tuple) or len(self.events) > MAX_EVENTS:
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

    def to_dict(self) -> dict:
        return {
            "schema_version": "mumei.verifier-attempt/v1",
            "request_fingerprint": self.request_fingerprint,
            "attempt_number": self.attempt_number,
            "timeout_ms": self.timeout_ms,
            "state": self.state,
            "events": [event.to_dict() for event in self.events],
        }
