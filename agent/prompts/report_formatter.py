"""Common formatting helpers for report.json structured fields."""
from __future__ import annotations

# Keywords that indicate a suggestion was dynamically generated from
# counterexample data rather than being a generic template fallback.
_CONTEXTUAL_MARKERS = (
    "counterexample",
    "counter-example",
    "e.g.",
    "for example",
    "value",
    "when ",
    "because ",
    "specific",
    "=",
)


def format_counterexample(report: dict) -> str:
    """Format counterexample field into human-readable string.

    Example output: "Z3 Counter-example: a=0, b=0"
    """
    ce = report.get("counterexample")
    if not ce or not isinstance(ce, dict):
        return ""
    pairs = ", ".join(f"{k}={v}" for k, v in ce.items())
    return f"Z3 Counter-example: {pairs}"


def format_violated_constraints(report: dict) -> str:
    """Format semantic_feedback.violated_constraints into structured text."""
    sf = report.get("semantic_feedback")
    if not sf or not isinstance(sf, dict):
        return ""
    constraints = sf.get("violated_constraints")
    if not constraints or not isinstance(constraints, list):
        return ""

    lines: list[str] = []
    for vc in constraints:
        param = vc.get("param", "?")
        typ = vc.get("type", "?")
        constraint = vc.get("constraint", "?")
        explanation = vc.get("explanation", "")
        lines.append(f"- Param '{param}' (type {typ}): constraint `{constraint}`")
        if explanation:
            lines.append(f"  Explanation: {explanation}")
        suggestion = vc.get("suggestion")
        if suggestion:
            lines.append(f"  Suggestion: {suggestion}")
        subs = vc.get("sub_constraints")
        if subs and isinstance(subs, list):
            for sc in subs:
                status = "SATISFIED" if sc.get("satisfied") else "VIOLATED"
                lines.append(f"  [{status}] {sc.get('constraint', '?')}")
    return "\n".join(lines)


def format_unsat_core(report: dict) -> str:
    """Format semantic_feedback.conflicting_constraints and raw_unsat_core."""
    sf = report.get("semantic_feedback")
    if not sf or not isinstance(sf, dict):
        return ""

    parts: list[str] = []
    cc = sf.get("conflicting_constraints")
    if cc and isinstance(cc, list):
        parts.append("Conflicting constraints:")
        for c in cc:
            parts.append(f"  - {c}")

    raw = sf.get("raw_unsat_core")
    if raw and isinstance(raw, list):
        parts.append("Raw unsat core:")
        for r in raw:
            parts.append(f"  - {r}")

    return "\n".join(parts)


def is_contextual_suggestion(suggestion: str) -> bool:
    """Determine whether *suggestion* was dynamically generated.

    A contextual suggestion is one produced by ``build_contextual_suggestion()``
    on the mumei side.  It typically references concrete counterexample values,
    specific variable names, or conditional language ("when", "because").

    Generic template suggestions (from ``suggestion_for_failure_type()``) tend
    to be short, imperative sentences without concrete data.
    """
    if not suggestion:
        return False
    lower = suggestion.lower()
    return any(marker in lower for marker in _CONTEXTUAL_MARKERS)


def format_suggestion(report: dict) -> str:
    """Format suggestion field."""
    suggestion = report.get("suggestion")
    if not suggestion:
        return ""
    return f"Suggestion: {suggestion}"


def format_span(report: dict) -> str:
    """Format span field into 'Location: file.mm:10:1' form."""
    span = report.get("span")
    if not span or not isinstance(span, dict):
        return ""
    f = span.get("file", "?")
    line = span.get("line", "?")
    col = span.get("col", "?")
    return f"Location: {f}:{line}:{col}"


