"""Route tests for ``native-recheck``: declared Core native consumer
recheck through the C11 attempt lifecycle."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.native_recheck import (
    BUNDLE_MEMBERS,
    RECORD_FILE,
    build_recheck_parser,
    main_recheck,
)

REPORT = {
    "schema_version": "mumei.native-consumer-evidence/v1",
    "build_id": "a" * 64,
    "acceptance": "not_evaluated",
    "evidence": [],
}

SOURCE = (
    "atom main() -> i64 requires: true; "
    "ensures: result == 0; body: { 0 };\n"
)

BUILD_ID = "a" * 64


def _write_core(tmp_path: Path, recheck_exit: int = 0) -> Path:
    """Stub `mumei` executable: `native-bundle recheck-llvm` emits a
    fake consumer report (exit per `recheck_exit`)."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-llvm" ]; then\n'
        f"    exit_code={recheck_exit}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"        printf '%s' '{json.dumps(REPORT)}'\n"
        "    fi\n"
        '    exit "$exit_code"\n'
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _write_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / RECORD_FILE).write_text(json.dumps({"record": True}))
    for name in BUNDLE_MEMBERS:
        (bundle / name).write_text(f"bytes of {name}")
    return bundle


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "native-source.mm"
    source.write_text(SOURCE)
    return source


def _run(capsys, argv):
    try:
        code = main_recheck(build_recheck_parser().parse_args(argv))
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
        "--attempt-timeout", "30000",
        *extra,
    ]


def test_equivalent_recheck_selects_report(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.native-recheck-report/v1"
    assert report["recheck"] == "equivalent"
    assert report["sequence"]["selected_result"] is not None
    assert (
        report["candidate"]["schema_version"]
        == "mumei.verifier-evidence-candidate/v1"
    )
    assert "evidence_check" not in report
    assert "acceptance" not in report


def test_exit_one_publishes_lineage_without_claimed_outcome(
    tmp_path, capsys
):
    """Exit 1 conflates Different/UndefinedBehavior with every static
    failure — the route claims no outcome for it."""
    core = _write_core(tmp_path, recheck_exit=1)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "recheck" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    assert report["normalized"]["exit_code"] == 1


def test_inconclusive_recheck_records_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=3)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["recheck"] == "inconclusive"
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == 3


def test_unknown_exit_code_omits_recheck_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=2)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "recheck" not in report
    assert report["normalized"]["exit_code"] == 2


def test_mid_run_input_drift_claims_no_outcome(tmp_path, capsys):
    """A child that mutates a declared bundle member mid-run exits 0,
    but the exit code applies to bytes outside the declared request."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-llvm" ]; then\n'
        '    printf "tampered" > "$6/program.ll"\n'
        f"    printf '%s' '{json.dumps(REPORT)}'\n"
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
    assert "recheck" not in report
    assert "candidate" not in report
    assert report["sequence"].get("selected_result") is None


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
        *(bundle / name for name in BUNDLE_MEMBERS),
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


def test_missing_member_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    (bundle / "program.o").unlink()
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only route")
def test_cli_dispatch(tmp_path):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    result = subprocess.run(
        [
            sys.executable, "-m", "agent", "native-recheck",
            "--core", str(core),
            "--bundle", str(bundle),
            "--source", str(source),
            "--expected-build-id", BUILD_ID,
            "--attempt-timeout", "30000",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["recheck"] == "equivalent"


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
def test_real_core_rechecks_native_bundle_equivalent(
    tmp_path, capsys, real_core
):
    """End-to-end against the real Core: build a real native bundle,
    then recheck it through the route — a consistent bundle yields
    `equivalent` with a selected consumer-evidence candidate."""
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
    assert report["recheck"] == "equivalent"
    assert (
        report["candidate"]["schema_version"]
        == "mumei.verifier-evidence-candidate/v1"
    )


@pytest.mark.integration
def test_real_core_rejects_wrong_build_id(
    tmp_path, capsys, real_core
):
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
    assert "recheck" not in report
    assert report["normalized"]["exit_code"] == 1
    assert report["sequence"].get("selected_result") is None
