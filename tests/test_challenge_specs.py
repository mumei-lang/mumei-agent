"""Tests for Zero-Human Challenge specs and runner.

Validates all challenge spec JSONs and tests dry-run mode of run_challenge.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHALLENGES_DIR = Path(__file__).parent.parent / "examples" / "challenges"

# ---------------------------------------------------------------------------
# Spec validation (same logic as run_e2e_demo.py / run_challenge.py)
# ---------------------------------------------------------------------------


def validate_spec(spec: dict) -> list[str]:
    """Validate a spec dict and return a list of error messages (empty = valid)."""
    errors: list[str] = []

    # Multi-atom spec
    if "atoms" in spec:
        if not spec.get("module_name"):
            errors.append("multi-atom spec must have a non-empty 'module_name' field")
        atoms = spec["atoms"]
        if not isinstance(atoms, list) or len(atoms) == 0:
            errors.append("'atoms' must be a non-empty list")
        else:
            for i, atom in enumerate(atoms):
                if not isinstance(atom, dict) or not atom.get("name"):
                    errors.append(f"atoms[{i}] must be a dict with a 'name' field")
                params = atom.get("params", atom.get("inputs", []))
                if not isinstance(params, list):
                    errors.append(f"atoms[{i}].params must be a list")
        return errors

    # Single-atom spec
    if not spec.get("name"):
        errors.append("spec must have a non-empty 'name' field")
    params = spec.get("params", spec.get("inputs", []))
    if not isinstance(params, list):
        errors.append("'params' must be a list")
    else:
        for i, p in enumerate(params):
            if not isinstance(p, dict) or "name" not in p:
                errors.append(f"params[{i}] must be a dict with at least a 'name' key")
    return errors


# ---------------------------------------------------------------------------
# Discover all challenge specs
# ---------------------------------------------------------------------------

SPEC_FILES = sorted(CHALLENGES_DIR.glob("*_spec.json"))


@pytest.mark.parametrize(
    "spec_path",
    SPEC_FILES,
    ids=[p.stem for p in SPEC_FILES],
)
class TestChallengeSpecs:
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
            # Single-atom spec: requires/ensures may be top-level or in constraints
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
# Dry-run mode test
# ---------------------------------------------------------------------------


class TestRunChallengeDryRun:
    """Test that run_challenge.py works in --dry-run mode."""

    def test_dry_run_single_spec(self) -> None:
        """--dry-run with a single spec exits 0."""
        spec_path = CHALLENGES_DIR / "bounded_queue_spec.json"
        result = subprocess.run(
            [
                sys.executable, "-m", "examples.challenges.run_challenge",
                "--spec", str(spec_path),
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
