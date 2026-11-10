"""Trusted Core handoff only; synthetic diagnostics are not proof evidence."""

import hashlib
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from agent import core_evidence
from agent.core_evidence import (
    MAX_CHECK_TIMEOUT_MS,
    MAX_DIAGNOSTIC_BYTES,
    check_evidence_representation,
)
from agent.verification_attempt import AttemptEvent, AttemptOutput, AttemptRecord

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX Core handoff pilot")

DIAGNOSTIC = {
    "schema_version": "mumei.evidence-representation-check/v1",
    "evidence_schema_version": "mumei.verification-evidence/v1",
    "representation": "valid",
    "acceptance": "not_evaluated",
    "checks_not_performed": [
        "claim_truth", "file_identity", "freshness", "producer_authenticity",
        "semantic_correspondence", "artifact_semantics",
    ],
}
VALID = json.dumps(DIAGNOSTIC).encode()
PRIVATE = b"FAKE_PRIVATE_STDOUT_NOT_PROOF"


def snapshot(body=PRIVATE, exit_code=0):
    attempt = AttemptRecord(
        "a" * 64, 1, 1000,
        (AttemptEvent("started", 0), AttemptEvent("exited", 1, exit_code)),
    )
    return AttemptOutput(attempt, body, hashlib.sha256(body).hexdigest())


@pytest.fixture
def executable(tmp_path):
    def write(script):
        path = tmp_path / "FAKE_PRIVATE trusted core; not-a-shell"
        path.write_text(f"#!{sys.executable}\n" + script, encoding="utf-8")
        path.chmod(0o700)
        return str(path)
    return write


def report_script(stdout=VALID, stderr=b"", code=0):
    return (
        "import sys\n"
        "sys.stdin.buffer.read()\n"
        f"sys.stdout.buffer.write({stdout!r})\n"
        f"sys.stderr.buffer.write({stderr!r})\n"
        f"sys.exit({code})\n"
    )


def failed(output, executable, timeout_ms=2000):
    with pytest.raises(ValueError, match="^Core Evidence representation check failed$") as error:
        check_evidence_representation(output, core_executable=executable, timeout_ms=timeout_ms)
    assert error.value.__suppress_context__
    assert "FAKE_PRIVATE" not in str(error.value)


@pytest.mark.parametrize("size", [0, 1, 4095, 4096, 4097, 65535, 65536])
@pytest.mark.parametrize("exit_code", [0, 7, -9])
@pytest.mark.parametrize("cancellable", [False, True])
def test_original_bytes_fixed_argv_empty_environment_and_no_snapshot_mutation(
    executable, monkeypatch, capsys, size, exit_code, cancellable,
):
    body = bytes(i % 256 for i in range(size))
    output = snapshot(body, exit_code)
    before = output.to_dict()
    monkeypatch.setenv("FAKE_PRIVATE_CORE_CHECK_SECRET", "FAKE_PRIVATE_SECRET_VALUE")
    script = (
        "import os, sys\n"
        "assert sys.argv[1:] == ['evidence', 'check', '--stdin', '--json']\n"
        "assert 'FAKE_PRIVATE_CORE_CHECK_SECRET' not in os.environ\n"
        "assert 'PATH' not in os.environ\n"
        f"assert sys.stdin.buffer.read() == {body!r}\n"
        f"sys.stdout.buffer.write({VALID!r})\n"
    )
    assert check_evidence_representation(
        output, core_executable=executable(script), timeout_ms=2000,
        cancel_event=threading.Event() if cancellable else None,
    ) is None
    assert output.to_dict() == before
    assert output.stdout == body
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("keys", list(itertools.permutations(DIAGNOSTIC)), ids=lambda keys: "-".join(keys))
def test_valid_diagnostic_is_order_independent(executable, keys):
    diagnostic = json.dumps({key: DIAGNOSTIC[key] for key in keys}, indent=2).encode()
    check_evidence_representation(
        snapshot(), core_executable=executable(report_script(diagnostic)), timeout_ms=2000,
    )


