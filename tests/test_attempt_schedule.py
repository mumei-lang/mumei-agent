import hashlib
import json
import sys
import threading

import pytest

from agent.attempt_runner import AttemptRunner
from agent.attempt_schedule import (
    MAX_SCHEDULE_ATTEMPTS,
    SCHEDULE_SCHEMA_VERSION,
    AttemptScheduleResult,
    run_attempt_schedule,
)
from agent.verification_planner import (
    AdapterDescriptor,
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
    RuntimeObservation,
    SOURCE_INPUT_FORMAT,
)

PY = sys.executable
SOURCE = b"FAKE_PRIVATE_SOURCE_NOT_EVIDENCE"
PROFILE = "mumei.test/v1"
CONTRACT = ResultContract(
    PROFILE, "deductive_proof", "unbounded", "mumei.source-model/v1", "assumed"
)


def argv(code):
    return (PY, "-c", f"import sys; sys.exit({code})")


def descriptor(adapter_id, priority=0, **overrides):
    return AdapterDescriptor(
        adapter_id,
        "1.0.0",
        frozenset({PROFILE}),
        frozenset({CONTRACT.method}),
        priority=priority,
        result_contracts=(CONTRACT,),
        input_formats=frozenset({SOURCE_INPUT_FORMAT}),
        required_permissions=frozenset(),
        **overrides,
    )


def registry_with(*ids):
    registry = AdapterRegistry()
    for adapter_id in ids:
        registry.register(descriptor(adapter_id, priority=0))
    return registry


def request():
    return RouteRequirements(
        PROFILE,
        CONTRACT.method,
        result_contract=CONTRACT,
        input_format=SOURCE_INPUT_FORMAT,
    )


def policy(**kwargs):
    kwargs.setdefault("allowed_permissions", frozenset())
    kwargs.setdefault("timeout_ms", 10_000)
    return PlannerPolicy(**kwargs)


def observations(*ids):
    return tuple(
        RuntimeObservation(adapter_id, "available", "1.0.0", stamp=index + 1)
        for index, adapter_id in enumerate(ids)
    )


def schedule(registry, ids, argv_map, **kwargs):
    kwargs.setdefault("observations", observations(*ids))
    return run_attempt_schedule(
        registry,
        request(),
        kwargs.pop("policy", policy()),
        SOURCE,
        hashlib.sha256(SOURCE).hexdigest(),
        lambda adapter_id: argv_map.get(adapter_id),
        **kwargs,
    )


def test_first_adapter_success_selects_without_fallback():
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"alpha": argv(0), "beta": argv(0)})
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "alpha"
    assert len(result.entries) == 1
    assert result.entries[0].terminal_state == "exited"
    assert result.entries[0].exit_code == 0
    doc = result.to_dict()
    assert doc["schema_version"] == SCHEDULE_SCHEMA_VERSION
    assert SOURCE.decode() not in json.dumps(doc) + repr(result)


def test_failed_exit_falls_back_to_next_adapter():
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"alpha": argv(3), "beta": argv(0)})
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert [e.adapter_id for e in result.entries] == ["alpha", "beta"]
    assert result.entries[0].terminal_state == "exited"
    assert result.entries[0].exit_code == 3
    assert len(result.plans) == 2
    assert result.plans[1].fallback_from is None or result.plans[1].selected.adapter_id == "beta"
    # Each adapter attempt is its own reconciled sequence.
    assert len(result.sequences) == 2
    assert result.sequences[0].current.state == "exited"


def test_spawn_failure_and_timeout_fall_back():
    registry = registry_with("gone", "slow", "third")
    argvs = {
        "gone": ("definitely-missing-mumei-argv-target-xyz",),
        "slow": (PY, "-c", "import time; time.sleep(30)"),
        "third": argv(0),
    }
    result = schedule(
        registry,
        ("gone", "slow", "third"),
        argvs,
        policy=policy(timeout_ms=200),
    )
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "third"
    assert result.entries[0].terminal_state == "failed"
    assert result.entries[1].terminal_state == "timed_out"
    assert result.entries[2].terminal_state == "exited"


def test_all_candidates_fail_reports_exhausted():
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"alpha": argv(1), "beta": argv(2)})
    assert result.outcome == "exhausted"
    assert result.selected_adapter_id is None
    assert len(result.entries) == 2


