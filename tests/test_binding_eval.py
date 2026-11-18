"""Route tests for ``binding-eval``: pinning a declared
subject-bearing document to the record bytes it is said to cover,
emitting ``mumei.evidence-binding/v1``.

The fold recomputes the record's SHA-256 from the supplied bytes — a
caller-declared fingerprint is never trusted — and reports
observations only: ``carrier_authenticity`` and
``binding_enforcement`` stay unperformed."""

import hashlib
import json
from pathlib import Path

import pytest

from agent.core_evidence import (
    evaluate_evidence_binding,
    evaluate_unperformed_check_recovery,
)
from agent.binding_eval import (
    build_eval_parser,
    main_eval,
)

_RECORD = b'{"schema_version":"mumei.example-record/v1","claim":1}'
_DIGEST = hashlib.sha256(_RECORD).hexdigest()
_OTHER = hashlib.sha256(b"other record").hexdigest()


def _envelope(subject=_DIGEST):
    return {
        "schema_version": "mumei.producer-signature/v1",
        "subject_digest": subject,
        "algorithm": "ed25519",
        "signature": "ab" * 64,
        "producer_key_id": "key-1",
    }


def _acceptance(fingerprint=_DIGEST):
    return {
        "schema_version": "mumei.source-evidence-acceptance/v1",
        "acceptance": "evaluated",
        "accepted": True,
        "scope": "restricted",
        "checks_performed": [],
        "checks_not_performed": [],
        "evidence_fingerprint": fingerprint,
    }


def _args(parser, record_path, evidence_path, *extra):
    return parser.parse_args(
        [
            "--record",
            str(record_path),
            "--evidence",
            str(evidence_path),
            *extra,
        ]
    )


def test_bound_signature_envelope():
    binding = evaluate_evidence_binding(_RECORD, _envelope())
    assert binding["schema_version"] == "mumei.evidence-binding/v1"
    assert binding["record_digest"] == _DIGEST
    assert binding["carrier_match"] is True
    assert binding["subject_declared"] is True
    assert binding["bound"] is True
    assert set(binding["checks_not_performed"]) == {
        "carrier_authenticity",
        "binding_enforcement",
    }


def test_bound_acceptance_descriptor():
    for schema in (
        "mumei.source-evidence-acceptance/v1",
        "mumei.native-evidence-acceptance/v1",
    ):
        descriptor = _acceptance()
        descriptor["schema_version"] = schema
        binding = evaluate_evidence_binding(_RECORD, descriptor)
        assert binding["carrier_match"] is True
        assert binding["bound"] is True


def test_bound_recheck_diagnostic():
    # The real `recheck-source` consistent diagnostic — schema,
    # `evidence_schema_version`, `evidence_fingerprint`, `recheck` —
    # binds like an acceptance descriptor. A fingerprint that does
    # not match the record bytes reports `bound` as an observation,
    # not an error.
    diagnostic = {
        "schema_version": "mumei.source-evidence-recheck/v1",
        "evidence_schema_version": "mumei.verification-evidence/v1",
        "evidence_fingerprint": _DIGEST,
        "recheck": "consistent",
    }
    binding = evaluate_evidence_binding(_RECORD, diagnostic)
    assert binding["carrier_match"] is True
    assert binding["subject_declared"] is True
    assert binding["bound"] is True
    diagnostic["evidence_fingerprint"] = _OTHER
    assert (
        evaluate_evidence_binding(_RECORD, diagnostic)["bound"] is False
    )


def test_digest_mismatch_is_an_observation_not_an_error():
    binding = evaluate_evidence_binding(_RECORD, _envelope(_OTHER))
    assert binding["carrier_match"] is True
    assert binding["subject_declared"] is True
    assert binding["bound"] is False


def test_record_bytes_are_what_bind():
    # Any byte change — one bit in the record — flips the digest.
    binding = evaluate_evidence_binding(_RECORD + b"\n", _envelope())
    assert binding["bound"] is False
    assert binding["record_digest"] == hashlib.sha256(
        _RECORD + b"\n"
    ).hexdigest()


def test_foreign_or_subjectless_documents_never_bind():
    for document in (
        {},
        {"schema_version": "mumei.unknown/v1", "subject_digest": _DIGEST},
        # A subject digest under an undeclared schema never counts.
        {"schema_version": "mumei.freshness-evaluation/v1"},
        # A well-formed carrier with no/invalid subject is unbound.
        _envelope(None),
        _envelope("not-hex"),
        _envelope(_DIGEST.upper()),
        _envelope(64),
    ):
        binding = evaluate_evidence_binding(_RECORD, document)
        assert binding["bound"] is False


def test_request_validation():
    with pytest.raises(ValueError):
        evaluate_evidence_binding("not-bytes", _envelope())
    with pytest.raises(ValueError):
        evaluate_evidence_binding(_RECORD, "not-a-dict")
    with pytest.raises(ValueError):
        evaluate_evidence_binding(b"", [])


