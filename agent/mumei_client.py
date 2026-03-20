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
        """Run mumei verify --json and return parsed result."""
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

    def build(self, source_path: str, output: str = "katana") -> dict:
        """Run mumei build and return result."""
        cmd = [*self._cmd_prefix, "build", source_path, "-o", output]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
