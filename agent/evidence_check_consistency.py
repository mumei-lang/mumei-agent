"""C02 evidence-check-consistency route: declared cross-record check.

`python -m agent evidence-check-consistency` feeds a saved Evidence
list envelope's bytes to `<core> evidence check-consistency --stdin
--json` inside the C11 dispatch lifecycle: a declared request — the
Core executable's bytes and the saved envelope's bytes — is
fingerprinted, a fresh ``AttemptSequence`` is keyed to it, one
reserved attempt is observed by ``AttemptRunner`` (the envelope
bytes are written to the child's stdin, the runner's bounded feed),
and the reconciled lineage is published compare-and-set.

This is the consistency companion of `evidence-check-list`: where
`check-list` only admits each record's representation (and names
`cross_record_consistency` in `checks_not_performed`),
`check-consistency` compares declared identity pins across the
records — same ``subject.id`` + ``subject.sha256`` pins must agree on
``subject.kind``; same ``obligation_id`` pins must agree on subject,
specification, semantics and method. Outcome fields are claims, not
identity, so they are never compared. Agreement on pins is not
correctness: the diagnostic names ``pin_correctness`` in
`checks_not_performed` — a consistent lie stays consistent.

Selection rule: only an ``exited`` run with ``exit_code == 0`` whose
captured stdout parses as the known
``mumei.evidence-consistency-check/v1`` diagnostic selects — both
``consistent`` outcomes select, because the completed check IS the
contract (Core exits 0 with the diagnostic whether or not conflicts
were found). Any other exit or unrecognised output publishes the
terminal lineage with no selection and no claimed outcome. The route
re-hashes every declared input after the observed run; a mid-run
drift skips the selection and reports ``inputs_changed``.

The report echoes the diagnostic's ``representation``,
``record_count``, ``consistent``, ``conflict_count`` and bounded
``conflicts`` list (Core truncates at 64 entries;
``conflict_count`` keeps the true total) plus its own
``checks_not_performed`` — only on selection.

Emits ``mumei.evidence-check-consistency-report/v1``: the canonical
sequence, the normalized run-result descriptor, the declared
consistency outcome and — only on selection — the
``mumei.verifier-evidence-candidate/v1`` handoff for the produced
diagnostic. The report carries no envelope or diagnostic bytes
beyond the bounded capture claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent.core_evidence import MAX_CHECK_TIMEOUT_MS

CHECK_CONSISTENCY_REQUEST_PROFILE = (
    "mumei.evidence-check-consistency-request/v1"
)
CHECK_CONSISTENCY_REPORT_PROFILE = (
    "mumei.evidence-check-consistency-report/v1"
)

# The list-envelope schema the Core's check-consistency diagnostic names.
LIST_SCHEMA_VERSION = "mumei.verification-evidence-list/v1"

# Mirror of the Core side's read bound for evidence inputs
# (mumei-core verification_evidence::MAX_INPUT_BYTES): a declared
# envelope the Core cannot even read is a static error, not a run.
MAX_INPUT_BYTES = 65_536

# Mirror of the Core side's report bound
# (mumei-core verification_evidence::MAX_CONSISTENCY_CONFLICTS).
MAX_CONFLICTS = 64

# The field names a `mumei.evidence-consistency-check/v1` conflict may
# name — mirror of the comparison set inside Core's
# `verification_evidence::consistency_check`.
CONFLICT_FIELDS = frozenset(
    {
        "subject.kind",
        "subject.id",
        "subject.sha256",
        "specification.id",
        "specification.sha256",
        "semantics.profile",
        "semantics.integer_model",
        "semantics.target_triple",
        "method",
    }
)

EXPECTED_CHECKS_NOT_PERFORMED = [
    "claim_truth",
    "file_identity",
    "freshness",
    "producer_authenticity",
    "semantic_correspondence",
    "artifact_semantics",
    "pin_correctness",
]

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
        raise ValueError("evidence-check-consistency requires a POSIX host")
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


def _attempt_fingerprint(
    args: argparse.Namespace, evidence_bytes: bytes
) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the Core executable's bytes and the envelope
    bytes actually fed to the check — hashing the fed bytes rather
    than re-reading the file keeps a mutation between the feed read
    and the fingerprint from silently binding content the check
    never saw. The envelope's own labels/paths are never read.
    """
    request = {
        "schema_version": CHECK_CONSISTENCY_REQUEST_PROFILE,
        "core": _file_sha256(args.core),
        "evidence": {
            "path": args.evidence,
            "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        },
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _valid_conflict(entry: object, record_count: int) -> bool:
    """One `{"index_a","index_b","field"}` conflict entry, or False.

    Core enumerates record pairs with ``index_a < index_b``, both below
    ``record_count`` — a conflict naming a record outside the envelope
    is not the known diagnostic. ``field`` must be a string before the
    membership test: an unhashable value (list, dict) would otherwise
    raise ``TypeError`` instead of binding nothing.
    """
    if not isinstance(entry, dict) or len(entry) != 3:
        return False
    index_a = entry.get("index_a")
    index_b = entry.get("index_b")
    for value in (index_a, index_b):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            return False
    if not index_a < index_b < record_count:
        return False
    field = entry.get("field")
    return isinstance(field, str) and field in CONFLICT_FIELDS


def _parse_diagnostic(captured: bytes) -> dict | None:
    """Recognise the Core's consistency diagnostic, or None.

    The ``mumei.evidence-consistency-check/v1`` document carries four
    variable fields — ``record_count``, ``consistent``,
    ``conflict_count``, ``conflicts`` — so the fixed fields are
    compared field-for-field and the variable ones are validated:
    ``consistent`` must equal ``conflict_count == 0``, and the
    reported ``conflicts`` list must be exactly
    ``min(conflict_count, 64)`` well-formed entries. Any deviation
    binds nothing — the diagnostic IS the contract.
    """
    try:
        document = json.loads(captured.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict) or len(document) != 9:
        return None
    if (
        document.get("schema_version")
        != "mumei.evidence-consistency-check/v1"
        or document.get("evidence_schema_version") != LIST_SCHEMA_VERSION
        or document.get("representation") != "valid"
        or document.get("acceptance") != "not_evaluated"
        or document.get("checks_not_performed")
        != EXPECTED_CHECKS_NOT_PERFORMED
    ):
        return None
    record_count = document.get("record_count")
    conflict_count = document.get("conflict_count")
    for value in (record_count, conflict_count):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            return None
    if type(document.get("consistent")) is not bool:
        return None
    conflicts = document.get("conflicts")
    if not isinstance(conflicts, list):
        return None
    if document["consistent"] != (conflict_count == 0):
        return None
    if len(conflicts) != min(conflict_count, MAX_CONFLICTS):
        return None
    if not all(
        _valid_conflict(entry, record_count) for entry in conflicts
    ):
        return None
    return document


def build_check_consistency_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="evidence-check-consistency")
    parser.description = (
        "Run a declared Core Evidence list cross-record consistency "
        "check as one attempt and emit the reconciled lineage plus "
        "the declared consistency outcome."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`evidence check-consistency`."
        ),
    )
    parser.add_argument(
        "--evidence",
        required=True,
        metavar="PATH",
        help=(
            "Declared saved Evidence list envelope (absolute path, a "
            "mumei.verification-evidence-list/v1 JSON, at most 65536 "
            "bytes); its bytes are fed to the check on stdin."
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


def run_check_consistency(args: argparse.Namespace) -> dict:
    """Run the declared evidence-check-consistency and return the report.

    Emits `mumei.evidence-check-consistency-report/v1`: the reconciled
    lineage, the normalized run record, `inputs_changed` when declared
    bytes drifted mid-run (the claimed outcome is then suppressed),
    the diagnostic's `representation`/`record_count`/`consistent`/
    `conflict_count`/`conflicts`/`checks_not_performed` when Core
    completed the check, and the evidence candidate on a selected
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
    fingerprint = _attempt_fingerprint(args, evidence_bytes)
    argv = (
        args.core,
        "evidence",
        "check-consistency",
        "--stdin",
        "--json",
    )
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
        inputs_changed = (
            _attempt_fingerprint(
                args, Path(args.evidence).read_bytes()
            )
            != fingerprint
        )
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
    # `evidence check-consistency` emits the diagnostic whether or not
    # conflicts were found — `consistent` is the outcome, not a gate.
    # Only a rejected envelope (exit 1, no diagnostic bytes) claims
    # nothing.
    if exit_code == 0 and not inputs_changed and diagnostic is not None:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": CHECK_CONSISTENCY_REPORT_PROFILE,
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
        report["record_count"] = diagnostic["record_count"]
        report["consistent"] = diagnostic["consistent"]
        report["conflict_count"] = diagnostic["conflict_count"]
        report["conflicts"] = list(diagnostic["conflicts"])
        report["checks_not_performed"] = list(
            diagnostic["checks_not_performed"]
        )
    if published.selected_result is not None:
        report["candidate"] = (
            published.evidence_candidate().to_dict()
        )
    return report


def main_check_consistency(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_check_consistency_parser().parse_args()
    try:
        report = run_check_consistency(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"evidence-check-consistency: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
