"""Minimal real process control for declared attempt requests, nothing else.

`AttemptRunner.run` is the single effectful boundary: it spawns one child
for one `AttemptExecutionRequest`, waits bounded by the declared timeout,
terminates runaways and honors one cancellation event. The runner reports
what it observed as `AttemptRecord` events — it does not interpret stdout,
decide success, schedule attempts or publish canonical values. Captured
bytes are truncated at `MAX_STDOUT_BYTES`; `complete` only declares whether
truncation happened, not that the producer stopped writing.
"""

import subprocess
import threading
import time
from dataclasses import dataclass, field

from agent.verification_attempt import (
    MAX_STDOUT_BYTES,
    AttemptEvent,
    AttemptExecutionRequest,
    AttemptRecord,
)

POLL_SECONDS = 0.005
CANCEL_GRACE_MS = 1000
READ_CHUNK = 65_536


class _BoundedCollector:
    """Drains one stream so writers past the pipe buffer never deadlock.

    Keeps only the first `MAX_STDOUT_BYTES`; `truncated` records whether
    more bytes were observed than kept, which is all `complete` declares.
    """

    def __init__(self, stream) -> None:
        self._stream = stream
        self._chunks: list[bytes] = []
        self._kept = 0
        self.truncated = False
        self._thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def join(self) -> None:
        self._thread.join()

    def _drain(self) -> None:
        while True:
            chunk = self._stream.read(READ_CHUNK)
            if not chunk:
                return
            room = MAX_STDOUT_BYTES - self._kept
            if room > 0:
                self._chunks.append(chunk[:room])
                self._kept += len(chunk[:room])
            if len(chunk) > room:
                self.truncated = True

    @property
    def data(self) -> bytes:
        return b"".join(self._chunks)


@dataclass(frozen=True)
class AttemptRunResult:
    """One observed run: a terminal record plus the bounded captured bytes.

    `stdout`/`complete` are collection observations, not success or Evidence
    claims; hosts still bind snapshots with `AttemptOutput` and own canonical
    publication. The record is terminal by construction.
    """

    record: AttemptRecord
    stdout: bytes = field(repr=False)
    complete: bool

    def __post_init__(self) -> None:
        if type(self.record) is not AttemptRecord or not self.record.is_terminal:
            raise ValueError("attempt run result requires a terminal record")
        if type(self.stdout) is not bytes or len(self.stdout) > MAX_STDOUT_BYTES:
            raise ValueError("attempt run result requires bounded bytes")
        if type(self.complete) is not bool:
            raise ValueError("invalid attempt run completeness declaration")


class AttemptRunner:
    """Executes one declared request per call with real process control.

    This is the only effectful boundary: actual spawn, signal, wait and clock
    reads live here, while every decision (what to run, whether to dispatch,
    what the bytes mean) stays with the host. Blocking `run` performs no
    authorization and keeps no state between calls.
    """

    def run(
        self,
        request: AttemptExecutionRequest,
        argv: tuple[str, ...],
        cancel_event: "threading.Event | None" = None,
    ) -> AttemptRunResult:
        """Spawn `argv`, observe one attempt and return a terminal record.

        `request` only binds the record (fingerprint, ordinal, declared
        timeout); the caller decides it is dispatchable via `check_dispatch`.
        On the declared deadline the child is killed and `timed_out` is
        reported; a set `cancel_event` triggers `cancel_requested` then a
        terminate-then-kill sequence ending in `exited` or `cancelled`.
        """
        if type(request) is not AttemptExecutionRequest:
            raise ValueError("attempt run requires an execution request")
        if (
            type(argv) is not tuple
            or not argv
            or any(type(arg) is not str or not arg for arg in argv)
        ):
            raise ValueError("attempt run requires a nonempty immutable argv")
        if cancel_event is not None and type(cancel_event) is not threading.Event:
            raise ValueError("attempt run cancellation requires an event")
        record = AttemptRecord(
            request.request_fingerprint,
            request.attempt_number,
            request.timeout_ms,
        )
        try:
            process = subprocess.Popen(
                list(argv),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return AttemptRunResult(
                record.record(AttemptEvent("started", 0)).record(
                    AttemptEvent("failed", 0)
                ),
                b"",
                True,
            )
        started_at = time.monotonic()
        collector = _BoundedCollector(process.stdout)
        collector.start()
        events = [AttemptEvent("started", 0)]
        cancel_at: int | None = None
        while True:
            elapsed = int((time.monotonic() - started_at) * 1000)
            code = process.poll()
            if code is not None:
                if elapsed >= request.timeout_ms:
                    events.append(AttemptEvent("timed_out", elapsed))
                else:
                    events.append(AttemptEvent("exited", elapsed, code))
                break
            if elapsed >= request.timeout_ms:
                process.kill()
                process.wait()
                events.append(
                    AttemptEvent("timed_out", max(elapsed, request.timeout_ms))
                )
                break
            if (
                cancel_at is not None
                and elapsed - cancel_at >= CANCEL_GRACE_MS
            ):
                process.kill()
                process.wait()
                events.append(
                    AttemptEvent(
                        "cancelled",
                        int((time.monotonic() - started_at) * 1000),
                    )
                )
                break
            if (
                cancel_at is None
                and cancel_event is not None
                and cancel_event.is_set()
            ):
                cancel_at = elapsed
                events.append(AttemptEvent("cancel_requested", elapsed))
                process.terminate()
            try:
                process.wait(timeout=POLL_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        collector.join()
        for event in events:
            record = record.record(event)
        return AttemptRunResult(record, collector.data, not collector.truncated)
