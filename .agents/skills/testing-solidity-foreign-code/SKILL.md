---
name: testing-solidity-foreign-code
description: Test mumei-agent Solidity (.sol) support across Layer A (spec extraction) and Layer B (Z3 strict verification). Use when verifying changes to agent/code_to_spec.py solidity detection, agent/cross_validation_foreign.py solidity inference/256-bit overflow, agent/strategies/foreign_code_strategy*.py extract_solidity, or agent/audit.py solidity wiring.
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

## Detection heuristic (Layer A) is easy to over-broaden
`_detect_language` content fallback (only used for files with NO recognized extension) must use
`re.search(r"\bcontract\s+[A-Z]", code)`, NOT `"contract " in code`. Regression test: a Python
file containing `contract = get_contract()` must resolve to `python`, not `solidity`.

## Relevant unit tests to keep green
`tests/test_code_to_spec.py`, `tests/test_foreign_code.py`, `tests/test_cross_validation.py`,
`tests/test_audit.py` (solidity cases), `tests/test_contract_vocabulary.py` (runs when
`README.md`/`docs/ROADMAP.md` change). Note: `test_telemetry.py::test_exporter_builders_return_none_without_extra`
may fail locally when otel exporter packages are installed — this is env-specific and passes in CI.
