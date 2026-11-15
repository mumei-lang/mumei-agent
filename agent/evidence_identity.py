"""C02 evidence file-identity route: declared source-binding comparison.

`evidence-identity-check` is a consumer route: it reads a declared
`mumei.verification-evidence/v1` record and a declared source file, then
emits `mumei.evidence-file-identity/v1` — whether the record's bound
`subject.sha256` still equals the sha256 of the current source bytes
(`identity: "match"`) or not (`identity: "mismatch"`).

This discharges the `file_identity` entry of the canonical
`checks_not_performed` vocabulary at representation level only: a match
means the saved record still binds THESE source bytes, never that the
record is valid, fresh-at-acceptance, authentic or true. Full record
representation validity stays Core's `evidence check` duty; the other
five semantic checks stay named in `checks_not_performed`. The route
performs no Core call, no fresh query and no I/O beyond its declared
inputs — a foreign or malformed record is a static error, not an answer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EVIDENCE_SCHEMA = "mumei.verification-evidence/v1"
DESCRIPTOR_SCHEMA = "mumei.evidence-file-identity/v1"
MAX_INPUT_BYTES = 65_536
_SUBJECT_KEYS = {"id", "kind", "sha256"}
_HEXDIGITS = frozenset("0123456789abcdef")


def build_identity_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--evidence",
        required=True,
        metavar="PATH",
        help=(
            "Declared verification-evidence record "
            "(mumei.verification-evidence/v1 JSON)."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        metavar="PATH",
        help="Declared source file the record is checked against.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the identity descriptor to PATH instead of stdout.",
    )


def _read_declared_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("declared input exceeds the bounded read limit")
    return data


def _read_evidence_subject(path: str) -> tuple[str, str]:
    data = _read_declared_bytes(path)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        # ValueError covers a malformed document and the integer-digit
        # conversion limit; RecursionError covers pathological nesting.
        # Both stay static errors, never a mismatch answer.
        raise ValueError("evidence document is not UTF-8 JSON") from exc
    if type(value) is not dict or value.get("schema_version") != EVIDENCE_SCHEMA:
        raise ValueError("evidence document is not mumei.verification-evidence/v1")
    subject = value.get("subject")
    if (
        type(subject) is not dict
        or set(subject.keys()) != _SUBJECT_KEYS
        or type(subject["id"]) is not str
        or not subject["id"]
        or type(subject["kind"]) is not str
        or type(subject["sha256"]) is not str
        or len(subject["sha256"]) != 64
        or not set(subject["sha256"]) <= _HEXDIGITS
    ):
        raise ValueError("evidence subject does not match the declared v1 shape")
    return subject["id"], subject["sha256"]


def _file_sha256(path: str) -> str:
    return hashlib.sha256(_read_declared_bytes(path)).hexdigest()


def compute_identity_descriptor(evidence_path: str, source_path: str) -> dict:
    """Compare a declared evidence record's bound source digest.

    Reads the record's `subject` (strict closed key set) and the source
    bytes under the bounded read, then returns the
    `mumei.evidence-file-identity/v1` descriptor — `identity` is
    `"match"` when the record's `subject.sha256` equals the current
    source digest, `"mismatch"` otherwise. Raises `ValueError`/`OSError`
    on any malformed or unreadable declared input; callers treat those
    as static errors, never as a mismatch answer.
    """
    subject_id, subject_sha256 = _read_evidence_subject(evidence_path)
    source_sha256 = _file_sha256(source_path)
    return {
        "schema_version": DESCRIPTOR_SCHEMA,
        "evidence_schema_version": EVIDENCE_SCHEMA,
        "subject_id": subject_id,
        "subject_sha256": subject_sha256,
        "source_sha256": source_sha256,
        "identity": "match" if subject_sha256 == source_sha256 else "mismatch",
        "checks_not_performed": [
            "claim_truth",
            "freshness",
            "producer_authenticity",
            "semantic_correspondence",
            "artifact_semantics",
        ],
    }


def main_identity(args: argparse.Namespace | None = None) -> int:
    try:
        output_path = getattr(args, "output", None)
        if output_path is not None:
            out_path = Path(output_path)
            for declared in (Path(args.evidence), Path(args.source)):
                try:
                    if declared.samefile(out_path):
                        raise ValueError(
                            "--output may not overwrite a declared "
                            "input document"
                        )
                except FileNotFoundError:
                    continue
        descriptor = compute_identity_descriptor(args.evidence, args.source)
        text = json.dumps(descriptor, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"evidence-identity-check: {exc}", file=sys.stderr)
        return 1
    return 0
