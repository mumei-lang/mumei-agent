"""High-density property generation and compression for Mumei code."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from openai import OpenAI


@dataclass(frozen=True)
class DenseCompressionStats:
    """Summary of contract compression performed after LLM generation."""

    original_predicates: int
    compressed_predicates: int
    original_chars: int
    compressed_chars: int

    @property
    def predicate_ratio(self) -> float:
        if self.original_predicates == 0:
            return 1.0
        return self.compressed_predicates / self.original_predicates

    @property
    def char_ratio(self) -> float:
        if self.original_chars == 0:
            return 1.0
        return self.compressed_chars / self.original_chars


_NUMERIC_BOUND_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_\.]*)\s*(>=|>|<=|<)\s*(-?\d+)$",
)
_CONTRACT_RE = re.compile(r"\b(requires|ensures)\s*:\s*([^;]+);", re.IGNORECASE)


class DensePropertyGenerator:
    """Generate compact requires/ensures clauses from specs and source."""

    def generate_dense_properties(
        self,
        spec: Mapping[str, object],
        source_code: str,
        client: OpenAI,
        model: str,
    ) -> dict[str, object]:
        """Return generated dense properties plus compression metadata."""
        current_properties = self._extract_properties(source_code)
        compressed = self._generate_compressed_repr(
            spec,
            current_properties,
            client,
            model,
        )
        decoded = self._decode_to_properties(compressed)
        return self._compress_properties(decoded)

    def _extract_properties(self, source_code: str) -> dict[str, list[str]]:
        """Extract current requires and ensures clauses."""
        properties: dict[str, list[str]] = {"requires": [], "ensures": []}
        for kind, expression in _CONTRACT_RE.findall(source_code):
            properties[kind.lower()].append(self._normalize_expression(expression))
        return properties

    def _generate_compressed_repr(
        self,
        spec: Mapping[str, object],
        current_properties: Mapping[str, list[str]],
        client: OpenAI,
        model: str,
    ) -> str:
        """Ask an LLM for compact mathematically precise properties."""
        from agent.prompts.dense_property import build_dense_property_prompt

        prompt = build_dense_property_prompt(spec, current_properties)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You synthesize Mumei contracts for Z3. Return only "
                        "solver-cheap requires/ensures clauses: quantifier-free "
                        "linear arithmetic first, no redundant predicates, and "
                        "no prose."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    def _decode_to_properties(self, compressed_repr: str) -> dict[str, object]:
        """Decode LLM text into property lists plus raw text."""
        requires: list[str] = []
        ensures: list[str] = []
        for kind, expression in _CONTRACT_RE.findall(compressed_repr):
            if kind.lower() == "requires":
                requires.append(expression)
            else:
                ensures.append(expression)
        return {"requires": requires, "ensures": ensures, "raw": compressed_repr}

    def _compress_properties(self, properties: Mapping[str, object]) -> dict[str, object]:
        """Compress decoded contract predicates using Z3-oriented heuristics."""
        requires = self._coerce_property_list(properties.get("requires"))
        ensures = self._coerce_property_list(properties.get("ensures"))
        raw = properties.get("raw")
        raw_text = raw if isinstance(raw, str) else ""
        original_predicates = sum(
            len(self._split_conjunction(expression))
            for expression in [*requires, *ensures]
        )
        original_chars = sum(len(expression) for expression in [*requires, *ensures])
        compressed_requires = self._compress_clause_list(requires)
        compressed_ensures = self._compress_clause_list(ensures)
        compressed_predicates = sum(
            len(self._split_conjunction(expression))
            for expression in [*compressed_requires, *compressed_ensures]
        )
        compressed_chars = sum(
            len(expression) for expression in [*compressed_requires, *compressed_ensures]
        )
        stats = DenseCompressionStats(
            original_predicates=original_predicates,
            compressed_predicates=compressed_predicates,
            original_chars=original_chars,
            compressed_chars=compressed_chars,
        )
        return {
            "requires": compressed_requires,
            "ensures": compressed_ensures,
            "raw": raw_text,
            "compression": {
                "original_predicates": stats.original_predicates,
                "compressed_predicates": stats.compressed_predicates,
                "predicate_ratio": stats.predicate_ratio,
                "original_chars": stats.original_chars,
                "compressed_chars": stats.compressed_chars,
                "char_ratio": stats.char_ratio,
            },
        }

    def _coerce_property_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item.strip()]

    def _compress_clause_list(self, clauses: list[str]) -> list[str]:
        compressed: list[str] = []
        for clause in clauses:
            parts = self._split_conjunction(clause)
            dense_parts = self._compress_predicates(parts)
            expression = " && ".join(dense_parts) if dense_parts else "true"
            if expression not in compressed:
                compressed.append(expression)
        return compressed

    def _compress_predicates(self, predicates: list[str]) -> list[str]:
        normalized = [
            self._normalize_expression(predicate)
            for predicate in predicates
            if self._normalize_expression(predicate).lower() != "true"
        ]
        deduped = list(dict.fromkeys(normalized))
        reduced = self._drop_redundant_numeric_bounds(deduped)
        return sorted(reduced, key=self._z3_cost_key)

    def _drop_redundant_numeric_bounds(self, predicates: list[str]) -> list[str]:
        strongest_lower: dict[str, tuple[str, int, bool]] = {}
        strongest_upper: dict[str, tuple[str, int, bool]] = {}
        passthrough: list[str] = []
        for predicate in predicates:
            match = _NUMERIC_BOUND_RE.match(predicate)
            if match is None:
                passthrough.append(predicate)
                continue
            variable, operator, raw_bound = match.groups()
            bound = int(raw_bound)
            strict = operator in {">", "<"}
            if operator in {">=", ">"}:
                current = strongest_lower.get(variable)
                if current is None or self._is_stronger_lower(
                    bound,
                    strict,
                    current[1],
                    current[2],
                ):
                    strongest_lower[variable] = (predicate, bound, strict)
            else:
                current = strongest_upper.get(variable)
                if current is None or self._is_stronger_upper(
                    bound,
                    strict,
                    current[1],
                    current[2],
                ):
                    strongest_upper[variable] = (predicate, bound, strict)
        bounds = [value[0] for value in strongest_lower.values()]
        bounds.extend(value[0] for value in strongest_upper.values())
        return [*bounds, *passthrough]

    def _is_stronger_lower(
        self,
        candidate_bound: int,
        candidate_strict: bool,
        current_bound: int,
        current_strict: bool,
    ) -> bool:
        return candidate_bound > current_bound or (
            candidate_bound == current_bound and candidate_strict and not current_strict
        )

    def _is_stronger_upper(
        self,
        candidate_bound: int,
        candidate_strict: bool,
        current_bound: int,
        current_strict: bool,
    ) -> bool:
        return candidate_bound < current_bound or (
            candidate_bound == current_bound and candidate_strict and not current_strict
        )

    def _split_conjunction(self, expression: str) -> list[str]:
        parts: list[str] = []
        depth = 0
        start = 0
        index = 0
        while index < len(expression):
            char = expression[index]
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            elif expression[index:index + 2] == "&&" and depth == 0:
                part = self._normalize_expression(expression[start:index])
                if part:
                    parts.append(part)
                start = index + 2
                index += 1
            index += 1
        tail = self._normalize_expression(expression[start:])
        if tail:
            parts.append(tail)
        return parts

    def _normalize_expression(self, expression: str) -> str:
        normalized = re.sub(r"\s+", " ", expression.strip())
        while normalized.startswith("(") and normalized.endswith(")"):
            inner = normalized[1:-1].strip()
            if not self._has_unbalanced_parens(inner):
                normalized = inner
            else:
                break
        return normalized

    def _has_unbalanced_parens(self, expression: str) -> bool:
        depth = 0
        for char in expression:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            if depth < 0:
                return True
        return depth != 0

    def _z3_cost_key(self, predicate: str) -> tuple[int, int, str]:
        quantifier_cost = 8 if re.search(r"\b(forall|exists)\b", predicate) else 0
        boolean_cost = predicate.count("||") * 4 + predicate.count("=>") * 4
        nonlinear_cost = len(re.findall(r"\b\w+\s*[*%]\s*\w+\b", predicate)) * 3
        function_cost = len(re.findall(r"\b[A-Za-z_]\w*\s*\(", predicate)) * 2
        array_cost = predicate.count("[") * 2
        return (
            quantifier_cost + boolean_cost + nonlinear_cost + function_cost + array_cost,
            len(predicate),
            predicate,
        )
