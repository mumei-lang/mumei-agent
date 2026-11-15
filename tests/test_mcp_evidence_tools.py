"""Tests for the C02 evidence MCP tools.

`evidence_identity_check` re-runs the CLI route's bounded byte
comparison in-process; `evidence_check_accept` restores declared
sequence/check documents and evaluates them — neither spawns Core.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from agent import mcp_server
from agent.verification_attempt import (
    AttemptEvidenceCheck,
    AttemptEvent,
    AttemptOutput,
    AttemptRecord,
    AttemptSequence,
)

FINGERPRINT = "a" * 64
FOREIGN_FINGERPRINT = "b" * 64

SOURCE = "atom main() -> i64\nrequires: true;\nensures: result == 0;\nbody: { 0 };\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write_evidence(path, subject_sha256: str):
    record = {
        "schema_version": "mumei.verification-evidence/v1",
        "subject": {"id": "s", "kind": "source", "sha256": subject_sha256},
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _selected_sequence(body: bytes = b"{}"):
    started = AttemptEvent("started", 0)
    exited = AttemptEvent("exited", 3, 0)
    attempt = AttemptRecord(FINGERPRINT, 1, 10, (started, exited))
    sequence = AttemptSequence(FINGERPRINT, 10, (attempt,))
    output = AttemptOutput(attempt, body, hashlib.sha256(body).hexdigest())
    return sequence.select_result(output)


class TestEvidenceIdentityCheckTool:
    def test_match(self, tmp_path):
        src = tmp_path / "identity.mm"
        src.write_text(SOURCE, encoding="utf-8")
        evidence = _write_evidence(tmp_path / "ev.json", _sha256(SOURCE))
        out = json.loads(
            mcp_server.evidence_identity_check(str(evidence), str(src))
        )
        assert out["status"] == "ok"
        assert out["identity"]["schema_version"] == "mumei.evidence-file-identity/v1"
        assert out["identity"]["identity"] == "match"
        assert out["identity"]["source_sha256"] == _sha256(SOURCE)

    def test_mismatch_is_data_not_error(self, tmp_path):
        src = tmp_path / "identity.mm"
        src.write_text(SOURCE, encoding="utf-8")
        foreign = tmp_path / "other.mm"
        foreign.write_text("atom f() -> i64\nbody: { 1 };\n", encoding="utf-8")
        evidence = _write_evidence(tmp_path / "ev.json", _sha256(SOURCE))
        out = json.loads(
            mcp_server.evidence_identity_check(str(evidence), str(foreign))
        )
        assert out["status"] == "ok"
        assert out["identity"]["identity"] == "mismatch"

    def test_malformed_evidence_is_error(self, tmp_path):
        src = tmp_path / "identity.mm"
        src.write_text(SOURCE, encoding="utf-8")
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        out = json.loads(
            mcp_server.evidence_identity_check(str(bad), str(src))
        )
        assert out["status"] == "error"

    def test_missing_source_is_error(self, tmp_path):
        src = tmp_path / "identity.mm"
        src.write_text(SOURCE, encoding="utf-8")
        evidence = _write_evidence(tmp_path / "ev.json", _sha256(SOURCE))
        missing = tmp_path / "gone.mm"
        out = json.loads(
            mcp_server.evidence_identity_check(str(evidence), str(missing))
        )
        assert out["status"] == "error"

    def test_error_redacts_declared_paths(self, tmp_path):
        """Model-facing errors carry basenames, never checkout-local paths."""
        src = tmp_path / "identity.mm"
        src.write_text(SOURCE, encoding="utf-8")
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        out = json.loads(
            mcp_server.evidence_identity_check(str(bad), str(src))
        )
        assert out["status"] == "error"
        assert str(bad) not in out["error"]
        assert str(src) not in out["error"]
        assert str(tmp_path) not in out["error"]

    @pytest.mark.parametrize(
        "evidence_path,source_path",
        [("", "x.mm"), ("x.json", ""), ("a\nb.json", "x.mm")],
    )
    def test_rejects_empty_or_multiline_paths(self, evidence_path, source_path):
        out = json.loads(
            mcp_server.evidence_identity_check(evidence_path, source_path)
        )
        assert out["status"] == "error"


class TestEvidenceCheckAcceptTool:
    def _check_for(self, sequence, outcome="valid"):
        return sequence.evidence_check(sequence.evidence_candidate(), outcome)

    def test_accepted_current_valid_record(self):
        sequence = _selected_sequence()
        check = self._check_for(sequence)
        out = json.loads(
            mcp_server.evidence_check_accept(
                json.dumps(sequence.to_dict()), json.dumps(check.to_dict())
            )
        )
        assert out["status"] == "ok"
        acceptance = out["acceptance"]
        assert acceptance["schema_version"] == "mumei.evidence-check-acceptance/v1"
        assert acceptance["candidate_match"] is True
        assert acceptance["accepted"] is True

    def test_foreign_check_never_accepts(self):
        sequence = _selected_sequence()
        candidate = sequence.evidence_candidate()
        foreign = AttemptEvidenceCheck(
            FOREIGN_FINGERPRINT,
            candidate.attempt_number,
            candidate.output_fingerprint,
            "valid",
        )
        out = json.loads(
            mcp_server.evidence_check_accept(
                json.dumps(sequence.to_dict()), json.dumps(foreign.to_dict())
            )
        )
        assert out["status"] == "ok"
        assert out["acceptance"]["candidate_match"] is False
        assert out["acceptance"]["accepted"] is False

    def test_failed_outcome_is_not_accepted(self):
        sequence = _selected_sequence()
        check = self._check_for(sequence, outcome="failed")
        out = json.loads(
            mcp_server.evidence_check_accept(
                json.dumps(sequence.to_dict()), json.dumps(check.to_dict())
            )
        )
        assert out["status"] == "ok"
        assert out["acceptance"]["candidate_match"] is True
        assert out["acceptance"]["accepted"] is False

    def test_sequence_without_selection_is_error(self):
        sequence = AttemptSequence(FINGERPRINT, 10)
        check = AttemptEvidenceCheck(FINGERPRINT, 1, "c" * 64, "valid")
        out = json.loads(
            mcp_server.evidence_check_accept(
                json.dumps(sequence.to_dict()), json.dumps(check.to_dict())
            )
        )
        assert out["status"] == "error"

    @pytest.mark.parametrize("name", ["sequence_json", "check_json"])
    def test_invalid_document_shapes(self, name):
        sequence = _selected_sequence()
        check = self._check_for(sequence)
        good = {
            "sequence_json": json.dumps(sequence.to_dict()),
            "check_json": json.dumps(check.to_dict()),
        }
        for bad in ("", "not json", "[]", "null", "1"):
            args = dict(good)
            args[name] = bad
            out = json.loads(mcp_server.evidence_check_accept(**args))
            assert out["status"] == "error", (name, bad)

    def test_oversized_document_is_error(self):
        sequence = _selected_sequence()
        check = self._check_for(sequence)
        oversized = json.dumps({"pad": "x" * (1024 * 1024)})
        out = json.loads(
            mcp_server.evidence_check_accept(oversized, json.dumps(check.to_dict()))
        )
        assert out["status"] == "error"


class TestPathologicalJson:
    def test_identity_tool_deep_nesting_is_error(self, tmp_path):
        bad = tmp_path / "deep.json"
        bad.write_text("[" * 30_000 + "]" * 30_000, encoding="utf-8")
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.evidence_identity_check(str(bad), str(src))
        )
        assert out["status"] == "error"

    def test_accept_tool_deep_nesting_is_error(self):
        deep = "[" * 30_000 + "]" * 30_000
        sequence = _selected_sequence()
        check = sequence.evidence_check(sequence.evidence_candidate(), "valid")
        out = json.loads(
            mcp_server.evidence_check_accept(deep, json.dumps(check.to_dict()))
        )
        assert out["status"] == "error"

    def test_accept_tool_integer_digit_limit_is_error(self):
        doc = '{"pad": ' + "1" * 5000 + "}"
        sequence = _selected_sequence()
        check = sequence.evidence_check(sequence.evidence_candidate(), "valid")
        out = json.loads(
            mcp_server.evidence_check_accept(doc, json.dumps(check.to_dict()))
        )
        assert out["status"] == "error"
