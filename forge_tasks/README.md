# Forge Task Specifications

Task specifications consumed by the `forge` mode (`uv run python -m agent forge`).

Each `.json` file in this directory describes one forge task: a unit of work
that extends the mumei standard library (`std/*.mm`) with new verified atoms.

The forge orchestrator (`agent/forge.py`) reads these specs, drives the
generate → verify → self-heal pipeline for each one, appends the generated
code to the target `.mm` file (or creates a new file), and optionally
commits the change to git.

## Spec JSON format

```json
{
  "task_id": "vstd-contracts-safe-add",
  "target_file": "std/contracts.mm",
  "mode": "append",
  "priority": 1,
  "atoms": [
    {
      "name": "safe_add",
      "description": "Overflow-safe addition",
      "inputs": [
        {"name": "a", "type": "i64"},
        {"name": "b", "type": "i64"}
      ],
      "return_type": "i64",
      "requires": "a >= 0 && b >= 0",
      "ensures": "result == a + b && result >= 0",
      "reference_patterns": ["safe_subtract", "bounded_increment"]
    }
  ],
  "max_retries": 10,
  "auto_commit": true
}
```

### Required fields

| Field          | Type            | Description                                                    |
|----------------|-----------------|----------------------------------------------------------------|
| `task_id`      | string          | Unique identifier (used to deduplicate completed tasks)        |
| `target_file`  | string          | Path relative to the mumei repo root (e.g. `std/contracts.mm`) |
| `mode`         | `append` / `create` / `replace` | How to apply the generated code               |
| `atoms`        | list            | One or more atom specs (see below)                             |

### Optional fields

| Field         | Type    | Default | Description                                                         |
|---------------|---------|---------|---------------------------------------------------------------------|
| `priority`    | integer | 100     | Lower values are forged first                                       |
| `max_retries` | integer | 5       | Per-task override for the self-healing retry budget                 |
| `auto_commit` | boolean | false   | When true, commit the change to git after a successful forge        |
| `description` | string  |         | Human-readable task description                                      |
| `context_files` | list[str] |     | Extra `.mm` files injected as style context                          |
| `depends_on`  | list[string] |  | Task ID                          | Target file                              | Difficulty | Atoms | Status   |
|----------------------------------|------------------------------------------|------------|-------|----------|
| `vstd-aviation-control` | `std/concurrency/aviation.mm` | — | 1 | forged |
| `vstd-core` | `std/core.mm` | — | 4 | verified |
| `vstd-math-abs` | `std/math/abs.mm` | — | 2 | verified |
| `vstd-math-clamp` | `std/math/clamp.mm` | — | 4 | verified |
| `vstd-math-gcd` | `std/math/gcd.mm` | — | 5 | verified |
| `vstd-math-patterns` | `std/math/patterns.mm` | medium | 5 | forged |
| `vstd-math-safe-div` | `std/math/safe_div.mm` | — | 2 | verified |
| `vstd-math-safe-mul` | `std/math/safe_mul.mm` | — | 2 | verified |
| `vstd-ownership` | `std/ownership.mm` | medium | 5 | verified |
| `vstd-settlement` | `std/settlement.mm` | hard | 7 | verified |
| `vstd-core-guards` | `std/core_guards.mm` | low | 4 | forged |
| `vstd-core-predicates` | `std/core_predicates.mm` | low | 3 | forged |
| `vstd-core-ranges` | `std/core_ranges.mm` | low | 4 | forged |
| `vstd-fixed-point` | `std/math/fixed_point.mm` | — | 4 | verified |
| `vstd-math-factorial` | `std/math/factorial.mm` | — | 2 | verified |
| `vstd-math-pow` | `std/math/pow.mm` | — | 2 | verified |
| `vstd-math-pow-nat` | `std/math/pow_nat.mm` | — | 2 | verified |
| `vstd-container-ring-buffer` | `std/container/ring_buffer.mm` | — | 5 | verified |
| `vstd-math-fibonacci` | `std/math/fibonacci.mm` | — | 2 | forged |
| `vstd-math-min-max` | `std/math/min_max.mm` | — | 3 | verified |
| `vstd-option-utils` | `std/option.mm` | — | 4 | verified |
| `vstd-container-binary-heap` | `std/container/binary_heap.mm` | — | 5 | verified |
| `vstd-container-deque` | `std/container/deque.mm` | — | 7 | verified |
| `vstd-container-stack` | `std/container/stack.mm` | — | 4 | verified |
| `vstd-safe-list` | `std/container/safe_list.mm` | — | 4 | verified |
| `vstd-iter` | `std/iter.mm` | — | 5 | verified |
| `vstd-string-utils` | `std/string_utils.mm` | low | 4 | verified |
| `vstd-string-validator` | `std/string/validator.mm` | — | 2 | forged |
| `vstd-trait-iterable` | `std/trait/iterable.mm` | — | 3 | verified |
| `vstd-container-sorted-list` | `std/container/sorted_list.mm` | — | 3 | verified |
| `vstd-container-sorted-map` | `std/container/sorted_map.mm` | — | 3 | forged |
| `vstd-hash` | `std/hash.mm` | — | 4 | verified |
| `vstd-math-extended` | `std/math/extended.mm` | medium | 4 | created |
| `vstd-math-sqrt` | `std/math/sqrt.mm` | medium | 1 | verified |
| `vstd-container-priority-queue` | `std/container/priority_queue.mm` | high | 3 | verified |
| `vstd-crypto-primitives` | `std/crypto/primitives.mm` | medium | 4 | forged |
| `vstd-bitwise` | `std/bitwise.mm` | medium | 5 | verified |
| `vstd-math-log2` | `std/math/log2.mm` | medium | 1 | verified |
| `vstd-container-set` | `std/container/set.mm` | high | 3 | verified |
| `vstd-regtech` | `std/compliance.mm` | medium | 5 | verified |