def format_error_diff(prev_report: dict, curr_report: dict) -> str:
    """Compare two verification reports and produce a structured diff string.

    Compares: failure_type, violation_type, counterexample, violated_constraints,
    and suggestion fields.  Returns a human-readable diff.
    """
    lines: list[str] = []

    # --- failure_type ---
    prev_ft = prev_report.get("failure_type", "unknown")
    curr_ft = curr_report.get("failure_type", "unknown")
    if prev_ft == curr_ft:
        lines.append(f"- failure_type: UNCHANGED ({curr_ft})")
    else:
        lines.append(f"- failure_type: CHANGED ({prev_ft} -> {curr_ft})")

    # --- violation_type ---
    prev_vt = prev_report.get("violation_type", "")
    curr_vt = curr_report.get("violation_type", "")
    if prev_vt or curr_vt:
        if prev_vt == curr_vt:
            lines.append(f"- violation_type: UNCHANGED ({curr_vt})")
        else:
            lines.append(
                f"- violation_type: CHANGED ({prev_vt or 'none'} -> {curr_vt or 'none'})"
            )

    # --- counterexample ---
    prev_ce = prev_report.get("counterexample") or {}
    curr_ce = curr_report.get("counterexample") or {}
    prev_ce_str = ", ".join(f"{k}={v}" for k, v in prev_ce.items()) if prev_ce else "none"
    curr_ce_str = ", ".join(f"{k}={v}" for k, v in curr_ce.items()) if curr_ce else "none"
    if prev_ce == curr_ce:
        lines.append(f"- counterexample: UNCHANGED ({curr_ce_str})")
    else:
        lines.append(f"- counterexample: CHANGED ({prev_ce_str} -> {curr_ce_str})")

    # --- violated_constraints ---
    prev_vc = _extract_constraint_set(prev_report)
    curr_vc = _extract_constraint_set(curr_report)
    resolved = prev_vc - curr_vc
    new_vc = curr_vc - prev_vc
    if resolved or new_vc:
        lines.append(
            f"- violated_constraints: {len(resolved)} resolved, {len(new_vc)} new"
        )
        for c in sorted(resolved):
            lines.append(f"  - RESOLVED: {c}")
        for c in sorted(new_vc):
            lines.append(f"  - NEW: {c}")
    elif curr_vc:
        lines.append("- violated_constraints: UNCHANGED")

    # --- suggestion ---
    prev_sug = prev_report.get("suggestion", "")
    curr_sug = curr_report.get("suggestion", "")
    if prev_sug != curr_sug and (prev_sug or curr_sug):
        lines.append(f"- suggestion: CHANGED")
        if curr_sug:
            lines.append(f"  Now: {curr_sug}")

    return "\n".join(lines)


def _extract_constraint_set(report: dict) -> set[str]:
    """Extract a set of constraint description strings from a report."""
    sf = report.get("semantic_feedback")
    if not sf or not isinstance(sf, dict):
        return set()
    constraints = sf.get("violated_constraints")
    if not constraints or not isinstance(constraints, list):
        return set()
    result: set[str] = set()
    for vc in constraints:
        param = vc.get("param", "?")
        constraint = vc.get("constraint", "?")
        result.add(f"param '{param}' constraint `{constraint}`")
    return result


def format_structured_unsat_core(report: dict) -> str:
    """Format semantic_feedback.structured_unsat_core into human-readable text.

    Each element has the shape:
        {"constraint_type": "requires"|"refined_type"|"struct_field"|"quantifier"|"u64_nonneg",
         "param": str|null, "type_name": str|null, "field": str|null,
         "description": str}
    """
    sf = report.get("semantic_feedback")
    if not sf or not isinstance(sf, dict):
        return ""
    suc = sf.get("structured_unsat_core")
    if not suc or not isinstance(suc, list):
        return ""

    lines: list[str] = []
    for entry in suc:
        ctype = entry.get("constraint_type", "unknown")
        desc = entry.get("description", "")
        param = entry.get("param")
        type_name = entry.get("type_name")
        field = entry.get("field")

        detail_parts: list[str] = []
        if param:
            detail_parts.append(f"param '{param}'")
        if type_name:
            detail_parts.append(f"type {type_name}")
        if field:
            detail_parts.append(f"field '{field}'")

        detail = f" {', '.join(detail_parts)}:" if detail_parts else ""
        suffix = f" {desc}" if desc else ""
        lines.append(f"- [{ctype}]{detail}{suffix}")

    return "\n".join(lines)


