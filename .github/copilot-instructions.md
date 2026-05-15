# Mumei Agent Development Guide

Always reference these instructions first and fall back to search or shell commands only when you encounter unexpected information that does not match the info here.

## Working Effectively

### Repository Role

`mumei-agent` is the LLM-driven autonomous repair and generation layer for the Mumei ecosystem. It calls the Mumei compiler/CLI for Z3 verification and may call Lean bridge tooling, but the Mumei compiler itself does **not** use LLMs. LLM calls belong here, in `mumei-agent`.

### Bootstrap and Test

Validated setup:

```bash
python -m pip install -e ".[test]"
```

Optional MCP support:

```bash
python -m pip install -e ".[mcp]"
```

Run tests:

```bash
pytest -v
```

If pre-commit is configured in a future revision, run:

```bash
pre-commit run --all-files
```

## LLM Configuration

The agent uses an OpenAI-compatible client.

| Variable | Meaning |
| --- | --- |
| `LLM_API_KEY` | API key for the LLM provider. `OPENAI_API_KEY` is accepted as fallback. |
| `LLM_BASE_URL` | Optional OpenAI-compatible API base URL, e.g. local Ollama or another provider. |
| `LLM_MODEL` | Model name. Defaults to `gpt-4o`. |
| `MUMEI_BIN` | Mumei CLI command/path. Defaults to `mumei`. |
| `MUMEI_REPO` | Mumei compiler checkout for std/ health, forge, and proliferate flows. |
| `MUMEI_LEAN_REPO` | Optional mumei-lean checkout for Lean fallback in proliferate. |
| `USE_MCP_CLIENT` | When true, route verification through the Mumei MCP client before falling back to subprocess verification. |
| `PREFER_MCP_GAPS` | When true, prefer the Mumei MCP server gap analyzer. |
| `AGENT_STRATEGY` | Repair strategy: `single` or `multi-stage`. |
| `ENABLE_LATENT_DEBUG` | When true, enable latent-space debugging in fix strategy (experimental). |
| `ENABLE_DENSE_PROPERTIES` | When true, enable high-density property generation (experimental). |
| `ENABLE_LATENT_PROTOCOL` | When true, enable the latent representation MCP protocol (experimental). |

Local Ollama smoke-test example:

```bash
export LLM_API_KEY=ollama
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen2.5:0.5b
```

## Subcommands

Run commands through `python -m agent`:

| Command | Purpose |
| --- | --- |
| `python -m agent heal [file.mm]` | Self-heal a failing `.mm` source file. |
| `python -m agent generate --spec-file spec.json --output out.mm` | Generate verified `.mm` code from a spec. |
| `python -m agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei` | Execute std extension forge tasks. |
| `python -m agent forge --dry-run` | Preview forge tasks without LLM/API key. |
| `python -m agent extract-spec --text "..." --output spec.json` | Extract a forge task spec from natural language. |
| `python -m agent extract-spec --text "..." --output spec.json --generate --generate-output out.mm` | Extract, generate, and verify in one flow. |
| `python -m agent proliferate --mumei-repo ../mumei --output-json summary.json` | Analyze gaps, generate candidates, run blast-radius checks, and summarize health delta. |
| `python -m agent health --mumei-repo ../mumei --format json` | Measure std proof health and `health_score`. |
| `python -m agent propose --mumei-repo ../mumei` | Generate forge task specs from gap analysis. |
| `python -m agent publish ...` | Generate, verify, emit wrappers, and prepare delivery artifacts. |
| `python -m agent mcp-server` | Start the mumei-agent MCP server. |

## MCP Servers

`.mcp.json` registers two stdio servers:

```json
{
  "mcpServers": {
    "mumei-forge": {
      "command": "sh",
      "args": ["-lc", "cd ../mumei && exec python mcp_server.py"]
    },
    "mumei-agent": {
      "command": "sh",
      "args": ["-lc", "cd . && exec python -m agent mcp-server"]
    }
  }
}
```

Important mumei-agent MCP tools:

| Tool | Use |
| --- | --- |
| `forge_task(task_json, mumei_repo, dry_run)` | Run or preview one forge spec. |
| `heal_file(source_code, error_report)` | Repair `.mm` source with the fix strategy. |
| `measure_std_health(mumei_repo)` | Measure std proof health for a Mumei checkout. |
| `propose_forge_tasks(mumei_repo, max_proposals)` | Analyze gaps and propose forge specs. |
| `list_forge_log(log_path)` | Read `forge_log.json`. |
| `get_agent_status()` | Inspect LLM settings, Mumei binary, feature flags, and subcommands. |
| `extract_spec(natural_language, domain_hint, generate)` | Extract NL requirements into a forge task spec; optionally generate verified code. |
| `extract_spec_from_code(code_file, language, domain_hint, generate, mumei_repo)` | Extract NL requirements from existing source code, then convert them into a forge task spec. |
| `send_latent_message(message, context, verify)` | Encode an inter-agent message as a latent vector when `ENABLE_LATENT_PROTOCOL=true`. |

## Common Workflows

### Repair `.mm` Code

```bash
python -m agent heal examples/sword_test.mm --max-retries 3
```

The loop runs `mumei verify --json`, reads structured feedback, asks the LLM for a repair, and verifies again.

### Generate from Spec

```bash
python -m agent generate --spec-file examples/spec.json --output out.mm --metrics
```

The generation strategy runs parse checks and `mumei verify --json`, then self-heals up to the configured retry limit.

### Extend std/

```bash
python -m agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --dry-run
python -m agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --max-tasks 1
```

Inspect `forge_log.json` after each run.

### Health and Proliferation

```bash
python -m agent health --mumei-repo ../mumei --format json
python -m agent proliferate --mumei-repo ../mumei --max-proposals 3 --output-json summary.json
```

Read `health_score`, `pre_health`, `post_health`, and `health_delta` before reporting improvement.
