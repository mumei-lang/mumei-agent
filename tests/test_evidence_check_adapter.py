"""Tests for the C11 Core adapter-manifest representation-check route."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from agent import attempt_runner, evidence_check_adapter
from agent.mcp_server import evidence_check_adapter as mcp_evidence_check_adapter

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = {
    "schema_version": "mumei.verifier-adapter/v1",
    "adapter_id": "integration-adapter",
    "adapter_version": "1.0.0",
    "profiles": ["fixture-profile"],
    "methods": ["deductive_proof"],
    "attempt_argv": ["declared-adapter-command"],
    "attempt_stdin": "declared stdin metadata",
    "verdict_markers": [
        {
            "stream": "stdout",
            "contains": "declared-valid-marker",
            "outcome": "valid",
        },
        {
            "stream": "stderr",
            "contains": "declared-failed-marker",
            "outcome": "failed",
        },
    ],
}
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
    "attempt_argv": "declared",
    "attempt_stdin": "declared",
    "verdict_marker_count": 2,
    "declared_field_meaning": DECLARED_FIELD_MEANING,
    "checks_performed": CHECKS_PERFORMED,
    "checks_not_performed": CHECKS_NOT_PERFORMED,
}


def _write_manifest(
    tmp_path: Path,
    document: dict | None = None,
    *,
    data: bytes | None = None,
    name: str = "saved-manifest.json",
) -> Path:
    manifest = tmp_path / name
    if data is None:
        data = json.dumps(
            copy.deepcopy(MANIFEST if document is None else document)
        ).encode("utf-8")
    manifest.write_bytes(data)
    return manifest


def _write_core(
    tmp_path: Path,
    expected_sha256: str,
    *,
    exit_code: int = 0,
    stdout: dict | str | None = DIAGNOSTIC,
    sleep_seconds: float = 0,
) -> Path:
    if stdout is None:
        stdout_command = ""
    else:
        stdout_text = stdout if isinstance(stdout, str) else json.dumps(stdout)
        stdout_command = f"printf '%s' {shlex.quote(stdout_text)}\n"
    core = tmp_path / "mumei-stub"
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
        + (f"        sleep {sleep_seconds}\n" if sleep_seconds else "")
        + f"        {stdout_command}"
        + f"        exit {exit_code}\n"
        + "    fi\n"
        + "    exit 2\n"
        + "fi\n"
        + "exit 2\n",
        encoding="utf-8",
    )
    core.chmod(0o755)
    return core


def _args(
    core: Path,
    manifest: Path,
    extra: tuple[str, ...] = (),
    *,
    attempt_timeout_ms: int = 30000,
) -> list[str]:
    return [
        "--core",
        str(core),
        "--manifest",
        str(manifest),
        "--attempt-timeout",
        str(attempt_timeout_ms),
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


def _assert_unselected(report: dict, *, exit_code: int | None = None) -> None:
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    for field in (
        "manifest_schema_version",
        "representation",
        "acceptance",
        "attempt_argv",
        "attempt_stdin",
        "verdict_marker_count",
        "declared_field_meaning",
        "checks_performed",
        "checks_not_performed",
    ):
        assert field not in report
    if exit_code is not None:
        assert report["normalized"]["exit_code"] == exit_code


def test_exact_diagnostic_selects_and_reconciles_manifest_fields(
    tmp_path: Path, capsys
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest())

    code, stdout, stderr = _run(capsys, _args(core, manifest))

    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert report["schema_version"] == "mumei.evidence-check-adapter-report/v1"
    assert report["manifest_schema_version"] == "mumei.verifier-adapter/v1"
    assert report["representation"] == "valid"
    assert report["acceptance"] == "not_evaluated"
    assert report["attempt_argv"] == "declared"
    assert report["attempt_stdin"] == "declared"
    assert report["verdict_marker_count"] == 2
    assert report["declared_field_meaning"] == DECLARED_FIELD_MEANING
    assert report["checks_performed"] == CHECKS_PERFORMED
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )


def test_absent_optional_manifest_fields_are_reported(tmp_path: Path, capsys) -> None:
    manifest_doc = copy.deepcopy(MANIFEST)
    manifest_doc.pop("attempt_argv")
    manifest_doc.pop("attempt_stdin")
    manifest_doc.pop("verdict_markers")
    manifest = _write_manifest(tmp_path, manifest_doc)
    diagnostic = {
        **DIAGNOSTIC,
        "attempt_argv": "absent",
        "attempt_stdin": "absent",
        "verdict_marker_count": 0,
    }
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    report = json.loads(stdout)
    assert report["attempt_argv"] == "absent"
    assert report["attempt_stdin"] == "absent"
    assert report["verdict_marker_count"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "mumei.adapter-manifest-check/v2"),
        ("manifest_schema_version", "mumei.verifier-adapter/v2"),
        ("representation", "invalid"),
        ("acceptance", "accepted"),
        ("attempt_argv", "unknown"),
        ("attempt_stdin", "unknown"),
        ("attempt_argv", []),
        ("attempt_stdin", {}),
        (
            "declared_field_meaning",
            {**DECLARED_FIELD_MEANING, "attempt_argv": "executed"},
        ),
        ("checks_performed", ["representation_gate"]),
        ("checks_not_performed", ["grade_promotion"]),
    ],
)
def test_each_fixed_diagnostic_field_must_match(
    tmp_path: Path, capsys, field: str, value
) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = copy.deepcopy(DIAGNOSTIC)
    diagnostic[field] = value
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_unexpected_diagnostic_field_is_rejected(tmp_path: Path, capsys) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = {**DIAGNOSTIC, "extra": "unrecognized"}
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_missing_diagnostic_field_is_rejected(tmp_path: Path, capsys) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = copy.deepcopy(DIAGNOSTIC)
    diagnostic.pop("verdict_marker_count")
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize("count", [True, False, -1, 33, 1.5, "2", None])
def test_invalid_verdict_marker_count_is_rejected(
    tmp_path: Path, capsys, count
) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = {**DIAGNOSTIC, "verdict_marker_count": count}
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempt_argv", "absent"),
        ("attempt_stdin", "absent"),
        ("verdict_marker_count", 1),
    ],
)
def test_core_diagnostic_must_match_local_manifest_decode(
    tmp_path: Path, capsys, field: str, value
) -> None:
    manifest = _write_manifest(tmp_path)
    diagnostic = {**DIAGNOSTIC, field: value}
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_invalid_local_manifest_cannot_select_valid_core_diagnostic(
    tmp_path: Path, capsys
) -> None:
    manifest_doc = copy.deepcopy(MANIFEST)
    manifest_doc["attempt_argv"] = []
    manifest = _write_manifest(tmp_path, manifest_doc)
    core = _write_core(tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest())

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize("exit_code", [1, 2, 17])
def test_nonzero_exit_claims_no_manifest_result(
    tmp_path: Path, capsys, exit_code: int
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        exit_code=exit_code,
    )

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=exit_code)


def test_timeout_claims_no_manifest_result(tmp_path: Path, capsys) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        sleep_seconds=1,
    )

    code, stdout, _ = _run(
        capsys,
        _args(core, manifest, attempt_timeout_ms=1),
    )

    assert code == 0
    _assert_unselected(json.loads(stdout))


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


def test_duplicate_diagnostic_keys_are_rejected(tmp_path: Path, capsys) -> None:
    manifest = _write_manifest(tmp_path)
    stdout = json.dumps(DIAGNOSTIC).replace(
        '"representation": "valid"',
        '"representation": "invalid", "representation": "valid"',
    )
    core = _write_core(
        tmp_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        stdout=stdout,
    )

    code, output, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    _assert_unselected(json.loads(output), exit_code=0)


def test_input_drift_suppresses_selection(tmp_path: Path, capsys, monkeypatch) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest())
    original_dispatch = attempt_runner.dispatch_attempt

    def dispatch_then_drift(*args, **kwargs):
        result = original_dispatch(*args, **kwargs)
        manifest.write_bytes(b'{"changed":true}\n')
        return result

    monkeypatch.setattr(attempt_runner, "dispatch_attempt", dispatch_then_drift)

    code, stdout, _ = _run(capsys, _args(core, manifest))

    assert code == 0
    report = json.loads(stdout)
    _assert_unselected(report, exit_code=0)
    assert report["inputs_changed"] is True


def test_oversize_manifest_is_rejected_before_dispatch(tmp_path: Path, capsys) -> None:
    manifest = _write_manifest(tmp_path, data=b"x" * 65_537)
    core = _write_core(tmp_path, "0" * 64)

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


def test_nonabsolute_paths_and_nonposix_hosts_are_rejected(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest())

    code, stdout, stderr = _run(
        capsys,
        _args(core, manifest, extra=("--manifest", "relative.json")),
    )
    assert code == 1 and stdout == ""
    assert "absolute path" in stderr

    monkeypatch.setattr(evidence_check_adapter.os, "name", "nt")
    code, stdout, stderr = _run(capsys, _args(core, manifest))
    assert code == 1 and stdout == ""
    assert "POSIX" in stderr


def test_output_may_not_overwrite_a_declared_input(tmp_path: Path, capsys) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest())

    code, stdout, stderr = _run(
        capsys,
        _args(core, manifest, extra=("--output", str(manifest))),
    )

    assert code == 1 and stdout == ""
    assert "declared input" in stderr


def test_mcp_tool_runs_adapter_check_and_validates_paths(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest())

    result = json.loads(mcp_evidence_check_adapter(str(core), str(manifest)))

    assert result["status"] == "ok"
    assert result["report"]["schema_version"] == (
        "mumei.evidence-check-adapter-report/v1"
    )
    assert result["report"]["verdict_marker_count"] == 2

    invalid = json.loads(mcp_evidence_check_adapter("\x00", str(manifest)))
    assert invalid["status"] == "error"
    assert "nonempty single-line path" in invalid["error"]

    missing_manifest = tmp_path / "missing-manifest.json"
    redacted = json.loads(mcp_evidence_check_adapter(str(core), str(missing_manifest)))
    assert redacted["status"] == "error"
    assert str(missing_manifest) not in redacted["error"]
    assert missing_manifest.name in redacted["error"]


def test_adapter_content_sentinels_never_appear_in_cli_or_mcp_results(
    tmp_path: Path, capsys
) -> None:
    sentinels = {
        "adapter-id-sentinel-7e52",
        "argv-sentinel-7e52",
        "stdin-sentinel-7e52",
        "marker-sentinel-7e52",
    }
    manifest_doc = copy.deepcopy(MANIFEST)
    manifest_doc["adapter_id"] = "adapter-id-sentinel-7e52"
    manifest_doc["attempt_argv"] = ["argv-sentinel-7e52"]
    manifest_doc["attempt_stdin"] = "stdin-sentinel-7e52"
    manifest_doc["verdict_markers"][0]["contains"] = "marker-sentinel-7e52"
    manifest = _write_manifest(tmp_path, manifest_doc)
    core = _write_core(tmp_path, hashlib.sha256(manifest.read_bytes()).hexdigest())

    code, stdout, stderr = _run(capsys, _args(core, manifest))
    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert report["sequence"]["selected_result"] is not None
    assert all(
        sentinel not in stdout and sentinel not in stderr for sentinel in sentinels
    )
    assert all(sentinel not in json.dumps(report) for sentinel in sentinels)

    mcp_result = mcp_evidence_check_adapter(str(core), str(manifest))
    assert json.loads(mcp_result)["status"] == "ok"
    assert all(sentinel not in mcp_result for sentinel in sentinels)


@pytest.fixture
def real_core() -> str:
    path = os.environ.get("MUMEI_BIN")
    if not path or not Path(path).is_absolute() or not Path(path).is_file():
        pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")
    return path


@pytest.mark.integration
def test_real_core_accepts_manifest_and_selects_matching_diagnostic(
    tmp_path: Path, capsys, real_core: str
) -> None:
    manifest = _write_manifest(tmp_path)
    manifest_bytes = manifest.read_bytes()

    core_check = subprocess.run(
        [
            real_core,
            "evidence",
            "check-adapter",
            "--stdin",
            "--json",
        ],
        input=manifest_bytes,
        capture_output=True,
        timeout=60,
    )
    assert core_check.returncode == 0, (
        "Core rejected the declared adapter manifest: "
        f"exit={core_check.returncode}; "
        f"stdout={core_check.stdout!r}; stderr={core_check.stderr!r}"
    )
    core_diagnostic = json.loads(core_check.stdout)
    assert core_diagnostic["representation"] == "valid"
    assert core_diagnostic["attempt_argv"] == "declared"
    assert core_diagnostic["attempt_stdin"] == "declared"
    assert core_diagnostic["verdict_marker_count"] == 2

    code, stdout, stderr = _run(
        capsys,
        _args(Path(real_core).resolve(), manifest),
    )
    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["schema_version"] == "mumei.evidence-check-adapter-report/v1"
    assert report["representation"] == "valid"
    assert report["attempt_argv"] == core_diagnostic["attempt_argv"]
    assert report["attempt_stdin"] == core_diagnostic["attempt_stdin"]
    assert report["verdict_marker_count"] == core_diagnostic["verdict_marker_count"]
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )
