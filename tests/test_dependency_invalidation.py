"""Tests for agent.dependency_invalidation and its blast-radius join.

The map is detection-only metadata: it derives which existing ``.mm``
files transitively import a changed file (the re-derive set) and which
are provably unaffected, on top of the ``_scan_std_imports`` graph.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.dependency_invalidation import (
    CHECKS_NOT_PERFORMED,
    SCHEMA_VERSION,
    _declared_import_targets,
    dependency_invalidation_map,
)
from agent.proliferate_healing import check_blast_radius


def _mm(std_dir: Path, rel: str, body: str = "") -> Path:
    path = std_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = body or f"atom {Path(rel).stem}()\n    requires: true;\n"
    path.write_text(text, encoding="utf-8")
    return path


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    std_dir = tmp_path / "std"
    std_dir.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        _mm(std_dir, rel, body)
    return tmp_path


class TestDeclaredImportTargets:
    def test_plain_and_aliased_imports(self):
        text = (
            'import "std/core" as core;\n'
            'import "std/math/safe_mul";\n'
        )
        assert _declared_import_targets(text) == [
            "std/core",
            "std/math/safe_mul",
        ]

    def test_leading_whitespace_accepted(self):
        assert _declared_import_targets('  import "std/core" as core;') == [
            "std/core"
        ]

    def test_commented_usage_lines_ignored(self):
        text = (
            "// Usage: import \"std/core\" as core;\n"
            "//   import \"std/alloc\" as alloc;\n"
            'import "std/json" as json;\n'
        )
        assert _declared_import_targets(text) == ["std/json"]

    def test_no_imports(self):
        assert _declared_import_targets("atom a()\n    requires: true;") == []

    def test_malformed_lines_ignored(self):
        assert _declared_import_targets('import std/core as core;') == []
        assert _declared_import_targets('import "std/core"') == []


class TestInvalidationMap:
    def test_linear_chain(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.mm": "atom a()\n    requires: true;\n",
                "b.mm": 'import "std/a" as a;\n',
                "c.mm": 'import "std/b" as b;\n',
                "d.mm": "atom d()\n    requires: true;\n",
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/a.mm")
        assert m["schema_version"] == SCHEMA_VERSION
        assert m["changed"] == "std/a.mm"
        assert m["re_derive"] == ["std/b.mm", "std/c.mm"]
        assert m["unaffected"] == ["std/d.mm"]

    def test_diamond(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.mm": "atom a()\n    requires: true;\n",
                "b.mm": 'import "std/a" as a;\n',
                "c.mm": 'import "std/a" as a;\n',
                "d.mm": 'import "std/b" as b;\nimport "std/c" as c;\n',
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/a.mm")
        assert m["re_derive"] == ["std/b.mm", "std/c.mm", "std/d.mm"]

    def test_cycle_members_all_invalidate_each_other(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.mm": 'import "std/b" as b;\n',
                "b.mm": 'import "std/a" as a;\n',
                "c.mm": 'import "std/b" as b;\n',
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/a.mm")
        # B imports A; A and C import B — the whole component lands here.
        assert m["re_derive"] == ["std/a.mm", "std/b.mm", "std/c.mm"]

    def test_new_file_nothing_imports(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.mm": "atom a()\n    requires: true;\n",
                "b.mm": 'import "std/a" as a;\n',
                "new.mm": "atom new_mod()\n    requires: true;\n",
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/new.mm")
        assert m["re_derive"] == []
        assert m["unaffected"] == ["std/a.mm", "std/b.mm"]

    def test_changed_outside_graph(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.mm": "atom a()\n    requires: true;\n",
                "b.mm": 'import "std/a" as a;\n',
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/ghost.mm")
        assert m["re_derive"] == []
        assert m["unaffected"] == ["std/a.mm", "std/b.mm"]

    def test_subdirectory_keys(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "math/safe_mul.mm": "atom sm()\n    requires: true;\n",
                "math/factorial.mm": 'import "std/math/safe_mul" as sm;\n',
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/math/safe_mul.mm")
        assert m["re_derive"] == ["std/math/factorial.mm"]

    def test_unresolved_import_reported_informationally(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.mm": "atom a()\n    requires: true;\n",
                "b.mm": 'import "std/ghost_dep" as ghost;\n',
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/a.mm")
        assert m["unresolved_imports"] == {"std/b.mm": ["std/ghost_dep"]}
        # An unresolved name cannot point at an existing changed file:
        # b stays honestly classified unaffected by a.
        assert m["re_derive"] == []

    def test_self_import_not_unresolved(self, tmp_path):
        repo = _repo(
            tmp_path,
            {"a.mm": 'import "std/a" as a;\n'},
        )
        m = dependency_invalidation_map(repo / "std", "std/a.mm")
        assert m["unresolved_imports"] == {}

    def test_comment_only_import_does_not_create_edge(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.mm": "atom a()\n    requires: true;\n",
                "b.mm": '// Usage: import "std/a" as a;\n',
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/a.mm")
        assert m["re_derive"] == []
        assert m["unaffected"] == ["std/b.mm"]

    def test_checks_not_performed_honest(self, tmp_path):
        repo = _repo(tmp_path, {"a.mm": "atom a()\n    requires: true;\n"})
        m = dependency_invalidation_map(repo / "std", "std/a.mm")
        assert m["checks_not_performed"] == CHECKS_NOT_PERFORMED
        for check in (
            "re_verification",
            "contract_level_diff",
            "symbol_resolution",
        ):
            assert check in m["checks_not_performed"]

    def test_empty_std_dir(self, tmp_path):
        std_dir = tmp_path / "std"
        std_dir.mkdir(parents=True)
        m = dependency_invalidation_map(std_dir, "std/a.mm")
        assert m["re_derive"] == []
        assert m["unaffected"] == []

    def test_missing_std_dir(self, tmp_path):
        m = dependency_invalidation_map(tmp_path / "nope", "std/a.mm")
        assert m["re_derive"] == []
        assert m["unaffected"] == []

    def test_output_deterministic(self, tmp_path):
        files = {
            "a.mm": "atom a()\n    requires: true;\n",
            "b.mm": 'import "std/a" as a;\n',
            "c.mm": 'import "std/a" as a;\nimport "std/b" as b;\n',
        }
        repo = _repo(tmp_path, files)
        first = dependency_invalidation_map(repo / "std", "std/a.mm")
        second = dependency_invalidation_map(repo / "std", "std/a.mm")
        assert first == second


class _FakeMumeiClient:
    """Verifies every file as passing except a configurable set."""

    def __init__(self, failing: dict[str, str] | None = None):
        self._failing = failing or {}

    def verify(self, path: str) -> dict:
        name = Path(path).name
        if name in self._failing:
            return {"success": False, "stderr": self._failing[name]}
        return {"success": True}


class TestBlastRadiusJoin:
    def test_broken_dependent_flagged_dependency_driven(self, tmp_path):
        std_dir = tmp_path / "std"
        _mm(std_dir, "a.mm", 'import "std/new_mod" as nm;\n')
        _mm(std_dir, "b.mm", "atom b()\n    requires: true;\n")
        client = _FakeMumeiClient({"a.mm": "type error"})
        candidate = tmp_path / "std" / "new_mod.mm"
        result = check_blast_radius(
            client, tmp_path, candidate, "atom new_mod()\n    requires: true;\n"
        )
        assert result["all_passed"] is False
        assert len(result["broken_files"]) == 1
        assert result["broken_files"][0]["dependency_driven"] is True
        inv = result["dependency_invalidation"]
        assert inv["changed"] == "std/new_mod.mm"
        assert inv["re_derive"] == ["std/a.mm"]

    def test_independent_broken_file_flagged_false(self, tmp_path):
        std_dir = tmp_path / "std"
        _mm(std_dir, "a.mm", "atom a()\n    requires: true;\n")
        client = _FakeMumeiClient({"a.mm": "type error"})
        candidate = tmp_path / "std" / "new_mod.mm"
        result = check_blast_radius(
            client, tmp_path, candidate, "atom new_mod()\n    requires: true;\n"
        )
        assert result["broken_files"][0]["dependency_driven"] is False
        assert result["dependency_invalidation"]["re_derive"] == []

    def test_all_passed_still_carries_map(self, tmp_path):
        std_dir = tmp_path / "std"
        _mm(std_dir, "a.mm", 'import "std/new_mod" as nm;\n')
        result = check_blast_radius(
            _FakeMumeiClient(),
            tmp_path,
            tmp_path / "std" / "new_mod.mm",
            "atom new_mod()\n    requires: true;\n",
        )
        assert result["all_passed"] is True
        assert result["broken_files"] == []
        assert result["dependency_invalidation"]["re_derive"] == ["std/a.mm"]

    def test_candidate_removed_after_check(self, tmp_path):
        std_dir = tmp_path / "std"
        _mm(std_dir, "a.mm", "atom a()\n    requires: true;\n")
        candidate = tmp_path / "std" / "new_mod.mm"
        check_blast_radius(
            _FakeMumeiClient(), tmp_path, candidate, "atom n()\n    requires: true;\n"
        )
        assert not candidate.exists()
