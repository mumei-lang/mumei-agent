"""Conservative single-file TypeScript lexical binding reports."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import re
import sys
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


PROFILE = "mumei.ts-lexical-bindings/v1"
MAX_SOURCE_BYTES = 64 * 1024
_UNKNOWN = TypeFact("unknown", "", 0, None, "")
_TYPE_BUILTINS = frozenset(
    {
        "Array", "BigInt", "Boolean", "Date", "Error", "Function",
        "IArguments", "Map", "Number", "Object", "Promise", "PropertyKey",
        "Readonly", "Record", "RegExp", "Set", "String", "Symbol",
        "TemplateStringsArray", "WeakMap", "WeakSet", "Partial", "Required",
        "Pick", "Omit", "Exclude", "Extract", "NonNullable", "Parameters",
        "ReturnType", "InstanceType", "ThisType", "Uppercase", "Lowercase",
        "Capitalize", "Uncapitalize",
    }
)
_BUILTIN_VALUES = frozenset(
    {
        "Math", "JSON", "console", "Object", "Array", "Number", "String",
        "Boolean", "Symbol", "BigInt", "Promise", "Map", "Set", "Error",
        "undefined", "NaN", "Infinity", "parseInt", "parseFloat", "isNaN",
        "globalThis", "require", "module", "exports", "process", "window",
        "document", "setTimeout", "clearTimeout", "setInterval",
        "clearInterval", "RegExp", "Date", "Reflect", "Proxy", "WeakMap",
        "WeakSet", "JSON", "Intl", "eval", "Function",
    }
)
_FUNCTION_NODES = frozenset(
    {
        "function_declaration", "function_expression",
        "generator_function_declaration", "generator_function",
        "arrow_function", "method_definition", "function_signature",
    }
)
_BLOCK_NODES = frozenset({"statement_block", "switch_body", "internal_module"})
_PRIMITIVE_FACTS = {
    "number": TypeFact("float", "number", 64, None, ""),
    "bigint": TypeFact("bigint", "bigint", 0, True, ""),
    "boolean": TypeFact("bool", "boolean", 1, None, ""),
}


@dataclass(eq=False)
class _Record:
    binding: Binding
    node: Any
    namespaces: frozenset[str]
    type_node: Any | None = None
    alias_node: Any | None = None
    body: Any | None = None
    function_node: Any | None = None
    function_declaration: bool = False
    generator: bool = False
    class_like: bool = False
    type_only: bool = False
    tdz: bool = False
    declaration_function: int | None = None
    self_scope: ByteSpan | None = None
    direct_function: bool = False
    member_of: int | None = None
    member_static: bool = False
    member_visibility: str = "public"
    member_container: str | None = None


@dataclass
class _FunctionInfo:
    record: _Record
    node: Any
    body: Any | None
    parameter_records: list[_Record]
    generic: bool
    is_async: bool
    method: bool
    variadic: bool
    generator: bool


class _TypeScriptBindings:
    def __init__(self, source: str, raw: bytes, root: Any, *, tsx: bool):
        self.source = source
        self.raw = raw
        self.root = root
        self.tsx = tsx
        self.source_hash = hashlib.sha256(raw).hexdigest()
        self.bindings: list[Binding] = []
        self.records: list[_Record] = []
        self.references: list[Reference] = []
        self.unresolved: list[Unresolved] = []
        self.functions: list[Function] = []
        self.calls: list[Call] = []
        self.gaps: list[Gap] = []
        self.function_infos: dict[int, _FunctionInfo] = {}
        self.function_records: dict[int, _Record] = {}
        self._function_node_ids: set[int] = set()
        self._type_alias_cache: dict[str, TypeFact] = {}
        self._loop_binding_ids: dict[int, frozenset[str]] = {}
        self._tdz_binding_ids: frozenset[str] = frozenset()
        self._type_bases: dict[int, list[str]] = {}
        self._initializer_active: set[str] = set()

    def span(self, node: Any) -> ByteSpan:
        return ByteSpan(node.start_byte, node.end_byte)

    def text(self, node: Any | None) -> str:
        return "" if node is None else self.raw[node.start_byte : node.end_byte].decode("utf-8")

    @staticmethod
    def children(node: Any | None) -> list[Any]:
        if node is None:
            return []
        return [child for child in node.named_children if child.type != "comment"]

    def walk(self, node: Any | None):
        if node is None:
            return
        stack = [node]
        while stack:
            current = stack.pop()
            if current.type == "comment":
                continue
            yield current
            stack.extend(
                child
                for child in reversed(current.children)
                if child.type != "comment"
            )

    def add_gap(self, reason: str, node: Any | ByteSpan) -> None:
        span = node if isinstance(node, ByteSpan) else self.span(node)
        gap = Gap(reason, span)
        if gap not in self.gaps:
            self.gaps.append(gap)

    def add_unresolved(self, node: Any, name: str, reason: str) -> None:
        span = self.span(node)
        if any(reference.span == span for reference in self.references):
            return
        value = Unresolved(span, name, reason)
        if value not in self.unresolved:
            self.unresolved.append(value)

    def add_reference(self, node: Any, record: _Record, kind: str) -> None:
        span = self.span(node)
        if any(item.span == span for item in self.unresolved):
            return
        reference = Reference(span, record.binding.id, kind)
        if reference not in self.references:
            self.references.append(reference)

    def add_binding(
        self,
        name_node: Any,
        kind: str,
        scope: ByteSpan | None,
        namespaces: frozenset[str],
        *,
        type_node: Any | None = None,
        alias_node: Any | None = None,
        body: Any | None = None,
        function_node: Any | None = None,
        function_declaration: bool = False,
        generator: bool = False,
        class_like: bool = False,
        type_only: bool = False,
        mutable: bool = False,
        tdz: bool = False,
        declaration_function: int | None = None,
        self_scope: ByteSpan | None = None,
        direct_function: bool = False,
        member_of: int | None = None,
        member_static: bool = False,
        member_visibility: str = "public",
    ) -> _Record:
        name = self.text(name_node)
        span = self.span(name_node)
        scope_start = 0 if scope is None else scope.start
        scope_end = 0 if scope is None else scope.end
        identifier = binding_id(
            self.source_hash, span.start, scope_start, scope_end
        )
        binding = Binding(
            identifier, name, kind, span, scope, _UNKNOWN, mutable
        )
        record = _Record(
            binding,
            name_node,
            namespaces,
            type_node,
            alias_node,
            body,
            function_node,
            function_declaration,
            generator,
            class_like,
            type_only,
            tdz,
            declaration_function,
            self_scope,
            direct_function,
            member_of,
            member_static,
            member_visibility,
        )
        self.bindings.append(binding)
        self.records.append(record)
        if function_node is not None:
            self.function_records[function_node.id] = record
        return record

    def build(self) -> LexicalBindingReport:
        for node in self.walk(self.root):
            if node.type == "decorator":
                self.add_gap("decorator", node)
            self._predeclare_node(node)
        self._link_members()
        for record in list(self.records):
            if record.function_node is not None:
                self._function_info(
                    record.function_node,
                    method=record.function_node.type == "method_definition",
                )
        self._finalize_types()
        self._build_function_entries()
        self._scan(self.root, "", None, ())
        return LexicalBindingReport(
            PROFILE,
            self.source_hash,
            {},
            tuple(self.bindings),
            tuple(self.references),
            tuple(self.unresolved),
            tuple(self.functions),
            tuple(self.calls),
            tuple(self.gaps),
        )

    def _ancestors(self, node: Any):
        parent = node.parent
        while parent is not None:
            yield parent
            parent = parent.parent

    def _nearest_function(self, node: Any) -> Any | None:
        return next(
            (parent for parent in self._ancestors(node) if parent.type in _FUNCTION_NODES),
            None,
        )

    def _nearest_block(self, node: Any) -> Any:
        for parent in self._ancestors(node):
            if parent.type in _BLOCK_NODES:
                return parent
        return self.root

    def _loop_head_scope(self, node: Any) -> Any | None:
        for parent in self._ancestors(node):
            if parent.type not in {"for_statement", "for_in_statement"}:
                continue
            body = parent.child_by_field_name("body")
            if body is not None and node.end_byte <= body.start_byte:
                return parent
        return None

    def _declaration_scope(self, node: Any, *, var: bool = False) -> ByteSpan:
        if var:
            for parent in self._ancestors(node):
                if parent.type in _FUNCTION_NODES:
                    body = parent.child_by_field_name("body")
                    return self.span(body if body is not None else parent)
                if parent.type in {"internal_module", "class_static_block"}:
                    return self.span(parent)
            return self.span(self.root)
        loop = self._loop_head_scope(node)
        return self.span(loop if loop is not None else self._nearest_block(node))

    def _is_ambient(self, node: Any) -> bool:
        return any(
            parent.type == "ambient_declaration"
            for parent in self._ancestors(node)
        )

    def _scope_contains(self, scope: ByteSpan | None, position: int) -> bool:
        return scope is not None and scope.start <= position < scope.end

    def _pattern_names(self, node: Any | None) -> list[Any]:
        if node is None:
            return []
        if node.type in {"identifier", "shorthand_property_identifier_pattern"}:
            return [node]
        if node.type == "pair_pattern":
            return self._pattern_names(node.child_by_field_name("value"))
        if node.type == "object_assignment_pattern":
            return self._pattern_names(node.child_by_field_name("left"))
        if node.type == "assignment_pattern":
            return self._pattern_names(node.child_by_field_name("left"))
        if node.type == "rest_pattern":
            return [
                name
                for child in self.children(node)
                for name in self._pattern_names(child)
            ]
        if node.type in {"object_pattern", "array_pattern"}:
            return [
                name
                for child in self.children(node)
                for name in self._pattern_names(child)
            ]
        return []

    def _pattern_type_node(self, owner: Any, pattern: Any) -> Any | None:
        annotation = owner.child_by_field_name("type")
        if annotation is None or pattern.type not in {"identifier", "shorthand_property_identifier_pattern"}:
            return None
        return annotation

    def _generic_parameters(self, node: Any, *, ambient: bool = False) -> None:
        parameters = node.child_by_field_name("type_parameters")
        if parameters is None:
            return
        scope = self.span(node)
        for parameter in self.children(parameters):
            if parameter.type != "type_parameter":
                continue
            name = parameter.child_by_field_name("name")
            if name is None:
                continue
            self.add_binding(
                name,
                "generic_parameter",
                scope,
                frozenset({"type"}),
                tdz=False,
                declaration_function=node.id if node.type in _FUNCTION_NODES else None,
            )

    def _predeclare_node(self, node: Any) -> None:
        if node.type in {"variable_declaration", "lexical_declaration"}:
            self._predeclare_variables(node)
        elif node.type == "for_in_statement":
            self._predeclare_for_in(node)
        elif node.type in {
            "function_declaration", "generator_function_declaration",
        }:
            name = node.child_by_field_name("name")
            if name is not None:
                self._predeclare_function(node, name, method=False)
        elif node.type == "function_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                self._predeclare_function(
                    node, name, method=False, ambient=self._is_ambient(node)
                )
        elif node.type == "method_definition":
            name = node.child_by_field_name("name")
            if name is not None and name.type not in {"computed_property_name"}:
                self._predeclare_function(node, name, method=True)
        elif node.type in {
            "class_declaration", "interface_declaration", "enum_declaration",
            "type_alias_declaration", "internal_module",
        }:
            self._predeclare_type_or_namespace(node)
        elif node.type in {"function_expression", "generator_function"}:
            name = node.child_by_field_name("name")
            if name is not None:
                self._predeclare_function(
                    node, name, method=False, expression_name=True
                )
        elif node.type == "class":
            name = node.child_by_field_name("name")
            if name is not None:
                self._predeclare_type_or_namespace(
                    node, expression_name=True
                )
        elif node.type == "import_statement":
            self._predeclare_import(node)
        if node.type in {
            "function_declaration", "function_expression",
            "generator_function_declaration", "generator_function",
            "arrow_function", "method_definition", "function_signature",
            "class_declaration", "class", "interface_declaration",
            "type_alias_declaration",
        }:
            self._generic_parameters(node)
        if node.type in _FUNCTION_NODES:
            self._predeclare_parameters(node)
        if node.type == "catch_clause":
            self._predeclare_catch_parameter(node)
    def _predeclare_variables(self, declaration: Any) -> None:
        declaration_text = self.text(declaration).lstrip()
        is_var = declaration.type == "variable_declaration"
        is_const = not is_var and re.match(r"const\b", declaration_text) is not None
        mutable = not is_const
        ambient = self._is_ambient(declaration)
        scope = self._declaration_scope(declaration, var=is_var)
        function = self._nearest_function(declaration)
        declaration_function = None if function is None else function.id
        for declarator in self.children(declaration):
            if declarator.type != "variable_declarator":
                continue
            pattern = declarator.child_by_field_name("name")
            names = self._pattern_names(pattern)
            annotation = declarator.child_by_field_name("type")
            for name in names:
                simple = len(names) == 1 and name == pattern
                kind = "ambient" if ambient else "local"
                namespaces = (
                    frozenset({"value", "type"})
                    if ambient
                    else frozenset({"value"})
                )
                self.add_binding(
                    name,
                    kind,
                    scope,
                    namespaces,
                    type_node=annotation if simple else None,
                    mutable=mutable and not self._is_readonly_parameter(name),
                    tdz=not is_var,
                    declaration_function=declaration_function,
                )

    def _predeclare_for_in(self, node: Any) -> None:
        kind = node.child_by_field_name("kind")
        pattern = node.child_by_field_name("left")
        if kind is None or pattern is None:
            return
        is_var = kind.type == "var"
        is_const = kind.type == "const"
        function = self._nearest_function(node)
        declaration_function = None if function is None else function.id
        scope = (
            self._declaration_scope(node, var=True)
            if is_var
            else self.span(node)
        )
        type_node = self._pattern_type_node(node, pattern)
        names = self._pattern_names(pattern)
        loop_binding_ids: set[str] = set()
        for name in names:
            record = self.add_binding(
                name,
                "local",
                scope,
                frozenset({"value"}),
                type_node=type_node if len(names) == 1 else None,
                mutable=not is_const,
                tdz=not is_var,
                declaration_function=declaration_function,
            )
            if not is_var:
                loop_binding_ids.add(record.binding.id)
        if loop_binding_ids:
            self._loop_binding_ids[node.id] = frozenset(loop_binding_ids)

    def _is_readonly_parameter(self, node: Any) -> bool:
        parent = node.parent
        if parent is None:
            return False
        parameter = parent
        while parameter is not None and parameter.type not in {
            "required_parameter", "optional_parameter",
        }:
            parameter = parameter.parent
        return parameter is not None and re.search(r"\breadonly\b", self.text(parameter)) is not None

    def _predeclare_function(
        self,
        node: Any,
        name: Any,
        *,
        method: bool,
        ambient: bool = False,
        expression_name: bool = False,
    ) -> _Record:
        body = node.child_by_field_name("body")
        namespaces: frozenset[str]
        if method:
            kind = "associated_function"
            scope = None
            namespaces = frozenset()
            direct = False
        elif ambient:
            kind = "ambient"
            scope = self._declaration_scope(node)
            namespaces = frozenset({"value", "type"})
            direct = False
        elif expression_name:
            kind = "function"
            scope = self.span(node)
            namespaces = frozenset({"value"})
            direct = False
        else:
            kind = "function"
            scope = self._declaration_scope(node)
            namespaces = frozenset({"value"})
            direct = True
        generator = node.type in {
            "generator_function_declaration", "generator_function",
        } or bool(
            re.search(r"\bfunction\s*\*", self.text(node))
            or (
                method
                and re.search(
                    r"(?:^|\s)\*",
                    # Only the signature head — a `*` in the body is
                    # multiplication, not the generator marker.
                    self.text(node).split("(", 1)[0],
                )
            )
        )
        record = self.add_binding(
            name,
            kind,
            scope,
            namespaces,
            body=body,
            function_node=node,
            function_declaration=direct,
            generator=generator,
            tdz=False,
            declaration_function=self._function_parent_id(node),
            self_scope=self.span(node) if expression_name else None,
            direct_function=direct,
        )
        self._function_node_ids.add(node.id)
        return record

    def _predeclare_parameters(self, node: Any) -> None:
        parameters = node.child_by_field_name("parameters")
        if parameters is None:
            parameter = node.child_by_field_name("parameter")
            parameter_nodes = [] if parameter is None else [parameter]
        else:
            parameter_nodes = self.children(parameters)
        for parameter in parameter_nodes:
            if parameter.type in {"required_parameter", "optional_parameter"}:
                pattern = parameter.child_by_field_name("pattern")
                type_node = self._pattern_type_node(parameter, pattern)
            elif node.type == "arrow_function":
                pattern = parameter
                type_node = None
            else:
                continue
            names = self._pattern_names(pattern)
            for name in names:
                self.add_binding(
                    name,
                    "parameter",
                    self.span(node),
                    frozenset({"value"}),
                    type_node=type_node if len(names) == 1 else None,
                    mutable=not self._is_readonly_parameter(parameter),
                    tdz=True,
                    declaration_function=node.id,
                )

    def _predeclare_catch_parameter(self, node: Any) -> None:
        parameter = node.child_by_field_name("parameter")
        if parameter is None:
            return
        function = self._nearest_function(node)
        function_id = None if function is None else function.id
        for name in self._pattern_names(parameter):
            self.add_binding(
                name,
                "parameter",
                self.span(node),
                frozenset({"value"}),
                mutable=True,
                declaration_function=function_id,
            )

    def _function_parent_id(self, node: Any) -> int | None:
        parent = self._nearest_function(node)
        return None if parent is None else parent.id

    def _predeclare_type_or_namespace(
        self, node: Any, *, expression_name: bool = False
    ) -> None:
        name = node.child_by_field_name("name")
        if name is None or name.type == "string":
            return
        kind_by_node = {
            "class_declaration": "class",
            "class": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "type_alias_declaration": "type_alias",
            "internal_module": "namespace",
        }
        kind = "ambient" if self._is_ambient(node) and node.type == "class_declaration" else kind_by_node[node.type]
        if expression_name:
            scope = self.span(node)
        else:
            scope = self._declaration_scope(node)
        namespaces = {
            "class": frozenset({"value", "type"}),
            "interface": frozenset({"type"}),
            "enum": frozenset({"value", "type"}),
            "type_alias": frozenset({"type"}),
            "namespace": frozenset({"value", "type"}),
            "ambient": frozenset({"value", "type"}),
        }[kind]
        record = self.add_binding(
            name,
            kind,
            scope,
            namespaces,
            alias_node=node.child_by_field_name("value"),
            class_like=kind in {"class", "interface", "enum", "ambient"},
            # Ambient declarations (`declare class`/`declare enum`)
            # don't initialize anything at runtime — no TDZ.
            tdz=node.type in {"class_declaration", "enum_declaration"}
            and not self._is_ambient(node),
            declaration_function=self._function_parent_id(node),
            self_scope=self.span(node) if expression_name else None,
        )
        if kind in {"class", "interface", "enum"}:
            record.binding = replace(
                record.binding,
                type=TypeFact("named", record.binding.name, 0, None, record.binding.id),
            )
            self.bindings[self.bindings.index(next(
                binding for binding in self.bindings if binding.id == record.binding.id
            ))] = record.binding

    def _predeclare_import(self, node: Any) -> None:
        type_only_statement = any(
            child.type == "type" for child in node.children
        )
        require_clause = next(
            (child for child in self.children(node) if child.type == "import_require_clause"),
            None,
        )
        if require_clause is not None:
            local_name = next(
                (item for item in self.children(require_clause) if item.type == "identifier"),
                None,
            )
            if local_name is not None:
                self.add_binding(
                    local_name,
                    "import",
                    self.span(self.root),
                    frozenset({"type", "value"}),
                )
            return
        clause = next(
            (child for child in self.children(node) if child.type == "import_clause"),
            None,
        )
        if clause is None:
            return
        for child in self.children(clause):
            local_name = None
            type_only = type_only_statement
            if child.type == "identifier":
                local_name = child
            elif child.type == "namespace_import":
                local_name = next(
                    (item for item in self.children(child) if item.type == "identifier"),
                    None,
                )
            elif child.type == "named_imports":
                for specifier in self.children(child):
                    if specifier.type != "import_specifier":
                        continue
                    alias = specifier.child_by_field_name("alias")
                    local_name = alias or specifier.child_by_field_name("name")
                    local_type_only = type_only_statement or any(
                        item.type == "type" for item in specifier.children
                    )
                    if local_name is not None:
                        self.add_binding(
                            local_name,
                            "import",
                            self.span(self.root),
                            frozenset({"type"}) if local_type_only else frozenset({"type", "value"}),
                            type_only=local_type_only,
                        )
                continue
            elif child.type == "import_require_clause":
                local_name = next(
                    (item for item in self.children(child) if item.type == "identifier"),
                    None,
                )
            if local_name is not None:
                self.add_binding(
                    local_name,
                    "import",
                    self.span(self.root),
                    frozenset({"type"}) if type_only else frozenset({"type", "value"}),
                    type_only=type_only,
                )

    def _function_info(self, node: Any, *, method: bool = False) -> None:
        record = self.function_records.get(node.id)
        if record is None:
            return
        params = node.child_by_field_name("parameters")
        parameter_records = [
            item
            for item in self.records
            if item.binding.kind == "parameter"
            and self._scope_contains(item.binding.scope, node.start_byte)
            and item.declaration_function == node.id
        ]
        is_async = bool(
            re.search(r"(?:^|\s)async\s", self.text(node))
        )
        generator = record.generator
        info = _FunctionInfo(
            record,
            node,
            node.child_by_field_name("body"),
            parameter_records,
            node.child_by_field_name("type_parameters") is not None,
            is_async,
            method,
            params is not None and any(
                item.type == "required_parameter"
                and self.text(item).lstrip().startswith("...")
                for item in self.children(params)
            ),
            generator,
        )
        self.function_infos[node.id] = info

    def _build_function_entries(self) -> None:
        for info in self.function_infos.values():
            return_node = info.node.child_by_field_name("return_type")
            result = self._type_fact(return_node)
            parameters = tuple(
                record.binding.id
                for record in sorted(
                    info.parameter_records,
                    key=lambda record: record.binding.span.start,
                )
            )
            self.functions.append(
                Function(
                    info.record.binding.id,
                    None if info.body is None else self.span(info.body),
                    parameters,
                    result,
                    info.generic,
                    info.is_async,
                    info.method,
                    info.variadic,
                )
            )

    def _finalize_types(self) -> None:
        for record in self.records:
            if record.type_node is None and record.alias_node is None:
                continue
            if record.binding.kind == "type_alias":
                fact = self._type_fact(record.alias_node, {record.binding.id})
                if fact.type_id != record.binding.id:
                    fact = replace(fact, type_id=record.binding.id)
            else:
                fact = self._type_fact(record.type_node)
            record.binding = replace(record.binding, type=fact)
        self.bindings = [record.binding for record in self.records]
        self._type_alias_cache.clear()

    def _unwrap_type(self, node: Any | None) -> Any | None:
        if node is None:
            return None
        if node.type in {"type_annotation", "return_type"}:
            children = self.children(node)
            return children[-1] if children else None
        return node

    def _type_fact(
        self, node: Any | None, visited: set[str] | None = None
    ) -> TypeFact:
        node = self._unwrap_type(node)
        if node is None:
            return _UNKNOWN
        visited = set() if visited is None else visited
        text = self.text(node).strip()
        if node.type == "predefined_type" and text in _PRIMITIVE_FACTS:
            return _PRIMITIVE_FACTS[text]
        if node.type == "type_identifier" and text in _PRIMITIVE_FACTS:
            return _PRIMITIVE_FACTS[text]
        if node.type in {
            "type_query", "member_expression", "nested_type_identifier",
        }:
            return _UNKNOWN
        if node.type == "type_identifier":
            record = self._lookup(text, node.start_byte, "type")
            if record is None:
                return _UNKNOWN
            if record.binding.kind == "type_alias":
                if record.binding.id in visited:
                    return TypeFact("unknown", text, 0, None, record.binding.id)
                cached = self._type_alias_cache.get(record.binding.id)
                if cached is not None:
                    return cached
                alias_visited = set(visited)
                alias_visited.add(record.binding.id)
                fact = self._type_fact(record.alias_node, alias_visited)
                if fact.kind == "unknown":
                    fact = TypeFact("unknown", text, 0, None, record.binding.id)
                else:
                    fact = replace(fact, type_id=record.binding.id)
                self._type_alias_cache[record.binding.id] = fact
                return fact
            if record.class_like or record.binding.kind in {
                "class", "interface", "enum", "namespace",
            }:
                return TypeFact(
                    "named",
                    record.binding.name,
                    0,
                    None,
                    record.binding.id,
                )
            return _UNKNOWN
        return _UNKNOWN

    def _lookup(
        self, name: str, position: int, namespace: str
    ) -> _Record | None:
        candidates: list[tuple[int, _Record]] = []
        for record in self.records:
            if namespace not in record.namespaces or record.binding.name != name:
                continue
            scope = record.binding.scope
            if self._scope_contains(scope, position):
                width = scope.end - scope.start if scope is not None else 0
                candidates.append((width, record))
            elif self._scope_contains(record.self_scope, position):
                self_scope = record.self_scope
                assert self_scope is not None
                candidates.append((self_scope.end - self_scope.start, record))
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                item[0],
                0 if item[1].body is not None else 1,
                -item[1].binding.span.start,
            )
        )
        return candidates[0][1]

    _MEMBER_DECLARATIONS = {
        "function_declaration", "generator_function_declaration",
        # `function f(): void` in an ambient namespace is a bare
        # function_signature, not wrapped in ambient_declaration.
        "function_signature",
        "class_declaration", "abstract_class_declaration",
        "interface_declaration", "enum_declaration",
        "type_alias_declaration", "internal_module",
        "lexical_declaration", "variable_declaration",
        "export_statement", "ambient_declaration",
    }

    def _member_visibility(self, member: Any, name_node: Any) -> str:
        if name_node.type == "private_property_identifier":
            return "private"
        for child in member.children:
            if child.type == "accessibility_modifier":
                text = self.text(child).strip()
                if text in {"private", "protected", "public"}:
                    return text
        return "public"

    def _link_members(self) -> None:
        """Attach member bindings to their declaring type or namespace.

        `method_definition` records exist by the time this runs; fields,
        signatures and enum members are declared here so every member is
        reachable through its declaring type record.
        """
        for record in list(self.records):
            decl = record.node.parent
            if decl is None:
                continue
            body = decl.child_by_field_name("body")
            if body is None:
                continue
            if record.class_like:
                bases: list[str] = []
                for child in self.children(decl):
                    heritage = (
                        self.children(child)
                        if child.type == "class_heritage"
                        else [child]
                        if child.type
                        in {
                            "extends_clause", "implements_clause",
                            "extends_type_clause",
                        }
                        else []
                    )
                    for clause in heritage:
                        if clause.type not in {
                            "extends_clause", "implements_clause",
                            "extends_type_clause",
                        }:
                            continue
                        for name_node in self.children(clause):
                            text = self.text(name_node).strip()
                            match = re.match(
                                r"[A-Za-z_$][A-Za-z0-9_$]*"
                                r"(?:\s*\.\s*[A-Za-z_$][A-Za-z0-9_$]*)*",
                                text,
                            )
                            if match:
                                bases.append(
                                    re.sub(r"\s+", "", match.group(0))
                                )
                self._type_bases[decl.id] = bases
                for member in self.children(body):
                    name_node = member.child_by_field_name("name")
                    if name_node is None and member.type == "enum_assignment":
                        name_node = next(
                            (
                                child
                                for child in self.children(member)
                                if child.type == "property_identifier"
                            ),
                            None,
                        )
                    if (
                        name_node is None
                        and body.type == "enum_body"
                        and member.type == "property_identifier"
                    ):
                        name_node = member
                    if name_node is None or name_node.type in {
                        "computed_property_name",
                    }:
                        continue
                    modifiers = [
                        child
                        for child in member.children
                        if child.type != "comment"
                    ]
                    is_static = any(
                        child.type == "static" or self.text(child) == "static"
                        for child in modifiers
                    )
                    visibility = self._member_visibility(member, name_node)
                    if member.type in {
                        "method_definition", "method_signature",
                        "abstract_method_signature",
                    }:
                        member_record = self.function_records.get(member.id)
                        if member_record is None:
                            member_record = self._predeclare_function(
                                member, name_node, method=True
                            )
                    elif member.type in {
                        "public_field_definition", "property_signature",
                    }:
                        member_record = self.add_binding(
                            name_node,
                            "struct_field",
                            self.span(body),
                            frozenset(),
                            type_node=member.child_by_field_name("type"),
                            mutable=not any(
                                self.text(child) == "readonly"
                                for child in modifiers
                            ),
                        )
                    elif (
                        member.type == "enum_assignment"
                        or body.type == "enum_body"
                    ) and name_node.type == "property_identifier":
                        member_record = self.add_binding(
                            name_node,
                            "enum_member",
                            self.span(body),
                            frozenset(),
                        )
                    else:
                        continue
                    member_record.member_of = decl.id
                    member_record.member_static = is_static
                    member_record.member_visibility = visibility
                    member_record.member_container = (
                        self._decl_qualified_name(decl)
                    )
            elif decl.type == "internal_module":
                for other in self.records:
                    if other is record or other.member_of is not None:
                        continue
                    node = other.node
                    boundary = False
                    while (
                        node.parent is not None
                        and node.parent.id != body.id
                    ):
                        node = node.parent
                        own_declaration = (
                            node.type == "internal_module"
                            and node.child_by_field_name("name") is not None
                            and node.child_by_field_name("name").id
                            == other.node.id
                        )
                        if not own_declaration and node.type in {
                            "internal_module", "class_body",
                            "interface_body", "enum_body",
                            "statement_block",
                        }:
                            boundary = True
                            break
                    if (
                        not boundary
                        and node.parent is not None
                        and node.parent.id == body.id
                        and node.type in self._MEMBER_DECLARATIONS
                    ):
                        other.member_of = decl.id
                        # Namespace members sit on the namespace object —
                        # treat them as static for call-kind selection.
                        other.member_static = True
                        # Only `export`ed members are reachable through
                        # qualified `N.x` access — a block-private
                        # declaration is module-local, like a class's
                        # private member. Ambient namespaces export
                        # every member implicitly, at any depth.
                        ambient = False
                        ancestor = decl.parent
                        while ancestor is not None:
                            if ancestor.type == "ambient_declaration":
                                ambient = True
                                break
                            ancestor = ancestor.parent
                        other.member_visibility = (
                            "public"
                            if node.type == "export_statement"
                            or ambient
                            else "private"
                        )
                        other.member_container = (
                            self._decl_qualified_name(decl)
                        )

    def _type_record_by_id(self, binding_id_value: str) -> _Record | None:
        for record in self.records:
            if record.binding.id == binding_id_value and (
                record.class_like or record.binding.kind == "namespace"
            ):
                return record
        return None

    def _type_record_for_node(self, decl_node: Any | None) -> _Record | None:
        if decl_node is None:
            return None
        name = decl_node.child_by_field_name("name")
        name_id = None if name is None else name.id
        for record in self.records:
            if record.node.id == name_id and (
                record.class_like or record.binding.kind == "namespace"
            ):
                return record
        return None

    def _enclosing_type_record(self, node: Any) -> _Record | None:
        ancestor = node.parent
        while ancestor is not None:
            if ancestor.type in {
                "function_declaration", "function_expression",
                "generator_function_declaration", "generator_function",
            }:
                return None
            if ancestor.type in {
                "class_declaration", "class", "abstract_class_declaration",
            }:
                return self._type_record_for_node(ancestor)
            ancestor = ancestor.parent
        return None

    def _member_lookup(
        self,
        type_record: _Record,
        name: str,
        position: int,
        *,
        static: bool,
        via_this: bool,
    ) -> _Record | None:
        """BFS over the declaring type and its bases for member `name`."""
        queue = [type_record]
        # Declaration merging: a namespace may merge with a class,
        # interface or enum of the same name in the same container, so
        # the siblings' members merge into a single type. A merged
        # namespace only augments the static side — instance lookups
        # skip it.
        for sibling in self._merge_siblings(type_record):
            if not static and sibling.binding.kind == "namespace":
                continue
            queue.append(sibling)
        visited: set[str] = set()
        seed_ids = {record.binding.id for record in queue}
        while queue:
            current = queue.pop(0)
            if current.binding.id in visited:
                continue
            visited.add(current.binding.id)
            first = current.binding.id in seed_ids
            decl = current.node.parent
            decl_id = None if decl is None else decl.id
            namespace_member = current.binding.kind == "namespace"
            for candidate in self.records:
                if (
                    decl_id is None
                    or candidate.member_of != decl_id
                    or candidate.binding.name != name
                ):
                    continue
                if (
                    not namespace_member
                    and candidate.binding.kind != "enum_member"
                    and candidate.member_static != static
                ):
                    continue
                if candidate.member_visibility == "private" and (
                    not via_this or not first
                ):
                    continue
                if candidate.member_visibility == "protected" and not via_this:
                    continue
                return candidate
            if decl_id is not None and decl is not None:
                for base in self._type_bases.get(decl_id, ()):
                    # Bases are resolved where the `extends`/`implements`
                    # clause is spelled — a use-site scope may shadow the
                    # base name with an unrelated declaration.
                    base_record = self._base_type_record(
                        base, decl.start_byte
                    )
                    if base_record is not None:
                        queue.append(base_record)
        return None

    def _base_type_record(
        self, base: str, position: int
    ) -> _Record | None:
        """Resolve an extends/implements spelling, incl. `N.Base` chains."""
        segments = [segment.strip() for segment in base.split(".")]
        record = self._lookup(segments[0], position, "type")
        if record is None:
            record = self._lookup(segments[0], position, "value")
        for segment in segments[1:]:
            if record is None:
                return None
            record = self._member_lookup(
                record, segment, position, static=True, via_this=False
            )
        return record

    def _callee_return_node(self, node: Any) -> Any | None:
        """Return-type annotation node of a call's resolved callee."""
        callee = node.child_by_field_name("function")
        record: _Record | None = None
        if callee is not None and callee.type == "identifier":
            record = self._lookup(
                self.text(callee), node.start_byte, "value"
            )
        elif callee is not None and callee.type == "member_expression":
            property_node = callee.child_by_field_name("property")
            if (
                property_node is not None
                and property_node.type == "property_identifier"
            ):
                record = self._resolve_member(
                    callee.child_by_field_name("object"),
                    self.text(property_node),
                    node.start_byte,
                )
        if record is None or record.function_node is None:
            return None
        return_node = record.function_node.child_by_field_name("return_type")
        if return_node is None:
            for child in self.children(record.function_node):
                if child.type in {"type_annotation", "return_type"}:
                    return_node = child
        return return_node

    def _return_type_record(self, node: Any) -> _Record | None:
        """Type record named by a call's return annotation, if resolvable."""
        return_node = self._callee_return_node(node)
        if return_node is None:
            return None
        fact = self._type_fact(next(iter(self.children(return_node)), None))
        if fact.kind != "named":
            return None
        return self._type_record_by_id(fact.type_id)

    def _declared_type_node(self, node: Any | None, position: int) -> Any | None:
        """The declaring type's syntax node for a member/subscript object."""
        if node is None:
            return None
        if node.type == "identifier":
            record = self._lookup(self.text(node), position, "value")
            if record is None:
                return None
            return self._unwrap_type(record.type_node)
        if node.type == "member_expression":
            property_node = node.child_by_field_name("property")
            if (
                property_node is None
                or property_node.type != "property_identifier"
            ):
                return None
            member = self._resolve_member(
                node.child_by_field_name("object"),
                self.text(property_node),
                position,
            )
            if member is None:
                return None
            return self._unwrap_type(member.type_node)
        if node.type == "call_expression":
            return_node = self._callee_return_node(node)
            if return_node is None:
                return None
            return self._unwrap_type(
                next(iter(self.children(return_node)), None)
            )
        if node.type == "subscript_expression":
            inner = self._declared_type_node(
                node.child_by_field_name("object"), position
            )
            if inner is not None and inner.type == "array_type":
                return next(iter(self.children(inner)), None)
            return None
        if node.type in {
            "parenthesized_expression", "non_null_expression",
            "as_expression", "satisfies_expression",
        }:
            return self._declared_type_node(
                next(iter(self.children(node)), None), position
            )
        return None

    def _initializer_type_record(
        self, record: _Record, position: int
    ) -> _Record | None:
        """Type named by a variable's `new T(...)` initializer."""
        if record.binding.id in self._initializer_active:
            return None
        declarator = record.node.parent
        if declarator is None or declarator.type != "variable_declarator":
            return None
        value = declarator.child_by_field_name("value")
        if value is None or value.type != "new_expression":
            return None
        constructor = value.child_by_field_name("constructor")
        if constructor is None:
            return None
        # Names in the initializer resolve at the initializer, not at a
        # later use site where a same-named local may shadow them.
        init_position = value.start_byte
        self._initializer_active.add(record.binding.id)
        try:
            if constructor.type in {"identifier", "type_identifier"}:
                resolved = self._lookup(
                    self.text(constructor), init_position, "type"
                )
                return (
                    self._merged_constructible(resolved)
                    if resolved is not None
                    else None
                )
            if constructor.type == "member_expression":
                property_node = constructor.child_by_field_name("property")
                if property_node is None:
                    return None
                resolved = self._resolve_member(
                    constructor.child_by_field_name("object"),
                    self.text(property_node),
                    init_position,
                )
                return (
                    self._merged_constructible(resolved)
                    if resolved is not None
                    else None
                )
            return None
        finally:
            self._initializer_active.discard(record.binding.id)

    def _decl_qualified_name(self, decl: Any) -> str:
        """Dotted name of a declaration, climbing `internal_module`s."""
        parts = []
        node = decl
        while node is not None:
            if node.type in {
                "internal_module", "class_declaration",
                "abstract_class_declaration", "interface_declaration",
                "enum_declaration",
            }:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    parts.insert(0, self.text(name_node))
            node = node.parent
        return ".".join(parts)

    def _merge_kind(self, record: _Record) -> str:
        """Declaration-merging kind of a record.

        `declare` statements all carry binding kind `ambient`, but the
        merge rules treat an ambient class, an ambient function and an
        ambient variable differently — recover the declared kind from
        the declaration node the record's name node climbs to.
        """
        if record.binding.kind != "ambient":
            return record.binding.kind
        node = record.node
        while node is not None and node.type in {
            "identifier", "type_identifier", "property_identifier",
            "variable_declarator",
        }:
            node = node.parent
        node_type = node.type if node is not None else ""
        if node_type in {
            "class_declaration", "abstract_class_declaration", "class",
        }:
            return "ambient_class"
        if node_type in {"function_declaration", "function_signature"}:
            return "ambient_function"
        return "ambient_var"

    def _mergeable_kind_pair(self, first: str, second: str) -> bool:
        """Whether two same-named declarations may merge (verified
        against tsc): `namespace` merges with anything; `enum` only
        with `enum`; `interface` with `interface`/`class`/ambient
        class/`function`/ambient function; an ambient class with
        `interface`/`function`/ambient function; `function` overloads.
        `class`+`class`, ambient+ambient class, `class`+ambient class,
        `class`+`function`, `enum`+anything-but-{enum,namespace} and
        pairs involving non-declaration kinds (`local`, `import`,
        `type_alias`, ambient variables) are duplicate-identifier
        errors, not merges."""
        kinds = {first, second}
        if "namespace" in kinds:
            return True
        if "enum" in kinds:
            return kinds == {"enum"}
        if "ambient_var" in kinds or "local" in kinds:
            # A variable only merges with an `interface`/`type` (the
            # type side of the name) — `const`/`declare const` +
            # `namespace` is legal only when the namespace exports no
            # value members, which _merge_siblings checks separately.
            return kinds - {"ambient_var", "local"} in (
                {"interface"}, {"type_alias"},
            )
        if kinds <= {"class", "ambient_class"}:
            return False
        if "ambient_class" in kinds:
            return kinds <= {
                "ambient_class", "interface", "function",
                "ambient_function",
            }
        return (
            kinds <= {"interface", "class"}
            or kinds <= {"interface", "function", "ambient_function"}
        )

    def _merge_siblings(self, record: _Record) -> list[_Record]:
        """Same-named declarations that merge into `record`'s entity.

        Siblings share a member container (a single namespace block, or
        several same-named blocks — declaration merging works across
        split `namespace N` declarations) or the same top-level scope.
        """
        siblings = []
        for sibling in self.records:
            if (
                sibling is record
                or sibling.binding.name != record.binding.name
            ):
                continue
            if not self._mergeable_kind_pair(
                self._merge_kind(record), self._merge_kind(sibling)
            ):
                continue
            if (
                "namespace" in {
                    self._merge_kind(record), self._merge_kind(sibling)
                }
                and {
                    self._merge_kind(record), self._merge_kind(sibling)
                }
                & {"ambient_var", "local"}
            ):
                ns = (
                    record
                    if self._merge_kind(record) == "namespace"
                    else sibling
                )
                if self._namespace_exports_value(ns):
                    continue
            if self._same_declaration_family(record, sibling):
                siblings.append(sibling)
        # Exported members are the public face of the merged name — a
        # block-private duplicate (non-exported member of a namespace
        # block) must not shadow them in member or `new` resolution.
        siblings.sort(key=lambda s: not self._is_exported_member(s))
        return siblings

    def _is_exported_member(self, record: _Record) -> bool:
        if record.member_of is None:
            return True
        node = record.node
        while node is not None and node.id != record.member_of:
            if node.type == "export_statement":
                return True
            node = node.parent
        return False

    def _namespace_exports_value(self, ns_record: _Record) -> bool:
        """Whether any same-named namespace block exports a value.

        tsc only accepts `namespace K` next to a same-named variable
        when the merged namespace exports types alone — a single
        exported value member makes the pair a redeclaration.
        """
        decl = ns_record.node.parent
        if decl is None:
            return False
        qname = self._decl_qualified_name(decl)
        owner_ids = {
            s.node.parent.id
            for s in self.records
            if s.binding.kind == "namespace"
            and s.node.parent is not None
            and self._decl_qualified_name(s.node.parent) == qname
        }
        for member in self.records:
            if (
                member.member_of in owner_ids
                and member.binding.kind not in {"interface", "type_alias"}
                and self._is_exported_member(member)
            ):
                return True
        return False

    def _merged_constructible(self, record: _Record) -> _Record:
        """Prefer the class (or ambient class) of a merged declaration."""
        merge_kind = self._merge_kind(record)
        if merge_kind in {"class", "ambient_class"}:
            return record
        if merge_kind not in {
            "interface", "enum", "namespace", "type_alias", "function",
            "ambient_function",
        }:
            # Only declaration-merging participants can stand in for a
            # class: a `local`/`import`/ambient variable named like a
            # class in a sibling block is a duplicate identifier, not
            # a merge — its references must name the variable.
            return record
        siblings = self._merge_siblings(record)
        for preferred in ("class", "ambient_class"):
            for sibling in siblings:
                if self._merge_kind(sibling) == preferred:
                    return sibling
        if merge_kind in {"interface", "namespace", "type_alias"}:
            # Type-only names can't be `new`'d: a same-scope value-side
            # declaration (e.g. `declare const C` carrying a construct
            # signature) is the honest referent for the constructor.
            candidates = [
                sibling
                for sibling in self.records
                if sibling is not record
                and sibling.binding.name == record.binding.name
                and self._same_declaration_family(record, sibling)
                and self._merge_kind(sibling)
                in {"local", "ambient_var", "function"}
            ]
            candidates.sort(
                key=lambda s: not self._is_exported_member(s)
            )
            if candidates:
                return candidates[0]
        return record

    def _same_declaration_family(
        self, record: _Record, sibling: _Record
    ) -> bool:
        return (
            (
                sibling.member_of is not None
                and sibling.member_of == record.member_of
            )
            or (
                sibling.member_container is not None
                and sibling.member_container == record.member_container
                and record.member_container is not None
            )
            or (
                sibling.member_of is None
                and record.member_of is None
                and sibling.binding.scope == record.binding.scope
            )
        )

    def _object_type(
        self, node: Any | None, position: int
    ) -> tuple[_Record | None, bool, bool]:
        """(type record, static side, via this/super) for a member object."""
        if node is None:
            return None, False, False
        if node.type == "this":
            record = self._enclosing_type_record(node)
            return record, False, True
        if node.type == "super":
            current = self._enclosing_type_record(node)
            if current is None:
                return None, False, True
            decl = current.node.parent
            for base in self._type_bases.get(
                None if decl is None else decl.id, ()
            )[:1]:
                base_record = self._base_type_record(
                    base, decl.start_byte
                )
                if base_record is not None:
                    return base_record, False, True
            return None, False, True
        if node.type == "identifier":
            record = self._lookup(self.text(node), position, "value")
            if record is None:
                return None, False, False
            if record.class_like or record.binding.kind == "namespace":
                return record, True, False
            fact = record.binding.type
            if fact is not None and fact.kind == "named":
                return self._type_record_by_id(fact.type_id), False, False
            fact = self._type_fact(record.type_node)
            if fact.kind == "named":
                return (
                    self._type_record_by_id(fact.type_id),
                    False,
                    False,
                )
            inferred = self._initializer_type_record(record, position)
            return inferred, False, False
        if node.type == "member_expression":
            property_node = node.child_by_field_name("property")
            if (
                property_node is None
                or property_node.type != "property_identifier"
            ):
                return None, False, False
            member = self._resolve_member(
                node.child_by_field_name("object"),
                self.text(property_node),
                position,
            )
            if member is None:
                return None, False, False
            if member.class_like or member.binding.kind == "namespace":
                return member, True, False
            fact = self._type_fact(member.type_node)
            if fact.kind != "named":
                return None, False, False
            return self._type_record_by_id(fact.type_id), False, False
        if node.type == "call_expression":
            return self._return_type_record(node), False, False
        if node.type == "subscript_expression":
            type_node = self._declared_type_node(node, position)
            fact = self._type_fact(type_node)
            if fact.kind != "named":
                return None, False, False
            return self._type_record_by_id(fact.type_id), False, False
        if node.type == "new_expression":
            constructor = node.child_by_field_name("constructor")
            if constructor is not None and constructor.type in {
                "identifier", "type_identifier",
            }:
                resolved = self._lookup(
                    self.text(constructor), position, "type"
                )
                return (
                    (
                        self._merged_constructible(resolved)
                        if resolved is not None
                        else None
                    ),
                    False,
                    False,
                )
            if constructor is not None and constructor.type == "member_expression":
                property_node = constructor.child_by_field_name("property")
                if property_node is not None:
                    record = self._resolve_member(
                        constructor.child_by_field_name("object"),
                        self.text(property_node),
                        position,
                    )
                    if record is not None:
                        return (
                            self._merged_constructible(record),
                            False,
                            False,
                        )
            return None, False, False
        if node.type in {
            "parenthesized_expression", "non_null_expression",
            "as_expression", "satisfies_expression", "await_expression",
        }:
            return self._object_type(
                next(iter(self.children(node)), None), position
            )
        return None, False, False

    def _resolve_member(
        self, object_node: Any | None, name: str, position: int
    ) -> _Record | None:
        type_record, static, via_this = self._object_type(
            object_node, position
        )
        if type_record is None:
            return None
        return self._member_lookup(
            type_record,
            name,
            position,
            static=static,
            via_this=via_this,
        )

    def _resolve(
        self,
        node: Any,
        namespace: str,
        kind: str,
        with_scopes: tuple[ByteSpan, ...] = (),
        *,
        tdz_function: Any | None = None,
        check_tdz: bool = True,
        constructible: bool = False,
    ) -> tuple[_Record | None, str | None]:
        name = self.text(node)
        if name == "arguments" and namespace == "value":
            self.add_unresolved(node, name, "arguments_object")
            return None, "arguments_object"
        if any(self._scope_contains(scope, node.start_byte) for scope in with_scopes):
            self.add_unresolved(node, name, "with_scope")
            return None, "with_scope"
        record = self._lookup(name, node.start_byte, namespace)
        if record is not None and constructible:
            # `new N()` on a merged declaration must name the class, so
            # the reference lands on the class before it is emitted.
            record = self._merged_constructible(record)
        if record is not None:
            if record.binding.span == self.span(node):
                return record, None
            if (
                kind == "write"
                and record.binding.kind in {
                    "function", "associated_function", "class", "interface",
                    "enum", "type_alias", "namespace", "import",
                    "generic_parameter",
                }
            ):
                self.add_reference(node, record, "read")
                self.add_gap("unsupported_syntax", node)
                return record, "unsupported_syntax"
            self.add_reference(node, record, kind)
            reference_function = self._nearest_function(node)
            reference_function_id = (
                None if reference_function is None else reference_function.id
            )
            if (
                check_tdz
                and record.tdz
                and (
                    record.binding.id in self._tdz_binding_ids
                    or (
                        node.start_byte < record.binding.span.start
                        and record.declaration_function == reference_function_id
                    )
                )
            ):
                self.add_gap("temporal_dead_zone", node)
            return record, None
        if kind == "write":
            reason = "implicit_global"
        elif namespace == "type" and name in _TYPE_BUILTINS:
            reason = "builtin"
        elif name in _BUILTIN_VALUES and namespace == "value":
            reason = "builtin"
        else:
            reason = "unknown_name"
        self.add_unresolved(node, name, reason)
        return None, reason

    def _scan_type(self, node: Any | None) -> None:
        if node is None or node.type == "comment":
            return
        if node.type in {"type_annotation", "return_type"}:
            for child in self.children(node):
                self._scan_type(child)
            return
        if node.type == "type_query":
            expression = next(iter(self.children(node)), None)
            if expression is not None and expression.type in {
                "member_expression", "subscript_expression",
            }:
                root = expression
                while root.type in {"member_expression", "subscript_expression"}:
                    root = root.child_by_field_name("object")
                if root is not None and root.type == "identifier":
                    self._resolve(root, "value", "read", check_tdz=False)
                    return
            elif expression is not None and expression.type == "identifier":
                self._resolve(expression, "value", "read", check_tdz=False)
                return
            self.add_unresolved(node, self.text(node).strip(), "qualified_path")
            return
        if node.type in {"member_expression", "nested_type_identifier"}:
            self.add_unresolved(node, self.text(node).strip(), "qualified_path")
            return
        if node.type == "type_identifier":
            if self.text(node) in _PRIMITIVE_FACTS:
                return
            self._resolve(node, "type", "read")
            return
        if node.type in {"import_type", "import"}:
            self.add_unresolved(node, self.text(node).strip(), "qualified_path")
            return
        for child in self.children(node):
            self._scan_type(child)

    def _scan_pattern_defaults(
        self,
        pattern: Any | None,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
    ) -> None:
        if pattern is None:
            return
        if pattern.type in {"assignment_pattern", "object_assignment_pattern"}:
            self._scan_pattern_defaults(
                pattern.child_by_field_name("left"),
                owner,
                function_context,
                with_scopes,
            )
            self._scan(
                pattern.child_by_field_name("right"),
                owner,
                function_context,
                with_scopes,
            )
            return
        if pattern.type == "pair_pattern":
            key = pattern.child_by_field_name("key")
            if key is not None and key.type == "computed_property_name":
                self._scan(key, owner, function_context, with_scopes)
            self._scan_pattern_defaults(
                pattern.child_by_field_name("value"),
                owner,
                function_context,
                with_scopes,
            )
            return
        for child in self.children(pattern):
            if child.type == "computed_property_name":
                self._scan(child, owner, function_context, with_scopes)
            else:
                self._scan_pattern_defaults(
                    child, owner, function_context, with_scopes
                )

    def _scan_parameters(
        self,
        node: Any,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
    ) -> None:
        parameters = node.child_by_field_name("parameters")
        if parameters is None:
            parameter = node.child_by_field_name("parameter")
            if parameter is not None:
                self._scan_pattern_defaults(
                    parameter, owner, function_context, with_scopes
                )
            return
        for parameter in self.children(parameters):
            pattern = parameter.child_by_field_name("pattern")
            self._scan_type(parameter.child_by_field_name("type"))
            self._scan_pattern_defaults(
                pattern, owner, function_context, with_scopes
            )
            default = parameter.child_by_field_name("value")
            self._scan(default, owner, function_context, with_scopes)

    def _scan_function(
        self,
        node: Any,
        enclosing_owner: str,
        with_scopes: tuple[ByteSpan, ...],
    ) -> None:
        info = self.function_infos.get(node.id)
        record = self.function_records.get(node.id)
        name = node.child_by_field_name("name")
        if name is not None and name.type == "computed_property_name":
            self._scan(name, enclosing_owner, None, with_scopes)
        for child in self.children(node):
            if child.type == "decorator":
                self._scan(child, "", None, with_scopes)
        self._scan_type(node.child_by_field_name("type_parameters"))
        parameter_owner = ""
        if record is not None and (
            (info is not None and info.method) or record.direct_function
        ):
            parameter_owner = record.binding.id
        self._scan_parameters(
            node,
            parameter_owner,
            node,
            with_scopes,
        )
        self._scan_type(node.child_by_field_name("return_type"))
        if node.type in {"function_expression", "generator_function"}:
            body_owner = ""
        elif record is not None and (record.direct_function or (info is not None and info.method)):
            body_owner = record.binding.id
        else:
            body_owner = ""
        body = node.child_by_field_name("body")
        if body is not None:
            self._scan(body, body_owner, node, with_scopes)

    def _scan_class(self, node: Any, owner: str, with_scopes: tuple[ByteSpan, ...]) -> None:
        name = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        type_parameters = node.child_by_field_name("type_parameters")
        self._scan_type(type_parameters)
        for child in self.children(node):
            if child == name or child == body or child == type_parameters:
                continue
            if child.type == "class_heritage":
                for clause in self.children(child):
                    if clause.type == "extends_clause":
                        self._scan(
                            clause.child_by_field_name("value"),
                            owner,
                            None,
                            with_scopes,
                        )
                    elif clause.type == "implements_clause":
                        self._scan_type(clause)
            elif child.type == "extends_clause":
                self._scan(
                    child.child_by_field_name("value"),
                    owner,
                    None,
                    with_scopes,
                )
            elif child.type == "implements_clause":
                self._scan_type(child)
            elif child.type == "decorator":
                self._scan(child, owner, None, with_scopes)
            else:
                self._scan(child, owner, None, with_scopes)
        if body is None:
            return
        for member in self.children(body):
            if member.type == "method_definition":
                self._scan_function(member, owner, with_scopes)
            elif member.type == "public_field_definition":
                name = member.child_by_field_name("name")
                if name is not None and name.type == "computed_property_name":
                    self._scan(name, owner, None, with_scopes)
                self._scan_type(member.child_by_field_name("type"))
                value = member.child_by_field_name("value")
                self._scan(value, "", None, with_scopes)
                for child in self.children(member):
                    if child.type == "decorator":
                        self._scan(child, "", None, with_scopes)
            elif member.type == "class_static_block":
                self._scan(member, "", None, with_scopes)
            else:
                self._scan(member, owner, None, with_scopes)

    def _scan_variable_declaration(
        self,
        node: Any,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
    ) -> None:
        for declarator in self.children(node):
            if declarator.type != "variable_declarator":
                continue
            self._scan_type(declarator.child_by_field_name("type"))
            pattern = declarator.child_by_field_name("name")
            self._scan_pattern_defaults(
                pattern, owner, function_context, with_scopes
            )
            self._scan(
                declarator.child_by_field_name("value"),
                owner,
                function_context,
                with_scopes,
            )

    def _scan_assignment_target(
        self,
        node: Any | None,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
        *,
        compound: bool,
        assignment_node: Any,
    ) -> None:
        if node is None:
            return
        if node.type == "parenthesized_expression":
            child = next(iter(self.children(node)), None)
            self._scan_assignment_target(
                child, owner, function_context, with_scopes,
                compound=compound, assignment_node=assignment_node,
            )
            return
        if node.type in {"identifier", "shorthand_property_identifier_pattern"}:
            if compound:
                self._resolve(node, "value", "read", with_scopes)
            record, _reason = self._resolve(
                node, "value", "write", with_scopes
            )
            if record is not None and not record.binding.mutable:
                self.add_gap("const_reassignment", assignment_node)
            return
        if node.type == "member_expression":
            self._scan(node, owner, function_context, with_scopes)
            return
        if node.type == "subscript_expression":
            self._scan(node, owner, function_context, with_scopes)
            return
        if node.type in {"object_pattern", "array_pattern"}:
            for child in self.children(node):
                self._scan_assignment_target(
                    child, owner, function_context, with_scopes,
                    compound=compound, assignment_node=assignment_node,
                )
            return
        if node.type == "pair_pattern":
            key = node.child_by_field_name("key")
            if key is not None and key.type == "computed_property_name":
                self._scan(key, owner, function_context, with_scopes)
            self._scan_assignment_target(
                node.child_by_field_name("value"),
                owner,
                function_context,
                with_scopes,
                compound=compound,
                assignment_node=assignment_node,
            )
            return
        if node.type in {"assignment_pattern", "object_assignment_pattern"}:
            self._scan_assignment_target(
                node.child_by_field_name("left"),
                owner,
                function_context,
                with_scopes,
                compound=compound,
                assignment_node=assignment_node,
            )
            self._scan(
                node.child_by_field_name("right"),
                owner,
                function_context,
                with_scopes,
            )
            return
        if node.type == "rest_pattern":
            for child in self.children(node):
                self._scan_assignment_target(
                    child, owner, function_context, with_scopes,
                    compound=compound, assignment_node=assignment_node,
                )
            return
        if node.type == "this":
            return
        self._scan(node, owner, function_context, with_scopes)

    def _write_place_root(
        self,
        node: Any | None,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
        *,
        compound: bool,
        assignment_node: Any,
    ) -> None:
        if node is None:
            return
        if node.type == "member_expression":
            self._write_place_root(
                node.child_by_field_name("object"),
                owner,
                function_context,
                with_scopes,
                compound=compound,
                assignment_node=assignment_node,
            )
            return
        if node.type == "subscript_expression":
            self._scan(
                node.child_by_field_name("index"),
                owner,
                function_context,
                with_scopes,
            )
            self._write_place_root(
                node.child_by_field_name("object"),
                owner,
                function_context,
                with_scopes,
                compound=compound,
                assignment_node=assignment_node,
            )
            return
        if node.type == "parenthesized_expression":
            self._write_place_root(
                next(iter(self.children(node)), None),
                owner,
                function_context,
                with_scopes,
                compound=compound,
                assignment_node=assignment_node,
            )
            return
        if node.type == "this":
            return
        if node.type == "identifier":
            self._scan_assignment_target(
                node,
                owner,
                function_context,
                with_scopes,
                compound=compound,
                assignment_node=assignment_node,
            )
            return
        self._scan(node, owner, function_context, with_scopes)

    def _call_arguments(self, node: Any) -> tuple[ByteSpan, ...]:
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            return ()
        return tuple(
            self.span(child)
            for child in self.children(arguments)
            if child.type != "comment"
        )

    def _append_call(self, call: Call) -> None:
        if not any(item.span == call.span for item in self.calls):
            self.calls.append(call)

    def _unwrap_callee(self, node: Any | None) -> Any | None:
        current = node
        while current is not None and current.type in {
            "parenthesized_expression", "instantiation_expression",
        }:
            if current.type == "instantiation_expression":
                type_arguments = current.child_by_field_name("type_arguments")
                self._scan_type(type_arguments)
            children = self.children(current)
            current = next(
                (
                    child for child in children
                    if child.type not in {"type_arguments"}
                ),
                None,
            )
        return current

    def _scan_call(
        self,
        node: Any,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
        *,
        new: bool = False,
        optional: bool = False,
    ) -> None:
        callee_node = (
            node.child_by_field_name("constructor")
            if new
            else node.child_by_field_name("function")
        )
        self._scan_type(node.child_by_field_name("type_arguments"))
        callee = self._unwrap_callee(callee_node)
        args = self._call_arguments(node)
        args_node = node.child_by_field_name("arguments")
        if not new and args_node is not None and args_node.type == "template_string":
            if callee is not None and callee.type == "identifier":
                self._resolve(callee, "value", "call", with_scopes)
            elif callee is not None:
                self._scan(callee, owner, function_context, with_scopes)
            self._scan(args_node, owner, function_context, with_scopes)
            self._append_call(
                Call(self.span(node), (), owner, "", "opaque_tagged")
            )
            return
        if args_node is not None:
            for argument in self.children(args_node):
                self._scan(argument, owner, function_context, with_scopes)
        if callee is None:
            self._append_call(
                Call(self.span(node), args, owner, "", "opaque_expression")
            )
            return
        if callee.type == "member_expression":
            receiver = callee.child_by_field_name("object")
            self._scan(receiver, owner, function_context, with_scopes)
            property_node = callee.child_by_field_name("property")
            member = None
            if property_node is not None and property_node.type in {
                "property_identifier", "private_property_identifier",
            }:
                member = self._resolve_member(
                    receiver,
                    self.text(property_node),
                    node.start_byte,
                )
                if new and member is not None:
                    member = self._merged_constructible(member)
                if member is not None:
                    self.add_reference(property_node, member, "call")
            kind = "opaque_method"
            if optional:
                kind = "opaque_optional"
            elif receiver is not None and receiver.type == "super":
                kind = "opaque_super"
            elif (
                new
                and member is not None
                and member.binding.kind == "ambient"
            ):
                kind = "opaque_ambient"
            elif (
                new
                and member is not None
                and member.binding.kind == "class"
            ):
                kind = "opaque_new"
            elif member is not None and (
                member.binding.kind
                in {"function", "associated_function"}
                or (
                    member.binding.kind == "ambient"
                    and member.function_node is not None
                )
            ):
                info = (
                    self.function_infos.get(member.function_node.id)
                    if member.function_node is not None
                    else None
                )
                if member.body is None or info is None:
                    kind = "opaque_bodyless"
                elif info.is_async:
                    kind = "opaque_async"
                elif info.generator:
                    kind = "opaque_generator"
                elif info.generic:
                    kind = "opaque_generic"
                elif member.member_static:
                    kind = "direct_local"
                else:
                    # Instance methods can dispatch to an override on a
                    # subclass — not a statically direct call.
                    kind = "opaque_virtual"
            target = (
                member.binding.id
                if member is not None
                and kind
                in {
                    "direct_local", "opaque_generic", "opaque_async",
                    "opaque_bodyless", "opaque_virtual",
                    "opaque_generator", "opaque_new", "opaque_ambient",
                }
                else ""
            )
            self._append_call(
                Call(self.span(node), args, owner, target, kind)
            )
            return
        if callee.type == "super":
            self._append_call(
                Call(self.span(node), args, owner, "", "opaque_super")
            )
            return
        if callee.type != "identifier":
            self._scan(callee, owner, function_context, with_scopes)
            self._append_call(
                Call(self.span(node), args, owner, "", "opaque_expression")
            )
            return
        name = self.text(callee)
        if new and name == "Function":
            self.add_gap("dynamic_function", node)
            self.add_unresolved(callee, name, "builtin")
            self._append_call(Call(self.span(node), args, owner, "", "builtin"))
            return
        record, reason = self._resolve(
            callee, "value", "call", with_scopes, constructible=new
        )
        if name == "eval" and not new:
            self.add_gap("dynamic_eval", node)
        if record is None:
            kind = "builtin" if reason == "builtin" else "unresolved"
            self._append_call(Call(self.span(node), args, owner, "", kind))
            return
        if optional:
            self._append_call(
                Call(self.span(node), args, owner, "", "opaque_optional")
            )
            return
        if new:
            if record.binding.kind == "import":
                kind = "opaque_import"
            elif record.binding.kind == "ambient":
                kind = "opaque_ambient"
            elif record.binding.kind == "class":
                kind = "opaque_new"
            else:
                kind = "opaque_expression"
            target = record.binding.id if kind != "opaque_expression" else ""
            self._append_call(Call(self.span(node), args, owner, target, kind))
            return
        if record.binding.kind == "ambient":
            kind = "opaque_ambient"
        elif record.binding.kind == "import":
            kind = "opaque_import"
        elif record.binding.kind == "function":
            info = self.function_infos.get(record.function_node.id) if record.function_node is not None else None
            if record.direct_function and record.body is not None and info is not None:
                if info.is_async:
                    kind = "opaque_async"
                elif info.generator:
                    kind = "opaque_generator"
                elif info.generic:
                    kind = "opaque_value"
                else:
                    kind = "direct_local"
            else:
                kind = "opaque_value"
        else:
            kind = "opaque_value"
        self._append_call(
            Call(self.span(node), args, owner, record.binding.id, kind)
        )

    def _scan_tagged_template(
        self,
        node: Any,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
    ) -> None:
        tag = node.child_by_field_name("tag")
        if tag is not None:
            if tag.type == "identifier":
                self._resolve(tag, "value", "call", with_scopes)
            else:
                self._scan(tag, owner, function_context, with_scopes)
        template = node.child_by_field_name("template")
        self._scan(template, owner, function_context, with_scopes)
        self._append_call(
            Call(self.span(node), (), owner, "", "opaque_tagged")
        )

    def _scan_export(
        self,
        node: Any,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
    ) -> None:
        declaration = node.child_by_field_name("declaration")
        if declaration is not None:
            self._scan(declaration, owner, function_context, with_scopes)
            return
        if re.search(r"\bfrom\b", self.text(node)):
            return
        namespace = "type" if re.match(r"\s*export\s+type\b", self.text(node)) else "value"
        if re.match(r"\s*export\s+(?:default\b|=)", self.text(node)):
            expression = node.child_by_field_name("value")
            if expression is None:
                expression = next(
                    (
                        child
                        for child in self.children(node)
                        if child.type != "export_clause"
                    ),
                    None,
                )
            self._scan(expression, owner, function_context, with_scopes)
            return
        for child in self.walk(node):
            if child.type != "export_specifier":
                continue
            local = child.child_by_field_name("name")
            if local is not None:
                self._resolve(local, namespace, "read", with_scopes)

    def _scan_jsx_tag(
        self,
        name: Any | None,
        with_scopes: tuple[ByteSpan, ...],
    ) -> None:
        if name is None:
            return
        if name.type == "member_expression":
            root = name
            while root.type == "member_expression":
                root = root.child_by_field_name("object")
            if root is not None and root.type == "identifier":
                self._resolve(root, "value", "read", with_scopes)
            return
        if name.type == "identifier":
            text = self.text(name)
            if text and not text[0].islower() and "-" not in text:
                self._resolve(name, "value", "read", with_scopes)

    def _scan(
        self,
        node: Any | None,
        owner: str,
        function_context: Any | None,
        with_scopes: tuple[ByteSpan, ...],
    ) -> None:
        if node is None or node.type == "comment":
            return
        node_type = node.type
        if node_type in _FUNCTION_NODES:
            self._scan_function(node, owner, with_scopes)
            return
        if node_type == "jsx_element":
            for child in self.children(node):
                if child.type != "jsx_closing_element":
                    self._scan(child, owner, function_context, with_scopes)
            return
        if node_type in {"jsx_opening_element", "jsx_self_closing_element"}:
            name = node.child_by_field_name("name")
            self._scan_jsx_tag(name, with_scopes)
            for child in self.children(node):
                if child != name:
                    self._scan(child, owner, function_context, with_scopes)
            return
        if node_type == "jsx_closing_element":
            return
        if node_type in {"class_declaration", "class"}:
            self._scan_class(node, owner, with_scopes)
            return
        if node_type == "interface_declaration":
            self._scan_type(node)
            return
        if node_type == "type_alias_declaration":
            self._scan_type(node.child_by_field_name("type_parameters"))
            self._scan_type(node.child_by_field_name("value"))
            return
        if node_type == "enum_declaration":
            body = node.child_by_field_name("body")
            if body is not None:
                for member in self.children(body):
                    self._scan(member.child_by_field_name("value"), owner, function_context, with_scopes)
            return
        if node_type == "internal_module":
            body = node.child_by_field_name("body")
            self._scan(body, owner, function_context, with_scopes)
            return
        if node_type in {"import_statement", "import_require_clause"}:
            return
        if node_type == "export_statement":
            self._scan_export(node, owner, function_context, with_scopes)
            return
        if node_type == "for_in_statement":
            left = node.child_by_field_name("left")
            kind = node.child_by_field_name("kind")
            if kind is None:
                self._scan_assignment_target(
                    left,
                    owner,
                    function_context,
                    with_scopes,
                    compound=False,
                    assignment_node=node,
                )
            else:
                self._scan_type(node.child_by_field_name("type"))
                self._scan_pattern_defaults(
                    left, owner, function_context, with_scopes
                )
            right = node.child_by_field_name("right")
            if kind is not None and kind.type != "var":
                previous_tdz_binding_ids = self._tdz_binding_ids
                self._tdz_binding_ids = previous_tdz_binding_ids | (
                    self._loop_binding_ids.get(node.id, frozenset())
                )
                try:
                    self._scan(
                        right, owner, function_context, with_scopes
                    )
                finally:
                    self._tdz_binding_ids = previous_tdz_binding_ids
            else:
                self._scan(right, owner, function_context, with_scopes)
            self._scan(
                node.child_by_field_name("body"),
                owner,
                function_context,
                with_scopes,
            )
            return
        if node_type in {"variable_declaration", "lexical_declaration"}:
            self._scan_variable_declaration(
                node, owner, function_context, with_scopes
            )
            return
        if node_type == "with_statement":
            self.add_gap("with_statement", node)
            self._scan(
                node.child_by_field_name("object"),
                owner,
                function_context,
                with_scopes,
            )
            body = node.child_by_field_name("body")
            if body is not None:
                self._scan(
                    body,
                    owner,
                    function_context,
                    (*with_scopes, self.span(body)),
                )
            return
        if node_type == "catch_clause":
            body = node.child_by_field_name("body")
            self._scan(body, owner, function_context, with_scopes)
            return
        if node_type in {"call_expression", "optional_call_expression"}:
            self._scan_call(
                node,
                owner,
                function_context,
                with_scopes,
                optional=node_type == "optional_call_expression"
                or "?." in self.text(node)[: self.text(node).find("(")],
            )
            return
        if node_type == "new_expression":
            self._scan_call(
                node, owner, function_context, with_scopes, new=True
            )
            return
        if node_type == "tagged_template":
            self._scan_tagged_template(node, owner, function_context, with_scopes)
            return
        if node_type in {"assignment_expression", "augmented_assignment_expression"}:
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            compound = node_type == "augmented_assignment_expression"
            self._scan_assignment_target(
                left,
                owner,
                function_context,
                with_scopes,
                compound=compound,
                assignment_node=node,
            )
            self._scan(right, owner, function_context, with_scopes)
            return
        if node_type == "update_expression":
            argument = node.child_by_field_name("argument")
            self._scan_assignment_target(
                argument,
                owner,
                function_context,
                with_scopes,
                compound=True,
                assignment_node=node,
            )
            return
        if node_type == "member_expression":
            object_node = node.child_by_field_name("object")
            self._scan(
                object_node,
                owner,
                function_context,
                with_scopes,
            )
            property_node = node.child_by_field_name("property")
            if property_node is not None and property_node.type == "computed_property_name":
                self._scan(property_node, owner, function_context, with_scopes)
            elif property_node is not None and property_node.type in {
                "property_identifier", "private_property_identifier",
            }:
                member = self._resolve_member(
                    object_node,
                    self.text(property_node),
                    node.start_byte,
                )
                if member is not None:
                    self.add_reference(property_node, member, "read")
            return
        if node_type == "subscript_expression":
            self._scan(node.child_by_field_name("object"), owner, function_context, with_scopes)
            self._scan(node.child_by_field_name("index"), owner, function_context, with_scopes)
            return
        if node_type in {"type_annotation", "return_type"}:
            self._scan_type(node)
            return
        if node_type in {
            "predefined_type", "type_identifier", "generic_type", "union_type",
            "intersection_type", "array_type", "tuple_type", "function_type",
            "object_type", "type_query", "conditional_type", "type_operator",
            "literal_type", "constructor_type", "infer_type", "type_predicate",
        }:
            self._scan_type(node)
            return
        if node_type == "decorator":
            for child in self.children(node):
                self._scan(child, owner, function_context, with_scopes)
            return
        if node_type == "identifier":
            self._resolve(node, "value", "read", with_scopes)
            return
        if node_type == "shorthand_property_identifier":
            self._resolve(node, "value", "read", with_scopes)
            return
        for child in self.children(node):
            self._scan(child, owner, function_context, with_scopes)


