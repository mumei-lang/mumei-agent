"""Prompt template for ambiguity detection in natural language specifications."""

import json

AMBIGUITY_DETECTION_SYSTEM_PROMPT = (
    "You are a specification analyst for proof-oriented requirements. "
    "Identify ambiguous requirements before they are converted to formal "
    "preconditions, postconditions, effects, and atom boundaries. "
    "Focus on vague adjectives, underspecified quantifiers, and conditional "
    "branches that need explicit trigger, threshold, or else-case semantics. "
    "Output ONLY valid JSON."
)


def build_disambiguation_prompt(natural_language: str) -> str:
    """Build a prompt for detecting ambiguity in a natural-language spec."""
    schema = {
        "findings": [
            {
                "ambiguous_text": "適切な",
                "ambiguity_type": "vague_adjective",
                "location": "sentence 1",
                "suggested_clarifications": [
                    "Replace the phrase with a numeric threshold.",
                    "Define the condition under which the requirement holds.",
                ],
            }
        ]
    }
    return "\n".join(
        [
            "# Task",
            "Analyze the following natural-language specification for ambiguity.",
            "",
            "# Ambiguity categories",
            "- vague_adjective: vague qualifiers such as appropriate, sufficient, reasonable, 妥当な, 十分な.",
            "- quantifier: non-actionable scope or timing such as as much as possible, when needed, 適時.",
            "- conditional: conditionals that omit exact triggers, outcomes, or else cases.",
            "",
            "# Output schema",
            "Return a JSON object matching this shape:",
            "```json",
            json.dumps(schema, indent=2, ensure_ascii=False),
            "```",
            "",
            "# Specification",
            natural_language.strip(),
            "",
            "Return `{ \"findings\": [] }` if no ambiguity is found.",
        ]
    )
