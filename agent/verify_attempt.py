"""C02 verify-attempt route: declared Core source-evidence production.

`python -m agent verify-attempt` runs `<core> evidence verify-source
<source> --json` inside the C11 dispatch lifecycle: a declared request —
the Core executable's bytes, the source file's bytes and the bounded
solver budgets — is fingerprinted, a fresh ``AttemptSequence`` is keyed
to it, one reserved attempt is observed by ``AttemptRunner``, and the
reconciled lineage is published compare-and-set.

Selection rule: only an ``exited`` run with ``exit_code == 0``
(``EstablishedWithinProfile``) selects — `verify-source` prints the
``mumei.verification-evidence/v1`` record on stdout only then. Refuted
(1) and inconclusive (3) exits publish the terminal lineage with no
selection: the child produced no evidence to bind. The route re-hashes
every declared input after the observed run and skips the selection
when any byte drifted mid-run.

When a result is selected, the route runs the live Core representation
check on the produced bytes (``record_evidence_check`` — the same
declared executable re-checks ``mumei.verification-evidence/v1`` via
``<core> evidence check --stdin --json``) and emits the recorded
``mumei.verifier-evidence-check/v1`` descriptor plus the
``mumei.evidence-check-acceptance/v1`` evaluation. This is the first
route where ``accepted`` can be ``true``: unlike the summary-manifest
produce routes, the selected bytes here ARE evidence-shaped.

Emits ``mumei.verify-attempt-report/v1``: the canonical sequence, the
normalized run-result descriptor, and — only when selected — the
``mumei.verifier-evidence-candidate/v1`` handoff, the check record and
its acceptance. The report carries no evidence bytes; the child's
output is only observed through its bounded capture claim. Recording
stays a host declaration: ``"valid"`` is representation-level only and
acceptance is not claim truth, freshness or semantic correspondence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ATTEMPT_REQUEST_PROFILE = "mumei.verify-attempt-request/v1"
ATTEMPT_REPORT_PROFILE = "mumei.verify-attempt-report/v1"

# Mirror of the Core side's read bound for verify-source inputs
# (mumei-core verification_evidence::MAX_INPUT_BYTES): a declared
# source the Core cannot even read is a static error, not a run.
MAX_SOURCE_BYTES = 65_536

DEFAULT_SOLVER_TIMEOUT_MS = "5000"
DEFAULT_SOLVER_RESOURCE_LIMIT = "1000000"
DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _declared_paths(args: argparse.Namespace) -> list[str]:
    return [args.core, args.source]


def _check_output_path(args: argparse.Namespace, declared: list[str]) -> None:
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


def _check_request(args: argparse.Namespace, check_timeout_ms: int) -> None:
    """Validate the declared request before any attempt is dispatched.

    A static-shape error raised after a completed run would lose the
    whole report, so everything checkable up front fails here as a
    plain `ValueError` before the attempt is dispatched.
    """
    if os.name != "posix":
        raise ValueError("verify-attempt requires a POSIX host")
    for name, path in (("--core", args.core), ("--source", args.source)):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    if not 1 <= args.attempt_timeout <= 300_000:
        raise ValueError("--attempt-timeout must be 1..300000 ms")
    if not 1 <= check_timeout_ms <= 60_000:
        raise ValueError("--check-timeout must be 1..60000 ms")
    try:
        size = os.path.getsize(args.source)
    except OSError as exc:
        raise ValueError(f"cannot read declared source: {exc}") from exc
    if size > MAX_SOURCE_BYTES:
        raise ValueError(
            f"declared source exceeds the Core input bound ({MAX_SOURCE_BYTES} bytes)"
        )
    _check_output_path(args, _declared_paths(args))


def _attempt_fingerprint(args: argparse.Namespace) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the Core executable's bytes, the declared
    source file's bytes and the bounded solver budgets — what the
    produce invocation would consume. The attempt's own timeout_ms is
    the sequence's separate declared field, not part of request
    identity.
    """
    request = {
        "schema_version": ATTEMPT_REQUEST_PROFILE,
        "core": _file_sha256(args.core),
        "source": {"path": args.source, "sha256": _file_sha256(args.source)},
        "solver_timeout_ms": args.solver_timeout,
        "solver_resource_limit": args.solver_resource_limit,
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_attempt_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="verify-attempt")
    parser.description = (
        "Run a declared Core source-evidence production as one attempt "
        "and emit the reconciled lineage plus the live representation "
        "check record and its acceptance evaluation."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path). Used both to "
            "produce the evidence (`evidence verify-source`) and to "
            "re-check it (`evidence check`)."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        metavar="PATH",
        help="Declared .mm source file (absolute path).",
    )
    parser.add_argument(
        "--solver-timeout",
        default=DEFAULT_SOLVER_TIMEOUT_MS,
        metavar="<MS>",
        help="Bounded solver budget passed to `evidence verify-source` (ms).",
    )
    parser.add_argument(
        "--solver-resource-limit",
        default=DEFAULT_SOLVER_RESOURCE_LIMIT,
        metavar="<N>",
        help="Bounded solver resource limit passed to `evidence verify-source`.",
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        default=DEFAULT_ATTEMPT_TIMEOUT_MS,
        metavar="<MS>",
        help="Declared attempt bound in milliseconds.",
    )
    parser.add_argument(
        "--check-timeout",
        type=int,
        default=None,
        metavar="<MS>",
        help=(
            "Bound for the live representation check in milliseconds "
            "(defaults to --attempt-timeout, capped at 60000)."
        ),
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


def main_attempt(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_attempt_parser().parse_args()
    try:
        from agent.core_evidence import (
            MAX_CHECK_TIMEOUT_MS,
            evaluate_evidence_check,
            record_evidence_check,
        )
        from agent.attempt_runner import dispatch_attempt
        from agent.verification_attempt import (
            AttemptSequence,
            AttemptSequenceStore,
        )

        check_timeout_ms = (
            args.check_timeout
            if args.check_timeout is not None
            else min(args.attempt_timeout, MAX_CHECK_TIMEOUT_MS)
        )
        _check_request(args, check_timeout_ms)

        fingerprint = _attempt_fingerprint(args)
        argv = (
            args.core,
            "evidence",
            "verify-source",
            args.source,
            "--json",
            "--solver-timeout",
            args.solver_timeout,
            "--solver-resource-limit",
            args.solver_resource_limit,
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
        # verify-source emits the evidence record only on a clean
        # `EstablishedWithinProfile` exit; refuted (1) and inconclusive
        # (3) runs produced no bytes to bind.
        if (
            dispatch.run.record.state == "exited"
            and dispatch.run.record.events[-1].exit_code == 0
            and not inputs_changed
        ):
            updated = dispatch.sequence.select_result(
                dispatch.captured_output()
            )
        else:
            updated = dispatch.sequence
        published = store.compare_and_set(current, updated)
        report: dict[str, object] = {
            "schema_version": ATTEMPT_REPORT_PROFILE,
            "sequence": published.to_dict(),
            "normalized": dispatch.run.normalized().to_dict(),
        }
        if published.selected_result is not None:
            report["candidate"] = (
                published.evidence_candidate().to_dict()
            )
            check = record_evidence_check(
                published,
                dispatch.captured_output(),
                core_executable=args.core,
                timeout_ms=check_timeout_ms,
            )
            report["evidence_check"] = check.to_dict()
            report["acceptance"] = evaluate_evidence_check(
                published, check
            )
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"verify-attempt: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
