"""C11 unperformed-check recovery route: fold a record's declared
``checks_not_performed`` over supporting evaluation documents.

`recovery-eval` restores one declared JSON record — any document that
may carry an optional ``checks_not_performed`` string list — plus one
or more supporting evaluation documents (`--evidence`, repeatable),
and emits `mumei.unperformed-check-recovery/v1`: for each declared
check, ``recovered`` / ``evidence_failed`` / ``no_evidence`` under the
declared performer table in `agent.core_evidence`.

The composition is representation-level only: the fold never re-runs
a check (`recovery_enforcement` stays), never verifies the supporting
documents (`evidence_authenticity` stays — they are trusted as
declared) and never binds a document to the record it is said to
cover (`evidence_binding` stays). A malformed or non-object input
fails statically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from agent.core_evidence import evaluate_unperformed_check_recovery

MAX_DOCUMENT_BYTES = 1024 * 1024


def build_eval_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--record",
        required=True,
        metavar="PATH",
        help="Declared record JSON that may carry an optional "
        "checks_not_performed string list.",
    )
    parser.add_argument(
        "--evidence",
        action="append",
        required=True,
        metavar="PATH",
        help="Supporting evaluation document JSON; repeatable. Each "
        "document is counted only when its schema_version names the "
        "declared performer for a check.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the recovery descriptor to PATH instead of stdout.",
    )


def _read_declared_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("declared document exceeds the bounded read limit")
    return data


def _parse_declared(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("declared document is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ValueError("declared document must be a JSON object")
    return value


def _read_declared(path: str) -> dict:
    return _parse_declared(_read_declared_bytes(path))


def main_eval(args: argparse.Namespace | None = None) -> int:
    try:
        record_bytes = _read_declared_bytes(args.record)
        record = _parse_declared(record_bytes)
        # SHA-256 of the record's raw bytes — the digest a bound
        # binding document must pin to count toward `evidence_binding`.
        record_digest = hashlib.sha256(record_bytes).hexdigest()
        evidence_paths = list(args.evidence)
        output_path = getattr(args, "output", None)
        if output_path is not None:
            out_path = Path(output_path)
            for declared in [args.record, *evidence_paths]:
                try:
                    if Path(declared).samefile(out_path):
                        raise ValueError(
                            "--output may not overwrite a declared input "
                            "document"
                        )
                except FileNotFoundError:
                    pass
        evidence = [_read_declared(path) for path in evidence_paths]
        recovery = evaluate_unperformed_check_recovery(
            record, evidence, record_digest=record_digest
        )
        text = json.dumps(recovery, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"recovery-eval: {exc}", file=sys.stderr)
        return 1
    return 0
