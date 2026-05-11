"""Latent-space debug strategy for Mumei verification failures."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from agent.latent_decoder import LatentDecoder
from agent.latent_encoder import LatentEncoder

logger = logging.getLogger(__name__)


class LatentDebugStrategy:
    """Try an NLAE-inspired latent repair before text-based strategies."""

    def get_fix_with_latent_debug(
        self,
        source_code: str,
        verification_report: dict[str, Any],
        encoder: LatentEncoder,
        decoder: LatentDecoder,
    ) -> str | None:
        """Return latent-space repair candidate, or ``None`` on fallback."""
        try:
            latent_vector = encoder.encode_to_latent(
                source_code,
                verification_report,
            )
            bug_direction = self._compute_bug_direction(
                latent_vector,
                verification_report,
            )
            corrected_vector = latent_vector - bug_direction
            corrected_code = decoder.decode_to_source(
                corrected_vector,
                source_code,
            )
            if corrected_code != source_code:
                logger.info("Latent space debug produced a candidate fix")
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
        verification_report: dict[str, Any],
    ) -> np.ndarray:
        """Compute a deterministic latent bug direction from report metadata."""
        violation_type = str(
            verification_report.get("violation_type")
            or verification_report.get("failure_type")
            or "",
        )
        direction = np.zeros_like(latent_vector)

        if "division_by_zero" in violation_type and len(direction) > 0:
            direction[0] = 0.1
        elif "precondition" in violation_type and len(direction) > 5:
            direction[5] = 0.1
        elif "postcondition" in violation_type and len(direction) > 6:
            direction[6] = 0.1
        elif "effect_mismatch" in violation_type and len(direction) > 10:
            direction[10] = -0.75
        elif "temporal_effect" in violation_type and len(direction) > 11:
            direction[11] = -0.75
        elif "invariant" in violation_type and len(direction) > 6:
            direction[6] = 0.15
            if len(direction) > 12:
                direction[12] = -0.75

        return direction
