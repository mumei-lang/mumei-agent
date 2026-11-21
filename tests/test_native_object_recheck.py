"""Route tests for ``native-object-recheck`` through the C11 attempt lifecycle."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.core_evidence import OBJECT_CHECK_VOCABULARY
from agent.native_object_recheck import (
    CHECK_VOCABULARY,
    FILE_MEMBERS,
    OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA,
    RECORD_FILE,
    build_object_recheck_parser,
    main_object_recheck,
)

BUILD_ID = "a" * 64

DESCRIPTOR = {
    "schema_version": OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA,
    "scope": "test",
    "build_id": BUILD_ID,
    "defined_functions": ["main"],
    "external_references": [],
    "call_edges": {"main": []},
    "checks_performed": [
        "toolchain_object_executable_reproduction",
        "object_symbol_correspondence",
        "object_call_edge_correspondence",
        "object_link_correspondence",
    ],
    "checks_not_performed": [
        "optimizer_semantics",
        "raw_link_argument_vector_reproduction",
        "abi_runtime_semantics",
    ],
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

SOURCE = "atom main() -> i64 requires: true; ensures: result == 0; body: { 0 };\n"

BASE_DISCHARGED = frozenset({"artifact_semantics", "claim_truth"})
BOUNDED_OBJECT_CHECKS = OBJECT_CHECK_VOCABULARY - {
    "machine_code_bounded_loop_function_tv",
    "machine_code_direct_call_site_tv",
    "machine_code_leaf_function_tv",
    "machine_code_forward_branch_function_tv",
    "machine_code_acyclic_branch_function_tv",
    "machine_code_conditional_call_function_tv",
    "machine_code_callee_saved_register_preservation",
    "machine_code_callee_saved_preservation_assumed_for_external_callees",
    "machine_code_entry_wrapper_tv",
    "machine_code_f64_scalar_function_tv",
    "machine_code_tv_mxcsr_control_state",
    "machine_code_tv_nan_payload_bits",
    "object_translation_correspondence",
}
EXPECTED_DISCHARGED = BASE_DISCHARGED | BOUNDED_OBJECT_CHECKS


def _write_core(tmp_path: Path, recheck_exit: int = 0, stdout=DESCRIPTOR) -> Path:
    """Stub Core for `native-bundle recheck-object`."""
    core = tmp_path / "mumei-stub"
    output = stdout if isinstance(stdout, str) else json.dumps(stdout)
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-object" ]; then\n'
        '    if [ "$3" != "--expected-build-id" ]; then exit 2; fi\n'
        f'    if [ "$4" != "{BUILD_ID}" ]; then exit 1; fi\n'
        '    if [ "$5" != "--json" ]; then exit 2; fi\n'
        f"    exit_code={recheck_exit}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"        printf '%s' '{output}'\n"
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
    for member in record.get("sources") or {}:
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
        code = main_object_recheck(build_object_recheck_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def _args(core: Path, bundle: Path, source: Path, extra=()):
    return [
        "--core",
        str(core),
        "--bundle",
        str(bundle),
        "--source",
        str(source),
        "--expected-build-id",
        BUILD_ID,
        "--attempt-timeout",
        "60000",
        *extra,
    ]


def _assert_check_partition(
    report,
    expected_build_id=BUILD_ID,
    expected_discharged=None,
):
    assert report["expected_build_id"] == expected_build_id
    discharged = set(report.get("discharged_checks", []))
    if expected_discharged is None:
        expected_discharged = (
            EXPECTED_DISCHARGED
            if report.get("object_recheck") == "corresponds"
            else frozenset()
        )
    assert discharged == set(expected_discharged)
    assert report["checks_not_performed"] == sorted(
        (CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY) - discharged
    )


def test_corresponding_run_selects_descriptor_and_bounded_checks(
    tmp_path, capsys
):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.native-object-recheck-report/v1"
    assert report["object_recheck"] == "corresponds"
    assert report["object_correspondence_schema"] == (
        OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA
    )
    assert report["sequence"]["selected_result"] is not None
    assert report["discharged_checks"] == sorted(EXPECTED_DISCHARGED)
    assert report["checks_not_performed"] == sorted(
        (CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY) - EXPECTED_DISCHARGED
    )
    assert "object_translation_correspondence" not in report["discharged_checks"]
    assert "historical_execution" not in report["discharged_checks"]
    assert "defined_functions" not in report
    _assert_check_partition(report)


def test_machine_tv_check_is_not_discharged_by_object_descriptor(
    tmp_path, capsys
):
    descriptor = dict(DESCRIPTOR)
    descriptor["checks_performed"] = [
        *DESCRIPTOR["checks_performed"],
        "machine_code_leaf_function_tv",
        "machine_code_direct_call_site_tv",
        "machine_code_forward_branch_function_tv",
        "machine_code_acyclic_branch_function_tv",
        "machine_code_conditional_call_function_tv",
        "machine_code_bounded_loop_function_tv",
        "machine_code_callee_saved_register_preservation",
        "machine_code_callee_saved_preservation_assumed_for_external_callees",
        "machine_code_entry_wrapper_tv",
        "machine_code_f64_scalar_function_tv",
        "machine_code_tv_mxcsr_control_state",
        "machine_code_tv_nan_payload_bits",
    ]
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    expected = BASE_DISCHARGED | BOUNDED_OBJECT_CHECKS
    assert report["discharged_checks"] == sorted(expected)
    assert "machine_code_leaf_function_tv" not in report["discharged_checks"]
    assert "machine_code_direct_call_site_tv" not in report["discharged_checks"]
    assert "machine_code_forward_branch_function_tv" not in report["discharged_checks"]
    assert "machine_code_acyclic_branch_function_tv" not in report["discharged_checks"]
    assert "machine_code_conditional_call_function_tv" not in report["discharged_checks"]
    assert "machine_code_bounded_loop_function_tv" not in report["discharged_checks"]
    assert (
        "machine_code_callee_saved_register_preservation"
        not in report["discharged_checks"]
    )
    assert (
        "machine_code_callee_saved_preservation_assumed_for_external_callees"
        not in report["discharged_checks"]
    )
    assert "machine_code_entry_wrapper_tv" not in report["discharged_checks"]
    assert "machine_code_entry_wrapper_tv" in report["checks_not_performed"]
    for check in (
        "machine_code_f64_scalar_function_tv",
        "machine_code_tv_mxcsr_control_state",
        "machine_code_tv_nan_payload_bits",
    ):
        assert check not in report["discharged_checks"]
        assert check in report["checks_not_performed"]
    _assert_check_partition(report, expected_discharged=expected)


@pytest.mark.parametrize(
    ("checks_performed", "expected_object_checks"),
    [
        (
            [
                "toolchain_object_executable_reproduction",
                "object_symbol_correspondence",
                "object_call_edge_correspondence",
            ],
            {
                "object_symbol_correspondence",
                "object_call_edge_correspondence",
            },
        ),
        (
            [
                "object_symbol_correspondence",
                "object_call_edge_correspondence",
                "object_link_correspondence",
                "object_translation_correspondence",
            ],
            BOUNDED_OBJECT_CHECKS,
        ),
        (
            [
                "object_symbol_correspondence",
                "object_link_correspondence",
                "unknown_check",
                17,
                None,
            ],
            {"object_symbol_correspondence", "object_link_correspondence"},
        ),
        ({"not": "a list"}, set()),
        (None, set()),
    ],
)
def test_descriptor_checks_performed_control_object_discharge(
    tmp_path, capsys, checks_performed, expected_object_checks
):
    descriptor = {**DESCRIPTOR, "checks_performed": checks_performed}
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["object_recheck"] == "corresponds"
    assert report["object_correspondence_schema"] == (
        OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA
    )
    expected_discharged = BASE_DISCHARGED | expected_object_checks
    assert report["discharged_checks"] == sorted(expected_discharged)
    assert "object_translation_correspondence" not in report["discharged_checks"]
    _assert_check_partition(report, expected_discharged=expected_discharged)


@pytest.mark.parametrize(
    "stdout",
    [
        {"schema_version": "mumei.other/v1", "build_id": BUILD_ID},
        {
            "schema_version": OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA,
            "build_id": "b" * 64,
        },
        "not-json",
        ["not", "an", "object"],
    ],
)
def test_correspondence_schema_requires_matching_object_descriptor(
    tmp_path, capsys, stdout
):
    core = _write_core(tmp_path, stdout=stdout)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["object_recheck"] == "corresponds"
    assert "object_correspondence_schema" not in report
    assert report["discharged_checks"] == sorted(BASE_DISCHARGED)
    _assert_check_partition(
        report, expected_discharged=BASE_DISCHARGED
    )


def test_inconclusive_recheck_records_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=3)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["object_recheck"] == "inconclusive"
    assert "object_correspondence_schema" not in report
    assert "discharged_checks" not in report
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == 3
    _assert_check_partition(report)


def test_exit_one_publishes_lineage_without_claimed_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, recheck_exit=1)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "object_recheck" not in report
    assert "object_correspondence_schema" not in report
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == 1
    assert "discharged_checks" not in report
    _assert_check_partition(report)


@pytest.mark.parametrize("recheck_exit", [2, 7])
def test_unknown_exit_omits_recheck_outcome(tmp_path, capsys, recheck_exit):
    core = _write_core(tmp_path, recheck_exit=recheck_exit)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "object_recheck" not in report
    assert "object_correspondence_schema" not in report
    assert report["sequence"].get("selected_result") is None
    assert report["normalized"]["exit_code"] == recheck_exit
    _assert_check_partition(report)


def test_wrong_build_id_is_echoed_without_claimed_outcome(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    argv = _args(core, bundle, source)
    wrong_id = "b" * 64
    argv[argv.index("--expected-build-id") + 1] = wrong_id
    code, out, _ = _run(capsys, argv)
    assert code == 0
    report = json.loads(out)
    assert report["expected_build_id"] == wrong_id
    assert "object_recheck" not in report
    assert "object_correspondence_schema" not in report
    assert report["normalized"]["exit_code"] == 1
    _assert_check_partition(report, wrong_id)


def test_inputs_changed_suppresses_recheck_outcome(tmp_path, capsys, monkeypatch):
    from agent import native_object_recheck as route

    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    original = route._attempt_fingerprint
    calls = 0

    def change_declared_member(args, members):
        nonlocal calls
        if calls:
            member = next(iter(FILE_MEMBERS.values()))
            (bundle / member).write_text("changed bytes")
        calls += 1
        return original(args, members)

    monkeypatch.setattr(route, "_attempt_fingerprint", change_declared_member)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "object_recheck" not in report
    assert "object_correspondence_schema" not in report
    _assert_check_partition(report)


def test_unparseable_bundle_rejected_without_traceback(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    (bundle / RECORD_FILE).write_text("{not json")
    source = _write_source(tmp_path)
    code, _, err = _run(capsys, _args(core, bundle, source))
    assert code == 1
    assert "Traceback" not in err


def test_oversized_inputs_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    (bundle / RECORD_FILE).write_text("x" * 1_100_000)
    code, _, _ = _run(capsys, _args(core, bundle, source))
    assert code == 1


def test_missing_member_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    (bundle / "program.o").unlink()
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


def test_multifile_bundle_rechecks_cleanly(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path, record=MULTIFILE_RECORD)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["object_recheck"] == "corresponds"
    _assert_check_partition(report)


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only route")
def test_cli_dispatch(tmp_path):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent",
            "native-object-recheck",
            "--core",
            str(core),
            "--bundle",
            str(bundle),
            "--source",
            str(source),
            "--expected-build-id",
            BUILD_ID,
            "--attempt-timeout",
            "60000",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["object_recheck"] == "corresponds"
    assert report["object_correspondence_schema"] == (
        OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA
    )


def test_mcp_tool_dispatch(tmp_path):
    from agent import mcp_server

    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    result = json.loads(
        mcp_server.native_object_recheck(
            str(core), str(bundle), str(source), BUILD_ID
        )
    )
    assert result["status"] == "ok"
    assert result["report"]["object_recheck"] == "corresponds"
    assert result["report"]["object_correspondence_schema"] == (
        OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA
    )


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
    if built.returncode == 0:
        return
    if "unsupported host for first native profile" in built.stderr:
        pytest.skip("native-bundle build needs linux/x86_64")
    pytest.fail(f"native-bundle build failed: {built.stderr}")


def _build_real_bundle(tmp_path: Path, real_core: str) -> tuple[Path, Path]:
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
    return bundle, source


@pytest.mark.integration
def test_real_core_rechecks_object_symbol_call_edge_and_link_correspondence(
    tmp_path, capsys, real_core
):
    bundle, source = _build_real_bundle(tmp_path, real_core)
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["object_recheck"] == "corresponds"
    assert report["expected_build_id"] == build_id
    assert report["object_correspondence_schema"] == (
        OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA
    )
    assert report["discharged_checks"] == sorted(EXPECTED_DISCHARGED)
    assert "object_link_correspondence" in report["discharged_checks"]
    assert report["checks_not_performed"] == sorted(
        (CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY) - EXPECTED_DISCHARGED
    )
    _assert_check_partition(report, build_id)


@pytest.mark.integration
def test_real_core_rejects_wrong_build_id(tmp_path, capsys, real_core):
    bundle, source = _build_real_bundle(tmp_path, real_core)
    argv = _args(Path(real_core), bundle, source)
    wrong_id = "0" * 64
    argv[argv.index("--expected-build-id") + 1] = wrong_id
    code, out, _ = _run(capsys, argv)
    assert code == 0
    report = json.loads(out)
    assert report["expected_build_id"] == wrong_id
    assert "object_recheck" not in report
    assert "object_correspondence_schema" not in report
    assert report["normalized"]["exit_code"] == 1
    _assert_check_partition(report, wrong_id)
