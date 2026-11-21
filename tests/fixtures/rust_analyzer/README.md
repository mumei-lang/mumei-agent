# Rust compiler snapshot fixtures

These envelopes capture `rust-analyzer lsif` output from the adjacent Cargo
projects with rust-analyzer `1.100.0 (0ef1bc3 2026-11-09)`. Regenerate them with
the pinned tool:

```sh
python3 tests/fixtures/rust_analyzer/regenerate.py /path/to/rust-analyzer
```

The producer replaces the Cargo root with `file:///project` and rewrites Rust
sysroot source URIs relative to the rustlib source root as
`file:///sysroot/...`. Project documents contain their exact UTF-8 source,
including `Cargo.toml` and `Cargo.lock`; document hashes and URI placeholders
make the checked-in envelopes byte-reproducible across machines.

The pinned fixture output uses these LSIF labels:
`contains`, `definitionResult`, `document`, `foldingRangeResult`, `hoverResult`,
`item`, `metaData`, `moniker`, `next`, `packageInformation`, `range`,
`referenceResult`, `resultSet`, `textDocument/definition`,
`textDocument/foldingRange`, `textDocument/hover`, and
`textDocument/references`.

The agent only reads these envelopes and never launches rust-analyzer, Cargo,
or rustc. Exact source equality detects stale output, not producer authenticity.
The reader rejects dependencies, build scripts, proc-macro crates, and workspace
members beyond the root package. Lexical comparison refuses macro invocation,
macro definition, and conditional-compilation gaps. Cross-file and external
references are metadata only and are not compared with single-file lexical
bindings. These fixtures make no trust, audit, Evidence, Seal Grade, ABI,
runtime, or proof claim.
