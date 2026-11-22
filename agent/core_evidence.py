"""Explicit POSIX handoff to a host-trusted Core, not Evidence acceptance.

No default route uses this API. The host must authorize the call and supply a
trusted executable; an absolute path is not authentication or a sandbox.
"""

import hashlib
import json
import os
import re
import selectors
import subprocess
import threading
import time
from datetime import datetime

from agent.verification_attempt import (
    AttemptEvidenceCheck,
    AttemptOutput,
    AttemptSequence,
)

MAX_DIAGNOSTIC_BYTES = 4096
# Acceptance descriptors repeat per-requirement per-record check
# outcomes, so `evidence accept` output is bounded separately — 4 MiB
# matches the descriptor bound the promotable gate itself reads.
MAX_ACCEPTANCE_DESCRIPTOR_BYTES = 4 * 1024 * 1024
MAX_CHECK_TIMEOUT_MS = 60_000
_CANCEL_POLL_SECONDS = 0.05
_DIAGNOSTIC = {
    "schema_version": "mumei.evidence-representation-check/v1",
    "evidence_schema_version": "mumei.verification-evidence/v1",
    "representation": "valid",
    "acceptance": "not_evaluated",
    "checks_not_performed": [
        "claim_truth",
        "file_identity",
        "freshness",
        "producer_authenticity",
        "semantic_correspondence",
        "artifact_semantics",
    ],
}


class CoreCheckCancelled(ValueError):
    """Host cancellation was observed; no representation result is returned."""


class CoreCheckFailed(ValueError):
    """The check produced no accepted diagnostic; the request itself was valid.

    Distinguished from request-shape errors (which stay plain `ValueError`)
    so a host can record a `\"failed\"` check outcome without misreading a
    malformed request as a checked-and-failed representation.
    """


def check_evidence_representation(
    output: AttemptOutput,
    *,
    core_executable: str,
    timeout_ms: int,
    cancel_event: threading.Event | None = None,
    attempt_sequence: AttemptSequence | None = None,
) -> None:
    """Send original bytes to Core; return None only for its known v1 diagnostic.

    This runs a local executable, independently of adapter permission metadata.
    The host owns executable trust/authorization and canonical output lineage.
    No Evidence/request contract matching, proof, receipt or grade is produced.
    Process creation itself is not interruptible; failed checks allow up to one
    additional second to kill/reap the direct child, not a descendant sandbox.
    An optional host-owned Event is sampled cooperatively, including before
    spawn and normal return. Keep it set: set/clear pulses may not be observed.
    Observed cancellation raises CoreCheckCancelled after direct-child cleanup.
    Cancellation is not an atomic completion handshake or an attempt report.
    An optional sequence requires an exact current-record/output binding before
    spawn; the host still owns canonical values, stdout conflicts and locking.
    It is a snapshot precondition, not freshness or a completion-time guarantee.
    """
    if (
        os.name != "posix"
        or type(output) is not AttemptOutput
        or type(core_executable) is not str
        or not os.path.isabs(core_executable)
        or "\x00" in core_executable
        or type(timeout_ms) is not int
        or not 1 <= timeout_ms <= MAX_CHECK_TIMEOUT_MS
        or (cancel_event is not None and type(cancel_event) is not threading.Event)
        or (
            attempt_sequence is not None
            and type(attempt_sequence) is not AttemptSequence
        )
    ):
        raise ValueError("unsupported Core representation check request")
    if attempt_sequence is not None:
        attempt_sequence.check_output_binding(output)
    try:
        stdout, code = _run_check(
            output.stdout, core_executable, timeout_ms, cancel_event
        )
        _check_cancelled(cancel_event)
        if code != 0:
            raise ValueError
        # Preserve pairs to reject duplicates without depending on key order.
        pairs = json.loads(stdout.decode("utf-8"), object_pairs_hook=tuple)
        if (
            type(pairs) is not tuple
            or len(pairs) != len(_DIAGNOSTIC)
            or dict(pairs) != _DIAGNOSTIC
        ):
            raise ValueError
        _check_cancelled(cancel_event)
    except CoreCheckCancelled:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, RecursionError):
        raise CoreCheckFailed(
            "Core Evidence representation check failed"
        ) from None


def record_evidence_check(
    sequence: AttemptSequence,
    output: AttemptOutput,
    *,
    core_executable: str,
    timeout_ms: int,
    cancel_event: threading.Event | None = None,
) -> AttemptEvidenceCheck:
    """Run the Core representation check and record its declared outcome.

    Returns the `AttemptEvidenceCheck` this sequence's `evidence_check`
    produces: `\"valid\"` when Core returned the known v1 diagnostic,
    `\"failed\"` when the check produced no accepted diagnostic and
    `\"cancelled\"` when the host's cancel event was observed. Static
    errors — an unselected sequence, a foreign/stale output binding, an
    output that is not the selected result or a malformed request —
    propagate as `ValueError` and record nothing; only a real check
    outcome becomes a record.

    `output` must be the selected result itself: the record names the
    candidate's fingerprint, so checking different bytes under the same
    attempt record would mislabel the declaration.

    Recording stays a host declaration, not acceptance, and the record
    carries no bytes: `"valid"` means representation-valid only.
    """
    if type(sequence) is not AttemptSequence:
        raise ValueError("unsupported Core representation check request")
    candidate = sequence.evidence_candidate()
    sequence.check_output_binding(output)
    if output.to_dict()["output_fingerprint"] != candidate.output_fingerprint:
        raise ValueError("evidence check output is not the selected result")
    try:
        check_evidence_representation(
            output,
            core_executable=core_executable,
            timeout_ms=timeout_ms,
            cancel_event=cancel_event,
            attempt_sequence=sequence,
        )
    except CoreCheckCancelled:
        outcome = "cancelled"
    except CoreCheckFailed:
        outcome = "failed"
    else:
        outcome = "valid"
    return sequence.evidence_check(candidate, outcome)


# The `mumei evidence accept` verdict ↔ exit-code contract: the check
# descriptor on stdout is authoritative, but a descriptor whose verdict
# disagrees with the process exit code is a check failure, not a verdict.
_VERDICT_EXIT_CODES = {
    "accepted": 0,
    "rejected": 1,
    "inconclusive": 3,
}


def check_evidence_requirement(
    output: AttemptOutput,
    *,
    core_executable: str,
    requirement_path: str,
    timeout_ms: int,
    cancel_event: threading.Event | None = None,
    attempt_sequence: AttemptSequence | None = None,
) -> dict:
    """Send original bytes to `core evidence accept`; return its descriptor.

    Runs `[core, "evidence", "accept", "--stdin", "--json", "--requirement",
    path]` under the same spawn/cancellation/lineage contract as
    `check_evidence_representation`. Returns the validated
    `mumei.evidence-acceptance/v1` descriptor only when: it is a
    duplicate-free JSON object declaring `acceptance: "evaluated"`; its
    `verdict` (`"accepted"` / `"rejected"` / `"inconclusive"`) agrees
    with the process exit code (0/1/3); `requirement_fingerprint` is a
    64-char hex pin of the requirement bytes Core itself evaluated; and
    `evidence_fingerprint` is the sha256 of the bytes fed on stdin — a
    descriptor answering different bytes is not this check's verdict.
    Anything else raises `CoreCheckFailed`; an invalid representation is
    a failure too — Core rejects it on the decode gate before any
    verdict exists. The check is a host-declared observation only: no
    Evidence, proof or grade is produced and semantic-check content
    stays Core-side."""
    if (
        os.name != "posix"
        or type(output) is not AttemptOutput
        or type(core_executable) is not str
        or not os.path.isabs(core_executable)
        or "\x00" in core_executable
        or type(requirement_path) is not str
        or not os.path.isabs(requirement_path)
        or "\x00" in requirement_path
        or type(timeout_ms) is not int
        or not 1 <= timeout_ms <= MAX_CHECK_TIMEOUT_MS
        or (cancel_event is not None and type(cancel_event) is not threading.Event)
        or (
            attempt_sequence is not None
            and type(attempt_sequence) is not AttemptSequence
        )
    ):
        raise ValueError("unsupported Core requirement check request")
    if attempt_sequence is not None:
        attempt_sequence.check_output_binding(output)
    try:
        # `evidence accept` writes a one-line verdict note to stderr on
        # every non-accepted outcome, and a requirement's check outcomes
        # can exceed the representation-diagnostic bound — stderr stays
        # diagnostic and stdout is bounded as a descriptor.
        stdout, code = _run_check(
            output.stdout,
            core_executable,
            timeout_ms,
            cancel_event,
            argv_tail=(
                "accept",
                "--stdin",
                "--json",
                "--requirement",
                requirement_path,
            ),
            tolerate_stderr=True,
            max_stdout_bytes=MAX_ACCEPTANCE_DESCRIPTOR_BYTES,
        )
        _check_cancelled(cancel_event)
        pairs = json.loads(stdout.decode("utf-8"), object_pairs_hook=tuple)
        if (
            type(pairs) is not tuple
            or len(pairs) != len({key for key, _ in pairs})
        ):
            raise ValueError
        descriptor = dict(pairs)
        verdict = descriptor.get("verdict")
        if (
            descriptor.get("schema_version")
            != "mumei.evidence-acceptance/v1"
            or descriptor.get("acceptance") != "evaluated"
            or _VERDICT_EXIT_CODES.get(verdict) != code
            or not _is_fingerprint(descriptor.get("requirement_fingerprint"))
            or descriptor.get("evidence_fingerprint")
            != hashlib.sha256(output.stdout).hexdigest()
        ):
            raise ValueError
        _check_cancelled(cancel_event)
        return descriptor
    except CoreCheckCancelled:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, RecursionError):
        raise CoreCheckFailed(
            "Core Evidence requirement check failed"
        ) from None


def check_evidence_requirement_list(
    output: AttemptOutput,
    *,
    core_executable: str,
    requirement_list_path: str,
    timeout_ms: int,
    cancel_event: threading.Event | None = None,
    attempt_sequence: AttemptSequence | None = None,
) -> tuple[dict, bytes]:
    """Send original bytes to `core evidence accept --requirement-list`.

    Same spawn/cancellation/lineage contract as
    `check_evidence_requirement`, but the declared requirement is a
    `mumei.evidence-requirement-list/v1` document and the returned
    descriptor is `mumei.evidence-requirement-list-acceptance/v1` — the
    conjunctive, promotable shape a downstream gate consumes. The
    descriptor is validated just as strictly: duplicate-free object,
    `acceptance: "evaluated"`, verdict agreeing with the exit code,
    64-char `requirement_list_fingerprint`, the requirement-list and
    record schema pins, and `evidence_fingerprint` bound to the bytes
    fed on stdin. Returns the validated descriptor together with the
    raw descriptor bytes, so an exporter can hand over the document
    exactly as Core emitted it rather than a re-serialized shape. The
    check stays a host-declared observation only."""
    if (
        os.name != "posix"
        or type(output) is not AttemptOutput
        or type(core_executable) is not str
        or not os.path.isabs(core_executable)
        or "\x00" in core_executable
        or type(requirement_list_path) is not str
        or not os.path.isabs(requirement_list_path)
        or "\x00" in requirement_list_path
        or type(timeout_ms) is not int
        or not 1 <= timeout_ms <= MAX_CHECK_TIMEOUT_MS
        or (cancel_event is not None and type(cancel_event) is not threading.Event)
        or (
            attempt_sequence is not None
            and type(attempt_sequence) is not AttemptSequence
        )
    ):
        raise ValueError("unsupported Core requirement check request")
    if attempt_sequence is not None:
        attempt_sequence.check_output_binding(output)
    try:
        # `evidence accept` writes a one-line verdict note to stderr on
        # every non-accepted outcome, so stderr is a diagnostic stream
        # here — the descriptor contract on stdout carries the verdict.
        # Its stdout bound is the descriptor bound: the conjunctive
        # document repeats per-requirement per-record outcomes and is
        # far larger than a representation diagnostic.
        stdout, code = _run_check(
            output.stdout,
            core_executable,
            timeout_ms,
            cancel_event,
            argv_tail=(
                "accept",
                "--stdin",
                "--json",
                "--requirement-list",
                requirement_list_path,
            ),
            tolerate_stderr=True,
            max_stdout_bytes=MAX_ACCEPTANCE_DESCRIPTOR_BYTES,
        )
        _check_cancelled(cancel_event)
        pairs = json.loads(stdout.decode("utf-8"), object_pairs_hook=tuple)
        if (
            type(pairs) is not tuple
            or len(pairs) != len({key for key, _ in pairs})
        ):
            raise ValueError
        descriptor = dict(pairs)
        verdict = descriptor.get("verdict")
        if (
            descriptor.get("schema_version")
            != "mumei.evidence-requirement-list-acceptance/v1"
            or descriptor.get("acceptance") != "evaluated"
            or _VERDICT_EXIT_CODES.get(verdict) != code
            or not _is_fingerprint(descriptor.get("requirement_list_fingerprint"))
            or descriptor.get("requirement_schema_version")
            != "mumei.evidence-requirement-list/v1"
            or descriptor.get("evidence_schema_version")
            != "mumei.verification-evidence/v1"
            or descriptor.get("evidence_fingerprint")
            != hashlib.sha256(output.stdout).hexdigest()
            or descriptor.get("list_fingerprint") is not None
        ):
            raise ValueError
        _check_cancelled(cancel_event)
        return descriptor, stdout
    except CoreCheckCancelled:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, RecursionError):
        raise CoreCheckFailed(
            "Core Evidence requirement check failed"
        ) from None


