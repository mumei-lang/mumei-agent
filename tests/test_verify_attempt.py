"""Route tests for ``verify-attempt``: declared Core source-evidence
production through the C11 attempt lifecycle plus the live
representation check."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.verify_attempt import build_attempt_parser, main_attempt

DIAGNOSTIC = {
    "schema_version": "mumei.evidence-representation-check/v1",
    "evidence_schema_version": "mumei.verification-evidence/v1",
    "representation": "valid",
    "acceptance": "not_evaluated",
    "checks_not_performed": [
        "claim_truth",
        "file_identity",
        "freshness",
        "producer_authenticity",
        "semantic_correspondence",
        "artifact_semantics",
    ],
}

EVIDENCE = {
    "schema_version": "mumei.verification-evidence/v1",
    "record": {"fake": True},
}

SOURCE = (
    "atom main() requires: true; ensures: result == 0; body: { 0 };\n"
)


def _write_core(tmp_path: Path, verify_exit: int = 0) -> Path:
    """Stub `mumei` executable: `evidence verify-source` emits a fake
    evidence record (exit per `verify_exit`), `evidence check` emits the
    known v1 diagnostic."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "verify-source" ]; then\n'
        f"    exit_code={verify_exit}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"        printf '%s' '{json.dumps(EVIDENCE)}'\n"
        "    fi\n"
        '    exit "$exit_code"\n'
        'elif [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
        "    cat >/dev/null\n"
        f"    printf '%s' '{json.dumps(DIAGNOSTIC)}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _write_source(tmp_path: Path) -> Path:
    src = tmp_path / "fixture.mm"
    src.write_text(SOURCE)
    return src


def _run(capsys, argv):
    try:
        code = main_attempt(build_attempt_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def _args(core: Path, source: Path, extra=()):
    return [
        "--core", str(core),
        "--source", str(source),
        "--attempt-timeout", "30000",
        *extra,
    ]


def test_selected_evidence_is_checked_and_accepted(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.verify-attempt-report/v1"
    seq = report["sequence"]
    assert seq["selected_result"] is not None
    check = report["evidence_check"]
    assert (
        check["schema_version"] == "mumei.verifier-evidence-check/v1"
    )
    assert check["outcome"] == "valid"
    acceptance = report["acceptance"]
    assert (
        acceptance["schema_version"]
        == "mumei.evidence-check-acceptance/v1"
    )
    assert acceptance["accepted"] is True
    assert acceptance["candidate_match"] is True


def test_refuted_run_publishes_lineage_without_selection(
    tmp_path, capsys
):
    core = _write_core(tmp_path, verify_exit=1)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, source))
    assert code == 0
    report = json.loads(out)
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    assert "evidence_check" not in report
    assert "acceptance" not in report
    assert report["normalized"]["exit_code"] == 1


def test_relative_core_path_rejected_before_run(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    rel = os.path.relpath(core)
    code, out, _ = _run(capsys, _args(rel, source))
    assert code == 1
    assert "selected_result" not in out


def test_output_may_not_overwrite_declared_source(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(
        capsys, _args(core, source, extra=["--output", str(source)])
    )
    assert code == 1
    assert source.read_text() == SOURCE


def test_oversize_source_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    src = tmp_path / "big.mm"
    src.write_text("x" * 70_000)
    code, out, _ = _run(capsys, _args(core, src))
    assert code == 1


def test_failing_check_records_failed_outcome(tmp_path, capsys):
    core = _write_core(tmp_path)
    # Make `evidence check` produce garbage -> recorded outcome "failed",
    # acceptance not accepted.
    text = core.read_text().replace(
        f"printf '%s' '{json.dumps(DIAGNOSTIC)}'",
        "printf 'not-json'",
    )
    core.write_text(text)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, source))
    assert code == 0
    report = json.loads(out)
    assert report["evidence_check"]["outcome"] == "failed"
    assert report["acceptance"]["accepted"] is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only route")
def test_cli_dispatch(tmp_path):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    result = subprocess.run(
        [
            sys.executable, "-m", "agent", "verify-attempt",
            "--core", str(core),
            "--source", str(source),
            "--attempt-timeout", "30000",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["acceptance"]["accepted"] is True
