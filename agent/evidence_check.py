"""C02 evidence-check acceptance route: evaluate a declared check record.

`evidence-check-accept` is a consumer route: it restores a declared
attempt-sequence snapshot (`mumei.verifier-attempt-sequence/v1`) and a
declared evidence-check record (`mumei.verifier-evidence-check/v1`),
then emits `mumei.evidence-check-acceptance/v1` — whether the record
binds the sequence's CURRENT evidence candidate (`candidate_match`) and
whether it is `accepted` (current AND declared `outcome: "valid"`).

Representation-level acceptance only: the route performs no Core check,
no fresh query and no semantic evaluation — `checks_not_performed` in
the descriptor names what stays unassessed. Producing a check record
requires a live Core run against the selected output bytes and stays
in-library (`agent.core_evidence.record_evidence_check`); a host cannot
forge acceptance here because a stale or foreign record always yields
`accepted: false`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.core_evidence import evaluate_evidence_check
from agent.verification_attempt import (
    AttemptEvidenceCheck,
    AttemptSequence,
)

MAX_SNAPSHOT_BYTES = 1024 * 1024


def build_accept_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sequence",
        required=True,
        metavar="PATH",
        help="Declared attempt-sequence snapshot (mumei.verifier-attempt-sequence/v1 JSON).",
    )
    parser.add_argument(
        "--check",
        required=True,
        metavar="PATH",
        help="Declared evidence-check record (mumei.verifier-evidence-check/v1 JSON).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the acceptance descriptor to PATH instead of stdout.",
    )


def _read_declared(path: str) -> dict:
    with open(path, "rb") as handle:
        data = handle.read(MAX_SNAPSHOT_BYTES + 1)
    if len(data) > MAX_SNAPSHOT_BYTES:
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


def main_accept(args: argparse.Namespace | None = None) -> int:
    try:
        sequence = AttemptSequence.from_dict(_read_declared(args.sequence))
        check = AttemptEvidenceCheck.from_dict(_read_declared(args.check))
        output_path = getattr(args, "output", None)
        if output_path is not None:
            out_path = Path(output_path)
            for declared in (Path(args.sequence), Path(args.check)):
                try:
                    if declared.samefile(out_path):
                        raise ValueError(
                            "--output may not overwrite a declared "
                            "input document"
                        )
                except FileNotFoundError:
                    continue
        acceptance = evaluate_evidence_check(sequence, check)
        text = json.dumps(acceptance, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"evidence-check-accept: {exc}", file=sys.stderr)
        return 1
    return 0