def record_evidence_acceptance_list(
    sequence: AttemptSequence,
    output: AttemptOutput,
    *,
    core_executable: str,
    requirement_list_path: str,
    timeout_ms: int,
    cancel_event: threading.Event | None = None,
) -> tuple[AttemptEvidenceCheck, dict | None, bytes | None]:
    """`record_evidence_acceptance` over a declared requirement list.

    Same contract — the record's outcome is the Core `evidence accept`
    verdict — but Core evaluates a `mumei.evidence-requirement-list/v1`
    document and returns the conjunctive
    `mumei.evidence-requirement-list-acceptance/v1` descriptor. The
    third return is the raw descriptor bytes (None when no descriptor
    exists) for the promotable export path."""
    if type(sequence) is not AttemptSequence:
        raise ValueError("unsupported Core requirement check request")
    candidate = sequence.evidence_candidate()
    sequence.check_output_binding(output)
    if output.to_dict()["output_fingerprint"] != candidate.output_fingerprint:
        raise ValueError("evidence check output is not the selected result")
    try:
        descriptor, raw = check_evidence_requirement_list(
            output,
            core_executable=core_executable,
            requirement_list_path=requirement_list_path,
            timeout_ms=timeout_ms,
            cancel_event=cancel_event,
            attempt_sequence=sequence,
        )
    except CoreCheckCancelled:
        outcome, descriptor, raw = "cancelled", None, None
    except CoreCheckFailed:
        outcome, descriptor, raw = "failed", None, None
    else:
        outcome = descriptor["verdict"]
    return sequence.evidence_check(candidate, outcome), descriptor, raw


def record_evidence_acceptance(
    sequence: AttemptSequence,
    output: AttemptOutput,
    *,
    core_executable: str,
    requirement_path: str,
    timeout_ms: int,
    cancel_event: threading.Event | None = None,
) -> tuple[AttemptEvidenceCheck, dict | None]:
    """Run the requirement-declared Core check; record the Core verdict.

    Same contract as `record_evidence_check`, but the record's outcome is
    the Core `evidence accept` verdict (`"accepted"` / `"rejected"` /
    `"inconclusive"`) — or `"failed"`/`"cancelled"` when no verdict
    exists — and the validated descriptor is returned alongside (None
    when no descriptor exists), so the caller can pin the
    `requirement_fingerprint` Core actually evaluated rather than
    re-reading the file. The verdict is Core's declared judgement under
    the host-declared requirement; recording stays a host declaration,
    not acceptance."""
    if type(sequence) is not AttemptSequence:
        raise ValueError("unsupported Core requirement check request")
    candidate = sequence.evidence_candidate()
    sequence.check_output_binding(output)
    if output.to_dict()["output_fingerprint"] != candidate.output_fingerprint:
        raise ValueError("evidence check output is not the selected result")
    try:
        descriptor = check_evidence_requirement(
            output,
            core_executable=core_executable,
            requirement_path=requirement_path,
            timeout_ms=timeout_ms,
            cancel_event=cancel_event,
            attempt_sequence=sequence,
        )
    except CoreCheckCancelled:
        outcome, descriptor = "cancelled", None
    except CoreCheckFailed:
        outcome, descriptor = "failed", None
    else:
        outcome = descriptor["verdict"]
    return sequence.evidence_check(candidate, outcome), descriptor


def evaluate_evidence_check(
    sequence: AttemptSequence,
    check: AttemptEvidenceCheck,
    *,
    requirement_fingerprint: str | None = None,
) -> dict:
    """Normalize a declared check record into an acceptance descriptor.

    Emits ``mumei.evidence-check-acceptance/v1``: whether the record binds
    the sequence's CURRENT `evidence_candidate()` (`candidate_match` — a
    stale or foreign check never counts) and `accepted`, which holds only
    when the record is current AND its outcome is `"valid"` or the
    requirement-declared Core verdict `"accepted"`. A declared
    `requirement_fingerprint` (sha256 of the requirement bytes the check
    ran under) is echoed so consumers pin which requirement the verdict
    answered. This is representation-level acceptance only — the six
    semantic checks remain listed in `checks_not_performed`, and nothing
    here is Evidence, a verdict or a grade promotion. A sequence with no
    selected result raises `ValueError`: there is no current candidate to
    evaluate."""
    if (
        type(sequence) is not AttemptSequence
        or type(check) is not AttemptEvidenceCheck
    ):
        raise ValueError("unsupported evidence check evaluation request")
    if requirement_fingerprint is not None and not _is_fingerprint(
        requirement_fingerprint
    ):
        raise ValueError("invalid requirement fingerprint")
    candidate = sequence.evidence_candidate()
    match = (
        check.request_fingerprint == candidate.request_fingerprint
        and check.attempt_number == candidate.attempt_number
        and check.output_fingerprint == candidate.output_fingerprint
    )
    evaluation = {
        "schema_version": "mumei.evidence-check-acceptance/v1",
        "request_fingerprint": check.request_fingerprint,
        "attempt_number": check.attempt_number,
        "output_fingerprint": check.output_fingerprint,
        "outcome": check.outcome,
        "candidate_match": match,
        "accepted": match and check.outcome in {"valid", "accepted"},
        "checks_not_performed": list(_DIAGNOSTIC["checks_not_performed"]),
    }
    if requirement_fingerprint is not None:
        evaluation["requirement_fingerprint"] = requirement_fingerprint
    return evaluation


def _check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CoreCheckCancelled(
            "Core Evidence representation check cancelled"
        ) from None


def _wait_timeout(deadline: float, cancel_event: threading.Event | None) -> float:
    _check_cancelled(cancel_event)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining if cancel_event is None else min(remaining, _CANCEL_POLL_SECONDS)


def _run_check(
    body: bytes,
    executable: str,
    timeout_ms: int,
    cancel_event: threading.Event | None,
    argv_tail: tuple[str, ...] = ("check", "--stdin", "--json"),
    tolerate_stderr: bool = False,
    max_stdout_bytes: int = MAX_DIAGNOSTIC_BYTES,
) -> tuple[bytes, int]:
    _check_cancelled(cancel_event)
    deadline = time.monotonic() + timeout_ms / 1000
    process = subprocess.Popen(
        [executable, "evidence", *argv_tail],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env={},
    )
    streams = {
        "stdin": process.stdin,
        "stdout": process.stdout,
        "stderr": process.stderr,
    }
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    offset = 0
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in streams.items():
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                if name == "stdin" and not body:
                    stream.close()
                    continue
                selector.register(
                    stream,
                    selectors.EVENT_WRITE if name == "stdin" else selectors.EVENT_READ,
                    name,
                )
            while selector.get_map():
                for key, _ in selector.select(_wait_timeout(deadline, cancel_event)):
                    _check_cancelled(cancel_event)
                    name = key.data
                    stream = streams[name]
                    assert stream is not None
                    if name == "stdin":
                        try:
                            count = os.write(key.fd, body[offset : offset + 4096])
                        except BlockingIOError:
                            continue
                        if not count:
                            raise ValueError
                        offset += count
                        if offset == len(body):
                            selector.unregister(key.fileobj)
                            stream.close()
                    else:
                        buffer = buffers[name]
                        bound = (
                            max_stdout_bytes
                            if name == "stdout"
                            else MAX_DIAGNOSTIC_BYTES
                        )
                        try:
                            chunk = os.read(key.fd, bound + 1 - len(buffer))
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            stream.close()
                        else:
                            buffer.extend(chunk)
                            if len(buffer) > bound:
                                raise ValueError
            while True:
                try:
                    code = process.wait(timeout=_wait_timeout(deadline, cancel_event))
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event is None:
                        raise
            _check_cancelled(cancel_event)
            if buffers["stderr"] and not tolerate_stderr:
                raise ValueError
        return bytes(buffers["stdout"]), code
    finally:
        for stream in streams.values():
            if stream is not None:
                stream.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)


# Core acceptance descriptor schemas the fold recognizes; each names a
# distinct Core-verified scope, so membership is checked rather than the
# scope string reinterpreted.
CORE_ACCEPTANCE_SCHEMAS = frozenset(
    {
        "mumei.source-evidence-acceptance/v1",
        "mumei.native-evidence-acceptance/v1",
    }
)

_CORE_ACCEPTANCE_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "acceptance",
        "accepted",
        "scope",
        "checks_performed",
        "checks_not_performed",
    }
)

# Optional descriptor fields Core may emit on top of the required shape.
_CORE_ACCEPTANCE_OPTIONAL_FIELDS = frozenset({"evidence_fingerprint"})


def _observation_invocation_match(value: object) -> bool:
    """Closed shape of the `invocation` pin the observation route emits."""
    return (
        type(value) is dict
        and frozenset(value)
        == frozenset(
            {
                "argv",
                "stdin",
                "timeout_ms",
                "channel_cap_bytes",
                "environment",
                "working_directory",
            }
        )
        and _string_list(value["argv"])
        and type(value["stdin"]) is str
        and _nonnegative_int(value["timeout_ms"])
        and _nonnegative_int(value["channel_cap_bytes"])
        and type(value["environment"]) is str
        and type(value["working_directory"]) is str
    )


def _observation_host_match(value: object) -> bool:
    """Closed shape of the `host` record the observation route emits."""
    return (
        type(value) is dict
        and frozenset(value) == frozenset({"os", "arch", "family"})
        and all(
            type(value[key]) is str for key in ("os", "arch", "family")
        )
    )


def _producer_signature_match(value: object) -> bool:
    """The `producer_signature` record `evidence accept` emits when
    signature verification ran — every field is optional; the ones
    present must have the right type."""
    if type(value) is not dict:
        return False
    bool_fields = {
        "envelope_match",
        "signature_valid",
        "subject_bound",
        "key_pinned",
        "key_not_revoked",
        "key_authentic",
        "envelope_fresh",
        "registry_authentic",
        "revocation_list_authentic",
        "produced_at_signed",
    }
    digest_fields = {
        "subject_digest",
        "registry_digest",
        "revocation_digest",
    }
    fields = frozenset(value)
    return (
        fields <= bool_fields | digest_fields | {"checks_not_performed"}
        and all(type(value[key]) is bool for key in fields & bool_fields)
        and all(
            _is_fingerprint(value[key])
            for key in fields & digest_fields
        )
        and (
            "checks_not_performed" not in value
            or _string_list(value["checks_not_performed"])
        )
    )


# `mumei.native-evidence-acceptance/v1`-only extras. The observation
# routes emit `invocation`/`host`/`pin_envelope` only when they
# performed one of the runtime-observation checks — enforced by
# _OBSERVATION_REQUIRED_CHECKS below. The object route pins the
# compared artifacts and the machine-TV outcome.
_NATIVE_ACCEPTANCE_EXTRA_FIELDS = {
    "invocation": _observation_invocation_match,
    "host": _observation_host_match,
    "pin_envelope": lambda value: (
        type(value) is str and value in {"recorded", "unrecorded"}
    ),
    "build_id": lambda value: type(value) is str and value != "",
    "llvm_sha256": lambda value: _is_fingerprint(value),
    "object_sha256": lambda value: _is_fingerprint(value),
    "register_convention_assumed": lambda value: type(value) is str,
    "input_domain": lambda value: type(value) is str,
    "functions": lambda value: type(value) is dict,
}

_OBSERVATION_EXTRA_FIELDS = frozenset(
    {"invocation", "host", "pin_envelope"}
)

# `producer_signature` extras admitted per descriptor schema — only
# when the route ran the `producer_signature_binding` check. The
# single-record accept and accept-source descriptors may also carry
# `produced_at_signed`; the list descriptors never do.
_PRODUCER_SIGNATURE_EXTRA_VALIDATORS = {
    "producer_signature": _producer_signature_match,
    "produced_at_signed": lambda value: type(value) is bool,
}
_PRODUCER_SIGNATURE_EXTRA_FIELDS = frozenset(
    _PRODUCER_SIGNATURE_EXTRA_VALIDATORS
)
_PRODUCER_SIGNATURE_DESCRIPTOR_EXTRAS = {
    "mumei.source-evidence-acceptance/v1": _PRODUCER_SIGNATURE_EXTRA_FIELDS,
}


def _producer_signature_admitted(
    descriptor: dict, admitted: frozenset
) -> bool:
    """True when every producer-signature extra on the descriptor is
    admitted for its schema, shape-valid and gated on the binding
    check."""
    extras = (
        frozenset(descriptor) & _PRODUCER_SIGNATURE_EXTRA_FIELDS
    )
    return (
        extras <= admitted
        and all(
            _PRODUCER_SIGNATURE_EXTRA_VALIDATORS[name](descriptor[name])
            for name in extras
        )
        and (
            not extras
            or (
                type(descriptor.get("checks_performed")) is list
                and "producer_signature_binding"
                in descriptor["checks_performed"]
            )
        )
    )
# The single-invocation observations route reports
# `runtime_observation_semantics`; the per-channel routes
# (accept-exit-status/-stdout/-stderr) report only their own channel
# check under the same bounded envelope. Any of the four pins the
# observation extras.
_OBSERVATION_REQUIRED_CHECKS = frozenset(
    {
        "os_exit_status_observation",
        "os_stdout_observation",
        "os_stderr_observation",
        "runtime_observation_semantics",
    }
)

