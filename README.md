# Mumei Agent

AI-driven autonomous fix loop for the [Mumei](https://github.com/mumei-lang/mumei) proof-driven programming language. It combines LLMs (Qwen/Ollama/OpenAI) with Z3 to detect, explain, and repair code issues.

> **Note:** 本ドキュメントのコマンドは uv 管理のプロジェクト環境で実行することを前提とし、`uv run` を付けて表記している。仮想環境をアクティベート済み（`source .venv/bin/activate`）の場合は `uv run` を省略できる。

## Architecture

```
mumei CLI (Z3 verification)
  ^ subprocess: mumei check / mumei verify --json
  |
agent/self_healing.py (heal mode)     agent/generate.py (generate mode)
  ^ OpenAI-compatible API               ^ OpenAI-compatible API
  |                                      |
Ollama + Qwen (LLM inference)          Ollama + Qwen (LLM inference)
  ^ Docker Compose                       ^ Docker Compose
  |                                      |
docker-compose.yml                     docker-compose.yml
```

The detailed generate flow, MCP relationships, and harness vocabulary are in [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md) and [`docs/MCP_SERVER.md`](docs/MCP_SERVER.md).

## Background

This repository was extracted from the [mumei](https://github.com/mumei-lang/mumei)
compiler repository. The self-healing agent and Streamlit visualizer were originally
developed in-tree and moved here as a standalone project
(see [mumei-lang/mumei#90](https://github.com/mumei-lang/mumei/pull/90)).

## Prerequisites

- Python 3.10+ and [uv](https://docs.astral.sh/uv/)
- A running Mumei checkout/binary for verification
- Ollama (default) or another OpenAI-compatible LLM provider

## Quick Start

```bash
uv sync
uv run mumei-agent examples/effect_test.mm
uv run mumei-agent audit --code-file src/example.py --auto-migrate --auto-heal
```

Use `uv run mumei-agent --help` for the full command-line help. Configuration, provider setup, retry budgets, and observability are in [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

## No-.mm audit

`audit` is the single contract for auditing existing Python, Rust, TypeScript, Go, or Solidity code before a `.mm` file exists. It reports stable audit fields, migration hints, and healing evidence; the vocabulary and layer details are in [`docs/AUDIT_CONTRACT.md`](docs/AUDIT_CONTRACT.md).

The stable audit keys are `spec_health_issues`, `verification_violations`,
`verification_status`, `cross_validation_gaps`, `next_steps`, `migration_hints`,
`healed_files`, and `heal_errors`.

```bash
uv run mumei-agent audit --code-file src/example.py --auto-migrate --auto-heal
```

## P9 NLAE Integration

P9 NLAE connects loss-vector self-correction with the mumei-lean fidelity checker. Run `uv run mumei-agent self-correct ...` or the integrated pipeline; details are in [`docs/NLAE_INTEGRATION.md`](docs/NLAE_INTEGRATION.md).

## Examples and Generate Mode

Generate verified `.mm` code from a JSON specification with `uv run mumei-agent generate --spec-file spec.json`. The E2E demo and P11 natural-language extraction recordings are documented in [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md); video: [`docs/e2e_demo.mp4`](docs/e2e_demo.mp4).

## Subcommands

| Command | Purpose | Example |
|---|---|---|
| `heal` | Iteratively repair a `.mm` file | `uv run mumei-agent heal examples/effect_test.mm` |
| `generate` | Generate and verify code from a spec | `uv run mumei-agent generate --spec-file spec.json` |
| `audit` | Audit foreign code, optionally migrate and heal | `uv run mumei-agent audit --code-file src/foo.py --auto-migrate` |
| `migrate-suggest` | Generate `.mm` migration skeletons | `uv run mumei-agent migrate-suggest --code-file src/foo.py` |
| `validate-spec` | Check natural-language specs | `uv run mumei-agent validate-spec --input spec.txt --format nl` |
| `validate-code` | Infer and verify contracts from code | `uv run mumei-agent validate-code --input code.ts` |
| `validate-spec-to-code` | Compare specs to implementation | `uv run mumei-agent validate-spec-to-code --spec spec.txt --code src/foo.py --language python` |
| `validate-code-to-spec` | Detect spec drift | `uv run mumei-agent validate-code-to-spec --code src/foo.py --spec spec.txt --language python` |
| `verify-conformance` | Produce a spec-to-code conformance matrix | `uv run mumei-agent verify-conformance --spec spec.txt --code src/foo.py --language python --format human` |
| `verify-traceability` | Combine conformance and drift summaries | `uv run mumei-agent verify-traceability --code src/foo.py --spec spec.txt --language python --format human` |
| `extract-spec` | Extract a forge specification | `uv run mumei-agent extract-spec --code-file src/foo.py` |
| `check-spec-health` | Check contradictions, over-constraints, and vacuity | `uv run mumei-agent check-spec-health spec.mm` |
| `cross-validate` | Cross-validate specs and code | `uv run mumei-agent cross-validate --spec spec.txt --code src/foo.py` |
| `proliferate` | Analyze gaps, generate, heal, and deliver | `uv run mumei-agent proliferate --mumei-repo ../mumei --max-proposals 3` |
| `propose` | Generate forge task specs | `uv run mumei-agent propose --auto --mumei-repo ../mumei` |
| `analyze-std-gaps` | Identify standard-library gaps | `uv run mumei-agent analyze-std-gaps --mumei-repo ../mumei` |
| `health` | Show provider and binary health | `uv run mumei-agent health` |
| `mcp-server` | Run the FastMCP server | `uv run mumei-agent mcp-server` |

## MCP Server

`uv run mumei-agent mcp-server` exposes forge, heal, audit, health, and verification tools over stdio for Claude Code, Devin, Codex, and other MCP clients. The exported-tools table, `.mcp.json`, proof-friendly guidance, and fallback diagnostics are in [`docs/MCP_SERVER.md`](docs/MCP_SERVER.md).

## Forge Mode

Forge extends the mumei standard library with verified atoms from `forge_tasks/`:

```bash
uv run mumei-agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --max-tasks 1
```

See [`forge_tasks/README.md`](forge_tasks/README.md) for the task schema.

## CI and Reports

The `report.json` schema is documented in [mumei's REPORT_SCHEMA.md](https://github.com/mumei-lang/mumei/blob/develop/docs/REPORT_SCHEMA.md). The reusable CI verification gate and standalone script are in [`docs/CI_WORKFLOWS.md`](docs/CI_WORKFLOWS.md).

### Distributed proof artifacts

mumei release and Homebrew distributions include per-module proof certificates
under `std/certs/` and the corresponding proof bundle. A consumer can verify a
distribution without the source checkout that produced it by running
`mumei verify-cert --strict` against each packaged certificate and its packaged
source. The locations are exposed through the existing `MUMEI_PROOF_CERTS` and
`MUMEI_PROOF_BUNDLE` settings; proof artifact paths are reported under the
existing `artifact_paths` key. Consumers handling Lean provenance should inspect
`lean_provenance` and use `--allow-lean-verified` only on the acceptance path
that explicitly permits `lean_verified`.

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md) and the [cross-project roadmap](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md).

## Documentation

| Document | Contents |
|---|---|
| [`docs/AUDIT_CONTRACT.md`](docs/AUDIT_CONTRACT.md) | No-.mm audit contract, vocabulary, layers, and review flow |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | Environment variables, retry budgets, OTel, and Ollama tuning |
| [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md) | Examples, generate mode, E2E demos, and P11 extraction |
| [`docs/MCP_SERVER.md`](docs/MCP_SERVER.md) | MCP tools, configuration, diagnostics, and verification |
| [`docs/CI_WORKFLOWS.md`](docs/CI_WORKFLOWS.md) | CI verification gate and standalone usage |
| [`docs/NLAE_INTEGRATION.md`](docs/NLAE_INTEGRATION.md) | P9 NLAE integration |
| [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md) | OpenTelemetry spans, metrics, and SLO alerts |
| [`docs/OLLAMA_TUNING.md`](docs/OLLAMA_TUNING.md) | Ollama KV-cache and long-context tuning |
| [`docs/AGENT_HARNESS_SPEC.md`](docs/AGENT_HARNESS_SPEC.md) | Harness and MCP sampling contract |
| [`docs/VERIFICATION_WORKFLOW_GUIDE.md`](docs/VERIFICATION_WORKFLOW_GUIDE.md) | Verification workflows |
| [`docs/LEAN_FALLBACK.md`](docs/LEAN_FALLBACK.md) | Lean fallback errors and troubleshooting |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Agent roadmap |

## License

[Apache-2.0 license](LICENSE)
