"""Tests for NLAH harness profile metrics."""
from __future__ import annotations

import argparse
import json

from agent import forge, proliferate
from agent.budget_metrics import aggregate_metrics
from agent.harness_metrics import HarnessMetrics, module_flags_for_profile
from agent.strategies.retry_history import RetryAttempt, RetryHistory


def test_module_flags_keep_heavy_search_off_by_default() -> None:
    basic = module_flags_for_profile("basic")
    full = module_flags_for_profile("full")

    assert basic["artifact_contract"] is True
    assert basic["multi_candidate_search"] is False
    assert full["multi_candidate_search"] is True
    assert full["lean_fallback"] is True


def test_harness_metrics_aggregate_summary_json() -> None:
    metrics = HarnessMetrics.from_profile("verifier")
    metrics.record_stage(
        "forge",
        module="verification_gate",
        verification_gate=True,
        handoff_count=2,
        retry_class="llm_fix",
        intent_fidelity_status="passed",
        tokens_to_success=300,
        solver_seconds_to_success=1.25,
        spec_drift_score=0.2,
    )
    metrics.record_stage(
        "forge",
        module="artifact_contract",
        artifact_contract_passed=False,
        retry_class="llm_fix",
        intent_fidelity_status="failed",
        tokens_to_success=100,
        solver_seconds_to_success=0.5,
        spec_drift_score=0.4,
    )

    payload = json.loads(metrics.aggregate_metrics_json())

    assert payload["profile"] == "verifier"
    assert payload["module_enabled"]["verification_gate"] is True
    assert payload["by_stage"]["forge"]["tokens_to_success"] == 400
    assert payload["by_stage"]["forge"]["handoff_count"] == 2
    assert payload["by_module"]["verification_gate"]["verification_gate_success_rate"] == 1.0
    assert payload["by_module"]["artifact_contract"]["artifact_contract_success_rate"] == 0.0
    assert payload["retry_class"] == {"llm_fix": 2}
    assert payload["intent_fidelity_status"] == {"passed": 1, "failed": 1}


def test_budget_summary_includes_harness_metrics() -> None:
    history = RetryHistory()
    history.add(
        RetryAttempt(
            attempt_number=1,
            source_code="before",
            error_log="error",
            report_data={},
            diagnosis={},
            tokens_used=25,
            solver_time_seconds=0.75,
            spec_drift_score=0.3,
        )
    )
    harness = HarnessMetrics.from_profile("stateful")
    harness.record_result("heal", True, attempts=1)

    summary = aggregate_metrics(history, harness).aggregate_summary()

    assert summary["tokens_to_success"] == 25
    assert summary["solver_seconds_to_success"] == 0.75
    assert summary["spec_drift_score"] == 0.3
    assert summary["harness_metrics"]["profile"] == "stateful"
    assert summary["harness_metrics"]["module_enabled"]["stateful_handoff"] is True


def test_harness_profile_parser_choices_for_forge_and_proliferate() -> None:
    forge_parser = argparse.ArgumentParser()
    forge.build_parser(forge_parser)
    forge_args = forge_parser.parse_args(["--dry-run", "--harness-profile", "full"])

    proliferate_parser = argparse.ArgumentParser()
    proliferate.build_parser(proliferate_parser)
    proliferate_args = proliferate_parser.parse_args(
        ["--mumei-repo", "/tmp/mumei", "--harness-profile", "lean_fallback"]
    )

    assert forge_args.harness_profile == "full"
    assert proliferate_args.harness_profile == "lean_fallback"


def test_apply_profile_to_spec_surfaces_runtime_module_controls() -> None:
    metrics = HarnessMetrics.from_profile("self_evolution")

    spec = metrics.apply_to_spec({"task_id": "nl-ablation"})

    assert spec["harness_profile"] == "self_evolution"
    assert spec["harness_modules"]["multi_candidate_search"] is True
    assert spec["enable_multi_candidate_search"] is True
