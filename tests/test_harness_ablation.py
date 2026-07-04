"""Tests for harness ablation comparison (agent/harness_ablation.py)."""
from __future__ import annotations

import json

import pytest

from agent.harness_ablation import (
    compare_ablation_runs,
    extract_harness_aggregate,
    format_ablation_report_markdown,
    load_run_aggregate,
)
from agent.harness_metrics import HarnessMetrics


def _run_aggregate(profile: str, *, successes: int, failures: int, tokens: int) -> dict:
    metrics = HarnessMetrics.from_profile(profile)
    for i in range(successes):
        metrics.record_result(
            f"stage_{i}",
            True,
            attempts=1,
            tokens_to_success=tokens,
            solver_seconds_to_success=0.5,
        )
    for i in range(failures):
        metrics.record_result(
            f"stage_fail_{i}",
            False,
            attempts=3,
            tokens_to_success=tokens * 2,
            solver_seconds_to_success=2.0,
        )
    return metrics.aggregate_metrics()


class TestExtractAndLoad:
    def test_extracts_nested_harness_metrics(self) -> None:
        aggregate = _run_aggregate("full", successes=1, failures=0, tokens=10)
        payload = {"proposals_processed": 1, "harness_metrics": aggregate}
        assert extract_harness_aggregate(payload)["profile"] == "full"

    def test_accepts_bare_aggregate(self) -> None:
        aggregate = _run_aggregate("basic", successes=1, failures=0, tokens=10)
        assert extract_harness_aggregate(aggregate)["profile"] == "basic"

    def test_rejects_payload_without_metrics(self) -> None:
        with pytest.raises(ValueError, match="harness metrics"):
            extract_harness_aggregate({"foo": "bar"})

    def test_load_run_aggregate_from_file(self, tmp_path) -> None:
        aggregate = _run_aggregate("verifier", successes=2, failures=1, tokens=5)
        path = tmp_path / "summary.json"
        path.write_text(
            json.dumps({"harness_metrics": aggregate}),
            encoding="utf-8",
        )
        assert load_run_aggregate(path)["profile"] == "verifier"


class TestCompareAblationRuns:
    def test_detects_ablated_modules_and_deltas(self) -> None:
        full = _run_aggregate("full", successes=8, failures=2, tokens=100)
        basic = _run_aggregate("basic", successes=4, failures=6, tokens=50)

        report = compare_ablation_runs({"full": full, "basic": basic}, "full")

        assert report["baseline"]["label"] == "full"
        assert report["baseline"]["profile"] == "full"
        run = report["runs"]["basic"]
        # basic disables everything except artifact_contract + retry_classifier.
        assert "verification_gate" in run["ablated_modules"]
        assert "lean_fallback" in run["ablated_modules"]
        assert "artifact_contract" not in run["ablated_modules"]
        assert run["added_modules"] == []
        # basic has a lower success rate than full → negative delta.
        assert run["overall_delta"]["success_rate"] < 0
        assert run["overall"]["success_rate"] == pytest.approx(0.4)
        # Costs are deduplicated per stage, not triple-counted across the
        # module records that record_result fans out to.
        assert run["overall"]["tokens_to_success"] == pytest.approx(4 * 50 + 6 * 100)
        # Per-module deltas mirror the drop for exercised modules.
        assert run["per_module"]["verification_gate"]["success_rate_delta"] < 0
        assert run["per_module"]["verification_gate"]["baseline_enabled"] is True
        assert run["per_module"]["verification_gate"]["module_enabled"] is False

    def test_added_modules_relative_to_smaller_baseline(self) -> None:
        basic = _run_aggregate("basic", successes=1, failures=0, tokens=10)
        verifier = _run_aggregate("verifier", successes=1, failures=0, tokens=10)

        report = compare_ablation_runs({"basic": basic, "verifier": verifier}, "basic")
        run = report["runs"]["verifier"]
        assert "verification_gate" in run["added_modules"]
        assert run["ablated_modules"] == []

    def test_unknown_baseline_raises(self) -> None:
        full = _run_aggregate("full", successes=1, failures=0, tokens=1)
        with pytest.raises(ValueError, match="baseline run 'missing' not found"):
            compare_ablation_runs({"full": full}, "missing")


class TestMarkdownReport:
    def test_renders_table_with_deltas(self) -> None:
        full = _run_aggregate("full", successes=8, failures=2, tokens=100)
        basic = _run_aggregate("basic", successes=4, failures=6, tokens=50)
        report = compare_ablation_runs({"full": full, "basic": basic}, "full")

        rendered = format_ablation_report_markdown(report)

        assert "# Harness Ablation Report" in rendered
        assert "Baseline: `full`" in rendered
        assert "| basic |" in rendered
        assert "verification_gate" in rendered


class TestCli:
    def test_cli_writes_markdown_report(self, tmp_path, capsys) -> None:
        import argparse

        from agent.harness_ablation import build_parser, main

        full = tmp_path / "full.json"
        basic = tmp_path / "basic.json"
        full.write_text(
            json.dumps(
                {"harness_metrics": _run_aggregate("full", successes=3, failures=1, tokens=10)}
            ),
            encoding="utf-8",
        )
        basic.write_text(
            json.dumps(
                {"harness_metrics": _run_aggregate("basic", successes=1, failures=3, tokens=5)}
            ),
            encoding="utf-8",
        )
        out = tmp_path / "report.md"

        parser = build_parser(argparse.ArgumentParser())
        args = parser.parse_args(
            [
                f"full={full}",
                f"basic={basic}",
                "--baseline",
                "full",
                "--format",
                "markdown",
                "--output",
                str(out),
            ]
        )
        main(args)

        rendered = out.read_text(encoding="utf-8")
        assert "# Harness Ablation Report" in rendered
        assert "| basic |" in rendered

    def test_cli_rejects_bad_run_spec(self) -> None:
        import argparse

        from agent.harness_ablation import build_parser, main

        parser = build_parser(argparse.ArgumentParser())
        args = parser.parse_args(["nolabel.json", "--baseline", "full"])
        with pytest.raises(SystemExit, match="invalid run spec"):
            main(args)
