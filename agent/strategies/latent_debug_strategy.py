"""Latent-space debug strategy for Mumei verification failures."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging

import numpy as np

from agent.latent_decoder import (
    EFFECT_ADD_INDEX,
    EFFECT_REMOVE_INDEX,
    ENSURES_WEAKEN_INDEX,
    REQUIRES_STRENGTHEN_INDEX,
    TYPE_REFINE_INDEX,
    LatentDecoder,
)
from agent.latent_encoder import LatentEncoder

logger = logging.getLogger(__name__)


class LatentDebugStrategy:
    """Try an NLAE-inspired latent repair before text-based strategies."""

    success_threshold = 0.30

    def get_fix_with_latent_debug(
        self,
        source_code: str,
        verification_report: Mapping[str, object],
        encoder: LatentEncoder,
        decoder: LatentDecoder,
    ) -> str | None:
        """Return latent-space repair candidate, or ``None`` on fallback."""
        try:
            latent_vector = encoder.encode_to_latent(
                source_code,
                verification_report,
            )
            probability = self._estimate_success_probability(verification_report)
            if probability < self.success_threshold:
                return None
            bug_direction = self._compute_bug_direction(
                latent_vector,
                verification_report,
            )
            if not np.any(bug_direction):
                return None
            corrected_vector = self._project_repair_vector(latent_vector, bug_direction)
            corrected_code = decoder.decode_to_source(
                corrected_vector,
                source_code,
                self._build_repair_context(verification_report),
            )
            if corrected_code != source_code:
                logger.info(
                    "Latent space debug produced a candidate fix with confidence %.2f",
                    probability,
                )
                return corrected_code
        except Exception:
            logger.warning(
                "Latent debug failed; falling back to text-based fix",
                exc_info=True,
            )
        return None

    def _compute_bug_direction(
        self,
        latent_vector: np.ndarray,
        verification_report: Mapping[str, object],
    ) -> np.ndarray:
        """Compute a deterministic latent bug direction from report metadata."""
        violation_type = self._violation_type(verification_report)
        direction = np.zeros_like(latent_vector)

        if "division_by_zero" in violation_type:
            self._set_direction(direction, REQUIRES_STRENGTHEN_INDEX, -0.95)
            self._set_direction(direction, TYPE_REFINE_INDEX, -0.35)
        elif "precondition" in violation_type:
            self._set_direction(direction, REQUIRES_STRENGTHEN_INDEX, -0.85)
        elif "postcondition" in violation_type:
            self._set_direction(direction, ENSURES_WEAKEN_INDEX, -0.75)
        elif "effect_mismatch" in violation_type or "effect_propagation" in violation_type:
            self._set_direction(direction, EFFECT_ADD_INDEX, -0.90)
        elif "temporal_effect" in violation_type:
            self._set_direction(direction, EFFECT_REMOVE_INDEX, -0.80)
        elif "invariant" in violation_type:
            self._set_direction(direction, ENSURES_WEAKEN_INDEX, -0.35)
            self._set_direction(direction, TYPE_REFINE_INDEX, -0.80)
        elif self._effect_violation(verification_report):
            self._set_direction(direction, EFFECT_ADD_INDEX, -0.70)

        if self._has_counterexample_zero(verification_report):
            self._set_direction(direction, REQUIRES_STRENGTHEN_INDEX, -0.25)
        return direction

    def _set_direction(self, direction: np.ndarray, index: int, value: float) -> None:
        if len(direction) > index:
            direction[index] = min(direction[index], value)

    def _project_repair_vector(
        self,
        latent_vector: np.ndarray,
        bug_direction: np.ndarray,
    ) -> np.ndarray:
        repair_vector = np.zeros_like(latent_vector)
        for index, value in enumerate(bug_direction):
            if value < 0:
                repair_vector[index] = min(1.0, abs(float(value)))
        return repair_vector

    def _estimate_success_probability(
        self,
        verification_report: Mapping[str, object],
    ) -> float:
        violation_type = self._violation_type(verification_report)
        if "effect_mismatch" in violation_type and self._effect_violation(verification_report):
            return 0.70
        if "effect_propagation" in violation_type and self._effect_violation(verification_report):
            return 0.65
        if "division_by_zero" in violation_type and self._has_counterexample_zero(verification_report):
            return 0.65
        if "precondition" in violation_type:
            return 0.45
        if "postcondition" in violation_type:
            return 0.35
        if "temporal_effect" in violation_type:
            return 0.30
        if "invariant" in violation_type:
            return 0.30
        if self._effect_violation(verification_report):
            return 0.35
        return 0.0

    def _build_repair_context(
        self,
        verification_report: Mapping[str, object],
    ) -> dict[str, object]:
        context: dict[str, object] = {}
        atom = verification_report.get("atom")
        if isinstance(atom, str):
            context["atom"] = atom
        effect_name = self._required_effect(verification_report)
        if effect_name:
            context["effect_name"] = effect_name
        effect_to_remove = self._effect_to_remove(verification_report)
        if effect_to_remove:
            context["effect_to_remove"] = effect_to_remove
        requires_constraint = self._requires_constraint(verification_report)
        if requires_constraint:
            context["requires_constraint"] = requires_constraint
        type_target = self._type_refinement_target(verification_report)
        if type_target:
            context["type_target"] = type_target
        return context

    def _violation_type(self, verification_report: Mapping[str, object]) -> str:
        return str(
            verification_report.get("violation_type")
            or verification_report.get("failure_type")
            or "",
        )

    def _effect_violation(self, verification_report: Mapping[str, object]) -> Mapping[str, object]:
        effect_violation = verification_report.get("effect_violation", {})
        if isinstance(effect_violation, Mapping):
            return effect_violation
        return {}

    def _required_effect(self, verification_report: Mapping[str, object]) -> str:
        effect_violation = self._effect_violation(verification_report)
        required = effect_violation.get("required_effect")
        if isinstance(required, str) and required.strip():
            return required.strip()
        missing = effect_violation.get("missing_effects")
        if isinstance(missing, Sequence) and not isinstance(missing, str):
            for effect in missing:
                if isinstance(effect, str) and effect.strip():
                    return effect.strip()
        operation = effect_violation.get("source_operation")
        if isinstance(operation, str) and "." in operation:
            return operation.split(".", 1)[0].strip()
        return ""

    def _effect_to_remove(self, verification_report: Mapping[str, object]) -> str:
        effect_violation = self._effect_violation(verification_report)
        for key in ("invalid_effect", "forbidden_effect", "effect_to_remove"):
            value = effect_violation.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        declared = effect_violation.get("declared_effects")
        if isinstance(declared, Sequence) and not isinstance(declared, str) and len(declared) > 1:
            value = declared[-1]
            if isinstance(value, str):
                return value.strip()
        return ""

    def _requires_constraint(self, verification_report: Mapping[str, object]) -> str:
        zero_name = self._first_zero_counterexample_name(verification_report)
        if zero_name:
            return f"{zero_name} != 0"
        negative_name = self._first_negative_counterexample_name(verification_report)
        if negative_name:
            return f"{negative_name} >= 0"
        semantic = verification_report.get("semantic_feedback", {})
        if isinstance(semantic, Mapping):
            expected = semantic.get("expected_precondition") or semantic.get("violated_precondition")
            if isinstance(expected, str) and expected.strip():
                return expected.strip()
        return ""

    def _type_refinement_target(self, verification_report: Mapping[str, object]) -> str:
        negative_name = self._first_negative_counterexample_name(verification_report)
        if negative_name:
            return negative_name
        zero_name = self._first_zero_counterexample_name(verification_report)
        return zero_name

    def _has_counterexample_zero(self, verification_report: Mapping[str, object]) -> bool:
        return bool(self._first_zero_counterexample_name(verification_report))

    def _first_zero_counterexample_name(self, verification_report: Mapping[str, object]) -> str:
        names = self._counterexample_names_matching(verification_report, "0")
        if not names:
            return ""
        return names[-1]

    def _first_negative_counterexample_name(self, verification_report: Mapping[str, object]) -> str:
        for name, value in self._counterexample_items(verification_report):
            try:
                if float(str(value)) < 0:
                    return name
            except ValueError:
                continue
        return ""

    def _counterexample_names_matching(
        self,
        verification_report: Mapping[str, object],
        expected: str,
    ) -> list[str]:
        return [
            name
            for name, value in self._counterexample_items(verification_report)
            if str(value) == expected
        ]

    def _counterexample_items(
        self,
        verification_report: Mapping[str, object],
    ) -> list[tuple[str, object]]:
        items: list[tuple[str, object]] = []
        counterexample = verification_report.get("counterexample", {})
        if isinstance(counterexample, Mapping):
            items.extend((str(name), value) for name, value in counterexample.items())
        semantic = verification_report.get("semantic_feedback", {})
        if isinstance(semantic, Mapping):
            semantic_counterexample = semantic.get("counter_example", {})
            if isinstance(semantic_counterexample, Mapping):
                items.extend((str(name), value) for name, value in semantic_counterexample.items())
        return items
