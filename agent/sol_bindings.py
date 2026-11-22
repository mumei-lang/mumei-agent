"""Conservative single-file Solidity lexical binding reports."""

from __future__ import annotations

import argparse
import importlib
import re
import sys
import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from agent.lexical_bindings import (
    NON_ASSIGNABLE_WRITE_KINDS,
    Binding,
    ByteSpan,
    Call,
    Function,
    Gap,
    LexicalBindingReport,
    LexicalReportError,
    Reference,
    TypeFact,
    Unresolved,
    binding_id,
)


PROFILE = "mumei.sol-lexical-bindings/v1"
MAX_SOURCE_BYTES = 64 * 1024
_UNKNOWN = TypeFact("unknown", "", 0, None, "")
_BUILTINS = frozenset(
    {
        "msg",
        "block",
        "tx",
        "this",
        "super",
        "now",
        "require",
        "assert",
        "revert",
        "keccak256",
        "sha256",
        "ripemd160",
        "ecrecover",
        "addmod",
        "mulmod",
        "selfdestruct",
        "abi",
        "type",
        "gasleft",
        "blockhash",
        "blobhash",
    }
)
_UNITS = frozenset(
    {
        "wei",
        "gwei",
        "ether",
        "seconds",
        "minutes",
        "hours",
        "days",
        "weeks",
    }
)
_TYPE_BINDINGS = frozenset(
    {"contract", "interface", "library", "struct", "enum", "user_type", "import"}
)
_FUNCTION_BINDINGS = frozenset({"function", "modifier", "constructor"})
_CALL_OPTIONS = {"value", "gas", "salt"}
_PARAMETER_TYPE_TEXT = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*"
    r"(?:\s+payable)?"
    r"(?:\s*\[\s*(?:[A-Za-z_$][A-Za-z0-9_$.]*|\d+)?\s*\])*"
)


@dataclass(eq=False)
class _Record:
    binding: Binding
    node: Any
    type_node: Any | None = None
    owner: "_Contract | None" = None
    body: Any | None = None
    visibility: str = ""
    virtual: bool = False
    override: bool = False
    location: str = ""
    underlying: Any | None = None
    parameter_signature: tuple[str, ...] | None = None
    members: dict[str, "_Record"] = field(default_factory=dict)


@dataclass(eq=False)
class _Scope:
    kind: str
    node: Any
    contract: "_Contract | None"
    records: dict[str, list[_Record]]

    @property
    def span(self) -> ByteSpan:
        return ByteSpan(self.node.start_byte, self.node.end_byte)

    def add(self, record: _Record) -> None:
        self.records.setdefault(record.binding.name, []).append(record)


@dataclass(eq=False)
class _Using:
    library: str
    target: str  # "" means `for *`
    node: Any


@dataclass(eq=False)
class _Contract:
    record: _Record
    node: Any
    body: Any
    kind: str
    scope: _Scope
    bases: list[tuple[str, Any]]
    usings: list[_Using] | None = None
    external_base: bool = False
    base_gap_added: bool = False

    def __post_init__(self) -> None:
        if self.usings is None:
            self.usings = []


