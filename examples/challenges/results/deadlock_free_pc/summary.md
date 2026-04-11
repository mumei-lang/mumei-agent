# deadlock_free_pc -- Zero-Human Challenge Result

- **Status**: PENDING (dry-run validated, awaiting full execution)
- **Difficulty**: High
- **Type**: Multi-atom with resource hierarchy (4 atoms: produce, consume, buffer_available, buffer_has_items)
- **Verification Target**: Deadlock-free concurrency via resource ordering

## Description

Deadlock-free producer-consumer module with resource hierarchy. Uses priority ordering on buffer and mutex resources to guarantee deadlock freedom. Both `produce` and `consume` must acquire the mutex (priority 1) before the buffer (priority 2), preventing circular wait — the fundamental condition for deadlock.

## Spec

```json
{
  "module_name": "deadlock_free_pc",
  "resources": ["buffer", "mutex"],
  "atoms": [
    {"name": "produce", "requires": "buf_len >= 0 && buf_cap > 0 && buf_len < buf_cap && mutex_held == 0"},
    {"name": "consume", "requires": "buf_len > 0 && buf_cap > 0 && buf_len <= buf_cap && mutex_held == 0"},
    {"name": "buffer_available", "requires": "buf_len >= 0 && buf_cap > 0 && buf_len <= buf_cap"},
    {"name": "buffer_has_items", "requires": "buf_len >= 0"}
  ]
}
```

## Expected Verification

- Z3 proves buffer overflow impossibility: `produce` requires `buf_len < buf_cap`
- Z3 proves buffer underflow impossibility: `consume` requires `buf_len > 0`
- Mutex precondition: both `produce` and `consume` require `mutex_held == 0`
- Resource ordering: acquiring mutex before buffer prevents circular wait (deadlock freedom)
- Boolean predicates: `buffer_available`/`buffer_has_items` always return 0 or 1

## Challenges for AI Generation

- Must correctly model the mutex state as a parameter
- Must maintain the resource hierarchy invariant across all atoms
- Postcondition arithmetic must be precise (e.g., `result == buf_len - 1 && result < buf_cap`)
- The `consume` postcondition `result < buf_cap` is a non-obvious invariant

## How to Execute

```bash
# Full execution (requires OPENAI_API_KEY)
python -m examples.challenges.run_challenge examples/challenges/deadlock_free_producer_consumer_spec.json

# Or via GitHub Actions
# Go to Actions > Zero-Human Challenge > Run workflow
```
