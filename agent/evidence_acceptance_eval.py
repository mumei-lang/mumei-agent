"""C11 Core-acceptance fold route: evaluate a Core acceptance descriptor.

`evidence-acceptance-eval` is a consumer route: it restores one declared
Core acceptance descriptor — `mumei.source-evidence-acceptance/v1`,
`mumei.native-evidence-acceptance/v1`, or a requirement-evaluated
verdict shape (`mumei.evidence-acceptance/v1`,
`mumei.evidence-list-acceptance/v1`,
`mumei.evidence-requirement-list-acceptance/v1`), emitted by the Core
`accept*` commands — and emits `mumei.core-acceptance-evaluation/v1`:
whether the document is a closed-shape member of the known descriptor
family (`descriptor_match`) and whether it is `accepted` (matching AND
the descriptor itself declared `accepted: true`, or
`verdict: "accepted"` on a verdict shape).

Representation-level evaluation only: the route performs no Core check,
no fresh query and no semantic evaluation — `checks_not_performed` names
what the fold leaves unassessed. With `--expected-fingerprint` the
caller declares the record pin an attempt binds to and the evaluation
emits `attempt_bound` — fingerprint equality against the descriptor's
`evidence_fingerprint`, representation-level only. Without it anonymous
descriptors bind no attempt, so `accepted: true` credits nothing to a
selected output; it only states some Core run accepted within its
declared scope. A malformed or foreign document fails statically rather
than matching nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.core_evidence import (
    MAX_ACCEPTANCE_DESCRIPTOR_BYTES,
    evaluate_core_acceptance,
)

# The conjunctive descriptor repeats per-requirement per-record check
# outcomes, so the read bound follows Core's 4 MiB acceptance-descriptor
# cap rather than the flat family's smaller envelope.
MAX_DESCRIPTOR_BYTES = MAX_ACCEPTANCE_DESCRIPTOR_BYTES


def build_eval_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--descriptor",
        required=True,
        metavar="PATH",
        help="Declared Core acceptance descriptor JSON "
        "(mumei.source-evidence-acceptance/v1, "
        "mumei.native-evidence-acceptance/v1, "
        "mumei.evidence-acceptance/v1, "
        "mumei.evidence-list-acceptance/v1 or "
        "mumei.evidence-requirement-list-acceptance/v1)."
    )
    parser.add_argument(
        "--expected-fingerprint",
        metavar="HEX",
        help="Declared record pin an attempt binds to (64-char lowercase "
        "SHA-256 hex of the record bytes, e.g. the evidence-check "
        "request's evidence.sha256). When supplied the evaluation emits "
        "attempt_bound comparing it to the descriptor's "
        "evidence_fingerprint.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the evaluation descriptor to PATH instead of stdout.",
    )


def _read_declared(path: str) -> dict:
    with open(path, "rb") as handle:
        data = handle.read(MAX_DESCRIPTOR_BYTES + 1)
    if len(data) > MAX_DESCRIPTOR_BYTES:
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
    descriptor = _read_declared(args.descriptor)
    output_path = getattr(args, "output", None)
    if output_path is not None:
        out_path = Path(output_path)
        try:
            if Path(args.descriptor).samefile(out_path):
                raise ValueError(
                    "--output may not overwrite a declared input document"
                )
        except FileNotFoundError:
            pass
    return evaluate_core_acceptance(
        descriptor, getattr(args, "expected_fingerprint", None)
    )


def main_eval(args: argparse.Namespace | None = None) -> int:
    try:
        assert args is not None
        evaluation = run_eval(args)
        output_path = getattr(args, "output", None)
        text = json.dumps(evaluation, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"evidence-acceptance-eval: {exc}", file=sys.stderr)
        return 1
    return 0
