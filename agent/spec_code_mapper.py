"""Specification to code mapping."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SpecCodeMapping:
    """Mapping between a specification item and code location."""

    spec_description: str
    spec_item_id: str
    requires_clause: str | None
    ensures_clause: str | None
    code_location: dict[str, int]
    verification_status: str
    confidence: float


class SpecCodeMapper:
    """Map specification items to generated code locations."""

    def build_mapping(
        self,
        spec: dict[str, Any],
        generated_code: str,
        verification_report: dict[str, Any] | None = None,
    ) -> list[SpecCodeMapping]:
        """Build specification-to-code mapping."""
        mappings = []

        for atom_spec in self._atom_specs(spec):
            atom_name = str(atom_spec.get("name", ""))
            requires = str(atom_spec.get("requires", ""))
            ensures = str(atom_spec.get("ensures", ""))
            code_location = self._find_atom_location(generated_code, atom_name)

            verification_status = "unknown"
            if verification_report:
                verification_status = self._extract_verification_status(
                    verification_report, atom_name,
                )

            confidence = self._calculate_confidence(
                atom_spec, generated_code, code_location,
            )

            mappings.append(
                SpecCodeMapping(
                    spec_description=str(atom_spec.get("description") or atom_name),
                    spec_item_id=atom_name,
                    requires_clause=requires if requires else None,
                    ensures_clause=ensures if ensures else None,
                    code_location=code_location,
                    verification_status=verification_status,
                    confidence=confidence,
                )
            )

        return mappings

    def _atom_specs(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        atoms = spec.get("atoms")
        if isinstance(atoms, list):
            return [atom for atom in atoms if isinstance(atom, dict)]
        if spec.get("name"):
            return [spec]
        return []

    def _find_atom_location(self, code: str, atom_name: str) -> dict[str, int]:
        """Find the line and column of an atom in the code."""
        if not atom_name:
            return {"line": 0, "col": 0}

        pattern = rf"\batom\s+{re.escape(atom_name)}\s*\("
        match = re.search(pattern, code)
        if match:
            before_match = code[:match.start()]
            line = before_match.count("\n") + 1
            last_newline = before_match.rfind("\n")
            col = match.start() - last_newline if last_newline >= 0 else match.start() + 1
            return {"line": line, "col": col}
        return {"line": 0, "col": 0}

    def _extract_verification_status(
        self,
        report: dict[str, Any],
        atom_name: str,
    ) -> str:
        """Extract verification status for an atom from report."""
        verified_atoms = report.get("verified_atoms", [])
        if self._atom_in_report_items(verified_atoms, atom_name):
            return "passed"

        failed_atoms = report.get("failed_atoms", [])
        if self._atom_in_report_items(failed_atoms, atom_name):
            return "failed"

        if report.get("success") is True or report.get("status") in {
            "ok",
            "success",
            "passed",
        }:
            return "passed"
        if self._report_mentions_atom(report, atom_name):
            if report.get("success") is False or report.get("status") in {
                "failed",
                "fail",
            }:
                return "failed"

        return "unknown"

    def _atom_in_report_items(self, items: Any, atom_name: str) -> bool:
        if isinstance(items, set):
            items = list(items)
        if isinstance(items, dict):
            items = list(items.values())
        if not isinstance(items, list) and not isinstance(items, tuple):
            return False
        for item in items:
            if item == atom_name:
                return True
            if isinstance(item, dict):
                name = item.get("name") or item.get("atom") or item.get("atom_name")
                if name == atom_name:
                    return True
        return False

    def _report_mentions_atom(self, report: dict[str, Any], atom_name: str) -> bool:
        report_atom = report.get("atom")
        if report_atom == atom_name:
            return True
        report_atoms = report.get("atoms", [])
        return self._atom_in_report_items(report_atoms, atom_name)

    def _calculate_confidence(
        self,
        atom_spec: dict[str, Any],
        code: str,
        location: dict[str, int],
    ) -> float:
        """Calculate confidence score for the mapping."""
        if location["line"] == 0:
            return 0.0

        confidence = 0.5
        requires = str(atom_spec.get("requires", ""))
        ensures = str(atom_spec.get("ensures", ""))

        if requires and requires in code:
            confidence += 0.2
        if ensures and ensures in code:
            confidence += 0.2

        raw_params = atom_spec.get("inputs", atom_spec.get("params", []))
        if isinstance(raw_params, list):
            for param in raw_params:
                if not isinstance(param, dict):
                    continue
                param_name = str(param.get("name", ""))
                if param_name and re.search(r"\b" + re.escape(param_name) + r"\b", code):
                    confidence += 0.05

        return min(confidence, 1.0)

    def to_json(self, mappings: list[SpecCodeMapping]) -> list[dict[str, Any]]:
        """Convert mappings to JSON-serializable format."""
        return [
            {
                "spec_description": mapping.spec_description,
                "spec_item_id": mapping.spec_item_id,
                "requires_clause": mapping.requires_clause,
                "ensures_clause": mapping.ensures_clause,
                "code_location": mapping.code_location,
                "verification_status": mapping.verification_status,
                "confidence": mapping.confidence,
            }
            for mapping in mappings
        ]
