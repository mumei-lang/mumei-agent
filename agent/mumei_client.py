"""Wrapper for mumei CLI commands."""
import subprocess
import json


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
