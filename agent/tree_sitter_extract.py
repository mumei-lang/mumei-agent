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

import re
import warnings
from dataclasses import dataclass, replace
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
    # The identifier exactly as it appears in source. Callers use this for
    # language-specific filtering (e.g. Go blank identifier ``_``) before the
    # ``safe_identifier`` normalization stored in ``name``.
    raw_name: str = ""
    # Signature metadata used by contract inference. Empty/default values keep
    # the original function-blocks API unchanged; callers that need signatures
    # can read these fields.
    params_text: str = ""
    return_type: str | None = None
    attributes: tuple[str, ...] = ()
    # Solidity visibility/state-mutability/modifier/return-type text used by
    # reentrancy and access-control heuristics.
    attrs_text: str = ""
    # Byte and character offsets of the declaration and body. tree-sitter works
    # on UTF-8 bytes, but callers operate on Python ``str`` values (characters).
    # Both units are exposed so callers can slice strings with character offsets
    # while still comparing against tree-sitter byte positions when needed.
    start_byte: int = 0
    end_byte: int = 0
    body_start_byte: int = 0
    body_end_byte: int = 0
    start_char: int = 0
    end_char: int = 0
    body_start_char: int = 0
    body_end_char: int = 0
    has_body: bool = True
    is_expression_body: bool = False
    is_top_level: bool = True


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


