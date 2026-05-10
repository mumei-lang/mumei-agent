# NLAE Integration

This document describes the experimental integration of Natural Language
Autoencoder (NLAE) concepts into `mumei-agent`.

## Overview

NLAE-inspired features add three opt-in capabilities:

1. **Latent-space debugging**: try a deterministic latent repair before the
   existing rule-based and LLM fix pipeline.
2. **Dense property generation**: synthesize compact `requires` / `ensures`
   clauses after initial generation.
3. **Latent protocol**: encode inter-agent messages as latent vectors exposed
   through the MCP server.

All capabilities are disabled by default and fall back to existing behavior on
failure.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENABLE_LATENT_DEBUG` | `false` | Enable latent-space debugging in fix strategy. |
| `ENABLE_DENSE_PROPERTIES` | `false` | Enable high-density property generation. |
| `ENABLE_LATENT_PROTOCOL` | `false` | Enable latent protocol MCP tool usage. |

Truthy values are `true`, `1`, `yes`, and `on` (case-insensitive).

## Components

- `agent/latent_encoder.py`: encodes Mumei source plus verification reports
  into deterministic NumPy feature vectors.
- `agent/latent_decoder.py`: decodes vectors into conservative source edits.
- `agent/strategies/latent_debug_strategy.py`: Phase 0 latent repair strategy.
- `agent/strategies/dense_property_generator.py`: LLM-backed dense contract
  generation.
- `agent/prompts/dense_property.py`: dense property prompt builder.
- `agent/latent_protocol.py`: hash-based latent inter-agent protocol.
- `agent/mcp_server.py`: exposes `send_latent_message`.

## Usage

```bash
ENABLE_LATENT_DEBUG=true python -m agent heal examples/sword_test.mm
ENABLE_DENSE_PROPERTIES=true python -m agent generate --spec-file examples/spec.json --output out.mm
ENABLE_LATENT_PROTOCOL=true python -m agent mcp-server
```

`send_latent_message(message, context="{}", verify=true)` accepts JSON object
strings and returns the latent vector, decoded metadata, and optional verifier
result.

## Current Scope

This is a clean-room, lightweight implementation inspired by the NLAE concept.
It does not vendor or depend on `kitft/natural_language_autoencoders`. Before
integrating that project directly, verify its license compatibility with
`mumei-agent`.

## References

- Anthropic NLAE research: https://www.anthropic.com/research/natural-language-autoencoders
- Reference implementation: https://github.com/kitft/natural_language_autoencoders
