# Single-file Go compiler metadata (C06)

This optional producer uses the Go compiler's `go/parser` and `go/types`
libraries. It is source-analysis infrastructure, **not a verifier or proof
backend**. The Agent owns its use; Mumei's compiler does not acquire an external
tool dependency. No existing audit, CLI, MCP, planner or evidence route runs it.

## Build and explicit use

From the repository root, with a maintained, stable Go 1.26+ toolchain:

```sh
mkdir -p build
(cd tools/go-types && GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off GOWORK=off go build -o ../../build/go-types .)
```

The separate Go module has **no third-party dependencies**. It needs no Python
package change. The Python distribution contains the reader, not a prebuilt
helper; building/provisioning a trusted helper is an explicit operator action.
`GOTOOLCHAIN=local` prevents toolchain auto-download during the build. The helper
itself does not read environment configuration, source paths, modules, imports
or additional files, and never compiles/executes the supplied Go program.

The binary reads one JSON object from stdin and emits one JSON object to stdout:

```json
{"source":"package p; func F(x int64) int64 { return x }","target_arch":"amd64"}
```

For example, an authorized caller can explicitly invoke it and consume its
metadata with a timeout. The reader does not execute any process itself:

```python
import json
import subprocess
from agent.go_type_snapshot import load_go_snapshot

source = "package p; func F(x int64) int64 { return x }"
completed = subprocess.run(
    ["./build/go-types"],
    input=json.dumps({"source": source, "target_arch": "amd64"}).encode(),
    capture_output=True, check=True, timeout=10,
)
snapshot = load_go_snapshot(completed.stdout, source, target_arch="amd64")
cfg = snapshot.cfg_for_function(source, snapshot.functions[0].binding_id)
```

The caller owns authorization, tool provisioning/identity and process sandbox,
timeout and memory limits. Source-size limits are not a resource sandbox. A
successful process exit is **not** a successful type check: inspect `status`,
or use the reader, which rejects non-`ok` reports. No fallback is performed.

## Contract and supported boundary

- Profile: `mumei.go-types-single-file/v1`; language rules: `go1.23`.
- Explicit target architecture: `amd64`, `386` or `arm64`, with `gc` sizes.
  `int`, `uint` and `uintptr` widths depend on that target. Boolean width 1 is
  logical, **not** a layout/ABI claim. No operating-system/build context,
  machine-code behavior, overflow proof or LLVM meaning is attested.
- All report spans are half-open **UTF-8 byte offsets in the complete source**.
  C05 CFG spans remain **Unicode-codepoint offsets in the function body**.
- A binding ID includes the source SHA-256, declaration offset and scope span.
  Reassignment is not a new binding or an SSA version. Shadowed bindings and
  implicit type-switch case bindings are distinct. Any unit change invalidates
  all its IDs; cross-file dependency invalidation is not implemented.
- Binding/reference metadata comes from a completed type check, including
  named/alias type identities, signed integer widths, parameters and results.
  Non-integer/Boolean value semantics are unsupported or untyped, not silently
  widened into the scalar fragment. Raw type strings, constant/literal values,
  struct tags, comments and compiler diagnostic messages are not emitted.
- `direct_local` only resolves a declaration, not semantics: implemented,
  non-method, non-generic, non-variadic local functions, including parenthesized
  names. Recursion is not analyzed. Calls through function variables/aliases,
  selectors, generic/variadic functions, bodyless declarations, conversions,
  builtins, defer/go and closures are opaque. Closure/initializer calls have no
  named-body owner. Argument spans and parameter/result types are not C07
  argument/return/effect summaries. Missing call edges cannot discharge anything.
- Imports and build/line/compiler directives are rejected, not loaded or ignored.
  Parse/type failures never export partial bindings. This checks an explicit
  source unit, **not** a loaded package, project, or actual build configuration.
- Limits: 64 KiB UTF-8 source, 512 KiB JSON request, 8 MiB JSON reply. `ok` can
  still have gaps for opaque calls and unsupported value semantics. Treat
  non-`ok`, unavailable, stale, malformed or incompatible reports as unusable.

The reader validates transport consistency, not compiler honesty or completeness.
A forged report with the correct hash is not authenticated. No source proof,
`lean_verified`, Seal Grade, audit verdict or evidence acceptance comes from
this API. C05 structural CFG restrictions and heuristic must/may/resource facts
remain unchanged. C06 multi-file/import/other-language resolution, C07 summaries
and C09 LLVM translation validation are separate follow-up work.

## Regression commands

```sh
(cd tools/go-types && GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off GOWORK=off go test ./... && go vet ./...)
PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_go_type_snapshot.py tests/test_control_flow.py -q
```

The real-compiler Python tests skip if Go is not on `PATH`; pure reader tests
still run. CI explicitly installs Go, runs the compiler tests and checks the
producer on both maintained Go series (1.26 and 1.27).
