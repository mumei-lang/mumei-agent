"""Report formatting core helpers for report.json structured fields."""
from __future__ import annotations


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
