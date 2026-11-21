"""Route tests for ``native-object-accept`` through the C11 lifecycle."""

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
from agent.native_object_accept import (
    CHECK_VOCABULARY,
    NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA,
    OBJECT_ACCEPT_CHECKS,
    OBJECT_ACCEPT_WITH_LINK_SCOPE,
    OBJECT_ACCEPT_WITHOUT_LINK_SCOPE,
    OBJECT_SOURCE_MACHINE_CODE_CHECK,
    build_object_accept_parser,
    main_object_accept,
)

BUILD_ID = "a" * 64
ALL_CHECKS = CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY
ENTRY_WRAPPER_CHECK = "machine_code_entry_wrapper_tv"
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
COMPOSITE_WIDE_AGGREGATE_REGISTER_CONVENTION = (
    "sysv_x86_64_integer_args_rdi_rsi_rdx_rcx_r8_r9_result_rax_"
    "llvm_first_class_aggregates_split_into_registers_result_rax_rdx_rcx_xmm0_xmm1"
)
COMPOSITE_WIDE_SSE_AGGREGATE_REGISTER_CONVENTION = (
    "sysv_x86_64_integer_args_rdi_rsi_rdx_rcx_r8_r9_f64_args_xmm0_7_"
    "result_rax_or_xmm0_llvm_first_class_aggregates_split_into_registers_"
    "result_rax_rdx_rcx_xmm0_xmm1"
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
COMPOSITE_THREE_LEAF_SOURCE = (
    "struct T { a: i64, b: i64, c: i64 }\n"
    "atom sum3(p: T) -> i64 requires: true; ensures: true; "
    "body: { p.a + p.b + p.c };\n"
    "atom mk3(a: i64, b: i64, c: i64) -> T requires: true; ensures: true; "
    "body: { T { a: a, b: b, c: c } };\n"
    "atom caller() -> i64 requires: true; ensures: true; "
    "body: { sum3(mk3(1, 2, 3)) };\n"
    "atom fwd(p: T) -> i64 requires: true; ensures: true; "
    "body: { sum3(p) };\n"
    "atom main() -> i64 requires: true; ensures: true; body: { 0 };\n"
)
COMPOSITE_WIDE_MIXED_F64_SOURCE = (
    "struct Q { a: i64, b: f64, c: i64, d: f64 }\n"
    "atom sum4(q: Q) -> f64 requires: true; ensures: true; "
    "body: { q.b + q.d };\n"
    "atom mk4(a: i64, b: f64, c: i64, d: f64) -> Q requires: true; "
    "ensures: true; body: { Q { a: a, b: b, c: c, d: d } };\n"
    "atom caller(x: f64) -> f64 requires: true; ensures: true; "
    "body: { sum4(mk4(1, x, 2, x)) };\n"
    "atom fwd(q: Q) -> f64 requires: true; ensures: true; "
    "body: { sum4(q) };\n"
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
BASE_DISCHARGED = frozenset(
    {
        "artifact_semantics",
        "claim_truth",
        "object_translation_correspondence",
    }
)

DESCRIPTOR = {
    "schema_version": NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA,
    "acceptance": "evaluated",
    "accepted": True,
    "scope": OBJECT_ACCEPT_WITH_LINK_SCOPE,
    "checks_performed": [
        "bundle_identity_binding",
        "object_symbol_correspondence",
        "object_call_edge_correspondence",
        "object_link_correspondence",
        "machine_code_leaf_function_tv",
        "machine_code_bounded_loop_function_tv",
        OBJECT_SOURCE_MACHINE_CODE_CHECK,
    ],
    "checks_not_performed": [
        "producer_authenticity",
        "historical_execution",
        "object_entry_wrapper_semantics",
    ],
    "build_id": BUILD_ID,
    "llvm_sha256": "1" * 64,
    "object_sha256": "2" * 64,
    "register_convention_assumed": "sysv_x86_64_integer_args_result",
    "input_domain": "pure_i64_inputs",
    "functions": {
        "__mumei_user_main": {"outcome": "equivalent_within_profile"},
        "main": {"outcome": "outside_profile", "reason": "not_a_source_atom"},
    },
}

RECORD = {
    "schema": "mumei.native-bundle/v1",
    "files": {key: {} for key in FILE_MEMBERS},
}

SOURCE = "atom main() -> i64 requires: true; ensures: result == 0; body: { 0 };\n"
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


def _write_core(
    tmp_path: Path,
    descriptor=DESCRIPTOR,
    exit_code: int = 0,
    *,
    drift_source: bool = False,
) -> Path:
    core = tmp_path / "mumei-stub"
    output = descriptor if isinstance(descriptor, str) else json.dumps(descriptor)
    drift = '    printf changed > "$7"\n' if drift_source else ""
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "accept-object" ]; then\n'
        '    if [ "$3" != "--expected-build-id" ]; then exit 2; fi\n'
        f'    if [ "$4" != "{BUILD_ID}" ]; then exit 1; fi\n'
        '    if [ "$5" != "--json" ]; then exit 2; fi\n'
        f"    exit_code={exit_code}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"{drift}"
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


def _write_source(tmp_path: Path, source_text: str = SOURCE) -> Path:
    source = tmp_path / "native-source.mm"
    source.write_text(source_text)
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
        code = main_object_accept(build_object_accept_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _assert_partition(report, expected_discharged=frozenset()):
    assert set(report.get("discharged_checks", [])) == set(expected_discharged)
    assert report["checks_not_performed"] == sorted(
        ALL_CHECKS - set(expected_discharged)
    )


@pytest.mark.parametrize(
    ("descriptor", "expected_discharged"),
    [
        (
            DESCRIPTOR,
            BASE_DISCHARGED
            | {
                "object_symbol_correspondence",
                "object_call_edge_correspondence",
                "object_link_correspondence",
                "machine_code_leaf_function_tv",
                "machine_code_bounded_loop_function_tv",
            },
        ),
        (
            {
                **DESCRIPTOR,
                "scope": OBJECT_ACCEPT_WITHOUT_LINK_SCOPE,
                "checks_performed": [
                    check
                    for check in DESCRIPTOR["checks_performed"]
                    if check != "object_link_correspondence"
                ],
            },
            BASE_DISCHARGED
            | {
                "object_symbol_correspondence",
                "object_call_edge_correspondence",
                "machine_code_leaf_function_tv",
                "machine_code_bounded_loop_function_tv",
            },
        ),
    ],
    ids=("with-object-link", "without-object-link"),
)
def test_accepted_descriptor_maps_core_checks_and_reports_bounds(
    tmp_path, capsys, descriptor, expected_discharged
):
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.native-object-accept-report/v1"
    assert report["acceptance"] == "accepted"
    assert report["acceptance_schema"] == NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA
    assert report["scope"] == descriptor["scope"]
    assert report["llvm_sha256"] == descriptor["llvm_sha256"]
    assert report["object_sha256"] == descriptor["object_sha256"]
    assert (
        report["register_convention_assumed"]
        == (descriptor["register_convention_assumed"])
    )
    assert report["input_domain"] == descriptor["input_domain"]
    assert report["function_outcomes"] == {
        "equivalent_within_profile": 1,
        "outside_profile": 1,
    }
    assert "__mumei_user_main" not in out
    assert '"main"' not in out
    assert "not_a_source_atom" not in out
    assert "object_entry_wrapper_semantics" not in OBJECT_CHECK_VOCABULARY
    assert "object_entry_wrapper_semantics" not in report["checks_not_performed"]
    assert "functions" not in report
    assert "object_translation_correspondence" not in descriptor["checks_performed"]
    assert report["sequence"]["selected_result"] is not None
    if descriptor["scope"] == OBJECT_ACCEPT_WITH_LINK_SCOPE:
        assert "object_link_correspondence" in report["discharged_checks"]
    else:
        assert "object_link_correspondence" not in report["discharged_checks"]
    _assert_partition(report, expected_discharged)


@pytest.mark.parametrize(
    ("placement", "expected_discharged"),
    [("performed", True), ("not_performed", False), ("absent", False)],
)
def test_entry_wrapper_check_requires_performed_descriptor_list(
    tmp_path, capsys, placement, expected_discharged
):
    performed = list(DESCRIPTOR["checks_performed"])
    not_performed = list(DESCRIPTOR["checks_not_performed"])
    if placement == "performed":
        performed.append(ENTRY_WRAPPER_CHECK)
    elif placement == "not_performed":
        not_performed.append(ENTRY_WRAPPER_CHECK)
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": performed,
        "checks_not_performed": not_performed,
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
        },
    }
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["acceptance"] == "accepted"
    assert (ENTRY_WRAPPER_CHECK in report["discharged_checks"]) is (
        expected_discharged
    )
    assert (ENTRY_WRAPPER_CHECK in report["checks_not_performed"]) is (
        not expected_discharged
    )
    assert report["function_outcomes"] == {
        "equivalent_within_profile": 2,
        "outside_profile": 0,
    }
    assert '"main"' not in out
    assert "__mumei_user_main" not in out
    assert "object_entry_wrapper_semantics" not in report["checks_not_performed"]
    assert "os_exit_status_observation" not in report["discharged_checks"]
    assert "os_exit_status_observation" not in OBJECT_CHECK_VOCABULARY
    expected = BASE_DISCHARGED | (
        set(performed)
        & (
            OBJECT_CHECK_VOCABULARY
            - {"object_translation_correspondence"}
            - MACHINE_TV_ASSUMPTION_MARKERS
        )
    )
    _assert_partition(report, expected)


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
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["acceptance"] == "accepted"
    assert (check in report["discharged_checks"]) is expected_discharged
    assert (check in report["checks_not_performed"]) is not expected_discharged
    assert report["register_convention_assumed"] == F64_REGISTER_CONVENTION
    expected = BASE_DISCHARGED | (
        set(performed)
        & (
            OBJECT_CHECK_VOCABULARY
            - {"object_translation_correspondence"}
            - MACHINE_TV_ASSUMPTION_MARKERS
        )
    )
    _assert_partition(report, expected)


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
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["acceptance"] == "accepted"
    assert (check in report["discharged_checks"]) is expected_discharged
    assert (check in report["checks_not_performed"]) is not expected_discharged
    assert (
        report["register_convention_assumed"]
        == register_convention
    )
    expected = BASE_DISCHARGED | (
        set(performed)
        & (
            OBJECT_CHECK_VOCABULARY
            - {"object_translation_correspondence"}
            - MACHINE_TV_ASSUMPTION_MARKERS
        )
    )
    _assert_partition(report, expected)


