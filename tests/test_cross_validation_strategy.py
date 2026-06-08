"""Tests for agent.strategies.cross_validation_strategy."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agent.strategies.cross_validation_strategy import (
    CrossValidationReport,
    CrossValidator,
    DriftReport,
    _extract_functions,
    _extract_spec_atoms,
)


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

SAMPLE_SPEC = """\
atom safe_add(a: i64, b: i64) -> i64
  requires: a >= 0 && b >= 0 && a + b <= 9223372036854775807
  ensures: result == a + b
{
  a + b
}

atom validate_balance(amount: i64) -> bool
  requires: amount > 0 && amount < 1000000
  ensures: result == true
{
  amount > 0
}
"""

SAMPLE_RUST_IMPL = """\
pub fn safe_add(a: i64, b: i64) -> i64 {
    assert!(a >= 0 && b >= 0);
    a.checked_add(b).expect("overflow")
}

pub fn validate_balance(amount: i64) -> bool {
    amount > 0 && amount < 1_000_000
}

pub fn internal_helper() -> () {
    // not in spec
}
"""

SAMPLE_PYTHON_IMPL = """\
def safe_add(a: int, b: int) -> int:
    assert a >= 0 and b >= 0
    return a + b

def validate_balance(amount: int) -> bool:
    return amount > 0 and amount < 1_000_000
"""

SAMPLE_TS_IMPL = """\
export function safe_add(a: number, b: number): number {
    if (a < 0 || b < 0) throw new Error("negative");
    return a + b;
}