def _syntax_nodes(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _spec_or_compact_error_wrapper(node, spec_type: str) -> list:
    if node.type == spec_type:
        return [node]
    if node.type == "ERROR" and len(node.children) == 1:
        inner = node.children[0]
        if inner.type == spec_type:
            return [inner]
    return []


def _compact_group_specs(node, spec_type: str) -> list:
    """Specs in a compact group, including tree-sitter's final-spec error wrapper."""
    specs = []
    for child in node.children:
        specs.extend(_spec_or_compact_error_wrapper(child, spec_type))
    return specs


def go_declaration_spec_nodes(node) -> list:
    """Flatten a Go const/var declaration's specs, including compact groups.

    Grouped vars nest under ``var_spec_list``; a compact final spec may
    additionally sit inside tree-sitter's zero-width ``ERROR`` wrapper.
    The wrapper is only syntactically valid after
    :func:`parse_go_with_compact_group_recovery` has accepted the tree.
    """
    if node.type == "const_declaration":
        return _compact_group_specs(node, "const_spec")
    if node.type != "var_declaration":
        return []
    specs = []
    for child in node.named_children:
        if child.type == "var_spec_list":
            for grand in child.named_children:
                specs.extend(_spec_or_compact_error_wrapper(grand, "var_spec"))
        else:
            specs.extend(_spec_or_compact_error_wrapper(child, "var_spec"))
    return specs


def _compact_group_parts(node):
    if node.type == "const_declaration":
        if not any(child.type == "(" for child in node.children):
            return None
        return _compact_group_specs(node, "const_spec")
    if node.type == "var_spec_list":
        return _compact_group_specs(node, "var_spec")
    return None


def _compact_group_close(node):
    return next(
        (child for child in reversed(node.children) if child.type == ")"),
        None,
    )


def _comment_spans(root) -> tuple[tuple[int, int], ...]:
    return tuple(
        (node.start_byte, node.end_byte)
        for node in _syntax_nodes(root)
        if node.type == "comment"
    )


def _semicolon_outside_comments(
    source_bytes: bytes,
    start_byte: int,
    end_byte: int,
    comments: tuple[tuple[int, int], ...],
) -> bool:
    """Whether a semicolon byte occurs outside tree-sitter comment nodes."""
    relevant = [
        (start, end)
        for start, end in comments
        if start < end_byte and start_byte < end
    ]
    for position in range(start_byte, end_byte):
        if source_bytes[position] != ord(";"):
            continue
        if any(start <= position < end for start, end in relevant):
            continue
        return True
    return False


def _compact_group_semicolon_insertions(
    root, source_bytes: bytes, comments: tuple[tuple[int, int], ...] | None = None
) -> list[int]:
    """Positions where tree-sitter misses Go's grouped-declaration terminator.

    The Go scanner terminates a final grouped spec before ``)`` even in
    the compact one-line form. tree-sitter-go usually parses that spec
    list into the right shape but marks a missing terminator; with one
    spec it wraps the final spec in a zero-width ``ERROR`` node instead.
    Detect only those shapes — a final spec directly before the group
    close with no newline or explicit semicolon between them — so
    ordinary parse errors still fail closed.
    """
    if comments is None:
        comments = _comment_spans(root)
    positions = []
    for node in _syntax_nodes(root):
        specs = _compact_group_parts(node)
        if specs is None:
            continue
        close = _compact_group_close(node)
        if not specs or close is None:
            continue
        last = specs[-1]
        between = source_bytes[last.end_byte : close.start_byte]
        if (
            _semicolon_outside_comments(
                source_bytes, last.end_byte, close.start_byte, comments
            )
            or b"\n" in between
            or b"\r" in between
        ):
            continue
        positions.append(close.start_byte)
    return positions


def _only_compact_group_error_wrappers(
    root, source_bytes: bytes, comments: tuple[tuple[int, int], ...] | None = None
) -> bool:
    """Whether every ``ERROR`` node is a recognised compact-group wrapper."""
    if comments is None:
        comments = _comment_spans(root)
    for node in _syntax_nodes(root):
        if not (node.is_error or node.type == "ERROR"):
            continue
        parent = node.parent
        if parent is None or len(node.children) != 1:
            return False
        spec_type = {
            "const_declaration": "const_spec",
            "var_spec_list": "var_spec",
        }.get(parent.type)
        inner = node.children[0]
        if (
            spec_type is None
            or inner.type != spec_type
            or node.start_byte != inner.start_byte
            or node.end_byte != inner.end_byte
        ):
            return False
        close = _compact_group_close(parent)
        if close is None or node.end_byte > close.start_byte:
            return False
        between = source_bytes[node.end_byte : close.start_byte]
        if (
            _semicolon_outside_comments(
                source_bytes, node.end_byte, close.start_byte, comments
            )
            or b"\n" in between
            or b"\r" in between
        ):
            return False
    return True


def _text_with_semicolon_insertions(
    text: bytes, start_byte: int, end_byte: int, positions: list[int]
) -> bytes:
    """Apply recovery semicolons that fall inside one original node span."""
    out = bytearray()
    cursor = 0
    for position in sorted(set(positions)):
        if not start_byte < position < end_byte:
            continue
        relative = position - start_byte
        out += text[cursor:relative]
        out += b";"
        cursor = relative
    out += text[cursor:]
    return bytes(out)


def _apply_semicolon_insertions(source_bytes: bytes, positions: list[int]) -> bytes:
    patched = bytearray()
    cursor = 0
    for position in sorted(set(positions)):
        patched += source_bytes[cursor:position]
        patched += b";"
        cursor = position
    patched += source_bytes[cursor:]
    return bytes(patched)


def parse_go_with_compact_group_recovery(parser, source_bytes: bytes):
    """Parse Go source, admitting only the compact-group terminator false positive.

    Returns the original tree when every parse error is explained by
    tree-sitter-go missing the implicit terminator before a grouped
    declaration's closing parenthesis. The returned tree keeps the
    original byte offsets; the semicolon-patched parse is used only as a
    fail-closed witness that no other syntax error is present. Recognised
    zero-width final-spec ``ERROR`` wrappers are admitted; any unrelated
    ``ERROR`` node, dropped spec or remaining parse error returns
    ``None``.
    """
    try:
        root = parser.parse(source_bytes).root_node
    except Exception:
        return None
    if not root.has_error:
        return root
    comments = _comment_spans(root)
    insertions = _compact_group_semicolon_insertions(root, source_bytes, comments)
    if not insertions or not _only_compact_group_error_wrappers(
        root, source_bytes, comments
    ):
        return None
    patched_source = _apply_semicolon_insertions(source_bytes, insertions)
    try:
        patched = parser.parse(patched_source).root_node
    except Exception:
        return None
    if patched.has_error:
        return None
    original_specs = [
        (
            node.type,
            _text_with_semicolon_insertions(
                source_bytes[node.start_byte : node.end_byte],
                node.start_byte,
                node.end_byte,
                insertions,
            ),
        )
        for node in _syntax_nodes(root)
        if node.type in {"const_spec", "var_spec"}
    ]
    patched_specs = [
        (node.type, node.text)
        for node in _syntax_nodes(patched)
        if node.type in {"const_spec", "var_spec"}
    ]
    return root if original_specs == patched_specs else None


# Node types that introduce a named function/method, per grammar.
_FUNCTION_NODE_TYPES = {
    # Rust traits use ``function_signature_item`` for methods without a body.
    "rust": {"function_item", "function_signature_item"},
    "go": {"function_declaration", "method_declaration"},
    "typescript": {"function_declaration", "method_definition"},
    "solidity": {"function_definition"},
}
# Expression-valued function forms bound to a variable (TypeScript arrows).
_VALUE_FUNCTION_NODE_TYPES = {"arrow_function", "function_expression"}
# Body node types that wrap a brace-enclosed statement block.
_BLOCK_NODE_TYPES = {"block", "statement_block", "function_body"}


def _react_wrapped_function(value_node, source_bytes: bytes):
    """Return the inner arrow/function expression wrapped by ``memo(...)`` or ``forwardRef(...)``.

    React components are often exported as ``const X = memo((props) => ...)``.
    If the variable value is a call to ``memo`` or ``forwardRef`` and the first
    argument is an arrow or function expression, treat that argument as the
    actual function body.
    """
    if value_node is None or value_node.type != "call_expression":
        return None
    callee = value_node.child_by_field_name("function")
    if callee is None:
        return None
    name = _decode(source_bytes, callee)
    if name not in {"memo", "forwardRef"}:
        return None
    arguments_node = value_node.child_by_field_name("arguments")
    if arguments_node is None:
        return None
    for arg in arguments_node.named_children:
        if arg.type in _VALUE_FUNCTION_NODE_TYPES:
            return arg
    return None


def _decode(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _inner_body_offsets(source_bytes: bytes, body_node) -> tuple[str, int, int]:
    """Return the text and byte offsets inside the outermost braces of ``body_node``.

    Matches the legacy ``_balanced_brace_body`` semantics (content between the
    first ``{`` and the last ``}``). Expression bodies (a braceless arrow body)
    are returned verbatim.
    """
    if body_node is None:
        # ``len(source_bytes)`` is a safe sentinel that always sits at EOF.
        return "", len(source_bytes), len(source_bytes)
    start = body_node.start_byte
    end = body_node.end_byte
    text = _decode(source_bytes, body_node)
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped[1:-1], start + 1, end - 1
    return text, start, end


def _is_top_level_function(node, language: str) -> bool:
    """Return True when ``node`` is not nested inside another function."""
    function_types = _FUNCTION_NODE_TYPES[language] | _VALUE_FUNCTION_NODE_TYPES | {
        "function_expression"
    }
    n = node.parent
    while n is not None:
        if n.type in function_types:
            return False
        n = n.parent
    return True


def _outer_declaration_node(node, language: str, source_bytes: bytes | None = None):
    """Return the outer-most statement node that owns a function declaration.

    For TypeScript this surfaces ``export_statement`` / ``lexical_declaration``
    so callers can extract preceding JSDoc from the correct declaration start.
    """
    if language != "typescript":
        return node
    if node.type == "function_declaration" and node.parent is not None:
        if node.parent.type == "export_statement":
            return node.parent
        return node
    if node.type == "variable_declarator" and node.parent is not None:
        value = node.child_by_field_name("value")
        func_value = (
            value
            if value is not None and value.type in _VALUE_FUNCTION_NODE_TYPES
            else _react_wrapped_function(value, source_bytes) if source_bytes is not None else None
        )
        if func_value is not None:
            lexical = node.parent
            if (
                lexical is not None
                and lexical.parent is not None
                and lexical.parent.type == "export_statement"
            ):
                return lexical.parent
            return lexical
    return node


def _char_offsets(source_bytes: bytes) -> list[int]:
    """Return a list mapping each byte index to its character index."""
    offsets = [0] * (len(source_bytes) + 1)
    char_count = 0
    for i, byte in enumerate(source_bytes):
        offsets[i] = char_count
        # UTF-8 continuation bytes are 0x80-0xBF; they do not start a character.
        if byte < 0x80 or byte >= 0xC0:
            char_count += 1
    offsets[len(source_bytes)] = char_count
    return offsets


def _iter_function_nodes(root, language: str, source_bytes: bytes | None = None):
    """Yield ``(name_node, body_node, function_node)`` for every function/method in the tree."""
    function_types = _FUNCTION_NODE_TYPES[language]
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in function_types:
            name_node = node.child_by_field_name("name")
            body_node = node.child_by_field_name("body")
            if name_node is not None:
                yield name_node, body_node, node
        elif language == "typescript" and node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            name_node = node.child_by_field_name("name")
            if value is not None and name_node is not None:
                func_value = (
                    value
                    if value.type in _VALUE_FUNCTION_NODE_TYPES
                    else _react_wrapped_function(value, source_bytes) if source_bytes is not None else None
                )
                if func_value is not None:
                    yield name_node, func_value.child_by_field_name("body"), node
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
    if language == "typescript" and tree.root_node.has_error:
        try:
            from tree_sitter import Language, Parser
            import tree_sitter_typescript as ts_grammar

            tsx_lang = Language(ts_grammar.language_tsx())
            tsx_parser = Parser(tsx_lang)
            tsx_tree = tsx_parser.parse(source_bytes)
            if not tsx_tree.root_node.has_error:
                return tsx_tree, source_bytes
        except Exception:
            pass
    return tree, source_bytes


def parse(source: str, language: str):
    """Return ``(tree, source_bytes)`` for ``language`` or ``(None, None)``.

    Raw-tree access for callers that need node-level scope analysis — guard
    domination, expression context, enclosing-function attribution — which the
    function/block boundary helpers above cannot express. Same fallback
    contract as the rest of the module: ``(None, None)`` when the grammar is
    unavailable or the parse fails, so callers keep their regex paths.
    """
    canonical = _normalize_language(language)
    if canonical not in SUPPORTED_LANGUAGES:
        return None, None
    return _parse(source, canonical)


def _extract(
    source: str, language: str, safe_identifier: Callable[[str], str]
) -> list[ExtractedFunction] | None:
    canonical = _normalize_language(language)
    if canonical not in SUPPORTED_LANGUAGES:
        return None
    tree, source_bytes = _parse(source, canonical)
    if tree is None:
        return None
    char_offsets = _char_offsets(source_bytes)
    results: list[ExtractedFunction] = []
    for name_node, body_node, fn_node in _iter_function_nodes(
        tree.root_node, canonical, source_bytes
    ):
        raw_name = _decode(source_bytes, name_node)
        declaration_node = _outer_declaration_node(fn_node, canonical, source_bytes)
        body, body_start_byte, body_end_byte = _inner_body_offsets(
            source_bytes, body_node
        )
        is_expression_body = (
            body_node is not None and body_node.type not in _BLOCK_NODE_TYPES
        )
        is_top_level = _is_top_level_function(fn_node, canonical)
        results.append(
            ExtractedFunction(
                name=safe_identifier(raw_name),
                line=name_node.start_point[0] + 1,
                body=body,
                raw_name=raw_name,
                start_byte=declaration_node.start_byte,
                end_byte=declaration_node.end_byte,
                body_start_byte=body_start_byte,
                body_end_byte=body_end_byte,
                start_char=char_offsets[declaration_node.start_byte],
                end_char=char_offsets[declaration_node.end_byte],
                body_start_char=char_offsets[body_start_byte],
                body_end_char=char_offsets[body_end_byte],
                has_body=body_node is not None,
                is_expression_body=is_expression_body,
                is_top_level=is_top_level,
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
# Full function extraction with signatures (Layer B stage 1, contract inference)
#
# Where the grammar supports it, recover the parameter list and return type
# directly from the syntax tree instead of re-scanning with regular expressions.
# The raw text is still returned so callers can apply their existing signature
# parsers (e.g. ``_params_from_signature`` / ``_mumei_return_type``).
# --------------------------------------------------------------------------- #


def _rust_attribute_identifiers(source_bytes: bytes, fn_node) -> tuple[str, ...]:
    """Return the identifiers of outer ``#[...]`` attributes preceding ``fn_node``.

    Recursively collects identifiers inside attribute paths (``tokio::test``)
    and token trees (``#[tokio::test(flavor = "multi_thread")]``).
    """
    attributes: list[str] = []

    def _collect_identifiers(node):
        for child in node.children:
            if child.type == "token_tree":
                # Argument token trees (e.g. ``(flavor = "multi_thread")`` or
                # ``cfg(test)``) are not part of the attribute path, so descending
                # into them would misclassify ``#[cfg(test)]`` as a test attribute.
                continue
            if child.type == "identifier":
                attributes.append(_decode(source_bytes, child))
            else:
                _collect_identifiers(child)

    prev = fn_node.prev_sibling
    while prev is not None and prev.type == "attribute_item":
        _collect_identifiers(prev)
        prev = prev.prev_sibling
    return tuple(reversed(attributes))


def _rust_signature(source_bytes: bytes, fn_node) -> tuple[str, str | None]:
    """Return ``(params_text, return_type)`` for a Rust function/signature item."""
    params_node = None
    body_node = None
    where_node = None
    arrow_end = None
    semicolon_node = None
    for child in fn_node.children:
        if child.type == "parameters":
            params_node = child
        elif child.type == "block":
            body_node = child
        elif child.type == "where_clause":
            where_node = child
        elif child.type == "->":
            arrow_end = child.end_byte
        elif child.type == ";":
            semicolon_node = child
    params_text = ""
    if params_node is not None:
        text = _decode(source_bytes, params_node).strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1]
        params_text = text
    return_type: str | None = None
    if arrow_end is not None:
        if body_node is not None:
            end_byte = body_node.start_byte
        elif semicolon_node is not None:
            end_byte = semicolon_node.start_byte
        else:
            end_byte = fn_node.end_byte
        if where_node is not None and where_node.start_byte < end_byte:
            end_byte = where_node.start_byte
        raw = source_bytes[arrow_end:end_byte].decode("utf-8", "replace").strip(" ;")
        return_type = raw or None
    return params_text, return_type


def _go_signature(source_bytes: bytes, fn_node, name_node) -> tuple[str, str | None]:
    """Return ``(params_text, return_type)`` for a Go function/method declaration."""
    param_lists: list = []
    body_node = None
    for child in fn_node.children:
        if child.type == "parameter_list":
            param_lists.append(child)
        elif child.type == "block":
            body_node = child
            break
    name_end = name_node.end_byte
    # Receiver, if present, is the parameter list that ends before the name.
    receiver_node = None
    params_node = None
    for pl in param_lists:
        if pl.end_byte <= name_end:
            receiver_node = pl
        elif pl.start_byte >= name_end and params_node is None:
            params_node = pl
    if params_node is None:
        params_node = param_lists[-1] if param_lists else None

    def strip_parens(node) -> str:
        if node is None:
            return ""
        text = _decode(source_bytes, node).strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1]
        return text

    receiver_text = strip_parens(receiver_node)
    params_text = strip_parens(params_node)
    if receiver_text:
        params_text = f"{receiver_text}, {params_text}" if params_text else receiver_text

    return_type: str | None = None
    if params_node is not None:
        start = params_node.end_byte
        end = body_node.start_byte if body_node is not None else fn_node.end_byte
        raw = source_bytes[start:end].decode("utf-8", "replace").strip(" ;")
        if raw:
            return_type = raw
    return params_text, return_type


def _typescript_signature(
    source_bytes: bytes, fn_node, name_node
) -> tuple[str, str | None]:
    """Return ``(params_text, return_type)`` for a TypeScript function/arrow/method."""
    value_node = fn_node
    if fn_node.type == "variable_declarator":
        value_node = fn_node.child_by_field_name("value")
        if value_node is not None and value_node.type == "call_expression":
            wrapped = _react_wrapped_function(value_node, source_bytes)
            if wrapped is not None:
                value_node = wrapped
    if value_node is None or value_node.type not in {
        "function_declaration",
        "method_definition",
        "function_expression",
        "arrow_function",
    }:
        return "", None
    params_node = value_node.child_by_field_name(
        "parameters"
    ) or value_node.child_by_field_name("parameter")
    params_text = ""
    if params_node is not None:
        text = _decode(source_bytes, params_node).strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1]
        params_text = text
    return_type: str | None = None
    return_type_node = value_node.child_by_field_name("return_type")
    if return_type_node is not None:
        raw = _decode(source_bytes, return_type_node).strip()
        if raw.startswith(":"):
            raw = raw[1:].strip()
        return_type = raw or None
    if return_type is None and fn_node.type == "variable_declarator":
        # Variables annotated with a function type (e.g. ``const f: (x) => number``)
        # carry the return type on the declarator itself.
        type_annotation = fn_node.child_by_field_name("type")
        if type_annotation is not None:
            raw = _decode(source_bytes, type_annotation).strip()
            if raw.startswith(":"):
                raw = raw[1:].strip()
            if "=>" in raw:
                return_type = raw.rsplit("=>", 1)[-1].strip()
    return params_text, return_type


def _solidity_signature(source_bytes: bytes, fn_node) -> tuple[str, str | None]:
    """Return ``(params_text, return_type)`` for a Solidity function definition."""
    params: list[str] = []
    for child in fn_node.children:
        if child.type == "parameter":
            params.append(_decode(source_bytes, child))
    params_text = ", ".join(params)
    return_type: str | None = None
    return_type_node = fn_node.child_by_field_name("return_type")
    if return_type_node is not None:
        raw = _decode(source_bytes, return_type_node).strip()
        match = re.search(r"returns\s*\((.*)\)", raw, flags=re.DOTALL)
        if match:
            return_type = match.group(1).strip()
    return params_text, return_type


def _solidity_attrs(source_bytes: bytes, fn_node) -> str:
    """Return visibility/state-mutability/modifier/return-type text for Solidity.

    This is the source text between the closing ``)`` of the parameter list and
    the opening ``{`` or terminating ``;`` of the function definition.
    """
    children = fn_node.children
    try:
        paren_close_idx = next(i for i, c in enumerate(children) if c.type == ")")
    except StopIteration:
        return ""
    parts: list[bytes] = []
    for child in children[paren_close_idx + 1 :]:
        if child.type in {"function_body", ";"}:
            break
        if child.type in {",", "(", ")"}:
            continue
        parts.append(source_bytes[child.start_byte : child.end_byte])
    if not parts:
        return ""
    return b" ".join(parts).decode("utf-8", "replace").strip()


def _extract_full(
    source: str, language: str, safe_identifier: Callable[[str], str]
) -> list[ExtractedFunction] | None:
    """Extract functions with signature metadata, or ``None`` to fall back."""
    canonical = _normalize_language(language)
    if canonical not in SUPPORTED_LANGUAGES:
        return None
    tree, source_bytes = _parse(source, canonical)
    if tree is None:
        return None
    char_offsets = _char_offsets(source_bytes)
    results: list[ExtractedFunction] = []
    for name_node, body_node, fn_node in _iter_function_nodes(
        tree.root_node, canonical, source_bytes
    ):
        raw_name = _decode(source_bytes, name_node)
        name = safe_identifier(raw_name)
        line = name_node.start_point[0] + 1
        declaration_node = _outer_declaration_node(fn_node, canonical, source_bytes)
        body, body_start_byte, body_end_byte = _inner_body_offsets(
            source_bytes, body_node
        )
        params_text = ""
        return_type: str | None = None
        attributes: tuple[str, ...] = ()
        attrs_text = ""
        if canonical == "rust":
            params_text, return_type = _rust_signature(source_bytes, fn_node)
            attributes = _rust_attribute_identifiers(source_bytes, fn_node)
        elif canonical == "go":
            params_text, return_type = _go_signature(source_bytes, fn_node, name_node)
        elif canonical == "typescript":
            params_text, return_type = _typescript_signature(
                source_bytes, fn_node, name_node
            )
        elif canonical == "solidity":
            params_text, return_type = _solidity_signature(source_bytes, fn_node)
            attrs_text = _solidity_attrs(source_bytes, fn_node)
        is_expression_body = (
            body_node is not None and body_node.type not in _BLOCK_NODE_TYPES
        )
        is_top_level = _is_top_level_function(fn_node, canonical)
        results.append(
            ExtractedFunction(
                name=name,
                line=line,
                body=body,
                raw_name=raw_name,
                params_text=params_text,
                return_type=return_type,
                attributes=attributes,
                attrs_text=attrs_text,
                start_byte=declaration_node.start_byte,
                end_byte=declaration_node.end_byte,
                body_start_byte=body_start_byte,
                body_end_byte=body_end_byte,
                start_char=char_offsets[declaration_node.start_byte],
                end_char=char_offsets[declaration_node.end_byte],
                body_start_char=char_offsets[body_start_byte],
                body_end_char=char_offsets[body_end_byte],
                has_body=body_node is not None,
                is_expression_body=is_expression_body,
                is_top_level=is_top_level,
            )
        )
    return results


def extract_contract_functions(
    source: str, language: str, safe_identifier: Callable[[str], str]
) -> list[ExtractedFunction] | None:
    """Return functions with signatures for contract inference, or ``None`` to fall back."""
    return _extract_full(source, language, safe_identifier)


def extract_functions(
    source: str, language: str, safe_identifier: Callable[[str], str]
) -> list[ExtractedFunction] | None:
    """Return full function metadata (signatures + offsets), or ``None`` to fall back."""
    return _extract_full(source, language, safe_identifier)


def _parse_constant_value(text: str) -> int | None:
    """Parse an integer literal, mirroring the semantic-safety parser."""
    text = text.strip()
    if not text:
        return None
    # Drop trailing casts/suffixes such as ``as const`` or Rust type suffixes.
    text = re.split(r"\s+as\b", text, maxsplit=1)[0].strip()
    text = re.sub(
        r"[iu](?:8|16|32|64|128|size)$", "", text, flags=re.IGNORECASE
    ).strip()
    text = text.replace("_", "")
    if not text:
        return None
    try:
        if text.lower().startswith(("0x", "0b", "0o")):
            return int(text, 0)
        return int(text, 10)
    except ValueError:
        return None


def _is_constant_declaration(node, source_bytes: bytes, language: str) -> bool:
    """Return True when ``node`` is a constant/immutable declaration."""
    if language == "solidity":
        if node.type == "constant_variable_declaration":
            return True
        if node.type != "state_variable_declaration":
            return False
        for child in node.children:
            if child.type in {"constant", "immutable"}:
                return True
        return False
    # Rust: const_item / static_item
    return node.type in {"const_item", "static_item"}


def _constant_name_value(node, source_bytes: bytes) -> tuple[str, str] | None:
    """Return ``(name, raw_value_text)`` for a constant declaration node."""
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if name_node is None or value_node is None:
        return None
    name = _decode(source_bytes, name_node)
    if not name.isidentifier():
        return None
    return name, _decode(source_bytes, value_node)


def _is_typescript_const_declaration(node) -> bool:
    """True when ``node`` is a ``const`` lexical declaration."""
    return node.type == "lexical_declaration" and bool(
        node.children and node.children[0].type == "const"
    )


def extract_declared_constants(source: str, language: str) -> dict[str, int] | None:
    """Map declared integer constant names to their value, or ``None`` to fall back.

    Covers Rust ``const`` / ``static``, TypeScript ``const``, and Solidity
    ``constant`` / ``immutable`` declarations.
    """
    canonical = _normalize_language(language)
    if canonical not in SUPPORTED_LANGUAGES:
        return None
    tree, source_bytes = _parse(source, canonical)
    if tree is None:
        return None
    constants: dict[str, int] = {}

    def walk(node):
        if canonical == "typescript" and _is_typescript_const_declaration(node):
            for child in node.children:
                if child.type == "variable_declarator":
                    result = _constant_name_value(child, source_bytes)
                    if result is not None:
                        name, raw = result
                        value = _parse_constant_value(raw)
                        if value is not None:
                            constants.setdefault(name, value)
        elif _is_constant_declaration(node, source_bytes, canonical):
            result = _constant_name_value(node, source_bytes)
            if result is not None:
                name, raw = result
                value = _parse_constant_value(raw)
                if value is not None:
                    constants.setdefault(name, value)
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return constants


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
    constant_index_accesses: tuple[tuple[str, int, str], ...] = ()


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
    constant_index_accesses: list[tuple[str, int, str]] = []

    def visit(node) -> None:
        if node.type == _BINARY_NODE_TYPE:
            operator = _binary_operator(node)
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if operator in {"/", "%"}:
                divisor = _identifier_name(source_bytes, right)
                if divisor is None and right is not None:
                    # Capture selectors such as ``time.Second`` or calls like ``len(x)``
                    # that are not plain identifiers.
                    divisor = re.sub(r"\s+", "", _decode(source_bytes, right).strip())
                if divisor:
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
            if canonical == "go" and base_name is not None and index is not None:
                index_text = re.sub(
                    r"\s+", "", _decode(source_bytes, index).strip()
                )
                literal = re.fullmatch(r"(?:0|[1-9](?:_?[0-9])*)", index_text)
                if literal:
                    constant_index_accesses.append(
                        (
                            base_name,
                            int(index_text.replace("_", "")) + 1,
                            index_text,
                        )
                    )
                else:
                    length_minus = re.fullmatch(
                        rf"len\({re.escape(base_name)}\)-([1-9](?:_?[0-9])*)",
                        index_text,
                    )
                    if length_minus:
                        constant_index_accesses.append(
                            (
                                base_name,
                                int(length_minus.group(1).replace("_", "")),
                                index_text,
                            )
                        )
        elif node.type == member_type:
            if any(child.type == "optional_chain" for child in node.children):
                # TypeScript/JavaScript optional chaining (``a?.b``) is null-safe.
                for child in node.children:
                    visit(child)
                return
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
        constant_index_accesses=tuple(constant_index_accesses),
    )


