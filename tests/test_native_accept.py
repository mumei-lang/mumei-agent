"""Route tests for ``native-accept``: declared Core native artifact
acceptance through the C11 attempt lifecycle."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.native_accept import (
    FILE_MEMBERS,
    RECORD_FILE,
    build_accept_parser,
    main_accept,
)

DESCRIPTOR = {
    "schema_version": "mumei.native-evidence-acceptance/v1",
    "acceptance": "evaluated",
    "accepted": True,
    "scope": "test",
    "checks_performed": [],
    "checks_not_performed": [],
}

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

BUILD_ID = "a" * 64


def _write_core(tmp_path: Path, accept_exit: int = 0) -> Path:
    """Stub `mumei` executable: `native-bundle accept-artifact` emits a
    fake acceptance descriptor (exit per `accept_exit`)."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "accept-artifact" ]; then\n'
        f"    exit_code={accept_exit}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"        printf '%s' '{json.dumps(DESCRIPTOR)}'\n"
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


def _run(capsys, argv):
    try:
        code = main_accept(build_accept_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def _args(core: Path, bundle: Path, source: Path, extra=()):
    return [
        "--core", str(core),
        "--bundle", str(bundle),
        "--source", str(source),
        "--expected-build-id", BUILD_ID,
        "--attempt-timeout", "60000",
        *extra,
    ]


def test_accepted_run_selects_descriptor(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.native-accept-report/v1"
    assert report["acceptance"] == "accepted"
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
    # The descriptor is anonymous — no verifier-evidence handoff.
    assert "candidate" not in report
    assert "recheck" not in report


def test_exit_one_publishes_lineage_without_claimed_outcome(
    tmp_path, capsys
):
    """Exit 1 conflates a failed reproduction with every static
    failure — the route claims no outcome for it."""
    core = _write_core(tmp_path, accept_exit=1)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "acceptance" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    assert report["normalized"]["exit_code"] == 1


def test_inconclusive_accept_records_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, accept_exit=3)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["acceptance"] == "inconclusive"
    assert "discharged_checks" not in report
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == 3


def test_unknown_exit_code_omits_acceptance_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, accept_exit=2)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "acceptance" not in report
    assert report["normalized"]["exit_code"] == 2


def test_mid_run_input_drift_claims_no_outcome(tmp_path, capsys):
    """A child that mutates a declared bundle member mid-run exits 0,
    but the exit code applies to bytes outside the declared request."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "accept-artifact" ]; then\n'
        '    printf "tampered" > "$6/program.ll"\n'
        f"    printf '%s' '{json.dumps(DESCRIPTOR)}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "discharged_checks" not in report
    assert "acceptance" not in report
    assert report["sequence"].get("selected_result") is None


def test_multifile_members_enumerated_and_fingerprinted(tmp_path, capsys):
    """A multifile record's `sources` members join the declared set —
    tampering with one mid-run is observed as drift."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "accept-artifact" ]; then\n'
        '    printf "tampered" > "$6/sources/dep.mm"\n'
        f"    printf '%s' '{json.dumps(DESCRIPTOR)}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "acceptance" not in report