export const validate_balance = (amount: number): boolean => {
    return amount > 0 && amount < 1_000_000;
};
"""


# ---------------------------------------------------------------------------
# Tests: _extract_functions
# ---------------------------------------------------------------------------

class TestExtractFunctions:
    def test_rust(self):
        names = _extract_functions(SAMPLE_RUST_IMPL, "rust")
        assert "safe_add" in names
        assert "validate_balance" in names
        assert "internal_helper" in names

    def test_python(self):
        names = _extract_functions(SAMPLE_PYTHON_IMPL, "python")
        assert "safe_add" in names
        assert "validate_balance" in names

    def test_typescript(self):
        names = _extract_functions(SAMPLE_TS_IMPL, "typescript")
        assert "safe_add" in names
        assert "validate_balance" in names


# ---------------------------------------------------------------------------
# Tests: _extract_spec_atoms
# ---------------------------------------------------------------------------

class TestExtractSpecAtoms:
    def test_extracts_atoms(self):
        atoms = _extract_spec_atoms(SAMPLE_SPEC)
        assert len(atoms) == 2
        names = [a["name"] for a in atoms]
        assert "safe_add" in names
        assert "validate_balance" in names

    def test_atom_has_requires(self):
        atoms = _extract_spec_atoms(SAMPLE_SPEC)
        add_atom = next(a for a in atoms if a["name"] == "safe_add")
        assert "a >= 0" in add_atom["requires"]


# ---------------------------------------------------------------------------
# Tests: CrossValidator.validate_spec_vs_impl
# ---------------------------------------------------------------------------

class TestValidateSpecVsImpl:
    def setup_method(self):
        self.validator = CrossValidator()
        self.tmpdir = tempfile.mkdtemp()
        self.spec_path = Path(self.tmpdir) / "spec.mm"
        self.spec_path.write_text(SAMPLE_SPEC)

    def test_full_coverage_rust(self):
        impl_path = Path(self.tmpdir) / "lib.rs"
        impl_path.write_text(SAMPLE_RUST_IMPL)
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(self.spec_path),
            impl_path=str(impl_path),
            language="rust",
        )
        assert isinstance(report, CrossValidationReport)
        # Both atoms are implemented
        assert report.coverage_ratio > 0.0
        assert "safe_add" not in report.uncovered_atoms
        assert "validate_balance" not in report.uncovered_atoms

    def test_uncovered_atom(self):
        impl_path = Path(self.tmpdir) / "lib.rs"
        # Only implement safe_add
        impl_path.write_text("pub fn safe_add(a: i64, b: i64) -> i64 { a + b }\n")
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(self.spec_path),
            impl_path=str(impl_path),
            language="rust",
        )
        assert "validate_balance" in report.uncovered_atoms
        assert report.coverage_ratio == 0.5

    def test_missing_spec_file(self):
        report = self.validator.validate_spec_vs_impl(
            spec_path="/nonexistent/spec.mm",
            impl_path="/nonexistent/impl.rs",
            language="rust",
        )
        assert report.details  # Should have error detail

    def test_python_impl(self):
        impl_path = Path(self.tmpdir) / "lib.py"
        impl_path.write_text(SAMPLE_PYTHON_IMPL)
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(self.spec_path),
            impl_path=str(impl_path),
            language="python",
        )
        assert report.coverage_ratio == 1.0


# ---------------------------------------------------------------------------
# Tests: CrossValidator.detect_spec_drift
# ---------------------------------------------------------------------------

class TestDetectSpecDrift:
    def setup_method(self):
        self.validator = CrossValidator()

    def test_no_drift(self):
        cert = {
            "atoms": [
                {"name": "add", "content_hash": "abc123"},
                {"name": "sub", "content_hash": "def456"},
            ]
        }
        report = self.validator.detect_spec_drift(cert, cert)
        assert not report.drift_detected
        assert report.changed_atoms == []
        assert report.new_atoms == []
        assert report.removed_atoms == []

    def test_changed_atom(self):
        old_cert = {
            "atoms": [
                {"name": "add", "content_hash": "abc123"},
                {"name": "sub", "content_hash": "def456"},
            ]
        }
        new_cert = {
            "atoms": [
                {"name": "add", "content_hash": "changed"},
                {"name": "sub", "content_hash": "def456"},
            ]
        }
        report = self.validator.detect_spec_drift(old_cert, new_cert)
        assert report.drift_detected
        assert "add" in report.changed_atoms

    def test_new_atom(self):
        old_cert = {"atoms": [{"name": "add", "content_hash": "abc123"}]}
        new_cert = {
            "atoms": [
                {"name": "add", "content_hash": "abc123"},
                {"name": "mul", "content_hash": "new789"},
            ]
        }
        report = self.validator.detect_spec_drift(old_cert, new_cert)
        assert report.drift_detected
        assert "mul" in report.new_atoms

    def test_removed_atom(self):
        old_cert = {
            "atoms": [
                {"name": "add", "content_hash": "abc123"},
                {"name": "deprecated", "content_hash": "old111"},
            ]
        }
        new_cert = {"atoms": [{"name": "add", "content_hash": "abc123"}]}
        report = self.validator.detect_spec_drift(old_cert, new_cert)
        assert report.drift_detected
        assert "deprecated" in report.removed_atoms


# ---------------------------------------------------------------------------
# Tests: CrossValidator.check_impl_coverage
# ---------------------------------------------------------------------------

class TestCheckImplCoverage:
    def setup_method(self):
        self.validator = CrossValidator()

    def test_full_coverage(self):
        result = self.validator.check_impl_coverage(
            spec_atoms=["add", "sub"],
            impl_functions=["add", "sub", "helper"],
        )
        assert result["ratio"] == 1.0
        assert result["covered"] == ["add", "sub"]
        assert result["uncovered"] == []
        assert result["extra_in_impl"] == ["helper"]

    def test_partial_coverage(self):
        result = self.validator.check_impl_coverage(
            spec_atoms=["add", "sub", "mul"],
            impl_functions=["add"],
        )
        assert abs(result["ratio"] - 1 / 3) < 0.01
        assert result["uncovered"] == ["mul", "sub"]

    def test_empty_spec(self):
        result = self.validator.check_impl_coverage(
            spec_atoms=[],
            impl_functions=["add"],
        )
        assert result["ratio"] == 0.0
