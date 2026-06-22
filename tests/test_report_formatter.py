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


def test_audit_text_report_keeps_fixed_no_mm_keys_when_empty() -> None:
    result = AuditResult(
        success=True,
        source_file="payment.py",
        language="python",
        spec_extracted=True,
    )

    report = _build_report(result)

    for key in AUDIT_SCHEMA_KEYS:
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
    assert AUDIT_CONTRACT_TERMS["next_steps"].startswith("ranked commands")
