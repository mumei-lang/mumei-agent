"""Contract tests for audit SARIF rendering and process exit classification."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from agent.audit import build_parser, main
from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.audit_sarif import audit_exit_code, sarif_document, sarif_json


def _file_result(**overrides) -> AuditResult:
    values = {
        "success": True,
        "source_file": "src/payment.py",
        "language": "python",
        "spec_extracted": True,
        "verification_status": "verified",
    }
    values.update(overrides)
    return AuditResult(**values)


def test_exit_code_is_zero_when_only_spec_diagnostics_exist() -> None:
    result = _file_result(
        spec_health_issues=["vacuous: withdraw"],
        cross_validation_gaps=["missing constraint"],
        verification_status="unverifiable",
    )

    assert audit_exit_code(result) == 0


def test_exit_code_is_one_for_code_findings() -> None:
    result = _file_result(
        success=False,
        verification_status="refuted",
        verification_violations=["balance can go negative"],
    )

    assert audit_exit_code(result) == 1


def test_exit_code_is_two_for_operational_or_extraction_errors() -> None:
    operational = _file_result(success=False, errors=["extractor failed"], spec_extracted=False)
    malformed = _file_result(
        success=False,
        spec_health_issues=["malformed-extraction: withdraw ensures: garbled comparison operators"],
    )

    assert audit_exit_code(operational) == 2
    assert audit_exit_code(malformed) == 2


def test_directory_exit_code_uses_worst_file_result() -> None:
    result = AuditDirectoryResult(
        success=False,
        source_dir="src",
        language="python",
        file_results=[
            _file_result(source_file="src/clean.py"),
            _file_result(
                source_file="src/refuted.py",
                success=False,
                verification_status="refuted",
                verification_violations=["refuted"],
            ),
        ],
    )

    assert audit_exit_code(result) == 1

    result.file_results.append(
        _file_result(source_file="src/error.py", success=False, errors=["timeout"])
    )
    assert audit_exit_code(result) == 2


def test_sarif_document_uses_stable_rules_locations_and_fingerprints() -> None:
    result = _file_result(
        success=False,
        verification_status="refuted",
        verification_violations=["balance can go negative"],
        spec_health_issues=["vacuous: withdraw"],
        cross_validation_gaps=["missing overflow constraint"],
        trusted_atoms=[{"atom": "withdraw", "line": 7}],
    )

    document = sarif_document(result)
    run = document["runs"][0]
    rules = {rule["id"]: rule for rule in run["tool"]["driver"]["rules"]}
    rows = run["results"]

    assert document["version"] == "2.1.0"
    assert set(rules) == {
        "mumei.audit/verification-violation",
        "mumei.audit/spec-health",
        "mumei.audit/cross-validation-gap",
        "mumei.audit/trusted-atom",
        "mumei.audit/audit-error",
    }
    assert [row["ruleId"] for row in rows] == [
        "mumei.audit/verification-violation",
        "mumei.audit/spec-health",
        "mumei.audit/cross-validation-gap",
        "mumei.audit/trusted-atom",
    ]
    assert rows[0]["level"] == "error"
    first_location = rows[0]["locations"][0]["physicalLocation"]
    assert first_location["artifactLocation"]["uri"] == "src/payment.py"
    assert "region" not in first_location
    assert rows[3]["locations"][0]["physicalLocation"]["region"]["startLine"] == 7
    assert all("mumeiAuditFinding/v1" in row["partialFingerprints"] for row in rows)
    assert document == json.loads(sarif_json(result))


def test_directory_sarif_uses_per_file_results_without_flattened_duplicates() -> None:
    directory = AuditDirectoryResult(
        success=False,
        source_dir="src",
        language="python",
        file_results=[
            _file_result(
                source_file="src/a.py",
                success=False,
                verification_violations=["a violation"],
            ),
            _file_result(
                source_file="src/b.py",
                success=False,
                verification_violations=["b violation"],
            ),
        ],
        verification_violations=["src/a.py: a violation", "src/b.py: b violation"],
        errors=["directory-level error"],
    )

    rows = sarif_document(directory)["runs"][0]["results"]

    assert [row["message"]["text"] for row in rows] == [
        "a violation",
        "b violation",
        "directory-level error",
    ]
    assert rows[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "src/a.py"
    assert rows[1]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "src/b.py"


def test_cli_writes_sarif_independently_of_primary_output(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    sarif_path = tmp_path / "reports" / "audit.sarif"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    result = _file_result(
        source_file=str(source),
        success=False,
        verification_status="refuted",
        verification_violations=["balance can go negative"],
    )

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = result
        args = build_parser().parse_args(
            [
                "--code-file", str(source),
                "--language", "python",
                "--format", "json",
                "--sarif-output", str(sarif_path),
            ]
        )
        returned = main(args)

    assert returned is result
    document = json.loads(sarif_path.read_text(encoding="utf-8"))
    rows = document["runs"][0]["results"]
    assert rows[0]["ruleId"] == "mumei.audit/verification-violation"
    assert rows[0]["message"]["text"] == "balance can go negative"


def test_cli_rejects_sarif_output_conflicts(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")

    hardlink = tmp_path / "payment-hardlink.py"
    try:
        os.link(source, hardlink)
        conflicts = (str(source), str(tmp_path / "report.json"), str(hardlink))
    except OSError:
        conflicts = (str(source), str(tmp_path / "report.json"))

    for conflict in conflicts:
        args = build_parser().parse_args(
            [
                "--code-file", str(source),
                "--language", "python",
                "--output", str(tmp_path / "report.json"),
                "--sarif-output", conflict,
            ]
        )
        try:
            main(args)
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - guards a silent overwrite regression
            raise AssertionError("conflicting SARIF output was accepted")


def test_python_module_dispatch_exits_with_audit_classification(monkeypatch) -> None:
    result = _file_result(
        success=False,
        verification_status="refuted",
        verification_violations=["balance can go negative"],
    )

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = result
        monkeypatch.setattr(
            sys,
            "argv",
            ["agent", "audit", "--code-file", "payment.py", "--language", "python"],
        )
        import agent.__main__ as agent_main

        try:
            agent_main.main()
        except SystemExit as exc:
            assert exc.code == 1
        else:  # pragma: no cover - guards a silent contract regression
            raise AssertionError("audit dispatch did not exit")


def test_python_module_dispatch_classifies_pre_result_operational_errors(monkeypatch, capsys) -> None:
    with patch("agent.audit.AuditPipeline", side_effect=FileNotFoundError("mumei")):
        monkeypatch.setattr(
            sys,
            "argv",
            ["agent", "audit", "--code-file", "payment.py", "--language", "python"],
        )
        import agent.__main__ as agent_main

        try:
            agent_main.main()
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - guards a silent contract regression
            raise AssertionError("audit dispatch did not exit")

    stderr = capsys.readouterr().err
    assert "operational error (FileNotFoundError)" in stderr
    assert "payment.py" not in stderr
