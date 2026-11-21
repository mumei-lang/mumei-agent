"""C02/C11 freshness fold route: evaluate a declared record's
``produced_at`` claim against a declared clock.

`freshness-eval` restores one declared JSON record — any producer
document that may carry an optional ``produced_at`` RFC 3339
timestamp — and emits `mumei.freshness-evaluation/v1`: whether the
record makes a well-formed freshness claim (`freshness_claimed`) and
whether the declared timestamp stays within the caller's window
(`within_window`: ``produced_at <= reference_time`` and
``produced_at + max_age_seconds >= reference_time``).

The clock is declared, never read: `--reference-time` is the caller's
own trusted reference and `--max-age-seconds` its window — two runs
over the same documents always agree. The fold reports observations
only: `clock_authenticity`, `producer_time_authenticity` and
`freshness_enforcement` stay in `checks_not_performed` — the declared
clock and the producer's timestamp are both trusted as claimed, and
gating on freshness is a host decision. A malformed or non-object
document fails statically.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.core_evidence import evaluate_freshness

MAX_RECORD_BYTES = 1024 * 1024


def build_eval_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--record",
        required=True,
        metavar="PATH",
        help="Declared producer record JSON that may carry an "
        "optional produced_at RFC 3339 timestamp.",
    )
    parser.add_argument(
        "--reference-time",
        required=True,
        metavar="RFC3339",
        help="The caller's declared reference time (RFC 3339 with "
        "timezone, e.g. 2026-11-18T00:00:00Z). The fold never reads "
        "the system clock.",
    )
    parser.add_argument(
        "--max-age-seconds",
        required=True,
        type=int,
        metavar="N",
        help="Declared freshness window: produced_at must be no "
        "older than reference_time minus N seconds.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the evaluation descriptor to PATH instead of stdout.",
    )


def _read_declared(path: str) -> dict:
    with open(path, "rb") as handle:
        data = handle.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
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
    record = _read_declared(args.record)
    output_path = getattr(args, "output", None)
    if output_path is not None:
        out_path = Path(output_path)
        try:
            if Path(args.record).samefile(out_path):
                raise ValueError(
                    "--output may not overwrite a declared input document"
                )
        except FileNotFoundError:
            pass
    return evaluate_freshness(
        record,
        args.reference_time,
        args.max_age_seconds,
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
        print(f"freshness-eval: {exc}", file=sys.stderr)
        return 1
    return 0
