# Observability (OpenTelemetry, P15)

mumei-agent emits OpenTelemetry **traces** and **metrics** covering the whole
verification-driven agent loop, and — when the `mumei` binary is built with the
`otel` feature — the trace extends into the Rust compiler / Z3 layer through
`TRACEPARENT` propagation. This document covers the operational side: how to
enable instrumentation, how to run the reference OTLP backend stack, the span
hierarchy and metrics catalogue, and how to verify the end-to-end distributed
trace from **MCP client → mumei-agent → `mumei verify` subprocess → Rust Z3**.
Section (f) covers the complementary compiler-side stream: the proof-aware
runtime monitors emitted by `--emit runtime-monitor` (P23) and how their
trust-boundary violations reach the same OTLP endpoint.

Everything here is **opt-in**. With `OTEL_ENABLED` unset (the default) or the
`otel` extra not installed, every span and instrument falls back to a NoOp, so
the heal / generate / forge / proliferate flows run byte-for-byte identically.

---

## (a) Enabling instrumentation in the agent

```bash
# Install the optional OTel dependencies
uv sync --extra otel          # or: pip install mumei-agent[otel]

# Enable and point at an OTLP endpoint (the reference collector below listens
# on gRPC :4317 and HTTP :4318).
export OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
# Optional: switch to the HTTP exporter (defaults to grpc).
# export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf   # -> use :4318

uv run mumei-agent heal examples/effect_test.mm
```

| Variable | Purpose | Default |
|---|---|---|
| `OTEL_ENABLED` | Master switch; instrumentation is active only when truthy **and** the `opentelemetry` packages are importable. | `false` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Standard OTLP endpoint the SDK exports traces/metrics to. | (SDK default) |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` (→ :4317) or `http/protobuf` (→ :4318). | `grpc` |

See [Per-phase span & attribute catalogue](#per-phase-span--attribute-catalogue)
under section (c) for the full span/attribute breakdown per instrumentation
phase.

---

## (b) Running the reference OTLP backend stack

A local, opt-in reference stack is provided in
[`docker-compose.otel.yml`](../docker-compose.otel.yml). It is **not** required
for normal agent operation — it only visualizes the telemetry the agent emits.
Config files live under [`deploy/otel/`](../deploy/otel/).

```
             OTLP (4317 gRPC / 4318 HTTP)
mumei-agent ───────────────────────────►  otel-collector
 mumei (Rust, --features otel)                 │
                                    traces ─────┼──► jaeger      (UI :16686)
                                    metrics ────┴──► :8889 ◄── prometheus (:9090)
                                                                     ▲
                                                              grafana (:3000)
```

```bash
# Start the stack (Collector + Jaeger + Prometheus + Grafana)
docker compose -f docker-compose.otel.yml up -d

