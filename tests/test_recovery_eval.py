"""Tests for the unperformed-check recovery fold and route (#897)."""

import argparse
import hashlib
import json

import pytest

from agent.core_evidence import (
    _CHECK_PERFORMERS,
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
        # A signature-verification doc is now a `key_authenticity`
        # performer (it may carry `key_authentic`); supplied without
        # the field it is ambiguous evidence — the established
        # evidence_failed convention, not no_evidence.
        "key_authenticity": "evidence_failed",
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


def test_descriptor_record_recovers_through_declared_carrier():
    # A Core acceptance descriptor declares its own
    # checks_not_performed AND the evidence digest it evaluated; a
    # recheck doc bound to the same evidence recovers its declared
    # checks even though the descriptor's own bytes differ.
    evidence_digest = "a" * 64
    record = _doc(
        "mumei.source-evidence-acceptance/v1",
        evidence_fingerprint=evidence_digest,
        accepted=True,
        checks_not_performed=[
            "claim_truth", "semantic_correspondence",
            "artifact_semantics", "llvm_correspondence",
        ],
    )
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [
            _recheck_doc(evidence_digest),
            _accept_doc("mumei.native-evidence-acceptance/v1",
                        evidence_digest),
        ],
        # the descriptor's own byte digest is different — bound docs
        # still match its declared carrier
        record_digest="c" * 64,
    )
    assert evaluation["checks"] == {
        "claim_truth": "recovered",
        "semantic_correspondence": "recovered",
        "artifact_semantics": "recovered",
        "llvm_correspondence": "no_evidence",
    }


def test_declared_carrier_only_binds_that_artifact():
    record = _doc(
        "mumei.source-evidence-acceptance/v1",
        evidence_fingerprint="a" * 64,
        checks_not_performed=["claim_truth"],
    )
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_recheck_doc("b" * 64)],
        record_digest="b" * 64,
    )
    # the doc binds the descriptor's byte digest but NOT its declared
    # carrier — the declared carrier names the artifact, so it wins
    assert evaluation["checks"]["claim_truth"] == "evidence_failed"


def _attempt_report(
    record_digest,
    accepted=True,
    schema="mumei.verify-attempt-report/v1",
):
    """A minimal realistic verify-attempt report.

    `record_digest` is the produced bytes' SHA-256, surfaced at
    `normalized.stdout.sha256`; `candidate.output_fingerprint` stays a
    DISTINCT verifier-output-manifest fingerprint — the fold binds the
    record through the normalized bytes, never the manifest hash.
    """
    manifest_fingerprint = "f" * 64
    return _doc(
        schema,
        sequence={
            "schema_version": "mumei.verifier-attempt-sequence/v1",
            "request_fingerprint": "e" * 64,
            "timeout_ms": 30000,
            "attempts": [
                {
                    "request_fingerprint": "e" * 64,
                    "attempt_number": 1,
                    "state": "exited",
                }
            ],
            "selected_result": {
                "attempt_number": 1,
                "output_fingerprint": manifest_fingerprint,
            },
        },
        normalized={
            "schema_version": "mumei.verifier-run-result/v1",
            "request_fingerprint": "e" * 64,
            "attempt_number": 1,
            "outcome": "exited",
            "stdout": {"sha256": record_digest, "size_bytes": 2},
        },
        candidate={
            "schema_version": "mumei.verifier-evidence-candidate/v1",
            "output_fingerprint": manifest_fingerprint,
        },
        acceptance={"accepted": accepted},
    )


def test_attempt_report_recovers_five_checks():
    digest = "a" * 64
    record = _record(
        "file_identity", "producer_authenticity", "freshness",
        "semantic_correspondence", "claim_truth", "artifact_semantics",
    )
    evaluation = evaluate_unperformed_check_recovery(
        record, [_attempt_report(digest)], record_digest=digest,
    )
    assert evaluation["checks"] == {
        "file_identity": "recovered",
        "producer_authenticity": "recovered",
        "freshness": "recovered",
        "semantic_correspondence": "recovered",
        "claim_truth": "recovered",
        # the artifact layer needs the native descriptor
        "artifact_semantics": "no_evidence",
    }


def test_attempt_report_recovers_historical_execution():
    digest = "a" * 64
    record = _record("historical_execution")
    evaluation = evaluate_unperformed_check_recovery(
        record, [_attempt_report(digest)], record_digest=digest,
    )
    assert evaluation["checks"]["historical_execution"] == "recovered"


