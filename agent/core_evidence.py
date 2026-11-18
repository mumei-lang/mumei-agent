"""Explicit POSIX handoff to a host-trusted Core, not Evidence acceptance.

No default route uses this API. The host must authorize the call and supply a
trusted executable; an absolute path is not authentication or a sandbox.
"""

import json
import os
import selectors
import subprocess
import threading
import time

from agent.verification_attempt import (
    AttemptEvidenceCheck,
    AttemptOutput,
    AttemptSequence,
)

MAX_DIAGNOSTIC_BYTES = 4096
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
        stdout = _run_check(output.stdout, core_executable, timeout_ms, cancel_event)
        _check_cancelled(cancel_event)
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


def evaluate_evidence_check(
    sequence: AttemptSequence, check: AttemptEvidenceCheck
) -> dict:
    """Normalize a declared check record into an acceptance descriptor.

    Emits ``mumei.evidence-check-acceptance/v1``: whether the record binds
    the sequence's CURRENT `evidence_candidate()` (`candidate_match` — a
    stale or foreign check never counts) and `accepted`, which holds only
    when the record is current AND its outcome is `"valid"`. This is
    representation-level acceptance only — the six semantic checks remain
    listed in `checks_not_performed`, and nothing here is Evidence,
    a verdict or a grade promotion. A sequence with no selected result
    raises `ValueError`: there is no current candidate to evaluate."""
    if (
        type(sequence) is not AttemptSequence
        or type(check) is not AttemptEvidenceCheck
    ):
        raise ValueError("unsupported evidence check evaluation request")
    candidate = sequence.evidence_candidate()
    match = (
        check.request_fingerprint == candidate.request_fingerprint
        and check.attempt_number == candidate.attempt_number
        and check.output_fingerprint == candidate.output_fingerprint
    )
    return {
        "schema_version": "mumei.evidence-check-acceptance/v1",
        "request_fingerprint": check.request_fingerprint,
        "attempt_number": check.attempt_number,
        "output_fingerprint": check.output_fingerprint,
        "outcome": check.outcome,
        "candidate_match": match,
        "accepted": match and check.outcome == "valid",
        "checks_not_performed": list(_DIAGNOSTIC["checks_not_performed"]),
    }


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
    body: bytes, executable: str, timeout_ms: int, cancel_event: threading.Event | None
) -> bytes:
    _check_cancelled(cancel_event)
    deadline = time.monotonic() + timeout_ms / 1000
    process = subprocess.Popen(
        [executable, "evidence", "check", "--stdin", "--json"],
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
                        try:
                            chunk = os.read(
                                key.fd, MAX_DIAGNOSTIC_BYTES + 1 - len(buffer)
                            )
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            stream.close()
                        else:
                            buffer.extend(chunk)
                            if len(buffer) > MAX_DIAGNOSTIC_BYTES:
                                raise ValueError
            while True:
                try:
                    code = process.wait(timeout=_wait_timeout(deadline, cancel_event))
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event is None:
                        raise
            _check_cancelled(cancel_event)
            if code != 0 or buffers["stderr"]:
                raise ValueError
        return bytes(buffers["stdout"])
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


def _string_list(value: object) -> bool:
    return type(value) is list and all(type(item) is str for item in value)


def _is_fingerprint(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def evaluate_core_acceptance(
    descriptor: dict, expected_fingerprint: str | None = None
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
    `unperformed_check_recovery` stay unperformed)."""
    if type(descriptor) is not dict:
        raise ValueError("unsupported core acceptance evaluation request")
    if expected_fingerprint is not None and not _is_fingerprint(
        expected_fingerprint
    ):
        raise ValueError("invalid expected evidence fingerprint")
    fields = frozenset(descriptor)
    match = (
        _CORE_ACCEPTANCE_REQUIRED_FIELDS <= fields
        and fields <= _CORE_ACCEPTANCE_REQUIRED_FIELDS | _CORE_ACCEPTANCE_OPTIONAL_FIELDS
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
    evaluation = {
        "schema_version": "mumei.core-acceptance-evaluation/v1",
        "descriptor_match": match,
        "accepted": match and descriptor["accepted"],
        "checks_not_performed": [
            "attempt_binding",
            "descriptor_authenticity",
            "descriptor_freshness",
            "unperformed_check_recovery",
        ],
    }
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

# The only algorithm the closed family admits — no negotiation.
_PRODUCER_SIGNATURE_ALGORITHM = "ed25519"
# ed25519 signatures are 64 bytes.
_PRODUCER_SIGNATURE_HEX_LEN = 128


def _is_hex(value: object, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def evaluate_signature_envelope(
    envelope: dict,
    expected_subject: str | None = None,
    expected_key: str | None = None,
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

    This is representation-level only: the fold checks the envelope's
    shape and declared pins, never the ed25519 signature bytes
    (`signature_verification` stays), never the key's own authenticity
    (the declared pin is trusted as supplied — `key_authenticity`
    stays), and never freshness or revocation. A matched envelope whose
    declared pins disagree reports `false` observations, never an
    error."""
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
    fields = frozenset(envelope)
    match = (
        fields == _PRODUCER_SIGNATURE_REQUIRED_FIELDS
        and envelope["schema_version"] == PRODUCER_SIGNATURE_SCHEMA
        and envelope["algorithm"] == _PRODUCER_SIGNATURE_ALGORITHM
        and _is_fingerprint(envelope["subject_digest"])
        and _is_hex(
            envelope["signature"], _PRODUCER_SIGNATURE_HEX_LEN
        )
        and type(envelope["producer_key_id"]) is str
        and envelope["producer_key_id"] != ""
    )
    evaluation = {
        "schema_version": "mumei.signature-envelope-evaluation/v1",
        "envelope_match": match,
        "checks_not_performed": [
            "subject_binding",
            "key_binding",
            "signature_verification",
            "key_authenticity",
            "envelope_freshness",
            "key_revocation",
        ],
    }
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
    return evaluation
