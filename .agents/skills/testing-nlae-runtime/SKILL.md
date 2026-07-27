---
name: testing-nlae-runtime
description: Test mumei-agent NLAE runtime integration paths. Use when verifying latent protocol MCP messaging, dense property generation, or latent-debug fallback behavior.
---

# Devin Secrets Needed

None for deterministic runtime testing. These tests should use mocked OpenAI-compatible and Mumei clients unless the task explicitly requires live LLM or live compiler verification.

If live end-to-end LLM generation is required, use `LLM_API_KEY` or `OPENAI_API_KEY` plus optional `LLM_BASE_URL` and `LLM_MODEL` from Devin Secrets.

# When to Use

Use this skill for PRs touching:
- `agent/config.py` NLAE flags (`ENABLE_LATENT_DEBUG`, `ENABLE_DENSE_PROPERTIES`, `ENABLE_LATENT_PROTOCOL`, `ENABLE_NLAE_MULTI_AGENT`)
- `agent/nlae_multi_agent.py` / `agent/nlae_pipeline.py` multi-agent workflow paths
- `agent/mcp_server.py` latent protocol tools or `heal_file`
- `agent/strategies/generate_strategy.py` dense property paths
- `agent/strategies/fix_strategy.py` latent-debug behavior
- `agent/latent_*` components

# Setup Checks

1. Confirm the repo has no UI path for this feature; prefer shell/runtime probes over browser recording.
2. Check CI and PR comments before execution:
   ```bash
   python -m pytest -q
   ```
3. Check lint according to the repo blueprint:
   ```bash
   if [ -f .pre-commit-config.yaml ]; then pre-commit run --all-files; else echo "No .pre-commit-config.yaml; skipping pre-commit"; fi
   ```
4. Do not require external secrets for deterministic runtime probes. Use mocked clients through public Python APIs.

# Runtime Test Shape

Create a temporary probe under an uncommitted artifact directory such as `test-artifacts/`. Do not commit the probe or artifacts.

The probe should verify these assertions:

1. Default flags remain disabled:
   - Remove `ENABLE_LATENT_DEBUG`, `ENABLE_DENSE_PROPERTIES`, and `ENABLE_LATENT_PROTOCOL` from `os.environ`.
   - Instantiate `AgentConfig()`.
   - Assert all three NLAE flags are exactly `False`.
   - Call `mcp_server.send_latent_message(..., verify=False)` and assert JSON `status == "error"` and the error includes `ENABLE_LATENT_PROTOCOL is not enabled`.

2. Latent protocol MCP tool works when enabled:
   - Set `ENABLE_LATENT_PROTOCOL=true` in the process.
   - Assert `send_latent_message` is present in `mcp_server.mcp._tool_manager._tools`.
   - Call `send_latent_message` with valid message/context JSON and `verify=False`.
   - Assert `status == "ok"`, `len(latent_vector) == 16`, `decoded.latent_dim == 16`, `decoded.decoded is True`, and `verification_result is None`.

3. Dense properties run on multi-atom generation:
   - Call `generate_code()` with a multi-atom spec, `mumei_client=None`, `enable_dense_properties=True`, and a mocked OpenAI client.
   - Mock the first LLM response to return two atoms with `requires: true;` and `ensures: true;`.
   - Mock the second LLM response to return a distinctive contract such as `requires: false;` and `ensures: result == 1;`.
   - Assert returned `verified is True`, output contains both distinctive contract clauses, and mocked LLM call count is exactly `2`.

4. Multi-agent verification workflow stays opt-in and auditable:
   - Remove `ENABLE_NLAE_MULTI_AGENT` from `os.environ`, instantiate `AgentConfig()`, and assert `enable_nlae_multi_agent is False` and `nlae_multi_agent_max_rounds == 2`.
   - Run `NLAEPipeline(...).run_full_pipeline()` with mocked agent / mumei client / self-correction / Lean bridge and no orchestrator, and assert `result.multi_agent is None`.
   - Re-run with `orchestrator=MultiAgentOrchestrator(protocol=LatentProtocol(audit_log_path=...))` and assert `multi_agent["status"] == "ok"`, `converged is True`, the handoff sequence is `generator -> counterexample` then `counterexample -> lean_escalation`, every handoff is `authenticated` with `protocol_version == "lp-v2"`, and the audit JSONL lines contain `semantic_hash` but no `message` / `context` body.
   - Run the same spec twice and assert the handoff `semantic_hash` sequences are identical (deterministic orchestration).
   - Make the orchestrator's `handoff` raise, then assert the run still returns a verified `NLAEResult` and `multi_agent["status"] == "fallback"` with the `fallback_reason` recorded.
   - Assert the span names observed through `agent.telemetry.start_span` include `mumei.nlae.pipeline`, `mumei.nlae.multi_agent`, `mumei.nlae.agent.<role>` for each role, and `mumei.nlae.handoff`, and exclude `mumei.nlae.lean_bridge`.

5. Latent debug validates before returning:
   - Call `get_fix()` with `enable_latent_debug=True`, a source containing a `requires` clause, and a report that triggers latent debugging.
   - Provide a fake `mumei_client.verify()` returning `{"success": False}`.
   - Mock the LLM fallback to return distinctive fallback code.
   - Assert `verify()` is called exactly once, the returned code is the fallback, and the unverified latent candidate marker (for example `&& true`) is absent.

# Reporting

- No screen recording is needed for shell-only testing.
- Save probe stdout and supporting pytest/lint output in `test-artifacts/`.
- Include the limitation that mocked clients prove integration behavior but do not exercise a live LLM provider or live `mumei` binary unless live secrets/tooling were explicitly available.
- When testing an open PR, post one collapsed PR comment with assertion results and attach evidence screenshots or raw artifacts as appropriate.
