"""Tests for dependency invalidation and its blast-radius join."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import agent.proliferate_healing
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
        text = 'import "std/core" as core;\nimport "std/math/safe_mul";\n'
        assert _declared_import_targets(text) == [
            "std/core",
            "std/math/safe_mul",
        ]

    def test_leading_whitespace_accepted(self):
        assert _declared_import_targets('  import "std/core" as core;') == ["std/core"]

    def test_commented_usage_lines_ignored(self):
        text = (
            '// Usage: import "std/core" as core;\n'
            '//   import "std/alloc" as alloc;\n'
            'import "std/json" as json;\n'
        )
        assert _declared_import_targets(text) == ["std/json"]

    def test_no_imports(self):
        assert _declared_import_targets("atom a()\n    requires: true;") == []

    def test_malformed_lines_ignored(self):
        assert _declared_import_targets("import std/core as core;") == []
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

    def test_unresolved_import_is_undetermined(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "a.mm": "atom a()\n    requires: true;\n",
                "b.mm": 'import "std/ghost_dep" as ghost;\n',
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/other.mm")
        assert m["unresolved_imports"] == {"std/b.mm": ["std/ghost_dep"]}
        assert m["re_derive"] == []
        assert m["undetermined"] == ["std/b.mm"]
        assert m["unaffected"] == ["std/a.mm"]

    def test_unresolved_import_and_transitive_dependents_are_undetermined(
        self, tmp_path
    ):
        repo = _repo(
            tmp_path,
            {
                "a.mm": 'import "std/missing" as missing;\n',
                "b.mm": 'import "std/a" as a;\n',
                "c.mm": 'import "std/b" as b;\n',
                "d.mm": "atom d()\n    requires: true;\n",
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/changed.mm")
        assert m["undetermined"] == ["std/a.mm", "std/b.mm", "std/c.mm"]
        assert m["unaffected"] == ["std/d.mm"]

    def test_import_resolution_matches_compiler_order(self, tmp_path):
        cases = [
            ("x.mm", "core_guards", "core_guards.mm"),
            ("a.mm", "./b", "b.mm"),
            ("math/f.mm", "../core", "core.mm"),
            ("math/f.mm", "std/core", "core.mm"),
            ("math/f.mm", "std/core.mm", "core.mm"),
        ]
        for importer, target, dependency in cases:
            repo = _repo(
                tmp_path / target.replace("/", "_").replace(".", "_"),
                {
                    importer: f'import "{target}" as dep;\n',
                    dependency: "atom dep()\n    requires: true;\n",
                },
            )
            m = dependency_invalidation_map(repo / "std", f"std/{dependency}")
            assert f"std/{importer}" in m["re_derive"]
            assert m["unresolved_imports"] == {}

    @pytest.mark.parametrize(
        "target",
        ["/absolute/module", r"C:\absolute\module"],
    )
    def test_absolute_import_is_unresolved(self, tmp_path, target):
        repo = _repo(tmp_path, {"a.mm": f'import "{target}" as dep;\n'})
        m = dependency_invalidation_map(repo / "std", "std/other.mm")
        assert m["unresolved_imports"] == {"std/a.mm": [target]}
        assert m["undetermined"] == ["std/a.mm"]

    def test_import_escaping_std_is_unresolved(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "math/f.mm": 'import "../../outside" as outside;\n',
                "outside.mm": "atom outside()\n    requires: true;\n",
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/other.mm")
        assert m["unresolved_imports"] == {"std/math/f.mm": ["../../outside"]}
        assert m["undetermined"] == ["std/math/f.mm"]

    def test_implicit_prelude_edge_invalidates_every_other_file(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "prelude.mm": "atom prelude()\n    requires: true;\n",
                "core.mm": "atom core()\n    requires: true;\n",
                "math/a.mm": "atom a()\n    requires: true;\n",
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/prelude.mm")
        assert m["re_derive"] == ["std/core.mm", "std/math/a.mm"]
        assert m["implicit_imports"] == ["std/prelude.mm"]

    def test_no_prelude_means_no_implicit_imports(self, tmp_path):
        repo = _repo(
            tmp_path,
            {"core.mm": "atom core()\n    requires: true;\n"},
        )
        m = dependency_invalidation_map(repo / "std", "std/core.mm")
        assert m["implicit_imports"] == []

    def test_prelude_importing_core_invalidates_prelude_and_all_files(self, tmp_path):
        repo = _repo(
            tmp_path,
            {
                "prelude.mm": 'import "std/core" as core;\n',
                "core.mm": "atom core()\n    requires: true;\n",
                "math/a.mm": "atom a()\n    requires: true;\n",
            },
        )
        m = dependency_invalidation_map(repo / "std", "std/core.mm")
        assert m["re_derive"] == [
            "std/core.mm",
            "std/math/a.mm",
            "std/prelude.mm",
        ]
        assert m["implicit_imports"] == ["std/prelude.mm"]

    def test_unreadable_file_is_undetermined_and_propagates(self, tmp_path):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("chmod cannot make a file unreadable to root")
        repo = _repo(
            tmp_path,
            {
                "a.mm": "atom a()\n    requires: true;\n",
                "b.mm": 'import "std/a" as a;\n',
            },
        )
        unreadable = repo / "std" / "a.mm"
        unreadable.chmod(0)
        try:
            m = dependency_invalidation_map(repo / "std", "std/other.mm")
        finally:
            unreadable.chmod(0o644)
        assert m["unresolved_imports"] == {"std/a.mm": ["<unreadable>"]}
        assert m["undetermined"] == ["std/a.mm", "std/b.mm"]

    def test_self_import_not_unresolved(self, tmp_path):
        repo = _repo(
            tmp_path,
            {"a.mm": 'import "std/a" as a;\n'},
        )
        m = dependency_invalidation_map(repo / "std", "std/a.mm")
        assert m["unresolved_imports"] == {}
        assert m["re_derive"] == []
        assert m["unaffected"] == []

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
            "external_std_path_resolution",
        ):
            assert check in m["checks_not_performed"]
        assert "transitive_prelude_import" not in m["checks_not_performed"]

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
    def test_broken_dependent_has_rederive_relation(self, tmp_path):
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
        assert result["broken_files"][0]["dependency_relation"] == "re_derive"
        inv = result["dependency_invalidation"]
        assert inv["changed"] == "std/new_mod.mm"
        assert inv["re_derive"] == ["std/a.mm"]

    def test_independent_broken_file_has_unaffected_relation(self, tmp_path):
        std_dir = tmp_path / "std"
        _mm(std_dir, "a.mm", "atom a()\n    requires: true;\n")
        client = _FakeMumeiClient({"a.mm": "type error"})
        candidate = tmp_path / "std" / "new_mod.mm"
        result = check_blast_radius(
            client, tmp_path, candidate, "atom new_mod()\n    requires: true;\n"
        )
        assert result["broken_files"][0]["dependency_relation"] == "unaffected"
        assert result["dependency_invalidation"]["re_derive"] == []

    def test_unresolved_broken_file_has_undetermined_relation(self, tmp_path):
        std_dir = tmp_path / "std"
        _mm(std_dir, "a.mm", 'import "std/missing" as missing;\n')
        result = check_blast_radius(
            _FakeMumeiClient({"a.mm": "type error"}),
            tmp_path,
            std_dir / "new_mod.mm",
            "atom new_mod()\n    requires: true;\n",
        )
        assert result["broken_files"][0]["dependency_relation"] == "undetermined"

    def test_map_failure_omits_map_and_uses_undetermined(self, tmp_path, monkeypatch):
        std_dir = tmp_path / "std"
        _mm(std_dir, "a.mm", "atom a()\n    requires: true;\n")

        def raiser(*args, **kwargs):
            raise ValueError("map unavailable")

        monkeypatch.setattr(
            agent.proliferate_healing, "dependency_invalidation_map", raiser
        )
        result = check_blast_radius(
            _FakeMumeiClient({"a.mm": "type error"}),
            tmp_path,
            std_dir / "new_mod.mm",
            "atom new_mod()\n    requires: true;\n",
        )
        assert "dependency_invalidation" not in result
        assert result["broken_files"][0]["dependency_relation"] == "undetermined"

    def test_candidate_outside_repo_uses_undetermined_without_map(self, tmp_path):
        repo = tmp_path / "repo"
        std_dir = repo / "std"
        _mm(std_dir, "a.mm", "atom a()\n    requires: true;\n")
        result = check_blast_radius(
            _FakeMumeiClient({"a.mm": "type error"}),
            repo,
            tmp_path / "new_mod.mm",
            "atom new_mod()\n    requires: true;\n",
        )
        assert "dependency_invalidation" not in result
        assert result["broken_files"][0]["dependency_relation"] == "undetermined"

    def test_broken_symlink_outside_repo_does_not_crash(self, tmp_path):
        std_dir = tmp_path / "std"
        std_dir.mkdir(parents=True)
        outside = tmp_path / "outside.mm"
        outside.write_text("atom outside()\n    requires: true;\n", encoding="utf-8")
        (std_dir / "escape.mm").symlink_to(outside)
        result = check_blast_radius(
            _FakeMumeiClient({"escape.mm": "type error"}),
            tmp_path,
            std_dir / "new_mod.mm",
            "atom new_mod()\n    requires: true;\n",
        )
        assert result["broken_files"][0]["dependency_relation"] == "unaffected"

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
