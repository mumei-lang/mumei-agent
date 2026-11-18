"""Route tests for ``verify-recheck``: declared Core source-evidence
recheck through the C11 attempt lifecycle."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.verify_recheck import build_recheck_parser, main_recheck

DIAGNOSTIC = {
    "schema_version": "mumei.source-evidence-recheck/v1",
    "evidence_schema_version": "mumei.verification-evidence/v1",
    # Real `recheck-source` consistent diagnostics carry the saved
    # record's fingerprint since the Core `evidence_fingerprint`
    # change; the stub emits a fake sentinel for the same shape.
    "evidence_fingerprint": "00" * 32,
    "recheck": "consistent",
}

EVIDENCE = {
    "schema_version": "mumei.verification-evidence/v1",
    "record": {"fake": True},
}

SOURCE = (
    "atom main() requires: true; ensures: result == 0; body: { 0 };\n"
)


def _write_core(tmp_path: Path, recheck_exit: int = 0) -> Path:
    """Stub `mumei` executable: `evidence recheck-source` emits a fake
    diagnostic (exit per `recheck_exit`)."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "recheck-source" ]; then\n'
        f"    exit_code={recheck_exit}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"        printf '%s' '{json.dumps(DIAGNOSTIC)}'\n"
        "    fi\n"
        '    exit "$exit_code"\n'
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    evidence = tmp_path / "saved.json"
    evidence.write_text(json.dumps(EVIDENCE))
    source = tmp_path / "fixture.mm"
    source.write_text(SOURCE)
    return evidence, source


