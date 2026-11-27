from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.audit import build_parser, main
from agent.audit_models import AuditResult
from agent.migration_execution import SCHEMA, build_migration_execution


class FakeVerifyClient:
    def __init__(self, *, success: bool = True, write_proof: bool = True) -> None:
        self.success = success
        self.write_proof = write_proof
        self.calls = []

    def verify(self, source_path, report_dir=None, extra_args=None, spec_code_mapping=None, collect_decidable_metrics=False):
        self.calls.append({"source_path": source_path, "report_dir": report_dir, "extra_args": extra_args})
        if self.write_proof and "--output" in (extra_args or []):
            Path(extra_args[extra_args.index("--output") + 1]).write_text('{"proof":"fake"}\n', encoding="utf-8")
        if report_dir:
            (Path(report_dir) / "report.sarif").write_text('{"version":"2.1.0","runs":[]}\n', encoding="utf-8")
        return {
            "success": self.success,
            "report": {"status": "verified" if self.success else "refuted", "message": "fake verifier"},
            "stdout": "{}",
            "stderr": "",
        }


def _result(source: Path, hints: list[dict], **overrides) -> AuditResult:
    values = {
        "success": False,
        "source_file": str(source),
        "language": "python",
        "spec_extracted": True,
        "verification_status": "unverifiable",
        "migration_hints": hints,
        "finding_counts": {"code": 1, "spec": 0, "errors": 0},
    }
    values.update(overrides)
    return AuditResult(**values)


def _hint(name: str, skeleton: str | None = None) -> dict:
    return {
        "function_name": name,
        "priority": "high",
        "reason": f"{name} violates the extracted contract",
        "skeleton": skeleton
        if skeleton is not None
        else f"atom {name}(x: i64) -> i64 {{\n    requires: x >= 0;\n    ensures: result >= 0;\n    body: {{\n        x\n    }}\n}}",
        "next_step": "review generated migration",
    }


def test_migration_execution_records_acceptance_evidence_and_boundary(tmp_path: Path) -> None:
    source = tmp_path / "ledger.py"
    source.write_text("def divide(total: int, count: int) -> int:\n    return total // count\n", encoding="utf-8")
    result = _result(
        source,
        [_hint("divide")],
        native_replays=[{"function": "divide", "input": {"total": 1, "count": 0}, "verdict": "violates", "reason": "division by zero"}],
    )
    output = tmp_path / "execution.json"
    client = FakeVerifyClient()

    report = build_migration_execution(result, output_path=output, mumei_client=client)

    assert report["schema"] == SCHEMA
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == SCHEMA
    candidate = report["candidates"][0]
    assert candidate["execution_state"] == "ready_for_human_review"
    assert candidate["review_required"] is True
    assert candidate["source_provenance"]["sha256"]
    assert candidate["generated_mm"]["sha256"]
    assert candidate["extracted_contract"]["requires"] == ["x >= 0"]
    assert candidate["extracted_contract"]["ensures"] == ["result >= 0"]
    verification = candidate["verification"]
    assert verification["status"] == "verified"
    assert verification["proof_certificate"]["written"] is True
    assert verification["proof_certificate"]["sha256"]
    assert verification["sarif"]["written"] is True
    assert verification["sarif"]["sha256"]
    assert client.calls[0]["source_path"].endswith(".mm")
    assert candidate["behavioral_evidence"]["status"] == "available"
    assert candidate["behavioral_evidence"]["entries"][0]["verdict"] == "violates"
    boundary = "\n".join(report["evidence_boundary"])
    assert "not proof that host-language code implements the same behavior" in boundary
    assert "diagnostic evidence only" in candidate["behavioral_evidence"]["semantics"]
    assert report["summary"]["ready_for_human_review"] == 1


