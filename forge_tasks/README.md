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
