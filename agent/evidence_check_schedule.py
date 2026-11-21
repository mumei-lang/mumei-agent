"""C11 evidence-check-schedule route: static attempt-schedule representation.

`python -m agent evidence-check-schedule` feeds a saved schedule's bytes to
`<core> evidence check-schedule --stdin --json` inside the C11 dispatch
lifecycle. The request fingerprint binds the Core executable and the exact
schedule bytes fed to one reserved attempt; the route then re-hashes both
declared inputs and publishes reconciled lineage compare-and-set.

Selection requires Core's exact representation-only diagnostic and a valid
schedule outcome/count. `selected` names only a manifest-declared-success
exit; it is not an Evidence acceptance, verification verdict, or grade
promotion. The route makes no claim about adapter execution, truth of its
self-report, Evidence acceptance, freshness, or resource enforcement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from agent.attempt_schedule import MAX_SCHEDULE_ATTEMPTS, SCHEDULE_OUTCOMES
from agent.core_evidence import MAX_CHECK_TIMEOUT_MS

CHECK_REQUEST_PROFILE = "mumei.evidence-check-schedule-request/v1"
CHECK_REPORT_PROFILE = "mumei.evidence-check-schedule-report/v1"
MAX_INPUT_BYTES = 65_536
DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000

CHECKS_PERFORMED = ["representation_gate", "schedule_consistency"]
CHECKS_NOT_PERFORMED = [
    "adapter_execution",
    "reported_outcome_truth",
    "evidence_acceptance",
    "embedded_acceptance_validation",
    "claim_truth",
    "producer_authenticity",
    "freshness",
    "resource_enforcement",
    "grade_promotion",
]
DIAGNOSTIC_KEYS = frozenset(
    {
        "schema_version",
        "schedule_schema_version",
        "representation",
        "acceptance",
        "outcome",
        "attempt_count",
        "reported_outcome_meaning",
        "checks_performed",
        "checks_not_performed",
    }
)


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_request(args: argparse.Namespace) -> None:
    """Validate declared paths and bounds before dispatch."""
    if os.name != "posix":
        raise ValueError("evidence-check-schedule requires a POSIX host")
    for name, path in (("--core", args.core), ("--schedule", args.schedule)):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    if not 1 <= args.attempt_timeout <= MAX_CHECK_TIMEOUT_MS:
        raise ValueError(f"--attempt-timeout must be 1..{MAX_CHECK_TIMEOUT_MS} ms")
    for name, path in (("Core executable", args.core), ("schedule", args.schedule)):
        try:
            mode = Path(path).stat().st_mode
        except OSError as exc:
            raise ValueError(f"cannot read declared {name}: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ValueError(f"declared {name} must be a regular file")
    try:
        size = os.path.getsize(args.schedule)
    except OSError as exc:
        raise ValueError(f"cannot read declared schedule: {exc}") from exc
    if size > MAX_INPUT_BYTES:
        raise ValueError(
            f"--schedule exceeds the Core input bound ({MAX_INPUT_BYTES} bytes)"
        )
    if args.output is not None:
        out_path = Path(args.output)
        for declared in (args.core, args.schedule):
            try:
                if out_path.samefile(declared):
                    raise ValueError(
                        "--output may not overwrite a declared input document"
                    )
            except FileNotFoundError:
                continue


def _attempt_fingerprint(args: argparse.Namespace, schedule_bytes: bytes) -> str:
    """Bind Core bytes and the exact schedule bytes fed to the check."""
    request = {
        "schema_version": CHECK_REQUEST_PROFILE,
        "core": _file_sha256(args.core),
        "schedule": {
            "path": args.schedule,
            "sha256": hashlib.sha256(schedule_bytes).hexdigest(),
        },
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_diagnostic(captured: bytes) -> dict | None:
    """Accept only the exact static diagnostic contract from Core."""
    try:
        document = json.loads(captured.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if type(document) is not dict or set(document) != DIAGNOSTIC_KEYS:
        return None
    expected = {
        "schema_version": "mumei.attempt-schedule-check/v1",
        "schedule_schema_version": "mumei.attempt-schedule/v1",
        "representation": "valid",
        "acceptance": "not_evaluated",
        "reported_outcome_meaning": "adapter_self_report",
        "checks_performed": CHECKS_PERFORMED,
        "checks_not_performed": CHECKS_NOT_PERFORMED,
    }
    if any(document.get(key) != value for key, value in expected.items()):
        return None
    outcome = document.get("outcome")
    if type(outcome) is not str or outcome not in SCHEDULE_OUTCOMES:
        return None
    attempt_count = document.get("attempt_count")
    if (
        type(attempt_count) is not int
        or not 0 <= attempt_count <= MAX_SCHEDULE_ATTEMPTS
    ):
        return None
    return document


def build_check_schedule_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="evidence-check-schedule")
    parser.description = (
        "Run a declared Core attempt-schedule representation check as "
        "one attempt and emit the reconciled lineage plus the declared "
        "schedule outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`evidence check-schedule`."
        ),
    )
    parser.add_argument(
        "--schedule",
        required=True,
        metavar="PATH",
        help=(
            "Declared saved mumei.attempt-schedule/v1 document "
            "(absolute regular-file path, at most 65536 bytes); its "
            "bytes are fed to the check on stdin."
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


def run_check_schedule(args: argparse.Namespace) -> dict:
    """Run one declared Core schedule check and return its report."""
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    _check_request(args)
    schedule_bytes = Path(args.schedule).read_bytes()
    fingerprint = _attempt_fingerprint(args, schedule_bytes)
    argv = (
        args.core,
        "evidence",
        "check-schedule",
        "--stdin",
        "--json",
    )
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        argv,
        memory_bound_mb=args.memory_bound_mb,
        feed_bytes=schedule_bytes,
    )
    try:
        inputs_changed = (
            _attempt_fingerprint(args, Path(args.schedule).read_bytes()) != fingerprint
        )
    except OSError:
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    diagnostic = (
        _parse_diagnostic(dispatch.run.stdout)
        if exit_code == 0 and not inputs_changed
        else None
    )
    if exit_code == 0 and not inputs_changed and diagnostic is not None:
        updated = dispatch.sequence.select_result(dispatch.captured_output())
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": CHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif diagnostic is not None:
        report["representation"] = diagnostic["representation"]
        report["acceptance"] = diagnostic["acceptance"]
        report["schedule_outcome"] = diagnostic["outcome"]
        report["attempt_count"] = diagnostic["attempt_count"]
        report["reported_outcome_meaning"] = diagnostic["reported_outcome_meaning"]
        report["checks_performed"] = list(diagnostic["checks_performed"])
        report["checks_not_performed"] = list(diagnostic["checks_not_performed"])
    if published.selected_result is not None:
        report["candidate"] = published.evidence_candidate().to_dict()
    return report


def main_check_schedule(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_check_schedule_parser().parse_args()
    try:
        report = run_check_schedule(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"evidence-check-schedule: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
