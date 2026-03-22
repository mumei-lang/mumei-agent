"""Prompt template for precondition/postcondition and other non-effect violations."""
from agent.prompts.report_formatter import (
    format_counterexample,
    format_violated_constraints,
    format_structured_unsat_core,
    format_suggestion,
    format_span,
)
from agent.prompts.examples.precondition_examples import EXAMPLES
from agent.prompts.examples.formatter import format_examples


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing precondition/postcondition violations."""
    sections: list[str] = []

    sections.append(
        "You are an expert in the Mumei language. The following code failed formal verification.\n"
        "Please fix the 'requires' (precondition) to resolve the mathematical contradiction."
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

    suc = format_structured_unsat_core(report_data)
    if suc:
        sections.append(f"# Structured Unsat Core (conflicting constraints identified by Z3):\n{suc}")

    ex = format_examples(EXAMPLES)
    if ex:
        sections.append(ex)

    sections.append("Output only the fixed code in ```mumei ... ``` format.")

    return "\n\n".join(sections)
