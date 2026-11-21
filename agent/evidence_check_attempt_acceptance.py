"""C11 consumer for Core's evidence-check acceptance representation diagnostic.

`evidence-check-attempt-acceptance` feeds a saved acceptance's bytes to
`evidence check-attempt-acceptance --stdin --json` as one declared attempt.
It reports only Core's static representation and producer-consistency fields.
The producer's `accepted` binding is not Core Evidence acceptance, and
`candidate_match` is not rechecked. There is no Core check rerun, claim-truth,
producer-authenticity, freshness, or grade-promotion claim. Selection means
only that Core validated the representation and its producer consistency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from agent.core_evidence import MAX_CHECK_TIMEOUT_MS

CHECK_ATTEMPT_ACCEPTANCE_REQUEST_PROFILE = (
    "mumei.evidence-check-attempt-acceptance-request/v1"
)
CHECK_ATTEMPT_ACCEPTANCE_REPORT_PROFILE = (
    "mumei.evidence-check-attempt-acceptance-report/v1"
)
ACCEPTANCE_SCHEMA_VERSION = "mumei.evidence-check-acceptance/v1"
DIAGNOSTIC_SCHEMA_VERSION = "mumei.evidence-check-acceptance-check/v1"
MAX_INPUT_BYTES = 65_536
DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000

DECLARED_OUTCOMES = frozenset(
    {"valid", "failed", "cancelled", "accepted", "rejected", "inconclusive"}
)
DECLARED_FIELD_MEANING = {
    "outcome": "declared_core_check_outcome",
    "candidate_match": "producer_computed_not_rechecked",
    "accepted": "producer_representation_binding_not_core_acceptance",
}
CHECKS_PERFORMED = ["representation_gate", "acceptance_consistency"]
CHECKS_NOT_PERFORMED = [
    "candidate_match_recheck",
    "core_check_rerun",
    "evidence_acceptance",
    "claim_truth",
    "producer_authenticity",
    "freshness",
    "grade_promotion",
]
DIAGNOSTIC_KEYS = frozenset(
    {
        "schema_version",
        "acceptance_schema_version",
        "representation",
        "acceptance",
        "declared_outcome",
        "requirement_fingerprint",
        "declared_field_meaning",
        "checks_performed",
        "checks_not_performed",
    }
)


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _check_request(args: argparse.Namespace) -> None:
    """Validate declared paths and bounds before dispatch."""
    if os.name != "posix":
        raise ValueError(
            "evidence-check-attempt-acceptance requires a POSIX host"
        )
    for name, path in (
        ("--core", args.core),
        ("--acceptance", args.acceptance),
    ):
        if (
            type(path) is not str
            or not os.path.isabs(path)
            or "\x00" in path
        ):
            raise ValueError(f"{name} must be an absolute path")
    if (
        type(args.attempt_timeout) is not int
        or not 1 <= args.attempt_timeout <= MAX_CHECK_TIMEOUT_MS
    ):
        raise ValueError(
            f"--attempt-timeout must be 1..{MAX_CHECK_TIMEOUT_MS} ms"
        )
    for name, path in (
        ("Core executable", args.core),
        ("acceptance", args.acceptance),
    ):
        try:
            mode = Path(path).stat().st_mode
        except OSError as exc:
            raise ValueError(f"cannot read declared {name}: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ValueError(f"declared {name} must be a regular file")
    try:
        size = os.path.getsize(args.acceptance)
    except OSError as exc:
        raise ValueError(f"cannot read declared acceptance: {exc}") from exc
    if size > MAX_INPUT_BYTES:
        raise ValueError(
            f"--acceptance exceeds the Core input bound ({MAX_INPUT_BYTES} bytes)"
        )
    if args.output is not None:
        out_path = Path(args.output)
        for declared in (args.core, args.acceptance):
            try:
                if out_path.samefile(declared):
                    raise ValueError(
                        "--output may not overwrite a declared input document"
                    )
            except FileNotFoundError:
                continue


def _attempt_fingerprint(
    args: argparse.Namespace, acceptance_bytes: bytes
) -> str:
    """Bind the Core executable and exact acceptance bytes fed to Core."""
    request = {
        "schema_version": CHECK_ATTEMPT_ACCEPTANCE_REQUEST_PROFILE,
        "core": _file_sha256(args.core),
        "acceptance": {
            "path": args.acceptance,
            "sha256": hashlib.sha256(acceptance_bytes).hexdigest(),
        },
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_local_acceptance(acceptance_bytes: bytes) -> dict | None:
    try:
        document = json.loads(
            acceptance_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return document if type(document) is dict else None


def _parse_diagnostic(
    captured: bytes, acceptance_bytes: bytes
) -> dict | None:
    """Accept only Core's exact diagnostic and local declared-field agreement."""
    try:
        document = json.loads(
            captured.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if type(document) is not dict or set(document) != DIAGNOSTIC_KEYS:
        return None
    expected = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "acceptance_schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "representation": "valid",
        "acceptance": "not_evaluated",
        "declared_field_meaning": DECLARED_FIELD_MEANING,
        "checks_performed": CHECKS_PERFORMED,
        "checks_not_performed": CHECKS_NOT_PERFORMED,
    }
    if any(document.get(key) != value for key, value in expected.items()):
        return None
    declared_outcome = document.get("declared_outcome")
    if (
        type(declared_outcome) is not str
        or declared_outcome not in DECLARED_OUTCOMES
    ):
        return None
    requirement_fingerprint = document.get("requirement_fingerprint")
    if (
        type(requirement_fingerprint) is not str
        or requirement_fingerprint not in {"declared", "absent"}
    ):
        return None
    local = _parse_local_acceptance(acceptance_bytes)
    if local is None or type(local.get("outcome")) is not str:
        return None
    if local["outcome"] != declared_outcome:
        return None
    if ("requirement_fingerprint" in local) != (
        requirement_fingerprint == "declared"
    ):
        return None
    return document


