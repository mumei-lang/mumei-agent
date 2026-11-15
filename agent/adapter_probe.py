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

For scheduling, `probe_requests_for(registry, request, policy,
observations, stamp=...)` runs `plan()` and emits a request for each
candidate excluded **only** by observation-level reasons
(`availability_unknown`, `tool_missing`, `tool_version_unknown`,
`tool_version_mismatch`) that declares `probe_argv` — adapters excluded
structurally are never probed, since no probe fixes an unsupported
method or a denied location.

`observe_probes(requests, runner=..., cancel_event=...)` executes a
scheduled request tuple through one shared runner and returns the
observations in request order — the caller feeds them back into
`plan()` to close the observe → re-plan loop. Normalized results stay
inside `run_probe`; only availability/stamp/version cross the boundary.

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
import re
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
    AdapterRegistry,
    PlannerPolicy,
    RouteRequirements,
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


_OBSERVATION_REASONS = frozenset(
    {
        "availability_unknown",
        "tool_missing",
        "tool_version_unknown",
        "tool_version_mismatch",
    }
)


def probe_requests_for(
    registry: AdapterRegistry,
    request: RouteRequirements,
    policy: PlannerPolicy,
    observations: tuple[RuntimeObservation, ...] = (),
    *,
    stamp: int,
    attempt_number: int = 1,
    tool_version: str | None = None,
) -> tuple[AdapterProbeRequest, ...]:
    """Declared probes for candidates excluded by observation alone.

    Runs `plan()` and returns a `AdapterProbeRequest` for every decision
    whose exclusion reasons are all observation-level
    (`availability_unknown`, `tool_missing`, `tool_version_unknown`,
    `tool_version_mismatch`) and whose descriptor declares `probe_argv`.
    Adapters excluded for any structural reason are not probed — a probe
    cannot fix an unsupported method or a denied location. The shared
    `stamp` is per-request safe: registry stamps are per adapter id.
    """
    if not isinstance(registry, AdapterRegistry):
        raise ValueError("probe scheduling requires a registry")
    if not isinstance(request, RouteRequirements):
        raise ValueError("probe scheduling requires a route request")
    if not isinstance(policy, PlannerPolicy):
        raise ValueError("probe scheduling requires a policy")
    plan = registry.plan(request, policy, observations)
    selected_id = (
        plan.selected.adapter_id if plan.selected is not None else None
    )
    out: list[AdapterProbeRequest] = []
    for decision in plan.decisions:
        if decision.adapter_id == selected_id:
            continue
        reasons = frozenset(decision.reasons)
        if not reasons or not reasons <= _OBSERVATION_REASONS:
            continue
        descriptor = registry.descriptor(decision.adapter_id)
        if descriptor is None or descriptor.probe_argv is None:
            continue
        out.append(
            probe_request_for(
                descriptor,
                stamp,
                attempt_number=attempt_number,
                tool_version=tool_version,
            )
        )
    return tuple(out)

def observe_probes(
    requests: tuple[AdapterProbeRequest, ...],
    *,
    runner: AttemptRunner | None = None,
    cancel_event: "threading.Event | None" = None,
) -> tuple[RuntimeObservation, ...]:
    """Execute probe requests and return their observations.

    One shared runner serves every request (the runner is an
    execution surface, not a per-attempt resource). The returned
    observations preserve request order and are ready to hand back
    to `registry.plan(..., observations)` or the next
    `probe_requests_for` round — feeding them through the caller
    is what closes the observe → re-plan loop; this helper never
    plans itself. Normalized attempt results stay inside
    `run_probe`: only availability/stamp/version cross the
    boundary, so a probe's stdout or exit detail cannot leak into
    a routing decision.
    """
    if not isinstance(requests, tuple):
        raise ValueError("probe observation requires a request tuple")
    if cancel_event is not None and type(cancel_event) is not threading.Event:
        raise ValueError("probe cancellation requires an event")
    if runner is None:
        runner = AttemptRunner()
    out: list[RuntimeObservation] = []
    for req in requests:
        outcome = run_probe(req, runner=runner, cancel_event=cancel_event)
        out.append(outcome.observation)
    return tuple(out)

# Bound on recorded probe attempts per adapter request — mirrors
# `MAX_ATTEMPTS` for attempt sequences: a history is replay
# evidence, not a retry scheduler, so it stays small.
MAX_PROBE_HISTORY = 8


@dataclass(frozen=True)
class AdapterProbeHistory:
    """Bounded record of probe outcomes for one declared request.

    Every entry must bind the same request fingerprint, and each
    `record()` call appends the next ordinal — a replayed, reordered
    or foreign outcome fails statically instead of contaminating the
    history. This is replay evidence only: it says nothing about
    adapter health, authorizes nothing, and never retries.
    """

    adapter_id: str
    request_fingerprint: str
    outcomes: tuple[AttemptNormalizedResult, ...] = ()

    def __post_init__(self) -> None:
        _label(self.adapter_id)
        if type(self.request_fingerprint) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.request_fingerprint
        ):
            raise ValueError("invalid probe history fingerprint")
        if (
            type(self.outcomes) is not tuple
            or len(self.outcomes) > MAX_PROBE_HISTORY
            or any(
                type(o) is not AttemptNormalizedResult
                for o in self.outcomes
            )
        ):
            raise ValueError("probe history requires bounded results")

    @classmethod
    def start(cls, request: "AdapterProbeRequest") -> "AdapterProbeHistory":
        """Bind a history to a declared probe request's fingerprint."""
        if type(request) is not AdapterProbeRequest:
            raise ValueError("probe history requires a probe request")
        return cls(request.adapter_id, request.execution_request().request_fingerprint)

    @property
    def attempt_count(self) -> int:
        return len(self.outcomes)

    def record(
        self,
        request: "AdapterProbeRequest",
        outcome: AdapterProbeOutcome,
    ) -> "AdapterProbeHistory":
        """Append an observed outcome; the request must re-derive the
        bound fingerprint and the outcome must be the request's own."""
        if type(request) is not AdapterProbeRequest:
            raise ValueError("probe history requires a probe request")
        if request.adapter_id != self.adapter_id:
            raise ValueError("probe history adapter mismatch")
        if (
            request.execution_request().request_fingerprint
            != self.request_fingerprint
        ):
            raise ValueError("probe history fingerprint mismatch")
        if type(outcome) is not AdapterProbeOutcome:
            raise ValueError("probe history requires a probe outcome")
        result = outcome.result
        if (
            result.request_fingerprint != self.request_fingerprint
            or result.attempt_number != request.attempt_number
        ):
            raise ValueError("probe history outcome does not match request")
        if result.attempt_number != len(self.outcomes) + 1:
            raise ValueError("probe history attempt ordinal mismatch")
        if len(self.outcomes) >= MAX_PROBE_HISTORY:
            raise ValueError("probe history attempt bound reached")
        return AdapterProbeHistory(
            self.adapter_id,
            self.request_fingerprint,
            self.outcomes + (result,),
        )