BAD_DIAGNOSTICS = [
    b"", b"{}", b"[]", b"null", b"true", b'"valid"', b'{"success":true}',
    b"\xff", b"\xef\xbb\xbf" + VALID, VALID + VALID, b"log\n" + VALID,
    VALID + b"\nlog", VALID[:-1], b'{"secret":NaN}', b"[" * 2000,
    VALID[:-1] + b', "acceptance": "not_evaluated"}',
    VALID[:-1] + b', "a\\u0063ceptance": "not_evaluated"}',
    json.dumps({**DIAGNOSTIC, "FAKE_PRIVATE_extra": True}).encode(),
]
for field in DIAGNOSTIC:
    BAD_DIAGNOSTICS.append(json.dumps({key: value for key, value in DIAGNOSTIC.items() if key != field}).encode())
    for value in [None, True, False, 0, 1, "FAKE_PRIVATE_success", [], {}]:
        BAD_DIAGNOSTICS.append(json.dumps({**DIAGNOSTIC, field: value}).encode())
for field, values in {
    "acceptance": ["accepted", "evaluated", "valid"],
    "representation": ["invalid", "verified"],
    "schema_version": ["mumei.evidence-representation-check/v2"],
    "checks_not_performed": [[], DIAGNOSTIC["checks_not_performed"][:-1]],
}.items():
    for value in values:
        BAD_DIAGNOSTICS.append(json.dumps({**DIAGNOSTIC, field: value}).encode())


@pytest.mark.parametrize("diagnostic", BAD_DIAGNOSTICS, ids=[f"invalid-{i}" for i in range(len(BAD_DIAGNOSTICS))])
def test_exit_zero_is_not_sufficient(executable, diagnostic, capsys):
    failed(snapshot(), executable(report_script(diagnostic)))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("code", [1, 2, 3, 7, 127, -9])
def test_even_a_valid_diagnostic_requires_successful_core_exit(executable, code):
    failed(snapshot(), executable(report_script(code=code)))


@pytest.mark.parametrize("size", [1, MAX_DIAGNOSTIC_BYTES, MAX_DIAGNOSTIC_BYTES + 1, 65536])
def test_stderr_is_private_and_any_stderr_fails(executable, size, capsys):
    failed(snapshot(), executable(report_script(stderr=b"X" * size)))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("padding", [b" ", b"\n", b"\t"])
def test_exact_diagnostic_bound_and_one_byte_overflow(executable, padding):
    exact = VALID + padding * (MAX_DIAGNOSTIC_BYTES - len(VALID))
    check_evidence_representation(snapshot(), core_executable=executable(report_script(exact)), timeout_ms=2000)
    failed(snapshot(), executable(report_script(exact + padding)))


@pytest.mark.parametrize("script", [
    "import time\ntime.sleep(60)\n",
    "import sys, time\nsys.stdin.buffer.read()\ntime.sleep(60)\n",
    "import os, time\nos.close(0)\nos.close(1)\nos.close(2)\ntime.sleep(60)\n",
])
def test_deadline_kills_and_reaps_direct_child(executable, monkeypatch, script):
    processes = []
    popen = subprocess.Popen

    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(core_evidence.subprocess, "Popen", launch)
    start = time.monotonic()
    failed(snapshot(b"X" * 65536), executable(script), timeout_ms=100)
    assert time.monotonic() - start < 2
    assert len(processes) == 1 and processes[0].returncode is not None


def test_closed_stdin_and_oversized_output_cannot_deadlock(executable):
    for script in [
        "import os\nwhile True:\n os.write(1, b'X' * 4096)\n",
        "import os\nwhile True:\n os.write(2, b'X' * 4096)\n",
    ]:
        start = time.monotonic()
        failed(snapshot(b"X" * 65536), executable(script), timeout_ms=500)
        assert time.monotonic() - start < 2