def test_migration_execution_keeps_weak_contracts_and_missing_proof_as_blockers(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    weak = "atom withdraw() -> i64 {\n    requires: true;\n    ensures: true;\n    body: { 0 }\n}"
    report = build_migration_execution(
        _result(source, [_hint("withdraw", weak)]),
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(write_proof=False),
    )

    candidate = report["candidates"][0]
    assert candidate["verification"]["status"] == "verified"
    assert candidate["execution_state"] == "blocked"
    assert "generated skeleton has weak true/true contracts" in candidate["evidence_blockers"]
    assert "proof certificate was not written" in candidate["evidence_blockers"]
    assert candidate["operational_errors"] == []


def test_migration_execution_distinguishes_operational_verifier_failure(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")

    class BrokenClient:
        def verify(self, *args, **kwargs):
            raise RuntimeError("verifier transport failed")

    report = build_migration_execution(
        _result(source, [_hint("withdraw")]),
        output_path=tmp_path / "execution.json",
        mumei_client=BrokenClient(),
    )

    candidate = report["candidates"][0]
    assert candidate["execution_state"] == "operational_error"
    assert candidate["verification"]["status"] == "operational_error"
    assert candidate["operational_errors"] == ["RuntimeError"]
    assert not any("verification status" in str(item) for item in candidate["evidence_blockers"])


def test_migration_execution_explicit_selection_and_healed_content(tmp_path: Path) -> None:
    source = tmp_path / "ledger.py"
    source.write_text("def divide():\n    pass\n\ndef other():\n    pass\n", encoding="utf-8")
    healed = tmp_path / "divide.mm"
    healed_text = "atom divide(x: i64) -> i64 {\n    requires: x > 0;\n    ensures: result >= 0;\n    body: { x }\n}"
    healed.write_text(healed_text + "\n", encoding="utf-8")
    result = _result(source, [_hint("divide"), _hint("other")], healed_files=[str(healed)])

    report = build_migration_execution(
        result,
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
        selected_functions=["divide", "missing"],
    )

    assert [item["function_name"] for item in report["candidates"]] == ["divide"]
    assert report["selection"]["missing_requested_functions"] == ["missing"]
    candidate = report["candidates"][0]
    assert candidate["generated_mm"]["origin"] == "healed_file"
    assert candidate["generated_mm"]["healed_source_path"] == str(healed)
    written = Path(candidate["generated_mm"]["path"]).read_text(encoding="utf-8")
    assert written == healed_text + "\n"
    assert candidate["heal"]["attempted"] is True
    assert len(result.migration_hints) == 2


def test_cli_requires_auto_migrate_for_migration_execution(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--code-file", str(source),
            "--language", "python",
            "--migration-execution-output", str(tmp_path / "execution.json"),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_cli_execution_output_enables_existing_heal_flow_and_adds_next_step(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    output = tmp_path / "execution.json"
    result = _result(source, [_hint("withdraw")])
    execution_report = {"summary": {"ready_for_human_review": 0, "blocked": 1, "operational_error": 0}}

    with patch("agent.audit.AuditPipeline") as pipeline_cls, patch("agent.audit.build_migration_execution", return_value=execution_report) as build:
        pipeline_cls.return_value.audit_file.return_value = result
        args = build_parser().parse_args(
            [
                "--code-file", str(source),
                "--language", "python",
                "--format", "json",
                "--auto-migrate",
                "--migration-function", "withdraw",
                "--migration-execution-output", str(output),
            ]
        )
        returned = main(args)

    assert returned is result
    assert pipeline_cls.return_value.audit_file.call_args.kwargs["auto_heal"] is True
    build.assert_called_once()
    assert build.call_args.kwargs["output_path"] == output
    assert build.call_args.kwargs["selected_functions"] == ["withdraw"]
    assert result.next_steps[-1]["migration_execution_report"] == str(output)
    assert "migration_hints" in result.report or result.report == ""


def test_cli_rejects_migration_execution_output_conflicts(tmp_path: Path, capsys) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    for conflict in (str(source), str(tmp_path / "audit.json"), str(tmp_path / "audit.sarif")):
        args = build_parser().parse_args(
            [
                "--code-file", str(source),
                "--language", "python",
                "--auto-migrate",
                "--output", str(tmp_path / "audit.json"),
                "--sarif-output", str(tmp_path / "audit.sarif"),
                "--migration-execution-output", conflict,
            ]
        )
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 2
        assert "--migration-execution-output must not overwrite" in capsys.readouterr().err


def test_cli_rejects_migration_function_without_execution_output(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--code-file", str(source),
            "--language", "python",
            "--auto-migrate",
            "--migration-function", "withdraw",
        ]
    )

    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
