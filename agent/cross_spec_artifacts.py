"""Mapping of mumei cross-spec report arrays to agent alignment artifacts.

`cross_spec.json` carries `agent_artifact_mapping[]`, which declares how each
compiler-side array is consumed on the agent side. `session_protocol_violations[]`
maps to `missing_constraints[]` with contradiction type `spec_vs_code`: a protocol
violation is an ordering constraint that the participating specifications do not
enforce.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SESSION_VIOLATION_FIELD = "session_protocol_violations[]"
SESSION_VIOLATION_AGENT_FIELD = "missing_constraints[]"
SESSION_VIOLATION_CONTRADICTION_TYPE = "spec_vs_code"


def artifact_mapping_divergences(cross_spec: dict[str, Any]) -> list[str]:
    """Compare the declared `agent_artifact_mapping[]` with the mapping used here.

    The agent-side target is a field of the self-healing/MCP contract and cannot
    be re-pointed at runtime, so a compiler-side mapping change is reported
    instead of silently followed.
    """
    mapping = cross_spec.get("agent_artifact_mapping")
    if not isinstance(mapping, list):
        return []
    divergences: list[str] = []
    for entry in mapping:
        if not isinstance(entry, dict):
            continue
        if entry.get("cross_spec_field") != SESSION_VIOLATION_FIELD:
            continue
        for key, expected in (
            ("agent_field", SESSION_VIOLATION_AGENT_FIELD),
            ("contradiction_type", SESSION_VIOLATION_CONTRADICTION_TYPE),
        ):
            declared = entry.get(key)
            if declared is not None and declared != expected:
                divergences.append(
                    f"{SESSION_VIOLATION_FIELD} declares {key}={declared!r} "
                    f"but the agent maps it to {expected!r}"
                )
    for divergence in divergences:
        logger.warning("cross-spec artifact mapping diverged: %s", divergence)
    return divergences


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