def test_max_attempts_bounds_the_schedule():
    registry = registry_with(*(f"a{i}" for i in range(MAX_SCHEDULE_ATTEMPTS + 2)))
    argvs = {f"a{i}": argv(1) for i in range(MAX_SCHEDULE_ATTEMPTS + 2)}
    result = schedule(
        registry,
        tuple(argvs),
        argvs,
        max_attempts=3,
    )
    assert result.outcome == "exhausted"
    assert len(result.entries) == 3
    assert len(result.plans) == 3


def test_explicit_selection_without_fallback_denies_replan():
    registry = registry_with("alpha", "beta")
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": argv(1), "beta": argv(0)},
        policy=policy(selected_adapter="alpha"),
    )
    assert result.outcome == "fallback_denied"
    assert result.fallback_permitted is False
    assert len(result.entries) == 1


def test_explicit_selection_with_fallback_replans():
    registry = registry_with("alpha", "beta")
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": argv(1), "beta": argv(0)},
        policy=policy(selected_adapter="alpha", allow_fallback=True),
    )
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"


def test_no_selected_adapter_reports_not_schedulable():
    registry = AdapterRegistry()
    registry.register(descriptor("other"))
    result = run_attempt_schedule(
        registry,
        request(),
        policy(),
        SOURCE,
        hashlib.sha256(SOURCE).hexdigest(),
        lambda adapter_id: argv(0),
        observations=(),  # no availability declared → nothing eligible
    )
    assert result.outcome == "not_schedulable"
    assert result.entries == ()


def test_undeclared_argv_records_not_dispatched_and_falls_back():
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"beta": argv(0)})
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert result.entries[0].terminal_state == "not_dispatched"
    assert result.entries[0].request_fingerprint is None
    # No argv → nothing was ever reserved, so no sequence exists for it.
    assert len(result.sequences) == 1


def test_unstamped_observations_still_fall_back():
    # Unstamped declarations are not retained by the registry's stamped
    # record — the schedule must replay the caller's tuple at replan.
    registry = registry_with("alpha", "beta")
    unstamped = tuple(
        RuntimeObservation(adapter_id, "available", "1.0.0")
        for adapter_id in ("alpha", "beta")
    )
    result = run_attempt_schedule(
        registry, request(), policy(), SOURCE,
        hashlib.sha256(SOURCE).hexdigest(),
        lambda adapter_id: {"alpha": argv(1), "beta": argv(0)}.get(adapter_id),
        observations=unstamped,
    )
    assert result.outcome == "selected"
    assert result.selected_adapter_id == "beta"
    assert [e.adapter_id for e in result.entries] == ["alpha", "beta"]


def test_cancel_event_stops_not_dispatched_rounds_too():
    registry = registry_with("alpha", "beta")
    event = threading.Event()
    event.set()
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"beta": argv(0)},  # alpha has no declared argv
        cancel_event=event,
    )
    assert result.outcome == "cancelled"
    assert result.entries == ()
    assert len(result.plans) == 1


def test_cancel_event_stops_schedule_without_fallback():
    registry = registry_with("alpha", "beta")
    event = threading.Event()
    event.set()
    result = schedule(
        registry,
        ("alpha", "beta"),
        {"alpha": argv(0), "beta": argv(0)},
        cancel_event=event,
    )
    # A pre-declared stop holds before the first spawn: nothing was ever
    # attempted, so no entry is recorded.
    assert result.outcome == "cancelled"
    assert result.entries == ()


def test_cancel_event_mid_run_records_killed_child_and_stops():
    registry = registry_with("alpha", "beta")
    event = threading.Event()
    timer = threading.Timer(0.3, event.set)
    timer.start()
    try:
        result = schedule(
            registry,
            ("alpha", "beta"),
            {"alpha": (PY, "-c", "import time; time.sleep(30)"), "beta": argv(0)},
            cancel_event=event,
        )
    finally:
        timer.cancel()
    # The record honestly reports the killed child as `exited`; the
    # schedule outcome is what names the host's stop decision.
    assert result.outcome == "cancelled"
    assert result.entries[-1].terminal_state in {"exited", "cancelled"}
    assert len(result.entries) == 1


