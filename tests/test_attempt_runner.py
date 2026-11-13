"""Real process-control boundary tests for the declared-request runner."""

import hashlib
import json
import sys
import threading
import time
from dataclasses import FrozenInstanceError

import pytest

from agent.attempt_runner import AttemptRunner, AttemptRunResult
from agent.verification_attempt import (
    MAX_STDOUT_BYTES,
    AttemptEvent,
    AttemptExecutionRequest,
    AttemptOutput,
    AttemptRecord,
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