def _run(capsys, argv):
    try:
        code = main_recheck(build_recheck_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def _args(core: Path, evidence: Path, source: Path, extra=()):
    return [
        "--core", str(core),
        "--evidence", str(evidence),
        "--source", str(source),
        "--attempt-timeout", "30000",
        *extra,
    ]


def test_consistent_recheck_selects_diagnostic(tmp_path, capsys):
    core = _write_core(tmp_path)
    evidence, source = _write_inputs(tmp_path)
    code, out, err = _run(capsys, _args(core, evidence, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.verify-recheck-report/v1"
    assert report["recheck"] == "consistent"
    assert report["sequence"]["selected_result"] is not None
    assert (
        report["candidate"]["schema_version"]
        == "mumei.verifier-evidence-candidate/v1"
    )
    assert "evidence_check" not in report
    assert "acceptance" not in report
    assert report["discharged_checks"] == [
        "claim_truth",
        "freshness",
        "semantic_correspondence",
    ]
    assert report["checks_not_performed"] == [
        "artifact_semantics",
        "file_identity",
        "producer_authenticity",
    ]


def test_mid_run_input_drift_claims_no_outcome(tmp_path, capsys):
    """A child that mutates a declared input mid-run exits 0, but the
    exit code applies to bytes outside the declared request: no
    selection, no claimed outcome, drift surfaced."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "recheck-source" ]; then\n'
        '    printf "tampered" > "$3"\n'
        f"    printf '%s' '{json.dumps(DIAGNOSTIC)}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    evidence, source = _write_inputs(tmp_path)
    code, out, _ = _run(capsys, _args(core, evidence, source))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "recheck" not in report
    assert "discharged_checks" not in report
    assert "candidate" not in report
    assert report["sequence"].get("selected_result") is None


def test_exit_one_publishes_lineage_without_claimed_outcome(
    tmp_path, capsys
):
    """Exit 1 conflates Refuted with every static failure (read,
    UTF-8, budget, Invalid/InconsistentSavedEvidence) — the route
    claims no outcome for it."""
    core = _write_core(tmp_path, recheck_exit=1)
    evidence, source = _write_inputs(tmp_path)
    code, out, _ = _run(capsys, _args(core, evidence, source))
    assert code == 0
    report = json.loads(out)
    assert "recheck" not in report
    assert "discharged_checks" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    assert report["normalized"]["exit_code"] == 1


def test_inconclusive_recheck_records_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=3)
    evidence, source = _write_inputs(tmp_path)
    code, out, _ = _run(capsys, _args(core, evidence, source))
    assert code == 0
    report = json.loads(out)
    assert report["recheck"] == "inconclusive"
    assert "discharged_checks" not in report
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == 3


def test_unknown_exit_code_omits_recheck_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=2)
    evidence, source = _write_inputs(tmp_path)
    code, out, _ = _run(capsys, _args(core, evidence, source))
    assert code == 0
    report = json.loads(out)
    assert "recheck" not in report
    assert report["normalized"]["exit_code"] == 2


def test_relative_core_path_rejected_before_run(tmp_path, capsys):
    core = _write_core(tmp_path)
    evidence, source = _write_inputs(tmp_path)
    rel = os.path.relpath(core)
    code, out, _ = _run(capsys, _args(rel, evidence, source))
    assert code == 1
    assert "selected_result" not in out


def test_output_may_not_overwrite_declared_inputs(tmp_path, capsys):
    core = _write_core(tmp_path)
    evidence, source = _write_inputs(tmp_path)
    for declared in (evidence, source):
        code, out, _ = _run(
            capsys, _args(core, evidence, source, extra=["--output", str(declared)])
        )
        assert code == 1
    assert evidence.read_text() == json.dumps(EVIDENCE)
    assert source.read_text() == SOURCE


def test_oversize_evidence_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    evidence, source = _write_inputs(tmp_path)
    evidence.write_text("x" * 70_000)
    code, out, _ = _run(capsys, _args(core, evidence, source))
    assert code == 1


def test_oversize_source_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    evidence, source = _write_inputs(tmp_path)
    source.write_text("x" * 70_000)
    code, out, _ = _run(capsys, _args(core, evidence, source))
    assert code == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only route")
def test_cli_dispatch(tmp_path):
    core = _write_core(tmp_path)
    evidence, source = _write_inputs(tmp_path)
    result = subprocess.run(
        [
            sys.executable, "-m", "agent", "verify-recheck",
            "--core", str(core),
            "--evidence", str(evidence),
            "--source", str(source),
            "--attempt-timeout", "30000",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["recheck"] == "consistent"


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


@pytest.mark.integration
def test_real_core_rechecks_saved_evidence_consistent(
    tmp_path, capsys, real_core
):
    """End-to-end against the real Core: produce fresh evidence with
    `evidence verify-source`, then recheck it — the same budgets must
    yield `consistent`."""
    source = tmp_path / "id_fn.mm"
    source.write_text(ESTABLISHED_SOURCE)
    produced = subprocess.run(
        [
            real_core, "evidence", "verify-source", str(source),
            "--json", "--solver-timeout", "5000",
            "--solver-resource-limit", "1000000",
        ],
        capture_output=True,
        timeout=60,
    )
    assert produced.returncode == 0, produced.stderr
    evidence = tmp_path / "saved.json"
    evidence.write_bytes(produced.stdout)
    code, out, err = _run(
        capsys, _args(Path(real_core), evidence, source)
    )
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["recheck"] == "consistent"
    assert report["sequence"]["selected_result"] is not None


@pytest.mark.integration
def test_real_core_recheck_detects_tampered_evidence(
    tmp_path, capsys, real_core
):
    """A saved record whose spec hash no longer matches the source's
    fresh query is rejected (InconsistentSavedEvidence — exit 1, the
    ambiguous code) — the freshness story this route exists for."""
    source = tmp_path / "id_fn.mm"
    source.write_text(ESTABLISHED_SOURCE)
    produced = subprocess.run(
        [
            real_core, "evidence", "verify-source", str(source),
            "--json", "--solver-timeout", "5000",
            "--solver-resource-limit", "1000000",
        ],
        capture_output=True,
        timeout=60,
    )
    assert produced.returncode == 0, produced.stderr
    record = json.loads(produced.stdout)
    record["specification"]["sha256"] = "0" * 64
    evidence = tmp_path / "saved.json"
    evidence.write_text(json.dumps(record))
    code, out, _ = _run(
        capsys, _args(Path(real_core), evidence, source)
    )
    assert code == 0
    report = json.loads(out)
    # Core exits 1 for InconsistentSavedEvidence — the ambiguous code,
    # so no claimed outcome; detection still surfaces as exit 1 with
    # no selection.
    assert "recheck" not in report
    assert report["normalized"]["exit_code"] == 1
    assert report["sequence"].get("selected_result") is None