# ---------------------------------------------------------------------------
# Statement-level traversal (Layer B stage 3: function-local dataflow input).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Statement:
    """A statement recovered from a function body syntax tree.

    ``kind`` is one of ``if`` / ``for`` / ``range`` / ``switch`` / ``case`` /
    ``return`` / ``define`` / ``assign`` / ``inc`` / ``dec`` / ``const`` /
    ``var`` / ``defer`` / ``go`` / ``expr`` / ``block`` / ``closure`` /
    ``terminate`` / ``other``. Nested statements are exposed through ``init``
    (``if``/``for`` initializer), ``body`` (consequence / loop body / case
    body), ``orelse`` (``else`` branch; an ``else if`` is a single nested
    ``if``) and ``post`` (``for`` update clause). Character offsets are relative
    to the body text handed to :func:`extract_statements`.
    """

    kind: str
    text: str
    start: int
    condition: str = ""
    operator: str = ""
    targets: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    init: tuple["Statement", ...] = ()
    body: tuple["Statement", ...] = ()
    orelse: tuple["Statement", ...] = ()
    post: tuple["Statement", ...] = ()
    has_tag: bool = False
    labeled: bool = False
    # The label name when ``labeled`` is set (e.g. ``outer`` in
    # ``outer: for ...``); ``""`` otherwise. Callers that model labelled
    # jumps resolve names against enclosing labelled statements.
    label: str = ""
    # ``True`` on the synthetic block that wraps ``L1: L2: stmt`` — it
    # exists only to carry the outer label and introduces no Go scope.
    stacked_label: bool = False


