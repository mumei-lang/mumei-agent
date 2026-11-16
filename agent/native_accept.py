"""C02/C10 native-accept route: declared Core native artifact acceptance.

`python -m agent native-accept` runs `<core> native-bundle
accept-artifact --expected-build-id <id> --json <bundle> <source>`
inside the C11 dispatch lifecycle: a declared request — the Core
executable's bytes, the pinned bundle's declared member bytes (the
component files plus, for multifile records, every `sources/<member>`
the merge is re-derived from), the caller-supplied source's bytes and
the trusted-channel build ID — is fingerprinted, a fresh
``AttemptSequence`` is keyed to it, one reserved attempt is observed by
``AttemptRunner``, and the reconciled lineage is published
compare-and-set.

This is the deepest consumer route: where `native-recheck` stops at the
source postcondition plus LLVM snapshot, `accept-artifact` additionally
rebuilds the pinned object from the pinned IR and relinks the pinned
executable, comparing both byte-for-byte against the bundle, then
reports the whole chain through a bounded acceptance descriptor
(``mumei.native-evidence-acceptance/v1``) — emitted on stdout only on
an accepted outcome.

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
``accept-artifact --json`` prints the acceptance descriptor on stdout
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

Emits ``mumei.native-accept-report/v1``: the canonical sequence, the
normalized run-result descriptor, the declared acceptance outcome and
the discharged-check partition on an accepted run. An ``accepted``
outcome discharges ``artifact_semantics`` — the bundle's user-body
LLVM AND its pinned object/executable bytes correspond to the declared
source's verified semantics under the recorded toolchain, the deepest
layer the pipeline covers — and ``claim_truth`` — the fresh source
postcondition was re-established within the declared profile — both at
representation level. The other four checks stay in
``checks_not_performed`` (producer authenticity, historical execution
and runtime/OS semantics remain outside the profile; the link
argument-vector is recorded-but-not-reproduced inside Core and adds no
claim here either).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

NATIVE_ACCEPT_REQUEST_PROFILE = "mumei.native-accept-request/v1"
NATIVE_ACCEPT_REPORT_PROFILE = "mumei.native-accept-report/v1"

# Mirrors of the Core side's read bounds (src/commands/native_bundle.rs):
# the pinned record is read under 1 MiB, every component member under
# 32 MiB, each source member under 64 KiB. A declared input the Core
# cannot even read is a static error, not a run.
RECORD_FILE = "native-bundle.json"
MAX_RECORD_BYTES = 1_048_576
MAX_COMPONENT_BYTES = 33_554_432
MAX_SOURCE_BYTES = 65_536

# The `files` map's snake_case keys to bundle-relative names — the same
# table as Core's BundleFile::file_name. An unknown key fails closed:
# the record's member set is the honest enumeration of what the Core
# reads.
FILE_MEMBERS = {
    "llvm_ir": "program.ll",
    "object": "program.o",
    "certificate": "proof-cert.json",
    "executable": "program",
}

# Member-name grammar mirror (mumei-core native_bundle::member_name):
# `/`-separated nonempty segments, none dot-prefixed, no `\\` or `:`,
# at most 16 segments. `.` and `..` segments are covered by the
# dot-prefix rule, so a record cannot steer reads outside `sources/`.
MAX_MEMBER_SEGMENTS = 16


def _valid_member_name(name: str) -> bool:
    stem = name[:-3] if name.endswith(".mm") else name
    segments = stem.split("/")
    return bool(stem) and len(segments) <= MAX_MEMBER_SEGMENTS and all(
        segment
        and not segment.startswith(".")
        and "\\" not in segment
        and ":" not in segment
        for segment in segments
    )


def _bundle_member_paths(record: dict) -> list[str]:
    """Enumerate the bundle-relative member paths a record declares.

    The `files` map enumerates component members; a `sources` map (the
    multifile family) enumerates original member texts consumed by the
    merge re-derivation. Fail-closed on shapes outside the record
    contract — a record the agent cannot enumerate is a static error
    before any attempt is dispatched.
    """
    files = record.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("native-bundle.json declares no files map")
    members = []
    for key in sorted(files):
        name = FILE_MEMBERS.get(key)
        if name is None:
            raise ValueError(f"native-bundle.json declares unknown member {key!r}")
        members.append(name)
    sources = record.get("sources")
    if sources is not None:
        if not isinstance(sources, dict):
            raise ValueError("native-bundle.json sources is not a map")
        for name in sorted(sources):
            if not _valid_member_name(name):
                raise ValueError(
                    f"native-bundle.json declares invalid member {name!r}"
                )
            members.append(f"sources/{name}")
    return members


# Terminal exit-code mapping mirrors the native accept-artifact
# contract, restricted to unambiguous codes: 0 = accepted and 3 =
# inconclusive. Exit 1 is shared by a failed reproduction and every
# `Err` path, so it gets no claimed outcome.
ACCEPT_OUTCOMES = {0: "accepted", 3: "inconclusive"}

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


def _declared_members(bundle: Path) -> list[str]:
    """Parse the pinned record and enumerate its declared members."""
    record_bytes = (bundle / RECORD_FILE).read_bytes()
    try:
        record = json.loads(record_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot parse {RECORD_FILE}: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"{RECORD_FILE} is not a JSON object")
    return [RECORD_FILE] + _bundle_member_paths(record)


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
        raise ValueError("native-accept requires a POSIX host")
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
        bound = (
            MAX_RECORD_BYTES
            if member == RECORD_FILE
            else MAX_SOURCE_BYTES
            if member.startswith("sources/")
            else MAX_COMPONENT_BYTES
        )
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
    accept-artifact invocation would consume. The attempt's own
    timeout_ms is the sequence's separate declared field, not part of
    request identity.
    """
    bundle = Path(args.bundle)
    member_hashes = {
        member: _file_sha256(bundle / member) for member in members
    }
    request = {
        "schema_version": NATIVE_ACCEPT_REQUEST_PROFILE,
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


def build_accept_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-accept")
    parser.description = (
        "Run a declared Core native artifact acceptance as one attempt "
        "and emit the reconciled lineage plus the declared acceptance "
        "outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle accept-artifact`."
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


def run_accept(args: argparse.Namespace) -> dict:
    """Run the declared native-accept and return the report dict.

    Emits `mumei.native-accept-report/v1`: the reconciled lineage,
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
        "accept-artifact",
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
        inputs_changed = _attempt_fingerprint(args, members) != fingerprint
    except OSError:
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    # accept-artifact emits the acceptance descriptor only on a clean
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
        "schema_version": NATIVE_ACCEPT_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        # The run consumed bytes that no longer match the declared
        # request: its exit code is not a verdict on this
        # fingerprint. Surface the drift; claim no outcome.
        report["inputs_changed"] = True
    elif exit_code in ACCEPT_OUTCOMES:
        report["acceptance"] = ACCEPT_OUTCOMES[exit_code]
        if report["acceptance"] == "accepted":
            report["discharged_checks"] = sorted(DischargedChecks.ACCEPTED)
            report["checks_not_performed"] = sorted(
                CHECK_VOCABULARY - DischargedChecks.ACCEPTED
            )
    return report


def main_accept(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_accept_parser().parse_args()
    try:
        report = run_accept(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-accept: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
