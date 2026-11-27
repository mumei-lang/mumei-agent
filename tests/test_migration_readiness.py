from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.audit import build_parser, main
from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.migration_readiness import SCHEMA, _artifact_directory, build_migration_readiness


class FakeVerifyClient:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.calls = []

    def verify(self, source_path, report_dir=None, extra_args=None, spec_code_mapping=None, collect_decidable_metrics=False):
        self.calls.append(
            {
                "source_path": source_path,
                "report_dir": report_dir,
                "extra_args": extra_args,
                "spec_code_mapping": spec_code_mapping,
                "collect_decidable_metrics": collect_decidable_metrics,
            }
        )
        if "--output" in (extra_args or []):
            Path(extra_args[extra_args.index("--output") + 1]).write_text("{}", encoding="utf-8")
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
        "finding_counts": {"code": 0, "spec": 1, "errors": 0},
    }
    values.update(overrides)
    return AuditResult(**values)


def _hint(name: str, priority: str, skeleton: str | None = None) -> dict:
    return {
        "function_name": name,
        "priority": priority,
        "reason": f"{name} needs review",
        "skeleton": skeleton if skeleton is not None else f"atom {name}() -> i64 {{\n    requires: true;\n    ensures: true;\n    body: {{\n        0\n    }}\n}}",
        "next_step": "review skeleton",
    }


def test_migration_readiness_ranks_candidates_and_verifies_critical_skeleton(tmp_path: Path) -> None:
    source = tmp_path / "ledger.py"
    source.write_text(
        "def divide(total: int, count: int) -> int:\n    return total // count\n\n"
        "def write_audit(path):\n    open(path, 'w').write('x')\n",
        encoding="utf-8",
    )
    result = _result(
        source,
        [_hint("write_audit", "high"), _hint("divide", "high")],
        spec_health_issues=["contradiction: divide"],
    )
    output = tmp_path / "evidence" / "migration-readiness.json"
    client = FakeVerifyClient()

    report = build_migration_readiness(result, output_path=output, mumei_client=client)

    assert report["schema"] == SCHEMA
    assert output.exists()
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == json.loads(_json_roundtrip(report))
    assert [entry["rank"] for entry in report["migration_plan"]] == [1, 2]
    assert report["migration_plan"][0]["function_name"] == "divide"
    assert report["migration_plan"][0]["readiness_score"] > report["migration_plan"][1]["readiness_score"]
    assert report["migration_plan"][1]["external_effects"] == ["filesystem"]
    assert "generated skeleton has weak true/true contracts" in report["migration_plan"][0]["readiness_blockers"]
    critical = report["critical_function"]
    assert critical["function_name"] == "divide"
    verification = critical["verification"]
    assert verification["attempted"] is True
    assert verification["status"] == "verified"
    assert verification["proof_certificate_written"] is True
    assert len(client.calls) == 1
    assert "/divide-" in client.calls[0]["source_path"]
    assert client.calls[0]["source_path"].endswith(".mm")
    assert "--proof-cert" in client.calls[0]["extra_args"]
    assert "not proof that host-language code implements" in "\n".join(report["evidence_boundary"])


