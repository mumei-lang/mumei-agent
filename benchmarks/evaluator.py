"""Quantitative evaluation framework for Mumei verification.

This module compares manual, agent, and baseline verification methods across
SV-COMP-style, Dafny puzzle, and Zero-Human benchmark categories.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""

    name: str
    category: str
    success: bool
    attempts: int
    verification_time_ms: float
    code_length: int
    solver_time_ms: float
    tokens_used: int
    method: str


@dataclass
class ComparisonMetrics:
    """Comparison metrics between different verification methods."""

    success_rate_human: float
    success_rate_agent: float
    avg_time_human: float
    avg_time_agent: float
    avg_code_quality_human: float
    avg_code_quality_agent: float
    statistical_significance: float


class BenchmarkEvaluator:
    """Evaluate benchmark results and generate comparison metrics."""

    def __init__(self, results_dir: Path):
        self.results_dir = results_dir
        self.results: list[BenchmarkResult] = []

    def run_benchmark(
        self,
        source_file: Path,
        method: str = "agent",
        max_attempts: int = 5,
    ) -> BenchmarkResult:
        """Run a single benchmark and return normalized metrics."""
        start_time = time.perf_counter()
        source_file = source_file.resolve()

        if method == "agent":
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "agent.self_healing",
                    str(source_file),
                    "--max-attempts",
                    str(max_attempts),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            attempts = self._parse_attempts(result.stdout)
            tokens_used = self._parse_tokens(result.stdout)
        else:
            result = subprocess.run(
                ["mumei", "verify", str(source_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            attempts = 1
            tokens_used = 0

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return BenchmarkResult(
            name=source_file.stem,
            category=self._categorize_benchmark(source_file),
            success=result.returncode == 0,
            attempts=attempts,
            verification_time_ms=elapsed_ms,
            code_length=len(source_file.read_text(encoding="utf-8")),
            solver_time_ms=self._parse_solver_time(result.stdout),
            tokens_used=tokens_used,
            method=method,
        )

    def compare_methods(self, category: str | None = None) -> ComparisonMetrics:
        """Compare human and agent verification methods."""
        human_results = self._results_for("human", category)
        agent_results = self._results_for("agent", category)

        return ComparisonMetrics(
            success_rate_human=self._success_rate(human_results),
            success_rate_agent=self._success_rate(agent_results),
            avg_time_human=self._average([r.verification_time_ms for r in human_results]),
            avg_time_agent=self._average([r.verification_time_ms for r in agent_results]),
            avg_code_quality_human=self._average_code_quality(human_results),
            avg_code_quality_agent=self._average_code_quality(agent_results),
            statistical_significance=self._compute_significance(
                [r.verification_time_ms for r in human_results],
                [r.verification_time_ms for r in agent_results],
            ),
        )

    def generate_report(self, output_path: Path) -> None:
        """Generate a comprehensive benchmark report."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        categories = sorted({r.category for r in self.results})
        report = {
            "summary": {
                "total_benchmarks": len(self.results),
                "human_success_rate": self._success_rate(self._results_for("human")),
                "agent_success_rate": self._success_rate(self._results_for("agent")),
            },
            "by_category": {
                category: asdict(self.compare_methods(category)) for category in categories
            },
            "detailed_results": [asdict(result) for result in self.results],
        }
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def _results_for(
        self,
        method: str,
        category: str | None = None,
    ) -> list[BenchmarkResult]:
        results = [r for r in self.results if r.method == method]
        if category is not None:
            results = [r for r in results if r.category == category]
        return results

    def _categorize_benchmark(self, source_file: Path) -> str:
        """Categorize a benchmark by its directory."""
        path = str(source_file).lower()
        if "svcomp" in path:
            return "svcomp"
        if "dafny" in path:
            return "dafny"
        if "challenges" in path:
            return "zero_human"
        return "other"

    def _parse_attempts(self, output: str) -> int:
        """Parse attempt count from command output."""
        matches = re.findall(r"(?:attempts?|total_attempts)[^\d]*(\d+)", output, re.I)
        return max([int(match) for match in matches], default=1)

    def _parse_tokens(self, output: str) -> int:
        """Parse token usage from command output."""
        matches = re.findall(r"(?:tokens?|llm_tokens_used)[^\d]*(\d+)", output, re.I)
        return sum(int(match) for match in matches)

    def _parse_solver_time(self, output: str) -> float:
        """Parse solver time from command output."""
        match = re.search(r"(?:solver_time_ms|solver time)[^\d]*(\d+(?:\.\d+)?)", output, re.I)
        if match is None:
            return 0.0
        return float(match.group(1))

    def _compute_significance(self, group1: list[float], group2: list[float]) -> float:
        """Compute an approximate two-tailed p-value for two timing samples."""
        if len(group1) < 2 or len(group2) < 2:
            return 1.0
        variance1 = self._sample_variance(group1)
        variance2 = self._sample_variance(group2)
        standard_error = math.sqrt((variance1 / len(group1)) + (variance2 / len(group2)))
        if standard_error == 0:
            return 1.0
        z_score = abs(self._average(group1) - self._average(group2)) / standard_error
        return math.erfc(z_score / math.sqrt(2))

    def _success_rate(self, results: list[BenchmarkResult]) -> float:
        if not results:
            return 0.0
        return sum(result.success for result in results) / len(results)

    def _average_code_quality(self, results: list[BenchmarkResult]) -> float:
        return self._average([r.code_length / max(1, r.attempts) for r in results])

    def _average(self, values: list[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _sample_variance(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        avg = self._average(values)
        return sum((value - avg) ** 2 for value in values) / (len(values) - 1)
