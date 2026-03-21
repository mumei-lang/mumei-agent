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