def test_mid_run_record_swap_declaring_new_member_is_drift(tmp_path, capsys):
    """A record swapped mid-run may declare members the pre-run
    enumeration never fingerprinted — the drift check re-enumerates
    from the current record so the member-set change is caught."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "accept-artifact" ]; then\n'
        f"    printf '%s' '{json.dumps(MULTIFILE_RECORD)}' > \"$6/{RECORD_FILE}\"\n"
        "    mkdir -p \"$6/sources/sub\"\n"
        '    printf "atom body" > "$6/sources/app.mm"\n'
        '    printf "atom body" > "$6/sources/dep.mm"\n'
        '    printf "atom body" > "$6/sources/sub/extra.mm"\n'
        f"    printf '%s' '{json.dumps(DESCRIPTOR)}'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    # Pre-run record declares no sources at all.
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "acceptance" not in report


def test_record_swap_inside_validation_window_is_drift(tmp_path, capsys, monkeypatch):
    """A record swapped between member enumeration and fingerprinting
    declares members the fingerprint never bound. Without re-enumerating
    the post-run member set the run's consumed-but-unbound bytes pass
    undetected — the drift check must enumerate the CURRENT record."""
    import agent.native_accept as native_accept

    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)  # record declares no `sources`
    source = _write_source(tmp_path)

    original = native_accept._attempt_fingerprint
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
        native_accept, "_attempt_fingerprint", swap_then_fingerprint
    )
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "acceptance" not in report


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
    code, _, err = _run(capsys, _args(core, bundle, source))
    assert code == 1
    assert "Traceback" not in err


def test_multifile_bundle_accepted_clean(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["acceptance"] == "accepted"


def test_invalid_sources_member_rejected(tmp_path, capsys):
    """A hand-crafted record declaring a member outside the grammar
    fails closed before any attempt — `../` never joins a path."""
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    bundle = _write_bundle(tmp_path)
    for member in ("../outside.mm", "sub//dep.mm", "/abs.mm", "a\\b.mm"):
        record = dict(RECORD)
        record["sources"] = {member: {}}
        (bundle / RECORD_FILE).write_text(json.dumps(record))
        code, _, _ = _run(capsys, _args(core, bundle, source))
        assert code == 1, member


def test_unknown_files_key_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    record = dict(RECORD)
    record["files"] = {**RECORD["files"], "mystery": {}}
    bundle = _write_bundle(tmp_path, record=record)
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_unparseable_record_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    (bundle / RECORD_FILE).write_text("{not json")
    source = _write_source(tmp_path)
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_relative_core_path_rejected_before_run(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    rel = os.path.relpath(core)
    code, out, _ = _run(capsys, _args(rel, bundle, source))
    assert code == 1
    assert "selected_result" not in out


def test_non_directory_bundle_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = tmp_path / "bundle"
    bundle.write_text("not a directory")
    source = _write_source(tmp_path)
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_invalid_build_id_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    argv = _args(core, bundle, source)
    argv[argv.index("--expected-build-id") + 1] = "not-a-sha256"
    code, _, _ = _run(capsys, argv)
    assert code == 1


def test_output_may_not_overwrite_declared_inputs(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    for declared in (
        bundle / RECORD_FILE,
        *(bundle / name for name in FILE_MEMBERS.values()),
        source,
    ):
        code, out, _ = _run(
            capsys, _args(core, bundle, source, extra=["--output", str(declared)])
        )
        assert code == 1
    assert (bundle / "program.ll").read_text() == "bytes of program.ll"


def test_oversize_source_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    source.write_text("x" * 70_000)
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_oversize_record_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    (bundle / RECORD_FILE).write_text("x" * 1_100_000)
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_oversize_source_member_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    (bundle / "sources" / "dep.mm").write_text("x" * 70_000)
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_missing_member_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    (bundle / "program.o").unlink()
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_missing_source_member_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    (bundle / "sources" / "dep.mm").unlink()
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only route")
def test_cli_dispatch(tmp_path):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    result = subprocess.run(
        [
            sys.executable, "-m", "agent", "native-accept",
            "--core", str(core),
            "--bundle", str(bundle),
            "--source", str(source),
            "--expected-build-id", BUILD_ID,
            "--attempt-timeout", "60000",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["acceptance"] == "accepted"


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
def test_real_core_accepts_native_bundle(tmp_path, capsys, real_core):
    """End-to-end against the real Core: build a real native bundle,
    then accept its artifact through the route — a consistent bundle
    yields `accepted` with the descriptor bound in the lineage."""
    source = tmp_path / "native-source.mm"
    source.write_text(SOURCE)
    bundle = tmp_path / "bundle"
    built = subprocess.run(
        [real_core, "native-bundle", "build", str(source), "-o", str(bundle)],
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
    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, _ = _run(capsys, argv)
    assert code == 0
    report = json.loads(out)
    assert report["acceptance"] == "accepted"
    assert "candidate" not in report


@pytest.mark.integration
def test_real_core_rejects_wrong_build_id(tmp_path, capsys, real_core):
    """A wrong expected-build-id fails the pinned-record gate — exit 1,
    the ambiguous code: no claimed outcome, no selection."""
    source = tmp_path / "native-source.mm"
    source.write_text(SOURCE)
    bundle = tmp_path / "bundle"
    built = subprocess.run(
        [real_core, "native-bundle", "build", str(source), "-o", str(bundle)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    _require_bundle(built)
    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = "b" * 64
    code, out, _ = _run(capsys, argv)
    assert code == 0
    report = json.loads(out)
    assert "acceptance" not in report
    assert report["normalized"]["exit_code"] == 1
    assert report["sequence"].get("selected_result") is None
