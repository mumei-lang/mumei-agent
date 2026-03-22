"""Common formatting helpers for report.json structured fields."""


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
