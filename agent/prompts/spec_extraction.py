"""Prompt template for extracting Mumei specifications from natural language."""

import json

SPEC_EXTRACTION_SYSTEM_PROMPT = (
    "You are a specification engineer for the Mumei proof-driven language. "
    "Your task is to extract formal specifications from natural language requirements.\n\n"
    "Mumei atoms have the following structure:\n"
    "- `requires`: preconditions that must hold before execution\n"
    "- `ensures`: postconditions guaranteed after execution\n"
    "- `effects`: side effects the atom performs (e.g., IO, State, Temporal)\n"
    "- `inputs`/`params`: typed parameters\n"
    "- `return_type`: the return type\n\n"
    "Your output must be a valid forge task spec JSON. "
    "Extract ALL implicit safety properties the user would expect "
    "(e.g., no overflow, no division by zero, non-negative balances). "
    "If the user's description is ambiguous, choose the SAFER interpretation.\n\n"
    "Output ONLY valid JSON, no explanation."
)


_SCHEMA = """{
  "task_id": "vstd-contracts-safe-add",
  "target_file": "std/contracts.mm",
  "mode": "append",
  "priority": 1,
  "atoms": [
    {
      "name": "safe_add",
      "description": "Overflow-safe addition",
      "inputs": [
        {"name": "a", "type": "i64"},
        {"name": "b", "type": "i64"}
      ],
      "return_type": "i64",
      "requires": "a >= 0 && b >= 0",
      "ensures": "result == a + b && result >= 0",
      "effects": [],
      "reference_patterns": ["safe_subtract", "bounded_increment"]
    }
  ],
  "max_retries": 10,
  "auto_commit": false
}"""


_EXAMPLE_OUTPUT = {
    "task_id": "nl-safe-add",
    "target_file": "std/math/safe_add.mm",
    "mode": "create",
    "atoms": [
        {
            "name": "safe_add",
            "description": "Overflow-safe addition",
            "inputs": [
                {"name": "a", "type": "i64"},
                {"name": "b", "type": "i64"},
            ],
            "return_type": "i64",
            "requires": "a >= 0 && b >= 0 && a <= i64::MAX - b",
            "ensures": "result == a + b && result >= a && result >= b",
            "effects": [],
        }
    ],
}


def build_extraction_prompt(
    natural_language: str,
    *,
    domain_hint: str = "",
    existing_catalog: str = "",
) -> str:
    """Build a prompt for extracting a forge task spec from natural language.

    Args:
        natural_language: The user's natural language requirement text.
        domain_hint: Optional domain hint (e.g., "financial", "security").
        existing_catalog: Optional std/ catalog summary for reuse hints.

    Returns:
        A prompt string for the LLM.
    """
    parts = [
        "# Natural language requirement",
        natural_language.strip(),
        "",
        "# Expected forge task spec JSON schema",
        "Match the forge_tasks/README.md Spec JSON format:",
        "```json",
        _SCHEMA,
        "```",
        "",
        "# Required schema rules",
        "- `task_id`: unique string identifier.",
        "- `target_file`: path under `std/`, for example `std/math/safe_add.mm`.",
        "- `mode`: one of `append`, `create`, or `replace`.",
        "- `atoms`: non-empty list of atom specs.",
        "- Each atom must include `name`, `description`, `inputs`, `return_type`, "
        "`requires`, `ensures`, and `effects`.",
        '- `inputs` must be a list of `{"name", "type"}` objects.',
        "- `requires` and `ensures` must be non-empty formal Mumei contract strings.",
        "",
        "# Example",
        "Input: 安全な加算関数。オーバーフローしないこと",
        "Output:",
        "```json",
        json.dumps(_EXAMPLE_OUTPUT, indent=2, ensure_ascii=False),
        "```",
    ]
    if domain_hint:
        parts.extend(
            [
                "",
                "# Domain hint",
                (
                    f"Domain: {domain_hint}. Use this to choose safer implicit "
                    "invariants and conventional atom names/paths."
                ),
            ]
        )
    if existing_catalog:
        parts.extend(
            [
                "",
                "# Existing std/ catalog",
                "Prefer reusing or referencing existing std/ atoms when relevant:",
                existing_catalog.strip(),
            ]
        )
    parts.extend(
        [
            "",
            "# Requirement to extract",
            natural_language.strip(),
            "",
            "Return ONLY valid JSON for the requirement above. Do not copy the example.",
        ]
    )
    return "\n".join(parts)
