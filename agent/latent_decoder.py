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
        if len(latent_vector) > 10 and latent_vector[10] > 0.5:
            return self._add_effect(original_code, "Write")
        if len(latent_vector) > 11 and latent_vector[11] > 0.5:
            return self._remove_first_effect(original_code)
        if len(latent_vector) > 12 and latent_vector[12] > 0.5:
            return self._refine_i64_types(original_code)
        if len(latent_vector) > 5 and latent_vector[5] > 0.5:
            return self._strengthen_first_requires(original_code)
        if len(latent_vector) > 6 and latent_vector[6] > 0.5:
            return self._weaken_ensures(original_code)
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

    def _weaken_ensures(self, source_code: str) -> str:
        """Weaken the first ensures clause by replacing one conjunct with true."""
        return re.sub(
            r"(ensures\s*:\s*)([^;]+)(;)",
            lambda match: (
                f"{match.group(1)}{self._remove_one_conjunct(match.group(2))}"
                f"{match.group(3)}"
            ),
            source_code,
            count=1,
        )

    def _remove_one_conjunct(self, expression: str) -> str:
        """Return an ensures expression with one top-level conjunct weakened."""
        conjuncts = self._split_top_level_conjuncts(expression)
        if len(conjuncts) <= 1:
            return expression.strip()
        return " && ".join([*conjuncts[:-1], "true"])

    def _split_top_level_conjuncts(self, expression: str) -> list[str]:
        conjuncts: list[str] = []
        start = 0
        depth = 0
        i = 0
        while i < len(expression):
            char = expression[i]
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif expression.startswith("&&", i) and depth == 0:
                part = expression[start:i].strip()
                if part:
                    conjuncts.append(part)
                i += 2
                start = i
                continue
            i += 1
        tail = expression[start:].strip()
        if tail:
            conjuncts.append(tail)
        return conjuncts

    def _add_effect(self, source_code: str, effect_name: str) -> str:
        """Add an effect to the first effects clause or create one after the header."""
        effects_match = re.search(r"(effects\s*:\s*\[)([^\]]*)(\])", source_code)
        if effects_match:
            existing = [
                effect.strip()
                for effect in effects_match.group(2).split(",")
                if effect.strip()
            ]
            if effect_name in existing:
                return source_code
            selected = self._choose_effect_name(effect_name, existing)
            if selected in existing:
                return source_code
            updated = ", ".join([*existing, selected])
            return (
                source_code[:effects_match.start()]
                + f"{effects_match.group(1)}{updated}{effects_match.group(3)}"
                + source_code[effects_match.end():]
            )
        selected = self._choose_effect_name(effect_name, [])
        return re.sub(
            r"(\batom\s+[A-Za-z_][A-Za-z0-9_]*[^\n]*\n)",
            f"\\1    effects: [{selected}];\n",
            source_code,
            count=1,
        )

    def _choose_effect_name(self, fallback: str, existing: list[str]) -> str:
        for effect in existing:
            words = effect.split()
            if len(words) > 1:
                return words[0]
        return fallback

    def _remove_first_effect(self, source_code: str) -> str:
        """Remove one effect entry from the first effects clause."""
        def replace(match: re.Match[str]) -> str:
            effects = [
                effect.strip()
                for effect in match.group(2).split(",")
                if effect.strip()
            ]
            if len(effects) <= 1:
                return f"{match.group(1)}{match.group(2)}{match.group(3)}"
            return f"{match.group(1)}{', '.join(effects[1:])}{match.group(3)}"

        return re.sub(r"(effects\s*:\s*\[)([^\]]*)(\])", replace, source_code, count=1)

    def _refine_i64_types(self, source_code: str) -> str:
        """Refine obviously boolean local bindings to bool annotations."""
        local_refinement = re.sub(
            r"\blet\s+(is_[A-Za-z0-9_]*|has_[A-Za-z0-9_]*|flag)\s*=\s*(true|false)\b",
            lambda match: f"let {match.group(1)}: bool = {match.group(2)}",
            source_code,
            count=1,
        )
        if local_refinement != source_code:
            return local_refinement
        return source_code
