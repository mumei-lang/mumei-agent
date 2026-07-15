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
