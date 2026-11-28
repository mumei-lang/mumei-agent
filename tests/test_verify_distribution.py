"""Tests for the native-first verify-distribution orchestrator."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.native_bundle import FILE_MEMBERS, RECORD_FILE
from agent.verify_distribution import (
    build_distribution_parser,
    main_distribution,
)

BUILD_ID = "a" * 64
OTHER_BUILD_ID = "b" * 64

NATIVE_REPORT = {
    "schema_version": "mumei.native-consumer-evidence/v1",
    "build_id": BUILD_ID,
    "acceptance": "not_evaluated",
    "evidence": [],
}
ACCEPTANCE = {
    "schema_version": "mumei.native-evidence-acceptance/v1",
    "acceptance": "evaluated",
    "accepted": True,
    "scope": "test",
    "checks_performed": [],
    "checks_not_performed": [],
}


def _record(*, multifile=False, runtime=True):
    record = {
        "schema": (
            "mumei.native-multifile-bundle/v1" if multifile else "mumei.native-bundle/v1"
        ),
        "files": {key: {} for key in FILE_MEMBERS},
    }
    if runtime:
        record["link_build"] = {
            "expected_exit_status": 0,
            "expected_stdout_sha256": "0" * 64,
            "expected_stderr_sha256": "0" * 64,
        }
    if multifile:
        record["sources"] = {"app.mm": {}, "dep.mm": {}}
    return record


def _write_core(tmp_path: Path, *, native_exit=0, artifact_exit=0, runtime_exit=0, cert_exit=0) -> Path:
    core = tmp_path / "mumei-stub"
    native_report = json.dumps(NATIVE_REPORT)
    acceptance = json.dumps(ACCEPTANCE)
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "verify-cert" ]; then\n'
        '    if [ "$2" != "--strict" ]; then exit 2; fi\n'
        '    case "$3" in */proof-cert.json) ;; *) exit 2;; esac\n'
        '    case "$4" in */source.mm) ;; *) exit 2;; esac\n'
        f"    exit {cert_exit}\n"
        "fi\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-llvm" ]; then\n'
        f'    if [ "$4" != "{BUILD_ID}" ]; then exit 1; fi\n'
        f'    if [ "{native_exit}" = "0" ]; then printf \'%s\' \'{native_report}\'; fi\n'
        f"    exit {native_exit}\n"
        "fi\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "accept-artifact" ]; then\n'
        f'    if [ "$4" != "{BUILD_ID}" ]; then exit 1; fi\n'
        f'    if [ "{artifact_exit}" = "0" ]; then printf \'%s\' \'{acceptance}\'; fi\n'
        f"    exit {artifact_exit}\n"
        "fi\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "accept-observations" ]; then\n'
        f'    if [ "$4" != "{BUILD_ID}" ]; then exit 1; fi\n'
        '    record="$6/native-bundle.json"\n'
        '    grep -q expected_exit_status "$record" || exit 3\n'
        '    grep -q expected_stdout_sha256 "$record" || exit 3\n'
        '    grep -q expected_stderr_sha256 "$record" || exit 3\n'
        f'    if [ "{runtime_exit}" = "0" ]; then printf \'%s\' \'{acceptance}\'; fi\n'
        f"    exit {runtime_exit}\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _write_bundle(tmp_path: Path, record) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / RECORD_FILE).write_text(json.dumps(record))
    for name in FILE_MEMBERS.values():
        (bundle / name).write_text(f"bytes of {name}")
    for member in record.get("sources") or {}:
        path = bundle / "sources" / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("atom dep() -> i64 requires: true; ensures: true; body: { 0 };")
    return bundle


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "source.mm"
    source.write_text("atom main() -> i64 requires: true; ensures: result == 0; body: { 0 };")
    return source


def _argv(core, bundle, source, *extra):
    return [
        "--core", str(core),
        "--bundle", str(bundle),
        "--source", str(source),
        "--expected-build-id", BUILD_ID,
        "--attempt-timeout", "60000",
        *extra,
    ]


def _run(capsys, argv):
    code = main_distribution(build_distribution_parser().parse_args(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def _fixture(tmp_path, **record_kwargs):
    return (
        _write_core(tmp_path),
        _write_bundle(tmp_path, _record(**record_kwargs)),
        _write_source(tmp_path),
    )


def test_positive_runtime_off_is_explicitly_skipped(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    code, out, err = _run(capsys, _argv(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.verify-distribution-report/v1"
    roles = report["roles"]
    assert roles["proof_certificate"]["status"] == "accepted"
    assert roles["native_source_llvm"]["status"] == "accepted"
    assert roles["artifact_reproduction"]["status"] == "accepted"
    assert roles["runtime_observation"] == {
        "status": "skipped",
        "reason": "runtime_observations_not_enabled",
        "checks_not_performed": [
            "os_exit_status_observation",
            "os_stdout_observation",
            "os_stderr_observation",
        ],
    }
    assert len(report["inputs"]["core_sha256"]) == 64
    assert "deep_acceptance_fold" in report["checks_not_performed"]
    assert "unified_verdict" in report["checks_not_performed"]


def test_runtime_opt_in_reuses_observations_route(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    code, out, _ = _run(
        capsys, _argv(core, bundle, source, "--enable-runtime-observations")
    )
    assert code == 0
    role = json.loads(out)["roles"]["runtime_observation"]
    assert role["status"] == "accepted"
    assert role["report_schema"] == "mumei.native-observations-accept-report/v1"
    assert role["report"]["sequence"]["selected_result"] is not None


def test_runtime_opt_in_without_pins_projects_core_inconclusive(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path, runtime=False)
    code, out, _ = _run(
        capsys, _argv(core, bundle, source, "--enable-runtime-observations")
    )
    assert code == 3
    role = json.loads(out)["roles"]["runtime_observation"]
    assert role["status"] == "inconclusive"
    assert role["reason"] == "core_inconclusive"


def test_wrong_build_id_projects_unclaimed_exit_as_inconclusive(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    argv = _argv(core, bundle, source)
    argv[argv.index(BUILD_ID)] = OTHER_BUILD_ID
    code, out, _ = _run(capsys, argv)
    assert code == 1
    roles = json.loads(out)["roles"]
    assert roles["proof_certificate"]["status"] == "accepted"
    for name in ("native_source_llvm", "artifact_reproduction"):
        assert roles[name]["status"] == "inconclusive"
        assert roles[name]["reason"] == "unclaimed_exit_outcome"
        assert roles[name]["exit_code"] == 1
        assert "acceptance" not in roles[name]["report"]
        assert "recheck" not in roles[name]["report"]


def test_partial_runtime_pin_projects_core_inconclusive(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    record = json.loads((bundle / RECORD_FILE).read_text())
    del record["link_build"]["expected_stdout_sha256"]
    del record["link_build"]["expected_stderr_sha256"]
    (bundle / RECORD_FILE).write_text(json.dumps(record))
    code, out, _ = _run(
        capsys, _argv(core, bundle, source, "--enable-runtime-observations")
    )
    assert code == 3
    role = json.loads(out)["roles"]["runtime_observation"]
    assert role["status"] == "inconclusive"
    assert role["reason"] == "core_inconclusive"


def test_missing_source_is_static_input_error_without_report(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    source.unlink()
    code, out, err = _run(capsys, _argv(core, bundle, source))
    assert code == 1
    assert out == ""
    assert "--source" in err


def test_multifile_proof_certificate_is_unsupported_not_silent(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path, multifile=True)
    code, out, _ = _run(capsys, _argv(core, bundle, source))
    assert code == 1
    roles = json.loads(out)["roles"]
    assert roles["proof_certificate"]["status"] == "unsupported"
    assert (
        roles["proof_certificate"]["reason"]
        == "multifile_certificate_source_binding_not_declared"
    )
    assert roles["native_source_llvm"]["status"] == "accepted"


def test_explicit_core_inconclusive_exits_three(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    # Rewrite the stub with artifact exit 3.
    core = _write_core(tmp_path, artifact_exit=3)
    code, out, _ = _run(capsys, _argv(core, bundle, source))
    assert code == 3
    role = json.loads(out)["roles"]["artifact_reproduction"]
    assert role["status"] == "inconclusive"
    assert role["reason"] == "core_inconclusive"


def test_multifile_schema_without_sources_is_still_unsupported(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    record = json.loads((bundle / RECORD_FILE).read_text())
    record["schema"] = "mumei.native-multifile-bundle/v1"
    (bundle / RECORD_FILE).write_text(json.dumps(record))
    code, out, _ = _run(capsys, _argv(core, bundle, source))
    assert code == 1
    assert (
        json.loads(out)["roles"]["proof_certificate"]["status"] == "unsupported"
    )


def test_missing_proof_certificate_is_failed(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    (bundle / "proof-cert.json").unlink()
    # Declared members are checked before orchestration, so remove the member
    # declaration as well to exercise the role-level missing-certificate path.
    record = json.loads((bundle / RECORD_FILE).read_text())
    del record["files"]["certificate"]
    (bundle / RECORD_FILE).write_text(json.dumps(record))
    code, out, _ = _run(capsys, _argv(core, bundle, source))
    assert code == 1
    assert (
        json.loads(out)["roles"]["proof_certificate"]["reason"]
        == "missing_proof_certificate"
    )


def test_cross_lane_input_drift_suppresses_accepted_projection(tmp_path, capsys, monkeypatch):
    core, bundle, source = _fixture(tmp_path)
    import agent.verify_distribution as verify_distribution

    original = verify_distribution.native_accept.run_accept

    def mutate_after_route(args):
        report = original(args)
        source.write_text(source.read_text() + "\n")
        return report

    monkeypatch.setattr(
        verify_distribution.native_accept, "run_accept", mutate_after_route
    )
    code, out, _ = _run(capsys, _argv(core, bundle, source))
    assert code == 1
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert report["roles"]["artifact_reproduction"]["status"] == "inconclusive"
    assert report["roles"]["artifact_reproduction"]["reason"] == "inputs_changed"
    assert (
        report["roles"]["artifact_reproduction"]["report"]["acceptance"]
        == "accepted"
    )


def test_timeout_and_memory_bound_pass_unchanged_to_reused_routes(tmp_path, capsys, monkeypatch):
    core, bundle, source = _fixture(tmp_path)
    import agent.verify_distribution as verify_distribution

    seen = {}

    run_functions = {
        "native_recheck": "run_recheck",
        "native_accept": "run_accept",
        "native_observations_accept": "run_observations_accept",
    }

    def capture(module_name):
        original = getattr(
            getattr(verify_distribution, module_name), run_functions[module_name]
        )

        def wrapped(args):
            seen[module_name] = (args.attempt_timeout, args.memory_bound_mb)
            return original(args)

        return wrapped

    monkeypatch.setattr(
        verify_distribution.native_recheck, "run_recheck", capture("native_recheck")
    )
    monkeypatch.setattr(
        verify_distribution.native_accept, "run_accept", capture("native_accept")
    )
    monkeypatch.setattr(
        verify_distribution.native_observations_accept,
        "run_observations_accept",
        capture("native_observations_accept"),
    )
    argv = _argv(core, bundle, source, "--enable-runtime-observations", "--memory-bound-mb", "256")
    argv[argv.index("60000")] = "45000"
    code, _out, _ = _run(capsys, argv)
    assert code == 0
    assert seen == {
        "native_recheck": (45000, 256),
        "native_accept": (45000, 256),
        "native_observations_accept": (45000, 256),
    }


def test_output_file_and_no_secret_echo(tmp_path, capsys, monkeypatch):
    core, bundle, source = _fixture(tmp_path)
    sentinel = "fake-verify-distribution-secret"
    monkeypatch.setenv("LLM_API_KEY", sentinel)
    output = tmp_path / "distribution-report.json"
    code, out, _ = _run(capsys, _argv(core, bundle, source, "--output", str(output)))
    assert code == 0 and out == ""
    text = output.read_text()
    assert sentinel not in text
    assert json.loads(text)["roles"]["artifact_reproduction"]["status"] == "accepted"


def test_output_may_not_overwrite_declared_bundle_member(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    code, out, err = _run(
        capsys, _argv(core, bundle, source, "--output", str(bundle / "proof-cert.json"))
    )
    assert code == 1
    assert out == ""
    assert "--output may not overwrite" in err


def test_oversize_declared_member_is_bounded_before_hashing(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    with (bundle / "program.o").open("wb") as member:
        member.truncate(33_554_432 + 1)
    code, out, err = _run(capsys, _argv(core, bundle, source))
    assert code == 1
    assert out == ""
    assert "exceeds the Core input bound" in err


def test_unwritable_output_is_operational_error_not_traceback(tmp_path, capsys):
    core, bundle, source = _fixture(tmp_path)
    missing_parent = tmp_path / "missing" / "report.json"
    code, out, err = _run(
        capsys, _argv(core, bundle, source, "--output", str(missing_parent))
    )
    assert code == 1
    assert out == ""
    assert "cannot write report" in err
    assert "Traceback" not in err


def test_cli_help_mentions_trusted_runtime_boundary():
    help_text = build_distribution_parser().format_help()
    compact = " ".join(help_text.split())
    assert "Off by default" in compact
    assert "trusted" in compact


@pytest.fixture
def real_core():
    path = os.environ.get("MUMEI_BIN")
    if path and Path(path).is_absolute() and Path(path).is_file():
        return path
    pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")


@pytest.mark.integration
def test_real_core_incomplete_runtime_pins_are_inconclusive(tmp_path, capsys, real_core):
    source = _write_source(tmp_path)
    bundle = tmp_path / "bundle"
    built = subprocess.run(
        [real_core, "native-bundle", "build", str(source), "-o", str(bundle)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if built.returncode != 0:
        if "unsupported host for first native profile" in built.stderr:
            pytest.skip("native-bundle build needs linux/x86_64")
        pytest.fail(f"native-bundle build failed: {built.stderr}")

    for mode in ("partial", "absent"):
        mutated = tmp_path / f"bundle-{mode}"
        shutil.copytree(bundle, mutated)
        record_path = mutated / RECORD_FILE
        record = json.loads(record_path.read_text())
        if mode == "partial":
            record["link_build"]["expected_stdout_sha256"] = None
            record["link_build"]["expected_stderr_sha256"] = None
        else:
            record["link_build"]["expected_exit_status"] = None
            record["link_build"]["expected_stdout_sha256"] = None
            record["link_build"]["expected_stderr_sha256"] = None
        record_path.write_text(json.dumps(record))
        import hashlib

        build_id = hashlib.sha256(record_path.read_bytes()).hexdigest()
        argv = _argv(Path(real_core), mutated, source, "--enable-runtime-observations")
        argv[argv.index("--expected-build-id") + 1] = build_id
        code, out, _ = _run(capsys, argv)
        assert code == 3
        role = json.loads(out)["roles"]["runtime_observation"]
        assert role["status"] == "inconclusive"
        assert role["reason"] == "core_inconclusive"
