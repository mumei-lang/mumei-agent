"""Route tests for ``evidence-check``: declared Core representation
check on a saved Evidence record through the C11 attempt lifecycle —
the record bytes reach the child via the runner's stdin feed."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from agent.core_evidence import _DIAGNOSTIC
from agent.evidence_check_route import (
    build_check_parser,
    main_check,
)

DIAGNOSTIC_JSON = json.dumps(_DIAGNOSTIC)

SOURCE = (
    "atom main() -> i64 requires: true; "
    "ensures: result == 0; body: { 0 };\n"
)


def _write_evidence(tmp_path: Path, body: str | None = None) -> Path:
    evidence = tmp_path / "saved.json"
    evidence.write_text(
        body
        if body is not None
        else json.dumps(
            {
                "schema_version": "mumei.verification-evidence/v1",
                "subject": {
                    "id": "x",
                    "kind": "mumei_source",
                    "sha256": "0" * 64,
                },
                "specification": {"id": "s", "sha256": "1" * 64},
                "claims": [],
            }
        )
    )
    return evidence


def _write_core(tmp_path: Path, expect_sha: str,
                check_exit: int = 0) -> Path:
    """Stub `mumei` executable: `evidence check --stdin --json` reads
    the fed bytes, emits the v1 diagnostic when their sha256 matches
    `expect_sha`, otherwise exits `check_exit` with no diagnostic."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
        "    input_file=$(mktemp)\n"
        '    cat > "$input_file"\n'
        "    got=$(python3 -c '\n"
        "import hashlib,sys\n"
        "print(hashlib.sha256(open(sys.argv[1],\"rb\").read()).hexdigest())\n"
        "' \"$input_file\")\n"
        '    rm -f "$input_file"\n'
        f'    if [ "$got" = "{expect_sha}" ]; then\n'
        f'        printf %s {json.dumps(DIAGNOSTIC_JSON)}\n'
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
        code = main_check(build_check_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_valid_record_selects_and_reports_representation(
    tmp_path, capsys
):
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(tmp_path, expect_sha=sha)
    code, out, err = _run(capsys, _args(core, evidence))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.evidence-check-report/v1"
    assert report["representation"] == "valid"
    assert report["checks_not_performed"] == list(
        _DIAGNOSTIC["checks_not_performed"]
    )
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )


def test_rejected_record_claims_nothing(tmp_path, capsys):
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
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
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
    assert sha  # (fixture sanity)


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


def test_oversize_evidence_is_static_error(tmp_path, capsys):
    core = _write_core(tmp_path, expect_sha="0" * 64)
    evidence = tmp_path / "saved.json"
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


MUMEI_BIN = os.environ.get("MUMEI_BIN")


@pytest.mark.skipif(
    not MUMEI_BIN or not Path(MUMEI_BIN).exists(),
    reason="MUMEI_BIN does not point at a real mumei binary",
)
class TestRealCore:
    def _produce_evidence(self, tmp_path: Path) -> Path:
        """Run the real Core's verify-source to mint a real record."""
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
        evidence = tmp_path / "saved.json"
        evidence.write_bytes(out.stdout)
        return evidence

    def test_real_check_reports_valid(self, tmp_path, capsys):
        evidence = self._produce_evidence(tmp_path)
        code, out, _ = _run(
            capsys, _args(Path(MUMEI_BIN).resolve(), evidence)
        )
        assert code == 0
        report = json.loads(out)
        assert report["representation"] == "valid"
        assert report["candidate"]["schema_version"] == (
            "mumei.verifier-evidence-candidate/v1"
        )

    def test_real_check_rejects_bogus_bytes(self, tmp_path, capsys):
        evidence = _write_evidence(tmp_path, body='{"bogus":1}')
        code, out, _ = _run(
            capsys, _args(Path(MUMEI_BIN).resolve(), evidence)
        )
        assert code == 0
        report = json.loads(out)
        assert "representation" not in report
        assert report["sequence"].get("selected_result") is None
        assert report["normalized"]["exit_code"] == 1


GATED_DIAGNOSTIC = dict(
    _DIAGNOSTIC,
    checks_performed=[
        "representation_gate",
        "declared_producer_identity",
    ],
)


