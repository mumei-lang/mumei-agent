"""Prompt template for generic atom generation from a spec JSON."""
import json

from agent.prompts.report_formatter import (
    format_actionable_fix_hint,
    format_for_initial_generate,
    format_structured_unsat_core,
    format_data_flow,
)

# Common mistakes checklist injected into all generation prompts.
# Shared with generate_stdlib via import.
COMMON_MISTAKES = (
    "# Common mistakes to avoid:\n"
    "1. **Division by zero**: If dividing, add `requires: divisor != 0`\n"
    "2. **Linearity**: If a parameter is `linear`, it can only be used once. "
    "Clone before reuse.\n"
    "3. **Temporal effects**: Effect operations must follow the state machine "
    "(e.g., File: open -> read/write -> close)\n"
    "4. **Postcondition mismatch**: Ensure the body's return value satisfies "
    "the `ensures` clause for ALL inputs satisfying `requires`\n"
    "5. **Missing effects**: Every `perform` call requires the effect to be "
    "listed in the `effects:` clause\n"
    "6. **Effect propagation**: If you call another atom with effects, your "
    "atom must declare those effects too\n"
    "7. **Consumed params**: Parameters listed in `consumed_params` are linear "
    "and must not be used after being passed to a consuming operation\n"
    "8. **Reuse std contracts**: Before writing custom validation, check if "
    "std/contracts.mm already provides the type or atom you need "
    "(e.g., Port, Percentage, clamp, safe_divide). "
    "Use `import \"std/contracts\" as contracts;` and call `contracts::clamp(val, min, max)`\n"
    "9. **Fixed-point arithmetic**: For financial calculations, use "
    "std/math/fixed_point.mm instead of raw i64 division to prevent precision loss"
)


def build_prompt(source_code: str, error_log: str, report_data: dict, *, inferred_context: dict | None = None) -> str:
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

    sections.append(COMMON_MISTAKES)

    # Pre-generation checklist if spec is parseable as JSON
    try:
        spec_dict = json.loads(source_code) if isinstance(source_code, str) else source_code
        if isinstance(spec_dict, dict):
            checklist = format_for_initial_generate(spec_dict)
            if checklist:
                sections.append(checklist)
    except (json.JSONDecodeError, TypeError):
        pass

    sections.append(f"# Specification:\n{source_code}")

    if error_log:
        sections.append(
            f"# Previous attempt produced errors. Fix these:\n{error_log}"
        )

    if report_data:
        # Actionable fix hint (human-readable)
        hint = format_actionable_fix_hint(report_data)
        if hint:
            sections.append(f"# Actionable fix instructions:\n{hint}")

        # Structured unsat core
        suc = format_structured_unsat_core(report_data)
        if suc:
            sections.append(f"# Structured Unsat Core (conflicting constraints from Z3):\n{suc}")

        # Data flow trace
        df = format_data_flow(report_data)
        if df:
            sections.append(f"# {df}")

        # Full report as fallback context
        sections.append(
            f"# Verification report from previous attempt:\n"
            f"{json.dumps(report_data, indent=2, ensure_ascii=False)}"
        )

    if inferred_context is not None:
        sections.append(
            f"# Inferred effects (from mumei infer-effects):\n"
            f"{json.dumps(inferred_context.get('effects', {}), indent=2)}"
        )
        sections.append(
            f"# Inferred contracts (from mumei infer-contracts):\n"
            f"{json.dumps(inferred_context.get('contracts', {}), indent=2)}"
        )

    sections.append("Output only the complete .mm file in ```mumei ... ``` format.")

    return "\n\n".join(sections)
