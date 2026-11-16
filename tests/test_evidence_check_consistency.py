"""Route tests for ``evidence-check-consistency``: declared Core
cross-record consistency check through the C11 attempt lifecycle —
the envelope bytes reach the child via the runner's stdin feed."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from agent.evidence_check_consistency import (
    LIST_SCHEMA_VERSION,
    build_check_consistency_parser,
    main_check_consistency,
)

CHECKS_NOT_PERFORMED = [
    "claim_truth",
    "file_identity",
    "freshness",
    "producer_authenticity",
    "semantic_correspondence",
    "artifact_semantics",
    "pin_correctness",
]


def _diagnostic(
    record_count: int = 2,
    consistent: bool = True,
    conflict_count: int = 0,
    conflicts: list | None = None,
) -> dict:
    return {
        "schema_version": "mumei.evidence-consistency-check/v1",
        "evidence_schema_version": LIST_SCHEMA_VERSION,
        "representation": "valid",
        "record_count": record_count,
        "consistent": consistent,
        "conflict_count": conflict_count,
        "conflicts": conflicts if conflicts is not None else [],
        "acceptance": "not_evaluated",
        "checks_not_performed": list(CHECKS_NOT_PERFORMED),
    }


def _diagnostic_json(**kwargs) -> str:
    return json.dumps(_diagnostic(**kwargs))


RECORD = {
    "schema_version": "mumei.verification-evidence/v1",
    "subject": {
        "id": "x",
        "kind": "mumei_source",
        "sha256": "0" * 64,
    },
    "specification": {"id": "s", "sha256": "1" * 64},
    "claims": [],
}


def _write_evidence(tmp_path: Path, body: str | None = None) -> Path:
    evidence = tmp_path / "saved-list.json"
    evidence.write_text(
        body
        if body is not None
        else json.dumps(
            {
                "schema_version": LIST_SCHEMA_VERSION,
                "evidence": [RECORD, RECORD],
            }
        )
    )
    return evidence


def _write_core(
    tmp_path: Path,
    expect_sha: str,
    check_exit: int = 0,
    diagnostic: str | None = None,
) -> Path:
    """Stub `mumei` executable: `evidence check-consistency --stdin
    --json` reads the fed bytes, emits `diagnostic` when their sha256
    matches `expect_sha`, otherwise exits `check_exit` with no
    diagnostic."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check-consistency" ]; then\n'
        "    input_file=$(mktemp)\n"
        '    cat > "$input_file"\n'
        "    got=$(python3 -c '\n"
        "import hashlib,sys\n"
        "print(hashlib.sha256(open(sys.argv[1],\"rb\").read()).hexdigest())\n"
        "' \"$input_file\")\n"
        '    rm -f "$input_file"\n'
        f'    if [ "$got" = "{expect_sha}" ]; then\n'
        f"        printf %s '{diagnostic if diagnostic is not None else _diagnostic_json()}'\n"
        "        exit 0\n"
        "    fi\n"
        f"    exit {check_exit}\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _args(core: Path, evidence: Path, extra=()):
    return [
        "--core", str(core),
        "--evidence", str(evidence),
        "--attempt-timeout", "30000",
        *extra,
    ]


def _run(capsys, argv):
    try:
        code = main_check_consistency(
            build_check_consistency_parser().parse_args(argv)
        )
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_consistent_envelope_selects_and_reports(tmp_path, capsys):
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(tmp_path, expect_sha=sha)
    code, out, err = _run(capsys, _args(core, evidence))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == (
        "mumei.evidence-check-consistency-report/v1"
    )
    assert report["representation"] == "valid"
    assert report["record_count"] == 2
    assert report["consistent"] is True
    assert report["conflict_count"] == 0
    assert report["conflicts"] == []
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )


def test_inconsistent_envelope_still_selects(tmp_path, capsys):
    """Conflicts found is still a completed check — the diagnostic is
    the contract, so `consistent: false` selects and reports."""
    conflicts = [{"index_a": 0, "index_b": 1, "field": "subject.kind"}]
    diagnostic = _diagnostic_json(
        consistent=False, conflict_count=1, conflicts=conflicts
    )
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(
        tmp_path, expect_sha=sha, diagnostic=diagnostic
    )
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["consistent"] is False
    assert report["conflict_count"] == 1
    assert report["conflicts"] == conflicts
    assert report["sequence"]["selected_result"] is not None


def test_rejected_envelope_claims_nothing(tmp_path, capsys):
    """Core exits 1 with no diagnostic — lineage only, no outcome."""
    evidence = _write_evidence(tmp_path)
    core = _write_core(tmp_path, expect_sha="f" * 64, check_exit=1)
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert "representation" not in report
    assert "consistent" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    assert report["normalized"]["exit_code"] == 1


def test_exit_zero_with_wrong_diagnostic_selects_nothing(
    tmp_path, capsys
):
    """A 0 exit whose stdout is not the known diagnostic binds nothing."""
    evidence = _write_evidence(tmp_path)
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check-consistency" ]; then\n'
        "    cat > /dev/null\n"
        '    printf %s \'{"schema_version":"something-else/v9"}\'\n'
        "    exit 0\n"
        "fi\nexit 2\n"
    )
    core.chmod(0o755)
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert "consistent" not in report
    assert report["sequence"].get("selected_result") is None


