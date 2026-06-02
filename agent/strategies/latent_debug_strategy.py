"""Latent-space debug strategy for Mumei verification failures."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging

import numpy as np

from agent.latent_decoder import (
    ASSERTION_ADD_INDEX,
    EFFECT_ADD_INDEX,
    EFFECT_REMOVE_INDEX,
    ENSURES_WEAKEN_INDEX,
    LOOP_INVARIANT_INDEX,
    REQUIRES_STRENGTHEN_INDEX,
    TYPE_REFINE_INDEX,
    VARIABLE_REFACTOR_INDEX,
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
            threshold = self._adaptive_success_threshold(verification_report)
            if probability < threshold:
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
        """Compute an adaptive latent bug direction from report metadata."""
        return self._compute_adaptive_bug_direction(latent_vector, verification_report)

    def _compute_adaptive_bug_direction(
        self,
        latent_vector: np.ndarray,
        verification_report: Mapping[str, object],
    ) -> np.ndarray:
        """Blend rule, linear-model, and historical bug-direction estimates."""
        direction = self._compute_rule_bug_direction(latent_vector, verification_report)
        threshold = self._adaptive_success_threshold(verification_report)

        for index, confidence in self._linear_model_direction_scores(verification_report).items():
            if confidence >= threshold:
                self._set_direction(direction, index, -confidence)

        for pattern in self._load_historical_patterns(verification_report):
            if not self._pattern_matches_report(pattern, verification_report):
                continue
            index = self._pattern_index(pattern)
            if index < 0:
                continue
            confidence = self._pattern_confidence(pattern)
            if confidence >= threshold:
                self._set_direction(direction, index, -confidence)
        return direction

    def _compute_rule_bug_direction(
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
            self._set_direction(direction, LOOP_INVARIANT_INDEX, -0.90)
            self._set_direction(direction, ASSERTION_ADD_INDEX, -0.55)
            self._set_direction(direction, TYPE_REFINE_INDEX, -0.80)
        elif "assert" in violation_type:
            self._set_direction(direction, ASSERTION_ADD_INDEX, -0.80)
        elif "data_flow" in violation_type or "unbound" in violation_type:
            self._set_direction(direction, ASSERTION_ADD_INDEX, -0.65)
            self._set_direction(direction, VARIABLE_REFACTOR_INDEX, -0.45)
        elif self._name_violation(violation_type):
            self._set_direction(direction, VARIABLE_REFACTOR_INDEX, -0.85)
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

    def _adaptive_success_threshold(
        self,
        verification_report: Mapping[str, object],
    ) -> float:
        success_rates = [
            self._pattern_success_rate(pattern)
            for pattern in self._load_historical_patterns(verification_report)
            if self._pattern_matches_report(pattern, verification_report)
        ]
        if not success_rates:
            return self.success_threshold
        average_success = sum(success_rates) / len(success_rates)
        threshold = self.success_threshold + (self.success_threshold - average_success) * 0.4
        return max(0.20, min(0.50, threshold))

    def _estimate_success_probability(
        self,
        verification_report: Mapping[str, object],
    ) -> float:
        violation_type = self._violation_type(verification_report)
        if "effect_mismatch" in violation_type and self._effect_violation(verification_report):
            return 0.70
        if "effect_propagation" in violation_type and self._effect_violation(verification_report):
            return 0.65
        if "division_by_zero" in violation_type and self._has_counterexample_zero(
            verification_report,
        ):
            return 0.65
        if "precondition" in violation_type:
            return 0.45
        if "postcondition" in violation_type:
            return 0.35
        if "temporal_effect" in violation_type:
            return 0.30
        if "invariant" in violation_type:
            return 0.42
        if "assert" in violation_type:
            return 0.36
        if "data_flow" in violation_type or "unbound" in violation_type:
            return 0.34
        if self._name_violation(violation_type):
            return 0.36
        if self._effect_violation(verification_report):
            return 0.35
        historical_matches = [
            self._pattern_success_rate(pattern)
            for pattern in self._load_historical_patterns(verification_report)
            if self._pattern_matches_report(pattern, verification_report)
        ]
        if historical_matches:
            return max(historical_matches)
        return 0.0

    def _linear_model_direction_scores(
        self,
        verification_report: Mapping[str, object],
    ) -> dict[int, float]:
        violation_type = self._violation_type(verification_report)
        features = np.array(
            [
                1.0 if "precondition" in violation_type else 0.0,
                1.0 if "postcondition" in violation_type else 0.0,
                1.0
                if "effect" in violation_type or self._effect_violation(verification_report)
                else 0.0,
                1.0 if "temporal" in violation_type else 0.0,
                1.0 if "invariant" in violation_type or "loop" in violation_type else 0.0,
                1.0 if "assert" in violation_type else 0.0,
                1.0 if "data_flow" in violation_type or "unbound" in violation_type else 0.0,
                1.0 if self._name_violation(violation_type) else 0.0,
                1.0 if self._has_counterexample_zero(verification_report) else 0.0,
                1.0 if self._first_negative_counterexample_name(verification_report) else 0.0,
                self._historical_bias(verification_report),
            ],
            dtype=np.float32,
        )
        weights = {
            REQUIRES_STRENGTHEN_INDEX: np.array(
                [1.2, 0.0, 0.0, 0.0, 0.1, 0.2, 0.3, 0.0, 0.8, 0.7, 0.4],
            ),
            ENSURES_WEAKEN_INDEX: np.array([0.0, 0.8, 0.0, 0.0, 0.2, 0.1, 0.1, 0.0, 0.0, 0.0, 0.2]),
            EFFECT_ADD_INDEX: np.array([0.0, 0.0, 1.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.3]),
            EFFECT_REMOVE_INDEX: np.array([0.0, 0.0, 0.2, 1.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.2]),
            LOOP_INVARIANT_INDEX: np.array([0.0, 0.0, 0.0, 0.0, 1.4, 0.2, 0.2, 0.0, 0.0, 0.2, 0.4]),
            ASSERTION_ADD_INDEX: np.array([0.3, 0.8, 0.0, 0.0, 0.7, 1.2, 0.9, 0.0, 0.4, 0.4, 0.3]),
            VARIABLE_REFACTOR_INDEX: np.array(
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 1.4, 0.0, 0.0, 0.3],
            ),
        }
        scores: dict[int, float] = {}
        for index, weight in weights.items():
            raw_score = float(np.dot(features, weight) - 1.10)
            scores[index] = float(1.0 / (1.0 + np.exp(-raw_score)))
        return scores

    def _load_historical_patterns(
        self,
        verification_report: Mapping[str, object],
    ) -> list[dict[str, object]]:
        defaults: list[dict[str, object]] = [
            {
                "violation_type": "division_by_zero",
                "edit": "requires",
                "confidence": 0.82,
                "success_rate": 0.48,
            },
            {
                "violation_type": "effect_mismatch",
                "edit": "effect_add",
                "confidence": 0.84,
                "success_rate": 0.44,
            },
            {
                "violation_type": "temporal_effect",
                "edit": "effect_remove",
                "confidence": 0.76,
                "success_rate": 0.34,
            },
            {
                "violation_type": "invariant",
                "edit": "loop_invariant",
                "confidence": 0.86,
                "success_rate": 0.40,
            },
            {
                "violation_type": "postcondition",
                "edit": "assertion",
                "confidence": 0.64,
                "success_rate": 0.32,
            },
            {
                "violation_type": "variable",
                "edit": "rename",
                "confidence": 0.78,
                "success_rate": 0.36,
            },
            {
                "violation_type": "data_flow",
                "edit": "assertion",
                "confidence": 0.66,
                "success_rate": 0.31,
            },
        ]
        configured = verification_report.get("historical_patterns", [])
        if isinstance(configured, Sequence) and not isinstance(configured, str):
            for pattern in configured:
                if isinstance(pattern, Mapping):
                    defaults.append(dict(pattern))
        return defaults

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
        loop_invariant = self._loop_invariant(verification_report)
        if loop_invariant:
            context["loop_invariant"] = loop_invariant
        assertion = self._assertion_condition(verification_report)
        if assertion:
            context["assertion"] = assertion
        rename_map = self._rename_map(verification_report)
        if rename_map:
            context["rename_map"] = rename_map
        return context

    def _historical_bias(self, verification_report: Mapping[str, object]) -> float:
        rates = [
            self._pattern_success_rate(pattern)
            for pattern in self._load_historical_patterns(verification_report)
            if self._pattern_matches_report(pattern, verification_report)
        ]
        if not rates:
            return 0.0
        return max(rates)

    def _pattern_matches_report(
        self,
        pattern: Mapping[str, object],
        verification_report: Mapping[str, object],
    ) -> bool:
        pattern_type = pattern.get("violation_type") or pattern.get("failure_type") or ""
        current_type = self._violation_type(verification_report)
        if not isinstance(pattern_type, str) or not pattern_type:
            return False
        return pattern_type in current_type or current_type in pattern_type

    def _pattern_index(self, pattern: Mapping[str, object]) -> int:
        vector_index = pattern.get("vector_index")
        if isinstance(vector_index, int):
            return vector_index
        edit = pattern.get("edit")
        if not isinstance(edit, str):
            return -1
        return {
            "requires": REQUIRES_STRENGTHEN_INDEX,
            "ensures": ENSURES_WEAKEN_INDEX,
            "effect_add": EFFECT_ADD_INDEX,
            "effect_remove": EFFECT_REMOVE_INDEX,
            "type_refine": TYPE_REFINE_INDEX,
            "loop_invariant": LOOP_INVARIANT_INDEX,
            "assertion": ASSERTION_ADD_INDEX,
            "rename": VARIABLE_REFACTOR_INDEX,
        }.get(edit, -1)

    def _pattern_confidence(self, pattern: Mapping[str, object]) -> float:
        confidence = pattern.get("confidence")
        if isinstance(confidence, int | float):
            return max(0.0, min(1.0, float(confidence)))
        return 0.50

    def _pattern_success_rate(self, pattern: Mapping[str, object]) -> float:
        success_rate = pattern.get("success_rate")
        if isinstance(success_rate, int | float):
            return max(0.0, min(1.0, float(success_rate)))
        return self._pattern_confidence(pattern)

    def _violation_type(self, verification_report: Mapping[str, object]) -> str:
        return str(
            verification_report.get("violation_type")
            or verification_report.get("failure_type")
            or "",
        )

    def _name_violation(self, violation_type: str) -> bool:
        return (
            "shadow" in violation_type
            or "variable" in violation_type
            or "identifier" in violation_type
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
            expected = semantic.get("expected_precondition") or semantic.get(
                "violated_precondition",
            )
            if isinstance(expected, str) and expected.strip():
                return expected.strip()
        return ""

    def _loop_invariant(self, verification_report: Mapping[str, object]) -> str:
        for key in ("loop_invariant", "invariant"):
            value = verification_report.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        semantic = verification_report.get("semantic_feedback", {})
        if isinstance(semantic, Mapping):
            for key in ("expected_invariant", "loop_invariant", "violated_invariant"):
                value = semantic.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        negative_name = self._first_negative_counterexample_name(verification_report)
        if negative_name:
            return f"{negative_name} >= 0"
        return "true" if "invariant" in self._violation_type(verification_report) else ""

    def _assertion_condition(self, verification_report: Mapping[str, object]) -> str:
        for key in ("assertion", "assertion_condition"):
            value = verification_report.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        semantic = verification_report.get("semantic_feedback", {})
        if isinstance(semantic, Mapping):
            for key in ("expected_assertion", "violated_postcondition", "failing_condition"):
                value = semantic.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        negative_name = self._first_negative_counterexample_name(verification_report)
        if negative_name:
            return f"{negative_name} >= 0"
        zero_name = self._first_zero_counterexample_name(verification_report)
        if zero_name:
            return f"{zero_name} != 0"
        return "true" if "assert" in self._violation_type(verification_report) else ""

    def _rename_map(self, verification_report: Mapping[str, object]) -> dict[str, str]:
        rename_map = self._coerce_rename_map(verification_report.get("rename_map"))
        if rename_map:
            return rename_map
        semantic = verification_report.get("semantic_feedback", {})
        if isinstance(semantic, Mapping):
            rename_map = self._coerce_rename_map(semantic.get("rename_map"))
            if rename_map:
                return rename_map
        old_name = verification_report.get("variable")
        new_name = verification_report.get("suggested_variable")
        if isinstance(old_name, str) and isinstance(new_name, str):
            return {old_name: new_name}
        return {}

    def _coerce_rename_map(self, value: object) -> dict[str, str]:
        if not isinstance(value, Mapping):
            return {}
        rename_map: dict[str, str] = {}
        for old_name, new_name in value.items():
            if isinstance(old_name, str) and isinstance(new_name, str):
                if old_name.strip() and new_name.strip():
                    rename_map[old_name.strip()] = new_name.strip()
        return rename_map

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
