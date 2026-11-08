"""Pure, opt-in route selection; not execution, availability probing or proof acceptance.

Descriptors and observations are host-supplied metadata, not trusted evidence.
Profile identifiers must denote the complete required semantics, not a lossy subset.
No production CLI/MCP/default verification path uses this experimental API yet.
"""

import re
from dataclasses import asdict, dataclass

PROTOCOL_VERSION = "mumei.verifier-adapter/v1"
METHODS = frozenset(
    {
        "deductive_proof",
        "abstract_interpretation",
        "bounded_model_checking",
        "finite_execution",
        "static_heuristic",
        "identity_check",
    }
)
LOCATIONS = frozenset({"local", "container", "remote"})
SCOPES = frozenset({"unbounded", "bounded", "finite", "identity_only"})
CORRESPONDENCE_STATUSES = frozenset({"validated", "assumed", "unverified"})


def _label(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)*", value
    ):
        raise ValueError("invalid metadata identifier")


def _labels(values: frozenset[str], *, empty: bool = False) -> None:
    if not isinstance(values, frozenset) or (not empty and not values):
        raise ValueError("expected immutable metadata identifiers")
    for value in values:
        _label(value)


def _version(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]+)*(?:[-+][A-Za-z0-9.-]+)?", value
    ):
        raise ValueError("invalid version identifier")


def _positive(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("budget must be a positive integer")


@dataclass(frozen=True)
class ResultContract:
    """Host-declared routing metadata, not an Evidence record or acceptance rule.

    Bounds, assumptions and relation are approved, versioned identifiers whose
    meanings belong to the host/profile. Matching is exact: no implication,
    scope ordering, assumption discharge or semantic translation is inferred.
    """

    profile: str
    method: str
    scope: str
    correspondence_relation: str
    correspondence_status: str
    bounds: frozenset[str] = frozenset()
    assumptions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _label(self.profile)
        if not isinstance(self.method, str) or self.method not in METHODS:
            raise ValueError("unsupported evidence method")
        if not isinstance(self.scope, str) or self.scope not in SCOPES:
            raise ValueError("unsupported result scope")
        _labels(self.bounds, empty=True)
        _labels(self.assumptions, empty=True)
        if bool(self.bounds) != (self.scope in {"bounded", "finite"}):
            raise ValueError("result scope and bounds disagree")
        _label(self.correspondence_relation)
        if (
            not isinstance(self.correspondence_status, str)
            or self.correspondence_status not in CORRESPONDENCE_STATUSES
        ):
            raise ValueError("unsupported correspondence status")

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "method": self.method,
            "scope": self.scope,
            "bounds": sorted(self.bounds),
            "assumptions": sorted(self.assumptions),
            "correspondence_relation": self.correspondence_relation,
            "correspondence_status": self.correspondence_status,
        }


@dataclass(frozen=True)
class RouteRequirements:
    """A capability query, not a complete executable obligation or assurance policy."""

    profile: str
    method: str
    logic_fragments: frozenset[str] = frozenset()
    target_triple: str | None = None
    result_contract: ResultContract | None = None

    def __post_init__(self) -> None:
        _label(self.profile)
        if self.method not in METHODS:
            raise ValueError("unsupported evidence method")
        _labels(self.logic_fragments, empty=True)
        if self.target_triple is not None:
            _label(self.target_triple)
        if self.result_contract is not None:
            if not isinstance(self.result_contract, ResultContract):
                raise ValueError("invalid result contract")
            if (self.result_contract.profile, self.result_contract.method) != (
                self.profile,
                self.method,
            ):
                raise ValueError("result contract does not match route requirements")


@dataclass(frozen=True)
class AdapterDescriptor:
    adapter_id: str
    adapter_version: str
    profiles: frozenset[str]
    methods: frozenset[str]
    logic_fragments: frozenset[str] = frozenset()
    targets: frozenset[str] = frozenset()
    protocol_version: str = PROTOCOL_VERSION
    priority: int = 0
    enabled: bool = True
    location: str = "local"
    max_timeout_ms: int = 30_000
    max_memory_mb: int = 1024
    result_contracts: tuple[ResultContract, ...] = ()

    def __post_init__(self) -> None:
        _label(self.adapter_id)
        _version(self.adapter_version)
        _label(self.protocol_version)
        _labels(self.profiles)
        _labels(self.methods)
        if not self.methods <= METHODS:
            raise ValueError("unsupported evidence method")
        _labels(self.logic_fragments, empty=True)
        _labels(self.targets, empty=True)
        if type(self.priority) is not int or type(self.enabled) is not bool:
            raise ValueError("invalid adapter policy")
        if self.location not in LOCATIONS:
            raise ValueError("unsupported execution location")
        _positive(self.max_timeout_ms)
        _positive(self.max_memory_mb)
        if not isinstance(self.result_contracts, tuple):
            raise ValueError("expected immutable result contracts")
        seen_contracts: set[ResultContract] = set()
        for contract in self.result_contracts:
            if not isinstance(contract, ResultContract):
                raise ValueError("invalid result contract")
            if contract in seen_contracts:
                raise ValueError("duplicate result contract")
            seen_contracts.add(contract)
            if (
                contract.profile not in self.profiles
                or contract.method not in self.methods
            ):
                raise ValueError("result contract outside declared capabilities")