@pytest.mark.parametrize(
    "register_convention",
    [
        COMPOSITE_WIDE_AGGREGATE_REGISTER_CONVENTION,
        COMPOSITE_WIDE_SSE_AGGREGATE_REGISTER_CONVENTION,
    ],
)
@pytest.mark.parametrize("placement", ["performed", "not_performed"])
def test_memory_class_aggregate_marker_never_discharges(
    tmp_path, capsys, placement, register_convention
):
    marker = "machine_code_tv_sysv_memory_class_aggregate_abi"
    assert marker in MACHINE_TV_ASSUMPTION_MARKERS
    assert marker not in OBJECT_ACCEPT_CHECKS
    performed = [
        check for check in DESCRIPTOR["checks_performed"] if check != marker
    ]
    not_performed = [
        check for check in DESCRIPTOR["checks_not_performed"] if check != marker
    ]
    if placement == "performed":
        performed.append(marker)
    else:
        not_performed.append(marker)
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": performed,
        "checks_not_performed": not_performed,
        "register_convention_assumed": register_convention,
    }
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["acceptance"] == "accepted"
    assert marker not in report["discharged_checks"]
    assert marker in report["checks_not_performed"]
    assert report["register_convention_assumed"] == register_convention
    expected_discharged = BASE_DISCHARGED | (
        set(performed) & OBJECT_ACCEPT_CHECKS
    )
    _assert_partition(report, expected_discharged)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "mumei.foreign-object-accept/v1"),
        ("build_id", "b" * 64),
        ("checks_performed", "not-a-list"),
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
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["descriptor_invalid"] is True
    assert check not in report.get("discharged_checks", [])
    assert check in report["checks_not_performed"]


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
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["acceptance"] == "accepted"
    assert marker not in report["discharged_checks"]
    assert marker in report["checks_not_performed"]
    expected = BASE_DISCHARGED | (
        set(descriptor["checks_performed"])
        & (
            OBJECT_CHECK_VOCABULARY
            - {"object_translation_correspondence"}
            - MACHINE_TV_ASSUMPTION_MARKERS
        )
    )
    _assert_partition(report, expected)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda descriptor: descriptor["checks_performed"].remove(
                OBJECT_SOURCE_MACHINE_CODE_CHECK
            ),
            id="missing-core-source-check",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(accepted=False),
            id="not-accepted",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(acceptance="not_evaluated"),
            id="not-evaluated",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(schema_version="wrong"),
            id="wrong-schema",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(build_id="b" * 64),
            id="wrong-build-id",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(scope="unknown"),
            id="unknown-scope",
        ),
        pytest.param(
            lambda descriptor: descriptor["checks_performed"].remove(
                "object_link_correspondence"
            ),
            id="link-required-but-absent",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(
                scope=OBJECT_ACCEPT_WITHOUT_LINK_SCOPE
            ),
            id="link-present-but-forbidden",
        ),
        pytest.param(
            lambda descriptor: descriptor["checks_not_performed"].append(
                "object_symbol_correspondence"
            ),
            id="performed-not-performed-overlap",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(llvm_sha256="Z" * 64),
            id="bad-llvm-sha",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(object_sha256="f" * 63),
            id="bad-object-sha",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(scope=[]),
            id="unhashable-scope",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(checks_performed=None),
            id="performed-not-list",
        ),
        pytest.param(
            lambda descriptor: descriptor["checks_performed"].__setitem__(0, 1),
            id="performed-non-string",
        ),
        pytest.param(
            lambda descriptor: descriptor.update(checks_not_performed=None),
            id="not-performed-not-list",
        ),
        pytest.param(
            lambda descriptor: descriptor["checks_not_performed"].append(1),
            id="not-performed-non-string",
        ),
    ],
)
def test_invalid_descriptor_claims_nothing(tmp_path, capsys, mutate):
    descriptor = json.loads(json.dumps(DESCRIPTOR))
    mutate(descriptor)
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["descriptor_invalid"] is True
    assert "acceptance" not in report
    assert "discharged_checks" not in report
    assert report["checks_not_performed"] == sorted(ALL_CHECKS)
    assert report["sequence"]["selected_result"] is not None
    assert "candidate" not in report
    assert "certificate" not in report


