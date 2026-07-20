---
name: testing-dogfood-triage
description: Test the mumei-agent dogfood verdict triage / audit aggregation layer end-to-end. Use when changes touch agent/dogfood_triage.py, agent/audit_reporting.py aggregation (_aggregate_directory_fixed_keys / verification_status buckets), or agent/audit.py directory audit reporting.
---

# Testing the dogfood triage / audit aggregation layer

`agent/dogfood_triage.py::triage_directory_result(AuditDirectoryResult)` buckets each
`file_result.verification_status` into `human_review` (refuted), `verified`, and
`unverifiable` subcategories (`skipped_rate_limited` > `timeout` > `encoding_gap` >
`no_function_declarations` > `other`, priority-ordered). It reuses existing verdict
logic and `_errors_indicate_rate_limit` / `_is_spec_lowering_or_unsupported_error`;
it does NOT re-derive verdicts.

## Environment
- `mumei` binary: `/home/ubuntu/repos/mumei/target/debug/mumei` (set `MUMEI_BIN` to it).
- Usually NO LLM key locally (`AgentConfig().api_key` is False), so audits run the
  deterministic extraction path only.

## Key fact that shapes the test
Without an LLM, deterministic extraction infers each function's contract FROM its own
body, so a real `audit_directory` run yields `verification_status == "verified"` for
nearly every file (even code with a wrong docstring claim). You therefore CANNOT
produce `refuted` / `unverifiable`-subcategory verdicts from a real offline audit.

So split the testing:
1. **verified bucket + fixed-key contract** — via a REAL audit run.
2. **refuted / unverifiable subcategories + priority** — via CONSTRUCTED `AuditResult`
   verdicts (verdict derivation itself is already unit-tested and is out of scope for
   the aggregation layer).

## Commands
Corpus property tests (deterministic extraction oracles):
```
cd /home/ubuntu/repos/mumei-agent && uv run pytest tests/test_foreign_code_corpus.py -v
```

Real audit -> triage (verified bucket + AUDIT_SCHEMA_KEYS intact):
```python
from agent.config import AgentConfig
from agent.audit import AuditPipeline, AUDIT_SCHEMA_KEYS
from agent.dogfood_triage import triage_directory_result
res = AuditPipeline(config=AgentConfig()).audit_directory("<dir>", "python")
rep = triage_directory_result(res)
assert all(hasattr(res, k) for k in AUDIT_SCHEMA_KEYS)  # 8 fixed keys still present
```
(run with `env MUMEI_BIN=/home/ubuntu/repos/mumei/target/debug/mumei uv run python ...`)

Constructed verdict bucketing (build AuditResult with pre-set `verification_status`,
`errors`, `spec_health_issues`, `skipped_rate_limited`; wrap in AuditDirectoryResult):
- rate-limit marker (429 / "rate limit") OR `skipped_rate_limited=True` OR file in
  `skipped_rate_limited_files` -> `skipped_rate_limited` (wins over timeout).
- "timeout" / "timed out" / "deadline exceeded" -> `timeout`.
- spec_health_issue starting `encoding-gap` / lowering-unsupported / "Skipped unsupported Z3 clause" -> `encoding_gap`.
- `spec_extracted=False` or errors mentioning "No Mumei atoms" -> `no_function_declarations`.
- else -> `other`.

Unit tests live in `tests/test_audit.py` (`test_dogfood_triage_*`) and
`tests/test_foreign_code_corpus.py`.
