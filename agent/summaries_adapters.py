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
from agent.ts_interprocedural import PROFILE as TS_SUMMARY_PROFILE
from agent.sol_interprocedural import PROFILE as SOL_SUMMARY_PROFILE
from agent.verification_planner import (
    SOURCE_INPUT_FORMAT,
    AdapterDescriptor,
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
)

SUMMARY_DERIVATION = "summary_derivation"
_SUMMARY_ALLOWED_PERMISSIONS = frozenset(
    {"filesystem.read", "process.spawn"}
)

# The declared bound and relation identifiers: a derivation is bounded
# by exactly the inputs the request declares, and the emitted manifest
# is a conservative report the host assumes until Evidence acceptance
# closes it — never validated by the adapter itself.
_DECLARED_INPUT_BOUND = "declared-inputs"
_CONSERVATIVE_SUMMARY = "conservative-summary"


def summary_planner_policy() -> PlannerPolicy:
    """Allow the permissions declared by the built-in summary routes."""
    return PlannerPolicy(allowed_permissions=_SUMMARY_ALLOWED_PERMISSIONS)


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


def ts_summaries_adapter() -> AdapterDescriptor:
    """The declared descriptor for the `ts-summaries` produce route.

    Fully in-process (tree-sitter): declares only `filesystem.read` —
    the `process.spawn` in its `probe_argv` belongs to the C11 probe
    boundary, not the route.
    """
    return AdapterDescriptor(
        adapter_id="agent.ts-summaries",
        adapter_version="1.0.0",
        profiles=frozenset({TS_SUMMARY_PROFILE}),
        methods=frozenset({SUMMARY_DERIVATION}),
        input_formats=frozenset({SOURCE_INPUT_FORMAT}),
        required_permissions=frozenset({"filesystem.read"}),
        result_contracts=(
            summary_requirements(TS_SUMMARY_PROFILE).result_contract,
        ),
        probe_argv=(
            sys.executable,
            "-m",
            "agent",
            "ts-summaries",
            "--help",
        ),
    )


def sol_summaries_adapter() -> AdapterDescriptor:
    """The declared descriptor for the `sol-summaries` produce route.

    Fully in-process (tree-sitter): declares only `filesystem.read` —
    the `process.spawn` in its `probe_argv` belongs to the C11 probe
    boundary, not the route.
    """
    return AdapterDescriptor(
        adapter_id="agent.sol-summaries",
        adapter_version="1.0.0",
        profiles=frozenset({SOL_SUMMARY_PROFILE}),
        methods=frozenset({SUMMARY_DERIVATION}),
        input_formats=frozenset({SOURCE_INPUT_FORMAT}),
        required_permissions=frozenset({"filesystem.read"}),
        result_contracts=(
            summary_requirements(SOL_SUMMARY_PROFILE).result_contract,
        ),
        probe_argv=(
            sys.executable,
            "-m",
            "agent",
            "sol-summaries",
            "--help",
        ),
    )


def summary_descriptors() -> tuple[AdapterDescriptor, ...]:
    """Every declared summary-route descriptor, in registry order."""
    return (
        go_summaries_adapter(),
        rust_summaries_adapter(),
        sol_summaries_adapter(),
        ts_summaries_adapter(),
    )


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
            "mumei.adapter-probe-history records this pass resumes "
            "(v1 records restore with undeclared outcome stamps; "
            "v2 records carry them)."
        ),
    )
    return parser


def run_plan(args, *, runner=None) -> dict:
    """Plan a summary route and return the ``mumei.summaries-plan/v1`` dict.

    Shared by the CLI entrypoint and the ``summaries_plan`` MCP tool so
    both bind the same declared request: histories are restored from the
    declared file, `plan_summary_route` drives the probes and the
    emitted document is identical. Declared failures raise —
    `(OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError)` —
    rather than exiting, so callers choose their own error surface.
    """
    probe_plan = plan_summary_route(
        args.profile,
        summary_planner_policy(),
        stamp=args.stamp,
        tool_version=args.tool_version,
        histories=load_plan_histories(args.histories),
        rounds=args.rounds,
        max_parallel=args.max_parallel,
        runner=runner,
    )
    return build_plan_document(args.profile, probe_plan)


def load_plan_histories(path) -> tuple:
    """Restore the declared ``mumei.adapter-probe-history`` JSON array.

    Shared by the ``summaries-plan`` CLI and the audit
    ``--enable-summary-plan`` wiring so both bind the same history
    records. Raises ``(OSError, ValueError, UnicodeDecodeError,
    json.JSONDecodeError)`` on a declared failure.
    """
    import json

    if path is None:
        return ()
    from agent.adapter_probe import AdapterProbeHistory

    declared = json.loads(Path(path).read_text(encoding="utf-8"))
    if type(declared) is not list:
        raise ValueError("histories file must be a JSON array")
    return tuple(
        AdapterProbeHistory.from_dict(record) for record in declared
    )


def build_plan_document(profile: str, probe_plan) -> dict:
    """Serialize an ``AdapterProbePlan`` as ``mumei.summaries-plan/v1``.

    Shared by ``run_plan`` and the audit ``--enable-summary-plan``
    wiring so both surfaces emit the identical document shape.
    """
    from agent.adapter_probe import evaluate_probe_history

    return {
        "schema_version": PLAN_PROFILE,
        "profile": profile,
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
        "evaluations": [
            evaluate_probe_history(history)
            for history in probe_plan.histories
        ],
    }


def main_plan(args=None, *, runner=None) -> int:
    """Plan a summary route through the declared probe boundary.

    Emits ``mumei.summaries-plan/v1``: the resulting
    ``mumei.verification-plan/v1`` document, the probe observations this
    pass recorded, the updated probe histories the host persists to
    schedule retries, and a `mumei.probe-history-evaluation/v1`
    descriptor per history. Routing only — no summary is derived, and a
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
    try:
        document = run_plan(args, runner=runner)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"summaries-plan: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return 0
