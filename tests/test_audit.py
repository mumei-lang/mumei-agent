"""Tests for integrated code audit pipeline."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

from agent import mcp_server
from agent.audit import (
    AUDIT_SCHEMA_KEYS,
    AuditDirectoryResult,
    AuditPipeline,
    AuditResult,
    _build_report,
    _format_result,
    build_parser,
    main,
)
from agent.audit_reporting import (
    _malformed_extraction_issue_strings,
    _spec_health_issue_strings,
)
from agent.audit_reporting import _verification_status_from_foreign_result
from agent.code_to_spec import CodeToSpecResult
from agent.config import AgentConfig
from agent.mm_migration_advisor import MigrationHint
from agent.strategies.cross_validation_strategy import CrossValidationReport
from agent.strategies.foreign_code_strategy import ForeignCodeVerifier
from agent.strategies.spec_health_strategy import SpecHealthReport
from agent.strategies.spec_health_strategy_helpers import ContradictionInfo

FIXTURES = Path(__file__).parent / "fixtures"


def _forge_spec() -> dict[str, object]:
    return {
        "task_id": "audit-payment",
        "target_file": "audit/payment.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "withdraw",
                "inputs": [
                    {"name": "balance", "type": "i64"},
                    {"name": "amount", "type": "i64"},
                ],
                "return_type": "i64",
                "requires": "balance >= amount && amount >= 0",
                "ensures": "result == balance - amount && result >= 0",
            }
        ],
    }


def _healthy_verify(source_path, report_dir=None, extra_args=None, **kwargs):
    if extra_args:
        for index, arg in enumerate(extra_args):
            if arg == "--output" and index + 1 < len(extra_args):
                Path(extra_args[index + 1]).write_text(
                    json.dumps(
                        {
                            "atoms": [
                                {
                                    "name": "withdraw",
                                    "spec_validation_result": {"is_satisfiable": True},
                                    "unused_hypotheses": {
                                        "unused_requires": [],
                                        "unused_invariants": [],
                                        "unused_effect_constraints": [],
                                    },
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
    return {"success": True, "report": {}, "stdout": "", "stderr": ""}


def _solidity_forge_spec() -> dict[str, object]:
    return {
        "task_id": "audit-add",
        "target_file": "audit/add.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "add",
                "inputs": [
                    {"name": "a", "type": "u64"},
                    {"name": "b", "type": "u64"},
                ],
                "return_type": "u64",
                "requires": "true",
                "ensures": "result == a + b",
            }
        ],
    }


def test_spec_health_lowering_failure_is_an_encoding_gap() -> None:
    report = SpecHealthReport(
        contradictions=[
            ContradictionInfo(
                atom="get_data_and_adjusted_bounds",
                details=(
                    "spec_lowering_failed: failed to lower ensures clause: "
                    "Verification Error: Unknown function: min"
                ),
            )
        ]
    )

    issues = _spec_health_issue_strings(report)

    assert issues == [
        "encoding-gap: get_data_and_adjusted_bounds: "
        "spec_lowering_failed: failed to lower ensures clause: "
        "Verification Error: Unknown function: min"
    ]
    assert not any(issue.startswith("contradiction:") for issue in issues)


def test_spec_health_unsupported_clause_errors_are_encoding_gaps() -> None:
    report = SpecHealthReport(
        contradictions=[
            ContradictionInfo(
                atom="get_data",
                details="spec_lowering_failed: forall() requires exactly 4 arguments",
            ),
            ContradictionInfo(
                atom="check_max_code_size",
                details="spec_lowering_failed: Expected bool for &&",
            ),
            ContradictionInfo(
                atom="opaque",
                details="Skipped unsupported Z3 clause: ensures clause 'opaque()'",
            ),
        ]
    )

    issues = _spec_health_issue_strings(report)

    assert len(issues) == 3
    assert all(issue.startswith("encoding-gap:") for issue in issues)


def test_spec_health_genuine_contradiction_remains_a_contradiction() -> None:
    report = SpecHealthReport(
        contradictions=[
            ContradictionInfo(
                atom="impossible_positive",
                details="requires_unsat: x > 0 && x < 0",
            )
        ]
    )

    assert _spec_health_issue_strings(report) == [
        "contradiction: impossible_positive: requires_unsat: x > 0 && x < 0"
    ]


def test_malformed_extraction_detector_flags_dogfood_clause_corruption() -> None:
    spec: dict[str, object] = {
        "atoms": [
            {
                "name": "calc_mem_size_64",
                "requires": "true",
                "ensures": (
                    "overflow == true <= >((offset + length) > "
                    "int(0 xFFFFFFFFFFFFFFFF))"
                ),
            }
        ]
    }

    issues = _malformed_extraction_issue_strings(spec)

    assert len(issues) == 2
    assert all(issue.startswith("malformed-extraction:") for issue in issues)
    assert any("split hexadecimal literal" in issue for issue in issues)
    assert any("garbled comparison operators" in issue for issue in issues)
    assert not any(issue.startswith("contradiction:") for issue in issues)


def test_malformed_extraction_detector_ignores_valid_clauses() -> None:
    spec: dict[str, object] = {
        "atoms": [
            {
                "name": "valid",
                "requires": "a <= b && p => q",
                "ensures": (
                    "x + y <= 2**64 - 1 && "
                    "result == int(0xFFFFFFFFFFFFFFFF)"
                ),
            }
        ]
    }

    assert _malformed_extraction_issue_strings(spec) == []


def test_audit_malformed_extraction_is_unverifiable(tmp_path: Path) -> None:
    source = tmp_path / "common.py"
    source.write_text("def calc(offset, length):\n    return 0\n", encoding="utf-8")
    malformed_spec = _forge_spec()
    malformed_atoms = cast(list[dict[str, object]], malformed_spec["atoms"])
    malformed_atoms[0]["ensures"] = (
        "overflow == true <= >((offset + length) > int(0 xFFFFFFFFFFFFFFFF))"
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="overflow-safe calculation",
        forge_task_spec=malformed_spec,
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {
        "success": True,
        "verification": {
            "success": True,
            "report": {"status": "satisfiable"},
        },
    }
    cross_validator = MagicMock()
    mumei = MagicMock()

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source, "python")

    assert result.success is False
    assert result.verification_status == "unverifiable"
    assert len(result.spec_health_issues) == 2
    assert all(
        issue.startswith("malformed-extraction:")
        for issue in result.spec_health_issues
    )
    assert "malformed-extraction:" in result.report
    assert not any(
        issue.startswith("contradiction:")
        for issue in result.spec_health_issues
    )
    mumei.verify.assert_not_called()
    cross_validator.validate_spec_vs_impl.assert_not_called()


def test_spec_health_non_boolean_lowering_failure_is_an_encoding_gap() -> None:
    report = SpecHealthReport(
        contradictions=[
            ContradictionInfo(
                atom="get_data",
                details=(
                    "spec_not_boolean: ensures clause must lower to boolean "
                    "(unsupported let..in expression)"
                ),
            )
        ]
    )

    issues = _spec_health_issue_strings(report)

    assert issues == [
        "encoding-gap: get_data: "
        "spec_not_boolean: ensures clause must lower to boolean "
        "(unsupported let..in expression)"
    ]
    assert not any(issue.startswith("contradiction:") for issue in issues)


def test_audit_pipeline_reports_solidity_uint256_overflow(tmp_path: Path) -> None:
    source = tmp_path / "Ledger.sol"
    source.write_text(
        "function add(uint256 a, uint256 b) public pure returns (uint256) {\n"
        "    return a + b;\n"
        "}\n",
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="add returns the sum of two uint256 values",
        forge_task_spec=_solidity_forge_spec(),
        detected_language="solidity",
    )
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=ForeignCodeVerifier(mumei_client=mumei),
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source, "solidity")

    assert result.language == "solidity"
    assert result.success is False
    assert any(
        "can overflow `a + b`" in violation for violation in result.verification_violations
    )
    assert any(
        "uint256 bounds contract" in violation
        for violation in result.verification_violations
    )
    assert {
        "function_name": "add",
        "counterexample": {"a": 2**256 - 1, "b": 1},
    } in result.counterexample_values


def test_audit_pipeline_reports_solidity_reentrancy(tmp_path: Path) -> None:
    source = tmp_path / "Vulnerable.sol"
    source.write_text(
        (FIXTURES / "sample_solidity_vulnerable.sol").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw and owner management for a vulnerable bank",
        forge_task_spec=_solidity_forge_spec(),
        detected_language="solidity",
    )
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=ForeignCodeVerifier(mumei_client=mumei),
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source, "solidity")

    assert result.language == "solidity"
    assert result.success is False
    assert any(
        "may be vulnerable to reentrancy" in violation
        for violation in result.verification_violations
    )
    assert any(
        "Checks-Effects-Interactions" in violation
        for violation in result.verification_violations
    )
    assert any(
        "no access-control guard" in violation
        for violation in result.verification_violations
    )
    assert all("withdrawAll" not in violation for violation in result.verification_violations)
    assert all("getBalance" not in violation for violation in result.verification_violations)
    assert {
        "function_name": "withdraw",
        "counterexample": {
            "reentrancy_trace": [
                "externalCall: msg.sender.call{value: amount}(\"\");",
                "stateWrite: balances[msg.sender]",
            ],
            "guard": "absent",
        },
    } in result.counterexample_values


def test_audit_pipeline_emits_guard_trace_certificate_and_upgrades_via_lean_bridge(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Guarded.sol"
    source.write_text(
        (FIXTURES / "sample_solidity_guarded.sol").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="guarded bank with nonReentrant and manual lock",
        forge_task_spec=_solidity_forge_spec(),
        detected_language="solidity",
    )
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.return_value = {"success": True, "report": {"status": "ok"}, "stdout": "{}", "stderr": ""}
    lean_cert = {
        "atoms": [
            {
                "name": "withdraw_guard_trace",
                "z3_check_result": "lean_verified",
                "status": "verified",
            },
            {
                "name": "manualWithdraw_guard_trace",
                "z3_check_result": "lean_verified",
                "status": "verified",
            },
        ]
    }

    with patch("agent.audit.run_lean_bridge_and_merge_proof_cert") as bridge_mock:
        bridge_mock.return_value = (
            {
                "atoms": [
                    {
                        "name": "withdraw_guard_trace",
                        "z3_check_result": "lean_verified",
                        "status": "verified",
                        "translator_ir": {
                            "guard_trace": {
                                "ops": ["lock", "externalCall", "unlock"],
                                "expected_outcome": "safe",
                            }
                        },
                    },
                    {
                        "name": "manualWithdraw_guard_trace",
                        "z3_check_result": "lean_verified",
                        "status": "verified",
                        "translator_ir": {
                            "guard_trace": {
                                "ops": ["lock", "externalCall", "unlock"],
                                "expected_outcome": "safe",
                            }
                        },
                    },
                ]
            },
            {
                "success": True,
                "lean_cert": lean_cert,
                "stdout": "",
                "stderr": "",
            },
        )
        result = AuditPipeline(
            AgentConfig(api_key="test", mumei_lean_repo="/tmp/mumei-lean"),
            code_to_spec_extractor=extractor,
            foreign_code_verifier=ForeignCodeVerifier(mumei_client=mumei),
            cross_validator=cross_validator,
            mumei_client=mumei,
        ).audit_file(source, "solidity", enable_lean_bridge=True)

    bridge_mock.assert_called_once()
    assert result.proof_certificate is not None
    atoms = {atom["name"]: atom for atom in result.proof_certificate["atoms"]}
    assert atoms["withdraw_guard_trace"]["z3_check_result"] == "lean_verified"
    assert atoms["withdraw_guard_trace"]["translator_ir"]["guard_trace"]["ops"] == [
        "lock",
        "externalCall",
        "unlock",
    ]
    assert atoms["manualWithdraw_guard_trace"]["translator_ir"]["guard_trace"]["expected_outcome"] == "safe"
    assert result.lean_bridge is not None
    assert result.lean_bridge["success"] is True


def test_audit_pipeline_reports_python_bug(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw requires balance >= amount and preserves non-negative balance",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {
        "success": False,
        "errors": ["balance can go negative (Z3 counterexample: amount=150, balance=100)"],
        "verification": {"success": False, "report": {"status": "failed", "failed": 1}},
    }
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        spec_stronger_than_impl=["withdraw"],
        details=[
            "spec requires balance >= amount, but code allows negative balance"
        ],
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source, "python")

    assert result.spec_extracted is True
    assert result.success is False
    assert result.spec_health_issues == []
    assert "balance can go negative" in result.verification_violations[0]
    assert any(
        "spec requires balance >= amount" in gap
        for gap in result.cross_validation_gaps
    )
    assert "verification_violations" in result.report
    assert "next_steps:" in result.report
    assert any(
        step["command"].startswith("mumei-agent migrate-suggest")
        for step in result.next_steps
    )
    assert any(
        step["command"]
        == "mumei-agent validate-spec-to-code --spec <spec> --code <file> --format human"
        for step in result.next_steps
    )


def test_audit_pipeline_marks_verification_status_refuted(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw requires balance >= amount",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {
        "success": False,
        "errors": [],
        "verification": {
            "success": False,
            "report": {
                "status": "failed",
                "failed": 1,
                "counterexample": {"balance": 100, "amount": 150},
            },
        },
    }
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source, "python")

    assert result.verification_status == "refuted"


def test_audit_verification_status_unverifiable_for_lowering_failure_without_counterexample() -> None:
    result = {
        "success": False,
        "verification": {
            "success": False,
            "report": {
                "status": "trusted",
                "failed": None,
            },
        },
    }

    status = _verification_status_from_foreign_result(
        result,
        counterexample_values=[],
        verification_violations=[
            "mumei verify failed",
            "mumei verify failed: status=trusted, failed=None",
        ],
        spec_health_issues=[
            "contradiction: calc_mem_size_64: spec_lowering_failed: failed to lower ensures clause"
        ],
    )

    assert status == "unverifiable"


def test_audit_verification_status_refuted_for_counterexample() -> None:
    result = {
        "success": False,
        "verification": {
            "success": False,
            "report": {
                "status": "trusted",
                "failed": None,
            },
        },
    }

    status = _verification_status_from_foreign_result(
        result,
        counterexample_values=[
            {"function_name": "calc_mem_size_64", "counterexample": {"offset": 1}}
        ],
        verification_violations=["mumei verify failed"],
        spec_health_issues=["spec_lowering_failed: failed to lower ensures clause"],
    )

    assert status == "refuted"


def test_audit_verification_status_preserves_skips_without_verification_failure() -> None:
    result = {
        "success": True,
        "verification": {
            "success": True,
            "report": {
                "status": "satisfiable_with_skips",
                "diagnostics": [
                    "Skipped unsupported Z3 clause: ensures clause 'opaque()'"
                ],
            },
        },
    }

    status = _verification_status_from_foreign_result(
        result,
        counterexample_values=[],
        verification_violations=[],
    )

    assert status == "unverifiable"


def test_audit_pipeline_marks_verification_status_unverifiable_for_skipped_clause(
    tmp_path: Path,
) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw requires balance >= amount",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {
        "success": False,
        "errors": ["mumei verify reported a skipped clause"],
        "verification": {
            "success": False,
            "report": {
                "status": "satisfiable_with_skips",
                "diagnostics": [
                    "Skipped unsupported Z3 clause: requires clause 'balance >= amount': Unknown function: is_hex_digit"
                ],
            },
        },
    }
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source, "python")

    assert result.verification_status == "unverifiable"


def test_audit_pipeline_marks_verification_status_verified_for_clean_run(
    tmp_path: Path,
) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw requires balance >= amount",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {
        "success": True,
        "errors": [],
        "verification": {
            "success": True,
            "report": {"status": "satisfiable"},
        },
    }
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source, "python")

    assert result.verification_status == "verified"


def test_audit_report_includes_counterexample_values(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw requires balance >= amount",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {
        "success": False,
        "errors": [],
        "specs": [{"function_name": "withdraw"}],
        "verification": {
            "success": False,
            "report": {
                "status": "failed",
                "failed": 1,
                "counterexample": {"balance": 100, "amount": 150},
            },
        },
    }
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source, "python")

    assert result.counterexample_values == [
        {
            "function_name": "withdraw",
            "counterexample": {"balance": 100, "amount": 150},
        }
    ]
    assert "Z3 Counter-example: balance=100, amount=150" in result.verification_violations
    assert "counterexample_values:" in result.report


def test_audit_report_includes_step_guidance() -> None:
    result = AuditResult(
        success=False,
        source_file="/tmp/payment.py",
        language="python",
        spec_extracted=True,
        verification_violations=["withdraw can return a negative balance"],
    )

    report = _build_report(result)

    assert "next_steps:" in report
    assert "priority: high" in report
    assert "mumei-agent migrate-suggest --code-file <file>" in report


def test_audit_pipeline_auto_migrate_adds_migration_hints(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw requires balance >= amount",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {
        "success": False,
        "errors": ["withdraw can return a negative balance"],
    }
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        spec_stronger_than_impl=["withdraw"],
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify
    hint = MigrationHint(
        function_name="withdraw",
        priority="high",
        reason="verification issue",
        skeleton=(
            "atom withdraw(balance: i64, amount: i64) -> i64 {\n"
            "    requires: balance >= amount;\n"
            "    ensures: result == balance - amount;\n"
            "}"
        ),
        next_step="save skeleton",
    )

    with patch("agent.mm_migration_advisor.suggest_migration_for_file") as suggest:
        suggest.return_value = [hint]
        result = AuditPipeline(
            AgentConfig(api_key="test"),
            code_to_spec_extractor=extractor,
            foreign_code_verifier=foreign_verifier,
            cross_validator=cross_validator,
            mumei_client=mumei,
        ).audit_file(source, "python", auto_migrate=True)

    assert result.migration_hints == [
        {
            "function_name": "withdraw",
            "priority": "high",
            "reason": "verification issue",
            "skeleton": hint.skeleton,
            "next_step": "save skeleton",
        }
    ]
    suggest.assert_called_once_with(
        str(source.resolve()),
        "python",
        {
            "issues": [
                {
                    "kind": "verification",
                    "severity": "error",
                    "message": "withdraw can return a negative balance",
                },
                {
                    "kind": "alignment",
                    "severity": "warning",
                    "message": "spec stronger than implementation: withdraw",
                },
            ]
        },
    )
    assert "migration_hints:" in result.report
    assert "function_name: withdraw" in result.report
    assert "priority: high" in result.report
    assert "ensures: result == balance - amount;" in result.report
    assert "}" not in result.report
    assert {
        "priority": "medium",
        "action": "heal で .mm スケルトンを自動修正",
        "command": "mumei-agent heal <mm_file>",
    } in result.next_steps


def test_audit_pipeline_auto_heal_records_healed_files(tmp_path: Path, capsys) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "healed"
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw requires balance >= amount",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {
        "success": False,
        "errors": ["withdraw can return a negative balance"],
    }
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        spec_stronger_than_impl=["withdraw"],
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify
    hint = MigrationHint(
        function_name="withdraw",
        priority="high",
        reason="verification issue",
        skeleton=(
            "atom withdraw(balance: i64, amount: i64) -> i64 {\n"
            "    requires: balance >= amount;\n"
            "    ensures: result == balance - amount;\n"
            "}"
        ),
        next_step="save skeleton",
    )

    with (
        patch("agent.mm_migration_advisor.suggest_migration_for_file") as suggest,
        patch("agent.self_healing.main") as heal_main,
    ):
        suggest.return_value = [hint]
        result = AuditPipeline(
            AgentConfig(api_key="test"),
            code_to_spec_extractor=extractor,
            foreign_code_verifier=foreign_verifier,
            cross_validator=cross_validator,
            mumei_client=mumei,
            heal_output_dir=str(output_dir),
        ).audit_file(source, "python", auto_migrate=True, auto_heal=True)

    healed_path = output_dir / "withdraw.mm"
    assert result.healed_files == [str(healed_path.resolve())]
    assert result.heal_errors == []
    assert healed_path.read_text(encoding="utf-8") == hint.skeleton + "\n"
    assert "healed_files:" in result.report
    stderr = capsys.readouterr().err
    assert "[Step 1/3] Extracting spec and verifying contracts..." in stderr
    assert (
        "[Step 2/3] Generating .mm migration skeletons for 1 functions with issues..."
        in stderr
    )
    assert "[Step 3/3] Running self-healing loop on generated skeletons..." in stderr
    heal_main.assert_called_once_with()


def test_audit_pipeline_auto_migrate_skips_without_violations(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw preserves balance",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.return_value = {"success": True, "report": {}}
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
        coverage_ratio=1.0,
    )
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    with patch("agent.mm_migration_advisor.suggest_migration_for_file") as suggest:
        result = AuditPipeline(
            AgentConfig(api_key="test"),
            code_to_spec_extractor=extractor,
            foreign_code_verifier=foreign_verifier,
            cross_validator=cross_validator,
            mumei_client=mumei,
        ).audit_file(source, "python", auto_migrate=True)

    assert result.success is True
    assert result.verification_violations == []
    assert result.cross_validation_gaps == []
    assert result.migration_hints == []
    assert result.next_steps[0]["priority"] == "info"
    assert "移行" in result.next_steps[0]["action"]
    assert result.next_steps[0]["command"] == ""
    suggest.assert_not_called()


def test_audit_pipeline_handles_spec_extraction_failure(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw(balance: int, amount: int) -> int:\n    return 0\n", encoding="utf-8")
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=False,
        natural_language_spec="",
        forge_task_spec=None,
        detected_language="python",
        errors=["LLM returned an empty natural language specification"],
    )
    foreign_verifier = MagicMock()
    cross_validator = MagicMock()

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=MagicMock(),
    ).audit_file(source, "python")

    assert result.success is False
    assert result.spec_extracted is False
    assert result.errors == ["LLM returned an empty natural language specification"]
    assert result.skipped_rate_limited is False
    foreign_verifier.verify.assert_not_called()
    cross_validator.validate_spec_vs_impl.assert_not_called()


def test_audit_pipeline_marks_rate_limited_extraction_failure(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw(x: int) -> int:\n    return x\n", encoding="utf-8")
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=False,
        natural_language_spec="",
        forge_task_spec=None,
        detected_language="python",
        errors=[
            "Error code: 429 - {'error': {'message': 'Rate limit reached for gpt-4o "
            "on tokens per min (TPM): Limit 30000. Please try again in 884ms.'}}"
        ],
    )

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=MagicMock(),
        cross_validator=MagicMock(),
        mumei_client=MagicMock(),
    ).audit_file(source, "python")

    assert result.success is False
    assert result.skipped_rate_limited is True


def test_audit_pipeline_handles_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "payment.py").write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    nested = source_dir / "nested"
    nested.mkdir()
    (nested / "transfer.rs").write_text(
        "pub fn transfer(balance: i64, amount: i64) -> i64 { balance - amount }\n",
        encoding="utf-8",
    )
    (source_dir / "covered.go").write_text(
        "package covered\nfunc balance(x int) int { return x }\n",
        encoding="utf-8",
    )

    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="withdraw/transfer preserve balances",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.side_effect = [
        {"success": False, "errors": ["withdraw can return a negative balance"]},
        {"success": True, "report": {}},
        {"success": True, "report": {}},
    ]
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.side_effect = [
        CrossValidationReport(spec_stronger_than_impl=["withdraw"], coverage_ratio=1.0),
        CrossValidationReport(coverage_ratio=1.0),
        CrossValidationReport(coverage_ratio=1.0),
    ]
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_file(source_dir)

    assert isinstance(result, AuditDirectoryResult)
    assert result.success is False
    assert result.total_files == 3
    assert result.files_with_issues == 1
    assert sorted(Path(file_result.source_file).name for file_result in result.file_results) == [
        "covered.go",
        "payment.py",
        "transfer.rs",
    ]
    assert foreign_verifier.verify.call_count == 3
    assert [step["priority"] for step in result.next_steps] == ["high", "high"]
    assert result.next_steps[0]["command"].startswith("mumei-agent migrate-suggest")
    assert (
        result.next_steps[1]["command"]
        == "mumei-agent validate-spec-to-code --spec <spec> --code <file> --format human"
    )

    # Directory audits must expose the same fixed keys at the top level as a
    # single-file audit (#284).
    from dataclasses import asdict

    payload = asdict(result)
    for key in AUDIT_SCHEMA_KEYS:
        assert key in payload, key
    # Aggregated lists flatten per-file findings and carry file attribution.
    aggregated_violations = result.verification_violations
    per_file_violations = sum(
        len(file_result.verification_violations) for file_result in result.file_results
    )
    assert len(aggregated_violations) == per_file_violations
    assert all(": " in violation for violation in aggregated_violations)


def test_audit_directory_summary_table(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    payment = source_dir / "payment.py"
    transfer = source_dir / "transfer.py"
    payment.write_text("def payment() -> int:\n    return 0\n", encoding="utf-8")
    transfer.write_text("def transfer() -> int:\n    return 0\n", encoding="utf-8")

    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True,
        natural_language_spec="payment/transfer preserve balances",
        forge_task_spec=_forge_spec(),
        detected_language="python",
    )
    foreign_verifier = MagicMock()
    foreign_verifier.verify.side_effect = [
        {"success": False, "errors": ["payment violation"]},
        {"success": True, "report": {}},
    ]
    cross_validator = MagicMock()
    cross_validator.validate_spec_vs_impl.side_effect = [
        CrossValidationReport(spec_stronger_than_impl=["payment"], coverage_ratio=1.0),
        CrossValidationReport(coverage_ratio=1.0),
    ]
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=foreign_verifier,
        cross_validator=cross_validator,
        mumei_client=mumei,
    ).audit_directory(source_dir, "python")

    assert "Audit directory:" in result.summary
    assert "payment.py: 1 violation, 1 gap" in result.summary
    assert "transfer.py: 0 violations, 0 gaps" in result.summary
    assert "Summary: 2 files, 1 file with issues" in result.summary
    assert "next_steps:" in result.summary
    assert "mumei-agent migrate-suggest --code-file <file>" in result.summary


def test_scan_and_fix_handles_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    result = AuditDirectoryResult(
        success=True,
        source_dir=str(source_dir),
        language="python",
        total_files=0,
        summary="Audit directory",
    )

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_directory.return_value = result
        payload = mcp_server.scan_and_fix(
            str(source_dir),
            "python",
            auto_heal=True,
            output_format="human",
        )

    assert payload["audit"]["success"] is True
    assert payload["next_steps"] == []
    assert "- Status: **Passed**" in payload["formatted_report"]
    assert f"- Source: `{source_dir}`" in payload["formatted_report"]
    pipeline_cls.return_value.audit_directory.assert_called_once_with(
        str(source_dir),
        "python",
        domain_hint="",
        auto_migrate=True,
        auto_heal=True,
    )
    pipeline_cls.return_value.audit_file.assert_not_called()


def test_scan_and_fix_shares_audit_contract_and_next_steps_review_gate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )
    next_steps = [
        {
            "priority": "high",
            "action": "migrate-suggest で.mm スケルトン生成",
            "command": (
                "mumei-agent migrate-suggest --code-file <file> "
                "--language <lang> --output generated/mm"
            ),
        }
    ]
    audit_result = AuditResult(
        success=False,
        source_file=str(source),
        language="python",
        spec_extracted=True,
        spec_health_issues=["requires balance >= amount and amount > balance"],
        verification_violations=["balance can go negative"],
        cross_validation_gaps=["spec requires a guard missing from code"],
        next_steps=next_steps,
        migration_hints=[{"function_name": "withdraw"}],
        healed_files=[str(tmp_path / "withdraw.mm")],
        heal_errors=["withdraw.mm: proof still failing"],
    )

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = audit_result
        payload = mcp_server.scan_and_fix(
            str(source),
            "python",
            auto_heal=True,
            output_format="human",
        )

    for key in AUDIT_SCHEMA_KEYS:
        assert key in payload
        assert payload[key] == getattr(audit_result, key)
        assert payload["audit"][key] == getattr(audit_result, key)
    assert payload["next_steps"] == next_steps
    report = payload["formatted_report"]
    assert "- ステータス: **要レビュー**" in report
    assert f"- コード: `{source}`" in report
    assert report.index("### 次の手順 (V1-E-1)") < report.index("### 検出事項")
    assert "human-review entrypoint" in payload["contract_terms"]["next_steps"]
    assert "recommendations" not in payload
    assert "actions" not in payload
    assert "review_actions" not in payload
    assert "human_review" not in payload
    assert "repair_hints" not in payload


def test_cli_audit_json_output(tmp_path: Path, capsys) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw(balance: int, amount: int) -> int:\n    return balance - amount\n", encoding="utf-8")
    result = AuditResult(
        success=False,
        source_file=str(source),
        language="python",
        spec_extracted=True,
        verification_violations=["balance can go negative"],
        report="audit report",
    )

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = result
        args = build_parser().parse_args(
            ["--code-file", str(source), "--language", "python", "--json"]
        )
        returned = main(args)

    payload = json.loads(capsys.readouterr().out)
    assert returned is result
    assert payload["success"] is False
    assert payload["verification_violations"] == ["balance can go negative"]
    assert "next_steps" in payload
    assert payload["next_steps"] == []
    pipeline_cls.return_value.audit_file.assert_called_once_with(
        str(source),
        "python",
        domain_hint="",
        auto_migrate=False,
        auto_heal=False,
        enable_lean_bridge=False,
    )


def test_cli_audit_markdown_output(tmp_path: Path, capsys) -> None:
    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n    return balance - amount\n",
        encoding="utf-8",
    )
    result = AuditResult(
        success=False,
        source_file=str(source),
        language="python",
        spec_extracted=True,
        verification_violations=["balance can go negative"],
        next_steps=[
            {
                "priority": "high",
                "action": "migrate-suggest で .mm スケルトンを生成",
                "command": (
                    "mumei-agent migrate-suggest --code-file <file> "
                    "--language <lang> --output generated/mm"
                ),
            }
        ],
        report="audit report",
    )

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = result
        args = build_parser().parse_args(
            ["--code-file", str(source), "--language", "python", "--format", "markdown"]
        )
        returned = main(args)

    output = capsys.readouterr().out
    assert returned is result
    assert "## No-.mm" in output
    assert str(source) in output
    assert "verification_violations" in output
    assert "balance can go negative" in output
    assert "V1-E-1" in output
    assert "```bash" in output
    assert "mumei-agent migrate-suggest --code-file <file>" in output


def test_audit_report_generates_spec_health_next_step() -> None:
    result = AuditResult(
        success=False,
        source_file="/tmp/payment.py",
        language="python",
        spec_extracted=True,
        spec_health_issues=["requires/ensures are contradictory"],
    )

    report = _build_report(result)

    assert "validate-spec で仕様の矛盾を修正" in report
    assert "mumei-agent validate-spec --input <spec>" in report


def test_mcp_audit_code_returns_dict() -> None:
    result = AuditResult(
        success=True,
        source_file="<inline:python>",
        language="python",
        spec_extracted=True,
        report="Audit passed",
    )
    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_source.return_value = result
        payload = mcp_server.audit_code(
            "def add(a: int, b: int) -> int:\n    return a + b\n",
            "python",
        )

    assert payload["success"] is True
    assert payload["source_file"] == "<inline:python>"
    assert payload["next_steps"] == []
    pipeline_cls.return_value.audit_source.assert_called_once()


def test_audit_result_asdict_includes_next_steps() -> None:
    result = AuditResult(
        success=False,
        source_file="/tmp/payment.py",
        language="python",
        spec_extracted=True,
        next_steps=[
            {
                "priority": "high",
                "action": "migrate-suggest で .mm スケルトンを生成",
                "command": "mumei-agent migrate-suggest --code-file <file>",
            }
        ],
    )

    payload = asdict(result)

    assert payload["next_steps"] == [
        {
            "priority": "high",
            "action": "migrate-suggest で .mm スケルトンを生成",
            "command": "mumei-agent migrate-suggest --code-file <file>",
        }
    ]


def test_cli_json_contract_keeps_scan_and_fix_schema_keys() -> None:
    result = AuditResult(
        success=False,
        source_file="payment.py",
        language="python",
        spec_extracted=True,
        spec_health_issues=["requires and ensures conflict"],
        verification_violations=["balance can go negative"],
        cross_validation_gaps=["spec/code mismatch"],
        migration_hints=[],
        healed_files=[],
        heal_errors=[],
    )
    result.next_steps = [
        {
            "priority": "high",
            "action": "migrate-suggest で.mm skeleton 生",
            "command": "mumei-agent migrate-suggest --code-file <file>",
        }
    ]

    payload = json.loads(_format_result(result, "json"))

    assert [key for key in AUDIT_SCHEMA_KEYS if key in payload] == AUDIT_SCHEMA_KEYS
    assert payload["next_steps"] == result.next_steps
    assert "recommendations" not in payload
    assert "repair_hints" not in payload


def test_audit_pipeline_reports_multilanguage_no_mm_violations(
    tmp_path: Path,
) -> None:
    fixtures = {
        "rust": (
            "calc.rs",
            (
                "pub fn add(a: i64, b: i64) -> i64 { a + b }\n"
                "pub fn nth(values: Vec<i64>, idx: i64) -> i64 { values[idx] }\n"
            ),
            ("can overflow", "bounds contract"),
            {"a", "b"},
        ),
        "typescript": (
            "names.ts",
            "export function len(name?: string): number { return name!.length; }\n",
            ("non-null contract",),
            {"name_is_null"},
        ),
        "go": (
            "lists.go",
            "package lists\nfunc nth(values []int, idx int) int { return values[idx] }\n",
            ("bounds contract",),
            {"idx", "len_values"},
        ),
    }
    forbidden_aliases = {
        "recommendations",
        "actions",
        "audit_issues",
        "verification_gaps",
        "repair_hints",
        "review_actions",
        "human_review",
    }

    for (
        language,
        (
            filename,
            source_text,
            expected_violations,
            expected_counterexample_keys,
        ),
    ) in fixtures.items():
        source = tmp_path / filename
        source.write_text(source_text, encoding="utf-8")
        mumei = MagicMock()
        mumei.verify.side_effect = _healthy_verify

        result = AuditPipeline(
            AgentConfig(api_key=""),
            foreign_code_verifier=ForeignCodeVerifier(mumei_client=mumei),
            mumei_client=mumei,
        ).audit_file(source, language)
        payload = asdict(result)

        assert result.spec_extracted is True
        assert result.success is False
        assert result.language == language
        assert [key for key in AUDIT_SCHEMA_KEYS if key in payload] == AUDIT_SCHEMA_KEYS
        assert forbidden_aliases.isdisjoint(payload)
        assert result.next_steps
        assert all(
            "Z3 counterexample" in issue
            or issue.startswith("Z3 Counter-example")
            for issue in result.verification_violations
        )
        for expected_violation in expected_violations:
            assert any(expected_violation in issue for issue in result.verification_violations)
        assert result.counterexample_values
        counterexample = result.counterexample_values[0]["counterexample"]
        assert expected_counterexample_keys.issubset(counterexample)
        assert set(result.next_steps[0]) == {"priority", "action", "command"}
        assert result.next_steps[0]["command"].startswith("mumei-agent migrate-suggest")


def test_audit_pipeline_reports_go_representative_violations(tmp_path: Path) -> None:
    fixtures = [
        (
            "lists.go",
            "package lists\nfunc nth(values []int, idx int) int { return values[idx] }\n",
            "bounds contract",
        ),
        (
            "users.go",
            "package users\nfunc age(user *User) int { return user.Age }\n",
            "non-nil contract",
        ),
        (
            "calc.go",
            "package calc\nfunc add(a int, b int) int { return a + b }\n",
            "can overflow",
        ),
    ]
    forbidden_aliases = {"recommendations", "repair_hints", "review_actions"}

    for filename, source_text, expected_violation in fixtures:
        source = tmp_path / filename
        source.write_text(source_text, encoding="utf-8")
        mumei = MagicMock()
        mumei.verify.side_effect = _healthy_verify

        result = AuditPipeline(
            AgentConfig(api_key=""),
            foreign_code_verifier=ForeignCodeVerifier(mumei_client=mumei),
            mumei_client=mumei,
        ).audit_file(source, "go")
        payload = asdict(result)

        assert result.spec_extracted is True
        assert result.success is False
        assert result.language == "go"
        assert [key for key in AUDIT_SCHEMA_KEYS if key in payload] == AUDIT_SCHEMA_KEYS
        assert forbidden_aliases.isdisjoint(payload)
        assert result.next_steps
        assert any(expected_violation in issue for issue in result.verification_violations)
        assert result.counterexample_values


def test_foreign_go_verifier_does_not_treat_package_selector_as_nil() -> None:
    code = 'package demo\nimport "math"\nfunc abs(x int) int { return math.Abs(x) }\n'
    mumei = MagicMock()
    mumei.verify.side_effect = _healthy_verify

    result = ForeignCodeVerifier(mumei_client=mumei).verify(code, "go")

    assert result["success"] is True
    assert result["errors"] == []
    assert all("math" not in message for message in result["errors"])
