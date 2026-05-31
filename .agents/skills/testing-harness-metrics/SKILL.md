---
name: testing-harness-metrics
description: Test mumei-agent harness metrics and harness-profile CLI flows. Use when verifying agent/harness_metrics.py, budget_metrics integration, or Forge/proliferate --harness-profile changes.
---

# Devin Secrets Needed

None for deterministic harness metrics/profile testing. Use parser checks, `HarnessMetrics`, `budget_metrics`, and mocked/runtime `Metrics` objects.

Live Forge/proliferate execution that calls an LLM requires `LLM_API_KEY` or `OPENAI_API_KEY`; live compiler verification may require a reachable `mumei` binary or `MUMEI_BIN`. Do not claim live execution unless those are explicitly available and used.

# When to Use

Use this skill for PRs touching:
- `agent/harness_metrics.py`
- `agent/budget_metrics.py` harness summary integration
- Forge/proliferate `--harness-profile` parser or runtime wiring
- Tests around module ON/OFF, module comparison, cost, drift, or retry/intent status aggregation

# Setup Checks

1. Confirm the repo has no browser UI path for the changed behavior; prefer shell/runtime probes.
2. Read the existing blueprint and follow its commands. The current repo blueprint uses:
   ```bash
   pip install -e ".[test]"
   if [ -f .pre-commit-config.yaml ]; then pre-commit run --all-files; else echo "No .pre-commit-config.yaml; skipping pre-commit"; fi
   ```
3. Check PR CI and comments before execution.
4. Inventory secrets. Deterministic harness metrics tests should not require secrets.

# Runtime Test Shape

Create a temporary/uncommitted probe or run an inline Python script that verifies all of these in one flow:

1. CLI parser profile wiring:
   - Build Forge's parser with `agent.forge.build_parser()`.
   - Parse `['--dry-run', '--harness-profile', 'full']`.
   - Assert `args.harness_profile == 'full'`.
   - Build proliferate's parser with `agent.proliferate.build_parser()`.
   - Parse `['--mumei-repo', '/tmp/mumei', '--harness-profile', 'lean_fallback']`.
   - Assert `args.harness_profile == 'lean_fallback'`.

2. Profile metadata and module comparison:
   - Instantiate `HarnessMetrics.from_profile('full')`.
   - Call `apply_to_spec({'task_id': 'ablation'})`.
   - Assert `harness_profile == 'full'`, `enable_multi_candidate_search is True`, `enable_lean_fallback is True`, and `enable_self_evolution is True`.
   - Record one successful `artifact_contract` stage with nonzero attempts/tokens/solver seconds/drift.
   - Record one failed `verification_gate` stage with distinct tokens/solver seconds/drift.
   - Assert `aggregate_metrics()['module_comparison']` contains concrete rows for both modules plus no-record enabled modules.
   - Assert success rates, `attempts_to_success`, `cost.tokens_to_success`, `cost.solver_seconds_to_success`, `max_spec_drift_score`, `retry_class`, and `intent_fidelity_status` exactly match the probe inputs.

3. Budget summary integration:
   - Create a `RetryHistory` with one `RetryAttempt`.
   - Call `aggregate_metrics(history, harness).aggregate_summary()`.
   - Assert `summary['harness_metrics']['profile']` is the selected profile and budget fields remain present.

4. Proliferate metrics payload compatibility:
   - Create an `agent.metrics.Metrics()` object with `total_attempts`, `llm_tokens_used`, and `verification_times_seconds` set.
   - Call `agent.proliferate._metrics_payload(metrics)`.
   - Assert the payload key is `attempts`, not `attempts_to_success`, and that solver seconds are summed.

# Acceptance Commands

Run the focused acceptance test:

```bash
python -m pytest -q tests/test_harness_metrics.py
```

Expected result:

```text
6 passed
```

If full CI failed on proliferate dry-run behavior, also run targeted proliferate tests around the failing call sites before pushing fixes.

# Reporting

- No screen recording is needed for shell-only testing.
- Save the probe stdout and focused pytest output in the test report.
- For open PRs, post one collapsed PR comment listing exact pass/fail assertions and include the Devin session link.
- Explicitly state whether live LLM/compiler execution was not performed, so reviewers do not overinterpret deterministic parser/metrics evidence.
