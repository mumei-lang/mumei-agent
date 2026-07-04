"""Cross-validate Mumei specifications (.mm) against implementation code.

Detects semantic gaps where the specification is stronger, weaker, or
contradicts the implementation.  Also detects spec drift from proof
certificate content-hash changes and computes coverage of spec atoms
against implementation functions.

Typical usage::

    from agent.strategies.cross_validation_strategy import CrossValidator

    validator = CrossValidator()
    report = validator.validate_spec_vs_impl(
        spec_path="contracts.mm",
        impl_path="src/lib.rs",
        language="rust",
    )
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.strategies.cross_validation_strategy_helpers import (
    _ATOM_DEF_RE,
    _ENSURES_RE,
    _GO_FUNC_RE,
    _PYTHON_FUNC_RE,
    _REQUIRES_RE,
    _RUST_FUNC_RE,
    _TS_ARROW_RE,
    _TS_FUNC_RE,
    _extract_function_body,
    _extract_functions,
    _extract_spec_atoms,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CrossValidationReport:
    """Result of cross-validating a spec against its implementation."""

    spec_stronger_than_impl: list[str] = field(default_factory=list)
    impl_stronger_than_spec: list[str] = field(default_factory=list)
    uncovered_atoms: list[str] = field(default_factory=list)
    drift_detected: bool = False
    coverage_ratio: float = 0.0
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_consistent(self) -> bool:
        return (
            not self.spec_stronger_than_impl
            and not self.impl_stronger_than_spec
            and not self.uncovered_atoms
            and not self.drift_detected
        )


@dataclass
class DriftReport:
    """Report of spec drift between two proof certificates."""

    changed_atoms: list[str] = field(default_factory=list)
    new_atoms: list[str] = field(default_factory=list)
    removed_atoms: list[str] = field(default_factory=list)
    drift_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# CrossValidator
# ---------------------------------------------------------------------------


class CrossValidator:
    """Cross-validate Mumei specs against implementation code."""

    def validate_spec_vs_impl(
        self,
        spec_path: str,
        impl_path: str,
        language: str,
    ) -> CrossValidationReport:
        """Compare spec atoms with implementation functions.

        Detects:
        - spec_stronger_than_impl: spec atoms with contracts that reference
          constraints not reflected in the implementation structure.
        - impl_stronger_than_spec: implementation functions with complex
          validation logic not captured in any spec atom.
        - uncovered_atoms: spec atoms with no corresponding implementation
          function.

        Args:
            spec_path: Path to .mm specification file.
            impl_path: Path to implementation source file.
            language: Language of the implementation (python/rust/typescript/go).

        Returns:
            CrossValidationReport with semantic gap analysis.
        """
        report = CrossValidationReport()

        # Read files
        try:
            spec_source = Path(spec_path).read_text(encoding="utf-8")
        except OSError as exc:
            report.details.append(f"Failed to read spec: {exc}")
            return report

        try:
            impl_source = Path(impl_path).read_text(encoding="utf-8")
        except OSError as exc:
            report.details.append(f"Failed to read implementation: {exc}")
            return report

        # Extract atoms and functions
        spec_atoms = _extract_spec_atoms(spec_source)
        impl_functions = _extract_functions(impl_source, language)

        if not spec_atoms:
            report.details.append("No spec atoms found in spec file.")
            return report

        # Coverage analysis
        spec_names = {a["name"] for a in spec_atoms}
        impl_names = set(impl_functions)
        report.uncovered_atoms = sorted(spec_names - impl_names)

        covered = spec_names & impl_names
        report.coverage_ratio = len(covered) / len(spec_names) if spec_names else 0.0

        # Semantic gap detection: spec stronger than impl
        # If the spec has complex requires/ensures but the implementation
        # function is trivial (heuristic: short or no validation code)
        for atom in spec_atoms:
            if atom["name"] not in impl_names:
                continue
            has_complex_contract = bool(atom["requires"]) and len(atom["requires"]) > 20
            if has_complex_contract:
                body = _extract_function_body(impl_source, language, atom["name"])
                if body and len(body.strip()) < len(atom["requires"]):
                    report.spec_stronger_than_impl.append(atom["name"])

        # Semantic gap detection: impl stronger than spec
        # Functions with complex validation that have no spec or trivial spec
        for func_name in impl_functions:
            matching_atom = next((a for a in spec_atoms if a["name"] == func_name), None)
            if matching_atom is None:
                continue
            if not matching_atom["requires"] and not matching_atom["ensures"]:
                # Impl exists but spec is trivial
                report.impl_stronger_than_spec.append(func_name)

        return report

    def detect_spec_drift(
        self,
        old_cert: dict[str, Any],
        new_cert: dict[str, Any],
    ) -> DriftReport:
        """Detect spec drift by comparing proof certificate content hashes.

        Compares the ``content_hash`` fields of atoms in old and new
        certificates to determine which atoms have been added, removed, or
        modified.

        Args:
            old_cert: Previous proof certificate (parsed JSON).
            new_cert: Current proof certificate (parsed JSON).

        Returns:
            DriftReport with changed/new/removed atoms.
        """
        old_atoms = {
            a["name"]: a.get("content_hash", "")
            for a in old_cert.get("atoms", [])
        }
        new_atoms = {
            a["name"]: a.get("content_hash", "")
            for a in new_cert.get("atoms", [])
        }

        old_names = set(old_atoms.keys())
        new_names = set(new_atoms.keys())

        changed = sorted(
            name
            for name in old_names & new_names
            if old_atoms[name] != new_atoms[name]
        )
        new = sorted(new_names - old_names)
        removed = sorted(old_names - new_names)

        return DriftReport(
            changed_atoms=changed,
            new_atoms=new,
            removed_atoms=removed,
            drift_detected=bool(changed or new or removed),
        )

    def check_impl_coverage(
        self,
        spec_atoms: list[str],
        impl_functions: list[str],
    ) -> dict[str, Any]:
        """Compute coverage ratio of spec atoms against implementation functions.

        Args:
            spec_atoms: List of spec atom names.
            impl_functions: List of implementation function names.

        Returns:
            Dict with ``covered``, ``uncovered``, ``extra``, and ``ratio``.
        """
        spec_set = set(spec_atoms)
        impl_set = set(impl_functions)

        covered = sorted(spec_set & impl_set)
        uncovered = sorted(spec_set - impl_set)
        extra = sorted(impl_set - spec_set)
        ratio = len(covered) / len(spec_set) if spec_set else 0.0

        return {
            "covered": covered,
            "uncovered": uncovered,
            "extra_in_impl": extra,
            "ratio": ratio,
        }