def test_early_reader_close_fails_when_input_cannot_be_written(executable, monkeypatch):
    processes = []
    popen, write = subprocess.Popen, os.write

    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    def write_after_reader_exit(fd, data):
        # Synchronize reader closure, rather than depending on pipe capacity.
        processes[0].wait(timeout=2)
        return write(fd, data)

    path = executable(f"import os, sys\nos.close(0)\nsys.stdout.buffer.write({VALID!r})\n")
    monkeypatch.setattr(core_evidence.subprocess, "Popen", launch)
    monkeypatch.setattr(core_evidence.os, "write", write_after_reader_exit)
    failed(snapshot(b"X" * 65536), path)
    assert processes[0].returncode is not None


def test_stdout_before_reading_input_is_drained_without_deadlock(executable):
    script = (
        "import sys\n"
        f"sys.stdout.buffer.write({VALID!r})\nsys.stdout.buffer.flush()\n"
        "assert len(sys.stdin.buffer.read()) == 65536\n"
    )
    check_evidence_representation(snapshot(b"X" * 65536), core_executable=executable(script), timeout_ms=2000)


def test_partial_writes_and_transient_unready_pipes_preserve_input(executable, monkeypatch):
    read, write = os.read, os.write
    first_read = first_write = True

    def read_once_unready(fd, count):
        nonlocal first_read
        if first_read:
            first_read = False
            raise BlockingIOError
        return read(fd, count)

    def write_once_unready(fd, data):
        nonlocal first_write
        if first_write:
            first_write = False
            raise BlockingIOError
        return write(fd, data[:13])

    body = b"FAKE_PRIVATE_BINARY\xff" * 128
    path = executable(f"import sys\nassert sys.stdin.buffer.read() == {body!r}\nsys.stdout.buffer.write({VALID!r})\n")
    # Leave Popen's own error-pipe read alone; perturb only registered pipes.
    original_selector = core_evidence.selectors.DefaultSelector

    class TransientSelector(original_selector):
        def __enter__(self):
            monkeypatch.setattr(core_evidence.os, "read", read_once_unready)
            monkeypatch.setattr(core_evidence.os, "write", write_once_unready)
            return super().__enter__()

    monkeypatch.setattr(core_evidence.selectors, "DefaultSelector", TransientSelector)
    check_evidence_representation(snapshot(body), core_executable=path, timeout_ms=2000)
    assert not first_read and not first_write


def test_keyboard_interrupt_closes_pipes_and_reaps_child(executable, monkeypatch):
    processes = []
    popen = subprocess.Popen

    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(core_evidence.subprocess, "Popen", launch)
    monkeypatch.setattr(core_evidence.selectors.DefaultSelector, "select", interrupt)
    with pytest.raises(KeyboardInterrupt):
        check_evidence_representation(
            snapshot(), core_executable=executable("import time\ntime.sleep(60)\n"), timeout_ms=2000,
        )
    assert len(processes) == 1 and processes[0].returncode is not None
    assert all(stream.closed for stream in [processes[0].stdin, processes[0].stdout, processes[0].stderr])


