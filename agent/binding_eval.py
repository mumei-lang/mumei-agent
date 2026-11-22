"""C11 evidence-binding route: pin a declared subject-bearing document
to the record bytes it is said to cover.

`binding-eval` reads one record's raw bytes (never parsed — any bounded
document binds the same way) plus one declared JSON document carrying a
subject digest, and emits `mumei.evidence-binding/v1`: the recomputed
`record_digest` (SHA-256 of the bytes), whether the document's declared
schema is a subject-bearing carrier (`carrier_match`), whether its
subject field is a well-formed digest (`subject_declared`), and whether
the declared digest equals the record's (`bound`).

The fold derives the digest itself — no caller-declared fingerprint is
trusted. The document is still trusted as declared: `carrier_authenticity`
(its own checks and signature are unverified) and `binding_enforcement`
(the report is an observation; gating is a host decision) stay in
`checks_not_performed`. A malformed or non-object evidence document
fails statically; a mismatched subject reports `bound: false`, never an
error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.core_evidence import (
    MAX_ACCEPTANCE_DESCRIPTOR_BYTES,
    evaluate_evidence_binding,
)

# The conjunctive acceptance descriptor — a subject-bearing carrier —
# repeats per-requirement per-record outcomes, so the document bound
# follows Core's 4 MiB acceptance-descriptor cap.
MAX_DOCUMENT_BYTES = MAX_ACCEPTANCE_DESCRIPTOR_BYTES


def build_eval_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--record",
        required=True,
        metavar="PATH",
        help="Record file whose raw bytes the document should cover. "
        "The bytes are hashed, never parsed.",
    )
    parser.add_argument(
        "--evidence",
        required=True,
        metavar="PATH",
        help="Declared JSON document carrying a subject digest — a "
        "producer-signature envelope, a Core acceptance descriptor, or "
        "a recheck diagnostic.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the binding descriptor to PATH instead of stdout.",
    )


def _read_record(path: str) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("record exceeds the bounded read limit")
    return data


def _read_declared(path: str) -> dict:
    with open(path, "rb") as handle:
        data = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("declared document exceeds the bounded read limit")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        # ValueError covers a malformed document and the integer-digit
        # conversion limit; RecursionError covers pathological nesting.
        raise ValueError("declared document is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ValueError("declared document must be a JSON object")
    return value


def run_eval(args: argparse.Namespace) -> dict:
    record = _read_record(args.record)
    document = _read_declared(args.evidence)
    output_path = getattr(args, "output", None)
    if output_path is not None:
        out_path = Path(output_path)
        try:
            if Path(args.record).samefile(out_path) or Path(
                args.evidence
            ).samefile(out_path):
                raise ValueError(
                    "--output may not overwrite a declared input document"
                )
        except FileNotFoundError:
            pass
    return evaluate_evidence_binding(record, document)


def main_eval(args: argparse.Namespace | None = None) -> int:
    try:
        assert args is not None
        binding = run_eval(args)
        output_path = getattr(args, "output", None)
        text = json.dumps(binding, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"binding-eval: {exc}", file=sys.stderr)
        return 1
    return 0
