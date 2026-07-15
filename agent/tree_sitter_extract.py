"""Deterministic syntactic function/block extraction via tree-sitter (Layer B stage 1).

This module replaces the regular-expression function/block extraction used by
the non-Python foreign-code paths (Rust / TypeScript / Go / Solidity) with a
deterministic syntax parser. tree-sitter is a pure in-process parser: it does
not shell out to ``solc`` / ``rustc`` / ``tsc``, does not touch the network, and
returns identical results without any LLM credential, so the deterministic /
no-LLM fixture path (``CI_FIXTURE_MODE``) is preserved.

Only *function/block boundary extraction* moves here. The safety-condition
heuristics (divide-by-zero, overflow, bounds, nil, reentrancy, ...) stay on the
regular-expression path (Layer B stage 2). Mirroring the Python design
(``ast`` for extraction, regex for safety inference), every public helper
returns ``None`` when tree-sitter or a language grammar is unavailable or the
source cannot be parsed, so callers transparently fall back to the legacy regex
extraction and never raise.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

# Languages whose function/block extraction is handled by tree-sitter. Python is
# intentionally excluded: it already uses the standard-library ``ast`` module.
SUPPORTED_LANGUAGES = frozenset({"rust", "go", "typescript", "solidity"})

# Aliases accepted by the callers, normalized to the canonical names above.
_LANGUAGE_ALIASES = {
    "rs": "rust",
    "ts": "typescript",
    "tsx": "typescript",
    "javascript": "typescript",
    "js": "typescript",
    "jsx": "typescript",
    "golang": "go",
    "sol": "solidity",
}


@dataclass(frozen=True)
class ExtractedFunction:
    """A function/block boundary recovered from a syntax tree."""

    name: str
    line: int
    body: str


def _normalize_language(language: str) -> str:
    canonical = language.strip().lower()
    return _LANGUAGE_ALIASES.get(canonical, canonical)


def _load_grammar(language: str):  # pragma: no cover - thin import wrapper
    """Return a tree-sitter ``Language`` for ``language`` or ``None``.

    Any import/attribute error (grammar wheel not installed, incompatible ABI)
    resolves to ``None`` so the caller falls back to the regex path.
    """
    try:
        from tree_sitter import Language

        if language == "rust":
            import tree_sitter_rust as grammar

            capsule = grammar.language()
        elif language == "go":
            import tree_sitter_go as grammar

            capsule = grammar.language()
        elif language == "typescript":
            import tree_sitter_typescript as grammar

            capsule = grammar.language_typescript()
        elif language == "solidity":
            import tree_sitter_solidity as grammar

            capsule = grammar.language()
        else:
            return None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return Language(capsule)
    except Exception:
        return None


@lru_cache(maxsize=None)
def _get_parser(language: str):
    """Return a cached tree-sitter ``Parser`` for ``language`` or ``None``."""
    if language not in SUPPORTED_LANGUAGES:
        return None
    grammar = _load_grammar(language)
    if grammar is None:
        return None
    try:
        from tree_sitter import Parser

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return Parser(grammar)
    except Exception:
        return None


def is_available(language: str) -> bool:
    """True when tree-sitter can parse ``language``."""
    return _get_parser(_normalize_language(language)) is not None


# Node types that introduce a named function/method, per grammar.
_FUNCTION_NODE_TYPES = {
    "rust": {"function_item"},
    "go": {"function_declaration", "method_declaration"},
    "typescript": {"function_declaration", "method_definition"},
    "solidity": {"function_definition"},
}
# Expression-valued function forms bound to a variable (TypeScript arrows).
_VALUE_FUNCTION_NODE_TYPES = {"arrow_function", "function_expression"}


def _decode(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _inner_body(source_bytes: bytes, body_node) -> str:
    """Return the text inside the outermost braces of ``body_node``.

    Matches the legacy ``_balanced_brace_body`` semantics (content between the
    first ``{`` and the last ``}``). Expression bodies (a braceless arrow body)
    are returned verbatim.
    """
    if body_node is None:
        return ""
    text = _decode(source_bytes, body_node)
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped[1:-1]
    return text


def _iter_function_nodes(root, language: str):
    """Yield ``(name_node, body_node)`` for every function/method in the tree."""
    function_types = _FUNCTION_NODE_TYPES[language]
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in function_types:
            name_node = node.child_by_field_name("name")
            body_node = node.child_by_field_name("body")
            if name_node is not None:
                yield name_node, body_node
        elif language == "typescript" and node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            name_node = node.child_by_field_name("name")
            if (
                value is not None
                and value.type in _VALUE_FUNCTION_NODE_TYPES
                and name_node is not None
            ):
                yield name_node, value.child_by_field_name("body")
        stack.extend(reversed(node.children))


def _parse(source: str, language: str):
    parser = _get_parser(language)
    if parser is None:
        return None, None
    source_bytes = source.encode("utf-8")
    try:
        tree = parser.parse(source_bytes)
    except Exception:
        return None, None
    return tree, source_bytes


def _extract(
    source: str, language: str, safe_identifier: Callable[[str], str]
) -> list[ExtractedFunction] | None:
    canonical = _normalize_language(language)
    if canonical not in SUPPORTED_LANGUAGES:
        return None
    tree, source_bytes = _parse(source, canonical)
    if tree is None:
        return None
    results: list[ExtractedFunction] = []
    for name_node, body_node in _iter_function_nodes(tree.root_node, canonical):
        raw_name = _decode(source_bytes, name_node)
        results.append(
            ExtractedFunction(
                name=safe_identifier(raw_name),
                line=name_node.start_point[0] + 1,
                body=_inner_body(source_bytes, body_node),
            )
        )
    return results


def function_blocks(
    source: str, language: str, safe_identifier: Callable[[str], str]
) -> list[tuple[str, str]] | None:
    """Return ``[(name, body)]`` for each function, or ``None`` to fall back."""
    extracted = _extract(source, language, safe_identifier)
    if extracted is None:
        return None
    return [(fn.name, fn.body) for fn in extracted]


def function_line_map(
    source: str, language: str, safe_identifier: Callable[[str], str]
) -> dict[str, int] | None:
    """Return ``{name: 1-based line}`` for each function, or ``None`` to fall back."""
    extracted = _extract(source, language, safe_identifier)
    if extracted is None:
        return None
    line_map: dict[str, int] = {}
    for fn in extracted:
        # Keep the first declaration's line, mirroring the regex line map which
        # only records a name once.
        line_map.setdefault(fn.name, fn.line)
    return line_map


def function_names(
    source: str, language: str, safe_identifier: Callable[[str], str]
) -> set[str] | None:
    """Return the set of declared function names, or ``None`` to fall back."""
    extracted = _extract(source, language, safe_identifier)
    if extracted is None:
        return None
    return {fn.name for fn in extracted}


# --------------------------------------------------------------------------- #
# Expression-level safety analysis (Layer B stage 2)
#
# Divide-by-zero, out-of-bounds, null/nil dereference and integer-overflow
# inference used to scan the raw expression text with regular expressions,
# which false-matches operators inside string/comment nodes, mis-reads member
# access (``obj.a / obj.b``) and cannot see nesting (``a[b[c]]``). Here the same
# structural facts are recovered from the syntax tree instead, so literals and
# comments are ignored for free and member/index nesting is exact. The semantic
# policies that decide what to *do* with the facts (``known_constants`` pinning,
# value-type nil/null exclusion, method-receiver exclusion) stay in the callers;
# this module only reports the structure. Every entry point returns ``None``
# when tree-sitter or the grammar is unavailable, so callers fall back to the
# legacy regex heuristics and never raise.
# --------------------------------------------------------------------------- #

_LENGTH_PROPERTIES = frozenset({"length", "len", "is_empty"})

# A single expression is wrapped in the smallest valid construct the grammar
# accepts so it parses cleanly; the wrapper identifiers never introduce a
# division, index, member, deref or ``+`` node, so they cannot be mistaken for
# a finding.
_EXPRESSION_WRAPPERS: dict[str, Callable[[str], str]] = {
    "rust": lambda expr: f"fn __ts_e() {{ let __ts_x = ({expr}); }}",
    "go": lambda expr: f"package __ts_p\nfunc __ts_e() {{ _ = ({expr}) }}",
    "typescript": lambda expr: f"const __ts_x = ({expr});",
    "solidity": (
        lambda expr: f"contract __ts_c {{ function __ts_e() public {{ __ts_y = {expr}; }} }}"
    ),
}

# Grammar node types for each structural form, keyed by canonical language.
_BINARY_NODE_TYPE = "binary_expression"  # shared by all four grammars
_INDEX_NODE_TYPES = {
    "rust": "index_expression",
    "go": "index_expression",
    "typescript": "subscript_expression",
    "solidity": "array_access",
}
_MEMBER_NODE_TYPES = {
    "rust": "field_expression",
    "go": "selector_expression",
    "typescript": "member_expression",
    "solidity": "member_expression",
}
# Field names for the object/base and index/property of the nodes above.
_MEMBER_OBJECT_FIELD = {
    "rust": "value",
    "go": "operand",
    "typescript": "object",
    "solidity": "object",
}
_MEMBER_PROPERTY_FIELD = {
    "rust": "field",
    "go": "field",
    "typescript": "property",
    "solidity": "property",
}
_INDEX_BASE_FIELD = {"go": "operand", "solidity": "base", "typescript": "object"}
_INDEX_INDEX_FIELD = {"go": "index", "solidity": "index", "typescript": "index"}


@dataclass(frozen=True)
class ExpressionSafety:
    """Structural safety-relevant facts recovered from an expression's syntax tree.

    Names are reported in source order so callers reproduce the deterministic
    ordering of the legacy ``re.finditer`` scans.
    """

    divisors: tuple[str, ...]
    index_accesses: tuple[tuple[str, str], ...]
    length_access_values: tuple[str, ...]
    member_access_values: tuple[str, ...]
    pointer_deref_values: tuple[str, ...]
    additions: tuple[tuple[str, str], ...]


def _unwrap(node):
    """Descend through Solidity's ``expression`` supertype wrapper nodes."""
    while node is not None and node.type == "expression" and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def _identifier_name(source_bytes: bytes, node) -> str | None:
    """Return the identifier text of ``node`` (unwrapping a TS ``x!``), else ``None``."""
    node = _unwrap(node)
    if node is None:
        return None
    if node.type == "identifier":
        return _decode(source_bytes, node)
    if node.type == "non_null_expression":  # TypeScript ``name!``
        for child in node.named_children:
            if child.type == "identifier":
                return _decode(source_bytes, child)
    return None


