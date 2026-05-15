"""Optional MCP client for richer verification feedback (P10).

By default mumei-agent talks to the mumei compiler via subprocess
(``mumei verify --json`` etc.) wrapped by :class:`agent.mumei_client.MumeiClient`.
That works everywhere but only returns the raw report JSON.

When the mumei MCP server is reachable, :class:`MumeiMCPClient` here
calls its richer tools (``validate_logic``, ``analyze_std_gaps``,
``list_std_catalog``, ``get_inferred_effects``, ``visualize_std_graph``)
which return semantic feedback, machine-readable failure summaries, and
counter-example details that the raw CLI does not.

Two modes are supported:

1. **In-process** (default when the mumei repo is on ``PYTHONPATH``):
   import ``mcp_server`` directly and call the tool functions.  This
   uses the same import dance as
   :func:`agent.propose._load_gaps_from_mcp` and avoids spawning a
   subprocess.
2. **stdio subprocess** (set ``MUMEI_MCP_COMMAND``): spawn an MCP
   server process and talk to it over the stdio transport via the
   official ``mcp`` Python SDK.  Useful when mumei is installed as a
   separate process / different Python environment.

Set ``USE_MCP_CLIENT=true`` to opt into MCP-backed verification at the
``MumeiMCPClient.validate_logic`` site; any failure transparently falls
back to a :class:`MumeiClient` subprocess call so the agent always
makes progress.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.mumei_client import MumeiClient

logger = logging.getLogger(__name__)


def use_mcp_client_enabled() -> bool:
    """Return True when ``USE_MCP_CLIENT=true|1|yes|on``."""
    return os.environ.get("USE_MCP_CLIENT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


@dataclass
class _InProcessTool:
    """Wrapper around an in-process FastMCP tool callable."""

    name: str
    func: Any

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # FastMCP wraps tools in a callable with optional ``.fn``
        # attribute; prefer that when present (matches the pattern in
        # ``agent.propose._load_gaps_from_mcp``).
        raw = getattr(self.func, "fn", self.func)
        return raw(*args, **kwargs)


class MumeiMCPClient:
    """Drop-in alternative to :class:`MumeiClient` backed by MCP tools.

    The constructor accepts the same ``mumei_bin`` argument as
    :class:`MumeiClient` so this class can serve as a stand-in wherever
    the bare CLI is used today.  It always keeps a real
    :class:`MumeiClient` around for the fallback path.
    """

    def __init__(
        self,
        mumei_bin: str = "mumei",
        *,
        fallback_client: MumeiClient | None = None,
    ) -> None:
        self.mumei_bin = mumei_bin
        self._fallback = fallback_client or MumeiClient(mumei_bin)
        self._inproc_module: Any | None = None
        self._mode = self._detect_mode()
        self._mcp_command = os.environ.get("MUMEI_MCP_COMMAND", "").strip()

    # ------------------------------------------------------------------
    # Mode detection
    # ------------------------------------------------------------------

    def _detect_mode(self) -> str:
        """Pick a transport mode (``in-process`` / ``stdio`` / ``unavailable``)."""
        try:
            import importlib

            module = importlib.import_module("mcp_server")
        except Exception as exc:
            logger.debug("MumeiMCPClient: in-process import failed (%s)", exc)
            module = None

        if module is not None:
            self._inproc_module = module
            return "in-process"

        if os.environ.get("MUMEI_MCP_COMMAND", "").strip():
            return "stdio"

        return "unavailable"

    @property
    def mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_inproc_tool(self, name: str) -> _InProcessTool | None:
        if self._inproc_module is None:
            return None
        func = getattr(self._inproc_module, name, None)
        if func is None or not callable(getattr(func, "fn", func)):
            return None
        return _InProcessTool(name, func)

    def _call_tool(self, name: str, /, **kwargs: Any) -> Any:
        """Invoke an MCP tool by *name*, returning the parsed payload.

        Raises :class:`RuntimeError` when no MCP transport is available
        so callers can decide whether to fall back to the CLI.
        """
        if self._mode == "in-process":
            tool = self._resolve_inproc_tool(name)
            if tool is None:
                raise RuntimeError(
                    f"MCP tool '{name}' is not exported by mcp_server"
                )
            return tool(**kwargs)

        if self._mode == "stdio":
            return self._call_stdio_tool(name, kwargs)

        raise RuntimeError(
            "no MCP transport available "
            "(set PYTHONPATH to the mumei repo or MUMEI_MCP_COMMAND)"
        )

    def _call_stdio_tool(self, name: str, kwargs: dict[str, Any]) -> Any:
        """Invoke *name* via a one-shot stdio subprocess MCP session.

        Lazy-imports the ``mcp`` SDK + ``anyio`` so the dependency is
        only paid when an external transport is configured.
        """
        if not self._mcp_command:
            raise RuntimeError("MUMEI_MCP_COMMAND is not set")

        try:
            import anyio
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError(f"mcp SDK is unavailable: {exc}") from exc

        parts = shlex.split(self._mcp_command)
        params = StdioServerParameters(command=parts[0], args=parts[1:])

        async def _run() -> Any:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await session.call_tool(name, arguments=kwargs)

        result = anyio.run(_run)
        return _coerce_tool_result(result)

    # ------------------------------------------------------------------
    # Tool wrappers (drop-in alternative to MumeiClient methods)
    # ------------------------------------------------------------------

    def validate_logic(self, source_code: str) -> dict[str, Any]:
        """Verify *source_code* via the ``validate_logic`` MCP tool.

        Returns a dict containing at least ``success`` (bool), ``raw``
        (the raw tool string), and ``mode`` (which transport was used).
        On any error, falls back to a subprocess
        :meth:`MumeiClient.verify` call and reports
        ``mode = "fallback"``.
        """
        if self._mode != "unavailable":
            try:
                raw = self._call_tool("validate_logic", source_code=source_code)
                if not isinstance(raw, str):
                    raw_str = json.dumps(raw, ensure_ascii=False, default=str)
                else:
                    raw_str = raw
                payload = _parse_validate_logic(raw_str)
                payload["mode"] = self._mode
                return payload
            except Exception as exc:
                logger.warning(
                    "MumeiMCPClient: validate_logic failed (%s); falling back to CLI",
                    exc,
                )

        return self._fallback_validate(source_code)

    def analyze_gaps(self) -> dict[str, Any]:
        """Call the ``analyze_std_gaps`` MCP tool."""
        if self._mode == "unavailable":
            raise RuntimeError(
                "analyze_gaps requires an MCP transport "
                "(set PYTHONPATH to the mumei repo)"
            )
        raw = self._call_tool("analyze_std_gaps")
        return _decode_json_or_dict(raw)

    def list_catalog(self) -> dict[str, Any]:
        """Call the ``list_std_catalog`` MCP tool."""
        if self._mode == "unavailable":
            raise RuntimeError("list_catalog requires an MCP transport")
        raw = self._call_tool("list_std_catalog")
        return _decode_json_or_dict(raw)

    def get_effects(self, source_code: str) -> dict[str, Any]:
        """Call the ``get_inferred_effects`` MCP tool."""
        if self._mode == "unavailable":
            return self._fallback_infer_effects(source_code)
        try:
            raw = self._call_tool(
                "get_inferred_effects", source_code=source_code
            )
            return _decode_json_or_dict(raw)
        except Exception as exc:
            logger.warning(
                "MumeiMCPClient: get_effects failed (%s); falling back",
                exc,
            )
            return self._fallback_infer_effects(source_code)

    def _fallback_infer_effects(self, source_code: str) -> dict[str, Any]:
        """Run ``MumeiClient.infer_effects`` on a temp file and clean up.

        Mirrors the cleanup pattern of :meth:`_fallback_validate` so the
        ``.mm`` temp file is always unlinked, even when
        ``infer_effects`` raises.
        """
        path = _write_temp_mm(source_code)
        try:
            return self._fallback.infer_effects(path)
        finally:
            try:
                Path(path).unlink()
            except OSError:
                pass

    def visualize_graph(self, format: str = "mermaid") -> str:
        """Call the ``visualize_std_graph`` MCP tool."""
        if self._mode == "unavailable":
            raise RuntimeError("visualize_graph requires an MCP transport")
        raw = self._call_tool("visualize_std_graph", format=format)
        if isinstance(raw, str):
            return raw
        return json.dumps(raw, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    # MumeiClient compatibility shim
    # ------------------------------------------------------------------

    def verify(
        self,
        source_path: str,
        report_dir: str | None = None,
        spec_code_mapping: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """``MumeiClient.verify``-compatible wrapper.

        When MCP is enabled (``USE_MCP_CLIENT=true``) and a transport is
        available, this routes through ``validate_logic`` so callers
        receive richer feedback in the ``report`` field.  Otherwise it
        forwards directly to the underlying CLI client.
        """
        if not use_mcp_client_enabled() or self._mode == "unavailable":
            return self._fallback.verify(
                source_path,
                report_dir=report_dir,
                spec_code_mapping=spec_code_mapping,
            )
        try:
            source_code = Path(source_path).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "MumeiMCPClient.verify: failed to read %s (%s); falling back",
                source_path,
                exc,
            )
            return self._fallback.verify(
                source_path,
                report_dir=report_dir,
                spec_code_mapping=spec_code_mapping,
            )
        result = self.validate_logic(source_code)
        report = result.get("report") or {}
        if isinstance(report, dict) and (report or spec_code_mapping):
            report.setdefault("spec_code_mapping", spec_code_mapping or [])
        return {
            "success": result.get("success", False),
            "report": report,
            "stdout": result.get("raw", ""),
            "stderr": "" if result.get("success") else result.get("raw", ""),
            "mcp": True,
            "spec_code_mapping": spec_code_mapping or [],
        }

    def check(self, source_path: str) -> dict[str, Any]:
        """Forward to the CLI client (no MCP equivalent)."""
        return self._fallback.check(source_path)

    def infer_effects(self, source_path: str) -> dict[str, Any]:
        """Forward to the CLI client (no MCP equivalent for path-based input)."""
        return self._fallback.infer_effects(source_path)

    def infer_contracts(self, source_path: str) -> dict[str, Any]:
        """Forward to the CLI client (no MCP equivalent for path-based input).

        Required by :func:`agent.strategies.generate_strategy.generate_code`
        when a spec sets ``context_file``; without this shim the
        ``USE_MCP_CLIENT=true`` path would raise ``AttributeError``.
        """
        return self._fallback.infer_contracts(source_path)

    def build(self, source_path: str, output: str = "katana") -> dict[str, Any]:
        """Forward to the CLI client (no MCP equivalent)."""
        return self._fallback.build(source_path, output=output)

    def build_with_emit(
        self, source_path: str, emit: str, output: str = "katana"
    ) -> dict[str, Any]:
        """Forward to the CLI client (no MCP equivalent for FFI emit targets).

        Kept so :class:`MumeiMCPClient` is a complete drop-in replacement
        for :class:`MumeiClient` — including the ``publish`` pipeline
        which calls ``build_with_emit`` for c-header / rust-wrapper /
        python-wrapper generation.
        """
        return self._fallback.build_with_emit(source_path, emit, output=output)

    # ------------------------------------------------------------------
    # Internal fallback
    # ------------------------------------------------------------------

    def _fallback_validate(self, source_code: str) -> dict[str, Any]:
        """Run :meth:`MumeiClient.verify` on a temp file and reshape the result."""
        path = _write_temp_mm(source_code)
        try:
            verify = self._fallback.verify(path)
        finally:
            try:
                Path(path).unlink()
            except OSError:
                pass
        return {
            "success": bool(verify.get("success", False)),
            "report": verify.get("report") or {},
            "raw": verify.get("stdout") or verify.get("stderr") or "",
            "mode": "fallback",
            "semantic_feedback": (verify.get("report") or {}).get(
                "semantic_feedback"
            ),
            "machine_readable": (verify.get("report") or {}).get(
                "machine_readable"
            ),
            "counter_example": (verify.get("report") or {}).get(
                "counter_example"
            ),
            "effect_violation": (verify.get("report") or {}).get(
                "effect_violation"
            ),
        }


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _write_temp_mm(source_code: str) -> str:
    """Persist *source_code* to a NamedTemporaryFile and return the path."""
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".mm", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(source_code)
    finally:
        tmp.close()
    return tmp.name


def _coerce_tool_result(result: Any) -> Any:
    """Pull the textual payload out of an MCP ``CallToolResult``."""
    content = getattr(result, "content", None)
    if not content:
        return result
    parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts) if parts else result


def _decode_json_or_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            return {"value": data}
        except json.JSONDecodeError:
            return {"raw": raw}
    return {"value": raw}


def _parse_validate_logic(raw: str) -> dict[str, Any]:
    """Best-effort parse of the ``validate_logic`` Markdown payload.

    The MCP server formats the output as a Markdown-y string with an
    embedded ``Verification Report`` JSON block.  We extract the JSON
    block when present, infer ``success`` from the prefix, and surface
    the structured feedback fields directly so callers don't have to
    re-parse the prose.
    """
    # Match the *value* (``true``) rather than just the key name —
    # otherwise ``"all_constraints_satisfied": false`` would still
    # satisfy a substring check and produce a false-positive ``success``
    # when the embedded JSON block fails to parse.
    success = (
        "Forge succeeded" in raw
        or '"all_constraints_satisfied": true' in raw
        or '"all_constraints_satisfied":true' in raw
    )
    report: dict[str, Any] = {}
    marker = "### Verification Report"
    if marker in raw:
        block = raw.split(marker, 1)[1]
        # The JSON sits inside ```json ... ``` fences.
        if "```json" in block:
            block = block.split("```json", 1)[1]
            if "```" in block:
                block = block.split("```", 1)[0]
            try:
                report = json.loads(block)
            except json.JSONDecodeError:
                report = {}
    if isinstance(report, dict) and "success" in report:
        success = bool(report.get("success", success))
    return {
        "success": success,
        "report": report,
        "raw": raw,
        "semantic_feedback": (
            report.get("semantic_feedback") if isinstance(report, dict) else None
        ),
        "machine_readable": (
            report.get("machine_readable") if isinstance(report, dict) else None
        ),
        "counter_example": (
            report.get("counter_example") if isinstance(report, dict) else None
        ),
        "effect_violation": (
            report.get("effect_violation") if isinstance(report, dict) else None
        ),
    }


__all__ = ["MumeiMCPClient", "use_mcp_client_enabled"]
