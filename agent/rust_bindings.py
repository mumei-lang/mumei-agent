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
# Method calls that still yield a container's element —
# `for p in v.iter()` binds like `for p in v`. Maps are excluded
# here (they iterate (K, V) pairs) and handled by their own
# `keys`/`values` entry points below.
_ITER_ELEMENT_METHODS = frozenset({"iter", "iter_mut", "into_iter", "drain"})
# Iterator adaptors that keep the same element type — `map`/`flat_map`
# change it through a closure and stay opaque.
_ITER_PRESERVING_METHODS = frozenset(
    {"rev", "skip", "take", "filter", "step_by", "chain",
     "cloned", "copied"}
)
# Vec/slice accessors that iterate the same element as `iter()`.
_ITER_SLICE_METHODS = frozenset({"as_slice", "as_mut_slice"})
# Iterators over `&[T]` slices — `v.chunks(n)`/`v.windows(n)`/
# `v.split(p)` spell `&P`, which index/iter unwrap to `P`.
_ITER_CHUNK_METHODS = frozenset(
    {"chunks", "windows", "rchunks", "split", "split_inclusive"}
)
# Map entry points and the key they read — `m.keys()` yields `K`,
# `m.values()` yields `V` of `HashMap<K, V>`/`BTreeMap<K, V>`.
_MAP_ELEMENT_METHODS = {"keys": 0, "values": 1}
_MAP_CONTAINER_NAMES = frozenset({"HashMap", "BTreeMap"})

# Prelude container methods that hand back `Option` — `v.get(i)`,
# `v.first()` and `v.last()` yield `Option<&T>` while `v.pop()`
# yields `Option<T>`. Each maps to its payload prefix and the
# container heads the method actually exists on.
# (payload prefix, container heads, arg index) — index picks the
# type arg that becomes Option's payload (`ok` reads P of
# `Result<P, E>`, `err` reads E); -1 is the last arg.
_OPTION_HEAD_METHODS = {
    "get": ("&", {"Vec", "VecDeque", "HashMap", "BTreeMap"}, -1),
    "first": ("&", {"Vec"}, -1),
    "last": ("&", {"Vec"}, -1),
    "pop": ("", {"Vec"}, -1),
    "front": ("&", {"VecDeque"}, -1),
    "back": ("&", {"VecDeque"}, -1),
    "pop_front": ("", {"VecDeque"}, -1),
    "pop_back": ("", {"VecDeque"}, -1),
    "remove": ("", {"HashMap", "BTreeMap", "VecDeque"}, -1),
    "next": ("&", None, -1),
    # `Option` exposes no `ok()` — only `Result::ok()` narrows to
    # `Option<T>`; an unresolved extension method on `Option` stays
    # opaque rather than pinning a payload.
    "ok": ("", {"Result"}, 0),
    "err": ("", {"Result"}, -1),
    "take": ("", {"Option"}, 0),
}

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
_UNWRAP_OK_METHODS = frozenset(
    {"unwrap", "expect", "unwrap_or", "unwrap_or_else", "unwrap_unchecked"}
)
_UNWRAP_ERR_METHODS = frozenset({"unwrap_err", "expect_err"})
_TRY_HEADS = frozenset({"Option", "Result"})
# Prelude constructors whose tuple payload position is fixed by the
# container type — `Some(x)` binds `Option<T>`'s first arg, `Err(e)`
# binds `Result<T, E>`'s second.
_PRELUDE_CONTAINER_PAYLOAD = {
    "Some": ("Option", 0),
    "Ok": ("Result", 0),
    "Err": ("Result", 1),
}
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
    # Module paths pulled in by `use m::*` — names not bound directly
    # resolve against the modules' declared items. Each entry is the
    # path, the use declaration's position (the import resolves in its
    # own scope, not at the reference site) and whether the use is
    # `pub` (only re-exports carry names onward).
    glob_imports: list[tuple[str, int, bool]] = field(default_factory=list)
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
    # Type/const/lifetime parameter names the impl block declares
    # (`impl<A> Tr<A> for P` → {"A"}); wildcard positions when a
    # UFCS `<P as Tr<u32>>` call names concrete trait arguments.
    member_impl_type_params: frozenset = frozenset()
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
    # Normalized generic arguments of a destructured binding's type
    # (`for inner in Vec<Vec<P>>` carries "P") so nested unwrapping
    # stays typed.
    type_args: str | None = None
    # A `mod` item's body scope — lets `m::T` annotations resolve.
    module_scope: Any = None
    # The scope the record was declared into — a type alias's body
    # resolves in its own scope, not the use-site scope stack.
    home_scope: Any = None
    # The item carries a `pub` visibility modifier — only `pub` items
    # come through a `use m::*` glob.
    public: bool = False
    # An `import` record's full use path (`use m::P as Q` → "m::P")
    # — the name it binds resolves through this target.
    import_path: str | None = None


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
        self._receiver_memo: dict[tuple, tuple] = {}
        self._spelling_memo: dict[tuple, tuple] = {}
        # Receiver-resolution epoch — bumped only by declarations that
        # can change a `_receiver_type` result (type/function/impl
        # items, or a record overwrite), so long `let` chains do not
        # flush the memo on every line.
        self._resolution_epoch = 0

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
        # `local`/`parameter` bindings never change what a receiver
        # resolves to — locals are bound before their scope is visited
        # and parameters at function entry — so they leave the memo
        # epoch alone. An overwrite (same identifier redeclared) always
        # bumps, whatever the kind.
        if identifier in self.records or kind not in {
            "local",
            "parameter",
            "self_parameter",
        }:
            self._resolution_epoch += 1
        self.records[identifier] = record
        return record

    def _add_to_scope(self, scope: _Scope, record: _Record) -> None:
        record.home_scope = scope
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
                record.public = any(
                    child.type == "visibility_modifier"
                    for child in node.named_children
                )
                self._add_to_scope(scope, record)
                if kind == "function":
                    self._function_records[record.binding.id] = record
                if kind == "type_alias":
                    record.alias_node = node.child_by_field_name("type")
                if node.type == "mod_item" and body is not None:
                    # Module contents are items too — predeclare them so
                    # `m::P` resolves before `mod m` is scanned, like a
                    # top-level item does. The child scope must be
                    # active while its own items predeclare, or names
                    # like a const-generic's type annotation stay
                    # unresolved.
                    child_scope = _Scope(
                        body, scope.module_depth + 1, scope.function_id
                    )
                    record.module_scope = child_scope
                    self.scopes.append(child_scope)
                    self._predeclare(body, child_scope)
                    self.scopes.pop()
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
        is_pub = any(
            child.type == "visibility_modifier"
            for child in node.named_children
        )
        for name_node, is_glob, bound_name, target_path in self._use_names(
            node
        ):
            if is_glob:
                scope.glob_import = True
                if bound_name:
                    scope.glob_imports.append(
                        (bound_name, node.start_byte, is_pub)
                    )
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
            record.public = is_pub
            record.import_path = target_path
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

    def _use_names(
        self, node: Any
    ) -> list[tuple[Any, bool, str | None, str | None]]:
        out: list[tuple[Any, bool, str | None, str | None]] = []

        def joined(prefix: tuple[str, ...], text: str) -> str:
            return "::".join(
                prefix + tuple(part for part in text.split("::") if part)
            )

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
                    path_node = next(
                        (
                            child
                            for child in self._children(tree)
                            if child.id != alias.id
                        ),
                        None,
                    )
                    out.append(
                        (
                            alias,
                            False,
                            self.text(alias),
                            None
                            if path_node is None
                            else joined(prefix, self.text(path_node)),
                        )
                    )
            elif tree.type in {"use_wildcard", "wildcard_pattern"} or self.text(tree).endswith("*"):
                path = self.text(tree).removesuffix("*").removesuffix("::")
                out.append(
                    (
                        tree,
                        True,
                        "::".join(prefix + (path,)) if prefix else path,
                        None,
                    )
                )
            elif tree.type == "self":
                out.append(
                    (
                        tree,
                        False,
                        prefix[-1] if prefix else "self",
                        "::".join(prefix) if prefix else None,
                    )
                )
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
                    out.append(
                        (picked, False, final, joined(prefix, self.text(tree)))
                    )

        for child in node.named_children:
            add_leaf(child)
        if not out and "::" in self.text(node):
            candidate = next(
                (c for c in self._descendants(node) if c.type in {"identifier", "type_identifier"}),
                None,
            )
            if candidate is not None:
                out.append(
                    (
                        candidate,
                        False,
                        self.text(candidate),
                        self.text(node)
                        .removeprefix("use")
                        .removesuffix(";")
                        .strip(),
                    )
                )
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
                impl_type_params: frozenset = frozenset()
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
                    type_params = node.child_by_field_name(
                        "type_parameters"
                    )
                    member_generic = type_params is not None
                    impl_type_params = frozenset(
                        self._normalize_identifier(
                            self.text(child.child_by_field_name("name"))
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
                        and child.child_by_field_name("name") is not None
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
                            self._type_impl_traits.setdefault(
                                member_of, []
                            ).append(
                                (
                                    member_trait,
                                    member_args,
                                    member_generic,
                                    impl_type_params,
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
                        impl_type_params,
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

    def _type_param_names(self, parameters: Any | None) -> list[str]:
        """Declared names of a `type_parameters` node — `<A, const N:
        usize, 'b>` → `["A", "N", "b"]`."""
        names: list[str] = []
        if parameters is None:
            return names
        for parameter in self._children(parameters):
            if parameter.type not in {
                "type_parameter",
                "lifetime_parameter",
                "const_parameter",
            }:
                continue
            name_node = parameter.child_by_field_name("name")
            if name_node is not None:
                names.append(self.text(name_node))
        return names

    @staticmethod
    def _type_arg_list(args: str) -> list[str]:
        """Top-level comma split of a type-argument key — commas
        inside `(...)`, `[...]` or `<...>` stay inside their arg."""
        parts: list[str] = []
        depth = 0
        braces = 0
        current: list[str] = []
        for index, ch in enumerate(args):
            if ch in "([{":
                depth += 1
                if ch == "{":
                    # `{1 << 2}` — inside a const block `<` and `>`
                    # are operators, not generic brackets.
                    braces += 1
            elif ch in ")]}":
                depth -= 1
                if ch == "}":
                    braces -= 1
            elif ch == "<":
                if braces == 0:
                    depth += 1
            elif ch == ">":
                # `>` also spells `->` in `dyn Fn(A) -> B` — only a
                # `>` not closing a function type's arrow counts.
                if (
                    braces == 0
                    and (index == 0 or args[index - 1] != "-")
                ):
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
        if a.startswith("[") and a.endswith("]"):
            if not (b.startswith("[") and b.endswith("]")):
                return False
            # `[A; N]` — element and length are both arg positions;
            # a const parameter binds the length (`N` = `4`).
            parts_a = a[1:-1].split(";", 1)
            parts_b = b[1:-1].split(";", 1)
            if len(parts_a) != len(parts_b):
                return False
            return all(
                self._type_arg_match(x, y, params, bindings)
                for x, y in zip(parts_a, parts_b)
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
        self,
        a: str | None,
        b: str | None,
        params: frozenset[str],
        bindings: dict[str, str] | None = None,
    ) -> bool:
        """Positional structural equality of two type-argument keys
        — `W<(u8,u16)>` and `W<(u8, u16)>` are the same type. The
        caller may pass a shared `bindings` map so parameter bindings
        established on one side (trait args) constrain the other
        (impl type args)."""
        if (a is None) != (b is None):
            return False
        if a is None:
            return True
        parts_a = self._type_arg_list(a)
        parts_b = self._type_arg_list(b)
        if bindings is None:
            bindings = {}
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
        self, node: Any, _seen: frozenset = frozenset()
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
        if node is not None and node.type == "tuple_type":
            # `(P, Q)` carries no head type — its args key lists the
            # element spellings so destructuring patterns can type
            # each bound name by position.
            return None, ", ".join(
                re.sub(r"\s+", " ", self.text(child)).strip()
                for child in self._children(node)
            )
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
                and record.binding.kind == "type_alias"
                and record.binding.id not in _seen
                and record.alias_node is not None
            ):
                resolved, resolved_args = (
                    self._annotation_type_in_record_scope(record, _seen)
                )
                if resolved_args is not None and args is not None:
                    params_node = record.alias_node.parent
                    param_names = (
                        []
                        if params_node is None
                        else self._type_param_names(
                            params_node.child_by_field_name("type_parameters")
                        )
                    )
                    if param_names:
                        mapping = dict(
                            zip(param_names, self._type_arg_list(args))
                        )
                        resolved_args = re.sub(
                            r"\b(" + "|".join(
                                re.escape(name) for name in mapping
                            ) + r")\b",
                            lambda m: mapping[m.group(1)],
                            resolved_args,
                        )
                return resolved, resolved_args
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
        record = self._through_import(
            self._lookup(
                self._normalize_identifier(self.text(node)),
                node.start_byte,
                "type",
            ),
            node.start_byte,
        )
        name = self._normalize_identifier(self.text(node))
        if (
            record is not None
            and record.binding.kind == "type_alias"
            and record.binding.id not in _seen
            and record.alias_node is not None
        ):
            # `type A = B` — the alias spells the same type, so a
            # receiver typed by `A` resolves `B`'s members.
            resolved, resolved_args = self._annotation_type_in_record_scope(
                record, _seen
            )
            if resolved_args is not None and args is not None:
                # `type Alias<B> = W<B>` at `Alias<u8>` reads
                # `W<u8>` — substitute the alias's declared params
                # with the spelled args.
                params_node = record.alias_node.parent
                param_names = (
                    []
                    if params_node is None
                    else self._type_param_names(
                        params_node.child_by_field_name("type_parameters")
                    )
                )
                if param_names:
                    mapping = dict(
                        zip(param_names, self._type_arg_list(args))
                    )
                    resolved_args = re.sub(
                        r"\b(" + "|".join(
                            re.escape(name) for name in mapping
                        ) + r")\b",
                        lambda m: mapping[m.group(1)],
                        resolved_args,
                    )
            return resolved, resolved_args
        if name in {"HashMap", "BTreeMap"} and args is not None:
            # A std map indexes to its value type — `m[k]` : V, not
            # the key-value pair. Applies whether the name resolves
            # (e.g. imported) or stays unresolved.
            parts = self._type_arg_list(args)
            args = parts[-1] if parts else None
        return (None if record is None else record.binding.id), args

    def _resolve_use_path(
        self, path: str, position: int, namespace: str,
        _seen: "set[str] | None" = None,
    ) -> "_Record | None":
        """Record a `use` target path names — `m::P` walks the module
        chain and returns `P`'s own binding in `namespace` (a name
        that only exists in the other namespace does not resolve)."""
        segments = path.split("::")
        if len(segments) < 2:
            return None
        module = self._lookup_module_path(
            "::".join(segments[:-1]), position
        )
        if module is not None and module.module_scope is not None:
            for record in reversed(
                module.module_scope.bindings.get(segments[-1], ())
            ):
                if self._in_namespace(record, namespace):
                    return record
            return None
        # The container is not a module — `use E::V` names a member
        # of a type (enum variant, associated item), `use m::E::V`
        # the same through a module chain.
        container = self._use_path_container(
            segments[:-1], position, _seen
        )
        if container is None:
            return None
        for record in self.records.values():
            if (
                record.member_of == container.binding.id
                and record.binding.name == segments[-1]
                and self._in_namespace(record, namespace)
            ):
                return record
        return None

    def _use_path_container(
        self, segments: list, position: int,
        seen: "set[str] | None" = None,
    ) -> "_Record | None":
        """Type record a `use` path's non-module container names —
        `E` itself or `m::E` inside module `m`."""
        if len(segments) == 1:
            return self._through_import(
                self._lookup(
                    self._normalize_identifier(segments[0]),
                    position,
                    "type",
                ),
                position,
                _seen=seen,
            )
        module = self._lookup_module_path(
            "::".join(segments[:-1]), position
        )
        if module is None or module.module_scope is None:
            return None
        for record in reversed(
            module.module_scope.bindings.get(segments[-1], ())
        ):
            if self._in_namespace(record, "type"):
                return record
        return None

    def _through_import(
        self, record: "_Record | None", position: int,
        namespace: str = "type",
        _seen: "set[str] | None" = None,
    ) -> "_Record | None":
        """Follow `import` records to their use-path target —
        `use m::P` makes `P::new` read `m`'s `P`. The path resolves
        where the `use` is declared, not at the reference site, and
        an unresolvable target keeps the import record itself (the
        name is still what `impl Trait for P` matches against)."""
        seen: set[str] = set() if _seen is None else _seen
        while (
            record is not None
            and record.binding.kind == "import"
            and record.import_path is not None
            and record.binding.id not in seen
        ):
            seen.add(record.binding.id)
            resolved = self._resolve_use_path(
                record.import_path,
                record.binding.span.start,
                namespace,
                seen,
            )
            if resolved is None:
                break
            record = resolved
        return record

    def _lookup_module_path(
        self, path: str, position: int
    ) -> "_Record | None":
        """Module record of a `use` path — `a::b` walks the module
        chain through each member's body scope."""
        module = None
        for segment in path.split("::"):
            if module is None:
                module = self._lookup_module(segment, position)
            else:
                if module.module_scope is None:
                    return None
                module = next(
                    (
                        record
                        for record in reversed(
                            module.module_scope.bindings.get(segment, ())
                        )
                        if record.binding.kind == "module"
                    ),
                    None,
                )
            if module is None:
                return None
        return module

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
            member.body_node = variant.child_by_field_name("body")
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
            record = self._through_import(
                self._lookup(
                    self._normalize_identifier(self.text(path)),
                    path.start_byte,
                    "type",
                ),
                path.start_byte,
            )
            type_id, args = (
                None
                if record is None
                else self._concrete_type_id(record.binding.id)
            ), None
        elif path.type in {"scoped_identifier", "scoped_type_identifier"}:
            record = self._scoped_type(path)
            type_id, args = (
                None
                if record is None
                else self._concrete_type_id(record.binding.id)
            ), None
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
            return self._trait_visible(trait, position)

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
                if not self._trait_visible(trait, position):
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

    def _concrete_type(
        self, type_id: str | None, args: str | None
    ) -> tuple[str | None, str | None]:
        """(type id, args) after following `type` alias chains — the
        alias target's own arguments win (`type A = W<u8>` spells
        `W<u8>` for an `<A as T>::m` receiver)."""
        seen: set[str] = set()
        while type_id is not None and type_id not in seen:
            seen.add(type_id)
            record = self.records.get(type_id)
            if (
                record is None
                or record.binding.kind != "type_alias"
                or record.alias_node is None
            ):
                break
            resolved, resolved_args = (
                self._annotation_type_in_record_scope(record)
            )
            if resolved is None or resolved == type_id:
                break
            type_id = resolved
            if resolved_args is not None:
                # `type Alias<B> = W<B>` at `Alias<u8>` — substitute
                # the alias's declared params with the spelled args.
                params_node = record.alias_node.parent
                param_names = (
                    []
                    if params_node is None
                    else self._type_param_names(
                        params_node.child_by_field_name("type_parameters")
                    )
                )
                if param_names and args is not None:
                    mapping = dict(
                        zip(param_names, self._type_arg_list(args))
                    )
                    resolved_args = re.sub(
                        r"\b(" + "|".join(
                            re.escape(name) for name in mapping
                        )
                        + r")\b",
                        lambda match: mapping[match.group(1)],
                        resolved_args,
                    )
                args = resolved_args
        return type_id, args

    def _annotation_type_in_record_scope(
        self, record: "_Record", _seen: frozenset = frozenset()
    ) -> tuple[str | None, str | None]:
        """`_annotation_type` on a record's alias body, evaluated in
        the scope the alias was declared into — module members are
        visible only inside their module scope, not from the
        use-site scope stack."""
        scope = record.home_scope
        push = scope is not None and scope not in self.scopes
        if push:
            self.scopes.append(scope)
        try:
            return self._annotation_type(
                record.alias_node, _seen | {record.binding.id}
            )
        finally:
            if push:
                self.scopes.pop()

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
            resolved, _ = self._annotation_type_in_record_scope(record)
            if resolved is None or resolved == type_id:
                return type_id
            type_id = resolved
        return type_id

    def _trait_visible(
        self, trait: "_Record", position: int
    ) -> bool:
        """Whether `trait` is in scope at `position` — directly, or
        through an import whose use path lands on it (`use m::Tr`,
        `use m::Tr as Q`). An import record stands for an externally
        declared trait: only its own binding satisfies membership."""
        resolved = self._through_import(
            self._lookup(trait.binding.name, position, "type"),
            position,
        )
        if resolved is trait:
            return True
        if trait.binding.kind == "import":
            return False
        # A `use` is name-visible only inside its own module — neither
        # `use` nor `pub use` in a parent module brings the name into a
        # nested `mod` (that needs `use super::Tr`). The span check keeps
        # block-local `use` scoped to its block; the depth check drops a
        # parent module's `use`, whose span encloses nested mods.
        depth = (
            self.scopes[-1].module_depth
            if self.scopes
            else self.module_depth
        )
        for scope in self.scopes:
            for records in scope.bindings.values():
                for candidate in records:
                    if (
                        candidate.binding.kind == "import"
                        and candidate.module_depth == depth
                        and (
                            candidate.binding.scope is None
                            or candidate.binding.scope
                            == ByteSpan(0, 0)
                            or (
                                candidate.binding.scope.start
                                <= position
                                < candidate.binding.scope.end
                            )
                        )
                        and self._through_import(candidate, position)
                        is trait
                    ):
                        return True
        return False

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
        return self._through_import(
            self._lookup(
                self._normalize_identifier(self.text(node)),
                node.start_byte,
                "type",
            ),
            node.start_byte,
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
        type_id, impl_args = self._concrete_type(type_id, impl_args)
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
        # P` must not answer for it. One shared bindings map unifies
        # the two sides: `A = u8` fixed by `T<A>` also constrains the
        # impl type `W<A>` against the receiver `W<V<u16>>`.
        _, trait_args = self._annotation_type(trait_node)

        def ufcs_args_match(record: _Record) -> bool:
            bindings: dict[str, str] = {}
            params = record.member_impl_type_params
            if trait_args is not None and not self._type_args_match(
                record.member_trait_args, trait_args, params, bindings
            ):
                return False
            if impl_args is None and record.member_impl_args is not None:
                # `<W as T>::m` omits the receiver's arguments — only
                # an impl whose every arg is a distinct parameter still
                # applies (`impl<A> T for W<A>`); `impl<A> T for
                # W<A, A>` would need the same parameter at both
                # positions, which an omitted list cannot satisfy.
                parts = self._type_arg_list(record.member_impl_args)
                return all(part in params for part in parts) and len(
                    set(parts)
                ) == len(parts)
            return self._type_args_match(
                record.member_impl_args, impl_args, params, bindings
            )

        pool = [
            record
            for record in self.records.values()
            if record.member_of == type_id
            and record.binding.name == name
            and record.member_trait == trait.binding.id
            and ufcs_args_match(record)
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

    def _field_member_typed(
        self, node: Any, kinds: tuple[str, ...] = ()
    ) -> "tuple[_Record | None, str | None, str | None]":
        """(member record, receiver type id, receiver args) for
        `expr.name` — the receiver type is returned so callers do not
        resolve `value` twice (once here, once in
        `_member_declared_type`)."""
        value = node.child_by_field_name("value")
        field_node = node.child_by_field_name("field")
        if field_node is None:
            return None, None, None
        name = self.text(field_node).strip()
        if not name or name[0].isdigit():
            # Tuple fields are positional; honest opaque.
            return None, None, None
        type_id, impl_args = self._receiver_type(value)
        return (
            self._member_record(
                type_id, name, kinds, impl_args, node.start_byte
            ),
            type_id,
            impl_args,
        )

    def _unwrapped(
        self,
        callee: Any,
        position: int,
        receiver: "tuple[str | None, str | None]",
    ) -> tuple[str | None, str | None]:
        """(type id, args) of `recv.<unwrap-family>()`, where the
        receiver's declared head is `Option`/`Result` — `unwrap`,
        `expect`, `unwrap_or*` and `unwrap_unchecked` yield the first
        type argument (`P`), `unwrap_err`/`expect_err` the second
        (`E`). Other receivers and names stay opaque — `Vec<P>`
        exposes no `unwrap`. `receiver` is the callee's resolved
        receiver type — the caller already computed it once."""
        value = callee.child_by_field_name("value")
        method_node = callee.child_by_field_name("field")
        if value is None or method_node is None:
            return None, None
        method = self._normalize_identifier(self.text(method_node))
        if method in _UNWRAP_OK_METHODS:
            heads, index = _TRY_HEADS, 0
        elif method in _UNWRAP_ERR_METHODS:
            heads, index = {"Result"}, 1
        else:
            return None, None
        value_id, value_args = receiver
        head, spelled_pos, args_scope = self._scrutinee_shape(
            value, value_id
        )
        if head not in heads:
            return None, None
        if spelled_pos is None:
            # A resolved scrutinee id carries no annotation position
            # — walk the declaration to recover one, or the spelled
            # args would resolve at the call site and hit shadows.
            _, spelled_pos, _ = self._scrutinee_shape(value, None)
        decl_scope = None
        ret = None
        if value.type == "call_expression":
            # `o.unwrap()` reads the args the method's return
            # annotation wrote (`fn get(&self) -> Option<Q>`) —
            # resolving at the receiver's own annotation position
            # picks up a `Q` shadowed there instead.
            callee = value.child_by_field_name("function")
            member = (
                self._field_member(callee, ("associated_function",))
                if callee is not None
                and callee.type == "field_expression"
                else None
            )
            if member is not None and member.type_node is not None:
                ret = (
                    member.type_node.child_by_field_name(
                        "return_type"
                    )
                    or member.type_node
                )
                if ret is not None:
                    spelled_pos = ret.start_byte
                    owner = (
                        self.records.get(member.member_of)
                        if member.member_of
                        else None
                    )
                    decl_scope = (
                        owner.home_scope
                        if owner is not None
                        else None
                    )
                    # The substitution map comes from the
                    # receiver's declared container (`w: W<Q>`),
                    # not the call's own return head (`Option`
                    # has no declared record to map params
                    # against).
                    callee_value = callee.child_by_field_name(
                        "value"
                    )
                    receiver_head, receiver_args = (
                        self._receiver_type(callee_value)
                    )
                    container = (
                        None
                        if receiver_head is None
                        else self.records.get(receiver_head)
                    )
                    param_map = (
                        {}
                        if container is None
                        else self._pattern_param_map(
                            container, receiver_args
                        )
                    )
                    member_text = self.text(member.type_node)
                    ret_args = []
                    ret_generics = re.search(
                        r"<([\s\S]*)>",
                        self.text(ret),
                    )
                    if ret_generics is not None:
                        ret_args = [
                            a.strip()
                            for a in self._type_arg_list(
                                ret_generics.group(1)
                            )
                        ]
                    arg_head = (
                        None
                        if index >= len(ret_args)
                        else re.match(
                            r"[A-Za-z_][\w:]*",
                            re.sub(
                                r"^(?:[\s&*()]+|(?:const|mut)\s+|'\w+\s*)+",
                                "",
                                ret_args[index],
                            ),
                        )
                    )
                    if (
                        param_map
                        and arg_head is not None
                        and self._normalize_identifier(arg_head.group(0))
                        in param_map
                        and any(
                            re.search(
                                rf"\b{re.escape(param)}\b",
                                member_text,
                            )
                            for param in param_map
                        )
                    ):
                        # The payload arg spells the container's
                        # own param — it was substituted from the
                        # receiver's annotation, so resolve it
                        # there. A fixed sibling arg (`E` in
                        # `Result<T, E>`) stays in the method's
                        # declaring scope.
                        inner_pos = (
                            self._receiver_annotation_position(
                                callee.child_by_field_name("value")
                            )
                        )
                        if inner_pos is not None:
                            spelled_pos = inner_pos
        args = self._type_arg_list(value_args or "")
        if len(args) <= index:
            return None, None
        if (
            args_scope is None
            and value.type == "field_expression"
        ):
            # Substituted field args are spelled in the receiver's
            # scope — resolve them at the receiver's own annotation,
            # not the field's declaring scope.
            _, inner_pos, _ = self._scrutinee_shape(
                value.child_by_field_name("value"), None
            )
            if inner_pos is not None:
                spelled_pos = inner_pos
        # The payload arg is spelled where the receiver's type was
        # annotated — resolving at the call site picks up a same-named
        # shadow, and the import's record id must not gate on
        # index-element containers.
        arg_pos = position if spelled_pos is None else spelled_pos
        if (
            decl_scope is not None
            and ret is not None
            and arg_pos == ret.start_byte
        ):
            # A fixed arg (`E` in `Result<T, E>`) resolves in the
            # member's declaring scope — a call-site `struct E`
            # must not shadow it.
            self.scopes.append(decl_scope)
            try:
                return self._spelled_type(args[index].strip(), arg_pos)
            finally:
                self.scopes.pop()
        return self._spelled_type(args[index].strip(), arg_pos)

    def _field_member(
        self, node: Any, kinds: tuple[str, ...] = ()
    ) -> _Record | None:
        """Resolve `expr.name` member access against the declared type."""
        return self._field_member_typed(node, kinds)[0]

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
            # A declared element type keeps its own generics —
            # `Vec<W<u8>>` binds the element as `W` with "u8" here so
            # `impl W<u8>` members still match.
            return record.binding.type.type_id, record.type_args
        if record.type_args is not None:
            return None, record.type_args
        if record.value_node is not None:
            return self._receiver_type(record.value_node)
        return None, None

    def _receiver_type(
        self, node: Any
    ) -> tuple[str | None, str | None]:
        """(type id, generic-args key) of a member-access receiver.

        Results are memoized per node — nested receivers otherwise
        re-resolve the same subtree once per fallback path, which
        compounds exponentially on call/field chains."""
        key = (
            None
            if node is None
            else (
                node.type,
                node.start_byte,
                node.end_byte,
                self._resolution_epoch,
            )
        )
        if key is not None and key in self._receiver_memo:
            return self._receiver_memo[key]
        result = self._receiver_type_uncached(node)
        if key is not None:
            # The key carries the declaration epoch — a miss stays
            # cached while the pool is unchanged (shared-subtree
            # chains stay linear) but re-evaluates once a later
            # declaration could name it.
            self._receiver_memo[key] = result
        return result

    def _receiver_type_uncached(
        self, node: Any
    ) -> tuple[str | None, str | None]:
        while node is not None and node.type == "reference_expression":
            # Auto-deref — `&P` calls `P`'s methods.
            node = next(iter(node.named_children), None)
        if node is not None and node.type == "parenthesized_expression":
            inner = self._children(node)
            if len(inner) == 1:
                node = inner[0]
        if node is None:
            return None, None
        if node.type == "type_cast_expression":
            # `x as T` reads as `T` — the cast pins the receiver.
            return self._annotation_type(node.child_by_field_name("type"))
        if node.type == "try_expression":
            # `x?` on `Option<P>`/`Result<P, E>` yields `P`.
            inner = next(iter(self._children(node)), None)
            inner_id, inner_args = self._receiver_type(inner)
            head, spelled_pos, _ = self._scrutinee_shape(
                inner, inner_id
            )
            if head not in _TRY_HEADS:
                return None, None
            if spelled_pos is None:
                _, spelled_pos, _ = self._scrutinee_shape(inner, None)
            first = next(
                iter(self._type_arg_list(inner_args or "")), None
            )
            if first is None:
                return None, None
            return self._spelled_type(
                first.strip(),
                node.start_byte if spelled_pos is None else spelled_pos,
            )
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
            while index is not None and index.type == "parenthesized_expression":
                index = next(iter(self._children(index)), None)
            if index is not None and index.type in {
                "range_expression",
                "range_pattern",
            }:
                # `v[a..b]` is a slice of the element, not the element
                # — encoded as an anonymous collection whose element
                # the next index can still unwrap. A call like
                # `v[f(0..10)]` keeps its integer index.
                return None, elem_args
            args_position, home_scope = self._field_args_scope(
                children[0]
            )
            push = home_scope is not None and home_scope not in self.scopes
            if push:
                self.scopes.append(home_scope)
            try:
                return self._element_of(
                    container_id,
                    elem_args,
                    args_position or node.start_byte,
                )
            finally:
                if push:
                    self.scopes.pop()
        if node.type == "field_expression":
            member, receiver_id, receiver_args = self._field_member_typed(
                node, ("struct_field", "associated_const")
            )
            if member is not None:
                declared = self._member_declared_type(
                    node.child_by_field_name("value"), member,
                    node.start_byte,
                    (receiver_id, receiver_args),
                )
                if declared is not None:
                    return declared
                return self._record_type(member, node.start_byte)
            value_node = node.child_by_field_name("value")
            field_node = node.child_by_field_name("field")
            element = self._tuple_element_node(value_node, field_node)
            if element is not None:
                return self._annotation_type(element)
            # `p.0` on a spelled tuple binding (`for p in a.zip(b)`)
            # has no annotation node — index into the spelled args.
            # A named head (`W<P>`) keeps its args as generic
            # parameters, not field types — `struct Swap<A,B>(B,A)`
            # orders its fields differently, so `t.0` stays opaque
            # unless the declared fields resolved above.
            if field_node is not None:
                index_text = self.text(field_node).strip()
                if index_text.isdigit():
                    head, spelled_args = self._receiver_type(
                        value_node
                    )
                    if head is None and spelled_args is not None:
                        spelled_args = spelled_args.strip()
                        wrapped = self._paren_wraps(spelled_args)
                        spelled = self._type_arg_list(
                            spelled_args[1:-1] if wrapped else spelled_args
                        )
                        index = int(index_text)
                        if (wrapped or len(spelled) > 1) and index < len(spelled):
                            return self._spelled_type(
                                spelled[index],
                                self._receiver_annotation_position(
                                    value_node
                                )
                                or node.start_byte,
                            )
            return None, None
        if node.type == "call_expression":
            callee_node = node.child_by_field_name("function")
            callee = (
                None if callee_node is None else self._callee(callee_node)
            )
            if callee is not None and callee.type == "generic_function":
                callee = callee.child_by_field_name("function")
            member = None
            receiver: "tuple[str | None, str | None]" = (None, None)
            if (
                callee is not None
                and callee.type == "field_expression"
                and callee_node is not None
                and callee_node.type == "parenthesized_expression"
            ):
                # `(w.f)()` invokes the field's function pointer — a
                # struct_field of that name shadows the method.
                field, frecv_id, frecv_args = self._field_member_typed(
                    callee, ("struct_field",)
                )
                if field is not None:
                    fn_ret = (
                        None
                        if field.type_node is None
                        else field.type_node.child_by_field_name(
                            "return_type"
                        )
                    )
                    if fn_ret is None:
                        # `f: F` where `F: Deref<Target = fn()>` —
                        # the field is not spelled as a function
                        # pointer, so calling it stays opaque rather
                        # than binding to F's own members.
                        return None, None
                    declared = self._member_declared_type(
                        callee.child_by_field_name("value"),
                        field,
                        node.start_byte,
                        (frecv_id, frecv_args),
                        fn_ret,
                    )
                    return (
                        (None, None) if declared is None else declared
                    )
            if callee is not None and callee.type == "field_expression":
                member, recv_id, recv_args = self._field_member_typed(
                    callee, ("associated_function",)
                )
                receiver = (recv_id, recv_args)
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
                field = (
                    callee.child_by_field_name("field")
                    if callee is not None
                    and callee.type == "field_expression"
                    else None
                )
                if field is not None and receiver[1] is not None:
                    option_head = _OPTION_HEAD_METHODS.get(
                        self.text(field).strip()
                    )
                else:
                    option_head = None
                if (
                    option_head is not None
                    and (
                        option_head[1] is None
                        or self._container_head_name(
                            callee.child_by_field_name("value")
                        ) in option_head[1]
                    )
                ):
                    prefix = option_head[0]
                    # `v.get(i)`/`v.first()`/`v.pop()` yield
                    # `Option<&T>`/`Option<T>` — only the payload
                    # spelling is carried; the head stays for
                    # `_scrutinee_shape` to declare.
                    elements = self._type_arg_list(receiver[1])
                    index = option_head[2]
                    element = (
                        elements[index].strip()
                        if -len(elements) <= index < len(elements)
                        else None
                    )
                    if element:
                        return None, prefix + element
                if (
                    callee is not None
                    and callee.type == "field_expression"
                ):
                    # Iterator chains (`v.iter()`, `it.zip(u)` …)
                    # spell their element from the receiver's args.
                    spelled = self._iterator_spelling(node)
                    if spelled is not None:
                        return None, spelled
                    return self._unwrapped(
                        callee, node.start_byte, receiver
                    )
                return None, None
            if member.binding.kind == "enum_member":
                # A variant constructor spells its enum — `E::C(P)`
                # constructs an `E`.
                return self._concrete_type_id(member.member_of), None
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
            annotated = self._member_declared_type(
                callee.child_by_field_name("value")
                if callee is not None and callee.type == "field_expression"
                else None,
                member,
                node.start_byte,
                receiver,
            )
            if annotated is None:
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
        if node.type in {"scoped_identifier", "scoped_type_identifier"}:
            # A unit variant spells its enum — `let e = E::F` is an `E`.
            member, _ = self._scoped_member(node)
            if member is not None and member.binding.kind == "enum_member":
                return self._concrete_type_id(member.member_of), None
            return None, None
        if node.type == "parenthesized_expression":
            children = self._children(node)
            if len(children) == 1:
                return self._receiver_type(children[0])
        return None, None

    def _element_of(
        self,
        container_id: str | None,
        elem_args: str,
        position: int,
    ) -> tuple[str | None, str | None]:
        """(type id, generic-args key) one collection step in —
        `Vec<P>`/`[P; N]`/`&Vec<P>` yield `P`; a resolved container
        whose element is not its generic argument (a custom
        `Wrapper<P>`) stays opaque."""
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
        if elem_args is None:
            # The iterable exposes no spelled args (`for x in
            # std::iter::once(1)` reaches an unresolvable extern
            # call) — the element stays opaque.
            return None, None
        if elem_args.startswith("&"):
            # `&P`/`&mut P`/`&[P]` spell a borrowed element — the
            # receiver of `x.m()`/`x[0]` is `P`.
            inner = elem_args.lstrip("&").strip()
            if inner.startswith("mut "):
                inner = inner[4:].strip()
            return self._element_of(None, inner, position)
        # A slice or array element exposes its own element type —
        # `&[[P; 2]]` reads first to `[P; 2]`, then to `P`.
        bracket = re.fullmatch(
            r"\[(.+?)(?:\s*;.+)?\]", elem_args
        )
        if bracket is not None:
            # The element is an anonymous slice/array — it is indexed
            # further by its own element (`[P; 2]` → `P`), not `P`.
            return None, bracket.group(1).strip()
        match = re.fullmatch(
            r"([A-Za-z_][\w:]*)\s*(?:<(.+)>)?", elem_args
        )
        if match is None:
            # The element is a reference or composite type — keep its
            # text so deeper indexing still reads args.
            return None, elem_args
        # `_spelled_type` follows `use m::P` imports and scoped
        # `m::P` spellings — a bare `_lookup` would miss both.
        return self._spelled_type(elem_args, position)

    def _is_map_container(
        self, container_id: str | None, node: Any | None
    ) -> bool:
        """Whether a receiver's declared container is HashMap/BTreeMap
        — by resolved record name, or by the spelled annotation when
        the prelude name has no record."""
        if container_id is not None:
            name = next(
                (
                    b.name
                    for b in self.bindings
                    if b.id == container_id
                ),
                None,
            )
            return name in _MAP_CONTAINER_NAMES
        if node is not None and node.type == "identifier":
            record = self._lookup(
                self._normalize_identifier(self.text(node)),
                node.start_byte,
                "value",
            )
            if record is not None and record.type_node is not None:
                if (
                    re.search(
                        r"\b(?:HashMap|BTreeMap)\s*<",
                        self.text(record.type_node),
                    )
                    is not None
                ):
                    return True
                pair = self._generic_head_args(
                    record.type_node, node.start_byte
                )
                seen: set[str] = set()
                while pair is not None and pair[1] is not None and (
                    pair[1].binding.kind == "type_alias"
                    and pair[1].alias_node is not None
                    and pair[1].binding.id not in seen
                ):
                    seen.add(pair[1].binding.id)
                    pair = self._generic_head_args(
                        pair[1].alias_node, node.start_byte
                    )
                return pair is not None and pair[2] in _MAP_CONTAINER_NAMES
        return False

    def _generic_head_args(
        self, type_node: Any | None, position: int
    ) -> "tuple[str | None, _Record | None, str | None] | None":
        """(spelled args, head record, spelled head) of a generic
        annotation — `HashMap<K, V>` gives ("K, V", HashMap's
        record, "HashMap"); a bare `Flip` has no args (None key)
        but still names its head."""
        node = type_node
        while node is not None and node.type in {
            "reference_type",
            "generic_type",
            "generic_type_with_turbofish",
        }:
            if node.type != "reference_type":
                key = self._type_args_key(
                    node.child_by_field_name("type_arguments")
                )
                if key is not None:
                    head = node.child_by_field_name("type")
                    record = (
                        None
                        if head is None
                        or head.type
                        not in {"identifier", "type_identifier"}
                        else self._lookup(
                            self._normalize_identifier(
                                self.text(head)
                            ),
                            position,
                            "type",
                        )
                    )
                    name = (
                        None
                        if head is None
                        else self._normalize_identifier(self.text(head))
                    )
                    return key, record, name
            node = node.child_by_field_name("type")
        if node is not None and node.type in {
            "identifier",
            "type_identifier",
        }:
            record = self._lookup(
                self._normalize_identifier(self.text(node)),
                position,
                "type",
            )
            return None, record, self._normalize_identifier(
                self.text(node)
            )
        return None

    def _map_spelled_args(self, receiver: Any | None) -> str | None:
        """Full `<K, V>` argument key of a map annotation — recovered
        from the receiver's type node because `_annotation_type`
        reduces map args to the value type."""
        node = receiver
        while node is not None and node.type == "reference_expression":
            node = next(iter(node.named_children), None)
        if node is None or node.type != "identifier":
            return None
        record = self._lookup(
            self._normalize_identifier(self.text(node)),
            node.start_byte,
            "value",
        )
        tnode = None if record is None else record.type_node
        # The annotation's `M` is resolved where it was written — a
        # same-named alias declared inside the loop's scope must not
        # steal the expansion (`type M = HashMap<A, B>` then an inner
        # `type M = HashMap<B, A>` would swap key and value types).
        pair = self._generic_head_args(
            tnode, None if tnode is None else tnode.start_byte
        )
        if pair is None:
            return None
        key, head, _ = pair
        seen: set[str] = set()
        # `type Flip<A, B> = HashMap<B, A>` — the alias's args must
        # be substituted into the body's spelling, not read raw.
        while (
            head is not None
            and head.binding.kind == "type_alias"
            and head.alias_node is not None
            and head.binding.id not in seen
        ):
            seen.add(head.binding.id)
            body_pair = self._generic_head_args(
                head.alias_node, head.alias_node.start_byte
            )
            if body_pair is None or body_pair[0] is None:
                break
            item = head.alias_node.parent
            names = self._type_param_names(
                None
                if item is None
                else item.child_by_field_name("type_parameters")
            )
            args = self._type_arg_list(key or "")
            if not names or len(args) < len(names):
                break
            mapping = dict(zip(names, args))
            key = re.sub(
                r"\b(" + "|".join(
                    re.escape(name) for name in mapping
                ) + r")\b",
                lambda m: mapping[m.group(1)],
                body_pair[0],
            )
            head = body_pair[1]
        return key

    def _receiver_annotation_position(
        self, receiver: Any | None
    ) -> "int | None":
        """Start byte of the annotation that typed this receiver —
        spelled element names resolve against the names visible
        there, not at the call site."""
        node = receiver
        while node is not None and node.type == "reference_expression":
            node = next(iter(node.named_children), None)
        if node is None:
            return None
        if node.type == "field_expression":
            member = self._field_member(
                node, ("struct_field", "associated_const")
            )
            if member is None or member.type_node is None:
                element = self._tuple_element_node(
                    node.child_by_field_name("value"),
                    node.child_by_field_name("field"),
                )
                return None if element is None else element.start_byte
            return member.type_node.start_byte
        if node.type == "call_expression":
            # `v.iter()`/`v.first()` spelled names were written in
            # the receiver's annotation — follow the call's value.
            callee = node.child_by_field_name("function")
            if callee is not None and callee.type == "field_expression":
                return self._receiver_annotation_position(
                    callee.child_by_field_name("value")
                )
            return None
        if node.type != "identifier":
            return None
        record = self._lookup(
            self._normalize_identifier(self.text(node)),
            node.start_byte,
            "value",
        )
        if record is None:
            return None
        if record.type_node is not None:
            return record.type_node.start_byte
        if record.value_node is not None and (
            record.value_node is not node
        ):
            # `let it = v.iter()` — the iterator's spelled element
            # names were written in `v`'s annotation.
            return self._receiver_annotation_position(
                record.value_node
            )
        return None

    def _field_args_position(
        self, field_expr: Any | None
    ) -> "int | None":
        """Scope position resolving a field access's spelled args —
        the receiver's annotation when the field type spells the
        container's own params (substituted args were written at the
        use site), else the field's declaration (a fixed `Vec<Q>`
        keeps `Q` in the field's scope, not a same-named local)."""
        if field_expr is None or field_expr.type != "field_expression":
            return self._receiver_annotation_position(field_expr)
        member = self._field_member(
            field_expr, ("struct_field", "associated_const")
        )
        if member is None or member.type_node is None:
            return None
        value = field_expr.child_by_field_name("value")
        type_id, impl_args = (
            (None, None) if value is None
            else self._receiver_type(value)
        )
        container = (
            None if type_id is None else self.records.get(type_id)
        )
        param_map = (
            {}
            if container is None
            else self._pattern_param_map(container, impl_args)
        )
        if param_map:
            member_text = self.text(member.type_node)
            if any(
                re.search(rf"\b{re.escape(param)}\b", member_text)
                for param in param_map
            ):
                return (
                    self._receiver_annotation_position(value)
                    or field_expr.start_byte
                )
        return member.type_node.start_byte

    def _spelling_scope_stable(
        self, spelled: str, pos_a: int | None, pos_b: int | None
    ) -> bool:
        """Whether every name in `spelled` resolves to the same
        record at both positions — guards a spelling whose names
        were written at `pos_a` but are consumed at `pos_b` (a zip
        pair carries names from two annotations)."""
        if pos_a is None or pos_b is None or pos_a == pos_b:
            return True
        for token in re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b", spelled
        ):
            a = self._lookup(token, pos_a, "type")
            b = self._lookup(token, pos_b, "type")
            if (None if a is None else a.binding.id) != (
                None if b is None else b.binding.id
            ):
                return False
        return True

    def _iterator_spelling(
        self, call: Any, _depth: int = 0
    ) -> "str | None":
        """Element spelling of an iterator chain — `v.iter()` on
        `Vec<P>` spells `P`, `v.iter().zip(u.iter())` spells
        `(P, Q)`, `enumerate` spells `(usize, P)`. Only undeclared
        std adaptors apply; a declared method's real return type is
        what `_iterator_method_element` types instead."""
        return self._iterator_spelling_with_pos(call, _depth)[0]

    def _iterator_spelling_with_pos(
        self, call: Any, _depth: int = 0
    ) -> "tuple[str | None, int | None]":
        """(spelling, annotation position) — the position is where
        the container's element names were written, so they resolve
        in the annotating scope rather than at the use site. A zip
        whose sides were annotated in different scopes stays
        unpinned when the names would resolve differently."""
        if _depth > 8:
            return None, None
        key = (
            call.start_byte,
            call.end_byte,
            self._resolution_epoch,
        )
        if key in self._spelling_memo:
            return self._spelling_memo[key]
        result = self._iterator_spelling_uncached(call, _depth)
        self._spelling_memo[key] = result
        return result

    def _iterator_spelling_uncached(
        self, call: Any, _depth: int
    ) -> "tuple[str | None, int | None]":
        callee = call.child_by_field_name("function")
        if callee is None or callee.type != "field_expression":
            return None, None
        if (
            self._field_member(callee, ("associated_function",))
            is not None
        ):
            return None, None
        method_node = callee.child_by_field_name("field")
        receiver = callee.child_by_field_name("value")
        if method_node is None or receiver is None:
            return None, None
        method = self._normalize_identifier(self.text(method_node))
        if method in _ITER_ELEMENT_METHODS:
            container_id, args = self._receiver_type(receiver)
            if args is None:
                return None, None
            if self._is_map_container(container_id, receiver):
                # `m.iter()` yields `(K, V)` — recover both halves
                # from the annotation since index typing keeps V.
                spelled = self._map_spelled_args(receiver)
                return (
                    (None, None)
                    if spelled is None
                    else (
                        f"({spelled})",
                        self._receiver_annotation_position(receiver),
                    )
                )
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
                    # A custom `W<P>` can `Deref` to a different
                    # element — its args are not the iterated
                    # element's type.
                    return None, None
            spelled = args.strip() or None
            if spelled is None:
                return None, None
            return spelled, self._receiver_annotation_position(
                receiver
            )
        if method in _ITER_CHUNK_METHODS:
            container_id, args = self._receiver_type(receiver)
            if args is None:
                return None, None
            container_name = (
                next(
                    (
                        b.name
                        for b in self.bindings
                        if b.id == container_id
                    ),
                    None,
                )
                if container_id is not None
                else None
            )
            if (
                container_id is not None
                and container_name not in _INDEX_ELEMENT_CONTAINERS
            ):
                # A custom `W<P>` can `Deref` to a different
                # element — `w.chunks(n)` yields `&[Q]` there,
                # not `&[P]`.
                return None, None
            spelled = args.strip() or None
            if spelled is None:
                return None, None
            # The element is a borrowed slice — `&P` unwraps to `P`
            # at the index/iter sites that consume it.
            return (
                "&" + spelled,
                self._receiver_annotation_position(receiver),
            )
        if method in _ITER_PRESERVING_METHODS or method in _ITER_SLICE_METHODS:
            if receiver.type != "call_expression":
                return None, None
            return self._iterator_spelling_with_pos(
                receiver, _depth + 1
            )
        if method == "enumerate":
            if receiver.type != "call_expression":
                return None, None
            inner, pos = self._iterator_spelling_with_pos(
                receiver, _depth + 1
            )
            return (
                (None, None)
                if inner is None
                else (f"(usize, {inner})", pos)
            )
        if method == "zip":
            if receiver.type != "call_expression":
                return None, None
            args_node = call.child_by_field_name("arguments")
            zipped = (
                None
                if args_node is None
                else next(
                    (
                        child
                        for child in self._children(args_node)
                        if child.type == "call_expression"
                    ),
                    None,
                )
            )
            if zipped is None:
                return None, None
            left, left_pos = self._iterator_spelling_with_pos(
                receiver, _depth + 1
            )
            right, right_pos = self._iterator_spelling_with_pos(
                zipped, _depth + 1
            )
            if left is None or right is None:
                return None, None
            position = (
                left_pos if left_pos is not None else right_pos
            )
            if (
                left_pos is not None
                and right_pos is not None
                and left_pos != right_pos
                and not (
                    self._spelling_scope_stable(
                        left, left_pos, position
                    )
                    and self._spelling_scope_stable(
                        right, right_pos, position
                    )
                )
            ):
                # The two sides' names were written where different
                # bindings are visible — resolving them at one
                # position could bind the wrong same-named type.
                return None, None
            return f"({left}, {right})", position
        return None, None

    def _field_args_scope(
        self, field_expr: Any | None
    ) -> "tuple[int | None, _Scope | None]":
        """(position, scope) resolving a field access's spelled
        args — the receiver's annotation when the field type spells
        the container's own params (substituted args were written at
        the use site), else the field's declaration position plus
        its home scope pushed (a fixed `Vec<Q>` keeps `Q` in the
        field's scope — module members are not reachable from the
        use-site stack)."""
        if field_expr is None or field_expr.type != "field_expression":
            return self._receiver_annotation_position(field_expr), None
        member = self._field_member(
            field_expr, ("struct_field", "associated_const")
        )
        if member is None or member.type_node is None:
            return None, None
        value = field_expr.child_by_field_name("value")
        type_id, impl_args = (
            (None, None) if value is None
            else self._receiver_type(value)
        )
        container = (
            None if type_id is None else self.records.get(type_id)
        )
        param_map = (
            {}
            if container is None
            else self._pattern_param_map(container, impl_args)
        )
        if param_map:
            member_text = self.text(member.type_node)
            inner = re.search(r"<([\s\S]*)>", member_text)
            elem_text = (
                inner.group(1) if inner else member_text
            ).strip()
            elem_head = re.match(r"[A-Za-z_][\w:]*", elem_text)
            if elem_head is not None and (
                self._normalize_identifier(elem_head.group(0)).rsplit(
                    "::", 1
                )[-1]
                not in param_map
            ):
                # `Vec<Fixed<T>>` — the element head `Fixed` was
                # spelled in the field's scope; only the substituted
                # args came from the receiver's annotation site, and
                # they stay spelled for downstream consumers.
                return (
                    member.type_node.start_byte,
                    None if container is None else container.home_scope,
                )
            if any(
                re.search(rf"\b{re.escape(param)}\b", member_text)
                for param in param_map
            ):
                return (
                    self._receiver_annotation_position(value)
                    or field_expr.start_byte
                ), None
        return (
                    member.type_node.start_byte,
                    None if container is None else container.home_scope,
                )

    def _iterator_method_element(
        self, call: Any
    ) -> "tuple[TypeFact, str | None]":
        """(TypeFact, element-args) for `for <pat> in c.iter()` kin —
        `iter`/`iter_mut`/`into_iter`/`drain` yield the container's
        element (maps iterate (K, V) pairs and stay unpinned);
        `keys()`/`values()` on HashMap/BTreeMap yield its
        first/second arg. Chained or unresolvable calls stay
        `_UNKNOWN`."""
        callee = call.child_by_field_name("function")
        if callee is None or callee.type != "field_expression":
            # Not a method call — `for p in make()` iterates whatever
            # the call's own declared return type yields.
            container_id, args = self._receiver_type(call)
            if self._is_map_container(container_id, call):
                return _UNKNOWN, None
            elem_id, rest = self._element_of(
                container_id,
                None if args is None else args.strip(),
                call.start_byte,
            )
            if elem_id is None:
                return _UNKNOWN, rest
            name = next(
                (b.name for b in self.bindings if b.id == elem_id), ""
            )
            return TypeFact("named", name, 0, None, elem_id), rest
        method_node = callee.child_by_field_name("field")
        receiver = callee.child_by_field_name("value")
        if method_node is None or receiver is None:
            return _UNKNOWN, None
        method = self._normalize_identifier(self.text(method_node))
        if (
            method in _ITER_ELEMENT_METHODS
            or method in _MAP_ELEMENT_METHODS
            or method in _ITER_PRESERVING_METHODS
            or method in _ITER_SLICE_METHODS
            or method in _ITER_CHUNK_METHODS
            or method == "enumerate"
            or method == "zip"
        ) and self._field_member(
            callee, ("associated_function",)
        ) is not None:
            # The call resolves to a declared method — a user
            # `iter()` need not yield the container's element, so
            # iterate its declared return type instead of the std
            # recipe.
            container_id, args = self._receiver_type(call)
            if self._is_map_container(container_id, call):
                return _UNKNOWN, None
            elem_id, rest = self._element_of(
                container_id,
                None if args is None else args.strip(),
                call.start_byte,
            )
            if elem_id is None:
                return _UNKNOWN, rest
            name = next(
                (b.name for b in self.bindings if b.id == elem_id), ""
            )
            return TypeFact("named", name, 0, None, elem_id), rest
        if method in _ITER_CHUNK_METHODS:
            # `v.chunks(n)` yields `&[P]` slices — spell `&P`, which
            # index/iter sites unwrap to `P`.
            container_id, args = self._receiver_type(receiver)
            if args is None:
                return _UNKNOWN, None
            container_name = (
                next(
                    (
                        b.name
                        for b in self.bindings
                        if b.id == container_id
                    ),
                    None,
                )
                if container_id is not None
                else None
            )
            if (
                container_id is not None
                and container_name not in _INDEX_ELEMENT_CONTAINERS
            ):
                # A custom `W<P>` can `Deref` to a different
                # element — `w.chunks(n)` yields `&[Q]` there,
                # not `&[P]`.
                return _UNKNOWN, None
            spelled = args.strip() or None
            return _UNKNOWN, None if spelled is None else "&" + spelled
        if method in _ITER_PRESERVING_METHODS:
            # `v.iter().rev()` yields the inner call's element —
            # recurse into the chained receiver. A non-call receiver
            # (`x.rev()` on a bare value) is not a std recipe — opaque.
            if receiver.type != "call_expression":
                return _UNKNOWN, None
            return self._iterator_method_element(receiver)
        if method == "enumerate":
            # `v.iter().enumerate()` yields `(usize, E)` — the spelled
            # pair feeds the tuple-pattern path so `(i, p)` binds `p`
            # by the element type while `usize` stays unpinned.
            if receiver.type != "call_expression":
                return _UNKNOWN, None
            inner_callee = receiver.child_by_field_name("function")
            if inner_callee is None or inner_callee.type != "field_expression":
                return _UNKNOWN, None
            inner_method = inner_callee.child_by_field_name("field")
            inner_receiver = inner_callee.child_by_field_name("value")
            if inner_method is None or inner_receiver is None:
                return _UNKNOWN, None
            if (
                self._normalize_identifier(self.text(inner_method))
                not in _ITER_ELEMENT_METHODS
            ):
                return _UNKNOWN, None
            if (
                self._field_member(
                    inner_callee, ("associated_function",)
                )
                is not None
            ):
                # A declared `iter()` need not yield the container's
                # element — its return type is opaque to the recipe.
                return _UNKNOWN, None
            inner_container, inner_args = self._receiver_type(
                inner_receiver
            )
            if inner_args is None:
                return _UNKNOWN, None
            if inner_container is not None:
                container_name = next(
                    (
                        b.name
                        for b in self.bindings
                        if b.id == inner_container
                    ),
                    None,
                )
                if container_name not in _INDEX_ELEMENT_CONTAINERS:
                    return _UNKNOWN, None
            spelled = inner_args.strip()
            if not spelled:
                return _UNKNOWN, None
            elem_id = None
            rest = f"(usize, {spelled})"
            return _UNKNOWN, rest
        if method == "zip":
            # `a.iter().zip(b.iter())` yields the spelled pair
            # `(A, B)` — it feeds the tuple-pattern path the same
            # way a `(P, Q)` element does; either side unresolvable
            # stays unpinned.
            if receiver.type != "call_expression":
                return _UNKNOWN, None
            spelled = self._iterator_spelling(call)
            return _UNKNOWN, spelled
        container_id, args = self._receiver_type(receiver)
        if args is None:
            return _UNKNOWN, None
        # Spelled element names refer to the types the receiver's
        # annotation wrote — resolve them there, not at the call.
        position = self._receiver_annotation_position(receiver)
        if position is None:
            position = call.start_byte
        if method in _ITER_ELEMENT_METHODS:
            if self._is_map_container(container_id, receiver):
                return _UNKNOWN, None
            if "," in args:
                # The element is a tuple spelling like `(P, Q)` — an
                # identifier binding stays unpinned, but the spelled
                # args feed the tuple-pattern path. Only a genuine
                # sequence container applies — `W<(P, Q)>` can
                # `Deref` to a different element entirely.
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
                        return _UNKNOWN, None
                return _UNKNOWN, args.strip()
            elem_id, rest = self._element_of(
                container_id, args.strip(), position
            )
        elif (index := _MAP_ELEMENT_METHODS.get(method)) is not None:
            if not self._is_map_container(container_id, receiver):
                return _UNKNOWN, None
            if index == 0:
                # `m[k]` typing reduces a map's args to the value
                # type upstream, so `keys()` must recover the spelled
                # argument list from the receiver's annotation.
                spelled = self._map_spelled_args(receiver)
                if spelled is None:
                    return _UNKNOWN, None
                arg = next(iter(self._type_arg_list(spelled)), None)
            else:
                # `values()` reads the value type — already the map's
                # reduced args.
                arg = args
            if arg is None:
                return _UNKNOWN, None
            elem_id, rest = self._spelled_type(arg, position)
        elif method in _ITER_SLICE_METHODS:
            # `v.as_slice()` iterates the same element as `iter()`.
            if "," in args or self._is_map_container(
                container_id, receiver
            ):
                return _UNKNOWN, None
            elem_id, rest = self._element_of(
                container_id, args.strip(), position
            )
        else:
            return _UNKNOWN, None
        if elem_id is None:
            return _UNKNOWN, rest
        name = next(
            (b.name for b in self.bindings if b.id == elem_id), ""
        )
        return TypeFact("named", name, 0, None, elem_id), rest

    def _for_pair_type_map(
        self, pattern: Any | None, iterator: Any | None
    ) -> dict:
        """Pair typings for `for (k, v) in m` — a map iterates its
        `(K, V)` pairs, so a two-name tuple pattern binds K and V.
        `m.iter()`/`into_iter()`/`iter_mut()`/`drain()` only count
        when the call does not resolve to a declared method."""
        if (
            pattern is None
            or pattern.type != "tuple_pattern"
            or iterator is None
        ):
            return {}
        node = iterator
        while node is not None and node.type in {
            "reference_expression",
            "parenthesized_expression",
        }:
            children = [
                child
                for child in self._children(node)
                if child.type != "mutable_specifier"
            ]
            if len(children) != 1:
                return {}
            node = children[0]
        if node is None:
            return {}
        receiver = node
        position = node.start_byte
        if node.type == "call_expression":
            callee = node.child_by_field_name("function")
            if callee is None or callee.type != "field_expression":
                return {}
            method_node = callee.child_by_field_name("field")
            receiver = callee.child_by_field_name("value")
            if method_node is None or receiver is None:
                return {}
            if (
                self._normalize_identifier(self.text(method_node))
                not in _ITER_ELEMENT_METHODS
            ):
                return {}
            if (
                self._field_member(callee, ("associated_function",))
                is not None
            ):
                return {}
        container_id, _ = self._receiver_type(receiver)
        if not self._is_map_container(container_id, receiver):
            return {}
        spelled = self._map_spelled_args(receiver)
        if spelled is None:
            return {}
        parts = self._type_arg_list(spelled)
        if len(parts) != 2:
            return {}
        annotated = self._receiver_annotation_position(receiver)
        if annotated is not None:
            position = annotated
        slots = [
            child
            for child in pattern.children
            if self.text(child).strip() not in {"(", ")", ","}
            and child.type not in {"line_comment", "block_comment"}
        ]
        rest_at = next(
            (
                index
                for index, child in enumerate(slots)
                if child.type == "remaining_field_pattern"
            ),
            None,
        )
        if rest_at is None:
            if len(slots) != 2:
                return {}
            pairs = list(zip(slots, parts))
        else:
            # `for (k, .., v) in m` — `..` swallows middle elements,
            # so the slots before it map to the pair's head and the
            # slots after it to its tail. `for (k, ..) in m` keeps
            # just the key and `for (.., v) in m` just the value.
            front = slots[:rest_at]
            back = slots[rest_at + 1 :]
            if len(front) + len(back) > len(parts):
                return {}
            pairs = list(zip(front, parts[: len(front)])) + list(
                zip(back, parts[len(parts) - len(back) :])
            )
        mapping = {}
        for child, arg in pairs:
            tid, rest = self._spelled_type(arg, position)
            # A nested pattern (`for (k, (a, b)) in m` over
            # `HashMap<K, (P, Q)>`) destructures its arg's own
            # slots instead of binding the pair as a name.
            mapping.update(
                self._pattern_type_map(
                    child, tid, rest,
                    self._type_head_name(tid, rest), position,
                )
            )
        return mapping

    def _for_element(
        self, iterator: Any | None
    ) -> "tuple[TypeFact, str | None]":
        """(TypeFact, element-args) bound by `for <pat> in <iterator>`
        — `Vec<P>`, `[P; N]` and their `&`/`&mut` forms yield `P`; a
        range, an iterator method call or anything else unpinned stays
        `_UNKNOWN`. The args carry the element's own generics
        (`Vec<Vec<P>>` binds `inner : Vec<P>`) so a nested loop keeps
        unwrapping."""
        if iterator is None:
            return _UNKNOWN, None
        while iterator.type == "reference_expression":
            iterator = next(iter(iterator.named_children), None)
            if iterator is None:
                return _UNKNOWN, None
        if iterator.type == "parenthesized_expression":
            children = self._children(iterator)
            if len(children) != 1:
                return _UNKNOWN, None
            iterator = children[0]
        if iterator.type == "call_expression":
            return self._iterator_method_element(iterator)
        container_id, elem_args = self._receiver_type(iterator)
        if elem_args is None or "," in elem_args:
            return _UNKNOWN, None
        # Iterating a map yields (K, V) pairs — index typing keeps
        # only the value type, so the pair's shape is unpinned here.
        if self._is_map_container(container_id, iterator):
            return _UNKNOWN, None
        if elem_args.strip().startswith("&"):
            # `let it = v.chunks(n)` — `it`'s spelled args ARE the
            # element (`&[P]`), not a container's type args.
            return _UNKNOWN, elem_args.strip()
        # Spelled element names on `it` (`let it = v.iter()`) were
        # written in `it`'s annotation — resolve them there.
        position = self._receiver_annotation_position(iterator)
        if iterator.type == "field_expression":
            # `for q in w.xs` — `xs: Vec<T>` substitutes the receiver
            # `w`'s args, so the element name is spelled at `w`'s
            # annotation, not the field's declaring scope; a fixed
            # `xs: Vec<Q>` keeps `Q` in the field's own scope.
            position = self._field_args_position(iterator) or position
        if position is None:
            position = iterator.start_byte
        elem_id, rest = self._element_of(
            container_id, elem_args.strip(), position
        )
        if elem_id is None:
            return _UNKNOWN, rest
        name = next(
            (b.name for b in self.bindings if b.id == elem_id), ""
        )
        return TypeFact("named", name, 0, None, elem_id), rest

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
        member_impl_type_params: frozenset = frozenset(),
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
                record.member_impl_type_params = member_impl_type_params
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
                const_record.member_trait_args = member_trait_args
                const_record.member_impl_type_params = (
                    member_impl_type_params
                )
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
            "reference_pattern", "mut_pattern", "captured_pattern",
            "remaining_field_pattern", "field_pattern", "tuple_struct_pattern",
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
            member, name_node = self._scoped_member(node)
            if member is None:
                # `m::W` heads resolve a module's type, not a member.
                member = self._scoped_type(node)
            if member is not None and member.binding.kind in {
                "enum_member",
                "struct",
                "associated_const",
            }:
                self.references.append(
                    Reference(
                        self.span(name_node or node),
                        member.binding.id,
                        "read",
                    )
                )
                return
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
                # A glob's names live at this scope — they resolve
                # before the walk moves outward, and an unresolvable
                # module keeps the lookup honest (its contents are
                # unknown, so the name is not trusted).
                found = None
                ambiguous_glob = False
                unresolvable = False
                for path, decl_position, _is_pub in scope.glob_imports:
                    members, resolved = self._glob_members(
                        path, name, decl_position, namespace, set()
                    )
                    if not resolved:
                        unresolvable = True
                        continue
                    for record in members:
                        if found is not None and found is not record:
                            ambiguous_glob = True
                            break
                        found = record
                    if ambiguous_glob:
                        break
                if ambiguous_glob or unresolvable:
                    return None, "glob_import"
                if found is not None:
                    return found, None
        return None, blocked

    def _glob_members(
        self,
        path: str,
        name: str,
        decl_position: int,
        namespace: str,
        seen: set[str],
    ) -> tuple[list["_Record"], bool]:
        """`pub` members `name` gains through `use path::*`, including
        names the module itself re-exports with `pub use` — resolved
        in the use declaration's scope, not the reference site's."""
        module = self._lookup_module_path(path, decl_position)
        if module is None or module.module_scope is None:
            return [], False
        if module.binding.id in seen:
            return [], True
        seen.add(module.binding.id)
        members = [
            record
            for record in reversed(
                module.module_scope.bindings.get(name, ())
            )
            if self._in_namespace(record, namespace) and record.public
        ]
        resolved = True
        for inner_path, inner_position, inner_pub in (
            module.module_scope.glob_imports
        ):
            if not inner_pub:
                continue
            inner, ok = self._glob_members(
                inner_path, name, inner_position, namespace, seen
            )
            resolved = resolved and ok
            members.extend(inner)
        return members, resolved

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
        scrut_id, scrut_args = (
            self._annotation_type(annotation)
            if annotation is not None
            else (
                (None, None)
                if value is None
                else self._receiver_type(value)
            )
        )
        if (
            annotation is not None
            and annotation.type == "tuple_type"
            and scrut_args is not None
            and any(
                arg.strip() == "_"
                for arg in self._type_arg_list(scrut_args)
            )
        ):
            # `let (a, b): (_, _) = t` — an inferred `_` element
            # does not erase the value's declared type; substitute
            # it positionally when the initialiser's args line up.
            value_id, value_args = (
                (None, None)
                if value is None
                else self._receiver_type(value)
            )
            if value_args is not None:
                annotated = self._type_arg_list(scrut_args)
                declared = self._type_arg_list(value_args)
                if len(annotated) == len(declared):
                    scrut_args = ", ".join(
                        dv if av.strip() == "_" else av
                        for av, dv in zip(annotated, declared)
                    )
                    if scrut_id is None:
                        scrut_id = value_id
        scrut_name, scrut_position, scrut_scope = (
            (
                self._alias_head_name(
                    annotation, annotation.start_byte
                ),
                annotation.start_byte,
                None,
            )
            if annotation is not None
            else self._scrutinee_shape(value, scrut_id)
        )
        type_map = (
            {}
            if whole_names
            else self._pattern_type_map(
                pattern, scrut_id, scrut_args, scrut_name,
                scrut_position, scrut_scope,
            )
        )
        for name_node, name_mutable in names:
            whole = name_node.id in whole_names
            pinned = type_map.get(name_node.start_byte)
            record = self._make_record(
                name_node,
                "local",
                ByteSpan(node.end_byte, scope.node.end_byte),
                self.current_function,
                self.module_depth,
                item=False,
                type_fact=(
                    pinned[0]
                    if pinned is not None
                    else fact if whole else _UNKNOWN
                ),
                mutable=name_mutable,
                type_node=annotation if whole else None,
            )
            if pinned is not None:
                record.type_args = pinned[1]
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
    ) -> tuple[list[tuple[Any, bool]], dict]:
        if condition.type == "let_condition":
            pattern = condition.child_by_field_name("pattern")
            value = condition.child_by_field_name("value")
            if value is None:
                named = self._children(condition)
                value = named[-1] if named else None
            if value is not None:
                self._expr(value)
            scrut_id, scrut_args = (
                (None, None)
                if value is None
                else self._receiver_type(value)
            )
            scrut_name, scrut_position, scrut_scope = (
                self._scrutinee_shape(value, scrut_id)
            )
            return (
                self._pattern_names(pattern, scope),
                self._pattern_type_map(
                    pattern, scrut_id, scrut_args,
                    scrut_name, scrut_position, scrut_scope,
                ),
            )
        if any(node.type == "let_condition" for node in self._descendants(condition)):
            self.gaps.append(Gap("unsupported_syntax", self.span(condition)))
            return [], {}
        self._expr(condition)
        return [], {}

    def _if(self, node: Any) -> None:
        condition = node.child_by_field_name("condition")
        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")
        if consequence is not None:
            scope = _Scope(consequence, self.module_depth, self.current_function)
            self.scopes.append(scope)
            names, type_map = (
                ([], {})
                if condition is None
                else self._condition(condition, scope)
            )
            self._bind_pattern_names(
                names, scope, self.span(consequence), type_map=type_map
            )
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
            names, type_map = (
                ([], {})
                if condition is None
                else self._condition(condition, scope)
            )
            self._bind_pattern_names(
                names, scope, self.span(body), type_map=type_map
            )
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
            names = self._pattern_names(pattern, scope)
            single = pattern
            # `for mut p in v` still binds one identifier — `mut` only
            # marks the binding writable. `ref p` binds `&T`, not `T`,
            # so it stays unpinned here.
            while (
                single is not None
                and single.type == "mut_pattern"
            ):
                # `mutable_specifier` is also a named child — pick the
                # nested pattern node.
                single = next(
                    (
                        child
                        for child in self._children(single)
                        if child.type != "mutable_specifier"
                    ),
                    None,
                )
            if (
                single is not None
                and single.type == "identifier"
                and len(names) == 1
            ):
                element_fact, element_args = self._for_element(iterator)
            else:
                # Destructuring binds fields/elements, not the iterated
                # value — `for P { x } in v` leaves `x` unpinned;
                # `for (k, v) in m` still reads the map's pair.
                element_fact, element_args = _UNKNOWN, None
            type_map = self._for_pair_type_map(pattern, iterator)
            if (
                not type_map
                and pattern is not None
                and pattern.type == "tuple_pattern"
                and iterator is not None
            ):
                # `for (a, b) in v` over `Vec<(P, Q)>` binds the
                # element's slots by position — same as the `let`
                # destructure once the element is spelled.
                node = iterator
                while node is not None and node.type in {
                    "reference_expression",
                    "parenthesized_expression",
                }:
                    node = next(
                        iter(
                            [
                                c
                                for c in self._children(node)
                                if c.type != "mutable_specifier"
                            ]
                        ),
                        None,
                    )
                if node is not None and node.type == "call_expression":
                    fact, spelled = self._iterator_method_element(node)
                    if spelled is not None:
                        # The spelled element names were written in
                        # the iterated container's annotation —
                        # resolving at the pattern site would pick
                        # up a same-named shadow.
                        spelled_position = (
                            self._iterator_spelling_with_pos(node)[1]
                        )
                        type_map = self._pattern_type_map(
                            pattern,
                            None if fact is None else fact.type_id,
                            spelled,
                            None,
                            spelled_position,
                        )
                else:
                    container_id, container_args = self._receiver_type(
                        iterator
                    )
                    if container_args is not None:
                        # `for p in it` — `it`'s args may be spelled
                        # names written in `it`'s own annotation
                        # (`let it = v.iter()`), not at the loop.
                        iterator_position = (
                            self._receiver_annotation_position(
                                iterator
                            )
                        )
                        if iterator_position is None:
                            iterator_position = iterator.start_byte
                        elem_id, elem_args = self._element_of(
                            container_id,
                            container_args.strip(),
                            iterator_position,
                        )
                        type_map = self._pattern_type_map(
                            pattern,
                            elem_id,
                            elem_args,
                            None,
                            iterator_position,
                        )
            self._bind_pattern_names(
                names,
                scope,
                self.span(body),
                element_fact,
                element_args,
                type_map,
            )
            self._expr(body)
            self.scopes.pop()

    def _match(self, node: Any) -> None:
        value = node.child_by_field_name("value")
        if value is not None:
            self._expr(value)
        scrut_id, scrut_args = (
            (None, None)
            if value is None
            else self._receiver_type(value)
        )
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
            type_map = self._pattern_type_map(
                pattern, scrut_id, scrut_args,
                *self._scrutinee_shape(value, scrut_id),
            )
            self._bind_pattern_names(
                names, arm_scope, self.span(arm), type_map=type_map
            )
            if guard is not None:
                self._expr(guard)
            result = arm.child_by_field_name("value")
            if result is not None:
                self._expr(result)
            self.scopes.pop()

    def _pattern_head_record(
        self, head: Any | None, scrut_id: str
    ) -> "_Record | None":
        """The record a destructuring pattern's head names — the
        scrutinee's own type (`W { .. }`) or an enum member of it
        (`E::V(..)`); anything else stays unpinned."""
        if head is None:
            return None
        record = None
        if head.type in {"identifier", "type_identifier"}:
            record = self._lookup(
                self._normalize_identifier(self.text(head)),
                head.start_byte,
                "type",
            )
            if record is not None and record.binding.kind == "import":
                resolved = self._through_import(
                    record, head.start_byte, "type"
                )
                if resolved is None or resolved.binding.kind == "import":
                    # `use E::V` names a member — a value-namespace
                    # target, unlike `use m::P`.
                    resolved = self._through_import(
                        record, head.start_byte, "value"
                    )
                record = resolved
            else:
                record = self._through_import(record, head.start_byte)
        elif head.type in {"scoped_identifier", "scoped_type_identifier"}:
            member, _ = self._scoped_member(head)
            record = self._through_import(
                member
                if member is not None
                else self._scoped_type(head),
                head.start_byte,
            )
        if record is None:
            return None
        if (
            record.binding.id == scrut_id
            or record.member_of == scrut_id
        ):
            return record
        return None

    def _member_declared_type(
        self,
        value_node: Any | None,
        member: _Record,
        position: int,
        receiver: "tuple[str | None, str | None] | None" = None,
        annotation: Any | None = None,
    ) -> "tuple[str | None, str | None] | None":
        """(type id, args) of a member's declared annotation with the
        receiver's generic arguments substituted — `W<T>` at `W<P>`
        reads `opt: Option<T>` as `Option<P>`, and `m::W`'s `P` is
        `m::P`, never a root-level `P` of the same spelling."""
        type_id, impl_args = (
            receiver
            if receiver is not None
            else (
                (None, None)
                if value_node is None
                else self._receiver_type(value_node)
            )
        )
        container = (
            None if type_id is None else self.records.get(type_id)
        )
        pos = position
        if value_node is not None and value_node.type == "identifier":
            record = self._lookup(
                self._normalize_identifier(self.text(value_node)),
                value_node.start_byte,
                "value",
            )
            if record is not None and record.type_node is not None:
                pos = record.type_node.start_byte
        param_map = self._pattern_param_map(container, impl_args)
        if member.member_impl_type_params:
            # An `impl<A, B> W<B, A>` member's annotation spells the
            # impl's own parameters — map those positions to the
            # receiver's args, not the struct's.
            param_map = self._impl_param_map(member, impl_args)
        type_id, args = self._field_annotation(
            member.type_node if annotation is None else annotation,
            param_map,
            pos,
            container,
        )
        if type_id is None and args is None:
            return None
        return type_id, args

    def _member_scope_for_args(
        self, value_node: Any | None, member: _Record
    ) -> "_Scope | None":
        """Scope the member's spelled args resolve in — its own
        declaration scope when the receiver adds no generic
        substitution (`m::W`'s `P` stays `m::P`), or the pattern's
        site when substituted args were spelled there."""
        type_id, impl_args = (
            (None, None)
            if value_node is None
            else self._receiver_type(value_node)
        )
        container = (
            None if type_id is None else self.records.get(type_id)
        )
        param_map = (
            {}
            if container is None
            else self._pattern_param_map(container, impl_args)
        )
        if param_map:
            # Substituted args were spelled at the receiver's
            # annotation — but only a member whose own annotation
            # spells a param needs that scope; a fixed member type
            # (`Option<Q>` on `W<A>` at `W<P>`) keeps its declaring
            # scope or a same-named local type would shadow it.
            member_text = (
                ""
                if member.type_node is None
                else self.text(member.type_node)
            )
            if any(
                re.search(rf"\b{re.escape(param)}\b", member_text)
                for param in param_map
            ):
                # A fixed sibling arg (`E` in `Result<T, E>`)
                # still wants the declaring scope — hand it back
                # when it shadows none of the substituted
                # spellings.
                decl = member.home_scope
                if decl is None:
                    owner = self.records.get(member.member_of)
                    decl = None if owner is None else owner.home_scope
                if decl is not None and decl not in self.scopes and not any(
                    (m := re.match(r"[A-Za-z_][\w:]*", s.strip()))
                    is not None
                    and m.group(0).rsplit("::", 1)[-1]
                    in decl.bindings
                    for s in param_map.values()
                ):
                    return decl
                return None
        if member.home_scope is not None:
            return member.home_scope
        owner = self.records.get(member.member_of)
        return None if owner is None else owner.home_scope

    def _impl_param_map(
        self, member: _Record, impl_args: str | None
    ) -> dict[str, str]:
        """{impl param name: spelled use arg} for an `impl` member —
        `impl<A, B> W<B, A>` at `W<P, Q>` maps `B→P` and `A→Q`, so a
        return spelled `A` reads as `Q`."""
        spelled = self._type_arg_list(member.member_impl_args or "")
        used = self._type_arg_list(impl_args or "")
        if not spelled or len(used) < len(spelled):
            return {}
        pairs = {}
        for name, arg in zip(spelled, used):
            # `impl<const N: usize> W<{N}>` spells the arg `{N}` and a
            # raw ident `r#T` keeps its prefix — normalize both before
            # matching the declared param names.
            key = self._normalize_identifier(name.strip())
            if key.startswith("{") and key.endswith("}"):
                key = self._normalize_identifier(key[1:-1].strip())
            if key in member.member_impl_type_params:
                pairs[key] = arg
        return pairs

    def _pattern_param_map(
        self, container: "_Record | None", scrut_args: str | None
    ) -> dict[str, str]:
        """{declared param name: spelled arg} of a generic scrutinee
        — `W<P>` substitutes a `T` field annotation with `P`."""
        if container is None or scrut_args is None:
            return {}
        body = container.body_node
        item = None if body is None else body.parent
        names = self._type_param_names(
            None
            if item is None
            else item.child_by_field_name("type_parameters")
        )
        args = self._type_arg_list(scrut_args)
        if not names or len(args) < len(names):
            return {}
        return dict(zip(names, args))

    def _field_annotation(
        self,
        type_node: Any,
        param_map: dict[str, str],
        position: int,
        container: "_Record | None" = None,
    ) -> tuple[str | None, str | None]:
        """(type id, args) of a declared field, substituting the
        scrutinee's generic arguments — `W<T>` at `W<P>` reads the
        field as `P`. The parameters themselves resolve at the
        container's declaration site, not the pattern's scope stack,
        so the map is consulted before the annotation; the declared
        type itself resolves in the container's own scope — `m::W`'s
        field `P` is `m::P`, never a root-level `P`."""
        if param_map and type_node is not None and type_node.type in {
            "identifier",
            "type_identifier",
        }:
            spelled = param_map.get(
                self._normalize_identifier(self.text(type_node))
            )
            if spelled is not None:
                return self._spelled_type(spelled, position)
        scope = None if container is None else container.home_scope
        push = scope is not None and scope not in self.scopes
        if push:
            self.scopes.append(scope)
        try:
            type_id, args = self._annotation_type(type_node)
        finally:
            if push:
                self.scopes.pop()
        if not param_map:
            return type_id, args
        if type_id is not None:
            param = self.records.get(type_id)
            if (
                param is not None
                and param.binding.kind == "generic_parameter"
            ):
                spelled = param_map.get(param.binding.name)
                if spelled is not None:
                    return self._spelled_type(spelled, position)
        if args is not None and param_map:
            # Substitute in one pass — a positional map like
            # {A: B, B: P} must read `A,B` as `B,P`, not `P,P`.
            args = re.sub(
                r"\b("
                + "|".join(re.escape(n) for n in param_map)
                + r")\b",
                lambda match: param_map[match.group(1)],
                args,
            )
        return type_id, args

    def _spelled_type(
        self, spelled: str, position: int
    ) -> tuple[str | None, str | None]:
        """(type id, args) for a type argument's spelling — `P`
        resolves to its record, `Vec<P>` keeps its args, `&P`/`m::P`
        strip to the named head, an unresolvable shape stays
        args-only."""
        spelled = spelled.strip()
        while True:
            ref = re.match(
                r"^(?:&\s*(?:'\w+\s+)?(?:mut\s+)?|\*\s*(?:const|mut)\s+)(.+)$",
                spelled,
            )
            if ref is not None:
                spelled = ref.group(1).strip()
                continue
            if (
                spelled.startswith("(")
                and spelled.endswith(")")
                and self._paren_wraps(spelled)
            ):
                spelled = spelled[1:-1].strip()
                continue
            break
        bracket = re.fullmatch(r"\[(.+?)(?:\s*;.+)?\]", spelled)
        if bracket is not None:
            # `[P; N]`/`[P]` — an anonymous array/slice carries its
            # element type as the args spelling, same shape a resolved
            # container's element keeps.
            return None, bracket.group(1).strip()
        match = re.fullmatch(
            r"([A-Za-z_][\w:]*)\s*(?:<(.+)>)?", spelled
        )
        if match is None:
            return None, spelled
        name = match.group(1)
        record = (
            self._scoped_spelled_type(name, position)
            if "::" in name
            else self._lookup(
                self._normalize_identifier(name), position, "type"
            )
        )
        record = self._through_import(record, position)
        return (
            None if record is None else record.binding.id,
            match.group(2),
        )

    @staticmethod
    def _paren_wraps(spelled: str) -> bool:
        """Whether `(...)` wraps the whole spelling — `(P, Q), (R, S)`
        only starts and ends with parens; the first one closes early."""
        depth = 0
        for index, char in enumerate(spelled):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index == len(spelled) - 1
        return False

    def _scoped_spelled_type(
        self, name: str, position: int
    ) -> "_Record | None":
        """Type record for a `m::P` spelling — the module path walks
        `_lookup_module_path`, the last segment reads that module's
        scope."""
        segments = name.split("::")
        module = self._lookup_module_path(
            "::".join(segments[:-1]), position
        )
        if module is None or module.module_scope is None:
            return None
        head = self._normalize_identifier(segments[-1])
        record = next(
            (
                candidate
                for candidate in reversed(
                    module.module_scope.bindings.get(head, ())
                )
                if self._in_namespace(candidate, "type")
            ),
            None,
        )
        return record

    def _pattern_head_fields(
        self, head: Any | None, scrut_id: str, scrut_args: str | None
    ) -> "dict[str, tuple[str | None, str | None]] | None":
        """{field name: (type id, args)} for `W { .. }` / `E::V { .. }`
        heads — None when the head does not name the scrutinee's
        declared type."""
        record = self._pattern_head_record(head, scrut_id)
        if record is None:
            return None
        container = (
            record
            if record.binding.id == scrut_id
            else self.records.get(record.member_of)
        )
        body = record.body_node
        if body is None or body.type != "field_declaration_list":
            return None
        param_map = self._pattern_param_map(container, scrut_args)
        fields: dict[str, tuple[str | None, str | None]] = {}
        for decl in self._children(body):
            if decl.type != "field_declaration":
                continue
            name_node = decl.child_by_field_name("name")
            type_node = decl.child_by_field_name("type")
            if name_node is None or type_node is None:
                continue
            fields[
                self._normalize_identifier(self.text(name_node))
            ] = self._field_annotation(
                type_node, param_map, head.start_byte, container
            )
        return fields

    def _pattern_head_payload(
        self,
        head: Any | None,
        scrut_id: str | None,
        scrut_args: str | None,
        scrut_name: str | None = None,
        scrut_position: int | None = None,
    ) -> "list[tuple[str | None, str | None]] | None":
        """Positional [(type id, args)] for `W(..)` / `E::V(..)`
        heads — None when the head does not name the scrutinee."""
        record = self._pattern_head_record(head, scrut_id)
        if record is None:
            scrut_record = (
                None if scrut_id is None else self.records.get(scrut_id)
            )
            if scrut_position is None or (
                scrut_record is not None
                and scrut_record.binding.kind != "type_alias"
            ):
                # A resolved scrutinee (a user `enum Option`) does
                # not reach the prelude path, and prelude payloads
                # need the annotation position to resolve args.
                return None
            return self._prelude_pattern_payload(
                head, scrut_name, scrut_args, scrut_position
            )
        container = (
            record
            if record.binding.id == scrut_id
            else self.records.get(record.member_of)
        )
        body = record.body_node
        if (
            body is None
            or body.type != "ordered_field_declaration_list"
        ):
            return None
        param_map = self._pattern_param_map(container, scrut_args)
        return [
            self._field_annotation(
                child, param_map, head.start_byte, container
            )
            for child in self._children(body)
            if child.type != "visibility_modifier"
        ]

    def _annotation_head_name(self, node: Any | None) -> str | None:
        """Head type name of an annotation — `Option<P>` gives
        "Option"; a scoped `m::Option` returns None (prelude gating
        needs the unqualified name)."""
        while node is not None and node.type in {
            "reference_type",
            "generic_type",
            "generic_type_with_turbofish",
            "return_type",
        }:
            node = node.child_by_field_name("type")
        if node is not None and node.type in {
            "identifier",
            "type_identifier",
        }:
            return self._normalize_identifier(self.text(node))
        return None

    def _alias_head_name(
        self, node: Any | None, position: int | None = None
    ) -> str | None:
        """Head name after following `type` alias chains — `type O =
        Option<P>` still gates the prelude fallback as `Option`; a
        head that is not an alias returns as written."""
        seen: set[str] = set()
        head = self._annotation_head_name(node)
        while head is not None and head not in seen:
            seen.add(head)
            record = self._through_import(
                self._lookup(
                    head,
                    node.start_byte if node is not None else 0,
                    "type",
                ),
                node.start_byte if node is not None else 0,
            )
            if (
                record is None
                or record.binding.kind != "type_alias"
                or record.alias_node is None
            ):
                return head
            node = record.alias_node
            head = self._annotation_head_name(node)
        return head

    def _type_head_name(
        self, type_id: str | None, args: str | None
    ) -> str | None:
        """Head name of a (type id, args) pair — the record's name,
        or the spelled head when the type stayed unresolvable
        (`Vec<P>`'s args carry "Option<P>" for nesting)."""
        if type_id is not None:
            record = self.records.get(type_id)
            if record is not None:
                return record.binding.name
            return None
        if args is None:
            return None
        match = re.match(r"[A-Za-z_]\w*", args.strip())
        return None if match is None else match.group(0)

    def _container_head_name(self, node: Any | None) -> "str | None":
        """Declared container head of a value — `v: Vec<P>` reads
        `Vec`, `m: HashMap<K, V>` reads `HashMap`. None when the
        receiver is not a plainly-annotated identifier."""
        while node is not None and node.type == "reference_expression":
            node = next(iter(node.named_children), None)
        if node is None or node.type != "identifier":
            return None
        record = self._lookup(
            self._normalize_identifier(self.text(node)),
            node.start_byte,
            "value",
        )
        if record is None or record.type_node is None:
            return None
        head = re.match(
            r"[A-Za-z_][\w:]*", self.text(record.type_node).strip()
        )
        if head is None:
            return None
        return head.group(0).split("::")[-1]

    def _scrutinee_shape(
        self, value: Any | None, scrut_id: str | None
    ) -> "tuple[str | None, int | None, _Scope | None]":
        """(head name, annotation position, args scope) of the
        scrutinee's declared type — `opt` in `match opt` reads
        `opt`'s annotation (`Option<P>` → ("Option", <pos>)). The
        scope is where the written args belong, so `m::W`'s `P`
        resolves to `m::P`, never a root `P` of the same spelling."""
        if scrut_id is not None:
            record = self.records.get(scrut_id)
            if record is None:
                return None, None, None
            if (
                record.binding.kind == "type_alias"
                and record.alias_node is not None
            ):
                # `type O = Option<P>` — the alias's body heads the
                # scrutinee, so `Some(p)` on an `O` still reads as a
                # prelude pattern.
                return (
                    self._alias_head_name(record.alias_node),
                    record.alias_node.start_byte,
                    record.home_scope,
                )
            # Spelled args (`Option<&P>` from `v.first()`) were
            # written in the receiver's annotation — resolve them
            # there, not at the pattern site.
            return (
                record.binding.name,
                self._receiver_annotation_position(value),
                None,
            )
        node = value
        while node is not None and node.type == "reference_expression":
            node = next(iter(node.named_children), None)
        if node is None:
            return None, None, None
        if node.type == "field_expression":
            # `match w.opt` / `if let Some(p) = self.opt` — the
            # scrutinee's spelled head is the field's annotation,
            # whose args resolve in the field's declaring scope.
            field = self._field_member(
                node, ("struct_field", "associated_const")
            )
            if field is None or field.type_node is None:
                return None, None, None
            args_scope = self._member_scope_for_args(
                node.child_by_field_name("value"), field
            )
            position = field.type_node.start_byte
            if args_scope is None:
                # Substituted args were spelled at the receiver's
                # annotation — a fn-local `Q` is invisible at the
                # field's declaration site. Only annotations that
                # actually spell a substituted param move the
                # position; a fixed field type (no param mention)
                # still resolves where the field was declared, or a
                # same-named local type would shadow it.
                receiver = node.child_by_field_name("value")
                if receiver is not None and receiver.type == "identifier":
                    record = self._lookup(
                        self._normalize_identifier(
                            self.text(receiver)
                        ),
                        receiver.start_byte,
                        "value",
                    )
                    if (
                        record is not None
                        and record.type_node is not None
                    ):
                        position = record.type_node.start_byte
            return (
                self._alias_head_name(field.type_node, position),
                position,
                args_scope,
            )
        if node.type == "call_expression":
            # `match m.get(k)` — the scrutinee's spelled head is the
            # callee's declared return annotation, whose args
            # resolve in the method's declaring scope. A turbofish
            # (`m.get::<u8>()`) wraps the callee in generic_function.
            callee_node = node.child_by_field_name("function")
            callee = (
                None if callee_node is None else self._callee(callee_node)
            )
            if (
                callee is not None
                and callee.type == "generic_function"
            ):
                callee = callee.child_by_field_name("function")
            if (
                callee is not None
                and callee.type == "field_expression"
                and callee_node is not None
                and callee_node.type == "parenthesized_expression"
            ):
                # `match (w.f)()` calls the field's function pointer —
                # the spelled head is the field's declared `fn`
                # return, resolved in the field's declaring scope.
                field = self._field_member(callee, ("struct_field",))
                if field is None or field.type_node is None:
                    return None, None, None
                ret = field.type_node.child_by_field_name("return_type")
                if ret is None:
                    return None, None, None
                return (
                    self._alias_head_name(ret),
                    ret.start_byte,
                    self._member_scope_for_args(
                        callee.child_by_field_name("value"), field
                    ),
                )
            member = None
            if callee is not None and callee.type == "field_expression":
                member = self._field_member(
                    callee, ("associated_function",)
                )
            elif callee is not None and callee.type in {
                "scoped_identifier",
                "scoped_type_identifier",
            }:
                member, _ = self._scoped_member(callee)
            elif callee is not None and callee.type == "identifier":
                # `match make() { Some(p) => }` — a bare callee's
                # declared return annotation heads the scrutinee.
                member = self._lookup(
                    self._normalize_identifier(self.text(callee)),
                    node.start_byte,
                    "value",
                )
            if member is None:
                field = (
                    callee.child_by_field_name("field")
                    if callee is not None
                    and callee.type == "field_expression"
                    else None
                )
                option_head = (
                    _OPTION_HEAD_METHODS.get(self.text(field).strip())
                    if field is not None
                    else None
                )
                if (
                    option_head is not None
                    and (
                        option_head[1] is None
                        or self._container_head_name(
                            callee.child_by_field_name("value")
                        ) in option_head[1]
                    )
                ):
                    # `v.get(i)`/`v.pop()` return `Option<_>` — the
                    # prelude container has no member record, but
                    # Some/None still heads the scrutinee. A declared
                    # method takes the normal path above. The spelled
                    # payload args were written in the receiver's
                    # annotation — resolve them there, not at the
                    # call site.
                    return (
                        "Option",
                        self._receiver_annotation_position(
                            callee.child_by_field_name("value")
                        ) or node.start_byte,
                        None,
                    )
                return None, None, None
            if member.type_node is None:
                return None, None, None
            return (
                self._alias_head_name(member.type_node),
                member.type_node.start_byte,
                self._member_scope_for_args(
                    callee.child_by_field_name("value"), member
                ),
            )
        if node.type != "identifier":
            return None, None, None
        record = self._lookup(
            self._normalize_identifier(self.text(node)),
            node.start_byte,
            "value",
        )
        if record is None:
            return None, None, None
        position = (
            None
            if record.type_node is None
            else record.type_node.start_byte
        )
        return (
            self._alias_head_name(record.type_node, position),
            position,
            record.home_scope,
        )

    def _prelude_pattern_payload(
        self,
        head: Any | None,
        scrut_name: str | None,
        scrut_args: str | None,
        scrut_position: int,
    ) -> "list[tuple[str | None, str | None]] | None":
        """Positional payload for a prelude constructor
        (`Some(x)`/`Ok(x)`/`Err(e)`) when the scrutinee's declared
        container is the matching prelude type — `Option<P>` lets
        `Some(p)` bind `p` to `P`. A head that resolves to a real
        record or names a different container stays unpinned."""
        if head is None or head.type not in {"identifier", "type_identifier"}:
            return None
        entry = _PRELUDE_CONTAINER_PAYLOAD.get(
            self._normalize_identifier(self.text(head))
        )
        if entry is None or scrut_name != entry[0]:
            return None
        args = self._type_arg_list(scrut_args or "")
        if entry[1] >= len(args):
            return None
        # The spelled arg refers to names visible where the
        # scrutinee's type was annotated — resolving at the pattern
        # position would pick up a same-named shadow.
        type_id, fargs = self._spelled_type(
            args[entry[1]], scrut_position
        )
        return [(type_id, fargs)]

    def _pattern_type_map(
        self,
        pattern: Any | None,
        scrut_id: str | None,
        scrut_args: str | None,
        scrut_name: str | None = None,
        scrut_position: int | None = None,
        scrut_scope: "_Scope | None" = None,
    ) -> dict:
        """start_byte -> (TypeFact, args) for the names a destructuring
        pattern binds, resolved against the scrutinee's declared
        type — `match e { E::V(p) => ... }` types `p` by V's payload;
        a name the shape cannot pin is simply absent."""
        push = scrut_scope is not None and scrut_scope not in self.scopes
        if push:
            self.scopes.append(scrut_scope)
        try:
            return self._pattern_type_map_body(
                pattern, scrut_id, scrut_args,
                scrut_name, scrut_position,
            )
        finally:
            if push:
                self.scopes.pop()

    def _pattern_type_map_body(
        self,
        pattern: Any | None,
        scrut_id: str | None,
        scrut_args: str | None,
        scrut_name: str | None = None,
        scrut_position: int | None = None,
    ) -> dict:
        if pattern is None:
            return {}
        kind = pattern.type
        if scrut_id is None and scrut_name is None and scrut_args is None:
            return {}
        if kind == "tuple_pattern":
            # `let (a, b) = t` on `t: (P, Q)` types each name by the
            # tuple's element at its position — the args key lists
            # the element spellings (`_annotation_type`'s tuple arm).
            spelled_args = (
                "" if scrut_args is None else scrut_args.strip()
            )
            if (
                spelled_args.startswith("(")
                and spelled_args.endswith(")")
                and self._paren_wraps(spelled_args)
            ):
                # A nested tuple spells its elements in parens —
                # `(A, B)` inside the parent's args key unwraps here;
                # `(A, B), (C, D)` is not wrapped — its parens close
                # mid-string.
                spelled_args = spelled_args[1:-1]
            elements = (
                []
                if not spelled_args
                else self._type_arg_list(spelled_args)
            )
            # Positions count anonymous `_` too — `(_, b)` binds
            # `b` to element 1, not 0.
            slots = [
                child
                for child in pattern.children
                if self.text(child).strip() not in {"(", ")", ","}
                and child.type not in {"line_comment", "block_comment"}
            ]
            rest_at = next(
                (
                    index
                    for index, child in enumerate(slots)
                    if child.type == "remaining_field_pattern"
                ),
                None,
            )
            if rest_at is None and len(slots) != len(elements):
                # `let (a, b) = t3` on a 3-tuple does not compile —
                # an arity mismatch stays unpinned, not guessed.
                return {}
            mapping: dict = {}
            for index, child in enumerate(slots):
                if child.type in {"remaining_field_pattern", "_"}:
                    continue
                if not child.is_named or self.text(child).strip() == "_":
                    continue
                if rest_at is not None and index > rest_at:
                    # `(a, .., z)` binds `z` to the LAST element.
                    position = len(elements) - (len(slots) - index)
                else:
                    position = index
                if position < 0 or position >= len(elements):
                    continue
                tid, fargs = self._spelled_type(
                    elements[position],
                    (
                        scrut_position
                        if scrut_position is not None
                        else pattern.start_byte
                    ),
                )
                # The container head is the element's own spelling —
                # `_type_head_name(None, "P")` would read the first
                # arg `P` instead of `Option`, so `(Some(p), _)` on
                # `(Option<P>, P)` still gates the prelude payload.
                spelled_head = re.match(
                    r"[A-Za-z_][\w:]*",
                    elements[position].strip(),
                )
                head_name = (
                    self._type_head_name(tid, fargs)
                    if tid is not None
                    else (
                        self._normalize_identifier(
                            spelled_head.group(0).split("::")[-1]
                        )
                        if spelled_head is not None
                        else None
                    )
                )
                mapping.update(
                    self._pattern_type_map(
                        child, tid, fargs, head_name, scrut_position
                    )
                )
            return mapping
        if kind in {"identifier", "self"}:
            name = self._normalize_identifier(self.text(pattern))
            # An unresolvable scrutinee (`Option<P>` has no record)
            # still carries its args — the fact stays `unknown` so
            # no null type_id is emitted.
            fact = (
                TypeFact("named", name, 0, None, scrut_id)
                if scrut_id is not None
                else _UNKNOWN
            )
            return {pattern.start_byte: (fact, scrut_args)}
        if kind in {"ref_pattern", "reference_pattern", "mut_pattern"}:
            inner = next(
                (
                    child
                    for child in self._children(pattern)
                    if child.type != "mutable_specifier"
                ),
                None,
            )
            return self._pattern_type_map(
                inner, scrut_id, scrut_args, scrut_name, scrut_position
            )
        if kind == "captured_pattern":
            mapping: dict = {}
            for child in self._children(pattern):
                mapping.update(
                    self._pattern_type_map(
                        child, scrut_id, scrut_args,
                        scrut_name, scrut_position,
                    )
                )
            return mapping
        if kind == "or_pattern":
            # Each alternative binds the same names — typing the
            # first one covers the arm.
            inner = next(iter(self._children(pattern)), None)
            return self._pattern_type_map(
                inner, scrut_id, scrut_args, scrut_name, scrut_position
            )
        if kind in {"match_pattern", "condition"}:
            mapping = {}
            for child in self._children(pattern):
                if child.type in {"binary_expression", "call_expression"}:
                    continue
                mapping.update(
                    self._pattern_type_map(
                        child, scrut_id, scrut_args,
                        scrut_name, scrut_position,
                    )
                )
            return mapping
        if kind == "struct_pattern":
            head = pattern.child_by_field_name("type")
            fields = self._pattern_head_fields(
                head, scrut_id, scrut_args
            )
            if fields is None:
                return {}
            mapping = {}
            for child in self._children(pattern):
                if child.type != "field_pattern":
                    continue
                fname_node = child.child_by_field_name("name")
                bound = child.child_by_field_name("pattern")
                fname = (
                    None
                    if fname_node is None
                    else self._normalize_identifier(
                        self.text(fname_node)
                    )
                )
                field_type = fields.get(fname) if fname else None
                if bound is not None:
                    tid, fargs = (
                        field_type
                        if field_type is not None
                        else (None, None)
                    )
                    mapping.update(
                        self._pattern_type_map(
                            bound, tid, fargs,
                            self._type_head_name(tid, fargs),
                            scrut_position,
                        )
                    )
                    continue
                if fname_node is not None and field_type is not None:
                    tid, fargs = field_type
                    if tid is not None or fargs is not None:
                        mapping[fname_node.start_byte] = (
                            TypeFact(
                                "named", fname or "", 0, None, tid or ""
                            ),
                            fargs,
                        )
            return mapping
        if kind == "slice_pattern":
            # `let [a, b, ..] = arr` — each element binds the
            # container's element type (`[P; N]`/`Vec<P>` → P);
            # `..` covers the rest without binding a name.
            elem_position = (
                pattern.start_byte
                if scrut_position is None
                else scrut_position
            )
            elem_id, elem_args = self._element_of(
                scrut_id, scrut_args or "", elem_position
            )
            mapping = {}
            for child in self._children(pattern):
                if child.type == "remaining_field_pattern":
                    continue
                if (
                    child.type == "captured_pattern"
                    and any(
                        grand.type == "remaining_field_pattern"
                        for grand in self._children(child)
                    )
                ):
                    # `h @ ..` binds the rest slice, not an
                    # element — its type is `[P]`, not `P`, so it
                    # stays opaque.
                    continue
                mapping.update(
                    self._pattern_type_map(
                        child, elem_id, elem_args,
                        self._type_head_name(elem_id, elem_args),
                        scrut_position,
                    )
                )
            return mapping
        if kind == "tuple_struct_pattern":
            head = pattern.child_by_field_name("type")
            payload = self._pattern_head_payload(
                head, scrut_id, scrut_args, scrut_name, scrut_position
            )
            if payload is None:
                return {}
            children = [
                child
                for child in self._children(pattern)
                if child != head
            ]
            rest_at = next(
                (
                    index
                    for index, child in enumerate(children)
                    if child.type == "remaining_field_pattern"
                ),
                None,
            )
            mapping = {}
            for index, child in enumerate(children):
                if child.type == "remaining_field_pattern":
                    continue
                if rest_at is not None and index > rest_at:
                    # `V(.., x)` binds `x` to the LAST payload
                    # element — `..` covers the skipped middle.
                    position = len(payload) - (len(children) - index)
                else:
                    position = index
                if position < 0 or position >= len(payload):
                    continue
                tid, fargs = payload[position]
                mapping.update(
                    self._pattern_type_map(
                        child, tid, fargs,
                        self._type_head_name(tid, fargs),
                        scrut_position,
                    )
                )
            return mapping
        return {}

    def _bind_pattern_names(
        self,
        names: list[tuple[Any, bool]],
        scope: _Scope,
        binding_scope: ByteSpan,
        type_fact: TypeFact = _UNKNOWN,
        type_args: str | None = None,
        type_map: dict | None = None,
    ) -> None:
        for name_node, mutable in names:
            fact, args = (type_map or {}).get(
                name_node.start_byte, (type_fact, type_args)
            )
            record = self._make_record(
                name_node, "local", binding_scope, self.current_function,
                self.module_depth, item=False, type_fact=fact, mutable=mutable,
            )
            record.type_args = args
            self._add_to_scope(scope, record)

    def _bind_pattern(
        self,
        pattern: Any,
        scope: _Scope,
        binding_scope: ByteSpan,
        type_fact: TypeFact,
        type_args: str | None = None,
    ) -> None:
        self._bind_pattern_names(
            self._pattern_names(pattern, scope),
            scope,
            binding_scope,
            type_fact,
            type_args,
        )

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
