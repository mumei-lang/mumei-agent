"""Real process-control boundary tests for the declared-request runner."""

import hashlib
import json
import subprocess
import sys
import threading
import time
from dataclasses import FrozenInstanceError

import pytest

from agent.attempt_runner import (
    AttemptDispatch,
    AttemptRunner,
    AttemptRunResult,
    dispatch_attempt,
)
from agent.verification_attempt import (
    MAX_STDOUT_BYTES,
    AttemptEvent,
    AttemptExecutionRequest,
    AttemptOutput,
    AttemptRecord,
    AttemptSequence,
)

FINGERPRINT = "a" * 64
PY = sys.executable


def request(number=1, timeout_ms=10_000, fingerprint=FINGERPRINT):
    return AttemptExecutionRequest(fingerprint, number, timeout_ms)


def argv(code):
    return (PY, "-c", code)


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


def test_run_captures_bounded_stdout_without_interpreting_it():
    body = b"FAKE_PRIVATE_RUNNER_STDOUT"
    result = AttemptRunner().run(
        request(), argv(f"import sys; sys.stdout.buffer.write({body!r})")
    )
    assert result.stdout == body
    assert result.complete is True
    assert result.record.state == "exited"
    assert "FAKE_PRIVATE_RUNNER_STDOUT" not in repr(result)


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
    for record, stdout, complete in (
        (running, b"", True),
        ("x", b"", True),
        (exited, b"x" * (MAX_STDOUT_BYTES + 1), True),
        (exited, "x", True),
        (exited, b"", 0),
        (exited, b"", "true"),
    ):
        with pytest.raises(ValueError):
            AttemptRunResult(record, stdout, complete)
    result = AttemptRunResult(exited, b"", True)
    with pytest.raises(FrozenInstanceError):
        result.complete = False


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
    # as a spawn failure rather than a wrapped prlimit exit.
    monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
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


def test_run_memory_bound_falls_back_to_preexec(monkeypatch):
    import agent.attempt_runner as runner_mod

    spawned = {}

    class FakePopen:
        def __init__(self, args, **kw):
            spawned["args"] = list(args)
            spawned["preexec_fn"] = kw.get("preexec_fn")
            raise OSError("stop before spawn")

    monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
    monkeypatch.setattr(runner_mod.subprocess, "Popen", FakePopen)
    AttemptRunner().run(request(), argv("pass"), memory_bound_mb=64)
    assert spawned["args"] == list(argv("pass"))
    assert spawned["preexec_fn"] is not None


def test_run_memory_bound_missing_target_reports_failed():
    # Under prlimit, a target the wrapper cannot exec would exit
    # 127 — masquerading as the target's own exit. The runner
    # leaves the argv unwrapped instead so the plain spawn reports
    # a real failure.
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
    assert runner_mod.memory_bound_spawn_thread_safe()
    monkeypatch.setattr(runner_mod, "_PRLIMIT", None)
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
