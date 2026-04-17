"""Forge task discovery and filtering.

Reads task specification JSON files from a directory and filters out
tasks that have already been completed (based on the forge log).

This module is intentionally free of side effects beyond filesystem reads
so it can be unit-tested without mocks.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# TODO marker pattern used by scan_std_todos — matches lines like
# `// TODO: forge atom foo` in .mm source files.
_TODO_PATTERN = re.compile(r"//\s*TODO:?\s*forge\s+atom\s+(\w+)(?::\s*(.*))?", re.IGNORECASE)


def _load_task(path: Path) -> dict[str, Any] | None:
    """Load a single task spec from *path*.

    Returns the parsed dict (augmented with ``_spec_path`` for traceability),
    or ``None`` if the file cannot be parsed or lacks a ``task_id``.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _logger.warning("Skipping %s: %s", path, exc)
        return None

    if not isinstance(data, dict):
        _logger.warning("Skipping %s: spec root must be an object", path)
        return None

    if "task_id" not in data or not isinstance(data["task_id"], str):
        _logger.warning("Skipping %s: missing or invalid task_id", path)
        return None

    if "target_file" not in data or not isinstance(data["target_file"], str):
        _logger.warning("Skipping %s: missing or invalid target_file", path)
        return None

    data.setdefault("mode", "append")
    data.setdefault("priority", 100)
    data.setdefault("max_retries", 5)
    data.setdefault("auto_commit", False)
    data["_spec_path"] = str(path)
    return data


def discover_tasks(forge_tasks_dir: Path) -> list[dict[str, Any]]:
    """Discover all forge task specs in *forge_tasks_dir*.

    Reads every ``*.json`` file in the directory, parses it as a task
    spec, and returns the list sorted by ``priority`` (ascending — lower
    priority values run first) then by ``task_id`` for stable ordering.

    Malformed files are skipped with a warning.
    """
    if not forge_tasks_dir.exists() or not forge_tasks_dir.is_dir():
        _logger.warning("Forge tasks directory %s does not exist", forge_tasks_dir)
        return []

    tasks: list[dict[str, Any]] = []
    for path in sorted(forge_tasks_dir.glob("*.json")):
        task = _load_task(path)
        if task is not None:
            tasks.append(task)

    tasks.sort(key=lambda t: (t.get("priority", 100), t.get("task_id", "")))
    return tasks


def scan_std_todos(std_dir: Path) -> list[dict[str, Any]]:
    """Scan the standard library for ``// TODO: forge atom <name>`` markers.

    Returns a list of task spec stubs (one per marker).  The output format
    matches the regular spec schema but uses ``mode: "append"`` and a
    lower default priority so that explicit specs run first.

    This is an initial stub — future versions may parse adjacent
    ``requires`` / ``ensures`` comment blocks to build richer specs.
    """
    if not std_dir.exists() or not std_dir.is_dir():
        return []

    tasks: list[dict[str, Any]] = []
    for mm_path in sorted(std_dir.rglob("*.mm")):
        try:
            content = mm_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _TODO_PATTERN.finditer(content):
            atom_name = match.group(1)
            description = (match.group(2) or "").strip() or f"Auto-forge atom {atom_name}"
            rel = mm_path.relative_to(std_dir.parent) if std_dir.parent in mm_path.parents else mm_path
            tasks.append({
                "task_id": f"vstd-auto-{atom_name}",
                "target_file": str(rel).replace("\\", "/"),
                "mode": "append",
                "priority": 500,
                "description": description,
                "atoms": [{"name": atom_name, "description": description}],
                "max_retries": 5,
                "auto_commit": False,
                "_auto_discovered": True,
            })
    return tasks


def _load_completed_ids(log_path: Path) -> set[str]:
    """Return the set of ``task_id``s that have a ``success`` run logged."""
    if not log_path.exists():
        return set()
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _logger.warning("Cannot read forge log %s: %s", log_path, exc)
        return set()

    runs = data.get("runs", []) if isinstance(data, dict) else []
    completed: set[str] = set()
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("status") == "success" and isinstance(run.get("task_id"), str):
            completed.add(run["task_id"])
    return completed


def filter_completed_tasks(
    tasks: list[dict[str, Any]],
    completed_log_path: Path,
) -> list[dict[str, Any]]:
    """Remove tasks whose ``task_id`` already has a successful log entry."""
    completed = _load_completed_ids(completed_log_path)
    if not completed:
        return list(tasks)
    return [t for t in tasks if t.get("task_id") not in completed]
