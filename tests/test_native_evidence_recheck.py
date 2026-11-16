"""Route tests for ``native-evidence-recheck``: declared saved
consumer-Evidence replay through the C11 attempt lifecycle."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.native_bundle import (
    FILE_MEMBERS,
    MAX_EVIDENCE_BYTES,
    RECORD_FILE,
)
from agent.native_evidence_recheck import (
    build_evidence_recheck_parser,
    main_evidence_recheck,
)

CONFIRM = "Saved native Evidence consistent with fresh checks.\n"

RECORD = {
    "schema": "mumei.native-bundle/v1",
    "files": {key: {} for key in FILE_MEMBERS},
}

MULTIFILE_RECORD = {
    "schema": "mumei.native-multifile-bundle/v1",
    "files": {key: {} for key in FILE_MEMBERS},
    "sources": {"app.mm": {}, "dep.mm": {}, "sub/extra.mm": {}},
}

SOURCE = (
    "atom main() -> i64 requires: true; "
    "ensures: result == 0; body: { 0 };\n"
)

EVIDENCE = {
    "schema_version": "mumei.native-consumer-evidence/v1",
    "records": [],
}

BUILD_ID = "a" * 64


def _write_core(tmp_path: Path, recheck_exit: int = 0) -> Path:
    """Stub `mumei` executable: `native-bundle recheck-evidence`
    prints a confirmation line (exit per `recheck_exit`)."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-evidence" ]; then\n'
        f"    exit_code={recheck_exit}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"        printf '%s' '{CONFIRM}'\n"
        "    fi\n"
        '    exit "$exit_code"\n'
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _write_bundle(tmp_path: Path, record: dict = RECORD) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / RECORD_FILE).write_text(json.dumps(record))
    for name in FILE_MEMBERS.values():
        (bundle / name).write_text(f"bytes of {name}")
    sources = record.get("sources") or {}
    for member in sources:
        member_path = bundle / "sources" / member
        member_path.parent.mkdir(parents=True, exist_ok=True)
        member_path.write_text(f"atom source of {member}")
    return bundle


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "native-source.mm"
    source.write_text(SOURCE)
    return source


def _write_evidence(tmp_path: Path) -> Path:
    evidence = tmp_path / "saved-evidence.json"
    evidence.write_text(json.dumps(EVIDENCE))
    return evidence


def _run(capsys, argv):
    try:
        code = main_evidence_recheck(
            build_evidence_recheck_parser().parse_args(argv)
        )
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def _args(core: Path, bundle: Path, source: Path, evidence: Path, extra=()):
    return [
        "--core", str(core),
        "--bundle", str(bundle),
        "--source", str(source),
        "--evidence", str(evidence),
        "--expected-build-id", BUILD_ID,
        "--attempt-timeout", "60000",
        *extra,
    ]


def test_consistent_run_selects_confirmation(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, err = _run(
        capsys, _args(core, bundle, source, evidence)
    )
    assert code == 0 and err == ""
    report = json.loads(out)
    assert (
        report["schema_version"]
        == "mumei.native-evidence-recheck-report/v1"
    )
    assert report["evidence_recheck"] == "consistent"
    assert report["sequence"]["selected_result"] is not None
    assert report["discharged_checks"] == [
        "artifact_semantics",
        "claim_truth",
    ]
    assert report["checks_not_performed"] == [
        "file_identity",
        "freshness",
        "producer_authenticity",
        "semantic_correspondence",
    ]
    # The saved envelope is the replayed input — no handoff.
    assert "candidate" not in report
    assert "recheck" not in report


def test_exit_one_publishes_lineage_without_claimed_outcome(
    tmp_path, capsys
):
    """Exit 1 conflates a saved-vs-fresh mismatch with every static
    failure — the route claims no outcome for it."""
    core = _write_core(tmp_path, recheck_exit=1)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert "evidence_recheck" not in report
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == 1


def test_inconclusive_recheck_records_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=3)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["evidence_recheck"] == "inconclusive"
    assert "discharged_checks" not in report
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == 3


def test_unknown_exit_code_omits_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=2)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert "evidence_recheck" not in report
    assert report["normalized"]["exit_code"] == 2


