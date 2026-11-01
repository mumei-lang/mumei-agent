# Naming convention for flags and environment variables

This convention prevents new naming drift; it does not rename existing interfaces.
Rule IDs are enforced by [`tests/test_naming.py`](../tests/test_naming.py).

## CLI flags

- **F1 — kebab-case:** Long flags match `--[a-z0-9]+(-[a-z0-9]+)*`; this keeps command-line use predictable. Good: `--strict-imports`. Bad: `--Strict_Imports`.
- **F2 — paired enable/disable:** `--disable-X` has `--enable-X` in the same command; a matched pair makes both directions explicit. Good: `--enable-cache` / `--disable-cache`. Bad: `--disable-cache` alone.
- **F3 — paired no-option:** `--no-X` has `--X` in the same command; callers can clearly select either behavior. Good: `--cache` / `--no-cache`. Bad: `--no-cache` alone.
- **F4 — safety-only allow:** Every `--allow-X` is listed in `SAFETY_RELAXATIONS` with the check it relaxes; `allow` must not disguise an ordinary feature opt-in. Good: `--allow-contract-erosion`, which explicitly bypasses the contract-erosion guard. Bad: `--allow-preview-mode`.
- **F5 — avoid ambiguous prefixes:** Do not start new flags with `--with-`, `--without-`, `--skip-`, `--use-`, or `--dont-`; use a direct action or a paired enable/disable name. Good: `--enable-cache`. Bad: `--skip-cache`.

## Environment variables

- **E1 — upper snake case:** Names match `[A-Z][A-Z0-9_]*`; this matches platform and shell conventions. Good: `ENABLE_CACHE`. Bad: `EnableCache`.
- **E2 — positive feature toggles:** Repo-owned names avoid `USE_`, `DISABLE_`, `NO_`, `MUMEI_USE_`, `MUMEI_DISABLE_`, and `MUMEI_NO_`, and avoid `_ENABLED` / `_DISABLED`; new boolean feature toggles use `ENABLE_X`. Good: `ENABLE_CACHE`. Bad: `USE_CACHE`.
- **E3 — repository prefix (mumei only):** Repo-owned Mumei variables start with `MUMEI_`; this distinguishes them from process and toolchain settings. This rule does not apply to mumei-agent. Good for mumei: `MUMEI_ENABLE_CACHE`. Bad for mumei: `ENABLE_CACHE`.
- **E4 — safety-only allow:** Every variable containing `ALLOW` is listed in `SAFETY_RELAXATIONS` with the check it relaxes; an allow variable is a reviewed safety exception. Good (mumei): `MUMEI_REGISTRY_ALLOW_PLAINTEXT` with its transport-policy reason. Bad: `MUMEI_ALLOW_PREVIEW`.
- **E5 — positive toggle names:** Repo-owned environment variables with `kind="toggle"` start with `ENABLE_`; this gives every boolean feature toggle the same positive form. Good: `ENABLE_CACHE`. Bad: `CACHE_ACTIVE`.

OpenTelemetry, GitHub Actions, shared CI fixture-mode, W3C trace-context, OpenAI-client, and toolchain variables are external and listed in `EXTERNAL`; the repo-owned prefix and toggle rules do not apply to them. New mumei-agent feature toggles use `ENABLE_X`.

## Adding an exception

Prefer renaming a new name so it follows the convention. Add an exception only when compatibility requires it: include the exact name, violated rule ID, and one-line reason in `GRANDFATHERED`; document the reason and the alias/deprecation plan. The tests reject unlisted violations and stale exceptions.

## Known inversions

`--allow-contract-erosion` bypasses the contract-erosion check, while `ENABLE_EROSION_GUARD` enables that check by default. This opposite-direction pair is grandfathered for compatibility and should be aligned only through future aliases, not an in-place rename.

## Cross-layer consistency

Use the same concept stem across layers: `--enable-cache`, `ENABLE_CACHE`, and `cache` in a configuration file. Use `--allow-*` only to relax a safety check. Default-on features use a paired `--disable-X` or `--no-X`. Never rename an existing flag or variable in place; add an alias and keep the old name with a deprecation note until the next major release.