def _write_gated_core(tmp_path: Path, expect_sha: str) -> Path:
    """Stub that emits the gated diagnostic when invoked with
    `--expected-adapter expected-id`, the ungated one without."""
    core = tmp_path / "mumei-stub-gated"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
        "    input_file=$(mktemp)\n"
        '    cat > "$input_file"\n'
        "    got=$(python3 -c '\n"
        "import hashlib,sys\n"
        "print(hashlib.sha256(open(sys.argv[1],\"rb\").read()).hexdigest())\n"
        "' \"$input_file\")\n"
        '    rm -f "$input_file"\n'
        f'    if [ "$got" = "{expect_sha}" ]; then\n'
        '        if [ "$5" = "--expected-adapter" ] '
        '&& [ "$6" = "expected-id" ]; then\n'
        f'            printf %s {json.dumps(json.dumps(GATED_DIAGNOSTIC))}\n'
        "            exit 0\n"
        "        fi\n"
        f'        printf %s {json.dumps(DIAGNOSTIC_JSON)}\n'
        "        exit 0\n"
        "    fi\n"
        "    exit 1\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def test_expected_adapter_gate_reports_declared_producer_identity(
    tmp_path, capsys
):
    """A gated run selects the gated diagnostic: checks_performed
    names declared_producer_identity while producer_authenticity stays
    not_performed."""
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_gated_core(tmp_path, expect_sha=sha)
    code, out, err = _run(
        capsys,
        _args(core, evidence, ("--expected-adapter", "expected-id")),
    )
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["representation"] == "valid"
    assert report["checks_performed"] == [
        "representation_gate",
        "declared_producer_identity",
    ]
    assert "producer_authenticity" in report["checks_not_performed"]
    assert report["sequence"]["selected_result"] is not None


def test_expected_adapter_binds_the_attempt_fingerprint(
    tmp_path, capsys
):
    """Gated and ungated requests are different request identities."""
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_gated_core(tmp_path, expect_sha=sha)
    _, out_a, _ = _run(capsys, _args(core, evidence))
    _, out_b, _ = _run(
        capsys,
        _args(core, evidence, ("--expected-adapter", "expected-id")),
    )
    fp_a = json.loads(out_a)["sequence"]["request_fingerprint"]
    fp_b = json.loads(out_b)["sequence"]["request_fingerprint"]
    assert fp_a != fp_b


def test_ungated_shape_on_a_gated_run_binds_nothing(tmp_path, capsys):
    """A gated request whose child emits the ungated diagnostic is not
    the accepted shape — nothing is claimed or selected."""
    evidence = _write_evidence(tmp_path)
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = _write_core(tmp_path, expect_sha=sha)
    code, out, _ = _run(
        capsys,
        _args(core, evidence, ("--expected-adapter", "expected-id")),
    )
    assert code == 0
    report = json.loads(out)
    assert "representation" not in report
    assert "checks_performed" not in report
    assert report["sequence"].get("selected_result") is None


def test_gated_shape_on_an_ungated_run_binds_nothing(tmp_path, capsys):
    """The reverse asymmetry: an ungated request must not accept the
    gated diagnostic either — the shape IS the contract."""
    evidence = _write_evidence(tmp_path)
    expect_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    core = tmp_path / "mumei-stub-always-gated"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
        "    input_file=$(mktemp)\n"
        '    cat > "$input_file"\n'
        "    got=$(python3 -c '\n"
        "import hashlib,sys\n"
        "print(hashlib.sha256(open(sys.argv[1],\"rb\").read()).hexdigest())\n"
        "' \"$input_file\")\n"
        '    rm -f "$input_file"\n'
        f'    if [ "$got" = "{expect_sha}" ]; then\n'
        f'        printf %s {json.dumps(json.dumps(GATED_DIAGNOSTIC))}\n'
        "        exit 0\n"
        "    fi\n"
        "    exit 1\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    code, out, _ = _run(capsys, _args(core, evidence))
    assert code == 0
    report = json.loads(out)
    assert "representation" not in report
    assert "checks_performed" not in report
    assert report["sequence"].get("selected_result") is None


def test_empty_expected_adapter_is_static_error(tmp_path, capsys):
    evidence = _write_evidence(tmp_path)
    core = _write_core(tmp_path, expect_sha="0" * 64)
    code, out, err = _run(
        capsys,
        _args(core, evidence, ("--expected-adapter", "")),
    )
    assert code == 1
    assert out == ""
    assert "--expected-adapter" in err