def _binary_operator(node) -> str | None:
    operator = node.child_by_field_name("operator")
    return operator.type if operator is not None else None


def _operand_is_receiver(source_bytes: bytes, node) -> bool:
    """True when ``node`` is a member-access/call receiver in the source text.

    Mirrors the legacy ``_operand_is_member_or_call`` character check so the
    #281 filter (``result + SafeCast.toUint(...)`` must not model ``SafeCast``
    as a free integer) is preserved even when a grammar re-associates the
    receiver into the addition (as tree-sitter-solidity does).
    """
    after = source_bytes[node.end_byte :].lstrip()
    if after[:1] in (b".", b"("):
        return True
    before = source_bytes[: node.start_byte].rstrip()
    return before[-1:] == b"."


def _index_operands(node, language: str):
    """Return the ``(base, index)`` child nodes of an index/subscript node."""
    base_field = _INDEX_BASE_FIELD.get(language)
    if base_field is not None:
        return (
            node.child_by_field_name(base_field),
            node.child_by_field_name(_INDEX_INDEX_FIELD[language]),
        )
    # Rust ``index_expression`` exposes no field names.
    named = node.named_children
    if len(named) >= 2:
        return named[0], named[1]
    return None, None


def analyze_expression(expression: str, language: str) -> ExpressionSafety | None:
    """Recover structural safety facts from ``expression`` or ``None`` to fall back."""
    if not expression or not expression.strip():
        return None
    canonical = _normalize_language(language)
    if canonical not in SUPPORTED_LANGUAGES:
        return None
    parser = _get_parser(canonical)
    if parser is None:
        return None
    wrapper = _EXPRESSION_WRAPPERS.get(canonical)
    if wrapper is None:
        return None
    source = wrapper(expression)
    source_bytes = source.encode("utf-8")
    try:
        tree = parser.parse(source_bytes)
    except Exception:
        return None
    if tree.root_node.has_error:
        # A partial/ambiguous parse is unreliable; defer to the regex fallback.
        return None

    index_type = _INDEX_NODE_TYPES[canonical]
    member_type = _MEMBER_NODE_TYPES[canonical]
    object_field = _MEMBER_OBJECT_FIELD[canonical]
    property_field = _MEMBER_PROPERTY_FIELD[canonical]

    divisors: list[str] = []
    index_accesses: list[tuple[str, str]] = []
    length_access_values: list[str] = []
    member_access_values: list[str] = []
    pointer_deref_values: list[str] = []
    additions: list[tuple[str, str]] = []

    def visit(node) -> None:
        if node.type == _BINARY_NODE_TYPE:
            operator = _binary_operator(node)
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if operator in {"/", "%"}:
                divisor = _identifier_name(source_bytes, right)
                if divisor is not None:
                    divisors.append(divisor)
            elif operator == "+":
                left_name = _identifier_name(source_bytes, left)
                right_name = _identifier_name(source_bytes, right)
                if (
                    left_name is not None
                    and right_name is not None
                    and not _operand_is_receiver(source_bytes, left)
                    and not _operand_is_receiver(source_bytes, right)
                ):
                    additions.append((left_name, right_name))
        elif node.type == index_type:
            base, index = _index_operands(node, canonical)
            base_name = _identifier_name(source_bytes, base)
            index_name = _identifier_name(source_bytes, index)
            if base_name is not None and index_name is not None:
                index_accesses.append((base_name, index_name))
        elif node.type == member_type:
            obj = node.child_by_field_name(object_field)
            prop = node.child_by_field_name(property_field)
            obj_name = _identifier_name(source_bytes, obj)
            if obj_name is not None:
                member_access_values.append(obj_name)
                if prop is not None and _decode(source_bytes, prop) in _LENGTH_PROPERTIES:
                    length_access_values.append(obj_name)
        elif canonical == "go" and node.type == "unary_expression":
            if _binary_operator(node) == "*":
                operand = _identifier_name(
                    source_bytes, node.child_by_field_name("operand")
                )
                if operand is not None:
                    pointer_deref_values.append(operand)
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return ExpressionSafety(
        divisors=tuple(divisors),
        index_accesses=tuple(index_accesses),
        length_access_values=tuple(length_access_values),
        member_access_values=tuple(member_access_values),
        pointer_deref_values=tuple(pointer_deref_values),
        additions=tuple(additions),
    )