def test_mid_run_member_drift_claims_no_outcome(tmp_path, capsys):
    """A child that mutates a declared bundle member mid-run exits 0,
    but the exit code applies to bytes outside the declared request."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-evidence" ]; then\n'
        '    printf "tampered" > "$5/program.ll"\n'
        f"    printf '%s' '{CONFIRM}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "discharged_checks" not in report
    assert "evidence_recheck" not in report
    assert report["sequence"].get("selected_result") is None


def test_mid_run_evidence_drift_claims_no_outcome(tmp_path, capsys):
    """The saved envelope is a declared input too — mutating it
    mid-run is drift."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-evidence" ]; then\n'
        '    printf "tampered" > "$7"\n'
        f"    printf '%s' '{CONFIRM}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "evidence_recheck" not in report


def test_multifile_members_enumerated_and_fingerprinted(tmp_path, capsys):
    """A multifile record's `sources` members join the declared set —
    tampering with one mid-run is observed as drift."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-evidence" ]; then\n'
        '    printf "tampered" > "$5/sources/dep.mm"\n'
        f"    printf '%s' '{CONFIRM}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "evidence_recheck" not in report


def test_mid_run_record_swap_declaring_new_member_is_drift(tmp_path, capsys):
    """A record swapped mid-run may declare members the pre-run
    enumeration never fingerprinted — the drift check re-enumerates
    from the current record so the member-set change is caught."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-evidence" ]; then\n'
        f"    printf '%s' '{json.dumps(MULTIFILE_RECORD)}' > \"$5/{RECORD_FILE}\"\n"
        "    mkdir -p \"$5/sources/sub\"\n"
        '    printf "atom body" > "$5/sources/app.mm"\n'
        '    printf "atom body" > "$5/sources/dep.mm"\n'
        '    printf "atom body" > "$5/sources/sub/extra.mm"\n'
        f"    printf '%s' '{CONFIRM}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    # Pre-run record declares no sources at all.
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "evidence_recheck" not in report


def test_record_swap_inside_validation_window_is_drift(
    tmp_path, capsys, monkeypatch
):
    """A record swapped between member enumeration and fingerprinting
    declares members the fingerprint never bound. Without re-enumerating
    the post-run member set the run's consumed-but-unbound bytes pass
    undetected — the drift check must enumerate the CURRENT record."""
    import agent.native_evidence_recheck as route

    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)  # record declares no `sources`
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)

    original = route._attempt_fingerprint
    swapped = {"done": False}

    def swap_then_fingerprint(args, members):
        if not swapped["done"]:
            swapped["done"] = True
            (bundle / RECORD_FILE).write_text(json.dumps(MULTIFILE_RECORD))
            (bundle / "sources" / "sub").mkdir(parents=True)
            for member in MULTIFILE_RECORD["sources"]:
                (bundle / "sources" / member).write_text("atom body")
        return original(args, members)

    monkeypatch.setattr(
        route, "_attempt_fingerprint", swap_then_fingerprint
    )
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "evidence_recheck" not in report


