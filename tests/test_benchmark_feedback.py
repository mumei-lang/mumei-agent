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
from agent.proliferate_cache import _spec_cache_key
from agent.propose_helpers import build_spec_from_proposal


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
    # Valid JSON that is not an object must degrade too, not raise.
    for text in ("[]", '"nope"', "7", "null"):
        non_object = tmp_path / "non-object.json"
        non_object.write_text(text, encoding="utf-8")
        assert load_benchmark_feedback(non_object) is None


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


def _generated_entry() -> dict:
    return {
        "name": "std/math/benchmark_gaps.mm",
        "reason": "Benchmark category arithmetic is weak",
        "depends_on": ["std/prelude.mm"],
        "difficulty": "medium",
        "atoms": [
            {
                "name": "math_counterexample_guard",
                "description": "Reject the missed counterexample input",
                "inputs": [{"name": "value", "type": "i64"}],
                "return_type": "i64",
                "requires": "true",
                "ensures": "result == 0 || result == 1",
            }
        ],
        "source": "benchmark_forge_feedback",
        "driving_category": "arithmetic",
        "domain": "std/math",
        "weakness_score": 0.25,
        "priority_delta": -13,
        "signals": ["counterexample_missed"],
    }


def test_generated_proposals_are_optional(tmp_path: Path):
    """Documents predating proposal generation stay bias-only."""
    feedback = BenchmarkFeedback.load(_write(tmp_path, _payload()))
    assert feedback.generated_proposals == ()
    proposals = [{"name": "std/json.mm", "priority": 1}]
    assert feedback.merge_generated_proposals(proposals) == proposals
    assert feedback.summary()["generated_proposals"] == []


def test_generated_proposals_add_forge_work_for_weak_categories(tmp_path: Path):
    payload = _payload()
    payload["generated_proposals"] = [_generated_entry()]
    feedback = BenchmarkFeedback.load(_write(tmp_path, payload))

    merged = feedback.merge_generated_proposals([{"name": "std/json.mm", "priority": 1}])
    assert [p["name"] for p in merged] == [
        "std/json.mm",
        "std/math/benchmark_gaps.mm",
    ]
    generated = merged[-1]
    assert generated["source"] == "benchmark_forge_feedback"
    assert generated["benchmark_generated"]["driving_category"] == "arithmetic"
    assert [a["name"] for a in generated["atoms"]] == ["math_counterexample_guard"]
    # The generated proposal is a real forge task, biased like any other.
    ranked = feedback.rank_proposals(merged)
    assert ranked[0]["name"] == "std/math/benchmark_gaps.mm"
    spec = build_spec_from_proposal(ranked[0], priority=1)
    assert spec["target_file"] == "std/math/benchmark_gaps.mm"
    assert spec["source"] == "benchmark_forge_feedback"
    assert spec["atoms"][0]["name"] == "math_counterexample_guard"
    assert spec["benchmark_generated"]["domain"] == "std/math"


def test_generated_proposals_never_duplicate_gap_analysis(tmp_path: Path):
    payload = _payload()
    payload["generated_proposals"] = [_generated_entry()]
    feedback = BenchmarkFeedback.load(_write(tmp_path, payload))

    existing = [{"name": "std/math/benchmark_gaps.mm", "priority": 1}]
    assert feedback.merge_generated_proposals(existing) == existing


def test_unusable_generated_proposals_are_skipped(tmp_path: Path):
    payload = _payload()
    valid = _generated_entry()
    payload["generated_proposals"] = [
        "not-an-object",
        {"reason": "missing name"},
        {"name": "std/math/no_atoms.mm", "atoms": []},
        valid,
    ]
    feedback = BenchmarkFeedback.load(_write(tmp_path, payload))
    assert [p.name for p in feedback.generated_proposals] == [valid["name"]]


def test_generated_provenance_does_not_invalidate_the_forge_result_cache(
    tmp_path: Path,
):
    spec = {"target_file": "std/math/benchmark_gaps.mm", "atoms": ["a"]}
    before = _spec_cache_key(spec, tmp_path)
    spec["benchmark_generated"] = {"driving_category": "arithmetic"}
    assert _spec_cache_key(spec, tmp_path) == before


def test_bias_does_not_invalidate_the_forge_result_cache(tmp_path: Path):
    """Ordering-only metadata must not change the spec cache key."""
    feedback = BenchmarkFeedback.load(_write(tmp_path, _payload()))
    spec = {"target_file": "std/math/patterns.mm", "priority": 2, "atoms": ["a"]}
    before = _spec_cache_key(spec, tmp_path)

    [biased] = feedback.apply_to_specs([spec])

    assert biased["priority"] != 2
    assert "benchmark_feedback" in biased
    assert _spec_cache_key(biased, tmp_path) == before
