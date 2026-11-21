"""C10 native-machine-tv-recheck route: bounded branch-aware machine-code TV.

`python -m agent native-machine-tv-recheck` runs
`<core> native-bundle recheck-machine-tv --expected-build-id <id> --json
<bundle> <source>` inside the C11 dispatch lifecycle. The request fingerprint
binds the Core executable, the bundle's declared members, source and trusted-
channel build ID; dispatch records one fresh attempt and publishes reconciled
lineage compare-and-set.

Core runs the object reproduction and correspondence pipeline, then compares
leaf straight-line, forward-branch, acyclic backward-branch, and bounded-loop
functions (LOOP_BOUND=4) with pure-i64 source models under an assumed
register convention. Direct calls, including calls inside branching
functions, are compared as uninterpreted call sites; conditional-call
functions use per-path guarded call matching. The agent consumes machine-TV
object checks only when the matching `mumei.machine-code-tv/v1` descriptor
lists them in `checks_performed`. Bounded loops use Core's `LOOP_BOUND=4`,
with `_and_loops_exiting_within_bound_4` in the input-domain string.
Callee-saved preservation is proved only for Equivalent functions within
this profile. Direct callees and the cancellation poll are assumed to
preserve callee-saved registers; external callees remain an assumption. The
argument/result register convention is also assumed, not validated.
Core's entry-wrapper check applies only when the object defines both `main`
and `__mumei_user_main` and the latter has a supported source signature. It
checks `main` as one unconditional call to `__mumei_user_main`, returning the
low 32 bits of its result. `machine_code_entry_wrapper_tv` is discharged only
when a matching descriptor lists it in `checks_performed`. This bounded
wrapper check makes no CRT, loader, OS exit-status, ABI, or runtime claim;
`os_exit_status_observation` remains a separate runtime-observation check and
is not discharged here.
Core's `machine_code_callee_saved_preservation_assumed_for_external_callees`
marker remains not performed.
Core #1233's scalar-f64 function check is consumed only when listed in a
matching descriptor's `checks_performed`; it applies only under Core's f64
profile with XMM argument/result registers assumed, not validated. MXCSR RNE,
masked exceptions, FTZ/DAZ-off assumptions, and NaN payload bits remain
unestablished and not performed; the agent never discharges the MXCSR or
NaN-payload markers even if a descriptor lists them as performed. Direct-call
f64 arguments are admitted only under Core's exact-bits obligation
(NaN-aware match, then an exact-bit proof against the XMM argument); computed
f64 arguments without provably identical bits and f64 tail calls fail closed.
This makes no IEEE-754 conformance, ABI, runtime, or full object-TV claim.
Core's `machine_code_composite_register_aggregate_tv` is consumed only when
listed in `checks_performed`; it covers one- through four-leaf struct
parameters, results and direct-call struct values with integer and/or f64
leaves. One- and two-leaf values use Core's existing assumed SysV eightbyte
convention; integer arguments use rdi–r9 and f64 arguments xmm0–xmm7, with
the whole aggregate fitting and never split or stack-passed. Aggregate
results are limited to three integer leaves in rax/rdx/rcx and two f64 leaves
in xmm0/xmm1. Aggregates wider than two leaves assume LLVM first-class
aggregate register lowering, not SysV C-ABI classification, and
`machine_code_tv_sysv_memory_class_aggregate_abi` stays not performed. This
makes no ABI, runtime or full object-TV claim.
Executions beyond the bound, cancellation/runtime semantics and other cyclic
control flow remain outside the profile. This is not an ABI-correctness,
runtime or full object-TV claim. No broader C entry-wrapper, CRT, loader or
libc behavior is covered; `object_translation_correspondence` stays
unperformed. Function outcomes and callee-saved preservation are aggregated
as counts without function names. This recheck report is never a recovery
performer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.core_evidence import (
    MACHINE_TV_ASSUMPTION_MARKERS,
    OBJECT_CHECK_VOCABULARY,
)
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
MACHINE_TV_OBJECT_CHECKS = (
    OBJECT_CHECK_VOCABULARY
    - {"object_translation_correspondence"}
    - MACHINE_TV_ASSUMPTION_MARKERS
)
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
        "Run Core's bounded leaf straight-line, forward-branch, acyclic "
        "backward-branch, conditional-call and LOOP_BOUND=4 bounded-loop "
        "machine-code TV recheck; direct calls remain uninterpreted sites, "
        "including inside branching functions with per-path guarded call "
        "matching; bounded loops use the "
        "`_and_loops_exiting_within_bound_4` input-domain suffix when listed "
        "by the descriptor; callee-saved preservation is proved only for "
        "Equivalent functions within the profile; direct callees and the "
        "cancellation poll are assumed to preserve callee-saved registers, "
        "and external callees remain an assumption; Core's external-callee "
        "`machine_code_callee_saved_preservation_assumed_for_external_callees` "
        "marker remains not performed. Core's `machine_code_entry_wrapper_tv` "
        "is consumed only when listed in `checks_performed`; when applicable "
        "it checks that `main` makes one unconditional call to "
        "`__mumei_user_main` and returns the low 32 bits of its result. The "
        "object must define both symbols and the user-main source signature "
        "must be supported. This makes no CRT, loader, OS exit-status, ABI or "
        "runtime claim; `os_exit_status_observation` is a separate "
        "runtime-observation check and is not discharged. The argument/result "
        "register convention is assumed, not validated; executions beyond "
        "the bound, cancellation/runtime semantics and other cyclic control "
        "flow stay outside. Core's `machine_code_f64_scalar_function_tv` is "
        "consumed only when listed in `checks_performed`; it applies only "
        "under Core's f64 profile with XMM argument/result registers assumed, "
        "not validated. MXCSR RNE, masked exceptions, FTZ/DAZ-off assumptions "
        "and NaN payload bits remain unestablished and not performed; the "
        "agent never discharges the MXCSR or NaN-payload markers even if a "
        "descriptor lists them as performed. Direct-call f64 arguments are "
        "admitted only under Core's exact-bits obligation (NaN-aware match, "
        "then an exact-bit proof against the XMM argument); computed f64 "
        "arguments without provably identical bits and f64 tail calls fail "
        "closed. This makes no IEEE-754 conformance, ABI, runtime or full "
        "object-TV claim. Core's `machine_code_composite_register_aggregate_tv` "
        "is consumed only when listed in `checks_performed`; it covers one- "
        "through four-leaf struct parameters, results and direct-call struct "
        "values with integer and/or f64 leaves. One- and two-leaf values use "
        "Core's existing assumed SysV eightbyte convention; integer arguments "
        "use rdi–r9 and f64 arguments xmm0–xmm7, with the whole aggregate "
        "fitting and never split or stack-passed. Aggregate results are limited "
        "to three integer leaves in rax/rdx/rcx and two f64 leaves in "
        "xmm0/xmm1. Aggregates wider than two leaves assume LLVM first-class "
        "aggregate register lowering, not SysV C-ABI classification, and "
        "`machine_code_tv_sysv_memory_class_aggregate_abi` stays not performed. "
        "This makes no ABI, runtime or full object-TV claim."
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


def _callee_saved_preservation_counts(descriptor: dict) -> dict[str, int] | None:
    functions = descriptor.get("functions")
    if not isinstance(functions, dict):
        return None
    counts = {"preserved": 0, "violated": 0, "unknown": 0}
    found = False
    for function in functions.values():
        if not isinstance(function, dict):
            return None
        if "callee_saved_preservation" not in function:
            continue
        preservation = function["callee_saved_preservation"]
        if not isinstance(preservation, str) or preservation not in counts:
            return None
        counts[preservation] += 1
        found = True
    return counts if found else None


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
                preservation_counts = _callee_saved_preservation_counts(
                    descriptor
                )
                if preservation_counts is not None:
                    report["callee_saved_preservation"] = preservation_counts
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
