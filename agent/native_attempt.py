"""C02/C10 native-attempt route: declared Core native bundle production.

`python -m agent native-attempt` runs `<core> native-bundle build
<source> -o <dir>` inside the C11 dispatch lifecycle: a declared
request — the Core executable's bytes, the declared source file's
bytes and the declared bundle output path — is fingerprinted, a fresh
``AttemptSequence`` is keyed to it, one reserved attempt is observed
by ``AttemptRunner``, and the reconciled lineage is published
compare-and-set.

This is the native produce companion of `verify-attempt` (source
evidence) and `native-recheck` (bundle consumer recheck): where those
routes observe a JSON document on stdout, `native-bundle build` writes
the ``mumei.native-bundle/v1`` directory — `native-bundle.json`,
`program.ll`, `program.o`, `proof-cert.json`, `program` — and prints
a `Build ID: <sha256>` line. The route therefore selects on three
post-conditions, not on the exit code alone: an ``exited`` run with
``exit_code == 0``, a parseable Build ID line in the bounded captured
stdout, and every member the produced record declares present after
the run (the component files plus, for a multifile record, each
``sources/`` member — an unparseable record is incomplete).

The route re-hashes every declared input after the observed run; when
any byte drifted mid-run it skips the selection, claims no outcome and
reports ``inputs_changed``. Bundle members are outputs — they are
never hashed into the request and their bytes never enter the report;
the produced directory's identity is the Build ID the Core printed
(the SHA-256 of `native-bundle.json`), which a later `native-recheck`
call can pin through `--expected-build-id`.

Emits ``mumei.native-attempt-report/v1``: the canonical sequence, the
normalized run-result descriptor, the declared ``build_id`` when it was
observed on a clean run, and — only when selected — the
``mumei.verifier-evidence-candidate/v1`` handoff for the captured
output. The report carries no bundle bytes; the child's output is only
observed through its bounded capture claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from agent.native_bundle import MAX_RECORD_BYTES, declared_members

NATIVE_ATTEMPT_REQUEST_PROFILE = "mumei.native-attempt-request/v1"
NATIVE_ATTEMPT_REPORT_PROFILE = "mumei.native-attempt-report/v1"

# Mirror of the Core side's read bound for native-bundle inputs
# (src/commands/native_bundle.rs): a declared source the Core cannot
# even read is a static error, not a run.
MAX_SOURCE_BYTES = 65_536

# The bundle record member — its sha256 is the Build ID a
# `native-recheck --expected-build-id` call pins.
RECORD_FILE = "native-bundle.json"

# The members every produced bundle must hold — the component files
# plus the record itself. A produced record may declare additional
# members (a multifile bundle's `sources/` members); `_bundle_complete`
# verifies every member the produced record declares, not just this
# fixed set.
BUNDLE_MEMBERS = (
    RECORD_FILE,
    "program.ll",
    "program.o",
    "proof-cert.json",
    "program",
)

# `native-bundle build` prints `Build ID: <64-hex>` on stdout.
_BUILD_ID_PATTERN = re.compile(r"^Build ID: ([0-9a-f]{64})$", re.MULTILINE)

DEFAULT_ATTEMPT_TIMEOUT_MS = 60_000


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declared_files(args: argparse.Namespace) -> list[Path]:
    return [Path(args.core), Path(args.source)]


def _check_output_path(args: argparse.Namespace, declared: list[Path]) -> None:
    if args.output is None:
        return
    out_path = Path(args.output)
    # The bundle is a write target, not a declared input — but letting
    # the report land on the directory or on a member's path would
    # corrupt the produced bundle after selection.
    protected = declared + [Path(args.bundle)] + [
        Path(args.bundle).joinpath(name) for name in BUNDLE_MEMBERS
    ]
    for protected_path in protected:
        try:
            if out_path.samefile(protected_path):
                raise ValueError(
                    "--output may not overwrite a declared input "
                    "or bundle output"
                )
        except FileNotFoundError:
            continue


def _check_request(args: argparse.Namespace) -> None:
    """Validate the declared request before any attempt is dispatched.

    A static-shape error raised after a completed run would lose the
    whole report, so everything checkable up front fails here as a
    plain `ValueError` before the attempt is dispatched.
    """
    if os.name != "posix":
        raise ValueError("native-attempt requires a POSIX host")
    for name, path in (
        ("--core", args.core),
        ("--source", args.source),
        ("--bundle", args.bundle),
    ):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    if not 1 <= args.attempt_timeout <= 300_000:
        raise ValueError("--attempt-timeout must be 1..300000 ms")
    try:
        size = os.path.getsize(args.source)
    except OSError as exc:
        raise ValueError(f"cannot read declared source: {exc}") from exc
    if size > MAX_SOURCE_BYTES:
        raise ValueError(
            f"declared source exceeds the Core input bound ({MAX_SOURCE_BYTES} bytes)"
        )
    _check_output_path(args, _declared_files(args))


def _attempt_fingerprint(args: argparse.Namespace) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the Core executable's bytes, the declared
    source file's bytes and the declared bundle output path — what the
    produce invocation consumes and where it writes. The produced
    bundle's bytes are outputs: they never enter the request, so a
    pre-existing directory's contents do not drift the identity.
    """
    request = {
        "schema_version": NATIVE_ATTEMPT_REQUEST_PROFILE,
        "core": _file_sha256(Path(args.core)),
        "source": {
            "path": args.source,
            "sha256": _file_sha256(Path(args.source)),
        },
        "bundle": {"path": args.bundle},
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_build_id(captured: bytes) -> str | None:
    try:
        text = captured.decode("utf-8")
    except UnicodeDecodeError:
        return None
    match = _BUILD_ID_PATTERN.search(text)
    if match is None:
        return None
    return match.group(1)


def _bundle_complete(bundle: Path) -> bool:
    """Every member the produced record declares must exist on disk.

    The fixed member set is the fast pre-check; the produced record is
    then enumerated the same way the consumer routes
    (`native-recheck`, `native-accept`) enumerate it, so a multifile
    bundle missing a declared `sources/` member is not a selectable
    production either. An unparseable record fails the enumeration —
    such a bundle is incomplete by definition.
    """
    if not all(
        bundle.joinpath(name).is_file() for name in BUNDLE_MEMBERS
    ):
        return False
    record_path = bundle.joinpath(RECORD_FILE)
    try:
        if os.path.getsize(record_path) > MAX_RECORD_BYTES:
            return False
        members = declared_members(bundle)
    except (OSError, ValueError):
        return False
    return all(bundle.joinpath(member).is_file() for member in members)


def build_attempt_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-attempt")
    parser.description = (
        "Run a declared Core native bundle production as one attempt "
        "and emit the reconciled lineage plus the declared Build ID."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle build`."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        metavar="PATH",
        help=(
            "Declared .mm source (absolute path, at most 65536 bytes) "
            "the bundle is built from."
        ),
    )
    parser.add_argument(
        "--bundle",
        required=True,
        metavar="DIR",
        help=(
            "Declared bundle output directory (absolute path) the "
            "Core writes the mumei.native-bundle/v1 members into."
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
        help="Write the attempt report JSON here instead of stdout.",
    )
    return parser


def run_attempt(args: argparse.Namespace) -> dict:
    """Run the declared native-attempt and return the report dict.

    Emits `mumei.native-attempt-report/v1`: the reconciled lineage,
    the normalized run record, `inputs_changed` when declared bytes
    drifted mid-run (the claimed build ID is then suppressed), the
    observed `build_id`, and the evidence candidate on a selected
    result. Raises `OSError`/`ValueError`/`UnicodeDecodeError` on any
    declared-input failure; the caller treats those as static errors.
    """
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    _check_request(args)

    fingerprint = _attempt_fingerprint(args)
    argv = (
        args.core,
        "native-bundle",
        "build",
        args.source,
        "-o",
        args.bundle,
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
        inputs_changed = _attempt_fingerprint(args) != fingerprint
    except OSError:
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    build_id = (
        _parse_build_id(dispatch.run.stdout)
        if exit_code == 0 and not inputs_changed
        else None
    )
    # `native-bundle build` writes the bundle directory as a side
    # effect: an exit 0 without a parseable Build ID, without the full
    # declared member set, or whose printed ID does not match the
    # sha256 of native-bundle.json (the identity a later
    # `native-recheck --expected-build-id` pins) is not a selectable
    # production — and the printed value is not claimable either.
    verified_build_id = None
    if exit_code == 0 and not inputs_changed and build_id is not None:
        record_path = Path(args.bundle).joinpath(RECORD_FILE)
        if _bundle_complete(Path(args.bundle)):
            try:
                if _file_sha256(record_path) == build_id:
                    verified_build_id = build_id
            except OSError:
                pass
    if verified_build_id is not None:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": NATIVE_ATTEMPT_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        # The run consumed bytes that no longer match the declared
        # request: its exit code is not a verdict on this
        # fingerprint. Surface the drift; claim no build ID.
        report["inputs_changed"] = True
    elif verified_build_id is not None:
        report["build_id"] = verified_build_id
    if published.selected_result is not None:
        report["candidate"] = (
            published.evidence_candidate().to_dict()
        )
    return report


def main_attempt(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_attempt_parser().parse_args()
    try:
        report = run_attempt(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-attempt: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
