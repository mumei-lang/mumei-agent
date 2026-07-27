# NLAE Integration

This document describes the experimental integration of Natural Language
Autoencoder (NLAE) concepts into `mumei-agent`.

## Overview

NLAE-inspired features add three capabilities:

1. **Latent-space debugging**: try a deterministic latent repair before the
   existing rule-based and LLM fix pipeline. Opt-in.
2. **Dense property generation**: synthesize compact `requires` / `ensures`
   clauses after initial generation, biased by proof-friendly specification
   guidance. Opt-in.
3. **Latent protocol**: encode inter-agent messages as latent vectors exposed
   through the MCP server. Opt-in.
4. **Multi-agent verification workflow**: split the P9-G pipeline stages across
   collaborating verification agents that hand work to each other over latent
   protocol envelopes. Opt-in.

Enabled capabilities fall back to existing behavior on failure.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENABLE_LATENT_DEBUG` | `false` | Opt in to latent-space debugging in fix strategy. |
| `ENABLE_DENSE_PROPERTIES` | `false` | Opt in to high-density property generation. |
| `ENABLE_LATENT_PROTOCOL` | `false` | Opt in to latent protocol MCP tool usage. |
| `ENABLE_NLAE_MULTI_AGENT` | `false` | Opt in to the multi-agent verification workflow in `NLAEPipeline`. |
| `NLAE_MULTI_AGENT_MAX_ROUNDS` | `2` | Counterexample rounds the workflow may spend before escalating to Lean. |

Truthy values are `true`, `1`, `yes`, and `on` (case-insensitive).

## Components

- `agent/latent_encoder.py`: encodes Mumei source plus verification reports
  into deterministic NumPy feature vectors.
- `agent/latent_decoder.py`: decodes vectors into conservative source edits.
- `agent/strategies/latent_debug_strategy.py`: Phase 0 latent repair strategy.
- `agent/strategies/dense_property_generator.py`: LLM-backed dense contract
  generation.
- `agent/prompts/dense_property.py`: dense property prompt builder.
- `agent/nlae_multi_agent.py`: deterministic multi-agent orchestrator that
  records each role-to-role handoff as a latent protocol envelope.
- `agent/latent_protocol.py`: hash-based latent inter-agent protocol with
  compression, semantic hashing, versioned envelopes, optional encryption,
  authentication tags, and privacy-preserving audit metadata.
- `agent/mcp_server.py`: exposes `send_latent_message`,
  `send_latent_message_batch`, `async_send_latent_message`, and
  `get_spec_guidelines`. The latter returns decidable-fragment guidance
  covering `linear_arithmetic`, `array_access`, `bounded_quantifiers`,
  `finite_state_machines`, `common_failure_patterns`, and
  `recommended_templates` for MCP clients that want to preflight a spec before
  generation.

## Usage

```bash
python -m agent heal examples/sword_test.mm
python -m agent generate --spec-file examples/spec.json --output out.mm
ENABLE_LATENT_PROTOCOL=true python -m agent mcp-server
```

Enable opt-in generation/healing helpers for a single run with:

```bash
ENABLE_LATENT_DEBUG=true ENABLE_DENSE_PROPERTIES=true python -m agent generate --spec-file examples/spec.json --output out.mm
```

`send_latent_message(message, context="{}", verify=true)` accepts JSON object
strings and returns the latent vector, decoded metadata, authentication status,
audit event count, and optional verifier result.

`send_latent_message_batch(messages, verify=false)` accepts a JSON array of
objects shaped as `{"message": {...}, "context": {...}}`. The batch path keeps
one protocol instance across items, so consecutive messages can use
`zlib-delta` compression when they share most semantic content. Item failures
are returned inline without aborting the whole batch.

`async_send_latent_message(message, context="{}", verify=true)` mirrors
`send_latent_message` but runs the encode/verify work off the async MCP
transport loop.

`get_spec_guidelines()` returns the proof-friendly specification checklist used
by the generation prompts. Use it when dense properties or natural-language
extraction produce contracts that may leave the Z3-stable fragment.

## Latent Protocol Security and Privacy

Latent protocol envelopes use `lp-v2` by default and retain `lp-v1`
compatibility for older clients. Each envelope includes:

- **Differential compression**: canonical JSON payloads are zlib-compressed;
  batch and explicit previous-message paths choose `zlib-delta` when the delta
  is smaller than the full payload. The MCP response reports raw bytes,
  transfer bytes, and `transfer_reduction_ratio`; large structured messages are
  expected to exceed the 50% reduction target.
- **Semantic hash**: stable `blake2b-128` hashes ignore volatile transport
  fields such as `timestamp`, `trace_id`, `request_id`, and `nonce` while still
  changing when meaningful fields such as `action`, `target`, or contracts
  change.
- **Version management**: encoded metadata records `protocol_version`, and
  unknown versions fail fast before transfer.
- **Encryption**: set `LATENT_PROTOCOL_KEY` to encrypt the compressed payload
  with AES-256-GCM before vectorization. The key is never returned in MCP
  responses or audit logs.
- **Authentication**: every envelope is authenticated with `hmac-sha256`;
  responses include `authentication_verified=true` when the generated vector
  matches the stored tag.
- **Audit logging**: set `LATENT_PROTOCOL_AUDIT_LOG=/path/to/audit.jsonl` to
  append redacted JSONL audit events. Audit entries include protocol version,
  semantic hash, payload hash, encryption/auth status, and transfer bytes, but
  never plaintext message or context bodies.

## Current Scope

This is a clean-room, lightweight implementation inspired by the NLAE concept.
It does not vendor or depend on `kitft/natural_language_autoencoders`. Perform
a license compatibility review only if future work integrates that project
directly.

## References

- Anthropic NLAE research: https://www.anthropic.com/research/natural-language-autoencoders
- Reference implementation: https://github.com/kitft/natural_language_autoencoders

## P9 NLAE Integration

P9-F and P9-G connect mumei-agent to the four-repository NLAE pipeline:

```text
spec / intent
  ↓