def test_multifile_bundle_recheck_consistent(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 0
    report = json.loads(out)
    assert report["evidence_recheck"] == "consistent"


def test_evidence_over_input_bound_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = tmp_path / "saved-evidence.json"
    evidence.write_bytes(b"x" * (MAX_EVIDENCE_BYTES + 1))
    code, _, err = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 1
    assert "exceeds the Core input bound" in err


def test_missing_evidence_is_static_error(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    missing = tmp_path / "absent.json"
    code, _, err = _run(capsys, _args(core, bundle, source, missing))
    assert code == 1
    assert "cannot read declared input" in err


def test_output_may_not_overwrite_evidence(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, _, err = _run(
        capsys,
        _args(core, bundle, source, evidence, ["--output", str(evidence)]),
    )
    assert code == 1
    assert "declared input" in err


def test_output_may_not_overwrite_sources_member(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    member = bundle / "sources" / "dep.mm"
    code, _, err = _run(
        capsys,
        _args(core, bundle, source, evidence, ["--output", str(member)]),
    )
    assert code == 1
    assert "declared input" in err


def test_relative_paths_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, _, err = _run(
        capsys,
        [
            "--core", "relative/mumei",
            "--bundle", str(bundle),
            "--source", str(source),
            "--evidence", str(evidence),
            "--expected-build-id", BUILD_ID,
        ],
    )
    assert code == 1
    assert "absolute path" in err


def test_deeply_nested_record_rejected_without_traceback(tmp_path, capsys):
    """json.loads raises RecursionError on ~1200-deep nesting — a
    static ValueError, not an unhandled traceback."""
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    depth = 2000
    (bundle / RECORD_FILE).write_text(
        '{"a":' * depth + "0" + "}" * depth
    )
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, _, err = _run(capsys, _args(core, bundle, source, evidence))
    assert code == 1
    assert "Traceback" not in err


def test_output_writes_report_file(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    out_path = tmp_path / "report.json"
    code, out, _ = _run(
        capsys,
        _args(core, bundle, source, evidence, ["--output", str(out_path)]),
    )
    assert code == 0 and out == ""
    report = json.loads(out_path.read_text())
    assert report["evidence_recheck"] == "consistent"


def test_attempt_timeout_bound(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, _, err = _run(
        capsys,
        [
            "--core", str(core),
            "--bundle", str(bundle),
            "--source", str(source),
            "--evidence", str(evidence),
            "--expected-build-id", BUILD_ID,
            "--attempt-timeout", "0",
        ],
    )
    assert code == 1
    assert "--attempt-timeout" in err


def test_invalid_build_id_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    evidence = _write_evidence(tmp_path)
    code, _, err = _run(
        capsys,
        [
            "--core", str(core),
            "--bundle", str(bundle),
            "--source", str(source),
            "--evidence", str(evidence),
            "--expected-build-id", "not-a-digest",
        ],
    )
    assert code == 1
    assert "sha256" in err


@pytest.fixture
def real_core():
    path = os.environ.get("MUMEI_BIN")
    if path and Path(path).is_absolute() and Path(path).is_file():
        return path
    found = shutil.which("mumei")
    if found:
        return found
    pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")


def _require_bundle(built: subprocess.CompletedProcess) -> None:
    """Skip only on the documented unsupported-host rejection; every
    other build failure is a genuine incompatibility the test must
    surface, not skip."""
    if built.returncode == 0:
        return
    if "unsupported host for first native profile" in built.stderr:
        pytest.skip("native-bundle build needs linux/x86_64")
    pytest.fail(f"native-bundle build failed: {built.stderr}")


@pytest.mark.integration
def test_real_core_saved_evidence_roundtrip(
    tmp_path, capsys, real_core
):
    """End-to-end against the real Core: build a real native bundle,
    emit the consumer envelope via `recheck-llvm --json`, then replay
    it through the route — a matching envelope yields `consistent`."""
    source = _write_source(tmp_path)
    bundle = tmp_path / "bundle"
    built = subprocess.run(
        [
            real_core,
            "native-bundle",
            "build",
            str(source),
            "-o",
            str(bundle),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    _require_bundle(built)
    build_id = next(
        line.split(":", 1)[1].strip()
        for line in built.stdout.splitlines()
        if line.startswith("Build ID:")
    )
    recheck = subprocess.run(
        [
            real_core,
            "native-bundle",
            "recheck-llvm",
            "--expected-build-id",
            build_id,
            "--json",
            str(bundle),
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert recheck.returncode == 0, recheck.stderr
    evidence = tmp_path / "saved.json"
    evidence.write_text(recheck.stdout)
    argv = _args(
        Path(real_core), bundle, source, evidence
    )
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["evidence_recheck"] == "consistent"


@pytest.mark.integration
def test_real_core_tampered_envelope_claims_no_outcome(
    tmp_path, capsys, real_core
):
    """A saved envelope that no longer matches the fresh recheck
    exits 1 — the ambiguous code: no claimed outcome, no selection."""
    source = _write_source(tmp_path)
    bundle = tmp_path / "bundle"
    built = subprocess.run(
        [
            real_core,
            "native-bundle",
            "build",
            str(source),
            "-o",
            str(bundle),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    _require_bundle(built)
    build_id = next(
        line.split(":", 1)[1].strip()
        for line in built.stdout.splitlines()
        if line.startswith("Build ID:")
    )
    recheck = subprocess.run(
        [
            real_core,
            "native-bundle",
            "recheck-llvm",
            "--expected-build-id",
            build_id,
            "--json",
            str(bundle),
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert recheck.returncode == 0, recheck.stderr
    evidence = tmp_path / "saved.json"
    payload = json.loads(recheck.stdout)
    payload["tampered"] = True
    evidence.write_text(json.dumps(payload))
    argv = _args(Path(real_core), bundle, source, evidence)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, _ = _run(capsys, argv)
    assert code == 0
    report = json.loads(out)
    assert "evidence_recheck" not in report
    assert report["normalized"]["exit_code"] == 1
