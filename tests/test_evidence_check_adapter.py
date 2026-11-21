"""Tests for the C11 Core adapter-manifest representation-check route."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shlex
from pathlib import Path

import pytest

from agent import attempt_runner, evidence_check_adapter
from agent.core_evidence import MAX_CHECK_TIMEOUT_MS
from agent.mcp_server import evidence_check_adapter as mcp_evidence_check_adapter

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "adapter_manifest_minimal.json"
)
MANIFEST_BYTES = MANIFEST_FIXTURE.read_bytes()
CHECKS_PERFORMED = ["representation_gate", "manifest_consistency"]
CHECKS_NOT_PERFORMED = [
    "adapter_execution",
    "command_safety",
    "stdin_semantics",
    "reported_outcome_truth",
    "resource_enforcement",
    "producer_authenticity",
    "host_policy",
    "grade_promotion",
]
DECLARED_FIELD_MEANING = {
    "attempt_argv": "inert_without_host_opt_in",
    "attempt_stdin": "inert_without_host_opt_in",
    "verdict_markers": "adapter_self_report_vocabulary",
    "max_memory_mb": "declared_ceiling_not_enforced_by_core",
}
DIAGNOSTIC = {
    "schema_version": "mumei.adapter-manifest-check/v1",
    "manifest_schema_version": "mumei.verifier-adapter/v1",
    "representation": "valid",
    "acceptance": "not_evaluated",
    "attempt_argv": "absent",
    "attempt_stdin": "absent",
    "verdict_marker_count": 0,
    "declared_field_meaning": DECLARED_FIELD_MEANING,
    "checks_performed": CHECKS_PERFORMED,
    "checks_not_performed": CHECKS_NOT_PERFORMED,
}
DIAGNOSTIC_FIELDS = (
    "representation",
    "acceptance",
    "attempt_argv",
    "attempt_stdin",
    "verdict_marker_count",
    "declared_field_meaning",
    "checks_performed",
    "checks_not_performed",
)


def _write_manifest(
    tmp_path: Path, data: bytes = MANIFEST_BYTES
) -> Path:
    manifest = tmp_path / "saved-adapter-manifest.json"
    manifest.write_bytes(data)
    return manifest


def _write_core(
    tmp_path: Path,
    expected_sha256: str,
    *,
    exit_code: int = 0,
    stdout: str | None = json.dumps(DIAGNOSTIC),
    stderr: str | None = None,
) -> Path:
    core = tmp_path / "mumei-stub"
    stdout_command = (
        "" if stdout is None else f"printf '%s' {shlex.quote(stdout)}\n"
    )
    stderr_command = (
        "" if stderr is None else f"printf '%s' {shlex.quote(stderr)} >&2\n"
    )
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check-adapter" ] && '
        '[ "$3" = "--stdin" ] && [ "$4" = "--json" ]; then\n'
        "    input_file=$(mktemp)\n"
        '    cat > "$input_file"\n'
        "    got=$(python3 -c '\n"
        "import hashlib,sys\n"
        'print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())\n'
        '\' "$input_file")\n'
        '    rm -f "$input_file"\n'
        f'    if [ "$got" = "{expected_sha256}" ]; then\n'
        f"        {stdout_command}"
        f"        {stderr_command}"
        f"        exit {exit_code}\n"
        "    fi\n"
        "    exit 2\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    core.chmod(0o755)
    return core


def _args(
    core: Path,
    manifest: Path,
    extra: tuple[str, ...] = (),
) -> list[str]:
    return [
        "--core",
        str(core),
        "--manifest",
        str(manifest),
        "--attempt-timeout",
        "30000",
        *extra,
    ]


def _run(capsys, argv: list[str]) -> tuple[int, str, str]:
    try:
        code = evidence_check_adapter.main_check_adapter(
            evidence_check_adapter.build_check_adapter_parser().parse_args(argv)
        )
    except SystemExit as exc:
        code = exc.code
    output = capsys.readouterr()
    return code, output.out, output.err


def _assert_unselected(
    report: dict, *, exit_code: int | None = None
) -> None:
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    for field in DIAGNOSTIC_FIELDS:
        assert field not in report
    if exit_code is not None:
        assert report["normalized"]["exit_code"] == exit_code


def test_exact_diagnostic_selects_and_hands_off_candidate(
    tmp_path: Path, capsys
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest()
    )

    code, stdout, stderr = _run(capsys, _args(core, manifest))

    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert report["schema_version"] == (
        "mumei.evidence-check-adapter-report/v1"
    )
    assert report["representation"] == "valid"
    assert report["acceptance"] == "not_evaluated"
    assert report["attempt_argv"] == "absent"
    assert report["attempt_stdin"] == "absent"
    assert report["verdict_marker_count"] == 0
    assert report["declared_field_meaning"] == DECLARED_FIELD_MEANING
    assert report["checks_performed"] == CHECKS_PERFORMED
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )
    report_text = json.dumps(report)
    assert "adapter_id" not in report_text
    assert '"fixture"' not in report_text
    assert "attempt_argv" in report


@pytest.mark.parametrize(
    ("attempt_argv", "attempt_stdin"),
    [
        ("declared", "absent"),
        ("absent", "declared"),
        ("declared", "declared"),
    ],
)
def test_valid_declared_input_labels_are_reported(
    tmp_path: Path, capsys, attempt_argv: str, attempt_stdin: str
) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = {
        **DIAGNOSTIC,
        "attempt_argv": attempt_argv,
        "attempt_stdin": attempt_stdin,
    }
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    report = json.loads(stdout)
    assert report["attempt_argv"] == attempt_argv
    assert report["attempt_stdin"] == attempt_stdin
    assert report["sequence"]["selected_result"] is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "mumei.adapter-manifest-check/v2"),
        ("manifest_schema_version", "mumei.verifier-adapter/v2"),
        ("representation", "invalid"),
        ("acceptance", "accepted"),
        ("attempt_argv", "executed"),
        ("attempt_argv", []),
        ("attempt_stdin", "consumed"),
        ("attempt_stdin", {}),
        (
            "declared_field_meaning",
            {**DECLARED_FIELD_MEANING, "attempt_argv": "executed"},
        ),
        ("checks_performed", ["representation_gate"]),
        (
            "checks_not_performed",
            ["adapter_execution", "grade_promotion"],
        ),
    ],
)
def test_every_constant_field_must_match(
    tmp_path: Path, capsys, field: str, value
) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = copy.deepcopy(DIAGNOSTIC)
    diagnostic[field] = value
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize(
    "diagnostic",
    [
        {**DIAGNOSTIC, "extra": "unrecognized"},
        {key: value for key, value in DIAGNOSTIC.items() if key != "acceptance"},
    ],
)
def test_diagnostic_key_set_must_be_exact(
    tmp_path: Path, capsys, diagnostic: dict
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize("marker_count", [-1, True, False, 0.5, "0", None])
def test_invalid_verdict_marker_count_is_rejected(
    tmp_path: Path, capsys, marker_count
) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = {**DIAGNOSTIC, "verdict_marker_count": marker_count}
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_grade_promotion_may_not_be_listed_as_performed(
    tmp_path: Path, capsys
) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = {
        **DIAGNOSTIC,
        "checks_performed": ["representation_gate", "grade_promotion"],
    }
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize(
    "stdout",
    [
        json.dumps(DIAGNOSTIC).replace(
            '"representation": "valid"',
            '"representation": "valid", "representation": "valid"',
        ),
        json.dumps(DIAGNOSTIC).replace(
            '"attempt_argv": "inert_without_host_opt_in"',
            '"attempt_argv": "inert_without_host_opt_in", '
            '"attempt_argv": "inert_without_host_opt_in"',
        ),
    ],
)
def test_duplicate_json_keys_are_rejected(
    tmp_path: Path, capsys, stdout: str
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=stdout,
    )

    code, output, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(output), exit_code=0)


@pytest.mark.parametrize("exit_code", [1, 2, 3, 17])
def test_nonzero_core_exit_claims_no_diagnostic(
    tmp_path: Path, capsys, exit_code: int
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        exit_code=exit_code,
        stdout=None,
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=exit_code)


@pytest.mark.parametrize("stdout", ["not-json", "[]", "null", "{}"])
def test_malformed_or_nonobject_stdout_claims_nothing(
    tmp_path: Path, capsys, stdout: str
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=stdout,
    )

    code, output, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(output), exit_code=0)


def test_core_stderr_note_does_not_invalidate_diagnostic(
    tmp_path: Path, capsys
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stderr="adapter manifest was checked statically",
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    report = json.loads(stdout)
    assert report["representation"] == "valid"
    assert report["sequence"]["selected_result"] is not None


def test_input_drift_suppresses_diagnostic_and_selection(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest()
    )
    original_dispatch = attempt_runner.dispatch_attempt

    def dispatch_then_drift(*args, **kwargs):
        result = original_dispatch(*args, **kwargs)
        manifest.write_bytes(b'{"changed":true}\n')
        return result

    monkeypatch.setattr(
        attempt_runner, "dispatch_attempt", dispatch_then_drift
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    report = json.loads(stdout)
    _assert_unselected(report, exit_code=0)
    assert report["inputs_changed"] is True


def test_oversize_manifest_is_rejected_before_dispatch(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    manifest = _write_manifest(tmp_path, b"x" * 65_537)
    core = _write_core(tmp_path, "0" * 64)

    def unexpected_dispatch(*args, **kwargs):
        pytest.fail("oversized manifest must not dispatch Core")

    monkeypatch.setattr(attempt_runner, "dispatch_attempt", unexpected_dispatch)
    code, stdout, stderr = _run(capsys, _args(core, manifest))

    assert code == 1 and stdout == ""
    assert "input bound" in stderr


def test_nonregular_manifest_is_rejected_before_dispatch(
    tmp_path: Path, capsys
) -> None:
    core = _write_core(tmp_path, "0" * 64)
    manifest_dir = tmp_path / "manifest-dir"
    manifest_dir.mkdir()

    code, stdout, stderr = _run(capsys, _args(core, manifest_dir))

    assert code == 1 and stdout == ""
    assert "regular file" in stderr


def test_nonposix_host_is_rejected_before_dispatch(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(evidence_check_adapter.os, "name", "nt")

    code, stdout, stderr = _run(capsys, _args(core, manifest))

    assert code == 1 and stdout == ""
    assert "POSIX" in stderr


def test_attempt_timeout_must_be_within_core_bound(
    tmp_path: Path, capsys
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest()
    )

    code, stdout, stderr = _run(
        capsys,
        _args(
            core,
            manifest,
            extra=("--attempt-timeout", str(MAX_CHECK_TIMEOUT_MS + 1)),
        ),
    )

    assert code == 1 and stdout == ""
    assert f"1..{MAX_CHECK_TIMEOUT_MS}" in stderr


def test_cli_requires_core_and_manifest() -> None:
    parser = evidence_check_adapter.build_check_adapter_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--core", "/tmp/mumei"])


def test_output_may_not_overwrite_declared_manifest(
    tmp_path: Path, capsys
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest()
    )

    code, stdout, stderr = _run(
        capsys,
        _args(core, manifest, extra=("--output", str(manifest))),
    )

    assert code == 1 and stdout == ""
    assert "declared input" in stderr


def test_mcp_tool_runs_the_adapter_check(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest()
    )

    result = json.loads(
        mcp_evidence_check_adapter(str(core), str(manifest))
    )

    assert result["status"] == "ok"
    assert result["report"]["schema_version"] == (
        "mumei.evidence-check-adapter-report/v1"
    )
    assert result["report"]["representation"] == "valid"


def test_mcp_tool_rejects_invalid_declared_path() -> None:
    result = json.loads(
        mcp_evidence_check_adapter("", "/absolute/manifest")
    )

    assert result["status"] == "error"
    assert "core_path" in result["error"]


@pytest.fixture
def real_core() -> str:
    path = os.environ.get("MUMEI_BIN")
    if not path or not Path(path).is_absolute() or not Path(path).is_file():
        pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")
    return path


@pytest.mark.integration
def test_real_core_accepts_minimal_adapter_manifest(
    tmp_path: Path, capsys, real_core: str
) -> None:
    manifest = _write_manifest(tmp_path)

    code, stdout, stderr = _run(
        capsys,
        _args(Path(real_core).resolve(), manifest),
    )

    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["schema_version"] == (
        "mumei.evidence-check-adapter-report/v1"
    )
    assert report["normalized"]["exit_code"] == 0
    assert report["representation"] == "valid"
    assert report["acceptance"] == "not_evaluated"
    assert report["attempt_argv"] == "absent"
    assert report["attempt_stdin"] == "absent"
    assert report["verdict_marker_count"] == 0
    assert report["declared_field_meaning"] == DECLARED_FIELD_MEANING
    assert report["checks_performed"] == CHECKS_PERFORMED
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )


@pytest.mark.integration
def test_real_core_rejects_invalid_adapter_manifest_without_selection(
    tmp_path: Path, capsys, real_core: str
) -> None:
    manifest = _write_manifest(
        tmp_path, b'{"schema_version":"mumei.not-verifier-adapter/v1"}\n'
    )

    code, stdout, stderr = _run(
        capsys,
        _args(Path(real_core).resolve(), manifest),
    )

    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["normalized"]["exit_code"] != 0
    _assert_unselected(report)
