from __future__ import annotations

from pathlib import Path

from agent.config import AgentConfig
from agent.cross_validation import (
    MumeiContractAtom,
    build_validate_spec_parser,
    main_validate_spec,
    validate_nl_spec,
    validate_nl_spec_multi,
)
from agent.spec_completeness_checker import (
    _keyword_matches,
    check_domain_completeness,
    check_forge_spec_domain_completeness,
    check_nl_vacuity,
)


def test_financial_domain_missing_balance_conservation() -> None:
    result = validate_nl_spec(
        "requires: amount > 0;\nensures: result >= 0;",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
        domain_hint="financial",
    )

    assert any("balance conservation" in warning for warning in result.completeness_warnings)
    assert any(
        warning.startswith("domain-completeness: financial")
        for warning in result.completeness_warnings
    )


def test_domain_completeness_scopes_keywords_to_contract_clause() -> None:
    atoms = [
        MumeiContractAtom(
            name="withdraw",
            requires="amount > 0 && amount >= 0 && balance >= amount",
            ensures="result == balance - amount",
        )
    ]

    warnings = check_domain_completeness("", atoms, "financial")

    assert all(
        warning.startswith("domain-completeness: financial") for warning in warnings
    )
    assert any("balance conservation" in warning for warning in warnings)
    assert any("expected in ensures" in warning for warning in warnings)
    # requires-scoped items are covered by the requires clause.
    assert not any("amount > 0" in warning for warning in warnings)
    assert not any("non-negative" in warning for warning in warnings)
    assert not any("insufficient" in warning for warning in warnings)


def test_domain_completeness_falls_back_to_prose_without_formal_clauses() -> None:
    warnings = check_domain_completeness(
        "Transfers keep balance conservation: total funds are unchanged.",
        [],
        "financial",
    )

    assert not any("balance conservation" in warning for warning in warnings)


def test_domain_completeness_unknown_domain_is_quiet() -> None:
    assert check_domain_completeness("anything", [], "unknown-domain") == []


def test_keyword_matching_uses_word_boundaries() -> None:
    # Stems still match their inflections.
    assert _keyword_matches("sanitize", "sanitizes all inputs")
    assert _keyword_matches("limit", "limit is enforced")
    # ...but not unrelated words containing them.
    assert not _keyword_matches("limit", "delimited scope")
    assert not _keyword_matches("audit", "auditory output")
    # Whole-word keywords reject embedded occurrences entirely.
    assert not _keyword_matches("nil", "vanilla values")
    assert not _keyword_matches("none", "nonempty list")
    assert _keyword_matches("nil", "x != nil")
    # Symbol-leading keywords keep substring semantics on the left.
    assert _keyword_matches(">= 0", "amount >= 0")
    assert _keyword_matches(">=0", "amount>=0")


def test_domain_completeness_expanded_domains() -> None:
    for domain in ("compliance", "regtech", "iot", "web", "math"):
        warnings = check_domain_completeness("add returns the sum", [], domain)
        assert warnings, domain
        assert all(
            warning.startswith(f"domain-completeness: {domain}")
            for warning in warnings
        )


def test_domain_completeness_web_domain_covered() -> None:
    warnings = check_domain_completeness(
        "All inputs are sanitized and validated; requests require an "
        "authenticated session token; rate limits apply to every endpoint.",
        [],
        "web",
    )
    assert warnings == []


def test_forge_spec_domain_completeness_reads_forge_atoms() -> None:
    forge_task_spec = {
        "task_id": "audit-payment",
        "atoms": [
            {
                "name": "withdraw",
                "inputs": [{"name": "balance", "type": "i64"}],
                "return_type": "i64",
                "requires": "amount > 0",
                "ensures": "result == balance - amount",
            }
        ],
    }

    warnings = check_forge_spec_domain_completeness(forge_task_spec, "financial")

    assert warnings
    assert all(
        warning.startswith("domain-completeness: financial") for warning in warnings
    )
    assert any("balance conservation" in warning for warning in warnings)
    assert check_forge_spec_domain_completeness(forge_task_spec, "") == []
    assert check_forge_spec_domain_completeness(None, "financial") == []


def test_validate_spec_accepts_domain_hint_alias(tmp_path: Path) -> None:
    spec = tmp_path / "spec.txt"
    spec.write_text("requires: amount > 0;\nensures: result >= 0;", encoding="utf-8")
    args = build_validate_spec_parser().parse_args(
        [
            "--input",
            str(spec),
            "--domain-hint",
            "financial",
            "--no-llm",
            "--no-mumei",
        ]
    )

    result = main_validate_spec(args)

    assert result.success is True
    assert any(
        warning.startswith("domain-completeness: financial")
        for warning in result.completeness_warnings
    )


def test_vacuity_check_detects_trivial_ensures() -> None:
    warnings = check_nl_vacuity([MumeiContractAtom(name="noop", ensures="true")])

    assert warnings
    assert "noop" in warnings[0]


def test_multi_spec_conflict_detection() -> None:
    result = validate_nl_spec_multi(
        [
            "requires: true;\nensures: result > 0;",
            "requires: true;\nensures: result < 0;",
        ],
        config=AgentConfig(api_key=""),
        use_llm=False,
    )

    conflicts = result["cross_spec_conflicts"]
    assert conflicts
    assert "documents 1 and 2" in conflicts[0]["message"]


def test_validate_spec_format_human(tmp_path: Path, capsys) -> None:
    spec = tmp_path / "spec.txt"
    spec.write_text("requires: x >= 0;\nensures: result >= x;", encoding="utf-8")
    args = build_validate_spec_parser().parse_args(
        [
            "--input",
            str(spec),
            "--format",
            "human",
            "--no-llm",
            "--no-mumei",
        ]
    )

    result = main_validate_spec(args)
    captured = capsys.readouterr()

    assert result.success is True
    assert "Natural-Language Spec Validation Report" in captured.out
