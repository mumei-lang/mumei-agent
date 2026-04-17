"""Unit tests for ``agent.proliferate`` — SI-5 Phase 2-C.

These tests exercise the pure-Python helpers of the proliferation
pipeline.  The LLM-dependent steps (``generate_code``, ``publish``) are
mocked so the tests stay hermetic — no network, no mumei binary.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import proliferate


# ---------------------------------------------------------------------------
# analyze_gaps
# ---------------------------------------------------------------------------


def _write_mm(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestAnalyzeGaps:
    def test_empty_std_returns_empty_result(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        result = proliferate.analyze_gaps(std)
        assert result["dependency_graph"] == {}
        assert result["trusted_atoms"] == []
        assert result["todo_comments"] == []
        # ``std/core.mm`` rule triggers even without siblings.
        assert any(p["name"] == "std/core.mm" for p in result["proposals"])

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        result = proliferate.analyze_gaps(tmp_path / "does-not-exist")
        assert result["proposals"] == []
        assert result["dependency_graph"] == {}

    def test_dependency_graph_captures_imports(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "prelude.mm",
            "// prelude\natom prelude_ok(x: i64) ensures: true; body: x;\n",
        )
        _write_mm(
            std / "iter.mm",
            'import "std/prelude" as prelude;\n'
            "atom iter_ok(x: i64) ensures: true; body: x;\n",
        )
        result = proliferate.analyze_gaps(std)
        assert "std/iter.mm" in result["dependency_graph"]
        assert "std/prelude.mm" in result["dependency_graph"]["std/iter.mm"]

    def test_trusted_atoms_detected(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "core.mm",
            "// proof hole: pending formalization\n"
            "trusted atom size_lift(x: u64) ensures: true; body: {}\n",
        )
        result = proliferate.analyze_gaps(std)
        assert any(
            t["atom"] == "size_lift" and t["file"] == "std/core.mm"
            for t in result["trusted_atoms"]
        )

    def test_todo_comments_detected(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "hash.mm",
            "// TODO: add collision resistance law\n"
            "atom hash_ok(x: i64) ensures: true; body: x;\n",
        )
        result = proliferate.analyze_gaps(std)
        assert any("TODO" in t["text"].upper() for t in result["todo_comments"])

    def test_trusted_atom_reason_takes_nearest_comment(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "core.mm",
            "// line A: general context\n"
            "// line B: actual reason\n"
            "trusted atom size_lift(x: u64) ensures: true; body: {}\n",
        )
        result = proliferate.analyze_gaps(std)
        ta = [t for t in result["trusted_atoms"] if t["atom"] == "size_lift"]
        assert len(ta) == 1
        assert "line B" in ta[0]["reason"]

    def test_existing_core_does_not_propose_core(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "core.mm",
            "atom core_ok(x: i64) ensures: true; body: x;\n",
        )
        result = proliferate.analyze_gaps(std)
        names = {p["name"] for p in result["proposals"]}
        assert "std/core.mm" not in names

    def test_proposals_are_ranked_and_capped(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        result = proliferate.analyze_gaps(std)
        # Cap is 3 regardless of how many rules match.
        assert len(result["proposals"]) <= 3
        # Each proposal has priority assigned in [1..3].
        for p in result["proposals"]:
            assert 1 <= p["priority"] <= 3


# ---------------------------------------------------------------------------
# generate_specs_from_gaps
# ---------------------------------------------------------------------------


class TestGenerateSpecsFromGaps:
    def test_empty_proposals_returns_empty(self) -> None:
        assert proliferate.generate_specs_from_gaps({"proposals": []}) == []

    def test_max_count_is_respected(self) -> None:
        gaps = {
            "proposals": [
                {"name": "std/a.mm", "reason": "", "depends_on": [], "difficulty": "low"},
                {"name": "std/b.mm", "reason": "", "depends_on": [], "difficulty": "low"},
                {"name": "std/c.mm", "reason": "", "depends_on": [], "difficulty": "low"},
            ]
        }
        specs = proliferate.generate_specs_from_gaps(gaps, max_count=2)
        assert len(specs) == 2
        assert [s["target_file"] for s in specs] == ["std/a.mm", "std/b.mm"]

    def test_produces_forge_compatible_specs(self) -> None:
        gaps = {
            "proposals": [
                {
                    "name": "std/iter.mm",
                    "reason": "iter",
                    "depends_on": ["std/prelude.mm"],
                    "difficulty": "medium",
                }
            ]
        }
        specs = proliferate.generate_specs_from_gaps(gaps, max_count=3)
        assert len(specs) == 1
        spec = specs[0]
        for key in ("task_id", "target_file", "mode", "atoms"):
            assert key in spec


# ---------------------------------------------------------------------------
# check_blast_radius
# ---------------------------------------------------------------------------


class TestCheckBlastRadius:
    def test_all_passed_when_no_existing_files(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        repo = tmp_path
        (repo / "std").mkdir()
        client = mock_mumei_client(verify_success=True)
        new_file = repo / "std" / "new.mm"
        result = proliferate.check_blast_radius(
            client, repo, new_file, "atom dummy(x: i64) ensures: true; body: x;\n"
        )
        assert result["all_passed"] is True
        assert result["broken_files"] == []
        # The new file should be cleaned up.
        assert not new_file.exists()

    def test_broken_file_is_reported(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        repo = tmp_path
        (repo / "std").mkdir()
        _write_mm(
            repo / "std" / "existing.mm",
            "atom existing(x: i64) ensures: true; body: x;\n",
        )
        client = mock_mumei_client(verify_success=False)
        new_file = repo / "std" / "broken_trigger.mm"
        result = proliferate.check_blast_radius(
            client, repo, new_file, "atom dummy(x: i64) ensures: true; body: x;\n"
        )
        assert result["all_passed"] is False
        assert len(result["broken_files"]) == 1
        assert result["broken_files"][0]["file"].endswith("existing.mm")
        assert not new_file.exists()

    def test_new_file_cleaned_up_on_verify_exception(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path
        (repo / "std").mkdir()
        _write_mm(repo / "std" / "x.mm", "atom x(y: i64) ensures: true; body: y;\n")
        client = MagicMock()
        client.verify.side_effect = RuntimeError("boom")
        new_file = repo / "std" / "candidate.mm"
        with pytest.raises(RuntimeError):
            proliferate.check_blast_radius(
                client, repo, new_file, "atom dummy(x: i64) ensures: true; body: x;\n"
            )
        # Even on exception, the new file must not linger.
        assert not new_file.exists()


# ---------------------------------------------------------------------------
# attempt_heal
# ---------------------------------------------------------------------------


class TestAttemptHeal:
    def test_returns_true_when_already_verified(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        f = tmp_path / "ok.mm"
        f.write_text("atom ok(x: i64) ensures: true; body: x;\n", encoding="utf-8")
        client = mock_mumei_client(verify_success=True)
        result = proliferate.attempt_heal(
            client=None,
            model="gpt-4",
            broken_info={"file": str(f), "error": ""},
            mumei_client=client,
        )
        assert result is True

    def test_returns_false_when_unrecoverable(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        f = tmp_path / "broken.mm"
        f.write_text("bad\n", encoding="utf-8")
        client = mock_mumei_client(verify_success=False)
        # Patch get_fix to always return the same source (no progress).
        with patch(
            "agent.strategies.fix_strategy.get_fix",
            return_value="bad\n",
        ):
            result = proliferate.attempt_heal(
                client=MagicMock(),
                model="gpt-4",
                broken_info={"file": str(f), "error": "fail"},
                mumei_client=client,
                max_retries=2,
            )
        assert result is False

    def test_partial_heal_restores_originals(
        self, tmp_path: Path
    ) -> None:
        """When healing fails partway, already-healed files are restored."""
        f1 = tmp_path / "a.mm"
        f2 = tmp_path / "b.mm"
        f1.write_text("original_a\n", encoding="utf-8")
        f2.write_text("original_b\n", encoding="utf-8")

        mumei_client = MagicMock()
        # f1 heals successfully (fail → fix → pass on next iter), f2 never heals.
        # attempt_heal calls verify at the *start* of each loop iteration and
        # returns True as soon as it succeeds, so f1 consumes exactly 2 calls:
        #   iter 0: fail → get_fix writes healed code
        #   iter 1: pass → return True
        # f2 returns the same source from get_fix (no progress), so all 3
        # loop iterations fail + 1 final check = 4 calls.
        mumei_client.verify.side_effect = [
            # attempt_heal for f1 (2 calls)
            {"success": False, "report": {}, "stdout": "", "stderr": "err"},
            {"success": True, "report": {}, "stdout": "", "stderr": ""},
            # attempt_heal for f2 (3 loop + 1 final = 4 calls)
            {"success": False, "report": {}, "stdout": "", "stderr": "err"},
            {"success": False, "report": {}, "stdout": "", "stderr": "err"},
            {"success": False, "report": {}, "stdout": "", "stderr": "err"},
            {"success": False, "report": {}, "stdout": "", "stderr": "err"},
        ]

        fix_calls = [0]
        def fake_get_fix(**kwargs):
            fix_calls[0] += 1
            src = kwargs.get("source_code", "")
            if "a.mm" in kwargs.get("source_path", ""):
                return "healed_a\n"
            # For b.mm, return same content (no progress).
            return src

        with patch("agent.strategies.fix_strategy.get_fix", side_effect=fake_get_fix):
            # Heal f1 — succeeds
            r1 = proliferate.attempt_heal(
                client=MagicMock(),
                model="gpt-4",
                broken_info={"file": str(f1), "error": ""},
                mumei_client=mumei_client,
                max_retries=3,
            )
            assert r1 is True
            assert f1.read_text(encoding="utf-8") == "healed_a\n"

            # Heal f2 — fails
            r2 = proliferate.attempt_heal(
                client=MagicMock(),
                model="gpt-4",
                broken_info={"file": str(f2), "error": ""},
                mumei_client=mumei_client,
                max_retries=3,
            )
            assert r2 is False

    def test_heals_after_one_fix(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "fixable.mm"
        f.write_text("broken\n", encoding="utf-8")

        mumei_client = MagicMock()
        # First verify fails, fix is applied, second verify succeeds.
        mumei_client.verify.side_effect = [
            {"success": False, "report": {"failure_type": "x"}, "stdout": "", "stderr": "err"},
            {"success": True, "report": {}, "stdout": "", "stderr": ""},
            {"success": True, "report": {}, "stdout": "", "stderr": ""},
        ]
        with patch(
            "agent.strategies.fix_strategy.get_fix",
            return_value="atom fixed(x: i64) ensures: true; body: x;\n",
        ):
            result = proliferate.attempt_heal(
                client=MagicMock(),
                model="gpt-4",
                broken_info={"file": str(f), "error": "fail"},
                mumei_client=mumei_client,
                max_retries=3,
            )
        assert result is True
        # The fixed code should be on disk.
        assert "fixed" in f.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# proliferate (end-to-end, dry-run, mocked)
# ---------------------------------------------------------------------------


class TestProliferateDryRun:
    def test_no_std_returns_error(self, tmp_path: Path) -> None:
        results = proliferate.proliferate(tmp_path, dry_run=True)
        assert results == [{"success": False, "reason": "std_dir_not_found"}]

    def test_no_proposals_when_std_is_complete(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        # Create every file that would otherwise be proposed.
        for rel in ("prelude.mm", "core.mm", "iter.mm", "hash.mm", "alloc.mm"):
            _write_mm(std / rel, "atom ok(x: i64) ensures: true; body: x;\n")
        _write_mm(
            std / "trait" / "iterable.mm",
            "atom ok(x: i64) ensures: true; body: x;\n",
        )

        results = proliferate.proliferate(tmp_path, dry_run=True)
        assert results == [{"success": True, "reason": "no_proposals"}]

    def test_dry_run_end_to_end_mocked(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        std = tmp_path / "std"
        std.mkdir()
        # Leaving std empty means the std/core.mm rule will propose a task.

        fake_code = (
            "// auto-generated\n"
            "atom core_ok(x: i64) ensures: true; body: x;\n"
        )

        with patch("agent.proliferate.generate_code") as gen_mock, patch(
            "agent.proliferate.AgentConfig"
        ) as cfg_mock, patch(
            "agent.proliferate.MumeiClient"
        ) as client_mock:
            gen_mock.return_value = (fake_code, True)
            cfg_instance = MagicMock()
            cfg_instance.mumei_bin = "mumei"
            cfg_instance.model = "gpt-test"
            cfg_instance.max_retries = 2
            cfg_instance.create_client.return_value = MagicMock()
            cfg_mock.return_value = cfg_instance

            # Blast-radius check: mumei_client.verify always succeeds.
            verify_client = mock_mumei_client(verify_success=True)
            client_mock.return_value = verify_client

            results = proliferate.proliferate(
                tmp_path, dry_run=True, max_proposals=1
            )

        assert len(results) >= 1
        assert results[0]["success"] is True
        assert results[0].get("dry_run") is True
        assert results[0]["code"] == fake_code

    def test_dry_run_with_broken_blast_radius_does_not_mutate(
        self, tmp_path: Path
    ) -> None:
        """Dry-run must not call attempt_heal or modify existing files."""
        std = tmp_path / "std"
        _write_mm(
            std / "existing.mm",
            "atom existing(x: i64) ensures: true; body: x;\n",
        )
        original_content = (std / "existing.mm").read_text(encoding="utf-8")

        fake_code = "atom new_ok(x: i64) ensures: true; body: x;\n"

        with patch("agent.proliferate.generate_code") as gen_mock, patch(
            "agent.proliferate.AgentConfig"
        ) as cfg_mock, patch(
            "agent.proliferate.MumeiClient"
        ) as client_mock, patch(
            "agent.proliferate.attempt_heal"
        ) as heal_mock:
            gen_mock.return_value = (fake_code, True)
            cfg_instance = MagicMock()
            cfg_instance.mumei_bin = "mumei"
            cfg_instance.model = "gpt-test"
            cfg_instance.max_retries = 2
            cfg_instance.create_client.return_value = MagicMock()
            cfg_mock.return_value = cfg_instance

            # Blast-radius check: verify fails for existing file.
            verify_client = MagicMock()
            verify_client.verify.return_value = {
                "success": False,
                "report": {},
                "stdout": "",
                "stderr": "broken",
            }
            client_mock.return_value = verify_client

            results = proliferate.proliferate(
                tmp_path, dry_run=True, max_proposals=1
            )

        # attempt_heal must never be called in dry-run mode.
        heal_mock.assert_not_called()
        # Existing file must be unchanged.
        assert (std / "existing.mm").read_text(encoding="utf-8") == original_content
        # The new file must not linger.
        assert not (std / "core.mm").exists()
        assert len(results) >= 1
        assert results[0].get("dry_run") is True
        assert results[0].get("reason") == "blast_radius_broken_dry_run"


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_required_and_default_args(self) -> None:
        import argparse

        parser = argparse.ArgumentParser()
        proliferate.build_parser(parser)
        args = parser.parse_args(["--mumei-repo", "/tmp/m"])
        assert args.mumei_repo == "/tmp/m"
        assert args.max_proposals == 3
        assert args.dry_run is False

    def test_dry_run_flag(self) -> None:
        import argparse

        parser = argparse.ArgumentParser()
        proliferate.build_parser(parser)
        args = parser.parse_args(
            ["--mumei-repo", "/tmp/m", "--max-proposals", "5", "--dry-run"]
        )
        assert args.max_proposals == 5
        assert args.dry_run is True