# Point the agent at the collector and run one flow
export OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
uv run mumei-agent heal examples/effect_test.mm
```

| Service | Image | URL | Notes |
|---|---|---|---|
| otel-collector | `otel/opentelemetry-collector-contrib` | gRPC `:4317`, HTTP `:4318`, Prom `:8889` | Routes traces → Jaeger, metrics → Prometheus exporter. |
| jaeger | `jaegertracing/all-in-one` | http://localhost:16686 | Trace visualization UI. |
| prometheus | `prom/prometheus` | http://localhost:9090 | Scrapes the collector's `:8889` exporter. |
| grafana | `grafana/grafana` | http://localhost:3000 | Anonymous admin, login disabled. Datasources + the *Mumei Agent Observability (P15)* dashboard are auto-provisioned. |

Ports are chosen to avoid colliding with the Ollama service in the primary
`docker-compose.yml` (`:11434`); the two compose files can run simultaneously.
All published ports bind to `127.0.0.1` (loopback) only, so the stack — including
Grafana's anonymous-admin UI — is never exposed on other network interfaces. To
reach it from another host, use SSH port-forwarding rather than changing the
bind address.

Tear down with `docker compose -f docker-compose.otel.yml down` (add `-v` to
also drop the Grafana volume).

### Grafana dashboard

The dashboard JSON lives in
[`deploy/otel/dashboards/mumei-agent-observability.json`](../deploy/otel/dashboards/mumei-agent-observability.json)
and is auto-loaded via provisioning
([`deploy/otel/grafana/provisioning/`](../deploy/otel/grafana/provisioning/)).
Open Grafana → *Dashboards* → *Mumei* → *Mumei Agent Observability (P15)*. It
visualizes:

- **LLM tokens/cost** — `gen_ai.usage.total_tokens` by `gen_ai.request.model`.
- **Verify latency** — `mumei.verify.duration` p50 / p95.
- **Fix success rate** — `mumei.fix.successes` / `mumei.fix.attempts` by `violation_type`.
- **Z3 unknowns** — `mumei.z3.unknowns` (and decidable-fragment warnings).
- **Harness** — `mumei.harness.tokens_to_success` / `solver_seconds_to_success` / `spec_drift_score` (p95, by `stage`/`module`).
- **Lean bridge** — `mumei.lean.verified_count` / `mumei.lean.bridge.duration` / `mumei.lean.bridge.error_code`.

---

## (c) Span hierarchy and metrics catalogue

### Span hierarchy

A single distributed trace nests as follows (each layer is NoOp when disabled):

```
mcp.tool.*                         (P15-4, MCP server tool entry point)
└─ mumei.loop.*                    (P15-3: heal / generate / self_correction / ...)
   │  ├─ mumei.proliferate / mumei.nlae.pipeline / mumei.audit.*   (P15-6 pipelines)
   └─ mumei.verify                 (P15-2, Python-side subprocess wrapper)
      └─ mumei.verify.cli          (Rust side, --features otel, parented via TRACEPARENT)
         └─ mumei.z3.solve         (Rust side, per-atom Z3 solve)
   └─ llm.complete / mcp_sampling.complete   (P15-1, LLM chokepoint)
```

`mumei.mcp.*` spans (`mumei.mcp.verify`, ...) appear as a distinct MCP-routing
layer above `mumei.verify` when calls go through `MumeiMCPClient`.

### Metrics catalogue

All instruments are a parallel OTel channel — the JSON metrics
(`Metrics.to_dict()`, `HarnessMetrics.aggregate_metrics()`) are unchanged. The
Prometheus names below reflect the collector's prometheus exporter naming
(dots → underscores, unit suffixes, `_total` for counters). Note the collector
collapses the redundant `total` in `gen_ai.usage.total_tokens`, exporting it as
`gen_ai_usage_tokens_total` (not `..._total_tokens_total`).

| OTel instrument | Type | Prometheus name | Key attributes/labels |
|---|---|---|---|
| `gen_ai.usage.total_tokens` | Counter | `gen_ai_usage_tokens_total` | `gen_ai.request.model` |
| `mumei.verify.duration` | Histogram (s) | `mumei_verify_duration_seconds_*` | — |
| `mumei.first_pass.success_rate` | Histogram (1) | `mumei_first_pass_success_rate_*` | — |
| `mumei.z3.unknowns` | Counter | `mumei_z3_unknowns_total` | — |
| `mumei.decidable_fragment.warnings` | Counter | `mumei_decidable_fragment_warnings_total` | `mumei.logic_fragment.tags` |
| `mumei.fix.attempts` | Counter | `mumei_fix_attempts_total` | `mumei.violation_type` |
| `mumei.fix.successes` | Counter | `mumei_fix_successes_total` | `mumei.violation_type` |
| `mumei.harness.tokens_to_success` | Histogram | `mumei_harness_tokens_to_success_*` | `stage`, `module`, `profile` |
| `mumei.harness.solver_seconds_to_success` | Histogram (s) | `mumei_harness_solver_seconds_to_success_*` | `stage`, `module`, `profile` |
| `mumei.harness.spec_drift_score` | Histogram (1) | `mumei_harness_spec_drift_score_*` | `stage`, `module`, `profile` |
| `mumei.lean.bridge.duration` | Histogram (s) | `mumei_lean_bridge_duration_seconds_*` | — |
| `mumei.lean.verified_count` | Counter | `mumei_lean_verified_count_total` | — |
| `mumei.lean.bridge.error_code` | Counter | `mumei_lean_bridge_error_code_total` | `mumei.lean.error_code` |

Example PromQL:

```promql
# Fix success rate by violation type
sum(rate(mumei_fix_successes_total[5m])) by (mumei_violation_type)
/ sum(rate(mumei_fix_attempts_total[5m])) by (mumei_violation_type)

