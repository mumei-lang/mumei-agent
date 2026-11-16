"""C02/C10 native-evidence-recheck route: declared saved-Evidence replay.

`python -m agent native-evidence-recheck` runs `<core> native-bundle
recheck-evidence --expected-build-id <id> <bundle> <source>
<evidence>` inside the C11 dispatch lifecycle: a declared request —
the Core executable's bytes, the pinned bundle's declared member
bytes, the caller-supplied source's bytes, the saved consumer-Evidence
envelope's bytes and the trusted-channel build ID — is fingerprinted,
a fresh ``AttemptSequence`` is keyed to it, one reserved attempt is
observed by ``AttemptRunner``, and the reconciled lineage is
published compare-and-set.

This is the deepest consumer replay: where `native-recheck` produces
a fresh ``mumei.native-consumer-evidence/v1`` envelope,
`recheck-evidence` replays a SAVED envelope — decoded under the
Core's own shape gate — against the fresh pinned source/LLVM
rechecks and accepts only when the saved report equals the fresh one
record-for-record. Consistency is not acceptance: the envelope's own
``acceptance`` stays ``not_evaluated`` — the route verifies a saved
report still reproduces, not that it was authentic or fresh when
issued.

The bundle members the Core consumes are enumerated from
``native-bundle.json`` itself — the same enumeration `native-recheck`
and `native-accept` share through ``agent.native_bundle``: the
``files`` map's component members plus, for
``mumei.native-multifile-bundle/v1`` records, every
``sources/<member>`` the merge is re-derived from. The saved evidence
file is a fourth declared input, bounded at the Core's
``MAX_EVIDENCE_BYTES`` (1 MiB) before the attempt is dispatched.

Selection rule: only an ``exited`` run with ``exit_code == 0``
selects — `recheck-evidence` prints its confirmation line on stdout
only then. Exit 1 conflates a genuine saved-vs-fresh mismatch (and
the other-family decode failure) with every static failure —
unreadable input, invalid build ID, pinned record or member mismatch,
outside-profile source — so the route names it only through the
lineage's ``exit_code``, never as a claimed outcome; inconclusive
exits 3. The route re-enumerates members and re-hashes every declared
input after the observed run; when any byte drifted mid-run it skips
the selection, claims no outcome and reports ``inputs_changed``.

The report carries an ``evidence_recheck`` field naming the terminal
outcome only when the exit code is unambiguous: ``"consistent"`` (0)
or ``"inconclusive"`` (3). A ``consistent`` run re-establishes the
same two representation-level checks the fresh recheck discharges —
``artifact_semantics`` and ``claim_truth`` — and the outcome itself
names the saved-vs-fresh agreement. The other four checks stay in
``checks_not_performed`` (producer authenticity, freshness and
runtime/OS semantics remain outside the profile).

No ``mumei.verifier-evidence-candidate/v1`` handoff: the saved
envelope is the declared INPUT being replayed, not a produced
artifact — the captured confirmation text enters the lineage through
the selection itself.

Emits ``mumei.native-evidence-recheck-report/v1``: the canonical
sequence, the normalized run-result descriptor and the declared
evidence-recheck outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.native_bundle import (
    MAX_EVIDENCE_BYTES,
    MAX_RECORD_BYTES,
    MAX_SOURCE_BYTES,
    RECORD_FILE,
    declared_members,
    member_bound_bytes,
)

NATIVE_EVIDENCE_RECHECK_REQUEST_PROFILE = (
    "mumei.native-evidence-recheck-request/v1"
)
NATIVE_EVIDENCE_RECHECK_REPORT_PROFILE = (
    "mumei.native-evidence-recheck-report/v1"
)


# Terminal exit-code mapping mirrors the native recheck-evidence
# contract, restricted to unambiguous codes: 0 = the saved envelope is
# consistent with the fresh pinned recheck and 3 = Inconclusive. Exit 1
# is shared by a genuine saved-vs-fresh mismatch and every `Err` path,
# so it gets no claimed outcome.
EVIDENCE_RECHECK_OUTCOMES = {0: "consistent", 3: "inconclusive"}

# The six semantic acceptance checks of the C02 contract. A
# `consistent` replay means the fresh recheck underneath it
# re-established the pinned bundle's user-body LLVM correspondence and
# the fresh source postcondition — the same two checks a bare
# `native-recheck` equivalent run discharges.
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
    """Semantic checks a terminal evidence-recheck outcome discharges."""

    CONSISTENT = frozenset({"artifact_semantics", "claim_truth"})


DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declared_files(
    args: argparse.Namespace, members: list[str]
) -> list[Path]:
    bundle = Path(args.bundle)
    return (
        [Path(args.core)]
        + [bundle / member for member in members]
        + [Path(args.source), Path(args.evidence)]
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
        raise ValueError("native-evidence-recheck requires a POSIX host")
    for name, path in (
        ("--core", args.core),
        ("--bundle", args.bundle),
        ("--source", args.source),
        ("--evidence", args.evidence),
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
    members = declared_members(bundle)
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
    for flag, path_arg, bound in (
        ("--source", args.source, MAX_SOURCE_BYTES),
        ("--evidence", args.evidence, MAX_EVIDENCE_BYTES),
    ):
        try:
            size = os.path.getsize(path_arg)
        except OSError as exc:
            raise ValueError(f"cannot read declared input: {exc}") from exc
        if size > bound:
            raise ValueError(
                f"{Path(path_arg).name} exceeds the Core input bound "
                f"({bound} bytes)"
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
    source's bytes, the saved evidence envelope's bytes and the
    expected build ID — what the recheck-evidence invocation would
    consume. The attempt's own timeout_ms is the sequence's separate
    declared field, not part of request identity.
    """
    bundle = Path(args.bundle)
    member_hashes = {
        member: _file_sha256(bundle / member) for member in members
    }
    request = {
        "schema_version": NATIVE_EVIDENCE_RECHECK_REQUEST_PROFILE,
        "core": _file_sha256(Path(args.core)),
        "bundle": {"path": str(bundle), "members": member_hashes},
        "source": {
            "path": args.source,
            "sha256": _file_sha256(Path(args.source)),
        },
        "evidence": {
            "path": args.evidence,
            "sha256": _file_sha256(Path(args.evidence)),
        },
        "expected_build_id": args.expected_build_id,
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_evidence_recheck_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-evidence-recheck")
    parser.description = (
        "Replay a saved native consumer Evidence envelope against a "
        "fresh pinned recheck as one declared attempt and emit the "
        "reconciled lineage plus the declared outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle recheck-evidence`."
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
        "--evidence",
        required=True,
        metavar="PATH",
        help=(
            "Declared saved consumer-Evidence envelope (absolute "
            "path, at most 1048576 bytes) to replay against the "
            "fresh pinned recheck."
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
        help="Write the evidence-recheck report JSON here instead of stdout.",
    )
    return parser


def run_evidence_recheck(args: argparse.Namespace) -> dict:
    """Run the declared native-evidence-recheck and return the report.

    Emits `mumei.native-evidence-recheck-report/v1`: the reconciled
    lineage, the normalized run record, `inputs_changed` when declared
    bytes drifted mid-run (the claimed outcome is then suppressed) and
    the mapped `evidence_recheck` outcome for uniquely-mapped exit
    codes. No evidence candidate is emitted: the saved envelope is the
    replayed input, not a produced artifact. Raises
    `OSError`/`ValueError`/`UnicodeDecodeError` on any declared-input
    failure; the caller treats those as static errors.
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
        "recheck-evidence",
        "--expected-build-id",
        args.expected_build_id,
        args.bundle,
        args.source,
        args.evidence,
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
        drift_members = declared_members(Path(args.bundle))
        inputs_changed = (
            _attempt_fingerprint(args, drift_members) != fingerprint
        )
    except (OSError, ValueError):
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    # recheck-evidence prints its confirmation line only on a clean
    # consistent exit; mismatched, refuted and inconclusive runs
    # produced no bytes to bind.
    if exit_code == 0 and not inputs_changed:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": NATIVE_EVIDENCE_RECHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        # The run consumed bytes that no longer match the declared
        # request: its exit code is not a verdict on this
        # fingerprint. Surface the drift; claim no outcome.
        report["inputs_changed"] = True
    elif exit_code in EVIDENCE_RECHECK_OUTCOMES:
        report["evidence_recheck"] = EVIDENCE_RECHECK_OUTCOMES[exit_code]
        if report["evidence_recheck"] == "consistent":
            report["discharged_checks"] = sorted(DischargedChecks.CONSISTENT)
            report["checks_not_performed"] = sorted(
                CHECK_VOCABULARY - DischargedChecks.CONSISTENT
            )
    return report


def main_evidence_recheck(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_evidence_recheck_parser().parse_args()
    try:
        report = run_evidence_recheck(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-evidence-recheck: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
