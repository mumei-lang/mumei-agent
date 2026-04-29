"""Unit tests for ``agent.propose`` — Phase 2-A forge task proposer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent import propose


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_GAPS_JSON = FIXTURES_DIR / "sample_gaps.json"


def _load_sample_gaps() -> dict:
    return json.loads(SAMPLE_GAPS_JSON.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Pure-function behaviour
# ---------------------------------------------------------------------------


class TestDifficultyRetries:
    def test_low_difficulty_maps_to_3(self) -> None:
        assert propose._resolve_max_retries("low") == 3

    def test_medium_difficulty_maps_to_5(self) -> None:
        assert propose._resolve_max_retries("medium") == 5

    def test_high_difficulty_maps_to_8(self) -> None:
        assert propose._resolve_max_retries("high") == 8

    def test_unknown_difficulty_defaults_to_medium(self) -> None:
        assert propose._resolve_max_retries("extreme") == 5

    def test_missing_difficulty_defaults_to_medium(self) -> None:
        assert propose._resolve_max_retries(None) == 5

    def test_difficulty_is_case_insensitive(self) -> None:
        assert propose._resolve_max_retries("LOW") == 3
        assert propose._resolve_max_retries("High") == 8


class TestImportPreamble:
    def test_single_depends_on(self) -> None:
        preamble = propose._build_import_preamble(["std/prelude.mm"])
        assert preamble == 'import "std/prelude" as prelude;'

    def test_multiple_depends_on(self) -> None:
        preamble = propose._build_import_preamble(
            ["std/core.mm", "std/prelude.mm"],
        )
        assert 'import "std/core" as core;' in preamble
        assert 'import "std/prelude" as prelude;' in preamble

    def test_duplicate_depends_on_deduped(self) -> None:
        preamble = propose._build_import_preamble(
            ["std/core.mm", "std/core.mm"],
        )
        assert preamble.count('import "std/core" as core;') == 1

    def test_empty_depends_on(self) -> None:
        assert propose._build_import_preamble([]) == ""

    def test_non_mm_paths_accepted(self) -> None:
        preamble = propose._build_import_preamble(["std/util"])
        assert preamble == 'import "std/util" as util;'


# ---------------------------------------------------------------------------
# Spec construction
# ---------------------------------------------------------------------------


class TestBuildSpecFromProposal:
    def test_minimal_spec_fields_present(self) -> None:
        proposal = {
            "name": "std/iter.mm",
            "reason": "iter interface",
            "depends_on": ["std/prelude.mm"],
            "difficulty": "medium",
        }
        spec = propose.build_spec_from_proposal(proposal)
        # Required fields for the forge runner.
        for key in ("task_id", "target_file", "mode", "atoms", "max_retries"):
            assert key in spec
        assert spec["target_file"] == "std/iter.mm"
        assert spec["mode"] == "create"
        assert spec["task_id"] == "vstd-iter"
        assert spec["max_retries"] == 5
        assert spec["source"] == "analyze_std_gaps"

    def test_depends_on_generates_import_preamble(self) -> None:
        proposal = {
            "name": "std/iter.mm",
            "reason": "iter interface",
            "depends_on": ["std/prelude.mm"],
            "difficulty": "medium",
        }
        spec = propose.build_spec_from_proposal(proposal)
        assert spec["depends_on"] == ["std/prelude.mm"]
        assert spec["context_files"] == ["std/prelude.mm"]
        assert 'import "std/prelude" as prelude;' in spec["import_preamble"]

    def test_difficulty_scales_max_retries(self) -> None:
        for difficulty, expected in (("low", 3), ("medium", 5), ("high", 8)):
            proposal = {
                "name": f"std/{difficulty}_mod.mm",
                "reason": "",
                "depends_on": [],
                "difficulty": difficulty,
            }
            assert propose.build_spec_from_proposal(proposal)["max_retries"] == expected

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError):
            propose.build_spec_from_proposal({"reason": "nope"})

    def test_non_dict_raises(self) -> None:
        with pytest.raises(TypeError):
            propose.build_spec_from_proposal("not-a-dict")  # type: ignore[arg-type]

    def test_missing_depends_on_has_no_preamble(self) -> None:
        proposal = {
            "name": "std/solo.mm",
            "reason": "",
            "difficulty": "low",
        }
        spec = propose.build_spec_from_proposal(proposal)
        assert "import_preamble" not in spec
        assert "depends_on" not in spec
        # A default placeholder atom is still emitted.
        assert spec["atoms"][0]["name"] == "solo_placeholder"

    def test_explicit_atoms_preserved(self) -> None:
        proposal = {
            "name": "std/bitset.mm",
            "reason": "",
            "depends_on": [],
            "difficulty": "low",
            "atoms": [
                {
                    "name": "bitset_popcount",
                    "description": "count set bits",
                    "inputs": [{"name": "bits", "type": "i64"}],
                    "return_type": "i64",
                    "requires": "true",
                    "ensures": "result >= 0",
                }
            ],
        }
        spec = propose.build_spec_from_proposal(proposal)
        assert spec["atoms"][0]["name"] == "bitset_popcount"
        assert spec["atoms"][0]["ensures"] == "result >= 0"


# ---------------------------------------------------------------------------
# Full fixture-driven integration path
# ---------------------------------------------------------------------------


class TestBuildSpecsFromGaps:
    def test_generates_one_spec_per_proposal(self) -> None:
        gaps = _load_sample_gaps()
        specs = propose.build_specs_from_gaps(gaps)
        assert len(specs) == len(gaps["proposals"])

    def test_generated_spec_names_are_unique(self) -> None:
        gaps = _load_sample_gaps()
        specs = propose.build_specs_from_gaps(gaps)
        task_ids = [s["task_id"] for s in specs]
        assert len(task_ids) == len(set(task_ids))

    def test_difficulty_mapping_is_applied(self) -> None:
        gaps = _load_sample_gaps()
        specs = propose.build_specs_from_gaps(gaps)
        by_target = {s["target_file"]: s for s in specs}
        assert by_target["std/iter.mm"]["max_retries"] == 5
        assert by_target["std/ring_buffer.mm"]["max_retries"] == 8
        assert by_target["std/bitset.mm"]["max_retries"] == 3

    def test_rejects_non_dict_payload(self) -> None:
        with pytest.raises(TypeError):
            propose.build_specs_from_gaps([1, 2, 3])  # type: ignore[arg-type]

    def test_rejects_non_list_proposals(self) -> None:
        with pytest.raises(ValueError):
            propose.build_specs_from_gaps({"proposals": "oops"})

    def test_explicit_priority_zero_preserved(self) -> None:
        """priority=0 (highest) must not be coerced into the list index."""
        gaps = {
            "proposals": [
                {
                    "name": "std/alpha.mm",
                    "reason": "",
                    "depends_on": [],
                    "difficulty": "low",
                    "priority": 0,
                },
                {
                    "name": "std/beta.mm",
                    "reason": "",
                    "depends_on": [],
                    "difficulty": "low",
                },
            ],
        }
        specs = propose.build_specs_from_gaps(gaps)
        by_target = {s["target_file"]: s for s in specs}
        assert by_target["std/alpha.mm"]["priority"] == 0
        # Second proposal has no explicit priority — falls back to its
        # 1-based position (idx=2).
        assert by_target["std/beta.mm"]["priority"] == 2


# ---------------------------------------------------------------------------
# Disk output + CLI integration
# ---------------------------------------------------------------------------


class TestWriteSpecs:
    def test_writes_expected_filenames(self, tmp_path: Path) -> None:
        gaps = _load_sample_gaps()
        specs = propose.build_specs_from_gaps(gaps)
        written = propose.write_specs(specs, tmp_path)
        names = sorted(p.name for p in written)
        assert names == sorted(
            ["vstd_iter.json", "vstd_ring_buffer.json", "vstd_bitset.json"]
        )

    def test_written_spec_is_valid_json(self, tmp_path: Path) -> None:
        gaps = _load_sample_gaps()
        specs = propose.build_specs_from_gaps(gaps)
        paths = propose.write_specs(specs, tmp_path)
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "task_id" in data
            assert data["target_file"].startswith("std/")

    def test_suffixed_filename_when_not_overwriting(self, tmp_path: Path) -> None:
        gaps = {
            "proposals": [
                {
                    "name": "std/iter.mm",
                    "reason": "",
                    "depends_on": [],
                    "difficulty": "low",
                }
            ]
        }
        specs = propose.build_specs_from_gaps(gaps)
        first = propose.write_specs(specs, tmp_path)
        second = propose.write_specs(specs, tmp_path)
        assert first[0].name == "vstd_iter.json"
        assert second[0].name == "vstd_iter.1.json"

    def test_overwrite_reuses_filename(self, tmp_path: Path) -> None:
        gaps = {
            "proposals": [
                {
                    "name": "std/iter.mm",
                    "reason": "",
                    "depends_on": [],
                    "difficulty": "low",
                }
            ]
        }
        specs = propose.build_specs_from_gaps(gaps)
        propose.write_specs(specs, tmp_path)
        rewritten = propose.write_specs(specs, tmp_path, overwrite=True)
        assert rewritten[0].name == "vstd_iter.json"


class TestCLIEntrypoint:
    def test_main_with_gaps_json_writes_specs(
        self,
        tmp_path: Path,
    ) -> None:
        out_dir = tmp_path / "forge_tasks"
        parser = propose.build_parser()
        args = parser.parse_args([
            "--gaps-json", str(SAMPLE_GAPS_JSON),
            "--output-dir", str(out_dir),
        ])
        propose.main(args)
        assert out_dir.exists()
        files = sorted(p.name for p in out_dir.glob("vstd_*.json"))
        assert files == sorted(
            ["vstd_iter.json", "vstd_ring_buffer.json", "vstd_bitset.json"]
        )

    def test_main_dry_run_does_not_write(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "forge_tasks"
        parser = propose.build_parser()
        args = parser.parse_args([
            "--gaps-json", str(SAMPLE_GAPS_JSON),
            "--output-dir", str(out_dir),
            "--dry-run",
        ])
        propose.main(args)
        assert not out_dir.exists() or not any(out_dir.iterdir())

    def test_main_auto_without_mcp_module_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Ensure the import fails deterministically.
        import sys

        monkeypatch.setitem(sys.modules, "mcp_server", None)
        parser = propose.build_parser()
        args = parser.parse_args([
            "--auto",
            "--output-dir", str(tmp_path),
        ])
        with pytest.raises(SystemExit):
            propose.main(args)


# ---------------------------------------------------------------------------
# Forge-spec schema compatibility
# ---------------------------------------------------------------------------


class TestSpecSchemaCompatibility:
    def test_spec_matches_forge_discovery_expectations(self, tmp_path: Path) -> None:
        """Generated specs must round-trip through forge_discovery._load_task."""
        from agent.forge_discovery import _load_task

        gaps = _load_sample_gaps()
        specs = propose.build_specs_from_gaps(gaps)
        paths = propose.write_specs(specs, tmp_path)
        for path in paths:
            task = _load_task(path)
            # Core contract: discovery returns a dict (not None) with
            # the canonical required fields for forge-runner dispatch.
            assert isinstance(task, dict)
            assert task["target_file"].startswith("std/")
            assert task["mode"] in {"append", "create"}
            assert isinstance(task["atoms"], list) and task["atoms"]


# ---------------------------------------------------------------------------
# Task 2-B — every gap rule must have a checked-in forge task spec
# ---------------------------------------------------------------------------


# Targets that intentionally have no forge_tasks/*.json yet.  Add a
# ``target -> reason`` entry here when a gap rule is deferred so the
# completeness test treats it as expected and emits the deferral
# rationale in the assertion message.
_DEFERRED_GAP_TARGETS: dict[str, str] = {}


class TestForgeTaskCoverage:
    def test_all_gap_rules_have_forge_tasks(self) -> None:
        """Each entry in ``_STD_GAP_RULES`` must map to a forge task."""
        from agent.gap_rules import _STD_GAP_RULES

        forge_tasks_dir = Path(__file__).parent.parent / "forge_tasks"
        targets_with_specs: set[str] = set()
        for spec_path in forge_tasks_dir.glob("vstd_*.json"):
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                pytest.fail(f"Malformed forge spec {spec_path.name}: {exc}")
            target = spec.get("target_file")
            if isinstance(target, str):
                targets_with_specs.add(target)

        missing: list[str] = []
        for rule in _STD_GAP_RULES:
            target = rule["target"]
            if target in _DEFERRED_GAP_TARGETS:
                continue
            if target not in targets_with_specs:
                missing.append(target)

        assert not missing, (
            "Gap rules without a corresponding forge_tasks/vstd_*.json: "
            f"{sorted(missing)}. Either add a spec or list the target in "
            "_DEFERRED_GAP_TARGETS with a rationale."
        )
