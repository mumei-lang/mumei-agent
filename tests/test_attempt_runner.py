"""Real process-control boundary tests for the declared-request runner."""

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import FrozenInstanceError

import pytest

import agent.attempt_runner as attempt_runner
from agent.attempt_runner import (
    AttemptDispatch,
    AttemptRunner,
    AttemptRunResult,
    dispatch_and_publish,
    dispatch_attempt,
    dispatch_next_attempt,
    publish_dispatch,
)
from agent.verification_attempt import (
    MAX_STDOUT_BYTES,
    AttemptEvent,
    AttemptExecutionRequest,
    AttemptOutput,
    AttemptRecord,
    AttemptSequence,
    AttemptSequenceStore,
)

FINGERPRINT = "a" * 64
PY = sys.executable


def request(number=1, timeout_ms=10_000, fingerprint=FINGERPRINT):
    return AttemptExecutionRequest(fingerprint, number, timeout_ms)


def argv(code):
    return (PY, "-c", code)


def _fake_unshare(tmp_path, script):
    executable = tmp_path / "unshare"
    executable.write_text(f"#!/bin/sh\n{script}\n")
    executable.chmod(0o755)
    return str(executable)


def _fake_passthrough_unshare(tmp_path):
    script = (
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--\" ]; then shift; break; fi\n"
        "  shift\n"
        "done\n"
        "exec \"$@\""
    )
    return _fake_unshare(tmp_path, script)


@pytest.mark.parametrize(
    "bad_request",
    [None, "x", 1, AttemptRecord(FINGERPRINT, 1, 10)],
)
def test_run_rejects_non_execution_requests(bad_request):
    with pytest.raises(
        ValueError, match="^attempt run requires an execution request$"
    ):
        AttemptRunner().run(bad_request, argv("pass"))


@pytest.mark.parametrize(
    "bad_argv",
    [
        None,
        "echo hi",
        1,
        (),
        ("",),
        ("echo", ""),
        ("echo", 1),
        ["echo", "hi"],
        b"echo",
    ],
)
def test_run_rejects_invalid_argv(bad_argv):
    with pytest.raises(
        ValueError, match="^attempt run requires a nonempty immutable argv$"
    ):
        AttemptRunner().run(request(), bad_argv)


@pytest.mark.parametrize("bad_event", ["x", 1, object()])
def test_run_rejects_non_event_cancellation(bad_event):
    with pytest.raises(
        ValueError, match="^attempt run cancellation requires an event$"
    ):
        AttemptRunner().run(request(), argv("pass"), cancel_event=bad_event)


@pytest.mark.parametrize("code", [0, 1, 7])
def test_run_observes_real_exit_codes(code):
    result = AttemptRunner().run(
        request(), argv(f"import sys; sys.exit({code})")
    )
    assert type(result) is AttemptRunResult
    assert result.record.state == "exited"
    assert result.record.is_terminal
    assert result.record.request_fingerprint == FINGERPRINT
    assert result.record.attempt_number == 1
    assert result.record.timeout_ms == 10_000
    events = result.record.events
    assert [event.kind for event in events] == ["started", "exited"]
    assert events[0].elapsed_ms == 0
    assert events[1].exit_code == code
    assert 0 <= events[1].elapsed_ms < 10_000
    assert result.complete is True


def test_run_inherits_environment_by_default(monkeypatch):
    monkeypatch.setenv("MUMEI_TEST_FAKE_SENTINEL", "not-a-secret-sentinel")
    result = AttemptRunner().run(
        request(),
        argv(
            "import os,sys; "
            "sys.exit(0 if os.getenv('MUMEI_TEST_FAKE_SENTINEL') == "
            "'not-a-secret-sentinel' else 1)"
        ),
    )
    assert result.record.events[-1].exit_code == 0


