"""Prompt template for postcondition_violated failures."""
from agent.prompts.report_formatter import (
    format_counterexample,
    format_violated_constraints,
    format_span,
    format_suggestion,
)
from agent.prompts.examples.postcondition_examples import EXAMPLES
from agent.prompts.examples.formatter import format_examples


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing postcondition violations."""
    sections: list[str] = []

    sections.append(
        "You are an expert in the Mumei language. The following code has a postcondition violation.\n"
        "The `ensures` condition is not satisfied by the function body's return value."
    )

    sections.append(f"# Source code:\n{source_code}")
    sections.append(f"# Error log:\n{error_log}")

    ce = format_counterexample(report_data)
    if ce:
        sections.append(f"# Counter-example:\n{ce}")

    vc = format_violated_constraints(report_data)
    if vc:
        sections.append(f"# Violated constraints:\n{vc}")

    span = format_span(report_data)
    if span:
        sections.append(f"# {span}")

    sug = format_suggestion(report_data)
    if sug:
        sections.append(f"# {sug}")

    sections.append(
        "# Fix guidance:\n"
        "Either fix the body so that its return value satisfies the `ensures` clause,\n"
        "or adjust the `ensures` clause to match the actual behaviour of the body."
    )

    ex = format_examples(EXAMPLES, max_examples=1)
    if ex:
        sections.append(ex)

    sections.append("Output only the fixed code in ```mumei ... ``` format.")

    return "\n\n".join(sections)
