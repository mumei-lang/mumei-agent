#!/usr/bin/env python3
"""Run all benchmarks and generate comparison report."""
from __future__ import annotations

import argparse
from pathlib import Path

from benchmarks.evaluator import BenchmarkEvaluator


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_mumei_repo(agent_root: Path) -> Path:
    return agent_root.parent / "mumei"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mumei benchmarks")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("benchmark_results"),
        help="Directory to store benchmark results",
    )
    parser.add_argument(
        "--category",
        choices=["svcomp", "dafny", "zero_human", "all"],
        default="all",
        help="Benchmark category to run",
    )
    parser.add_argument(
        "--mumei-repo",
        type=Path,
        default=None,
        help="Path to the mumei compiler repository",
    )
    parser.add_argument(
        "--method",
        choices=["agent", "baseline"],
        default="agent",
        help="Verification method to run",
    )
    args = parser.parse_args()

    agent_root = _repo_root()
    mumei_repo = args.mumei_repo or _default_mumei_repo(agent_root)
    evaluator = BenchmarkEvaluator(args.results_dir)

    if args.category in ("svcomp", "all"):
        for file in sorted((mumei_repo / "benchmarks" / "svcomp_style").glob("*.mm")):
            evaluator.results.append(evaluator.run_benchmark(file, method=args.method))

    if args.category in ("dafny", "all"):
        for file in sorted((mumei_repo / "benchmarks" / "dafny_puzzles").glob("*.mm")):
            evaluator.results.append(evaluator.run_benchmark(file, method=args.method))

    if args.category in ("zero_human", "all"):
        for file in sorted((agent_root / "examples" / "challenges").glob("*_spec.json")):
            evaluator.results.append(evaluator.run_benchmark(file, method=args.method))

    report_path = args.results_dir / "report.json"
    evaluator.generate_report(report_path)
    print(f"Benchmark report saved to {report_path}")


if __name__ == "__main__":
    main()
