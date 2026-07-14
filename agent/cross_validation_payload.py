"""Cross-validation payload parsing and atom rendering helpers."""
from __future__ import annotations

import json
import re

from agent.cross_validation_foreign import _safe_identifier
from agent.cross_validation_models import (
    ContractParam,
    CrossValidationIssue,
    IssueKind,
    MumeiContractAtom,
    Severity,
)


def _json_from_text(text: str) -> dict[str, object]:
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1)
    else:
        # Tolerate a leading prose preamble by seeking the first object, and a
        # trailing prose/second-object suffix by decoding only the first JSON
        # value (small/OSS models routinely append an explanation after the
        # JSON, which plain ``json.loads`` rejects with "Extra data").
        start = stripped.find("{")
        if start > 0:
            stripped = stripped[start:]
    payload, _end = json.JSONDecoder().raw_decode(stripped)
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("expected JSON object", stripped, 0)
    return payload


def _atoms_from_payload(payload: dict[str, object]) -> list[MumeiContractAtom]:
    atoms_value = payload.get("atoms")
    if not isinstance(atoms_value, list):
        return []
    atoms: list[MumeiContractAtom] = []
    for index, atom_value in enumerate(atoms_value):
        if isinstance(atom_value, dict):
            atoms.append(_atom_from_mapping(atom_value, index))
    return atoms


def _requires_clause(value: object) -> str:
    """Normalize a precondition clause from an LLM-extracted JSON payload.

    Small OSS models frequently emit ``false`` when there is no meaningful
    precondition.  A literal ``false`` precondition is unsatisfiable and would
    always refute the code, so treat it as the intended ``true`` (no
    precondition).  This only applies to the LLM JSON payload path; other
    call-sites can still use ``requires: false`` to express a genuine
    unsatisfiable precondition.
    """
    clause = _contract_clause(value)
    return "true" if clause.strip().lower() == "false" else clause


def _ensures_clause(value: object) -> str:
    """Normalize a postcondition clause from an LLM-extracted JSON payload.

    Small OSS models also emit ``false`` for the postcondition when they cannot
    infer a meaningful return value (or when the function has no return value).
    A literal ``false`` postcondition is unsatisfiable and produces false
    `refuted` verdicts for otherwise valid code, so treat it as the intended
    ``true`` (no postcondition).  This only applies to the LLM JSON payload path;
    manually-written specs and test fixtures can still use ``ensures: false`` to
    express a genuine contradiction.
    """
    clause = _contract_clause(value)
    return "true" if clause.strip().lower() == "false" else clause


def _atom_from_mapping(value: dict[object, object], index: int) -> MumeiContractAtom:
    name = _safe_identifier(_string_value(value, "name", f"cross_validation_{index}"))
    params = _params_from_value(value.get("params") or value.get("inputs"))
    return_type = _string_value(value, "return_type", "i64")
    requires = _requires_clause(value.get("requires"))
    ensures = _ensures_clause(value.get("ensures"))
    effects = _string_list(value.get("effects"))
    return MumeiContractAtom(
        name=name,
        params=params,
        return_type=return_type,
        requires=requires,
        ensures=ensures,
        effects=effects,
    )


def _issues_from_payload(payload: dict[str, object]) -> list[CrossValidationIssue]:
    issues_value = payload.get("issues")
    if not isinstance(issues_value, list):
        return []
    issues: list[CrossValidationIssue] = []
    valid_kinds = {
        "contradiction",
        "ambiguity",
        "overconstraint",
        "satisfiability",
        "llm",
        "verification",
        "alignment",
        "missing_implementation",
        "postcondition_violated",
        "drift",
    }
    for issue_value in issues_value:
        if not isinstance(issue_value, dict):
            continue
        kind_text = str(issue_value.get("kind") or "llm")
        kind: IssueKind = kind_text if kind_text in valid_kinds else "llm"
        severity_text = str(issue_value.get("severity") or "error")
        severity: Severity = "warning" if severity_text == "warning" else "error"
        issues.append(
            CrossValidationIssue(
                kind=kind,
                message=str(issue_value.get("message") or "LLM reported a cross-validation issue."),
                evidence=str(issue_value.get("evidence") or ""),
                fix_suggestion=str(issue_value.get("fix_suggestion") or ""),
                location=str(issue_value.get("location") or ""),
                severity=severity,
                source_line=_int_value(issue_value.get("source_line")),
            )
        )
    return issues


