"""Prompts for natural-language spec to code conformance verification."""
from __future__ import annotations

import json


CONFORMANCE_VERIFICATION_SYSTEM_PROMPT = (
    "You are a Mumei conformance verifier. Compare a natural-language "
    "specification with implementation code and return only structured JSON."
)


def build_conformance_verification_prompt(spec: str, code: str, language: str) -> str:
    """Build a prompt for spec-to-code conformance verification."""
    schema = {
        "unimplemented_conditions": [
            {
                "condition": "amount >= 0",
                "source": "natural_language_spec",
                "evidence": "code never rejects negative amount",
                "implementation_symbol": "withdraw",
                "status": "missing",
            }
        ],
        "hidden_specifications": [
            {
                "condition": "b != 0",
                "source": "implementation",
                "evidence": "division requires a non-zero divisor",
                "implementation_symbol": "divide",
                "status": "undocumented",
            }
        ],
        "traceability_matrix": [
            {
                "spec_item_id": "spec-1",
                "spec_condition": "result == balance - amount",
                "implementation_symbol": "withdraw",
                "code_line": 2,
                "status": "implemented",
                "evidence": "return balance - amount",
            }
        ],
        "verification_violations": ["code does not imply the spec postcondition"],
        "cross_validation_gaps": ["spec requires amount >= 0; code requires true"],
        "next_steps": [
            {
                "priority": "high",
                "action": "Update implementation or refine spec.",
                "command": "mumei-agent validate-spec-to-code --spec spec.txt --code impl.py",
            }
        ],
    }
    return "\n".join(
        [
            "# Task",
            "Compare the natural-language specification with the implementation.",
            "Return JSON only. Use `next_steps` as the only human review handoff.",
            "",
            "# Output schema",
            "```json",
            json.dumps(schema, indent=2, ensure_ascii=False),
            "```",
            "",
            "# Natural-language specification",
            spec.strip(),
            "",
            f"# Code ({language})",
            f"```{language}",
            code.strip(),
            "```",
        ]
    )
