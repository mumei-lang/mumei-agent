"""Pure, opt-in route selection; not execution, availability probing or proof acceptance.

Descriptors and observations are host-supplied metadata, not trusted evidence.
Profile identifiers must denote the complete required semantics, not a lossy subset.
No production CLI/MCP/default verification path uses this experimental API yet.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace

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
SettingValue = bool | int | str
SettingValues = tuple[tuple[str, SettingValue], ...]
MAX_SETTINGS = 32
SOURCE_INPUT_FORMAT = "mumei.source-text/v1"
MAX_SOURCE_BYTES = 1_048_576
PERMISSIONS = frozenset(
    {
        "filesystem.read",
        "filesystem.write",
        "environment.read",
        "network.connect",
        "process.spawn",
    }
)


_MANIFEST_FIELDS = frozenset(
    {
        "adapter_id",
        "adapter_version",
        "profiles",
        "methods",
        "logic_fragments",
        "targets",
        "protocol_version",
        "priority",
        "enabled",
        "location",
        "max_timeout_ms",
        "max_memory_mb",
        "result_contracts",
        "setting_specs",
        "input_formats",
        "required_permissions",
    }
)
_MANIFEST_REQUIRED = frozenset(
    {"adapter_id", "adapter_version", "profiles", "methods"}
)
_CONTRACT_FIELDS = frozenset(
    {
        "profile",
        "method",
        "scope",
        "bounds",
        "assumptions",
        "correspondence_relation",
        "correspondence_status",
    }
)
_CONTRACT_REQUIRED = _CONTRACT_FIELDS - {"bounds", "assumptions"}
_SPEC_FIELDS = frozenset(
    {"name", "kind", "default", "minimum", "maximum", "choices"}
)
_SPEC_REQUIRED = frozenset({"name", "kind", "default"})


def _manifest_strings(value: object) -> frozenset[str]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError("invalid adapter manifest labels")
    return frozenset(value)


def _contract_from_manifest(entry: object) -> "ResultContract":
    if (
        type(entry) is not dict
        or set(entry) - _CONTRACT_FIELDS
        or _CONTRACT_REQUIRED - set(entry)
    ):
        raise ValueError("invalid adapter manifest result contract")
    return ResultContract(
        profile=entry["profile"],
        method=entry["method"],
        scope=entry["scope"],
        bounds=_manifest_strings(entry.get("bounds", [])),
        assumptions=_manifest_strings(entry.get("assumptions", [])),
        correspondence_relation=entry["correspondence_relation"],
        correspondence_status=entry["correspondence_status"],
    )


def _spec_from_manifest(entry: object) -> "SettingSpec":
    if (
        type(entry) is not dict
        or set(entry) - _SPEC_FIELDS
        or _SPEC_REQUIRED - set(entry)
    ):
        raise ValueError("invalid adapter manifest setting spec")
    return SettingSpec(
        name=entry["name"],
        kind=entry["kind"],
        default=entry["default"],
        minimum=entry.get("minimum"),
        maximum=entry.get("maximum"),
        choices=_manifest_strings(entry.get("choices", [])),
    )


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


def _permissions(values: frozenset[str]) -> None:
    if not isinstance(values, frozenset) or not values <= PERMISSIONS:
        raise ValueError("expected immutable supported permission categories")


def _setting_name(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 64
        or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value)
    ):
        raise ValueError("invalid setting name")
    if set(value.split("_")) & {
        "key",
        "token",
        "secret",
        "password",
        "credential",
        "credentials",
        "auth",
        "authentication",
        "authorization",
        "cookie",
        "endpoint",
        "url",
        "path",
        "command",
        "argv",
        "args",
        "env",
        "environment",
        "header",
        "headers",
        "executable",
    }:
        raise ValueError("setting channel is not permitted")


@dataclass(frozen=True)
class SettingSpec:
    """Host-approved non-secret options only; no free text or invocation channels."""

    name: str
    kind: str
    default: SettingValue
    minimum: int | None = None
    maximum: int | None = None
    choices: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _setting_name(self.name)
        if not isinstance(self.kind, str) or self.kind not in {
            "boolean",
            "integer",
            "choice",
        }:
            raise ValueError("unsupported setting kind")
        if not isinstance(self.choices, frozenset) or len(self.choices) > MAX_SETTINGS:
            raise ValueError("invalid setting choices")
        if self.kind == "integer":
            if type(self.minimum) is not int or type(self.maximum) is not int:
                raise ValueError("integer settings require explicit bounds")
            if not -(2**63) <= self.minimum <= self.maximum < 2**63:
                raise ValueError("invalid integer setting bounds")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("bounds require an integer setting")
        if self.kind == "choice":
            _labels(self.choices)
            if any(len(choice) > 64 for choice in self.choices):
                raise ValueError("invalid setting choice")
        elif self.choices:
            raise ValueError("choices require a choice setting")
        self.validate(self.default)

    def validate(self, value: SettingValue) -> None:
        if self.kind == "boolean" and type(value) is bool:
            return
        if self.kind == "integer" and type(value) is int:
            assert self.minimum is not None and self.maximum is not None
            if self.minimum <= value <= self.maximum:
                return
        if self.kind == "choice" and type(value) is str and value in self.choices:
            return
        raise ValueError("setting value outside declared schema")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "choices": sorted(self.choices),
        }


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
    input_format: str | None = None

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
        if self.input_format is not None:
            _label(self.input_format)

    def to_dict(self) -> dict:
        request: dict[str, object] = {
            "profile": self.profile,
            "method": self.method,
            "logic_fragments": sorted(self.logic_fragments),
            "target_triple": self.target_triple,
        }
        if self.result_contract is not None:
            request["result_contract"] = self.result_contract.to_dict()
        if self.input_format is not None:
            request["input_format"] = self.input_format
        return request


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
    setting_specs: tuple[SettingSpec, ...] = ()
    input_formats: frozenset[str] = frozenset()
    required_permissions: frozenset[str] | None = None

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
        if (
            not isinstance(self.setting_specs, tuple)
            or len(self.setting_specs) > MAX_SETTINGS
        ):
            raise ValueError("invalid setting schema")
        names: set[str] = set()
        for spec in self.setting_specs:
            if not isinstance(spec, SettingSpec):
                raise ValueError("invalid setting schema")
            if spec.name in names:
                raise ValueError("duplicate setting schema name")
            names.add(spec.name)
        _labels(self.input_formats, empty=True)
        if self.required_permissions is not None:
            _permissions(self.required_permissions)

    def to_dict(self) -> dict:
        return {
            "schema_version": PROTOCOL_VERSION,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "profiles": sorted(self.profiles),
            "methods": sorted(self.methods),
            "logic_fragments": sorted(self.logic_fragments),
            "targets": sorted(self.targets),
            "protocol_version": self.protocol_version,
            "priority": self.priority,
            "enabled": self.enabled,
            "location": self.location,
            "max_timeout_ms": self.max_timeout_ms,
            "max_memory_mb": self.max_memory_mb,
            "result_contracts": [
                contract.to_dict() for contract in self.result_contracts
            ],
            "setting_specs": [spec.to_dict() for spec in self.setting_specs],
            "input_formats": sorted(self.input_formats),
            "required_permissions": (
                sorted(self.required_permissions)
                if self.required_permissions is not None
                else None
            ),
        }

    @classmethod
    def from_manifest(cls, manifest: dict) -> "AdapterDescriptor":
        """Static parse of a declared adapter manifest, not plugin loading.

        A manifest is detached host-supplied metadata: it names capabilities,
        budgets and schemas but carries no code, grants no authority and
        proves nothing about availability. Unknown or missing fields and
        malformed entries are static errors; nothing is imported, probed or
        discovered here.
        """
        if type(manifest) is not dict:
            raise ValueError("adapter manifest must be an object")
        if manifest.get("schema_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported adapter manifest schema")
        if set(manifest) - _MANIFEST_FIELDS - {"schema_version"}:
            raise ValueError("unsupported adapter manifest field")
        if _MANIFEST_REQUIRED - set(manifest):
            raise ValueError("adapter manifest field missing")
        contracts = manifest.get("result_contracts", [])
        if type(contracts) is not list:
            raise ValueError("invalid adapter manifest result contract")
        specs = manifest.get("setting_specs", [])
        if type(specs) is not list:
            raise ValueError("invalid adapter manifest setting spec")
        permissions = manifest.get("required_permissions")
        return cls(
            adapter_id=manifest["adapter_id"],
            adapter_version=manifest["adapter_version"],
            profiles=_manifest_strings(manifest["profiles"]),
            methods=_manifest_strings(manifest["methods"]),
            logic_fragments=_manifest_strings(manifest.get("logic_fragments", [])),
            targets=_manifest_strings(manifest.get("targets", [])),
            protocol_version=manifest.get("protocol_version", PROTOCOL_VERSION),
            priority=manifest.get("priority", 0),
            enabled=manifest.get("enabled", True),
            location=manifest.get("location", "local"),
            max_timeout_ms=manifest.get("max_timeout_ms", 30_000),
            max_memory_mb=manifest.get("max_memory_mb", 1024),
            result_contracts=tuple(
                _contract_from_manifest(entry) for entry in contracts
            ),
            setting_specs=tuple(_spec_from_manifest(entry) for entry in specs),
            input_formats=_manifest_strings(manifest.get("input_formats", [])),
            required_permissions=(
                None if permissions is None else _manifest_strings(permissions)
            ),
        )


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
    adapter_settings: tuple[tuple[str, SettingValues], ...] = field(
        default=(), repr=False
    )
    allowed_permissions: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.allowed_permissions is not None:
            _permissions(self.allowed_permissions)
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
        if not isinstance(self.adapter_settings, tuple):
            raise ValueError("invalid adapter settings")
        configured: set[str] = set()
        for entry in self.adapter_settings:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise ValueError("invalid adapter settings")
            adapter_id, values = entry
            _label(adapter_id)
            if adapter_id in configured:
                raise ValueError("duplicate adapter settings")
            configured.add(adapter_id)
            if not isinstance(values, tuple) or len(values) > MAX_SETTINGS:
                raise ValueError("invalid adapter setting values")
            names: set[str] = set()
            for pair in values:
                if not isinstance(pair, tuple) or len(pair) != 2:
                    raise ValueError("invalid adapter setting value")
                name, value = pair
                _setting_name(name)
                if name in names:
                    raise ValueError("duplicate adapter setting name")
                names.add(name)
                if type(value) not in {bool, int, str}:
                    raise ValueError("unsupported adapter setting value")


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
    adapter_settings: SettingValues = ()
    configuration_fingerprint: str | None = None
    input_format: str | None = None
    required_permissions: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.required_permissions is not None:
            _permissions(self.required_permissions)


def _effective_options(
    adapter: AdapterDescriptor, overrides: SettingValues
) -> SettingValues:
    specs = {spec.name: spec for spec in adapter.setting_specs}
    values = {name: spec.default for name, spec in specs.items()}
    for name, value in overrides:
        if name not in specs:
            raise ValueError("setting has no registered schema")
        specs[name].validate(value)
        values[name] = value
    return tuple(sorted(values.items()))


def _configuration_fingerprint(
    adapter: AdapterDescriptor, request: RouteRequirements, settings: EffectiveSettings
) -> str:
    projection = {
        "schema_version": "mumei.adapter-configuration/v1",
        "adapter_id": settings.adapter_id,
        "adapter_version": settings.adapter_version,
        "protocol_version": settings.protocol_version,
        "tool_version": settings.observed_tool_version,
        "location": settings.location,
        "timeout_ms": settings.timeout_ms,
        "memory_mb": settings.memory_mb,
        "request": request.to_dict(),
        "setting_specs": [
            spec.to_dict()
            for spec in sorted(adapter.setting_specs, key=lambda spec: spec.name)
        ],
        "effective_settings": dict(settings.adapter_settings),
    }
    if settings.required_permissions is not None:
        projection["required_permissions"] = sorted(settings.required_permissions)
    return hashlib.sha256(
        json.dumps(
            projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class VerificationPlan:
    request: RouteRequirements
    policy: PlannerPolicy
    selected: EffectiveSettings | None
    fallback_from: str | None
    decisions: tuple[AdapterDecision, ...]

    def to_dict(self) -> dict:
        request = self.request.to_dict()
        selected: dict[str, object] | None = None
        if self.selected is not None:
            selected = asdict(self.selected)
            selected.pop("result_contract")
            selected.pop("adapter_settings")
            selected.pop("configuration_fingerprint")
            selected.pop("input_format")
            selected.pop("required_permissions")
            if self.selected.result_contract is not None:
                selected["result_contract"] = self.selected.result_contract.to_dict()
            if self.selected.configuration_fingerprint is not None:
                selected["adapter_settings"] = dict(self.selected.adapter_settings)
                selected["configuration_fingerprint"] = (
                    self.selected.configuration_fingerprint
                )
            if self.selected.input_format is not None:
                selected["input_format"] = self.selected.input_format
            if self.selected.required_permissions is not None:
                selected["required_permissions"] = sorted(
                    self.selected.required_permissions
                )
        policy = {
            "selected_adapter": self.policy.selected_adapter,
            "allow_fallback": self.policy.allow_fallback,
            "disabled_adapters": sorted(self.policy.disabled_adapters),
            "allowed_locations": sorted(self.policy.allowed_locations),
            "tool_version_pins": dict(sorted(self.policy.tool_version_pins)),
            "timeout_ms": self.policy.timeout_ms,
            "memory_mb": self.policy.memory_mb,
        }
        if self.policy.allowed_permissions is not None:
            policy["allowed_permissions"] = sorted(self.policy.allowed_permissions)
        return {
            "schema_version": "mumei.verification-plan/v1",
            "request": request,
            "policy": policy,
            "selected": selected,
            "fallback_from": self.fallback_from,
            "decisions": [asdict(decision) for decision in self.decisions],
        }


@dataclass(frozen=True)
class PreparedSourceRequest:
    """Opaque in-memory input binding, never an execution or acceptance token.

    Use the registry preparation API to plan against current host declarations.
    The digest is raw-byte identity, not normalized specification identity.
    """

    plan: VerificationPlan
    source: bytes = field(repr=False)
    expected_source_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.plan, VerificationPlan):
            raise ValueError("invalid preparation plan")
        if (
            self.plan.selected is None
            or self.plan.request.input_format != SOURCE_INPUT_FORMAT
            or self.plan.request.result_contract is None
            or self.plan.selected.input_format != SOURCE_INPUT_FORMAT
            or self.plan.selected.result_contract != self.plan.request.result_contract
        ):
            raise ValueError(
                "source preparation requires an explicit selected contract and format"
            )
        allowed = self.plan.policy.allowed_permissions
        required = self.plan.selected.required_permissions
        if allowed is not None and (required is None or not required <= allowed):
            raise ValueError(
                "source preparation requires compatible permission metadata"
            )
        if not isinstance(self.expected_source_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.expected_source_sha256
        ):
            raise ValueError("invalid expected source identity")
        if (
            type(self.source) is not bytes
            or not 0 < len(self.source) <= MAX_SOURCE_BYTES
        ):
            raise ValueError("source must be bounded immutable bytes")
        text: str | None = None
        try:
            text = self.source.decode("utf-8")
        except UnicodeError:
            pass
        if text is None:
            raise ValueError("source must be UTF-8 text")
        if not text.strip() or "\x00" in text:
            raise ValueError("source must be nonempty text without NUL")
        if hashlib.sha256(self.source).hexdigest() != self.expected_source_sha256:
            raise ValueError("source identity mismatch")

    def to_dict(self) -> dict:
        manifest = {
            "schema_version": "mumei.prepared-source-request/v1",
            "plan": self.plan.to_dict(),
            "input": {
                "format": SOURCE_INPUT_FORMAT,
                "sha256": self.expected_source_sha256,
                "size_bytes": len(self.source),
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
        return {**manifest, "request_fingerprint": fingerprint}


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

    def register_manifest(self, manifest: dict, *, replace: bool = False) -> None:
        """Register a declared manifest; parsing is static, no code is loaded.

        This is the declarative add/replace path: a test user adapter can be
        described in a manifest and registered without editing core code.
        Loading, discovery, probing and execution stay host duties.
        """
        self.register(AdapterDescriptor.from_manifest(manifest), replace=replace)

    def prepare_source(
        self,
        request: RouteRequirements,
        policy: PlannerPolicy,
        observations: tuple[RuntimeObservation, ...],
        source: bytes,
        expected_source_sha256: str,
    ) -> PreparedSourceRequest:
        if (
            request.input_format != SOURCE_INPUT_FORMAT
            or request.result_contract is None
        ):
            raise ValueError(
                "source preparation requires an explicit contract and format"
            )
        return PreparedSourceRequest(
            self.plan(request, policy, observations), source, expected_source_sha256
        )

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
        overrides = dict(policy.adapter_settings)
        if any(key not in self._adapters for key in overrides):
            raise ValueError("settings have no registered adapter")
        options = {
            key: _effective_options(adapter, overrides.get(key, ()))
            for key, adapter in self._adapters.items()
        }
        ordered = sorted(
            self._adapters.values(), key=lambda a: (-a.priority, a.adapter_id)
        )
        reasons: dict[str, list[str]] = {}
        for adapter in ordered:
            excluded = reasons[adapter.adapter_id] = []
            if policy.allowed_permissions is not None:
                if adapter.required_permissions is None:
                    excluded.append("permission_requirements_not_declared")
                elif not adapter.required_permissions <= policy.allowed_permissions:
                    excluded.append("permissions_not_allowed")
            observed = runtime.get(adapter.adapter_id)
            if not adapter.enabled or adapter.adapter_id in policy.disabled_adapters:
                excluded.append("disabled")
            if adapter.protocol_version != PROTOCOL_VERSION:
                excluded.append("protocol_mismatch")
            if request.profile not in adapter.profiles:
                excluded.append("unsupported_semantic_profile")
            if request.method not in adapter.methods:
                excluded.append("unsupported_evidence_method")
            if request.input_format is not None:
                if not adapter.input_formats:
                    excluded.append("input_format_not_declared")
                elif request.input_format not in adapter.input_formats:
                    excluded.append("unsupported_input_format")
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
                options[selected.adapter_id],
                input_format=request.input_format,
                required_permissions=(
                    selected.required_permissions
                    if policy.allowed_permissions is not None
                    else None
                ),
            )
            if selected.setting_specs:
                settings = replace(
                    settings,
                    configuration_fingerprint=_configuration_fingerprint(
                        selected, request, settings
                    ),
                )
        return VerificationPlan(
            request, policy, settings, fallback_from, tuple(decisions)
        )
