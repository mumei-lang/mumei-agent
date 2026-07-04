"""Pure parsing/normalization and fix-suggestion helpers for spec-health strategy."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ContradictionInfo:
    """An atom whose ``spec_validation_result.is_satisfiable`` is false."""

    atom: str
    details: str = ""
    fix_suggestion: str = ""


@dataclass
class OverConstrainedInfo:
    """An atom with many unused hypotheses (requires, invariants, effects)."""

    atom: str
    unused_requires: list[str] = field(default_factory=list)
    unused_invariants: list[str] = field(default_factory=list)
    unused_effect_constraints: list[str] = field(default_factory=list)
    fix_suggestion: str = ""


@dataclass
class VacuousInfo:
    """An atom flagged as vacuous by ``--enable-vacuity-check``."""

    atom: str
    message: str = ""
    fix_suggestion: str = ""


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def _string_value(value: object, default: str = "") -> str:
    if isinstance(value, str):
        return value
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _collect_atoms(spec_json: dict[str, object]) -> list[dict[str, object]]:
    atoms = spec_json.get("atoms")
    if isinstance(atoms, list):
        return [_as_dict(atom) for atom in atoms if isinstance(atom, dict)]

    report = _as_dict(spec_json.get("report"))
    report_atoms = report.get("atoms")
    if isinstance(report_atoms, list):
        return [_as_dict(atom) for atom in report_atoms if isinstance(atom, dict)]

    if "spec_validation_result" in spec_json or "unused_hypotheses" in spec_json:
        return [spec_json]
    return []


def _vacuity_texts(verify_result: dict[str, object]) -> list[str]:
    texts: list[str] = []
    for key in ("stderr", "stdout"):
        value = verify_result.get(key)
        if isinstance(value, str) and value:
            texts.append(value)

    report = _as_dict(verify_result.get("report"))
    for key in ("reason", "message", "error"):
        value = report.get(key)
        if isinstance(value, str) and value:
            texts.append(value)

    diagnostics = report.get("diagnostics")
    if isinstance(diagnostics, list):
        texts.extend(item for item in diagnostics if isinstance(item, str))
    return texts


def _extract_atom_from_vacuity_line(line: str, fallback: str) -> str:
    for marker, quote in (("for '", "'"), ("for \u2018", "\u2019")):
        idx = line.find(marker)
        if idx >= 0:
            end = line.find(quote, idx + len(marker))
            if end >= 0:
                return line[idx + len(marker):end]
    return fallback


def _suggest_health_fix(kind: str, evidence: str) -> str:
    if kind == "contradiction":
        return (
            "Inspect the unsatisfiable constraints and relax one side of the conflict "
            f"(usually a `requires` bound or an incompatible `ensures` clause): `{evidence}`."
        )
    return (
        "Strengthen the spec so mutated implementations fail verification; add a concrete "
        f"postcondition, bound, or observable effect for the vacuous behavior: `{evidence}`."
    )


def _suggest_overconstrained_fix(
    unused_requires: list[str],
    unused_invariants: list[str],
    unused_effect_constraints: list[str],
) -> str:
    constraints = [*unused_requires, *unused_invariants, *unused_effect_constraints]
    if not constraints:
        return "Remove or weaken unused preconditions, invariants, or effect constraints."
    return (
        "Remove, weaken, or move these unused constraints to a narrower helper atom: "
        + ", ".join(f"`{constraint}`" for constraint in constraints[:5])
    )


def _collect_fix_suggestions(
    contradictions: list[ContradictionInfo],
    over_constrained: list[OverConstrainedInfo],
    vacuous: list[VacuousInfo],
) -> list[str]:
    suggestions: list[str] = []
    seen: set[str] = set()
    for contradiction in contradictions:
        if contradiction.fix_suggestion and contradiction.fix_suggestion not in seen:
            seen.add(contradiction.fix_suggestion)
            suggestions.append(contradiction.fix_suggestion)
    for issue in over_constrained:
        if issue.fix_suggestion and issue.fix_suggestion not in seen:
            seen.add(issue.fix_suggestion)
            suggestions.append(issue.fix_suggestion)
    for vacuity in vacuous:
        if vacuity.fix_suggestion and vacuity.fix_suggestion not in seen:
            seen.add(vacuity.fix_suggestion)
            suggestions.append(vacuity.fix_suggestion)
    return suggestions