def build_check_attempt_acceptance_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(
            prog="evidence-check-attempt-acceptance"
        )
    parser.description = (
        "Check only static representation and producer consistency for a "
        "saved evidence-check acceptance. The producer's accepted binding "
        "is not Core Evidence acceptance; candidate_match is not rechecked. "
        "No Core check rerun, claim truth, producer authenticity, freshness, "
        "or grade promotion."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help="Declared Core executable (absolute path).",
    )
    parser.add_argument(
        "--acceptance",
        required=True,
        metavar="PATH",
        help=(
            "Declared saved mumei.evidence-check-acceptance/v1 document "
            "(absolute regular-file path, at most 65536 bytes); its bytes "
            "are fed to Core on stdin."
        ),
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        default=DEFAULT_ATTEMPT_TIMEOUT_MS,
        metavar="<MS>",
        help=f"Declared attempt bound in ms (max {MAX_CHECK_TIMEOUT_MS}).",
    )
    parser.add_argument(
        "--memory-bound-mb",
        type=int,
        default=None,
        metavar="<MB>",
        help=(
            "Optional declared POSIX RLIMIT_AS ceiling applied to the "
            "attempt child's whole address space."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the check report JSON here instead of stdout.",
    )
    return parser


def run_check_attempt_acceptance(args: argparse.Namespace) -> dict:
    """Run one Core acceptance-representation check and return its report."""
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    _check_request(args)
    acceptance_bytes = Path(args.acceptance).read_bytes()
    if len(acceptance_bytes) > MAX_INPUT_BYTES:
        raise ValueError(
            f"--acceptance exceeds the Core input bound ({MAX_INPUT_BYTES} bytes)"
        )
    fingerprint = _attempt_fingerprint(args, acceptance_bytes)
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        (
            args.core,
            "evidence",
            "check-attempt-acceptance",
            "--stdin",
            "--json",
        ),
        memory_bound_mb=args.memory_bound_mb,
        feed_bytes=acceptance_bytes,
    )
    try:
        current_bytes = Path(args.acceptance).read_bytes()
        inputs_changed = (
            len(current_bytes) > MAX_INPUT_BYTES
            or _attempt_fingerprint(args, current_bytes) != fingerprint
        )
    except (OSError, ValueError):
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    diagnostic = (
        _parse_diagnostic(dispatch.run.stdout, acceptance_bytes)
        if exit_code == 0 and not inputs_changed
        else None
    )
    if exit_code == 0 and not inputs_changed and diagnostic is not None:
        updated = dispatch.sequence.select_result(dispatch.captured_output())
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": CHECK_ATTEMPT_ACCEPTANCE_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif diagnostic is not None:
        report["representation"] = diagnostic["representation"]
        report["declared_outcome"] = diagnostic["declared_outcome"]
        report["requirement_fingerprint"] = diagnostic[
            "requirement_fingerprint"
        ]
        report["checks_performed"] = list(diagnostic["checks_performed"])
        report["checks_not_performed"] = list(
            diagnostic["checks_not_performed"]
        )
    if published.selected_result is not None:
        report["candidate"] = published.evidence_candidate().to_dict()
    return report


def main_check_attempt_acceptance(
    args: argparse.Namespace | None = None,
) -> int:
    if args is None:
        args = build_check_attempt_acceptance_parser().parse_args()
    try:
        report = run_check_attempt_acceptance(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"evidence-check-attempt-acceptance: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
