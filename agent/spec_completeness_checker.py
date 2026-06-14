"""Domain completeness and NL-spec health checks."""
from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.config import AgentConfig
    from agent.cross_validation import CrossValidationIssue, MumeiContractAtom


DOMAIN_CHECKLISTS: dict[str, list[dict[str, str]]] = {
    "financial": [
        {"keyword": "balance conservation", "description": "残高保存則（送受信合計が不変）"},
        {"keyword": "non-negative", "description": "残高非負条件"},
        {"keyword": "amount > 0", "description": "金額正値条件"},
        {"keyword": "insufficient", "description": "残高不足エラー条件"},
    ],
    "security": [
        {"keyword": "auth", "description": "認証チェック"},
        {"keyword": "sanitize", "description": "入力サニタイズ"},
        {"keyword": "permission", "description": "権限チェック"},
    ],
    "crypto": [
        {"keyword": "hash", "description": "ハッシュ整合性"},
        {"keyword": "signature", "description": "署名検証"},
    ],
    "data_structure": [
        {"keyword": "bounds", "description": "境界チェック"},
        {"keyword": "non-null", "description": "null安全性"},
    ],
}


def check_domain_completeness(
    spec_text: str,
    atoms: list[MumeiContractAtom],
    domain: str,
) -> list[str]:
    checklist = DOMAIN_CHECKLISTS.get(domain.strip().lower())
    if not checklist:
        return []
    haystack = "\n".join([spec_text, *[atom.ensures for atom in atoms]]).lower()
    warnings: list[str] = []
    for item in checklist:
        keyword = item["keyword"]
        if keyword.lower() not in haystack:
            warnings.append(
                f"Missing {domain} required condition: {item['description']} "
                f"(keyword: {keyword})"
            )
    return warnings


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
        ContractParam,
        CrossValidationIssue,
        MumeiContractAtom,
        _check_atoms_with_z3,
        _dedupe_issues,
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
    conflicts: list[CrossValidationIssue] = []
    for left_index, left in enumerate(results):
        for right_index in range(left_index + 1, len(results)):
            right = results[right_index]
            combined_atoms = [*left.inferred_atoms, *right.inferred_atoms]
            if not combined_atoms:
                continue
            params = {
                param.name: param.type
                for atom in combined_atoms
                for param in atom.params
            }
            combined = MumeiContractAtom(
                name=f"nl_spec_{left_index + 1}_vs_{right_index + 1}",
                params=[
                    ContractParam(name=name, type=param_type)
                    for name, param_type in sorted(params.items())
                ],
                requires=_join_clauses(atom.requires for atom in combined_atoms),
                ensures=_join_clauses(atom.ensures for atom in combined_atoms),
            )
            _, pair_issues, _ = _check_atoms_with_z3([combined])
            for issue in pair_issues:
                conflicts.append(
                    CrossValidationIssue(
                        kind=issue.kind,
                        message=(
                            f"NL spec documents {left_index + 1} and {right_index + 1} "
                            f"are inconsistent: {issue.message}"
                        ),
                        evidence=issue.evidence,
                        location=f"spec[{left_index}],spec[{right_index}]",
                        severity=issue.severity,
                    )
                )
    return _dedupe_issues(conflicts)


def _join_clauses(clauses: Iterable[str]) -> str:
    parts = [
        str(clause).strip().rstrip(";")
        for clause in clauses
        if str(clause).strip() and str(clause).strip().lower() != "true"
    ]
    return " && ".join(parts) if parts else "true"
