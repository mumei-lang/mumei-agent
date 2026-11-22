"""Conservative single-file Solidity lexical binding reports."""

from __future__ import annotations

import argparse
import importlib
import re
import sys
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from agent.lexical_bindings import (
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
class _Contract:
    record: _Record
    node: Any
    body: Any
    kind: str
    scope: _Scope
    bases: list[tuple[str, Any]]
    external_base: bool = False
    base_gap_added: bool = False


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
        self.current_contract: _Contract | None = None
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
        return self._add(
            scope,
            name,
            kind,
            binding_scope=self.span(owner.body) if owner else ByteSpan(0, 0),
            type_node=type_node,
            owner=owner,
            underlying=underlying,
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
            inherited, _reason = self._lookup_contract(
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
    ) -> tuple[_Record | None, str | None]:
        if namespace == "value":
            layers = self._contract_layers(
                name, contract, namespace, visited
            )
            functions: list[_Record] = []
            private_match = False
            for index, (_layer, records) in enumerate(layers):
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
                    return self._choose(records)
                functions.extend(records)
            if functions:
                return self._choose(self._drop_overridden_functions(functions))
            if private_match:
                return None, "private_base_member"
            return None, None
        visited = set() if visited is None else visited
        if contract.record.binding.id in visited:
            return None, None
        visited.add(contract.record.binding.id)
        own = self._matching_records(
            contract.scope.records.get(name, []),
            contract.body.start_byte,
            namespace,
        )
        if own:
            return self._choose(own)
        for base_name, _base_node in reversed(contract.bases):
            base = self.contracts.get(base_name)
            if base is None:
                continue
            record, reason = self._lookup_contract(
                name, base, position, namespace, visited
            )
            if reason is not None:
                return None, reason
            if record is not None:
                if record.visibility == "private":
                    return None, "private_base_member"
                return record, None
        return None, None

    def _resolve_member(
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
                # `super` follows the C3 linearization: the later a base
                # is declared, the more derived it is, so walk the bases
                # in reverse declaration order (as `_lookup_contract`
                # does for inherited members).
                for base_name, _base_node in reversed(owner.bases):
                    base = self.contracts.get(base_name)
                    if base is None:
                        continue
                    record, reason = self._lookup_contract(
                        name,
                        base,
                        member.start_byte,
                        "value",
                        allow_private_own=False,
                    )
                    if record is not None or reason is not None:
                        return member, record, reason
            return member, None, None
        contract = None
        inside_owner = False
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
                        contract = next(
                            (
                                candidate
                                for candidate in self.contracts.values()
                                if candidate.record.binding.id == fact.type_id
                            ),
                            None,
                        )
        if contract is None:
            return member, None, None
        inside_owner = inside_owner or (
            self.current_contract is not None
            and contract is self.current_contract
        )
        record, reason = self._lookup_contract(
            name,
            contract,
            member.start_byte,
            "value",
            allow_private_own=inside_owner,
        )
        return member, record, reason

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
            record, reason = self._lookup_contract(
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
            elif node.type != "inheritance_specifier":
                self._add_gap("unsupported_syntax", node)
        self.scopes.pop()
        self.current_contract = old_contract

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
                return
            if root is not None and root.type == "identifier":
                record = self._lookup(root.text.decode(), root.start_byte, "value")[0]
                if record is not None and record.location == "storage":
                    self._add_ref(root, record, "read")
                else:
                    self._place(root, mode, assignment_node=assignment_node)
            else:
                self._expr(root)
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
                    Call(self.span(node), args, self.call_owner, "", "unresolved")
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
