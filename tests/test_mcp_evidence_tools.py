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
        f'    printf \'%s\' \'{json.dumps(diagnostic)}\'\n'
        "    exit 0\n"
        'elif [ "$1" = "evidence" ] && [ "$2" = "recheck-source" ]; then\n'
        f'    printf \'%s\' \'{{"schema_version":"mumei.evidence-consistency/v1"}}\'\n'
        f'    exit {exits.get("recheck-source", 0)}\n'
        'elif [ "$1" = "native-bundle" ] && [ "$2" = "recheck-llvm" ]; then\n'
        f'    printf \'%s\' \'{{"schema_version":"mumei.native-consumer-evidence/v1"}}\'\n'
        f'    exit {exits.get("recheck-llvm", 0)}\n'
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
        record.write_text('{"schema_version": "mumei.native-bundle/v1"}', encoding="utf-8")
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
                          build_id: str = "c" * 64, build_exit: int = 0):
        names = ("native-bundle.json", "program.ll", "program.o",
                 "proof-cert.json", "program")
        members = "\n".join(
            f'    printf %s "{n}-bytes" > "$out/{n}"'
            for n in (names if complete else names[:-1])
        )
        core = tmp_path / "mumei-stub"
        core.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "native-bundle" ] && [ "$2" = "build" ]; then\n'
            '    out="$5"\n'
            "    mkdir -p \"$out\"\n"
            f"{members}\n"
            f'    printf "Build ID: {build_id}\\n"\n'
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
        assert report["build_id"] == "c" * 64
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
