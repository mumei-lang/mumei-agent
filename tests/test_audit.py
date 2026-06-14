"""Tests for integrated code audit pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import mcp_server
from agent.audit import AuditPipeline, AuditResult, build_parser, main
from agent.code_to_spec import CodeToSpecResult
from agent.config import AgentConfig
from agent.strategies.cross_validation_strategy import CrossValidationReport


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
    foreign_verifier.verify.assert_not_called()
    cross_validator.validate_spec_vs_impl.assert_not_called()


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
    pipeline_cls.return_value.audit_file.assert_called_once_with(
        str(source),
        "python",
        domain_hint="",
    )


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
    pipeline_cls.return_value.audit_source.assert_called_once()
