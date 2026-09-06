# Lean fallback troubleshooting

`agent.proliferate` can escalate `z3_check_result == "unknown"` atoms to the
`mumei-lang/mumei-lean` bridge when `MUMEI_LEAN_REPO` points at a checkout that
contains `scripts/bridge.py`.

## Runtime flow

1. Unknown atoms are copied into a temporary `.proof-cert.json`.
2. `agent.lean_bridge.run_lean_bridge()` invokes
   `python <mumei-lean>/scripts/bridge.py --cert ... --lean-cert-out ...`.
3. For `std/math/abs.mm::abs_saturating`, the standard live generated path emits
   `Generated.Std.Math.Abs.abs_saturating_correct`, builds it with Lake, and
   merges `lean_verified` metadata with `known_witness_used = false`.
4. If another generated Lean module fails but a known std witness exists, the
   agent can still build that witness module and report the explicit fallback
   strategy.
5. (Opt-in, Task 2-D) With `--enable-lean-ai-proof` / `ENABLE_LEAN_AI_PROOF=1`,
   atoms still `unknown` after steps 3–4 are handed to
   `agent.lean_ai_proof.run_ai_proof_repair()`: the LLM writes a Lean module
   containing `theorem <atom>_correct`, the module is written under
   `generated/Generated/AiProof/` and checked with `lake build`, and the build
   log is fed back to the LLM for up to `LEAN_AI_PROOF_MAX_ATTEMPTS` (default 3)
   repair rounds. Only a module that builds with exit code 0, no `error:` lines
   and no `declaration uses 'sorry'` is promoted; the source is rejected before
   Lake if it contains `sorry` / `admit` / `axiom` / `unsafe` /
   `native_decide` / `implemented_by`. The AI stage is skipped entirely when no
   LLM key is configured or `CI_FIXTURE_MODE` is set, so fixture runs keep the
   known-witness-only behaviour.
6. Only obligations that remain `unknown` after step 5 are the input to the
   human path (`agent/human_review.py::escalate_to_lean`, MCP
   `escalate_to_lean`), which is now the final fallback.
7. `proliferate` records per-spec fallback diagnostics and aggregate metrics in
   the output summary JSON.

## Error codes

| Code | Meaning | Retryable | Typical action |
| --- | --- | --- | --- |
| `repo_missing` | `MUMEI_LEAN_REPO` does not exist. | No | Point `MUMEI_LEAN_REPO` at a mumei-lean checkout. |
| `bridge_missing` | `scripts/bridge.py` is absent. | No | Refresh the mumei-lean checkout. |
| `lake_missing` | Lake/Lean is not on `PATH`. | Yes | Install elan/Lean or prepend `$HOME/.elan/bin`. |
| `import_error` | Lean could not resolve a generated module/mathlib import. | Yes | Refresh `lake exe cache get` and regenerate `generated/`. |
| `theorem_not_found` | A referenced Lean theorem name is missing. | No | Check witness module imports and theorem naming. |
| `tactic_failed` | Lean elaborated the theorem but tactics left goals open. | No | First run with `--enable-lean-ai-proof` so the LLM generates/repairs a proof against the Lake feedback; only if `ai_proof_residual` still lists the atom, add a handwritten witness/proof strategy. |
| `partial_translation` | mumei-lean marked unsupported syntax/manual review. | No | First let the AI proof stage state the theorem directly from `requires` / `ensures` / body (`--enable-lean-ai-proof`); extend the translator or simplify the contract only for the residual atoms. |
| `unsound_source` | AI-generated Lean source was rejected before Lake (`sorry` / `axiom` / missing theorem, …). | No | Never promoted. Inspect `attempt_N.lean` under `ai_proof_evidence_dir`; the next repair round already receives the rejection reason. |
| `generator_error` | The LLM call for AI proof generation failed. | Yes | Check `LLM_API_KEY` / `LLM_BASE_URL`; the atom stays `unknown`. |
| `timeout` | Bridge or witness build exceeded its timeout. | Yes | Re-run with a warm Lake cache or a higher timeout. |
| `subprocess_error` | Python could not execute the bridge. | Yes | Inspect the runner environment and bridge script permissions. |
| `bridge_failed` | Non-zero bridge exit not covered above. | Yes | Inspect captured stdout/stderr for the root cause. |

