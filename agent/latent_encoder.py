"""Encode Mumei code and verifier state into latent feature vectors."""
from __future__ import annotations

import re
from typing import Any

import numpy as np


class LatentEncoder:
    """Mumei-specific NLAE-inspired latent encoder.

    The current implementation is intentionally lightweight and deterministic:
    it extracts structural, contract, and verifier-report features without
    depending on an external neural checkpoint.
    """

    def encode_to_latent(
        self,
        source_code: str,
        verification_report: dict[str, Any],
    ) -> np.ndarray:
        """Return a latent feature vector for source plus verification state."""
        syntax_features = self._extract_syntax_features(source_code)
        semantic_features = self._extract_semantic_features(source_code)
        verification_features = self._extract_verification_features(
            verification_report,
        )
        return self._combine_features(
            syntax_features,
            semantic_features,
            verification_features,
        )

    def _extract_syntax_features(self, source_code: str) -> np.ndarray:
        """Extract variable, type, control-flow, and size features."""
        var_names = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\s*:", source_code)
        types = re.findall(r":\s*(i64|bool|string|\w+)", source_code)
        control_flow = re.findall(r"\b(if|while|for|match)\b", source_code)
        atoms = re.findall(r"\batom\s+[A-Za-z_][A-Za-z0-9_]*", source_code)
        return np.array(
            [
                len(var_names),
                len(types),
                len(control_flow),
                len(source_code),
                len(atoms),
            ],
            dtype=np.float32,
        )

    def _extract_semantic_features(self, source_code: str) -> np.ndarray:
        """Extract requires/ensures/effects feature counts."""
        requires_matches = re.findall(r"requires\s*:\s*([^;]+);", source_code)
        ensures_matches = re.findall(r"ensures\s*:\s*([^;]+);", source_code)
        effects_matches = re.findall(r"effects\s*:\s*\[([^\]]*)\]", source_code)
        return np.array(
            [
                len(requires_matches),
                len(ensures_matches),
                sum(len(m) for m in requires_matches),
                sum(len(m) for m in ensures_matches),
                len(effects_matches),
            ],
            dtype=np.float32,
        )

    def _extract_verification_features(
        self,
        verification_report: dict[str, Any],
    ) -> np.ndarray:
        """Extract verifier failure and counterexample features."""
        violation_type = str(
            verification_report.get("violation_type")
            or verification_report.get("failure_type")
            or "",
        )
        counterexample = verification_report.get("counterexample", {})
        if not isinstance(counterexample, dict):
            counterexample = {}
        unsat_core = verification_report.get("structured_unsat_core", [])
        if not isinstance(unsat_core, list):
            unsat_core = []
        return np.array(
            [
                len(violation_type),
                len(counterexample),
                1.0 if violation_type else 0.0,
                len(unsat_core),
            ],
            dtype=np.float32,
        )

    def _combine_features(
        self,
        syntax: np.ndarray,
        semantic: np.ndarray,
        verification: np.ndarray,
    ) -> np.ndarray:
        """Combine extracted feature groups into one vector."""
        return np.concatenate([syntax, semantic, verification])