# P95 verify duration
histogram_quantile(0.95, sum(rate(mumei_verify_duration_seconds_bucket[5m])) by (le))
```

### Per-phase span & attribute catalogue

Instrumentation was rolled out in six phases (P15 Phase 1-6). Every span below
is `is_enabled()`-guarded and NoOp when OTel is disabled or the `otel` extra is
not installed; all instrumentation is purely additive and never changes JSON
outputs (`Metrics.to_dict()`, `HarnessMetrics.aggregate_metrics()`,
`ThoughtProcess.to_dict()`, `proliferate()`'s `summary.json`,
`NLAEResult.to_dict()`, and the `AuditResult` / `AuditDirectoryResult`
dataclasses).

#### Phase 1 — LLM call sites

All LLM call sites are instrumented. `OpenAILLMProvider.complete` and
`McpSamplingLLMProvider.complete` emit spans with `gen_ai.request.model`,
`gen_ai.system`, `server.address`, and `gen_ai.usage.total_tokens`; token usage
is also reported to the `gen_ai.usage.total_tokens` counter (tagged with the
`gen_ai.request.model` attribute) as a parallel channel that never changes the
JSON metrics output. MCP sampling requests carry a W3C `traceparent` in their
metadata for cross-process trace propagation.
`McpSamplingLLMProvider.complete_with_tools` has its own
`mcp_sampling.complete_with_tools` span with `tool_count` and `tool_choice`
attributes. The dispatch functions `complete_text` / `complete_response` emit
`llm.complete_text` / `llm.complete_response` spans with `gen_ai.dispatch_path`
identifying the routing decision. All 8 direct
`client.chat.completions.create` call sites (spec refinement, multi-stage fix,
diagnose, CEGIS invariant synthesis, spec extraction, code-to-spec, dense
property generation, ambiguity detection) are individually instrumented with
`llm.*` spans.

#### Phase 2 — Z3 verification subprocess

Every `MumeiClient` / `MumeiMCPClient` CLI subprocess call is wrapped in an OTel
span (`mumei.verify`, `mumei.check`, `mumei.infer_effects`,
`mumei.infer_contracts`, `mumei.build`) with attributes `mumei.command`,
`mumei.source_path`, `mumei.exit_code`, `mumei.duration_ms`,
`mumei.stdout.size`, and `mumei.stderr.size`. The `mumei.verify` span
additionally carries `mumei.verification.duration_ms`,
`mumei.collect_decidable_metrics`, `mumei.decidable_fragment.present`, and
`mumei.loss_vector.present`. Failed verifications that trigger a loss-vector
re-run produce a child span `mumei.verify.loss_vector`. `MumeiMCPClient` wraps
the same methods under `mumei.mcp.*` span names (`mumei.mcp.verify`,
`mumei.mcp.check`, etc.) so MCP routing and CLI execution appear as distinct
layers in the trace. Verification wall-clock time is also reported to the
`mumei.verify.duration` histogram (unit: seconds) as a parallel OTel metrics
channel.

#### Phase 3 — Per-loop root spans & `ThoughtProcess` events

- **`mumei.loop.generate`** — wraps the `generate_code` / `generate_multi_atom`
  retry loop in `generate_strategy.py`. Attributes:
  `mumei.loop.type=generate`, `mumei.strategy` (`single` / `multi-stage`),
  `mumei.loop.max_retries`, `mumei.loop.final_success`, `mumei.loop.attempt`.
- **`mumei.loop.heal`** — wraps the `main()` heal loop in `self_healing.py`.
  CEGIS repair, Meta-Architect refactor, and LLM fix branches emit span events.
  Attributes: `mumei.loop.stop_reason` (`success` / `max_retries_exhausted` /
  `budget_denied`), `mumei.loop.final_success`, `mumei.loop.attempt`.
- **`mumei.loop.self_correction`** — wraps
  `StructuredFeedbackSelfCorrectionLoop.run` in `self_correction.py`.
  `stop_reason` (`converged` / `max_retries_reached` / `token_cost_exceeded` /
  `no_fix_produced` / `hard_repair_limit_reached`) is mapped to
  `mumei.loop.stop_reason`.
- **`mumei.loop.self_correction_strategy`** — wraps
  `SelfCorrectionStrategy.run` in `self_correction_strategy.py`.
  `action_class` / `budget_policy` decisions are emitted as span events;
  `mumei.budget_policy.fingerprint` is set as a span attribute.
- **`ThoughtProcess.add_step()`** emits an OTel span event on the current span
  for each verification step (`initial_verify`, `re_verify`, `llm_fix`).

#### Phase 4 — MCP server tool entry points

MCP server tool entry points are instrumented so external MCP clients (Claude
Code, Devin, ...) become the top of a single distributed trace. Each
instrumented tool opens an `mcp.tool.<name>` span (e.g. `mcp.tool.forge_task`,
`mcp.tool.heal_file`, `mcp.tool.self_correct`, `mcp.tool.run_nlae_pipeline`,
`mcp.tool.audit_code`, `mcp.tool.scan_and_fix`,
`mcp.tool.extract_spec_from_code`, plus the lightweight
`mcp.tool.measure_std_health` / `mcp.tool.propose_forge_tasks` /
`mcp.tool.list_forge_log` / `mcp.tool.get_agent_status`) carrying
`mcp.tool.name` and tool-specific attributes (`mcp.tool.dry_run` /
`mcp.tool.task_id` / `mcp.tool.status` for `forge_task`, `mumei.heal.kind` for
`heal_file`, `mcp.tool.max_iterations` for `self_correct`, `mcp.tool.no_build`
for `run_nlae_pipeline`, `mcp.tool.generate` for `extract_spec_from_code`,
`mumei.language` for `audit_code` / `scan_and_fix`). Directory heals
additionally emit a per-file `mcp.tool.heal_file.file` child span. Because the
entry span is the current span, the loop root spans (`mumei.loop.*`) and verify
spans (`mumei.verify`) nest underneath it automatically.

`telemetry.extract_trace_context(carrier)` is the inverse of
`inject_trace_context`: given a W3C `traceparent` / `tracestate` carrier it
returns the OTel `Context` to start the entry span as a child of. An external
MCP client connects its trace by attaching `traceparent` / `tracestate` to the
request `_meta`; the server reads it via `ctx.request_context.meta`
(`_carrier_from_ctx`) and parents the `mcp.tool.<name>` span on it, so
**MCP client → tool → inner loop → verify subprocess → LLM** appear as one
trace. When no context is present the entry span behaves as a fresh root
(backward compatible). With `OTEL_ENABLED` unset, `extract_trace_context`
returns `None` and every entry span is a NoOp.

#### Phase 5 — JSON metrics → OTel Metrics

The `Metrics`, `HarnessMetrics`, and `run_lean_bridge` code paths emit the OTel
instruments listed in the [Metrics catalogue](#metrics-catalogue) above (all
no-op when disabled). Dimension attributes: `mumei.violation_type` on fix
counters, `stage`/`module`/`profile` on harness histograms, and
`mumei.lean.error_code` on the bridge error counter. `to_dict()` /
`aggregate_metrics()` / return-value dicts remain byte-for-byte identical; OTel
is purely additive.

#### Phase 6 — Long-running pipeline root/child spans

The three long-running Python pipelines are wrapped in root/child spans so a
single proliferate / NLAE / audit run appears as one hierarchical trace, with
the `mumei.verify` (P15-2) and `mumei.loop.*` (P15-3) spans nesting underneath
automatically.

- **`mumei.proliferate`** — wraps the whole `proliferate()` weekly run.
  Attributes: `mumei.proliferate.max_proposals`, `mumei.proliferate.dry_run`,
  `mumei.proliferate.harness_profile`, `mumei.proliferate.proposals_found`.
  Child spans: `mumei.proliferate.gap_analysis`,
  `mumei.proliferate.spec_generation`, `mumei.proliferate.forge`, and
  `mumei.proliferate.lean_fallback`. Because `_parallel_forge` runs on a
  `ThreadPoolExecutor`, the submitting thread's context is captured with
  `telemetry.capture_context()` and re-attached in each worker via
  `telemetry.use_context()`, so every `mumei.proliferate.forge.candidate`
  worker span (attributes `mumei.proliferate.target_file`,
  `mumei.proliferate.verified`, `mumei.proliferate.cache_hit`) parents onto the
  `mumei.proliferate.forge` span rather than becoming an orphan root. Each
  publish iteration opens a `mumei.proliferate.proposal` span
  (`mumei.proliferate.target_file`, `mumei.proliferate.verified`,
  `mumei.proliferate.blast_radius_broken`, `mumei.proliferate.healed`).
- **`mumei.nlae.pipeline`** — wraps `NLAEPipeline.run_full_pipeline`. The four
  stages are child spans `mumei.nlae.generate`, `mumei.nlae.verify`,
  `mumei.nlae.self_correction`, and `mumei.nlae.lean_bridge`. Attributes:
  `mumei.nlae.verified`, `mumei.nlae.lean_verified`,
  `mumei.nlae.loss_vector.present`. The root span's 32-hex trace ID is surfaced
  on the optional `NLAEResult.trace_id` field (default `None`, present only as
  the last dataclass field so `to_dict()` stays backward compatible). When the
  pipeline is invoked through the `run_nlae_pipeline` MCP tool, that
  `mcp.tool.run_nlae_pipeline` entry span is the current span, so
  `mumei.nlae.pipeline` nests underneath it and `trace_id` lets a caller follow
  the distributed trace back to the originating MCP request across the
  mumei-agent / mumei / mumei-lean / mumei-demo repositories.
- **`mumei.audit.file` / `mumei.audit.directory` / `mumei.audit.source`** —
  wrap `AuditPipeline.audit_file` / `audit_directory` / `audit_source`. A
  directory audit's per-file `audit_file` calls appear as sequential
  `mumei.audit.file` child spans under the `mumei.audit.directory` span.
  Attributes: `mumei.audit.language`, `mumei.audit.success`,
  `mumei.audit.violations` (file / source) and `mumei.audit.files_with_issues`
  (directory).

#### Rust compiler-side integration

When the `mumei` binary is built with `--features otel` and `OTEL_ENABLED=true`,
`MumeiClient` methods automatically inject `TRACEPARENT` into the subprocess
environment. The Rust side extracts this context and parents its
`mumei.verify.cli` / `mumei.z3.solve` spans under the Python caller's span,
creating a single end-to-end distributed trace from **MCP client →
mumei-agent → mumei verify → Z3**. See section (d) below for the verification
procedure.

---

## (d) Verifying the end-to-end distributed trace

The distributed trace crosses the Python → Rust boundary via the W3C
`TRACEPARENT` environment variable. When `OTEL_ENABLED=true`, `MumeiClient`
injects the current span's `traceparent` into the `mumei` subprocess
environment; a `mumei` binary built with `--features otel` extracts it and
parents its `mumei.verify.cli` / `mumei.z3.solve` spans under the Python caller.

**1. Build an `otel`-enabled `mumei` binary** (in the `mumei-lang/mumei` repo):

```bash
LLVM_SYS_170_PREFIX=/usr/lib/llvm-17 LIBCLANG_PATH=/usr/lib/x86_64-linux-gnu \
  cargo build --features otel
