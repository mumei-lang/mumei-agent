"""High-density property generation for Mumei code."""
from __future__ import annotations

import re
from typing import Any

from openai import OpenAI


class DensePropertyGenerator:
    """Generate compact requires/ensures clauses from specs and source."""

    def generate_dense_properties(
        self,
        spec: dict[str, Any],
        source_code: str,
        client: OpenAI,
        model: str,
    ) -> dict[str, Any]:
        """Return generated dense properties."""
        current_properties = self._extract_properties(source_code)
        compressed = self._generate_compressed_repr(
            spec,
            current_properties,
            client,
            model,
        )
        return self._decode_to_properties(compressed)

    def _extract_properties(self, source_code: str) -> dict[str, Any]:
        """Extract current requires and ensures clauses."""
        return {
            "requires": re.findall(r"requires\s*:\s*([^;]+);", source_code),
            "ensures": re.findall(r"ensures\s*:\s*([^;]+);", source_code),
        }

    def _generate_compressed_repr(
        self,
        spec: dict[str, Any],
        current_properties: dict[str, Any],
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
                        "You are a helpful programming assistant specializing "
                        "in Mumei contracts. Generate high-density, "
                        "mathematically precise properties."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    def _decode_to_properties(self, compressed_repr: str) -> dict[str, Any]:
        """Decode LLM text into property lists plus raw text."""
        return {
            "requires": re.findall(r"requires\s*:\s*([^;]+);", compressed_repr),
            "ensures": re.findall(r"ensures\s*:\s*([^;]+);", compressed_repr),
            "raw": compressed_repr,
        }
