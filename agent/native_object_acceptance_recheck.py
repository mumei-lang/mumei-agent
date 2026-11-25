"""C10 native-object-acceptance-recheck route: saved accept-object replay.

`python -m agent native-object-acceptance-recheck` runs `<core>
native-bundle recheck-object-acceptance --expected-build-id <id> <bundle>
<source> <descriptor>` inside the C11 dispatch lifecycle. The request
fingerprint binds the Core executable, the bundle's declared members, the
source, the saved descriptor and the trusted-channel build ID. One fresh
attempt is dispatched, declared inputs are re-hashed, and reconciled lineage
is published through compare-and-set.

Before dispatch the saved descriptor must decode without duplicate keys or
non-finite constants and pass the same validation `native-object-accept`
applies to a fresh descriptor, under an object-translation scope and with a
lowercase SHA-256 `evidence_fingerprint`. Core then reruns `accept-object`
on the pinned inputs, recomputes `evidence_fingerprint` and exits 0 only
when the saved descriptor equals the fresh one. Only that exit, with no
input drift, reports `consistent`; the saved descriptor's checks are then
discharged exactly as `native-object-accept` discharges a fresh descriptor.
Exit 3 is `inconclusive`. Exit 1 shares a stale, tampered or foreign
descriptor with every static failure, so the route claims nothing for it.

Consistency re-establishes the fresh acceptance; it does not authenticate
the descriptor or its producer, and it says nothing about historical
execution. Register convention, ABI/runtime/OS and final-artifact assurance
stay outside the claim. The report is not reusable Evidence or a
certificate, emits no evidence candidate, is not a recovery performer and
does not promote a grade.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.core_evidence import OBJECT_CHECK_VOCABULARY
from agent.native_accept import CHECK_VOCABULARY
from agent.native_bundle import (
    MAX_EVIDENCE_BYTES,
    MAX_RECORD_BYTES,
    MAX_SOURCE_BYTES,
    RECORD_FILE,
    declared_members,
    member_bound_bytes,
)
from agent.native_object_accept import (
    OBJECT_ACCEPT_TRANSLATION_SCOPES,
    _reject_json_constant,
    _unique_json_object,
    _valid_acceptance_descriptor,
    _valid_sha256,
    accepted_descriptor_fields,
)

NATIVE_OBJECT_ACCEPTANCE_RECHECK_REQUEST_PROFILE = (
    "mumei.native-object-acceptance-recheck-request/v1"
)
NATIVE_OBJECT_ACCEPTANCE_RECHECK_REPORT_PROFILE = (
    "mumei.native-object-acceptance-recheck-report/v1"
)
OBJECT_ACCEPTANCE_RECHECK_OUTCOMES = {0: "consistent", 3: "inconclusive"}

DEFAULT_ATTEMPT_TIMEOUT_MS = 60_000


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declared_files(args: argparse.Namespace, members: list[str]) -> list[Path]:
    bundle = Path(args.bundle)
    return (
        [Path(args.core)]
        + [bundle / member for member in members]
        + [Path(args.source), Path(args.descriptor)]
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


def _input_size(path: str, bound: int) -> None:
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ValueError(f"cannot read declared input: {exc}") from exc
    if size > bound:
        raise ValueError(
            f"{Path(path).name} exceeds the Core input bound ({bound} bytes)"
        )


def load_saved_descriptor(path: str, expected_build_id: str) -> dict:
    """Decode and validate a saved `accept-object --json` descriptor."""
    try:
        descriptor = json.loads(
            Path(path).read_bytes(),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError("--descriptor is not a valid JSON document") from exc
    if not (
        _valid_acceptance_descriptor(descriptor, expected_build_id)
        and descriptor["scope"] in OBJECT_ACCEPT_TRANSLATION_SCOPES
        and _valid_sha256(descriptor.get("evidence_fingerprint"))
    ):
        raise ValueError(
            "--descriptor is not an accepted native object acceptance "
            "descriptor for --expected-build-id"
        )
    return descriptor


def _check_request(args: argparse.Namespace) -> tuple[list[str], dict]:
    """Validate declared paths, bounds and the saved descriptor before dispatch."""
    if os.name != "posix":
        raise ValueError("native-object-acceptance-recheck requires a POSIX host")
    for name, path in (
        ("--core", args.core),
        ("--bundle", args.bundle),
        ("--source", args.source),
        ("--descriptor", args.descriptor),
    ):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    bundle = Path(args.bundle)
    if not bundle.is_dir():
        raise ValueError("--bundle must be a native-bundle directory")
    if not _valid_sha256(args.expected_build_id):
        raise ValueError("--expected-build-id must be a 64-character lowercase sha256")
    if not 1 <= args.attempt_timeout <= 300_000:
        raise ValueError("--attempt-timeout must be 1..300000 ms")
    _input_size(str(bundle / RECORD_FILE), MAX_RECORD_BYTES)
    members = declared_members(bundle)
    for member in members:
        _input_size(str(bundle / member), member_bound_bytes(member))
    _input_size(args.source, MAX_SOURCE_BYTES)
    _input_size(args.descriptor, MAX_EVIDENCE_BYTES)
    descriptor = load_saved_descriptor(args.descriptor, args.expected_build_id)
    _check_output_path(args, _declared_files(args, members))
    return members, descriptor


def _attempt_fingerprint(args: argparse.Namespace, members: list[str]) -> str:
    bundle = Path(args.bundle)
    member_hashes = {member: _file_sha256(bundle / member) for member in members}
    request = {
        "schema_version": NATIVE_OBJECT_ACCEPTANCE_RECHECK_REQUEST_PROFILE,
        "core": _file_sha256(Path(args.core)),
        "bundle": {"path": str(bundle), "members": member_hashes},
        "source": {
            "path": args.source,
            "sha256": _file_sha256(Path(args.source)),
        },
        "descriptor": {
            "path": args.descriptor,
            "sha256": _file_sha256(Path(args.descriptor)),
        },
        "expected_build_id": args.expected_build_id,
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_object_acceptance_recheck_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-object-acceptance-recheck")
    parser.description = (
        "Replay a saved native-bundle accept-object descriptor against a "
        "fresh object acceptance of the pinned inputs as one declared "
        "attempt. A consistent run discharges the saved descriptor's checks "
        "as native-object-accept does for a fresh one; it does not "
        "authenticate the descriptor or its producer, and makes no "
        "historical-execution, register-convention, ABI, runtime or "
        "final-artifact claim. It emits no evidence candidate, is not "
        "reusable Evidence or a certificate, is not a recovery performer and "
        "does not promote a grade."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle recheck-object-acceptance`."
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
            "Declared caller-supplied .mm source (absolute path, at most "
            "65536 bytes); the bundle's own labels/paths are never read."
        ),
    )
    parser.add_argument(
        "--descriptor",
        required=True,
        metavar="PATH",
        help=(
            "Declared saved `accept-object --json` descriptor (absolute path, "
            "at most 1048576 bytes) to replay."
        ),
    )
    parser.add_argument(
        "--expected-build-id",
        required=True,
        metavar="SHA256",
        help=(
            "SHA-256 of native-bundle.json obtained through a separately "
            "trusted channel, not the descriptor."
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
        help="Write the object-acceptance-recheck report JSON here instead of stdout.",
    )
    return parser


def run_object_acceptance_recheck(args: argparse.Namespace) -> dict:
    """Run the declared saved object-acceptance replay and return its report."""
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    members, descriptor = _check_request(args)
    fingerprint = _attempt_fingerprint(args, members)
    argv = (
        args.core,
        "native-bundle",
        "recheck-object-acceptance",
        "--expected-build-id",
        args.expected_build_id,
        args.bundle,
        args.source,
        args.descriptor,
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
        drift_members = declared_members(Path(args.bundle))
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
        "schema_version": NATIVE_OBJECT_ACCEPTANCE_RECHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
        "expected_build_id": args.expected_build_id,
        "checks_not_performed": sorted(CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY),
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif exit_code in OBJECT_ACCEPTANCE_RECHECK_OUTCOMES:
        outcome = OBJECT_ACCEPTANCE_RECHECK_OUTCOMES[exit_code]
        report["object_acceptance_recheck"] = outcome
        if outcome == "consistent":
            report["evidence_fingerprint"] = descriptor["evidence_fingerprint"]
            report.update(accepted_descriptor_fields(descriptor))
    return report


def main_object_acceptance_recheck(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_object_acceptance_recheck_parser().parse_args()
    try:
        report = run_object_acceptance_recheck(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-object-acceptance-recheck: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
