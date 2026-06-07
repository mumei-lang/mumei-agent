"""Prompts for cross-validating natural-language specifications."""

import json

from agent.prompts.spec_guide import SPEC_GUIDE_DECIDABLE_FRAGMENT


CROSS_VALIDATION_NL_SYSTEM_PROMPT = (
    "You are a cross-validation engineer for the Mumei proof-driven language. "
    "Convert natural-language requirements into small Mumei contract atoms and "
    "flag contradictions, ambiguity, and over-constrained requirements before "
    "implementation begins.\n\n"
    + SPEC_GUIDE_DECIDABLE_FRAGMENT
    + "Output ONLY valid JSON."
)


def build_nl_cross_validation_prompt(spec_text: str) -> str:
    """Build a prompt for NL-spec cross validation."""
    schema = {
        "atoms": [
            {
                "name": "safe_divide",
                "params": [
                    {"name": "a", "type": "i64"},
                    {"name": "b", "type": "i64"},
                ],
                "return_type": "i64",
                "requires": "b != 0",
                "ensures": "result == a / b",
                "effects": [],
            }
        ],
        "issues": [
            {
                "kind": "contradiction",
                "message": "The spec both requires X and forbids X.",
                "evidence": "always X and never X",
                "severity": "error",
            }
        ],
    }
    return "\n".join(
        [
            "# Task",
            "Cross-validate this natural-language specification.",
            "",
            "# Checks",
            "- Translate implementable requirements into Mumei-style atoms.",
            "- Use explicit `requires` preconditions and `ensures` postconditions.",
            "- Flag direct contradictions such as `A and not A`.",
            "- Flag vague terms such as appropriate, sufficient, 適切に, 十分に.",
            "- Flag over-constrained contracts that cannot be satisfied.",
            "",
            "# Output schema",
            "Return a JSON object matching this shape:",
            "```json",
            json.dumps(schema, indent=2, ensure_ascii=False),
            "```",
            "",
            "# Specification",
            spec_text.strip(),
        ]
    )
