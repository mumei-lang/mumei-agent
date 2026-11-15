"""C02 verify-recheck route: declared Core source-evidence recheck.

`python -m agent verify-recheck` runs `<core> evidence recheck-source
<evidence> --source <source> --json` inside the C11 dispatch lifecycle:
a declared request — the Core executable's bytes, the saved Evidence
record's bytes, the caller-supplied source's bytes and the bounded
solver budgets — is fingerprinted, a fresh ``AttemptSequence`` is keyed
to it, one reserved attempt is observed by ``AttemptRunner``, and the
reconciled lineage is published compare-and-set.

This is the C02 freshness companion of `verify-attempt`: where
verify-attempt produces a fresh evidence record, verify-recheck
re-runs the same restricted source query against a SAVED record —
Core detects a stale, tampered or profile-drifted record without any
saved label/path being read.

Selection rule: only an ``exited`` run with ``exit_code == 0``
(``Consistent``) selects — `recheck-source` prints the
``mumei.source-evidence-recheck/v1`` diagnostic on stdout only then.
Refuted (1) and inconclusive (3) exits publish the terminal lineage
with no selection: the child produced no diagnostic to bind. The route
re-hashes every declared input after the observed run; when any byte
drifted mid-run it skips the selection, claims no recheck outcome
(the observed exit code applies to bytes outside the declared
request) and reports ``inputs_changed``.

The report carries a ``recheck`` field naming the terminal outcome
only when the exit code is unambiguous: ``"consistent"`` (0) or
``"inconclusive"`` (3). Exit 1 conflates ``Refuted`` with every
static failure — read/UTF-8/budget errors AND ``Invalid`` /
``InconsistentSavedEvidence`` (the stale-or-tampered case this route
exists to detect) all exit 1 in Core's contract — so the route names
it only through the lineage's ``exit_code``, never as a claimed
outcome. Unlike verify-attempt, no
``record_evidence_check`` runs here: the produced diagnostic is
``mumei.source-evidence-recheck/v1``, not a
``mumei.verification-evidence/v1`` record, so the representation
check/acceptance pair does not apply — the recheck's exit code IS the
semantic verdict (consistency of the saved record against a fresh
same-profile query), not a claim-truth or acceptance receipt.

Emits ``mumei.verify-recheck-report/v1``: the canonical sequence, the
normalized run-result descriptor, the declared recheck outcome and —
only when consistent — the ``mumei.verifier-evidence-candidate/v1``
handoff for the produced diagnostic. The report carries no record
bytes; the child's output is only observed through its bounded capture
claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

RECHECK_REQUEST_PROFILE = "mumei.verify-recheck-request/v1"
RECHECK_REPORT_PROFILE = "mumei.verify-recheck-report/v1"

# Mirror of the Core side's read bound for recheck-source inputs
# (mumei-core verification_evidence::MAX_INPUT_BYTES): a declared
# input the Core cannot even read is a static error, not a run.
MAX_INPUT_BYTES = 65_536

# Terminal exit-code mapping mirrors mumei's recheck_source contract,
# restricted to unambiguous codes: 0 = Consistent and 3 = Inconclusive.
# Exit 1 is shared by Refuted and every `Err` path (unreadable or
# non-UTF-8 input, invalid budget, InvalidSavedEvidence,
# InconsistentSavedEvidence), so it gets no claimed outcome — the
# lineage carries the raw code.
RECHECK_OUTCOMES = {0: "consistent", 3: "inconclusive"}

DEFAULT_SOLVER_TIMEOUT_MS = "5000"
DEFAULT_SOLVER_RESOURCE_LIMIT = "1000000"
DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _declared_paths(args: argparse.Namespace) -> list[str]:
    return [args.core, args.evidence, args.source]


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


def _check_request(args: argparse.Namespace) -> None:
    """Validate the declared request before any attempt is dispatched.

    A static-shape error raised after a completed run would lose the
    whole report, so everything checkable up front fails here as a
    plain `ValueError` before the attempt is dispatched.
    """
    if os.name != "posix":
        raise ValueError("verify-recheck requires a POSIX host")
    for name, path in (
        ("--core", args.core),
        ("--evidence", args.evidence),
        ("--source", args.source),
    ):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    if not 1 <= args.attempt_timeout <= 300_000:
        raise ValueError("--attempt-timeout must be 1..300000 ms")
    for name, path in (
        ("--evidence", args.evidence),
        ("--source", args.source),
    ):
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            raise ValueError(f"cannot read declared input: {exc}") from exc
        if size > MAX_INPUT_BYTES:
            raise ValueError(
                f"{name} exceeds the Core input bound ({MAX_INPUT_BYTES} bytes)"
            )
    _check_output_path(args, _declared_paths(args))


def _attempt_fingerprint(args: argparse.Namespace) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the Core executable's bytes, the saved
    Evidence record's bytes, the declared source file's bytes and the
    bounded solver budgets — what the recheck invocation would consume.
    The attempt's own timeout_ms is the sequence's separate declared
    field, not part of request identity.
    """
    request = {
        "schema_version": RECHECK_REQUEST_PROFILE,
        "core": _file_sha256(args.core),
        "evidence": {"path": args.evidence, "sha256": _file_sha256(args.evidence)},
        "source": {"path": args.source, "sha256": _file_sha256(args.source)},
        "solver_timeout_ms": args.solver_timeout,
        "solver_resource_limit": args.solver_resource_limit,
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_recheck_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="verify-recheck")
    parser.description = (
        "Run a declared Core source-evidence recheck as one attempt "
        "and emit the reconciled lineage plus the declared recheck "
        "outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`evidence recheck-source`."
        ),
    )
    parser.add_argument(
        "--evidence",
        required=True,
        metavar="PATH",
        help=(
            "Declared saved Evidence record (absolute path, a common "
            "mumei.verification-evidence/v1 JSON, at most 65536 bytes)."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        metavar="PATH",
        help=(
            "Declared caller-supplied .mm source (absolute path); the "
            "saved record's own labels/paths are never read."
        ),
    )
    parser.add_argument(
        "--solver-timeout",
        default=DEFAULT_SOLVER_TIMEOUT_MS,
        metavar="<MS>",
        help=(
            "Bounded solver budget passed to `evidence recheck-source` "
            "(ms); must match the producer's explicit budget."
        ),
    )
    parser.add_argument(
        "--solver-resource-limit",
        default=DEFAULT_SOLVER_RESOURCE_LIMIT,
        metavar="<N>",
        help="Bounded solver resource limit passed to `evidence recheck-source`.",
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


def run_recheck(args: argparse.Namespace) -> dict:
    """Run the declared verify-recheck and return the report dict.

    Emits `mumei.verify-recheck-report/v1`: the reconciled lineage,
    the normalized run record, `inputs_changed` when declared bytes
    drifted mid-run (the claimed outcome is then suppressed), the
    mapped `recheck` outcome for uniquely-mapped exit codes, and the
    evidence candidate on a selected result. Raises
    `OSError`/`ValueError`/`UnicodeDecodeError` on any declared-input
    failure; the caller treats those as static errors.
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
        "evidence",
        "recheck-source",
        args.evidence,
        "--source",
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
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    # recheck-source emits the consistency diagnostic only on a
    # clean `Consistent` exit; refuted (1) and inconclusive (3)
    # runs produced no bytes to bind.
    if exit_code == 0 and not inputs_changed:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": RECHECK_REPORT_PROFILE,
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
    return report


def main_recheck(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_recheck_parser().parse_args()
    try:
        report = run_recheck(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"verify-recheck: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
