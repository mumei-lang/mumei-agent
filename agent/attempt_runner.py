"""Minimal real process control for declared attempt requests, nothing else.

`AttemptRunner.run` is the single effectful boundary: it spawns one child
for one `AttemptExecutionRequest`, waits bounded by the declared timeout,
terminates runaways and honors one cancellation event. The runner reports
what it observed as `AttemptRecord` events — it does not interpret stdout,
decide success, schedule attempts or publish canonical values. Each captured
stream is truncated at `MAX_STDOUT_BYTES`; `complete` only declares whether
truncation happened, not that the producer stopped writing.
"""

import hashlib
import os
import platform
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from agent.verification_attempt import (
    MAX_COUNTER,
    MAX_STDOUT_BYTES,
    AttemptEvent,
    AttemptExecutionRequest,
    AttemptNormalizedResult,
    AttemptOutput,
    AttemptRecord,
    AttemptSequence,
    AttemptSequenceStore,
)

try:  # POSIX-only; a declared memory bound is unavailable elsewhere.
    import resource
except ImportError:  # pragma: no cover - exercised only off POSIX
    resource = None

# A session-leader child owns its process group, so a deadline or
# cancellation kill reaches helpers the child spawned itself instead
# of orphaning them. Off POSIX the runner falls back to signalling
# the direct child only.
_PROCESS_GROUP = os.name == "posix" and hasattr(os, "killpg")


def _signal_tree(process: subprocess.Popen, terminate: bool) -> None:
    """Signal the child's whole process group, or just the child.

    Group delivery fails closed to the direct signal when the group
    is already gone or the platform cannot signal one — the child
    still receives its deadline or cancellation signal.
    """
    if _PROCESS_GROUP:
        try:
            os.killpg(
                process.pid,
                signal.SIGTERM if terminate else signal.SIGKILL,
            )
            return
        except OSError:
            pass
    if terminate:
        process.terminate()
    else:
        process.kill()

POLL_SECONDS = 0.005
CANCEL_GRACE_MS = 1000
READ_CHUNK = 65_536
COLLECTOR_JOIN_SECONDS = 5.0
MAX_MEMORY_BOUND_MB = 1_048_576
# Upper bound on bytes a host may feed into a spawned attempt's stdin.
MAX_FEED_BYTES = 65_536


def minimal_environment() -> dict[str, str]:
    environment = {}
    if "PATH" in os.environ:
        environment["PATH"] = os.environ["PATH"]
    if os.name == "nt" and "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return environment


def _writable_poller(fd: int) -> "select.poll | None":
    """A writability waiter with no fd-number ceiling, or None.

    `select.select` refuses descriptors >= FD_SETSIZE (1024) on POSIX:
    a long-running host holding that many descriptors (an MCP server
    on a busy box) hands the feed pipe a high-numbered fd, every
    select() raises ValueError, and the feed silently becomes empty.
    `poll` has no such bound; `select` stays only as the fallback."""
    try:
        poller = select.poll()
    except AttributeError:
        return None
    try:
        poller.register(
            fd,
            select.POLLOUT | select.POLLERR | select.POLLHUP | select.POLLNVAL,
        )
    except (OSError, ValueError):
        return None
    return poller


def _feed_stdin(
    process: subprocess.Popen, data: bytes, stop: threading.Event
) -> None:
    """Write `data` to the child's stdin then close it.

    Runs on a daemon thread writing in non-blocking chunks: a
    bounded write (<= MAX_FEED_BYTES) fits the pipe buffer or drains
    as the child reads; a child that exits early or never reads
    surfaces `BrokenPipeError`/EPIPE — simply the observed run
    outcome. `stop` (set once the run is terminal) bounds the worst
    case: a descendant that inherits the read end but never reads
    leaves the pipe full forever, and without the event the blocked
    write would linger past the join timeout."""
    fd = process.stdin.fileno()
    try:
        os.set_blocking(fd, False)
    except OSError:
        pass
    poller = _writable_poller(fd)
    view = memoryview(data)
    offset = 0
    while offset < len(view) and not stop.is_set():
        if poller is not None:
            try:
                events = poller.poll(int(POLL_SECONDS * 1000) or 1)
            except OSError:
                break
            if not events:
                continue
            mask = events[0][1]
            if mask & select.POLLNVAL:
                break
            if not mask & (select.POLLOUT | select.POLLERR | select.POLLHUP):
                continue
        else:
            try:
                _, writable, _ = select.select([], [fd], [], POLL_SECONDS)
            except (OSError, ValueError):
                break
            if not writable:
                continue
        try:
            offset += os.write(fd, view[offset:])
        except BlockingIOError:
            continue
        except (BrokenPipeError, OSError, ValueError):
            break
    try:
        process.stdin.close()
    except (OSError, ValueError):
        pass


def _memory_bound_preexec(bound_mb: int):
    def _apply() -> None:
        limit = bound_mb * 1_048_576
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    return _apply


# `prlimit` applies the same RLIMIT_AS as `preexec_fn` but through a
# plain exec, so a bounded spawn avoids `preexec_fn` entirely — the
# mechanism CPython docs warn can deadlock in a multithreaded
# process. A POSIX `sh -c 'ulimit -v K; exec "$@"'` wrapper does the
# same on hosts without prlimit (e.g. macOS): `ulimit -v` sets
# RLIMIT_AS in the shell and `exec` carries it into the target —
# still a pure exec chain. `preexec_fn` remains only as the last
# resort when neither wrapper exists.
_PRLIMIT = shutil.which("prlimit")