def test_import_never_starts_core(monkeypatch):
    import importlib

    monkeypatch.setattr(core_evidence.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawned"))
    importlib.reload(core_evidence)


@pytest.fixture
def child_processes(monkeypatch):
    processes = []
    popen = subprocess.Popen

    class ChildProcess(popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            processes.append(self)

    monkeypatch.setattr(core_evidence.subprocess, "Popen", ChildProcess)
    yield processes
    for process in processes:
        assert process.returncode is not None
        assert all(stream.closed for stream in [process.stdin, process.stdout, process.stderr])


def cancelled(output, executable, event):
    with pytest.raises(core_evidence.CoreCheckCancelled, match="^Core Evidence representation check cancelled$") as error:
        check_evidence_representation(output, core_executable=executable, timeout_ms=2000, cancel_event=event)
    assert error.value.__suppress_context__
    assert event.is_set()


@pytest.mark.parametrize("size", [0, 1, 4095, 4096, 4097, 65535, 65536])
@pytest.mark.parametrize("exit_code", [0, 7, -9])
def test_pre_cancelled_never_spawns_or_changes_lineage(monkeypatch, capsys, size, exit_code):
    output = snapshot(b"x" * size, exit_code)
    before = output.to_dict()
    event = threading.Event()
    event.set()
    monkeypatch.setattr(core_evidence.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawned"))
    cancelled(output, "/FAKE_PRIVATE_unread_core", event)
    assert output.to_dict() == before
    assert output.stdout == b"x" * size
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


class EventSubclass(threading.Event):
    def is_set(self):
        pytest.fail("untrusted cancellation hook called")


@pytest.mark.parametrize("event", [True, False, 0, 1, "FAKE_PRIVATE", {}, [], object(), threading.Event, EventSubclass()])
def test_invalid_cancellation_event_fails_before_spawn(monkeypatch, event):
    monkeypatch.setattr(core_evidence.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="^unsupported Core representation check request$"):
        check_evidence_representation(snapshot(), core_executable="/core", timeout_ms=100, cancel_event=event)


@pytest.mark.parametrize("size", [0, 1, 65536])
def test_cancel_after_spawn_reaps_direct_child(executable, monkeypatch, child_processes, size):
    event = threading.Event()
    launch = core_evidence.subprocess.Popen

    def launch_then_cancel(*args, **kwargs):
        process = launch(*args, **kwargs)
        event.set()
        return process

    monkeypatch.setattr(core_evidence.subprocess, "Popen", launch_then_cancel)
    cancelled(snapshot(b"x" * size), executable("import time\ntime.sleep(60)\n"), event)
    assert len(child_processes) == 1


@pytest.mark.parametrize("size", [0, 1, 65536])
def test_cancel_during_selector_wait_has_bounded_poll(executable, monkeypatch, child_processes, size):
    event = threading.Event()
    select = core_evidence.selectors.DefaultSelector.select
    waits = []

    def select_then_cancel(self, timeout):
        waits.append(timeout)
        events = select(self, timeout)
        event.set()
        return events

    monkeypatch.setattr(core_evidence.selectors.DefaultSelector, "select", select_then_cancel)
    cancelled(snapshot(b"x" * size), executable("import time\ntime.sleep(60)\n"), event)
    assert waits and all(0 < timeout <= 0.05 for timeout in waits)
    assert len(child_processes) == 1


@pytest.mark.parametrize("operation", ["read", "write"])
@pytest.mark.parametrize("size", [1, 4097, 65536])
def test_cancel_during_pipe_io_closes_pipes(executable, monkeypatch, child_processes, operation, size):
    event = threading.Event()
    original = getattr(core_evidence.os, operation)
    selector = core_evidence.selectors.DefaultSelector

    def io_then_cancel(*args):
        result = original(*args)
        event.set()
        return result

    class CancellingSelector(selector):
        def __enter__(self):
            monkeypatch.setattr(core_evidence.os, operation, io_then_cancel)
            return super().__enter__()

    monkeypatch.setattr(core_evidence.selectors, "DefaultSelector", CancellingSelector)
    cancelled(snapshot(b"x" * size), executable(report_script()), event)
    assert len(child_processes) == 1


def test_cancel_while_waiting_for_exit_is_not_held_until_deadline(executable, monkeypatch, child_processes):
    event = threading.Event()
    wait = subprocess.Popen.wait
    waits = []

    def wait_then_cancel(self, timeout):
        if self.poll() is None and not event.is_set():
            waits.append(timeout)
            try:
                return wait(self, timeout=timeout)
            except subprocess.TimeoutExpired:
                event.set()
                raise
        return wait(self, timeout=timeout)

    monkeypatch.setattr(core_evidence.subprocess.Popen, "wait", wait_then_cancel)
    script = "import os, time\nfor fd in (0, 1, 2):\n    os.close(fd)\ntime.sleep(60)\n"
    cancelled(snapshot(b""), executable(script), event)
    assert waits and all(0 < timeout <= 0.05 for timeout in waits)
    assert len(child_processes) == 1


@pytest.mark.parametrize("code", [0, 7])
def test_cancel_observed_at_exit_prevents_normal_result(executable, monkeypatch, child_processes, code):
    event = threading.Event()
    wait = subprocess.Popen.wait

    def wait_then_cancel(self, timeout):
        result = wait(self, timeout=timeout)
        event.set()
        return result

    monkeypatch.setattr(core_evidence.subprocess.Popen, "wait", wait_then_cancel)
    cancelled(snapshot(), executable(report_script(code=code)), event)
    assert len(child_processes) == 1


def test_cancel_between_handoff_and_decode_skips_json(executable, monkeypatch, child_processes):
    event = threading.Event()
    run_check = core_evidence._run_check

    def run_then_cancel(*args):
        result = run_check(*args)
        event.set()
        return result

    monkeypatch.setattr(core_evidence, "_run_check", run_then_cancel)
    monkeypatch.setattr(core_evidence.json, "loads", lambda *args, **kwargs: pytest.fail("decoded after cancellation"))
    cancelled(snapshot(), executable(report_script()), event)
    assert len(child_processes) == 1


def test_cancel_during_diagnostic_decode_prevents_normal_result(executable, monkeypatch, child_processes):
    event = threading.Event()
    loads = json.loads

    def decode_then_cancel(*args, **kwargs):
        result = loads(*args, **kwargs)
        event.set()
        return result

    monkeypatch.setattr(core_evidence.json, "loads", decode_then_cancel)
    cancelled(snapshot(), executable(report_script()), event)
    assert len(child_processes) == 1


@pytest.mark.parametrize("remaining", [0.001, 0.05, 0.1, 60.0])
@pytest.mark.parametrize("cancellable", [False, True])
def test_polling_keeps_original_deadline(monkeypatch, remaining, cancellable):
    monkeypatch.setattr(core_evidence.time, "monotonic", lambda: 100.0)
    event = threading.Event() if cancellable else None
    timeout = core_evidence._wait_timeout(100.0 + remaining, event)
    assert timeout == pytest.approx(min(remaining, 0.05) if cancellable else remaining)


@pytest.mark.parametrize("remaining", [0, -1, -60])
@pytest.mark.parametrize("cancellable", [False, True])
def test_polling_cannot_extend_expired_deadline(monkeypatch, remaining, cancellable):
    monkeypatch.setattr(core_evidence.time, "monotonic", lambda: 100.0)
    with pytest.raises(TimeoutError):
        core_evidence._wait_timeout(100.0 + remaining, threading.Event() if cancellable else None)


def test_host_owns_event_and_clears_it_only_between_calls(executable, child_processes):
    event = threading.Event()
    path = executable(report_script())
    output = snapshot()
    before = output.to_dict()
    event.set()
    cancelled(output, path, event)
    assert not child_processes
    event.clear()
    assert check_evidence_representation(output, core_executable=path, timeout_ms=2000, cancel_event=event) is None
    assert not event.is_set()
    event.set()
    cancelled(output, path, event)
    assert len(child_processes) == 1
    assert output.to_dict() == before and output.stdout == PRIVATE


@pytest.mark.parametrize("timeout_ms", [None, True, False, 0, -1, 1.5, "10", MAX_CHECK_TIMEOUT_MS + 1])
def test_invalid_timeout_fails_before_spawn(monkeypatch, timeout_ms):
    monkeypatch.setattr(core_evidence.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="^unsupported Core representation check request$"):
        check_evidence_representation(snapshot(), core_executable="/host/trusted/core", timeout_ms=timeout_ms)


@pytest.mark.parametrize("path", [None, False, Path("/core"), "", "mumei", "cargo run --", "/FAKE_PRIVATE\x00core"])
def test_invalid_executable_fails_before_spawn(monkeypatch, path):
    monkeypatch.setattr(core_evidence.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="^unsupported Core representation check request$"):
        check_evidence_representation(snapshot(), core_executable=path, timeout_ms=100)


@pytest.mark.parametrize("value", [None, {}, PRIVATE, "FAKE_PRIVATE", snapshot().attempt])
def test_only_exact_snapshots_are_accepted(monkeypatch, value):
    monkeypatch.setattr(core_evidence.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="^unsupported Core representation check request$"):
        check_evidence_representation(value, core_executable="/host/trusted/core", timeout_ms=100)


def test_unsupported_platform_fails_before_spawn(monkeypatch):
    monkeypatch.setattr(core_evidence.os, "name", "nt")
    monkeypatch.setattr(core_evidence.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="^unsupported Core representation check request$"):
        check_evidence_representation(snapshot(), core_executable="/host/trusted/core", timeout_ms=100)


def test_missing_and_nonexecutable_core_have_static_errors(tmp_path):
    path = tmp_path / "FAKE_PRIVATE_missing_core"
    failed(snapshot(), str(path))
    path.write_bytes(b"FAKE_PRIVATE_NOT_EXECUTABLE")
    failed(snapshot(), str(path))


def synthetic_evidence():
    return {
        "schema_version": "mumei.verification-evidence/v1",
        "subject": {"id": "synthetic-model", "kind": "model", "sha256": "0" * 64},
        "specification": {"id": "synthetic-spec", "sha256": "1" * 64},
        "obligation_id": "synthetic-obligation",
        "semantics": {"profile": "synthetic/v1", "integer_model": "mathematical_integer", "target_triple": None},
        "method": "deductive_proof", "execution": "completed", "result": "established",
        "scope": {"kind": "unbounded", "bounds": []},
        "correspondence": {"relation": "unchecked", "status": "unverified", "notes": []},
        "assumptions": [], "exclusions": ["Synthetic record, not proof or authenticity."],
        "provenance": {
            "adapter": {"id": "synthetic", "version": "fixture-only", "protocol_version": "fixture/v1"},
            "tool": {"name": "synthetic", "version": "not-run"},
            "configuration_fingerprint": "2" * 64,
        },
        "artifact_paths": ["FAKE_PRIVATE_NONEXISTENT_ARTIFACT"],
    }


@pytest.fixture
def real_core():
    path = os.environ.get("MUMEI_BIN")
    if not path or not Path(path).is_absolute() or not Path(path).is_file():
        pytest.skip("set MUMEI_BIN to an absolute trusted Core executable")
    return path


@pytest.mark.integration
@pytest.mark.parametrize("result", ["established", "counterexample", "unknown", "unsupported", "not_checked", "inconsistent"])
def test_real_core_checks_representation_not_stored_result_truth(real_core, result):
    evidence = synthetic_evidence()
    evidence["result"] = result
    output = snapshot(json.dumps(evidence, ensure_ascii=False).encode())
    assert check_evidence_representation(output, core_executable=real_core, timeout_ms=2000) is None


@pytest.mark.integration
def test_real_core_raw_encoding_duplicates_and_boundaries(real_core):
    evidence = synthetic_evidence()
    evidence["exclusions"].append("Synthetic scalar Unicode: 日本語")
    raw = json.dumps(evidence, ensure_ascii=False).encode()
    for body in [raw, raw + b" " * (65536 - len(raw))]:
        check_evidence_representation(snapshot(body), core_executable=real_core, timeout_ms=2000)
    for body in [
        b"", b"{}", b'{"success":true}', b"[]", b"\xff", b"\xef\xbb\xbf" + raw,
        raw + b"{}", raw[:-1] + b', "result": "established"}',
        raw.replace(b'"assumptions": []', b'"assumptions": ["\\ud800"]'), VALID,
    ]:
        failed(snapshot(body), real_core)
