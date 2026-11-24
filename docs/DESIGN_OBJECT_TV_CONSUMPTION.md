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

---

## Object-stage acceptance producer survey (audit backlog item 4)

Survey of the agent side ahead of Core's `DESIGN_OBJECT_ACCEPTANCE.md`
producer design. Recorded so the producer's emitted descriptor can be
checked against the consumption conditions below; no code change is
required by the survey itself.

### 1. Current `native-object-accept` inventory (landed, #1081)

The route dispatches `<core> native-bundle accept-object
--expected-build-id <id> --json <bundle> <source>` inside the C11 dispatch
lifecycle: the request fingerprint binds the Core executable hash, every
declared bundle member hash, the source hash, and the trusted-channel
build ID; exactly one fresh attempt is dispatched; declared inputs are
re-hashed after exit (drift invalidates the result); the reconciled
sequence is published compare-and-set.

What the route folds as acceptance metadata — only when exit code is 0,
no input drift occurred, and the stdout descriptor passes
`_valid_acceptance_descriptor`: `acceptance: "accepted"`, the schema
name, `scope`, `llvm_sha256`/`object_sha256`, bounded
`register_convention_assumed`/`input_domain` strings, aggregated
`function_outcomes`, and a `discharged_checks` list computed as
`DischargedChecks.ACCEPTED ∪ (checks_performed ∩ OBJECT_ACCEPT_CHECKS) ∪
{object_translation_correspondence}`.

Current `object_translation_correspondence` claim boundary: the check is
discharged only under a valid descriptor that lists Core's
`object_source_machine_code_correspondence` in `checks_performed`
(Core does not emit the agent name — the route maps it). The claim is
profile-bounded source-to-object machine-code correspondence, not
universal object TV: machine-TV assumption markers are never discharged
even if listed; scope ↔ `object_link_correspondence` membership must be
consistent; no CRT/loader/ABI/runtime/OS-exit-status claim; no evidence
candidate, certificate, grade promotion, or recovery performer.

Descriptor shape the route requires: schema
`mumei.native-evidence-acceptance/v1`, `acceptance: "evaluated"`,
`accepted: true`, `build_id` equal to the declared expected pin, `scope`
in {`native_bundle_object_machine_code_translation_correspondence`,
`..._without_object_link`}, both check fields string lists,
`object_source_machine_code_correspondence ∈ checks_performed`,
`object_link_correspondence` membership ⇔ with-link scope, disjoint
performed/not-performed, valid `llvm_sha256`/`object_sha256`
fingerprints. This is a minimum-requirement check, not a closed shape —
`_valid_acceptance_descriptor` ignores fields it does not name, whereas
`evaluate_core_acceptance`'s stored-carrier fold rejects any field
outside its admitted set; the producer should not assume the two routes
share one acceptance condition.

### 2. Agent-fold requirements for a Core object-stage acceptance
   descriptor emitted as a stored carrier

