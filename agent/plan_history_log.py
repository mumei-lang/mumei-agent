"""Opt-in durable log of verification-plan projections, not dispatch or Evidence.

The digest chain detects in-file edits, reordering and mid-file deletion.
Tail truncation or rollback is detected only against a host-pinned
``expected_head``. This is not authentication: a writer can rewrite the whole
chain. Plans contain only the existing non-secret ``to_dict()`` projection.
The log is not a dispatch or acceptance record.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent.verification_planner import VerificationPlan

ENTRY_SCHEMA = "mumei.verification-plan-history-entry/v1"
MAX_ENTRY_BYTES = 1 << 20
MAX_LOG_BYTES = 16 << 20

_ENTRY_KEYS = {"schema_version", "index", "prev_digest", "plan", "digest"}
_PLAN_SCHEMA = "mumei.verification-plan/v1"
_INVALID_ENTRY = "invalid plan history entry"
_INVALID_LOG = "invalid plan history log"
_INVALID_HEAD = "invalid expected plan history head"
_HEAD_MISMATCH = "plan history head mismatch"
_ENTRY_TOO_LARGE = "plan history entry exceeds size limit"
_LOG_TOO_LARGE = "plan history log exceeds size limit"
_IO_FAILURE = "plan history I/O failed"
_PLAN_TYPE_ERROR = "plan history append requires a verification plan"

_path_locks: dict[str, threading.Lock] = {}
_path_locks_guard = threading.Lock()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _reject_json_constant(value: str) -> None:
    raise ValueError(_INVALID_LOG)


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _as_path(path: str) -> Path:
    try:
        result = Path(path)
        if "\x00" in os.fspath(result):
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ValueError(_IO_FAILURE) from None


def _read_entries(
    path: Path, expected_head: str | None = None
) -> tuple[tuple[dict, ...], int, bool]:
    if expected_head is not None and not _is_digest(expected_head):
        raise ValueError(_INVALID_HEAD)

    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_LOG_BYTES + 1)
    except FileNotFoundError:
        if expected_head is not None:
            raise ValueError(_HEAD_MISMATCH) from None
        return (), 0, False
    except (OSError, ValueError):
        raise ValueError(_IO_FAILURE) from None

    if len(raw) > MAX_LOG_BYTES:
        raise ValueError(_LOG_TOO_LARGE)
    if raw and not raw.endswith(b"\n"):
        raise ValueError(_INVALID_LOG)

    entries: list[dict] = []
    previous_digest: str | None = None
    for index, line in enumerate(raw.splitlines(keepends=True)):
        if len(line) > MAX_ENTRY_BYTES:
            raise ValueError(_ENTRY_TOO_LARGE)
        if not line.endswith(b"\n") or line == b"\n":
            raise ValueError(_INVALID_LOG)
        try:
            entry = json.loads(
                line[:-1].decode("utf-8"), parse_constant=_reject_json_constant
            )
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ValueError(_INVALID_LOG) from None
        if type(entry) is not dict or set(entry) != _ENTRY_KEYS:
            raise ValueError(_INVALID_ENTRY)
        try:
            canonical_entry = _canonical_json(entry)
        except (RecursionError, ValueError):
            raise ValueError(_INVALID_ENTRY) from None
        if canonical_entry + b"\n" != line:
            raise ValueError(_INVALID_ENTRY)
        if entry["schema_version"] != ENTRY_SCHEMA:
            raise ValueError(_INVALID_ENTRY)
        if type(entry["index"]) is not int or entry["index"] != index:
            raise ValueError(_INVALID_ENTRY)
        if entry["prev_digest"] != previous_digest:
            raise ValueError(_INVALID_ENTRY)

        plan = entry["plan"]
        if type(plan) is not dict or plan.get("schema_version") != _PLAN_SCHEMA:
            raise ValueError(_INVALID_ENTRY)
        digest = entry["digest"]
        if not _is_digest(digest):
            raise ValueError(_INVALID_ENTRY)
        unsigned = {key: value for key, value in entry.items() if key != "digest"}
        try:
            computed_digest = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
        except (RecursionError, ValueError):
            raise ValueError(_INVALID_ENTRY) from None
        if computed_digest != digest:
            raise ValueError(_INVALID_ENTRY)

        entries.append(entry)
        previous_digest = digest

    if expected_head is not None and (
        not entries or entries[-1]["digest"] != expected_head
    ):
        raise ValueError(_HEAD_MISMATCH)
    return tuple(entries), len(raw), True


def read_plan_history(
    path: str, *, expected_head: str | None = None
) -> tuple[dict, ...]:
    """Read and validate a canonical plan-history digest chain."""
    history_path = _as_path(path)
    entries, _, _ = _read_entries(history_path, expected_head)
    return tuple(entry["plan"] for entry in entries)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    with _path_locks_guard:
        lock = _path_locks.setdefault(str(lock_path.resolve()), threading.Lock())
    with lock:
        try:
            import fcntl
        except ImportError:
            yield
            return

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _fsync_directory(directory: Path) -> None:
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(directory_fd)
        except OSError as error:
            if error.errno not in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS):
                raise
    finally:
        os.close(directory_fd)


def append_plan_history(path: str, plan: VerificationPlan) -> str:
    """Append one plan projection and return its digest."""
    if type(plan) is not VerificationPlan:
        raise ValueError(_PLAN_TYPE_ERROR)
    history_path = _as_path(path)

    try:
        history_path = history_path.resolve()
        missing_directories = []
        directory = history_path.parent
        while not directory.exists():
            missing_directories.append(directory)
            if directory.parent == directory:
                break
            directory = directory.parent
        history_path.parent.mkdir(parents=True, exist_ok=True)
        for directory in missing_directories:
            _fsync_directory(directory.parent)
        with _locked(history_path):
            entries, current_size, _ = _read_entries(history_path)
            unsigned = {
                "schema_version": ENTRY_SCHEMA,
                "index": len(entries),
                "prev_digest": entries[-1]["digest"] if entries else None,
                "plan": plan.to_dict(),
            }
            digest = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
            line = _canonical_json({**unsigned, "digest": digest}) + b"\n"
            if len(line) > MAX_ENTRY_BYTES:
                raise ValueError(_ENTRY_TOO_LARGE)
            if current_size + len(line) > MAX_LOG_BYTES:
                raise ValueError(_LOG_TOO_LARGE)

            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
            try:
                file_fd = os.open(history_path, flags | os.O_EXCL, 0o600)
                created = True
            except FileExistsError:
                file_fd = os.open(history_path, flags, 0o600)
                created = False
            try:
                remaining = memoryview(line)
                while remaining:
                    try:
                        written = os.write(file_fd, remaining)
                    except InterruptedError:
                        continue
                    if written <= 0:
                        raise OSError
                    remaining = remaining[written:]
                os.fsync(file_fd)
            except BaseException:
                try:
                    os.ftruncate(file_fd, current_size)
                except OSError:
                    pass
                try:
                    os.fsync(file_fd)
                except OSError:
                    pass
                raise
            finally:
                os.close(file_fd)
            if created:
                _fsync_directory(history_path.parent)
            return digest
    except ValueError:
        raise
    except (OSError, RuntimeError):
        raise ValueError(_IO_FAILURE) from None
