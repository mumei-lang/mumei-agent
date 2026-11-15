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
from pathlib import Path

from agent.go_interprocedural import PROFILE as GO_SUMMARY_PROFILE
from agent.rust_interprocedural import PROFILE as RUST_SUMMARY_PROFILE
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


def rust_summaries_adapter() -> AdapterDescriptor:
    """The declared descriptor for the `rust-summaries` produce route.

    Unlike `go-summaries` the route is fully in-process (tree-sitter),
    so it declares only `filesystem.read` — the `process.spawn` in its
    `probe_argv` belongs to the C11 probe boundary, not the route.
    """
    return AdapterDescriptor(
        adapter_id="agent.rust-summaries",
        adapter_version="1.0.0",
        profiles=frozenset({RUST_SUMMARY_PROFILE}),
        methods=frozenset({SUMMARY_DERIVATION}),
        input_formats=frozenset({SOURCE_INPUT_FORMAT}),
        required_permissions=frozenset({"filesystem.read"}),
        result_contracts=(
            summary_requirements(RUST_SUMMARY_PROFILE).result_contract,
        ),
        probe_argv=(
            sys.executable,
            "-m",
            "agent",
            "rust-summaries",
            "--help",
        ),
    )


def summary_descriptors() -> tuple[AdapterDescriptor, ...]:
    """Every declared summary-route descriptor, in registry order."""
    return (go_summaries_adapter(), rust_summaries_adapter())


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


PLAN_PROFILE = "mumei.summaries-plan/v1"


def build_plan_parser(parser):
    """Arguments for the ``summaries-plan`` route."""
    parser.add_argument(
        "--profile",
        required=True,
        help=(
            "Summary-derivation profile to plan for (for example "
            f"{GO_SUMMARY_PROFILE})."
        ),
    )
    parser.add_argument(
        "--stamp",
        type=int,
        required=True,
        help=(
            "Host-assigned monotonically increasing base stamp for the "
            "probe observations this pass records; a resumed retry "
            "records base stamp + its previous attempt count."
        ),
    )
    parser.add_argument(
        "--tool-version",
        default=None,
        help="Optional declared tool version the planner pins against.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="Maximum observe-and-replan rounds (default 1).",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=1,
        help="Maximum probes run concurrently per round (default 1).",
    )
    parser.add_argument(
        "--histories",
        default=None,
        metavar="PATH",
        help=(
            "Optional JSON array of persisted "
            "mumei.adapter-probe-history/v1 records this pass resumes."
        ),
    )
    return parser


def main_plan(args=None, *, runner=None) -> int:
    """Plan a summary route through the declared probe boundary.

    Emits ``mumei.summaries-plan/v1``: the resulting
    ``mumei.verification-plan/v1`` document, the probe observations this
    pass recorded and the updated probe histories the host persists to
    schedule retries. Routing only — no summary is derived, and a
    selected adapter is a routing decision, not an accepted manifest.
    """
    import argparse
    import json

    if args is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent summaries-plan",
            description=(
                "Plan the summary-derivation route for a declared "
                "profile through the C11 probe boundary and print the "
                "plan JSON."
            ),
        )
        build_plan_parser(parser)
        args = parser.parse_args()
    histories = ()
    if args.histories is not None:
        from agent.adapter_probe import AdapterProbeHistory

        try:
            declared = json.loads(
                Path(args.histories).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"summaries-plan: {exc}", file=sys.stderr)
            sys.exit(1)
        if type(declared) is not list:
            print(
                "summaries-plan: histories file must be a JSON array",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            histories = tuple(
                AdapterProbeHistory.from_dict(record) for record in declared
            )
        except ValueError as exc:
            print(f"summaries-plan: {exc}", file=sys.stderr)
            sys.exit(1)
    try:
        probe_plan = plan_summary_route(
            args.profile,
            PlannerPolicy(),
            stamp=args.stamp,
            tool_version=args.tool_version,
            histories=histories,
            rounds=args.rounds,
            max_parallel=args.max_parallel,
            runner=runner,
        )
    except (ValueError, OSError) as exc:
        print(f"summaries-plan: {exc}", file=sys.stderr)
        sys.exit(1)
    document = (
        json.dumps(
            {
                "schema_version": PLAN_PROFILE,
                "profile": args.profile,
                "plan": probe_plan.plan.to_dict(),
                "observations": [
                    {
                        "adapter_id": observation.adapter_id,
                        "availability": observation.availability,
                        "tool_version": observation.tool_version,
                        "stamp": observation.stamp,
                    }
                    for observation in probe_plan.observations
                ],
                "histories": [
                    history.to_dict() for history in probe_plan.histories
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    sys.stdout.write(document)
    return 0
