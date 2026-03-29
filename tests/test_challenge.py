"""Tests for Zero-Human Challenge specs and runner.

Validates all challenge spec JSONs, tests dry-run mode, multi-atom format
verification, and import correctness of run_challenge.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHALLENGES_DIR = Path(__file__).parent.parent / "examples" / "challenges"

# ---------------------------------------------------------------------------
# Import the runner's validate_spec directly
# ---------------------------------------------------------------------------

from examples.challenges.run_challenge import (
    DEFAULT_RESULTS_DIR,
    CHALLENGES_DIR as RUNNER_CHALLENGES_DIR,
    discover_specs,
    validate_spec,
)


# ---------------------------------------------------------------------------
# Discover all challenge specs
# ---------------------------------------------------------------------------

SPEC_FILES = sorted(CHALLENGES_DIR.glob("*_spec.json"))

# New challenge specs added for the Zero-Human Challenge
NEW_CHALLENGE_SPECS = [
    "safe_queue_spec.json",
    "verified_json_validator_spec.json",
    "deadlock_free_producer_consumer_spec.json",
]


# ---------------------------------------------------------------------------
# Spec validation tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec_path",
    SPEC_FILES,
    ids=[p.stem for p in SPEC_FILES],
)
class TestSpecValidation:
    """Validate each challenge spec JSON."""

    def test_spec_is_valid_json(self, spec_path: Path) -> None:
        """Spec file is valid JSON."""
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        assert isinstance(spec, dict)

    def test_spec_passes_validation(self, spec_path: Path) -> None:
        """Spec passes the validate_spec() checks."""
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        errors = validate_spec(spec)
        assert errors == [], f"Validation errors: {errors}"

    def test_spec_has_requires_ensures(self, spec_path: Path) -> None:
        """Every atom in the spec has requires and ensures fields."""
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)

        if "atoms" in spec:
            for atom in spec["atoms"]:
                assert "requires" in atom, f"atom '{atom.get('name')}' missing 'requires'"
                assert "ensures" in atom, f"atom '{atom.get('name')}' missing 'ensures'"
        else:
            has_requires = "requires" in spec or "requires" in spec.get("constraints", {})
            has_ensures = "ensures" in spec or "ensures" in spec.get("constraints", {})
            assert has_requires, "spec missing 'requires'"
            assert has_ensures, "spec missing 'ensures'"

    def test_spec_has_params(self, spec_path: Path) -> None:
        """Every atom in the spec has parameters."""
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)

        if "atoms" in spec:
            for atom in spec["atoms"]:
                params = atom.get("params", atom.get("inputs", []))
                assert isinstance(params, list) and len(params) > 0, (
                    f"atom '{atom.get('name')}' must have at least one parameter"
                )
        else:
            params = spec.get("params", spec.get("inputs", []))
            assert isinstance(params, list) and len(params) > 0, (
                "spec must have at least one parameter"
            )


# ---------------------------------------------------------------------------
# Multi-atom format verification
# ---------------------------------------------------------------------------


class TestMultiAtomFormat:
    """Verify that multi-atom specs follow the correct format."""

    @pytest.mark.parametrize("spec_name", [
        "safe_queue_spec.json",
        "deadlock_free_producer_consumer_spec.json",
        "bounded_queue_spec.json",
        "safe_arithmetic_spec.json",
        "payment_spec.json",
    ])
    def test_multi_atom_has_module_name(self, spec_name: str) -> None:
        """Multi-atom specs must have a module_name field."""
        spec_path = CHALLENGES_DIR / spec_name
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        assert "atoms" in spec, f"{spec_name} should be a multi-atom spec"
        assert "module_name" in spec, f"{spec_name} missing 'module_name'"
        assert isinstance(spec["module_name"], str) and len(spec["module_name"]) > 0

    @pytest.mark.parametrize("spec_name", [
        "safe_queue_spec.json",
        "deadlock_free_producer_consumer_spec.json",
        "bounded_queue_spec.json",
        "safe_arithmetic_spec.json",
        "payment_spec.json",
    ])
    def test_multi_atom_atoms_is_list(self, spec_name: str) -> None:
        """Multi-atom specs must have an atoms array."""
        spec_path = CHALLENGES_DIR / spec_name
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        assert isinstance(spec["atoms"], list)
        assert len(spec["atoms"]) >= 2, "multi-atom spec should have at least 2 atoms"

    def test_single_atom_spec_format(self) -> None:
        """Single-atom spec (verified_json_validator) should NOT have atoms array."""
        spec_path = CHALLENGES_DIR / "verified_json_validator_spec.json"
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        assert "atoms" not in spec
        assert "name" in spec
        assert "effects" in spec
        assert isinstance(spec["effects"], list) and len(spec["effects"]) > 0


# ---------------------------------------------------------------------------
# New challenge specs existence
# ---------------------------------------------------------------------------


class TestNewChallengeSpecs:
    """Verify that the three new challenge specs exist and are valid."""

    @pytest.mark.parametrize("spec_name", NEW_CHALLENGE_SPECS)
    def test_spec_file_exists(self, spec_name: str) -> None:
        """New challenge spec file exists."""
        spec_path = CHALLENGES_DIR / spec_name
        assert spec_path.exists(), f"{spec_name} does not exist"

    def test_safe_queue_has_four_atoms(self) -> None:
        """safe_queue_spec.json should have 4 atoms."""
        with open(CHALLENGES_DIR / "safe_queue_spec.json", encoding="utf-8") as f:
            spec = json.load(f)
        atom_names = [a["name"] for a in spec["atoms"]]
        assert set(atom_names) == {"enqueue", "dequeue", "is_empty", "is_full"}

    def test_verified_json_validator_has_effects(self) -> None:
        """verified_json_validator_spec.json should have SafeFileRead effect."""
        with open(CHALLENGES_DIR / "verified_json_validator_spec.json", encoding="utf-8") as f:
            spec = json.load(f)
        assert "effects" in spec
        assert any("SafeFileRead" in e for e in spec["effects"])

    def test_deadlock_free_pc_has_resources(self) -> None:
        """deadlock_free_producer_consumer_spec.json should have resources."""
        with open(CHALLENGES_DIR / "deadlock_free_producer_consumer_spec.json", encoding="utf-8") as f:
            spec = json.load(f)
        assert "resources" in spec
        assert "buffer" in spec["resources"]
        assert "mutex" in spec["resources"]


# ---------------------------------------------------------------------------
# Dry-run mode tests
# ---------------------------------------------------------------------------


class TestDryRun:
    """Test that run_challenge.py works in --dry-run mode."""

    def test_dry_run_single_spec(self) -> None:
        """Dry-run with a single spec exits 0."""
        spec_path = CHALLENGES_DIR / "safe_queue_spec.json"
        result = subprocess.run(
            [
                sys.executable, "-m", "examples.challenges.run_challenge",
                str(spec_path),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert "Spec validation: OK" in result.stdout

    def test_dry_run_all_specs(self) -> None:
        """--all --dry-run validates all specs and exits 0."""
        result = subprocess.run(
            [
                sys.executable, "-m", "examples.challenges.run_challenge",
                "--all",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert "Final Summary" in result.stdout


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestImports:
    """Test that run_challenge.py can be imported correctly."""

    def test_import_run_challenge(self) -> None:
        """run_challenge module can be imported."""
        from examples.challenges import run_challenge
        assert hasattr(run_challenge, "run_challenge")
        assert hasattr(run_challenge, "validate_spec")
        assert hasattr(run_challenge, "discover_specs")
        assert hasattr(run_challenge, "main")
        assert hasattr(run_challenge, "_write_results")

    def test_discover_specs_returns_all(self) -> None:
        """discover_specs() returns all *_spec.json files."""
        specs = discover_specs()
        assert len(specs) >= 7, f"Expected at least 7 specs, got {len(specs)}"
        names = [p.name for p in specs]
        for new_spec in NEW_CHALLENGE_SPECS:
            assert new_spec in names, f"{new_spec} not found in discovered specs"

    def test_validate_spec_rejects_invalid(self) -> None:
        """validate_spec() rejects specs with missing required fields."""
        errors = validate_spec({})
        assert len(errors) > 0

        errors = validate_spec({"atoms": []})
        assert len(errors) > 0

        errors = validate_spec({"atoms": [{"name": "x"}], "module_name": ""})
        assert len(errors) > 0
