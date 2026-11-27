"""Contract tests for audit finding metadata and file-level triage."""
from __future__ import annotations

from dataclasses import asdict

from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.audit_reporting import _aggregate_directory_fixed_keys, _finalize_audit_result


def _result(**overrides):
    values = {
        "success": True,
        "source_file": "src/example.py",
        "language": "python",
        "spec_extracted": True,
    }
    values.update(overrides)
    return AuditResult(**values)


def _finalize(**overrides):
    result = _result(**overrides)
    return _finalize_audit_result(result)


def test_code_findings_expose_verification_basis_and_confidence() -> None:
    result = _finalize(
        success=False,
        verification_status="refuted",
        verification_violations=[
            "body-port: withdraw — status=refuted counterexample {'x': 1}",
            "native-replay: transfer violates contract",
            "checksum mismatch",
        ],
    )

    rows = {row["message"]: row for row in result.findings}
    assert rows["body-port: withdraw — status=refuted counterexample {'x': 1}"]["verification_basis"] == "body-port"
    assert rows["body-port: withdraw — status=refuted counterexample {'x': 1}"]["confidence"] == "medium"
    assert rows["native-replay: transfer violates contract"]["verification_basis"] == "native-replay"
    assert rows["native-replay: transfer violates contract"]["confidence"] == "high"
    assert rows["checksum mismatch"]["verification_basis"] == "deterministic-static-analysis"
    assert all(row["category"] == "code" for row in rows.values())
    assert all(row["triage_bucket"] == "code_review" for row in rows.values())
    assert len({row["fingerprint"] for row in rows.values()}) == 3


def test_spec_and_operational_findings_have_separate_categories() -> None:
    result = _finalize(
        verification_status="unverifiable",
        spec_health_issues=[
            "vacuity: requires is unreachable",
            "encoding-gap: bitwise operation unsupported",
            "malformed-extraction: generated spec is invalid",
        ],
        cross_validation_gaps=["requires clause is not reflected in code"],
        trusted_atoms=[{"atom": "withdraw", "line": 7}],
        errors=["mumei verify timed out"],
    )

    by_message = {row["message"]: row for row in result.findings}
    assert by_message["vacuity: requires is unreachable"]["category"] == "spec"
    assert by_message["vacuity: requires is unreachable"]["verification_basis"] == "z3-spec-health"
    assert by_message["encoding-gap: bitwise operation unsupported"]["category"] == "model_limitation"
    assert by_message["encoding-gap: bitwise operation unsupported"]["triage_bucket"] == "model_limitation"
    assert by_message["malformed-extraction: generated spec is invalid"]["category"] == "error"
    assert by_message["malformed-extraction: generated spec is invalid"]["triage_bucket"] == "operational"
    assert by_message["requires clause is not reflected in code"]["verification_basis"] == "cross-validation"
    trusted = by_message["trusted atom bypasses Z3 verification: withdraw"]
    assert trusted["category"] == "advisory"
    assert trusted["line"] == 7
    assert by_message["mumei verify timed out"]["category"] == "error"


def test_file_triage_reflects_verdict_without_replacing_fixed_keys() -> None:
    refuted = _finalize(verification_status="refuted", verification_violations=["counterexample"])
    verified = _finalize(verification_status="verified")
    timeout = _finalize(verification_status="unverifiable", errors=["mumei verify timed out"])

    assert refuted.triage["refuted"] == ["src/example.py"]
    assert verified.triage["verified"] == ["src/example.py"]
    assert timeout.triage["unverifiable"]["timeout"] == ["src/example.py"]
    assert timeout.triage["counts"]["unverifiable_by_cause"]["timeout"] == 1
    assert timeout.verification_status == "unverifiable"
    assert timeout.next_steps


def test_directory_aggregation_builds_findings_and_triage() -> None:
    refuted = _finalize(
        source_file="bad.py",
        verification_status="refuted",
        verification_violations=["counterexample"],
    )
    verified = _finalize(source_file="good.py", verification_status="verified")
    gap = _finalize(
        source_file="wide.py",
        verification_status="unverifiable",
        spec_health_issues=["encoding-gap: unsupported shift"],
    )
    directory = AuditDirectoryResult(
        success=False,
        source_dir="src",
        language="python",
        file_results=[refuted, verified, gap],
        total_files=3,
    )
    _aggregate_directory_fixed_keys(directory)

    assert directory.triage["refuted"] == ["bad.py"]
    assert directory.triage["verified"] == ["good.py"]
    assert directory.triage["unverifiable"]["encoding_gap"] == ["wide.py"]
    assert directory.triage["counts"] == {
        "refuted": 1,
        "verified": 1,
        "unverifiable": 1,
        "unverifiable_by_cause": {
            "skipped_rate_limited": 0,
            "timeout": 0,
            "encoding_gap": 1,
            "no_function_declarations": 0,
            "other": 0,
        },
    }
    assert {row["source_file"] for row in directory.findings} >= {"bad.py", "wide.py"}
    serialized = asdict(directory)
    assert serialized["findings"]
    assert serialized["triage"]["schema"] == "mumei.audit-triage/v1"


def test_rate_limit_category_wins_over_timeout() -> None:
    noisy = _finalize(
        verification_status="unverifiable",
        errors=["error code: 429 rate limit; mumei verify timed out"],
    )
    assert noisy.triage["unverifiable"]["skipped_rate_limited"] == ["src/example.py"]
    assert noisy.triage["unverifiable"]["timeout"] == []


def test_lowering_failure_uses_encoding_gap_triage() -> None:
    noisy = _finalize(
        verification_status="unverifiable",
        spec_health_issues=["spec_lowering_failed: unsupported expression"],
    )
    assert noisy.triage["unverifiable"]["encoding_gap"] == ["src/example.py"]


def test_directory_report_surfaces_triage_counts() -> None:
    from agent.audit_reporting import _build_directory_report

    refuted = _finalize(verification_status="refuted", verification_violations=["counterexample"])
    directory = AuditDirectoryResult(
        success=False,
        source_dir="src",
        language="python",
        file_results=[refuted],
        total_files=1,
        files_with_issues=1,
    )
    _aggregate_directory_fixed_keys(directory)
    assert "triage: refuted=1, verified=0, unverifiable=0" in _build_directory_report(directory)

def test_fingerprint_uses_checkout_relative_source_key(tmp_path, monkeypatch) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(checkout)
    absolute = _finalize(
        source_file=str(checkout / "src" / "example.py"),
        verification_violations=["counterexample"],
    )
    relative = _finalize(
        source_file="src/example.py",
        verification_violations=["counterexample"],
    )
    assert absolute.findings[0]["fingerprint"] == relative.findings[0]["fingerprint"]