@dataclass(frozen=True)
class RuntimeObservation:
    """A host's preflight observation; freshness and actual probing are not implemented."""

    adapter_id: str
    availability: str = "unknown"
    tool_version: str | None = None

    def __post_init__(self) -> None:
        _label(self.adapter_id)
        if self.availability not in {"available", "missing", "unknown"}:
            raise ValueError("invalid availability observation")
        if self.tool_version is not None:
            _version(self.tool_version)


@dataclass(frozen=True)
class PlannerPolicy:
    selected_adapter: str | None = None
    allow_fallback: bool = False
    disabled_adapters: frozenset[str] = frozenset()
    allowed_locations: frozenset[str] = frozenset({"local"})
    tool_version_pins: tuple[tuple[str, str], ...] = ()
    timeout_ms: int = 30_000
    memory_mb: int = 1024

    def __post_init__(self) -> None:
        if self.selected_adapter is not None:
            _label(self.selected_adapter)
        if type(self.allow_fallback) is not bool:
            raise ValueError("fallback must be explicit Boolean policy")
        _labels(self.disabled_adapters, empty=True)
        _labels(self.allowed_locations)
        if not self.allowed_locations <= LOCATIONS:
            raise ValueError("unsupported execution location")
        _positive(self.timeout_ms)
        _positive(self.memory_mb)
        if not isinstance(self.tool_version_pins, tuple):
            raise ValueError("invalid tool version pins")
        seen = set()
        for pin in self.tool_version_pins:
            if not isinstance(pin, tuple) or len(pin) != 2:
                raise ValueError("invalid tool version pin")
            adapter_id, version = pin
            _label(adapter_id)
            _version(version)
            if adapter_id in seen:
                raise ValueError("duplicate tool version pin")
            seen.add(adapter_id)


@dataclass(frozen=True)
class AdapterDecision:
    adapter_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EffectiveSettings:
    adapter_id: str
    adapter_version: str
    observed_tool_version: str
    protocol_version: str
    location: str
    timeout_ms: int
    memory_mb: int
    result_contract: ResultContract | None = None


@dataclass(frozen=True)
class VerificationPlan:
    request: RouteRequirements
    policy: PlannerPolicy
    selected: EffectiveSettings | None
    fallback_from: str | None
    decisions: tuple[AdapterDecision, ...]

    def to_dict(self) -> dict:
        request: dict[str, object] = {
            "profile": self.request.profile,
            "method": self.request.method,
            "logic_fragments": sorted(self.request.logic_fragments),
            "target_triple": self.request.target_triple,
        }
        if self.request.result_contract is not None:
            request["result_contract"] = self.request.result_contract.to_dict()
        selected: dict[str, object] | None = None
        if self.selected is not None:
            selected = asdict(self.selected)
            selected.pop("result_contract")
            if self.selected.result_contract is not None:
                selected["result_contract"] = self.selected.result_contract.to_dict()
        return {
            "schema_version": "mumei.verification-plan/v1",
            "request": request,
            "policy": {
                "selected_adapter": self.policy.selected_adapter,
                "allow_fallback": self.policy.allow_fallback,
                "disabled_adapters": sorted(self.policy.disabled_adapters),
                "allowed_locations": sorted(self.policy.allowed_locations),
                "tool_version_pins": dict(sorted(self.policy.tool_version_pins)),
                "timeout_ms": self.policy.timeout_ms,
                "memory_mb": self.policy.memory_mb,
            },
            "selected": selected,
            "fallback_from": self.fallback_from,
            "decisions": [asdict(decision) for decision in self.decisions],
        }


