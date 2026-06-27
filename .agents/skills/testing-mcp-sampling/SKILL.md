---
name: testing-mcp-sampling
description: Test mumei-agent MCP sampling provider and fallback behavior. Use when changes touch agent/llm_provider.py MCP sampling, USE_MCP_SAMPLING, or agent/mcp_server.py LLM-backed MCP tools.
---

# Devin Secrets Needed

None for deterministic MCP sampling provider tests. Use fake MCP `Context`/session objects and fake fallback providers.

Live end-to-end runs against a real external LLM require either an MCP client with sampling support or an OpenAI-compatible fallback secret such as `LLM_API_KEY` or `OPENAI_API_KEY`.

# When to Use

Use this skill for PRs touching:
- `agent/llm_provider.py` MCP sampling provider behavior
- `USE_MCP_SAMPLING` configuration in `agent/config.py` or `agent/mcp_server.py`
- LLM-backed MCP tools such as `heal_file`, `forge_task`, `extract_spec`, or `self_correct`
- Documentation about MCP sampling capabilities, `includeContext`, or sampling fallback behavior

# Setup Checks

1. Confirm this is a shell/runtime path, not a browser UI path; do not record screen for shell-only testing.
2. Read the repo blueprint and use its environment command shape. The repo runs tests through `uv`, so execute probes with:
   ```bash
   uv run --directory /home/ubuntu/repos/mumei-agent python <probe.py>
   ```
3. Inventory secrets. Deterministic provider tests do not need secrets.
4. Check PR CI and comments before executing probes.

# Runtime Test Shape

Create a temporary probe that instantiates `McpSamplingLLMProvider` directly:

1. Sampling-supported client:
   - Use `ctx.session._client_params = {"capabilities": {"sampling": {}}}`.
   - Stub `ctx.session.create_message` to assert the request has text `SamplingMessage`, expected `system_prompt`, `model_preferences.hints[0].name`, bounded `max_tokens`, and no `include_context`, `tools`, or `tool_choice` kwargs.
   - Use a fallback provider that raises if called.
   - Assert `complete()` returns the stubbed text and calls sampling exactly once.

2. Unsupported client:
   - Use `ctx.session._client_params = {"capabilities": {"sampling": None}}`.
   - Stub `create_message` to raise if called.
   - Use a fallback provider that records inputs and returns fixed text.
   - Assert `complete()` returns fallback text, never calls sampling, and passes through the original messages/model.

3. Documentation alignment when relevant:
   - Assert README/ROADMAP do not mention obsolete draft-only migration tokens.
   - Assert docs mention the current MCP spec terms being relied on, such as `capabilities.sampling`, `sampling.tools`, `sampling.context`, and `includeContext` soft-deprecation.

# Reporting

- Treat the provider warning `MCP sampling failed; falling back...` as expected only in fallback tests.
- Provide command output as evidence; no recording is needed for shell-only tests.
