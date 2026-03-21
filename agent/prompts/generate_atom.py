"""Prompt template for generic atom generation from a spec JSON."""
import json


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for generating a Mumei atom from a specification.

    Args:
        source_code: Specification JSON string describing the desired atom.
        error_log: Any error output from a previous generation attempt.
        report_data: Structured report data (may contain verification errors).

    Returns:
        A prompt string for the LLM.
    """
    sections: list[str] = []

    sections.append(
        "You are an expert in the Mumei programming language. "
        "Generate a complete .mm file implementing the atom described in the "
        "specification below.\n\n"
        "Mumei atoms have the following structure:\n"
        "```\n"
        "atom <name>(<params>) -> <return_type>\n"
        "    effects: [<effect_list>]\n"
        "    requires: <precondition>;\n"
        "    ensures: <postcondition>;\n"
        "    body: { <implementation> }\n"
        "```\n\n"
        "Rules:\n"
        "- Every atom MUST have requires, ensures, and body clauses\n"
        "- Effects must be declared if the atom performs side effects\n"
        "- Use `perform <Effect>.<operation>(args)` to invoke effects in the body\n"
        "- The body expression's result is the atom's return value"
    )

    sections.append(f"# Specification:\n{source_code}")

    if error_log:
        sections.append(
            f"# Previous attempt produced errors. Fix these:\n{error_log}"
        )

    if report_data:
        sections.append(
            f"# Verification report from previous attempt:\n"
            f"{json.dumps(report_data, indent=2, ensure_ascii=False)}"
        )

    sections.append("Output only the complete .mm file in ```mumei ... ``` format.")

    return "\n\n".join(sections)
