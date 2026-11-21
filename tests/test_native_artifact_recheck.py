"""Route tests for ``native-artifact-recheck``: declared Core native
artifact recheck through the C11 attempt lifecycle."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.core_evidence import OBJECT_CHECK_VOCABULARY
from agent.native_artifact_recheck import (
    CHECK_VOCABULARY,
    DischargedChecks,
    FILE_MEMBERS,
    RECORD_FILE,
    build_artifact_recheck_parser,
    main_artifact_recheck,
)

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


def _write_core(tmp_path: Path, recheck_exit: int = 0) -> Path:
    """Stub `mumei` executable: `native-bundle recheck-artifact`
    prints a fixed line and exits per `recheck_exit`."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-artifact" ]; then\n'
        f"    exit_code={recheck_exit}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        "        printf 'Pinned toolchain outputs reproduce the pinned artifacts.'\n"
        "    fi\n"
        '    exit "$exit_code"\n'
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _write_bundle(tmp_path: Path, record: dict = RECORD) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True)
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
        code = main_artifact_recheck(
            build_artifact_recheck_parser().parse_args(argv)
        )
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


def _assert_check_partition(report, discharged=frozenset()):
    assert report["checks_not_performed"] == sorted(
        (CHECK_VOCABULARY - discharged) | OBJECT_CHECK_VOCABULARY
    )
    assert not (
        set(report.get("discharged_checks", []))
        & OBJECT_CHECK_VOCABULARY
    )


def test_reproduced_run_selects_output(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert (
        report["schema_version"]
        == "mumei.native-artifact-recheck-report/v1"
    )
    assert report["artifact_recheck"] == "reproduced"
    assert report["sequence"]["selected_result"] is not None
    assert report["discharged_checks"] == [
        "artifact_semantics",
        "claim_truth",
    ]
    assert report["checks_not_performed"] == [
        "file_identity",
        "freshness",
        "machine_code_direct_call_site_tv",
        "machine_code_leaf_function_tv",
        "object_call_edge_correspondence",
        "object_link_correspondence",
        "object_symbol_correspondence",
        "object_translation_correspondence",
        "producer_authenticity",
        "semantic_correspondence",
    ]
    _assert_check_partition(report, DischargedChecks.REPRODUCED)
    # The stdout line is not an evidence record — no handoff.
    assert "candidate" not in report
    assert "recheck" not in report


def test_exit_one_publishes_lineage_without_claimed_outcome(
    tmp_path, capsys
):
    """Exit 1 conflates a failed reproduction with every static
    failure — the route claims no outcome for it."""
    core = _write_core(tmp_path, recheck_exit=1)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "artifact_recheck" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    assert report["normalized"]["exit_code"] == 1
    _assert_check_partition(report)


def test_inconclusive_recheck_records_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=3)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["artifact_recheck"] == "inconclusive"
    assert "discharged_checks" not in report
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == 3
    _assert_check_partition(report)


def test_unknown_exit_code_omits_recheck_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=2)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "artifact_recheck" not in report
    assert report["normalized"]["exit_code"] == 2
    _assert_check_partition(report)


def test_mid_run_input_drift_claims_no_outcome(tmp_path, capsys):
    """A child that mutates a declared bundle member mid-run exits 0,
    but the exit code applies to bytes outside the declared request."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-artifact" ]; then\n'
        '    printf "tampered" > "$5/program.ll"\n'
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
    assert "artifact_recheck" not in report
    assert report["sequence"].get("selected_result") is None
    _assert_check_partition(report)


def test_multifile_members_enumerated_and_fingerprinted(tmp_path, capsys):
    """A multifile record's `sources` members join the declared set —
    tampering with one mid-run is observed as drift."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-artifact" ]; then\n'
        '    printf "tampered" > "$5/sources/dep.mm"\n'
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
    assert "artifact_recheck" not in report
    _assert_check_partition(report)


