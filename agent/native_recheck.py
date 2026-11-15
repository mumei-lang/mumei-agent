"""C02/C10 native-recheck route: declared Core native consumer recheck.

`python -m agent native-recheck` runs `<core> native-bundle recheck-llvm
--expected-build-id <id> --json <bundle> <source>` inside the C11
dispatch lifecycle: a declared request — the Core executable's bytes,
the pinned bundle's declared member bytes, the caller-supplied source's
bytes and the trusted-channel build ID — is fingerprinted, a fresh
``AttemptSequence`` is keyed to it, one reserved attempt is observed by
``AttemptRunner``, and the reconciled lineage is published
compare-and-set.

This is the native consumer companion of `verify-recheck`: where
verify-recheck replays a saved source-evidence record, native-recheck
re-runs the pinned snapshot identities plus the fresh C03 source
postcondition plus the C09-derived native LLVM body/wrapper comparison
against an externally supplied bundle — and on success emits the
``mumei.native-consumer-evidence/v1`` report (three separate
``mumei.verification-evidence/v1`` records: bundle identity, fresh
source postcondition, source-to-LLVM user-body correspondence).

Selection rule: only an ``exited`` run with ``exit_code == 0``
(``EquivalentWithinProfile``) selects — `recheck-llvm --json` prints
the consumer evidence on stdout only then. Different/UB/refuted runs
and every static failure exit 1 with no bytes to bind; inconclusive
exits 3. The route re-hashes every declared input after the observed
run; when any byte drifted mid-run it skips the selection, claims no
outcome and reports ``inputs_changed``.

The report carries a ``recheck`` field naming the terminal outcome
only when the exit code is unambiguous: ``"equivalent"`` (0) or
``"inconclusive"`` (3). Exit 1 conflates a failed comparison with every
static failure — unreadable/non-UTF-8 input, invalid build ID, pinned
record mismatch, outside-profile source or snapshot — so the route
names it only through the lineage's ``exit_code``, never as a claimed
outcome. No ``record_evidence_check`` runs here: the produced report is
``mumei.native-consumer-evidence/v1`` — an envelope of evidence records
whose own ``acceptance`` is ``not_evaluated`` — so the representation
check/acceptance pair does not apply; the exit code IS the verdict.

Emits ``mumei.native-recheck-report/v1``: the canonical sequence, the
normalized run-result descriptor, the declared recheck outcome and —
only when equivalent — the ``mumei.verifier-evidence-candidate/v1``
handoff for the produced evidence report. The report carries no bundle
or record bytes; the child's output is only observed through its
bounded capture claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

NATIVE_RECHECK_REQUEST_PROFILE = "mumei.native-recheck-request/v1"
NATIVE_RECHECK_REPORT_PROFILE = "mumei.native-recheck-report/v1"

# Mirrors of the Core side's read bounds (src/commands/native_bundle.rs):
# the pinned record is read under 1 MiB, every bundle member under
# 32 MiB, the source under 64 KiB. A declared input the Core cannot
# even read is a static error, not a run.
RECORD_FILE = "native-bundle.json"
MAX_RECORD_BYTES = 1_048_576
MAX_COMPONENT_BYTES = 33_554_432
MAX_SOURCE_BYTES = 65_536

# Bundle members the Core reads via components() — declared in the
# request fingerprint exactly as the Core consumes them.
BUNDLE_MEMBERS = ("program.ll", "program.o", "proof-cert.json", "program")

# Terminal exit-code mapping mirrors the native recheck-llvm contract,
# restricted to unambiguous codes: 0 = EquivalentWithinProfile and
# 3 = Inconclusive. Exit 1 is shared by Different/UndefinedBehavior
# outcomes and every `Err` path, so it gets no claimed outcome.
RECHECK_OUTCOMES = {0: "equivalent", 3: "inconclusive"}

DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_files(bundle: Path) -> list[Path]:
    return [bundle.joinpath(RECORD_FILE)] + [
        bundle.joinpath(name) for name in BUNDLE_MEMBERS
    ]


def _declared_files(args: argparse.Namespace) -> list[Path]:
    return (
        [Path(args.core)]
        + _bundle_files(Path(args.bundle))
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


def _check_request(args: argparse.Namespace) -> None:
    """Validate the declared request before any attempt is dispatched.

    A static-shape error raised after a completed run would lose the
    whole report, so everything checkable up front fails here as a
    plain `ValueError` before the attempt is dispatched.
    """
    if os.name != "posix":
        raise ValueError("native-recheck requires a POSIX host")
    for name, path in (
        ("--core", args.core),
        ("--bundle", args.bundle),
        ("--source", args.source),
    ):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    if not Path(args.bundle).is_dir():
        raise ValueError("--bundle must be a native-bundle directory")
    if not _is_build_id(args.expected_build_id):
        raise ValueError(
            "--expected-build-id must be a 64-character lowercase sha256"
        )
    if not 1 <= args.attempt_timeout <= 300_000:
        raise ValueError("--attempt-timeout must be 1..300000 ms")
    bundle = Path(args.bundle)
    for path, bound in (
        (bundle / RECORD_FILE, MAX_RECORD_BYTES),
        *((bundle / name, MAX_COMPONENT_BYTES) for name in BUNDLE_MEMBERS),
        (Path(args.source), MAX_SOURCE_BYTES),
    ):
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            raise ValueError(f"cannot read declared input: {exc}") from exc
        if size > bound:
            raise ValueError(
                f"{path.name} exceeds the Core input bound ({bound} bytes)"
            )
    _check_output_path(args, _declared_files(args))


def _attempt_fingerprint(args: argparse.Namespace) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the Core executable's bytes, every bundle
    member the Core reads (the pinned record plus the four component
    files), the declared source's bytes and the expected build ID —
    what the recheck-llvm invocation would consume. The attempt's own
    timeout_ms is the sequence's separate declared field, not part of
    request identity.
    """
    bundle = Path(args.bundle)
    members = {
        RECORD_FILE: _file_sha256(bundle / RECORD_FILE),
        **{
            name: _file_sha256(bundle / name)
            for name in BUNDLE_MEMBERS
        },
    }
    request = {
        "schema_version": NATIVE_RECHECK_REQUEST_PROFILE,
        "core": _file_sha256(Path(args.core)),
        "bundle": {"path": str(bundle), "members": members},
        "source": {
            "path": args.source,
            "sha256": _file_sha256(Path(args.source)),
        },
        "expected_build_id": args.expected_build_id,
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_recheck_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="native-recheck")
    parser.description = (
        "Run a declared Core native consumer recheck as one attempt "
        "and emit the reconciled lineage plus the declared recheck "
        "outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`native-bundle recheck-llvm`."
        ),
    )
    parser.add_argument(
        "--bundle",
        required=True,
        metavar="DIR",
        help=(
            "Declared native-bundle directory (absolute path) holding "
            "native-bundle.json, program.ll, program.o, "
            "proof-cert.json and program."
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


def main_recheck(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_recheck_parser().parse_args()
    try:
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
            "recheck-llvm",
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
            inputs_changed = _attempt_fingerprint(args) != fingerprint
        except OSError:
            inputs_changed = True
        record = dispatch.run.record
        exit_code = None
        if record.state == "exited" and record.events:
            exit_code = record.events[-1].exit_code
        # recheck-llvm emits the consumer evidence report only on a
        # clean EquivalentWithinProfile exit; different, refuted and
        # inconclusive runs produced no bytes to bind.
        if exit_code == 0 and not inputs_changed:
            updated = dispatch.sequence.select_result(
                dispatch.captured_output()
            )
        else:
            updated = dispatch.sequence
        published = store.compare_and_set(current, updated)
        report: dict[str, object] = {
            "schema_version": NATIVE_RECHECK_REPORT_PROFILE,
            "sequence": published.to_dict(),
            "normalized": dispatch.run.normalized().to_dict(),
        }
        if inputs_changed:
            # The run consumed bytes that no longer match the declared
            # request: its exit code is not a verdict on this
            # fingerprint. Surface the drift; claim no outcome.
            report["inputs_changed"] = True
        elif exit_code in RECHECK_OUTCOMES:
            report["recheck"] = RECHECK_OUTCOMES[exit_code]
        if published.selected_result is not None:
            report["candidate"] = (
                published.evidence_candidate().to_dict()
            )
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"native-recheck: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