def test_internally_contradictory_diagnostic_selects_nothing(
    tmp_path, capsys
):
    """`consistent: true` with conflict_count 3 is not the contract —
    the validator cross-checks the variable fields."""
    diagnostic = _diagnostic_json(
        consistent=True,
        conflict_count=3,
        conflicts=[
            {"index_a": 0, "index_b": 1, "field": "subject.kind"},
            {"index_a": 0, "index_b": 1, "field": "method"},
            {"index_a": 0, "index_b": 1, "field": "subject.id"},
        ],
    )
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(
        tmp_path, expect_sha=sha, diagnostic=diagnostic
    )
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert "consistent" not in report
    assert report["sequence"].get("selected_result") is None


def test_unknown_conflict_field_selects_nothing(tmp_path, capsys):
    """A conflict naming a field outside the comparison vocabulary is
    not the known diagnostic."""
    diagnostic = _diagnostic_json(
        consistent=False,
        conflict_count=1,
        conflicts=[{"index_a": 0, "index_b": 1, "field": "result"}],
    )
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(
        tmp_path, expect_sha=sha, diagnostic=diagnostic
    )
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert "consistent" not in report


def test_mid_run_envelope_drift_claims_no_outcome(tmp_path, capsys):
    """A child that mutates the declared envelope mid-run exits 0 —
    the exit applies to bytes outside the declared request."""
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check-consistency" ]; then\n'
        "    cat > /dev/null\n"
        f'    printf tampered > "{evidence}"\n'
        f"    printf %s '{_diagnostic_json()}'\n"
        "    exit 0\n"
        "fi\nexit 2\n"
    )
    core.chmod(0o755)
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "consistent" not in report
    assert report["sequence"].get("selected_result") is None
    assert sha  # fixture sanity: the fed bytes matched pre-drift


def test_relative_and_missing_paths_are_static_errors(tmp_path, capsys):
    core = _write_core(tmp_path, expect_sha="0" * 64)
    evidence = _write_evidence(tmp_path)
    code, _, err = _run(
        capsys, _args(Path("rel/mumei"), evidence)
    )
    assert code == 1 and "absolute" in err
    code, _, err = _run(
        capsys, _args(core, tmp_path / "missing.json")
    )
    assert code == 1 and "cannot read" in err


def test_oversize_envelope_is_static_error(tmp_path, capsys):
    core = _write_core(tmp_path, expect_sha="0" * 64)
    evidence = tmp_path / "saved-list.json"
    evidence.write_text("x" * 65_537)
    code, _, err = _run(capsys, _args(core, evidence))
    assert code == 1 and "bound" in err


def test_output_may_not_overwrite_evidence(tmp_path, capsys):
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(tmp_path, expect_sha=sha)
    code, _, err = _run(
        capsys,
        _args(core, evidence, extra=("--output", str(evidence))),
    )
    assert code == 1 and "declared input" in err


def test_output_writes_report_file(tmp_path, capsys):
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(tmp_path, expect_sha=sha)
    out_path = tmp_path / "report.json"
    code, out, _ = _run(
        capsys,
        _args(core, evidence, extra=("--output", str(out_path))),
    )
    assert code == 0 and out == ""
    report = json.loads(out_path.read_text())
    assert report["consistent"] is True


MUMEI_BIN = os.environ.get("MUMEI_BIN")


@pytest.mark.skipif(
    not MUMEI_BIN or not Path(MUMEI_BIN).exists(),
    reason="MUMEI_BIN does not point at a real mumei binary",
)
class TestRealCore:
    def _produce_envelope(self, tmp_path: Path, records: int) -> Path:
        """Mint a real record via verify-source, wrap `records` copies
        in the real list envelope."""
        import subprocess

        src = tmp_path / "main.mm"
        src.write_text(
            "atom main() -> i64\n"
            "requires: true;\n"
            "ensures: result == 0;\n"
            "body: { 0 };\n"
        )
        out = subprocess.run(
            [MUMEI_BIN, "evidence", "verify-source", str(src), "--json"],
            capture_output=True,
            timeout=60,
        )
        assert out.returncode == 0, out.stderr
        envelope = tmp_path / "saved-list.json"
        envelope.write_text(
            json.dumps(
                {
                    "schema_version": LIST_SCHEMA_VERSION,
                    "evidence": [json.loads(out.stdout)] * records,
                }
            )
        )
        return envelope

    def test_real_check_consistency_reports_consistent(
        self, tmp_path, capsys
    ):
        evidence = self._produce_envelope(tmp_path, records=2)
        code, out, _ = _run(
            capsys, _args(Path(MUMEI_BIN).resolve(), evidence)
        )
        assert code == 0
        report = json.loads(out)
        assert report["consistent"] is True
        assert report["record_count"] == 2
        assert report["conflict_count"] == 0
        assert report["candidate"]["schema_version"] == (
            "mumei.verifier-evidence-candidate/v1"
        )

    def test_real_check_consistency_rejected_envelope_claims_nothing(
        self, tmp_path, capsys
    ):
        evidence = tmp_path / "saved-list.json"
        evidence.write_text('{"schema_version": "bogus/v9"}')
        code, out, _ = _run(
            capsys, _args(Path(MUMEI_BIN).resolve(), evidence)
        )
        assert code == 0
        report = json.loads(out)
        assert "consistent" not in report
        assert report["normalized"]["exit_code"] == 1
