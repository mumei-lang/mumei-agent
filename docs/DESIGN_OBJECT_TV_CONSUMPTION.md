# Design memo: agent-side consumption of object-code translation validation (C10 Option B)

Part of the cross-project roadmap tracked in
[mumei-lang/mumei-agent#651](https://github.com/mumei-lang/mumei-agent/issues/651)
(C09/C10 deeper assurance layer). Companion to
[`DESIGN_RUNTIME_ABI_ASSURANCE.md`](DESIGN_RUNTIME_ABI_ASSURANCE.md), which
kept Option B (object-code translation validation, "object TV") as the named
deep endpoint. This memo is a design record only — no production code. Core
owns the producer side; every Core command and field name below that does not
exist yet is a **hypothesis** the agent adopts verbatim from Core once it lands.

## Status

Core has landed `native-bundle recheck-object` and the
`mumei.object-symbol-correspondence/v1` descriptor for bounded symbol-surface,
direct-call-edge and object-to-executable linked-placement correspondence.
The agent's `native-object-recheck` route discharges only bounded checks
listed in a descriptor with the matching schema and build ID; it does not
infer `object_link_correspondence` from an older Core's exit code. The route
is not a recovery performer.
`accept-object`, full object translation validation, and the
`object_translation_correspondence` performer remain deferred until Core
provides that deeper acceptance route.

Core has also landed `native-bundle recheck-machine-tv` and its
`mumei.machine-code-tv/v1` descriptor. The agent's
`native-machine-tv-recheck` route consumes only descriptor-listed checks for
leaf straight-line and bounded forward-branch pure-i64 functions under an
assumed register convention; direct calls are compared as uninterpreted call
sites. Backward branches and loops remain outside the profile. The route is
not an ABI, runtime or full object-TV claim and is not a recovery performer.
The C `main` wrapper, CRT, loader and libc remain outside the profile, so the
`object_translation_correspondence` performer and `accept-object` route
remain deferred.

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

| Agent route (future) | Core command (hypothesis) | Report schema | Performer? |
|---|---|---|---|
| `native-object-recheck` | `native-bundle recheck-object --json` | `mumei.native-object-recheck-report/v1` | No — recheck reports never perform |
| `native-object-accept` | `native-bundle accept-object --json` | `mumei.native-object-accept-report/v1` | Yes — `object_translation_correspondence` |

Both routes run inside the existing C11 dispatch lifecycle (declared request
fingerprint over Core bytes + declared bundle members + source + trusted-channel
build ID, one reserved attempt, compare-and-set publication), reuse the native
exit-code map `{0: equivalent/accepted, 3: inconclusive}`, leave exit 1
unclaimed, re-hash inputs after the run and report `inputs_changed` on drift —
exactly as `native-recheck` / `native-observations-accept` do today.

Expected Core descriptor: the existing `mumei.translation-validation-report/v1`
family with `checked_stage: "object"`, an object-level `profile`, and an added
`object_sha256` beside `llvm_sha256`. The agent keys on
`(schema_version, checked_stage, profile)` — never on `checked_stage` alone —
and treats any other combination as foreign. If Core instead introduces a new
schema name, the agent adopts it; no agent-invented schema is ever registered
as a performer.

`recovery-eval` registration (only once `native-object-accept` exists):

```python
"object_translation_correspondence": [
    ("mumei.native-object-accept-report/v1", "acceptance", "accepted",
     "normalized.stdout.sha256"),
    ("mumei.native-object-accept-report/v1", "acceptance", "accepted",
     "shared:expected_build_id"),
],
```

The `shared:expected_build_id` carrier lets a sibling native report for the
same bundle recover the object check, exactly like the channel observations.
Hash binding (`llvm_sha256` / `object_sha256` against the bundle pins) is Core's
job inside the accept command; the agent never parses object files.

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
3. **Slice 3 (agent, after slice 2):** the two routes above, CLI + MCP, the
   performer registration, and a mumei-demo scenario including a C13 negative
   control (source↔LLVM accept + artifact reproduction never recover
   `object_translation_correspondence`).

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
- accept/recheck の分担は Option A と同じ。回収（performer）できるのは accept
  レポートだけで、recheck は回収しない。
- 段階ごとの別レポートを合成して end-to-end の主張を作ることはしない
  （`runtime_observation_semantics` と同じ理由: 1回の実行で観測されたものだけが主張になる）。
- Core 側のコマンド名・スキーマ名は仮説扱い。Core が実装したら、その名前をそのまま採用する。
- 今すぐ agent 側でできるのはスライス1（語彙の予約と、境界ルートでの「未実施」明示）だけ。
  performer 登録は Core の実装後。
