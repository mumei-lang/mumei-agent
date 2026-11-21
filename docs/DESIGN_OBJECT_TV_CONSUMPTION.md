# Design memo: agent-side consumption of object-code translation validation (C10 Option B)

Part of the cross-project roadmap tracked in
[mumei-lang/mumei-agent#651](https://github.com/mumei-lang/mumei-agent/issues/651)
(C09/C10 deeper assurance layer). Companion to
[`DESIGN_RUNTIME_ABI_ASSURANCE.md`](DESIGN_RUNTIME_ABI_ASSURANCE.md), which
kept Option B (object-code translation validation, "object TV") as the named
deep endpoint. This memo records the agent-side consumption boundary for
landed Core commands and reports; Core owns the producer side.

## Status

Core has landed `native-bundle recheck-object` and the
`mumei.object-symbol-correspondence/v1` descriptor for bounded symbol-surface,
direct-call-edge and object-to-executable linked-placement correspondence.
The agent's `native-object-recheck` route discharges only bounded checks
listed in a descriptor with the matching schema and build ID; it does not
infer `object_link_correspondence` from an older Core's exit code. The route
is not a recovery performer. Core #1228 added `native-bundle accept-object`;
the agent's `native-object-accept` route validates its acceptance descriptor
and maps Core's `object_source_machine_code_correspondence` to the
agent-owned `object_translation_correspondence`. The route is the acceptance
route for this bounded check, but is not a recovery performer.

Core has also landed `native-bundle recheck-machine-tv` and its
`mumei.machine-code-tv/v1` descriptor. The agent's
`native-machine-tv-recheck` route consumes only descriptor-listed checks for
leaf straight-line, bounded forward-branch, and acyclic backward-branch
pure-i64 functions under an assumed, not validated, register convention.
Direct calls, including calls inside branching functions, are compared as
uninterpreted call sites; conditional-call functions use per-path guarded call
matching. Core #1210 adds `machine_code_conditional_call_function_tv`, and
Core #1227 adds `machine_code_bounded_loop_function_tv`; both are consumed
only when listed in `checks_performed`. Core uses `LOOP_BOUND=4` for bounded
loops, with `_and_loops_exiting_within_bound_4` in the input-domain string.
Executions beyond the bound, cancellation/runtime semantics and other cyclic
control flow remain outside the profile. For `native-machine-tv-recheck`,
`object_translation_correspondence` stays unperformed; that route is not an
ABI, runtime or full object-TV claim and is not a recovery performer.
The native-object-accept route does not promote a grade, emit reusable
Evidence or a certificate. Core #1230 adds
`machine_code_entry_wrapper_tv`, consumed by machine-TV recheck and object
acceptance only when a matching valid descriptor lists it in
`checks_performed`. It applies only when the object defines both `main` and
`__mumei_user_main` and the user-main source signature is supported; it checks
one unconditional call from `main` to `__mumei_user_main`, returning the low
32 bits of its result. This does not cover broader C entry-wrapper, CRT,
loader, ABI or runtime behavior. `os_exit_status_observation` remains a
separate runtime-observation check and is not discharged by this check.
ABI/runtime semantics, optimizer semantics, producer authenticity and
historical execution also remain outside the claim.

Core #1229 adds
`machine_code_callee_saved_register_preservation`, consumed only when listed
in `checks_performed`. It is performed only when at least one function is
Equivalent and all Equivalent functions are proved to preserve callee-saved
registers; each Equivalent function reports `preserved`, `violated`, or
`unknown`, and the agent aggregates those counts without function names.
Direct callees and the cancellation poll are assumed to preserve
callee-saved registers; external callees remain an assumption, and Core's
`machine_code_callee_saved_preservation_assumed_for_external_callees` marker
remains not performed. The argument/result register convention is still
assumed, not validated. This is not an ABI-correctness, runtime, or full
object-TV claim.

#### Core #1230 entry-wrapper machine-code TV

`machine_code_entry_wrapper_tv` checks only Core's modeled C entry wrapper:
when both object symbols exist and `__mumei_user_main` has a supported source
signature, `main` makes one unconditional call to `__mumei_user_main` and
returns the low 32 bits of its result. The agent consumes the check only when
a valid matching descriptor lists it in `checks_performed`; the
native-object-recheck route always leaves it unperformed. The aggregate
function-outcome and callee-saved-preservation counts include the wrapper
entry when Core reports it, without exposing function names.

This does not establish CRT, loader, OS exit-status, ABI, or runtime
semantics. `os_exit_status_observation` remains a separate
runtime-observation check and is not discharged by entry-wrapper TV. Core's
`object_entry_wrapper_semantics` not-performed marker is Core-only and is not
added to the agent vocabulary.

#### Core #1233 scalar-f64 machine-code TV

`machine_code_f64_scalar_function_tv` is consumed by machine-TV recheck and
object acceptance only when a valid matching descriptor lists it in
`checks_performed`. It covers scalar-f64 functions only under Core's f64
profile, with XMM argument/result registers assumed rather than validated.
MXCSR RNE, masked exceptions, FTZ/DAZ-off assumptions and NaN payload bits
remain unestablished and not performed; the agent never discharges
`machine_code_tv_mxcsr_control_state` or `machine_code_tv_nan_payload_bits`,
even if a descriptor lists them as performed. Direct-call f64 arguments are
admitted only under Core's exact-bits obligation (NaN-aware match, then an
exact-bit proof against the XMM argument); computed f64 arguments without
provably identical bits and f64 tail calls fail closed. Native-object-recheck
never discharges machine-TV checks. This establishes no IEEE-754 conformance,
ABI, runtime, or full object-TV claim.

