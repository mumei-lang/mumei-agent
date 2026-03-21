"""Prompt template for temporal effect violations."""
from agent.prompts.report_formatter import format_span, format_suggestion


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing temporal effect violations."""
    sections: list[str] = []

    sections.append(
        "You are an expert in the Mumei language. The following code has a temporal effect violation.\n"
        "The state transitions for an effect are performed in the wrong order."
    )

    sections.append(f"# Source code:\n{source_code}")
    sections.append(f"# Error log:\n{error_log}")

    span = format_span(report_data)
    if span:
        sections.append(f"# {span}")

    sug = format_suggestion(report_data)
    if sug:
        sections.append(f"# {sug}")

    sections.append(
        "# Fix guidance:\n"
        "Reorder the effectful operations to follow the correct state machine transitions.\n"
        "For example, a File effect requires: open → write/read → close.\n"
        "Ensure that each `perform` call transitions from a valid pre-state to its post-state."
    )

    sections.append("Output only the fixed code in ```mumei ... ``` format.")

    return "\n\n".join(sections)