def test_run_uses_explicit_environment_instead_of_inheriting(monkeypatch):
    monkeypatch.setenv("MUMEI_TEST_FAKE_SENTINEL", "not-a-secret-sentinel")
    result = AttemptRunner().run(
        request(),
        argv(
            "import os,sys; "
            "sys.exit(0 if 'MUMEI_TEST_FAKE_SENTINEL' not in os.environ else 1)"
        ),
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert result.record.events[-1].exit_code == 0


@pytest.mark.parametrize(
    "environment",
    [
        [],
        {"": "value"},
        {1: "value"},
        {"BAD=KEY": "value"},
        {"BAD\0KEY": "value"},
        {"KEY": 1},
        {"KEY": "bad\0value"},
    ],
)
def test_run_rejects_invalid_environment(environment):
    with pytest.raises(
        ValueError, match="^invalid attempt run environment$"
    ):
        AttemptRunner().run(request(), argv("pass"), environment=environment)


@pytest.mark.skipif(
    not attempt_runner.network_isolation_enforceable(),
    reason="network isolation requires an unprivileged network namespace",
)
def test_run_network_isolation_blocks_loopback_connection():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        code = (
            "import socket,sys\n"
            "try:\n"
            f" s=socket.create_connection(('127.0.0.1',{port}), timeout=3)\n"
            "except OSError:\n"
            " sys.exit(1)\n"
            "else:\n"
            " s.close(); sys.exit(0)\n"
        )
        direct = AttemptRunner().run(request(), argv(code))
        isolated = AttemptRunner().run(
            request(), argv(code), isolate_network=True
        )

    assert direct.record.state == "exited"
    assert direct.record.events[-1].exit_code == 0
    assert isolated.record.state == "exited"
    assert isolated.record.events[-1].exit_code != 0


def test_run_network_isolation_requires_boundary_before_spawn(monkeypatch):
    spawned = False

    def fail_if_spawned(*args, **kwargs):
        nonlocal spawned
        spawned = True
        pytest.fail("isolation validation must precede spawn")

    monkeypatch.setattr(attempt_runner, "_UNSHARE", None)
    monkeypatch.setattr(attempt_runner.subprocess, "Popen", fail_if_spawned)
    with pytest.raises(
        ValueError,
        match="^attempt run network isolation requires a network namespace boundary$",
    ):
        AttemptRunner().run(
            request(), argv("pass"), isolate_network=True
        )
    assert spawned is False


@pytest.mark.parametrize("isolate_network", [1, "true"])
def test_run_rejects_non_boolean_network_isolation(isolate_network):
    with pytest.raises(
        ValueError, match="^invalid attempt run network isolation$"
    ):
        AttemptRunner().run(
            request(), argv("pass"), isolate_network=isolate_network
        )


@pytest.mark.skipif(
    not attempt_runner.network_isolation_enforceable(),
    reason="network isolation requires an unprivileged network namespace",
)
def test_run_network_isolation_missing_target_reports_spawn_failure():
    target = ("/nonexistent-mumei-network-isolation-target",)
    direct = AttemptRunner().run(request(), target)
    isolated = AttemptRunner().run(
        request(), target, isolate_network=True
    )

    assert direct.record.state == "failed"
    assert isolated.record.state == direct.record.state
    assert [event.kind for event in isolated.record.events] == [
        event.kind for event in direct.record.events
    ]
    assert isolated.record.events[-1].exit_code is None


@pytest.mark.skipif(os.name != "posix", reason="fake unshare requires POSIX")
def test_run_network_isolation_missing_target_never_spawns(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        attempt_runner,
        "_UNSHARE",
        _fake_unshare(tmp_path, "exit 0"),
    )

    def fail_if_spawned(*args, **kwargs):
        raise AssertionError("an unresolved isolated target must not spawn")

    monkeypatch.setattr(attempt_runner.subprocess, "Popen", fail_if_spawned)
    result = AttemptRunner().run(
        request(),
        (str(tmp_path / "missing-target"),),
        isolate_network=True,
    )

    assert result.record.state == "failed"
    assert [event.kind for event in result.record.events] == [
        "started",
        "failed",
    ]
    assert [event.elapsed_ms for event in result.record.events] == [0, 0]
    assert result.record.events[-1].exit_code is None
    assert result.stdout == b""
    assert result.stderr == b""


@pytest.mark.parametrize("unshare_status", [0, 1])
@pytest.mark.skipif(os.name != "posix", reason="fake unshare requires POSIX")
def test_run_network_isolation_rejects_unshare_failure(
    tmp_path, monkeypatch, unshare_status
):
    monkeypatch.setattr(
        attempt_runner,
        "_UNSHARE",
        _fake_unshare(tmp_path, f"exit {unshare_status}"),
    )
    result = AttemptRunner().run(
        request(),
        argv("import sys; sys.exit(0)"),
        isolate_network=True,
    )

    assert result.record.state == "failed"
    assert [event.kind for event in result.record.events] == [
        "started",
        "failed",
    ]
    assert result.record.events[-1].exit_code is None


@pytest.mark.parametrize("exit_code", [0, 3])
@pytest.mark.skipif(os.name != "posix", reason="fake unshare requires POSIX")
def test_run_network_isolation_marker_preserves_target_exit(
    tmp_path, monkeypatch, exit_code
):
    monkeypatch.setattr(
        attempt_runner,
        "_UNSHARE",
        _fake_passthrough_unshare(tmp_path),
    )
    result = AttemptRunner().run(
        request(),
        argv(f"import sys; sys.exit({exit_code})"),
        isolate_network=True,
    )

    assert result.record.state == "exited"
    assert [event.kind for event in result.record.events] == [
        "started",
        "exited",
    ]
    assert result.record.events[-1].exit_code == exit_code


@pytest.mark.parametrize(
    ("locale", "expected"),
    [(None, b"unset"), ("POSIX", b"POSIX")],
    ids=["absent-lc-ctype", "explicit-lc-ctype"],
)
@pytest.mark.skipif(os.name != "posix", reason="fake unshare requires POSIX")
def test_run_network_isolation_restores_target_lc_ctype(
    tmp_path, monkeypatch, locale, expected
):
    monkeypatch.setattr(
        attempt_runner,
        "_UNSHARE",
        _fake_passthrough_unshare(tmp_path),
    )
    environment = {"PATH": os.environ["PATH"]}
    if locale is not None:
        environment["LC_CTYPE"] = locale
    result = AttemptRunner().run(
        request(),
        ("/bin/sh", "-c", 'printf %s "${LC_CTYPE-unset}"'),
        environment=environment,
        isolate_network=True,
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout == expected


@pytest.mark.skipif(
    not sys.platform.startswith("linux")
    or not os.path.exists("/proc/self/status"),
    reason="requires Linux /proc/self/status",
)
def test_run_network_isolation_restores_default_ignored_signals(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        attempt_runner,
        "_UNSHARE",
        _fake_passthrough_unshare(tmp_path),
    )
    result = AttemptRunner().run(
        request(),
        ("/bin/sh", "-c", "grep SigIgn /proc/self/status"),
        isolate_network=True,
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    sigign_line = next(
        line for line in result.stdout.splitlines() if line.startswith(b"SigIgn:")
    )
    ignored_signals = int(sigign_line.split()[1], 16)
    for name in ("SIGPIPE", "SIGXFSZ"):
        if hasattr(signal, name):
            signal_bit = 1 << (getattr(signal, name) - 1)
            assert ignored_signals & signal_bit == 0


@pytest.mark.skipif(
    not attempt_runner.network_isolation_enforceable()
    or not attempt_runner.memory_bound_enforceable(),
    reason="requires network namespace and memory-bound enforcement",
)
def test_run_network_isolation_combines_with_memory_bound():
    result = AttemptRunner().run(
        request(),
        argv(
            "import resource; "
            "print(resource.getrlimit(resource.RLIMIT_AS)[0])"
        ),
        memory_bound_mb=256,
        isolate_network=True,
    )
    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert int(result.stdout.strip()) == 256 * 1_048_576


@pytest.mark.skipif(
    not attempt_runner.memory_bound_enforceable(),
    reason="memory bounds require a POSIX resource boundary",
)
def test_run_memory_bound_spawns_with_scrubbed_environment():
    result = AttemptRunner().run(
        request(),
        argv("print('ok')"),
        memory_bound_mb=256,
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout == b"ok\n"


@pytest.mark.skipif(
    not sys.platform.startswith("linux")
    or not attempt_runner.memory_bound_spawn_thread_safe(),
    reason="target PATH bound test requires Linux with prlimit or POSIX sh",
)
def test_run_memory_bound_resolves_target_from_child_path(tmp_path):
    memory_bound_mb = 256
    script_name = "memory-bound-probe"
    script = tmp_path / script_name
    script.write_text(
        f"#!{sys.executable}\n"
        "import resource\n"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0])\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    assert str(tmp_path) not in os.environ.get("PATH", "").split(os.pathsep)

    result = AttemptRunner().run(
        request(),
        (script_name,),
        memory_bound_mb=memory_bound_mb,
        environment={"PATH": str(tmp_path)},
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout == f"{memory_bound_mb * 1_048_576}\n".encode()


def test_run_captures_bounded_stdout_without_interpreting_it():
    body = b"FAKE_PRIVATE_RUNNER_STDOUT"
    result = AttemptRunner().run(
        request(), argv(f"import sys; sys.stdout.buffer.write({body!r})")
    )
    assert result.stdout == body
    assert result.complete is True
    assert result.record.state == "exited"
    assert "FAKE_PRIVATE_RUNNER_STDOUT" not in repr(result)


def test_run_captures_bounded_stderr_without_interpreting_it():
    body = b"FAKE_PRIVATE_RUNNER_STDERR"
    result = AttemptRunner().run(
        request(), argv(f"import sys; sys.stderr.buffer.write({body!r})")
    )
    assert result.stderr == body
    assert result.stderr_complete is True
    assert result.stdout == b""
    assert result.record.state == "exited"
    assert "FAKE_PRIVATE_RUNNER_STDERR" not in repr(result)


def test_run_marks_oversize_stderr_incomplete_but_keeps_stdout_whole():
    code = (
        "import sys\n"
        "sys.stdout.buffer.write(b'ok')\n"
        "sys.stderr.buffer.write(b'e' * 200000)\n"
    )
    result = AttemptRunner().run(request(), argv(code))
    assert result.record.state == "exited"
    assert result.stdout == b"ok"
    assert result.complete is True
    assert len(result.stderr) == MAX_STDOUT_BYTES
    assert result.stderr_complete is False


def test_run_binds_records_and_outputs_to_the_request():
    req = request(number=3, fingerprint="b" * 64)
    result = AttemptRunner().run(req, argv("print('ok')"))
    assert result.record.request_fingerprint == "b" * 64
    assert result.record.attempt_number == 3
    output = AttemptOutput(
        result.record,
        result.stdout,
        hashlib.sha256(result.stdout).hexdigest(),
        "stdout",
        result.complete,
    )
    assert output.attempt == result.record


def test_run_timeout_kills_runaways_and_reports_timed_out():
    started = time.monotonic()
    result = AttemptRunner().run(
        request(timeout_ms=200), argv("import time; time.sleep(60)")
    )
    wall = time.monotonic() - started
    assert result.record.state == "timed_out"
    assert result.record.events[-1].elapsed_ms >= 200
    assert wall < 30


@pytest.mark.skipif(
    not (os.name == "posix" and hasattr(os, "killpg")),
    reason="process-group kill is POSIX-only",
)
def test_run_timeout_kills_spawned_helpers_too():
    child = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    result = AttemptRunner().run(
        request(timeout_ms=300), argv(child)
    )
    assert result.record.state == "timed_out"
    helper_pid = int(result.stdout.strip())
    for _ in range(50):
        try:
            os.kill(helper_pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    pytest.fail("spawned helper survived the attempt timeout")


def test_run_exit_past_deadline_reports_timed_out_not_exited():
    result = AttemptRunner().run(
        request(timeout_ms=300),
        argv(
            "import threading,time;time.sleep(0.5);"
        ),
    )
    assert result.record.state == "timed_out"
    assert result.record.events[-1].elapsed_ms >= 300


def test_run_huge_output_is_truncated_with_complete_false():
    size = MAX_STDOUT_BYTES + 10_000
    result = AttemptRunner().run(
        request(timeout_ms=30_000),
        argv(f"import sys; sys.stdout.buffer.write(b'x'*{size})"),
    )
    assert result.complete is False
    assert len(result.stdout) == MAX_STDOUT_BYTES
    assert result.record.state == "exited"


def test_run_spawn_failure_reports_failed_record():
    result = AttemptRunner().run(
        request(), ("/nonexistent-devin-binary-9f2e",)
    )
    assert result.record.state == "failed"
    assert [e.kind for e in result.record.events] == ["started", "failed"]
    assert result.stdout == b""
    assert result.complete is True


def test_run_cancel_event_terminates_and_reports_cancelled_or_exited():
    cancel = threading.Event()
    cancel.set()
    result = AttemptRunner().run(
        request(timeout_ms=30_000),
        argv("import time; time.sleep(60)"),
        cancel_event=cancel,
    )
    assert result.record.state in {"cancelled", "exited"}
    kinds = [e.kind for e in result.record.events]
    assert kinds[0] == "started"
    assert "cancel_requested" in kinds
    assert kinds[-1] == result.record.state


def test_run_cancel_then_exit_during_grace_reports_exited():
    cancel = threading.Event()
    timer = threading.Timer(0.1, cancel.set)
    timer.start()
    result = AttemptRunner().run(
        request(timeout_ms=30_000),
        argv(
            "import signal,time\n"
            "signal.signal(signal.SIGTERM, lambda *a: __import__('sys').exit(0))\n"
            "time.sleep(60)"
        ),
        cancel_event=cancel,
    )
    kinds = [e.kind for e in result.record.events]
    assert kinds == ["started", "cancel_requested", "exited"]
    assert result.record.events[-1].exit_code == 0


def test_run_unset_cancel_event_leaves_execution_alone():
    cancel = threading.Event()
    result = AttemptRunner().run(
        request(), argv("pass"), cancel_event=cancel
    )
    assert result.record.state == "exited"
    assert [e.kind for e in result.record.events] == ["started", "exited"]


def test_run_result_rejects_invalid_metadata():
    exited = AttemptRecord(
        FINGERPRINT, 1, 10, (AttemptEvent("started", 0), AttemptEvent("exited", 1, 0))
    )
    running = AttemptRecord(FINGERPRINT, 1, 10, (AttemptEvent("started", 0),))
    for record, stdout, complete, stderr, stderr_complete in (
        (running, b"", True, b"", True),
        ("x", b"", True, b"", True),
        (exited, b"x" * (MAX_STDOUT_BYTES + 1), True, b"", True),
        (exited, "x", True, b"", True),
        (exited, b"", 0, b"", True),
        (exited, b"", "true", b"", True),
        (exited, b"", True, b"x" * (MAX_STDOUT_BYTES + 1), True),
        (exited, b"", True, "x", True),
        (exited, b"", True, b"", 0),
        (exited, b"", True, b"", "true"),
    ):
        with pytest.raises(ValueError):
            AttemptRunResult(
                record, stdout, complete, stderr, stderr_complete
            )
    result = AttemptRunResult(exited, b"", True, b"", True)
    with pytest.raises(FrozenInstanceError):
        result.complete = False


def test_feed_bytes_reach_child_stdin():
    result = AttemptRunner().run(
        request(),
        argv("import sys; print(len(sys.stdin.buffer.read()))"),
        feed_bytes=b"x" * 4096,
    )
    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout.strip() == b"4096"


def test_feed_rejects_non_bytes_and_oversize():
    runner = AttemptRunner()
    with pytest.raises(ValueError):
        runner.run(request(), argv("pass"), feed_bytes="nope")
    with pytest.raises(ValueError):
        runner.run(
            request(),
            argv("pass"),
            feed_bytes=b"x" * (attempt_runner.MAX_FEED_BYTES + 1),
        )


def test_feed_stdin_stop_event_bounds_a_full_pipe():
    """A descendant holding stdin's read end open without reading can
    leave the write side blocked on a full pipe; the stop event must
    still bound the feeder."""
    import fcntl
    import types

    read_fd, write_fd = os.pipe()
    if hasattr(fcntl, "F_SETPIPE_SZ"):
        fcntl.fcntl(write_fd, fcntl.F_SETPIPE_SZ, 4096)
    os.write(write_fd, b"z" * 4096)
    proc = types.SimpleNamespace(stdin=os.fdopen(write_fd, "wb"))
    stop = threading.Event()
    feeder = threading.Thread(
        target=attempt_runner._feed_stdin,
        args=(proc, b"y" * attempt_runner.MAX_FEED_BYTES, stop),
        daemon=True,
    )
    feeder.start()
    time.sleep(0.2)
    assert feeder.is_alive()
    stop.set()
    feeder.join(5)
    assert not feeder.is_alive()
    os.close(read_fd)


def test_feed_stdin_writes_through_a_high_numbered_fd():
    """select() refuses fds >= FD_SETSIZE; a host holding that many
    descriptors must still deliver the feed (poll has no fd bound)."""
    import types

    try:
        import resource
    except ImportError:
        resource = None
    if resource is not None:
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft != resource.RLIM_INFINITY and soft < 1040:
            pytest.skip("host fd limit keeps pipe descriptors below 1024")

    spares = []
    try:
        try:
            while len(spares) < 1030:
                spares.append(os.open(os.devnull, os.O_RDONLY))
        except OSError:
            pytest.skip("host fd limit keeps pipe descriptors below 1024")
        read_fd, write_fd = os.pipe()
        spares.append(read_fd)
        if write_fd < 1024:
            pytest.skip("host fd ceiling keeps pipe descriptors below 1024")
        proc = types.SimpleNamespace(stdin=os.fdopen(write_fd, "wb"))
        stop = threading.Event()
        payload = b"x" * 8192
        feeder = threading.Thread(
            target=attempt_runner._feed_stdin,
            args=(proc, payload, stop),
            daemon=True,
        )
        feeder.start()
        got = b""
        while len(got) < len(payload):
            chunk = os.read(read_fd, len(payload) - len(got))
            if not chunk:
                break
            got += chunk
        feeder.join(5)
        assert not feeder.is_alive()
        assert got == payload
    finally:
        for fd in spares:
            os.close(fd)


def test_run_results_feed_sequence_reconciliation():
    runner = AttemptRunner()
    req = request()
    first = runner.run(req, argv("import sys; sys.exit(9)"))
    seq_record = AttemptRecord(FINGERPRINT, 1, 10_000)
    reconciled = seq_record.reconcile(first.record)
    assert reconciled.state == "exited"
    assert reconciled.events[-1].exit_code == 9
    assert reconciled.reconcile(first.record) is reconciled


def test_run_elapsed_counters_are_monotonic():
    result = AttemptRunner().run(
        request(timeout_ms=30_000),
        argv("import time; time.sleep(0.05)"),
    )
    elapsed = [event.elapsed_ms for event in result.record.events]
    assert elapsed == sorted(elapsed)


def test_runner_keeps_no_state_between_calls():
    runner = AttemptRunner()
    first = runner.run(request(1), argv("print('a')"))
    second = runner.run(request(2), argv("print('b')"))
    assert first.record.attempt_number == 1
    assert second.record.attempt_number == 2
    assert first.stdout != second.stdout


def test_run_result_manifest_is_body_free():
    result = AttemptRunner().run(
        request(), argv("print('FAKE_PRIVATE_RESULT_BODY')")
    )
    data = {
        "record": result.record.to_dict(),
        "complete": result.complete,
    }
    encoded = json.dumps(data)
    assert "FAKE_PRIVATE_RESULT_BODY" not in encoded
    assert "stdout" not in encoded


def test_normalized_maps_a_real_exit_to_detached_metadata():
    body = b"normalized-observation"
    result = AttemptRunner().run(
        request(number=2, timeout_ms=30_000),
        argv(f"import sys; sys.stdout.buffer.write({body!r}); sys.exit(3)"),
    )
    normalized = result.normalized()
    assert type(normalized).__name__ == "AttemptNormalizedResult"
    assert normalized.request_fingerprint == FINGERPRINT
    assert normalized.attempt_number == 2
    assert normalized.timeout_ms == 30_000
    assert normalized.outcome == "exited"
    assert normalized.exit_code == 3
    assert normalized.elapsed_ms == result.record.events[-1].elapsed_ms
    assert normalized.stdout_size == len(body)
    assert normalized.stdout_sha256 == hashlib.sha256(body).hexdigest()
    assert normalized.complete is True
    manifest = normalized.to_dict()
    assert manifest["schema_version"] == "mumei.verifier-run-result/v1"
    assert "normalized-observation" not in json.dumps(manifest)


@pytest.mark.parametrize(
    "code,expected",
    [("import sys; sys.exit(0)", "exited"), ("import sys; sys.exit(42)", "exited")],
)
def test_normalized_outcome_matches_terminal_state(code, expected):
    result = AttemptRunner().run(request(), argv(code))
    assert result.normalized().outcome == expected


def test_normalized_timeout_and_spawn_failure_carry_no_exit_code():
    runner = AttemptRunner()
    timed_out = runner.run(
        request(timeout_ms=150), argv("import time; time.sleep(60)")
    ).normalized()
    assert timed_out.outcome == "timed_out"
    assert timed_out.exit_code is None
    assert "exit_code" not in timed_out.to_dict()
    failed = runner.run(request(), ("/nonexistent-devin-binary-9f2e",)).normalized()
    assert failed.outcome == "failed"
    assert failed.exit_code is None
    assert failed.stdout_size == 0


def test_normalized_marks_truncated_collection():
    size = MAX_STDOUT_BYTES + 10_000
    result = AttemptRunner().run(
        request(timeout_ms=30_000),
        argv(f"import sys; sys.stdout.buffer.write(b'x'*{size})"),
    )
    normalized = result.normalized()
    assert normalized.complete is False
    assert normalized.stdout_size == MAX_STDOUT_BYTES
    assert normalized.stdout_sha256 == hashlib.sha256(result.stdout).hexdigest()
    assert normalized.to_dict()["stdout"]["complete"] is False


# ---- declared memory bound (POSIX RLIMIT_AS) ----


@pytest.mark.parametrize(
    "bad_bound",
    [True, 0, -1, 1_048_577, "64", 64.0, b"64", (64,)],
)
def test_run_rejects_invalid_memory_bounds(bad_bound):
    with pytest.raises(ValueError, match="^invalid attempt run memory bound$"):
        AttemptRunner().run(request(), argv("pass"), memory_bound_mb=bad_bound)


@pytest.mark.parametrize("bound", [256, 512, 1_048_576])
def test_run_accepts_declared_memory_bounds(bound):
    result = AttemptRunner().run(
        request(), argv("pass"), memory_bound_mb=bound
    )
    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0


def test_run_reports_allocation_past_declared_bound_as_exit():
    code = "x = b' ' * (256 * 1024 * 1024); print(len(x))"
    result = AttemptRunner().run(
        request(timeout_ms=30_000), argv(code), memory_bound_mb=96
    )
    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code != 0


def test_run_bound_does_not_diagnose_or_extend_outcomes():
    code = "x = b' ' * (256 * 1024 * 1024); print(len(x))"
    result = AttemptRunner().run(
        request(timeout_ms=30_000), argv(code), memory_bound_mb=96
    )
    assert result.normalized().outcome == "exited"
    assert result.complete is True


def test_run_under_bound_can_still_allocate():
    code = "x = b' ' * (32 * 1024 * 1024); print(len(x))"
    result = AttemptRunner().run(
        request(), argv(code), memory_bound_mb=256
    )
    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout.strip() == str(32 * 1024 * 1024).encode()


def test_run_memory_bound_leaves_parent_unbound():
    runner = AttemptRunner()
    runner.run(request(), argv("pass"), memory_bound_mb=96)
    _ = b" " * (256 * 1024 * 1024)  # parent is not constrained


def test_run_memory_bound_still_times_out():
    result = AttemptRunner().run(
        request(timeout_ms=150),
        argv("import time; time.sleep(60)"),
        memory_bound_mb=256,
    )
    assert result.record.state == "timed_out"


def test_run_memory_bound_still_honors_cancellation():
    cancel = threading.Event()
    runner = AttemptRunner()
    thread = threading.Thread(
        target=lambda: runner.run(
            request(timeout_ms=30_000),
            argv("import time; time.sleep(60)"),
            cancel,
            256,
        ),
        daemon=True,
    )
    thread.start()
    time.sleep(0.2)
    cancel.set()
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_run_memory_bound_failure_reports_failed(monkeypatch):
    import agent.attempt_runner as runner_mod

    def boom(limit):
        raise OSError("rlimit refused")

    # Force the preexec fallback so the refused rlimit surfaces
    # as a spawn failure rather than a wrapped exit.
    monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
    monkeypatch.setattr(runner_mod, "_SH", None)
    monkeypatch.setattr(runner_mod.resource, "setrlimit", boom)
    result = AttemptRunner().run(request(), argv("pass"), memory_bound_mb=64)
    assert result.record.state == "failed"
    assert result.stdout == b""


def test_run_memory_bound_prefers_prlimit_wrapper(monkeypatch):
    import agent.attempt_runner as runner_mod

    spawned = {}

    class FakePopen:
        def __init__(self, args, **kw):
            spawned["args"] = list(args)
            spawned["preexec_fn"] = kw.get("preexec_fn")
            raise OSError("stop before spawn")

    monkeypatch.setattr(runner_mod, "_PRLIMIT", "/usr/bin/prlimit")
    monkeypatch.setattr(runner_mod.subprocess, "Popen", FakePopen)
    result = AttemptRunner().run(
        request(), argv("pass"), memory_bound_mb=64
    )
    assert result.record.state == "failed"
    assert spawned["args"][:3] == [
        "/usr/bin/prlimit",
        "--as=67108864",
        "--",
    ]
    assert spawned["args"][3:] == list(argv("pass"))
    assert spawned["preexec_fn"] is None


def test_run_memory_bound_falls_back_to_sh_wrapper(monkeypatch):
    import agent.attempt_runner as runner_mod

    spawned = {}

    class FakePopen:
        def __init__(self, args, **kw):
            spawned["args"] = list(args)
            spawned["preexec_fn"] = kw.get("preexec_fn")
            raise OSError("stop before spawn")

    monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
    monkeypatch.setattr(runner_mod, "_SH", "/bin/sh")
    monkeypatch.setattr(runner_mod.subprocess, "Popen", FakePopen)
    AttemptRunner().run(request(), argv("pass"), memory_bound_mb=64)
    assert spawned["args"] == [
        "/bin/sh",
        "-c",
        "ulimit -v 65536 && exec \"$@\"",
        "mumei-attempt-bound",
        *argv("pass"),
    ]
    assert spawned["preexec_fn"] is None


def test_run_memory_bound_sh_wrapper_still_enforces_the_bound(
    monkeypatch,
):
    import agent.attempt_runner as runner_mod

    monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
    code = "x = b' ' * (256 * 1024 * 1024); print(len(x))"
    result = AttemptRunner().run(
        request(timeout_ms=30_000), argv(code), memory_bound_mb=96
    )
    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code != 0


def test_run_memory_bound_falls_back_to_preexec(monkeypatch):
    import agent.attempt_runner as runner_mod

    spawned = {}

    class FakePopen:
        def __init__(self, args, **kw):
            spawned["args"] = list(args)
            spawned["preexec_fn"] = kw.get("preexec_fn")
            raise OSError("stop before spawn")

    monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
    monkeypatch.setattr(runner_mod, "_SH", None)
    monkeypatch.setattr(runner_mod.subprocess, "Popen", FakePopen)
    AttemptRunner().run(request(), argv("pass"), memory_bound_mb=64)
    assert spawned["args"] == list(argv("pass"))
    assert spawned["preexec_fn"] is not None


@pytest.mark.parametrize("wrapper", ["prlimit", "sh", "preexec"])
def test_run_memory_bound_missing_target_reports_failed(
    monkeypatch, wrapper
):
    # Under a wrapper, a target it cannot exec would exit 127 —
    # masquerading as the target's own exit. The runner leaves the
    # argv unwrapped instead so the plain spawn reports a real
    # failure on every spawn path.
    import agent.attempt_runner as runner_mod

    if wrapper == "prlimit":
        monkeypatch.setattr(runner_mod, "_PRLIMIT", "/usr/bin/prlimit")
        monkeypatch.setattr(runner_mod, "_SH", "/bin/sh")
    elif wrapper == "sh":
        monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
        monkeypatch.setattr(runner_mod, "_SH", "/bin/sh")
    else:
        monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
        monkeypatch.setattr(runner_mod, "_SH", None)
    result = AttemptRunner().run(
        request(), ("/nonexistent-mumei-probe-binary",), memory_bound_mb=64
    )
    assert result.record.state == "failed"


def test_run_memory_bound_wraps_target_found_via_empty_path(
    tmp_path, monkeypatch
):
    # `shutil.which` treats PATH="" as no directories while execvp
    # searches the working directory — the wrapper must still apply
    # the bound for a command only the working directory provides.
    import agent.attempt_runner as runner_mod

    probe = tmp_path / "probe"
    probe.write_text("#!/bin/sh\nexit 0\n")
    probe.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    spawned = {}

    class FakePopen:
        def __init__(self, args, **kw):
            spawned["args"] = list(args)
            raise OSError("stop before spawn")

    monkeypatch.setattr(runner_mod, "_PRLIMIT", "/usr/bin/prlimit")
    monkeypatch.setattr(runner_mod.subprocess, "Popen", FakePopen)
    AttemptRunner().run(request(), ("probe",), memory_bound_mb=64)
    assert spawned["args"] == [
        "/usr/bin/prlimit",
        "--as=67108864",
        "--",
        "probe",
    ]


def test_memory_bound_spawn_thread_safe(monkeypatch):
    import agent.attempt_runner as runner_mod

    monkeypatch.setattr(runner_mod, "_PRLIMIT", "/usr/bin/prlimit")
    monkeypatch.setattr(runner_mod, "_SH", None)
    assert runner_mod.memory_bound_spawn_thread_safe()
    monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
    monkeypatch.setattr(runner_mod, "_SH", "/bin/sh")
    assert runner_mod.memory_bound_spawn_thread_safe()
    monkeypatch.setattr(runner_mod, "_SH", None)
    assert not runner_mod.memory_bound_spawn_thread_safe()


def ready_sequence(timeout_ms=10_000):
    return AttemptSequence(
        FINGERPRINT, timeout_ms, (AttemptRecord(FINGERPRINT, 1, timeout_ms),)
    )


def test_dispatch_attempt_runs_and_reconciles_the_ready_attempt():
    sequence = ready_sequence()
    before = sequence.to_dict()
    dispatch = dispatch_attempt(sequence, argv("import sys; sys.exit(9)"))
    assert dispatch.run.record.state == "exited"
    assert dispatch.run.record.events[-1].exit_code == 9
    current = dispatch.sequence.current
    assert current.state == "exited"
    assert current.events == dispatch.run.record.events
    assert current.attempt_number == 1
    assert sequence.to_dict() == before


def test_dispatch_attempt_binds_the_request_fingerprint_and_ordinal():
    sequence = ready_sequence()
    dispatch = dispatch_attempt(sequence, argv("pass"))
    assert dispatch.run.record.request_fingerprint == FINGERPRINT
    assert dispatch.sequence.request_fingerprint == FINGERPRINT
    assert dispatch.sequence.current is not sequence.current


@pytest.mark.parametrize(
    "sequence",
    [
        AttemptSequence(FINGERPRINT, 10_000),
        AttemptSequence(
            FINGERPRINT,
            10_000,
            (
                AttemptRecord(
                    FINGERPRINT,
                    1,
                    10_000,
                    (AttemptEvent("started", 0),),
                ),
            ),
        ),
        AttemptSequence(
            FINGERPRINT,
            10_000,
            (
                AttemptRecord(
                    FINGERPRINT,
                    1,
                    10_000,
                    (
                        AttemptEvent("started", 0),
                        AttemptEvent("exited", 1, 0),
                    ),
                ),
            ),
        ),
    ],
    ids=["empty", "in-flight", "terminal"],
)
def test_dispatch_attempt_rejects_nothing_dispatchable(sequence):
    with pytest.raises(
        ValueError, match="^attempt dispatch requires a ready attempt$"
    ):
        dispatch_attempt(sequence, argv("pass"))


@pytest.mark.parametrize("bad", [None, "x", 1, AttemptRecord(FINGERPRINT, 1, 10)])
def test_dispatch_attempt_rejects_foreign_sequences(bad):
    with pytest.raises(
        ValueError, match="^attempt dispatch requires an attempt sequence$"
    ):
        dispatch_attempt(bad, argv("pass"))


@pytest.mark.parametrize(
    "bad_runner", [None.__class__, "x", 1, object(), AttemptRunner]
)
def test_dispatch_attempt_rejects_foreign_runners(bad_runner):
    with pytest.raises(
        ValueError, match="^attempt dispatch requires an attempt runner$"
    ):
        dispatch_attempt(ready_sequence(), argv("pass"), runner=bad_runner)


def test_dispatch_attempt_propagates_run_validation():
    with pytest.raises(
        ValueError, match="^attempt run requires a nonempty immutable argv$"
    ):
        dispatch_attempt(ready_sequence(), ("echo", 1))


def test_dispatch_attempt_reports_spawn_failure_as_failed():
    dispatch = dispatch_attempt(
        ready_sequence(), ("/FAKE_PRIVATE_missing_executable_9f31",)
    )
    assert dispatch.run.record.state == "failed"
    assert dispatch.sequence.current.state == "failed"
    assert dispatch.run.stdout == b""
    assert dispatch.run.stderr == b""


def test_dispatch_attempt_captured_stderr_binds_the_stream_snapshot():
    body = b"FAKE_PRIVATE_DISPATCH_STDERR"
    sequence = ready_sequence()
    dispatch = dispatch_attempt(
        sequence,
        argv(f"import sys; sys.stderr.buffer.write({body!r})"),
    )
    output = dispatch.captured_stderr()
    assert output.stream == "stderr"
    assert output.stdout == body
    assert output.complete is True
    assert output.attempt == dispatch.sequence.current
    manifest = output.to_dict()
    assert manifest["stdout"]["stream"] == "stderr"
    assert manifest["stdout"]["sha256"] == hashlib.sha256(body).hexdigest()
    assert "FAKE_PRIVATE_DISPATCH_STDERR" not in repr(output)


def test_dispatch_attempt_honors_cancellation(monkeypatch):
    event = threading.Event()
    launch = subprocess.Popen

    def launch_then_cancel(*args, **kwargs):
        process = launch(*args, **kwargs)
        event.set()
        return process

    monkeypatch.setattr(
        "agent.attempt_runner.subprocess.Popen", launch_then_cancel
    )
    dispatch = dispatch_attempt(
        ready_sequence(),
        argv("import time; time.sleep(60)"),
        cancel_event=event,
    )
    assert dispatch.run.record.state in {"exited", "cancelled"}
    assert dispatch.sequence.current.events == dispatch.run.record.events


def test_dispatch_attempt_forwards_memory_bound_validation():
    with pytest.raises(
        ValueError, match="^invalid attempt run memory bound$"
    ):
        dispatch_attempt(
            ready_sequence(), argv("pass"), memory_bound_mb=0
        )


def test_dispatch_attempt_result_is_frozen_and_bound():
    dispatch = dispatch_attempt(ready_sequence(), argv("pass"))
    with pytest.raises(FrozenInstanceError):
        dispatch.run = dispatch.run
    mismatched_timeout = AttemptRecord(
        FINGERPRINT, 1, 20_000, dispatch.run.record.events
    )
    for sequence, run in (
        (None, dispatch.run),
        (dispatch.sequence, None),
        (ready_sequence(timeout_ms=20_000), dispatch.run),
        (AttemptSequence("b" * 64, 10_000), dispatch.run),
        (
            AttemptSequence(FINGERPRINT, 20_000, (mismatched_timeout,)),
            dispatch.run,
        ),
    ):
        with pytest.raises(ValueError):
            AttemptDispatch(sequence, run)


def stamped_sequence(stamp=1, timeout_ms=10_000):
    return AttemptSequence(
        FINGERPRINT,
        timeout_ms,
        (AttemptRecord(FINGERPRINT, 1, timeout_ms),),
        report_stamp=stamp,
    )


def test_dispatch_attempt_forwards_a_fresh_report_stamp():
    dispatch = dispatch_attempt(
        stamped_sequence(3), argv("pass"), report_stamp=4
    )
    assert dispatch.sequence.report_stamp == 4
    assert dispatch.sequence.current.state == "exited"


def test_dispatch_attempt_adopts_the_first_report_stamp():
    dispatch = dispatch_attempt(
        ready_sequence(), argv("pass"), report_stamp=7
    )
    assert dispatch.sequence.report_stamp == 7


@pytest.mark.parametrize("stamp", [None, 0, 2, 5])
def test_dispatch_attempt_rejects_missing_or_stale_stamps(stamp):
    sequence = stamped_sequence(5)
    with pytest.raises(
        ValueError, match="report stamp"
    ):
        dispatch_attempt(sequence, argv("pass"), report_stamp=stamp)
    assert sequence.current is not None and sequence.current.state == "ready"


@pytest.mark.parametrize("stamp", [-1, 0, 1.5, True, "7"])
def test_dispatch_attempt_rejects_malformed_stamps(stamp):
    with pytest.raises(ValueError, match="^invalid attempt report stamp$"):
        dispatch_attempt(ready_sequence(), argv("pass"), report_stamp=stamp)


def test_dispatch_captured_output_binds_the_run_snapshot():
    dispatch = dispatch_attempt(
        ready_sequence(), argv("import sys; sys.stdout.write('payload')")
    )
    output = dispatch.captured_output()
    assert output.attempt is dispatch.sequence.current
    assert output.stdout == b"payload"
    assert output.expected_stdout_sha256 == hashlib.sha256(b"payload").hexdigest()
    assert output.stream == "stdout"
    assert output.complete is True
    dispatch.sequence.check_output_binding(output)


def test_dispatch_captured_output_carries_the_complete_claim():
    dispatch = dispatch_attempt(
        ready_sequence(), argv("import sys; sys.exit(9)")
    )
    assert dispatch.run.complete is True
    assert dispatch.captured_output().complete is True


def test_dispatch_captured_output_rejects_non_exited_runs():
    dispatch = dispatch_attempt(
        ready_sequence(), ("/FAKE_PRIVATE_missing_executable_9f31",)
    )
    assert dispatch.run.record.state == "failed"
    with pytest.raises(ValueError, match="exited"):
        dispatch.captured_output()


def test_publish_dispatch_selects_and_publishes_an_exited_run():
    sequence = ready_sequence()
    store = AttemptSequenceStore()
    store.publish(sequence)
    dispatch = dispatch_attempt(
        sequence, argv("import sys; sys.stdout.write('payload')")
    )
    published = publish_dispatch(store, dispatch, expected=sequence)
    assert published is store.current
    assert published.selected_result is not None
    candidate = published.evidence_candidate()
    output = dispatch.captured_output()
    assert candidate.output_fingerprint == output.to_dict()[
        "output_fingerprint"
    ]


def test_publish_dispatch_records_terminal_failures_without_selection():
    sequence = ready_sequence()
    store = AttemptSequenceStore()
    store.publish(sequence)
    dispatch = dispatch_attempt(
        sequence, ("/FAKE_PRIVATE_missing_executable_9f31",)
    )
    published = publish_dispatch(store, dispatch, expected=sequence)
    assert published.current.state == "failed"
    assert published.selected_result is None


def test_publish_dispatch_first_publication_needs_no_expected():
    store = AttemptSequenceStore()
    dispatch = dispatch_attempt(ready_sequence(), argv("pass"))
    published = publish_dispatch(store, dispatch)
    assert published is store.current


@pytest.mark.parametrize(
    "store,dispatch,expected,message",
    [
        (None, "dispatch", None, "sequence store"),
        ("store", None, None, "attempt dispatch"),
        ("store", "dispatch", "expected", "expected sequence"),
    ],
    ids=["foreign-store", "foreign-dispatch", "foreign-expected"],
)
def test_publish_dispatch_rejects_foreign_inputs(
    store, dispatch, expected, message
):
    if store == "store":
        store = AttemptSequenceStore()
    if dispatch == "dispatch":
        dispatch = dispatch_attempt(ready_sequence(), argv("pass"))
    with pytest.raises(ValueError, match=message):
        publish_dispatch(store, dispatch, expected)


def test_publish_dispatch_requires_expected_on_a_populated_store():
    sequence = ready_sequence()
    store = AttemptSequenceStore()
    store.publish(sequence)
    dispatch = dispatch_attempt(sequence, argv("pass"))
    with pytest.raises(
        ValueError, match="dispatch publication requires an expected sequence"
    ):
        publish_dispatch(store, dispatch)


def test_publish_dispatch_rejects_a_stale_expected():
    sequence = ready_sequence()
    store = AttemptSequenceStore()
    store.publish(dispatch_attempt(sequence, argv("pass")).sequence)
    dispatch = dispatch_attempt(ready_sequence(), argv("pass"))
    with pytest.raises(ValueError, match="compare failed"):
        publish_dispatch(store, dispatch, expected=sequence)


def exited_sequence(state="failed", ordinal=1):
    record = AttemptRecord(
        FINGERPRINT,
        ordinal,
        10_000,
        (AttemptEvent("started", 0), AttemptEvent(state, 2)),
    )
    return AttemptSequence(FINGERPRINT, 10_000, (record,))


def test_dispatch_next_attempt_reserves_and_runs_attempt_one():
    sequence = AttemptSequence(FINGERPRINT, 10_000)
    dispatch = dispatch_next_attempt(sequence, argv("import sys; sys.exit(3)"))
    assert dispatch.sequence.current.attempt_number == 1
    assert dispatch.sequence.current.state == "exited"
    assert dispatch.run.record.events[-1].exit_code == 3


def test_dispatch_next_attempt_retries_after_a_terminal_record():
    first = dispatch_next_attempt(
        AttemptSequence(FINGERPRINT, 10_000),
        argv("import sys; sys.exit(1)"),
    )
    dispatch = dispatch_next_attempt(first.sequence, argv("pass"))
    assert dispatch.sequence.current.attempt_number == 2
    assert dispatch.sequence.current.state == "exited"
    assert len(dispatch.sequence.attempts) == 2


def test_dispatch_next_attempt_runs_after_a_failed_attempt():
    sequence = exited_sequence("failed")
    dispatch = dispatch_next_attempt(sequence, argv("pass"))
    assert dispatch.sequence.current.attempt_number == 2
    assert dispatch.sequence.current.state == "exited"


@pytest.mark.parametrize(
    "sequence",
    [
        AttemptSequence(
            FINGERPRINT,
            10_000,
            (
                AttemptRecord(
                    FINGERPRINT, 1, 10_000, (AttemptEvent("started", 0),)
                ),
            ),
        ),
        ready_sequence(),
    ],
    ids=["in-flight", "ready-unstarted"],
)
def test_dispatch_next_attempt_rejects_a_nonterminal_current(sequence):
    with pytest.raises(ValueError):
        dispatch_next_attempt(sequence, argv("pass"))


def test_dispatch_next_attempt_rejects_a_selected_sequence():
    dispatch = dispatch_next_attempt(
        AttemptSequence(FINGERPRINT, 10_000), argv("pass")
    )
    output = AttemptOutput(
        dispatch.sequence.current,
        dispatch.run.stdout,
        hashlib.sha256(dispatch.run.stdout).hexdigest(),
    )
    selected = dispatch.sequence.select_result(output)
    with pytest.raises(
        ValueError, match="a selected result closes the attempt sequence"
    ):
        dispatch_next_attempt(selected, argv("pass"))


@pytest.mark.parametrize("bad", [None, "x", 1, AttemptRecord(FINGERPRINT, 1, 10)])
def test_dispatch_next_attempt_rejects_foreign_sequences(bad):
    with pytest.raises(
        ValueError, match="^attempt dispatch requires an attempt sequence$"
    ):
        dispatch_next_attempt(bad, argv("pass"))


def stamped_terminal_sequence(stamp=1):
    record = AttemptRecord(
        FINGERPRINT,
        1,
        10_000,
        (AttemptEvent("started", 0), AttemptEvent("exited", 2, 1)),
    )
    return AttemptSequence(
        FINGERPRINT, 10_000, (record,), report_stamp=stamp
    )


def test_dispatch_next_attempt_forwards_a_fresh_report_stamp():
    sequence = stamped_terminal_sequence(4)
    dispatch = dispatch_next_attempt(
        sequence, argv("pass"), report_stamp=5
    )
    assert dispatch.sequence.report_stamp == 5
    assert dispatch.sequence.current.attempt_number == 2


@pytest.mark.parametrize("stamp", [None, 0, 4])
def test_dispatch_next_attempt_rejects_missing_or_stale_stamps(stamp):
    sequence = stamped_terminal_sequence(4)
    with pytest.raises(ValueError, match="report stamp"):
        dispatch_next_attempt(sequence, argv("pass"), report_stamp=stamp)
    assert sequence.current.state == "exited"


def test_detect_ulimit_sh_returns_none_without_sh(monkeypatch):
    monkeypatch.setattr(attempt_runner.shutil, "which", lambda name: None)
    assert attempt_runner._detect_ulimit_sh() is None


def test_detect_ulimit_sh_requires_a_ulimit_v_shell(monkeypatch):
    monkeypatch.setattr(
        attempt_runner.shutil, "which", lambda name: "/bin/sh"
    )

    def fake_run(argv, **kwargs):
        assert argv == ["/bin/sh", "-c", "ulimit -v >/dev/null 2>&1"]
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(attempt_runner.subprocess, "run", fake_run)
    assert attempt_runner._detect_ulimit_sh() is None


def test_detect_ulimit_sh_accepts_a_capable_shell(monkeypatch):
    monkeypatch.setattr(
        attempt_runner.shutil, "which", lambda name: "/bin/sh"
    )
    monkeypatch.setattr(
        attempt_runner.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0),
    )
    assert attempt_runner._detect_ulimit_sh() == "/bin/sh"


def test_detect_ulimit_sh_treats_probe_errors_as_absent(monkeypatch):
    monkeypatch.setattr(
        attempt_runner.shutil, "which", lambda name: "/bin/sh"
    )

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 10)

    monkeypatch.setattr(attempt_runner.subprocess, "run", fake_run)
    assert attempt_runner._detect_ulimit_sh() is None


def test_detect_ulimit_sh_rejects_non_posix_hosts(monkeypatch):
    monkeypatch.setattr(attempt_runner.os, "name", "nt")
    monkeypatch.setattr(
        attempt_runner.subprocess,
        "run",
        lambda argv, **kwargs: pytest.fail("probe must not run"),
    )
    assert attempt_runner._detect_ulimit_sh() is None


def test_detect_unshare_requires_linux(monkeypatch):
    monkeypatch.setattr(attempt_runner.sys, "platform", "darwin")
    monkeypatch.setattr(
        attempt_runner.shutil,
        "which",
        lambda name: pytest.fail("unshare lookup must not run"),
    )
    assert attempt_runner._detect_unshare() is None


def test_detect_unshare_returns_none_without_binary(monkeypatch):
    monkeypatch.setattr(attempt_runner.sys, "platform", "linux")
    monkeypatch.setattr(attempt_runner.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        attempt_runner.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("probe must not run"),
    )
    assert attempt_runner._detect_unshare() is None


def test_detect_unshare_probes_the_required_namespace_options(monkeypatch):
    monkeypatch.setattr(attempt_runner.sys, "platform", "linux")
    monkeypatch.setattr(
        attempt_runner.shutil, "which", lambda name: "/usr/bin/unshare"
    )

    def fake_run(argv, **kwargs):
        assert argv == [
            "/usr/bin/unshare",
            "--net",
            "--map-current-user",
            "--",
            "true",
        ]
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(attempt_runner.subprocess, "run", fake_run)
    assert attempt_runner._detect_unshare() == "/usr/bin/unshare"


def test_detect_unshare_treats_probe_errors_as_absent(monkeypatch):
    monkeypatch.setattr(attempt_runner.sys, "platform", "linux")
    monkeypatch.setattr(
        attempt_runner.shutil, "which", lambda name: "/usr/bin/unshare"
    )

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 10)

    monkeypatch.setattr(attempt_runner.subprocess, "run", fake_run)
    assert attempt_runner._detect_unshare() is None


def test_run_memory_bound_non_posix_sh_still_rejected(monkeypatch):
    # A host where `sh` exists but cannot enforce RLIMIT_AS (e.g.
    # Git Bash on Windows) must not accept the declared bound.
    monkeypatch.setattr(attempt_runner, "_PRLIMIT", None)
    monkeypatch.setattr(attempt_runner, "_SH", None)
    monkeypatch.setattr(attempt_runner, "resource", None)
    runner = AttemptRunner()
    with pytest.raises(ValueError, match="memory bound"):
        runner.run(request(), argv("pass"), memory_bound_mb=8)


def test_run_memory_bound_sh_probe_failure_falls_back_to_preexec(
    monkeypatch,
):
    # An `sh` that fails the ulimit probe leaves _SH None, so the
    # preexec path (old behavior) still carries the bound.
    monkeypatch.setattr(attempt_runner, "_PRLIMIT", None)
    monkeypatch.setattr(attempt_runner, "_SH", None)
    run = AttemptRunner().run(
        request(), argv("import sys; sys.stdout.write('ok')"),
        memory_bound_mb=128,
    )
    assert run.stdout == b"ok"
    assert run.record.state == "exited"


def test_dispatch_and_publish_runs_and_publishes_end_to_end():
    sequence = AttemptSequence(FINGERPRINT, 10_000)
    store = AttemptSequenceStore()
    store.publish(sequence)
    dispatch = dispatch_and_publish(
        store, argv("import sys; sys.stdout.write('ok')")
    )
    assert dispatch.run.record.state == "exited"
    assert store.current is not dispatch.sequence
    assert store.current.selected_result is not None
    assert store.current.current.attempt_number == 1
    output = dispatch.captured_output()
    assert store.current.selected_result[1] == output.to_dict()[
        "output_fingerprint"
    ]


def test_dispatch_and_publish_retries_after_a_terminal_run():
    sequence = AttemptSequence(FINGERPRINT, 10_000)
    store = AttemptSequenceStore()
    store.publish(sequence)
    first = dispatch_and_publish(
        store, ("/FAKE_PRIVATE_missing_executable_9f31",)
    )
    assert first.run.record.state == "failed"
    assert store.current.selected_result is None
    second = dispatch_and_publish(store, argv("pass"))
    assert second.sequence.current.attempt_number == 2


def test_dispatch_and_publish_records_failure_without_selection():
    sequence = AttemptSequence(FINGERPRINT, 10_000)
    store = AttemptSequenceStore()
    store.publish(sequence)
    dispatch = dispatch_and_publish(
        store, ("/FAKE_PRIVATE_missing_executable_9f31",)
    )
    assert dispatch.run.record.state == "failed"
    assert store.current.current.state == "failed"
    assert store.current.selected_result is None


def test_dispatch_and_publish_rejects_foreign_stores():
    with pytest.raises(
        ValueError, match="requires a sequence store"
    ):
        dispatch_and_publish("store", argv("pass"))
    store = AttemptSequenceStore()
    with pytest.raises(ValueError, match="requires a lineage"):
        dispatch_and_publish(store, argv("pass"))


def test_dispatch_and_publish_rejects_a_closed_lineage():
    sequence = AttemptSequence(FINGERPRINT, 10_000)
    store = AttemptSequenceStore()
    store.publish(sequence)
    first = dispatch_and_publish(store, argv("pass"))
    assert store.current.selected_result is not None
    with pytest.raises(
        ValueError, match="a selected result closes the attempt sequence"
    ):
        dispatch_and_publish(store, argv("pass"))


@pytest.mark.parametrize("isolate_filesystem_write", [1, "true", None])
def test_run_rejects_non_boolean_filesystem_write_isolation(
    isolate_filesystem_write,
):
    with pytest.raises(
        ValueError,
        match="^invalid attempt run filesystem write isolation$",
    ):
        AttemptRunner().run(
            request(),
            argv("pass"),
            isolate_filesystem_write=isolate_filesystem_write,
        )


@pytest.mark.parametrize("isolate_process_spawn", [1, "true", None])
def test_run_rejects_non_boolean_process_spawn_isolation(
    isolate_process_spawn,
):
    with pytest.raises(
        ValueError,
        match="^invalid attempt run process spawn isolation$",
    ):
        AttemptRunner().run(
            request(),
            argv("pass"),
            isolate_process_spawn=isolate_process_spawn,
        )


def test_process_spawn_detector_rejects_non_linux(monkeypatch):
    monkeypatch.setattr(attempt_runner.sys, "platform", "darwin")
    monkeypatch.setattr(
        attempt_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "non-Linux hosts do not probe process-spawn isolation"
        ),
    )

    assert attempt_runner._detect_process_spawn_isolation() is False


def test_process_spawn_detector_rejects_unsupported_architecture(
    monkeypatch,
):
    monkeypatch.setattr(attempt_runner.sys, "platform", "linux")
    monkeypatch.setattr(
        attempt_runner.platform, "machine", lambda: "riscv64"
    )
    monkeypatch.setattr(
        attempt_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "unsupported architectures do not probe process-spawn isolation"
        ),
    )

    assert attempt_runner._detect_process_spawn_isolation() is False


