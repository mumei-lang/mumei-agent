"""Tests for vStd Phase 4 forge checkpoint validation."""
from __future__ import annotations

import json
from pathlib import Path

from agent.vstd_phase4 import (
    PHASE4_EXPECTED_TASKS,
    phase4_forge_log_is_clean,
    validate_phase4_forge_log,
)


def test_repository_forge_log_covers_phase4_checkpoint() -> None:
    forge_log = Path(__file__).resolve().parents[1] / "forge_log.json"

    statuses = validate_phase4_forge_log(forge_log)

    assert {status.task_id for status in statuses} == set(PHASE4_EXPECTED_TASKS)
    assert all(status.ok for status in statuses)
    assert phase4_forge_log_is_clean(forge_log)


def test_validate_phase4_forge_log_reports_missing_task(tmp_path: Path) -> None:
    forge_log = tmp_path / "forge_log.json"
    forge_log.write_text(json.dumps({"runs": []}), encoding="utf-8")

    statuses = validate_phase4_forge_log(forge_log)

    assert not all(status.ok for status in statuses)
    assert any("missing forge_log entry" in status.problems for status in statuses)


def test_validate_phase4_forge_log_reports_atom_mismatch(tmp_path: Path) -> None:
    task_id = "vstd-math-factorial"
    expected = PHASE4_EXPECTED_TASKS[task_id]
    forge_log = tmp_path / "forge_log.json"
    forge_log.write_text(
        json.dumps({
            "runs": [
                {
                    "task_id": task_id,
                    "status": "success",
                    "target_file": expected["target_file"],
                    "atoms_added": ["factorial_step"],
                    "error": None,
                }
            ]
        }),
        encoding="utf-8",
    )

    status = validate_phase4_forge_log(
        forge_log,
        expected_tasks={task_id: expected},
    )[0]

    assert not status.ok
    assert any("atoms_added" in problem for problem in status.problems)
