"""Tests for the C02 and C11 declared-evidence MCP tools.

`evidence_identity_check` re-runs the CLI route's bounded byte
comparison in-process; `evidence_check_accept` restores declared
sequence/check documents and evaluates them. C11 fold tools preserve
CLI payloads and remain spawn-free.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from agent import (
    binding_eval as binding_route,
    evidence_acceptance_eval as acceptance_route,
    freshness_eval as freshness_route,
    mcp_server,
    recovery_eval as recovery_route,
    signature_eval as signature_eval_route,
    signature_verify as signature_verify_route,
)
from tests import (
    test_signature_eval as signature_eval_fixtures,
    test_signature_verify as signature_verify_fixtures,
)
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


def _write_stub_core(tmp_path, exits: dict):
    """Stub `mumei`: per-subcommand exit codes; verify-source emits a
    fake record and `evidence check` the canonical diagnostic."""
    diagnostic = {
        "schema_version": "mumei.evidence-representation-check/v1",
        "evidence_schema_version": "mumei.verification-evidence/v1",
        "representation": "valid",
        "acceptance": "not_evaluated",
        "checks_not_performed": [
            "claim_truth", "file_identity", "freshness",
            "producer_authenticity", "semantic_correspondence",
            "artifact_semantics",
        ],
    }
    evidence = {"schema_version": "mumei.verification-evidence/v1", "record": True}
    lines = ["#!/bin/sh\n"]
    lines.append(
        'if [ "$1" = "evidence" ] && [ "$2" = "verify-source" ]; then\n'
        f'    printf \'%s\' \'{json.dumps(evidence)}\'\n'
        f'    exit {exits.get("verify-source", 0)}\n'
        'elif [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
        "    cat >/dev/null\n"
        f'    if [ {exits.get("check", 0)} -eq 0 ]; then\n'
        f'        printf \'%s\' \'{json.dumps(diagnostic)}\'\n'
        "    fi\n"
        f'    exit {exits.get("check", 0)}\n'
        'elif [ "$1" = "evidence" ] && [ "$2" = "recheck-source" ]; then\n'
        f'    printf \'%s\' \'{{"schema_version":"mumei.evidence-consistency/v1"}}\'\n'
        f'    exit {exits.get("recheck-source", 0)}\n'
        'elif [ "$1" = "native-bundle" ] && [ "$2" = "recheck-llvm" ]; then\n'
        f'    printf \'%s\' \'{{"schema_version":"mumei.native-consumer-evidence/v1"}}\'\n'
        f'    exit {exits.get("recheck-llvm", 0)}\n'
        'elif [ "$1" = "native-bundle" ] && [ "$2" = "accept-artifact" ]; then\n'
        f'    if [ {exits.get("accept-artifact", 0)} -eq 0 ]; then\n'
        '        printf \'%s\' \'{"schema_version":"mumei.native-evidence-acceptance/v1","accepted":true}\'\n'
        "    fi\n"
        f'    exit {exits.get("accept-artifact", 0)}\n'
        'elif [ "$1" = "native-bundle" ] && [ "$2" = "recheck-evidence" ]; then\n'
        f'    if [ {exits.get("recheck-evidence", 0)} -eq 0 ]; then\n'
        '        printf \'%s\' \'Saved native Evidence consistent\'\n'
        "    fi\n"
        f'    exit {exits.get("recheck-evidence", 0)}\n'
        'elif [ "$1" = "native-bundle" ] && [ "$2" = "accept-evidence" ]; then\n'
        f'    if [ {exits.get("accept-evidence", 0)} -eq 0 ]; then\n'
        '        printf \'%s\' \'{"schema_version":"mumei.native-evidence-acceptance/v1","accepted":true}\'\n'
        "    fi\n"
        f'    exit {exits.get("accept-evidence", 0)}\n'
        "fi\n"
        "exit 2\n"
    )
    core = tmp_path / "mumei-stub"
    core.write_text("".join(lines))
    core.chmod(0o755)
    return core


class TestVerifyAttemptTool:
    def test_selected_result_reports_acceptance(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(mcp_server.verify_attempt(str(core), str(src)))
        assert out["status"] == "ok"
        report = out["report"]
        assert report["schema_version"] == "mumei.verify-attempt-report/v1"
        assert report["acceptance"]["accepted"] is True
        assert report["candidate"] is not None

    def test_refuted_exit_has_no_selection(self, tmp_path):
        core = _write_stub_core(tmp_path, {"verify-source": 1})
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(mcp_server.verify_attempt(str(core), str(src)))
        assert out["status"] == "ok"
        assert "selected_result" not in out["report"]["sequence"]
        assert "acceptance" not in out["report"]

    def test_bad_args_are_errors(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        for args in (
            ("", str(src)),
            (str(core), ""),
        ):
            out = json.loads(mcp_server.verify_attempt(*args))
            assert out["status"] == "error"
        out = json.loads(mcp_server.verify_attempt(str(core), str(src), attempt_timeout_ms=0))
        assert out["status"] == "error"

    def test_error_redacts_declared_paths(self, tmp_path):
        missing_core = tmp_path / "no-such-core"
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.verify_attempt(str(missing_core), str(src))
        )
        assert out["status"] == "error"
        assert str(missing_core) not in out["error"]
        assert str(src) not in out["error"]


class TestVerifyRecheckTool:
    def test_consistent_outcome(self, tmp_path):
        core = _write_stub_core(tmp_path, {"recheck-source": 0})
        evidence = _write_evidence(tmp_path / "ev.json", _sha256(SOURCE))
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.verify_recheck(str(core), str(evidence), str(src))
        )
        assert out["status"] == "ok"
        assert out["report"]["recheck"] == "consistent"

    def test_inconclusive_outcome(self, tmp_path):
        core = _write_stub_core(tmp_path, {"recheck-source": 3})
        evidence = _write_evidence(tmp_path / "ev.json", _sha256(SOURCE))
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.verify_recheck(str(core), str(evidence), str(src))
        )
        assert out["status"] == "ok"
        assert out["report"]["recheck"] == "inconclusive"

    def test_missing_evidence_is_error(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        missing = tmp_path / "gone.json"
        out = json.loads(
            mcp_server.verify_recheck(str(core), str(missing), str(src))
        )
        assert out["status"] == "error"
        assert str(missing) not in out["error"]


class TestNativeRecheckTool:
    def _bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        record = bundle / "native-bundle.json"
        record.write_text(json.dumps({
            "schema": "mumei.native-bundle/v1",
            "files": {
                "llvm_ir": {}, "object": {},
                "certificate": {}, "executable": {},
            },
        }), encoding="utf-8")
        for name in ("program.ll", "program.o", "proof-cert.json", "program"):
            (bundle / name).write_text("x", encoding="utf-8")
        return bundle, hashlib.sha256(record.read_bytes()).hexdigest()

    def test_equivalent_outcome(self, tmp_path):
        core = _write_stub_core(tmp_path, {"recheck-llvm": 0})
        bundle, build_id = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.native_recheck(str(core), str(bundle), str(src), build_id)
        )
        assert out["status"] == "ok"
        assert out["report"]["recheck"] == "equivalent"

    def test_bad_build_id_is_error(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        bundle, _ = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.native_recheck(str(core), str(bundle), str(src), "zz" * 32)
        )
        assert out["status"] == "error"


class TestNativeAcceptTool:
    def _bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        record = bundle / "native-bundle.json"
        record.write_text(json.dumps({
            "schema": "mumei.native-bundle/v1",
            "files": {
                "llvm_ir": {}, "object": {},
                "certificate": {}, "executable": {},
            },
        }), encoding="utf-8")
        for name in ("program.ll", "program.o", "proof-cert.json", "program"):
            (bundle / name).write_text("x", encoding="utf-8")
        return bundle, hashlib.sha256(record.read_bytes()).hexdigest()

    def test_accepted_outcome(self, tmp_path):
        core = _write_stub_core(tmp_path, {"accept-artifact": 0})
        bundle, build_id = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.native_accept(str(core), str(bundle), str(src), build_id)
        )
        assert out["status"] == "ok"
        assert out["report"]["acceptance"] == "accepted"
        assert "candidate" not in out["report"]

    def test_bad_build_id_is_error(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        bundle, _ = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.native_accept(str(core), str(bundle), str(src), "zz" * 32)
        )
        assert out["status"] == "error"

    def test_record_without_files_map_is_error(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "native-bundle.json").write_text("{}\n", encoding="utf-8")
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.native_accept(
                str(core), str(bundle), str(src), "a" * 64
            )
        )
        assert out["status"] == "error"


class TestNativeEvidenceRecheckTool:
    def _bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        record = bundle / "native-bundle.json"
        record.write_text(json.dumps({
            "schema": "mumei.native-bundle/v1",
            "files": {
                "llvm_ir": {}, "object": {},
                "certificate": {}, "executable": {},
            },
        }), encoding="utf-8")
        for name in ("program.ll", "program.o", "proof-cert.json", "program"):
            (bundle / name).write_text("x", encoding="utf-8")
        return bundle, hashlib.sha256(record.read_bytes()).hexdigest()

    def _evidence(self, tmp_path):
        evidence = tmp_path / "saved.json"
        evidence.write_text(
            '{"schema_version":"mumei.native-consumer-evidence/v1"}',
            encoding="utf-8",
        )
        return evidence

    def test_consistent_outcome(self, tmp_path):
        core = _write_stub_core(tmp_path, {"recheck-evidence": 0})
        bundle, build_id = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        evidence = self._evidence(tmp_path)
        out = json.loads(
            mcp_server.native_evidence_recheck(
                str(core), str(bundle), str(src), str(evidence), build_id
            )
        )
        assert out["status"] == "ok"
        assert out["report"]["evidence_recheck"] == "consistent"
        assert "candidate" not in out["report"]

    def test_missing_evidence_is_error(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        bundle, build_id = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.native_evidence_recheck(
                str(core), str(bundle), str(src),
                str(tmp_path / "absent.json"), build_id,
            )
        )
        assert out["status"] == "error"

    def test_bad_build_id_is_error(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        bundle, _ = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        evidence = self._evidence(tmp_path)
        out = json.loads(
            mcp_server.native_evidence_recheck(
                str(core), str(bundle), str(src), str(evidence), "zz" * 32
            )
        )
        assert out["status"] == "error"


class TestNativeEvidenceAcceptTool:
    def _bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        record = bundle / "native-bundle.json"
        record.write_text(json.dumps({
            "schema": "mumei.native-bundle/v1",
            "files": {
                "llvm_ir": {}, "object": {},
                "certificate": {}, "executable": {},
            },
        }), encoding="utf-8")
        for name in ("program.ll", "program.o", "proof-cert.json", "program"):
            (bundle / name).write_text("x", encoding="utf-8")
        return bundle, hashlib.sha256(record.read_bytes()).hexdigest()

    def _evidence(self, tmp_path):
        evidence = tmp_path / "saved.json"
        evidence.write_text(
            '{"schema_version":"mumei.native-consumer-evidence/v1"}',
            encoding="utf-8",
        )
        return evidence

    def test_accepted_outcome(self, tmp_path):
        core = _write_stub_core(tmp_path, {"accept-evidence": 0})
        bundle, build_id = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        evidence = self._evidence(tmp_path)
        out = json.loads(
            mcp_server.native_evidence_accept(
                str(core), str(bundle), str(src), str(evidence), build_id
            )
        )
        assert out["status"] == "ok"
        assert out["report"]["acceptance"] == "accepted"
        assert "candidate" not in out["report"]

    def test_rejected_exit_claims_no_outcome(self, tmp_path):
        core = _write_stub_core(tmp_path, {"accept-evidence": 1})
        bundle, build_id = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        evidence = self._evidence(tmp_path)
        out = json.loads(
            mcp_server.native_evidence_accept(
                str(core), str(bundle), str(src), str(evidence), build_id
            )
        )
        assert out["status"] == "ok"
        assert "acceptance" not in out["report"]
        assert "selected_result" not in out["report"]["sequence"]

    def test_missing_evidence_is_error(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        bundle, build_id = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        out = json.loads(
            mcp_server.native_evidence_accept(
                str(core), str(bundle), str(src),
                str(tmp_path / "absent.json"), build_id,
            )
        )
        assert out["status"] == "error"

    def test_bad_build_id_is_error(self, tmp_path):
        core = _write_stub_core(tmp_path, {})
        bundle, _ = self._bundle(tmp_path)
        src = tmp_path / "s.mm"
        src.write_text(SOURCE, encoding="utf-8")
        evidence = self._evidence(tmp_path)
        out = json.loads(
            mcp_server.native_evidence_accept(
                str(core), str(bundle), str(src), str(evidence), "zz" * 32
            )
        )
        assert out["status"] == "error"


class TestEvidenceCompareTool:
    def _evidence(self, sha: str, spec_id: str = "source.postcondition") -> str:
        return json.dumps({
            "schema_version": "mumei.verification-evidence/v1",
            "subject": {"id": "mumei_source", "kind": "mumei_source",
                        "sha256": sha},
            "specification": {"id": spec_id, "sha256": "0" * 64},
        })

    def test_claims_match(self, tmp_path):
        body = self._evidence(_sha256("atom x"))
        a = tmp_path / "a.json"; a.write_text(body)
        b = tmp_path / "b.json"; b.write_text(body)
        out = json.loads(mcp_server.evidence_compare(str(a), str(b)))
        assert out["status"] == "ok"
        c = out["comparison"]
        assert c["schema_version"] == "mumei.evidence-comparison/v1"
        assert c["claims_match"] is True

    def test_claims_mismatch(self, tmp_path):
        a = tmp_path / "a.json"; a.write_text(self._evidence(_sha256("x")))
        b = tmp_path / "b.json"; b.write_text(self._evidence(_sha256("y")))
        out = json.loads(mcp_server.evidence_compare(str(a), str(b)))
        assert out["status"] == "ok"
        assert out["comparison"]["subject_match"] is False
        assert out["comparison"]["claims_match"] is False

    def test_empty_and_multiline_paths(self, tmp_path):
        b = tmp_path / "b.json"; b.write_text(self._evidence(_sha256("x")))
        for bad in ("", "x\ny"):
            out = json.loads(mcp_server.evidence_compare(bad, str(b)))
            assert out["status"] == "error"
            out = json.loads(mcp_server.evidence_compare(str(b), bad))
            assert out["status"] == "error"

    def test_error_redacts_declared_paths(self, tmp_path):
        a = tmp_path / "missing-a.json"
        b = tmp_path / "b.json"; b.write_text(self._evidence(_sha256("x")))
        out = json.loads(mcp_server.evidence_compare(str(a), str(b)))
        assert out["status"] == "error"
        assert str(a) not in out["error"]
        assert str(b) not in out["error"]

    def test_malformed_record_is_error(self, tmp_path):
        a = tmp_path / "a.json"; a.write_text("not json")
        b = tmp_path / "b.json"; b.write_text(self._evidence(_sha256("x")))
        out = json.loads(mcp_server.evidence_compare(str(a), str(b)))
        assert out["status"] == "error"
class TestNativeAttemptTool:
    def _write_build_core(self, tmp_path, complete: bool = True,
                          build_exit: int = 0):
        names = ("native-bundle.json", "program.ll", "program.o",
                 "proof-cert.json", "program")
        record = (
            '{"schema": "mumei.native-bundle/v1", "files": {'
            '"llvm_ir": {}, "object": {}, "certificate": {}, '
            '"executable": {}}}'
        )
        lines = []
        for n in (names if complete else names[:-1]):
            if n == "native-bundle.json":
                lines.append(f"    printf %s '{record}' > \"$out/{n}\"")
            else:
                lines.append(f'    printf %s "{n}-bytes" > "$out/{n}"')
        members = "\n".join(lines)
        py = (
            "import hashlib,sys;"
            'print(hashlib.sha256(open(sys.argv[1],"rb").read())'
            ".hexdigest())"
        )
        core = tmp_path / "mumei-stub"
        core.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "native-bundle" ] && [ "$2" = "build" ]; then\n'
            '    out="$5"\n'
            "    mkdir -p \"$out\"\n"
            f"{members}\n"
            '    printf "Build ID: %s\\n" '
            f'"$(python3 -c \'{py}\' "$out/native-bundle.json")"\n'
            f"    exit {build_exit}\n"
            "fi\n"
            "exit 2\n"
        )
        core.chmod(0o755)
        return core

    def test_selected_build_reports_build_id(self, tmp_path):
        core = self._write_build_core(tmp_path)
        src = tmp_path / "main.mm"; src.write_text("atom")
        bundle = tmp_path / "bundle"
        out = json.loads(mcp_server.native_attempt(
            str(core), str(src), str(bundle)))
        assert out["status"] == "ok"
        report = out["report"]
        assert report["schema_version"] == "mumei.native-attempt-report/v1"
        assert report["build_id"] == hashlib.sha256(
            (bundle / "native-bundle.json").read_bytes()).hexdigest()
        assert report["candidate"]["schema_version"] == (
            "mumei.verifier-evidence-candidate/v1"
        )
        assert (bundle / "program").is_file()

    def test_incomplete_bundle_selects_nothing(self, tmp_path):
        core = self._write_build_core(tmp_path, complete=False)
        src = tmp_path / "main.mm"; src.write_text("atom")
        out = json.loads(mcp_server.native_attempt(
            str(core), str(src), str(tmp_path / "bundle")))
        assert out["status"] == "ok"
        assert "candidate" not in out["report"]

    def test_bad_args_and_redaction(self, tmp_path):
        src = tmp_path / "main.mm"; src.write_text("atom")
        out = json.loads(mcp_server.native_attempt("", str(src), "/b"))
        assert out["status"] == "error"
        missing = tmp_path / "missing-mumei"
        out = json.loads(mcp_server.native_attempt(
            str(missing), str(src), str(tmp_path / "bundle")))
        assert out["status"] == "error"
        assert str(missing) not in out["error"]
class TestEvidenceCheckTool:
    def test_valid_record_reports_representation(self, tmp_path):
        core = _write_stub_core(tmp_path, {"check": 0})
        evidence = _write_evidence(tmp_path / "ev.json", _sha256(SOURCE))
        out = json.loads(
            mcp_server.evidence_check(str(core), str(evidence))
        )
        assert out["status"] == "ok"
        report = out["report"]
        assert report["schema_version"] == "mumei.evidence-check-report/v1"
        assert report["representation"] == "valid"
        assert report["candidate"]["schema_version"] == (
            "mumei.verifier-evidence-candidate/v1"
        )

    def test_rejected_record_claims_nothing(self, tmp_path):
        core = _write_stub_core(tmp_path, {"check": 1})
        evidence = _write_evidence(tmp_path / "ev.json", _sha256(SOURCE))
        out = json.loads(
            mcp_server.evidence_check(str(core), str(evidence))
        )
        assert out["status"] == "ok"
        report = out["report"]
        assert "representation" not in report
        assert "candidate" not in report
        assert report["normalized"]["exit_code"] == 1

    def test_bad_args_and_redaction(self, tmp_path):
        evidence = _write_evidence(tmp_path / "ev.json", _sha256(SOURCE))
        out = json.loads(mcp_server.evidence_check("", str(evidence)))
        assert out["status"] == "error"
        missing = tmp_path / "missing.json"
        core = _write_stub_core(tmp_path, {})
        out = json.loads(
            mcp_server.evidence_check(str(core), str(missing))
        )
        assert out["status"] == "error"
        assert str(missing) not in out["error"]


_SCHEDULE_PROFILE = "mumei.test/v1"
_SCHEDULE_SOURCE = b"FAKE_PRIVATE_SOURCE_NOT_EVIDENCE"


def _schedule_inputs(tmp_path):
    def write(name, doc):
        path = tmp_path / f"FAKE_PRIVATE_{name}.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    def manifest(adapter_id):
        return {
            "schema_version": "mumei.verifier-adapter/v1",
            "adapter_id": adapter_id,
            "adapter_version": "1.0.0",
            "profiles": [_SCHEDULE_PROFILE],
            "methods": ["deductive_proof"],
            "result_contracts": [
                {
                    "profile": _SCHEDULE_PROFILE,
                    "method": "deductive_proof",
                    "scope": "unbounded",
                    "correspondence_relation": "exact_model",
                    "correspondence_status": "assumed",
                }
            ],
            "input_formats": ["mumei.source-text/v1"],
            "required_permissions": [],
        }

    source = tmp_path / "FAKE_PRIVATE_SOURCE.mm"
    source.write_bytes(_SCHEDULE_SOURCE)
    import sys

    py = sys.executable
    return {
        "request": write(
            "request",
            {
                "profile": _SCHEDULE_PROFILE,
                "method": "deductive_proof",
                "result_contract": {
                    "profile": _SCHEDULE_PROFILE,
                    "method": "deductive_proof",
                    "scope": "unbounded",
                    "correspondence_relation": "exact_model",
                    "correspondence_status": "assumed",
                },
                "input_format": "mumei.source-text/v1",
            },
        ),
        "adapters": write("adapters", [manifest("alpha"), manifest("beta")]),
        "argv_map": write(
            "argv",
            {
                "alpha": [py, "-c", "import sys; sys.exit(3)"],
                "beta": [py, "-c", "import sys; sys.exit(0)"],
            },
        ),
        "policy": write("policy", {"allowed_permissions": [], "timeout_ms": 10000}),
        "observations": write(
            "obs",
            [
                {"adapter_id": "alpha", "availability": "available",
                 "tool_version": "1.0.0", "stamp": 1},
                {"adapter_id": "beta", "availability": "available",
                 "tool_version": "1.0.0", "stamp": 2},
            ],
        ),
        "source": str(source),
    }


class TestVerifyScheduleTool:
    def test_selected_result_reports_descriptor(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"],
                inputs["adapters"],
                inputs["argv_map"],
                inputs["policy"],
                inputs["source"],
                observations_path=inputs["observations"],
            )
        )
        assert out["status"] == "ok"
        report = out["report"]
        assert report["schema_version"] == "mumei.attempt-schedule/v1"
        assert report["outcome"] == "selected"
        assert report["selected_adapter_id"] == "beta"
        assert "FAKE_PRIVATE" not in json.dumps(report)

    def test_core_path_records_evidence_check(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        # The selected adapter emits declared bytes; the stub Core
        # accepts only their exact sha256 — the fed-bytes binding is
        # verified, not just the check outcome.
        expected = "BETA_DECLARED_OUTPUT"
        expected_sha = hashlib.sha256(expected.encode()).hexdigest()
        argv_doc = json.loads(Path(inputs["argv_map"]).read_text())
        argv_doc["beta"] = [
            sys.executable, "-c",
            f"import sys; sys.stdout.write({expected!r}); sys.exit(0)",
        ]
        Path(inputs["argv_map"]).write_text(json.dumps(argv_doc))
        diagnostic = {
            "schema_version": "mumei.evidence-representation-check/v1",
            "evidence_schema_version": "mumei.verification-evidence/v1",
            "representation": "valid",
            "acceptance": "not_evaluated",
            "checks_not_performed": [
                "claim_truth", "file_identity", "freshness",
                "producer_authenticity", "semantic_correspondence",
                "artifact_semantics",
            ],
        }
        core = tmp_path / "mumei-stub"
        # sha via Python — no mktemp/SHA tool dependency across platforms.
        sha_check = (
            '"%s" -c "import hashlib, sys; '
            'd = sys.stdin.buffer.read(); '
            "sys.exit(0 if hashlib.sha256(d).hexdigest() == '"
            + expected_sha
            + "' else 1)"
            '"'
        ) % sys.executable
        core.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
            "    " + sha_check + " || exit 1\n"
            "    printf %s '" + json.dumps(diagnostic) + "'\n"
            "    exit 0\n"
            "fi\n"
            "exit 2\n"
        )
        core.chmod(0o755)
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"], inputs["adapters"],
                inputs["argv_map"], inputs["policy"], inputs["source"],
                observations_path=inputs["observations"],
                core_path=str(core),
            )
        )
        assert out["status"] == "ok"
        report = out["report"]
        assert report["evidence_check"]["outcome"] == "valid"
        assert report["evidence_acceptance"]["accepted"] is True
        assert "FAKE_PRIVATE" not in json.dumps(report)

    @pytest.mark.parametrize("verdict,accepted", [
        ("accepted", True), ("rejected", False), ("inconclusive", False),
    ])
    def test_core_requirement_path_records_verdict(
        self, tmp_path, verdict, accepted
    ):
        inputs = _schedule_inputs(tmp_path)
        req = tmp_path / "requirement.json"
        req.write_text(
            json.dumps({"schema_version": "mumei.evidence-requirement/v1"}),
            encoding="utf-8",
        )
        code = (
            0 if verdict == "accepted"
            else 1 if verdict == "rejected" else 3
        )
        core = tmp_path / f"mumei-stub-accept-{verdict}"
        core.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "evidence" ] && [ "$2" = "accept" ]; then\n'
            '    [ "$5" = "--requirement" ] || exit 4\n'
            '    [ -f "$6" ] || exit 5\n'
            "    sum=$(sha256sum | cut -d' ' -f1)\n"
            "    req=$(sha256sum \"$6\" | cut -d' ' -f1)\n"
            '    printf %s "{\\"schema_version\\":\\"mumei.evidence-acceptance/v1\\",'
            '\\"requirement_fingerprint\\":\\"$req\\",'
            '\\"evidence_fingerprint\\":\\"$sum\\",'
            '\\"acceptance\\":\\"evaluated\\",'
            '\\"verdict\\":\\"' + verdict + '\\"}"\n'
            f"    exit {code}\n"
            "fi\n"
            "exit 2\n"
        )
        core.chmod(0o755)
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"], inputs["adapters"],
                inputs["argv_map"], inputs["policy"], inputs["source"],
                observations_path=inputs["observations"],
                core_path=str(core),
                core_requirement_path=str(req),
            )
        )
        assert out["status"] == "ok"
        report = out["report"]
        assert report["evidence_check"]["outcome"] == verdict
        assert report["evidence_acceptance"]["accepted"] is accepted
        assert report["evidence_acceptance"]["requirement_fingerprint"] == (
            hashlib.sha256(req.read_bytes()).hexdigest()
        )

    def test_core_requirement_path_requires_core(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        req = tmp_path / "requirement.json"
        req.write_text("{}", encoding="utf-8")
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"], inputs["adapters"],
                inputs["argv_map"], inputs["policy"], inputs["source"],
                core_requirement_path=str(req),
            )
        )
        assert out["status"] == "error"
        assert "core_path" in out["error"]

    @pytest.mark.parametrize("verdict,accepted", [
        ("accepted", True), ("rejected", False), ("inconclusive", False),
    ])
    def test_core_requirement_list_path_records_verdict(
        self, tmp_path, verdict, accepted
    ):
        inputs = _schedule_inputs(tmp_path)
        req = tmp_path / "requirement-list.json"
        req.write_text(
            json.dumps({
                "schema_version": "mumei.evidence-requirement-list/v1",
                "requirements": [
                    {"schema_version": "mumei.evidence-requirement/v1"}
                ],
            }),
            encoding="utf-8",
        )
        code = (
            0 if verdict == "accepted"
            else 1 if verdict == "rejected" else 3
        )
        core = tmp_path / f"mumei-stub-accept-list-{verdict}"
        core.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "evidence" ] && [ "$2" = "accept" ]; then\n'
            '    [ "$5" = "--requirement-list" ] || exit 4\n'
            '    [ -f "$6" ] || exit 5\n'
            "    sum=$(sha256sum | cut -d' ' -f1)\n"
            "    req=$(sha256sum \"$6\" | cut -d' ' -f1)\n"
            '    printf %s "{\\"schema_version\\":\\"mumei.evidence-requirement-list-acceptance/v1\\",'
            '\\"requirement_schema_version\\":\\"mumei.evidence-requirement-list/v1\\",'
            '\\"evidence_schema_version\\":\\"mumei.verification-evidence/v1\\",'
            '\\"requirement_list_fingerprint\\":\\"$req\\",'
            '\\"evidence_fingerprint\\":\\"$sum\\",'
            '\\"requirements\\":[{\\"index\\":0,\\"verdict\\":\\"' + verdict + '\\"}],'
            '\\"acceptance\\":\\"evaluated\\",'
            '\\"verdict\\":\\"' + verdict + '\\"}"\n'
            f"    exit {code}\n"
            "fi\n"
            "exit 2\n"
        )
        core.chmod(0o755)
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"], inputs["adapters"],
                inputs["argv_map"], inputs["policy"], inputs["source"],
                observations_path=inputs["observations"],
                core_path=str(core),
                core_requirement_list_path=str(req),
            )
        )
        assert out["status"] == "ok"
        report = out["report"]
        assert report["evidence_check"]["outcome"] == verdict
        assert report["evidence_acceptance"]["accepted"] is accepted
        assert report["evidence_acceptance"]["requirement_fingerprint"] == (
            hashlib.sha256(req.read_bytes()).hexdigest()
        )

    def test_core_requirement_list_path_requires_core(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        req = tmp_path / "requirement-list.json"
        req.write_text("{}", encoding="utf-8")
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"], inputs["adapters"],
                inputs["argv_map"], inputs["policy"], inputs["source"],
                core_requirement_list_path=str(req),
            )
        )
        assert out["status"] == "error"
        assert "core_path" in out["error"]

    def test_core_requirement_list_path_conflicts(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        req = tmp_path / "requirement.json"
        req.write_text("{}", encoding="utf-8")
        req_list = tmp_path / "requirement-list.json"
        req_list.write_text("{}", encoding="utf-8")
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"], inputs["adapters"],
                inputs["argv_map"], inputs["policy"], inputs["source"],
                core_path=str(tmp_path / "core"),
                core_requirement_path=str(req),
                core_requirement_list_path=str(req_list),
            )
        )
        assert out["status"] == "error"
        assert "conflicts" in out["error"]

    def test_bad_args_are_errors(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        out = json.loads(mcp_server.verify_schedule("", inputs["adapters"],
                                                    inputs["argv_map"],
                                                    inputs["policy"],
                                                    inputs["source"]))
        assert out["status"] == "error"
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"], inputs["adapters"], inputs["argv_map"],
                inputs["policy"], inputs["source"], max_attempts=0,
            )
        )
        assert out["status"] == "error"
        out = json.loads(
            mcp_server.verify_schedule(
                inputs["request"], inputs["adapters"], inputs["argv_map"],
                inputs["policy"], inputs["source"], max_attempts=99,
            )
        )
        assert out["status"] == "error"

    def test_error_redacts_declared_paths(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        missing = str(tmp_path / "missing.json")
        out = json.loads(
            mcp_server.verify_schedule(
                missing, inputs["adapters"], inputs["argv_map"],
                inputs["policy"], inputs["source"],
            )
        )
        assert out["status"] == "error"
        for path in inputs.values():
            assert path not in out["error"]
        assert missing not in out["error"]


class TestVerifyPlanTool:
    def test_plan_reports_selected_adapter(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        out = json.loads(
            mcp_server.verify_plan(
                inputs["request"], inputs["adapters"],
                inputs["policy"], observations_path=inputs["observations"],
            )
        )
        assert out["status"] == "ok"
        report = out["report"]
        assert report["schema_version"] == "mumei.verification-plan/v1"
        assert report["selected"]["adapter_id"] == "alpha"
        assert "FAKE_PRIVATE" not in json.dumps(report)

    def test_plan_without_observations(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        out = json.loads(
            mcp_server.verify_plan(
                inputs["request"], inputs["adapters"], inputs["policy"],
            )
        )
        assert out["status"] == "ok"
        assert out["report"]["schema_version"] == "mumei.verification-plan/v1"

    def test_plan_rejects_malformed_path(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        out = json.loads(
            mcp_server.verify_plan("", inputs["adapters"], inputs["policy"])
        )
        assert out["status"] == "error"
        assert "request_path" in out["error"]

    def test_plan_error_redacts_declared_paths(self, tmp_path):
        inputs = _schedule_inputs(tmp_path)
        missing = str(tmp_path / "missing.json")
        out = json.loads(
            mcp_server.verify_plan(
                missing, inputs["adapters"], inputs["policy"],
            )
        )
        assert out["status"] == "error"
        for path in inputs.values():
            assert path not in out["error"]
        assert missing not in out["error"]


def _fold_payload(raw: str) -> dict:
    return json.loads(raw)


def _fold_write_json(path: Path, value: dict | list) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _fold_cli_payload(module, argv: list[str], output_path: Path) -> dict:
    parser = argparse.ArgumentParser()
    module.build_eval_parser(parser)
    args = parser.parse_args([*argv, "--output", str(output_path)])
    assert module.main_eval(args) == 0
    return json.loads(output_path.read_text(encoding="utf-8"))


def _signature_cli_payload(
    build_parser, main_route, argv: list[str], output_path: Path
) -> dict:
    parser = argparse.ArgumentParser()
    build_parser(parser)
    args = parser.parse_args([*argv, "--output", str(output_path)])
    assert main_route(args) == 0
    return json.loads(output_path.read_text(encoding="utf-8"))


def _signature_cli_error(build_parser, main_route, argv, capsys) -> str:
    parser = argparse.ArgumentParser()
    build_parser(parser)
    assert main_route(parser.parse_args(argv)) == 1
    error = capsys.readouterr().err.strip()
    prefix, separator, message = error.partition(": ")
    assert separator
    assert prefix in {"signature-eval", "signature-verify"}
    return message


def _fold_assert_error(raw: str) -> dict:
    payload = _fold_payload(raw)
    assert payload["status"] == "error"
    assert isinstance(payload["error"], str)
    return payload


def _fold_acceptance_descriptor(**overrides) -> dict:
    descriptor = {
        "schema_version": "mumei.source-evidence-acceptance/v1",
        "acceptance": "evaluated",
        "accepted": True,
        "scope": "saved_source_record_and_fresh_same_profile_recheck",
        "checks_performed": ["representation_check", "fresh_source_recheck"],
        "checks_not_performed": ["producer_authenticity"],
        "evidence_fingerprint": "a" * 64,
    }
    descriptor.update(overrides)
    return descriptor


def _fold_binding_document(subject_digest: str) -> dict:
    return {
        "schema_version": "mumei.producer-signature/v1",
        "subject_digest": subject_digest,
        "algorithm": "ed25519",
        "signature": "ab" * 64,
        "producer_key_id": "key-1",
    }


def _fold_record(checks: list[str]) -> dict:
    return {
        "schema_version": "mumei.example-record/v1",
        "checks_not_performed": checks,
    }


def _fold_acceptance_evidence(record_bytes: bytes, *, accepted=True) -> dict:
    return {
        "schema_version": "mumei.source-evidence-acceptance/v1",
        "accepted": accepted,
        "evidence_fingerprint": hashlib.sha256(record_bytes).hexdigest(),
    }


class TestEvidenceAcceptanceEvalTool:
    def test_accepted_descriptor_cli_parity_without_and_with_fingerprint(
        self, tmp_path
    ) -> None:
        descriptor = _fold_write_json(
            tmp_path / "descriptor.json", _fold_acceptance_descriptor()
        )
        cases = (
            (None, None),
            ("a" * 64, True),
            ("b" * 64, False),
        )
        for index, (fingerprint, attempt_bound) in enumerate(cases):
            argv = ["--descriptor", str(descriptor)]
            if fingerprint is not None:
                argv.extend(["--expected-fingerprint", fingerprint])
            cli = _fold_cli_payload(
                acceptance_route, argv, tmp_path / f"acceptance-{index}.json"
            )
            tool = _fold_payload(
                mcp_server.evidence_acceptance_eval(
                    str(descriptor), fingerprint
                )
            )
            assert tool["status"] == "ok"
            assert tool["evaluation"] == cli
            assert cli["accepted"] is True
            if attempt_bound is None:
                assert "attempt_bound" not in cli
            else:
                assert cli["attempt_bound"] is attempt_bound

    @pytest.mark.parametrize("path", ["", "line\nbreak", None, 7])
    def test_invalid_descriptor_paths_are_rejected(self, path) -> None:
        payload = _fold_assert_error(
            mcp_server.evidence_acceptance_eval(path)
        )
        assert "descriptor_path must be a nonempty single-line path" in (
            payload["error"]
        )

    def test_missing_descriptor_path_is_redacted(self, tmp_path) -> None:
        missing = tmp_path / "missing-descriptor.json"
        payload = _fold_assert_error(
            mcp_server.evidence_acceptance_eval(str(missing))
        )
        assert str(tmp_path) not in payload["error"]

    @pytest.mark.parametrize(
        "body",
        [b" " * (1024 * 1024 + 1), b"[]", b"\xff"],
        ids=["oversized", "non-object", "invalid-utf8"],
    )
    def test_invalid_descriptor_documents_fail_statically(
        self, tmp_path, body: bytes
    ) -> None:
        descriptor = tmp_path / "bad-descriptor.json"
        descriptor.write_bytes(body)
        payload = _fold_assert_error(
            mcp_server.evidence_acceptance_eval(str(descriptor))
        )
        assert payload["status"] == "error"

    @pytest.mark.parametrize("fingerprint", ["not-a-digest", 7, True])
    def test_malformed_expected_fingerprint_is_an_error(
        self, tmp_path, fingerprint
    ) -> None:
        descriptor = _fold_write_json(
            tmp_path / "descriptor.json", _fold_acceptance_descriptor()
        )
        payload = _fold_assert_error(
            mcp_server.evidence_acceptance_eval(
                str(descriptor), fingerprint
            )
        )
        assert "attempt_bound" not in payload


class TestFreshnessEvalTool:
    def test_fresh_stale_and_unclaimed_records_match_cli(self, tmp_path) -> None:
        reference = "2026-11-18T01:00:00Z"
        cases = (
            ({"produced_at": "2026-11-18T00:00:00Z"}, 7200, True),
            ({"produced_at": "2026-11-18T00:00:00Z"}, 1800, False),
            ({}, 7200, False),
        )
        for index, (record_value, age, expected) in enumerate(cases):
            record = _fold_write_json(
                tmp_path / f"record-{index}.json", record_value
            )
            cli = _fold_cli_payload(
                freshness_route,
                [
                    "--record",
                    str(record),
                    "--reference-time",
                    reference,
                    "--max-age-seconds",
                    str(age),
                ],
                tmp_path / f"freshness-{index}.json",
            )
            tool = _fold_payload(
                mcp_server.freshness_eval(str(record), reference, age)
            )
            assert tool["status"] == "ok"
            assert tool["evaluation"] == cli
            assert cli["within_window"] is expected
            if index == 2:
                assert cli["freshness_claimed"] is False

    def test_huge_max_age_returns_json_ok(self, tmp_path) -> None:
        record = _fold_write_json(
            tmp_path / "record.json",
            {"produced_at": "2026-01-01T00:00:00Z"},
        )
        payload = _fold_payload(
            mcp_server.freshness_eval(
                str(record), "2026-01-01T00:00:01Z", 10**18
            )
        )
        assert payload["status"] == "ok"
        assert payload["evaluation"]["within_window"] is True

    @pytest.mark.parametrize("path", ["", "line\nbreak", None, 7])
    def test_invalid_record_paths_are_rejected(self, path) -> None:
        payload = _fold_assert_error(
            mcp_server.freshness_eval(
                path, "2026-11-18T01:00:00Z", 1
            )
        )
        assert "record_path must be a nonempty single-line path" in (
            payload["error"]
        )

    def test_missing_record_path_is_redacted(self, tmp_path) -> None:
        missing = tmp_path / "a\\b.json"
        payload = _fold_assert_error(
            mcp_server.freshness_eval(
                str(missing), "2026-11-18T01:00:00Z", 1
            )
        )
        assert str(tmp_path) not in payload["error"]
        assert repr(str(missing))[1:-1] not in payload["error"]

    @pytest.mark.parametrize(
        "body",
        [b" " * (1024 * 1024 + 1), b"[]", b"\xff"],
        ids=["oversized", "non-object", "invalid-utf8"],
    )
    def test_invalid_record_documents_fail_statically(
        self, tmp_path, body: bytes
    ) -> None:
        record = tmp_path / "bad-record.json"
        record.write_bytes(body)
        payload = _fold_assert_error(
            mcp_server.freshness_eval(
                str(record), "2026-11-18T01:00:00Z", 1
            )
        )
        assert payload["status"] == "error"

    @pytest.mark.parametrize("max_age", [True, "1"])
    def test_max_age_requires_non_boolean_integer(self, tmp_path, max_age) -> None:
        missing = str(tmp_path / "unread-record.json")
        payload = _fold_assert_error(
            mcp_server.freshness_eval(
                missing, "2026-11-18T01:00:00Z", max_age
            )
        )
        assert payload["error"] == "max_age_seconds must be an int"

    @pytest.mark.parametrize("max_age", [True, "3600"])
    def test_dispatch_rejects_coerced_max_age_values(
        self, tmp_path, max_age
    ) -> None:
        record = _fold_write_json(tmp_path / "record.json", {})
        with pytest.raises(ToolError):
            asyncio.run(
                mcp_server.mcp.call_tool(
                    "freshness_eval",
                    {
                        "record_path": str(record),
                        "reference_time": "2026-11-18T01:00:00Z",
                        "max_age_seconds": max_age,
                    },
                )
            )

    def test_dispatch_accepts_strict_integer_max_age(self, tmp_path) -> None:
        record = _fold_write_json(tmp_path / "record.json", {})
        content = asyncio.run(
            mcp_server.mcp.call_tool(
                "freshness_eval",
                {
                    "record_path": str(record),
                    "reference_time": "2026-11-18T01:00:00Z",
                    "max_age_seconds": 3600,
                },
            )
        )
        payload = _fold_payload(content[0][0].text)
        assert payload["status"] == "ok"
        assert payload["evaluation"]["freshness_claimed"] is False

    def test_bad_reference_time_is_an_error(self, tmp_path) -> None:
        record = _fold_write_json(tmp_path / "record.json", {})
        payload = _fold_assert_error(
            mcp_server.freshness_eval(str(record), "not-a-time", 10)
        )
        assert payload["error"] == "invalid reference time"


class TestBindingEvalTool:
    def test_bound_and_mismatched_documents_match_cli(self, tmp_path) -> None:
        record_bytes = b'{"schema_version":"mumei.example-record/v1","claim":1}'
        record = tmp_path / "record.json"
        record.write_bytes(record_bytes)
        digest = hashlib.sha256(record_bytes).hexdigest()
        for index, subject in enumerate((digest, "b" * 64)):
            evidence = _fold_write_json(
                tmp_path / f"evidence-{index}.json",
                _fold_binding_document(subject),
            )
            cli = _fold_cli_payload(
                binding_route,
                ["--record", str(record), "--evidence", str(evidence)],
                tmp_path / f"binding-{index}.json",
            )
            tool = _fold_payload(
                mcp_server.binding_eval(str(record), str(evidence))
            )
            assert tool["status"] == "ok"
            assert tool["binding"] == cli
            assert cli["bound"] is (index == 0)
            assert cli["record_digest"] == digest

    @pytest.mark.parametrize(
        ("record_path", "evidence_path", "error_key"),
        [
            ("", "evidence.json", "record_path"),
            ("line\nbreak", "evidence.json", "record_path"),
            (None, "evidence.json", "record_path"),
            ("record.json", "", "evidence_path"),
            ("record.json", "line\nbreak", "evidence_path"),
            ("record.json", 7, "evidence_path"),
        ],
    )
    def test_invalid_binding_paths_are_rejected(
        self, record_path, evidence_path, error_key
    ) -> None:
        payload = _fold_assert_error(
            mcp_server.binding_eval(record_path, evidence_path)
        )
        assert f"{error_key} must be a nonempty single-line path" in (
            payload["error"]
        )

    def test_missing_record_path_is_redacted(self, tmp_path) -> None:
        evidence = _fold_write_json(
            tmp_path / "evidence.json", _fold_binding_document("a" * 64)
        )
        missing = tmp_path / "a\\b.json"
        payload = _fold_assert_error(
            mcp_server.binding_eval(str(missing), str(evidence))
        )
        assert str(tmp_path) not in payload["error"]
        assert repr(str(missing))[1:-1] not in payload["error"]

    @pytest.mark.parametrize(
        "body",
        [b" " * (1024 * 1024 + 1), b"[]", b"\xff"],
        ids=["oversized", "non-object", "invalid-utf8"],
    )
    def test_invalid_evidence_documents_fail_statically(
        self, tmp_path, body: bytes
    ) -> None:
        record = tmp_path / "record.bin"
        record.write_bytes(b"record")
        evidence = tmp_path / "bad-evidence.json"
        evidence.write_bytes(body)
        payload = _fold_assert_error(
            mcp_server.binding_eval(str(record), str(evidence))
        )
        assert payload["status"] == "error"


class TestRecoveryEvalTool:
    def test_recovered_failed_and_no_evidence_match_cli(self, tmp_path) -> None:
        record_bytes = json.dumps(_fold_record(["claim_truth"])).encode()
        record = tmp_path / "record.json"
        record.write_bytes(record_bytes)
        cases = (
            (_fold_acceptance_evidence(record_bytes), "recovered"),
            (
                _fold_acceptance_evidence(record_bytes, accepted=False),
                "evidence_failed",
            ),
            ({"schema_version": "mumei.unknown/v1"}, "no_evidence"),
        )
        for index, (document, expected) in enumerate(cases):
            evidence = _fold_write_json(
                tmp_path / f"evidence-{index}.json", document
            )
            cli = _fold_cli_payload(
                recovery_route,
                ["--record", str(record), "--evidence", str(evidence)],
                tmp_path / f"recovery-{index}.json",
            )
            tool = _fold_payload(
                mcp_server.recovery_eval(str(record), [str(evidence)])
            )
            assert tool["status"] == "ok"
            assert tool["recovery"] == cli
            assert cli["checks"]["claim_truth"] == expected

    def test_lone_surrogate_record_returns_utf8_payload(self, tmp_path) -> None:
        record = _fold_write_json(
            tmp_path / "record.json", _fold_record(["\ud800"])
        )
        evidence = _fold_write_json(
            tmp_path / "evidence.json",
            {"schema_version": "mumei.unknown/v1"},
        )
        raw = mcp_server.recovery_eval(str(record), [str(evidence)])
        raw.encode("utf-8")
        payload = json.loads(raw)
        assert payload["recovery"]["checks"]["\ud800"] == "no_evidence"

    def test_binding_document_for_other_record_does_not_recover_binding(
        self, tmp_path
    ) -> None:
        record_bytes = json.dumps(
            _fold_record(["evidence_binding"])
        ).encode()
        other_record_bytes = b'{"schema_version":"mumei.other-record/v1"}'
        record = tmp_path / "record.json"
        other_record = tmp_path / "other-record.json"
        record.write_bytes(record_bytes)
        other_record.write_bytes(other_record_bytes)
        subject = hashlib.sha256(other_record_bytes).hexdigest()
        envelope = _fold_write_json(
            tmp_path / "envelope.json", _fold_binding_document(subject)
        )
        other_binding = _fold_payload(
            mcp_server.binding_eval(str(other_record), str(envelope))
        )["binding"]
        assert other_binding["bound"] is True
        assert other_binding["record_digest"] == hashlib.sha256(
            other_record_bytes
        ).hexdigest()
        binding_document = _fold_write_json(
            tmp_path / "binding.json", other_binding
        )
        cli = _fold_cli_payload(
            recovery_route,
            [
                "--record",
                str(record),
                "--evidence",
                str(binding_document),
            ],
            tmp_path / "recovery.json",
        )
        tool = _fold_payload(
            mcp_server.recovery_eval(str(record), [str(binding_document)])
        )
        assert tool["recovery"] == cli
        assert cli["checks"]["evidence_binding"] == "evidence_failed"

    @pytest.mark.parametrize("record_path", ["", "line\nbreak", None, 7])
    def test_invalid_record_paths_are_rejected(self, record_path) -> None:
        payload = _fold_assert_error(
            mcp_server.recovery_eval(record_path, ["doc.json"])
        )
        assert "record_path must be a nonempty single-line path" in (
            payload["error"]
        )

    @pytest.mark.parametrize(
        "evidence_paths",
        [
            [],
            "doc.json",
            None,
            ("doc.json",),
            [""],
            ["line\nbreak"],
            [7],
        ],
    )
    def test_invalid_evidence_paths_are_rejected(
        self, tmp_path, evidence_paths
    ) -> None:
        record = str(tmp_path / "record.json")
        payload = _fold_assert_error(
            mcp_server.recovery_eval(record, evidence_paths)
        )
        assert "evidence_paths" in payload["error"]

    def test_too_many_evidence_paths_are_rejected_before_reads(
        self, tmp_path
    ) -> None:
        paths = [str(tmp_path / f"{index}.json") for index in range(65)]
        payload = _fold_assert_error(
            mcp_server.recovery_eval(str(tmp_path / "record.json"), paths)
        )
        assert "maximum of 64" in payload["error"]
        assert str(tmp_path) not in payload["error"]

    def test_missing_evidence_path_is_redacted(self, tmp_path) -> None:
        record = _fold_write_json(
            tmp_path / "record.json", _fold_record(["claim_truth"])
        )
        missing = tmp_path / "missing-evidence.json"
        payload = _fold_assert_error(
            mcp_server.recovery_eval(str(record), [str(missing)])
        )
        assert str(tmp_path) not in payload["error"]

    @pytest.mark.parametrize(
        "body",
        [b" " * (1024 * 1024 + 1), b"[]", b"\xff"],
        ids=["oversized", "non-object", "invalid-utf8"],
    )
    def test_invalid_evidence_documents_fail_statically(
        self, tmp_path, body: bytes
    ) -> None:
        record = _fold_write_json(
            tmp_path / "record.json", _fold_record(["claim_truth"])
        )
        evidence = tmp_path / "bad-evidence.json"
        evidence.write_bytes(body)
        payload = _fold_assert_error(
            mcp_server.recovery_eval(str(record), [str(evidence)])
        )
        assert payload["status"] == "error"


class TestEvidenceFoldToolsDoNotSpawn:
    def test_all_four_routes_are_spawn_free(self, monkeypatch, tmp_path) -> None:
        def forbidden(*args, **kwargs):
            raise AssertionError("evidence fold MCP tools must not spawn")

        monkeypatch.setattr(subprocess, "Popen", forbidden)
        monkeypatch.setattr(subprocess, "run", forbidden)

        descriptor = _fold_write_json(
            tmp_path / "descriptor.json", _fold_acceptance_descriptor()
        )
        record_bytes = json.dumps(_fold_record(["claim_truth"])).encode()
        record = tmp_path / "record.json"
        record.write_bytes(record_bytes)
        evidence = _fold_write_json(
            tmp_path / "evidence.json",
            _fold_acceptance_evidence(record_bytes),
        )

        assert _fold_payload(
            mcp_server.evidence_acceptance_eval(str(descriptor))
        )["status"] == "ok"
        assert _fold_payload(
            mcp_server.freshness_eval(
                str(record), "2026-11-18T01:00:00Z", 7200
            )
        )["status"] == "ok"
        assert _fold_payload(
            mcp_server.binding_eval(str(record), str(evidence))
        )["status"] == "ok"
        assert _fold_payload(
            mcp_server.recovery_eval(str(record), [str(evidence)])
        )["status"] == "ok"


class TestMcpPayloadSerialization:
    def test_non_ascii_payload_remains_unescaped(self) -> None:
        raw = mcp_server._ok({"label": "日本語"})
        assert "日本語" in raw
        assert r"\u65e5" not in raw
        assert json.loads(raw)["label"] == "日本語"

    def test_error_payload_escapes_lone_surrogates(self) -> None:
        raw = mcp_server._err("\ud800")
        raw.encode("utf-8")
        assert json.loads(raw)["error"] == "\ud800"


class TestSignatureEvalTool:
    def test_envelope_and_declared_pins_match_cli(self, tmp_path):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_eval_fixtures._envelope(),
        )
        cases = (
            ([], {}),
            (
                [
                    "--expected-subject",
                    signature_eval_fixtures._SUBJECT,
                    "--expected-producer-key",
                    signature_eval_fixtures._KEY,
                ],
                {
                    "expected_subject": signature_eval_fixtures._SUBJECT,
                    "expected_producer_key": signature_eval_fixtures._KEY,
                },
            ),
        )
        for index, (options, tool_options) in enumerate(cases):
            cli = _signature_cli_payload(
                signature_eval_route.build_eval_parser,
                signature_eval_route.main_eval,
                ["--envelope", str(envelope), *options],
                tmp_path / f"eval-{index}.json",
            )
            payload = _fold_payload(
                mcp_server.signature_eval(str(envelope), **tool_options)
            )
            assert payload["status"] == "ok"
            assert payload["evaluation"] == cli
            assert "checks_not_performed" in payload["evaluation"]

    def test_revocation_list_observations_match_cli(self, tmp_path):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_eval_fixtures._envelope(),
        )
        for index, (revoked_keys, expected) in enumerate(
            ((["other-key"], True), ([signature_eval_fixtures._KEY], False))
        ):
            revocation_list = _fold_write_json(
                tmp_path / f"revocation-{index}.json",
                {
                    "schema_version": "mumei.key-revocation-list/v1",
                    "revoked_keys": revoked_keys,
                },
            )
            options = [
                "--envelope",
                str(envelope),
                "--revocation-list",
                str(revocation_list),
            ]
            cli = _signature_cli_payload(
                signature_eval_route.build_eval_parser,
                signature_eval_route.main_eval,
                options,
                tmp_path / f"revocation-eval-{index}.json",
            )
            payload = _fold_payload(
                mcp_server.signature_eval(
                    str(envelope), revocation_list_path=str(revocation_list)
                )
            )
            assert payload["evaluation"] == cli
            assert payload["evaluation"]["key_not_revoked"] is expected

    def test_registry_and_signature_wrappers_are_bound(self, tmp_path):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_eval_fixtures._envelope(),
        )
        registry = _fold_write_json(
            tmp_path / "registry.json",
            signature_eval_fixtures._registry_doc(),
        )
        revocation_list = _fold_write_json(
            tmp_path / "revocation.json",
            {
                "schema_version": "mumei.key-revocation-list/v1",
                "revoked_keys": ["other-key"],
            },
        )
        registry_digest = hashlib.sha256(registry.read_bytes()).hexdigest()
        revocation_digest = hashlib.sha256(
            revocation_list.read_bytes()
        ).hexdigest()
        registry_signature = _fold_write_json(
            tmp_path / "registry-signature.json",
            signature_eval_fixtures._anchor_signature(registry_digest),
        )
        revocation_signature = _fold_write_json(
            tmp_path / "revocation-signature.json",
            signature_eval_fixtures._anchor_signature(revocation_digest),
        )
        options = [
            "--envelope",
            str(envelope),
            "--key-registry",
            str(registry),
            "--reference-time",
            signature_eval_fixtures._REFERENCE,
            "--revocation-list",
            str(revocation_list),
            "--registry-signature",
            str(registry_signature),
            "--revocation-signature",
            str(revocation_signature),
        ]
        cli = _signature_cli_payload(
            signature_eval_route.build_eval_parser,
            signature_eval_route.main_eval,
            options,
            tmp_path / "signature-eval.json",
        )
        payload = _fold_payload(
            mcp_server.signature_eval(
                str(envelope),
                key_registry_path=str(registry),
                reference_time=signature_eval_fixtures._REFERENCE,
                revocation_list_path=str(revocation_list),
                registry_signature_path=str(registry_signature),
                revocation_signature_path=str(revocation_signature),
            )
        )
        assert payload["evaluation"] == cli
        assert payload["evaluation"]["registry_signature_bound"] is True
        assert payload["evaluation"]["revocation_signature_bound"] is True
        assert payload["evaluation"]["key_authentic"] is True

    @pytest.mark.parametrize(
        ("produced_at", "expected"),
        [
            ("2025-12-31T23:30:00Z", True),
            ("2025-12-31T22:00:00Z", False),
        ],
    )
    def test_fresh_and_stale_envelopes_match_cli(
        self, tmp_path, produced_at, expected
    ):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_eval_fixtures._envelope(produced_at=produced_at),
        )
        options = [
            "--envelope",
            str(envelope),
            "--reference-time",
            signature_eval_fixtures._REFERENCE,
            "--max-age-seconds",
            "3600",
        ]
        cli = _signature_cli_payload(
            signature_eval_route.build_eval_parser,
            signature_eval_route.main_eval,
            options,
            tmp_path / "freshness-eval.json",
        )
        payload = _fold_payload(
            mcp_server.signature_eval(
                str(envelope),
                reference_time=signature_eval_fixtures._REFERENCE,
                max_age_seconds=3600,
            )
        )
        assert payload["evaluation"] == cli
        assert payload["evaluation"]["envelope_fresh"] is expected

    def test_huge_max_age_returns_json_ok(self, tmp_path):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_eval_fixtures._envelope(
                produced_at="2026-01-01T00:00:00Z"
            ),
        )
        payload = _fold_payload(
            mcp_server.signature_eval(
                str(envelope),
                reference_time="2026-01-01T00:00:01Z",
                max_age_seconds=10**18,
            )
        )
        assert payload["status"] == "ok"
        assert payload["evaluation"]["envelope_fresh"] is True

    def test_requires_argument_errors_match_cli(self, tmp_path, capsys):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_eval_fixtures._envelope(),
        )
        registry = _fold_write_json(
            tmp_path / "registry.json",
            signature_eval_fixtures._registry_doc(),
        )
        revocation_signature = _fold_write_json(
            tmp_path / "revocation-signature.json",
            signature_eval_fixtures._anchor_signature("a" * 64),
        )
        cases = (
            (
                [
                    "--envelope",
                    str(envelope),
                    "--key-registry",
                    str(registry),
                ],
                lambda: mcp_server.signature_eval(
                    str(envelope), key_registry_path=str(registry)
                ),
            ),
            (
                [
                    "--envelope",
                    str(envelope),
                    "--registry-signature",
                    str(revocation_signature),
                ],
                lambda: mcp_server.signature_eval(
                    str(envelope),
                    registry_signature_path=str(revocation_signature),
                ),
            ),
            (
                [
                    "--envelope",
                    str(envelope),
                    "--revocation-signature",
                    str(revocation_signature),
                ],
                lambda: mcp_server.signature_eval(
                    str(envelope),
                    revocation_signature_path=str(revocation_signature),
                ),
            ),
        )
        for argv, tool_call in cases:
            cli_error = _signature_cli_error(
                signature_eval_route.build_eval_parser,
                signature_eval_route.main_eval,
                argv,
                capsys,
            )
            payload = _fold_assert_error(tool_call())
            assert payload["error"] == cli_error

    @pytest.mark.parametrize("bad_path", ["", "line\nbreak", 7])
    def test_invalid_paths_and_optional_values_are_rejected(
        self, tmp_path, bad_path
    ):
        envelope = str(tmp_path / "envelope.json")
        payload = _fold_assert_error(
            mcp_server.signature_eval(bad_path)
        )
        assert "envelope_path" in payload["error"]
        payload = _fold_assert_error(
            mcp_server.signature_eval(envelope, revocation_list_path=bad_path)
        )
        assert "revocation_list_path" in payload["error"]

    def test_missing_required_envelope_path_is_rejected(self):
        payload = _fold_assert_error(mcp_server.signature_eval(None))
        assert "envelope_path" in payload["error"]

    def test_non_string_optional_value_is_rejected(self, tmp_path):
        payload = _fold_assert_error(
            mcp_server.signature_eval(
                str(tmp_path / "envelope.json"), expected_subject=7
            )
        )
        assert payload["error"] == "expected_subject must be a string"

    def test_bad_max_age_is_rejected(self, tmp_path):
        envelope = str(tmp_path / "envelope.json")
        payload = _fold_assert_error(
            mcp_server.signature_eval(envelope, max_age_seconds=True)
        )
        assert payload["error"] == "max_age_seconds must be an integer"

    @pytest.mark.parametrize(
        "body",
        [b" " * (1024 * 1024 + 1), b"[]", b"\xff"],
        ids=["oversized", "non-object", "invalid-utf8"],
    )
    def test_invalid_envelope_documents_fail_statically(
        self, tmp_path, body
    ):
        envelope = tmp_path / "bad-envelope.json"
        envelope.write_bytes(body)
        payload = _fold_assert_error(
            mcp_server.signature_eval(str(envelope))
        )
        assert payload["status"] == "error"

    def test_missing_backslash_path_is_redacted(self, tmp_path):
        missing = tmp_path / "a\\b.json"
        payload = _fold_assert_error(
            mcp_server.signature_eval(str(missing))
        )
        assert str(tmp_path) not in payload["error"]
        assert repr(str(missing))[1:-1] not in payload["error"]


class TestSignatureVerifyTool:
    def test_good_tampered_and_wrong_key_signatures_match_cli(self, tmp_path):
        cases = (
            (
                signature_verify_fixtures._envelope(),
                signature_verify_fixtures._PUBLIC_KEY_HEX,
                True,
            ),
            (
                signature_verify_fixtures._envelope(signature="00" * 64),
                signature_verify_fixtures._PUBLIC_KEY_HEX,
                False,
            ),
            (
                signature_verify_fixtures._envelope(),
                signature_verify_fixtures._OTHER_PUBLIC_KEY_HEX,
                False,
            ),
        )
        for index, (document, public_key, expected) in enumerate(cases):
            envelope = _fold_write_json(
                tmp_path / f"envelope-{index}.json", document
            )
            options = [
                "--envelope",
                str(envelope),
                "--producer-key",
                public_key,
            ]
            cli = _signature_cli_payload(
                signature_verify_route.build_verify_parser,
                signature_verify_route.main_verify,
                options,
                tmp_path / f"verify-{index}.json",
            )
            payload = _fold_payload(
                mcp_server.signature_verify(str(envelope), public_key)
            )
            assert payload["status"] == "ok"
            assert payload["verification"] == cli
            assert payload["verification"]["signature_valid"] is expected

    def test_revocation_list_observations_match_cli(self, tmp_path):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_verify_fixtures._envelope(),
        )
        for index, (revoked_keys, expected) in enumerate(
            (
                (["other-key"], True),
                ([signature_verify_fixtures._KEY_ID], False),
            )
        ):
            revocation_list = _fold_write_json(
                tmp_path / f"revocation-{index}.json",
                {
                    "schema_version": "mumei.key-revocation-list/v1",
                    "revoked_keys": revoked_keys,
                },
            )
            options = [
                "--envelope",
                str(envelope),
                "--producer-key",
                signature_verify_fixtures._PUBLIC_KEY_HEX,
                "--revocation-list",
                str(revocation_list),
            ]
            cli = _signature_cli_payload(
                signature_verify_route.build_verify_parser,
                signature_verify_route.main_verify,
                options,
                tmp_path / f"revocation-verify-{index}.json",
            )
            payload = _fold_payload(
                mcp_server.signature_verify(
                    str(envelope),
                    signature_verify_fixtures._PUBLIC_KEY_HEX,
                    revocation_list_path=str(revocation_list),
                )
            )
            assert payload["verification"] == cli
            assert payload["verification"]["key_not_revoked"] is expected

    def test_expected_pins_revocation_and_registry_wrappers_match_cli(
        self, tmp_path
    ):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_verify_fixtures._envelope(),
        )
        registry = _fold_write_json(
            tmp_path / "registry.json",
            signature_verify_fixtures._registry_doc(),
        )
        revocation_list = _fold_write_json(
            tmp_path / "revocation.json",
            {
                "schema_version": "mumei.key-revocation-list/v1",
                "revoked_keys": ["other-key"],
            },
        )
        registry_digest = hashlib.sha256(registry.read_bytes()).hexdigest()
        revocation_digest = hashlib.sha256(
            revocation_list.read_bytes()
        ).hexdigest()
        registry_signature = _fold_write_json(
            tmp_path / "registry-signature.json",
            signature_verify_fixtures._anchor_signature(registry_digest),
        )
        revocation_signature = _fold_write_json(
            tmp_path / "revocation-signature.json",
            signature_verify_fixtures._anchor_signature(revocation_digest),
        )
        options = [
            "--envelope",
            str(envelope),
            "--producer-key",
            signature_verify_fixtures._PUBLIC_KEY_HEX,
            "--expected-subject",
            signature_verify_fixtures._SUBJECT,
            "--expected-producer-key",
            signature_verify_fixtures._KEY_ID,
            "--key-registry",
            str(registry),
            "--reference-time",
            signature_verify_fixtures._REFERENCE,
            "--registry-signature",
            str(registry_signature),
            "--registry-key",
            signature_verify_fixtures._ROOT_PUBLIC_KEY_HEX,
            "--revocation-list",
            str(revocation_list),
            "--revocation-signature",
            str(revocation_signature),
            "--revocation-key",
            signature_verify_fixtures._ROOT_PUBLIC_KEY_HEX,
        ]
        cli = _signature_cli_payload(
            signature_verify_route.build_verify_parser,
            signature_verify_route.main_verify,
            options,
            tmp_path / "verify-anchors.json",
        )
        payload = _fold_payload(
            mcp_server.signature_verify(
                str(envelope),
                signature_verify_fixtures._PUBLIC_KEY_HEX,
                expected_subject=signature_verify_fixtures._SUBJECT,
                expected_producer_key=signature_verify_fixtures._KEY_ID,
                key_registry_path=str(registry),
                reference_time=signature_verify_fixtures._REFERENCE,
                registry_signature_path=str(registry_signature),
                registry_key=signature_verify_fixtures._ROOT_PUBLIC_KEY_HEX,
                revocation_list_path=str(revocation_list),
                revocation_signature_path=str(revocation_signature),
                revocation_key=signature_verify_fixtures._ROOT_PUBLIC_KEY_HEX,
            )
        )
        assert payload["verification"] == cli
        assert payload["verification"]["subject_bound"] is True
        assert payload["verification"]["key_pinned"] is True
        assert payload["verification"]["registry_authentic"] is True
        assert payload["verification"]["revocation_list_authentic"] is True

    @pytest.mark.parametrize(
        ("produced_at", "expected"),
        [
            ("2025-12-31T23:30:00Z", True),
            ("2025-12-31T22:00:00Z", False),
        ],
    )
    def test_fresh_and_stale_signatures_match_cli(
        self, tmp_path, produced_at, expected
    ):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_verify_fixtures._envelope(produced_at=produced_at),
        )
        options = [
            "--envelope",
            str(envelope),
            "--producer-key",
            signature_verify_fixtures._PUBLIC_KEY_HEX,
            "--reference-time",
            signature_verify_fixtures._REFERENCE,
            "--max-age-seconds",
            "3600",
        ]
        cli = _signature_cli_payload(
            signature_verify_route.build_verify_parser,
            signature_verify_route.main_verify,
            options,
            tmp_path / "verify-freshness.json",
        )
        payload = _fold_payload(
            mcp_server.signature_verify(
                str(envelope),
                signature_verify_fixtures._PUBLIC_KEY_HEX,
                reference_time=signature_verify_fixtures._REFERENCE,
                max_age_seconds=3600,
            )
        )
        assert payload["verification"] == cli
        assert payload["verification"]["envelope_fresh"] is expected

    def test_requires_argument_errors_match_cli(self, tmp_path, capsys):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_verify_fixtures._envelope(),
        )
        registry = _fold_write_json(
            tmp_path / "registry.json",
            signature_verify_fixtures._registry_doc(),
        )
        wrapper = _fold_write_json(
            tmp_path / "wrapper.json",
            signature_verify_fixtures._anchor_signature("a" * 64),
        )
        revocation_list = _fold_write_json(
            tmp_path / "revocation.json",
            {
                "schema_version": "mumei.key-revocation-list/v1",
                "revoked_keys": [],
            },
        )
        base_cli = [
            "--envelope",
            str(envelope),
            "--producer-key",
            signature_verify_fixtures._PUBLIC_KEY_HEX,
        ]
        base_tool = (
            str(envelope),
            signature_verify_fixtures._PUBLIC_KEY_HEX,
        )
        cases = (
            (
                [*base_cli, "--key-registry", str(registry)],
                lambda: mcp_server.signature_verify(
                    *base_tool, key_registry_path=str(registry)
                ),
            ),
            (
                [
                    *base_cli,
                    "--key-registry",
                    str(registry),
                    "--reference-time",
                    signature_verify_fixtures._REFERENCE,
                    "--registry-signature",
                    str(wrapper),
                ],
                lambda: mcp_server.signature_verify(
                    *base_tool,
                    key_registry_path=str(registry),
                    reference_time=signature_verify_fixtures._REFERENCE,
                    registry_signature_path=str(wrapper),
                ),
            ),
            (
                [
                    *base_cli,
                    "--key-registry",
                    str(registry),
                    "--reference-time",
                    signature_verify_fixtures._REFERENCE,
                    "--registry-key",
                    signature_verify_fixtures._ROOT_PUBLIC_KEY_HEX,
                ],
                lambda: mcp_server.signature_verify(
                    *base_tool,
                    key_registry_path=str(registry),
                    reference_time=signature_verify_fixtures._REFERENCE,
                    registry_key=signature_verify_fixtures._ROOT_PUBLIC_KEY_HEX,
                ),
            ),
            (
                [*base_cli, "--registry-signature", str(wrapper)],
                lambda: mcp_server.signature_verify(
                    *base_tool, registry_signature_path=str(wrapper)
                ),
            ),
            (
                [
                    *base_cli,
                    "--revocation-list",
                    str(revocation_list),
                    "--revocation-signature",
                    str(wrapper),
                ],
                lambda: mcp_server.signature_verify(
                    *base_tool,
                    revocation_list_path=str(revocation_list),
                    revocation_signature_path=str(wrapper),
                ),
            ),
            (
                [
                    *base_cli,
                    "--revocation-list",
                    str(revocation_list),
                    "--revocation-key",
                    signature_verify_fixtures._ROOT_PUBLIC_KEY_HEX,
                ],
                lambda: mcp_server.signature_verify(
                    *base_tool,
                    revocation_list_path=str(revocation_list),
                    revocation_key=signature_verify_fixtures._ROOT_PUBLIC_KEY_HEX,
                ),
            ),
        )
        for argv, tool_call in cases:
            cli_error = _signature_cli_error(
                signature_verify_route.build_verify_parser,
                signature_verify_route.main_verify,
                argv,
                capsys,
            )
            payload = _fold_assert_error(tool_call())
            assert payload["error"] == cli_error

    @pytest.mark.parametrize("bad_path", ["", "line\nbreak", 7])
    def test_invalid_paths_and_optional_values_are_rejected(
        self, tmp_path, bad_path
    ):
        envelope = str(tmp_path / "envelope.json")
        public_key = signature_verify_fixtures._PUBLIC_KEY_HEX
        payload = _fold_assert_error(
            mcp_server.signature_verify(bad_path, public_key)
        )
        assert "envelope_path" in payload["error"]
        payload = _fold_assert_error(
            mcp_server.signature_verify(
                envelope, public_key, key_registry_path=bad_path
            )
        )
        assert "key_registry_path" in payload["error"]

    def test_missing_required_arguments_are_rejected(self):
        payload = _fold_assert_error(
            mcp_server.signature_verify("envelope.json", None)
        )
        assert payload["error"] == "producer_key must be a string"

    def test_non_string_optional_value_is_rejected(self, tmp_path):
        payload = _fold_assert_error(
            mcp_server.signature_verify(
                str(tmp_path / "envelope.json"),
                signature_verify_fixtures._PUBLIC_KEY_HEX,
                reference_time=7,
            )
        )
        assert payload["error"] == "reference_time must be a string"

    def test_bad_hex_key_is_rejected_without_echo(self, tmp_path):
        envelope = _fold_write_json(
            tmp_path / "envelope.json",
            signature_verify_fixtures._envelope(),
        )
        public_key = "not-a-public-key"
        payload = _fold_assert_error(
            mcp_server.signature_verify(str(envelope), public_key)
        )
        assert payload["error"] == "invalid producer key"
        assert public_key not in payload["error"]

    @pytest.mark.parametrize(
        "body",
        [b" " * (1024 * 1024 + 1), b"[]", b"\xff"],
        ids=["oversized", "non-object", "invalid-utf8"],
    )
    def test_invalid_envelope_documents_fail_statically(
        self, tmp_path, body
    ):
        envelope = tmp_path / "bad-envelope.json"
        envelope.write_bytes(body)
        payload = _fold_assert_error(
            mcp_server.signature_verify(
                str(envelope), signature_verify_fixtures._PUBLIC_KEY_HEX
            )
        )
        assert payload["status"] == "error"

    def test_missing_backslash_path_is_redacted(self, tmp_path):
        missing = tmp_path / "a\\b.json"
        payload = _fold_assert_error(
            mcp_server.signature_verify(
                str(missing), signature_verify_fixtures._PUBLIC_KEY_HEX
            )
        )
        assert str(tmp_path) not in payload["error"]
        assert repr(str(missing))[1:-1] not in payload["error"]


class TestSignatureMaxAgeDispatch:
    @pytest.mark.parametrize("tool_name", ["signature_eval", "signature_verify"])
    @pytest.mark.parametrize("max_age", [True, "3600"])
    def test_dispatch_rejects_coerced_max_age_values(
        self, tmp_path, tool_name, max_age
    ):
        envelope = _fold_write_json(
            tmp_path / f"{tool_name}-{max_age}.json",
            signature_eval_fixtures._envelope(),
        )
        arguments = {
            "envelope_path": str(envelope),
            "reference_time": signature_eval_fixtures._REFERENCE,
            "max_age_seconds": max_age,
        }
        if tool_name == "signature_verify":
            arguments["producer_key"] = signature_verify_fixtures._PUBLIC_KEY_HEX
        with pytest.raises(ToolError):
            asyncio.run(mcp_server.mcp.call_tool(tool_name, arguments))

    @pytest.mark.parametrize("tool_name", ["signature_eval", "signature_verify"])
    def test_dispatch_accepts_strict_integer_max_age(
        self, tmp_path, tool_name
    ):
        envelope = _fold_write_json(
            tmp_path / f"{tool_name}.json",
            signature_eval_fixtures._envelope(
                produced_at="2025-12-31T23:30:00Z"
            ),
        )
        arguments = {
            "envelope_path": str(envelope),
            "reference_time": signature_eval_fixtures._REFERENCE,
            "max_age_seconds": 3600,
        }
        response_key = "evaluation"
        if tool_name == "signature_verify":
            arguments["producer_key"] = signature_verify_fixtures._PUBLIC_KEY_HEX
            response_key = "verification"
        content = asyncio.run(
            mcp_server.mcp.call_tool(tool_name, arguments)
        )
        payload = _fold_payload(content[0][0].text)
        assert payload["status"] == "ok"
        assert payload[response_key]["envelope_fresh"] is True


class TestSignatureToolsDoNotSpawn:
    def test_eval_and_verify_are_spawn_free(self, monkeypatch, tmp_path):
        def forbidden(*args, **kwargs):
            raise AssertionError("signature MCP tools must not spawn")

        monkeypatch.setattr(subprocess, "Popen", forbidden)
        monkeypatch.setattr(subprocess, "run", forbidden)

        eval_envelope = _fold_write_json(
            tmp_path / "eval-envelope.json",
            signature_eval_fixtures._envelope(),
        )
        verify_envelope = _fold_write_json(
            tmp_path / "verify-envelope.json",
            signature_verify_fixtures._envelope(),
        )
        assert _fold_payload(
            mcp_server.signature_eval(str(eval_envelope))
        )["status"] == "ok"
        assert _fold_payload(
            mcp_server.signature_verify(
                str(verify_envelope),
                signature_verify_fixtures._PUBLIC_KEY_HEX,
            )
        )["status"] == "ok"


class TestNulDeclaredPaths:
    def test_signature_and_binding_tools_reject_nul_paths(self) -> None:
        results = (
            (
                mcp_server.signature_eval("envelope\x00.json"),
                "envelope_path",
            ),
            (
                mcp_server.signature_verify(
                    "envelope\x00.json",
                    signature_verify_fixtures._PUBLIC_KEY_HEX,
                ),
                "envelope_path",
            ),
            (
                mcp_server.binding_eval("record\x00.json", "evidence.json"),
                "record_path",
            ),
        )
        for raw, name in results:
            payload = _fold_assert_error(raw)
            assert (
                f"{name} must be a nonempty single-line path"
                in payload["error"]
            )
        assert (
            mcp_server._redact_declared_paths("unchanged", ["a\x00b"])
            == "unchanged"
        )
