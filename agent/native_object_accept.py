"""C10 native-object-accept route: bounded object-stage machine-code acceptance.

`python -m agent native-object-accept` runs `<core> native-bundle
accept-object --expected-build-id <id> --json <bundle> <source>` inside the
C11 dispatch lifecycle. The request fingerprint binds the Core executable,
the bundle's declared members, source, and trusted-channel build ID. One fresh
attempt is dispatched, declared inputs are re-hashed, and reconciled lineage
is published through compare-and-set.

Only an exit-0 descriptor that passes validation and has no input drift
discharges checks. Core's `object_source_machine_code_correspondence` maps to
the agent-owned `object_translation_correspondence`; Core does not emit the
agent check name. The report is not reusable Evidence or a certificate, is
not a recovery performer, emits no evidence candidate, and does not promote a
grade.

This is bounded object-stage machine-code acceptance under an assumed, not
validated, register convention and the stated input domain. Here
`object_translation_correspondence` means only Core's profile-bounded
source-to-object machine-code correspondence, not universal object TV. The C
`machine_code_entry_wrapper_tv` check is consumed only when the validated
descriptor lists it in `checks_performed`. It applies only when the object
defines both `main` and `__mumei_user_main` and the latter has a supported
source signature; it checks one unconditional call from `main` to
`__mumei_user_main`, returning the low 32 bits of its result. This makes no
CRT, loader, OS exit-status, ABI, or runtime claim;
`os_exit_status_observation` remains a separate runtime-observation check and
is not discharged here. Broader C entry-wrapper behavior, CRT, loader/libc,
ABI/runtime semantics, optimizer semantics, producer authenticity, and
historical execution remain outside the claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.core_evidence import OBJECT_CHECK_VOCABULARY
from agent.native_accept import CHECK_VOCABULARY, DischargedChecks
from agent.native_bundle import (
    MAX_RECORD_BYTES,
    MAX_SOURCE_BYTES,
    RECORD_FILE,
    member_bound_bytes,
)
from agent.native_bundle import (
    declared_members as _declared_members,
)
from agent.native_machine_tv_recheck import (
    _bounded_descriptor_string,
    _function_outcomes,
)

NATIVE_OBJECT_ACCEPT_REQUEST_PROFILE = "mumei.native-object-accept-request/v1"
NATIVE_OBJECT_ACCEPT_REPORT_PROFILE = "mumei.native-object-accept-report/v1"
NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA = "mumei.native-evidence-acceptance/v1"
OBJECT_ACCEPT_OUTCOMES = {0: "accepted", 3: "inconclusive"}
OBJECT_ACCEPT_WITH_LINK_SCOPE = (
    "native_bundle_object_machine_code_translation_correspondence"
)
OBJECT_ACCEPT_WITHOUT_LINK_SCOPE = (
    "native_bundle_object_machine_code_translation_correspondence_without_object_link"
)
OBJECT_SOURCE_MACHINE_CODE_CHECK = "object_source_machine_code_correspondence"

DEFAULT_ATTEMPT_TIMEOUT_MS = 60_000


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate descriptor key")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid descriptor constant: {value}")


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


def _is_build_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _check_request(args: argparse.Namespace) -> list[str]:
    """Validate declared paths and bounds before dispatch."""
    if os.name != "posix":
        raise ValueError("native-object-accept requires a POSIX host")
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
        source_size = os.path.getsize(args.source)
    except OSError as exc:
        raise ValueError(f"cannot read declared input: {exc}") from exc
    if source_size > MAX_SOURCE_BYTES:
        raise ValueError(
            f"{Path(args.source).name} exceeds the Core input bound "
            f"({MAX_SOURCE_BYTES} bytes)"
        )
    _check_output_path(args, _declared_files(args, members))
    return members


def _attempt_fingerprint(args: argparse.Namespace, members: list[str]) -> str:
    bundle = Path(args.bundle)
    member_hashes = {member: _file_sha256(bundle / member) for member in members}
    request = {
        "schema_version": NATIVE_OBJECT_ACCEPT_REQUEST_PROFILE,
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


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _valid_acceptance_descriptor(descriptor: object, expected_build_id: str) -> bool:
    if not isinstance(descriptor, dict):
        return False
    if (
        descriptor.get("schema_version") != NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA
        or descriptor.get("acceptance") != "evaluated"
        or descriptor.get("accepted") is not True
        or descriptor.get("build_id") != expected_build_id
    ):
        return False
    scope = descriptor.get("scope")
    if scope not in (
        OBJECT_ACCEPT_WITH_LINK_SCOPE,
        OBJECT_ACCEPT_WITHOUT_LINK_SCOPE,
    ):
        return False
    performed = descriptor.get("checks_performed")
    not_performed = descriptor.get("checks_not_performed")
    if (
        not isinstance(performed, list)
        or not all(isinstance(check, str) for check in performed)
        or not isinstance(not_performed, list)
        or not all(isinstance(check, str) for check in not_performed)
    ):
        return False
    if OBJECT_SOURCE_MACHINE_CODE_CHECK not in performed:
        return False
    has_object_link = "object_link_correspondence" in performed
    if has_object_link != (scope == OBJECT_ACCEPT_WITH_LINK_SCOPE):
        return False
    if set(performed) & set(not_performed):
        return False
    return _valid_sha256(descriptor.get("llvm_sha256")) and _valid_sha256(
        descriptor.get("object_sha256")
    )


def build_object_accept_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-object-accept")
    parser.description = (
        "Run Core's bounded object-stage machine-code acceptance under an "
        "assumed, not validated, register convention and stated input domain. "
        "Core's machine_code_entry_wrapper_tv is consumed only when the valid "
        "descriptor lists it in checks_performed; when applicable, it checks "
        "one unconditional main call to __mumei_user_main returning the low "
        "32 bits of its result. Applicability requires both object symbols "
        "and a supported __mumei_user_main source signature. This makes no "
        "CRT, loader, OS exit-status, ABI or runtime claim; "
        "os_exit_status_observation remains a separate runtime-observation "
        "check and is not discharged. "
        "This emits no evidence candidate, is not reusable Evidence or a "
        "certificate, is not a recovery performer, and does not promote a "
        "grade; broader C entry-wrapper behavior, CRT, loader/libc, "
        "ABI/runtime, optimizer semantics, producer authenticity and "
        "historical execution remain outside the profile. "
        "object_translation_correspondence here is only profile-bounded "
        "source-to-object machine-code correspondence, not universal object "
        "TV."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle accept-object`."
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
        "--expected-build-id",
        required=True,
        metavar="SHA256",
        help=(
            "SHA-256 of native-bundle.json obtained through a separately "
            "trusted channel."
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
        help="Write the object-accept report JSON here instead of stdout.",
    )
    return parser


def run_object_accept(args: argparse.Namespace) -> dict:
    """Run declared native object acceptance and return its report."""
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
        "accept-object",
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
        "schema_version": NATIVE_OBJECT_ACCEPT_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
        "expected_build_id": args.expected_build_id,
        "checks_not_performed": sorted(CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY),
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif exit_code == 0:
        try:
            descriptor = json.loads(
                dispatch.run.stdout,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (ValueError, UnicodeDecodeError, RecursionError):
            descriptor = None
        if not _valid_acceptance_descriptor(descriptor, args.expected_build_id):
            report["descriptor_invalid"] = True
        else:
            report["acceptance"] = "accepted"
            report["acceptance_schema"] = NATIVE_EVIDENCE_ACCEPTANCE_SCHEMA
            report["scope"] = descriptor["scope"]
            report["llvm_sha256"] = descriptor["llvm_sha256"]
            report["object_sha256"] = descriptor["object_sha256"]
            for field in ("register_convention_assumed", "input_domain"):
                value = _bounded_descriptor_string(descriptor, field)
                if value is not None:
                    report[field] = value
            outcomes = _function_outcomes(descriptor)
            if outcomes is not None:
                report["function_outcomes"] = outcomes
            checks_performed = set(descriptor["checks_performed"])
            discharged = set(DischargedChecks.ACCEPTED)
            discharged.update(
                checks_performed
                & (OBJECT_CHECK_VOCABULARY - {"object_translation_correspondence"})
            )
            discharged.add("object_translation_correspondence")
            report["discharged_checks"] = sorted(discharged)
            report["checks_not_performed"] = sorted(
                (CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY) - discharged
            )
    elif exit_code == 3:
        report["acceptance"] = OBJECT_ACCEPT_OUTCOMES[exit_code]
    return report


def main_object_accept(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_object_accept_parser().parse_args()
    try:
        report = run_object_accept(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-object-accept: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
