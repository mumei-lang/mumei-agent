"""Unit tests for ``agent.proliferate`` — SI-5 Phase 2-C.

These tests exercise the pure-Python helpers of the proliferation
pipeline.  The LLM-dependent steps (``generate_code``, ``publish``) are
mocked so the tests stay hermetic — no network, no mumei binary.
"""
from __future__ import annotations

import argparse
import json
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

    def test_math_abs_rule_triggers_when_missing(self, tmp_path: Path) -> None:
        """std/math/abs.mm should be a candidate proposal when absent."""
        std = tmp_path / "std"
        std.mkdir()
        abs_rule = next(
            r for r in proliferate._STD_GAP_RULES if r["target"] == "std/math/abs.mm"
        )
        assert proliferate._evaluate_rule(abs_rule, set(), std) is True
        # And once the file exists, the rule must no longer trigger.
        _write_mm(
            std / "math" / "abs.mm",
            "atom abs_i64(x: i64) ensures: true; body: x;\n",
        )
        existing = {"std/math/abs.mm"}
        assert proliferate._evaluate_rule(abs_rule, existing, std) is False

    def test_math_pow_rule_requires_core_present(self, tmp_path: Path) -> None:
        """std/math/pow.mm must only be proposed when std/core.mm exists."""
        std = tmp_path / "std"
        std.mkdir()
        pow_rule = next(
            r for r in proliferate._STD_GAP_RULES if r["target"] == "std/math/pow.mm"
        )
        # Without core.mm present, requires_present fails.
        assert proliferate._evaluate_rule(pow_rule, set(), std) is False
        # With core.mm present and pow.mm missing, the rule triggers.
        assert (
            proliferate._evaluate_rule(pow_rule, {"std/core.mm"}, std) is True
        )
        # With pow.mm already present, the rule no longer triggers.
        assert (
            proliferate._evaluate_rule(
                pow_rule, {"std/core.mm", "std/math/pow.mm"}, std
            )
            is False
        )

    def test_binary_heap_rule_requires_bounded_array(self, tmp_path: Path) -> None:
        """std/container/binary_heap.mm must wait for bounded_array.mm."""
        std = tmp_path / "std"
        std.mkdir()
        heap_rule = next(
            r
            for r in proliferate._STD_GAP_RULES
            if r["target"] == "std/container/binary_heap.mm"
        )
        assert proliferate._evaluate_rule(heap_rule, set(), std) is False
        assert (
            proliferate._evaluate_rule(
                heap_rule, {"std/container/bounded_array.mm"}, std
            )
            is True
        )

    def test_low_difficulty_math_rules_rank_before_medium(
        self, tmp_path: Path
    ) -> None:
        """Low-difficulty math gaps should outrank medium-difficulty ones.

        With std/core.mm present, abs / safe_div / safe_mul (difficulty="low",
        fully satisfied deps) should rank ahead of ring_buffer / hash
        ("medium") and fill the top-3 cap.
        """
        std = tmp_path / "std"
        _write_mm(
            std / "core.mm",
            "atom core_ok(x: i64) ensures: true; body: x;\n",
        )
        result = proliferate.analyze_gaps(std)
        names = [p["name"] for p in result["proposals"]]
        assert set(names) == {
            "std/math/abs.mm",
            "std/math/safe_div.mm",
            "std/math/safe_mul.mm",
        }
        # All three winners must have difficulty "low".
        assert all(p["difficulty"] == "low" for p in result["proposals"])
        # Priorities assigned in order 1..3.
        assert [p["priority"] for p in result["proposals"]] == [1, 2, 3]

    def test_pow_surfaces_after_low_math_rules_are_filled(
        self, tmp_path: Path
    ) -> None:
        """Once abs/safe_div/safe_mul exist, pow should become a proposal."""
        std = tmp_path / "std"
        for rel in (
            "core.mm",
            "math/abs.mm",
            "math/safe_div.mm",
            "math/safe_mul.mm",
        ):
            _write_mm(
                std / rel,
                f"atom placeholder_{rel.replace('/', '_').replace('.mm', '')}"
                "(x: i64) ensures: true; body: x;\n",
            )
        result = proliferate.analyze_gaps(std)
        names = {p["name"] for p in result["proposals"]}
        assert "std/math/pow.mm" in names


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
# forge optimisation helpers
# ---------------------------------------------------------------------------