_GO_TERMINATING_CALLS = re.compile(
    r"^(?:panic|os\.Exit|log\.Fatal\w*|log\.Panic\w*|\w+\.Fatal\w*|runtime\.Goexit)\s*\("
)


def _go_expression_list(source_bytes: bytes, node) -> tuple[str, ...]:
    if node is None:
        return ()
    if node.type == "expression_list":
        return tuple(_decode(source_bytes, child).strip() for child in node.named_children)
    return (_decode(source_bytes, node).strip(),)


def _go_assigned_identifiers(source_bytes: bytes, node) -> set[str]:
    """Return root identifiers assigned anywhere under ``node`` (for closures)."""
    assigned: set[str] = set()
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in {"assignment_statement", "short_var_declaration"}:
            left = current.child_by_field_name("left")
            if left is not None:
                for target in left.named_children:
                    root = target
                    while root.type in {"index_expression", "selector_expression", "unary_expression", "parenthesized_expression"}:
                        root = root.child_by_field_name("operand") or (root.named_children[0] if root.named_children else root)
                        if root is target:
                            break
                    if root.type == "identifier":
                        assigned.add(_decode(source_bytes, root))
        elif current.type in {"inc_statement", "dec_statement"}:
            for child in current.named_children:
                if child.type == "identifier":
                    assigned.add(_decode(source_bytes, child))
        stack.extend(current.children)
    return assigned


