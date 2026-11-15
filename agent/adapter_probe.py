"""C11 declared availability probes.

The opt-in `agent.adapter_probe` module connects a **host-declared probe
command** to `AttemptRunner` and maps the observed terminal outcome to a
`RuntimeObservation` that `AdapterRegistry.plan()` consumes. This closes
the "actual probing" phrase of the C11 scope at the observation level:
the probe decides nothing — it only records what the declared command
was observed to do.

Declared outcome mapping (a convention, not a verdict):

- `exited` with exit code 0 → `availability="available"`
- `exited` with a nonzero code → `availability="missing"`
- `failed` (the spawn itself was refused — e.g. ENOENT) → `"missing"`
- `timed_out` / `cancelled` → `"unknown"`

Manifests may declare the probe command itself:
`AdapterDescriptor.probe_argv` is an optional immutable command parsed
from the `probe_argv` manifest key, and `probe_request_for(descriptor,
stamp)` binds it to the descriptor's declared `max_timeout_ms` /
`max_memory_mb` budgets — a manifest pins how much room its own probe
gets, and a descriptor without the declaration is a static error, never
a wildcard probe.

Boundary held honestly: a probe reports **observed command behavior**,
not tool health, availability proof, version truth or acceptance. The
command is host-declared, so a lying or wrong probe simply records a
lying observation — replay ordering across probes is the stamp's job and
the registry still treats observations as untrusted claims. No parsing
of stdout is performed (the normalized digest binds bytes, never
meaning), `tool_version` stays a host-declared field, and nothing here
authorizes, schedules, retries or accepts anything. Actual plugin
loading, adapter code execution beyond the declared probe, output
interpretation and Evidence acceptance remain open.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass

from agent.attempt_runner import (
    MAX_MEMORY_BOUND_MB,
    AttemptRunner,
)
from agent.verification_attempt import (
    AttemptExecutionRequest,
    AttemptNormalizedResult,
)
from agent.verification_planner import (
    MAX_STAMP,
    AdapterDescriptor,
    RuntimeObservation,
    _label,
    _positive,
    _version,
)

PROBE_SCHEMA = "mumei.verifier-adapter-probe/v1"


def _probe_fingerprint(
    adapter_id: str, argv: tuple[str, ...], stamp: int
) -> str:
    payload = json.dumps(
        {
            "schema_version": PROBE_SCHEMA,
            "adapter_id": adapter_id,
            "argv": list(argv),
            "stamp": stamp,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class AdapterProbeRequest:
    """Host-declared probe intent; running it is an observation, not a check.

    `argv` is the command whose terminal outcome maps to availability by
    the declared convention in the module docstring. `stamp` is the
    host-declared monotonic observation stamp the registry's replay
    detection consumes. `attempt_number` only binds the execution record;
    hosts own its uniqueness per fingerprint. `tool_version` is a
    host-declared claim echoed into the observation — the probe itself
    never parses the command's output for it.
    """

    adapter_id: str
    argv: tuple[str, ...]
    timeout_ms: int
    stamp: int
    attempt_number: int = 1
    memory_bound_mb: int | None = None
    tool_version: str | None = None

    def __post_init__(self) -> None:
        _label(self.adapter_id)
        if (
            type(self.argv) is not tuple
            or not self.argv
            or any(
                type(arg) is not str or not arg for arg in self.argv
            )
        ):
            raise ValueError(
                "adapter probe requires a nonempty immutable argv"
            )
        _positive(self.timeout_ms)
        if (
            type(self.stamp) is not int
            or not 1 <= self.stamp <= MAX_STAMP
        ):
            raise ValueError("invalid adapter probe stamp")
        if (
            type(self.attempt_number) is not int
            or not 1 <= self.attempt_number <= MAX_STAMP
        ):
            raise ValueError("invalid adapter probe attempt number")
        if self.memory_bound_mb is not None and (
            type(self.memory_bound_mb) is not int
            or not 1 <= self.memory_bound_mb <= MAX_MEMORY_BOUND_MB
        ):
            raise ValueError("invalid adapter probe memory bound")
        if self.tool_version is not None:
            _version(self.tool_version)

    def execution_request(self) -> AttemptExecutionRequest:
        """The attempt-binding descriptor for `AttemptRunner.run`."""
        return AttemptExecutionRequest(
            _probe_fingerprint(
                self.adapter_id, self.argv, self.stamp
            ),
            self.attempt_number,
            self.timeout_ms,
        )


@dataclass(frozen=True)
class AdapterProbeOutcome:
    """One observed probe: the registry-ready observation plus the run's
    detached normalization.

    `observation` is directly consumable by `AdapterRegistry.plan()`;
    `result` is the detached transport metadata of the run itself.
    """

    observation: RuntimeObservation
    result: AttemptNormalizedResult

    def to_dict(self) -> dict:
        return {
            "schema_version": PROBE_SCHEMA,
            "observation": {
                "adapter_id": self.observation.adapter_id,
                "availability": self.observation.availability,
                "stamp": self.observation.stamp,
                "tool_version": self.observation.tool_version,
            },
            "result": self.result.to_dict(),
        }


def _map_outcome(
    normalized: AttemptNormalizedResult,
) -> str:
    if normalized.outcome == "exited":
        return "available" if normalized.exit_code == 0 else "missing"
    if normalized.outcome == "failed":
        return "missing"
    return "unknown"


def run_probe(
    request: AdapterProbeRequest,
    *,
    runner: AttemptRunner | None = None,
    cancel_event: "threading.Event | None" = None,
) -> AdapterProbeOutcome:
    """Run one declared probe and return the observation.

    Effects are confined to `AttemptRunner.run`: one spawned child,
    bounded wait, optional declared memory ceiling and one optional
    cancellation event. The observation's `stamp` echoes the declared
    stamp so the registry's replay detection applies unchanged.
    """
    if type(request) is not AdapterProbeRequest:
        raise ValueError("probe requires an adapter probe request")
    if cancel_event is not None and type(cancel_event) is not threading.Event:
        raise ValueError("probe cancellation requires an event")
    if runner is None:
        runner = AttemptRunner()
    result = runner.run(
        request.execution_request(),
        request.argv,
        cancel_event=cancel_event,
        memory_bound_mb=request.memory_bound_mb,
    ).normalized()
    observation = RuntimeObservation(
        request.adapter_id,
        availability=_map_outcome(result),
        tool_version=request.tool_version,
        stamp=request.stamp,
    )
    return AdapterProbeOutcome(observation, result)


def probe_request_for(
    descriptor: AdapterDescriptor,
    stamp: int,
    *,
    attempt_number: int = 1,
    tool_version: str | None = None,
) -> AdapterProbeRequest:
    """Bind a manifest-declared probe command to its declared budgets.

    The descriptor's `probe_argv` becomes the request argv verbatim —
    it is host-declared text, never parsed or expanded. The request's
    `timeout_ms` and `memory_bound_mb` are the descriptor's declared
    `max_timeout_ms` / `max_memory_mb` budgets, so a manifest pins how
    much room its own probe gets. A descriptor without `probe_argv` is
    a static error (`probe command not declared`), not a wildcard probe.
    """
    if not isinstance(descriptor, AdapterDescriptor):
        raise ValueError("probe binding requires an adapter descriptor")
    if descriptor.probe_argv is None:
        raise ValueError("probe command not declared")
    return AdapterProbeRequest(
        descriptor.adapter_id,
        descriptor.probe_argv,
        timeout_ms=descriptor.max_timeout_ms,
        stamp=stamp,
        attempt_number=attempt_number,
        memory_bound_mb=descriptor.max_memory_mb,
        tool_version=tool_version,
    )
