"""Declared adapter descriptors for the summary-derivation routes.

`summary_derivation` extends the planner's method vocabulary: deriving a
dependency-summary manifest is an evidence method distinct from every
verification method the planner already knows, so the `<lang>-summaries`
routes can be registered adapters rather than unreachable CLI endpoints.

A descriptor is routing metadata only: registering it does not spawn a
process, derive a summary or accept a manifest — the host still runs the
route itself and owns every acceptance decision. The declared
`probe_argv` merely gives the C11 probe boundary an availability check.
"""

import sys

from agent.go_interprocedural import PROFILE as GO_SUMMARY_PROFILE
from agent.verification_planner import (
    SOURCE_INPUT_FORMAT,
    AdapterDescriptor,
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
)

SUMMARY_DERIVATION = "summary_derivation"

# The declared bound and relation identifiers: a derivation is bounded
# by exactly the inputs the request declares, and the emitted manifest
# is a conservative report the host assumes until Evidence acceptance
# closes it — never validated by the adapter itself.
_DECLARED_INPUT_BOUND = "declared-inputs"
_CONSERVATIVE_SUMMARY = "conservative-summary"


def summary_requirements(profile: str) -> RouteRequirements:
    """The capability query a summary-derivation adapter satisfies."""
    return RouteRequirements(
        profile,
        SUMMARY_DERIVATION,
        result_contract=ResultContract(
            profile=profile,
            method=SUMMARY_DERIVATION,
            scope="bounded",
            bounds=frozenset({_DECLARED_INPUT_BOUND}),
            correspondence_relation=_CONSERVATIVE_SUMMARY,
            correspondence_status="assumed",
        ),
        input_format=SOURCE_INPUT_FORMAT,
    )


def go_summaries_adapter() -> AdapterDescriptor:
    """The declared descriptor for the `go-summaries` produce route."""
    return AdapterDescriptor(
        adapter_id="agent.go-summaries",
        adapter_version="1.0.0",
        profiles=frozenset({GO_SUMMARY_PROFILE}),
        methods=frozenset({SUMMARY_DERIVATION}),
        input_formats=frozenset({SOURCE_INPUT_FORMAT}),
        required_permissions=frozenset(
            {"filesystem.read", "process.spawn"}
        ),
        result_contracts=(
            summary_requirements(GO_SUMMARY_PROFILE).result_contract,
        ),
        probe_argv=(
            sys.executable,
            "-m",
            "agent",
            "go-summaries",
            "--help",
        ),
    )


def summary_descriptors() -> tuple[AdapterDescriptor, ...]:
    """Every declared summary-route descriptor, in registry order."""
    return (go_summaries_adapter(),)


def summary_registry() -> AdapterRegistry:
    """A registry holding every declared summary-route descriptor."""
    registry = AdapterRegistry()
    for descriptor in summary_descriptors():
        registry.register(descriptor)
    return registry


def plan_summary_route(
    profile: str,
    policy: PlannerPolicy,
    *,
    stamp: int,
    tool_version: str | None = None,
    histories: tuple = (),
    rounds: int = 1,
    max_parallel: int = 1,
    cancel_event=None,
    runner=None,
):
    """Plan the summary route for `profile` through the probe boundary.

    Composes `summary_registry()` with `plan_with_probes`: an adapter
    excluded only because its availability or version was never
    observed gets its declared `probe_argv` run through `AttemptRunner`
    and is re-planned with the fresh observation. Returns the
    `AdapterProbePlan` — selected candidate (when probing cleared the
    exclusion), the observations and the updated probe histories the
    caller persists to schedule retries. Selecting is routing only:
    nothing here runs the route or accepts a manifest.
    """
    from agent.adapter_probe import plan_with_probes

    return plan_with_probes(
        summary_registry(),
        summary_requirements(profile),
        policy,
        stamp=stamp,
        tool_version=tool_version,
        runner=runner,
        cancel_event=cancel_event,
        rounds=rounds,
        max_parallel=max_parallel,
        histories=histories,
    )
