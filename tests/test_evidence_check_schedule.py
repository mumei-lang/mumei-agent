"""Tests for the C11 Core attempt-schedule representation-check route."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from agent import attempt_runner, evidence_check_schedule
from agent.attempt_schedule import MAX_SCHEDULE_ATTEMPTS, SCHEDULE_OUTCOMES
from agent.mcp_server import evidence_check_schedule as mcp_evidence_check_schedule

REPO_ROOT = Path(__file__).resolve().parents[1]
STUB_ADAPTER = REPO_ROOT / "tests" / "fixtures" / "stub_adapter.py"
SCHEDULE_BYTES = b'{"schema_version":"mumei.attempt-schedule/v1","fixture":true}\n'
CHECKS_PERFORMED = ["representation_gate", "schedule_consistency"]
CHECKS_NOT_PERFORMED = [
    "adapter_execution",
    "reported_outcome_truth",
    "evidence_acceptance",
    "embedded_acceptance_validation",
    "claim_truth",
    "producer_authenticity",
    "freshness",
    "resource_enforcement",
    "grade_promotion",
]
DIAGNOSTIC = {
    "schema_version": "mumei.attempt-schedule-check/v1",
    "schedule_schema_version": "mumei.attempt-schedule/v1",
    "representation": "valid",
    "acceptance": "not_evaluated",
    "outcome": "selected",
    "attempt_count": 1,
    "reported_outcome_meaning": "adapter_self_report",
    "checks_performed": CHECKS_PERFORMED,
    "checks_not_performed": CHECKS_NOT_PERFORMED,
}


def _write_schedule(tmp_path: Path, data: bytes = SCHEDULE_BYTES) -> Path:
    schedule = tmp_path / "saved-schedule.json"
    schedule.write_bytes(data)
    return schedule


def _write_core(
    tmp_path: Path,
    expected_sha256: str,
    *,
    exit_code: int = 0,
    stdout: str | None = json.dumps(DIAGNOSTIC),
) -> Path:
    core = tmp_path / "mumei-stub"
    stdout_command = "" if stdout is None else f"printf '%s' {shlex.quote(stdout)}\n"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check-schedule" ] && '
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
        f"        exit {exit_code}\n"
        "    fi\n"
        "    exit 2\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    core.chmod(0o755)
    return core


def _args(core: Path, schedule: Path, extra: tuple[str, ...] = ()) -> list[str]:
    return [
        "--core",
        str(core),
        "--schedule",
        str(schedule),
        "--attempt-timeout",
        "30000",
        *extra,
    ]


def _run(capsys, argv: list[str]) -> tuple[int, str, str]:
    try:
        code = evidence_check_schedule.main_check_schedule(
            evidence_check_schedule.build_check_schedule_parser().parse_args(argv)
        )
    except SystemExit as exc:
        code = exc.code
    output = capsys.readouterr()
    return code, output.out, output.err


def _assert_unselected(report: dict, *, exit_code: int | None = None) -> None:
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    for field in (
        "representation",
        "acceptance",
        "schedule_outcome",
        "attempt_count",
        "reported_outcome_meaning",
        "checks_performed",
        "checks_not_performed",
    ):
        assert field not in report
    if exit_code is not None:
        assert report["normalized"]["exit_code"] == exit_code


def test_check_schedule_bytes_returns_diagnostic_fields(tmp_path: Path) -> None:
    core = _write_core(tmp_path, hashlib.sha256(SCHEDULE_BYTES).hexdigest())

    report = evidence_check_schedule.check_schedule_bytes(
        str(core),
        SCHEDULE_BYTES,
        30_000,
        None,
    )

    assert report["normalized"]["exit_code"] == 0
    assert report["representation"] == "valid"
    assert report["acceptance"] == "not_evaluated"
    assert report["schedule_outcome"] == "selected"
    assert report["attempt_count"] == 1
    assert report["reported_outcome_meaning"] == "adapter_self_report"
    assert report["checks_performed"] == CHECKS_PERFORMED
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED


def test_exact_diagnostic_selects_and_hands_off_candidate(
    tmp_path: Path, capsys
) -> None:
    schedule = _write_schedule(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(schedule.read_bytes()).hexdigest())

    code, stdout, stderr = _run(capsys, _args(core, schedule))

    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert report["schema_version"] == ("mumei.evidence-check-schedule-report/v1")
    assert report["representation"] == "valid"
    assert report["acceptance"] == "not_evaluated"
    assert report["schedule_outcome"] == "selected"
    assert report["attempt_count"] == 1
    assert report["reported_outcome_meaning"] == "adapter_self_report"
    assert report["checks_performed"] == CHECKS_PERFORMED
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )


@pytest.mark.parametrize("outcome", sorted(SCHEDULE_OUTCOMES))
def test_each_declared_schedule_outcome_is_reported(
    tmp_path: Path, capsys, outcome: str
) -> None:
    schedule = _write_schedule(tmp_path)
    diagnostic = {**DIAGNOSTIC, "outcome": outcome, "attempt_count": 0}
    core = _write_core(
        tmp_path,
        hashlib.sha256(schedule.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, schedule))

    assert code == 0
    report = json.loads(stdout)
    assert report["schedule_outcome"] == outcome
    assert report["attempt_count"] == 0
    assert report["sequence"]["selected_result"] is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "mumei.attempt-schedule-check/v2"),
        ("schedule_schema_version", "mumei.attempt-schedule/v2"),
        ("representation", "invalid"),
        ("acceptance", "accepted"),
        ("reported_outcome_meaning", "truth"),
        ("checks_performed", ["representation_gate"]),
        ("checks_not_performed", ["grade_promotion"]),
    ],
)
def test_every_fixed_diagnostic_field_must_match(
    tmp_path: Path, capsys, field: str, value
) -> None:
    schedule = _write_schedule(tmp_path)
    diagnostic = copy.deepcopy(DIAGNOSTIC)
    diagnostic[field] = value
    core = _write_core(
        tmp_path,
        hashlib.sha256(schedule.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, schedule))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


def test_unexpected_diagnostic_field_is_rejected(tmp_path: Path, capsys) -> None:
    schedule = _write_schedule(tmp_path)
    diagnostic = {**DIAGNOSTIC, "extra": "unrecognized"}
    core = _write_core(
        tmp_path,
        hashlib.sha256(schedule.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, schedule))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize("outcome", ["unknown", None, [], True])
def test_unknown_or_malformed_schedule_outcome_is_rejected(
    tmp_path: Path, capsys, outcome
) -> None:
    schedule = _write_schedule(tmp_path)
    diagnostic = {**DIAGNOSTIC, "outcome": outcome}
    core = _write_core(
        tmp_path,
        hashlib.sha256(schedule.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, schedule))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize(
    "attempt_count",
    [True, False, -1, MAX_SCHEDULE_ATTEMPTS + 1, 1.5, "1", None],
)
def test_invalid_attempt_count_is_rejected(
    tmp_path: Path, capsys, attempt_count
) -> None:
    schedule = _write_schedule(tmp_path)
    diagnostic = {**DIAGNOSTIC, "attempt_count": attempt_count}
    core = _write_core(
        tmp_path,
        hashlib.sha256(schedule.read_bytes()).hexdigest(),
        stdout=json.dumps(diagnostic),
    )

    code, stdout, _ = _run(capsys, _args(core, schedule))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=0)


@pytest.mark.parametrize("exit_code", [1, 2, 3, 17])
def test_nonzero_exit_claims_no_schedule_outcome(
    tmp_path: Path, capsys, exit_code: int
) -> None:
    schedule = _write_schedule(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(schedule.read_bytes()).hexdigest(),
        exit_code=exit_code,
        stdout=None,
    )

    code, stdout, _ = _run(capsys, _args(core, schedule))

    assert code == 0
    _assert_unselected(json.loads(stdout), exit_code=exit_code)


@pytest.mark.parametrize("stdout", ["not-json", "[]", "null", "{}"])
def test_malformed_or_nonobject_stdout_claims_nothing(
    tmp_path: Path, capsys, stdout: str
) -> None:
    schedule = _write_schedule(tmp_path)
    core = _write_core(
        tmp_path,
        hashlib.sha256(schedule.read_bytes()).hexdigest(),
        stdout=stdout,
    )

    code, output, _ = _run(capsys, _args(core, schedule))

    assert code == 0
    _assert_unselected(json.loads(output), exit_code=0)


def test_input_drift_suppresses_selection(tmp_path: Path, capsys, monkeypatch) -> None:
    schedule = _write_schedule(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(schedule.read_bytes()).hexdigest())
    original_dispatch = attempt_runner.dispatch_attempt

    def dispatch_then_drift(*args, **kwargs):
        result = original_dispatch(*args, **kwargs)
        schedule.write_bytes(b'{"changed":true}\n')
        return result

    monkeypatch.setattr(attempt_runner, "dispatch_attempt", dispatch_then_drift)

    code, stdout, _ = _run(capsys, _args(core, schedule))

    assert code == 0
    report = json.loads(stdout)
    _assert_unselected(report, exit_code=0)
    assert report["inputs_changed"] is True


def test_oversize_schedule_is_rejected_before_dispatch(tmp_path: Path, capsys) -> None:
    schedule = _write_schedule(tmp_path, b"x" * 65_537)
    core = _write_core(tmp_path, "0" * 64)

    code, stdout, stderr = _run(capsys, _args(core, schedule))

    assert code == 1 and stdout == ""
    assert "input bound" in stderr


def test_nonregular_schedule_is_rejected_before_dispatch(
    tmp_path: Path, capsys
) -> None:
    core = _write_core(tmp_path, "0" * 64)
    schedule_dir = tmp_path / "schedule-dir"
    schedule_dir.mkdir()

    code, stdout, stderr = _run(capsys, _args(core, schedule_dir))

    assert code == 1 and stdout == ""
    assert "regular file" in stderr


def test_nonposix_host_is_rejected_before_dispatch(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    schedule = _write_schedule(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(schedule.read_bytes()).hexdigest())
    monkeypatch.setattr(evidence_check_schedule.os, "name", "nt")

    code, stdout, stderr = _run(capsys, _args(core, schedule))

    assert code == 1 and stdout == ""
    assert "POSIX" in stderr


def test_output_may_not_overwrite_a_declared_input(tmp_path: Path, capsys) -> None:
    schedule = _write_schedule(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(schedule.read_bytes()).hexdigest())

    code, stdout, stderr = _run(
        capsys,
        _args(core, schedule, extra=("--output", str(schedule))),
    )

    assert code == 1 and stdout == ""
    assert "declared input" in stderr


def test_mcp_tool_runs_the_schedule_check(tmp_path: Path) -> None:
    schedule = _write_schedule(tmp_path)
    core = _write_core(tmp_path, hashlib.sha256(schedule.read_bytes()).hexdigest())

    result = json.loads(mcp_evidence_check_schedule(str(core), str(schedule)))

    assert result["status"] == "ok"
    assert result["report"]["schema_version"] == (
        "mumei.evidence-check-schedule-report/v1"
    )
    assert result["report"]["schedule_outcome"] == "selected"


def _write_agent_schedule(tmp_path: Path) -> Path:
    profile = "mumei.test/v1"
    contract = {
        "profile": profile,
        "method": "deductive_proof",
        "scope": "unbounded",
        "correspondence_relation": "exact_model",
        "correspondence_status": "assumed",
    }

    def write(name: str, document: dict) -> Path:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    request = write(
        "request",
        {
            "profile": profile,
            "method": "deductive_proof",
            "result_contract": contract,
            "input_format": "mumei.source-text/v1",
        },
    )
    adapters = write(
        "adapters",
        [
            {
                "schema_version": "mumei.verifier-adapter/v1",
                "adapter_id": "integration-adapter",
                "adapter_version": "1.0.0",
                "profiles": [profile],
                "methods": ["deductive_proof"],
                "result_contracts": [contract],
                "input_formats": ["mumei.source-text/v1"],
                "required_permissions": [],
            }
        ],
    )
    argv_map = write(
        "argv-map",
        {
            "integration-adapter": [
                sys.executable,
                str(STUB_ADAPTER),
            ]
        },
    )
    policy = write(
        "policy",
        {
            "allowed_permissions": ["process.spawn"],
            "allow_fallback": False,
            "timeout_ms": 10_000,
        },
    )
    observations = write(
        "observations",
        [
            {
                "adapter_id": "integration-adapter",
                "availability": "available",
                "tool_version": "1.0.0",
                "stamp": 1,
            }
        ],
    )
    source = tmp_path / "source.mm"
    source.write_bytes(b"FAKE_PRIVATE_SOURCE_NOT_EVIDENCE")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent",
            "verify-schedule",
            "--request",
            str(request),
            "--adapters",
            str(adapters),
            "--argv-map",
            str(argv_map),
            "--policy",
            str(policy),
            "--observations",
            str(observations),
            "--source",
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env={
            "PYTHONPATH": str(REPO_ROOT),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["schema_version"] == "mumei.attempt-schedule/v1"
    assert document["outcome"] == "selected"
    schedule = tmp_path / "agent-produced-schedule.json"
    schedule.write_text(completed.stdout, encoding="utf-8")
    return schedule


@pytest.fixture
def real_core() -> str:
    path = os.environ.get("MUMEI_BIN")
    if not path or not Path(path).is_absolute() or not Path(path).is_file():
        pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")
    return path


@pytest.mark.integration
def test_real_core_accepts_agent_generated_verify_schedule(
    tmp_path: Path, capsys, real_core: str
) -> None:
    schedule = _write_agent_schedule(tmp_path)
    schedule_bytes = schedule.read_bytes()

    core_check = subprocess.run(
        [
            real_core,
            "evidence",
            "check-schedule",
            "--stdin",
            "--json",
        ],
        input=schedule_bytes,
        capture_output=True,
        timeout=60,
    )
    assert core_check.returncode == 0, (
        "Core rejected the agent-produced verify-schedule document: "
        f"exit={core_check.returncode}; "
        f"stdout={core_check.stdout!r}; stderr={core_check.stderr!r}"
    )
    core_diagnostic = json.loads(core_check.stdout)
    assert core_diagnostic["representation"] == "valid"
    assert core_diagnostic["schedule_schema_version"] == ("mumei.attempt-schedule/v1")

    code, stdout, stderr = _run(
        capsys,
        _args(Path(real_core).resolve(), schedule),
    )

    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["schema_version"] == ("mumei.evidence-check-schedule-report/v1")
    assert report["representation"] == "valid"
    assert report["acceptance"] == "not_evaluated"
    assert report["schedule_outcome"] == core_diagnostic["outcome"]
    assert report["attempt_count"] == core_diagnostic["attempt_count"]
    assert report["reported_outcome_meaning"] == "adapter_self_report"
    assert report["checks_performed"] == CHECKS_PERFORMED
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )
