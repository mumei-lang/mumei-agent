# CLI and E2E Guide

## Examples

The `examples/` directory contains sample `.mm` files with known verification
failures for testing the self-healing loop:

| File | Violation Type | Description |
|---|---|---|
| `examples/sword_test.mm` | Precondition | Division without `b != 0` guard |
| `examples/effect_test.mm` | Effect mismatch | Uses `FileWrite` but only declares `[Log]` |

```bash
# Demo: precondition fix
uv run mumei-agent heal examples/sword_test.mm

# Demo: effect mismatch fix
uv run mumei-agent heal examples/effect_test.mm

# Backward compatible (no subcommand = heal mode)
uv run mumei-agent examples/sword_test.mm

# Disable the original-contract erosion guard for one repair
uv run mumei-agent heal examples/sword_test.mm --allow-contract-erosion
```

Repair acceptance checks run in order: verifier, pinned charter (when
configured), then contract erosion against the source snapshot. The
`--allow-contract-erosion` option disables only the final check for that
invocation; see [Configuration](CONFIGURATION.md#contract-guards) for the
environment variables and defaults.

## Generate Mode

The `generate` subcommand creates new Mumei code from a JSON specification.
It uses an LLM to generate code, then verifies it with `mumei check` and
`mumei verify --json`, auto-fixing any issues.

### Spec JSON Format

```json
{
  "name": "safe_read",
  "params": [{"name": "path", "type": "Str"}],
  "effects": ["SafeFileRead(path)"],
  "requires": "starts_with(path, \"/tmp/\") && not_contains(path, \"..\")",
  "ensures": "result >= 0",
  "description": "Read a file safely with path traversal prevention"
}
```

### Usage

```bash
# From a spec file
uv run mumei-agent generate --spec-file spec.json --output out.mm

# From inline JSON
uv run mumei-agent generate --spec '{"name": "add", "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}], "requires": "true", "ensures": "result == a + b"}' --output add.mm

# With metrics output
uv run mumei-agent generate --spec-file spec.json --output out.mm --metrics

# Require a discriminating negative-control result
uv run mumei-agent generate --spec-file spec.json --output out.mm \
  --controls-gate require
```

### Metrics

Use the `--metrics` flag to output a JSON summary of generation/fix statistics:

```json
{
  "total_attempts": 3,
  "successes": 1,
  "by_violation_type": {
    "generation": {"attempts": 1, "successes": 1},
    "effect_mismatch": {"attempts": 2, "successes": 0}
  }
}
```

### Negative-controls gate

After generated code verifies, `generate` checks only the atom names in the
specification with `mumei controls`. The default mode is `warn`; select
`--controls-gate off` to disable the check or `--controls-gate require` to fail
when an atom is weak or inconclusive. A required-gate failure exits with status
1 but leaves the generated output in place. The mode can also be set with
`CONTROLS_GATE=off|warn|require`.

See the [Mumei controls guide](https://github.com/mumei-lang/mumei/blob/develop/docs/CONTROLS.md)
for the report semantics. Equivalent mutants can survive; a surviving mutant
still needs human judgment. The gate does not run for `proliferate`, MCP
`generate`/`self_correct` tools, or `heal`.

## E2E Demo

https://github.com/user-attachments/assets/908ae828-d249-4967-b9b0-55d56dd3d95e

The self-healing loop follows this interaction flow:

1. **Verification failure**: `mumei build` detects a precondition bug (missing `b != 0` guard)
2. **LLM fix**: The agent sends the Z3 counter-example to the LLM, which generates a corrected `requires` clause
3. **Re-verification**: `mumei build` confirms the fix passes formal verification

### Spec-to-Verified-Code E2E Demo

The `examples/run_e2e_demo.py` script demonstrates the full pipeline: specification
JSON -> LLM code generation -> mumei verify -> self-healing loop -> verified output.

```bash
# Dry-run mode (validate spec only, no LLM or mumei required)
python -m examples.run_e2e_demo --dry-run
python -m examples.run_e2e_demo examples/simple_add_spec.json --dry-run

# Full pipeline (requires LLM API key and optionally mumei binary)
python -m examples.run_e2e_demo                                # uses e2e_demo_spec.json
python -m examples.run_e2e_demo examples/simple_add_spec.json  # minimal example
```

Available spec files:

| File | Description | Effects |
|---|---|---|
| `examples/e2e_demo_spec.json` | Fetch GitHub user via HTTPS | `SecureHttpGet` |
| `examples/simple_add_spec.json` | Add two non-negative numbers | None |

### P11 Natural-language Specification Extraction

See [`docs/NL_SPEC_DEMO.md`](./NL_SPEC_DEMO.md) for a recorded field demo of `uv run mumei-agent extract-spec`, including bank-transfer, RegTech KYC, and spec-extraction-to-code-generation examples with `mumei verify` output.

Use contradiction-only mode when you want to validate natural-language requirements before generating code:

```bash
uv run mumei-agent extract-spec \
  --text "x must be greater than 0 and less than 0" \
  --domain math \
  --output contradiction-report.json \
  --check-contradiction-only
```

This extracts the forge-task spec, builds temporary trusted atoms from the extracted contracts, runs Mumei spec satisfiability, and writes `contradiction_found`, `natural_language_explanation`, and the raw verification payload to the output JSON. It skips `.mm` code generation and self-healing entirely.

https://github.com/user-attachments/assets/7426e5e0-c9ac-4c30-a267-012ad8b0ffdd

A live OpenAI extraction E2E recording is available at [`docs/p11_live_extraction_e2e.mp4`](./p11_live_extraction_e2e.mp4).

## LLM Provider Support

| Provider | Config Pattern | Cost |
|---|---|---|
| Ollama (local) | Pattern 1 | Free |
| External API (DashScope etc.) | Pattern 2 | Pay-per-use |
| vLLM (local) | Pattern 3 | Free |
| OpenAI | Pattern 4 | Pay-per-use |

See `.env.example` for configuration details.

## Subcommands

| Command | Description | Example |
|---|---|---|
| `heal` (default) | Self-healing loop for existing .mm files | `uv run mumei-agent heal examples/sword_test.mm` |
| `self-correct` | P9-F Loss Vector driven self-correction loop | `uv run mumei-agent self-correct examples/effect_test.mm --max-iterations 3` |
| `generate` | Generate new .mm code from spec JSON | `uv run mumei-agent generate --spec-file spec.json --output out.mm` |
| `audit` | Audit existing code or directories: extract spec, check health, verify contracts, detect cross-validation gaps | `uv run mumei-agent audit --code-file src/ --auto-migrate --auto-heal` |
| `migrate-suggest` | Generate .mm migration skeletons for functions with verification issues | `uv run mumei-agent migrate-suggest --code-file src/foo.ts --language typescript` |
| `publish` | Autonomous delivery: generate → verify → emit wrappers → PR | `uv run mumei-agent publish --spec examples/publish_demo/payment_spec.json --dry-run` |
| `forge` | Autonomously extend the mumei std library with verified atoms | `uv run mumei-agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --max-tasks 1` |
| `validate-spec` | Cross-validate natural-language specs for contradiction, ambiguity, over-constraint, and Z3 satisfiability | `uv run mumei-agent validate-spec --input spec.txt --format nl` |
| `validate-code` | Infer and verify contracts from existing code (Python, Rust, TypeScript, Go). `--language` is optional; inferred from extension when omitted | `uv run mumei-agent validate-code --input code.ts` |
| `validate-spec-to-code` | Detect missing implementation constraints by comparing specs to code | `uv run mumei-agent validate-spec-to-code --spec spec.txt --code src/foo.py --language python` |
| `validate-code-to-spec` | Detect spec drift by comparing changed code to specs | `uv run mumei-agent validate-code-to-spec --code src/foo.py --spec spec.txt --language python` |
| `verify-conformance` | Produce the V1-C spec→code conformance matrix and next_steps-first report | `uv run mumei-agent verify-conformance --spec spec.txt --code src/foo.py --language python --format human` (python\|rust\|typescript\|go) |
| `verify-traceability` | Combine V1-C conformance and V1-D drift into one bidirectional traceability summary | `uv run mumei-agent verify-traceability --code src/foo.py --spec spec.txt --language python --format human` (python\|rust\|typescript\|go) |
| `extract-spec` | Extract forge spec from existing code or natural-language input | `uv run mumei-agent extract-spec --code-file src/foo.py` |
| `harvest-tests` | Deterministically extract example, relation, property, and expected-failure observations from Python and Rust tests | `uv run mumei-agent harvest-tests tests/ --target add` |
| `check-spec-health` | Check a Mumei spec for contradictions, over-constraints, and vacuity | `uv run mumei-agent check-spec-health spec.mm` |
| `cross-validate` | Cross-validate spec↔code consistency across multiple files | `uv run mumei-agent cross-validate --spec spec.txt --code src/foo.py` |
| `proliferate` | Autonomous weekly loop: analyze gaps → spec → generate → blast-radius check → heal → PR | `uv run mumei-agent proliferate --mumei-repo ../mumei --max-proposals 3` |
| `propose` | Generate forge task specs from `analyze-std-gaps` output | `uv run mumei-agent propose --auto --mumei-repo ../mumei` |
| `analyze-std-gaps` | Identify gaps in std/ coverage | `uv run mumei-agent analyze-std-gaps --mumei-repo ../mumei` |
| `health` | Show agent health status (LLM provider, mumei binary, etc.) | `uv run mumei-agent health` |
| `mcp-server` | Run mumei-agent as a FastMCP server (forge / heal / health / propose tools) | `uv run mumei-agent mcp-server` |

## Test Harvest

`harvest-tests` performs deterministic, LLM-free extraction of test observations from Python (`ast`) and Rust (the existing tree-sitter parser). It accepts files or directories; `.py` and `.rs` files are detected automatically, including mixed-language directories. Use `--language python|rust` to restrict directory discovery, `--target NAME` more than once to filter target functions, and `--output FILE` to write the JSON report to a file.

```bash
uv run python -m agent harvest-tests tests/python/
uv run python -m agent harvest-tests tests/rust/ --language rust --target add --output observations.json
```

The report uses schema `mumei.test-harvest/v1`. `sources` and every file path are relative to the common input root. `targets` maps target names to per-language metadata, for example `{"f": {"python": {"params": ["x"], "file": "lib.py", "line": 1}, "rust": {"params": ["value"], "file": "lib.rs", "line": 1}}}`. Each language entry uses `params`, `file`, and `line`; unresolved targets set all three to `null`. If a name has multiple definitions in one language, that language's entry is `{"params": null, "ambiguous": true, "definitions": [...]}`; each definition has `params`, `file`, and `line`, sorted by file and line. Calls use a same-file definition when available, otherwise a unique definition in the calling language across the inputs; ambiguous or unresolved calls keep positional `args`. Each observation contains `kind` (`example`, `relation`, `property`, or `rejects`), `target`, `args`, `test`, `file`, and `line`; examples add `result`, relations add a Mumei-syntax `predicate`, rejects add `expected: "failure"`, and properties add declared `variables`, rendered `assumptions`, and a `predicate`. A property argument is either a literal or `{"var": "name"}`; property variable bounds are inclusive and omitted when unbounded. Unsupported assertions appear in `skipped` with a reason and source text. Partial parse failures are reported as `parse_error` skips; if every source fails to parse, the CLI exits 4 without emitting a report. The totals count test functions and observations by kind. `totals.skipped` counts skip entries: one per assertion or unsupported property test, except `test_not_run`, which is one per test; `parse_error` entries are per source file.

Property observations are extracted statically from Python Hypothesis `@given` tests and Rust `proptest!` cases. Python supports integer and boolean strategies from `hypothesis.strategies`; Rust supports integer ranges and `any::<i64>()` / `any::<bool>()`. Top-level assumptions before the first assertion are recorded. Unsupported strategies, assumptions, or expressions are skipped rather than executed; the harvest command never imports or runs test code.

```json
{
  "kind": "property",
  "target": "f",
  "args": {"a": {"var": "x"}, "b": 3},
  "test": "test_f_nonnegative",
  "file": "tests/test_f.py",
  "line": 12,
  "variables": [{"name": "x", "type": "i64", "min": 0, "max": 100}],
  "assumptions": ["(x != 5)"],
  "predicate": "(result >= x)"
}
```

Predicates support comparisons, boolean operators, and arithmetic `+`, `-`, and `*`. Division and modulo expressions are skipped as unsupported because their language-specific integer semantics do not reliably match Mumei's. Only direct test-body assertions are harvested (Python also recurses through ordinary `with` blocks); conditional assertions are skipped as `conditional_assertion`. In property tests, only top-level assumptions before the first assertion are accepted, and tests that rebind or shadow a generator variable are skipped as `generator_variable_rebound`. Assertions after top-level Python `return`/`raise`, a return inside an ordinary `with`, recognized Python test/process termination calls, or Rust `return`, panic, or process exit are skipped as `unreachable_assertion`. A raise inside an ordinary Python `with` and a Rust `?` make later assertions conditional. Tests not known to run because of Python skip/xfail decorators or Rust `#[ignore]` produce one `test_not_run` skip. Literal boolean conditions on `skipif`, `skipIf`, and `skipUnless` are evaluated; non-literal conditions are treated as not known to run. `test_not_run` means the test is not known to run. Integer literals must fit signed i64. Other skip reasons include `no_target_call`, `multiple_target_calls`, `non_literal_argument`, `unsupported_expression`, `unsupported_strategy`, `unsupported_assumption`, `generator_variable_rebound`, `parse_error`, and `ambiguous_rejects`. Exit code 4 is returned when no source parses, with no report emitted.

```json
{
  "schema": "mumei.test-harvest/v1",
  "sources": ["tests/test_math.py"],
  "targets": {
    "add": {
      "python": {
        "params": ["left", "right"],
        "file": "tests/test_math.py",
        "line": 1
      }
    }
  },
  "observations": [
    {
      "kind": "example",
      "target": "add",
      "args": {"left": 2, "right": 3},
      "test": "test_add",
      "file": "tests/test_math.py",
      "line": 5,
      "result": 5
    }
  ],
  "skipped": [],
  "totals": {
    "tests": 1,
    "observations": {"example": 1, "relation": 0, "rejects": 0, "property": 0},
    "skipped": 0
  }
}
```

```python
# tests/python/test_math.py
def add(left: int, right: int) -> int:
    return left + right

def test_add():
    assert add(2, 3) == 5
```

```bash
uv run python -m agent harvest-tests tests/python/test_math.py
```

The observation is an `example` for target `add`, arguments `{"left": 2, "right": 3}`, and result `5`.

### Check observations against contracts

`observe-tests` runs the harvested observations through `mumei observe`.
Choose an existing `.mm` module with `--mm`, or pass an extracted forge spec
with `--spec` (the harvest arguments are aligned to its parameter order):

```bash
uv run python -m agent observe-tests --mm contracts.mm tests/python/
uv run python -m agent observe-tests --spec extracted.json tests/python/ \
  --language python --output observation-report.json
```

The report is printed as JSON unless `--output` is supplied; a verdict summary
and any warnings are printed to stderr. Property observations can be
`entailed`, `not_entailed`, `contradicts_ensures`, `domain_exceeds_requires`,
`outside_requires`, `inconclusive`, or `not_checked`. `not_checked` can mean
that the installed `mumei` build does not support property observations.
Only `contradicts_ensures` and `requires_admits_rejected` produce exit status
`1`; outside-requires, explained rejections, inconclusive checks, unsupported
observations, and other warnings do not fail the run. An invalid input or
unavailable/incompatible `mumei observe` returns status `4`.

`extract-spec --from-tests` uses the same observations as extraction context
and retries specs that contradict examples, admit rejected inputs, or fail to
guarantee a property predicate. Property contradictions block extraction;
`not_entailed` is retry feedback while retries remain and a warning on the
final attempt, while `domain_exceeds_requires` is a warning. Missing atoms are
retry feedback but do not block the final extraction attempt:

```bash
uv run mumei-agent extract-spec \
  --text "add returns the sum of two integers" \
  --from-tests tests/python/ --from-tests-language python \
  --observations-output observation-report.json \
  --output extracted.json
```

Property context is quantified over the generated variables and their ranges,
with the test assumptions made explicit, for example:

```text
for all x in [0, 100], y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies (result >= x)
```

```rust
// tests/rust/math.rs
fn add(left: i64, right: i64) -> i64 {
    left + right
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_add() {
        assert_eq!(super::add(2, 3), 5);
    }
}
```

```bash
uv run python -m agent harvest-tests tests/rust/math.rs
```

This produces the same `example` shape with Rust parameter names and paths relative to the supplied input root.

## Verification Workflow Guide

ユースケース別の検証手順（自然言語仕様の矛盾チェック、既存コードの検証、仕様↔コード整合性検証、人間向け操作ガイド）は [`docs/VERIFICATION_WORKFLOW_GUIDE.md`](./VERIFICATION_WORKFLOW_GUIDE.md) を参照。

## Forge Mode

`forge` extends the mumei [standard library](https://github.com/mumei-lang/mumei/tree/develop/std) with new verified atoms described in task spec JSON files.

```bash
# Preview the execution plan without running anything
uv run mumei-agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --dry-run

# Run a single spec (path is looked up relative to --tasks-dir)
uv run mumei-agent forge --mumei-repo ../mumei --task vstd_safe_add.json

# Bias the queue toward the weakest P16 benchmark categories' stdlib domains
uv run mumei-agent forge --mumei-repo ../mumei --max-tasks 2 \
  --benchmark-feedback /tmp/forge-feedback.json

# Run the whole queue, capped at 5 tasks per invocation
uv run mumei-agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --max-tasks 5

# Reject task contracts that do not constrain their generated bodies
uv run mumei-agent forge --mumei-repo ../mumei --task vstd_safe_add.json \
  --controls-gate require
```

Each task spec declares a `target_file` inside the mumei repo, a `mode`
(`append`, `create`, or `replace`), and one or more `atoms`.  The orchestrator
drives `generate_code()` + `mumei verify --json` + self-healing, appends
(or creates/replaces) the target `.mm` file, optionally git-commits the
change, and records the outcome to `forge_log.json`.  Already-completed
`task_id`s are automatically skipped on subsequent runs.

After full-file verification, Forge checks only the task's atom names; existing
atoms in append-mode targets are not included. `--controls-gate` accepts `off`,
`warn` (the default), or `require`, with `CONTROLS_GATE` providing the default
for both Forge and Generate. In `require` mode a weak or inconclusive task
contract fails without an LLM retry and restores the target file. See the
[Mumei controls guide](https://github.com/mumei-lang/mumei/blob/develop/docs/CONTROLS.md);
equivalent mutants can survive and require human judgment. Proliferate, MCP
`generate`/`self_correct` tools, and Heal are outside this gate.

Create/replace tasks whose atoms provide explicit `body` values and set
`deterministic_bodies: true` are rendered deterministically without requiring an
LLM credential; `vstd_core_predicates.json` and `vstd_crypto_primitives.json`
exercise this no-LLM path.

See [`forge_tasks/README.md`](../forge_tasks/README.md) for the full task
spec schema.

## Benchmark Feedback (P16-C)

The mumei benchmark suite can drive vStd prioritisation:

```bash
# In the mumei repo: score each benchmark category and emit the feedback doc
python3 benchmarks/run_benchmarks.py --forge-feedback /tmp/forge-feedback.json

# In mumei-agent: bias gap proposals / forge tasks toward weak domains
uv run mumei-agent proliferate --mumei-repo ../mumei \
  --benchmark-feedback /tmp/forge-feedback.json \
  --output-json /tmp/proliferate/summary.json
```

The `mumei.benchmark_forge_feedback/v1` document carries a per-category
`weakness_score` (expected-outcome match rate, counterexample catch rate,
trusted ratio, plus Z3 / Lean solver-time signals) and the resulting negative
`priority_delta` per stdlib domain. Feedback only **reorders** work that gap
analysis already produced — it never adds or drops proposals — and the applied
bias is recorded under `benchmark_feedback` in the run summary JSON. A missing or
malformed document is logged and ignored so the loop still runs.
