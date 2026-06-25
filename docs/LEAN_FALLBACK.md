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
5. `proliferate` records per-spec fallback diagnostics and aggregate metrics in
   the output summary JSON.

## Error codes

| Code | Meaning | Retryable | Typical action |
| --- | --- | --- | --- |
| `repo_missing` | `MUMEI_LEAN_REPO` does not exist. | No | Point `MUMEI_LEAN_REPO` at a mumei-lean checkout. |
| `bridge_missing` | `scripts/bridge.py` is absent. | No | Refresh the mumei-lean checkout. |
| `lake_missing` | Lake/Lean is not on `PATH`. | Yes | Install elan/Lean or prepend `$HOME/.elan/bin`. |
| `import_error` | Lean could not resolve a generated module/mathlib import. | Yes | Refresh `lake exe cache get` and regenerate `generated/`. |
| `theorem_not_found` | A referenced Lean theorem name is missing. | No | Check witness module imports and theorem naming. |
| `tactic_failed` | Lean elaborated the theorem but tactics left goals open. | No | Add or improve a handwritten witness/proof strategy. |
| `partial_translation` | mumei-lean marked unsupported syntax/manual review. | No | Extend the translator or simplify the contract. |
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
`partial_success`.

## Generated-module and witness paths

The reference generated-module path is no longer a skip precondition:
`abs_saturating` carries body semantics, builds as
`Generated.Std.Math.Abs.abs_saturating_correct`, and exports `lean_verified`
with `known_witness_used = false`.

Known witness modules remain an explicitly attributed fallback for std atoms
that cannot yet be discharged by generated theorem output:

- `abs_saturating`
- `fixed_point_abs`
- `fixed_point_from_int`
- `list_length`

This keeps the fallback conservative: unmapped unknown atoms remain unknown, and
partial success is reported instead of treated as a full bridge success.
