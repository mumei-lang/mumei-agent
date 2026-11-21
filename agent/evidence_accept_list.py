"""C11 Core consumer for requirement-normalized Evidence-list acceptance.

The declared request is fingerprinted, the list-envelope bytes are fed to
`evidence accept-list` through one reserved attempt, and all declared inputs
are re-hashed before any verdict is reported. A verdict is Core's
declared-requirement normalization over representation plus cross-record pin
agreement; it does not establish claim truth, producer authenticity,
freshness, tool execution, or grade promotion. Selection is a
declared-success exit, not a grade promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.core_evidence import MAX_CHECK_TIMEOUT_MS

ACCEPT_LIST_REQUEST_PROFILE = "mumei.evidence-accept-list-request/v1"
ACCEPT_LIST_REPORT_PROFILE = "mumei.evidence-accept-list-report/v1"

LIST_SCHEMA_VERSION = "mumei.verification-evidence-list/v1"
REQUIREMENT_SCHEMA_VERSION = "mumei.evidence-requirement/v1"
REQUIREMENT_LIST_SCHEMA_VERSION = "mumei.evidence-requirement-list/v1"
SINGLE_ACCEPTANCE_SCHEMA = "mumei.evidence-list-acceptance/v1"
CONJUNCTIVE_ACCEPTANCE_SCHEMA = (
    "mumei.evidence-requirement-list-acceptance/v1"
)

MAX_INPUT_BYTES = 65_536
DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000
_VERDICT_EXIT_CODES = {"accepted": 0, "rejected": 1, "inconclusive": 3}
_UNPERFORMED_CHECKS = {
    "grade_promotion",
    "producer_authenticity",
    "claim_truth",
}
_SINGLE_DESCRIPTOR_KEYS = {
    "schema_version",
    "evidence_schema_version",
    "requirement_schema_version",
    "requirement_fingerprint",
    "list_fingerprint",
    "acceptance",
    "verdict",
    "consistent",
    "conflict_count",
    "conflicts",
    "records_evaluated",
    "records",
    "checks_performed",
    "checks_not_performed",
}
_CONJUNCTIVE_DESCRIPTOR_KEYS = {
    "schema_version",
    "evidence_schema_version",
    "requirement_schema_version",
    "requirement_list_fingerprint",
    "list_fingerprint",
    "acceptance",
    "verdict",
    "consistent",
    "conflict_count",
    "conflicts",
    "requirements_evaluated",
    "records_evaluated",
    "requirements",
    "checks_performed",
    "checks_not_performed",
}


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _requirement_declaration(args: argparse.Namespace) -> tuple[str, str]:
    requirement = getattr(args, "requirement", None)
    requirement_list = getattr(args, "requirement_list", None)
    if (requirement is None) == (requirement_list is None):
        raise ValueError(
            "exactly one of --requirement or --requirement-list is required"
        )
    if requirement is not None:
        return "requirement", requirement
    return "requirement-list", requirement_list


def _check_request(args: argparse.Namespace) -> None:
    """Reject static request errors before dispatching an attempt."""
    if os.name != "posix":
        raise ValueError("evidence-accept-list requires a POSIX host")
    mode, requirement_path = _requirement_declaration(args)
    declared = [
        ("--core", args.core),
        ("--list", args.list_path),
        (
            "--requirement" if mode == "requirement" else "--requirement-list",
            requirement_path,
        ),
    ]
    for name, path in declared:
        if (
            type(path) is not str
            or not os.path.isabs(path)
            or "\x00" in path
        ):
            raise ValueError(f"{name} must be an absolute path")
        if not os.path.isfile(path):
            raise ValueError(f"{name} must name a regular file")
    if (
        type(args.attempt_timeout) is not int
        or not 1 <= args.attempt_timeout <= MAX_CHECK_TIMEOUT_MS
    ):
        raise ValueError(
            f"--attempt-timeout must be 1..{MAX_CHECK_TIMEOUT_MS} ms"
        )
    for name, path in (
        ("--list", args.list_path),
        (
            "--requirement" if mode == "requirement" else "--requirement-list",
            requirement_path,
        ),
    ):
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            raise ValueError(f"cannot read declared {name}: {exc}") from exc
        if size > MAX_INPUT_BYTES:
            raise ValueError(
                f"{name} exceeds the Core input bound ({MAX_INPUT_BYTES} bytes)"
            )
    if args.output is not None:
        out_path = Path(args.output)
        for _, path in declared:
            try:
                if out_path.samefile(path):
                    raise ValueError(
                        "--output may not overwrite a declared input document"
                    )
            except FileNotFoundError:
                continue


def _attempt_fingerprint(
    args: argparse.Namespace,
    list_bytes: bytes,
    requirement_bytes: bytes,
) -> str:
    """Bind executable and declared input bytes, including the mode."""
    mode, requirement_path = _requirement_declaration(args)
    request = {
        "schema_version": ACCEPT_LIST_REQUEST_PROFILE,
        "core": _file_sha256(args.core),
        "list": {
            "path": args.list_path,
            "sha256": hashlib.sha256(list_bytes).hexdigest(),
        },
        "requirement_mode": mode,
        "requirement": {
            "path": requirement_path,
            "sha256": hashlib.sha256(requirement_bytes).hexdigest(),
        },
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_descriptor(
    captured: bytes,
    exit_code: int | None,
    *,
    mode: str,
    list_bytes: bytes,
    requirement_bytes: bytes,
) -> dict | None:
    """Return a fully bound Core descriptor, or None if it is unrecognised."""
    if type(exit_code) is not int:
        return None
    try:
        pairs = json.loads(captured.decode("utf-8"), object_pairs_hook=tuple)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if (
        type(pairs) is not tuple
        or any(type(pair) is not tuple or len(pair) != 2 for pair in pairs)
        or len(pairs) != len({key for key, _ in pairs})
    ):
        return None
    descriptor = dict(pairs)
    verdict = descriptor.get("verdict")
    if (
        type(verdict) is not str
        or _VERDICT_EXIT_CODES.get(verdict) != exit_code
    ):
        return None

    common = {
        "evidence_schema_version": LIST_SCHEMA_VERSION,
        "acceptance": "evaluated",
    }
    expected_list_fingerprint = hashlib.sha256(list_bytes).hexdigest()
    if mode == "requirement":
        expected_keys = _SINGLE_DESCRIPTOR_KEYS
        schema = SINGLE_ACCEPTANCE_SCHEMA
        requirement_schema = REQUIREMENT_SCHEMA_VERSION
        fingerprint_field = "requirement_fingerprint"
        expected_requirement_fingerprint = hashlib.sha256(
            requirement_bytes
        ).hexdigest()
    else:
        expected_keys = _CONJUNCTIVE_DESCRIPTOR_KEYS
        schema = CONJUNCTIVE_ACCEPTANCE_SCHEMA
        requirement_schema = REQUIREMENT_LIST_SCHEMA_VERSION
        fingerprint_field = "requirement_list_fingerprint"
        expected_requirement_fingerprint = hashlib.sha256(
            requirement_bytes
        ).hexdigest()
    if (
        set(descriptor) != expected_keys
        or descriptor.get("schema_version") != schema
        or descriptor.get("requirement_schema_version") != requirement_schema
        or descriptor.get(fingerprint_field) != expected_requirement_fingerprint
        or descriptor.get("list_fingerprint") != expected_list_fingerprint
        or any(
            descriptor.get(name) != value
            for name, value in common.items()
        )
    ):
        return None

    if (
        type(descriptor.get("consistent")) is not bool
        or type(descriptor.get("conflict_count")) is not int
        or descriptor["conflict_count"] < 0
        or type(descriptor.get("records_evaluated")) is not int
        or descriptor["records_evaluated"] < 0
        or type(descriptor.get("conflicts")) is not list
    ):
        return None
    if mode == "requirement":
        if type(descriptor.get("records")) is not list:
            return None
    elif (
        type(descriptor.get("requirements_evaluated")) is not int
        or descriptor["requirements_evaluated"] < 0
        or type(descriptor.get("requirements")) is not list
    ):
        return None

    checks_performed = descriptor.get("checks_performed")
    checks_not_performed = descriptor.get("checks_not_performed")
    if (
        type(checks_performed) is not list
        or any(type(check) is not str for check in checks_performed)
        or type(checks_not_performed) is not list
        or any(type(check) is not str for check in checks_not_performed)
        or not _UNPERFORMED_CHECKS.issubset(checks_not_performed)
        or _UNPERFORMED_CHECKS.intersection(checks_performed)
    ):
        return None
    return descriptor


def build_accept_list_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="evidence-accept-list")
    parser.description = (
        "Run Core's declared-requirement normalization over a saved "
        "Evidence list and emit one attempt lineage and verdict."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help="Declared Core executable (absolute path).",
    )
    parser.add_argument(
        "--list",
        dest="list_path",
        required=True,
        metavar="PATH",
        help=(
            "Saved mumei.verification-evidence-list/v1 envelope "
            "(absolute path, at most 65536 bytes); its bytes are fed "
            "to Core on stdin."
        ),
    )
    requirements = parser.add_mutually_exclusive_group(required=True)
    requirements.add_argument(
        "--requirement",
        metavar="PATH",
        help="Declared mumei.evidence-requirement/v1 document.",
    )
    requirements.add_argument(
        "--requirement-list",
        dest="requirement_list",
        metavar="PATH",
        help="Declared conjunctive mumei.evidence-requirement-list/v1 document.",
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
        help="Write the report JSON here instead of stdout.",
    )
    return parser


def run_accept_list(args: argparse.Namespace) -> dict:
    """Run one bounded declared Core list-acceptance attempt.

    The report contains only the validated aggregate verdict and counts,
    never the descriptor, per-record checks or consistency-conflict list.
    A descriptor larger than the attempt stdout capture bound
    (`MAX_STDOUT_BYTES`) is reported as `descriptor_truncated` with no
    verdict and no selection.
    A selected result is Core's declared-success exit, not a grade promotion.
    """
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    _check_request(args)
    mode, requirement_path = _requirement_declaration(args)
    list_bytes = Path(args.list_path).read_bytes()
    requirement_bytes = Path(requirement_path).read_bytes()
    fingerprint = _attempt_fingerprint(args, list_bytes, requirement_bytes)
    argv = (
        args.core,
        "evidence",
        "accept-list",
        "--stdin",
        "--json",
        "--requirement" if mode == "requirement" else "--requirement-list",
        requirement_path,
    )
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        argv,
        memory_bound_mb=args.memory_bound_mb,
        feed_bytes=list_bytes,
    )
    try:
        current_list_bytes = Path(args.list_path).read_bytes()
        current_requirement_bytes = Path(requirement_path).read_bytes()
        inputs_changed = (
            _attempt_fingerprint(
                args,
                current_list_bytes,
                current_requirement_bytes,
            )
            != fingerprint
        )
    except OSError:
        inputs_changed = True

    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    descriptor = (
        _parse_descriptor(
            dispatch.run.stdout,
            exit_code,
            mode=mode,
            list_bytes=list_bytes,
            requirement_bytes=requirement_bytes,
        )
        if not inputs_changed and dispatch.run.complete
        else None
    )
    if (
        exit_code == 0
        and descriptor is not None
        and descriptor["verdict"] == "accepted"
        and not inputs_changed
    ):
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": ACCEPT_LIST_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif exit_code is not None and not dispatch.run.complete:
        # Per-record descriptors can exceed the attempt capture bound;
        # a truncated descriptor yields no verdict and never selects.
        report["descriptor_truncated"] = True
    elif descriptor is not None:
        report["acceptance_schema"] = descriptor["schema_version"]
        report["verdict"] = descriptor["verdict"]
        report["consistent"] = descriptor["consistent"]
        report["conflict_count"] = descriptor["conflict_count"]
        report["records_evaluated"] = descriptor["records_evaluated"]
        if mode == "requirement-list":
            report["requirements_evaluated"] = descriptor[
                "requirements_evaluated"
            ]
        report["checks_performed"] = list(descriptor["checks_performed"])
        report["checks_not_performed"] = list(
            descriptor["checks_not_performed"]
        )
    if published.selected_result is not None:
        report["candidate"] = published.evidence_candidate().to_dict()
    return report


def main_accept_list(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_accept_list_parser().parse_args()
    try:
        report = run_accept_list(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"evidence-accept-list: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
