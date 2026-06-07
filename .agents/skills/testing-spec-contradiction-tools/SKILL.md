---
name: testing-spec-contradiction-tools
description: Test mumei-agent natural-language contradiction-only extraction and MCP cross-spec consistency tools end-to-end. Use when changes touch agent/extract_spec.py, agent/mcp_server.py contradiction tools, or check_cross_spec_consistency behavior.
---

# Testing Spec Contradiction Tools

## Devin Secrets Needed

None for deterministic local CLI/MCP testing.

Live natural-language extraction through an LLM requires `LLM_API_KEY` or `OPENAI_API_KEY`; avoid claiming live extraction quality unless one is available and used. Contradiction-only engine tests can bypass live LLM calls by passing a deterministic extracted spec directly to `check_spec_contradiction_from_spec`.

## Prerequisites

- A built local Mumei binary, usually `/home/ubuntu/repos/mumei/target/debug/mumei`.
- Z3 available on PATH for `mumei verify`.
- mumei-agent installed in editable mode (`pip install -e ".[test]"` from repo root) if imports fail.

## Runtime Test Shape

1. Verify multi-file cross-spec via the Mumei CLI:
   ```bash
   cd /home/ubuntu/repos/mumei
   REPORT_DIR=/home/ubuntu/cross-spec-e2e-report
   rm -rf "$REPORT_DIR"
   LLVM_SYS_170_PREFIX=/usr/lib/llvm-17 LIBCLANG_PATH=/usr/lib/x86_64-linux-gnu \
     cargo run -- verify \
       --report-dir "$REPORT_DIR" \
       --cross-spec-files tests/test_cross_spec_multi_file_dep.mm \
       tests/test_cross_spec_multi_file.mm
   ```
   Assert `/home/ubuntu/cross-spec-e2e-report/cross_spec.json` exists, `summary.inconsistent_calls == 1`, and at least one `global_invariant_conflicts[]` entry references both `test_cross_spec_multi_file.mm` and `test_cross_spec_multi_file_dep.mm`.

2. Verify the MCP wrapper uses the same cross-spec path:
   ```bash
   cd /home/ubuntu/repos/mumei-agent
   MUMEI_BIN=/home/ubuntu/repos/mumei/target/debug/mumei python - <<'PY'
   import json
   from agent import mcp_server
   result = json.loads(mcp_server.check_cross_spec_consistency(json.dumps([
       '/home/ubuntu/repos/mumei/tests/test_cross_spec_multi_file.mm',
       '/home/ubuntu/repos/mumei/tests/test_cross_spec_multi_file_dep.mm',
   ])))
   assert result['status'] == 'ok', result
   assert result['consistent'] is False, result
   assert result['cross_spec']['summary']['inconsistent_calls'] == 1, result
   PY
   ```
   MCP `_ok` responses put payload fields at top level alongside `status`; do not expect a nested `payload` key.

3. Verify contradiction-only runtime behavior without LLM secrets:
   ```bash
   cd /home/ubuntu/repos/mumei-agent
   python - <<'PY'
   from agent.extract_spec import check_spec_contradiction_from_spec
   from agent.mumei_client import create_mumei_client
   spec = {'atoms': [{'name': 'impossible_positive', 'params': [{'name': 'n', 'type': 'i64'}], 'return_type': 'i64', 'requires': 'n > 0 && n < 0', 'ensures': 'result >= 0'}]}
   result = check_spec_contradiction_from_spec(spec, create_mumei_client('/home/ubuntu/repos/mumei/target/debug/mumei'))
   assert result['contradiction_found'] is True, result
   assert result['natural_language_explanation'].startswith('The extracted natural-language specification contains a direct contradiction.'), result
   PY
   ```

## Notes

- `mumei verify --json` might return only a minimal failed summary for synthesized contradiction modules. `check_spec_contradiction_from_spec` should still surface that as a contradiction if `report.status == "failed"` or `report.failed > 0`.
- These are shell-only tests; do not start a screen recording unless a future UI is introduced.
