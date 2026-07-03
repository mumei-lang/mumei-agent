"""Utility helpers for the MCP server."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context

def _err(message: str, **extra: Any) -> str:
    """Return a JSON-encoded error payload."""
    payload: dict[str, Any] = {"status": "error", "error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)

def _ok(payload: dict[str, Any]) -> str:
    """Return a JSON-encoded ``status: ok`` payload."""
    payload.setdefault("status", "ok")
    return json.dumps(payload, ensure_ascii=False, default=str)

def _ok_dataclass(result: Any) -> str:
    """Return a dataclass result as a JSON-encoded ``status: ok`` payload."""
    return _ok(asdict(result))

def _resolve_repo(path: str) -> Path:
    """Resolve *path* as an absolute Path."""
    return Path(path).expanduser().resolve()

def _parse_spec_files(spec_files: Any) -> list[str]:
    if isinstance(spec_files, list):
        return [str(item) for item in spec_files if str(item).strip()]
    if not isinstance(spec_files, str):
        return []
    text = spec_files.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]

def _parse_error_report(error_report: str) -> tuple[dict[str, Any], str]:
    if not error_report:
        return {}, ""
    try:
        parsed = json.loads(error_report)
    except json.JSONDecodeError:
        return {"raw": error_report}, error_report
    if isinstance(parsed, dict):
        return parsed, error_report
    return {"raw": parsed}, error_report

def _existing_path_arg(value: str) -> Path | None:
    if not value or "\n" in value or len(value) > 4096:
        return None
    try:
        candidate = Path(value).expanduser()
        if candidate.exists():
            return candidate.resolve()
    except OSError:
        return None
    return None

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}

def _sampling_enabled(config: Any) -> bool:
    return bool(getattr(config, "use_mcp_sampling", False)) or _env_bool("USE_MCP_SAMPLING")

def _llm_provider_for_context(config: Any, ctx: Context | None) -> Any | None:
    if not _sampling_enabled(config) or ctx is None:
        return None
    from agent.llm_provider import McpSamplingLLMProvider, OpenAILLMProvider

    return McpSamplingLLMProvider(ctx, fallback=OpenAILLMProvider(config))

def _llm_client_for_context(config: Any, ctx: Context | None) -> Any:
    provider = _llm_provider_for_context(config, ctx)
    if provider is None:
        return config.create_client()
    from agent.llm_provider import openai_client_adapter

    return openai_client_adapter(provider)

def _json_object_arg(value: Any, name: str) -> tuple[dict[str, Any], str | None]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            return {}, f"{name} is not valid JSON: {exc}"
    else:
        decoded = value
    if not isinstance(decoded, dict):
        return {}, f"{name} must decode to a JSON object"
    return decoded, None
