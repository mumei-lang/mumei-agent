---
name: testing-otel-slo-alerts
description: Test the P15 OTel SLO alert/regression layer (deploy/otel/alert_rules.yml, prometheus/grafana provisioning, proliferate otel_slo_status). Use when verifying Prometheus alert rules, the docker-compose.otel.yml stack, or summary.json OTel SLO fields.
---

# Testing the OTel SLO alert layer

Covers `deploy/otel/alert_rules.yml`, the `docker-compose.otel.yml` observability stack, and `agent/proliferate.py` `_collect_otel_slo_status` / `otel_slo_status`.

## Environment / deps
- `uv sync --extra otel --extra test` — the `otel` extra (opentelemetry-{api,sdk,exporter-otlp}) is NOT installed by the default `uv sync --extra test`; you need it to emit real metrics.
- `promtool` (Prometheus CLI) is installed via the blueprint `initialize` step (pinned to the compose Prometheus version). If missing, download `prometheus-<ver>.linux-amd64.tar.gz` and copy `promtool` to `/usr/local/bin`.
- Docker is available; `docker compose -f docker-compose.otel.yml up -d` brings up collector(:4317/:4318, prom export :8889), Prometheus(:9090), Grafana(:3000), Jaeger.

## Devin Secrets Needed
- None. All testing is local (no external API keys).

## Strongest test approach (shell/API, no GUI needed)
1. **`promtool test rules <file>`** — deterministic alert firing via synthetic time series; handles `for:` windows without waiting real time. Assert each SLO violation fires the right alert (severity label + exact annotations) AND a healthy case fires nothing (anti-false-positive). This is the primary proof for the rules.
2. **Live collector name match** — set `OTEL_ENABLED=true` + `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, call `agent.telemetry` helpers (`record_first_pass_success_rate`, `record_verify_duration`, `record_fix_attempt/success`, `record_lean_bridge_result(error_code=...)`, `record_llm_tokens`), then `metrics.get_meter_provider().force_flush()`. `curl localhost:8889/metrics` and confirm every name referenced by `alert_rules.yml` appears — this proves acceptance criterion "alert metric names match telemetry.py instrument names".
3. **Backward compat** — `proliferate.proliferate(path, dry_run=True, output_json=out)` with `OTEL_ENABLED` unset → `summary.json` has trailing `otel_slo_status: null`, existing fields intact.

## Critical gotcha: Prometheus rate() ramp-up
A counter that starts at 0 is NOT extrapolated before its first sample, so `rate(counter[Nm])` reads a *fraction* of steady-state until a full `N`-minute window of data exists (e.g. at t=5m a 15m-window rate is ~1/3 of true). Consequences for promtool tests:
- Single-counter absolute-rate alerts (`MumeiLLMTokenRateSurge` 15m, `MumeiLeanFallbackErrorRateHigh` 30m) fire LATE — evaluate at `~rate_window + for` (e.g. token: eval ~40m; lean: eval ~60m), and make input series long enough (`0+Nx70`).
- Ratio alerts (`first_pass`, `fix`) and histogram p95 (`verify`) fire on time because numerator & denominator ramp proportionally — eval just after `for` (e.g. first-pass for:15m → eval 16m; fix for:30m → eval 31m).

## promtool annotation matching (gotcha)
`exp_annotations` is all-or-nothing: if you specify it, it must EXACTLY equal the full annotation map (summary + runbook_url + description). Omitting it means "expect empty annotations" and fails when the alert has any. Grab the exact rendered `description` (with humanized `$value`, e.g. "3.333k", "58.5s", "20%") from a first failing run, then paste it verbatim. A reusable, verified test file lives at `~/slo_promtool_test.yml`.

## Reference values (thresholds)
first-pass <0.70 warn / <0.40 crit; verify p95 >30s; fix ratio <0.50; lean error >0.05/s; tokens >2000/s. Summary field is `proposal_success_rate` (post self-heal/publish) — deliberately distinct from the OTel `mumei.first_pass.success_rate` instrument.
