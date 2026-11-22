"""C02/C11 signature-verification route: verify a declared producer
signature's ed25519 signature cryptographically.

`signature-verify` restores one declared `mumei.producer-signature/v1`
envelope — the detached authenticity record the issue #886 design memo
fixes — plus a raw ed25519 public key the caller supplies over a
separately trusted channel, and emits
`mumei.signature-verification/v1`: whether the document is a
closed-shape member of the known envelope family (`envelope_match`),
whether the signature cryptographically verifies over the
`subject_digest`'s lowercase-hex bytes under the declared key
(`signature_valid`), and the same `subject_bound`/`key_pinned`
declared pins `signature-eval` emits.

The signed payload convention matches Core's `crypto_verify_signature`
FFI: the message is `subject_digest`'s ASCII bytes. A signature that
verifies binds the declared key to the declared digest — nothing more:
`checks_not_performed` keeps `key_authenticity` and
`envelope_freshness` honest (`key_revocation` too, unless the caller
supplies a declared `mumei.key-revocation-list/v1` (or /v2) document with
`--revocation-list`, which performs it and emits `key_not_revoked`).
The declared anchors themselves are authenticatable too:
`--registry-signature`/`--registry-key` and
`--revocation-signature`/`--revocation-key` each supply a
`mumei.producer-signature/v1` envelope over the anchor document's
exact bytes verified under a consumer-pinned root key, emitting
`registry_authentic`/`revocation_list_authentic` and AND-ing them
into `key_authentic`/`key_not_revoked`. A
malformed or foreign document fails statically rather than reporting
`envelope_match: false`; a matched envelope whose signature fails
reports `false` observations, never an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from agent.core_evidence import (
    producer_key_registry,
    revocation_key_set,
    revocation_list_metadata,
    verify_signature_envelope,
)

MAX_ENVELOPE_BYTES = 1024 * 1024


def build_verify_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--envelope",
        required=True,
        metavar="PATH",
        help="Declared producer-signature envelope JSON "
        "(mumei.producer-signature/v1).",
    )
    parser.add_argument(
        "--producer-key",
        required=True,
        metavar="HEX",
        help="Raw ed25519 public key (64-char lowercase hex) supplied "
        "over a separately trusted channel. The route verifies the "
        "envelope's signature over subject_digest under this key.",
    )
    parser.add_argument(
        "--expected-subject",
        metavar="HEX",
        help="Declared record digest the signature should cover "
        "(64-char lowercase SHA-256 hex). When supplied the "
        "verification emits subject_bound comparing it to the "
        "envelope's subject_digest.",
    )
    parser.add_argument(
        "--expected-producer-key",
        metavar="ID",
        help="Declared producer key id the caller trusts, arriving "
        "over a separately trusted channel. When supplied the "
        "verification emits key_pinned comparing it to the envelope's "
        "producer_key_id.",
    )
    parser.add_argument(
        "--revocation-list",
        metavar="PATH",
        help="Declared revocation list JSON "
        "(mumei.key-revocation-list/v1) supplied over a separately "
        "trusted channel. When supplied the verification emits "
        "key_not_revoked checking the envelope's producer_key_id "
        "against the list's revoked_keys.",
    )
    parser.add_argument(
        "--key-registry",
        metavar="PATH",
        help="Declared producer-key registry JSON "
        "(mumei.producer-key-registry/v1) supplied over a separately "
        "trusted channel. Requires --reference-time. When supplied "
        "the verification emits key_authentic checking the "
        "envelope's producer_key_id against the registry's declared "
        "windows.",
    )
    parser.add_argument(
        "--registry-signature",
        metavar="PATH",
        help="Declared producer-signature envelope JSON "
        "(mumei.producer-signature/v1) signing the --key-registry "
        "document's exact bytes — its subject_digest must be the "
        "SHA-256 of those bytes. Requires --key-registry and "
        "--registry-key. When supplied the verification emits "
        "registry_authentic and ANDs it into key_authentic.",
    )
    parser.add_argument(
        "--registry-key",
        metavar="HEX",
        help="Raw ed25519 public key (64-char lowercase hex) of the "
        "registry's signer — the consumer-pinned root key, supplied "
        "over a separately trusted channel. Requires "
        "--registry-signature.",
    )
    parser.add_argument(
        "--revocation-signature",
        metavar="PATH",
        help="Declared producer-signature envelope JSON "
        "(mumei.producer-signature/v1) signing the --revocation-list "
        "document's exact bytes. Requires --revocation-list and "
        "--revocation-key. When supplied the verification emits "
        "revocation_list_authentic and ANDs it into key_not_revoked.",
    )
    parser.add_argument(
        "--min-revocation-version",
        metavar="N",
        type=int,
        help="Declared minimum list_version the revocation list must "
        "clear. Requires --revocation-list naming a "
        "mumei.key-revocation-list/v2 document, --reference-time and "
        "a signed list (--revocation-signature, and on this route "
        "--revocation-key). When supplied the evaluation emits "
        "revocation_list_current checking the list's declared window "
        "and version.",
    )
    parser.add_argument(
        "--revocation-key",
        metavar="HEX",
        help="Raw ed25519 public key (64-char lowercase hex) of the "
        "revocation list's signer — the consumer-pinned root key, "
        "supplied over a separately trusted channel. Requires "
        "--revocation-signature.",
    )
    parser.add_argument(
        "--reference-time",
        metavar="RFC3339",
        help="The caller's declared reference time (RFC 3339 with "
        "timezone, e.g. 2026-11-18T00:00:00Z) the registry windows "
        "and the envelope's produced_at stamp are compared against. "
        "The fold never reads the system clock. Required with "
        "--key-registry or --max-age-seconds.",
    )
    parser.add_argument(
        "--max-age-seconds",
        metavar="N",
        type=int,
        help="Declared freshness window in seconds: the envelope's "
        "optional produced_at stamp must be no older than "
        "reference_time minus N seconds. Requires --reference-time. "
        "When supplied the evaluation emits envelope_fresh.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the verification descriptor to PATH instead of stdout.",
    )


def _load_declared(path: str, unique: bool = False) -> tuple:
    """Read one declared document, returning (raw bytes, parsed dict).

    The raw bytes come back so a caller can pin a signature envelope
    to the document's own SHA-256 — the trust-anchor signature covers
    the exact file bytes, not a re-encoded form."""
    with open(path, "rb") as handle:
        data = handle.read(MAX_ENVELOPE_BYTES + 1)
    if len(data) > MAX_ENVELOPE_BYTES:
        raise ValueError("declared document exceeds the bounded read limit")
    try:
        if unique:
            value = json.loads(
                data.decode("utf-8"), object_pairs_hook=_unique_object
            )
        else:
            value = json.loads(data.decode("utf-8"))
    except _DuplicateKey:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        # ValueError covers a malformed document and the integer-digit
        # conversion limit; RecursionError covers pathological nesting.
        raise ValueError("declared document is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ValueError("declared document must be a JSON object")
    return data, value


def _read_declared(path: str) -> dict:
    return _load_declared(path)[1]


class _DuplicateKey(ValueError):
    """Sentinel so a duplicate-key rejection keeps its own message."""


def _unique_object(pairs: list) -> dict:
    """Reject duplicate keys — a closed registry shape must not let a
    repeated `key_id` silently shadow an earlier entry."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(
                "declared document has a duplicate key"
            )
        result[key] = value
    return result


