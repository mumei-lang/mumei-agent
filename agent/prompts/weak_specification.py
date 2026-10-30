"""Prompt template for weak negative-control specifications."""
from __future__ import annotations


def _mutant_descriptions(atom: dict) -> list[str]:
    values = atom.get("surviving_descriptions")
    if not isinstance(values, list) or not values:
        mutants = atom.get("mutants")
        if isinstance(mutants, list):
            values = [
                mutant
                for mutant in mutants
                if isinstance(mutant, dict)
                and mutant.get("outcome") == "survived"
            ]
        else:
            values = atom.get("surviving")
    if not isinstance(values, list):
        values = []

    descriptions: list[str] = []
    for value in values:
        if isinstance(value, str):
            descriptions.append(value)
        elif isinstance(value, dict):
            description = (
                value.get("detail")
                or value.get("description")
                or value.get("id")
            )
            if isinstance(description, str):
                descriptions.append(description)
    return descriptions


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build repair guidance for verified code with weak negative controls."""
    sections = [
        "You are an expert in the Mumei language. Verification passed, but "
        "negative controls show that the contracts are too weak to tell the "
        "body apart from the generated mutants.",
        f"# Source code:\n{source_code}",
        f"# Error log:\n{error_log}",
    ]

    controls = report_data.get("controls")
    if isinstance(controls, dict):
        weak_atoms = [
            (name, atom)
            for name, atom in sorted(controls.items())
            if isinstance(atom, dict)
            and atom.get("status") in {"weak", "inconclusive"}
        ]
    else:
        weak_atoms = []

    if weak_atoms:
        lines = ["# Weak or inconclusive negative-control atoms:"]
        for name, atom in weak_atoms:
            survived = atom.get("survived", 0)
            descriptions = _mutant_descriptions(atom)
            detail = (
                ", ".join(descriptions)
                if descriptions
                else "no surviving mutant descriptions reported"
            )
            lines.append(
                f"- `{name}` ({atom['status']}): {survived} survived; "
                f"surviving mutants: {detail}"
            )
        sections.append("\n".join(lines))

    sections.append(
        "# Fix guidance:\n"
        "Strengthen `ensures` or add precise postconditions so the surviving "
        "mutants are rejected while keeping the body's behavior unchanged. "
        "Do not weaken `requires` or `ensures`, and do not add `trusted`. "
        "Keep the resulting code verifiable."
    )
    sections.append("Output only the fixed code in ```mumei ... ``` format.")
    return "\n\n".join(sections)
