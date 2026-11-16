"""C02/C10 native-source-recheck route: declared bundle source
recheck.

`python -m agent native-source-recheck` runs `<core> native-bundle
recheck-source --expected-build-id <id> <bundle> <source>` inside
the C11 dispatch lifecycle: a declared request — the Core
executable's bytes, the pinned bundle's declared member bytes (the
component files plus, for multifile records, every
`sources/<member>` the merge is re-derived from), the
caller-supplied source's bytes and the trusted-channel build ID —
is fingerprinted, a fresh ``AttemptSequence`` is keyed to it, one
reserved attempt is observed by ``AttemptRunner``, and the
reconciled lineage is published compare-and-set.

`recheck-source` is the Stage A consumer between `check` and
`recheck-llvm`: on top of `check`'s identity gate it freshly
rechecks the C03 source postcondition within the profile, without
replaying the LLVM snapshot, toolchain or binary semantics the
deeper consumers recheck. The exit code IS the verdict, exactly as
`native-evidence-recheck` relates to `native-evidence-accept`.

Selection rule: only an ``exited`` run with ``exit_code == 0``
selects — the pinned identities checked consistent and the source
postcondition was freshly rechecked within profile then. Exit 1
conflates a refuted postcondition with every static failure —
unreadable input, invalid build ID, pinned record or member
mismatch, outside-profile source — so the route names it only
through the lineage's ``exit_code``, never as a claimed outcome;
inconclusive exits 3. The route re-hashes every declared input after
the observed run; when any byte drifted mid-run it skips the
selection, claims no outcome and reports ``inputs_changed``.

The report carries a ``source_recheck`` field naming the terminal
outcome only when the exit code is unambiguous: ``"rechecked"`` (0)
or ``"inconclusive"`` (3). Exit 1 conflates a refuted postcondition
with every static failure, so the route names it only through the
lineage's ``exit_code``. No evidence candidate is emitted: the
produced stdout is a fixed diagnostic line, not an evidence record,
so there is no ``mumei.verifier-evidence-candidate/v1`` handoff.
The captured bytes still enter the lineage through the selection
itself.

Emits ``mumei.native-source-recheck-report/v1``: the canonical
sequence, the normalized run-result descriptor, the declared
recheck outcome and the discharged-check partition on a rechecked
run. A ``rechecked`` outcome discharges ``file_identity`` — the
pinned bundle's declared files and identities match the bytes the
caller declared — and ``claim_truth`` — the source postcondition
was freshly re-proven within the profile — at representation
level. The other four checks stay in ``checks_not_performed``
(producer authenticity, freshness, semantic correspondence and
artifact semantics all need the deeper consumers this route does
not run).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.native_bundle import (
    FILE_MEMBERS,  # noqa: F401 — re-exported for route consumers/tests
    MAX_RECORD_BYTES,
    MAX_SOURCE_BYTES,
    RECORD_FILE,
    declared_members as _declared_members,
    member_bound_bytes,
)

NATIVE_SOURCE_RECHECK_REQUEST_PROFILE = (
    "mumei.native-source-recheck-request/v1"
)
NATIVE_SOURCE_RECHECK_REPORT_PROFILE = (
    "mumei.native-source-recheck-report/v1"
)


# Terminal exit-code mapping mirrors the native-bundle recheck-source
# contract, restricted to unambiguous codes: 0 = identities consistent
# and the source postcondition rechecked; 3 = inconclusive. Exit 1 is
# shared by a refuted postcondition and every `Err` path, so it gets
# no claimed outcome.
SOURCE_RECHECK_OUTCOMES = {0: "rechecked", 3: "inconclusive"}

# The six semantic acceptance checks of the C02 contract. A
# `rechecked` run proves the pinned bundle's declared identities
# match the declared inputs — file_identity — and that the source
# postcondition re-proved within the profile — claim_truth. Producer
# authenticity, freshness, semantic correspondence and artifact
# semantics all need deeper consumers and stay out of the profile.
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
    """Semantic checks a terminal recheck outcome discharges."""

    RECHECKED = frozenset({"file_identity", "claim_truth"})


DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000


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
                raise ValueError(
                    "--output may not overwrite a declared input document"
                )
        except FileNotFoundError:
            continue


def _is_build_id(value: str) -> bool:
    return len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _check_request(args: argparse.Namespace) -> list[str]:
    """Validate the declared request before any attempt is dispatched.

    Returns the declared member list so the fingerprint binds exactly
    the members the Core consumes. A static-shape error raised after a
    completed run would lose the whole report, so everything checkable
    up front fails here as a plain `ValueError` before the attempt is
    dispatched.
    """
    if os.name != "posix":
        raise ValueError("native-source-recheck requires a POSIX host")
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
        raise ValueError(
            "--expected-build-id must be a 64-character lowercase sha256"
        )
    if not 1 <= args.attempt_timeout <= 300_000:
        raise ValueError("--attempt-timeout must be 1..300000 ms")
    # Bound the record before parsing it — enumeration reads it whole.
    try:
        record_size = os.path.getsize(bundle / RECORD_FILE)
    except OSError as exc:
        raise ValueError(f"cannot read declared input: {exc}") from exc
    if record_size > MAX_RECORD_BYTES:
        raise ValueError(
            f"{RECORD_FILE} exceeds the Core input bound "
            f"({MAX_RECORD_BYTES} bytes)"
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


def _attempt_fingerprint(
    args: argparse.Namespace, members: list[str]
) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the Core executable's bytes, every member
    the record declares (the pinned record, the component files and
    each `sources/` member the merge is re-derived from), the declared
    source's bytes and the expected build ID — what the
    recheck-source invocation would consume. The attempt's own
    timeout_ms is the sequence's separate declared field, not part of
    request identity.
    """
    bundle = Path(args.bundle)
    member_hashes = {
        member: _file_sha256(bundle / member) for member in members
    }
    request = {
        "schema_version": NATIVE_SOURCE_RECHECK_REQUEST_PROFILE,
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


def build_source_recheck_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-source-recheck")
    parser.description = (
        "Run a declared Core native bundle source recheck as one "
        "attempt and emit the reconciled lineage plus the declared "
        "source recheck outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle recheck-source`."
        ),
    )
    parser.add_argument(
        "--bundle",
        required=True,
        metavar="DIR",
        help=(
            "Declared native-bundle directory (absolute path) holding "
            "native-bundle.json and its declared members (the component "
            "files plus any `sources/` members a multifile record "
            "pins)."
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
        help="Write the source recheck report JSON here instead of stdout.",
    )
    return parser


def run_source_recheck(args: argparse.Namespace) -> dict:
    """Run the declared native-bundle recheck-source and return the report dict.

    Emits `mumei.native-source-recheck-report/v1`: the reconciled
    lineage, the normalized run record, `inputs_changed` when declared
    bytes drifted mid-run (the claimed outcome is then suppressed), the
    mapped `bundle_check` outcome for uniquely-mapped exit codes,
    and the discharged-check partition on a rechecked run. The produced
    stdout is a fixed diagnostic line — no evidence candidate is
    emitted. Raises `OSError`/`ValueError`/`UnicodeDecodeError` on any
    declared-input failure; the caller treats those as static errors.
    """
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
        "recheck-source",
        "--expected-build-id",
        args.expected_build_id,
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
    # Re-enumerate members from the CURRENT record before re-hashing:
    # the member set derives from the record, so a record swapped
    # mid-run may declare members the pre-run enumeration never
    # fingerprinted. Only a same-set, same-bytes re-hash is consistent.
    try:
        drift_members = _declared_members(Path(args.bundle))
        inputs_changed = (
            _attempt_fingerprint(args, drift_members) != fingerprint
        )
    except (OSError, ValueError):
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    # recheck-source prints only a fixed diagnostic line on a clean
    # rechecked exit; mismatched and failed runs produced no bytes
    # to bind.
    if exit_code == 0 and not inputs_changed:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": NATIVE_SOURCE_RECHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        # The run consumed bytes that no longer match the declared
        # request: its exit code is not a verdict on this
        # fingerprint. Surface the drift; claim no outcome.
        report["inputs_changed"] = True
    elif exit_code in SOURCE_RECHECK_OUTCOMES:
        report["source_recheck"] = SOURCE_RECHECK_OUTCOMES[exit_code]
        if report["source_recheck"] == "rechecked":
            report["discharged_checks"] = sorted(DischargedChecks.RECHECKED)
            report["checks_not_performed"] = sorted(
                CHECK_VOCABULARY - DischargedChecks.RECHECKED
            )
    return report


def main_source_recheck(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_source_recheck_parser().parse_args()
    try:
        report = run_source_recheck(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-source-recheck: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
