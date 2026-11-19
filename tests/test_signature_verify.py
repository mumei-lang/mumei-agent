"""Route tests for ``signature-verify``: cryptographically verifying a
declared ``mumei.producer-signature/v1`` envelope's ed25519 signature
under a caller-supplied public key, emitting
``mumei.signature-verification/v1``.

The signed payload is the ``subject_digest``'s lowercase-hex ASCII
bytes — the same message convention Core's ``crypto_verify_signature``
FFI uses. ``signature_valid`` binds the declared key to the declared
digest only; key authenticity, freshness and revocation stay
unperformed."""

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from agent.core_evidence import verify_signature_envelope
from agent.signature_verify import (
    build_verify_parser,
    main_verify,
)

_SUBJECT = "a" * 64
_OTHER_SUBJECT = "b" * 64
_KEY_ID = "producer-key-fingerprint"

_PRIVATE_KEY = Ed25519PrivateKey.generate()
_PUBLIC_KEY_HEX = (
    _PRIVATE_KEY.public_key()
    .public_bytes_raw()
    .hex()
)
_OTHER_PRIVATE_KEY = Ed25519PrivateKey.generate()
_OTHER_PUBLIC_KEY_HEX = (
    _OTHER_PRIVATE_KEY.public_key()
    .public_bytes_raw()
    .hex()
)


def _sign(message: str, key: Ed25519PrivateKey = _PRIVATE_KEY) -> str:
    return key.sign(message.encode("ascii")).hex()


def _envelope(**overrides) -> dict:
    value = {
        "schema_version": "mumei.producer-signature/v1",
        "subject_digest": _SUBJECT,
        "algorithm": "ed25519",
        "signature": _sign(_SUBJECT),
        "producer_key_id": _KEY_ID,
    }
    value.update(overrides)
    return value


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


def _args(parser, envelope_path, key=_PUBLIC_KEY_HEX, *extra):
    return parser.parse_args(
        [
            "--envelope",
            str(envelope_path),
            "--producer-key",
            key,
            *extra,
        ]
    )


def test_valid_signature_verifies():
    verification = verify_signature_envelope(
        _envelope(), _PUBLIC_KEY_HEX
    )
    assert verification["schema_version"] == (
        "mumei.signature-verification/v1"
    )
    assert verification["envelope_match"] is True
    assert verification["signature_valid"] is True
    assert verification["subject_digest"] == _SUBJECT
    assert "subject_bound" not in verification
    assert "key_pinned" not in verification
    assert set(verification["checks_not_performed"]) == {
        "subject_binding",
        "key_binding",
        "key_authenticity",
        "envelope_freshness",
        "key_revocation",
    }


def test_tampered_and_wrong_key_fail():
    # A signature over a different message does not verify.
    verification = verify_signature_envelope(
        _envelope(signature=_sign(_OTHER_SUBJECT)), _PUBLIC_KEY_HEX
    )
    assert verification["envelope_match"] is True
    assert verification["signature_valid"] is False

    # A signature from a different key does not verify.
    verification = verify_signature_envelope(
        _envelope(signature=_sign(_SUBJECT, _OTHER_PRIVATE_KEY)),
        _PUBLIC_KEY_HEX,
    )
    assert verification["envelope_match"] is True
    assert verification["signature_valid"] is False

    # The matching signature under a different declared key fails too.
    verification = verify_signature_envelope(
        _envelope(), _OTHER_PUBLIC_KEY_HEX
    )
    assert verification["envelope_match"] is True
    assert verification["signature_valid"] is False


def test_subject_and_key_pins():
    verification = verify_signature_envelope(
        _envelope(),
        _PUBLIC_KEY_HEX,
        expected_subject=_SUBJECT,
        expected_key=_KEY_ID,
    )
    assert verification["envelope_match"] is True
    assert verification["signature_valid"] is True
    assert verification["subject_bound"] is True
    assert verification["key_pinned"] is True
    assert "subject_binding" not in verification["checks_not_performed"]
    assert "key_binding" not in verification["checks_not_performed"]
    # Key authenticity, freshness and revocation are never claimed.
    assert "key_authenticity" in verification["checks_not_performed"]
    assert "envelope_freshness" in verification["checks_not_performed"]
    assert "key_revocation" in verification["checks_not_performed"]

    verification = verify_signature_envelope(
        _envelope(),
        _PUBLIC_KEY_HEX,
        expected_subject=_OTHER_SUBJECT,
        expected_key="other-key",
    )
    assert verification["subject_bound"] is False
    assert verification["key_pinned"] is False


def test_unmatched_envelope_never_verifies():
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
        verification = verify_signature_envelope(
            broken,
            _PUBLIC_KEY_HEX,
            expected_subject=_SUBJECT,
            expected_key=_KEY_ID,
        )
        assert verification["envelope_match"] is False
        assert verification["signature_valid"] is False
        assert verification["subject_bound"] is False
        assert verification["key_pinned"] is False
        # An unmatched envelope carries no digest a consumer could
        # bind to a record.
        assert "subject_digest" not in verification