# The conjunctive promotable descriptor Core `evidence accept
# --requirement-list` emits: same `acceptance: "evaluated"` convention,
# but the accepted claim is `verdict` and the evidence pin is exactly
# one of `evidence_fingerprint` (a single record) or `list_fingerprint`
# (a record list), paired with the matching `evidence_schema_version`.
REQUIREMENT_LIST_ACCEPTANCE_SCHEMA = (
    "mumei.evidence-requirement-list-acceptance/v1"
)

_REQUIREMENT_LIST_ACCEPTANCE_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "acceptance",
        "verdict",
        "requirement_schema_version",
        "requirement_list_fingerprint",
        "evidence_schema_version",
        "consistent",
        "conflict_count",
        "conflicts",
        "requirements_evaluated",
        "records_evaluated",
        "requirements",
        "checks_performed",
        "checks_not_performed",
    }
)

# Which `evidence_schema_version` each pin field must pair with — the
# pin and the schema name the same conjunctive input, so a mismatched
# pair is a foreign document, not a different opinion.
_REQUIREMENT_LIST_ACCEPTANCE_PIN_SCHEMAS = {
    "evidence_fingerprint": "mumei.verification-evidence/v1",
    "list_fingerprint": "mumei.verification-evidence-list/v1",
}

_ACCEPTANCE_VERDICTS = frozenset({"accepted", "rejected", "inconclusive"})

# The single-requirement descriptor `evidence accept --requirement`
# emits over one record: a flat verdict document pinning the record by
# `evidence_fingerprint`.
EVIDENCE_ACCEPTANCE_SCHEMA = "mumei.evidence-acceptance/v1"

_EVIDENCE_ACCEPTANCE_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "acceptance",
        "verdict",
        "requirement_schema_version",
        "requirement_fingerprint",
        "evidence_schema_version",
        "evidence_fingerprint",
        "checks",
        "checks_performed",
        "checks_not_performed",
    }
)

# The record-list variant `evidence accept-list --requirement` emits:
# per-record verdicts plus the consistency report, pinning the list
# bytes by `list_fingerprint`.
EVIDENCE_LIST_ACCEPTANCE_SCHEMA = "mumei.evidence-list-acceptance/v1"

_EVIDENCE_LIST_ACCEPTANCE_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "acceptance",
        "verdict",
        "requirement_schema_version",
        "requirement_fingerprint",
        "evidence_schema_version",
        "list_fingerprint",
        "consistent",
        "conflict_count",
        "conflicts",
        "records_evaluated",
        "records",
        "checks_performed",
        "checks_not_performed",
    }
)


def _string_list(value: object) -> bool:
    return type(value) is list and all(type(item) is str for item in value)


def _is_fingerprint(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _verdict(value: object) -> bool:
    return type(value) is str and value in _ACCEPTANCE_VERDICTS


def _acceptance_check_match(value: object) -> bool:
    return (
        type(value) is dict
        and frozenset(value) == frozenset({"name", "outcome"})
        and type(value["name"]) is str
        and type(value["outcome"]) is str
    )


def _acceptance_record_match(value: object) -> bool:
    return (
        type(value) is dict
        and frozenset(value) == frozenset({"index", "verdict", "checks"})
        and _nonnegative_int(value["index"])
        and _verdict(value["verdict"])
        and type(value["checks"]) is list
        and all(
            _acceptance_check_match(check) for check in value["checks"]
        )
    )


def _acceptance_requirement_match(value: object) -> bool:
    return (
        type(value) is dict
        and frozenset(value)
        == frozenset(
            {"index", "requirement_fingerprint", "verdict", "records"}
        )
        and _nonnegative_int(value["index"])
        and _is_fingerprint(value["requirement_fingerprint"])
        and _verdict(value["verdict"])
        and type(value["records"]) is list
        and all(
            _acceptance_record_match(record)
            for record in value["records"]
        )
    )


def _consistency_conflict_match(value: object) -> bool:
    return (
        type(value) is dict
        and frozenset(value) == frozenset({"index_a", "index_b", "field"})
        and _nonnegative_int(value["index_a"])
        and _nonnegative_int(value["index_b"])
        and type(value["field"]) is str
    )


def _evidence_acceptance_match(descriptor: dict) -> bool:
    """Membership for `mumei.evidence-acceptance/v1` —
    `evidence accept --requirement` over a single record. The producer-
    signature extras are admitted when the descriptor ran the binding
    check (`mumei#1315`)."""
    fields = frozenset(descriptor)
    return (
        _EVIDENCE_ACCEPTANCE_REQUIRED_FIELDS <= fields
        and fields
        <= _EVIDENCE_ACCEPTANCE_REQUIRED_FIELDS
        | _PRODUCER_SIGNATURE_EXTRA_FIELDS
        and _producer_signature_admitted(
            descriptor, _PRODUCER_SIGNATURE_EXTRA_FIELDS
        )
        and descriptor["schema_version"] == EVIDENCE_ACCEPTANCE_SCHEMA
        and descriptor["acceptance"] == "evaluated"
        and _verdict(descriptor["verdict"])
        and descriptor["requirement_schema_version"]
        == "mumei.evidence-requirement/v1"
        and _is_fingerprint(descriptor["requirement_fingerprint"])
        and descriptor["evidence_schema_version"]
        == "mumei.verification-evidence/v1"
        and _is_fingerprint(descriptor["evidence_fingerprint"])
        and type(descriptor["checks"]) is list
        and all(
            _acceptance_check_match(check)
            for check in descriptor["checks"]
        )
        and _string_list(descriptor["checks_performed"])
        and _string_list(descriptor["checks_not_performed"])
    )


def _evidence_list_acceptance_match(descriptor: dict) -> bool:
    """Membership for `mumei.evidence-list-acceptance/v1` —
    `evidence accept-list --requirement` over a record-list envelope.
    Only `producer_signature` is admitted as an extra — the list route
    never emits `produced_at_signed`."""
    fields = frozenset(descriptor)
    return (
        _EVIDENCE_LIST_ACCEPTANCE_REQUIRED_FIELDS <= fields
        and fields
        <= _EVIDENCE_LIST_ACCEPTANCE_REQUIRED_FIELDS
        | frozenset({"producer_signature"})
        and _producer_signature_admitted(
            descriptor, frozenset({"producer_signature"})
        )
        and descriptor["schema_version"] == EVIDENCE_LIST_ACCEPTANCE_SCHEMA
        and descriptor["acceptance"] == "evaluated"
        and _verdict(descriptor["verdict"])
        and descriptor["requirement_schema_version"]
        == "mumei.evidence-requirement/v1"
        and _is_fingerprint(descriptor["requirement_fingerprint"])
        and descriptor["evidence_schema_version"]
        == "mumei.verification-evidence-list/v1"
        and _is_fingerprint(descriptor["list_fingerprint"])
        and type(descriptor["consistent"]) is bool
        and _nonnegative_int(descriptor["conflict_count"])
        and type(descriptor["conflicts"]) is list
        and all(
            _consistency_conflict_match(conflict)
            for conflict in descriptor["conflicts"]
        )
        and _nonnegative_int(descriptor["records_evaluated"])
        and type(descriptor["records"]) is list
        and all(
            _acceptance_record_match(record)
            for record in descriptor["records"]
        )
        and _string_list(descriptor["checks_performed"])
        and _string_list(descriptor["checks_not_performed"])
    )



def _requirement_list_acceptance_match(descriptor: dict) -> bool:
    """Closed-shape membership for the conjunctive acceptance descriptor.

    Exactly one pin field is required and must pair with the matching
    `evidence_schema_version`; the nested `requirements`/`records`/
    `checks`/`conflicts` bodies are validated to the same closed shape
    Core emits, so a foreign or malformed document never matches."""
    fields = frozenset(descriptor)
    pins = fields & frozenset(_REQUIREMENT_LIST_ACCEPTANCE_PIN_SCHEMAS)
    return (
        _REQUIREMENT_LIST_ACCEPTANCE_REQUIRED_FIELDS <= fields
        and fields
        <= _REQUIREMENT_LIST_ACCEPTANCE_REQUIRED_FIELDS
        | frozenset(_REQUIREMENT_LIST_ACCEPTANCE_PIN_SCHEMAS)
        | frozenset({"producer_signature"})
        and len(pins) == 1
        and _producer_signature_admitted(
            descriptor, frozenset({"producer_signature"})
        )
        and descriptor["schema_version"] == (
            REQUIREMENT_LIST_ACCEPTANCE_SCHEMA
        )
        and descriptor["acceptance"] == "evaluated"
        and _verdict(descriptor["verdict"])
        and descriptor["requirement_schema_version"]
        == "mumei.evidence-requirement-list/v1"
        and _is_fingerprint(descriptor["requirement_list_fingerprint"])
        and descriptor["evidence_schema_version"]
        == _REQUIREMENT_LIST_ACCEPTANCE_PIN_SCHEMAS[next(iter(pins))]
        and _is_fingerprint(descriptor[next(iter(pins))])
        and type(descriptor["consistent"]) is bool
        and _nonnegative_int(descriptor["conflict_count"])
        and type(descriptor["conflicts"]) is list
        and all(
            _consistency_conflict_match(conflict)
            for conflict in descriptor["conflicts"]
        )
        and _nonnegative_int(descriptor["requirements_evaluated"])
        and _nonnegative_int(descriptor["records_evaluated"])
        and type(descriptor["requirements"]) is list
        and all(
            _acceptance_requirement_match(requirement)
            for requirement in descriptor["requirements"]
        )
        and _string_list(descriptor["checks_performed"])
        and _string_list(descriptor["checks_not_performed"])
    )


# Verdict-shaped acceptance descriptors (requirement-evaluated), keyed
# by schema so the flat source/native shapes stay the default family.
_VERDICT_ACCEPTANCE_MATCHERS = {
    EVIDENCE_ACCEPTANCE_SCHEMA: _evidence_acceptance_match,
    EVIDENCE_LIST_ACCEPTANCE_SCHEMA: _evidence_list_acceptance_match,
    REQUIREMENT_LIST_ACCEPTANCE_SCHEMA: _requirement_list_acceptance_match,
}


def evaluate_core_acceptance(
    descriptor: dict,
    expected_fingerprint: str | None = None,
    descriptor_bytes: bytes | None = None,
) -> dict:
    """Fold a restored Core acceptance descriptor into an evaluation.

    Emits ``mumei.core-acceptance-evaluation/v1``: `descriptor_match`
    holds only for a closed-shape descriptor naming a known Core
    acceptance schema with `acceptance: "evaluated"`, a Boolean
    `accepted`, a non-empty `scope` string and two string-list check
    fields — a foreign or malformed document never counts. `accepted`
    holds only when the descriptor matches AND itself declared
    `accepted: true`. Core may add the optional `evidence_fingerprint`
    field — a 64-char lowercase-hex SHA-256 of the accepted record's
    bytes; a malformed fingerprint breaks the match like any foreign
    field.

    When `expected_fingerprint` is supplied (the record pin an attempt
    binds to — e.g. the evidence-check request's declared
    `evidence.sha256`, the SHA-256 of the record bytes fed to the
    attempt; note a `request_fingerprint` covers the whole request
    manifest, not the record),
    the fold emits `attempt_bound`: true only when the descriptor
    matched AND carries an equal `evidence_fingerprint`. A matched
    descriptor with no fingerprint or a different one reports
    `attempt_bound: false` — the descriptor may honestly describe a
    different record, so a mismatch is an observation, not an error.
    Without an expected fingerprint the fold cannot bind, so the key is
    absent and `attempt_binding` stays in `checks_not_performed`.
    `descriptor_match` and `accepted` keep their descriptor-only
    meaning — binding is a separate observation, never folded into the
    descriptor's own verdict. The binding is representation-level:
    fingerprint equality says the descriptor and the caller pin the
    same record bytes, not that the descriptor was produced for this
    attempt (`descriptor_authenticity` and
    `unperformed_check_recovery` stay unperformed).

    When `descriptor_bytes` is supplied (the route reads the declared
    file's raw bytes), the evaluation also emits `descriptor_digest` —
    the recomputed SHA-256 of those bytes. The field is the eval
    doc's declared carrier: it names the assessed descriptor, not the
    eval doc's own bytes, so a producer signature over the descriptor
    (verified by `signature-verify` and bound through its
    `subject_digest` carrier) can recover the eval's declared
    `descriptor_authenticity` — while a signature over the eval doc
    itself cannot.

    Three requirement-evaluated verdict shapes form a second family —
    `mumei.evidence-acceptance/v1` (`evidence accept --requirement`
    over one record), `mumei.evidence-list-acceptance/v1`
    (`evidence accept-list --requirement` over a record-list envelope)
    and the conjunctive
    `mumei.evidence-requirement-list-acceptance/v1`
    (`evidence accept --requirement-list`, exported by
    `evidence-check-schedule --promote`). Each has its own closed
    shape: `verdict` replaces the Boolean `accepted` (`accepted` in
    the evaluation holds only for `verdict == "accepted"`), and the
    pin naming the evaluated input must pair with the matching
    `evidence_schema_version` — `evidence_fingerprint` with
    `mumei.verification-evidence/v1`, `list_fingerprint` with
    `mumei.verification-evidence-list/v1` (the conjunctive shape admits
    exactly one of the two). `attempt_bound` still compares
    `expected_fingerprint` to `evidence_fingerprint`, so a list-pinned
    descriptor honestly reports `attempt_bound: false` — it pins
    record-list bytes, not one record."""
    if type(descriptor) is not dict:
        raise ValueError("unsupported core acceptance evaluation request")
    if expected_fingerprint is not None and not _is_fingerprint(
        expected_fingerprint
    ):
        raise ValueError("invalid expected evidence fingerprint")
    schema = descriptor.get("schema_version")
    verdict_matcher = (
        _VERDICT_ACCEPTANCE_MATCHERS.get(schema)
        if type(schema) is str
        else None
    )
    if verdict_matcher is not None:
        match = verdict_matcher(descriptor)
    else:
        fields = frozenset(descriptor)
        schema = descriptor.get("schema_version")
        allowed = _CORE_ACCEPTANCE_REQUIRED_FIELDS | _CORE_ACCEPTANCE_OPTIONAL_FIELDS
        if schema == "mumei.native-evidence-acceptance/v1":
            allowed |= frozenset(_NATIVE_ACCEPTANCE_EXTRA_FIELDS)
        if type(schema) is str:
            allowed |= _PRODUCER_SIGNATURE_DESCRIPTOR_EXTRAS.get(
                schema, frozenset()
            )
        extras = fields - _CORE_ACCEPTANCE_REQUIRED_FIELDS - _CORE_ACCEPTANCE_OPTIONAL_FIELDS
        producer_extras = extras & _PRODUCER_SIGNATURE_EXTRA_FIELDS
        native_extras = extras - producer_extras
        extra_valid = (
            _producer_signature_admitted(
                descriptor,
                _PRODUCER_SIGNATURE_DESCRIPTOR_EXTRAS.get(
                    schema, frozenset()
                )
                if type(schema) is str
                else frozenset(),
            )
            and (
                not native_extras
                or (
                    schema == "mumei.native-evidence-acceptance/v1"
                    and all(
                        name in _NATIVE_ACCEPTANCE_EXTRA_FIELDS
                        and _NATIVE_ACCEPTANCE_EXTRA_FIELDS[name](
                            descriptor[name]
                        )
                        for name in native_extras
                    )
                    and (
                        not native_extras & _OBSERVATION_EXTRA_FIELDS
                        or (
                            type(descriptor.get("checks_performed"))
                            is list
                            and any(
                                type(check) is str
                                and check in _OBSERVATION_REQUIRED_CHECKS
                                for check in descriptor["checks_performed"]
                            )
                        )
                    )
                )
            )
        )
        match = (
            _CORE_ACCEPTANCE_REQUIRED_FIELDS <= fields
            and fields <= allowed
            and extra_valid
            and type(descriptor["schema_version"]) is str
            and descriptor["schema_version"] in CORE_ACCEPTANCE_SCHEMAS
            and type(descriptor["acceptance"]) is str
            and descriptor["acceptance"] == "evaluated"
            and type(descriptor["accepted"]) is bool
            and type(descriptor["scope"]) is str
            and descriptor["scope"] != ""
            and _string_list(descriptor["checks_performed"])
            and _string_list(descriptor["checks_not_performed"])
            and (
                "evidence_fingerprint" not in descriptor
                or _is_fingerprint(descriptor["evidence_fingerprint"])
            )
        )
    declared_accepted = (
        descriptor.get("verdict") == "accepted"
        if verdict_matcher is not None
        else descriptor.get("accepted") is True
    )
    evaluation = {
        "schema_version": "mumei.core-acceptance-evaluation/v1",
        "descriptor_match": match,
        "accepted": match and declared_accepted,
        "checks_not_performed": [
            "attempt_binding",
            "descriptor_authenticity",
            "descriptor_freshness",
            "unperformed_check_recovery",
        ],
    }
    if type(descriptor_bytes) is bytes:
        evaluation["descriptor_digest"] = hashlib.sha256(
            descriptor_bytes
        ).hexdigest()
    if expected_fingerprint is not None:
        evaluation["attempt_bound"] = (
            match
            and descriptor.get("evidence_fingerprint") == expected_fingerprint
        )
        evaluation["checks_not_performed"] = [
            check
            for check in evaluation["checks_not_performed"]
            if check != "attempt_binding"
        ]
    return evaluation


# Producer-signature envelope schema (the detached authenticity record
# issue mumei-agent#886's memo fixes): the signature travels beside the
# signed record, never inside it, so every existing pin on the record
# stays byte-identical.
PRODUCER_SIGNATURE_SCHEMA = "mumei.producer-signature/v1"

_PRODUCER_SIGNATURE_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "subject_digest",
        "algorithm",
        "signature",
        "producer_key_id",
    }
)

