# CI Workflows

## SI-5 Autonomous Proliferation

`.github/workflows/proliferate.yml` runs the scheduled autonomous stdlib
proliferation loop and can also be launched with `workflow_dispatch`.

Lean fallback is enabled by default in the `python -m agent proliferate` CLI and
therefore in CI. The workflow:

1. checks out `mumei-agent`, `mumei`, and best-effort `mumei-lean`;
2. installs Python and the mumei compiler dependencies;
3. installs Lean/Lake with `elan`;
4. verifies `lean --version` and `lake --version` for diagnostics;
5. runs proliferation with `--output-json /tmp/proliferate/summary.json`;
6. reports `lean_fallback_attempted`, `lean_fallback_proved`,
   `lean_fallback_failed`, and `lean_fallback_success_rate` to the job summary;
7. fails the workflow when Lean fallback attempted Z3 `unknown` atoms but proved
   fewer than 70% of them.

When Lean is unavailable, the agent does not abort the forge run. Instead,
`summary.json` records a per-result `lean_fallback.error_code` such as
`lean_unavailable` or `lake_missing`, and the atom-level failures contribute to
the fallback metrics.

See [Lean Fallback Troubleshooting](./LEAN_FALLBACK_TROUBLESHOOTING.md) for
diagnostic codes and remediation steps.
