# Agent Harness Specification

This document externalizes the `mumei-agent` control loop as a Natural-Language Agent Harness (NLAH)-style policy. It is intentionally operational: every stage names the artifacts it reads and writes, the verifier gate that accepts the stage, and the condition that stops the run.

## Scope

The harness covers these entrypoints:

- `python -m agent extract-spec`
- `python -m agent generate`
- `python -m agent heal`
- `python -m agent forge`
- `python -m agent proliferate`
- `python -m agent mcp-server`

The lower-level Python modules remain the deterministic runtime:

- `agent/spec_extractor.py` extracts natural language into forge task JSON.
- `agent/strategies/generate_strategy.py` generates `.mm` code.
- `agent/strategies/fix_strategy.py` repairs verifier failures.
- `agent/self_healing.py` owns the generate/heal retry loop.
- `agent/forge.py` runs task specs against a Mumei checkout.
- `agent/proliferate.py` discovers std gaps, generates specs, checks blast radius, publishes PRs, and optionally calls Lean.
- `agent/lean_bridge.py` is the subprocess adapter to `mumei-lean`.

## Roles

| Role | Runtime owner | Responsibility | Must not do |
| --- | --- | --- | --- |
| Planner | `spec_extractor`, `propose`, `proliferate.analyze_gaps` | Convert requirements or std gaps into explicit forge task specs. | Write `.mm` code directly without a forge task spec. |
| Generator | `generate_strategy.generate_code` | Produce candidate Mumei atoms from a validated task spec. | Treat LLM output as accepted before `mumei verify`. |
| Verifier | `MumeiClient`, `MumeiMCPClient` | Run Mumei verification and return structured JSON feedback. | Hide `unknown`, timeout, effect, or contract failures. |
| Repairer | `fix_strategy.get_fix`, `self_healing` | Convert structured verifier feedback into a bounded repair attempt. | Retry the same counterexample indefinitely. |
| Budget Controller | `budget_policy`, `budget_metrics`, retry history | Decide whether another repair/escalation is allowed. | Spend LLM calls after the budget gate says manual review is required. |
| Deep-Proof Adapter | `lean_bridge`, `proliferate._run_lean_fallback` | Hand Z3 `unknown` atoms to `mumei-lean` and merge `lean_verified` certificates. | Make Lean mandatory for flows where Z3 already proves all atoms. |
| Publisher | `publish`, `proliferate` | Persist verified artifacts, summaries, and PR metadata. | Publish code that has not passed the configured verifier gates. |

## Stage Policy

| Stage | Entrypoints | Input artifacts | Output artifacts | Verifier gate | Stop condition |
| --- | --- | --- | --- | --- | --- |
| S0 Requirement extraction | `extract-spec` | `--text`, `--text-file`, or `--code-file`; optional `--domain` | Forge task spec JSON at `--output` or `forge_tasks/<task_id>.json` | JSON parses, matches forge task schema, and `_normalize_forge_task_spec()` accepts it. | Spec accepted, or extraction retry budget exhausted. |
| S1 Task discovery | `forge`, `proliferate` | `forge_tasks/*.json` or `analyze_std_gaps` proposals | Ordered task list; optional `proliferate` summary | Task has `task_id`, `target_file`, `mode`, and non-empty `atoms`. | No tasks, `--max-tasks`, or `--max-proposals`. |
| S2 Code generation | `generate`, `forge`, `proliferate` | Forge task spec, std catalog/core context, prompt templates | Candidate `.mm` source | Code block is extractable and syntactically suitable for Mumei verification. | Candidate generated, or generation retry budget exhausted. |
| S3 Verification | all generation/heal flows | Candidate `.mm`, existing target module, Mumei binary or MCP client | `mumei verify --json` report; optional proof certificate | `success == true` or report contains actionable structured failure. | Verified, or structured failure moves to S4/S5. |
| S4 Repair | `heal`, `generate --max-retries`, `forge`, `proliferate` | Source, verifier report, retry history, pattern library, budget policy | Revised source; retry history entry; optional `manual_review_required` | `evaluate_budget()` allows the action class, and re-verification improves or passes. | Verified, or budget/manual-review gate stops. |
| S5 Blast-radius check | `proliferate` | Candidate std file plus existing `std/*.mm` | Per-file verification result list | No new std verification failures with the candidate in place. | Candidate accepted, rollback, or healing of affected files succeeds. |
| S6 Lean fallback | `proliferate --enable-lean-fallback` | Proof certificate with `z3_check_result == "unknown"` atoms, `MUMEI_LEAN_REPO` | `.lean-cert.json`, merged upgraded cert, `lean_fallback` summary | Bridge returns success and matching atoms become `lean_verified`; failures stay structured and non-fatal. | Unknown atoms discharged, skipped, or bridge failure recorded. |
| S7 Publish/report | `forge`, `proliferate`, `publish` | Verified source, proof certificate, metrics, artifacts | Commit/PR, `forge_log.json`, `summary.json`, wrapper artifacts | Publish result records success and artifact targets; no verifier regression remains hidden. | PR created, dry-run summary written, or publish error recorded. |