def _go_statements(source_bytes: bytes, node, base: int, offsets: list[int]) -> tuple[Statement, ...]:
    """Convert a Go ``block`` / ``statement_list`` node into :class:`Statement` values."""
    if node is None:
        return ()
    if node.type == "block":
        lists = [child for child in node.named_children if child.type == "statement_list"]
        if not lists:
            return ()
        node = lists[0]
    results: list[Statement] = []
    for child in node.named_children:
        declaration_node = child
        label_nodes = []
        while declaration_node is not None and declaration_node.type == "labeled_statement":
            label = ""
            inner = None
            for part in declaration_node.named_children:
                if part.type == "label_name":
                    label = _decode(source_bytes, part)
                else:
                    inner = part
            label_nodes.append((declaration_node, label))
            declaration_node = inner
        if declaration_node is not None and declaration_node.type in {
            "const_declaration",
            "var_declaration",
        }:
            spec_statements = _go_declaration_spec_statements(
                source_bytes, declaration_node, base, offsets
            )
            if spec_statements:
                if not label_nodes:
                    results.extend(spec_statements)
                    continue
                if len(label_nodes) == 1:
                    results.extend(
                        (
                            replace(
                                spec_statements[0],
                                labeled=True,
                                label=label_nodes[0][1],
                            ),
                            *spec_statements[1:],
                        )
                    )
                    continue
                wrapped = spec_statements
                for label_node, label in reversed(label_nodes):
                    wrapped = (
                        Statement(
                            kind="block",
                            text=_decode(source_bytes, label_node).strip(),
                            start=offsets[label_node.start_byte] - base,
                            body=wrapped,
                            labeled=True,
                            label=label,
                            stacked_label=True,
                        ),
                    )
                results.extend(wrapped)
                continue
        statement = _go_statement(source_bytes, child, base, offsets)
        if statement is not None:
            results.append(statement)
    return tuple(results)


