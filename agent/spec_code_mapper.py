"""Map specification items to generated code locations."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.config import AgentConfig
from agent.intent_tracker import IntentDriftResult


@dataclass
class SpecCodeMapping:
    """Mapping between a spec item and code location."""

    spec_description: str
    spec_type: str
    spec_clause: str
    code_location: dict[str, int]
    verification_status: str
    confidence: float
    spec_item_id: str = ""
    requires_clause: str | None = None
    ensures_clause: str | None = None
    intent_drift_score: float | None = None


@dataclass
class MappingResult:
    """Result of spec-to-code mapping."""

    success: bool
    mappings: list[SpecCodeMapping]
    warnings: list[str]
    errors: list[str]


class SpecCodeMapper:
    """Map specification items to generated code locations."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()

    def build_mapping(
        self,
        spec: dict[str, Any],
        generated_code: str,
        verification_report: dict[str, Any] | None = None,
        intent_drift_result: IntentDriftResult | None = None,
    ) -> MappingResult:
        """Build mappings between specification clauses and code locations."""
        mappings: list[SpecCodeMapping] = []
        warnings: list[str] = []

        for atom_spec in self._atom_specs(spec):
            atom_name = str(atom_spec.get("name", ""))

            for requires_clause in self._clauses(atom_spec.get("requires")):
                requires_mapping = self.map_requires_to_code(
                    requires_clause,
                    generated_code,
                    verification_report,
                    atom_name=atom_name,
                    description=str(atom_spec.get("description") or atom_name),
                    intent_drift_result=intent_drift_result,
                )
                if requires_mapping is None:
                    warnings.append(
                        f"No code location found for requires clause: {requires_clause}",
                    )
                else:
                    mappings.append(requires_mapping)

            for ensures_clause in self._clauses(atom_spec.get("ensures")):
                ensures_mapping = self.map_ensures_to_code(
                    ensures_clause,
                    generated_code,
                    verification_report,
                    atom_name=atom_name,
                    description=str(atom_spec.get("description") or atom_name),
                    intent_drift_result=intent_drift_result,
                )
                if ensures_mapping is None:
                    warnings.append(
                        f"No code location found for ensures clause: {ensures_clause}",
                    )
                else:
                    mappings.append(ensures_mapping)

            for effect_clause in self._clauses(atom_spec.get("effects")):
                effect_mapping = self.map_effect_to_code(
                    effect_clause,
                    generated_code,
                    verification_report,
                    atom_name=atom_name,
                    description=str(atom_spec.get("description") or atom_name),
                    intent_drift_result=intent_drift_result,
                )
                if effect_mapping is None:
                    warnings.append(
                        f"No code location found for effect clause: {effect_clause}",
                    )
                else:
                    mappings.append(effect_mapping)

            if not self._clauses(atom_spec.get("requires")) and not self._clauses(
                atom_spec.get("ensures"),
            ) and not self._clauses(atom_spec.get("effects")):
                fallback = self._map_atom_to_code(
                    atom_spec,
                    generated_code,
                    verification_report,
                    intent_drift_result,
                )
                mappings.append(fallback)

        return MappingResult(
            success=True,
            mappings=mappings,
            warnings=warnings,
            errors=[],
        )

    def map_requires_to_code(
        self,
        requires_clause: str,
        generated_code: str,
        verification_report: dict[str, Any] | None = None,
        *,
        atom_name: str = "",
        description: str = "",
        intent_drift_result: IntentDriftResult | None = None,
    ) -> SpecCodeMapping | None:
        """Map a requires clause to the closest generated code location."""
        return self._map_clause_to_code(
            "requires",
            requires_clause,
            generated_code,
            verification_report,
            atom_name=atom_name,
            description=description,
            intent_drift_result=intent_drift_result,
        )

    def map_ensures_to_code(
        self,
        ensures_clause: str,
        generated_code: str,
        verification_report: dict[str, Any] | None = None,
        *,
        atom_name: str = "",
        description: str = "",
        intent_drift_result: IntentDriftResult | None = None,
    ) -> SpecCodeMapping | None:
        """Map an ensures clause to the closest generated code location."""
        return self._map_clause_to_code(
            "ensures",
            ensures_clause,
            generated_code,
            verification_report,
            atom_name=atom_name,
            description=description,
            intent_drift_result=intent_drift_result,
        )

    def map_effect_to_code(
        self,
        effect_clause: str,
        generated_code: str,
        verification_report: dict[str, Any] | None = None,
        *,
        atom_name: str = "",
        description: str = "",
        intent_drift_result: IntentDriftResult | None = None,
    ) -> SpecCodeMapping | None:
        """Map an effect clause to the closest generated code location."""
        return self._map_clause_to_code(
            "effect",
            effect_clause,
            generated_code,
            verification_report,
            atom_name=atom_name,
            description=description,
            intent_drift_result=intent_drift_result,
        )

    _map_requires_to_code = map_requires_to_code
    _map_ensures_to_code = map_ensures_to_code

    def _map_clause_to_code(
        self,
        spec_type: str,
        clause: str,
        generated_code: str,
        verification_report: dict[str, Any] | None,
        *,
        atom_name: str,
        description: str,
        intent_drift_result: IntentDriftResult | None,
    ) -> SpecCodeMapping | None:
        line, confidence = self._find_clause_location(
            generated_code,
            clause,
            atom_name,
            spec_type,
        )
        if line["line"] == 0:
            return None

        status = self._determine_verification_status(
            clause,
            verification_report or {},
            atom_name,
        )
        prefix = {
            "requires": "Precondition",
            "ensures": "Postcondition",
            "effect": "Effect",
        }.get(spec_type, "Specification")
        return SpecCodeMapping(
            spec_description=f"{prefix}: {clause}",
            spec_type=spec_type,
            spec_clause=clause,
            code_location=line,
            verification_status=status,
            spec_item_id=atom_name,
            requires_clause=clause if spec_type == "requires" else None,
            ensures_clause=clause if spec_type == "ensures" else None,
            confidence=confidence,
            intent_drift_score=self._intent_drift_score(
                intent_drift_result,
                spec_type,
                atom_name,
            ),
        )

    def _map_atom_to_code(
        self,
        atom_spec: dict[str, Any],
        code: str,
        verification_report: dict[str, Any] | None,
        intent_drift_result: IntentDriftResult | None = None,
    ) -> SpecCodeMapping:
        atom_name = str(atom_spec.get("name", ""))
        code_location = self._find_atom_location(code, atom_name)
        status = self._extract_verification_status(verification_report or {}, atom_name)
        return SpecCodeMapping(
            spec_description=str(atom_spec.get("description") or atom_name),
            spec_type="effect",
            spec_clause=str(atom_spec.get("effects") or atom_name),
            code_location=code_location,
            verification_status=status,
            spec_item_id=atom_name,
            confidence=self._calculate_confidence(atom_spec, code, code_location),
            intent_drift_score=self._intent_drift_score(
                intent_drift_result,
                "effect",
                atom_name,
            ),
        )

    def _atom_specs(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        atoms = spec.get("atoms")
        if isinstance(atoms, list):
            return [atom for atom in atoms if isinstance(atom, dict)]
        if spec.get("name"):
            return [spec]
        return []

    def _clauses(self, raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            stripped = raw.strip()
            return [stripped] if stripped else []
        if isinstance(raw, list):
            clauses: list[str] = []
            for item in raw:
                if isinstance(item, str) and item.strip():
                    clauses.append(item.strip())
            return clauses
        return [str(raw).strip()] if str(raw).strip() else []

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

    def _find_clause_location(
        self,
        code: str,
        clause: str,
        atom_name: str,
        spec_type: str,
    ) -> tuple[dict[str, int], float]:
        exact = self._find_text_location(code, clause)
        if exact["line"] > 0:
            return exact, 0.95

        clause_terms = self._significant_terms(clause)
        best_location = {"line": 0, "col": 0}
        best_score = 0.0
        lines = code.split("\n")
        for index, line in enumerate(lines, 1):
            stripped = line.strip()
            if spec_type in stripped:
                score = 0.35
            elif atom_name and re.search(r"\b" + re.escape(atom_name) + r"\b", stripped):
                score = 0.2
            else:
                score = 0.0

            if clause_terms:
                matched = sum(
                    1
                    for term in clause_terms
                    if re.search(r"\b" + re.escape(term) + r"\b", stripped)
                )
                score += matched / len(clause_terms) * 0.55

            if score > best_score:
                col = line.find(spec_type)
                if col < 0:
                    col = len(line) - len(line.lstrip())
                best_location = {"line": index, "col": col + 1}
                best_score = score

        if best_score >= 0.35:
            return best_location, min(best_score, 0.85)

        atom_location = self._find_atom_location(code, atom_name)
        if atom_location["line"] > 0:
            return atom_location, 0.25
        return {"line": 0, "col": 0}, 0.0

    def _find_text_location(self, code: str, text: str) -> dict[str, int]:
        if not text:
            return {"line": 0, "col": 0}
        match = re.search(re.escape(text), code)
        if not match:
            return {"line": 0, "col": 0}
        before_match = code[:match.start()]
        line = before_match.count("\n") + 1
        last_newline = before_match.rfind("\n")
        col = match.start() - last_newline if last_newline >= 0 else match.start() + 1
        return {"line": line, "col": col}

    def _significant_terms(self, clause: str) -> list[str]:
        terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[-]?\d+", clause)
        ignored = {"and", "or", "not", "true", "false", "result"}
        return [term for term in terms if term.lower() not in ignored]

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

    def _determine_verification_status(
        self,
        clause: str,
        verification_report: dict[str, Any],
        atom_name: str = "",
    ) -> str:
        """Determine verification status from a verification report."""
        violated_constraints = verification_report.get(
            "semantic_feedback", {},
        ).get("violated_constraints", [])

        for vc in violated_constraints:
            if isinstance(vc, dict) and clause in str(vc.get("constraint", "")):
                return "failed"
            if isinstance(vc, str) and clause in vc:
                return "failed"

        failed_status = self._extract_verification_status(
            verification_report,
            atom_name,
        )
        if failed_status in {"failed", "passed"}:
            return failed_status
        if not verification_report:
            return "unknown"
        if verification_report.get("success") is False or verification_report.get("status") in {
            "failed",
            "fail",
        }:
            return "failed"
        return "passed"

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

    def _intent_drift_score(
        self,
        intent_drift_result: IntentDriftResult | None,
        spec_type: str,
        atom_name: str,
    ) -> float | None:
        if intent_drift_result is None:
            return None

        field = "effects" if spec_type == "effect" else spec_type
        expected_fields = {field}
        if atom_name:
            expected_fields.add(f"atoms.{atom_name}.{field}")

        for change in intent_drift_result.changes:
            if change.field in expected_fields:
                return intent_drift_result.drift_score
        return intent_drift_result.drift_score

    def to_json(self, mappings: list[SpecCodeMapping]) -> list[dict[str, Any]]:
        """Convert mappings to JSON-serializable format."""
        return [
            {
                "spec_description": mapping.spec_description,
                "spec_type": mapping.spec_type,
                "spec_clause": mapping.spec_clause,
                "spec_item_id": mapping.spec_item_id,
                "requires_clause": mapping.requires_clause,
                "ensures_clause": mapping.ensures_clause,
                "code_location": mapping.code_location,
                "verification_status": mapping.verification_status,
                "confidence": mapping.confidence,
                "intent_drift_score": mapping.intent_drift_score,
            }
            for mapping in mappings
        ]