mumei-agent NLAEPipeline (Module A / AV)
  ↓ generated .mm
mumei verify --emit loss-vector (Module B / AR)
  ↓ Loss Vector JSON
uv run mumei-agent self-correct
  ↓ proof certificate
mumei-lean Fidelity Checker
  ↓
mumei-demo Evaluation Loop
```

Run the Loss Vector driven self-correction loop directly:

```bash
uv run mumei-agent self-correct examples/effect_test.mm --max-iterations 3
```

MCP clients can run the full P9-G integration with `run_nlae_pipeline`:

```json
{
  "spec": "vault withdraw safety",
  "mumei_lean_repo": "../mumei-lean",
  "work_dir": ".nlae-work",
  "no_build": true
}
```

## P12-D Multi-Agent Verification Workflow

The single P9-G pipeline runs generate → verify → self-correct → Lean fidelity
as one agent. With `ENABLE_NLAE_MULTI_AGENT=true` (or `multi_agent=true` on the
`run_nlae_pipeline` MCP call) the same stages are divided between three
specialised agents that share one spec:

| Role | Stage | Input handoff |
| --- | --- | --- |
| `generator` | generate + `mumei verify --emit loss-vector` | spec |
| `counterexample` | Loss Vector driven self-correction rounds | `generator` → `counterexample` |
| `lean_escalation` | `mumei-lean` fidelity check on the proof certificate | `counterexample` → `lean_escalation` |

Orchestration is deterministic: the roles, the round order, and the handoff
bodies are fixed functions of the spec and the verifier output, so two runs of
the same spec produce the same handoff `semantic_hash` sequence. Verdicts still
come only from the verifier and the Lean bridge — the workflow adds no verdict
classification and no alias for `lean_verified`.

Each handoff is encoded with `LatentProtocol.encode_message`, so it carries the
existing `lp-v2` versioned envelope, `blake2b-128` semantic hash,
`hmac-sha256` authentication tag, optional AES-256-GCM payload encryption, and a
redacted audit entry (`LATENT_PROTOCOL_KEY` / `LATENT_PROTOCOL_AUDIT_LOG` apply
unchanged). The `NLAEResult.multi_agent` field reports `rounds`, `converged`,
`converged_by`, `audit_events`, and one record per handoff (`from_role`,
`to_role`, `round`, `semantic_hash`, `protocol_version`, `transfer_bytes`,
`authenticated`). `converged` mirrors `NLAEResult.verified`, which is true when
*either* backend discharged the obligations, and `converged_by` names which one
(`"z3"`, `"lean"`, or `null`) so a Lean-only close is distinguishable from a Z3
close. The `lean_escalation` handoff body includes a digest of the verified
source, so its semantic hash differs between specs.

The opt-in flag is authoritative: passing `multi_agent=False` keeps the single
pipeline even when an orchestrator is injected; an injected orchestrator only
enables the workflow when the flag is left unset (`None`).

Tracing keeps one distributed trace: `mumei.nlae.multi_agent` nests under the
`mumei.nlae.pipeline` root span, each agent runs in
`mumei.nlae.agent.<role>`, and every handoff emits `mumei.nlae.handoff` with the
role, round, semantic hash, and authentication status as span attributes. The
handoff envelope also carries the current `trace_id`, which the protocol treats
as a volatile field so the semantic hash stays comparable across traces.

If any part of the workflow raises, the run degrades to the single pipeline and
`multi_agent` records `status="fallback"` with the `fallback_reason`; the
resulting `NLAEResult` is otherwise identical to a non-multi-agent run.

```bash
ENABLE_NLAE_MULTI_AGENT=true NLAE_MULTI_AGENT_MAX_ROUNDS=3 \
  LATENT_PROTOCOL_AUDIT_LOG=.nlae-work/latent-audit.jsonl \
  python -m agent mcp-server
```

Regression gate: `uv run pytest tests/test_nlae_pipeline.py tests/test_latent_protocol.py -q`.