class AdapterRegistry:
    """Explicit data registration only: no plugin loading, imports or discovery."""

    def __init__(self) -> None:
        self._adapters: dict[str, AdapterDescriptor] = {}

    def register(self, adapter: AdapterDescriptor, *, replace: bool = False) -> None:
        if type(replace) is not bool:
            raise ValueError("replacement must be explicit Boolean policy")
        if adapter.adapter_id in self._adapters and not replace:
            raise ValueError("adapter already registered; replacement must be explicit")
        self._adapters[adapter.adapter_id] = adapter

    def plan(
        self,
        request: RouteRequirements,
        policy: PlannerPolicy,
        observations: tuple[RuntimeObservation, ...] = (),
    ) -> VerificationPlan:
        runtime: dict[str, RuntimeObservation] = {}
        for observation in observations:
            if observation.adapter_id in runtime:
                raise ValueError("duplicate runtime observation")
            if observation.adapter_id not in self._adapters:
                raise ValueError("runtime observation has no registered adapter")
            runtime[observation.adapter_id] = observation
        pins = dict(policy.tool_version_pins)
        if any(key not in self._adapters for key in pins):
            raise ValueError("tool version pin has no registered adapter")
        ordered = sorted(
            self._adapters.values(), key=lambda a: (-a.priority, a.adapter_id)
        )
        reasons: dict[str, list[str]] = {}
        for adapter in ordered:
            excluded = reasons[adapter.adapter_id] = []
            observed = runtime.get(adapter.adapter_id)
            if not adapter.enabled or adapter.adapter_id in policy.disabled_adapters:
                excluded.append("disabled")
            if adapter.protocol_version != PROTOCOL_VERSION:
                excluded.append("protocol_mismatch")
            if request.profile not in adapter.profiles:
                excluded.append("unsupported_semantic_profile")
            if request.method not in adapter.methods:
                excluded.append("unsupported_evidence_method")
            if request.result_contract is not None:
                if not adapter.result_contracts:
                    excluded.append("result_contract_not_declared")
                elif request.result_contract not in adapter.result_contracts:
                    excluded.append("unsupported_result_contract")
            if not request.logic_fragments <= adapter.logic_fragments:
                excluded.append("unsupported_logic_fragments")
            if adapter.targets and request.target_triple is None:
                excluded.append("target_unknown")
            elif adapter.targets and request.target_triple not in adapter.targets:
                excluded.append("unsupported_target")
            if adapter.location not in policy.allowed_locations:
                excluded.append("location_not_allowed")
            if observed is None or observed.availability == "unknown":
                excluded.append("availability_unknown")
            elif observed.availability == "missing":
                excluded.append("tool_missing")
            if observed is None or observed.tool_version is None:
                excluded.append("tool_version_unknown")
            elif (
                adapter.adapter_id in pins
                and observed.tool_version != pins[adapter.adapter_id]
            ):
                excluded.append("tool_version_mismatch")

        eligible = [a for a in ordered if not reasons[a.adapter_id]]
        selected = next(
            (a for a in eligible if a.adapter_id == policy.selected_adapter), None
        )
        if selected is None and (
            policy.selected_adapter is None or policy.allow_fallback
        ):
            selected = next(iter(eligible), None)
        fallback_from = (
            policy.selected_adapter
            if selected is not None
            and policy.selected_adapter not in {None, selected.adapter_id}
            else None
        )
        decisions = []
        for adapter in ordered:
            reason = reasons[adapter.adapter_id]
            if not reason:
                if selected == adapter:
                    reason = [
                        "selected_fallback"
                        if fallback_from
                        else (
                            "selected_explicit"
                            if policy.selected_adapter
                            else "selected_priority"
                        )
                    ]
                elif selected is None and policy.selected_adapter is not None:
                    reason = ["explicit_selection_blocks_automatic_route"]
                else:
                    reason = ["compatible_not_selected"]
            decisions.append(AdapterDecision(adapter.adapter_id, tuple(reason)))
        if (
            policy.selected_adapter is not None
            and policy.selected_adapter not in self._adapters
        ):
            decisions.append(
                AdapterDecision(policy.selected_adapter, ("not_registered",))
            )
        settings = None
        if selected is not None:
            version = runtime[selected.adapter_id].tool_version
            assert version is not None
            settings = EffectiveSettings(
                selected.adapter_id,
                selected.adapter_version,
                version,
                selected.protocol_version,
                selected.location,
                min(policy.timeout_ms, selected.max_timeout_ms),
                min(policy.memory_mb, selected.max_memory_mb),
                request.result_contract,
            )
        return VerificationPlan(
            request, policy, settings, fallback_from, tuple(decisions)
        )