#### Core #1241/#1242/#1243/#1244 composite aggregate register machine-code TV

Core's `machine_code_composite_register_aggregate_tv` is consumed only when
listed in `checks_performed`; it covers one- through four-leaf struct
parameters, results and direct-call struct values with integer and/or f64
leaves. One- and two-leaf values use Core's existing assumed SysV eightbyte
convention; integer arguments use rdi–r9 and f64 arguments xmm0–xmm7, with
the whole aggregate fitting and never split or stack-passed. Aggregate
results are limited to three integer leaves in rax/rdx/rcx and two f64 leaves
in xmm0/xmm1. Aggregates wider than two leaves assume LLVM first-class
aggregate register lowering, not SysV C-ABI classification, and
`machine_code_tv_sysv_memory_class_aggregate_abi` stays not performed. This
makes no ABI, runtime or full object-TV claim.

## Background

What exists today (verified against mumei `develop` and this repo):

- Core's C09 validator `validate_native_module` checks the verified source
  model against the pinned merged **pre-optimization LLVM IR** and emits the
  advisory `mumei.translation-validation-report/v1` record (`profile`,
  `source_profile`, `target`, `data_layout`, `checked_stage`, `input_domain`,
  `source_sha256`, `llvm_sha256`, `timeout_ms`, `resource_limit`, optional
  `unroll_bound`, per-function `outcome`, aggregate `outcome` ∈
  {`equivalent_within_profile`, `different`, `undefined_behavior`,
  `inconclusive`}). Today `checked_stage` is always `"llvm"`.
- `native-bundle recheck-llvm` re-derives that correspondence for a bundle;
  the agent's `native-recheck` / `native-accept` routes discharge
  `artifact_semantics` + `claim_truth` from it — at LLVM level.
- `native-bundle recheck-artifact` rebuilds `program.o` and the executable
  byte-for-byte under the recorded toolchain. That is **identity**, not
  correspondence: it proves the same bytes come out, not that the object
  computes what `program.ll` says.
- Option A (landed) names bounded OS observations of one invocation of the
  reproduced executable (`RUNTIME_CHECK_VOCABULARY`).

