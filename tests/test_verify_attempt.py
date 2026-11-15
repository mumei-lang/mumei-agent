"""Route tests for ``verify-attempt``: declared Core source-evidence
production through the C11 attempt lifecycle plus the live
representation check."""

import json
import os
import shutil
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


@pytest.fixture
def real_core():
    path = os.environ.get("MUMEI_BIN")
    if path and Path(path).is_absolute() and Path(path).is_file():
        return path
    found = shutil.which("mumei")
    if found:
        return found
    pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")


ESTABLISHED_SOURCE = (
    "atom id_fn(x: i64) -> i64\n"
    "requires: true;\n"
    "ensures: result == x;\n"
    "body: x;\n"
)

REFUTED_SOURCE = (
    "atom bad_fn(x: i64) -> i64\n"
    "requires: true;\n"
    "ensures: result == x + 1;\n"
    "body: x;\n"
)


@pytest.mark.integration
def test_real_core_produces_and_accepts_live_evidence(
    tmp_path, capsys, real_core
):
    """End-to-end against the real Core: `evidence verify-source` must
    accept our argv (solver budgets) and emit a real
    mumei.verification-evidence/v1 record that the same binary's
    `evidence check` then validates."""
    source = tmp_path / "id_fn.mm"
    source.write_text(ESTABLISHED_SOURCE)
    code, out, err = _run(
        capsys, _args(Path(real_core), source)
    )
    assert code == 0 and err == ""
    report = json.loads(out)
    candidate = report["candidate"]
    assert (
        candidate["schema_version"]
        == "mumei.verifier-evidence-candidate/v1"
    )
    # `accepted` here is only possible when the produced bytes were a
    # real mumei.verification-evidence/v1 record the same binary's
    # `evidence check` validated — the argv/shape compatibility a stub
    # cannot prove.
    assert report["evidence_check"]["outcome"] == "valid"
    acceptance = report["acceptance"]
    assert acceptance["accepted"] is True
    assert acceptance["candidate_match"] is True


@pytest.mark.integration
def test_real_core_refuted_source_publishes_lineage_only(
    tmp_path, capsys, real_core
):
    source = tmp_path / "bad_fn.mm"
    source.write_text(REFUTED_SOURCE)
    code, out, _ = _run(capsys, _args(Path(real_core), source))
    assert code == 0
    report = json.loads(out)
    assert report["normalized"]["exit_code"] == 1
    assert report["sequence"].get("selected_result") is None
    assert "acceptance" not in report
