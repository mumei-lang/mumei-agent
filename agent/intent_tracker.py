"""Intent tracking for specification refinement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.config import AgentConfig


@dataclass
class IntentChange:
    """A single change in specification intent."""

    field: str
    original: str
    refined: str
    change_type: str
    intent_impact: str


@dataclass
class IntentDriftResult:
    """Result of intent drift analysis."""

    intent_preserved: bool
    changes: list[IntentChange]
    drift_score: float
    warnings: list[str]
    errors: list[str]


class IntentTracker:
    """Track intent drift during specification refinement."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()

    def track_intent_drift(
        self,
        original_spec: dict[str, Any],
        refined_spec: dict[str, Any],
        natural_language_intent: str | None = None,
    ) -> IntentDriftResult:
        """Detect whether a refined specification preserves the original intent."""
        changes: list[IntentChange] = []

        if natural_language_intent:
            changes.extend(
                self.detect_intent_violation(
                    original_spec,
                    refined_spec,
                    natural_language_intent,
                ),
            )

        changes.extend(self._track_single_spec("", original_spec, refined_spec))
        changes.extend(self._track_atom_specs(original_spec, refined_spec))

        drift_score = self._calculate_drift_score(changes)
        intent_preserved = drift_score >= self.config.intent_drift_threshold
        warnings = self._build_warnings(changes, drift_score, intent_preserved)

        return IntentDriftResult(
            intent_preserved=intent_preserved,
            changes=changes,
            drift_score=drift_score,
            warnings=warnings,
            errors=[],
        )

    def compare_constraints(
        self,
        field: str,
        original: Any,
        refined: Any,
    ) -> IntentChange:
        """Compare a requires/ensures/effects field across refinement."""
        if field == "effects" or field.endswith(".effects"):
            return self._compare_effects(
                field,
                self._as_list(original),
                self._as_list(refined),
            )
        return self._compare_constraints(field, str(original), str(refined))

    def detect_intent_violation(
        self,
        original_spec: dict[str, Any],
        refined_spec: dict[str, Any],
        natural_language_intent: str | None = None,
    ) -> list[IntentChange]:
        """Detect explicit intent violations introduced by refinement."""
        changes: list[IntentChange] = []
        intent_text = (natural_language_intent or "").lower()

        for field in ("requires", "ensures", "effects"):
            if field not in original_spec or field in refined_spec:
                continue
            changes.append(
                IntentChange(
                    field=field,
                    original=str(original_spec[field]),
                    refined="",
                    change_type="removed",
                    intent_impact="violated",
                ),
            )

        if intent_text and "non-negative" in intent_text:
            refined_ensures = str(refined_spec.get("ensures", ""))
            if ">= 0" not in refined_ensures and "non-negative" not in refined_ensures:
                original_ensures = str(original_spec.get("ensures", ""))
                changes.append(
                    IntentChange(
                        field="ensures",
                        original=original_ensures,
                        refined=refined_ensures,
                        change_type="removed",
                        intent_impact="violated",
                    ),
                )

        return changes

    def _track_single_spec(
        self,
        prefix: str,
        original_spec: dict[str, Any],
        refined_spec: dict[str, Any],
    ) -> list[IntentChange]:
        changes: list[IntentChange] = []
        for field in ("requires", "ensures", "effects"):
            if field in original_spec and field in refined_spec:
                change = self.compare_constraints(
                    f"{prefix}{field}",
                    original_spec[field],
                    refined_spec[field],
                )
                changes.append(change)
            elif field in original_spec and field not in refined_spec:
                changes.append(
                    IntentChange(
                        field=f"{prefix}{field}",
                        original=str(original_spec[field]),
                        refined="",
                        change_type="removed",
                        intent_impact="violated",
                    ),
                )
        return changes

    def _track_atom_specs(
        self,
        original_spec: dict[str, Any],
        refined_spec: dict[str, Any],
    ) -> list[IntentChange]:
        original_atoms = self._atom_by_name(original_spec)
        refined_atoms = self._atom_by_name(refined_spec)
        changes: list[IntentChange] = []
        for atom_name, original_atom in original_atoms.items():
            refined_atom = refined_atoms.get(atom_name)
            if refined_atom is None:
                changes.append(
                    IntentChange(
                        field=f"atoms.{atom_name}",
                        original=str(original_atom),
                        refined="",
                        change_type="removed",
                        intent_impact="violated",
                    ),
                )
                continue
            changes.extend(
                self._track_single_spec(
                    f"atoms.{atom_name}.",
                    original_atom,
                    refined_atom,
                ),
            )
        return changes

    def _atom_by_name(self, spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
        atoms = spec.get("atoms")
        if not isinstance(atoms, list):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for index, atom in enumerate(atoms):
            if not isinstance(atom, dict):
                continue
            atom_name = str(atom.get("name") or index)
            result[atom_name] = atom
        return result

    def _compare_constraints(
        self,
        field: str,
        original: str,
        refined: str,
    ) -> IntentChange:
        """Compare a textual constraint change."""
        if original == refined:
            return IntentChange(
                field=field,
                original=original,
                refined=refined,
                change_type="unchanged",
                intent_impact="preserved",
            )

        if self._contains_constraint(refined, original):
            change_type = "strengthened"
            intent_impact = "strengthened"
        elif self._contains_constraint(original, refined):
            change_type = "weakened"
            intent_impact = "weakened"
        elif len(refined) > len(original):
            change_type = "strengthened"
            intent_impact = "strengthened"
        elif len(refined) < len(original):
            change_type = "weakened"
            intent_impact = "weakened"
        else:
            change_type = "replaced"
            intent_impact = "preserved"

        return IntentChange(
            field=field,
            original=original,
            refined=refined,
            change_type=change_type,
            intent_impact=intent_impact,
        )

    def _compare_effects(
        self,
        field: str,
        original: list[str],
        refined: list[str],
    ) -> IntentChange:
        """Compare effect-set changes."""
        if original == refined:
            change_type = "unchanged"
            intent_impact = "preserved"
        elif set(original).issubset(set(refined)):
            change_type = "strengthened"
            intent_impact = "strengthened"
        elif set(refined).issubset(set(original)):
            change_type = "weakened"
            intent_impact = "weakened"
        else:
            change_type = "replaced"
            intent_impact = "preserved"

        return IntentChange(
            field=field,
            original=str(original),
            refined=str(refined),
            change_type=change_type,
            intent_impact=intent_impact,
        )

    def _calculate_drift_score(self, changes: list[IntentChange]) -> float:
        """Calculate a 0.0-1.0 intent preservation score."""
        if not changes:
            return 1.0

        impact_scores = {
            "preserved": 1.0,
            "strengthened": 0.8,
            "weakened": 0.3,
            "violated": 0.0,
        }
        total_score = sum(
            impact_scores.get(change.intent_impact, 0.0)
            for change in changes
        )
        return total_score / len(changes)

    def _build_warnings(
        self,
        changes: list[IntentChange],
        drift_score: float,
        intent_preserved: bool,
    ) -> list[str]:
        warnings: list[str] = []
        if not intent_preserved:
            warnings.append(
                f"Intent drift detected (score: {drift_score:.2f}). "
                f"Threshold: {self.config.intent_drift_threshold:.2f}",
            )

        for change in changes:
            if change.intent_impact == "violated":
                warnings.append(
                    f"Intent violation in {change.field}: "
                    f"original '{change.original}' -> refined '{change.refined}'",
                )
        return warnings

    def _as_list(self, raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(item) for item in raw]
        return [str(raw)]

    def _contains_constraint(self, container: str, item: str) -> bool:
        normalized_container = self._normalize_constraint(container)
        normalized_item = self._normalize_constraint(item)
        if not normalized_item:
            return False
        return normalized_item in normalized_container

    def _normalize_constraint(self, constraint: str) -> str:
        return " ".join(constraint.replace("(", " ").replace(")", " ").split())
