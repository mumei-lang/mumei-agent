"""C02/C10 native-stderr-accept route: declared stderr acceptance.

`python -m agent native-stderr-accept` runs `<core> native-bundle
accept-stderr --expected-build-id <id> --json <bundle> <source>`
inside the C11 dispatch lifecycle: a declared request — the Core
executable's bytes, the pinned bundle's declared member bytes (the
component files plus, for multifile records, every `sources/<member>`
the merge is re-derived from), the caller-supplied source's bytes and
the trusted-channel build ID — is fingerprinted, a fresh
``AttemptSequence`` is keyed to it, one reserved attempt is observed by
``AttemptRunner``, and the reconciled lineage is published
compare-and-set.

This is the deepest consumer route: `accept-stderr` runs the whole
`recheck-artifact` chain — the pinned object rebuilt from the pinned IR
and the pinned executable relinked, each compared byte-for-byte against
the bundle — and then executes the byte-identical reproduced `program`
once, never the bundle's own copy, under a closed-stdin/stdout
30-second bound, comparing the SHA-256 of its captured stderr against
the record's `expected_stderr_sha256` pin. On a matching observation
it reports the whole chain through a bounded acceptance descriptor
(``mumei.native-evidence-acceptance/v1``) — emitted on stdout only on
an accepted outcome — with ``os_stderr_observation`` in
``checks_performed``. One run under one environment is an observation,
not a history: the descriptor keeps ``historical_execution`` and
``abi_runtime_semantics`` in ``checks_not_performed``, and the route
inherits that boundary — the nested execution is a real subprocess
inside the attempt, so the attempt's memory/time bounds cover it (Core
caps the run itself at 30 seconds).

The bundle members the Core consumes are enumerated from
``native-bundle.json`` itself: the ``files`` map keys (component file
names) plus, for ``mumei.native-multifile-bundle/v1`` records, the
``sources`` member names joined under ``sources/``. Each member name is
validated against the Core member grammar (``/``-separated nonempty
segments, none dot-prefixed, no ``\\`` or ``:``, at most 16 segments)
BEFORE it joins a path, so a hand-crafted record cannot steer the
fingerprint's file reads outside the bundle. A record the agent cannot
even enumerate is a static error, not a run — the Core could not read
it either. Files present on disk but undeclared in the record are never
fingerprinted: the Core does not consume them either.

Selection rule: only an ``exited`` run with ``exit_code == 0`` selects —
``accept-stderr --json`` prints the acceptance descriptor on stdout
only then. Exit 1 conflates a failed reproduction with every static
failure — unreadable input, invalid build ID, pinned record or member
mismatch, outside-profile source — so the route names it only through
the lineage's ``exit_code``, never as a claimed outcome; inconclusive
exits 3. The route re-hashes every declared input after the observed
run; when any byte drifted mid-run it skips the selection, claims no
outcome and reports ``inputs_changed``.

The report carries an ``acceptance`` field naming the terminal outcome
only when the exit code is unambiguous: ``"accepted"`` (0) or
``"inconclusive"`` (3). No evidence candidate is emitted: the
descriptor is anonymous by design — it binds no subject, digest or
provenance and cannot be replayed as Evidence — so there is no
``mumei.verifier-evidence-candidate/v1`` handoff. The captured bytes
still enter the lineage through the selection itself.

Emits ``mumei.native-stderr-accept-report/v1``: the canonical
sequence, the normalized run-result descriptor, the declared
acceptance outcome and the discharged-check partition on an accepted
run. An ``accepted`` outcome discharges ``artifact_semantics`` — the
bundle's user-body LLVM AND its pinned object/executable bytes
correspond to the declared source's verified semantics under the
recorded toolchain, the deepest layer the pipeline covers — and
``claim_truth`` — the fresh source postcondition was re-established
within the declared profile — both at representation level. The
stderr digest match itself is the named ``os_stderr_observation``
check, bound by the record pin. The other runtime-observation checks
stay in ``checks_not_performed``; the ``runtime_observation_semantics``
conjunction awaits a Core descriptor. The remaining C02 checks
(producer authenticity, freshness, file identity and semantic
correspondence) remain outside the profile; the raw link
argument-vector is recorded-but-not-reproduced inside Core and adds
no claim here either.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.core_evidence import RUNTIME_CHECK_VOCABULARY
from agent.native_bundle import (
    FILE_MEMBERS,  # noqa: F401 — re-exported for route consumers/tests
    MAX_RECORD_BYTES,
    MAX_SOURCE_BYTES,
    RECORD_FILE,
    declared_members as _declared_members,
    member_bound_bytes,
)

NATIVE_STDERR_ACCEPT_REQUEST_PROFILE = "mumei.native-stderr-accept-request/v1"
NATIVE_STDERR_ACCEPT_REPORT_PROFILE = "mumei.native-stderr-accept-report/v1"


# Terminal exit-code mapping mirrors the native accept-stderr
# contract, restricted to unambiguous codes: 0 = accepted and 3 =
# inconclusive. Exit 1 is shared by a failed reproduction and every
# `Err` path, so it gets no claimed outcome.
STDERR_ACCEPT_OUTCOMES = {0: "accepted", 3: "inconclusive"}

# The six semantic acceptance checks of the C02 contract. An
# `accepted` run proves the pinned bundle's user-body LLVM and its
# pinned object/executable bytes correspond to the declared source's
# verified semantics — the artifact-semantics duty at the deepest layer
# the pipeline covers — and re-establishes the fresh source
# postcondition within the declared profile (claim_truth). Producer
# authenticity, freshness, file identity and semantic correspondence
# checks stay out of the profile.
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
    """Semantic checks a terminal acceptance outcome discharges."""

    ACCEPTED = frozenset({"artifact_semantics", "claim_truth"})


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
        raise ValueError("native-stderr-accept requires a POSIX host")
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


def _attempt_fingerprint(args: argparse.Namespace, members: list[str]) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the Core executable's bytes, every member
    the record declares (the pinned record, the component files and
    each `sources/` member the merge is re-derived from), the declared
    source's bytes and the expected build ID — what the
    accept-stderr invocation would consume. The attempt's own
    timeout_ms is the sequence's separate declared field, not part of
    request identity.
    """
    bundle = Path(args.bundle)
    member_hashes = {
        member: _file_sha256(bundle / member) for member in members
    }
    request = {
        "schema_version": NATIVE_STDERR_ACCEPT_REQUEST_PROFILE,
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


def build_stderr_accept_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-stderr-accept")
    parser.description = (
        "Run a declared Core native stderr acceptance as one attempt "
        "and emit the reconciled lineage plus the declared acceptance "
        "outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle accept-stderr`."
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
        help="Write the accept report JSON here instead of stdout.",
    )
    return parser


def run_stderr_accept(args: argparse.Namespace) -> dict:
    """Run the declared native-stderr-accept and return the report dict.

    Emits `mumei.native-stderr-accept-report/v1`: the reconciled lineage,
    the normalized run record, `inputs_changed` when declared bytes
    drifted mid-run (the claimed outcome is then suppressed), the
    mapped `acceptance` outcome for uniquely-mapped exit codes, and
    the discharged-check partition on an accepted run. The produced
    descriptor is anonymous — no evidence candidate is emitted. Raises
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
        "accept-stderr",
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
    # accept-stderr emits the acceptance descriptor only on a clean
    # accepted exit; different, refuted and inconclusive runs produced
    # no bytes to bind.
    if exit_code == 0 and not inputs_changed:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": NATIVE_STDERR_ACCEPT_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
        "expected_build_id": args.expected_build_id,
        "checks_not_performed": sorted(CHECK_VOCABULARY | RUNTIME_CHECK_VOCABULARY),
    }
    if inputs_changed:
        # The run consumed bytes that no longer match the declared
        # request: its exit code is not a verdict on this
        # fingerprint. Surface the drift; claim no outcome.
        report["inputs_changed"] = True
    elif exit_code in STDERR_ACCEPT_OUTCOMES:
        report["acceptance"] = STDERR_ACCEPT_OUTCOMES[exit_code]
        if report["acceptance"] == "accepted":
            report["discharged_checks"] = sorted(
                DischargedChecks.ACCEPTED | {"os_stderr_observation"}
            )
            report["checks_not_performed"] = sorted(
                (CHECK_VOCABULARY - DischargedChecks.ACCEPTED)
                | (RUNTIME_CHECK_VOCABULARY - {"os_stderr_observation"})
            )
    return report


def main_stderr_accept(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_stderr_accept_parser().parse_args()
    try:
        report = run_stderr_accept(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-stderr-accept: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
