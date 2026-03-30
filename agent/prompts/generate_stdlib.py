"""Prompt template for standard library-style atom generation.

Uses few-shot examples based on patterns from mumei's std/file.mm and
std/http.mm to guide the LLM in generating verified atoms with effects.
"""
import json

from agent.prompts.generate_atom import COMMON_MISTAKES
from agent.prompts.report_formatter import (
    format_actionable_fix_hint,
    format_for_initial_generate,
    format_structured_unsat_core,
    format_data_flow,
)

_STDLIB_EXAMPLES = """\
## Example 1 — std/file.mm: read_file
```mumei
atom read_file(path: i64)
    effects: [FileRead]
    requires: true;
    ensures: result >= 0;
    body: {
        perform FileRead.read(path);
        file_read(path)
    }
```

## Example 2 — std/http.mm: get
```mumei
atom get(url: Str)
    effects: [HttpGet(url)]
    requires: true;
    ensures: result >= 0;
    body: {
        perform HttpGet.request(url);
        http_get(url)
    }
```

## Example 3 — std/file.mm: safe_read_file (parameterized effect)
```mumei
atom safe_read_file(path: Str)
    effects: [SafeFileRead(path)]
    requires: starts_with(path, "/tmp/") && not_contains(path, "..");
    ensures: result >= 0;
    body: {
        perform SafeFileRead.read(path);
        1
    }
```

## Example 4 — std/contracts.mm: clamp (pure computation, no effects)
```mumei
atom clamp(val: i64, min_val: i64, max_val: i64)
    requires: min_val <= max_val;
    ensures: result >= min_val && result <= max_val;
    body: { if val < min_val { min_val } else { if val > max_val { max_val } else { val } } }
```

## Example 5 — std/math/fixed_point.mm: fp_add (overflow-safe arithmetic)
```mumei
atom fp_add(a: i64, b: i64)
    requires: a >= -999999999999 && a <= 999999999999
           && b >= -999999999999 && b <= 999999999999
           && a + b >= -999999999999 && a + b <= 999999999999;
    ensures: result == a + b;
    body: a + b;
```

## Example 6 — std/container/safe_queue.mm: enqueue (bounded data structure)
```mumei
atom enqueue(q_len: i64, q_cap: i64)
    requires: q_len >= 0 && q_cap > 0 && q_len < q_cap;
    ensures: result == q_len + 1 && result <= q_cap;
    body: q_len + 1;
```

## Example 7 — std/http_secure.mm: secure_get (HTTPS-only with parameterized effect)
```mumei
effect SecureHttpGet(url: Str) where starts_with(url, "https://");

atom secure_get(url: Str)
    effects: [SecureHttpGet(url)]
    requires: starts_with(url, "https://");
    ensures: result >= 0;
    body: {
        perform SecureHttpGet.request(url);
        http_get(url)
    }
```
"""


def build_prompt(source_code: str, error_log: str, report_data: dict, *, inferred_context: dict | None = None) -> str:
    """Build a prompt for generating stdlib-style atoms.

    Args:
        source_code: Specification JSON string describing the desired atom.
        error_log: Any error output from a previous generation attempt.
        report_data: Structured report data (may contain verification errors).

    Returns:
        A prompt string for the LLM.
    """
    sections: list[str] = []

    sections.append(
        "You are an expert in the Mumei language. Generate a complete .mm file "
        "implementing the atom described below. Follow the standard library patterns "
        "shown in the examples."
    )

    sections.append(COMMON_MISTAKES)

    # Pre-generation checklist if spec is parseable as JSON
    try:
        spec_dict = json.loads(source_code) if isinstance(source_code, str) else source_code
        if isinstance(spec_dict, dict):
            checklist = format_for_initial_generate(spec_dict)
            if checklist:
                sections.append(checklist)
    except (json.JSONDecodeError, TypeError):
        pass

    sections.append(f"# Specification:\n{source_code}")

    sections.append(f"# Standard library patterns:\n{_STDLIB_EXAMPLES}")

    if error_log:
        sections.append(f"# Previous attempt error:\n{error_log}")

    if report_data:
        # Actionable fix hint (human-readable)
        hint = format_actionable_fix_hint(report_data)
        if hint:
            sections.append(f"# Actionable fix instructions:\n{hint}")

        # Structured unsat core
        suc = format_structured_unsat_core(report_data)
        if suc:
            sections.append(f"# Structured Unsat Core (conflicting constraints from Z3):\n{suc}")

        # Data flow trace
        df = format_data_flow(report_data)
        if df:
            sections.append(f"# {df}")

        # Full report as fallback context
        sections.append(
            f"# Verification report:\n{json.dumps(report_data, indent=2, ensure_ascii=False)}"
        )

    if inferred_context is not None:
        sections.append(
            f"# Inferred effects (from mumei infer-effects):\n"
            f"{json.dumps(inferred_context.get('effects', {}), indent=2)}"
        )
        sections.append(
            f"# Inferred contracts (from mumei infer-contracts):\n"
            f"{json.dumps(inferred_context.get('contracts', {}), indent=2)}"
        )

    sections.append(
        "Generate a complete .mm file with the atom, including any required "
        "extern declarations, effect declarations, requires, ensures, and body. "
        "Output only the code in ```mumei ... ``` format."
    )

    return "\n\n".join(sections)
