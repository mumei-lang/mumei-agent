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
import sys
from pathlib import Path

from agent.attempt_schedule import MAX_SCHEDULE_ATTEMPTS, run_attempt_schedule
from agent.verification_planner import (
    AdapterRegistry,
    PlannerPolicy,
    ResultContract,
    RouteRequirements,
    RuntimeObservation,
    SOURCE_INPUT_FORMAT,
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
     "tool_version_pins", "timeout_ms", "memory_mb", "allowed_permissions"}
)
_OBSERVATION_KEYS = frozenset({"adapter_id", "availability", "tool_version", "stamp"})


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
    allowed = document.get("allowed_permissions")
    return PlannerPolicy(
        selected_adapter=document.get("selected_adapter"),
        allow_fallback=document.get("allow_fallback", False),
        disabled_adapters=frozenset(document.get("disabled_adapters") or ()),
        allowed_locations=frozenset(
            document.get("allowed_locations") or {"local"}
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


def _load_registry(path: str) -> AdapterRegistry:
    document = _load_document(path, "adapter manifests")
    if type(document) is not list or not document:
        raise ValueError("adapter manifests must be a nonempty JSON array")
    registry = AdapterRegistry()
    for manifest in document:
        registry.register_manifest(manifest)
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
        "--argv-map", required=True, metavar="PATH",
        help="Declared JSON object mapping adapter_id to its argv array.",
    )
    parser.add_argument(
        "--policy", required=True, metavar="PATH",
        help=(
            "Declared planner policy JSON. allowed_permissions must be "
            "declared for attempt binding; omit it only to exclude all "
            "permission-requiring adapters."
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
        "--output", metavar="PATH",
        help="Write the schedule document here instead of stdout.",
    )
    return parser


def run_schedule(args: argparse.Namespace) -> dict:
    request = _load_request(args.request)
    if request.input_format != SOURCE_INPUT_FORMAT or request.result_contract is None:
        raise ValueError("verify-schedule requires the source input contract and format")
    registry = _load_registry(args.adapters)
    argv_map = _load_argv_map(args.argv_map)
    policy = _load_policy(args.policy)
    observations = _load_observations(args.observations)
    declared = Path(args.source)
    if not declared.is_file():
        raise ValueError("source requires a regular declared file")
    source = declared.read_bytes()
    success = (
        frozenset({0})
        if args.success_exit_code is None
        else frozenset(args.success_exit_code)
    )
    result = run_attempt_schedule(
        registry,
        request,
        policy,
        source,
        hashlib.sha256(source).hexdigest(),
        argv_map.get,
        observations=observations,
        max_attempts=args.max_attempts,
        success_exit_codes=success,
        memory_bound_mb=args.memory_bound_mb,
    )
    return result.to_dict()


def main_schedule(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_schedule_parser().parse_args()
    try:
        document = json.dumps(run_schedule(args), indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"verify-schedule: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