So between `program.ll` and `program.o` the chain has a hole: instruction
selection, register allocation, and relocation emission are trusted (LLVM 17
codegen is in the trusted base), and no agent vocabulary says so explicitly.
The C02 checks `artifact_semantics` / `semantic_correspondence` currently mean
*source ↔ LLVM*; reusing them for *LLVM ↔ object* would silently change the
meaning of every existing performer.

The question this memo answers: *when Core eventually emits an object-level TV
observation, which agent route, vocabulary and report consume it — and what
can the agent honestly do before that?*

## Requirements

1. No existing check changes meaning; no existing performer gains a claim.
2. The object-level claim is scoped exactly like the LLVM one: bounded profile,
   pinned target/data layout, budgets, exact input/output hashes, and an
   `inconclusive` that is never equivalence.
3. Composition through `recovery-eval` must not synthesize an end-to-end
   *source → executable* claim from separate stage reports (the lesson of
   `runtime_observation_semantics`: a conjunction is only a claim when one
   run observed it).
4. Fail closed on absence, unknown schema, profile/stage mismatch, drift, and
   every ambiguous exit code.
5. No ABI, calling-convention, loader, linker or runtime claim.

## Options evaluated

### Option 1 — reuse `artifact_semantics` for object TV

Let an object-TV report perform `artifact_semantics`. Cheapest, but violates
requirement 1: a record whose `artifact_semantics` was recovered from an LLVM
recheck and one recovered from an object TV would be indistinguishable.
Rejected.

### Option 2 — dedicated object-check vocabulary (recommended)

A third, separate family next to `CHECK_VOCABULARY` and
`RUNTIME_CHECK_VOCABULARY`:

```python
OBJECT_CHECK_VOCABULARY = frozenset({"object_translation_correspondence"})
```

`object_translation_correspondence` — *the pinned `program.o` text for the
profiled functions corresponds to the pinned `program.ll` within the declared
object-TV profile, target, data layout and budget*. It says nothing about the
linker, the C `main` wrapper beyond its screened shape, relocations resolved at
link time, the loader, or the ABI.

Consumption surface (mirrors the Option A split between accept and recheck):

| Agent route | Core command | Report schema | Acceptance route? |
|---|---|---|---|
| `native-object-recheck` | `native-bundle recheck-object --json` | `mumei.native-object-recheck-report/v1` | No — recheck reports never perform |
| `native-object-accept` | `native-bundle accept-object --expected-build-id <id> --json` | `mumei.native-object-accept-report/v1` | Yes — maps Core's source/object check to `object_translation_correspondence`; not a recovery performer |

Both routes run inside the existing C11 dispatch lifecycle (declared request
fingerprint over Core bytes + declared bundle members + source + trusted-channel
build ID, one reserved attempt, compare-and-set publication), reuse the native
exit-code map `{0: equivalent/accepted, 3: inconclusive}`, leave exit 1
unclaimed, re-hash inputs after the run and report `inputs_changed` on drift —
exactly as `native-recheck` / `native-observations-accept` do today.

Core's `accept-object --json` emits the
`mumei.native-evidence-acceptance/v1` descriptor. The agent requires the
evaluated/accepted outcome, expected build ID, one of the two object acceptance
scopes, Core's source/object correspondence check, scope-consistent link
correspondence, disjoint performed/not-performed lists, and lowercase
SHA-256 digests for both LLVM and object bytes.
`object_translation_correspondence` is discharged only from Core's
`object_source_machine_code_correspondence`; the agent-owned name in Core
output is not sufficient.

`object_translation_correspondence` is intentionally not registered in
`agent.core_evidence._CHECK_PERFORMERS`: this anonymous acceptance report is
not a recovery performer and cannot recover sibling checks. The route reports
bounded descriptor strings and aggregate function-outcome counts only; it
never parses object files or exposes function names.

