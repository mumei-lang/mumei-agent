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

`plan_with_probes(registry, request, policy, observations, stamp=...)`
runs that loop for a bounded number of rounds (default 1, at most
`MAX_PLAN_ROUNDS`): plan, probe the observation-excluded candidates,
re-plan with the fresh observations — incrementing the stamp per round
so the registry's freshness check accepts them. It stops early on a
selection or an empty schedule, returns the final plan plus the new
observations, and never authorizes or accepts Evidence itself.

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

import concurrent.futures
import hashlib
import json
import re
import threading
from dataclasses import dataclass, replace

from agent.attempt_runner import (
    MAX_MEMORY_BOUND_MB,
    AttemptRunner,
    memory_bound_spawn_thread_safe,
)
from agent.verification_attempt import (
    AttemptCancelRequest,
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
    VerificationPlan,
    _label,
    _positive,
    _version,
)

PROBE_SCHEMA = "mumei.verifier-adapter-probe/v1"


def _probe_fingerprint(
    adapter_id: str,
    argv: tuple[str, ...],
    stamp: int,
    timeout_ms: int,
    memory_bound_mb: int | None,
) -> str:
    payload = json.dumps(
        {
            "schema_version": PROBE_SCHEMA,
            "adapter_id": adapter_id,
            "argv": list(argv),
            "stamp": stamp,
            "timeout_ms": timeout_ms,
            "memory_bound_mb": memory_bound_mb,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _command_fingerprint(
    adapter_id: str,
    argv: tuple[str, ...],
    timeout_ms: int,
    memory_bound_mb: int | None,
) -> str:
    """The probe command identity — request identity minus the stamp,
    so attempts at different observation stamps share one history."""
    payload = json.dumps(
        {
            "schema_version": PROBE_SCHEMA,
            "adapter_id": adapter_id,
            "argv": list(argv),
            "timeout_ms": timeout_ms,
            "memory_bound_mb": memory_bound_mb,
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

    def command_fingerprint(self) -> str:
        """The probe command identity: adapter, argv and declared
        budgets — everything `execution_request()` binds except the
        observation stamp, so retries at fresh stamps stay in one
        `AdapterProbeHistory`."""
        return _command_fingerprint(
            self.adapter_id,
            self.argv,
            self.timeout_ms,
            self.memory_bound_mb,
        )

    def execution_request(self) -> AttemptExecutionRequest:
        """The attempt-binding descriptor for `AttemptRunner.run`."""
        return AttemptExecutionRequest(
            _probe_fingerprint(
                self.adapter_id,
                self.argv,
                self.stamp,
                self.timeout_ms,
                self.memory_bound_mb,
            ),
            self.attempt_number,
            self.timeout_ms,
        )

    def cancel_request(self) -> AttemptCancelRequest:
        """The declared cancel descriptor for this probe attempt.

        Bound to the same fingerprint and attempt ordinal as
        `execution_request()` — the descriptor only names which
        running record a host proposes to stop; it never signals a
        process, confirms delivery or proves a stop.
        """
        execution = self.execution_request()
        return AttemptCancelRequest(
            execution.request_fingerprint,
            execution.attempt_number,
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

def _run_probe_batch(
    requests: tuple[AdapterProbeRequest, ...],
    *,
    runner: AttemptRunner,
    cancel_event: "threading.Event | None",
    max_parallel: int,
) -> tuple[AdapterProbeOutcome, ...]:
    """Execute probe requests, preserving order; returns full outcomes.

    The parallel path is only taken when no request declares a
    `memory_bound_mb` whose spawn would use `preexec_fn`: `preexec_fn`
    forces the fork+exec spawn path, which can deadlock in a
    multithreaded process. When `memory_bound_spawn_thread_safe()`
    reports that bounds go through a plain exec (`prlimit`, or a
    POSIX `sh`/`ulimit -v` wrapper), a memory-bound batch stays
    parallel-safe; only on a host with neither does it fall back to
    sequential execution rather than risk a spawn that can stall
    before timeout accounting starts.
    """
    memory_bound_serial = (
        any(req.memory_bound_mb is not None for req in requests)
        and not memory_bound_spawn_thread_safe()
    )
    if (
        max_parallel == 1
        or len(requests) <= 1
        or memory_bound_serial
    ):
        return tuple(
            run_probe(req, runner=runner, cancel_event=cancel_event)
            for req in requests
        )
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_parallel
    ) as pool:
        return tuple(
            pool.map(
                lambda req: run_probe(
                    req, runner=runner, cancel_event=cancel_event
                ),
                requests,
            )
        )


def observe_probes(
    requests: tuple[AdapterProbeRequest, ...],
    *,
    runner: AttemptRunner | None = None,
    cancel_event: "threading.Event | None" = None,
    max_parallel: int = 1,
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

    `max_parallel` bounds how many probes run at once. The runner
    keeps no state between calls, so sharing it across workers is
    safe; output order never depends on completion order —
    `observations[i]` always answers `requests[i]`. `max_parallel=1`
    is plain sequential execution.

    The parallel path is only skipped when a request declares a
    `memory_bound_mb` AND the runner would install it through a
    `preexec_fn` — `preexec_fn` forces the fork+exec spawn path,
    which can deadlock in a multithreaded process. With `prlimit` or
    a POSIX `sh` present the bound is applied by an exec wrapper
    instead (`ulimit -v` sets the same RLIMIT_AS), so memory-bound
    probes stay parallel-safe; only on a host with neither does such
    a batch fall back to sequential execution rather than risk a
    spawn that can stall before timeout accounting starts.
    """
    if not isinstance(requests, tuple):
        raise ValueError("probe observation requires a request tuple")
    if cancel_event is not None and type(cancel_event) is not threading.Event:
        raise ValueError("probe cancellation requires an event")
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) or max_parallel < 1:
        raise ValueError("probe parallelism bound must be a positive int")
    if runner is None:
        runner = AttemptRunner()
    outcomes = _run_probe_batch(
        requests,
        runner=runner,
        cancel_event=cancel_event,
        max_parallel=max_parallel,
    )
    return tuple(outcome.observation for outcome in outcomes)

# Bound on recorded probe attempts per adapter request — mirrors
# `MAX_ATTEMPTS` for attempt sequences: a history is replay
# evidence, not a retry scheduler, so it stays small.
MAX_PROBE_HISTORY = 8

# Terminal outcome vocabulary of `AttemptNormalizedResult` — the
# declared retry gate compares the last recorded outcome's kind
# against this set.
PROBE_OUTCOME_KINDS = frozenset(
    {"exited", "failed", "timed_out", "cancelled"}
)


def _check_retry_on(retry_on) -> None:
    """`retry_on` is a declared non-empty subset of the terminal
    outcome vocabulary; anything else is a static error, never a
    wildcard or a silently dropped gate."""
    if retry_on is None:
        return
    if (
        type(retry_on) is not frozenset
        or not retry_on
        or not retry_on <= PROBE_OUTCOME_KINDS
    ):
        raise ValueError("probe retry kinds out of vocabulary")


@dataclass(frozen=True)
class AdapterProbeHistory:
    """Bounded record of probe outcomes for one declared probe command.

    The history binds the command fingerprint — adapter id, argv and
    declared budgets — so attempts at different observation stamps
    accumulate in one record. `record()` re-derives that fingerprint
    from each new request, requires the outcome to bind the request's
    own execution fingerprint, and appends the next ordinal — a
    replayed, reordered or foreign outcome fails statically instead of
    contaminating the history. Each recorded outcome carries the
    observation stamp of the request that produced it: a record whose
    stamps regress — a replayed older observation — fails statically
    (equal stamps stay ordered by their attempt ordinals). This is
    replay evidence only: it says nothing about adapter health,
    authorizes nothing, and never retries.

    `stamps[i]` is the declared observation stamp of `outcomes[i]`;
    `None` marks a restored v1 record's undeclared stamp (a v1 record
    never claimed ordering). A `None` may only precede real stamps —
    ordering evidence once declared cannot be undeclared later.
    """

    adapter_id: str
    command_fingerprint: str
    outcomes: tuple[AttemptNormalizedResult, ...] = ()
    stamps: tuple[int | None, ...] = ()

    def __post_init__(self) -> None:
        _label(self.adapter_id)
        if type(self.command_fingerprint) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.command_fingerprint
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
        # Direct construction validates ordinals; the outcome-to-request
        # binding itself is only checkable against a presented request,
        # which `record()` enforces.
        for i, o in enumerate(self.outcomes):
            if o.attempt_number != i + 1:
                raise ValueError("probe history attempt ordinal mismatch")
        if (
            type(self.stamps) is not tuple
            or len(self.stamps) != len(self.outcomes)
            or any(
                s is not None
                and (type(s) is not int or not 1 <= s <= MAX_STAMP)
                for s in self.stamps
            )
        ):
            raise ValueError("probe history requires parallel stamps")
        declared = [s for s in self.stamps if s is not None]
        # `None` (a v1-restored undeclared stamp) may only form a
        # prefix: the first declared stamp must sit exactly after it.
        if declared and self.stamps.index(declared[0]) != len(
            self.stamps
        ) - len(declared):
            raise ValueError("probe history stamp ordering violation")
        if any(b < a for a, b in zip(declared, declared[1:])):
            raise ValueError("probe history stamp ordering violation")

    @classmethod
    def start(cls, request: "AdapterProbeRequest") -> "AdapterProbeHistory":
        """Bind a history to a declared probe command's fingerprint."""
        if type(request) is not AdapterProbeRequest:
            raise ValueError("probe history requires a probe request")
        return cls(request.adapter_id, request.command_fingerprint())

    @property
    def attempt_count(self) -> int:
        return len(self.outcomes)

    def record(
        self,
        request: "AdapterProbeRequest",
        outcome: AdapterProbeOutcome,
    ) -> "AdapterProbeHistory":
        """Append an observed outcome; the request must re-derive the
        bound fingerprint and the outcome must be the request's own.
        The request's stamp must not regress below the last declared
        stamp — a replayed older observation fails statically; a
        `None` tail (a v1-restored record) carries no declared stamp
        to compare."""
        if type(request) is not AdapterProbeRequest:
            raise ValueError("probe history requires a probe request")
        if request.adapter_id != self.adapter_id:
            raise ValueError("probe history adapter mismatch")
        if request.command_fingerprint() != self.command_fingerprint:
            raise ValueError("probe history fingerprint mismatch")
        if type(outcome) is not AdapterProbeOutcome:
            raise ValueError("probe history requires a probe outcome")
        result = outcome.result
        if (
            result.request_fingerprint
            != request.execution_request().request_fingerprint
            or result.attempt_number != request.attempt_number
        ):
            raise ValueError("probe history outcome does not match request")
        if result.attempt_number != len(self.outcomes) + 1:
            raise ValueError("probe history attempt ordinal mismatch")
        if len(self.outcomes) >= MAX_PROBE_HISTORY:
            raise ValueError("probe history attempt bound reached")
        last = next(
            (s for s in reversed(self.stamps) if s is not None),
            None,
        )
        if last is not None and request.stamp < last:
            raise ValueError("probe history stamp ordering violation")
        return AdapterProbeHistory(
            self.adapter_id,
            self.command_fingerprint,
            self.outcomes + (result,),
            self.stamps + (request.stamp,),
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": "mumei.adapter-probe-history/v2",
            "adapter_id": self.adapter_id,
            "command_fingerprint": self.command_fingerprint,
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "stamps": list(self.stamps),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AdapterProbeHistory":
        """Rebuild a declared probe-history record; the constructor
        re-validates it.

        Both record schemas restore: v1 carries no `stamps` key, so
        each outcome restores with `None` — the record never declared
        their ordering. v2 carries `stamps` parallel to `outcomes`,
        each entry a declared stamp or `null`; the constructor
        re-checks that no real stamp follows a `None` and that the
        declared run is strictly increasing, so a reordered record
        never restores. Foreign schemas, unknown keys or malformed
        members are static errors."""
        if (
            type(data) is not dict
            or type(data.get("schema_version")) is not str
            or data["schema_version"]
            not in {
                "mumei.adapter-probe-history/v1",
                "mumei.adapter-probe-history/v2",
            }
        ):
            raise ValueError(
                "probe history requires its declared record schema"
            )
        required = {
            "adapter_id",
            "command_fingerprint",
            "outcomes",
        }
        if data["schema_version"] == "mumei.adapter-probe-history/v2":
            required = required | {"stamps"}
        if not required <= set(data) or not set(data) <= required | {
            "schema_version",
        }:
            raise ValueError(
                "probe history record has unknown or missing keys"
            )
        outcomes = data["outcomes"]
        if type(outcomes) is not list:
            raise ValueError("probe history record has malformed outcomes")
        stamps = data.get("stamps")
        if data["schema_version"] == "mumei.adapter-probe-history/v2":
            if type(stamps) is not list:
                raise ValueError(
                    "probe history record has malformed stamps"
                )
        elif stamps is not None:
            raise ValueError(
                "probe history record has malformed stamps"
            )
        return cls(
            data["adapter_id"],
            data["command_fingerprint"],
            tuple(
                AttemptNormalizedResult.from_dict(outcome)
                for outcome in outcomes
            ),
            (
                tuple(stamps)
                if stamps is not None
                else (None,) * len(outcomes)
            ),
        )

# Bound on observe → re-plan iterations inside `plan_with_probes` —
# each round re-probes the same observation-excluded set, so a
# bound keeps a perpetually-missing adapter from probing forever.
MAX_PLAN_ROUNDS = 4


@dataclass(frozen=True)
class AdapterProbePlan:
    """Result of a bounded probe-driven planning pass."""

    plan: VerificationPlan
    observations: tuple[RuntimeObservation, ...]
    histories: tuple["AdapterProbeHistory", ...] = ()


def plan_with_probes(
    registry: AdapterRegistry,
    request: RouteRequirements,
    policy: PlannerPolicy,
    observations: tuple[RuntimeObservation, ...] = (),
    *,
    stamp: int,
    tool_version: str | None = None,
    runner: AttemptRunner | None = None,
    cancel_event: "threading.Event | None" = None,
    rounds: int = 1,
    max_parallel: int = 1,
    histories: tuple["AdapterProbeHistory", ...] = (),
    max_attempts: int = MAX_PROBE_HISTORY,
    retry_on: "frozenset[str] | None" = None,
) -> AdapterProbePlan:
    """Plan, probe the observation-excluded candidates, re-plan.

    One round is: `plan()` → `probe_retry_requests` → run the
    requests → feed every observation back in. Each attempt's
    stamp is `stamp` plus the adapter's recorded attempt count,
    so the registry's freshness check accepts each new
    observation and stamps stay inside the caller's allocation.
    `rounds` (1..MAX_PLAN_ROUNDS) bounds the loop:
    more than one round only re-probes adapters still excluded by
    observation — a probe that timed out may deserve one retry, a
    structurally excluded adapter is never re-asked. `max_parallel`
    bounds concurrency inside one round; rounds still run one
    after another. The driver stops early when a candidate is
    selected or a round emits no requests.

    `histories` carries prior per-adapter `AdapterProbeHistory`
    records: each round's requests are scheduled by
    `probe_retry_requests`, so an adapter's attempt number advances
    with its recorded history and is skipped once `max_attempts`
    (bounded by MAX_PROBE_HISTORY) is reached. Every observed
    outcome is appended to the adapter's history, and the updated
    histories come back on the returned `AdapterProbePlan` for the
    caller to persist or chain. `retry_on` is the declared retry
    gate passed to `probe_retry_requests` each round — an adapter
    whose last outcome kind is outside the set stops being
    re-asked.

    The caller owns `stamp` allocation: pass a base stamp that is
    fresh for every adapter, then keep the returned observations to
    chain further planning. Nothing here authorizes or accepts
    Evidence — the loop only schedules and observes declared probes.
    """
    if not isinstance(registry, AdapterRegistry):
        raise ValueError("probe planning requires a registry")
    if not isinstance(request, RouteRequirements):
        raise ValueError("probe planning requires a route request")
    if not isinstance(policy, PlannerPolicy):
        raise ValueError("probe planning requires a policy")
    if type(stamp) is not int or not 1 <= stamp <= MAX_STAMP:
        raise ValueError("invalid probe planning stamp")
    if not isinstance(rounds, int) or not 1 <= rounds <= MAX_PLAN_ROUNDS:
        raise ValueError("probe planning rounds out of bounds")
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) or max_parallel < 1:
        raise ValueError("probe parallelism bound must be a positive int")
    if type(histories) is not tuple or any(
        type(h) is not AdapterProbeHistory for h in histories
    ):
        raise ValueError("probe planning requires probe histories")
    if type(max_attempts) is not int or not (
        1 <= max_attempts <= MAX_PROBE_HISTORY
    ):
        raise ValueError("probe planning attempt bound out of range")
    _check_retry_on(retry_on)
    if runner is None:
        runner = AttemptRunner()
    # Latest observation per adapter — the result must be
    # chainable back into `plan()`, which rejects duplicate ids.
    seen: dict[str, RuntimeObservation] = {}
    by_hist: dict[str, AdapterProbeHistory] = {}
    for h in histories:
        if h.adapter_id in by_hist:
            raise ValueError("duplicate probe history")
        by_hist[h.adapter_id] = h
    observed = tuple(observations)
    plan = registry.plan(request, policy, observed)
    for _ in range(rounds):
        if plan.selected is not None:
            break
        reqs = probe_retry_requests(
            registry,
            request,
            policy,
            observed,
            histories=tuple(by_hist.values()),
            stamp=stamp,
            max_attempts=max_attempts,
            tool_version=tool_version,
            retry_on=retry_on,
        )
        if not reqs:
            break
        outcomes = _run_probe_batch(
            reqs,
            runner=runner,
            cancel_event=cancel_event,
            max_parallel=max_parallel,
        )
        by_id = {o.adapter_id: o for o in observed}
        for req, outcome in zip(reqs, outcomes):
            o = outcome.observation
            # A re-probed adapter replaces its prior observation —
            # `plan()` rejects duplicate adapter ids, and the
            # freshest stamped observation is the one that counts.
            seen[o.adapter_id] = o
            by_id[o.adapter_id] = o
            hist = by_hist.get(req.adapter_id)
            by_hist[req.adapter_id] = (
                AdapterProbeHistory.start(req).record(req, outcome)
                if hist is None
                else hist.record(req, outcome)
            )
        observed = tuple(by_id.values())
        plan = registry.plan(request, policy, observed)
    return AdapterProbePlan(
        plan, tuple(seen.values()), tuple(by_hist.values())
    )


def probe_retry_requests(
    registry: AdapterRegistry,
    request: RouteRequirements,
    policy: PlannerPolicy,
    observations: tuple[RuntimeObservation, ...] = (),
    histories: tuple[AdapterProbeHistory, ...] = (),
    *,
    stamp: int,
    max_attempts: int = MAX_PROBE_HISTORY,
    tool_version: str | None = None,
    retry_on: "frozenset[str] | None" = None,
) -> tuple[AdapterProbeRequest, ...]:
    """Retry scheduling for declared probes, bounded by history.

    Emits the next attempt for every still-excluded declared
    candidate: an adapter with no recorded history starts at
    attempt 1; otherwise its request carries
    `attempt_number = attempt_count + 1` and the adapter is skipped
    once the history reaches `max_attempts`. A history whose
    fingerprint does not re-derive from the scheduled request —
    changed argv or stamp — fails statically: stale evidence must
    not silently authorize another attempt.

    A retry is a NEW declared request: the emitted stamp advances by
    the recorded attempt count, so the superseding observation reads
    as fresh to the registry's replay detection (a same-stamp changed
    claim would be a conflict, and the registry never forgets one).
    The history binds the probe COMMAND — adapter, argv and budgets —
    not the stamp, so attempts across stamps stay in one record.

    `retry_on` is the declared retry gate: when given, an adapter
    whose last recorded outcome kind is not in the set is skipped
    — `retry_on=frozenset({"timed_out"})` re-asks a timed-out
    probe but never one whose spawn `failed`. First attempts are
    unaffected (no outcome exists to gate on), and `None` keeps
    the unfiltered behavior.

    Scheduling stays declarative: this runs nothing, never invents
    a candidate the observation rules did not exclude, and retries
    only inside the declared bound and gate. Concurrency and
    Evidence acceptance remain open.
    """
    if type(max_attempts) is not int or not (
        1 <= max_attempts <= MAX_PROBE_HISTORY
    ):
        raise ValueError("probe retry bound out of range")
    if type(histories) is not tuple or any(
        type(h) is not AdapterProbeHistory for h in histories
    ):
        raise ValueError("probe retries require probe histories")
    _check_retry_on(retry_on)
    by_id: dict[str, AdapterProbeHistory] = {}
    for h in histories:
        if h.adapter_id in by_id:
            raise ValueError("duplicate probe history")
        by_id[h.adapter_id] = h
    first = probe_requests_for(
        registry,
        request,
        policy,
        observations,
        stamp=stamp,
        attempt_number=1,
        tool_version=tool_version,
    )
    out: list[AdapterProbeRequest] = []
    for req in first:
        hist = by_id.get(req.adapter_id)
        if hist is None:
            out.append(req)
            continue
        if hist.command_fingerprint != req.command_fingerprint():
            raise ValueError("probe retry history fingerprint mismatch")
        if hist.attempt_count >= max_attempts:
            continue
        if (
            retry_on is not None
            and hist.outcomes
            and hist.outcomes[-1].outcome not in retry_on
        ):
            # The last observed outcome's kind is not one the
            # declared policy re-requests — the adapter stays
            # excluded and is never re-asked.
            continue
        out.append(
            replace(
                req,
                attempt_number=hist.attempt_count + 1,
                stamp=stamp + hist.attempt_count,
            )
        )
    return tuple(out)


def evaluate_probe_acceptance(
    request: AdapterProbeRequest,
    outcome: AdapterProbeOutcome,
) -> dict:
    """Normalize a declared probe outcome into an acceptance descriptor.

    Emits ``mumei.probe-acceptance/v1``: `request_match` holds only
    when the outcome binds the presented request — the same binding
    `AdapterProbeHistory.record` enforces — so a stale (older-attempt)
    or foreign outcome never counts. `accepted` holds only when the
    outcome is current AND mapped decisive: an `exited`/`failed`
    probe answers `available`/`missing`, while a `timed_out` or
    `cancelled` one answers `unknown` — an inconclusive attempt that
    accepts nothing.

    An outcome whose observation disagrees with its own result's
    declared mapping — e.g. `available` over a `timed_out` run —
    fails statically rather than accepting an inconclusive attempt.

    This is declaration-level acceptance, not Evidence: the
    descriptor lists every semantic check left unassessed in
    `checks_not_performed` (stdout interpretation, tool-version
    truth, availability semantics beyond the exit-code convention,
    freshness beyond the declared stamp, producer authenticity).
    Nothing here is a verdict, an adapter-health claim or a routing
    authority — `plan()` consumes observations unchanged.
    """
    if (
        type(request) is not AdapterProbeRequest
        or type(outcome) is not AdapterProbeOutcome
    ):
        raise ValueError("unsupported probe acceptance evaluation")
    if outcome.observation.adapter_id != request.adapter_id:
        raise ValueError("probe acceptance adapter mismatch")
    result = outcome.result
    if outcome.observation.availability != _map_outcome(result):
        # The declaration is internally inconsistent — an outcome
        # claiming `available` over a `timed_out` result must fail
        # statically, not accept an inconclusive attempt.
        raise ValueError("inconsistent probe outcome")
    match = (
        result.request_fingerprint
        == request.execution_request().request_fingerprint
        and result.attempt_number == request.attempt_number
    )
    availability = outcome.observation.availability
    return {
        "schema_version": "mumei.probe-acceptance/v1",
        "adapter_id": request.adapter_id,
        "request_fingerprint": result.request_fingerprint,
        "attempt_number": result.attempt_number,
        "outcome": result.outcome,
        "availability": availability,
        "request_match": match,
        "accepted": match and availability != "unknown",
        "checks_not_performed": [
            "stdout_interpretation",
            "tool_version_truth",
            "availability_semantics",
            "freshness",
            "producer_authenticity",
        ],
    }


def evaluate_probe_history(
    history: AdapterProbeHistory,
) -> dict:
    """Fold a declared probe history into an evaluation descriptor.

    Emits ``mumei.probe-history-evaluation/v1``. The record itself
    carries the binding — every recorded outcome already bound its
    request's execution fingerprint and ordinal at `record()` time
    — so the fold needs no presented request: a history is
    evaluated for the command it recorded, never against a
    candidate it did not answer.

    The descriptor reports what the record proves:
    `outcome_count`/`latest_attempt`/`latest_kind`,
    `latest_availability` re-derived from the last result through
    the same mapping `evaluate_probe_acceptance` uses, `ordered`
    (the declared stamps never regress — enforced by construction
    for a validated history, reported here so the check is visible
    rather than assumed), and `decisive` (the latest outcome
    answers `available`/`missing` rather than `unknown`).

    An empty history evaluates honestly (`outcome_count` 0, no
    latest kind or availability, `decisive` false). Acceptance is
    not emitted at history level — it belongs to a single outcome
    bound to a presented request (`evaluate_probe_acceptance`).

    This is declaration-level evaluation, not Evidence: the
    descriptor lists every check left unassessed in
    `checks_not_performed` (freshness beyond the last stamp,
    cross-adapter ordering, stdout interpretation, tool-version
    truth, availability semantics, producer authenticity, Evidence
    acceptance). Nothing here is a verdict, an adapter-health
    claim or a routing authority.
    """
    if type(history) is not AdapterProbeHistory:
        raise ValueError("unsupported probe history evaluation")
    latest = history.outcomes[-1] if history.outcomes else None
    declared = [s for s in history.stamps if s is not None]
    ordered = all(b >= a for a, b in zip(declared, declared[1:]))
    return {
        "schema_version": "mumei.probe-history-evaluation/v1",
        "adapter_id": history.adapter_id,
        "command_fingerprint": history.command_fingerprint,
        "outcome_count": len(history.outcomes),
        "latest_attempt": latest.attempt_number if latest else 0,
        "latest_kind": latest.outcome if latest else None,
        "latest_availability": (
            _map_outcome(latest) if latest is not None else None
        ),
        "ordered": ordered,
        "decisive": (
            latest is not None
            and latest.outcome in {"exited", "failed"}
        ),
        "checks_not_performed": [
            "freshness_beyond_last_stamp",
            "cross_adapter_ordering",
            "stdout_interpretation",
            "tool_version_truth",
            "availability_semantics",
            "producer_authenticity",
            "evidence_acceptance",
        ],
    }
