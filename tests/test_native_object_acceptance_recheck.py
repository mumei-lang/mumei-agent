"""Route tests for ``native-object-acceptance-recheck`` through the C11 lifecycle."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent import mcp_server
from agent.core_evidence import (
    OBJECT_CHECK_VOCABULARY,
    OBJECT_TRANSLATION_CORRESPONDENCE_ITEMS,
)
from agent.native_accept import CHECK_VOCABULARY
from agent.native_bundle import FILE_MEMBERS, MAX_EVIDENCE_BYTES, RECORD_FILE
from agent.native_object_accept import (
    NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA,
    OBJECT_ACCEPT_TRANSLATION_WITH_LINK_SCOPE,
    OBJECT_ACCEPT_WITH_LINK_SCOPE,
    OBJECT_SOURCE_MACHINE_CODE_CHECK,
)
from agent.native_object_acceptance_recheck import (
    build_object_acceptance_recheck_parser,
    main_object_acceptance_recheck,
)

BUILD_ID = "a" * 64
FINGERPRINT = "ab" * 32
ALL_CHECKS = sorted(CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY)
CONFIRM = (
    "Saved native object acceptance descriptor consistent with a fresh "
    "object acceptance of the pinned inputs."
)
SOURCE = "atom main() -> i64 requires: true; ensures: result == 0; body: { 0 };\n"
RECORD = {
    "schema": "mumei.native-bundle/v1",
    "files": {key: {} for key in FILE_MEMBERS},
}
DESCRIPTOR = {
    "schema_version": NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA,
    "acceptance": "evaluated",
    "accepted": True,
    "scope": OBJECT_ACCEPT_TRANSLATION_WITH_LINK_SCOPE,
    "checks_performed": sorted(
        {
            "bundle_identity_binding",
            "object_link_correspondence",
            "machine_code_leaf_function_tv",
            OBJECT_SOURCE_MACHINE_CODE_CHECK,
        }
        | OBJECT_TRANSLATION_CORRESPONDENCE_ITEMS
    ),
    "checks_not_performed": ["producer_authenticity", "historical_execution"],
    "build_id": BUILD_ID,
    "llvm_sha256": "1" * 64,
    "object_sha256": "2" * 64,
    "evidence_fingerprint": FINGERPRINT,
    "register_convention_assumed": "sysv_x86_64_integer_args_result",
    "input_domain": "pure_i64_inputs",
    "functions": {
        "__mumei_user_main": {"outcome": "equivalent_within_profile"},
        "main": {"outcome": "outside_profile", "reason": "not_a_source_atom"},
    },
}


def _write_core(tmp_path: Path, exit_code: int = 0, *, drift: bool = False) -> Path:
    core = tmp_path / "mumei-stub"
    touch = '    printf " " >> "$7"\n' if drift else ""
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && '
        '[ "$2" = "recheck-object-acceptance" ]; then\n'
        '    if [ "$3" != "--expected-build-id" ]; then exit 2; fi\n'
        f'    if [ "$4" != "{BUILD_ID}" ]; then exit 1; fi\n'
        f"{touch}"
        f"    exit_code={exit_code}\n"
        '    if [ "$exit_code" = "0" ]; then\n'
        f"        printf '%s\\n' '{CONFIRM}'\n"
        "    fi\n"
        '    exit "$exit_code"\n'
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _write_inputs(tmp_path: Path, descriptor: object = DESCRIPTOR):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / RECORD_FILE).write_text(json.dumps(RECORD))
    for name in FILE_MEMBERS.values():
        (bundle / name).write_text(f"bytes of {name}")
    source = tmp_path / "native-source.mm"
    source.write_text(SOURCE)
    saved = tmp_path / "object-acceptance.json"
    saved.write_text(descriptor if isinstance(descriptor, str) else json.dumps(descriptor))
    return bundle, source, saved


def _args(core, bundle, source, saved, build_id=BUILD_ID):
    return [
        "--core", str(core),
        "--bundle", str(bundle),
        "--source", str(source),
        "--descriptor", str(saved),
        "--expected-build-id", build_id,
        "--attempt-timeout", "60000",
    ]


def _run(capsys, argv):
    try:
        code = main_object_acceptance_recheck(
            build_object_acceptance_recheck_parser().parse_args(argv)
        )
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_consistent_replay_discharges_saved_descriptor_checks(tmp_path, capsys):
    core = _write_core(tmp_path)
    code, out, err = _run(capsys, _args(core, *_write_inputs(tmp_path)))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.native-object-acceptance-recheck-report/v1"
    assert report["object_acceptance_recheck"] == "consistent"
    assert report["sequence"]["selected_result"] is not None
    assert report["evidence_fingerprint"] == FINGERPRINT
    assert report["scope"] == OBJECT_ACCEPT_TRANSLATION_WITH_LINK_SCOPE
    assert report["function_outcomes"] == {
        "equivalent_within_profile": 1,
        "outside_profile": 1,
    }
    discharged = set(report["discharged_checks"])
    assert {
        "artifact_semantics",
        "claim_truth",
        "object_translation_correspondence",
        "object_link_correspondence",
        "machine_code_leaf_function_tv",
    } <= discharged
    assert "producer_authenticity" in report["checks_not_performed"]
    assert discharged.isdisjoint(report["checks_not_performed"])


@pytest.mark.parametrize("exit_code", [1, 2, 3])
def test_non_consistent_exit_discharges_nothing(tmp_path, capsys, exit_code):
    core = _write_core(tmp_path, exit_code)
    code, out, _ = _run(capsys, _args(core, *_write_inputs(tmp_path)))
    assert code == 0
    report = json.loads(out)
    assert report["sequence"].get("selected_result") is None
    assert report["checks_not_performed"] == ALL_CHECKS
    assert "discharged_checks" not in report
    assert "evidence_fingerprint" not in report
    expected = "inconclusive" if exit_code == 3 else None
    assert report.get("object_acceptance_recheck") == expected


def test_descriptor_drift_claims_no_outcome(tmp_path, capsys):
    core = _write_core(tmp_path, drift=True)
    code, out, _ = _run(capsys, _args(core, *_write_inputs(tmp_path)))
    assert code == 0
    report = json.loads(out)
    assert report["inputs_changed"] is True
    assert "object_acceptance_recheck" not in report
    assert report["sequence"].get("selected_result") is None


def _variant(**changes):
    descriptor = dict(DESCRIPTOR)
    for key, value in changes.items():
        if value is None:
            descriptor.pop(key)
        else:
            descriptor[key] = value
    return descriptor


@pytest.mark.parametrize(
    "descriptor",
    [
        json.dumps(DESCRIPTOR)[:-1] + ', "accepted": true}',
        json.dumps(DESCRIPTOR)[:-1] + ', "x": NaN}',
        "{",
        "[]",
        _variant(accepted=False),
        _variant(acceptance="not_evaluated"),
        _variant(build_id="b" * 64),
        _variant(scope=OBJECT_ACCEPT_WITH_LINK_SCOPE),
        _variant(evidence_fingerprint=None),
        _variant(evidence_fingerprint=FINGERPRINT.upper()),
        _variant(schema_version="mumei.native-consumer-evidence/v1"),
        _variant(checks_performed=["bundle_identity_binding"]),
    ],
    ids=[
        "duplicate-key",
        "nan-constant",
        "truncated",
        "non-object",
        "rejected",
        "unevaluated",
        "other-build",
        "pre-translation-scope",
        "missing-fingerprint",
        "uppercase-fingerprint",
        "foreign-schema",
        "missing-object-checks",
    ],
)
def test_invalid_saved_descriptor_is_static_error(tmp_path, capsys, descriptor):
    core = _write_core(tmp_path)
    code, out, err = _run(capsys, _args(core, *_write_inputs(tmp_path, descriptor)))
    assert code == 1 and out == ""
    assert "--descriptor" in err


def test_oversized_descriptor_is_rejected_before_parsing(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle, source, saved = _write_inputs(tmp_path)
    saved.write_text(" " * (MAX_EVIDENCE_BYTES + 1))
    code, out, err = _run(capsys, _args(core, bundle, source, saved))
    assert code == 1 and out == ""
    assert "exceeds the Core input bound" in err


def test_relative_descriptor_path_is_rejected(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle, source, _ = _write_inputs(tmp_path)
    code, _, err = _run(
        capsys, _args(core, bundle, source, Path("object-acceptance.json"))
    )
    assert code == 1
    assert "--descriptor must be an absolute path" in err


def test_output_may_not_overwrite_descriptor(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle, source, saved = _write_inputs(tmp_path)
    argv = _args(core, bundle, source, saved) + ["--output", str(saved)]
    code, _, err = _run(capsys, argv)
    assert code == 1
    assert "may not overwrite" in err


def test_mcp_tool_reports_consistent_replay(tmp_path):
    core = _write_core(tmp_path)
    bundle, source, saved = _write_inputs(tmp_path)
    out = json.loads(
        mcp_server.native_object_acceptance_recheck(
            str(core), str(bundle), str(source), str(saved), BUILD_ID
        )
    )
    assert out["status"] == "ok"
    assert out["report"]["object_acceptance_recheck"] == "consistent"
    assert "candidate" not in out["report"]


def test_mcp_tool_rejects_invalid_descriptor_without_paths(tmp_path):
    core = _write_core(tmp_path)
    bundle, source, saved = _write_inputs(tmp_path, _variant(accepted=False))
    out = json.loads(
        mcp_server.native_object_acceptance_recheck(
            str(core), str(bundle), str(source), str(saved), BUILD_ID
        )
    )
    assert out["status"] == "error"
    assert str(tmp_path) not in out["error"]


@pytest.fixture
def real_core():
    path = os.environ.get("MUMEI_BIN")
    if path and Path(path).is_absolute() and Path(path).is_file():
        return path
    found = shutil.which("mumei")
    if found:
        return found
    pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")


@pytest.mark.integration
def test_real_core_replays_saved_object_acceptance(tmp_path, capsys, real_core):
    source = tmp_path / "native-source.mm"
    source.write_text(SOURCE)
    bundle = tmp_path / "bundle"
    built = subprocess.run(
        [real_core, "native-bundle", "build", str(source), "-o", str(bundle)],
        check=False, capture_output=True, text=True, timeout=300,
    )
    if built.returncode != 0:
        if "unsupported host for first native profile" in built.stderr:
            pytest.skip("native-bundle build needs linux/x86_64")
        pytest.fail(f"native-bundle build failed: {built.stderr}")
    build_id = next(
        line.split(":", 1)[1].strip()
        for line in built.stdout.splitlines()
        if line.startswith("Build ID:")
    )
    accepted = subprocess.run(
        [
            real_core, "native-bundle", "accept-object",
            "--expected-build-id", build_id, "--json", str(bundle), str(source),
        ],
        check=False, capture_output=True, text=True, timeout=300,
    )
    assert accepted.returncode == 0, accepted.stderr
    saved = tmp_path / "object-acceptance.json"
    saved.write_text(accepted.stdout)

    code, out, err = _run(
        capsys, _args(real_core, bundle, source, saved, build_id)
    )
    assert code == 0, err
    report = json.loads(out)
    assert report["object_acceptance_recheck"] == "consistent"
    assert "object_translation_correspondence" in report["discharged_checks"]
    assert report["evidence_fingerprint"] == json.loads(accepted.stdout)[
        "evidence_fingerprint"
    ]

    tampered = json.loads(accepted.stdout)
    tampered["checks_not_performed"] = tampered["checks_not_performed"][1:]
    saved.write_text(json.dumps(tampered, indent=2) + "\n")
    code, out, err = _run(
        capsys, _args(real_core, bundle, source, saved, build_id)
    )
    assert code == 0, err
    report = json.loads(out)
    assert "object_acceptance_recheck" not in report
    assert "discharged_checks" not in report
    assert report["normalized"]["exit_code"] == 1
