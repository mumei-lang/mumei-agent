from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import jsonschema

from agent.audit import AuditPipeline, build_parser, main
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
            "report": {"status": "success" if self.success else "refuted", "message": "fake verifier"},
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
    schema = json.loads((Path(__file__).parents[1] / "schema" / "migration-execution.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(report, schema)
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
    assert verification["status"] == "success"
    assert verification["contract_proved"] is True
    assert verification["proof_certificate"]["written"] is True
    assert verification["proof_certificate"]["sha256"]
    assert verification["sarif"]["written"] is True
    assert verification["sarif"]["sha256"]
    assert client.calls[0]["source_path"].endswith(".mm")
    assert candidate["unbound_audit_diagnostics"]["status"] == "available"
    assert candidate["unbound_audit_diagnostics"]["entries"][0]["outcome"] == "violates"
    assert candidate["unbound_audit_diagnostics"]["binding"]["status"] == "not_bound_to_generated_mm"
    assert candidate["unbound_audit_diagnostics"]["binding"]["generated_mm_sha256"] is None
    provenance = candidate["contract_provenance"]
    assert provenance["original_skeleton_sha256"] == provenance["final_sha256"]
    assert provenance["content_changed"] is False
    assert provenance["contract_clauses_changed"] is False
    assert provenance["final_sha256"] == candidate["generated_mm"]["sha256"]
    boundary = "\n".join(report["evidence_boundary"])
    assert "not proof that host-language code implements the same behavior" in boundary
    assert "diagnostic evidence only" in candidate["unbound_audit_diagnostics"]["semantics"]
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
    assert candidate["verification"]["status"] == "success"
    assert candidate["verification"]["contract_proved"] is True
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
    assert pipeline_cls.return_value.audit_file.call_args.kwargs["migration_heal_functions"] == ["withdraw"]
    build.assert_called_once()
    assert build.call_args.kwargs["output_path"] == output
    assert build.call_args.kwargs["selected_functions"] == ["withdraw"]
    assert build.call_args.kwargs["heal_attempted"] is True
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


def test_commented_trusted_atom_text_is_not_a_contract_blocker(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    skeleton = (
        "atom withdraw() -> i64 {\n"
        "    requires: true;\n"
        "    ensures: result == 0;\n"
        "    // trusted atom documented_only() -> i64\n"
        "    body: { 0 }\n"
        "}"
    )

    report = build_migration_execution(
        _result(source, [_hint("withdraw", skeleton)]),
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
    )

    candidate = report["candidates"][0]
    assert candidate["extracted_contract"]["trusted_atom_declarations"] == []
    assert not any("trusted atoms" in str(item) for item in candidate["evidence_blockers"])


def test_directory_candidates_keep_per_file_provenance(tmp_path: Path) -> None:
    from agent.audit_models import AuditDirectoryResult

    first = tmp_path / "src" / "first.py"
    second = tmp_path / "src" / "second.py"
    first.parent.mkdir()
    first.write_text("def same():\n    return 1\n", encoding="utf-8")
    second.write_text("def same():\n    return 2\n", encoding="utf-8")
    first_hint = _hint("same")
    second_hint = _hint("same")
    first_result = _result(first, [first_hint])
    second_result = _result(second, [second_hint])
    directory = AuditDirectoryResult(
        success=False,
        source_dir=str(first.parent),
        language="python",
        file_results=[first_result, second_result],
        verification_status="unverifiable",
        migration_hints=[first_hint, second_hint],
    )

    report = build_migration_execution(
        directory,
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
    )

    provenance = [item["source_provenance"] for item in report["candidates"]]
    assert [item["path"] for item in provenance] == [str(first), str(second)]
    assert len({item["sha256"] for item in provenance}) == 2


def test_healed_contract_replaces_weak_skeleton_blocker(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    weak = "atom withdraw() -> i64 {\n    requires: true;\n    ensures: true;\n    body: { 0 }\n}"
    strong = "atom withdraw(x: i64) -> i64 {\n    requires: x >= 0;\n    ensures: result >= 0;\n    body: { x }\n}"
    healed = tmp_path / "withdraw.mm"
    healed.write_text(strong, encoding="utf-8")

    report = build_migration_execution(
        _result(source, [_hint("withdraw", weak)], healed_files=[str(healed)]),
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
    )

    candidate = report["candidates"][0]
    assert candidate["extracted_contract"]["weak_true_contract"] is False
    assert not any("weak true/true" in str(item) for item in candidate["evidence_blockers"])
    provenance = candidate["contract_provenance"]
    assert provenance["original_requires"] == ["true"]
    assert provenance["final_requires"] == ["x >= 0"]
    assert provenance["content_changed"] is True
    assert provenance["contract_clauses_changed"] is True


def test_empty_verifier_report_is_operational_even_with_zero_exit(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")

    class EmptyReportClient(FakeVerifyClient):
        def verify(self, *args, **kwargs):
            super().verify(*args, **kwargs)
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

    report = build_migration_execution(
        _result(source, [_hint("withdraw")]),
        output_path=tmp_path / "execution.json",
        mumei_client=EmptyReportClient(),
    )

    candidate = report["candidates"][0]
    assert candidate["execution_state"] == "operational_error"
    assert candidate["verification"]["operational_error"] == "VerifierOutputUnavailable"
    assert candidate["verification"]["contract_proved"] is not True


def test_heal_migration_hints_respects_selected_functions(tmp_path: Path) -> None:
    pipeline = object.__new__(AuditPipeline)
    pipeline.heal_output_dir = tmp_path
    pipeline._run_heal_loop = lambda target: None
    hints = [_hint("withdraw"), _hint("deposit")]

    healed, errors = pipeline._heal_migration_hints(hints, tmp_path / "source.py", selected_functions=["withdraw"])

    assert errors == []
    assert len(healed) == 1
    assert Path(healed[0]).parent == tmp_path
    assert Path(healed[0]).name.startswith("withdraw-")
    assert Path(healed[0]).suffix == ".mm"
    assert not list(tmp_path.glob("deposit*.mm"))



def test_string_literals_in_contracts_are_redacted_and_not_reparsed(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    secret = "requires: injected; hello;world"
    original = f'atom withdraw() -> i64 {{\n    requires: password == "{secret}";\n    ensures: result >= 0;\n    body: {{ 0 }}\n}}'

    report = build_migration_execution(
        _result(source, [_hint("withdraw", original)]),
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
    )

    candidate = report["candidates"][0]
    provenance = candidate["contract_provenance"]
    assert provenance["original_requires"] == ['password == "<redacted>"']
    assert len(provenance["original_requires"]) == 1
    assert candidate["extracted_contract"]["string_literals_redacted"] is True
    assert candidate["execution_state"] == "blocked"
    assert secret not in json.dumps(report)


def test_migration_output_never_overwrites_existing_mm(tmp_path: Path) -> None:
    existing = tmp_path / "withdraw.mm"
    existing.write_text("atom existing() -> i64 { body: { 1 } }\n", encoding="utf-8")
    pipeline = object.__new__(AuditPipeline)
    pipeline.heal_output_dir = tmp_path
    pipeline._run_heal_loop = lambda target: None

    healed, errors = pipeline._heal_migration_hints([_hint("withdraw")], tmp_path / "source.py")

    assert errors == []
    assert len(healed) == 1
    assert Path(healed[0]).name.startswith("withdraw-")
    assert Path(healed[0]).name != "withdraw.mm"
    assert existing.read_text(encoding="utf-8") == "atom existing() -> i64 { body: { 1 } }\n"

    healed_again, errors_again = pipeline._heal_migration_hints([_hint("withdraw")], tmp_path / "source.py")
    assert errors_again == []
    assert len(healed_again) == 1
    assert healed_again[0] == healed[0]


def test_credential_shaped_skeleton_is_not_written_or_copied(tmp_path: Path) -> None:
    secret = "ghp_" + "a" * 30
    skeleton = f'atom withdraw() -> i64 {{\n    requires: token == "{secret}";\n    ensures: result >= 0;\n    body: {{ 0 }}\n}}'
    pipeline = object.__new__(AuditPipeline)
    pipeline.heal_output_dir = tmp_path / "heal"
    pipeline._run_heal_loop = lambda target: None

    healed, errors = pipeline._heal_migration_hints([_hint("withdraw", skeleton)], tmp_path / "source.py")

    assert healed == []
    assert errors == ["withdraw: migration skeleton contains string literals that may be sensitive"]
    assert not (tmp_path / "heal" / "withdraw.mm").exists()

    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    report = build_migration_execution(
        _result(source, [_hint("withdraw", skeleton)]),
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
    )
    candidate = report["candidates"][0]
    assert candidate["execution_state"] == "blocked"
    assert candidate["generated_mm"]["path"] is None
    assert secret not in json.dumps(report)
    assert not list(Path(report["artifact_paths"]["generated_artifacts"]).glob("*.mm"))


def test_heal_errors_are_attributed_per_file_and_paths_are_redacted(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    absolute_error = f"{tmp_path}/withdraw.mm: proof failed"
    report = build_migration_execution(
        _result(source, [_hint("withdraw")], heal_errors=[absolute_error]),
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
    )

    candidate = report["candidates"][0]
    assert candidate["execution_state"] == "blocked"
    assert "heal completed with errors" in candidate["evidence_blockers"]
    assert candidate["heal"]["errors"] == ["<path>: proof failed"]
    assert str(tmp_path) not in json.dumps(candidate["heal"])


def test_ambiguous_same_named_healed_files_are_not_bound(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def same():\n    pass\n", encoding="utf-8")
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "same.mm"
    second = second_dir / "same.mm"
    first.write_text("atom same() -> i64 { body: { 1 } }\n", encoding="utf-8")
    second.write_text("atom same() -> i64 { body: { 2 } }\n", encoding="utf-8")

    report = build_migration_execution(
        _result(source, [_hint("same")], healed_files=[str(first), str(second)]),
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
    )

    candidate = report["candidates"][0]
    assert candidate["heal"]["healed_file"] is None
    assert candidate["generated_mm"]["origin"] == "generated_skeleton"


def test_unqualified_diagnostic_does_not_match_qualified_candidate(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("class Service:\n    def check(self):\n        pass\n", encoding="utf-8")
    result = _result(
        source,
        [_hint("Service.check"), _hint("check")],
        native_replays=[
            {"function": "check", "input": {}, "verdict": "violates"},
            {"function": "Service.check", "input": {}, "verdict": "consistent"},
        ],
    )

    report = build_migration_execution(result, output_path=tmp_path / "execution.json", mumei_client=FakeVerifyClient())

    entries = report["candidates"][0]["unbound_audit_diagnostics"]["entries"]
    assert [entry["outcome"] for entry in entries] == ["consistent"]


def test_output_stem_collision_still_writes_report(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    output = tmp_path / "review.migration-execution"

    report = build_migration_execution(
        _result(source, [_hint("withdraw")]),
        output_path=output,
        mumei_client=FakeVerifyClient(),
    )

    assert output.is_file()
    assert Path(report["artifact_paths"]["generated_artifacts"]).is_dir()
    assert report["artifact_paths"]["generated_artifacts"] != str(output)


@pytest.mark.integration
def test_real_mumei_verify_writes_proof_and_sarif(tmp_path: Path) -> None:
    binary = os.environ.get("MUMEI_BIN", "")
    if not binary or not Path(binary).is_absolute() or not Path(binary).is_file():
        pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")
    from agent.mumei_client import create_mumei_client

    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    report = build_migration_execution(
        _result(source, [_hint("withdraw")]),
        output_path=tmp_path / "execution.json",
        mumei_client=create_mumei_client(binary),
    )

    verification = report["candidates"][0]["verification"]
    assert verification["contract_proved"] is True
    assert verification["proof_certificate"]["written"] is True
    assert verification["proof_certificate"]["sha256"]
    assert verification["sarif"]["written"] is True
    assert verification["sarif"]["sha256"]


def test_directory_heal_errors_stay_attached_to_file_candidate(tmp_path: Path) -> None:
    from agent.audit_models import AuditDirectoryResult

    source = tmp_path / "src" / "payment.py"
    source.parent.mkdir()
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    hint = _hint("withdraw")
    file_result = _result(source, [hint], heal_errors=["withdraw.mm: proof still failing"])
    directory = AuditDirectoryResult(
        success=False,
        source_dir=str(source.parent),
        language="python",
        file_results=[file_result],
        verification_status="unverifiable",
        migration_hints=[hint],
        heal_errors=[f"payment.py: {file_result.heal_errors[0]}"],
    )

    report = build_migration_execution(directory, output_path=tmp_path / "execution.json", mumei_client=FakeVerifyClient())

    candidate = report["candidates"][0]
    assert candidate["heal"]["errors"] == ["withdraw.mm: proof still failing"]
    assert "heal completed with errors" in candidate["evidence_blockers"]
    assert candidate["execution_state"] == "blocked"


def test_unique_unqualified_diagnostic_matches_qualified_method(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("class Ledger:\n    def debit(self):\n        pass\n", encoding="utf-8")
    result = _result(
        source,
        [_hint("Ledger.debit")],
        native_replays=[{"function": "debit", "input": {}, "verdict": "consistent"}],
    )

    report = build_migration_execution(result, output_path=tmp_path / "execution.json", mumei_client=FakeVerifyClient())

    entries = report["candidates"][0]["unbound_audit_diagnostics"]["entries"]
    assert [entry["outcome"] for entry in entries] == ["consistent"]


def test_keyed_healed_output_binds_to_generated_mm(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    existing = tmp_path / "withdraw.mm"
    existing.write_text("atom existing() -> i64 { body: { 1 } }\n", encoding="utf-8")
    pipeline = object.__new__(AuditPipeline)
    pipeline.heal_output_dir = tmp_path
    pipeline._run_heal_loop = lambda target: None
    hint = _hint("withdraw")
    healed, errors = pipeline._heal_migration_hints([hint], source)

    assert errors == []
    report = build_migration_execution(
        _result(source, [hint], healed_files=healed),
        output_path=tmp_path / "execution.json",
        mumei_client=FakeVerifyClient(),
    )

    candidate = report["candidates"][0]
    assert candidate["heal"]["healed_file"] == healed[0]
    assert candidate["generated_mm"]["origin"] == "healed_file"
    assert candidate["generated_mm"]["healed_source_path"] == healed[0]


def test_same_named_directory_candidates_bind_their_own_keyed_healing(tmp_path: Path) -> None:
    from agent.audit_models import AuditDirectoryResult

    source_dir = tmp_path / "src"
    output_dir = tmp_path / "heal"
    source_dir.mkdir()
    first = source_dir / "first.py"
    second = source_dir / "second.py"
    first.write_text("def same():\n    return 1\n", encoding="utf-8")
    second.write_text("def same():\n    return 2\n", encoding="utf-8")
    pipeline = object.__new__(AuditPipeline)
    pipeline.heal_output_dir = output_dir
    pipeline._run_heal_loop = lambda target: None
    hint = _hint("same")
    first_healed, first_errors = pipeline._heal_migration_hints([hint], first)
    second_healed, second_errors = pipeline._heal_migration_hints([hint], second)
    assert first_errors == second_errors == []
    assert first_healed != second_healed

    first_result = _result(first, [hint], healed_files=first_healed)
    second_result = _result(second, [hint], healed_files=second_healed)
    directory = AuditDirectoryResult(
        success=False,
        source_dir=str(source_dir),
        language="python",
        file_results=[first_result, second_result],
        verification_status="unverifiable",
        migration_hints=[hint, hint],
        healed_files=first_healed + second_healed,
    )

    report = build_migration_execution(directory, output_path=tmp_path / "execution.json", mumei_client=FakeVerifyClient())

    assert [candidate["heal"]["healed_file"] for candidate in report["candidates"]] == [first_healed[0], second_healed[0]]
    assert all(candidate["generated_mm"]["origin"] == "healed_file" for candidate in report["candidates"])


@pytest.mark.integration
def test_real_mumei_cli_audit_writes_migration_execution(tmp_path: Path) -> None:
    binary = os.environ.get("MUMEI_BIN", "")
    if not binary or not Path(binary).is_absolute() or not Path(binary).is_file():
        pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")
    source = tmp_path / "payment.py"
    source.write_text("def divide(total: int, count: int) -> int:\n    return total // count\n", encoding="utf-8")
    audit_output = tmp_path / "audit.json"
    execution_output = tmp_path / "execution.json"
    env = os.environ.copy()
    env["LLM_API_KEY"] = ""
    env["OPENAI_API_KEY"] = ""
    env["MUMEI_BIN"] = binary
    repo = str(Path(__file__).parents[1])
    env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent",
            "audit",
            "--code-file",
            str(source),
            "--language",
            "python",
            "--format",
            "json",
            "--auto-migrate",
            "--migration-function",
            "divide",
            "--migration-execution-output",
            str(execution_output),
            "--output",
            str(audit_output),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "[Step 3/3] Running self-healing loop" in completed.stderr
    audit = json.loads(audit_output.read_text(encoding="utf-8"))
    assert len(audit["migration_hints"]) == 1
    assert audit["next_steps"][-1]["migration_execution_report"] == str(execution_output)
    report = json.loads(execution_output.read_text(encoding="utf-8"))
    assert report["selection"]["requested_functions"] == ["divide"]
    assert len(report["candidates"]) == 1
    candidate = report["candidates"][0]
    assert candidate["heal"]["attempted"] is True
    assert candidate["verification"]["contract_proved"] is True
    assert candidate["verification"]["proof_certificate"]["written"] is True
    assert candidate["verification"]["sarif"]["written"] is True
    assert Path(candidate["generated_mm"]["path"]).is_file()


def test_rerun_reuses_identical_output_and_suffixes_healed_divergence(tmp_path: Path) -> None:
    pipeline = object.__new__(AuditPipeline)
    pipeline.heal_output_dir = tmp_path
    source = tmp_path / "source.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    hint = _hint("withdraw")
    def mutate(target: Path) -> None:
        target.write_text(target.read_text(encoding="utf-8") + "// healed\n", encoding="utf-8")

    pipeline._run_heal_loop = mutate
    first, first_errors = pipeline._heal_migration_hints([hint], source)
    diverged, diverged_errors = pipeline._heal_migration_hints([hint], source)
    assert first_errors == diverged_errors == []
    assert diverged[0] != first[0]
    assert Path(diverged[0]).name.endswith("-1.mm")