def _signature_verification_doc(
    record_digest,
    signature_valid=True,
    key_pinned=True,
):
    """A signature-verification doc bound to *record_digest* — the
    shape `signature-verify` emits since the doc carries the
    envelope's `subject_digest` carrier."""
    return _doc(
        "mumei.signature-verification/v1",
        envelope_match=True,
        signature_valid=signature_valid,
        key_pinned=key_pinned,
        subject_digest=record_digest,
    )


def test_pinned_signature_verification_recovers_producer_authenticity():
    digest = "a" * 64
    record = _record("producer_authenticity")
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_signature_verification_doc(digest)],
        record_digest=digest,
    )
    assert evaluation["checks"]["producer_authenticity"] == "recovered"

    # A record declaring a carrier binds through the same digest.
    descriptor_record = {
        "schema_version": "mumei.any/v1",
        "checks_not_performed": ["producer_authenticity"],
        "evidence_fingerprint": digest,
    }
    evaluation = evaluate_unperformed_check_recovery(
        descriptor_record, [_signature_verification_doc(digest)],
    )
    assert evaluation["checks"]["producer_authenticity"] == "recovered"


def test_producer_authenticity_needs_signature_and_key_pin_and_binding():
    digest = "a" * 64
    record = _record("producer_authenticity")

    # A valid signature under an UNPINNED key only proves somebody
    # signed — it never performs producer_authenticity.
    for doc in (
        _signature_verification_doc(digest, key_pinned=False),
        _doc(
            "mumei.signature-verification/v1",
            envelope_match=True,
            signature_valid=True,
            subject_digest=digest,
        ),
    ):
        evaluation = evaluate_unperformed_check_recovery(
            record, [doc], record_digest=digest,
        )
        assert evaluation["checks"]["producer_authenticity"] == (
            "evidence_failed"
        )

    # A pinned key whose signature failed counts for nothing.
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_signature_verification_doc(digest, signature_valid=False)],
        record_digest=digest,
    )
    assert evaluation["checks"]["producer_authenticity"] == (
        "evidence_failed"
    )

    # A doc bound to other bytes can never recover this record — the
    # subject_digest carrier must name this record's digest. The
    # performer schema was supplied, so the fold reports the failed
    # evidence rather than no evidence.
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_signature_verification_doc("b" * 64)],
        record_digest=digest,
    )
    assert evaluation["checks"]["producer_authenticity"] == (
        "evidence_failed"
    )

    # Undeclared records recover only through bound documents — and a
    # bound verification doc scopes itself by the carrier.
    evaluation = evaluate_unperformed_check_recovery(
        {"any": "manifest"},
        [_signature_verification_doc(digest)],
        record_digest=digest,
    )
    assert evaluation["checks"]["producer_authenticity"] == "recovered"


def test_real_attempt_report_recovers_produced_record(tmp_path, capsys):
    """The fold binds a REAL verify-attempt report's declared digests.

    Runs the route against a stub Core so the report shape — where the
    produced bytes' digest lands — is exercised end to end rather than
    handwritten."""
    from tests.test_verify_attempt import (
        EVIDENCE,
        _args,
        _run,
        _write_core,
        _write_source,
    )

    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["acceptance"]["accepted"] is True

    # The produced record is the run's stdout bytes verbatim.
    record_bytes = json.dumps(EVIDENCE).encode()
    record_digest = hashlib.sha256(record_bytes).hexdigest()
    assert report["normalized"]["stdout"]["sha256"] == record_digest

    record = _record(
        "file_identity", "producer_authenticity", "freshness",
        "semantic_correspondence", "claim_truth",
        "historical_execution",
    )
    evaluation = evaluate_unperformed_check_recovery(
        record, [report], record_digest=record_digest,
    )
    assert evaluation["checks"] == {
        "file_identity": "recovered",
        "producer_authenticity": "recovered",
        "freshness": "recovered",
        "semantic_correspondence": "recovered",
        "claim_truth": "recovered",
        "historical_execution": "recovered",
    }


def test_go_summaries_attempt_report_recovers_manifest_checks():
    """An accepted go-summaries attempt report discharges the same
    five checks plus historical_execution on the manifest bytes its
    selected run produced."""
    digest = "a" * 64
    record = _record(
        "file_identity", "producer_authenticity", "freshness",
        "semantic_correspondence", "claim_truth", "artifact_semantics",
        "historical_execution",
    )
    report = _attempt_report(
        digest, schema="mumei.go-summaries-attempt-report/v1"
    )
    evaluation = evaluate_unperformed_check_recovery(
        record, [report], record_digest=digest,
    )
    checks = evaluation["checks"]
    for name in (
        "file_identity",
        "producer_authenticity",
        "freshness",
        "historical_execution",
    ):
        assert checks[name] == "recovered", name
    # Parsing never verifies the manifest's dep claims
    assert checks["claim_truth"] == "no_evidence"
    assert checks["semantic_correspondence"] == "no_evidence"
    assert checks["artifact_semantics"] == "no_evidence"


