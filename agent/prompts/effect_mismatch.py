"""Prompt template for effect_mismatch violations."""


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing effect mismatch violations."""
    ev = report_data.get("effect_violation", {})
    resolution_paths = ev.get("resolution_paths", [])
    opt_a = resolution_paths[0].get("description", "") if resolution_paths else ""
    opt_b = resolution_paths[1].get("description", "") if len(resolution_paths) > 1 else "Remove the offending call."

    return f"""
You are an expert in the Mumei language. The following code has an effect violation.
The atom '{report_data.get("atom")}' declares effects {ev.get("declared_effects")}
but uses operation '{ev.get("source_operation")}' which requires [{ev.get("required_effect")}].

# Source code:
{source_code}

# Error log:
{error_log}

# Resolution paths (choose ONE):

## Option A: Propagation (expand the effect boundary)
{opt_a}
Add the missing effect to the atom's `effects:` declaration.

## Option B: Isolation (remove the effectful operation)
{opt_b}
Replace the effectful operation with a pure computation.

Output only the fixed code in ```mumei ... ``` format.
Choose the option that best preserves the code's intent.
"""
