"""Prompt template for linearity_violated failures."""
from agent.prompts.report_formatter import format_span, format_suggestion
from agent.prompts.examples.linearity_examples import EXAMPLES
from agent.prompts.examples.formatter import format_examples


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing linearity violations."""
    sections: list[str] = []

    sf = report_data.get("semantic_feedback")
    if not sf or not isinstance(sf, dict):
        sf = {}
    violations = sf.get("violations") or []
    if not isinstance(violations, list):
        violations = []

    sections.append(
        "You are an expert in the Mumei language. The following code has a linearity violation.\n"
        "A linear resource is used more than once, which violates ownership rules."
    )

    sections.append(f"# Source code:\n{source_code}")
    sections.append(f"# Error log:\n{error_log}")

    if violations:
        lines = ["# Linearity violations:"]
        for v in violations:
            if isinstance(v, str):
                lines.append(f"  - {v}")
            elif isinstance(v, dict):
                lines.append(f"  - {v.get('description', v)}")
        sections.append("\n".join(lines))

    span = format_span(report_data)
    if span:
        sections.append(f"# {span}")

    sug = format_suggestion(report_data)
    if sug:
        sections.append(f"# {sug}")

    sections.append(
        "# Fix guidance:\n"
        "Either clone the resource before the second use, or restructure the code\n"
        "so each linear value is consumed exactly once."
    )

    ex = format_examples(EXAMPLES, max_examples=1)
    if ex:
        sections.append(ex)

    sections.append("Output only the fixed code in ```mumei ... ``` format.")

    return "\n\n".join(sections)
