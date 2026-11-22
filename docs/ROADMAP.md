# mumei-agent Roadmap (2026-03 〜)

> mumei-agent の次期ロードマップ。mumei の思想（proof-first / AI生成コード → 検証済み資産への変換）に沿って優先度を設定。
>
> 全体のクロスプロジェクトロードマップは [mumei-lang/mumei の docs/CROSS_PROJECT_ROADMAP.md](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) を参照。

## Verification-Native planner and analysis program

Follow the [canonical implementation order](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md#verification-native-program-ordered-implementation)
and [shared architecture contract](https://github.com/mumei-lang/mumei/blob/develop/docs/VERIFICATION_NATIVE.md).
The Agent orchestrates verification; it does not define independent proof
grades or make a backend self-report sufficient for acceptance.

- [C04 planner](https://github.com/mumei-lang/mumei-agent/issues/649) and
  [C11 plugin contract](https://github.com/mumei-lang/mumei-agent/issues/653):
  users can register, select, configure, disable and replace adapters without
  changing planner core. Capabilities, compatibility, budgets, selection and
  exclusion reasons, effective non-secret settings and explicit fallback
  policy are required. Test with existing paths and synthetic adapters first.
- [C05 CFG](https://github.com/mumei-lang/mumei-agent/issues/650) extends existing
  Go function-local must/may facts, then
  [C06 language/type/symbol adapters](https://github.com/mumei-lang/mumei-agent/issues/651)
  and [C07 resolved-call summaries](https://github.com/mumei-lang/mumei-agent/issues/652)
  add coverage incrementally. Tree-sitter alone is not semantic resolution.
- [C02 evidence](https://github.com/mumei-lang/mumei/issues/786) keeps body-port
  proofs, finite native replay, bounded/abstract analysis and source/artifact
  correspondence separate. Existing audit keys and Lean gates remain fixed.

External tools are not selected for adoption now. Plugin design precedes and
is independent of individual pilots. Missing/incompatible explicitly selected
tools must report a reason, not silently substitute another tool; fallback
requires user permission and cannot lower a required assurance level.
Plugin execution and remote data access require user/admin authorization.
Agent owns external-tool selection/execution; Mumei owns specification meaning
and shared acceptance rules, not external-tool orchestration. Do not run Z3
and all installed plugins in parallel by default: comparisons require a stated
purpose, permitted user policy, budget and result-reconciliation rules.

### C04/C11 first supported planning slice

`agent.verification_planner` is an opt-in, in-memory, single-route planning API.
`AdapterRegistry.register` accepts user descriptors and requires explicit
replacement for an existing ID. `RouteRequirements` is a capability query,
not a complete executable obligation. Profile/method/fragment/target constraints,
protocol compatibility, caller-supplied availability/version observations,
disable/location policy and exact tool-version pins filter candidates. Priority
then adapter ID break ties deterministically. Registering a descriptor alone
does not make it available or trusted; absent/unknown observations fail closed.

Explicit selection overrides priority. An unavailable explicit choice produces
no selection unless `allow_fallback=True`; any replacement must still satisfy
the original profile, method and other query constraints. A plan selects at most
one adapter, never all installed adapters. It exposes every candidate's reasons,
planned replacement provenance and effective timeout/memory ceilings, capped by
both user policy and descriptor limits. These are declared budgets, not resource
enforcement or a promise of successful verification.

`VerificationPlan.to_dict()` emits versioned, deterministic metadata only. It
has no verifier verdict, grade, command, path-to-execute, environment, arbitrary
options or endpoint channel. Metadata and runtime observations remain untrusted
claims; selection cannot bypass Mumei's common evidence acceptance or Lean gates.

This slice does **not** load plugins, discover/probe tools, launch processes,
read configuration/environment/source files, enforce authorization/resources,
perform runtime fallback, parse adapter results or change existing CLI/MCP/Z3
routes. Source/obligation/evidence ingestion, semantic assurance implication and
acceptance policy, observation freshness and full execution/fallback history remain
open C02/C03/C04/C11 work. The API is not a production verification dispatcher.
No external verifier is adopted. Regression fixtures use synthetic descriptors.

```python
from agent.verification_planner import (
    AdapterDescriptor, AdapterRegistry, PlannerPolicy, RouteRequirements,
    RuntimeObservation,
)

registry = AdapterRegistry()
registry.register(AdapterDescriptor(
    "user.adapter", "1.0.0", frozenset({"user.approved-profile/v1"}),
    frozenset({"deductive_proof"}),
))
plan = registry.plan(
    RouteRequirements("user.approved-profile/v1", "deductive_proof"),
    PlannerPolicy(selected_adapter="user.adapter"),
    # An illustrative host observation, not an actual tool probe or proof.
    (RuntimeObservation("user.adapter", "available", "1.0.0"),),
)
assert plan.selected is not None
```

### C04/C11 declared runtime fallback replanning

`AdapterRegistry.replan(plan, exclude=(), observations=None)` re-routes
a recorded plan after a host-declared runtime failure — the runtime
fallback the plan history was recorded for. It produces a new plan over
the same request and policy constraints with the previously selected
adapter — plus every registered id in `exclude` — treated as disabled
and explicit selection cleared; the new plan is recorded like any other.

```python
second = registry.replan(first)  # same constraints, new route
```

Three static preconditions keep the contract honest: the plan must come
from this registry's recorded `history()`, must have selected an
adapter, and must permit routing — an explicit non-fallback selection
(`selected_adapter` without `allow_fallback`) stays a hard boundary even
at replan. When `observations` is `None` the registry reuses its last
accepted stamped observations; pass `()` for no availability or a fresh
tuple for newer declarations.

Replanning is a **declared re-selection, not a runtime verdict**: it
records that the host observed a failure — it does not prove the
excluded adapter actually failed or that the new route will work, and it
carries no attempt outcome or Evidence. C04/C11 stay partial; source/
evidence ingestion, acceptance and default routes remain open.

### C11 bounded plan history for runtime fallback records

`AdapterRegistry.plan()` now appends every successful `VerificationPlan`
to a bounded in-memory `history()` — the runtime fallback/selection
record the C04/C11 gap list called for. Entries are appended in call
order and evicted oldest-first past `MAX_PLAN_HISTORY`; failed plans are
never recorded, `prepare_source` records exactly the plan it ran, and
adapter replacement does not clear the record. `history()` returns a
detached immutable snapshot.

```python
registry.plan(request, policy, observations)
registry.history()  # -> tuple[VerificationPlan, ...], oldest first
```

History is a **declared record, not a durable audit or Evidence**: it is
lost with the registry, evicts silently past the bound, and says nothing
about whether a plan was dispatched or accepted. Persistence, tamper
evidence, cross-registry ordering and Evidence acceptance remain host
duties and open work. No default CLI/MCP/audit route, external verifier
or dependency is added. C11 stays partial; C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C04 durable plan history log

The opt-in `agent.plan_history_log` library module exposes
`append_plan_history(path: str, plan: VerificationPlan) -> str` and
`read_plan_history(path: str, *, expected_head: str | None = None) ->
tuple[dict, ...]` for a canonical JSONL log of existing
`VerificationPlan.to_dict()` projections. Each entry is SHA-256 chained
to the previous entry. The chain detects in-file edits, reordering and
mid-file deletion; tail truncation or rollback is detected only when the
host supplies a pinned `expected_head`. This is tamper evidence, not
authentication: a writer can rewrite the complete chain. The projection
contains only the existing non-secret plan fields, and the log is not
Evidence or a dispatch or acceptance record.

Cross-process writer exclusion requires POSIX `fcntl`; where it is
unavailable, locking is process-local and hosts must use a single writer
process. A write or fsync failure triggers best-effort rollback to the
validated prefix. Entries use standard JSON and reject NaN and Infinity.

C04/C11 remain partial: Evidence acceptance and default routes are open
work. The log does not wire persistence into planning, dispatch or runtime
fallback.

`verify-plan --history-log PATH [--expected-history-head HEX]` appends the
emitted plan and reports the new head on stderr without changing the plan
document. MCP `verify_plan` and `verify-schedule` do not write this log.

### C04 environment.read enforcement at dispatch

Scheduled adapter attempts run with only `PATH` (and `SYSTEMROOT` on
Windows) unless the selected adapter declares `environment.read` and the
explicit policy permits it. Undeclared permissions fail closed. This
enforces only the environment category; `filesystem.*`, `network.connect`, and
`process.spawn` remain declared-only. Environment scrubbing is not a
sandbox and is not Evidence.

### C11 declared memory bounds for attempted executions

`AttemptRunner.run(request, argv, cancel_event=None, memory_bound_mb=None)`
accepts an optional host-declared memory ceiling (an integer in
`1..=MAX_MEMORY_BOUND_MB`, validated statically). When declared, the child
is spawned under POSIX `RLIMIT_AS`, capping its whole address space — the
declared `memory_mb` budget a plan produces now reaches the execution
boundary instead of stopping at the plan manifest. The bound applies to
the child only; the runner process is never constrained, and a non-POSIX
host rejects a declared bound with a static error. The bound is applied
by an exec wrapper — `prlimit --as=` when available, else a POSIX
`sh -c 'ulimit -v <KiB> && exec "$@"'` wrapper (the same RLIMIT_AS
through a pure exec chain, so bounded spawns stay thread-safe on hosts
without `prlimit`); `preexec_fn` remains only when neither exists.

```python
result = AttemptRunner().run(request, argv, memory_bound_mb=256)
```

A declared bound is **best-effort resource enforcement, not a sandbox**:
it covers no CPU, I/O, network or permission policy, and the runner never
diagnoses why a child ended — exceeding the bound surfaces only as an
ordinary observed outcome (`exited` with its code, `failed` or
`timed_out`), indistinguishable from a natural exit. Timeout, cancel,
collector and record semantics are unchanged. Authorization, scheduling,
output interpretation, Evidence acceptance and any further isolation stay
host duties and open work. No default CLI/MCP/audit route, external
verifier or dependency is added. C11 stays partial; C12's demand gate and
existing assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 monotonic observation stamps for replay detection

`RuntimeObservation` carries an optional host-declared `stamp` — a bounded
monotonic counter, the planner-side analogue of attempt `report_stamp`.
`AdapterRegistry.plan()` records accepted stamped observations per adapter
id: once one is accepted every later observation for that adapter must
carry a stamp, a smaller stamp is a static stale error (`adapter
observation stamp is not fresh`), a reused stamp only tolerates an
identical observation (`adapter observation stamp conflict` otherwise) and
a larger one advances the boundary. Stamp tracking only updates when the
whole plan succeeds, and unstamped tuples keep legacy behavior.

```python
registry.plan(request, policy, (RuntimeObservation("a", "available", "1.0", 5),))
registry.plan(request, policy, (RuntimeObservation("a", "missing", "1.0", 6),))
```

A stamp is a **delivery counter, not freshness proof, authenticity or
acceptance**: the host can always mint a larger one, observed availability
and tool versions stay untrusted claims, and a stale result detects reorder
or replay only at this registry. Probing, clock checks, delivery
completeness, cross-registry ordering and Evidence acceptance remain host
duties and open work. No default CLI/MCP/audit route, external verifier or
dependency is added. C11 stays partial; C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 declarative adapter manifests

`AdapterDescriptor.from_manifest(manifest)` statically parses a detached,
host-supplied manifest (`schema_version` `mumei.verifier-adapter/v1`) into
a validated descriptor, and `AdapterRegistry.register_manifest(manifest,
replace=...)` registers it — a test user adapter can now be described and
added or replaced **without editing core code**. `to_dict()` round-trips
losslessly: required fields are `adapter_id`, `adapter_version`,
`profiles`, `methods`; every other field defaults exactly as the
constructor does. Wrong schemas, unknown or missing fields, malformed
label lists, contracts or setting specs are static errors.

```python
registry.register_manifest(manifest)                # declared add
registry.register_manifest(manifest, replace=True)  # explicit replace
```

A manifest is **metadata, not a plugin**: it names capabilities, budgets
and schemas but carries no code, grants no authority and proves nothing
about availability — nothing is imported, discovered, probed or executed
on registration, and registration is still not an availability proof or
acceptance. Actual plugin loading, adapter code execution, resource
enforcement and Evidence acceptance remain host duties and open work. No
default CLI/MCP/audit route, external verifier or dependency is added. C11
stays partial; C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 normalized run-result descriptors

`AttemptRunResult.normalized()` maps one observed terminal run into
`AttemptNormalizedResult` — detached metadata under
`mumei.verifier-run-result/v1` naming only the request binding
(fingerprint, ordinal, declared timeout), the terminal outcome
(`exited`/`failed`/`timed_out`/`cancelled`), the terminal event's elapsed
counter, the exit code when and only when the outcome is `exited`, and the
bounded-output manifest (size, SHA-256, `complete`). Hosts can consume every
outcome through one stable shape without reading event histories or raw
bytes; non-terminal outcomes, foreign exit codes, oversize declarations and
non-bool completeness are static errors.

```python
result = AttemptRunner().run(request, argv)
normalized = result.normalized()
assert normalized.to_dict()["outcome"] == "exited"
```

Normalization covers **agent-side observations only**: the digest binds
bytes, not meaning; an exit code is transport metadata, never a
verification verdict; `complete` records only that collection stayed within
the bound, not how much was missed. No parsing, verdict interpretation,
acceptance, canonical publication, retry policy or scheduling is added —
Core still owns Evidence checks and meaning, and hosts still bind snapshots
with `AttemptOutput` and publish via `AttemptSequenceStore`. No default
CLI/MCP/audit route, external verifier or dependency is added. C11 stays
partial; C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 real process control for declared execution requests

`agent/attempt_runner.py` is the first **effectful** boundary in this
cluster: `AttemptRunner.run(request, argv, cancel_event=None)` spawns one
real child process for one declared `AttemptExecutionRequest`, waits bounded
by the request's declared timeout, terminates runaways and honors a single
`threading.Event` cancellation. What the runner observes is reported as
`AttemptRecord` events — `started`, then exactly one of `exited` (natural
exit with its real code), `failed` (spawn refused by the OS), `timed_out`
(deadline reached, child killed) or `cancelled` (cancel grace expired, child
killed after `cancel_requested` + terminate). Captured stdout is drained on
a side thread so writers past the pipe buffer cannot deadlock the wait,
bounded to `MAX_STDOUT_BYTES`, and returned on `AttemptRunResult` with a
`complete` declaration that is `False` whenever truncation occurred or the
bounded drain could not finish (e.g. a grandchild holding the pipe open).

```python
from agent.attempt_runner import AttemptRunner
from agent.verification_attempt import AttemptOutput

result = AttemptRunner().run(request, ("mumei", "verify", path))
output = AttemptOutput(
    result.record, result.stdout, digest, "stdout", result.complete
)
```

`run` is deliberately small: it performs **no** authorization, scheduling,
dispatch decision, output interpretation or canonical publication — the
host still decides via `check_dispatch`, binds snapshots with
`AttemptOutput` and publishes through `AttemptSequenceStore`. The record is
only what was observed this call: `complete=False` records observed
truncation, not how much was lost, and an `exited` code is a fact about
process exit, never a verification verdict. Wall-clock reads stay inside
this module; `verification_attempt.py` remains passive. No default
CLI/MCP/audit route, Evidence normalization/acceptance, cross-attempt
scheduling, retry policy, plugin, external verifier or dependency is added.
C11 stays partial; Core meaning and acceptance, C12's demand gate and
existing assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 dispatch-boundary checks for declared requests

`AttemptSequence.next_dispatch()` derives the single outstanding
dispatchable intent: a `ready` current record yields its
`AttemptExecutionRequest`, and anything else — nothing reserved, a running
attempt still in flight, a cancelling or terminal record — yields `None`.
`None` does not mean nothing may run: an in-flight attempt continues and
host-initiated cancellations are declared separately. `check_dispatch` is
the static counterpart for host-built requests: an
`AttemptExecutionRequest` must name this value's current ready record
(including its declared timeout) and an `AttemptCancelRequest` the current
running one — wrong types, foreign fingerprints, stale ordinals and
unserved states are static errors, never silent drops.

```python
from agent.verification_attempt import AttemptSequence

sequence = AttemptSequence.from_prepared(prepared).begin_attempt()
request = sequence.next_dispatch()      # or None when nothing is ready
sequence.check_dispatch(request)        # raises for stale/foreign requests
```

These are **boundary checks, not a runner or scheduler**: nothing is
dispatched, delivered, queued, ordered across sequences or confirmed —
dispatch, delivery integrity, ordering policy and process control remain
host duties, and a request that passes today is just a description the host
must re-check against the canonical value at send time. No I/O, clocks,
plugins, runner/scheduler, Evidence normalization/acceptance, external
verifier, dependency or default audit/CLI/MCP route is added. C11 stays
partial; Core meaning and acceptance, C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 declared-dispatch execution driver

`agent.attempt_runner.dispatch_attempt(sequence, argv, *, runner=None,
cancel_event=None, memory_bound_mb=None, report_stamp=None)` runs the
sequence's outstanding dispatch end-to-end: `next_dispatch()` must
yield a request (nothing reserved, an attempt in flight or a terminal
current record is a static error, never a run), `AttemptRunner.run`
executes it under the declared timeout and the terminal record is
reconciled back into the sequence. A stamped sequence requires a fresh
`report_stamp`, validated before spawn so a missing or stale stamp is a
static error rather than a lost observation. The returned
`AttemptDispatch(sequence, run)` pairs the reconciled sequence with the
observed run — its own validation requires the sequence's current
record to carry the run's full binding (fingerprint, ordinal, declared
timeout) and events. `dispatch.captured_output()` binds the run's
bounded stdout as an `AttemptOutput` on the reconciled current record
(stream `stdout`, `complete` carried from the run's collection claim);
a failed, timed-out or cancelled run cannot mint a snapshot — output
requires an exited record — and the result is still a host claim, not
Evidence. `publish_dispatch(store, dispatch, expected=None)` closes the
loop: an `exited` run first selects its captured output, then the
terminal lineage is atomically published — CAS against `expected`, or
first publication on an empty store — while non-exited terminals
publish the reconciled lineage without a selection.

The driver adds no new authority: it composes the declared dispatch
boundary with the same single-spawn runner, performing no scheduling or
ordering, and publication goes through the same CAS/first-publish
contract — cross-sequence arbitration, durability and Evidence remain
host duties. C11 stays partial; Evidence
normalization/acceptance remains open, and C12's demand gate plus
existing assurance/Lean/native/LLVM/deferred-WASM policies are
unchanged.

### C11 reserve-and-dispatch driver for the next attempt

`agent.attempt_runner.dispatch_next_attempt(sequence, argv, *, runner=None,
cancel_event=None, memory_bound_mb=None, report_stamp=None)` reserves the
next attempt and runs it through the same declared-dispatch driver:
`begin_attempt` supplies the reservation (a sequence closed by a selected
result fails statically, and a running or cancelling current record fails
because predecessors must be terminal), then `dispatch_attempt` runs it —
on a fresh sequence this runs attempt one, after a terminal record it is
the declared retry. A stamped sequence requires a fresh `report_stamp`,
checked before spawn, and the returned `AttemptDispatch` carries the same
reconciled-sequence/observed-run pair.

```python
from agent.attempt_runner import dispatch_next_attempt

dispatch = dispatch_next_attempt(sequence, ("python", "-c", "..."))
dispatch = dispatch_next_attempt(dispatch.sequence, argv)  # declared retry
assert dispatch.sequence.current.attempt_number == 2
```

The driver adds no new authority: nothing here decides whether another
attempt is worthwhile, re-picks `argv`, bounds the attempt count or
inspects the previous outcome — each next attempt is declared by the host
calling. No scheduling, ordering, result selection, output snapshot,
publication, Evidence normalization/acceptance, external verifier,
dependency or default audit/CLI/MCP route is added. C11 stays partial;
Core meaning and acceptance are unchanged.

### C11 end-to-end dispatch-and-publish driver

`agent.attempt_runner.dispatch_and_publish(store, argv, *, runner=None,
cancel_event=None, memory_bound_mb=None, report_stamp=None)` closes the
attempt lifecycle loop: `store.current` supplies the lineage (an empty
store is a static error), `begin_attempt` reserves the next record,
`dispatch_attempt` runs it and reconciles the observation, and
`publish_dispatch` publishes the terminal lineage through
compare-and-set against the pre-run store value — a store another
writer touched mid-run fails statically instead of clobbering. The
canonical lineage, including any `selected_result` the publish added,
is the store's current value; the returned `AttemptDispatch` pairs the
reconciled sequence with the observed run.

```python
from agent.attempt_runner import dispatch_and_publish

dispatch = dispatch_and_publish(store, argv)
assert store.current is not None  # terminal lineage published
```

A CAS rejection after a completed run surfaces the store's error — the
process still ran and recovering it is a host decision. The driver adds
no arbitration across writers, retry policy, durability or Evidence
acceptance — it composes the declared boundaries only. C11 stays
partial; Core meaning and acceptance are unchanged.

### C11 declared lifecycle composition coverage

`tests/test_attempt_lifecycle.py` exercises the declared boundaries as
one chain rather than five separate gates: a manifest-declared adapter
probe → `probe_request_for`/`observe_probes`/`run_probe` →
`AdapterProbeHistory` and `probe_retry_requests` → `plan_with_probes` →
`AttemptSequenceStore` lineage → `dispatch_and_publish` →
`captured_output` → canonical `selected_result` → `evidence_candidate` →
`normalized()` and `to_dict` snapshots. A regression in any composition
fails one test.

This is regression coverage of the declared contracts only: every value
in the chain remains a host declaration — probing proves a command ran,
selection names a declared canonical snapshot and the evidence candidate
is a handoff descriptor, never acceptance. C11 stays partial; Core
meaning and acceptance, C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 evidence-candidate handoff descriptors

`AttemptSequence.evidence_candidate()` returns an `AttemptEvidenceCandidate`
naming the declared canonical snapshot for a host to hand to Core: the
request fingerprint, the selected attempt ordinal and the output manifest
fingerprint — nothing else. Only a sequence closed by `select_result` can
produce one; unclosed sequences fail with a static error. The value
serializes as detached metadata under
`mumei.verifier-evidence-candidate/v1`.

```python
from agent.verification_attempt import AttemptSequence

selected = sequence.select_result(output)
candidate = selected.evidence_candidate()
assert candidate.output_fingerprint == output.to_dict()["output_fingerprint"]
```

This is a **handoff descriptor, not Evidence**: the fingerprint binds the
manifest, not content correctness — hashing a manifest is not semantic
correctness and naming a candidate is not acceptance. The value carries no
bytes, makes no validity claim and grants no authority; it performs no
normalization and asserts no acceptance — Core owns the meaning and
acceptance of the original bytes, which the host must still deliver over its
own channel. No I/O, clocks, plugins, runner/scheduler, Evidence
normalization/acceptance, external verifier, dependency or default
audit/CLI/MCP route is added. C11 stays partial; Core meaning and
acceptance, C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 declared evidence-check outcomes

`AttemptSequence.evidence_check(candidate, outcome)` records a
host-declared representation-check outcome for the candidate as an
`AttemptEvidenceCheck`: the request fingerprint, the attempt ordinal,
the output manifest fingerprint and one declared `outcome` from
`EVIDENCE_CHECK_OUTCOMES` — `"valid"` (Core returned the known v1
diagnostic for the delivered bytes), `"failed"` (the check produced no
accepted diagnostic — an invalid representation, a malformed diagnostic
and a spawn/I/O failure are indistinguishable by design) or
`"cancelled"`. The `candidate` must equal the sequence's
`evidence_candidate()`; a stale or foreign descriptor and any outcome
outside the vocabulary are static errors, not recorded checks.

```python
selected = sequence.select_result(output)
check = selected.evidence_check(
    selected.evidence_candidate(), "valid"
)
assert check.outcome == "valid"
```

This is a **check record, not Evidence**: `"valid"` only means Core's
representation check passed for the bytes the host delivered — the
record carries no bytes, performs no check itself and asserts no truth,
freshness, authenticity, correspondence or grade promotion, which remain
unassessed host/Core duties. The value serializes as detached metadata
under `mumei.verifier-evidence-check/v1`. No I/O, clocks, plugins,
runner/scheduler, Evidence normalization/acceptance, external verifier,
dependency or default audit/CLI/MCP route is added. C11 stays partial;
Core meaning and acceptance, C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 recorded evidence-check outcomes

`agent.core_evidence.record_evidence_check(sequence, output, *,
core_executable, timeout_ms, cancel_event=None)` runs
`check_evidence_representation` and returns the `AttemptEvidenceCheck`
the sequence's `evidence_check` produces: `"valid"` when Core returned
the known v1 diagnostic, `"failed"` when the check produced no accepted
diagnostic and `"cancelled"` when the host's cancel event was observed.
The check now distinguishes failure kinds: `CoreCheckFailed` (a
`ValueError` subclass) marks a real check failure, while request-shape
errors stay plain `ValueError`, so a malformed request is never recorded
as a checked-and-failed representation. `output` must be the selected
result itself — its manifest fingerprint must equal the candidate's, so
checking different bytes under the same attempt record cannot mislabel
the declaration. Static errors — an unselected sequence, a
foreign/stale output binding, an unselected output or a malformed
request — propagate and record nothing; the candidate, output binding
and selection are validated before any spawn.

```python
check = record_evidence_check(
    selected, output,
    core_executable=trusted_core_path, timeout_ms=1000,
)
assert check.outcome in {"valid", "failed", "cancelled"}
```

The driver adds no new authority: it runs the same opt-in POSIX handoff
with the same executable/trust/timeout contract, and the record remains
a host declaration — `"valid"` means representation-valid only, never
acceptance. C11 stays partial; Core meaning and acceptance, C12's demand
gate and existing assurance/Lean/native/LLVM/deferred-WASM policies are
unchanged.

### C02 declared evidence-check acceptance normalization

`AttemptEvidenceCheck.from_dict(data)` restores a stored check record:
the exact key set and `mumei.verifier-evidence-check/v1` schema are
required, then the constructor re-checks every invariant — a foreign
schema, unknown keys or malformed members are static errors, and the
record still carries no bytes and asserts no acceptance.
`AttemptEvidenceCandidate.from_dict(data)` restores the handoff
descriptor under the same discipline (`mumei.verifier-evidence-candidate/v1`),
so a stored candidate and its check record both survive a declared
round trip. `AttemptNormalizedResult.from_dict(data)` restores the
`mumei.verifier-run-result/v1` record the candidate binds: the exact
key set, the conditional `exit_code` member and the `stdout`
sub-record's optional `complete: false` are all re-checked, so a
stored run result round-trips under the same declared discipline. The
detached attempt requests restore the same way:
`AttemptExecutionRequest.from_dict` and `AttemptCancelRequest.from_dict`
rebuild `mumei.verifier-attempt-execution/v1` and
`mumei.verifier-attempt-cancel/v1` records fail-closed.

`agent.core_evidence.evaluate_evidence_check(sequence, check)` normalizes
a declared record into an acceptance descriptor
`mumei.evidence-check-acceptance/v1`: `candidate_match` holds only when
the record binds the sequence's CURRENT `evidence_candidate()` — a stale
or foreign check never counts — and `accepted` holds only when the record
is current AND its outcome is `"valid"`. This is representation-level
acceptance: the six semantic checks (`claim_truth`, `file_identity`,
`freshness`, `producer_authenticity`, `semantic_correspondence`,
`artifact_semantics`) stay in `checks_not_performed`, and nothing here is
Evidence, a verdict or a grade promotion. A sequence with no selected
result raises `ValueError` — there is no current candidate to evaluate.

```python
descriptor = evaluate_evidence_check(selected, check)
assert descriptor["accepted"] == (
    descriptor["candidate_match"] and check.outcome == "valid"
)
```

Evaluation adds no new authority: it reads declared values only and
performs no I/O, spawn or Core call. Core meaning and acceptance,
freshness-at-acceptance-time beyond record currency, cross-sequence
ordering and every `checks_not_performed` entry remain unassessed
host/Core duties. C02/C11 stay partial; existing assurance/Lean/native/
LLVM/deferred-WASM policies are unchanged.

### C02 declared evidence-check acceptance route (evidence-check-accept)

`python -m agent evidence-check-accept --sequence <path> --check <path>`
loads a stored sequence and a stored `mumei.verifier-evidence-check/v1`
record, runs `evaluate_evidence_check` and prints the
`mumei.evidence-check-acceptance/v1` descriptor — the consume side of
the produce+consume pair. `accepted` holds only when the stored record
binds the sequence's CURRENT `evidence_candidate()` AND its outcome is
`"valid"`: a stale or foreign record always yields `accepted: false`,
so the route cannot forge acceptance. Declared inputs are bounded,
checked for shape before any evaluation and may not be overwritten by
`--output`. This stays representation-level — claim truth, freshness,
authenticity and correspondence remain unassessed duties. C02 stays
partial.

### C02 declared verify-attempt route (verify-attempt)

`python -m agent verify-attempt --core <path> --source <path>` closes
the produce+consume loop: it runs `<core> evidence verify-source <src>
--json` as one declared attempt — the `mumei.verify-attempt-request/v1`
fingerprint binds the Core executable's bytes, the source bytes and the
bounded solver budgets — publishes the reconciled sequence, and only
when a result is selected (`exited` with `exit_code == 0`, i.e.
`EstablishedWithinProfile`) runs `record_evidence_check` +
`evaluate_evidence_check` against the live Core, emitting
`mumei.verify-attempt-report/v1` (sequence + normalized + candidate +
evidence_check + acceptance). This is the first route where `accepted`
can be `true`: the produced bytes are `mumei.verification-evidence/v1`
— evidence-shaped, unlike the summary manifests that made the
withdrawn `--evidence-core` wiring deterministically `accepted:false`.
Refuted (exit 1) / inconclusive (exit 3) runs publish the terminal
lineage with no selection; `--output` may not overwrite declared
inputs and sources over Core's 64 KiB input bound are rejected before
dispatch. The `acceptance` descriptor itself stays
representation-level — it asserts no semantic duty on its own.
A selected run also discharges five of the six semantic checks for
the produced record at representation level — `file_identity` (its
`subject.sha256` was computed over the declared bytes),
`producer_authenticity` (provenance binds the pinned executable),
`freshness` (just produced), `semantic_correspondence`
(established within the declared profile) and `claim_truth` (the
verifier's `established` verdict is the strongest truth receipt the
pipeline emits) — reported in `discharged_checks` with
`artifact_semantics` (the compiled-artifact layer) left in
`checks_not_performed`.
C02 stays partial.

### C02 declared verify-recheck route (verify-recheck)

`python -m agent verify-recheck --core <path> --evidence <path>
--source <path>` is the freshness companion of verify-attempt: it runs
`<core> evidence recheck-source <evidence> --source <src> --json` as
one declared attempt — the `mumei.verify-recheck-request/v1`
fingerprint binds the Core executable's bytes, the saved Evidence
record's bytes, the caller-supplied source's bytes and the bounded
solver budgets — re-running the same restricted source query against a
SAVED record so stale, tampered or profile-drifted records surface
without any saved label/path being read. Only an `exited` run with
`exit_code == 0` (`Consistent`) selects the produced
`mumei.source-evidence-recheck/v1` diagnostic. The `recheck` field
names only unambiguous codes (`0 → consistent`, `3 → inconclusive`):
exit 1 conflates `Refuted` with every static failure including
`Invalid`/`InconsistentSavedEvidence` — the stale-or-tampered case —
so it is claimed only through the lineage's `exit_code`. Mid-run input
drift suppresses selection and any claimed outcome, reported as
`inputs_changed`. No evidence_check runs: the recheck diagnostic is
not verification-evidence-shaped — its exit code IS the verdict.
A `consistent` outcome discharges three of the six semantic checks
at representation level: the record still binds the declared source
bytes' fresh same-profile verdict, so it is current (`freshness`),
its claims still correspond to the source's verified semantics
(`semantic_correspondence`) and those claims were re-established
within the declared profile (`claim_truth`) — reported in
`discharged_checks`, with `checks_not_performed` naming the rest
(`file_identity`, `producer_authenticity` and `artifact_semantics`,
the first two discharged by their own declared routes). A non-consistent run
discharges nothing.
C02 stays partial.

### C02 declared verify-accept route (verify-accept)

`python -m agent verify-accept --core <path> --evidence <path>
--source <path>` is the acceptance companion of verify-recheck: it
runs `<core> evidence accept-source <evidence> --source <src> --json`
as one declared attempt under a `mumei.verify-accept-request/v1`
fingerprint binding the same four inputs — Core executable, saved
record, declared source, bounded solver budgets. Where verify-recheck
asks whether the record is still consistent, accept-source folds the
representation gate in on top — the record must parse AND still match
a fresh same-profile verification — and emits the
`mumei.source-evidence-acceptance/v1` descriptor (with
`evidence_fingerprint` binding the record's bytes) on acceptance
only. Only an `exited` run with `exit_code == 0` (`Accepted`) selects
the produced descriptor; `rejected` (1) and `inconclusive` (3) runs
publish terminal lineage with no selection. The `acceptance` field
names only `0 → accepted` and `3 → inconclusive`: exit 1 conflates
`Rejected` with every static failure including
`Invalid`/`InconsistentSavedEvidence`, so it is claimed only through
the lineage's `exit_code`; mid-run drift reports `inputs_changed`
with no claimed outcome. An `accepted` outcome discharges the same
honest three-check set as a consistent recheck — `claim_truth`,
`freshness` and `semantic_correspondence` — reported in
`discharged_checks` with the rest in `checks_not_performed`. The
route is also reachable as the `verify_accept` MCP tool. C02 stays
partial.

### C02/C10 declared native-recheck route (native-recheck)

`python -m agent native-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares a native
consumer recheck as one attempt: `<core> native-bundle recheck-llvm
--expected-build-id <id> --json <bundle> <source>` under a
`mumei.native-recheck-request/v1` fingerprint binding the Core
executable's bytes, every bundle member the record declares — the
`files` map's component members plus, for
`mumei.native-multifile-bundle/v1`, each `sources/<member>` the merge
is re-derived from, enumerated from `native-bundle.json` and
validated against the member grammar before joining so a hand-crafted
record cannot steer the fingerprint's reads outside the bundle — the
source's bytes and the trusted-channel build ID. The post-run drift
check re-enumerates members from the current record, so a record
swapped mid-run that declares new members reports `inputs_changed`
rather than claiming an outcome on unbound bytes. Only
an `exited` run with `exit_code == 0` (`EquivalentWithinProfile`)
selects the produced `mumei.native-consumer-evidence/v1` report (the
three-record envelope: bundle identity, fresh source postcondition,
source-to-LLVM user-body correspondence). `recheck` names only
`0 → equivalent` and `3 → inconclusive`; exit 1 conflates
Different/UndefinedBehavior with every static failure, and mid-run
drift reports `inputs_changed` with no claimed outcome. No
evidence_check: the envelope's own `acceptance` is `not_evaluated`.
An `equivalent` outcome discharges `artifact_semantics` — the
pinned bundle's user-body LLVM corresponds to the declared source's
verified semantics, the deepest layer the pipeline covers — and
`claim_truth` (the envelope's fresh source postcondition was
re-established within the declared profile), both at representation
level and reported in `discharged_checks` with the other four checks
in `checks_not_performed` (linker, runtime and binary correctness
stay outside the profile).
C02/C10 stay partial.

### C02/C10 declared native-accept route (native-accept)

`python -m agent native-accept --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares a native
artifact acceptance as one attempt: `<core> native-bundle
accept-artifact --expected-build-id <id> --json <bundle> <source>`
under a `mumei.native-accept-request/v1` fingerprint binding the Core
executable's bytes, every bundle member the record declares — the
component files plus, for `mumei.native-multifile-bundle/v1`, each
`sources/<member>` the merge is re-derived from, enumerated from
`native-bundle.json` and validated against the member grammar before
joining so a hand-crafted record cannot steer the fingerprint's file
reads outside the bundle — the source's bytes and the trusted-channel
build ID. Where `native-recheck` stops at the LLVM snapshot,
`accept-artifact` additionally rebuilds the pinned object from the
pinned IR and relinks the pinned executable, comparing both
byte-for-byte. Only an `exited` run with `exit_code == 0` selects the
produced `mumei.native-evidence-acceptance/v1` descriptor.
`acceptance` names only `0 → accepted` and `3 → inconclusive`; exit 1
conflates a failed reproduction with every static failure, and mid-run
drift reports `inputs_changed` with no claimed outcome. No evidence
candidate is emitted: the descriptor is anonymous by design — it binds
no subject, digest or provenance — so there is no handoff; the captured
bytes enter the lineage through the selection itself. An `accepted`
outcome discharges `artifact_semantics` — the bundle's user-body LLVM
AND its pinned object/executable bytes correspond to the declared
source's verified semantics under the recorded toolchain, the deepest
layer the pipeline covers — and `claim_truth`, both at representation
level and reported in `discharged_checks` with the other four checks in
`checks_not_performed` (producer authenticity, historical execution and
runtime/OS semantics stay outside the profile; the link
argument-vector is recorded-but-not-reproduced inside Core and adds no
claim). `object_translation_correspondence` stays in
`checks_not_performed` until a Core object-stage TV accept route exists.
The bounded `object_symbol_correspondence`,
`object_call_edge_correspondence` and `object_link_correspondence` checks
also stay unperformed by
`native-accept`; the separate `native-object-recheck` report is
non-performing in recovery.
The route is also the `native_accept` MCP tool (same
`run_accept` report production, declared-path validation and basename
redaction as the other spawn tools). C02/C10 stay partial.

### C02/C10 declared native-artifact-recheck route (native-artifact-recheck)

`python -m agent native-artifact-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares a native
artifact reproduction replay as one attempt: `<core> native-bundle
recheck-artifact --expected-build-id <id> <bundle> <source>` under a
`mumei.native-artifact-recheck-request/v1` fingerprint binding the
bundle record plus every member it declares (the component files and,
for a multifile record, each `sources/` member the merge is re-derived
from) and the declared source. `artifact_recheck` is claimed only for
uniquely-mapped exit codes (`0 → reproduced`, `3 → inconclusive`);
exit 1 conflates a failed reproduction with every static failure and
claims nothing, mid-run drift reports `inputs_changed` with no claimed
outcome, and the drift check re-enumerates the member set from the
current record so a swapped-in member is caught. A `reproduced` run
reports `discharged_checks` — `artifact_semantics` and `claim_truth` —
with the remaining checks in `checks_not_performed`. The command's
stdout is a fixed diagnostic line rather than an evidence record, so
no `candidate` is emitted and a successful run selects only lineage.
`object_translation_correspondence` stays in `checks_not_performed`
until a Core object-stage TV accept route exists.
The bounded `object_symbol_correspondence`,
`object_call_edge_correspondence` and `object_link_correspondence` checks
also stay unperformed by
`native-artifact-recheck`; the separate `native-object-recheck` report
is non-performing in recovery.
The route is also the `native_artifact_recheck` MCP tool (same
`run_artifact_recheck` report production, declared-path validation and
basename redaction as the other spawn tools). C02/C10 stay partial.

### C02/C10 declared native-exit-status-recheck route (native-exit-status-recheck)

`python -m agent native-exit-status-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares the deepest
native consumer replay as one attempt: `<core> native-bundle
recheck-exit-status --expected-build-id <id> <bundle> <source>` under a
`mumei.native-exit-status-recheck-request/v1` fingerprint binding the
bundle record plus every member it declares (the component files and,
for a multifile record, each `sources/` member the merge is re-derived
from) and the declared source. `exit_status_recheck` is claimed only
for uniquely-mapped exit codes (`0 → reproduced`, `3 → inconclusive`);
exit 1 conflates a mismatched exit status with every static failure
and claims nothing, mid-run drift reports `inputs_changed` with no
claimed outcome, and the drift check re-enumerates the member set from
the current record. A `reproduced` run reports `discharged_checks` —
`artifact_semantics`, `claim_truth` and
`os_exit_status_observation` — with the remaining checks in
`checks_not_performed`; the exit-status match itself is an OS-level
observation bound by the record pin and discharges the named
`os_exit_status_observation` check. The other runtime-observation checks
remain in `checks_not_performed`, including
`runtime_observation_semantics`, which is performed only by the
one-invocation observations-accept route. The
command's stdout is a fixed diagnostic line rather
than an evidence record, so no `candidate` is emitted and a successful
run selects only lineage. The route is also the
`native_exit_status_recheck` MCP tool (same `run_exit_status_recheck`
report production, declared-path validation and basename redaction as
the other spawn tools). Every outcome echoes the trusted-channel
`expected_build_id`; recheck reports remain non-performers. C02/C10 stay
partial.

### C02/C10 declared native-exit-status-accept route (native-exit-status-accept)

`python -m agent native-exit-status-accept --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares the deepest
native consumer acceptance as one attempt: `<core> native-bundle
accept-exit-status --expected-build-id <id> --json <bundle> <source>`
under a `mumei.native-exit-status-accept-request/v1` fingerprint
binding the bundle record plus every member it declares (the
component files and, for a multifile record, each `sources/` member
the merge is re-derived from) and the declared source. `acceptance`
is claimed only for uniquely-mapped exit codes (`0 → accepted`,
`3 → inconclusive`); exit 1 conflates a mismatched exit status with
every static failure and claims nothing, mid-run drift reports
`inputs_changed` with no claimed outcome, and the drift check
re-enumerates the member set from the current record. An `accepted`
run reports `discharged_checks` — `artifact_semantics`, `claim_truth`
and `os_exit_status_observation` — with the remaining checks in
`checks_not_performed`;
the exit-status match itself is an OS-level observation bound by the
record pin and discharges the named `os_exit_status_observation` check.
The other runtime-observation checks remain in `checks_not_performed`,
including `runtime_observation_semantics`, which is performed only by
the one-invocation observations-accept route. Only an `exited`
run with `exit_code == 0` selects the produced
`mumei.native-evidence-acceptance/v1` descriptor — it is anonymous by
design, so no `candidate` is emitted. The route is also the
`native_exit_status_accept` MCP tool (same `run_exit_status_accept`
report production, declared-path validation and basename redaction as
the other spawn tools). Every outcome echoes the trusted-channel
`expected_build_id`; accepted sibling reports sharing that
Core-authenticated ID can recover one another's channel checks through
`recovery-eval`. C02/C10 stay partial.

### C02/C10 declared native-stdout-recheck route (native-stdout-recheck)

`python -m agent native-stdout-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares the adjacent
channel-observation replay as one attempt: `<core> native-bundle
recheck-stdout --expected-build-id <id> <bundle> <source>` under a
`mumei.native-stdout-recheck-request/v1` fingerprint binding the
bundle record plus every member it declares (the component files and,
for a multifile record, each `sources/` member the merge is re-derived
from) and the declared source. `stdout_recheck` is claimed only
for uniquely-mapped exit codes (`0 → reproduced`, `3 → inconclusive`);
exit 1 conflates a mismatched stdout digest with every static failure
and claims nothing, mid-run drift reports `inputs_changed` with no
claimed outcome, and the drift check re-enumerates the member set from
the current record. A `reproduced` run reports `discharged_checks` —
`artifact_semantics`, `claim_truth` and `os_stdout_observation` — with
the remaining checks in
`checks_not_performed`; the stdout digest match itself is an OS-level
observation bound by the record pin and discharges the named
`os_stdout_observation` check. The other runtime-observation checks
remain in `checks_not_performed`, including
`runtime_observation_semantics`, which is performed only by the
one-invocation observations-accept route. The
command's stdout is a fixed diagnostic line rather
than an evidence record, so no `candidate` is emitted and a successful
run selects only lineage. The route is also the
`native_stdout_recheck` MCP tool (same `run_stdout_recheck`
report production, declared-path validation and basename redaction as
the other spawn tools). Every outcome echoes the trusted-channel
`expected_build_id`; recheck reports remain non-performers. C02/C10 stay
partial.

### C02/C10 declared native-stdout-accept route (native-stdout-accept)

`python -m agent native-stdout-accept --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares the adjacent
channel-observation acceptance as one attempt: `<core> native-bundle
accept-stdout --expected-build-id <id> --json <bundle> <source>`
under a `mumei.native-stdout-accept-request/v1` fingerprint
binding the bundle record plus every member it declares (the
component files and, for a multifile record, each `sources/` member
the merge is re-derived from) and the declared source. `acceptance`
is claimed only for uniquely-mapped exit codes (`0 → accepted`,
`3 → inconclusive`); exit 1 conflates a mismatched stdout digest with
every static failure and claims nothing, mid-run drift reports
`inputs_changed` with no claimed outcome, and the drift check
re-enumerates the member set from the current record. An `accepted`
run reports `discharged_checks` — `artifact_semantics`, `claim_truth`
and `os_stdout_observation` — with the remaining checks in
`checks_not_performed`;
the stdout digest match itself is an OS-level observation bound by the
record pin and discharges the named `os_stdout_observation` check.
The other runtime-observation checks remain in `checks_not_performed`,
including `runtime_observation_semantics`, which is performed only by
the one-invocation observations-accept route. Only an `exited`
run with `exit_code == 0` selects the produced
`mumei.native-evidence-acceptance/v1` descriptor — it is anonymous by
design, so no `candidate` is emitted. The route is also the
`native_stdout_accept` MCP tool (same `run_stdout_accept`
report production, declared-path validation and basename redaction as
the other spawn tools). Every outcome echoes the trusted-channel
`expected_build_id`; accepted sibling reports sharing that
Core-authenticated ID can recover one another's channel checks through
`recovery-eval`. C02/C10 stay partial.

### C02/C10 declared native-stderr-recheck route (native-stderr-recheck)

`python -m agent native-stderr-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares the closing
channel-observation replay as one attempt: `<core> native-bundle
recheck-stderr --expected-build-id <id> <bundle> <source>` under a
`mumei.native-stderr-recheck-request/v1` fingerprint binding the
bundle record plus every member it declares (the component files and,
for a multifile record, each `sources/` member the merge is re-derived
from) and the declared source. `stderr_recheck` is claimed only
for uniquely-mapped exit codes (`0 → reproduced`, `3 → inconclusive`);
exit 1 conflates a mismatched stderr digest with every static failure
and claims nothing, mid-run drift reports `inputs_changed` with no
claimed outcome, and the drift check re-enumerates the member set from
the current record. A `reproduced` run reports `discharged_checks` —
`artifact_semantics`, `claim_truth` and `os_stderr_observation` — with
the remaining checks in
`checks_not_performed`; the stderr digest match itself is an OS-level
observation bound by the record pin and discharges the named
`os_stderr_observation` check. The other runtime-observation checks
remain in `checks_not_performed`, including
`runtime_observation_semantics`, which is performed only by the
one-invocation observations-accept route. The
command's stdout is a fixed diagnostic line rather
than an evidence record, so no `candidate` is emitted and a successful
run selects only lineage. The route is also the
`native_stderr_recheck` MCP tool (same `run_stderr_recheck`
report production, declared-path validation and basename redaction as
the other spawn tools). Every outcome echoes the trusted-channel
`expected_build_id`; recheck reports remain non-performers. C02/C10 stay
partial.

### C02/C10 declared native-stderr-accept route (native-stderr-accept)

`python -m agent native-stderr-accept --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares the closing
channel-observation acceptance as one attempt: `<core> native-bundle
accept-stderr --expected-build-id <id> --json <bundle> <source>`
under a `mumei.native-stderr-accept-request/v1` fingerprint
binding the bundle record plus every member it declares (the
component files and, for a multifile record, each `sources/` member
the merge is re-derived from) and the declared source. `acceptance`
is claimed only for uniquely-mapped exit codes (`0 → accepted`,
`3 → inconclusive`); exit 1 conflates a mismatched stderr digest with
every static failure and claims nothing, mid-run drift reports
`inputs_changed` with no claimed outcome, and the drift check
re-enumerates the member set from the current record. An `accepted`
run reports `discharged_checks` — `artifact_semantics`, `claim_truth`
and `os_stderr_observation` — with the remaining checks in
`checks_not_performed`;
the stderr digest match itself is an OS-level observation bound by the
record pin and discharges the named `os_stderr_observation` check.
The other runtime-observation checks remain in `checks_not_performed`,
including `runtime_observation_semantics`, which is performed only by
the one-invocation observations-accept route. Only an `exited`
run with `exit_code == 0` selects the produced
`mumei.native-evidence-acceptance/v1` descriptor — it is anonymous by
design, so no `candidate` is emitted. The route is also the
`native_stderr_accept` MCP tool (same `run_stderr_accept`
report production, declared-path validation and basename redaction as
the other spawn tools). Every outcome echoes the trusted-channel
`expected_build_id`; accepted sibling reports sharing that
Core-authenticated ID can recover one another's channel checks through
`recovery-eval`. C02/C10 stay partial.

### C02/C10 declared native-observations-accept route (native-observations-accept)

`python -m agent native-observations-accept --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares one invocation
acceptance: `<core> native-bundle accept-observations
--expected-build-id <id> --json <bundle> <source>` under a
`mumei.native-observations-accept-request/v1` fingerprint binding the
Core executable, the bundle record and every declared member, the
source and the trusted-channel build ID. `acceptance` is claimed only
for uniquely-mapped exit codes (`0 → accepted`, `3 → inconclusive`);
exit 1 claims nothing, and mid-run drift reports `inputs_changed`
without an outcome. Only exit 0 selects the anonymous
`mumei.native-evidence-acceptance/v1` descriptor.

An `accepted` run reports `artifact_semantics`, `claim_truth` and all
four runtime checks in `discharged_checks`: the reproduced executable
was observed once with its exit status, stdout and stderr matched to
the pins. `runtime_observation_semantics` names that one bounded
invocation; it is not an ABI, general runtime or process-semantics
claim, and `historical_execution` remains unclaimed. The remaining C02
checks stay in `checks_not_performed`. The route is also the
`native_observations_accept` MCP tool (same report production,
declared-path validation and basename redaction as the other spawn
tools). C02/C10 stay partial.

### C02/C10 declared native-observations-recheck route (native-observations-recheck)

`python -m agent native-observations-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares one invocation
recheck: `<core> native-bundle recheck-observations
--expected-build-id <id> --json <bundle> <source>` under a
`mumei.native-observations-recheck-request/v1` fingerprint binding the
Core executable, the bundle record and every declared member, the
source and the trusted-channel build ID. `observations_recheck` is
claimed only for uniquely-mapped exit codes (`0 → reproduced`,
`3 → inconclusive`); other exits claim nothing, and mid-run drift
reports `inputs_changed` without an outcome. Normalized stdout keeps
only the captured descriptor's digest and size, not its body; the route
parses the captured stdout and adds `runtime_observation_schema` only
when the descriptor names `mumei.runtime-observation/v1`. Every report outcome echoes the
declared `expected_build_id`.

A `reproduced` run reports `artifact_semantics`, `claim_truth` and all
four runtime observation checks for that one bounded invocation. It
does not claim ABI, general runtime or process semantics, or
`historical_execution`. The descriptor and recheck report are not
performers in `recovery-eval`; runtime semantics remains performed only
by the one-invocation observations acceptance. C02/C10 stay partial.

### C02/C10 declared native-check route (native-check)

`python -m agent native-check --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares the shallowest
native consumer as one attempt: `<core> native-bundle check
--expected-build-id <id> <bundle> <source>` under a
`mumei.native-check-request/v1` fingerprint binding the bundle record
plus every member it declares and the declared source. `bundle_check`
is claimed only for uniquely-mapped exit codes (`0 → consistent`);
the command has no inconclusive exit and exit 1 conflates an identity
mismatch with every static failure, so it claims nothing, mid-run
drift reports `inputs_changed` with no claimed outcome, and the drift
check re-enumerates the member set from the current record. A
`consistent` run reports `discharged_checks` — `file_identity` — with
the remaining five checks in `checks_not_performed`. The command's
stdout is a fixed diagnostic line rather than an evidence record, so
no `candidate` is emitted. The route is also the `native_check` MCP
tool (same `run_check` report production, declared-path validation
and basename redaction as the other spawn tools). C02/C10 stay
partial.

### C02/C10 declared native-source-recheck route (native-source-recheck)

`python -m agent native-source-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` declares the Stage A
native consumer as one attempt: `<core> native-bundle recheck-source
--expected-build-id <id> <bundle> <source>` under a
`mumei.native-source-recheck-request/v1` fingerprint binding the
bundle record plus every member it declares and the declared source.
`source_recheck` is claimed only for uniquely-mapped exit codes
(`0 → rechecked`, `3 → inconclusive`); exit 1 conflates a refuted
postcondition with every static failure so it claims nothing, mid-run
drift reports `inputs_changed` with no claimed outcome, and the drift
check re-enumerates the member set from the current record. A
`rechecked` run reports `discharged_checks` — `file_identity` plus
`claim_truth` (the source postcondition re-proven within the
profile) — with the remaining four checks in `checks_not_performed`.
The command's stdout is a fixed diagnostic line rather than an
evidence record, so no `candidate` is emitted. The route is also the
`native_source_recheck` MCP tool (same `run_source_recheck` report
production, declared-path validation and basename redaction as the
other spawn tools). C02/C10 stay partial.

### C02/C10 declared native-attempt route (native-attempt)

`python -m agent native-attempt --core <path> --source <path>
--bundle <dir>` declares a native bundle production as one attempt:
`<core> native-bundle build <source> -o <dir>` under a
`mumei.native-attempt-request/v1` fingerprint binding the Core
executable's bytes, the source's bytes and the declared output path.
Where verify-attempt selects on a clean exit alone (the evidence
record IS the stdout document), `native-bundle build` writes the
`mumei.native-bundle/v1` directory as a side effect — so selection
requires three post-conditions: an `exited` run with `exit_code == 0`,
a parseable `Build ID: <sha256>` line in the bounded capture, and
every member the produced record declares present — the component
files plus, for a multifile record, each `sources/<member>` (an
unparseable produced record is incomplete by definition). The
reported `build_id` is the Core-computed SHA-256 of
`native-bundle.json` — the exact identity a `native-recheck` call
pins via `--expected-build-id`. Bundle bytes are outputs: they never
enter the request fingerprint or the report. Mid-run drift reports
`inputs_changed` with no claimed `build_id`. The route is also the
`native_attempt` MCP tool (same `run_attempt` report production,
declared-path validation and basename redaction as the other spawn
tools). C02/C10 stay partial.

### C02/C10 declared native-evidence-recheck route (native-evidence-recheck)

`python -m agent native-evidence-recheck --core <path> --bundle <dir>
--source <path> --evidence <path> --expected-build-id <sha256>`
declares the saved-Evidence replay as one attempt: `<core>
native-bundle recheck-evidence --expected-build-id <id> <bundle>
<source> <evidence>` under a
`mumei.native-evidence-recheck-request/v1` fingerprint binding the
Core executable's bytes, every bundle member the record declares (the
same dynamic enumeration `native-recheck`/`native-accept` share —
component `files` plus multifile `sources/<member>`), the source's
bytes, the saved consumer-Evidence envelope's bytes (bounded at the
Core's 1 MiB `MAX_EVIDENCE_BYTES`) and the trusted-channel build ID.
`evidence_recheck` names only `0 → consistent` and
`3 → inconclusive`; exit 1 conflates a genuine saved-vs-fresh
mismatch (or an other-family envelope) with every static failure, so
the route claims nothing for it. Mid-run drift — including the saved
envelope itself, a fourth declared input — reports `inputs_changed`
with no claimed outcome. A `consistent` run reports
`discharged_checks` {`artifact_semantics`, `claim_truth`} — the fresh
recheck re-establishes them — with the remaining checks in
`checks_not_performed`. Consistency is not acceptance: the envelope's
own `acceptance` stays `not_evaluated`, and no evidence candidate is
emitted — the saved envelope is the replayed input, not a produced
artifact. The route is also the `native_evidence_recheck` MCP tool
(same `run_evidence_recheck` report production, declared-path
validation and basename redaction as the other spawn tools).
C02/C10 stay partial.

### C02/C10 declared native-evidence-accept route (native-evidence-accept)

`python -m agent native-evidence-accept --core <path> --bundle <dir>
--source <path> --evidence <path> --expected-build-id <sha256>`
declares the saved-Evidence acceptance as one attempt: `<core>
native-bundle accept-evidence --expected-build-id <id> --json
<bundle> <source> <evidence>` under a
`mumei.native-evidence-accept-request/v1` fingerprint binding the
Core executable's bytes, every bundle member the record declares (the
same dynamic enumeration `native-recheck`/`native-accept`/
`native-evidence-recheck` share — component `files` plus multifile
`sources/<member>`), the source's bytes, the saved consumer-Evidence
envelope's bytes (bounded at the Core's 1 MiB `MAX_EVIDENCE_BYTES`)
and the trusted-channel build ID. Where `native-evidence-recheck`
only reports saved-vs-fresh consistency, this route selects the
produced `mumei.native-evidence-acceptance/v1` descriptor — printed
on stdout only on a clean accepted exit — into the attempt lineage.
`acceptance` names only `0 → accepted` and `3 → inconclusive`; exit 1
conflates a rejected or non-reproducing envelope (or an other-family
decode failure) with every static failure, so the route claims
nothing for it. Mid-run drift — including the saved envelope itself,
a fourth declared input — reports `inputs_changed` with no claimed
outcome. An `accepted` run reports `discharged_checks`
{`artifact_semantics`, `claim_truth`} with the remaining checks in
`checks_not_performed`. The descriptor is anonymous by design (no
subject, digest or provenance binding), so no evidence candidate is
emitted — the captured bytes enter the lineage through the selection
itself. Acceptance is representation-level only: producer
authenticity, freshness against an external clock and runtime/OS
semantics stay outside the profile. The route is also the
`native_evidence_accept` MCP tool (same `run_evidence_accept` report
production, declared-path validation and basename redaction as the
other spawn tools). C02/C10 stay partial.

### C02 declared evidence file-identity route (evidence-identity-check)

`python -m agent evidence-identity-check --evidence <path>
--source <path>` discharges the `file_identity` duty at
representation level: it reads a declared
`mumei.verification-evidence/v1` record — fail-closed on a foreign
schema or a `subject` outside the closed `{id, kind, sha256}` shape —
and a declared source file, then emits
`mumei.evidence-file-identity/v1` comparing the record's bound
`subject.sha256` (the source digest Core binds at production) with the
sha256 of the current source bytes. `identity` is `"match"` or
`"mismatch"`; a mismatch is data, not an error — a saved record that
no longer binds the declared source answers `mismatch`, while a
malformed or oversized input (over Core's 64 KiB bound) is a static
failure. A match only means the record still binds THESE bytes: full
representation validity stays Core's `evidence check` duty, and the
other five checks (`claim_truth`, `freshness`,
`producer_authenticity`, `semantic_correspondence`,
`artifact_semantics`) stay in `checks_not_performed`. The route runs
no Core and no fresh query — it is the byte-level staleness
companion of `verify-recheck`, which discharges freshness by
re-running the source query. C02 stays partial.

### C02 declared evidence producer-identity route (evidence-producer-check)

`python -m agent evidence-producer-check --evidence <path> --tool <name>
--adapter <id> [--tool-version <v>] [--adapter-version <v>]` discharges
the `producer_authenticity` duty at representation level: it reads a
declared `mumei.verification-evidence/v1` record's `provenance` block —
fail-closed on a missing block, a foreign schema or a shape outside the
closed `adapter{id, version, protocol_version}` /
`tool{name, version}` / `configuration_fingerprint` contract — then
emits `mumei.evidence-producer-identity/v1` comparing each declared
expectation against the record's fields. `identity` is `"match"` or
`"mismatch"` with `mismatched` naming the compared fields that
differed; a mismatch is data, not an error. Versions are pinned only
when declared — an omitted `--tool-version`/`--adapter-version` is
never compared, so a host can pin identity without pinning a release.

A match only means the record DECLARES these producer values: it is
producer pinning, not cryptographic attestation — nothing proves the
named tool actually produced the record, and the other five checks
(`claim_truth`, `file_identity`, `freshness`,
`semantic_correspondence`, `artifact_semantics`) stay in
`checks_not_performed`. The route runs no Core and no fresh query.
`evidence_producer_check` is the same wiring over MCP: expectations
arrive as tool arguments (`tool_version`/`adapter_version` empty means
unpinned) and declared-path failures redact to basenames. C02 stays
partial.

### C02 declared evidence routes as MCP tools

The MCP server exposes the two spawn-free consume routes so a model can
drive them without a shell: `evidence_identity_check(evidence_path,
source_path)` returns the `mumei.evidence-file-identity/v1` descriptor
via `compute_identity_descriptor` — the same strict subject shape and
64 KiB bounded reads as the CLI route — and
`evidence_check_accept(sequence_json, check_json)` restores the two
declared documents from inline JSON (bounded to the route's 1 MiB
snapshot limit before parsing) and returns
`mumei.evidence-check-acceptance/v1` through
`evaluate_evidence_check`. Both tools keep the CLI contract verbatim:
a malformed or oversized declared input is a `status: "error"`, never
a mismatch/reject answer, and `checks_not_performed` stays verbatim.
Failure text is model-facing, so declared checkout-local paths are
redacted to basenames before returning; the inline-JSON accept tool
needs no redaction because it performs no file reads at all. Neither
tool spawns, queries Core or decides truth — a `"valid"` acceptance
still means Core's representation check passed at record time only.

The three spawn-based routes are exposed the same way, in-process:
each route file now factors its report production into a
`run_*(args) -> dict` (`run_attempt` in `verify_attempt.py`,
`run_recheck` in `verify_recheck.py` and `native_recheck.py`) that the
thin `main_*` wraps for the CLI (argparse + JSON emission), and the
MCP tools `verify_attempt`, `verify_recheck` and `native_recheck`
build the identical declared `Namespace` — solver budgets as ints
converted to the CLI's string fields, no `--output`, no
`--memory-bound` — call the `run_*` function directly, and return the
report dict under `status: "ok"`. This is the same pattern
`go_summaries` uses: the model supplies declared absolute paths and
integer budgets, the route performs its own `_check_request`
validation (absolute POSIX paths, size bounds, timeout ranges) before
dispatching, and the fingerprint still binds the executable bytes,
input bytes and budgets. Reported path-validation and budget checks
fail as `status: "error"` before any spawn; spawn failures and
declared-input errors surface through `_err` with declared paths
redacted to basenames — model-facing text never carries a
checkout-local absolute path.

### C02 declared evidence comparison route (evidence-compare)

`python -m agent evidence-compare --evidence-a <path>
--evidence-b <path>` is the record-vs-record companion of
`evidence-identity-check` (record vs current source bytes) and
`verify-recheck` (record vs a fresh Core query): it reads two
declared `mumei.verification-evidence/v1` records — the same bounded
read, the same fail-closed schema check, the same closed
`{id, kind, sha256}` subject shape, plus a required `specification`
object — and emits `mumei.evidence-comparison/v1` comparing the two
records' claim surfaces verbatim: `subject_match` (bound subject
objects equal), `specification_match` (claim objects equal) and
`claims_match` (both). A mismatch is data, not an error; a malformed,
oversized or wrong-shaped input on either side is a static failure.
The route runs no Core, no fresh query and no spawn — `claims_match`
means the two records carry the same claims, never that the claims
are true, current or authentic: the full six-entry
`checks_not_performed` vocabulary stays named. C02 stays partial.

The route is also reachable as the `evidence_compare` MCP tool: it
validates both declared paths, calls
`compute_comparison_descriptor` in-process and returns
`{status, comparison}`; declared failures surface as `_err` with
checkout-local paths basename-redacted, like the other consume
tools.

### C02 declared evidence-check route (evidence-check)

`python -m agent evidence-check --core <path> --evidence <path>` is
the consume-side companion of `verify-attempt`: it feeds a saved
`mumei.verification-evidence/v1` record's bytes to
`<core> evidence check --stdin --json` as one declared attempt.
`AttemptRunner`/`dispatch_attempt` gain a bounded `feed_bytes`
argument (at most 65536 bytes, written to the child's stdin on a
daemon feeder thread then closed — a child that exits early or never
reads surfaces `BrokenPipeError`, which is simply the observed run
outcome), so the representation check itself now carries canonical
attempt lineage instead of running as an inline Popen.

Selection requires exit 0 AND captured stdout that parses as the
Core's one accepted `mumei.evidence-representation-check/v1`
diagnostic — every rejection exits 1 with no diagnostic to bind, and
a 0 exit with unrecognised bytes binds nothing. The report
(`mumei.evidence-check-report/v1`) echoes the diagnostic's
`representation` and its own `checks_not_performed` list only on
selection — the six semantic duties the check never assesses stay
named — plus the evidence candidate; a mid-run drift of the declared
record suppresses the outcome via `inputs_changed`. The route is
also reachable as the `evidence_check` MCP tool. C02 stays partial:
this discharges the representation check as a declared consume
attempt only — `claim_truth`, `freshness` (beyond record currency),
`producer_authenticity`, `semantic_correspondence` and
`artifact_semantics` remain host/Core duties.

### C02 declared evidence-check-list route (evidence-check-list)

`python -m agent evidence-check-list --core <path> --evidence <path>`
is the multi-record companion of `evidence-check`: it feeds a saved
`mumei.verification-evidence-list/v1` envelope's bytes to
`<core> evidence check-list --stdin --json` as one declared attempt —
same bounded `feed_bytes` stdin wiring, same drift re-hash, same
compare-and-set publication.

Selection requires exit 0 AND captured stdout that parses as the
list-family `mumei.evidence-representation-check/v1` diagnostic —
`evidence_schema_version` pinned to `mumei.verification-evidence-list/v1`,
`representation: valid`, and a non-negative `record_count` lifted out
and compared field-for-field (a single-record v1 diagnostic or any
unrecognised bytes bind nothing). The report
(`mumei.evidence-check-list-report/v1`) echoes `representation`,
`record_count` and `checks_not_performed` only on selection — the
seven names now include `cross_record_consistency`, which stays
Core's `evidence check-consistency` duty — plus the evidence
candidate; mid-run drift suppresses the outcome via
`inputs_changed`. The route is also reachable as the
`evidence_check_list` MCP tool. C02 stays partial: representation
admission of a multi-record envelope, not record agreement or
acceptance.

### C02 declared evidence-check-consistency route (evidence-check-consistency)

`python -m agent evidence-check-consistency --core <path> --evidence
<path>` is the consistency companion of `evidence-check`: it feeds a
saved `mumei.verification-evidence-list/v1` envelope's bytes to
`<core> evidence check-consistency --stdin --json` as one declared
attempt — same bounded `feed_bytes` stdin wiring, same drift
re-hash, same compare-and-set publication.

Selection requires exit 0 AND captured stdout that parses as the
`mumei.evidence-consistency-check/v1` diagnostic. Both `consistent`
outcomes select — the completed check IS the contract, and Core
exits 0 whether or not conflicts were found. The validator is
stricter than shape-matching: `record_count`/`conflict_count` are
lifted and cross-checked (`consistent` must equal
`conflict_count == 0`; `conflicts` must be exactly
`min(conflict_count, 64)` well-formed
`{"index_a","index_b","field"}` entries drawn from the nine-name
comparison vocabulary), so an internally contradictory or
out-of-vocabulary diagnostic binds nothing.

The report (`mumei.evidence-check-consistency-report/v1`) echoes
`representation`, `record_count`, `consistent`, `conflict_count`,
the bounded `conflicts` list and `checks_not_performed` only on
selection — the seven names now include `pin_correctness`:
syntactic agreement on identity pins, not correctness, currency or
authenticity of the pins themselves — plus the evidence candidate;
mid-run drift suppresses the outcome via `inputs_changed`. The
route is also reachable as the `evidence_check_consistency` MCP
tool. C02 stays partial: cross-record agreement, not cross-record
truth.

All three check routes accept `--expected-adapter <id>` (and the
matching `expected_adapter` MCP tool parameter), which forwards the
Core's declared producer-identity gate from
[mumei#1074](https://github.com/mumei-lang/mumei/pull/1074): the
child must emit the gated diagnostic whose `checks_performed` ends
with `declared_producer_identity` for anything to select — the
gated and ungated diagnostic shapes are distinct accepted
documents, so a shape that does not match the declared request
binds nothing. The expectation joins the attempt fingerprint only
when given, keeping ungated request identities stable, and the
report lifts `checks_performed` alongside `checks_not_performed`
on selection. The gate asserts the declared `provenance.adapter.id`
match only — `producer_authenticity` remains not_performed:
identity is what the record says, authenticity is whether it is
true.

### C11 declared stream identity and completeness

`AttemptOutput` declares the collection boundary of its snapshot with two
optional metadata fields: `stream` names the declared stream the captured
bytes came from (the `STREAM_KINDS` vocabulary supports only `"stdout"`
today — other stream names are rejected outright rather than aliased), and
`complete` is an exact `bool` declaring whether the capture is the whole
stream. `AttemptOutput.from_prepared` accepts both as keyword arguments.
`reconcile` compares the claims too, so identical bytes carrying different
stream or completeness claims conflict instead of silently merging. The
`mumei.verifier-output/v1` manifest emits `stream`/`complete` only when
non-default, keeping default declarations' `output_fingerprint` unchanged.

```python
from agent.verification_attempt import AttemptOutput

output = AttemptOutput(
    exited_record, captured, sha256_of_captured,
    stream="stdout", complete=False,
)
assert output.to_dict()["stdout"]["complete"] is False
```

Both fields are **host declarations, not proven observations**: a declared
`complete=True` does not establish completeness and `False` does not measure
what was missed — only the SHA-256 binds the captured bytes. No streams are
read, pipes are opened or truncation is detected; capture mechanics, the
producer's true byte count and multi-stream capture remain host duties. No
I/O, clocks, plugins, runner/scheduler, Evidence normalization/acceptance,
external verifier, dependency or default audit/CLI/MCP route is added. C11
stays partial; Core meaning and acceptance, C12's demand gate and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 declared execution and cancellation requests

`AttemptSequence.request_execution()` returns an `AttemptExecutionRequest`
value declaring which reserved record a host intends to run next: the request
binding (request fingerprint, attempt number, declared timeout) is taken from
the current record, and only a `ready` current record can produce one — no
reserved attempt, an already-started, cancelling or terminal record, and a
sequence closed by a selected result all fail with a static error.
`AttemptSequence.request_cancellation()` likewise returns an
`AttemptCancelRequest` for the running current record only, so a cancellation
intent cannot be declared for nothing running or twice (a `cancelling` record
already carries the intent). Both values serialize as detached metadata under
`mumei.verifier-attempt-execution/v1` and `mumei.verifier-attempt-cancel/v1`
— no source, stdout, environment or process state is carried.

```python
from agent.verification_attempt import AttemptEvent, AttemptSequence

sequence = AttemptSequence.from_prepared(prepared).begin_attempt()
execution = sequence.request_execution()
sequence = sequence.reconcile_report(
    sequence.current.record(AttemptEvent("started", 0))
)
cancellation = sequence.request_cancellation()
assert cancellation.attempt_number == execution.attempt_number
```

These are **declarations of intent only**: producing a request never spawns
a process, signals a running one, delivers anything to a runner, reserves
resources or confirms an outcome — dispatch, delivery integrity, process
control and observation of the start/stop remain host duties. Both calls are
pure: the sequence is unchanged, and a request bound to a stale sequence
value is just a stale description the host must discard. No I/O, clocks,
plugins, runner/scheduler, stream collection, Evidence
normalization/acceptance, external verifier, dependency or default
audit/CLI/MCP route is added. C11 stays partial; Core meaning and acceptance,
C12's demand gate and existing assurance/Lean/native/LLVM/deferred-WASM
policies are unchanged.

### C11 ready-record withdrawal

`AttemptSequence.withdraw_attempt()` records a host's decision not to run the
reserved-but-never-started current attempt: the `ready` record is extended
with a terminal `cancelled` event at elapsed zero. The direct
`ready → cancelled` transition is shared lineage vocabulary — a host report
carrying the same event reconciles to an identical sequence — so withdrawal
is not a special state, only the declared counterpart of an observation the
lifecycle already admits.

```python
from agent.verification_attempt import AttemptSequence

sequence = AttemptSequence.from_prepared(prepared).begin_attempt()
withdrawn = sequence.withdraw_attempt()
assert withdrawn.current.state == "cancelled"
assert withdrawn.next_dispatch() is None
assert withdrawn.begin_attempt().current.attempt_number == 2
```

Only a `ready` current record can be withdrawn: a running attempt still goes
through `request_cancellation` (signal delivery and stop confirmation remain
host duties), a terminal record is already finished, an empty sequence has
nothing to withdraw and a sequence closed by a selected result fails
statically. Withdrawal is intent **and** outcome collapsed into one
declaration — there is no process to signal — but it is still not a crash,
timeout, Evidence verdict or authorization: the next attempt needs an
explicit `begin_attempt`. No I/O, clocks, plugins, runner/scheduler, stream
collection, Evidence normalization/acceptance, external verifier, dependency
or default audit/CLI/MCP route is added. C11 stays partial; Core meaning and
acceptance are unchanged.

### C11 monotonic report stamps for replay detection

`AttemptSequence.reconcile_report` accepts an optional `report_stamp`: a
host-declared monotonic counter bound to the lineage's report stream. A stamp
must be an exact positive `int` within the bounded counter range. Once a stamp
is accepted, every later report must carry one; unstamped calls keep the
earlier behavior while the lineage has no stamp. The sequence retains the
last accepted stamp and serializes it as detached `report_stamp` metadata
under the existing `mumei.verifier-attempt-sequence/v1` schema — no report
content, source or stdout is retained.

```python
from agent.verification_attempt import AttemptEvent, AttemptSequence

sequence = AttemptSequence.from_prepared(prepared).begin_attempt()
reported = sequence.current.record(AttemptEvent("started", 0))
sequence = sequence.reconcile_report(reported, report_stamp=1)
reported = reported.record(AttemptEvent("exited", 3, 0))
sequence = sequence.reconcile_report(reported, report_stamp=2)
assert sequence.report_stamp == 2
```

A stamp must strictly increase across **distinct** deliveries: a smaller
stamp fails as stale, and reusing the last stamp only reconciles an identical
report — a reused stamp on changed content fails as stale too. A fresh stamp
on identical content still advances the counter, so replays delivered after
newer reports are detected. Stamps are delivery counters, not clocks: gaps
are allowed and no ordering between independent sequences is implied.
`begin_attempt`, `select_result` and existing idempotent reconciliations keep
the counter, and `AttemptSequenceStore` lineage updates may never regress it.

This is a replay/reorder **detection** contract, not a clock, freshness
proof, authentication or authorization: a host assigns stamps itself, so a
host can always mint a higher one. Delivery integrity, sender identity,
durable storage, global counters across lineages and acceptance of any
content remain host duties. No I/O, clocks, plugins, runner/scheduler, stream
collection, execution/cancellation, Evidence normalization/acceptance,
external verifier, dependency or default audit/CLI/MCP route is added.
C11/C13 stay partial; Core meaning and acceptance, C12's demand gate and
existing assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 atomic canonical-lineage publication

`AttemptSequenceStore` is an opt-in **in-process** compare-and-set publication
point for one canonical `AttemptSequence` lineage — the atomic storage hosts
were previously told to own. `publish(sequence)` stores the first canonical
value; `compare_and_set(expected, updated)` atomically swaps the stored value
when `expected` equals it. A mismatch means a competing writer already moved
the lineage and raises a static error without changing anything, so two
callers extending the same prefix can no longer silently fork. Equal updates
and re-publications are idempotent no-ops, not freshness or authentication.

```python
from agent.verification_attempt import AttemptSequenceStore

store = AttemptSequenceStore()
store.publish(sequence)
stored = store.current
following = stored.reconcile_report(reported)  # Or begin/select transitions.
store.compare_and_set(stored, following)       # Atomic check + publish.
assert store.current is following
```

An update must be a **lineage extension** of the expected value: same request
fingerprint and timeout, every retained record equal or a valid same-attempt
report extension, and no change after a selected result (a closed lineage
accepts only the identical value). Removed, replaced, rewound, rebound or
diverged updates are rejected. Any number of valid transitions may be batched
between one `expected`/`updated` pair; the store neither replays operations
nor infers them.

The store holds immutable values only — never source bytes, stdout bodies,
plans or diagnostics — and has no serialization surface of its own. It
linearizes callers on **this object**: it is not durable storage, a
cross-process/OS lock, a replay-protected boundary or an authenticated
channel. Stale `expected` values are detected by equality, not freshness
proof; hosts still own distribution, crash recovery and any cross-attempt/
backend arbitration. No runner/scheduler, stream collection, execution/
cancellation, Evidence normalization/acceptance, external verifier,
dependency or default audit/CLI/MCP route is added. C11/C13 stay partial;
Core meaning and acceptance, C12's demand gate and existing assurance/Lean/
native/LLVM/deferred-WASM policies are unchanged.

### C11 declared lineage restoration

`AttemptEvent.from_dict`, `AttemptRecord.from_dict` and
`AttemptSequence.from_dict` rebuild the declared
`mumei.verifier-attempt-sequence/v1` (and nested
`mumei.verifier-attempt/v1`) snapshots a host persisted, letting a host
reinstate its own canonical lineage after a restart without trusting the
bytes: unknown or missing keys, a foreign `schema_version`, malformed
members and a record's declared `state` disagreeing with its replayed
events are static errors, and every constructor invariant — record
bindings, ordinals, terminal predecessors, the selected-result reference,
the report stamp — is re-checked, not recovered.

```python
from agent.verification_attempt import AttemptSequence

restored = AttemptSequence.from_dict(persisted_snapshot)
```

A restored `selected_result` still names a declared fingerprint the
snapshot cannot re-bind to bytes, and a record's restored events are the
same host reports they were before persistence — restoration changes
nothing about their provenance. Durability itself, canonical-store
ownership, distribution, crash recovery and Evidence remain host duties:
this is a parse boundary, not a trust boundary. No runner/scheduler,
stream collection, execution/cancellation, Evidence normalization/
acceptance, external verifier, dependency or default audit/CLI/MCP route
is added. C11 stays partial; Core meaning and acceptance, C12's demand
gate and existing assurance/Lean/native/LLVM/deferred-WASM policies are
unchanged.

### C11 durable canonical-lineage publication

`FileAttemptSequenceStore` is an opt-in **file-backed** publication point
with the same contract as `AttemptSequenceStore` — `publish` is
first-wins and `compare_and_set` only accepts lineage extensions — but the
canonical value persists as `mumei.verifier-attempt-sequence/v1` JSON so a
host reinstates its own lineage across restarts through the same declared
parse boundary `AttemptSequence.from_dict` enforces. A sibling
`<path>.lock` serializes writers on the same host (`fcntl.flock` on POSIX;
a process-local lock shared per lock path elsewhere, so same-process
instances still exclude each other) and writes are atomic — a temp file in
the same directory plus `os.replace` followed by a directory fsync, so the
rename itself survives a power loss — and a crash mid-write cannot leave a
partial snapshot. A missing file reads as unpublished; a malformed or
foreign-schema one fails closed.

The `attempt_runner` publish helpers (`publish_dispatch`,
`dispatch_and_publish`) accept only the in-process `AttemptSequenceStore`
by strict type check, so wiring durable publication into the execution
flow needs a host-side publish step — that integration is out of scope
here.

```python
from agent.verification_attempt import FileAttemptSequenceStore

store = FileAttemptSequenceStore("/var/lib/mumei/canonical.json")
canonical = store.publish(sequence)            # first publication wins
canonical = store.compare_and_set(expected, updated)  # lineage extension only
```

It remains **the host's canonical value, not the canonical store**: which
file is canonical, locking across hosts, freshness, authentication,
backup/rotation and every result/Evidence decision stay host duties, and
the store still holds values only — never source or stdout bodies. No
runner/scheduler, stream collection, execution/cancellation, Evidence
normalization/acceptance, external verifier, dependency or default
audit/CLI/MCP route is added. C11 stays partial; Core meaning and
acceptance, C12's demand gate and existing assurance/Lean/native/LLVM/
deferred-WASM policies are unchanged.

### C11 cross-lineage reconciliation

`AttemptSequence.reconcile(incoming)` arbitrates between the value a host
holds and an independently-published candidate for the same request. Two
callers that each extended an older common prefix can diverge — atomic
publication serializes writes, not the histories behind them — so the
declared arbitration is lineage order only: an identical or prefix-shorter
candidate keeps the current value, a strict extension returns the
candidate, and every true fork fails closed.

```python
canonical = sequence.reconcile(published_candidate)
```

Divergent records at a shared ordinal, competing selected results and
foreign request bindings all raise static errors, and so does a candidate
that both diverges and regresses the report stamp; a candidate that only
carries an older stamp on an identical history is stale and loses silently.
Neither input is mutated. This arbitrates between VALUES only — which
side was the canonical store's own value, authority, freshness and
authentication stay host duties, and a fork still needs a human or a
host-declared rule to pick a winner. No runner/scheduler, stream
collection, execution/cancellation, Evidence normalization/acceptance,
external verifier, dependency or default audit/CLI/MCP route is added.
C11 stays partial; Core meaning and acceptance, C12's demand gate and
existing assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 canonical result selection for sequential attempts

`AttemptSequence.select_result(output)` declares one bound `AttemptOutput` the
canonical result of **the current record only**, closing the sequence. The
output must be an exact `AttemptOutput` satisfying the existing
`check_output_binding` precondition against the sequence's current record —
same request fingerprint, ordinal, timeout and complete event history — and
that record must be `exited`. Selection binds the exit observation, not a
Core check: an `exited` record with any reported exit code can be selected.
Exit code zero is transport metadata, never verification success.

```python
from agent.verification_attempt import AttemptOutput, AttemptSequence

sequence = AttemptSequence.from_prepared(prepared).begin_attempt()
reported = sequence.current.record(AttemptEvent("started", 0))
reported = reported.record(AttemptEvent("exited", 3, 0))
sequence = sequence.reconcile_report(reported)
output = AttemptOutput.from_prepared(
    prepared, 1, reported, stdout_bytes, expected_stdout_sha256
)
sequence = sequence.select_result(output)
assert sequence.select_result(output) is sequence  # Same marker: idempotent.
```

A selected sequence rejects `begin_attempt()` and every different output with
static errors; re-selecting the same output is a no-op returning the same
object. The selected marker is the immutable `(attempt_number,
output_fingerprint)` pair — detached metadata, not a copy of stdout, a
diagnostic or a receipt. `to_dict()` adds a matching `selected_result` entry
under the existing `mumei.verifier-attempt-sequence/v1` schema; it retains no
raw bytes, source, plan or diagnostics.

This is **host-declared canonical metadata for this sequence value only** —
not truth, verification acceptance, a Core representation-check receipt or
cross-sequence arbitration. Two independently captured snapshots bound to the
same attempt both satisfy binding; the first selection wins on this value and
the host must still detect conflicting captures with `AttemptOutput.reconcile`
and host-owned atomic storage. Independent sequence values can still select
independent results; there is no global ordering, locking/CAS, replay
protection or freshness claim. A selection does not revalidate the output,
run Core, or mutate the output/record; serializers stay body-free.

No parsing, I/O, clocks, plugins, external verifier, dependency or default
audit/CLI/MCP route is added. Runner/scheduler, stream collection, Evidence
normalization/acceptance, cross-attempt/backend arbitration and actual
execution/cancellation remain open. C11/C13 stay partial; Core meaning and
acceptance, C12's demand gate, and existing assurance/Lean/native/LLVM/
deferred-WASM policies are unchanged.

### C11 explicit local Core representation handoff

`agent.core_evidence.check_evidence_representation` is an opt-in **POSIX-only**
local Core invocation, not a general adapter runner. The host must independently
authorize this process and choose a trusted absolute executable path; adapter
permission declarations, prepared requests and stored fingerprints do not grant
that authority. Path syntax does not authenticate the binary or prevent replacement.
The API neither discovers a binary through PATH/environment nor accepts a command
prefix, shell, arbitrary flags, container or remote endpoint.

```python
from agent.core_evidence import check_evidence_representation

# The host first reconciles and retains its canonical attempt/output lineage.
check_evidence_representation(
    output, core_executable=trusted_core_path, timeout_ms=1000,
    attempt_sequence=sequence,  # Optional explicit current-record precondition.
)
# Normal return means representation-valid only, never proof or acceptance.
```

The optional `attempt_sequence` requires an exact `AttemptSequence` value and
calls its `check_output_binding(output)` before any Core process/I/O. An exact
`AttemptOutput` must match the supplied sequence's current record in request
fingerprint, ordinal, timeout and complete event history. Empty sequences,
unreconciled/non-exited current records, old/future outputs, different bindings
or terminal histories fail with fixed, body-free errors. Equal metadata copies
are allowed; object identity and exit code zero are not required. Omitting the
argument or passing `None` preserves the earlier sequence-independent API.

This compares only the two supplied immutable values. Reconcile/retain the
host's canonical sequence first; a stale sequence can still match a stale output.
The check neither reads/decodes stdout nor reconciles/selects competing bodies:
different stdout snapshots with the same current attempt each pass binding.
Use `AttemptOutput.reconcile()` and host-owned atomic storage to detect conflicts.
There is no global freshness/replay protection, lock/CAS, completion-time
revalidation, result winner, process cleanup proof or Evidence/request-contract
matching. Hosts arbitrate concurrent updates and publication after the call.
The helper returns `None`, not authority, a receipt or acceptance; schemas and
default routes are unchanged.

Exactly the original `AttemptOutput.stdout` bytes are sent to fixed
`evidence check --stdin --json`, without a decoded-tree round trip or temporary
file. The Core subprocess receives an empty environment. Caller environment,
credentials and TRACEPARENT are not forwarded; no telemetry or child output is
published. The executable must run in that environment: there is no cargo/MCP/
legacy-client fallback. Synthetic test executables stand in for a trusted Core
only in tests, not as independent validators of Evidence meaning.

The caller separately specifies a strict integer timeout of 1–60,000 ms; the
adapter's historical timeout is not reused. Nonblocking concurrent pipe I/O avoids
stdin/stdout/stderr backpressure deadlocks. Each diagnostic stream is limited to
4,096 bytes plus one overflow-detection byte, with no oversized stream drain.
The deadline includes I/O and child exit; OS process creation is not interruptible.
Failure/interrupt cleanup closes pipes and kills/reaps the direct child with up
to one additional second; it does not claim descendant cleanup or an OS sandbox.
This is a small trusted-Core process boundary, not arbitrary plugin lifecycle,
resource/authority enforcement, memory/CPU limiting or Windows support.

The optional `cancel_event` accepts only a standard `threading.Event` (not a
subclass or callback). The host owns it and keeps it set until the call returns.
An already-set event prevents process creation. With an event supplied, pipe
and child-exit waits use at most 50 ms polling intervals without resetting the
original deadline. Observed cancellation closes pipes and kills/reaps the direct
child, then raises `CoreCheckCancelled` with a fixed, body-free message instead
of returning a representation result. Cleanup failures remain check failures.
Without an event, existing calls keep their original deadline-sized waits.

This is cooperative cancellation of this one Core invocation, not preemptive
interruption of process creation, a hard real-time response guarantee or
descendant cleanup. Checks also occur before diagnostic decoding and normal
return; a signal after the last check can race with completion. A set/clear pulse
between checks may be missed, so do not clear/reuse an event during the call.
The API never sets/clears the event, creates an attempt cancellation report,
mutates an existing attempt/output, or turns host lifecycle metadata into an
authenticated Core receipt.
The host separately reconciles its canonical lineage and completion/cancel race.

Code zero alone, empty output, any stderr, malformed/duplicate/extra diagnostics,
unsupported diagnostic/schema versions, timeouts and I/O failures fail closed.
The complete diagnostic must match the known v1 representation-only shape,
including `acceptance: not_evaluated` and all six `checks_not_performed` entries.
JSON key order/whitespace and equivalent string escapes are immaterial.
Check failures expose fixed errors,
not commands, private bytes, child diagnostics, paths or underlying exceptions.

The API returns `None`, not Evidence, a cached receipt or a new assurance record,
and does not mutate the snapshot or its attempt. Even normal return depends on
the host-trusted executable: the anonymous diagnostic is not authenticated or
bound to this input by itself. Stored result truth, request/result-contract
matching, freshness, authenticity, correspondence and Core Evidence acceptance
remain unassessed. No new verifier, automatic audit/CLI/MCP route or grade
promotion is added. General adapter execution/stream collection and normalization
remain open; C11 is partial, C12 demand-gated, and existing assurance/Lean/native/
LLVM/deferred-WASM policies unchanged.

### C11 original-byte Core stdin handoff entry point

Core exposes explicit `mumei evidence check --stdin [--json]` so an authorized
host can supply original `.stdout` bytes without writing a temporary input file
or reserializing `decode_json_object()` results. It checks one common Evidence
record using Core's existing representation decoder, not Agent-owned schema
rules. A JSON transport object can still fail Core shape/combination checks;
representation-valid counterexamples/unknown/timeout results are not verification
success. Its anonymous diagnostic keeps acceptance `not_evaluated` and is not an
acceptance receipt, proof of a Core run or binding to an Agent request/attempt.

Explicit stdin and file input are mutually exclusive; absent input does not
silently select stdin, and a positional `-` remains a literal file. The existing
65,536-byte limit applies, with at most one extra byte read for overflow detection
and no oversized-stream drain. Byte bounds do not enforce a deadline: the host
must close input, enforce timeouts/cancellation and handle early reader closure.
Input/decoder/I/O errors do not quote the private body or underlying errors.
The interface consumes raw UTF-8 bytes from pipes/redirected files, not terminal
text requiring encoding conversion (including Windows console code pages).

This Core entry point does not automatically wire an Agent call. The separate
opt-in local handoff above uses it, without adding a general adapter runner,
stream capture, normalization, request/result matching, authority enforcement,
acceptance or grade promotion. Full C11 and Core-owned acceptance remain open; C12's
demand gate and existing assurance/Lean/native/LLVM/deferred-WASM policies stay
unchanged. See the
[canonical stdin milestone](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md#wave-2-original-byte-core-stdin-representation-checks).

### C11 bounded JSON stdout decoding

`AttemptOutput.decode_json_object()` is explicit access to the private body,
limited to a single UTF-8 JSON object. It rejects duplicate decoded keys at any
depth, prefixes/trailing output, BOM/other encodings, malformed syntax, non-JSON
numeric constants and unpaired surrogate escapes. Key spelling is not Unicode
normalized. Nesting (objects and arrays, including the root) is bounded to 32
before invoking the JSON parser; numeric literals are at most 128 characters,
including sign/exponent, and decimal exponents must be representable by Python's
`Decimal`. The existing 65,536-byte snapshot limit remains unchanged.

Integer values use exact `int`; fractional/exponent values use finite exact
`Decimal`, not rounded binary floats. Parsing does not change the caller's
decimal context. Each call returns a fresh mutable tree; edits do not change the
snapshot, its raw-byte identity, metadata or future decodes. The tree is private
untrusted data and **must not be logged**. Returned values are not a canonical
serialization or Core Evidence: downstream Core checks must consume the original
`.stdout` bytes, not a reserialization of this tree. Syntax/encoding/bound errors
raise one static message without the underlying decoder exception/context.

An empty object or an object claiming success can decode without satisfying any
Evidence schema or meaning. No schema/method/profile/result-contract matching,
normalization, path following, process/stream collection, authority check or
acceptance/grade promotion is performed. Opaque snapshot construction, lifecycle
and output reconciliation, repr/manifest and default audit/CLI/MCP behavior are
unchanged. Core owns Evidence checks/acceptance; adapter normalization, actual
execution and full C11 remain open, with C12 still demand-gated and existing
assurance/Lean/native/LLVM/deferred-WASM policies unchanged.

### C11 bounded opaque stdout snapshots

`AttemptOutput` adds an opt-in, in-memory preparation boundary for **host-supplied
stdout bytes**, not a stream collector or Evidence parser. The record must be
exactly an `AttemptRecord` in `exited` state (including a reported exit before its
deadline); failed, timed-out, cancelled and incomplete histories are rejected.
Zero and nonzero exit codes are both transport metadata, never verification
success. Exact immutable bytes of length 0 through 65,536 are accepted only when
their raw SHA-256 matches a separately supplied lowercase digest. Oversized input
is rejected before hashing, never truncated. Empty, binary, invalid JSON and even
stored success claims remain uninterpreted bytes, **not well-formed Evidence**.

```python
from agent.verification_attempt import AttemptOutput

current = current.reconcile(reported_exit)
output = AttemptOutput.from_prepared(
    prepared, 1, current, stdout_bytes, expected_stdout_sha256
)
assert output.reconcile(output) is output
```

The helper checks the separately specified attempt number, prepared-request
fingerprint and selected timeout, and requires the existing explicit permission
policy. Direct construction checks the exited record/body/digest only; it does
not independently bind a prepared request. Neither path checks the live registry
or grants authority. Reconcile the host's retained current attempt first: binding
against a prepared request alone cannot detect an independently forked history.

`repr` omits stdout; `to_dict()` emits only detached `mumei.verifier-output/v1`
metadata: the full attempt manifest, stdout size/digest and a canonical SHA-256
over that metadata (excluding the fingerprint itself). No source/plan, stderr,
command, diagnostic or raw stdout is emitted. The snapshot retains stdout for
explicit downstream access; reflection such as `dataclasses.asdict`, inspecting
locals or accessing `.stdout` is **not redacted** and must not be logged. Digests
are identity metadata, not secret detectors, authorization or declassification.

`output.reconcile(incoming)` keeps the current object only for an exact duplicate
snapshot. A different attempt binding, terminal event payload/history or raw
stdout fails with static errors, even if size/exit code agree. It does not pick a
winner, atomically publish updates or prevent independently captured conflicting
snapshots. Hosts own the canonical output record, attempt identity and atomic
storage. Duplicate acceptance is not freshness/authentication/replay protection.

This helper performs no parsing, file/network/process/clock/plugin operations.
The caller-supplied digest does not prove stream completeness, provenance or
delivery timing. Real stream limits/collection, timeout/cancel cleanup, authority
and resource enforcement, cross-attempt/backend arbitration, adapter result
normalization and Core-owned common Evidence checks/acceptance remain open.
No default audit/CLI/MCP path or
external verifier is added; C11 is partial, C12 remains demand-gated and existing
assurance/Lean/native/LLVM/deferred-WASM policies are unchanged.

### C11 bounded sequential attempt records

`AttemptSequence` is an opt-in immutable ledger value for **one prepared request**,
not a retry runner or a result-selection policy. `from_prepared(prepared)` requires
the same explicit permission metadata as `AttemptRecord.from_prepared` and starts
empty. Direct construction checks representation only; neither form grants
authority or proves freshness. All records retain the same request fingerprint
and selected per-attempt timeout. A different plan/settings/timeout needs a new
prepared request and separate sequence, not weakened binding or fallback reuse.

`begin_attempt()` reserves the next `ready` record numbered contiguously from 1,
up to a fixed **16 attempts**. It fails while the current record is nonterminal
or at capacity, without truncation, renumbering or mutation. Constructor checks
also reject gaps, duplicates, reordering, mixed bindings and nonterminal
predecessors. Exact tuple/record types exclude custom mutable subclass behavior.
`current` is the last reserved record (or `None`), **not a verification winner**.

```python
from agent.verification_attempt import AttemptEvent, AttemptSequence

sequence = AttemptSequence.from_prepared(prepared).begin_attempt()
reported = sequence.current.record(AttemptEvent("started", 0))
reported = reported.record(AttemptEvent("failed", 3))
sequence = sequence.reconcile_report(reported)
sequence = sequence.begin_attempt()  # Reserves metadata only; no process starts.
assert sequence.current.attempt_number == 2
assert sequence.reconcile_report(reported) is sequence  # Old terminal duplicate.
```

`reconcile_report(report)` uses existing same-attempt prefix reconciliation for
an already reserved ordinal. Unknown ordinals cannot create attempts. Exact
duplicates, including old terminal reports, return the current sequence unchanged;
rewinds, branches, changed timeout/identity and terminal replacements fail with
static errors. It never attaches a report to the newest attempt implicitly.
The metadata-only `mumei.verifier-attempt-sequence/v1` dictionary contains the
request fingerprint, timeout and ordered existing attempt dictionaries; no
source, stdout, diagnostics, success/acceptance/grade or result is retained.
Existing attempt/output serialization and explicit Core-call behavior are unchanged.

This is bounded **local logical ordering**, not global identity allocation,
locking/CAS/durable publication, report authentication/freshness/replay protection
or cross-attempt/backend result arbitration. Hosts must retain and atomically
advance their canonical sequence; independent values can still fork. A terminal
timeout/cancel/failure/exit report does **not** prove a process stopped or that
physical execution cannot overlap: cleanup and authorization remain host duties.
Elapsed counters reset for each record; no wall clock, total retry deadline,
backoff, retry eligibility or aggregate resource budget is enforced. Code zero
does not stop retries or establish success. Existing outputs are not invalidated,
selected or made canonical by reserving a new attempt; hosts still own their
output lineage. There is no stream collection, runner/scheduler, Evidence
normalization/acceptance, new external verifier/dependency, or default
audit/CLI/MCP route. C11/C13 remain partial, Core meaning/acceptance, C12's demand
gate and existing assurance/Lean/native/LLVM/deferred-WASM policies unchanged.

### C11 same-attempt report reconciliation

`AttemptRecord.reconcile(incoming)` compares a host-reported snapshot to the
caller's current immutable record. It accepts only an exact `AttemptRecord`
with the same request fingerprint, attempt number and timeout, whose events
contain the complete current event tuple as an exact prefix. Identical reports
return the current object; a proper extension returns the incoming object.
Either result retains the existing `mumei.verifier-attempt/v1` serialization.
Reports can advance over multiple observations only when the incoming snapshot
already contains the complete, valid bounded history; events are never inferred.

```python
current = AttemptRecord.from_prepared(prepared, 1)
reported = current.record(AttemptEvent("started", 0))
current = current.reconcile(reported)
assert current.reconcile(reported) is current
```

Shorter/stale histories, changed elapsed counters/exit codes, divergent branches,
terminal replacements and mismatched binding fields fail with static errors.
Neither input changes on success or failure. A cancel/exit disagreement is not
resolved by preferring code zero, a later elapsed counter or report arrival order;
it is rejected against the current lineage. The caller must retain that current
record, atomically publish any returned replacement and surface conflicts. This
helper does not maintain a global ledger or arbitrate which independent branch
was true; two callers starting from an older common prefix can still diverge.

Exact duplicate reports are intentionally idempotent, **not fresh/authenticated
observations or replay protection**. Fingerprints and attempt numbers remain
untrusted metadata rather than authority tokens. Global identity allocation,
durable/atomic storage, cross-attempt/backend result reconciliation, actual
execution/cancellation/cleanup/resource enforcement and output/Evidence
normalization/acceptance remain open. No parsing, I/O, clocks, plugins, new
schema/dependency or default audit/CLI/MCP integration is added. This remains a
partial C11/C13 lifecycle contract; Core meaning/acceptance, C12's demand gate,
existing assurance/Lean/native/LLVM behavior and deferred WASM are unchanged.

### C11 bounded host-observed attempt lifecycle

The opt-in `agent.verification_attempt` module provides `AttemptRecord` and
`AttemptEvent` for a bounded **host-reported observation contract**, not a runner
or alternative Evidence format. `AttemptRecord.from_prepared(prepared, n)` binds
the prepared manifest fingerprint and selected timeout to a host-assigned
positive attempt number. The helper requires an explicit permission policy;
it does not establish authority, current registry state or observation freshness.
The record retains no source bytes, plan, commands, stdout/stderr or free-text
diagnostics. Fingerprints/numbers are identifiers, not authorization/replay tokens.

| Current state | Accepted next observations |
| --- | --- |
| `ready` | `started` → `running` |
| `running` | `cancel_requested` → `cancelling`; `exited`, `failed`, `timed_out` |
| `cancelling` | `exited`, `failed`, `timed_out`, `cancelled` |
| `exited`, `failed`, `timed_out`, `cancelled` | None |

Histories are immutable, validated at construction and on append, with at most
three events. Strings, event tuples and integers require exact primitive types,
not subclasses with mutable/custom behavior. The recorded start defines elapsed zero; subsequent host-reported
millisecond counters must be nonnegative and monotonic. Exit observations must
precede the declared deadline; timeout observations must reach it. Failure or
cancellation acknowledgement may be recorded after the deadline without becoming
success. Only `exited` carries an integer exit code, and **zero does not mean
verified, proved or accepted**. Counters/attempt numbers use bounded signed-i64
nonnegative/positive ranges; exit codes use the full signed-i64 range.

```python
from agent.verification_attempt import AttemptEvent, AttemptRecord

attempt = AttemptRecord.from_prepared(prepared, 1)
running = attempt.record(AttemptEvent("started", 0))
pending = running.record(AttemptEvent("cancel_requested", 5))
assert not pending.is_terminal
cancelled = pending.record(AttemptEvent("cancelled", 6))
```

The API records a reported cancellation request/acknowledgement; it does not send
signals or prove that a process stopped. A timeout record does not prove cleanup
or resource enforcement. No clock is read, so missing host reports cannot be
detected and timeouts do not fire automatically. A cancellation/exit race can be
represented as `exited` before the deadline; it cannot rewrite an existing
terminal record. Incomplete `ready`/`running`/`cancelling` histories remain
nonterminal. Same-attempt snapshots now have explicit prefix-only reconciliation
above. Independent branches may still conflict: host attempt-number uniqueness,
cross-attempt/backend arbitration/replay protection, final preflight/authority checks,
actual execution/cancellation/cleanup/resource enforcement, output collection and
Evidence normalization/acceptance are still open for execution
outcomes beyond the declared checks the attempt routes already fold
(`evidence_check`/`acceptance` on the summaries routes, and Core
`mumei evidence accept` verdicts for declared-requirement docs).
Pre-start cancellation has since landed as `ready → cancelled` via
`AttemptSequence.withdraw_attempt()` above; the retry/fallback scheduler
(`run_attempt_schedule`), the `verify-schedule` CLI route, the
`verify_schedule` MCP tool and `audit --enable-scheduled-verification`
integration have since landed.
This is partial C11/C13, with Core meaning/acceptance, C12's demand gate, existing
assurance/Lean/native/LLVM behavior and deferred WASM unchanged. No external
verifier, dependency, file/environment/network access or plugin loading is added.

### C04/C11 declared permission-policy filtering

The opt-in planner accepts `AdapterDescriptor.required_permissions` and
`PlannerPolicy.allowed_permissions` as closed, immutable sets of coarse planning
categories: `filesystem.read`, `filesystem.write`, `environment.read`,
`network.connect` and `process.spawn`. These are host-reviewed declarations, not
capability tokens, paths/endpoints, Mumei effects or an OS permission model.
There are no wildcards, inheritance, implied rights or free-text channels.

An explicit policy excludes adapters with missing declarations
(`permission_requirements_not_declared`) or requirements outside the allowed
set (`permissions_not_allowed`). An empty allowed set denies every nonempty
declaration; an explicitly empty requirement set may still match. Priority and
explicit selection cannot bypass the filter; permitted preflight fallback must
meet the same policy, full result contract, input format and other filters using
its own declaration/settings. Invalid metadata fails before selection or hashing.

`None` is intentionally distinct from an empty set: an omitted policy keeps the
legacy planning/JSON behavior, without asserting that no permissions are needed
or implicitly approving execution. Explicit policies and selected requirements
appear as sorted arrays in plan JSON. Selected configuration fingerprints bind
the declared requirements when a settings schema is present; prepared-source
manifest fingerprints also bind the allowed policy. Changing the registry
declaration requires a fresh plan before source preparation.

```python
descriptor = AdapterDescriptor(
    "user.adapter", "1.0.0", approved_profiles, approved_methods,
    required_permissions=frozenset({"process.spawn"}),
)
policy = PlannerPolicy(allowed_permissions=frozenset())
# This policy excludes the descriptor; explicit selection cannot override it.
```

This is partial C04/C11 pre-execution policy matching and C13 regression
coverage, **not authorization or enforcement**. Declarations may be false or
incomplete: the planner does not inspect adapter code, derive actual privileges
from an execution location, authenticate a user/admin grant, or sandbox anything.
Even a matching plan/prepared request is not an execution or data-egress permit.
Future executors must independently establish authority, current preflight and
actual resource/I/O/process/network enforcement. No file/environment reads,
secret transport, tool/plugin probing/loading, process execution/cancellation,
runtime fallback/reconciliation or default CLI/MCP/audit integration is added.
Core retains specification meaning and Evidence acceptance; C12's demand-gated
real-authority mapping, all assurance/Lean/native/LLVM policies and deferred WASM
remain unchanged. No external verifier is adopted.

### C04/C11 bounded source-input preparation

The opt-in planner can now require an explicit `RouteRequirements.input_format`
against `AdapterDescriptor.input_formats`. Missing declarations are not wildcards:
`input_format_not_declared` and `unsupported_input_format` explain exclusions.
Existing priority, explicit selection, permitted fallback, exact result contract,
settings, location/version/availability filters and budgets remain in force.
Unconstrained legacy request/selected JSON gains no format field.

`AdapterRegistry.prepare_source` is a separate in-memory preparation API. It
requires `mumei.source-text/v1` plus an explicit exact result contract and calls
the current registry planner itself, rather than consuming a saved plan. An
eligible selection is required. It captures strict immutable `bytes`, checks a
host-supplied expected lowercase SHA-256, and rejects empty/whitespace-only,
NUL-containing, invalid UTF-8 or over-1-MiB input. No conversion, normalization,
source/specification extraction or path lookup is performed. Well-formed text
need not be a syntactically or semantically valid Mumei program.

The frozen `PreparedSourceRequest` retains the exact bytes in memory for a later,
separately authorized adapter boundary. Its explicit `to_dict()` emits only the
plan and format/raw-byte digest/byte count, with a canonical SHA-256
`request_fingerprint` over that manifest. The payload is excluded from repr and
never interpolated into diagnostics or exception context. Use this serializer;
do not log the `.source` payload or apply generic dataclass serialization to it.
Changed input bytes, selected settings, result contract or observed context
change the binding; even a whitespace-only source edit changes raw-byte identity.
The host must approve metadata labels and input handling independently.

```python
from agent.verification_planner import SOURCE_INPUT_FORMAT, RouteRequirements

# Register a descriptor with input_formats=frozenset({SOURCE_INPUT_FORMAT})
# and an exact result-contract offer, then explicitly prepare host-held bytes.
request = RouteRequirements(
    required.profile, required.method, result_contract=required,
    input_format=SOURCE_INPUT_FORMAT,
)
prepared = registry.prepare_source(
    request, policy, observations, host_source_bytes, host_expected_sha256,
)
manifest = prepared.to_dict()
```

This remains partial C04/C11 and C13 regression coverage. Digests bind bytes and
declared metadata, not normalized specification meaning, authenticity, actual
tool execution, observation freshness or acceptance. A prepared record is not
an execution permission/token; saved records remain historical metadata and any
future executor must independently re-authorize/revalidate. Core retains parsing,
semantic interpretation and Evidence acceptance. There is no file/environment
access, import/artifact-path following, plugin loading, transport, execution,
resource enforcement, runtime fallback/reconciliation or production CLI/MCP/audit
integration. No external verifier, grade/Lean/native/LLVM/WASM policy changes.

### C04/C11 typed configuration follow-up

The opt-in planner now accepts host-reviewed non-secret `SettingSpec` declarations
per descriptor: strict Boolean, explicitly bounded signed-64-bit integer, or a
closed set of approved identifier choices. Each declaration supplies a valid
default. Schemas and overrides are immutable, unique by name and limited to 32
settings; choice sets are also limited to 32. Names and choices are bounded.
There is no free-text, file, environment or invocation-argument setting type.
Obvious credential, endpoint, path and command-channel names are rejected.
This is not a secret detector: the host must review every declared default and
choice as non-secret metadata before registration.

`PlannerPolicy.adapter_settings` supplies per-adapter explicit overrides after
registered defaults. Unknown adapters/options, duplicate entries and invalid
types/ranges/choices fail with static diagnostics before selection, including
settings for disabled/ineligible adapters. They cannot silently trigger fallback
or become a wildcard. Permitted preflight fallback resolves the destination's
own schema, defaults and explicit overrides; it never copies the original
adapter's values or relaxes the exact result contract.

```python
from agent.verification_planner import PlannerPolicy, SettingSpec

mode = SettingSpec(
    "search_mode", "choice", "balanced",
    choices=frozenset({"balanced", "eager"}),
)
# Register a descriptor with setting_specs=(mode,), then plan explicitly:
policy = PlannerPolicy(
    adapter_settings=(("user.fixture", (("search_mode", "eager"),)),),
)
```

For a selected descriptor with a nonempty schema, effective settings expose only
the sorted approved values plus a SHA-256 `configuration_fingerprint` over a
canonical `mumei.adapter-configuration/v1` projection. It binds the registered
schema (including defaults/bounds/choices), effective values/budgets, selected
adapter/protocol/tool-version/location and full capability/result-contract query.
Explicitly restating a default, reordering declarations or requesting a budget
above the same effective cap does not change it. Changed schemas/selected
context do. Raw policy overrides are omitted from serialized policy and repr;
invalid values never reach hashing. Schema-less legacy selected JSON stays
unchanged. The fingerprint is not a Core Evidence configuration identity,
authenticity check, source identity, execution receipt or acceptance decision.

This is partial C04/C11 planning and C13 regression coverage. There is no config
file/environment lookup, plugin discovery, tool installation/invocation, secret
transport, permission grant, resource enforcement, runtime reconciliation or
Evidence validation/acceptance. No production route, audit key, grade, Lean
gate, LLVM/native guarantee or WASM policy changes.

### C04/C11 explicit result-contract routing

`ResultContract` extends that metadata-only API with an optional, exact required
result contract. A contract binds **one** semantic profile and method to scope
(`unbounded`, `bounded`, `finite`, `identity_only`), complete bound identifiers,
assumption identifiers and an explicit correspondence relation/status
(`validated`, `assumed`, `unverified`). Bounded/finite scopes require nonempty
bounds; unbounded/identity scopes forbid them. These are approved host/profile
labels, not raw Evidence notes, arbitrary configuration or executable inputs.
Their meanings must be defined by the host/profile; the planner does not invent
their semantics or interpret numbers embedded in identifiers.

Set `RouteRequirements.result_contract` and register a tuple of complete offers
in `AdapterDescriptor.result_contracts`. The request's profile/method must agree
with its enclosing query; each offer must belong to the descriptor's declared
profiles/methods. Duplicate, mutable and malformed offers fail with static
errors. No declaration is **not** a wildcard for a constrained request.

An eligible candidate must advertise **one whole equal contract**. Fields from
different offers, profiles, methods or adapters cannot be combined. Equality is
deliberately conservative: no scope hierarchy, numeric-bound comparison,
assumption discharge/subset inference, correspondence upgrade or semantic
implication is inferred. Even an apparently stronger but unequal offer is not
substituted automatically. Priority, explicit selection and permitted preflight
fallback retain the original contract along with every existing constraint.
`result_contract_not_declared` and `unsupported_result_contract` explain
exclusions; authorization still does not make an incompatible route eligible.

The effective settings and deterministic plan JSON carry the matched contract
only for constrained requests, with sorted bounds/assumptions. Unconstrained
queries retain the existing Python defaults and exact v1 serialized shape;
they do **not** acquire an assurance policy implicitly. Runtime observations,
budgets, tie-breaking, disable/location/version policy and single-route behavior
remain unchanged.

```python
from agent.verification_planner import ResultContract

required = ResultContract(
    "user.approved-profile/v1", "deductive_proof", "unbounded",
    "user.source-model/v1", "assumed",
    assumptions=frozenset({"user.model-trust/v1"}),
)
registry.register(AdapterDescriptor(
    "user.adapter", "1.0.0", frozenset({required.profile}),
    frozenset({required.method}), result_contracts=(required,),
), replace=True)
plan = registry.plan(
    RouteRequirements(required.profile, required.method, result_contract=required),
    PlannerPolicy(selected_adapter="user.adapter"),
    (RuntimeObservation("user.adapter", "available", "1.0.0"),),
)
assert plan.selected.result_contract == required
```

This is partial C04/C11 and C13 confusion-regression coverage, **not Evidence
validation or acceptance**. An adapter can lie about a capability; matching
host-declared `validated` metadata proves no correspondence. Real outputs still
need independent identity, representation, scope, trust/freshness and acceptance
checks owned by Mumei/the appropriate checker. The Core source producer/recheck
is a separate, fresh-query path; this API neither consumes its records nor
executes it. Plugin lifecycle, execution/cancellation/resource enforcement,
runtime fallback/conflict reconciliation and common result ingestion remain
open. No new verifier, CLI/MCP/default route, audit key, grade or Lean policy is
introduced.

### C05 first source-mapped Go CFG slice

`agent.control_flow.build_go_cfg` builds the `mumei.go-explicit-normal-flow/v1`
profile from the existing statement extractor: assignments/declarations, blocks,
if/else and initializers, for/range loops, unlabeled break/continue and explicit
returns. Guard edges preserve true/false alternatives; continue reaches the
loop post clause and break reaches the following statement. Nodes bind to a
body hash and half-open, body-relative Unicode-codepoint spans, not byte offsets
or resolved source-file identities. Calls are opaque, normally-returning steps;
this is not an interprocedural, exceptional-flow or concurrency model.

A `go`/`defer` statement now admits like an expression-statement call:
Go evaluates the callee and its arguments at the statement itself, so
the call folds normally while its result is discarded — a `defer`d
call runs before the function returns and a goroutine's effects may
happen, and the union model covers both orderings. For supported
deferred calls, the registration-time fold remains a conservative
over-approximation, with an additional exit-time fixed-point fold over
captured bindings and escaped writes; records are joined by defer site
and retained across branches and loop iterations, so a textually earlier
return may conservatively include a later defer. Unsupported
switch/select, heuristic termination, labels/goto and other
statements return explicit source-mapped gaps **without** a partial
graph. Parse/parser unavailability also produces a gap. More language/type
coverage, fixed-point CFG dataflow and full source provenance remain open
C02/C05/C06 work.

The existing Go walker still owns must/may facts and resource findings.
`FunctionDataflow.cfg` and `cfg_gaps` expose the structural boundary;
`facts_for_return(node_id)` connects a reachable CFG return site to the existing
walker's facts without merging identical expressions at different locations.
It is not a claim that the CFG computed or proved those facts. The legacy
expression lookup remains conservative across all matching return expressions,
and existing audit/CLI/MCP keys, grades and fallbacks are unchanged. These
remain heuristic analysis facts, not backend-neutral proof evidence.

### C05 fixed-point assignment facts over the explicit CFG

`agent.control_flow.assignment_facts(body, graph)` runs the first bounded
fixed-point dataflow over the `mumei.go-explicit-normal-flow/v1` graph:
per-node `AssignmentFacts` with `all_paths` (identifiers textually
assigned on every path from entry) and `some_path` (assigned on at least
one path). `all_paths` descends from the name universe by intersection,
`some_path` ascends from empty by union — both monotone on a finite
lattice with a defensive iteration bound, so the analysis always
terminates on the finite graph. Facts attach to the same body digest and
spans as the CFG; a mismatched body or unparsed source is a static error.

```python
facts = control_flow.assignment_facts(body, graph)
facts[node_id].all_paths  # assigned on every path reaching the node
facts[node_id].some_path  # assigned on some path reaching the node
```

This is **declared textual assignment, not memory truth**: only simple
identifier targets of `define`/`assign`/`inc`/`dec`/`const`/`var`/`range`
statements count — selectors, indexes, the blank `_`, scoping/shadowing
and mutation through opaque calls (including `&x` arguments) are excluded.
Unreachable nodes hold the vacuous `all_paths` universe and only their own
`some_path` targets; facts read "if this node is reached". Interprocedural
flow, use/defect detection, fields and proof-grade semantics remain open
C05/C06 work. The existing walker still owns must/may resource facts;
audit/CLI/MCP keys, grades and fallbacks are unchanged.

### C05 possibly-unassigned use hints over assignment facts

`agent.control_flow.unassigned_uses(body, graph)` connects the fixed-point
facts to reads: it reports `UnassignedUse(node_id, name, span)` when a
simple identifier is textually assigned somewhere in the body yet absent
from that node's `all_paths` pre-state — a possibly-unassigned read, e.g.
a name assigned in only one branch or inside a loop and then returned.
Checks run against the pre-state, so a statement's own targets never
count as uses, and `if x := f(); x > 0` initializers flow correctly into
their conditions.

```python
uses = control_flow.unassigned_uses(body, graph)
# -> tuple[UnassignedUse, ...], sorted by node then name
```

A finding is a **hint for the host's own analysis, not a defect verdict**:
only recognized simple identifiers are considered — names never textually
assigned anywhere are ignored, fields/elements, calls, shadowing and
closures are not modelled, and the normal-flow profile's gaps still apply.
Both directions still say nothing about memory truth or proof grades.
The existing walker owns must/may resource facts; audit/CLI/MCP keys,
grades and fallbacks are unchanged.

### C05 definite unassigned-use classes over the same facts

`UnassignedUse` gains a `definite` flag over the same fixed-point facts:
a finding is definite when the name is textually assigned somewhere in
the body yet absent from the node's `some_path` pre-state too — no
remaining path can deliver it (assignment only after the use, or only in
a sibling the use's path never takes). `definite = False` keeps the
earlier class: some path may deliver the value.

```python
uses = control_flow.unassigned_uses(body, graph)
# UnassignedUse.definite distinguishes unreachable-assignment uses
```

The class is still a **hint, not a defect verdict**: a definite finding
means no modelled path delivers a textual assignment, which is a
stronger suspicion the host must still confirm — fields/elements, calls,
shadowing and closures remain unmodelled, and unreachable uses produce
no findings at all. The flag defaults to `False` for compatibility with
the previous slice's construction.

### C05 unused-assignment hints at name granularity

`agent.control_flow.unused_assignments(body, graph)` reports
`UnusedAssignment(node_id, name, span)` when a recognized assignment
statement targets a simple identifier that appears in no use position
anywhere in the body — the dead-store hint at name granularity, over the
same conservative identifier scan `unassigned_uses` performs.

```python
unread = control_flow.unused_assignments(body, graph)
# -> tuple[UnusedAssignment, ...], ordered by node then name
```

Still a **hint, not a defect verdict**: "read" means any textual
occurrence in a use position, so a name mentioned inside its own
initializer counts as read, `x++` reads `x`, and reads in unreachable
code count like any other. The check does not decide which of several
writers is dead — every writer of an unread name is flagged — and
fields/elements, calls, shadowing and closures remain unmodelled.

### C05 one-pass flow-hint report and unreachable-statement hints

`agent.control_flow.flow_hints(body, graph)` returns `FlowHints` —
the three bounded hint families in one immutable report:
`unassigned_uses`, `unused_assignments` and the new
`unreachable_statements(graph)`, which flags every span-carrying node
outside `graph.reachable()` as `UnreachableStatement(node_id, kind,
span)` — statements no normal-flow path from the entry reaches.

```python
hints = control_flow.flow_hints(body, graph)
# FlowHints(unassigned=..., unused=..., unreachable=...)
```

The aggregate adds no analysis of its own: every member keeps its own
boundary — syntactic reachability over explicit normal flow is not
dead-code proof, and each finding stays a **hint for the host, not a
defect verdict**. Unsupported syntax the profile already drops remains
invisible, and the same gaps and modelling limits apply throughout.

### C05 independent hint metrics over declared expectations

`agent.control_flow.evaluate_flow_hints(hints, expected)` compares a
`FlowHints` report against host-declared `HintExpectations` — the same
keys the report uses (`(node_id, name)` for unassigned and unused,
`node_id` for unreachable). Each family returns `FamilyMetrics` with
three separate counts: `matched`, expected-but-unreported (`missed`)
and reported-but-unexpected (`unexpected`) — false positives and
missed defects kept independent, as the C05 acceptance criteria
require.

```python
metrics = control_flow.evaluate_flow_hints(hints, expectations)
# HintMetrics(unassigned=FamilyMetrics, unused=..., unreachable=...)
```

Expectations are **host declarations, not ground truth**: agreement
measures consistency between two declarations, not correctness of
either — a metric says nothing about the analysis being right, only
about whether two declarations disagree. Invalid expectation shapes are
static `ValueError`s (`invalid hint expectation`).

### C05 file-level provenance over Go source units

`agent.control_flow.go_file_units(source)` indexes every function
declaration in one Go source unit into `GoFileUnits`: the unit's
SHA-256 plus one `FileFunction` per function carrying its raw name, a
declaration `SourceSpan` and an inner-body `SourceSpan` (both
codepoint offsets into that source) and the body's SHA-256 — the
file-level provenance the body-scoped CFG slices were missing.
Declarations without a body keep empty spans and surface a
`declaration_without_body` gap; an unparseable unit yields a
`syntax_or_parser_unavailable` gap and no units — never a partial
index. `function_body(source, units, function)` re-extracts one body
only when the source still hashes to `units.source_sha256`, the
function is one of the declared units and the sliced text matches the
declared digest — every check a static `ValueError`, so callers reach
`build_go_cfg` only on bytes the provenance still binds.

```python
units = control_flow.go_file_units(source)
body = control_flow.function_body(source, units, units.functions[0])
cfg = control_flow.build_go_cfg(body).graph
```

Provenance is **declared metadata, not semantic identity**: digests
bind bytes, not meaning — identical names may repeat across methods
and a digest match says nothing about the body being correct.
File units are not symbol resolution, module indexing or cross-file
linking; parsed-here does not imply compiled or linked elsewhere.

### C05 labelled loop jumps over the explicit CFG

`build_go_cfg` now models Go's labelled `break`/`continue`: a label on a
`for`/`range` statement registers a jump target for that loop's body,
and `break L` / `continue L` edge to the labelled loop's exit or
update exactly like their unlabelled forms — including a labelled jump
through nested unlabelled loops. `Statement.label` carries the label
name from the syntax tree. Labels on non-loop statements stay a
`labelled_statement` gap, a labelled jump whose name matches no
enclosing labelled loop is an `unresolved_label` gap, and `goto`
remains `unsupported_goto` — every limitation still a declared gap,
never a partial graph. Existing analyses (`assignment_facts`,
`flow_hints`, `evaluate_flow_hints`) work unchanged over the new
edges: a labelled break that skips the loop update correctly reports
the update statement as unreachable.

Modelling boundaries: label names come from syntax, not scope
resolution — the checker only verifies the name matches an enclosing
labelled loop; Go's function-scoped label namespace and duplicate-label
rejection are not modelled.

### C05 terminating calls as exit edges

`build_go_cfg` now models Go's terminating calls: expression statements
matching `panic(...)`, `os.Exit(...)`, `log.Fatal*`/`log.Panic*` and
`runtime.Goexit()` build `terminate` nodes that edge straight to the
CFG exit — normal flow after such a call is genuinely unreachable and
`unreachable_statements` now reports it (previously the whole body was
refused with an `unsupported_terminate` gap). Calls inside branches
leave sibling paths reachable; a trailing statement after `panic` is
reported dead, and the call's arguments still count as reads for
unused-assignment hints.

Modelling boundaries: termination means *exit of the modelled
function's normal flow* — deferred calls, `recover` and unwinding
semantics are not modelled (defer remains `unsupported_defer`), and a
`terminate` edge asserts nothing about whether the process actually
stops. Recognised callees are the declared `panic`/`os.Exit`/
`log.Fatal*`/`log.Panic*`/`runtime.Goexit` set only.

### C05 declared unreliable names over flow hints

`flow_hints` now carries `unreliable` — the names the extractor already
declares unsafe for path facts (`closure_assigned`: written inside a
nested function literal; `address_taken`: aliased by `&`). Such names
can still appear in `unassigned` findings but are never promoted to
`definite`: a closure call or an aliased write sits outside the
modelled paths, so "no modelled path can deliver it" would overclaim.
The weaker possibly-unassigned class still fires, and the declared set
is exported on the report so the host can see which findings were
suppressed rather than infer it.

Boundaries: the unreliable set comes from syntax (`func` literals and
`&` occurrences), not from call-graph or escape analysis — a name may
be marked unreliable even when no closure ever runs, and a name missed
by the syntactic scan gets no protection.

### C05 expression switches as exclusive alternatives

`build_go_cfg` now models Go expression switches: a `switch` node edges
to one `case`/`default` node per arm (implicit-break semantics — each
arm's body exits to the switch's following, never to the next arm), and
edges straight to following when no `default` exists. `break` inside a
case body exits the *switch* — not an enclosing loop — while `continue`
still targets the enclosing loop; labelled jumps keep resolving to
enclosing labelled loops. Switch initializers (`switch i := 0; x`) are
modelled, and tag/case-guard identifiers count as reads for the hint
families. `select` and type switches are rejected up front
(`unsupported_select_switch`/`unsupported_type_switch`), `fallthrough`
and labels on non-loop statements stay declared gaps.

Modelling boundaries: arms are alternatives under the same
non-evaluating profile as `if` — no ordering, overlap or exhaustiveness
claims beyond "a default catches the no-match path"; `switch` says
nothing about the guard's value.

### C05 compound targets as reads, not assignments

`_use_text` now treats compound assignment targets (`x.f`, `a[i]`,
`*p`) as *reads* of every identifier inside them: the root object and
index/key operands must exist before the write, so `x := 1; x.f = 2`
no longer flags `x` as an unused store, and `a[i] = 2` keeps `a` and
`i` live. Compound targets still never *assign* their root — `x.f = 2`
puts nothing into `assignment_facts` for `x`, and a name whose only
writes are compound stays outside the declared universe.

Boundaries: the scan is textual — field names in a target may be
over-counted as reads (a conservative miss for `unused`, never a
false "assigned" claim), and pointer/field aliasing beyond the
unreliable-name set stays unmodelled.

### C05 terminal fallthrough in expression switches

A `fallthrough` statement that is the final statement of a non-final
case clause (including a non-final `default:`) now edges into the next
clause's body instead of producing `unsupported_fallthrough`. Case
bodies are built back-to-front so the jump resolves to the next
clause's entry; `break` inside such a clause still exits the switch
and `continue` still targets an enclosing loop.

`fallthrough` anywhere else — the last clause, a non-terminal position,
outside a switch — remains the declared `unsupported_fallthrough` gap.
The model is positional, not a Go type check: a fallthrough the compiler
would reject can still be graphed, and select/type-switches stay
unmodelled entirely.

### C05 type-switch alternatives

`switch v := x.(type) { ... }` now builds the same exclusive-alternative
fan-out as an expression switch: one `case` edge per clause, bodies
ending at the following statement, `break` exiting the switch and
`continue` targeting an enclosing loop. The match itself is type-less —
the graph does not evaluate types, so a type switch with no `default`
keeps a fall-through edge (no case matching is always possible) while a
`select` without `default` still blocks. The guard binding is no longer
dropped: the extractor synthesizes the initializer `define` for
`v := x.(type)` (the bound name lives in an `expression_list` child and
`.(type)` is anonymous syntax), so `v`'s assignment and the cases' uses
of it join the graph like any other `:=`.

Boundaries: this is a control-flow model, not a type analysis — case
types are not compared, narrowed per-clause bindings (single-type cases
re-bind `v` with that type in Go) are not distinguished, and
`fallthrough` is not legal in type switches, so one parsed there stays
the declared `unsupported_fallthrough` gap instead of being edged like
an expression switch. Labelled type switches, `goto` and the remaining
unmodelled constructs still produce their existing gaps.

### C05 forward `goto` in the dataflow walker

`dataflow_facts` now analyses bodies that contain forward `goto`
instead of declining them wholesale. A `goto L` records the current
environment against the label and leaves its path dead: the recorded
environment merges into the env at the labelled statement (must-facts
intersect, `held` union — the usual join), so a jump that skips an
assignment or an `Unlock` correctly keeps the merged env conservative.
A `goto` can also be the only path that reaches a label (the
fall-through `return`s first): the walk then resumes at the labelled
sibling with the recorded environments as the only live state.

Admissibility is checked up front (`_forward_goto_plan`): every `goto`
must name a label that is declared later in document order inside the
goto's own statement list or an enclosing one. Backward jumps (real
loops through a label), undeclared or duplicate labels, malformed
operands and jumps into a non-ancestor block still return `None` —
unmodelled shapes stay unanalysed rather than partially correct, the
same fail-closed posture the CFG layer keeps for its own gaps.
Dead-path continuation after an absorbed `goto` under-approximates
must-facts, which is the safe direction for every consumer
(`facts_for_expression`, resource-state and reaching-definition
issues).

Tests cover the label merge (skipped assignments lose facts), the
resume past a dead fall-through (the guarded env is the only live
one), jumps out of loops, carried resource state across a jump, and
each bail shape (backward / undeclared / into an inner block).
Remaining limits: backward `goto` and labels crossed by non-ancestor
frames stay unanalysed.

### C06 first compiler-backed Go binding slice

`tools/go-types` is an opt-in, standard-library-only metadata producer using
`go/parser` and `go/types`, not Tree-sitter guesses. It checks one explicitly
provided UTF-8 source unit under Go 1.23 language rules and `gc` sizes for an
explicit `amd64`, `386` or `arm64` target. Stable Go 1.26+ builds the helper;
the actual compiler version, language version, profile and full source SHA-256
are recorded. Imports, build/line/compiler directives, parse/type errors and
unknown targets yield no partial bindings. No importer, package loader,
project/tool discovery, user-code execution or network operation is used.

The `mumei.go-types-single-file/v1` report records lexical binding identities,
declaration/scope spans, identifier references, named/alias type identities,
integer signedness/width, logical Boolean width, function parameters/results
and conservative call classification. Reassignment preserves a binding;
shadowing and implicit type-switch case bindings do not merge. Binding IDs
include the complete source hash, declaration position and scope, so any unit
change invalidates the old IDs, including callers of a changed local callee.
This is not SSA, alias/value-flow analysis or cross-file cache invalidation.

Only ordinary calls resolved to an implemented, non-method, non-generic,
non-variadic function declaration in this unit get a `direct_local` target.
Function variables/aliases, selectors, methods, generic/variadic calls,
bodyless declarations, builtins, conversions and closure/initializer
contexts stay explicit and opaque. A call inside a `go` or `defer`
statement classifies normally and carries a `special`
("concurrent"/"deferred") marker, since the callee resolves and its
arguments evaluate at the statement like any other call. A direct target says nothing about purity,
termination, recursion, argument/return/effect transfer or proof. Non-scalar
value semantics remain explicit gaps even when declaration lookup succeeds.

`agent.go_type_snapshot.load_go_snapshot` is a pure, fail-closed reader with
schema/profile/source/target/span/reference/type-width checks. It never launches
the helper or chooses tools. `cfg_for_function` checks the full unit before
joining the exact function body to the existing C05 CFG; report spans are
file-relative UTF-8 bytes, while CFG spans remain body-relative Unicode
codepoints. Neither typed metadata nor the CFG recomputes the legacy walker's
must/may/resource facts or suppresses findings. Compiler reports require a
trusted producer: source hashes detect staleness, not authenticity or semantic
truth. No grade or common-evidence acceptance is added.

See [build, protocol and limits](../tools/go-types/README.md). Existing audit,
CLI/MCP, planner, Seal Grade and Lean freshness/trust gates are unchanged; no
external verifier is adopted. Project/import resolution, full Go and other
language coverage, C07 interprocedural summaries and C09 LLVM translation
validation remain open, in that order. C06 is **partially delivered**, not done.

### C07 first scalar parameter-dependency summaries

`agent/go_interprocedural.py` adds an opt-in, in-process consumer of trusted,
reader-checked C06 Go snapshots. It joins source-mapped C05 CFGs and composes
parameter dependencies through compiler-resolved local calls. Syntax comes from
Tree-sitter, but identifier/callee resolution comes only from C06 bindings.
It does not launch the compiler, install tools or change audit/CLI/MCP routes.

The fragment is deliberately small: an ordinary function with scalar integer
or Boolean parameters, one unnamed scalar result and a body containing exactly
one explicit return expression. Supported expressions are parameter reads,
integer/rune literals, unshadowed Boolean constants, parentheses, selected pure
unary/binary operators and supported local calls. Named scalar types and target
widths retain their compiler identity. For example, `Pick(a,b) = a` composed
with `F(x,y) = Pick(y,x)` yields caller parameter dependency `{1}`. Nested calls
record source-byte spans, target identities and formal-to-actual dependency
sets. Every argument must be supported even if the callee ignores its value.

This is a conservative dependency analysis, **not value evaluation, equality,
correctness or proof**: `x*0` and `x-x` still depend on parameter `x` in the
reported overapproximation. An empty dependency set means parameter-independent
within the fragment, not a known constant. An unavailable result is `None`,
never an empty set; failed functions retain gaps but no partial call transfers.

Recursion/cycles, opaque/missing/external/indirect edges, methods, generics,
variadics, named/multiple results, statements/branches/loops, closures,
defer/concurrency, conversions/builtins, division/remainder/shifts, floats,
global/constant reads, pointers, aliasing and resource operations are unsupported.
Unsupported callees block their callers, not unrelated supported functions.
The effect tag `none_in_supported_fragment` describes only the whitelisted
function invocation; otherwise effects are `unknown`. It does not verify
package initialization, the process/runtime, resource state or authority.

Source/profile/language/target/compiler and the complete consumed snapshot
contribute to the context key. `GoSummarySet.for_function` requires the current
source and snapshot: any unit change, including a changed callee with unchanged
caller text, invalidates reuse. These hashes are freshness/consistency identities,
not authentication. There is no persistent cache or evidence acceptance route.
The initial budgets are 128 functions, 48 levels of active expansion/syntax
depth and 2,048 syntax/expression nodes per function. Limit exhaustion blocks
analysis rather than supplying an effect-free or dependency-free result.

C07 is **partially delivered**, not done. Fixed-point joins, bounded
loop bodies, `&x` escape folds, `*p` stores/reads (named *and*
unnamed scalar pointees), scalar package-level `var` reads/writes,
struct-typed local values (conflated dep sets), composite package
globals (named-type struct/array/map/pointer `var`s admit
field/index/deref reads and writes under the same external-state
model — the var's own binding identity records each mutation and
`stale_dependents` stays honest; an anonymous `struct{...}` var
admits the same way, with fields resolving through their own
bindings instead of named identities), multi-file
package
units and audit wiring
(`--enable-summaries`) have all landed
since this line was written — the honest residuals are the
remaining composite-pointee surfaces (index-element reads and
assignments through bound pointers to containers and whole-pointee
stores admit under the external-state model — `(*p)[i]`/`p[i]` and
`(*p)[i] = v` on `p *[]T`/`*map`/`*[N]T`, `*p = v` on any
resolvable pointee; element-field reads and stores admit too —
`(*p)[i].F`/`p[i].F` reads and `(*p)[i].F = v`/`+=`/`++` stores on
a named-struct element (the store folds the value's deps into
`indirect_writes` so an aliased `(*q)[j].F` observes them), plus
`GA[i].V`/`M["k"].V` on a package container `var`; container
iteration and element inc/dec admit as well — `for range *p`/
`for range p`/`for range *GP`/`for range GP` (the element name
carries deps(p) ∪ indirect stores for a bound pointer, dep-free
for a package var) and `(*p)[i]++`/`--` — and a computed range
operand admits too: `for range *g()`/`for range g()` over a
locally declared callee whose declared result is a pointer to a
slice/array/map (or a slice/array/map directly, or a
pointer-to-array under the same sugar rule as `for range p`)
ranges it under the opaque-callee model — the callee's body is
outside the scalar signature fragment, so the call records an
imported transfer, argument deps union, `&x` arguments fold and
`effects` stays unknown, while each element name carries
deps(args) ∪ escaped ∪ indirect writes and the index/key stays
dep-free — and nested element
fields admit arbitrary named-struct levels (`(*p)[i].F.G`,
`(*p)[i].F.G.H`, … reads, stores and inc/dec: every intermediate
must be a `var` member whose named struct type pins, the leaf
resolves through its own reference, and the deps union the
pointer's own, the indexes' and every indirect store exactly
like `(*p)[i].F` — an anonymous `struct{...}` intermediate stays
closed), while
deeper nested derefs
now admit at any depth (`**p`/`***p`/`****q` — the chain of unary
`*` operands must still end at a bare identifier, each pointee
level resolves through the pointer fact's `elem` or a named type
identity, and the deepest element classifies scalar/pointer under
a `<binding>/pointee`*depth identity or a named deep type).
Named-alias
pointer chains now admit one hop — `type PP *T` emits a
`pointer` fact on PP's own member (type_id keeps PP, `elem`
carries the pointee), so `*p`/`p.V`/`p.V = v`, `(*p)[i]` and
the range/auto-deref sugar on `type PS *[]T`/`type PA *[N]T`,
an anonymous `*struct{...}` elem, and imported `var V PP`
derefs all resolve like their `*T` spellings, pinning PP and
every identity `elem` names (a `PP` signature parameter pins
the pointee through `signature_type_ids` too), while a pointee
that is itself a named pointer (`type PP *PS`) and any
unmodelled elem kind stay closed.
Anonymous `*struct{...}` pointees now admit single-level scalar
field access — `p.V`/`(*p).V` reads and `p.V = v`/`+=`/`++`
stores — since the producer emits a `struct` fact for every
struct underlying and each field still resolves through its own
binding; the synthetic `<binding>/pointee` identity records the
store (never pinned — no declaration can redeclare it), while
whole-struct derefs (`*p` reads or stores) and nested selections
through a pointer-typed `A` stay closed. Anonymous `struct{...}`
VALUES admit too — `st := struct{...}{...}`/`var st struct{...}`
carry the same conflated dep set as a named composite (declaration,
`st.V`/`st.A.N` reads and stores, `st.V++`), plus `var GS
struct{...}` at package scope under the external-state model; the
direct-field window enumerates the literal's fields by source
order, so a field promoted through an embedded `*Q` still closes.
Struct-typed parameters and results now admit too — a `struct`
fact on a signature slot (named or anonymous) seeds the binding's
conflated dep set in `locals_` like a composite local, so
`s.V = x`/`s.A.W = x` fold in and `s.V`/`s.A.W`/`p := G(x)`
reads carry the caller's provenance — while `st.P`/`*st.P` on a
pointer-typed field
stays closed like `st.A.N` on `A *P2`,
the remaining
resource-state semantics (channels — local `make(chan T)`
channels now admit under a conflated dep set: `ch <- x`
accumulates the sent value's deps, `<-ch` and `for v := range ch`
return the union of every send, `v, ok := <-ch` binds both names
with it, and `close(ch)` admits as an untracked synchronization
fact — and `chan T` parameters with a scalar element admit under
an external sync-resource model: a send records an imported
transfer on the parameter's binding and broadcasts the sent deps
into indirect writes (a later `<-ch` can observe them), a receive
returns the parameter's provenance union the indirect writes, and
`close(ch)` is a caller-visible effect — channel-name copies
(`ch2 := ch`, `var ch2 = ch`, an unconditional `ch2 = ch3`) now
admit as queue aliases: `ch2` resolves to the same queue as `ch`,
so sends and receives through either name share the root's dep
set (aliasing a `chan` parameter adopts its external
sync-resource model) — channel operands in
external state admit under the same model: a package-level
`var GC chan T` or an imported member `lib.GC` records sends,
receives, `for range` and `close` as imported transfers on the
var's or member's own identity, receives returning the indirect
writes — and a bound pointer's scalar-element `chan` field
(`p.C <- x`, `<-p.W.C`, `close(p.C)`, `for range p.C`) admits
the same way, the queue living in caller memory: ops record on
the field member's identity, sends broadcast into the indirect
writes, reads union `deps(root)`. A `chan T` result now admits
the same way a `chan` parameter does: `ch := g()` and
`var ch = g()` bind a callee-produced queue when the
(local) callee declares a single scalar `chan` result —
ops on the bound name broadcast sends into indirect
writes and observe the caller's queue through them,
exactly like a parameter — and an unconditional
`ch = g()` rebind reseats the name to the callee's
queue the same way (a passthrough callee makes `ch`
name the argument's queue; any prior alias drops).
An imported `lib.G()` binds the same way: the
producer declares the member's `result_types` and
classifies the call `direct_import` when the lone
result is a scalar-element `chan`, so `ch :=
lib.G()` admits as an external queue whose ops
record on the member's identity. An
alias to that name
(`ch2 := ch`) follows the external queue through the
root binding, a bare read or argument surfaces the
queue's widened set, and a function literal that
captures the name records the same external effect a
captured `chan` parameter does. A channel rebound under a branch or
loop (`if c { ch = q }`, `ch = g(q)`, `ch = g()`,
or `ch = make(chan)` over an aliased name) could
mean EITHER queue after the join, so the name
detaches to an external queue: its dep slot unions
the old queue's contents with the RHS deps and every
queue it could still mean is promoted external —
sends broadcast through `indirect_writes` and
receives union it, so a third name still holding
the old queue's identity (`z := t` before `ch = q`)
sees writes the untaken path delivered. A
multi-result callee admits per slot: `ch, n := g()`
binds an external queue when the (local) callee
declares a scalar `chan` at the name's position —
the tuple shares one RHS node, so make/alias/
passthrough all resolve to None and only the
per-position result type decides admission (a
`chan` name at a non-`chan` or non-scalar slot
stays closed). The `var` declaration and plain
assignment forms admit the same slot — `var ch,
n = g()` and `ch, n = g()` bind an external
queue when the chan name's position declares a
scalar `chan`; when the callee provably returns
a `chan` argument at that position the name
aliases the argument's queue instead — while a
non-scalar element at the slot stays closed. A fresh
`make` on an unaliased name keeps the old conflated
admission since every name resolving to it already
converges on the same slot. An imported
multi-result callee admits the same slot: `ch, n :=
lib.G()` records `direct_import` when every result
is scalar/pointer or a scalar-element `chan` (the
member's `result_types` carries each slot's fact),
the chan name's position binds an external queue,
and the call's `chan` arguments join the external
model since the opaque callee may return one — the
`var` and plain-assignment forms admit identically,
while a non-scalar leaf stays closed. An
imported method declares the same way: `ch := st.M()`
or `ch, n := st.M()` admits when `M`'s signature
carries a scalar-element `chan` at the bound slot
(the call records `direct_import` marked `method`).
A func-typed callee declaring a scalar `chan`
result admits too: `ch := g(x)` / `var ch = g(x)`
where `g` is a func-typed parameter or a bound func
value (`f := mk(x); ch := f(x)`) binds an external
queue — go-types resolves the bound name's declared
`chan` type from the callee's signature, so the LHS
gate already carries the result fact; an
unconditional `ch = g(x)` rebind reseats the name
like `ch = G()`, and each `chan` argument promotes
external since the opaque body may hand it back
(`ch := g(q)` seeds `ch`'s slot with `q`'s
contents). A func value declaring `chan chan T`
admits through the `chan chan` arm on the declared
LHS type. The callee must resolve to a name bound
to a func-typed value or a func-element collection:
`fs[k](x)` / `fm["k"](x)` — which parse as a
generic-instantiation conversion — run the
collection's element opaque on its declared-`chan`
result like `g(x)` does, while a call-result callee
(`mk(x)()`) and a nested index (`fm["k"][0](x)`)
stay closed, and a multi-result func-value callee
stays closed since no signature record verifies the
per-slot `chan` fact. Nested channel queues with an integer or
boolean leaf admit under the external queue model at any depth: a
`chan chan ... chan T` parameter or result (local or imported), a
package-level queue variable, or a `cc := G()` / `cc, n := G()`
bound name joins the external model. Operations on the outer queue
record imported effects; channels received from it remain external,
including when they are themselves nested queues, and retain their
selectors and parameter origins through later operations. `close`
likewise records the imported effect. The follow-on forms admit
identically:
`cc = G()` reseats a `chan chan` name to the
callee-produced external queue (conditional or not
— the unioned slot covers either meaning), `var cc
= G()` and `var cc, n = G()` bind like the
short-decl forms, `for c := range cc` (and `for c =
range cc` over an existing scalar-`chan` name)
binds each element as an external channel like `c
:= <-cc`, and the comma-ok receives `c, ok :=
<-cc`, `var c, ok = <-cc` and `c, _ = <-cc` reseat
or bind the value slot to the received external
queue. A local `make(chan chan ... chan T)` or `var cc chan
chan ... chan T` is admitted as a bound queue under one
conflated share-group model: every local channel sent into or
received from the queue at any depth joins its group, as do
aliases and members of other local channel groups. Local queue
operations (`send`, `receive`, `close`, `len`, and `cap`) do not
record a transfer on the outer queue identity. External members
remain externally observable through the group: their reads and
sends contribute indirect writes and imported transfers. Passing a
local queue to a direct local function call, `go`, or `defer` is
supported only when its parameter has the same scalar-leaf nested
channel shape. Its whole share group becomes external at the call
or defer-registration boundary; later members joined by sends,
receives, aliases, or group merges inherit that externality.
Imported, indirect, method, variadic, and type-mismatched calls
remain closed.

External scalar-leaf nested-channel queue sources may be aliased
through short declarations, `var` initializers, or
assignment: nested-channel parameters, package/imported
queue variables, and already-admitted external queue locals are
supported. A local queue reseated onto one of
these sources or an admitted direct local/imported
call-result queue is promoted conservatively; its prior
share-group members become caller-visible. An admitted
direct local/imported call result may also be used
directly as a queue operand.

For an admitted queue, a received channel at any depth may be used
directly as an operation target without a named binding:
`(<-src) <- x`, `<-(<-src)`, `close(<-src)`,
`len(<-src)`, `cap(<-src)`, `range <-src`, and channel
operands in `select`. These carry the same share-group,
externality, selector, and origin facts as a same-point
temporary receive. Passing a received external channel
as a value to another local queue (`dst <- <-src`) joins
their share groups.

Returning a local scalar-leaf nested-channel queue through a
matching `chan chan ... chan T` result is supported: the result
dependencies include the readable contents of its share group, and the
whole group becomes external at the return point so deferred
work observes the caller-visible identity. Storing such a
queue in a package or imported matching nested-channel variable also
promotes its group and broadcasts its dependencies to later
external reads. The container value itself still cannot be returned,
stored, passed, captured, or addressed; struct fields, local queue
escapes other than the admitted return/package-store paths,
non-scalar leaves, and unsupported converted/interface/method/
variadic call forms stay closed. Scalar-leaf channel queues at depth
three and deeper use the same recursive share-group model.
`select` continues to admit each communication case's
receive (`v := <-ch`, `v, ok := <-ch`, `v = <-ch`, a bare `<-ch`)
or send (`ch <- v`); operands run in a fresh alternative scope and
every alternative joins back by union —
an if/else chain whose guards are comm ops;
`break` exits the select like a switch clause, an
empty `select {}` blocks forever and stays closed,
and a non-identifier receive target admits the way the
ordinary assignment does — `s.V = <-ch` accumulates the
received deps into the composite's base (broadcast on a
declared-type base), while `*p = <-ch`, `(*p)[i] = <-ch`
and `(*p)[i].F = <-ch` alias-fold them into every escaped
binding plus `indirect_writes`; an unbound-container target
(`a[i] = <-ch`) still stays closed — while
`len(ch)`/`cap(ch)` now admit as
dep-free — the queue length and capacity are runtime
state, not parameter provenance; on a `chan` parameter
each records an imported transfer like a receive does —
`make` —
`new(T)` now admits as a dep-free `*T` allocation whose type
argument pins, with the pointee's own use-site gates classifying
what `*p`/`p.V`/`(*p)[i]` admit; `&P{...}` admits for struct
composite literals (named, imported, anonymous) as a fresh pointer
whose value carries the initializer's deps, which also fold into
the pointee dependency set like stores through it — and bound
function values:
a function literal bound to a local name
(`h := func(...)...` / `var h = func(...)...`) now admits as a
function-typed binding whose deps capture the enclosing bindings
the literal references; invoking it through a bare-identifier
call `h(args)` admits with deps(captured) ∪ deps(args) ∪
indirect writes, and a literal that captures a pointer-typed
enclosing binding records an imported transfer on the bound
name's identity (effects unknown — the captured pointer may aim
at caller memory). A package-level `var Alias = Id` call
admits as an opaque external call — the callee is
reassignable by any caller, so `Alias(args)` is dep-free
for the callee, unions the args and indirect writes, and
always records an imported transfer on the var's real
binding identity (effects unknown). A function-typed
parameter `f func(int64) int64` calls the same way —
`f(args)` is an opaque external call, since the caller
chooses the callee — and it stays external even when a
branch binds a literal under it (`if b { f = func()... }`),
because the untaken path still runs the caller's callback.
For any such external callee (package function var or
func-typed parameter) the callee name reads its current
deps — `f = g` reseats `f` to g's set — the call unions the
escaped bindings' deps like a `*p` read (the opaque callee
may read caller memory through a pointer argument), and the
argument deps together with the callee's own read set fold
into every escaped binding and into indirect writes — the
opaque callee may write `*p = y` through a pointer argument
or send `y` on a channel argument — and the callee's
declared type identity pins alongside the var's/parameter's
binding identity so a named `type MyFn func(...)`
regenerating in another file flags the caller stale. A
func-typed binding's signature (`f func(N) int64`, `var f
MyFn`, `type MyFn func(N) int64`) declares its inner
named/alias type identities on the binding's
`signature_type_ids` — the func type fact itself carries
none — and they pin at the declaring function's own
signature, at resolved local callees and at external calls
alike. A function name bound in a store's RHS position —
`h := G`, `h = G`, `var h = G`, including copies through
tuple binds (`h2 := h`) — records a function-name alias, and
`h(args)` resolves through G's own summary exactly like a
`direct_local` call (argument evaluation, folded
`return_dependencies`, signature pinning, the callee's
effect opacity and its transfer on G's identity). A
maybe-skipped rebind that could leave the name's value
path-dependent — a different function, a literal, or a
param still carrying the caller's callback — drops the
alias so the call falls back to the opaque external model;
a package-level `var Alias = Id` keeps the opaque external
model since any caller may reassign it. A function name in a
call's argument list — `H(G, args)` — reads dep-free: it is a
declaration, not data, but the callee may invoke it, so the
read queues a pending invocation that the call's own fold
drains once its deps are known — recording a transfer on G's
identity (`imported` when G's effects are unbounded) and,
when G can write or send into shared state, broadcasting the
call's deps into `indirect_writes` for a later receive to
observe. G's binding and signature identities pin for
staleness. Other non-store positions — a `return`, a
comparison operand — stay closed. An in-place
literal call — `func(...) T { ... }(args)` — admits like
a bound-literal call whose captures resolve at the call
site: the result unions the captured bindings' current
dep sets, the arguments and indirect writes, and a
pointer or external-channel capture records an imported
transfer on that identity. A literal whose
body still defers an effect — a call, a store, a `*p`
store — admits too, as an opaque effectful callee: a
literal-internal call or `*p` write unions the escaped
bindings' deps into the result and records an imported
transfer on a synthetic span identity, a store whose
write target resolves to a captured binding lands the
written value's deps on that binding at the call site
(conditional _store union semantics), and a declared
function name inside the literal body (`return G(x)`)
needs no capture — only the send/go/defer statements
that target a shared queue stay closed. A captured local plain
integer/boolean channel with only local `make`, `nil`, or zero-value
origins admits a literal send only when every enclosing-function
reference is a send-channel, receive, builtin
`close`/`len`/`cap` argument, or range operand, and the literal is
invoked synchronously as a direct call of its bound name or an
immediately invoked literal; `go`, `defer`, and callback invocations
stay closed. Synchronous literals also admit queue/container sends
(`cc <- d`, `s[i] <- v`, and `(<-cc) <- v`), receives (`<-cc`,
`<-s[i]`, including nested receives), and `close`/`len`/`cap` of
those operands. Queue groups must remain local and unescaped; plain
containers must be tracked local scalar-leaf containers (not params,
package values or escaped roots) and every enclosing reference must be
a supported indexed channel operation. Aliases, enclosing channel
values sent into a queue,
non-operation uses (including call arguments, returns, assignments,
composite values, range, address-of, and comparisons), `select`, and
asynchronous, deferred, or callback invocations stay closed. A function name
read in a call's argument list admits dep-free (the
possible invocation folds through the call's own record); a
func literal passed directly as an argument folds its
capture/write record like a bound func value;
a name in any other non-store position
(operand) stays closed — while a `return` of a function
name admits dep-free under the func-result signature below),
per-statement read attribution now
lands in `statement_reads` (one `(span, deps)` record per walked
statement — see its own section below), and cross-file dependencies
beyond the TS-style host-declared resolver contract — Rust resolves
`mod`/`use` and Sol resolves `import` directives through the same
`summarize_*(source, resolver, source_path)`/`--resolve-modules`
shape; existing function-local dataflow stays
authoritative.
A `func`-typed *result* now admits at the signature gate like a
`func` parameter: the value carries no scalar deps, `return G` on
a declared function reads dep-free, and a literal return
(`return func() int64 { return x }`) lets the literal's captured
deps ride the result's dep set — so `f := mk(x)` binds an opaque
func value whose calls resolve through the ordinary func-value
path (`var f = mk()` and `f = mk()` admit identically, and a
multi-result signature with a func slot unpacks the same way).
An imported func-result callee (`f := lib.Mk()`) records
`direct_import` and binds an opaque func value the same way —
see the C06 imported-callee section below.
A func-element collection result — `[]func` / `[N]func` — admits
at the same gate: the caller's `mk(x)[0]()` runs the indexed
element as an opaque call on the container's slot (the producing
call's `chan` arguments join the external model exactly like the
`f := mk(ch)` capture, so `mk(ch)[0](x)` can send `x` into `ch`'s
queue). A `[]func`/`[N]func` local binds the same conflated way
(`fs := mk(x)`, `var fs = mk(x)`, `var fs []func() T; fs = mk(x)`),
and `fs[k]()` then calls opaque on the container's slot — the
callee read is the container's dep set and a computed index
evaluates like an argument. Element literals inside the composite
record their captures under the container's name (unioned, like
other maybe-set records), so `fs := []func(){func(){ return y }}`
followed by `y = x` resolves at the `fs[0]()` call site, and a
captured write target gets the call's write-back fold. The
container's `chan` arguments promote like `f := mk(ch)`: elements
may capture the queue, so a later `ch <- x` reaches `fs[k]()` via
`indirect_writes`. A `nil` literal admits as a dep-free value in
every expression position (`return nil`, `G(nil)`, `f = nil`,
`p == nil`) — a nil read on a non-nilable type cannot compile, and
the nil queue holds nothing.
A `map[K]func` call result admits through the same gate:
`lib.Mk(x)["k"]()` runs the keyed element as an opaque call on
the container's slot — which value a map key holds is as
unknowable as a slice index, and map literals never reach the
fragment, so only call results produce these containers. A
computed key evaluates like an argument (`lib.Mk(x)[k]()` folds
the key's deps). A `map[K]func` local binds the same conflated
way a `[]func` local does (`fm := lib.Mk(x)`, `var fm =
lib.Mk(x)`, `fm = lib.Mk(x)`): a keyed slot is as unknowable as
a numbered index, so `fm["k"]()` calls opaque on the
container's slot and the producing call's `chan` arguments
promote through it. `make` on a func-element collection binds
the same way (`fs := make([]func, n)`, `make(map[K]func)`,
`make(FM, n)` on a named collection type): a fresh empty
container whose dep set starts empty and grows by element
stores, while `make` on a non-func collection still cannot
bind.
An element store into a bound container — `fs[i] = v`,
`fm[k] = v` — unions the stored value's deps into the
container's conflated set, and a func-typed RHS is recorded
element-wise: a literal's captures, write targets and inner
calls record under the container's name like a composite
element's, and an identifier or selector RHS adopts the
referent's own func records into the container (read from the
pre-state, so `cl, fs[0] = g, cl` still hands `fs[0]` `cl`'s
OLD records — the element store is not a name rebind, so the
record-clearing that a scalar store's name gets does not apply).
A computed index or key evaluates like an argument on the store
side too. Copies share the backing (`fs2 := fs`, `fs2 = fs`,
`var fs2 = fs`): an element store through any name in the group
unions into every member's records, while a definite non-append
reseat (`fs = mk()`, `fs = []func(){…}`, `fs = nil`) hands the
old elements to the names still sharing the array and detaches.
`append` admits on a bound func-element container
(`fs = append(fs, f)`, `fs2 := append(fs, f)`, a `fs2...`
spread): the result may reuse the argument's array, so the name
joins the argument's group, and each appended element records
like a composite literal's — a literal argument climbs through
the argument list the same way. An element literal or store
inside a branch keeps the deps of branch-local bindings it
captures even after the merge drops them: a closure stored into
a container still reads the value the capture held at the merge.
A param container's elements live in caller memory and a
scalar-element container has no func records — both stores stay
closed.
One level of collection-of-collection admits the same conflated
model: `fm := [][]func(){…}`, `var fm = …`, `make([][]func, n)`,
`make(map[K][]func)` and a named `type FMM map[K][]func` bind like
the single-level containers, `fm[k][i] = f` (literal, identifier
or `nil` RHS) stores an element under the root binding's slot,
`fm2 := fm` / `fm2 = fm` share the backing, and `fm[k][i]()` calls
opaque on the root slot — both index expressions evaluate into the
call's dep set when they are not literals. Inner-slot donor keys
resolve canonically (`1`, `0x1` and `'\x01'` name the same Go
element, `"a"` and `` `a` `` the same map key; a keyed element
continues the implicit index like Go's own layout), a store through `fm[k][i]` folds the
stored value's deps into the donor backing's set so the call reads
the same slot, and a donor reseat with no surviving sharer parks
the old backing's element records under a surrogate donor the
nested call still resolves. The conflation depth is
exactly one extra level: a third index (`fm[k][i][j]`), an element
read (`v := fm[k][i]`), an `append` into the inner collection
(`append(fm[k], f)`), a whole-inner-container store
(`fm[k] = sub`), a param container and a call-result nested
container (`mk()[k][i]()`) all stay closed.
A call-result callee (`mk(x)()` — also `lib.Mk(x)()` where the
inner callee resolves) admits as an opaque indirect call: Go
evaluates the callee expression before the arguments, so the
inner call's own records land first, the outer call's result
unions the inner call's dep set with the arguments', and the
external effect records an `imported` transfer on the inner
call's span identity — an anonymous callee with no binding to
name, like an immediate literal call's. `mk()()()` nests the
same evaluation. An inner call the model cannot evaluate keeps
the outer call closed.
A func-element collection *parameter* — `[]func` / `[N]func` /
`map[K]func`, including a named container type — admits like the
result form: the elements live in caller memory, so `fs[i](x)`
calls opaque on the parameter's own slot (the callee read carries
the container's index and the computed index evaluates like an
argument). A non-empty argument list parses the `fs[i]` callee as
a `generic_type` instantiation shape — admitted only when the
operand's binding is a func-element collection, so a true
`F[T](x)` instantiation of a function stays closed, and the same
parse shape on a bound local container resolves through
`locals_`. Element writes into a parameter container
(`fs[i] = g`) stay closed: they reach caller memory the model
cannot scope.
`new(struct{...})` admits the anonymous pointee the type
checker already reports: the literal names no `type` identity,
so pinning reduces to each field's declared type — a nested
literal, a signature field or an unresolvable name keeps the
call closed through the ordinary gate. The bound pointer then
resolves `p.F`, `(*p).F` and `p = new(struct{...})` exactly
like `var p *struct{...}` or a `*struct{...}` parameter — field
bindings carry the same union-fold semantics named-struct
pointees get.

No verification grade, Lean trust gate or external verifier changes. C09 LLVM
translation validation remains separate from these source-analysis summaries.

### C07 let bindings before the single return

The body fragment now admits `name := expression` declarations ahead of
the single scalar return. Each let binding records its compiler-resolved
binding identity, requires a scalar (`integer`/`boolean`) declared type,
and contributes its initializer's dependencies to later expressions and
the return — `F(x,y) { z:=x+y; return z }` reports `{0,1}` and
`z:=y` ignores `x` (`{1}`).

Reassignment (`y=1`), tuple declarations, increments, effect-only calls
and every other statement shape produce `unsupported_statement`; a
left-hand identifier with no compiler binding or a non-scalar declared
type yields `binding_unavailable`. The overapproximation is unchanged:
dependencies are conservative, never equality or proof.

### C07 branched bodies and multiple returns

The body fragment now admits `if`/`else` statements and more than one
return: dependencies union every syntactic return (`F(x,y) { if x>0
{return x} else {return y} }` reports `{0,1}`). A condition is evaluated
— it must be a supported expression — but contributes no result
dependency because every fragment statement is effect-free. Branch-local
let bindings feed only their own scope, matching the compiler: a
reference outside the branch simply does not resolve.

Unreachable returns still contribute — reachability is not proven.
`if` initializers, `for` loops and every other statement shape stay
`unsupported_statement`. The union is still a conservative
overapproximation, never equality or proof.

### C07 bounded for statements

`for` statements join the fragment under a narrow clause contract: the
`for_clause` initializer is one let binding, the condition is a
supported expression (evaluated, effect-free) and the update is an
inc/dec on a bound scalar identifier — or the clause is absent
(`for {}`, `for cond {}`). The loop variable and every binding inside
the body stay scoped to the loop, matching the compiler. Returns inside
the body union into the result like any other syntactic return;
iteration itself is never unrolled or counted — dependencies describe
textual reachability, not trip counts.

`range` clauses, `break`/`continue`, assignment updates and non-identifier
update operands stay `unsupported_statement`/`binding_unavailable`.
Still a conservative overapproximation — never equality or proof.

### C07 scalar reassignment

A scalar `x = expression` reassignment joins the fragment: a single
identifier left-hand side resolving to a parameter or an in-scope let
binding — never a declaration. At top level the reassignment replaces
the binding's dependencies (the old value is gone); inside a branch or
loop body the caller joins the new value back by *union*, because the
inner path may not execute — a may-analysis, still a conservative
overapproximation, never equality. Loop bodies are joined to a widening
fixed point so dependencies propagating across iterations are captured
(a join, not an unroll — trip counts are never modelled).

Compound operators (`+=`, `-=`, ...), tuple targets, and assignments to
names outside the parameter/let scope stay `unsupported_statement` /
`binding_unavailable`.

### C07 expression switches in bodies

An `expression_switch_statement` with no `initializer` and no
`fallthrough` joins the fragment: the tag and every case guard are
evaluated (effect-free, like `if`/`for` conditions) and each clause body
runs in its own scope, with reassignments joining back by union because
exactly one clause — or none — may execute. `return` inside a clause
unions into the result like any syntactic return.

Switch initializers, `fallthrough`, type switches, `select` and every
other statement shape stay `unsupported_statement`.

### C07 var declarations in bodies

`var_declaration` joins the fragment under the same binding contract as
lets: every `var_spec` declares exactly one name with at most one value;
the binding is taken
from `bindings_by_span` and must be scalar (integer/boolean), else
`binding_unavailable`. `var x T` without a value binds the dep-free zero
value — honestly dep-free, not an approximation. Vars scope like lets:
branch/loop-local declarations never escape.

Multi-name specs, non-scalar bindings, `const` declarations and grouped
`var (...)` forms (a tree-sitter parser gap) stay
`unsupported_statement` / `syntax_or_parser_unavailable`.

### C07 effect-free control statements

`x++`/`x--` join the fragment as dependency-preserving statements: the
operand must be a single identifier resolving to a bound scalar —
incrementing changes the value, never which parameters it derives from.
`_ = expression` evaluates-and-discards like a condition, and
`labeled_statement` unwraps to its inner statement — a label without
labelled jumps is inert syntax, and a label that IS used requires a
jump, which stays `unsupported_statement`.

Unlabelled `break`/`continue` mark their innermost loop-or-switch
construct as exited (a `continue` inside a `switch` clause still reaches
the enclosing loop); every later statement in that construct's body is
then a may-assignment — its writes union instead of replace, because the
jump may have skipped them. This is the same over-approximation the
branch and loop joins already use; reachability is still not proven.

Labelled `break`/`continue`, `goto`, `defer` and `go` stay
`unsupported_statement`/`binding_unavailable`. An inc/dec operand
that is not a bound identifier admits through the imported
member-write gate instead — `lib.V++` (or dot-imported `V++`,
indexed `lib.VA[i]++`, field `lib.VS.F++`, dereferenced
`(*lib.PV)++` on a pointer-typed member) records the same
external mutation a `lib.V = v` write does, index sub-expressions
evaluate like a write's, and a member that names no writable
storage or an operand that resolves to none stays closed. A bound
field (`t.F++`, `(*t).F++`, or a nested `t.W.F++` on a bound
`*S`/`**W2` param) routes through the opaque-write-target gate:
the mutation records on the same identity `t.F = v` uses, and —
like `(*p)++` — no dependency fold is needed since the stored
value is the field's own external contents.

### C07 statement initializers on if and switch

`if` and expression `switch` statements accept a simple-statement
`initializer` — `if v := f(); v > 0 { ... }` and `switch v := f(); v {
... }` — handled by the same mechanism as a for-clause initializer: the
statement is dispatched normally before the condition or tag is
evaluated, and a bound name is scoped to the statement (a later
out-of-scope reference simply never resolves). Initializer forms
outside the fragment — multi-name declarations, expression/send
statements — stay `unsupported_statement` /
`binding_unavailable` through the same dispatch.

### C07 scalar conversions in expressions

Conversion calls `T(e)` — reported by the producer as call kind
`conversion` — are effect-free for dependency purposes: the result
inherits the operand's dependencies. The type change itself
(truncation, widening, signedness) is not modelled; dependency is about
value provenance, not representation. Conversions to types outside the
scalar fragment fail closed at the conversion itself — the target
type's binding (or the fixed predeclared scalar set for universe type
names) must be integer or boolean, so a non-scalar result can never
flow into a context that doesn't bind it (`binding_unavailable`).
Builtin calls inside a conversion stay `unresolved_or_opaque_call`.

### C07 pure builtins in expressions

Builtin calls classified `builtin` by the producer are admitted only
for `min`/`max` — the pure builtins whose operands are scalars — and
their result unions every argument's dependencies. `len`/`cap` admit
one extra shape: a single argument naming an imported container `var`
(`len(lib.VA)`, `cap(lib.VA)`, `len(lib.VS)` on a `string` var) reads
external state like the member itself, so the result is dep-free —
the call still records the imported transfer and pins the declared
identity. An index chain on an imported var whose element is itself
a container admits the same way (`len(lib.V2[i])` on `[][]int64`,
`len(lib.VM2["a"])` on a map-valued map): dep-free apart from the
indexes' own dependencies, and the member's whole fact tree pins.
Any other operand (`len(xs)` on a binding, `len(f())`,
`len(lib.VS2.G)` on a field, `len(lib.VC)` on a channel)
stays opaque, as does every other builtin (`panic`, `complex`,
`real`, `imag`, ...); `copy`/`delete`/`clear` admit on a bound
scalar-element container operand — see the scalar-element
container section.

### C07 compound and tuple assignments

Assignment statements now cover the full scalar fragment: beyond
`x = e`, compound forms `x op= e` (`+=`, `-=`, `*=`, `/=`, `%=`, `&=`,
`|=`, `^=`, `<<=`, `>>=`, `&^=`) union the binding's current
dependencies with the right-hand side's — the operator reads the old
value. Tuple assignments `x, y = e1, e2` are parallel: every right-hand
side evaluates against the pre-state before any store lands, so
`x, y = y, x` swaps each name's original dependencies; `_` slots
evaluate-and-discard. Because initializers dispatch through the same
statement path, `for`/`if`/`switch` initializers accept the new forms
too. Left-hand sides stay bound identifiers or `_` — selector/index
targets and a right-hand side count mismatch stay
`unsupported_statement` / `binding_unavailable`. A count mismatch is
admitted only for a lone multi-valued imported call whose declared
arity matches the left-hand width (`a, b = lib.F(x)` — see the C06
multi-valued imported results slice).

### C07 integer range loops

`for` statements accept a `range` clause over an integer operand —
`for i := range e` binds a fresh scoped index variable carrying the
operand's dependencies, `for i = range e` reuses an existing binding,
and `for _ = range e` / bare `for range e` just evaluate. Body
may-assignments join back exactly like clause loops, and unlabelled
`break`/`continue` use the same frame machinery.

A `range` clause over an imported container member —
`for i := range lib.VA`, `for k, v := range lib.VMK`, or a
`.`-imported operand — admits when the operand names a `var` member
whose `type` is a `slice`, `array` or `map` fact, with up to two
identifier left-hand names. The member read transfers on the member's
identity and marks `effects` `unknown` (iterating external state),
pins the member's `type_id` plus a named map `key.type_id` / container
`elem.type_id`, and binds each left-hand name dependency-free — the
yielded values are external, like any other imported read. A `_` slot
skips binding; the `:=` form binds fresh identifiers and the `=` form
stores through `_store`. The clause stays closed when the operand is
not an imported container member (local bindings, computed operands,
member `func`/`type`/`const`, non-container member types like
`lib.VStr`), when a bound name's type is not `integer`, `boolean` or
`pointer` (a `map[string]` key or struct element), or when there are
more than two left-hand names or a non-identifier slot. Composite
ranges over any other operand shape remain unreachable in-fragment —
their operands cannot be produced by any supported binding or literal.

### C07 multi-name declarations

The declaration fragment now admits `a, b := e1, e2` and multi-name
`var` specs (`var a, b int64 = e1, e2`, `var a, b = e1, e2`, and the
dep-free zero-value form `var a, b int64`). Each left-hand name binds
its matching right-hand side's dependencies; the whole right-hand side
evaluates in parallel against the pre-state before any store lands —
the same parallel semantics as tuple assignments — so shadowing and
redeclaration behave the way the compiler resolves them. `_` slots
evaluate-and-discard, and a mixed redeclare like `x, y := e1, e2`
where `x` already exists keeps the existing binding: go/types records
a use, not a fresh binding, and the store lands on it like an
assignment.

Every name still must resolve to a compiler-reported integer or
boolean binding — a non-scalar name anywhere in the list is
`binding_unavailable`. Multi-valued calls take one right-hand
expression supplying every name (`a, b := lib.F(x)`) — admitted only
for an imported callee whose record declares the matching arity (see
the C06 multi-valued imported results slice); every other count
mismatch stays `unsupported_statement`. Redeclaration inside a nested
block still produces a fresh, branch-scoped binding that cannot escape
its scope, matching the compiler.

### C07 expression statements

Statement-position expressions are admitted — in Go these can only be
calls (or receives, which can never appear in-fragment), so the shape
evaluates the inner expression for its recorded transfer and discards
the result. `G(x); return y` records the `G` transfer exactly like a
bound call would; a callee without a summary keeps its
`callee_unsupported` gap. A void callee (`func s(x) { ... }`) now
summarizes — the signature gate no longer requires a result, a bare
`return` or falling off the end carries nothing, and a statement call
folds the callee's calls and effects with an empty result-dep set
(effects land; no value flows back). An empty-body `func v(){}` still
stays `unsupported_body`. Because initializers dispatch through the same statement
path, `if G(x); cond` / `switch G(x); tag` initializers admit the same
form.

### C07 alias and resource-state fixtures

The acceptance criterion that interprocedural fixtures cover aliasing
and resource state is exercised as negative coverage: pointer
parameters and `&x` aliases, slice/map/channel resource state
(package-level `var`s now *do* admit — scalar and composite — under
the external-state transfer model, local `make(chan T)` channels
admit under the conflated dep-set model, and scalar-element `chan`
parameters admit under the external sync-resource model; the
still-closed shapes are non-scalar elements and
`chan` results from imported or multi-result
callees — conditionally-changed channel bindings
now admit under the detach-to-external model, and
`select` admits its communication cases as
switch-like alternatives),
slice/map `make` constructor
state all fail closed —
selector/computed callees and function-typed parameters
now admit as opaque external calls (the callee slot's
identity is unknowable to the caller), and an in-place
literal call `func(...) T { ... }(args)` admits like a
bound-literal call whose captures resolve at the call
site; every still-closed shape
lands as a declared gap (`unsupported_signature`,
`unsupported_operator`, `unsupported_expression`,
`binding_unavailable`, `non_parameter_reference`,
`unresolved_or_opaque_call` or `callee_unsupported`) and never as a
summary that silently misses the alias or mutation. Some producer-level
shapes (e.g. `make`/`[]int64{...}` in binding position) fail even
earlier, at the snapshot boundary — still closed, just not a summary
gap. Admitting any of these is a deliberate future slice, not an
accident of the fragment.

### C07 dependent invalidation

`GoSummarySet.stale_dependents(known)` closes the acceptance criterion
that callee replacement invalidates dependent summaries: a recorded
`CallTransfer.target` is a source-anchored binding identity — it embeds
the producing unit's source digest — so a replaced or deleted callee
never reuses it. Given the currently known binding identities, the set
of summaries that recorded a call to anything outside it is exactly the
re-derive set, and the walk is pure metadata. `FunctionSummary.call_targets`
exposes each summary's recorded callee identities for the same join.

Boundaries: this is detection, not recomputation — the host decides what
to rebuild, no persistent cache or evidence acceptance is implied, and
an unavailable summary that recorded no transfer is never flagged (it
was already unusable). Flagging propagates transitively along recorded
`call_targets` edges to a fixed point — a caller's summary encodes its
callee's answer, so a stale callee invalidates its callers — and the
fragment's recursion rejection keeps the walk finite. True cross-file
calls still cannot be made at
all (single-unit snapshots); this maps invalidation for whatever calls
the fragment does resolve.

### C07 switch fallthrough

Expression switches admit a terminal `fallthrough` as the final
statement of a non-final clause, mirroring the C05 positional rule: the
next clause's body is evaluated twice — once in the carried chain scope
as a sequential continuation, and once as a fresh alternative from the
switch scope, because the clause can also be matched directly without
the preceding clause's writes (`case 1: y = 0; fallthrough; case 2:
return y` still keeps `y`'s dependency on the switch's entry state).
A conditional `break` before the fallthrough keeps the continuation's
writes may-assignments — they execute only when the break was not
taken. Guards of a fall-through clause are still evaluated
unconditionally like every other clause's; the fragment already
over-approximates guard evaluation, and fallthrough chains extend
transitively across consecutive clauses.

Boundaries: `fallthrough` remains admissible only as the terminal
statement of a clause — Go rejects a trailing fallthrough in the final
clause and a non-terminal one upstream at the type check (a defensive
`unsupported_fallthrough`/`unsupported_statement` gap covers both
shapes anyway). Type switches, `select`, labelled jumps and `goto`
stay outside the fragment.

### C07 general for updates

A for-clause update no longer requires the `i++`/`i--` inc/dec shapes:
the update statement runs through the same `statement` dispatch as the
body, once per fixed-point pass after the body sequence, so assignments
(`i = i - 1`), compound updates (`y += z`), tuple updates
(`y, w = w, y`) and calls (`y = G(y)`) all admit — inc/dec keep their
dependency-preserving no-op semantics while assignment updates widen
their RHS dependencies into the loop fixed point exactly like a body
statement would.

Boundaries: the update is replayed inside the widening pass, so it is
evaluated as a may-assignment per pass — dependency sets converge by
union, and update shapes the fragment rejects anywhere else (defer,
go, select, type switches, unsupported expression forms) still
surface as the same declared gaps. Condition
evaluation stays a once-per-loop approximation, and trip counts remain
unmodelled.

### C07 scalar const declarations and reads

`const` declarations and constant reads are admitted on the scalar
fragment: a constant expression can never read a variable — the
compiler rejects a non-constant right-hand side before this reader runs —
so a scalar-typed `constant` binding always resolves to an empty
dependency set and a `const` spec writes nothing. Spec names must be
identifiers bound as constants of scalar type (typed or untyped
integer/rune/bool); `_` names discard like declarations do. `iota` is
dep-free, and values are still evaluated for fragment legality —
constant-expression builtins like `min` record their transfer.

Boundaries: non-scalar constants (string, float, complex) stay
`binding_unavailable`, a read of one through a scalar context surfaces
the same gap, and grouped `const ( ... )` declarations remain a parser
gap like grouped `var`. A spec with no value (implicit iota repetition)
is unmodelled, and this is still not constant *evaluation* — a const is
parameter-independent, not a known value.

### C07 remaining scalar binary operators

All remaining scalar binary operators — `/`, `%`, `<<` and `>>` — are
admitted on the scalar fragment. Dependency composition is
operation-agnostic: every pure operator unions its operands'
dependencies like the arithmetic and bitwise set already does. This
also removes the inconsistency where the compound forms `/=`, `%=`,
`<<=` and `>>=` were admitted while their plain counterparts were
gaps.

Boundaries: this is still dependency analysis, not arithmetic — no
value, overflow, shift-count or division-by-zero semantics are
modelled, matching the existing boundary for every other operator.
Non-scalar operands stay type gaps, and unary operators beyond
`+`, `-`, `!` and `^` remain unsupported.

### C07 named result parameters

A scalar named result — `func F(x int64) (r int64)` — is an ordinary
local pre-initialised to the dep-free zero value. Body statements write
to it like any local; a bare `return` (legal only with a named result)
yields its current dependencies, while `return e` assigns the
expression's dependencies exactly as an unnamed result does. A result
never written stays parameter-independent, and inner declarations can
still shadow it.

Boundaries: this slice admits the named result's *dependency* role only
— no zero-value semantics are modelled, and a bare `return` without a
named result stays `unsupported_return` (the compiler rejects it
anyway). A multi-result signature (named or unnamed, every result in
the admitted kinds) is admitted too: the callee reports ONE conflated
dependency set over all its results, so `a, b := g()` hands each bound
name the union — the same over-approximation the C06 multi-valued
imported results slice uses — while `return e1, e2` and a bare
`return` over several named slots fold into it. Result bindings keep
needing scalar type, and methods/generics follow the same gates as
single-result signatures. Bare-return legality is guaranteed by
`go/types` before the reader runs — no extra validation is needed.

### C07 multi-file package units and per-file freshness

A package-level producer profile — `mumei.go-types-package/v1` — takes
named sources `{name, source}` (mutually exclusive with `source`) and
reports file-indexed spans. `load_go_package_snapshot` validates it
like the v1 loader, plus: `source_sha256` is a unit digest over
`name\x00file-digest` pairs, each binding identity is
`sha256:{declaring-file-digest}:{file}:{pos}:{scope_start}:{scope_end}`,
and the package scope is the sentinel span `file=-1`. Every file's
bytes re-validate against its declared digest — a tampered, missing or
reordered file fails closed.

The payoff is per-file freshness: replacing one file churns only that
file's binding identities, so `stale_dependents` — which already maps
callee replacement to dependents — now detects file-level changes
without re-deriving the untouched files' identities. Within a unit all
functions share the package scope and calls across file boundaries
classify `direct_local` like any in-package call. `summarize_go_package`
is the multi-file consumer; span lookups are normalised to
`(file, start, end)` keys so the body analyser runs unchanged.

Boundaries: at most 64 files of at most 64 KiB each, unique non-empty
names, one shared `package` name enforced by `go/types`. No ambient
import resolution — paths resolve only through host-declared `imports`
(see C06 below); anything else fails the report as `unresolved_import`.
File indices are report-internal
positions in the `files` list, not filesystem paths. Single-file v1
reports keep their exact wire shape (`file` is omitempty); the summary
gap spans carry the declaring file's position only — file identity
lives in the binding identity, not the gap. Ordering, caching, and
which file sets form a unit stay host decisions.

### C06 host-declared import resolution

The package request gains `imports: [{path, sources: [{name, source}]}]`
— the host declares every source set an import path may resolve to.
The producer's `types.Importer` resolves only through that map:
nothing reads disk, the network, or the toolchain, and the stdlib is
not provided. Resolution is recursive (a declared unit may import other
declared paths) and cycle-safe; an undeclared, uncompilable or cyclic
import fails the report as `unresolved_import`. `imports` requires
`sources` — the single-file profile stays closed. At most 64 declared
paths, each a unit under the same ≤64-file/≤64-KiB rules.

The payoff is cross-package freshness: a package-qualified call
`lib.G(x)` — or a dot-imported `G(x)` — records `direct_import` whose
target is the callee's identity computed in the imported unit's own
coordinate space (`sha256:{its-file-digest}:{file}:{pos}:{scope}` —
identical to what that unit's own `mumei.go-types-package/v1` report
assigns, given the same source order). Regenerating the imported unit's
report churns that identity, so `stale_dependents` flags callers across
package boundaries. Uses of imported members record `import` references
with the same identity; package names are namespace qualifiers and are
not emitted as bindings or references. The loader revalidates the
format: `direct_import` targets and `import` binding ids must carry the
`sha256:{digest}:{file}:{pos}:{scope_start}:{scope_end}` imported-
identity shape and must not collide with local
functions or bindings; the single-file loader rejects both kinds.

Consumer semantics stay honest: `summarize_go_package` treats a
`direct_import` call's result as potentially depending on every
argument — a documented over-approximation, since the callee body is
opaque and package-level state is not modelled — and records the
transfer so staleness propagates. `call_not_summarized_direct_import`
is therefore not a gap a resolved report emits. `direct_import` is only
classified for callees whose results are all scalar — a composite
result at any arity stays `external_or_bodyless` and fails closed (a
`range` over a composite operand would break the integer-only range
model). A `func`-typed result admits the same way a `func` parameter
does: `f := lib.Mk()` binds an opaque func value whose calls resolve
through the func-value path, and a multi-result signature carrying a
func slot (`f, n := lib.Mk()`) binds the slot opaquely beside the
conflated scalar results. A generic callee still rejects the same
way an instantiated generic always has — `lib.Mk[int64]()` (explicit
type arguments) and inferred instantiations fail the
generic-instantiation gate regardless of the result's kind, func or
scalar. A multi-valued scalar callee is admitted and declares its
arity on the call record; see the C06 multi-valued imported results
slice below. A variadic callee (`lib.W(x, y)`, `WV(x, y)`) admits the
same way — every argument is an independent expression whose
dependencies union into the result — while the spread form
`lib.W(xs...)` records only the operand's span, cannot map its
argument expressions and stays closed. A summary recording a
`direct_import` transfer reports
`effects` as `unknown` — the imported callee's side effects are outside
the fragment. Imported sources honour the same no-directive contract as
the root unit (`//go:`, `// +build`, `//line` markers fail resolution).
Identities are content-addressed within a unit's file order: two
declared packages with identical file contents produce identical
identities, so a host tracking freshness per path must not rely on
identity membership alone. Which packages exist,
their paths, and their source order stay host decisions; there is no
import shadowing, vendoring or version selection, and a transitive
import path must also be declared.

### C06 imported member declarations and scalar constant reads

The package report gains `imported_members: [{id, name, kind, type}]`
— one declaration per imported object the unit actually names (a
`direct_import` callee or an `import` reference target), nothing more.
`id` is the member's binding identity in the imported unit's own
coordinate space (the same imported-identity shape as `import`
references), `kind` is `function`, `const`, `var` or `type`, and `type`
is the standard type fact. The loader validates the shape and dedupes
ids; the section is optional — a report without it still loads and
imported names simply stay unmodelled.

The payoff is honest value coverage: a package-qualified read
`lib.K` now classifies only by the declared member. A scalar
constant (`kind == "const"` with an integer/boolean/untyped-scalar
type) is admitted dep-free, exactly like a local constant — the
member's name must also match the source token, so a record that
names a different object never widens a read. Imported functions
are not values in the fragment: their reads keep
`non_parameter_reference` and fail closed, as does any read whose
member declaration is absent.

A package-qualified `var` read `lib.V` is admitted as an opaque
state read: it records a zero-argument `CallTransfer` with
`imported=True` — the value derives from package state, not from
any parameter, so the result contributes no dependencies while
`effects` reports `unknown`. The recorded target is the member's
own imported identity, so a regenerated report for that unit still
flags the reader through `stale_dependents`. The read is scalar
only: a `var` whose type fact is not integer/boolean keeps
`non_parameter_reference`, matching the fragment's value model.

One level of dereference on such a var is admitted too: `*lib.PV`
where `PV` is a pointer-typed `var` member reads the pointee as
package state. The operand's own var read already records the
imported transfer and pins the pointee identity the `*T` fact
carries, so the dereference shares both — the result stays dep-free
and `effects` reports `unknown`, and redeclaring the pointee type
flags the summary. Admission is pointee-gated: the named pointee
must resolve to a `type` member whose fact is scalar or pointer —
a struct or interface pointee stays closed because the dep model
cannot represent the value. An unnamed pointee classifies by the
member's `pointee_kind` declaration instead: `*lib.PU` on `*int64`
reads an `integer` dep-free, `*lib.PPV` on `**T` reads a `*T` and
pins `T` through `pointee_type_ids` — whose identities the producer
now declares as members so a bound `*p` on the stored pointer
resolves `T` too — while a non-scalar shape (`*lib.PA` on
`*[4]int64`, `*lib.PSTR` on `*struct{ F T }`) stays closed like a
named struct pointee. A deref
through a pointer-typed *field* member resolves the same way:
`*lib.VS2.P` resolves the field like a field read, classifies the
result through the field member's `*T` fact, and pins the base
member's identity beside the pointee's — a field whose pointee
carries no identity (`*lib.VS3.PU` on `PU *int64`) classifies by
`pointee_kind` exactly like `*lib.PU`. A bound
pointer dereferences the same way: `*t` on a parameter or local
whose declared `*T` names the pointee admits, records its own
imported transfer against the pointee identity (the binding's read
carries none of its own), and returns the pointer's provenance —
the binding's dependencies — as the result; `p := &t` inherits the
same `*T` identity, so `*p` reads the same way. Because a stored
pointer may alias any escaped binding, the read also unions the
current deps of every `&x`-escaped binding — no type check, since
a `*A` pointer can alias an `A2 = T` binding even though the facts
record distinct type_id's for the aliases — `p := &x; x = y; *p`
reads x's updated
value, and the same may-read covers `*lib.PV` once `lib.PV = &x`
could have pointed it there. The read also unions every dependency
ever stored through a pointer write — `*t = v; return *t` reports
`v`'s deps even when no `&x` escaped — because the store lands in
untracked memory this read may observe. The pointee's
identity resolves through `imported_members` or — since the
local-named-types slice — the unit's own `type` bindings, so `*T`
on a local `type T` admits the same way. An unnamed *scalar* pointee — a
`p := &x` binding on a builtin `int64` — admits the same way by
classifying through the pointer fact's own `elem` (see the unnamed
scalar pointees slice); composite unnamed pointees, a computed
pointer (`*g()`), and a nested deref (`**t`) stay closed — matching
the `*t = v` write side, where dep sets track binding indices, not
pointee contents. To make the named pointee visible the producer
now declares it: recording a pointer-typed `var` member also
records the pointee's `type` member, the same way a function
member's `signature_type_ids` declares the types its contract
names.

Member declarations also classify the conversion target of
`lib.T(e)`. The producer already records such calls as
`conversion`; the consumer now admits one whose field resolves to
an `import` reference on a member declared `kind == "type"` whose
type fact is integer or boolean — the result inherits the
operand's dependencies exactly like a local or predeclared
scalar conversion, and the member name must match the source
token. Alias targets take the same path (`type A = int64` declares
a `type` member whose underlying fact is the scalar). Conversions
to a non-scalar named type (`type F64 float64`, `type S string`),
a member record whose kind is not `type` and a missing declaration
keep `binding_unavailable`; generic instantiations `lib.T[int](e)`
fail even earlier, since an `index_expression` callee is not an
admitted expression.

Dot-imported names take the same path: the producer records `import`
references (and member declarations) for a `. "lib"` import's objects,
so a bare `K`/`V`/`T(e)` in the source classifies by the declared
member exactly like `lib.K`/`lib.V`/`lib.T(e)` — a scalar const read
is dep-free, a scalar `var` read records the same opaque state-read
transfer (with the same staleness propagation), and a scalar `type`
member admits the conversion. The member name must still match the
source token; function values, non-scalars, generic instantiations
and reads without a matching record stay closed.

A field read of an imported struct var — `lib.VS.F` — admits through
the member records the producer already emits: the field itself is a
`var` member whose `import` reference classifies the selection, and
the operand resolves like a member read (`lib.VS`, `VS` under a dot
import, or parentheses around either). The field is external state
like the member itself — the read is dep-free, reports `effects` as
`unknown`, records the imported transfer against the *field's* own
identity, and pins both the struct var's and the field's declared
type identities for `stale_dependents`. The field's declared type
must be scalar or pointer — a composite field is a value the
fragment's model cannot hold — and anything that resolves to no
field member stays closed: a method selection (`lib.VS.PF`) names a
`function` member, and a non-struct member's selection resolves no
field. A bound base admits through the same dep-free model: `t.F`
on a `*S` parameter or local is an auto-deref read of caller state
— the operand must be a bound identifier whose pointer names a `type`
member (one explicit dereference, `(*t).F`, spells the same
auto-deref out), the field resolves through its `import` reference
to a scalar-or-pointer `var` member, and the pointee identity pins
for `stale_dependents`. Intermediate selections walk the same way:
`t.W.N` resolves `W`'s `*W2` member to the `W2` `type` member — every
`type` member the chain traverses pins — so the chain admits while
each field is pointer-typed. The pointee is struct-typed, so it can
never alias a tracked scalar binding — no escaped union is needed. A
doubly-derefed base (`(**t).F`), a struct-valued intermediate
(`t.A.B` on `A S3`), a method value (`t.PF`) and a composite-typed
field stay closed. Package-local named types admit identically since
the local-named-types slice: the pointee `type_id` falls back to the
unit's own `type` bindings, and the selector's `field` resolves
through its `local` reference to the field's `variable` binding
(the `scope`-less field marker) — the identities are real, so
`stale_dependents` stays honest in both directions.

A field read through an index chain admits the same way:
`lib.VSM[k].F` on `map[string]S` or `lib.VSS[i].F` on `[]S` reads a
field of external state — dep-free apart from the indexes' own
dependencies (literal indexes carry none, like `lib.VM["k"]`),
recording the imported transfer against the field's identity and
pinning the container member's whole fact tree so the element's
named type flags `stale_dependents` too. The element of the whole
chain must resolve — a computed operand (`g()[0].F`) names no member
and stays closed, and a scalar element cannot compile anyway.

### C06 imported member type identities

A member's declared type fact now carries `type_id` when the type is
a named or alias type the imported unit declares: the producer names
it with that declaration's own imported-unit binding identity — the
same `sha256:{digest}:{file}:{pos}:{scope}` coordinate space
`direct_import` targets and member ids already use (an alias names
the alias object). Basic and unnamed types keep no identity. The
package loader admits the imported-identity shape on `type_id` in
addition to local binding ids; the single-file profile still rejects
`imported_members` outright, so the relaxation is unreachable there.

The consumer pins that identity on every admitted read or conversion
whose declared member type carries one — a scalar `var`/`const` read
of a named-type member and a named-type conversion alike,
package-qualified or dot-imported. `FunctionSummary.pinned` records
the pinned identities alongside `call_targets`, and
`stale_dependents(known)` flags a summary whose pinned identity
leaves the known set: redeclaring `type T` in the imported unit flags
summaries that read `lib.VT` or convert through `lib.T` even when the
member declaration itself is byte-identical.

Boundaries: the pin names the *declared* type, not its meaning — a
compatible redeclaration still flags the dependent (detection, not
equivalence), and a member whose type fact has no `type_id` (basic,
unnamed or composite types) pins nothing. Pins attach only on
admitted reads: a read of a member declared with a non-scalar named
type stays closed before any pin applies, and an unavailable summary
still records none. A *local* binding that merely names an imported
type (`var x lib.T`) records no pin either — its admission never
depends on the type's identity, so redeclaring `T` only reaches it
through the consumer report's own regenerated type facts.
Package-level constant reads remain
dependency-free but their *values* are not modelled — the fragment
tracks what a result depends on, not what a constant equals.
Selector reads remain limited to a plain package-qualified name:
nested selectors, method values and field accesses on values stay
unsupported.

### C06 call signature type-identity pins

A function member record now declares the named and alias type
identities its signature's parameters and results mention, as
`signature_type_ids` — the same imported-unit coordinate space the
member ids themselves use, deduplicated and sorted (receiver types
are not signature types here). The validator admits the key only on
`kind == "function"` members and requires every entry to match the
imported-identity shape *and* sit outside the report's own bindings,
so a tampered entry cannot name a local binding — local ids share
that sha256 shape — nor borrow a non-imported identity.

An admitted call pins the callee's declared signature type
identities in `FunctionSummary.pinned` exactly like a member read's
declared type: `direct_import` unions the member's
`signature_type_ids`, and a resolved local call pins its callee's
declared parameter and result `type_id`s — a local `func G(y lib.T)`
parameter names an imported identity a bare `call_targets` edge can
never reach, while a local type's identity already churns with its
declaring file so pinning it is harmless. `stale_dependents`
therefore flags a caller of `lib.Z` — `func Z() T` — when `T` is
redeclared even though `Z`'s own identity and the call's member
record stay byte-identical.

Boundaries: pins name *declared* signature types at top level — a
type nested inside a composite (`[]lib.T`, `map[string]lib.T`)
records no entry, and a signature naming no named/alias type carries
no key. Callers pin the callee's signature at each admitted call
site. The
non-scalar-result admissibility rules are unchanged,
so the pin only ever covers calls the fragment already summarises.

### C07 transitive staleness and own-signature pins

`stale_dependents` now propagates flagging transitively along
recorded `call_targets` edges to a fixed point, instead of reporting
direct edges only: a caller's summary encodes its callee's answer,
so a stale callee invalidates its callers however many files apart
they sit — closing the under-flagging a direct-edges report left
for chains like `F → H → G` where `T` churns while every function's
own identity stays live. The fragment rejects recursion, so the
propagation terminates.

At the same time a function summary now pins the named/alias type
identities its *own* declared parameter and result type facts carry
— the summary embeds those facts, so redeclaring a signature type
makes the recorded summary stale even when the function's own
identity is unchanged (previously only callers pinned, at call
sites). Basic and unnamed types still pin nothing, and an
unavailable summary still records no pin.

Boundaries: propagation follows `call_targets` only — `pinned`
edges flag the pinner directly but are not walked further (a pinned
identity names a type declaration, not a summary). Transitivity is
detection semantics, not proof that the re-derived summaries will
differ; detection, not equivalence.

### C07 unnamed scalar pointees

A bound pointer whose pointee names no member — `p := &x` producing
an unnamed `*int64` binding — now admits `*p` reads and writes.
The producer emits the pointee's own type fact on every pointer fact
(`elem`, the same encoding slices/arrays/maps already used), so the
analyzer can classify `*p` even when `type_id` is empty: a
scalar-or-pointer `elem` admits the deref, composite shapes
(`*[]int64`, `*struct{...}`) and facts recorded before `elem` was
emitted stay closed, matching the named-pointee rule. A `*int64`
parameter dereference admits the same way, so
`G(p *int64) { return *p }` composed with `F(x) { return G(&x) }`
reports `{0}`.

The dep model is unchanged: the read unions the pointer binding's
own deps with every escaped binding's deps and every stored
indirect-write deps; the store records the external mutation and
folds the stored value into every escaped binding (the same
approximation `*lib.PV = v` uses). Since nothing declared can name
the unnamed pointee, the recorded mutation/read transfer carries a
synthetic per-binding identity, `<binding_id>/pointee` — it can
never be pinned nor redeclared, so `stale_dependents` can never
falsely flag it, and `effects` still reports `unknown` like every
other pointee-touching operation.

Boundaries: the admitted surface is unnamed pointees only —
`*struct{...}`, `*[]T`, `*map[K]V`, `**T`-deref (`*p` where `p`
is `**T` admits; `**p` does not) and local named types keep their
closed verdicts. A snapshot produced by an older helper carries no
`elem` on pointer facts and stays closed, so consumer and producer
move together; the compiler-helper test matrix covers the new
emission on every arch.

### C07 package-level scalar vars

`var G int64` declarations at package scope — shared mutable state
outside the parameter set — now admit reads and writes, modelled
exactly like an imported `lib.V`: the read is dep-free for the
value (its contents derive from package state, not from any
parameter) but records an imported transfer, so `effects` reports
`unknown`; the write records the same transfer and drops the
stored value's dependencies, since no binding tracks global
contents — `G = x; return G` therefore reports no parameter deps,
matching `lib.V = x; return lib.V`. `G += v` follows the same
assignment gate, and `G++`/`G--` admit like `lib.V++` —
provenance-preserving, only the external mutation records.

The recorded target is the var's own binding identity — a real
declaration, so `stale_dependents` works honestly in both
directions: removing or redeclaring `G` flags every summary that
touched it, and an unchanged unit flags nothing (no synthetic
identity). Named types in the var's fact tree pin through
`_pin_fact_identities`, so redeclaring `T` under `var G T` flags
the readers and writers too.

Package scope is detected from the binding's scope record: the
packaged profile's file `-1` sentinel, or the whole-file span in
the single-file profile. A function-local `var` the fragment does
not track carries its function's scope and stays closed; a bare read
of a package var with composite or non-scalar type (`G` for
`var G []int64`, `G` for `var G string`) stays closed too. Direct
slice, array, and map operations on package vars and on container
fields of package-level composite vars are external-state reads;
field-rooted index, range, `len`, and `cap` operations transfer on
the resolved field identity, while field chains with indexed extras
remain closed. Scalar package `const`s were always dep-free. Package
vars shadowing universe names (`var iota int64`, `var true bool`)
admit the same way: the compiler resolves the use to the
declaration, so the read is package state like any other.

### C07 bound pointers to local named types

The named-pointee paths previously resolved `type_id` and field
references through `imported_members` exclusively, which left an
asymmetry: `p.V = x` on a local `type P struct{...}` already
admitted (the member-write path returns the pointer's `type_id`
unvalidated) while `p.V`, `(*p).V`, `t.W.N` and `*p` on `p *MyInt`
stayed closed. The three resolution sites now fall back to the
unit's own bindings: the pointee `type_id` resolves to a `type`
binding, and the selector's `field` resolves through its `local`
reference to a `variable` binding with `scope is None` — the field
marker (package vars carry the unit scope, function vars the
function's). Dep semantics are verbatim the imported model: field
reads are dep-free plus an imported transfer against the field's
real binding identity, `*p` reads return the pointer's provenance,
and writes keep the existing `_member_write`/pointee-identity
contracts — `effects` reports `unknown` everywhere, and every
resolved identity lives in `known`, so `stale_dependents` flags a
redeclared `type T` or renamed field without any synthetic ids.
Boundaries hold: struct-typed local values (`st := P{...}` —
admitted in the next slice), unnamed composites (`*[]T`,
`*struct{...}` — single-level scalar field access admitted in a
later slice via the producer's `struct` fact and the field's own
binding), nested derefs (`**t`) and non-scalar fields stay
closed.

### C07 struct-typed local values

`st := P{...}` — a local variable bound to a named composite type
(`type P struct{...}` in the same unit) — now admits declaration,
field reads, field writes and reassignment under a **conflated
dependency model**: the binding carries ONE dependency set covering
every field, a sound over-approximation in both directions. `st :=
P{V: x}` unions every literal field value's deps into `st`; `st.V`
or a nested chain `st.A.N` reads the whole set (local state, so no
transfer records and `effects` stays honest); `st.V = y`,
`st.V += y`, `st.A.N = y` and `st.V++` union the RHS in via the
existing `(ref, accumulate)` slot — never a transfer, because a
local mutation is not an external effect; `st = P{...}` replaces
the set wholesale. Admission gates on a composite `type.kind` —
`"unsupported"` with a `type_id` resolving to a local `type`
binding, or `"struct"` with no `type_id` for an anonymous
`struct{...}` value (`st := struct{...}{...}`/`var st struct{...}`
behave identically, and `st.A.N` traverses nested anonymous
fields since each field's direct set enumerates by source order
after its declaring name's span; a promoted field through an
embedded `*Q` still fails the window). Other unnamed composites
(`[]T`/`map` values, `type_id`-less bindings) stay closed
(`binding_unavailable`).
Struct params/results stay closed at the signature gate.
Bound-pointer field chains also admit named struct-valued
intermediates (`t.A.B` and `(*t).A.B`), pinning each resolved
struct type; anonymous struct intermediates remain closed.
Promoted fields on tracked local structs admit enumerable value-only
embed paths, pinning each embedded field and type; pointer crossings,
generic or imported embeds, and promoted methods stay closed.

The hard boundary is the aliasing invariant the dep-free bound-
pointer field read relies on: a bound pointer must never alias a
tracked composite. `&P{...}` admits only for struct literals;
`&st`, `&st.V` and non-struct composite literals stay
`unsupported_operator` (the `&` operand's root is walked through
parens/selectors/indexes), and a chain through a *pointer-typed*
intermediate field (`st.A.N` where `A *P2`) stays closed — the
deref reads caller memory the conflated set cannot represent.
Composite-typed package globals, `st[i]` and `*st.V` stay closed.
A field read of a call result — `g(a).V`, `g(a).A.B` — admits the
same conflation: the call's result dep set covers whichever field
the read selects, so the operand evaluates like a value (only a
call at the selector chain's base takes this path — an identifier
base keeps the local composite path and its promoted-field gate,
and an index on a call result like `g(a)[0]` stays closed with
the callee's unsupported signature).
An index read on a call result — `lib.G(a)[i]`,
`lib.M(a)["k"]`, `lib.N(a)[i][j]` — admits when the callee's
declared single-result type names a container (slice, array or
map) whose element is scalar-or-pointer: the element's provenance
is the call's own dep set plus each index's deps, with the
container/element/key identities pinned. An imported callee whose
composite result stays `external_or_bodyless` still admits through
the index (the member's `result_types` carry the fact) — the call
folds through the minimal opaque-argument union — while struct
elements, multi-result calls and local callees whose composite
result is not summarizable stay closed.
A bare composite binding — `s := lib.G(a)` or `var s = lib.G(a)` —
now admits when the callee's declared single result is a slice,
array or map: the name binds one conflated dep set (the call's own
dep set, matching the `len(lib.G(a))` convention that a
callee-produced container's provenance is its call's) plus a
backing token keyed on the call node. `s[i]`/`s[k]` element reads
carry the sharers' union plus each index's deps (scalar elements
only); `s[i] = v` unions the stored value's deps into every name
sharing the backing — `s2 := s` shares it for slice and map (an
aliased store lands in both reads) and copies for an array (`[N]T`
keeps the value copy). `for range s`, `len(s)`/`cap(s)` and a
rebind `s = lib.G(b)`/`s = t` retarget or drop the backing token —
a non-container RHS detaches the name so `s[i]` fails closed
again. Literals, multi-result calls, package container vars and
non-scalar elements stay closed. A scalar-element container
PARAMETER registers as a share group at function entry like the
`struct` seed: `a[i] = x` accumulates on the param's (the
caller's) dep set, `b := a`/`b := a[i]` share it, `a = s` reseats
off the caller's backing, and reads carry the param ordinal plus
whatever the body stored — `a = nil` detaches it the same way.
Container params that can share backing (slices, maps, and arrays
of shared-memory elements like `[N][]T`) seed ONE group — a store
through `s` lands in `t`'s set so `G(a, a)` stays honest; a pure
`[N]int64` is a local copy and keeps a solo group. A param whose
dep set grows past its seed — a store landed on caller-visible
memory — records an imported `/caller-backing` transfer like the
`*p = v` `/pointee` write, so `effects` reports unknown and the
caller's `_store_call_writes` folds the argument deps into the
container arg's sharers: `G(s, v) { s[0] = v }` makes
`G(a, x); return a[0]` read `{0, 1}` — and a local callee's
`return s` unions the named params' arg tokens into the result's
backing, so `t := G(a)` joins `a`'s group (`return []int64{s[0]}`
over-joins the same way, the conflated `return_dependencies`
trade-off). A scalar-element collection RESULT (`func G()
[]int64`) admits too:
its dep set is the local's conflated one and the caller binds it
like any `t := g()` container. Multi-level index READS (`s[i][j]`)
admit one `elem` descent per level like the imported-member read;
element WRITES stay one-level (`s[i] = v` only).
A range over a call result — `for _, v := range lib.G(a)` and the
explicit `for range *lib.P(a)` deref — admits on the same shape:
the imported member's `result_types` carry the container (or
pointer-to-container) fact even when the composite result keeps
the call `external_or_bodyless`, so the element binds with the
call's dep set like the local `for range g(a)` path already did.
Func-typed arguments still queue their invocations on the call
node, which this path drains itself, and a chan argument promotes
onto the shared queue.
`len`/`cap` on a call result — `len(lib.G(a))`, `cap(lib.M(a))` —
admits through the same member resolution: the length is runtime
container state whose provenance is the call's own dep set (a
callee-produced container, not external state like `len(lib.VA)`),
while a bodyless callee's call still folds minimally (argument
deps evaluated, func-arg invocations drained, chan arguments
promoted onto the external queue, writes stored, and a transfer
recorded on the member). A resolvable callee — local or
`direct_import` — evaluates through `expression` for its effects
only, so `len(lib.S(x))` on a string result admits too. The
pointer operand (`len(*lib.P(x))`), `len` on a bound local other
than the bare composite binding above, and index/field chains keep
the existing closure.
Direct method *calls* (`st.M(x)`, `T.M(st, x)`) admit in the Go
interprocedural frontier's method-call slice below; bound method
*values* (`f := st.M`) admit in the slice after it.

### C07 scalar-element local containers

A *local* `[]T`/`[N]T`/`map[K]T` whose element is scalar or a
pointer — `var a [4]int64`, `a := []int64{x, 7}`,
`m := map[K]V{...}`, `a := make([]int64, n)` — binds under the
same backing-token model a call-result container uses: one
conflated dep set carries every element's provenance, so
`a[i] = v` lands `v|index` in the backing every sharer reads and
`a[i]`/`m[k]`/`v, ok := m[k]`/`for _, v := range a` union the
sharers' sets with the index's own deps. `a[i] = <-ch` in a
select lands the received deps the same way, and `a[i]++` reads
the element's own set plus the index before unioning both back.
`b := a` shares a slice/map backing and copies an array's;
`a = append(a, v)`/`b := append(a, v)` may reuse the argument's
array so the element lands in the shared group, and a definite
`a = []T{...}`/`a = make(...)` reseat mints a fresh backing like
`a :=` does while `a = nil` drops the token (`a[i]` then fails
closed again). A named collection type pins its declared
identities on admit. The element gate keeps the honest closures:
`[][]int64` admits one level deeper in the nested section below,
while `[]func` locals keep their own func-element model. The
mutating builtins `copy`/`delete`/`clear` admit on a bound
scalar-element container operand: `copy(dst, src)` lands the
source's conflated element set on every sharer of `dst`'s group
like an element store (the source takes any evaluable
expression), and when the source is itself bound the two groups
MERGE — `dst[i]` aliases `src[i]`'s backing (a `[][]int64` copy
shares the inner slices). `delete(m, k)` stores the key's deps
into the sharers — an element's survival depends on `k`, the
most the conflated set can say — and `clear(m)` mutates without
a stored value: the set cannot track removal, so a later read
keeps its deps (the sound over-approximation). A shared-group
PARAM operand flags `/caller-backing` unconditionally for all
three — a dep-free mutation (`clear(m)`, `delete(m, 1)`) grows
no dep set but still writes caller memory. On an unbound
operand all three stay opaque. A struct element admits the
same conflated way — `s := []St{...}`, `var a
[N]St`, `m := map[K]St{...}` bind, and a field access on an
element rides the element's own set since the conflated model
cannot distinguish fields: `s[i].F = v` stores like `s[i] =
v`, `s[i].F.G = v` resolves through the selector chain to the
same slot, `s[i].F++`/`s[i].F` reads union the group's deps
with the indexes' own, and a parallel assign (`s[i].F, s[j].F
= x, y`) shares the form. A whole-element map store (`m[k] =
St{...}`) lands like any element write — the only write Go
allows on a map element — and whole-value extraction or range
binding of a supported named struct element preserves Go's
value-copy semantics while reusing collection-field share groups,
including struct-field roots such as `o.A[i]`/`range o.A` and
one-level nested roots such as `s[0][i]`/`range s[0]`.
Scalar-field reads and writes on supported struct elements also
resolve through struct-field container roots (`o.A[i].V`,
`o.M[k].V`, and nested named fields), reusing the same field slot
as identifier aliases while preserving array value copies.
A COLLECTION field on the element extracts like `a := st.F` on a
composite: `b := s[i].F` /
`b = s[i].F` (and deeper `s[i].F.G`) binds the field's own
share group — minted under the root container and joined to
its group — so a store through one extraction reaches the
others, and direct `s[i].F[j]` reads and writes now match that
extraction model; pure array fields reached through an index stay
closed. A *bare `*S` parameter root* is admitted the same way —
`p.A[i].V`, `p.M[k].V`, `p.F[0]` slot on the parameter the way a
slice shares its backing — while local pointer bindings (`q :=
p`) and reseats onto opaque memory (`p = &local`) remain closed.
Pointer-element collections admit too, for any supported root: a
`[]*E` field (or a `[]*E` parameter itself) resolves `a[i].V`
reads and `a[i].V = x` stores through the element pointer the
way a struct element's `a[i].V` does — the element pointer
conflates into the collection's group, and like a bare `*p`
deref the read unions every indirect store and the escaped
bindings' live slots (`a[0] = &e; e.V = x` keeps reporting the
update). Map fields of pointer elements admit reads the same
way — `p.M[k].V` on `M map[K]*E` conflates like the slice —
while a map element's field write (`p.M[k].V = x`) stays closed
because the element is not addressable, and `map[string]…`
closes on the key's side (string indices sit outside the scalar
fragment). An array of pointer elements (`A [N]*E`) stays
closed too. Through a *parameter pointer root* (`*S`, `(*pp)`
on `**S`, or a `q := p` alias) an element's pointer member
resolves one level deeper — `p.A[i].W.V` reads the member's
pointee, caller memory the caller's `indirect_writes` union
already covers, so `*q = …` before the read shows up in it;
a local composite root keeps the chain closed (its pointer
member escapes the slot model). A store through the same
member — `p.A[i].W = q` — lands in caller memory the slot
model does not track, so it folds opaquely like `p.P = q`:
an external-mutation transfer on the pointee identity, and
the stored value plus the index's dependencies unioned into
the root's set and `indirect_writes`. A value-struct element's
pointer member resolves the same way once the field admits a
named element type — `p.B[i].W.V` and `p.B[i].W = q` on
`B []Elem` (and `ss[i].W` on a `[]Elem` parameter) fold into
the collection's group like the `[]*Elem` forms; a
`map[int64]Elem` field admits the *read* (`p.B[k].W.V`) and
stores through the pointer member (`p.B[k].W.V = x`) — only
a direct field store on the map element (`p.B[k].W = q`)
stays closed because Go itself rejects it. Handing the member to a call —
`G(p.A[i].W, x)` — folds the callee's writes through the
pointer into the pointee like `p.A[i].W = q`. Extracting the
element into a name — `x := p.B[i]` (likewise `p.A[i]` and
`p.M[k]`) — binds the copy to the group's deps, and a member
path on the copy that crosses a pointer (`x.W.V`, and the
store `x.W.V = v`) names the extracted element's memory like
the indexed form does; a plain `x.V` read still sees the
copy's own deps. Reassigning `x` clears the share, and a
non-parameter root's extraction (`x := o.B[i]`) keeps the
pointer-member path closed. A pointer member read with no deeper field —
`p.A[i].W`, `p.B[i].W`, `p.A[i].W == nil` — reads the
member's slot value, which names the same group deps as a
scalar leaf. Whole-element stores admit the same way on every
supported root — `p.A[i] = e`, `o.A[i] = e`, `p.M[k] = e`,
`p.A[i][j] = e` — and an inline
*array* member (`o.R[i] = e` on `R [N]E`) folds into the
field's own slot too, since its tokens name no share-group
holder a `o.R[i].V` read could observe the store through.
An array member's element pointer member (`p.R[i].W` on
`R [N]Elem`), a local root's member store
(`o.A[i].W = q`, `o.B[i].W = q`), a nested array member's
element (`o.R[i][j]`), and a `&x` escape into an element
(`p.A[i] = &e`) stay closed.
An explicit `(*p)` deref of a
`*S` param resolves through the same slot machinery as the
implicit deref — Go's grammar parses `(*p)` as a parenthesized
unary `*`, so the root walks unwrap it (a non-`*` unary operand
like `(&x).F` stays closed, and `(*p.A[i])` — an element-pointer
deref — is not a root field chain). A reseat onto another `*S`
parameter is an alias: `p = q` makes reads through `p` resolve on
`q`'s entry slot (with the same may-write `caller-backing`
over-report the shared-container params already make), while a
reseat onto opaque memory closes the root. A reseat back onto the
name's own entry — `q = p; p = r; p = q` — restores the entry
state, while a literal `p = p` is a no-op. Reseats take effect at
the next statement — `p, x = q, p.A[i].V` still reads the entry
pointee — and scope per control-flow arm: if/else arms, each
switch and select clause (case guards evaluate once at the
statement's entry), and a for body's may-not-run path all join
pointwise on the entry state, so an alias only survives when every
path agrees and a may-alias or may-reseat closes the root
afterwards. A clause whose tail statement unconditionally leaves
the construct's post-state contributes no exit state —
return/continue always leave it, and `break L` only leaves it
when the label names an outer construct; a plain `break` exits
the switch/select itself and a `goto` may land after it, so both
keep their end state. `switch { case 1: p = q; return 0 }` keeps
`p` on its entry pointee after the switch. The alias target's name is only
its entry pointee
while it is clean — if the target is itself reseated or re-seated
(`p = q; q = r`, `p, q = q, p`), its slot tracks the new pointee,
and a read through `p` closes rather than mis-attribute the
dependency; a store through `p` still lands in the target's entry
pointee (an over-report is sound there). A
store through the parameter lands in the caller's pointee, so the
param joins the caller-visible set and a grown dep set emits the
`caller-backing` transfer like a shared slice. Two `*S` parameters
that alias the same struct are not tracked as one group — the same
may-alias gap the model already accepts between two slice or map
parameters. A bare `*p` dereference read of a `*S` parameter admits
too — the whole caller-shared pointee carries the parameter's own
dependency like `p.V` does for one member, so `return *p` reports
`p`'s dep — and `q := *p` copies the pointee's member bindings the
way `q := o` copies a value parameter's: scalar members read the
parameter's dep, collection members alias the pointee's backing
tokens (an over-report on divergence is sound, matching the value
copy). One level deeper, `(*pp)` on an unreseated `**S` parameter
is the same caller-shared root one pointer level down — `(*pp).V`,
`(*pp).A[i]`, `(*pp).M[k]`, `(*pp).W.f` and stores through them
resolve like the `*S` versions — `(*pp).A[0] = x` emits the same
caller-backing mutation — and `pp = qq` reseats through the
same alias path (a store through `(*pp)` lands in `qq`'s backing,
so `(*qq).A[0]` observes it). A store into the middle pointer
(`*pp = r`) reseats the `*S` value the caller sees, so the binding
is marked dirty and every later `(*pp)` root stays closed — the
mark lands with the store, so `*pp, x = r, (*pp).V` still reads
the old pointee — while a deeper `**pp = s` writes the struct
pointee itself and leaves the root live. A whole-pointee store
(`*p = s`, `**pp = s`) broadcasts through `indirect_writes` like
any aliased store, so a later element read (`p.A[i]`,
`(*pp).A[i]`, and their `a[i].V` field forms) reports the stored
value's dependency the way `p.V` already did — and an unrelated
`*q = s` may-alias union the same way `(*p)[i]` already did.

A *scalar-payload channel element* admits the same conflated way
— `s := []chan int64{c}`, `var m map[K]chan int64 = {...}` bind
under `_chan_elem_collection` (slice/map only; an `[N]chan` array
stays closed because its copy detaches the names while the queues
inside still share). The stored queues keep their own identity —
`c`'s token seeds into the container's group on bind, on `s[i] =
c`, and on a `s = []chan{c2}` reseat — so a send through either
side lands in the shared set: `s[i] <- x` deposits
`value|index` into every sharer like an element store (and into
`indirect_writes`, since the backing may alias escaped memory),
and `c <- x` shows up in `<-s[j]`; `<-s[i]` reads the group's
conflated union, FIFO order unmodelled like `<-ch`. `b := s`
shares the group like any bound container copy. `append` on a
chan-element collection — `s = append(s, c2)`, `b := append(s,
c2)` and `var b = append(s, c2)` — admits like the scalar
`append(a, v)` slice: the result may reuse the argument's
backing, so it keeps the group's tokens, and each appended
`chan` argument joins the result's share group exactly like a
`[]chan{c2}` literal seed — carrying the queue's token in the
result's set is not enough, since a member only reads and
writes through the group once its own token entry exists.
The remaining closures are nested containers such as
`[N][M]chan`; scalar-element `chan chan T` containers use the
separate queue-group model below.

Extracting a bound channel element — `d := s[i]`,
`var d chan T = s[i]` or a plain `d = s[i]` reseat, on a
`[]chan` or a `map[K]chan` alike — mints `d` as another member
of the container's share group rather than copying the
container's token set (a copied frozenset diverges the first
later `s[j] = c2` union grows the root's set past it). `d`'s
own slot takes the element read's deps, so `d <- x`, `<-d`,
`for v := range d` and a member passed as a chan parameter all
see the group's conflated queue deps — and a `s[j] <- x` send
lands in `d`'s slot the same way it lands in every sharer's.
Reseating behaves like any rebind: `d = t[i]` detaches `d`
from the group it left before joining `t`'s (pre-state
resolution on a parallel assign), a conditional `if f { d =
t[i] }` externalises like the maybe-skipped rebind *and*
mints the new membership, and `d = make(chan)` parks the old
queue under a surrogate so `<-s[0]` keeps reading what `c`
serves. The honest closures stay: `d := s[0][0]` on a
`[][]chan` extracts nothing (the nested-element gate already
declines it), `[N]chan T` arrays admit the same way — the copy
`b := a` still names the same queues, so it joins `a`'s share
group like a slice copy. `[]chan chan T` uses the separate
queue-valued element group model described below; `[][]chan` and
`[N][M]chan` nests remain closed.
`close(s[i])` admits — an untracked synchronization fact on a
local group, and a caller-visible effect recorded on each
param/external member like `s[i] <- x`. `for v := range s[i]`
admits through the bound root: the element operand registers
the root binding as the range's channel, so the per-pass
rejoin unions the whole group's deps, and `select`
alternatives on `s[i]` / `s[i] <- x` resolve through the same
operand path. `[][]chan` extraction stays opaque.

A chan-element collection PARAMETER or RESULT admits like the
scalar-element form — `func F(s []chan int64)`, `func G()
[]chan int64`, `m map[K]chan int64`: the parameter seeds its own
share group (sibling `[]chan` params share one group like
`G(a, a)` does for slices), so `s[i] <- x` deposits into the
group and lands in `indirect_writes` — a callee's send through a
`[]chan` parameter reaches caller memory exactly like `s[0] =
v` does. A `[]chan` result binds like the local `s :=` form.
`[N]chan` signatures stay closed here; scalar-element chan-chan
container signatures are described below.

The same conflation covers a chan-element container living in
*external* state — a package-level `var GS []chan T` /
`var GM map[K]chan T` / `var GA [N]chan T`, or an imported
member `lib.GS[i]`. The element queues have no declared
identity of their own, so `GS[i] <- x`, `<-GS[i]`,
`close(GS[i])` and `for v := range GS[i]` record an imported
CallTransfer on the *container's* identity exactly like a
`lib.VA[i] = v` member write: the send's value ∪ index deps
broadcast into `indirect_writes`, the read returns
`indirect_writes` plus the index's own deps, and select
alternatives resolve through the same send/receive operand
paths. Extracting `d := GS[i]` (or `var d = GS[i]` /
`var d chan T = GS[i]`) binds `d` as an external name: sends
through it broadcast into `indirect_writes`, while reads union
that set with the index's dependencies; sends through the extracted
name also retain the extraction's index dependencies. The extraction itself
records a transfer on the container identity, so a callee's
extraction propagates to callers just like `ch = g()` does.
Plain reseats (`d = GS[i]`) and conditional reseats are admitted
through the same external-name path. A reseated group member
keeps its old group membership as a sound over-approximation.
Local chan-element share groups also retain external members added
by literals, element stores, or `append` — including `GC` /
`lib.GC`, `GS[i]`, and extracted external names. Reads and sends
through any group member (including extracted aliases, range,
select, and channel-call arguments) join `indirect_writes` and
record the corresponding imported transfer; group merges and copies
preserve that external marker.
The honest closures mirror the bound case — `[][]chan` nests,
non-scalar payloads outside the scalar-leaf nested-channel queue
forms below, comma-ok `d, ok := GM[k]`, and a
`map[string]chan` variable key stay closed or unreachable (a
`string` value is never producible).

### C07 scalar-leaf nested-channel containers

Local `[]chan chan ... chan T`, `[N]chan chan ... chan T`, and
`map[K]chan chan ... chan T` containers model one conflated local
nested-channel queue group, identified by the container binding.
Every channel reachable at any nesting level joins that group, and
the leaf `T` is an integer or boolean.
Elements from literals, `make`, zero-value arrays, `append`, and
indexed stores join that group; an element that is already an
external queue promotes the group and carries its selectors and
parameter origins. Conditional stores union possible members and
externality. Indexing the container in a queue position therefore
acts like the same queue group: sends, receives (including
comma-ok), nested receives, received-channel operation targets,
`close`, `len`/`cap`, `range`, `select`, and extracted aliases all
resolve through the group. `len`/`cap` of the container itself
remain pure. Range-bound elements alias the same conflated group.

Nested-channel container parameters and package/imported
`[]chan chan ... chan T`, `[N]chan chan ... chan T`, and
`map[K]chan chan ... chan T` sources act like external indexed queue
sources. Element reads retain the container's parameter origin and
index dependencies; external stores and operations propagate through
the container identity. As with named local queues, local-only
operations keep `none_in_supported_fragment` effects.

Container values of slice, map, and array type can escape while
retaining the identity of their conflated queue group. Returning a
local container returns the group's read dependencies and promotes
the group externally; storing it to a package or imported variable
records the write, promotes the group, and broadcasts dependencies
to later joins. A result container from a direct same-package call
is bound as an external container, so element operations preserve
the imported-transfer behavior. Passing a local container to a
same-package direct call, `go` call, or `defer` call promotes the
group just like passing one queue. Arrays share the referenced
queues despite value-copying the array header. These escapes apply
recursively when the container elements are nested queues.

A direct outermost composite-literal return of local chan-chan queues
is admitted; container-value closure capture, taking its address,
struct-field store or return, nested containers such as
`[][]chan chan T`, and non-scalar leaves such as
`[]chan chan ... chan []T` remain closed.
Plain imported-call arguments are admitted.

### C07 scalar-element *nested* local containers

Exactly one level of nesting over a scalar-element collection
admits under the same conflated backing-token model —
`var a [][]int64`, `a := [][]int64{{x}}`,
`m := map[K][]int64{...}`, `a := [N][]int64{...}`,
`a := make([][]int64, n)` and the named-type forms all bind, and
an uninitialised `var a [][]int64` mints an empty backing like
the single-level case. A two-index element store
(`a[i][j] = v`, `m[k][i] = v`) resolves the inner operand
`a[i]`/`m[k]` back to its bound container, unions both index
deps with the value's, and lands them in the backing every
sharer reads; `a[i][j]` reads the conflated set through the
multi-index descent (a `select` receive `a[i][j] = <-ch` and
`a[i][j]++` follow the store/read rules identically). `b := a`
shares the backing, `a = [][]int64{...}`/`a = make(...)` reseat
mints a fresh one, and a one-level element store (`a[i] =
sub-slice`) lands the inner container's deps in the root's set
like any element write. A donor whose type is an array still
shares when its element chain bottoms in a slice/map header —
`s[0] = sub` on `[1][1][]int64` with `sub : [1][]int64`
embeds `sub`'s headers, so `sub[0][0] = x` reaches
`s[0][0][0]` reads (`[1][1]int64` donors keep the value-copy
closure). Extracting an inner container by
index — `b := a[i]`, `b := m[k]`, `var b = a[i]` — binds `b`
into the root's share group (the conflated model makes no
per-slot distinction, so `b` reads and writes the whole
backing the root and its other sharers see), and an element
read on a bound nested operand is admitted by the
imported-index-read gate since its element is itself a
scalar-element collection. A plain `b = a[i]` reseat (and
`b = m[k]`) lands `b` on the same group — it replaces `b`'s
tokens, so reseating away detaches `b` from the group it
left, and a parallel-assignment RHS resolves `a[i]` at the
pre-state (`a, b = sub, a[0]` names the group `a` held
before the reseat). The nesting generalises to ARBITRARY
depth: `[][][]int64` and deeper scalar-element chains bind
the same way (each level pins its declared identities), a
store `a[i][j][k] = v` unions every index's deps into the
root's backing, `a[i][j][k]++` and `a[i][j][k] = <-ch`
follow identically, and multi-level extraction
(`b := a[i][j]`, `b = a[i][j]`, donors like
`[][]int64{a[i][j]}` or `[][][]int64{sub}` — including the
elided `{{sub}}` form — and the
opaque-callee argument `lib.U(a[i][j], v)`) joins the
root's share group whenever the extracted value still
shares the backing's headers — a slice/map element, or an
array embedding one (`b := a[i]` on `[N][M][]T` copies
`[M][]T` headers that alias the root's backing). The honest
closures stay honest: extracting from an unbound operand
stays closed because the operand never joined a share group
(a parameter operand registers its own group at entry — see
the section above), extracting
an element that shares nothing (`a[i]` on `[][M]T`,
`a[i][j]` on `[][M][K]T`) stays closed — it is a pure value
copy with no shared backing — `[]func` nested shapes keep
their own func-element model.
`append(a[i], v)` and the deeper `append(a[i][j], v)` bind
like any other element carrier: the appended slice may
reuse the extracted element's backing, so `b := append(a[i], v)`
unions the root's share-group tokens into `b` beside the
fresh result token (an unbound/array operand stays closed),
and the appended elements' deps land in the root's sharers
like the plain `append(a, v)` slice case; an appended
SLICE or MAP element (`append(a[i][j], sub)`) unions the
element's share group into the result's, so a store through
either side reaches the other, while a spread `sub...` or
array element copies and stays detached. A FIELD member
shares the same way at any depth — `a := s.F`
on a `[][]int64`/`[][][]int64`/`map[K][]T`/`[N][]T` member binds
`a` into the field's group like the single-level form, and an
array member EMBEDDING a collection (`[1][]int64`) shares its
copied header instead of minting a fresh value copy. A whole
deep array arg (`[1][1][]int64`) handed to an opaque callee
shares caller memory through its innermost `[]int64` headers,
so the callee's writes land in every sharer's set. The same
share applies wherever an index operand
carries the element: a literal donor (`c :=
[][]int64{a[0]}`), a slot store (`a[i] = a2[j]`), and an
opaque-callee argument (`lib.U(a[i], v)` — its writes land
in every sharer's set like `a[i][0] = v`). An element
store through a chain that crosses a slice/map level is
never treated as inline-array storage — the array-roots
gate only applies while every crossed container level is
an array (`a[i][j] = v` on `[N][M][]T` stays inline; a
slice level anywhere in the chain leaves the conflated
holder model).

Local struct literals link tracked collection-valued fields
to the same slots used by field extraction and assignment
(`s := S{A: a}`, including positional and nested literals);
copies of memory-sharing structs retain those slots. Writes
through effectful call arguments, receivers, and collection
field arguments flow to the slot holders and later field
reads. Non-identifier struct arguments and value receivers passed as
composite literals or value selectors use the same tracked field slots
as a bound temporary. Struct call results (`s := mk(a)`, `lib.Mk(...)`,
methods) mint a fresh backing joined with the backings of
memory-sharing arguments; reseating one alias re-keys its
field slots to a surviving alias; parallel assignments
(`s, t = t, s`, rotations) read every struct RHS from the
pre-assignment state, and a non-identifier RHS that reads a
struct LHS of the same statement stays closed. Plain array
fields and scalar-only structs remain value copies.
Pointer-root or otherwise untracked field shapes stay closed
rather than inventing a backing relationship.
Direct operations on collection-valued fields are admitted as implicit
extractions. Fixed-size scalar array fields on named value structs admit
full-depth indexed reads and writes for array-only chains ending in scalar
elements, whole-field stores, `len`/`cap`, and index-only range while
retaining value-copy semantics; partial row operations, pointer roots and
other plain array fields stay closed. Comma-ok map reads and select-receive
targets on direct fields remain closed.
Caller-visible container element reads observe pointer writes and opaque or
dynamic call writes through shared backing tokens; imported calls remain out
of scope.

### C07 per-statement read attribution

`FunctionSummary` now also emits `statement_reads`: one
`(span, deps)` record per walked statement naming the parameter
ordinals its evaluation read. `expression` appends every dep set
it returns to every open statement frame, so a read inside a
nested block attributes upward (`if c { y = x }` records `x` on
both the assignment and the `if`); loop fixed-point re-passes
union into the same span key, so records stay idempotent.
Spans use the same file-indexed addressing `CallTransfer.span`
uses. The records serialize only on available summaries — a
gapped walk would misattribute — and round-trip through
`from_dict` under the usual ordinals-`<`-parameters invariant.
Like `calls`, `statement_reads` is descriptive: it never feeds
`for_function`/`stale_dependents`. TS/Rust/Sol summaries emit no
field; consumers treat absence as "not provided".

### C07 labelled jumps and `goto` in summary bodies

`L:` on a `for`/`switch`/`select` registers on the construct's frame, so
`break L`/`continue L` resolve against the labelled loop-or-switch —
the jump marks every construct between the statement and the labelled
one exited exactly like an unlabelled jump marks its innermost frame, and
later writes stay may-assignments. A label wrapping any other statement
is inert syntax. A forward `goto` joins the same over-approximation: it
marks all open constructs exited and every later statement conditional,
since any statement between the jump and its label may never have run —
the walker does not resolve goto targets, so an unreachable label
degrades to the conservative may-write model rather than a gap. A
backward goto — one whose label was already processed — would need a
fixed point this fragment does not compute and stays
`unsupported_statement`, as does a labelled jump whose name resolves to
no enclosing labelled frame (or, for `continue`, to a non-loop
construct); `defer` and `go` remain outside the fragment.

### C06 imported generic instantiations

An explicit instantiation of an imported generic function —
`lib.G[int64](x)` — now classifies as `direct_import` when every
type argument and every instantiated parameter is a basic type and
every instantiated result is scalar. The
producer resolves the instantiation through `types.Info.Instances`
(newly recorded on the info map) and applies the same scalar-result
rule as `directImportID`, against the *instantiated* signature —
at any arity, with the arity declared on the call record's
`results` field exactly like a non-generic callee. The
dependency model is the existing opaque shape: the result depends on
every evaluated argument, and the member record's
`signature_type_ids` — which cover the generic's declared signature,
including its type-parameter identities — pin the call site as with
any other imported call.

The basic-or-named restriction keeps the admitted surface pinnable:
a substituted type-parameter identity is declared nowhere, so a
named/alias type argument (`lib.G[lib.T](v)`) carries its identity
on the call record as `type_arg_type_ids` — pinning `lib.T` at this
call site alone, where the member record's signature pins could
never reach. A *declared* named parameter
(`func G[T any](v T2)`) is already pinned by `signature_type_ids`;
only composite instantiated parameters (`[]T`) are rejected, as
outside the scalar fragment. A composite type *argument* pins every
named identity inside it — `G[*lib.T](v)`, `G[[]lib.T](v)` and
`G[map[string]lib.T](v)` all record `lib.T` — while a signature,
struct, interface or type-parameter argument carries no pinnable
identity and keeps the call closed (`G[func()](nil)`). Nested named
arguments pin every identity they contain — `G[other.N[lib.T]](v)`
records both `N` and `T`, so redeclaring either stales the call
site. The consumer admits the call through the
same `direct_import` path — tree-sitter parses the single-type-arg
form `lib.G[T](x)` as `type_conversion_expression`, so a dedicated
arm maps that node shape onto the recorded call; multi-type-arg
forms already arrive as `call_expression`. An *inferred*
instantiation `lib.G(x)` or `G(x)` arrives as an ordinary
`call_expression` and takes the same gate through `info.Instances`:
the call is admitted when every inferred type argument is basic,
named, alias or a composite constructor of those — no explicit
`[T]` syntax is required.

Boundaries: inferred calls `lib.G(x)`/`G(x)` take the same gate —
`info.Instances` records the inferred type arguments either way,
so an inferred instance admits the call at its instantiated arity (partial explicit forms `lib.G[int64](x, c)`
with inferred rest-arguments follow too). An argument inferred to a
named type — `lib.G(t)` with `t` declared `lib.T` — admits with the
`lib.T` pin recorded on the call, exactly like the explicit
`lib.G[lib.T]` form. A dot-imported instantiation `G[int64](x)`
follows the same rule through the unqualified-callee path —
admitted with basic or named type arguments alike (`G[lib.T](v)`
pins `lib.T` on its record). Instantiated generic *type*
conversions are admitted too — `lib.S[int64](x)` and
`lib.S[lib.T](x)` behave like any scalar `T(e)` conversion
(operand deps flow through) when the target member declares a
scalar underlying (`type S[A any] int64`); the consumer walks the
whole type expression and pins every named identity it contains —
`lib.S[other.N[lib.T]](x)` pins `S`, `N` and `T`, and composite
argument constructors pin their elements — `lib.S[*lib.T](x)` pins
`S` and `T`. A composite
underlying (`type C[A any] *A`) or an unpinnable argument
(`lib.S[func() int64](x)` — a signature carries no identity) stays
closed. Local
generics and methods are unchanged and closed. A multi-valued instantiated callee
(`a, b := lib.G[int64](x)`) unpacks at its declared `results`
arity through the same tuple rule as any `direct_import` call —
including the single-type-arg `type_conversion_expression` shape
in RHS position. A void
instantiated callee records its
argument-dependency union like any other `direct_import` transfer.

### Go deep-analysis: same-package method calls (`st.M(x)`, `T.M(st, x)`)

A `direct_local` call on a same-package method now resolves through
the callee's summary like a plain local call: the producer emits a
`receiver` parameter on every function record (null for plain
functions) and flags the call `method` for a method value
(`st.M(args)`) or `method_expr` for a method expression
(`T.M(st, args)`). The receiver binds as leading parameter index 0 —
a `st.M(args)` call evaluates the selector operand for its deps and
prepends it to the actuals; `T.M(st, args)` already carries the
receiver as argument 0, so arity is `parameters + 1`. The callee
summary's `return_dependencies` index 0 is the receiver, so
`st.V + x` reports the deps the caller seeded `st` with.

Admission stays narrow: the receiver must be a concrete named type
(`localReceiverOK` unwraps aliases and one pointer layer, rejects
interface underlyings, type parameters and instantiated types), the
callee must be non-generic, non-variadic and single-result like
every other admitted function, and the receiver's declared fact must
sit in the admitted kinds (scalar, pointer, struct, scalar-element
`chan`). Result-less or generic/variadic/interface-receiver
methods stay closed; method calls on imported named types keep the
`direct_import` path. An effectful pointer-receiver callee
conservatively folds the write deps into the receiver binding —
`st.M()` on a value variable auto-takes `&st`, so the fold applies
even when the operand isn't `&st`-shaped.

### Go deep-analysis: bound method values (`f := st.M`, `f := St.M`)

`f := st.M`, `var f = st.M` and `f = st.M` record the
`(method, receiver)` binding pair under the bound name — the
selector's field resolves to a same-package method whose receiver
operand is a bare identifier. A type-name operand (`f := St.M`, a
method *expression* value) records `(method, None)` instead — the
caller passes the receiver as argument 0, exactly like the direct
`St.M(st, args)` call, so arity is `parameters + 1` and arg 0's
deps sit at actuals[0]. A `g := f`/`var g = f`/`g = f`
identifier copy propagates the pair like closure captures, and any
other RHS clears it. A `f(args)` call then resolves through the
method's summary exactly like `st.M(args)`: the recorded receiver
re-resolves at the CALL site (a `st = …` reseat between bind and
call tracks the current set), sits at actuals index 0, and an
effectful `*T`-receiver callee folds its write deps back into the
receiver binding — into `indirect_writes` plus escaped bindings
when the receiver itself is a bound pointer.

A conditional rebind (`if c { f = t.M }`) drops the pair rather
than pick an alternative — the call then runs opaque like any
unrecorded local func var, unioning every may-rebind's receiver
deps. A computed receiver (`g().M`) records nothing — calls
through it keep the `indirect_or_selector` record closed like
before.

### C06 imported method calls on concrete named types

A method call `recv.M(args)` now classifies as `direct_import` when
the method is declared in a resolved imported unit on a concrete
named receiver type (`lib.T`, or a pointer to one) and whose results
are all scalar — arity travels on the record like a plain function's.
The producer resolves the selection
through `types.Info.Selections` (field selections keep the existing
classification) and marks a method value `method: true`, so the
consumer also evaluates the receiver expression: the result depends
on the receiver and every evaluated argument. `x.M(y)` on a
parameter, `lib.V.M(x)` on package state (its var read still records
the staleness transfer) and `lib.K.M(x)` on a constant all share the
path. A composite imported var receiver admits too — `lib.VS.PF()`
on a struct var reads external state like the member itself, so it
is dep-free and records the imported transfer against the member.
The same admission reaches a composite *element* of an imported
container: `lib.VSS[i].PF()` and `lib.VSM[k].VF()` read external
state like the container, carry only the indexes' dependencies
(innermost-first, like every index chain), record the transfer on
the container member and pin its whole fact tree — while a computed
operand (`g()[0].PF()`) still names no member and stays closed. A
method *expression*
`lib.T.M(recv, args)` records `method_expr: true` so the consumer
applies the receiver rules to the leading argument — `lib.S.PM(lib.VS,
x)` admits through the same composite-var receiver read
(`(*lib.T).PM(t, x)` on a scalar receiver still evaluates it like
any argument).

Pointer-typed parameters and results now belong to the signature
fragment: a `*lib.T` parameter reports `kind: "pointer"` with the
pointee's named/alias identity on `type_id`, and
`signature_type_ids` unwraps one pointer layer so `func Take(t *T)`
pins `T` exactly like `func Take(t T)`. The consumer admits the fact
wherever a scalar is allowed — parameters, results, `:=` and `var`
locals — so `func F(t *lib.T, x int64) { t.PM(x) }` summarizes with
the usual receiver-plus-arguments union, and `(*lib.T).PM(t, x)`
follows the method-expression path. The dep model tracks the
*binding's* index, not the pointee's state — dereferences, field
access on a bound base (`t.f`, `(*t).f`), indexing and mutations
through the pointer stay outside the
fragment (`effects` already reports every admitted body as
`unknown`), so `return *t` is still `unsupported_expression`. A
pointer to an unnamed or composite pointee (`*int64`, `**T`,
`*struct{…}`) pins nothing — the pointee names no type identity —
but the binding still tracks its dep set like any scalar.

Pointer *values* flow through the fragment too: `&x` inherits its
operand's dep set like any unary (non-addressable operands fail the
producer's own type check), imported calls may return pointers
(`lib.R(t)` — `allScalarResults` admits a `*T` result since the
arg-union dep set is the same), and pointer-typed imported `var`
reads (`lib.PV`) stay dep-free like scalar member reads while still
emitting the staleness transfer. A mixed tuple
`a, b := lib.RR(t)` unpacks at its declared arity with a `*T`
binding storing the pointer half. Passing `&x` to an imported
callee hands it a writable alias of `x`, so afterwards `x`
conservatively depends on every call argument. A pointer result
never admits a generic callee through its declared signature —
`func G[P any](v P) *P` still goes through the instantiation
gate. A field write *through* a pointer-typed parameter lands only
in caller state — struct-typed bindings cannot exist in the
fragment, so `t.f = v` can never overwrite a tracked binding — so it
admits as an opaque write target: the base must be a bound
parameter or local identifier carrying a declared named-type
identity, the RHS still evaluates for its calls, and the stored
value's dependencies accumulate into the base binding — a later
`t.M()` can observe the write through the pointer, so the dep set
must keep it. The store is an external mutation, so it also records a
zero-argument imported transfer against the base's declared type
identity — `effects` reports `unknown` like an imported var read,
and a redeclaration of that type flags the summary via
`stale_dependents`. A `(*t).f = v` base spells the same auto-deref
out and admits identically; `(**t).f` stays closed. A nested
selection `t.W.f = v` walks the same
way the field read does: the operand chain resolves through
pointer-typed field members (`W *W2`), every traversed
member pins, the deepest pointee's identity records the transfer,
and the stored value's dependencies still accumulate into the root
binding `t`. A struct-valued intermediate (`t.A.B = v` on `A S3`)
or a double deref (`**t`) keeps the write closed. A `*t = v` dereference store admits too, routed
through the escaped-binding fold: `p := &x` may aim the pointer at
any tracked local, and dep sets carry indices, not identities, so
the store cannot be proven to miss one — unioning the stored
value's dependencies into every escaped binding is the same
over-approximation `*lib.PV = v` uses, and the pointee's declared
identity records the external mutation (`effects` reports
`unknown`). Beyond the escaped fold the stored deps also accumulate
into the indirect-write set every dereference read unions back —
`*t = v; return *t` reports `v`'s dependencies. The gate classifies
the pointee exactly like the
`*lib.PV` read: the operand must be a bound identifier whose
pointer names a scalar or pointer pointee, so `p := &b` on a
builtin `int64` (unnamed `*int64`), `**t = v`, and a computed
pointer stay closed; `(*p)++` and `*t--` admit the same way
without a fold — an increment is provenance-preserving, so an
aliased binding keeps its deps. Unbound bases keep the statement
closed, as does `&` on anything but a fragment operand.

Writes to imported `var` members admit through the same external-
mutation rule: `lib.V = v`, `lib.VA[i] = v` and `lib.VS.f = v` — and
their dot-imported forms — resolve the LHS through selector and
index operands until a `var` member names the target, then record a
zero-argument imported transfer against the member's own identity
(`effects` reports `unknown`, and the member's declared type
identity — plus a container element's — pins for
`stale_dependents`). A `*`-dereference operand unwraps the same
way when it names a pointer-typed `var` member whose pointee is
named: `*lib.PV = v` and dot-imported `*PV = v` store through the
member into package state and pin the pointee's identity through
the pointer fact's `type_id`. Deeper pointee trees declare their
named uses on the member record's `pointee_type_ids` — a fully
unnamed pointee (`*lib.PU = v` on `*int64`, `(*lib.PA)[i] = v` on
`*[4]int64`) resolves to the empty list and admits because the
member's own identity covers the declaration completely, while a
deeper named use (`*lib.PPV` or `**lib.PPV` on `**T`) declares and
pins `T` exactly like a type argument. Only a pointee shape the
key cannot declare stays closed — an anonymous struct hiding a
named use (`*lib.PSTR` on `*struct{ F T }`) or a signature tree —
a `*chan T` pointee resolves its `T` element like a slice or map
and admits. A shape the walk cannot reach stays closed because
the member's own identity would not flag a redeclaration inside
it. A non-pointer member behind a `*`
stays closed (uncompilable), and any unary operator other than
`*` never unwraps. A deref through a pointer-typed *field* member
resolves the same way: `*lib.VS2.P = v` resolves the field like a
field read, records the field member's identity as the write
target, and pins the base member's identity beside the field's —
the same `pointee_type_ids` rule decides the field's pointee, so
`*lib.VS3.PU = v` on `PU *int64` admits through the empty list
while an undeclarable pointee shape stays closed. A deref store can also alias a tracked binding — `lib.PV =
&x` aims the member at `x` — so any binding `&x` escaped marks the
binding, and a `*lib.PV = v` write unions the stored value's
dependencies into every escaped binding (`return x` then reports
the stored value's dependencies too) and into the same
indirect-write set dereference reads observe (`*lib.PV = v; return
*lib.PV` reports them too). Member reads stay dep-free — no binding
tracks member contents — and a nested index
expression still evaluates whenever it could record something — a
call (`lib.VA[f()]`), a conversion, or an imported member read
(`lib.VA[lib.V]`, whose pin `stale_dependents` needs) — while a
literal or plain-name index (`lib.VM["k"]`) needs no evaluation.
Compilable closed cases: a computed operand
(`g()[0] = v` or `*g() = v`) names no member, and a `const`, `func`
or `type`
member names no writable storage. Inc/dec statements
(`lib.V++`, `(*lib.PV)++`, `(*lib.PU)++`) route through this same
gate — the `pointee_type_ids` rule applies to them too.

An index read of an imported container var — `lib.VA[i]` — admits
through the member record's new element fact: slice and array type
facts (`[]T`, `[N]T`, and named or alias types whose underlying is
one) carry an `elem` fact, so the consumer can classify what an
element read returns. The element is external state like the
container var itself — the result contributes only the index's own
dependencies while the read still records the imported transfer,
reports `effects` as `unknown`, and pins both the container's
declared identity and the element's named identity
(`[]lib.T` pins `T`; `var VNS NS` pins `NS`) for `stale_dependents`.
The operand resolves like a member read: a package-qualified name, a
dot-imported name, or parentheses around either. The element fact
must be scalar or pointer — a struct or nested-slice element is a
value the fragment's model cannot hold — and anything that names no
member stays closed: strings declare no `elem` fact, and a
computed operand (`f()[i]`) is not a member name. A nested index
chain (`lib.V2[i][j]` on `[][]int64`, `lib.VM2["a"]["b"]` on
`map[string]map[string]int64`) admits too: each level descends one
`elem` fact and the result unions every level's index deps —
evaluated innermost-first in Go's order — while intermediate
container facts pin their own named and key identities; the final
element keeps the scalar-or-pointer rule (`lib.VSM[k]` yields a
struct and stays closed). An index write (`lib.VA[i] = v`) takes
the imported-var-write path above instead — the LHS never reaches
the read gate.

A single-value read of an imported map var — `lib.VM[k]` — admits
through the same gate: map type facts carry both a `key` fact and the
`elem` value fact (`map[K]V`), the result carries only the index's
dependencies, and the named key's identity pins alongside the
container's and value's. The index expression must still be a
modelled shape — a literal index (`lib.VM["k"]`) is dep-free like a
constant (`true`/`false` go through expression resolution instead,
since Go allows shadowing the predeclared names as variables) — and
the comma-ok form `v, ok := lib.VM[k]` admits too: it binds
exactly two names on a map member, so the `:=`, `var` and plain
`=` tuple paths unpack the pair like a two-result call — the value
read and the presence flag each conservatively take the read's own
dependencies. A composite-typed element (`lib.VSM[k]`) stays closed
the same way the single-value read does. A comma-ok read on a
nested chain admits when the outermost index's container is still
map-typed — `v, ok := lib.VM2[k1][k2]` descends one `elem` fact per
level and requires the surviving container fact to be a `map`, so
the root need not itself be a map (`v, ok := lib.V[i]["k"]` on a
`[]map[K]V` admits), while `v, ok := lib.VM2[k]` (whose value is a
map the model cannot bind) stays closed. A member
write (`lib.VM[k] = v`) pins the named key's identity too.

The member record's `signature_type_ids` for a method now include
the receiver's own named-type identity — `x.M(y)` pins `T` even when
`x` is a plain local variable that names `T` through no member read,
so redeclaring `T` still flags every admitted caller.

An *instantiated* receiver admits through the same gate: `x.GM(y)`
with `x: lib.GT[lib.T]`, and the method expression `lib.GT[lib.T].GM`,
classify as `direct_import` when every type argument of the receiver
is basic, named, alias or a composite constructor of those — the
collected identities ride on the call
record's `type_arg_type_ids`, the same wire key an instantiated callee
uses, so a type-argument redeclare stales every admitted caller.
Interface dispatch admits method expressions and method-value calls
on interface-typed parameters and their plain copies with integer,
boolean or pointer results. Receivers may also be selector chains
through non-pointer named-struct fields rooted at a value-struct
parameter and ending at an interface field, or a `direct_import` call
result whose expression is representable. Method-value bindings on
those parameter field chains are admitted too. Local-struct and
package-variable roots, pointer roots or crossings, element receivers,
local call results and type assertions stay closed. Interface results,
concrete-to-interface uses and promoted methods stay closed.
Defined-from-struct and imported-struct roots stay closed.
An interface method value (`f := i.M`) and a named interface method
expression (`f := I.M`) may be directly called, and a plain function
value copy preserves the record. Bound method values freeze receiver
dependencies at binding time; invoking them with `go` or `defer` is
admitted, while passing, returning, capturing, storing or comparing
the value stays closed.

### C06 multi-valued imported results

A `direct_import` callee whose results are all scalar now classifies
at any arity — the producer's gate moved from `scalarResults` (zero
or one result) to `allScalarResults` (every result integer/boolean)
for plain functions, methods and method expressions. The call record
declares the arity on an optional `results` key — emitted only for a
`direct_import` callee with more than one result — so the consumer
can admit tuple unpacking `a, b := lib.F(x)` only when the declared
arity matches the left-hand width. Each result carries the same
over-approximated dependency set (the union of the receiver's and
every argument's dependencies), so a single call evaluation stores to
every name — per-result distinction is impossible inside the opaque-
callee model and unnecessary for dependency purposes.

The unpack positions are exactly the compile-valid ones: short
variable declarations, multi-name `var` specs (`var a, b = lib.F(x)`)
and plain tuple assignments (`a, b = lib.F(x)`) — which also means
`for`/`if`/`switch` initializers admit the shape through the same
statement path, and `_` slots still evaluate-and-discard. A spread
call `lib.W(lib.G(x))` needs no arity check: the inner call's unioned
dependencies already cover the outer result in the `direct_import`
model, while a spread into a *local* callee stays `callee_unavailable`
via the parameter-count check. A multi-valued call evaluated and
discarded (`lib.G(x)`) was always an admitted `expression_statement`.

Boundaries: a composite result anywhere in the tuple keeps the call
`external_or_bodyless`; an arity mismatch between the record and the
left-hand width stays `unsupported_statement`, as does a parenthesized
RHS unwrapping to anything but a matching call. The instantiation
gate (`lib.G[T](x)`) shares the tuple rule — a multi-valued
instantiated callee unpacks at its instantiated `results` arity
(composite instantiated results still stay closed). The `results` key is optional on
the wire — reports predating it keep validating — and it is rejected
for any non-`direct_import` call, for arity below two, and for a
non-integer value. A forged arity that still validates is caught at
the consumer: the left-hand width must equal it.


### C06 declared summary manifests

`GoSummarySet.to_dict()` serializes a derived summary set into a
detached manifest under `mumei.go-scalar-parameter-deps/v1`: the
context key the set was derived against plus each function's declared
fields — binding identity, key, parameter/result type facts (with
element/key chains), sorted return dependencies, call transfers
(target, per-argument dependency sets, result set, span, `imported`
marker), gaps (reason, span, callee) and pinned type identities.
Serialization is metadata only: it carries no bytes and claims no
acceptance, and derived properties (`available`, `effects`) are not
stored — a reader recomputes them from the same declared fields. A
`None` dependencies field serializes as an absent key, never a null
that could read as parameter-independent, and absent optional
fields (`result_type`, `pinned`, `callee`, `imported`) stay absent
rather than defaulting. Spans serialize with their file index for
package units and without it for single-file units; anything that is
not a declared `ByteSpan`/`FileSpan` fails statically rather than
serializing a foreign shape. The set also declares the `target_arch`
it was derived for — scalar widths are arch-dependent while binding
identities are not — so a reuse route can refuse a mismatched unit.

`GoSummarySet.from_dict()` rebuilds a declared set with the same
boundary discipline as the C11 snapshot restorations: strict key sets
at every level, the schema name matched exactly, member lists bounded,
function identities unique, dependencies validated as non-negative
ordinals inside the declared parameter count, and spans shape-checked
(byte ranges are metadata — there is no source here to bound them
against, so a consumer that slices bytes must re-derive bounds itself).
A restored set is **declared data, not derived truth**: reuse still
goes through `for_function`/`for_package_function` — which reject
after any source, target or report change — and `stale_dependents`
still flags dependents of replaced identities, so a foreign or stale
manifest can only describe reuse, never authorize it.

This is a **handoff surface, not a route**: a host may persist the
manifest or feed it to a scheduler, but no I/O, transport, versioning
negotiation, evidence semantics, plugin, runner/scheduler, or default
audit/CLI/MCP route is added; TS/Solidity/Rust adapter summary sets
keep their own shapes. C06 stays partially delivered — the manifest
is the first declared output surface a consumable route can bind.

### C06 declared summary manifest route (go-summaries)

`python -m agent go-summaries` is the first consumable route over the
summary manifests: it runs a provisioned `tools/go-types` helper on
explicitly declared sources, validates the report through the
fail-closed snapshot reader and emits the
`mumei.go-scalar-parameter-deps/v1` manifest from
`GoSummarySet.to_dict()` on stdout (or `--output`). One `--source`
selects the single-file profile; repeated `--source` selects the
package profile, declaring each file under its basename (duplicates
are a static error). `--target-arch` names the `gc` target the report
is validated against and `--timeout` bounds the helper spawn.
`--import <IMPORT_PATH>=<FILE>` declares one file of an importable
package unit (repeatable per file and path; requires a multi-file
`--source` unit) — the helper resolves imports only through the
declared map, never disk, network or the toolchain.

The route stays inside the declared boundary: it never discovers
projects, resolves imports or chooses tools — the operator provisions
the binary (`--go-types`) and supplies every byte the helper reads.
A nonzero exit, any stderr or a non-`ok` report status fails closed
before parsing, and the emitted manifest remains declared data — a
reader still recomputes derived properties and reuse still goes
through `for_function`/`stale_dependents`. Audit consumption is
wired (`--enable-summaries`, `--summaries-manifest-map`,
`--enable-summary-attempts`, and `--enable-summary-plan` for the
plan boundary); Evidence normalization/acceptance
lives on the `*-attempt` route's envelope — the produce route
itself still emits declared data.

### C06 declared summary manifest reuse check (go-summaries-check)

`python -m agent go-summaries-check` is the second consumable route:
it runs the same provisioned helper on the same declared inputs
(`--go-types`, `--source`, `--import`, `--target-arch`, `--timeout`)
plus `--manifest <PATH>` naming a manifest the produce route emitted,
restores it through `GoSummarySet.from_dict` (bounded at the helper's
`maxReply` scale) and emits `mumei.go-summary-check/v1` on stdout (or
`--output`). The report names whether the manifest's declared context
key still matches the fresh derivation (`context_match`) and partitions
the manifest's functions by identity: `reusable` — the identity
survives in the fresh report and nothing it references went stale —
`stale` — `stale_dependents` flags it, transitively, for referencing a
replaced binding, member or type identity — and `missing` — the fresh
report no longer produces the identity at all.

The report is detection, not authorization: identity survival is
weaker evidence than the monolithic `context_key` gate `for_function`
enforces, so a host that consumes `reusable` under `context_match:
false` is choosing per-function freshness over the strict whole-set
check — `stale_dependents` itself stays a detection helper and what
to recompute remains the host's call. `--output` may not equal any
declared input (sources, import files or the manifest itself). Audit
consumption is wired (`--summaries-manifest-map`); Evidence
normalization/acceptance lives on the `*-attempt` route's envelope.

### C06 declared summary manifest reuse (go-summaries-reuse)

`python -m agent go-summaries-reuse` is the third consumable route: it
runs the same provisioned helper on the same declared inputs plus
`--manifest <PATH>`, partitions the declared manifest's functions by the
same rule `go-summaries-check` reports, and emits a merged
`mumei.go-scalar-parameter-deps/v1` manifest — a `reusable` function's
declared summary is carried over verbatim, every other live function is
freshly derived and a `missing` entry is dropped. The merged set is
keyed to the fresh context, so it describes the current unit, not the
declared one. The manifest now declares the `target_arch` it was
derived for (`int`/`uintptr` widths are arch-dependent while binding
identities are not): a manifest whose declared architecture differs
from `--target-arch` — or that declares none — fails closed rather
than carrying wrong-width summaries forward.

Reuse remains detection, not authorization: carrying a declared summary
forward is the host's per-function freshness choice under the weaker
identity-survival rule — the strict whole-set gate is still
`for_function`/`for_package_function` against the live context key, and
`stale_dependents` still flags what must be re-derived. `--output` may
not equal any declared input (sources, import files or the manifest
itself). Audit consumption is wired (`--summaries-manifest-map`);
Evidence normalization/acceptance lives on the `*-attempt` route's
envelope.

### C06 declared summary strict acceptance (go-summaries-accept)

`python -m agent go-summaries-accept` is the fourth consumable route
and the strict counterpart of check and reuse: it runs the same
provisioned helper on the same declared inputs plus `--manifest` and
`--binding <ID>`, and emits `mumei.go-summary-accept/v1` — `accepted`
is true only when the manifest's declared context key still matches
the fresh derivation (the monolithic `for_function` gate) and the
named binding survives in the fresh report. A refusal names its
`reason` — `context_mismatch` when any byte of the unit moved, or
`unknown_binding` — and never carries a `summary`; an accepted report
carries the freshly derived function record — under the strict gate it
is identical to the declared one, and emitting the live record removes
any tamper channel in the declared record itself.

The weaker identity partition never authorizes here: reuse's
per-function freshness choice stays the host's, while accept refuses
a summary after any change anywhere in the unit. `--output` may not
equal any declared input. Audit consumption is wired
(`--summaries-manifest-map`); the strict route's re-derivation is
what performs the summary claim checks the attempt envelope leaves
unperformed.

### C06 declared summary attempt MCP tool (go_summaries_attempt)

`go_summaries_attempt` exposes the `go-summaries-attempt` route
over MCP: the produce route's declared inputs arrive as the same
JSON encodings the `go_summaries` tool already speaks
(`source_files` as an array, `imports_json` as an object), parsed
through the shared `_go_summaries_declared_args`, and the
route's lifecycle is shared through `run_attempt(args)` — the
same `AttemptSequence` keyed to the request fingerprint (helper
binary bytes plus every declared file), `dispatch_attempt`
observation and the same drift gate. The tool emits
`{"report": ...}` carrying the
`mumei.go-summaries-attempt-report/v1` lineage — canonical, never
an accepted manifest.


### C06 declared summary consume MCP tools (go_summaries_check / go_summaries_reuse / go_summaries_accept)

`go_summaries_check`, `go_summaries_reuse` and
`go_summaries_accept` expose the three go consume routes over
MCP. Declared inputs arrive as the same JSON encodings the
`go_summaries` tool already speaks (`source_files` as an array,
`imports_json` as an object), parsed through the shared
`_go_summaries_declared_args`, with `manifest_path` naming the
declared `mumei.go-scalar-parameter-deps/v1` manifest and — for
accept — `binding` naming the binding identity to accept
(`sha256:<digest>:<start>:<line>:<len>`, not a function name). Each
tool runs the identical document construction the CLI route emits —
`summary_check_document`, `summary_reuse_set` and
`summary_accept_document` are the single source both surfaces
share — so `context_match` plus the
`reusable`/`stale`/`missing` partition, the per-function freshness
merge (including the manifest-architecture guard) and the strict
whole-set accept gate all behave exactly as the routes do. The
tools return `{"check": ...}`, `{"manifest": ...}` and
`{"accept": ...}` respectively; declared-input failures return
`error` with checkout-local paths redacted to basenames.


### C06 declared summary attempt route (go-summaries-attempt)

`python -m agent go-summaries-attempt` is the fifth consumable route:
it runs the produce route itself as one declared attempt inside the
C11 lifecycle. The route spawns `python -m agent go-summaries` with
the same declared inputs (`--go-types`, `--source`, `--import`,
`--target-arch`, `--timeout`) through `dispatch_and_publish`: a fresh
`AttemptSequence` keyed to a request fingerprint that binds the helper
binary's bytes and every declared input file's bytes under
`mumei.go-summaries-attempt-request/v1`, one reserved attempt observed
by `AttemptRunner` under the required `--attempt-timeout <MS>` bound
(plus an optional `--memory-bound-mb` POSIX ceiling), reconcile and
compare-and-set publication. An `exited` run's captured stdout becomes
the sequence's selected result; failed, timed-out or cancelled runs
publish the terminal lineage with no selection.

The emitted `mumei.go-summaries-attempt-report/v1` carries the
canonical lineage, the `mumei.verifier-run-result/v1` normalized
descriptor and — only when a result was selected — the
`mumei.verifier-evidence-candidate/v1` handoff descriptor, so a host
can later restore the lineage through `AttemptSequence.from_dict` and
evaluate a recorded check against the candidate. The report carries
no manifest bytes: the child's manifest is observed only through the
bounded capture claim, a nonzero observed exit is still a completed
observation (the outcome lives in the report, not this route's exit
status) and the spawned child inherits only the caller's environment.

When a result is selected, the route also performs the manifest's
declared representation check itself — the captured stdout bytes are
restored through `GoSummarySet.from_dict`, the strict
`mumei.go-scalar-parameter-deps/v1` boundary — and records the outcome
as a `mumei.verifier-evidence-check/v1` document
(`sequence.evidence_check`) plus the `mumei.evidence-check-acceptance/v1`
verdict from `evaluate_evidence_check`. A produced manifest discharges
only the byte/run-level checks — `file_identity`, `freshness` and
`producer_authenticity` (`DischargedChecks.SUMMARY_ESTABLISHED`):
parsing restores the manifest's shape but never verifies its dep
claims against the implementation, so `claim_truth` and
`semantic_correspondence` stay in `checks_not_performed` until the
strict accept route's re-derivation performs them, and
`artifact_semantics` stays the compiled-artifact layer.
recovery-eval folds `mumei.go-summaries-attempt-report/v1` as a
performer schema for exactly those checks plus `historical_execution`,
bound through `normalized.stdout.sha256`, and folds any record that
declares no `checks_not_performed` — a produced manifest carries none —
over the full known-check vocabulary so the bound report recovers what
it discharges. The ts/sol/rust sibling routes carry the same
envelope, and directory audits reach the attempt lifecycle through
`--enable-summary-attempts`; no retry policy or scheduling is wired.

### go-summaries-reuse-attempt (+ ts/sol/rust siblings) — manifest replay through the attempt lifecycle

`python -m agent go-summaries-reuse-attempt` runs the reuse route as
one declared attempt inside the C11 lifecycle, closing the last gap
in the Go summary route family: manifest replay no longer stays out
of attempt mode. The route spawns `python -m agent
go-summaries-reuse` with the same declared inputs (`--go-types`,
`--source`, `--import`, `--manifest`, `--target-arch`, `--timeout`,
plus `--summary-aware-calls` when declared) through
`dispatch_attempt`: a fresh `AttemptSequence` keyed to a request
fingerprint that additionally binds the declared manifest's bytes
under `mumei.go-summaries-reuse-attempt-request/v1`, one reserved
attempt under the required `--attempt-timeout <MS>` bound (plus an
optional `--memory-bound-mb` ceiling), reconcile and compare-and-set
publication. An `exited` run's captured stdout — the merged manifest
— becomes the selected result only when every declared input byte is
unchanged after the observed run (the drift gate re-hashes the
manifest too); failed, timed-out or cancelled runs publish the
terminal lineage with no selection.

The emitted `mumei.go-summaries-reuse-attempt-report/v1` carries the
same envelope as the produce attempt — canonical lineage, the
normalized run-result descriptor and, on selection, the evidence
candidate, the `mumei.verifier-evidence-check/v1` outcome of
restoring the merged bytes through `GoSummarySet.from_dict`, the
`mumei.evidence-check-acceptance/v1` verdict, and the same
`discharged_checks`/`checks_not_performed` split
(`SUMMARY_ESTABLISHED`: a merged manifest's shape is restored but
its dep claims stay unperformed until the strict accept route
re-derives them). recovery-eval folds the report schema under the
same four bound-report performer lists as the produce attempt.
`go_summaries_reuse_attempt` is the matching MCP tool. The ts/sol/rust
siblings landed the same variant — `ts-summaries-reuse-attempt`,
`rust-summaries-reuse-attempt` and `sol-summaries-reuse-attempt`
mirror it one-to-one (single declared source, `--manifest` bound into
the fingerprint, identical envelope and `SUMMARY_ESTABLISHED`
discharge, matching `*_summaries_reuse_attempt` MCP tools), and
recovery-eval folds the three sibling report schemas under the same
four performer lists. Audit `--enable-summary-attempts` now combines
with `--summaries-manifest-map`: a mapped unit runs its
`<route>-reuse-attempt` route (entry `mode: "reuse-attempt"`, same
acceptance-envelope fields), and an unreadable or malformed prior
manifest falls back to the plain `-attempt` route with
`reuse_status: "stale_manifest"` — a bad prior manifest can never
weaken the audit.


### C06 declared Rust summary route family

`python -m agent rust-summaries` and its four siblings bring the Rust
interprocedural spike to the same declared route family Go pioneered —
one opt-in surface per route, all fail-closed, none wired into a
production verification path:

- `rust-summaries` emits `mumei.rust-scalar-parameter-deps/v1` for one
  declared `.rs` source: per-function scalar dependency summaries over
  the bounded fragment (scalar params, `let` bindings, if/else joins,
  a one-pass loop may-analysis, intra-file calls, tail-expression
  deps). Parsing is in-process tree-sitter — no helper binary, no
  `process.spawn` need — and every uncovered construct lands as a
  recorded gap, not a dropped edge.
- `rust-summaries-check` (`mumei.rust-summary-check/v1`) compares a
  declared manifest against a fresh derivation and partitions its
  functions into reusable/stale/missing.
- `rust-summaries-reuse` emits a manifest reusing the unchanged
  summaries `check` reports, re-keyed to the fresh context.
- `rust-summaries-accept` (`mumei.rust-summary-accept/v1`) echoes one
  binding's declared summary under the strict whole-context gate.
- `rust-summaries-attempt` runs the produce route as one declared
  attempt inside the C11 lifecycle (`dispatch_attempt` → reconcile →
  compare-and-set publication, input bytes re-hashed after the run)
  and emits `mumei.rust-summaries-attempt-report/v1`. On a selected result the route also performs the manifest's
declared representation check — the captured stdout is restored
through the strict `from_dict` boundary — and emits the
`mumei.verifier-evidence-check/v1` outcome, the
`mumei.evidence-check-acceptance/v1` verdict and the same
`SUMMARY_ESTABLISHED` byte-level discharge split
`go-summaries-attempt` pioneered (`claim_truth` and
`semantic_correspondence` stay unperformed — parsing restores shape,
never verifies dep claims); recovery-eval folds the report
schema as a performer bound through `normalized.stdout.sha256`.

`rust_summaries_adapter()` registers the produce route as a second
`summary_derivation` descriptor — declaring only `filesystem.read`,
since the derivation spawns no process — so `summary_descriptors()`,
`summary_registry()` and `plan_summary_route` cover it the same way.

`summarize_rust(source, resolver=None, source_path=None)` accepts
the same resolver contract TypeScript pioneered: `resolver(spec)`
(or `resolver(spec, importer_path)` for filesystem resolvers) maps
a `mod NAME;` declaration to source bytes/text or a resolved Path,
and the builder registers the module's functions under its dotted
path (`b.f`, `b.c.f`, `b.T.f` for `impl` methods). `use`
declarations bind local names to normalized registry keys —
`use b::f`, `use b::{f, g as h}`, and `crate`/`self`/`super`-headed
paths — and call sites resolve in order: locals shadow, then `use`
bindings, then a same-module item, then the crate root. Resolved
module bytes fold into `context_key`, so a changed module
invalidates reuse; chains are bounded (`MAX_MODULE_DEPTH`), an
ancestor (importer, spec) check stops degenerate self-resolving
declarations, and anything unresolvable stays opaque — resolution
only ever sharpens. `rust-summaries --resolve-modules` resolves
through the filesystem (`<base>/NAME.rs`, `<base>/NAME/mod.rs`,
confined to the importer's base tree); the flag is shared across
produce/check/reuse/accept so a resolved manifest's context key
matches, and `rust-summaries-attempt` refuses it — the attempt
fingerprint cannot bind undeclared bytes. Receiver dispatch
(`self.methods`) and compile-time globals stay root-file scopes;
`pub use` re-exports, glob `use b::*`, `#[path]` attributes and
macro-generated callables stay closed.

### C06 Rust lexical binding report (`rust-bindings`)

`python -m agent rust-bindings <file> --pointer-width {16,32,64}`
emits `mumei.rust-lexical-bindings/v1`, a bounded, single-file
tree-sitter report of lexical declaration identities and scopes,
references and writes, explicit scalar type facts, functions, calls,
unresolved names, and analysis gaps. It models Rust's local lexical
scope and item visibility, including shadowing and nested functions;
its stable binding IDs pin declaration and scope byte offsets to the
source digest. Pointer width is required because `isize` and `usize`
cannot be assigned a width without a declared target.

This report is lexical, not type-checked: it does not infer types from
initializers, resolve qualified paths or imported declarations, or
claim dynamic, macro, and other unsupported behavior. Such symbols
remain unresolved and unsupported syntax is recorded as a gap; either
makes the report incomplete. Attribute handling is explicit: inert
compiler/tool attributes and standard derives do not create gaps,
`cfg`/`cfg_attr` create `conditional_compilation` gaps, and unknown
procedural attributes or non-standard derives create `macro_invocation`
gaps. The fail-closed reader rejects stale, malformed, or internally
inconsistent reports. It is metadata only, not a proof or verdict. It
adds no default route and changes no audit, Seal Grade, or Lean
behavior. Rust (#1033) and Solidity (#1038) lexical reports are delivered;
this PR adds TypeScript for this C06 lexical-report scope.

### C06 Solidity lexical binding report (`sol-bindings`)

`python -m agent sol-bindings <file>` emits
`mumei.sol-lexical-bindings/v1`, a bounded, single-file tree-sitter report
of Solidity declarations, lexical scopes, references and writes, explicit
type facts, functions, conservative calls, unresolved names, and analysis
gaps. It models file and contract declarations, overload ambiguity, and
same-file inheritance while keeping imported and otherwise-unresolved
behavior explicit. Address and fixed-byte widths are language-fixed.

This report is lexical metadata, not a type check, proof, or verdict; it
does not claim to resolve imported or dynamic behavior. Unsupported
constructs and inline assembly remain explicitly gapped. The fail-closed
reader rejects stale, malformed, or internally inconsistent reports.
It adds no default route and changes no audit, Seal Grade, or Lean
behavior. Rust (#1033) and Solidity (#1038) lexical reports are delivered;
this PR adds TypeScript for this C06 lexical-report scope.

### C06 first compiler-backed Solidity binding slice

The pure reader consumes an operator-produced standard-JSON envelope from
pinned `solc` 0.8.39+commit.ce47f2c8; the agent never launches the compiler
and adds no CLI or MCP route. It reads single-file AST `Identifier` declaration spans
and compares them with the same-source lexical report, returning metadata
only. Exact source-content equality detects stale output, not compiler
authenticity. Imports and inline assembly fail closed. This slice makes no
trust, audit, Evidence acceptance, Seal Grade, ABI, runtime, or proof claim.

### C06 first compiler-backed TypeScript binding slice

The pure reader consumes an operator-produced envelope from pinned TypeScript
5.9.3; TypeScript 7.0.2 has no JavaScript compiler API. The agent never launches
Node or the helper and adds no CLI or MCP route. It compares single-file
identifier symbol declaration spans with the same-source lexical report,
returning metadata only. Exact source-content equality detects stale output,
not compiler authenticity. Only `lib.es2022.d.ts` is loaded, so DOM and Node
globals such as `console` fail closed with a diagnostic error. Imports,
dynamic imports, `require`, external module references, and triple-slash
references fail closed. This slice makes no trust, audit, Evidence acceptance,
Seal Grade, runtime, or proof claim.
Compiler intrinsics with no declaration, such as `undefined` and `globalThis`,
are reported as builtins; a reference with no symbol still fails closed.

### C06 first compiler-backed Rust binding slice

The pure reader consumes operator-produced LSIF envelopes from pinned
rust-analyzer `1.100.0 (0ef1bc3 2026-11-09)`; the agent never launches
rust-analyzer, Cargo, or rustc and adds no CLI or MCP route. It accepts one
root Cargo package with no dependencies, no build script, no proc-macro crate,
and no workspace members beyond the root. Cargo lock packages must be local.
The envelope carries project-document bytes and hashes; exact target-source
equality detects stale output, not producer authenticity.

Target-file local declaration spans are compared with the same-source lexical
report. Cross-file definitions are recorded with project-relative paths and
spans; external definitions are recorded by moniker only. Neither category is
compared with lexical bindings or asserts lexical resolution. Macro invocation,
macro definition, and conditional-compilation gaps make lexical comparison
fail closed. This is metadata only and makes no trust, audit, Evidence
acceptance, Seal Grade, ABI, runtime, or proof claim.

### C06 TypeScript lexical binding report (`ts-bindings`)

`python -m agent ts-bindings <file>` emits
`mumei.ts-lexical-bindings/v1`, a bounded, single-file tree-sitter report
of TypeScript lexical declarations, scopes, references and writes,
source-annotated scalar type facts, functions, conservative calls,
unresolved names, and explicit analysis gaps. `.tsx` files use the TSX
grammar. It models hoisting, block scopes, closures, imports, and generic
type parameters without inferring from expressions or claiming compiler
resolution.

The report is lexical metadata, not a type check, proof, or verdict.
Dynamic `eval`, `with`, decorators, unsupported qualified types, and other
uncertain behavior remain explicitly unresolved or gapped. The fail-closed
reader rejects stale, malformed, or inconsistent reports. Rust (#1033) and
Solidity (#1038) are delivered; this PR adds TypeScript for this C06 scope.
It adds no default route and changes no audit, Seal Grade, or Lean behavior.

### rust-summaries `--summary-aware-calls`

`--summary-aware-calls <MANIFEST>` (all rust-summaries routes)
declares a callee summary manifest the derivation folds into
otherwise-opaque calls: an opaque call whose recorded name a
manifest entry covers — `f` exactly, `crate::m::f`/`m::f` through
one module-token prefix, never a deeper strip — adopts the entry's
declared `return_dependencies` over its own actuals instead of the
every-argument union. Receiver-carrying calls (`x.m`, `t.f`),
local-bound callee names (fn pointers), voided calls, unavailable
entries, arity mismatches and out-of-range ordinals all stay
opaque; `effects` and the `&mut`-write merge stay opaque too —
the manifest cannot bound writes through argument objects. The
manifest is trusted as declared; its canonical bytes fold into
`context_key`, so a swapped manifest invalidates the strict
whole-context gate. The derived set's `call_modeling` block is
advisory counting only (`summary_modeled_calls`, `opaque_calls`,
`summary_unmatched`), never a verdict; `rust-summaries-reuse`
propagates it and `rust-summaries-attempt` forwards the flag,
binding the manifest bytes into the request fingerprint.


`summarize_solidity(source, resolver=None, source_path=None)`
accepts the same resolver contract: `resolver(spec)` (or
`resolver(spec, importer_path)`) maps an `import` directive's path
specifier to source text or a resolved Path. Imported modules
register under a basename-derived prefix (`b.f`, `b.C.f`); the
root module keeps bare names, so a resolver-free unit is
byte-identical to before. A module's visible scope is its own
top-level names merged with each resolved import's own names —
imports do not re-export — and a name contributed by more than
one source (two imports, or an import and a local declaration)
is ambiguous: every visibility lookup treats it as unresolved
rather than risking a wrong pick. Star imports bind all own
symbols, `import {f, C as C2}` binds only the listed names, and
`import "x" as D` / `import * as D` expose the module's own free
functions as `D.f(...)`. Ancestor and `using` targets resolve
through the declaring module's scope, so `contract A is Base`
and `x.dbl()` under `using L` work across files. Resolved module
bytes fold into `context_key` so a changed module invalidates
reuse; `MAX_MODULE_DEPTH` bounds chains, an ancestor
(importer, spec) plus a resolved-bytes digest guard stops cycles
and self-feeding resolvers, and anything unresolvable stays
opaque — resolution only ever sharpens.
`sol-summaries --resolve-modules` resolves paths against the
importing file's directory, confined to its tree and the source
cap; the flag is shared across produce/check/reuse/accept so a
resolved manifest's context key matches, and
`sol-summaries-attempt` refuses it — the attempt fingerprint
cannot bind undeclared bytes. Remappings, `D.C.m()` member calls
through a namespace, `using for` declared outside a contract
body, and cyclic imports stay closed; a modifier body inlined
into a caller keeps the caller's visible scope for any free-name
lookups it performs.


### C06 declared summary adapter descriptor

`agent.summaries_adapters` registers the produce route as a planner
adapter: `summary_derivation` joins the planner's method vocabulary —
deriving a dependency-summary manifest is an evidence method distinct
from every verification method — and `go_summaries_adapter()` returns
the declared `AdapterDescriptor` for `go-summaries` (profile
`mumei.go-scalar-parameter-deps/v1`, `mumei.source-text/v1` input,
`filesystem.read` + `process.spawn` permissions, a `bounded`/
`declared-inputs` result contract with `conservative-summary`
correspondence at `assumed` status, and a `probe_argv` the C11 probe
boundary can observe). `summary_requirements(profile)` builds the
matching `RouteRequirements` query, so `AdapterRegistry.plan()` and
`prepare_source()` select and bind the adapter like any declared
capability.

A descriptor is routing metadata only: registering it spawns no
process and accepts no manifest — the host still runs the route and
owns acceptance. Audit wiring for the produce/reuse/attempt routes
landed (`--enable-summaries` family); no production verification
path consults this registry yet.


### C06 summary-route probe wiring

`plan_summary_route(profile, policy, stamp=...)` composes
`summary_registry()` with `plan_with_probes`: when `go-summaries` is
excluded only because nothing observed it, its declared `probe_argv`
runs through `AttemptRunner` and the adapter is re-planned with the
fresh `RuntimeObservation`. `summary_descriptors()` /
`summary_registry()` are the shared enumeration — adding a language's
descriptor is a one-line change there.

Probing is availability only: the version is host-declared
(`tool_version`), so an unversioned observation still excludes
(`tool_version_unknown`) and a structural exclusion — denied
location, missing permission — is never probed at all. The returned
`AdapterProbePlan` carries the updated `AdapterProbeHistory` records
for retry scheduling. `summaries-plan` (below) is the first consumable
caller and `summaries_plan` the MCP tool; directory audits record
the same documents via `--enable-summary-plan` (below) while
scheduled verification wiring stays open.


### C06 consumable plan route (summaries-plan)

`python -m agent summaries-plan --profile <id> --stamp <n>` is the
planner-facing consumable over `plan_summary_route`: it plans the
summary route for a declared profile through the probe boundary and
prints `mumei.summaries-plan/v1` — the resulting
`mumei.verification-plan/v1` document, the `RuntimeObservation`s the
pass recorded, the updated `AdapterProbeHistory` records, and a
`mumei.probe-history-evaluation/v1` descriptor per history so a host
reads ordering and decisiveness checks rather than assuming them.

`--tool-version` declares the host's observed adapter version (without
it the adapter stays excluded as `tool_version_unknown`), `--rounds`
and `--max-parallel` bound the observe-and-replan loop, and
`--histories <file>` resumes a JSON array of persisted
`mumei.adapter-probe-history` records (v2 emitted, v1 restored) so
retries continue from the host's saved attempt counts.
`AdapterProbeHistory.to_dict()` / `from_dict()` is the declared
record schema for that persistence.
Routing only — a selected adapter is a routing decision, not an
accepted manifest.


### C06 summary planning as an MCP tool (summaries_plan)

The `summaries_plan` MCP tool exposes the same declared boundary:
`run_plan(args)` is the shared report builder the CLI entrypoint and
the tool both call — identical request binding, identical
`mumei.summaries-plan/v1` document. `histories_path` is a declared
path checked against the single-line rule; a declared failure
(invalid profile/stamp, unreadable or malformed histories, a probe
boundary error) surfaces as `error` with the histories path
basename-redacted, never as a process exit. Planning is routing
only: the tool returns `plan`, `observations` and `histories` and a
selected adapter is still not an accepted manifest.


### C06 declared summary produce routes as MCP tools

`ts_summaries`, `rust_summaries` and `sol_summaries` expose the three
in-process produce routes over MCP: each tool validates the declared
`source_path`, reads the source under the same byte bound as the CLI
route (64 KiB for TypeScript and Rust, 256 KiB for Solidity) and
returns the emitted `mumei.<lang>-scalar-parameter-deps/v1` manifest
as `manifest`. `ts_summaries` takes the `resolve_modules` opt-in —
the same relative-specifier filesystem resolver as the CLI flag —
while `rust_summaries` and `sol_summaries` match their routes' fixed
declaration surface. Declared failures (unreadable source, oversize,
an analysis limit) surface as `error` with the declared path
basename-redacted; nothing spawns and no manifest is accepted. The
`go_summaries` tool already covered the helper-backed route — the
family's produce surface is now uniformly reachable over MCP.


### C06 declared summary check routes as MCP tools

`ts_summaries_check`, `rust_summaries_check` and `sol_summaries_check`
expose the declared check routes over MCP. Each module's check
document is shared through `summary_check_document(declared, live)`:
the CLI route and the tool emit the identical partition —
`context_match` (the strict whole-context gate) plus the name-level
`reusable`/`stale`/`missing` sets. Both declared inputs are read
under the same byte bounds as the CLI route (source per route,
manifest at 8 MiB), the manifest restores through the strict
`from_dict` gate, and `ts_summaries_check` carries the
`resolve_modules` opt-in. Declared failures surface as `error` with
the declared paths basename-redacted; detection only — nothing is
accepted or merged.


### C06 declared summary reuse routes as MCP tools

`ts_summaries_reuse`, `rust_summaries_reuse` and `sol_summaries_reuse`
expose the declared reuse routes over MCP. Each module's merge is
shared through `summary_reuse_set(declared, live)`: a declared
function whose record is identical under the fresh derivation is
reused verbatim, every other live function is freshly derived and a
`missing` entry is dropped — the emitted set keyed to the fresh
context. The CLI route and the tool emit the identical manifest, so
the weaker per-function freshness merge stays exactly what the CLI
route promised; the strict whole-context gate remains `accept`'s
alone. Declared inputs are read under the same byte bounds and the
same `from_dict` restore as the check tools, and
`ts_summaries_reuse` carries the `resolve_modules` opt-in.


### C06 declared summary accept routes as MCP tools

`ts_summaries_accept`, `rust_summaries_accept` and
`sol_summaries_accept` expose the strict whole-context accept gate
over MCP. Each module's decision is shared through
`summary_accept_document(declared, live, function)`: `context_match`
first — the strict gate — then a declared-only function resolution
(`unknown_function` / `ambiguous_function` / `undeclared_function`)
that emits the freshly derived record, never the declared one, so
the manifest-forgery channel stays closed. The per-language name
resolution is preserved exactly — Rust and Solidity keep the
bare-member-name fallback while TypeScript requires the emitted
name. The returned `accept` document is the acceptance decision;
the summary inside remains a conservative report, not a proof.


### C06 declared summary attempt routes as MCP tools

`ts_summaries_attempt`, `rust_summaries_attempt` and
`sol_summaries_attempt` expose the declared attempt routes over
MCP. Each module's lifecycle is shared through
`run_attempt(source_path, raw, attempt_timeout, memory_bound_mb)`:
the same `AttemptSequence` keyed to the request fingerprint, the
same `dispatch_attempt` observation and the same drift gate — an
`exited` run's captured stdout becomes the selected result only
when every declared input byte is unchanged after the observed
run. The CLI route and the tool emit the identical
`mumei.<lang>-summaries-attempt-report/v1` document — the
canonical lineage, never an accepted manifest. Declared arguments
are validated the same way (single-line `source_path`, positive
`attempt_timeout_ms`, positive `memory_bound_mb` when set) and the
source is read under the route's byte bound.


### C06 declared summary MCP tool (go_summaries)

The MCP surface exposes the produce route as `go_summaries(
source_files, go_types, target_arch='amd64', imports_json='{}',
timeout_s=30)` — the same declared boundary the CLI speaks: the
caller declares every byte (source texts, import units, the helper
binary), the tool runs the provisioned helper through the shared
`summarize_declared` entry point, and the manifest goes out under
`manifest`. Nothing is resolved from disk, a project or the
toolchain — a summary is a conservative report, not a proof or a
verdict.

`agent.go_summaries.summarize_declared` is the wire's public entry
point: the CLI routes and the MCP tool both build the same helper
request (single-file profile vs package profile, bounded
`MAX_REQUEST_BYTES`, per-file `MAX_SOURCE_BYTES`, `MAX_IMPORTS`
units). Tool-level failures report under `error` via `_err` like
every other tool.


### C06 declared TypeScript summary route family

`agent.ts_interprocedural` promotes the TypeScript summary spike to the
declared route family: `python -m agent ts-summaries` emits
`mumei.ts-scalar-parameter-deps/v1` for single-file TypeScript — an
in-process tree-sitter summarizer covering scalar parameters and
returns, local declarations, assignments, `if`/`else` joins, loops,
same-file calls, closures, destructuring, classes, and recorded gaps
for everything outside the fragment. `--resolve-modules` is refused
on the attempt route because implicit module resolution names files
the request identity cannot cover.

`ts-summaries-accept` applies the strict whole-context gate to one
function's declared summary, `ts-summaries-check` and
`ts-summaries-reuse` partition and merge a declared manifest against
the fresh derivation, and `ts-summaries-attempt` runs the produce
route as one declared attempt through the C11 dispatch lifecycle and
emits `mumei.ts-summaries-attempt-report/v1`. On a selected result the route also performs the manifest's
declared representation check — the captured stdout is restored
through the strict `from_dict` boundary — and emits the
`mumei.verifier-evidence-check/v1` outcome, the
`mumei.evidence-check-acceptance/v1` verdict and the same
`SUMMARY_ESTABLISHED` byte-level discharge split
`go-summaries-attempt` pioneered (`claim_truth` and
`semantic_correspondence` stay unperformed — parsing restores shape,
never verifies dep claims); recovery-eval folds the report
schema as a performer bound through `normalized.stdout.sha256`. The `agent.ts-summaries`
adapter descriptor declares `filesystem.read` only — the route runs
in-process, so the `process.spawn` in its `probe_argv` belongs to the
C11 probe boundary, not the route.

Producing or accepting a summary is not a proof, an audit or a
verification verdict — the routes emit declared routing evidence only.

The opt-in `--summary-aware-calls <MANIFEST>` flag ports the same
declared-manifest fold Go pioneered: when a call resolves to a
module-external binding, the callee's entry in the declared callee
manifest is folded into the caller's derivation — the folded result
unions only the declared `return_dependencies` ordinals instead of
every actual, while writes through argument objects stay the opaque
union over every actual (a declared `effects` records whether the
callee CONTAINS calls, never what it writes). Matching is by export
name carried at the last path step (`import {g as h}` matches `g`,
`ns.f` matches `f`, `ns.g.h` matches nothing): a member deeper than
one step, a spread call, a `new` expression and `import()` never
fold and stay opaque. An entry that is unavailable,
arity-mismatched, names a colliding export or carries an
out-of-range ordinal folds nothing — the last is malformed at
`from_dict` since no honest derivation can emit it — and the
emitted manifest's advisory `call_modeling` counts
`summary_modeled_calls`, `opaque_calls` and `summary_unmatched`
(declared entries no call referenced). The manifest's canonical
bytes fold into `context_key`, so a swapped callee manifest
invalidates the strict whole-context gate; the attempt route
forwards the flag to the produce child and binds the manifest's
bytes into the request fingerprint — the fold is declared-input
data, trusted as asserted like every manifest these routes
consume. TS staleness stays record-equality, so a folded record
simply differs when a regenerated callee manifest changes what it
folds — no extra identity plumbing is needed.

### C06 declared Solidity summary route family

`agent.sol_interprocedural` promotes the Solidity summary spike to the
declared route family: `python -m agent sol-summaries` emits
`mumei.sol-scalar-parameter-deps/v1` for single-file Solidity — an
in-process tree-sitter summarizer (no helper binary) covering `pure`/
`view` functions with scalar `uint*`/`int*`/`bool` parameters and a
single scalar return, local declarations, assignments, `if`/`else`
joins, one-pass loop may-analysis, same-contract calls, state-variable
writes (`effects`), `require`/`revert`/`new`/struct/member/index
handling and recorded gaps for everything outside the fragment.

`sol-summaries-accept` applies the strict whole-context gate to one
function's declared summary (overloaded `C.g#2` stems stay ambiguous
until the emitted name disambiguates), `sol-summaries-check` and
`sol-summaries-reuse` partition and merge a declared manifest against
the fresh derivation, and `sol-summaries-attempt` runs the produce
route as one declared attempt through the C11 dispatch lifecycle and
emits `mumei.sol-summaries-attempt-report/v1`. On a selected result the route also performs the manifest's
declared representation check — the captured stdout is restored
through the strict `from_dict` boundary — and emits the
`mumei.verifier-evidence-check/v1` outcome, the
`mumei.evidence-check-acceptance/v1` verdict and the same
`SUMMARY_ESTABLISHED` byte-level discharge split
`go-summaries-attempt` pioneered (`claim_truth` and
`semantic_correspondence` stay unperformed — parsing restores shape,
never verifies dep claims); recovery-eval folds the report
schema as a performer bound through `normalized.stdout.sha256`. The `agent.sol-summaries`
adapter descriptor declares `filesystem.read` only — the route runs
in-process, so the `process.spawn` in its `probe_argv` belongs to the
C11 probe boundary, not the route.

Producing or accepting a summary is not a proof, an audit or a
verification verdict — the routes emit declared routing evidence only.

### sol-summaries `--summary-aware-calls` (issue #900 Option B, Sol port)

`sol-summaries --summary-aware-calls <MANIFEST>` declares a callee
summary manifest (`mumei.sol-scalar-parameter-deps/v1`). An opaque
external-member call — `ext.g(x)` or `ext.Lib.g(x)` — whose recorded
name an entry covers folds the entry's declared `return_dependencies`
instead of the opaque every-argument union: matching is the recorded
name exactly, or one module-token prefix over the callee's standalone
name (`ext.Lib.g` folds a manifest entry named `Lib.g`), never a
deeper qualifier. The entry must be `available`, arity-matched and
have every declared return ordinal inside the call's actual count.
The fold only narrows the recorded result set — `effects` still
reports `unknown` since the manifest cannot bound writes through
argument objects — and the discarded-result path, named arguments
and gapped/arity-mismatched/out-of-range entries keep today's opaque
record, so a partial or stale manifest can never narrow below the
width a run without the flag would report.

A manifest derived with the flag carries `call_modeling` —
`summary_modeled_calls` (folded), `opaque_calls` (left opaque),
`summary_unmatched` (manifest entries no call referenced) — advisory
counts only, never a verdict; manifests without the block load
unchanged. The callee manifest's canonical bytes fold into the
produced `context_key`, so a changed callee manifest invalidates the
strict whole-context gate; check and reuse re-derive with the same
flag and reuse keeps the counts in the merged manifest.
`sol-summaries-attempt` forwards the flag to the child and binds the
manifest's bytes into the request fingerprint like every other
declared input; the manifest path joins the declared inputs, so
`--output` can never overwrite it.

### C06 declared summaries in directory audits (audit --enable-summaries)

`python -m agent audit --code-file <dir> --enable-summaries` connects the
directory audit to the declared produce routes: every collected source
unit that has a summary route (`go-summaries` per package directory,
`ts-summaries` / `rust-summaries` / `sol-summaries` per file) is invoked
through `python -m agent <route>` as a bounded subprocess, and the
directory result records only the manifest's declared metadata under
`summary_audits` — `route`, `unit`, `status` (`emitted`,
`skipped_no_helper`, `failed`), plus `context_key` and `function_count`
on emitted entries. Manifest bytes never land in the audit output.

Go units need the provisioned helper declared via `--go-types <path>`;
without it they record `skipped_no_helper` and never spawn. Entries are
advisory — a failed or skipped unit reports its status without flipping
`success`, matching the `trusted_atoms` convention. The flag is
CLI-only; `scan_and_fix` does not expose it, and single-file audits are
unchanged.

### C11 declared availability probes

The opt-in `agent.adapter_probe` module connects a host-declared probe
command to `AttemptRunner` and maps the observed terminal outcome to a
`RuntimeObservation` that `AdapterRegistry.plan()` consumes. This closes
the "actual probing" phrase of the C11 scope at the observation level —
the probe decides nothing and records only what the declared command was
observed to do.

Declared outcome mapping (a convention, not a verdict): `exited` with
exit code 0 maps to `availability="available"`; `exited` with a nonzero
code and `failed` (a refused spawn, e.g. ENOENT) map to `"missing"`;
`timed_out` and `cancelled` map to `"unknown"`. `AdapterProbeRequest`
declares `adapter_id`, an immutable nonempty `argv`, `timeout_ms`, the
registry's monotonic `stamp`, an attempt number and an optional bounded
`memory_bound_mb`. Its `execution_request()` binds an execution-record
fingerprint over schema, adapter id, argv and stamp; `run_probe` runs
exactly one `AttemptRunner.run` with the declared bounds and one optional
cancellation event, then returns `AdapterProbeOutcome{observation,
result}` — the registry-ready observation plus the run's detached
normalization.

```python
from agent.adapter_probe import AdapterProbeRequest, run_probe

req = AdapterProbeRequest(
    "zendingsol.host.lean_scaffold",
    ("lean", "--version"),
    timeout_ms=5_000,
    stamp=7,
)
outcome = run_probe(req)
plan = registry.plan(request, policy, (outcome.observation,))
```

Boundary held honestly: a probe reports observed command behavior, not
tool health, availability proof or version truth — the command is
host-declared, so a lying probe simply records a lying observation, and
replay ordering across probes stays the stamp's job. No stdout is parsed
(the normalized digest binds bytes, never meaning), `tool_version` stays
a host-declared field, and nothing here authorizes, schedules, retries,
accepts or verifies anything. Actual plugin loading, adapter code
execution beyond the declared probe, output interpretation and Evidence
acceptance remain open.


### C11 manifest-declared probe commands

`AdapterDescriptor.probe_argv` is an optional immutable command declared
by the adapter manifest (`probe_argv` key, a nonempty list of nonempty
strings — any other shape is a static manifest error). A descriptor
without it serializes `null` and stays probe-free.

`agent.adapter_probe.probe_request_for(descriptor, stamp)` binds the
declared command to the descriptor's own budgets: the request's
`timeout_ms` is the declared `max_timeout_ms` and `memory_bound_mb` the
declared `max_memory_mb`, so a manifest pins how much room its own probe
gets. A descriptor without `probe_argv` is a static error
(`probe command not declared`), never a wildcard probe. The declared
argv passes through verbatim — host-declared text, never parsed,
expanded or resolved against PATH here — and the resulting observation
stays an untrusted, stamp-ordered claim exactly like a free-standing
`AdapterProbeRequest`.

```python
descriptor = AdapterDescriptor.from_manifest(manifest)  # has probe_argv
req = probe_request_for(descriptor, stamp=7)
outcome = run_probe(req)  # bounded by declared max_* budgets
```

Still closed: plugin loading, adapter code execution beyond the declared
probe, stdout interpretation, version truth and Evidence acceptance
(the declared probe-outcome acceptance descriptor is covered by its
own section below).


### C11 observation-driven probe scheduling

`agent.adapter_probe.probe_requests_for(registry, request, policy,
observations, stamp=...)` runs `plan()` and returns an
`AdapterProbeRequest` for every decision whose exclusion reasons are all
observation-level (`availability_unknown`, `tool_missing`,
`tool_version_unknown`, `tool_version_mismatch`) and whose descriptor
declares `probe_argv`. Adapters excluded for structural reasons are not
probed — no probe fixes an unsupported method or a denied location — and
an already-selected adapter is skipped. The shared stamp is per-request
safe because registry stamps are per adapter id.

Scheduling stays declarative: it decides which declared probes would
make excluded candidates observable — it runs nothing itself, keeps the
argv host-declared verbatim text, and the emitted request still goes
through `run_probe` for actual execution. Retry policy, concurrency
and Evidence acceptance remain open (probe ordering across stamps
and the declared probe-outcome acceptance descriptor are covered by
their own sections below).

### C11 probe execution driver

`agent.adapter_probe.observe_probes(requests, runner=..., cancel_event=...)`
executes a scheduled request tuple through one shared `AttemptRunner`
and returns the `RuntimeObservation` tuple in request order — the
half-step that closes the observe → re-plan loop: `probe_requests_for`
emits, `observe_probes` executes, and the caller feeds the observations
back into `registry.plan` (or the next scheduling round) itself. The
driver never plans, reorders or retries on its own.

Normalized attempt results stay inside `run_probe`: only
availability/stamp/tool_version cross the boundary into observations,
so probe stdout or exit detail cannot leak into a routing decision.

`observe_probes(..., max_parallel=N)` bounds how many probes run at
once through a `ThreadPoolExecutor`. The shared `AttemptRunner` keeps
no state between calls, so concurrent workers are safe; the returned
tuple keeps request order regardless of completion order — observation
`i` always answers request `i`. `max_parallel=1` is plain sequential
execution and remains the default; non-positive or non-int bounds are
static errors. `AttemptRunner` applies a declared `memory_bound_mb`
through an exec wrapper — `prlimit --as=` when available, else a POSIX
`sh -c 'ulimit -v <KiB> && exec "$@"'` wrapper — so memory-bound
probes stay parallel-safe on POSIX hosts; `preexec_fn` remains
only when neither wrapper exists, and only on such a host does a
batch carrying a bound request fall back to sequential
execution because the fork+exec spawn path can deadlock in a
multithreaded process before timeout accounting starts. Evidence
acceptance remains open; the declared retry gate is covered by its
own section below.

### C11 declared probe cancellation

`AdapterProbeRequest.cancel_request()` returns the declared
`AttemptCancelRequest` bound to the same fingerprint and attempt
ordinal as `execution_request()`. The descriptor only names which
running probe record a host proposes to stop — it never signals a
process, confirms delivery or proves a stop; dispatch and stop
observation remain host duties. C11 stays partial; Evidence
acceptance remains open (the declared probe-outcome acceptance
descriptor is covered by its own section below).

### C11 bounded probe outcome history

`agent.adapter_probe.AdapterProbeHistory` is a frozen record of probe
outcomes bound to one declared request fingerprint:
`AdapterProbeHistory.start(request)` binds the request's execution
fingerprint, and `record(request, outcome)` re-derives that fingerprint
from each new request and appends the next ordinal — a replayed,
reordered or foreign outcome fails statically instead of contaminating
the history. `MAX_PROBE_HISTORY` (8) bounds the record.

The history is replay evidence only: it says nothing about adapter
health, authorizes nothing and never retries. C11 stays partial;
Evidence acceptance remains open (the declared probe-outcome
acceptance descriptor is covered by its own section below).

### C11 bounded probe-driven planning

`agent.adapter_probe.plan_with_probes(registry, request, policy,
observations, stamp=..., rounds=1, max_parallel=1, histories=...,
max_attempts=...)` runs the observe → re-plan loop: `plan()`,
`probe_retry_requests`, `_run_probe_batch` (the same sequential /
bounded-parallel execution `observe_probes` uses), then `plan()`
again with the accumulated observations — incrementing the stamp each
round so the registry's freshness check accepts them. `rounds` is
bounded by `MAX_PLAN_ROUNDS` (4); the loop stops early when a
candidate is selected or a scheduling round emits no requests.
`histories` carries per-adapter `AdapterProbeHistory` records: each
round's requests are scheduled through `probe_retry_requests`, so an
adapter's `attempt_number` advances with its recorded history and the
adapter is skipped once `max_attempts` is reached; every observed
outcome is appended to the adapter's history. The result,
`AdapterProbePlan(plan, observations, histories)`, hands the caller
the final plan, the new observations, and the updated histories to
chain further planning.

The driver never authorizes, retries beyond `max_attempts`, or
accepts Evidence — it only schedules and observes declared probes.
C11 stays partial; Evidence acceptance remains open (the declared
probe-outcome acceptance descriptor is covered by its own section
below).

### C11 history-bounded probe retry scheduling

`agent.adapter_probe.probe_retry_requests(registry, request, policy,
observations, histories, stamp=..., max_attempts=...)` emits the next
attempt for every still-excluded declared candidate: an adapter with no
recorded history starts at attempt 1, otherwise the request carries
`attempt_number = attempt_count + 1`, and the adapter is skipped once
its `AdapterProbeHistory` reaches `max_attempts` (bounded by
`MAX_PROBE_HISTORY`). A history whose fingerprint does not re-derive
from the scheduled request — changed argv or stamp — fails statically
rather than authorizing a retry on stale evidence.

Scheduling stays declarative: it runs nothing, invents no candidate the
observation rules did not exclude, and retries only inside the declared
bound. Concurrency and Evidence acceptance remain open
(the declared probe-outcome acceptance descriptor is covered by its
own section below).

### C11 declared probe retry gate

`probe_retry_requests(..., retry_on=frozenset({...}))` narrows which
still-excluded candidates are re-asked: when the gate is given, an
adapter whose **last recorded outcome kind** is outside the set is
skipped — `retry_on=frozenset({"timed_out"})` re-asks a probe that
timed out but never one whose spawn `failed`. `PROBE_OUTCOME_KINDS`
(`{"exited", "failed", "timed_out", "cancelled"}`) bounds the
vocabulary: anything else — an unknown kind, an empty set, or a
non-frozenset — is a static `ValueError`, never a silently dropped
gate. `plan_with_probes(..., retry_on=...)` passes the same gate to
every scheduling round.

First attempts are unaffected (no outcome exists to gate on) and
`None` keeps the unfiltered behavior. The gate stays declarative — it
emits or withholds requests; it runs nothing, invents no outcome,
and accepts no Evidence. The `summaries-plan` route surface is
unchanged (the gate is an opt-in scheduling argument, like
`max_attempts`). The declared probe-outcome acceptance descriptor
is covered by its own section below.

### C11 declared probe-outcome acceptance

`agent.adapter_probe.evaluate_probe_acceptance(request, outcome)`
normalizes a declared `AdapterProbeOutcome` into an acceptance
descriptor `mumei.probe-acceptance/v1`: `request_match` holds only
when the outcome binds the presented request — the same
execution-fingerprint and attempt-ordinal binding
`AdapterProbeHistory.record` enforces — so a stale or foreign
outcome never counts, and `accepted` holds only when the outcome
is current AND mapped decisive: an `exited`/`failed` probe answers
`available`/`missing`, while a `timed_out`/`cancelled` one answers
`unknown` — an inconclusive attempt that accepts nothing. An
outcome naming another adapter fails statically rather than
matching nothing.

This is declaration-level acceptance, not Evidence: the
descriptor names every check left unassessed
(`checks_not_performed`: stdout interpretation, tool-version
truth, availability semantics beyond the exit-code convention,
freshness beyond the declared stamp, producer authenticity), and
nothing here is a verdict, an adapter-health claim or a routing
authority — `plan()` consumes observations unchanged and no route
surface is added. C11 stays partial; Evidence acceptance of
selected attempt outputs remains a Core duty.

### C11 declared probe-history stamp ordering

`AdapterProbeHistory` now records each outcome's observation stamp
beside it and emits `mumei.adapter-probe-history/v2` — the same
record shape plus a `stamps` array parallel to `outcomes`.
`record()` fails statically when the request's stamp regresses below
the last declared stamp (equal stamps stay ordered by their attempt
ordinals), and `__post_init__` applies the same check to restored
records, so a replayed or reordered stamp is a `ValueError`, never a
silently re-sorted history.

Persisted v1 records (`summaries-plan --histories`, MCP
`summaries_plan`) still resume: `from_dict` restores them with each
stamp `None` — undeclared, not fabricated — and a v2 record whose
`stamps` run contains a `None` after a declared stamp, a wrong
length, or a regressing pair is rejected on restore. Ordering is
per `command_fingerprint` only; cross-adapter ordering stays the
registry stamp's job, and probe acceptance remains open.

### C11 declared probe-history evaluation

`evaluate_probe_history(history)` folds a recorded
`AdapterProbeHistory` into `mumei.probe-history-evaluation/v1` —
the record itself carries the binding (every outcome bound its
request's fingerprint and ordinal at `record()` time), so the
fold needs no presented request. The descriptor reports what the
record proves — `outcome_count`,
`latest_attempt`/`latest_kind`, `latest_availability` re-derived
through the same outcome mapping as `evaluate_probe_acceptance`,
`ordered` (the declared stamps never regress) and `decisive` (the
latest outcome answers `available`/`missing` rather than
`unknown`). An empty history evaluates honestly; acceptance stays
a single-outcome property and is not emitted here.
`checks_not_performed` names what the fold leaves unassessed
(freshness beyond the last stamp, cross-adapter ordering, stdout
interpretation, tool-version truth, availability semantics,
producer authenticity, Evidence acceptance) — declaration-level
evaluation, not a verdict or routing authority.

### C11 declared Core-acceptance evaluation

`agent.core_evidence.evaluate_core_acceptance(descriptor)` and the
`evidence-acceptance-eval` route restore one declared Core acceptance
descriptor — `mumei.source-evidence-acceptance/v1` or
`mumei.native-evidence-acceptance/v1`, emitted by the Core `accept-*`
commands — and fold it into `mumei.core-acceptance-evaluation/v1`.
`descriptor_match` holds only for a closed-shape member of that known
family (`acceptance: "evaluated"`, a Boolean `accepted`, a non-empty
`scope` and two string check lists); a foreign or malformed document
never counts, and a well-formed descriptor that itself declared
non-acceptance matches but credits nothing. `accepted` holds only
when the descriptor matches AND declared `accepted: true`. Core may
attach the optional `evidence_fingerprint` field (the 64-char
lowercase-hex SHA-256 of the accepted record's bytes) — it stays
inside the closed shape; a malformed fingerprint breaks the match
like a foreign field, and the fold reports but does not re-verify it.

This is representation-level evaluation, not Evidence acceptance
credit: anonymous Core descriptors bind no request or attempt, so
`accepted` says only that some Core run accepted within its declared
scope — `checks_not_performed` names `attempt_binding`,
`descriptor_authenticity`, `descriptor_freshness` and
`unperformed_check_recovery` (the fold re-runs nothing the descriptor
left unassessed). plan() consumes nothing new; C11 stays partial.

### C11 declared attempt-binding fold

`evidence-acceptance-eval --expected-fingerprint <hex>` declares the
record pin an attempt binds to — the SHA-256 of the record bytes fed to
the attempt, matching the `evidence.sha256` the evidence-check request
embeds in its request identity (a `request_fingerprint` covers the
whole manifest, not the record, so it cannot serve as the pin). The
fold then emits `attempt_bound` — true only when the descriptor matched
AND carries an equal `evidence_fingerprint` — and `attempt_binding`
leaves `checks_not_performed`. A matched descriptor with no fingerprint
or a different one reports `attempt_bound: false` as an observation,
never an error; a malformed expected fingerprint is a static request
error; without one the key is absent and the check stays declared
unperformed. `descriptor_match`/`accepted` keep their descriptor-only
meaning — binding never folds into the descriptor's own verdict.

This is representation-level binding: fingerprint equality says the
descriptor and the caller pin the same record bytes, not that the
descriptor was produced for this attempt (`descriptor_authenticity`
stays) nor that any check ran again (`unperformed_check_recovery`
stays). The caller-side pin is trusted as declared — matching an
attempt's own pin is the caller's duty, not the fold's.

### C11 declared producer-signature envelope fold

`agent.core_evidence.evaluate_signature_envelope(envelope,
expected_subject, expected_key)` and the `signature-eval` route restore
one declared `mumei.producer-signature/v1` envelope — the detached
authenticity record the issue #886 design memo fixes — and fold it into
`mumei.signature-envelope-evaluation/v1`. `envelope_match` holds only
for the closed five-field shape naming `algorithm: "ed25519"` (the only
admitted algorithm — no negotiation) with a 64-char lowercase-hex
`subject_digest`, a 128-char hex `signature` and a non-empty
`producer_key_id`; a foreign or malformed document never counts, and a
matched envelope whose declared pins disagree reports `false`
observations, never an error.

`--expected-subject` declares the record digest the signature should
cover — e.g. an accepted descriptor's `evidence_fingerprint` or a
record's own `sha256` — and the fold emits `subject_bound`;
`--expected-producer-key` declares the producer key fingerprint the
caller trusts, arriving over a separately trusted channel exactly like
`--expected-adapter`/`--expected-build-id` pins, and the fold emits
`key_pinned`. Either pin left out stays declared-unperformed
(`subject_binding`/`key_binding` remain in `checks_not_performed`).

This is representation-level evaluation, not producer authenticity:
the fold checks the envelope's shape and declared pins, never the
ed25519 signature bytes (`signature_verification` stays), the pinned
key's own authenticity (`key_authenticity` stays — the caller-side pin
is trusted as declared), freshness (`envelope_freshness` stays — a
stale-but-well-formed envelope still matches) or revocation
(`key_revocation` stays). Rotation and the Core producer side are
separate later slices; C11 stays partial.

### C11 declared producer-signature verification

`agent.core_evidence.verify_signature_envelope(envelope,
producer_key, expected_subject, expected_key)` and the
`signature-verify` route restore one declared
`mumei.producer-signature/v1` envelope plus a raw ed25519 public key
(`--producer-key`, 64-char lowercase hex) supplied over a separately
trusted channel, and emit `mumei.signature-verification/v1`.
`signature_valid` holds only when the envelope matched the closed
five-field shape AND the declared key cryptographically verifies the
envelope's `signature` over the `subject_digest` — the signed payload
is the digest's lowercase-hex ASCII bytes, the same message
convention Core's `crypto_verify_signature` FFI signs
(`message.as_bytes()`). `--expected-subject`/`--expected-producer-key`
declare the same pins the evaluation fold takes and emit
`subject_bound`/`key_pinned` under identical rules. A matched
document also echoes the envelope's `subject_digest`, letting a
consumer bind the verification to the record bytes it covers — the
carrier convention `evidence-binding` and `recovery-eval` already
use (`mumei.signature-verification/v1` pins `subject_digest` in
`_BINDING_CARRIERS`, and a bound doc with `signature_valid` +
`key_pinned` performs `producer_authenticity` in the recovery fold).

`signature_verification` leaves `checks_not_performed`, but the fold
still claims nothing more: `key_authenticity` stays (the supplied key
is trusted as declared — a verifying signature binds that key to the
digest, it does not establish the key is the producer's),
`envelope_freshness` stays (a stale-but-signed envelope verifies) and
`key_revocation` stays. An unmatched envelope or a failed verify
reports `false` observations, never an error. Signing is a later
slice (see `signature-sign` below); rotation and the Core producer
side are separate later slices; C11 stays partial.

### C11 declared producer-record signing

`agent.core_evidence.sign_producer_record(record, secret_key,
producer_key_id)` and the `signature-sign` route produce the
`mumei.producer-signature/v1` envelope `signature-verify` consumes,
over a caller-declared record file and ed25519 secret key file
(`--record`, `--key-file`, `--producer-key-id`, `--output`). The key
file follows the Core convention: exactly 64 lowercase-hex characters
of a 32-byte ed25519 secret — strict ASCII, no whitespace or other
trimmable bytes admitted — and the signed payload is
`sha256(record bytes)`'s lowercase-hex ASCII encoding, the same
message `crypto_verify_signature` verifies. Both inputs are bounded
reads (record ≤ `MAX_INPUT_BYTES` matching the Core limit, key file
≤ 256 bytes), and `--output` refuses to overwrite either declared
input by inode. The secret is a declared input only: it never
appears in the emitted envelope, in error text, or on any output
surface — malformed key material reports only
`invalid producer key material`.

Signing claims nothing beyond producing the envelope: key generation
(the `mumei evidence keygen` side), key authenticity, rotation and
revocation policy, and the Core producer signing its own records are
separate slices; C11 stays partial.

### C11 declared key-revocation list

`agent.core_evidence.revocation_key_set(document)` folds a declared
`mumei.key-revocation-list/v1` — a closed two-field shape
`{schema_version, revoked_keys}` naming producer key ids, supplied over
a separately trusted channel exactly like the declared pins — into the
key set both signature folds take as `revoked_keys`. The
`signature-eval`/`signature-verify` routes expose it as
`--revocation-list`; when supplied, the fold emits `key_not_revoked`
(true only when the envelope matched AND its declared
`producer_key_id` is absent from the list) and removes
`key_revocation` from `checks_not_performed`. A malformed or foreign
list fails statically rather than silently revoking nothing or
everything.

To let the recovery fold bind the revocation observation to the record
the signature covers, the envelope-evaluation doc now echoes the
matched envelope's `subject_digest` — the same carrier the
verification doc already emits — and
`mumei.signature-envelope-evaluation/v1` joins `_BINDING_CARRIERS`.
`_CHECK_PERFORMERS["key_revocation"]` names both fold docs'
`key_not_revoked` bound through `subject_digest`, so
`recovery-eval` reports `recovered` only when every bound fold doc
for the record agrees `key_not_revoked: true` (a revoked-key
evaluation beside a clean one for the same record stays
`evidence_failed` — a conflicting bound observation never recovers).
`binding-eval` only checks the carrier's digest equality — it
reports `bound: true` for a bound doc regardless of the outcome
field; the outcome judgement lives in `recovery-eval` alone.

This is a declared list, not a revocation system: who maintains the
list, how it is distributed and authenticated, signing or freshness of
the list itself, and the Core producer side are separate later slices;
C11/C02 stay partial.

`key_authenticity` — the trust anchor the memo left open — is
performed by a second declared input (`agent.core_evidence`):
`mumei.producer-key-registry/v1` is a closed shape
`{schema_version, registry: {key_id → {principal, not_before,
not_after}}}` binding producer key ids to principals over a validity
window, supplied over a separately trusted channel exactly like the
pins and the revocation list. Both signature routes accept
`--key-registry PATH` with `--reference-time RFC3339` — the declared
clock, never the wall clock, the same convention `freshness-eval`
fixes; each is required by the other. With both supplied the folds
emit `key_authentic`: true only when the envelope matched AND its
`producer_key_id` names an entry whose window covers the declared
reference (conservative (low, high) bounds, like `within_window`).
The document is statically strict: duplicate `key_id`s are rejected
at parse time, every entry is the closed three-field shape, and a
definitely-inverted window is a caller error. `_CHECK_PERFORMERS`
names both folds' `key_authentic` bound through `subject_digest`, so
`recovery-eval` recovers `key_authenticity` from a bound eval/verify
doc and `binding-eval` binds it on the same carrier.

This is a declared registry, not a key directory: who signs,
distributes and revokes the registry itself (out-of-band attestation
is the memo's deferred Option D) stays a separate later slice;
`envelope_freshness` landed below; C11/C02 stay partial.

### C02 signature-envelope freshness fold

`produced_at` joins the `mumei.producer-signature/v1` envelope as its
only optional field (the stamp itself landed on Core's
`--produced-at`, [mumei#1136](https://github.com/mumei-lang/mumei/pull/1136)):
both signature folds admit it in the closed field set when it is a
string — a non-string stamp still breaks `envelope_match`, and any
other extra field still does — while never requiring it, so stamped
and unstamped envelopes both match.

`--max-age-seconds N` on `signature-eval`/`signature-verify`
requires `--reference-time` and emits `envelope_fresh`, folding the
stamp with the same conservative (low, high) bounds as
`evaluate_freshness`: the claim must not postdate the declared
reference and `produced_at + N` must reach it. An absent or
unparseable stamp fails closed — it cannot prove freshness —
matching `freshness_claimed` on the record fold. `--reference-time`
now requires a declared consumer (`--key-registry` or
`--max-age-seconds`); the clock stays declared, never read.

`_CHECK_PERFORMERS` names both folds' `envelope_fresh` bound through
`subject_digest`, so `recovery-eval` recovers a record's
`envelope_freshness` from a bound eval/verify doc — the same carrier
convention `key_revocation` and `key_authenticity` use. The stamp is
declared, not signed (the signature covers the digest alone, like
`producer_key_id`), so `producer_time_authenticity` — a timestamp
inside the signed payload — and `clock_authenticity` stay
not-performed by design.

### C02 signed trust anchors (issue #984 Option A)

The declared anchors `key_authenticity`/`key_revocation` lean on are
now themselves authenticatable: `--registry-signature PATH` +
`--registry-key HEX` on `signature-verify` supplies a
`mumei.producer-signature/v1` envelope signing the `--key-registry`
document's exact bytes — canonicalization is the document itself, so
the signed `subject_digest` is the file's SHA-256 — verified under a
consumer-pinned root key arriving over a separately trusted channel.
Only when the wrapper matches the closed envelope shape, verifies
cryptographically and pins the registry's digest does the fold emit
`registry_authentic: true` and AND it into `key_authentic` — an
inauthentic anchor can only fail the check, never widen it.
`--revocation-signature` + `--revocation-key` do the same for the
`--revocation-list` document, emitting `revocation_list_authentic`
AND-ed into `key_not_revoked`. Each signature flag requires its
anchor flag; each key requires its signature flag. `signature-eval`
accepts `--registry-signature`/`--revocation-signature`
representation-level only, emitting `registry_signature_bound` /
`revocation_signature_bound` (the wrapper's declared digest echoing
the anchor's) while `registry_authenticity` /
`revocation_list_authenticity` stay not-performed — the eval fold
binds signatures, never verifies them.

Both check names now join `_CHECK_PERFORMERS`: a verification doc
emits `registry_digest`/`revocation_digest` whenever it assesses an
anchor — pinning WHICH anchor document its outcome covered — and a
new `shared:<field>` bind-path convention binds a performer to a
record only when both docs declare the same anchor digest. A doc
that authenticated a different registry can never recover this
record's anchor check; the checks compose through `recovery-eval`
while staying anchored to the exact bytes each fold assessed. The
producer side needs no Core change: `mumei evidence sign` already
accepts any record file — the registry is just a record. Revocation
of the root keys themselves and rotation policy stay deferred.

### C11 declared unperformed-check recovery

`agent.core_evidence.evaluate_unperformed_check_recovery(record,
evidence)` and the `recovery-eval` route — the issue #897 design
memo — compose the family's folds: given a record's declared
`checks_not_performed` and a set of supporting documents, emit
`mumei.unperformed-check-recovery/v1` reporting each check as
`recovered` (a supplied document carries the declared performer
schema, its outcome field holds the declared value — `true` for the
evaluation folds, `"consistent"` for a source recheck — and, for
bound descriptors, its declared carrier equals the record's bound
digest), `evidence_failed` (the performer schema was supplied but
the outcome or the binding fails) or `no_evidence`. The bound digest
is the record's own declared carrier
(`evidence_fingerprint`/`subject_digest`/`record_digest`) when it
pins another artifact — so a Core acceptance descriptor folded as
the record is recovered by a recheck doc bound to the same
evidence — else the record's byte digest (`record_digest`). Note
`freshness` recovers two honest senses a consumer may want told
apart: recency (`freshness-evaluation/v1`·`within_window` over a
declared `produced_at`) and currency (a bound consistent recheck or
accepted acceptance re-establishing the record's claims); the report
names only which checks recovered, so a consumer that needs the
distinction reads the supplied documents.

Attribution is closed: `_CHECK_PERFORMERS` pins each check name to
its emitted schema and outcome field (`signature_verification` ←
`signature-verification/v1`·`signature_valid`; `envelope_freshness` /
`descriptor_freshness` / `freshness` ← `freshness-evaluation/v1`·
`within_window`; `attempt_binding` ←
`core-acceptance-evaluation/v1`·`attempt_bound`; `subject_binding` /
`key_binding` ← either signature fold's `subject_bound`/`key_pinned`),
so a document never declares its own coverage and a foreign schema
never counts. The fold stays representation-level: it does not re-run
checks (`recovery_enforcement`), does not verify the supporting
documents (`evidence_authenticity` — trusted as declared) and does
not pin a document to the record it covers (`evidence_binding` —
recovered below through `mumei.evidence-binding/v1`, pinned to the
record's own bytes even when the record declares a carrier for a
different artifact).

The six C02 semantic checks all recover through bound documents,
mirroring each attempt route's `discharged_checks`: `claim_truth`,
`freshness` and `semantic_correspondence` ← a consistent
`source-evidence-recheck/v1` or an accepted
`source-evidence-acceptance/v1`; `claim_truth` and
`artifact_semantics` ← an accepted `native-evidence-acceptance/v1`;
and all five non-artifact checks — `file_identity`,
`producer_authenticity`, `freshness`, `semantic_correspondence` and
`claim_truth` — ← an accepted `verify-attempt-report/v1`, whose
attempt sequence is also the recorded execution lineage, so the
same bound report performs `historical_execution` on the record its
run produced. The native accept routes' reports
(`native-accept-report/v1`, `native-exit-status-accept-report/v1`,
`native-stdout-accept-report/v1`, `native-stderr-accept-report/v1`)
perform the same check through their own outcome surface — the
string `acceptance: "accepted"` — since an accepted run's stdout is
the acceptance descriptor itself and `normalized.stdout.sha256`
binds the report's lineage to those bytes; a descriptor that kept
`historical_execution` unperformed ("one run is an observation, not
a history") recovers it through the route's published sequence. The
exit-status/stdout/stderr accept reports also perform their matching
`os_*_observation` check through the existing
`normalized.stdout.sha256` binding. Each has a second
`shared:expected_build_id` binding: an accepted Core run has authenticated
that declared ID against the bundle record, so accepted sibling reports
can perform their channel checks when both reports name the same ID.
The ID is echoed by all six per-channel accept/recheck reports,
including outcomes without an acceptance or reproduced result.
Single-channel rechecks remain non-performers because their stdout is
a fixed diagnostic line with no bound carrier. The
`native-observations-recheck-report/v1` is also deliberately
non-performing: Core prints the `mumei.runtime-observation/v1`
descriptor with `--json` (the report keeps its digest and schema name,
not the body), but that recheck is not acceptance. The accepted
`native-observations-accept-report/v1` performs all three channel checks
and `runtime_observation_semantics` through its bound stdout digest or
shared expected build ID: one Core invocation has observed every
channel. The raw `mumei.runtime-observation/v1` descriptor remains
non-performing, and three single-channel reports never compose
`runtime_observation_semantics`. `producer_authenticity` also
recovers through a
`mumei.signature-verification/v1` doc — the only multi-outcome
performer: a verifying signature alone binds SOME key to the digest,
so the doc must hold `signature_valid` AND `key_pinned` (the
producer-key pin the caller declared with `--expected-producer-key`),
and it counts only when its `subject_digest` carrier — echoed from
the matched envelope — equals the record's bound digest. Bound
documents match through a declared carrier pinned per schema:
`evidence_fingerprint` on a Core descriptor, `record_digest` on a
binding document, `normalized.stdout.sha256` (the produced bytes'
SHA-256 — `candidate.output_fingerprint` fingerprints the
verifier-output manifest, not the record) on the attempt report — and each counts only when the carrier equals the record's
bound digest, so a document produced for different bytes (or an
anonymous artifact acceptance with no record input) applies to
nothing, and without a declared `record_digest` or declared carrier
no bound document can be attributed. `claim_truth` and
`artifact_semantics` recovering here is still representation-level
composition — the fold re-verifies nothing the descriptor declares
(`recovery_enforcement`/`evidence_authenticity` stay).

### C11 declared freshness evaluation

`agent.core_evidence.evaluate_freshness(record, reference_time,
max_age_seconds)` and the `freshness-eval` route restore one declared
producer record — any JSON object that may carry an optional
`produced_at` RFC 3339 timestamp, per the issue #894 design memo —
and emit `mumei.freshness-evaluation/v1`. `freshness_claimed` holds
only when `produced_at` is present and parses with a timezone;
`within_window` holds only when the claim does not postdate the
declared `--reference-time` and stays inside `--max-age-seconds`.

The clock is declared, never read — `--reference-time` is the
caller's own trusted reference, so two runs over the same documents
always agree. `checks_not_performed` keeps `clock_authenticity` (the
declared reference is trusted as supplied), `producer_time_authenticity`
(the timestamp is the producer's claim — only a signature-bound
timestamp inside the signed `subject_digest` upgrades it) and
`freshness_enforcement` (the fold reports; gating is a host
decision). A record with no `produced_at` reports
`freshness_claimed: false` — never an error — so the fold composes
with every record shape that predates the optional field. Core-side
emission of `produced_at` is the memo's slice 2 — landed on mumei as
an opt-in `--produced-at` stamp on Evidence records
([mumei#1110](https://github.com/mumei-lang/mumei/pull/1110)) — and
`record_freshness` joins the recovery fold through this same
document; C11 stays partial.

### C11 audit-side summary-manifest reuse consumption

`audit --enable-summaries` only observed the declared produce routes.
`audit --summaries-manifest-map <PATH>` — the issue #893 Option A
slice — declares a JSON object mapping each emitted `unit` label to a
prior summary manifest, and a mapped unit runs its
`*-summaries-reuse` route (`ts-summaries-reuse`,
`rust-summaries-reuse`, `sol-summaries-reuse`,
`go-summaries-reuse` — the go unit keeps its per-directory shape and
inherited `--go-types`/`--source` flags) instead of the produce
route. The merged manifest is keyed to the fresh context, so the
audit entry reports `mode: "reuse"` with `reused_function_count` /
`derived_function_count` — how many merged records equal the prior
manifest's record for the same function name.

The flag requires `--enable-summaries` and the map document is
bounded (1 MiB) and strictly typed (object of string to string); a
malformed map fails the audit statically before any unit runs. A
unit whose declared manifest is missing, oversized, malformed or
rejected by the reuse route records `reuse_status:
"stale_manifest"` and falls back to the produce route — a stale
manifest can never weaken the audit, and manifest bytes still never
land in the report. Reuse counts are observed metadata only:
`summary_audits` stays advisory and carries no verdict.

### audit `--enable-summary-attempts` — summary units through the attempt lifecycle

`audit --enable-summaries --enable-summary-attempts` runs each summary
unit through its declared `<route>-attempt` route
(`ts-summaries-attempt`, `rust-summaries-attempt`,
`sol-summaries-attempt`, `go-summaries-attempt` — the go unit keeps
its per-directory shape and `--go-types`) instead of the produce
route, and the audit entry records the attempt report's acceptance
envelope: `mode: "attempt"`, `selected`, `manifest_sha256` (the
normalized stdout digest the report binds), `check_outcome` and
`accepted` when the route emits an evidence check and acceptance.
`--summary-attempt-timeout <MS>` declares the attempt bound passed
to every unit (default 120000 — the same bound the bounded
subprocess runner applies).

The flag requires `--enable-summaries` and cannot combine with
`--summaries-manifest-map`: mapped units run the plain
`*-summaries-reuse` route — `go-summaries-reuse-attempt` exists but
the audit does not route mapped units through it. Entries remain
advisory by construction — a refused,
malformed or unparseable attempt report records `status: "failed"`
without failing the audit, and report bytes never land in the
output.

### audit `--enable-summary-plan` — summary profiles through the probe-boundary planner

`audit --enable-summaries --enable-summary-plan` connects the
directory audit to the declared plan boundary: once per summary
profile present among the collected units
(`mumei.{go,ts,rust,sol}-scalar-parameter-deps/v1`) the audit runs
`plan_summary_route` and records the advisory
`mumei.summaries-plan/v1` document under `summary_plans` — the
resulting `mumei.verification-plan/v1`, the probe observations the
pass recorded, the updated `mumei.adapter-probe-history` records and
their evaluations, through the same `build_plan_document` the
`summaries-plan` CLI and `summaries_plan` MCP tool emit. Planning
executes each adapter's declared probe command through the probe
boundary; routing only — a selected adapter is a routing decision,
not an accepted manifest.

`--summary-plan-stamp <N>` declares the host's observation stamp
(default 1), `--summary-plan-tool-version` pins the declared adapter
version and `--summary-plan-histories <PATH>` resumes a JSON array
of persisted `mumei.adapter-probe-history` records — the same
bindings `summaries-plan` exposes, restored through the shared
`load_plan_histories`. Entries stay advisory: a declared failure (an
unreadable histories file, an invalid stamp, a probe-runner error)
records `status: "failed"` per profile without failing the audit.

### go-summaries `--summary-aware-calls` (issue #900 Option B, Go first)

`go-summaries --summary-aware-calls <MANIFEST>` declares a callee
summary manifest (`mumei.go-scalar-parameter-deps/v1`). A plain
`lib.F(args)` `direct_import` call whose callee the manifest covers
folds the callee's declared data instead of the opaque every-argument
union: the call's `result` becomes the union over the actuals the
declared `return_dependencies` names, `imported` follows the callee's
declared `effects` (an `unknown`-effects callee still transfers as
imported and still widens store-through-alias writes), and the
callee's declared `pinned` type identities fold like a local call's.
The callee's declared statement reads need no fold — each maps to a
subset of the actuals the call-site statement already reads. A folded
call's transfer also records `folded_targets` — the callee's own
`call_targets` transitively through the manifest — so
`stale_dependents` flags the caller when a folded dep two hops out
churns even though the directly named callee's bytes never moved.

The declared manifest is trusted as asserted: authenticity and
staleness stay unperformed, so `summary_authenticity` and
`summary_staleness` still report honestly rather than silently
upgrading. Matching is the declaration position, not the serialized
binding id — a callee's (file digest, declaration start) mints
identically under single-file and package unit shapes, so a
single-file callee manifest folds into the package-minted call
targets imports always carry; two manifest entries colliding on one
position fold neither. Folding is monotone-widening only: a callee
the manifest misses, or an entry that is gapped, arity-mismatched or
non-scalar, keeps today's opaque approximation, so a partial or stale
manifest can never narrow below the width a run without the flag
would report. Method and receiver-carrying calls never fold — the
manifest's parameter ordinals do not describe the receiver.

A manifest derived with the flag carries `call_modeling` —
`summary_modeled_calls` (folded), `opaque_calls` (left opaque),
`summary_unmatched` (manifest entries no call referenced) — advisory
counts only, never a verdict; manifests without the block load
unchanged. A `--summary-aware-calls` reuse run keeps the counts in the
merged manifest, and `go-summaries-attempt` forwards the flag to the
child and binds the manifest's bytes into the request fingerprint like
every other declared input. The manifest path joins the declared
inputs, so `--output` can never overwrite it. Check and reuse treat
the callee manifest's declared identities as `known`, so a folded dep
the caller's helper never emits (an import's import, or a type only
the callee's unit pins) stays checkable instead of flagging its caller
stale on identical inputs — a regenerated manifest's churned ids still
flag it. The callee manifest's canonical bytes also fold into the
produced `context_key`, so a changed callee manifest invalidates the
strict whole-context gate — `for_function`/`for_package_function`
take the same declared set when the manifest was derived with one.


### C11 declared evidence binding over record bytes

`agent.core_evidence.evaluate_evidence_binding(record, document)` and
the `binding-eval` route close the last representation-level gap the
recovery fold names: `evidence_binding`. The route reads a record's
raw bytes — never parsed, so any bounded document binds the same way —
and emits `mumei.evidence-binding/v1` reporting the recomputed
`record_digest` (SHA-256 of the bytes, the same convention as
`subject_digest` / `evidence_fingerprint`), `carrier_match` (the
document's `schema_version` is a declared subject-bearing schema),
`subject_declared` (the carrier's subject field is a well-formed
digest) and `bound` (the declared digest equals the record's).

Attribution is closed like the recovery fold: `_BINDING_CARRIERS` pins
the subject field per schema (`mumei.producer-signature/v1` →
`subject_digest`; `mumei.source-evidence-acceptance/v1`,
`mumei.native-evidence-acceptance/v1` and
`mumei.source-evidence-recheck/v1` → `evidence_fingerprint`), so a
document never declares its own coverage and a foreign schema never
binds. A mismatched or missing subject reports `bound: false` — never
an error — since a document may honestly describe a different record.

A `bound` binding document now performs `evidence_binding` in the
recovery fold (`_CHECK_PERFORMERS`), so subject-bound recovery
composes: `recovery-eval` plus `binding-eval` reports which recovered
documents actually cover this record. The recovery fold only counts a
binding document whose `record_digest` equals the record's own
SHA-256 — the `recovery-eval` route recomputes it from the record
file, dict callers declare it like `expected_fingerprint` — so a bound
document for a different record can never recover this record's
`evidence_binding`. The fold stays
representation-level: `carrier_authenticity` (the document is trusted
as declared — its own checks and signature are not re-verified) and
`binding_enforcement` (the report is an observation; gating is a host
decision) stay in `checks_not_performed`. C11 stays partial.

### C11 bounded attempt scheduling with declared retry/fallback

`agent.attempt_schedule.run_attempt_schedule(registry, request, policy,
source, expected_source_sha256, argv_for, ...)` composes the declared
boundaries without new authority: `registry.plan` → `PreparedSourceRequest`
→ `AttemptSequence.begin_attempt` → `dispatch_attempt` → on a non-success
terminal outcome `registry.replan` with the failed adapter excluded, until
`max_attempts` (≤ `MAX_SCHEDULE_ATTEMPTS` = 8). `argv_for(adapter_id)` is
the host's declared argv lookup — `None` records the round as
`not_dispatched` and falls back like a failed run, so an adapter without a
declared command is skipped, never run. `success_exit_codes` (default
`{0}`) is the host's declared exit mapping: `exited` with any other code
is a scheduling failure, not a verdict. Fallback requires permissive
routing (automatic selection or `allow_fallback`); an explicit
non-fallback selection ends a failed schedule as `fallback_denied`, and a
set `cancel_event` ends it as `cancelled` — a stop decision, not a
failure the policy may route around. A selectionless plan reports
`not_schedulable`.

The result, `AttemptScheduleResult`, folds into
`mumei.attempt-schedule/v1`: per-round `ordinal`, `adapter_id`,
`plan_fingerprint`, `request_fingerprint`, `terminal_state` (including
`not_dispatched`) and `exit_code`, plus `outcome` ∈
{`selected`, `exhausted`, `not_schedulable`, `fallback_denied`,
`cancelled`}. Each adapter attempt is its own `AttemptSequence`, so a
fallback never contaminates the prior attempt's lineage. The descriptor
carries fingerprints only — no argv, source or output bytes — and
`selected` names which adapter produced a declared-success exit, never
an Evidence acceptance. This is partial C11: scheduling is observed
dispatch, not authorization, output normalization, arbitration or
acceptance.

### C11 verify-schedule CLI route

`python -m agent verify-schedule` is the consumable surface for
`run_attempt_schedule`: it loads the declared
`RouteRequirements`/`ResultContract` (`--request`), adapter manifests
(`--adapters`), `PlannerPolicy` (`--policy`), optional stamped runtime
observations (`--observations`), the source (`--source`, sha256-checked)
and the host's argv lookup (`--argv-map`, adapter_id → argv array), then
prints the `mumei.attempt-schedule/v1` descriptor (`--output` writes it
to a file). Every input document is closed-shape — unknown keys are
rejected — and the schedule's own bounds (`--max-attempts` ≤ 8,
`--success-exit-code` repeated, `--memory-bound-mb`) are declared on the
command line, not hidden in policy defaults. The route is dispatch only:
like `verify-attempt` it emits a dispatch record, never an Evidence
acceptance, and it keeps the fingerprint-only output contract.

### C11 audit-side scheduled verification

`audit --enable-scheduled-verification` wires the scheduler into the
audit lane: each unit's generated `.mm` spec is dispatched through
`run_attempt_schedule` against the host's declared
`--schedule-request`/`--schedule-adapters`/`--schedule-argv-map`/
`--schedule-policy` inputs (plus optional `--schedule-observations`,
`--schedule-max-attempts`, `--schedule-success-exit-code` and
`--schedule-memory-bound-mb`). The declared argv is a prefix — the
unit's generated spec path is appended as the final argument — and the
resulting `mumei.attempt-schedule/v1` descriptor records on each
unit's `scheduled_verification` field, a dispatch record that never
alters `verification_status` or `success`. The enable flag requires
all four declared input paths; every `--schedule-*` option without it
is a static error, and declared-path failures are redacted like the
`verify-schedule` route. `scheduled_verification` stays out of the
MCP `audit_schema` vocabulary — it is a CLI observational lane, not a
finding contract.

### C04 consumable verification-plan route

`python -m agent verify-plan` is the explainable counterpart to
`verify-schedule`: the same declared inputs (request, adapter
manifests, planner policy, optional observations) run through
`AdapterRegistry.plan` and emit the full
`mumei.verification-plan/v1` document — the selected adapter's
effective non-secret settings, `fallback_from`, and every candidate's
`decisions` reasons (`selected_priority`, `selected_explicit`,
`selected_fallback`, `compatible_not_selected`,
`explicit_selection_blocks_automatic_route`, `not_registered` and the
whole exclusion vocabulary from `disabled` to
`tool_version_mismatch`). Until now the plan document only existed as
a fingerprint inside the schedule record, so the C04 "explainable"
surface was not consumable; this route is planning only — it declares
no argv, spawns nothing, and `not_dispatched` is not a plan outcome.
Failures reuse the declared-path redaction of `verify-schedule`, the
closed-shape JSON checks reject unknown keys, and `--output` refuses
to overwrite a declared input. 13 tests cover selection/exclusion
reasons, explicit and fallback selection, denied fallback, pins,
missing tools, unregistered selections, effective settings exposure,
closed-shape rejection, the output guard, secret-free output and
CLI/library document equality.

### C11 test-user-adapter E2E lane

`tests/fixtures/stub_adapter.py` is a checked-in test user adapter: a
small executable whose entire behavior is declared on its argv
(`--exit`, `--sleep`, `--emit`, `--err`, `--spew`, `--alloc-mb`,
`--die`). `tests/test_fixture_adapter_schedule.py` drives it through
the real `python -m agent verify-schedule` subprocess, so the whole
lane a user faces when adding an adapter — manifest registration,
argv declaration, plan/dispatch, real spawn, terminal reconciliation,
fallback — is exercised end to end **with no core edit**: adding,
swapping or replacing an adapter is a manifest plus an argv-map
entry.

The matrix covers the acceptance negatives: a missing tool records a
`failed` round then falls back; an observation whose `tool_version`
violates a declared `tool_version_pins` is never scheduled; a sleeping
stub times out at the declared `timeout_ms`; an over-allocating stub
dies under `--memory-bound-mb`; malformed, partial or conflicting
adapter output is recorded as terminal state + exit code and never as
content; explicit `selected_adapter` dispatch honors `allow_fallback:
false` as `fallback_denied`; an undeclared argv is `not_dispatched`
— the route never guesses, installs or probes a command. Two host
guards hold throughout: a sentinel env secret and the source bytes
appear nowhere in the descriptor or stderr, and the stub itself reads
no environment, opens no file, spawns no child and touches no network.

The lane remains a dispatch record, not an Evidence acceptance:
`mumei.attempt-schedule/v1` carries fingerprints, terminal states and
declared exit codes only — adapter stdout never lands in the document.

### C11 manifest-declared attempt argv

`AdapterDescriptor.attempt_argv` lets an adapter manifest declare the
attempt command itself: `verify-schedule` and the audit
`--enable-scheduled-verification` schedule can fall back to the
declared `attempt_argv` when the host argv map carries no entry for
the adapter — but only when the host planner policy declares
`allow_manifest_attempt_argv: true`, so a manifest can never plant an
executable command on its own. The host argv map still wins when both
are present, so a host can always pin or override the command an
adapter shipped with.

The field is a static manifest declaration like `probe_argv` — a tuple
of argv strings validated at registration, round-tripped through
`to_dict`/`from_manifest`, and listed in `_MANIFEST_FIELDS`. It is
never executed at parse time; the scheduled dispatch runs it through
the same declared boundary as an argv-map entry (plan → dispatch →
terminal reconciliation), so an adapter that declares its own attempt
needs no host-side argv declaration to run. A manifest with neither
still yields `not_dispatched` — the route never guesses a command, and
without the explicit policy opt-in a declared `attempt_argv` is inert
metadata.

```python
descriptor = AdapterDescriptor.from_manifest({
    ...,
    "attempt_argv": ["/usr/bin/myverifier", "--batch"],
})
```

C11 stays partial; Core meaning and acceptance, C12's demand gate and
any default audit/CLI/MCP route are unchanged — declared output
interpretation is covered by `verdict_markers` below while Evidence
acceptance remains open.

### C11 manifest-declared attempt stdin

`AdapterDescriptor.attempt_stdin` lets an adapter manifest declare the
byte payload piped to the attempt process's standard input:
`verify-schedule` and the audit `--enable-scheduled-verification`
schedule feed it through `dispatch_attempt`'s `feed_bytes` channel —
but only when the host planner policy declares
`allow_manifest_attempt_stdin: true`. Like `attempt_argv`, the field is
static metadata (a bounded UTF-8 string, at most 64 KiB when encoded,
validated at registration and round-tripped through
`to_dict`/`from_manifest`); without the explicit policy opt-in a
declared `attempt_stdin` is inert and the attempt reads EOF. The opt-in
is separate from `allow_manifest_attempt_argv` so a host can let a
manifest carry its command while still refusing planted input, or the
reverse.

```python
descriptor = AdapterDescriptor.from_manifest({
    ...,
    "attempt_stdin": "{\"problem\": \"...\"}\n",
})
```

C11 stays partial; Core meaning and acceptance, C12's demand gate and
any default audit/CLI/MCP route are unchanged — Evidence acceptance
remains open.

### C11 manifest-declared output verdict markers

`AdapterDescriptor.verdict_markers` lets an adapter manifest declare
how its own output self-reports an outcome: an ordered tuple of
`{stream, contains, outcome}` where `stream` is `stdout` or `stderr`,
`contains` is a bounded byte string, and `outcome` is one of `valid` /
`failed` / `inconclusive`. After a dispatch reaches `exited`, the
schedule scans the captured stream for the first matching marker and
records it as the attempt entry's `reported_outcome` on
`mumei.attempt-schedule/v1`.

The reported outcome is the adapter's own declared self-report — the
schedule interprets bytes only through the manifest's declared
markers, never through a guessed format. `reported_outcome` is not a
selection signal (exit codes still decide `selected`), not an
evidence-check outcome, and never Evidence acceptance — Core owns the
meaning of what an adapter claims.

```python
descriptor = AdapterDescriptor.from_manifest({
    ...,
    "verdict_markers": [
        {"stream": "stdout", "contains": "VERIFIED", "outcome": "valid"},
    ],
})
```

C11 stays partial; Core meaning and acceptance, C12's demand gate and
any default audit/CLI/MCP route are unchanged.

Markers scan only the captured prefix of each stream: the output
collector keeps at most the first 64 KiB of stdout and stderr, so a
marker that appears only beyond the byte bound records `null`
(indistinguishable from no match — the run's `complete` flag declares
stdout's completeness, `stderr_complete` stderr's, so a stderr marker
that misses is checked against `stderr_complete`).

C11 stays partial; Core meaning and acceptance, C12's demand gate and
any default audit/CLI/MCP route are unchanged — Evidence acceptance
remains open.

### C11 manifest-declared attempt memory bound

When the host declares no `--memory-bound-mb`, a scheduled attempt now
runs under the adapter's own manifest `max_memory_mb` as its POSIX
RLIMIT_AS ceiling — the adapter's declared budget enforced as an
ordinary observed outcome (an over-bound child surfaces as `exited` /
`failed` / `timed_out`, never diagnosed). The host's declared bound
always wins when present, so a host can still pin a tighter or looser
ceiling per route. This needs no opt-in: the bound only limits the
child, it grants nothing.

C11 stays partial; Core meaning and acceptance, C12's demand gate and
any default audit/CLI/MCP route are unchanged — Evidence acceptance
remains open.

### C11 scheduled-attempt evidence check

`run_attempt_schedule(..., core_executable=PATH)` and the
`verify-schedule --core PATH` flag close the same produce+consume loop
as `verify-attempt` for a scheduled selection: when the schedule
selects an attempt, the dispatch's captured output is canonically
selected on the sequence, the Core representation check is run against
the declared executable (`record_evidence_check`, bounded like
verify-attempt's check), and `evaluate_evidence_check` normalizes it
into the schedule record's `evidence_check` /
`evidence_acceptance` fields — null when no `--core` is declared or no
attempt is selected. `--core` must be an absolute path to a regular
file; a failed or cancelled check records its outcome with
`accepted: false` — it never blocks the selection.

C11 stays partial; Core meaning and acceptance, C12's demand gate and
any default audit/CLI/MCP route are unchanged — Evidence acceptance
remains open.

### C11 Core attempt-schedule representation check

The `evidence-check-schedule` CLI route and `evidence_check_schedule`
MCP tool consume Core's `evidence check-schedule --stdin --json`
diagnostic over a declared `mumei.attempt-schedule/v1` document. The
route selects only the exact representation-and-consistency diagnostic
and reports its schedule outcome and attempt count. A `selected` outcome
means only the schedule's manifest-declared-success exit; adapter
execution, reported-outcome truth, Evidence acceptance, and grade
promotion remain unperformed. The declared schedule bytes and Core
executable are fingerprinted and rechecked after the attempt; drift
suppresses selection.

C11 stays partial; this route adds no Evidence acceptance or grade
promotion.

### C11 Core attempt-acceptance representation check

The `evidence-check-attempt-acceptance` CLI route and
`evidence_check_attempt_acceptance` MCP tool consume Core's
`evidence check-attempt-acceptance --stdin --json` diagnostic. The route
validates the static representation and local agreement on the declared
outcome and requirement-fingerprint presence. Selection means only Core
validated that representation and producer consistency: the producer's
`accepted` binding is not Core Evidence acceptance, and `candidate_match`
is not rechecked. There is no Core check rerun, claim-truth,
producer-authenticity, freshness, or grade-promotion claim.

C11 stays partial; this route adds no Evidence acceptance or grade
promotion.

### C11 Evidence accept-list consumer route

The `evidence-accept-list` CLI route and `evidence_accept_list` MCP
tool consume Core's `evidence accept-list` verdict over a declared
Evidence list and exactly one single or conjunctive requirement. The
route validates the duplicate-free, input-fingerprinted Core descriptor
and reports only its aggregate verdict, consistency, counts and check
lists. Accepted selection requires exit 0, an accepted verdict, a valid
descriptor and unchanged inputs; rejected and inconclusive verdicts do
not select. The verdict is Core's declared-requirement normalization
over representation plus cross-record pin agreement, not claim truth,
producer authenticity, freshness, tool execution or grade promotion.
Selection is a declared-success exit, not a grade promotion. A
descriptor larger than the 64 KiB attempt capture bound is reported as
`descriptor_truncated` with no verdict and no selection. C11 stays
partial.

### C11 Core adapter-manifest representation check

The `evidence-check-adapter` CLI route and `evidence_check_adapter`
MCP tool consume Core's `evidence check-adapter --stdin --json`
diagnostic over a declared `mumei.verifier-adapter/v1` manifest. The
selection requires Core's exact closed diagnostic and local
`AdapterDescriptor.from_manifest` agreement on attempt argv, stdin and
verdict-marker count. These fields remain
declarations only: argv/stdin need host opt-in, markers are self-report
vocabulary, and `max_memory_mb` is a declared ceiling. This route does
not execute adapters, assess command safety or host policy, enforce
resources, claim producer authenticity, accept Evidence or promote
grades. Selection means only a manifest-declared-success exit; input
drift suppresses selection.

C11 stays partial; this route adds no Evidence acceptance or grade
promotion.

### C11 audit scheduled-attempt evidence check

`audit --schedule-core PATH` (with `--enable-scheduled-verification`)
declares the trusted Core executable for an audit's scheduled dispatch —
single-file and directory audits alike: when a unit's schedule selects
an attempt, the captured
output runs through the Core representation check and the schedule
record carries `evidence_check` / `evidence_acceptance`, matching the
`verify-schedule --core` route. `--schedule-core` must be an absolute
path to a regular file; a failed or cancelled check records its
outcome with `accepted: false` — it never blocks the selection.

With `--schedule-core`, audit also serializes each generated schedule in
the same format as `verify-schedule` and records Core's
`evidence check-schedule --stdin --json` diagnostic separately as
`scheduled_verification_check`. This is an advisory representation and
consistency diagnostic only; it is not a verdict or Evidence acceptance
and does not change `verification_status` or `success`. It adds no
Evidence acceptance or grade promotion. Like `scheduled_verification`,
it remains outside the fixed MCP `audit_schema` finding vocabulary.

C11 stays partial; Core meaning and acceptance, C12's demand gate and
any default audit/CLI/MCP route are unchanged — Evidence acceptance
remains open.

### C11 MCP scheduled-attempt evidence check

The MCP `verify_schedule` tool gains an optional `core_path` input that
declares the same trusted Core executable as `verify-schedule --core`:
absolute path, passed through to `run_attempt_schedule` so a selected
attempt's captured output runs the Core representation check and the
schedule record carries `evidence_check` / `evidence_acceptance`. The
MCP surface is identical in shape to the CLI — the field is a dispatch
observation on `mumei.attempt-schedule/v1`, never a grade or claim
verdict. C11 stays partial; Evidence acceptance remains open.


### C11 scheduled-attempt evidence acceptance

`run_attempt_schedule(..., core_requirement=PATH)` and the
`verify-schedule --core-requirement PATH` flag declare a
`mumei.evidence-requirement/v1` document for the selected attempt's
check: instead of the representation check, the captured output runs
through `core evidence accept --stdin --json --requirement PATH`
(`record_evidence_acceptance`), and the recorded `evidence_check`
outcome is Core's declared verdict — `accepted` / `rejected` /
`inconclusive`, `failed` or `cancelled`. The acceptance descriptor
echoes the `requirement_fingerprint` Core itself emitted — the
requirement bytes it actually evaluated — so consumers pin which
requirement the verdict answered.
`--core-requirement` requires `--core` and must be an absolute path to
a regular file; a verdict that disagrees with Core's exit code is a
`failed` check, never a verdict — and no outcome blocks the selection.

C11 stays partial; verdict-bearing grade promotion, C12's demand gate
and the audit/MCP ports are unchanged — Evidence acceptance remains
open.

### C11 audit scheduled-attempt evidence acceptance

`audit --schedule-core-requirement PATH` (with
`--enable-scheduled-verification` and `--schedule-core`) declares the
same `mumei.evidence-requirement/v1` document for the directory
audit's scheduled verification: the selected attempt's captured
output runs through `core evidence accept --stdin --json
--requirement PATH` and the schedule record carries Core's declared
verdict and the `requirement_fingerprint` it emitted — the audit
port of `verify-schedule --core-requirement`. The requirement path is
redacted from per-unit failure text like every other declared input.
`--schedule-core-requirement` requires `--schedule-core` and an
absolute path to a regular file.

C11 stays partial; verdict-bearing grade promotion, C12's demand gate
and the MCP port are unchanged — Evidence acceptance remains open.


### C11 MCP scheduled-attempt evidence acceptance

The MCP `verify_schedule` tool gains an optional
`core_requirement_path` input — the MCP port of
`verify-schedule --core-requirement`: it requires `core_path` and
declares the same `mumei.evidence-requirement/v1` document, so the
selected attempt's captured output runs `core evidence accept --stdin
--json --requirement PATH` and the schedule record carries Core's
declared verdict and the `requirement_fingerprint` it emitted. The
path joins the declared inputs and is redacted from error text.

C11 stays partial; verdict-bearing grade promotion and C12's demand
gate are unchanged — Evidence acceptance remains open.


### C11 scheduled-attempt promotable export

`run_attempt_schedule(..., core_requirement_list=PATH)` and the
`verify-schedule --core-requirement-list PATH` flag (requires `--core`,
conflicts with `--core-requirement`) run the requirement-declared
check over a `mumei.evidence-requirement-list/v1` document: Core
answers with the conjunctive
`mumei.evidence-requirement-list-acceptance/v1` descriptor and the
recorded `evidence_check` outcome is that verdict. With
`--export-evidence-acceptance DIR` the schedule also writes the
promotable gate triple — `requirement-list.json` (the declared
bytes), `evidence.json` (the captured output Core evaluated) and
`acceptance.json` (the validated descriptor) — the exact input shape
`mumei claims --require-evidence-acceptance` pins and gates on. The
descriptor is exported only when Core produced one; a `failed` or
`cancelled` check exports nothing. Export is observability, not
promotion: the schedule records what it dispatched and what Core
declared, and grade promotion stays with the downstream gate — C11
stays partial.


### C11 audit + MCP scheduled-attempt requirement-list acceptance

The audit and MCP mirrors of the conjunctive check:
`audit --schedule-core-requirement-list PATH` (requires
`--schedule-core`, conflicts with `--schedule-core-requirement`) and
the MCP `verify_schedule` `core_requirement_list_path` input
(requires `core_path`, conflicts with `core_requirement_path`) run
`core evidence accept --stdin --json --requirement-list PATH` over
the selected attempt's captured output against a declared
`mumei.evidence-requirement-list/v1` document, recording Core's
declared verdict as the `evidence_check` outcome with the
`requirement_fingerprint` it emitted. Both paths join the declared
inputs and are redacted from error text; the promotable export stays
CLI-only — neither surface writes the gate triple.

C11 stays partial; verdict-bearing grade promotion and C12's demand
gate are unchanged.

### C11 MCP verification-plan route

The MCP `verify_plan(request_path, adapters_path, policy_path,
observations_path=None)` tool mirrors the `verify-plan` CLI route:
declared route requirements, adapter manifests, planner policy and
optional stamped runtime observations feed `registry.plan`, and the
`mumei.verification-plan/v1` descriptor is returned as `report` —
the selected adapter, its effective non-secret settings,
per-candidate selection/exclusion reasons and the fallback origin.
Planning only: nothing is spawned, dispatched or accepted. Declared
inputs join the path validation and error redaction applied to the
other declared-path tools.

### C11 declared evidence folds as MCP tools

The MCP tools `evidence_acceptance_eval`, `freshness_eval`,
`binding_eval`, and `recovery_eval` mirror the four spawn-free CLI folds
over bounded declared inputs. They preserve `checks_not_performed` and
redact declared paths in errors; recovery requests accept at most 64
evidence paths. They make no Core command or subprocess call and add no
authority, Evidence acceptance, verdict, or grade promotion. C11 stays
partial; Core meaning and acceptance, C12's demand gate and grade
promotion are unchanged.

### C11 declared producer-signature folds as MCP tools

The MCP `signature_eval` and `signature_verify` tools mirror the
spawn-free `signature-eval` and `signature-verify` CLI routes over
bounded declared inputs. Evaluation preserves `checks_not_performed`;
verification performs Ed25519 under caller-declared public keys. Both
make no Core command or subprocess call and add no authority, Evidence
acceptance, verdict, or grade promotion. `signature-sign` remains
CLI-only because it reads secret key material. C11 stays partial; Core
meaning and acceptance, C12's demand gate and grade promotion are unchanged.

### C10 runtime/ABI assurance — design memo

The remaining research-level C10 item — the object/ABI/runtime/final-binary
assurance chain — has a design memo:
[`docs/DESIGN_RUNTIME_ABI_ASSURANCE.md`](DESIGN_RUNTIME_ABI_ASSURANCE.md).
Core stage 2 has landed in mumei as `native-bundle
recheck-observations`, which emits `mumei.runtime-observation/v1`.
Both agent routes for Core observation commands have landed:
`native-observations-accept` is the only performer of
`runtime_observation_semantics`, while `native-observations-recheck`
reports but does not perform the raw observation descriptor. These
checks describe one bounded invocation, never ABI, general runtime or
process semantics. The named channel checks remain composable through
`recovery-eval` when their Core-authenticated `expected_build_id`
values match. The remaining deep endpoint is object-code translation
validation (Option B); no ABI claim is made. No grade or audit surface
changes.

### C10 object-code translation validation — consumption memo

How the agent consumes Core object-stage translation-validation observations
(Option B) is designed in
[`docs/DESIGN_OBJECT_TV_CONSUMPTION.md`](DESIGN_OBJECT_TV_CONSUMPTION.md):
a separate `object_translation_correspondence` check (never a reuse of
`artifact_semantics`), an accept route as the only performer, a non-performing
recheck route, and no end-to-end source-to-executable check composed from
stage reports. Core's `recheck-object` command and
`mumei.object-symbol-correspondence/v1` descriptor have landed; the
`native-object-recheck` agent route consumes its three bounded checks without
registering a recovery performer. Core #1228 and the agent's
`native-object-accept` route add bounded object-stage machine-code acceptance;
universal object translation validation remains outside the profile.

### C10 Option B native-object-recheck route

`python -m agent native-object-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` runs Core's
`native-bundle recheck-object --expected-build-id <id> --json <bundle>
<source>` in the C11 declared-attempt lifecycle. A `corresponds` outcome
always discharges `artifact_semantics` and `claim_truth`. Its bounded object
checks are derived only from `checks_performed` in a descriptor whose schema
and build ID match the declared request; only listed checks among
`object_symbol_correspondence`, `object_call_edge_correspondence` and
`object_link_correspondence` are discharged. Older Core descriptors may
omit `object_link_correspondence`, so exit code 0 alone cannot imply that
check. `object_translation_correspondence` stays unperformed. Other
outcomes leave the full C02 and object-check vocabularies unperformed, and
mid-run input drift claims no outcome. The report is deliberately not a
`recovery-eval` performer and makes no instruction-selection,
register-allocation, general linker-semantics, ABI, runtime or
historical-execution claim.

### C10 Option B native-object-accept route

`python -m agent native-object-accept --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` runs Core's
`native-bundle accept-object --expected-build-id <id> --json <bundle>
<source>` in the C11 declared-attempt lifecycle. Exit 0 selects the captured
descriptor only when the declared Core, bundle members, source and build ID
remain unchanged; exit 3 is `inconclusive`, exit 1 claims no outcome, and
mid-run drift reports `inputs_changed` without an outcome.

The route accepts only `mumei.native-evidence-acceptance/v1` descriptors with
`acceptance: "evaluated"`, `accepted: true`, the expected build ID, one of the
two object-acceptance scopes, `object_source_machine_code_correspondence` in
`checks_performed`, scope-consistent `object_link_correspondence`, disjoint
performed/not-performed lists and lowercase 64-character LLVM/object SHA-256
digests. An exit-0 invalid descriptor is marked `descriptor_invalid` and
discharges nothing. Core's source/object check maps to the agent-owned
`object_translation_correspondence`; Core's agent-owned name, if present in
its list, is not a substitute for the Core check. Other object and
machine-TV checks are discharged only when listed in the validated
descriptor.

The report exposes the acceptance schema, scope, hashes, bounded
`register_convention_assumed` and `input_domain` strings, and aggregate
function-outcome counts without function names. This is bounded object-stage
machine-code acceptance under an assumed, not validated, register convention
and stated input domain—not universal object TV. The C `main` wrapper, CRT,
loader/libc, ABI/runtime semantics, optimizer semantics, producer authenticity
and historical execution remain outside the claim. The report is not reusable
Evidence or a certificate, does not promote a grade, emits no evidence
candidate and is not a recovery performer.

### C10 Option B native-machine-tv-recheck route

`python -m agent native-machine-tv-recheck --core <path> --bundle <dir>
--source <path> --expected-build-id <sha256>` runs Core's
`native-bundle recheck-machine-tv --expected-build-id <id> --json <bundle>
<source>` in the C11 declared-attempt lifecycle. A `checked` result always
discharges `artifact_semantics` and `claim_truth`; object checks are added
only from `checks_performed` in a matching `mumei.machine-code-tv/v1`
descriptor with the declared build ID. The agent exposes aggregate
function-outcome and callee-saved-preservation counts without names, plus
`register_convention_assumed` and `input_domain` when they are bounded
strings. Core #1201 adds
`machine_code_direct_call_site_tv`, consumed only when listed in
`checks_performed`; direct calls are compared as uninterpreted call sites.
Core #1206 adds `machine_code_forward_branch_function_tv`, consumed only when
listed in `checks_performed`. Core #1209 adds
`machine_code_acyclic_branch_function_tv`, also consumed only when listed in
`checks_performed`. Core #1210 adds
`machine_code_conditional_call_function_tv`, also consumed only when listed
in `checks_performed`. Core #1227 adds
`machine_code_bounded_loop_function_tv`, consumed only when listed there.
Core compares bounded loops with `LOOP_BOUND=4`; the input-domain string
includes `_and_loops_exiting_within_bound_4`. Executions beyond the bound,
cancellation/runtime semantics and other cyclic control flow remain outside
the profile. The profile covers leaf straight-line functions, bounded
forward and acyclic backward branches, bounded loops, and direct calls as
uninterpreted call sites, including calls inside branching functions with
per-path guarded call matching, under an assumed, not validated, register
convention. The C `main`
wrapper, CRT, loader and libc also remain outside its scope, so
`object_translation_correspondence` stays unperformed. Other outcomes leave
the full C02 and object-check vocabularies unperformed; mid-run input drift
claims no outcome. The route remains a non-performer for recovery-eval. It
makes no ABI, runtime or full object-TV claim.

#### Core #1229 callee-saved register preservation

Core adds `machine_code_callee_saved_register_preservation`, consumed only
when listed in `checks_performed`. It is performed only when at least one
function is Equivalent and all Equivalent functions are proved to preserve
callee-saved registers. Each Equivalent function reports
`callee_saved_preservation` as `preserved`, `violated`, or `unknown`; the
agent counts these values without exposing function names. Direct callees
and the cancellation poll are assumed to preserve callee-saved registers;
external callees remain an assumption, and Core's
`machine_code_callee_saved_preservation_assumed_for_external_callees` marker
remains not performed. The argument/result register convention is assumed,
not validated. This does not establish ABI correctness, runtime behavior,
or full object TV.

#### Core #1230 entry-wrapper machine-code TV

`machine_code_entry_wrapper_tv` checks only Core's modeled C entry wrapper:
when both object symbols exist and `__mumei_user_main` has a supported source
signature, `main` makes one unconditional call to `__mumei_user_main` and
returns the low 32 bits of its result. The agent consumes the check only when
a valid matching descriptor lists it in `checks_performed`; the
native-object-recheck route always leaves it unperformed. Existing
function-outcome and callee-saved-preservation counts include the wrapper
entry when Core reports it, without exposing function names.

This does not establish CRT, loader, OS exit-status, ABI, or runtime
semantics. `os_exit_status_observation` remains a separate
runtime-observation check and is not discharged by entry-wrapper TV. Core's
`object_entry_wrapper_semantics` not-performed marker is Core-only and is not
added to the agent vocabulary.

#### Core #1233 scalar-f64 machine-code TV

The agent consumes `machine_code_f64_scalar_function_tv` only when a valid
matching descriptor lists it in `checks_performed`, and only for Core's
scalar-f64 profile. XMM argument/result registers are assumed, not validated.
MXCSR RNE, masked exceptions, FTZ/DAZ-off assumptions and NaN payload bits
remain unestablished and not performed; the agent never discharges
`machine_code_tv_mxcsr_control_state` or `machine_code_tv_nan_payload_bits`.
Direct calls with f64 arguments fail closed in Core. This is not an
IEEE-754-conformance, ABI, runtime, or full object-TV claim.

#### Core #1241/#1242/#1243/#1244 composite aggregate register machine-code TV

Core's `machine_code_composite_register_aggregate_tv` is consumed only when
listed in `checks_performed`. It covers one- through sixteen-leaf struct
parameters and direct-call struct arguments, and struct results of at most
four leaves (at most three integer leaves in rax/rdx/rcx and at most two f64
leaves in xmm0/xmm1), with integer and/or f64 leaves; an i128/u128 leaf
occupies two consecutive integer slots, low half first. Integer leaves take
the next register in rdi–r9 and f64 leaves the next in xmm0–xmm7; leaves
without a free register in their class are passed on the argument stack in
declaration order, as LLVM lowers scalar stack arguments. Four-integer-leaf
results (hidden sret) and three-f64-leaf results (x87) fail closed. One- and
two-leaf values use Core's existing assumed SysV eightbyte convention;
aggregates wider than two leaves assume LLVM first-class aggregate lowering,
not SysV C-ABI classification, and
`machine_code_tv_sysv_memory_class_aggregate_abi` stays not performed. This
makes no ABI, runtime or full object-TV claim.

## Roadmap authority and vocabulary

Alias-free docs are now regression-fixed at the docs level by `tests/test_contract_vocabulary.py`, while the existing CLI/MCP/report tests continue to lock runtime JSON output.

Run the local contract vocabulary gate before opening a PR that touches docs, README, CLI help, or MCP docstrings:

```bash
uv run pytest tests/test_contract_vocabulary.py -q
```

CI enforces the same gate through `.github/workflows/contract-vocabulary.yml` on pull requests into `develop`. This is the mumei-agent complement to the canonical `mumei/scripts/check_contract_vocabulary.py` gate; keep both green in the same changeset when contract vocabulary moves.

`mumei-lang/mumei/docs/CROSS_PROJECT_ROADMAP.md` is the single top-level roadmap. This file only records mumei-agent-local acceptance details and must keep terminology aligned to `harness_contract`, `intent_fidelity`, `artifact_paths`, `budget_policy_fingerprint`, and `lean_verified`. Current priority is docs-sync and harness-contract regression prevention, not new portability/runtime scope.

Audit/spec/MCP vocabulary is fixed as:

| Term | Meaning | CLI/MCP surface |
| --- | --- | --- |
| `contradiction_type` | Stable classifier: `spec_internal`, `spec_overconstraint`, `spec_vacuity`, `spec_vs_code`. | `validate-spec`, `extract-spec --check-contradiction-only`, `validate-spec-to-code`, `validate-code-to-spec`, report formatter |
| `spec_health_issues` | Spec-only contradictions, overconstraints, vacuity, or ambiguity in extracted/provided specs. | `audit`, `scan_and_fix`, `validate-spec` |
| `verification_violations` | Existing-code bugs or unsafe paths found before `.mm` migration. | `audit`, `scan_and_fix`, `validate-code` |
| `verification_status` | Machine-readable code-safety verdict for audited source (`verified` / `refuted` / `unverifiable`). | `audit`, `scan_and_fix`, `validate-code` |
| `cross_validation_gaps` | Spec↔code mismatches or cross-spec drift that still needs migration or review. | `audit`, `scan_and_fix`, `validate-spec-to-code`, `check_cross_spec_consistency` |
| `next_steps` | Human-review entrypoint with prioritized actions and commands; this is where reviewers decide whether to migrate, heal, or accept a finding. | `audit`, `scan_and_fix`, report formatter |
| `migration_hints` | `.mm` skeleton advice generated by `migrate-suggest` / `--auto-migrate` for violations or gaps. | `audit --auto-migrate`, `scan_and_fix` |
| `healed_files` | Generated `.mm` skeletons accepted or rewritten by the self-healing loop. | `audit --auto-heal`, `scan_and_fix` |
| `heal_errors` | Per-skeleton self-healing failures and diagnostics. | `audit --auto-heal`, `scan_and_fix` |
| `trusted_atoms` | Advisory findings (severity `warning`) listing each `trusted atom` declaration in `.mm` sources under the audited path — trusted atoms bypass Z3, so audits surface them rather than pass silently. | `audit`, `scan_and_fix` |

`scan_and_fix` is the MCP spelling of `audit --code-file ... --auto-migrate --auto-heal`; README flowchart, guide steps, CLI help, MCP docstrings, and this roadmap must describe the same `audit -> migrate-suggest -> heal` contract and the nine fixed keys above without aliases.

If `scan_and_fix` also receives `spec`, its response may include `spec_alignment` and `conformance_verification` sidecars. These do not rename or replace the audit contract: `audit` owns no-`.mm` findings and migration/heal artifacts, `spec_alignment` owns spec→code comparison, and `conformance_verification` owns traceability plus human/markdown report text. `V1-E` is only `next_steps`-origin human review across those surfaces; do not add alternate review keys.

### Single audit contract and review handoff

`audit -> migrate-suggest -> heal` is one contract, whether invoked as one command or as separated review gates:

1. `audit` produces `spec_health_issues`, `verification_violations`, `verification_status`, `cross_validation_gaps`, `next_steps`, and `trusted_atoms` (advisory warnings for `trusted atom` declarations in `.mm` sources).
2. `next_steps` is the required human-review handoff before generated skeletons are trusted.
3. `migrate-suggest` produces `migration_hints` for accepted findings.
4. `heal` records `healed_files` and `heal_errors` without changing the audit classification.

The names above are the public MCP/report schema. Do not document synonyms such as "audit issues", "verification gaps", or "repair hints" as alternate JSON keys.

### V1 priority alignment

This repository owns V1-A/V1-B/V1-C/V1-D agent surfaces while `mumei-lang/mumei/docs/CROSS_PROJECT_ROADMAP.md` owns the global order: land V1-A spec health and V1-B code audit in parallel, then V1-C spec→code and V1-D code→spec conformance, then V1-E human review. PRs that update this roadmap should review the cross-project roadmap in the same diff and record relevant MCP/audit/spec regression commands from `tests/`.

For V1-E user-facing output, `verify-conformance --format human|json|markdown` and MCP `scan_and_fix(..., output_format="human"|"markdown")` must keep `next_steps` before findings/reports, while JSON preserves `next_steps`, `verification_violations`, and `cross_validation_gaps` exactly.

### MCP sampling compatibility follow-up

`USE_MCP_SAMPLING=true` is an opt-in compatibility path for MCP clients that can
serve as the LLM provider via standard sampling.  The current implementation is
aligned with the MCP 2025-11-25 sampling specification and is limited to basic
text `sampling/createMessage` requests:

- convert OpenAI-style `messages[]` into MCP `SamplingMessage` text content
- map `role=system` messages to `systemPrompt`
- pass the configured model as `modelPreferences.hints[].name`
- bound `maxTokens` by `MCP_SAMPLING_MAX_TOKENS` (default `4096`)
- check initialization `capabilities.sampling` before sending sampling requests,
  preferring the public `session.client_params` property and
  `session.check_client_capability()` method, with `session._client_params`
  retained as a fallback for older SDK versions
- omit `includeContext`; 2025-11-25 marks `"thisServer"` and `"allServers"`
  as soft-deprecated and requires explicit `sampling.context` capability before
  using them
- omit sampling `tools` because 2025-11-25 requires explicit `sampling.tools`
  capability before sending tool-enabled sampling requests

Future work:

1. ✅ **Complete** — capability detection now uses the public
   `session.client_params` property and `session.check_client_capability()`
   method (MCP SDK ≥ 1.28) as the primary path.  `session._client_params` is
   retained as a fallback for older SDK versions.  Resolution order:
   (a) public `client_params` + `check_client_capability()`,
   (b) private `_client_params` attribute,
   (c) unknown → assume capable (backward-compat).
   OpenAI-compatible fallback when sampling is absent is unchanged.
2. ✅ **Complete** — optional tool-enabled sampling is available via
   `McpSamplingLLMProvider.complete_with_tools()`.  It requires an explicit
   `sampling.tools` client capability (detected via the same public
   `client_params` + `check_client_capability()` path with `_client_params`
   fallback; unknown capabilities resolve to *not supported*, never
   optimistic), keeps tool definitions scoped to each sampling request, and
   returns parsed text + `tool_use` blocks (`SamplingToolCompletion`).  The
   default text-only `complete()` path is unchanged.
3. 🔍 **監視項目** — multimodal image/audio sampling は具体的な forge/heal ユースケースが発生するまで追加しない。現行の text-only path をデフォルトとして維持する。
4. 🔍 **監視項目** — MCP spec release 追随。特に `includeContext` soft-deprecation と client capability shape の変更を監視し、`LLMProvider` 抽象と OpenAI-compatible fallback の安定性を維持する。text-only `complete()` が `includeContext` を送らないこと・sampling 失敗時に OpenAI-compatible fallback へ委譲すること・`maxTokens` が `MCP_SAMPLING_MAX_TOKENS` で bound されることは `tests/test_llm_provider_sampling_tools.py::TestBasicSamplingMonitoringContract` で回帰固定済み（`mcp` SDK 1.27.2 で検証。public `client_params` + `check_client_capability()` を主経路、`_client_params` をフォールバックとする解決順序を維持）。
5. ✅ **実装済み** — Go の剰余インデックス `idx = expr % len(container)` を sound に bounds safe と判定する。抑制条件は (a) `expr` が unsigned または非負と証明可能（loop counter / range index / `len(...)` / 非負リテラル）、かつ (b) `len(container) > 0`（非空グローバルスライス・固定長配列・非空 composite literal・正リテラル `make`）。空コンテナや符号付きで負になり得る dividend は抑制せず警告を維持する。`grafana/pkg/registry/apis/provisioning/webhooks/pullrequest/changes_test.go` 型の false positive を解消。実装は `agent/strategies/foreign_code_strategy_helpers.py` の `_go_modulo_bounded_indices` / `_go_nonempty_container_names` / `_go_nonnegative_local_vars`、回帰テストは `tests/test_foreign_code.py`（`signed_modulo_len_index_is_guarded` / `modulo_empty_container_not_guarded` / `signed_modulo_negative_dividend_not_guarded`）。

## 現状

- mumeiリポジトリから分離直後（[mumei-lang/mumei#90](https://github.com/mumei-lang/mumei/pull/90)）
- single/multi-stage strategy、retry history、generate mode、metricsが実装済み
- 対応する violation type: `division_by_zero`, `precondition_violated`, `postcondition_violated`, `invariant_violated`, `linearity_violated`, `effect_mismatch`, `effect_propagation`, `temporal_effect_violated`

---

## 2026-10: Trust-aware repair and test-observation integrations (#616–#627)

- Claim Book consumption makes claim evidence and Seal Grade available to agent workflows. Sibling-lemma reuse is limited to machine-verified claims and carries dependency context.
- Repair paths can use Charter and contract-erosion checks, and classic heal now supports opt-in negative-controls candidate ranking after those checks. These checks do not replace the underlying proof result.
- `harvest-tests`, `observe-tests`, and `extract-spec --from-tests` connect existing test behavior to extracted contracts and observation checks. These observations inform spec extraction but are not proofs.
- Regression coverage spans Claim Book consumption, guard/gate behavior, harvested-test observations, `--from-tests` extraction (including the #625 fix), and sibling-lemma proliferation.

## P1-A: Generate Mode の強化 (最高優先度) ✅ Complete

- ✅ 仕様からの atom 生成: spec JSON → generate_code() → mumei verify → self-healing loop
- ✅ `mumei infer-contracts`/`mumei infer-effects` 統合済み
- ✅ テンプレートベースの生成: skeleton + fill-in-the-blanks 形式
- ✅ Common mistakes checklist injected into all generation prompts
- ✅ Pre-generation checklist extracted from spec constraints

---

## P1-B: structured_unsat_core の活用 (最高優先度) ✅ Complete

- ✅ `structured_unsat_core` parsed and formatted in `report_formatter.py`
- ✅ All prompt templates (`precondition`, `postcondition`, `invariant`, `division_by_zero`) include structured unsat core
- ✅ `format_actionable_fix_hint()` translates failures into concrete instructions
- ✅ `format_for_initial_generate()` extracts spec constraints as pre-warnings
- ✅ `_build_retry_prompt()` combines actionable hints + unsat core + data flow + error diff

---

## P1-C: E2E テスト・CI の整備 (高優先度) ✅ Complete

- ✅ GitHub Actions で `pytest` を実行するCI（`.github/workflows/ci.yml`）
- ✅ `pyproject.toml` に `[tool.pytest.ini_options]` と `integration` マーカー定義
- ✅ CI では `-m "not integration"` で integration テストを除外
- ✅ `format_error_diff` のユニットテスト追加（UNCHANGED / CHANGED / RESOLVED）
- ✅ カバレッジレポート出力（`--cov=agent`, XML artifact アップロード）
- ✅ mumei 実バイナリを使ったインテグレーションテスト (`tests/test_binary_integration.py`)
  - 各 violation fixture (`tests/fixtures/*.mm`) に対して `mumei verify --json` を実行し `violation_type` を検証
  - `valid.mm` の検証成功テスト
  - Self-healing ループ統合テスト（LLM は Mock、mumei バイナリは実物）
  - `mumei check` パーステスト
- ✅ mumei バイナリのモック or 実バイナリを使ったインテグレーションテスト (`tests/test_integration_e2e.py`)
  - `tests/fixtures/mock_mumei.py` — mumei CLI のモックスクリプト（`verify --json` / `check` 対応）
  - `tests/fixtures/reports/*.json` — 各 violation type のレポート JSON
  - 各 violation type に対する verify → fix → re-verify ループの E2E テスト
  - `@pytest.mark.integration` マーカーで CI から除外可能
- ✅ 各 violation type に対する修正成功率の回帰テスト (`tests/test_regression.py`)
  - `Metrics.success_rate()` / `Metrics.overall_success_rate` メソッド追加
  - `TestRegressionSuccessRate`: 各 violation type で N=5 回の fix pipeline 実行、成功率 ≥ 80% を検証
  - `TestMetricsSuccessRate`: success_rate / overall_success_rate のユニットテスト

### 対象ファイル
- `.github/workflows/ci.yml` — CI ワークフロー
- `tests/test_prompts.py` — `format_error_diff` テスト追加
- `tests/test_binary_integration.py` — mumei バイナリ統合テスト
- `tests/test_integration_e2e.py` — モック mumei バイナリ E2E 統合テスト
- `tests/conftest.py` — `real_mumei_client` / `fixtures_dir` / `mumei_mock_bin` / `mumei_mock_e2e_client` fixture 追加
- `tests/fixtures/mock_mumei.py` — mumei CLI モックスクリプト
- `tests/fixtures/reports/*.json` — 各 violation type のレポート JSON
- `tests/fixtures/*.mm` — 各 violation type のサンプルファイル
- `agent/metrics.py` — `success_rate()` / `overall_success_rate` メソッド追加
- `pyproject.toml` — pytest 設定・テスト依存

---

## P3-B: 「仕様 → 検証済みAPIクライアント」E2Eデモ (中優先度) ✅ Complete

mumeiの思想の究極的な体現:

1. 自然言語で「GitHub API からユーザー情報を取得し、名前を返す」と指示
2. mumei-agent が `atom` を生成（`effects: [SecureHttpGet]`, `requires`/`ensures` 付き）
3. `mumei verify` で検証
4. 失敗時は self-healing ループで自動修正
5. 検証通過後、Rust/Go/TypeScript にトランスパイル

### 前提条件
- ✅ P1-A (Generate Mode 強化) 完了
- ✅ mumei 側の P2-A (Cross-atom composition) 完了

### 実装済み
- ✅ `examples/e2e_demo_spec.json` — デモ仕様ファイル (fetch_github_user, `inputs`/`requires`/`ensures`/`return_type` 対応)
- ✅ `examples/simple_add_spec.json` — 最小デモ仕様ファイル (mumei バイナリなしでもテスト可能)
- ✅ `examples/simple_e2e_spec.json` — 純粋算術 `safe_div` デモ (エフェクトなし、LLM 不要でフロー確認可能)
- ✅ `examples/run_e2e_demo.py` — デモ実行スクリプト (spec → generate → verify → build → summary, `--dry-run` 対応)
- ✅ `tests/test_e2e_demo.py` — E2E デモのバリデーション・モックテスト (`simple_e2e_spec.json` テスト含む)
- ✅ Contextual suggestion の活用強化 (`format_actionable_fix_hint()` / `_build_retry_prompt()`)

---

## P3-C: CI Verification Gate (中優先度) ✅ Phase 1 Complete

PR 上の `.mm` ファイルを自動検証し、結果をコメントとして投稿するパイプライン。

### Phase 1 — 実装済み
- ✅ `scripts/ci_verify.py` — `.mm` ファイルの自動発見・検証・Markdown レポート生成
- ✅ `.github/workflows/mumei-verify.yml` — 再利用可能な検証ワークフロー (`workflow_call`)
- ✅ `.github/workflows/verify-examples.yml` — `examples/*.mm` の自動検証
- ✅ `tests/test_ci_verify.py` — ファイル発見・Markdown フォーマットのユニットテスト
- ✅ Proof certificate 生成・アーティファクトアップロード対応
- ✅ PR コメントへの検証結果自動投稿 (`marocchino/sticky-pull-request-comment`)

### 対象ファイル
- `scripts/ci_verify.py` — CI 検証ゲートスクリプト
- `.github/workflows/mumei-verify.yml` — 再利用可能ワークフロー
- `.github/workflows/verify-examples.yml` — examples 検証ワークフロー
- `tests/test_ci_verify.py` — ユニットテスト

---

## P6-A: Multi-atom / Multi-file 生成 ✅ Complete

- ✅ Multi-atom spec JSON フォーマット (`atoms: [...]` 配列)
- ✅ `generate_multi_atom()`: 依存関係検出・ソート・一括生成・atom 単位 retry
- ✅ 既存 single-atom spec との後方互換性維持

## P6-B: Pattern Library の学習型拡張 ✅ Complete

- ✅ `FixPattern` に `applied_count` / `success_count` フィールド追加
- ✅ `try_pattern_fix()`: 成功率ベースのパターン自動適用（LLM バイパス）
- ✅ `lookup()` の成功率ランキング
- ✅ `Metrics` に `pattern_attempts` / `pattern_successes` 追加

## P6-C: Specification Refinement Loop ✅ Complete

- ✅ `spec_refinement.py`: 検証失敗時に仕様（requires/ensures）自体の修正を提案
- ✅ `RetryHistory.is_same_error_repeating()` トリガーで仕様洗練モードに切り替え
- ✅ `mumei infer-contracts` 結果を活用した仕様推論

## P8-C: Proof-friendly Specification Metrics ✅ Complete (PR #87)

`mumei-agent` now measures whether newly generated specifications stay inside the Z3-stable decidable fragment before escalating to Lean.

- ✅ `agent.mcp_server.get_spec_guidelines()` — MCP clients can request guidance for linear arithmetic, bounded array/sequence access, bounded quantifiers, and finite temporal state machines.
- ✅ Generation prompts include the same decidable-fragment checklist and tell the agent to simplify specs that trigger `outside_decidable_fragment` before changing implementation code.
- ✅ `Metrics.record_new_spec()` tracks `new_spec_attempts`, `outside_decidable_fragment_warnings`, `z3_unknowns`, `first_pass_verification_success_rate`, and `by_logic_fragment` success rates for quarterly guidance refreshes.
- ✅ Lean escalation remains explicit: non-linear arithmetic, symbolic division/modulo, quantifier alternation, and unbounded temporal invariants are tagged for Lean rather than hidden in first-pass Z3 retries.

---

## P14: `.mm`を書かない入口 / Spec-Code Verification Suite ✅ Implemented

P14 は、既存コードまたは自然言語仕様をそのまま監査入口にし、必要な部分だけ
`.mm` skeleton へ移行するための実装群。2026-06-15 時点では、CLI / MCP / docs / demo
の導線が揃っている。

### P14-A: 自然言語仕様の健全性検証強化 ✅ Implemented

自然言語仕様を `.mm` 生成前に検査し、矛盾・曖昧さ・過制約・vacuity を spec-only
feedback として返す。

**実装タスク**:

1. `validate-spec --input spec.txt --format nl` で contradiction / ambiguity /
   overconstraint / satisfiability を統合検査する。
2. `extract-spec --check-contradiction-only` で code generation を行わず direct contradiction
   だけを fail-fast で返す。
3. `contradiction_type` を `NLSpecValidationResult` / `SpecCodeAlignmentResult` と
   human / markdown report に含める。
4. MCP tool `check_spec_contradiction(natural_language, domain_hint="")` を公開する。

**対象ファイル**:

- `agent/cross_validation.py` — `NLSpecValidationResult.contradiction_type`
- `agent/extract_spec.py` — contradiction-only extraction
- `agent/report_formatter.py` — `contradiction_type` 表示
- `agent/mcp_server.py` — `check_spec_contradiction`
- `tests/test_cross_validation.py`, `tests/test_report_formatter.py`, `tests/test_mcp_server.py`

**成功指標**:

- `.mm` 生成前に直接矛盾を検出できる。
- CLI / MCP / Markdown report が同じ `contradiction_type` を返す。
- LLM 生成失敗ではなく仕様側の問題として human review に回せる。

### P14-B: 他言語コードの論理的健全性検証 ✅ Implemented

既存 Python/Rust/TypeScript/Go/Solidity コードを `.mm` なしで監査し、問題箇所だけ migration hints
へ送る。V1-B の新規スコープとして、Python 以外の no-`.mm` 入口を Rust / TypeScript / Go / Solidity まで拡張し、固定語彙と `audit -> migrate-suggest -> heal` の順序は変更しない。

**実装タスク**:

1. `audit --code-file src/foo.py` で code-to-spec extraction、spec health、
   foreign-code verification、cross-validation を統合実行する。
2. `audit --code-file src/` でディレクトリ内の対応ファイルを再帰スキャンし、
   `AuditDirectoryResult` として集約する。
3. `--auto-migrate` で migration skeleton を生成し、`--auto-heal` で self-healing loop
   を続けて実行する。
4. `--heal-output-dir` で生成・修復済み `.mm` の出力先を指定できるようにする。
5. Rust / TypeScript / Go の決定的 parser 経路で関数シグネチャ、pre/postcondition 候補、分岐・安全性条件を抽出し、Rust overflow/bounds、TypeScript null/undefined、Go bounds/nil/overflow の代表ケースを Z3 counterexample 付き `verification_violations` に接続する。
6. `validate-code`, `validate-spec-to-code`, `validate-code-to-spec`, MCP `scan_and_fix` の対応言語を Python / Rust / TypeScript / Go に揃え、LLM credential なしの fixture 経路を維持する。

**対象ファイル**:

- `agent/audit.py` — `AuditPipeline`, directory scan, `--auto-migrate`, `--auto-heal`
- `agent/extract_spec.py` — `_collect_code_files()` / directory extraction
- `agent/mm_migration_advisor.py` — migration hints / skeletons
- `agent/strategies/foreign_code_strategy.py` — foreign-code contract verification
- `tests/test_audit.py`, `tests/test_cross_validation.py`, `tests/test_extract_spec.py`, `tests/test_mm_migration_advisor.py`

**成功指標**:

- `uv run mumei-agent audit --code-file src/` が複数ファイルを処理し、成功/失敗件数を集約する。
- 問題ありの関数だけ `.mm` skeleton と self-heal 対象になる。
- `verification_violations`, `counterexample_values`, `cross_validation_gaps`,
  `migration_hints`, `healed_files` が機械可読に返る。
- Rust / TypeScript / Go 入力でも `AUDIT_SCHEMA_KEYS` が alias なしで揃い、`next_steps` が唯一の人間レビュー入口として返る。
- 回帰テストは Rust `a + b` overflow と `values[idx]` bounds、TypeScript `name!.length` null/undefined、Go `values[idx]` bounds を deterministic/no-LLM fixture と MCP `scan_and_fix` の両方で固定し、Z3 counterexample を `verification_violations` に集約する。

#### 対応レベル分離方針

言語対応は二層に分離する:

- **層A（spec 抽出）**: LLM/正規表現ベースの自然言語仕様抽出。`CodeToSpecExtractor.EXTENSION_MAP` を単一真実源とし、`rust`, `c`, `cpp`, `go`, `python`, `javascript`, `typescript`, `java`, `solidity` の9言語をサポートする。
- **層B（Z3 厳密検証）**: `CodeToSpecConverter.convert_source` および `validate_foreign_code` が対応する `python`, `rust`, `typescript`, `go`, `solidity` の5言語のみ。外部コードパーサ（`_python_params`, `_rust_params`, `_typescript_params`, `_go_params`, `_solidity_params`）は層B対応言語に限定する。

層A のみ対応の言語（`c`, `cpp`, `java`, `javascript`）で `convert_source` を呼ぶと「spec 抽出には対応するが Z3 厳密検証は未対応」のエラーを返す。層B の対応言語拡張（C/C++/Java パーサの追加等）は次タスク候補として残す。

Solidity（`.sol`）は関数レベルの契約（pre/postcondition）と `uint256`/`int256` の 256bit オーバーフロー・配列境界を最小スコープとして層A・層B 両方で対応する。`uint256`（下限 0）と `int256`（符号付き 256bit）の境界を Z3 counterexample として `verification_violations` に集約する。reentrancy / access control / Checks-Effects-Interactions などスマートコントラクト固有の状態機械検証は本対応のスコープ外とし、別タスク（下記「次タスク候補: スマートコントラクト固有パターン検証」）で扱う。

`validate-code` CLI の `--language` は省略可能とし、`--input` の拡張子から自動推定する。対応外拡張子の場合はエラーで終了する。

#### 次タスク候補: スマートコントラクト固有パターン検証

Solidity の Layer B は stage 1 として、CEI/reentrancy と access control 欠落の
**決定論的ヒューリスティック警告**を実装済み（Z3 証明ではない）。stage 2 では
reentrancy について guard-state-machine の Z3 検証を実装済み（`solc` 依存なし）。
stage 3 も実装完了しており、本タスクは全 stage が完了済み:

- **stage 3 ✅ 実装済み**: mumei-lean の `SmartContract.lean` / `GuardState` / `runGuard`
  モデルと `no_external_call_without_lock` 系 theorem による Lean 証明証跡化を完了。
  mumei-agent 側は `agent/strategies/foreign_code_strategy_helpers.py` の
  `extract_solidity_guard_trace_atoms` / `build_solidity_guard_trace_proof_certificate`
  が Solidity の guard-trace atom（`obligation_class == "smart_contract_guard_trace_obligation"`,
  `logic_fragment_tag == "smart_contract_guard_trace"`）を抽出し、mumei-lean の
  `scripts/expr_translator.py`（`OBLIGATION_CLASS_SMART_CONTRACT_GUARD_TRACE` /
  `render_guard_trace_theorem` / `normalize_guard_trace_translator_ir`）が
  `runGuard` トレース theorem を生成、Lake ビルドで `z3_check_result == "lean_verified"`
  へ昇格する。回帰ゲートは以下の CI 必須テスト:
  - mumei-agent: `tests/test_foreign_code.py` の guard-trace 証明証跡テストと
    `tests/test_audit.py::test_audit_pipeline_emits_guard_trace_certificate_and_upgrades_via_lean_bridge`
    （`.github/workflows/ci.yml` の "Guard-trace regression gate" ステップで明示実行）。
  - mumei-lean: `tests/test_lean_bridge_e2e.py::test_guard_trace_fixture_upgrades_unknown_to_lean_verified`
    （`z3_check_result == "lean_verified"` を検証）と
    `tests/test_ingest_cert.py::test_guard_trace_fixture_renders_run_guard_theorems_and_imports`。

- **access-control（stage 4a）✅ 実装済み**: reentrancy guard-trace と同じ方式で
  access-control 欠落を Z3→Lean へ昇格。mumei-lean の `SmartContract.lean` に
  `AccessState` / `AccessOp` / `runAccess` 状態機械と
  `no_state_write_without_auth`（auth なしの state write は `none`）系 theorem を追加。
  mumei-agent 側は `extract_solidity_access_control_atoms` /
  `build_solidity_access_control_proof_certificate` が、外部呼び出し可能かつ
  storage を書き換える関数について access-control atom
  （`obligation_class == "smart_contract_access_control_obligation"`,
  `logic_fragment_tag == "smart_contract_access_control"`）を抽出する。
  authorization guard（`onlyOwner` 等の modifier または `require(msg.sender == owner)`
  のような body ガード）があれば `[authCheck, stateWrite] -> AccessState.Checked`、
  なければ `[stateWrite] -> none` を obligation として lower する。view/pure 関数と
  外部呼び出し不可能な関数は obligation を生成しない。mumei-lean の
  `scripts/expr_translator.py`（`OBLIGATION_CLASS_SMART_CONTRACT_ACCESS_CONTROL` /
  `render_access_control_theorem` / `normalize_access_control_translator_ir`）が
  `runAccess` トレース theorem を生成し、Lake ビルドで `z3_check_result == "lean_verified"`
  へ昇格する。access-control 証跡は guard-trace と同一証明証跡（`proof_certificate`）に
  相乗りし、`agent/cross_validation.py` / `agent/audit.py` の Lean bridge 1 パスで
  両パターンをまとめて昇格する。回帰ゲート:
  - mumei-agent: `tests/test_foreign_code.py` の access-control 抽出・証跡・
    Lean bridge 昇格テストと
    `tests/test_audit.py::test_audit_pipeline_emits_access_control_certificate_and_upgrades_via_lean_bridge`
    （`.github/workflows/ci.yml` の "Access-control regression gate" ステップで明示実行）。
  - mumei-lean: `tests/test_lean_bridge_e2e.py::test_access_control_fixture_upgrades_unknown_to_lean_verified`
    と `tests/test_ingest_cert.py::test_access_control_fixture_renders_run_access_theorems_and_imports`。
- **CEI 順序（stage 4b）✅ 実装済み**: access-control に続く独立パターンとして
  Checks-Effects-Interactions 順序を Z3→Lean へ昇格。mumei-lean の
  `SmartContract.lean` に `CeiState`（`Effects` / `Interacted`）/ `CeiOp`
  （`effect` = storage write, `interaction` = external call）/ `ceiStep` /
  `runCei` 状態機械と `effect_after_interaction_is_none`（interaction 後の
  effect は `none`）/ `cei_ordered_trace_is_interacted` /
  `cei_violation_trace_is_none` theorem を追加。effect が interaction に
  先行する `[effect, interaction]` は `some CeiState.Interacted`、逆順の
  `[interaction, effect]` は `none` に評価される。mumei-agent 側は
  `extract_solidity_cei_atoms` / `build_solidity_cei_proof_certificate` が、
  storage 書き換えと external call の**両方**を含む関数について、ソース順の
  op トレースを `runCei` に落として CEI atom
  （`obligation_class == "smart_contract_cei_obligation"`,
  `logic_fragment_tag == "smart_contract_cei"`）を抽出する。期待結果は
  同じ状態機械をシミュレートして決定するため、メタデータのみで昇格せず
  具体トレースに基づく。mumei-lean 側 translator/ingest
  （`OBLIGATION_CLASS_SMART_CONTRACT_CEI` / `render_cei_theorem` /
  `normalize_cei_translator_ir` / `cei_expected_to_lean`）が `runCei` トレース
  theorem を生成し、Lake ビルドで `z3_check_result == "lean_verified"` へ昇格する。
  CEI 証跡は guard-trace / access-control と同一証明証跡（`proof_certificate`）に
  相乗りし、`agent/cross_validation.py` / `agent/audit.py` の Lean bridge 1 パスで
  全パターンをまとめて昇格する（マージ後に `certificate_hash` を再計算し、
  fingerprint が証跡内容と一致するよう維持）。回帰ゲート:
  - mumei-agent: `tests/test_foreign_code.py` の CEI 抽出・証跡・
    Lean bridge 昇格テストと
    `tests/test_audit.py::test_audit_pipeline_emits_cei_certificate_and_upgrades_via_lean_bridge`
    を `.github/workflows/ci.yml` の "CEI ordering regression gate" で明示実行。
  - mumei-lean: `tests/test_lean_bridge_e2e.py::test_cei_fixture_upgrades_unknown_to_lean_verified`
    と `tests/test_ingest_cert.py::test_cei_fixture_renders_run_cei_theorems_and_imports`。

#### 次タスク候補: 層B パーサの構文解析移行

層B のうち Python は `agent/strategies/foreign_code_strategy.py` の `extract_python` と
`agent/cross_validation_foreign.py` の `_infer_python_source_line_map` で標準 `ast` による
構文解析を使う。一方、Rust / TypeScript / Go / Solidity は
`agent/cross_validation_foreign.py` の `_infer_foreign_contracts_with_patterns` や
`agent/strategies/foreign_code_strategy_helpers.py` の `_rust_function_blocks` /
`_go_function_blocks` など、正規表現ベースの抽出に依存している。

正規表現は文脈自由なネスト構造を正確に扱えないため、その回避として
`_balanced_brace_body`（波括弧の手動カウント）、
`_strip_go_rust_literals_and_comments`（リテラル/コメント除去の前処理）、
`_is_function_name_in_source`（幻覚関数フィルタ）といった対症療法コードが必要になる。
この構造的脆さは主に「関数/ブロック抽出」に局在しているため、次の段階に分けて移行する:

- **stage 1（第一歩・最優先）✅ 実装済み**: 関数/ブロック抽出だけを tree-sitter による
  構文解析へ置き換えた。導入範囲は Rust / TypeScript / Go / Solidity の
  **関数/ブロック境界抽出のみ**で、安全性条件推論（除算ゼロ・overflow・bounds・nil、
  reentrancy / CEI / access-control 等）は当面 `_generic_safety_requires_for_expression`
  など正規表現ヒューリスティクスに残す（= stage 2 の範囲）。Python が採る
  「関数抽出は `ast`、安全性推論はフォールバックで正規表現」という構成と対称にし、
  blast radius を抽出層に閉じる。
  - 新規モジュール `agent/tree_sitter_extract.py` が `function_blocks` /
    `function_line_map` / `function_names` を提供し、tree-sitter またはいずれかの
    言語文法が未導入・パース不能な場合は `None` を返して既存の正規表現経路へ
    フォールバックする（Python の `extract_python` が `SyntaxError` 時に空を返すのと
    同じ堅牢性方針）。
  - 置き換えた経路: `agent/strategies/foreign_code_strategy_helpers.py` の
    `_rust_function_blocks` / `_go_function_blocks` / `_typescript_function_blocks` /
    `_solidity_function_blocks`、`agent/cross_validation_foreign.py` の
    `_infer_foreign_source_line_map`（Rust / TypeScript / Go / Solidity）、
    `agent/cross_validation.py` の `_is_function_name_in_source`（幻覚 atom フィルタ）。
  - 依存: `pyproject.toml` に `tree-sitter` 本体と `tree-sitter-rust` /
    `tree-sitter-go` / `tree-sitter-typescript` / `tree-sitter-solidity` の文法 wheel を
    追加。いずれも純粋な in-process パーサで `solc` / `rustc` / `tsc` やネットワークを
    要求せず、LLM credential なしで決定論的に同一結果を返す（`CI_FIXTURE_MODE`
    経路を維持）。
  - これにより正規表現由来の構造的脆さ（ネスト波括弧の取りこぼし、文字列/コメント内の
    `{}` や `fn`/`func`/`function` の誤検出、class メソッドやネスト関数の取りこぼし）が
    解消され、対症療法だった `_balanced_brace_body` / `_strip_go_rust_literals_and_comments`
    は関数境界特定については不要化した（安全性推論側の body 前処理では引き続き使用）。
- **stage 2 ✅ 実装済み**: 安全性条件推論の式パース部分を構文木ベースへ拡張した。
  除算ゼロ (`/` `%`)・配列境界 (`container[index]`)・null/undefined (`.length` /
  `.len` / `.is_empty`)・nil 参照 (`*value` / `value.member`)・integer overflow
  (`a + b`) の各パターン検出を、正規表現の文字列マッチではなく構文ノード走査で行う。
  - `agent/tree_sitter_extract.py` に `analyze_expression` を追加。式を各言語文法が
    受理する最小の構文へラップして tree-sitter でパースし、除数・添字アクセス・
    `.length` レシーバ・メンバアクセス・ポインタ deref・加算ペアを **構文的事実** として
    抽出した `ExpressionSafety` を返す。tree-sitter または文法が未導入、パース失敗
    (`root_node.has_error`)、非対応言語の場合は `None` を返し、既存の正規表現経路へ
    フォールバックする（Python の `_safety_requires_for_expression` が
    `SyntaxError` 時に正規表現へ戻る方針と対称）。Python は従来どおり標準 `ast` 経路。
  - 置き換えた経路: `agent/cross_validation_foreign.py` の
    `_safety_requires_for_expression`（非 Python）/ `_generic_safety_requires_for_expression`
    相当 / `_integer_overflow_requires_for_expression` / `_go_nil_dereference_values` /
    Solidity overflow、`agent/strategies/foreign_code_strategy_helpers.py` の
    `_issues_for_expression`（境界・除算・null/nil・overflow）と `_go_nil_dereference_values`。
    戻り値インタフェース（`ForeignSafetyIssue` のリスト、`requires` 文字列、
    counterexample、required_contracts）と出力順序は不変。
  - これにより文字列/コメント内の `/` `[]` `+` の誤検出、`obj.a / obj.b` のメンバ
    アクセス誤認、ネスト添字 `a[b[c]]` の取りこぼしといった正規表現の構造的脆さが
    解消される。`solc` / `rustc` / `tsc` に依存せず、LLM credential なしで決定論的に
    同一結果を返す（`CI_FIXTURE_MODE` 経路を維持）。
- **別軸（意味解析強化）✅ 実装済み**: #281 / #295 / #296 のような偽陽性（`SafeCast` の
  誤認、value 型への `!= nil` / `!= null` 誤付与、`constant` / `immutable` 除数・添字の偽
  counterexample）は tree-sitter 化（構文的事実の抽出）だけでは解消しない。抽出された
  式・型・定数から安全性条件を導出する **意味解析層** を新規モジュール
  `agent/semantic_safety.py` に集約し、散在していた個別分岐を型述語と定数モデルへ
  統一した。
  - **定数モデル（#296）**: `collect_declared_constants(source, language)` が Solidity
    `constant` / `immutable`・Rust `const` / `static`・TypeScript `const` の整数リテラルを
    言語横断で収集する。`divisor_provably_nonzero` / `known_nonnegative_index` を通じて、
    除数がゼロになり得ない定数・添字が負になり得ない定数を検出し、除算ゼロ / 配列境界の
    偽 counterexample を抑止する（従来 Solidity のみだった `known_constants` 参照を
    Rust / TypeScript の検証・契約推論両経路へ拡張）。overflow は健全性維持のため定数で
    抑止しない（自由変数側でオーバーフローし得るため）。
  - **型述語（#295）**: `is_nullable_type(raw_type, language)` /
    `should_flag_null_deref(...)` が「参照・ポインタ・nullable か」を言語横断で判定する
    単一の述語となり、Go の nil 参照（`_go_type_is_nillable` を委譲）・Solidity value
    型・Rust 参照・TypeScript primitive を統一的に扱う。value 型パラメータへの
    `!= nil` / `!= null` 付与を言語横断で抑止し、契約推論経路の Solidity / Rust
    `.length` / `.len` 誤付与（従来の全言語一律付与）を解消した。
  - **メンバアクセス / 呼び出しレシーバ（#281）**: overflow オペランドがメンバアクセス
    （`a.b`）・関数呼び出し（`f()`）である場合に自由整数変数として扱わない判定は、stage 2
    の構文木情報（`tree_sitter_extract` の `_operand_is_receiver`）を主経路とし、tree-sitter
    非利用時は正規表現 `_operand_is_member_or_call` にフォールバックする。
  - 型・定数情報が取得できない場合は従来どおり保守的に安全性条件を生成する
    （偽陽性は許容しても偽陰性で健全性を損なわない）フォールバックを維持し、決定論性・
    no-LLM fixture（`CI_FIXTURE_MODE`）・コンパイラ非依存（`solc` / `rustc` / `tsc` 不要）・
    Z3 健全性を損なわない。
  - **残る未対応領域**: 定数畳み込み（`const` を参照する派生定数、算術式の初期化子）は
    値解決せず保守側に倒す。TypeScript の非 optional value 型への null 抑止は既定で
    nullable 扱いのまま（`x!.length` の非 null アサーションを尊重）。関数スコープを跨いだ
    エイリアス解析・データフロー解析は範囲外（LLM 意味推論は導入しない）。

#### 外部コード安全性推論の意味モデル化（データフロー / パス感度）✅ Implemented (stage 3)

**実装状況（stage 3, Track A-1〜A-6 の関数内ローカル範囲）**:

- `agent/tree_sitter_extract.py` に文レベル走査 `extract_statements` を追加（Go）。`if` /
  `for` / `range` / `switch` / `return` / `break` / 短変数宣言 / 代入 / `defer` / 関数リテラル
  を `Statement` 木として返し、クロージャ内で再代入された名前・`&x` でアドレスが取られた
  名前を `StatementTree.closure_assigned` / `address_taken` として報告する。
- 新規 `agent/dataflow_facts.py` が第三の入力「データフロー事実」を算出する
  （`analyze_function(body, "go", constants=, param_names=, nonneg_names=, nonzero_names=,
  sequence_names=) -> FunctionDataflow`）。各 `return` 式に到達する `PathFacts`
  （`nonzero` / `nonneg` / `nonnil` / `lt_len` / `len_ge` / `consts`）を返す。
  - A-1 定数畳み込み: `evaluate_constant_expression` / `fold_constants`（依存順解決、
    `int64` に収まらない・非整数・未知名参照は未解決のまま保守側）。関数内 `const` ブロックも
    畳み込む。
  - A-2 ガード伝播: `if` / 早期 `return` / `switch` の case / ループ条件から真偽両分岐の事実を
    導出し、合流点では交差（intersection）で保守的にマージする。ループは 0 回実行と
    n 回実行後の状態を交差し、`break` を含む場合は代入名を全て破棄する。
  - A-3 到達定義: `x := 100` / `x = other` の再定義で事実を kill、`n := len(xs)` /
    `len(xs) - 1` / `k % len(xs)`（`xs` 非空が既知の場合のみ）/ `make([]T, n+1)` 由来の値を
    `lt_len` に反映する。
  - A-4 局所エイリアス: `ys := xs` のスライス別名で長さ事実を共有し、クロージャ内再代入・
    アドレス取得された名前は事実対象から外す（`&files[i]` の要素アドレスは対象外）。
- 消費側: `_detect_go_safety_issues` は `analyze_expression` の構文的事実、`semantic_safety`
  の型・定数モデルに加えて `flow.facts_for_expression(expr)` を参照し、除数の `nonzero`、添字の
  `bounded_indices`、レシーバの `nonnil`、局所定数を既存の Z3 モデルに供給する。
  `cross_validation_foreign._infer_go_contracts_tree_sitter` も同じ事実を（局所定数のみ）
  `requires` 推論の定数モデルに接続する。`ForeignSafetyIssue` / `requires` 文字列 /
  counterexample / required_contracts と出力順序（bounds → nil → division → overflow）は不変。
- A-5 抑制ヘルパ削減: 8 系統のヘルパ（`_go_zero_guarded_nonzero_params` /
  `_go_zero_guarded_nonzero_locals` / `_go_zero_guarded_nonzero_names` /
  `_go_dual_len_loop_guarded_indices` / `_go_grow_guarded_indices` /
  `_go_last_index_guarded_indices` / `_go_reverse_loop_guarded_indices` /
  `_go_modulo_bounded_indices`）をデータフロー層で置換・削除した。続く第 2 弾で
  `_go_median_guarded_indices`（`mid := len(arr)/2` は `_LEN_DIV` + 非空ガードで汎用
  カバー）と `_go_sort_search_guarded_indices`（`sort.Search` 結果は `i < len(files)`
  条件ガードで汎用カバー、クロージャ本体は対象外）も削除した。あわせて `_define` が
  `x := len(c)` で `len_values` を seed しない非対称を修正し、`(a+b)>>k` / `(a+b)/k`
  （両項が同一コンテナの `lt_len`/`len_values` で非負・少なくとも一方は厳格 `< len`）を
  midpoint 規則として `_define`（`=`/`:=` 共通）に追加した。あわせて `_comparison` で
  左辺が既知 const の比較（`0 < hi` 等）が演算子反転で `lt_len` を失っていた点を修正し、
  反転前に len-alias 右辺へ `lt_len` を記録するようにした。残る特化ヘルパは置換不可を確認済み:
  `_go_binary_search_guarded_indices`（`hi = m` のループ内再代入で `len_values` が
  kill されるため不変式推論が必要 — 単一パス walk の範囲外）、`_go_enum_string_guarded_indices`
  / `_go_enum_string_array_guarded_indices`（`iota` enum 定数が `constants` で未解決のため
  範囲ガードの上端を証明できない）、`_go_bits_uint8_lookup_guarded_indices`（テーブル宣言が
  ソース内に存在せず `uint8 < 256` の型上端も未モデル化）。第 3 弾の監査では残存ヘルパを
  全件 probe 検証し、いずれも置換不可と確認: `_go_range_index_guarded_indices`（ループ内の
  直接 index は `_range` が `lt_len` を汎用付与済みだが、ループ後の alias 使用は may-fact
  merge で落ちる）、`_go_short_circuit_or_guarded_indices`（`i <= len` ∧ `i != len` の
  合成交差は単一パス事実モデルの範囲外）、`_go_pow10_guarded_indices`（`bits.Len64` の値域と
  テーブルサイズが未モデル）、`_go_op_enum_guarded_indices` / `_go_mapfast_guarded_indices` /
  `_go_cnames_guarded_indices`（enum・iota 定数の値域が未解決）。call site に保持理由を
  明記済みで A-5 は完了。
- A-6 新バグ種別（データフロー層のみで判定、既存 4 カテゴリの後ろに追記）: nil マップへの
  書き込み（`var m map[K]V` 未初期化のまま `m[k] = v`）、ロック二重取得（`mu.Lock()` 保持中の
  再 `Lock`）、ロック保持中の `return`（`defer Unlock` なし・当該パスで `Unlock` なし）、
  `os.Open` 等のハンドル未 `Close` での `return`（`defer Close` / 戻り値として返却 / 未知関数への
  受け渡しは所有権移転として抑止）。未初期化値の使用も対応済み（`uninitialized_use`）:
  `var` 宣言で nil 値を取るポインタ / スライス / `func` / `error`・`any`・`interface{…}` 型を
  `_Env.held` に（`uninit_ptr` / `uninit_slice` / `uninit_func` / `uninit_iface` / 既存 `nilmap`）
  として保持し、`nilable` 型事実が `p = &x` をまたいで残るため `p = nil` での再 nil 化や
  `T(nil)` キャスト、`x := p` エイリアスも追随する。確定パニックのみを報告する:
  `*p`・`p.field`・`p[i]`、`s[i]`（`s[a:b]` リスライスは `s[:0]` が合法なため対象外）、
  `f(…)`、`i.m(…)` / `i.(T)`。`p.m(…)` の nil レシーバ許容メソッド呼び出し、`len(s)` /
  `range s` / `append(s, …)` / nil マップ読み出し、`chan` の nil（`select` 無効化イディオム）は
  報告しない。`var (…)` グループ宣言は extractor が targets を返さないため `_var` が文面を
  行単位でパースして個別 spec に展開する（`nilmap` も同じ経路でカバー）。既知制約: 単一行の
  `var (x T)` は tree-sitter-go が parse error とし関数全体が regex フォールバックに落ちる
  （`nil_map_write` 等他カテゴリにも共通する従来制約）。状態遷移前提（ガード状態に
  依存する呼び出し順序）も対応済み: `close(ch)` 済み channel への `ch <- v` / 再 `close`
  （`send_on_closed_channel`）、nil channel の `close`（`close_nil_channel`）、
  `Close()` 済みハンドルの `Read`/`Write`/`Stat` 等の呼び出し（`use_after_close`）、
  `var mu sync.Mutex`・`sync.Mutex{}`/`new(sync.Mutex)` で未ロックと分かる mutex の
  `Unlock`/`RUnlock`（`unlock_of_unlocked`）を `_Env.held` の `closed_chan` /
  `closed_file` / `mutex_unlocked` / `uninit_chan` マーカで追跡する。`Unlock` 成功後は
  常に unlocked へ遷移するため、仮引数 mutex の 2 回目 `Unlock` も確定パニックとして報告。
  `x2 := x` のエイリアスには `closed_file` / `closed_chan` / `mutex_unlocked` / nil-able マーカが
  伝播し、`x.Close()` / `close(x)` は alias クラスタ全体に適用される（`("lock", …)` は
  コピーが *locked copy* になるため非伝播）。`make(chan|map|[]…)` / `&x` / `new(T)` / ident
  エイリアス由来の `:=` は nilable 型事実を seed するため `ch = nil` 等の再 nil 化も追随する
  （`var` 宣言以外でも）。nil chan への `ch <- v`・`<-ch`・`range ch` は panic ではなく
  ブロックのため対象外（`select` 無効化イディオム）。`defer` / `go` 呼出しとクロージャ本体は
  即時遷移としてマークしないが、登録時点で確定するパニック（nil / closed chan への
  `close`・送信、unlocked mutex の `Unlock`）は報告する。`*sync.Mutex` /
  `*sync.RWMutex` の nil 値は `uninit_mutex`（全メソッドがレシーバを deref するため
  `mu.Unlock()` も確定パニック）。契約由来事後条件（`contract_output_unassigned`）も
  対応済み: doc コメントの `ensures:` / `@ensures` / `postcondition:` が指名した
  named result / `*T` 出力引数が return パス上で一度も `=` 代入されない場合を報告する
  （`_Env.defined` の must-assign 交差マージで追跡。`return <exprs>` は named result を
  位置代入で満たすため対象外、`r := …` のシャドーイングは確立とみなさない、`*out` への
  書き込み・`f(out)` 呼出し引数は確立とみなすが、変数自体の再代入
  （`out = &x`）や `f(&out)`（`**T` は pointee を書かない）は確立とみなさない）。
  既知の制限: 後方 `goto` / 未宣言ラベル / 非祖先ブロックへの `goto` を含む関数は
  全体未解析（従来仕様。前方 `goto` はラベルで環境を合流して解析済み）、ループ内
  `continue` のみ先行する
  経路の代入は exit 交差マージで未確立扱いになり得る（偽陽性側）、`for` post 句での
  呼出し引数書き込みは 0 回実行があり得るため確立とみなさない。これで A-6 の拡張種別は
  全件対応。データフロー事実だけで閉じない義務は従来どおり `unverifiable` / Lean 送り。
- テスト: `tests/test_dataflow_facts.py`（定数畳み込み / ガード / 早期 return / ループ条件 /
  到達定義 / `len` 由来値 / エイリアス / クロージャ・アドレス無効化 / 削除ヘルパの旧偽陽性ケース /
  新バグ種別の正例・偽陽性例 / 契約由来事後条件の到達定義ケース）。既存
  `tests/test_foreign_code.py` / `tests/test_cross_validation.py` は無変更で通過。
- 解析は関数内ローカルに閉じ、LLM・`solc` / `rustc` / `tsc` に依存せず決定論的。

**cross-repo 位置づけ**: 本タスクは [mumei `docs/CROSS_PROJECT_ROADMAP.md` Priority 25](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) の **Track A**（A-1 データフロー事実の器 + 定数畳み込み → A-2 ガード伝播 → A-3 到達定義 / `len` 由来値 → A-4 局所エイリアス → A-5 抑制ヘルパ置換と削減計測 → A-6 新バグ種別）として順序付けられている。Track B（Task 2-D）とは非依存で完全並行。A-6 は A-5 の削減計測が出てから着手する。完了時は Priority 25 の表と本節を同一 diff で更新する。

stage 1 / stage 2 / 意味解析強化で「構文的事実の抽出」と「型述語・定数モデル」は整った
が、外部コード安全性推論は依然として関数本体の **意味モデル** を持たない。
`agent/strategies/foreign_code_strategy_helpers.py` の `_detect_go_safety_issues` /
`_issues_from_findings` / `_i64_overflow_safety_issue` などは、抽出した式テキストを
構文的に走査し、遭遇した偽陽性パターンごとに抑制分岐（`_go_enum_string_guarded_indices` /
`_go_binary_search_guarded_indices` 等の
`_go_*_guarded_indices` 群、`_solidity_guaranteed_nonzero_params` 等の `guaranteed_nonzero`
系ヘルパ）を追加する構造になっている。その結果、検証できるバグ種別は bounds / nil /
division / overflow の 4 カテゴリに留まる一方、実装量は「検証できるバグ種別数」ではなく
「遭遇した偽陽性パターン数」に比例して膨張している。

- **根本原因**: 上記「残る未対応領域」に記した「関数スコープを跨いだエイリアス解析・
  データフロー解析は範囲外」が最大の制約である。ガード条件（`if i < len(xs)`）や
  代入（`n := len(xs); ... xs[n-1]`）が添字・除数にどう到達するかを追跡できないため、
  個々のコードイディオムを正規表現で認識する抑制分岐で代替せざるを得ない。
- **方針（stage 3 相当）**: 出発点は `agent/semantic_safety.py` への集約で実証済みの
  「型述語・定数モデルへの統一 = 実装量減 + 偽陽性減」を、データフロー事実へ拡張する
  ことである。関数内に閉じた **ローカルなデータフロー / パス感度解析** を導入する:
  - 定数畳み込み（`const` を参照する派生定数、算術式の初期化子の値解決）。
  - ガード条件の伝播（`if` / 早期 `return` / ループ条件から各文に到達する事実の収集）。
  - 代入到達（除数・添字に到達する定義の追跡、`len(xs)` 由来の値の識別）。
  - エイリアスの局所追跡（同一関数内でのスライス / ポインタ / 参照の別名付け）。
  これらを単一の「データフロー事実」として `analyze_expression` の構文的事実と
  `semantic_safety` の型・定数モデルに並ぶ第三の入力に据え、散在する
  `_go_*_guarded_indices` / `guaranteed_nonzero` 系ヘルパの多くを置き換える。狙いは
  「抑制コード削減」と「バグ種別拡大」を同一投資で両立することであり、既存の
  `ForeignSafetyIssue` / `requires` 文字列 / counterexample のインタフェースは不変とする。
- **健全性原則の維持**: 型・定数・データフロー情報が取得できない場合は保守側に倒す
  （偽陽性は許容しても偽陰性を出さない）方針を崩さない。`agent/semantic_safety.py`
  冒頭の方針と同じく、純粋な決定論的解析として LLM を呼ばず、`solc` / `rustc` / `tsc`
  にも依存せず、no-LLM / `CI_FIXTURE_MODE` 経路で同一結果を返す。
- **拡張先バグ種別の候補**: 現 4 カテゴリに加え、データフロー層があって初めて健全に
  扱える種別を候補とする — 未初期化値の使用、リソースの取得 / 解放不整合（open /
  close、lock / unlock の対応）、状態遷移の前提条件（ガード状態に依存する呼び出し順序）、
  契約由来の事後条件チェック（`ensures` が参照する戻り値・出力引数の到達定義）。
  これらは無償ではなく、データフロー事実だけで閉じない義務は従来どおり `unverifiable`
  または Lean 送りになるトレードオフを伴う。
- **スコープ外**: 「LLM 意味推論は導入しない」方針はこの stage でも維持する。関数
  スコープを跨いだ大域的なエイリアス / データフロー解析も本 stage の範囲外とし、
  関数内ローカル解析で解ける範囲を先に確定する。

### P14-C: 仕様↔コードのクロス検証 ✅ Implemented

自然言語仕様、既存コード、抽出された `.mm` を双方向に照合し、multi-file cross-spec
基盤へ接続する。

**実装タスク**:

1. `validate-spec-to-code --spec spec.txt --code src/foo.py` で仕様にある制約の未実装と
   divergence を検出する。
2. `validate-code-to-spec --code src/foo.py --spec spec.txt` でコード変更に対する仕様 drift
   を検出する。
3. `check_cross_spec_consistency(spec_files)` MCP tool で複数 `.mm` を
   `mumei verify --cross-spec-files` に渡し、`cross_spec.json` を返す。
4. mumei PR #285 の `contract_consistency[]`, `global_invariant_conflicts[]`,
   `circular_dependencies[]` を agent の repair / review 判断へ接続する。
5. V1-D-3 `verify-traceability` / `verify_code_spec_traceability` で V1-C の `conformance` と
   V1-D の `drift` を統合し、`cross_validation_gaps`, `drift_score`, `next_steps` を固定キーで返す。

**対象ファイル**:

- `agent/cross_validation.py` — `validate_spec_to_code`, `validate_code_to_spec`
- `agent/conformance_verifier.py`, `agent/traceability_verifier.py` — V1-C/V1-D summary
- `agent/spec_code_mapper.py` — spec/code traceability
- `agent/intent_tracker.py` — drift result
- `agent/mcp_server.py` — `check_cross_spec_consistency`,
  `validate_spec_to_code`, `validate_code_to_spec`, `verify_code_spec_traceability`
- `agent/verify_traceability.py`, `tests/test_traceability.py`, `tests/test_cross_validation.py`,
  `tests/test_mcp_server.py`

**成功指標**:

- `missing_constraints[]`, `divergences[]`, `drift_issues[]` が structured JSON で返る。
- V1-D-3 は `conformance`, `drift`, `cross_validation_gaps`, `drift_score`, `next_steps` だけを使い、別名 alias を出さない。
- 複数 `.mm` の cross-spec result を MCP client が直接取得できる。
- `cross_validation_gaps` が `audit` summary に集約され、migration / human review 分岐に使える。

### P14-D: 人間向けUX強化（Human-in-the-Loop）✅ Implemented

自動監査の結果を人間が判断しやすい導線にまとめ、`.mm` を書く前の入口を標準化する。

**実装タスク**:

1. `audit --auto-migrate --auto-heal` を 1 コマンド flow として documentation / CLI summary
   に明示する。
2. MCP tool `scan_and_fix(code_file, language, spec="", auto_heal=false, ...)`
   で `audit -> migrate-suggest -> heal` を全部 agent から実行できるようにする。
3. `contradiction_type`, `migration_hints`, `cross_validation_gaps`, `heal_errors`
   を `next_steps` 起点の human review 判定材料として出す。
4. README の `.mmを書かない入口` flowchart を `scan_and_fix`, `--auto-migrate`,
   `--auto-heal` を含む最新導線に更新する。

**対象ファイル**:

- `README.md` — no-`.mm` entry flowchart
- `docs/VERIFICATION_WORKFLOW_GUIDE.md` — audit / directory scan / MCP guide
- `agent/mcp_server.py` — `scan_and_fix`
- `agent/human_review.py` — human-review metadata
- `agent/report_formatter.py` — human / markdown report

**成功指標**:

- 既存コードから `uv run mumei-agent audit --code-file src/ --auto-migrate --auto-heal`
  だけで監査・移行・修復まで試せる。
- MCP client は `scan_and_fix` だけで同じ workflow を実行できる。
- 問題なし / 自動修復可能 / human review の分岐が README と guide で一致する。

---

## Strategic Initiatives（次期戦略）

mumei エコシステム全体の戦略的イニシアチブ。詳細は [mumei-lang/mumei の docs/CROSS_PROJECT_ROADMAP.md](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) を参照。

### SI-1: Zero-Human Challenge — ✅ Complete

mumei-agent に難易度の高い課題（100% 安全なキュー、Verified JSON validator 等）を与え、人間が一切介入せずに検証をパスするまでのログを公開する。

**mumei-agent 側の作業**:
- ✅ `examples/challenges/` に課題 spec JSON を作成（safe_queue, verified_json_validator, deadlock_free_producer_consumer, bounded_queue, safe_arithmetic, payment, verified_clamp）
- ✅ `examples/challenges/benchmark.py` — ベンチマーク集計・Markdown レポート生成
- ✅ `examples/challenges/run_challenge.py` — チャレンジ実行パイプライン + パターン自動登録
- ✅ rule_based_fix: postcondition_violated, invariant_violated, linearity_violated 対応追加
- ✅ `agent/metrics.py` — `llm_tokens_used` フィールド追加
- ✅ `--dry-run` モードで全 7 spec のバリデーション完了 (7/7 OK)
- ✅ `examples/challenges/results/` に結果テンプレート・サンプル生成コードを配置
- ✅ `docs/ZERO_HUMAN_CHALLENGE.md` — チャレンジ分析ドキュメント作成
- ✅ `.github/workflows/challenge.yml` — `workflow_dispatch` でフル実行可能

**前提条件**: P6-A (Multi-atom 生成) ✅ 完了済み

### SI-3: Autonomous Delivery Flow — ✅ Complete (実地検証完了)

mumei-agent が mumei コードを書く → 検証 → Rust/Python ラッパーを自動生成 → PR を出す。

**mumei-agent 側の作業**:
- ✅ `--publish` モードの追加（生成 → 検証 → ラッパー生成 → git commit → PR）
- ✅ GitHub API 連携
- ✅ GitHub Actions CI テスト（`.github/workflows/verify-publish.yml`）
  - PR 内の `.mm` ファイルを自動検出
  - `mumei verify --json` で検証
  - `--emit c-header` / `rust-wrapper` / `python-wrapper` の生成・コンパイル確認
  - `rustc` によるRustラッパーコンパイルチェック
  - Python `ast.parse` による構文チェック
  - 結果を PR コメントとして投稿（`marocchino/sticky-pull-request-comment`）
- ✅ `examples/publish_demo/` — デモ spec + ドキュメント
- ✅ `tests/test_publish.py` — パイプライン全体のユニットテスト（dry-run, emit targets, verification failure, branch naming）

**実地検証（E2E テスト・CI 連携確認）**:
- ✅ `tests/test_publish_e2e.py` — E2E インテグレーションテスト
  - 既存 spec（`simple_add_spec.json`, `simple_e2e_spec.json`, `payment_spec.json`）を使った dry-run パイプラインテスト
  - mock mumei バイナリ（`tests/fixtures/mock_mumei.py`）を使った完全パイプラインテスト
  - 生成ファイル（`.mm`）の存在・内容検証
  - `@pytest.mark.integration` マーカー付与
- ✅ `tests/test_wrapper_validation.py` — FFI ラッパー静的検証テスト
  - C ヘッダー: `#ifndef` ガード、`stdint.h` インクルード、関数宣言、Doxygen `@pre`/`@post`
  - Rust ラッパー: `extern "C"` ブロック、安全ラッパー（`_checked`）、`Option<T>` 戻り値
  - Python ラッパー: `ctypes` インポート、`argtypes`/`restype` 定義、型ヒント、`ast.parse` 検証
  - クロスラッパー一貫性: 関数名・パラメータ数・マルチ atom 対応の整合性チェック
- ✅ `.github/workflows/verify-examples.yml` — publish dry-run テストジョブ追加
- ✅ `docs/AUTONOMOUS_DELIVERY.md` — パイプライン全体フロー図（mermaid）、使い方、環境変数、CI 連携、FFI glue code の説明

**前提条件**: SI-1, SI-2 (Verified FFI Boundary, mumei 側), Rust/Python Wrapper Emitter (mumei 側)

---

## P9: Autonomous Forge Mode — ✅ Infrastructure Complete / 🔧 Expansion In Progress

`forge` モードは、mumei-agent が自律的に std ライブラリを拡張・検証・コミットする新しい運用モード。既存の generate + self-healing + publish パイプラインを再利用し、「タスク発見」と「オーケストレーション」のレイヤーを追加する。

### P9-A: Forge Infrastructure ✅ Complete (PR #31)

- ✅ `forge_tasks/` — タスク spec JSON 配置ディレクトリ (`vstd_safe_add.json`, `vstd_safe_multiply.json`, `README.md`)
- ✅ `agent/forge_discovery.py` — `discover_tasks()` / `scan_std_todos()` / `filter_completed_tasks()`
- ✅ `agent/forge.py` — `MumeiForge` オーケストレーター（`append` / `create` / `replace` モード、`forge_log.json` ロギング、`fcntl.flock` による排他制御）
- ✅ `agent/prompts/forge/` — 鍛冶職人（Master Blacksmith）システムプロンプト + append mode プロンプト（`reference_patterns` で指定された既存 atom のコードを style context として注入）
- ✅ `python -m agent forge` CLI サブコマンド（`--tasks-dir` / `--mumei-repo` / `--max-tasks` / `--task` / `--dry-run` / `--auto-commit` / `--max-retries` / `--log-path`）
- ✅ `tests/test_forge_discovery.py`, `tests/test_forge.py`, `tests/test_forge_e2e.py`（最後は `@pytest.mark.integration`）
- ✅ `.github/workflows/forge.yml` — 手動 workflow_dispatch 実行用（schedule はコメントアウト）
- ✅ ファイル復元機構（post-write verify 失敗時のロールバック）
- ✅ `forge_log.json` によるタスク完了追跡

### P9-B: Z3 Logical Repair Protocol ✅ Integrated

- ✅ `FORGE_SYSTEM_PROMPT` に論理修復プロトコル（Counterexample Extraction → Unsat Core Analysis → Repair Strategy Selection → Code Transformation）を組み込み
- ✅ `build_append_prompt` のリトライセクションを Logical Repair Analysis 指示文に書き換え
- ✅ `_forge_append` の verify 失敗時に `report_formatter` の `format_actionable_fix_hint` / `format_counterexample` / `format_structured_unsat_core` を再利用し、LLM に構造化された修復ヒントを注入

### P9-C: Cross-file Context Loading ✅ Integrated

- ✅ タスク spec の `context_files` フィールドで関連モジュールを LLM コンテキストに注入（`MumeiForge._load_context_files` + `build_append_prompt(cross_file_context=...)`）
- ✅ 複数 std ファイルをまたいだスタイル / 契約パターンの参照基盤
- ✅ `create` / `replace` モードでも `_task_to_generate_spec` が spec に `cross_file_context` を付与

### P9-D: vStd Autonomous Expansion ✅ Phase 1-3 Complete

- ✅ Phase 1 Created→Forged: 7/7 タスクを昇格（既存生成済みの ownership / regtech / settlement は再検証で採用、trait-iterable / sorted-list / priority-queue / set を verified std atom に整備）
- ✅ Phase 2 Forged→Verified: 16/16 タスクを `mumei verify --proof-cert` で検証（Low 5、Medium 10、High 1）
- ✅ 追加検証: Phase 1 の 7 タスクもすべて proof certificate 生成フローで検証済み
- ✅ 成功指標: created 昇格率 100%、forged verified 昇格率 100%（目標 ≥80%）、Lean escalation は不要（対象 atom は Z3 decidable fragment 内で完了）

- ✅ `forge_tasks/vstd_safe_list.json` — `std/container/safe_list.mm` の `safe_push` / `safe_pop` / `safe_peek` / `safe_len` 鍛造ターゲット（`safe_queue.mm` パターン拡張）
- ✅ `forge_tasks/vstd_fixed_point.json` — `std/math/fixed_point.mm` 固定小数点演算モジュール（`fixed_from_int` / `fixed_to_int` / `fixed_add` / `fixed_mul`、`safe_mul.mm` を活用）
- ✅ `forge_tasks/vstd_string_utils.json` — `std/string_utils.mm` 文字列ユーティリティ（`safe_truncate` / `is_ascii`、propose-driven gap task）
- ✅ `forge_tasks/vstd_math_min_max.json` — `std/math/min_max.mm` min/max プリミティブ（`min2` / `max2` / `min3`、propose-driven gap task）
- ✅ `forge_tasks/vstd_iter.json` — `std/iter.mm` index-based iterator primitives（`analyze_std_gaps` の iter gap rule に対応）
- ✅ `forge_tasks/vstd_hash.json` — `std/hash.mm` Hashable primitives（`analyze_std_gaps` の hash gap rule に対応）
- ✅ `forge_tasks/vstd_math_gcd.json` — `std/math/gcd.mm` Euclidean-algorithm step atoms（Z3 整数理論で完全検証可能）
- ✅ `forge_tasks/vstd_math_clamp.json` — `std/math/clamp.mm` clamp primitives（`std/contracts.mm` の `clamp` を独立モジュール化）
- ✅ `forge_tasks/vstd_container_deque.json` — `std/container/deque.mm` 両端キュー（`safe_queue.mm` パターン拡張）
- ✅ `forge_tasks/vstd_math_sqrt.json` — `std/math/sqrt.mm` 整数平方根 `isqrt`（`n >= 0` → `result >= 0 && result * result <= n`）
- ✅ `forge_tasks/vstd_container_priority_queue.json` — `std/container/priority_queue.mm` 優先度キュー（`pq_push` / `pq_pop` / `pq_peek`）
- ✅ `forge_tasks/vstd_bitwise.json` — `std/bitwise.mm` ビット演算プリミティブ（and/or/xor/shift）
- ✅ `forge_tasks/vstd_math_log2.json` — `std/math/log2.mm` 整数 `ilog2`（`n > 0` → `result >= 0`）
- ✅ `forge_tasks/vstd_container_set.json` — `std/container/set.mm` 集合操作（`set_contains` / `set_add` / `set_size`）
- ✅ `forge_tasks/vstd_trait_iterable.json` — `std/trait/iterable.mm` Iterable traversal interface（`iterable_len_nonneg` / `iterable_in_bounds` / `iterable_advance`）
- ✅ `forge_tasks/vstd_container_sorted_list.json` — `std/container/sorted_list.mm` ordered sequence helpers（`sorted_insert_position` / `sorted_insert_len` / `sorted_is_ordered_pair`）
- ✅ `forge_tasks/vstd_container_binary_heap.json` — `std/container/binary_heap.mm` heap index / length helpers（`heap_parent` / children / insert / extract）
- ✅ `forge_tasks/vstd_container_stack.json` — `std/container/stack.mm` bounded stack helpers（`stack_push` / `stack_pop` / `stack_peek` / `stack_is_empty`）
- ✅ `forge_tasks/vstd_container_ring_buffer.json` — `std/container/ring_buffer.mm` circular buffer helpers（advance / push / pop / empty / full）
- ✅ `forge_tasks/vstd_math_pow.json` — `std/math/pow.mm` bounded integer power helpers（`pow_small` / `pow_saturating`）
- ✅ `forge_tasks/vstd_math_pow_nat.json` — `std/math/pow_nat.mm` small-domain natural power helpers（`pow2` / `pow_nat`）
- ✅ `forge_tasks/vstd_math_safe_div.json` — `std/math/safe_div.mm` safe division / modulo helpers
- ✅ `forge_tasks/vstd_math_safe_mul.json` — `std/math/safe_mul.mm` safe multiplication helpers
- ✅ `forge_tasks/vstd_crypto_primitives.json` — `std/crypto/primitives.mm` structural crypto predicates（`is_valid_key_len` / `is_valid_nonce_len` / `constant_time_eq_flag` / `digest_len_ok`）を Z3 decidable fragment 内で proof certificate 検証し、Lean escalation 不要として `forge_log.json` に記録
- ✅ `forge_tasks/vstd_core_predicates.json` — `std/core_predicates.mm` core-seeded predicate helpers（`safe_index_or_zero` / `is_nonzero_flag` / `preserve_safe_index`）を明示 body + `deterministic_bodies: true` で LLM credential なしにレンダリングし、Z3 decidable fragment 内で検証
- ✅ `forge_tasks/vstd_core_guards.json` — `std/core_guards.mm` core-seeded defensive guard predicates（`is_in_bounds` / `safe_abs_diff` / `clamp_to_positive` / `both_positive`）を明示 body + `deterministic_bodies: true` で LLM credential なしにレンダリングし、Z3 decidable fragment 内で proof certificate 検証
- ✅ `forge_tasks/vstd_core_ranges.json` — `std/core_ranges.mm` core-seeded interval range predicates（`ranges_disjoint` / `ranges_overlap` / `range_width_nonneg` / `point_before_range`）を明示 body + `deterministic_bodies: true` で LLM credential なしにレンダリングし、線形整数のみ（変数積・除算なし）で Z3 decidable fragment 内 proof certificate 検証（`z3_check_result == "unsat"`、Lean escalation 不要）。`agent/gap_rules.py` の `_STD_GAP_RULES` に対応 gap rule を追加し `analyze-std-gaps` の forge_task_conversion_rate = 1.0 を維持。回帰テストは `tests/test_forge.py::TestForgeOneModule::test_core_ranges_task_uses_deterministic_bodies` と `tests/test_forge_discovery.py::TestCoreRangesGap`
- ✅ Phase 4 high-priority expansion checkpoint（2026-Q2）
  - `vstd_aviation_control.json` — `std/concurrency/aviation.mm` に runway resource hierarchy と `RunwayAllocation` temporal effect を追加
  - `vstd_container_sorted_map.json` — `std/container/sorted_map.mm` の挿入位置 / 長さ更新 / key ordering witness を forge log 上で完了扱いに更新
  - `vstd_math_factorial.json` — `std/math/factorial.mm` の `factorial_step` / `factorial_in_range` を proof certificate 生成フローで確認
  - `vstd_math_fibonacci.json` — 既存 `std/math/fibonacci.mm` を proof certificate 生成フローで確認（live forge は生成品質ゲートで停止）
  - `vstd_string_validator.json` — `std/string/validator.mm` の ASCII numeric / alphanumeric predicates を forge log 上で完了扱いに更新
- ✅ `tests/test_llm_benchmark.py` — LLM モデル別 forge 生成品質ベンチマーク基盤（`@pytest.mark.benchmark` で opt-in、`forge_tasks/vstd_math_abs.json` を基準タスクとする）
  - `LLM_BENCHMARK_MODELS` / `LLM_BENCHMARK_TRIALS` / `LLM_BENCHMARK_OUTPUT` 環境変数でモデル・試行回数・出力先を制御
  - `success_rate` / `avg_code_length` / `avg_time_seconds` を JSON に記録（`generate_code` は retries を返さないため、コード長を品質プロキシとして利用）
  - `.github/workflows/proliferate.yml` の `llm_model` 入力説明に推奨モデルと品質トレードオフを追記
- ✅ `.github/workflows/proliferate.yml` schedule 実行でも LLM benchmark を自動実行し、`docs/BENCHMARK_HISTORY.md` に `success_rate` / `avg_code_length` の時系列を最大50行で蓄積
- ✅ vStd ロードマップ残項目の forge タスク化
  - `python -m agent analyze-std-gaps` が `_STD_GAP_RULES` と `forge_tasks/vstd_*.json` を照合し、重複 std module / 未 task 化 / unmet dependency を JSON report 化
  - `.github/workflows/proliferate.yml` の週次 CI で `vstd_roadmap_gaps.json` と生成候補 task spec を artifact として保存

### P9-E: Demo Integration Forge Tasks

Phase 1 統合デモ用の forge タスク。

- ✅ `forge_tasks/vstd_ownership.json` — Ownership Transfer Protocol (PR #53)
  - `std/ownership.mm` の `propose_transfer` / `accept_transfer` / `cancel_transfer` / `full_transfer` / `propose_and_cancel` を forge ターゲットとする
  - `context_files`: `tests/test_order_state_machine.mm`, `tests/test_modular_verification.mm`, `std/effects.mm`
  - Temporal Effect（stateful effect）を含む初の forge タスク
- ✅ `forge_tasks/vstd_settlement.json` — RTGS Settlement (Phase 2 Demo, Complete)
- ✅ `forge_tasks/vstd_regtech.json` — RegTech Compliance (Phase 3 Demo)

### P9-F: Self-Correction Protocol ✅ Implemented

生成 → 検証 → Loss Vector 反例出力 → LLM 修正 → 再検証の自己修復ループ。

- ✅ `agent.strategies.fix_strategy.SelfCorrectionLoop` — `all_verified` 収束、最大イテレーション停止、`loss_vector` 欠落時の graceful stop
- ✅ `python -m agent self-correct <file.mm>` — P9-F ループ実行 CLI（`--feedback` 指定時は既存 structured-feedback ループも継続利用可）
- ✅ `self_correct` MCP tool — 外部エージェントから P9-F ループを実行
- ✅ `tests/test_self_correction.py` — 収束 / 最大イテレーション / `loss_vector is None` の停止条件を fixture で検証

### P9-G: Ecosystem Integration ✅ Implemented

4 リポジトリを NLAE コンポーネントとして接続する E2E pipeline。

- ✅ `agent/nlae_pipeline.py` — Module A (AV) の生成、Module B (AR) の `verify --emit loss-vector`、P9-F 自己修復、mumei-lean Fidelity Checker を順に実行
- ✅ `run_nlae_pipeline` MCP tool — 外部エージェントから P9-G pipeline を起動
- ✅ `tests/test_nlae_pipeline.py` — E2E pipeline、Loss Vector 受け渡し、Lean fallback 呼び出しを fixture で検証
- ✅ P9-D/E/F/G の完了により P9 NLAE integration milestone を完了

---

## SI-5: Self-Improving Standard Library (Phase 2) — ✅ Implemented

mumei 側の `analyze_std_gaps` MCP ツール（提案を吐き出す）と mumei-agent 側の forge パイプラインを直接接続し、`std/core.mm` の公理型と P8-C の proof-friendly specification guidance を新規 std モジュール生成プロンプトに常時注入することで、std の自己拡張ループをクローズする。

### SI-5 Phase 2-A: Forge Task Auto-Proposal ✅ Implemented

- ✅ `agent/propose.py` — `analyze_std_gaps` の JSON 出力から forge task spec (`forge_tasks/vstd_*.json`) を自動生成
  - `depends_on` → `import "<path>" as <alias>;` プレアンブル自動構築
  - `difficulty` に応じて `max_retries` をスケール（low=3 / medium=5 / high=8）
  - 既存 `forge_discovery._load_task` と互換な spec フォーマット
- ✅ `python -m agent propose` CLI サブコマンド
  - `--gaps-json <path>` — ファイル入力モード
  - `--auto` — mumei MCP サーバーの `analyze_std_gaps` をインプロセス呼び出し
  - `--output-dir` / `--overwrite` / `--dry-run`
  - 各提案の概要（task_id / target / difficulty / depends_on / reason）を stdout に表示
  - `get_spec_guidelines` の decidable fragment guidance と連携し、生成前に線形算術・有限範囲 quantifier・明示的 state transition を優先する spec へ整形
- ✅ `tests/test_propose.py` — 全 fixture 駆動の互換性テスト（difficulty → retries 変換、import プレアンブル生成、`forge_discovery` ラウンドトリップ、CLI エントリポイント）
- ✅ `tests/fixtures/sample_gaps.json` — `analyze_std_gaps` の代表的な JSON 出力を fixture として固定化

### SI-5 Phase 2-B: Core Axiom Injection ✅ Implemented

- ✅ `agent/strategies/generate_strategy.py` — `std/` 配下モジュール生成時に `std/core.mm` の公理（型定義 + atom シグネチャ）をプロンプトへ常時注入
  - `_is_std_module(spec)` — `target_file` / `module_name` / `output_path` / `name` の先頭 `std/` を検出
  - `_summarise_core_axioms(source)` — `type ...;` と `atom ... requires/ensures;` のみを抽出（`body: {...};` はトークン節約のため除去）
  - `_load_core_axiom_context(path)` — `(path, mtime)` でキャッシュし、プロンプトブロック（マークダウン + コードブロック）を返却
  - 単一 atom (`generate_code`) と複数 atom (`generate_multi_atom`) 両方に接続
- ✅ `agent/config.py`
  - `AgentConfig.core_axiom_path` — `CORE_AXIOM_PATH` 環境変数、または隣接 `../mumei/std/core.mm` を自動検出
  - `AgentConfig.inject_core_axioms` — `INJECT_CORE_AXIOMS` 環境変数（default: `true`）
- ✅ `tests/test_core_axiom_injection.py` — std vs non-std の振る舞い、フラグ OFF 時の挙動、環境変数経路、単一/複数 atom の両経路でのプロンプト注入を検証

### SI-5 Phase 2-C: Self-Healing + Forge 統合ループ ✅ Implemented

- ✅ `agent/proliferate.py` — 自律増殖ループ: 欠落発見 → spec 生成 → コード鍛造 → 既存 std 影響検査 → 修復 → PR
  - `analyze_gaps(std_dir)` — `mcp_server.py` の `analyze_std_gaps` と同等のロジックをローカル実装（MCP 起動不要）
    - 依存グラフ、trusted atom、TODO/FIXME、提案リストを返す
    - 提案は difficulty + 未充足依存数でランキングし先頭 3 件に priority を付与
  - `generate_specs_from_gaps(gaps, max_count)` — `propose.build_spec_from_proposal` を再利用して forge 互換 spec を生成
  - `check_blast_radius(mumei_client, repo_dir, new_file_path, code)` — 新規 `.mm` を `std/` に仮配置 → 既存 `std/*.mm` を全検証 → 仮ファイルを自動除去（例外時も cleanup）
    - ✅ 深層レイヤー（cross-file dependencies）: token-level import scan が複数行・複数宣言を検出し、`agent/dependency_invalidation.py` が compiler と同じ importer-relative → std fallback の順で import を解決して暗黙の `std/prelude.mm` 依存 edge を加える。解決不能・malformed import はファイルとその推移的 dependents を fail-closed で `undetermined` に分類する。`mumei.std-dependency-invalidation/v1` 記述子には symlink / path alias を統合した依存関係を含め、`check_blast_radius` は各 broken_files エントリに `dependency_relation`（`re_derive` / `undetermined` / `unaffected`）を付記し、各 per-spec/per-member 結果および `summary.json` にも `dependency_invalidation` を保持する。検出のみで再検証・契約差分・シンボル解決・サイクル解析・外部 std path 解決は `checks_not_performed` に列挙（C07 stale_dependents と同じ「検出≠再計算」方針）。
    - ✅ 依存チェック継承レイヤー: `mumei.std-dependency-checks/v1` は依存 closure（暗黙 prelude と real-path alias を含む）をたどり、report が未回収の `checks_not_performed` を依存キー付きで各 dependent record に継承する。report 欠落は `dependency_verification`、closure 内の unresolved import は `dependency_resolution` として fail-closed に追加し、出力 record はそのまま recovery-eval に渡せる。再検証・evidence binding・symbol resolution・external std path resolution は `checks_not_performed` に残す。
  - `attempt_heal(client, model, broken_info, mumei_client, max_retries=3)` — 既存 `fix_strategy.get_fix` を再利用し、壊れた既存ファイルを自動修復
  - `proliferate(mumei_repo_dir, max_proposals=3, dry_run=False)` — 全体オーケストレーター
    - 各提案を独立処理（1 件の失敗が他をブロックしない）
    - blast radius で壊れたファイルが生じた場合、rollback or heal を自動選択
    - ループの前後で `measure_health` を呼び出し、健全度の delta をログ出力
- ✅ `python -m agent proliferate` CLI サブコマンド
  - `--mumei-repo <path>` — mumei ローカルクローンへの絶対/相対パス
  - `--max-proposals N` — 一度に処理する提案数（default: 3）
  - `--mumei-bin <path>` — mumei バイナリのオーバーライド
  - `--dry-run` — git/PR 操作と生成ファイルの永続化をスキップ
  - `--enable-lean-fallback` — `MUMEI_LEAN_REPO` の mumei-lean bridge 経由で Z3 `unknown` atom の Lean 4 証明を追加試行
- ✅ `tests/test_proliferate.py` — 26 ケース
  - `analyze_gaps` の依存グラフ、trusted atom、TODO 検出、ランキング
  - `generate_specs_from_gaps` の `max_count` リスペクト + forge 互換性
  - `check_blast_radius` の broken_files 報告、例外時 cleanup
  - `tests/test_dependency_invalidation.py` — 45 ケース: token-level import scan、compiler-mirrored resolution、symlink aliases、暗黙 prelude edge、unresolved / unreadable import の fail-closed 分類、blast-radius join（`dependency_relation` 分類 + 記述子同封）
  - `tests/test_dependency_checks.py` — 依存 closure の未回収チェック継承、recovery report、alias / prelude / cycle、fail-closed marker と recovery-eval 接続
  - `attempt_heal` の already-verified ショートサーキット、固定点検出、fix 適用後成功
  - `proliferate` の dry_run end-to-end（`generate_code` / `MumeiClient` をモック）
  - Lean fallback CLI フラグ伝搬と `summary.json` 内 `lean_fallback` 監査フィールドの保持を検証

### SI-5 Phase 3-B: Scheduled Autonomous Runs ✅ Implemented

週次の GitHub Actions で「欠落発見 → spec 生成 → コード鍛造 → 検証 → PR」を人間の介入なしで回し続ける定常ループ。`mumei-lang/mumei` 側の `verify-std.yml` と組み合わせて、自動生成 PR のマージ前に std 全体を再検証する安全柵も追加。

- ✅ `.github/workflows/proliferate.yml` — SI-5 Autonomous Proliferation workflow
  - `cron: '0 0 * * 1'`（毎週月曜 00:00 UTC = JST 09:00）+ `workflow_dispatch` による手動トリガー
  - `workflow_dispatch` 入力: `max_proposals`（default: 3）、`dry_run`（default: false）
  - `schedule` 起動時と `workflow_dispatch` のデフォルトは実 PR 作成モード。dry run が必要な場合だけ `dry_run=true` を明示する
  - mumei-agent / mumei / mumei-lean を checkout → mumei コンパイラを `cargo build --release` → `PATH` に追加
  - Lean toolchain を best-effort で導入し、`lean --version` / `lake --version` を診断出力。`python -m agent proliferate` は Lean fallback がデフォルト有効のため、`MUMEI_LEAN_REPO=${{ github.workspace }}/mumei-lean` 経由で Z3 `unknown` atom の Lean 4 証明を CI 常時試行（Lean/lake 不在時は `lean_unavailable` / `lake_missing` として graceful degrade）
  - `python -m agent health` で pre/post-flight のヘルス JSON を取得
  - `python -m agent proliferate --mumei-repo ../mumei --output-json /tmp/proliferate/summary.json`（Lean fallback は default-on、ローカルデバッグ時のみ `--disable-lean-fallback` で無効化）
  - `summary.json` に`lean_fallback_enabled`、トップレベルの`lean_fallback_attempted` / `lean_fallback_proved` / `lean_fallback_failed` / `lean_fallback_success_rate`、および各`details[].lean_fallback`を必ず出力し、Z3 `unknown` atom があるrun で`details[].lean_fallback.proved > 0`と Lean fallback success rate 70%以上を示す
  - 生成物: `pre_health.json` / `post_health.json` / `proliferate.log` / `summary.json` を `proliferate-logs` artifact として保存
  - **ハイブリッド LLM プロファイル**（`workflow_dispatch` 入力 `llm_profile` / `llm_model` で切替。cron ではデフォルト `ollama-local` + `qwen3.5:4b` を使用し外部依存ゼロで動作）:
    - `ollama-local`（default）: runner 内で `ollama serve` を起動 → `ollama pull ${llm_model}` → `LLM_BASE_URL=http://localhost:11434/v1` に接続。`~/.ollama/models` を `actions/cache@v4` で `llm_model` 毎にキャッシュ。既定モデルは `qwen3.5:4b`、スモークテストなら軽量な `qwen3.5:0.8b`、品質優先なら `qwen2.5-coder:7b`、予備枠として 1bit 量子化系（例: `bonsai-1bit-qwen`）を `llm_model` 入力で指定可能
    - `remote`: 任意の OpenAI 互換エンドポイント（DashScope / vLLM / tailscale 経由の自宅 Ollama / OpenAI）を secrets 経由で利用。優先順: `LLM_API_KEY` → legacy `OPENAI_API_KEY`。`LLM_BASE_URL` / `LLM_MODEL` は optional、後者は未設定なら `llm_model` 入力で上書き
  - 必要なシークレット（操作者が手動で設定）:
    - `MUMEI_REPO_TOKEN`（必須） — mumei-lang/mumei への cross-repo write / PR 作成権限を持つ PAT or GitHub App token
    - `LLM_API_KEY`（`llm_profile=remote` 時に必須） — OpenAI 互換エンドポイントの API key
    - `LLM_BASE_URL`（`remote` 時 optional） — 非 OpenAI エンドポイント URL
    - `LLM_MODEL`（`remote` 時 optional） — `llm_model` 入力より優先
    - `OPENAI_API_KEY`（optional） — `LLM_API_KEY` 未設定時の後方互換 fallback。`agent/config.py` の `LLM_API_KEY` → `OPENAI_API_KEY` fallback と整合
- ✅ `agent/proliferate.py` の CI 対応強化
  - `[PROLIFERATE] Step N/4: ...` 形式のステップログで CI 出力を人間が追跡しやすく
  - `_log_step()` / `_log_info()` ヘルパーで一貫したプレフィックス付きログを出力
  - `--output-json <path>` オプションで構造化サマリを書き出し（`timestamp` / `dry_run` / `pre_health` / `post_health` / `proposals_processed` / `proposals_succeeded` / `proposals_failed` / `lean_fallback_*` metrics / `details[]`）
  - `agent/lean_bridge.py` は `lake_missing` / `partial_translation` / `timeout` / `bridge_failed` を `error_code` + `diagnostics[]` として返し、fallback 不能時も `summary.json` に失敗 atom 数を残す
  - `_jsonify_result()` で巨大な生成コード本体を `code_length` に圧縮して JSON artifact サイズを抑制
  - `_build_pr_body_extra()` で PR description を構築: 提案（target / reason / difficulty / depends_on / priority）+ 健全度 delta + 検証サマリ
  - `publish()` に `pr_title_prefix` / `pr_body_extra` を追加し、PR タイトルに `[SI-5 Autonomous Proliferation]` を付与
- ✅ Lean fallback 運用ドキュメント
  - `docs/LEAN_FALLBACK_TROUBLESHOOTING.md` — `lean_unavailable` / `lake_missing` / `partial_translation` / `timeout` の診断と復旧手順
  - `docs/CI_WORKFLOWS.md` — proliferate workflow の Lean toolchain verification、default-on fallback、metrics gate を説明
- ✅ `mumei-lang/mumei` `.github/workflows/verify-std.yml` — std/ 変更 PR に対する自動検証ゲート（cross-repo 安全柵）

### 検証手順
1. mumei-lang/mumei-agent の Settings → Secrets and variables → Actions で `MUMEI_REPO_TOKEN` を登録する（必須）。`remote` プロファイルを使いたい場合のみ `LLM_API_KEY`（+ 必要に応じて `LLM_BASE_URL` / `LLM_MODEL`）も登録する。`ollama-local` プロファイルでは追加 secret は不要。
2. dry run が必要な検証時のみ Actions タブから "SI-5 Autonomous Proliferation" を `workflow_dispatch` + `llm_profile=ollama-local` + `dry_run=true` で起動し、`proliferate-logs` artifact の `summary.json` / `proliferate.log` を確認する（runner 内で ollama 起動 → qwen3.5:4b を pull する 1 回目は数分かかる、2 回目以降はキャッシュが効く）。
3. 通常運用では `dry_run` のデフォルト `false` を使い、生成される PR のタイトル・description・health delta を確認する。
4. 最後に週次 cron（月曜 00:00 UTC = JST 09:00）の自動起動を待つ。cron は `ollama-local` + 実 PR 作成モードで起動し、health regression が出た場合は artifact 保存後にジョブを失敗させる。

### 恒常運用の推奨設定（PR 4）

- **モデル選択**: cron でのデフォルトは `qwen3.5:4b`（`LLM_MODEL_INPUT` のデフォルト値）。`qwen3.5:0.8b` は CI のスモークテスト用と割り切り、品質優先のラン（PR を本当に開くラン）では `4b` 以上を選ぶ。`qwen2.5-coder:7b` は精度が最も高いが ollama-local では runner キャッシュ容量を圧迫する点に注意。
- **max_proposals**: デフォルトの `3` を維持。1 ラン = 最大 3 PR を上限とすることで、レビューキューが詰まらないバランスをとる。スパイク的な大量提案が必要な場合のみ `workflow_dispatch` で個別に上書きする。
- **dry_run デフォルト**: `workflow_dispatch` の `dry_run` default は `false`。schedule 実行で実 PR 作成が検証済みになったため、手動実行も production mode を既定にし、パイプライン検証時だけ明示的に `dry_run=true` を指定する。
- **健全度ゲート**: `Compare pre/post health` ステップが post-flight `health_score` < pre-flight - 0.001 のときに `::warning` アノテーションを出し、`health_regression=true` を後続ステップへ渡す。`Upload proliferate artifacts` の後に `Fail on health regression` が実行されるため、PR が作成済みでも CI を赤にして degraded PR のマージを防ぐ。
- **summary.json の `health_delta`**: `agent.proliferate._write_output_json()` が pre/post の `health_score` 差分を `health_delta` として出力する。`Compare pre/post health` はこの値も読み取り、負値なら `::warning` を出して health regression と同じ失敗ゲートへ接続する。

---

### SI-5 Phase 3-A: Proof Health Metrics ✅ Implemented

- ✅ `agent/std_health.py` — `std/` 全体の証明健全度を定量測定
  - `measure_health(mumei_client, std_dir)` — 各 `.mm` を `mumei verify` で検証 + atom/trusted/TODO を集計
    - 返却フィールド: `total_files` / `verified_files` / `failed_files` / `total_atoms` / `verified_atoms` / `trusted_atoms` / `health_score` / `todo_count` / `details[]`
  - `compute_health_score(total, verified, trusted, todo)` — 0.0〜1.0 クランプされたスコア
    - base = `(verified_atoms - trusted_atoms) / total_atoms`
    - TODO ペナルティは 1 件あたり 0.01、累積上限 0.2
    - trusted atom は「信仰による証明」として差し引く設計
  - `_format_table(report)` — 人間向けテーブルレンダラー
- ✅ `python -m agent health` CLI サブコマンド
  - `--mumei-repo <path>` — 対象 mumei リポジトリ
  - `--format json|table` — 出力形式（default: json）
  - 失敗ファイルが 1 つでもあれば exit code 2（CI ゲート用）
- ✅ `proliferate.py` からの統合 — ループ前後で `measure_health` を呼び出し、delta をログ表示
- ✅ `tests/test_std_health.py` — 13 ケース
  - `compute_health_score` のエッジケース（0 atoms / 全 trusted / TODO キャップ / クランプ）
  - `measure_health` の missing dir、empty、all-verified、trusted 混在、mixed pass/fail、TODO カウント、details 生成
  - CLI パーサーと table フォーマッター

### 関連 (mumei 側)
- [`mcp_server.py`](https://github.com/mumei-lang/mumei/blob/develop/mcp_server.py) の `analyze_std_gaps` — Phase 2-A 入力源 / Phase 2-C ローカル実装の参照元
- [`std/core.mm`](https://github.com/mumei-lang/mumei/blob/develop/std/core.mm) — Phase 2-B 注入源
- [`docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) の SI-5 セクションと連携

### タスク spec フォーマット
`forge_tasks/README.md` を参照。主なフィールド:
- `task_id` — 完了重複排除の識別子
- `target_file` — mumei リポジトリ root 相対パス（例: `std/contracts.mm`）
- `mode` — `append` / `create` / `replace`
- `atoms` — 1 つ以上の atom spec（`reference_patterns` で既存 atom を style context として指定可能）
- `auto_commit` — 成功時に git commit を自動実行するか

### 関連 (mumei 側)
- [`docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) の vStd セクション (vStd-1〜4, vStd-MCP) と連携

---

## 推奨実行順序

```
P1-C → P1-B → P1-A → P3-B → P6-A/B/C → SI-1 (Zero-Human Challenge) → SI-3 (Autonomous Delivery Flow) → P9 (Forge Mode)
                                  ✅ All Complete        ✅ Complete              ✅ Complete                🚧 In Progress
```

---

## P10: MCP Integration Strengthening ✅Implemented

mumei-agent と mumei MCP server の双方向 MCP 統合を強化。外部 MCP クライアント
（Claude Code / Devin / Codex 等）からも forge / heal / health / propose を直接
呼び出せるようになり、内部の検証パイプラインも opt-in で MCP server の richer
feedback（`semantic_feedback` / `machine_readable` / `counter_example` /
`effect_violation`）を消費できる。

- ✅`agent/mcp_server.py` — `FastMCP("Mumei-Agent")` を起動し以下のツールを公開
  - `forge_task(task_json, mumei_repo, dry_run=true)` — `MumeiForge.forge_one`
    の MCP ラッパ
  - `heal_file(source_code, error_report)` — `agent.strategies.fix_strategy.get_fix`
    によるセルフヒール
  - `measure_std_health(mumei_repo)` — `agent.std_health.measure_health` を委譲
  - `propose_forge_tasks(mumei_repo, max_proposals)` — `analyze_gaps` →
    `generate_specs_from_gaps` を MCP 経由で実行
  - `list_forge_log(log_path)` — `forge_log.json` の読み出し
  - `get_agent_status()` — LLM provider / mumei binary / 利用可能サブコマンド一覧
- ✅`agent/__main__.py` に `mcp-server` サブコマンドを登録
  （`python -m agent mcp-server`）
- ✅`pyproject.toml` の optional-dependencies に `mcp[cli]>=1.0` を追加
- ✅`pyproject.toml` の `[project.scripts]` に `mumei-agent-mcp` エントリポイントを追加

- ✅`agent/mcp_client.py` — `MumeiMCPClient`（drop-in `MumeiClient` 互換）
  - `validate_logic` / `analyze_gaps` / `list_catalog` / `get_effects` /
    `visualize_graph` を mumei MCP server に委譲
  - 自動トランスポート選択: in-process（`PYTHONPATH` に mumei が乗っていれば直接
    `import mcp_server`）/ stdio subprocess（`MUMEI_MCP_COMMAND` 設定時）
  - `verify(source_path)` シムが `MumeiClient.verify` と同じシグネチャで
    `validate_logic` を呼び richer な `report` を返す
  - 失敗時は `MumeiClient` サブプロセス呼び出しに自動フォールバック
- ✅`USE_MCP_CLIENT` 環境変数 — `agent.mumei_client.create_mumei_client` ファクトリ経由で
  forge / heal / proliferate が `MumeiClient` か `MumeiMCPClient` かを切り替え

- ✅`agent/gap_rules.py` — `_STD_GAP_RULES` / `_scan_std_imports` /
  `_collect_trusted_atoms` / `_collect_todo_comments` / `_evaluate_rule` /
  `analyze_gaps_local` をオフライン用フォールバックとして分離
- ✅`agent/proliferate.py` — `_STD_GAP_RULES` 等を `agent.gap_rules` から再エクスポートし
  in-file 重複を排除
- ✅`PREFER_MCP_GAPS` 環境変数 — `true` のとき `proliferate.analyze_gaps` が mumei
  リポの `mcp_server.analyze_std_gaps` に委譲（`_load_gaps_from_mcp` 経由）。
  `SystemExit`（mumei 不在）の場合は静かにローカル分析にフォールバック
- ✅`.github/workflows/proliferate.yml` — `PREFER_MCP_GAPS=true` と
  `PYTHONPATH=${{ github.workspace }}/mumei` を設定し CI 上で常に mumei リポの
  ルールセットを使用

- ✅`tests/test_mcp_server.py` — 全 6 ツールを直接呼び出してアサーション
  （`MumeiForge` / `AgentConfig` / `measure_health` / `get_fix` をモック）
- ✅`tests/test_mcp_client.py` — `MumeiMCPClient` のモード判定 / fallback /
  `verify` シム / `create_mumei_client` ファクトリ
- ✅`tests/test_gap_rules.py` — `analyze_gaps_local` の純関数挙動 /
  `PREFER_MCP_GAPS` ON-OFF / fake `mcp_server` モジュールでのデリゲーション

### Cross-repo: mumei-side MCP tools (P10-D) ✅ Implemented

mumei-lang/mumei 側 `mcp_server.py` に以下が実装済み。external agents が
mumei-agent のインストールなしに proof health / proof certificate /
documentation を取得できる:

- ✅ `measure_std_health()` — std/ 全体に対する health metric を JSON で返却
  （`mumei/mcp_server.py` L1333-L1447）
- ✅ `get_proof_certificate(module_path)` — `std/certs/` または proof bundle から
  proof certificate JSON を返却
  （`mumei/mcp_server.py` L1450-L1526）
- ✅ `generate_doc(source_code, format="json")` — `mumei doc --format json` を起動し
  構造化ドキュメントを返却（`mumei/mcp_server.py` L1530-L1643）
- ✅ Claude Code CLI 統合 — project scope の `.mcp.json` と `.claude/CLAUDE.md`
  を mumei / mumei-agent の両リポジトリに配置し、Claude Code から
  `mumei-forge` / `mumei-agent` MCP server を自動検出できるようにした。

---


## P12: NLAE Integration (Experimental) ✅ Implemented

Anthropic Natural Language Autoencoders (NLAE) の概念を mumei-agent に統合し、
潜在空間でのデバッグ、高密度プロパティ生成、エージェント間通信標準化を
オプトイン機能として提供する。

### P12-A: Latent-space Debugging ✅ Implemented

- ✅ `LatentEncoder` / `LatentDecoder` の実装
- ✅ `LatentDebugStrategy` の実装
- ✅ `fix_strategy.py` への Phase 0 統合
- ✅ フォールバック動作とユニットテスト

### P12-B: Dense Property Generation ✅ Implemented

- ✅ `DensePropertyGenerator` の実装
- ✅ `generate_strategy.py` への opt-in 統合
- ✅ 高密度 `requires` / `ensures` 生成テスト

### P12-C: Latent Protocol for Agent Communication ✅ Implemented

- ✅ `LatentProtocol` の実装
- ✅ `mcp_server.py` への `send_latent_message` 追加
- ✅ MCP feature flag とプロトコルテスト

### P12-D: Multi-Agent Verification Workflow ✅ Implemented (paper Future Work #9)

P9-G の単一 pipeline（generate → verify → self-correct → Lean fidelity）と
`LatentProtocol` の 1 対 1 メッセージングに留まっていた範囲を、1 つの spec を
複数の検証エージェントで分担する opt-in ワークフローへ拡張する。

- ✅ `agent/nlae_multi_agent.py` を追加。`generator`（生成 + verify）/
  `counterexample`（Loss Vector 駆動の self-correction、`NLAE_MULTI_AGENT_MAX_ROUNDS`
  ラウンドまで）/ `lean_escalation`（`mumei-lean` fidelity check）の 3 role を
  固定し、`MultiAgentOrchestrator` が決定的にオーケストレーションする。
- ✅ role 間の受け渡しは既存の `LatentProtocol.encode_message` envelope に載せる。
  `lp-v2` versioned envelope / `blake2b-128` semantic hash / `hmac-sha256`
  authentication tag / AES-256-GCM（`LATENT_PROTOCOL_KEY`）/ redacted audit log
  （`LATENT_PROTOCOL_AUDIT_LOG`）をそのまま再利用し、新規 verdict 分類や別名
  alias は追加しない。verdict は従来どおり verifier と Lean bridge のみが決める。
- ✅ `NLAEResult.multi_agent` に `rounds` / `converged` / `converged_by` /
  `audit_events` と handoff 毎の `from_role` / `to_role` / `round` /
  `semantic_hash` / `protocol_version` / `transfer_bytes` / `authenticated` を
  記録。同一 spec の再実行で semantic hash 列が一致する（決定性）。`converged` は
  `NLAEResult.verified`（Z3 か Lean のいずれかで discharge）と同義であり、
  `converged_by`（`z3` / `lean` / `null`）でどちらが閉じたかを判別できる。
  `lean_escalation` handoff の body には検証済みソースの digest を含めるため、
  spec が異なれば semantic hash も異なる。
- ✅ opt-in フラグが優先: `multi_agent=False` を明示した場合は orchestrator を
  注入しても単一 pipeline のまま。orchestrator による opt-in はフラグ未指定
  （`None`）のときだけ有効。
- ✅ OTel は 1 本の分散トレースを維持: `mumei.nlae.pipeline` root の下に
  `mumei.nlae.multi_agent`、その下に `mumei.nlae.agent.<role>` と
  `mumei.nlae.handoff`。handoff envelope は `trace_id` を volatile field として
  運ぶため semantic hash はトレース間で比較可能なまま。
- ✅ デフォルト無効（`ENABLE_NLAE_MULTI_AGENT`、MCP は `run_nlae_pipeline`
  の `multi_agent` 引数）。ワークフロー内の例外は既存の単一 pipeline へ graceful
  fallback し、`multi_agent.status = "fallback"` と `fallback_reason` を記録する。
- ✅ 回帰ゲート: `uv run pytest tests/test_nlae_pipeline.py tests/test_latent_protocol.py -q`
  （収束・決定性・fallback・trace 接続・デフォルト無効を fixture で固定）。

### Configuration

- すべての機能はデフォルト無効
- `ENABLE_LATENT_DEBUG`, `ENABLE_DENSE_PROPERTIES`, `ENABLE_LATENT_PROTOCOL`,
  `ENABLE_NLAE_MULTI_AGENT`（ラウンド予算は `NLAE_MULTI_AGENT_MAX_ROUNDS`, 既定 `2`）

### References

- Anthropic NLAE research: https://www.anthropic.com/research/natural-language-autoencoders
- Reference implementation: https://github.com/kitft/natural_language_autoencoders
- Implementation guide: `docs/NLAE_GUIDE.md`

---

## P13: Agent Harness Externalization (NLAH-style) ✅ Complete

`mumei-lang/mumei` の Priority 11 roadmap に沿って、mumei-agent の既存
Forge / heal / extract-spec / proliferate / Lean fallback を、コード内の暗黙制御ではなく
外部化された harness policy として扱う。

### P13-A: Agent Harness Specification ✅ Documented

- ✅ `docs/AGENT_HARNESS_SPEC.md` を追加。
- ✅ role、stage、artifact contract、state semantics、verifier gates、failure taxonomy、budget/search policy、intent fidelity、module ablation plan を明文化。
- ✅ 既存 entrypoint (`extract-spec`, `generate`, `heal`, `forge`, `proliferate`, `mcp-server`) と runtime module の責務対応を整理。

### P13-B: Harness telemetry & ablation metrics ✅ Implemented

- ✅ `agent/harness_metrics.py` を追加し、stage/module 単位で `artifact_contract_passed`, `verification_gate`, `handoff_count`, `retry_class`, `intent_fidelity_status` を集計する。
- ✅ P8-G `budget_metrics.py` と統合し、attempts/token/solver-time/spec-drift と同じ summary に出す。
- ✅ `--harness-profile basic|stateful|verifier|self_evolution|lean_fallback|full` を dry-run 可能な flow から導入する。

### P13-C: Harness-aware summaries ✅ Implemented

- ✅ `forge_log.json` と `proliferate --output-json` の details に stage evidence を追加する。
- ✅ Lean fallback、manual review、blast-radius rollback を同じ failure taxonomy で表示する。
- ✅ mumei 側 certificate metadata (`harness_contract`, `intent_fidelity`, `artifact_paths`, `budget_policy_fingerprint`) が利用可能になったら summary から参照する。

---


## P11: Natural Language Specification Extraction

自然言語の要件テキストを forge task spec JSON に変換する Step 0 を追加し、
既存の `generate_code()` / `spec_refinement` / `forge_task` / self-healing loop は変更せずに
「自然言語 → forge task spec JSON → verified .mm」の導線を提供する。

- Entry Point A（新規）: 自然言語テキスト → `agent.spec_extractor.extract_spec()` → forge task spec JSON → 既存パイプライン
- Entry Point B（既存）: forge task spec JSON → 既存パイプライン

### CLI

```bash
python -m agent extract-spec --text "安全な銀行送金機能。残高不足はエラーにする" --output spec.json
python -m agent extract-spec --text-file requirements.md --domain financial --output spec.json --generate --generate-output transfer.mm
```

### MCP

- `extract_spec(natural_language, domain_hint="", generate=false, mumei_repo="")` —
  human-readable requirements を structured forge task spec に抽出し、`generate=true` の場合は
  抽出した spec をそのまま `generate_code()` + `run_refinement_loop()` に接続する。

### 接続設計

- `agent/prompts/spec_extraction.py` — forge task schema、入出力例、`domain_hint`、
  existing std catalog context を含む仕様抽出プロンプト。
- `agent/spec_extractor.py` — LLM 出力 JSON の抽出、forge task schema validation、
  invalid JSON / schema error feedback retry、`extract_and_generate()` の薄い統合。
- `agent/extract_spec.py` — `python -m agent extract-spec` サブコマンド。
- 既存の `generate_code()`、`spec_refinement.run_refinement_loop()`、`forge_task` MCP tool、
  self-healing loop はそのまま再利用し、Step 0 の追加に限定する。

---

## Task 2-C: mumei-lean integration pipeline (opt-in)

mumei-agent の forge / verify サクル、`z3_check_result == "unknown"` の atom が残た合に[mumei-lang/mumei-lean](https://github.com/mumei-lang/mumei-lean)Lean 4 ロフバクド連携、人手の介在なし lean_verified 状態を昇格さるプライ。

### 概

- **オトイン導入** — 既存ローは byte-identical に動作し`--enable-lean-fallback` フグまた `MUMEI_LEAN_REPO` 環境変数を有効化したきの起。
- **subprocess ベの薄連携** — `agent.lean_bridge.run_lean_bridge()` `mumei-lean` リの `scripts/bridge.py` を `python -m scripts.bridge --cert ... --lean-cert-out ...`使形動。Lean toolchain (`lake`) が無ても`bridge.py` が`lake_missing` を伝搬 fallback は best-effort 失敗。
- **non-mutating merge** — `merge_lean_cert_into_proof_cert()` 元の proof certificate を deep-copy 上で`lean_verified` ル上書しない atom はそのま据え置く。bundle 体の `all_verified` `unsat` ま `lean_verified` の atom のみで構成さている合に True に。

### Pipeline 概観

1. `proliferate()` ロプ通常通生 → verify → publish を行
2. `--enable-lean-fallback` が有効 ループ後 `_run_lean_fallback()` を起。
3. 各 `spec_result.publish_result.proof_certificate` を走査 `unknown` atom を取出。
4. Tempfile に proof-cert を書出し`scripts/bridge.py --cert ... --lean-cert-out ...` を呼出。
5. Read the emitted `.lean-cert.json`, merge it into the original proof certificate, replace `spec_result["publish_result"]["proof_certificate"]` with the upgraded certificate, and carry the same promotion through `spec_result["upgraded_cert"]` plus `summary.json.details[].publish_result.proof_certificate_summary.lean_verified_count`.
6. 健康度算出れの工程続。

### 動作

```
export MUMEI_LEAN_REPO=/path/to/mumei-lang/mumei-lean
python -m agent proliferate \
    --mumei-repo /path/to/mumei-lang/mumei \
    --enable-lean-fallback \
    --output-json /tmp/proliferate-summary.json
```

`AgentConfig.mumei_lean_repo` プロパティ`MUMEI_LEAN_REPO` 環境変数か起かに値を取得しないば `None`。`None` の場 `lean_fallback_available()` `False` を返す`_run_lean_fallback()` no-op に。

### 関連ドキメ

- [mumei-lang/mumei-lean README](https://github.com/mumei-lang/mumei-lean/blob/main/README.md) — Lean 側の bridge / ingest_cert / export_cert の仕。
- `agent/lean_bridge.py` — agent 側のルパ層`tests/test_lean_bridge.py` テスを照。

### E2E 検証メモ

- `tests/test_lean_bridge_e2e.py` now verifies the live path `_run_lean_fallback()` → `publish_result.proof_certificate.atoms[].z3_check_result == "lean_verified"` → `summary.json.details[].publish_result.proof_certificate_summary.lean_verified_count`.
- The reference body-semantics obligation is `std/math/abs.mm::abs_saturating`. With Lake available, `scripts/bridge.py --cert ... --lean-cert-out ...` now emits and builds `Generated.Std.Math.Abs.abs_saturating_correct`, exports `lean_verified`, and carries `known_witness_used = false`.
- `tests/test_lean_bridge_e2e.py` no longer skips because the generated theorem path is unavailable: it verifies promotion when Lake is present and uses graceful skip only when the `mumei-lean` checkout or Lake toolchain is unavailable. Stale `translator_version` / `bridge_lemma_hash` output remains unpromoted as `stale_translator`.

---

## Task 2-D: unknown atom の AI 主体 Lean 証明生成 ✅ Implemented（PR #572、2026-09-11）

実装は `agent/lean_ai_proof.py`（`run_ai_proof_repair` / `AiProofGenerator` / `LLMAiProofGenerator`）と
`agent/lean_bridge.py::run_lean_bridge` の `ai_proof_generator` 経路、CLI / 環境変数の
`--enable-lean-ai-proof` / `ENABLE_LEAN_AI_PROOF`、lean-cert / summary の `ai_proof_used` provenance
（`lean_fallback_strategy = "ai_generated_proof"`）で構成される。回帰は `tests/test_lean_ai_proof.py`（LLM モックで
「1 回目失敗 → 修復成功」「上限到達で unknown 残置」「`sorry` 等の `unsound_source` 拒否」「フラグ無効で
既存結果不変」）と `tests/test_lean_bridge.py` / `tests/test_lean_bridge_e2e.py`（既存結果不変）。

**B-4 → mumei-lean B-2 / B-3 接続 ✅（Wave 4、2026-09-13）**: PR #572 時点の実装は mumei-lean checkout 内で
自前に `lake build` を実行しログを解釈（`_build_log_accepts` 系）して `lean_verified` を判定していたが、
現在は mumei-lean 正規経路を信頼境界として再利用する。統一契約は以下:

1. statement は従来どおり `scripts/ingest_cert.py` の再実行でのみ再生成し、LLM には tactic script だけを要求する。
2. `sorry` / `admit` / `axiom` / `unsafe` / `native_decide` / `implemented_by` を含む tactic は bridge 呼び出し前に
   `unsound_source` として拒否する。
3. 残余 atom ごとに `mumei-agent.external_proofs/v1`（`atom` / `tactic_script` / `module_key` /
   `source = "ai_generated_proof"` / `attempts`）を書き出し、`scripts/bridge.py --cert … --lean-cert-out …
   --external-proofs … --failure-report … --summary-json …` を呼ぶ。tactic は mumei-lean B-2 の
   `IngestedAtom.auto_tactic` に注入され、`export_cert.py` の `_translator_contract_current` /
   `_lean_result_contract_current` ゲートを通過した atom だけが `z3_check_result = "lean_verified"` になる。
4. mumei-agent 側は正規 lean-cert の `lean_metadata` を読み、`lean_verified` かつ
   `ai_proof_used = true` / `external_proof.source = "ai_generated_proof"` の provenance がある atom のみ昇格し、
   別途 `#print axioms` 監査（`sorryAx` 拒否、`propext` / `Classical.choice` / `Quot.sound` のみ許容）を維持する。
   失敗 atom は `unknown` のまま残す。
5. 修復フィードバックは B-3 の `mumei-lean-build-failures-v1`（atom 単位の `kind` = `unsolved_goals` /
   `type_mismatch` / `import_error` / `unknown_identifier` / `sorry` / `other_error` + `line` / `message`）を
   次の LLM 試行プロンプトに構造化して渡す。

lean-cert キー（`ai_proof_used` / `ai_proof_attempts` / `lean_fallback_strategy`）、`translator_version` /
`bridge_lemma_hash` は不変。フラグ無効時の出力は byte-identical。回帰は `tests/test_lean_ai_proof.py` の
`FakeBridge` fixture（1 回目失敗 → 修復成功 / 上限到達で unknown 残置 / `sorry` 拒否 / bridge exit 0 でも
昇格なし / import_error・type_mismatch の構造化フィードバック / 監査失敗で拒否）と mumei-lean 側
`tests/test_lean_bridge_e2e.py -k external_proof_matrix`。

**B-7 / R-7 計測（mumei `benchmarks/evaluation/evaluation_suite.json`、2026-09-13）**: `scripts/measure_lean_ai_proof.py`
（AI on/off の proof-cert 生成）と `scripts/measure_repair_convergence.py`（counterexample ベンチ 20 件への
`heal --proof-cert-out`、`self_correction_summary` 付き certificate）をローカル Ollama `qwen2.5-coder:3b`
（OpenAI 互換 `LLM_BASE_URL`）で実行。Lean escalation 候補 6 は AI off / on ともに 6 `lean_verified`（delta +0、
`ai_proof_used` 0、`manual_lemma_reason` 残 0 — 決定的 tactic ladder が AI 段の前に全候補を解いた）、
repair convergence は `SKIP` → `MEASURED` 41.67%（10/24 atom、平均 1.3333 attempts、max 3 retries）。
Wave 4 は完了（2026-09-13: mumei-agent #579 / mumei #558 + papers #6 / mumei-lean #118）。Wave 5（C-2 / R-8、mumei 側 P10-D nlsat 先行）は
実装済み・レビュー中で、B-7 再測定を同一 PR 群で実施（escalation 候補 6 → 6、`lean_verified_delta` 0 不変、AI 段への影響なし）。
C-1（mumei `docs/ROADMAP.md` P30）の群 3 — `while` ループ不変量 3 atom（`svcomp_style/loop_invariant.mm::sum_array` /
`domain_compliance/regtech_exhaustiveness.mm::all_transactions_within_limit` /
`domain_compliance/rtgs_balance_conservation.mm::queue_total_is_nonnegative`）— が B-4 AI 証明生成の対象義務入力
（既存 `lean_fallback_strategy` / `ai_proof_attempts` / `ai_proof_used` で計測、新 alias なし）。
**2026-09-19 実運用化**: `measure_lean_ai_proof.py --force-lean-atom <atom>`（repeatable）で Z3 が `unsat` と
判定した atom を bridge 入力側のみ `unknown` へ降格し AI 証明生成経路へ投入 — 群 3 atom は unsat のため
`extract_unknown_atoms` に載らなかった設計を補完。`run.json` の `force_lean_atoms` / per-file `forced_atoms` /
`lean_verified_forced` が出処、bridge 失敗時は元の Z3 verdict に復帰（`_restore_forced_misses`、回帰なし）。
実 cert 実走行（gpt-4o）で `all_transactions_within_limit` が手動 `--external-proofs` 無しに `lean_verified` 到達
（残 2 atom は OpenAI 429 で停止 → ローカル Ollama `qwen2.5-coder:1.5b` で再実行したところ AI 段まで到達するも
`tactic_failed` / `unsound_source` で未証明 — 小規模モデルの能力限界、forced atom は元の Z3 verdict 復帰を実走行で確認）。

### 実装済み

- **B-0 escalation-bundle v2** — `cegis_loop_helpers.escalate_to_lean` は既存 4 キーに
  追記形で `bundle_schema_version` / `atom`（`requires` / `ensures` / `body` / `body_expr` 等）/
  `counterexamples` / `tried_invariants` を書き出す。`self_healing_repair._try_cegis_repair`
  が `CEGISLoop.history` と `_extract_counterexample` の結果を渡す。
- **B-4 AI 生成 + 修復ループ** — `agent/lean_ai_proof.py::run_ai_proof_repair`。
  `AiProofGenerator` Protocol（`LLMAiProofGenerator` が既定実装、テストはモック）が
  tactic script を生成 → `scripts/bridge.py --external-proofs` 経由で mumei-lean B-2 に注入 →
  B-3 の構造化失敗 JSON を feedback として最大 `LEAN_AI_PROOF_MAX_ATTEMPTS`（既定 3）回修復。
  `sorry` / `admit` / `axiom` / `unsafe` / `native_decide` / `implemented_by` を含む
  ソースは Lake 前に `unsound_source` として拒否。`--enable-lean-ai-proof` /
  `ENABLE_LEAN_AI_PROOF` で opt-in、LLM キー無し / `CI_FIXTURE_MODE` では自動スキップ。
- **B-5 マージ** — `run_lean_bridge(..., ai_proof_generator=...)` が Task 2-C
  （生成モジュール → known witness）の残余 unknown にのみ AI 段を適用し、
  `merge_lean_cert_into_proof_cert` で non-mutating にマージ。`lean_verified_count`
  伝搬は既存経路。lean-cert の `lean_metadata` / `lean_result_metadata` に
  `ai_proof_used = true` / `ai_proof_attempts` / `proof_path` / `build_log_path` を記録
  （`lean_fallback_strategy = "ai_generated_proof"`）。
- **B-6 人手フォールバック** — `human_review.escalate_to_lean` / MCP `escalate_to_lean`
  は残余義務向けの最終手段として `lean_escalation.stage = "human_final_fallback"` と
  `prior_stages` を記録。`docs/LEAN_FALLBACK.md` の `tactic_failed` /
  `partial_translation` Typical action を AI 先行に更新。

以下は設計時の仕様（実装の根拠として保持）。

**cross-repo 位置づけ**: 本タスクは [mumei `docs/CROSS_PROJECT_ROADMAP.md` Priority 25](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) の **Track B** に対応する。mumei-agent 側の担当は B-0（契約合意: escalation bundle 拡張スキーマ / lean-cert の `ai_proof_used` provenance / build 失敗の構造化形式、docs のみ）、B-4（`--enable-lean-ai-proof` と AI 生成 + 修復ループ）、B-5（`merge_lean_cert_into_proof_cert` によるマージと `lean_verified_count` 伝搬）、B-6（`docs/LEAN_FALLBACK.md` error code 表と `human_review.py` / MCP `escalate_to_lean` の再配置）。当初は B-4 / B-5 を mumei-lean 側の受理面 B-2 と構造化フィードバック B-3 の後（Wave 3）に置いていたが、実際には上記のとおり B-4 / B-5 / B-6 が PR #572 で先行完了し、B-2 / B-3 は後続タスクに位置づけ直された。下記「パイプライン設計」の前提タスク（bundle スキーマ拡張）は B-0 に相当し、こちらも PR #572 に含まれる。

Task 2-C の Lean fallback は、`agent/lean_bridge.py` の `run_lean_bridge` /
`agent/lean_bridge_helpers.py` の `extract_unknown_atoms` と known witness fallback
（`_verify_known_witnesses` / `_combine_with_witness_fallback`）、および `agent/proliferate.py`
の `_run_lean_fallback_inner` で構成され、昇格対象は mumei-lean 側の生成モジュール経路と
既知 witness モジュールに限定される。それ以外の unknown atom は unknown のまま保守的に
残し `partial_success` として報告する（`docs/LEAN_FALLBACK.md`）。同ドキュメントの
error code 表では `tactic_failed` / `partial_translation` の Typical action が「手書き
witness / proof strategy の追加・改善」「translator の拡張」とされており、Z3 で解けない
義務の最終解決が人手の証明記述に依存している。

### 目標

P8-C で Lean エスカレーション対象と定めた義務 — 非線形算術・記号的除算 / 剰余・
量化子交替・非有界時相不変量など Z3 が `unknown` を返すもの — について、Lean 送りの
後段で AI（LLM）が Lean 4 の証明（tactic script / witness lemma）を自動生成・自動修復し、
人手の証明記述を「最終手段」へ後退させる導線を追加する。CEGIS の `escalate_to_lean`
（`agent/strategies/cegis_loop_helpers.py`、`tests/test_cegis_loop.py::test_escalate_to_lean_writes_bundle`）
が書き出す escalation-bundle（現状は `source_file` / `loop_line` / `loop_context` /
`reason` のみ）を AI 証明生成の入力として活用する。対象 atom の契約と `_extract_counterexample`
で得た counterexample・試行済み不変量候補は現状 bundle に含まれないため、bundle スキーマの
拡張（または proof certificate 側からの補完）を前提タスクとし、Z3 側で得た反例・不変量候補を
Lean 側の証明ヒントとして再利用する。

### パイプライン設計（opt-in、既存互換）

既存の opt-in 方針（`--enable-lean-fallback` / `MUMEI_LEAN_REPO`）を踏襲し、無効時の
既存挙動を byte-identical に保つ。AI 証明生成はさらに別フラグ（例:
`--enable-lean-ai-proof`）で有効化し、Task 2-C の known witness 経路には影響を与えない。

1. `extract_unknown_atoms` で proof certificate から unknown atom を抽出する。
2. AI が atom の `requires` / `ensures` / body と escalation-bundle を入力に Lean theorem と
   proof（tactic script または witness lemma）を生成する。
3. `scripts/bridge.py` 相当で生成モジュールを Lake ビルドし機械的に検証する。
4. 失敗時は Lean のエラー（unsolved goals、型不一致、`import_error` 等）を feedback として
   AI に返し、上限回数まで反復修復する。多エージェント構成は `agent/nlae_pipeline.py`
   の generator → counterexample → Lean escalation の handoff 構造（`LeanBridgeRunner` /
   `ConfiguredLeanBridgeRunner`）を参考にする。
5. ビルド成功で当該 atom の `z3_check_result` を `"lean_verified"` に昇格し、
   `merge_lean_cert_into_proof_cert` で元の proof certificate へ non-mutating にマージする。
   `summary.json.details[].publish_result.proof_certificate_summary.lean_verified_count`
   への伝搬は Task 2-C と同一経路を使う。

### 健全性ガード（最重要）

- `lean_verified` へ昇格できるのは、AI が生成した証明のうち Lean / Lake で機械的にチェック
  され成功したものだけとする。AI 出力自体を信頼して昇格することは行わない。
- ビルド未成功・タクティク未解決のものは従来どおり unknown / `unverifiable` のまま残し、
  `partial_success` として報告する保守設計を維持する。既存の `stale_translator` /
  `bridge_lemma_hash` 検査もそのまま適用する。
- 生成した Lean ソースと検証ログは証跡として保存し、`known_witness_used` と対になる
  `ai_proof_used` 等の provenance を lean-cert に残して、人手 witness / 生成モジュール /
  AI 生成のいずれで昇格したかを追跡可能にする。

### 人手フォールバックの位置づけ

- AI 生成・自動修復で解けなかった義務のみを人手レビュー / 手書き witness に回す
  「最終手段」とし、`agent/human_review.py` の `escalate_to_lean` / MCP `escalate_to_lean`
  はその残余に対して起動する。
- `docs/LEAN_FALLBACK.md` の error code 表（特に `tactic_failed` / `partial_translation`
  の Typical action）を、AI 証明生成を先に試みる前提へ更新する。

### 決定論・fixture

- no-LLM / `CI_FIXTURE_MODE` 経路では AI 証明生成をスキップし、既存挙動（known witness
  のみ）に退避する。`tests/test_lean_bridge.py` / `tests/test_lean_bridge_e2e.py` の既存
  結果は不変とし、AI 経路は LLM をモックした fixture で別テストとして回帰を固定する。

---

## 統合デモ戦略

mumei-demo リポジトリとの連携。詳細は [mumei-lang/mumei の docs/CROSS_PROJECT_ROADMAP.md](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) の「統合デモ戦略」セクションを参照。

### デモにおける mumei-agent の役割

1. **バグ入りコード生成**: `generate_code()` で LLM にコードを書かせる（意図的にバグを含む）
2. **検証ループの可視化**: Z3 失敗 → LLM 修正 → 再検証の思考プロセスを構造化ログとして出力
3. **Lean fallback**: `--enable-lean-fallback` で Z3 unknown atom を mumei-lean に委譲

### 残タスク

| 項目 | 状態 | 備考 |
|---|---|---|
| vstd_ownership.json | ✅ Complete (PR #53) | Phase 1 Demo |
| 検証ループの Step-by-step 思考プロセスログ | ✅ Implemented | `summary.json` の拡張。各ステップの Z3 結果・LLM 修正・再検証を構造化 |
| vstd_settlement.json | ✅ Complete | Phase 2 Demo (RTGS) |
| vstd_regtech.json | ✅ Complete | Phase 3 Demo (RegTech) |

---

## P15: OpenTelemetry Observability 導入（完了）

**ステータス: 完了** — Phase 1〜6 の Python 側全実装 + Rust コンパイラ側 `mumei verify` / Z3 span 連携の分散トレース接続が実装済み。`TRACEPARENT` 環境変数による W3C Trace Context 伝播により、外部 MCP client → mumei-agent → mumei verify subprocess 内の Z3 実行まで 1 本の分散トレースで貫通する。

Phase 1（`agent/telemetry.py` の NoOp フォールバック基盤 + LLM 呼び出しの span 計装 + `gen_ai.usage.total_tokens` counter 接続 + `otel` optional-dependency）および Phase 2（`MumeiClient` / `MumeiMCPClient` の Z3 verify span 計装 + `mumei.verify.duration` histogram）および Phase 3（各ループの root span 化 + `ThoughtProcess` の span イベント写像）および Phase 4（MCP サーバーのツール入口 span 化 + `extract_trace_context` による W3C Trace Context 受信）および Phase 5（既存 `Metrics` / `HarnessMetrics` / `run_lean_bridge` の OTel Metrics 並行チャネル接続）および Phase 6 の Python 側 3 ファイル（`proliferate` の root/step/proposal/parallel-forge span、`nlae_pipeline` の分散トレース + `NLAEResult.trace_id`、`audit` の file/directory/source span）が実装済み。Phase 6 の Rust コンパイラ連携（`mumei-lang/mumei` への `tracing-opentelemetry` 導入、`otel` feature / `OTEL_ENABLED` / `TRACEPARENT` 受信）は **実装済み（mumei PR #398）**。`mumei verify` を `--features otel` ビルド + `TRACEPARENT` 付きで呼ぶと Rust 側 `mumei.verify.cli` → `mumei.z3.solve` span が Python 側 trace と同一 trace ID で貫通する。運用層（リファレンス OTLP スタック・Grafana ダッシュボード・運用ドキュメント）は [`docs/OBSERVABILITY.md`](OBSERVABILITY.md) を参照。

### 目的

[OpenTelemetry ブログ「AI エージェント可観測性」](https://opentelemetry.io/ja/blog/2025/ai-agent-observability/) の観点に沿って、mumei-agent の LLM 呼び出し・ツール呼び出し・エージェントループを span/trace で串刺しにし、トークン・コスト・レイテンシを OTel Metrics として可視化可能にする。

### 現状

mumei-agent リポジトリ全体で OpenTelemetry はまだ導入されていない。各所が独自の JSON メトリクス（`agent/metrics.py` の `Metrics`、`agent/harness_metrics.py` の `HarnessMetrics`）、`print`/`logging` に留まっており、分散トレースやメトリクスバックエンドへのエクスポートは行っていない。`pyproject.toml` に `opentelemetry-*` パッケージは未登録。

クロスプロジェクトロードマップ（[`mumei-lang/mumei/docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md)）の P11-C「Harness telemetry & ablation metrics」は mumei-agent 側では P13-B として完了済みだが、これは JSON ベースのハーネス内テレメトリであり OTel バックエンドへの接続は含まれていない。OTel 導入は P13-B の成果を OTel Metrics/Traces に接続する後続ステップとなる。

### 推奨導入順

1. **Phase 1**: `llm_provider.py` の LLM span + トークン/コスト metrics
2. **Phase 2**: `mumei_client.py` の verify span（Z3 サブプロセス計装）
3. **Phase 3**: 各ループの root span 化 + `ThoughtProcess` の span イベント写像
4. **Phase 4**: MCP サーバーのツール計装とコンテキスト伝播

### 依存追加（予定）

`pyproject.toml` の `[project.optional-dependencies]` に以下を追加する想定（opt-in）:

```
otel = [
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
    "opentelemetry-exporter-otlp>=1.20",
    "opentelemetry-instrumentation-openai>=0.1",  # 利用可能な場合
]
```

既存の `mcp` optional と同様にデフォルト無効で導入し、OTel バックエンドが設定されていない場合は `NoOp` tracer/meter にフォールバックして既存動作への影響をゼロにする。

---

### P15-1: LLM 呼び出しの計装（最優先・単一チョークポイント）

**ステータス: 実装済み（Phase 1）**

LLM 呼び出しはエージェントのコスト・レイテンシの大部分を占める単一チョークポイントであり、最も費用対効果の高い計装対象。

実装内容:

- `agent/telemetry.py` — `OTEL_ENABLED`（デフォルト `false`）と `OTEL_EXPORTER_OTLP_ENDPOINT` を読み、OTel SDK 未インストール/無効時は NoOp tracer/meter を返す `get_tracer()` / `get_meter()`。`opentelemetry` が import できない環境でも ImportError を握りつぶして NoOp にフォールバックする。
- `OpenAILLMProvider.complete` を `llm.complete` span でラップし、`gen_ai.system=openai-compatible` / `gen_ai.request.model` / `server.address`（`config.base_url`）/ `gen_ai.usage.total_tokens` を属性化。
- `McpSamplingLLMProvider.complete` を `mcp_sampling.complete` span 化し、`_complete_via_sampling` の `metadata` に `traceparent`（W3C Trace Context）を注入。
- `fix_strategy_helpers.response_token_count()` が抽出する `usage.total_tokens` を OTel の `gen_ai.usage.total_tokens` counter へ並行報告（`Metrics.record_tokens` / `Metrics.to_dict()` の出力形式には一切影響しない）。
- `pyproject.toml` に opt-in の `otel` extra を追加。

Phase 1 の残り — ✅ **完了**: 直接 `client.chat.completions.create` 呼び出し 8 箇所の個別計装（`spec_refinement`, `multi_stage_strategy`, `multi_stage_strategy_helpers`, `cegis_loop`, `spec_extractor`, `code_to_spec`, `dense_property_generator`, `ambiguity_detector`）、`complete_with_tools` の独立 `mcp_sampling.complete_with_tools` span 化（tool_count / tool_choice 属性付き）、ディスパッチ関数 `complete_text` / `complete_response` の `llm.complete_text` / `llm.complete_response` span 化（dispatch_path 属性 + response token annotation）。

#### 計装対象（provider 経由の正規パス）

| 対象ファイル | 関数/メソッド | 計装内容 |
|---|---|---|
| `agent/llm_provider.py` | `OpenAILLMProvider.complete` (L55-60) | `client.chat.completions.create` を span でラップ |
| `agent/llm_provider.py` | `complete_text` (L242-244) / `complete_response` (L247-260) | ディスパッチ関数を計装し provider 種別を属性に記録 |
| `agent/llm_provider.py` | `McpSamplingLLMProvider.complete` (L77-84) / `_complete_via_sampling` (L86-116) | MCP sampling 経路を span 化。既存 `metadata={"mumei_agent_llm_provider": "mcp_sampling"}` に trace/span ID を追加 |
| `agent/llm_provider.py` | `McpSamplingLLMProvider.complete_with_tools` (L118-172) | ツール付き sampling を独立 span 化 |

#### 計装対象（provider を経由しない直接 `client.chat.completions.create` 呼び出し）

以下の箇所は `OpenAILLMProvider` を経由せず `client.chat.completions.create` を直接呼び出しているため、provider への寄せ直しまたは個別計装が必要:

| 対象ファイル | 関数 | 行番号 |
|---|---|---|
| `agent/strategies/spec_refinement.py` | `run_refinement_loop` 内の LLM 呼び出し | L86 |
| `agent/strategies/multi_stage_strategy.py` | `_multi_stage_fix` 内の fix LLM 呼び出し | L123 |
| `agent/strategies/multi_stage_strategy_helpers.py` | `_diagnose` 内の診断 LLM 呼び出し | L112 |
| `agent/strategies/cegis_loop.py` | `CEGISLoop._synthesize_invariant` | L195 |
| `agent/spec_extractor.py` | `_call_llm` 内の仕様抽出 LLM 呼び出し | L107 |
| `agent/code_to_spec.py` | `CodeToSpecConverter._call_llm` | L238 |
| `agent/dense_property_generator.py` | `DensePropertyGenerator.generate` | L76 |
| `agent/ambiguity_detector.py` | `AmbiguityDetector._detect_ambiguities` | L156 |

#### span 属性候補

- `gen_ai.request.model` — `agent/config.py` の `config.model`（例: `gpt-4o`、`qwen3.5:4b`）
- `gen_ai.system` — `openai-compatible` / `mcp-sampling` / `mcp-sampling-tools`
- `server.address` — `config.base_url`（例: `https://api.openai.com/v1`、`http://localhost:11434/v1`）
- `gen_ai.prompt.type` — プロンプト種別（`generate`、`fix`、`diagnose`、`refine`、`extract_spec` 等）

#### トークン metrics

- `agent/strategies/fix_strategy_helpers.py` の `response_token_count()` (L309) が OpenAI response の `usage.total_tokens` を抽出済み — これを OTel の `gen_ai.usage.total_tokens` counter/histogram に流用
- `agent/metrics.py` の `Metrics.record_tokens(count)` も同データを蓄積しており、OTel meter への二重報告を避ける設計が必要

---

### P15-2: Z3 検証のサブプロセス呼び出し（ツール span）

**ステータス: 実装済み（Phase 2）**

#### 計装対象

| 対象ファイル | 関数/メソッド | 計装内容 |
|---|---|---|
| `agent/mumei_client.py` | `MumeiClient.verify` (L86-168) | `mumei verify --json` の `subprocess.run` を span でラップ。exit code・stdout/stderr サイズ・`decidable_fragment` 有無を属性化 |
| `agent/mumei_client.py` | `MumeiClient.verify_loss_vector` (L170-183) | `mumei verify --emit loss-vector` を独立 span。loss-vector 取得が re-run されるケースの可視化 |
| `agent/mumei_client.py` | `MumeiClient.check` (L185-197) | `mumei check` パース検証 span |
| `agent/mumei_client.py` | `MumeiClient.infer_effects` (L199-208) / `infer_contracts` (L210-219) | エフェクト/契約推論 span |
| `agent/mumei_client.py` | `MumeiClient.build_with_emit` (L221-235) / `build` (L237-249) | ビルド/FFI emit span |

#### span 属性候補

- `mumei.command` — `verify` / `check` / `infer-effects` / `infer-contracts` / `build`
- `mumei.source_path` — 検証対象ファイルパス
- `mumei.exit_code` — subprocess exit code
- `mumei.collect_decidable_metrics` — decidable-metrics 収集フラグ
- `mumei.loss_vector.present` — loss-vector が返されたか
- `mumei.verification.duration_ms` — サブプロセス実行時間

#### 備考

- `create_mumei_client` ファクトリ (L53-75) が `MumeiMCPClient` を返す場合（`USE_MCP_CLIENT=true`）、MCP 経由の検証パスも同じ span 体系でラップする必要がある

---

### P15-3: エージェントの反復ループ（親 trace / root span）

**ステータス: 実装済み（Phase 3）**

実装内容:

- `agent/telemetry.py` に `start_loop_span(loop_type, *, max_retries, strategy, **attrs)` コンテキストマネージャと `add_thought_event(action, attributes)` ヘルパを追加。`is_enabled()` ガード付き・OTel 未インストール時 NoOp・例外握りつぶし。
- `agent/thought_log.py` の `ThoughtProcess.add_step()` 内部で `add_thought_event()` を呼び出し、現在の trace context 上の span に `action` イベントを発行。`to_dict()` 出力形式は一切変更なし。
- `agent/strategies/generate_strategy.py` の `generate_code` / `generate_multi_atom` を `mumei.loop.generate` root span でラップ。`mumei.strategy`（`single` / `multi-stage`）、`mumei.loop.final_success`、`mumei.loop.attempt` を属性化。
- `agent/self_healing.py` の `main()` heal ループを `mumei.loop.heal` root span でラップ。CEGIS / Meta-Architect / LLM fix 分岐を span イベント化、`mumei.loop.stop_reason` を属性化。
- `agent/self_correction.py` の `StructuredFeedbackSelfCorrectionLoop.run` を `mumei.loop.self_correction` root span でラップ。`stop_reason` を span 属性に写像。
- `agent/strategies/self_correction_strategy.py` の `SelfCorrectionStrategy.run` を `mumei.loop.self_correction_strategy` root span でラップ。`budget_policy.fingerprint` を属性化、`budget_decision` を span イベント化。

#### 計装対象

| 対象ファイル | 関数/クラス | 計装内容 |
|---|---|---|
| `agent/strategies/generate_strategy.py` | `generate_code` / `generate_multi_atom` (L263-606) | retry ループ全体を root span 化。各イテレーション（parse check → verify → fix）を子 span にする |
| `agent/self_healing.py` | `main()` の heal ループ (L314-) | `for attempt in range(max_retries + 1)` を root span 化。CEGIS repair / Meta-Architect refactor / LLM fix の分岐を子 span にする |
| `agent/self_correction.py` | `StructuredFeedbackSelfCorrectionLoop.run` (L81-211) | P9-F 収束ループを root span 化。`stop_reason`（`converged` / `max_retries_reached` / `token_cost_exceeded` / `no_fix_produced`）を span 属性化 |
| `agent/strategies/self_correction_strategy.py` | `SelfCorrectionStrategy.run` (L94-227) | P9-F 予算付き自己修正ループを root span 化。`action_class` / `budget_policy` 判定を span イベント化 |

#### `ThoughtProcess` → span イベント写像

`agent/thought_log.py` の `ThoughtProcess.add_step()` が記録する `VerificationStep`（action = `initial_verify` / `re_verify` / `llm_fix`）を OTel span events に写像する統合方針:

- `ThoughtProcess` のコンストラクタで現在の trace context を取得し、`started_at` と trace の開始時刻を一致させる
- `add_step(action=...)` の呼び出しごとに `span.add_event(name=action, attributes={...})` を発行
- `final_success` / `total_attempts` を root span の終了時属性として付与

#### span 属性候補

- `mumei.loop.type` — `generate` / `heal` / `self_correction` / `self_correction_strategy`
- `mumei.loop.max_retries` — 最大リトライ回数
- `mumei.loop.attempt` — 現在のイテレーション番号
- `mumei.loop.stop_reason` — 停止理由
- `mumei.loop.final_success` — 最終結果
- `mumei.strategy` — `single` / `multi-stage` / `cegis_loop` / `meta_architect`
- `mumei.budget_policy.fingerprint` — 予算ポリシーのフィンガープリント

---

### P15-4: MCP サーバー（外部エージェント連携の入口）（実装済み）

**ステータス: 実装済み**（`agent/telemetry.py` に `extract_trace_context` / `start_tool_span` を追加し、`agent/mcp_server.py` の主要 10 ツールを `mcp.tool.<name>` span でラップ。`agent/mcp_server_helpers.py` の `_carrier_from_ctx` が incoming MCP request の `_meta` から W3C Trace Context を取り出し、入口 span の parent に設定する。）

#### 計装対象

| 対象ファイル | ツール / 関数 | 計装内容 |
|---|---|---|
| `agent/mcp_server.py` | `@mcp.tool()` `forge_task` | forge 実行の入口 span。呼び出し元 agent の trace context を受信 |
| `agent/mcp_server.py` | `@mcp.tool()` `heal_file` | heal 実行の入口 span。ディレクトリ対応時の子 span 生成 |
| `agent/mcp_server.py` | `@mcp.tool()` `run_nlae_pipeline` | NLAE pipeline の入口 span |
| `agent/mcp_server.py` | `@mcp.tool()` `self_correct` | 自己修正ループの入口 span |
| `agent/mcp_server.py` | `@mcp.tool()` `audit_code` / `scan_and_fix` | 監査パイプラインの入口 span |
| `agent/mcp_server.py` | `@mcp.tool()` `extract_spec_from_code` | 仕様抽出の入口 span |
| `agent/mcp_server.py` | `@mcp.tool()` `measure_std_health` / `propose_forge_tasks` / `list_forge_log` / `get_agent_status` | 軽量ツールの span（レイテンシ計測目的） |

#### トレースコンテキスト伝播

- `agent/llm_provider.py` の `McpSamplingLLMProvider._complete_via_sampling` は `telemetry.inject_trace_context({"mumei_agent_llm_provider": "mcp_sampling"})` により送信側 `traceparent` / `tracestate` を注入済み（P15-1）。
- 外部 MCP client（Claude Code / Devin）が W3C Trace Context を MCP request の `_meta` に含める場合、`mcp_server.py` の各ツールハンドラが `_carrier_from_ctx(ctx)` → `telemetry.extract_trace_context(carrier)` でコンテキストを抽出し、入口 span（`mcp.tool.<name>`）の parent に設定する。抽出できない場合は新規 root span として振る舞う（後方互換）。これにより MCP client → tool → 内部ループ（`mumei.loop.*`）→ verify subprocess（`mumei.verify`）→ LLM が 1 本の trace で接続される。

---

### P15-5: 既存メトリクスの OTel Metrics 接続（実装済み）

**ステータス: 実装済み**（`agent/telemetry.py` に P15-5 instrument ヘルパ群を追加し、`agent/metrics.py` の `record_verification_time` / `record_new_spec` / `record_attempt` / `record_success`、`agent/harness_metrics.py` の `record_stage`、`agent/lean_bridge.py` の `run_lean_bridge` 全 return 経路から OTel Metrics を並行送信。既存の `to_dict()` / `aggregate_metrics()` / 戻り値 dict の JSON 形式は一切変更なし。）

#### 計装対象

| 対象ファイル | クラス / 関数 | OTel Metric 候補 |
|---|---|---|
| `agent/metrics.py` | `Metrics.llm_tokens_used` | `gen_ai.usage.total_tokens` (Counter) |
| `agent/metrics.py` | `Metrics.verification_times_seconds` | `mumei.verify.duration` (Histogram, 単位: seconds) |
| `agent/metrics.py` | `Metrics.first_pass_verification_success_rate` | `mumei.first_pass.success_rate` (Gauge) |
| `agent/metrics.py` | `Metrics.z3_unknowns` | `mumei.z3.unknowns` (Counter) |
| `agent/metrics.py` | `Metrics.outside_decidable_fragment_warnings` | `mumei.decidable_fragment.warnings` (Counter) |
| `agent/metrics.py` | `Metrics.total_attempts` / `successes` | `mumei.fix.attempts` / `mumei.fix.successes` (Counter) |
| `agent/metrics.py` | `Metrics.by_violation_type` | `mumei.fix.attempts` に `violation_type` attribute を付与 |
| `agent/harness_metrics.py` | `HarnessMetrics.record_result` | `mumei.harness.tokens_to_success` (Histogram)、`mumei.harness.solver_seconds_to_success` (Histogram)、`mumei.harness.spec_drift_score` (Histogram) |
| `agent/harness_metrics.py` | `HarnessMetrics.aggregate_metrics` | stage/module 別集計を OTel の dimension attributes で自然に再現 |
| `agent/lean_bridge.py` | `count_lean_verified_unknowns` / `run_lean_bridge` 結果 | `mumei.lean.verified_count` (Counter)、`mumei.lean.bridge.duration` (Histogram)、`mumei.lean.bridge.error_code` (属性付き Counter) |

#### 統合方針

- `Metrics` / `HarnessMetrics` の既存 `record_*` メソッド内部で OTel meter が利用可能な場合のみ OTel instrument に値を送信し、既存の JSON 出力パスはそのまま維持する
- `to_dict()` の出力形式には影響を与えない（OTel は並行チャネルとして追加）

---

### P15-6: 週次ラン / NLAE / 監査パイプラインの span 計装 + Rust コンパイラ連携（実装済み）

**ステータス: 実装済み**（全 span は `is_enabled()` ガード付き・OTel 未インストール時 NoOp・例外を握りつぶす設計。既存の `proliferate()` 戻り値・`summary.json` 出力、`NLAEResult.to_dict()`、`AuditResult` / `AuditDirectoryResult` の dataclass 形式は不変。`NLAEResult` には末尾 optional の `trace_id: str | None = None` のみ追加。）Rust コンパイラ連携が実装済み — 下記参照。

#### `agent/proliferate.py` — 週次自律ラン（実装済み）

- `proliferate()` 全体を `mumei.proliferate` root span でラップ。属性 `mumei.proliferate.max_proposals` / `dry_run` / `harness_profile` / `proposals_found`
- `[PROLIFERATE] Step N/4` を子 span 化：`mumei.proliferate.gap_analysis` / `spec_generation` / `forge`
- 並列 forge（`_parallel_forge`, `ThreadPoolExecutor`）は `telemetry.capture_context()` / `use_context()` でワーカースレッドに span コンテキストを伝播し、各候補が `mumei.proliferate.forge.candidate` 子 span として `mumei.proliferate.forge` 配下に紐づく
- 各提案の publish 処理は `mumei.proliferate.proposal` 子 span。属性 `target_file` / `verified` / `blast_radius_broken` / `healed`
- `_run_lean_fallback()` を `mumei.proliferate.lean_fallback` span でラップ（metrics は P15-5 の `record_lean_bridge_result` に一本化、二重報告なし）

#### `agent/nlae_pipeline.py` — `NLAEPipeline.run_full_pipeline`（実装済み）

- 全体を `mumei.nlae.pipeline` root span でラップ。生成 → Z3 検証 → 自己修正 → Lean bridge の 4 段階を `mumei.nlae.generate` / `verify` / `self_correction` / `lean_bridge` 子 span に分割
- 属性 `mumei.nlae.verified` / `lean_verified` / `loss_vector.present`
- root span の trace ID を `NLAEResult.trace_id`（末尾 optional）に格納し、MCP tool `run_nlae_pipeline` の入口 span（P15-4）まで trace を遡及可能。MCP 経由呼び出し時は入口 span が current span となり、この root span が自動的にその子として接続される
- 4 リポジトリ横断（mumei-agent / mumei / mumei-lean / mumei-demo）の分散トレースの起点

#### `agent/audit.py` — 監査パイプライン（実装済み）

- `AuditPipeline.audit_file` / `audit_directory` / `audit_source` を `mumei.audit.file` / `mumei.audit.directory` / `mumei.audit.source` span でラップ
- `audit_directory` 配下に各ファイルの `mumei.audit.file` 子 span が逐次ぶら下がる
- 属性 `mumei.audit.language` / `success` / `violations`（file/source）/ `files_with_issues`（directory）

#### Rust コンパイラ側（`mumei-lang/mumei`）との分散トレース接続（実装済み）

- Rust 側: `Cargo.toml` に `otel` feature（デフォルト無効）を新設。`tracing` / `tracing-opentelemetry` / `opentelemetry` / `opentelemetry-otlp` を opt-in で追加。`src/telemetry.rs` が `OTEL_ENABLED` + `OTEL_EXPORTER_OTLP_ENDPOINT` で OTLP tracer を初期化し、`TRACEPARENT` 環境変数から親コンテキストを抽出する
- `src/commands/verify.rs`: `mumei.verify.cli` root span（属性 `source_path` / `timeout_ms`）を `TRACEPARENT` から抽出した親コンテキストにぶら下げる
- `mumei-core/src/verification/executor.rs`: `verify_inner` を `mumei.z3.solve` 子 span（属性 `atom_name` / `timeout_ms`）でラップ
- Python 側: `agent/telemetry.py` に `current_traceparent() -> str | None` を追加。`agent/mumei_client.py` の `MumeiClient._run_command` / `verify` の `subprocess.run` に `env={**os.environ, "TRACEPARENT": tp}` を注入（OTel 無効時は既存挙動のまま）
- 結果: `mumei-agent` → `subprocess.run("mumei verify ...")` → Z3 実行まで、W3C Trace Context で 1 本の分散トレースに串刺し

### P15-7: 運用アラート/SLO 層（完了）

**ステータス: 完了** — P15-1〜P15-6 で整備した OTel メトリクス/ダッシュボードの上に、SLO ベースで回帰を自動検知するアラート層を追加。アラート式のメトリクス名は `agent/telemetry.py` の instrument 名（`deploy/otel/prometheus.yml` の collector 正規化を経た Prometheus 名）に厳密一致させ、`docs/OBSERVABILITY.md` の「(e) Alerts / SLO」に各アラートの意味・閾値・runbook を記載。

- **Prometheus アラートルール** — [`deploy/otel/alert_rules.yml`](../deploy/otel/alert_rules.yml) に SLO アラートを定義し `prometheus.yml` の `rule_files` に登録。first-pass 成功率低下（`mumei_first_pass_success_rate_{sum,count}` の窓平均、warning <0.70 / critical <0.40）、verify p95 スパイク（`mumei_verify_duration_seconds_bucket`、>30s）、fix 成功率低下（`mumei_fix_successes_total` / `mumei_fix_attempts_total`、<0.50）、Lean fallback エラー率上昇（`mumei_lean_bridge_error_code_total` を `mumei_lean_error_code` 別、>0.05/s）、LLM トークンコスト急増（`gen_ai_usage_tokens_total`、>2000 tok/s）。各ルールに severity ラベルと `docs/OBSERVABILITY.md` 該当セクションへの runbook_url annotation を付与。`promtool check rules` で検証可能。
- **Grafana アラート/しきい値可視化** — ダッシュボード JSON に SLO しきい値ライン付きパネルと alertlist（アラート状態）パネルの行を追加。`deploy/otel/grafana/provisioning/alerting/` に contact point（ローカル検証用 webhook）と notification policy を provisioning。
- **proliferate 回帰ゲート接続** — `summary.json` に末尾 optional の `otel_slo_status` フィールドを追加（`OTEL_ENABLED=false` 時は `None` で後方互換を維持、既存フィールド・`_write_output_json` 契約は不変）。run 結果から `proposal_success_rate`（self-heal / publish 後の proposal 単位成功率）を導出し SLO 違反を集約する。これは OTel の `mumei.first_pass.success_rate`（atom 単位の初回 verify 成功率、Prometheus 側 `MumeiFirstPassSuccessRateLow` が担当）とは別量である点に注意。
- **CI 連携** — `.github/workflows/proliferate.yml` の post-run 集計に `otel_slo_status` を GitHub Step Summary へ出力するステップを追加（既存の health regression 失敗ゲートのロジックは不変・観測のみ）。

### 対象ファイル（全体）

- `agent/llm_provider.py` — LLM provider の span 計装（Phase 1）
- `agent/strategies/fix_strategy_helpers.py` — `response_token_count()` の OTel token counter 接続
- `agent/strategies/spec_refinement.py` — 直接 LLM 呼び出しの provider 寄せまたは個別計装
- `agent/strategies/multi_stage_strategy.py` — 同上
- `agent/strategies/multi_stage_strategy_helpers.py` — 同上
- `agent/strategies/cegis_loop.py` — 同上
- `agent/spec_extractor.py` — 同上
- `agent/code_to_spec.py` — 同上
- `agent/dense_property_generator.py` — 同上
- `agent/ambiguity_detector.py` — 同上
- `agent/mumei_client.py` — Z3 verify subprocess の span 計装（Phase 2）
- `agent/strategies/generate_strategy.py` — generate/retry ループの root span 化（Phase 3）
- `agent/self_healing.py` — heal ループの root span 化（Phase 3）
- `agent/self_correction.py` — P9-F self-correction ループの root span 化（Phase 3）
- `agent/strategies/self_correction_strategy.py` — P9-F strategy ループの root span 化（Phase 3）
- `agent/thought_log.py` — `ThoughtProcess` の OTel span event 写像（Phase 3）
- `agent/mcp_server.py` — MCP ツールの入口 span 計装 + トレースコンテキスト伝播（Phase 4）
- `agent/metrics.py` — `Metrics` の OTel Metrics 接続（Phase 1-3 並行）
- `agent/harness_metrics.py` — `HarnessMetrics` の OTel Metrics 接続（Phase 1-3 並行）
- `agent/lean_bridge.py` — Lean bridge の span + metrics 接続（Phase 2-3）
- `agent/proliferate.py` — 週次自律ランの root span 化（Phase 6、実装済み）
- `agent/nlae_pipeline.py` — NLAE pipeline の分散トレース（Phase 6、実装済み）
- `agent/audit.py` — 監査パイプラインの span 計装（Phase 6、実装済み）
- `pyproject.toml` — `opentelemetry-*` optional-dependencies 追加

### 成功指標

- OTel SDK 導入後、`OTEL_EXPORTER_OTLP_ENDPOINT` を設定するだけで Jaeger / Grafana Tempo 等のバックエンドに trace が送信される
- 既存の JSON metrics 出力（`Metrics.to_dict()`、`HarnessMetrics.aggregate_metrics()`）との互換性を 100% 維持
- `OTel_ENABLED=false`（デフォルト）の場合、パフォーマンスへの影響が計測不可能なレベルに収まる
- LLM 呼び出し 1 件ごとに `gen_ai.request.model`、`gen_ai.usage.total_tokens`、レイテンシが trace に記録される
- Z3 verify のサブプロセス実行時間が `mumei.verify.duration` histogram に記録される
- エージェントの 1 回の heal/generate/self-correct サイクル全体が 1 つの trace として可視化される
- MCP ツール経由の外部呼び出しが W3C Trace Context で親 trace に接続される
- `mumei verify` を `--features otel` ビルド + `TRACEPARENT` 付きで呼んだとき、Rust 側 `mumei.verify.cli` → `mumei.z3.solve` span が Python 側 trace と同一 trace ID で貫通する（Rust 連携: mumei PR #398、達成済み）
- リファレンス OTLP スタック（`docker-compose.otel.yml`: OTel Collector / Jaeger / Prometheus / Grafana）で trace と metrics を可視化できる（[`docs/OBSERVABILITY.md`](OBSERVABILITY.md)、達成済み）
- SLO ベースのアラート（`deploy/otel/alert_rules.yml`）で first-pass 成功率・verify p95・fix 成功率・Lean fallback エラー率・LLM トークンコストの回帰を自動検知でき、`promtool check rules` が通る（P15-7、達成済み）

---

## Related Documents

- [mumei-lang/mumei `docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) — Cross-project roadmap (incl. Strategic Initiatives)
- [mumei-lang/mumei `docs/ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/ROADMAP.md) — Compiler strategic roadmap
- [mumei-lang/mumei `docs/REPORT_SCHEMA.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/REPORT_SCHEMA.md) — report.json schema (consumed by agent)

## 外部コード解析基盤（Layer B / language_patterns）の現状と将来選択肢 — 備考

**現状**: tree-sitter（単一ファイル・構文レベルのみ）+ 正規表現フォールバック + Python のみ `ast` モジュールの3層。シンボルテーブル・型解決・alias / call-graph 解析は存在しない。そのため完全な taint 追跡や race/競合検出（P17 残課題: 同期プリミティブ保護下の共有可変状態への干渉推論）は現基盤では信頼度が下がり、現在は縮小版（`taint_lite` は同一ファイル内の代入追跡のみ、`go_shared_state` は宣言 mutex の存在ベース）として実装済み。

**将来の選択肢（必要になった段階で判断）**:

1. tree-sitter stack-graphs / SCIP・LSIF によるシンボル解決層の追加 — 自前実装で正確だが基盤構築コスト大。
2. CodeQL / Semgrep 連携 — 解析を外部エンジンに委譲し mumei-agent が結果を取り込む。工数対効果で最も現実的。
3. P17 の独自実装（干渉推論）— rely-guarantee / separation-logic 級の研究寄り項目。スコープを絞れば可能だが優先度は需要次第。

層B の対応言語拡張（C/C++/Java）も同じく「必要な段階で判断」の次タスク候補として残置する。

## P-Deferred-A: heal コマンドの複数ファイル対応 — ✅ Implemented

### 実装完了サマリ

`heal` の複数ファイル対応は、mumei-lang/mumei PR #285（multi-file cross-spec verification）および mumei-lang/mumei-agent PR #121（spec contradiction MCP tools）の成果物を前提に実装済み。
ファイル間依存解決・cross-spec verification の基盤を使い、複数 `.mm` ファイルを依存順に修復できる。

### 実装内容

**前提条件**: PR #285 / PR #121 の完了

1. ✅ `heal_file` MCP ツール（`agent/mcp_server.py`）にディレクトリ対応を追加
   - 引数 `code_file` がディレクトリの場合、`.mm` ファイルを再帰収集する
   - PR #285/#121 が提供するファイル間依存グラフを使って修復順序を決定する（依存先ファイルを先に修復）
2. ✅ `python -m agent heal` CLI サブコマンド（`agent/__main__.py`）もディレクトリを受け付けるよう拡張
3. ✅ 修復ループをファイル間依存グラフに基づいて順序制御する
   - 依存先ファイルの修復が完了してから依存元ファイルの修復を開始する
   - 循環依存がある場合は警告を出して手動レビューへ送る
4. ✅ 複数ファイルの修復結果を集約して返す（成功/失敗件数、ファイルごとのサマリ）

**対象ファイル**:
- `agent/mcp_server.py` — `heal_file` ツールのディレクトリ対応
- `agent/__main__.py` — `heal` サブコマンドのディレクトリ対応
- `agent/strategies/fix_strategy.py` — 依存グラフに基づく修復順序制御

**性能上の注意**:
- ファイル間依存関係がある場合、処理時間は N×（単一ファイル時間）を超える可能性がある
- 依存解決の追加オーバーヘッドが発生するため、並列化よりも依存順序の正確性を優先する

## P-Deferred-B: extract_spec_from_code の対応言語拡張（Ruby/Swift/Kotlin 等） — ⏸️ Deferred (低優先度)

### 対応しない理由

`extract_spec_from_code` は LLM ベースの処理であるため、未対応言語でも `unknown` として扱うことで一定の動作が保証される。
精度改善は継続的な作業であり、現時点では他の課題（ディレクトリ対応等）を優先する。

### 将来の対応詳細

**実装方針**:
1. `agent/extract_spec.py` の `--code-language` オプションの `choices` に以下を段階的に追加する
   - 優先度高: `ruby`, `swift`, `kotlin`
   - 優先度中: `scala`, `haskell`, `elixir`
   - 優先度低: その他の言語
2. `agent/mcp_server.py` の `extract_spec_from_code` ツールの `language` パラメータの説明を更新する
3. `agent/code_to_spec.py` の LLM プロンプトに言語固有のヒントを追記する
   - 型システムの特徴（例: Ruby の duck typing、Swift の Optional、Kotlin の null safety）
   - 言語固有の慣用句（例: Ruby の block/proc/lambda、Swift の guard let）
   - 言語固有のエラーハンドリングパターン

**対象ファイル**:
- `agent/extract_spec.py` — `--code-language` の `choices` 拡張
- `agent/mcp_server.py` — `extract_spec_from_code` の `language` パラメータ説明更新
- `agent/code_to_spec.py` — 言語固有プロンプトヒントの追加

**性能上の注意**:
- 処理時間への影響は小さい（LLM 呼び出し回数は変わらない）
- 精度（spec 抽出品質）の改善が主な目的

---

## 外部コード dogfooding 堅牢性拡張 ✅ Implemented

> **ステータス: ✅ Implemented** — 項目1（実 OSS コーパス）・項目2（集計 / ゲート層の CI 恒久運用化）とも
> 実装済み。実装位置は `tests/corpora/oss/`（`MANIFEST.json` で upstream commit をピン留め）と
> `tests/test_foreign_code_oss_corpus.py`、`scripts/dogfood_triage_gate.py`、
> `.github/workflows/dogfood-triage.yml`。運用手順は `docs/CI_WORKFLOWS.md` 参照。
> 過去のドッグフーディングでは go-ethereum 等の外部 OSS コードを
> `agent/cross_validation.py` の `validate_foreign_code`（python/rust/typescript/go/solidity 対応）へ通し、
> 決定的抽出（`agent/cross_validation_foreign.py` の `_infer_go_contracts` →
> `_raw_return_statement_expression`）が「多値 return から不正な `ensures`（例: `result == sum, carryOut != 0`）を
> 生成する」クラスのバグを発見・修正した（PR #371）。
> 既にプラン済みの直近作業（① 各言語の合成シグネチャコーパスによるパーサ堅牢性 property テスト、
> ② dogfood 結果を既存 verdict でバケット分けする集計/トリアージ層）の **次段階** として、以下 2 施策を追加する。
>
> top-level 権威は `mumei-lang/mumei/docs/CROSS_PROJECT_ROADMAP.md` であり、本節は mumei-agent 側の
> ローカル受け入れ詳細のみを記載する。用語は固定キー（`verification_status` = `verified` / `refuted` / `unverifiable`、
> `verification_violations`、`cross_validation_gaps` 等）に揃え、別名 alias は導入しない。新規の verdict 分類も作らない。

**推奨導入順**: 項目1（実 OSS コーパス拡大）→ 項目2（集計層の CI 恒久運用化）。
両者とも既存の決定的抽出（`use_llm=False`）・既存 verdict・既存 oracle を信頼し、外部依存ゼロ（`ollama-local`）を維持する。

### 項目1: コーパスの実 OSS サンプリング拡大 ✅ Implemented

**実装**: `tests/corpora/oss/` に python / rust / typescript / go / solidity の実 OSS ファイル 10 件
（requests / packaging / memchr / ripgrep / vscode / golang 標準ライブラリ / OpenZeppelin）を
**未修正のまま** 取り込み、`MANIFEST.json` に upstream リポジトリ・タグ・40 桁 commit sha・元パス・
license を記録してバージョンを固定した。`tests/test_foreign_code_oss_corpus.py` が決定的抽出
（`use_llm=False`, `run_mumei=False`）経由で全 44 atom の `requires` / `ensures` を既存 oracle 3 種で
面検証し、ファイルごと 200 行 / コーパス合計 2000 行の CI 予算ガードと manifest/ディスク一致・
言語網羅・atom 非空も回帰テストする（実行時間 < 1s）。

当初の計画メモ（履歴として保存）:

- 現状の property / コーパステストは **合成シグネチャ中心** である前提を明記する。合成コーパスは決定的抽出の
  構造的脆さ（多値 return、ネスト式、幻覚関数）を面で叩くには有効だが、実 OSS の多様な構文分布は覆いきれない。
- 次段階として、ピン留め（バージョン固定）した **実 OSS ファイル群** を各対応言語（python / rust / typescript / go / solidity）から
  サンプリングし、決定的抽出（`use_llm=False`）経由で `inferred_atoms` の `ensures` / `requires` が **常に妥当** であることを
  面で検証する構想を記載する。妥当性は既存 oracle をそのまま流用する:
  - `agent/audit_reporting.py` の `_malformed_extraction_issue_strings` が空であること。
  - `agent/audit_reporting.py` の `_is_boolean_like_clause` が真であること。
  - `agent/cross_validation_foreign.py` の `_is_multi_value_return_expression` で多値カンマ残存がないこと。
- **前提条件**: `oss-dogfood` 配置と `local-llm-demo` blueprint はまだ未コミットである。実 OSS コーパスの固定
  （ピン留めしたファイル群の取り込み）は、その基盤コミットが前提になる。基盤が入るまでは合成コーパスを主軸に維持する。
- 🔍 **監視項目** — 実 OSS 固定コーパスの分量とパース時間（大きな関数・ループ・inline assembly・複雑な generics は
  per-file timeout を超えやすい）。小さいファイル起点でサンプリングし、コーパス総体が CI 予算内に収まるよう調整する。

**漸進拡大（実装済み）**: 監視項目の 3 形状を覆う小さいファイルを 3 件追加して 13 件に拡大した:
`rust/memchr_ext.rs`（54 行、generics）/ `go/go_cmp_ordered.go`（71 行、generics）/
`solidity/openzeppelin_short_strings.sol`（123 行、inline assembly）。`MANIFEST.json` の `risk_shape` に
追加理由を記録し、`tests/test_dogfood_timeout.py::test_pinned_corpus_covers_every_risk_shape` が
コーパスが risk 形状を覆い続けていることを固定する。合計行数は CI 予算ガード（ファイル 200 行 /
合計 2000 行）内に収まる。

### 項目2: dogfood 集計層の CI 恒久運用化 ✅ Implemented

**実装**: `scripts/dogfood_triage_gate.py` がディレクトリ監査を実行し、既存の
`agent/dogfood_triage.py::triage_directory_result` で verdict バケットに分け、JSON / Markdown（job
summary へ追記）を出力する。`refuted` のみ `next_steps` と `verification_violations` を展開し、
`unverifiable` は原因サブカテゴリの件数に畳み込む。`--fail-on-refuted` でゲート化可能。
`.github/workflows/dogfood-triage.yml` が cron（毎週水 02:00 UTC）＋ `ollama-local` で外部依存ゼロの
スケジュール実行を行う（proliferate.yml と同型の checkout / mumei build / ollama provisioning）。
8 固定キー契約（`AUDIT_SCHEMA_KEYS`）は `audit_contract` としてそのまま反射し、新規分類や alias は追加していない。
回帰テストは `tests/test_dogfood_triage_gate.py`。

**堅牢化（実装済み）**:

- `--per-file-timeout` でファイル単位の子プロセス監視（`agent/dogfood_timeout.py`）を行い、予算超過ファイルのみを
  強制終了する。打ち切ったファイルは既存語彙のまま `unverifiable` の `timeout` サブカテゴリに入る（新規 verdict はなし）。
  同時に構造的 risk marker（`large_function` / `inline_assembly` / `complex_generics`）と秒数を job summary に出す。
- `--history-file` で verdict バケットの時系列（`agent/dogfood_trend.py`）を蓄積し、`refuted` 急増と
  `unverifiable` サブカテゴリの偏りを `::warning::` で検知する。ワークフロー側は `actions/cache` で履歴を保持し、
  `verdict_history.json` をアーティファクトに含める。
- 回帰テストは `tests/test_dogfood_timeout.py` / `tests/test_dogfood_trend.py`、手順は
  [`docs/CI_WORKFLOWS.md`](./CI_WORKFLOWS.md)。

当初の計画メモ（履歴として保存）:

- verdict 分類（`refuted` / `unverifiable` / `verified`）は **既に実装済み** である前提を明記する
  （`agent/cross_validation_models.py` の `ForeignCodeVerdict`、`agent/cross_validation.py` の
  `_validate_foreign_code_verdict`）。新規分類は作らず、既存 verdict をそのまま信頼する。
- 次段階として、ディレクトリ / コーパス dogfood の出力を verdict でバケット分けする集計 / ゲート層を構想する:
  - `refuted`（実バグ候補）のみを human review に浮かせる（`verification_violations` と counterexample を伴う）。
  - `unverifiable` は原因サブカテゴリ（`skipped_rate_limited` / `timeout` / `no_function_declarations` / `encoding_gap`）へ
    畳み込み、ノイズとして人間の注意から外す。
  - `verified` は集計値として保持する。
- この集計層は `.github/workflows/proliferate.yml` と同型の **スケジュール実行ワークフロー**（cron + `ollama-local` で
  外部依存ゼロ）として恒久運用に組み込む構想とする。
- **前提の順守**: 既存の 8 固定キー契約（`AUDIT_SCHEMA_KEYS`）を壊さない。集計は `verification_status` /
  `verification_violations` / `cross_validation_gaps` 等の固定キーの上に載せ、別名 alias や新規レビュー入口キーは足さない
  （human review 入口は既存の `next_steps` のまま）。
- **ドキュメント**: 実ワークフローファイルを追加する段階で、`docs/CI_WORKFLOWS.md` に本ワークフローの説明節を後で追記する
  必要がある（下記「Planned」節参照）。
- 🔍 **監視項目** — verdict バケットの時系列（`refuted` 件数の急増は決定的抽出のリグレッション兆候、
  `unverifiable` サブカテゴリの偏りは環境要因の兆候）。既存 proliferate の job summary 出力慣習に揃える。

---

## 自然言語仕様抽出の曖昧性レポート（欠落要件 vs underspecified 意図） ✅ Implemented

paper `paper/index.md` Future Work #4 / known-limitations「the natural-language extraction
pipeline must conservatively distinguish missing requirements from underspecified intent」への対応。
canonical 上位ロードマップは mumei `docs/CROSS_PROJECT_ROADMAP.md`。

- `agent/spec_ambiguity.py` が抽出結果を保守的に 2 分類する。
  - `missing_requirement`: 抽出された contract clause が trivial（未設定 / 空 / `true`）で、かつ
    自然言語側が当該 atom に一切言及していない場合のみ。何も述べられていない以上、推測で補完しない。
  - `underspecified_intent`: 対象は述べられているが clause が確定していない場合、および
    `AmbiguityDetector` の語彙パターン（vague adjective / quantifier / conditional）に該当する prose。
- レポート経路は既存の 8 固定キー契約（`AUDIT_SCHEMA_KEYS`）の上に載せる。新規 verdict 分類や別名 alias は追加しない。
  - `missing_requirement` は `cross_validation_gaps` の 1 エントリとして出し、`verification_status` が
    `verified` になっていた場合は `unverifiable` へ落とす（検証した契約が空だったため）。
  - `underspecified_intent` はコードに対する所見ではないため verdict を下げず、`next_steps`
    （既存の human-review 入口）に確認依頼として積む。
- どちらの場合も抽出済み spec は書き換えない（曖昧なケースを勝手に補完しない）。
- 回帰ゲート: `uv run pytest tests/test_spec_ambiguity.py tests/test_audit.py tests/test_contract_vocabulary.py -q`

---

## AI エージェントネイティブ統合の標準化（agent 側 local checkpoint）— ✅ Implemented

canonical 上位ロードマップは mumei `docs/CROSS_PROJECT_ROADMAP.md` の
"Priority 17: AI エージェントネイティブ統合の標準化（MCP / CI / エディタ）"。
本節はその agent 側 local checkpoint であり、canonical contract に従属する。

**実装エビデンス**:

1. **MCP ツール契約** — `docs/MCP_SERVER.md` の生成済み表は agent
   `agent/mcp_server.py` の AST からツール名・引数注釈・デフォルト値を導出し、
   docstring の Returns-style 記述にある戻り値キーだけを記録する。mumei の
   `docs/MCP_TOOL_CONTRACT.md` が cross-server canonical table であり、agent
   文書は従属文書である。`tests/test_mcp_tool_contract.py` がコードと表の
   双方向 drift（追加・欠落・署名差分）を offline で検査し、
   `.github/workflows/contract-vocabulary.yml` がこれを実行する。
   `scan_and_fix` は `audit --auto-migrate --auto-heal` と同一契約であり、
   既存の 8 固定キー（`spec_health_issues` / `verification_violations` /
   `verification_status` / `cross_validation_gaps` / `next_steps` /
   `migration_hints` / `healed_files` / `heal_errors`）と別名禁止を維持する。
2. **MCP sampling** — `USE_MCP_SAMPLING` の capability detection、sampling
   fallback、tool-enabled sampling、`maxTokens` 上限、および text-only request
   の回帰は `tests/test_mcp_server.py` と
   `tests/test_llm_provider_sampling_tools.py` で検査する。sampling
   provider と OpenAI-compatible provider が同一の戻り値 surface
   （`response.choices[0].message.content` と token accounting）を出すことは
   `tests/test_llm_provider_contract.py` が provider-independent contract
   として固定する。`budget_policy_fingerprint` は LLM 応答ではなく
   certificate artifact 由来のため、ここでは対象外とする。
3. **Proof artifact** — mumei が配布する per-module certificate と bundle は
   canonical な `artifact_paths` で参照し、`MUMEI_PROOF_CERTS` /
   `MUMEI_PROOF_BUNDLE` と `mumei verify-cert --strict` による distribution-only
   再検証手順を [`docs/VERIFICATION_WORKFLOW_GUIDE.md`](VERIFICATION_WORKFLOW_GUIDE.md)
   に同期した。consumer wiring は `agent/proofcert.py` の
   `artifact_paths_of` / `validate_artifact_paths` と
   `ProofCertificate` の P5-A metadata accessors（`harness_contract` /
   `intent_fidelity` / `artifact_paths` / `budget_policy_fingerprint` /
   `lean_provenance`）で実装し、`agent/publish.py` が `--proof-cert` で
   生成した証明書ファイルから宣言された `artifact_paths` を収集し
   `artifact_paths_status` として検証（verify --json レポートは
   これらを持たないため証明書ファイルが正典ソース）、
   `proliferate --output-json` の `proof_certificate_summary` /
   `upgraded_cert_summary` が certificate の canonical keys をそのまま
   参照する。独立した bundle intake や新しい artifact key / alias は
   追加しない。
4. **CI 常時化** — mumei の `.github/workflows/stdlib-proof-gate.yml` が
   certificate-derived baseline `scripts/std_proof_baseline.json` と shared
   `scripts/verify_packaged_certs.py` を使って証明書・bundle・metrics の gate を
   常時実行する。metrics の `proven` / proof density は source-count heuristic
   であり、certificate-derived count との density 比較は意図的に行わない。

**回帰ゲート**: `uv run pytest tests/test_contract_vocabulary.py tests/test_mcp_server.py tests/test_mcp_tool_contract.py tests/test_llm_provider_contract.py -q`

## 大規模ケースでの合成性報告（agent 側 local checkpoint）— ✅ Implemented

canonical 上位ロードマップは mumei `docs/CROSS_PROJECT_ROADMAP.md` の
"Priority 16: 大規模・安全性クリティカル領域での atom-local proof obligation 合成性検証"。
本節はその agent 側 local checkpoint であり、canonical contract に従属する。

**実装エビデンス**:

1. **`python -m agent scale-report`** — `agent/scale_report.py` が mumei の
   `scripts/measure_composability.py` / `scripts/scale_trust_surface.py` が出した
   artifact を読み、大規模ケース（`mumei-demo` の `*_scale` シナリオ、172 atoms、
   依存深さ 5–7）の結果を既存の 8 固定キー（`spec_health_issues` /
   `verification_violations` / `verification_status` / `cross_validation_gaps` /
   `next_steps` / `migration_hints` / `healed_files` / `heal_errors`）で報告する。
   新しい verdict 分類も別名 alias も追加しない。
2. **合成の破れ → `verification_violations`** — 隣接 atom の契約を弱めると閉じない
   箇所（277 本）は 1 件ずつ `verification_violations` に載る。対象 atom、clause 種別
   （`requires` / `ensures` / `effect_pre` / `effect_post`）、行、破れのパターンを含む。
3. **compiler 改善入力 → `next_steps`** — パターン別（`call_site_precondition` 86 /
   `counterexample_replay_mismatch` 86 / `effect_state_obligation` 58 /
   `neighbor_ensures_strengthening` 47）の集計を、対応する compiler surface とともに
   既存の `next_steps` に載せる。
4. **verdict は既存 3 値のみ** — `verify-cert --strict` の失敗と `std/` trusted atom の
   回帰（0 → 非 0）だけが `refuted` を立て、artifact にケースが無い場合は
   `unverifiable`、それ以外は `verified`。`budget_policy_fingerprint` は artifact から
   そのまま引き継ぐ。

**回帰ゲート**: `uv run pytest tests/test_scale_report.py tests/test_contract_vocabulary.py -q`

## ドッグフーディング本監査（12リポ・4331ファイル）— 結果集計と是正バックログ

2026-09 実施の外部 OSS 監査（監査セッション: dogfooding 検証 run、
対象 = zERC20 / helios / tfhe-rs / leanVM / eris-agent-simulator / dioxus /
uniswap-contracts / lighthouse / grin / tidb / bsc-genesis-contract / world-chain、
全 4331 ファイル、`python -m agent audit` + Ollama `qwen2.5-coder:1.5b-2k`）の
最終集計と、是正・改善バックログ。元集計メモは `reports/dogfood-main-audit-2026-09.md` に保存済み。verdict 語彙は固定キー
（`verified` / `unverifiable` / `refuted`）のまま、新しい verdict 分類や alias は導入しない。

**集計**: `verified` 515 / `unverifiable` 237 / `refuted` 6 / timeout 3576（≈82%）。
内訳合計は 4334 で全ファイル表記（4331）と 3 件差がある — 元集計値どおり転記し、差分は監査ログ側の境界カウント由来と推定される。
対象リポ側の確定的な不具合・脆弱性はゼロ（潜伏防御的ギャップ 1 件: tidb
`pkg/expression/expropt/optional.go` の `Contains` 境界チェック欠落 — 実害なし・悪用不可のため起票しない）。

**是正済み（マージ）**:

- **#573**: encoding-gap（`spec_not_boolean` 等、clause が Z3 にエンコードされず
  スキップ）を抱えたまま `verified` と報告される誤判定 → `unverifiable` 扱いに修正。
- **#574**: Solidity — relative import 先の constant 未解決 + 固定長配列長の未モデル化で
  `zeroHash[TREE_HEIGHT]` 偽陽性 `refuted`。推移的 import・alias・overload・
  `../../` パストラバーサル等 9 件も堅牢化。
- **#580**: Rust — `&mut [u32; 16]` 等の固定長配列パラメータ長と usize 非負制約の
  未モデル化で不可能な反例を生成。len 束縛 + パラメータ型を index チェックに反映。
- **#582**: Go — interface がパッケージスコープなのに同一ファイル宣言しか見ず
  nil レシーバ誤検知。`fmt.Stringer` を既知 interface に追加しシグネチャ一致
  （引数型+戻り値まで）で抑制判定を厳密化。

### 是正バックログ — 実装状況（2026-09-22 同期）

起票後のフォローアップセッションで B-1〜B-8 は全て実装・マージ済み（B-8 は #605）。

- **B-1 spec 抽出キャッシュ — ✅ Implemented**（#583 系、`9022f31a` + `54dab227`）:
  `extract_from_file` が `_spec_cache_key`（schema バージョン + モデル + 言語 +
  domain_hint + コード内容の SHA-256）で結果を content-addressed に保存し、
  `MUMEI_SPEC_CACHE_DIR`（または `AgentConfig.spec_cache_dir`）で有効化。
  write-then-rename の atomic write で中断耐性あり。再実行・部分再開で
  未変更ファイルの Ollama 推論をスキップ。
- **B-2 大ファイルの関数分割並列抽出 → 合成 — ✅ Implemented**（#586、`a68b09a2` +
  `3bb0a73d`）: `MUMEI_SPEC_SPLIT_CHARS` 指定で関数単位チャンクに分割し並列抽出、
  `_merge_forge_task_specs` で合成。per-chunk 失敗は寛容化（他チャンクを継続）。
- **B-3 trivial-spec 検出 → 再プロンプト — ✅ Implemented**（`9022f31a` +
  `54dab227` + `1de4e1dd`/#587）: trivial spec（自明 requires/ensures、`is not nil` 系）を
  検出して再プロンプト、加えて minimum spec 品質ガイドをプロンプトに埋め込み。
- **B-4 呼出側契約 `refuted` のノイズ抑制 — ✅ Implemented**（#585/#587）:
  `157e4275` で unexported 関数の抑制を試行したが pinned test が非公開関数の
  param contract 報告を要求するため `7a803303` で意図的に revert（判断記録済み）。
  到達可能反例フィルタは `1de4e1dd`（reachable-counterexample callsite filter）で実装。
- **B-5 兄弟メソッド guard 非対称ヒューリスティクス — ✅ Implemented**（#586、`a68b09a2`）:
  Go で一方は範囲チェック・他方は未チェックの兄弟関数を検出。
- **B-6 定数 / import 解決の汎化 — ✅ Implemented**（#585、`157e4275`）:
  Go の cross-package `const` 解決（module-relative import path のガード付き）。
- **B-7 重いファイル推定 + スキップ / 延長オプション — ✅ Implemented**:
  `--risky-timeout-scale`（`scripts/dogfood_triage_gate.py` →
  `agent/dogfood_timeout.py`）が risk marker（`large_function` / `inline_assembly` /
  `complex_generics`）を持つファイルの per-file timeout を拡大し、effective timeout を
  gate warning に出力（`ec04acc3`）。LLM レート制限時のスキップは
  `skipped_rate_limited_files` で報告。
- **B-8 `--enable-lean-bridge` のドキュメント化 / 既定検討 — ✅ Implemented**:
  `docs/AUDIT_CONTRACT.md`（Solidity 節: guard-trace certificate の
  access-control obligation は既定で `unknown`、bridge 有効化で `lean_verified`、
  CLI-only・MCP 非対応）と `docs/LEAN_FALLBACK.md`（audit 経路と proliferate
  fallback の区別）に明記。既定 ON は見送り — flag は `--mumei-lean-repo` 未設定で
  no-op 化する設計で、audit はローカルの mumei-lean checkout / Lake toolchain なし
  でも走れることが要件。既定 OFF + docs 明記が正しい結論と評価。
- **ローカル LLM 選定の profile 化 — ✅ Implemented**（#586、`a68b09a2`）:
  `MUMEI_LLM_PROFILE`（local-small / local-large preset）、`LLM_MODEL` 等の env は優先。

## C11 evidence-acceptance-eval: conjunctive requirement-list acceptance の fold — ✅ Implemented

canonical 上位ロードマップは mumei `docs/CROSS_PROJECT_ROADMAP.md` の C11
（Evidence acceptance と attempt binding）。本節はその agent 側 fold の
継続スライスであり、canonical contract に従属する。

`evidence-acceptance-eval` はこれまで `mumei.source-evidence-acceptance/v1` と
`mumei.native-evidence-acceptance/v1` の flat 記述子だけを受理し、Core
`evidence accept --requirement-list`（および `evidence-check-schedule
--promote` エクスポート）が emit する conjunctive
`mumei.evidence-requirement-list-acceptance/v1` は foreign document として
`descriptor_match: false` に落ちていた — 自分で書き出した promotable 記述子を
自分の eval fold が読めない非対称。本スライスで fold を拡張した。

**実装エビデンス**:

1. **closed-shape の第二メンバー** — `agent/core_evidence.py` の
   `evaluate_core_acceptance` が conjunctive 記述子を独自の閉じた形状で判定する
   （`_requirement_list_acceptance_match`）。`verdict ∈ {accepted, rejected,
   inconclusive}` が `accepted` Boolean の代わりになり、評価の `accepted` は
   `verdict == "accepted"` のときだけ立つ。`requirements` / `records` /
   `checks` / `conflicts` の入れ子も Core が emit する同一形状まで検証し、
   未知フィールド・欠落フィールド・型違いは全て match=false。
2. **pin と evidence schema の整合** — `evidence_fingerprint` は
   `mumei.verification-evidence/v1`、`list_fingerprint` は
   `mumei.verification-evidence-list/v1` と必ずペア。両方存在・両方欠落・
   pin/schema の組合せ違いは foreign document であって別解釈ではない。
3. **attempt binding は pin 非依存** — `attempt_bound` は引き続き
   `evidence_fingerprint` との指紋一致のみ。list-pinned 記述子は単一レコードの
   attempt にバインドできず `attempt_bound: false` と正直に報告する（エラーでは
   ない）。`_BINDING_CARRIERS` にも conjunctive スキーマを `evidence_fingerprint`
   carrier として登録し、`binding-eval` の `shared:` bind-path がそのまま解決する
   （list-pinned は carrier 不在で fail-closed）。
4. **read bound の引き上げ** — conjunctive 記述子は per-requirement per-record の
   結果を繰り返すため Core 側で 4 MiB 上限（`MAX_ACCEPTANCE_DESCRIPTOR_BYTES`）。
   `evidence-acceptance-eval` と `binding-eval` の読み取り上限を同じ 4 MiB に揃えた。
   verdict 昇格・Core チェック・新しい claim は一切追加しない representation-level
   の拡張であり、`checks_not_performed` は不変。

**回帰ゲート**: `uv run pytest tests/test_evidence_acceptance_eval.py tests/test_binding_eval.py tests/test_contract_vocabulary.py tests/test_mcp_evidence_tools.py -q`

## C11 evidence-acceptance-eval: requirement-evaluated verdict 記述子 family 完結 — ✅ Implemented

canonical 上位ロードマップは mumei `docs/CROSS_PROJECT_ROADMAP.md` の C11。
前スライスの conjunctive 記述子に続き、Core `accept*` が emit する残りの
verdict 形状を family に追加して coverage を完結させた。

**実装エビデンス**:

1. **`mumei.evidence-acceptance/v1`** — `evidence accept --requirement` が
   単一レコードに対して emit する verdict 記述子。閉じた形状（pin は
   `evidence_fingerprint` 固定、`evidence_schema_version` は
   `mumei.verification-evidence/v1` 固定、flat `checks` リスト）を
   `_evidence_acceptance_match` で判定。`_BINDING_CARRIERS` にも登録し
   `binding-eval` の `shared:` bind-path が解決する。
2. **`mumei.evidence-list-acceptance/v1`** — `evidence accept-list
   --requirement` が record-list envelope に対して emit。pin は
   `list_fingerprint` 固定、`records` は conjunctive と同じ閉じた
   `{index, verdict, checks}` 形状、consistency 報告（`consistent` /
   `conflict_count` / `conflicts`）を内包。record pin を持たないため
   carrier には登録しない（`attempt_bound: false` を正直に報告）。
3. **dispatch の一般化** — `evaluate_core_acceptance` は `schema_version`
   で verdict-matcher テーブル（`_VERDICT_ACCEPTANCE_MATCHERS`）に分岐し、
   flat source/native pair は従来経路のまま。評価の `accepted` は verdict
   形状では `verdict == "accepted"`、flat 形状では `accepted is True`。
   verdict 語彙 `{accepted, rejected, inconclusive}` の厳密判定は family
   全体で共有（`_verdict`）。
4. **実出力 golden fixture** — 実 mumei（debug build）が emit した
   `accept --requirement` / `accept-list --requirement` の記述子を
   `tests/fixtures/` に保存し、手書き fixture との drift を防ぐ回帰面にした。

**回帰ゲート**: `uv run pytest tests/test_evidence_acceptance_eval.py tests/test_binding_eval.py tests/test_contract_vocabulary.py tests/test_mcp_evidence_tools.py -q`

## C11 binding-eval: list-pinned acceptance descriptors の carrier 化 — ✅ Implemented

`binding-eval` が promotable gate triple の list 側を bind できるように、
`_BINDING_CARRIERS` を複数候補 subject field に一般化し、list pin carrier を
追加した。

- `mumei.evidence-list-acceptance/v1`（`accept-list --requirement` 出力）→
  `list_fingerprint` を carrier として登録 — 評価対象の list envelope bytes を
  pin する。
- `mumei.evidence-requirement-list-acceptance/v1`（conjunctive）→
  `evidence_fingerprint` と `list_fingerprint` の2候補 — descriptor 自身の
  schema が XOR を強制するため、record pin と list pin のどちらが来ても bind
  できる（`verify-schedule --export-evidence-acceptance` が書く triple の
  `acceptance.json` ↔ `evidence.json` の list 形を検査可能）。
- `mumei.evidence-acceptance/v1` → `evidence_fingerprint`（#1106 で carrier
  登録済みだったが binding-eval の回帰テストが未整備だったため併せて追加）。
- `subject_declared` は「候補のいずれかが well-formed digest」、`bound` は
  「declared subject のいずれかが `record_digest` と一致」。XOR schema では
  実質一意なので曖昧さなし。`carrier_authenticity` / `binding_enforcement`
  は従来どおり unperformed。
- 実 mumei（debug build）が emit した evidence list envelope
  （`tests/fixtures/evidence_list.json`）を golden fixture として追加し、
  既存の golden descriptor（`evidence_list_acceptance.json`・
  `evidence_requirement_list_acceptance_list_pin.json`）と route レベルで
  bind する回帰を追加。

representation-level のみ — verdict 昇格・grade promotion・Core check の
新規クレームなし。`binding-eval` は観測を出すだけで gating は host 側の
`mumei claims --require-evidence-acceptance` に委ねる設計のまま。

**回帰ゲート**: `uv run pytest tests/test_binding_eval.py tests/test_evidence_acceptance_eval.py tests/test_contract_vocabulary.py -q`

## C11 recovery-eval: descriptor_authenticity の performer — ✅ Implemented

`mumei.core-acceptance-evaluation/v1` が宣言する
`descriptor_authenticity`（**評価対象 descriptor** の真正性）を、
`mumei.signature-verification/v1` の `signature_valid` + `key_pinned`
（`subject_digest` carrier）で回収する performer 登録を追加。

- eval doc は `descriptor_digest`（評価対象 descriptor の raw bytes の
  SHA-256、route が再計算）を emit — eval doc 自身の bytes ではなく
  評価対象を名指す declared carrier。`_record_bound_digest` と
  `_BINDING_CARRIERS` に `descriptor_digest` を登録し、署名対象が
  descriptor bytes であるときだけ verification doc が bind される。
- `producer_authenticity` と同一の performer 形状（signed + caller-pinned
  producer key；key 自体の authenticity は別チェックのまま）。
- **eval doc 自身への署名では回収しない**（bind 先が descriptor digest
  なので evidence_failed）— Devin Review の指摘（eval doc の署名で
  descriptor の真正性が誤認 recovered になる）を反映。
- unpinned key・失敗署名・別 bytes への bind も `evidence_failed`。
- e2e: 実 mumei `evidence sign` で descriptor に署名 → `signature-verify`
  → `recovery-eval` で `descriptor_authenticity: recovered` を確認。
- 残る performer なし check は設計上 unrecoverable:
  `unperformed_check_recovery`（自己回収の無限後退を回避）、
  `independent_model_correspondence` / `tool_execution`（Core 領域）、
  `grade_promotion`（demand gate）。

representation-level のみ — verdict 昇格・grade promotion・Core check の
新規クレームなし。

**回帰ゲート**: `uv run pytest tests/test_recovery_eval.py tests/test_binding_eval.py tests/test_evidence_acceptance_eval.py tests/test_contract_vocabulary.py -q`

### C06 second compiler-backed Solidity binding slice — IdentifierPath

`agent/sol_compiler_snapshot.py` now also captures `IdentifierPath`
references — the 0.8.39 AST path form carrying inheritance specifiers
(`is Base`), `using ... for` lists and user-defined type names (the
older `UserDefinedTypeName` node no longer appears; its inner `pathNode`
is itself an `IdentifierPath` and is covered without double counting).
The envelope shape, pinned-version allowlist and fail-closed boundary
(imports, inline assembly) are unchanged — the reader still launches no
compiler and emits metadata only.

A dotted path such as `Lib.S` resolves atomically to one declaration on
the compiler side while the lexical report records only the base
segment's reference, so the whole-path span honestly compares as
`lexical_missing` — no path semantics are invented to force agreement.
`MemberAccess` member names stay uncaptured because the lexical report
never resolves them (member names would compare `lexical_missing` on
every hit — noise, not signal).

Fixture `inheritance_override` now yields two `agree` references: the
`is Base` path and the `hook()` call (which resolves to the override).
metadata only — no trust, audit, Evidence acceptance, Seal Grade, ABI,
runtime or proof claim.

**回帰ゲート**: `uv run pytest tests/test_sol_compiler_snapshot.py tests/test_sol_bindings.py -q`

### C06 Solidity compiler fixture — block-scope shadowing and reassignment

`tests/fixtures/solc/block_scope_shadowing.sol` (envelope regenerated with
the pinned solc 0.8.39 binary, SHA-256 verified against the fixture
README) exercises the acceptance criterion's shadowing/reassignment
requirement for Solidity: a block-local `count` shadows the state
variable — block reads/writes bind to the inner declaration while
references before and after the block bind to the state variable — and
a `local` reassignment keeps one declaration identity. All eight
references compare `agree`. Fixture registered in
`tests/fixtures/solc/regenerate.py`. Metadata comparison only — no new
capture surface, route or claim.

**回帰ゲート**: `uv run pytest tests/test_sol_compiler_snapshot.py -q`
### C06 lexical member access — contract-typed member resolution

`agent/sol_bindings.py` `_resolve_member` resolves
`object.property` when the object is an identifier whose declared type
is a contract/interface/library or names one directly (`Lib.f`,
`token.transfer` resolving through `type_id` on the declared type,
`this.` against the current contract and `super.` across declared
bases in linearization order). Member reads record `read`/`call` references against
the resolved member binding and member calls classify with the same
honest kinds as direct calls (`direct_local`, `opaque_bodyless`,
`opaque_virtual`, `opaque_call_options`, `opaque_value`). Private
members are visible only inside the declaring contract (`this.` and
instances of the current contract); `super.` and other instances
report `private_base_member`. Struct fields, enum members and builtin
members (`.length`, `.balance`, `.push`) stay opaque by design — they
are not bindings, so the position keeps its previous `opaque_member`
call and silent-member treatment rather than inventing identities.
`import`-bound module objects and unresolved bases are unchanged.

The compiler snapshot intentionally still does not capture
`MemberAccess` member names, so member references produced here have
no compiler counterpart yet — the honest next slice captures
`MemberAccess` spans in `agent/sol_compiler_snapshot.py` and compares
the member declarations.

**回帰ゲート**: `uv run pytest tests/test_sol_bindings.py tests/test_lexical_bindings.py -q`
### C06 lexical member access — `using Lib for T` directives

`agent/sol_bindings.py` `_resolve_member` now falls back to
`using`-directive resolution when the contract-type path finds no
member: contract-body and file-level `using Lib for T` / `for *`
directives are collected per contract and the member is looked up in
the named library's scope when the object's declared type text equals
the `for` target (bare `uint`/`int`/`byte` spellings normalize to
their canonical widths — `uint`/`int` are `uint256`/`int256`, `byte`
is `bytes1`; dynamic `bytes` is distinct). Member resolution also
follows non-identifier objects: array
elements of contract arrays (`tokens[0].transfer`), call returns and
constructors/casts (`getToken().transfer`, `Token(addr).transfer`)
resolve against the value's declared contract type (`new Token().f`
via the `new_expression` type name, `this.token().f` via the public
getter's declared variable type). The `using` fallback names the
receiver's declared type the same way, so directives also apply to
array elements (`values[0].add`), member chains (`coin.v.add`), call
returns (`getTotal().add`) and chained library calls
(`total.add(1).sub(2)`); receivers whose type cannot be named
statically (function-typed returns, exploded struct tuples) keep
their opaque treatment. `mapping(K => V)` index access is
V-typed — `balances[msg.sender].add(1)` binds the extension and a
public mapping getter (`this.balances(k).add(1)`) peels the same
way. Indexing nests recursively: `nested[k1]` on
`mapping(K => mapping(L => V))` is mapping-typed (a `for *` or
mapping-parameter extension can still apply) and `nested[k1][k2]`
resolves to `V`; array indexing peels one dimension, so
`grid[0][0]` on `uint256[][]` is `uint256`-typed while `grid[0]`
stays `uint256[]`. A `mapping(K => U slot)` declaration names the
value slot — the name is not part of the type — and a public
getter returning a struct value yields the exploded tuple
(opaque) while an enum value comes back as the enum type itself.
A derived contract value implicitly converts to a base-contract
parameter when argument types resolve a candidate set. When `x.f(...)` is a
call, member overloads and all applicable `using` extensions form a
single candidate set resolved by argument types — the extension's
first (receiver) parameter is skipped, literal ints/bools/strings
match by kind (a numeric literal converts to every integer width, so
`t.f(1)` across `f(uint8)`/`f(uint256)` stays ambiguous), typed
arguments use widening-only implicit conversion (`uint8`→`uint256`,
`uintN`→`intM` needs strictly more width, `bytesN`→`bytesM`/`bytes`,
`address payable`→`address`), and a unique survivor binds — including
an extension that wins because no member overload can take the
arguments (solc-verified: `inst.f("x")` with only `f(uint256)`/
`f(address)` members binds `f(D,string)` via `using`). A candidate
set with zero or tied survivors reports `ambiguous_overload` rather
than binding the first match; a member that exists but is private
reports
`private_base_member`, and the library identifier inside the directive
emits a `read` reference like any other type name. The aliased
form `using {f as g} for T` fails parse at the grammar level, so the
whole source stays fail-closed rather than resolving half of it.
Member objects on non-contract types,
function-typed returns (`returns (function() ...)`), function-typed
variables, array `new` expressions and non-call member positions
(`x.f` as a value, where a lone candidate binds by name only) keep
their opaque treatment. `this.f(...)` and `super.f(...)` never reach
`using` — solc does not apply directives through `this` or `super`
(verified: `this.v.ext()` under `using S for uint256` errors); only
the member overload set is argument-resolved there. Struct fields and enum members are now
first-class bindings (`struct_field`, `enum_member` kinds): the
declaration's members attach to the struct/enum type record and
member access resolves them on variables, member chains
(`coin.t.transfer`), struct-array elements (`coins[0].v`), call
returns (`getCoin().v`), struct-constructor values (`Coin(...).v`),
qualified enum literals (`Status.Ready`, `Container.State.On`) and
nested type names (`Container.State` resolves the enum declaration).
Enum constants only bind through the type name: an enum-typed value
member (`status.Ready()`) prefers a `using` extension, matching
solc. A struct-typed public getter returns the exploded fields, not
the struct, so its member position stays opaque. Writes through a
member chain emit the member's own `write` reference (read+write for
compound updates) matching the compiler's MemberAccess
referencedDeclaration list; assigning a non-assignable member
(enum constant, function) records `unsupported_syntax` + read like
the identifier rule. A qualified type name in a declaration
annotation (`Container.State cst`) still only emits the root
identifier — the type-position member is recorded `lexical_missing`
in the fixture comparison.

**回帰ゲート**: `uv run pytest tests/test_sol_bindings.py tests/test_sol_compiler_snapshot.py -q`
### C06 second compiler-backed Solidity binding slice — MemberAccess

`agent/sol_compiler_snapshot.py` now captures `MemberAccess` member
names from the pinned solc 0.8.39 AST: `memberLocation` is the
member-name span and `referencedDeclaration` points at the member's
declaration for contract members (`token.transfer`, `token.supply`),
while builtins (`.length`, `.push`, `msg.sender`) carry no
`referencedDeclaration` and record as builtin references. The
`member_access.sol` fixture exercises member calls, a public getter,
builtin members, reassignment, `this.`/`super.`/inherited member
calls, a `using SafeMath for uint256` member call and a file-level
`using Stamps for Coin global` call, contract-array element calls,
call returns, `new Token()` and public-getter calls, struct-field
reads/writes (`coin.v`, `coins[0].v`, `coin.v += 1`), member chains
(`coin.t.transfer`), a struct-constructor member (`Coin(...).v`),
an enum literal (`Status.Ready`) and a qualified enum literal
(`Container.State.On`): 59 `agree`, 6 `builtin` and one
`lexical_missing` (the qualified type name inside the declaration
annotation) statuses against the lexical report's member resolution. Envelope shape, pinned-version allowlist
and fail-closed boundary are unchanged. Metadata comparison only — no
new capture surface, route or claim.

**回帰ゲート**: `uv run pytest tests/test_sol_compiler_snapshot.py -q`
