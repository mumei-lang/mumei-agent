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
    # Public names a member is reachable under when they differ from
    # its declared name (`export {A as B}` → {B}, `export {A as B, A}`
    # → {A, B}). Empty means the declared name applies as usual.
    member_public_names: frozenset[str] = frozenset()
    # Names under which the member is reachable on the type side
    # through `export type {…}` alone (value exports union in at
    # lookup). Empty = not type-clause exported.
    member_type_public_names: frozenset[str] = frozenset()
    # Reachable on the type side only (`export type {A}` /
    # `export {type A}`) — no value-side export.
    member_type_exported: bool = False
    # Public names authored by the member's OWN namespace block's
    # `export {…}` clause (aliases and listed names). Sibling blocks
    # may re-export the member under further names through declaration
    # merging, but the clause's own block is the canonical referent for
    # the exported name.
    member_authored_names: frozenset[str] = frozenset()
    member_authored_type_names: frozenset[str] = frozenset()


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


# Which namespace facet a member binding publishes. Member records
# leave `record.namespaces` empty (they are not top-level symbols), so
# the lookup decides the type/value side from the binding kind.
_MEMBER_KIND_NAMESPACES: dict[str, frozenset[str]] = {
    "class": frozenset({"value", "type"}),
    "interface": frozenset({"type"}),
    "enum": frozenset({"value", "type"}),
    "enum_member": frozenset({"value", "type"}),
    "type_alias": frozenset({"type"}),
    "namespace": frozenset({"value", "type"}),
    "ambient": frozenset({"value", "type"}),
    "function": frozenset({"value"}),
    "associated_function": frozenset({"value"}),
    "variable": frozenset({"value"}),
    "parameter": frozenset({"value"}),
}


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
        self._member_lookup_active: set[
            tuple[str, str, bool]
        ] = set()
        self.function_records: dict[int, _Record] = {}
        self._function_node_ids: set[int] = set()
        self._type_alias_cache: dict[str, TypeFact] = {}
        self._loop_binding_ids: dict[int, frozenset[str]] = {}
        self._tdz_binding_ids: frozenset[str] = frozenset()
        self._type_bases: dict[int, list[tuple[str, bool]]] = {}
        self._initializer_active: set[str] = set()
        self._type_node_active: set[int] = set()
        self._narrowed: dict[int, Any] = {}

    def span(self, node: Any) -> ByteSpan:
        return ByteSpan(node.start_byte, node.end_byte)

    def text(self, node: Any | None) -> str:
        return "" if node is None else self.raw[node.start_byte : node.end_byte].decode("utf-8")

    def _export_name(self, node: Any | None) -> str:
        """Export-clause specifier text without surrounding quotes."""
        text = self.text(node).strip()
        if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'":
            return text[1:-1]
        return text

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
        if name_node.type == "string":
            # Quoted member names (`class C { "m"() {} }`) bind under the
            # literal's text without its quotes; escaped names keep the
            # string node so their span stays faithful to the source.
            fragments = self.children(name_node)
            if len(fragments) == 1 and fragments[0].type == "string_fragment":
                name_node = fragments[0]
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
        self._collect_narrowings()
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

    def _new_container_args(
        self, node: Any | None
    ) -> tuple[str, list[Any]] | None:
        """`const m = new Map<K, V>()` — the builtin container's head
        and its type-arg nodes, when `m` carries no annotation. A
        user-declared `class Map`/`Set`/`Array` shadows the builtin,
        so it stays unbound."""
        if node is None or node.type != "identifier":
            return None
        record = self._lookup(self.text(node), node.start_byte, "value")
        if record is None or record.node is None:
            return None
        declarator = record.node.parent
        if (
            declarator is None
            or declarator.type != "variable_declarator"
        ):
            return None
        value = declarator.child_by_field_name("value")
        if value is None or value.type != "new_expression":
            return None
        constructor = value.child_by_field_name("constructor")
        if constructor is None or constructor.type not in {
            "identifier", "type_identifier",
        }:
            return None
        head = self.text(constructor)
        if head not in {"Map", "WeakMap", "Set", "WeakSet", "Array"}:
            return None
        resolved = self._lookup(head, node.start_byte, "type")
        if resolved is not None and resolved.binding.kind not in {
            "import", "ambient",
        }:
            return None
        args_node = value.child_by_field_name("type_arguments")
        return head, (
            list(self.children(args_node))
            if args_node is not None
            else []
        )

    def _iterable_member_args(
        self, operand: Any | None
    ) -> tuple[str, str, list[Any]] | None:
        """`recv.keys()|values()|entries()` on a generic container —
        (member name, container head, container type-arg nodes)."""
        if operand is None or operand.type != "call_expression":
            return None
        callee = operand.child_by_field_name("function")
        if callee is None or callee.type != "member_expression":
            return None
        obj = callee.child_by_field_name("object")
        prop = callee.child_by_field_name("property")
        if obj is None or prop is None:
            return None
        member = self.text(prop)
        if member not in {"keys", "values", "entries"}:
            return None
        declared = self._unwrap_type(
            self._declared_type_node(obj, obj.start_byte)
        )
        if declared is None:
            if self.text(obj) == "Object" and not self._builtin_shadowed(
                obj, member
            ):
                # `Object.entries(obj)` — `obj` is the call's argument;
                # a local `Object` that actually declares `entries`
                # shadows the builtin and keeps this opaque.
                # `Record<K, V>` iterates `[K, V]` pairs like a `Map`.
                args_node = operand.child_by_field_name("arguments")
                arg0 = (
                    next(iter(self.children(args_node)), None)
                    if args_node is not None
                    else None
                )
                record = self._unwrap_type(
                    self._declared_type_node(
                        arg0,
                        arg0.start_byte if arg0 is not None else 0,
                    )
                )
                if record is None or record.type != "generic_type":
                    return None
                kids = self.children(record)
                args = [
                    child
                    for child in kids
                    if child.type == "type_arguments"
                ]
                if (
                    not kids
                    or not args
                    or self.text(kids[0]) != "Record"
                ):
                    return None
                return member, "Map", list(self.children(args[0]))
            constructed = self._new_container_args(obj)
            if constructed is None:
                return None
            return member, constructed[0], constructed[1]
        if declared.type == "array_type":
            elem = next(iter(self.children(declared)), None)
            return (
                member,
                "Array",
                [elem] if elem is not None else [],
            )
        if declared.type != "generic_type":
            return None
        kids = self.children(declared)
        args = [c for c in kids if c.type == "type_arguments"]
        if not kids or not args:
            return None
        return member, self.text(kids[0]), list(self.children(args[0]))

    def _builtin_shadowed(self, obj: Any, member: str) -> bool:
        """A same-named user declaration shadows `Object.values` /
        `Array.from`/`Array.isArray` — a bare `class Object` keeps the
        builtin statics unless it actually declares `member`."""
        record = self._lookup(
            self.text(obj), obj.start_byte, "value"
        )
        if record is None or record.node is None:
            return False
        parent = record.node.parent
        if (
            parent is not None
            and parent.type
            in {
                "class_declaration",
                "abstract_class_declaration",
                "interface_declaration",
                "type_alias_declaration",
            }
            and self._resolve_member(obj, member, obj.start_byte)
            is None
        ):
            return False
        return True

    def _iterable_element_node(self, operand: Any | None) -> Any | None:
        """Element type node of a `for..of` operand — `P[]` peels to
        `P`; `Array<P>`/`Set<P>`/`Iterable<P>` take args[0]."""
        member = self._iterable_member_args(operand)
        if member is not None:
            name, head, arg_nodes = member
            # `m.keys()`/`m.values()` yield scalars; `entries()` yields
            # pairs the pattern path handles. Array keys are `number`
            # — no named type to bind, so stay unbound.
            if head == "Map":
                if name == "keys" and arg_nodes:
                    return arg_nodes[0]
                if name == "values" and len(arg_nodes) > 1:
                    return arg_nodes[1]
                return None
            if head in {"Array", "Set", "Iterable", "ReadonlyArray"}:
                if name == "values" and arg_nodes:
                    return arg_nodes[0]
                if name == "keys" and head == "Set" and arg_nodes:
                    return arg_nodes[0]
                return None
        declared = self._unwrap_type(
            self._declared_type_node(operand, operand.start_byte)
            if operand is not None
            else None
        )
        if declared is None:
            if operand is not None and operand.type == "call_expression":
                # `for (const x of arr.flatMap(f))` — the call's
                # result array peels to its element.
                result = self._array_method_result(operand)
                if result is not None:
                    return self._array_element_node(result)
            constructed = self._new_container_args(operand)
            if (
                constructed is not None
                and constructed[0]
                in {"Set", "WeakSet", "Array"}
                and constructed[1]
            ):
                # `for (const x of new Set<P>())` — the element
                # is the constructor's sole type argument.
                return constructed[1][0]
            return None
        if declared.type == "array_type":
            return next(iter(self.children(declared)), None)
        if declared.type == "generic_type":
            kids = self.children(declared)
            if kids and self.text(kids[0]) in {
                "Array", "Set", "Iterable", "ReadonlyArray",
            }:
                args = [
                    child
                    for child in self.children(declared)
                    if child.type == "type_arguments"
                ]
                if args:
                    return next(iter(self.children(args[0])), None)
        return None

    def _predeclare_for_in(self, node: Any) -> None:
        kind = node.child_by_field_name("kind")
        pattern = node.child_by_field_name("left")
        operand = node.child_by_field_name("right")
        if kind is None or pattern is None:
            # tree-sitter-typescript leaves the loop kind, pattern and
            # operand unfielded — `for (` `<kind>` `<pattern>` `of|in`
            # `<operand>` `)` positionally instead.
            all_children = list(node.children)
            kind = next(
                (
                    child
                    for child in all_children
                    if child.type in {"var", "let", "const"}
                ),
                None,
            )
            op_index = next(
                (
                    index
                    for index, child in enumerate(all_children)
                    if child.type in {"of", "in"}
                ),
                -1,
            )
            if kind is None or op_index < 1:
                return
            if pattern is None and op_index - 1 >= 0:
                pattern = all_children[op_index - 1]
            if (
                operand is None
                and op_index + 1 < len(all_children)
            ):
                operand = all_children[op_index + 1]
        if kind is None or pattern is None:
            return
        element_node = (
            self._iterable_element_node(operand)
            if any(child.type == "of" for child in node.children)
            else None
        )
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
        if type_node is None and element_node is not None and len(names) == 1:
            # `for (const x of arr: P[])` types `x` as the element.
            type_node = element_node
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
        for index, parameter in enumerate(parameter_nodes):
            if parameter.type in {"required_parameter", "optional_parameter"}:
                pattern = parameter.child_by_field_name("pattern")
                type_node = self._pattern_type_node(parameter, pattern)
            elif node.type == "arrow_function":
                pattern = parameter
                type_node = None
            else:
                continue
            if type_node is None:
                type_node = self._callback_param_type_node(node, index)
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
        if node.type == "nested_type_identifier":
            member = self._qualified_type_member(node)
            if member is None:
                return _UNKNOWN
            if member.binding.kind == "type_alias":
                if member.binding.id in visited:
                    return TypeFact(
                        "unknown", text, 0, None, member.binding.id
                    )
                cached = self._type_alias_cache.get(member.binding.id)
                if cached is not None:
                    return cached
                alias_visited = set(visited)
                alias_visited.add(member.binding.id)
                fact = self._type_fact(member.alias_node, alias_visited)
                if fact.kind == "unknown":
                    fact = TypeFact(
                        "unknown", text, 0, None, member.binding.id
                    )
                else:
                    fact = replace(fact, type_id=member.binding.id)
                self._type_alias_cache[member.binding.id] = fact
                return fact
            if member.class_like or member.binding.kind in {
                "class", "interface", "enum", "namespace",
            }:
                return TypeFact(
                    "named",
                    member.binding.name,
                    0,
                    None,
                    member.binding.id,
                )
            return _UNKNOWN
        if node.type in {"type_query", "member_expression"}:
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

    def _lookup_candidates(
        self, name: str, position: int, namespace: str
    ) -> list[_Record]:
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
        candidates.sort(
            key=lambda item: (
                item[0],
                0 if item[1].body is not None else 1,
                -item[1].binding.span.start,
            )
        )
        return [record for _, record in candidates]

    def _lookup(
        self, name: str, position: int, namespace: str
    ) -> _Record | None:
        candidates = self._lookup_candidates(name, position, namespace)
        return candidates[0] if candidates else None

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
                                    (
                                        re.sub(
                                            r"\s+", "", match.group(0)
                                        ),
                                        clause.type == "extends_clause",
                                    )
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
                # Ambient namespaces export every member implicitly,
                # at any depth — unless the body has an `export {…}`
                # clause, which disables the implicit export. The
                # clause is body-wide; collect it once per decl.
                ambient = False
                ancestor = decl.parent
                while ancestor is not None:
                    if ancestor.type == "ambient_declaration":
                        ambient = True
                        break
                    ancestor = ancestor.parent
                export_clause = False
                exported_names: set[str] = set()
                # (exported, local) pairs — a list, not a dict: two
                # specifiers may publish the same exported name
                # (`export {I as Public}; export {M as Public}`), and a
                # dict silently drops one local.
                exported_aliases: list[tuple[str, str]] = []
                exported_type_names: set[str] = set()
                exported_type_aliases: list[tuple[str, str]] = []
                for statement in body.named_children:
                    if statement.type != "export_statement":
                        continue
                    type_only = any(
                        child.type == "type"
                        for child in statement.children
                    )
                    for child in statement.children:
                        if child.type != "export_clause":
                            continue
                        export_clause = True
                        for spec in child.named_children:
                            if spec.type != "export_specifier":
                                continue
                            spec_type_only = type_only or any(
                                part.type == "type"
                                for part in spec.children
                            )
                            local_name = spec.child_by_field_name("name")
                            alias_node = spec.child_by_field_name("alias")
                            if local_name is None:
                                continue
                            local_text = self._export_name(local_name)
                            alias_text = self._export_name(alias_node)
                            if spec_type_only:
                                if alias_node is None:
                                    exported_type_names.add(local_text)
                                else:
                                    exported_type_aliases.append(
                                        (alias_text, local_text)
                                    )
                            elif alias_node is None:
                                exported_names.add(local_text)
                            else:
                                exported_aliases.append(
                                    (alias_text, local_text)
                                )
                if ambient and export_clause:
                    ambient = False
                type_alias_targets = {local for _, local in exported_type_aliases}
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
                    member_node = node
                    if (
                        not boundary
                        and node.parent is not None
                        and node.parent.id == body.id
                        and node.type == "expression_statement"
                    ):
                        # A bare `namespace Inner` / declaration
                        # parses inside an `expression_statement`
                        # wrapper — descend to the declaration
                        # itself when that is all it holds.
                        inner = [
                            child
                            for child in node.named_children
                            if child.type in self._MEMBER_DECLARATIONS
                        ]
                        if len(node.named_children) == 1 and inner:
                            member_node = inner[0]
                    if (
                        not boundary
                        and node.parent is not None
                        and node.parent.id == body.id
                        and member_node.type in self._MEMBER_DECLARATIONS
                    ):
                        other.member_of = decl.id
                        # Namespace members sit on the namespace object —
                        # treat them as static for call-kind selection.
                        other.member_static = True
                        # Only `export`ed members are reachable through
                        # qualified `N.x` access — a block-private
                        # declaration is module-local, like a class's
                        # private member. Ambient namespaces export
                        # every member implicitly, at any depth —
                        # unless the body has an `export {…}` clause,
                        # which disables the implicit export. A member
                        # exported under an alias (`export {A as B}`)
                        # is reachable only through the alias.
                        member_name = self.text(other.node)
                        public_names = {
                            exported
                            for exported, local in exported_aliases
                            if local == member_name
                        }
                        if (
                            node.type == "export_statement"
                            or ambient
                            or member_name in exported_names
                        ):
                            public_names.add(member_name)
                        other.member_authored_names = frozenset(
                            {
                                exported
                                for exported, local in exported_aliases
                                if local == member_name
                            }
                            | (
                                {member_name}
                                if member_name in exported_names
                                else set()
                            )
                        )
                        other.member_visibility = (
                            "public" if public_names else "private"
                        )
                        if public_names and public_names != {member_name}:
                            other.member_public_names = frozenset(
                                public_names
                            )
                        type_names = {
                            exported
                            for exported, local in exported_type_aliases
                            if local == member_name
                        }
                        if member_name in exported_type_names:
                            type_names.add(member_name)
                        if type_names and type_names != {member_name}:
                            other.member_type_public_names = frozenset(
                                type_names
                            )
                        other.member_type_exported = (
                            member_name in exported_type_names
                            or member_name in type_alias_targets
                        )
                        other.member_authored_type_names = frozenset(
                            {
                                exported
                                for exported, local in exported_type_aliases
                                if local == member_name
                            }
                            | (
                                {member_name}
                                if member_name in exported_type_names
                                else set()
                            )
                        )
                        other.member_container = (
                            self._decl_qualified_name(decl)
                        )
                # Declaration merging: this block's `export` clause
                # re-exports members declared in sibling same-named
                # blocks — `namespace N { function f() {} }
                # namespace N { export {f as g} }` publishes `g`.
                sibling_decl_ids = {
                    sibling.node.parent.id
                    for sibling in self._merge_siblings(record)
                    if sibling.binding.kind == "namespace"
                    and sibling.node.parent is not None
                }
                if sibling_decl_ids:
                    for member in self.records:
                        if member.member_of not in sibling_decl_ids:
                            continue
                        member_name = self.text(member.node)
                        added = {
                            exported
                            for exported, local in exported_aliases
                            if local == member_name
                        }
                        if member_name in exported_names:
                            added.add(member_name)
                        if added:
                            names = set(member.member_public_names)
                            if (
                                not names
                                and member.member_visibility == "public"
                            ):
                                names = {member_name}
                            names |= added
                            member.member_visibility = "public"
                            if names != {member_name}:
                                member.member_public_names = frozenset(
                                    names
                                )
                        added_types = {
                            exported
                            for exported, local in exported_type_aliases
                            if local == member_name
                        }
                        if member_name in exported_type_names:
                            added_types.add(member_name)
                        if added_types:
                            type_names = set(
                                member.member_type_public_names
                            )
                            if member.member_type_exported and not type_names:
                                type_names = {member_name}
                            type_names |= added_types
                            member.member_type_exported = True
                            if type_names != {member_name}:
                                member.member_type_public_names = (
                                    frozenset(type_names)
                                )

    def _type_record_by_id(self, binding_id_value: str) -> _Record | None:
        for record in self.records:
            if record.binding.id != binding_id_value:
                continue
            if record.class_like or record.binding.kind == "namespace":
                return record
            # Aliases are transparent for member resolution — `x: T`
            # with `type T = C` types `x` as `C`. Cyclic aliases leave
            # the fact `unknown`, which stays unresolvable.
            if (
                record.binding.kind == "type_alias"
                and record.alias_node is not None
            ):
                fact = self._type_fact(record.alias_node)
                if (
                    fact.kind == "named"
                    and fact.type_id != binding_id_value
                ):
                    return self._type_record_by_id(fact.type_id)
            return None
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

    def _qualified_type_member(self, node: Any) -> _Record | None:
        """Resolve `A.B.C` nested type identifiers to a member record.

        Each segment resolves on the type side: `N.Public` where the
        clause `export {Inner as Public}` authored the spelling is
        reachable, the private `N.Inner` is not."""
        segments: list[str] = []
        current = node
        while current is not None and current.type in {
            "nested_type_identifier",
            "nested_identifier",
        }:
            name_node = current.child_by_field_name(
                "name"
            ) or current.child_by_field_name("property")
            if name_node is not None:
                segments.append(self.text(name_node))
            current = current.child_by_field_name(
                "module"
            ) or current.child_by_field_name("object")
        if current is None or current.type != "identifier":
            return None
        segments.append(self.text(current))
        segments.reverse()
        record = self._lookup(segments[0], node.start_byte, "type")
        if record is None:
            record = self._lookup(segments[0], node.start_byte, "value")
        for segment in segments[1:]:
            if record is None:
                return None
            record = self._member_lookup(
                record,
                segment,
                node.start_byte,
                static=True,
                via_this=False,
                for_type=True,
            )
        return record

    def _member_lookup(
        self,
        type_record: _Record,
        name: str,
        position: int,
        *,
        static: bool,
        via_this: bool,
        for_type: bool = False,
        extra_seed: tuple[_Record, ...] = (),
        collect_extras: list[_Record] | None = None,
        args_node: Any | None = None,
        arg_nodes: list | None = None,
    ) -> _Record | None:
        """BFS over the declaring type and its bases for member `name`.

        `for_type` resolves on the type side (implements and interface
        `extends` spellings), where `export type`-only members are
        reachable; class `extends` is a value position."""
        # Reentrancy guard: base clauses can cycle (`Outer extends
        # Middle`, `Middle extends Outer.Base`), and `_base_type_record`
        # re-enters `_member_lookup` for qualified segments. A cycle
        # cannot name a target — return None.
        active_key = (
            type_record.binding.id, name, for_type
        )
        if active_key in self._member_lookup_active:
            return None
        self._member_lookup_active.add(active_key)
        try:
            return self._member_lookup_inner(
                type_record,
                name,
                position,
                static=static,
                via_this=via_this,
                for_type=for_type,
                extra_seed=extra_seed,
                collect_extras=collect_extras,
                args_node=args_node,
                arg_nodes=arg_nodes,
            )
        finally:
            self._member_lookup_active.discard(active_key)

    def _member_lookup_inner(
        self,
        type_record: _Record,
        name: str,
        position: int,
        *,
        static: bool,
        via_this: bool,
        for_type: bool = False,
        extra_seed: tuple[_Record, ...] = (),
        collect_extras: list[_Record] | None = None,
        args_node: Any | None = None,
        arg_nodes: list | None = None,
    ) -> _Record | None:
        queue: list[tuple[Any, bool]] = [(type_record, False)]
        # Declaration merging: a namespace may merge with a class,
        # interface or enum of the same name in the same container, so
        # the siblings' members merge into a single type. A merged
        # namespace only augments the static side — instance lookups
        # skip it.
        for sibling in self._merge_siblings(type_record):
            if not static and sibling.binding.kind == "namespace":
                continue
            queue.append((sibling, False))
        # Seeded members (alias-collision losers of an earlier path
        # segment) can never win this lookup — they only apply when
        # the primary candidates yield nothing — but their matches
        # still chain into `collect_extras` for deeper segments. The
        # flag travels with the queue entry, so a shared base class
        # keeps the primary side's priority.
        for seed in extra_seed:
            queue.append((seed, True))
            for sibling in self._merge_siblings(seed):
                queue.append((sibling, True))
        visited: set[str] = set()
        seed_ids = {record.binding.id for record, _ in queue}
        matches: list[_Record] = []
        seeded_matches: list[_Record] = []
        while queue:
            current, is_seeded = queue.pop(0)
            if current.binding.id in visited:
                continue
            visited.add(current.binding.id)
            first = current.binding.id in seed_ids
            decl = current.node.parent
            decl_id = None if decl is None else decl.id
            namespace_member = current.binding.kind == "namespace"
            for candidate in self.records:
                if decl_id is None or candidate.member_of != decl_id:
                    continue
                value_names, type_names = self._member_name_sets(candidate)
                if name not in (type_names if for_type else value_names):
                    continue
                member_ns = _MEMBER_KIND_NAMESPACES.get(
                    candidate.binding.kind
                )
                if member_ns is None:
                    member_ns = candidate.namespaces or frozenset(
                        {"value", "type"}
                    )
                if (
                    "type" if for_type else "value"
                ) not in member_ns:
                    # `export {I as Public}` on an interface publishes
                    # the name on the type side only — a value-side
                    # `N.Public.f()` must keep looking for a
                    # value-carrying member (the namespace M).
                    continue
                if (
                    not namespace_member
                    and candidate.binding.kind != "enum_member"
                    and candidate.member_static != static
                ):
                    continue
                if (
                    candidate.member_visibility == "private"
                    and (not via_this or not first)
                    and not (
                        for_type
                        and (
                            name in candidate.member_type_public_names
                            or (
                                not candidate.member_type_public_names
                                and candidate.member_type_exported
                            )
                        )
                    )
                ):
                    continue
                if candidate.member_visibility == "protected" and not via_this:
                    continue
                if is_seeded:
                    seeded_matches.append(candidate)
                else:
                    matches.append(candidate)
            if decl_id is not None and decl is not None:
                for base, base_value in self._type_bases.get(
                    decl_id, ()
                ):
                    # Bases are resolved where the `extends`/`implements`
                    # clause is spelled — a use-site scope may shadow the
                    # base name with an unrelated declaration.
                    base_record = self._base_type_record(
                        base,
                        decl.start_byte,
                        for_type=not base_value,
                    )
                    if base_record is not None:
                        queue.append((base_record, is_seeded))
        if not matches and not seeded_matches:
            return None
        fallback = not matches
        if fallback:
            matches = seeded_matches
        if for_type:
            # A namespace merges with a same-named class/interface/
            # enum in the same container; the merged symbol's type
            # facet is the class-like declaration, so it wins the
            # type-side lookup. Namespace members stay reachable
            # through merge siblings for path segments.
            matches.sort(
                key=lambda candidate: 0
                if candidate.class_like
                or candidate.binding.kind
                in {"class", "interface", "enum", "type_alias"}
                else 1
            )
        if args_node is not None:
            narrowed = self._narrow_overloads(
                matches, args_node, arg_nodes
            )
            # A clause-authored name (`export {f as g}` in one sibling
            # block) pins the referent to that block's declaration —
            # keep it ahead of overload narrowing, which would drop it
            # when its signature does not fit the arguments.
            authored_pre = (
                "member_authored_type_names" if for_type
                else "member_authored_names"
            )
            narrowed_authored = [
                candidate
                for candidate in narrowed
                if name in getattr(candidate, authored_pre)
            ]
            if narrowed_authored:
                matches = narrowed_authored
            else:
                original_authored = [
                    candidate
                    for candidate in matches
                    if name in getattr(candidate, authored_pre)
                ]
                if original_authored:
                    matches = original_authored
                else:
                    matches = narrowed
        # When sibling `namespace` blocks re-export each other's members
        # (`namespace N { export {f as g} }` publishes the merged `f`),
        # prefer the member whose own block authored the looked-up name —
        # it is the referent the clause itself points at.
        # Exported-name collisions: when several members share the
        # looked-up name (duplicate `export {... as Public}` — a tsc
        # error, but still indexed), the losers are reported to the
        # caller via `collect_extras` so a qualified path can keep
        # descending (`N.Public.B` reaches the namespace's `B` even
        # when the interface won the `Public` segment). Only path
        # lookups chain them — a direct `N.I` spelling must never
        # reach `M`'s members.
        authored = (
            "member_authored_type_names" if for_type
            else "member_authored_names"
        )
        for candidate in matches:
            if name in getattr(candidate, authored):
                if collect_extras is not None:
                    collect_extras.extend(
                        m for m in matches if m is not candidate
                    )
                    if not fallback:
                        collect_extras.extend(seeded_matches)
                return candidate
        if collect_extras is not None:
            collect_extras.extend(matches[1:])
            if not fallback:
                collect_extras.extend(seeded_matches)
        return matches[0]

    def _narrow_overloads(
        self,
        matches: list[_Record],
        args_node: Any,
        arg_nodes: list | None = None,
        type_args: list[str] | None = None,
    ) -> list[_Record]:
        """Pick the first overload whose signature the arguments fit.

        Mirrors tsc's first-matching-signature rule over arity and
        literal/identifier argument kinds. A `...arg` spread expands
        when its operand's declared type is a tuple; other spreads or
        fewer than two signature-shaped candidates leave the list
        untouched. `type_args` carries the call's explicit type
        arguments so constraints disqualify an overload and defaults
        inform the value-argument matching. When nothing fits, the
        original match order is kept so the reference still lands on
        a same-named member."""
        args = (
            arg_nodes
            if arg_nodes is not None
            else [
                child
                for child in self.children(args_node)
                if child.type != "comment"
            ]
        )
        specs: list[tuple[Any | None, str | None, int]] = []
        for arg in args:
            if arg.type == "spread_element":
                expanded = self._spread_arg_specs(arg)
                if expanded is None:
                    return matches
                specs.extend(expanded)
            else:
                specs.append(
                    (arg, self._arg_kind(arg), arg.start_byte)
                )
        if matches and matches[0].function_node is None:
            # A same-named property/const member overrides everything
            # behind it — narrowing must not cross the nearest
            # declaration to reach a base type's method.
            return matches
        owner_ids = {matches[0].member_of}
        owner_pos = {}
        # Declaration merging splits one entity's members across
        # several blocks; signatures on merge siblings of the nearest
        # declaring block are overloads of the same member, not
        # overrides hidden behind it.
        owner_record = next(
            (
                record
                for record in self.records
                if record.node is not None
                and record.node.parent is not None
                and record.node.parent.id == matches[0].member_of
            ),
            None,
        )
        if owner_record is not None:
            owner_pos[owner_record.node.parent.id] = (
                owner_record.node.parent.start_byte
            )
            for sibling in self._merge_siblings(owner_record):
                if (
                    sibling.node is not None
                    and sibling.node.parent is not None
                ):
                    decl = sibling.node.parent
                    owner_ids.add(decl.id)
                    owner_pos[decl.id] = decl.start_byte
        signatures = [
            candidate
            for candidate in matches
            if candidate.function_node is not None
            and candidate.member_of in owner_ids
        ]
        if len(signatures) < 2:
            return matches

        bindings_map: dict[str, dict[str, str] | None] = {}
        if type_args is not None:
            bindings_map = {
                candidate.binding.id: self._type_arg_bindings(
                    candidate, type_args, args_node.start_byte
                )
                for candidate in signatures
            }
            eligible = [
                candidate
                for candidate in signatures
                if bindings_map[candidate.binding.id] is not None
            ]
            if eligible:
                # An explicit type argument that breaks a constraint
                # (`f<number>` against `f<T extends string>`)
                # disqualifies that overload entirely.
                signatures = eligible

        remaining = [
            candidate
            for candidate in signatures
            if self._arity_accepts(candidate, len(specs))
        ]
        if not remaining:
            return matches
        proven = len(remaining) < len(signatures)
        for index, (arg, kind, position) in enumerate(specs):
            if kind is None:
                continue
            filtered = [
                candidate
                for candidate in remaining
                if self._param_accepts(
                    candidate,
                    index,
                    arg,
                    kind,
                    position,
                    bindings=bindings_map.get(candidate.binding.id),
                )
            ]
            if filtered:
                remaining = filtered
                proven = True
        if not remaining or not proven:
            return matches
        # tsc's first-matching-signature rule: the earliest declaration
        # that fits the arguments wins, not the lookup's latest-first
        # order. Literal-typed parameters matching the argument's
        # literal outrank wider annotations (`m(x: "s")` beats
        # `m(x: string)` for `m("s")`). For merged declarations,
        # signatures of a LATER block precede earlier blocks'
        # signatures; inside one block they keep declaration order.
        # Non-signature matches (properties, clause aliases) lose to a
        # signature the call actually fits.
        literal_match = {
            candidate.binding.id: any(
                self._param_literal_match(candidate, index, arg, kind)
                for index, (arg, kind, position) in enumerate(specs)
            )
            for candidate in remaining
        }
        remaining.sort(
            key=lambda candidate: (
                not literal_match[candidate.binding.id],
                -owner_pos.get(candidate.member_of, 0),
                candidate.binding.span.start,
            )
        )
        return remaining

    def _param_annotation_node(
        self, candidate: _Record, index: int
    ) -> Any | None:
        """Inner annotation node of the candidate's parameter at
        `index`, unwrapping the element type of a rest parameter."""
        params = (
            candidate.function_node.child_by_field_name("parameters")
            if candidate.function_node is not None
            else None
        )
        if params is None:
            return None
        items = self._param_items(params)
        if index >= len(items):
            tail = items[-1] if items else None
            annotation = (
                tail.child_by_field_name("type") if tail is not None else None
            )
            if annotation is None:
                return None
            return self._rest_element_node(
                next(iter(self.children(annotation)), None)
            )
        item = items[index]
        annotation = item.child_by_field_name("type")
        if annotation is None:
            return None
        inner = next(iter(self.children(annotation)), None)
        pattern = item.child_by_field_name("pattern")
        if (
            pattern is not None
            and self.text(pattern).lstrip().startswith("...")
        ):
            inner = self._rest_element_node(inner)
        return inner

    def _param_literal_match(
        self,
        candidate: _Record,
        index: int,
        arg: Any | None,
        kind: str | None = None,
    ) -> bool:
        """The parameter's annotation is a literal type spelled exactly
        like the argument — `m(x: "s")` vs argument `"s"`. A spread
        element expanded from a tuple annotation carries no argument
        node and is read through `kind` instead."""
        annotation = self._param_annotation_node(candidate, index)
        if annotation is None or annotation.type != "literal_type":
            return False
        inner = next(
            (
                child
                for child in self.children(annotation)
                if child.type != "comment"
            ),
            None,
        )
        actual = self.text(arg) if arg is not None else kind
        return (
            inner is not None
            and actual is not None
            and self._literal_equal(self.text(inner), actual)
        )

    @staticmethod
    def _literal_equal(declared: str, actual: str) -> bool:
        """Literal spellings carrying the same value — `'s'` fits
        `x: "s"`, `0x1` fits `x: 1`, and an uninterpolated `` `s` ``
        fits `x: "s"`. A quoted literal never equals a bare token
        (`"true"` does not fit `x: true` arguments or a `Widget`
        type), and a backtick string containing `${` is a computed
        template, not a constant."""
        if declared == actual:
            return True
        nonconstant = object()

        def quoted(spelling: str) -> bool:
            return (
                len(spelling) >= 2
                and spelling[0] in "\"'`"
                and spelling.endswith(spelling[0])
            )

        def value(spelling: str) -> object:
            if quoted(spelling):
                inner = spelling[1:-1]
                # `${` starts interpolation unless an odd run of
                # backslashes precedes it — `\${` is literal text but
                # `\\${` (escaped backslash) still interpolates.
                if spelling[0] == "`":
                    pos = 0
                    while True:
                        idx = inner.find("${", pos)
                        if idx == -1:
                            break
                        backslashes = 0
                        j = idx - 1
                        while j >= 0 and inner[j] == "\\":
                            backslashes += 1
                            j -= 1
                        if backslashes % 2 == 0:
                            return nonconstant
                        pos = idx + 2
                return inner.replace("\\$", "$")
            cleaned = spelling.replace("_", "")
            if len(cleaned) > 1 and cleaned.endswith("n"):
                # `1_000n` and `1000n` spell the same bigint — the
                # `n` tag keeps `1n` distinct from `1`.
                try:
                    return ("bigint", int(cleaned[:-1], 0))
                except ValueError:
                    return spelling
            try:
                return int(cleaned, 0)
            except ValueError:
                pass
            try:
                return float(cleaned)
            except ValueError:
                return spelling

        if quoted(declared) != quoted(actual):
            return False
        declared_value, actual_value = value(declared), value(actual)
        if declared_value is nonconstant or actual_value is nonconstant:
            return False
        if isinstance(declared_value, str) or isinstance(
            actual_value, str
        ):
            return isinstance(declared_value, str) and isinstance(
                actual_value, str
            ) and declared_value == actual_value
        return declared_value == actual_value

    def _arity_accepts(self, candidate: _Record, arg_count: int) -> bool:
        params = (
            candidate.function_node.child_by_field_name("parameters")
            if candidate.function_node is not None
            else None
        )
        if params is None:
            return arg_count == 0
        required = 0
        total = 0
        variadic = False
        for item in self._param_items(params):
            pattern = item.child_by_field_name("pattern")
            if pattern is not None and self.text(
                pattern
            ).lstrip().startswith("..."):
                variadic = True
                continue
            total += 1
            if item.type == "required_parameter":
                required += 1
        if arg_count < required:
            return False
        return variadic or arg_count <= total

    def _param_items(self, params: Any) -> list[Any]:
        """Parameter nodes that consume real arguments — `this:`
        parameters type the receiver only and take no argument."""
        items = []
        for item in self.children(params):
            if item.type not in {"required_parameter", "optional_parameter"}:
                continue
            pattern = item.child_by_field_name("pattern")
            if pattern is not None and self.text(pattern).strip() == "this":
                continue
            items.append(item)
        return items

    def _call_type_args_node(self, node: Any) -> Any | None:
        """The `type_arguments` node a call carries — `f<T, U>(...)`,
        also nested in parentheses or an instantiation expression
        (`(f<T, U>)(...)`); None when the call supplies none."""
        type_args = node.child_by_field_name("type_arguments")
        callee = node.child_by_field_name("function")
        while callee is not None and callee.type in {
            "parenthesized_expression",
            "instantiation_expression",
        }:
            inner = next(
                (
                    child
                    for child in self.children(callee)
                    if child.type == "type_arguments"
                ),
                None,
            )
            if inner is not None:
                type_args = inner
            callee = next(
                (
                    child
                    for child in self.children(callee)
                    if child.type != "type_arguments"
                ),
                None,
            )
        return type_args

    def _call_type_args_count(self, node: Any) -> int | None:
        """Explicit type-argument count on a call — `f<T, U>(...)`."""
        type_args = self._call_type_args_node(node)
        if type_args is None:
            return None
        return len(self.children(type_args))

    def _type_param_count(self, record: _Record) -> int:
        """Type parameters a signature declares — `f<T, U>` is 2,
        a non-generic signature 0."""
        function_node = record.function_node
        if function_node is None:
            return 0
        parameters = function_node.child_by_field_name(
            "type_parameters"
        )
        if parameters is None:
            return 0
        return sum(
            1
            for child in self.children(parameters)
            if child.type in {"type_parameter", "required_type_parameter"}
        )

    def _required_type_param_count(self, record: _Record) -> int:
        """Type parameters without defaults — explicit type arguments
        must supply at least this many, so `f<T, U = string>` accepts
        `f<A>(...)` while `f<T, U>` does not."""
        function_node = record.function_node
        if function_node is None:
            return 0
        parameters = function_node.child_by_field_name(
            "type_parameters"
        )
        if parameters is None:
            return 0
        return sum(
            1
            for child in self.children(parameters)
            if child.type == "required_type_parameter"
            or (
                child.type == "type_parameter"
                and child.child_by_field_name("value") is None
            )
        )

    def _type_param_specs(
        self, record: _Record
    ) -> list[tuple[str | None, Any | None, Any | None]]:
        """(name, constraint inner node, default inner node) per
        declared type parameter — `f<T extends string, U = number>`
        reads `[("T", string-node, None), ("U", None, number-node)]`."""
        function_node = record.function_node
        if function_node is None:
            return []
        parameters = function_node.child_by_field_name(
            "type_parameters"
        )
        if parameters is None:
            return []
        specs = []
        for child in self.children(parameters):
            if child.type not in {
                "type_parameter",
                "required_type_parameter",
            }:
                continue
            name_node = child.child_by_field_name("name")
            name = (
                None
                if name_node is None
                else self.text(name_node).strip()
            )
            constraint = child.child_by_field_name("constraint")
            constraint_inner = (
                next(
                    (
                        inner
                        for inner in self.children(constraint)
                        if self.text(inner) != "extends"
                    ),
                    None,
                )
                if constraint is not None
                else None
            )
            default = child.child_by_field_name("value")
            default_inner = (
                next(
                    (
                        inner
                        for inner in self.children(default)
                        if self.text(inner) != "="
                    ),
                    None,
                )
                if default is not None
                else None
            )
            specs.append((name, constraint_inner, default_inner))
        return specs

    def _literal_primitive_kind(self, text: str) -> str | None:
        """Primitive kind a literal type argument spells —
        `"s"`/`3`/`true`/`1n` — or None for non-literals."""
        text = text.strip()
        if not text:
            return None
        if text[0] in "\"'`":
            return "string"
        if text in {"true", "false"}:
            return "boolean"
        cleaned = text.replace("_", "")
        if cleaned.endswith("n"):
            cleaned = cleaned[:-1]
            if cleaned and all(c in "0123456789abcdefxobABCDEFXOB." for c in cleaned):
                return "bigint"
            return None
        if cleaned and all(
            c in "0123456789abcdefxobABCDEFXOB.eE+-" for c in cleaned
        ) and any(c.isdigit() for c in cleaned):
            return "number"
        return None

    def _bound_type_satisfies(
        self, bound: str, constraint_inner: Any, position: int
    ) -> bool:
        """Whether an explicit type argument can stand in for the
        parameter's `extends` constraint. Literal spellings satisfy
        both literal-typed and primitive-typed constraints."""
        if self._annotation_accepts(constraint_inner, None, bound, position):
            return True
        primitive = self._literal_primitive_kind(bound)
        return primitive is not None and self._annotation_accepts(
            constraint_inner, None, primitive, position
        )

    def _bound_type_accepts(
        self, bound: str, arg: Any | None, kind: str, position: int
    ) -> bool:
        """Whether a parameter annotated `T` accepts `kind` when `T`
        is bound to `bound` by explicit type arguments (or a
        default). Unresolvable bound names accept — the bindings stay
        honest rather than guessing."""
        bound = bound.strip()
        if bound in {"any", "unknown", "object"}:
            return True
        if bound in {"number", "string", "boolean", "bigint", "symbol"}:
            return kind == bound
        if self._literal_primitive_kind(bound) is not None:
            actual = (
                self.text(arg)
                if arg is not None
                and arg.type
                in {"string", "number", "template_string", "true", "false"}
                else kind
            )
            return self._literal_equal(bound, actual)
        if " | " in bound:
            return any(
                self._bound_type_accepts(part, arg, kind, position)
                for part in bound.split(" | ")
            )
        if self._lookup(bound, position, "type") is None:
            return True
        return kind == bound or self._type_derives_from(
            kind, bound, position, position
        )

    def _type_arg_bindings(
        self, candidate: _Record, type_args: list[str], position: int
    ) -> dict[str, str] | None:
        """Type-parameter bindings `f<A, B>` gives a candidate —
        supplied arguments plus defaults. None when a supplied
        argument verifiably violates the parameter's constraint, so
        that overload cannot be the callee."""
        specs = self._type_param_specs(candidate)
        if not specs:
            return {}
        bindings: dict[str, str] = {}
        for index, (name, constraint_inner, default_inner) in enumerate(
            specs
        ):
            if index < len(type_args):
                bound = type_args[index].strip()
                if (
                    constraint_inner is not None
                    and self._verifiable_type_text(bound, position)
                    and not self._bound_type_satisfies(
                        bound, constraint_inner, position
                    )
                ):
                    return None
            elif default_inner is not None:
                bound = self.text(default_inner).strip()
            else:
                return None
            if name is not None:
                bindings[name] = bound
        # A default can name an earlier parameter (`U = T`) — resolve
        # one hop so it reads the same concrete type.
        for name, bound in bindings.items():
            bindings[name] = bindings.get(bound, bound)
        return bindings

    def _verifiable_type_text(self, text: str, position: int) -> bool:
        """Whether a type-argument spelling is concrete enough to
        check — primitives, literals, or a resolvable named type.
        An outer generic like `T` cannot be judged here."""
        text = text.strip()
        if text in {"any", "unknown", "object", "number", "string",
                    "boolean", "bigint", "symbol"}:
            return True
        if self._literal_primitive_kind(text) is not None:
            return True
        record = self._lookup(text, position, "type")
        # A generic parameter's concrete type is unknowable here —
        # it cannot be judged against the constraint either way.
        return (
            record is not None
            and record.binding.kind != "generic_parameter"
        )

    def _arg_kind(self, arg: Any) -> str | None:
        """Primitive kind of a literal, or the declared name for
        identifiers — `None` when the argument type is not pinned."""
        if arg.type == "number":
            # `1n`/`0xfn` literals are bigint — a hex digit is never
            # `n`, so the suffix is unambiguous.
            return (
                "bigint"
                if self.text(arg).strip().endswith("n")
                else "number"
            )
        if arg.type in {"string", "template_string"}:
            return "string"
        if arg.type in {"true", "false"}:
            return "boolean"
        if arg.type == "identifier":
            record = self._lookup(
                self.text(arg), arg.start_byte, "value"
            )
            if record is None or record.type_node is None:
                return None
            fact = self._type_fact(
                next(iter(self.children(record.type_node)), None)
            )
            if fact.kind != "named":
                return None
            type_record = self._type_record_by_id(fact.type_id)
            return None if type_record is None else type_record.binding.name
        if arg.type == "new_expression":
            constructor = arg.child_by_field_name("constructor")
            if constructor is not None and constructor.type == "identifier":
                return self.text(constructor)
        return None

    def _spread_arg_specs(
        self, arg: Any
    ) -> list[tuple[Any | None, str | None, int]] | None:
        """(arg_node, kind, position) triples a `...expr` expands to
        when `expr`'s declared type is a tuple — `f(...t)` with
        `t: [number, string]` supplies two arguments. None when the
        operand's arity cannot be pinned (array types, unresolved or
        non-identifier operands), so the caller keeps the overloads
        untouched."""
        operand = next(
            (
                child
                for child in self.children(arg)
                if child.type != "comment"
            ),
            None,
        )
        if operand is None or operand.type != "identifier":
            return None
        record = self._lookup(
            self.text(operand), operand.start_byte, "value"
        )
        if record is None or record.type_node is None:
            return None
        inner = next(iter(self.children(record.type_node)), None)
        elements = self._tuple_element_nodes(inner)
        if elements is None:
            return None
        return [
            (None, self._type_node_kind(element), arg.start_byte)
            for element in elements
        ]

    def _tuple_element_nodes(self, node: Any | None) -> list | None:
        """Element type nodes of a `tuple_type`, following one
        `type_alias` hop — `type Pair = [number, string]` exposes the
        same elements as the spelled tuple."""
        if node is None:
            return None
        if node.type == "tuple_type":
            return [
                child
                for child in self.children(node)
                if child.type != "comment"
            ]
        if node.type == "type_identifier":
            record = self._lookup(
                self.text(node).strip(), node.start_byte, "type"
            )
            if (
                record is not None
                and record.binding.kind == "type_alias"
                and record.alias_node is not None
            ):
                inner = next(iter(self.children(record.alias_node)), None)
                if inner is not None and inner.type == "tuple_type":
                    return [
                        child
                        for child in self.children(inner)
                        if child.type != "comment"
                    ]
        return None

    def _type_node_kind(self, node: Any | None) -> str | None:
        """Kind a tuple element type contributes to a spread call —
        primitives and named types by spelling, literals by their
        spelled text so literal-typed parameters still compare."""
        if node is None:
            return None
        if node.type == "literal_type":
            inner = next(
                (
                    child
                    for child in self.children(node)
                    if child.type != "comment"
                ),
                None,
            )
            return None if inner is None else self.text(inner)
        text = self.text(node).strip()
        return text or None

    def _param_accepts(
        self,
        candidate: _Record,
        index: int,
        arg: Any,
        kind: str,
        position: int,
        bindings: dict[str, str] | None = None,
    ) -> bool:
        params = (
            candidate.function_node.child_by_field_name("parameters")
            if candidate.function_node is not None
            else None
        )
        if params is None:
            return False
        items = self._param_items(params)
        if index >= len(items):
            # Past the declared list: only a rest tail accepts more.
            tail = items[-1] if items else None
            pattern = (
                tail.child_by_field_name("pattern")
                if tail is not None
                else None
            )
            if not (
                pattern is not None
                and self.text(pattern).lstrip().startswith("...")
            ):
                return False
            annotation = tail.child_by_field_name("type")
            if annotation is None:
                return True
            return self._annotation_accepts(
                self._rest_element_node(
                    next(iter(self.children(annotation)), None)
                ),
                arg,
                kind,
                position,
                bindings,
            )
        item = items[index]
        pattern = item.child_by_field_name("pattern")
        variadic = (
            pattern is not None
            and self.text(pattern).lstrip().startswith("...")
        )
        annotation = item.child_by_field_name("type")
        if annotation is None:
            return True
        inner = next(iter(self.children(annotation)), None)
        if variadic:
            inner = self._rest_element_node(inner)
        return self._annotation_accepts(inner, arg, kind, position, bindings)

    def _rest_element_node(self, node: Any | None) -> Any | None:
        """Element annotation of a rest parameter — `...x: T[]` and
        `...x: Array<T>` are compared against `T`, not the array."""
        if node is None:
            return None
        if node.type == "array_type":
            return next(iter(self.children(node)), node)
        if node.type == "generic_type":
            args = node.child_by_field_name("type_arguments")
            if args is not None:
                return next(iter(self.children(args)), node)
        return node


    def _annotation_accepts(
        self,
        node: Any | None,
        arg: Any | None,
        kind: str,
        position: int,
        bindings: dict[str, str] | None = None,
    ) -> bool:
        """Whether the parameter annotation can hold `kind`.

        `kind` is a primitive name or a named type's spelling. Missing
        or unknown annotations accept — only spelled contradictions
        eliminate a candidate. `bindings` maps the candidate's type
        parameters to the explicit type arguments (and defaults) a
        call supplied, so `x: T` checks against the bound type."""
        if node is None:
            return True
        if node.type == "union_type":
            return any(
                self._annotation_accepts(
                    child, arg, kind, position, bindings
                )
                for child in self.children(node)
                if child.type != "|"
            )
        if node.type == "literal_type":
            inner = next(
                (
                    child
                    for child in self.children(node)
                    if child.type != "comment"
                ),
                None,
            )
            if inner is None:
                return True
            # A literal annotation accepts only the same literal —
            # `m(x: "s")` rejects `"t"` and `v: string`. Identifiers
            # accept when their declared type spells the literal.
            literal_text = self.text(inner)
            if arg is not None and arg.type in {
                "string",
                "number",
                "template_string",
                "true",
                "false",
            }:
                return self._literal_equal(literal_text, self.text(arg))
            return self._literal_equal(literal_text, kind)
        text = self.text(node).strip()
        if text in {"any", "unknown", "object"}:
            return True
        if text in {"number", "string", "boolean", "bigint", "symbol"}:
            return kind == text
        if node.type == "type_identifier":
            if bindings is not None and text in bindings:
                return self._bound_type_accepts(
                    bindings[text], arg, kind, position
                )
            record = self._lookup(text, node.start_byte, "type")
            if record is not None and record.binding.kind == "type_alias":
                inner = (
                    next(iter(self.children(record.alias_node)), None)
                    if record.alias_node is not None
                    else None
                )
                return self._annotation_accepts(
                    inner, arg, kind, position, bindings
                )
            if (
                record is not None
                and record.binding.kind == "generic_parameter"
            ):
                # `T` accepts whatever its `extends` constraint
                # accepts; an unconstrained parameter accepts
                # anything the caller binds to it.
                owner = record.node.parent if record.node is not None else None
                constraint = (
                    owner.child_by_field_name("constraint")
                    if owner is not None and owner.type == "type_parameter"
                    else None
                )
                if constraint is None:
                    return True
                inner = next(
                    (
                        child
                        for child in self.children(constraint)
                        if child.type != "extends"
                    ),
                    None,
                )
                return self._annotation_accepts(
                    inner, arg, kind, position, bindings
                )
            return text == kind or self._type_derives_from(
                kind, text, position, node.start_byte
            )
        if node.type == "generic_type":
            return text == kind or self._type_derives_from(
                kind, text, position, node.start_byte
            )
        return True

    def _type_derives_from(
        self, name: str, ancestor: str, arg_position: int, decl_position: int
    ) -> bool:
        """True when type `name` transitively extends/implements
        `ancestor` — `new Derived()` fits a `Base` parameter when
        `class Derived extends Base`. The argument's type resolves where
        the argument is spelled; the annotation's name resolves at its
        own site so `D extends N.Base` is not confused with a global
        `Base`."""
        first = self._lookup(name, arg_position, "type")
        ancestor_record = self._base_type_record(ancestor, decl_position)
        if first is None or ancestor_record is None:
            return False
        seen: set[int] = set()
        queue = [first]
        while queue:
            record = queue.pop()
            if record.binding.id == ancestor_record.binding.id:
                return True
            decl = record.node.parent if record.node is not None else None
            if decl is None or decl.id in seen:
                continue
            seen.add(decl.id)
            for base, base_value in self._type_bases.get(decl.id, ()):
                base_record = self._base_type_record(
                    base,
                    decl.start_byte,
                    for_type=not base_value,
                )
                if base_record is not None:
                    queue.append(base_record)
        return False


    def _member_name_sets(
        self, candidate: _Record
    ) -> tuple[frozenset[str], frozenset[str]]:
        """(value names, type names) a namespace member answers to.

        Explicit export lists publish a member only under the listed
        names — `export type {A as B}` removes `N.A` entirely. An inline
        `export` (or implicit ambient export) keeps the declared name
        alongside any clause aliases — `export class A` +
        `export type {A as B}` still answers `N.A`."""
        if candidate.member_public_names or candidate.member_type_public_names:
            declared = candidate.binding.name
            value_names = set(candidate.member_public_names)
            if candidate.member_visibility == "public" and (
                not value_names or declared in value_names
            ):
                value_names.add(declared)
            type_names = set(candidate.member_type_public_names)
            if (
                candidate.class_like
                or candidate.binding.kind == "namespace"
            ):
                # A namespace answers its public spellings on the type
                # side too — it is a qualified-path segment (`N.B.T`),
                # never a terminal type itself.
                type_names |= value_names
            if (
                candidate.member_type_exported
                and (
                    not candidate.member_type_public_names
                    or declared in candidate.member_type_public_names
                )
            ) or (
                candidate.member_visibility == "public"
                and not candidate.member_public_names
            ):
                type_names.add(declared)
            return frozenset(value_names), frozenset(type_names)
        declared_names = frozenset({candidate.binding.name})
        return declared_names, declared_names

    def _base_type_record(
        self, base: str, position: int, *, for_type: bool = True
    ) -> _Record | None:
        """Resolve an extends/implements spelling, incl. `N.Base` chains.

        `for_type` is False for class `extends` — a value position
        where type-only exports do not apply."""
        segments = [segment.strip() for segment in base.split(".")]
        record = self._lookup(segments[0], position, "type")
        if record is None:
            record = self._lookup(segments[0], position, "value")
        extras: list[_Record] = []
        for segment in segments[1:]:
            if record is None:
                return None
            next_extras: list[_Record] = []
            record = self._member_lookup(
                record,
                segment,
                position,
                static=True,
                via_this=False,
                for_type=for_type,
                extra_seed=tuple(extras),
                collect_extras=next_extras,
            )
            extras = next_extras
        return record

    def _array_element_node(self, declared: Any) -> Any | None:
        """Element type node of an `array_type`/`Array<T>` node."""
        if declared.type == "array_type":
            return next(iter(self.children(declared)), None)
        if declared.type == "generic_type":
            kids = self.children(declared)
            if kids and self.text(kids[0]) in {
                "Array",
                "ReadonlyArray",
            }:
                args = [
                    child
                    for child in kids
                    if child.type == "type_arguments"
                ]
                if args:
                    return next(iter(self.children(args[0])), None)
        return None

    def _callback_param_type_node(
        self, fn_node: Any, index: int
    ) -> Any | None:
        """Type node a callback parameter takes from the receiver's
        element type — `arr.forEach(p => ...)`, `m.forEach((v, k)
        => ...)`, `arr.filter/find/map/some/every/flatMap/sort/reduce`.
        Only std array/Map receivers spell one; declared member
        signatures keep their own annotation."""
        parent = fn_node.parent
        if parent is None or parent.type != "arguments":
            return None
        call = parent.parent
        if call is None or call.type != "call_expression":
            return None
        callee = call.child_by_field_name("function")
        if callee is None or callee.type != "member_expression":
            return None
        obj = callee.child_by_field_name("object")
        prop = callee.child_by_field_name("property")
        if obj is None or prop is None:
            return None
        member = self.text(prop)
        declared = self._unwrap_type(
            self._declared_type_node(obj, obj.start_byte)
        )
        if declared is None:
            return None
        if member == "forEach" and declared.type == "generic_type":
            kids = self.children(declared)
            if kids and self.text(kids[0]) in {"Map", "WeakMap"}:
                args = [
                    child
                    for child in kids
                    if child.type == "type_arguments"
                ]
                if args:
                    # `Map<K, V>.forEach((value, key) => ...)`.
                    elems = self.children(args[0])
                    slot = {0: 1, 1: 0}.get(index)
                    return (
                        elems[slot]
                        if slot is not None and slot < len(elems)
                        else None
                    )
        if member not in {
            "every",
            "filter",
            "find",
            "findIndex",
            "findLast",
            "flatMap",
            "forEach",
            "map",
            "some",
            "sort",
            "reduce",
        }:
            return None
        if member == "sort":
            if index > 1:
                return None
        elif member == "reduce":
            # `reduce((acc, cur) => ...)` — only `cur` is `T`.
            if index != 1:
                return None
        elif index != 0:
            return None
        return self._array_element_node(declared)

    def _is_arrayish(self, node: Any) -> bool:
        if node.type == "array_type":
            return True
        return (
            node.type == "generic_type"
            and bool(self.children(node))
            and self.text(self.children(node)[0])
            in {"Array", "ReadonlyArray"}
        )

    def _callback_array_return(
        self, node: Any, receiver_elem: Any
    ) -> Any | None:
        """Array type node an array-method callback returns — a
        named function's return annotation, an arrow's annotated
        return or body, or the identity `r => r` shorthand (the
        receiver's own element)."""
        args_node = node.child_by_field_name("arguments")
        callback = (
            next(iter(self.children(args_node)), None)
            if args_node is not None
            else None
        )
        if callback is None:
            return None
        if callback.type == "identifier":
            record = self._lookup(
                self.text(callback), node.start_byte, "value"
            )
            if record is None or record.function_node is None:
                return None
            return_node = record.function_node.child_by_field_name(
                "return_type"
            )
            if return_node is None:
                for child in self.children(record.function_node):
                    if child.type in {"type_annotation", "return_type"}:
                        return_node = child
            ret = self._unwrap_type(
                next(iter(self.children(return_node)), None)
                if return_node is not None
                else None
            )
            return ret if ret is not None and self._is_arrayish(ret) else None
        if callback.type == "arrow_function":
            return_node = callback.child_by_field_name("return_type")
            if return_node is not None:
                ret = self._unwrap_type(
                    next(iter(self.children(return_node)), None)
                )
                return ret if self._is_arrayish(ret) else None
            body = callback.child_by_field_name("body")
            if body is None:
                kids = self.children(callback)
                body = kids[-1] if kids else None
            if body is None:
                return None
            params = callback.child_by_field_name("parameters")
            if params is not None:
                names = [
                    self.text(pattern)
                    for child in self.children(params)
                    for pattern in [
                        child.child_by_field_name("pattern") or child
                    ]
                    if pattern.type == "identifier"
                ]
            else:
                names = [
                    self.text(child)
                    for child in self.children(callback)
                    if child.type == "identifier"
                    and child.id != body.id
                ]
            if body.type == "identifier":
                # `r => r` — identity on the callback's parameter:
                # the result keeps the receiver's element array.
                if self.text(body) in names:
                    return receiver_elem
                return None
            if body.type == "member_expression":
                # `r2 => r2.cells` — the object is the callback's
                # parameter (the receiver's element type); resolve
                # the member on that type record directly.
                obj = body.child_by_field_name("object")
                prop = body.child_by_field_name("property")
                if (
                    obj is not None
                    and prop is not None
                    and obj.type == "identifier"
                    and self.text(obj) in names
                ):
                    fact = self._type_fact(receiver_elem)
                    if fact.kind == "named":
                        type_record = self._type_record_by_id(
                            fact.type_id
                        )
                        if type_record is not None:
                            # `_member_lookup` needs the member
                            # records, which are bound in a later
                            # pass — this runs while a for-in's
                            # pattern is being predeclared, so the
                            # declaration body's members are read
                            # from the AST instead.
                            ret = self._decl_member_type_node(
                                type_record, self.text(prop)
                            )
                            if (
                                ret is not None
                                and self._is_arrayish(ret)
                            ):
                                return ret
                return None
            ret = self._unwrap_type(
                self._declared_type_node(body, body.start_byte)
            )
            return ret if ret is not None and self._is_arrayish(ret) else None
        return None

    def _decl_member_type_node(
        self, type_record: Any, name: str
    ) -> Any | None:
        """Type annotation node of member `name` on the declaration
        body of `type_record` — read straight from the AST so it also
        works before member records are bound."""
        decl = None if type_record.node is None else type_record.node.parent
        if decl is None:
            return None
        body = decl.child_by_field_name("body")
        if body is None:
            return None
        for member in self.children(body):
            name_node = member.child_by_field_name("name")
            if name_node is None:
                continue
            if self.text(name_node) != name:
                continue
            if member.type in {
                "property_signature",
                "public_field_definition",
                "abstract_method_signature",
                "method_signature",
                "method_definition",
            } and not any(
                self.text(child) == "static" for child in member.children
            ):
                ret = member.child_by_field_name("type") or (
                    member.child_by_field_name("return_type")
                )
                return self._unwrap_type(ret) if ret is not None else None
        return None

    def _array_method_result(self, node: Any) -> Any | None:
        """Result type node of a std array method call — `at`/`find`
        approximate `T | undefined` as `T`; `filter`/`slice` keep
        the array; `flat` peels one nesting level; `flatMap` reads
        the callback's return array. Declared members always win —
        this only runs when `_callee_return_node` found none."""
        callee = node.child_by_field_name("function")
        if callee is None or callee.type != "member_expression":
            return None
        obj = callee.child_by_field_name("object")
        prop = callee.child_by_field_name("property")
        if obj is None or prop is None:
            return None
        member = self.text(prop)
        declared = self._unwrap_type(
            self._declared_type_node(obj, obj.start_byte)
        )
        if declared is None:
            if self.text(obj) == "Array" and member == "from" and (
                not self._builtin_shadowed(obj, member)
            ):
                # `Array.from(iterable)` keeps the iterable's
                # element type.
                args_node = node.child_by_field_name("arguments")
                arg0 = (
                    next(iter(self.children(args_node)), None)
                    if args_node is not None
                    else None
                )
                source = self._unwrap_type(
                    self._declared_type_node(
                        arg0,
                        arg0.start_byte if arg0 is not None else 0,
                    )
                )
                if source is not None and self._is_arrayish(source):
                    return source
            return None
        elem = self._array_element_node(declared)
        if member == "get":
            # `Map<K, V>.get(k)` / `WeakMap` — `V | undefined`
            # spelled as `V`; `?.`/`!` do the narrowing.
            if declared.type == "generic_type":
                kids = self.children(declared)
                if kids and self.text(kids[0]) in {
                    "Map", "WeakMap",
                }:
                    args = [
                        child
                        for child in kids
                        if child.type == "type_arguments"
                    ]
                    if args:
                        elems = self.children(args[0])
                        return (
                            elems[1] if len(elems) > 1 else None
                        )
            return None
        if elem is None:
            return None
        if member in {"at", "find", "findLast"}:
            return elem
        if member in {
            "concat",
            "filter",
            "fill",
            "reverse",
            "slice",
            "sort",
            "splice",
            "toReversed",
            "toSorted",
            "toSpliced",
            "with",
        }:
            return declared
        if member == "flat":
            return elem if self._is_arrayish(elem) else declared
        if member == "flatMap":
            return self._callback_array_return(node, elem)
        return None

    def _callee_return_node(self, node: Any) -> Any | None:
        """Return-type annotation node of a call's resolved callee —
        the signature the arguments narrow to, so `make(1).method()`
        reads `make`'s chosen overload's return type."""
        callee = node.child_by_field_name("function")
        # Explicit type arguments on the call (`make<T, U>(...)`,
        # `(make<T, U>)(...)`) pin the signature's declared arity —
        # an overload whose required/total range excludes it cannot
        # be the callee.
        type_args_node = self._call_type_args_node(node)
        type_arg_texts = (
            [self.text(child) for child in self.children(type_args_node)]
            if type_args_node is not None
            else None
        )
        type_args_count = (
            None if type_arg_texts is None else len(type_arg_texts)
        )
        while callee is not None and callee.type in {
            "parenthesized_expression", "instantiation_expression",
        }:
            callee = next(
                (
                    child
                    for child in self.children(callee)
                    if child.type not in {"type_arguments"}
                ),
                None,
            )
        args_node = node.child_by_field_name("arguments")
        arg_nodes: list | None = None
        if args_node is not None and args_node.type == "template_string":
            # A tag is called `(strings, ...values)` — the template
            # itself plus one argument per interpolation. The first
            # argument is a strings array, not the template's literal
            # text, so it is represented by an unpinned node; each
            # substitution narrows by its expression's type.
            arg_nodes = [node] + [
                expr
                for child in self.children(args_node)
                if child.type == "template_substitution"
                for expr in [next(iter(self.children(child)), None)]
                if expr is not None
            ]
        record: _Record | None = None
        if callee is not None and callee.type == "identifier":
            candidates = self._lookup_candidates(
                self.text(callee), node.start_byte, "value"
            )
            if candidates:
                # A nearer scope's declaration shadows outer ones —
                # only the innermost scope's overloads may be picked,
                # matching the call-site rule in `_reference`.
                scope = candidates[0].binding.scope
                key = (
                    None if scope is None else (scope.start, scope.end)
                )
                candidates = [
                    candidate
                    for candidate in candidates
                    if (
                        None
                        if candidate.binding.scope is None
                        else (
                            candidate.binding.scope.start,
                            candidate.binding.scope.end,
                        )
                    ) == key
                ]
                if type_args_count is not None:
                    # Defaults keep an overload eligible — `f<T, U = V>`
                    # accepts `f<A>(...)`.
                    matching = [
                        candidate
                        for candidate in candidates
                        if self._required_type_param_count(candidate)
                        <= type_args_count
                        <= self._type_param_count(candidate)
                    ]
                    if matching:
                        candidates = matching
                narrowed = self._narrow_overloads(
                    candidates, args_node, arg_nodes,
                    type_args=type_arg_texts,
                )
                if (
                    narrowed is candidates
                    and type_args_count is not None
                    and narrowed
                ):
                    # Explicit type args, indiscriminate value args —
                    # tsc picks the earliest declared signature that
                    # fits, not the lookup's latest-first head.
                    record = min(
                        narrowed, key=lambda c: c.binding.span.start
                    )
                else:
                    record = narrowed[0] if narrowed else candidates[0]
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
                    args_node=args_node,
                    arg_nodes=arg_nodes,
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
            narrowed = self._narrowed.get(node.id)
            if narrowed is not None and narrowed.type != "identifier":
                # `Array.isArray(arr)` narrows the use to the
                # declared union's array constituent — a real type
                # node. An `instanceof` right operand is a class
                # expression, consumed by member lookup only.
                return narrowed
            type_node = self._unwrap_type(record.type_node)
            if type_node is not None:
                if (
                    type_node.type == "union_type"
                    and self._accessed_optionally(node)
                ):
                    # `arr?.[0]` — `?.`/`!` narrow the union to its
                    # non-null constituent before the access.
                    return self._non_nullable_type_node(type_node)
                return type_node
            if (
                record.node is not None
                and record.node.id not in self._type_node_active
            ):
                declarator = record.node.parent
                if (
                    declarator is not None
                    and declarator.type == "variable_declarator"
                ):
                    value = declarator.child_by_field_name("value")
                    if value is not None and value.type in {
                        "array", "binary_expression",
                        "ternary_expression",
                    }:
                        # `const cp = [...arr]` / `lit = arr ?? []`
                        # — unannotated, the initializer spells the
                        # element type.
                        self._type_node_active.add(record.node.id)
                        try:
                            return self._declared_type_node(
                                value, position
                            )
                        finally:
                            self._type_node_active.discard(
                                record.node.id
                            )
            return None
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
                object_node = node.child_by_field_name("object")
                literal_value = self._object_literal_property(
                    object_node,
                    self.text(property_node),
                    position,
                )
                if literal_value is not None:
                    owner = self._literal_owner_record(
                        object_node, position
                    )
                    if owner is None:
                        return None
                    self._type_node_active.add(owner.node.id)
                    try:
                        # The pair's value resolves in the
                        # literal's own scope — a same-named
                        # local at the use site cannot steal it.
                        return self._declared_type_node(
                            literal_value, literal_value.start_byte
                        )
                    finally:
                        self._type_node_active.discard(
                            owner.node.id
                        )
                return None
            return self._unwrap_type(member.type_node)
        if node.type == "call_expression":
            return_node = self._callee_return_node(node)
            if return_node is not None:
                return self._unwrap_type(
                    next(iter(self.children(return_node)), None)
                )
            return self._array_method_result(node)
        if node.type == "subscript_expression":
            inner = self._declared_type_node(
                node.child_by_field_name("object"), position
            )
            if inner is not None and inner.type == "array_type":
                return next(iter(self.children(inner)), None)
            index = node.child_by_field_name("index")
            if index is not None and index.type == "string":
                # `o["head"]` on `const o = {head: arr[0]}` — the
                # same literal-pair fallback as member access.
                object_node = node.child_by_field_name("object")
                literal_value = self._object_literal_property(
                    object_node,
                    self.text(index).strip().strip("\"'"),
                    position,
                )
                if literal_value is not None:
                    owner = self._literal_owner_record(
                        object_node, position
                    )
                    if owner is None:
                        return None
                    self._type_node_active.add(owner.node.id)
                    try:
                        return self._declared_type_node(
                            literal_value, position
                        )
                    finally:
                        self._type_node_active.discard(
                            owner.node.id
                        )
            return None
        if node.type == "array":
            # `[...arr]` — a single spread keeps the operand's
            # element type; mixed or multiple spreads form a union
            # the syntax cannot spell, so they stay opaque.
            kids = self.children(node)
            if len(kids) == 1 and kids[0].type == "spread_element":
                inner = next(iter(self.children(kids[0])), None)
                return self._declared_type_node(inner, position)
            return None
        if node.type == "binary_expression":
            kids = self.children(node)
            if any(
                child.type == "??" or self.text(child) == "??"
                for child in node.children
            ):
                # `arr ?? []` — the left's non-null constituent; when
                # the left spells nothing, the right's type is it.
                left = next(iter(kids), None)
                left_node = self._non_nullable_type_node(
                    self._unwrap_type(
                        self._declared_type_node(
                            left,
                            left.start_byte if left is not None else 0,
                        )
                    )
                )
                if left_node is not None:
                    right = kids[-1] if kids else None
                    right_node = self._unwrap_type(
                        self._declared_type_node(
                            right,
                            right.start_byte if right is not None else 0,
                        )
                    )
                    if right_node is not None:
                        left_fact = self._type_fact(left_node)
                        right_fact = self._type_fact(right_node)
                        if (
                            left_fact.kind == "named"
                            and right_fact.kind == "named"
                            and right_fact.type_id != left_fact.type_id
                        ):
                            # `a ?? b` may hold `b`'s type —
                            # claiming `a`'s alone would bind
                            # calls to the wrong declaration.
                            return None
                    return left_node
                right = kids[-1] if kids else None
                return self._declared_type_node(
                    right,
                    right.start_byte if right is not None else position,
                )
            return None
        if node.type == "ternary_expression":
            # `c ? a : b` — both alternatives must spell the same
            # named type; differing types form a union the syntax
            # cannot spell and stay opaque.
            kids = self.children(node)
            if len(kids) >= 3:
                left = self._declared_type_node(
                    kids[-2], kids[-2].start_byte
                )
                right = self._declared_type_node(
                    kids[-1], kids[-1].start_byte
                )
                if left is not None and right is not None:
                    lf = self._type_fact(left)
                    rf = self._type_fact(right)
                    if (
                        lf.kind == "named"
                        and rf.kind == "named"
                        and lf.type_id == rf.type_id
                    ):
                        return left
                    if self.text(left).strip() == self.text(
                        right
                    ).strip():
                        # Non-named but identical spellings —
                        # `P[]`/`Map<K, V>`/`(A, B)` — resolve to the
                        # shared shape.
                        return left
            return None
        if node.type in {
            "parenthesized_expression", "non_null_expression",
            "satisfies_expression",
        }:
            return self._declared_type_node(
                next(iter(self.children(node)), None), position
            )
        if node.type == "as_expression":
            # `u as P` — the asserted type is the declared type.
            kids = self.children(node)
            return kids[-1] if len(kids) > 1 else None
        return None

    def _pattern_slot_index(self, pattern: Any, name: Any) -> int:
        """Positional slot index of `name` inside an array/tuple
        destructuring pattern — `[, v]`'s leading comma is an elided
        slot, so `v` sits at index 1, not 0."""
        index = 0
        prev_slot = False
        for child in pattern.children:
            if child.is_named:
                if child.id == name.id:
                    return index
                index += 1
                prev_slot = True
            elif self.text(child) == ",":
                if not prev_slot:
                    index += 1
                prev_slot = False
            else:
                prev_slot = False
        return -1

    def _pattern_slot_type_node(
        self, pattern: Any, name: Any
    ) -> Any | None:
        """The type node a destructuring slot takes — `const [a, b]
        = arr: P[]` types both `a`/`b` as `P`; tuple types take the
        slot's index."""
        declarator = pattern.parent
        if (
            declarator is not None
            and declarator.type == "for_in_statement"
            and any(child.type == "of" for child in declarator.children)
        ):
            # `for (const [k, v] of m)` — the slot peels the
            # iterable's element type (`Map` entries give pairs).
            operand = next(
                (
                    child
                    for child in declarator.children
                    if child.type not in {
                        "for", "(", ")", "of", "in",
                        "var", "let", "const",
                    }
                    and child.start_byte > pattern.end_byte
                ),
                None,
            )
            member = self._iterable_member_args(operand)
            if member is not None:
                member_name, head, arg_nodes = member
                if member_name == "entries":
                    index = self._pattern_slot_index(pattern, name)
                    if index < 0:
                        return None
                    # `for (const [k, v] of m.entries())` — Map pairs
                    # take args positionally; Set yields [P, P];
                    # Array entries pair `number` with the element.
                    if head == "Map" and index < len(arg_nodes):
                        return arg_nodes[index]
                    if head == "Set" and arg_nodes:
                        return arg_nodes[0]
                    if (
                        head in {"Array", "Iterable", "ReadonlyArray"}
                        and index == 1
                        and arg_nodes
                    ):
                        return arg_nodes[0]
                return None
            iterable = self._unwrap_type(
                self._declared_type_node(
                    operand,
                    operand.start_byte if operand is not None else 0,
                )
            )
            if iterable is None:
                constructed = self._new_container_args(operand)
                if (
                    constructed is not None
                    and constructed[0] in {"Map", "WeakMap"}
                ):
                    # `for (const [k, v] of new Map<K, V>())` —
                    # the pair slots take the constructor's args.
                    index = self._pattern_slot_index(pattern, name)
                    arg_nodes = constructed[1]
                    return (
                        arg_nodes[index]
                        if 0 <= index < len(arg_nodes)
                        else None
                    )
            if (
                iterable is not None
                and iterable.type == "generic_type"
                and self.children(iterable)
                and self.text(self.children(iterable)[0]) == "Map"
            ):
                # `for (const [k, v] of m: Map<K, V>)` — entries are
                # `[K, V]` pairs; take the slot from the type args.
                args = [
                    child
                    for child in self.children(iterable)
                    if child.type == "type_arguments"
                ]
                elems = (
                    self.children(args[0]) if args else []
                )
                index = self._pattern_slot_index(pattern, name)
                return (
                    elems[index]
                    if 0 <= index < len(elems)
                    else None
                )
            declared = self._unwrap_type(
                self._iterable_element_node(operand)
            )
            if declared is None or declared.type != "tuple_type":
                return None
        elif (
            declarator is None
            or declarator.type != "variable_declarator"
        ):
            return None
        else:
            value = declarator.child_by_field_name("value")
            declared = self._unwrap_type(
                self._declared_type_node(value, value.start_byte)
            )
        if declared is None:
            if pattern.type == "object_pattern" and value is not None:
                # `const {head} = o` where `o = {head: arr[0]}` —
                # the slot takes the literal pair's value type.
                prop = name
                if (
                    name.parent is not None
                    and name.parent.type == "pair_pattern"
                ):
                    key = name.parent.child_by_field_name("key")
                    if key is not None:
                        prop = key
                prop_name = self.text(prop).strip("\"'")
                record = (
                    self._lookup(
                        self.text(value), value.start_byte, "value"
                    )
                    if value.type == "identifier"
                    else None
                )
                if (
                    record is not None
                    and record.node is not None
                    and record.node.id not in self._type_node_active
                ):
                    pair_value = self._object_literal_property(
                        value, prop_name, value.start_byte
                    )
                    if pair_value is not None:
                        self._type_node_active.add(record.node.id)
                        try:
                            return self._declared_type_node(
                                pair_value, value.start_byte
                            )
                        finally:
                            self._type_node_active.discard(
                                record.node.id
                            )
            return None
        if declared.type == "array_type":
            return next(iter(self.children(declared)), None)
        if declared.type == "tuple_type":
            index = self._pattern_slot_index(pattern, name)
            elems = self.children(declared)
            return elems[index] if 0 <= index < len(elems) else None
        if declared.type == "generic_type":
            kids = self.children(declared)
            if kids and self.text(kids[0]) in {
                "Array", "Set", "Iterable", "ReadonlyArray",
            }:
                args = [
                    child
                    for child in self.children(declared)
                    if child.type == "type_arguments"
                ]
                if args:
                    return next(iter(self.children(args[0])), None)
        return None

    def _initializer_type_record(
        self, record: _Record, position: int
    ) -> _Record | None:
        """Type named by a variable's `new T(...)` initializer."""
        if record.binding.id in self._initializer_active:
            return None
        declarator = record.node.parent
        if declarator is not None and declarator.type in {
            "array_pattern", "object_pattern",
        }:
            # `const [a, b] = arr` — a pattern slot's type comes from
            # the destructured value, not an initializer.
            self._initializer_active.add(record.binding.id)
            try:
                slot_node = self._pattern_slot_type_node(
                    declarator, record.node
                )
                fact = self._type_fact(slot_node)
                return (
                    self._type_record_by_id(fact.type_id)
                    if fact.kind == "named"
                    else None
                )
            finally:
                self._initializer_active.discard(record.binding.id)
        if declarator is None or declarator.type != "variable_declarator":
            return None
        value = declarator.child_by_field_name("value")
        if value is not None and value.type in {
            "subscript_expression",
            "call_expression",
            "member_expression",
            "parenthesized_expression",
            "non_null_expression",
            "as_expression",
            "satisfies_expression",
            "array",
            "binary_expression",
            "ternary_expression",
        }:
            # `const q = arr[0]`/`f()`/`w.p` infer `q`'s type from
            # the initializer's declared result — resolved at the
            # initializer so a same-named local cannot shadow it.
            self._initializer_active.add(record.binding.id)
            try:
                type_node = self._declared_type_node(
                    value, value.start_byte
                )
                fact = self._type_fact(type_node)
                return (
                    self._type_record_by_id(fact.type_id)
                    if fact.kind == "named"
                    else None
                )
            finally:
                self._initializer_active.discard(record.binding.id)
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
                    self._merged_constructible(
                        resolved, self.text(property_node)
                    )
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
                or (
                    sibling.member_of is not None
                    and sibling.member_of != record.member_of
                    and (
                        sibling.member_visibility == "private"
                        or record.member_visibility == "private"
                    )
                )
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

    def _merged_constructible(
        self, record: _Record, name: str | None = None
    ) -> _Record:
        """Prefer the class (or ambient class) of a merged declaration.

        `name` is the property the caller spelled (`new N.A()` → "A"):
        sibling blocks can contribute same-named members reachable under
        different export names, so prefer a class that actually answers
        to the spelled name."""
        def _named(sibling: _Record) -> bool:
            if name is None:
                return True
            value_names, _ = self._member_name_sets(sibling)
            return name in value_names

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
            classes = [
                sibling
                for sibling in siblings
                if self._merge_kind(sibling) == preferred
            ]
            for sibling in classes:
                if _named(sibling):
                    return sibling
            if classes:
                return classes[0]
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

    def _collect_narrowings(self) -> None:
        """Map identifier uses inside condition-controlled regions to
        the narrowed type: `x instanceof C`/`'p' in x`/`Array.isArray(x)`
        on the consequence (if/ternary/while/for bodies), and the union
        minus the named part on else/alternative branches. Reassignment
        stays out of scope (uses there fall back to the declared type)."""
        for node in self.walk(self.root):
            if node.type == "switch_statement":
                self._collect_switch_narrowings(node)
                continue
            if node.type == "ternary_expression":
                self._apply_condition_narrowings(
                    node.child_by_field_name("condition"),
                    node.child_by_field_name("consequence"),
                    node.child_by_field_name("alternative"),
                )
                continue
            if node.type in {"while_statement", "for_statement"}:
                # The body runs only while the condition holds —
                # same consequence-style narrowing as `if`.
                self._apply_condition_narrowings(
                    node.child_by_field_name("condition"),
                    node.child_by_field_name("body"),
                    None,
                )
                continue
            if node.type != "if_statement":
                continue
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            if condition is None or consequence is None:
                continue
            self._apply_condition_narrowings(
                condition,
                consequence,
                node.child_by_field_name("alternative"),
            )
            for node in self.walk(condition):
                # `x && x.pm()` — the left operand's narrowing also
                # covers the right operand's uses.
                if node.type != "binary_expression":
                    continue
                if not any(
                    self.text(child) == "&&"
                    for child in node.children
                ):
                    continue
                kids = self.children(node)
                if len(kids) != 2:
                    continue
                for ident, narrowed in self._condition_narrowings(
                    kids[0]
                ):
                    self._narrow_uses(
                        kids[1], self.text(ident), ident, narrowed
                    )

    def _apply_condition_narrowings(
        self,
        condition: Any | None,
        consequence: Any | None,
        alternative: Any | None,
    ) -> None:
        if consequence is not None:
            for ident, narrowed in self._condition_narrowings(
                condition
            ):
                self._narrow_uses(
                    consequence, self.text(ident), ident, narrowed
                )
        if alternative is not None:
            for ident, narrowed in self._else_narrowings(condition):
                self._narrow_uses(
                    alternative, self.text(ident), ident, narrowed
                )

    def _narrow_uses(
        self,
        region: Any,
        name: str,
        ident: Any,
        narrowed: Any,
    ) -> None:
        """Apply `narrowed` to `name`'s uses inside `region`.

        A use that resolves to another declaration (an inner
        `const x` shadowing the guarded binding) or that follows a
        reassignment of `name` keeps its own type. A later, deeper
        guard wins over an outer one for the same use."""
        target = self._lookup(name, ident.start_byte, "value")
        writes = [
            child
            for child in self.walk(region)
            if (
                child.type
                in {
                    "assignment_expression",
                    "augmented_assignment_expression",
                }
                and (left := child.child_by_field_name("left"))
                is not None
                and left.type == "identifier"
                and self.text(left) == name
            )
        ]
        for desc in self.walk(region):
            if (
                desc.type != "identifier"
                or self.text(desc) != name
                or desc.id == ident.id
            ):
                continue
            if target is not None:
                resolved = self._lookup(
                    name, desc.start_byte, "value"
                )
                if resolved is not None and resolved is not target:
                    continue
            if any(
                w.start_byte < desc.start_byte for w in writes
            ):
                continue
            self._narrowed[desc.id] = narrowed

    def _else_narrowings(self, condition: Any | None):
        """(identifier, narrowed type node) pairs for the else /
        alternative side — the union minus the constituent the
        check names: `u instanceof A` excludes A's part,
        `'p' in u` excludes constituents declaring `p`,
        `Array.isArray(u)` excludes array parts, and `||` combines
        the exclusions (`!(a || b)` is `!a && !b`). `&&` under
        negation is a disjunction, so it spells nothing."""
        while (
            condition is not None
            and condition.type == "parenthesized_expression"
        ):
            condition = next(iter(self.children(condition)), None)
        if condition is None:
            return ()
        if condition.type == "call_expression":
            function = condition.child_by_field_name("function")
            args = condition.child_by_field_name("arguments")
            kids = self.children(args) if args else []
            if (
                function is not None
                and function.type == "member_expression"
                and len(kids) == 1
                and kids[0].type == "identifier"
            ):
                obj = function.child_by_field_name("object")
                prop = function.child_by_field_name("property")
                if (
                    obj is not None
                    and prop is not None
                    and self.text(obj) == "Array"
                    and self.text(prop) == "isArray"
                    and not self._builtin_shadowed(obj, "isArray")
                ):
                    narrowed = self._union_minus(
                        kids[0],
                        lambda c: c.type == "array_type",
                    )
                    if narrowed is not None:
                        return ((kids[0], narrowed),)
            return ()
        if condition.type == "binary_expression":
            kids = self.children(condition)
            if len(kids) != 2:
                return ()
            operators = {
                self.text(child) for child in condition.children
            }
            if "||" in operators:
                return self._else_narrowings(
                    kids[0]
                ) + self._else_narrowings(kids[1])
            if "instanceof" in operators:
                left, right = kids
                if (
                    left.type == "identifier"
                    and right.type == "identifier"
                ):
                    if self.text(right) == "Array":
                        narrowed = self._union_minus(
                            left, lambda c: c.type == "array_type"
                        )
                        if narrowed is not None:
                            return ((left, narrowed),)
                        return ()
                    cls = self._lookup(
                        self.text(right), right.start_byte, "value"
                    )
                    if cls is not None:
                        narrowed = self._union_minus(
                            left,
                            lambda c: self._same_type_record(c, cls),
                        )
                        if narrowed is not None:
                            return ((left, narrowed),)
                return ()
            if "in" in operators:
                left, right = kids
                prop = (
                    self.text(left).strip().strip("\"'")
                    if left.type == "string"
                    else None
                )
                if prop and right.type == "identifier":
                    narrowed = self._union_minus(
                        right,
                        lambda c: self._constituent_declares(
                            c, prop, right.start_byte
                        ),
                    )
                    if narrowed is not None:
                        return ((right, narrowed),)
            return ()
        return ()

    def _union_minus(self, ident: Any, predicate) -> Any | None:
        """The single declared-union constituent left after
        `predicate` drops the checked-out parts; None when the
        identifier has no union or several parts remain."""
        record = self._lookup(
            self.text(ident), ident.start_byte, "value"
        )
        if record is None:
            return None
        declared = self._unwrap_type(record.type_node)
        if declared is None or declared.type != "union_type":
            return None
        kept = [
            child
            for child in self.children(declared)
            if not predicate(child)
        ]
        return kept[0] if len(kept) == 1 else None

    def _same_type_record(self, child: Any, record: _Record) -> bool:
        fact = self._type_fact(child)
        if fact.kind != "named":
            return False
        type_record = self._type_record_by_id(fact.type_id)
        return (
            type_record is not None
            and type_record.node.id == record.node.id
        )

    def _constituent_declares(
        self, child: Any, prop: str, position: int
    ) -> bool:
        fact = self._type_fact(child)
        if fact.kind != "named":
            return False
        type_record = self._type_record_by_id(fact.type_id)
        if type_record is None:
            return False
        return (
            self._member_lookup(
                type_record, prop, position,
                static=False, via_this=False,
            )
            is not None
        )

    def _condition_narrowings(self, condition: Any | None):
        """(identifier, narrowed type node) pairs a condition spells:
        `x instanceof C` narrows to C's class expression;
        `Array.isArray(x)` narrows to the declared union's single
        array constituent; `&&` combines both sides."""
        while (
            condition is not None
            and condition.type == "parenthesized_expression"
        ):
            condition = next(iter(self.children(condition)), None)
        if condition is None:
            return ()
        if condition.type == "binary_expression":
            kids = self.children(condition)
            if len(kids) == 2:
                operators = {
                    self.text(child) for child in condition.children
                }
                if "instanceof" in operators:
                    left, right = kids
                    if left.type == "identifier" and right.type in {
                        "identifier",
                        "member_expression",
                    }:
                        if (
                            right.type == "identifier"
                            and self.text(right) == "Array"
                        ):
                            # `x instanceof Array` is Array.isArray.
                            narrowed = self._array_constituent_node(
                                left
                            )
                            if narrowed is not None:
                                return ((left, narrowed),)
                            return ()
                        return ((left, right),)
                    return ()
                if "in" in operators:
                    left, right = kids
                    prop = (
                        self.text(left).strip().strip("\"'")
                        if left.type == "string"
                        else None
                    )
                    if prop and right.type == "identifier":
                        narrowed = self._member_union_constituent(
                            right, prop
                        )
                        if narrowed is not None:
                            return ((right, narrowed),)
                    return ()
                if "!==" in operators or "!=" in operators:
                    left, right = kids
                    operand = (
                        right
                        if self.text(left).strip()
                        in {"null", "undefined"}
                        else left
                        if self.text(right).strip()
                        in {"null", "undefined"}
                        else None
                    )
                    if operand is not None and operand.type == "identifier":
                        narrowed = self._non_nullable_declared(operand)
                        if narrowed is not None:
                            return ((operand, narrowed),)
                    return ()
                if "&&" in operators:
                    return self._condition_narrowings(
                        kids[0]
                    ) + self._condition_narrowings(kids[1])
            return ()
        if condition.type == "identifier":
            # `if (x)` — truthy narrows `P | undefined` to `P`.
            narrowed = self._non_nullable_declared(condition)
            if narrowed is not None:
                return ((condition, narrowed),)
            return ()
        if condition.type == "call_expression":
            callee = condition.child_by_field_name("function")
            if (
                callee is not None
                and callee.type == "member_expression"
                and self.text(callee.child_by_field_name("property"))
                == "isArray"
                and self.text(callee.child_by_field_name("object"))
                == "Array"
            ):
                arg = next(
                    iter(
                        self.children(
                            condition.child_by_field_name("arguments")
                        )
                    ),
                    None,
                )
                if arg is not None and arg.type == "identifier":
                    narrowed = self._array_constituent_node(arg)
                    if narrowed is not None:
                        return ((arg, narrowed),)
            return ()
        return ()

    def _literal_owner_record(
        self, obj: Any | None, position: int
    ) -> _Record | None:
        """The record of the identifier at the base of a literal
        member chain (`n` for `n.head.inner`) — the node the
        `_type_node_active` guard marks during recursion."""
        root = obj
        while root is not None and root.type != "identifier":
            if root.type == "member_expression":
                root = root.child_by_field_name("object")
            else:
                root = None
        if root is None:
            return None
        record = self._lookup(self.text(root), position, "value")
        if record is None or record.node is None:
            return None
        return record

    def _object_literal_node(
        self, obj: Any | None, position: int
    ) -> Any | None:
        """The `object` literal an expression resolves to — a
        declarator's `object` value for an identifier, or a nested
        literal reached through member chains (`n.head`)."""
        if obj is None:
            return None
        if obj.type == "identifier":
            record = self._literal_owner_record(obj, position)
            if (
                record is None
                or record.node.id in self._type_node_active
            ):
                return None
            declarator = record.node.parent
            if (
                declarator is None
                or declarator.type != "variable_declarator"
            ):
                return None
            literal = declarator.child_by_field_name("value")
            if literal is not None and literal.type == "object":
                return literal
            return None
        if obj.type == "member_expression":
            property_node = obj.child_by_field_name("property")
            if property_node is None:
                return None
            inner = self._object_literal_property(
                obj.child_by_field_name("object"),
                self.text(property_node),
                position,
            )
            if inner is not None and inner.type == "object":
                return inner
        return None

    def _object_literal_property(
        self, obj: Any | None, name: str, position: int
    ) -> Any | None:
        """The value node paired with `name` in `obj`'s object-literal
        initializer — `const o = {head: arr[0]}` gives `o.head` the
        pair's value expression. A self-referential literal stays
        opaque via `_type_node_active`."""
        literal = self._object_literal_node(obj, position)
        if literal is None:
            return None
        for child in self.children(literal):
            if child.type == "pair":
                key = child.child_by_field_name("key")
                if (
                    key is not None
                    and self.text(key).strip("\"'") == name
                ):
                    return child.child_by_field_name("value")
            if (
                child.type == "shorthand_property_identifier"
                and self.text(child) == name
            ):
                return child
        return None

    def _collect_switch_narrowings(self, node: Any) -> None:
        """`switch (u.kind)` on a `u: A | B` union discriminated by a
        literal member maps each `case "a":` body's uses of `u` to
        the matching constituent. `default:` bodies stay opaque."""
        value = node.child_by_field_name("value")
        while (
            value is not None
            and value.type == "parenthesized_expression"
        ):
            value = next(iter(self.children(value)), None)
        if value is None or value.type != "member_expression":
            return
        discriminant = value.child_by_field_name("property")
        obj = value.child_by_field_name("object")
        if (
            discriminant is None
            or obj is None
            or obj.type != "identifier"
        ):
            return
        prop = self.text(discriminant)
        record = self._lookup(self.text(obj), obj.start_byte, "value")
        if record is None:
            return
        declared = self._unwrap_type(record.type_node)
        if declared is None or declared.type != "union_type":
            return
        constituents = {}
        for child in self.children(declared):
            fact = self._type_fact(child)
            if fact.kind != "named":
                continue
            type_record = self._type_record_by_id(fact.type_id)
            if type_record is None:
                continue
            member = self._member_lookup(
                type_record,
                prop,
                obj.start_byte,
                static=False,
                via_this=False,
            )
            if member is None:
                continue
            lit = self._unwrap_type(member.type_node)
            if lit is not None and lit.type == "literal_type":
                constituents[self.text(lit).strip()] = child
        body = node.child_by_field_name("body")
        if body is None:
            return
        name = self.text(obj)
        covered = {
            constituents[self.text(c.child_by_field_name("value")).strip()].id
            for c in self.children(body)
            if c.type == "switch_case"
            and c.child_by_field_name("value") is not None
            and self.text(c.child_by_field_name("value")).strip() in constituents
        }
        for case in self.children(body):
            if case.type == "switch_case":
                case_value = case.child_by_field_name("value")
                if case_value is None:
                    continue
                narrowed = constituents.get(
                    self.text(case_value).strip()
                )
            elif case.type == "switch_default":
                # `default:` sees the union minus every covered
                # constituent — only a single remaining part
                # spells a type.
                remaining = [
                    child
                    for child in self.children(declared)
                    if child.id not in covered
                ]
                narrowed = remaining[0] if len(remaining) == 1 else None
            else:
                continue
            if narrowed is None:
                continue
            for desc in self.walk(case):
                if (
                    desc.type == "identifier"
                    and self.text(desc) == name
                    and desc.id != obj.id
                ):
                    self._narrowed.setdefault(desc.id, narrowed)

    def _non_nullable_declared(self, ident: Any) -> Any | None:
        """The non-null constituent of `ident`'s declared type —
        `x !== undefined`/`if (x)` narrow `P | undefined` to `P`."""
        record = self._lookup(
            self.text(ident), ident.start_byte, "value"
        )
        if record is None or record.type_node is None:
            return None
        return self._non_nullable_type_node(
            self._unwrap_type(record.type_node)
        )

    def _member_union_constituent(
        self, ident: Any, prop: str
    ) -> Any | None:
        """The union constituent declaring member `prop` —
        `'pm' in u` narrows `P | Q` to `P`. When every or no part
        declares it the check does not discriminate, so the use
        keeps the declared union."""
        record = self._lookup(
            self.text(ident), ident.start_byte, "value"
        )
        if record is None:
            return None
        declared = self._unwrap_type(record.type_node)
        if declared is None or declared.type != "union_type":
            return None
        matches = []
        for child in self.children(declared):
            fact = self._type_fact(child)
            if fact.kind != "named":
                continue
            type_record = self._type_record_by_id(fact.type_id)
            if type_record is None:
                continue
            if (
                self._member_lookup(
                    type_record,
                    prop,
                    ident.start_byte,
                    static=False,
                    via_this=False,
                )
                is not None
            ):
                matches.append(child)
        return matches[0] if len(matches) == 1 else None

    def _array_constituent_node(self, ident: Any) -> Any | None:
        """The array part of `ident`'s declared union —
        `Array.isArray` narrows `P[] | string` to `P[]`. Anything
        else (no union, several array parts, none) stays opaque."""
        record = self._lookup(
            self.text(ident), ident.start_byte, "value"
        )
        if record is None:
            return None
        declared = self._unwrap_type(record.type_node)
        if declared is None or declared.type != "union_type":
            return None
        parts = [
            child
            for child in self.children(declared)
            if child.type == "array_type"
        ]
        return parts[0] if len(parts) == 1 else None

    def _non_nullable_type_node(self, node: Any | None) -> Any | None:
        """The non-null constituent of a union annotation — `P |
        undefined` peels to `P` for `?.`/`!` narrowing. A union
        that keeps several constituents returns None (the member
        must exist on every part — unresolved either way)."""
        node = self._unwrap_type(node)
        if node is None:
            return None
        if node.type != "union_type":
            return node
        kept = []
        for child in self.children(node):
            text = self.text(child).strip()
            if child.type in {"literal_type", "predefined_type",
                              "type_identifier"} and text in {
                "undefined", "null", "void", "never",
            }:
                continue
            kept.append(child)
        return kept[0] if len(kept) == 1 else None

    def _accessed_optionally(self, node: Any) -> bool:
        """True when `node` is the object of a `?.` member/subscript
        access or wrapped by `!` — the forms TS narrows to the
        non-null union constituent."""
        parent = node.parent
        if parent is None:
            return False
        if parent.type == "non_null_expression":
            return True
        if parent.type in {"member_expression", "subscript_expression"}:
            return any(
                child.type == "optional_chain"
                for child in self.children(parent)
            )
        return False

    def _object_type(
        self,
        node: Any | None,
        position: int,
        extras_out: list[_Record] | None = None,
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
            for base, base_value in self._type_bases.get(
                None if decl is None else decl.id, ()
            )[:1]:
                base_record = self._base_type_record(
                    base, decl.start_byte, for_type=not base_value
                )
                if base_record is not None:
                    return base_record, False, True
            return None, False, True
        if node.type == "identifier":
            record = self._lookup(self.text(node), position, "value")
            if record is None:
                return None, False, False
            narrowed = self._narrowed.get(node.id)
            if narrowed is not None:
                # `x instanceof C` narrows x's uses in the
                # consequence to the checked class; the right
                # operand is a value (class expression), so look
                # it up as a value.
                if narrowed.type == "identifier":
                    narrowed_record = self._lookup(
                        self.text(narrowed),
                        narrowed.start_byte,
                        "value",
                    )
                    if narrowed_record is not None and (
                        narrowed_record.class_like
                        or narrowed_record.binding.kind
                        in {"class", "interface", "enum", "namespace"}
                    ):
                        return narrowed_record, False, False
                elif narrowed.type == "member_expression":
                    property_node = narrowed.child_by_field_name(
                        "property"
                    )
                    if property_node is not None:
                        narrowed_record = self._resolve_member(
                            narrowed.child_by_field_name("object"),
                            self.text(property_node),
                            narrowed.start_byte,
                        )
                        if narrowed_record is not None and (
                            narrowed_record.class_like
                            or narrowed_record.binding.kind
                            in {"class", "interface", "enum", "namespace"}
                        ):
                            return narrowed_record, False, False
                else:
                    fact = self._type_fact(narrowed)
                    if fact.kind == "named":
                        return (
                            self._type_record_by_id(fact.type_id),
                            False,
                            False,
                        )
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
            if self._accessed_optionally(node):
                # `o?.pm()` reads `pm` on the non-null union part —
                # `P | undefined` narrows to `P`. Plain `o.pm()` on
                # the union stays opaque (TS flags it an error).
                fact = self._type_fact(
                    self._non_nullable_type_node(record.type_node)
                )
                if fact.kind != "named" and record.type_node is None:
                    # `const v = o` carries `o`'s union through the
                    # initializer — peel that for `v?.pm()` too.
                    declarator = record.node.parent
                    if (
                        declarator is not None
                        and declarator.type == "variable_declarator"
                    ):
                        fact = self._type_fact(
                            self._non_nullable_type_node(
                                self._declared_type_node(
                                    declarator.child_by_field_name(
                                        "value"
                                    ),
                                    position,
                                )
                            )
                        )
                if fact.kind == "named":
                    return (
                        self._type_record_by_id(fact.type_id),
                        False,
                        False,
                    )
            annotated_opaque = self._unwrap_type(
                record.type_node
            )
            if annotated_opaque is None or annotated_opaque.type not in {
                "union_type", "intersection_type",
            }:
                # Unannotated or unresolvable (`x: Missing.T`)
                # declarators infer `q`'s type from the initializer —
                # `const q = arr[0]`/`f()`/`new P()`. A union or
                # intersection annotation is authoritative even
                # though the member stays opaque.
                inferred = self._initializer_type_record(
                    record, position
                )
                return inferred, False, False
            return None, False, False
        if node.type == "non_null_expression":
            # `o!.pm()` — the assertion narrows the union to its
            # non-null constituent before member lookup.
            inner = next(
                iter(self.children(node)), None
            )
            type_node = self._non_nullable_type_node(
                self._declared_type_node(inner, position)
            )
            fact = self._type_fact(type_node)
            if fact.kind != "named":
                return None, False, False
            return self._type_record_by_id(fact.type_id), False, False
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
                collect_extras=extras_out,
            )
            if member is None:
                object_node = node.child_by_field_name("object")
                literal_value = self._object_literal_property(
                    object_node,
                    self.text(property_node),
                    position,
                )
                if literal_value is not None:
                    # `o.head.pm()` on `const o = {head: arr[0]}` —
                    # the pair's value expression spells the type.
                    owner = self._literal_owner_record(
                        object_node, position
                    )
                    if owner is None:
                        return None, False, False
                    self._type_node_active.add(owner.node.id)
                    try:
                        # The pair's value resolves in the
                        # literal's own scope, not the use site's.
                        return self._object_type(
                            literal_value, literal_value.start_byte
                        )
                    finally:
                        self._type_node_active.discard(
                            owner.node.id
                        )
                return None, False, False
            if member.class_like or member.binding.kind == "namespace":
                return member, True, False
            fact = self._type_fact(member.type_node)
            if fact.kind != "named":
                return None, False, False
            return self._type_record_by_id(fact.type_id), False, False
        if node.type == "call_expression":
            record = self._return_type_record(node)
            if record is not None:
                return record, False, False
            # Undeclared callee — std array recipes (`arr.find(cb)
            # ?.pm()`, `Array.from(...)`) still spell a result type.
            type_node = self._declared_type_node(node, position)
            fact = self._type_fact(type_node)
            if fact.kind != "named":
                return None, False, False
            return self._type_record_by_id(fact.type_id), False, False
        if node.type in {
            "subscript_expression",
            "as_expression",
        }:
            # `(u as P).pm()` — the asserted type declares the member;
            # parenthesized/satisfies/await still recurse into the
            # inner expression below.
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
                            self._merged_constructible(
                                record, self.text(property_node)
                            ),
                            False,
                            False,
                        )
            return None, False, False
        if node.type in {
            "parenthesized_expression", "non_null_expression",
            "as_expression", "satisfies_expression", "await_expression",
        }:
            return self._object_type(
                next(iter(self.children(node)), None),
                position,
                extras_out=extras_out,
            )
        return None, False, False

    def _resolve_member(
        self,
        object_node: Any | None,
        name: str,
        position: int,
        *,
        collect_extras: list[_Record] | None = None,
        args_node: Any | None = None,
        arg_nodes: list | None = None,
    ) -> _Record | None:
        # Exported-name collisions on the object segment: the losing
        # members stay reachable for this one lookup step, so a value
        # path like `N.Public.f()` still reaches the namespace's `f`
        # when the class won `Public`.
        inner_extras: list[_Record] = []
        type_record, static, via_this = self._object_type(
            object_node, position, extras_out=inner_extras
        )
        if type_record is None:
            return self._union_member(object_node, name, position)
        # The collision losers only apply when the winning member
        # record does not provide the name — seeded candidates can
        # never beat the winner's own members.
        member = self._member_lookup(
            type_record,
            name,
            position,
            static=static,
            via_this=via_this,
            extra_seed=tuple(inner_extras),
            collect_extras=collect_extras,
            args_node=args_node,
            arg_nodes=arg_nodes,
        )
        if member is None:
            member = self._union_member(object_node, name, position)
        return member

    def _member_return_fact(self, member: _Record):
        """`_type_fact` of a member's declared type — a field's
        annotation, or a method's return annotation."""
        type_node = member.type_node
        if type_node is None and member.node is not None:
            signature = member.node.parent
            if signature is not None:
                return_node = signature.child_by_field_name(
                    "return_type"
                )
                type_node = (
                    next(iter(self.children(return_node)), None)
                    if return_node is not None
                    else None
                )
        if type_node is None:
            return None
        return self._type_fact(self._unwrap_type(type_node))

    def _union_member(
        self, object_node: Any | None, name: str, position: int
    ) -> _Record | None:
        """`u.m` where `u: A | B` and every named constituent declares
        `m` — tsc resolves the access to each declaration, so binding
        the first is honest. A primitive or undeclared part keeps it
        opaque (the access would not typecheck)."""
        if object_node is None or object_node.type != "identifier":
            return None
        record = self._lookup(
            self.text(object_node), object_node.start_byte, "value"
        )
        if record is None:
            return None
        declared = self._unwrap_type(record.type_node)
        if declared is None or declared.type != "union_type":
            return None
        found: _Record | None = None
        for child in self.children(declared):
            fact = self._type_fact(child)
            if fact.kind != "named":
                return None
            type_record = self._type_record_by_id(fact.type_id)
            if type_record is None:
                return None
            member = self._member_lookup(
                type_record,
                name,
                position,
                static=False,
                via_this=False,
            )
            if member is None:
                return None
            if found is None:
                found = member
                found_fact = self._member_return_fact(member)
                continue
            other_fact = self._member_return_fact(member)
            if (
                found_fact is not None
                and other_fact is not None
                and found_fact.kind == "named"
                and other_fact.kind == "named"
                and found_fact.type_id != other_fact.type_id
            ):
                # `u.m()` where the constituents' `m` return
                # different types — a chained `.n()` would bind
                # the first member's declaration only.
                return None
        return found

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
        args_node: Any | None = None,
        type_args: list[str] | None = None,
    ) -> tuple[_Record | None, str | None]:
        name = self.text(node)
        if name == "arguments" and namespace == "value":
            self.add_unresolved(node, name, "arguments_object")
            return None, "arguments_object"
        if any(self._scope_contains(scope, node.start_byte) for scope in with_scopes):
            self.add_unresolved(node, name, "with_scope")
            return None, "with_scope"
        record = self._lookup(name, node.start_byte, namespace)
        if (
            record is not None
            and args_node is not None
            and namespace == "value"
            and record.function_node is not None
        ):
            signatures = [
                candidate
                for candidate in self._lookup_candidates(
                    name, node.start_byte, namespace
                )
                if candidate.function_node is not None
            ]
            if signatures:
                # A nearer scope's `f` shadows outer declarations — only
                # overloads in that innermost scope may be picked.
                scope = signatures[0].binding.scope
                key = (
                    None if scope is None else (scope.start, scope.end)
                )
                signatures = [
                    candidate
                    for candidate in signatures
                    if (
                        None
                        if candidate.binding.scope is None
                        else (
                            candidate.binding.scope.start,
                            candidate.binding.scope.end,
                        )
                    ) == key
                ]
            type_args_count = (
                None if type_args is None else len(type_args)
            )
            if type_args_count is not None:
                # The call target narrows by the same explicit type
                # arguments the return-type side uses — `make<A, B>(x)`
                # cannot bind an overload that lacks that arity.
                matching = [
                    candidate
                    for candidate in signatures
                    if self._required_type_param_count(candidate)
                    <= type_args_count
                    <= self._type_param_count(candidate)
                ]
                if matching:
                    signatures = matching
            narrowed = self._narrow_overloads(
                signatures, args_node, type_args=type_args
            )
            if (
                narrowed is signatures
                and type_args_count is not None
                and narrowed
            ):
                # Same tsc rule as the return-type side: explicit type
                # args, indiscriminate value args — earliest declared.
                record = min(
                    narrowed, key=lambda c: c.binding.span.start
                )
            elif narrowed:
                record = narrowed[0]
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
        if node.type == "nested_type_identifier":
            # Qualified paths in type position stay conservative:
            # `_type_fact` resolves them for receiver typing, but the
            # reference report keeps the `qualified_path` marker.
            self.add_unresolved(
                node, self.text(node).strip(), "qualified_path"
            )
            return
        if node.type == "member_expression":
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
                    args_node=node.child_by_field_name("arguments"),
                )
                if new and member is not None:
                    member = self._merged_constructible(
                        member, self.text(property_node)
                    )
                if member is not None:
                    self.add_reference(property_node, member, "call")
            kind = "opaque_method"
            if optional and member is None:
                # `o?.pm()` with `pm` unresolved — the optional chain
                # keeps the receiver's narrowable type opaque.
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
        call_type_args = self._call_type_args_node(node)
        record, reason = self._resolve(
            callee,
            "value",
            "call",
            with_scopes,
            constructible=new,
            args_node=node.child_by_field_name("arguments"),
            type_args=(
                [
                    self.text(child)
                    for child in self.children(call_type_args)
                ]
                if call_type_args is not None
                else None
            ),
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
                if (
                    namespace == "value"
                    and self._lookup(
                        self.text(local), local.start_byte, "value"
                    )
                    is None
                    and self._lookup(
                        self.text(local), local.start_byte, "type"
                    )
                    is not None
                ):
                    # A plain `export {X as Y}` publishes type-only
                    # names (interfaces, aliases) too — fall back to
                    # the type side when the value side misses.
                    self._resolve(local, "type", "read", with_scopes)
                else:
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
