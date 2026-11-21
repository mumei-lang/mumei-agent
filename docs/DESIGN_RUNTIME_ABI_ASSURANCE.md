# Design memo: runtime/ABI/final-binary assurance below the pinned LLVM snapshot

Part of the cross-project roadmap tracked in
[mumei-lang/mumei-agent#651](https://github.com/mumei-lang/mumei-agent/issues/651)
(C02/C10 deeper assurance layer). This memo is a design record only — no
production code.

## Background

The C10 consumer chain now covers every stage from a declared source to the
final executable, but each stage claims a different, strictly weaker thing:

- `native-bundle recheck-source` re-derives the source postcondition inside
  the declared profile — `claim_truth` at representation level.
- `recheck-llvm` re-runs translation validation between the verified source
  model and the pinned `program.ll` — `semantic_correspondence` /
  `artifact_semantics` at representation level.
- `recheck-artifact` rebuilds `program.o` and the executable byte-for-byte
  under the recorded toolchain — byte identity, i.e. *the same artifact*, not
  a semantic claim about what it does.
- `recheck-exit-status` / `recheck-stdout` / `recheck-stderr` execute the
  reproduced binary and compare pinned OS-level observations (exit status,
  bounded channel digests). Before Option A slice 1, these observations
  discharged no named runtime check.

The remaining research-level item in the C-roadmap is exactly that gap: the
**object/ABI/runtime/final-binary assurance chain**. The question this memo
answers: *what can an honest, declared check claim about the reproduced
binary's execution — below the pinned IR — without pretending byte
reproduction or one pinned invocation is a proof of runtime semantics?*

Concretely, the open sub-questions are:

1. Which execution facts are *checkable* (re-derivable from the record and
   the environment) rather than merely observable?
2. What vocabulary names the resulting checks honestly — distinguishing
   "one pinned invocation behaved X" from "the binary's ABI/runtime
   semantics are X"?
3. Where does the chain bottom out — what stays declared host duty forever
   (loader, libc, kernel, hardware)?

## Options evaluated

### Option A — observation-vocabulary extension (recommended)

Extend the declared-check vocabulary with a runtime-observation family and
give the existing pinned observations something honest to discharge:

- New check names in a dedicated `RUNTIME_CHECK_VOCABULARY` (kept separate
  from the C02 semantic six so existing `discharged_checks` surfaces do not
  silently change meaning):
  - `os_exit_status_observation` — a reproduced binary run under the pinned
    invocation exited with the record's `expected_exit_status`.
  - `os_stdout_observation` / `os_stderr_observation` — bounded channel
    digests matched `expected_stdout_sha256` / `expected_stderr_sha256`.
  - `runtime_observation_semantics` — the *conjunction*: all pinned
    channel observations of a reproduced binary hold on one fresh,
    resource-bounded invocation. The name says what it is: semantics of
    the recorded observations, not of the program.
- A sibling `mumei.runtime-observation/v1` record family, reserved for the
  Core slice, that folds the
  three existing `link_build` pins plus a declared invocation envelope
  (argument vector, empty/stdin bytes, `resource_limit`, `timeout_ms`)
  into one descriptor a consumer can recheck as a unit.
  `runtime_observation_semantics` remains unperformed until this descriptor
  exists. Slice 1 names each per-channel OS observation; accepted channel
  reports recover only their matching check when their bound carrier agrees,
  while fixed-diagnostic recheck reports are not performers.

Why this is honest: it claims *bounded observed behavior on one declared
invocation*, which is exactly what the pins already verify. It upgrades
an unnamed observation to a named, bounded, composable claim without
asserting anything about unseen inputs, other process states, or the ABI
itself.

### Option B — object-code translation validation

Extend the TV pipeline one stage further: validate correspondence between
the pinned `program.ll` and the emitted object code (instruction
selection, register allocation, relocation resolution) — e.g. a
machine-code-level equivalence check or an instruction-listing contract.

This is the only option that could someday claim real ABI semantics, but
it is a research project of its own (a verified binary-lifter or a
per-instruction TV profile), not a slice. Rejected as today's step; kept
as the named deep endpoint — see *Revisit triggers*.

### Option C — ABI contract conformance probing

Declare an `mumei.abi-contract/v1` descriptor naming the binary's external
interface (entry contract, exported symbol calling conventions, struct
layouts on the boundary) and probe the reproduced binary against it:
harness invocations that marshal declared inputs across the ABI and
compare declared outputs.

More semantic than Option A but strictly weaker than B, and costly: every
probed convention needs its own declared contract, and the harness becomes
part of the trusted base. The pure-i64 fragment today exposes almost no
ABI surface to probe (one `main`, no exports), so the check would mostly
re-derive what the pins already say. Rejected now; natural follow-on if
the profile ever admits exported functions or FFI.

### Option D — pinned execution-environment attestation

Pin the *environment* instead of the behavior: a declared execution
envelope (loader, libc version, kernel ABI surface, resource limits,
sandbox policy) under which the pinned observations are reproducible and
interpretable, so `runtime_observation_semantics` is scoped to a named
environment rather than "some host".

Worth doing *inside* Option A's invocation envelope (the envelope already
declares resource bounds; host facts like `uname` belong in the record as
observations, never claims) but it cannot stand alone — an attested
environment with no pinned behavior proves nothing. Folded into Option A;
rejected as a separate track.

