"""Rule-based deterministic fixes for common verification failures.

These fixes modify Mumei source code directly based on structured
verification report data, without calling an LLM. Each fix function
returns the modified source code on success, or None if the rule
cannot be applied.
"""
from __future__ import annotations

from agent.strategies.rule_based_fix_helpers import (
    _append_to_requires,
    _find_atom_declaration_end,
    _find_atom_effects,
    _find_atom_requires,
    _fix_division_by_zero,
    _fix_effect_mismatch,
    _fix_effect_propagation,
    _fix_invariant_violated,
    _fix_linearity_violated,
    _fix_postcondition_violated,
    _fix_precondition,
    _scoped_block,
)


def try_rule_based_fix(source_code: str, report: dict) -> str | None:
    """Attempt a deterministic fix based on the verification report.

    Returns modified source code if a rule applies, None otherwise.
    """
    failure_type = report.get("failure_type", "")
    violation_type = report.get("violation_type", "")

    # Check violation_type first to match the priority used by
    # _build_prompt_for_report in fix_strategy.py (and tested by
    # test_violation_type_takes_precedence_over_failure_type).
    if violation_type == "effect_mismatch":
        return _fix_effect_mismatch(source_code, report)
    elif violation_type == "effect_propagation":
        return _fix_effect_propagation(source_code, report)
    elif failure_type == "division_by_zero":
        return _fix_division_by_zero(source_code, report)
    elif failure_type == "linearity_violated" or violation_type == "linearity_violated":
        return _fix_linearity_violated(source_code, report)
    elif failure_type == "postcondition_violated" or violation_type == "postcondition_violated":
        return _fix_postcondition_violated(source_code, report)
    elif failure_type == "invariant_violated" or violation_type == "invariant_violated":
        return _fix_invariant_violated(source_code, report)
    elif failure_type == "precondition_violated" or violation_type == "precondition_violated":
        return _fix_precondition(source_code, report)
    return None
