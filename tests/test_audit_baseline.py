"""Contract tests for audit baselines and fail-on policy."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.audit import build_parser, main
from agent.audit_baseline import apply_baseline, load_baseline, write_baseline
from agent.audit_models import AuditResult
from agent.audit_reporting import _finalize_audit_result
from agent.audit_sarif import audit_exit_code


def _result(**overrides):
    values = {
        "success": False,
        "source_file": "src/example.py",
        "language": "python",
        "spec_extracted": True,
        "verification_status": "refuted",
        "verification_violations": ["body-port: counterexample x=0"],
    }
    values.update(overrides)
    return _finalize_audit_result(AuditResult(**values))


def test_write_and_load_baseline_roundtrip_is_deterministic(tmp_path: Path) -> None:
    result = _result()
    first = tmp_path / "baseline.json"
    second = tmp_path / "baseline-again.json"

    write_baseline(result, first)
    write_baseline(result, second)

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["version"] == "mumei.audit-baseline/v1"
    assert payload["fingerprints"] == [result.findings[0]["fingerprint"]]
    assert load_baseline(first) == {result.findings[0]["fingerprint"]}


def test_invalid_baseline_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text('{"version":"wrong","fingerprints":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported schema"):
        load_baseline(path)


def test_baseline_suppresses_matching_finding_for_default_refuted_policy() -> None:
    result = _result()
    fingerprint = result.findings[0]["fingerprint"]

    assert audit_exit_code(result) == 1
    apply_baseline(result, {fingerprint})

    assert result.findings[0]["baseline"] == "suppressed"
    assert audit_exit_code(result) == 0


def test_fail_on_high_confidence_ignores_medium_body_port_but_not_native_replay() -> None:
    medium = _result()
    high = _result(
        verification_violations=["native-replay: withdraw violates contract"],
    )

    assert medium.findings[0]["confidence"] == "medium"
    assert audit_exit_code(medium, fail_on="high-confidence") == 0
    assert high.findings[0]["confidence"] == "high"
    assert audit_exit_code(high, fail_on="high-confidence") == 1


def test_fail_on_never_does_not_hide_operational_errors() -> None:
    result = _result(errors=["mumei verify did not produce a verification report"])

    assert audit_exit_code(result, fail_on="never") == 2


def test_fail_on_error_includes_error_level_findings() -> None:
    result = _result()

    assert audit_exit_code(result, fail_on="error") == 1


def test_cli_writes_baseline_then_suppresses_matching_finding(tmp_path: Path, capsys) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    baseline = tmp_path / "audit-baseline.json"
    result = _result(source_file=str(source))
    args = build_parser().parse_args([
        "--code-file", str(source),
        "--language", "python",
        "--format", "json",
        "--write-baseline", str(baseline),
    ])

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = result
        main(args)

    assert baseline.exists()
    capsys.readouterr()
    args = build_parser().parse_args([
        "--code-file", str(source),
        "--language", "python",
        "--format", "json",
        "--baseline", str(baseline),
    ])
    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = result
        main(args)

    output = json.loads(capsys.readouterr().out)
    assert output["findings"][0]["baseline"] == "suppressed"


def test_cli_rejects_write_baseline_over_audit_input(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    args = build_parser().parse_args([
        "--code-file", str(source),
        "--language", "python",
        "--write-baseline", str(source),
    ])

    with pytest.raises(SystemExit) as excinfo:
        main(args)

    assert excinfo.value.code == 2
    assert source.read_text(encoding="utf-8") == "def withdraw():\n    pass\n"


def test_cli_rejects_invalid_baseline_before_running_pipeline(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    baseline = tmp_path / "bad.json"
    baseline.write_text("not-json", encoding="utf-8")
    args = build_parser().parse_args([
        "--code-file", str(source),
        "--language", "python",
        "--baseline", str(baseline),
    ])

    with patch("agent.audit.AuditPipeline") as pipeline_cls, pytest.raises(SystemExit) as excinfo:
        main(args)

    assert excinfo.value.code == 2
    pipeline_cls.return_value.audit_file.assert_not_called()

def test_sarif_marks_suppressed_and_new_findings_with_baseline_state() -> None:
    from agent.audit_sarif import sarif_document

    result = _result()
    suppressed = result.findings[0]["fingerprint"]
    apply_baseline(result, {suppressed})
    rows = sarif_document(result)["runs"][0]["results"]
    assert rows[0]["baselineState"] == "unchanged"

    apply_baseline(result, set())
    rows = sarif_document(result)["runs"][0]["results"]
    assert rows[0]["baselineState"] == "new"

def test_python_module_dispatch_uses_fail_on_policy(monkeypatch) -> None:
    result = _result()

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = result
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "agent",
                "audit",
                "--code-file", "payment.py",
                "--language", "python",
                "--fail-on", "high-confidence",
            ],
        )
        import agent.__main__ as agent_main

        with pytest.raises(SystemExit) as excinfo:
            agent_main.main()

    assert excinfo.value.code == 0

def test_sarif_baseline_state_distinguishes_same_message_in_different_files() -> None:
    from agent.audit_reporting import _aggregate_directory_fixed_keys
    from agent.audit_sarif import sarif_document
    from agent.audit_models import AuditDirectoryResult

    directory = AuditDirectoryResult(
        success=True,
        source_dir="src",
        language="mixed",
        trusted_atoms=[
            {"file": "a/spec.mm", "atom": "withdraw", "line": 3},
            {"file": "b/spec.mm", "atom": "withdraw", "line": 3},
        ],
    )
    _aggregate_directory_fixed_keys(directory)
    first, second = directory.findings
    apply_baseline(directory, {first["fingerprint"]})

    rows = sarif_document(directory)["runs"][0]["results"]

    assert rows[0]["baselineState"] == "unchanged"
    assert rows[1]["baselineState"] == "new"


def test_cli_rejects_write_baseline_over_uppercase_source_in_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    source = source_dir / "Calc.PY"
    source.write_text("def calc():\n    pass\n", encoding="utf-8")
    args = build_parser().parse_args([
        "--code-file", str(source_dir),
        "--language", "python",
        "--write-baseline", str(source),
    ])

    with pytest.raises(SystemExit) as excinfo:
        main(args)

    assert excinfo.value.code == 2
    assert source.read_text(encoding="utf-8") == "def calc():\n    pass\n"


def test_cli_rejects_baseline_input_overwritten_by_report_outputs(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"version":"mumei.audit-baseline/v1","fingerprints":[]}', encoding="utf-8")
    for output_flag in ("--output", "--sarif-output"):
        args = build_parser().parse_args([
            "--code-file", str(source),
            "--language", "python",
            "--baseline", str(baseline),
            output_flag, str(baseline),
        ])

        with pytest.raises(SystemExit) as excinfo:
            main(args)

        assert excinfo.value.code == 2
        assert baseline.read_text(encoding="utf-8").startswith('{"version"')


def test_cli_rejects_write_baseline_over_summary_inputs(tmp_path: Path) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    for flag in ("--summaries-manifest-map", "--summary-plan-histories"):
        input_path = tmp_path / f"{flag[2:]}.json"
        input_path.write_text("{}", encoding="utf-8")
        args = build_parser().parse_args([
            "--code-file", str(source),
            "--language", "python",
            flag, str(input_path),
            "--write-baseline", str(input_path),
        ])

        with pytest.raises(SystemExit) as excinfo:
            main(args)

        assert excinfo.value.code == 2
        assert input_path.read_text(encoding="utf-8") == "{}"


def test_directory_fingerprints_distinguish_independent_nested_checkouts(tmp_path: Path) -> None:
    from agent.audit_models import AuditDirectoryResult
    from agent.audit_reporting import _aggregate_directory_fixed_keys

    root = tmp_path / "scan-root"
    files = []
    for repo in ("repo-one", "repo-two"):
        checkout = root / repo
        (checkout / ".git").mkdir(parents=True)
        target = checkout / "src" / "payment.py"
        target.parent.mkdir()
        target.write_text("def withdraw():\n    pass\n", encoding="utf-8")
        files.append(
            _result(
                source_file=str(target),
                verification_violations=["body-port: counterexample x=0"],
            )
        )
    directory = AuditDirectoryResult(
        success=False,
        source_dir=str(root),
        language="python",
        file_results=files,
    )

    _aggregate_directory_fixed_keys(directory)

    assert directory.findings[0]["fingerprint"] != directory.findings[1]["fingerprint"]


def test_exit_code_preserves_raw_refuted_signal_before_findings_exist() -> None:
    result = AuditResult(
        success=False,
        source_file="src/example.py",
        language="python",
        spec_extracted=True,
        verification_status="unverifiable",
        verification_violations=["body-port: counterexample x=0"],
    )

    assert not result.findings
    assert audit_exit_code(result) == 1


def test_cli_skips_baseline_write_when_audit_has_operational_errors(tmp_path: Path, capsys) -> None:
    source = tmp_path / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    baseline = tmp_path / "audit-baseline.json"
    result = _result(source_file=str(source), errors=["mumei verify did not produce a verification report"])
    args = build_parser().parse_args([
        "--code-file", str(source),
        "--language", "python",
        "--write-baseline", str(baseline),
    ])

    with patch("agent.audit.AuditPipeline") as pipeline_cls:
        pipeline_cls.return_value.audit_file.return_value = result
        main(args)

    assert not baseline.exists()
    assert "baseline output skipped" in capsys.readouterr().err
