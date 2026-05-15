"""Prompt templates for specification intent tracking."""
from __future__ import annotations

import json
from typing import Any

INTENT_TRACKING_SYSTEM_PROMPT = (
    "You are a specification intent auditor for the Mumei proof-driven language. "
    "Compare original and refined specifications, identify whether requires, ensures, "
    "and effects changes preserve user intent, and return precise JSON only."
)


def build_intent_analysis_prompt(
    original_spec: dict[str, Any],
    refined_spec: dict[str, Any],
    natural_language_intent: str | None = None,
) -> str:
    """Build a prompt for LLM-assisted intent drift analysis."""
    original_json = json.dumps(original_spec, indent=2, ensure_ascii=False)
    refined_json = json.dumps(refined_spec, indent=2, ensure_ascii=False)
    intent = natural_language_intent or "(not provided)"
    schema = {
        "intent_preserved": True,
        "drift_score": 1.0,
        "changes": [
            {
                "field": "requires",
                "original": "x >= 0",
                "refined": "x >= 0 && x < 100",
                "change_type": "strengthened",
                "intent_impact": "strengthened",
            }
        ],
        "warnings": [],
        "errors": [],
    }
    return f"""# Natural language intent
{intent}

# Original specification
```json
{original_json}
```

# Refined specification
```json
{refined_json}
```

# Task
Analyze whether the refined specification preserves the original intent.
Classify each changed requires, ensures, and effects field as unchanged,
strengthened, weakened, or replaced, then classify intent impact as preserved,
strengthened, weakened, or violated.

# Output schema
Return ONLY JSON matching this shape:
```json
{json.dumps(schema, indent=2, ensure_ascii=False)}
```"""