class _SolBindings:
    def __init__(self, source: str, raw: bytes, root: Any):
        self.source = source
        self.raw = raw
        self.root = root
        self.digest = __import__("hashlib").sha256(raw).hexdigest()
        self.file_scope = _Scope("file", root, None, {})
        self.scopes = [self.file_scope]
        self.bindings: list[Binding] = []
        self.records: list[_Record] = []
        self.functions: list[Function] = []
        self.references: list[Reference] = []
        self.unresolved: list[Unresolved] = []
        self.calls: list[Call] = []
        self.gaps: list[Gap] = []
        self.contracts: dict[str, _Contract] = {}
        self.type_records: dict[int, _Record] = {}
        self.current_contract: _Contract | None = None
        # `_resolve_member` results keyed by node span: a member
        # chain resolves its prefix once and shares it between the
        # contract path and the `using` fallback.
        self._member_resolution: dict[
            tuple[int, int], tuple[Any, Any, Any]
        ] = {}
        self.file_usings: list[_Using] = []
        self.call_owner = ""
        self.glob_imports: list[Any] = []

    def span(self, node: Any) -> ByteSpan:
        return ByteSpan(node.start_byte, node.end_byte)

    def text(self, node: Any | None) -> str:
        return "" if node is None else node.text.decode("utf-8", errors="replace")

    def children(self, node: Any | None) -> list[Any]:
        return (
            []
            if node is None
            else [child for child in node.named_children if child.type != "comment"]
        )

    def _scope_for_id(self, scope: ByteSpan | None) -> tuple[int, int]:
        if scope is None:
            return 0, 0
        return scope.start, scope.end

    def _add(
        self,
        scope: _Scope,
        name_node: Any,
        kind: str,
        *,
        binding_scope: ByteSpan | None,
        name_override: str | None = None,
        type_node: Any | None = None,
        owner: _Contract | None = None,
        body: Any | None = None,
        mutable: bool = False,
        visibility: str = "",
        virtual: bool = False,
        override: bool = False,
        location: str = "",
        underlying: Any | None = None,
        parameter_signature: tuple[str, ...] | None = None,
    ) -> _Record:
        name = name_override or self.text(name_node)
        scope_start, scope_end = self._scope_for_id(binding_scope)
        identifier = binding_id(
            self.digest, name_node.start_byte, scope_start, scope_end
        )
        binding = Binding(
            identifier,
            name,
            kind,
            self.span(name_node),
            binding_scope,
            _UNKNOWN,
            mutable,
        )
        record = _Record(
            binding,
            name_node,
            type_node,
            owner,
            body,
            visibility,
            virtual,
            override,
            location,
            underlying,
            parameter_signature,
        )
        self.records.append(record)
        self.bindings.append(binding)
        scope.add(record)
        return record

    def _add_gap(self, reason: str, node: Any) -> None:
        value = Gap(reason, self.span(node))
        if value not in self.gaps:
            self.gaps.append(value)

    def _add_ref(self, node: Any, record: _Record, kind: str) -> None:
        ref = Reference(self.span(node), record.binding.id, kind)
        if ref not in self.references:
            self.references.append(ref)

    def _add_unresolved(self, node: Any, name: str, reason: str) -> None:
        if any(item.span == self.span(node) for item in self.references):
            return
        value = Unresolved(self.span(node), name, reason)
        if value not in self.unresolved:
            self.unresolved.append(value)

    def _new_scope(
        self, kind: str, node: Any, contract: _Contract | None = None
    ) -> _Scope:
        return _Scope(kind, node, contract, {})

    def _contract_kind(self, node: Any) -> str:
        header = self.text(node).lstrip()
        match = re.match(r"(contract|interface|library)\b", header)
        return match.group(1) if match else "contract"

    def _predeclare(self) -> None:
        contract_nodes: list[Any] = []
        for node in self.children(self.root):
            if node.type == "import_directive":
                self._predeclare_import(node)
            elif node.type == "using_directive":
                using = self._parse_using(node)
                if using is not None:
                    self.file_usings.append(using)
            elif node.type in {
                "contract_declaration",
                "interface_declaration",
                "library_declaration",
            }:
                contract_nodes.append(node)
                name = node.child_by_field_name("name")
                if name is None:
                    continue
                kind = self._contract_kind(node)
                record = self._add(
                    self.file_scope,
                    name,
                    kind,
                    binding_scope=ByteSpan(0, 0),
                    owner=None,
                )
                body = node.child_by_field_name("body")
                if body is None:
                    continue
                scope = self._new_scope("contract", body)
                self.contracts[record.binding.name] = _Contract(
                    record, node, body, kind, scope, []
                )
            elif node.type == "function_definition":
                self._predeclare_function(node, self.file_scope, None)
            elif node.type in {
                "struct_declaration",
                "enum_declaration",
                "user_defined_type_definition",
                "error_declaration",
                "event_definition",
                "state_variable_declaration",
                "constant_variable_declaration",
            }:
                self._predeclare_item(node, self.file_scope, None)

        for node in contract_nodes:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            contract = self.contracts.get(self.text(name_node))
            if contract is None:
                continue
            for child in self.children(contract.node):
                if child.type == "inheritance_specifier":
                    ancestor = child.child_by_field_name("ancestor")
                    base_name = self._root_type_name(ancestor)
                    if base_name:
                        contract.bases.append((base_name, child))
            for child in self.children(contract.body):
                if child.type == "function_definition":
                    self._predeclare_function(child, contract.scope, contract)
                elif child.type == "constructor_definition":
                    self._predeclare_constructor(child, contract)
                elif child.type == "fallback_receive_definition":
                    continue
                elif child.type == "using_directive":
                    using = self._parse_using(child)
                    if using is not None:
                        contract.usings.append(using)
                elif child.type in {
                    "modifier_definition",
                    "struct_declaration",
                    "enum_declaration",
                    "user_defined_type_definition",
                    "error_declaration",
                    "event_definition",
                    "state_variable_declaration",
                    "constant_variable_declaration",
                }:
                    self._predeclare_item(child, contract.scope, contract)

        for contract in self.contracts.values():
            for name, node in contract.bases:
                base = self.file_scope.records.get(name, [])
                base_record = next(
                    (item for item in base if item.binding.kind in _TYPE_BINDINGS),
                    None,
                )
                if base_record is None or base_record.binding.kind not in {
                    "contract",
                    "interface",
                }:
                    contract.external_base = True

    def _parse_using(self, node: Any) -> _Using | None:
        # `using Lib for T` / `using Lib for *` parse cleanly; the
        # aliased set form `using {f as g} for T` produces an ERROR node
        # in this grammar version, so such directives are skipped
        # rather than mis-modeled.
        library = None
        target = ""
        for child in self.children(node):
            if child.type == "ERROR" or child.type == "using_alias":
                return None
            if child.type in {"type_alias", "user_defined_type"} and library is None:
                library = self.text(child)
            elif child.type == "type_name":
                target = self.text(child)
        if not library:
            return None
        return _Using(library, target, node)

    def _predeclare_import(self, node: Any) -> None:
        imported_names: list[Any] = []
        aliases: list[Any] = []
        pending: list[Any] = []
        for index, child in enumerate(node.children):
            field = node.field_name_for_child(index)
            if field == "import_name":
                pending.append(child)
                imported_names.append(child)
            elif field == "alias":
                aliases.append(child)
                preceding = next(
                    (
                        imported
                        for imported in reversed(pending)
                        if imported.end_byte <= child.start_byte
                    ),
                    None,
                )
                if preceding is not None:
                    pending.remove(preceding)
                self._add(
                    self.file_scope,
                    child,
                    "import",
                    binding_scope=ByteSpan(0, 0),
                )
        for imported in pending:
            self._add(
                self.file_scope,
                imported,
                "import",
                binding_scope=ByteSpan(0, 0),
            )
        if imported_names or aliases:
            return
        self.glob_imports.append(node)
        self._add_gap("glob_import", node)

    def _predeclare_function(
        self, node: Any, scope: _Scope, owner: _Contract | None
    ) -> _Record:
        name = node.child_by_field_name("name")
        if name is None:
            name = next(
                (child for child in self.children(node) if child.type == "identifier"),
                None,
            )
        if name is None:
            return self._add(
                scope,
                node,
                "function",
                binding_scope=ByteSpan(0, 0),
                owner=owner,
                body=node.child_by_field_name("body"),
            )
        return self._add(
            scope,
            name,
            "function",
            binding_scope=(
                self.span(owner.body)
                if owner is not None
                else ByteSpan(0, 0)
            ),
            owner=owner,
            body=node.child_by_field_name("body"),
            visibility=self._visibility(node),
            virtual=bool(re.search(r"\bvirtual\b", self.text(node))),
            override=bool(re.search(r"\boverride\b", self.text(node))),
            parameter_signature=self._parameter_signature(node),
        )

    def _predeclare_constructor(self, node: Any, owner: _Contract) -> _Record:
        return self._add(
            owner.scope,
            node,
            "constructor",
            binding_scope=None,
            name_override="constructor",
            owner=owner,
            body=node.child_by_field_name("body"),
        )

    def _predeclare_item(
        self, node: Any, scope: _Scope, owner: _Contract | None
    ) -> _Record | None:
        kind_by_node = {
            "struct_declaration": "struct",
            "enum_declaration": "enum",
            "user_defined_type_definition": "user_type",
            "error_declaration": "error",
            "event_definition": "event",
            "modifier_definition": "modifier",
            "state_variable_declaration": "state_variable",
            "constant_variable_declaration": "const",
        }
        kind = kind_by_node.get(node.type)
        if kind is None:
            return None
        name = node.child_by_field_name("name")
        if name is None:
            return None
        if kind == "state_variable" and owner is None:
            kind = "const" if "constant" in self.text(node).split() else "state_variable"
        elif kind == "const" and owner is not None:
            kind = "state_variable"
        if kind == "modifier":
            return self._add(
                scope,
                name,
                kind,
                binding_scope=self.span(owner.body) if owner else ByteSpan(0, 0),
                owner=owner,
                body=node.child_by_field_name("body"),
                virtual=False,
            )
        type_node = node.child_by_field_name("type")
        if kind == "state_variable" or kind == "const":
            mutable = not bool(
                re.search(r"\b(constant|immutable)\b", self.text(node))
            )
            location = "storage" if re.search(r"\bstorage\b", self.text(node)) else ""
            return self._add(
                scope,
                name,
                kind,
                binding_scope=self.span(owner.body) if owner else ByteSpan(0, 0),
                type_node=type_node,
                owner=owner,
                mutable=mutable,
                visibility=self._visibility(node),
                location=location,
            )
        underlying = None
        if kind == "user_type":
            underlying = next(
                (
                    child
                    for child in self.children(node)
                    if child.type
                    in {"type_name", "user_defined_type", "primitive_type"}
                    and child is not node.child_by_field_name("name")
                ),
                None,
            )
            type_node = underlying
        record = self._add(
            scope,
            name,
            kind,
            binding_scope=self.span(owner.body) if owner else ByteSpan(0, 0),
            type_node=type_node,
            owner=owner,
            underlying=underlying,
        )
        if kind in {"struct", "enum"}:
            self.type_records[record.binding.id] = record
            self._populate_type_members(record, node, owner)
        return record

    def _populate_type_members(
        self, record: _Record, node: Any, owner: _Contract | None
    ) -> None:
        member_scope = _Scope("type_members", node, owner, {})
        span = ByteSpan(node.start_byte, node.end_byte)
        if record.binding.kind == "struct":
            body = next(
                (child for child in self.children(node) if child.type == "struct_body"),
                None,
            )
            if body is None:
                return
            for member in self.children(body):
                if member.type != "struct_member":
                    continue
                field_name = member.child_by_field_name("name") or next(
                    (c for c in self.children(member) if c.type == "identifier"),
                    None,
                )
                if field_name is None:
                    continue
                record.members[self.text(field_name)] = self._add(
                    member_scope,
                    field_name,
                    "struct_field",
                    binding_scope=span,
                    type_node=member.child_by_field_name("type")
                    or next(
                        (c for c in self.children(member) if c.type == "type_name"),
                        None,
                    ),
                    owner=owner,
                    mutable=True,
                )
        elif record.binding.kind == "enum":
            body = next(
                (child for child in self.children(node) if child.type == "enum_body"),
                None,
            )
            if body is None:
                return
            for member in self.children(body):
                if member.type != "enum_value":
                    continue
                record.members[self.text(member)] = self._add(
                    member_scope,
                    member,
                    "enum_member",
                    binding_scope=span,
                    owner=owner,
                )

    def _visibility(self, node: Any) -> str:
        value = node.child_by_field_name("visibility")
        if value is not None:
            return self.text(value)
        match = re.search(r"\b(private|internal|public|external)\b", self.text(node))
        return "" if match is None else match.group(1)

    def _root_type_name(self, node: Any | None) -> str:
        if node is None:
            return ""
        if node.type == "identifier":
            return self.text(node)
        if node.type == "user_defined_type":
            identifiers = [item for item in self._walk(node) if item.type == "identifier"]
            return self.text(identifiers[0]) if identifiers else ""
        identifiers = [item for item in self._walk(node) if item.type == "identifier"]
        return self.text(identifiers[0]) if identifiers else ""

    def _walk(self, root: Any):
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "comment":
                continue
            yield node
            stack.extend(
                reversed([child for child in node.children if child.type != "comment"])
            )

    def _finalize_types(self) -> None:
        for record in self.records:
            fact = self._type_fact(record.type_node, record.owner, set())
            record.binding = replace(record.binding, type=fact)
        self.bindings = [record.binding for record in self.records]

    def _type_fact(
        self,
        node: Any | None,
        owner: _Contract | None,
        visited: set[str],
    ) -> TypeFact:
        if node is None:
            return _UNKNOWN
        if any(child.type in {"mapping", "["} for child in self._walk(node)):
            return _UNKNOWN
        name = self.text(node).strip()
        direct = name.replace(" ", "")
        if direct == "bool":
            return TypeFact("bool", "bool", 1, None, "")
        if direct in {"address", "addresspayable"}:
            return TypeFact(
                "address",
                "address payable" if direct.endswith("payable") else "address",
                160,
                False,
                "",
            )
        match = re.fullmatch(r"(u?int)([0-9]*)", direct)
        if match:
            width = int(match.group(2) or "256")
            if 8 <= width <= 256 and width % 8 == 0:
                return TypeFact("int", direct, width, match.group(1) == "int", "")
        match = re.fullmatch(r"bytes([1-9]|[12][0-9]|3[0-2])", direct)
        if match:
            width = int(match.group(1)) * 8
            return TypeFact("fixed_bytes", direct, width, False, "")
        root = self._root_type_name(node)
        record = self._lookup_type_record(root, node.start_byte, owner) if root else None
        if record is None:
            return _UNKNOWN
        if record.binding.kind == "user_type":
            if record.binding.id in visited:
                return TypeFact("unknown", name, 0, None, record.binding.id)
            visited.add(record.binding.id)
            underlying = self._type_fact(record.underlying, owner or record.owner, visited)
            if underlying.kind == "unknown":
                return TypeFact("unknown", name, 0, None, record.binding.id)
            return replace(underlying, type_id=record.binding.id)
        if record.binding.kind in {
            "contract",
            "interface",
            "library",
            "struct",
            "enum",
        }:
            return TypeFact("named", record.binding.name, 0, None, record.binding.id)
        return _UNKNOWN

    def _matching_records(
        self, records: list[_Record], position: int, namespace: str
    ) -> list[_Record]:
        result = []
        for record in records:
            kind = record.binding.kind
            if namespace == "type" and kind not in _TYPE_BINDINGS:
                continue
            scope = record.binding.scope
            if scope is None:
                continue
            if scope.start == 0 and scope.end == 0:
                result.append(record)
            elif scope.start <= position <= scope.end:
                result.append(record)
        return result

    def _choose(
        self, records: list[_Record]
    ) -> tuple[_Record | None, str | None]:
        if not records:
            return None, None
        functions = [record for record in records if record.binding.kind == "function"]
        if len(functions) > 1 and len(functions) == len(records):
            return None, "ambiguous_overload"
        return max(records, key=lambda item: item.binding.span.start), None

    def _lookup_type_record(
        self, name: str, position: int, owner: _Contract | None
    ) -> _Record | None:
        if owner is not None:
            inherited, _reason, _c = self._lookup_contract(
                name, owner, position, "type"
            )
            if inherited is not None:
                return inherited
        records = self.file_scope.records.get(name, [])
        found = self._matching_records(records, position, "type")
        record, _ambiguous = self._choose(found)
        return record

    def _lookup_contract(
        self,
        name: str,
        contract: _Contract,
        position: int,
        namespace: str,
        visited: set[str] | None = None,
        allow_private_own: bool = True,
        exclude_type_members: bool = False,
    ) -> tuple[_Record | None, str | None, list[_Record]]:
        # The third element is the surviving overload set — populated
        # only when the lookup ends in ``ambiguous_overload`` — so a
        # call site can resolve the winner by argument types.
        if namespace == "value":
            layers = self._contract_layers(
                name, contract, namespace, visited
            )
            functions: list[_Record] = []
            private_match = False
            for index, (_layer, records) in enumerate(layers):
                if exclude_type_members:
                    records = [
                        record
                        for record in records
                        if record.binding.kind not in _TYPE_BINDINGS
                    ]
                if not records:
                    continue
                if index > 0 or not allow_private_own:
                    private_match = private_match or any(
                        record.binding.kind in {"function", "state_variable"}
                        and record.visibility == "private"
                        for record in records
                    )
                    records = [
                        record
                        for record in records
                        if record.visibility != "private"
                    ]
                if not records:
                    continue
                if any(record.binding.kind != "function" for record in records):
                    if functions:
                        break
                    record, reason = self._choose(records)
                    return record, reason, []
                functions.extend(records)
            if functions:
                candidates = self._drop_overridden_functions(functions)
                record, reason = self._choose(candidates)
                return (
                    record,
                    reason,
                    candidates if reason == "ambiguous_overload" else [],
                )
            if private_match:
                return None, "private_base_member", []
            return None, None, []
        visited = set() if visited is None else visited
        if contract.record.binding.id in visited:
            return None, None, []
        visited.add(contract.record.binding.id)
        own = self._matching_records(
            contract.scope.records.get(name, []),
            contract.body.start_byte,
            namespace,
        )
        if own:
            record, reason = self._choose(own)
            return (
                record,
                reason,
                own if reason == "ambiguous_overload" else [],
            )
        for base_name, _base_node in reversed(contract.bases):
            base = self.contracts.get(base_name)
            if base is None:
                continue
            record, reason, candidates = self._lookup_contract(
                name, base, position, namespace, visited
            )
            if reason is not None:
                return None, reason, candidates
            if record is not None:
                if record.visibility == "private":
                    return None, "private_base_member", []
                return record, None, []
        return None, None, []

    def _resolve_member(
        self, node: Any
    ) -> tuple[Any | None, _Record | None, str | None]:
        cached = self._member_resolution.get(
            (node.start_byte, node.end_byte)
        )
        if cached is not None:
            return cached
        result = self._resolve_member_uncached(node)
        self._member_resolution[
            (node.start_byte, node.end_byte)
        ] = result
        return result

    def _resolve_member_uncached(
        self, node: Any
    ) -> tuple[Any | None, _Record | None, str | None]:
        """Resolve `object.property` when the object has a declared
        contract/interface/library type or names one directly.

        Returns the member name node, the member record and a failure
        reason. When the object's declared type is not a contract kind —
        a struct, enum, elementary type, mapping or array — the triple
        carries no record and no reason: builtin members (`.length`,
        `.balance`) and struct fields stay unmodeled rather than being
        guessed, so the member position keeps its pre-existing opaque
        treatment.
        """
        member = node.child_by_field_name("property")
        if member is None or member.type != "identifier":
            return None, None, None
        name = self.text(member)
        obj = self._unwrap(node.child_by_field_name("object"))
        if obj is None:
            return member, None, None
        text = self.text(obj)
        if obj.type == "identifier" and text == "super":
            owner = self.current_contract
            if owner is not None:
                # `super` resolves among every contract after this one
                # in the C3 linearization: private members are invisible
                # to derived contracts and skipped, overridden
                # same-signature definitions drop out, a lone surviving
                # signature binds to the most derived definition, and a
                # mixed-signature overload set stays opaque. The DFS
                # layer walk would emit a base's ancestors before a
                # sibling base under diamonds, so the merge has to be
                # done explicitly.
                saw_private = False
                functions: list[_Record] = []
                for base in self._linearized_bases(owner):
                    records = self._matching_records(
                        base.scope.records.get(name, []),
                        base.body.start_byte,
                        "value",
                    )
                    visible = [
                        record
                        for record in records
                        if record.visibility != "private"
                        and record.binding.kind not in _TYPE_BINDINGS
                    ]
                    saw_private = saw_private or len(visible) < len(records)
                    if not visible:
                        continue
                    if any(
                        record.binding.kind != "function"
                        for record in visible
                    ):
                        if functions:
                            break
                        record, reason = self._choose(visible)
                        return member, record, reason
                    functions.extend(visible)
                functions = self._drop_overridden_functions(functions)
                if len(functions) == 1:
                    return member, functions[0], None
                if functions:
                    # Same signature in several unrelated bases resolves
                    # to the most derived, the first in linearization
                    # order; differing signatures — or any signature the
                    # scanner could not pin down — form an overload set
                    # the call resolves against, which stays opaque.
                    signatures = {
                        record.parameter_signature for record in functions
                    }
                    if len(signatures) == 1 and None not in signatures:
                        return member, functions[0], None
                    # `super.f` is explicit dispatch — `using`
                    # extensions never enter the candidate set — but
                    # the overload set itself is still resolved by the
                    # call's argument types.
                    winner, _outcome = self._resolve_overload(
                        [(item, 0) for item in functions], node
                    )
                    if winner is not None:
                        return member, winner, None
                    return member, None, "ambiguous_overload"
                if saw_private:
                    return member, None, "private_base_member"
            return member, None, None
        contract = None
        type_record = None
        enum_via_type_name = False
        via_type_name = False
        inside_owner = False
        reason = None
        if obj.type == "identifier" and text == "this":
            contract = self.current_contract
            inside_owner = True
        elif obj.type == "identifier":
            record, _reason = self._lookup(text, obj.start_byte, "value")
            if record is None:
                record, _reason = self._lookup(text, obj.start_byte, "type")
            if record is not None:
                if record.binding.kind in {"contract", "interface", "library"}:
                    contract = self.contracts.get(record.binding.name)
                    via_type_name = True
                elif record.binding.kind == "enum":
                    type_record = record
                    enum_via_type_name = True
                    via_type_name = True
                elif record.type_node is not None and re.match(
                    r"\s*function\b", self.text(record.type_node)
                ):
                    # Function-typed variables carry builtin members
                    # (`cb.selector`); the signature's return struct
                    # must not leak fields into this position.
                    pass
                else:
                    fact = self._type_fact(
                        record.type_node, record.owner, set()
                    )
                    # A qualified declared type `Lib.S` still roots at
                    # `Lib`, so `fact.type_id` names the library, not the
                    # struct — leave such member positions opaque rather
                    # than binding fields to library-level declarations.
                    if (
                        fact.type_id is not None
                        and record.type_node is not None
                        and "." not in self.text(record.type_node)
                    ):
                        type_record = self.type_records.get(fact.type_id)
                        if type_record is None:
                            contract = next(
                                (
                                    candidate
                                    for candidate in self.contracts.values()
                                    if candidate.record.binding.id == fact.type_id
                                ),
                                None,
                            )
        elif obj.type == "member_expression":
            # Member chains (`vault.coin.v`): resolve the inner member
            # first, then use its declared type. A nested type name
            # (`Container.State.Ready`) supplies the type record itself
            # — its declaration has no type annotation to look through.
            _inner_member, inner, _inner_reason = self._resolve_member(obj)
            if inner is not None:
                if inner.binding.kind in {
                    "contract",
                    "interface",
                    "library",
                    "struct",
                    "enum",
                }:
                    type_record = inner
                    enum_via_type_name = inner.binding.kind == "enum"
                    via_type_name = True
                else:
                    type_record = self._type_record_for_type_node(
                        inner.type_node, inner.owner
                    )
        elif obj.type == "array_access":
            # `tokens[0].transfer()`: the element type of a contract
            # array is contract-typed.
            base = self._unwrap(obj.child_by_field_name("base"))
            base_record = self._object_record(base)
            type_record = self._array_element_type_record(base_record)
            if type_record is None:
                # `nested[k1][k2]` — the base indexes into a mapping's
                # mapping value, so no binding record exists; its type
                # still peels through declared-type text, in the scope
                # that spelled it.
                declared = self._object_declared_type(base)
                if declared is not None:
                    element = self._index_value_type_text(declared[0])
                    type_record = self._user_type_record(
                        element, declared[1], member.start_byte
                    )
        elif obj.type == "call_expression":
            type_record = self._call_return_type_record(obj)
        if contract is None and type_record is not None and (
            type_record.binding.kind in {"contract", "interface", "library"}
        ):
            contract = self.contracts.get(type_record.binding.name)
        if contract is not None:
            inside_owner = inside_owner or (
                self.current_contract is not None
                and contract is self.current_contract
            )
            # Nested type declarations are reachable through the
            # contract name only; on an instance (`inst.S(...)`) the
            # member position skips them, so an inherited same-named
            # function or a `using` extension owns the call instead.
            record, reason, candidates = self._lookup_contract(
                name,
                contract,
                member.start_byte,
                "value",
                allow_private_own=inside_owner,
                exclude_type_members=not via_type_name,
            )
            if (
                record is not None
                and record.binding.kind != "function"
            ):
                return member, record, reason
            member_pool = (
                [record] if record is not None else candidates
            )
            if member_pool:
                # solc resolves `x.f(...)` by argument-dependent
                # lookup over ONE set: member overloads plus every
                # `using` extension applicable to the receiver's type.
                # A member that cannot take the call's arguments loses
                # to an applicable extension (verified: `inst.f("x")`
                # with only f(uint256)/f(address) members binds the
                # f(D,string) extension; a single member that cannot
                # convert the argument is a compile error, not a bind).
                pool = [(item, 0) for item in member_pool]
                if self._call_argument_exprs(node) is not None:
                    seen = {item.binding.id for item in member_pool}
                    pool += [
                        (item, 1)
                        for item in self._using_candidates(
                            name, obj, member.start_byte
                        )[0]
                        if item.binding.id not in seen
                    ]
                winner, _outcome = self._resolve_overload(pool, node)
                if winner is not None:
                    return member, winner, None
                return member, None, "ambiguous_overload"
            # A lookup that ended on an invisible private member does
            # not close the position: solc treats the member as absent,
            # so a `using` extension still owns the call.
        if type_record is not None:
            # Enum constants only resolve through the type name
            # (`Status.Ready`): on an enum-typed value they would shadow
            # a same-named `using` extension, which solc prefers.
            if type_record.binding.kind != "enum" or enum_via_type_name:
                found = type_record.members.get(name)
                if found is not None:
                    return member, found, None
        using_record, using_reason = self._lookup_using(
            name, obj, member.start_byte, node
        )
        if using_record is not None or using_reason is not None:
            return member, using_record, using_reason
        return member, None, reason

    def _object_declared_type_text(self, obj: Any) -> str | None:
        declared = self._object_declared_type(obj)
        return declared[0] if declared is not None else None

    def _object_declared_type(
        self, obj: Any
    ) -> "tuple[str, _Contract | None] | None":
        """Declared-type text of a member-call receiver together with
        the scope that spelling resolves in, or None when the object's
        type cannot be named statically. Identifier objects keep the
        original variable lookup; member chains (`coin.v.f()`), array
        elements (`totals[0].f()`), calls returning a named type
        (`getTotal().f()`, `total.add(1).sub(2)`) and type conversions
        (`Token(addr).f()`) reuse the same type-node machinery as the
        contract path. The owner matters for user-defined types:
        `A.get()` returning `S` spells `S` inside `A`, not in the
        call site's contract.
        """
        obj = self._unwrap(obj)
        if obj is None:
            return None
        if obj.type == "identifier":
            if self.text(obj) in {"this", "super"}:
                return None
            record, _reason = self._lookup(
                self.text(obj), obj.start_byte, "value"
            )
            if (
                record is None
                or record.type_node is None
                or record.binding.kind
                in {"contract", "interface", "library"}
            ):
                return None
            return self.text(record.type_node), record.owner
        if obj.type == "member_expression":
            _member, inner, _reason = self._resolve_member(obj)
            if inner is None or inner.type_node is None:
                return None
            return self.text(inner.type_node), inner.owner
        if obj.type == "array_access":
            base = self._unwrap(obj.child_by_field_name("base"))
            base_record = self._object_record(base)
            if base_record is not None and base_record.type_node is not None:
                owner = base_record.owner
                text = re.sub(
                    r"\b(memory|calldata|storage)\b",
                    "",
                    self.text(base_record.type_node),
                )
            else:
                # `nested[k1]` carries no binding record, but its type
                # text still comes from the same peel — a nested
                # mapping value indexes to its own value type.
                declared = self._object_declared_type(base)
                if declared is None:
                    return None
                text, owner = declared
            # `mapping(K => V)` indexes to V and `bytes` to `bytes1`.
            element = self._index_value_type_text(text)
            if element is None:
                return None
            return element, owner
        if obj.type == "type_cast_expression":
            # `uint(1)`-style elementary conversions — the value is
            # typed by the cast's primitive type so `using` directives
            # still apply.
            type_node = next(
                (
                    child
                    for child in self.children(obj)
                    if child.type in {"primitive_type", "type_name"}
                ),
                None,
            )
            if type_node is None:
                return None
            return (
                re.sub(r"\s+", " ", self.text(type_node)).strip(),
                self.current_contract,
            )
        if obj.type == "call_expression":
            callee = self._unwrap(obj.child_by_field_name("function"))
            record = self._object_record(callee)
            if record is None:
                return None
            if record.binding.kind in {
                "contract",
                "interface",
                "library",
                "struct",
                "enum",
            }:
                # `Token(addr)` / `Coin(...)` — the value is typed by
                # the declared type itself. A qualified callee keeps
                # its dotted name (`Container.Coin(1)`): using targets
                # spell the type the same way. The name resolved at
                # the call site, so it re-resolves in the call site's
                # scope.
                if callee.type == "member_expression":
                    return self.text(callee), self.current_contract
                return record.binding.name, self.current_contract
            if record.binding.kind != "function":
                if record.type_node is None or re.match(
                    r"\s*function\b", self.text(record.type_node)
                ):
                    return None
                text = self.text(record.type_node)
                if callee.type == "member_expression":
                    # A public getter on an indexable member peels one
                    # level per index argument: `this.values(0)` is a
                    # `uint256`, `this.grid(0, 0)` on `uint256[][]` a
                    # `uint256`, `this.b(0)` on `bytes` a `bytes1`. The
                    # no-argument getter returns the whole value.
                    args = sum(
                        1
                        for child in self.children(obj)
                        if child.type == "call_argument"
                    )
                    for _ in range(args):
                        peeled = self._index_value_type_text(text)
                        if peeled is None:
                            break
                        text = peeled
                # A public getter on a struct-typed member — directly or
                # as a mapping's value — returns the exploded fields as
                # a tuple, not the type, so no extension target exists.
                # An enum value comes back as the enum type itself.
                resolved = self._user_type_record(
                    text, record.owner, record.node.start_byte
                )
                if (
                    resolved is not None
                    and resolved.binding.kind == "struct"
                ):
                    return None
                return text, record.owner
            function_node = record.node.parent
            if function_node is None:
                return None
            returns = self._return_parameters(function_node)
            if not returns:
                return None
            type_node = returns[0].child_by_field_name("type")
            if type_node is None or re.match(
                r"\s*function\b", self.text(type_node)
            ):
                return None
            # The returns clause is spelled inside the callee's
            # declaring contract (`A.get(): returns (S)` means `A.S`),
            # not the caller's.
            return self.text(type_node), record.owner
        return None

    def _using_candidates(
        self, name: str, obj: Any, position: int
    ) -> tuple[list[_Record], str | None]:
        """`using Lib for T` candidates for `obj.name`: the object's
        declared type text must equal the directive's `for` target, or
        the directive must be `for *`. Objects whose type cannot be
        named statically (nested mappings, nested arrays,
        function-typed returns) keep their opaque treatment.
        """
        declared = self._object_declared_type(obj)
        if declared is None:
            return [], None
        raw_text, type_owner = declared
        type_text = self._canonical_type_text(raw_text)
        directives = list(self.file_usings)
        if self.current_contract is not None:
            directives.extend(self.current_contract.usings)
        candidates: list[_Record] = []
        first_reason: str | None = None
        for directive in directives:
            if directive.target:
                target_text = self._canonical_type_text(directive.target)
                if target_text != type_text:
                    target_record = self._user_type_record(
                        target_text, self.current_contract, position
                    )
                    receiver_record = self._user_type_record(
                        type_text, type_owner, position
                    )
                    if (
                        target_record is None
                        or receiver_record is None
                        or target_record.binding.id
                        != receiver_record.binding.id
                    ):
                        continue
            library = self.contracts.get(directive.library)
            if library is None or library.kind != "library":
                continue
            member_record, member_reason, member_candidates = (
                self._lookup_contract(
                    name,
                    library,
                    position,
                    "value",
                    allow_private_own=False,
                )
            )
            pool = (
                [member_record]
                if member_record is not None
                else member_candidates
            )
            for item in pool:
                signature = item.parameter_signature
                if (
                    signature
                    and self._param_accepts(
                        signature[0],
                        "typed",
                        type_text,
                        param_owner=item.owner,
                        arg_owner=type_owner,
                        position=position,
                    )
                    == "nomatch"
                ):
                    # A `for *` directive admits every name, but a
                    # function still only applies when the receiver
                    # implicitly converts to its first parameter.
                    continue
                if all(
                    candidate.binding.id != item.binding.id
                    for candidate in candidates
                ):
                    candidates.append(item)
            if (
                member_reason is not None
                and member_reason != "ambiguous_overload"
                and first_reason is None
            ):
                first_reason = member_reason
        return candidates, first_reason

    def _lookup_using(
        self,
        name: str,
        obj: Any,
        position: int,
        member_node: Any | None = None,
    ) -> tuple[_Record | None, str | None]:
        """Resolve `x.f` through `using Lib for T` directives when the
        contract-type path found no member. The extension's first
        parameter is the receiver, so argument matching skips it. On a
        non-call member position (`x.f` as a value) a single candidate
        binds and several stay an overload set, as before.
        """
        candidates, first_reason = self._using_candidates(
            name, obj, position
        )
        if not candidates:
            return None, first_reason
        if member_node is not None:
            winner, _outcome = self._resolve_overload(
                [(item, 1) for item in candidates], member_node
            )
            if winner is not None:
                return winner, None
            return None, "ambiguous_overload"
        if len(candidates) > 1:
            return None, "ambiguous_overload"
        return candidates[0], None

    def _call_argument_exprs(self, member_node: Any) -> list[Any] | None:
        """Argument expressions when `member_node` (`x.f`) is the callee
        of a `call_expression`, else None — non-call member positions
        cannot be disambiguated by argument types.
        """
        parent = member_node.parent
        if parent is not None and parent.type == "expression":
            parent = parent.parent
        if parent is None or parent.type != "call_expression":
            return None
        callee = self._unwrap(parent.child_by_field_name("function"))
        if (
            callee is None
            or (callee.start_byte, callee.end_byte)
            != (member_node.start_byte, member_node.end_byte)
        ):
            return None
        # Named arguments (`f({y: true, x: 1})`) reorder by parameter
        # name — the scanner has no parameter names to reorder by, so
        # the position falls back to name-only resolution.
        for child in self.children(parent):
            if child.type != "call_argument":
                continue
            if any(
                inner.type == "call_struct_argument"
                for inner in self.children(child)
            ):
                return None
        _spans, expressions = self._call_arguments(parent)
        return [self._unwrap(expr) for expr in expressions]

    def _argument_kind(
        self, arg: Any
    ) -> "tuple[str, str | None, _Contract | None]":
        """Best-effort type of a call argument: a literal marker for
        literals, the canonical declared-type text for expressions the
        receiver-type machinery can name plus the scope that spelling
        resolves in, or ``("unknown", None, None)``.
        """
        arg = self._unwrap(arg)
        if arg is None:
            return "unknown", None, None
        if arg.type == "number_literal":
            return "literal_int", self.text(arg), None
        if arg.type == "string_literal":
            return "literal_string", None, None
        if arg.type == "boolean_literal":
            return "literal_bool", None, None
        declared = self._object_declared_type(arg)
        if declared is not None:
            text, owner = declared
            return "typed", self._canonical_type_text(text), owner
        return "unknown", None, None

    @staticmethod
    def _int_width(text: str) -> tuple[bool, int] | None:
        match = re.fullmatch(r"(u?)int(\d*)", text)
        if match is None:
            return None
        width = int(match.group(2)) if match.group(2) else 256
        return (match.group(1) == "u"), width

    @staticmethod
    def _bytes_width(text: str) -> int | None:
        match = re.fullmatch(r"bytes(\d{1,2})", text)
        if match is None:
            return None
        return int(match.group(1))

    def _implicitly_converts(self, arg: str, param: str) -> bool:
        """Whether a value of canonical type `arg` implicitly converts
        to a parameter of canonical type `param` (widening only —
        narrowing and signed→unsigned are not implicit).
        """
        if arg == param:
            return True
        arg_int = self._int_width(arg)
        param_int = self._int_width(param)
        if arg_int is not None and param_int is not None:
            arg_unsigned, arg_width = arg_int
            param_unsigned, param_width = param_int
            if arg_unsigned and param_unsigned:
                return param_width >= arg_width
            if not arg_unsigned and not param_unsigned:
                return param_width >= arg_width
            if arg_unsigned:
                # uintN -> intM needs strictly more width.
                return param_width > arg_width
            return False
        arg_bytes = self._bytes_width(arg)
        if arg_bytes is not None:
            if param == "bytes":
                return True
            param_bytes = self._bytes_width(param)
            return param_bytes is not None and param_bytes >= arg_bytes
        if arg == "address payable" and param == "address":
            return True
        return False

    def _user_type_record(
        self, text: str | None, owner: "_Contract | None", position: int
    ) -> "_Record | None":
        """Resolve a canonical user-type spelling to its declaration
        record, so a qualified spelling (`L.S`) and the scope-local
        spelling the declaring scope uses (`S` inside `L`) compare by
        identity rather than by text.
        """
        if not text:
            return None
        parts = text.split(".")
        if len(parts) == 1:
            return self._lookup_type_record(parts[0], position, owner)
        if len(parts) != 2:
            return None
        container = self.contracts.get(parts[0])
        if container is None:
            return None
        record, _reason, _candidates = self._lookup_contract(
            parts[1], container, position, "type"
        )
        return record

    def _param_accepts(
        self,
        param_text: str,
        arg_kind: str,
        arg_text: str | None,
        *,
        param_owner: "_Contract | None" = None,
        arg_owner: "_Contract | None" = None,
        position: int = 0,
    ) -> str:
        """`match` / `convert` / `nomatch` for one parameter against one
        call argument. Literals carry only a kind (a numeric literal's
        value — and so its smallest fitting type — is unknown, matching
        solc's ambiguity for `f(1)` across integer overloads).
        """
        param = self._canonical_type_text(
            re.sub(
                r"\b(memory|calldata|storage)\b", "", param_text
            ).strip()
        )
        if arg_kind == "unknown":
            return "convert"
        if arg_kind == "literal_int":
            if re.fullmatch(
                r"0x[0-9a-fA-F]{40}", arg_text or ""
            ):
                # A 40-hex-digit literal is an address literal.
                return (
                    "match"
                    if param in {"address", "address payable"}
                    else "nomatch"
                )
            return (
                "convert"
                if self._int_width(param) is not None
                else "nomatch"
            )
        if arg_kind == "literal_string":
            if (
                param == "string"
                or param == "bytes"
                or self._bytes_width(param) is not None
            ):
                return "convert"
            return "nomatch"
        if arg_kind == "literal_bool":
            return "convert" if param == "bool" else "nomatch"
        if arg_text == param:
            return "match"
        if arg_text is not None and self._implicitly_converts(
            arg_text, param
        ):
            return "convert"
        param_record = self._user_type_record(
            param, param_owner, position
        )
        arg_record = self._user_type_record(
            arg_text, arg_owner, position
        )
        if param_record is not None and arg_record is not None:
            if param_record.binding.id == arg_record.binding.id:
                return "match"
            if (
                arg_record.binding.kind in {"contract", "interface"}
                and param_record.binding.kind
                in {"contract", "interface"}
                and self._contract_subtype(arg_record, param_record)
            ):
                # A derived contract value implicitly converts to any
                # contract it inherits from (`m[i]` yields `Derived`;
                # `f(Base)` still takes it).
                return "convert"
        return "nomatch"

    def _contract_subtype(self, arg: _Record, param: _Record) -> bool:
        """Whether the argument contract's declared base chain reaches
        the parameter contract."""
        start = self.contracts.get(arg.binding.name)
        seen: set[str] = set()
        stack = [start] if start is not None else []
        while stack:
            contract = stack.pop()
            if contract.record.binding.id in seen:
                continue
            seen.add(contract.record.binding.id)
            for base_name, _node in contract.bases:
                base = self.contracts.get(base_name)
                if base is None:
                    continue
                if base.record.binding.id == param.binding.id:
                    return True
                stack.append(base)
        return False

    def _resolve_overload(
        self, pool: list[tuple[_Record, int]], member_node: Any
    ) -> tuple[_Record | None, str]:
        """Argument-driven overload resolution over `pool` of
        `(record, leading_params_to_skip)` pairs — extensions skip
        their receiver parameter. Returns the winning record and a
        status: ``ok``, ``none`` (no candidate can take the args) or
        ``ambiguous``. A non-call member position keeps name-only
        semantics: a lone candidate binds, a set stays ambiguous.
        """
        args = self._call_argument_exprs(member_node)
        if args is None:
            if len(pool) == 1:
                return pool[0][0], "ok"
            return None, "ambiguous"
        survivors: list[tuple[_Record, int]] = []
        for record, skip in pool:
            signature = record.parameter_signature
            if signature is None:
                # Parameters the scanner could not pin down stay in
                # the set but can never outrank a known candidate.
                survivors.append((record, -1))
                continue
            params = signature[skip:]
            if len(params) != len(args):
                continue
            rank = 0
            viable = True
            for param, arg in zip(params, args):
                kind, arg_text, arg_owner = self._argument_kind(arg)
                verdict = self._param_accepts(
                    param,
                    kind,
                    arg_text,
                    param_owner=record.owner,
                    arg_owner=arg_owner,
                    position=member_node.start_byte,
                )
                if verdict == "nomatch":
                    viable = False
                    break
                if verdict == "match":
                    rank += 1
            if viable:
                survivors.append((record, rank))
        if len(survivors) == 1:
            return survivors[0][0], "ok"
        if not survivors:
            return None, "none"
        if any(
            self._argument_kind(arg)[0] == "unknown"
            for arg in args
        ):
            # An argument whose type cannot be named could be an exact
            # match for any survivor — solc would still disambiguate,
            # but ranking here could pick a wrong winner, so the set
            # stays ambiguous rather than binding the best-ranked.
            return None, "ambiguous"
        best = max(rank for _record, rank in survivors)
        winners = [
            record
            for record, rank in survivors
            if rank == best and record.parameter_signature is not None
        ]
        if len(winners) == 1 and best >= 0:
            return winners[0], "ok"
        return None, "ambiguous"

    def _type_record_for_type_node(
        self, type_node: Any | None, owner: _Contract | None
    ) -> _Record | None:
        if type_node is None or "." in self.text(type_node):
            return None
        if re.match(r"\s*function\b", self.text(type_node)):
            # A function-typed slot (`S(cb).cb.selector`) carries
            # builtin members; `_type_fact` would root at the
            # signature's return struct and leak its fields.
            return None
        fact = self._type_fact(type_node, owner, set())
        if fact.type_id is None:
            return None
        record = self.type_records.get(fact.type_id)
        if record is not None:
            return record
        return next(
            (
                candidate.record
                for candidate in self.contracts.values()
                if candidate.record.binding.id == fact.type_id
            ),
            None,
        )

    def _object_record(self, obj: Any | None) -> _Record | None:
        if obj is None:
            return None
        if obj.type == "identifier":
            record, _reason = self._lookup(
                self.text(obj), obj.start_byte, "value"
            )
            if record is None:
                record, _reason = self._lookup(
                    self.text(obj), obj.start_byte, "type"
                )
            return record
        if obj.type == "member_expression":
            _member, record, _reason = self._resolve_member(obj)
            return record
        if obj.type == "new_expression":
            type_name = next(
                (
                    child
                    for child in self.children(obj)
                    if child.type == "type_name"
                ),
                None,
            )
            if type_name is not None and "[" in self.text(type_name):
                # `new Token[](1)` yields an array, not a contract.
                return None
            root = self._root_type_name(type_name)
            if root:
                return self._lookup_type_record(root, obj.start_byte, None)
        return None

    @staticmethod
    def _mapping_value_type_text(text: str) -> str | None:
        """`mapping(K => V)` → `V`; the `=>` separator is found at
        paren depth one. Anything else returns None.
        """
        text = text.strip()
        if not text.startswith("mapping"):
            return None
        depth = 0
        for index, char in enumerate(text):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif (
                char == "="
                and depth == 1
                and text[index : index + 2] == "=>"
            ):
                value = text[index + 2 :].strip()
                if value.endswith(")"):
                    value = value[:-1].strip()
                # `address\npayable` and other loose spacing is one
                # spelling to solc — collapse it before the guards.
                value = re.sub(r"\s+", " ", value)
                if re.fullmatch(
                    r"u?int[0-9]*|bytes[0-9]*|byte|address payable|address|bool|string",
                    value,
                ) is None:
                    named = re.fullmatch(
                        r"(.+?)\s+[A-Za-z_$][A-Za-z0-9_$]*",
                        value,
                        re.S,
                    )
                    if named is not None:
                        # `mapping(K => U slot)` names the value slot —
                        # the name is not part of the type. Builtin
                        # multi-word spellings (`address payable`) were
                        # kept whole by the guard above.
                        value = named.group(1).strip()
                return value
        return None

    def _index_value_type_text(self, text: str) -> str | None:
        """One index level peeled off a declared-type text: the mapping
        value, the array element type or `bytes1` for dynamic `bytes`.
        None when the text is not indexable (a nested array peels one
        dimension but stays unnamed downstream)."""
        mapping_value = self._mapping_value_type_text(text)
        if mapping_value is not None:
            return mapping_value
        if text.strip() == "bytes":
            return "bytes1"
        element = re.sub(r"\[[^\]]*\]\s*$", "", text).strip()
        if element == text.strip():
            return None
        return element

    def _array_element_type_record(
        self, record: _Record | None
    ) -> _Record | None:
        if record is None or record.type_node is None:
            return None
        if self.text(record.type_node).lstrip().startswith("mapping"):
            # `m[k]` on `mapping(K => V)` is V-typed; the value type is
            # the `type_name` child after `=>`. A nested mapping value
            # has no member surface.
            value_node = next(
                (
                    child
                    for child in self.children(record.type_node)
                    if child.type == "type_name"
                ),
                None,
            )
            if value_node is None:
                return None
            resolved = self._type_record_for_type_node(
                value_node, record.owner
            )
            if resolved is not None and resolved.binding.kind in {
                "contract",
                "interface",
                "library",
                "struct",
                "enum",
            }:
                return resolved
            return None
        text = re.sub(
            r"\b(memory|calldata|storage)\b", "", self.text(record.type_node)
        )
        # Strip one array dimension; anything left that still indexes
        # (nested arrays) has no member surface.
        element = re.sub(r"\[[^\]]*\]\s*$", "", text).strip()
        if element == text.strip() or "[" in element:
            return None
        base = self._lookup_type_record(element, record.node.start_byte, record.owner)
        if base is None or base.binding.kind not in {
            "contract",
            "interface",
            "library",
            "struct",
        }:
            return None
        return base

    def _call_return_type_record(self, call: Any) -> _Record | None:
        callee = self._unwrap(call.child_by_field_name("function"))
        record = self._object_record(callee)
        if record is None:
            return None
        if record.binding.kind in {
            "contract",
            "interface",
            "library",
            "struct",
            "enum",
        }:
            # `new Token()` / `Token(addr)` / `Coin(1)` / `Status(0)` —
            # the value is typed by the declaration itself.
            return record
        if record.binding.kind != "function":
            if record.type_node is not None and not re.match(
                r"\s*function\b", self.text(record.type_node)
            ):
                # Getter-style call on a declared variable, e.g.
                # `this.token().f()` — the value has the variable's
                # declared type. Function-typed variables (`cb(t)`)
                # would root at the signature's first identifier. A
                # struct-typed public getter returns the exploded
                # fields as a tuple, so it carries no member surface;
                # an enum value comes back as the enum type itself.
                text = self.text(record.type_node)
                if callee.type == "member_expression":
                    # An indexable member's getter peels one level per
                    # index argument (`this.tokens(k)` on
                    # `mapping(uint => Token)` returns `Token`), the
                    # same peel `_object_declared_type_text` applies.
                    args = sum(
                        1
                        for child in self.children(call)
                        if child.type == "call_argument"
                    )
                    peeled = False
                    for _ in range(args):
                        value = self._index_value_type_text(text)
                        if value is None:
                            break
                        text = value
                        peeled = True
                    if peeled:
                        resolved = self._user_type_record(
                            text, record.owner, call.start_byte
                        )
                        if (
                            resolved is not None
                            and resolved.binding.kind == "struct"
                        ):
                            return None
                        return resolved
                resolved = self._type_record_for_type_node(
                    record.type_node, record.owner
                )
                if (
                    resolved is not None
                    and resolved.binding.kind == "struct"
                ):
                    return None
                return resolved
            return None
        function_node = record.node.parent
        if function_node is None:
            return None
        returns = self._return_parameters(function_node)
        if not returns:
            return None
        type_node = returns[0].child_by_field_name("type")
        if type_node is not None and re.match(
            r"\s*function\b", self.text(type_node)
        ):
            # A function-typed return (`returns (function() ...)`) has
            # no contract member surface; `_type_fact` would root at the
            # first identifier inside the signature.
            return None
        return self._type_record_for_type_node(type_node, record.owner)

    def _canonical_type_text(self, text: str) -> str:
        # Whitespace is canonicalized (`uint256 [ ]`, `address
        # payable`) and the bare `uint`/`int`/`byte`/`fixed`/`ufixed`
        # spellings map to their canonical widths at every position —
        # `uint` is exactly `uint256` to solc even inside a composite
        # (`uint[]` is `uint256[]`). Dynamic `bytes` is a distinct
        # type and stays as written.
        canonical = re.sub(r"\s+", " ", text).strip()
        # Only identifier characters keep surrounding whitespace —
        # `uint => uint`, `uint=>uint` and `uint256[2 + 3]` are each
        # one spelling, while `address payable` stays two words.
        canonical = re.sub(r"\s*([^A-Za-z0-9_$ ])\s*", r"\1", canonical)
        canonical = re.sub(r"\buint\b", "uint256", canonical)
        canonical = re.sub(r"\bint\b", "int256", canonical)
        canonical = re.sub(r"\bbyte\b", "bytes1", canonical)
        canonical = re.sub(r"\bufixed\b", "ufixed128x18", canonical)
        canonical = re.sub(r"\bfixed\b", "fixed128x18", canonical)
        return canonical

    def _lookup(
        self, name: str, position: int, namespace: str = "value"
    ) -> tuple[_Record | None, str | None]:
        for scope in reversed(self.scopes[1:]):
            found = self._matching_records(
                scope.records.get(name, []), position, namespace
            )
            if found:
                if (
                    namespace == "value"
                    and self.current_contract is not None
                    and scope is self.current_contract.scope
                    and all(
                        record.binding.kind == "function" for record in found
                    )
                ):
                    continue
                return self._choose(found)
        if self.current_contract is not None:
            record, reason, _candidates = self._lookup_contract(
                name, self.current_contract, position, namespace
            )
            if record is not None or reason is not None:
                return record, reason
        file_records = self._matching_records(
            self.file_scope.records.get(name, []), position, namespace
        )
        if file_records:
            return self._choose(file_records)
        return None, None

    def _reason_for_missing(
        self, name: str, position: int, node: Any
    ) -> str:
        if name in _BUILTINS:
            return "builtin"
        if self.glob_imports:
            return "glob_import"
        if self.current_contract is not None and self.current_contract.external_base:
            contract = self.current_contract
            if not contract.base_gap_added:
                self._add_gap("unresolved_base", contract.node)
                contract.base_gap_added = True
            return "unresolved_base"
        return "unknown_name"

    def _resolve_name(
        self,
        node: Any,
        *,
        namespace: str = "value",
        reference_kind: str | None = None,
    ) -> _Record | None:
        name = self.text(node)
        if name == "_" or name in _UNITS:
            return None
        record, reason = self._lookup(name, node.start_byte, namespace)
        if record is not None:
            if reference_kind is not None:
                self._add_ref(node, record, reference_kind)
            return record
        reason = reason or self._reason_for_missing(name, node.start_byte, node)
        self._add_unresolved(node, name, reason)
        return None

    def _record_type_refs(self, node: Any | None, owner: _Contract | None) -> None:
        if node is None:
            return
        for child in self._walk(node):
            if child.type != "user_defined_type":
                continue
            member = next(
                (item for item in child.named_children if item.type == "member_expression"),
                None,
            )
            if member is not None:
                base = member.child_by_field_name("object")
                if base is not None:
                    self._expr(base)
                continue
            identifier = next(
                (item for item in child.named_children if item.type == "identifier"),
                None,
            )
            if identifier is not None:
                self._resolve_name(identifier, namespace="type", reference_kind="read")

    def _type_nodes_in_parameters(self, node: Any) -> list[Any]:
        return [child for child in self.children(node) if child.type == "parameter"]

    def _parameter_signature(self, node: Any) -> tuple[str, ...] | None:
        signature = []
        for parameter in self._type_nodes_in_parameters(node):
            type_node = parameter.child_by_field_name("type")
            if (
                type_node is None
                or type_node.has_error
                or type_node.is_missing
            ):
                return None
            type_text = " ".join(self.text(type_node).split())
            if not _PARAMETER_TYPE_TEXT.fullmatch(type_text):
                return None
            signature.append(type_text)
        return tuple(signature)

    def _return_parameters(self, node: Any) -> list[Any]:
        result = node.child_by_field_name("return_type")
        if result is None:
            return []
        return [child for child in self._walk(result) if child.type == "parameter"]

    def _bind_parameters(
        self,
        params: list[Any],
        scope: _Scope,
        owner: _Contract | None,
        *,
        kind: str = "parameter",
        binding_scope: ByteSpan,
    ) -> tuple[list[str], list[TypeFact]]:
        identifiers: list[str] = []
        facts: list[TypeFact] = []
        for param in params:
            type_node = param.child_by_field_name("type")
            self._record_type_refs(type_node, owner)
            facts.append(self._type_fact(type_node, owner, set()))
            name = param.child_by_field_name("name")
            if name is None:
                continue
            location_node = param.child_by_field_name("location")
            location = self.text(location_node)
            record = self._add(
                scope,
                name,
                kind,
                binding_scope=binding_scope,
                type_node=type_node,
                owner=owner,
                mutable=True,
                location=location,
            )
            identifiers.append(record.binding.id)
        return identifiers, facts

    def _function_result(self, facts: list[TypeFact]) -> TypeFact:
        if len(facts) == 1:
            return facts[0]
        return _UNKNOWN

    def _scan_function(
        self,
        node: Any,
        record: _Record,
        *,
        kind: str = "function",
    ) -> None:
        owner = record.owner
        old_contract = self.current_contract
        old_owner = self.call_owner
        self.current_contract = owner
        self.call_owner = record.binding.id
        function_scope = self._new_scope("function", node, owner)
        self.scopes.append(function_scope)
        params = self._type_nodes_in_parameters(node)
        param_ids, _param_facts = self._bind_parameters(
            params,
            function_scope,
            owner,
            binding_scope=self.span(node),
        )
        return_params = self._return_parameters(node)
        return_ids, return_facts = self._bind_parameters(
            return_params,
            function_scope,
            owner,
            kind="return_parameter",
            binding_scope=self.span(node),
        )
        for child in self.children(node):
            if child.type == "modifier_invocation":
                self._modifier_invocation(child)
        body = node.child_by_field_name("body")
        if body is not None:
            self._visit(body)
        self.functions.append(
            Function(
                record.binding.id,
                None if body is None else self.span(body),
                tuple(param_ids + return_ids),
                self._function_result(return_facts),
                False,
                False,
                owner is not None and kind == "function",
                False,
            )
        )
        self.scopes.pop()
        self.current_contract = old_contract
        self.call_owner = old_owner

    def _scan_constructor(self, node: Any, record: _Record) -> None:
        self._scan_function(node, record, kind="constructor")

    def _scan_modifier(self, node: Any, record: _Record) -> None:
        self._scan_function(node, record, kind="modifier")

    def _scan_fallback(self, node: Any) -> None:
        old_owner = self.call_owner
        self.call_owner = ""
        scope = self._new_scope("function", node, self.current_contract)
        self.scopes.append(scope)
        params = self._type_nodes_in_parameters(node)
        self._bind_parameters(
            params,
            scope,
            self.current_contract,
            binding_scope=self.span(node),
        )
        body = node.child_by_field_name("body")
        if body is not None:
            self._visit(body)
        self.scopes.pop()
        self.call_owner = old_owner

    def _scan_contract(self, contract: _Contract) -> None:
        old_contract = self.current_contract
        self.current_contract = contract
        self.scopes.append(contract.scope)
        for name, base_node in contract.bases:
            ancestor = base_node.child_by_field_name("ancestor")
            if ancestor is not None:
                base_record = self._resolve_type_node(ancestor, contract)
                has_arguments = any(
                    base_node.field_name_for_child(index) == "ancestor_arguments"
                    and self.text(child) == "("
                    for index, child in enumerate(base_node.children)
                )
                args = [
                    child
                    for child in self.children(base_node)
                    if child.type == "call_argument"
                ]
                if has_arguments:
                    spans = tuple(
                        self.span(self._argument_expression(arg)) for arg in args
                    )
                    for arg in args:
                        self._visit(self._argument_expression(arg))
                    target_id = ""
                    call_kind = "unresolved"
                    if (
                        base_record is not None
                        and base_record.binding.kind == "contract"
                    ):
                        target_id = base_record.binding.id
                        call_kind = "base_constructor"
                    self.calls.append(
                        Call(
                            self.span(base_node),
                            spans,
                            "",
                            target_id,
                            call_kind,
                        )
                    )
            if contract.external_base and self.contracts.get(name) is None:
                base_record = self._lookup_type_record(name, base_node.start_byte, None)
                if base_record is None:
                    identifier = next(
                        (child for child in self._walk(base_node) if child.type == "identifier"),
                        None,
                    )
                    if identifier is not None:
                        self._add_unresolved(identifier, name, "unresolved_base")
                    if not contract.base_gap_added:
                        self._add_gap("unresolved_base", contract.node)
                        contract.base_gap_added = True

        for node in self.children(contract.body):
            if node.type in {"function_definition", "modifier_definition"}:
                record = self._record_for_declaration(node)
                if record is not None:
                    if node.type == "modifier_definition":
                        self._scan_modifier(node, record)
                    else:
                        self._scan_function(node, record)
            elif node.type == "constructor_definition":
                record = self._record_for_declaration(node)
                if record is not None:
                    self._scan_constructor(node, record)
            elif node.type == "fallback_receive_definition":
                self._scan_fallback(node)
            elif node.type in {
                "state_variable_declaration",
                "constant_variable_declaration",
            }:
                self._scan_declaration_types(node, contract)
                self._scan_initializer(node)
            elif node.type in {
                "struct_declaration",
                "enum_declaration",
                "user_defined_type_definition",
                "event_definition",
                "error_declaration",
            }:
                self._scan_declaration_types(node, contract)
            elif node.type == "using_directive":
                self._scan_using_refs(node)
            elif node.type != "inheritance_specifier":
                self._add_gap("unsupported_syntax", node)
        self.scopes.pop()
        self.current_contract = old_contract

    def _scan_using_refs(self, node: Any) -> None:
        # The library name in `using Lib for T` is a real reference to
        # the library declaration, and a `for` target naming a
        # user-defined type (`for Coin`) references its declaration;
        # primitive targets carry no compiler reference.
        for child in self.children(node):
            if child.type in {"type_alias", "user_defined_type"}:
                identifier = next(
                    (
                        item
                        for item in child.named_children
                        if item.type == "identifier"
                    ),
                    None,
                )
                if identifier is not None:
                    self._resolve_name(
                        identifier, namespace="type", reference_kind="read"
                    )
            elif child.type == "type_name":
                # The `for` target binds to its declaration only when
                # it names a user-defined type (`for Coin`); primitive
                # targets carry no compiler reference.
                for descendant in self._walk(child):
                    if descendant.type != "user_defined_type":
                        continue
                    identifier = next(
                        (
                            item
                            for item in descendant.named_children
                            if item.type == "identifier"
                        ),
                        None,
                    )
                    if identifier is not None:
                        self._resolve_name(
                            identifier,
                            namespace="type",
                            reference_kind="read",
                        )

    def _record_for_declaration(self, node: Any) -> _Record | None:
        for record in self.records:
            if record.node == node or record.node.parent == node:
                return record
        name = node.child_by_field_name("name")
        if name is not None:
            return next(
                (
                    record
                    for record in self.records
                    if record.binding.span == self.span(name)
                ),
                None,
            )
        if node.type == "constructor_definition":
            return next(
                (
                    record
                    for record in self.records
                    if record.binding.kind == "constructor"
                    and record.owner is self.current_contract
                    and record.binding.span == self.span(node)
                ),
                None,
            )
        return None

    def _scan_declaration_types(self, node: Any, owner: _Contract | None) -> None:
        for child in self.children(node):
            if child.type in {
                "type_name",
                "user_defined_type",
                "parameter",
                "event_parameter",
                "error_parameter",
            }:
                self._record_type_refs(child, owner)
            elif child.type in {"struct_body", "enum_body"}:
                for descendant in self._walk(child):
                    if descendant.type in {"type_name", "user_defined_type"}:
                        self._record_type_refs(descendant, owner)

    def _scan_initializer(self, node: Any) -> None:
        for child in self.children(node):
            if child.type in {"type_name", "visibility", "identifier"}:
                continue
            self._visit(child)

    def _resolve_type_node(
        self,
        node: Any,
        owner: _Contract | None,
        *,
        reference_kind: str | None = "read",
    ) -> _Record | None:
        member = next(
            (item for item in self._walk(node) if item.type == "member_expression"),
            None,
        )
        if member is not None:
            base = member.child_by_field_name("object")
            if base is not None:
                return self._resolve_name(
                    base, namespace="type", reference_kind=reference_kind
                )
        identifier = next(
            (item for item in self._walk(node) if item.type == "identifier"),
            None,
        )
        if identifier is None:
            return None
        return self._resolve_name(
            identifier, namespace="type", reference_kind=reference_kind
        )

    def _scan_file_items(self) -> None:
        for node in self.children(self.root):
            if node.type in {
                "contract_declaration",
                "interface_declaration",
                "library_declaration",
            }:
                name = node.child_by_field_name("name")
                contract = None if name is None else self.contracts.get(self.text(name))
                if contract is not None:
                    self._scan_contract(contract)
            elif node.type == "function_definition":
                record = self._record_for_declaration(node)
                if record is not None:
                    self._scan_function(node, record)
            elif node.type in {
                "state_variable_declaration",
                "constant_variable_declaration",
            }:
                self._scan_declaration_types(node, None)
                self._scan_initializer(node)
            elif node.type in {
                "struct_declaration",
                "enum_declaration",
                "user_defined_type_definition",
                "error_declaration",
                "event_definition",
            }:
                self._scan_declaration_types(node, None)
            elif node.type == "using_directive":
                self._scan_using_refs(node)
            elif node.type not in {"pragma_directive", "import_directive"}:
                self._add_gap("unsupported_syntax", node)

    def _argument_expression(self, node: Any) -> Any:
        return next(
            (child for child in self.children(node) if child.type == "expression"),
            node,
        )

    def _expr_children(self, node: Any) -> list[Any]:
        return self.children(node)

    def _unwrap(self, node: Any | None) -> Any | None:
        while node is not None and node.type == "expression":
            children = self._expr_children(node)
            if len(children) != 1:
                return node
            node = children[0]
        return node

    def _visit(self, node: Any | None) -> None:
        if node is None:
            return
        kind = node.type
        if kind in {"function_body", "block_statement"}:
            scope = self._new_scope("block", node, self.current_contract)
            self.scopes.append(scope)
            for child in self.children(node):
                self._visit(child)
            self.scopes.pop()
            return
        if kind == "variable_declaration_statement":
            self._variable_declaration_statement(node)
            return
        if kind == "for_statement":
            self._for_statement(node)
            return
        if kind == "try_statement":
            self._try_statement(node)
            return
        if kind == "catch_clause":
            self._catch_clause(node)
            return
        if kind == "assembly_statement":
            self._add_gap("inline_assembly", node)
            return
        if kind == "call_expression":
            self._call_expression(node)
            return
        if kind == "type_cast_expression":
            self._type_cast(node)
            return
        if kind == "unary_expression":
            operator = node.child_by_field_name("operator")
            argument = node.child_by_field_name("argument")
            if self.text(operator) == "delete":
                self._place(argument, "write", assignment_node=node)
            else:
                self._expr(argument)
            return
        if kind == "member_expression":
            obj = node.child_by_field_name("object")
            self._expr(obj)
            member, record, reason = self._resolve_member(node)
            if member is not None and record is not None:
                self._add_ref(member, record, "read")
            elif member is not None and reason is not None:
                self._add_unresolved(member, self.text(member), reason)
            return
        if kind == "array_access":
            self._expr(node.child_by_field_name("base"))
            self._expr(node.child_by_field_name("index"))
            return
        if kind in {"assignment_expression", "augmented_assignment_expression"}:
            self._assignment(node)
            return
        if kind == "update_expression":
            self._place(
                node.child_by_field_name("argument"),
                "read_write",
                assignment_node=node,
            )
            return
        if kind == "emit_statement":
            self._emit_statement(node)
            return
        if kind == "revert_statement":
            self._revert_statement(node)
            return
        if kind == "modifier_invocation":
            self._modifier_invocation(node)
            return
        if kind == "struct_field_assignment":
            value = node.child_by_field_name("value")
            if value is None:
                self._add_gap("unsupported_syntax", node)
            else:
                self._expr(value)
            return
        if kind == "identifier":
            self._expr_identifier(node)
            return
        if kind in {
            "type_name",
            "user_defined_type",
            "primitive_type",
            "number_literal",
            "string_literal",
            "hex_string_literal",
            "boolean_literal",
            "unicode_string_literal",
            "visibility",
            "storage_location",
            "state_mutability",
            "comment",
        }:
            return
        if kind == "expression" and self.text(node).lstrip().startswith("delete "):
            children = self.children(node)
            if children:
                self._place(children[-1], "write")
            return
        if kind == "expression":
            for child in self.children(node):
                self._expr(child)
            return
        if kind in {"contract_body", "source_file"}:
            for child in self.children(node):
                self._visit(child)
            return
        for child in self.children(node):
            self._visit(child)

    def _expr(self, node: Any | None) -> None:
        if node is None:
            return
        node = self._unwrap(node)
        if node is None:
            return
        if node.type == "expression":
            if self.text(node).lstrip().startswith("delete "):
                children = self.children(node)
                if children:
                    self._place(children[-1], "write")
                return
            for child in self.children(node):
                self._expr(child)
            return
        self._visit(node)

    def _expr_identifier(self, node: Any) -> _Record | None:
        name = self.text(node)
        if name == "_" or name in _UNITS:
            return None
        record, reason = self._lookup(name, node.start_byte, "value")
        if record is None:
            type_record, type_reason = self._lookup(name, node.start_byte, "type")
            if type_record is not None:
                record = type_record
            elif reason is None:
                reason = type_reason
        if record is not None:
            self._add_ref(node, record, "read")
            return record
        self._add_unresolved(
            node,
            name,
            reason or self._reason_for_missing(name, node.start_byte, node),
        )
        return None

    def _visit_generic(self, node: Any) -> None:
        for child in self.children(node):
            self._visit(child)

    def _variable_declaration_statement(
        self, node: Any, forced_scope: ByteSpan | None = None
    ) -> None:
        declarations = [
            child
            for child in self.children(node)
            if child.type in {"variable_declaration", "variable_declaration_tuple"}
        ]
        value = node.child_by_field_name("value")
        if value is not None:
            self._expr(value)
        else:
            for child in self.children(node):
                if child not in declarations:
                    self._visit(child)
        block = self.scopes[-1].node
        binding_scope = forced_scope or ByteSpan(node.end_byte, block.end_byte)
        for declaration in declarations:
            entries = (
                self.children(declaration)
                if declaration.type == "variable_declaration_tuple"
                else [declaration]
            )
            for entry in entries:
                if entry.type != "variable_declaration":
                    continue
                type_node = entry.child_by_field_name("type")
                self._record_type_refs(type_node, self.current_contract)
                name = entry.child_by_field_name("name")
                if name is None:
                    continue
                location = entry.child_by_field_name("location")
                self._add(
                    self.scopes[-1],
                    name,
                    "local",
                    binding_scope=binding_scope,
                    type_node=type_node,
                    owner=self.current_contract,
                    mutable=True,
                    location=self.text(location),
                )

    def _for_statement(self, node: Any) -> None:
        scope = self._new_scope("for", node, self.current_contract)
        self.scopes.append(scope)
        initial = node.child_by_field_name("initial")
        if initial is not None:
            if initial.type == "variable_declaration_statement":
                self._variable_declaration_statement(initial, self.span(node))
            else:
                self._visit(initial)
        for field in ("condition", "update", "body"):
            child = node.child_by_field_name(field)
            if child is not None:
                self._visit(child)
        self.scopes.pop()

    def _try_statement(self, node: Any) -> None:
        attempt = node.child_by_field_name("attempt")
        self._expr(attempt)
        children = self.children(node)
        body = node.child_by_field_name("body")
        params = [child for child in children if child.type == "parameter"]
        if body is not None:
            scope = self._new_scope("try", body, self.current_contract)
            self.scopes.append(scope)
            self._bind_parameters(
                params,
                scope,
                self.current_contract,
                binding_scope=self.span(body),
            )
            self._visit(body)
            self.scopes.pop()
        for child in children:
            if child.type == "catch_clause":
                self._catch_clause(child)

    def _catch_clause(self, node: Any) -> None:
        body = node.child_by_field_name("body")
        scope = self._new_scope("catch", body or node, self.current_contract)
        self.scopes.append(scope)
        params = [child for child in self.children(node) if child.type == "parameter"]
        self._bind_parameters(
            params,
            scope,
            self.current_contract,
            binding_scope=self.span(body or node),
        )
        if body is not None:
            self._visit(body)
        self.scopes.pop()

    def _place(
        self,
        node: Any | None,
        mode: str,
        *,
        assignment_node: Any | None = None,
    ) -> None:
        if node is None:
            return
        node = self._unwrap(node)
        if node is None:
            return
        if node.type == "tuple_expression":
            for child in self.children(node):
                self._place(child, mode, assignment_node=assignment_node)
            return
        if node.type == "expression":
            children = self.children(node)
            if len(children) == 1:
                self._place(children[0], mode, assignment_node=assignment_node)
            else:
                for child in children:
                    self._expr(child)
            return
        if node.type == "identifier":
            record = self._lookup(node.text.decode(), node.start_byte, "value")[0]
            if record is None:
                record = self._resolve_name(node, reference_kind="read" if mode == "read" else None)
            if record is not None:
                if mode in {"read", "read_write"}:
                    self._add_ref(node, record, "read")
                if mode in {"write", "read_write"}:
                    if record.location == "storage":
                        if mode == "write":
                            self._add_ref(node, record, "read")
                    elif record.binding.kind in {
                        "function", "struct", "enum", "const", "type_alias",
                        "trait", "union", "module", "import", "associated_function",
                        "associated_const", "contract", "interface", "library",
                        "modifier", "event", "error", "user_type",
                    } or (
                        record.binding.kind == "state_variable"
                        and not record.binding.mutable
                    ):
                        self._add_gap(
                            "unsupported_syntax", assignment_node or node
                        )
                        if mode == "write":
                            self._add_ref(node, record, "read")
                    else:
                        self._add_ref(node, record, "write")
            return
        if node.type == "member_expression":
            root = node
            while root.type == "member_expression":
                root = root.child_by_field_name("object")
                root = self._unwrap(root)
            if root is not None and root.type == "array_access":
                self._place(root, mode, assignment_node=assignment_node)
            elif root is not None and root.type == "identifier":
                record = self._lookup(root.text.decode(), root.start_byte, "value")[0]
                if record is not None and record.location == "storage":
                    self._add_ref(root, record, "read")
                else:
                    self._place(root, mode, assignment_node=assignment_node)
            else:
                self._expr(root)
            # Member names in the chain keep their own references:
            # inner members are reads, the outermost mirrors the
            # identifier write rules — read+write for compound updates,
            # gap+read for non-assignable members (enum constants,
            # functions) so readers accepting the report's invariants
            # never see a write they forbid.
            current = node
            while current.type == "member_expression":
                member, member_record, member_reason = self._resolve_member(
                    current
                )
                if member is not None and member_record is not None:
                    effective = mode if current is node else "read"
                    if effective in {"read", "read_write"}:
                        self._add_ref(member, member_record, "read")
                    if effective in {"write", "read_write"}:
                        if (
                            member_record.binding.kind
                            in NON_ASSIGNABLE_WRITE_KINDS
                            or (
                                member_record.binding.kind
                                == "state_variable"
                                and not member_record.binding.mutable
                            )
                        ):
                            self._add_gap(
                                "unsupported_syntax", assignment_node or node
                            )
                            if effective == "write":
                                self._add_ref(member, member_record, "read")
                        else:
                            self._add_ref(member, member_record, "write")
                elif member is not None and member_reason is not None:
                    self._add_unresolved(
                        member, self.text(member), member_reason
                    )
                obj = self._unwrap(current.child_by_field_name("object"))
                if obj is current:
                    break
                current = obj
            return
        if node.type == "array_access":
            base = self._unwrap(node.child_by_field_name("base"))
            index = node.child_by_field_name("index")
            self._expr(index)
            self._place(base, mode, assignment_node=assignment_node)
            return
        self._expr(node)

    def _assignment(self, node: Any) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        compound = node.type == "augmented_assignment_expression"
        self._place(
            left,
            "read_write" if compound else "write",
            assignment_node=node,
        )
        self._expr(right)

    def _call_arguments(self, node: Any) -> tuple[tuple[ByteSpan, ...], list[Any]]:
        args = [child for child in self.children(node) if child.type == "call_argument"]
        expressions = [self._argument_expression(arg) for arg in args]
        return tuple(self.span(item) for item in expressions), expressions

    def _function_expression_base(
        self, node: Any
    ) -> tuple[Any, bool, list[Any]]:
        current = self._unwrap(node)
        options: list[Any] = []
        has_options = False
        if current is not None and current.type == "struct_expression":
            options = [
                child
                for child in self.children(current)
                if child.type == "struct_field_assignment"
            ]
            if options:
                has_options = True
                current = self._unwrap(current.child_by_field_name("type"))
        if current is not None and current.type == "expression":
            children = self.children(current)
            option_nodes = [child for child in children if child.type == "struct_field_assignment"]
            if option_nodes:
                has_options = True
                options = option_nodes
                current = self._unwrap(
                    next(
                        (child for child in children if child not in option_nodes),
                        None,
                    )
                )
        return current, has_options, options

    def _is_virtual_dispatch(self, record: _Record) -> bool:
        if record.virtual:
            return True
        owner = record.owner
        if owner is None:
            return False
        for derived in self.contracts.values():
            if derived is owner or not self._is_derived_from(derived, owner, set()):
                continue
            if any(
                candidate.binding.name == record.binding.name
                and candidate.binding.kind == "function"
                for candidate in derived.scope.records.get(record.binding.name, [])
            ):
                return True
        return False

    def _is_derived_from(
        self, derived: _Contract, base: _Contract, visited: set[str]
    ) -> bool:
        if derived.record.binding.id in visited:
            return False
        visited.add(derived.record.binding.id)
        for name, _node in derived.bases:
            candidate = self.contracts.get(name)
            if candidate is base or (
                candidate is not None
                and self._is_derived_from(candidate, base, visited)
            ):
                return True
        return False

    def _contract_layers(
        self,
        name: str,
        contract: _Contract,
        namespace: str,
        visited: set[str] | None = None,
    ) -> list[tuple[_Contract, list[_Record]]]:
        visited = set() if visited is None else visited
        if contract.record.binding.id in visited:
            return []
        visited.add(contract.record.binding.id)
        records = self._matching_records(
            contract.scope.records.get(name, []),
            contract.body.start_byte,
            namespace,
        )
        layers = [(contract, records)]
        for base_name, _base_node in reversed(contract.bases):
            base = self.contracts.get(base_name)
            if base is not None:
                layers.extend(
                    self._contract_layers(name, base, namespace, visited)
                )
        return layers

    def _linearized_bases(self, contract: _Contract) -> list[_Contract]:
        """C3 linearization of `contract`'s ancestors, most derived
        first. Solidity lists direct bases most base-like first, so the
        merge consumes them in reverse declaration order; unresolved or
        already-visited contracts contribute nothing.
        """
        memo: dict[str, list[_Contract]] = {}

        def linearize(owner: _Contract) -> list[_Contract]:
            cached = memo.get(owner.record.binding.id)
            if cached is not None:
                return cached
            sequences: list[list[_Contract]] = []
            declared: list[_Contract] = []
            for base_name, _base_node in reversed(owner.bases):
                base = self.contracts.get(base_name)
                if base is None:
                    continue
                sequences.append([base] + linearize(base))
                declared.append(base)
            sequences.append(declared)
            merged: list[_Contract] = []
            seen = {owner.record.binding.id}
            pools = [list(sequence) for sequence in sequences]
            while any(pools):
                progressed = False
                for pool in pools:
                    if not pool:
                        continue
                    head = pool[0]
                    if any(
                        head is candidate
                        for other in pools
                        for candidate in other[1:]
                    ):
                        continue
                    if head.record.binding.id not in seen:
                        seen.add(head.record.binding.id)
                        merged.append(head)
                    for other in pools:
                        if other and other[0] is head:
                            other.pop(0)
                    progressed = True
                    break
                if not progressed:
                    break
            memo[owner.record.binding.id] = merged
            return merged

        return linearize(contract)

    def _drop_overridden_functions(
        self, candidates: list[_Record]
    ) -> list[_Record]:
        kept = []
        for candidate in candidates:
            signature = candidate.parameter_signature
            if signature is not None and any(
                other is not candidate
                and other.owner is not None
                and candidate.owner is not None
                and other.parameter_signature == signature
                and self._is_derived_from(other.owner, candidate.owner, set())
                and (
                    other.override
                    or (candidate.body is None and other.body is not None)
                )
                for other in candidates
            ):
                continue
            kept.append(candidate)
        return kept

    def _call_expression(self, node: Any) -> None:
        function = node.child_by_field_name("function")
        args, expressions = self._call_arguments(node)
        callee, has_options, option_nodes = self._function_expression_base(function)
        for option in option_nodes:
            value = option.child_by_field_name("value")
            self._expr(value)
        for argument in expressions:
            self._expr(argument)
        if callee is None:
            self.calls.append(Call(self.span(node), args, self.call_owner, "", "opaque_expression"))
            self._add_gap("unsupported_syntax", node)
            return
        if callee.type == "new_expression":
            type_node = callee.child_by_field_name("name")
            target = self._resolve_type_node(
                type_node, self.current_contract, reference_kind=None
            )
            if target is None:
                self.calls.append(Call(self.span(node), args, self.call_owner, "", "unresolved"))
            elif target.binding.kind in {"contract", "import"}:
                identifier = next(
                    (child for child in self._walk(type_node) if child.type == "identifier"),
                    None,
                )
                if identifier is not None:
                    self._add_ref(identifier, target, "call")
                self.calls.append(
                    Call(
                        self.span(node),
                        args,
                        self.call_owner,
                        target.binding.id,
                        "opaque_new"
                        if target.binding.kind == "contract"
                        else "opaque_import",
                    )
                )
            else:
                self._add_gap("unsupported_syntax", node)
                self.calls.append(
                    Call(self.span(node), args, self.call_owner, "", "opaque_expression")
                )
            return
        if callee.type == "member_expression":
            base = callee.child_by_field_name("object")
            self._expr(base)
            member, record, reason = self._resolve_member(callee)
            if member is None or (record is None and reason is None):
                self.calls.append(
                    Call(
                        self.span(node),
                        args,
                        self.call_owner,
                        "",
                        "opaque_member",
                    )
                )
                return
            if record is None:
                self._add_unresolved(member, self.text(member), reason)
                self.calls.append(
                    Call(
                        self.span(node),
                        args,
                        self.call_owner,
                        "",
                        (
                            "opaque_overload"
                            if reason == "ambiguous_overload"
                            else "unresolved"
                        ),
                    )
                )
                return
            self._add_ref(member, record, "call")
            binding_kind = record.binding.kind
            if binding_kind == "function":
                if has_options:
                    call_kind = "opaque_call_options"
                elif record.body is None:
                    call_kind = "opaque_bodyless"
                elif self._is_virtual_dispatch(record):
                    call_kind = "opaque_virtual"
                else:
                    call_kind = "direct_local"
            elif binding_kind in _FUNCTION_BINDINGS:
                call_kind = "opaque_call_options" if has_options else "opaque_value"
            else:
                call_kind = "opaque_call_options" if has_options else "opaque_value"
            self.calls.append(
                Call(
                    self.span(node),
                    args,
                    self.call_owner,
                    record.binding.id,
                    call_kind,
                )
            )
            return
        if callee.type != "identifier":
            self._expr(callee)
            self.calls.append(Call(self.span(node), args, self.call_owner, "", "opaque_expression"))
            return
        name = self.text(callee)
        record, reason = self._lookup(name, callee.start_byte, "value")
        if record is None and reason == "ambiguous_overload":
            self._add_unresolved(callee, name, reason)
            self.calls.append(Call(self.span(node), args, self.call_owner, "", "opaque_overload"))
            return
        if record is None:
            type_record, type_reason = self._lookup(name, callee.start_byte, "type")
            if type_record is not None:
                record = type_record
                reason = None
            else:
                reason = reason or type_reason
        if record is None:
            reason = reason or self._reason_for_missing(name, callee.start_byte, callee)
            self._add_unresolved(callee, name, reason)
            kind = "builtin" if reason == "builtin" else "unresolved"
            self.calls.append(Call(self.span(node), args, self.call_owner, "", kind))
            return
        if record.binding.kind in {"contract", "interface", "library", "user_type"}:
            self._add_ref(callee, record, "read")
            self.calls.append(Call(self.span(node), args, self.call_owner, "", "conversion"))
            return
        self._add_ref(callee, record, "call")
        binding_kind = record.binding.kind
        if binding_kind == "struct":
            kind = "constructor"
        elif binding_kind == "import":
            kind = "opaque_import"
        elif binding_kind == "function":
            if has_options:
                kind = "opaque_call_options"
            elif record.body is None:
                kind = "opaque_bodyless"
            elif self._is_virtual_dispatch(record):
                kind = "opaque_virtual"
            else:
                kind = "direct_local"
        elif binding_kind in {"local", "parameter", "return_parameter", "state_variable"}:
            kind = "opaque_call_options" if has_options else "opaque_value"
        else:
            kind = "opaque_call_options" if has_options else "opaque_value"
        self.calls.append(Call(self.span(node), args, self.call_owner, record.binding.id, kind))

    def _type_cast(self, node: Any) -> None:
        args = []
        for child in self.children(node):
            if child.type == "expression":
                args.append(child)
            elif child.type == "call_argument":
                args.append(self._argument_expression(child))
        spans = tuple(self.span(self._unwrap(arg) or arg) for arg in args)
        for arg in args:
            self._expr(arg)
        self.calls.append(
            Call(self.span(node), spans, self.call_owner, "", "conversion")
        )

    def _emit_statement(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        args = [child for child in self.children(node) if child.type == "call_argument"]
        expressions = [self._argument_expression(arg) for arg in args]
        for expression in expressions:
            self._expr(expression)
        target = None if name_node is None else self._resolve_name(
            self._unwrap(name_node) or name_node,
            reference_kind="call",
        )
        if target is None or target.binding.kind != "event":
            self.calls.append(Call(self.span(node), tuple(self.span(a) for a in expressions), self.call_owner, "", "unresolved"))
        else:
            self.calls.append(Call(self.span(node), tuple(self.span(a) for a in expressions), self.call_owner, target.binding.id, "emit"))

    def _revert_statement(self, node: Any) -> None:
        error = node.child_by_field_name("error")
        args_nodes = [
            child for child in self._walk(node) if child.type == "call_argument"
        ]
        expressions = [self._argument_expression(arg) for arg in args_nodes]
        for expression in expressions:
            self._expr(expression)
        if error is None:
            self.calls.append(Call(self.span(node), tuple(self.span(a) for a in expressions), self.call_owner, "", "builtin"))
            return
        callee = self._unwrap(error) or error
        if callee.type != "identifier":
            self._expr(error)
            self.calls.append(Call(self.span(node), tuple(self.span(a) for a in expressions), self.call_owner, "", "unresolved"))
            return
        record, reason = self._lookup(self.text(callee), callee.start_byte, "value")
        if record is not None and record.binding.kind == "error":
            self._add_ref(callee, record, "call")
            self.calls.append(Call(self.span(node), tuple(self.span(a) for a in expressions), self.call_owner, record.binding.id, "error_constructor"))
        else:
            name = self.text(callee)
            self._add_unresolved(callee, name, reason or self._reason_for_missing(name, callee.start_byte, callee))
            self.calls.append(Call(self.span(node), tuple(self.span(a) for a in expressions), self.call_owner, "", "unresolved"))

    def _modifier_invocation(self, node: Any) -> None:
        identifiers = [child for child in self.children(node) if child.type == "identifier"]
        callee = identifiers[0] if identifiers else None
        args = [child for child in self.children(node) if child.type == "call_argument"]
        expressions = [self._argument_expression(arg) for arg in args]
        for expression in expressions:
            self._expr(expression)
        if callee is None:
            self.calls.append(
                Call(
                    self.span(node),
                    tuple(self.span(a) for a in expressions),
                    self.call_owner,
                    "",
                    "unresolved",
                )
            )
            return
        name = self.text(callee)
        target, reason = self._lookup(name, callee.start_byte, "value")
        argument_spans = tuple(self.span(argument) for argument in expressions)
        if target is not None and target.binding.kind == "modifier":
            self._add_ref(callee, target, "call")
            self.calls.append(
                Call(
                    self.span(node),
                    argument_spans,
                    self.call_owner,
                    target.binding.id,
                    "modifier",
                )
            )
            return
        if node.parent is not None and node.parent.type == "constructor_definition":
            type_record = self._lookup_type_record(
                name, callee.start_byte, self.current_contract
            )
            base_contract = (
                None
                if type_record is None
                else self.contracts.get(type_record.binding.name)
            )
            if (
                type_record is not None
                and type_record.binding.kind == "contract"
                and base_contract is not None
                and self.current_contract is not None
                and self._is_derived_from(
                    self.current_contract, base_contract, set()
                )
            ):
                self._add_ref(callee, type_record, "call")
                self.calls.append(
                    Call(
                        self.span(node),
                        argument_spans,
                        self.call_owner,
                        type_record.binding.id,
                        "base_constructor",
                    )
                )
                return
        self._add_unresolved(
            callee,
            name,
            reason or self._reason_for_missing(name, callee.start_byte, callee),
        )
        self.calls.append(
            Call(
                self.span(node),
                argument_spans,
                self.call_owner,
                "",
                "unresolved",
            )
        )

    def build(self) -> LexicalBindingReport:
        self._predeclare()
        self._finalize_types()
        self._scan_file_items()
        self._finalize_types()
        return LexicalBindingReport(
            PROFILE,
            self.digest,
            {},
            tuple(self.bindings),
            tuple(self.references),
            tuple(self.unresolved),
            tuple(self.functions),
            tuple(self.calls),
            tuple(self.gaps),
        )


def _walk(root: Any):
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            continue
        yield node
        stack.extend(child for child in node.children if child.type != "comment")


def build_sol_bindings(source: str) -> LexicalBindingReport:
    try:
        raw = source.encode("utf-8")
    except (AttributeError, UnicodeError):
        raise LexicalReportError("Solidity source encoding is invalid") from None
    if len(raw) > MAX_SOURCE_BYTES:
        raise LexicalReportError("Solidity source exceeds the lexical report limit")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="int argument support is deprecated",
                category=DeprecationWarning,
            )
            tree_sitter = importlib.import_module("tree_sitter")
            tree_sitter_solidity = importlib.import_module("tree_sitter_solidity")
            language = tree_sitter.Language(tree_sitter_solidity.language())
        parser = tree_sitter.Parser(language)
        root = parser.parse(raw).root_node
    except RecursionError:
        raise LexicalReportError(
            "Solidity source nesting exceeds the lexical report limit"
        ) from None
    except Exception as exc:
        raise LexicalReportError("Solidity source could not be parsed") from exc
    if root.has_error or any(node.is_missing for node in _walk(root)):
        raise LexicalReportError("Solidity source has parse errors or missing nodes")
    try:
        return _SolBindings(source, raw, root).build()
    except RecursionError:
        raise LexicalReportError(
            "Solidity source nesting exceeds the lexical report limit"
        ) from None


def build_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(
        prog="python -m agent sol-bindings",
        description=(
            "Emit a conservative Solidity lexical binding report as JSON; "
            "this is lexical metadata, not a type check, proof, or verdict."
        ),
    )
    parser.add_argument("file", type=Path, help="Solidity source file")
    return parser


def main(args: argparse.Namespace) -> int:
    try:
        source = args.file.read_bytes().decode("utf-8", errors="strict")
        report = build_sol_bindings(source)
        sys.stdout.write(report.to_json())
        return 0
    except OSError:
        print("sol-bindings: could not read source file", file=sys.stderr)
        return 2
    except UnicodeError:
        print("sol-bindings: source file is not valid UTF-8", file=sys.stderr)
        return 2
    except LexicalReportError as exc:
        print(f"sol-bindings: {exc}", file=sys.stderr)
        return 2