def test_process_spawn_detector_treats_architecture_errors_as_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(attempt_runner.sys, "platform", "linux")

    def fail_architecture_lookup():
        raise RuntimeError("arch lookup failed")

    monkeypatch.setattr(
        attempt_runner.platform,
        "machine",
        fail_architecture_lookup,
    )
    monkeypatch.setattr(
        attempt_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "arch lookup failure must stop the process-spawn probe"
        ),
    )

    assert attempt_runner._detect_process_spawn_isolation() is False


@pytest.mark.parametrize(
    "error", [OSError("probe failed"), RuntimeError("probe failed")]
)
def test_process_spawn_detector_treats_probe_errors_as_unavailable(
    monkeypatch, error
):
    monkeypatch.setattr(attempt_runner.sys, "platform", "linux")
    monkeypatch.setattr(
        attempt_runner.platform, "machine", lambda: "x86_64"
    )

    def fail_probe(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(attempt_runner.subprocess, "run", fail_probe)
    assert attempt_runner._detect_process_spawn_isolation() is False


def test_run_process_spawn_isolation_requires_boundary_before_spawn(
    monkeypatch,
):
    spawned = False

    def fail_if_spawned(*args, **kwargs):
        nonlocal spawned
        spawned = True
        pytest.fail("isolation validation must precede spawn")

    monkeypatch.setattr(
        attempt_runner,
        "_PROCESS_SPAWN_ISOLATION_ENFORCEABLE",
        False,
    )
    monkeypatch.setattr(attempt_runner.subprocess, "Popen", fail_if_spawned)
    with pytest.raises(
        ValueError,
        match="^attempt run process spawn isolation requires a seccomp filter boundary$",
    ):
        AttemptRunner().run(
            request(),
            argv("pass"),
            isolate_process_spawn=True,
        )
    assert spawned is False


def test_filesystem_write_detector_rejects_non_linux(monkeypatch):
    monkeypatch.setattr(attempt_runner.sys, "platform", "darwin")
    monkeypatch.setattr(
        attempt_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "non-Linux hosts do not probe filesystem isolation"
        ),
    )

    assert attempt_runner._detect_filesystem_write_isolation() is False


