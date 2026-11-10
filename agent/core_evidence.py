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

from agent.verification_attempt import AttemptOutput

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


def check_evidence_representation(
    output: AttemptOutput,
    *,
    core_executable: str,
    timeout_ms: int,
    cancel_event: threading.Event | None = None,
) -> None:
    """Send original bytes to Core; return None only for its known v1 diagnostic.

    This runs a local executable, independently of adapter permission metadata.
    The host owns executable trust/authorization and canonical output lineage.
    No Evidence/request contract matching, proof, receipt or grade is produced.
    Process creation itself is not interruptible; failed checks allow up to one
    additional second to kill/reap the direct child, not a descendant sandbox.
    An optional host-owned Event is sampled cooperatively, including before
    spawn and normal return. Keep it set: set/clear pulses may not be observed.
    Cancellation is not an atomic completion handshake or an attempt report.
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
    ):
        raise ValueError("unsupported Core representation check request")
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
        raise ValueError("Core Evidence representation check failed") from None


def _check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CoreCheckCancelled("Core Evidence representation check cancelled") from None


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
    streams = {"stdin": process.stdin, "stdout": process.stdout, "stderr": process.stderr}
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
                            chunk = os.read(key.fd, MAX_DIAGNOSTIC_BYTES + 1 - len(buffer))
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
