# Lean Fallback Troubleshooting

`python -m agent proliferate` enables Lean fallback by default. When `mumei verify`
returns Z3 `unknown` atoms, the agent writes a temporary proof certificate and
invokes `mumei-lang/mumei-lean/scripts/bridge.py` via `MUMEI_LEAN_REPO`.

## Required runtime

- `MUMEI_LEAN_REPO` points at a `mumei-lang/mumei-lean` checkout with
  `scripts/bridge.py`.
- `lean` and `lake` are on `PATH` when the bridge runs builds.
- CI installs the toolchain with `elan` and verifies both binaries before
  proliferation starts.

## Common diagnostics

| `error_code` | Meaning | Fix |
| --- | --- | --- |
| `lean_unavailable` | `MUMEI_LEAN_REPO` is unset or does not contain `scripts/bridge.py`. | Check out `mumei-lang/mumei-lean` and export `MUMEI_LEAN_REPO=/path/to/mumei-lean`. |
| `lake_missing` | `lake` is not on `PATH` for a real mumei-lean checkout. | Install Lean with `elan` and prepend `$HOME/.elan/bin` to `PATH`. |
| `partial_translation` | The bridge generated Lean that needs manual review or hit unsupported Mumei syntax. | Inspect the generated Lean module and simplify the atom contract/body into the supported bridge fragment. |
| `timeout` | `bridge.py` or `lake build` exceeded the timeout. | Retry with a warm Lake cache, reduce the escalation bundle, or increase the bridge timeout for large modules. |
| `bridge_failed` | `bridge.py` exited non-zero for another reason. | Read `stdout`/`stderr` in `summary.json`-adjacent CI logs and the `proliferate.log` artifact. |

## Metrics

`summary.json` reports atom-level fallback metrics:

- `lean_fallback_attempted`: Z3 `unknown` atoms sent to the fallback path.
- `lean_fallback_proved`: attempted atoms upgraded to `lean_verified`.
- `lean_fallback_failed`: attempted atoms that remained unproved.
- `lean_fallback_success_rate`: `proved / attempted`, or `null` when no unknown
  atoms were seen.

The scheduled CI workflow gates attempted fallback runs at a 70% success rate.
