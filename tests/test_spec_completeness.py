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
from agent.spec_completeness_checker import check_nl_vacuity


def test_financial_domain_missing_balance_conservation() -> None:
    result = validate_nl_spec(
        "requires: amount > 0;\nensures: result >= 0;",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
        domain_hint="financial",
    )

    assert any("balance conservation" in warning for warning in result.completeness_warnings)


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