# ``produced_at`` is the family's only optional field: a declared
# production timestamp the consumer's `envelope_fresh` fold reads —
# declared like `producer_key_id`, never signed (the signature covers
# the digest alone).
_PRODUCER_SIGNATURE_OPTIONAL_FIELDS = frozenset({"produced_at"})

# The only algorithm the closed family admits — no negotiation.
_PRODUCER_SIGNATURE_ALGORITHM = "ed25519"
# ed25519 signatures are 64 bytes.
_PRODUCER_SIGNATURE_HEX_LEN = 128

SIGNATURE_ENVELOPE_EVALUATION_SCHEMA = (
    "mumei.signature-envelope-evaluation/v1"
)

# A caller-supplied revocation list: a closed-shape declared document
# naming the producer key ids the caller considers revoked — trusted as
# declared, exactly like every other supporting document.
#
# v1 is a bare key set. v2 adds a version and a validity window so a
# replayed older list can be told apart from a current one:
# `list_version` (a positive integer the consumer pins a minimum for),
# `issued_at` (when the producer cut the list) and the optional
# `not_after` (the list's own expiry). v1 stays accepted — it just
# cannot discharge `revocation_list_rollback`.
KEY_REVOCATION_LIST_SCHEMA = "mumei.key-revocation-list/v1"
KEY_REVOCATION_LIST_V2_SCHEMA = "mumei.key-revocation-list/v2"

_KEY_REVOCATION_LIST_REQUIRED_FIELDS = frozenset(
    {"schema_version", "revoked_keys"}
)
_KEY_REVOCATION_LIST_V2_REQUIRED_FIELDS = frozenset(
    {"schema_version", "list_version", "issued_at", "revoked_keys"}
)
_KEY_REVOCATION_LIST_V2_OPTIONAL_FIELDS = frozenset({"not_after"})


def _revoked_key_list(document: dict) -> frozenset:
    revoked = document.get("revoked_keys")
    if type(revoked) is not list or any(
        type(key) is not str or key == "" for key in revoked
    ):
        raise ValueError("invalid key-revocation list document")
    return frozenset(revoked)


def _parse_revocation_list(
    document: dict,
) -> "tuple[frozenset, dict | None]":
    """Parse a declared revocation list into its key set and — for v2
    only — the metadata `revocation_list_current` pins: `list_version`
    plus the RFC3339 `issued_at`/`not_after` windows as (low, high)
    instant bounds. A malformed or foreign document raises ValueError:
    the caller supplied it as input, so a wrong shape is a caller
    error like a malformed ``--record``."""
    if type(document) is not dict:
        raise ValueError("invalid key-revocation list document")
    fields = frozenset(document)
    if document.get("schema_version") == KEY_REVOCATION_LIST_SCHEMA:
        if fields != _KEY_REVOCATION_LIST_REQUIRED_FIELDS:
            raise ValueError("invalid key-revocation list document")
        return _revoked_key_list(document), None
    if document.get("schema_version") == KEY_REVOCATION_LIST_V2_SCHEMA:
        if not (
            _KEY_REVOCATION_LIST_V2_REQUIRED_FIELDS <= fields
            <= _KEY_REVOCATION_LIST_V2_REQUIRED_FIELDS
            | _KEY_REVOCATION_LIST_V2_OPTIONAL_FIELDS
        ):
            raise ValueError("invalid key-revocation list document")
        list_version = document["list_version"]
        if type(list_version) is not int or list_version <= 0:
            raise ValueError("invalid key-revocation list document")
        issued_at = _parse_rfc3339(document["issued_at"])
        not_after = None
        if "not_after" in document:
            not_after = _parse_rfc3339(document["not_after"])
            if not_after is None:
                raise ValueError("invalid key-revocation list document")
        if issued_at is None or (
            not_after is not None and issued_at[0] > not_after[1]
        ):
            raise ValueError("invalid key-revocation list document")
        return _revoked_key_list(document), {
            "list_version": list_version,
            "issued_at": issued_at,
            "not_after": not_after,
        }
    raise ValueError("invalid key-revocation list document")


def revocation_key_set(document: dict) -> frozenset:
    """Fold a declared ``mumei.key-revocation-list/v1`` (or ``/v2``)
    into a key set — producer key ids in the same label space
    `producer_key_id`/`--expected-producer-key` pin."""
    keys, _meta = _parse_revocation_list(document)
    return keys


def revocation_list_metadata(document: dict) -> "dict | None":
    """The v2 list's `list_version`/`issued_at`/`not_after` metadata —
    `None` for a v1 list, which carries nothing a rollback check could
    pin."""
    _keys, meta = _parse_revocation_list(document)
    return meta


# A caller-supplied producer-key registry: a closed-shape declared
# document binding producer key ids to principals over a validity
# window — the trust anchor `key_authenticity` needs. Trusted as
# declared, exactly like the pins and the revocation list.
PRODUCER_KEY_REGISTRY_SCHEMA = "mumei.producer-key-registry/v1"

_PRODUCER_KEY_REGISTRY_REQUIRED_FIELDS = frozenset(
    {"schema_version", "registry"}
)

_REGISTRY_ENTRY_REQUIRED_FIELDS = frozenset(
    {"principal", "not_before", "not_after"}
)


def producer_key_registry(document: dict) -> dict:
    """Fold a declared ``mumei.producer-key-registry/v1`` into a map.

    The registry is a closed shape: `schema_version` names the schema
    and `registry` maps each producer key id (the same label space
    `producer_key_id`/`--expected-producer-key` pin) to a closed entry
    `{principal, not_before, not_after}` — a non-empty principal label
    plus two strict RFC 3339 timestamps bracketing the window the key
    is authorized for. Returns ``key_id → {principal, not_before,
    not_after}`` with the timestamps kept as parsed (low, high) bound
    pairs so callers compare conservatively against a declared
    ``reference_time`` — the same convention `evaluate_freshness`
    uses, never the wall clock.

    A malformed or foreign document raises ValueError rather than
    silently trusting nothing or everything — including a window that
    is definitely inverted (``not_before`` above ``not_after`` under
    the conservative bounds) or a duplicate key id, which the routes
    reject at parse time via a duplicate-rejecting pairs hook.
    """
    if type(document) is not dict:
        raise ValueError("invalid producer-key registry document")
    registry = document.get("registry")
    if (
        frozenset(document) != _PRODUCER_KEY_REGISTRY_REQUIRED_FIELDS
        or document["schema_version"] != PRODUCER_KEY_REGISTRY_SCHEMA
        or type(registry) is not dict
        or not registry
    ):
        raise ValueError("invalid producer-key registry document")
    parsed = {}
    for key_id, entry in registry.items():
        if type(key_id) is not str or key_id == "":
            raise ValueError("invalid producer-key registry document")
        if (
            type(entry) is not dict
            or frozenset(entry) != _REGISTRY_ENTRY_REQUIRED_FIELDS
            or type(entry["principal"]) is not str
            or entry["principal"] == ""
        ):
            raise ValueError("invalid producer-key registry document")
        not_before = _parse_rfc3339(entry["not_before"])
        not_after = _parse_rfc3339(entry["not_after"])
        if not_before is None or not_after is None:
            raise ValueError("invalid producer-key registry document")
        if not_before[0] > not_after[1]:
            # Definitely inverted even under the conservative bounds —
            # a caller error like any other malformed field.
            raise ValueError("invalid producer-key registry document")
        parsed[key_id] = {
            "principal": entry["principal"],
            "not_before": not_before,
            "not_after": not_after,
        }
    return parsed


def _registry_entry_current(entry: dict, reference: tuple) -> bool:
    """Whether a parsed registry entry's window covers a declared time.

    Conservative both ways, the `within_window` convention: the
    entry's `not_before` (worst-case latest) must not postdate the
    reference's earliest bound, and its `not_after` (worst-case
    earliest) must not precede the reference's latest bound — so a
    sub-microsecond fraction can never widen a window into a pass."""
    return (
        entry["not_before"][1] <= reference[0]
        and entry["not_after"][0] >= reference[1]
    )