def test_mid_run_record_swap_declaring_new_member_is_drift(
    tmp_path, capsys
):
    """A record swapped mid-run may declare members the pre-run
    enumeration never fingerprinted — the drift check re-enumerates
    from the current record so the member-set change is caught."""
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-artifact" ]; then\n'
        f"    printf '%s' '{json.dumps(MULTIFILE_RECORD)}' > \"$5/{RECORD_FILE}\"\n"
        "    mkdir -p \"$5/sources/sub\"\n"
        '    printf "atom body" > "$5/sources/app.mm"\n'
        '    printf "atom body" > "$5/sources/dep.mm"\n'
        '    printf "atom body" > "$5/sources/sub/extra.mm"\n'
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
    assert "artifact_recheck" not in report


def test_multifile_bundle_rechecked_clean(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["artifact_recheck"] == "reproduced"


def test_invalid_sources_member_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    for index, member in enumerate(
        ("../escape.mm", ".hidden.mm", "a\\b.mm", "a:b.mm")
    ):
        record = {
            "schema": "mumei.native-multifile-bundle/v1",
            "files": {key: {} for key in FILE_MEMBERS},
            "sources": {member: {}},
        }
        bundle = _write_bundle(tmp_path / f"b{index}", record=record)
        code, _, err = _run(capsys, _args(core, bundle, source))
        assert code == 1, member


def test_unknown_files_key_rejected(tmp_path, capsys):
    record = {
        "schema": "mumei.native-bundle/v1",
        "files": {**{key: {} for key in FILE_MEMBERS}, "evil.bin": {}},
    }
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path, record=record)
    (bundle / "evil.bin").write_text("x")
    source = _write_source(tmp_path)
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
    argv = _args(Path("relative-mumei"), bundle, source)
    code, out, _ = _run(capsys, argv)
    assert code == 1
    assert "selected_result" not in out


def test_non_directory_bundle_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    code, _, _ = _run(capsys, _args(core, source, source))
    assert code == 1


def test_invalid_build_id_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    argv = _args(core, bundle, source)
    argv[argv.index(BUILD_ID)] = "not-a-digest"
    code, _, _ = _run(capsys, argv)
    assert code == 1


def test_output_may_not_overwrite_declared_inputs(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    for declared in (bundle / "program.ll", source):
        code, _, _ = _run(
            capsys,
            _args(core, bundle, source, ("--output", str(declared))),
        )
        assert code == 1
    assert (bundle / "program.ll").read_text() == "bytes of program.ll"


def test_oversize_source_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = tmp_path / "big.mm"
    source.write_text("x" * 65537)
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_report_written_to_output_file(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    report_path = tmp_path / "report.json"
    code, out, _ = _run(
        capsys,
        _args(core, bundle, source, ("--output", str(report_path))),
    )
    assert code == 0
    assert out == ""
    report = json.loads(report_path.read_text())
    assert report["artifact_recheck"] == "reproduced"


def test_cli_dispatch():
    proc = subprocess.run(
        [sys.executable, "-m", "agent", "native-artifact-recheck", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
    )
    assert proc.returncode == 0
    assert "--expected-build-id" in proc.stdout


@pytest.mark.skipif(
    not os.path.exists("/home/ubuntu/repos/mumei/target/debug/mumei"),
    reason="real Core binary not built",
)
def test_real_core_end_to_end(tmp_path, capsys):
    """Build a real bundle with the real Core, then replay the artifact
    recheck as a declared attempt — reproduced + discharged checks."""
    core = Path("/home/ubuntu/repos/mumei/target/debug/mumei")
    source = tmp_path / "main.mm"
    source.write_text(SOURCE)
    bundle = tmp_path / "bundle"
    build = subprocess.run(
        [str(core), "native-bundle", "build", str(source), "-o", str(bundle)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    record = json.loads((bundle / RECORD_FILE).read_bytes())
    build_id = __import__("hashlib").sha256(
        (bundle / RECORD_FILE).read_bytes()
    ).hexdigest()
    assert record["schema"] == "mumei.native-bundle/v1"
    code, out, err = _run(
        capsys,
        [
            "--core", str(core),
            "--bundle", str(bundle),
            "--source", str(source),
            "--expected-build-id", build_id,
            "--attempt-timeout", "120000",
        ],
    )
    assert code == 0, err
    report = json.loads(out)
    assert report["artifact_recheck"] == "reproduced"
    assert report["discharged_checks"] == [
        "artifact_semantics",
        "claim_truth",
    ]
