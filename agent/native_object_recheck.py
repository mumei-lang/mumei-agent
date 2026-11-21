"""C10 native-object-recheck route: bounded symbol and call-edge correspondence.

`python -m agent native-object-recheck` runs `<core> native-bundle
recheck-object --expected-build-id <id> --json <bundle> <source>` inside
the C11 dispatch lifecycle. The request fingerprint binds the Core
executable, the bundle's declared members, source and trusted-channel
build ID; dispatch records one fresh attempt and publishes reconciled
lineage compare-and-set.

Core reproduces the pinned artifacts, then checks the object's non-local
defined text symbols against externally visible IR function definitions
and checks direct call edges plus bounded object-to-executable function
bytes and resolved PC-relative call targets. Object checks are discharged
only when a matching descriptor lists them; an older Core may exit 0
without listing `object_link_correspondence`. This makes no
instruction-selection, register-allocation, linker-semantics, ABI, runtime
or historical-execution claim. `machine_code_leaf_function_tv`,
`machine_code_direct_call_site_tv`,
`machine_code_forward_branch_function_tv`,
`machine_code_acyclic_branch_function_tv`,
`machine_code_conditional_call_function_tv`,
`machine_code_bounded_loop_function_tv`,
`machine_code_callee_saved_register_preservation`,
`machine_code_callee_saved_preservation_assumed_for_external_callees`,
`machine_code_entry_wrapper_tv`, `machine_code_f64_scalar_function_tv`,
`machine_code_composite_register_aggregate_tv`,
`machine_code_tv_mxcsr_control_state`, `machine_code_tv_nan_payload_bits`,
`machine_code_tv_sysv_memory_class_aggregate_abi` and
`object_translation_correspondence` stay unperformed. This recheck report is
never a recovery performer.

Machine-TV recheck and object acceptance (not native-object-recheck) consume
Core's `machine_code_composite_register_aggregate_tv` only when listed in
`checks_performed`; it covers one- through four-leaf struct parameters,
results and direct-call struct values with integer and/or f64 leaves. One- and
two-leaf values use Core's existing assumed SysV eightbyte convention;
integer arguments use rdi–r9 and f64 arguments xmm0–xmm7, with the whole
aggregate fitting and never split or stack-passed. Aggregate results are
limited to three integer leaves in rax/rdx/rcx and two f64 leaves in
xmm0/xmm1. Aggregates wider than two leaves assume LLVM first-class aggregate
register lowering, not SysV C-ABI classification, and
`machine_code_tv_sysv_memory_class_aggregate_abi` stays not performed. This
makes no ABI, runtime or full object-TV claim. Native-object-recheck itself
never discharges this machine-TV check.
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

NATIVE_OBJECT_RECHECK_REQUEST_PROFILE = (
    "mumei.native-object-recheck-request/v1"
)
NATIVE_OBJECT_RECHECK_REPORT_PROFILE = "mumei.native-object-recheck-report/v1"
OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA = "mumei.object-symbol-correspondence/v1"
OBJECT_RECHECK_CHECKS = OBJECT_CHECK_VOCABULARY - {
    "machine_code_leaf_function_tv",
    "machine_code_direct_call_site_tv",
    "machine_code_forward_branch_function_tv",
    "machine_code_acyclic_branch_function_tv",
    "machine_code_conditional_call_function_tv",
    "machine_code_bounded_loop_function_tv",
    "machine_code_callee_saved_register_preservation",
    "machine_code_callee_saved_preservation_assumed_for_external_callees",
    "machine_code_entry_wrapper_tv",
    "machine_code_f64_scalar_function_tv",
    "machine_code_composite_register_aggregate_tv",
    "machine_code_tv_mxcsr_control_state",
    "machine_code_tv_nan_payload_bits",
    "machine_code_tv_sysv_memory_class_aggregate_abi",
    "object_translation_correspondence",
}

OBJECT_RECHECK_OUTCOMES = {0: "corresponds", 3: "inconclusive"}

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


class DischargedChecks:
    """Checks established by a successful artifact reproduction."""

    RECHECKED = frozenset(
        {
            "artifact_semantics",
            "claim_truth",
        }
    )


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
        raise ValueError("native-object-recheck requires a POSIX host")
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
        "schema_version": NATIVE_OBJECT_RECHECK_REQUEST_PROFILE,
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


def build_object_recheck_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-object-recheck")
    parser.description = (
        "Run a declared Core native object correspondence recheck as one "
        "attempt and emit the reconciled lineage plus declared outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle recheck-object`."
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


def run_object_recheck(args: argparse.Namespace) -> dict:
    """Run declared native object recheck and return its report."""
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
        "recheck-object",
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
        "schema_version": NATIVE_OBJECT_RECHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
        "expected_build_id": args.expected_build_id,
        "checks_not_performed": sorted(CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY),
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif exit_code in OBJECT_RECHECK_OUTCOMES:
        report["object_recheck"] = OBJECT_RECHECK_OUTCOMES[exit_code]
        if report["object_recheck"] == "corresponds":
            try:
                descriptor = json.loads(dispatch.run.stdout)
            except (ValueError, UnicodeDecodeError, RecursionError):
                descriptor = None
            valid_descriptor = (
                isinstance(descriptor, dict)
                and descriptor.get("schema_version")
                == OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA
                and descriptor.get("build_id") == args.expected_build_id
            )
            discharged = set(DischargedChecks.RECHECKED)
            if valid_descriptor:
                report["object_correspondence_schema"] = (
                    OBJECT_SYMBOL_CORRESPONDENCE_SCHEMA
                )
                checks_performed = descriptor.get("checks_performed")
                if isinstance(checks_performed, list):
                    discharged.update(
                        check
                        for check in checks_performed
                        if isinstance(check, str)
                        and check in OBJECT_RECHECK_CHECKS
                    )
            report["discharged_checks"] = sorted(discharged)
            report["checks_not_performed"] = sorted(
                (CHECK_VOCABULARY | OBJECT_CHECK_VOCABULARY) - discharged
            )
    return report


def main_object_recheck(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_object_recheck_parser().parse_args()
    try:
        report = run_object_recheck(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-object-recheck: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
