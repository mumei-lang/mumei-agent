"""Prompt template for effect_mismatch violations."""
from agent.prompts.report_formatter import format_span, format_suggestion
from agent.prompts.examples.effect_examples import EXAMPLES
from agent.prompts.examples.formatter import format_examples


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing effect mismatch violations."""
    ev = report_data.get("effect_violation", {})
    resolution_paths = ev.get("resolution_paths", [])
    opt_a = resolution_paths[0].get("description", "") if resolution_paths else ""
    opt_b = resolution_paths[1].get("description", "") if len(resolution_paths) > 1 else "Remove the offending call."

    sections: list[str] = []

    sections.append(
        f"You are an expert in the Mumei language. The following code has an effect violation.\n"
        f"The atom '{report_data.get('atom')}' declares effects {ev.get('declared_effects')}\n"
        f"but uses operation '{ev.get('source_operation')}' which requires [{ev.get('required_effect')}]."
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
        f"# Resolution paths (choose ONE):\n\n"
        f"## Option A: Propagation (expand the effect boundary)\n"
        f"{opt_a}\n"
        f"Add the missing effect to the atom's `effects:` declaration.\n\n"
        f"## Option B: Isolation (remove the effectful operation)\n"
        f"{opt_b}\n"
        f"Replace the effectful operation with a pure computation."
    )

    ex = format_examples(EXAMPLES, max_examples=1)
    if ex:
        sections.append(ex)

    sections.append(
        "Output only the fixed code in ```mumei ... ``` format.\n"
        "Choose the option that best preserves the code's intent."
    )

    return "\n\n".join(sections)
