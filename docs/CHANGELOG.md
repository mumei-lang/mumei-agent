# Changelog

## 2026-06-28: Multi-language audit and Forge regression hardening

- Added deterministic no-`.mm` audit regressions for Rust `a + b` overflow and `values[idx]` bounds, TypeScript `name!.length` null/undefined, and Go `values[idx]` bounds; all normalize Z3 counterexamples into `verification_violations` with the fixed seven-key audit schema and no aliases.
- Extended MCP `scan_and_fix` regressions so the audit -> migrate-suggest -> heal key order is stable across Python, Rust, TypeScript, and Go, with `next_steps` as the only human-review entrypoint.
- Continued P9 Forge with `forge_tasks/vstd_crypto_primitives.json`, generated and verified `std/crypto/primitives.mm`, and recorded the Z3-decidable proof-certificate result in `forge_log.json` without Lean escalation.