## Metrics

`proliferate(..., output_json=...)` writes both top-level metrics and a nested
`lean_fallback_metrics` object:

- `lean_fallback_attempted`, `lean_fallback_proved`, `lean_fallback_failed`
- `lean_fallback_success_rate`
- `lean_fallback_attempted_specs`
- `lean_fallback_partial_successes`
- `lean_fallback_retryable_failures`
- `lean_fallback_error_code_counts`
- `lean_fallback_failure_rate_by_error_code`
- `lean_fallback_duration_seconds` (`count`, `min`, `max`, `avg`, `p50`, `p95`)

Per-spec `details[*].lean_fallback` also records `error_code`,
`primary_error_code`, `retryable`, `fallback_strategy`, `duration_seconds`, and
`partial_success`. When the AI stage ran it additionally records
`ai_proof_used`, `ai_proof_proved`, `ai_proof_attempted`, `ai_proof_residual`
(atom names left for human review) and `ai_proof_evidence_dir`.
`lean_verified_count` in `publish_result.proof_certificate_summary` is derived
through the same `merge_lean_cert_into_proof_cert` path regardless of which
stage discharged the atom.

## Generated-module and witness paths

The reference generated-module path is no longer a skip precondition:
`abs_saturating` carries body semantics, builds as
`Generated.Std.Math.Abs.abs_saturating_correct`, and exports `lean_verified`
with `known_witness_used = false`.

Known witness modules remain an explicitly attributed fallback. For
`abs_saturating`, this fallback is used only when the source certificate lacks
complete body semantics; the live generated path above is canonical when
`body_expr` is present. Other current witness-backed std atoms include:

- `fixed_point_abs`
- `fixed_point_from_int`
- `list_length`

This keeps the fallback conservative: unmapped unknown atoms remain unknown, and
partial success is reported instead of treated as a full bridge success.

## Provenance: which stage discharged an atom

Every promoted atom carries `lean_fallback_strategy` plus `lean_metadata` /
`lean_result_metadata` flags so the three automated stages are distinguishable:

| Stage | `lean_fallback_strategy` | `known_witness_used` | `ai_proof_used` |
| --- | --- | --- | --- |
| Generated module (`scripts/bridge.py`) | `generated_bridge` / bridge value | `false` | absent / `false` |
| Known witness module | `known_witness_module` | `true` | `false` |
| AI-generated proof (Task 2-D) | `ai_generated_proof` | `false` | `true` |

AI-promoted atoms also record `ai_proof_attempts`, `proof_path` (the accepted
`attempt_N.lean`) and `build_log_path` (the matching Lake log) under
`lean_metadata`, and `lean_module` / `lean_theorem_name` point at
`Generated.AiProof.<Atom>.<atom>_correct`. The evidence directory defaults to
`<mumei-lean>/.ai_proof_evidence/<Atom>/` and can be moved with
`LEAN_AI_PROOF_EVIDENCE_DIR`. The `stale_translator` / `bridge_lemma_hash`
checks in `merge_lean_cert_into_proof_cert` apply to AI-promoted atoms exactly
as they do to the other two stages.

## Escalation bundle schema (v2)

`agent/strategies/cegis_loop_helpers.py::escalate_to_lean` still writes
`source_file` / `loop_line` / `loop_context` / `reason`, and appends:

- `bundle_schema_version` — `mumei.escalation_bundle/2`
- `atom` — the target atom's `name` / `requires` / `ensures` / `body` /
  `body_expr` (and `params`, `return_type`, `module_key` when known)
- `counterexamples` — every Z3 model collected by `_extract_counterexample`
- `tried_invariants` — each CEGIS candidate (`expression`, `source`,
  `iteration`, `counterexamples`)

The AI proof stage forwards these as hints in its prompt; absent keys are
simply omitted, so older bundles remain valid.