def _detect_ulimit_sh() -> "str | None":
    """A POSIX `sh` supporting `ulimit -v` (RLIMIT_AS), or None.

    The fallback bound depends on the shell actually applying the
    limit, so it is probed once at import: `ulimit -v` with no operand
    queries the current bound and exits nonzero where `-v` is
    unsupported. A present-but-incapable `sh` is treated as absent so
    the `preexec_fn` fallback still applies. Only a POSIX host
    qualifies — on Windows an `sh` in PATH (e.g. Git Bash) may answer
    the probe yet cannot enforce RLIMIT_AS, and accepting a bound the
    platform cannot honor is worse than rejecting it statically."""
    if os.name != "posix":
        return None
    sh = shutil.which("sh")
    if sh is None:
        return None
    try:
        supported = subprocess.run(
            [sh, "-c", "ulimit -v >/dev/null 2>&1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        supported = False
    return sh if supported else None


_SH = _detect_ulimit_sh()


def _detect_unshare() -> "str | None":
    """An `unshare` supporting a fresh user/network namespace, or None."""
    if not sys.platform.startswith("linux"):
        return None
    unshare = shutil.which("unshare")
    if unshare is None:
        return None
    try:
        supported = subprocess.run(
            [unshare, "--net", "--map-current-user", "--", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        supported = False
    return unshare if supported else None


_UNSHARE = _detect_unshare()

_FILESYSTEM_READ_BASE_ROOTS = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib32",
    "/lib64",
    "/libx32",
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/opt",
    "/snap",
    "/nix/store",
    "/run/systemd/resolve",
)


def _resolved_spawn_target(
    name: str, environment: dict[str, str] | None = None
) -> str | None:
    if environment is None:
        resolved = shutil.which(name)
        if resolved is not None:
            return resolved
        path = os.environ.get("PATH")
        return shutil.which(name, path=".") if path == "" else None
    path = environment.get("PATH", os.defpath)
    resolved = shutil.which(name, path=path)
    if resolved is not None:
        return resolved
    return shutil.which(name, path=".") if path == "" else None


def _filesystem_read_allowed_roots(
    resolved_executable: str,
) -> tuple[str, ...]:
    resolved = resolved_executable
    roots = [
        *_FILESYSTEM_READ_BASE_ROOTS,
        os.path.realpath(os.path.dirname(resolved) or os.curdir),
        os.path.dirname(os.path.realpath(resolved)),
    ]
    return tuple(dict.fromkeys(roots))


def _path_is_under_roots(path: str, roots: tuple[str, ...]) -> bool:
    candidate = os.path.realpath(path)
    for root in roots:
        resolved_root = os.path.realpath(root)
        try:
            if os.path.commonpath((candidate, resolved_root)) == resolved_root:
                return True
        except ValueError:
            continue
    return False


_FILESYSTEM_WRITE_ISOLATION_SETUP_SCRIPT = """import ctypes, os
class _MountAttr(ctypes.Structure):
    _fields_ = [
        ("attr_set", ctypes.c_uint64),
        ("attr_clr", ctypes.c_uint64),
        ("propagation", ctypes.c_uint64),
        ("userns_fd", ctypes.c_uint64),
    ]

def _make_mounts_readonly():
    uid = os.getuid()
    gid = os.getgid()
    libc = ctypes.CDLL(None, use_errno=True)
    libc.unshare.argtypes = [ctypes.c_int]
    libc.unshare.restype = ctypes.c_int
    ctypes.set_errno(0)
    if libc.unshare(0x10000000 | 0x00020000) != 0:
        return False
    try:
        for path, value in (
            ("/proc/self/setgroups", "deny"),
            ("/proc/self/uid_map", f"{uid} {uid} 1"),
            ("/proc/self/gid_map", f"{gid} {gid} 1"),
        ):
            with open(path, "w", encoding="ascii") as mapping:
                if mapping.write(value) != len(value):
                    return False
    except Exception:
        return False
    libc.mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    libc.mount.restype = ctypes.c_int
    ctypes.set_errno(0)
    mounted = libc.mount(
        None,
        b"/",
        None,
        0x4000 | (1 << 18),
        None,
    )
    if mounted != 0:
        return False
    attr = _MountAttr(1, 0, 0, 0)
    libc.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    result = libc.syscall(
        ctypes.c_long(442),
        ctypes.c_long(-100),
        ctypes.c_char_p(b"/"),
        ctypes.c_long(0x8000),
        ctypes.byref(attr),
        ctypes.c_size_t(ctypes.sizeof(attr)),
    )
    if result != 0:
        return False
    libc.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    libc.prctl.restype = ctypes.c_int
    ctypes.set_errno(0)
    if libc.prctl(28, 0xEF, 0, 0, 0) != 0:
        return False
    ctypes.set_errno(0)
    if libc.prctl(47, 4, 0, 0, 0) != 0:
        return False
    try:
        with open(
            "/proc/sys/kernel/cap_last_cap", "r", encoding="ascii"
        ) as cap_last_file:
            cap_last = int(cap_last_file.read())
    except Exception:
        return False
    if cap_last < 0:
        return False
    for capability in range(cap_last + 1):
        ctypes.set_errno(0)
        if libc.prctl(24, capability, 0, 0, 0) != 0:
            return False

    class _CapHeader(ctypes.Structure):
        _fields_ = [
            ("version", ctypes.c_uint32),
            ("pid", ctypes.c_int),
        ]

    class _CapData(ctypes.Structure):
        _fields_ = [
            ("effective", ctypes.c_uint32),
            ("permitted", ctypes.c_uint32),
            ("inheritable", ctypes.c_uint32),
        ]

    header = _CapHeader(0x20080522, 0)
    data = (_CapData * 2)()
    libc.capset.argtypes = [
        ctypes.POINTER(_CapHeader),
        ctypes.POINTER(_CapData),
    ]
    libc.capset.restype = ctypes.c_int
    ctypes.set_errno(0)
    if libc.capset(ctypes.byref(header), data) != 0:
        return False
    ctypes.set_errno(0)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        return False
    return True
"""
_FILESYSTEM_WRITE_PROBE_SCRIPT = (
    f"exec({_FILESYSTEM_WRITE_ISOLATION_SETUP_SCRIPT!r}, globals())\n"
    "raise SystemExit(0 if _make_mounts_readonly() else 1)\n"
)


def _detect_filesystem_write_isolation() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        return subprocess.run(
            [sys.executable, "-I", "-c", _FILESYSTEM_WRITE_PROBE_SCRIPT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).returncode == 0
    except Exception:
        return False


_FILESYSTEM_WRITE_ISOLATION_ENFORCEABLE = (
    _detect_filesystem_write_isolation()
)
_PROCESS_SPAWN_ISOLATION_SETUP_SCRIPT = """import ctypes, errno, os, platform, sys, threading

def _install_process_spawn_filter():
    try:
        machine = platform.machine().lower()
        if sys.byteorder != "little":
            return False
        if machine == "x86_64":
            audit_arch = 0xC000003E
            fork_vfork = (57, 58)
            clone = 56
        elif machine == "aarch64":
            audit_arch = 0xC00000B7
            fork_vfork = ()
            clone = 220
        else:
            return False

        class _SockFilter(ctypes.Structure):
            _fields_ = [
                ("code", ctypes.c_ushort),
                ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte),
                ("k", ctypes.c_uint),
            ]

        class _SockFprog(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ushort),
                ("filters", ctypes.POINTER(_SockFilter)),
            ]

        instructions = []

        def statement(code, value):
            instructions.append(_SockFilter(code, 0, 0, value))

        def jump(code, value, true_skip=0, false_skip=0):
            instructions.append(
                _SockFilter(code, true_skip, false_skip, value)
            )

        def deny(error):
            statement(0x06, 0x00050000 | (error & 0xFFFF))

        statement(0x20, 4)
        jump(0x15, audit_arch, 1, 0)
        deny(errno.EPERM)
        if machine == "x86_64":
            statement(0x20, 0)
            statement(0x54, 0x40000000)
            jump(0x15, 0, 1, 0)
            deny(errno.EPERM)
        statement(0x20, 0)
        for number in fork_vfork:
            jump(0x15, number, 0, 1)
            deny(errno.EPERM)
        jump(0x15, 435, 0, 1)
        deny(errno.ENOSYS)
        jump(0x15, clone, 0, 4)
        statement(0x20, 16)
        jump(0x45, 0x00010000, 1, 0)
        deny(errno.EPERM)
        statement(0x06, 0x7FFF0000)
        statement(0x06, 0x7FFF0000)
        program_filters = (_SockFilter * len(instructions))(
            *instructions
        )
        program = _SockFprog(len(instructions), program_filters)
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        libc.prctl.restype = ctypes.c_int
        ctypes.set_errno(0)
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            return False
        ctypes.set_errno(0)
        if libc.prctl(
            22, 2, ctypes.addressof(program), 0, 0
        ) != 0:
            return False
        return True
    except Exception:
        return False
"""
_FILESYSTEM_READ_ISOLATION_SETUP_SCRIPT = """import ctypes, os, platform, sys

def _install_filesystem_read_isolation(roots):
    try:
        if (
            not sys.platform.startswith("linux")
            or sys.byteorder != "little"
            or platform.machine().lower() not in {"x86_64", "aarch64"}
            or not hasattr(os, "O_PATH")
        ):
            return False

        class _RulesetAttr(ctypes.Structure):
            _fields_ = [("handled_access_fs", ctypes.c_uint64)]

        class _PathBeneathAttr(ctypes.Structure):
            _pack_ = 1
            _fields_ = [
                ("allowed_access", ctypes.c_uint64),
                ("parent_fd", ctypes.c_int32),
            ]

        if ctypes.sizeof(_RulesetAttr) != 8:
            return False
        if ctypes.sizeof(_PathBeneathAttr) != 12:
            return False

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        libc.prctl.restype = ctypes.c_int
        libc.syscall.restype = ctypes.c_long

        ctypes.set_errno(0)
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            return False

        ctypes.set_errno(0)
        abi = libc.syscall(
            ctypes.c_long(444),
            ctypes.c_void_p(),
            ctypes.c_size_t(0),
            ctypes.c_uint(1),
        )
        if abi < 1:
            return False

        ruleset_attr = _RulesetAttr((1 << 2) | (1 << 3))
        ctypes.set_errno(0)
        ruleset_fd = libc.syscall(
            ctypes.c_long(444),
            ctypes.byref(ruleset_attr),
            ctypes.c_size_t(ctypes.sizeof(ruleset_attr)),
            ctypes.c_uint(0),
        )
        if ruleset_fd < 0:
            return False

        try:
            seen_roots = set()
            for root in roots:
                if type(root) is not str or not root:
                    return False
                if not os.path.exists(root):
                    continue
                parent_fd = os.open(root, os.O_PATH | os.O_CLOEXEC)
                try:
                    root_stat = os.fstat(parent_fd)
                    identity = (root_stat.st_dev, root_stat.st_ino)
                    if identity in seen_roots:
                        continue
                    path_attr = _PathBeneathAttr(
                        (1 << 2) | (1 << 3), parent_fd
                    )
                    ctypes.set_errno(0)
                    if libc.syscall(
                        ctypes.c_long(445),
                        ctypes.c_int(ruleset_fd),
                        ctypes.c_int(1),
                        ctypes.byref(path_attr),
                        ctypes.c_uint(0),
                    ) != 0:
                        return False
                    seen_roots.add(identity)
                finally:
                    os.close(parent_fd)

            ctypes.set_errno(0)
            return (
                libc.syscall(
                    ctypes.c_long(446),
                    ctypes.c_int(ruleset_fd),
                    ctypes.c_uint(0),
                )
                == 0
            )
        finally:
            os.close(ruleset_fd)
    except Exception:
        return False
"""
_PROCESS_SPAWN_PROBE_SCRIPT = (
    f"exec({_PROCESS_SPAWN_ISOLATION_SETUP_SCRIPT!r}, globals())\n"
    "if not _install_process_spawn_filter(): raise SystemExit(1)\n"
    "try:\n"
    "    child = os.fork()\n"
    "except PermissionError:\n"
    "    pass\n"
    "else:\n"
    "    if child == 0: os._exit(1)\n"
    "    os.waitpid(child, 0)\n"
    "    raise SystemExit(2)\n"
    "ran = []\n"
    "thread = threading.Thread(target=lambda: ran.append(True))\n"
    "thread.start()\n"
    "thread.join(timeout=3)\n"
    "if thread.is_alive() or ran != [True]: raise SystemExit(3)\n"
)
_FILESYSTEM_READ_PROBE_SCRIPT = (
    f"exec({_FILESYSTEM_READ_ISOLATION_SETUP_SCRIPT!r}, globals())\n"
    "if not _install_filesystem_read_isolation(sys.argv[1:]): raise SystemExit(1)\n"
    "try:\n"
    "    os.listdir('/')\n"
    "except PermissionError:\n"
    "    pass\n"
    "else:\n"
    "    raise SystemExit(2)\n"
    "try:\n"
    "    os.listdir('/usr')\n"
    "    with open(os.path.realpath(sys.executable), 'rb') as stream: stream.read(1)\n"
    "except Exception:\n"
    "    raise SystemExit(3)\n"
)


def _detect_filesystem_read_isolation() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        if (
            sys.byteorder != "little"
            or platform.machine().lower() not in {"x86_64", "aarch64"}
        ):
            return False
        resolved_executable = _resolved_spawn_target(sys.executable)
        if resolved_executable is None:
            return False
        roots = _filesystem_read_allowed_roots(resolved_executable)
        if "/" in roots:
            return False
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                _FILESYSTEM_READ_PROBE_SCRIPT,
                *roots,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).returncode == 0
    except Exception:
        return False


_FILESYSTEM_READ_ISOLATION_ENFORCEABLE = (
    _detect_filesystem_read_isolation()
)


def _detect_process_spawn_isolation() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        if (
            sys.byteorder != "little"
            or platform.machine().lower() not in {"x86_64", "aarch64"}
        ):
            return False
        return subprocess.run(
            [sys.executable, "-I", "-c", _PROCESS_SPAWN_PROBE_SCRIPT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).returncode == 0
    except Exception:
        return False


_PROCESS_SPAWN_ISOLATION_ENFORCEABLE = (
    _detect_process_spawn_isolation()
)
_NAMESPACE_MARKER_SCRIPT = f"""import os, signal, sys
fd = int(sys.argv[1])
readonly = sys.argv[2] == "1"
process_spawn = sys.argv[3] == "1"
filesystem_read = sys.argv[4] == "1"
lc_ctype = sys.argv[5]
filesystem_read_root_count = int(sys.argv[6])
filesystem_read_roots = sys.argv[7:7 + filesystem_read_root_count]
target_start = 7 + filesystem_read_root_count
if lc_ctype:
    os.environ["LC_CTYPE"] = lc_ctype[1:]
else:
    os.environ.pop("LC_CTYPE", None)
for name in ("SIGPIPE", "SIGXFSZ"):
    if hasattr(signal, name):
        signal.signal(getattr(signal, name), signal.SIG_DFL)
if readonly:
    exec({_FILESYSTEM_WRITE_ISOLATION_SETUP_SCRIPT!r}, globals())
    if not _make_mounts_readonly():
        os._exit(126)
if process_spawn:
    try:
        exec({_PROCESS_SPAWN_ISOLATION_SETUP_SCRIPT!r}, globals())
        installed = _install_process_spawn_filter()
    except BaseException:
        os._exit(126)
    if not installed:
        os._exit(126)
if filesystem_read:
    try:
        exec({_FILESYSTEM_READ_ISOLATION_SETUP_SCRIPT!r}, globals())
        installed = _install_filesystem_read_isolation(filesystem_read_roots)
    except BaseException:
        os._exit(126)
    if not installed:
        os._exit(126)
os.write(fd, b"x")
os.set_inheritable(fd, False)
try:
    os.execvp(sys.argv[target_start], sys.argv[target_start:])
except OSError:
    os.write(fd, b"e")
    os._exit(127)
"""


def memory_bound_enforceable() -> bool:
    """Whether any POSIX bound mechanism can cap a child's address space.

    `resource`+`preexec_fn`, `prlimit` or a POSIX `sh` each suffice; on
    a platform with none (e.g. Windows without a shell) a declared bound
    cannot be applied and `run` would reject it statically."""
    return resource is not None or _PRLIMIT is not None or _SH is not None


def memory_bound_spawn_thread_safe() -> bool:
    """Whether a memory-bound spawn avoids `preexec_fn`.

    `preexec_fn` forces the unsafe fork+exec spawn path, which can
    deadlock in a multithreaded process. With `prlimit` or a POSIX
    `sh` present the bound is applied by an exec wrapper instead,
    making bounded spawns thread-safe."""
    return _PRLIMIT is not None or _SH is not None


def network_isolation_enforceable() -> bool:
    """Whether this host can place a child in a network namespace."""
    return _UNSHARE is not None


def filesystem_write_isolation_enforceable() -> bool:
    """Whether this host can apply recursive read-only mount attributes."""
    return _FILESYSTEM_WRITE_ISOLATION_ENFORCEABLE


def process_spawn_isolation_enforceable() -> bool:
    """Whether this host can deny child creation while preserving threads."""
    return _PROCESS_SPAWN_ISOLATION_ENFORCEABLE


def filesystem_read_isolation_enforceable() -> bool:
    """Whether this host can enforce the Landlock filesystem read scope."""
    return _FILESYSTEM_READ_ISOLATION_ENFORCEABLE


def _spawn_target_resolvable(
    name: str, environment: dict[str, str] | None = None
) -> bool:
    """Whether execvp would locate `name` under the child PATH.

    `shutil.which` treats an empty PATH as no directories, while
    execvp searches the working directory for it — mirror that one
    case so resolution agrees with the spawn the runner performs."""
    return _resolved_spawn_target(name, environment) is not None


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

    `stdout`/`complete` and `stderr`/`stderr_complete` are collection
    observations, not success or Evidence claims; a dispatched run binds its
    snapshots through `AttemptDispatch.captured_output()` and
    `AttemptDispatch.captured_stderr()`, and hosts still own canonical
    publication. The record is terminal by construction.
    """

    record: AttemptRecord
    stdout: bytes = field(repr=False)
    complete: bool
    stderr: bytes = field(repr=False)
    stderr_complete: bool

    def __post_init__(self) -> None:
        if type(self.record) is not AttemptRecord or not self.record.is_terminal:
            raise ValueError("attempt run result requires a terminal record")
        if type(self.stdout) is not bytes or len(self.stdout) > MAX_STDOUT_BYTES:
            raise ValueError("attempt run result requires bounded bytes")
        if type(self.complete) is not bool:
            raise ValueError("invalid attempt run completeness declaration")
        if type(self.stderr) is not bytes or len(self.stderr) > MAX_STDOUT_BYTES:
            raise ValueError("attempt run result requires bounded bytes")
        if type(self.stderr_complete) is not bool:
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


def _spawn_failure_result(record: AttemptRecord) -> AttemptRunResult:
    return AttemptRunResult(
        record.record(AttemptEvent("started", 0)).record(
            AttemptEvent("failed", 0)
        ),
        b"",
        True,
        b"",
        True,
    )


def _read_namespace_marker(fd: int) -> bytes | None:
    marker = bytearray()
    eof = False
    try:
        while len(marker) < 8:
            chunk = os.read(fd, 8 - len(marker))
            if not chunk:
                eof = True
                break
            marker.extend(chunk)
    except OSError:
        return None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    return bytes(marker) if eof else None


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
        feed_bytes: bytes | None = None,
        environment: Mapping[str, str] | None = None,
        isolate_network: bool = False,
        isolate_filesystem_write: bool = False,
        isolate_process_spawn: bool = False,
        isolate_filesystem_read: bool = False,
    ) -> AttemptRunResult:
        """Spawn `argv`, observe one attempt and return a terminal record.

        `request` only binds the record (fingerprint, ordinal, declared
        timeout); the caller decides it is dispatchable via `check_dispatch`.
        On the declared deadline the child's whole process group is
        killed and `timed_out` is reported; a set `cancel_event`
        triggers `cancel_requested` then a terminate-then-kill
        sequence ending in `exited` or `cancelled`. Group delivery
        covers helpers the child spawned itself so a killed attempt
        leaves no orphaned subprocesses.
        `memory_bound_mb` applies a declared POSIX `RLIMIT_AS` ceiling to
        the child's whole address space — a best-effort bound, not a
        sandbox: it covers no CPU, I/O, network or permission policy, and
        exceeding it surfaces only as an ordinary observed outcome (`exited`
        with its code, `failed` or `timed_out`), never diagnosed as a
        resource violation.
        `environment=None` inherits the host environment; an explicit
        mapping is passed to the child as its complete environment.
        Environment scrubbing is not a sandbox and does not restrict
        filesystem, network or process access.
        `isolate_network=True` runs the child in a fresh network namespace
        with only a down loopback and the current uid mapped to the current
        user. This is not a sandbox and imposes no filesystem or process
        restriction.
        `isolate_filesystem_write=True` runs the child in a private user+mount
        namespace created by the launcher, with a recursively read-only mount
        tree where supported. This is not a sandbox; character devices and
        output pipes may remain writable.
        `isolate_process_spawn=True` uses seccomp to deny fork, vfork and
        non-thread clone operations, returns ENOSYS for clone3, and leaves
        exec and thread creation available where the host supports it.
        `isolate_filesystem_read=True` uses Landlock to limit file and
        directory reads to system roots and the target executable's
        directories where the host supports it; it does not restrict exec.
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
        if type(isolate_network) is not bool:
            raise ValueError("invalid attempt run network isolation")
        if isolate_network and _UNSHARE is None:
            raise ValueError(
                "attempt run network isolation requires a network namespace boundary"
            )
        if type(isolate_filesystem_write) is not bool:
            raise ValueError("invalid attempt run filesystem write isolation")
        if (
            isolate_filesystem_write
            and not filesystem_write_isolation_enforceable()
        ):
            raise ValueError(
                "attempt run filesystem write isolation requires a read-only mount namespace boundary"
            )
        if type(isolate_process_spawn) is not bool:
            raise ValueError("invalid attempt run process spawn isolation")
        if (
            isolate_process_spawn
            and not process_spawn_isolation_enforceable()
        ):
            raise ValueError(
                "attempt run process spawn isolation requires a seccomp filter boundary"
            )
        if type(isolate_filesystem_read) is not bool:
            raise ValueError("invalid attempt run filesystem read isolation")
        if (
            isolate_filesystem_read
            and not filesystem_read_isolation_enforceable()
        ):
            raise ValueError(
                "attempt run filesystem read isolation requires a Landlock boundary"
            )
        if memory_bound_mb is not None and (
            type(memory_bound_mb) is not int
            or not 1 <= memory_bound_mb <= MAX_MEMORY_BOUND_MB
        ):
            raise ValueError("invalid attempt run memory bound")
        if (
            memory_bound_mb is not None
            and resource is None
            and _PRLIMIT is None
            and _SH is None
        ):
            raise ValueError(
                "attempt run memory bound requires a POSIX resource boundary"
            )
        if feed_bytes is not None and (
            type(feed_bytes) is not bytes or len(feed_bytes) > MAX_FEED_BYTES
        ):
            raise ValueError("invalid attempt run feed")
        child_environment = None
        if environment is not None:
            if not isinstance(environment, Mapping):
                raise ValueError("invalid attempt run environment")
            child_environment = dict(environment)
            if any(
                type(key) is not str
                or not key
                or "=" in key
                or "\0" in key
                or type(value) is not str
                or "\0" in value
                for key, value in child_environment.items()
            ):
                raise ValueError("invalid attempt run environment")
        record = AttemptRecord(
            request.request_fingerprint,
            request.attempt_number,
            request.timeout_ms,
        )
        namespaced = (
            isolate_network
            or isolate_filesystem_write
            or isolate_process_spawn
            or isolate_filesystem_read
        )
        resolved_target = (
            _resolved_spawn_target(argv[0], child_environment)
            if namespaced
            else None
        )
        if namespaced and resolved_target is None:
            return _spawn_failure_result(record)
        if isolate_filesystem_read:
            if resolved_target is None:
                return _spawn_failure_result(record)
            filesystem_read_roots = _filesystem_read_allowed_roots(
                resolved_target
            )
        else:
            filesystem_read_roots = ()
        marker_read_fd = None
        marker_write_fd = None
        if namespaced:
            try:
                marker_read_fd, marker_write_fd = os.pipe()
            except OSError:
                return _spawn_failure_result(record)
        spawn_argv: list[str] = list(argv)
        preexec = None
        if memory_bound_mb is not None:
            if _PRLIMIT is not None:
                if _spawn_target_resolvable(spawn_argv[0], child_environment):
                    spawn_argv = [
                        _PRLIMIT,
                        f"--as={memory_bound_mb * 1_048_576}",
                        "--",
                        *spawn_argv,
                    ]
                # A target prlimit cannot exec makes it exit 127 —
                # which would masquerade as the target's own exit.
                # Leave argv unwrapped so a missing target still
                # reports a spawn failure.
            elif _SH is not None:
                if _spawn_target_resolvable(spawn_argv[0], child_environment):
                    # `ulimit -v` is RLIMIT_AS in KiB; `exec` carries
                    # the limit into the target. The `&&` keeps a
                    # rejected bound from running the target
                    # unbounded; a target the shell cannot exec
                    # exits 127 — the same masquerade prlimit would
                    # make — so the wrapper is applied only when the
                    # target resolves.
                    spawn_argv = [
                        _SH,
                        "-c",
                        f"ulimit -v {memory_bound_mb * 1024} && exec \"$@\"",
                        "mumei-attempt-bound",
                        *spawn_argv,
                    ]
            else:
                preexec = _memory_bound_preexec(memory_bound_mb)
        if namespaced:
            # The close-on-exec marker distinguishes target exits from setup failures.
            target_environment = (
                os.environ if child_environment is None else child_environment
            )
            target_lc_ctype = target_environment.get("LC_CTYPE")
            lc_ctype_argument = (
                "" if target_lc_ctype is None else f"={target_lc_ctype}"
            )
            namespace_argv = [
                sys.executable,
                "-I",
                "-c",
                _NAMESPACE_MARKER_SCRIPT,
                str(marker_write_fd),
                "1" if isolate_filesystem_write else "0",
                "1" if isolate_process_spawn else "0",
                "1" if isolate_filesystem_read else "0",
                lc_ctype_argument,
                str(len(filesystem_read_roots)),
                *filesystem_read_roots,
                *spawn_argv,
            ]
            if isolate_network:
                spawn_argv = [
                    _UNSHARE,
                    "--net",
                    "--map-current-user",
                    "--",
                    *namespace_argv,
                ]
            else:
                spawn_argv = namespace_argv
        popen_options = (
            {} if marker_write_fd is None else {"pass_fds": (marker_write_fd,)}
        )
        try:
            popen_environment = (
                {} if child_environment is None else {"env": child_environment}
            )
            process = subprocess.Popen(
                spawn_argv,
                stdin=subprocess.PIPE if feed_bytes is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=preexec,
                start_new_session=_PROCESS_GROUP,
                **popen_environment,
                **popen_options,
            )
        except (OSError, subprocess.SubprocessError):
            for fd in (marker_read_fd, marker_write_fd):
                if fd is not None:
                    os.close(fd)
            return _spawn_failure_result(record)
        if marker_write_fd is not None:
            os.close(marker_write_fd)
        feed_stop = threading.Event()
        feeder = None
        if feed_bytes is not None:
            feeder = threading.Thread(
                target=_feed_stdin,
                args=(process, feed_bytes, feed_stop),
                daemon=True,
            )
            feeder.start()
        started_at = time.monotonic()
        collector = _BoundedCollector(process.stdout)
        collector.start()
        stderr_collector = _BoundedCollector(process.stderr)
        stderr_collector.start()
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
                _signal_tree(process, terminate=False)
                process.wait()
                events.append(
                    AttemptEvent("timed_out", max(elapsed, request.timeout_ms))
                )
                break
            if (
                cancel_at is not None
                and elapsed - cancel_at >= CANCEL_GRACE_MS
            ):
                _signal_tree(process, terminate=False)
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
                _signal_tree(process, terminate=True)
            try:
                process.wait(timeout=POLL_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        collector.join(COLLECTOR_JOIN_SECONDS)
        stderr_collector.join(COLLECTOR_JOIN_SECONDS)
        if feeder is not None:
            feed_stop.set()
            feeder.join(COLLECTOR_JOIN_SECONDS)
        marker = (
            None
            if marker_read_fd is None
            else _read_namespace_marker(marker_read_fd)
        )
        if (
            namespaced
            and marker != b"x"
            and events[-1].kind == "exited"
        ):
            events[-1] = AttemptEvent("failed", events[-1].elapsed_ms)
        for event in events:
            record = record.record(event)
        return AttemptRunResult(
            record,
            collector.data,
            not collector.truncated,
            stderr_collector.data,
            not stderr_collector.truncated,
        )


@dataclass(frozen=True)
class AttemptDispatch:
    """One dispatch observed end-to-end; not a result selection or Evidence.

    `sequence` is the sequence reconciled with the run's terminal record;
    `run` is the observed run itself — terminal record, bounded stdout and
    the `complete` collection claim. Nothing here selects a canonical
    result or publishes lineage: the host still calls `select_result` —
    typically on the `captured_output()` snapshot, the canonical builder
    for this run's bytes — and publishes through `AttemptSequenceStore`.
    """

    sequence: AttemptSequence
    run: AttemptRunResult

    def __post_init__(self) -> None:
        if type(self.sequence) is not AttemptSequence:
            raise ValueError("attempt dispatch requires an attempt sequence")
        if type(self.run) is not AttemptRunResult:
            raise ValueError("attempt dispatch requires a run result")
        current = self.sequence.current
        if (
            current is None
            or current.state != self.run.record.state
            or current.events != self.run.record.events
            or current.attempt_number != self.run.record.attempt_number
            or current.timeout_ms != self.run.record.timeout_ms
            or self.sequence.request_fingerprint
            != self.run.record.request_fingerprint
        ):
            raise ValueError("attempt dispatch does not match the sequence")

    def captured_output(self) -> AttemptOutput:
        """Bind the run's captured stdout as an `AttemptOutput` snapshot.

        The snapshot is built from the reconciled sequence's current
        record — identical to the run's record after reconciliation — the
        bounded captured bytes and the run's `complete` collection claim,
        then checked against `check_output_binding`. A non-`exited`
        terminal run cannot produce a snapshot: `AttemptOutput` requires
        an exited record, so a failed, timed-out or cancelled dispatch
        fails statically rather than minting an output for a process
        that never produced one. The snapshot is still a host claim, not
        Evidence — selection and publication stay explicit host steps.
        """
        output = AttemptOutput(
            self.sequence.current,
            self.run.stdout,
            hashlib.sha256(self.run.stdout).hexdigest(),
            complete=self.run.complete,
        )
        self.sequence.check_output_binding(output)
        return output

    def captured_stderr(self) -> AttemptOutput:
        """Bind the run's captured stderr as an `AttemptOutput` snapshot.

        Same host-claim snapshot as `captured_output()` with `stream`
        declaring `stderr` and `complete` declaring the stderr collection
        stayed within the byte bound. A non-`exited` terminal run fails
        statically for the same reason — no output exists to snapshot.
        """
        output = AttemptOutput(
            self.sequence.current,
            self.run.stderr,
            hashlib.sha256(self.run.stderr).hexdigest(),
            stream="stderr",
            complete=self.run.stderr_complete,
        )
        self.sequence.check_output_binding(output)
        return output


def dispatch_attempt(
    sequence: AttemptSequence,
    argv: tuple[str, ...],
    *,
    runner: "AttemptRunner | None" = None,
    cancel_event: "threading.Event | None" = None,
    memory_bound_mb: int | None = None,
    feed_bytes: bytes | None = None,
    report_stamp: int | None = None,
    environment: Mapping[str, str] | None = None,
    isolate_network: bool = False,
    isolate_filesystem_write: bool = False,
    isolate_process_spawn: bool = False,
    isolate_filesystem_read: bool = False,
) -> AttemptDispatch:
    """Run the sequence's outstanding dispatch and reconcile the observation.

    `next_dispatch` must yield a request — nothing reserved, an attempt in
    flight or a terminal current record is a static error, not a run.
    `runner` defaults to a fresh `AttemptRunner`; the returned dispatch's
    sequence has the run's terminal record reconciled in. A stamped
    sequence requires `report_stamp` — it is checked before spawn so a
    missing, malformed or non-fresh stamp fails statically instead of
    losing an observed run. Reconciling does not select a result or
    publish — `captured_output()` binds the run's bytes as the declared
    `AttemptOutput` snapshot, and selection and publication stay explicit
    host steps.
    """
    if type(sequence) is not AttemptSequence:
        raise ValueError("attempt dispatch requires an attempt sequence")
    if runner is not None and type(runner) is not AttemptRunner:
        raise ValueError("attempt dispatch requires an attempt runner")
    if report_stamp is not None and (
        type(report_stamp) is not int or not 1 <= report_stamp <= MAX_COUNTER
    ):
        raise ValueError("invalid attempt report stamp")
    if sequence.report_stamp is not None and (
        report_stamp is None or report_stamp <= sequence.report_stamp
    ):
        raise ValueError("attempt dispatch requires a fresh report stamp")
    request = sequence.next_dispatch()
    if request is None:
        raise ValueError("attempt dispatch requires a ready attempt")
    run = (runner or AttemptRunner()).run(
        request,
        argv,
        cancel_event=cancel_event,
        memory_bound_mb=memory_bound_mb,
        feed_bytes=feed_bytes,
        environment=environment,
        isolate_network=isolate_network,
        isolate_filesystem_write=isolate_filesystem_write,
        isolate_process_spawn=isolate_process_spawn,
        isolate_filesystem_read=isolate_filesystem_read,
    )
    return AttemptDispatch(
        sequence.reconcile_report(run.record, report_stamp), run
    )


def publish_dispatch(
    store: AttemptSequenceStore,
    dispatch: AttemptDispatch,
    expected: "AttemptSequence | None" = None,
) -> AttemptSequence:
    """Publish one dispatch's terminal lineage through the canonical store.

    An `exited` run first binds its captured stdout as the sequence's
    selected result; failed, timed-out or cancelled runs publish the
    reconciled terminal lineage without a selection — a recorded failure
    is still canonical history. `expected` names the host's stored value:
    a mismatch or a non-extension is a static error and changes nothing,
    while an empty store publishes `updated` as the first canonical
    value. This composes existing boundaries only — it adds no
    arbitration across sequences, no durability and no Evidence.
    """
    if type(store) is not AttemptSequenceStore:
        raise ValueError("dispatch publication requires a sequence store")
    if type(dispatch) is not AttemptDispatch:
        raise ValueError("dispatch publication requires an attempt dispatch")
    if expected is not None and type(expected) is not AttemptSequence:
        raise ValueError("dispatch publication requires an expected sequence")
    updated = dispatch.sequence
    if dispatch.run.record.state == "exited":
        updated = updated.select_result(dispatch.captured_output())
    if store.current is None:
        return store.publish(updated)
    if expected is None:
        raise ValueError("dispatch publication requires an expected sequence")
    return store.compare_and_set(expected, updated)


def dispatch_next_attempt(
    sequence: AttemptSequence,
    argv: tuple[str, ...],
    *,
    runner: "AttemptRunner | None" = None,
    cancel_event: "threading.Event | None" = None,
    memory_bound_mb: int | None = None,
    report_stamp: int | None = None,
) -> AttemptDispatch:
    """Reserve the next attempt and run it through the same dispatch driver.

    `begin_attempt` supplies the reservation: a sequence closed by a
    selected result fails statically, and a running or cancelling current
    record fails because predecessors must be terminal. On a fresh
    sequence this reserves and runs attempt one; after a terminal record
    it is the declared retry. A stamped sequence requires a fresh
    `report_stamp`, forwarded to `dispatch_attempt` and checked before
    spawn. This is still not a retry policy: nothing here decides whether
    another attempt is worthwhile, picks `argv` again, bounds the attempt
    count or inspects the previous outcome — the host declares each next
    attempt by calling.
    """
    if type(sequence) is not AttemptSequence:
        raise ValueError("attempt dispatch requires an attempt sequence")
    return dispatch_attempt(
        sequence.begin_attempt(),
        argv,
        runner=runner,
        cancel_event=cancel_event,
        memory_bound_mb=memory_bound_mb,
        report_stamp=report_stamp,
    )


def dispatch_and_publish(
    store: AttemptSequenceStore,
    argv: tuple[str, ...],
    *,
    runner: "AttemptRunner | None" = None,
    cancel_event: "threading.Event | None" = None,
    memory_bound_mb: int | None = None,
    report_stamp: int | None = None,
) -> AttemptDispatch:
    """Reserve the next attempt, run it and publish its terminal lineage.

    `store.current` supplies the lineage — an empty store has nothing to
    reserve from. `begin_attempt` provides the reservation (a sequence
    closed by a selected result or holding a nonterminal current record
    fails statically), `dispatch_attempt` runs it under the declared
    timeout and reconciles the observation (a stamped lineage requires a
    fresh `report_stamp`, checked before spawn), and `publish_dispatch`
    publishes the terminal lineage through compare-and-set against the
    pre-run store value: a store another writer touched between the read
    and the publish fails statically instead of clobbering their value.

    The returned `AttemptDispatch` pairs the reconciled sequence with
    the observed run; the canonical lineage — including any
    `selected_result` the publish added — is the store's current value.
    A CAS rejection after a completed run surfaces the store's error:
    the process still ran, and recovering or retrying it is a host
    decision. No arbitration across writers, retry policy, durability or
    Evidence acceptance is added — the driver composes the declared
    boundaries and nothing else.
    """
    if type(store) is not AttemptSequenceStore:
        raise ValueError(
            "attempt dispatch-and-publish requires a sequence store"
        )
    current = store.current
    if current is None:
        raise ValueError("attempt dispatch-and-publish requires a lineage")
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        argv,
        runner=runner,
        cancel_event=cancel_event,
        memory_bound_mb=memory_bound_mb,
        report_stamp=report_stamp,
    )
    publish_dispatch(store, dispatch, expected=current)
    return dispatch
