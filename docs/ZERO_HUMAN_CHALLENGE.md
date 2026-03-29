# Zero-Human Challenge (SI-1)

> Can mumei-agent produce formally verified code from spec alone — with zero human intervention?

## Overview

The Zero-Human Challenge is a strategic initiative to demonstrate that the mumei-agent pipeline can autonomously generate mathematically verified code from a JSON specification, without any human guidance during the generation process.

The pipeline for each challenge is:

```
spec JSON → generate_code() → self-healing loop → mumei verify → verified .mm output
```

Each challenge provides a JSON specification defining one or more atoms with their `requires`/`ensures` contracts. The agent must generate Mumei code that satisfies all contracts, as proven by the Z3 SMT solver.

## Challenges

### 1. Bounded Queue (`bounded_queue_spec.json`)

A multi-atom module implementing safe queue operations with overflow/underflow prevention:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `enqueue` | Add element to queue | `requires: len < cap` → `ensures: result == len + 1` |
| `dequeue` | Remove element from queue | `requires: len > 0` → `ensures: result == len - 1` |
| `is_full` | Check if queue is at capacity | `ensures: result ∈ {0, 1}` |

**Difficulty**: Medium — requires consistent bounds across multiple atoms.

### 2. Safe Arithmetic (`safe_arithmetic_spec.json`)

A multi-atom module with overflow/underflow-safe arithmetic operations:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `safe_add` | Bounded addition | `requires: a + b <= 1000000` → `ensures: result == a + b` |
| `safe_sub` | Safe subtraction | `requires: a >= b` → `ensures: result == a - b` |
| `safe_mul` | Bounded multiplication | `requires: a <= 1000 && b <= 1000` → `ensures: result == a * b` |

**Difficulty**: Medium — straightforward arithmetic with explicit bounds.

### 3. Verified Clamp (`verified_clamp_spec.json`)

A single-atom challenge with a rich postcondition:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `clamp` | Clamp value to [min, max] | `ensures: result ∈ [min_val, max_val] ∧ (value ∈ range → result == value)` |

**Difficulty**: Medium-High — requires conditional logic in the body that satisfies a compound postcondition including an implication.

## Running the Challenges

```bash
# Validate all specs (no LLM or mumei required)
python -m examples.challenges.run_challenge --all --dry-run

# Run a single challenge
python -m examples.challenges.run_challenge --spec examples/challenges/bounded_queue_spec.json

# Run all challenges
python -m examples.challenges.run_challenge --all
```

## Results

> _To be filled after execution._

| Challenge | Status | Attempts | Elapsed | Notes |
|-----------|--------|----------|---------|-------|
| bounded_queue | — | — | — | — |
| safe_arithmetic | — | — | — | — |
| verified_clamp | — | — | — | — |

Full logs are stored in `examples/challenges/logs/<challenge_name>.json`.

## Methodology

1. **Spec Design**: Each challenge spec is designed to be verifiable by Z3, with realistic `requires`/`ensures` constraints.
2. **Zero Human Intervention**: The agent runs `generate_code()` which:
   - Uses an LLM to generate initial `.mm` code from the spec
   - Runs `mumei check` for parse validation
   - Runs `mumei verify --json` for formal verification
   - On failure, enters the self-healing loop (up to 5 retries)
3. **Logging**: Every generation attempt, verification result, and metric is recorded.
4. **Evaluation**: Success = all atoms in the module pass `mumei verify` (Z3 proves all contracts).

## Conclusions

> _To be filled after execution._

## Related Documents

- [mumei-agent Roadmap](ROADMAP.md) — SI-1 status
- [Cross-Project Roadmap](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) — Strategic Initiatives overview
- [examples/run_e2e_demo.py](../examples/run_e2e_demo.py) — E2E demo pipeline (reference implementation)