class TestForgeOptimisationHelpers:
    def test_forge_cache_path_uses_ignored_mumei_dir(self, tmp_path: Path) -> None:
        assert proliferate._forge_cache_path(tmp_path) == (
            tmp_path / ".mumei" / "proliferate_forge_cache.json"
        )

    def test_detect_diffs_reports_unchanged_and_changed(self, tmp_path: Path) -> None:
        target = tmp_path / "std" / "math" / "extended.mm"
        _write_mm(target, "atom same(x: i64) ensures: true; body: x;\n")

        same = proliferate._detect_diffs(
            tmp_path,
            "std/math/extended.mm",
            target.read_text(encoding="utf-8"),
        )
        assert same["exists"] is True
        assert same["changed"] is False
        assert same["old_sha256"] == same["new_sha256"]

        changed = proliferate._detect_diffs(
            tmp_path,
            "std/math/extended.mm",
            "atom other(x: i64) ensures: true; body: x;\n",
        )
        assert changed["changed"] is True
        assert changed["old_sha256"] != changed["new_sha256"]

    def test_cache_results_round_trips_verified_code(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "cache.json"
        spec = {"task_id": "vstd-x", "target_file": "std/x.mm"}
        code = "atom x(y: i64) ensures: true; body: y;\n"

        assert proliferate._cache_results(cache_path, spec) is None
        proliferate._cache_results(
            cache_path,
            spec,
            {"code": code, "verified": True},
        )
        cached = proliferate._cache_results(cache_path, spec)
        assert cached is not None
        assert cached["code"] == code
        assert cached["verified"] is True

    def test_cache_key_tracks_context_file_changes(self, tmp_path: Path) -> None:
        _write_mm(tmp_path / "std" / "core.mm", "atom a(x: i64) ensures: true; body: x;\n")
        spec = {
            "task_id": "vstd-x",
            "target_file": "std/x.mm",
            "context_files": ["std/core.mm"],
        }

        before = proliferate._spec_cache_key(spec, tmp_path)
        _write_mm(tmp_path / "std" / "core.mm", "atom b(x: i64) ensures: true; body: x;\n")

        assert proliferate._spec_cache_key(spec, tmp_path) != before

    def test_parallel_forge_preserves_order_and_uses_cache(self, tmp_path: Path) -> None:
        specs = [
            {"task_id": "vstd-a", "target_file": "std/a.mm"},
            {"task_id": "vstd-b", "target_file": "std/b.mm"},
        ]
        cache_path = tmp_path / "cache.json"
        proliferate._cache_results(
            cache_path,
            specs[0],
            {"code": "atom a(x: i64) ensures: true; body: x;\n", "verified": True},
        )
        config = MagicMock()
        config.model = "gpt-test"
        config.max_retries = 2
        config.create_client.return_value = MagicMock()
        harness = proliferate.HarnessMetrics.from_profile("basic")

        def fake_generate_code(**kwargs):
            spec = kwargs["spec"]
            name = spec["target_file"].split("/")[-1].replace(".mm", "")
            return f"atom {name}(x: i64) ensures: true; body: x;\n", True

        with patch("agent.proliferate.generate_code", side_effect=fake_generate_code) as gen_mock:
            results = proliferate._parallel_forge(
                specs,
                config=config,
                mumei_client=MagicMock(),
                harness_metrics=harness,
                cache_path=cache_path,
                max_workers=2,
            )

        assert [r["spec"]["task_id"] for r in results] == ["vstd-a", "vstd-b"]
        assert results[0]["cache_hit"] is True
        assert results[1]["verified"] is True
        gen_mock.assert_called_once()


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
        # iter 0: verify fails → get_fix writes fixed code
        # iter 1: verify succeeds → return True  (2 calls total)
        mumei_client.verify.side_effect = [
            {"success": False, "report": {"failure_type": "x"}, "stdout": "", "stderr": "err"},
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
        for rel in (
            "prelude.mm",
            "core.mm",
            "iter.mm",
            "hash.mm",
            "alloc.mm",
            "math/abs.mm",
            "math/safe_div.mm",
            "math/safe_mul.mm",
            "math/pow.mm",
            "math/factorial.mm",
            "math/fibonacci.mm",
            "math/extended.mm",
            "math/extended.mm",
            "math/extended.mm",
            "container/ring_buffer.mm",
            "container/binary_heap.mm",
            "crypto/hash.mm",
            "crypto/primitives.mm",
            "container/bounded_array.mm",
            "string_utils.mm",
            "crypto/hash.mm",
            "crypto/primitives.mm",
            "container/sorted_map.mm",
            "string_utils.mm",
            "crypto/hash.mm",
            "crypto/primitives.mm",
            "string/validator.mm",
            "string_utils.mm",
        ):
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
            "agent.proliferate.create_mumei_client"
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

    def test_dry_run_lean_fallback_verify_exception_is_best_effort(
        self, tmp_path: Path
    ) -> None:
        std = tmp_path / "std"
        std.mkdir()
        summary_path = tmp_path / "summary.json"
        fake_code = "atom core_ok(x: i64) ensures: true; body: x;\n"

        with patch("agent.proliferate.generate_code") as gen_mock, patch(
            "agent.proliferate.AgentConfig"
        ) as cfg_mock, patch(
            "agent.proliferate.create_mumei_client"
        ) as client_mock, patch(
            "agent.proliferate._run_lean_fallback"
        ) as fallback_mock:
            gen_mock.return_value = (fake_code, True)
            cfg_instance = MagicMock()
            cfg_instance.mumei_bin = "mumei"
            cfg_instance.model = "gpt-test"
            cfg_instance.max_retries = 2
            cfg_instance.mumei_lean_repo = "/tmp/mumei-lean"
            cfg_instance.create_client.return_value = MagicMock()
            cfg_mock.return_value = cfg_instance

            verify_client = MagicMock()
            verify_client.verify.side_effect = FileNotFoundError("mumei")
            client_mock.return_value = verify_client

            results = proliferate.proliferate(
                tmp_path,
                dry_run=True,
                max_proposals=1,
                output_json=summary_path,
                enable_lean_fallback=True,
            )

        assert results[0]["success"] is True
        assert results[0].get("dry_run") is True
        assert "publish_result" not in results[0]
        fallback_mock.assert_called_once()
        assert summary_path.exists()
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        assert data["details"][0]["success"] is True

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
            "agent.proliferate.create_mumei_client"
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
        parser = argparse.ArgumentParser()
        proliferate.build_parser(parser)
        args = parser.parse_args(["--mumei-repo", "/tmp/m"])
        assert args.mumei_repo == "/tmp/m"
        assert args.max_proposals == 3
        assert args.dry_run is False
        assert args.output_json is None
        assert args.enable_lean_fallback is True

    def test_disable_lean_fallback_flag(self) -> None:
        parser = argparse.ArgumentParser()
        proliferate.build_parser(parser)
        args = parser.parse_args(
            ["--mumei-repo", "/tmp/m", "--disable-lean-fallback"]
        )
        assert args.enable_lean_fallback is False

    def test_enable_self_correction_flag(self) -> None:
        parser = argparse.ArgumentParser()
        proliferate.build_parser(parser)
        args = parser.parse_args(
            ["--mumei-repo", "/tmp/m", "--enable-self-correction"]
        )
        assert args.enable_self_correction is True

    def test_dry_run_flag(self) -> None:
        parser = argparse.ArgumentParser()
        proliferate.build_parser(parser)
        args = parser.parse_args(
            ["--mumei-repo", "/tmp/m", "--max-proposals", "5", "--dry-run"]
        )
        assert args.max_proposals == 5
        assert args.dry_run is True

    def test_output_json_flag(self) -> None:
        parser = argparse.ArgumentParser()
        proliferate.build_parser(parser)
        args = parser.parse_args(
            ["--mumei-repo", "/tmp/m", "--output-json", "/tmp/summary.json"]
        )
        assert args.output_json == "/tmp/summary.json"

    def test_lean_fallback_flag_passed_to_proliferate(self) -> None:
        parser = argparse.ArgumentParser()
        proliferate.build_parser(parser)
        args = parser.parse_args(
            [
                "--mumei-repo",
                "/tmp/m",
                "--enable-lean-fallback",
            ]
        )

        with patch("agent.proliferate.proliferate", return_value=[]) as run_mock:
            proliferate.main(args)

        run_mock.assert_called_once_with(
            mumei_repo_dir="/tmp/m",
            max_proposals=3,
            dry_run=False,
            mumei_bin=None,
            output_json=None,
            enable_lean_fallback=True,
        )


# ---------------------------------------------------------------------------
# SI-5 Phase 3-B: PR body helper + JSON run summary
# ---------------------------------------------------------------------------


class TestBuildPrBodyExtra:
    def test_includes_marker_and_proposal(self) -> None:
        spec = {"target_file": "std/iter.mm"}
        proposal = {
            "name": "std/iter.mm",
            "reason": "Collection traversal common interface.",
            "difficulty": "medium",
            "depends_on": ["std/prelude.mm"],
            "priority": 1,
        }
        body = proliferate._build_pr_body_extra(
            spec=spec, proposal=proposal, health_before=None, health_after=None
        )
        assert "[SI-5 Autonomous Proliferation]" in body
        assert "std/iter.mm" in body
        assert "Collection traversal" in body
        assert "`medium`" in body
        assert "`std/prelude.mm`" in body

    def test_includes_health_delta_when_both_snapshots_given(self) -> None:
        spec = {"target_file": "std/core.mm"}
        health_before = {
            "health_score": 0.80,
            "verified_files": 3,
            "total_files": 5,
            "trusted_atoms": 4,
        }
        health_after = {
            "health_score": 0.90,
            "verified_files": 4,
            "total_files": 5,
            "trusted_atoms": 3,
        }
        body = proliferate._build_pr_body_extra(
            spec=spec,
            proposal=None,
            health_before=health_before,
            health_after=health_after,
        )
        assert "0.800" in body and "0.900" in body
        assert "+0.100" in body
        assert "3/5" in body and "4/5" in body

    def test_omits_health_section_when_missing(self) -> None:
        body = proliferate._build_pr_body_extra(
            spec={"target_file": "std/core.mm"},
            proposal=None,
            health_before=None,
            health_after=None,
        )
        assert "Proof health" not in body
        # Verification summary is always included.
        assert "Verification summary" in body

    def test_shows_baseline_when_only_health_before(self) -> None:
        health_before = {
            "health_score": 0.75,
            "verified_files": 3,
            "total_files": 4,
            "trusted_atoms": 2,
        }
        body = proliferate._build_pr_body_extra(
            spec={"target_file": "std/core.mm"},
            proposal=None,
            health_before=health_before,
            health_after=None,
        )
        assert "pre-run baseline" in body
        assert "0.750" in body
        assert "3/4" in body
        assert "trusted atoms: 2" in body
        # Should NOT contain delta arrow since post-health is absent.
        assert "→" not in body


class TestJsonifyResult:
    def test_code_is_replaced_with_length(self) -> None:
        result = {
            "spec": {"task_id": "t1", "target_file": "std/x.mm", "mode": "create"},
            "code": "atom x(y: i64) ensures: true; body: y;\n",
            "success": True,
        }
        out = proliferate._jsonify_result(result)
        assert "code" not in out
        assert out["code_length"] == len(result["code"])
        assert out["spec"] == {
            "task_id": "t1",
            "target_file": "std/x.mm",
            "mode": "create",
        }
        assert out["success"] is True

    def test_unknown_fields_are_preserved(self) -> None:
        result = {"reason": "no_proposals", "success": True}
        out = proliferate._jsonify_result(result)
        assert out == {"reason": "no_proposals", "success": True}


class TestOutputJson:
    def test_lean_fallback_summary_in_output_json(self, tmp_path: Path) -> None:
        out_path = tmp_path / "summary.json"
        lean_fallback = {
            "attempted": True,
            "unknown_count": 2,
            "proved": 1,
            "bridge": "mumei-lean",
        }

        proliferate._write_output_json(
            out_path,
            started_at="2026-05-02T10:00:00+00:00",
            pre_health=None,
            post_health=None,
            results=[
                {
                    "success": True,
                    "reason": "published",
                    "lean_fallback": lean_fallback,
                }
            ],
            dry_run=False,
        )

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["details"][0]["lean_fallback"] == lean_fallback
        assert data["lean_fallback_attempted"] == 2
        assert data["lean_fallback_proved"] == 1
        assert data["lean_fallback_failed"] == 1
        assert data["lean_fallback_success_rate"] == 0.5
        metrics = data["lean_fallback_metrics"]
        assert metrics["lean_fallback_attempted"] == 2
        assert metrics["lean_fallback_proved"] == 1
        assert metrics["lean_fallback_failed"] == 1
        assert metrics["lean_fallback_success_rate"] == 0.5
        assert metrics["lean_fallback_attempted_specs"] == 1
        assert metrics["lean_fallback_error_code_counts"] == {}
        assert metrics["lean_fallback_duration_seconds"]["count"] == 0

    def test_no_std_writes_summary_json(self, tmp_path: Path) -> None:
        out_path = tmp_path / "summary.json"
        proliferate.proliferate(
            tmp_path / "does-not-exist",
            dry_run=True,
            output_json=out_path,
        )

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["proposals_processed"] == 1
        assert data["proposals_succeeded"] == 0
        assert data["dry_run"] is True
        assert "timestamp" in data
        assert data["details"][0]["reason"] == "std_dir_not_found"

    def test_no_proposals_writes_summary_json(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        for rel in (
            "prelude.mm",
            "core.mm",
            "iter.mm",
            "hash.mm",
            "alloc.mm",
            "math/abs.mm",
            "math/safe_div.mm",
            "math/safe_mul.mm",
            "math/pow.mm",
            "math/factorial.mm",
            "math/fibonacci.mm",
            "math/extended.mm",
            "container/ring_buffer.mm",
            "container/binary_heap.mm",
            "container/bounded_array.mm",
            "container/sorted_map.mm",
            "crypto/hash.mm",
            "crypto/primitives.mm",
            "string/validator.mm",
            "string_utils.mm",
        ):
            _write_mm(std / rel, "atom ok(x: i64) ensures: true; body: x;\n")
        _write_mm(
            std / "trait" / "iterable.mm",
            "atom ok(x: i64) ensures: true; body: x;\n",
        )
        out_path = tmp_path / "logs" / "summary.json"
        proliferate.proliferate(
            tmp_path,
            dry_run=True,
            output_json=out_path,
        )

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["proposals_processed"] == 1
        assert data["proposals_succeeded"] == 1
        assert data["details"][0]["reason"] == "no_proposals"

    def test_missing_output_json_is_noop(self, tmp_path: Path) -> None:
        # Should not raise when output_json=None (default).
        results = proliferate.proliferate(
            tmp_path / "does-not-exist",
            dry_run=True,
        )
        assert results[0]["reason"] == "std_dir_not_found"


class TestOtelSloStatus:
    """P15 operational alerts / SLO layer — otel_slo_status in summary.json."""

    def test_otel_slo_status_none_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Default path: OTEL disabled -> otel_slo_status is present but None,
        # and every pre-existing summary.json field is unchanged.
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
        out_path = tmp_path / "summary.json"
        proliferate._write_output_json(
            out_path,
            started_at="2026-07-05T10:00:00+00:00",
            pre_health=None,
            post_health=None,
            results=[{"success": True, "reason": "published"}],
            dry_run=False,
        )
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert "otel_slo_status" in data
        assert data["otel_slo_status"] is None
        # Backward-compat: existing fields still present.
        assert data["proposals_processed"] == 1
        assert data["proposals_succeeded"] == 1
        assert data["health_delta"] is None

    def test_default_proliferate_summary_has_null_slo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # End-to-end default run (OTEL unset) writes otel_slo_status=None.
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
        out_path = tmp_path / "summary.json"
        proliferate.proliferate(
            tmp_path / "does-not-exist",
            dry_run=True,
            output_json=out_path,
        )
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["otel_slo_status"] is None

    def test_otel_slo_status_flags_low_first_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # When OTEL is enabled, the helper derives the first-pass rate and
        # flags an SLO violation below the warning threshold.
        monkeypatch.setattr(proliferate.telemetry, "is_enabled", lambda: True)
        status = proliferate._collect_otel_slo_status(
            succeeded=1,
            processed=4,
            harness_metrics=None,
        )
        assert status is not None
        assert status["otel_enabled"] is True
        assert status["first_pass_success_rate"] == 0.25
        assert status["slo_met"] is False
        assert "first_pass_success_rate:critical" in status["violations"]

    def test_otel_slo_status_met_when_healthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(proliferate.telemetry, "is_enabled", lambda: True)
        status = proliferate._collect_otel_slo_status(
            succeeded=4,
            processed=4,
            harness_metrics=None,
        )
        assert status is not None
        assert status["first_pass_success_rate"] == 1.0
        assert status["violations"] == []
        assert status["slo_met"] is True

    def test_otel_slo_status_none_when_disabled_helper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(proliferate.telemetry, "is_enabled", lambda: False)
        assert (
            proliferate._collect_otel_slo_status(
                succeeded=0, processed=0, harness_metrics=None
            )
            is None
        )


# ---------------------------------------------------------------------------
# Task 2-A — auto-close on health regression + model field in summary JSON
# ---------------------------------------------------------------------------


class TestHealthRegressionAutoClose:
    """Verify that proliferate marks PRs for auto-close when proof-health
    regresses across the run, and that the summary JSON records the LLM
    model used for traceability."""

    def test_proliferate_skips_pr_on_health_regression(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange: mock health_before > health_after so the post-loop
        # gate flips ``should_close_pr=True`` on every result and any
        # already-published PR is closed via gh.
        std = tmp_path / "std"
        std.mkdir()
        fake_code = "atom core_ok(x: i64) ensures: true; body: x;\n"

        health_before = {
            "health_score": 0.90,
            "verified_files": 9,
            "total_files": 10,
            "trusted_atoms": 0,
        }
        health_after = {
            "health_score": 0.50,
            "verified_files": 5,
            "total_files": 10,
            "trusted_atoms": 0,
        }
        health_calls: list[Path] = []

        def _measure_health_stub(_client, std_dir: Path) -> dict[str, Any]:
            health_calls.append(std_dir)
            return health_before if len(health_calls) == 1 else health_after

        # Insert a stub module so ``from agent.std_health import
        # measure_health`` returns our fake without touching the real
        # mumei binary.
        import sys as _sys
        import types as _types

        stub = _types.ModuleType("agent.std_health")
        stub.measure_health = _measure_health_stub  # type: ignore[attr-defined]
        monkeypatch.setitem(_sys.modules, "agent.std_health", stub)

        close_calls: list[tuple[str, float]] = []

        def _close_stub(pr_url: str, delta: float) -> bool:
            close_calls.append((pr_url, delta))
            return True

        monkeypatch.setattr(
            proliferate, "_close_pr_for_regression", _close_stub
        )

        with patch("agent.proliferate.generate_code") as gen_mock, patch(
            "agent.proliferate.AgentConfig"
        ) as cfg_mock, patch(
            "agent.proliferate.create_mumei_client"
        ) as client_mock, patch(
            "agent.proliferate.publish"
        ) as publish_mock:
            gen_mock.return_value = (fake_code, True)
            cfg_instance = MagicMock()
            cfg_instance.mumei_bin = "mumei"
            cfg_instance.model = "gpt-test"
            cfg_instance.max_retries = 2
            cfg_instance.create_client.return_value = MagicMock()
            cfg_mock.return_value = cfg_instance
            verify_client = MagicMock()
            verify_client.verify.return_value = {
                "success": True,
                "report": {},
                "stdout": "",
                "stderr": "",
            }
            client_mock.return_value = verify_client
            publish_mock.return_value = {
                "success": True,
                "pr_url": "https://github.com/mumei-lang/mumei/pull/999",
            }

            results = proliferate.proliferate(
                tmp_path, dry_run=False, max_proposals=1
            )

        # Assert: regression detection populates auto-close fields on
        # the result and triggers the gh-backed close helper.
        assert results, "expected at least one result"
        first = results[0]
        assert first.get("should_close_pr") is True
        assert first.get("pr_closed") is True
        assert first.get("health_delta") is not None
        assert first["health_delta"] < 0
        assert close_calls and close_calls[0][0].endswith("/pull/999")

    def test_output_json_includes_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange: LLM_MODEL must be reflected in summary JSON so
        # operators can correlate per-run health/success metrics with
        # the model that produced them.
        monkeypatch.setenv("LLM_MODEL", "qwen3.5:4b")
        out_path = tmp_path / "summary.json"
        proliferate.proliferate(
            tmp_path / "does-not-exist",
            dry_run=True,
            output_json=out_path,
        )

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["model"] == "qwen3.5:4b"

    def test_output_json_model_defaults_to_agent_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # When LLM_MODEL is unset, the summary JSON must record the
        # actual default ``AgentConfig`` would use for LLM calls
        # (currently ``"gpt-4o"``) rather than a misleading literal
        # ``"unknown"`` — operators rely on this field as an audit
        # trail of which model produced the run.
        monkeypatch.delenv("LLM_MODEL", raising=False)
        out_path = tmp_path / "summary.json"
        proliferate.proliferate(
            tmp_path / "does-not-exist",
            dry_run=True,
            output_json=out_path,
        )

        from agent.config import AgentConfig

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["model"] == AgentConfig().model
