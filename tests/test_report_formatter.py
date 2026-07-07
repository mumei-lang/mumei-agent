"""Regression tests for no-.mm audit report vocabulary."""
from __future__ import annotations

import json
from dataclasses import asdict

from agent.audit import (
    AUDIT_CONTRACT_TERMS,
    AUDIT_SCHEMA_KEYS,
    AuditResult,
    _build_report,
    _format_result,
)
from agent.report_formatter import format_result_report


def test_audit_text_report_keeps_fixed_no_mm_keys_when_empty() -> None:
    result = AuditResult(
        success=True,
        source_file="payment.py",
        language="python",
        spec_extracted=True,
    )

    report = _build_report(result)

    for key in AUDIT_SCHEMA_KEYS:
        if key == "verification_status":
            assert "Verification status:" in report
        else:
            assert f"{key}:" in report
    assert "recommendations:" not in report
    assert "repair_hints:" not in report


def test_audit_json_report_uses_next_steps_without_aliases() -> None:
    result = AuditResult(
        success=False,
        source_file="payment.py",
        language="python",
        spec_extracted=True,
        verification_violations=["balance can go negative"],
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

    assert list(k for k in AUDIT_SCHEMA_KEYS if k in payload) == AUDIT_SCHEMA_KEYS
    assert payload["next_steps"] == result.next_steps
    assert "recommendations" not in payload
    assert "actions" not in payload
    assert "repair_hints" not in payload


def test_contract_terms_cover_schema_keys() -> None:
    result = AuditResult(
        success=True,
        source_file="payment.py",
        language="python",
        spec_extracted=True,
    )
    payload = asdict(result)

    assert set(AUDIT_SCHEMA_KEYS).issubset(payload)
    assert set(AUDIT_SCHEMA_KEYS).issubset(AUDIT_CONTRACT_TERMS)
    assert AUDIT_CONTRACT_TERMS["next_steps"].startswith("human-review entrypoint")


def test_scan_and_fix_report_keeps_role_split_and_next_steps_contract() -> None:
    payload = {
        "audit": {
            "success": False,
            "source_file": "payment.py",
            "language": "python",
            "spec_health_issues": [],
            "verification_violations": ["balance can go negative"],
            "cross_validation_gaps": [],
            "next_steps": [
                {
                    "priority": "high",
                    "action": "Run migrate-suggest before trusting generated .mm.",
                    "command": "mumei-agent migrate-suggest --code-file payment.py",
                }
            ],
            "migration_hints": [],
            "healed_files": [],
            "heal_errors": [],
        },
        "next_steps": [
            {
                "priority": "high",
                "action": "Run migrate-suggest before trusting generated .mm.",
                "command": "mumei-agent migrate-suggest --code-file payment.py",
            }
        ],
        "spec_alignment": {
            "success": False,
            "cross_validation_gaps": ["Spec postcondition is not implemented."],
            "next_steps": [
                {
                    "priority": "medium",
                    "action": "Review spec-to-code gaps.",
                    "command": "mumei-agent validate-spec-to-code --format human",
                }
            ],
        },
        "conformance_verification": {
            "success": False,
            "unimplemented_conditions": [
                {
                    "condition": "result == balance_after",
                    "evidence": "missing postcondition",
                    "implementation_symbol": "transfer",
                    "status": "missing",
                }
            ],
            "hidden_specifications": [],
            "verification_violations": ["result differs from required balance"],
            "cross_validation_gaps": ["result differs from required balance"],
            "next_steps": [
                {
                    "priority": "high",
                    "action": "Review conformance traceability before merge.",
                    "command": "mumei-agent verify-conformance --format human",
                }
            ],
        },
        "audit_schema": AUDIT_SCHEMA_KEYS,
        "contract_terms": AUDIT_CONTRACT_TERMS,
    }

    report = format_result_report(payload, "human", lang="en")

    assert "### scan_and_fix role split" in report
    assert "`audit`" in report
    assert "`spec_alignment`" in report
    assert "`conformance_verification`" in report
    assert report.index("### next_steps (V1-E-1)") < report.index(
        "### Human review entrypoints"
    )
    assert "mumei-agent migrate-suggest --code-file payment.py" in report
    assert "mumei-agent validate-spec-to-code --format human" in report
    assert "mumei-agent verify-conformance --format human" in report
    assert "`recommendations`" not in report
    assert "`review_actions`" not in report
    assert "`human_review`" not in report