def test_agent_owned_translation_name_does_not_replace_core_check(tmp_path, capsys):
    descriptor = {
        **DESCRIPTOR,
        "checks_performed": [
            check
            for check in DESCRIPTOR["checks_performed"]
            if check != OBJECT_SOURCE_MACHINE_CODE_CHECK
        ]
        + ["object_translation_correspondence"],
    }
    core = _write_core(tmp_path, descriptor)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    report = json.loads(out)
    assert code == 0
    assert report["descriptor_invalid"] is True
    assert "acceptance" not in report
    assert "discharged_checks" not in report
    _assert_partition(report)


@pytest.mark.parametrize("stdout", ["not-json", ""])
def test_unparseable_exit_zero_descriptor_claims_nothing(tmp_path, capsys, stdout):
    core = _write_core(tmp_path, stdout)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    report = json.loads(out)
    assert code == 0
    assert report["descriptor_invalid"] is True
    assert "acceptance" not in report
    assert "discharged_checks" not in report
    _assert_partition(report)


def test_duplicate_descriptor_keys_claim_nothing(tmp_path, capsys):
    stdout = (
        '{"schema_version":"mumei.native-evidence-acceptance/v1",'
        '"schema_version":"other"}'
    )
    core = _write_core(tmp_path, stdout)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    report = json.loads(out)
    assert code == 0
    assert report["descriptor_invalid"] is True
    assert "acceptance" not in report
    assert "discharged_checks" not in report
    _assert_partition(report)


