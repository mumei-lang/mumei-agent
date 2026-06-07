"""Prompt template for extracting Mumei specifications from natural language."""

import json

from agent.prompts.spec_guide import SPEC_GUIDE_DECIDABLE_FRAGMENT


SPEC_EXTRACTION_SYSTEM_PROMPT = (
    "You are a specification engineer for the Mumei proof-driven language. "
    "Your task is to extract formal specifications from natural language requirements.\n\n"
    + SPEC_GUIDE_DECIDABLE_FRAGMENT
    + "Mumei atoms have the following structure:\n"
    "- `requires`: preconditions that must hold before execution\n"
    "- `ensures`: postconditions guaranteed after execution\n"
    "- `effects`: side effects the atom performs (e.g., IO, State, Temporal)\n"
    "- `inputs`/`params`: typed parameters\n"
    "- `return_type`: the return type\n\n"
    "Your output must be a valid forge task spec JSON. "
    "Extract ALL implicit safety properties the user would expect "
    "(e.g., no overflow, no division by zero, non-negative balances). "
    "If the user's description is ambiguous, choose the SAFER interpretation. "
    "When the requirement describes multiple related operations, produce one "
    "atom per operation in the atoms array instead of collapsing them into a "
    "single atom. For example, bank-transfer requirements with both debit and "
    "credit behavior should emit debit_transfer and credit_transfer atoms.\n\n"
    "Output ONLY valid JSON, no explanation."
)

DOMAIN_TEMPLATES: dict[str, str] = {
    "financial": (
        "Financial domain conventions:\n"
        "- Balance must be non-negative: `requires: balance >= 0`\n"
        "- Transfer amount must be positive: `requires: amount > 0`\n"
        "- Sender must have sufficient funds: `requires: sender_balance >= amount`\n"
        "- No money creation: `ensures: result_sender + result_receiver == sender_balance + receiver_balance`\n"
        "- Use effects: [State(balance)] for balance mutations\n"
    ),
    "compliance": (
        "Compliance / KYC / AML / RegTech domain conventions:\n"
        "- Model customer categories as CustomerType-like enum values: Individual, Corporate, Government, PEP\n"
        "- RiskLevel outputs should be bounded, e.g. `ensures: result >= Low && result <= Critical`\n"
        "- PEP or sanctions hits imply high risk: `ensures: is_pep == 1 ==> result >= High`\n"
        "- AML screening should preserve auditability and not silently drop flagged customers\n"
        "- Use forall-style patterns for portfolio rules: `forall customer in customers: screened(customer)`\n"
    ),
    "data_structure": (
        "Data-structure domain conventions:\n"
        "- Boundary checks before indexing: `requires: index >= 0 && index < length`\n"
        "- Capacity constraints for containers: `requires: length < capacity` before push/enqueue\n"
        "- Pop/dequeue requires non-empty state: `requires: length > 0`\n"
        "- Size updates are exact: `ensures: result_length == length + 1` or `length - 1`\n"
        "- Preserve ordering/FIFO/LIFO invariants for queues, lists, stacks, and deques\n"
    ),
    "math": (
        "Math domain conventions:\n"
        "- Prevent overflow: bound operands with min/max constraints before arithmetic\n"
        "- Define domain restrictions explicitly, e.g. denominator != 0, input >= 0 for sqrt\n"
        "- Absolute-value results must be non-negative and preserve magnitude\n"
        "- Monotonic functions should state monotonicity where relevant\n"
        "- Use effects: [] for pure mathematical functions\n"
    ),
    "crypto": (
        "Cryptography domain conventions:\n"
        "- Modular arithmetic: use `mod` for remainder operations\n"
        "- Exponentiation: use `pow(base, exp)` for power operations\n"
        "- RSA signatures: verify with `mod(pow(signature, public_key), n) == mod(message, n)`\n"
        "- Include modulus preconditions such as `n > 0` before modular arithmetic\n"
        "- Finite field operations: bounds are `0 <= x < p` where p is prime\n"
        "- Use effects: [] for pure cryptographic verification helpers\n"
    ),
    "security": (
        "Security domain conventions:\n"
        "- Input validation: all string inputs must be bounded\n"
        "- Authentication state: `requires: is_authenticated == 1`\n"
        "- Authorization: `requires: has_permission(user, resource) == 1`\n"
        "- No information leakage in error paths\n"
    ),
    "iot": (
        "IoT domain conventions:\n"
        "- Sensor values have physical bounds: `requires: value >= MIN && value <= MAX`\n"
        "- Timestamps are monotonically increasing\n"
        "- Device state transitions must be valid\n"
    ),
    "web": (
        "Web API domain conventions:\n"
        "- HTTP status codes: `ensures: result >= 100 && result <= 599`\n"
        "- Request validation before processing\n"
        "- Idempotency for PUT/DELETE operations\n"
    ),
}

DOMAIN_ALIASES: dict[str, str] = {
    "regtech": "compliance",
    "kyc": "compliance",
    "aml": "compliance",
    "container": "data_structure",
    "queue": "data_structure",
    "list": "data_structure",
    "mathematics": "math",
    "cryptography": "crypto",
    "rsa": "crypto",
    "digital_signature": "crypto",
    "crypto_signature": "crypto",
}


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
        "- `target_file`: safe relative path under `std/` ending in `.mm`, for example `std/math/safe_add.mm`.",
        "- `mode`: one of `append`, `create`, or `replace`.",
        "- `atoms`: non-empty list of atom specs.",
        "- Use multiple atom entries when the requirement describes multiple related operations.",
        "- Example: `銀行送金機能。送金と受取の両方を実装` should produce separate `debit_transfer` and `credit_transfer` atoms.",
        "- Each atom must include `name`, `description`, `inputs`, `return_type`, "
        "`requires`, `ensures`, and `effects`.",
        "- Atom names must match `[A-Za-z_][A-Za-z0-9_]*` and be unique.",
        '- `inputs` must be a list of `{"name", "type"}` objects; use `inputs` rather than `params` in extracted forge tasks.',
        "- `effects` must be a list, using `[]` for pure atoms.",
        "- `requires` and `ensures` must be non-empty formal Mumei contract strings.",
        "- If existing std/ catalog context is provided, populate `reference_patterns` with relevant existing atom names.",
        "",
        "# Example",
        "Input: 安全な加算関数。オーバーフローしないこと",
        "Output:",
        "```json",
        json.dumps(_EXAMPLE_OUTPUT, indent=2, ensure_ascii=False),
        "```",
    ]
    if domain_hint:
        matched_domain = None
        lowered_domain = domain_hint.lower()
        for alias, canonical in DOMAIN_ALIASES.items():
            if alias in lowered_domain:
                matched_domain = canonical
                break
        if matched_domain is None:
            for key in DOMAIN_TEMPLATES:
                if key in lowered_domain:
                    matched_domain = key
                    break
        if matched_domain:
            parts.extend(
                [
                    "",
                    "# Domain-specific contract patterns",
                    DOMAIN_TEMPLATES[matched_domain],
                ]
            )
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
