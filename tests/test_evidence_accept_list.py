"""Tests for Core's declared-requirement Evidence-list acceptance route."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent import mcp_server
from agent.evidence_accept_list import (
    CONJUNCTIVE_ACCEPTANCE_SCHEMA,
    LIST_SCHEMA_VERSION,
    MAX_INPUT_BYTES,
    REQUIREMENT_LIST_SCHEMA_VERSION,
    REQUIREMENT_SCHEMA_VERSION,
    SINGLE_ACCEPTANCE_SCHEMA,
    build_accept_list_parser,
    run_accept_list,
)

MUMEI_BIN = os.environ.get("MUMEI_BIN")

CHECKS_PERFORMED = [
    "representation",
    "declared_requirement_normalization",
    "cross_record_pin_agreement",
]
CHECKS_NOT_PERFORMED = [
    "claim_truth",
    "producer_authenticity",
    "grade_promotion",
    "freshness",
    "tool_execution",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inputs(tmp_path: Path, mode: str = "requirement"):
    list_bytes = json.dumps(
        {"schema_version": LIST_SCHEMA_VERSION, "evidence": []},
        separators=(",", ":"),
    ).encode()
    list_path = tmp_path / "evidence-list.json"
    list_path.write_bytes(list_bytes)
    requirement_path = tmp_path / "requirement.json"
    if mode == "requirement":
        requirement_doc = {"schema_version": REQUIREMENT_SCHEMA_VERSION}
    else:
        requirement_doc = {
            "schema_version": REQUIREMENT_LIST_SCHEMA_VERSION,
            "requirements": [
                {"schema_version": REQUIREMENT_SCHEMA_VERSION},
            ],
        }
    requirement_bytes = json.dumps(
        requirement_doc, separators=(",", ":")
    ).encode()
    requirement_path.write_bytes(requirement_bytes)
    return list_path, list_bytes, requirement_path, requirement_bytes


def _descriptor(
    mode: str,
    list_bytes: bytes,
    requirement_bytes: bytes,
    verdict: str = "accepted",
) -> dict:
    descriptor = {
        "schema_version": (
            SINGLE_ACCEPTANCE_SCHEMA
            if mode == "requirement"
            else CONJUNCTIVE_ACCEPTANCE_SCHEMA
        ),
        "evidence_schema_version": LIST_SCHEMA_VERSION,
        "requirement_schema_version": (
            REQUIREMENT_SCHEMA_VERSION
            if mode == "requirement"
            else REQUIREMENT_LIST_SCHEMA_VERSION
        ),
        "list_fingerprint": _sha256(list_bytes),
        "acceptance": "evaluated",
        "verdict": verdict,
        "consistent": True,
        "conflict_count": 0,
        "conflicts": [],
        "records_evaluated": 1,
        "checks_performed": list(CHECKS_PERFORMED),
        "checks_not_performed": list(CHECKS_NOT_PERFORMED),
    }
    if mode == "requirement":
        descriptor["requirement_fingerprint"] = _sha256(requirement_bytes)
        descriptor["records"] = []
    else:
        descriptor["requirement_list_fingerprint"] = _sha256(
            requirement_bytes
        )
        descriptor["requirements_evaluated"] = 1
        descriptor["requirements"] = []
    return descriptor


def _write_core(
    tmp_path: Path,
    list_path: Path,
    list_bytes: bytes,
    requirement_path: Path,
    requirement_bytes: bytes,
    descriptor: dict,
    exit_code: int = 0,
    *,
    mode: str | None = None,
    stdout: bytes | None = None,
    stderr: bytes = b"",
    mutate_path: Path | None = None,
    marker_path: Path | None = None,
) -> Path:
    selected_mode = mode or (
        "requirement"
        if "requirement_fingerprint" in descriptor
        else "requirement-list"
    )
    mode_flag = (
        "--requirement"
        if selected_mode == "requirement"
        else "--requirement-list"
    )
    expected_argv = [
        "evidence",
        "accept-list",
        "--stdin",
        "--json",
        mode_flag,
        str(requirement_path),
    ]
    output = (
        stdout
        if stdout is not None
        else json.dumps(descriptor, separators=(",", ":")).encode()
    )
    script = (
        f"#!{sys.executable}\n"
        "import hashlib, pathlib, sys\n"
        f"if sys.argv[1:] != {expected_argv!r}: sys.exit(91)\n"
        "payload = sys.stdin.buffer.read()\n"
        f"if hashlib.sha256(payload).hexdigest() != {_sha256(list_bytes)!r}:"
        " sys.exit(92)\n"
        f"requirement = pathlib.Path({str(requirement_path)!r}).read_bytes()\n"
        f"if hashlib.sha256(requirement).hexdigest() != "
        f"{_sha256(requirement_bytes)!r}: sys.exit(93)\n"
    )
    if marker_path is not None:
        script += f"pathlib.Path({str(marker_path)!r}).write_text('called')\n"
    if mutate_path is not None:
        script += (
            f"pathlib.Path({str(mutate_path)!r}).write_bytes(b'drifted')\n"
        )
    script += (
        f"sys.stdout.buffer.write({output!r})\n"
        f"sys.stderr.buffer.write({stderr!r})\n"
        f"sys.exit({exit_code})\n"
    )
    core = tmp_path / "mumei-stub"
    core.write_text(script, encoding="utf-8")
    core.chmod(0o755)
    return core


def _args(
    core: Path,
    list_path: Path,
    requirement_path: Path,
    mode: str = "requirement",
):
    argv = ["--core", str(core), "--list", str(list_path)]
    if mode == "requirement":
        argv += ["--requirement", str(requirement_path)]
    else:
        argv += ["--requirement-list", str(requirement_path)]
    return build_accept_list_parser().parse_args(argv)


def _unselected(report: dict) -> None:
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report


def _no_verdict(report: dict) -> None:
    for field in (
        "acceptance_schema",
        "verdict",
        "consistent",
        "conflict_count",
        "records_evaluated",
        "requirements_evaluated",
        "checks_performed",
        "checks_not_performed",
    ):
        assert field not in report
    _unselected(report)


@pytest.mark.parametrize("mode", ["requirement", "requirement-list"])
def test_accepted_descriptor_selects_and_reports_aggregate_fields(
    tmp_path: Path, mode: str
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path, mode
    )
    descriptor = _descriptor(mode, list_bytes, requirement_bytes)
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
        mode=mode,
    )

    report = run_accept_list(_args(core, list_path, requirement_path, mode))

    assert report["schema_version"] == "mumei.evidence-accept-list-report/v1"
    assert report["acceptance_schema"] == descriptor["schema_version"]
    assert report["verdict"] == "accepted"
    assert report["consistent"] is True
    assert report["conflict_count"] == 0
    assert report["records_evaluated"] == 1
    assert report["checks_performed"] == CHECKS_PERFORMED
    assert report["checks_not_performed"] == CHECKS_NOT_PERFORMED
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )
    assert report["sequence"]["selected_result"] is not None
    assert "conflicts" not in report
    assert "records" not in report
    assert "requirements" not in report
    if mode == "requirement-list":
        assert report["requirements_evaluated"] == 1
    else:
        assert "requirements_evaluated" not in report


@pytest.mark.parametrize(
    ("verdict", "exit_code"),
    [("rejected", 1), ("inconclusive", 3)],
)
def test_rejected_and_inconclusive_verdicts_do_not_select(
    tmp_path: Path, verdict: str, exit_code: int
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor(
        "requirement", list_bytes, requirement_bytes, verdict=verdict
    )
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
        exit_code,
        stderr=b"Core verdict diagnostic\n",
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    assert report["verdict"] == verdict
    assert report["acceptance_schema"] == SINGLE_ACCEPTANCE_SCHEMA
    assert report["normalized"]["exit_code"] == exit_code
    _unselected(report)


@pytest.mark.parametrize(
    ("verdict", "exit_code"),
    [("accepted", 1), ("rejected", 0), ("inconclusive", 1)],
)
def test_exit_and_verdict_must_agree(
    tmp_path: Path, verdict: str, exit_code: int
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor(
        "requirement", list_bytes, requirement_bytes, verdict=verdict
    )
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
        exit_code,
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    _no_verdict(report)


@pytest.mark.parametrize("verdict", [[], {}])
def test_unhashable_verdict_is_rejected_without_raising(
    tmp_path: Path, verdict: object
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor("requirement", list_bytes, requirement_bytes)
    descriptor["verdict"] = verdict
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    _no_verdict(report)


@pytest.mark.parametrize(
    ("mode", "wrong_mode"),
    [
        ("requirement", "requirement-list"),
        ("requirement-list", "requirement"),
    ],
)
def test_mode_specific_schema_mismatch_is_not_reported(
    tmp_path: Path, mode: str, wrong_mode: str
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path, mode
    )
    descriptor = _descriptor(wrong_mode, list_bytes, requirement_bytes)
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
        mode=mode,
    )

    report = run_accept_list(_args(core, list_path, requirement_path, mode))

    _no_verdict(report)


@pytest.mark.parametrize(
    ("mode", "field"),
    [
        ("requirement", "list_fingerprint"),
        ("requirement", "requirement_fingerprint"),
        ("requirement-list", "list_fingerprint"),
        ("requirement-list", "requirement_list_fingerprint"),
    ],
)
def test_wrong_input_fingerprints_are_not_reported(
    tmp_path: Path, mode: str, field: str
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path, mode
    )
    descriptor = _descriptor(mode, list_bytes, requirement_bytes)
    descriptor[field] = "0" * 64
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )

    report = run_accept_list(_args(core, list_path, requirement_path, mode))

    _no_verdict(report)


def test_duplicate_top_level_keys_are_rejected(tmp_path: Path) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor("requirement", list_bytes, requirement_bytes)
    raw = json.dumps(descriptor, separators=(",", ":"))
    raw = raw[:-1] + ',"verdict":"rejected"}'
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
        stdout=raw.encode(),
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    _no_verdict(report)


def test_forbidden_checks_cannot_be_reported_as_performed(
    tmp_path: Path,
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor("requirement", list_bytes, requirement_bytes)
    descriptor["checks_performed"].append("grade_promotion")
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    _no_verdict(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("consistent", 1),
        ("conflict_count", True),
        ("conflict_count", -1),
        ("records_evaluated", False),
        ("records_evaluated", -1),
        ("conflicts", {}),
        ("checks_performed", ["valid", 1]),
        ("checks_not_performed", "claim_truth"),
    ],
)
def test_malformed_aggregate_fields_are_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor("requirement", list_bytes, requirement_bytes)
    descriptor[field] = value
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    _no_verdict(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_schema_version", "mumei.verification-evidence/v1"),
        ("acceptance", "not_evaluated"),
        ("unexpected", True),
    ],
)
def test_schema_and_exact_key_set_are_enforced(
    tmp_path: Path, field: str, value: object
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor("requirement", list_bytes, requirement_bytes)
    descriptor[field] = value
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    _no_verdict(report)


@pytest.mark.parametrize(
    "forbidden",
    ["grade_promotion", "producer_authenticity", "claim_truth"],
)
def test_forbidden_checks_must_remain_unperformed(
    tmp_path: Path, forbidden: str
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor("requirement", list_bytes, requirement_bytes)
    descriptor["checks_not_performed"].remove(forbidden)
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    _no_verdict(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requirements_evaluated", True),
        ("requirements_evaluated", -1),
        ("records_evaluated", True),
    ],
)
def test_malformed_conjunctive_counts_are_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path, "requirement-list"
    )
    descriptor = _descriptor(
        "requirement-list", list_bytes, requirement_bytes
    )
    descriptor[field] = value
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )

    report = run_accept_list(
        _args(core, list_path, requirement_path, "requirement-list")
    )

    _no_verdict(report)


@pytest.mark.parametrize("input_to_mutate", ["list", "requirement"])
def test_input_drift_suppresses_verdict_and_selection(
    tmp_path: Path, input_to_mutate: str
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor("requirement", list_bytes, requirement_bytes)
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
        mutate_path=(
            list_path if input_to_mutate == "list" else requirement_path
        ),
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    assert report["inputs_changed"] is True
    _no_verdict(report)


def test_oversized_descriptor_is_reported_as_truncated(tmp_path: Path) -> None:
    from agent.verification_attempt import MAX_STDOUT_BYTES

    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    descriptor = _descriptor("requirement", list_bytes, requirement_bytes)
    descriptor["records"] = [{"pad": "x" * 1024}] * (
        MAX_STDOUT_BYTES // 1024 + 1
    )
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )

    report = run_accept_list(_args(core, list_path, requirement_path))

    assert report["descriptor_truncated"] is True
    assert report["normalized"]["exit_code"] == 0
    _no_verdict(report)


def test_parser_requires_exactly_one_requirement_mode() -> None:
    parser = build_accept_list_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--core", "/core", "--list", "/list"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--core",
                "/core",
                "--list",
                "/list",
                "--requirement",
                "/requirement",
                "--requirement-list",
                "/requirement-list",
            ]
        )


@pytest.mark.parametrize("oversize", ["list", "requirement"])
def test_oversize_input_is_rejected_before_dispatch(
    tmp_path: Path, oversize: str
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path
    )
    if oversize == "list":
        list_bytes = b"x" * (MAX_INPUT_BYTES + 1)
        list_path.write_bytes(list_bytes)
    else:
        requirement_bytes = b"x" * (MAX_INPUT_BYTES + 1)
        requirement_path.write_bytes(requirement_bytes)
    marker = tmp_path / "core-was-run"
    descriptor = _descriptor(
        "requirement", list_bytes, requirement_bytes
    )
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
        marker_path=marker,
    )

    with pytest.raises(ValueError, match="Core input bound"):
        run_accept_list(_args(core, list_path, requirement_path))
    assert not marker.exists()


def test_non_regular_inputs_are_rejected_before_dispatch(tmp_path: Path) -> None:
    list_path, _, requirement_path, _ = _inputs(tmp_path)
    core = tmp_path / "core"
    core.write_text("stub", encoding="utf-8")

    with pytest.raises(ValueError, match="regular file"):
        run_accept_list(_args(core, tmp_path, requirement_path))


@pytest.mark.parametrize("mode", ["requirement", "requirement-list"])
def test_mcp_tool_supports_both_requirement_modes(
    tmp_path: Path, mode: str
) -> None:
    list_path, list_bytes, requirement_path, requirement_bytes = _inputs(
        tmp_path, mode
    )
    descriptor = _descriptor(mode, list_bytes, requirement_bytes)
    core = _write_core(
        tmp_path,
        list_path,
        list_bytes,
        requirement_path,
        requirement_bytes,
        descriptor,
    )
    kwargs = (
        {"requirement_path": str(requirement_path)}
        if mode == "requirement"
        else {"requirement_list_path": str(requirement_path)}
    )

    result = json.loads(
        mcp_server.evidence_accept_list(
            str(core), str(list_path), **kwargs
        )
    )

    assert result["status"] == "ok"
    assert result["report"]["verdict"] == "accepted"
    assert result["report"]["acceptance_schema"] == descriptor["schema_version"]


def test_mcp_tool_rejects_both_or_neither_requirement_arguments(
    tmp_path: Path,
) -> None:
    list_path, _, requirement_path, _ = _inputs(tmp_path)
    core = tmp_path / "core"
    core.write_text("stub", encoding="utf-8")

    neither = json.loads(
        mcp_server.evidence_accept_list(str(core), str(list_path))
    )
    both = json.loads(
        mcp_server.evidence_accept_list(
            str(core),
            str(list_path),
            requirement_path=str(requirement_path),
            requirement_list_path=str(requirement_path),
        )
    )

    assert neither["status"] == "error"
    assert both["status"] == "error"


@pytest.mark.integration
@pytest.mark.skipif(
    not MUMEI_BIN or not Path(MUMEI_BIN).is_file(),
    reason="MUMEI_BIN does not point at a real mumei binary",
)
@pytest.mark.parametrize("mode", ["requirement", "requirement-list"])
def test_real_core_accept_list_reports_accepted_descriptor(
    tmp_path: Path, mode: str
) -> None:
    source = tmp_path / "main.mm"
    source.write_text(
        "atom main() -> i64\n"
        "requires: true;\n"
        "ensures: result == 0;\n"
        "body: { 0 };\n",
        encoding="utf-8",
    )
    produced = subprocess.run(
        [str(Path(MUMEI_BIN).resolve()), "evidence", "verify-source",
         str(source), "--json"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert produced.returncode == 0, produced.stderr.decode(
        "utf-8", errors="replace"
    )
    record = json.loads(produced.stdout)
    list_path = tmp_path / "evidence-list.json"
    list_path.write_text(
        json.dumps(
            {
                "schema_version": LIST_SCHEMA_VERSION,
                "evidence": [record],
            }
        ),
        encoding="utf-8",
    )
    requirement = {
        "schema_version": REQUIREMENT_SCHEMA_VERSION,
        "subject_sha256": record["subject"]["sha256"],
        "obligation_id": record["obligation_id"],
        "semantics": {
            "profile": record["semantics"]["profile"],
            "integer_model": record["semantics"]["integer_model"],
            "target_triple": record["semantics"]["target_triple"],
        },
        "minimum_assurance": "unbounded_proof",
        "correspondence_status": ["validated", "assumed"],
        "excluded_assumptions": [],
    }
    requirement_path = tmp_path / "requirement.json"
    if mode == "requirement":
        requirement_path.write_text(json.dumps(requirement), encoding="utf-8")
        acceptance_schema = SINGLE_ACCEPTANCE_SCHEMA
    else:
        requirement_path.write_text(
            json.dumps(
                {
                    "schema_version": REQUIREMENT_LIST_SCHEMA_VERSION,
                    "requirements": [requirement],
                }
            ),
            encoding="utf-8",
        )
        acceptance_schema = CONJUNCTIVE_ACCEPTANCE_SCHEMA
    args = _args(Path(MUMEI_BIN).resolve(), list_path, requirement_path, mode)

    report = run_accept_list(args)

    assert report["acceptance_schema"] == acceptance_schema
    assert report["verdict"] == "accepted"
    assert report["normalized"]["exit_code"] == 0
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )
