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

### 1. Safe Queue (`safe_queue_spec.json`)

A multi-atom module implementing 100% safe queue operations with overflow/underflow prevention. References `std/container/bounded_array.mm` patterns (`bounded_push`/`bounded_pop`).

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `enqueue` | Add element (overflow prevention) | `requires: len >= 0 && cap > 0 && len < cap` → `ensures: result == len + 1 && result <= cap` |
| `dequeue` | Remove element (underflow prevention) | `requires: len > 0` → `ensures: result == len - 1 && result >= 0` |
| `is_empty` | Check if queue is empty | `ensures: (len == 0 => result == 1) && (len > 0 => result == 0)` |
| `is_full` | Check if queue is at capacity | `ensures: (len == cap => result == 1) && (len < cap => result == 0)` |

**Difficulty**: Medium-High — 4 atoms with consistent bounds, conditional logic with implication contracts.

### 2. Verified JSON Validator (`verified_json_validator_spec.json`)

A single-atom challenge with capability security via the effect system. Uses `SafeFileRead(path)` effect to enforce file access restrictions.

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `validate_json_file` | Validate a JSON file with path security | `effects: [SafeFileRead(path)]`, `requires: starts_with(path, "/tmp/") && not_contains(path, "..")` → `ensures: result >= 0 && result <= 1` |

**Difficulty**: High — combines effect system (`SafeFileRead`) with path traversal prevention. References `std/effects.mm`.

### 3. Deadlock-free Producer-Consumer (`deadlock_free_producer_consumer_spec.json`)

A multi-atom module implementing deadlock-free producer-consumer with resource hierarchy. Uses `resources: [buffer, mutex]` with priority ordering.

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `produce` | Produce item into buffer | `requires: buf_len < buf_cap && mutex_held == 0` → `ensures: result == buf_len + 1` |
| `consume` | Consume item from buffer | `requires: buf_len > 0 && mutex_held == 0` → `ensures: result == buf_len - 1` |
| `buffer_available` | Check if space available | `ensures: (buf_len < buf_cap => result == 1) && (buf_len == buf_cap => result == 0)` |
| `buffer_has_items` | Check if buffer has items | `ensures: (buf_len > 0 => result == 1) && (buf_len == 0 => result == 0)` |

**Difficulty**: High — resource hierarchy for deadlock prevention, 4 atoms with mutex/buffer coordination.

### 4. Bounded Queue (`bounded_queue_spec.json`)

A multi-atom module implementing safe queue operations with overflow/underflow prevention:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `enqueue` | Add element to queue | `requires: len < cap` → `ensures: result == len + 1` |
| `dequeue` | Remove element from queue | `requires: len > 0` → `ensures: result == len - 1` |
| `is_full` | Check if queue is at capacity | `ensures: result ∈ {0, 1}` |

**Difficulty**: Medium — requires consistent bounds across multiple atoms.

### 5. Safe Arithmetic (`safe_arithmetic_spec.json`)

A multi-atom module with overflow/underflow-safe arithmetic operations:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `safe_add` | Bounded addition | `requires: a + b <= 1000000` → `ensures: result == a + b` |
| `safe_sub` | Safe subtraction | `requires: a >= b` → `ensures: result == a - b` |
| `safe_mul` | Bounded multiplication | `requires: a <= 1000 && b <= 1000` → `ensures: result == a * b` |

**Difficulty**: Medium — straightforward arithmetic with explicit bounds.

### 6. Payment (`payment_spec.json`)

A multi-atom module for verified payment calculations:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `calc_subtotal` | Price * quantity | `ensures: result == price * quantity` |
| `calc_tax` | Tax calculation | `ensures: result == amount * tax_rate_pct / 100` |
| `calc_total` | Total with tax | `ensures: result >= 0` |

**Difficulty**: Medium — cross-atom composition with overflow prevention.

### 7. Verified Clamp (`verified_clamp_spec.json`)

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
python -m examples.challenges.run_challenge examples/challenges/safe_queue_spec.json

# Run all challenges
python -m examples.challenges.run_challenge --all

# Run with custom log directory
python -m examples.challenges.run_challenge --all --log-dir /tmp/challenge_results
```

Results are saved per challenge to `examples/challenges/results/<challenge_name>/`:
- `log.jsonl` — full step log (JSON Lines)
- `output.mm` — final generated Mumei code
- `metrics.json` — `Metrics.to_dict()` output
- `summary.md` — human-readable Markdown summary

## Results

> _To be filled after execution._

| Challenge | Status | Attempts | Elapsed | Notes |
|-----------|--------|----------|---------|-------|
| safe_queue | — | — | — | — |
| verified_json_validator | — | — | — | — |
| deadlock_free_pc | — | — | — | — |
| bounded_queue | — | — | — | — |
| safe_arithmetic | — | — | — | — |
| payment | — | — | — | — |
| verified_clamp | — | — | — | — |

## Methodology

1. **Spec Design**: Each challenge spec is designed to be verifiable by Z3, with realistic `requires`/`ensures` constraints. Challenges range from pure arithmetic to effect-system integration and resource hierarchy enforcement.
2. **Zero Human Intervention**: The agent runs `generate_code()` / `generate_multi_atom()` which:
   - Uses an LLM to generate initial `.mm` code from the spec
   - Runs `mumei check` for parse validation
   - Runs `mumei verify --json` for formal verification
   - On failure, enters the self-healing loop (up to 5 retries)
   - For multi-atom specs, identifies failing atoms and generates targeted fixes
3. **Logging**: Every generation attempt, verification result, and metric is recorded in JSON Lines format.
4. **Evaluation**: Success = all atoms in the module pass `mumei verify` (Z3 proves all contracts).

## Analysis

> _To be filled after execution._

### Success/Failure Factors

- **Spec complexity**: How does the number of atoms, contract complexity, and use of effects/resources affect success rates?
- **Self-healing effectiveness**: How many retries are typically needed? What types of violations are hardest to fix autonomously?
- **LLM capability**: Which categories of formal logic are within the LLM's reach, and which require human intervention?

### Expected Verification Items

| Challenge | Verification Items |
|-----------|-------------------|
| safe_queue | Overflow prevention, underflow prevention, boolean return bounds, implication contracts |
| verified_json_validator | Effect capability (`SafeFileRead`), path traversal prevention, boolean result |
| deadlock_free_pc | Resource hierarchy (priority ordering), buffer bounds, mutex state tracking |
| bounded_queue | Overflow/underflow prevention, boolean return bounds |
| safe_arithmetic | Integer overflow bounds, underflow prevention, non-negative results |
| payment | Cross-atom composition, overflow-safe multiplication, percentage calculation |
| verified_clamp | Compound postcondition with implication, range clamping |

## Conclusions

> _To be filled after execution._

## Benchmark

After running challenges, use the benchmark summary generator to aggregate results into a Markdown table:

```bash
# Generate summary from default results directory
python -m examples.challenges.benchmark

# Specify a custom results directory
python -m examples.challenges.benchmark --results-dir /path/to/results

# Write output to a file instead of stdout
python -m examples.challenges.benchmark --output benchmark_summary.md
```

The generator scans `examples/challenges/results/*/metrics.json` for completed challenge results and produces a summary table with:
- Challenge name
- Status (PASSED / FAILED)
- Total attempts
- Elapsed time
- Success rate

The output can be pasted directly into the [Results](#results) section above.

## Related Documents

- [mumei-agent Roadmap](ROADMAP.md) — SI-1 status
- [Cross-Project Roadmap](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) — Strategic Initiatives overview
- [examples/run_e2e_demo.py](../examples/run_e2e_demo.py) — E2E demo pipeline (reference implementation)