def _go_declaration_spec_statements(
    source_bytes: bytes, node, base: int, offsets: list[int]
) -> tuple[Statement, ...] | None:
    """Split multi-spec grouped declarations into source-order specs.

    Each grouped spec is a separate Go declaration: a later initializer may
    read a name introduced by an earlier spec, while names in one multi-name
    spec still bind simultaneously. Single-spec declarations keep the original
    node span/text through the ordinary statement path. Empty groups return no
    statements because they are no-ops.
    """
    if node.type not in {"const_declaration", "var_declaration"}:
        return None
    specs = go_declaration_spec_nodes(node)
    if len(specs) <= 1:
        return None
    kind = "const" if node.type == "const_declaration" else "var"
    statements: list[Statement] = []
    for spec in specs:
        names: list[str] = []
        values: list[str] = []
        spec_names = [
            _decode(source_bytes, child)
            for child in spec.children_by_field_name("name")
        ]
        spec_values = _go_expression_list(
            source_bytes, spec.child_by_field_name("value")
        )
        type_node = spec.child_by_field_name("type")
        type_text = (
            _decode(source_bytes, type_node).strip() if type_node is not None else ""
        )
        for index, name in enumerate(spec_names):
            names.append(name)
            values.append(spec_values[index] if index < len(spec_values) else "")
        statements.append(
            Statement(
                kind=kind,
                text=_decode(source_bytes, spec).strip(),
                start=offsets[spec.start_byte] - base,
                operator="|".join(type_text for _ in names),
                targets=tuple(names),
                values=tuple(values),
            )
        )
    return tuple(statements)


