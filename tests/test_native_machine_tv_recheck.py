"""Route tests for ``native-machine-tv-recheck`` through the C11 lifecycle."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.core_evidence import (
    MACHINE_TV_ASSUMPTION_MARKERS,
    OBJECT_CHECK_VOCABULARY,
)
from agent.native_bundle import FILE_MEMBERS, RECORD_FILE
from agent.native_machine_tv_recheck import (
    CHECK_VOCABULARY,
    MACHINE_TV_OBJECT_CHECKS,
    MACHINE_TV_SCHEMA,
    build_machine_tv_recheck_parser,
    main_machine_tv_recheck,
)
from agent.native_object_recheck import OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA

BUILD_ID = "a" * 64
SOURCE = (
    "atom main() -> i64 requires: true; ensures: result == 7; "
    "body: { 7 };\n"
)
DESCRIPTOR = {
    "schema_version": MACHINE_TV_SCHEMA,
    "scope": "test",
    "build_id": BUILD_ID,
    "register_convention_assumed": (
        "sysv_x86_64_integer_args_rdi_rsi_rdx_rcx_r8_r9_result_rax"
    ),
    "input_domain": "pure_i64_inputs",
    "functions": {
        "__mumei_user_main": {"outcome": "equivalent_within_profile"},
        "main": {"outcome": "outside_profile", "reason": "wrapper"},
    },
    "checks_performed": [
        "toolchain_object_executable_reproduction",
        "object_symbol_correspondence",
        "object_call_edge_correspondence",
        "object_link_correspondence",
        "machine_code_leaf_function_tv",
        "machine_code_callee_saved_register_preservation",
    ],
    "checks_not_performed": [
        "machine_code_direct_call_site_tv",
        "machine_code_forward_branch_function_tv",
        "machine_code_acyclic_branch_function_tv",
        "machine_code_conditional_call_function_tv",
        "machine_code_bounded_loop_function_tv",
        "machine_code_callee_saved_preservation_assumed_for_external_callees",
        "machine_code_tv_cyclic_control_flow_functions",
        "object_translation_correspondence",
    ],
}
RECORD = {
    "schema": "mumei.native-bundle/v1",
    "files": {key: {} for key in FILE_MEMBERS},
}
BASE_DISCHARGED = frozenset({"artifact_semantics", "claim_truth"})
OBJECT_MACHINE_CHECKS = MACHINE_TV_OBJECT_CHECKS
ALL_CHECKS = CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY
F64_REGISTER_CONVENTION = (
    "sysv_x86_64_integer_args_rdi_rsi_rdx_rcx_r8_r9_f64_args_"
    "xmm0_7_result_rax_or_xmm0"
)
COMPOSITE_AGGREGATE_REGISTER_CONVENTION = (
    "sysv_x86_64_integer_args_rdi_rsi_rdx_rcx_r8_r9_result_rax_"
    "two_eightbyte_integer_aggregates_in_consecutive_gprs_result_rax_rdx"
)
COMPOSITE_SSE_AGGREGATE_REGISTER_CONVENTION = (
    "sysv_x86_64_integer_args_rdi_rsi_rdx_rcx_r8_r9_f64_args_xmm0_7_"
    "result_rax_or_xmm0_two_eightbyte_aggregates_classified_integer_gprs_"
    "sse_xmm_result_rax_rdx_xmm0_xmm1"
)
COMPOSITE_AGGREGATE_SOURCE = (
    "struct P { x: i64, y: i64 }\n"
    "atom sum(p: P) -> i64 requires: true; ensures: true; "
    "body: { p.x + p.y };\n"
    "atom mk(a: i64, b: i64) -> P requires: true; ensures: true; "
    "body: { P { x: a, y: b } };\n"
    "atom caller() -> i64 requires: true; ensures: true; "
    "body: { sum(mk(1, 2)) };\n"
    "atom fwd(p: P) -> i64 requires: true; ensures: true; "
    "body: { sum(p) };\n"
    "atom main() -> i64 requires: true; ensures: true; body: { 0 };\n"
)
COMPOSITE_MIXED_F64_SOURCE = (
    "struct Q { a: i64, b: f64 }\n"
    "atom mkq(a: i64, b: f64) -> Q requires: true; ensures: true; "
    "body: { Q { a: a, b: b } };\n"
    "atom getb(q: Q) -> f64 requires: true; ensures: true; body: { q.b };\n"
    "atom use_q(x: f64) -> f64 requires: true; ensures: true; "
    "body: { getb(mkq(1, x)) };\n"
    "atom main() -> i64 requires: true; ensures: true; body: { 0 };\n"
)
F64_SOURCE = (
    "atom fadd(x: f64, y: f64) -> f64 requires: true; ensures: true; "
    "body: { x * y + x };\n"
    "atom feq(x: f64, y: f64) -> bool requires: true; "
    "ensures: result == (x == y); body: { x == y };\n"
    "atom mixed(x: i64, y: f64) -> f64 requires: true; ensures: true; "
    "body: { y };\n"
    "atom main() -> i64 requires: true; ensures: true; body: { 0 };\n"
)
EXPECTED_CHECKED = BASE_DISCHARGED | (
    set(DESCRIPTOR["checks_performed"]) & OBJECT_MACHINE_CHECKS
)
EXPECTED_LEAF_CHECKED = EXPECTED_CHECKED - {
    "machine_code_direct_call_site_tv",
    "machine_code_forward_branch_function_tv",
    "machine_code_acyclic_branch_function_tv",
    "machine_code_conditional_call_function_tv",
    "machine_code_bounded_loop_function_tv",
}


def _write_core(tmp_path: Path, exit_code: int = 0, stdout=DESCRIPTOR) -> Path:
    core = tmp_path / "mumei-stub"
    output = stdout if isinstance(stdout, str) else json.dumps(stdout)
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "recheck-machine-tv" ]; then\n'
        '    if [ "$3" != "--expected-build-id" ]; then exit 2; fi\n'
        f'    if [ "$4" != "{BUILD_ID}" ]; then exit 1; fi\n'
        '    if [ "$5" != "--json" ]; then exit 2; fi\n'
        f"    exit_code={exit_code}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"        printf '%s' '{output}'\n"
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
    (bundle / RECORD_FILE).write_text(json.dumps(RECORD))
    for name in FILE_MEMBERS.values():
        (bundle / name).write_text(f"bytes of {name}")
    return bundle


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "native-source.mm"
    source.write_text(SOURCE)
    return source


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


def _run(capsys, argv):
    try:
        code = main_machine_tv_recheck(
            build_machine_tv_recheck_parser().parse_args(argv)
        )
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _assert_partition(report, expected_discharged=frozenset()):
    assert report["expected_build_id"] == BUILD_ID
    assert set(report.get("discharged_checks", [])) == set(expected_discharged)
    assert report["checks_not_performed"] == sorted(
        ALL_CHECKS - set(expected_discharged)
    )


def _expected_discharged_checks(descriptor):
    return BASE_DISCHARGED | (
        set(descriptor["checks_performed"]) & OBJECT_MACHINE_CHECKS
    )


def test_checked_descriptor_discharges_listed_checks_and_reports_aggregates(
    tmp_path, capsys
):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == (
        "mumei.native-machine-tv-recheck-report/v1"
    )
    assert report["machine_tv_recheck"] == "checked"
    assert report["machine_tv_schema"] == MACHINE_TV_SCHEMA
    assert report["register_convention_assumed"] == DESCRIPTOR[
        "register_convention_assumed"
    ]
    assert report["input_domain"] == "pure_i64_inputs"
    assert report["function_outcomes"] == {
        "equivalent_within_profile": 1,
        "outside_profile": 1,
    }
    assert "__mumei_user_main" not in out
    assert '"main"' not in out
    assert report["discharged_checks"] == sorted(EXPECTED_LEAF_CHECKED)
    assert "machine_code_entry_wrapper_tv" in report["checks_not_performed"]
    assert "object_translation_correspondence" not in report["discharged_checks"]
    assert "machine_code_direct_call_site_tv" not in report["discharged_checks"]
    assert report["sequence"]["selected_result"] is not None
    _assert_partition(report, EXPECTED_LEAF_CHECKED)


def test_descriptor_without_equivalent_function_leaves_leaf_tv_unperformed(
    tmp_path, capsys
):
    descriptor = {
        **DESCRIPTOR,
        "functions": {"main": {"outcome": "outside_profile"}},
        "checks_performed": [
            "toolchain_object_executable_reproduction",
            "object_symbol_correspondence",
            "object_call_edge_correspondence",
            "object_link_correspondence",
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    expected = _expected_discharged_checks(descriptor)
    assert report["machine_tv_recheck"] == "checked"
    assert report["function_outcomes"] == {
        "equivalent_within_profile": 0,
        "outside_profile": 1,
    }
    assert "machine_code_leaf_function_tv" not in report["discharged_checks"]
    assert "machine_code_acyclic_branch_function_tv" not in report["discharged_checks"]
    _assert_partition(report, expected)


def test_direct_call_site_check_is_discharged_when_listed_as_performed(
    tmp_path, capsys
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            *DESCRIPTOR["checks_performed"],
            "machine_code_direct_call_site_tv",
        ],
        "checks_not_performed": [
            "machine_code_forward_branch_function_tv",
            "machine_code_acyclic_branch_function_tv",
            "machine_code_conditional_call_function_tv",
            "machine_code_bounded_loop_function_tv",
            "machine_code_tv_cyclic_control_flow_functions",
            "object_translation_correspondence",
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    expected = _expected_discharged_checks(descriptor)
    assert "machine_code_direct_call_site_tv" in report["discharged_checks"]
    _assert_partition(report, expected)


def test_direct_call_and_leaf_checks_stay_unperformed_when_not_listed(
    tmp_path, capsys
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            name
            for name in DESCRIPTOR["checks_performed"]
            if name != "machine_code_leaf_function_tv"
        ],
        "checks_not_performed": [
            "machine_code_direct_call_site_tv",
            "machine_code_leaf_function_tv",
            "machine_code_forward_branch_function_tv",
            "machine_code_acyclic_branch_function_tv",
            "machine_code_conditional_call_function_tv",
            "machine_code_bounded_loop_function_tv",
            "machine_code_tv_cyclic_control_flow_functions",
            "object_translation_correspondence",
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    expected = _expected_discharged_checks(descriptor)
    assert "machine_code_direct_call_site_tv" not in report["discharged_checks"]
    assert "machine_code_forward_branch_function_tv" not in report["discharged_checks"]
    assert "machine_code_leaf_function_tv" not in report["discharged_checks"]
    assert "machine_code_acyclic_branch_function_tv" not in report["discharged_checks"]
    assert "machine_code_forward_branch_function_tv" in report["checks_not_performed"]
    _assert_partition(report, expected)


def test_forward_branch_check_is_discharged_when_listed_as_performed(
    tmp_path, capsys
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            *DESCRIPTOR["checks_performed"],
            "machine_code_forward_branch_function_tv",
        ],
        "checks_not_performed": [
            "machine_code_direct_call_site_tv",
            "machine_code_acyclic_branch_function_tv",
            "machine_code_conditional_call_function_tv",
            "machine_code_bounded_loop_function_tv",
            "machine_code_tv_cyclic_control_flow_functions",
            "object_translation_correspondence",
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    expected = _expected_discharged_checks(descriptor)
    assert "machine_code_forward_branch_function_tv" in report["discharged_checks"]
    assert "machine_code_forward_branch_function_tv" not in report["checks_not_performed"]
    _assert_partition(report, expected)


def test_acyclic_branch_check_is_discharged_when_listed_as_performed(
    tmp_path, capsys
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            *DESCRIPTOR["checks_performed"],
            "machine_code_acyclic_branch_function_tv",
        ],
        "checks_not_performed": [
            "machine_code_direct_call_site_tv",
            "machine_code_forward_branch_function_tv",
            "machine_code_conditional_call_function_tv",
            "machine_code_bounded_loop_function_tv",
            "machine_code_tv_cyclic_control_flow_functions",
            "object_translation_correspondence",
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    expected = _expected_discharged_checks(descriptor)
    assert "machine_code_acyclic_branch_function_tv" in report["discharged_checks"]
    assert "machine_code_acyclic_branch_function_tv" not in report["checks_not_performed"]
    _assert_partition(report, expected)


def test_conditional_call_check_is_discharged_when_listed_as_performed(
    tmp_path, capsys
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            *DESCRIPTOR["checks_performed"],
            "machine_code_conditional_call_function_tv",
        ],
        "checks_not_performed": [
            "machine_code_direct_call_site_tv",
            "machine_code_forward_branch_function_tv",
            "machine_code_acyclic_branch_function_tv",
            "machine_code_bounded_loop_function_tv",
            "machine_code_tv_cyclic_control_flow_functions",
            "object_translation_correspondence",
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    expected = _expected_discharged_checks(descriptor)
    assert "machine_code_conditional_call_function_tv" in report["discharged_checks"]
    assert "machine_code_conditional_call_function_tv" not in report["checks_not_performed"]
    _assert_partition(report, expected)


def test_bounded_loop_check_is_discharged_when_listed_as_performed(
    tmp_path, capsys
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            *DESCRIPTOR["checks_performed"],
            "machine_code_bounded_loop_function_tv",
        ],
        "checks_not_performed": [
            "machine_code_direct_call_site_tv",
            "machine_code_forward_branch_function_tv",
            "machine_code_acyclic_branch_function_tv",
            "machine_code_conditional_call_function_tv",
            "machine_code_tv_cyclic_control_flow_functions",
            "object_translation_correspondence",
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    expected = _expected_discharged_checks(descriptor)
    assert "machine_code_bounded_loop_function_tv" in report["discharged_checks"]
    assert "machine_code_bounded_loop_function_tv" not in report["checks_not_performed"]
    _assert_partition(report, expected)


def test_forward_branch_check_stays_unperformed_when_not_listed(
    tmp_path, capsys
):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "machine_code_forward_branch_function_tv" in report["checks_not_performed"]
    assert "machine_code_forward_branch_function_tv" not in report["discharged_checks"]


def test_acyclic_branch_check_stays_unperformed_when_not_listed(
    tmp_path, capsys
):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "machine_code_acyclic_branch_function_tv" in report["checks_not_performed"]
    assert "machine_code_acyclic_branch_function_tv" not in report["discharged_checks"]


def test_conditional_call_check_stays_unperformed_when_not_listed(
    tmp_path, capsys
):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "machine_code_conditional_call_function_tv" in report["checks_not_performed"]
    assert "machine_code_conditional_call_function_tv" not in report["discharged_checks"]


def test_bounded_loop_check_stays_unperformed_when_not_listed(
    tmp_path, capsys
):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "machine_code_bounded_loop_function_tv" in report["checks_not_performed"]
    assert "machine_code_bounded_loop_function_tv" not in report["discharged_checks"]


@pytest.mark.parametrize(
    ("placement", "expected_discharged"),
    [("performed", True), ("not_performed", False), ("absent", False)],
)
def test_entry_wrapper_check_requires_performed_descriptor_list(
    tmp_path, capsys, placement, expected_discharged
):
    check = "machine_code_entry_wrapper_tv"
    performed = [
        name for name in DESCRIPTOR["checks_performed"] if name != check
    ]
    not_performed = [
        name for name in DESCRIPTOR["checks_not_performed"] if name != check
    ]
    if placement == "performed":
        performed.append(check)
    elif placement == "not_performed":
        not_performed.append(check)
    not_performed.append("object_entry_wrapper_semantics")
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": performed,
        "checks_not_performed": not_performed,
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert (check in report["discharged_checks"]) is expected_discharged
    assert (check in report["checks_not_performed"]) is not expected_discharged
    assert "object_entry_wrapper_semantics" not in OBJECT_CHECK_VOCABULARY
    assert "object_entry_wrapper_semantics" not in report["checks_not_performed"]


def test_machine_tv_assumption_marker_set_is_exact():
    assert MACHINE_TV_ASSUMPTION_MARKERS == frozenset(
        {
            "machine_code_callee_saved_preservation_assumed_for_external_callees",
            "machine_code_tv_mxcsr_control_state",
            "machine_code_tv_nan_payload_bits",
        }
    )


@pytest.mark.parametrize(
    "check",
    ["machine_code_callee_saved_register_preservation"],
)
def test_callee_saved_check_is_discharged_only_when_listed(
    tmp_path, capsys, check
):
    assert check in MACHINE_TV_OBJECT_CHECKS
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            *(name for name in DESCRIPTOR["checks_performed"] if name != check),
            check,
        ],
        "checks_not_performed": [
            name for name in DESCRIPTOR["checks_not_performed"] if name != check
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert check in report["discharged_checks"]
    assert check not in report["checks_not_performed"]


@pytest.mark.parametrize(
    "check",
    [
        "machine_code_callee_saved_register_preservation",
        "machine_code_callee_saved_preservation_assumed_for_external_callees",
    ],
)
def test_callee_saved_check_stays_unperformed_when_absent(
    tmp_path, capsys, check
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            name for name in DESCRIPTOR["checks_performed"] if name != check
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert check in report["checks_not_performed"]
    assert check not in report["discharged_checks"]


@pytest.mark.parametrize(
    ("placement", "expected_discharged"),
    [("performed", True), ("not_performed", False), ("absent", False)],
)
def test_f64_check_requires_performed_descriptor_list(
    tmp_path, capsys, placement, expected_discharged
):
    check = "machine_code_f64_scalar_function_tv"
    performed = [
        name for name in DESCRIPTOR["checks_performed"] if name != check
    ]
    not_performed = [
        name for name in DESCRIPTOR["checks_not_performed"] if name != check
    ]
    if placement == "performed":
        performed.append(check)
    elif placement == "not_performed":
        not_performed.append(check)
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": performed,
        "checks_not_performed": not_performed,
        "register_convention_assumed": F64_REGISTER_CONVENTION,
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert (check in report["discharged_checks"]) is expected_discharged
    assert (check in report["checks_not_performed"]) is not expected_discharged
    assert report["register_convention_assumed"] == F64_REGISTER_CONVENTION
    _assert_partition(report, _expected_discharged_checks(descriptor))


@pytest.mark.parametrize(
    ("placement", "expected_discharged"),
    [("performed", True), ("not_performed", False), ("absent", False)],
)
@pytest.mark.parametrize(
    "register_convention",
    [
        COMPOSITE_AGGREGATE_REGISTER_CONVENTION,
        COMPOSITE_SSE_AGGREGATE_REGISTER_CONVENTION,
    ],
)
def test_composite_aggregate_check_requires_performed_descriptor_list(
    tmp_path, capsys, placement, expected_discharged, register_convention
):
    check = "machine_code_composite_register_aggregate_tv"
    assert check not in MACHINE_TV_ASSUMPTION_MARKERS
    performed = [
        name for name in DESCRIPTOR["checks_performed"] if name != check
    ]
    not_performed = [
        name for name in DESCRIPTOR["checks_not_performed"] if name != check
    ]
    if placement == "performed":
        performed.append(check)
    elif placement == "not_performed":
        not_performed.append(check)
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": performed,
        "checks_not_performed": not_performed,
        "register_convention_assumed": register_convention,
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert (check in report["discharged_checks"]) is expected_discharged
    assert (check in report["checks_not_performed"]) is not expected_discharged
    assert (
        report["register_convention_assumed"]
        == register_convention
    )
    _assert_partition(report, _expected_discharged_checks(descriptor))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "mumei.foreign-machine-code-tv/v1"),
        ("build_id", "b" * 64),
    ],
)
def test_composite_aggregate_check_is_not_discharged_by_foreign_or_invalid_descriptor(
    tmp_path, capsys, field, value
):
    check = "machine_code_composite_register_aggregate_tv"
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [*DESCRIPTOR["checks_performed"], check],
        "register_convention_assumed": COMPOSITE_AGGREGATE_REGISTER_CONVENTION,
        field: value,
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert check not in report["discharged_checks"]
    assert check in report["checks_not_performed"]
    assert "register_convention_assumed" not in report


@pytest.mark.parametrize("marker", sorted(MACHINE_TV_ASSUMPTION_MARKERS))
def test_assumption_markers_never_discharge_when_forged(
    tmp_path, capsys, marker
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [*DESCRIPTOR["checks_performed"], marker],
        "checks_not_performed": [
            check
            for check in DESCRIPTOR["checks_not_performed"]
            if check != marker
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert marker not in report["discharged_checks"]
    assert marker in report["checks_not_performed"]
    _assert_partition(report, _expected_discharged_checks(descriptor))


@pytest.mark.parametrize(
    "out_of_profile_check",
    [
        "machine_code_tv_branching_functions",
        "machine_code_tv_backward_branch_functions",
        "machine_code_tv_cyclic_control_flow_functions",
    ],
)
def test_core_out_of_profile_branch_names_remain_accepted(
    tmp_path, capsys, out_of_profile_check
):
    descriptor = {
        **DESCRIPTOR,
        "checks_not_performed": [
            out_of_profile_check,
            "machine_code_bounded_loop_function_tv",
            "object_translation_correspondence",
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["machine_tv_recheck"] == "checked"
    assert "machine_code_forward_branch_function_tv" in report["checks_not_performed"]
    assert "machine_code_acyclic_branch_function_tv" in report["checks_not_performed"]
    assert "machine_code_conditional_call_function_tv" in report["checks_not_performed"]


def test_descriptor_cannot_discharge_full_object_translation(tmp_path, capsys):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            "machine_code_leaf_function_tv",
            "object_translation_correspondence",
            "unknown_check",
            7,
            None,
        ],
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    expected = BASE_DISCHARGED | {"machine_code_leaf_function_tv"}
    assert report["discharged_checks"] == sorted(expected)
    assert "object_translation_correspondence" not in report["discharged_checks"]
    _assert_partition(report, expected)


@pytest.mark.parametrize("checks_performed", [None, {"not": "a list"}])
def test_non_list_checks_performed_discharge_no_object_checks(
    tmp_path, capsys, checks_performed
):
    descriptor = {**DESCRIPTOR, "checks_performed": checks_performed}
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["machine_tv_schema"] == MACHINE_TV_SCHEMA
    _assert_partition(report, BASE_DISCHARGED)


@pytest.mark.parametrize(
    "stdout",
    [
        {
            "schema_version": OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA,
            "build_id": BUILD_ID,
            "checks_performed": [
                "machine_code_entry_wrapper_tv",
                "machine_code_leaf_function_tv",
                "machine_code_bounded_loop_function_tv",
                "machine_code_callee_saved_register_preservation",
            ],
        },
        {
            "schema_version": "mumei.other/v1",
            "build_id": BUILD_ID,
            "checks_performed": [
                "machine_code_bounded_loop_function_tv",
                "machine_code_callee_saved_register_preservation",
                "machine_code_entry_wrapper_tv",
            ],
        },
        {
            "schema_version": MACHINE_TV_SCHEMA,
            "build_id": "b" * 64,
            "checks_performed": [
                "machine_code_bounded_loop_function_tv",
                "machine_code_callee_saved_register_preservation",
                "machine_code_entry_wrapper_tv",
            ],
        },
        "not-json",
        ["not", "an", "object"],
    ],
)
def test_descriptor_schema_and_build_id_gate_machine_tv_fields(
    tmp_path, capsys, stdout
):
    core = _write_core(tmp_path, stdout=stdout)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["machine_tv_recheck"] == "checked"
    assert "machine_tv_schema" not in report
    assert "register_convention_assumed" not in report
    assert "input_domain" not in report
    assert "function_outcomes" not in report
    assert "callee_saved_preservation" not in report
    assert report["discharged_checks"] == sorted(BASE_DISCHARGED)
    assert "machine_code_bounded_loop_function_tv" not in report["discharged_checks"]
    assert "machine_code_entry_wrapper_tv" not in report["discharged_checks"]
    assert "machine_code_entry_wrapper_tv" in report["checks_not_performed"]
    assert (
        "machine_code_callee_saved_register_preservation"
        not in report["discharged_checks"]
    )
    _assert_partition(report, BASE_DISCHARGED)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("register_convention_assumed", "x" * 257),
        ("register_convention_assumed", 7),
        ("input_domain", "x" * 257),
        ("input_domain", None),
    ],
)
def test_descriptor_strings_are_echoed_only_when_bounded(
    tmp_path, capsys, field, value
):
    descriptor = {**DESCRIPTOR, field: value}
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert field not in report
    assert report["machine_tv_schema"] == MACHINE_TV_SCHEMA
    _assert_partition(report, EXPECTED_LEAF_CHECKED)


def test_function_outcomes_ignore_malformed_entries(tmp_path, capsys):
    descriptor = {
        **DESCRIPTOR,
        "functions": {
            "eq": {"outcome": "equivalent_within_profile"},
            "outside": {"outcome": "outside_profile"},
            "list": [],
            "malformed_outcome": {"outcome": []},
            "other": {"outcome": "different"},
        },
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["function_outcomes"] == {
        "equivalent_within_profile": 1,
        "outside_profile": 1,
    }
    assert '"eq":' not in out and '"outside":' not in out


def test_callee_saved_preservation_counts_valid_values_without_function_names(
    tmp_path, capsys
):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            *DESCRIPTOR["checks_performed"],
            "machine_code_entry_wrapper_tv",
        ],
        "checks_not_performed": [
            *DESCRIPTOR["checks_not_performed"],
            "object_entry_wrapper_semantics",
        ],
        "functions": {
            "main": {
                "role": "entry_wrapper",
                "outcome": "equivalent_within_profile",
                "callee_saved_preservation": "preserved",
            },
            "__mumei_user_main": {
                "outcome": "equivalent_within_profile",
                "callee_saved_preservation": "preserved",
            },
            "preserved_function": {
                "outcome": "equivalent_within_profile",
                "callee_saved_preservation": "preserved",
            },
            "violated_function": {
                "outcome": "equivalent_within_profile",
                "callee_saved_preservation": "violated",
            },
            "unknown_function": {
                "outcome": "equivalent_within_profile",
                "callee_saved_preservation": "unknown",
            },
            "function_without_preservation": {
                "outcome": "outside_profile",
            },
        },
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["function_outcomes"] == {
        "equivalent_within_profile": 5,
        "outside_profile": 1,
    }
    assert report["callee_saved_preservation"] == {
        "preserved": 3,
        "violated": 1,
        "unknown": 1,
    }
    assert "machine_code_entry_wrapper_tv" in report["discharged_checks"]
    assert "object_entry_wrapper_semantics" not in report["checks_not_performed"]
    for function_name in descriptor["functions"]:
        assert f'"{function_name}"' not in out


def test_callee_saved_preservation_omitted_when_no_function_has_field(
    tmp_path, capsys
):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "callee_saved_preservation" not in report


@pytest.mark.parametrize("preservation", ["invalid", 7, None])
def test_callee_saved_preservation_omitted_for_invalid_value(
    tmp_path, capsys, preservation
):
    descriptor = {
        **DESCRIPTOR,
        "functions": {
            "valid": {"callee_saved_preservation": "preserved"},
            "invalid": {"callee_saved_preservation": preservation},
        },
    }
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "callee_saved_preservation" not in report


@pytest.mark.parametrize(
    "functions",
    [["not", "a", "map"], {"malformed": []}, {"malformed": None}],
)
def test_callee_saved_preservation_omitted_for_malformed_functions(
    tmp_path, capsys, functions
):
    descriptor = {**DESCRIPTOR, "functions": functions}
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "callee_saved_preservation" not in report


def test_non_dict_functions_omits_aggregate_field(tmp_path, capsys):
    descriptor = {**DESCRIPTOR, "functions": ["not", "a", "map"]}
    core = _write_core(tmp_path, stdout=descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "function_outcomes" not in report
    assert "callee_saved_preservation" not in report


@pytest.mark.parametrize(
    ("exit_code", "outcome"),
    [(3, "inconclusive"), (1, None), (2, None), (7, None)],
)
def test_exit_mapping(tmp_path, capsys, exit_code, outcome):
    core = _write_core(tmp_path, exit_code=exit_code)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    if outcome is None:
        assert "machine_tv_recheck" not in report
    else:
        assert report["machine_tv_recheck"] == outcome
    assert "discharged_checks" not in report
    assert report["normalized"]["exit_code"] == exit_code
    _assert_partition(report)


def test_wrong_build_id_has_no_outcome_or_discharges(tmp_path, capsys):
    core = _write_core(
        tmp_path,
        stdout={
            **DESCRIPTOR,
            "checks_performed": [
                *DESCRIPTOR["checks_performed"],
                "machine_code_entry_wrapper_tv",
            ],
        },
    )
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    argv = _args(core, bundle, source)
    wrong_id = "b" * 64
    argv[argv.index("--expected-build-id") + 1] = wrong_id
    code, out, _ = _run(capsys, argv)
    assert code == 0
    report = json.loads(out)
    assert report["expected_build_id"] == wrong_id
    assert "machine_tv_recheck" not in report
    assert "discharged_checks" not in report
    assert report["normalized"]["exit_code"] == 1
    assert report["checks_not_performed"] == sorted(ALL_CHECKS)
    assert "machine_code_entry_wrapper_tv" in report["checks_not_performed"]


def test_inputs_changed_suppresses_machine_tv_outcome(
    tmp_path, capsys, monkeypatch
):
    from agent import native_machine_tv_recheck as route

    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    original = route._attempt_fingerprint
    calls = 0

    def change_member(args, members):
        nonlocal calls
        if calls:
            (bundle / next(iter(FILE_MEMBERS.values()))).write_text("changed")
        calls += 1
        return original(args, members)

    monkeypatch.setattr(route, "_attempt_fingerprint", change_member)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "machine_tv_recheck" not in report
    assert "discharged_checks" not in report
    _assert_partition(report)


def test_cli_dispatch(tmp_path):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent",
            "native-machine-tv-recheck",
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
    assert report["machine_tv_recheck"] == "checked"
    assert report["machine_tv_schema"] == MACHINE_TV_SCHEMA


def test_mcp_tool_dispatch(tmp_path):
    from agent import mcp_server

    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    result = json.loads(
        mcp_server.native_machine_tv_recheck(
            str(core), str(bundle), str(source), BUILD_ID
        )
    )
    assert result["status"] == "ok"
    assert result["report"]["machine_tv_recheck"] == "checked"


@pytest.fixture
def real_core():
    path = os.environ.get("MUMEI_BIN")
    if path and Path(path).is_absolute() and Path(path).is_file():
        return path
    found = shutil.which("mumei")
    if found:
        return found
    pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")


def _build_real_bundle(
    tmp_path: Path, real_core: str, source_text: str = SOURCE
) -> tuple[Path, Path]:
    source = tmp_path / "native-source.mm"
    source.write_text(source_text)
    bundle = tmp_path / "real-bundle"
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
    return bundle, source


def _real_machine_tv_descriptor(
    real_core: str, bundle: Path, source: Path, build_id: str
) -> dict:
    checked = subprocess.run(
        [
            real_core,
            "native-bundle",
            "recheck-machine-tv",
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
    assert checked.returncode == 0, checked.stderr
    descriptor = json.loads(checked.stdout)
    function_outcomes = {
        value.get("outcome")
        for value in descriptor["functions"].values()
        if isinstance(value, dict)
    }
    unexpected = function_outcomes - {
        "equivalent_within_profile",
        "outside_profile",
    }
    assert not unexpected, f"Unexpected Core machine-TV outcomes: {unexpected}"
    return descriptor


def _expected_function_outcomes(descriptor: dict) -> dict:
    return {
        outcome: sum(
            isinstance(function, dict) and function.get("outcome") == outcome
            for function in descriptor["functions"].values()
        )
        for outcome in ("equivalent_within_profile", "outside_profile")
    }


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_leaf_function(tmp_path, capsys, real_core):
    bundle, source = _build_real_bundle(tmp_path, real_core)
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    assert (
        "machine_code_callee_saved_register_preservation"
        in descriptor["checks_performed"]
    )
    assert (
        "machine_code_callee_saved_preservation_assumed_for_external_callees"
        in descriptor["checks_not_performed"]
    )
    assert "machine_code_entry_wrapper_tv" in descriptor["checks_performed"]
    assert "machine_code_entry_wrapper_tv" not in descriptor["checks_not_performed"]
    equivalent_functions = [
        function
        for function in descriptor["functions"].values()
        if isinstance(function, dict)
        and function.get("outcome") == "equivalent_within_profile"
    ]
    wrapper_entry = next(
        function
        for function in descriptor["functions"].values()
        if isinstance(function, dict) and function.get("role") == "entry_wrapper"
    )
    assert wrapper_entry["outcome"] == "equivalent_within_profile"
    assert equivalent_functions
    assert all(
        function.get("callee_saved_preservation") == "preserved"
        for function in equivalent_functions
    )
    assert "machine_code_leaf_function_tv" in descriptor["checks_performed"]
    assert "machine_code_direct_call_site_tv" in descriptor["checks_not_performed"]
    assert "machine_code_forward_branch_function_tv" in descriptor["checks_not_performed"]
    assert "machine_code_acyclic_branch_function_tv" in descriptor["checks_not_performed"]
    assert "machine_code_conditional_call_function_tv" in descriptor["checks_not_performed"]
    assert "machine_code_bounded_loop_function_tv" in descriptor["checks_not_performed"]
    assert (
        "machine_code_tv_cyclic_control_flow_functions"
        not in descriptor["checks_not_performed"]
    )
    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["machine_tv_recheck"] == "checked"
    assert report["expected_build_id"] == build_id
    assert report["machine_tv_schema"] == MACHINE_TV_SCHEMA
    assert report["register_convention_assumed"] == (
        "sysv_x86_64_integer_args_rdi_rsi_rdx_rcx_r8_r9_result_rax"
    )
    assert report["function_outcomes"] == _expected_function_outcomes(descriptor)
    expected_preservation_counts = {
        value: sum(
            isinstance(function, dict)
            and function.get("callee_saved_preservation") == value
            for function in descriptor["functions"].values()
        )
        for value in ("preserved", "violated", "unknown")
    }
    assert report["callee_saved_preservation"] == expected_preservation_counts
    assert "machine_code_leaf_function_tv" in report["discharged_checks"]
    assert "machine_code_entry_wrapper_tv" in report["discharged_checks"]
    assert (
        "machine_code_callee_saved_register_preservation"
        in report["discharged_checks"]
    )
    assert (
        "machine_code_callee_saved_preservation_assumed_for_external_callees"
        in report["checks_not_performed"]
    )
    assert "machine_code_direct_call_site_tv" not in report["discharged_checks"]
    assert "machine_code_conditional_call_function_tv" not in report["discharged_checks"]
    assert "machine_code_bounded_loop_function_tv" not in report["discharged_checks"]
    assert "object_translation_correspondence" not in report["discharged_checks"]
    assert "machine_code_forward_branch_function_tv" not in report["discharged_checks"]
    expected_discharged = EXPECTED_LEAF_CHECKED | {
        "machine_code_entry_wrapper_tv",
    }
    assert report["discharged_checks"] == sorted(expected_discharged)
    assert '"main"' not in out
    assert report["checks_not_performed"] == sorted(
        ALL_CHECKS - expected_discharged
    )


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_scalar_f64(tmp_path, capsys, real_core):
    bundle, source = _build_real_bundle(tmp_path, real_core, F64_SOURCE)
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    f64_check = "machine_code_f64_scalar_function_tv"
    assert f64_check in descriptor["checks_performed"]
    assert descriptor["register_convention_assumed"] == F64_REGISTER_CONVENTION
    for marker in MACHINE_TV_ASSUMPTION_MARKERS:
        assert marker in descriptor["checks_not_performed"]
        assert marker not in descriptor["checks_performed"]

    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["machine_tv_recheck"] == "checked"
    assert report["register_convention_assumed"] == F64_REGISTER_CONVENTION
    assert f64_check in report["discharged_checks"]
    for marker in MACHINE_TV_ASSUMPTION_MARKERS:
        assert marker in report["checks_not_performed"]
        assert marker not in report["discharged_checks"]


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_composite_integer_aggregate(
    tmp_path, capsys, real_core
):
    bundle, source = _build_real_bundle(
        tmp_path, real_core, COMPOSITE_AGGREGATE_SOURCE
    )
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    check = "machine_code_composite_register_aggregate_tv"
    assert check in descriptor["checks_performed"]
    for name in ("sum", "mk", "caller", "fwd"):
        assert (
            descriptor["functions"][name]["outcome"] == "equivalent_within_profile"
        )
    assert (
        descriptor["register_convention_assumed"]
        == COMPOSITE_AGGREGATE_REGISTER_CONVENTION
    )

    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["machine_tv_recheck"] == "checked"
    assert check in report["discharged_checks"]
    assert (
        report["register_convention_assumed"]
        == COMPOSITE_AGGREGATE_REGISTER_CONVENTION
    )


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_composite_mixed_integer_f64_aggregate(
    tmp_path, capsys, real_core
):
    bundle, source = _build_real_bundle(
        tmp_path, real_core, COMPOSITE_MIXED_F64_SOURCE
    )
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    check = "machine_code_composite_register_aggregate_tv"
    assert check in descriptor["checks_performed"]
    for name in ("mkq", "getb", "use_q"):
        assert (
            descriptor["functions"][name]["outcome"] == "equivalent_within_profile"
        )
    assert (
        descriptor["register_convention_assumed"]
        == COMPOSITE_SSE_AGGREGATE_REGISTER_CONVENTION
    )

    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["machine_tv_recheck"] == "checked"
    assert check in report["discharged_checks"]
    assert (
        report["register_convention_assumed"]
        == COMPOSITE_SSE_AGGREGATE_REGISTER_CONVENTION
    )


DIRECT_CALL_SOURCE = (
    "atom helper(x: i64) -> i64 requires: x > 0; "
    "ensures: result == x + 1; body: { x + 1 };\n"
    "atom main() -> i64 requires: true; ensures: result == 6; "
    "body: { helper(5) };\n"
)

CONDITIONAL_CALL_SOURCE = (
    "atom helper(x: i64) -> i64 requires: x >= 0 && x <= 100; "
    "ensures: result >= 1; body: { x + 1 };\n"
    "atom cc(x: i64) -> i64 requires: x >= 0 && x <= 100; "
    "ensures: true; body: { if x > 5 { helper(x) } else { 0 } };\n"
    "atom cc_both(x: i64) -> i64 requires: x >= 0 && x <= 100; "
    "ensures: result >= 1; "
    "body: { if x > 5 { helper(x) } else { helper(5) } };\n"
    "atom cc_result(x: i64) -> i64 requires: x >= 0 && x <= 100; "
    "ensures: true; body: { if helper(x) > 5 { 10 } else { 0 } };\n"
    "atom main() -> i64 requires: true; ensures: true; body: { cc(1) };\n"
)

BOUNDED_LOOP_SOURCE = (
    "atom loop_count(n: i64) -> i64\n"
    "requires: n >= 0 && n <= 10;\n"
    "ensures: true;\n"
    "body: {\n"
    "    let i = 0;\n"
    "    while i < n\n"
    "    invariant: i >= 0 && i <= n\n"
    "    decreases: n - i\n"
    "    {\n"
    "        i = i + 1;\n"
    "    };\n"
    "    i\n"
    "};\n"
    "atom main() -> i64\n"
    "requires: true;\n"
    "ensures: true;\n"
    "body: { loop_count(3) };\n"
)

FORWARD_BRANCH_SOURCE = (
    "atom absd(x: i64, y: i64) -> i64 requires: x >= 0 && x <= 1000 && "
    "y >= 0 && y <= 1000; ensures: result >= 0; "
    "body: { if x > y { x - y } else { y - x } };\n"
    "atom clamp(x: i64) -> i64 requires: true; ensures: result <= 10; "
    "body: { if x > 10 { 10 } else { x } };\n"
    "atom pick(b: bool, x: i64) -> i64 requires: true; ensures: true; "
    "body: { if b { x } else { 0 } };\n"
    "atom main() -> i64 requires: true; ensures: result >= 0; "
    "body: { absd(7, 3) };\n"
)

ACYCLIC_BACKWARD_BRANCH_SOURCE = (
    "atom absd(x: i64, y: i64) -> i64 requires: x >= 0 && x <= 1000 && "
    "y >= 0 && y <= 1000; ensures: result >= 0; "
    "body: { if x > y { x - y } else { y - x } };\n"
    "atom clamp(x: i64) -> i64 requires: true; ensures: result <= 10; "
    "body: { if x > 10 { 10 } else { x } };\n"
    "atom pick(b: bool, x: i64) -> i64 requires: true; ensures: true; "
    "body: { if b { x } else { 0 } };\n"
    "atom band(x: i64, y: i64) -> i64 requires: x >= 0 && x <= 100 && "
    "y >= 0 && y <= 100; ensures: true; "
    "body: { if x > 5 && y > 5 { x + y } else { 0 } };\n"
    "atom main() -> i64 requires: true; ensures: result >= 0; "
    "body: { absd(7, 3) };\n"
)


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_direct_call_sites(
    tmp_path, capsys, real_core
):
    bundle, source = _build_real_bundle(
        tmp_path, real_core, DIRECT_CALL_SOURCE
    )
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    assert "machine_code_direct_call_site_tv" in descriptor["checks_performed"]
    assert (
        "machine_code_conditional_call_function_tv"
        in descriptor["checks_not_performed"]
    )
    assert "machine_code_bounded_loop_function_tv" in descriptor["checks_not_performed"]
    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["machine_tv_recheck"] == "checked"
    assert report["function_outcomes"] == _expected_function_outcomes(descriptor)
    assert "machine_code_direct_call_site_tv" in report["discharged_checks"]
    assert (
        "machine_code_conditional_call_function_tv"
        not in report["discharged_checks"]
    )
    assert "machine_code_bounded_loop_function_tv" not in report["discharged_checks"]
    assert "machine_code_leaf_function_tv" in report["discharged_checks"]
    assert "machine_code_forward_branch_function_tv" not in report["discharged_checks"]
    assert "machine_code_acyclic_branch_function_tv" not in report["discharged_checks"]
    assert "machine_code_forward_branch_function_tv" in report["checks_not_performed"]
    assert "helper" not in out
    assert "object_translation_correspondence" not in report["discharged_checks"]


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_forward_branch_functions(
    tmp_path, capsys, real_core
):
    bundle, source = _build_real_bundle(
        tmp_path, real_core, FORWARD_BRANCH_SOURCE
    )
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    assert "machine_code_forward_branch_function_tv" in descriptor["checks_performed"]
    assert (
        "machine_code_tv_cyclic_control_flow_functions"
        not in descriptor["checks_not_performed"]
    )
    assert (
        "machine_code_conditional_call_function_tv"
        in descriptor["checks_not_performed"]
    )
    assert "machine_code_bounded_loop_function_tv" in descriptor["checks_not_performed"]
    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["machine_tv_recheck"] == "checked"
    assert report["function_outcomes"] == _expected_function_outcomes(descriptor)
    assert "absd" not in out
    assert "machine_code_forward_branch_function_tv" in report["discharged_checks"]
    assert (
        "machine_code_conditional_call_function_tv"
        not in report["discharged_checks"]
    )
    assert "machine_code_bounded_loop_function_tv" not in report["discharged_checks"]


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_bounded_loop(
    tmp_path, capsys, real_core
):
    bundle, source = _build_real_bundle(
        tmp_path, real_core, BOUNDED_LOOP_SOURCE
    )
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    assert "machine_code_bounded_loop_function_tv" in descriptor["checks_performed"]
    assert (
        "machine_code_bounded_loop_function_tv"
        not in descriptor["checks_not_performed"]
    )
    assert "machine_code_entry_wrapper_tv" in descriptor["checks_performed"]
    assert "machine_code_entry_wrapper_tv" not in descriptor["checks_not_performed"]
    assert "_and_loops_exiting_within_bound_4" in descriptor["input_domain"]
    assert "machine_code_tv_loop_executions_beyond_bound" in descriptor[
        "checks_not_performed"
    ]
    assert "runtime_cancellation_semantics" in descriptor["checks_not_performed"]
    assert "machine_code_tv_cyclic_control_flow_functions" not in descriptor[
        "checks_not_performed"
    ]

    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    expected_discharged = BASE_DISCHARGED | (
        set(descriptor["checks_performed"]) & OBJECT_MACHINE_CHECKS
    )
    assert report["machine_tv_recheck"] == "checked"
    assert report["input_domain"] == descriptor["input_domain"]
    assert "_and_loops_exiting_within_bound_4" in report["input_domain"]
    assert report["function_outcomes"] == _expected_function_outcomes(descriptor)
    assert "machine_code_bounded_loop_function_tv" in report["discharged_checks"]
    assert "machine_code_entry_wrapper_tv" in report["discharged_checks"]
    assert report["discharged_checks"] == sorted(expected_discharged)
    assert report["checks_not_performed"] == sorted(ALL_CHECKS - expected_discharged)
    assert "object_translation_correspondence" not in report["discharged_checks"]


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_acyclic_backward_branch_functions(
    tmp_path, capsys, real_core
):
    bundle, source = _build_real_bundle(
        tmp_path, real_core, ACYCLIC_BACKWARD_BRANCH_SOURCE
    )
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    assert "machine_code_acyclic_branch_function_tv" in descriptor["checks_performed"]
    assert (
        "machine_code_tv_cyclic_control_flow_functions"
        not in descriptor["checks_not_performed"]
    )
    assert "machine_code_leaf_function_tv" in descriptor["checks_not_performed"]
    assert (
        "machine_code_conditional_call_function_tv"
        in descriptor["checks_not_performed"]
    )
    assert "machine_code_bounded_loop_function_tv" in descriptor["checks_not_performed"]

    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    expected_discharged = _expected_discharged_checks(descriptor)
    assert report["machine_tv_recheck"] == "checked"
    assert report["function_outcomes"] == _expected_function_outcomes(descriptor)
    assert report["discharged_checks"] == sorted(expected_discharged)
    assert report["checks_not_performed"] == sorted(ALL_CHECKS - expected_discharged)
    assert all(name not in out for name in ("absd", "clamp", "pick", "band"))
    assert "object_translation_correspondence" not in report["discharged_checks"]


@pytest.mark.integration
def test_real_core_rechecks_machine_tv_conditional_calls(
    tmp_path, capsys, real_core
):
    bundle, source = _build_real_bundle(
        tmp_path, real_core, CONDITIONAL_CALL_SOURCE
    )
    build_id = hashlib.sha256((bundle / RECORD_FILE).read_bytes()).hexdigest()
    descriptor = _real_machine_tv_descriptor(real_core, bundle, source, build_id)
    assert (
        "machine_code_conditional_call_function_tv"
        in descriptor["checks_performed"]
    )
    assert (
        "machine_code_conditional_call_function_tv"
        not in descriptor["checks_not_performed"]
    )
    assert "machine_code_direct_call_site_tv" in descriptor["checks_performed"]
    assert (
        "machine_code_forward_branch_function_tv"
        in descriptor["checks_not_performed"]
    )
    assert (
        "machine_code_acyclic_branch_function_tv"
        in descriptor["checks_not_performed"]
    )
    assert (
        "machine_code_tv_cyclic_control_flow_functions"
        not in descriptor["checks_not_performed"]
    )
    assert "machine_code_bounded_loop_function_tv" in descriptor["checks_not_performed"]

    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    expected_discharged = BASE_DISCHARGED | (
        set(descriptor["checks_performed"]) & OBJECT_MACHINE_CHECKS
    )
    assert report["machine_tv_recheck"] == "checked"
    assert report["function_outcomes"] == _expected_function_outcomes(descriptor)
    assert (
        "machine_code_conditional_call_function_tv"
        in report["discharged_checks"]
    )
    assert "machine_code_bounded_loop_function_tv" not in report["discharged_checks"]
    assert report["discharged_checks"] == sorted(expected_discharged)
    assert report["checks_not_performed"] == sorted(ALL_CHECKS - expected_discharged)
    assert all(
        f'"{name}"' not in out
        for name in ("helper", "cc", "cc_both", "cc_result")
    )
    assert "object_translation_correspondence" not in report["discharged_checks"]
