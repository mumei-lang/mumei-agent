"""C10 native-machine-tv-recheck route: bounded straight-line machine-code TV.

`python -m agent native-machine-tv-recheck` runs
`<core> native-bundle recheck-machine-tv --expected-build-id <id> --json
<bundle> <source>` inside the C11 dispatch lifecycle. The request fingerprint
binds the Core executable, the bundle's declared members, source and trusted-
channel build ID; dispatch records one fresh attempt and publishes reconciled
lineage compare-and-set.

Core runs the object reproduction and correspondence pipeline, then compares
straight-line functions with pure-i64 source models under an assumed register
convention. Direct calls are compared as uninterpreted call sites. This is not
an ABI, full object translation, runtime or historical-execution claim.
Branching functions, the C `main` wrapper, CRT, loader and libc are outside
the profile; `object_translation_correspondence` stays unperformed. This
recheck report is never a recovery performer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.core_evidence import OBJECT_CHECK_VOCABULARY
from agent.native_bundle import (
    FILE_MEMBERS,  # noqa: F401 — re-exported for route consumers/tests
    MAX_RECORD_BYTES,
    MAX_SOURCE_BYTES,
    RECORD_FILE,
    declared_members as _declared_members,
    member_bound_bytes,
)

NATIVE_MACHINE_TV_RECHECK_REQUEST_PROFILE = (
    "mumei.native-machine-tv-recheck-request/v1"
)
NATIVE_MACHINE_TV_RECHECK_REPORT_PROFILE = (
    "mumei.native-machine-tv-recheck-report/v1"
)
MACHINE_TV_SCHEMA = "mumei.machine-code-tv/v1"
MACHINE_TV_OUTCOMES = {0: "checked", 3: "inconclusive"}

CHECK_VOCABULARY = frozenset(
    {
        "claim_truth",
        "file_identity",
        "freshness",
        "producer_authenticity",
        "semantic_correspondence",
        "artifact_semantics",
    }
)
MACHINE_TV_OBJECT_CHECKS = OBJECT_CHECK_VOCABULARY - {
    "object_translation_correspondence"
}
ALWAYS_DISCHARGED = frozenset({"artifact_semantics", "claim_truth"})
MAX_DESCRIPTOR_STRING_LENGTH = 256
DEFAULT_ATTEMPT_TIMEOUT_MS = 60_000


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declared_files(args: argparse.Namespace, members: list[str]) -> list[Path]:
    bundle = Path(args.bundle)
    return (
        [Path(args.core)]
        + [bundle / member for member in members]
        + [Path(args.source)]
    )


def _check_output_path(args: argparse.Namespace, declared: list[Path]) -> None:
    if args.output is None:
        return
    out_path = Path(args.output)
    for declared_path in declared:
        try:
            if out_path.samefile(declared_path):
                raise ValueError("--output may not overwrite a declared input document")
        except FileNotFoundError:
            continue


def _is_build_id(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _check_request(args: argparse.Namespace) -> list[str]:
    """Validate the declared request before any attempt is dispatched."""
    if os.name != "posix":
        raise ValueError("native-machine-tv-recheck requires a POSIX host")
    for name, path in (
        ("--core", args.core),
        ("--bundle", args.bundle),
        ("--source", args.source),
    ):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    bundle = Path(args.bundle)
    if not bundle.is_dir():
        raise ValueError("--bundle must be a native-bundle directory")
    if not _is_build_id(args.expected_build_id):
        raise ValueError("--expected-build-id must be a 64-character lowercase sha256")
    if not 1 <= args.attempt_timeout <= 300_000:
        raise ValueError("--attempt-timeout must be 1..300000 ms")
    try:
        record_size = os.path.getsize(bundle / RECORD_FILE)
    except OSError as exc:
        raise ValueError(f"cannot read declared input: {exc}") from exc
    if record_size > MAX_RECORD_BYTES:
        raise ValueError(
            f"{RECORD_FILE} exceeds the Core input bound ({MAX_RECORD_BYTES} bytes)"
        )
    members = _declared_members(bundle)
    for member in members:
        path = bundle / member
        bound = member_bound_bytes(member)
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            raise ValueError(f"cannot read declared input: {exc}") from exc
        if size > bound:
            raise ValueError(
                f"{path.name} exceeds the Core input bound ({bound} bytes)"
            )
    try:
        size = os.path.getsize(args.source)
    except OSError as exc:
        raise ValueError(f"cannot read declared input: {exc}") from exc
    if size > MAX_SOURCE_BYTES:
        raise ValueError(
            f"{Path(args.source).name} exceeds the Core input bound "
            f"({MAX_SOURCE_BYTES} bytes)"
        )
    _check_output_path(args, _declared_files(args, members))
    return members


def _attempt_fingerprint(args: argparse.Namespace, members: list[str]) -> str:
    """Bind the request's declared inputs into one request identity."""
    bundle = Path(args.bundle)
    member_hashes = {member: _file_sha256(bundle / member) for member in members}
    request = {
        "schema_version": NATIVE_MACHINE_TV_RECHECK_REQUEST_PROFILE,
        "core": _file_sha256(Path(args.core)),
        "bundle": {"path": str(bundle), "members": member_hashes},
        "source": {
            "path": args.source,
            "sha256": _file_sha256(Path(args.source)),
        },
        "expected_build_id": args.expected_build_id,
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_machine_tv_recheck_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-machine-tv-recheck")
    parser.description = (
        "Run Core's bounded straight-line machine-code TV recheck, with "
        "direct calls compared as uninterpreted sites, and emit one attempt."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle recheck-machine-tv`."
        ),
    )
    parser.add_argument(
        "--bundle",
        required=True,
        metavar="DIR",
        help=(
            "Declared native-bundle directory (absolute path) holding "
            "native-bundle.json and its declared members."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        metavar="PATH",
        help=(
            "Declared caller-supplied .mm source (absolute path, at "
            "most 65536 bytes); the bundle's own labels/paths are "
            "never read."
        ),
    )
    parser.add_argument(
        "--expected-build-id",
        required=True,
        metavar="SHA256",
        help=(
            "SHA-256 of native-bundle.json obtained through a "
            "separately trusted channel."
        ),
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        default=DEFAULT_ATTEMPT_TIMEOUT_MS,
        metavar="<MS>",
        help="Declared attempt bound in milliseconds.",
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
        help="Write the recheck report JSON here instead of stdout.",
    )
    return parser


def _bounded_descriptor_string(descriptor: dict, field: str) -> str | None:
    value = descriptor.get(field)
    if isinstance(value, str) and len(value) <= MAX_DESCRIPTOR_STRING_LENGTH:
        return value
    return None


def _function_outcomes(descriptor: dict) -> dict[str, int] | None:
    functions = descriptor.get("functions")
    if not isinstance(functions, dict):
        return None
    counts = {"equivalent_within_profile": 0, "outside_profile": 0}
    for function in functions.values():
        if isinstance(function, dict):
            outcome = function.get("outcome")
            if isinstance(outcome, str) and outcome in counts:
                counts[outcome] += 1
    return counts


def run_machine_tv_recheck(args: argparse.Namespace) -> dict:
    """Run declared native machine-TV recheck and return its report."""
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    members = _check_request(args)
    fingerprint = _attempt_fingerprint(args, members)
    argv = (
        args.core,
        "native-bundle",
        "recheck-machine-tv",
        "--expected-build-id",
        args.expected_build_id,
        "--json",
        args.bundle,
        args.source,
    )
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        argv,
        memory_bound_mb=args.memory_bound_mb,
    )
    try:
        drift_members = _declared_members(Path(args.bundle))
        inputs_changed = _attempt_fingerprint(args, drift_members) != fingerprint
    except (OSError, ValueError):
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    if exit_code == 0 and not inputs_changed:
        updated = dispatch.sequence.select_result(dispatch.captured_output())
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": NATIVE_MACHINE_TV_RECHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
        "expected_build_id": args.expected_build_id,
        "checks_not_performed": sorted(CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY),
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif exit_code in MACHINE_TV_OUTCOMES:
        report["machine_tv_recheck"] = MACHINE_TV_OUTCOMES[exit_code]
        if report["machine_tv_recheck"] == "checked":
            try:
                descriptor = json.loads(dispatch.run.stdout)
            except (ValueError, UnicodeDecodeError, RecursionError):
                descriptor = None
            valid_descriptor = (
                isinstance(descriptor, dict)
                and descriptor.get("schema_version") == MACHINE_TV_SCHEMA
                and descriptor.get("build_id") == args.expected_build_id
            )
            discharged = set(ALWAYS_DISCHARGED)
            if valid_descriptor:
                report["machine_tv_schema"] = MACHINE_TV_SCHEMA
                for field in (
                    "register_convention_assumed",
                    "input_domain",
                ):
                    value = _bounded_descriptor_string(descriptor, field)
                    if value is not None:
                        report[field] = value
                outcomes = _function_outcomes(descriptor)
                if outcomes is not None:
                    report["function_outcomes"] = outcomes
                checks_performed = descriptor.get("checks_performed")
                if isinstance(checks_performed, list):
                    discharged.update(
                        check
                        for check in checks_performed
                        if isinstance(check, str)
                        and check in MACHINE_TV_OBJECT_CHECKS
                    )
            report["discharged_checks"] = sorted(discharged)
            report["checks_not_performed"] = sorted(
                (CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY) - discharged
            )
    return report


def main_machine_tv_recheck(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_machine_tv_recheck_parser().parse_args()
    try:
        report = run_machine_tv_recheck(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-machine-tv-recheck: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
