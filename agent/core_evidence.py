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

SIGNATURE_ENVELOPE_EVALUATION_SCHEMA = (
    "mumei.signature-envelope-evaluation/v1"
)

# A caller-supplied revocation list: a closed-shape declared document
# naming the producer key ids the caller considers revoked — trusted as
# declared, exactly like every other supporting document.
KEY_REVOCATION_LIST_SCHEMA = "mumei.key-revocation-list/v1"

_KEY_REVOCATION_LIST_REQUIRED_FIELDS = frozenset(
    {"schema_version", "revoked_keys"}
)


def revocation_key_set(document: dict) -> frozenset:
    """Fold a declared ``mumei.key-revocation-list/v1`` into a key set.

    The list is a closed shape: `schema_version` names the schema and
    `revoked_keys` is a list of non-empty strings — producer key ids in
    the same label space `producer_key_id`/`--expected-producer-key`
    pin. A malformed or foreign document raises ValueError rather than
    silently revoking nothing or everything: the caller supplied it as
    input, so a wrong shape is a caller error like a malformed
    ``--record``.
    """
    if type(document) is not dict:
        raise ValueError("invalid key-revocation list document")
    revoked = document.get("revoked_keys")
    if (
        frozenset(document) != _KEY_REVOCATION_LIST_REQUIRED_FIELDS
        or document["schema_version"] != KEY_REVOCATION_LIST_SCHEMA
        or type(revoked) is not list
        or any(
            type(key) is not str or key == "" for key in revoked
        )
    ):
        raise ValueError("invalid key-revocation list document")
    return frozenset(revoked)


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


def evaluate_signature_envelope(
    envelope: dict,
    expected_subject: str | None = None,
    expected_key: str | None = None,
    revoked_keys: frozenset | None = None,
    key_registry: dict | None = None,
    reference_time: str | None = None,
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
    if key_registry is not None:
        if reference is None:
            raise ValueError("key registry requires a reference time")
    elif reference is not None:
        raise ValueError("reference time requires a key registry")
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
        "schema_version": SIGNATURE_ENVELOPE_EVALUATION_SCHEMA,
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
    if key_registry is not None:
        if reference is None:
            raise ValueError("key registry requires a reference time")
    elif reference is not None:
        raise ValueError("reference time requires a key registry")
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
# SHA-256 a consumer reproduces with `sha256sum`.
_BINDING_CARRIERS: dict = {
    PRODUCER_SIGNATURE_SCHEMA: "subject_digest",
    "mumei.source-evidence-acceptance/v1": "evidence_fingerprint",
    "mumei.native-evidence-acceptance/v1": "evidence_fingerprint",
    # `recheck-source --json` emits the same binding convention — the
    # diagnostic stays anonymous and non-reusable, but its fingerprint
    # pins the consistency verdict to the record it was derived from.
    "mumei.source-evidence-recheck/v1": "evidence_fingerprint",
    # The verification doc echoes the envelope's `subject_digest` — the
    # record digest the signature covers — so it binds to the record
    # bytes like the envelope itself.
    SIGNATURE_VERIFICATION_SCHEMA: "subject_digest",
    # The evaluation doc echoes the same digest — a bound
    # `key_not_revoked` observation names the record the signature
    # covers, not just an unscoped envelope.
    SIGNATURE_ENVELOPE_EVALUATION_SCHEMA: "subject_digest",
}


def evaluate_evidence_binding(record: bytes, document: dict) -> dict:
    """Pin a declared subject-bearing document to record bytes.

    Emits ``mumei.evidence-binding/v1``: `record_digest` is the
    SHA-256 lowercase hex of the supplied record's raw bytes —
    recomputed by the fold, never trusted from a declared pin.
    `carrier_match` holds only when `document` is an object whose
    `schema_version` names a declared subject-bearing schema (a
    producer-signature envelope's `subject_digest`, or a Core
    acceptance descriptor's `evidence_fingerprint`). `subject_declared`
    holds only when the matched carrier's subject field carries a
    64-char lowercase-hex value. `bound` holds only when all three
    hold AND the declared digest equals `record_digest` — a mismatched
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
    field = (
        _BINDING_CARRIERS.get(schema) if type(schema) is str else None
    )
    match = field is not None
    declared = (
        _is_fingerprint(document.get(field)) if match else False
    )
    return {
        "schema_version": EVIDENCE_BINDING_SCHEMA,
        "record_digest": record_digest,
        "carrier_match": match,
        "subject_declared": declared,
        "bound": match
        and declared
        and document[field] == record_digest,
        "checks_not_performed": [
            "carrier_authenticity",
            "binding_enforcement",
        ],
    }


# Unperformed-check recovery schema (the composition fold issue
# mumei-agent#897's memo fixes): which of a record's declared
# ``checks_not_performed`` a set of supporting documents covers.
UNPERFORMED_CHECK_RECOVERY_SCHEMA = "mumei.unperformed-check-recovery/v1"

# Which emitted schema performs each check name, the outcome field and
# the value it must hold for the check to count as recovered. A document
# never gets to declare its own coverage — attribution is pinned to the
# emitted schema, so a foreign document claiming a check cannot count.
_CHECK_PERFORMERS: dict = {
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
    "envelope_freshness": [
        ("mumei.freshness-evaluation/v1", "within_window", True, None),
    ],
    "descriptor_freshness": [
        ("mumei.freshness-evaluation/v1", "within_window", True, None),
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
    "historical_execution": [
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
    the underlying record's bytes, not the descriptor's own. Folding
    such a descriptor as the record recovers its declared checks
    against documents bound to the same artifact, so the declared
    carrier wins over the record's own byte digest. A record with no
    declared carrier binds documents to its own bytes."""
    for field in ("evidence_fingerprint", "subject_digest", "record_digest"):
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
    bind_path: str | None, doc: dict, bound_digest: str | None
) -> bool:
    """Whether a performer-schema document counts for *this* record.

    A bound performer pins itself to one record's artifact through its
    declared carrier — `evidence_fingerprint` on a Core descriptor,
    `record_digest` on a binding document,
    `normalized.stdout.sha256` on a verify-attempt report — so it only applies when the carrier's
    declared digest equals the record's bound digest (an anonymous
    descriptor, e.g. an artifact acceptance with no record input,
    applies to nothing). A `None` bind path applies record-agnostically
    (the document's own binding is a separate, still-declared check)."""
    if bind_path is None:
        return True
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
    (`evidence_fingerprint`/`subject_digest`/`record_digest`) when it
    pins another artifact, else `record_digest`. So a Core acceptance
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
                    bind_path, doc, comparison_digest
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
    from datetime import timedelta

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
        and produced[0] + timedelta(seconds=max_age_seconds) >= reference[1]
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