export MUMEI_BIN="$PWD/target/debug/mumei"
```

**2. Start the reference stack and run the agent** against it (see section b),
pointing `MUMEI_BIN` at the `otel` build so the subprocess is trace-aware.
Use the **OTLP/HTTP** endpoint (`:4318`) for this flow: the `mumei` binary's
exporter is HTTP-only, and the agent passes its own `OTEL_EXPORTER_OTLP_*`
environment through to the `mumei` subprocess, so both sides must agree on a
protocol the Rust side supports.

```bash
docker compose -f docker-compose.otel.yml up -d
export OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
uv run mumei-agent heal examples/effect_test.mm
```

> The Python agent alone also works over gRPC (the default,
> `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`); HTTP/`:4318` is required
> only when you want the spawned `mumei` subprocess to export into the same
> collector.

**3. Confirm in Jaeger** (http://localhost:16686): select service
`mumei-agent`, open a recent trace, and confirm the span chain
`mcp.tool.*` → `mumei.loop.*` → `mumei.verify` → `mumei.verify.cli` →
`mumei.z3.solve`. The Rust `mumei.verify.cli` / `mumei.z3.solve` spans share the
**same trace ID** as the Python spans — that is the end-to-end proof.

**4. Confirm metrics in Grafana** (http://localhost:3000): the *Mumei Agent
Observability (P15)* dashboard should plot `mumei.verify.duration` and the
`mumei.fix.*` panels once a flow has run.

### Manual single-command check

```bash
# Emulate a caller-provided trace context and run verify directly.
# The mumei binary exports over OTLP/HTTP, so target :4318.
OTEL_ENABLED=true \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
TRACEPARENT="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" \
  "$MUMEI_BIN" verify examples/effect_test.mm
