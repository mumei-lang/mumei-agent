# Forge Task Specifications

Task specifications consumed by the `forge` mode (`python -m agent forge`).

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

### Atom spec fields

| Field                | Type      | Description                                                          |
|----------------------|-----------|----------------------------------------------------------------------|
| `name`               | string    | Atom name (must match `[a-zA-Z_][a-zA-Z0-9_]*`)                      |
| `description`        | string    | Short description used in the LLM prompt                             |
| `inputs` / `params`  | list      | Parameter definitions (`{"name": ..., "type": ...}`)                 |
| `return_type`        | string    | Return type, e.g. `i64`                                              |
| `requires`           | string    | Precondition expression                                              |
| `ensures`            | string    | Postcondition expression                                             |
| `effects`            | list      | Effect labels, if the atom performs side effects                     |
| `reference_patterns` | list[str] | Names of existing atoms to inject as style context in the LLM prompt |

### Mode semantics

- **`append`** — Read the existing `target_file`, send its content to the LLM
  as style context, generate only the new atom(s), and append them to the
  end of the file.
- **`create`** — Target file must not exist. Generate a complete `.mm`
  module and write it to `target_file`.
- **`replace`** — Overwrite `target_file` with the newly generated module.

## Adding a new task

1. Copy one of the existing `vstd_*.json` files as a template.
2. Set a unique `task_id`.
3. Populate `atoms` with one or more atom specs.
4. List sibling atoms in `reference_patterns` to keep generation style
   consistent with the existing standard library.
5. Run `python -m agent forge --task <your_task>.json --dry-run` to preview
   the execution plan.

## Task inventory

A snapshot of the forge tasks that ship with this repo, sorted by `priority`
(lowest = forged first). The `Status` column distinguishes between tasks
that exist as JSON specs (`created`), tasks whose generated `.mm` file has
already been forged into `mumei-lang/mumei` (`forged`), and tasks whose
forged output has been verified end-to-end via `mumei verify` and
checked into the std-proof bundle (`verified`). Update this table when
adding or promoting tasks.

| Task ID                          | Target file                              | Difficulty | Atoms | Status   |
|----------------------------------|------------------------------------------|------------|-------|----------|
| `vstd-core`                      | `std/core.mm`                            | low        | 4     | created  |
| `vstd-ownership`                 | `std/ownership.mm`                       | medium     | 5     | created  |
| `vstd-trait-iterable`            | `std/trait/iterable.mm`                  | medium     | 3     | created  |
| `vstd-iter`                      | `std/iter.mm`                            | medium     | 5+    | forged   |
| `vstd-hash`                      | `std/hash.mm`                            | medium     | 2+    | forged   |
| `vstd-fixed-point`               | `std/math/fixed_point.mm`                | medium     | 2+    | forged   |
| `vstd-safe-list`                 | `std/container/safe_list.mm`             | medium     | 2+    | forged   |
| `vstd-string-utils`              | `std/string_utils.mm`                    | medium     | 2+    | forged   |
| `vstd-math-abs`                  | `std/math/abs.mm`                        | low        | 2     | verified |
| `vstd-math-clamp`                | `std/math/clamp.mm`                      | low        | 2+    | forged   |
| `vstd-math-gcd`                  | `std/math/gcd.mm`                        | low        | 2+    | forged   |
| `vstd-math-sqrt`                 | `std/math/sqrt.mm`                       | medium     | 1     | created  |
| `vstd-math-min-max`              | `std/math/min_max.mm`                    | low        | 2+    | forged   |
| `vstd-math-log2`                 | `std/math/log2.mm`                       | medium     | 1     | created  |
| `vstd-math-pow`                  | `std/math/pow.mm`                        | medium     | 2+    | forged   |
| `vstd-math-pow-nat`              | `std/math/pow_nat.mm`                    | medium     | 2+    | forged   |
| `vstd-math-safe-div`             | `std/math/safe_div.mm`                   | low        | 2     | forged   |
| `vstd-math-safe-mul`             | `std/math/safe_mul.mm`                   | low        | 2+    | forged   |
| `vstd-math-factorial`            | `std/math/factorial.mm`                  | low        | 2     | created  |
| `vstd-bitwise`                   | `std/bitwise.mm`                         | medium     | 5     | created  |
| `vstd-option-utils`              | `std/option.mm`                          | low        | 4     | created  |
| `vstd-container-binary-heap`     | `std/container/binary_heap.mm`           | high       | 2+    | forged   |
| `vstd-container-deque`           | `std/container/deque.mm`                 | medium     | 2+    | forged   |
| `vstd-container-priority-queue`  | `std/container/priority_queue.mm`        | high       | 3     | created  |
| `vstd-container-ring-buffer`     | `std/container/ring_buffer.mm`           | medium     | 2+    | forged   |
| `vstd-container-stack`           | `std/container/stack.mm`                 | medium     | 4+    | forged   |
| `vstd-container-set`             | `std/container/set.mm`                   | high       | 3     | created  |
| `vstd-container-sorted-list`     | `std/container/sorted_list.mm`           | medium     | 3     | created  |
