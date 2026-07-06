"""Detect ambiguity in natural language specifications."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent import telemetry
from agent.config import AgentConfig
from agent.prompts.ambiguity_detection import (
    AMBIGUITY_DETECTION_SYSTEM_PROMPT,
    build_disambiguation_prompt,
)


@dataclass(frozen=True)
class AmbiguityFinding:
    """An ambiguity found in the specification."""

    ambiguous_text: str
    ambiguity_type: str
    location: str
    suggested_clarifications: list[str]


@dataclass(frozen=True)
class AmbiguityDetectionResult:
    """Result of ambiguity detection."""

    has_ambiguity: bool
    findings: list[AmbiguityFinding]
    warnings: list[str]
    errors: list[str]


class AmbiguityDetector:
    """Detect ambiguity in natural language specifications."""

    AMBIGUOUS_PATTERNS: dict[str, list[str]] = {
        "vague_adjective": [
            r"適切な",
            r"十分な",
            r"合理的な",
            r"妥当な",
            r"適切に",
            r"十分に",
            r"\bappropriate\b",
            r"\bsufficient\b",
            r"\breasonable\b",
            r"\badequate\b",
        ],
        "quantifier": [
            r"可能な限り",
            r"必要に応じて",
            r"場合によっては",
            r"適時",
            r"\bas much as possible\b",
            r"\bwhen needed\b",
            r"\bas needed\b",
            r"\bfrom time to time\b",
        ],
        "conditional": [
            r"もし.*?なら",
            r"[^。.\n]*場合",
            r"[^。.\n]*時",
            r"\bif\b[^.。\n]*\bthen\b",
            r"\bwhen\b[^.。\n]*",
        ],
    }

    VALID_AMBIGUITY_TYPES = frozenset(AMBIGUOUS_PATTERNS)

    def __init__(self, config: AgentConfig):
        self.config = config

    def detect_ambiguity(
        self,
        natural_language: str,
        use_llm: bool = True,
    ) -> AmbiguityDetectionResult:
        """Detect ambiguity in a natural-language specification."""
        warnings: list[str] = []
        errors: list[str] = []
        if not natural_language.strip():
            return AmbiguityDetectionResult(
                has_ambiguity=False,
                findings=[],
                warnings=[],
                errors=["natural_language must be non-empty"],
            )

        findings = self._detect_with_patterns(natural_language)
        if use_llm and self.config.enable_ambiguity_detection:
            llm_findings, llm_warnings = self._detect_with_llm(natural_language)
            findings.extend(llm_findings)
            warnings.extend(llm_warnings)

        findings = self._deduplicate_findings(findings)
        return AmbiguityDetectionResult(
            has_ambiguity=bool(findings),
            findings=findings,
            warnings=warnings,
            errors=errors,
        )

    def suggest_disambiguation(self, finding: AmbiguityFinding | str) -> list[str]:
        """Return clarification options for a finding or ambiguity type."""
        if isinstance(finding, AmbiguityFinding):
            if finding.suggested_clarifications:
                return finding.suggested_clarifications
            return self._get_suggestions(finding.ambiguity_type, finding.ambiguous_text)
        return self._get_suggestions(finding, "")

    def _detect_with_patterns(self, natural_language: str) -> list[AmbiguityFinding]:
        findings: list[AmbiguityFinding] = []
        for ambiguity_type, patterns in self.AMBIGUOUS_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, natural_language, re.IGNORECASE):
                    text = match.group().strip()
                    findings.append(
                        AmbiguityFinding(
                            ambiguous_text=text,
                            ambiguity_type=ambiguity_type,
                            location=f"Position {match.start()}-{match.end()}",
                            suggested_clarifications=self._get_suggestions(
                                ambiguity_type,
                                text,
                            ),
                        )
                    )
        return findings

    def _get_suggestions(self, ambiguity_type: str, text: str) -> list[str]:
        target = f"'{text}'" if text else "the expression"
        suggestions = {
            "vague_adjective": [
                f"Replace {target} with a concrete numeric threshold or formal condition.",
                f"Define exactly what {target} means for this domain.",
            ],
            "quantifier": [
                f"Replace {target} with explicit scope, timing, or trigger conditions.",
                f"State whether {target} is mandatory, optional, or best-effort.",
            ],
            "conditional": [
                f"Clarify the exact branch condition for {target}.",
                f"Specify the else case or default behavior for {target}.",
            ],
        }
        return suggestions.get(ambiguity_type, [])

    def _detect_with_llm(
        self,
        natural_language: str,
    ) -> tuple[list[AmbiguityFinding], list[str]]:
        try:
            client = self.config.create_client()
            tracer = telemetry.get_tracer(__name__)
            with tracer.start_as_current_span("llm.ambiguity_detection") as span:
                span.set_attribute("gen_ai.system", "openai-compatible")
                span.set_attribute("gen_ai.request.model", self.config.model)
                response = client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": AMBIGUITY_DETECTION_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": build_disambiguation_prompt(natural_language),
                        },
                    ],
                    response_format={"type": "json_object"},
                )
            raw = response.choices[0].message.content or ""
            payload = json.loads(raw)
        except (ValueError, json.JSONDecodeError, AttributeError, TypeError) as exc:
            return [], [f"LLM ambiguity detection skipped: {exc}"]

        return self._findings_from_payload(payload), []

    def _findings_from_payload(self, payload: object) -> list[AmbiguityFinding]:
        if isinstance(payload, dict):
            raw_findings = payload.get("findings", [])
        else:
            raw_findings = payload
        if not isinstance(raw_findings, list):
            return []

        findings: list[AmbiguityFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            ambiguity_type = item.get("ambiguity_type")
            ambiguous_text = item.get("ambiguous_text")
            location = item.get("location")
            if (
                not isinstance(ambiguity_type, str)
                or ambiguity_type not in self.VALID_AMBIGUITY_TYPES
                or not isinstance(ambiguous_text, str)
                or not ambiguous_text.strip()
            ):
                continue
            suggestions = item.get("suggested_clarifications", [])
            if not isinstance(suggestions, list):
                suggestions = []
            findings.append(
                AmbiguityFinding(
                    ambiguous_text=ambiguous_text.strip(),
                    ambiguity_type=ambiguity_type,
                    location=location if isinstance(location, str) else "LLM finding",
                    suggested_clarifications=[
                        suggestion
                        for suggestion in suggestions
                        if isinstance(suggestion, str) and suggestion.strip()
                    ],
                )
            )
        return findings

    def _deduplicate_findings(
        self,
        findings: list[AmbiguityFinding],
    ) -> list[AmbiguityFinding]:
        deduplicated: list[AmbiguityFinding] = []
        seen: set[tuple[str, str]] = set()
        for finding in findings:
            key = (finding.ambiguity_type, finding.ambiguous_text.lower())
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(finding)
        return deduplicated