@pytest.mark.parametrize(
    "schema",
    [
        "mumei.ts-summaries-attempt-report/v1",
        "mumei.sol-summaries-attempt-report/v1",
        "mumei.rust-summaries-attempt-report/v1",
    ],
)
def test_summaries_attempt_reports_recover_manifest_checks(schema):
    """An accepted ts/sol/rust summaries attempt report discharges the
    same checks plus historical_execution on the manifest bytes its
    selected run produced."""
    digest = "a" * 64
    record = _record(
        "file_identity", "producer_authenticity", "freshness",
        "semantic_correspondence", "claim_truth", "artifact_semantics",
        "historical_execution",
    )
    evaluation = evaluate_unperformed_check_recovery(
        record, [_attempt_report(digest, schema=schema)],
        record_digest=digest,
    )
    checks = evaluation["checks"]
    for name in (
        "file_identity",
        "producer_authenticity",
        "freshness",
        "historical_execution",
    ):
        assert checks[name] == "recovered", (schema, name)
    # Parsing never verifies the manifest's dep claims
    assert checks["claim_truth"] == "no_evidence"
    assert checks["semantic_correspondence"] == "no_evidence"
    assert checks["artifact_semantics"] == "no_evidence"


def test_attempt_report_requires_accepted_and_bound():
    digest = "a" * 64
    record = _record("file_identity", "claim_truth")
    # not accepted
    evaluation = evaluate_unperformed_check_recovery(
        record, [_attempt_report(digest, accepted=False)],
        record_digest=digest,
    )
    assert evaluation["checks"]["file_identity"] == "evidence_failed"
    assert evaluation["checks"]["claim_truth"] == "evidence_failed"
    # accepted but bound to a different record
    evaluation = evaluate_unperformed_check_recovery(
        record, [_attempt_report("b" * 64)], record_digest=digest,
    )
    assert evaluation["checks"]["file_identity"] == "evidence_failed"
    # no candidate at all
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_doc("mumei.verify-attempt-report/v1",
              acceptance={"accepted": True})],
        record_digest=digest,
    )
    assert evaluation["checks"]["file_identity"] == "evidence_failed"


def test_record_freshness_recovers_via_freshness_eval():
    record = _record("record_freshness")
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_doc("mumei.freshness-evaluation/v1", within_window=True)],
    )
    assert evaluation["checks"]["record_freshness"] == "recovered"
    evaluation = evaluate_unperformed_check_recovery(
        record,
        [_doc("mumei.freshness-evaluation/v1", within_window=False)],
    )
    assert evaluation["checks"]["record_freshness"] == "evidence_failed"


def test_evidence_binding_pins_record_bytes_not_declared_carrier():
    # A descriptor record declares `subject_digest` for the artifact it
    # signs; a binding doc still evaluates THIS record's bytes.
    artifact_digest = "b" * 64
    record_digest = "c" * 64
    record = _record("evidence_binding")
    record["subject_digest"] = artifact_digest
    bound_to_record = _doc(
        "mumei.evidence-binding/v1", bound=True, record_digest=record_digest
    )
    bound_to_artifact = _doc(
        "mumei.evidence-binding/v1",
        bound=True,
        record_digest=artifact_digest,
    )
    evaluation = evaluate_unperformed_check_recovery(
        record, [bound_to_record], record_digest=record_digest
    )
    assert evaluation["checks"]["evidence_binding"] == "recovered"
    # A doc bound to the referred artifact is not a binding of THIS
    # record.
    evaluation = evaluate_unperformed_check_recovery(
        record, [bound_to_artifact], record_digest=record_digest
    )
    assert evaluation["checks"]["evidence_binding"] == "evidence_failed"


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
        # undeclared records fold over every known check
        assert set(evaluation["checks"]) == set(_CHECK_PERFORMERS)
        assert evaluation["recovered"] == []
    # non-string entries inside the list are skipped
    evaluation = evaluate_unperformed_check_recovery(
        {"checks_not_performed": ["signature_verification", 7, None, {}]},
        [_doc("mumei.signature-verification/v1", signature_valid=True)],
    )
    assert evaluation["checks"] == {
        "signature_verification": "recovered"
    }


