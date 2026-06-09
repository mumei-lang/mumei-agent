# Mumei Agent Skills

Reusable, composable agentic workflows for AI-assisted Mumei code repair, generation, std forging, natural-language spec extraction, autonomous proliferation, and health reporting.

## Skill Catalogue

| Skill | Status | Description |
|-------|--------|-------------|
| heal | implemented | Run the self-healing loop over failing `.mm` source |
| generate | implemented | Generate verified `.mm` code from JSON specs |
| forge | implemented | Execute std extension forge task specs and inspect `forge_log.json` |
| extract-spec | implemented | Convert natural-language requirements into forge task spec JSON |
| proliferate | implemented | Analyze gaps, generate candidates, check blast radius, and summarize health delta |
| health | implemented | Measure std proof health and interpret `health_score` |

## Agent

A single orchestration agent composes these skills into end-to-end workflows:

| Agent | Role |
|-------|------|
| mumei-agent | AI-driven autonomous repair and generation agent for verified Mumei code |

## Shared Infrastructure

- `agent/config.py`: LLM, model, Mumei binary, and optional Lean checkout configuration.
- `agent/self_healing.py`: `heal` loop.
- `agent/generate.py`: spec-to-code generation.
- `agent/forge.py`: forge task orchestration and `forge_log.json`.
- `agent/extract_spec.py`: natural-language extraction CLI.
- `agent/proliferate.py`: health-driven gap closure.
- `agent/std_health.py`: std proof-health metrics.
- `agent/mcp_server.py`: MCP wrapper around forge/heal/health/propose/status/extract tools.

## Usage

Run individual skills directly:

```bash
uv run python -m agent heal examples/sword_test.mm
uv run python -m agent generate --spec-file examples/spec.json --output out.mm
uv run python -m agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --dry-run
uv run python -m agent extract-spec --text "..." --output spec.json
uv run python -m agent proliferate --mumei-repo ../mumei --output-json summary.json
uv run python -m agent health --mumei-repo ../mumei --format json
```

Non-dry-run LLM flows require `LLM_API_KEY` or `OPENAI_API_KEY`; `LLM_BASE_URL` and `LLM_MODEL` select the provider/model.