def build_ts_bindings(
    source: str, *, tsx: bool = False
) -> LexicalBindingReport:
    try:
        raw = source.encode("utf-8")
    except (AttributeError, UnicodeError):
        raise LexicalReportError("TypeScript source encoding is invalid") from None
    if len(raw) > MAX_SOURCE_BYTES:
        raise LexicalReportError("TypeScript source exceeds the lexical report limit")
    try:
        tree_sitter = importlib.import_module("tree_sitter")
        tree_sitter_typescript = importlib.import_module("tree_sitter_typescript")
        language = (
            tree_sitter_typescript.language_tsx()
            if tsx
            else tree_sitter_typescript.language_typescript()
        )
        parser = tree_sitter.Parser(tree_sitter.Language(language))
        root = parser.parse(raw).root_node
    except RecursionError:
        raise LexicalReportError(
            "TypeScript source nesting exceeds the lexical report limit"
        ) from None
    except Exception as exc:
        raise LexicalReportError("TypeScript source could not be parsed") from exc
    if root.has_error or any(node.is_missing for node in _walk(root)):
        raise LexicalReportError(
            "TypeScript source has parse errors or missing nodes"
        )
    try:
        return _TypeScriptBindings(source, raw, root, tsx=tsx).build()
    except RecursionError:
        raise LexicalReportError(
            "TypeScript source nesting exceeds the lexical report limit"
        ) from None


def _walk(root: Any):
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            continue
        yield node
        stack.extend(
            child
            for child in reversed(node.children)
            if child.type != "comment"
        )


def build_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(
        prog="python -m agent ts-bindings",
        description=(
            "Emit a conservative TypeScript lexical binding report as JSON; "
            "this is lexical metadata, not a type check, proof, or verdict."
        ),
    )
    parser.add_argument("file", type=Path, help="TypeScript source file")
    return parser


def main(args: argparse.Namespace) -> int:
    try:
        source = args.file.read_bytes().decode("utf-8", errors="strict")
        report = build_ts_bindings(
            source, tsx=args.file.suffix.lower() == ".tsx"
        )
        sys.stdout.write(report.to_json())
        return 0
    except OSError:
        print("ts-bindings: could not read source file", file=sys.stderr)
        return 2
    except UnicodeError:
        print("ts-bindings: source file is not valid UTF-8", file=sys.stderr)
        return 2
    except LexicalReportError as exc:
        print(f"ts-bindings: {exc}", file=sys.stderr)
        return 2