@pytest.mark.parametrize(
    ("exit_code", "expected_outcome"),
    [(1, None), (3, "inconclusive")],
)
def test_nonaccepted_exit_codes_make_no_object_claim(
    tmp_path, capsys, exit_code, expected_outcome
):
    core = _write_core(tmp_path, exit_code=exit_code)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    report = json.loads(out)
    assert code == 0
    assert report["normalized"]["exit_code"] == exit_code
    if expected_outcome is None:
        assert "acceptance" not in report
    else:
        assert report["acceptance"] == expected_outcome
    assert "discharged_checks" not in report
    assert report["sequence"].get("selected_result") is None
    _assert_partition(report)


def test_input_drift_suppresses_acceptance_and_selection(tmp_path, capsys):
    core = _write_core(tmp_path, drift_source=True)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    report = json.loads(out)
    assert code == 0
    assert report["inputs_changed"] is True
    assert "acceptance" not in report
    assert "descriptor_invalid" not in report
    assert "discharged_checks" not in report
    assert report["sequence"].get("selected_result") is None
    _assert_partition(report)


@pytest.mark.parametrize(
    ("change", "expected_error"),
    [
        (
            lambda argv, core, bundle, source: argv.__setitem__(
                argv.index("--expected-build-id") + 1, "bad"
            ),
            "--expected-build-id",
        ),
        (
            lambda argv, core, bundle, source: argv.__setitem__(
                argv.index("--attempt-timeout") + 1, "0"
            ),
            "--attempt-timeout",
        ),
        (
            lambda argv, core, bundle, source: argv.__setitem__(
                argv.index("--core") + 1, "relative-core"
            ),
            "--core",
        ),
        (
            lambda argv, core, bundle, source: argv.__setitem__(
                argv.index("--bundle") + 1, "relative-bundle"
            ),
            "--bundle",
        ),
        (
            lambda argv, core, bundle, source: argv.__setitem__(
                argv.index("--source") + 1, "relative-source"
            ),
            "--source",
        ),
    ],
)
def test_request_validation_fails_before_dispatch(
    tmp_path, capsys, change, expected_error
):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    argv = _args(core, bundle, source)
    change(argv, core, bundle, source)
    code, out, err = _run(capsys, argv)
    assert code == 1
    assert out == ""
    assert expected_error in err


