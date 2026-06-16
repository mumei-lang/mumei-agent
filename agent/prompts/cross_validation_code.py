"""Prompts for cross-validating foreign-language code."""

import json

from agent.prompts.spec_guide import SPEC_GUIDE_DECIDABLE_FRAGMENT


CROSS_VALIDATION_CODE_SYSTEM_PROMPT = (
    "You are a cross-validation engineer for the Mumei proof-driven language. "
    "Infer formal contracts from foreign-language code and express them as "
    "Mumei atoms suitable for `mumei verify`.\n\n"
    + SPEC_GUIDE_DECIDABLE_FRAGMENT
    + "Output ONLY valid JSON."
)


def build_code_cross_validation_prompt(code: str, language: str) -> str:
    """Build a prompt for foreign-code cross validation."""
    schema = {
        "atoms": [
            {
                "name": "add",
                "params": [
                    {"name": "a", "type": "i64"},
                    {"name": "b", "type": "i64"},
                ],
                "return_type": "i64",
                "requires": "true",
                "ensures": "result == a + b",
                "effects": [],
            }
        ],
        "issues": [
            {
                "kind": "overconstraint",
                "message": "The inferred contract is unsatisfiable.",
                "evidence": "result > x && result < x",
                "source_line": 12,
                "severity": "error",
            }
        ],
    }
    return "\n".join(
        [
            "# Task",
            "Infer Mumei contracts from this foreign-language code.",
            "",
            "# Requirements",
            "- Infer one atom per function or method with externally visible behavior.",
            "- Include safety preconditions, such as non-zero divisors and bounds checks.",
            "- Use decidable arithmetic-friendly `requires` and `ensures` clauses.",
            "- For every issue, identify the 1-based source code line that contradicts or implements the constraint and return it as `source_line`.",
            "- Count `source_line` from the fenced source code block below, ignoring markdown fences.",
            "- Return JSON only.",
            "",
            "# Output schema",
            "```json",
            json.dumps(schema, indent=2, ensure_ascii=False),
            "```",
            "",
            f"# Language: {language}",
            f"```{language}",
            code.strip(),
            "```",
        ]
    )