def _safe_sf(report: dict) -> dict:
    """Return ``semantic_feedback`` as a dict, defaulting to ``{}`` on null/missing."""
    sf = report.get("semantic_feedback")
    if not sf or not isinstance(sf, dict):
        return {}
    return sf


def _safe_dict(report: dict, key: str) -> dict:
    """Return *key* from *report* as a dict, defaulting to ``{}`` on null/missing."""
    val = report.get(key)
    if not val or not isinstance(val, dict):
        return {}
    return val


def format_actionable_fix_hint(report: dict) -> str:
    """Translate a structured verification failure into concrete fix instructions.

    Produces one or more actionable sentences telling the LLM exactly what to
    change and why, derived from the report's failure_type, violation_type,
    semantic_feedback, and counterexample fields.
    """
    lines: list[str] = []
    failure_type = report.get("failure_type", "")
    violation_type = report.get("violation_type", "")

    # --- division_by_zero ---
    if failure_type == "division_by_zero":
        sf = _safe_sf(report)
        ce = sf.get("counter_example") or {}
        if not isinstance(ce, dict):
            ce = {}
        divisor = ce.get("divisor", "the divisor")
        lines.append(
            f"The divisor `{divisor}` can be zero. "
            "Add `requires: <divisor_param> != 0` to the atom's precondition."
        )

    # --- linearity_violated ---
    elif failure_type == "linearity_violated":
        sf = _safe_sf(report)
        violations = sf.get("violations") or []
        if not isinstance(violations, list):
            violations = []
        for v in violations:
            desc = v.get("description", str(v)) if isinstance(v, dict) else str(v)
            lines.append(
                f"Linear resource violation: {desc}. "
                "Either clone the resource before the second use, or restructure "
                "the code so each linear value is consumed exactly once."
            )
        if not violations:
            lines.append(
                "A linear resource is used more than once. "
                "Clone before the second use or restructure to consume each value once."
            )

    # --- invariant_violated ---
    elif failure_type == "invariant_violated":
        sf = _safe_sf(report)
        cc = sf.get("conflicting_constraints") or []
        if not isinstance(cc, list):
            cc = []
        if cc:
            constraints_str = ", ".join(f"`{c}`" for c in cc[:4])
            lines.append(
                f"The constraints {constraints_str} are contradictory. "
                "Relax one or more constraints so they can be simultaneously satisfied."
            )
        else:
            lines.append(
                "The constraints are contradictory — the verifier found an unsatisfiable core. "
                "Relax one or more of the conflicting constraints."
            )

    # --- postcondition_violated ---
    elif failure_type == "postcondition_violated":
        ce = _safe_dict(report, "counterexample")
        if ce:
            ce_str = ", ".join(f"{k}={v}" for k, v in ce.items())
            lines.append(
                f"The `ensures` clause is not satisfied for inputs: {ce_str}. "
                "Fix the body to satisfy `ensures`, or adjust `ensures` to match actual behaviour."
            )
        else:
            lines.append(
                "The `ensures` clause is not satisfied by the function body's return value. "
                "Fix the body or adjust `ensures`."
            )

    # --- temporal_effect_violated ---
    elif failure_type == "temporal_effect_violated":
        lines.append(
            "The effect state transitions are in the wrong order. "
            "Reorder `perform` calls to follow the correct state machine "
            "(e.g., File: open -> write/read -> close)."
        )

    # --- effect_mismatch ---
    elif violation_type == "effect_mismatch":
        ev = _safe_dict(report, "effect_violation")
        required = ev.get("required_effect", "?")
        declared = ev.get("declared_effects", [])
        lines.append(
            f"Effect `{required}` is used in the body but not declared in "
            f"the effects list (currently: {declared}). "
            f"Add `{required}` to the effects list."
        )

    # --- effect_propagation ---
    elif violation_type == "effect_propagation":
        ev = _safe_dict(report, "effect_violation")
        missing = ev.get("missing_effects", [])
        caller = ev.get("caller", "the caller")
        callee = ev.get("callee", "the callee")
        if missing:
            lines.append(
                f"Caller `{caller}` calls `{callee}` which requires effects "
                f"{missing} that are not declared. Add them to `{caller}`'s effects list."
            )
        else:
            lines.append(
                f"Caller `{caller}` calls `{callee}` but does not propagate all "
                "required effects. Check that all callee effects are declared in the caller."
            )

    # --- precondition (generic fallback) ---
    elif failure_type == "precondition_violated" or not lines:
        sf = _safe_sf(report)
        vc = sf.get("violated_constraints") or []
        if not isinstance(vc, list):
            vc = []
        for c in vc[:3]:
            param = c.get("param", "?") if isinstance(c, dict) else "?"
            constraint = c.get("constraint", "?") if isinstance(c, dict) else "?"
            lines.append(
                f"The requires clause `{constraint}` was not satisfied for param `{param}`. "
                "Ensure the caller provides a value that meets this constraint."
            )

    # --- structured_unsat_core enrichment ---
    sf = _safe_sf(report)
    suc = sf.get("structured_unsat_core") or []
    if not isinstance(suc, list):
        suc = []
    if suc and not lines:
        for entry in suc[:3]:
            desc = entry.get("description", "") if isinstance(entry, dict) else ""
            if desc:
                lines.append(f"Constraint conflict: {desc}")

    # --- contextual suggestion enrichment ---
    # If the suggestion is contextual (dynamically generated with concrete
    # counterexample data), surface it alongside existing hints for maximum
    # precision.  Generic template suggestions are only used as a last-resort
    # fallback when no other hints are available.
    sug = report.get("suggestion", "")
    if sug and lines and is_contextual_suggestion(sug):
        lines.append(f"Verifier suggestion (contextual): {sug}")
    elif not lines:
        if sug:
            lines.append(f"Verifier suggestion: {sug}")
        else:
            lines.append("Verification failed. Review the error log and fix the code.")

    return "\n".join(lines)


