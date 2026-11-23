"""C11 consumable attempt-schedule route (verify-schedule).

`python -m agent verify-schedule` binds declared adapter manifests, a
declared planner policy and a declared argv map to
`run_attempt_schedule`: the declared plan→dispatch→observe→fallback loop
over a bounded source, emitting `mumei.attempt-schedule/v1`.

Every input is a host-declared document or path: manifests are parsed
statically, the argv map names each adapter's declared command (an
adapter without one is recorded `not_dispatched`, never spawned), and
observations are declared availability claims — the route probes nothing.
The schedule doc is a dispatch record, not an Evidence acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from agent.attempt_schedule import (
    MAX_SCHEDULE_ATTEMPTS,
    AttemptScheduleResult,
    run_attempt_schedule,
)
from agent.plan_history_log import (
    append_plan_histories,
    append_plan_history,
    read_plan_history,
)
from agent.verification_planner import (
    SOURCE_INPUT_FORMAT,
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
    RuntimeObservation,
    VerificationPlan,
)

MAX_INPUT_BYTES = 1 << 20
_REQUEST_KEYS = frozenset(
    {"profile", "method", "logic_fragments", "target_triple", "result_contract", "input_format"}
)
_CONTRACT_KEYS = frozenset(
    {"profile", "method", "scope", "correspondence_relation", "correspondence_status",
     "bounds", "assumptions"}
)
_POLICY_KEYS = frozenset(
    {"selected_adapter", "allow_fallback", "disabled_adapters", "allowed_locations",
     "tool_version_pins", "timeout_ms", "memory_mb", "allowed_permissions",
     "allow_manifest_attempt_argv", "allow_manifest_attempt_stdin",
     "require_enforced_isolation"}
)
_OBSERVATION_KEYS = frozenset({"adapter_id", "availability", "tool_version", "stamp"})
_ADAPTER_OVERLAY_HELP = (
    "Declared JSON array of user adapter manifests registered after --adapters; "
    "an overlay entry adds a new adapter or replaces the same adapter_id. "
    "Repeatable; later overlays win. Manifests are parsed statically; "
    "nothing is loaded or executed."
)


def _load_document(path: str, what: str):
    declared = Path(path)
    if not declared.is_file():
        raise ValueError(f"{what} requires a regular declared file")
    raw = declared.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"{what} exceeds the declared byte bound")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{what} is not a JSON document") from exc
    return document


def _closed(document, allowed: frozenset, what: str, required: frozenset = frozenset()) -> None:
    if (
        type(document) is not dict
        or set(document) - allowed
        or not required <= set(document)
    ):
        raise ValueError(f"{what} has unknown or missing keys")


def _load_request(path: str) -> RouteRequirements:
    document = _load_document(path, "route requirements")
    if type(document) is not dict or set(document) - _REQUEST_KEYS:
        raise ValueError("route requirements has unknown keys")
    if "profile" not in document or "method" not in document:
        raise ValueError("route requirements lacks profile or method")
    contract = document.get("result_contract")
    if contract is None:
        raise ValueError("route requirements lacks a result contract")
    _closed(
        contract,
        _CONTRACT_KEYS,
        "result contract",
        frozenset({"profile", "method", "scope", "correspondence_relation", "correspondence_status"}),
    )
    return RouteRequirements(
        document["profile"],
        document["method"],
        frozenset(document.get("logic_fragments") or ()),
        document.get("target_triple"),
        ResultContract(
            contract["profile"],
            contract["method"],
            contract["scope"],
            contract["correspondence_relation"],
            contract["correspondence_status"],
            frozenset(contract.get("bounds") or ()),
            frozenset(contract.get("assumptions") or ()),
        ),
        document.get("input_format"),
    )


def _load_policy(path: str) -> PlannerPolicy:
    document = _load_document(path, "planner policy")
    if type(document) is not dict or set(document) - _POLICY_KEYS:
        raise ValueError("planner policy has unknown keys")
    pins = document.get("tool_version_pins")
    if pins is None:
        pins = []
    if type(pins) is not list or any(
        type(pin) is not list or len(pin) != 2 for pin in pins
    ):
        raise ValueError("invalid tool version pin declaration")
    if "allowed_permissions" not in document:
        raise ValueError(
            "planner policy requires an explicit allowed_permissions list"
        )
    allowed = document["allowed_permissions"]
    locations = document.get("allowed_locations")
    return PlannerPolicy(
        selected_adapter=document.get("selected_adapter"),
        allow_fallback=document.get("allow_fallback", False),
        allow_manifest_attempt_argv=document.get(
            "allow_manifest_attempt_argv", False
        ),
        allow_manifest_attempt_stdin=document.get(
            "allow_manifest_attempt_stdin", False
        ),
        require_enforced_isolation=document.get(
            "require_enforced_isolation", False
        ),
        disabled_adapters=frozenset(document.get("disabled_adapters") or ()),
        allowed_locations=frozenset(
            {"local"} if locations is None else locations
        ),
        tool_version_pins=tuple(tuple(pin) for pin in pins),
        timeout_ms=document.get("timeout_ms", 30_000),
        memory_mb=document.get("memory_mb", 1024),
        allowed_permissions=None if allowed is None else frozenset(allowed),
    )


def _load_observations(path: str | None) -> tuple[RuntimeObservation, ...]:
    if path is None:
        return ()
    document = _load_document(path, "runtime observations")
    if type(document) is not list:
        raise ValueError("runtime observations must be a JSON array")
    for entry in document:
        _closed(entry, _OBSERVATION_KEYS, "runtime observation", frozenset({"adapter_id"}))
    return tuple(
        RuntimeObservation(
            entry["adapter_id"],
            entry.get("availability", "unknown"),
            entry.get("tool_version"),
            entry.get("stamp"),
        )
        for entry in document
    )


def _load_argv_map(path: str) -> dict[str, tuple[str, ...]]:
    document = _load_document(path, "adapter argv map")
    if type(document) is not dict:
        raise ValueError("adapter argv map must be a JSON object")
    argvs: dict[str, tuple[str, ...]] = {}
    for adapter_id, argv in document.items():
        if (
            type(adapter_id) is not str
            or type(argv) is not list
            or not argv
            or any(type(arg) is not str or not arg for arg in argv)
        ):
            raise ValueError("invalid adapter argv declaration")
        argvs[adapter_id] = tuple(argv)
    return argvs


def _load_registry(
    path: str, overlays: Sequence[str] = ()
) -> AdapterRegistry:
    document = _load_document(path, "adapter manifests")
    if type(document) is not list or not document:
        raise ValueError("adapter manifests must be a nonempty JSON array")
    registry = AdapterRegistry()
    for manifest in document:
        registry.register_manifest(manifest)
    for overlay_path in overlays:
        overlay = _load_document(overlay_path, "adapter overlay manifests")
        if type(overlay) is not list or not overlay:
            raise ValueError(
                "adapter overlay manifests must be a nonempty JSON array"
            )
        overlay_ids: set[str] = set()
        for manifest in overlay:
            adapter_id = (
                manifest.get("adapter_id")
                if type(manifest) is dict
                else None
            )
            if type(adapter_id) is str:
                if adapter_id in overlay_ids:
                    raise ValueError(
                        "adapter overlay declares a duplicate adapter_id"
                    )
                overlay_ids.add(adapter_id)
            registry.register_manifest(manifest, replace=True)
    return registry


def build_schedule_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="verify-schedule")
    parser.description = (
        "Run the declared plan/dispatch/observe/fallback schedule over "
        "declared adapter manifests and emit mumei.attempt-schedule/v1. "
        "The schedule is a dispatch record, not an Evidence acceptance."
    )
    parser.add_argument(
        "--request", required=True, metavar="PATH",
        help="Declared route requirements JSON (profile, method, result_contract, input_format).",
    )
    parser.add_argument(
        "--adapters", required=True, metavar="PATH",
        help="Declared JSON array of adapter manifests to register.",
    )
    parser.add_argument(
        "--adapter-overlay", action="append", default=None, metavar="PATH",
        help=_ADAPTER_OVERLAY_HELP,
    )
    parser.add_argument(
        "--argv-map", required=True, metavar="PATH",
        help="Declared JSON object mapping adapter_id to its argv array.",
    )
    parser.add_argument(
        "--policy", required=True, metavar="PATH",
        help=(
            "Declared planner policy JSON. allowed_permissions must be "
            "declared (an empty list permits only permission-free adapters); "
            "optional Boolean require_enforced_isolation defaults to false "
            "and fails closed when required isolation or memory cannot be "
            "enforced."
        ),
    )
    parser.add_argument(
        "--observations", metavar="PATH",
        help="Optional declared JSON array of runtime observations.",
    )
    parser.add_argument(
        "--source", required=True, metavar="PATH",
        help="Declared .mm source file (absolute path).",
    )
    parser.add_argument(
        "--max-attempts", type=int, default=MAX_SCHEDULE_ATTEMPTS, metavar="<N>",
        help="Bounded schedule attempts across all adapters.",
    )
    parser.add_argument(
        "--success-exit-code", type=int, action="append", default=None,
        metavar="<N>",
        help=(
            "Declared exit code counting as a scheduling success "
            "(repeatable; default {0})."
        ),
    )
    parser.add_argument(
        "--memory-bound-mb", type=int, default=None, metavar="<MB>",
        help="Optional declared POSIX RLIMIT_AS ceiling per attempt child.",
    )
    parser.add_argument(
        "--core", metavar="PATH", default=None,
        help=(
            "Optional Core executable: when a schedule selects an attempt, "
            "run the Core representation check on its captured output and "
            "record the mumei.evidence-check-acceptance/v1 descriptor."
        ),
    )
    parser.add_argument(
        "--core-requirement", metavar="PATH", default=None,
        help=(
            "Optional declared mumei.evidence-requirement/v1 document: "
            "requires --core; the selected attempt's check becomes the "
            "requirement-declared `evidence accept` and the recorded "
            "outcome is Core's verdict."
        ),
    )
    parser.add_argument(
        "--core-requirement-list", metavar="PATH", default=None,
        help=(
            "Optional declared mumei.evidence-requirement-list/v1 "
            "document: requires --core and conflicts with "
            "--core-requirement; the selected attempt's check becomes "
            "the conjunctive requirement-declared `evidence accept` and "
            "the descriptor is promotable gate input."
        ),
    )
    parser.add_argument(
        "--export-evidence-acceptance", metavar="DIR", default=None,
        help=(
            "Optional export directory: requires "
            "--core-requirement-list; writes the promotable gate triple "
            "(requirement-list.json, evidence.json, acceptance.json) "
            "for `mumei claims --require-evidence-acceptance`."
        ),
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help="Write the schedule document here instead of stdout.",
    )
    parser.add_argument(
        "--history-log", metavar="PATH",
        help=(
            "Append every plan of the schedule (the initial plan, then each "
            "replan, in order) to an opt-in tamper-evident plan history log "
            "(mumei.verification-plan-history-entry/v1) as one all-or-nothing "
            "batch. Not Evidence, a dispatch record or authentication."
        ),
    )
    parser.add_argument(
        "--expected-history-head", metavar="HEX",
        help=(
            "Refuse to append unless the log's last entry digest equals this "
            "pinned head. Requires --history-log."
        ),
    )
    return parser


def _run_schedule_result(args: argparse.Namespace) -> AttemptScheduleResult:
    request = _load_request(args.request)
    if request.input_format != SOURCE_INPUT_FORMAT or request.result_contract is None:
        raise ValueError("verify-schedule requires the source input contract and format")
    registry = _load_registry(
        args.adapters, getattr(args, "adapter_overlay", None) or ()
    )
    argv_map = _load_argv_map(args.argv_map)
    policy = _load_policy(args.policy)
    observations = _load_observations(args.observations)
    declared = Path(args.source)
    if not declared.is_file():
        raise ValueError("source requires a regular declared file")
    core = getattr(args, "core", None)
    if core is not None and (
        not os.path.isabs(core)
        or "\x00" in core
        or not Path(core).is_file()
    ):
        raise ValueError("--core must be an absolute path to a regular file")
    requirement = getattr(args, "core_requirement", None)
    if requirement is not None and (
        core is None
        or not os.path.isabs(requirement)
        or "\x00" in requirement
        or not Path(requirement).is_file()
    ):
        raise ValueError(
            "--core-requirement requires --core and an absolute path to a regular file"
        )
    requirement_list = getattr(args, "core_requirement_list", None)
    if requirement_list is not None and (
        core is None
        or requirement is not None
        or not os.path.isabs(requirement_list)
        or "\x00" in requirement_list
        or not Path(requirement_list).is_file()
    ):
        raise ValueError(
            "--core-requirement-list requires --core, conflicts with "
            "--core-requirement and needs an absolute path to a regular file"
        )
    export_dir = getattr(args, "export_evidence_acceptance", None)
    if export_dir is not None and (
        requirement_list is None
        or not os.path.isabs(export_dir)
        or "\x00" in export_dir
    ):
        raise ValueError(
            "--export-evidence-acceptance requires --core-requirement-list "
            "and an absolute directory path"
        )
    if export_dir is not None:
        # The export must not clobber a declared input or the schedule
        # document itself: an export target that resolves to an
        # existing declared path, or --output pointing into the export
        # directory's triple, is a declaration error.
        declared_inputs = [
            args.request,
            args.adapters,
            args.argv_map,
            args.policy,
            args.source,
            args.core,
            requirement or "",
            requirement_list,
        ]
        declared_inputs.extend(getattr(args, "adapter_overlay", None) or ())
        if args.observations is not None:
            declared_inputs.append(args.observations)
        for name in (
            "requirement-list.json",
            "evidence.json",
            "acceptance.json",
        ):
            target = os.path.join(export_dir, name)
            if args.output is not None and os.path.realpath(
                target
            ) == os.path.realpath(args.output):
                raise ValueError(
                    "--output must not overwrite an exported acceptance artifact"
                )
            if os.path.exists(target) and any(
                os.path.exists(p) and os.path.samefile(target, p)
                for p in declared_inputs
            ):
                raise ValueError(
                    "--export-evidence-acceptance must not overwrite a declared input"
                )
    source = declared.read_bytes()
    success = (
        frozenset({0})
        if args.success_exit_code is None
        else frozenset(args.success_exit_code)
    )
    def argv_for(adapter_id: str) -> tuple[str, ...] | None:
        # The host's argv_map wins; a manifest-declared ``attempt_argv``
        # runs only when the host policy opts in — a manifest must not
        # plant an executable command by itself.
        declared = argv_map.get(adapter_id)
        if declared is not None:
            return declared
        if policy.allow_manifest_attempt_argv:
            descriptor = registry.descriptor(adapter_id)
            if descriptor is not None:
                return descriptor.attempt_argv
        return None

    def stdin_for(adapter_id: str) -> bytes | None:
        # Manifest-declared stdin feeds the attempt only when the host
        # policy opts in — like argv, a manifest must not plant input.
        if not policy.allow_manifest_attempt_stdin:
            return None
        descriptor = registry.descriptor(adapter_id)
        if descriptor is None or descriptor.attempt_stdin is None:
            return None
        return descriptor.attempt_stdin.encode("utf-8")

    result = run_attempt_schedule(
        registry,
        request,
        policy,
        source,
        hashlib.sha256(source).hexdigest(),
        argv_for,
        observations=observations,
        max_attempts=args.max_attempts,
        success_exit_codes=success,
        memory_bound_mb=args.memory_bound_mb,
        stdin_for=stdin_for,
        core_executable=core,
        core_requirement=requirement,
        core_requirement_list=requirement_list,
        export_dir=export_dir,
    )
    return result


def run_schedule(args: argparse.Namespace) -> dict:
    return _run_schedule_result(args).to_dict()


def _declared_paths(args: argparse.Namespace) -> list[str]:
    paths = [args.request, args.adapters, args.argv_map, args.policy,
             args.source]
    paths.extend(getattr(args, "adapter_overlay", None) or ())
    if getattr(args, "core", None) is not None:
        paths.append(args.core)
    if getattr(args, "core_requirement", None) is not None:
        paths.append(args.core_requirement)
    if getattr(args, "core_requirement_list", None) is not None:
        paths.append(args.core_requirement_list)
    if getattr(args, "export_evidence_acceptance", None) is not None:
        paths.append(args.export_evidence_acceptance)
    if args.observations is not None:
        paths.append(args.observations)
    if args.output is not None:
        paths.append(args.output)
    if getattr(args, "history_log", None) is not None:
        paths.append(args.history_log)
    return paths


def _redact_declared_paths(text: str, declared: list[str]) -> str:
    # Failure text must not carry checkout-local paths: inputs may sit
    # inside private directories whose names are not evidence.
    for path in declared:
        if not path:
            continue
        for form in (path, os.path.realpath(path)):
            text = text.replace(form, "<declared path>")
    return text


def build_plan_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="verify-plan")
    parser.description = (
        "Plan one declared route through the adapter registry and emit "
        "mumei.verification-plan/v1 — the selected adapter, its effective "
        "non-secret settings, per-candidate selection/exclusion reasons "
        "and the fallback origin. Planning only: nothing is spawned, "
        "dispatched or accepted."
    )
    parser.add_argument(
        "--request", required=True, metavar="PATH",
        help="Declared route requirements JSON (profile, method, result_contract).",
    )
    parser.add_argument(
        "--adapters", required=True, metavar="PATH",
        help="Declared JSON array of adapter manifests to register.",
    )
    parser.add_argument(
        "--adapter-overlay", action="append", default=None, metavar="PATH",
        help=_ADAPTER_OVERLAY_HELP,
    )
    parser.add_argument(
        "--policy", required=True, metavar="PATH",
        help=(
            "Declared planner policy JSON. allowed_permissions must be "
            "declared (an empty list permits only permission-free adapters)."
        ),
    )
    parser.add_argument(
        "--observations", metavar="PATH",
        help="Optional declared JSON array of runtime observations.",
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help="Write the plan document here instead of stdout.",
    )
    parser.add_argument(
        "--history-log", metavar="PATH",
        help=(
            "Append the emitted plan to an opt-in tamper-evident plan history "
            "log (mumei.verification-plan-history-entry/v1). Not Evidence, "
            "a dispatch record or authentication."
        ),
    )
    parser.add_argument(
        "--expected-history-head", metavar="HEX",
        help=(
            "Refuse to append unless the log's last entry digest equals this "
            "pinned head. Requires --history-log."
        ),
    )
    return parser


def _build_plan(args: argparse.Namespace) -> VerificationPlan:
    request = _load_request(args.request)
    registry = _load_registry(
        args.adapters, getattr(args, "adapter_overlay", None) or ()
    )
    policy = _load_policy(args.policy)
    observations = _load_observations(args.observations)
    return registry.plan(request, policy, observations)


def run_plan(args: argparse.Namespace) -> dict:
    return _build_plan(args).to_dict()


def _plan_declared_paths(args: argparse.Namespace) -> list[str]:
    paths = [args.request, args.adapters, args.policy]
    paths.extend(getattr(args, "adapter_overlay", None) or ())
    if args.observations is not None:
        paths.append(args.observations)
    if args.output is not None:
        paths.append(args.output)
    history_log = getattr(args, "history_log", None)
    if history_log is not None:
        paths.append(history_log)
    return paths


def _same_file(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b) or (
        os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b)
    )


def main_plan(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_plan_parser().parse_args()
    declared = _plan_declared_paths(args)
    try:
        history_log = getattr(args, "history_log", None)
        expected_history_head = getattr(args, "expected_history_head", None)
        if expected_history_head is not None and history_log is None:
            raise ValueError("--expected-history-head requires --history-log")
        if args.output is not None:
            inputs = [args.request, args.adapters, args.policy]
            inputs.extend(getattr(args, "adapter_overlay", None) or ())
            if args.observations is not None:
                inputs.append(args.observations)
            if any(_same_file(path, args.output) for path in inputs):
                raise ValueError(
                    "--output must not overwrite a declared input"
                )
        if history_log is not None:
            declared_inputs = [args.request, args.adapters, args.policy]
            declared_inputs.extend(
                getattr(args, "adapter_overlay", None) or ()
            )
            if args.observations is not None:
                declared_inputs.append(args.observations)
            if args.output is not None:
                declared_inputs.append(args.output)
            if any(_same_file(path, history_log) for path in declared_inputs):
                raise ValueError(
                    "--history-log must not overwrite a declared input or output"
                )

        plan = _build_plan(args)
        if history_log is not None:
            digest = append_plan_history(
                history_log, plan, expected_head=expected_history_head
            )
            print(f"verify-plan: history head {digest}", file=sys.stderr)
        document = json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(
            f"verify-plan: {_redact_declared_paths(str(exc), declared)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return 0


def main_schedule(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_schedule_parser().parse_args()
    declared = _declared_paths(args)
    try:
        history_log = getattr(args, "history_log", None)
        expected_history_head = getattr(args, "expected_history_head", None)
        if expected_history_head is not None and history_log is None:
            raise ValueError("--expected-history-head requires --history-log")
        if history_log is not None:
            declared_inputs_and_outputs = _declared_paths(args)[:-1]
            if any(
                _same_file(history_log, path)
                for path in declared_inputs_and_outputs
            ):
                raise ValueError(
                    "--history-log must not overwrite a declared input or output"
                )
            export_dir = getattr(args, "export_evidence_acceptance", None)
            if export_dir is not None and any(
                _same_file(
                    history_log,
                    os.path.join(export_dir, filename),
                )
                for filename in (
                    "requirement-list.json",
                    "evidence.json",
                    "acceptance.json",
                )
            ):
                raise ValueError(
                    "--history-log must not overwrite a declared input or output"
                )
        if args.output is not None:
            target = os.path.realpath(args.output)
            inputs = [args.request, args.adapters, args.argv_map,
                      args.policy, args.source]
            inputs.extend(getattr(args, "adapter_overlay", None) or ())
            if args.observations is not None:
                inputs.append(args.observations)
            if getattr(args, "core", None) is not None:
                inputs.append(args.core)
            if getattr(args, "core_requirement", None) is not None:
                inputs.append(args.core_requirement)
            if getattr(args, "core_requirement_list", None) is not None:
                inputs.append(args.core_requirement_list)
            if getattr(args, "export_evidence_acceptance", None) is not None:
                inputs.append(args.export_evidence_acceptance)
            if any(
                os.path.realpath(p) == target
                or os.path.exists(args.output)
                and os.path.exists(p)
                and os.path.samefile(p, args.output)
                for p in inputs
            ):
                raise ValueError(
                    "--output must not overwrite a declared input"
                )
        if history_log is not None:
            read_plan_history(
                history_log, expected_head=expected_history_head
            )
        result = _run_schedule_result(args)
        if history_log is not None:
            digests = append_plan_histories(
                history_log,
                result.plans,
                expected_head=expected_history_head,
            )
            print(
                f"verify-schedule: history head {digests[-1]}",
                file=sys.stderr,
            )
        document = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(
            f"verify-schedule: {_redact_declared_paths(str(exc), declared)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return 0