def test_success_exit_codes_are_host_declared():
    registry = registry_with("alpha")
    result = schedule(
        registry,
        ("alpha",),
        {"alpha": argv(7)},
        success_exit_codes=frozenset({7}),
    )
    assert result.outcome == "selected"
    # And a default policy treats the same exit as failure.
    registry2 = registry_with("alpha")
    result2 = schedule(registry2, ("alpha",), {"alpha": argv(7)})
    assert result2.outcome == "exhausted"


def test_static_rejections():
    registry = registry_with("alpha")
    sha = hashlib.sha256(SOURCE).hexdigest()
    for bad in (
        lambda: run_attempt_schedule(None, request(), policy(), SOURCE, sha, lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, "x", policy(), SOURCE, sha, lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, request(), None, SOURCE, sha, lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, request(), policy(), b"", sha, lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, "z" * 64, lambda a: argv(0), observations=observations("alpha")),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha.upper(), lambda a: argv(0)),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, "echo"),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), runner=object()),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), observations=[]),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), max_attempts=0),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), max_attempts=MAX_SCHEDULE_ATTEMPTS + 1),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), max_attempts="3"),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), success_exit_codes={0}),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), success_exit_codes=frozenset({"0"})),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), cancel_event=object()),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), stdin_for="x"),
        lambda: run_attempt_schedule(registry, request(), policy(), SOURCE, sha, lambda a: argv(0), stdin_for=lambda a: "not-bytes", observations=observations("alpha")),
    ):
        with pytest.raises(ValueError):
            bad()


def test_result_declaration_rules():
    registry = registry_with("alpha")
    result = schedule(registry, ("alpha",), {"alpha": argv(0)})
    with pytest.raises(ValueError, match="invalid schedule outcome"):
        AttemptScheduleResult(
            result.entries, result.plans, result.sequences, "alpha", "bogus", True, 1
        )
    with pytest.raises(ValueError, match="a selected schedule must name its adapter"):
        AttemptScheduleResult(
            result.entries, result.plans, result.sequences, None, "selected", True, 1
        )
    with pytest.raises(ValueError, match="exceed the declared bound"):
        AttemptScheduleResult(
            result.entries * 2, result.plans, result.sequences, "alpha", "selected", True, 1
        )


def test_descriptor_stays_fingerprint_only(capsys):
    registry = registry_with("alpha", "beta")
    result = schedule(registry, ("alpha", "beta"), {"alpha": argv(9), "beta": argv(0)})
    doc = result.to_dict()
    text = json.dumps(doc) + repr(result)
    assert "FAKE_PRIVATE" not in text
    assert SOURCE.decode() not in text
    assert PY not in text
    # Request fingerprints bind each attempt to its prepared request.
    assert all(
        len(entry["request_fingerprint"]) == 64
        for entry in doc["attempts"]
        if entry["request_fingerprint"] is not None
    )


def _argv_spew(text, code=0):
    return (
        PY,
        "-c",
        f"import sys; sys.stdout.write({text!r}); sys.exit({code})",
    )


def test_verdict_marker_reports_declared_outcome():
    from agent.verification_planner import VerdictMarker

    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            "alpha",
            "1.0.0",
            frozenset({PROFILE}),
            frozenset({CONTRACT.method}),
            priority=0,
            result_contracts=(CONTRACT,),
            input_formats=frozenset({SOURCE_INPUT_FORMAT}),
            required_permissions=frozenset(),
            verdict_markers=(
                VerdictMarker("stdout", "VERIFIED", "valid"),
                VerdictMarker("stdout", "REFUTED", "failed"),
            ),
        )
    )
    result = schedule(
        registry, ["alpha"], {"alpha": _argv_spew("REFUTED\n")}
    )
    entry = result.entries[0]
    assert entry.terminal_state == "exited"
    assert entry.reported_outcome == "failed"


