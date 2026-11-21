"""Tests for Core's evidence-check acceptance representation consumer."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
from pathlib import Path

import pytest

from agent import (
    attempt_runner,
    evidence_check_attempt_acceptance,
    mcp_server,
)
from agent.core_evidence import MAX_CHECK_TIMEOUT_MS

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
VALID_BYTES = (FIXTURE_DIR / "evidence_check_acceptance_valid.json").read_bytes()
REQUIREMENT_BYTES = (
    FIXTURE_DIR / "evidence_check_acceptance_requirement.json"
).read_bytes()
MISMATCH_BYTES = (
    FIXTURE_DIR / "evidence_check_acceptance_mismatch.json"
).read_bytes()
FAILED_BYTES = (
    FIXTURE_DIR / "evidence_check_acceptance_failed.json"
).read_bytes()

CHECKS_PERFORMED = ["representation_gate", "acceptance_consistency"]
CHECKS_NOT_PERFORMED = [
    "candidate_match_recheck",
    "core_check_rerun",
    "evidence_acceptance",
    "claim_truth",
    "producer_authenticity",
    "freshness",
    "grade_promotion",
]


def _diagnostic_for(acceptance_bytes: bytes) -> dict:
    acceptance = json.loads(acceptance_bytes)
    return {
        "schema_version": "mumei.evidence-check-acceptance-check/v1",
        "acceptance_schema_version": "mumei.evidence-check-acceptance/v1",
        "representation": "valid",
        "acceptance": "not_evaluated",
        "declared_outcome": acceptance["outcome"],
        "requirement_fingerprint": (
            "declared"
            if "requirement_fingerprint" in acceptance
            else "absent"
        ),
        "declared_field_meaning": {
            "outcome": "declared_core_check_outcome",
            "candidate_match": "producer_computed_not_rechecked",
            "accepted": "producer_representation_binding_not_core_acceptance",
        },
        "checks_performed": CHECKS_PERFORMED,
        "checks_not_performed": CHECKS_NOT_PERFORMED,
    }


def _write_acceptance(
    tmp_path: Path, data: bytes = VALID_BYTES, name: str = "acceptance.json"
) -> Path:
    acceptance = tmp_path / name
    acceptance.write_bytes(data)
    return acceptance


def _write_core(
    tmp_path: Path,
    acceptance_bytes: bytes,
    *,
    exit_code: int = 0,
    stdout: str | dict | None = None,
    stderr_note: str = "",
) -> Path:
    core = tmp_path / "mumei-stub"
    if isinstance(stdout, dict):
        stdout = json.dumps(stdout)
    if stdout is None and exit_code == 0:
        stdout_command = ""
    elif stdout is None:
        stdout_command = ""
    else:
        stdout_command = f"printf '%s' {shlex.quote(stdout)}\n"
    stderr_command = (
        f"printf '%s' {shlex.quote(stderr_note)} >&2\n"
        if stderr_note
        else ""
    )
    expected_sha256 = hashlib.sha256(acceptance_bytes).hexdigest()
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && '
        '[ "$2" = "check-attempt-acceptance" ] && '
        '[ "$3" = "--stdin" ] && [ "$4" = "--json" ]; then\n'
        '    input_file=$(mktemp)\n'
        '    cat > "$input_file"\n'
        '    got=$(sha256sum "$input_file" | cut -d" " -f1)\n'
        '    rm -f "$input_file"\n'
        f'    if [ "$got" = "{expected_sha256}" ]; then\n'
        f"        {stderr_command}"
        f"        {stdout_command}"
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
    core: Path, acceptance: Path, extra: tuple[str, ...] = ()
) -> list[str]:
    return [
        "--core",
        str(core),
        "--acceptance",
        str(acceptance),
        "--attempt-timeout",
        "30000",
        *extra,
    ]


def _run(capsys, argv: list[str]) -> tuple[int, str, str]:
    try:
        code = evidence_check_attempt_acceptance.main_check_attempt_acceptance(
            evidence_check_attempt_acceptance
            .build_check_attempt_acceptance_parser()
            .parse_args(argv)
        )
    except SystemExit as exc:
        code = exc.code
    output = capsys.readouterr()
    return code, output.out, output.err


def _assert_selected(report: dict) -> None:
    assert report["sequence"].get("selected_result") is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )


def _assert_unselected(
    report: dict, *, exit_code: int | None = None
) -> None:
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    for field in (
        "representation",
        "declared_outcome",
        "requirement_fingerprint",
        "checks_performed",
        "checks_not_performed",
    ):
        assert field not in report
    if exit_code is not None:
        assert report["normalized"]["exit_code"] == exit_code


def test_valid_diagnostic_selects_and_reports_only_aggregate_fields(
    tmp_path: Path, capsys
) -> None:
    acceptance = _write_acceptance(tmp_path)
    core = _write_core(tmp_path, acceptance.read_bytes(), stdout=_diagnostic_for(VALID_BYTES))

    code, stdout, stderr = _run(capsys, _args(core, acceptance))

    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert report["schema_version"] == (
        "mumei.evidence-check-attempt-acceptance-report/v1"
    )
    assert report["representation"] == "valid"
    assert report["declared_outcome"] == "valid"
    assert report["requirement_fingerprint"] == "absent"
    assert report["checks_performed"] == CHECKS_PERFORMED
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED
    assert "acceptance_schema_version" not in report
    assert "declared_field_meaning" not in report
    assert "acceptance" not in report
    assert "candidate_match" not in report
    assert "accepted" not in report
    for internal_fingerprint in (
        "a" * 64,
        "f929ae0e8d4c7e23ffb54256f115179925629a76112971aca0a591b24ad5738f",
    ):
        assert internal_fingerprint not in stdout
    assert VALID_BYTES.decode("utf-8") not in stdout
    _assert_selected(report)


def test_requirement_fingerprint_presence_is_reported_without_hash(
    tmp_path: Path, capsys
) -> None:
    acceptance = _write_acceptance(tmp_path, REQUIREMENT_BYTES)
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=_diagnostic_for(REQUIREMENT_BYTES),
    )

    code, stdout, stderr = _run(capsys, _args(core, acceptance))

    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert report["declared_outcome"] == "accepted"
    assert report["requirement_fingerprint"] == "declared"
    assert "d" * 64 not in stdout
    _assert_selected(report)


def test_consistent_non_acceptance_mismatch_still_selects_representation(
    tmp_path: Path, capsys
) -> None:
    # candidate_match=false and accepted=false are producer declarations;
    # a valid representation/consistency diagnostic is still selectable.
    acceptance = _write_acceptance(tmp_path, MISMATCH_BYTES)
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=_diagnostic_for(MISMATCH_BYTES),
    )

    code, stdout, stderr = _run(capsys, _args(core, acceptance))

    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert report["declared_outcome"] == "valid"
    assert report["requirement_fingerprint"] == "absent"
    _assert_selected(report)


def test_failed_declared_outcome_is_still_selectable_representation(
    tmp_path: Path, capsys
) -> None:
    acceptance = _write_acceptance(tmp_path, FAILED_BYTES)
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=_diagnostic_for(FAILED_BYTES),
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    report = json.loads(stdout)
    assert report["declared_outcome"] == "failed"
    _assert_selected(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "mumei.evidence-check-acceptance-check/v2"),
        ("acceptance_schema_version", "mumei.evidence-check-acceptance/v2"),
        ("representation", "invalid"),
        ("acceptance", "accepted"),
        (
            "declared_field_meaning",
            {
                "outcome": "declared_core_check_outcome",
                "candidate_match": "rechecked",
                "accepted": "producer_representation_binding_not_core_acceptance",
            },
        ),
        ("checks_performed", ["representation_gate"]),
        ("checks_not_performed", ["grade_promotion"]),
        ("declared_outcome", "unknown"),
        ("declared_outcome", True),
        ("requirement_fingerprint", "a" * 64),
        ("requirement_fingerprint", []),
    ],
)
def test_every_fixed_diagnostic_field_must_match(
    tmp_path: Path, capsys, field: str, value
) -> None:
    acceptance = _write_acceptance(tmp_path)
    diagnostic = _diagnostic_for(VALID_BYTES)
    diagnostic[field] = value
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize("field", ["schema_version", "checks_not_performed"])
def test_missing_or_unexpected_diagnostic_keys_are_rejected(
    tmp_path: Path, capsys, field: str
) -> None:
    acceptance = _write_acceptance(tmp_path)
    diagnostic = _diagnostic_for(VALID_BYTES)
    del diagnostic[field]
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_unexpected_diagnostic_key_is_rejected(tmp_path: Path, capsys) -> None:
    acceptance = _write_acceptance(tmp_path)
    diagnostic = {
        **_diagnostic_for(VALID_BYTES),
        "extra": "unrecognized",
    }
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_duplicate_diagnostic_key_is_rejected(tmp_path: Path, capsys) -> None:
    acceptance = _write_acceptance(tmp_path)
    encoded = json.dumps(_diagnostic_for(VALID_BYTES))
    encoded = encoded.replace(
        '"schema_version":',
        '"schema_version":"mumei.evidence-check-acceptance-check/v1",'
        '"schema_version":',
        1,
    )
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=encoded,
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_local_duplicate_keys_are_rejected(tmp_path: Path, capsys) -> None:
    acceptance_bytes = b'{"outcome":"valid","outcome":"valid"}'
    acceptance = _write_acceptance(tmp_path, acceptance_bytes)
    core = _write_core(
        tmp_path,
        acceptance_bytes,
        stdout=_diagnostic_for(VALID_BYTES),
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_local_outcome_must_match_core_declaration(tmp_path: Path, capsys) -> None:
    acceptance_data = json.loads(VALID_BYTES)
    acceptance_data["outcome"] = "failed"
    acceptance_bytes = json.dumps(acceptance_data).encode()
    acceptance = _write_acceptance(tmp_path, acceptance_bytes)
    core = _write_core(
        tmp_path,
        acceptance_bytes,
        stdout=_diagnostic_for(VALID_BYTES),
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize(
    ("data", "marker"),
    [
        (VALID_BYTES, "declared"),
        (REQUIREMENT_BYTES, "absent"),
    ],
)
def test_requirement_fingerprint_presence_must_match(
    tmp_path: Path, capsys, data: bytes, marker: str
) -> None:
    acceptance = _write_acceptance(tmp_path, data)
    diagnostic = _diagnostic_for(data)
    diagnostic["requirement_fingerprint"] = marker
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=diagnostic,
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_nonzero_core_exit_has_no_diagnostic_or_selection(
    tmp_path: Path, capsys
) -> None:
    acceptance = _write_acceptance(tmp_path)
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        exit_code=1,
        stdout=None,
        stderr_note="invalid acceptance record",
    )

    code, stdout, stderr = _run(capsys, _args(core, acceptance))

    assert code == 0 and stderr == ""
    _assert_unselected(json.loads(stdout), exit_code=1)


def test_core_stderr_note_does_not_invalidate_diagnostic(
    tmp_path: Path, capsys
) -> None:
    acceptance = _write_acceptance(tmp_path)
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=_diagnostic_for(VALID_BYTES),
        stderr_note="Core representation note\n",
    )

    code, stdout, stderr = _run(capsys, _args(core, acceptance))

    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert report["representation"] == "valid"
    _assert_selected(report)


def test_acceptance_input_drift_suppresses_diagnostic_and_selection(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    acceptance = _write_acceptance(tmp_path)
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=_diagnostic_for(VALID_BYTES),
    )
    original_dispatch = attempt_runner.dispatch_attempt

    def dispatch_then_drift(*args, **kwargs):
        result = original_dispatch(*args, **kwargs)
        acceptance.write_bytes(b'{"outcome":"changed"}')
        return result

    monkeypatch.setattr(
        attempt_runner, "dispatch_attempt", dispatch_then_drift
    )

    code, stdout, _ = _run(capsys, _args(core, acceptance))

    assert code == 0
    report = json.loads(stdout)
    assert report["inputs_changed"] is True
    _assert_unselected(report)


def test_oversize_acceptance_is_rejected_before_dispatch(
    tmp_path: Path, capsys
) -> None:
    acceptance = _write_acceptance(tmp_path, b"x" * 65_537)
    core = _write_core(tmp_path, acceptance.read_bytes())

    code, stdout, stderr = _run(capsys, _args(core, acceptance))

    assert code == 1 and stdout == ""
    assert "input bound" in stderr


def test_acceptance_must_be_a_regular_file(tmp_path: Path, capsys) -> None:
    acceptance = tmp_path / "acceptance-directory"
    acceptance.mkdir()
    core = _write_core(tmp_path, b"")

    code, stdout, stderr = _run(capsys, _args(core, acceptance))

    assert code == 1 and stdout == ""
    assert "regular file" in stderr


def test_posix_host_is_required(tmp_path: Path, capsys, monkeypatch) -> None:
    acceptance = _write_acceptance(tmp_path)
    core = _write_core(tmp_path, acceptance.read_bytes())
    monkeypatch.setattr(evidence_check_attempt_acceptance.os, "name", "nt")

    code, stdout, stderr = _run(capsys, _args(core, acceptance))

    assert code == 1 and stdout == ""
    assert "POSIX" in stderr


def test_output_cannot_overwrite_a_declared_input(
    tmp_path: Path, capsys
) -> None:
    acceptance = _write_acceptance(tmp_path)
    core = _write_core(tmp_path, acceptance.read_bytes())

    code, stdout, stderr = _run(
        capsys,
        _args(core, acceptance, extra=("--output", str(acceptance))),
    )

    assert code == 1 and stdout == ""
    assert "may not overwrite" in stderr


def test_attempt_timeout_is_bounded(tmp_path: Path, capsys) -> None:
    acceptance = _write_acceptance(tmp_path)
    core = _write_core(tmp_path, acceptance.read_bytes())

    code, stdout, stderr = _run(
        capsys,
        _args(
            core,
            acceptance,
            extra=("--attempt-timeout", str(MAX_CHECK_TIMEOUT_MS + 1)),
        ),
    )

    assert code == 1 and stdout == ""
    assert f"1..{MAX_CHECK_TIMEOUT_MS}" in stderr


def test_relative_core_path_is_rejected(tmp_path: Path, capsys) -> None:
    acceptance = _write_acceptance(tmp_path)
    core = _write_core(tmp_path, acceptance.read_bytes())

    code, stdout, stderr = _run(
        capsys,
        [
            "--core",
            "relative-core",
            "--acceptance",
            str(acceptance),
        ],
    )

    assert code == 1 and stdout == ""
    assert "--core must be an absolute path" in stderr
    assert core.is_file()


@pytest.mark.parametrize("fixture", [VALID_BYTES, REQUIREMENT_BYTES])
def test_mcp_tool_dispatches_declared_acceptance(
    tmp_path: Path, fixture: bytes
) -> None:
    acceptance = _write_acceptance(tmp_path, fixture)
    core = _write_core(
        tmp_path,
        acceptance.read_bytes(),
        stdout=_diagnostic_for(fixture),
    )

    result = json.loads(
        mcp_server.evidence_check_attempt_acceptance(
            str(core), str(acceptance), attempt_timeout_ms=30_000
        )
    )

    assert result["status"] == "ok"
    assert result["report"]["sequence"]["selected_result"] is not None
    assert result["report"]["requirement_fingerprint"] == (
        "declared" if fixture == REQUIREMENT_BYTES else "absent"
    )


def test_mcp_tool_reports_invalid_arguments(tmp_path: Path) -> None:
    result = json.loads(
        mcp_server.evidence_check_attempt_acceptance(
            "relative-core", "/tmp/acceptance.json"
        )
    )

    assert result["status"] == "error"
    assert "absolute path" in result["error"]


def test_cli_help_states_the_representation_only_boundary() -> None:
    help_text = (
        evidence_check_attempt_acceptance
        .build_check_attempt_acceptance_parser()
        .format_help()
    )
    help_text = " ".join(help_text.split())

    assert "candidate_match is not rechecked" in help_text
    assert "not Core Evidence acceptance" in help_text
    assert "No Core check rerun" in help_text
    assert "grade promotion" in help_text


@pytest.fixture
def real_core() -> str:
    path = os.environ.get("MUMEI_BIN")
    if path and Path(path).is_absolute() and Path(path).is_file():
        return path
    found = shutil.which("mumei")
    if found:
        return found
    pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")


@pytest.mark.integration
@pytest.mark.parametrize(
    ("fixture_name", "declared_outcome", "requirement_fingerprint"),
    [
        ("valid", "valid", "absent"),
        ("requirement", "accepted", "declared"),
        ("mismatch", "valid", "absent"),
    ],
)
def test_real_core_acceptance_fixtures_select_consistent_representation(
    capsys,
    real_core: str,
    fixture_name: str,
    declared_outcome: str,
    requirement_fingerprint: str,
) -> None:
    acceptance = FIXTURE_DIR / f"evidence_check_acceptance_{fixture_name}.json"

    code, stdout, stderr = _run(
        capsys, _args(Path(real_core), acceptance)
    )

    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["representation"] == "valid"
    assert report["declared_outcome"] == declared_outcome
    assert report["requirement_fingerprint"] == requirement_fingerprint
    _assert_selected(report)


@pytest.mark.integration
def test_real_core_rejects_inconsistent_acceptance_without_selection(
    tmp_path: Path, capsys, real_core: str
) -> None:
    acceptance_data = json.loads(VALID_BYTES)
    acceptance_data["candidate_match"] = False
    acceptance_data["accepted"] = True
    acceptance = _write_acceptance(
        tmp_path, json.dumps(acceptance_data).encode()
    )

    code, stdout, stderr = _run(
        capsys, _args(Path(real_core), acceptance)
    )

    assert code == 0 and stderr == ""
    _assert_unselected(json.loads(stdout), exit_code=1)
