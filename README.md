# Mumei Agent

AI-driven autonomous fix loop for the [Mumei](https://github.com/mumei-lang/mumei)
proof-driven programming language. Combines LLM (Qwen/Ollama/OpenAI) with Z3 formal
verification to automatically detect and fix code issues.

## Background

This repository was extracted from the [mumei](https://github.com/mumei-lang/mumei)
compiler repository. The self-healing agent and Streamlit visualizer were originally
developed in-tree and moved here as a standalone project
(see [mumei-lang/mumei#90](https://github.com/mumei-lang/mumei/pull/90)).

## Architecture

```
mumei CLI (Z3 verification)
  ^ subprocess: mumei build / mumei verify --json
  |
agent/self_healing.py (orchestration loop)
  ^ OpenAI-compatible API
  |
Ollama + Qwen (LLM inference)
  ^ Docker Compose
  |
docker-compose.yml
```

## Prerequisites

- [Mumei](https://github.com/mumei-lang/mumei) installed and available in PATH
  - Or: clone mumei repo and use `cargo run --` mode
- Docker (for Ollama)
- Python 3.10+

## Quick Start

```bash
# 1. Start Ollama container
docker compose up -d
docker exec mumei-ollama ollama pull qwen3.5

# 2. Configure environment
cp .env.example .env
# Edit .env to select your LLM provider (default: Ollama local)

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run self-healing loop (uses examples/sword_test.mm by default)
python -m agent.self_healing

# Or specify a file explicitly:
python -m agent.self_healing examples/effect_test.mm

# 5. (Optional) Start Streamlit visualizer
streamlit run visualizer/app.py
```

## Examples

The `examples/` directory contains sample `.mm` files with known verification
failures for testing the self-healing loop:

| File | Violation Type | Description |
|---|---|---|
| `examples/sword_test.mm` | Precondition | Division without `b != 0` guard |
| `examples/effect_test.mm` | Effect mismatch | Uses `FileWrite` but only declares `[Log]` |

```bash
# Demo: precondition fix
python -m agent.self_healing examples/sword_test.mm

# Demo: effect mismatch fix
python -m agent.self_healing examples/effect_test.mm
```

## E2E Demo

<!-- TODO: Replace with actual recording after running scripts/demo_e2e.sh -->
<!-- asciinema rec demo.cast -c "bash scripts/demo_e2e.sh" -->
<!-- agg demo.cast docs/demo.gif -->
<!-- ![E2E Demo](docs/demo.gif) -->

The self-healing loop follows this interaction flow:

```
┌─────────────────────────────────────────────────────────────┐
│  Input: examples/sword_test.mm (buggy)                      │
│                                                             │
│  atom safe_divide(a: Nat, b: Nat) -> Nat                    │
│      requires: a >= 0;          ← Missing: b != 0           │
│      ensures: result >= 0;                                  │
│      body: a / b;               ← Division by zero possible │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 1: mumei build → ❌ Verification Failed                │
│                                                              │
│  report.json:                                                │
│  {                                                           │
│    "status": "failed",                                       │
│    "atom": "safe_divide",                                    │
│    "reason": "Division by zero possible",                    │
│    "counterexample": { "a": "0", "b": "0" }                 │
│  }                                                           │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 2: LLM Fix (Ollama/Qwen)                              │
│                                                              │
│  Prompt: "The atom 'safe_divide' failed verification.        │
│   Counter-example: a=0, b=0. Fix the requires clause."       │
│                                                              │
│  LLM Response:                                               │
│  ```mumei                                                    │
│  atom safe_divide(a: Nat, b: Nat) -> Nat                     │
│      requires: a >= 0 && b != 0;    ← Fixed!                 │
│      ensures: result >= 0;                                   │
│      body: a / b;                                            │
│  ```                                                         │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 3: mumei build → ✅ Verification Passed                │
│                                                              │
│  "Success! Blade is flawless (Attempt 2)."                   │
└──────────────────────────────────────────────────────────────┘
```

**Expected console output:**

```
$ python -m agent.self_healing examples/sword_test.mm --max-retries 3
Mumei Self-Healing Loop Start...
Original source backed up to examples/sword_test.mm.bak
Attempt 1: Flaw detected. Consulting AI...
Code updated. Retrying...
Success! Blade is flawless (Attempt 2).
```

### Recording a demo

An E2E demo script is provided for recording with [asciinema](https://asciinema.org/):

```bash
# Run the demo interactively
bash scripts/demo_e2e.sh

# Or record as an asciinema cast
asciinema rec docs/demo.cast -c "bash scripts/demo_e2e.sh"

# Convert to GIF (requires agg: cargo install --git https://github.com/asciinema/agg)
agg docs/demo.cast docs/demo.gif
```

## LLM Provider Support

| Provider | Config Pattern | Cost |
|---|---|---|
| Ollama (local) | Pattern 1 | Free |
| External API (DashScope etc.) | Pattern 2 | Pay-per-use |
| vLLM (local) | Pattern 3 | Free |
| OpenAI | Pattern 4 | Pay-per-use |

See `.env.example` for configuration details.

## report.json Schema

This agent consumes the `report.json` output from `mumei verify --json`.
See [REPORT_SCHEMA.md](https://github.com/mumei-lang/mumei/blob/develop/docs/REPORT_SCHEMA.md)
for the full schema documentation.

## License

[Apache-2.0 license](LICENSE)
