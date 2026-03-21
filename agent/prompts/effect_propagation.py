"""Prompt template for effect_propagation violations."""
from agent.prompts.report_formatter import format_span, format_suggestion


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing effect propagation violations."""
    ev = report_data.get("effect_violation", {})
    caller_effects = ev.get("caller_effects", [])
    missing_effects = ev.get("missing_effects", [])
    combined = sorted(set(caller_effects + missing_effects))

    sections: list[str] = []

    sections.append(
        f"You are an expert in the Mumei language. The following code has an effect propagation violation.\n"
        f"Atom '{ev.get('caller')}' calls '{ev.get('callee')}' which requires effects {ev.get('callee_effects')},\n"
        f"but '{ev.get('caller')}' only declares effects {ev.get('caller_effects')}.\n"
        f"Missing effects: {ev.get('missing_effects')}"
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
        f"# Resolution:\n"
        f"Add the missing effects {missing_effects} to atom '{ev.get('caller')}'s\n"
        f"effects declaration. The declaration should be:\n"
        f"  effects: [{', '.join(combined)}];"
    )

    sections.append("Output only the fixed code in ```mumei ... ``` format.")

    return "\n\n".join(sections)
