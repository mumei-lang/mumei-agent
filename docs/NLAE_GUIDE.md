# NLAE Guide

`mumei-agent` ships lightweight Natural Language Autoencoder-inspired features for denser generation and earlier repair attempts. Latent-space debugging and dense property generation are disabled by default. The latent protocol for inter-agent communication remains disabled by default.

## Latent-space debugging

Latent debugging runs at the start of `agent.strategies.fix_strategy.get_fix()` when `ENABLE_LATENT_DEBUG` is enabled.

1. `LatentEncoder` converts the current `.mm` source and verifier report into a deterministic NumPy feature vector.
2. `LatentDebugStrategy` derives a bug-direction vector from verifier metadata such as `violation_type`, `failure_type`, counterexamples, and unsat-core data.
3. `LatentDecoder` applies conservative source edits, such as effect adjustments, tautological requires strengthening, or safe ensures weakening.
4. If the candidate is empty, unchanged, invalid, or raises an exception, the strategy falls back to the existing rule-based and LLM repair path.

Use it with the normal heal or generate flows:

```bash
python -m agent heal path/to/file.mm
python -m agent generate --spec-file spec.json --output out.mm
```

Disable it for a single run:

```bash
ENABLE_LATENT_DEBUG=false python -m agent heal path/to/file.mm
```

## Dense property generation

Dense property generation runs after initial code generation when `ENABLE_DENSE_PROPERTIES` is enabled.

1. `DensePropertyGenerator` extracts existing `requires` and `ensures` clauses from generated code.
2. It asks the configured LLM for compact, mathematically precise replacements using `agent.prompts.dense_property` and the shared proof-friendly specification guidance.
3. `_apply_dense_properties()` replaces the first generated `requires` and `ensures` clauses with the dense variants.
4. Failures are logged and the original generated code is used unchanged.

Dense properties improve proof density by replacing broad placeholders such as `true` with contract clauses tied to the task specification. They are intentionally scoped to generated contracts; they do not prove the properties independently and they can still require later verification repair. MCP clients can call `get_spec_guidelines` to inspect the same decidable-fragment guidance (`outside_decidable_fragment`, bounded quantifiers, explicit witnesses) before asking the agent to generate or densify a spec.

Disable dense properties for a single run:

```bash
ENABLE_DENSE_PROPERTIES=false python -m agent generate --spec-file spec.json --output out.mm
```

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

Truthy values are `true`, `1`, `yes`, and `on` case-insensitively. Any other set value disables the flag.

## Recommended controls

- Enable `ENABLE_LATENT_DEBUG=true` and `ENABLE_DENSE_PROPERTIES=true` for normal agent generation and healing to benefit from NLAE-inspired features.
- Set `ENABLE_DENSE_PROPERTIES=false` for low-latency experiments that must avoid the extra LLM call.
- Set `ENABLE_LATENT_DEBUG=false` when comparing against the legacy repair pipeline.
- Keep `ENABLE_LATENT_PROTOCOL=false` unless explicitly testing latent inter-agent communication.
