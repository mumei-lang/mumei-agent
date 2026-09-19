"""Domain completeness and NL-spec health checks.

V1-A-2: when a caller passes a domain hint (``audit --domain-hint`` /
``validate-spec --domain``), the extracted spec is checked for
domain-required conditions beyond generic contradiction/vacuity health.
Missing conditions are reported as ``domain-completeness:`` warnings so
they flow into the same ``spec_health_issues`` (audit) /
``completeness_warnings`` (validate-spec) channels as other spec findings.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.config import AgentConfig
    from agent.cross_validation import CrossValidationIssue, MumeiContractAtom


# Each checklist item carries:
#   keywords:    alternative substrings; any match counts as coverage.
#   clause:      ``requires`` / ``ensures`` scopes the search to that contract
#                clause when the spec carries formal atoms; ``any`` searches the
#                whole spec.  For prose-only specs (no atoms and no clause-labelled
#                lines) clause-scoped items fall back to the full spec text.
#   description: human-readable name of the expected condition.
DOMAIN_CHECKLISTS: dict[str, list[dict[str, object]]] = {
    "financial": [
        {
            "keywords": ["balance conservation", "conservation", "conserved", "old("],
            "clause": "ensures",
            "description": "残高保存則（送受信合計が不変）",
        },
        {
            "keywords": ["non-negative", "non_negative", ">= 0", ">=0"],
            "clause": "requires",
            "description": "非負の金額・残高条件",
        },
        {
            "keywords": ["amount > 0", "amount>0", "amount >= 1", "positive amount"],
            "clause": "requires",
            "description": "金額正値条件",
        },
        {
            "keywords": [
                "insufficient",
                "balance >= amount",
                "balance>=amount",
                "sufficient",
            ],
            "clause": "any",
            "description": "残高不足エラー条件",
        },
    ],
    "security": [
        {
            "keywords": ["auth", "caller ==", "msg.sender"],
            "clause": "requires",
            "description": "認証チェック",
        },
        {
            "keywords": ["sanitize", "escape", "validate input"],
            "clause": "any",
            "description": "入力サニタイズ",
        },
        {
            "keywords": [
                "permission",
                "only_owner",
                "onlyowner",
                "authorized",
                "role",
            ],
            "clause": "requires",
            "description": "権限チェック",
        },
    ],
    "crypto": [
        {
            "keywords": ["hash"],
            "clause": "any",
            "description": "ハッシュ整合性",
        },
        {
            "keywords": ["signature", "signed"],
            "clause": "any",
            "description": "署名検証",
        },
    ],
    "data_structure": [
        {
            "keywords": ["bounds", "< len", "< size", "index <", "in bounds"],
            "clause": "any",
            "description": "境界チェック",
        },
        {
            "keywords": [
                "non-null",
                "non_null",
                "non-nil",
                "!= null",
                "not null",
                "!= nil",
            ],
            "clause": "requires",
            "description": "null安全性",
        },
    ],
}


_REQUIRES_LINE_RE = re.compile(r"requires|precondition", re.IGNORECASE)
_ENSURES_LINE_RE = re.compile(r"ensures|postcondition|invariant", re.IGNORECASE)
_TRIVIAL_CLAUSES = {"", "true", "false"}


def _clause_lines(spec_text: str, pattern: re.Pattern[str]) -> str:
    return "\n".join(
        line for line in spec_text.splitlines() if pattern.search(line)
    )


def _non_trivial_clauses(atoms: list[MumeiContractAtom], field: str) -> list[str]:
    clauses: list[str] = []
    for atom in atoms:
        clause = (atom.requires if field == "requires" else atom.ensures).strip()
        if clause.lower() not in _TRIVIAL_CLAUSES:
            clauses.append(clause)
    return clauses


def check_domain_completeness(
    spec_text: str,
    atoms: list[MumeiContractAtom],
    domain: str,
) -> list[str]:
    checklist = DOMAIN_CHECKLISTS.get(domain.strip().lower())
    if not checklist:
        return []
    requires_text = "\n".join(
        [
            *_non_trivial_clauses(atoms, "requires"),
            _clause_lines(spec_text, _REQUIRES_LINE_RE),
        ]
    ).lower()
    ensures_text = "\n".join(
        [
            *_non_trivial_clauses(atoms, "ensures"),
            _clause_lines(spec_text, _ENSURES_LINE_RE),
        ]
    ).lower()
    full_text = "\n".join(
        [
            spec_text,
            *[atom.requires for atom in atoms],
            *[atom.ensures for atom in atoms],
        ]
    ).lower()
    formal_clauses_present = bool(requires_text.strip() or ensures_text.strip())
    normalized_domain = domain.strip().lower()
    warnings: list[str] = []
    for item in checklist:
        raw_keywords = item.get("keywords") or [item.get("keyword", "")]
        keywords = [str(keyword).lower() for keyword in raw_keywords if str(keyword)]
        if not keywords:
            continue
        clause = str(item.get("clause") or "any").lower()
        clause_label = ""
        if clause in {"requires", "ensures"}:
            haystack = (
                (requires_text if clause == "requires" else ensures_text)
                if formal_clauses_present
                else full_text
            )
            clause_label = clause
        else:
            haystack = full_text
        if any(keyword in haystack for keyword in keywords):
            continue
        description = str(item.get("description") or "")
        detail_parts = [part for part in (description,) if part]
        if clause_label:
            detail_parts.append(f"expected in {clause_label}")
        detail = f" ({'; '.join(detail_parts)})" if detail_parts else ""
        warnings.append(
            f"domain-completeness: {normalized_domain} spec lacks "
            f"{keywords[0]}{detail}"
        )
    return warnings


def check_forge_spec_domain_completeness(
    forge_task_spec: dict[str, object] | None,
    domain: str,
    *,
    spec_text: str = "",
) -> list[str]:
    """Domain completeness check for an extracted forge task spec (audit path).

    ``forge_task_spec`` is the dict produced by ``CodeToSpecExtractor``;
    ``spec_text`` is the natural-language spec it was extracted from.
    """
    if not isinstance(forge_task_spec, dict) or not domain.strip():
        return []
    from agent.cross_validation_payload import _atoms_from_payload

    payload = forge_task_spec
    if not isinstance(payload.get("atoms"), list) and "name" in payload:
        payload = {**payload, "atoms": [payload]}
    atoms = _atoms_from_payload(payload)
    return check_domain_completeness(spec_text, atoms, domain)


def check_nl_vacuity(atoms: list[MumeiContractAtom]) -> list[str]:
    warnings: list[str] = []
    for atom in atoms:
        ensures = atom.ensures.strip()
        if not ensures or ensures.lower() == "true":
            warnings.append(
                f"Vacuous NL atom `{atom.name}` has trivial ensures: "
                f"{ensures or '<empty>'}"
            )
    return warnings


def check_multi_spec_consistency(
    spec_texts: list[str],
    config: AgentConfig,
    *,
    use_llm: bool = True,
    domain_hint: str = "",
) -> list[CrossValidationIssue]:
    from agent.cross_validation import (
        _check_nl_result_pairs_for_conflicts,
        validate_nl_spec,
    )

    results = [
        validate_nl_spec(
            spec_text,
            config=config,
            use_llm=use_llm,
            run_mumei=False,
            domain_hint=domain_hint,
        )
        for spec_text in spec_texts
    ]
    return _check_nl_result_pairs_for_conflicts(results)
