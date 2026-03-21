"""Prompt template for division_by_zero failures."""
from agent.prompts.report_formatter import (
    format_counterexample,
    format_span,
    format_suggestion,
)


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing division-by-zero violations."""
    sections: list[str] = []

    sf = report_data.get("semantic_feedback", {})
    ce = sf.get("counter_example", {})
    dividend = ce.get("dividend", "?")
    divisor = ce.get("divisor", "?")

    sections.append(
        "You are an expert in the Mumei language. The following code has a division-by-zero violation.\n"
        f"The verifier found that the divisor can be zero (dividend={dividend}, divisor={divisor}).\n"
        "You must add a `requires` clause ensuring the divisor is non-zero."
    )

    sections.append(f"# Source code:\n{source_code}")
    sections.append(f"# Error log:\n{error_log}")

    ce_str = format_counterexample(report_data)
    if ce_str:
        sections.append(f"# Counter-example:\n{ce_str}")

    span = format_span(report_data)
    if span:
        sections.append(f"# {span}")

    sug = format_suggestion(report_data)
    if sug:
        sections.append(f"# {sug}")

    sections.append(
        "# Fix guidance:\n"
        "Add `requires: <divisor_param> != 0` to the atom's precondition.\n"
        "If there is already a requires clause, conjoin the new constraint with `&&`."
    )

    sections.append("Output only the fixed code in ```mumei ... ``` format.")

    return "\n\n".join(sections)
