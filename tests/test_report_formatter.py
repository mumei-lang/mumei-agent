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
from agent.prompts.report_formatter import format_actionable_fix_hint
from agent.report_formatter import format_result_report


def test_actionable_fix_hint_formats_labeled_failed_clause_with_escaped_quotes() -> None:
    label = 'result "must grow"'
    clause = "result > x"

    hint = format_actionable_fix_hint(
        {
            "failure_type": "postcondition_violated",
            "counterexample": {"x": 4},
            "failed_clause": clause,
            "failed_clause_label": label,
        }
    )

    assert (
        'Violated ensures clause "result \\"must grow\\"": result > x'
        in hint
    )


def test_actionable_fix_hint_formats_unlabeled_failed_clause() -> None:
    hint = format_actionable_fix_hint(
        {
            "failure_type": "postcondition_violated",
            "failed_clause": "result >= 0",
        }
    )

    assert "Violated ensures clause: result >= 0" in hint


def test_actionable_fix_hint_explains_ensures_outcomes() -> None:
    cases = [
        (
            "always_false",
            "This clause is false for every input that satisfies requires — "
            "the specification or the body is likely wrong.",
        ),
        (
            "fails_on_some_inputs",
            "This clause holds for some inputs but not all — look for a "
            "missing case in the body or a missing requires.",
        ),
    ]
    for outcome, expected_hint in cases:
        hint = format_actionable_fix_hint(
            {
                "failure_type": "postcondition_violated",
                "failed_clause": "result > x",
                "ensures_outcomes": [
                    None,
                    {"clause": "result > x", "outcome": outcome},
                ],
            }
        )
        assert expected_hint in hint


def test_actionable_fix_hint_ignores_malformed_optional_clause_fields() -> None:
    report = {
        "failure_type": "postcondition_violated",
        "counterexample": {"x": 1},
        "failed_clause": 42,
        "failed_clause_label": ["not", "a", "string"],
        "ensures_outcomes": [
            None,
            {"clause": {}, "outcome": "always_false"},
            "not a dictionary",
        ],
    }
    expected = (
        "The `ensures` clause is not satisfied for inputs: x=1. "
        "Fix the body to satisfy `ensures`, or adjust `ensures` to match actual behaviour."
    )

    assert format_actionable_fix_hint(report) == expected


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
