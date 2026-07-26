"""Tests for the dogfood verdict time series and its spike/skew detection."""
from __future__ import annotations

import json
from pathlib import Path

from agent.dogfood_trend import (
    VerdictSnapshot,
    detect_refuted_spike,
    detect_unverifiable_skew,
    format_trend_markdown,
    load_history,
    save_history,
    snapshot_from_totals,
)


def _snapshot(
    index: int,
    *,
    refuted: int = 0,
    verified: int = 5,
    unverifiable_counts: dict[str, int] | None = None,
) -> VerdictSnapshot:
    counts = unverifiable_counts or {}
    return VerdictSnapshot(
        timestamp=f"2026-07-{index:02d}T00:00:00+00:00",
        run_id=str(index),
        total_files=refuted + verified + sum(counts.values()),
        refuted=refuted,
        verified=verified,
        unverifiable=sum(counts.values()),
        unverifiable_counts=counts,
    )


def test_snapshot_is_built_from_gate_totals() -> None:
    snapshot = snapshot_from_totals(
        {
            "total_files": 12,
            "human_review_count": 2,
            "verified_count": 7,
            "unverifiable_count": 3,
            "unverifiable_counts": {"timeout": 3},
        },
        run_id="42",
        timestamp="2026-07-26T00:00:00+00:00",
    )
    assert snapshot.refuted == 2
    assert snapshot.verified == 7
    assert snapshot.unverifiable_counts == {"timeout": 3}


def test_history_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    history = [_snapshot(1), _snapshot(2, refuted=1)]
    save_history(path, history)
    assert [snapshot.to_dict() for snapshot in load_history(path)] == [
        snapshot.to_dict() for snapshot in history
    ]


def test_history_limit_keeps_recent_snapshots(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    save_history(path, [_snapshot(i) for i in range(1, 11)], limit=3)
    assert [snapshot.run_id for snapshot in load_history(path)] == ["8", "9", "10"]


def test_corrupt_history_does_not_fail_the_gate(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_history(path) == []
    path.write_text(json.dumps([{"bogus": 1}, "nope"]), encoding="utf-8")
    assert load_history(path) == []
    assert load_history(tmp_path / "missing.json") == []


def test_refuted_spike_is_detected() -> None:
    history = [
        _snapshot(1, refuted=0),
        _snapshot(2, refuted=1),
        _snapshot(3, refuted=6),
    ]
    alerts = detect_refuted_spike(history)
    assert len(alerts) == 1
    assert "refuted spike: 6 file(s)" in alerts[0]


def test_steady_refuted_count_is_not_a_spike() -> None:
    history = [_snapshot(i, refuted=3) for i in range(1, 5)]
    assert detect_refuted_spike(history) == []


def test_single_new_refuted_file_is_not_a_spike() -> None:
    history = [_snapshot(1, refuted=0), _snapshot(2, refuted=1)]
    assert detect_refuted_spike(history) == []


def test_first_run_has_no_alerts() -> None:
    history = [_snapshot(1, refuted=9, unverifiable_counts={"timeout": 9})]
    assert detect_refuted_spike(history) == []
    assert detect_unverifiable_skew(history) == []


def test_unverifiable_skew_is_detected() -> None:
    history = [
        _snapshot(1, unverifiable_counts={"timeout": 1, "encoding_gap": 3}),
        _snapshot(2, unverifiable_counts={"timeout": 1, "encoding_gap": 3}),
        _snapshot(3, unverifiable_counts={"timeout": 7, "encoding_gap": 1}),
    ]
    alerts = detect_unverifiable_skew(history)
    assert len(alerts) == 1
    assert "`timeout` holds 88%" in alerts[0]


def test_stable_unverifiable_mix_is_not_skew() -> None:
    history = [
        _snapshot(i, unverifiable_counts={"timeout": 8, "encoding_gap": 1})
        for i in range(1, 4)
    ]
    assert detect_unverifiable_skew(history) == []


def test_trend_markdown_renders_series_causes_and_alerts() -> None:
    history = [
        _snapshot(1, refuted=0, unverifiable_counts={"timeout": 1}),
        _snapshot(2, refuted=5, unverifiable_counts={"timeout": 4}),
    ]
    markdown = format_trend_markdown(history, ["refuted spike: something"])
    assert "Dogfood verdict time series" in markdown
    assert "| 2026-07-02T00:00:00+00:00 (2) | 14 | 5 | 4 | 5 |" in markdown
    assert "| timeout | 4 | 100% |" in markdown
    assert "- refuted spike: something" in markdown


def test_trend_markdown_is_empty_without_history() -> None:
    assert format_trend_markdown([], []) == ""
