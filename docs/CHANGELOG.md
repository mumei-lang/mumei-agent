# Changelog

## 2026-07-26: P16-C benchmark feedback into the vStd forge / proliferate loop

- Added `agent/benchmark_feedback.py`, which loads the mumei `mumei.benchmark_forge_feedback/v1` document emitted by `benchmarks/run_benchmarks.py --forge-feedback` and maps each benchmark category's weakness score to a negative `priority_delta` over its stdlib domains.
- Wired `--benchmark-feedback` into `forge` (bias applied before the `--max-tasks` cut, so a weak domain can win a limited budget) and `proliferate` (gap proposals ranked, spec priorities biased, provenance recorded under `benchmark_feedback` in the `--output-json` summary).
- Feedback only reorders work that gap analysis already produced; missing or malformed documents are logged and ignored. Regression gate: `uv run pytest tests/test_benchmark_feedback.py tests/test_forge.py tests/test_proliferate.py -q`.

## 2026-06-28: Multi-language audit and Forge regression hardening

- Added deterministic no-`.mm` audit regressions for Rust `a + b` overflow and `values[idx]` bounds, TypeScript `name!.length` null/undefined, and Go `values[idx]` bounds; all normalize Z3 counterexamples into `verification_violations` with the fixed seven-key audit schema and no aliases.
- Extended MCP `scan_and_fix` regressions so the audit -> migrate-suggest -> heal key order is stable across Python, Rust, TypeScript, and Go, with `next_steps` as the only human-review entrypoint.
- Continued P9 Forge with `forge_tasks/vstd_crypto_primitives.json`, generated and verified `std/crypto/primitives.mm`, and recorded the Z3-decidable proof-certificate result in `forge_log.json` without Lean escalation.
