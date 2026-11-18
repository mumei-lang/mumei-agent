"""Route tests for ``signature-sign``: signing a declared record's
digest into a detached ``mumei.producer-signature/v1`` envelope under
a caller-supplied ed25519 secret key file.

The signed payload is the ``subject_digest``'s lowercase-hex ASCII
bytes — the same convention Core's ``crypto_verify_signature`` FFI
and ``verify_signature_envelope`` use. The secret key is a declared
input only: it never appears in the emitted envelope, error text or
any output surface.
"""

import argparse
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from agent.core_evidence import (
    sign_producer_record,
    verify_signature_envelope,
)
from agent.signature_sign import (
    MAX_RECORD_BYTES,
    build_sign_parser,
    main_sign,
)

# An obviously fake sentinel secret — never a real key. Tests assert
# it never lands in any output surface.
_SECRET_HEX = "aa" * 32
_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    bytes.fromhex(_SECRET_HEX)
)
_PUBLIC_KEY_HEX = _PRIVATE_KEY.public_key().public_bytes_raw().hex()
_KEY_ID = "producer-key-fingerprint"

_RECORD = b'{"schema_version": "mumei.test-record/v1", "ok": true}\n'


def _args(record, key_file, key_id=_KEY_ID, *extra):
    parser = argparse.ArgumentParser()
    build_sign_parser(parser)
    return parser.parse_args(
        [
            "--record",
            str(record),
            "--key-file",
            str(key_file),
            "--producer-key-id",
            key_id,
            *extra,
        ]
    )


def _files(tmp_path: Path, record: bytes = _RECORD, key: str = _SECRET_HEX):
    record_path = tmp_path / "record.json"
    record_path.write_bytes(record)
    key_path = tmp_path / "secret.key"
    key_path.write_text(key)
    return record_path, key_path


def test_sign_emits_closed_envelope_and_verifies(tmp_path):
    envelope = sign_producer_record(_RECORD, _SECRET_HEX, _KEY_ID)
    assert set(envelope) == {
        "schema_version",
        "subject_digest",
        "algorithm",
        "signature",
        "producer_key_id",
    }
    assert envelope["schema_version"] == "mumei.producer-signature/v1"
    assert envelope["algorithm"] == "ed25519"
    assert len(envelope["subject_digest"]) == 64
    assert len(envelope["signature"]) == 128
    assert envelope["producer_key_id"] == _KEY_ID
    import hashlib

    assert (
        envelope["subject_digest"]
        == hashlib.sha256(_RECORD).hexdigest()
    )
    # Round-trip: the emitted envelope verifies under the public key.
    verification = verify_signature_envelope(
        envelope, _PUBLIC_KEY_HEX, expected_key=_KEY_ID
    )
    assert verification["envelope_match"] is True
    assert verification["signature_valid"] is True
    assert verification["key_pinned"] is True


def test_sign_rejects_malformed_key_material():
    for bad in (
        "",
        "zz" * 32,           # non-hex
        _SECRET_HEX.upper(),   # uppercase hex rejected (strict lowercase)
        _SECRET_HEX + "00",    # wrong length
        _SECRET_HEX[:-2],      # short
        " " + _SECRET_HEX,     # no whitespace admitted
    ):
        with pytest.raises(ValueError, match="key material"):
            sign_producer_record(_RECORD, bad, _KEY_ID)


def test_sign_rejects_empty_producer_key_id():
    with pytest.raises(ValueError, match="producer key id"):
        sign_producer_record(_RECORD, _SECRET_HEX, "")


def test_sign_never_emits_secret_material(tmp_path, capsys):
    envelope = sign_producer_record(_RECORD, _SECRET_HEX, _KEY_ID)
    assert _SECRET_HEX not in json.dumps(envelope)

    record_path, key_path = _files(tmp_path)
    assert main_sign(_args(record_path, key_path)) == 0
    out = capsys.readouterr()
    assert _SECRET_HEX not in out.out
    assert _SECRET_HEX not in out.err
    emitted = json.loads(out.out)
    assert emitted["schema_version"] == "mumei.producer-signature/v1"

    # Failure paths never leak the key either.
    bad_key = tmp_path / "bad.key"
    bad_key.write_text(_SECRET_HEX.upper())
    assert main_sign(_args(record_path, bad_key)) == 1
    out = capsys.readouterr()
    assert _SECRET_HEX not in out.out
    assert _SECRET_HEX not in out.err


def test_route_static_failures(tmp_path, capsys):
    record_path, key_path = _files(tmp_path)

    missing = tmp_path / "missing.json"
    assert main_sign(_args(missing, key_path)) == 1
    assert main_sign(_args(record_path, missing)) == 1

    oversized = tmp_path / "big.json"
    oversized.write_bytes(b" " * (MAX_RECORD_BYTES + 1))
    assert main_sign(_args(oversized, key_path)) == 1
    out = capsys.readouterr()
    assert "bounded read limit" in out.err

    non_ascii = tmp_path / "nonascii.key"
    non_ascii.write_bytes(b"\xff" * 64)
    assert main_sign(_args(record_path, non_ascii)) == 1

    oversized_key = tmp_path / "bigkey.key"
    oversized_key.write_text("a" * 300)
    assert main_sign(_args(record_path, oversized_key)) == 1

    trailing_ws = tmp_path / "ws.key"
    trailing_ws.write_text(_SECRET_HEX + "\n")
    assert main_sign(_args(record_path, trailing_ws)) == 1

    out = capsys.readouterr()
    assert _SECRET_HEX not in out.err


def test_route_output_file(tmp_path, capsys):
    record_path, key_path = _files(tmp_path)
    out_path = tmp_path / "envelope.json"
    assert (
        main_sign(_args(record_path, key_path, _KEY_ID,
                        "--output", str(out_path)))
        == 0
    )
    assert capsys.readouterr().out == ""
    envelope = json.loads(out_path.read_text())
    assert envelope["schema_version"] == "mumei.producer-signature/v1"
    assert _SECRET_HEX not in out_path.read_text()


def test_route_refuses_output_over_declared_inputs(tmp_path):
    record_path, key_path = _files(tmp_path)
    for declared in (record_path, key_path):
        assert (
            main_sign(
                _args(
                    record_path,
                    key_path,
                    _KEY_ID,
                    "--output",
                    str(declared),
                )
            )
            == 1
        )
        # The declared input is untouched.
        assert declared.read_bytes() in (record_path.read_bytes(),
                                         key_path.read_bytes())
