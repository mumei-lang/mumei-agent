"""Route tests for ``signature-eval``: folding a declared
``mumei.producer-signature/v1`` envelope into
``mumei.signature-envelope-evaluation/v1``.

Representation-level only — the fold checks the envelope's closed shape
and declared pins, never the ed25519 signature bytes, the key's own
authenticity, freshness or revocation."""

import json
from pathlib import Path

import pytest

from agent.core_evidence import evaluate_signature_envelope
from agent.signature_eval import (
    build_eval_parser,
    main_eval,
)

_SUBJECT = "a" * 64
_OTHER_SUBJECT = "b" * 64
_SIGNATURE = "c" * 128
_KEY = "producer-key-fingerprint"


def _envelope(**overrides) -> dict:
    value = {
        "schema_version": "mumei.producer-signature/v1",
        "subject_digest": _SUBJECT,
        "algorithm": "ed25519",
        "signature": _SIGNATURE,
        "producer_key_id": _KEY,
    }
    value.update(overrides)
    return value


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


def _args(parser, envelope_path, *extra):
    return parser.parse_args(
        ["--envelope", str(envelope_path), *extra]
    )


def test_well_formed_envelope_matches():
    evaluation = evaluate_signature_envelope(_envelope())
    assert evaluation["schema_version"] == (
        "mumei.signature-envelope-evaluation/v1"
    )
    assert evaluation["envelope_match"] is True
    assert "subject_bound" not in evaluation
    assert "key_pinned" not in evaluation
    assert set(evaluation["checks_not_performed"]) == {
        "subject_binding",
        "key_binding",
        "signature_verification",
        "key_authenticity",
        "envelope_freshness",
        "key_revocation",
    }


def test_subject_and_key_pins():
    evaluation = evaluate_signature_envelope(
        _envelope(),
        expected_subject=_SUBJECT,
        expected_key=_KEY,
    )
    assert evaluation["envelope_match"] is True
    assert evaluation["subject_bound"] is True
    assert evaluation["key_pinned"] is True
    assert "subject_binding" not in evaluation["checks_not_performed"]
    assert "key_binding" not in evaluation["checks_not_performed"]
    # Crypto verification, key authenticity, freshness and revocation
    # are never claimed at representation level.
    assert "signature_verification" in evaluation["checks_not_performed"]
    assert "key_authenticity" in evaluation["checks_not_performed"]
    assert "envelope_freshness" in evaluation["checks_not_performed"]
    assert "key_revocation" in evaluation["checks_not_performed"]


def test_pin_mismatch_is_observation_not_error():
    evaluation = evaluate_signature_envelope(
        _envelope(),
        expected_subject=_OTHER_SUBJECT,
        expected_key="other-key",
    )
    assert evaluation["envelope_match"] is True
    assert evaluation["subject_bound"] is False
    assert evaluation["key_pinned"] is False


def test_unmatched_envelope_reports_pins_false():
    for broken in (
        _envelope(schema_version="other/v1"),
        _envelope(algorithm="rsa"),
        _envelope(subject_digest="not-hex"),
        _envelope(signature="ab" * 4),
        _envelope(signature="C" * 128),  # uppercase hex rejected
        _envelope(producer_key_id=""),
        _envelope(producer_key_id=7),
        {**_envelope(), "extra": True},
        {k: v for k, v in _envelope().items() if k != "signature"},
    ):
        evaluation = evaluate_signature_envelope(
            broken,
            expected_subject=_SUBJECT,
            expected_key=_KEY,
        )
        assert evaluation["envelope_match"] is False
        assert evaluation["subject_bound"] is False
        assert evaluation["key_pinned"] is False


def test_request_validation():
    with pytest.raises(ValueError):
        evaluate_signature_envelope("not-a-dict")
    with pytest.raises(ValueError):
        evaluate_signature_envelope(_envelope(), expected_subject="zz")
    with pytest.raises(ValueError):
        evaluate_signature_envelope(_envelope(), expected_key="")


def test_route_emits_evaluation(tmp_path, capsys):
    envelope = _write(tmp_path / "env.json", _envelope())
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    exit_code = main_eval(
        _args(
            parser,
            envelope,
            "--expected-subject", _SUBJECT,
            "--expected-producer-key", _KEY,
        )
    )
    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["envelope_match"] is True
    assert emitted["subject_bound"] is True
    assert emitted["key_pinned"] is True


def test_route_output_file(tmp_path, capsys):
    envelope = _write(tmp_path / "env.json", _envelope())
    out = tmp_path / "out.json"
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    exit_code = main_eval(
        _args(parser, envelope, "--output", str(out))
    )
    assert exit_code == 0
    emitted = json.loads(out.read_text())
    assert emitted["envelope_match"] is True


