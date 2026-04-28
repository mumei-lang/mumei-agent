"""Wrapper for mumei CLI commands."""
from __future__ import annotations

import json
import subprocess


def create_mumei_client(mumei_bin: str = "mumei") -> "MumeiClient":
    """Return a verifier client honoring the ``USE_MCP_CLIENT`` flag.

    When ``USE_MCP_CLIENT=true`` (and the mumei MCP server is reachable
    either in-process via ``PYTHONPATH`` or as a stdio subprocess via
    ``MUMEI_MCP_COMMAND``), this returns a
    :class:`agent.mcp_client.MumeiMCPClient` so callers benefit from
    richer semantic feedback / counter-example details.  Otherwise it
    returns a plain :class:`MumeiClient`.

    The MCP client is API-compatible with :class:`MumeiClient` for the
    methods used by the forge / heal / proliferate pipelines and falls
    back to subprocess CLI calls automatically on any error.
    """
    try:
        from agent.mcp_client import MumeiMCPClient, use_mcp_client_enabled
    except Exception:
        return MumeiClient(mumei_bin)
    if use_mcp_client_enabled():
        client = MumeiMCPClient(mumei_bin)
        if client.mode != "unavailable":
            return client  # type: ignore[return-value]
    return MumeiClient(mumei_bin)


class MumeiClient:
    """Abstraction over mumei CLI for verification."""

    def __init__(self, mumei_bin: str = "mumei"):
        self.mumei_bin = mumei_bin
        # Support "cargo run --" style invocation
        self._cmd_prefix = mumei_bin.split()

    def verify(self, source_path: str, report_dir: str | None = None) -> dict:
        """Run mumei verify --json and return parsed result.

        The self-healing loop calls this method to obtain a structured
        verification report as an in-memory dict.
        """
        cmd = [*self._cmd_prefix, "verify", "--json"]
        if report_dir:
            cmd.extend(["--report-dir", report_dir])
        cmd.append(source_path)

        result = subprocess.run(cmd, capture_output=True, text=True)
        report = {}
        if result.stdout.strip():
            try:
                report = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
        return {
            "success": result.returncode == 0,
            "report": report,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def check(self, source_path: str) -> dict:
        """Run mumei check to verify parsing succeeds.

        Returns:
            Dict with keys: success (bool), stdout (str), stderr (str).
        """
        cmd = [*self._cmd_prefix, "check", source_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def infer_effects(self, source_path: str) -> dict:
        """Run mumei infer-effects and return parsed JSON result."""
        cmd = [*self._cmd_prefix, "infer-effects", source_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            try:
                return {"success": True, "analysis": json.loads(result.stdout)}
            except json.JSONDecodeError:
                pass
        return {"success": False, "analysis": {}}

    def infer_contracts(self, source_path: str) -> dict:
        """Run mumei infer-contracts and return parsed JSON result."""
        cmd = [*self._cmd_prefix, "infer-contracts", source_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            try:
                return {"success": True, "analysis": json.loads(result.stdout)}
            except json.JSONDecodeError:
                pass
        return {"success": False, "analysis": {}}

    def build_with_emit(self, source_path: str, emit: str, output: str = "katana") -> dict:
        """Run mumei build with a specific --emit target.

        The emit targets generate FFI glue code (not transpiled code):
        - c-header: generates .h files
        - rust-wrapper: generates Rust extern "C" bindings + safe wrappers
        - python-wrapper: generates ctypes-based Python wrappers
        """
        cmd = [*self._cmd_prefix, "build", source_path, "-o", output, "--emit", emit]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def build(self, source_path: str, output: str = "katana") -> dict:
        """Run mumei build and return result.

        Note: The self-healing loop now uses verify() instead.  This method
        is retained for standalone build use-cases.
        """
        cmd = [*self._cmd_prefix, "build", source_path, "-o", output]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
