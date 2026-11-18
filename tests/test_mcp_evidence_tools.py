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
