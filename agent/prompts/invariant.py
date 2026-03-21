"""Prompt template for invariant_violated failures."""
from agent.prompts.report_formatter import (
    format_unsat_core,
    format_span,
    format_suggestion,
)
from agent.prompts.examples.precondition_examples import EXAMPLES
from agent.prompts.examples.formatter import format_examples


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing invariant violations."""
    sections: list[str] = []

    sections.append(
        "You are an expert in the Mumei language. The following code has an invariant violation.\n"
        "The constraints are contradictory — the verifier found an unsatisfiable core."
    )

    sections.append(f"# Source code:\n{source_code}")
    sections.append(f"# Error log:\n{error_log}")

    unsat = format_unsat_core(report_data)
    if unsat:
        sections.append(f"# Unsat core:\n{unsat}")

    span = format_span(report_data)
    if span:
        sections.append(f"# {span}")

    sug = format_suggestion(report_data)
    if sug:
        sections.append(f"# {sug}")

    sections.append(
        "# Fix guidance:\n"
        "Relax one or more of the contradictory constraints so that they can be\n"
        "simultaneously satisfied. Identify which constraint is too strict and weaken it."
    )

    ex = format_examples(EXAMPLES, max_examples=1)
    if ex:
        sections.append(ex)

    sections.append("Output only the fixed code in ```mumei ... ``` format.")

    return "\n\n".join(sections)
