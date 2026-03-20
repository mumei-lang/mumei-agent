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

        Note: The self-healing loop currently uses build() instead, which
        triggers verification as a side effect.  This method is provided for
        direct verification use-cases and may replace the build-then-read-file
        pattern in a future refactor.
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

    def build(self, source_path: str, output: str = "katana") -> dict:
        """Run mumei build and return result.

        The self-healing loop uses this method because ``mumei build``
        triggers verification as a side effect and writes ``report.json``.
        A future refactor may switch to verify() → build() two-step flow;
        see verify() docstring for details.
        """
        cmd = [*self._cmd_prefix, "build", source_path, "-o", output]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
