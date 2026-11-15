"""Tests for the C02 evidence-identity-check route."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from agent.evidence_identity import main_identity

SOURCE = "atom main() -> i64\nrequires: true;\nensures: result == 0;\nbody: { 0 };\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _evidence(sha256: str, *, schema: str = "mumei.verification-evidence/v1",
              subject_extra: dict | None = None) -> str:
    subject = {"id": "mumei_source", "kind": "mumei_source", "sha256": sha256}
    if subject_extra:
        subject.update(subject_extra)
    return json.dumps({
        "schema_version": schema,
        "subject": subject,
        "specification": {"id": "source.postcondition", "sha256": "0" * 64},
        "obligation_id": "source_postcondition:" + "0" * 64,
    })


def _write(tmp_path: Path, name: str, content: str | bytes) -> str:
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return str(path)


def _args(evidence: str, source: str, output: str | None = None) -> Namespace:
    return Namespace(evidence=evidence, source=source, output=output)


def test_identity_match(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    evidence = _write(tmp_path, "e.json", _evidence(_sha256(SOURCE)))
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(evidence, source)) == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["schema_version"] == "mumei.evidence-file-identity/v1"
    assert descriptor["identity"] == "match"
    assert descriptor["subject_sha256"] == _sha256(SOURCE)
    assert descriptor["source_sha256"] == _sha256(SOURCE)
    assert descriptor["subject_id"] == "mumei_source"
    assert "file_identity" not in descriptor["checks_not_performed"]
    assert "freshness" in descriptor["checks_not_performed"]


def test_identity_mismatch_is_data_not_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    evidence = _write(tmp_path, "e.json", _evidence("f" * 64))
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(evidence, source)) == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["identity"] == "mismatch"
    assert descriptor["subject_sha256"] == "f" * 64
    assert descriptor["source_sha256"] == _sha256(SOURCE)


def test_evidence_not_json_refused(tmp_path: Path) -> None:
    evidence = _write(tmp_path, "e.json", "not json{")
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(evidence, source)) == 1


def test_wrong_schema_refused(tmp_path: Path) -> None:
    evidence = _write(
        tmp_path, "e.json",
        _evidence(_sha256(SOURCE), schema="mumei.other/v1"),
    )
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(evidence, source)) == 1


def test_evidence_not_object_refused(tmp_path: Path) -> None:
    evidence = _write(tmp_path, "e.json", json.dumps([1, 2, 3]))
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(evidence, source)) == 1


def test_subject_extra_key_refused(tmp_path: Path) -> None:
    evidence = _write(
        tmp_path, "e.json",
        _evidence(_sha256(SOURCE), subject_extra={"note": "x"}),
    )
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(evidence, source)) == 1


def test_subject_bad_sha256_refused(tmp_path: Path) -> None:
    for bad in ("F" * 64, "0" * 63, "g" * 64, 123):
        evidence = _write(tmp_path, "e.json", _evidence(bad))
        source = _write(tmp_path, "s.mm", SOURCE)
        assert main_identity(_args(evidence, source)) == 1, bad


def test_missing_subject_refused(tmp_path: Path) -> None:
    path = tmp_path / "e.json"
    doc = json.loads(_evidence("0" * 64))
    del doc["subject"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(str(path), source)) == 1


def test_oversized_inputs_refused(tmp_path: Path) -> None:
    evidence = _write(tmp_path, "e.json", b"x" * (65_536 + 1))
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(evidence, source)) == 1
    evidence = _write(tmp_path, "e.json", _evidence(_sha256(SOURCE)))
    source = _write(tmp_path, "big.mm", "x" * (65_536 + 1))
    assert main_identity(_args(evidence, source)) == 1


def test_missing_file_refused(tmp_path: Path) -> None:
    evidence = _write(tmp_path, "e.json", _evidence(_sha256(SOURCE)))
    assert main_identity(_args(evidence, str(tmp_path / "absent.mm"))) == 1


def test_output_writes_descriptor(tmp_path: Path) -> None:
    evidence = _write(tmp_path, "e.json", _evidence(_sha256(SOURCE)))
    source = _write(tmp_path, "s.mm", SOURCE)
    out = tmp_path / "out.json"
    assert main_identity(_args(evidence, source, str(out))) == 0
    assert json.loads(out.read_text())["identity"] == "match"


def test_output_may_not_overwrite_declared_inputs(tmp_path: Path) -> None:
    evidence = _write(tmp_path, "e.json", _evidence(_sha256(SOURCE)))
    source = _write(tmp_path, "s.mm", SOURCE)
    assert main_identity(_args(evidence, source, evidence)) == 1
    assert main_identity(_args(evidence, source, source)) == 1


def test_cli_end_to_end(tmp_path: Path) -> None:
    evidence = _write(tmp_path, "e.json", _evidence(_sha256(SOURCE)))
    source = _write(tmp_path, "s.mm", SOURCE)
    result = subprocess.run(
        [sys.executable, "-m", "agent", "evidence-identity-check",
         "--evidence", evidence, "--source", source],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["identity"] == "match"