def _go_statement(source_bytes: bytes, node, base: int, offsets: list[int]) -> Statement | None:
    text = _decode(source_bytes, node).strip()
    start = offsets[node.start_byte] - base
    kind = node.type
    children = lambda name: _go_statements(  # noqa: E731
        source_bytes, node.child_by_field_name(name), base, offsets
    )
    if kind == "if_statement":
        init_node = node.child_by_field_name("initializer")
        init = ()
        if init_node is not None:
            init_stmt = _go_statement(source_bytes, init_node, base, offsets)
            init = (init_stmt,) if init_stmt is not None else ()
        condition = node.child_by_field_name("condition")
        alternative = node.child_by_field_name("alternative")
        orelse: tuple[Statement, ...] = ()
        if alternative is not None:
            if alternative.type == "block":
                orelse = _go_statements(source_bytes, alternative, base, offsets)
            else:
                nested = _go_statement(source_bytes, alternative, base, offsets)
                orelse = (nested,) if nested is not None else ()
        return Statement(
            kind="if",
            text=text,
            start=start,
            condition=_decode(source_bytes, condition).strip() if condition is not None else "",
            init=init,
            body=children("consequence"),
            orelse=orelse,
        )
    if kind == "for_statement":
        clause = None
        for child in node.named_children:
            if child.type in {"for_clause", "range_clause"}:
                clause = child
                break
        body = children("body")
        if clause is None:
            condition_node = None
            for child in node.named_children:
                if child.type not in {"block"}:
                    condition_node = child
            condition = _decode(source_bytes, condition_node).strip() if condition_node is not None else ""
            return Statement(kind="for", text=text, start=start, condition=condition, body=body)
        if clause.type == "range_clause":
            left = clause.child_by_field_name("left")
            right = clause.child_by_field_name("right")
            operator_node = None
            for child in clause.children:
                if child.type in {":=", "="}:
                    operator_node = child
            return Statement(
                kind="range",
                text=text,
                start=start,
                operator=operator_node.type if operator_node is not None else "",
                targets=_go_expression_list(source_bytes, left),
                values=(_decode(source_bytes, right).strip(),) if right is not None else (),
                body=body,
            )
        init_node = clause.child_by_field_name("initializer")
        cond_node = clause.child_by_field_name("condition")
        update_node = clause.child_by_field_name("update")
        init_stmt = _go_statement(source_bytes, init_node, base, offsets) if init_node is not None else None
        update_stmt = _go_statement(source_bytes, update_node, base, offsets) if update_node is not None else None
        return Statement(
            kind="for",
            text=text,
            start=start,
            condition=_decode(source_bytes, cond_node).strip() if cond_node is not None else "",
            init=(init_stmt,) if init_stmt is not None else (),
            body=body,
            post=(update_stmt,) if update_stmt is not None else (),
        )
    if kind in {"expression_switch_statement", "type_switch_statement", "select_statement"}:
        init_node = node.child_by_field_name("initializer")
        init_stmt = _go_statement(source_bytes, init_node, base, offsets) if init_node is not None else None
        value_node = (
            node.child_by_field_name("value")
            if kind in {"expression_switch_statement", "type_switch_statement"}
            else None
        )
        type_guard = None
        if kind == "type_switch_statement":
            # A leading SimpleStmt (``switch n := f(); v := x.(type)``)
            # is a plain statement child, not an ``initializer`` field.
            if init_stmt is None:
                init_node = next(
                    (
                        child
                        for child in node.named_children
                        if child.type
                        in {
                            "short_var_declaration",
                            "assignment_statement",
                            "inc_statement",
                            "dec_statement",
                            "expression_statement",
                            "send_statement",
                        }
                    ),
                    None,
                )
                init_stmt = (
                    _go_statement(source_bytes, init_node, base, offsets)
                    if init_node is not None
                    else None
                )
            # ``v := x.(type)`` — the bound name sits in an
            # ``expression_list`` child, the value under ``value`` and
            # ``.(type)`` is anonymous syntax. Synthesize the init
            # ``define`` so the binding is not silently dropped.
            expr_list = next(
                (
                    child
                    for child in node.named_children
                    if child.type == "expression_list"
                ),
                None,
            )
            if expr_list is not None and value_node is not None:
                # The guard ends at the ``)`` closing ``(type)`` — slice
                # the source verbatim so whitespace and comments inside
                # the guard still satisfy the span check.
                close = source_bytes.find(b")", value_node.end_byte)
                if close != -1:
                    names = tuple(
                        _decode(source_bytes, n).strip()
                        for n in expr_list.named_children
                        if n.type != "comment"
                    )
                    guard_start = offsets[expr_list.start_byte] - base
                    guard_text = source_bytes[
                        expr_list.start_byte : close + 1
                    ].decode("utf-8", "replace")
                    type_guard = Statement(
                        kind="define",
                        text=guard_text,
                        start=guard_start,
                        operator=":=",
                        targets=names,
                        # Only the operand expression is read — a
                        # type-switch guard never panics on a nil
                        # interface (nil routes to ``case nil``).
                        values=(_decode(source_bytes, value_node).strip(),),
                    )
        cases: list[Statement] = []
        for child in node.named_children:
            if child.type in {"expression_case", "default_case", "type_case", "communication_case"}:
                case_values = ()
                case_targets = ()
                if child.type == "expression_case":
                    case_values = _go_expression_list(source_bytes, child.child_by_field_name("value"))
                elif child.type == "communication_case":
                    for grand in child.named_children:
                        if grand.type == "send_statement":
                            # `ch <- x` — the channel and the value
                            # both read.
                            case_values = tuple(
                                _decode(source_bytes, n).strip()
                                for n in (
                                    grand.child_by_field_name("channel"),
                                    grand.child_by_field_name("value"),
                                )
                                if n is not None
                            )
                        elif grand.type == "receive_statement":
                            # `v := <-ch` — the bound names assign,
                            # the receive expression reads.
                            recv = None
                            for part in grand.named_children:
                                if part.type == "expression_list":
                                    case_targets = tuple(
                                        _decode(source_bytes, t).strip()
                                        for t in part.named_children
                                        if t.type != "comment"
                                    )
                                elif part.is_named:
                                    recv = part
                            if recv is not None:
                                case_values = (
                                    _decode(source_bytes, recv).strip(),
                                )
                case_body: list[Statement] = []
                for grand in child.named_children:
                    if grand.type == "statement_list":
                        case_body.extend(_go_statements(source_bytes, grand, base, offsets))
                cases.append(
                    Statement(
                        kind="case" if child.type != "default_case" else "default",
                        text=_decode(source_bytes, child).strip(),
                        start=offsets[child.start_byte] - base,
                        targets=case_targets,
                        values=case_values,
                        body=tuple(case_body),
                    )
                )
        return Statement(
            kind="switch",
            text=text,
            start=start,
            condition=_decode(source_bytes, value_node).strip() if value_node is not None else "",
            # ``expression`` | ``type`` | ``select`` — callers modelling
            # only expression switches reject the other two operators.
            operator=(
                "select"
                if kind == "select_statement"
                else "type"
                if kind == "type_switch_statement"
                else "expression"
            ),
            init=tuple(
                s for s in (init_stmt, type_guard) if s is not None
            ),
            body=tuple(cases),
            has_tag=value_node is not None or kind != "expression_switch_statement",
        )
    if kind == "return_statement":
        values = ()
        for child in node.named_children:
            values = _go_expression_list(source_bytes, child)
        return Statement(kind="return", text=text, start=start, values=values)
    if kind in {"break_statement", "continue_statement", "goto_statement", "fallthrough_statement"}:
        return Statement(kind=kind[: -len("_statement")], text=text, start=start)
    if kind == "short_var_declaration":
        return Statement(
            kind="define",
            text=text,
            start=start,
            operator=":=",
            targets=_go_expression_list(source_bytes, node.child_by_field_name("left")),
            values=_go_expression_list(source_bytes, node.child_by_field_name("right")),
        )
    if kind == "assignment_statement":
        operator = node.child_by_field_name("operator")
        return Statement(
            kind="assign",
            text=text,
            start=start,
            operator=operator.type if operator is not None else "=",
            targets=_go_expression_list(source_bytes, node.child_by_field_name("left")),
            values=_go_expression_list(source_bytes, node.child_by_field_name("right")),
        )
    if kind in {"inc_statement", "dec_statement"}:
        targets = tuple(_decode(source_bytes, child).strip() for child in node.named_children[:1])
        return Statement(kind="inc" if kind == "inc_statement" else "dec", text=text, start=start, targets=targets)
    if kind in {"const_declaration", "var_declaration"}:
        names: list[str] = []
        values: list[str] = []
        types: list[str] = []
        specs = go_declaration_spec_nodes(node)
        for spec in specs:
            spec_names = [
                _decode(source_bytes, child)
                for child in spec.children_by_field_name("name")
            ]
            spec_values = _go_expression_list(source_bytes, spec.child_by_field_name("value"))
            type_node = spec.child_by_field_name("type")
            type_text = _decode(source_bytes, type_node).strip() if type_node is not None else ""
            for index, name in enumerate(spec_names):
                names.append(name)
                values.append(spec_values[index] if index < len(spec_values) else "")
                types.append(type_text)
        return Statement(
            kind="const" if kind == "const_declaration" else "var",
            text=text,
            start=start,
            operator="|".join(types),
            targets=tuple(names),
            values=tuple(values),
        )
    if kind in {"defer_statement", "go_statement"}:
        call = node.named_children[0] if node.named_children else None
        call_text = _decode(source_bytes, call).strip() if call is not None else ""
        if call is not None and call.type == "call_expression":
            fn = call.child_by_field_name("function")
            if fn is not None and fn.type == "func_literal":
                assigned = _go_assigned_identifiers(source_bytes, fn)
                return Statement(
                    kind="closure",
                    text=text,
                    start=start,
                    operator=kind[:-10],
                    targets=tuple(sorted(assigned)),
                    values=(call_text,),
                )
        return Statement(
            kind="defer" if kind == "defer_statement" else "go",
            text=text,
            start=start,
            values=(call_text,),
        )
    if kind == "send_statement":
        # `ch <- x` — a straight-line effect with no assigned names,
        # so the CFG walks it like any other expression statement;
        # the summary analyzer decides whether the send admits.
        return Statement(kind="expr", text=text, start=start, values=(text,))
    if kind == "expression_statement":
        expr = node.named_children[0] if node.named_children else None
        expr_text = _decode(source_bytes, expr).strip() if expr is not None else text
        if _GO_TERMINATING_CALLS.match(expr_text):
            return Statement(kind="terminate", text=text, start=start, values=(expr_text,))
        return Statement(kind="expr", text=text, start=start, values=(expr_text,))
    if kind == "block":
        return Statement(kind="block", text=text, start=start, body=_go_statements(source_bytes, node, base, offsets))
    if kind == "labeled_statement":
        inner = None
        label = ""
        for child in node.named_children:
            if child.type == "label_name":
                label = _decode(source_bytes, child)
            else:
                inner = child
        if inner is None:
            # ``L:`` immediately before ``}`` — tree-sitter reports the
            # labelled statement with no child. The label still exists
            # as a ``goto`` target; model it as a no-op expression.
            return Statement(
                kind="expr", text=text, start=start,
                labeled=True, label=label,
            )
        statement = _go_statement(source_bytes, inner, base, offsets)
        if statement is None:
            # ``L: ;`` — the labelled statement is empty, but the label
            # still exists as a ``goto`` target. Model it as a no-op
            # expression statement.
            return Statement(
                kind="expr", text=text, start=start,
                labeled=True, label=label,
            )
        if statement.labeled:
            # ``L1: L2: stmt`` — both labels exist: carry the outer one
            # on a block wrapping the inner labelled statement.
            return Statement(
                kind="block", text=text, start=start,
                body=(statement,), labeled=True, label=label,
                stacked_label=True,
            )
        return replace(statement, labeled=True, label=label)
    if kind == "func_literal":
        return Statement(
            kind="closure",
            text=text,
            start=start,
            targets=tuple(sorted(_go_assigned_identifiers(source_bytes, node))),
        )
    if kind in {"comment", "empty_statement"}:
        return None
    return Statement(kind="other", text=text, start=start)


