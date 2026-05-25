from pathlib import Path

from benchmarks.evaluator import BenchmarkEvaluator, BenchmarkResult


def test_benchmark_result_creation() -> None:
    result = BenchmarkResult(
        name="test",
        category="svcomp",
        success=True,
        attempts=1,
        verification_time_ms=100.0,
        code_length=100,
        solver_time_ms=50.0,
        tokens_used=0,
        method="agent",
    )

    assert result.name == "test"
    assert result.success is True


def test_categorize_benchmark() -> None:
    evaluator = BenchmarkEvaluator(Path("test_results"))

    assert evaluator._categorize_benchmark(Path("svcomp/test.mm")) == "svcomp"
    assert evaluator._categorize_benchmark(Path("dafny/test.mm")) == "dafny"
    assert evaluator._categorize_benchmark(Path("examples/challenges/test.json")) == "zero_human"


def test_compare_methods_handles_empty_results() -> None:
    comparison = BenchmarkEvaluator(Path("test_results")).compare_methods()

    assert comparison.success_rate_human == 0.0
    assert comparison.success_rate_agent == 0.0
    assert comparison.statistical_significance == 1.0


def test_generate_report_writes_json(tmp_path: Path) -> None:
    evaluator = BenchmarkEvaluator(tmp_path)
    evaluator.results.append(
        BenchmarkResult(
            name="test",
            category="dafny",
            success=True,
            attempts=1,
            verification_time_ms=10.0,
            code_length=50,
            solver_time_ms=1.0,
            tokens_used=2,
            method="agent",
        )
    )

    report = tmp_path / "report.json"
    evaluator.generate_report(report)

    text = report.read_text(encoding="utf-8")
    assert '"total_benchmarks": 1' in text
    assert '"dafny"' in text
