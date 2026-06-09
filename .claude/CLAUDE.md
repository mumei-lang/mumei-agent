# mumei-agent Claude Code Guide

## Overview

mumei-agent is an AI-driven autonomous repair loop that uses mumei verification to generate, verify, and self-heal `.mm` code: 「mumei の検証機能を活用した AI 駆動の自律修正ループ」. It combines LLM output with Z3-backed proof checks so generated code can be iteratively repaired until it satisfies mumei contracts.

## Install MCP support

The MCP integration is optional. Install the project with the `mcp` extra before using the server:

```bash
uv sync --extra mcp
```

Claude Code detects `.mcp.json` at the project root. This repository registers both:

- `mumei-forge`: the mumei compiler MCP server from a sibling `../mumei` checkout.
- `mumei-agent`: the agent MCP server from this repository.

Use `/mcp` in Claude Code to inspect server status and approve tools. If your mumei checkout is not adjacent to this repository, edit `.mcp.json` or launch Claude Code with an equivalent project MCP config for your local paths.

## MCP tools

| Tool | Use |
| --- | --- |
| `forge_task(task_json, mumei_repo, dry_run)` | Run one forge spec. Use `dry_run=true` first to preview the execution plan. |
| `heal_file(source_code, error_report)` | Repair `.mm` source using the existing fix strategy and optional verification report. |
| `measure_std_health(mumei_repo)` | Measure std/ health for a mumei checkout. |
| `propose_forge_tasks(mumei_repo, max_proposals)` | Analyze std/ gaps and propose forge specs. |
| `list_forge_log(log_path)` | Read forge execution history from `forge_log.json`. |
| `get_agent_status()` | Inspect LLM settings, mumei binary configuration, feature flags, and available subcommands. |
| `extract_spec(natural_language, domain_hint, generate)` | Extract a forge task spec from natural-language requirements (Step 0). Set `generate=true` to also run the generate + refinement pipeline and return verified `.mm` code. |
| `extract_spec_from_code(code_file, language, domain_hint, generate, mumei_repo)` | Extract a natural-language spec from existing Rust/C/Go/Python/etc. source code, then feed it into the forge task spec extraction pipeline. |

## Recommended workflow

1. Call `get_agent_status` to confirm available tools and LLM configuration.
2. Call `measure_std_health` to capture the current std/ health baseline.
3. Call `propose_forge_tasks` to identify the next candidate tasks.
4. Call `forge_task` with `dry_run=true` to preview a task.
5. Call `forge_task` with `dry_run=false` only when LLM credentials and mumei paths are configured.
6. Call `list_forge_log` to inspect execution results.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `LLM_API_KEY` | API key for the OpenAI-compatible LLM provider. Required for non-dry-run forge/heal flows. |
| `MUMEI_BIN` | mumei binary or command used by the agent. Defaults to `mumei`. |
| `USE_MCP_CLIENT` | When `true`, route verification through the mumei MCP client before falling back to subprocess verification. |
| `PREFER_MCP_GAPS` | When `true`, prefer the mumei MCP server's `analyze_std_gaps` for gap analysis. |

## Notes

- `forge_task(..., dry_run=false)` may call an LLM and modify files under the target mumei repository.
- The default `.mcp.json` assumes `../mumei` exists next to this repository.
- The config uses `sh -lc "cd ... && exec ..."` instead of relying on `cwd`, because Claude Code's project MCP examples focus on `command` / `args` and `cwd` support is not reliable across versions.
