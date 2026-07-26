"""Tests for agent/benchmark_feedback.py (P16 benchmark -> forge/proliferate)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.benchmark_feedback import (
    SCHEMA,
    BenchmarkFeedback,
    load_benchmark_feedback,
)


def _payload() -> dict:
    return {
        "schema": SCHEMA,
        "timestamp": "2026-07-26 13:00 UTC",
        "stdlib_trusted_ratio": 0.12,
        "categories": [
            {
                "category": "arithmetic",
                "success_rate": 0.5,
                "counterexample_catch_rate": 1.0,
                "trusted_ratio": 0.0,
                "weakness_score": 0.25,
                "signals": ["expected_outcome_mismatch"],
                "std_domains": ["std/math"],
                "priority_delta": -13,
            }
        ],
        "weak_categories": ["arithmetic"],
        "domain_bias": [
            {
                "domain": "std/math",
                "priority_delta": -13,
                "weakness_score": 0.25,
                "driving_category": "arithmetic",
            },
            {
                "domain": "std/concurrency",
                "priority_delta": -5,
                "weakness_score": 0.1,
                "driving_category": "concurrency",
            },
        ],
    }


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "forge-feedback.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_and_summary(tmp_path: Path):
    feedback = BenchmarkFeedback.load(_write(tmp_path, _payload()))
    assert feedback.weak_categories == ("arithmetic",)
    summary = feedback.summary()
    assert summary["schema"] == SCHEMA
    assert summary["weak_categories"] == ["arithmetic"]
    assert summary["domain_bias"][0]["domain"] == "std/math"


def test_unsupported_schema_is_rejected(tmp_path: Path):
    payload = _payload()
    payload["schema"] = "mumei.benchmark_forge_feedback/v99"
    with pytest.raises(ValueError):
        BenchmarkFeedback.load(_write(tmp_path, payload))


def test_load_benchmark_feedback_degrades_to_none(tmp_path: Path):
    assert load_benchmark_feedback(None) is None
    assert load_benchmark_feedback(tmp_path / "missing.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_benchmark_feedback(broken) is None


def test_bias_for_matches_longest_domain_prefix(tmp_path: Path):
    payload = _payload()
    payload["domain_bias"].append({
        "domain": "std/math/abs.mm",
        "priority_delta": -40,
        "weakness_score": 0.8,
        "driving_category": "arithmetic",
    })
    feedback = BenchmarkFeedback.load(_write(tmp_path, payload))
    assert feedback.bias_for("std/math/abs.mm").priority_delta == -40
    assert feedback.bias_for("std/math/patterns.mm").priority_delta == -13
    assert feedback.bias_for("std/concurrency.mm").priority_delta == -5
    assert feedback.bias_for("std/json.mm") is None


def test_rank_proposals_pulls_weak_domains_forward_and_renumbers(tmp_path: Path):
    feedback = BenchmarkFeedback.load(_write(tmp_path, _payload()))
    proposals = [
        {"name": "std/json.mm", "priority": 1},
        {"name": "std/concurrency/queue.mm", "priority": 2},
        {"name": "std/math/patterns.mm", "priority": 3},
    ]
    ranked = feedback.rank_proposals(proposals)

    assert [p["name"] for p in ranked] == [
        "std/math/patterns.mm",
        "std/concurrency/queue.mm",
        "std/json.mm",
    ]
    assert [p["priority"] for p in ranked] == [1, 2, 3]
    assert ranked[0]["benchmark_feedback"]["driving_category"] == "arithmetic"
    # Unbiased proposals carry no provenance and are never dropped.
    assert "benchmark_feedback" not in ranked[-1]
    assert len(ranked) == len(proposals)


def test_rank_proposals_keeps_gap_order_for_equal_bias(tmp_path: Path):
    feedback = BenchmarkFeedback.load(_write(tmp_path, _payload()))
    proposals = [
        {"name": "std/math/a.mm", "priority": 1},
        {"name": "std/math/b.mm", "priority": 2},
    ]
    ranked = feedback.rank_proposals(proposals)
    assert [p["name"] for p in ranked] == ["std/math/a.mm", "std/math/b.mm"]


def test_apply_to_specs_biases_priority_and_reorders(tmp_path: Path):
    feedback = BenchmarkFeedback.load(_write(tmp_path, _payload()))
    specs = [
        {"target_file": "std/json.mm", "priority": 1},
        {"target_file": "std/math/patterns.mm", "priority": 2},
    ]
    ordered = feedback.apply_to_specs(specs)
    assert [s["target_file"] for s in ordered] == [
        "std/math/patterns.mm",
        "std/json.mm",
    ]
    assert ordered[0]["priority"] == 2 - 13
    assert ordered[1]["priority"] == 1
    assert ordered[0]["benchmark_feedback"]["domain"] == "std/math"