def test_undeclared_record_requires_bound_documents():
    """Record-agnostic performers can only count against the
    record's own declared list: a signature-verification doc for
    some other artifact must not recover an undeclared record."""
    evaluation = evaluate_unperformed_check_recovery(
        {"any": "manifest"},
        [_doc("mumei.signature-verification/v1", signature_valid=True)],
        record_digest="a" * 64,
    )
    assert evaluation["checks_declared"] is False
    assert evaluation["checks"]["signature_verification"] == "no_evidence"
    assert evaluation["recovered"] == []
    # A bound attempt report still recovers the undeclared record.
    digest = "b" * 64
    report = _attempt_report(
        digest, schema="mumei.go-summaries-attempt-report/v1"
    )
    evaluation = evaluate_unperformed_check_recovery(
        {"any": "manifest"}, [report], record_digest=digest,
    )
    assert evaluation["checks"]["file_identity"] == "recovered"
    assert evaluation["checks"]["historical_execution"] == "recovered"
    assert evaluation["checks"]["signature_verification"] == "no_evidence"


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


def test_key_revocation_recovers_through_bound_fold_docs():
    digest = "a" * 64
    record = _record("key_revocation")
    for schema in (
        "mumei.signature-envelope-evaluation/v1",
        "mumei.signature-verification/v1",
    ):
        doc = _doc(
            schema,
            envelope_match=True,
            key_not_revoked=True,
            subject_digest=digest,
        )
        evaluation = evaluate_unperformed_check_recovery(
            record, [doc], record_digest=digest,
        )
        assert evaluation["checks"]["key_revocation"] == "recovered"


def test_key_revocation_needs_binding_and_outcome():
    digest = "a" * 64
    record = _record("key_revocation")

    # A revoked key reports evidence_failed, not recovered.
    doc = _doc(
        "mumei.signature-verification/v1",
        envelope_match=True,
        key_not_revoked=False,
        subject_digest=digest,
    )
    evaluation = evaluate_unperformed_check_recovery(
        record, [doc], record_digest=digest,
    )
    assert evaluation["checks"]["key_revocation"] == "evidence_failed"

    # A doc bound to other bytes never performs this record's check.
    doc = _doc(
        "mumei.signature-verification/v1",
        envelope_match=True,
        key_not_revoked=True,
        subject_digest="b" * 64,
    )
    evaluation = evaluate_unperformed_check_recovery(
        record, [doc], record_digest=digest,
    )
    assert evaluation["checks"]["key_revocation"] == "evidence_failed"

    # The record-agnostic freshness convention does NOT apply — a
    # bound doc is required even when the record declares its checks.
    doc = _doc(
        "mumei.signature-envelope-evaluation/v1",
        envelope_match=True,
        key_not_revoked=True,
    )
    evaluation = evaluate_unperformed_check_recovery(
        record, [doc], record_digest=digest,
    )
    assert evaluation["checks"]["key_revocation"] == "evidence_failed"


def test_conflicting_bound_revocation_docs_stay_evidence_failed():
    # Two envelopes sign the same record — one by a revoked key, one
    # by a clean key. Both eval docs bind the record's subject digest;
    # a `key_not_revoked: false` observation must not be masked by a
    # `true` from a different key.
    from agent.core_evidence import (
        evaluate_signature_envelope,
        evaluate_unperformed_check_recovery,
        revocation_key_set,
    )

    revoked_list = revocation_key_set(
        {"schema_version": "mumei.key-revocation-list/v1",
         "revoked_keys": ["revoked-key"]}
    )
    base = {
        "schema_version": "mumei.producer-signature/v1",
        "subject_digest": "a" * 64,
        "algorithm": "ed25519",
        "signature": "00" * 64,
        "producer_key_id": "revoked-key",
    }
    bad = evaluate_signature_envelope(dict(base), revoked_keys=revoked_list)
    good = evaluate_signature_envelope(
        dict(base, producer_key_id="clean-key"), revoked_keys=revoked_list,
    )
    record = {
        "checks_not_performed": ["key_revocation"],
        "subject_digest": "a" * 64,
    }
    assert (
        evaluate_unperformed_check_recovery(record, [bad, good])[
            "checks"
        ]["key_revocation"]
        == "evidence_failed"
    )
    # The clean doc alone recovers; the revoked doc alone fails.
    assert (
        evaluate_unperformed_check_recovery(record, [good])["checks"][
            "key_revocation"
        ]
        == "recovered"
    )
    assert (
        evaluate_unperformed_check_recovery(record, [bad])["checks"][
            "key_revocation"
        ]
        == "evidence_failed"
    )


