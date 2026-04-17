"""Integration-style unit tests for Step 2-4 of forge mode expansion.

Covers:
- SafeList task spec validation and discovery
- Z3 logical-repair enrichment (``_enrich_error_with_report``)
- Cross-file context loading (``MumeiForge._load_context_files``)
- Logical Repair Protocol wording in ``FORGE_SYSTEM_PROMPT`` and append prompt
- ``--dry-run`` plan for SafeList
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from agent.forge import MumeiForge, _enrich_error_with_report
from agent.forge_discovery import discover_tasks
from agent.prompts.forge.forge_append import build_append_prompt
from agent.prompts.forge.forge_system import FORGE_SYSTEM_PROMPT


REPO_ROOT = Path(__file__).resolve().parent.parent
SAFE_LIST_SPEC = REPO_ROOT / "forge_tasks" / "vstd_safe_list.json"


# ---------------------------------------------------------------------------
# Step 2: SafeList task spec validation
# ---------------------------------------------------------------------------


class TestSafeListSpec:
    def test_spec_file_exists(self):
        assert SAFE_LIST_SPEC.exists(), \
            f"Expected SafeList spec at {SAFE_LIST_SPEC}"

    def test_spec_parses_as_valid_json(self):
        data = json.loads(SAFE_LIST_SPEC.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_spec_required_fields(self):
        data = json.loads(SAFE_LIST_SPEC.read_text(encoding="utf-8"))
        assert data["task_id"] == "vstd-container-safe-list"
        assert data["target_file"] == "std/container/safe_list.mm"
        assert data["mode"] == "create"
        assert data["auto_commit"] is False
        assert isinstance(data["atoms"], list) and len(data["atoms"]) >= 1

    def test_spec_includes_context_files(self):
        data = json.loads(SAFE_LIST_SPEC.read_text(encoding="utf-8"))
        ctx = data.get("context_files")
        assert isinstance(ctx, list) and ctx
        assert "std/container/safe_queue.mm" in ctx
        assert "std/container/bounded_array.mm" in ctx
        assert "std/contracts.mm" in ctx

    def test_atoms_have_names_and_contracts(self):
        data = json.loads(SAFE_LIST_SPEC.read_text(encoding="utf-8"))
        names = {a.get("name") for a in data["atoms"]}
        # Core API surface promised by the spec.
        for expected in (
            "safe_get", "safe_set", "safe_push", "safe_pop",
            "safe_list_is_empty", "safe_list_is_full", "safe_list_remaining",
            "safe_get_checked",
        ):
            assert expected in names, f"Missing atom: {expected}"
        for atom in data["atoms"]:
            assert "requires" in atom and atom["requires"]
            assert "ensures" in atom and atom["ensures"]
            assert atom.get("return_type")

    def test_discover_tasks_finds_safe_list(self, tmp_path):
        # Copy the real spec into an isolated tasks dir so discover_tasks
        # only sees one file (avoids interference from other specs).
        tasks_dir = tmp_path / "forge_tasks"
        tasks_dir.mkdir()
        (tasks_dir / "vstd_safe_list.json").write_text(
            SAFE_LIST_SPEC.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        tasks = discover_tasks(tasks_dir)
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "vstd-container-safe-list"
        assert tasks[0]["mode"] == "create"


# ---------------------------------------------------------------------------
# Step 3: Z3 Logical Repair Protocol
# ---------------------------------------------------------------------------


class TestLogicalRepairProtocol:
    def test_system_prompt_contains_protocol_header(self):
        assert "Logical Repair Protocol" in FORGE_SYSTEM_PROMPT
        assert "論理修復プロトコル" in FORGE_SYSTEM_PROMPT

    def test_system_prompt_lists_four_repair_strategies(self):
        # All four strategies must be documented so the LLM knows the
        # complete menu of fixes it is allowed to pick from.
        assert "Strengthen Precondition" in FORGE_SYSTEM_PROMPT
        assert "Weaken Postcondition" in FORGE_SYSTEM_PROMPT
        assert "Fix Body Logic" in FORGE_SYSTEM_PROMPT
        assert "Invariant Adjustment" in FORGE_SYSTEM_PROMPT

    def test_append_prompt_includes_logical_repair_analysis(self):
        task = {
            "task_id": "t",
            "target_file": "std/x.mm",
            "atoms": [{
                "name": "f",
                "requires": "x > 0",
                "ensures": "result == x",
            }],
        }
        prompt = build_append_prompt(
            task,
            existing_source="// existing code\n",
            last_error="ensures violated: result >= 0",
            last_snippet="atom f() ensures: result >= 0; body: 0;",
        )
        assert "Logical Repair Analysis" in prompt
        assert "counterexample" in prompt.lower()
        assert "unsat core" in prompt.lower()


class TestEnrichErrorWithReport:
    def test_none_report_preserves_raw_error(self):
        assert _enrich_error_with_report("boom", None) == "boom"

    def test_empty_report_preserves_raw_error(self):
        assert _enrich_error_with_report("boom", {}) == "boom"

    def test_counterexample_added_to_structured_analysis(self):
        report = {
            "failure_type": "postcondition_violated",
            "counterexample": {"a": 0, "b": 0},
        }
        enriched = _enrich_error_with_report("postcondition failed", report)
        assert "Structured Analysis" in enriched
        assert "Z3 Counter-example" in enriched
        assert "a=0" in enriched and "b=0" in enriched
        # Actionable hint must also be surfaced.
        assert "ensures" in enriched.lower() or "Actionable fix hint" in enriched

    def test_structured_unsat_core_surface(self):
        report = {
            "failure_type": "invariant_violated",
            "semantic_feedback": {
                "structured_unsat_core": [
                    {
                        "constraint_type": "requires",
                        "param": "x",
                        "description": "x >= 0 conflicts with x < 0",
                    }
                ],
            },
        }
        enriched = _enrich_error_with_report("inv", report)
        assert "Structured unsat core" in enriched
        assert "requires" in enriched


# ---------------------------------------------------------------------------
# Step 4: Cross-file context loading
# ---------------------------------------------------------------------------


class TestLoadContextFiles:
    def _make_forge(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        tasks = tmp_path / "forge_tasks"
        tasks.mkdir()
        cfg = MagicMock()
        cfg.mumei_bin = "mumei"
        cfg.model = "test-model"
        return MumeiForge(
            config=cfg,
            mumei_client=MagicMock(),
            mumei_repo_dir=repo,
            forge_tasks_dir=tasks,
            log_path=tmp_path / "forge_log.json",
            openai_client=MagicMock(),
        )

    def test_no_context_files_returns_empty(self, tmp_path):
        forge = self._make_forge(tmp_path)
        assert forge._load_context_files({}) == ""
        assert forge._load_context_files({"context_files": []}) == ""

    def test_loads_existing_files(self, tmp_path):
        forge = self._make_forge(tmp_path)
        (forge.mumei_repo_dir / "std").mkdir()
        (forge.mumei_repo_dir / "std" / "a.mm").write_text(
            "atom a() requires: true; ensures: true; body: 0;",
            encoding="utf-8",
        )
        (forge.mumei_repo_dir / "std" / "b.mm").write_text(
            "atom b() requires: true; ensures: true; body: 1;",
            encoding="utf-8",
        )
        ctx = forge._load_context_files({
            "context_files": ["std/a.mm", "std/b.mm"]
        })
        assert "Cross-file context" in ctx
        assert "std/a.mm" in ctx
        assert "std/b.mm" in ctx
        assert "atom a()" in ctx
        assert "atom b()" in ctx

    def test_rejects_paths_escaping_repo_root(self, tmp_path):
        forge = self._make_forge(tmp_path)
        # Attempt to pull a file from outside the repo via ``..``
        outside = tmp_path / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        ctx = forge._load_context_files({
            "context_files": ["../secret.txt"]
        })
        assert ctx == ""
        assert "secret" not in ctx

    def test_missing_files_are_skipped(self, tmp_path):
        forge = self._make_forge(tmp_path)
        ctx = forge._load_context_files({
            "context_files": ["std/does_not_exist.mm"]
        })
        assert ctx == ""

    def test_mixes_missing_and_present_files(self, tmp_path):
        forge = self._make_forge(tmp_path)
        (forge.mumei_repo_dir / "std").mkdir()
        (forge.mumei_repo_dir / "std" / "real.mm").write_text(
            "atom real() requires: true; ensures: true; body: 42;",
            encoding="utf-8",
        )
        ctx = forge._load_context_files({
            "context_files": ["std/missing.mm", "std/real.mm"]
        })
        assert "std/real.mm" in ctx
        assert "atom real()" in ctx
        # Missing file should simply be skipped, not fatal.
        assert "std/missing.mm" not in ctx


class TestTaskToGenerateSpecCrossFileContext:
    def _make_forge(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "std").mkdir()
        (repo / "std" / "ref.mm").write_text(
            "atom ref() requires: true; ensures: true; body: 0;",
            encoding="utf-8",
        )
        cfg = MagicMock()
        cfg.mumei_bin = "mumei"
        cfg.model = "test-model"
        return MumeiForge(
            config=cfg,
            mumei_client=MagicMock(),
            mumei_repo_dir=repo,
            forge_tasks_dir=tmp_path / "forge_tasks",
            log_path=tmp_path / "forge_log.json",
            openai_client=MagicMock(),
        )

    def test_single_atom_spec_includes_cross_file_context(self, tmp_path):
        forge = self._make_forge(tmp_path)
        task = {
            "task_id": "solo",
            "atoms": [{"name": "f", "requires": "true", "ensures": "true"}],
            "context_files": ["std/ref.mm"],
        }
        spec = forge._task_to_generate_spec(task)
        assert "cross_file_context" in spec
        assert "atom ref()" in spec["cross_file_context"]

    def test_multi_atom_spec_includes_cross_file_context(self, tmp_path):
        forge = self._make_forge(tmp_path)
        task = {
            "task_id": "multi",
            "atoms": [
                {"name": "a"},
                {"name": "b"},
            ],
            "context_files": ["std/ref.mm"],
        }
        spec = forge._task_to_generate_spec(task)
        assert spec["module_name"] == "multi"
        assert "cross_file_context" in spec
        assert "atom ref()" in spec["cross_file_context"]

    def test_missing_context_files_omits_field(self, tmp_path):
        forge = self._make_forge(tmp_path)
        task = {
            "task_id": "plain",
            "atoms": [{"name": "f"}],
        }
        spec = forge._task_to_generate_spec(task)
        assert "cross_file_context" not in spec


# ---------------------------------------------------------------------------
# dry-run plan for SafeList
# ---------------------------------------------------------------------------


class TestSafeListDryRun:
    def test_single_task_dry_run_plan(self, tmp_path, capsys):
        # Copy the real SafeList spec into an isolated dir and run dry-run.
        repo = tmp_path / "repo"
        repo.mkdir()
        tasks_dir = tmp_path / "forge_tasks"
        tasks_dir.mkdir()
        (tasks_dir / "vstd_safe_list.json").write_text(
            SAFE_LIST_SPEC.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        cfg = MagicMock()
        cfg.mumei_bin = "mumei"
        cfg.model = "test-model"
        forge = MumeiForge(
            config=cfg,
            mumei_client=MagicMock(),
            mumei_repo_dir=repo,
            forge_tasks_dir=tasks_dir,
            log_path=tmp_path / "forge_log.json",
            openai_client=MagicMock(),
        )

        results = forge.run(dry_run=True)
        assert len(results) == 1
        assert results[0].task_id == "vstd-container-safe-list"
        assert results[0].status == "skipped"

        out = capsys.readouterr().out
        assert "vstd-container-safe-list" in out
        assert "std/container/safe_list.mm" in out
        assert "mode=create" in out
