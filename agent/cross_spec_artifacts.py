"""Mapping of mumei cross-spec report arrays to agent alignment artifacts.

`cross_spec.json` carries `agent_artifact_mapping[]`, which declares how each
compiler-side array is consumed on the agent side. `session_protocol_violations[]`
maps to `missing_constraints[]` with contradiction type `spec_vs_code`: a protocol
violation is an ordering constraint that the participating specifications do not
enforce.
"""
from __future__ import annotations

from typing import Any

SESSION_VIOLATION_FIELD = "session_protocol_violations[]"
SESSION_VIOLATION_AGENT_FIELD = "missing_constraints[]"
SESSION_VIOLATION_CONTRADICTION_TYPE = "spec_vs_code"


def session_protocol_violations(cross_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the session protocol violations of one cross-spec report."""
    violations = cross_spec.get("session_protocol_violations")
    if not isinstance(violations, list):
        return []
    return [violation for violation in violations if isinstance(violation, dict)]


def session_analysis_skips(cross_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return effects the bounded session analysis did not check.

    The analysis is fail-open, so an empty violation array alone does not mean
    every protocol was verified.
    """
    skips = cross_spec.get("session_analysis_skips")
    if not isinstance(skips, list):
        return []
    return [skip for skip in skips if isinstance(skip, dict)]


def session_protocol_missing_constraints(
    violations: list[dict[str, Any]],
) -> list[str]:
    """Render session protocol violations as `missing_constraints[]` strings."""
    constraints: list[str] = []
    for violation in violations:
        effect = str(violation.get("effect") or "<unknown effect>")
        kind = str(violation.get("kind") or "session_protocol_violation")
        message = str(violation.get("message") or "")
        suggested_fix = str(violation.get("suggested_fix") or "")
        text = f"[{effect}/{kind}] {message}".strip()
        if suggested_fix:
            text = f"{text} Suggested fix: {suggested_fix}"
        if text not in constraints:
            constraints.append(text)
    return constraints


def session_protocol_atoms(violation: dict[str, Any]) -> list[str]:
    """Return the atoms participating in one violation, without duplicates."""
    atoms: list[str] = []
    for key in ("caller_atom", "callee_atom"):
        atom = violation.get(key)
        if isinstance(atom, str) and atom.strip() and atom not in atoms:
            atoms.append(atom.strip())
    return atoms


def session_protocol_files(violation: dict[str, Any]) -> list[str]:
    """Return the spec files participating in one violation."""
    files: list[str] = []
    for key in ("caller_file", "callee_file"):
        file = violation.get(key)
        if isinstance(file, str) and file.strip() and file not in files:
            files.append(file.strip())
    return files
