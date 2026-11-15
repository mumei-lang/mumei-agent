"""C02 evidence-check route: declared Core representation check.

`python -m agent evidence-check` feeds a saved Evidence record's bytes
to `<core> evidence check --stdin --json` inside the C11 dispatch
lifecycle: a declared request — the Core executable's bytes and the
saved record's bytes — is fingerprinted, a fresh ``AttemptSequence``
is keyed to it, one reserved attempt is observed by ``AttemptRunner``
(the record bytes are written to the child's stdin, the runner's
bounded feed), and the reconciled lineage is published
compare-and-set.

This is the consume-side companion of `verify-attempt`: where
verify-attempt produces a record and checks the SAME process's
output in one flow, evidence-check runs the Core's representation
check as a declared attempt on a record that arrived by any path —
the check itself now carries canonical attempt lineage.

Selection rule: only an ``exited`` run with ``exit_code == 0`` whose
captured stdout parses as the known
``mumei.evidence-representation-check/v1`` diagnostic selects. Any
other exit or unrecognised output publishes the terminal lineage with
no selection and no claimed outcome — the diagnostic IS the contract,
so a record Core rejects (exit 1, no diagnostic bytes) claims nothing.
The route re-hashes every declared input after the observed run; a
mid-run drift skips the selection and reports ``inputs_changed``.

The report's ``representation`` field echoes the diagnostic's declared
value (``"valid"``) only on selection, alongside the diagnostic's own
``checks_not_performed`` — the six semantic duties this check never
claims to assess.

Emits ``mumei.evidence-check-report/v1``: the canonical sequence, the
normalized run-result descriptor, the declared representation outcome
and — only on selection — the ``mumei.verifier-evidence-candidate/v1``
handoff for the produced diagnostic. The report carries no record or
diagnostic bytes beyond the bounded capture claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.core_evidence import MAX_CHECK_TIMEOUT_MS, _DIAGNOSTIC

CHECK_REQUEST_PROFILE = "mumei.evidence-check-request/v1"
CHECK_REPORT_PROFILE = "mumei.evidence-check-report/v1"

# Mirror of the Core side's read bound for evidence inputs
# (mumei-core verification_evidence::MAX_INPUT_BYTES): a declared
# record the Core cannot even read is a static error, not a run.
MAX_INPUT_BYTES = 65_536

DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_request(args: argparse.Namespace) -> None:
    """Validate the declared request before any attempt is dispatched.

    A static-shape error raised after a completed run would lose the
    whole report, so everything checkable up front fails here as a
    plain `ValueError` before the attempt is dispatched.
    """
    if os.name != "posix":
        raise ValueError("evidence-check requires a POSIX host")
    for name, path in (("--core", args.core), ("--evidence", args.evidence)):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    if not 1 <= args.attempt_timeout <= MAX_CHECK_TIMEOUT_MS:
        raise ValueError(
            f"--attempt-timeout must be 1..{MAX_CHECK_TIMEOUT_MS} ms"
        )
    try:
        size = os.path.getsize(args.evidence)
    except OSError as exc:
        raise ValueError(f"cannot read declared evidence: {exc}") from exc
    if size > MAX_INPUT_BYTES:
        raise ValueError(
            f"--evidence exceeds the Core input bound ({MAX_INPUT_BYTES} bytes)"
        )
    if args.output is not None:
        out_path = Path(args.output)
        for declared in (args.core, args.evidence):
            try:
                if out_path.samefile(declared):
                    raise ValueError(
                        "--output may not overwrite a declared input document"
                    )
            except FileNotFoundError:
                continue


def _attempt_fingerprint(args: argparse.Namespace) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the Core executable's bytes and the saved
    record's bytes — what the check invocation consumes. The record's
    own labels/paths are never read.
    """
    request = {
        "schema_version": CHECK_REQUEST_PROFILE,
        "core": _file_sha256(args.core),
        "evidence": {
            "path": args.evidence,
            "sha256": _file_sha256(args.evidence),
        },
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_diagnostic(captured: bytes) -> dict | None:
    """Recognise the Core's one accepted v1 diagnostic, or None."""
    try:
        document = json.loads(captured.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return document if document == _DIAGNOSTIC else None


def build_check_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="evidence-check")
    parser.description = (
        "Run a declared Core Evidence representation check as one "
        "attempt and emit the reconciled lineage plus the declared "
        "representation outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`evidence check`."
        ),
    )
    parser.add_argument(
        "--evidence",
        required=True,
        metavar="PATH",
        help=(
            "Declared saved Evidence record (absolute path, a common "
            "mumei.verification-evidence/v1 JSON, at most 65536 bytes); "
            "its bytes are fed to the check on stdin."
        ),
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        default=DEFAULT_ATTEMPT_TIMEOUT_MS,
        metavar="<MS>",
        help=f"Declared attempt bound in ms (max {MAX_CHECK_TIMEOUT_MS}).",
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
        help="Write the check report JSON here instead of stdout.",
    )
    return parser


def run_check(args: argparse.Namespace) -> dict:
    """Run the declared evidence-check and return the report dict.

    Emits `mumei.evidence-check-report/v1`: the reconciled lineage,
    the normalized run record, `inputs_changed` when declared bytes
    drifted mid-run (the claimed outcome is then suppressed), the
    diagnostic's `representation`/`checks_not_performed` when Core
    accepted the record, and the evidence candidate on a selected
    result. Raises `OSError`/`ValueError`/`UnicodeDecodeError` on any
    declared-input failure; the caller treats those as static errors.
    """
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    _check_request(args)

    evidence_bytes = Path(args.evidence).read_bytes()
    fingerprint = _attempt_fingerprint(args)
    argv = (args.core, "evidence", "check", "--stdin", "--json")
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        argv,
        memory_bound_mb=args.memory_bound_mb,
        feed_bytes=evidence_bytes,
    )
    try:
        inputs_changed = _attempt_fingerprint(args) != fingerprint
    except OSError:
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    diagnostic = (
        _parse_diagnostic(dispatch.run.stdout)
        if exit_code == 0 and not inputs_changed
        else None
    )
    # `evidence check` emits the representation diagnostic only when the
    # record is representation-valid; every rejection exits 1 with no
    # diagnostic to bind.
    if exit_code == 0 and not inputs_changed and diagnostic is not None:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": CHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        # The run consumed bytes that no longer match the declared
        # request: its exit code is not a verdict on this
        # fingerprint. Surface the drift; claim no outcome.
        report["inputs_changed"] = True
    elif diagnostic is not None:
        report["representation"] = diagnostic["representation"]
        report["checks_not_performed"] = list(
            diagnostic["checks_not_performed"]
        )
    if published.selected_result is not None:
        report["candidate"] = (
            published.evidence_candidate().to_dict()
        )
    return report


def main_check(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_check_parser().parse_args()
    try:
        report = run_check(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"evidence-check: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
