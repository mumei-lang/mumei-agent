"""C02 evidence comparison route: declared record-vs-record claims.

`evidence-compare` is a consumer route: it reads two declared
`mumei.verification-evidence/v1` records and emits
`mumei.evidence-comparison/v1` — whether the records bind the same
`subject` and the same `specification` claim set, at representation
level (`subject_match`, `specification_match`, `claims_match`).

This is the record-vs-record companion of `evidence-identity-check`
(record vs current source bytes) and `verify-recheck` (record vs a
fresh Core query): it detects whether two saved records carry the
same claims without running Core at all. A match never means the
claims are true, fresh-at-acceptance or authentic — the full
`checks_not_performed` vocabulary stays named. The route performs no
Core call and no I/O beyond its declared inputs; a malformed record
is a static error, not an answer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.evidence_identity import (
    EVIDENCE_SCHEMA,
    MAX_INPUT_BYTES,
    _SUBJECT_KEYS,
)

DESCRIPTOR_SCHEMA = "mumei.evidence-comparison/v1"
_HEXDIGITS = frozenset("0123456789abcdef")


def build_compare_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--evidence-a",
        required=True,
        metavar="PATH",
        help=(
            "First declared verification-evidence record "
            "(mumei.verification-evidence/v1 JSON)."
        ),
    )
    parser.add_argument(
        "--evidence-b",
        required=True,
        metavar="PATH",
        help=(
            "Second declared verification-evidence record "
            "(mumei.verification-evidence/v1 JSON)."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the comparison descriptor to PATH instead of stdout.",
    )


def _read_evidence(path: str) -> dict:
    with open(path, "rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("declared input exceeds the bounded read limit")
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
    if "specification" not in value or type(value["specification"]) is not dict:
        raise ValueError("evidence specification does not match the declared v1 shape")
    return value


def compute_comparison_descriptor(evidence_a_path: str, evidence_b_path: str) -> dict:
    """Compare two declared evidence records' claim surfaces.

    Reads both records under the bounded read and the strict v1 shape
    checks, then returns the `mumei.evidence-comparison/v1` descriptor:
    `subject_match` compares the bound `subject` objects verbatim,
    `specification_match` compares the `specification` claim objects
    verbatim, and `claims_match` holds only when both match. Raises
    `ValueError`/`OSError` on any malformed or unreadable declared
    input; callers treat those as static errors, never as a mismatch
    answer.
    """
    record_a = _read_evidence(evidence_a_path)
    record_b = _read_evidence(evidence_b_path)
    subject_match = record_a["subject"] == record_b["subject"]
    specification_match = record_a["specification"] == record_b["specification"]
    return {
        "schema_version": DESCRIPTOR_SCHEMA,
        "evidence_schema_version": EVIDENCE_SCHEMA,
        "subject_match": subject_match,
        "specification_match": specification_match,
        "claims_match": subject_match and specification_match,
        "checks_not_performed": [
            "claim_truth",
            "file_identity",
            "freshness",
            "producer_authenticity",
            "semantic_correspondence",
            "artifact_semantics",
        ],
    }


def main_compare(args: argparse.Namespace | None = None) -> int:
    try:
        output_path = getattr(args, "output", None)
        if output_path is not None:
            out_path = Path(output_path)
            for declared in (Path(args.evidence_a), Path(args.evidence_b)):
                try:
                    if declared.samefile(out_path):
                        raise ValueError(
                            "--output may not overwrite a declared "
                            "input document"
                        )
                except FileNotFoundError:
                    continue
        descriptor = compute_comparison_descriptor(
            args.evidence_a, args.evidence_b
        )
        text = json.dumps(descriptor, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"evidence-compare: {exc}", file=sys.stderr)
        return 1
    return 0