def test_verdict_marker_first_match_wins_and_no_match_is_null():
    from agent.verification_planner import VerdictMarker

    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            "alpha",
            "1.0.0",
            frozenset({PROFILE}),
            frozenset({CONTRACT.method}),
            priority=0,
            result_contracts=(CONTRACT,),
            input_formats=frozenset({SOURCE_INPUT_FORMAT}),
            required_permissions=frozenset(),
            verdict_markers=(
                VerdictMarker("stdout", "OK", "valid"),
                VerdictMarker("stdout", "OKAY", "failed"),
            ),
        )
    )
    matched = schedule(
        registry, ["alpha"], {"alpha": _argv_spew("OKAY")}
    )
    assert matched.entries[0].reported_outcome == "valid"

    quiet = schedule(
        registry, ["alpha"], {"alpha": _argv_spew("nothing here")}
    )
    assert quiet.entries[0].reported_outcome is None


def test_verdict_marker_stderr_stream():
    from agent.verification_planner import VerdictMarker

    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            "alpha",
            "1.0.0",
            frozenset({PROFILE}),
            frozenset({CONTRACT.method}),
            priority=0,
            result_contracts=(CONTRACT,),
            input_formats=frozenset({SOURCE_INPUT_FORMAT}),
            required_permissions=frozenset(),
            verdict_markers=(
                VerdictMarker("stderr", "UNSAT", "failed"),
            ),
        )
    )
    argv_err = (
        PY,
        "-c",
        "import sys; sys.stderr.write('UNSAT'); sys.exit(0)",
    )
    result = schedule(registry, ["alpha"], {"alpha": argv_err})
    assert result.entries[0].reported_outcome == "failed"


def test_verdict_marker_validation():
    from agent.verification_planner import VerdictMarker

    import pytest as _pytest

    with _pytest.raises(ValueError):
        VerdictMarker("stdin", "x", "valid")
    with _pytest.raises(ValueError):
        VerdictMarker("stdout", "", "valid")
    with _pytest.raises(ValueError):
        VerdictMarker("stdout", "x", "bogus")
    with _pytest.raises(ValueError):
        AdapterDescriptor.from_manifest(
            {
                "schema_version": "mumei.verifier-adapter/v1",
                "adapter_id": "alpha",
                "adapter_version": "1.0.0",
                "profiles": [PROFILE],
                "methods": ["deductive_proof"],
                "verdict_markers": [{"stream": "stdout"}],
            }
        )

def test_stdin_for_feeds_the_attempt_process():
    # A byte probe exits 0 only when the declared payload reaches stdin.
    registry = registry_with("alpha")
    probe = (
        PY,
        "-c",
        "import sys;"
        "sys.exit(0 if sys.stdin.buffer.read() == b'FEED' else 3)",
    )
    fed = schedule(
        registry,
        ("alpha",),
        {"alpha": probe},
        stdin_for=lambda adapter_id: b"FEED",
    )
    assert fed.outcome == "selected"
    unfed = schedule(registry, ("alpha",), {"alpha": probe})
    assert unfed.outcome == "exhausted"


def test_no_feed_closes_stdin_instead_of_inheriting():
    # With no declared feed the child's stdin is a closed pipe — the
    # probe sees EOF immediately rather than inheriting the parent's.
    registry = registry_with("alpha")
    probe = (
        PY,
        "-c",
        "import sys;"
        "sys.exit(0 if sys.stdin.buffer.read() == b'' else 5)",
    )
    result = schedule(registry, ("alpha",), {"alpha": probe})
    assert result.outcome == "selected"
||||||| parent of 1a617047 (C11: manifest max_memory_mb is the scheduled attempt ceiling when the host declares none)
=======


def test_manifest_memory_bound_caps_the_attempt():
    # With no host ``memory_bound_mb`` the adapter's declared
    # ``max_memory_mb`` is the child's ceiling: a probe that allocates
    # past it fails instead of running unbounded.
    registry = AdapterRegistry()
    registry.register(descriptor("alpha", max_memory_mb=64))
    probe = (PY, "-c", "x = bytearray(256 * 1024 * 1024); import sys; sys.exit(0)")
    result = schedule(registry, ("alpha",), {"alpha": probe})
    assert result.outcome != "selected"
    assert result.entries[0].terminal_state in {"exited", "failed", "timed_out"}
    # The host's declared bound wins over the manifest's.
    result2 = schedule(
        registry, ("alpha",), {"alpha": probe}, memory_bound_mb=1024
    )
    assert result2.outcome == "selected"
