"""Prompt template for standard library-style atom generation.

Uses few-shot examples based on patterns from mumei's std/file.mm and
std/http.mm to guide the LLM in generating verified atoms with effects.
"""

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
"""


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
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

    sections.append(f"# Specification:\n{source_code}")

    sections.append(f"# Standard library patterns:\n{_STDLIB_EXAMPLES}")

    if error_log:
        sections.append(f"# Previous attempt error:\n{error_log}")

    if report_data:
        import json
        sections.append(
            f"# Verification report:\n{json.dumps(report_data, indent=2, ensure_ascii=False)}"
        )

    sections.append(
        "Generate a complete .mm file with the atom, including any required "
        "extern declarations, effect declarations, requires, ensures, and body. "
        "Output only the code in ```mumei ... ``` format."
    )

    return "\n\n".join(sections)
