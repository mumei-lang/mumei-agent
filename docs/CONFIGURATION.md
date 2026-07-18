# Configuration Reference

## Configuration

Core agent and local Ollama settings are controlled through environment variables
(`.env` is loaded automatically):

- `LLM_API_KEY` / `OPENAI_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`: select the
  OpenAI-compatible LLM endpoint. For local Ollama, set `LLM_BASE_URL` to
  `http://localhost:11434/v1`.
- `USE_MCP_SAMPLING` (default: `false`): for `agent/mcp_server.py` tool calls,
  ask the connected MCP client (for example Devin) to provide completions via
  MCP sampling. All LLM-backed MCP tools support this path; OpenAI-compatible
  settings remain the fallback.
- `MCP_SAMPLING_MAX_TOKENS` (default: `4096`): maximum `maxTokens` sent in MCP
  sampling requests.
- `MAX_CONTEXT_TOKENS` (default: `16000`): operator-facing estimate for the
  maximum prompt budget to send to the LLM. Use this to align prompt construction
  with the model/context window selected for your backend.
- `PROMPT_REPORT_TRUNCATE_CHARS` (default: `4000`): maximum number of characters
  embedded from verifier retry context. Retry prompts prefer actionable fix hints
  and structured unsat cores instead of raw JSON dumps to keep long-context runs
  focused on repair-relevant evidence.

### OpenTelemetry Observability

Distributed tracing and token/latency metrics are **opt-in** and default to off.
Without the `otel` extra installed or with `OTEL_ENABLED` unset, every LLM/tool
span and metric instrument falls back to a NoOp implementation, so the heal /
generate / forge / proliferate flows run byte-for-byte identically.

When enabled, the whole pipeline — **MCP client → mumei-agent → `mumei verify`
→ Z3 → LLM** — can be visualized as a single distributed trace. This makes it
straightforward to identify bottlenecks in the heal / generate / forge /
proliferate loops, to monitor token consumption, solver time, and spec-drift
scores, and to track Lean bridge error rates across a run.

```bash
# Install the optional OTel dependencies
uv sync --extra otel        # or: pip install mumei-agent[otel]

# Enable and point at an OTLP backend (Jaeger, Grafana Tempo, etc.)
export OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
uv run mumei-agent heal examples/effect_test.mm
```

Three main environment variables control it:

- `OTEL_ENABLED` (default: `false`): master switch. Instrumentation is active
  only when this is truthy **and** the `opentelemetry` packages are importable;
  otherwise NoOp tracers/meters are used.
- `OTEL_EXPORTER_OTLP_ENDPOINT`: standard OTLP endpoint the SDK exports
  traces/metrics to (honored by the `opentelemetry` SDK).
- `OTEL_EXPORTER_OTLP_PROTOCOL` (default: `grpc`): OTLP wire protocol. Set to
  `http/protobuf` (or any `http*` value) to use the HTTP exporters instead of
  gRPC.

See [`docs/OBSERVABILITY.md`](./OBSERVABILITY.md) for the per-phase span
hierarchy and attribute catalogue, the metrics catalogue and PromQL examples,
the reference Grafana / Jaeger / Prometheus / Collector stack
(`docker compose -f docker-compose.otel.yml up`), and the end-to-end
distributed-trace verification procedure (mumei-agent → `mumei verify` →
Rust Z3).

### Ollama KV cache and long-context tuning

`docker-compose.yml` configures the Ollama service with:

```yaml
OLLAMA_KV_CACHE_TYPE: q8_0
OLLAMA_NUM_CTX: "32768"
```

See [`docs/OLLAMA_TUNING.md`](./OLLAMA_TUNING.md) for what these do, how to
tune them for memory-constrained machines, and future KV-cache compression
directions (TurboQuant / PolarQuant).

## Retry Budget Policy (P8-G)

Self-healing uses a budget-aware loop to avoid unbounded token spend, repeated solver work, and false success from spec weakening. By default it uses a conservative in-code policy; pass `--budget-policy` to load JSON:

```json
{
  "max_attempts": 5,
  "max_tokens": 10000,
  "max_solver_time_ms": 30000,
  "max_semantic_delta": 0.5,
  "action_class_limits": {
    "llm_fix": { "max_attempts": 3, "max_tokens": 5000, "max_lean_escalations": 0 },
    "lean_escalation": { "max_attempts": 1, "max_tokens": 5000, "max_lean_escalations": 1 }
  }
}
```

When the budget is exhausted or the same counterexample signature repeats without new information, the loop suppresses another LLM call and prints a structured `manual_review_required` summary containing the policy fingerprint, attempt counts, token/solver usage, spec drift score, and recommended action class. Successful runs aggregate `attempts_to_success`, `tokens_to_success`, `solver_seconds_to_success`, and `spec_drift_score` for quarterly feedback tuning.

## Retry Budget Policy (P8-G)

Self-healing uses a budget-aware loop to avoid unbounded token spend, repeated solver work, and false success from spec weakening. By default it uses a conservative in-code policy; pass `--budget-policy` to load JSON:

```json
{
  "max_attempts": 5,
  "max_tokens": 10000,
  "max_solver_time_ms": 30000,
  "max_semantic_delta": 0.5,
  "action_class_limits": {
    "llm_fix": { "max_attempts": 3, "max_tokens": 5000, "max_lean_escalations": 0 },
    "lean_escalation": { "max_attempts": 1, "max_tokens": 5000, "max_lean_escalations": 1 }
  }
}
```

When the budget is exhausted or the same counterexample signature repeats without new information, the loop suppresses another LLM call and prints a structured `manual_review_required` summary containing the policy fingerprint, attempt counts, token/solver usage, spec drift score, and recommended action class. Successful runs aggregate `attempts_to_success`, `tokens_to_success`, `solver_seconds_to_success`, and `spec_drift_score` for quarterly feedback tuning.