def _read_declared_unique(path: str) -> dict:
    """Like ``_read_declared`` but rejecting duplicate object keys."""
    return _load_declared(path, unique=True)[1]


def run_verify(args: argparse.Namespace) -> dict:
    envelope = _read_declared(args.envelope)
    output_path = getattr(args, "output", None)
    if output_path is not None:
        out_path = Path(output_path)
        for declared_input in (
            args.envelope,
            getattr(args, "revocation_list", None),
            getattr(args, "key_registry", None),
            getattr(args, "registry_signature", None),
            getattr(args, "revocation_signature", None),
        ):
            if declared_input is None:
                continue
            try:
                if Path(declared_input).samefile(out_path):
                    raise ValueError(
                        "--output may not overwrite a declared"
                        " input document"
                    )
            except FileNotFoundError:
                pass
    revoked_keys = None
    revocation_digest = None
    revocation_list_meta = None
    revocation_path = getattr(args, "revocation_list", None)
    if revocation_path is not None:
        raw, declared = _load_declared(revocation_path)
        revoked_keys = revocation_key_set(declared)
        revocation_list_meta = revocation_list_metadata(declared)
        revocation_digest = hashlib.sha256(raw).hexdigest()
    key_registry = None
    registry_digest = None
    registry_path = getattr(args, "key_registry", None)
    if registry_path is not None:
        raw, declared = _load_declared(registry_path, unique=True)
        key_registry = producer_key_registry(declared)
        registry_digest = hashlib.sha256(raw).hexdigest()
    registry_signature = None
    registry_signature_path = getattr(args, "registry_signature", None)
    if registry_signature_path is not None:
        if registry_path is None:
            raise ValueError(
                "--registry-signature requires --key-registry"
            )
        registry_signature = _read_declared(registry_signature_path)
    revocation_signature = None
    revocation_signature_path = getattr(
        args, "revocation_signature", None
    )
    if revocation_signature_path is not None:
        if revocation_path is None:
            raise ValueError(
                "--revocation-signature requires --revocation-list"
            )
        revocation_signature = _read_declared(revocation_signature_path)
    if getattr(args, "registry_key", None) is not None and (
        registry_signature is None
    ):
        raise ValueError(
            "--registry-key requires --registry-signature"
        )
    if getattr(args, "revocation_key", None) is not None and (
        revocation_signature is None
    ):
        raise ValueError(
            "--revocation-key requires --revocation-signature"
        )
    return verify_signature_envelope(
        envelope,
        args.producer_key,
        getattr(args, "expected_subject", None),
        getattr(args, "expected_producer_key", None),
        revoked_keys,
        key_registry,
        getattr(args, "reference_time", None),
        getattr(args, "max_age_seconds", None),
        registry_signature,
        getattr(args, "registry_key", None),
        registry_digest,
        revocation_signature,
        getattr(args, "revocation_key", None),
                revocation_digest,
        revocation_list_meta,
        getattr(args, "min_revocation_version", None),
    )


def main_verify(args: argparse.Namespace | None = None) -> int:
    try:
        assert args is not None
        verification = run_verify(args)
        output_path = getattr(args, "output", None)
        text = json.dumps(verification, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"signature-verify: {exc}", file=sys.stderr)
        return 1
    return 0