### Option 3 — one end-to-end `final_binary_semantics` check

Name a single source → executable check and let `recovery-eval` recover it when
source↔LLVM, LLVM↔object, artifact reproduction and observations are all
recovered. Violates requirement 3: four separate runs on possibly different
hosts are not one observation of the chain. Rejected; an end-to-end name is
only admissible from a single Core descriptor that binds every stage hash in one
run, and is not proposed here.

### Option 4 — agent-side object lifting

Have the agent disassemble `program.o` and run its own equivalence check.
Moves a large lifter into the agent's trusted base and duplicates Core's
validator. Rejected: Core owns semantic meaning and acceptance.

## Recommended direction

Option 2, staged:

1. **Slice 1 (agent, now, non-deferred):** reserve
   `OBJECT_CHECK_VOCABULARY = {"object_translation_correspondence"}` in
   `agent/core_evidence.py` with **no performer**, and list it in
   `checks_not_performed` of the routes whose claim stops exactly at that
   boundary — `native-artifact-recheck` (byte reproduction of `program.o`) and
   `native-accept` (`accept-artifact`). That turns the currently implicit
   trusted-codegen gap into a named, unperformed check and makes `recovery-eval`
   report it as `no_evidence` instead of not mentioning it. No other route's
   output changes, so no demo scenario pins break (the
   `native_artifact_recheck` / `native_accept` demos do not assert
   `checks_not_performed`). Tests: both routes list the check on every outcome
   and never discharge it; `recovery-eval` on such a record reports
   `no_evidence`; a foreign report self-reporting the check does not recover it;
   the three vocabularies are pairwise disjoint.
2. **Slice 2 (Core, other session):** object-stage TV in Core and the
   `recheck-object` / `accept-object` commands. Deferred on the agent side
   until it lands.
3. **Slice 3 (agent, after slice 2):** the two routes above, CLI + MCP, and a
   mumei-demo scenario including a C13 negative control (source↔LLVM accept +
   artifact reproduction never recover `object_translation_correspondence`).
   As landed, `native-object-accept` discharges the check in its own report
   but is **not** registered as a recovery performer (see Option 2 above);
   the earlier plan to register it in `_CHECK_PERFORMERS` was superseded.

What stays host duty forever: linker and relocation semantics at link time,
loader/libc/kernel/hardware, the ABI, and anything outside the object-TV
profile.

## Revisit triggers

- Core picks a different command or schema name → slice 3 adopts it; slice 1's
  vocabulary name is agent-owned and unaffected.
- Core emits one descriptor binding source, LLVM, object and executable hashes
  from one run → an end-to-end check may be named (Option 3's admissible form).
- The profile admits externs/FFI/exported functions → ABI probing
  (runtime memo Option C) must be redrawn alongside this.

---

## 補足（日本語）

- 目的: Core が将来出す object-code TV 観測を agent がどう受けるかを先に決め、
  既存語彙の意味を変えずに受け口を用意すること。
- `artifact_semantics` の流用（Option 1）は、既存の source↔LLVM の主張と
  LLVM↔object の主張が区別できなくなるため却下。新しい独立語彙
  `object_translation_correspondence` を置く。
- accept/recheck の分担は Option A と同じ。ただし着地した `native-object-accept`
  は自分のレポートでチェックを discharge するだけで、回収（performer）としては
  登録しない（当初の performer 登録案は撤回）。recheck も回収しない。
- 段階ごとの別レポートを合成して end-to-end の主張を作ることはしない
  （`runtime_observation_semantics` と同じ理由: 1回の実行で観測されたものだけが主張になる）。
- Core #1228 が `accept-object` と `mumei.native-evidence-acceptance/v1` を出し、
  agent はその名前をそのまま採用した（スライス3着地）。
- スライス1（語彙の予約と、境界ルートでの「未実施」明示）は先行して着地済み。
