"""Tests for directory-based multi-file heal ordering."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import mcp_server
from agent.strategies.fix_strategy import (
    CyclicDependencyWarning,
    _aggregate_heal_results,
    build_dependency_graph,
    topological_sort_files,
)


def _payload(raw: str) -> dict:
    assert isinstance(raw, str)
    return json.loads(raw)


def test_directory_heal_collects_mm_files_recursively(monkeypatch, tmp_path: Path) -> None:
    root_file = tmp_path / "root.mm"
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_file = nested_dir / "child.mm"
    ignored_file = nested_dir / "child.txt"
    root_file.write_text("atom root() -> i64 body: { 0 }\n", encoding="utf-8")
    nested_file.write_text("atom child() -> i64 body: { 0 }\n", encoding="utf-8")
    ignored_file.write_text("not mumei\n", encoding="utf-8")

    healed: list[Path] = []

    def fake_heal_single_file(path: Path, **_kwargs) -> dict:
        healed.append(path)
        return {"file": str(path), "success": True, "attempts": 1}

    monkeypatch.setattr(mcp_server, "_heal_single_file", fake_heal_single_file)
    monkeypatch.setattr("agent.config.AgentConfig", lambda: SimpleNamespace(
        mumei_bin="mumei",
        create_client=lambda: SimpleNamespace(),
    ))
    monkeypatch.setattr(
        "agent.mumei_client.create_mumei_client",
        lambda _bin: SimpleNamespace(),
    )

    result = _payload(mcp_server._heal_directory(tmp_path))

    assert result["status"] == "ok"
    assert result["total_files"] == 2
    assert healed == sorted([root_file.resolve(), nested_file.resolve()])


def test_dependency_graph_orders_dependencies_before_dependents(tmp_path: Path) -> None:
    dependency = tmp_path / "dependency.mm"
    dependent = tmp_path / "dependent.mm"
    dependency.write_text("atom dependency() -> i64 body: { 1 }\n", encoding="utf-8")
    dependent.write_text(
        "import dependency;\natom dependent() -> i64 body: { dependency() }\n",
        encoding="utf-8",
    )

    graph = build_dependency_graph([dependent, dependency])
    ordered = topological_sort_files(graph)

    assert ordered == [dependency.resolve(), dependent.resolve()]


def test_cycle_emits_warning_and_keeps_all_files(tmp_path: Path) -> None:
    left = tmp_path / "left.mm"
    right = tmp_path / "right.mm"
    left.write_text("import right;\n", encoding="utf-8")
    right.write_text("import left;\n", encoding="utf-8")

    graph = build_dependency_graph([left, right])
    with pytest.warns(CyclicDependencyWarning):
        ordered = topological_sort_files(graph)

    assert set(ordered) == {left.resolve(), right.resolve()}


def test_directory_heal_routes_cycles_to_manual_review(
    monkeypatch,
    tmp_path: Path,
) -> None:
    left = tmp_path / "left.mm"
    right = tmp_path / "right.mm"
    left.write_text("import right;\n", encoding="utf-8")
    right.write_text("import left;\n", encoding="utf-8")
    healed: list[Path] = []

    def fake_heal_single_file(path: Path, **_kwargs) -> dict:
        healed.append(path)
        return {"file": str(path), "success": True, "attempts": 1}

    monkeypatch.setattr(mcp_server, "_heal_single_file", fake_heal_single_file)

    result = _payload(mcp_server._heal_directory(tmp_path))

    assert result["status"] == "ok"
    assert result["success"] is False
    assert result["failed"] == 2
    assert result["manual_review_required"]["reason"] == "cyclic_dependency"
    assert healed == []


def test_aggregate_heal_results_formats_summary() -> None:
    result = _aggregate_heal_results(
        [
            {"file": "ok.mm", "success": True, "attempts": 1},
            {"file": "bad.mm", "success": False, "attempts": 2, "error": "failed"},
        ]
    )

    assert result == {
        "success": False,
        "total_files": 2,
        "succeeded": 1,
        "failed": 1,
        "files": [
            {"file": "ok.mm", "success": True, "attempts": 1},
            {"file": "bad.mm", "success": False, "attempts": 2, "error": "failed"},
        ],
    }