def format_for_initial_generate(spec: dict) -> str:
    """Extract relevant constraints from a spec to pre-warn the LLM.

    Produces a checklist of things the LLM should keep in mind when generating
    code from the specification.
    """
    lines: list[str] = ["# Pre-generation checklist from spec:"]

    constraints = spec.get("constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
    requires = constraints.get("requires", "")
    ensures = constraints.get("ensures", "")
    if requires:
        lines.append(f"- The `requires` clause must be: `{requires}`")
    if ensures:
        lines.append(f"- The `ensures` clause must be: `{ensures}`")

    effects = spec.get("effects", [])
    if effects:
        lines.append(f"- Declared effects: {effects}")
        lines.append("- Use `perform <Effect>.<operation>(args)` for each side effect")

    inputs = spec.get("inputs", spec.get("params", []))
    if not isinstance(inputs, list):
        inputs = []
    for inp in inputs:
        name = inp.get("name", "?")
        typ = inp.get("type", "i64")
        lines.append(f"- Param `{name}`: type `{typ}`")

    lines.append("- Every atom MUST have requires, ensures, and body clauses")
    lines.append("- The body must satisfy the ensures clause for all inputs satisfying requires")
    lines.append("- Do NOT use effects that are not declared in the effects list")

    return "\n".join(lines)


def format_data_flow(report: dict) -> str:
    """Format semantic_feedback.data_flow trace."""
    sf = report.get("semantic_feedback")
    if not sf or not isinstance(sf, dict):
        return ""
    df = sf.get("data_flow")
    if not df or not isinstance(df, list):
        return ""

    lines: list[str] = ["Data flow trace:"]
    for entry in df:
        if isinstance(entry, str):
            lines.append(f"  - {entry}")
        elif isinstance(entry, dict):
            lines.append(f"  - {entry.get('expression', '?')}: {entry.get('value', '?')}")
    return "\n".join(lines)
