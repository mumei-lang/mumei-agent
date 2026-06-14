"""Domain completeness and NL-spec health checks."""
from __future__ import annotations

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