def test_output_path_cannot_overwrite_declared_input(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(
        capsys, _args(core, bundle, source, extra=["--output", str(source)])
    )
    assert code == 1
    assert out == ""
    assert "--output may not overwrite" in err


@pytest.mark.parametrize(
    ("target", "expected_error"),
    [
        ("source", "exceeds the Core input bound"),
        ("record", "exceeds the Core input bound"),
        ("member", "exceeds the Core input bound"),
    ],
)
def test_oversized_declared_input_is_rejected(tmp_path, capsys, target, expected_error):
    from agent.native_bundle import (
        MAX_RECORD_BYTES,
        MAX_SOURCE_BYTES,
        member_bound_bytes,
    )

    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    if target == "source":
        source.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    elif target == "member":
        member = "program.ll"
        (bundle / member).write_bytes(b"x" * (member_bound_bytes(member) + 1))
    else:
        (bundle / RECORD_FILE).write_bytes(b"x" * (MAX_RECORD_BYTES + 1))
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 1
    assert out == ""
    assert expected_error in err


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
            "native-object-accept",
            "--core",
            str(core),
            "--bundle",
            str(bundle),
            "--source",
            str(source),
            "--expected-build-id",
            BUILD_ID,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["acceptance"] == "accepted"
    assert "object_translation_correspondence" in report["discharged_checks"]


def test_mcp_tool_dispatch(tmp_path):
    from agent import mcp_server

    core = _write_core(tmp_path)
    bundle = _write_bundle(tmp_path)
    source = _write_source(tmp_path)
    result = json.loads(
        mcp_server.native_object_accept(str(core), str(bundle), str(source), BUILD_ID)
    )
    assert result["status"] == "ok"
    report = result["report"]
    assert report["acceptance"] == "accepted"
    assert "object_translation_correspondence" in report["discharged_checks"]


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


@pytest.mark.integration
@pytest.mark.parametrize(
    "source_text",
    [
        SOURCE,
        BOUNDED_LOOP_SOURCE,
        F64_SOURCE,
        COMPOSITE_AGGREGATE_SOURCE,
        COMPOSITE_MIXED_F64_SOURCE,
        COMPOSITE_THREE_LEAF_SOURCE,
        COMPOSITE_WIDE_MIXED_F64_SOURCE,
    ],
    ids=(
        "simple-atom",
        "bounded-loop",
        "scalar-f64",
        "composite-integer-aggregate",
        "composite-mixed-integer-f64-aggregate",
        "composite-three-leaf-integer-aggregate",
        "composite-four-leaf-mixed-f64-aggregate",
    ),
)
def test_real_core_accepts_native_object(tmp_path, capsys, real_core, source_text):
    source = _write_source(tmp_path, source_text)
    bundle = tmp_path / "bundle"
    built = subprocess.run(
        [real_core, "native-bundle", "build", str(source), "-o", str(bundle)],
        check=False,
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
    core_acceptance = subprocess.run(
        [
            real_core,
            "native-bundle",
            "accept-object",
            "--expected-build-id",
            build_id,
            "--json",
            str(bundle),
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert core_acceptance.returncode == 0, core_acceptance.stderr
    descriptor = json.loads(core_acceptance.stdout)
    assert descriptor["acceptance"] == "evaluated"
    assert descriptor["accepted"] is True
    assert ENTRY_WRAPPER_CHECK in descriptor["checks_performed"]
    assert ENTRY_WRAPPER_CHECK not in descriptor["checks_not_performed"]
    assert "os_exit_status_observation" in descriptor["checks_not_performed"]
    wrapper_entry = next(
        function
        for function in descriptor["functions"].values()
        if isinstance(function, dict) and function.get("role") == "entry_wrapper"
    )
    assert wrapper_entry["outcome"] == "equivalent_within_profile"
    expected_function_outcomes = {
        outcome: sum(
            isinstance(function, dict) and function.get("outcome") == outcome
            for function in descriptor["functions"].values()
        )
        for outcome in ("equivalent_within_profile", "outside_profile")
    }

    argv = _args(Path(real_core), bundle, source)
    argv[argv.index("--expected-build-id") + 1] = build_id
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    report = json.loads(out)
    assert report["acceptance"] == "accepted"
    assert report["acceptance_schema"] == NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA
    assert report["sequence"]["selected_result"] is not None
    assert "object_translation_correspondence" in report["discharged_checks"]
    assert ENTRY_WRAPPER_CHECK in report["discharged_checks"]
    assert report["function_outcomes"] == expected_function_outcomes
    assert "os_exit_status_observation" not in report["discharged_checks"]
    assert report["checks_not_performed"] == sorted(
        ALL_CHECKS - set(report["discharged_checks"])
    )
    if source_text == BOUNDED_LOOP_SOURCE:
        assert "machine_code_bounded_loop_function_tv" in report["discharged_checks"]
        assert report["input_domain"].endswith("_and_loops_exiting_within_bound_4")
    elif source_text == F64_SOURCE:
        f64_check = "machine_code_f64_scalar_function_tv"
        assert f64_check in descriptor["checks_performed"]
        assert f64_check in report["discharged_checks"]
        assert descriptor["register_convention_assumed"] == F64_REGISTER_CONVENTION
        assert report["register_convention_assumed"] == F64_REGISTER_CONVENTION
        for marker in MACHINE_TV_ASSUMPTION_MARKERS:
            assert marker in descriptor["checks_not_performed"]
            assert marker in report["checks_not_performed"]
            assert marker not in report["discharged_checks"]
    elif source_text in (
        COMPOSITE_AGGREGATE_SOURCE,
        COMPOSITE_MIXED_F64_SOURCE,
        COMPOSITE_THREE_LEAF_SOURCE,
        COMPOSITE_WIDE_MIXED_F64_SOURCE,
    ):
        aggregate_check = "machine_code_composite_register_aggregate_tv"
        expected_conventions = {
            COMPOSITE_AGGREGATE_SOURCE: COMPOSITE_AGGREGATE_REGISTER_CONVENTION,
            COMPOSITE_MIXED_F64_SOURCE: COMPOSITE_SSE_AGGREGATE_REGISTER_CONVENTION,
            COMPOSITE_THREE_LEAF_SOURCE: (
                COMPOSITE_WIDE_AGGREGATE_REGISTER_CONVENTION
            ),
            COMPOSITE_WIDE_MIXED_F64_SOURCE: (
                COMPOSITE_WIDE_SSE_AGGREGATE_REGISTER_CONVENTION
            ),
        }
        expected_convention = expected_conventions[source_text]
        assert aggregate_check in descriptor["checks_performed"]
        assert aggregate_check in report["discharged_checks"]
        equivalent_functions_by_source = {
            COMPOSITE_AGGREGATE_SOURCE: ("sum", "mk", "caller", "fwd"),
            COMPOSITE_MIXED_F64_SOURCE: ("mkq", "getb", "use_q"),
            COMPOSITE_THREE_LEAF_SOURCE: ("sum3", "mk3", "caller", "fwd"),
            COMPOSITE_WIDE_MIXED_F64_SOURCE: ("sum4", "mk4", "caller", "fwd"),
        }
        equivalent_functions = equivalent_functions_by_source[source_text]
        for name in equivalent_functions:
            assert (
                descriptor["functions"][name]["outcome"]
                == "equivalent_within_profile"
            )
        marker = "machine_code_tv_sysv_memory_class_aggregate_abi"
        assert marker not in descriptor["checks_performed"]
        assert marker in report["checks_not_performed"]
        assert marker not in report["discharged_checks"]
        if source_text in (
            COMPOSITE_THREE_LEAF_SOURCE,
            COMPOSITE_WIDE_MIXED_F64_SOURCE,
        ):
            assert marker in descriptor["checks_not_performed"]
        assert (
            descriptor["register_convention_assumed"]
            == expected_convention
        )
        assert (
            report["register_convention_assumed"]
            == expected_convention
        )
    else:
        assert (
            "machine_code_bounded_loop_function_tv" not in report["discharged_checks"]
        )
    assert '"main"' not in out
    assert "functions" not in report