def test_route_static_failures(tmp_path, capsys):
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)

    missing = tmp_path / "missing.json"
    assert main_eval(_args(parser, missing)) == 1
    assert "signature-eval:" in capsys.readouterr().err

    malformed = _write(tmp_path / "bad.json", "{not json")
    assert main_eval(_args(parser, malformed)) == 1

    non_object = _write(tmp_path / "list.json", [1, 2])
    assert main_eval(_args(parser, non_object)) == 1

    envelope = _write(tmp_path / "env.json", _envelope())
    assert main_eval(
        _args(parser, envelope, "--expected-subject", "zz")
    ) == 1


def test_route_refuses_output_over_input(tmp_path):
    envelope = _write(tmp_path / "env.json", _envelope())
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    assert (
        main_eval(_args(parser, envelope, "--output", str(envelope)))
        == 1
    )


def test_revocation_list_performs_key_revocation():
    # A declared `mumei.key-revocation-list/v1` performs
    # `key_revocation` on the matched envelope's key id — the list is
    # trusted as declared like every other supporting document.
    revoked = {"schema_version": "mumei.key-revocation-list/v1",
               "revoked_keys": ["other-key"]}
    from agent.core_evidence import revocation_key_set

    evaluation = evaluate_signature_envelope(
        _envelope(), revoked_keys=revocation_key_set(revoked)
    )
    assert evaluation["envelope_match"] is True
    assert evaluation["key_not_revoked"] is True
    assert "key_revocation" not in evaluation["checks_not_performed"]
    assert "key_authenticity" in evaluation["checks_not_performed"]


def test_revoked_key_reports_false():
    from agent.core_evidence import revocation_key_set

    evaluation = evaluate_signature_envelope(
        _envelope(), revoked_keys=revocation_key_set(
            {"schema_version": "mumei.key-revocation-list/v1",
             "revoked_keys": [_KEY]}
        )
    )
    assert evaluation["envelope_match"] is True
    assert evaluation["key_not_revoked"] is False


def test_unmatched_envelope_reports_not_revoked_false():
    from agent.core_evidence import revocation_key_set

    evaluation = evaluate_signature_envelope(
        _envelope(schema_version="other"),
        revoked_keys=revocation_key_set(
            {"schema_version": "mumei.key-revocation-list/v1",
             "revoked_keys": []}
        ),
    )
    assert evaluation["envelope_match"] is False
    assert evaluation["key_not_revoked"] is False
    # An unmatched envelope has no trusted digest to echo.
    assert "subject_digest" not in evaluation


def test_eval_doc_echoes_subject_digest():
    # The echoed carrier lets the recovery fold bind the document to
    # the record the signature covers.
    evaluation = evaluate_signature_envelope(_envelope())
    assert evaluation["subject_digest"] == _SUBJECT


def test_revocation_list_shape_rejects_foreign_documents():
    from agent.core_evidence import revocation_key_set

    for bad in (
        {"schema_version": "mumei.key-revocation-list/v1"},
        {"schema_version": "other", "revoked_keys": [_KEY]},
        {"schema_version": "mumei.key-revocation-list/v1",
         "revoked_keys": "not-a-list"},
        {"schema_version": "mumei.key-revocation-list/v1",
         "revoked_keys": [""]},
        {"schema_version": "mumei.key-revocation-list/v1",
         "revoked_keys": [_KEY], "extra": 1},
    ):
        with pytest.raises(ValueError):
            revocation_key_set(bad)


def test_route_revocation_list(tmp_path, capsys):
    import argparse

    envelope = _write(tmp_path / "env.json", _envelope())
    revoked = _write(
        tmp_path / "rev.json",
        {"schema_version": "mumei.key-revocation-list/v1",
         "revoked_keys": []},
    )
    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    exit_code = main_eval(
        _args(parser, envelope, "--revocation-list", str(revoked))
    )
    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["key_not_revoked"] is True
    assert "key_revocation" not in emitted["checks_not_performed"]


def test_route_malformed_revocation_list_fails(tmp_path, capsys):
    import argparse

    envelope = _write(tmp_path / "env.json", _envelope())
    bad = _write(tmp_path / "bad.json", {"schema_version": "other"})
    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    assert (
        main_eval(
            _args(parser, envelope, "--revocation-list", str(bad))
        )
        == 1
    )
    assert "signature-eval:" in capsys.readouterr().err


def test_route_refuses_output_over_revocation_list(tmp_path):
    # `--output` colliding with the declared revocation list is the
    # same overwrite hazard as colliding with the envelope.
    envelope = _write(tmp_path / "env.json", _envelope())
    revoked = _write(
        tmp_path / "revoked.json",
        {"schema_version": "mumei.key-revocation-list/v1",
         "revoked_keys": []},
    )
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    assert (
        main_eval(
            _args(parser, envelope, "--revocation-list", str(revoked),
                  "--output", str(revoked))
        )
        == 1
    )
    # The declared input survives untouched.
    assert json.loads(revoked.read_text())["revoked_keys"] == []