def _is_hex(value: object, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def _producer_signature_envelope_match(envelope: dict) -> bool:
    """The closed-shape `mumei.producer-signature/v1` test both folds
    share — also applied to declared wrapper envelopes signing a
    trust-anchor document's digest."""
    fields = frozenset(envelope)
    return (
        _PRODUCER_SIGNATURE_REQUIRED_FIELDS
        <= fields
        <= _PRODUCER_SIGNATURE_REQUIRED_FIELDS
        | _PRODUCER_SIGNATURE_OPTIONAL_FIELDS
        and (
            "produced_at" not in envelope
            or type(envelope["produced_at"]) is str
        )
        and envelope["schema_version"] == PRODUCER_SIGNATURE_SCHEMA
        and envelope["algorithm"] == _PRODUCER_SIGNATURE_ALGORITHM
        and _is_fingerprint(envelope["subject_digest"])
        and _is_hex(
            envelope["signature"], _PRODUCER_SIGNATURE_HEX_LEN
        )
        and type(envelope["producer_key_id"]) is str
        and envelope["producer_key_id"] != ""
    )


def _ed25519_signature_valid(
    public_key_hex: str, signature_hex: str, message: bytes
) -> bool:
    """Verify one ed25519 signature under a raw 64-hex public key —
    the Core `crypto_verify_signature` convention."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    verifying_key = Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(public_key_hex)
    )
    try:
        verifying_key.verify(
            bytes.fromhex(signature_hex), message
        )
    except InvalidSignature:
        return False
    return True


def evaluate_signature_envelope(
    envelope: dict,
    expected_subject: str | None = None,
    expected_key: str | None = None,
    revoked_keys: frozenset | None = None,
    key_registry: dict | None = None,
    reference_time: str | None = None,
    max_age_seconds: int | None = None,
    registry_signature: dict | None = None,
    registry_digest: str | None = None,
    revocation_signature: dict | None = None,
    revocation_digest: str | None = None,
    revocation_list_meta: dict | None = None,
    min_revocation_version: int | None = None,
) -> dict:
    """Fold a declared producer-signature envelope into an evaluation.

    Emits ``mumei.signature-envelope-evaluation/v1``: `envelope_match`
    holds only for a closed-shape `mumei.producer-signature/v1` record
    naming `algorithm: "ed25519"` with a 64-char hex `subject_digest`,
    a 128-char hex `signature` and a non-empty `producer_key_id` — a
    foreign or malformed document never counts.

    With `expected_subject` (the record digest the signature should
    cover — e.g. an accepted descriptor's `evidence_fingerprint` or a
    record's own `sha256`) the fold emits `subject_bound`: true only
    when the envelope matched AND pins the same digest. With
    `expected_key` the caller declares the producer key fingerprint it
    trusts (over a separately trusted channel, exactly like
    `--expected-adapter`/`--expected-build-id` pins) and the fold emits
    `key_pinned`: true only when the envelope matched AND names that
    key. Either pin left out stays declared-unperformed — the key is
    absent and the check remains in `checks_not_performed`.

    With `key_registry` (the parsed
    ``mumei.producer-key-registry/v1`` map) and a declared
    `reference_time` (the caller's clock, never the wall clock — the
    freshness convention) the fold emits `key_authentic`: true only
    when the envelope matched AND its `producer_key_id` names a
    registry entry whose `not_before`/`not_after` window covers the
    reference time. A registry without a reference time performs
    nothing — the window needs a declared clock — and a reference
    time without a registry is a caller error.

    This is representation-level only: the fold checks the envelope's
    shape, declared pins and declared registry, never the ed25519
    signature bytes (`signature_verification` stays) and never
    freshness. A matched envelope whose declared inputs disagree
    reports `false` observations, never an error."""
    if type(envelope) is not dict:
        raise ValueError("unsupported signature envelope evaluation request")
    if expected_subject is not None and not _is_fingerprint(
        expected_subject
    ):
        raise ValueError("invalid expected subject digest")
    if expected_key is not None and (
        type(expected_key) is not str or expected_key == ""
    ):
        raise ValueError("invalid expected producer key")
    reference = None
    if reference_time is not None:
        reference = _parse_rfc3339(reference_time)
        if reference is None:
            raise ValueError("invalid reference time")
    if max_age_seconds is not None:
        if type(max_age_seconds) is not int or max_age_seconds < 0:
            raise ValueError("invalid max age")
        if reference is None:
            raise ValueError("max age requires a reference time")
    if key_registry is not None:
        if reference is None:
            raise ValueError("key registry requires a reference time")
    elif (
        reference is not None
        and max_age_seconds is None
        and min_revocation_version is None
    ):
        raise ValueError(
            "reference time requires a key registry or max age"
        )
    if registry_signature is not None:
        if key_registry is None:
            raise ValueError(
                "registry signature requires a key registry"
            )
        if not _is_fingerprint(registry_digest or ""):
            raise ValueError("invalid registry digest")
    if revocation_signature is not None:
        if revoked_keys is None:
            raise ValueError(
                "revocation signature requires a revocation list"
            )
        if not _is_fingerprint(revocation_digest or ""):
            raise ValueError("invalid revocation digest")
    if min_revocation_version is not None:
        if (
            type(min_revocation_version) is not int
            or min_revocation_version < 0
        ):
            raise ValueError("invalid min revocation version")
        if revoked_keys is None:
            raise ValueError(
                "min revocation version requires a revocation list"
            )
        if revocation_list_meta is None:
            raise ValueError(
                "min revocation version requires a v2 revocation list"
            )
        if reference is None:
            raise ValueError(
                "min revocation version requires a reference time"
            )
    match = _producer_signature_envelope_match(envelope)
    evaluation = {
        "schema_version": SIGNATURE_ENVELOPE_EVALUATION_SCHEMA,
        "envelope_match": match,
        "checks_not_performed": [
            "subject_binding",
            "key_binding",
            "signature_verification",
            "key_authenticity",
            "envelope_freshness",
            "key_revocation",
            # Without a versioned list (v2 + a declared minimum and
            # reference time) a replayed old list cannot be told from
            # a current one — the rollback check stays unperformed.
            "revocation_list_rollback",
            # Declared trust anchors are trusted as declared unless a
            # signature pins them to the document's digest — the eval
            # fold can bind that signature but not verify it, so the
            # anchors' authenticity stays unperformed here.
            "registry_authenticity",
            "revocation_list_authenticity",
            # The stamp is declared, not signed, and the reference is
            # the caller's trusted clock — neither fold performs the
            # producer's time authenticity nor the clock's, matching
            # `evaluate_freshness`' declared set.
            "producer_time_authenticity",
            "clock_authenticity",
        ],
    }
    if match:
        # The envelope's declared digest echoes so a consumer can bind
        # this document to the record the signature covers — the same
        # carrier convention the verification fold emits.
        evaluation["subject_digest"] = envelope["subject_digest"]
    if expected_subject is not None:
        evaluation["subject_bound"] = (
            match and envelope["subject_digest"] == expected_subject
        )
        evaluation["checks_not_performed"].remove("subject_binding")
    if expected_key is not None:
        evaluation["key_pinned"] = (
            match and envelope["producer_key_id"] == expected_key
        )
        evaluation["checks_not_performed"].remove("key_binding")
    if revoked_keys is not None:
        # A declared revocation list performs `key_revocation` on the
        # matched envelope's key id: `key_not_revoked` is true only
        # when the envelope matched AND its producer key id is absent
        # from the caller's list. The list itself is trusted as
        # declared — an authentic list needs the directory/trust-anchor
        # story (`key_authenticity` still stays).
        evaluation["key_not_revoked"] = (
            match and envelope["producer_key_id"] not in revoked_keys
        )
        evaluation["checks_not_performed"].remove("key_revocation")
    if (
        revoked_keys is not None
        and revocation_list_meta is not None
        and min_revocation_version is not None
        and reference is not None
    ):
        # The replay check: the v2 list must predate the declared
        # reference, stay inside its optional `not_after` window and
        # clear the caller's minimum version — the conservative
        # bounds convention, same as registry windows.
        evaluation["revocation_list_current"] = (
            revocation_list_meta["issued_at"][1] <= reference[0]
            and (
                revocation_list_meta["not_after"] is None
                or revocation_list_meta["not_after"][0] >= reference[1]
            )
            and revocation_list_meta["list_version"]
            >= min_revocation_version
        )
        evaluation["checks_not_performed"].remove(
            "revocation_list_rollback"
        )
    if key_registry is not None:
        # A declared registry performs `key_authenticity` on the
        # matched envelope's key id: `key_authentic` is true only
        # when the envelope matched AND its producer key id names an
        # entry whose declared window covers the declared reference
        # time. The registry itself is trusted as declared — an
        # authentic registry needs the distribution/attestation story
        # (the route emits no claim about where the document came
        # from).
        key_id = envelope.get("producer_key_id")
        # A non-string producer key id already fails `match`'s shape
        # check; an unhashable one (list/dict) would raise TypeError
        # inside `get`, so guard the lookup instead of crashing on a
        # malformed envelope.
        entry = key_registry.get(key_id) if type(key_id) is str else None
        evaluation["key_authentic"] = (
            match
            and entry is not None
            and _registry_entry_current(entry, reference)
        )
        evaluation["checks_not_performed"].remove("key_authenticity")
    if max_age_seconds is not None:
        # Same conservative (low, high) bounds as `evaluate_freshness`:
        # a stamp that could postdate the reference or sit barely
        # outside the window fails closed. An absent or unparseable
        # `produced_at` simply cannot prove freshness.
        produced = _parse_rfc3339(envelope.get("produced_at"))
        evaluation["envelope_fresh"] = (
            match
            and produced is not None
            and produced[1] <= reference[0]
            and _within_age_window(
                produced[0], reference[1], max_age_seconds
            )
        )
        evaluation["checks_not_performed"].remove("envelope_freshness")
    if key_registry is not None:
        # Pin which anchor bytes the fold assessed: `recovery-eval`
        # binds a `signature-verification/v1` document to this
        # descriptor only when both name the same registry digest.
        evaluation["registry_digest"] = registry_digest
    if revoked_keys is not None:
        evaluation["revocation_digest"] = revocation_digest
    if registry_signature is not None:
        # Representation-level only: the wrapper envelope's declared
        # `subject_digest` is compared to the registry's digest — the
        # signature itself is verified on the crypto route, so
        # `registry_authenticity` stays unperformed here.
        evaluation["registry_signature_bound"] = (
            _producer_signature_envelope_match(registry_signature)
            and registry_signature["subject_digest"] == registry_digest
        )
    if revocation_signature is not None:
        evaluation["revocation_signature_bound"] = (
            _producer_signature_envelope_match(revocation_signature)
            and revocation_signature["subject_digest"]
            == revocation_digest
        )
    return evaluation


SIGNATURE_VERIFICATION_SCHEMA = "mumei.signature-verification/v1"

# An ed25519 public key is 32 bytes.
_PRODUCER_KEY_HEX_LEN = 64


def verify_signature_envelope(
    envelope: dict,
    producer_key: str,
    expected_subject: str | None = None,
    expected_key: str | None = None,
    revoked_keys: frozenset | None = None,
    key_registry: dict | None = None,
    reference_time: str | None = None,
    max_age_seconds: int | None = None,
    registry_signature: dict | None = None,
    registry_key: str | None = None,
    registry_digest: str | None = None,
    revocation_signature: dict | None = None,
    revocation_key: str | None = None,
    revocation_digest: str | None = None,
    revocation_list_meta: dict | None = None,
    min_revocation_version: int | None = None,
) -> dict:
    """Verify a declared producer-signature envelope's ed25519 signature.

    Emits ``mumei.signature-verification/v1``. `envelope_match` is the
    same closed-shape test `evaluate_signature_envelope` performs; a
    foreign or malformed document never counts. `signature_valid`
    holds only when the envelope matched AND the declared
    `producer_key` (a 64-char lowercase-hex raw ed25519 public key the
    caller supplies over a separately trusted channel) verifies the
    envelope's `signature` over the `subject_digest` — the signed
    payload is the digest's lowercase-hex ASCII bytes, matching the
    Core `crypto_verify_signature` FFI convention that signs
    `message.as_bytes()`.

    `expected_subject`/`expected_key` declare the same subject/key-id
    pins as the evaluation fold and emit `subject_bound`/`key_pinned`
    under the same rules. A matched document also echoes the envelope's
    `subject_digest` so a consumer can bind the verification to the
    record bytes it covers — the same carrier convention the envelope
    itself pins. With `key_registry` and a declared `reference_time`
    the fold emits `key_authentic` under the same registry-window rule
    as the evaluation fold. `signature_valid` says only that the
    signature cryptographically binds the declared key to the declared
    digest — without the declared registry the key's own authenticity
    stays unassessed (`key_authenticity` stays in
    `checks_not_performed`, as does `envelope_freshness`), and an
    unmatched envelope or a failed verify reports `false`
    observations, never an error."""
    if type(envelope) is not dict:
        raise ValueError("unsupported signature verification request")
    if not _is_hex(producer_key, _PRODUCER_KEY_HEX_LEN):
        raise ValueError("invalid producer key")
    if expected_subject is not None and not _is_fingerprint(
        expected_subject
    ):
        raise ValueError("invalid expected subject digest")
    if expected_key is not None and (
        type(expected_key) is not str or expected_key == ""
    ):
        raise ValueError("invalid expected producer key")
    reference = None
    if reference_time is not None:
        reference = _parse_rfc3339(reference_time)
        if reference is None:
            raise ValueError("invalid reference time")
    if max_age_seconds is not None:
        if type(max_age_seconds) is not int or max_age_seconds < 0:
            raise ValueError("invalid max age")
        if reference is None:
            raise ValueError("max age requires a reference time")
    if key_registry is not None:
        if reference is None:
            raise ValueError("key registry requires a reference time")
    elif (
        reference is not None
        and max_age_seconds is None
        and min_revocation_version is None
    ):
        raise ValueError(
            "reference time requires a key registry or max age"
        )
    if registry_signature is not None:
        if key_registry is None:
            raise ValueError(
                "registry signature requires a key registry"
            )
        if not _is_hex(registry_key or "", _PRODUCER_KEY_HEX_LEN):
            raise ValueError("invalid registry key")
        if not _is_fingerprint(registry_digest or ""):
            raise ValueError("invalid registry digest")
    if revocation_signature is not None:
        if revoked_keys is None:
            raise ValueError(
                "revocation signature requires a revocation list"
            )
        if not _is_hex(revocation_key or "", _PRODUCER_KEY_HEX_LEN):
            raise ValueError("invalid revocation key")
        if not _is_fingerprint(revocation_digest or ""):
            raise ValueError("invalid revocation digest")
    if min_revocation_version is not None:
        if (
            type(min_revocation_version) is not int
            or min_revocation_version < 0
        ):
            raise ValueError("invalid min revocation version")
        if revoked_keys is None:
            raise ValueError(
                "min revocation version requires a revocation list"
            )
        if revocation_list_meta is None:
            raise ValueError(
                "min revocation version requires a v2 revocation list"
            )
        if reference is None:
            raise ValueError(
                "min revocation version requires a reference time"
            )
    match = _producer_signature_envelope_match(envelope)
    signature_valid = False
    if match:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        verifying_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(producer_key)
        )
        try:
            verifying_key.verify(
                bytes.fromhex(envelope["signature"]),
                envelope["subject_digest"].encode("ascii"),
            )
            signature_valid = True
        except InvalidSignature:
            signature_valid = False
    verification = {
        "schema_version": SIGNATURE_VERIFICATION_SCHEMA,
        "envelope_match": match,
        "signature_valid": signature_valid,
        "checks_not_performed": [
            "subject_binding",
            "key_binding",
            "key_authenticity",
            "envelope_freshness",
            "key_revocation",
            # Without a versioned list (v2 + a declared minimum and
            # reference time) a replayed old list cannot be told from
            # a current one — the rollback check stays unperformed.
            "revocation_list_rollback",
            # The declared trust anchors are trusted as declared
            # unless the caller pins each to a
            # `mumei.producer-signature/v1` envelope over its bytes
            # verified under a consumer-pinned root key — the checks
            # drop out of this list only when those signatures are
            # supplied and assessed.
            "registry_authenticity",
            "revocation_list_authenticity",
            # The stamp is declared, not signed, and the reference is
            # the caller's trusted clock — neither fold performs the
            # producer's time authenticity nor the clock's, matching
            # `evaluate_freshness`' declared set.
            "producer_time_authenticity",
            "clock_authenticity",
        ],
    }
    if match:
        # The envelope's declared digest is emitted so a consumer can
        # bind this document to the record the signature covers — the
        # same carrier convention `subject_digest` already pins on the
        # envelope itself.
        verification["subject_digest"] = envelope["subject_digest"]
    if expected_subject is not None:
        verification["subject_bound"] = (
            match and envelope["subject_digest"] == expected_subject
        )
        verification["checks_not_performed"].remove("subject_binding")
    if expected_key is not None:
        verification["key_pinned"] = (
            match and envelope["producer_key_id"] == expected_key
        )
        verification["checks_not_performed"].remove("key_binding")
    if revoked_keys is not None:
        # Same declared revocation list as the evaluation fold:
        # `key_not_revoked` holds only when the envelope matched AND
        # its producer key id is absent from the caller's list.
        verification["key_not_revoked"] = (
            match and envelope["producer_key_id"] not in revoked_keys
        )
        verification["checks_not_performed"].remove("key_revocation")
    if (
        revoked_keys is not None
        and revocation_list_meta is not None
        and min_revocation_version is not None
        and reference is not None
    ):
        verification["revocation_list_current"] = (
            revocation_list_meta["issued_at"][1] <= reference[0]
            and (
                revocation_list_meta["not_after"] is None
                or revocation_list_meta["not_after"][0] >= reference[1]
            )
            and revocation_list_meta["list_version"]
            >= min_revocation_version
        )
        verification["checks_not_performed"].remove(
            "revocation_list_rollback"
        )
    if key_registry is not None:
        # Same declared registry as the evaluation fold:
        # `key_authentic` holds only when the envelope matched AND
        # its producer key id names an entry whose declared window
        # covers the declared reference time.
        key_id = envelope.get("producer_key_id")
        entry = key_registry.get(key_id) if type(key_id) is str else None
        verification["key_authentic"] = (
            match
            and entry is not None
            and _registry_entry_current(entry, reference)
        )
        verification["checks_not_performed"].remove("key_authenticity")
    if max_age_seconds is not None:
        produced = _parse_rfc3339(envelope.get("produced_at"))
        verification["envelope_fresh"] = (
            match
            and produced is not None
            and produced[1] <= reference[0]
            and _within_age_window(
                produced[0], reference[1], max_age_seconds
            )
        )
        verification["checks_not_performed"].remove("envelope_freshness")
    if key_registry is not None:
        # Pin which anchor bytes the fold assessed: `recovery-eval`
        # binds a bound verifying document to this descriptor only
        # when both name the same registry digest.
        verification["registry_digest"] = registry_digest
    if revoked_keys is not None:
        verification["revocation_digest"] = revocation_digest
    if registry_signature is not None:
        # The consumer-pinned root key authenticates the declared
        # registry itself: the wrapper envelope must match the closed
        # producer-signature shape, verify cryptographically under the
        # pinned key, and pin the registry's own digest. Only then
        # does `key_authentic` lean on the registry.
        wrapper_match = _producer_signature_envelope_match(
            registry_signature
        )
        registry_authentic = (
            wrapper_match
            and _ed25519_signature_valid(
                registry_key,
                registry_signature["signature"],
                registry_signature["subject_digest"].encode("ascii"),
            )
            and registry_signature["subject_digest"] == registry_digest
        )
        verification["registry_authentic"] = registry_authentic
        verification["checks_not_performed"].remove(
            "registry_authenticity"
        )
        if key_registry is not None:
            verification["key_authentic"] = (
                verification["key_authentic"] and registry_authentic
            )
    if revocation_signature is not None:
        wrapper_match = _producer_signature_envelope_match(
            revocation_signature
        )
        revocation_list_authentic = (
            wrapper_match
            and _ed25519_signature_valid(
                revocation_key,
                revocation_signature["signature"],
                revocation_signature["subject_digest"].encode("ascii"),
            )
            and revocation_signature["subject_digest"]
            == revocation_digest
        )
        verification["revocation_list_authentic"] = (
            revocation_list_authentic
        )
        verification["checks_not_performed"].remove(
            "revocation_list_authenticity"
        )
        if revoked_keys is not None:
            verification["key_not_revoked"] = (
                verification["key_not_revoked"]
                and revocation_list_authentic
            )
    return verification


# A 32-byte ed25519 secret key in its 64-char lowercase-hex form — the
# same shape `mumei evidence keygen --secret-file` writes and
# `decode_secret_key` decodes on the Core side: strictly ASCII, no
# whitespace, prefix or surrounding bytes.
_PRODUCER_SECRET_KEY_HEX_LEN = 64


def sign_producer_record(
    record: bytes,
    secret_key: str,
    producer_key_id: str,
) -> dict:
    """Sign one declared record's digest into a detached envelope.

    Emits ``mumei.producer-signature/v1``: `subject_digest` is the
    SHA-256 of the record's raw bytes (the same digest a consumer
    reproduces with `sha256sum`), `algorithm` is `ed25519` (the only
    admitted algorithm — no negotiation) and `signature` covers the
    digest's lowercase-hex ASCII bytes, matching the Core
    `crypto_verify_signature` FFI convention that
    `verify_signature_envelope` verifies against.

    `secret_key` is the 64-char lowercase-hex encoding of the 32-byte
    ed25519 secret `mumei evidence keygen --secret-file` writes — a
    declared input the caller supplies over its own trusted channel.
    The key material never appears in the emitted envelope, in error
    text, or in any output surface: the envelope carries only the
    signature and the declared `producer_key_id` label, which the
    consumer pins separately (`key_authenticity` stays unperformed —
    the id is a declared label, not an attested identity).

    A malformed key or an empty `producer_key_id` raises ValueError;
    nothing else can fail. Signing is representation-level: it binds
    the declared key to the declared bytes' digest and claims nothing
    about freshness, revocation, or claim truth.
    """
    if not _is_hex(secret_key, _PRODUCER_SECRET_KEY_HEX_LEN):
        raise ValueError("invalid producer key material")
    if type(producer_key_id) is not str or producer_key_id == "":
        raise ValueError("producer key id must not be empty")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    signing_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(secret_key)
    )
    digest = hashlib.sha256(record).hexdigest()
    signature = signing_key.sign(digest.encode("ascii"))
    return {
        "schema_version": PRODUCER_SIGNATURE_SCHEMA,
        "subject_digest": digest,
        "algorithm": _PRODUCER_SIGNATURE_ALGORITHM,
        "signature": signature.hex(),
        "producer_key_id": producer_key_id,
    }


# Evidence-binding schema: pin a subject-bearing document to the record
# bytes it is said to cover.
EVIDENCE_BINDING_SCHEMA = "mumei.evidence-binding/v1"

# Which declared field of each subject-bearing schema carries the
# record's SHA-256 digest. Both conventions hash the record's raw
# bytes: `subject_digest` on a producer-signature envelope and
# `evidence_fingerprint` on a Core acceptance descriptor are the same
# SHA-256 a consumer reproduces with `sha256sum`. A carrier may name
# several candidate subject fields when the schema pins different
# artifacts by different field names — the descriptor's own schema
# decides which is present; a missing candidate is an honest miss,
# never an error.
_BINDING_CARRIERS: dict[str, tuple[str, ...]] = {
    PRODUCER_SIGNATURE_SCHEMA: ("subject_digest",),
    "mumei.source-evidence-acceptance/v1": ("evidence_fingerprint",),
    "mumei.native-evidence-acceptance/v1": ("evidence_fingerprint",),
    # The conjunctive acceptance descriptor pins `evidence_fingerprint`
    # when it evaluates a single record and `list_fingerprint` when it
    # evaluates a record list — its own schema allows exactly one, so
    # a consumer binding the exported list bytes (the promotable gate
    # triple) uses the list pin and a consumer binding one record uses
    # the record pin.
    REQUIREMENT_LIST_ACCEPTANCE_SCHEMA: (
        "evidence_fingerprint",
        "list_fingerprint",
    ),
    # The single-requirement accept descriptor pins the record it
    # evaluated by the same `evidence_fingerprint` convention.
    EVIDENCE_ACCEPTANCE_SCHEMA: ("evidence_fingerprint",),
    # `accept-list --requirement` pins the evidence list it evaluated
    # by `list_fingerprint` — the same raw-bytes SHA-256 convention on
    # the list envelope bytes.
    EVIDENCE_LIST_ACCEPTANCE_SCHEMA: ("list_fingerprint",),
    # `recheck-source --json` emits the same binding convention — the
    # diagnostic stays anonymous and non-reusable, but its fingerprint
    # pins the consistency verdict to the record it was derived from.
    "mumei.source-evidence-recheck/v1": ("evidence_fingerprint",),
    # The verification doc echoes the envelope's `subject_digest` — the
    # record digest the signature covers — so it binds to the record
    # bytes like the envelope itself.
    SIGNATURE_VERIFICATION_SCHEMA: ("subject_digest",),
    # The evaluation doc echoes the same digest — a bound
    # `key_not_revoked` observation names the record the signature
    # covers, not just an unscoped envelope.
    SIGNATURE_ENVELOPE_EVALUATION_SCHEMA: ("subject_digest",),
    # The acceptance evaluation pins the descriptor it assessed — the
    # digest the promotable pipeline signs and verifies.
    "mumei.core-acceptance-evaluation/v1": ("descriptor_digest",),
}


def evaluate_evidence_binding(record: bytes, document: dict) -> dict:
    """Pin a declared subject-bearing document to record bytes.

    Emits ``mumei.evidence-binding/v1``: `record_digest` is the
    SHA-256 lowercase hex of the supplied record's raw bytes —
    recomputed by the fold, never trusted from a declared pin.
    `carrier_match` holds only when `document` is an object whose
    `schema_version` names a declared subject-bearing schema (a
    producer-signature envelope's `subject_digest`, a Core
    acceptance descriptor's `evidence_fingerprint`, or a
    record-list acceptance descriptor's `list_fingerprint`).
    `subject_declared` holds only when at least one of the matched
    carrier's candidate subject fields carries a 64-char
    lowercase-hex value. `bound` holds only when all three hold AND
    a declared subject digest equals `record_digest` — a mismatched
    or missing subject reports `false` observations, never an error,
    since a document may honestly describe a different record.

    This is representation-level: the document is trusted as declared
    (`carrier_authenticity` — the fold never verifies the document's
    own checks or signature) and the report gates nothing itself
    (`binding_enforcement` stays in `checks_not_performed`)."""
    if type(record) is not bytes:
        raise ValueError("unsupported evidence binding record")
    if type(document) is not dict:
        raise ValueError("unsupported evidence binding document")
    record_digest = hashlib.sha256(record).hexdigest()
    schema = document.get("schema_version")
    fields = (
        _BINDING_CARRIERS.get(schema) if type(schema) is str else None
    )
    match = fields is not None
    declared = (
        any(
            _is_fingerprint(document.get(field)) for field in fields
        )
        if match
        else False
    )
    return {
        "schema_version": EVIDENCE_BINDING_SCHEMA,
        "record_digest": record_digest,
        "carrier_match": match,
        "subject_declared": declared,
        "bound": match
        and declared
        and any(
            document.get(field) == record_digest for field in fields
        ),
        "checks_not_performed": [
            "carrier_authenticity",
            "binding_enforcement",
        ],
    }


# Unperformed-check recovery schema (the composition fold issue
# mumei-agent#897's memo fixes): which of a record's declared
# ``checks_not_performed`` a set of supporting documents covers.
UNPERFORMED_CHECK_RECOVERY_SCHEMA = "mumei.unperformed-check-recovery/v1"

# Emitted by Core's recheck-observations command; the raw descriptor
# remains non-performing, unlike the accepted one-invocation report.
RUNTIME_OBSERVATION_SCHEMA = "mumei.runtime-observation/v1"
RUNTIME_CHECK_VOCABULARY = frozenset(
    {
        "os_exit_status_observation",
        "os_stdout_observation",
        "os_stderr_observation",
        "runtime_observation_semantics",
    }
)

# Core's object-symbol, direct-call-edge and object-to-executable checks are
# bounded correspondences. Leaf and direct-call-site machine-code checks
# cover straight-line TV under an assumed register convention; calls are
# compared as uninterpreted sites. Forward-branch and acyclic backward-branch
# function TV are also bounded. Conditional-call TV matches uninterpreted
# call sites along each guarded path in branching functions. Bounded-loop
# function TV is limited to Core's LOOP_BOUND=4 profile. Executions beyond
# that bound, cancellation/runtime semantics and other cyclic control flow
# remain outside; the loop input domain carries
# `_and_loops_exiting_within_bound_4`. These checks do not establish ABI
# behavior or full object TV. Core's callee-saved preservation check applies
# only to Equivalent functions within this profile; direct callees and the
# cancellation poll are assumed to preserve those registers, while external
# callees remain an assumption. The argument/result register convention is
# assumed, not validated. Core's entry-wrapper TV check applies only when the
# object defines both main and __mumei_user_main and the latter has a supported
# source signature. It checks main as one unconditional call to
# __mumei_user_main, returning the low 32 bits of its result; it makes no CRT,
# loader, OS exit-status, ABI, or runtime claim. os_exit_status_observation is
# a separate runtime-observation check. object_translation_correspondence is
# the full object-TV check; none is a recovery performer or makes a linker,
# loader, ABI, or runtime claim.
# Core's scalar-f64 TV check is limited to its f64 profile with XMM registers
# assumed; MXCSR control state and NaN payload bits are not established.
OBJECT_CHECK_VOCABULARY = frozenset(
    {
        "object_call_edge_correspondence",
        "object_link_correspondence",
        "object_symbol_correspondence",
        "object_translation_correspondence",
        "machine_code_bounded_loop_function_tv",
        "machine_code_leaf_function_tv",
        "machine_code_direct_call_site_tv",
        "machine_code_forward_branch_function_tv",
        "machine_code_acyclic_branch_function_tv",
        "machine_code_conditional_call_function_tv",
        "machine_code_callee_saved_register_preservation",
        "machine_code_callee_saved_preservation_assumed_for_external_callees",
        "machine_code_entry_wrapper_tv",
        "machine_code_f64_scalar_function_tv",
        # Bounded assumed-SysV aggregate evidence; this does not validate an ABI.
        "machine_code_composite_register_aggregate_tv",
        "machine_code_tv_mxcsr_control_state",
        "machine_code_tv_nan_payload_bits",
        "machine_code_tv_sysv_memory_class_aggregate_abi",
    }
)

MACHINE_TV_ASSUMPTION_MARKERS = frozenset(
    {
        "machine_code_callee_saved_preservation_assumed_for_external_callees",
        "machine_code_tv_mxcsr_control_state",
        "machine_code_tv_nan_payload_bits",
        "machine_code_tv_sysv_memory_class_aggregate_abi",
    }
)

# Which emitted schema performs each check name, the outcome field and
# the value it must hold for the check to count as recovered. A document
# never gets to declare its own coverage — attribution is pinned to the
# emitted schema, so a foreign document claiming a check cannot count.
_CHECK_PERFORMERS: dict = {
    "os_exit_status_observation": [
        ("mumei.native-exit-status-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-exit-status-accept-report/v1", "acceptance",
         "accepted", "shared:expected_build_id"),
        ("mumei.native-observations-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-observations-accept-report/v1", "acceptance",
         "accepted", "shared:expected_build_id"),
    ],
    "os_stdout_observation": [
        ("mumei.native-stdout-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-stdout-accept-report/v1", "acceptance",
         "accepted", "shared:expected_build_id"),
        ("mumei.native-observations-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-observations-accept-report/v1", "acceptance",
         "accepted", "shared:expected_build_id"),
    ],
    "os_stderr_observation": [
        ("mumei.native-stderr-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-stderr-accept-report/v1", "acceptance",
         "accepted", "shared:expected_build_id"),
        ("mumei.native-observations-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-observations-accept-report/v1", "acceptance",
         "accepted", "shared:expected_build_id"),
    ],
    # Accepted Core runs authenticate this build ID against the bundle
    # record, so it pins sibling reports to the same record. Single-
    # channel rechecks have fixed diagnostic stdout. The observations-
    # recheck report and raw runtime-observation descriptor are also
    # deliberately non-performers: they recheck, they do not accept.
    # runtime_observation_semantics is performed only by the one-
    # invocation observations acceptance; it is never a conjunction of
    # the three single-channel reports.
    "runtime_observation_semantics": [
        ("mumei.native-observations-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-observations-accept-report/v1", "acceptance",
         "accepted", "shared:expected_build_id"),
    ],
    "attempt_binding": [
        ("mumei.core-acceptance-evaluation/v1", "attempt_bound", True, None),
    ],
    "subject_binding": [
        ("mumei.signature-envelope-evaluation/v1", "subject_bound", True, None),
        ("mumei.signature-verification/v1", "subject_bound", True, None),
    ],
    "key_binding": [
        ("mumei.signature-envelope-evaluation/v1", "key_pinned", True, None),
        ("mumei.signature-verification/v1", "key_pinned", True, None),
    ],
    "signature_verification": [
        ("mumei.signature-verification/v1", "signature_valid", True, None),
    ],
    # A declared revocation list performs `key_revocation` through
    # either signature fold's `key_not_revoked` — bound to the record
    # via the fold doc's echoed `subject_digest` carrier, so the
    # observation names the key that signed *this* record.
    "key_revocation": [
        (
            "mumei.signature-envelope-evaluation/v1",
            "key_not_revoked",
            True,
            "subject_digest",
        ),
        (
            "mumei.signature-verification/v1",
            "key_not_revoked",
            True,
            "subject_digest",
        ),
    ],
    # A declared producer-key registry performs `key_authenticity`
    # through either signature fold's `key_authentic` — bound to the
    # record via the fold doc's echoed `subject_digest` carrier, like
    # `key_revocation`.
    "key_authenticity": [
        (
            "mumei.signature-envelope-evaluation/v1",
            "key_authentic",
            True,
            "subject_digest",
        ),
        (
            "mumei.signature-verification/v1",
            "key_authentic",
            True,
            "subject_digest",
        ),
    ],
    # `registry_authenticity` / `revocation_list_authenticity` are
    # deliberately NOT recoverable through the bound fold doc: a
    # verification emits the anchor outcomes bound only to the
    # signed record's digest — it does not pin WHICH anchor document
    # it assessed, so a doc authenticating a different registry would
    # wrongly recover this record's anchor check.
    # A signature fold's `envelope_fresh` performs `envelope_freshness`
    # for the envelope's covered record — bound via the echoed
    # `subject_digest` carrier, like `key_revocation`/`key_authenticity`.
    "envelope_freshness": [
        ("mumei.freshness-evaluation/v1", "within_window", True, None),
        (
            "mumei.signature-envelope-evaluation/v1",
            "envelope_fresh",
            True,
            "subject_digest",
        ),
        (
            "mumei.signature-verification/v1",
            "envelope_fresh",
            True,
            "subject_digest",
        ),
    ],
    # A signature-verification doc that authenticated the same anchor
    # bytes performs the anchor check on a descriptor that left it
    # unperformed — `shared:` binds both docs to the declared anchor
    # digest they each assessed (`registry_digest`/`revocation_digest`),
    # never to each other's bytes.
    "registry_authenticity": [
        ("mumei.signature-verification/v1", "registry_authentic", True,
         "shared:registry_digest"),
    ],
    "revocation_list_authenticity": [
        ("mumei.signature-verification/v1", "revocation_list_authentic",
         True, "shared:revocation_digest"),
    ],
    "descriptor_freshness": [
        ("mumei.freshness-evaluation/v1", "within_window", True, None),
    ],
    # `descriptor_authenticity` is the acceptance evaluation's own
    # authenticity check on the descriptor it assessed. A producer
    # signature over the descriptor's bytes, verified under a
    # caller-pinned producer key, performs it — the same
    # `signature_valid` + `key_pinned` shape as
    # `producer_authenticity` (the key's own authenticity still stays
    # unperformed), bound to the descriptor via the verification
    # doc's `subject_digest` carrier.
    "descriptor_authenticity": [
        ("mumei.signature-verification/v1",
         ("signature_valid", "key_pinned"), True, "subject_digest"),
    ],
    # Core acceptance descriptors declare `record_freshness` — whether
    # the accepted record itself was recently produced. A freshness
    # evaluation over the record's `produced_at` performs it, like
    # `freshness`/`descriptor_freshness` (record-agnostic: the doc is
    # trusted as declared and binds no record at this layer).
    "record_freshness": [
        ("mumei.freshness-evaluation/v1", "within_window", True, None),
    ],
    "freshness": [
        ("mumei.freshness-evaluation/v1", "within_window", True, None),
        ("mumei.source-evidence-recheck/v1", "recheck", "consistent",
         "evidence_fingerprint"),
        ("mumei.source-evidence-acceptance/v1", "accepted", True,
         "evidence_fingerprint"),
        ("mumei.verify-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.go-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.go-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.ts-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.ts-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.sol-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.sol-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.rust-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.rust-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
    ],
    "evidence_binding": [
        (EVIDENCE_BINDING_SCHEMA, "bound", True, "record_digest"),
    ],
    # The semantic C02 checks recover through the fingerprint-carrying
    # Core descriptors and the attempt reports, mirroring the
    # discharged_checks sets the declared attempt routes report: a
    # consistent source recheck or an accepted source acceptance
    # re-establishes the record's claims within its declared profile; a
    # native acceptance descriptor adds the compiled-artifact layer; an
    # accepted verify-attempt report discharges every check of the
    # produced record but the artifact layer. Each bound document only
    # counts when its carrier — `evidence_fingerprint`, `record_digest`
    # or the report's `normalized.stdout.sha256` — equals the
    # record's bound digest, so an anonymous or differently-bound
    # document can never recover this record.
    "claim_truth": [
        ("mumei.source-evidence-recheck/v1", "recheck", "consistent",
         "evidence_fingerprint"),
        ("mumei.source-evidence-acceptance/v1", "accepted", True,
         "evidence_fingerprint"),
        ("mumei.native-evidence-acceptance/v1", "accepted", True,
         "evidence_fingerprint"),
        ("mumei.verify-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
    ],
    "semantic_correspondence": [
        ("mumei.source-evidence-recheck/v1", "recheck", "consistent",
         "evidence_fingerprint"),
        ("mumei.source-evidence-acceptance/v1", "accepted", True,
         "evidence_fingerprint"),
        ("mumei.verify-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
    ],
    "artifact_semantics": [
        ("mumei.native-evidence-acceptance/v1", "accepted", True,
         "evidence_fingerprint"),
    ],
    "file_identity": [
        ("mumei.verify-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.go-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.go-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.ts-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.ts-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.sol-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.sol-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.rust-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.rust-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
    ],
    "producer_authenticity": [
        # A verifying signature binds SOME key to the digest, so it
        # only performs producer_authenticity when the doc also pins
        # the producer key (`key_pinned` under a caller-declared
        # `--expected-producer-key`) — the key's own authenticity still
        # stays unperformed — and the doc's `subject_digest` carrier
        # names this record's bytes.
        ("mumei.signature-verification/v1",
         ("signature_valid", "key_pinned"), True, "subject_digest"),
        ("mumei.verify-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.go-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.go-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.ts-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.ts-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.sol-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.sol-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.rust-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.rust-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
    ],
    # The attempt report's sequence IS the recorded execution lineage
    # for the record its candidate produced, so an accepted report
    # performs `historical_execution` on it at representation level.
    # The native accept routes follow the same convention with a
    # different outcome surface — `acceptance` is the string
    # "accepted", and an accepted run's stdout is the acceptance
    # descriptor itself, so `normalized.stdout.sha256` binds the
    # report to the descriptor its lineage produced.
    "historical_execution": [
        ("mumei.verify-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.native-accept-report/v1", "acceptance", "accepted",
         "normalized.stdout.sha256"),
        ("mumei.native-exit-status-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-stdout-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.native-stderr-accept-report/v1", "acceptance",
         "accepted", "normalized.stdout.sha256"),
        ("mumei.go-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.go-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.ts-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.ts-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.sol-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.sol-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
        ("mumei.rust-summaries-attempt-report/v1", "acceptance.accepted", True,
         "normalized.stdout.sha256"),
        ("mumei.rust-summaries-reuse-attempt-report/v1",
         "acceptance.accepted", True, "normalized.stdout.sha256"),
    ],
}


def _outcome_matches(actual: object, expected: object) -> bool:
    """Strict outcome equality: a declared `1` or `"true"` is not the
    boolean `true` a boolean performer requires, while a string
    outcome like `"consistent"` compares by value."""
    if type(expected) is bool:
        return actual is expected
    return actual == expected


def _record_bound_digest(record: dict, record_digest: str | None) -> str | None:
    """The digest a bound document must name to count for *record*.

    A Core descriptor declares the artifact it evaluated — its
    `evidence_fingerprint` (or `subject_digest`/`record_digest`) names
    the underlying record's bytes, not the descriptor's own. An
    acceptance evaluation names the descriptor it assessed by
    `descriptor_digest`. Folding such a descriptor as the record
    recovers its declared checks against documents bound to the same
    artifact, so the declared carrier wins over the record's own byte
    digest. A record with no declared carrier binds documents to its
    own bytes."""
    for field in (
        "evidence_fingerprint",
        "subject_digest",
        "record_digest",
        # An acceptance evaluation names the descriptor it assessed
        # rather than its own bytes — bound documents recover the
        # descriptor's declared checks (e.g. `descriptor_authenticity`
        # via a signature over the descriptor).
        "descriptor_digest",
    ):
        value = record.get(field)
        if _is_fingerprint(value):
            return value
    return record_digest


def _dotted(doc: dict, path: str) -> object:
    """Resolve a dot-separated field path; a non-dict hop yields None."""
    current: object = doc
    for part in path.split("."):
        if type(current) is not dict:
            return None
        current = current.get(part)
    return current


def _performer_document_applies(
    bind_path: str | None,
    doc: dict,
    bound_digest: str | None,
    record: dict | None = None,
) -> bool:
    """Whether a performer-schema document counts for *this* record.

    A bound performer pins itself to one record's artifact through its
    declared carrier — `evidence_fingerprint` on a Core descriptor,
    `record_digest` on a binding document,
    `normalized.stdout.sha256` on a verify-attempt report — so it only applies when the carrier's
    declared digest equals the record's bound digest (an anonymous
    descriptor, e.g. an artifact acceptance with no record input,
    applies to nothing). A `None` bind path applies record-agnostically
    (the document's own binding is a separate, still-declared check).

    A ``shared:<field>`` bind path instead pins the performer to a
    third artifact both documents assess: it applies only when the
    record and the document both declare a fingerprint under the same
    field name and those digests are equal — e.g. two
    signature-verification docs that each assessed a key registry
    bind through their shared ``registry_digest``, never through the
    record's own bytes."""
    if bind_path is None:
        return True
    if bind_path.startswith("shared:"):
        field = bind_path[len("shared:"):]
        if record is None:
            return False
        doc_digest = _dotted(doc, field)
        record_digest_value = _dotted(record, field)
        return (
            _is_fingerprint(doc_digest)
            and doc_digest == record_digest_value
        )
    return (
        bound_digest is not None
        and _dotted(doc, bind_path) == bound_digest
    )


def evaluate_unperformed_check_recovery(
    record: dict, evidence: list, record_digest: str | None = None
) -> dict:
    """Fold a record's declared ``checks_not_performed`` over the
    supporting documents into a recovery report.

    Emits ``mumei.unperformed-check-recovery/v1``: for each check the
    record declares, `checks` reports one of

    - ``recovered`` — a supporting document carries the declared
      performer schema AND its outcome field is ``true``;
    - ``evidence_failed`` — a document with the performer schema was
      supplied but its outcome field is absent or not ``true``;
    - ``no_evidence`` — no performer schema is declared for the check,
      or no supplied document carries it.

    Schema-open on the record: any object may declare
    ``checks_not_performed`` (non-list/non-string entries are skipped
    and the fold reports ``checks_declared: false`` when the list is
    absent or invalid); a record declaring none — a produced summary
    manifest carries no check fields — is folded over every check
    ``_CHECK_PERFORMERS`` knows, so a bound attempt report still
    recovers what it discharges. Undeclared records recover only
    through bound documents: record-agnostic performers (whose entry
    carries no `bind_path`, e.g. signature-verification and
    freshness-eval reports) are skipped, because without the
    record's own declaration nothing scopes such a document to this
    record. Fail-closed on the evidence: a document is
    only counted when it is a dict whose ``schema_version`` exactly
    names the declared performer.

    This is representation-level composition: the fold does not re-run
    any check (`recovery_enforcement` stays), does not verify the
    supporting documents themselves (`evidence_authenticity` stays —
    they are trusted as declared), and does not bind a document to the
    record it is said to cover (`evidence_binding` stays — a
    freshness doc counts whether or not it was produced for this
    record).

    `record_digest` declares the SHA-256 of the record's bytes (the
    `recovery-eval` route recomputes it from the record file; dict
    callers declare it like `expected_fingerprint`). Bound performer
    documents — each carrying the dotted `bind_path` its entry
    declares — count only when that carrier equals the record's bound
    digest: the record's own declared carrier
    (`evidence_fingerprint`/`subject_digest`/`record_digest`/
    `descriptor_digest`) when it pins another artifact, else
    `record_digest`. So a Core acceptance
    descriptor folded as the record is recovered by a recheck doc
    bound to the *same evidence*, and a verify-attempt report counts
    for the record its `normalized.stdout.sha256` produced, while
    a bound document for different bytes can never recover this
    record's checks. Without a declared digest and no declared
    carrier no bound document can be attributed, so those checks stay
    unrecovered."""
    if type(record) is not dict:
        raise ValueError("unsupported check-recovery request")
    if record_digest is not None and not _is_fingerprint(record_digest):
        raise ValueError("invalid record digest")
    evidence = evidence or []
    if any(type(doc) is not dict for doc in evidence):
        raise ValueError("unsupported check-recovery evidence document")

    bound_digest = _record_bound_digest(record, record_digest)

    declared = record.get("checks_not_performed")
    checks_declared = type(declared) is list
    if checks_declared:
        check_names = [name for name in declared if type(name) is str]
    else:
        # A record that declares no performed/unperformed checks (a
        # freshly produced manifest carries no check fields at all)
        # still gets a fold: every check a performer is known for is
        # a candidate, so a bound attempt report can recover what it
        # discharges. `checks_declared: false` marks the default.
        check_names = sorted(_CHECK_PERFORMERS)

    schema_to_docs: dict = {}
    for doc in evidence:
        schema = doc.get("schema_version")
        if type(schema) is str:
            schema_to_docs.setdefault(schema, []).append(doc)

    checks: dict = {}
    for name in check_names:
        performers = _CHECK_PERFORMERS.get(name, [])
        status = "no_evidence"
        # A binding document's `record_digest` is always the record's
        # byte SHA-256 — `evidence_binding` pins bytes, so it compares
        # against `record_digest` even when the record declares a
        # carrier for a different artifact.
        comparison_digest = (
            record_digest if name == "evidence_binding" else bound_digest
        )
        for schema, field, expected, bind_path in performers:
            if schema not in schema_to_docs:
                continue
            if bind_path is None and not checks_declared:
                # Record-agnostic documents count only against the
                # record's own declared list — without it nothing
                # scopes them to this record, so an unrelated
                # signature-verification or freshness report would
                # otherwise be attributed to it. Undeclared records
                # recover only through bound documents (each matched
                # against the record's bound digest below).
                continue
            if status == "no_evidence":
                status = "evidence_failed"
            fields = field if type(field) is tuple else (field,)
            applies = [
                doc
                for doc in schema_to_docs[schema]
                if _performer_document_applies(
                    bind_path, doc, comparison_digest, record
                )
            ]
            if bind_path is None:
                # Record-agnostic documents make no claim about this
                # record, so disagreement between them is expected —
                # they evaluate different artifacts, not conflicting
                # observations of one. Any true outcome recovers.
                agreed = any(
                    all(
                        _outcome_matches(_dotted(doc, path), expected)
                        for path in fields
                    )
                    for doc in applies
                )
            else:
                # Bound documents all scope to this record, so they
                # must agree on the outcome — a conflicting
                # observation (a revoked-key evaluation beside a
                # clean one for the same record) stays
                # evidence_failed rather than letting any true mask
                # it.
                agreed = bool(applies) and all(
                    all(
                        _outcome_matches(_dotted(doc, path), expected)
                        for path in fields
                    )
                    for doc in applies
                )
            if agreed:
                status = "recovered"
                break
        checks[name] = status

    recovered = [name for name in check_names if checks[name] == "recovered"]
    recovery = {
        "schema_version": UNPERFORMED_CHECK_RECOVERY_SCHEMA,
        "checks_declared": checks_declared,
        "checks": checks,
        "recovered": recovered,
        "unrecovered": [
            name for name in check_names if checks[name] != "recovered"
        ],
        "checks_not_performed": [
            "evidence_binding",
            "evidence_authenticity",
            "recovery_enforcement",
        ],
    }
    return recovery


FRESHNESS_EVALUATION_SCHEMA = "mumei.freshness-evaluation/v1"

# Strict RFC 3339: full date, full time with seconds, optional
# fractional seconds, and a numeric offset or Z. Looser ISO 8601
# shapes `datetime.fromisoformat` accepts (missing seconds, missing
# colon in the offset, date-only, week dates) stay unclaimed.
# ``[0-9]`` rather than ``\d``: the unicode-aware class accepts
# non-ASCII digits (Arabic-Indic etc.) that RFC 3339 excludes and
# ``int()`` happily parses.
_RFC3339_RE = re.compile(
    r"^([0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.([0-9]+))?"
    r"([Zz]|[+-][0-9]{2}:[0-9]{2})$"
)


def _parse_rfc3339(value: object) -> "tuple | None":
    """Parse an RFC 3339 timestamp into ``(low, high)`` bounds, or None.

    Returns two aware datetimes bracketing the claimed instant: the
    whole-second floor plus the declared fractional seconds
    (`low`), and `low` plus one microsecond when the fraction carries
    sub-microsecond precision `datetime` cannot represent (`high`).
    Consumers compare `high` against upper bounds and `low` against
    lower bounds, so sub-microsecond truncation can never turn a
    postdated or stale claim into a pass."""
    from datetime import datetime, timedelta

    if type(value) is not str:
        return None
    match = _RFC3339_RE.match(value.strip())
    if match is None:
        return None
    base, fraction, zone = match.groups()
    text = base + ("+00:00" if zone.upper() == "Z" else zone)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    digits = fraction or ""
    micros = int((digits + "000000")[:6])
    low = parsed + timedelta(microseconds=micros)
    # No int() on the tail — an absurdly long fraction must not trip
    # the integer-digit limit.
    sub_micro = len(digits) > 6 and any(c != "0" for c in digits[6:])
    return low, low + (timedelta(microseconds=1) if sub_micro else timedelta(0))


def _within_age_window(
    produced: datetime, reference: datetime, max_age_seconds: int
) -> bool:
    delta = reference - produced
    delta_us = (
        (delta.days * 86400 + delta.seconds) * 1_000_000
        + delta.microseconds
    )
    return delta_us <= max_age_seconds * 1_000_000


def evaluate_freshness(
    record: dict,
    reference_time: str,
    max_age_seconds: int,
) -> dict:
    """Evaluate a declared record's freshness claim against a declared
    clock.

    Emits ``mumei.freshness-evaluation/v1``. The record is schema-open:
    any JSON object may carry a ``produced_at`` RFC 3339 timestamp —
    its absence (or an unparseable value) reports
    ``freshness_claimed: false`` rather than an error, since the field
    is optional by design and a record without it simply makes no
    freshness claim.

    ``within_window`` holds only when a well-formed ``produced_at``
    exists, does not postdate the declared ``reference_time``, and
    ``produced_at + max_age_seconds >= reference_time``. The
    ``reference_time`` is the caller's declared clock — the fold never
    reads the system clock, so the same documents always evaluate the
    same way.

    ``checks_not_performed`` keeps ``clock_authenticity`` (the declared
    reference time is trusted as supplied), ``producer_time_authenticity``
    (the record's timestamp is a claim by the producer — only a
    signature-bound timestamp upgrades it) and ``freshness_enforcement``
    (the fold reports; gating on freshness is a host decision)."""
    if type(record) is not dict:
        raise ValueError("unsupported freshness evaluation request")
    reference = _parse_rfc3339(reference_time)
    if reference is None:
        raise ValueError("invalid reference time")
    if type(max_age_seconds) is not int or max_age_seconds < 0:
        raise ValueError("invalid max age")
    produced = _parse_rfc3339(record.get("produced_at"))
    claimed = produced is not None
    # Conservative both ways: a claim that could postdate the
    # reference fails the first bound even by a sub-microsecond
    # fraction, and a record only barely inside the window still
    # fails the second.
    within = (
        claimed
        and produced[1] <= reference[0]
        and _within_age_window(
            produced[0], reference[1], max_age_seconds
        )
    )
    return {
        "schema_version": FRESHNESS_EVALUATION_SCHEMA,
        "freshness_claimed": claimed,
        "within_window": within,
        "checks_not_performed": [
            "clock_authenticity",
            "producer_time_authenticity",
            "freshness_enforcement",
        ],
    }
