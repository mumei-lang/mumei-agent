"""Tests for the unperformed-check recovery fold and route (#897)."""

import argparse
import hashlib
import json

import pytest

from agent.core_evidence import (
    UNPERFORMED_CHECK_RECOVERY_SCHEMA,
    evaluate_unperformed_check_recovery,
)
from agent.recovery_eval import build_eval_parser, main_eval


def _record(*checks):
    return {"schema_version": "mumei.any/v1",
            "checks_not_performed": list(checks)}


def _doc(schema, **fields):
    doc = {"schema_version": schema}
    doc.update(fields)
    return doc


def test_recovery_statuses():
    record = _record(
        "signature_verification",
        "key_authenticity",
        "freshness",
    )
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [
            _doc("mumei.signature-verification/v1", signature_valid=True),
            _doc("mumei.freshness-evaluation/v1", within_window=False),
        ],
    )
    assert evaluation["schema_version"] == UNPERFORMED_CHECK_RECOVERY_SCHEMA
    assert evaluation["checks_declared"] is True
    assert evaluation["checks"] == {
        "signature_verification": "recovered",
        "key_authenticity": "no_evidence",
        "freshness": "evidence_failed",
    }
    assert evaluation["recovered"] == ["signature_verification"]
    assert evaluation["unrecovered"] == ["key_authenticity", "freshness"]
    assert evaluation["checks_not_performed"] == [
        "evidence_binding",
        "evidence_authenticity",
        "recovery_enforcement",
    ]


def test_multi_performer_check_accepts_either_schema():
    record = _record("subject_binding")
    for schema in (
        "mumei.signature-envelope-evaluation/v1",
        "mumei.signature-verification/v1",
    ):
        evaluation = evaluate_unperformed_check_recovery(
            record, [_doc(schema, subject_bound=True)]
        )
        assert evaluation["checks"]["subject_binding"] == "recovered"


def test_outcome_field_must_be_true():
    record = _record("signature_verification")
    for outcome in (False, None, "true", 1):
        evaluation = evaluate_unperformed_check_recovery(
            record,
            [_doc("mumei.signature-verification/v1",
                  signature_valid=outcome)],
        )
        assert evaluation["checks"]["signature_verification"] == (
            "evidence_failed"
        )
    # matching schema, field absent entirely
    evaluation = evaluate_unperformed_check_recovery(
        record, [_doc("mumei.signature-verification/v1")]
    )
    assert evaluation["checks"]["signature_verification"] == (
        "evidence_failed"
    )


def _recheck_doc(fingerprint, recheck="consistent"):
    return _doc(
        "mumei.source-evidence-recheck/v1",
        evidence_fingerprint=fingerprint,
        recheck=recheck,
    )


def _accept_doc(schema, fingerprint):
    return _doc(
        schema,
        evidence_fingerprint=fingerprint,
        accepted=True,
    )


def test_bound_core_docs_recover_semantic_checks():
    record_bytes = b'{"record": true}'
    digest = hashlib.sha256(record_bytes).hexdigest()
    record = _record(
        "claim_truth",
        "freshness",
        "semantic_correspondence",
        "artifact_semantics",
    )
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [
            _recheck_doc(digest),
            _accept_doc("mumei.native-evidence-acceptance/v1", digest),
        ],
        record_digest=digest,
    )
    assert evaluation["checks"] == {
        "claim_truth": "recovered",
        "freshness": "recovered",
        "semantic_correspondence": "recovered",
        "artifact_semantics": "recovered",
    }


def test_source_acceptance_recovers_the_same_three():
    digest = "a" * 64
    record = _record(
        "claim_truth", "freshness", "semantic_correspondence",
        "artifact_semantics",
    )
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_accept_doc("mumei.source-evidence-acceptance/v1", digest)],
        record_digest=digest,
    )
    assert evaluation["checks"] == {
        "claim_truth": "recovered",
        "freshness": "recovered",
        "semantic_correspondence": "recovered",
        # the compiled-artifact layer needs the native descriptor
        "artifact_semantics": "no_evidence",
    }


def test_core_docs_only_count_for_the_bound_record():
    record = _record("claim_truth", "semantic_correspondence")
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_recheck_doc("b" * 64)],
        record_digest="a" * 64,
    )
    assert evaluation["checks"] == {
        "claim_truth": "evidence_failed",
        "semantic_correspondence": "evidence_failed",
    }