## Recommended direction

Option A, staged:

1. **Slice 1 (agent-side, docs + vocabulary + fold):** reserve
   `mumei.runtime-observation/v1`, define `RUNTIME_CHECK_VOCABULARY`, and
   register the three native accept reports as performers of their
   respective channel observations. Extend all six routes to name only
   their observed channel check on success, keeping the other runtime
   checks unperformed. Do not register `runtime_observation_semantics`
   until Core emits its descriptor.
2. **Slice 2 (Core-side):** a `recheck-runtime` (or folded
   `recheck-observations`) subcommand that runs the reproduced binary once
   under the declared invocation envelope and emits the
   `runtime_observation_semantics` verdict — spawn-fail / timeout /
   signal / digested-overflow / pinless all honestly `inconclusive`,
   matching the per-channel commands.
3. **Slice 3 (composition):** acceptance descriptors move the observation
   checks into `checks_performed` only when the same run performed the
   observation — the symmetry rule the stdout/stderr slices already
   follow — and `recovery-eval` composes the new descriptor.

What stays declared host duty forever: loader/libc/kernel/hardware
correctness, temporal behavior beyond the declared bound, memory safety
of dynamically-linked code outside the profile, and anything Option B's
object-code TV would be needed to claim.

## Rejected alternatives

Option B (object-code TV) is the eventual ceiling but is out of slice
scope. Option C (ABI contract probing) costs a trusted harness for almost
no checkable surface under today's profile. Option D (environment
attestation) is absorbed into Option A's invocation envelope.

## Revisit triggers

- The bundle profile admits exported functions, FFI or dynamic linking →
  Option C becomes checkable and this memo's boundary must be redrawn.
- An instruction-level lifter or machine-code TV profile becomes
  available → Option B replaces the observation layer as the honest
  `abi_runtime_semantics` claim.
- Multiple pinned invocations (argv/env matrices) enter the record →
  `runtime_observation_semantics` splits into per-invocation checks.

## Minimal first implementation slice

Status: Slice 1 has landed agent-side; Core recheck-runtime and acceptance composition remain.

Slice 1 alone is self-contained and agent-side:

- `agent/core_evidence.py`: reserve the
  `mumei.runtime-observation/v1` schema name for the later Core slice and
  add `RUNTIME_CHECK_VOCABULARY` (`os_exit_status_observation`,
  `os_stdout_observation`, `os_stderr_observation`,
  `runtime_observation_semantics`). The three OS-observation checks are
  bound to their native accept reports; `runtime_observation_semantics`
  has no performer until Core emits its descriptor.
- `agent/native_exit_status_recheck.py` and the five sibling
  observation routes: emit the observation check name in
  `discharged_checks` on `reproduced`/`accepted`, and list the rest of
  the runtime family in `checks_not_performed` — replacing today's
  previously unnamed posture with the honest named claim.
- Regression tests: a reproduced run discharges exactly its channel's
  observation check and no sibling's; inconclusive and drifted runs keep
  the whole runtime family not-performed; `recovery-eval` composes each
  bound native accept report into only its channel check, while
  `runtime_observation_semantics` stays unperformed until the Core slice.

Nothing here changes a grade, a Lean gate, an audit verdict or a default
route — it gives the pipeline's existing, already-verified OS
observations a name the evidence vocabulary can carry.

---

## 補足（日本語）

- このメモが対象にするのは issue #651 の残 research 項目のうち
  「object/ABI/runtime/final-binary 保証チェーン」一つだけ。C12 demand
  gate、C08 trust-anchor 深層（rotation/revocation）、Go 深層解析残層は
  別件として扱う。
- 推奨は Option A。「1回の宣言済み起動での観測」しか主張しない命名
  （`runtime_observation_semantics`）に留めるのが、既存の正直性ルール
  （各 descriptor が実際に行った検査だけを主張する対称ルール）と整合する。
- Option B（オブジェクトコード TV）だけが真の ABI 意味論を主張できるが、
  それは別の研究プロジェクトであり、本スライスの範囲外。revisit trigger
  として明示した。