## Artifact Contracts

### Forge task spec JSON

Required for generation-oriented flows.

- Location: `forge_tasks/*.json`, `extract-spec --output`, or a temporary spec inside `proliferate`.
- Required fields: `task_id`, `target_file`, `mode`, `atoms`.
- Optional control fields: `max_retries`, `auto_commit`, `domain`, `difficulty`, `depends_on`.
- Acceptance: the spec must round-trip through the same schema path used by `agent.generate` and `agent.forge`.

### Candidate source

- Location: `--output`, generated temp file, or target `std/.../*.mm`.
- Acceptance: `mumei verify --json` succeeds, or the structured failure is passed to the repair/budget gate.
- Non-goal: LLM confidence, comments, or natural-language rationales never count as verification evidence.

### Verifier report / proof certificate

- Location: `MumeiClient.verify()` result, `publish_result.proof_certificate`, dry-run proof certificate attachment, or mumei-side `.proof-cert.json`.
- Required evidence: success flag, atom-level status when available, `z3_check_result`, counterexample or structured failure payload on failure.
- Acceptance: all target atoms pass Z3 (`unsat`) or are explicitly escalated/recorded as `unknown`, `lean_verified`, or manual-review-required.

### Retry and budget state

- Runtime: `RetryHistory`, `BudgetPolicy`, `BudgetDecision`, `BudgetMetrics`.
- Persisted evidence: attempt counts, token counts, solver seconds, action class, spec drift score, budget fingerprint where available.
- Acceptance: repeated counterexample signatures and exhausted budgets stop LLM calls and require manual review.

### Forge log

- Location: `forge_log.json` or `--log-path`.
- Shape: a dictionary with `runs[]` entries from `ForgeResult.to_dict()`.
- Required fields per run: `task_id`, `status`, `attempts`, `target_file`, `atoms_added`, and optional `error`.
- Acceptance: downstream MCP `list_forge_log` must be able to read the log without replaying a run.

### Proliferate summary

- Location: `python -m agent proliferate --output-json <path>`.
- Required fields: `timestamp`, `pre_health`, `post_health`, proposal counts, and `details[]`.
- Each detail keeps short-form spec metadata, code length, publish summary, proof certificate summary, thought process, and optional Lean fallback summary.
- Acceptance: the summary must be JSON-serializable without embedding large generated code bodies.

### Lean fallback summary

- Location: `details[].lean_fallback` and optional `details[].upgraded_cert_summary`.
- Required fields: `attempted`, `unknown_count`, `proved`, `success`, `returncode`.
- Acceptance: Lean failure is not hidden; Z3-proven flows remain valid without Lean.

## Failure Taxonomy

| Failure class | Source fields | Harness action |
| --- | --- | --- |
| Invalid extraction JSON | `extract_spec` parse/schema error | Retry extraction until `--max-retries`, then stop before generation. |
| Syntax or parser failure | verifier report parse failure | Repair as `llm_fix` if budget allows. |
| Precondition failure | `violation_type` / `failure_type` contains `precondition` | Prefer contract strengthening or caller-side guard repair. |
| Postcondition failure | `violation_type` / `failure_type` contains `postcondition` | Prefer implementation correction before weakening specs. |
| Effect failure | `effect_mismatch`, `effect_propagation`, temporal/effect fields | Repair declared effects or state preconditions, then re-verify. |
| Repeated counterexample | `RetryHistory.same_counterexample_signature_seen()` | Stop with `manual_review_required`; do not spend another LLM call. |
| Budget exhaustion | `max_attempts`, `max_tokens`, `max_solver_time_ms`, `max_semantic_delta`, action class limits | Stop with the budget summary attached to the report. |
| Z3 unknown / timeout | `z3_result_class`, `z3_check_result`, `escalation_reason` | If enabled and available, use Lean fallback; otherwise report as unresolved evidence. |
| Lean bridge unavailable | missing `MUMEI_LEAN_REPO`, `lake_missing`, bridge return code | Record structured fallback failure and continue non-Lean gates. |
| Blast-radius regression | existing std file newly fails | Roll back candidate, attempt bounded heal, or mark proposal failed. |
| Publish failure | `pr_error`, `git_error`, `verify_error`, `generation_error` | Preserve summary and do not claim delivery. |

## Budget and Search Policy

The default harness is single-path:

```text
spec → generate candidate → verify → repair same candidate → verify → publish
```

This is deliberate. Multi-candidate search can be useful for isolated benchmarks, but it is not the default path because it multiplies verifier cost and can make intent drift harder to attribute.

Use heavier strategies only when all are true:

1. The task has an explicit budget policy.
2. The candidates can be evaluated by the same artifact contract.
3. The summary records per-candidate success, token, solver-time, and drift.
4. A losing candidate cannot leak into the final published artifact.

## Intent Fidelity Policy

Mumei verification proves mathematical contract correctness, not automatically that the contract captured the original human intent. The harness therefore keeps intent evidence next to proof evidence:

- S0 stores natural-language requirements or a code-to-requirements source.
- S2 generation prompts include the task spec and domain hint.
- S4 budget metrics track `spec_drift_score`.
- S7 summaries preserve task IDs, target files, and proof summaries for review.

Future P13 work should add explicit `intent_fidelity_status` to run summaries and proof-certificate metadata once the mumei-side optional fields are available.

## Module Ablation Plan

These modules should be independently toggleable and measurable in later P13 implementation work:

| Module | Current control | Metric to compare |
| --- | --- | --- |
| MCP verifier delegation | `USE_MCP_CLIENT`, `PREFER_MCP_GAPS` | fallback rate, richer feedback usage, verification latency |
| Core axiom injection | `INJECT_CORE_AXIOMS`, `CORE_AXIOM_PATH` | first-pass verification success, prompt size |
| Retry budget | `--budget-policy` | attempts to success, manual-review rate, token cost |
| NLAE latent debug | `ENABLE_LATENT_DEBUG` | repair success before LLM fallback |
| Dense property generation | `ENABLE_DENSE_PROPERTIES` | proof density, Z3 unknown rate, extra LLM calls |
| Lean fallback | `--enable-lean-fallback`, `MUMEI_LEAN_REPO` | unknown atoms discharged, bridge failure rate |
| Proliferate dry-run | `--dry-run` | proposal quality without git/PR side effects |

## Review Checklist

Before a harness-changing PR is merged, confirm:

- The PR names the stage(s) it changes.
- Every new artifact has a documented path and schema owner.
- Every new verifier or fallback path has a structured failure result.
- The default path remains bounded by retry and budget policy.
- New summaries are JSON-serializable and avoid embedding large generated code.
- Existing entrypoints keep their current behavior unless the PR explicitly announces a migration.
