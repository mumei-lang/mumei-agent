"""Check the health of the AI code generation process."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from agent.config import AgentConfig


@dataclass
class HealthCheckResult:
    """Result of generation health check."""

    is_healthy: bool
    spec_adherence_score: float
    code_diversity_score: float
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class GenerationHealthChecker:
    """Check whether generated code follows the current specification."""

    _STOP_WORDS = {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "can",
        "her",
        "was",
        "one",
        "our",
        "out",
        "with",
        "from",
        "this",
        "that",
        "true",
        "false",
        "null",
        "none",
        "body",
        "atom",
        "type",
        "name",
        "params",
        "requires",
        "ensures",
        "description",
        "return_type",
        "effects",
        "inputs",
        "module_name",
        "atoms",
    }

    def __init__(self, config: AgentConfig):
        self.config = config
        self.past_code_examples: list[str] = []

    def check_generation_health(
        self,
        spec_text: str,
        generated_code: str,
        generation_metadata: Mapping[str, object] | None = None,
    ) -> HealthCheckResult:
        """Check generation health without relying on an LLM API."""
        del generation_metadata

        warnings: list[str] = []
        errors: list[str] = []

        spec_adherence = self.check_spec_adherence(spec_text, generated_code)
        if spec_adherence < 0.5:
            warnings.append(
                f"Low spec adherence score: {spec_adherence:.2f}. "
                "The generated code may not follow the specification."
            )

        diversity = self.check_code_diversity(generated_code)
        if diversity < 0.3:
            warnings.append(
                f"Low code diversity score: {diversity:.2f}. "
                "The generated code may be copying from past examples."
            )

        is_healthy = (
            spec_adherence >= 0.3 or self._has_spec_name_anchor(spec_text, generated_code)
        ) and diversity >= 0.2

        return HealthCheckResult(
            is_healthy=is_healthy,
            spec_adherence_score=spec_adherence,
            code_diversity_score=diversity,
            warnings=warnings,
            errors=errors,
        )

    def check_spec_adherence(self, spec_text: str, generated_code: str) -> float:
        """Score whether important specification keywords appear in code."""
        spec_keywords = self._extract_keywords(spec_text)
        if not spec_keywords:
            return 1.0

        code_tokens = self._tokenize(generated_code)
        if not code_tokens:
            return 0.0

        matched = sum(1 for keyword in spec_keywords if keyword.lower() in code_tokens)
        return matched / len(spec_keywords)

    def check_code_diversity(self, generated_code: str) -> float:
        """Score generated code diversity against previous examples."""
        if not self.past_code_examples:
            return 1.0

        generated_tokens = self._tokenize(generated_code)
        if not generated_tokens:
            return 0.0

        max_similarity = 0.0
        for past_code in self.past_code_examples:
            past_tokens = self._tokenize(past_code)
            if not past_tokens:
                continue
            intersection = generated_tokens & past_tokens
            union = generated_tokens | past_tokens
            similarity = len(intersection) / len(union)
            max_similarity = max(max_similarity, similarity)

        return 1.0 - max_similarity

    def add_past_example(self, code: str) -> None:
        """Add a prior code example for diversity comparison."""
        self.past_code_examples.append(code)

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract unique, stable keywords from specification text."""
        words = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", text)
        keywords: list[str] = []
        seen: set[str] = set()
        for word in words:
            lowered = word.lower()
            if lowered in self._STOP_WORDS or lowered in seen:
                continue
            seen.add(lowered)
            keywords.append(word)
        return keywords

    def _has_spec_name_anchor(self, spec_text: str, generated_code: str) -> bool:
        code_tokens = self._tokenize(generated_code)
        return any(name.lower() in code_tokens for name in self._extract_spec_names(spec_text))

    def _extract_spec_names(self, spec_text: str) -> list[str]:
        try:
            payload = json.loads(spec_text)
        except json.JSONDecodeError:
            return []

        names: list[str] = []

        def collect(value: object) -> None:
            if isinstance(value, Mapping):
                for key, nested in value.items():
                    if key in {"name", "module_name"} and isinstance(nested, str):
                        names.extend(self._split_identifier(nested))
                    collect(nested)
                return
            if isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        return names

    def _split_identifier(self, value: str) -> list[str]:
        return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", value)

    def _tokenize(self, text: str) -> set[str]:
        return {word.lower() for word in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text)}
