"""Tests for the C02 evidence-compare route."""

from __future__ import annotations

import hashlib
import json
from argparse import Namespace
from pathlib import Path

import pytest

from agent.evidence_compare import main_compare


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _evidence(
    sha256: str,
    *,
    spec_id: str = "source.postcondition",
    spec_sha256: str = "0" * 64,
    schema: str = "mumei.verification-evidence/v1",
) -> str:
    return json.dumps({
        "schema_version": schema,
        "subject": {"id": "mumei_source", "kind": "mumei_source",
                    "sha256": sha256},
        "specification": {"id": spec_id, "sha256": spec_sha256},
        "obligation_id": "source_postcondition:" + spec_sha256,
    })


def _write(tmp_path: Path, name: str, content: str | bytes) -> str:
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return str(path)


def _args(a: str, b: str, output: str | None = None) -> Namespace:
    return Namespace(evidence_a=a, evidence_b=b, output=output)


def test_full_claim_match(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    body = _evidence(_sha256("atom x"))
    a = _write(tmp_path, "a.json", body)
    b = _write(tmp_path, "b.json", body)
    assert main_compare(_args(a, b)) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["schema_version"] == "mumei.evidence-comparison/v1"
    assert d["subject_match"] is True
    assert d["specification_match"] is True
    assert d["claims_match"] is True
    assert "claim_truth" in d["checks_not_performed"]
    assert "file_identity" in d["checks_not_performed"]


def test_subject_mismatch_only(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    a = _write(tmp_path, "a.json", _evidence(_sha256("atom x")))
    b = _write(tmp_path, "b.json", _evidence(_sha256("atom y")))
    assert main_compare(_args(a, b)) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["subject_match"] is False
    assert d["specification_match"] is True
    assert d["claims_match"] is False


def test_specification_mismatch_only(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    same = _sha256("atom x")
    a = _write(tmp_path, "a.json", _evidence(same))
    b = _write(tmp_path, "b.json", _evidence(same, spec_id="source.other"))
    assert main_compare(_args(a, b)) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["subject_match"] is True
    assert d["specification_match"] is False
    assert d["claims_match"] is False


def test_malformed_a_is_static_error(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.json", "not json {{{")
    b = _write(tmp_path, "b.json", _evidence(_sha256("x")))
    assert main_compare(_args(a, b)) == 1


def test_wrong_schema_is_static_error(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.json", _evidence(_sha256("x"), schema="other/v9"))
    b = _write(tmp_path, "b.json", _evidence(_sha256("x")))
    assert main_compare(_args(a, b)) == 1


def test_missing_specification_is_static_error(tmp_path: Path) -> None:
    record = json.loads(_evidence(_sha256("x")))
    del record["specification"]
    a = _write(tmp_path, "a.json", json.dumps(record))
    b = _write(tmp_path, "b.json", _evidence(_sha256("x")))
    assert main_compare(_args(a, b)) == 1


def test_oversize_is_static_error(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.json", b" " * (65_536 + 1))
    b = _write(tmp_path, "b.json", _evidence(_sha256("x")))
    assert main_compare(_args(a, b)) == 1


def test_pathological_nesting_is_static_error(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.json", b"[" * 30_000 + b"]" * 30_000)
    b = _write(tmp_path, "b.json", _evidence(_sha256("x")))
    assert main_compare(_args(a, b)) == 1


def test_output_overwrite_guard(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.json", _evidence(_sha256("x")))
    b = _write(tmp_path, "b.json", _evidence(_sha256("x")))
    assert main_compare(_args(a, b, output=a)) == 1


def test_output_writes_descriptor(tmp_path: Path) -> None:
    body = _evidence(_sha256("x"))
    a = _write(tmp_path, "a.json", body)
    b = _write(tmp_path, "b.json", body)
    out = _write(tmp_path, "out.json", "")
    assert main_compare(_args(a, b, output=out)) == 0
    d = json.loads(Path(out).read_text())
    assert d["claims_match"] is True
