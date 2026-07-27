# NLAE Guide

`mumei-agent` ships lightweight Natural Language Autoencoder-inspired features for denser generation and earlier repair attempts. Latent-space debugging and dense property generation are disabled by default. The latent protocol for inter-agent communication, and the multi-agent verification workflow built on it, remain disabled by default.

## Latent-space debugging

Latent debugging runs at the start of `agent.strategies.fix_strategy.get_fix()` when `ENABLE_LATENT_DEBUG` is enabled.

1. `LatentEncoder` converts the current `.mm` source and verifier report into a deterministic NumPy feature vector.
2. `LatentDebugStrategy` derives a bug-direction vector from verifier metadata such as `violation_type`, `failure_type`, counterexamples, and unsat-core data.
3. `LatentDecoder` applies conservative source edits, such as effect adjustments, tautological requires strengthening, or safe ensures weakening.
4. If the candidate is empty, unchanged, invalid, or raises an exception, the strategy falls back to the existing rule-based and LLM repair path.

Enable it explicitly for a heal or generate run:

```bash
ENABLE_LATENT_DEBUG=true python -m agent heal path/to/file.mm
ENABLE_LATENT_DEBUG=true python -m agent generate --spec-file spec.json --output out.mm
```

## Dense property generation

Dense property generation runs after initial code generation when `ENABLE_DENSE_PROPERTIES` is enabled.

1. `DensePropertyGenerator` extracts existing `requires` and `ensures` clauses from generated code.
2. It asks the configured LLM for compact, mathematically precise replacements using `agent.prompts.dense_property` and the shared proof-friendly specification guidance.
3. `_apply_dense_properties()` replaces the first generated `requires` and `ensures` clauses with the dense variants.
4. Failures are logged and the original generated code is used unchanged.

Dense properties improve proof density by replacing broad placeholders such as `true` with contract clauses tied to the task specification. They are intentionally scoped to generated contracts; they do not prove the properties independently and they can still require later verification repair. MCP clients can call `get_spec_guidelines` to inspect the decidable fragment guidelines before asking the agent to generate or densify a spec. Those guidelines are organized around `decidable_fragment` entries such as `linear_arithmetic`, `array_access`, `bounded_quantifiers`, and `finite_state_machines`, plus `common_failure_patterns` and `recommended_templates`.

Enable dense properties for a single run:

```bash
ENABLE_DENSE_PROPERTIES=true python -m agent generate --spec-file spec.json --output out.mm
```

## Multi-agent verification workflow

With `ENABLE_NLAE_MULTI_AGENT` enabled, `NLAEPipeline.run_full_pipeline()` divides the P9-G stages between a `generator` agent (generate + verify), a `counterexample` agent (Loss Vector driven self-correction, up to `NLAE_MULTI_AGENT_MAX_ROUNDS` rounds), and a `lean_escalation` agent (`mumei-lean` fidelity check).

1. `MultiAgentOrchestrator` encodes every role-to-role handoff through `LatentProtocol`, so the run inherits the existing versioned envelope, semantic hash, authentication tag, optional encryption, and redacted audit log.
2. Orchestration is deterministic, so repeated runs of the same spec produce the same handoff `semantic_hash` sequence; `NLAEResult.multi_agent` carries the handoff records for audit.
3. Spans stay in one trace: `mumei.nlae.multi_agent` under the `mumei.nlae.pipeline` root, `mumei.nlae.agent.<role>` per agent, and `mumei.nlae.handoff` per handoff.
4. Any failure inside the workflow degrades to the single pipeline, and `multi_agent.status` becomes `fallback` with the reason recorded.
5. `multi_agent.converged` mirrors `NLAEResult.verified` (Z3 *or* Lean); `multi_agent.converged_by` names the backend that closed the run (`z3`, `lean`, or `null`).
6. An explicit `multi_agent=False` keeps the single pipeline even when an orchestrator is injected.

```bash
ENABLE_NLAE_MULTI_AGENT=true NLAE_MULTI_AGENT_MAX_ROUNDS=3 python -m agent mcp-server
```

See `docs/NLAE_INTEGRATION.md` for the role/handoff table and the audit payload shape.

## Performance impact

- Latent debugging is local and deterministic. Its overhead is typically limited to NumPy feature extraction and a small decoder pass.
- Dense property generation adds one LLM request per generation attempt where dense properties are enabled.
- Both features are best-effort. Exceptions fall back to the previous pipeline instead of failing the whole task.
- Metrics record dense property attempts, successful code changes, and `dense_property_usage_rate` so runs can verify usage targets such as 50% or higher.
- P8-C metrics record `outside_decidable_fragment_warnings`, `z3_unknowns`, and per-fragment first-pass success rates so dense-property prompts can be tuned toward proof-friendly specs.

## Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `ENABLE_LATENT_DEBUG` | `false` | Run latent-space repair before rule-based and LLM fixes. |
| `ENABLE_DENSE_PROPERTIES` | `false` | Generate dense `requires` / `ensures` clauses after initial generation. |
| `ENABLE_LATENT_PROTOCOL` | `false` | Expose latent inter-agent protocol behavior through MCP tools. |
| `ENABLE_NLAE_MULTI_AGENT` | `false` | Run the NLAE pipeline as a multi-agent verification workflow. |
| `NLAE_MULTI_AGENT_MAX_ROUNDS` | `2` | Counterexample rounds before the workflow escalates to Lean. |

Truthy values are `true`, `1`, `yes`, and `on` case-insensitively. Any other set value disables the flag.

## Recommended controls

- Leave `ENABLE_LATENT_DEBUG=false` and `ENABLE_DENSE_PROPERTIES=false` for normal agent generation and healing unless the run is explicitly evaluating NLAE-inspired behavior.
- Set `ENABLE_LATENT_DEBUG=true` only when a repair run should try the experimental latent-space pass before the legacy repair pipeline.
- Set `ENABLE_DENSE_PROPERTIES=true` only when a generation run should spend the extra LLM call to densify generated contracts.
- Keep `ENABLE_LATENT_PROTOCOL=false` unless explicitly testing latent inter-agent communication.
- Keep `ENABLE_NLAE_MULTI_AGENT=false` unless a run should divide verification across the `generator` / `counterexample` / `lean_escalation` agents; the single pipeline stays the default path.
