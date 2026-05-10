"""Decode latent feature vectors back into conservative Mumei code edits."""
from __future__ import annotations

import re

import numpy as np


class LatentDecoder:
    """Mumei-specific NLAE-inspired latent decoder."""

    def decode_to_source(self, latent_vector: np.ndarray, original_code: str) -> str:
        """Decode a latent vector into source while preserving structure."""
        return self._apply_latent_changes(original_code, latent_vector)

    def _apply_latent_changes(
        self,
        original_code: str,
        latent_vector: np.ndarray,
    ) -> str:
        """Apply conservative latent edits that can safely fall back."""
        if len(latent_vector) > 5 and latent_vector[5] > 0.5:
            return self._strengthen_first_requires(original_code)
        return original_code

    def _strengthen_first_requires(self, source_code: str) -> str:
        """Strengthen the first requires clause with a neutral tautology."""
        return re.sub(
            r"(requires\s*:\s*)([^;]+)(;)",
            lambda match: (
                match.group(0)
                if "&& true" in match.group(2)
                else f"{match.group(1)}({match.group(2).strip()}) && true{match.group(3)}"
            ),
            source_code,
            count=1,
        )