```

The resulting `mumei.verify.cli` → `mumei.z3.solve` spans appear in Jaeger under
trace ID `0af7651916cd43dd8448eb211c80319c`.

---

## (e) Alerts / SLO

The reference stack ships an SLO-based alerting layer on top of the metrics
above. Prometheus alert rules live in
[`deploy/otel/alert_rules.yml`](../deploy/otel/alert_rules.yml) (registered via
`rule_files` in [`deploy/otel/prometheus.yml`](../deploy/otel/prometheus.yml)),
and Grafana provisions a webhook contact point plus notification policy under
[`deploy/otel/grafana/provisioning/alerting/`](../deploy/otel/grafana/provisioning/alerting/).
The Grafana dashboard's *SLO thresholds & alerts (P15 …)* row renders the
threshold lines and an alert-state panel.

The alert expressions query the Prometheus names in the metrics catalogue
above, which are kept in strict correspondence with the OTel instrument names
in `agent/telemetry.py`. Validate the rules with:

```bash
promtool check rules deploy/otel/alert_rules.yml
```

Notifications route to the `mumei-slo-webhook` contact point, a placeholder
local webhook (`http://host.docker.internal:5001/mumei-slo`) so alerts can be
observed end-to-end without a real pager. Point it at any local HTTP sink
(e.g. `python -m http.server 5001` or a webhook tunnel) for verification.