def _string_value(value: dict[object, object], key: str, default: str) -> str:
    raw = value.get(key)
    if raw is None:
        return default
    text = str(raw).strip()
    return text or default


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _params_from_value(value: object) -> list[ContractParam]:
    if not isinstance(value, list):
        return []
    params: list[ContractParam] = []
    for index, raw_param in enumerate(value):
        if isinstance(raw_param, dict):
            name = _safe_identifier(str(raw_param.get("name") or f"arg{index}"))
            type_name = str(raw_param.get("type") or "i64").strip() or "i64"
            params.append(ContractParam(name=name, type=type_name))
    return params


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_mumei_boolean_literals(clause: str) -> str:
    """Map Python/JSON-style boolean literals to Mumei lowercase keywords.

    LLMs and JSON decoders may produce ``True``/``False`` (Python bools) or
    the capitalized strings ``"True"``/``"False"``.  Mumei source expects
    lowercase ``true``/``false`` in contract clauses, so normalize them before
    writing ``.mm`` files or passing clauses to Z3/mumei.
    """
    return re.sub(r"\bTrue\b", "true", re.sub(r"\bFalse\b", "false", clause))


def _contract_clause(value: object) -> str:
    if isinstance(value, bool):
        clause = "true" if value else "false"
    elif isinstance(value, list):
        parts = [str(item).strip().rstrip(";") for item in value if str(item).strip()]
        clause = " && ".join(parts) if parts else "true"
    else:
        clause = str(value).strip().rstrip(";") if value is not None else "true"
        clause = clause or "true"
    return _normalize_mumei_boolean_literals(clause)


def _extract_inline_contract_atoms(spec_text: str) -> list[MumeiContractAtom]:
    requires_match = re.search(r"requires\s*:\s*([^;\n]+)", spec_text, flags=re.IGNORECASE)
    ensures_match = re.search(r"ensures\s*:\s*([^;\n]+)", spec_text, flags=re.IGNORECASE)
    if not requires_match and not ensures_match:
        return []
    return [
        MumeiContractAtom(
            name="nl_spec_contract",
            params=_params_from_contract_text(spec_text),
            return_type="i64",
            requires=requires_match.group(1).strip() if requires_match else "true",
            ensures=ensures_match.group(1).strip() if ensures_match else "true",
        )
    ]


def _params_from_contract_text(text: str) -> list[ContractParam]:
    names = sorted(
        name
        for name in set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", text))
        if name
        not in {
            "and",
            "or",
            "true",
            "false",
            "requires",
            "ensures",
            "result",
            "i64",
            "MAX",
            "MIN",
        }
    )
    return [ContractParam(name=name, type="i64") for name in names[:8]]


def _atoms_to_mumei_module(atoms: list[MumeiContractAtom]) -> str:
    blocks: list[str] = []
    for atom in atoms:
        params = ", ".join(f"{param.name}: {param.type}" for param in atom.params)
        default_value = _default_literal(atom.return_type)
        requires = _normalize_mumei_boolean_literals(atom.requires)
        ensures = _normalize_mumei_boolean_literals(atom.ensures)
        blocks.append(
            "\n".join(
                [
                    f"trusted atom {atom.name}({params}) -> {atom.return_type} {{",
                    f"    requires: {requires};",
                    f"    ensures: {ensures};",
                    "    body: {",
                    f"        {default_value}",
                    "    }",
                    "}",
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _default_literal(return_type: str) -> str:
    normalized = return_type.strip().lower()
    if normalized in {"bool", "boolean"}:
        return "true"
    if normalized in {"str", "string"}:
        return '""'
    if normalized in {"()", "void", "unit", "none", "nonetype"}:
        return "()"
    if normalized in {"float", "f64"}:
        return "0.0"
    return "0"
