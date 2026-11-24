# mumei-agent — agent instructions

Canonical agent guidance lives in [`AGENTS.md`](../AGENTS.md): fast-path setup/test commands (`uv sync --extra test`, `uv run pytest`, ruff, pre-commit), secret-handling rules, and naming/output-surface rules.

Tool-specific guides:

- Claude Code / MCP setup, forge workflow, and LLM env-var summary: [`.claude/CLAUDE.md`](../.claude/CLAUDE.md)
- Full environment-variable reference (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, USE_MCP_SAMPLING, ...): [`agent/env_reference.py`](../agent/env_reference.py) — run `uv run python -m agent config` to inspect effective values.
