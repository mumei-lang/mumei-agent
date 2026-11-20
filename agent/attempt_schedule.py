"""C11 declared attempt scheduling: bounded retry/fallback over planned routes.

`run_attempt_schedule` composes the declared boundaries without adding any
new authority: it plans through `AdapterRegistry.plan`, prepares a
`PreparedSourceRequest`, reserves and dispatches one attempt through
`dispatch_attempt`, and on a non-success terminal outcome re-plans through
`registry.replan` — the same runtime-fallback path a host would drive by
hand — bounded by a declared `max_attempts`.

The scheduler only records what it dispatched and observed: it does not
authorize adapters, prove tool health, normalize outputs or accept
Evidence, and `success` is a host-declared exit-code mapping, not a
verification verdict. A host-initiated `cancel_event` ends the schedule
instead of falling back — cancellation is a stop decision, not a failure
the policy may route around.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field

from agent.attempt_runner import (
    AttemptRunner,
    dispatch_attempt,
    memory_bound_enforceable,
)
from agent.core_evidence import (
    evaluate_evidence_check,
    record_evidence_acceptance,
    record_evidence_check,
    requirement_fingerprint,
)
from agent.verification_attempt import (
    AttemptEvidenceCheck,
    AttemptSequence,
)
from agent.verification_planner import (
    VERDICT_OUTCOMES,
    AdapterRegistry,
    PlannerPolicy,
    PreparedSourceRequest,
    RouteRequirements,
    RuntimeObservation,
    VerificationPlan,
)

MAX_SCHEDULE_ATTEMPTS = 8
SCHEDULE_SCHEMA_VERSION = "mumei.attempt-schedule/v1"
SCHEDULE_OUTCOMES = frozenset(
    {"selected", "exhausted", "not_schedulable", "fallback_denied", "cancelled"}
)
NOT_DISPATCHED = "not_dispatched"

_MAX_LABEL = 128


def _label(value: str) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_LABEL
        or not value.strip()
        or value != value.strip()
    ):
        raise ValueError("invalid schedule label")


def _plan_fingerprint(plan: VerificationPlan) -> str:
    return hashlib.sha256(
        json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ScheduledAttemptEntry:
    """One scheduled round: which adapter was tried and what terminal state
    the attempt reached — `not_dispatched` when the host declared no argv
    for the selected adapter, never a fabricated run."""

    ordinal: int
    adapter_id: str
    plan_fingerprint: str
    request_fingerprint: str | None
    terminal_state: str
    exit_code: int | None
    reported_outcome: str | None = None

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= MAX_SCHEDULE_ATTEMPTS:
            raise ValueError("invalid schedule entry ordinal")
        _label(self.adapter_id)
        if (
            type(self.plan_fingerprint) is not str
            or len(self.plan_fingerprint) != 64
            or self.plan_fingerprint != self.plan_fingerprint.lower()
        ):
            raise ValueError("invalid schedule entry plan fingerprint")
        if self.request_fingerprint is not None and (
            type(self.request_fingerprint) is not str
            or len(self.request_fingerprint) != 64
            or self.request_fingerprint != self.request_fingerprint.lower()
        ):
            raise ValueError("invalid schedule entry request fingerprint")
        if self.terminal_state not in {
            "exited",
            "failed",
            "timed_out",
            "cancelled",
            NOT_DISPATCHED,
        }:
            raise ValueError("invalid schedule entry terminal state")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise ValueError("invalid schedule entry exit code")
        if self.reported_outcome is not None and (
            type(self.reported_outcome) is not str
            or self.reported_outcome not in VERDICT_OUTCOMES
        ):
            raise ValueError("invalid schedule entry reported outcome")

    def to_dict(self) -> dict:
        return {
            "ordinal": self.ordinal,
            "adapter_id": self.adapter_id,
            "plan_fingerprint": self.plan_fingerprint,
            "request_fingerprint": self.request_fingerprint,
            "terminal_state": self.terminal_state,
            "exit_code": self.exit_code,
            "reported_outcome": self.reported_outcome,
        }


@dataclass(frozen=True)
class AttemptScheduleResult:
    """A bounded schedule record: the tried entries, the resulting plans and
    reconciled sequences, and the host-meaning outcome — `selected` only
    names which adapter produced a declared-success exit, never an
    Evidence acceptance."""

    entries: tuple[ScheduledAttemptEntry, ...]
    plans: tuple[VerificationPlan, ...]
    sequences: tuple[AttemptSequence, ...]
    selected_adapter_id: str | None
    outcome: str
    fallback_permitted: bool
    max_attempts: int
    evidence_check: AttemptEvidenceCheck | None = None
    evidence_acceptance: dict | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple) or not all(
            isinstance(entry, ScheduledAttemptEntry) for entry in self.entries
        ):
            raise ValueError("invalid schedule entries")
        if not isinstance(self.plans, tuple) or not all(
            isinstance(plan, VerificationPlan) for plan in self.plans
        ):
            raise ValueError("invalid schedule plans")
        if not isinstance(self.sequences, tuple) or not all(
            isinstance(sequence, AttemptSequence) for sequence in self.sequences
        ):
            raise ValueError("invalid schedule sequences")
        if self.selected_adapter_id is not None:
            _label(self.selected_adapter_id)
        if self.outcome not in SCHEDULE_OUTCOMES:
            raise ValueError("invalid schedule outcome")
        if self.outcome == "selected" and self.selected_adapter_id is None:
            raise ValueError("a selected schedule must name its adapter")
        if type(self.fallback_permitted) is not bool:
            raise ValueError("invalid schedule fallback declaration")
        if (
            type(self.max_attempts) is not int
            or not 1 <= self.max_attempts <= MAX_SCHEDULE_ATTEMPTS
        ):
            raise ValueError("invalid schedule attempt bound")
        if len(self.entries) > self.max_attempts:
            raise ValueError("schedule entries exceed the declared bound")
        if self.evidence_check is not None and (
            type(self.evidence_check) is not AttemptEvidenceCheck
            or self.outcome != "selected"
        ):
            raise ValueError("invalid schedule evidence check record")
        if self.evidence_acceptance is not None and (
            type(self.evidence_acceptance) is not dict
            or self.evidence_acceptance.get("schema_version")
            != "mumei.evidence-check-acceptance/v1"
        ):
            raise ValueError("invalid schedule evidence acceptance")
        if self.evidence_check is None and self.evidence_acceptance is not None:
            raise ValueError("schedule acceptance requires a check record")

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEDULE_SCHEMA_VERSION,
            "outcome": self.outcome,
            "selected_adapter_id": self.selected_adapter_id,
            "fallback_permitted": self.fallback_permitted,
            "max_attempts": self.max_attempts,
            "attempts": [entry.to_dict() for entry in self.entries],
            "evidence_check": (
                self.evidence_check.to_dict()
                if self.evidence_check is not None
                else None
            ),
            "evidence_acceptance": self.evidence_acceptance,
        }


def _fallback_permitted(policy: PlannerPolicy) -> bool:
    return policy.selected_adapter is None or policy.allow_fallback


def run_attempt_schedule(
    registry: AdapterRegistry,
    request: RouteRequirements,
    policy: PlannerPolicy,
    source: bytes,
    expected_source_sha256: str,
    argv_for,
    *,
    runner: "AttemptRunner | None" = None,
    observations: tuple[RuntimeObservation, ...] = (),
    max_attempts: int = MAX_SCHEDULE_ATTEMPTS,
    success_exit_codes: frozenset[int] = frozenset({0}),
    cancel_event: "threading.Event | None" = None,
    core_executable: str | None = None,
    core_requirement: str | None = None,
    memory_bound_mb: int | None = None,
    stdin_for=None,
) -> AttemptScheduleResult:
    """Plan → dispatch → observe → fall back, bounded by `max_attempts`.

    `argv_for(adapter_id)` is the host's declared argv lookup for the
    selected adapter; `None` means nothing declared — the round is recorded
    `not_dispatched` and the schedule falls back like a failed run.
    `success_exit_codes` is the host's declared exit mapping (default
    `{0}`): `exited` with any other code is a failure for scheduling, not
    a verdict. Fallback requires permissive routing (no explicit
    non-fallback selection); without it a failed attempt ends the schedule
    as `fallback_denied`.
    """
    if type(registry) is not AdapterRegistry:
        raise ValueError("attempt scheduling requires an adapter registry")
    if type(request) is not RouteRequirements:
        raise ValueError("attempt scheduling requires route requirements")
    if type(policy) is not PlannerPolicy:
        raise ValueError("attempt scheduling requires a planner policy")
    if type(source) is not bytes or not source:
        raise ValueError("attempt scheduling requires source bytes")
    if (
        type(expected_source_sha256) is not str
        or len(expected_source_sha256) != 64
        or expected_source_sha256 != expected_source_sha256.lower()
    ):
        raise ValueError("invalid expected source identity")
    if not callable(argv_for):
        raise ValueError("attempt scheduling requires an argv provider")
    if stdin_for is not None and not callable(stdin_for):
        raise ValueError("attempt scheduling stdin requires a provider")
    if runner is not None and type(runner) is not AttemptRunner:
        raise ValueError("attempt scheduling requires an attempt runner")
    if not isinstance(observations, tuple):
        raise ValueError("attempt scheduling requires immutable observations")
    if (
        type(max_attempts) is not int
        or not 1 <= max_attempts <= MAX_SCHEDULE_ATTEMPTS
    ):
        raise ValueError("invalid schedule attempt bound")
    if not isinstance(success_exit_codes, frozenset) or any(
        type(code) is not int for code in success_exit_codes
    ):
        raise ValueError("invalid schedule success declaration")
    if cancel_event is not None and type(cancel_event) is not threading.Event:
        raise ValueError("attempt schedule cancellation requires an event")
    if core_executable is not None and (
        type(core_executable) is not str or not core_executable
    ):
        raise ValueError("attempt schedule evidence check requires a core path")
    if core_requirement is not None and (
        type(core_requirement) is not str
        or not core_requirement
        or core_executable is None
    ):
        raise ValueError(
            "attempt schedule evidence acceptance requires a requirement path and a core"
        )
    active_runner = runner or AttemptRunner()

    entries: list[ScheduledAttemptEntry] = []
    plans: list[VerificationPlan] = []
    sequences: list[AttemptSequence] = []
    evidence_check: AttemptEvidenceCheck | None = None
    evidence_acceptance: dict | None = None
    excluded: list[str] = []
    current_observations = observations
    ordinal = 0
    outcome = "exhausted"
    selected_adapter_id: str | None = None

    plan = registry.plan(request, policy, current_observations)
    plans.append(plan)
    while True:
        if plan.selected is None:
            outcome = "exhausted" if entries else "not_schedulable"
            break
        adapter_id = plan.selected.adapter_id
        ordinal += 1
        if cancel_event is not None and cancel_event.is_set():
            # A host stop declared before the round: it must hold for a
            # `not_dispatched` round too, not just a spawned attempt.
            outcome = "cancelled"
            break
        prepared = PreparedSourceRequest(
            plan, source, expected_source_sha256
        )
        argv = argv_for(adapter_id)
        if argv is None:
            entries.append(
                ScheduledAttemptEntry(
                    ordinal,
                    adapter_id,
                    _plan_fingerprint(plan),
                    None,
                    NOT_DISPATCHED,
                    None,
                )
            )
            terminal = NOT_DISPATCHED
        else:
            sequence = AttemptSequence.from_prepared(prepared).begin_attempt()
            feed = stdin_for(adapter_id) if stdin_for is not None else None
            if feed is not None and type(feed) is not bytes:
                raise ValueError("attempt stdin must be bytes or absent")
            descriptor = registry.descriptor(adapter_id)
            dispatch = dispatch_attempt(
                sequence,
                argv,
                runner=active_runner,
                cancel_event=cancel_event,
                # The host's declared bound wins; otherwise the adapter's
                # own manifest ``max_memory_mb`` is the child's ceiling —
                # its declared budget, enforced as an observed outcome.
                # On a platform with no POSIX bound mechanism the manifest
                # fallback stays unenforced rather than breaking the run;
                # an explicit host bound still fails statically there.
                memory_bound_mb=(
                    memory_bound_mb
                    if memory_bound_mb is not None
                    else (
                        descriptor.max_memory_mb
                        if descriptor is not None
                        and memory_bound_enforceable()
                        else None
                    )
                ),
                # No declared feed means a closed pipe — a scheduled child
                # must never inherit the parent's stdin and block on it.
                feed_bytes=feed if feed is not None else b"",
            )
            sequences.append(dispatch.sequence)
            record = dispatch.run.record
            exit_code = record.events[-1].exit_code
            reported = None
            if descriptor is not None and record.state == "exited":
                # Declared interpretation: the adapter's own markers map
                # its raw output onto its declared outcome vocabulary —
                # a self-report, never Evidence acceptance.
                for marker in descriptor.verdict_markers:
                    blob = (
                        dispatch.run.stdout
                        if marker.stream == "stdout"
                        else dispatch.run.stderr
                    )
                    if marker.contains.encode("utf-8") in blob:
                        reported = marker.outcome
                        break
            entries.append(
                ScheduledAttemptEntry(
                    ordinal,
                    adapter_id,
                    _plan_fingerprint(plan),
                    prepared.to_dict()["request_fingerprint"],
                    record.state,
                    exit_code,
                    reported,
                )
            )
            terminal = record.state
            if cancel_event is not None and cancel_event.is_set():
                # A host-initiated cancellation is a stop decision — the
                # child may still report `exited` under the kill signal,
                # so check the event, not just the terminal state.
                outcome = "cancelled"
                break
            if terminal == "exited" and exit_code in success_exit_codes:
                outcome = "selected"
                selected_adapter_id = adapter_id
                if core_executable is not None:
                    # Same produce+consume pair as verify-attempt: select
                    # the captured bytes and run the declared Core check
                    # — the requirement-declared `evidence accept` when a
                    # requirement is declared, else the representation
                    # check — normalized into an acceptance descriptor.
                    selected = dispatch.sequence.select_result(
                        dispatch.captured_output()
                    )
                    sequences[-1] = selected
                    if core_requirement is not None:
                        evidence_check = record_evidence_acceptance(
                            selected,
                            dispatch.captured_output(),
                            core_executable=core_executable,
                            requirement_path=core_requirement,
                            timeout_ms=min(policy.timeout_ms, 60_000),
                            cancel_event=cancel_event,
                        )
                        evidence_acceptance = evaluate_evidence_check(
                            selected,
                            evidence_check,
                            requirement_fingerprint=requirement_fingerprint(
                                core_requirement
                            ),
                        )
                    else:
                        evidence_check = record_evidence_check(
                            selected,
                            dispatch.captured_output(),
                            core_executable=core_executable,
                            # The representation check is its own bounded
                            # call — capped like verify-attempt's check.
                            timeout_ms=min(policy.timeout_ms, 60_000),
                            cancel_event=cancel_event,
                        )
                        evidence_acceptance = evaluate_evidence_check(
                            selected, evidence_check
                        )
                break
            if terminal == "cancelled":
                outcome = "cancelled"
                break
        if ordinal >= max_attempts:
            outcome = "exhausted"
            break
        if not _fallback_permitted(policy):
            outcome = "fallback_denied"
            break
        excluded.append(adapter_id)
        # Reuse the caller's declarations: `replan(observations=None)`
        # replays only stamped records, which would drop unstamped
        # availability and strand every later candidate.
        plan = registry.replan(
            plans[-1], tuple(excluded), observations=current_observations or None
        )
        plans.append(plan)

    return AttemptScheduleResult(
        tuple(entries),
        tuple(plans),
        tuple(sequences),
        selected_adapter_id,
        outcome,
        _fallback_permitted(policy),
        max_attempts,
        evidence_check,
        evidence_acceptance,
    )
