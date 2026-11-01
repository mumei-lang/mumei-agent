# Agent guidelines

These rules are for coding agents and harnesses that work in this repository (Devin, Codex, Claude Code, Cursor and others). [`.claude/CLAUDE.md`](.claude/CLAUDE.md) covers MCP setup and the forge workflow. The rules below apply in addition to it.

## Secrets and sensitive data

These rules follow the OWASP Logging and Secrets Management cheat sheets, CWE-200, CWE-532 and CWE-798.

- Never write a secret value to any output. That includes:
  - CLI text and JSON
  - logs, OpenTelemetry spans and attributes
  - MCP tool results and the MCP log (`MUMEI_AGENT_MCP_LOG`)
  - latent-protocol audit logs (`LATENT_PROTOCOL_AUDIT_LOG`)
  - forge/heal/audit reports, `forge_log.json` and Lean evidence directories
  - exception messages, test snapshots, PR descriptions and commit messages

  Report only whether the secret is set.
- Don't mask secrets with `***` or by showing the first or last characters. Leave the value out entirely. A mask still says something about the value, and masking rules are easy to get wrong.
- Classify every environment variable that can hold a credential as `sensitive=True` in [`agent/env_reference.py`](agent/env_reference.py). Today that is `GITHUB_TOKEN`, `LATENT_PROTOCOL_KEY`, `LLM_API_KEY` and `OPENAI_API_KEY`. The registry test fails when a name looks like a credential (TOKEN, KEY, SECRET, PASSWORD, AUTH, ...) but is neither classified as sensitive nor listed as a reviewed exception, so each new variable gets an explicit decision.
- Print URL values (for example `LLM_BASE_URL` and `OTEL_EXPORTER_OTLP_ENDPOINT`) without userinfo, query or fragment, because those parts can carry credentials. `python -m agent config` already does this.
- Only print environment variables that are in the registry. Never dump the whole environment. Passing `os.environ` to a subprocess is fine. Echoing it is not.
- Don't commit credentials. `.env` is gitignored. Keep [`.env.example`](.env.example) to placeholders.
- Tests that touch secret handling use an obviously fake sentinel value and assert that it never appears in stdout, stderr or written files.

## LLM and MCP guardrails

- Never put secret values or environment dumps into LLM prompts, sampling requests or MCP tool results. Model input and output end up in logs, reports, PR comments and evidence directories.
- Treat model output as untrusted. Don't let it pick which environment variables or files get read or printed.
- Build logs and failure messages that go to a model or into a report must have checkout-local paths redacted first, as `agent/lean_ai_proof.py` does.

## When you change an output surface

When a change adds or widens an output surface, check it against the rules above before opening the PR. Output surfaces include a command, a report field, a log line, an MCP tool, a prompt template and a JSON schema. Don't paste secret values into chat, issues, PRs or tool arguments that may be logged. To check a credential, check whether it is set.