def test_filesystem_write_detector_does_not_require_unshare(monkeypatch):
    monkeypatch.setattr(attempt_runner.sys, "platform", "linux")
    monkeypatch.setattr(
        attempt_runner.shutil,
        "which",
        lambda _name: pytest.fail("filesystem isolation does not use unshare"),
    )
    calls = []

    def successful_probe(argv, **kwargs):
        calls.append((argv, kwargs))
        return attempt_runner.subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(attempt_runner.subprocess, "run", successful_probe)

    assert attempt_runner._detect_filesystem_write_isolation() is True
    assert calls[0][0] == [
        attempt_runner.sys.executable,
        "-I",
        "-c",
        attempt_runner._FILESYSTEM_WRITE_PROBE_SCRIPT,
    ]
    assert calls[0][1]["timeout"] == 10


@pytest.mark.parametrize(
    "error", [OSError("probe failed"), RuntimeError("probe failed")]
)
def test_filesystem_write_detector_rejects_probe_errors(monkeypatch, error):
    monkeypatch.setattr(attempt_runner.sys, "platform", "linux")

    def fail_probe(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(attempt_runner.subprocess, "run", fail_probe)
    assert attempt_runner._detect_filesystem_write_isolation() is False


def test_run_filesystem_write_isolation_requires_boundary_before_spawn(
    monkeypatch,
):
    spawned = False

    def fail_if_spawned(*args, **kwargs):
        nonlocal spawned
        spawned = True
        pytest.fail("isolation validation must precede spawn")

    monkeypatch.setattr(
        attempt_runner,
        "_FILESYSTEM_WRITE_ISOLATION_ENFORCEABLE",
        False,
    )
    monkeypatch.setattr(attempt_runner.subprocess, "Popen", fail_if_spawned)
    with pytest.raises(
        ValueError,
        match="^attempt run filesystem write isolation requires a read-only mount namespace boundary$",
    ):
        AttemptRunner().run(
            request(),
            argv("pass"),
            isolate_filesystem_write=True,
        )
    assert spawned is False


@pytest.mark.skipif(
    not attempt_runner.filesystem_write_isolation_enforceable(),
    reason="filesystem write isolation requires unprivileged mount namespaces",
)
def test_run_filesystem_write_isolation_blocks_writes_and_preserves_host(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(attempt_runner, "_UNSHARE", None)
    child_path = tmp_path / "child-write.txt"
    child_argv = (
        PY,
        "-c",
        "import pathlib,sys; "
        "print('capeff='+next(line.split()[1] "
        "for line in pathlib.Path('/proc/self/status').read_text().splitlines() "
        "if line.startswith('CapEff:')), flush=True); "
        "print('attempting-write', flush=True); "
        "pathlib.Path(sys.argv[1]).write_text('child')",
        str(child_path),
    )

    isolated = AttemptRunner().run(
        request(),
        child_argv,
        isolate_filesystem_write=True,
    )
    assert isolated.record.state == "exited"
    assert isolated.record.events[-1].exit_code != 0
    assert isolated.stdout == (
        b"capeff=0000000000000000\nattempting-write\n"
    )
    assert not child_path.exists()

    host_path = tmp_path / "host-write.txt"
    host_path.write_text("host")
    assert host_path.read_text() == "host"

    direct = AttemptRunner().run(request(), child_argv)
    assert direct.record.state == "exited"
    assert direct.record.events[-1].exit_code == 0
    assert child_path.read_text() == "child"


def test_root_mapped_filesystem_isolation_drops_capabilities(tmp_path):
    if not attempt_runner.filesystem_write_isolation_enforceable():
        pytest.skip("filesystem write isolation is unavailable")
    unshare = attempt_runner.shutil.which("unshare")
    if unshare is None:
        pytest.skip("unshare is unavailable")
    try:
        root_mapping = subprocess.run(
            [unshare, "--user", "--map-root-user", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("root-mapped user namespace is unavailable")
    if root_mapping.returncode != 0:
        pytest.skip("root-mapped user namespace is unavailable")

    child_path = tmp_path / "root-child-write.txt"
    target_script = """import ctypes, pathlib, sys
status = pathlib.Path("/proc/self/status").read_text().splitlines()
cap_eff = next(line.split()[1] for line in status if line.startswith("CapEff:"))
print(f"capeff={cap_eff}", flush=True)
class _MountAttr(ctypes.Structure):
    _fields_ = [
        ("attr_set", ctypes.c_uint64),
        ("attr_clr", ctypes.c_uint64),
        ("propagation", ctypes.c_uint64),
        ("userns_fd", ctypes.c_uint64),
    ]
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
ctypes.set_errno(0)
clear_result = libc.syscall(
    ctypes.c_long(442),
    ctypes.c_long(-100),
    ctypes.c_char_p(b"/"),
    ctypes.c_long(0x8000),
    ctypes.byref(_MountAttr(0, 1, 0, 0)),
    ctypes.c_size_t(ctypes.sizeof(_MountAttr)),
)
print(f"clear_result={clear_result} clear_errno={ctypes.get_errno()}", flush=True)
try:
    pathlib.Path(sys.argv[1]).write_text("child")
except OSError as error:
    print(f"write_errno={error.errno}", flush=True)
else:
    print("write_succeeded", flush=True)
"""
    outer_script = f"""import sys
from agent.attempt_runner import AttemptRunner
from agent.verification_attempt import AttemptExecutionRequest
target_script = {target_script!r}
result = AttemptRunner().run(
    AttemptExecutionRequest("a" * 64, 1, 10000),
    (sys.executable, "-c", target_script, sys.argv[1]),
    isolate_filesystem_write=True,
)
sys.stdout.buffer.write(result.stdout)
sys.exit(
    0
    if result.record.state == "exited"
    and result.record.events[-1].exit_code == 0
    else 1
)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    mapped = subprocess.run(
        [
            unshare,
            "--user",
            "--map-root-user",
            "--",
            PY,
            "-c",
            outer_script,
            str(child_path),
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )

    assert mapped.returncode == 0
    output = dict(
        line.split("=", 1) for line in mapped.stdout.splitlines()
    )
    assert int(output["capeff"], 16) == 0
    assert output["clear_result"] == "-1 clear_errno=1"
    assert output["write_errno"] == "30"
    assert not child_path.exists()

    host_path = tmp_path / "root-host-write.txt"
    host_path.write_text("host")
    assert host_path.read_text() == "host"


@pytest.mark.skipif(
    not attempt_runner.filesystem_write_isolation_enforceable(),
    reason="filesystem write isolation requires unprivileged mount namespaces",
)
def test_run_filesystem_write_isolation_keeps_dev_null_writable():
    result = AttemptRunner().run(
        request(),
        argv(
            "open('/dev/null', 'wb').write(b'x'); "
            "print('stdout-captured')"
        ),
        isolate_filesystem_write=True,
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout == b"stdout-captured\n"


@pytest.mark.skipif(
    not attempt_runner.filesystem_write_isolation_enforceable()
    or not attempt_runner.network_isolation_enforceable(),
    reason="requires mount and network namespace enforcement",
)
def test_run_filesystem_write_isolation_combines_with_network():
    result = AttemptRunner().run(
        request(),
        argv("print('combined')"),
        isolate_network=True,
        isolate_filesystem_write=True,
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout == b"combined\n"


@pytest.mark.skipif(
    not attempt_runner.filesystem_write_isolation_enforceable()
    or not attempt_runner.memory_bound_enforceable(),
    reason="requires mount namespace and memory-bound enforcement",
)
def test_run_filesystem_write_isolation_combines_with_memory_bound():
    result = AttemptRunner().run(
        request(),
        argv(
            "import resource; "
            "print(resource.getrlimit(resource.RLIMIT_AS)[0])"
        ),
        memory_bound_mb=256,
        isolate_filesystem_write=True,
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert int(result.stdout.strip()) == 256 * 1_048_576


@pytest.mark.skipif(os.name != "posix", reason="namespace marker requires POSIX")
def test_run_filesystem_write_isolation_setup_failure_is_failed(
    monkeypatch,
):
    monkeypatch.setattr(
        attempt_runner,
        "_FILESYSTEM_WRITE_ISOLATION_ENFORCEABLE",
        True,
    )
    monkeypatch.setattr(
        attempt_runner,
        "_NAMESPACE_MARKER_SCRIPT",
        "import os; os._exit(126)",
    )
    result = AttemptRunner().run(
        request(),
        argv("print('unreached')"),
        isolate_filesystem_write=True,
    )

    assert result.record.state == "failed"
    assert [event.kind for event in result.record.events] == [
        "started",
        "failed",
    ]
    assert result.record.events[-1].exit_code is None
    assert result.stdout == b""


def test_dispatch_attempt_forwards_filesystem_write_isolation(monkeypatch):
    calls = []
    real_run = AttemptRunner.run

    def record_run(self, execution_request, child_argv, **kwargs):
        calls.append(kwargs["isolate_filesystem_write"])
        kwargs["isolate_filesystem_write"] = False
        return real_run(self, execution_request, child_argv, **kwargs)

    monkeypatch.setattr(AttemptRunner, "run", record_run)
    sequence = AttemptSequence(FINGERPRINT, 10_000).begin_attempt()
    dispatch = dispatch_attempt(
        sequence,
        argv("pass"),
        isolate_filesystem_write=True,
    )

    assert calls == [True]
    assert dispatch.run.record.state == "exited"
    assert dispatch.run.record.events[-1].exit_code == 0


@pytest.mark.skipif(
    not attempt_runner.process_spawn_isolation_enforceable(),
    reason="process-spawn isolation requires seccomp support",
)
def test_run_process_spawn_isolation_denies_forks_and_preserves_threads():
    result = AttemptRunner().run(
        request(),
        argv(
            "import os, subprocess, threading\n"
            "try:\n"
            " os.fork()\n"
            "except PermissionError as error:\n"
            " print(f'fork={error.errno}', flush=True)\n"
            "else:\n"
            " raise SystemExit('fork unexpectedly succeeded')\n"
            "try:\n"
            " subprocess.run(['true'], check=True)\n"
            "except OSError as error:\n"
            " print(f'subprocess={error.errno}', flush=True)\n"
            "else:\n"
            " raise SystemExit('subprocess unexpectedly succeeded')\n"
            "ran = []\n"
            "thread = threading.Thread(target=lambda: ran.append(True))\n"
            "thread.start(); thread.join(timeout=3)\n"
            "if thread.is_alive() or ran != [True]: raise SystemExit(4)\n"
            "print('thread=ok')"
        ),
        isolate_process_spawn=True,
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout == b"fork=1\nsubprocess=1\nthread=ok\n"


def test_run_without_process_spawn_isolation_can_spawn_children():
    result = AttemptRunner().run(
        request(),
        argv(
            "import subprocess, sys\n"
            "subprocess.run([sys.executable, '-c', 'pass'], check=True)\n"
            "print('spawn=ok')"
        ),
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert result.stdout == b"spawn=ok\n"


@pytest.mark.skipif(
    not attempt_runner.process_spawn_isolation_enforceable()
    or not attempt_runner.filesystem_write_isolation_enforceable()
    or not attempt_runner.network_isolation_enforceable()
    or not attempt_runner.memory_bound_enforceable(),
    reason="requires seccomp, mount/network namespaces, and memory bounds",
)
def test_process_spawn_isolation_combines_with_network_filesystem_and_memory():
    result = AttemptRunner().run(
        request(),
        argv(
            "import resource\n"
            "print(resource.getrlimit(resource.RLIMIT_AS)[0])"
        ),
        memory_bound_mb=256,
        isolate_network=True,
        isolate_filesystem_write=True,
        isolate_process_spawn=True,
    )

    assert result.record.state == "exited"
    assert result.record.events[-1].exit_code == 0
    assert int(result.stdout.strip()) == 256 * 1_048_576


@pytest.mark.skipif(
    os.name != "posix",
    reason="namespace marker requires POSIX",
)
def test_run_process_spawn_isolation_setup_failure_is_failed(monkeypatch):
    monkeypatch.setattr(
        attempt_runner,
        "_PROCESS_SPAWN_ISOLATION_ENFORCEABLE",
        True,
    )
    monkeypatch.setattr(
        attempt_runner,
        "_NAMESPACE_MARKER_SCRIPT",
        "import os; os._exit(126)",
    )
    result = AttemptRunner().run(
        request(),
        argv("print('unreached')"),
        isolate_process_spawn=True,
    )

    assert result.record.state == "failed"
    assert [event.kind for event in result.record.events] == [
        "started",
        "failed",
    ]
    assert result.record.events[-1].exit_code is None
    assert result.stdout == b""


def test_dispatch_attempt_forwards_process_spawn_isolation(monkeypatch):
    calls = []
    real_run = AttemptRunner.run

    def record_run(self, execution_request, child_argv, **kwargs):
        calls.append(kwargs["isolate_process_spawn"])
        kwargs["isolate_process_spawn"] = False
        return real_run(self, execution_request, child_argv, **kwargs)

    monkeypatch.setattr(
        attempt_runner,
        "_PROCESS_SPAWN_ISOLATION_ENFORCEABLE",
        True,
    )
    monkeypatch.setattr(AttemptRunner, "run", record_run)
    sequence = AttemptSequence(FINGERPRINT, 10_000).begin_attempt()
    dispatch = dispatch_attempt(
        sequence,
        argv("pass"),
        isolate_process_spawn=True,
    )

    assert calls == [True]
    assert dispatch.run.record.state == "exited"
    assert dispatch.run.record.events[-1].exit_code == 0