def test_binding_doc_recovers_evidence_binding():
    # Subject-bound recovery: a bound binding document performs the
    # `evidence_binding` check a record declares unperformed — but
    # only when the fold pins it to THIS record's digest.
    record = {"checks_not_performed": ["evidence_binding"]}
    bound_doc = evaluate_evidence_binding(_RECORD, _envelope())
    recovery = evaluate_unperformed_check_recovery(
        record, [bound_doc], record_digest=_DIGEST
    )
    assert recovery["checks"]["evidence_binding"] == "recovered"

    unbound_doc = evaluate_evidence_binding(_RECORD, _envelope(_OTHER))
    recovery = evaluate_unperformed_check_recovery(
        record, [unbound_doc], record_digest=_DIGEST
    )
    assert recovery["checks"]["evidence_binding"] == "evidence_failed"

    # A document only *claiming* the schema without a true outcome
    # can never recover the check.
    forged = {"schema_version": "mumei.evidence-binding/v1"}
    recovery = evaluate_unperformed_check_recovery(
        record, [forged], record_digest=_DIGEST
    )
    assert recovery["checks"]["evidence_binding"] == "evidence_failed"


def test_binding_recovery_requires_this_records_digest():
    record = {"checks_not_performed": ["evidence_binding"]}
    bound_doc = evaluate_evidence_binding(_RECORD, _envelope())

    # A bound document for record A never recovers record B's
    # `evidence_binding`.
    recovery = evaluate_unperformed_check_recovery(
        record, [bound_doc], record_digest=_OTHER
    )
    assert recovery["checks"]["evidence_binding"] == "evidence_failed"

    # Without a declared digest no binding document can be
    # attributed — the check stays unrecovered rather than trusting
    # an unattributable bound result.
    recovery = evaluate_unperformed_check_recovery(record, [bound_doc])
    assert recovery["checks"]["evidence_binding"] == "evidence_failed"

    # A malformed declared digest fails statically.
    with pytest.raises(ValueError):
        evaluate_unperformed_check_recovery(
            record, [bound_doc], record_digest="not-hex"
        )

    # Other performer checks stay record-agnostic.
    record = {
        "checks_not_performed": ["evidence_binding", "subject_binding"]
    }
    subject_doc = {
        "schema_version": "mumei.signature-verification/v1",
        "subject_bound": True,
    }
    recovery = evaluate_unperformed_check_recovery(
        record, [bound_doc, subject_doc], record_digest=_DIGEST
    )
    assert recovery["checks"]["evidence_binding"] == "recovered"
    assert recovery["checks"]["subject_binding"] == "recovered"


def test_route_composes_with_recovery_eval(tmp_path, capsys):
    import argparse

    from agent.recovery_eval import (
        build_eval_parser as build_recovery_parser,
        main_eval as recovery_main,
    )

    # The record under recovery declares `evidence_binding`; the
    # signature envelope was issued over this file's exact bytes.
    record_bytes = (
        b'{"schema_version":"mumei.example/v1",'
        b'"checks_not_performed":["evidence_binding"]}'
    )
    record = tmp_path / "record.json"
    record.write_bytes(record_bytes)
    envelope = tmp_path / "env.json"
    envelope.write_text(
        json.dumps(_envelope(hashlib.sha256(record_bytes).hexdigest()))
    )

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    binding_out = tmp_path / "binding.json"
    assert (
        main_eval(
            _args(parser, record, envelope, "--output", str(binding_out))
        )
        == 0
    )
    assert json.loads(binding_out.read_text())["bound"] is True

    rec_parser = argparse.ArgumentParser()
    build_recovery_parser(rec_parser)

    # recovery-eval recomputes the record's digest and only counts
    # the bound document when the digests match — a rewritten record
    # (same declared check, different bytes) is not covered.
    for suffix, expected in ((b"", "recovered"), (b"\n", "evidence_failed")):
        record.write_bytes(record_bytes + suffix)
        args = rec_parser.parse_args(
            ["--record", str(record), "--evidence", str(binding_out)]
        )
        assert recovery_main(args) == 0
        emitted = json.loads(capsys.readouterr().out)
        assert emitted["checks"]["evidence_binding"] == expected


def test_route_emits_binding(tmp_path, capsys):
    import argparse

    record = tmp_path / "record.bin"
    record.write_bytes(_RECORD)
    evidence = tmp_path / "env.json"
    evidence.write_text(json.dumps(_envelope()))

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    assert main_eval(_args(parser, record, evidence)) == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["bound"] is True
    assert emitted["record_digest"] == _DIGEST


def test_route_output_file_and_overwrite_guard(tmp_path, capsys):
    import argparse

    record = tmp_path / "record.bin"
    record.write_bytes(_RECORD)
    evidence = tmp_path / "env.json"
    evidence.write_text(json.dumps(_envelope()))
    out = tmp_path / "out.json"

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    assert (
        main_eval(_args(parser, record, evidence, "--output", str(out)))
        == 0
    )
    assert json.loads(out.read_text())["bound"] is True

    # --output may not clobber either declared input.
    for target in (record, evidence):
        assert (
            main_eval(
                _args(parser, record, evidence, "--output", str(target))
            )
            == 1
        )


def test_route_static_failures(tmp_path, capsys):
    import argparse

    record = tmp_path / "record.bin"
    record.write_bytes(_RECORD)
    evidence = tmp_path / "env.json"
    evidence.write_text(json.dumps(_envelope()))

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)

    missing = tmp_path / "missing.json"
    assert main_eval(_args(parser, record, missing)) == 1
    assert main_eval(_args(parser, missing, evidence)) == 1

    malformed = tmp_path / "bad.json"
    malformed.write_text("{not json")
    assert main_eval(_args(parser, record, malformed)) == 1
    assert "binding-eval:" in capsys.readouterr().err

    non_object = tmp_path / "list.json"
    non_object.write_text("[1, 2]")
    assert main_eval(_args(parser, record, non_object)) == 1