> **Notes for local verification**
> - On **Linux**, `host.docker.internal` is not resolved by Docker by default.
>   Add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `grafana`
>   service in `docker-compose.otel.yml` (or point the contact point at your
>   host's LAN/bridge IP) so notifications can reach a sink on the host.
> - The alert rules run in **Prometheus**; the authoritative firing state is at
>   Prometheus → *Alerts* (http://localhost:9090/alerts). The dashboard's
>   `alertlist` panel lists **Grafana-managed** alerts (none are provisioned
>   here), so the SLO row is primarily for the threshold-line visualisations.

| Alert | Severity | Expression (summary) | Threshold |
|---|---|---|---|
| `MumeiFirstPassSuccessRateLow` / `Critical` | warning / critical | mean of `mumei_first_pass_success_rate_{sum,count}` | < 0.70 / < 0.40 |
| `MumeiVerifyLatencyP95High` | warning | p95 of `mumei_verify_duration_seconds_bucket` | > 30s |
| `MumeiFixSuccessRateLow` | warning | `rate(mumei_fix_successes_total)` / `rate(mumei_fix_attempts_total)` | < 0.50 |
| `MumeiLeanFallbackErrorRateHigh` | warning | `rate(mumei_lean_bridge_error_code_total)` by `mumei_lean_error_code` | > 0.05/s |
| `MumeiLLMTokenRateSurge` | warning | `rate(gen_ai_usage_tokens_total)` | > 2000 tok/s |

To exercise the alerts locally, bring the stack up
(`docker compose -f docker-compose.otel.yml up -d`), run agent flows with
`OTEL_ENABLED=true`, and watch Prometheus → *Alerts* (http://localhost:9090/alerts)
or the Grafana SLO row transition to firing when an SLO is violated.

### First-pass verification success rate

**What it means.** The share of atoms that pass verification on the first
attempt (`mumei.first_pass.success_rate`). A sustained drop means generated
specs/code are increasingly failing before any self-healing.

**Runbook.** Inspect recent `mumei.z3.unknowns` and decidable-fragment
warnings; review spec-extraction / generation prompt quality and the LLM model
in use. A critical breach (< 40%) usually indicates a model or prompt
regression rather than task difficulty.

### Verify latency p95

**What it means.** The p95 wall-clock time of `mumei verify` subprocess calls
(`mumei.verify.duration`). Spikes point at slow Z3 solves or subprocess/IO
overhead.

**Runbook.** Correlate with the Jaeger `mumei.verify.cli` → `mumei.z3.solve`
spans for the slow traces; check for pathological atoms (non-linear arithmetic,
large quantifier alternation) and consider Lean escalation.

### Fix success rate

**What it means.** `rate(mumei.fix.successes) / rate(mumei.fix.attempts)` — how
often the self-healing loop repairs a violation. A drop means the loop is
burning attempts without converging.

**Runbook.** Break down by `mumei_violation_type` on the *Fix success rate*
panel to find the failing class; inspect loss vectors / counterexamples for
that violation type.

### Lean fallback error rate

**What it means.** The rate of `mumei.lean.bridge.error_code` increments,
labelled by `mumei_lean_error_code`. A rising rate means Z3 `unknown` atoms are
failing Lean escalation.

**Runbook.** Check the `error_code` label (`lake_missing`, `stale_translator`,
…). `lake_missing` indicates a toolchain/availability issue rather than a proof
failure; `stale_translator` means the certificate/bridge versions diverged.

### LLM token cost

**What it means.** `rate(gen_ai.usage.total_tokens)` — token consumption per
second. A surge signals runaway retries or an unexpectedly expensive model.

**Runbook.** Break down by `gen_ai_request_model`; check for retry storms in
the self-healing loop and confirm the configured `LLM_MODEL` matches
expectations.

---

## (f) Proof-aware runtime monitors (P23)

Sections (a)-(e) cover telemetry the *agent* emits. The compiler emits a second,
complementary stream: `mumei build --emit runtime-monitor` (in
`mumei-lang/mumei`) generates Rust guards around **trust boundaries only** —
atoms that are `trusted`, `extern`-backed, or that assume an effect state via
`effect_pre`. An atom whose proof is self-contained produces no artifact at all,
so proven code stays zero-cost and the generated monitor pulls in no OTel
dependency of its own.

```bash
# in mumei-lang/mumei
LLVM_SYS_170_PREFIX=/usr/lib/llvm-17 LIBCLANG_PATH=/usr/lib/x86_64-linux-gnu \
  cargo run -- build path/to/spec.mm --emit runtime-monitor --output out/mon
# -> out/mon_<atom>.monitor.rs, one per trust-boundary atom (none for proven atoms)
```

### Violation events

Each guard reports a `mumei_monitor::Violation` instead of panicking — the
monitor observes, it never aborts the program:

| Field | Meaning |
|---|---|
| `atom` | Monitored atom name. |
| `boundary` | Why the atom is a trust boundary: `trusted_atom`, `extern_ffi`, `effect_pre_override` (joined with `+` when several apply). |
| `contract` | `requires`, `ensures`, `effect_pre`, or `requires_unchecked` / `ensures_unchecked` when the contract is not expressible as a runtime condition and is left to verification. |
| `expression` | The contract text that was checked (`"<effect>: <state>"` for `effect_pre`). |
| `observed` | Effect state the host reported for an `effect_pre` violation, or `"evaluation panicked"` when the contract itself faulted. |

Reporting is a no-op unless `OTEL_ENABLED` is truthy — the same switch the agent
uses — and the default hook writes one line per violation to stderr, naming the
configured endpoint:

```
mumei.monitor.contract_violation atom=read_clock boundary=trusted_atom contract=requires expression=x > 0 observed=-
```

### Wiring monitors into the P15 reference stack

The monitor reports through a host-installed hook, so the host application owns
the OTel SDK. Point it at the collector from section (b) — the generated runtime
defaults `OTEL_EXPORTER_OTLP_ENDPOINT` to `http://localhost:4318`, which is the
reference collector's OTLP/HTTP port, the same endpoint the `otel`-built `mumei`
binary exports to.

```rust
// host application startup, once
mumei_monitor::set_violation_hook(|v| {
    // e.g. tracing/opentelemetry: record as a span event on the current span
    tracing::event!(
        tracing::Level::WARN,
        atom = v.atom,
        boundary = v.boundary,
        contract = v.contract,
        expression = v.expression,
        observed = v.observed.as_deref().unwrap_or("-"),
        "mumei.monitor.contract_violation",
    );
})
.expect("hook installed once");

// optional: without a probe the runtime effect state is unobservable and
// `effect_pre` assumptions stay unchecked
mumei_monitor::set_effect_state_probe(|effect| current_state_of(effect));
```

```bash
docker compose -f docker-compose.otel.yml up -d
export OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
./your-app-linked-against-the-monitors
```

Because the hook runs inside the host's own tracer, violations land on whatever
span is current. When the host is invoked underneath an agent flow (section d),
that is the `mumei.verify.cli` / `mumei.loop.*` trace, so a runtime violation at
a trust boundary and the proof obligation it corresponds to share a trace ID in
Jaeger. Filter with `mumei.monitor.contract_violation` and group by `boundary` /
`contract` to see which trust boundaries actually break at runtime.

### Summarizing violations from the agent

With no hook installed the default stderr lines above are the agent-observable
surface: they are stable, single-line, and `key=value`-shaped, so an agent that
runs a monitored binary can aggregate them by `atom` / `boundary` / `contract`
without parsing Rust. A rising `contract=effect_pre` count is the runtime
counterpart of a P22 `session_protocol_violations[]` finding — the same protocol
assumption, observed instead of proven — and both map to `missing_constraints[]`
on the agent side (see `docs/VERIFICATION_WORKFLOW_GUIDE.md` § 3-2).

---

## Related

- README → *OpenTelemetry Observability* — opt-in enablement summary and env vars.
- `docs/ROADMAP.md` § P15 — status and design.
- `mumei-lang/mumei` `docs/ROADMAP.md` § P15 — Rust compiler-side `otel` feature and `TRACEPARENT` handling.