def test_request_validation():
    with pytest.raises(ValueError):
        verify_signature_envelope("not-a-dict", _PUBLIC_KEY_HEX)
    with pytest.raises(ValueError):
        verify_signature_envelope(_envelope(), "not-hex")
    with pytest.raises(ValueError):
        verify_signature_envelope(_envelope(), _PUBLIC_KEY_HEX[:-2])
    with pytest.raises(ValueError):
        verify_signature_envelope(
            _envelope(), _PUBLIC_KEY_HEX, expected_subject="zz"
        )
    with pytest.raises(ValueError):
        verify_signature_envelope(
            _envelope(), _PUBLIC_KEY_HEX, expected_key=""
        )


def test_route_emits_verification(tmp_path, capsys):
    envelope = _write(tmp_path / "env.json", _envelope())
    import argparse

    parser = argparse.ArgumentParser()
    build_verify_parser(parser)
    exit_code = main_verify(
        _args(
            parser,
            envelope,
            _PUBLIC_KEY_HEX,
            "--expected-subject",
            _SUBJECT,
            "--expected-producer-key",
            _KEY_ID,
        )
    )
    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["envelope_match"] is True
    assert emitted["signature_valid"] is True
    assert emitted["subject_bound"] is True
    assert emitted["key_pinned"] is True


def test_route_output_file(tmp_path, capsys):
    envelope = _write(tmp_path / "env.json", _envelope())
    out = tmp_path / "out.json"
    import argparse

    parser = argparse.ArgumentParser()
    build_verify_parser(parser)
    exit_code = main_verify(
        _args(parser, envelope, _PUBLIC_KEY_HEX, "--output", str(out))
    )
    assert exit_code == 0
    emitted = json.loads(out.read_text())
    assert emitted["envelope_match"] is True
    assert emitted["signature_valid"] is True


def test_route_static_failures(tmp_path, capsys):
    import argparse

    parser = argparse.ArgumentParser()
    build_verify_parser(parser)

    missing = tmp_path / "missing.json"
    assert main_verify(_args(parser, missing)) == 1
    assert "signature-verify:" in capsys.readouterr().err

    malformed = _write(tmp_path / "bad.json", "{not json")
    assert main_verify(_args(parser, malformed)) == 1

    non_object = _write(tmp_path / "list.json", [1, 2])
    assert main_verify(_args(parser, non_object)) == 1

    envelope = _write(tmp_path / "env.json", _envelope())
    assert main_verify(_args(parser, envelope, "not-a-key")) == 1
    assert (
        main_verify(
            _args(
                parser,
                envelope,
                _PUBLIC_KEY_HEX,
                "--expected-subject",
                "zz",
            )
        )
        == 1
    )


def test_route_refuses_output_over_input(tmp_path):
    envelope = _write(tmp_path / "env.json", _envelope())
    import argparse

    parser = argparse.ArgumentParser()
    build_verify_parser(parser)
    assert (
        main_verify(
            _args(parser, envelope, _PUBLIC_KEY_HEX, "--output", str(envelope))
        )
        == 1
    )


def test_revocation_list_performs_key_revocation():
    from agent.core_evidence import revocation_key_set

    verification = verify_signature_envelope(
        _envelope(),
        _PUBLIC_KEY_HEX,
        revoked_keys=revocation_key_set(
            {"schema_version": "mumei.key-revocation-list/v1",
             "revoked_keys": ["other-key"]}
        ),
    )
    assert verification["envelope_match"] is True
    assert verification["signature_valid"] is True
    assert verification["key_not_revoked"] is True
    assert "key_revocation" not in verification["checks_not_performed"]
    assert "key_authenticity" in verification["checks_not_performed"]
    assert "envelope_freshness" in verification["checks_not_performed"]


def test_revoked_key_reports_false():
    from agent.core_evidence import revocation_key_set

    verification = verify_signature_envelope(
        _envelope(),
        _PUBLIC_KEY_HEX,
        revoked_keys=revocation_key_set(
            {"schema_version": "mumei.key-revocation-list/v1",
             "revoked_keys": [_KEY_ID]}
        ),
    )
    assert verification["signature_valid"] is True
    assert verification["key_not_revoked"] is False


def test_route_revocation_list(tmp_path, capsys):
    import argparse

    envelope = _write(tmp_path / "env.json", _envelope())
    revoked = _write(
        tmp_path / "rev.json",
        {"schema_version": "mumei.key-revocation-list/v1",
         "revoked_keys": []},
    )
    parser = argparse.ArgumentParser()
    build_verify_parser(parser)
    exit_code = main_verify(
        _args(
            parser,
            envelope,
            _PUBLIC_KEY_HEX,
            "--revocation-list",
            str(revoked),
        )
    )
    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["key_not_revoked"] is True
    assert "key_revocation" not in emitted["checks_not_performed"]


def test_route_refuses_output_over_revocation_list(tmp_path):
    # `--output` colliding with the declared revocation list is the
    # same overwrite hazard as colliding with the envelope or key.
    envelope = tmp_path / "env.json"
    envelope.write_text(json.dumps(_envelope()))
    revoked = tmp_path / "revoked.json"
    revoked.write_text(json.dumps(
        {"schema_version": "mumei.key-revocation-list/v1",
         "revoked_keys": []}
    ))
    import argparse

    parser = argparse.ArgumentParser()
    build_verify_parser(parser)
    assert (
        main_verify(
            _args(parser, envelope, _PUBLIC_KEY_HEX,
                  "--revocation-list", str(revoked),
                  "--output", str(revoked))
        )
        == 1
    )
    assert json.loads(revoked.read_text())["revoked_keys"] == []
