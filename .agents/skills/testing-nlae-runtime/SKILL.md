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
2. Check CI and PR comments before execution. Inside `mumei-agent` always use `uv run pytest`
   (bare `pytest` on PATH belongs to the system Python and misses the project deps):
   ```bash
   uv run pytest -q   # baseline as of commit 2835e0c7: 1964 passed, 64 skipped
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
   - Adversarial controls worth adding (they catch implementations that only *look* correct):
     - Tamper control for `authenticated`: encode one envelope directly with `LatentProtocol`, assert
       `verify_authentication_tag(vec) is True`, mutate the stored `encoded_frame` in
       `protocol._metadata_by_vector[protocol._vector_key(vec)]`, and assert it flips to `False`.
     - "No behaviour drift" control: extract the pre-change pipeline with
       `git show <feature-commit>^:agent/nlae_pipeline.py > test-artifacts/old_nlae_pipeline.py`,
       import it with `importlib.util.spec_from_file_location`, run it with the same fakes, and compare
       `NLAEResult.to_dict()` plus the generated `.mm` / `.proof-cert.json` bytes. Normalise work-dir
       absolute paths (they appear inside `lean_result`) and drop `trace_id` / `artifacts` before
       comparing, otherwise the comparison fails for path reasons only. Add a mutated-input negative
       control so the comparison cannot pass vacuously.
     - Spec-sensitivity control: a changed spec must change at least one handoff `semantic_hash`.
       Note the escalation handoff body is `{proof_cert filename, stage, z3_verified}` + atom names, so
       that particular hash is expected to stay stable across different specs.
     - Failure injection twice: raise from `MultiAgentOrchestrator.handoff` *and* monkeypatch
       `LatentProtocol.encode_message` to raise; both must fall back and the resulting `NLAEResult`
       (minus `multi_agent`/`trace_id`/paths) must equal the single-pipeline baseline, with the Lean
       bridge called exactly once.
     - Audit privacy: seed the loss vector and atom name with unique marker strings, set
       `LATENT_PROTOCOL_AUDIT_LOG` *and* `LATENT_PROTOCOL_KEY` in the environment only (the
       orchestrator picks both up itself), then grep the raw JSONL for the markers, the key value and
       `protocol._auth_key().hex()`. Audit line keys should be exactly
       `authentication, encrypted, event, payload_hash, protocol_version, semantic_hash, transfer_bytes`.
     - Real trace assertions instead of span-name recording: set `OTEL_ENABLED=true` and install an SDK
       `TracerProvider` + `InMemorySpanExporter` (from `opentelemetry.sdk.trace.export.in_memory_span_exporter`)
       **before** the first `agent.telemetry` call — `telemetry._initialise()` keeps an already-installed
       provider. Then assert one distinct `trace_id`, one root (`mumei.nlae.pipeline`, `parent is None`),
       `mumei.nlae.multi_agent` parented on the root, all three `mumei.nlae.agent.<role>` spans and the
       `mumei.nlae.handoff` spans parented on the workflow span, and no orphan parents. Do this in a
       separate process from the non-OTel probes, since `OTEL_ENABLED` also switches on
       `telemetry.span_trace_id`.
     - MCP surface: patch `agent.mcp_server.NLAEPipeline` with a thin **subclass of the real**
       `NLAEPipeline` that only injects fakes (signature `(work_dir, lean_no_build=False,
       multi_agent=None)`), then call `mcp_server.run_nlae_pipeline(...)` directly. Check three
       combinations: `multi_agent=True`; `multi_agent=False` with `ENABLE_NLAE_MULTI_AGENT=true`
       (must still opt in via config); `multi_agent=False` with the env var unset (`multi_agent` null).
     - Round budget: with a self-correction stub that never fixes the code, `rounds` must stop at
       `NLAE_MULTI_AGENT_MAX_ROUNDS` and the run must still end with one escalation handoff.
       `converged` mirrors `NLAEResult.verified` (Z3 **or** Lean), so make the Lean fake fail too if you
       want to prove `converged` can be `False`.
   - Caveat: passing `orchestrator=` enables the workflow even with `multi_agent=False`
     (`nlae_pipeline.py`: `self.multi_agent = resolved_multi_agent or orchestrator is not None`).
     Use `multi_agent=False` **without** an orchestrator when testing the default-off path.

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