The route's current consumption gets three things free from the dispatch
lifecycle that a stored descriptor does not carry: freshness (the
descriptor came out of *this* attempt), input binding (the fingerprint
re-hash ties it to declared inputs), and producer identity (the Core
executable hash is in the fingerprint). Folding a persisted descriptor
through the `evidence-acceptance-eval` family (#1105–#1107 patterns)
enumerates these requirements:

1. **Carrier registration.** `mumei.native-evidence-acceptance/v1` is
   already in `CORE_ACCEPTANCE_SCHEMAS` and the eval route folds it
   representationally (closed shape via
   `_CORE_ACCEPTANCE_REQUIRED_FIELDS` + `_NATIVE_ACCEPTANCE_EXTRA_FIELDS`:
   `invocation`, `host`, `pin_envelope`, `build_id`, `llvm_sha256`,
   `object_sha256`, `register_convention_assumed`, `input_domain`,
   `functions`). A new schema name would need registration there and in
   the eval's matcher table.
2. **Digest pins.** `build_id`, `llvm_sha256`, `object_sha256` already
   pin the compared artifacts; the route additionally pins the caller's
   `expected_build_id`. The eval's `attempt_bound` compares
   `expected_fingerprint` only against `evidence_fingerprint` /
   `sidecar_fingerprint` — neither exists on the object descriptor, so a
   stored object descriptor reports `attempt_bound: false` unless Core
   also emits a record pin over the acceptance subject.
3. **Signature rules.** `producer_signature` /
   `produced_at_signed` extras are admitted only on
   `mumei.source-evidence-acceptance/v1`
   (`_PRODUCER_SIGNATURE_DESCRIPTOR_EXTRAS`); the native schema admits
   neither. For the descriptor to travel as a signed carrier
   (`signature-verify` binding via `subject_digest`), Core must emit it
   as a persisted document AND the extras must be admitted on this
   schema — or the signature binds the descriptor through a separate
   carrier, the way `descriptor_digest` on the eval doc already names
   the assessed bytes.
4. **Scope and check vocabulary.** Unchanged: `scope` names the bounded
   claim, `checks_performed`/`checks_not_performed` bound what any
   consumer may credit; the agent never discharges
   `MACHINE_TV_ASSUMPTION_MARKERS` even if listed, and
   `object_translation_correspondence` stays agent-owned vocabulary the
   Core descriptor does not spell.
5. **Freshness/authenticity boundary.** Stored-carrier folds are
   representation-level: `descriptor_authenticity`,
   `descriptor_freshness`, `unperformed_check_recovery` stay in
   `checks_not_performed` — a stored descriptor can describe an
   acceptance but cannot by itself prove this attempt produced it.

### 3. Overlap with Core's design memo

Once `DESIGN_OBJECT_ACCEPTANCE.md` lands, each producer-side decision
(schema name, pinned fields, signature envelope, freshness marker) maps
to one enumerated consumption condition above; the corresponding
agent-side adoption is a small slice: extend `_NATIVE_ACCEPTANCE_EXTRA_FIELDS`
or the per-schema extras, wire `attempt_bound` if a record pin is added,
and admit `producer_signature` on the native schema only when Core signs
the descriptor document.

### 4. Producer decision mapping (`DESIGN_OBJECT_ACCEPTANCE.md` landed,
   mumei#1433)

Core's memo is now landed; each producer-side decision maps to one
consumption condition above. Decisions (a)–(g) refer to its §7.

| Producer decision | Agent-side consumption condition | Required agent change |
| --- | --- | --- |
| Schema stays `mumei.native-evidence-acceptance/v1` (§5) | Carrier registration (§2.1) | None — already in `CORE_ACCEPTANCE_SCHEMAS` |
| New scope `native_bundle_object_translation_correspondence` (+ `_without_object_link`); old scope stays readable (§5, c) | Scope vocabulary (§2.4); route scope allowlist | `_valid_acceptance_descriptor`'s scope set must admit the new value (both link variants) while keeping the machine-TV scope — order matters: the memo's §6 Step 3 requires the agent to accept both scopes *before* Core switches the emitted value, or valid new descriptors get rejected on scope mismatch. The scope↔`object_link_correspondence` consistency check must also cover both generations — admitting the new with-link scope alone would wrongly reject valid linked descriptors for carrying `object_link_correspondence`, and wrongly admit unlinked ones |
| `checks_performed` enumerates correspondence item names (`llvm_ir_object_equivalence`, `object_data_correspondence`, `object_symbol_attribute_correspondence`, `hir_llvm_model_correspondence`, relocation ×4, `function_coverage`, `function_count`) alongside the existing hard-gate names (§5) | Check vocabulary (§2.4); discharge computation | `OBJECT_ACCEPT_CHECKS` must include the correspondence item names so `checks_performed ∩ OBJECT_ACCEPT_CHECKS` credits them; the `{object_translation_correspondence}` discharge mapping widens from the single `object_source_machine_code_correspondence` name to the item set — matching the memo's §3.4 note that the 1:1 name mapping is stale. Because `OBJECT_ACCEPT_CHECKS` derives from the shared `OBJECT_CHECK_VOCABULARY` and `test_native_check_partitions` pins the accept and machine-TV recheck sets equal, the item names join the shared vocabulary (all three object routes may credit them when a descriptor lists them) rather than becoming accept-only additions — the partition contract stays unchanged |
| `accepted` now requires `correspondence.status == "checked_correspondence"` — all items checked, `inconsistent` → reject, `unchecked`/`unknown` → inconclusive, no descriptor on failure (§4, b) | Claim boundary (§1) | Semantic only: a folded `accepted: true` under the new scope already carries the stronger claim; the route's claim boundary text should be restated as "all correspondence items checked within the bounded profile" rather than the single machine-TV arc |
| `evidence_fingerprint`-style pin binding the whole `correspondence` record recommended (f) | Digest pins (§2.2); stored-carrier closed shape | Whatever field name Core picks must be added to `_NATIVE_ACCEPTANCE_EXTRA_FIELDS` or the stored fold rejects the descriptor. Whether it then doubles as the record pin `attempt_bound` needs depends on the name: `attempt_bound` compares `expected_fingerprint` only against `evidence_fingerprint`/`sidecar_fingerprint`, so the literal name `evidence_fingerprint` works with admission alone while any other name also needs the comparison set extended. The same §5 binding adds `executable_sha256` on with-link descriptors — it must be admitted too, or stored linked descriptors still fail the closed shape |
| `producer_signature`/`produced_at_signed` not emitted — producer authenticity stays `not_performed` (§3.6, §5) | Signature rules (§2.3) | None — `_PRODUCER_SIGNATURE_DESCRIPTOR_EXTRAS` stays source-schema-only; if a later memo signs the object descriptor, admitting the extras on the native schema is the small slice already enumerated |
| Core does not emit the agent-owned `object_translation_correspondence` name (e) | Agent-owned vocabulary (§2.4) | None — the mapping stays agent-side, as assumed |
| Stored-carrier path remains dispatch-lifecycle emission (§2 saved-evidence recheck notes the acceptance schema is unread by `evidence::decode`) | Freshness boundary (§2.5) | None for the direct route; any future *stored* object descriptor still folds representation-level only |

Net: the only blocking agent-side work is vocabulary — the new scope
values in `_valid_acceptance_descriptor` (with the link-consistency rule
covering both generations) and the correspondence item names in
`OBJECT_CHECK_VOCABULARY`, sequenced before Core's emit switch — plus
the fingerprint/`executable_sha256` field admissions once Core names
them. Everything else is either already satisfied or a semantic
restatement.

**回帰ゲート**: `uv run pytest tests/test_native_object_accept.py tests/test_core_evidence.py -q`
