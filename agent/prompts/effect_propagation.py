"""Prompt template for effect_propagation violations."""


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing effect propagation violations."""
    ev = report_data.get("effect_violation", {})
    caller_effects = ev.get("caller_effects", [])
    missing_effects = ev.get("missing_effects", [])
    combined = sorted(set(caller_effects + missing_effects))

    return f"""
You are an expert in the Mumei language. The following code has an effect propagation violation.
Atom '{ev.get("caller")}' calls '{ev.get("callee")}' which requires effects {ev.get("callee_effects")},
but '{ev.get("caller")}' only declares effects {ev.get("caller_effects")}.
Missing effects: {ev.get("missing_effects")}

# Source code:
{source_code}

# Error log:
{error_log}

# Resolution:
Add the missing effects {missing_effects} to atom '{ev.get("caller")}'s
effects declaration. The declaration should be:
  effects: [{", ".join(combined)}];

Output only the fixed code in ```mumei ... ``` format.
"""