def _go_collect_closure_assignments(source_bytes: bytes, root) -> set[str]:
    """Return identifiers assigned inside any ``func_literal`` under ``root``."""
    assigned: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "func_literal":
            assigned |= _go_assigned_identifiers(source_bytes, node)
            continue
        stack.extend(node.children)
    return assigned


@dataclass(frozen=True)
class StatementTree:
    """Statements of a function body plus body-wide syntactic facts."""

    statements: tuple[Statement, ...]
    # Identifiers assigned inside nested function literals; facts about them
    # cannot be trusted across calls of the closure.
    closure_assigned: frozenset[str]
    # Identifiers whose address is taken (``&x``); they may be mutated through
    # pointers so facts about them are unreliable after any call.
    address_taken: frozenset[str]


_GO_BODY_PREFIX = "package p\nfunc _() {\n"


def extract_statements(body: str, language: str) -> StatementTree | None:
    """Return the statement tree of a function ``body`` or ``None`` to fall back.

    Only Go is supported for now; other languages return ``None`` so callers
    keep their regex heuristics. ``body`` is the text between the outer braces
    (``ExtractedFunction.body``).
    """
    canonical = _normalize_language(language)
    if canonical != "go":
        return None
    parser = _get_parser(canonical)
    if parser is None:
        return None
    wrapped = _GO_BODY_PREFIX + body + "\n}\n"
    source_bytes = wrapped.encode("utf-8")
    root_node = parse_go_with_compact_group_recovery(parser, source_bytes)
    if root_node is None:
        return None
    fn_node = None
    for child in root_node.named_children:
        if child.type == "function_declaration":
            fn_node = child
    if fn_node is None:
        return None
    block = fn_node.child_by_field_name("body")
    if block is None:
        return None
    offsets = _char_offsets(source_bytes)
    base = len(_GO_BODY_PREFIX)
    statements = _go_statements(source_bytes, block, base, offsets)
    address_taken = frozenset(
        re.findall(r"(?<![&\w)\]])&([A-Za-z_]\w*)\b(?!\s*[\{\[])", body)
    )
    return StatementTree(
        statements=statements,
        closure_assigned=frozenset(_go_collect_closure_assignments(source_bytes, block)),
        address_taken=address_taken,
    )
