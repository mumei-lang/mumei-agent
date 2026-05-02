"""Unit tests for agent.forge_discovery."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.forge_discovery import (
    _load_task,
    discover_tasks,
    filter_completed_tasks,
    scan_std_todos,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FORGE_TASKS_DIR = REPO_ROOT / "forge_tasks"


def _write_spec(dir_: Path, name: str, spec: dict) -> Path:
    p = dir_ / name
    p.write_text(json.dumps(spec), encoding="utf-8")
    return p


class TestDiscoverTasks:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert discover_tasks(tmp_path) == []

    def test_missing_dir_returns_empty(self, tmp_path):
        assert discover_tasks(tmp_path / "does_not_exist") == []

    def test_loads_and_defaults(self, tmp_path):
        _write_spec(tmp_path, "a.json", {
            "task_id": "t1", "target_file": "std/a.mm", "atoms": [{"name": "a"}],
        })
        tasks = discover_tasks(tmp_path)
        assert len(tasks) == 1
        t = tasks[0]
        assert t["task_id"] == "t1"
        assert t["mode"] == "append"       # default
        assert t["priority"] == 100        # default
        assert t["max_retries"] == 5       # default
        assert t["auto_commit"] is False   # default
        assert t["_spec_path"].endswith("a.json")

    def test_sorts_by_priority_then_id(self, tmp_path):
        _write_spec(tmp_path, "b.json", {
            "task_id": "zzz", "target_file": "x", "priority": 1, "atoms": [{"name": "a"}],
        })
        _write_spec(tmp_path, "a.json", {
            "task_id": "aaa", "target_file": "x", "priority": 5, "atoms": [{"name": "a"}],
        })
        _write_spec(tmp_path, "c.json", {
            "task_id": "mmm", "target_file": "x", "priority": 1, "atoms": [{"name": "a"}],
        })
        ids = [t["task_id"] for t in discover_tasks(tmp_path)]
        # priority 1 group (mmm, zzz sorted lexicographically) then priority 5
        assert ids == ["mmm", "zzz", "aaa"]

    def test_skips_malformed_json(self, tmp_path):
        (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
        _write_spec(tmp_path, "ok.json", {
            "task_id": "ok", "target_file": "x", "atoms": [{"name": "a"}],
        })
        tasks = discover_tasks(tmp_path)
        assert [t["task_id"] for t in tasks] == ["ok"]

    def test_skips_missing_task_id(self, tmp_path):
        _write_spec(tmp_path, "no_id.json", {
            "target_file": "std/a.mm", "atoms": [{"name": "a"}],
        })
        assert discover_tasks(tmp_path) == []

    def test_skips_missing_target_file(self, tmp_path):
        _write_spec(tmp_path, "no_target.json", {
            "task_id": "t", "atoms": [{"name": "a"}],
        })
        assert discover_tasks(tmp_path) == []

    def test_ignores_non_json(self, tmp_path):
        (tmp_path / "README.md").write_text("hi", encoding="utf-8")
        _write_spec(tmp_path, "ok.json", {
            "task_id": "ok", "target_file": "x", "atoms": [{"name": "a"}],
        })
        tasks = discover_tasks(tmp_path)
        assert [t["task_id"] for t in tasks] == ["ok"]


class TestFilterCompletedTasks:
    def test_no_log_passthrough(self, tmp_path):
        tasks = [{"task_id": "t1"}, {"task_id": "t2"}]
        out = filter_completed_tasks(tasks, tmp_path / "nope.json")
        assert out == tasks

    def test_filters_success_only(self, tmp_path):
        log = tmp_path / "forge_log.json"
        log.write_text(json.dumps({"runs": [
            {"task_id": "t1", "status": "success"},
            {"task_id": "t2", "status": "failed"},
            {"task_id": "t3", "status": "success"},
        ]}), encoding="utf-8")
        tasks = [{"task_id": "t1"}, {"task_id": "t2"}, {"task_id": "t3"}, {"task_id": "t4"}]
        out = filter_completed_tasks(tasks, log)
        assert [t["task_id"] for t in out] == ["t2", "t4"]

    def test_corrupt_log_passthrough(self, tmp_path):
        log = tmp_path / "forge_log.json"
        log.write_text("not json", encoding="utf-8")
        tasks = [{"task_id": "t1"}, {"task_id": "t2"}]
        out = filter_completed_tasks(tasks, log)
        assert out == tasks

    def test_non_dict_runs_passthrough(self, tmp_path):
        log = tmp_path / "forge_log.json"
        log.write_text(json.dumps({"runs": ["string-entry", 42]}), encoding="utf-8")
        tasks = [{"task_id": "t1"}]
        assert filter_completed_tasks(tasks, log) == tasks


class TestScanStdTodos:
    def test_missing_dir(self, tmp_path):
        assert scan_std_todos(tmp_path / "nope") == []

    def test_finds_todo_markers(self, tmp_path):
        std = tmp_path / "std"
        std.mkdir()
        (std / "a.mm").write_text(
            "// regular comment\n"
            "// TODO: forge atom clamp_pct: Clamp to [0, 100]\n"
            "atom foo() requires: true; ensures: true; body: 1;\n"
            "// TODO: forge atom bar\n",
            encoding="utf-8",
        )
        tasks = scan_std_todos(std)
        assert len(tasks) == 2
        ids = {t["task_id"] for t in tasks}
        assert "vstd-auto-clamp_pct" in ids
        assert "vstd-auto-bar" in ids
        for t in tasks:
            assert t["_auto_discovered"] is True
            assert t["mode"] == "append"

    def test_ignores_unrelated_todos(self, tmp_path):
        std = tmp_path / "std"
        std.mkdir()
        (std / "a.mm").write_text(
            "// TODO: write docs\n// TODO: refactor something\n",
            encoding="utf-8",
        )
        assert scan_std_todos(std) == []


class TestRealForgeSpecs:
    """Validate that every JSON spec under forge_tasks/ loads correctly."""

    @pytest.mark.parametrize(
        "spec_name",
        [
            "vstd_safe_list.json",
            "vstd_fixed_point.json",
            "vstd_string_utils.json",
            "vstd_math_min_max.json",
            "vstd_math_sqrt.json",
            "vstd_container_priority_queue.json",
            "vstd_bitwise.json",
            "vstd_math_log2.json",
            "vstd_container_set.json",
        ],
    )
    def test_new_p9d_specs_load(self, spec_name):
        path = FORGE_TASKS_DIR / spec_name
        assert path.exists(), f"missing forge spec: {path}"
        task = _load_task(path)
        assert task is not None, f"_load_task returned None for {path}"
        assert task["task_id"]
        assert task["target_file"].startswith("std/")
        assert task["mode"] == "create"
        assert isinstance(task["atoms"], list) and task["atoms"]
        for atom in task["atoms"]:
            assert "name" in atom and atom["name"]
            assert "inputs" in atom and isinstance(atom["inputs"], list)
            assert "return_type" in atom
            assert "requires" in atom
            assert "ensures" in atom

    def test_all_real_specs_discoverable(self):
        tasks = discover_tasks(FORGE_TASKS_DIR)
        ids = {t["task_id"] for t in tasks}
        for required in {
            "vstd-safe-list",
            "vstd-fixed-point",
            "vstd-string-utils",
            "vstd-math-min-max",
            "vstd-math-sqrt",
            "vstd-container-priority-queue",
            "vstd-bitwise",
            "vstd-math-log2",
            "vstd-container-set",
        }:
            assert required in ids, f"{required} not found in {sorted(ids)}"
