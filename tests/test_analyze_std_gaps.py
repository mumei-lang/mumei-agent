"""Tests for vStd roadmap gap analysis."""
from __future__ import annotations

import json
from pathlib import Path

from agent.analyze_std_gaps import (
    analyze_vstd_roadmap,
    classify_priority,
    task_filename_for_target,
)


def test_task_filename_for_nested_std_target() -> None:
    assert (
        task_filename_for_target("std/container/ring_buffer.mm")
        == "vstd_container_ring_buffer.json"
    )


def test_classify_priority_marks_missing_ready_task_high() -> None:
    rule = {"target": "std/core.mm", "depends_on": [], "difficulty": "low"}
    assert (
        classify_priority(rule, existing_paths=set(), forge_task_exists=False)
        == "high"
    )


def test_analyze_vstd_roadmap_reports_conversion_rate(tmp_path: Path) -> None:
    std = tmp_path / "std"
    std.mkdir()
    (std / "prelude.mm").write_text("atom ok() ensures: true; body: 1;\n")
    tasks = tmp_path / "forge_tasks"
    tasks.mkdir()
    (tasks / "vstd_core.json").write_text(json.dumps({"task_id": "vstd-core"}))

    report = analyze_vstd_roadmap(std_dir=std, forge_tasks_dir=tasks)

    assert report["metrics"]["roadmap_items"] > 0
    assert report["metrics"]["forge_task_specs"] >= 1
    assert 0.0 <= report["metrics"]["forge_task_conversion_rate"] <= 1.0
    assert any(item["name"] == "std/core.mm" for item in report["roadmap_items"])
    assert all("priority_band" in proposal for proposal in report["proposals"])
