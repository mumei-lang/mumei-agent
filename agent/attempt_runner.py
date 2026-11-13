"""Minimal real process control for declared attempt requests, nothing else.

`AttemptRunner.run` is the single effectful boundary: it spawns one child
for one `AttemptExecutionRequest`, waits bounded by the declared timeout,
terminates runaways and honors one cancellation event. The runner reports
what it observed as `AttemptRecord` events — it does not interpret stdout,
decide success, schedule attempts or publish canonical values. Captured
bytes are truncated at `MAX_STDOUT_BYTES`; `complete` only declares whether
truncation happened, not that the producer stopped writing.
"""

import hashlib
import subprocess
import threading
import time
from dataclasses import dataclass, field

from agent.verification_attempt import (
    MAX_STDOUT_BYTES,
    AttemptEvent,
    AttemptExecutionRequest,
    AttemptNormalizedResult,
    AttemptRecord,
)

try:  # POSIX-only; a declared memory bound is unavailable elsewhere.
    import resource
except ImportError:  # pragma: no cover - exercised only off POSIX
    resource = None

POLL_SECONDS = 0.005
CANCEL_GRACE_MS = 1000
READ_CHUNK = 65_536
COLLECTOR_JOIN_SECONDS = 5.0
MAX_MEMORY_BOUND_MB = 1_048_576


def _memory_bound_preexec(bound_mb: int):
    def _apply() -> None:
        limit = bound_mb * 1_048_576
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    return _apply


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

    def join(self, timeout: float) -> None:
        """Wait for the drain to finish; a live thread means a stuck pipe.

        A grandchild can keep stdout open after the child exits, so the join
        is bounded: when the thread outlives the budget the kept bytes are
        still returned and `truncated` marks the collection incomplete.
        """
        self._thread.join(timeout)
        if self._thread.is_alive():
            self.truncated = True

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

    def normalized(self) -> AttemptNormalizedResult:
        """Normalize this observation into detached metadata; never a verdict.

        The result names the request binding, the terminal outcome and the
        bounded-output manifest — no raw bytes, no success claim, no
        acceptance. Hosts still own interpretation and publication.
        """
        last = self.record.events[-1]
        return AttemptNormalizedResult(
            self.record.request_fingerprint,
            self.record.attempt_number,
            self.record.timeout_ms,
            self.record.state,
            last.elapsed_ms,
            last.exit_code,
            len(self.stdout),
            hashlib.sha256(self.stdout).hexdigest(),
            self.complete,
        )


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
        memory_bound_mb: int | None = None,
    ) -> AttemptRunResult:
        """Spawn `argv`, observe one attempt and return a terminal record.

        `request` only binds the record (fingerprint, ordinal, declared
        timeout); the caller decides it is dispatchable via `check_dispatch`.
        On the declared deadline the child is killed and `timed_out` is
        reported; a set `cancel_event` triggers `cancel_requested` then a
        terminate-then-kill sequence ending in `exited` or `cancelled`.
        `memory_bound_mb` applies a declared POSIX `RLIMIT_AS` ceiling to
        the child's whole address space — a best-effort bound, not a
        sandbox: it covers no CPU, I/O, network or permission policy, and
        exceeding it surfaces only as an ordinary observed outcome (`exited`
        with its code, `failed` or `timed_out`), never diagnosed as a
        resource violation.
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
        if memory_bound_mb is not None and (
            type(memory_bound_mb) is not int
            or not 1 <= memory_bound_mb <= MAX_MEMORY_BOUND_MB
        ):
            raise ValueError("invalid attempt run memory bound")
        if memory_bound_mb is not None and resource is None:
            raise ValueError(
                "attempt run memory bound requires a POSIX resource boundary"
            )
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
                preexec_fn=(
                    _memory_bound_preexec(memory_bound_mb)
                    if memory_bound_mb is not None
                    else None
                ),
            )
        except (OSError, subprocess.SubprocessError):
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
        collector.join(COLLECTOR_JOIN_SECONDS)
        for event in events:
            record = record.record(event)
        return AttemptRunResult(record, collector.data, not collector.truncated)
