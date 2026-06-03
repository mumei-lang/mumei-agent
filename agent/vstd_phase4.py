"""Validation helpers for the vStd Phase 4 forge checkpoint."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PHASE4_EXPECTED_TASKS: dict[str, dict[str, Any]] = {
    "vstd-aviation-control": {
        "target_file": "std/concurrency/aviation.mm",
        "atoms_added": ["allocate_runway"],
    },
    "vstd-container-sorted-map": {
        "target_file": "std/container/sorted_map.mm",
        "atoms_added": [
            "sorted_map_insert_position",
            "sorted_map_insert_len",
            "sorted_map_key_ordered",
        ],
    },
    "vstd-math-factorial": {
        "target_file": "std/math/factorial.mm",
        "atoms_added": ["factorial_step", "factorial_in_range"],
    },
    "vstd-math-fibonacci": {
        "target_file": "std/math/fibonacci.mm",
        "atoms_added": ["fib_step_next", "fib_remaining_decreases"],
    },
    "vstd-string-validator": {
        "target_file": "std/string/validator.mm",
        "atoms_added": ["is_numeric_ascii_code", "is_alphanumeric_ascii_code"],
    },
}


@dataclass(frozen=True)
class Phase4TaskStatus:
    task_id: str
    ok: bool
    status: str | None
    target_file: str | None
    atoms_added: tuple[str, ...]
    problems: tuple[str, ...]
    note: str | None = None


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def validate_phase4_forge_log(
    forge_log_path: Path,
    expected_tasks: dict[str, dict[str, Any]] | None = None,
) -> list[Phase4TaskStatus]:
    """Validate that every Phase 4 forge-log entry succeeded as expected."""
    expected = expected_tasks or PHASE4_EXPECTED_TASKS
    data = json.loads(forge_log_path.read_text(encoding="utf-8"))
    runs = data.get("runs", []) if isinstance(data, dict) else []
    by_id = {
        run.get("task_id"): run
        for run in runs
        if isinstance(run, dict) and isinstance(run.get("task_id"), str)
    }

    results: list[Phase4TaskStatus] = []
    for task_id, spec in expected.items():
        run = by_id.get(task_id)
        if run is None:
            results.append(
                Phase4TaskStatus(
                    task_id=task_id,
                    ok=False,
                    status=None,
                    target_file=None,
                    atoms_added=(),
                    problems=("missing forge_log entry",),
                )
            )
            continue

        problems: list[str] = []
        atoms = _as_str_tuple(run.get("atoms_added"))
        expected_atoms = tuple(spec["atoms_added"])
        if run.get("status") != "success":
            problems.append(f"status is {run.get('status')!r}, expected 'success'")
        if run.get("error") is not None:
            problems.append(f"error is {run.get('error')!r}, expected null")
        if run.get("target_file") != spec["target_file"]:
            problems.append(
                f"target_file is {run.get('target_file')!r}, "
                f"expected {spec['target_file']!r}"
            )
        if atoms != expected_atoms:
            problems.append(f"atoms_added is {atoms!r}, expected {expected_atoms!r}")

        results.append(
            Phase4TaskStatus(
                task_id=task_id,
                ok=not problems,
                status=run.get("status"),
                target_file=run.get("target_file"),
                atoms_added=atoms,
                problems=tuple(problems),
                note=run.get("note") if isinstance(run.get("note"), str) else None,
            )
        )
    return results


def phase4_forge_log_is_clean(forge_log_path: Path) -> bool:
    """Return True when all Phase 4 forge-log entries match the checkpoint."""
    return all(status.ok for status in validate_phase4_forge_log(forge_log_path))