def test_core_docs_need_the_claimed_outcome():
    digest = "a" * 64
    record = _record("claim_truth")
    for recheck in ("inconclusive", None, True):
        evaluation = evaluate_unperformed_check_recovery(
            record,
            [_recheck_doc(digest, recheck=recheck)],
            record_digest=digest,
        )
        assert evaluation["checks"]["claim_truth"] == "evidence_failed"
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_doc("mumei.native-evidence-acceptance/v1",
              evidence_fingerprint=digest, accepted=False)],
        record_digest=digest,
    )
    assert evaluation["checks"]["claim_truth"] == "evidence_failed"


def test_core_docs_cannot_be_attributed_without_record_digest():
    record = _record("claim_truth")
    evaluation = evaluate_unperformed_check_recovery(
        record, [_recheck_doc("a" * 64)]
    )
    assert evaluation["checks"]["claim_truth"] == "evidence_failed"
    evaluation = evaluate_unperformed_check_recovery(record, [])
    assert evaluation["checks"]["claim_truth"] == "no_evidence"


def test_anonymous_native_acceptance_applies_to_nothing():
    # Artifact acceptance with no record input carries no
    # evidence_fingerprint, so it can never be attributed.
    record = _record("artifact_semantics")
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_doc("mumei.native-evidence-acceptance/v1", accepted=True)],
        record_digest="a" * 64,
    )
    assert evaluation["checks"]["artifact_semantics"] == "evidence_failed"


def test_foreign_schema_never_counts():
    record = _record("signature_verification")
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [
            _doc("mumei.forged-verification/v1", signature_valid=True),
            _doc("mumei.signature-verification/v2", signature_valid=True),
        ],
    )
    assert evaluation["checks"]["signature_verification"] == "no_evidence"


def test_unknown_check_names_report_no_evidence():
    evaluation = evaluate_unperformed_check_recovery(
        _record("key_revocation", "producer_authenticity"), []
    )
    assert evaluation["checks"] == {
        "key_revocation": "no_evidence",
        "producer_authenticity": "no_evidence",
    }


def test_missing_or_malformed_declaration():
    for record in (
        {},
        {"checks_not_performed": "signature_verification"},
        {"checks_not_performed": None},
        {"checks_not_performed": 7},
    ):
        evaluation = evaluate_unperformed_check_recovery(record, [])
        assert evaluation["checks_declared"] is False
        assert evaluation["checks"] == {}
        assert evaluation["recovered"] == []
    # non-string entries inside the list are skipped
    evaluation = evaluate_unperformed_check_recovery(
        {"checks_not_performed": ["signature_verification", 7, None, {}]},
        [_doc("mumei.signature-verification/v1", signature_valid=True)],
    )
    assert evaluation["checks"] == {
        "signature_verification": "recovered"
    }


def test_rejects_non_dict_inputs():
    with pytest.raises(ValueError):
        evaluate_unperformed_check_recovery([], [])
    with pytest.raises(ValueError):
        evaluate_unperformed_check_recovery(
            _record("signature_verification"), [["not-a-dict"]]
        )


def _write(path, payload):
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )
    return str(path)


def _args(parser, record, evidence, output=None):
    argv = ["--record", record]
    for doc in evidence:
        argv += ["--evidence", doc]
    if output is not None:
        argv += ["--output", output]
    return parser.parse_args(argv)


def test_route_emits_recovery(tmp_path):
    record = _write(
        tmp_path / "record.json", _record("signature_verification")
    )
    evidence = _write(
        tmp_path / "verify.json",
        _doc("mumei.signature-verification/v1", signature_valid=True),
    )
    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    assert main_eval(_args(parser, record, [evidence])) == 0


def test_route_static_failures(tmp_path):
    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    record = _write(tmp_path / "record.json", _record("signature_verification"))
    evidence = _write(
        tmp_path / "verify.json",
        _doc("mumei.signature-verification/v1", signature_valid=True),
    )
    # missing file
    assert main_eval(
        _args(parser, str(tmp_path / "none.json"), [evidence])
    ) == 1
    # malformed JSON
    bad = _write(tmp_path / "bad.json", "{not json")
    assert main_eval(_args(parser, bad, [evidence])) == 1
    # non-object record and non-object evidence
    nonobj = _write(tmp_path / "list.json", "[1]")
    assert main_eval(_args(parser, nonobj, [evidence])) == 1
    assert main_eval(_args(parser, record, [nonobj])) == 1
    # output may not overwrite any declared input
    assert main_eval(
        _args(parser, record, [evidence], output=record)
    ) == 1
    assert main_eval(
        _args(parser, record, [evidence], output=evidence)
    ) == 1
