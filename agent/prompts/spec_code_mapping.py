"""Prompts for mapping Mumei specifications to generated code."""
from __future__ import annotations

import json
from typing import Any

SPEC_CODE_MAPPING_SYSTEM_PROMPT = (
    "You are a verification traceability engineer for the Mumei proof-driven language. "
    "Map each specification clause to the generated code line and column that implements "
    "or enforces it. Return precise JSON only."
)


def build_mapping_prompt(
    spec: dict[str, Any],
    generated_code: str,
    verification_report: dict[str, Any] | None = None,
) -> str:
    """Build a prompt for specification-to-code mapping."""
    spec_json = json.dumps(spec, indent=2, ensure_ascii=False)
    report_json = json.dumps(verification_report or {}, indent=2, ensure_ascii=False)
    return f"""# Specification
```json
{spec_json}
```

# Generated Mumei code
```mumei
{generated_code}
```

# Verification report
```json
{report_json}
```

# Task
For every requires, ensures, and effect item, identify the generated code location that
implements, checks, or justifies it.

Return ONLY JSON with this shape:
{{
  "mappings": [
    {{
      "spec_description": "human-readable summary",
      "spec_type": "requires|ensures|effect",
      "spec_clause": "original clause text",
      "code_location": {{"line": 1, "col": 1}},
      "verification_status": "passed|failed|unknown"
    }}
  ],
  "warnings": []
}}"""