def _json_roundtrip(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def test_migration_readiness_marks_blocked_and_verifier_failure(tmp_path: Path) -> None:
    source = tmp_path / "bad.py"
    source.write_text("def bad():\n    pass\n", encoding="utf-8")
    result = _result(
        source,
        [_hint("bad", "high", skeleton="")],
        spec_health_issues=["malformed-extraction: bad requires: broken"],
    )
    output = tmp_path / "migration-readiness.json"
    client = FakeVerifyClient(success=False)

    report = build_migration_readiness(result, output_path=output, mumei_client=client)

    entry = report["migration_plan"][0]
    assert entry["verification_feasibility"] == "blocked"
    assert entry["readiness"] == "not_ready"
    assert "malformed extraction must be repaired" in entry["readiness_blockers"][0]
    assert report["critical_function"]["verification"]["status"] == "not_attempted"
    assert client.calls == []


def test_migration_readiness_writes_empty_plan_without_candidates(tmp_path: Path) -> None:
    source = tmp_path / "clean.py"
    source.write_text("def clean():\n    return 1\n", encoding="utf-8")
    output = tmp_path / "migration-readiness.json"

    report = build_migration_readiness(
        _result(source, [], success=True, verification_status="verified", migration_hints=[]),
        output_path=output,
        mumei_client=FakeVerifyClient(),
    )

    assert report["migration_plan"] == []
    assert report["critical_function"] is None
    assert json.loads(output.read_text(encoding="utf-8"))["audit"]["migration_candidate_count"] == 0


def test_critical_verification_diagnostics_are_redacted_and_sarif_is_declared(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    output = tmp_path / "readiness.json"

    class FailingClient(FakeVerifyClient):
        def verify(self, *args, **kwargs):
            super().verify(*args, **kwargs)
            return {
                "success": False,
                "report": {"status": "refuted", "message": "counterexample"},
                "stdout": "{}",
                "stderr": "sk-1234567890abcdefghij\nmore",
            }

    client = FailingClient(success=False)
    report = build_migration_readiness(
        _result(source, [_hint("withdraw", "high")]),
        output_path=output,
        mumei_client=client,
    )

    verification = report["critical_function"]["verification"]
    assert verification["status"] == "refuted"
    assert verification["sarif_path"].endswith(".sarif")
    assert verification["sarif_path"].endswith("report.sarif")
    assert "sk-1234567890abcdefghij" not in json.dumps(report)
    assert "<redacted>" in json.dumps(report)


def test_effect_detection_uses_python_function_ast_scope(tmp_path: Path) -> None:
    source = tmp_path / "mixed.py"
    source.write_text(
        "def write_file():\n    open('x', 'w').write('x')\n\n"
        "def pure_add(x: int) -> int:\n    return x + 1\n",
        encoding="utf-8",
    )
    result = _result(source, [_hint("pure_add", "high")])

    report = build_migration_readiness(
        result,
        output_path=tmp_path / "readiness.json",
        mumei_client=FakeVerifyClient(),
    )

    entry = report["migration_plan"][0]
    assert entry["analysis"] == "python-ast-function"
    assert entry["external_effects"] == []


def test_directory_hints_keep_per_file_health_and_duplicate_attribution(tmp_path: Path) -> None:
    first = tmp_path / "src" / "first.py"
    second = tmp_path / "src" / "second.py"
    first.parent.mkdir()
    first.write_text("def same():\n    open('x', 'w').write('x')\n", encoding="utf-8")
    second.write_text("def same():\n    return 1\n", encoding="utf-8")
    first_hint = _hint("same", "high")
    second_hint = _hint("same", "high")
    first_result = _result(first, [first_hint], spec_health_issues=["malformed-extraction: first broken"])
    second_result = _result(second, [second_hint], spec_health_issues=[])
    directory = AuditDirectoryResult(
        success=False,
        source_dir=str(first.parent),
        language="python",
        file_results=[first_result, second_result],
        verification_status="unverifiable",
        spec_health_issues=[
            "first.py: malformed-extraction: first broken",
        ],
        migration_hints=[first_hint, second_hint],
    )

    report = build_migration_readiness(
        directory,
        output_path=tmp_path / "readiness.json",
        mumei_client=FakeVerifyClient(),
    )

    entries = {entry["source_file"]: entry for entry in report["migration_plan"]}
    assert entries[str(first)]["verification_feasibility"] == "blocked"
    assert entries[str(second)]["verification_feasibility"] != "blocked"
    assert entries[str(first)]["external_effects"] == ["filesystem"]
    assert entries[str(second)]["external_effects"] == []


def test_duplicate_hints_within_one_file_keep_file_attribution(tmp_path: Path) -> None:
    source = tmp_path / "src" / "same.py"
    source.parent.mkdir()
    source.write_text("def same():\n    open('x', 'w').write('x')\n", encoding="utf-8")
    hint = _hint("same", "high")
    file_result = _result(source, [hint, dict(hint)], spec_health_issues=[])
    directory = AuditDirectoryResult(
        success=False,
        source_dir=str(source.parent),
        language="python",
        file_results=[file_result],
        verification_status="unverifiable",
        migration_hints=[hint, dict(hint)],
    )

    report = build_migration_readiness(
        directory,
        output_path=tmp_path / "readiness.json",
        mumei_client=FakeVerifyClient(),
    )

    entries = [entry for entry in report["migration_plan"] if entry["function_name"] == "same"]
    assert len(entries) == 2
    assert all(entry["source_file"] == str(source) for entry in entries)
    assert all(entry["external_effects"] == ["filesystem"] for entry in entries)


def test_artifact_directory_does_not_take_over_foreign_directory(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    foreign = tmp_path / "readiness.migration-readiness"
    foreign.mkdir()
    sentinel = foreign / "sentinel.mm"
    sentinel.write_text("atom user_owned() -> i64 {\n    requires: true;\n    ensures: true;\n    body: { 0 }\n}\n", encoding="utf-8")

    report = build_migration_readiness(
        _result(source, [_hint("withdraw", "high")]),
        output_path=tmp_path / "readiness.json",
        mumei_client=FakeVerifyClient(),
    )

    assert sentinel.read_text(encoding="utf-8").startswith("atom user_owned")
    assert "readiness.migration-readiness-1" in report["artifact_paths"]["critical_artifacts"]


def test_artifact_directory_does_not_follow_or_reuse_checkout_controlled_paths(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    victim = tmp_path / "victim.mm"
    victim.write_text("atom victim() -> i64 {\n    requires: true;\n    ensures: true;\n    body: { 0 }\n}\n", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / ".mumei-generated-artifacts").write_text("planted\n", encoding="utf-8")
    controlled = tmp_path / "readiness.migration-readiness"
    controlled.symlink_to(target, target_is_directory=True)

    report = build_migration_readiness(
        _result(source, [_hint("withdraw", "high")]),
        output_path=tmp_path / "readiness.json",
        mumei_client=FakeVerifyClient(),
    )

    artifacts = report["artifact_paths"]["critical_artifacts"]
    assert "readiness.migration-readiness-1" in artifacts
    assert victim.read_text(encoding="utf-8").startswith("atom victim")
    assert not list(target.glob("withdraw-*.mm"))

    second = build_migration_readiness(
        _result(source, [_hint("withdraw", "high")]),
        output_path=tmp_path / "readiness.json",
        mumei_client=FakeVerifyClient(),
    )
    assert "readiness.migration-readiness-2" in second["artifact_paths"]["critical_artifacts"]


def test_diagnostics_redact_credentials_before_truncation_and_remove_absolute_paths(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    token = "sk-1234567890abcdefghij" + ("x" * 600)

    class FailingClient(FakeVerifyClient):
        def verify(self, *args, **kwargs):
            super().verify(*args, **kwargs)
            return {
                "success": False,
                "report": {
                    "status": "refuted",
                    "message": f"failed at {tmp_path}/payment.py",
                    "counterexample": {"token": token},
                },
                "stdout": "{}",
                "stderr": "",
            }

    report = build_migration_readiness(
        _result(source, [_hint("withdraw", "high")]),
        output_path=tmp_path / "readiness.json",
        mumei_client=FailingClient(success=False),
    )
    serialized = json.dumps(report)

    diagnostics = json.dumps(report["critical_function"]["verification"]["diagnostics"])
    assert token not in serialized
    assert str(tmp_path) not in diagnostics
    assert "<redacted>" in serialized
    assert "<path>" in diagnostics


def test_diagnostics_redact_artifact_paths_containing_spaces(tmp_path: Path) -> None:
    spaced = tmp_path / "checkout with spaces"
    spaced.mkdir()
    source = spaced / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")

    class PathLeakClient(FakeVerifyClient):
        def verify(self, source_path, **kwargs):
            super().verify(source_path, **kwargs)
            return {
                "success": False,
                "report": {"status": "refuted", "message": f"failed at {source_path}"},
                "stdout": "{}",
                "stderr": "",
            }

    report = build_migration_readiness(
        _result(source, [_hint("withdraw", "high")]),
        output_path=spaced / "readiness.json",
        mumei_client=PathLeakClient(success=False),
    )

    diagnostics = json.dumps(report["critical_function"]["verification"]["diagnostics"])
    assert "checkout with spaces" not in diagnostics
    assert "<path>" in diagnostics


def test_migration_readiness_output_replaces_symlink_without_overwriting_target(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    victim = tmp_path / "victim.json"
    victim.write_text("user data\n", encoding="utf-8")
    output = tmp_path / "readiness.json"
    output.symlink_to(victim)

    build_migration_readiness(
        _result(source, [_hint("withdraw", "high")]),
        output_path=output,
        mumei_client=FakeVerifyClient(),
    )

    assert victim.read_text(encoding="utf-8") == "user data\n"
    assert not output.is_symlink()
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == SCHEMA


def test_migration_readiness_output_preserves_existing_group_read_mode(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    output = tmp_path / "readiness.json"
    output.write_text("old\n", encoding="utf-8")
    output.chmod(0o640)

    build_migration_readiness(
        _result(source, [_hint("withdraw", "high")]),
        output_path=output,
        mumei_client=FakeVerifyClient(),
    )

    assert output.stat().st_mode & 0o777 == 0o640


def test_artifact_directory_allocation_has_no_fixed_collision_cap(tmp_path: Path) -> None:
    output = tmp_path / "readiness.json"
    for index in range(1000):
        name = "readiness.migration-readiness" if index == 0 else f"readiness.migration-readiness-{index}"
        (tmp_path / name).mkdir()

    allocated = _artifact_directory(output)

    assert allocated.name == "readiness.migration-readiness-1000"


def test_cli_requires_auto_migrate_for_migration_readiness(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--code-file", str(source),
            "--language", "python",
            "--migration-readiness-output", str(tmp_path / "readiness.json"),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_cli_writes_migration_readiness_after_audit(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    output = tmp_path / "readiness.json"
    result = _result(source, [_hint("withdraw", "high")])
    report = {"schema": SCHEMA, "migration_plan": []}

    with patch("agent.audit.AuditPipeline") as pipeline_cls, patch("agent.audit.build_migration_readiness", return_value=report) as build:
        pipeline_cls.return_value.audit_file.return_value = result
        args = build_parser().parse_args(
            [
                "--code-file", str(source),
                "--language", "python",
                "--format", "json",
                "--auto-migrate",
                "--migration-readiness-output", str(output),
            ]
        )
        returned = main(args)

    assert returned is result
    build.assert_called_once()
    assert build.call_args.kwargs["output_path"] == output
    assert build.call_args.kwargs["mumei_client"] is pipeline_cls.return_value.mumei_client


def test_cli_rejects_migration_readiness_output_conflicts(tmp_path: Path) -> None:
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
                "--migration-readiness-output", conflict,
            ]
        )
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 2


def test_cli_rejects_case_insensitive_source_collision_in_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    source = source_dir / "ledger.PY"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--code-file", str(source_dir),
            "--language", "python",
            "--auto-migrate",
            "--migration-readiness-output", str(source),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
