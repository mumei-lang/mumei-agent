"""Route tests for ``evidence-check-list``: declared Core list-envelope
representation check through the C11 attempt lifecycle — the envelope
bytes reach the child via the runner's stdin feed."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from agent.evidence_check_list import (
    LIST_SCHEMA_VERSION,
    build_check_list_parser,
    main_check_list,
)

LIST_DIAGNOSTIC = {
    "schema_version": "mumei.evidence-representation-check/v1",
    "evidence_schema_version": LIST_SCHEMA_VERSION,
    "representation": "valid",
    "acceptance": "not_evaluated",
    "checks_not_performed": [
        "claim_truth",
        "file_identity",
        "freshness",
        "producer_authenticity",
        "semantic_correspondence",
        "artifact_semantics",
        "cross_record_consistency",
    ],
}

SOURCE = (
    "atom main() -> i64 requires: true; "
    "ensures: result == 0; body: { 0 };\n"
)

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


def _diagnostic_json(record_count: int) -> str:
    return json.dumps({**LIST_DIAGNOSTIC, "record_count": record_count})


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


def _write_core(tmp_path: Path, expect_sha: str,
                check_exit: int = 0, record_count: int = 2) -> Path:
    """Stub `mumei` executable: `evidence check-list --stdin --json`
    reads the fed bytes, emits the list diagnostic when their sha256
    matches `expect_sha`, otherwise exits `check_exit` with no
    diagnostic."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check-list" ]; then\n'
        "    input_file=$(mktemp)\n"
        '    cat > "$input_file"\n'
        "    got=$(python3 -c '\n"
        "import hashlib,sys\n"
        "print(hashlib.sha256(open(sys.argv[1],\"rb\").read()).hexdigest())\n"
        "' \"$input_file\")\n"
        '    rm -f "$input_file"\n'
        f'    if [ "$got" = "{expect_sha}" ]; then\n'
        f"        printf %s '{_diagnostic_json(record_count)}'\n"
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
        code = main_check_list(build_check_list_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_valid_envelope_selects_and_reports_representation(
    tmp_path, capsys
):
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(tmp_path, expect_sha=sha)
    code, out, err = _run(capsys, _args(core, evidence))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert (
        report["schema_version"] == "mumei.evidence-check-list-report/v1"
    )
    assert report["representation"] == "valid"
    assert report["record_count"] == 2
    assert report["checks_not_performed"] == list(
        LIST_DIAGNOSTIC["checks_not_performed"]
    )
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )


def test_rejected_envelope_claims_nothing(tmp_path, capsys):
    """Core exits 1 with no diagnostic — lineage only, no outcome."""
    evidence = _write_evidence(tmp_path)
    core = _write_core(tmp_path, expect_sha="f" * 64, check_exit=1)
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert "representation" not in report
    assert "checks_not_performed" not in report
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
        'if [ "$1" = "evidence" ] && [ "$2" = "check-list" ]; then\n'
        "    cat > /dev/null\n"
        '    printf %s \'{"schema_version":"something-else/v9"}\'\n'
        "    exit 0\n"
        "fi\nexit 2\n"
    )
    core.chmod(0o755)
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert "representation" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report


def test_exit_zero_single_record_diagnostic_selects_nothing(
    tmp_path, capsys
):
    """A single-record diagnostic (no record_count, v1 schema) is not
    the list diagnostic — it binds nothing."""
    evidence = _write_evidence(tmp_path)
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check-list" ]; then\n'
        "    cat > /dev/null\n"
        '    printf %s \'{"schema_version":"mumei.evidence-representation-check/v1","evidence_schema_version":"mumei.verification-evidence/v1","representation":"valid","acceptance":"not_evaluated","checks_not_performed":["claim_truth","file_identity","freshness","producer_authenticity","semantic_correspondence","artifact_semantics"]}\'\n'
        "    exit 0\n"
        "fi\nexit 2\n"
    )
    core.chmod(0o755)
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert "representation" not in report
    assert report["sequence"].get("selected_result") is None


def test_mid_run_envelope_drift_claims_no_outcome(tmp_path, capsys):
    """A child that mutates the declared envelope mid-run exits 0 —
    the exit applies to bytes outside the declared request."""
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check-list" ]; then\n'
        "    cat > /dev/null\n"
        f'    printf tampered > "{evidence}"\n'
        f"    printf %s '{_diagnostic_json(2)}'\n"
        "    exit 0\n"
        "fi\nexit 2\n"
    )
    core.chmod(0o755)
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "representation" not in report
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
    assert report["representation"] == "valid"


MUMEI_BIN = os.environ.get("MUMEI_BIN")


@pytest.mark.skipif(
    not MUMEI_BIN or not Path(MUMEI_BIN).exists(),
    reason="MUMEI_BIN does not point at a real mumei binary",
)
class TestRealCore:
    def _produce_envelope(self, tmp_path: Path) -> Path:
        """Mint a real record via verify-source, wrap it in the real
        list envelope."""
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
                    "evidence": [json.loads(out.stdout)],
                }
            )
        )
        return envelope

    def test_real_check_list_reports_valid(self, tmp_path, capsys):
        evidence = self._produce_envelope(tmp_path)
        code, out, _ = _run(
            capsys, _args(Path(MUMEI_BIN).resolve(), evidence)
        )
        assert code == 0
        report = json.loads(out)
        assert report["representation"] == "valid"
        assert report["record_count"] == 1
        assert report["candidate"]["schema_version"] == (
            "mumei.verifier-evidence-candidate/v1"
        )

    def test_real_check_list_rejects_bogus_bytes(self, tmp_path, capsys):
        evidence = _write_evidence(tmp_path, body='{"bogus":1}')
        code, out, _ = _run(
            capsys, _args(Path(MUMEI_BIN).resolve(), evidence)
        )
        assert code == 0
        report = json.loads(out)
        assert "representation" not in report
        assert report["sequence"].get("selected_result") is None
        assert report["normalized"]["exit_code"] == 1
