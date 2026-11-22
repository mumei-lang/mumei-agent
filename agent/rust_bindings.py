"""Conservative tree-sitter Rust lexical binding reports."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field, replace
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
    NON_ASSIGNABLE_WRITE_KINDS,
    Reference,
    TypeFact,
    Unresolved,
    binding_id,
)

PROFILE = "mumei.rust-lexical-bindings/v1"
MAX_SOURCE_BYTES = 64 * 1024
_UNKNOWN = TypeFact("unknown", "", 0, None, "")
# Single-generic-argument containers whose `Index::Output` is the
# element type — `Vec<P>[i]` : P. Maps are handled by value-arg
# extraction in `_annotation_type`; anything else stays opaque.
_INDEX_ELEMENT_CONTAINERS = frozenset(
    {
        "Vec",
        "VecDeque",
        "LinkedList",
        "HashSet",
        "BTreeSet",
        "BinaryHeap",
        "HashMap",
        "BTreeMap",
    }
)

_PRELUDE_NAMES = frozenset(
    {
        "Some", "None", "Ok", "Err", "Vec", "String", "Box", "Option",
        "Result", "drop", "Default", "Clone", "Copy", "Iterator",
        "ToString", "ToOwned", "AsRef", "AsMut", "Borrow", "Into",
        "From", "TryFrom", "TryInto", "Send", "Sync", "Sized", "Unpin",
        "Fn", "FnMut", "FnOnce", "bool", "char", "str", "i8", "i16",
        "i32", "i64", "i128", "isize", "u8", "u16", "u32", "u64",
        "u128", "usize", "f32", "f64", "Self",
    }
)
_PRELUDE_TYPE_NAMES = frozenset(
    {
        "Vec", "String", "Box", "Option", "Result", "Default", "Clone",
        "Copy", "Iterator", "ToString", "ToOwned", "AsRef", "AsMut",
        "Borrow", "Into", "From", "TryFrom", "TryInto", "Send", "Sync",
        "Sized", "Unpin", "Fn", "FnMut", "FnOnce", "bool", "char", "str",
        "i8", "i16", "i32", "i64", "i128", "isize", "u8", "u16", "u32",
        "u64", "u128", "usize", "f32", "f64", "Self",
    }
)
_PRELUDE_PATTERN_PATHS = frozenset({"Some", "None", "Ok", "Err"})
_INERT_ATTRIBUTES = frozenset(
    {
        "allow",
        "warn",
        "deny",
        "forbid",
        "expect",
        "deprecated",
        "must_use",
        "inline",
        "cold",
        "doc",
        "repr",
        "non_exhaustive",
        "track_caller",
        "no_mangle",
        "export_name",
        "link_name",
        "link_section",
        "used",
        "test",
        "ignore",
        "should_panic",
        "automatically_derived",
    }
)
_DERIVE_TRAITS = frozenset(
    {"Debug", "Clone", "Copy", "PartialEq", "Eq", "PartialOrd", "Ord", "Hash", "Default"}
)
_ATTRIBUTE_PATH = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*)")
_DERIVE_ARGUMENTS = re.compile(r"^derive\s*\((.*)\)\s*$", re.DOTALL)
_ITEM_KINDS = {
    "function_item": "function",
    "const_item": "const",
    "static_item": "static",
    "struct_item": "struct",
    "enum_item": "enum",
    "type_item": "type_alias",
    "trait_item": "trait",
    "union_item": "union",
    "mod_item": "module",
    "extern_crate_declaration": "import",
}
_EXPR_NODES = {
    "array_expression", "assignment_expression", "await_expression",
    "async_block", "binary_expression", "block", "break_expression", "call_expression",
    "cast_expression", "closure_expression", "continue_expression",
    "const_block", "field_expression", "for_expression", "if_expression", "index_expression",
    "let_declaration", "let_condition", "loop_expression", "match_expression",
    "method_call_expression", "parenthesized_expression", "range_expression",
    "reference_expression", "return_expression", "scoped_identifier",
    "scoped_type_identifier", "try_block", "try_expression", "tuple_expression",
    "unary_expression", "unsafe_block", "while_expression", "yield_expression",
}
_TRANSPARENT_NODES = {
    "expression_statement", "arguments", "tuple_type", "reference_type",
    "array_type", "slice_type", "generic_type", "type_arguments",
    "type_parameters", "where_clause", "parameter", "parameters",
    "closure_parameters", "else_clause", "mutable_specifier", "mut_pattern",
}


def _has_keyword(text: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


@dataclass
class _Scope:
    node: Any
    module_depth: int
    function_id: str
    bindings: dict[str, list["_Record"]] = field(default_factory=dict)
    glob_import: bool = False
    ambiguous_names: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass
class _Record:
    binding: Binding
    owner_function: str | None
    module_depth: int
    item: bool
    alias_node: Any = None
    body_node: Any = None
    generic: bool = False
    is_async: bool = False
    variadic: bool = False
    extern: bool = False
    struct_constructor: bool = False
    generic_kind: str = ""
    type_node: Any = None
    # Binding id of the declaring struct/union/impl target this
    # record is a member of; None for non-members.
    member_of: str | None = None
    # Normalized type arguments of a concrete specialization impl
    # (`impl Wrap<i32>` → "i32"); None for plain impls.
    member_impl_args: str | None = None
    # The impl block itself is generic (`impl<T> Wrap<T>`) — its
    # members apply to every instantiation.
    member_impl_generic: bool = False
    # Binding id of the trait an `impl Tr for T` member belongs to;
    # None for inherent impl members.
    member_trait: str | None = None
    # Normalized trait type arguments (`impl Tr<u32> for T` → "u32");
    # None for a non-generic trait impl.
    member_trait_args: str | None = None
    # The impl block's own `type` node — the declared type `self`
    # parameters inside it refer to (keeps generic args).
    self_type_node: Any = None
    # A `let` initializer node — used to infer the binding's type
    # when no annotation is present.
    value_node: Any = None
    # A `mod` item's body scope — lets `m::T` annotations resolve.
    module_scope: Any = None


class _RustBindings:
    def __init__(self, source: str, raw: bytes, pointer_width: int, root: Any):
        self.source = source
        self.raw = raw
        self.pointer_width = pointer_width
        self.root = root
        self.source_hash = hashlib.sha256(raw).hexdigest()
        self.bindings: list[Binding] = []
        self.references: list[Reference] = []
        self.unresolved: list[Unresolved] = []
        self.functions: list[Function] = []
        self.calls: list[Call] = []
        self.gaps: list[Gap] = []
        self.scopes: list[_Scope] = []
        self.records: dict[str, _Record] = {}
        self._type_impl_traits: dict[
            str, list[tuple[str, str | None, bool, frozenset[str]]]
        ] = {}
        self.current_function = ""
        self.call_owner = ""
        self.module_depth = 0
        self.in_extern = False
        self._function_records: dict[str, _Record] = {}

    def span(self, node: Any) -> ByteSpan:
        return ByteSpan(node.start_byte, node.end_byte)

    def text(self, node: Any | None) -> str:
        if node is None:
            return ""
        return self.raw[node.start_byte : node.end_byte].decode("utf-8")

    @staticmethod
    def _normalize_identifier(name: str) -> str:
        return "::".join(
            part[2:] if part.startswith("r#") else part
            for part in name.split("::")
        )

    def build(self) -> LexicalBindingReport:
        root_scope = _Scope(self.root, 0, "")
        self.scopes.append(root_scope)
        self._scan_attributes()
        self._predeclare(self.root, root_scope)
        self._scan_container(self.root, root_scope)
        return LexicalBindingReport(
            PROFILE,
            self.source_hash,
            {"pointer_width": self.pointer_width},
            tuple(self.bindings),
            tuple(self.references),
            tuple(self.unresolved),
            tuple(self.functions),
            tuple(self.calls),
            tuple(self.gaps),
        )

    def _scan_attributes(self) -> None:
        for node in self._descendants(self.root):
            if node.type not in {"attribute_item", "inner_attribute_item"}:
                continue
            attribute = next(
                (child for child in node.named_children if child.type == "attribute"),
                None,
            )
            text = "" if attribute is None else self.text(attribute).strip()
            match = _ATTRIBUTE_PATH.match(text)
            path = "" if match is None else match.group(1)
            if path in {"cfg", "cfg_attr"}:
                self.gaps.append(Gap("conditional_compilation", self.span(node)))
            elif path == "derive":
                arguments = _DERIVE_ARGUMENTS.fullmatch(text)
                derives = (
                    []
                    if arguments is None
                    else [part.strip() for part in arguments.group(1).split(",") if part.strip()]
                )
                if not derives or not all(self._is_std_derive(name) for name in derives):
                    self.gaps.append(Gap("macro_invocation", self.span(node)))
            elif (
                path not in _INERT_ATTRIBUTES
                and not path.startswith("clippy::")
                and not path.startswith("rustfmt::")
            ):
                self.gaps.append(Gap("macro_invocation", self.span(node)))

    @staticmethod
    def _is_std_derive(path: str) -> bool:
        parts = path.split("::")
        if len(parts) == 1:
            return parts[0] in _DERIVE_TRAITS
        return parts[0] in {"std", "core"} and parts[-1] in _DERIVE_TRAITS

    def _make_record(
        self,
        name_node: Any,
        kind: str,
        scope: ByteSpan | None,
        owner: str | None,
        module_depth: int,
        *,
        item: bool,
        type_fact: TypeFact = _UNKNOWN,
        mutable: bool = False,
        alias_node: Any = None,
        body_node: Any = None,
        generic: bool = False,
        is_async: bool = False,
        variadic: bool = False,
        extern: bool = False,
        struct_constructor: bool = False,
        name_override: str | None = None,
        generic_kind: str = "",
        type_node: Any = None,
    ) -> _Record:
        name = self._normalize_identifier(
            self.text(name_node) if name_override is None else name_override
        )
        declaration = self.span(name_node)
        scope_start = 0 if scope is None else scope.start
        scope_end = 0 if scope is None else scope.end
        identifier = binding_id(
            self.source_hash, declaration.start, scope_start, scope_end
        )
        binding = Binding(
            identifier,
            name,
            kind,
            declaration,
            scope,
            type_fact,
            mutable,
        )
        record = _Record(
            binding,
            owner,
            module_depth,
            item,
            alias_node,
            body_node,
            generic,
            is_async,
            variadic,
            extern,
            struct_constructor,
            generic_kind,
            type_node,
        )
        self.bindings.append(binding)
        self.records[identifier] = record
        return record

    def _add_to_scope(self, scope: _Scope, record: _Record) -> None:
        scope.bindings.setdefault(record.binding.name, []).append(record)

    def _item_name(self, node: Any) -> Any | None:
        named = node.child_by_field_name("name")
        if named is not None:
            return named
        for child in node.named_children:
            if child.type in {"identifier", "type_identifier"}:
                return child
        return None

    def _predeclare(self, container: Any, scope: _Scope) -> None:
        for node in container.named_children:
            kind = _ITEM_KINDS.get(node.type)
            if kind is not None:
                name_node = self._item_name(node)
                if node.type == "use_declaration":
                    continue
                if name_node is None:
                    continue
                body = node.child_by_field_name("body")
                if node.type == "function_item":
                    body = node.child_by_field_name("body")
                generic = self._is_generic_function(node)
                signature = self.text(node)
                is_async = _has_keyword(signature[: signature.find("fn")], "async")
                variadic = any(c.type == "variadic_parameter" for c in self._descendants(node.child_by_field_name("parameters")))
                extern = self.in_extern or (node.type == "function_item" and body is None)
                constructor = node.type == "struct_item"
                if constructor:
                    struct_body = node.child_by_field_name("body")
                    constructor = (
                        struct_body is None
                        or struct_body.type == "ordered_field_declaration_list"
                    )
                record = self._make_record(
                    name_node,
                    kind,
                    self.span(container) if container.type != "source_file" else ByteSpan(0, 0),
                    scope.function_id,
                    scope.module_depth,
                    item=True,
                    body_node=body,
                    generic=generic,
                    is_async=is_async,
                    variadic=variadic,
                    extern=extern,
                    struct_constructor=constructor,
                    # `fn mk() -> W<i32>` keeps its return annotation —
                    # result-type inference reads it for receivers like
                    # `mk().n()`.
                    type_node=(
                        node.child_by_field_name("return_type")
                        if kind == "function"
                        else None
                    ),
                )
                self._add_to_scope(scope, record)
                if kind == "function":
                    self._function_records[record.binding.id] = record
                if kind == "type_alias":
                    record.alias_node = node.child_by_field_name("type")
                if node.type == "mod_item" and body is not None:
                    # Module contents are items too — predeclare them so
                    # `m::P` resolves before `mod m` is scanned, like a
                    # top-level item does.
                    child_scope = _Scope(
                        body, scope.module_depth + 1, scope.function_id
                    )
                    record.module_scope = child_scope
                    self._predeclare(body, child_scope)
                self._add_generic_parameters(
                    node,
                    scope,
                    owner_function=(
                        record.binding.id
                        if kind == "function"
                        else None
                        if node.type == "trait_item"
                        else scope.function_id
                    ),
                    inherit_scope_function=node.type != "trait_item",
                )
            elif node.type == "impl_item":
                self._add_generic_parameters(
                    node, scope, inherit_scope_function=False
                )
            elif node.type in {"extern_block", "foreign_mod_item"}:
                body = node.child_by_field_name("body")
                if body is None:
                    body = next(
                    (child for child in node.named_children if child.type == "declaration_list"),
                    None,
                )
                if body is not None:
                    for function_node in body.named_children:
                        if function_node.type not in {"function_item", "function_signature_item"}:
                            continue
                        name_node = self._item_name(function_node)
                        if name_node is None:
                            continue
                        fn_record = self._make_record(
                            name_node,
                            "function",
                            self.span(container) if container.type != "source_file" else ByteSpan(0, 0),
                            scope.function_id,
                            scope.module_depth,
                            item=True,
                            body_node=function_node.child_by_field_name("body"),
                            generic=self._is_generic_function(function_node),
                            variadic=any(
                                child.type == "variadic_parameter"
                                for child in self._descendants(
                                    function_node.child_by_field_name("parameters")
                                )
                            ),
                            extern=True,
                        )
                        self._add_to_scope(scope, fn_record)
                        self._function_records[fn_record.binding.id] = fn_record
                        self._add_generic_parameters(
                            function_node,
                            scope,
                            owner_function=fn_record.binding.id,
                        )
            elif node.type == "use_declaration":
                self._predeclare_use(node, scope)
            elif node.type == "macro_definition":
                self.gaps.append(Gap("macro_definition", self.span(node)))
        self._finalize_generic_type_facts(scope)

    def _finalize_generic_type_facts(self, scope: _Scope) -> None:
        for records in scope.bindings.values():
            for record in records:
                if (
                    record.binding.kind != "generic_parameter"
                    or record.generic_kind != "const"
                    or record.type_node is None
                ):
                    continue
                type_fact = self._type_fact(record.type_node)
                if type_fact == record.binding.type:
                    continue
                updated = replace(record.binding, type=type_fact)
                self.bindings[self.bindings.index(record.binding)] = updated
                record.binding = updated

    def _descendants(self, node: Any | None):
        if node is None:
            return
        stack = [node]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(reversed(self._children(current)))

    @staticmethod
    def _children(node: Any) -> tuple[Any, ...]:
        return tuple(
            child
            for child in node.named_children
            if child.type not in {"line_comment", "block_comment"}
        )

    def _is_generic_function(self, node: Any) -> bool:
        if node.child_by_field_name("type_parameters") is not None:
            return True
        parameters = node.child_by_field_name("parameters")
        return any(
            candidate.type == "abstract_type"
            for candidate in self._descendants(parameters)
        )

    def _predeclare_use(self, node: Any, scope: _Scope) -> None:
        for name_node, is_glob, bound_name in self._use_names(node):
            if is_glob:
                scope.glob_import = True
                self.gaps.append(Gap("glob_import", self.span(node)))
                continue
            record = self._make_record(
                name_node,
                "import",
                self.span(scope.node) if scope.node.type != "source_file" else ByteSpan(0, 0),
                scope.function_id,
                scope.module_depth,
                item=True,
                name_override=bound_name,
            )
            self._add_to_scope(scope, record)

    def _add_generic_parameters(
        self,
        node: Any,
        scope: _Scope,
        *,
        owner_function: str | None = None,
        inherit_scope_function: bool = True,
    ) -> None:
        parameters = node.child_by_field_name("type_parameters")
        if parameters is None:
            return
        item_scope = self.span(node)
        for parameter in self._children(parameters):
            if parameter.type not in {
                "type_parameter",
                "lifetime_parameter",
                "const_parameter",
            }:
                continue
            generic_kind = {
                "type_parameter": "type",
                "lifetime_parameter": "lifetime",
                "const_parameter": "const",
            }[parameter.type]
            name_node = parameter.child_by_field_name("name")
            if name_node is None:
                continue
            annotation = (
                parameter.child_by_field_name("type")
                if generic_kind == "const"
                else None
            )
            record = self._make_record(
                name_node,
                "generic_parameter",
                item_scope,
                (
                    scope.function_id
                    if owner_function is None and inherit_scope_function
                    else owner_function
                ),
                scope.module_depth,
                item=False,
                generic_kind=generic_kind,
                type_node=annotation,
            )
            self._add_to_scope(scope, record)

    def _add_higher_ranked_lifetimes(self, node: Any) -> None:
        if node.type == "higher_ranked_trait_bound":
            parameters = node.child_by_field_name("type_parameters")
            binder_scope = self.span(node)
            parent = node.parent
            if (
                parent is not None
                and parent.type == "where_predicate"
                and parent.child_by_field_name("left") == node
            ):
                binder_scope = self.span(parent)
        elif node.type == "function_type":
            parameters = next(
                (
                    child
                    for child in self._children(node)
                    if child.type == "for_lifetimes"
                ),
                None,
            )
            binder_scope = self.span(node)
        else:
            return
        if parameters is None or not self.scopes:
            return
        scope = self.scopes[-1]
        for parameter in self._children(parameters):
            name_node = (
                parameter.child_by_field_name("name")
                if parameter.type == "lifetime_parameter"
                else parameter
                if parameter.type == "lifetime"
                else None
            )
            if name_node is None:
                continue
            name = self._normalize_identifier(self.text(name_node))
            if any(
                record.binding.kind == "generic_parameter"
                and record.binding.span == self.span(name_node)
                and record.binding.scope == binder_scope
                for record in scope.bindings.get(name, ())
            ):
                continue
            record = self._make_record(
                name_node,
                "generic_parameter",
                binder_scope,
                self.current_function or None,
                scope.module_depth,
                item=False,
                generic_kind="lifetime",
            )
            self._add_to_scope(scope, record)

    def _generic_references(
        self, node: Any | None, *, skip_nested_items: bool = False
    ) -> None:
        if node is None:
            return
        candidates = []
        stack = [node]
        while stack:
            candidate = stack.pop()
            if (
                skip_nested_items
                and candidate is not node
                and candidate.type
                in {"function_item", "function_signature_item"}
            ):
                continue
            self._add_higher_ranked_lifetimes(candidate)
            if candidate.type in {"scoped_identifier", "scoped_type_identifier"}:
                self._record_qualified_path(candidate)
                continue
            if candidate.type == "type_arguments":
                for child in reversed(self._children(candidate)):
                    if child.type in {"identifier", "type_identifier"}:
                        self._generic_argument_reference(child)
                    else:
                        stack.append(child)
                continue
            candidates.append(candidate)
            stack.extend(reversed(self._children(candidate)))
        for candidate in candidates:
            if candidate.type in {"type_identifier", "lifetime"}:
                namespace = "type"
            elif candidate.type == "identifier":
                namespace = "value"
            else:
                continue
            record, boundary = self._lookup_with_boundary(
                self.text(candidate), candidate.start_byte, namespace
            )
            if record is None and boundary == "item_boundary":
                unresolved = Unresolved(
                    self.span(candidate),
                    self._normalize_identifier(self.text(candidate)),
                    "item_boundary",
                )
                if unresolved not in self.unresolved:
                    self.unresolved.append(unresolved)
                continue
            if (
                record is None
                or record.binding.kind != "generic_parameter"
                or record.binding.span == self.span(candidate)
            ):
                continue
            reference = Reference(self.span(candidate), record.binding.id, "read")
            if reference not in self.references:
                self.references.append(reference)

    def _generic_argument_reference(self, node: Any) -> None:
        name = self._normalize_identifier(self.text(node))
        type_record, type_boundary = self._lookup_with_boundary(
            name, node.start_byte, "type"
        )
        if type_record is not None:
            record = type_record
        elif type_boundary is None and name not in _PRELUDE_TYPE_NAMES:
            value_record, value_boundary = self._lookup_with_boundary(
                name, node.start_byte, "value"
            )
            if value_record is not None and (
                value_record.binding.kind in {"const", "import"}
                or (
                    value_record.binding.kind == "generic_parameter"
                    and value_record.generic_kind == "const"
                )
            ):
                record = value_record
            else:
                reason = type_boundary or value_boundary or (
                    "prelude_name" if name in _PRELUDE_NAMES else "unknown_name"
                )
                unresolved = Unresolved(self.span(node), name, reason)
                if unresolved not in self.unresolved:
                    self.unresolved.append(unresolved)
                return
        else:
            value_boundary = None
            record = None
        if record is None:
            reason = type_boundary or value_boundary or (
                "prelude_name" if name in _PRELUDE_NAMES else "unknown_name"
            )
            unresolved = Unresolved(self.span(node), name, reason)
            if unresolved not in self.unresolved:
                self.unresolved.append(unresolved)
            return
        reference = Reference(self.span(node), record.binding.id, "read")
        if reference not in self.references:
            self.references.append(reference)

    def _record_macro_invocations(self, node: Any | None) -> None:
        for candidate in self._descendants(node):
            if candidate.type != "macro_invocation":
                continue
            gap = Gap("macro_invocation", self.span(candidate))
            if gap not in self.gaps:
                self.gaps.append(gap)

    def _use_names(self, node: Any) -> list[tuple[Any, bool, str | None]]:
        out: list[tuple[Any, bool, str | None]] = []

        def add_leaf(tree: Any, prefix: tuple[str, ...] = ()) -> None:
            if tree.type == "use_list":
                for child in tree.named_children:
                    add_leaf(child, prefix)
            elif tree.type == "scoped_use_list":
                path = tree.child_by_field_name("path")
                child_list = next((c for c in tree.named_children if c.type == "use_list"), None)
                new_prefix = prefix + tuple(
                    part for part in self.text(path).split("::") if part
                )
                if child_list is not None:
                    add_leaf(child_list, new_prefix)
            elif tree.type == "use_as_clause":
                alias = tree.child_by_field_name("alias")
                if alias is not None:
                    out.append((alias, False, self.text(alias)))
            elif tree.type in {"use_wildcard", "wildcard_pattern"} or self.text(tree).endswith("*"):
                out.append((tree, True, None))
            elif tree.type == "self":
                out.append((tree, False, prefix[-1] if prefix else "self"))
            else:
                candidates = [
                    child for child in self._descendants(tree)
                    if child.type in {"identifier", "type_identifier", "self"}
                ]
                if candidates:
                    picked = candidates[-1]
                    final = self.text(picked)
                    if final == "self":
                        final = prefix[-1] if prefix else "self"
                    out.append((picked, False, final))

        for child in node.named_children:
            add_leaf(child)
        if not out and "::" in self.text(node):
            candidate = next(
                (c for c in self._descendants(node) if c.type in {"identifier", "type_identifier"}),
                None,
            )
            if candidate is not None:
                out.append((candidate, False, self.text(candidate)))
        return out

    def _scan_container(self, container: Any, scope: _Scope) -> None:
        for node in container.named_children:
            if node.type in {"attribute_item", "inner_attribute_item", "line_comment", "block_comment"}:
                continue
            if node.type in _ITEM_KINDS or node.type in {
                "use_declaration", "macro_definition", "extern_block", "foreign_mod_item",
                "impl_item",
            }:
                self._scan_item(node, scope)
            elif node.type == "expression_statement":
                self._expr(node)
            elif node.type in {"let_declaration"}:
                self._let(node, scope)
            else:
                self._expr(node)

    def _scan_item(self, node: Any, scope: _Scope) -> None:
        self._record_macro_invocations(node)
        if node.type == "macro_definition":
            return
        if node.type == "use_declaration":
            return
        if node.type == "function_item":
            record = self._find_item_record(scope, node)
            if record is not None:
                self._function(node, record)
            return
        if node.type in {"const_item", "static_item"}:
            value = node.child_by_field_name("value")
            if value is not None:
                old_owner = self.call_owner
                self.call_owner = ""
                self._expr(value)
                self.call_owner = old_owner
            self._assign_item_type(node, scope)
            return
        if node.type == "mod_item":
            body = node.child_by_field_name("body")
            if body is not None:
                self.module_depth += 1
                record = self._find_item_record(scope, node)
                child_scope = (
                    record.module_scope
                    if record is not None
                    and record.module_scope is not None
                    else _Scope(
                        body, self.module_depth, self.current_function
                    )
                )
                if record is not None:
                    record.module_scope = child_scope
                self.scopes.append(child_scope)
                # Items inside were already predeclared with the
                # module's own record — only expressions need the walk.
                self._scan_container(body, child_scope)
                self.scopes.pop()
                self.module_depth -= 1
            return
        if node.type in {"impl_item", "trait_item"}:
            body = node.child_by_field_name("body")
            old_function, old_owner = self.current_function, self.call_owner
            old_extern = self.in_extern
            self.current_function = ""
            self.call_owner = ""
            try:
                self._generic_references(node.child_by_field_name("type_parameters"))
                self._generic_references(self._where_clause(node))
                member_of = None
                member_args = None
                member_generic = False
                member_trait = None
                member_trait_args = None
                member_type_node = None
                if node.type == "trait_item":
                    # Key a trait's own members to the trait so impls
                    # without an override fall back to the trait's
                    # default member (`trait T { fn m(&self) {} }`).
                    trait_record = self._find_item_record(scope, node)
                    if trait_record is not None:
                        member_of = trait_record.binding.id
                        member_trait = trait_record.binding.id
                elif node.type == "impl_item":
                    self._generic_references(node.child_by_field_name("type"))
                    trait_node = node.child_by_field_name("trait")
                    member_type_node = node.child_by_field_name("type")
                    member_of, member_args = self._annotation_type(
                        member_type_node
                    )
                    member_generic = (
                        node.child_by_field_name("type_parameters")
                        is not None
                    )
                    if trait_node is not None:
                        member_trait, member_trait_args = (
                            self._annotation_type(trait_node)
                        )
                        if member_trait is None:
                            # `impl path::Tr for T` — the scoped trait is
                            # not resolvable here; its members attach to
                            # the type but never resolve as methods.
                            member_trait = "<unresolved>"
                        elif member_of is not None:
                            # Record the `impl T for <type>` edge even
                            # when the impl block is empty, so the
                            # trait's default members can apply. The
                            # specialization args matter: `impl T for
                            # W<i32>` does not implement T for `W<u32>`,
                            # and a generic `impl<A> T for W<A, i32>`
                            # only covers receivers whose concrete args
                            # match every non-parameter position.
                            type_params = node.child_by_field_name(
                                "type_parameters"
                            )
                            self._type_impl_traits.setdefault(
                                member_of, []
                            ).append(
                                (
                                    member_trait,
                                    member_args,
                                    member_generic,
                                    frozenset(
                                        self._normalize_identifier(
                                            self.text(
                                                child.child_by_field_name(
                                                    "name"
                                                )
                                            )
                                        )
                                        for child in (
                                            ()
                                            if type_params is None
                                            else type_params.named_children
                                        )
                                        if child.type
                                        in {
                                            "type_parameter",
                                            "const_parameter",
                                            "lifetime_parameter",
                                        }
                                        and child.child_by_field_name(
                                            "name"
                                        )
                                        is not None
                                    ),
                                )
                            )
                if body is not None:
                    self._scan_associated_container(
                        body,
                        scope,
                        self.span(node),
                        member_of,
                        member_args,
                        member_generic,
                        member_trait,
                        member_trait_args,
                        member_type_node,
                    )
            finally:
                self.in_extern = old_extern
                self.current_function = old_function
                self.call_owner = old_owner
            return
        if node.type in {"extern_block", "foreign_mod_item"}:
            body = node.child_by_field_name("body")
            if body is None:
                body = next((c for c in node.named_children if c.type == "declaration_list"), None)
            if body is not None:
                self._scan_extern_container(body, scope)
            return
        if node.type == "type_item":
            self._assign_item_type(node, scope)
            self._generic_references(node)
            return
        if node.type in {"struct_item", "enum_item", "union_item"}:
            self._generic_references(node)
            if node.type in {"struct_item", "union_item"}:
                self._link_fields(node, scope)
            elif node.type == "enum_item":
                self._link_variants(node, scope)
            return
        if node.type == "trait_item":
            return

    def _find_item_record(self, scope: _Scope, node: Any) -> _Record | None:
        name_node = self._item_name(node)
        if name_node is None:
            return None
        name = self._normalize_identifier(self.text(name_node))
        return next(
            (r for r in scope.bindings.get(name, ()) if r.binding.span == self.span(name_node)),
            None,
        )

    def _where_clause(self, node: Any) -> Any | None:
        return next(
            (child for child in self._children(node) if child.type == "where_clause"),
            None,
        )

    @staticmethod
    def _type_arg_list(args: str) -> list[str]:
        """Top-level comma split of a type-argument key — commas
        inside `(...)`, `[...]` or `<...>` stay inside their arg."""
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in args:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth <= 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)
        parts.append("".join(current))
        return [part.strip() for part in parts]

    def _type_arg_match(
        self,
        pattern: str,
        concrete: str,
        params: frozenset[str],
        bindings: dict[str, str],
    ) -> bool:
        """Does impl-side arg `pattern` cover receiver arg `concrete`?

        Positions spelled with an impl parameter are wildcards —
        every occurrence of one parameter must bind the same arg, so
        `W<(A,A)>` covers `W<(u8,u8)>` but not `W<(u8,u16)>`. Other
        positions must match structurally — `Vec<A>` covers `Vec<u8>`.
        Reference mutability is significant (`&mut u8` is not `&u8`);
        lifetimes are ignored: they never change which methods a type
        provides."""
        a = pattern.strip().strip("{}").strip()
        b = concrete.strip().strip("{}").strip()
        if a in params:
            bound = bindings.get(a)
            # Lifetimes are erased for consistency — `&'a u8` and
            # `&'b u8` bind the same parameter.
            normalized = re.sub(r"'\w+(?!')", "", b).replace(" ", "")
            if bound is None:
                bindings[a] = normalized
                return True
            return bound == normalized
        ref_a = re.fullmatch(
            r"&\s*(?:'\w+\s*)?(mut(?![\w']))?\s*(.+)", a
        )
        ref_b = re.fullmatch(
            r"&\s*(?:'\w+\s*)?(mut(?![\w']))?\s*(.+)", b
        )
        if (ref_a is None) != (ref_b is None):
            return False
        if ref_a is not None:
            if bool(ref_a.group(1)) != bool(ref_b.group(1)):
                return False
            return self._type_arg_match(
                ref_a.group(2), ref_b.group(2), params, bindings
            )
        if a.startswith("(") and a.endswith(")"):
            if not (b.startswith("(") and b.endswith(")")):
                return False
            sub_a = self._type_arg_list(a[1:-1])
            sub_b = self._type_arg_list(b[1:-1])
            return len(sub_a) == len(sub_b) and all(
                self._type_arg_match(x, y, params, bindings)
                for x, y in zip(sub_a, sub_b)
            )
        match_a = re.fullmatch(r"(.+?)\s*<(.+)>", a)
        match_b = re.fullmatch(r"(.+?)\s*<(.+)>", b)
        if (match_a is None) != (match_b is None):
            return False
        if match_a is not None:
            if match_a.group(1).replace(" ", "") != match_b.group(
                1
            ).replace(" ", ""):
                return False
            sub_a = self._type_arg_list(match_a.group(2))
            sub_b = self._type_arg_list(match_b.group(2))
            return len(sub_a) == len(sub_b) and all(
                self._type_arg_match(x, y, params, bindings)
                for x, y in zip(sub_a, sub_b)
            )
        return a.replace(" ", "") == b.replace(" ", "")

    def _type_args_match(
        self, a: str | None, b: str | None, params: frozenset[str]
    ) -> bool:
        """Positional structural equality of two type-argument keys
        — `W<(u8,u16)>` and `W<(u8, u16)>` are the same type."""
        if (a is None) != (b is None):
            return False
        if a is None:
            return True
        parts_a = self._type_arg_list(a)
        parts_b = self._type_arg_list(b)
        bindings: dict[str, str] = {}
        return len(parts_a) == len(parts_b) and all(
            self._type_arg_match(x, y, params, bindings)
            for x, y in zip(parts_a, parts_b)
        )

    def _type_args_key(self, args_node: Any | None) -> str | None:
        """Normalized `Wrap<i32>`-style type-argument text."""
        if args_node is None:
            return None
        return ",".join(
            re.sub(r"\s+", " ", self.text(child)).strip()
            for child in self._children(args_node)
        )

    def _annotation_type(
        self, node: Any
    ) -> tuple[str | None, str | None]:
        """(binding id, generic-args key) a type annotation refers to.

        Unwraps `&T`/`&mut T` references, `-> T` return types and
        `Name<Args>` generics; names resolve at the annotation's own
        position so a later same-named declaration cannot shadow them."""
        args = None
        while node is not None and node.type in {
            "reference_type",
            "generic_type",
            "generic_type_with_turbofish",
            "return_type",
        }:
            if node.type in {"generic_type", "generic_type_with_turbofish"}:
                key = self._type_args_key(
                    node.child_by_field_name("type_arguments")
                )
                if key is not None:
                    args = key
            node = node.child_by_field_name("type")
        if node is not None and node.type in {
            "slice_type",
            "array_type",
        }:
            # Index receivers read the element type out of `args` —
            # `[P]` and `[P; N]` both expose `P`.
            element = node.child_by_field_name("element")
            if element is None:
                return None, None
            return None, re.sub(
                r"\s+", " ", self.text(element)
            ).strip()
        if node is not None and node.type == "scoped_type_identifier":
            # `m::W<i32>` keeps its own type arguments — the scoped
            # node's field takes them when the loop did not.
            scoped_args = self._type_args_key(
                node.child_by_field_name("type_arguments")
            )
            if scoped_args is not None:
                args = scoped_args
            record = self._scoped_type(node)
            if record is not None and record.binding.kind == "import":
                record = self._lookup(
                    record.binding.name, node.start_byte, "type"
                ) or record
            if (
                record is not None
                and record.binding.name in {"HashMap", "BTreeMap"}
                and args is not None
            ):
                parts = self._type_arg_list(args)
                args = parts[-1] if parts else None
            return (None if record is None else record.binding.id), args
        if node is None or node.type != "type_identifier":
            return None, None
        record = self._lookup(
            self._normalize_identifier(self.text(node)),
            node.start_byte,
            "type",
        )
        name = self._normalize_identifier(self.text(node))
        if name in {"HashMap", "BTreeMap"} and args is not None:
            # A std map indexes to its value type — `m[k]` : V, not
            # the key-value pair. Applies whether the name resolves
            # (e.g. imported) or stays unresolved.
            parts = self._type_arg_list(args)
            args = parts[-1] if parts else None
        return (None if record is None else record.binding.id), args

    def _lookup_module(self, name: str, position: int) -> "_Record | None":
        name = self._normalize_identifier(name)
        for scope in reversed(self.scopes):
            for record in reversed(scope.bindings.get(name, ())):
                if record.binding.kind != "module":
                    continue
                if (
                    record.binding.scope is not None
                    and record.binding.scope != ByteSpan(0, 0)
                    and not (
                        record.binding.scope.start
                        <= position
                        < record.binding.scope.end
                    )
                ):
                    continue
                return record
        return None

    def _scoped_type(self, node: Any) -> "_Record | None":
        """Record for `m::T` — walks each module segment's body scope."""
        path = node.child_by_field_name("path")
        name = node.child_by_field_name("name")
        if path is None or name is None or name.type not in {
            "identifier",
            "type_identifier",
        }:
            return None
        module = None
        if path.type in {"identifier", "type_identifier"}:
            module = self._lookup_module(self.text(path), path.start_byte)
        elif path.type in {"scoped_identifier", "scoped_type_identifier"}:
            nested = self._scoped_type(path)
            if nested is not None and nested.binding.kind == "module":
                module = nested
        if module is None or module.module_scope is None:
            return None
        for record in reversed(
            module.module_scope.bindings.get(
                self._normalize_identifier(self.text(name)), ()
            )
        ):
            if record.binding.kind in {
                "struct",
                "enum",
                "union",
                "type_alias",
                "trait",
                "module",
            }:
                return record
        return None

    def _link_fields(self, node: Any, scope: _Scope) -> None:
        """Attach named struct/union fields as member bindings."""
        record = self._find_item_record(scope, node)
        body = node.child_by_field_name("body")
        if (
            record is None
            or body is None
            or body.type != "field_declaration_list"
        ):
            return
        for field_node in self._children(body):
            if field_node.type != "field_declaration":
                continue
            name_node = field_node.child_by_field_name("name")
            if name_node is None:
                continue
            annotation = field_node.child_by_field_name("type")
            member = self._make_record(
                name_node,
                "struct_field",
                self.span(node),
                scope.function_id,
                scope.module_depth,
                item=True,
                type_fact=(
                    _UNKNOWN
                    if annotation is None
                    else self._type_fact(annotation)
                ),
                type_node=annotation,
            )
            member.member_of = record.binding.id

    def _link_variants(self, node: Any, scope: _Scope) -> None:
        """Attach enum variants as member bindings."""
        record = self._find_item_record(scope, node)
        body = node.child_by_field_name("body")
        if record is None or body is None:
            return
        for variant in self._children(body):
            if variant.type != "enum_variant":
                continue
            name_node = variant.child_by_field_name("name")
            if name_node is None:
                continue
            member = self._make_record(
                name_node,
                "enum_member",
                self.span(node),
                scope.function_id,
                scope.module_depth,
                item=True,
            )
            member.member_of = record.binding.id
            value = variant.child_by_field_name("value")
            if value is not None:
                self._expr(value)

    def _scoped_member(self, node: Any) -> tuple[Any | None, Any | None]:
        """Member record + name node of a `Path::name` segment pair.

        Only resolves when the path names a type reachable here —
        `P::new` or `W<i32>::new` — deeper `m::P::new` paths stay
        unresolved."""
        path = node.child_by_field_name("path")
        name = node.child_by_field_name("name")
        if path is None or name is None:
            return None, name
        if path.type == "generic_type":
            type_id, args = self._annotation_type(path)
        elif path.type in {"identifier", "type_identifier"}:
            record = self._lookup(
                self._normalize_identifier(self.text(path)),
                path.start_byte,
                "type",
            )
            type_id, args = (None if record is None else record.binding.id), None
        elif path.type in {"scoped_identifier", "scoped_type_identifier"}:
            record = self._scoped_type(path)
            type_id, args = (None if record is None else record.binding.id), None
        elif path.type == "bracketed_type":
            qualified = next(
                (
                    child
                    for child in self._children(path)
                    if child.type == "qualified_type"
                ),
                None,
            )
            if qualified is None:
                # `<P>::m` — bare qualified path, same member pool as
                # `P::m`.
                inner = next(iter(self._children(path)), None)
                type_id, args = self._annotation_type(inner)
                member = self._member_record(
                    type_id,
                    self._normalize_identifier(self.text(name)),
                    (
                        "associated_function",
                        "associated_const",
                        "enum_member",
                    ),
                    args,
                    node.start_byte,
                )
                return member, name
            type_id, args = self._annotation_type(
                qualified.child_by_field_name("type")
            )
            trait_node = qualified.child_by_field_name("alias")
            member = self._ufcs_member(
                type_id,
                self._normalize_identifier(self.text(name)),
                trait_node,
                args,
                node.start_byte,
            )
            return member, name
        else:
            return None, name
        if type_id is None:
            return None, name
        member = self._member_record(
            type_id,
            self._normalize_identifier(self.text(name)),
            ("associated_function", "associated_const", "enum_member"),
            impl_args=args,
            position=node.start_byte,
        )
        return member, name

    def _member_record(
        self,
        type_id: str | None,
        name: str,
        kinds: tuple[str, ...] = (),
        impl_args: str | None = None,
        position: int | None = None,
    ) -> _Record | None:
        """Member `name` of the type `type_id`.

        `kinds` prefers e.g. `struct_field` for field access or
        `associated_function` for calls when both spellings exist.
        Members of a concrete specialization impl (`impl Wrap<i32>`)
        only apply to receivers annotated with the same arguments.
        Inherent impl members win; trait-impl members apply only when
        the trait itself resolves at the access site — an out-of-scope
        trait's methods do not."""
        if type_id is None:
            return None

        def args_match(record: _Record) -> bool:
            if (
                record.member_impl_args is not None
                and not record.member_impl_generic
                and not self._type_args_match(
                    record.member_impl_args, impl_args, frozenset()
                )
            ):
                return False
            return True

        def trait_in_scope(record: _Record) -> bool:
            if record.member_trait is None or position is None:
                return record.member_trait is None
            trait = self.records.get(record.member_trait)
            if trait is None:
                return False
            resolved = self._lookup(
                trait.binding.name, position, "type"
            )
            return resolved is trait

        pool = [
            record
            for record in self.records.values()
            if record.member_of == type_id
            and record.binding.name == name
            and args_match(record)
            and trait_in_scope(record)
        ]
        # Trait-declared defaults apply when an `impl T for <type>`
        # exists but does not spell `name` — they rank below both
        # inherent and trait-impl members of the type itself.
        impl_traits = self._type_impl_traits.get(type_id, ())
        if impl_traits:
            for (
                trait_id,
                edge_args,
                edge_generic,
                edge_params,
            ) in impl_traits:
                if edge_args is not None:
                    if not edge_generic:
                        if not self._type_args_match(
                            edge_args, impl_args, frozenset()
                        ):
                            continue
                    elif impl_args is not None:
                        # Generic impl (`impl<A> T for W<A, i32>`):
                        # parameter positions are wildcards, concrete
                        # positions must structurally equal the
                        # receiver's args — `W<(u8,u16)>` still matches
                        # `impl<A> T for W<A>` since the comma is
                        # nested inside the tuple.
                        edge_parts = self._type_arg_list(edge_args)
                        impl_parts = self._type_arg_list(impl_args)
                        bindings: dict[str, str] = {}
                        if len(edge_parts) != len(impl_parts) or any(
                            not self._type_arg_match(
                                edge, concrete, edge_params, bindings
                            )
                            for edge, concrete in zip(
                                edge_parts, impl_parts
                            )
                        ):
                            continue
                trait = self.records.get(trait_id)
                if trait is None:
                    continue
                resolved = self._lookup(
                    trait.binding.name, position, "type"
                )
                if resolved is not trait:
                    continue
                pool.extend(
                    record
                    for record in self.records.values()
                    if record.member_of == trait_id
                    and record.member_of != type_id
                    and record.binding.name == name
                    and args_match(record)
                )
        def tier(record: _Record) -> int:
            if record.member_trait is None:
                return 0
            if record.member_of == type_id:
                return 1
            return 2
        pool.sort(key=tier)
        candidates = (
            [record for record in pool if record.binding.kind in kinds]
            if kinds
            else pool
        )
        if not candidates:
            return None
        first = candidates[0]
        if tier(first) == 1:
            # More than one trait impl can spell `name` — Rust reports
            # ambiguity, so no single implementation is picked.
            if sum(1 for record in candidates if tier(record) == 1) > 1:
                return None
        elif tier(first) == 2:
            # Defaults from several in-scope traits are equally
            # ambiguous — and an impl member would have shadowed them.
            if sum(1 for record in candidates if tier(record) == 2) > 1:
                return None
        return first

    def _concrete_type_id(self, type_id: str | None) -> str | None:
        """Unwrap `type A = B` aliases to the aliased type's id."""
        seen = set()
        while type_id is not None and type_id not in seen:
            seen.add(type_id)
            record = self.records.get(type_id)
            if (
                record is None
                or record.binding.kind != "type_alias"
                or record.alias_node is None
            ):
                return type_id
            resolved, _ = self._annotation_type(record.alias_node)
            if resolved is None or resolved == type_id:
                return type_id
            type_id = resolved
        return type_id

    def _resolve_trait_node(self, trait_node: Any) -> "_Record | None":
        """Trait record for a UFCS `as` qualifier — plain, scoped
        (`m::T`) or generic (`T<A>`) spellings all resolve."""
        node = trait_node
        while node is not None and node.type in {
            "generic_type",
            "generic_type_with_turbofish",
            "return_type",
        }:
            node = node.child_by_field_name("type")
        if node is None:
            return None
        if node.type in {"scoped_identifier", "scoped_type_identifier"}:
            return self._scoped_type(node)
        return self._lookup(
            self._normalize_identifier(self.text(node)),
            node.start_byte,
            "type",
        )

    def _ufcs_member(
        self,
        type_id: str | None,
        name: str,
        trait_node: Any | None,
        impl_args: str | None,
        position: int,
    ) -> _Record | None:
        """Member picked by `<P as T>::name` UFCS syntax.

        With an `as` qualifier the spelling names the trait-impl member
        specifically — it only resolves when the trait record resolves at
        the access site. Without it (`<P>::m`) the member set is the same
        pool `P::m` would see."""
        if type_id is None:
            return None
        # `<A as T>::m` with `type A = P` looks up the impl on the
        # concrete type P — the alias only spells the receiver.
        type_id = self._concrete_type_id(type_id)
        if type_id is None:
            return None
        if trait_node is None:
            return self._member_record(
                type_id,
                name,
                ("associated_function", "associated_const", "enum_member"),
                impl_args,
                position,
            )
        trait = self._resolve_trait_node(trait_node)
        if trait is None:
            return None
        # `<P as T<u32>>::m` names a specific impl — `impl T<i32> for
        # P` must not answer for it.
        _, trait_args = self._annotation_type(trait_node)
        pool = [
            record
            for record in self.records.values()
            if record.member_of == type_id
            and record.binding.name == name
            and record.member_trait == trait.binding.id
            and (
                trait_args is None
                or record.member_trait_args == trait_args
            )
            and (
                record.member_impl_args is None
                or record.member_impl_generic
                or record.member_impl_args == impl_args
            )
        ]
        if not pool:
            # `<P as T>::m` falls back to the trait's default
            # implementation when the impl does not spell `m`.
            pool = [
                record
                for record in self.records.values()
                if record.member_of == trait.binding.id
                and record.member_trait == trait.binding.id
                and record.binding.name == name
            ]
        return pool[0] if pool else None

    def _field_member(
        self, node: Any, kinds: tuple[str, ...] = ()
    ) -> _Record | None:
        """Resolve `expr.name` member access against the declared type."""
        value = node.child_by_field_name("value")
        field_node = node.child_by_field_name("field")
        if field_node is None:
            return None
        name = self.text(field_node).strip()
        if not name or name[0].isdigit():
            # Tuple fields are positional; honest opaque.
            return None
        type_id, impl_args = self._receiver_type(value)
        return self._member_record(
            type_id, name, kinds, impl_args, node.start_byte
        )

    def _record_type(
        self, record: _Record, position: int
    ) -> tuple[str | None, str | None]:
        """(type id, generic-args key) declared for a binding."""
        annotated = self._annotation_type(record.type_node)
        if annotated[0] is not None or annotated[1] is not None:
            # An opaque container still carries its args (`v: Vec<P>` →
            # (None, "P")) — index receivers read the element type
            # from them.
            return annotated
        if record.binding.type is not None and record.binding.type.type_id:
            return record.binding.type.type_id, None
        if record.value_node is not None:
            return self._receiver_type(record.value_node)
        return None, None

    def _receiver_type(
        self, node: Any
    ) -> tuple[str | None, str | None]:
        """(type id, generic-args key) of a member-access receiver."""
        if node is None:
            return None, None
        if node.type in {"identifier", "self"}:
            record = self._lookup(
                self._normalize_identifier(self.text(node)),
                node.start_byte,
                "value",
            )
            if record is None:
                return None, None
            return self._record_type(record, node.start_byte)
        if node.type == "index_expression":
            # `v[i]` yields the element type — the collection's single
            # generic argument (`Vec<P>` → P). The element keeps its
            # own args so nested indexing stays typed (`Vec<Vec<P>>`).
            # Multi-arg containers and arrays stay honest opaque.
            children = node.named_children
            if not children:
                return None, None
            container_id, elem_args = self._receiver_type(children[0])
            if elem_args is None or "," in elem_args:
                return None, None
            elem_args = elem_args.strip()
            index = children[1] if len(children) > 1 else None
            if index is not None and index.type in {
                "range_expression",
                "range_pattern",
            }:
                # `v[a..b]` is a slice of the element, not the element
                # — encoded as an anonymous collection whose element
                # the next index can still unwrap. A call like
                # `v[f(0..10)]` keeps its integer index.
                return None, elem_args
            # A resolved container whose `Index::Output` is not its
            # generic argument (a custom `Wrapper<P>`) stays opaque —
            # only the known element-indexing collections apply.
            if container_id is not None:
                container_name = next(
                    (
                        b.name
                        for b in self.bindings
                        if b.id == container_id
                    ),
                    None,
                )
                if container_name not in _INDEX_ELEMENT_CONTAINERS:
                    return None, None
            # A slice or array element exposes its own element type —
            # `&[[P; 2]]` indexes first to `[P; 2]`, then to `P`.
            bracket = re.fullmatch(
                r"\[(.+?)(?:\s*;.+)?\]", elem_args
            )
            if bracket is not None:
                # The element is an anonymous slice/array — `v[i]` has
                # that anonymous type, indexed further by its own
                # element (`[P; 2]` → `P`), not `P` itself.
                return None, bracket.group(1).strip()
            match = re.fullmatch(
                r"([A-Za-z_][\w:]*)\s*(?:<(.+)>)?", elem_args
            )
            if match is None:
                # The element is a reference or composite type —
                # keep its text so deeper indexing still reads args.
                return None, elem_args
            elem = self._lookup(
                self._normalize_identifier(match.group(1)),
                node.start_byte,
                "type",
            )
            return (
                None if elem is None else elem.binding.id,
                match.group(2),
            )
        if node.type == "field_expression":
            member = self._field_member(
                node, ("struct_field", "associated_const")
            )
            if member is not None:
                return self._record_type(member, node.start_byte)
            element = self._tuple_element_node(
                node.child_by_field_name("value"),
                node.child_by_field_name("field"),
            )
            return self._annotation_type(element)
        if node.type == "call_expression":
            callee = node.child_by_field_name("function")
            callee = None if callee is None else self._callee(callee)
            if callee is not None and callee.type == "generic_function":
                callee = callee.child_by_field_name("function")
            member = None
            if callee is not None and callee.type == "field_expression":
                member = self._field_member(callee, ("associated_function",))
            elif callee is not None and callee.type in {
                "scoped_identifier",
                "scoped_type_identifier",
            }:
                member, _ = self._scoped_member(callee)
            elif callee is not None and callee.type == "identifier":
                member = self._lookup(
                    self._normalize_identifier(self.text(callee)),
                    node.start_byte,
                    "value",
                )
            if member is None:
                return None, None
            function = next(
                (
                    entry
                    for entry in self.functions
                    if entry.binding_id == member.binding.id
                ),
                None,
            )
            if function is None or function.result is None:
                return None, None
            if function.is_async:
                # `a.mk()` is a Future, not the output type — await is
                # required before `B`'s members apply.
                return None, None
            # The declaration's return annotation carries generic args
            # (`fn mk() -> W<i32>`) that the summary's type id drops.
            annotated = self._annotation_type(member.type_node)
            if annotated[0] is not None or annotated[1] is not None:
                return annotated
            if function.result.type_id:
                return function.result.type_id, None
            return annotated
        if node.type == "struct_expression":
            # `W<i32>{..}` keeps its type arguments — the annotation
            # walk reads them off the generic name node.
            return self._annotation_type(node.child_by_field_name("name"))
        if node.type == "parenthesized_expression":
            children = self._children(node)
            if len(children) == 1:
                return self._receiver_type(children[0])
        return None, None

    def _receiver_type_node(self, node: Any | None) -> Any | None:
        """Annotation node of the receiver's declared type, if any."""
        if node is None:
            return None
        if node.type in {"identifier", "self"}:
            record = self._lookup(
                self._normalize_identifier(self.text(node)),
                node.start_byte,
                "value",
            )
            return None if record is None else record.type_node
        if node.type == "field_expression":
            member = self._field_member(
                node, ("struct_field", "associated_const")
            )
            if member is not None:
                return member.type_node
            return self._tuple_element_node(
                node.child_by_field_name("value"),
                node.child_by_field_name("field"),
            )
        return None

    def _tuple_element_node(
        self, value_node: Any | None, field_node: Any | None
    ) -> Any | None:
        """Element annotation node of `value.index` on a tuple type.

        Tuple fields have no named member to bind, but the element's
        declared type still types member chains (`t.1.m()`)."""
        if field_node is None:
            return None
        text = self.text(field_node).strip()
        if not text.isdigit():
            return None
        type_node = self._receiver_type_node(value_node)
        while type_node is not None and type_node.type == "reference_type":
            type_node = type_node.child_by_field_name("type")
        if type_node is None or type_node.type != "tuple_type":
            return None
        elements = self._children(type_node)
        index = int(text)
        if index >= len(elements):
            return None
        return elements[index]

    @staticmethod
    def _member_call_kind(record: _Record) -> str:
        if record.extern or record.body_node is None:
            return "opaque_bodyless"
        if record.generic:
            return "opaque_generic"
        if record.is_async:
            return "opaque_async"
        return "direct_local"

    def _scan_associated_container(
        self,
        body: Any,
        parent_scope: _Scope,
        generic_scope: ByteSpan,
        member_of: str | None = None,
        member_impl_args: str | None = None,
        member_impl_generic: bool = False,
        member_trait: str | None = None,
        member_trait_args: str | None = None,
        member_type_node: Any = None,
    ) -> None:
        children = self._children(body)
        # Predeclare members so a body earlier in the block can call a
        # member declared later (`fn outer { self.inner() } fn inner`).
        predeclared: dict[int, _Record] = {}
        for node in children:
            if node.type in {"function_item", "function_signature_item"}:
                name_node = self._item_name(node)
                if name_node is None:
                    continue
                body_node = node.child_by_field_name("body")
                record = self._make_record(
                    name_node,
                    "associated_function",
                    None,
                    parent_scope.function_id,
                    parent_scope.module_depth,
                    item=True,
                    body_node=body_node,
                    generic=self._is_generic_function(node),
                    is_async=_has_keyword(
                        self.text(node)[: self.text(node).find("fn")], "async"
                    ),
                    extern=self.in_extern or body_node is None,
                    type_node=node.child_by_field_name("return_type"),
                )
                record.member_of = member_of
                record.member_impl_args = member_impl_args
                record.member_impl_generic = member_impl_generic
                record.member_trait = member_trait
                record.member_trait_args = member_trait_args
                record.self_type_node = member_type_node
                self._function_records[record.binding.id] = record
                predeclared[node.id] = record
            elif node.type == "const_item":
                name_node = self._item_name(node)
                if name_node is None:
                    continue
                annotation = node.child_by_field_name("type")
                const_record = self._make_record(
                    name_node, "associated_const", None,
                    parent_scope.function_id,
                    parent_scope.module_depth, item=True,
                    type_fact=_UNKNOWN
                    if annotation is None
                    else self._type_fact(annotation),
                    type_node=annotation,
                )
                const_record.member_of = member_of
                const_record.member_impl_args = member_impl_args
                const_record.member_impl_generic = member_impl_generic
                const_record.member_trait = member_trait
        for node in children:
            if node.type in {"function_item", "function_signature_item"}:
                record = predeclared.get(node.id)
                if record is None:
                    self.gaps.append(Gap("unsupported_syntax", self.span(node)))
                    continue
                self._add_generic_parameters(
                    node, parent_scope, owner_function=record.binding.id
                )
                self._finalize_generic_type_facts(parent_scope)
                self._function(
                    node, record, inherited_generic_scopes=(generic_scope,)
                )
            elif node.type == "const_item":
                value = node.child_by_field_name("value")
                if value is not None:
                    self._expr(value)
            elif node.type in {"macro_definition"}:
                self.gaps.append(Gap("macro_definition", self.span(node)))
            else:
                # Associated type declarations are names, not values, but are not
                # yet in the public item inventory.
                if node.type not in {"attribute_item", "line_comment"}:
                    self.gaps.append(Gap("unsupported_syntax", self.span(node)))

    def _scan_extern_container(self, body: Any, parent_scope: _Scope) -> None:
        for node in self._children(body):
            if node.type in {"function_item", "function_signature_item"}:
                record = self._find_item_record(parent_scope, node)
                if record is not None:
                    self._function(node, record)
            elif node.type not in {"attribute_item", "line_comment", "block_comment"}:
                self.gaps.append(Gap("unsupported_syntax", self.span(node)))

    def _assign_item_type(self, node: Any, scope: _Scope) -> None:
        name_node = self._item_name(node)
        if name_node is None:
            return
        record = self._find_item_record(scope, node)
        if record is None:
            return
        annotation = node.child_by_field_name("type")
        if annotation is not None:
            fact = self._type_fact(annotation)
            replacement = Binding(
                record.binding.id,
                record.binding.name,
                record.binding.kind,
                record.binding.span,
                record.binding.scope,
                fact,
                node.type == "static_item"
                and _has_keyword(self.text(node)[: self.text(node).find("=")], "mut"),
            )
            self.bindings[self.bindings.index(record.binding)] = replacement
            record.binding = replacement

    def _function(
        self,
        node: Any,
        record: _Record,
        *,
        inherited_generic_scopes: tuple[ByteSpan, ...] = (),
    ) -> None:
        old_function, old_call_owner = self.current_function, self.call_owner
        self.current_function = record.binding.id
        self.call_owner = record.binding.id
        body = node.child_by_field_name("body")
        body_span = None if body is None else self.span(body)
        parameter_ids: list[str] = []
        parameters = node.child_by_field_name("parameters")
        fn_scope = _Scope(
            body if body is not None else node,
            self.module_depth,
            record.binding.id,
        )
        self.scopes.append(fn_scope)
        inherited_generics: set[str] = set()
        for outer_scope in self.scopes[:-1]:
            for records in outer_scope.bindings.values():
                for generic in records:
                    if (
                        generic.binding.kind != "generic_parameter"
                        or (
                            generic.owner_function != record.binding.id
                            and generic.binding.scope not in inherited_generic_scopes
                        )
                        or generic.binding.id in inherited_generics
                        or generic.binding.scope is None
                        or not (
                            generic.binding.scope.start
                            <= node.start_byte
                            < generic.binding.scope.end
                        )
                    ):
                        continue
                    inherited_generics.add(generic.binding.id)
                    self._add_to_scope(
                        fn_scope,
                        replace(
                            generic,
                            owner_function=record.binding.id,
                            item=False,
                        ),
                    )
        self._generic_references(node.child_by_field_name("type_parameters"))
        if parameters is not None:
            for parameter in self._children(parameters):
                self._generic_references(parameter.child_by_field_name("type"))
        self._generic_references(node.child_by_field_name("return_type"))
        self._generic_references(self._where_clause(node))
        if body is not None:
            parameter_scope = self.span(body)
            if parameters is not None:
                for parameter in self._children(parameters):
                    parameter_ids.extend(
                        self._parameter(parameter, fn_scope, parameter_scope)
                    )
            if body.type == "block":
                self._predeclare(body, fn_scope)
                self._scan_container(body, fn_scope)
            else:
                self._expr(body)
        result_node = node.child_by_field_name("return_type")
        result = _UNKNOWN if result_node is None else self._type_fact(result_node)
        is_method = bool(parameter_ids and any(
            b.id == parameter_ids[0] and b.kind == "self_parameter" for b in self.bindings
        ))
        function = Function(
            record.binding.id,
            body_span,
            tuple(parameter_ids),
            result,
            record.generic,
            record.is_async,
            is_method,
            record.variadic,
        )
        self.functions.append(function)
        self.scopes.pop()
        self.current_function, self.call_owner = old_function, old_call_owner

    def _parameter(self, node: Any, scope: _Scope, body_span: ByteSpan) -> list[str]:
        if node.type == "self_parameter":
            self_node = next((c for c in self._descendants(node) if c.type == "self"), None)
            if self_node is None:
                return []
            mutable = _has_keyword(self.text(node), "mut")
            self_type = _UNKNOWN
            owner = self.records.get(self.current_function)
            if owner is not None and owner.member_of is not None:
                type_record = self.records.get(owner.member_of)
                if type_record is not None:
                    self_type = TypeFact(
                        "named",
                        type_record.binding.name,
                        0,
                        None,
                        owner.member_of,
                    )
            record = self._make_record(
                self_node, "self_parameter", body_span, self.current_function,
                self.module_depth, item=False, mutable=mutable,
                type_fact=self_type,
                type_node=None if owner is None else owner.self_type_node,
            )
            self._add_to_scope(scope, record)
            return [record.binding.id]
        if node.type == "variadic_parameter":
            return []
        if node.type in {"identifier", "self"}:
            record = self._make_record(
                node, "parameter", body_span, self.current_function,
                self.module_depth, item=False,
            )
            self._add_to_scope(scope, record)
            return [record.binding.id]
        pattern = node.child_by_field_name("pattern")
        annotation = node.child_by_field_name("type")
        self._generic_references(annotation)
        # Only names bound to the whole matched value carry the
        # annotation — destructured names (`P { inner }: P`) get
        # `_UNKNOWN` so `inner.m()` does not bind `P`'s members.
        whole_names = self._whole_pattern_names(pattern)
        fact = _UNKNOWN if annotation is None else self._type_fact(annotation)
        identifiers = []
        names = self._pattern_names(pattern, scope)
        mutable_specifier = any(
            child.type == "mutable_specifier" for child in self._children(node)
        )
        names = self._apply_outer_mutability(names, pattern, mutable_specifier)
        for name_node, name_mutable in names:
            whole = name_node.id in whole_names
            record = self._make_record(
                name_node,
                "parameter",
                body_span,
                self.current_function,
                self.module_depth,
                item=False,
                type_fact=fact if whole else _UNKNOWN,
                mutable=name_mutable,
                type_node=annotation if whole else None,
            )
            self._add_to_scope(scope, record)
            identifiers.append(record.binding.id)
        return identifiers

    def _type_fact(self, node: Any, aliases: frozenset[str] = frozenset()) -> TypeFact:
        self._record_macro_invocations(node)
        text = self.text(node).strip()
        if not text:
            return _UNKNOWN
        if node.type in {"scoped_identifier", "scoped_type_identifier"}:
            self._record_qualified_path(node)
            return _UNKNOWN
        if text == "()":
            return TypeFact("unit", "()", 0, None, "")
        if (
            node.type in {"type_identifier", "identifier", "primitive_type"}
            and "::" not in text
        ):
            resolved = self._lookup(text, node.start_byte, "type")
            if resolved is not None:
                record = resolved
                if record.binding.kind == "type_alias":
                    if record.binding.id in aliases:
                        return _UNKNOWN
                    fact = self._type_fact(record.alias_node, aliases | {record.binding.id})
                    return TypeFact(
                        fact.kind, fact.name, fact.bit_width, fact.signed, record.binding.id
                    )
                if record.binding.kind in {"struct", "enum"}:
                    return TypeFact("named", text, 0, None, record.binding.id)
                return _UNKNOWN
        if node.type == "primitive_type" or text in {
            "i8", "i16", "i32", "i64", "i128", "isize",
            "u8", "u16", "u32", "u64", "u128", "usize", "f32", "f64",
            "bool", "char",
        }:
            if text == "bool":
                return TypeFact("bool", text, 1, None, "")
            if text == "char":
                return TypeFact("char", text, 32, None, "")
            if text in {"isize", "usize"}:
                return TypeFact("int", text, self.pointer_width, text == "isize", "")
            if text[0] in "iu" and text[1:].isdigit():
                return TypeFact("int", text, int(text[1:]), text[0] == "i", "")
            if text[0] == "f" and text[1:].isdigit():
                return TypeFact("float", text, int(text[1:]), None, "")
        return _UNKNOWN

    def _whole_pattern_names(self, pattern: Any | None) -> set[int]:
        """Name-node ids bound to the whole matched value.

        `identifier`/`mut x`/`&x` bind the value under that name;
        `x @ P { .. }` binds `x` to the whole value while nested
        names only see their fields. `ref x` is excluded — it binds
        `x` to a reference, so the written type is not `x`'s type."""
        if pattern is None:
            return set()
        if pattern.type == "identifier":
            return {pattern.id}
        if pattern.type in {
            "mutable_specifier",
            "reference_pattern",
            "captured_pattern",
        }:
            for child in self._children(pattern):
                if child.type == "identifier":
                    return {child.id}
        return set()

    def _pattern_names(
        self, pattern: Any | None, scope: _Scope, mutable: bool = False
    ) -> list[tuple[Any, bool]]:
        if pattern is None or pattern.type in {"line_comment", "block_comment"}:
            return []
        if pattern.type in {"identifier", "self"}:
            name = self._normalize_identifier(self.text(pattern))
            found, _ = self._lookup_with_boundary(name, pattern.start_byte, "value")
            if found is not None and found.binding.kind in {
                "const", "static", "struct",
            } and (found.binding.kind != "struct" or found.struct_constructor):
                self.references.append(Reference(self.span(pattern), found.binding.id, "read"))
                return []
            if self._name_imported_or_glob(name, pattern.start_byte):
                self.gaps.append(Gap("pattern_name_ambiguous", self.span(pattern)))
                scope.ambiguous_names[name] = (pattern.end_byte, scope.node.end_byte)
                return []
            if name in _PRELUDE_PATTERN_PATHS:
                self.unresolved.append(
                    Unresolved(self.span(pattern), name, "prelude_name")
                )
                return []
            return [(pattern, mutable)]
        if pattern.type in {
            "_",
            "wildcard_pattern",
            "remaining_field_pattern",
            "integer_literal",
            "float_literal",
            "boolean_literal",
            "char_literal",
            "byte_literal",
            "string_literal",
            "raw_string_literal",
            "byte_string_literal",
            "negative_literal",
            "unit_expression",
        }:
            return []
        if pattern.type == "range_pattern":
            for bound_name in ("left", "right"):
                bound = pattern.child_by_field_name(bound_name)
                if bound is None or bound.type in {
                    "integer_literal",
                    "float_literal",
                    "char_literal",
                    "byte_literal",
                    "string_literal",
                    "raw_string_literal",
                    "byte_string_literal",
                    "negative_literal",
                }:
                    continue
                if bound.type in {
                    "identifier",
                    "self",
                    "scoped_identifier",
                    "scoped_type_identifier",
                }:
                    self._reference(bound)
                else:
                    self.gaps.append(Gap("unsupported_syntax", self.span(bound)))
            return []
        if pattern.type in {"scoped_identifier", "scoped_type_identifier"}:
            member, name_node = self._scoped_member(pattern)
            if member is not None:
                self.references.append(
                    Reference(
                        self.span(name_node), member.binding.id, "read"
                    )
                )
            else:
                self.unresolved.append(
                    Unresolved(
                        self.span(pattern), self.text(pattern), "qualified_path"
                    )
                )
            return []
        if pattern.type == "mut_pattern":
            inner = next(
                (
                    child
                    for child in self._children(pattern)
                    if child.type != "mutable_specifier"
                ),
                None,
            )
            if inner is None:
                return []
            names = self._pattern_names(inner, scope)
            if inner.type in {"identifier", "self"}:
                return [(name, True) for name, _mutable in names]
            if inner.type == "captured_pattern":
                capture = next(
                    (
                        child
                        for child in self._children(inner)
                        if child.type in {"identifier", "self"}
                    ),
                    None,
                )
                return [
                    (name, name == capture or name_mutable)
                    for name, name_mutable in names
                ]
            return names
        if pattern.type == "tuple_struct_pattern":
            tuple_struct_bindings: list[tuple[Any, bool]] = []
            constructor = pattern.child_by_field_name("type")
            if constructor is not None:
                self._record_pattern_path(constructor, "value", {"struct", "import"})
            for child in self._children(pattern):
                if child == constructor:
                    continue
                tuple_struct_bindings.extend(
                    self._pattern_names(child, scope, mutable)
                )
            return tuple_struct_bindings
        if pattern.type == "field_pattern":
            value = pattern.child_by_field_name("pattern")
            field_mutable = any(
                child.type == "mutable_specifier" for child in self._children(pattern)
            )
            if value is not None:
                return self._pattern_names(value, scope)
            field = next(
                (
                    node
                    for node in self._children(pattern)
                    if node.type in {"field_identifier", "shorthand_field_identifier"}
                ),
                None,
            )
            return [] if field is None else [(field, field_mutable)]
        if pattern.type == "or_pattern":
            alternatives = self._children(pattern)
            name_sets: list[list[tuple[Any, bool]]] = [
                self._pattern_names(alternative, scope, mutable)
                for alternative in alternatives
            ]
            normalized = [tuple(sorted(self.text(n) for n, _ in values)) for values in name_sets]
            if normalized and any(names != normalized[0] for names in normalized[1:]):
                self.gaps.append(Gap("or_pattern_mismatch", self.span(pattern)))
            if not name_sets:
                return []
            first: dict[str, tuple[Any, bool]] = {}
            for name_node, mutable in name_sets[0]:
                first.setdefault(self.text(name_node), (name_node, mutable))
            return list(first.values())
        if pattern.type in {
            "tuple_pattern", "slice_pattern", "struct_pattern", "ref_pattern",
            "mut_pattern", "captured_pattern", "remaining_field_pattern",
            "field_pattern", "tuple_struct_pattern",
        }:
            if pattern.type == "struct_pattern":
                type_node = pattern.child_by_field_name("type")
                if type_node is not None:
                    self._record_pattern_path(
                        type_node, "type", {"struct", "enum", "type_alias", "import"}
                    )
            nested_bindings = []
            for child in self._children(pattern):
                if pattern.type == "struct_pattern" and child == pattern.child_by_field_name("type"):
                    continue
                if child.type == "mutable_specifier":
                    continue
                if child.type == "field_identifier" and pattern.type == "struct_pattern":
                    nested_bindings.append((child, mutable))
                    continue
                if child.type == "type_identifier" and pattern.type == "struct_pattern":
                    continue
                nested_bindings.extend(self._pattern_names(child, scope, mutable))
            return nested_bindings
        if pattern.type in {"match_pattern", "condition"}:
            condition_bindings = []
            for child in self._children(pattern):
                if child.type in {"binary_expression", "call_expression"}:
                    continue
                condition_bindings.extend(
                    self._pattern_names(child, scope, mutable)
                )
            return condition_bindings
        self.gaps.append(Gap("unsupported_syntax", self.span(pattern)))
        return []

    def _apply_outer_mutability(
        self,
        names: list[tuple[Any, bool]],
        pattern: Any | None,
        is_mutable: bool,
    ) -> list[tuple[Any, bool]]:
        if not is_mutable:
            return names
        if pattern is not None and pattern.type == "captured_pattern":
            capture = next(
                (
                    child
                    for child in self._children(pattern)
                    if child.type in {"identifier", "self"}
                ),
                None,
            )
            return [(name, mutable or name == capture) for name, mutable in names]
        return [(name, True) for name, _mutable in names]

    def _record_pattern_path(
        self, node: Any, namespace: str, expected_kinds: set[str]
    ) -> None:
        if node.type in {"scoped_identifier", "scoped_type_identifier"}:
            self.unresolved.append(
                Unresolved(
                    self.span(node),
                    self._normalize_identifier(self.text(node)),
                    "qualified_path",
                )
            )
            return
        name = self._normalize_identifier(self.text(node))
        record, boundary = self._lookup_with_boundary(name, node.start_byte, namespace)
        if record is not None and record.binding.kind in expected_kinds:
            self.references.append(Reference(self.span(node), record.binding.id, "read"))
            return
        reason = boundary or (
            "prelude_name" if name in _PRELUDE_PATTERN_PATHS else "unknown_name"
        )
        self.unresolved.append(Unresolved(self.span(node), name, reason))

    def _lookup_with_boundary(self, name: str, position: int, namespace: str) -> tuple[_Record | None, str | None]:
        name = self._normalize_identifier(name)
        blocked: str | None = None
        for scope in reversed(self.scopes):
            if scope.module_depth < self.module_depth and self.module_depth > 0:
                if any(
                    self._in_namespace(record, namespace)
                    for record in scope.bindings.get(name, ())
                ):
                    blocked = "module_boundary"
                continue
            records = scope.bindings.get(name, ())
            generic_records = []
            for record in records:
                if (
                    record.binding.kind != "generic_parameter"
                    or not self._in_namespace(record, namespace)
                ):
                    continue
                binding_scope = record.binding.scope
                if binding_scope is None or not (
                    binding_scope.start <= position < binding_scope.end
                ):
                    continue
                if (record.owner_function or None) != (self.current_function or None):
                    blocked = "item_boundary"
                    continue
                generic_records.append(record)
            if generic_records:
                return min(
                    generic_records,
                    key=lambda record: (
                        record.binding.scope.end - record.binding.scope.start
                        if record.binding.scope is not None
                        else 0
                    ),
                ), None
            for record in reversed(records):
                if record.binding.scope is not None and record.binding.scope != ByteSpan(0, 0) and not (
                    record.binding.scope.start <= position < record.binding.scope.end
                ):
                    continue
                if not self._in_namespace(record, namespace):
                    continue
                if (
                    not record.item
                    and (record.owner_function or None)
                    != (self.current_function or None)
                ):
                    blocked = "item_boundary"
                    continue
                return record, None
            ambiguous = scope.ambiguous_names.get(name)
            if ambiguous is not None and ambiguous[0] <= position < ambiguous[1]:
                return None, "unknown_name"
            if scope.glob_import:
                return None, "glob_import"
        return None, blocked

    def _lookup(self, name: str, position: int, namespace: str) -> _Record | None:
        return self._lookup_with_boundary(name, position, namespace)[0]

    @staticmethod
    def _in_namespace(record: _Record, namespace: str) -> bool:
        kind = record.binding.kind
        if kind == "generic_parameter":
            if record.generic_kind == "const":
                return namespace != "type"
            return namespace == "type"
        if namespace == "type":
            return kind in {"struct", "enum", "type_alias", "trait", "union", "import"}
        if kind == "struct":
            return record.struct_constructor
        return kind not in {"enum", "trait", "union", "type_alias", "module", "associated_const", "associated_function"}

    def _name_imported_or_glob(self, name: str, position: int) -> bool:
        name = self._normalize_identifier(name)
        for scope in reversed(self.scopes):
            if name in scope.bindings and any(r.binding.kind == "import" for r in scope.bindings[name]):
                return True
            if scope.glob_import:
                return True
        return False

    def _reference(self, node: Any, kind: str = "read", namespace: str = "value") -> _Record | None:
        name = self._normalize_identifier(self.text(node))
        if node.type in {"scoped_identifier", "scoped_type_identifier"}:
            self._record_qualified_path(node)
            return None
        record, boundary = self._lookup_with_boundary(name, node.start_byte, namespace)
        if record is not None:
            self.references.append(Reference(self.span(node), record.binding.id, kind))
            return record
        reason = boundary or ("prelude_name" if name in _PRELUDE_NAMES else "unknown_name")
        self.unresolved.append(Unresolved(self.span(node), name, reason))
        return None

    def _record_qualified_path(self, node: Any) -> None:
        member, name_node = self._scoped_member(node)
        if member is not None:
            # An enum discriminant's path is visited by both the type
            # walk and the value walk — append once.
            reference = Reference(self.span(name_node), member.binding.id, "read")
            if reference not in self.references:
                self.references.append(reference)
            return
        unresolved = Unresolved(
            self.span(node),
            self._normalize_identifier(self.text(node)),
            "qualified_path",
        )
        if unresolved not in self.unresolved:
            self.unresolved.append(unresolved)

    def _let(self, node: Any, scope: _Scope) -> None:
        pattern = node.child_by_field_name("pattern")
        value = node.child_by_field_name("value")
        annotation = node.child_by_field_name("type")
        if value is not None:
            self._expr(value)
        self._generic_references(annotation)
        whole_names = self._whole_pattern_names(pattern)
        fact = _UNKNOWN if annotation is None else self._type_fact(annotation)
        alternative = node.child_by_field_name("alternative")
        if alternative is not None:
            self._expr(alternative)
        names = self._pattern_names(pattern, scope)
        mutable_specifier = any(
            child.type == "mutable_specifier" for child in self._children(node)
        )
        names = self._apply_outer_mutability(
            names, pattern, mutable_specifier
        )
        for name_node, name_mutable in names:
            whole = name_node.id in whole_names
            record = self._make_record(
                name_node,
                "local",
                ByteSpan(node.end_byte, scope.node.end_byte),
                self.current_function,
                self.module_depth,
                item=False,
                type_fact=fact if whole else _UNKNOWN,
                mutable=name_mutable,
                type_node=annotation if whole else None,
            )
            if whole:
                record.value_node = value
            self._add_to_scope(scope, record)

    def _expr(self, node: Any | None) -> None:
        if node is None:
            return
        kind = node.type
        if kind == "macro_invocation":
            self._record_macro_invocations(node)
            return
        if kind == "macro_definition":
            self.gaps.append(Gap("macro_definition", self.span(node)))
            return
        if kind in {"identifier", "self"}:
            self._reference(node)
            return
        if kind in {"scoped_identifier", "scoped_type_identifier", "generic_function"}:
            self._record_qualified_path(node)
            return
        if kind == "type_cast_expression":
            self._expr(node.child_by_field_name("value"))
            self._generic_references(node.child_by_field_name("type"))
            return
        if kind == "call_expression":
            self._call(node)
            return
        if kind == "method_call_expression":
            self._method_call(node)
            return
        if kind == "field_expression":
            base = node.child_by_field_name("value")
            if base is not None:
                self._expr(base)
            member = self._field_member(node, ("struct_field",))
            field_node = node.child_by_field_name("field")
            if member is not None and field_node is not None:
                self.references.append(
                    Reference(
                        self.span(field_node), member.binding.id, "read"
                    )
                )
            return
        if kind == "struct_expression":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                path_node = name_node
                if name_node.type in {"generic_type", "generic_type_with_turbofish"}:
                    self._generic_references(
                        name_node.child_by_field_name("type_arguments")
                    )
                    path_node = name_node.child_by_field_name("type")
                if path_node is not None:
                    self._reference(path_node, "read", "type")
            fields = node.child_by_field_name("body")
            if fields is not None:
                for initializer in self._children(fields):
                    if initializer.type == "shorthand_field_initializer":
                        identifier = next(
                            (
                                child
                                for child in self._children(initializer)
                                if child.type == "identifier"
                            ),
                            None,
                        )
                        if identifier is not None:
                            self._expr(identifier)
                    elif initializer.type == "field_initializer":
                        self._expr(initializer.child_by_field_name("value"))
                    elif initializer.type == "base_field_initializer":
                        for child in self._children(initializer):
                            self._expr(child)
                    else:
                        self.gaps.append(
                            Gap("unsupported_syntax", self.span(initializer))
                        )
            return
        if kind in {"assignment_expression", "compound_assignment_expr"}:
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            if left is not None:
                operator = node.child_by_field_name("operator")
                is_compound = kind == "compound_assignment_expr" or (
                    operator is not None and self.text(operator) != "="
                )
                self._assign_to_place(left, is_compound, node)
            self._expr(right)
            return
        if kind == "let_declaration":
            if self.scopes:
                self._let(node, self.scopes[-1])
            return
        if kind == "let_condition":
            self.gaps.append(Gap("unsupported_syntax", self.span(node)))
            return
        if kind == "block":
            self._block(node)
            return
        if kind == "closure_expression":
            self._closure(node)
            return
        if kind == "if_expression":
            self._if(node)
            return
        if kind == "while_expression":
            self._while(node)
            return
        if kind == "for_expression":
            self._for(node)
            return
        if kind == "match_expression":
            self._match(node)
            return
        if kind == "parenthesized_expression":
            for child in self._children(node):
                self._expr(child)
            return
        if kind in _TRANSPARENT_NODES:
            for child in self._children(node):
                self._expr(child)
            return
        if kind in _EXPR_NODES or kind in {
            "return_expression", "break_expression", "continue_expression",
            "await_expression", "try_expression", "yield_expression",
        }:
            for child in self._children(node):
                self._expr(child)
            return
        if kind in {
            "integer_literal", "float_literal", "boolean_literal", "char_literal",
            "string_literal", "raw_string_literal", "byte_string_literal",
            "unit_expression", "self_parameter", "primitive_type", "type_identifier",
            "field_identifier", "attribute_item", "inner_attribute_item",
            "line_comment", "block_comment", "token_tree",
        }:
            return
        if kind in {"type_item", "struct_item", "enum_item", "union_item", "trait_item"}:
            return
        if kind in {"expression_statement"}:
            for child in self._children(node):
                self._expr(child)
            return
        # Every syntax node that can conceal a read is surfaced as a gap.
        self.gaps.append(Gap("unsupported_syntax", self.span(node)))

    def _place_root(self, node: Any) -> Any | None:
        if node.type == "parenthesized_expression":
            children = self._children(node)
            return None if not children else self._place_root(children[0])
        if node.type in {"identifier", "self"}:
            return node
        if node.type == "field_expression":
            base = node.child_by_field_name("value")
            return None if base is None else self._place_root(base)
        if node.type == "index_expression":
            children = self._children(node)
            return None if not children else self._place_root(children[0])
        return None

    def _visit_place_indices(self, node: Any) -> None:
        if node.type == "parenthesized_expression":
            children = self._children(node)
            if children:
                self._visit_place_indices(children[0])
            return
        if node.type == "field_expression":
            base = node.child_by_field_name("value")
            if base is not None:
                self._visit_place_indices(base)
            return
        if node.type == "index_expression":
            children = self._children(node)
            if children:
                self._visit_place_indices(children[0])
                for index in children[1:]:
                    self._expr(index)
            return
        if node.type == "unary_expression" and self.text(node).lstrip().startswith("*"):
            children = self._children(node)
            operand = children[-1] if children else None
            self._expr(operand)
            return
        if node.type in {"identifier", "self"}:
            return
        self._expr(node)

    def _assign_to_place(self, node: Any, compound: bool, assignment: Any) -> None:
        if node.type == "parenthesized_expression":
            children = self._children(node)
            if children:
                self._assign_to_place(children[0], compound, assignment)
            return
        if node.type in {"identifier", "self"}:
            self._assignment_reference(node, compound, assignment)
            return
        if node.type == "field_expression":
            root = self._place_root(node)
            self._visit_place_indices(node)
            member = self._field_member(node, ("struct_field",))
            field_node = node.child_by_field_name("field")
            if member is not None and field_node is not None:
                self.references.append(
                    Reference(
                        self.span(field_node), member.binding.id, "write"
                    )
                )
            if root is None:
                return
            else:
                self._assignment_reference(root, compound, assignment)
            return
        if node.type == "index_expression":
            root = self._place_root(node)
            self._visit_place_indices(node)
            if root is not None:
                self._assignment_reference(root, compound, assignment)
            return
        if node.type == "unary_expression" and self.text(node).lstrip().startswith("*"):
            children = self._children(node)
            operand = children[-1] if children else None
            self._expr(operand)
            return
        if node.type in {"scoped_identifier", "scoped_type_identifier"}:
            self._reference(node, "write")
            return
        self._expr(node)
        self.gaps.append(Gap("unsupported_syntax", self.span(assignment)))

    def _assignment_reference(
        self, node: Any, compound: bool, assignment: Any
    ) -> None:
        record, _ = self._lookup_with_boundary(self.text(node), node.start_byte, "value")
        if record is None:
            self._reference(node, "write")
            return
        if record.binding.kind in NON_ASSIGNABLE_WRITE_KINDS:
            self.references.append(Reference(self.span(node), record.binding.id, "read"))
            self.gaps.append(Gap("unsupported_syntax", self.span(assignment)))
            return
        if compound:
            self.references.append(Reference(self.span(node), record.binding.id, "read"))
        self.references.append(Reference(self.span(node), record.binding.id, "write"))

    def _block(self, node: Any) -> None:
        scope = _Scope(node, self.module_depth, self.current_function)
        self.scopes.append(scope)
        self._predeclare(node, scope)
        self._scan_container(node, scope)
        self.scopes.pop()

    def _condition(
        self, condition: Any, scope: _Scope
    ) -> list[tuple[Any, bool]]:
        if condition.type == "let_condition":
            pattern = condition.child_by_field_name("pattern")
            value = condition.child_by_field_name("value")
            if value is None:
                named = self._children(condition)
                value = named[-1] if named else None
            if value is not None:
                self._expr(value)
            return self._pattern_names(pattern, scope)
        if any(node.type == "let_condition" for node in self._descendants(condition)):
            self.gaps.append(Gap("unsupported_syntax", self.span(condition)))
            return []
        self._expr(condition)
        return []

    def _if(self, node: Any) -> None:
        condition = node.child_by_field_name("condition")
        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")
        if consequence is not None:
            scope = _Scope(consequence, self.module_depth, self.current_function)
            self.scopes.append(scope)
            names = [] if condition is None else self._condition(condition, scope)
            self._bind_pattern_names(names, scope, self.span(consequence))
            self._expr(consequence)
            self.scopes.pop()
        elif condition is not None:
            self._condition(condition, self.scopes[-1])
        if alternative is not None:
            self._expr(alternative)

    def _while(self, node: Any) -> None:
        condition = node.child_by_field_name("condition")
        body = node.child_by_field_name("body")
        if body is not None:
            scope = _Scope(body, self.module_depth, self.current_function)
            self.scopes.append(scope)
            names = [] if condition is None else self._condition(condition, scope)
            self._bind_pattern_names(names, scope, self.span(body))
            self._expr(body)
            self.scopes.pop()
        elif condition is not None:
            self._condition(condition, self.scopes[-1])

    def _for(self, node: Any) -> None:
        iterator = node.child_by_field_name("value")
        pattern = node.child_by_field_name("pattern")
        body = node.child_by_field_name("body")
        if iterator is not None:
            self._expr(iterator)
        if body is not None:
            scope = _Scope(body, self.module_depth, self.current_function)
            self.scopes.append(scope)
            self._bind_pattern(pattern, scope, self.span(body), _UNKNOWN)
            self._expr(body)
            self.scopes.pop()

    def _match(self, node: Any) -> None:
        value = node.child_by_field_name("value")
        if value is not None:
            self._expr(value)
        body = node.child_by_field_name("body")
        if body is None:
            return
        for arm in self._children(body):
            if arm.type != "match_arm":
                self.gaps.append(Gap("unsupported_syntax", self.span(arm)))
                continue
            arm_scope = _Scope(arm, self.module_depth, self.current_function)
            self.scopes.append(arm_scope)
            match_pattern = arm.child_by_field_name("pattern")
            guard = (
                None
                if match_pattern is None
                else match_pattern.child_by_field_name("condition")
            )
            pattern = (
                match_pattern
                if match_pattern is None or guard is None
                else next(
                    (
                        child
                        for child in self._children(match_pattern)
                        if child != guard
                    ),
                    None,
                )
            )
            names = self._pattern_names(pattern, arm_scope)
            self._bind_pattern_names(names, arm_scope, self.span(arm))
            if guard is not None:
                self._expr(guard)
            result = arm.child_by_field_name("value")
            if result is not None:
                self._expr(result)
            self.scopes.pop()

    def _bind_pattern_names(
        self,
        names: list[tuple[Any, bool]],
        scope: _Scope,
        binding_scope: ByteSpan,
        type_fact: TypeFact = _UNKNOWN,
    ) -> None:
        for name_node, mutable in names:
            record = self._make_record(
                name_node, "local", binding_scope, self.current_function,
                self.module_depth, item=False, type_fact=type_fact, mutable=mutable,
            )
            self._add_to_scope(scope, record)

    def _bind_pattern(
        self, pattern: Any, scope: _Scope, binding_scope: ByteSpan, type_fact: TypeFact
    ) -> None:
        self._bind_pattern_names(self._pattern_names(pattern, scope), scope, binding_scope, type_fact)

    def _closure(self, node: Any) -> None:
        params = node.child_by_field_name("parameters")
        body = node.child_by_field_name("body")
        if body is None:
            return
        closure_scope = _Scope(body, self.module_depth, self.current_function)
        self.scopes.append(closure_scope)
        old_owner = self.call_owner
        self.call_owner = ""
        if params is not None:
            for parameter in self._children(params):
                self._parameter(parameter, closure_scope, self.span(body))
        self._expr(body)
        self.call_owner = old_owner
        self.scopes.pop()

    def _callee(self, node: Any) -> Any:
        while node.type == "parenthesized_expression" and len(self._children(node)) == 1:
            node = self._children(node)[0]
        return node

    def _call(self, node: Any) -> None:
        callee = node.child_by_field_name("function")
        arguments_node = node.child_by_field_name("arguments")
        arguments = () if arguments_node is None else self._children(arguments_node)
        args = tuple(self.span(arg) for arg in arguments)
        # `(p.f)()` calls the field value while `p.f()` prefers a
        # method — remember whether parens wrapped the callee before
        # _callee unwraps them.
        paren_wrapped = (
            callee is not None
            and callee.type == "parenthesized_expression"
        )
        callee = None if callee is None else self._callee(callee)
        span = self.span(node)
        kind = "opaque_expression"
        target = ""
        if callee is not None and callee.type in {"scoped_identifier", "scoped_type_identifier"}:
            member, name_node = self._scoped_member(callee)
            if member is not None and member.binding.kind == "associated_function":
                self.references.append(
                    Reference(
                        self.span(name_node), member.binding.id, "call"
                    )
                )
                target = member.binding.id
                kind = self._member_call_kind(member)
            elif member is not None:
                self.references.append(
                    Reference(
                        self.span(name_node), member.binding.id, "read"
                    )
                )
                target = member.binding.id
                kind = "opaque_value"
            else:
                self.unresolved.append(Unresolved(self.span(callee), self.text(callee), "qualified_path"))
                kind = "opaque_path"
        elif callee is not None and callee.type == "generic_function":
            self._generic_references(callee.child_by_field_name("type_arguments"))
            inner = callee.child_by_field_name("function")
            if inner is not None and inner.type == "identifier":
                record = self._reference(inner, "call")
                if record is None:
                    kind = "unresolved"
                else:
                    target = record.binding.id
                    if record.binding.kind == "struct":
                        kind = "constructor"
                    elif record.binding.kind == "import":
                        kind = "opaque_import"
                    else:
                        kind = "opaque_generic"
            elif inner is not None and inner.type == "field_expression":
                receiver = inner.child_by_field_name("value")
                if receiver is not None:
                    self._expr(receiver)
                # Method-call spelling prefers methods; when none is
                # named `field`, a same-named field can still be the
                # callee — `(p.callback)()` reads the `fn()` field.
                member = self._field_member(
                    inner, ("associated_function", "associated_const")
                ) or self._field_member(inner, ("struct_field",))
                field_node = inner.child_by_field_name("field")
                if member is not None and member.binding.kind == "associated_function":
                    self.references.append(
                        Reference(
                            self.span(field_node), member.binding.id, "call"
                        )
                    )
                    target = member.binding.id
                    kind = self._member_call_kind(member)
                elif member is not None:
                    self.references.append(
                        Reference(
                            self.span(field_node), member.binding.id, "read"
                        )
                    )
                    target = member.binding.id
                    kind = "opaque_value"
                elif field_node is not None:
                    field_member = self._field_member(
                        inner, ("struct_field",)
                    )
                    if field_member is not None:
                        self.references.append(
                            Reference(
                                self.span(field_node),
                                field_member.binding.id,
                                "read",
                            )
                        )
                        target = field_member.binding.id
                        kind = "opaque_value"
                    else:
                        kind = "opaque_method"
                else:
                    kind = "opaque_method"
            elif inner is not None and inner.type in {
                "scoped_identifier",
                "scoped_type_identifier",
            }:
                member, name_node = self._scoped_member(inner)
                if (
                    member is not None
                    and member.binding.kind == "associated_function"
                ):
                    self.references.append(
                        Reference(
                            self.span(name_node), member.binding.id, "call"
                        )
                    )
                    target = member.binding.id
                    kind = self._member_call_kind(member)
                elif member is not None:
                    self.references.append(
                        Reference(
                            self.span(name_node), member.binding.id, "read"
                        )
                    )
                    target = member.binding.id
                    kind = "opaque_value"
                else:
                    self.unresolved.append(
                        Unresolved(
                            self.span(callee), self.text(callee), "qualified_path"
                        )
                    )
                    kind = "opaque_path"
            else:
                self.unresolved.append(
                    Unresolved(self.span(callee), self.text(callee), "qualified_path")
                )
                kind = "opaque_path"
        elif callee is not None and callee.type == "identifier":
            record = self._reference(callee, "call")
            if record is None:
                kind = "unresolved"
            else:
                target = record.binding.id
                binding_kind = record.binding.kind
                if binding_kind == "struct":
                    kind = "constructor"
                elif binding_kind == "import":
                    kind = "opaque_import"
                elif binding_kind == "function":
                    if record.extern or record.body_node is None:
                        kind = "opaque_bodyless"
                    elif record.generic:
                        kind = "opaque_generic"
                    elif record.is_async:
                        kind = "opaque_async"
                    else:
                        kind = "direct_local"
                elif binding_kind in {"local", "parameter", "self_parameter", "const", "static"}:
                    kind = "opaque_value"
                else:
                    kind = "opaque_value"
        elif callee is not None and callee.type == "field_expression":
            value = callee.child_by_field_name("value")
            if value is not None:
                self._expr(value)
            member = (
                self._field_member(callee, ("struct_field",))
                or self._field_member(
                    callee, ("associated_function", "associated_const")
                )
                if paren_wrapped
                else self._field_member(
                    callee, ("associated_function", "associated_const")
                )
                or self._field_member(callee, ("struct_field",))
            )
            field_node = callee.child_by_field_name("field")
            if member is not None and member.binding.kind == "associated_function":
                self.references.append(
                    Reference(
                        self.span(field_node), member.binding.id, "call"
                    )
                )
                target = member.binding.id
                kind = self._member_call_kind(member)
            elif member is not None:
                self.references.append(
                    Reference(
                        self.span(field_node), member.binding.id, "read"
                    )
                )
                target = member.binding.id
                kind = "opaque_value"
            elif field_node is not None:
                field_member = self._field_member(
                    callee, ("struct_field",)
                )
                if field_member is not None:
                    self.references.append(
                        Reference(
                            self.span(field_node),
                            field_member.binding.id,
                            "read",
                        )
                    )
                    target = field_member.binding.id
                    kind = "opaque_value"
                else:
                    kind = "opaque_method"
            else:
                kind = "opaque_method"
        elif callee is not None:
            self._expr(callee)
        if arguments_node is not None:
            for argument in arguments:
                self._expr(argument)
        self.calls.append(Call(span, args, self.call_owner, target, kind))

    def _method_call(self, node: Any) -> None:
        self._generic_references(node.child_by_field_name("type_arguments"))
        receiver = node.child_by_field_name("receiver")
        if receiver is None:
            children = self._children(node)
            receiver = children[0] if children else None
        if receiver is not None:
            self._expr(receiver)
        name_node = node.child_by_field_name("name")
        if name_node is None:
            name_node = next(
                (
                    child
                    for child in self._children(node)
                    if child.type == "field_identifier"
                ),
                None,
            )
        recv_type, recv_args = self._receiver_type(receiver)
        member = (
            None
            if name_node is None
            else self._member_record(
                recv_type,
                self._normalize_identifier(self.text(name_node)),
                ("associated_function", "associated_const"),
                recv_args,
                node.start_byte,
            )
        )
        args_node = node.child_by_field_name("arguments")
        arguments = () if args_node is None else self._children(args_node)
        args = tuple(self.span(arg) for arg in arguments)
        if args_node is not None:
            for arg in arguments:
                self._expr(arg)
        if member is not None and member.binding.kind == "associated_function":
            self.references.append(
                Reference(
                    self.span(name_node), member.binding.id, "call"
                )
            )
            self.calls.append(
                Call(
                    self.span(node),
                    args,
                    self.call_owner,
                    member.binding.id,
                    self._member_call_kind(member),
                )
            )
            return
        self.calls.append(Call(self.span(node), args, self.call_owner, "", "opaque_method"))


def build_rust_bindings(source: str, *, pointer_width: int) -> LexicalBindingReport:
    if pointer_width not in {16, 32, 64} or type(pointer_width) is not int:
        raise LexicalReportError("pointer width must be 16, 32, or 64")
    try:
        raw = source.encode("utf-8")
    except UnicodeError:
        raise LexicalReportError("unsupported Rust source encoding") from None
    if len(raw) > MAX_SOURCE_BYTES:
        raise LexicalReportError("Rust source exceeds the lexical report limit")
    try:
        from tree_sitter import Language, Parser  # type: ignore[import-not-found]
        import tree_sitter_rust  # type: ignore[import-not-found]

        parser = Parser(Language(tree_sitter_rust.language()))
        root = parser.parse(raw).root_node
    except Exception as exc:
        raise LexicalReportError("Rust source could not be parsed") from exc
    if root.has_error or any(node.is_missing for node in _walk(root)):
        raise LexicalReportError("Rust source has parse errors or missing nodes")
    try:
        return _RustBindings(source, raw, pointer_width, root).build()
    except RecursionError:
        raise LexicalReportError(
            "Rust source nesting exceeds the lexical report limit"
        ) from None


def _walk(root: Any):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(
        prog="python -m agent rust-bindings",
        description="Emit a conservative Rust lexical binding report as JSON.",
    )
    parser.add_argument("file", type=Path, help="Rust source file")
    parser.add_argument(
        "--pointer-width",
        type=int,
        choices=(16, 32, 64),
        required=True,
        help="Target pointer width used for isize and usize",
    )
    return parser


def main(args: argparse.Namespace) -> int:
    try:
        source = args.file.read_bytes().decode("utf-8", errors="strict")
        report = build_rust_bindings(source, pointer_width=args.pointer_width)
        sys.stdout.write(report.to_json())
        return 0
    except (OSError, UnicodeError, LexicalReportError) as exc:
        print(f"rust-bindings: {exc}", file=sys.stderr)
        return 2
