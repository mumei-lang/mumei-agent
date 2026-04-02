# Publish Demo: Payment Module

This directory demonstrates the **autonomous publish pipeline** (`--publish` mode) of mumei-agent.

The pipeline takes a spec JSON describing a multi-atom module and automatically:

1. **Generates** verified mumei code from the spec using an LLM
2. **Verifies** the generated code passes Z3 formal verification
3. **Emits** FFI wrappers for multiple targets:
   - `c-header` — C header file (`.h`)
   - `rust-wrapper` — Rust `extern "C"` bindings + safe wrappers (`.rs`)
   - `python-wrapper` — ctypes-based Python wrappers (`.py`)
4. **Commits** all generated files to a `auto/<module_name>` branch
5. **Creates a PR** via the GitHub API

## Payment Spec

The `payment_spec.json` defines a `payment` module with three atoms:

| Atom | Requires | Ensures |
|------|----------|---------|
| `calc_subtotal(quantity, price)` | `quantity > 0 && price > 0` | `result > 0` |
| `calc_tax(amount, rate)` | `amount > 0 && rate >= 0 && rate <= 100` | `result >= 0` |
| `calc_total(subtotal, tax)` | `subtotal > 0 && tax >= 0` | `result >= subtotal` |

## Usage

### Dry-run (no git/PR operations)

```bash
python -m agent publish --spec examples/publish_demo/payment_spec.json --dry-run
```

This will:
- Generate `payment.mm` from the spec
- Verify the generated code with `mumei verify`
- Emit all three wrapper targets to `katana/`
- Print the result summary without creating any git commits or PRs

### Full pipeline

```bash
python -m agent publish \
  --spec examples/publish_demo/payment_spec.json \
  --github-owner <owner> \
  --github-repo <repo>
```

This will perform all steps above, plus:
- Create a git branch `auto/payment`
- Commit the generated `.mm` file and `katana/` artifacts
- Push to origin and create a PR against `develop`

Requires `GITHUB_TOKEN` environment variable (or `--github-owner` / `--github-repo` flags).

## Pipeline Steps in Detail

| Step | Tool | What happens |
|------|------|-------------|
| Generate | LLM + mumei-agent | Spec → mumei code with contracts |
| Verify | `mumei verify` | Z3 proves all requires/ensures |
| Emit c-header | `mumei build --emit c-header` | Generates `.h` FFI header |
| Emit rust-wrapper | `mumei build --emit rust-wrapper` | Generates Rust extern bindings |
| Emit python-wrapper | `mumei build --emit python-wrapper` | Generates ctypes wrappers |
| Git | `git checkout/add/commit/push` | Branch `auto/payment`, commit all |
| PR | GitHub API | Opens PR against base branch |

## Note on FFI Wrappers

The `rust-wrapper` and `python-wrapper` emit targets generate **FFI glue code**, not transpiled source. They produce `extern "C"` bindings (Rust) or ctypes wrappers (Python) for calling the compiled mumei shared library (`.so`/`.dll`).
