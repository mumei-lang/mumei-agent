---
name: testing-solidity-foreign-code
description: Test mumei-agent Solidity (.sol) support across Layer A (spec extraction) and Layer B (Z3 strict verification + smart-contract heuristics). Use when verifying changes to agent/code_to_spec.py solidity detection, agent/cross_validation_foreign.py solidity inference/256-bit overflow, agent/strategies/foreign_code_strategy*.py extract_solidity / _detect_solidity_contract_issues (reentrancy/CEI + access control), or agent/audit.py solidity wiring.
---

# Testing Solidity foreign-code support (Layer A / Layer B)

Solidity is supported in two layers:
- **Layer A** (spec extraction): detection + `.sol` extension mapping in `agent/code_to_spec.py`.
- **Layer B** (Z3 strict verification): deterministic contract inference + 256-bit overflow in
  `agent/cross_validation_foreign.py`, `agent/strategies/foreign_code_strategy*.py`, consumed by
  `validate-code` and by `audit`/`scan_and_fix` (`agent/audit.py`).

## All testing is deterministic — no secrets needed
Every path can be exercised with `--no-llm` / mocked LLM. No API keys, no logins.
**Devin Secrets Needed:** none.

## Environment gotcha: the `mumei` binary
The `mumei` Rust binary is usually **not installed** in the test VM. Consequences:
- The `audit` **CLI** crashes at the spec-health step (`_check_spec_health` → `mumei_client.verify`)
  for *every* language — `FileNotFoundError: 'mumei'`. This is NOT solidity-specific.
- Workaround: exercise the audit verification path in-process via `AuditPipeline(...)` with a
  **stubbed `mumei_client`** (`mumei.verify.return_value={"success":True,"report":{},"stdout":"","stderr":""}`)
  and a **real** `ForeignCodeVerifier(mumei_client=mumei)`. That is the exact path the CLI runs
  after spec-health, and the Z3 foreign verification does not need the binary.
- `validate-code` does NOT hit the binary when run with `--no-mumei`, so its CLI works fully.

## Key behaviors to assert (with concrete expected values)
- `2^256-1 = 115792089237316195423570985008687907853269984665640564039457584007913129639935`
- `2^255-1 = 57896044618658097711785492504343953926634992332820282019728792003956564819967`
- `-2^255 = -57896044618658097711785492504343953926634992332820282019728792003956564819968`
- **uint256** operands → requires `a + b <= 2^256-1 && a + b >= 0` (lower bound 0).
- **int256** operands → requires `a + b <= 2^255-1 && a + b >= -2^255`.
- A broken impl that reuses the i64 helper would instead show `9223372036854775807` (2^63-1) — a
  clear tell. Always assert the full 256-bit literal, not just "has a bound".
- Mumei type mapping: `uint*`→`u64`, `int*`→`i64` in `params`, but the *overflow bounds* respect
  256-bit semantics. So params can read `i64`/`u64` while requires use the 256-bit literal.

## Fast commands
```bash
# T1 Layer B validate-code (uint256), deterministic
uv run python -m agent validate-code --input tests/fixtures/sample_solidity.sol \
  --language solidity --no-llm --no-mumei --output /tmp/t1.json

# T4 audit CLI must accept solidity in argparse
uv run python -m agent audit --help | grep -i "language {"   # expect ...,go,solidity}
```
```python
# T3 audit path -> verification_violations (in-process; mumei stubbed)
from unittest.mock import MagicMock
from agent.audit import AuditPipeline
from agent.code_to_spec import CodeToSpecResult
from agent.config import AgentConfig
from agent.strategies.cross_validation_strategy import CrossValidationReport
from agent.strategies.foreign_code_strategy import ForeignCodeVerifier
# extractor returns a CodeToSpecResult(detected_language="solidity", forge_task_spec=...);
# cross_validator returns CrossValidationReport(coverage_ratio=1.0); mumei = MagicMock() healthy.
# AuditPipeline(..., foreign_code_verifier=ForeignCodeVerifier(mumei_client=mumei), ...).audit_file(sol, "solidity")
# assert "can overflow `a + b`" and "uint256 bounds contract" in a verification_violations entry.
```

