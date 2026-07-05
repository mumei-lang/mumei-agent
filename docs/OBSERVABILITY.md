# Observability (OpenTelemetry, P15)

mumei-agent emits OpenTelemetry **traces** and **metrics** covering the whole
verification-driven agent loop, and — when the `mumei` binary is built with the
`otel` feature — the trace extends into the Rust compiler / Z3 layer through
`TRACEPARENT` propagation. This document covers the operational side: how to
enable instrumentation, how to run the reference OTLP backend stack, the span
hierarchy and metrics catalogue, and how to verify the end-to-end distributed
trace from **MCP client → mumei-agent → `mumei verify` subprocess → Rust Z3**.

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

See the README's *OpenTelemetry Observability* section for the per-phase span
attribute catalogue.

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

## Related

- README → *OpenTelemetry Observability (opt-in, P15 Phase 1-6)* — per-phase span/attribute catalogue.
- `docs/ROADMAP.md` § P15 — status and design.
- `mumei-lang/mumei` `docs/ROADMAP.md` § P15 — Rust compiler-side `otel` feature and `TRACEPARENT` handling.
