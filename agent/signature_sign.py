"""C02/C11 producer-signature route: sign a declared record's digest
into a detached `mumei.producer-signature/v1` envelope.

`signature-sign` is the producing half of the producer-authenticity
lane `signature-verify` verifies: it reads one declared record,
SHA-256s its raw bytes (the `subject_digest` a consumer reproduces
with `sha256sum`), signs the digest's lowercase-hex ASCII bytes under
a declared 32-byte ed25519 secret key — the 64-char lowercase-hex
shape `mumei evidence keygen --secret-file` writes — and emits the
closed five-field envelope `evaluate_signature_envelope` and
`verify_signature_envelope` already consume.

Secret handling follows the AGENTS.md output-surface rules: the key
material is a declared input, read from `--key-file` only, and never
appears in the emitted envelope, error text, logs or test artifacts.
The `producer_key_id` carried in the envelope is a declared label the
consumer pins separately (`--expected-producer-key` on the verify
side) — not an attested identity, so `key_authenticity`,
`envelope_freshness` and `key_revocation` stay unperformed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.core_evidence import sign_producer_record

# The record's raw bytes are hashed, not canonicalized — the same
# 64 KiB bound the Core `evidence sign` route applies to its input.
MAX_RECORD_BYTES = 65536
# The key file is exactly 64 ASCII bytes; a small bound keeps the read
# finite without admitting surrounding whitespace or prefixes.
MAX_KEY_FILE_BYTES = 256


def build_sign_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--record",
        required=True,
        metavar="PATH",
        help="Declared record whose raw bytes are SHA-256'd into the "
        "envelope's subject_digest.",
    )
    parser.add_argument(
        "--key-file",
        required=True,
        metavar="PATH",
        help="File holding the 64-char lowercase-hex ed25519 secret "
        "key (the shape `mumei evidence keygen --secret-file` "
        "writes). The key material is never printed or emitted.",
    )
    parser.add_argument(
        "--producer-key-id",
        required=True,
        metavar="ID",
        help="Declared producer key id carried in the envelope — a "
        "label the consumer pins separately via "
        "--expected-producer-key, not an attested identity.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the signature envelope to PATH instead of stdout.",
    )


def _read_record(path: str) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError("declared record exceeds the bounded read limit")
    return data


def _read_secret_key(path: str) -> str:
    with open(path, "rb") as handle:
        data = handle.read(MAX_KEY_FILE_BYTES + 1)
    if len(data) > MAX_KEY_FILE_BYTES:
        raise ValueError("invalid producer key material")
    try:
        return data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid producer key material") from exc


def main_sign(args: argparse.Namespace | None = None) -> int:
    try:
        output_path = getattr(args, "output", None)
        if output_path is not None:
            out_path = Path(output_path)
            for declared in (args.record, args.key_file):
                try:
                    if Path(declared).samefile(out_path):
                        raise ValueError(
                            "--output may not overwrite a declared "
                            "input document"
                        )
                except FileNotFoundError:
                    pass
        record = _read_record(args.record)
        secret_key = _read_secret_key(args.key_file)
        envelope = sign_producer_record(
            record, secret_key, args.producer_key_id
        )
        text = json.dumps(envelope, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"signature-sign: {exc}", file=sys.stderr)
        return 1
    return 0