def test_unbound_performer_docs_disagreeing_recover_on_any_true():
    # Record-agnostic performer docs (bind_path=None) are not scoped
    # to this record — an eval doc reporting `subject_bound: false`
    # for a different record's envelope must not veto a `true` doc.
    from agent.core_evidence import evaluate_unperformed_check_recovery

    record = {
        "checks_not_performed": ["subject_binding"],
    }
    good = {
        "schema_version": "mumei.signature-envelope-evaluation/v1",
        "envelope_match": True,
        "subject_bound": True,
        "subject_digest": "a" * 64,
    }
    unrelated = {
        "schema_version": "mumei.signature-envelope-evaluation/v1",
        "envelope_match": True,
        "subject_bound": False,
        "subject_digest": "b" * 64,
    }
    report = evaluate_unperformed_check_recovery(
        record, [good, unrelated]
    )
    assert report["checks"]["subject_binding"] == "recovered"
    # Only the unrelated doc still fails.
    report = evaluate_unperformed_check_recovery(record, [unrelated])
    assert report["checks"]["subject_binding"] == "evidence_failed"


def test_key_authenticity_recovers_via_bound_registry_eval():
    # A bound envelope-eval doc carrying `key_authentic: true`
    # performs `key_authenticity` on the record it covers — the same
    # subject_digest carrier convention as `key_revocation`.
    from agent.core_evidence import (
        evaluate_unperformed_check_recovery,
        producer_key_registry,
        evaluate_signature_envelope,
    )

    registry = producer_key_registry({
        "schema_version": "mumei.producer-key-registry/v1",
        "registry": {
            "key-1": {
                "principal": "release-producer",
                "not_before": "2025-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
            }
        },
    })
    doc = evaluate_signature_envelope(
        {
            "schema_version": "mumei.producer-signature/v1",
            "subject_digest": "a" * 64,
            "algorithm": "ed25519",
            "signature": "00" * 64,
            "producer_key_id": "key-1",
        },
        key_registry=registry,
        reference_time="2026-01-01T00:00:00Z",
    )
    assert doc["key_authentic"] is True
    record = {
        "checks_not_performed": ["key_authenticity"],
        "subject_digest": "a" * 64,
    }
    report = evaluate_unperformed_check_recovery(record, [doc])
    assert report["checks"]["key_authenticity"] == "recovered"
    # A doc for different bytes does not recover this record.
    report = evaluate_unperformed_check_recovery(
        {
            "checks_not_performed": ["key_authenticity"],
            "subject_digest": "c" * 64,
        },
        [doc],
    )
    assert report["checks"]["key_authenticity"] == "evidence_failed"


def test_envelope_freshness_recovers_through_bound_fold_docs():
    digest = "a" * 64
    record = _record("envelope_freshness")
    for schema in (
        "mumei.signature-envelope-evaluation/v1",
        "mumei.signature-verification/v1",
    ):
        doc = _doc(
            schema,
            envelope_match=True,
            envelope_fresh=True,
            subject_digest=digest,
        )
        evaluation = evaluate_unperformed_check_recovery(
            record, [doc], record_digest=digest,
        )
        assert evaluation["checks"]["envelope_freshness"] == "recovered"

    # Stale envelopes report evidence_failed, and a doc bound to
    # other bytes never performs this record's check.
    for doc in (
        _doc(
            "mumei.signature-verification/v1",
            envelope_match=True,
            envelope_fresh=False,
            subject_digest=digest,
        ),
        _doc(
            "mumei.signature-verification/v1",
            envelope_match=True,
            envelope_fresh=True,
            subject_digest="b" * 64,
        ),
    ):
        evaluation = evaluate_unperformed_check_recovery(
            record, [doc], record_digest=digest,
        )
        assert (
            evaluation["checks"]["envelope_freshness"]
            == "evidence_failed"
        )


def test_anchor_authenticity_is_not_composable_through_the_fold():
    # `registry_authentic` / `revocation_list_authentic` on a
    # signature-verification doc are bound only to the signed record's
    # digest — they do not pin WHICH anchor document was assessed, so
    # a doc authenticating a different registry must not recover this
    # record's anchor check. The checks stay unperformable by
    # composition: no performer entries exist.
    digest = "a" * 64
    for check, field in (
        ("registry_authenticity", "registry_authentic"),
        ("revocation_list_authenticity", "revocation_list_authentic"),
    ):
        record = _record(check)
        doc = _doc(
            "mumei.signature-verification/v1",
            envelope_match=True,
            subject_digest=digest,
            **{field: True},
        )
        evaluation = evaluate_unperformed_check_recovery(
            record, [doc], record_digest=digest,
        )
        assert evaluation["checks"][check] == "no_evidence"
