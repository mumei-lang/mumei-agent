"""End-to-end composition of the declared C11 boundaries.

Each boundary was delivered behind its own static gate; these tests
drive the whole declared chain — manifest → probe request → observed
outcome → planning → attempt lineage → dispatch → captured output →
selection → evidence candidate → detached snapshots — so a regression
in any composition fails one test, not five separate ones. Nothing
here asserts acceptance: every value remains a host declaration.
"""

import hashlib
import sys

import pytest

from agent.adapter_probe import (
    AdapterProbeHistory,
    observe_probes,
    plan_with_probes,
    probe_request_for,
    probe_retry_requests,
    run_probe,
)
from agent.attempt_runner import (
    AttemptRunner,
    dispatch_and_publish,
)
from agent.verification_attempt import (
    AttemptSequence,
    AttemptSequenceStore,
)
from agent.verification_planner import (
    PROTOCOL_VERSION,
    AdapterDescriptor,
    AdapterRegistry,
    PlannerPolicy,
    RouteRequirements,
)

FINGERPRINT = "a" * 64
ADAPTER_ID = "zendingsol.host.lifecycle_fake"
PROFILE = "zendingsol.host.lifecycle_fake/v0"


def _manifest(**kw):
    base = {
        "schema_version": PROTOCOL_VERSION,
        "adapter_id": ADAPTER_ID,
        "adapter_version": "0.1.0",
        "profiles": [PROFILE],
        "methods": ["deductive_proof"],
        "max_timeout_ms": 30_000,
        "max_memory_mb": 256,
        "probe_argv": [sys.executable, "-c", "import sys; sys.exit(0)"],
    }
    base.update(kw)
    return base


def _registry(**kw):
    registry = AdapterRegistry()
    registry.register(AdapterDescriptor.from_manifest(_manifest(**kw)))
    return registry


def _request():
    return RouteRequirements(PROFILE, "deductive_proof", frozenset())


def test_manifest_probe_plan_dispatch_publish_composes():
    registry = _registry()
    descriptor = registry.descriptor(ADAPTER_ID)
    assert descriptor is not None

    # Manifest-declared probe → observed outcome → plan selects.
    probe = probe_request_for(descriptor, stamp=1, tool_version="0.1.0")
    observations = observe_probes((probe,))
    assert len(observations) == 1
    assert observations[0].availability == "available"
    plan = registry.plan(
        _request(), PlannerPolicy(), observations
    )
    assert plan.selected is not None

    # Attempt lineage → dispatch-and-publish → captured output →
    # canonical selection → evidence candidate.
    store = AttemptSequenceStore()
    store.publish(AttemptSequence(FINGERPRINT, 10_000))
    dispatch = dispatch_and_publish(
        store,
        (sys.executable, "-c", "import sys; sys.stdout.write('ok')"),
    )
    lineage = store.current
    assert lineage.selected_result is not None
    output = dispatch.captured_output()
    assert lineage.selected_result[1] == output.to_dict()[
        "output_fingerprint"
    ]
    candidate = lineage.evidence_candidate()
    assert candidate.request_fingerprint == FINGERPRINT
    assert candidate.attempt_number == 1
    assert candidate.output_fingerprint == lineage.selected_result[1]

    # Detached snapshots round-trip the declared metadata only.
    normalized = dispatch.run.normalized()
    assert normalized.outcome == "exited"
    data = lineage.to_dict()
    assert data["schema_version"] == "mumei.verifier-attempt-sequence/v1"
    assert data["selected_result"]["output_fingerprint"] == (
        candidate.output_fingerprint
    )


def test_probe_history_composes_with_retry_scheduling():
    descriptor = _registry().descriptor(ADAPTER_ID)
    probe = probe_request_for(descriptor, stamp=1, tool_version="0.1.0")
    outcome = run_probe(probe)

    history = AdapterProbeHistory.start(probe)
    history = history.record(probe, outcome)
    assert history.attempt_count == 1

    # The recorded history schedules the next ordinal, not a replay.
    registry = _registry()
    retries = probe_retry_requests(
        registry, _request(), PlannerPolicy(),
        (outcome.observation,), (history,),
        stamp=2, tool_version="0.1.0",
    )
    assert retries == ()

    # An adapter still excluded by observation gets the next ordinal.
    registry = _registry(
        probe_argv=[sys.executable, "-c", "import sys; sys.exit(3)"]
    )
    missing = _registry(
        probe_argv=[sys.executable, "-c", "import sys; sys.exit(3)"]
    ).descriptor(ADAPTER_ID)
    miss_probe = probe_request_for(missing, stamp=1, tool_version="0.1.0")
    miss_outcome = run_probe(miss_probe)
    miss_history = AdapterProbeHistory.start(miss_probe).record(
        miss_probe, miss_outcome
    )
    retries = probe_retry_requests(
        registry, _request(), PlannerPolicy(),
        (miss_outcome.observation,), (miss_history,),
        stamp=2, tool_version="0.1.0",
    )
    assert len(retries) == 1
    assert retries[0].attempt_number == 2
    assert retries[0].command_fingerprint() == miss_probe.command_fingerprint()


def test_plan_with_probes_runs_the_full_observe_replan_loop():
    registry = _registry()
    plan = plan_with_probes(
        registry, _request(), PlannerPolicy(), stamp=1,
        tool_version="0.1.0",
    )
    assert plan.plan.selected is not None
    history = next(
        h for h in plan.histories if h.adapter_id == ADAPTER_ID
    )
    assert history.attempt_count >= 1


def test_missing_probe_excludes_candidate_without_substitution():
    registry = _registry(
        probe_argv=[sys.executable, "-c", "import sys; sys.exit(3)"]
    )
    plan = plan_with_probes(
        registry, _request(), PlannerPolicy(), stamp=1
    )
    assert plan.plan.selected is None