## Smart-contract heuristics (Layer B stage 1): reentrancy/CEI + access control
`_detect_solidity_contract_issues` in `agent/strategies/foreign_code_strategy_helpers.py` emits
**advisory heuristic warnings** (NOT Z3 proofs — no counterexample, `required_contracts=()`):
- **Reentrancy/CEI**: external value-transfer call (`.call{value:}`/`.call(`/`.transfer(`/`.send(`)
  followed *in source order* by a storage write → message contains `may be vulnerable to reentrancy`
  and `Checks-Effects-Interactions`.
- **Missing access control**: externally callable (`public`/`external`, non-`view`/`pure`)
  state-mutating function with no `only*`/`auth` modifier and no body guard
  (`require(msg.sender == ...)`, `hasRole(`, `_checkOwner()`, owner-revert `if`) → message contains
  `no access-control guard`.
These surface in `verification_violations` (audit/validate-code) and as `warning`-severity
`verification` issues from `validate_foreign_code(..., "solidity")`.

**Test adversarially on BOTH axes** — a fixture must contain vulnerable AND safe functions:
- vulnerable `withdraw` (call then state write, unguarded) → both warnings;
- `setOwner(...) public { owner = ...; }` → access-control only;
- `withdrawAll() public onlyOwner { state write; then transfer }` → NEITHER (guarded + correct order);
- `getBalance() public view` → NEITHER.
The most discriminating check: a function that writes state **before** the external call and is
guarded (`onlyOwner`) must produce **0** CEI and **0** access-control warnings. A naive detector that
flags "external call + any state write" (ignoring order) or "state write + public" (ignoring guards)
would wrongly flag it. Always assert absence for safe functions, not just presence for vulnerable ones.
Fixture: `tests/fixtures/sample_solidity_vulnerable.sol`.

## Stage 2: Z3 reentrancy guard-state-machine (suppression + trace)
Stage 2 upgraded the CEI/reentrancy detector (`_solidity_reentrancy_trace` +
`_solidity_cei_issue` in `foreign_code_strategy_helpers.py`) from a pure ordering heuristic to a
Z3-backed guard-state-machine check (GuardState Unlocked/Locked, modeled on mumei-lean
`SmartContract.lean`). Two testable behaviors:
- **Trace**: an unguarded call-then-write finding now carries `counterexample =
  {"reentrancy_trace": ["externalCall: ...", "stateWrite: ..."], "guard": "absent"}`. This surfaces on
  `ForeignCodeVerifier.verify(...)["counterexample"]` and on `AuditPipeline` `counterexample_values`
  (list of `{"function_name", "counterexample"}`), but is NOT inline in the `validate-code` JSON
  `issues[]` entries — assert it at the verifier/audit layer, not the CLI JSON.
- **Suppression**: a reentrancy guard makes the finding disappear. Guard = a `nonReentrant`/
  `noReentrancy` modifier, OR a manual lock (`require(!locked); locked=true; ...; locked=false;`).
  Fixture `tests/fixtures/sample_solidity_guarded.sol` has both a `nonReentrant withdraw` and a
  manual-lock `manualWithdraw`; both do call-then-write yet must produce NO
  `may be vulnerable to reentrancy` warning — while their access-control warnings STILL appear
  (only the reentrancy branch is suppressed, the function isn't skipped). This is the key adversarial
  check: a broken guard detector would still flag them.
Note `ForeignCodeVerifier(mumei_client=...)` must be passed by keyword — the first positional arg is
not `mumei_client`, so a positional mock falls through to the real `mumei` subprocess and errors with
`FileNotFoundError: 'verify'`.

## Detection heuristic (Layer A) is easy to over-broaden
`_detect_language` content fallback (only used for files with NO recognized extension) must use
`re.search(r"\bcontract\s+[A-Z]", code)`, NOT `"contract " in code`. Regression test: a Python
file containing `contract = get_contract()` must resolve to `python`, not `solidity`.

## Relevant unit tests to keep green
`tests/test_code_to_spec.py`, `tests/test_foreign_code.py`, `tests/test_cross_validation.py`,
`tests/test_audit.py` (solidity cases), `tests/test_contract_vocabulary.py` (runs when
`README.md`/`docs/ROADMAP.md` change). Note: `test_telemetry.py::test_exporter_builders_return_none_without_extra`
may fail locally when otel exporter packages are installed — this is env-specific and passes in CI.
