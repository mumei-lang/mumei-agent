"""Language-specific "common problem" heuristics (V1-B-2).

Each detector is a small self-contained function returning
``ForeignSafetyIssue`` objects and is registered in ``LANGUAGE_PATTERNS``.
Adding a pattern means writing one detector and appending one entry —
no dispatch code to edit. All patterns are advisory: they carry no
counterexample, so downstream surfaces report them as warnings rather than
hard violations.

Detectors receive a ``PatternContext`` carrying the tree-sitter parse of the
whole source when the language's grammar is available. The Rust and
TypeScript detectors use it for scope-aware decisions (a guard only counts
when it dominates the call site; a call's "handled" status comes from its
position in the syntax tree) instead of scanning body text — body-text scans
let a guard in a sibling or outer branch suppress unrelated findings. When
``ctx.tree`` is ``None`` (grammar missing or unparseable) they fall back to
the previous text heuristics, marked ``confidence="medium"``.

Opt-out: a ``mumei:allow`` marker in the file's own comment syntax —
``# mumei:allow`` for Python, ``// mumei:allow`` for Rust/Go/TypeScript/
Solidity — suppresses a finding on the same line or the line immediately
below it. Rust additionally honors ``#[allow(mumei::*)]`` attribute lines,
which suppress the line below and, when placed on a ``fn`` item, every
finding inside that function. Findings that carry no source line (call
sites a text fallback cannot locate) are never suppressed.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Callable, Iterable

from agent import tree_sitter_extract
from agent.cross_validation_foreign import _strip_go_rust_literals_and_comments
from agent.strategies.foreign_code_strategy_helpers import (
    _GUARD_HOLDS_MECHANISMS,
    _GUARD_NEGATED_MECHANISMS,
    ForeignSafetyIssue,
    _balanced_brace_body,
    _go_function_blocks,
    _guard_mechanism,
    _is_generated_source,
    _is_solidity_mock_source,
    _mask_nested_function_literals,
    _normalize_language,
    _rust_function_scopes,
    _solidity_function_blocks_with_attrs,
    _solidity_function_scopes,
    _typescript_function_blocks,
)


@dataclass(frozen=True)
class PatternContext:
    """Syntactic context shared by all pattern detectors on one source.

    ``tree``/``source_bytes`` are the tree-sitter parse of the whole source,
    or ``None`` when the grammar is unavailable or the parse fails — in that
    case detectors must use their text fallback paths. The context is built
    once per ``language_pattern_issues`` call so detectors never re-parse.
    """

    language: str
    tree: object | None = None
    source_bytes: bytes | None = None


def _node_text(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _body_offset(
    haystacks: tuple[str, ...],
    body: str,
    used_offsets: set[int],
    non_code: bytearray | None = None,
) -> int:
    """First offset of ``body`` not already claimed, or ``-1``.

    Function bodies handed to the text fallbacks are exact slices of the raw
    source — or, for the Rust regex fallback, of the comment-stripped copy
    that shares its offsets — so a hit in either haystack is a source
    offset. Extractors do not always list functions in source order (named
    declarations before arrows/literals), so scanning every occurrence and
    skipping offsets already consumed keeps duplicate bodies attributed to
    distinct locations. ``non_code`` marks offsets inside string literals
    or comments — a body whose text also appears inside a literal must not
    steal that occurrence's location from the real body.
    """
    for text in haystacks:
        start = 0
        while True:
            offset = text.find(body, start)
            if offset < 0:
                break
            if offset not in used_offsets and not (
                non_code is not None and non_code[offset]
            ):
                used_offsets.add(offset)
                return offset
            start = offset + 1
    return -1


def _issue_line(source: str, body_offset: int, offset_in_body: int) -> int:
    """1-based line of the construct ``offset_in_body`` chars into a function
    body that starts at ``body_offset`` in ``source``; 0 when unlocated."""
    if body_offset < 0 or offset_in_body < 0:
        return 0
    return source.count("\n", 0, body_offset + offset_in_body) + 1


def _paren_args(text: str, open_paren: int) -> str:
    """Return the contents of the parenthesized span starting at
    ``text[open_paren] == "("`` (nested parens counted)."""
    depth = 0
    for i in range(open_paren, len(text)):
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : i]
    return text[open_paren + 1 :]


def _strip_ts_literals_and_comments(text: str) -> str:
    """Mask TS/JS ``'…'``/``"…"``/template-literal contents (delimiters kept,
    positions preserved) and blank ``//``/``/* … */`` comments so advisory
    patterns can't match inside literals."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("//", i):
            end = text.find("\n", i)
            if end == -1:
                end = len(text)
            out.append(" " * (end - i))
            i = end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = len(text) if end == -1 else end + 2
            out.append(
                "".join("\n" if c == "\n" else " " for c in text[i:end])
            )
            i = end
            continue
        char = text[i]
        if char == "`":
            # Template literal: blank the literal text but keep ``${…}``
            # interpolations — they are code and can carry patterns like
            # ``x!``/``eval(`` (with their own literals recursively masked).
            inner_parts: list[str] = []
            j = i + 1
            while j < len(text):
                if text[j] == "\\":
                    inner_parts.extend(
                        "\n" if c == "\n" else " "
                        for c in text[j : j + 2]
                    )
                    j += 2
                    continue
                if text[j] == "`":
                    break
                if text[j] == "$" and j + 1 < len(text) and text[j + 1] == "{":
                    depth = 1
                    k = j + 2
                    in_str: str | None = None
                    while k < len(text):
                        ch = text[k]
                        if in_str:
                            if ch == "\\":
                                k += 1
                            elif ch == in_str:
                                in_str = None
                        elif ch in "\"'`":
                            in_str = ch
                        elif ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        k += 1
                    interp = text[j + 2 : k]
                    inner_parts.append(
                        "${" + _strip_ts_literals_and_comments(interp) + "}"
                    )
                    j = k + 1
                    continue
                inner_parts.append("\n" if text[j] == "\n" else " ")
                j += 1
            if j >= len(text):
                out.append("`" + "".join(inner_parts))
                break
            out.append("`" + "".join(inner_parts) + "`")
            i = j + 1
            continue
        if char in "\"'":
            j = i + 1
            while j < len(text):
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == char:
                    break
                j += 1
            if j >= len(text):
                out.append(
                    char
                    + "".join(
                        "\n" if c == "\n" else " " for c in text[i + 1 :]
                    )
                )
                break
            inner = "".join("\n" if c == "\n" else " " for c in text[i + 1 : j])
            out.append(char + inner + text[j])
            i = j + 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

_MUTABLE_DEFAULT_TYPES = (ast.List, ast.Dict, ast.Set)
_MUTABLE_DEFAULT_CALLS = frozenset({"list", "dict", "set", "bytearray"})
# ``except*`` (PEP 654) lands in ast.TryStar on 3.11+.
_PY_TRY_TYPES: tuple[type[ast.AST], ...] = tuple(
    t for t in (ast.Try, getattr(ast, "TryStar", None)) if t is not None
)


def _python_noop_statement(stmt: ast.AST) -> bool:
    """True for ``pass`` and the ``...`` placeholder body."""
    if isinstance(stmt, ast.Pass):
        return True
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    )


def _python_swallow_all_name(handler_type: ast.AST | None) -> str | None:
    """Name of the catch-all exception in ``handler_type`` — bare
    ``Exception``/``BaseException`` or a tuple containing either."""
    names = (
        (handler_type,)
        if isinstance(handler_type, ast.Name)
        else handler_type.elts
        if isinstance(handler_type, ast.Tuple)
        else ()
    )
    for node in names:
        if (
            isinstance(node, ast.Name)
            and node.id in {"Exception", "BaseException"}
        ):
            return node.id
    return None


def _python_own_statements(function: ast.AST) -> Iterable[ast.AST]:
    """Yield the statements of ``function`` without descending into nested
    function/class definitions."""
    stack = list(getattr(function, "body", []))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield child
        stack.extend(ast.iter_child_nodes(child))


def _python_mutable_default_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    issues: list[ForeignSafetyIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        positional = node.args.posonlyargs + node.args.args
        pairs: list[tuple[str, ast.AST]] = list(
            zip(
                [a.arg for a in positional][-len(node.args.defaults) :]
                if node.args.defaults
                else [],
                node.args.defaults,
            )
        )
        pairs += [
            (a.arg, d)
            for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults)
            if d is not None
        ]
        for param_name, default in pairs:
            mutable = isinstance(default, _MUTABLE_DEFAULT_TYPES) or (
                isinstance(default, ast.Call)
                and isinstance(default.func, ast.Name)
                and default.func.id in _MUTABLE_DEFAULT_CALLS
            )
            if not mutable:
                continue
            try:
                default_text = ast.unparse(default)
            except ValueError:
                default_text = "..."
            issues.append(
                ForeignSafetyIssue(
                    function_name=node.name,
                    message=(
                        f"Python function `{node.name}` uses a mutable default "
                        f"argument `{param_name}={default_text}` that is shared "
                        "across calls"
                    ),
                    line=default.lineno,
                )
            )
    return issues


def _python_swallow_except_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    issues: list[ForeignSafetyIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in _python_own_statements(node):
            if not isinstance(child, _PY_TRY_TYPES):
                continue
            for handler in child.handlers:
                if handler.type is None:
                    issues.append(
                        ForeignSafetyIssue(
                            function_name=node.name,
                            message=(
                                f"Python function `{node.name}` has a bare "
                                "`except:` that swallows all exceptions "
                                "(including KeyboardInterrupt/SystemExit)"
                            ),
                            line=handler.lineno,
                        )
                    )
                elif (
                    (swallow_name := _python_swallow_all_name(handler.type))
                    is not None
                    and all(_python_noop_statement(stmt) for stmt in handler.body)
                ):
                    issues.append(
                        ForeignSafetyIssue(
                            function_name=node.name,
                            message=(
                                f"Python function `{node.name}` catches "
                                f"`{swallow_name}` and does nothing — "
                                "the error is silently swallowed"
                            ),
                            line=handler.lineno,
                        )
                    )
    return issues


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------

# Receivers cover the common expression chains: plain idents, call/index
# segments (`v.pop()`, `m["k"]`), member chains (`self.opt`), and `::` path
# prefixes with single-level turbofish (`fs::read(path)`). Nested parens or
# nested generics in turbofish (`collect::<Vec<i32>>()`) fall back to the
# nearest simple ident or go unreported.
_RUST_UNWRAP_RE = re.compile(
    r"\b(?P<recv>"
    r"(?:[A-Za-z_]\w*::)*"
    r"[A-Za-z_]\w*(?:::<[^<>]*>)?"
    r"(?:\([^()]*\))?"
    r"(?:(?:\.[A-Za-z_]\w*|\[[^\[\]]*\])(?:\([^()]*\))?)*"
    r")\s*\.\s*(?P<call>unwrap|expect)\s*\("
)
_RUST_NESTED_FN_RE = re.compile(r"\bfn\s+[A-Za-z_]\w*")

_RUST_UNWRAP_METHODS = frozenset({"unwrap", "expect"})
# Standard-library predicates on the receiver: ``then``-polarity checks
# prove the value variant when true (the composed ``*_and`` predicates keep
# that polarity); ``else``-polarity checks prove it when false
# (``is_none_or`` false means Some). ``is_err_and`` takes neither polarity —
# true proves ``Err`` and false is inconclusive — so it is absent from both.
_RUST_POSITIVE_CHECKS = frozenset({"is_some", "is_ok", "is_some_and", "is_ok_and"})
_RUST_NEGATIVE_CHECKS = frozenset({"is_err", "is_none", "is_none_or"})
_RUST_DIVERGING_MACROS = frozenset({"panic", "unreachable", "todo", "unimplemented"})
_RUST_ASSERT_MACROS = frozenset({"assert", "debug_assert"})
# ``async {}`` blocks are deferred like closures; ``unsafe``/``const``
# blocks evaluate inline and stay transparent.
_RUST_FN_BOUNDARY_TYPES = frozenset(
    {"function_item", "closure_expression", "async_block"}
)
# Patterns that select the value-carrying variant: inside a ``Some``/``Ok``
# arm (or after a let-else on one) the receiver is safe to unwrap. ``None``/
# ``Err`` arms run precisely when it is not.
_RUST_VALUE_PATTERN_RE = re.compile(r"\b(?:Some|Ok)\b")
_RUST_EMPTY_PATTERN_RE = re.compile(r"\b(?:None|Err)\b")


def _mask_rust_nested_fns(body: str) -> str:
    """Blank out nested ``fn`` item spans — ``_rust_function_scopes`` returns
    an outer function's body including nested ``fn`` items, so without
    masking a call inside ``inner`` would be attributed to ``outer`` too."""
    chars = list(body)
    for match in _RUST_NESTED_FN_RE.finditer(body):
        brace = body.find("{", match.end())
        if brace < 0:
            continue
        inner = _balanced_brace_body(body, brace)
        end = brace + len(inner) + 1
        for i in range(match.start(), min(end, len(body))):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def _rust_unwrap_guarded(body: str, receiver: str) -> bool:
    recv = re.escape(receiver)
    return bool(
        re.search(
            rf"\b{recv}\s*\.\s*"
            rf"(?:is_ok|is_some|is_err|is_none|is_ok_and|is_some_and|is_none_or)\s*\(",
            body,
        )
        # ``res.ok()``/``res.err()`` project the receiver into an Option;
        # the composed checks on that projection keep a provable polarity.
        or re.search(
            rf"\b{recv}\s*\.\s*ok\s*\(\s*\)\s*\.\s*"
            rf"(?:is_some|is_none|is_some_and|is_none_or)\s*\(",
            body,
        )
        or re.search(
            rf"\b{recv}\s*\.\s*err\s*\(\s*\)\s*\.\s*is_none\s*\(", body
        )
        or re.search(rf"\b(?:if|while)\s+let\b[^{{}};]*\b{recv}\b", body)
        or re.search(rf"\blet\b[^{{}};]*\b{recv}\b[^{{}};]*\belse\b", body)
        or re.search(rf"\bmatch\s+{recv}\b", body)
        or re.search(rf"\b{recv}\s*\?", body)
    )


def _rust_unwrap_expect_text_issues(source: str) -> list[ForeignSafetyIssue]:
    """Body-text scan used when the tree-sitter grammar is unavailable.

    Any guard-looking text anywhere in the function body suppresses the
    finding, including guards in sibling branches or after the call — the
    known false-negative the scoped path exists to fix.
    """
    issues: list[ForeignSafetyIssue] = []
    stripped_source = _strip_go_rust_literals_and_comments(source)
    non_code = _non_code_states(source, "rust")
    used_offsets: set[int] = set()
    for name, body, _params in _rust_function_scopes(source):
        offset = _body_offset(
            (source, stripped_source), body, used_offsets, non_code
        )
        masked = _mask_rust_nested_fns(_strip_go_rust_literals_and_comments(body))
        for match in _RUST_UNWRAP_RE.finditer(masked):
            receiver = match.group("recv")
            if _rust_unwrap_guarded(masked, receiver):
                continue
            call = match.group("call")
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"Rust function `{name}` can panic via "
                        f"`{receiver}.{call}()` without a contract that the "
                        "value is Ok/Some"
                    ),
                    confidence="medium",
                    line=_issue_line(source, offset, match.start()),
                )
            )
    return issues


def _rust_expr_key(source_bytes: bytes, node) -> str:
    """Whitespace-insensitive text for comparing receiver expressions —
    parenthesized wrappers peel to the inner expression."""
    while node.type == "parenthesized_expression":
        inner = next(iter(node.named_children), None)
        if inner is None:
            break
        node = inner
    return re.sub(r"\s+", "", _node_text(source_bytes, node))


def _rust_iterable_base_key(source_bytes: bytes, node) -> str:
    """Receiver key behind a ``for`` iterable: strips a leading borrow
    (``&``/``& mut``) and a trailing ``.iter()``/``.iter_mut()`` so
    ``for v in &res`` / ``for v in res.iter()`` still identify ``res``."""
    key = _rust_expr_key(source_bytes, node)
    key = re.sub(r"^&(?:mut)?", "", key)
    return re.sub(r"\.(?:iter|iter_mut|into_iter)\(\)$", "", key)


def _rust_call_parts(node, source_bytes: bytes) -> tuple[str, str] | None:
    """``(receiver_key, method_name)`` for a ``receiver.method(...)`` call."""
    if node.type != "call_expression":
        return None
    function = node.child_by_field_name("function")
    if function is None or function.type != "field_expression":
        return None
    value = function.child_by_field_name("value")
    field = function.child_by_field_name("field")
    if value is None or field is None:
        return None
    if field.type == "generic_function":
        field = field.child_by_field_name("function") or next(
            iter(field.named_children), None
        )
        if field is None:
            return None
    return _rust_expr_key(source_bytes, value), _node_text(source_bytes, field)


def _rust_check_polarity(
    receiver_key: str, method: str, recv: str
) -> str | None:
    """Polarity of ``receiver_key.method(...)`` as a check on ``recv``:
    ``"then"`` when the call being true proves ``recv`` Ok/Some,
    ``"else"`` when it being false proves that, ``None`` otherwise.

    Only standard-library method names resolve. ``res.ok()``/
    ``res.err()`` project a ``Result`` into an ``Option`` — ``err()``
    flips the value variant, and the composed ``*_and``/``*_or``
    predicates keep a polarity only where unambiguous. Custom guard
    functions (``guard(&res)``) and anything resolved through imports or
    other files stay out of scope by design.
    """
    if receiver_key == recv:
        if method in _RUST_POSITIVE_CHECKS:
            return "then"
        if method in _RUST_NEGATIVE_CHECKS:
            return "else"
        return None
    if receiver_key == f"{recv}.ok()":
        # res.ok() is Some exactly when res is Ok — same polarities apply
        # to the plain and composed Option checks on the projection.
        if method in {"is_some", "is_some_and"}:
            return "then"
        if method in {"is_none", "is_none_or"}:
            return "else"
        return None
    if receiver_key == f"{recv}.err()":
        # res.err() is Some exactly when res is Err — the flip: only the
        # plain predicates are unambiguous on this projection.
        if method == "is_none":
            return "then"
        if method == "is_some":
            return "else"
    return None


def _rust_pattern_is_value_arm(pattern, source_bytes: bytes) -> bool:
    """True when a match/let pattern selects the ``Some``/``Ok`` variant."""
    text = _node_text(source_bytes, pattern)
    if _RUST_EMPTY_PATTERN_RE.search(text):
        return False
    return bool(_RUST_VALUE_PATTERN_RE.search(text))


def _rust_flip(polarity: str | None) -> str | None:
    return {"then": "else", "else": "then"}.get(polarity)


def _rust_condition_polarity(condition, recv: str, source_bytes: bytes) -> str | None:
    """Which outcome of ``condition`` makes ``recv`` provably Ok/Some.

    ``"then"`` when the condition being true implies it, ``"else"`` when the
    condition being false implies it, ``None`` when neither can be shown.
    """
    while condition is not None and condition.type == "parenthesized_expression":
        condition = next(iter(condition.named_children), None)
    if condition is None:
        return None
    if condition.type == "unary_expression" and (
        condition.children and condition.children[0].type == "!"
    ):
        inner = next(iter(condition.named_children), None)
        return _rust_flip(_rust_condition_polarity(inner, recv, source_bytes))
    if condition.type == "let_condition":
        # ``if let Some(v) = recv``: the consequence runs only when the
        # pattern matched, i.e. when recv held a value. An ``Err``/``None``
        # pattern is the mirror image: the else/fallthrough path proves
        # recv holds the value variant.
        named = condition.named_children
        if len(named) >= 2 and _rust_expr_key(source_bytes, named[-1]) == recv:
            if _rust_pattern_is_value_arm(named[0], source_bytes):
                return "then"
            if _RUST_EMPTY_PATTERN_RE.search(
                _node_text(source_bytes, named[0])
            ):
                return "else"
        return None
    if condition.type == "let_chain":
        # ``if let Some(v) = recv && flag``: every conjunct holds on the then
        # path, so a let-condition on recv guards the consequence. The else
        # path may have failed on another conjunct — never guardable here.
        for child in condition.named_children:
            if _rust_condition_polarity(child, recv, source_bytes) == "then":
                return "then"
        return None
    if condition.type == "binary_expression":
        operator = condition.child_by_field_name("operator")
        left = condition.child_by_field_name("left")
        right = condition.child_by_field_name("right")
        op = operator.type if operator is not None else ""
        left_p = _rust_condition_polarity(left, recv, source_bytes)
        right_p = _rust_condition_polarity(right, recv, source_bytes)
        if op == "&&":
            # then: both operands hold — either operand's guard applies.
            if "then" in (left_p, right_p):
                return "then"
            # else: at least one failed — only safe when either failure
            # alone still proves recv Ok/Some.
            if left_p == "else" and right_p == "else":
                return "else"
            return None
        if op == "||":
            # else: both operands failed — either operand's guard applies.
            if "else" in (left_p, right_p):
                return "else"
            if left_p == "then" and right_p == "then":
                return "then"
            return None
        # Other operators (==, <, ...) fall through to the generic scan —
        # the guard call inside them is not a dominance guard, matching the
        # leniency of the text path.
    # Generic scan: the first decisive ``recv``-check in the condition
    # decides; calls that are not provable checks on ``recv`` are skipped.
    stack = [condition]
    while stack:
        node = stack.pop()
        parts = _rust_call_parts(node, source_bytes)
        if parts is not None:
            polarity = _rust_check_polarity(parts[0], parts[1], recv)
            if polarity is not None:
                return polarity
        stack.extend(node.children)
    return None


def _rust_statement_inner(node):
    """Peel ``expression_statement``/``empty_statement`` wrappers."""
    while node is not None and node.type in {
        "expression_statement",
        "empty_statement",
    }:
        node = next(iter(node.named_children), None)
    return node


def _rust_is_diverging_macro(node, source_bytes: bytes) -> bool:
    if node is None or node.type != "macro_invocation":
        return False
    macro = node.child_by_field_name("macro")
    return (
        macro is not None
        and _node_text(source_bytes, macro) in _RUST_DIVERGING_MACROS
    )


def _rust_if_always_diverges(node, source_bytes: bytes) -> bool:
    consequence = node.child_by_field_name("consequence")
    if consequence is None or not _rust_block_diverges(
        consequence, source_bytes
    ):
        return False
    alternative = node.child_by_field_name("alternative")
    if alternative is None:
        return False
    body = _rust_statement_inner(next(iter(alternative.named_children), None))
    if body is None:
        return False
    if body.type == "if_expression":
        return _rust_if_always_diverges(body, source_bytes)
    return body.type == "block" and _rust_block_diverges(body, source_bytes)


def _rust_statement_diverges(node, source_bytes: bytes) -> bool:
    """True when a block-level statement always exits (return/break/
    continue/panic!/unreachable!, a bare nested block that diverges, or an
    if whose every arm diverges)."""
    inner = _rust_statement_inner(node)
    if inner is None:
        return False
    if inner.type in {
        "return_expression",
        "break_expression",
        "continue_expression",
    }:
        return True
    if _rust_is_diverging_macro(inner, source_bytes):
        return True
    if inner.type == "block":
        return _rust_block_diverges(inner, source_bytes)
    if inner.type == "if_expression":
        return _rust_if_always_diverges(inner, source_bytes)
    return False


def _rust_block_diverges(block, source_bytes: bytes) -> bool:
    """True when a direct statement of ``block`` always exits control flow."""
    for child in block.named_children:
        if _rust_statement_diverges(child, source_bytes):
            return True
    return False


def _rust_if_guards_fallthrough(if_node, recv: str, source_bytes: bytes) -> bool:
    """True when every non-diverging exit of ``if_node`` leaves ``recv``
    Ok/Some — e.g. ``if r.is_err() { return }`` or ``if let Some(v) = r {
    ... } else { return }``."""
    condition = if_node.child_by_field_name("condition")
    consequence = if_node.child_by_field_name("consequence")
    if condition is None or consequence is None:
        return False
    polarity = _rust_condition_polarity(condition, recv, source_bytes)
    if polarity != "then" and not _rust_block_diverges(
        consequence, source_bytes
    ):
        return False
    alternative = if_node.child_by_field_name("alternative")
    if alternative is None:
        return polarity == "else"
    body = _rust_statement_inner(next(iter(alternative.named_children), None))
    if body is None:
        return polarity == "else"
    if body.type == "block":
        return polarity == "else" or _rust_block_diverges(body, source_bytes)
    if body.type == "if_expression":
        # ``else if`` chains guard the fallthrough the same way.
        return _rust_if_guards_fallthrough(body, recv, source_bytes)
    return False


def _rust_match_guards_fallthrough(match_node, recv: str, source_bytes: bytes) -> bool:
    """True when a preceding ``match recv`` leaves ``recv`` Ok/Some on every
    non-diverging arm — value arms (``Some``/``Ok``) keep it, diverging arms
    (``None => return`` / ``Err(_) => panic!()``) never reach the code below."""
    value = match_node.child_by_field_name("value")
    if value is None or _rust_expr_key(source_bytes, value) != recv:
        return False
    body = match_node.child_by_field_name("body")
    if body is None:
        return False
    saw_arm = False
    for arm in body.named_children:
        if arm.type != "match_arm":
            continue
        saw_arm = True
        pattern = arm.child_by_field_name("pattern")
        if pattern is not None and _rust_pattern_is_value_arm(
            pattern, source_bytes
        ):
            continue
        arm_value = arm.child_by_field_name("value")
        if arm_value is None:
            return False
        if arm_value.type == "block":
            if not _rust_block_diverges(arm_value, source_bytes):
                return False
        elif arm_value.type == "if_expression":
            if not _rust_if_always_diverges(arm_value, source_bytes):
                return False
        elif arm_value.type in {
            "return_expression",
            "break_expression",
            "continue_expression",
        } or _rust_is_diverging_macro(arm_value, source_bytes):
            continue
        else:
            return False
    return saw_arm


def _rust_unconditionally_evaluated_children(node) -> list:
    """Named children of ``node`` that evaluate unconditionally when the
    node runs — used to decide whether a ``?`` inside a statement is a
    guaranteed early return.

    Conditional children are excluded: ``if``/``while``/``for`` bodies and
    ``else`` arms, ``match`` arms, the right operand of ``&&``/``||``,
    ``let`` else-blocks, ``loop`` bodies (statements after a ``break`` never
    run), and function/closure bodies (their ``?`` returns from the nested
    function)."""
    if node.type in _RUST_FN_BOUNDARY_TYPES:
        return []
    if node.type in {"if_expression", "while_expression"}:
        condition = node.child_by_field_name("condition")
        return [condition] if condition is not None else []
    if node.type == "for_expression":
        value = node.child_by_field_name("value")
        return [value] if value is not None else []
    if node.type == "loop_expression":
        return []
    if node.type == "match_expression":
        value = node.child_by_field_name("value")
        return [value] if value is not None else []
    if node.type == "let_declaration":
        value = node.child_by_field_name("value")
        return [value] if value is not None else []
    if node.type == "binary_expression":
        operator = node.child_by_field_name("operator")
        if operator is not None and operator.type in {"&&", "||"}:
            left = node.child_by_field_name("left")
            return [left] if left is not None else []
    return node.named_children


def _rust_subtree_has_try(node, recv: str, source_bytes: bytes) -> bool:
    """True when ``recv?`` (the try operator) runs unconditionally inside
    ``node`` — it early-returns on the empty variant, guarding the code
    below it."""
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == "try_expression":
            operand = next(iter(current.named_children), None)
            if (
                operand is not None
                and _rust_expr_key(source_bytes, operand) == recv
            ):
                return True
        stack.extend(_rust_unconditionally_evaluated_children(current))
    return False


def _rust_statement_guards(
    node, recv: str, source_bytes: bytes, targets: set | None = None, aliases: set | None = None
) -> bool:
    """True when a preceding sibling statement guarantees ``recv`` is
    Ok/Some for everything after it in the same block. ``targets``/``aliases``
    carry the caller's receiver+``&mut``-alias set for conditional-repair
    recognition; when omitted the rule sees direct writes to ``recv`` only."""
    if targets is None:
        targets = {recv}
    if aliases is None:
        aliases = targets - {recv}
    inner = _rust_statement_inner(node)
    if inner is None:
        return False
    if inner.type == "let_declaration":
        # ``let Some(v) = recv else { diverge };`` — the else must diverge
        # by definition, so the fallthrough bound the value variant.
        if inner.child_by_field_name("alternative") is not None:
            pattern = inner.child_by_field_name("pattern")
            value = inner.child_by_field_name("value")
            if (
                value is not None
                and _rust_expr_key(source_bytes, value) == recv
                and pattern is not None
                and _rust_pattern_is_value_arm(pattern, source_bytes)
            ):
                return True
    # ``let x = recv?;``, ``recv?;``, ``foo(recv?);`` — a ``?`` anywhere in
    # the statement early-returns on the empty variant.
    if _rust_subtree_has_try(inner, recv, source_bytes):
        return True
    if inner.type == "if_expression" and (
        _rust_if_guards_fallthrough(inner, recv, source_bytes)
        or _rust_if_conditional_repair(inner, recv, targets, aliases, source_bytes)
    ):
        return True
    if inner.type == "match_expression" and _rust_match_guards_fallthrough(
        inner, recv, source_bytes
    ):
        return True
    if inner.type == "macro_invocation":
        macro = inner.child_by_field_name("macro")
        if (
            macro is not None
            and _node_text(source_bytes, macro) in _RUST_ASSERT_MACROS
        ):
            token_tree = next(
                (c for c in inner.children if c.type == "token_tree"), None
            )
            if token_tree is not None and re.search(
                # Asserted-true must prove the value variant: the direct
                # positive checks plus the ``ok()``/``err()`` projections.
                rf"{re.escape(recv)}\.(?:{'|'.join(_RUST_POSITIVE_CHECKS)})\("
                rf"|{re.escape(recv)}\.ok\(\)\.(?:is_some|is_some_and)\("
                rf"|{re.escape(recv)}\.err\(\)\.is_none\(",
                re.sub(r"\s+", "", _node_text(source_bytes, token_tree)),
            ):
                return True
    return False


def _rust_pattern_binds(pattern, recv: str, source_bytes: bytes) -> bool:
    """True when a ``let`` pattern binds (or re-binds/shadows) ``recv`` —
    plain identifiers and shorthand struct fields (`S { res }`) alike."""
    if pattern.type in {"identifier", "shorthand_field_identifier"}:
        return _node_text(source_bytes, pattern) == recv
    return any(
        _rust_pattern_binds(child, recv, source_bytes)
        for child in pattern.named_children
    )


_RUST_VALUE_CTOR_RE = re.compile(r"^(?:Some|Ok)\s*\(")
# ``Option`` methods that write a value variant — the receiver is provably
# Some afterwards. ``take`` (or any ``&mut recv`` borrow) writes an unknown
# variant and counts as a mutation, never a repair.
_RUST_REPAIR_METHODS = frozenset(
    {"insert", "get_or_insert", "get_or_insert_with", "replace"}
)
_RUST_WRITE_METHODS = _RUST_REPAIR_METHODS | {"take"}


def _rust_write_target_key(source_bytes: bytes, node) -> str:
    """Receiver key written through an assignment LHS — dereference
    (``*p``) and parenthesized wrappers peel to the underlying name."""
    while node.type in {"unary_expression", "parenthesized_expression"}:
        inner = next(iter(node.named_children), None)
        if inner is None:
            break
        node = inner
    return _rust_expr_key(source_bytes, node)


def _rust_alias_target_key(value, alias_of: dict, recv: str, source_bytes: bytes):
    """The receiver key a ``&mut``-binding ultimately writes through:
    ``&mut res`` -> ``res``, ``&mut p``/``let q = p`` resolve through the
    alias map, anything else returns ``None``."""
    if value.type == "reference_expression":
        key = _rust_expr_key(source_bytes, value)
        if not key.startswith("&mut"):
            return None
        inner = key[len("&mut"):]
        return alias_of.get(inner, inner if inner == recv else None)
    if value.type == "identifier":
        return alias_of.get(_node_text(source_bytes, value))
    return None


def _rust_collect_mut_aliases(scope, recv: str, source_bytes: bytes) -> set:
    """Names bound to ``&mut recv`` (directly or copied from another
    alias) inside ``scope`` — collected over the whole enclosing function
    so aliases apply wherever they are in scope. Copies resolve through a
    fixpoint pass; a name re-bound to a different target is dropped
    (conservative — writes through it may not reach ``recv``)."""
    binders = []

    def walk(node):
        if node.type == "function_item" and node.id != scope.id:
            return
        if node.type in {"let_declaration", "assignment_expression"}:
            binders.append(node)
        for child in node.named_children:
            walk(child)

    walk(scope)
    alias_of: dict[str, str] = {}
    conflicts: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in binders:
            bound = None
            value = None
            if node.type == "let_declaration":
                pattern = node.child_by_field_name("pattern")
                value = node.child_by_field_name("value")
                if pattern is not None and pattern.type == "identifier":
                    bound = _node_text(source_bytes, pattern)
            else:
                left = node.child_by_field_name("left")
                value = node.child_by_field_name("right")
                if left is not None and left.type == "identifier":
                    bound = _node_text(source_bytes, left)
            if bound is None or bound in conflicts or value is None:
                continue
            target = _rust_alias_target_key(
                value, alias_of, recv, source_bytes
            )
            if bound in alias_of and alias_of[bound] != target:
                # The name is (re)bound to something that is not an alias
                # of ``recv`` — stop trusting it as one.
                del alias_of[bound]
                conflicts.add(bound)
                changed = True
            elif bound not in alias_of and target is not None:
                alias_of[bound] = target
                changed = True
    return set(alias_of)


def _rust_assignment_repairs(inner, targets: set, source_bytes: bytes) -> bool:
    """True when an ``assignment_expression`` writes a value variant
    (``res = Some(..)``/``Ok(..)``) onto a tracked target, including writes
    through ``&mut`` aliases (``*p = Some(..)``)."""
    if inner.type != "assignment_expression":
        return False
    left = inner.child_by_field_name("left")
    right = inner.child_by_field_name("right")
    return (
        left is not None
        and right is not None
        and (
            _rust_expr_key(source_bytes, left) in targets
            or _rust_write_target_key(source_bytes, left) in targets
        )
        and bool(_RUST_VALUE_CTOR_RE.match(_node_text(source_bytes, right)))
    )


def _rust_statement_repairs_existing(node, targets: set, source_bytes: bytes) -> bool:
    """Like ``_rust_statement_repairs`` but only counts writes to the
    existing binding — ``res = Some(..)`` or insert-style method calls.
    ``let res = Some(..)`` is excluded on purpose: inside a conditional
    branch it merely shadows ``recv`` for the block and does not repair the
    outer binding."""
    inner = _rust_statement_inner(node)
    if inner is None:
        return False
    if _rust_assignment_repairs(inner, targets, source_bytes):
        return True
    stack = [inner]
    while stack:
        current = stack.pop()
        if current.type == "call_expression":
            parts = _rust_call_parts(current, source_bytes)
            if (
                parts is not None
                and parts[0] in targets
                and parts[1] in _RUST_REPAIR_METHODS
            ):
                return True
        stack.extend(_rust_unconditionally_evaluated_children(current))
    return False


def _rust_block_repair_effect(
    block, recv: str, targets: set, aliases: set, source_bytes: bytes
) -> str:
    """How ``block``'s statements leave ``recv`` in order: ``"repaired"``
    when the latest write restores a value variant, ``"invalidated"`` when
    it may leave a non-value variant, ``"untouched"`` when nothing writes
    ``recv``. Writes inside nested control flow count as invalidating — a
    repair that only runs under an inner ``if`` is not unconditional."""
    effect = "untouched"
    for stmt in block.named_children:
        if _rust_statement_repairs_existing(stmt, targets, source_bytes):
            effect = "repaired"
        elif _rust_subtree_assigns(stmt, recv, targets, aliases, source_bytes):
            effect = "invalidated"
    return effect


def _rust_if_conditional_repair(
    if_node, recv: str, targets: set, aliases: set, source_bytes: bytes
) -> bool:
    """True when ``if``'s empty-variant branch unconditionally repairs
    ``recv`` to a value variant while the value-variant branch leaves it
    alone — e.g. ``if res.is_none() { res = Some(0) }`` or
    ``if let Err(_) = res { res = Ok(0) }`` before ``res.unwrap()``.
    ``else if`` chains resolve through the nested ``if``; a nested ``if``
    that neither repairs nor writes ``recv`` is ``untouched`` on its
    branch's path."""
    condition = if_node.child_by_field_name("condition")
    consequence = if_node.child_by_field_name("consequence")
    if condition is None or consequence is None:
        return False
    polarity = _rust_condition_polarity(condition, recv, source_bytes)
    if polarity not in {"then", "else"}:
        return False
    if consequence.type == "block":
        con_effect = _rust_block_repair_effect(
            consequence, recv, targets, aliases, source_bytes
        )
    else:
        con_effect = "invalidated"
    alternative = if_node.child_by_field_name("alternative")
    if alternative is None:
        alt_effect = None
    else:
        body = _rust_statement_inner(
            next(iter(alternative.named_children), None)
        )
        if body is None:
            alt_effect = "untouched"
        elif body.type == "block":
            alt_effect = _rust_block_repair_effect(
                body, recv, targets, aliases, source_bytes
            )
        elif body.type == "if_expression":
            if _rust_if_conditional_repair(
                body, recv, targets, aliases, source_bytes
            ):
                alt_effect = "repaired"
            elif not _rust_subtree_assigns(
                body, recv, targets, aliases, source_bytes
            ):
                alt_effect = "untouched"
            else:
                alt_effect = "invalidated"
        else:
            alt_effect = "invalidated"
    if polarity == "else":
        # Consequence = empty path → must repair; alternative = value path
        # → must not invalidate (absent means the value variant survives).
        return con_effect == "repaired" and alt_effect != "invalidated"
    # Consequence = value path → must not invalidate; alternative = empty
    # path → must repair.
    return con_effect != "invalidated" and alt_effect == "repaired"


def _rust_statement_repairs(node, targets: set, recv: str, source_bytes: bytes) -> bool:
    """True when the statement unconditionally leaves a tracked target
    holding a value variant — ``res = Some(..)``/``Ok(..)``, writes through
    ``&mut`` aliases (``*p = Some(..)``, ``p.insert(..)``), a
    ``let res = Some(..)`` shadowing, or an ``Option`` insert-style method
    call anywhere in the statement's unconditionally-evaluated part (e.g.
    ``let v = res.get_or_insert(5)``). Conditional repairs
    (``if … { res = Ok(..) }``) are not read here; ``_rust_statement_guards``
    recognizes them via ``_rust_if_conditional_repair``."""
    inner = _rust_statement_inner(node)
    if inner is None:
        return False
    if _rust_assignment_repairs(inner, targets, source_bytes):
        return True
    if inner.type == "let_declaration":
        pattern = inner.child_by_field_name("pattern")
        value = inner.child_by_field_name("value")
        if (
            pattern is not None
            and value is not None
            and pattern.type in {"identifier", "mutable_specifier"}
            and _rust_pattern_binds(pattern, recv, source_bytes)
            and _RUST_VALUE_CTOR_RE.match(_node_text(source_bytes, value))
        ):
            return True
    stack = [inner]
    while stack:
        current = stack.pop()
        if current.type == "call_expression":
            parts = _rust_call_parts(current, source_bytes)
            if (
                parts is not None
                and parts[0] in targets
                and parts[1] in _RUST_REPAIR_METHODS
            ):
                return True
        stack.extend(_rust_unconditionally_evaluated_children(current))
    return False


def _rust_subtree_assigns(
    node, recv: str, targets: set, aliases: set, source_bytes: bytes
) -> bool:
    """True when the subtree may write the receiver: a plain/compound
    assignment (incl. ``*p`` derefs through ``&mut`` aliases), a ``let``
    re-binding of ``recv`` (shadowing), a mutating method call
    (``take``/insert-style), or a ``&mut`` borrow/alias handed to a callee.
    Nested ``fn`` items open a fresh scope and cannot assign the outer
    binding; closures and async blocks are scanned conservatively since
    they may run."""
    if node.type == "function_item":
        return False
    if node.type in {"assignment_expression", "compound_assignment_expr"}:
        left = node.child_by_field_name("left")
        if left is not None and (
            _rust_expr_key(source_bytes, left) in targets
            or _rust_write_target_key(source_bytes, left) in targets
        ):
            return True
    if node.type == "let_declaration":
        pattern = node.child_by_field_name("pattern")
        if pattern is not None and _rust_pattern_binds(
            pattern, recv, source_bytes
        ):
            return True
    if node.type == "call_expression":
        parts = _rust_call_parts(node, source_bytes)
        if (
            parts is not None
            and parts[0] in targets
            and parts[1] in _RUST_WRITE_METHODS
        ):
            return True
        # ``f(&mut res, …)`` or ``f(p)`` with ``p`` a ``&mut`` alias — any
        # callee receiving a mutable borrow may write the receiver.
        arguments = node.child_by_field_name("arguments")
        if arguments is not None:
            for arg in arguments.named_children:
                if arg.type == "reference_expression" and _rust_expr_key(
                    source_bytes, arg
                ).startswith("&mut") and _rust_iterable_base_key(
                    source_bytes, arg
                ) in targets:
                    return True
                if arg.type == "identifier" and (
                    _node_text(source_bytes, arg) in aliases
                ):
                    return True
    return any(
        _rust_subtree_assigns(child, recv, targets, aliases, source_bytes)
        for child in node.named_children
    )


def _rust_match_arm_guarded(arm, recv: str, source_bytes: bytes) -> bool:
    """True when a ``match`` arm's pattern binds the value variant of
    ``recv`` — the arm body only runs when ``recv`` is Ok/Some."""
    match_block = arm.parent
    match_expr = match_block.parent if match_block is not None else None
    if match_expr is None or match_expr.type != "match_expression":
        return False
    scrutinee = match_expr.child_by_field_name("value")
    pattern = arm.child_by_field_name("pattern")
    return (
        scrutinee is not None
        and _rust_expr_key(source_bytes, scrutinee) == recv
        and pattern is not None
        and _rust_pattern_is_value_arm(pattern, source_bytes)
    )


def _rust_unwrap_is_guarded(call_node, recv: str, source_bytes: bytes) -> bool:
    """Scope-aware guard check: a guard counts only when it dominates the
    call — an enclosing ``if``/``while`` consequence, ``else`` of a negative
    check, ``match`` value arm, short-circuit ``&&``/``||`` right operand, or
    a preceding diverging guard (``let-else``, ``if ... { return }``,
    ``assert!``, ``recv?``, exhaustive ``match``) in an enclosing block —
    and no write to the receiver (direct or through a ``&mut`` alias) sits
    between the guard and the call."""
    child = call_node
    node = call_node.parent
    # ``let p = &mut res`` (or copies) anywhere in the enclosing function
    # makes writes through ``p`` writes to ``recv``.
    scope = call_node
    while scope.parent is not None and scope.type != "function_item":
        scope = scope.parent
    targets = {recv} | _rust_collect_mut_aliases(scope, recv, source_bytes)
    aliases = targets - {recv}
    while node is not None:
        if node.type == "binary_expression":
            # ``recv.is_ok() && recv.unwrap()`` — the right operand runs only
            # when the left held.
            operator = node.child_by_field_name("operator")
            right = node.child_by_field_name("right")
            if right is not None and right.id == child.id:
                op = operator.type if operator is not None else ""
                side = _rust_condition_polarity(
                    node.child_by_field_name("left"), recv, source_bytes
                )
                if (op == "&&" and side == "then") or (
                    op == "||" and side == "else"
                ):
                    return True
        elif node.type == "match_arm":
            if _rust_match_arm_guarded(node, recv, source_bytes):
                return True
        elif node.type == "block":
            guarded = False
            mutated = False
            for sibling in node.named_children:
                if sibling.id == child.id:
                    break
                if _rust_subtree_assigns(
                    sibling, recv, targets, aliases, source_bytes
                ):
                    if _rust_statement_repairs(
                        sibling, targets, recv, source_bytes
                    ) or _rust_statement_guards(
                        sibling, recv, source_bytes, targets, aliases
                    ):
                        # `res = Some(..)` or a conditional-repair `if`
                        # re-establishes the invariant.
                        guarded = True
                    else:
                        # A write to ``recv`` stales any earlier guard —
                        # only a guard after the latest write still applies.
                        guarded = False
                        mutated = True
                elif _rust_statement_guards(
                    sibling, recv, source_bytes, targets, aliases
                ):
                    guarded = True
            if guarded:
                return True
            if mutated:
                # Guards established by enclosing constructs (``if``/``while``
                # consequences, ``match`` arms, outer blocks) all predate the
                # write, so none of them can still prove ``recv`` is safe.
                return False
            owner = node.parent
            if owner is None:
                return False
            if owner.type in _RUST_FN_BOUNDARY_TYPES:
                # Guards never cross a function boundary: a nested ``fn`` is
                # hoisted and a closure may outlive the guarded scope.
                return False
            if owner.type == "else_clause":
                if_expr = owner.parent
                if (
                    if_expr is not None
                    and if_expr.type == "if_expression"
                    and _rust_condition_polarity(
                        if_expr.child_by_field_name("condition"),
                        recv,
                        source_bytes,
                    )
                    == "else"
                ):
                    return True
            elif owner.type == "if_expression":
                consequence = owner.child_by_field_name("consequence")
                if (
                    consequence is not None
                    and consequence.id == node.id
                    and _rust_condition_polarity(
                        owner.child_by_field_name("condition"),
                        recv,
                        source_bytes,
                    )
                    == "then"
                ):
                    return True
            elif owner.type == "while_expression":
                if _rust_condition_polarity(
                    owner.child_by_field_name("condition"), recv, source_bytes
                ) == "then":
                    return True
            elif owner.type == "for_expression":
                # `for v in res` (or `&res`/`res.iter()`) over an
                # Option/Result runs the body only for the value variant.
                iterable = owner.child_by_field_name("value")
                if (
                    iterable is not None
                    and _rust_iterable_base_key(source_bytes, iterable) == recv
                ):
                    return True
            # Any other owner (mod, impl, unsafe/async blocks, loops, ...)
            # is transparent — keep climbing.
        child = node
        node = node.parent
    return False


def _rust_enclosing_function_name(node, source_bytes: bytes) -> str:
    """Name of the nearest enclosing ``fn`` item for issue attribution."""
    current = node.parent
    while current is not None:
        if current.type == "function_item":
            name = current.child_by_field_name("name")
            if name is not None:
                return _node_text(source_bytes, name)
            break
        current = current.parent
    return "<top-level>"


def _rust_unwrap_expect_scoped_issues(ctx: PatternContext) -> list[ForeignSafetyIssue]:
    source_bytes = ctx.source_bytes
    issues: list[ForeignSafetyIssue] = []
    stack = [ctx.tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            parts = _rust_call_parts(node, source_bytes)
            if parts is not None and parts[1] in _RUST_UNWRAP_METHODS:
                recv, call = parts
                if not _rust_unwrap_is_guarded(node, recv, source_bytes):
                    name = _rust_enclosing_function_name(node, source_bytes)
                    issues.append(
                        ForeignSafetyIssue(
                            function_name=name,
                            message=(
                                f"Rust function `{name}` can panic via "
                                f"`{recv}.{call}()` without a contract that "
                                "the value is Ok/Some"
                            ),
                            line=node.start_point[0] + 1,
                        )
                    )
        elif node.type == "macro_invocation":
            # Macro bodies are opaque token trees — calls inside them
            # (``println!("{}", r.unwrap())``) are not expression nodes, so
            # scan the token text and judge dominance by the macro's own
            # position in the tree.
            token_text = _node_text(source_bytes, node)
            for match in _RUST_UNWRAP_RE.finditer(token_text):
                recv = re.sub(r"\s+", "", match.group("recv"))
                call = match.group("call")
                if _rust_unwrap_is_guarded(node, recv, source_bytes):
                    continue
                name = _rust_enclosing_function_name(node, source_bytes)
                issues.append(
                    ForeignSafetyIssue(
                        function_name=name,
                        message=(
                            f"Rust function `{name}` can panic via "
                            f"`{recv}.{call}()` without a contract that "
                            "the value is Ok/Some"
                        ),
                        line=(
                            node.start_point[0]
                            + 1
                            + token_text[: match.start()].count("\n")
                        ),
                    )
                )
        stack.extend(reversed(node.children))
    return issues


def _rust_unwrap_expect_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    if ctx.tree is not None and ctx.source_bytes is not None:
        return _rust_unwrap_expect_scoped_issues(ctx)
    return _rust_unwrap_expect_text_issues(source)


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

_GO_FOR_HEADER_RE = re.compile(r"\bfor\b")


def _go_defer_in_loop_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    blocks = _go_function_blocks(source)
    issues: list[ForeignSafetyIssue] = []
    non_code = _non_code_states(source, "go")
    used_offsets: set[int] = set()
    for name, body in blocks:
        offset = _body_offset((source,), body, used_offsets, non_code)
        masked = _strip_go_rust_literals_and_comments(
            _mask_nested_function_literals(body, "go")
        )
        deferred = None
        deferred_offset = -1
        for match in _GO_FOR_HEADER_RE.finditer(masked):
            # The first `{` after `for` may belong to a composite literal in
            # the header (`for _, x := range []int{1,2} {`) — skip balanced
            # `{...}` groups until the segment before the `{` is plain
            # header text.
            pos = match.end()
            while True:
                opening = masked.find("{", pos)
                if opening < 0:
                    break
                header = masked[pos:opening]
                if ";" in header and header.count(";") > 2:
                    break
                loop_body = _balanced_brace_body(masked, opening)
                close = opening + len(loop_body) + 1  # index of matching `}`
                defer_match = re.search(r"\bdefer\s+(.+)", loop_body)
                if defer_match:
                    deferred = defer_match.group(1).strip()
                    deferred_offset = opening + 1 + defer_match.start()
                    break
                if close >= len(masked):
                    break
                # A composite literal's `}` is followed directly (whitespace
                # only) by the loop's own `{`. Any other content means the
                # header already ended — the next `{` starts a different
                # statement and must not be scanned as the loop body.
                rest = masked[close + 1 :]
                next_brace = rest.find("{")
                if next_brace < 0 or rest[:next_brace].strip():
                    break
                pos = close + 1 + next_brace
            if deferred:
                break
        if deferred:
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"Go function `{name}` runs `defer {deferred}` inside a "
                        "loop — deferred calls accumulate until the function "
                        "returns"
                    ),
                    confidence="medium",
                    line=_issue_line(source, offset, deferred_offset),
                )
            )
    return issues


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------

_TS_ASYNC_NAME_RES = (
    re.compile(r"\basync\s+function\s+(?P<name>[A-Za-z_$][\w$]*)"),
    re.compile(r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*async\b"),
    re.compile(r"\basync\s+(?P<name>[A-Za-z_$][\w$]*)\s*\("),
)
_TS_AWAIT_PREFIX_RE = re.compile(
    r"(?:\bawait|\bvoid|\breturn|\byield|\bPromise\.(?:all|allSettled|race|any)\s*\([^()]*|[\[(=,])\s*$"
)
_TS_PROMISE_CHAIN_RE = re.compile(r"^\s*\.\s*(?:then|catch|finally)\s*\(")
# Expression-bodied arrows (`const h = x => send(x)`) return the call result,
# so a promise callee inside them is handed to the caller — not floating.
_TS_EXPR_ARROW_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*=>(?!\s*\{)"
)

_TS_CHAIN_METHODS = frozenset({"then", "catch", "finally"})
_TS_FUNCTION_TYPES = frozenset(
    {"function_declaration", "generator_function_declaration", "method_definition"}
)
_TS_VALUE_FUNCTION_TYPES = frozenset({"arrow_function", "function_expression"})
# Parent node types that consume the call's value — the promise is handed to
# an awaiter/return slot/callee and is therefore not floating.
_TS_HANDLED_PARENT_TYPES = frozenset(
    {
        "await_expression",
        "return_statement",
        "throw_statement",
        "yield_expression",
        "variable_declarator",
        "assignment_expression",
        "augmented_assignment_expression",
        "arguments",
        "new_expression",
        "lexical_declaration",
        "variable_declaration",
        "import_statement",
        # Class field initializers store the promise like an assignment.
        "public_field_definition",
        "field_definition",
    }
)
# Parent node types that just wrap the call — whether the promise is floating
# is decided by the context above them.
_TS_TRANSPARENT_PARENT_TYPES = frozenset(
    {
        "parenthesized_expression",
        "sequence_expression",
        "binary_expression",
        "ternary_expression",
        "non_null_expression",
        "as_expression",
        "satisfies_expression",
        "type_assertion",
        "subscript_expression",
        "array",
        "object",
        "pair",
        "spread_element",
        "template_string",
        "update_expression",
        "else_clause",
    }
)


def _ts_call_close(text: str, open_paren: int) -> int:
    """Index of the ``)`` matching the ``(`` at ``open_paren``, or -1."""
    depth = 0
    for i in range(open_paren, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _typescript_floating_promise_text_issues(source: str) -> list[ForeignSafetyIssue]:
    """Prefix-regex scan used when the tree-sitter grammar is unavailable."""
    # Collect async names from the comment/string-stripped source — an
    # `async function f` mention inside a comment must not mark `f` async.
    stripped = _strip_go_rust_literals_and_comments(source)
    async_names = {
        match.group("name")
        for pattern in _TS_ASYNC_NAME_RES
        for match in pattern.finditer(stripped)
    }
    if not async_names:
        return []
    expr_arrow_names = {
        match.group("name") for match in _TS_EXPR_ARROW_RE.finditer(stripped)
    }
    issues: list[ForeignSafetyIssue] = []
    non_code = _non_code_states(source, "typescript")
    used_offsets: set[int] = set()
    for name, body in _typescript_function_blocks(source):
        if name in expr_arrow_names:
            continue
        offset = _body_offset((source,), body, used_offsets, non_code)
        masked = _strip_go_rust_literals_and_comments(
            _mask_nested_function_literals(body, "typescript")
        )
        for callee in sorted(async_names):
            if callee == name:
                continue
            for match in re.finditer(rf"\b{re.escape(callee)}\s*\(", masked):
                prefix = masked[max(0, match.start() - 80) : match.start()]
                open_paren = masked.find("(", match.start())
                closing = _ts_call_close(masked, open_paren) if open_paren >= 0 else -1
                after = masked[closing + 1 : closing + 61] if closing >= 0 else ""
                if _TS_AWAIT_PREFIX_RE.search(prefix):
                    continue
                if _TS_PROMISE_CHAIN_RE.match(after):
                    continue
                issues.append(
                    ForeignSafetyIssue(
                        function_name=name,
                        message=(
                            f"TypeScript function `{name}` calls async "
                            f"`{callee}()` without awaiting it — a floating "
                            "promise can reject unobserved"
                        ),
                        confidence="medium",
                        line=_issue_line(source, offset, match.start()),
                    )
                )
                break
    return issues


def _ts_bound_name(fn_node, source_bytes: bytes) -> str | None:
    """The binding name of an arrow/function-expression, when bound."""
    parent = fn_node.parent
    if parent is None:
        return None
    if parent.type == "variable_declarator":
        name = parent.child_by_field_name("name")
        if name is not None and name.type == "identifier":
            return _node_text(source_bytes, name)
        return None
    if parent.type == "pair":
        key = parent.child_by_field_name("key")
        if key is None:
            return None
        return _node_text(source_bytes, key).strip("'\"")
    if parent.type == "assignment_expression":
        left = parent.child_by_field_name("left")
        if left is None:
            return None
        if left.type == "identifier":
            return _node_text(source_bytes, left)
        if left.type == "member_expression":
            prop = left.child_by_field_name("property")
            if prop is not None:
                return _node_text(source_bytes, prop)
        return None
    if parent.type in {"public_field_definition", "field_definition"}:
        name = parent.child_by_field_name("name") or parent.child_by_field_name(
            "property"
        )
        if name is not None:
            return _node_text(source_bytes, name)
    return None


def _ts_function_name(fn_node, source_bytes: bytes) -> str | None:
    if fn_node.type in _TS_FUNCTION_TYPES:
        name = fn_node.child_by_field_name("name")
        return _node_text(source_bytes, name) if name is not None else None
    return _ts_bound_name(fn_node, source_bytes)


def _ts_collect_async_names(root, source_bytes: bytes) -> set[str]:
    """Names of ``async`` functions/methods/arrows declared in the file,
    plus same-file aliases: ``const s = send``/``const s = api.send``/
    ``const s = api['send']`` and renamed destructuring
    ``const { send: s } = api`` all re-export the async callee."""
    names: set[str] = set()
    declarators = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in _TS_FUNCTION_TYPES | _TS_VALUE_FUNCTION_TYPES:
            if any(child.type == "async" for child in node.children):
                name = _ts_function_name(node, source_bytes)
                if name:
                    names.add(name)
        if node.type in {"variable_declarator", "assignment_expression"}:
            declarators.append(node)
        stack.extend(node.children)

    def value_alias(value) -> str | None:
        """The name an expression refers to — identifier, member property,
        or string subscript."""
        if value.type == "identifier":
            return _node_text(source_bytes, value)
        if value.type == "member_expression":
            prop = value.child_by_field_name("property")
            if prop is not None:
                return _node_text(source_bytes, prop)
        if value.type == "subscript_expression":
            index = value.child_by_field_name("index")
            if index is not None and index.type == "string":
                return _node_text(source_bytes, index).strip("'\"")
        return None

    # Fixpoint so chained aliases (`const s = send; const t = s`) resolve.
    changed = True
    while changed:
        changed = False
        for decl in declarators:
            if decl.type == "variable_declarator":
                lhs = decl.child_by_field_name("name")
                rhs = decl.child_by_field_name("value")
            else:
                lhs = decl.child_by_field_name("left")
                rhs = decl.child_by_field_name("right")
            if lhs is None or rhs is None:
                continue
            if lhs.type == "identifier":
                if value_alias(rhs) in names:
                    bound = _node_text(source_bytes, lhs)
                    if bound not in names:
                        names.add(bound)
                        changed = True
            elif lhs.type == "object_pattern":
                for part in lhs.named_children:
                    if part.type not in {"pair", "pair_pattern"}:
                        continue
                    key = part.child_by_field_name("key")
                    val = part.child_by_field_name("value")
                    if (
                        key is not None
                        and val is not None
                        and val.type == "identifier"
                        and _node_text(source_bytes, key) in names
                    ):
                        bound = _node_text(source_bytes, val)
                        if bound not in names:
                            names.add(bound)
                            changed = True
    return names


def _ts_call_callee_name(call_node, source_bytes: bytes) -> str | None:
    """The called function's name — ``send(...)`` or ``obj.send(...)``."""
    function = call_node.child_by_field_name("function")
    if function is None:
        return None
    if function.type == "identifier":
        return _node_text(source_bytes, function)
    if function.type == "member_expression":
        prop = function.child_by_field_name("property")
        if prop is not None:
            return _node_text(source_bytes, prop)
    if function.type == "subscript_expression":
        index = function.child_by_field_name("index")
        if index is not None and index.type == "string":
            return _node_text(source_bytes, index).strip("'\"")
    return None


def _ts_call_is_handled(call_node, source_bytes: bytes) -> bool:
    """True when the call's result reaches a consumer: ``await``/``return``/
    ``throw``/``yield``, an assignment or declarator, a call/new argument, a
    ``.then/.catch/.finally`` chain, an expression-bodied arrow, or any
    non-expression statement (``if`` conditions, ``for`` headers, exports).
    ``False`` when it ends as an ``expression_statement`` — the floating
    case."""
    node = call_node
    while True:
        parent = node.parent
        if parent is None:
            return False
        ptype = parent.type
        if ptype in {"expression_statement", "jsx_expression", "jsx_attribute"}:
            # A promise passed as a JSX attribute/child value is dropped —
            # the DOM consumer never awaits it.
            return False
        if ptype in _TS_HANDLED_PARENT_TYPES:
            return True
        if ptype in _TS_TRANSPARENT_PARENT_TYPES:
            node = parent
            continue
        if ptype == "unary_expression":
            # ``void x`` discards deliberately; other unary operators
            # (``!x``, ``typeof x``) keep the dropped-result semantics of
            # their own parent context.
            operator = parent.child_by_field_name("operator")
            if (
                operator is not None
                and _node_text(source_bytes, operator) == "void"
            ):
                return True
            node = parent
            continue
        if ptype == "member_expression":
            obj = parent.child_by_field_name("object")
            if obj is not None and obj.id == node.id:
                prop = parent.child_by_field_name("property")
                if (
                    prop is not None
                    and _node_text(source_bytes, prop) in _TS_CHAIN_METHODS
                ):
                    return True
            node = parent
            continue
        if ptype == "call_expression":
            func = parent.child_by_field_name("function")
            if func is not None and func.id == node.id:
                # The result is itself invoked (`send(1)()`); classify by the
                # outer call's context.
                node = parent
                continue
            # The call sits in the arguments — the promise is handed to the
            # callee (covers Promise.all([...]) and friends).
            return True
        if ptype in {"arrow_function", "function_expression"}:
            # An expression-bodied function returns the call's value to its
            # own caller — not floating.
            return True
        if ptype == "program" or ptype.endswith("_statement"):
            # Reaching a statement means the value is consumed by control
            # flow (condition, initializer, export, ...).
            return True
        if ptype.endswith("_declaration"):
            return True
        node = parent


def _ts_enclosing_function_name(node, source_bytes: bytes) -> str | None:
    """Name of the nearest enclosing function for issue attribution.

    Anonymous arrows/functions fall through to the next enclosing named
    function so the advisory names a function the user can find.
    """
    current = node.parent
    while current is not None:
        if current.type in _TS_FUNCTION_TYPES:
            return _ts_function_name(current, source_bytes)
        if current.type in _TS_VALUE_FUNCTION_TYPES:
            bound = _ts_bound_name(current, source_bytes)
            if bound is not None:
                return bound
        current = current.parent
    return None


def _typescript_floating_promise_scoped_issues(
    ctx: PatternContext,
) -> list[ForeignSafetyIssue]:
    source_bytes = ctx.source_bytes
    root = ctx.tree.root_node
    async_names = _ts_collect_async_names(root, source_bytes)
    if not async_names:
        return []
    issues: list[ForeignSafetyIssue] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            callee = _ts_call_callee_name(node, source_bytes)
            if callee in async_names and not _ts_call_is_handled(
                node, source_bytes
            ):
                name = _ts_enclosing_function_name(node, source_bytes)
                if name is None or name == callee:
                    continue
                issues.append(
                    ForeignSafetyIssue(
                        function_name=name,
                        message=(
                            f"TypeScript function `{name}` calls async "
                            f"`{callee}()` without awaiting it — a floating "
                            "promise can reject unobserved"
                        ),
                        line=node.start_point[0] + 1,
                    )
                )
        stack.extend(reversed(node.children))
    return issues


def _typescript_floating_promise_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    if ctx.tree is not None and ctx.source_bytes is not None:
        return _typescript_floating_promise_scoped_issues(ctx)
    return _typescript_floating_promise_text_issues(source)


# ---------------------------------------------------------------------------
# Solidity
# ---------------------------------------------------------------------------

_SOLIDITY_LOW_LEVEL_CALL_RE = re.compile(
    r"(?<![\w.])(?P<target>(?:[A-Za-z_]\w*\([^()]*\)|[A-Za-z_]\w*)(?:\.\w+)*)"
    r"\s*\.\s*(?P<call>staticcall|delegatecall|call|send)\s*"
    r"(?:\{[^}]*\})?\s*\("
)
_SOLIDITY_STATEMENT_GUARD_RE = re.compile(
    r"=|require|assert|revert|return|\bif\b"
)


def _solidity_pattern_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    if _is_solidity_mock_source(source):
        return []
    issues: list[ForeignSafetyIssue] = []
    used_offsets: set[int] = set()
    non_code = _non_code_states(source, "solidity")
    for name, _attrs, raw_body in _solidity_function_blocks_with_attrs(source):
        offset = _body_offset((source,), raw_body, used_offsets, non_code)
        body = _strip_go_rust_literals_and_comments(raw_body)
        # ``blockhash``/``block.*`` sources are miner-influenced or public —
        # a modulo or keccak256 draw over them is weak randomness. The
        # ``block.*`` reference must feed the draw itself (inside the
        # keccak256 argument list or under a modulo), not merely coexist
        # in the body.
        weak_rng = bool(re.search(r"\bblockhash\s*\(", body))
        block_ref = re.search(
            r"\bblock\.(?:timestamp|number|prevrandao|difficulty|coinbase)\b",
            body,
        )
        if not weak_rng and block_ref is not None:
            for kmatch in re.finditer(r"\bkeccak256\s*\(", body):
                args = _paren_args(body, kmatch.end() - 1)
                if re.search(r"\bblock\.", args):
                    weak_rng = True
                    break
            if not weak_rng:
                # ``%``-modulo must draw from ``block.*`` in the same
                # statement — an unrelated modulo elsewhere in the body is
                # not a weak-randomness draw.
                weak_rng = bool(
                    re.search(
                        r"(?:%[^%;\n]*\bblock\.|\bblock\.[A-Za-z]+\s*%)",
                        body,
                    )
                )
        if weak_rng:
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"Solidity function `{name}` derives randomness from "
                        "`block.*`/`blockhash` — these values are public and "
                        "partly miner-influenced; use a VRF oracle for "
                        "unpredictable draws"
                    ),
                    confidence="medium",
                )
            )
        tx_origin = re.search(r"\btx\.origin\b", body)
        if tx_origin:
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"Solidity function `{name}` uses `tx.origin` — it "
                        "authenticates the originating account, not the "
                        "immediate caller, and is phishable; prefer "
                        "`msg.sender`"
                    ),
                    confidence="medium",
                    line=_issue_line(source, offset, tx_origin.start()),
                )
            )
        selfdestruct = re.search(r"\bselfdestruct\s*\(", body)
        if selfdestruct:
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"Solidity function `{name}` invokes `selfdestruct` — "
                        "it destroys contract storage and force-forwards "
                        "funds; confirm the authorization guard and removal "
                        "plan"
                    ),
                    confidence="medium",
                    line=_issue_line(source, offset, selfdestruct.start()),
                )
            )
        for match in _SOLIDITY_LOW_LEVEL_CALL_RE.finditer(body):
            statement_start = body.rfind(";", 0, match.start()) + 1
            statement_start = max(
                statement_start,
                body.rfind("{", 0, match.start()) + 1,
                body.rfind("}", 0, match.start()) + 1,
            )
            statement = body[statement_start : match.start()]
            if _SOLIDITY_STATEMENT_GUARD_RE.search(statement):
                continue
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"Solidity function `{name}` makes an unchecked "
                        f"`{match.group('call')}` low-level call — the "
                        "returned success flag is ignored"
                    ),
                    confidence="medium",
                    line=_issue_line(source, offset, match.start()),
                )
            )
    # Zero-address guard: an externally callable function that stores an
    # ``address`` parameter into state without any ``address(0)`` check can
    # brick the contract (burn address ownership/fee sinks).
    for name, raw_body, params_text, attrs in _solidity_function_scopes(source):
        if not re.search(r"\b(?:public|external)\b", attrs):
            continue
        body = _strip_go_rust_literals_and_comments(raw_body)
        address_params = re.findall(
            r"\baddress\s+(?:payable\s+)?(?P<name>[A-Za-z_]\w*)\b", params_text
        )
        for param in address_params:
            # Per-param guard: a check must reject ``param == address(0)``
            # and dominate the store — ``require(param != address(0))`` /
            # ``assert`` / ``if (param == address(0)) { revert }`` before the
            # store, or ``if (param != address(0)) { …store… }`` enclosing
            # it. An unrelated check on another parameter, or one placed
            # after/inside a conditional that doesn't cover the store,
            # does not suppress the advisory.
            param_guard = re.compile(
                rf"\b{re.escape(param)}\b[^;{{}}]*\baddress\s*\(\s*0\s*\)"
                rf"|\baddress\s*\(\s*0\s*\)[^;{{}}]*\b{re.escape(param)}\b"
            )
            guard_checks = list(param_guard.finditer(body))
            for store in re.finditer(
                rf"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*=\s*{re.escape(param)}\s*;",
                body,
            ):
                # ``address owner = newOwner;`` declares a local rather than
                # storing state — a Solidity type keyword (including
                # ``address payable`` and data-location keywords) ends the
                # statement's prefix.
                before = body[max(0, store.start() - 60) : store.start()]
                stmt_prefix = re.split(r"[;{}()]", before)[-1]
                if re.search(
                    r"\b(?:u?int\d*|address|payable|bool|bytes\d*|string|var"
                    r"|mapping|memory|storage|calldata)\s*$",
                    stmt_prefix,
                ):
                    continue
                def _protects(
                    check: re.Match[str],
                    _body: str = body,
                    _store: re.Match[str] = store,
                ) -> bool:
                    mech = _guard_mechanism(_body, check, _store.start())
                    if mech is None:
                        # Solidity ``revert`` is not in the generic divergence
                        # set — ``if (param == address(0)) { revert … }``
                        # before the store rejects the zero case.
                        if "==" not in check.group(0):
                            return False
                        open_paren = _body.rfind("(", 0, check.start())
                        if (
                            open_paren == -1
                            or re.search(r"\bif\s*$", _body[:open_paren])
                            is None
                        ):
                            return False
                        close_paren = (
                            open_paren + 1 + len(_paren_args(_body, open_paren))
                        )
                        after = _body[close_paren + 1 :]
                        brace_rel = after.find("{")
                        if brace_rel == -1 or not re.fullmatch(
                            r"\s*", after[:brace_rel]
                        ):
                            return False
                        blk = _balanced_brace_body(
                            _body, close_paren + 1 + brace_rel
                        )
                        blk_end = close_paren + 2 + brace_rel + len(blk)
                        return "revert" in blk and _store.start() >= blk_end
                    if check.end() > _store.start():
                        return False
                    # ``param != address(0)`` must hold; ``param ==
                    # address(0)`` must be the diverging branch's condition.
                    nonzero_when_holds = "!=" in check.group(0)
                    nonzero_when_negated = "==" in check.group(0)
                    if nonzero_when_holds and mech in _GUARD_HOLDS_MECHANISMS:
                        return True
                    return (
                        nonzero_when_negated
                        and mech in _GUARD_NEGATED_MECHANISMS
                    )

                if any(_protects(check) for check in guard_checks):
                    continue
                issues.append(
                    ForeignSafetyIssue(
                        function_name=name,
                        message=(
                            f"Solidity function `{name}` stores `address` "
                            f"parameter `{param}` without a zero-address "
                            "`require(param != address(0))` check"
                        ),
                        confidence="medium",
                    )
                )
                break
    return issues


# ---------------------------------------------------------------------------
# Rust — escape hatches advisories
# ---------------------------------------------------------------------------


def _rust_escape_hatch_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    for name, raw_body, _params in _rust_function_scopes(source):
        body = _mask_rust_nested_fns(
            _strip_go_rust_literals_and_comments(raw_body)
        )
        flags: list[str] = []
        if re.search(r"\bunsafe\s*\{", body):
            flags.append(
                "an `unsafe` block — borrow/type guarantees are suspended; "
                "the enclosing safety invariant needs a manual argument"
            )
        if re.search(r"\bmem::forget\s*\(", body):
            flags.append(
                "`mem::forget` — the value's Drop obligations leak; confirm "
                "no resource is abandoned"
            )
        if re.search(r"\bmem::transmute|transmute\s*<", body):
            flags.append(
                "`mem::transmute` — bypasses the type system entirely"
            )
        for flag in flags:
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=f"Rust function `{name}` contains {flag}",
                    confidence="medium",
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Python — dangerous calls + mutation during iteration
# ---------------------------------------------------------------------------

_PY_UNSAFE_NAME_CALLS = frozenset({"eval", "exec"})
_PY_UNSAFE_METHODS = {
    ("pickle", "load"): "`pickle.load` deserializes arbitrary objects — "
    "only load trusted payloads",
    ("pickle", "loads"): "`pickle.loads` deserializes arbitrary objects — "
    "only load trusted payloads",
    ("os", "system"): "`os.system` runs a shell string — injection risk; "
    "prefer subprocess with an argument list",
    ("os", "popen"): "`os.popen` runs a shell string — injection risk; "
    "prefer subprocess with an argument list",
    ("marshal", "load"): "`marshal.load` deserializes code objects — "
    "only load trusted payloads",
    ("marshal", "loads"): "`marshal.loads` deserializes code objects — "
    "only load trusted payloads",
}
_PY_SUBPROCESS_CALLS = frozenset(
    {"run", "call", "Popen", "check_output", "check_call", "getoutput"}
)
_PY_ITER_MUTATING_METHODS = frozenset(
    {"append", "extend", "insert", "remove", "pop", "clear", "discard", "update"}
)


def _python_dangerous_call_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    def describe(node: ast.Call) -> str | None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in _PY_UNSAFE_NAME_CALLS:
            return (
                f"`{func.id}` evaluates caller-supplied text as code — "
                "prefer a parser or an allowlisted dispatch"
            )
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            base, attr = func.value.id, func.attr
            if (base, attr) in _PY_UNSAFE_METHODS:
                return _PY_UNSAFE_METHODS[(base, attr)]
            if base == "subprocess" and attr in _PY_SUBPROCESS_CALLS:
                shell = any(
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in node.keywords
                )
                if shell or attr == "getoutput":
                    return (
                        f"`subprocess.{attr}` with `shell=True` interpolates "
                        "through a shell — injection risk; pass an argument "
                        "list with `shell=False`"
                    )
            if (
                base == "yaml"
                and attr == "load"
                and not any(kw.arg == "Loader" for kw in node.keywords)
            ):
                return (
                    "`yaml.load` without a `Loader=` uses the unsafe "
                    "default and deserializes arbitrary objects — use "
                    "`yaml.safe_load`"
                )
        return None

    issues: list[ForeignSafetyIssue] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in _python_own_nodes(fn):
            if isinstance(node, ast.Call):
                description = describe(node)
                if description is not None:
                    issues.append(
                        ForeignSafetyIssue(
                            function_name=fn.name,
                            message=(
                                f"Python function `{fn.name}` calls "
                                f"{description}"
                            ),
                            confidence="medium",
                        )
                    )
    return issues


def _python_own_nodes(node: ast.AST):
    """Yield ``node`` and its subtree without descending into nested
    ``def``/``lambda`` bodies — nested definitions get their own top-level
    visit via the outer ``ast.walk`` and must not be attributed to the
    enclosing scope."""
    yield node
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        yield current
        if isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        ):
            continue
        stack.extend(ast.iter_child_nodes(current))


def _python_mutation_during_iteration_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    """Mutating the iterated collection inside a ``for`` — skips elements
    silently (lists) or raises ``RuntimeError`` (dicts/sets)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    def iterated_name(loop) -> str | None:
        it = loop.iter
        if isinstance(it, ast.Name):
            return it.id
        # ``for k in d.items()`` / ``d.keys()`` / ``d.values()``
        if (
            isinstance(it, ast.Call)
            and isinstance(it.func, ast.Attribute)
            and it.func.attr in {"items", "keys", "values"}
            and isinstance(it.func.value, ast.Name)
        ):
            return it.func.value.id
        return None

    def key_vars(loop) -> set[str]:
        """Loop target names that hold iterated *keys* — ``for k in d``,
        ``for k in d.keys()``, and the first tuple element of
        ``for k, v in d.items()``. ``d.values()`` targets and the second
        ``items()`` element hold *values* — ``d[v]`` inserts a new key and
        breaks the iteration."""
        it = loop.iter
        target = loop.target
        target_names = (
            {e.id for e in ast.walk(target) if isinstance(e, ast.Name)}
            if isinstance(target, (ast.Name, ast.Tuple, ast.List))
            else set()
        )
        if isinstance(it, ast.Name):
            # ``for k in d`` — k iterates keys.
            return target_names
        if (
            isinstance(it, ast.Call)
            and isinstance(it.func, ast.Attribute)
            and isinstance(it.func.value, ast.Name)
        ):
            if it.func.attr == "keys":
                return target_names
            if it.func.attr == "values":
                return set()
            if it.func.attr == "items":
                if isinstance(target, (ast.Tuple, ast.List)) and target.elts:
                    return {
                        e.id
                        for e in ast.walk(target.elts[0])
                        if isinstance(e, ast.Name)
                    }
                return set()
        return set()

    def mutates(
        name: str, node: ast.AST, key_names: set[str], rebound: set[str]
    ) -> bool:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
            and node.func.attr in _PY_ITER_MUTATING_METHODS
        ):
            return True
        value_update_ok = not isinstance(node, ast.Delete)
        if isinstance(node, (ast.Delete, ast.Assign)):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            return False
        for target in targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == name
            ):
                # ``d[k] = v`` under ``for k in d`` rewrites the value in
                # place — the key set never changes, so iteration is safe.
                # ``del d[k]`` still resizes the container mid-iteration,
                # and ``d[v]`` where ``v`` is an iterated *value* inserts a
                # new key — also a mid-iteration resize. A rebound key var
                # (``for k in d: k = other; d[k] = v``) inserts the new key —
                # same resize.
                if (
                    value_update_ok
                    and isinstance(target.slice, ast.Name)
                    and target.slice.id in key_names
                    and target.slice.id not in rebound
                ):
                    continue
                return True
        return False

    issues: list[ForeignSafetyIssue] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for loop in _python_own_nodes(fn):
            if not isinstance(loop, (ast.For, ast.AsyncFor)):
                continue
            name = iterated_name(loop)
            if name is None:
                continue
            keys = key_vars(loop)

            def _bound_names(t: ast.AST) -> Iterable[str]:
                if isinstance(t, ast.Name):
                    yield t.id
                elif isinstance(t, (ast.Tuple, ast.List)):
                    for e in t.elts:
                        yield from _bound_names(e)
                elif isinstance(t, ast.Starred):
                    yield from _bound_names(t.value)

            rebound = {
                name_
                for stmt in loop.body
                for node in _python_own_nodes(stmt)
                if isinstance(
                    node,
                    (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr),
                )
                for t in (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                )
                for name_ in _bound_names(t)
            }
            rebound &= keys
            if any(
                mutates(name, node, keys, rebound)
                for stmt in loop.body
                if not isinstance(
                    stmt, (ast.FunctionDef, ast.AsyncFunctionDef)
                )
                for node in _python_own_nodes(stmt)
            ):
                issues.append(
                    ForeignSafetyIssue(
                        function_name=fn.name,
                        message=(
                            f"Python function `{fn.name}` mutates `{name}` "
                            "inside a loop iterating it — list element removal "
                            "skips items; dict/set mutation raises RuntimeError"
                        ),
                        confidence="medium",
                    )
                )
                break
    return issues


# ---------------------------------------------------------------------------
# TypeScript — non-null assertions, JSON.parse, eval, innerHTML, mutation
# ---------------------------------------------------------------------------

_TS_NON_NULL_RE = re.compile(
    r"(?:(?P<name>[A-Za-z_]\w*)|(?P<call>[A-Za-z_]\w*\s*\([^()]*\))"
    r"|(?P<idx>[A-Za-z_]\w*\s*\[[^\]]*\]))!(?!=)"
)
_TS_FOR_OF_RE = re.compile(
    r"\bfor\s*\([^)]*\bof\s+(?P<arr>[A-Za-z_]\w*)[^)]*\)\s*\{"
)
_TS_ITER_MUTATE_RE = (
    r"\.(?:push|splice|pop|shift|unshift|fill|sort|reverse)\s*\(|\s*\[[^\]]*\]\s*="
)


def _typescript_safety_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    for name, raw_body in _typescript_function_blocks(source):
        body = _mask_nested_function_literals(
            _strip_ts_literals_and_comments(raw_body), "typescript"
        )
        asserted = {
            (m.group("name") or m.group("call") or m.group("idx"))
            for m in _TS_NON_NULL_RE.finditer(body)
        }
        if asserted:
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"TypeScript function `{name}` uses non-null "
                        f"assertion(s) `{'`/`'.join(sorted(asserted))}!` — "
                        "the compile-time claim is unchecked at runtime; "
                        "prefer an explicit guard"
                    ),
                    confidence="medium",
                )
            )
        json_parse = list(re.finditer(r"\bJSON\.parse\s*\(", body))
        for parse in json_parse:
            in_try = False
            for try_match in re.finditer(r"\btry\s*\{", body):
                if try_match.end() - 1 > parse.start():
                    break
                block = _balanced_brace_body(body, try_match.end() - 1)
                if parse.start() < try_match.end() + len(block):
                    # ``try { … } finally { … }`` without a ``catch`` still
                    # throws — only a ``catch`` clause suppresses the throw.
                    block_end = try_match.end() + len(block) + 1
                    if re.match(r"\s*catch\b", body[block_end:]):
                        in_try = True
                        break
            if not in_try:
                issues.append(
                    ForeignSafetyIssue(
                        function_name=name,
                        message=(
                            f"TypeScript function `{name}` calls `JSON.parse` "
                            "without a try/catch — malformed input throws"
                        ),
                        confidence="medium",
                    )
                )
                break
        if re.search(r"\beval\s*\(", body):
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"TypeScript function `{name}` calls `eval` — "
                        "attacker-influenceable text runs as code"
                    ),
                    confidence="medium",
                )
            )
        if re.search(r"\.innerHTML\s*=", body):
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"TypeScript function `{name}` assigns to "
                        "`innerHTML` — unsanitized markup enables DOM XSS; "
                        "prefer `textContent` or a sanitizer"
                    ),
                    confidence="medium",
                )
            )
        for match in _TS_FOR_OF_RE.finditer(body):
            loop_body = _balanced_brace_body(body, match.end() - 1)
            arr = match.group("arr")
            if re.search(rf"\b{re.escape(arr)}{_TS_ITER_MUTATE_RE}", loop_body):
                issues.append(
                    ForeignSafetyIssue(
                        function_name=name,
                        message=(
                            f"TypeScript function `{name}` mutates `{arr}` "
                            "inside a `for … of` loop over it — element "
                            "addition/removal shifts the iteration"
                        ),
                        confidence="medium",
                    )
                )
                break
    return issues


# ---------------------------------------------------------------------------
# Taint-lite — request-derived data reaching a sink without sanitization
# ---------------------------------------------------------------------------

_TAINT_SOURCE_RE = re.compile(
    r"\breq(?:uest)?\.(?:query|params|body|headers|cookies|get_json)\b"
    r"|\brequest\.(?:args|form|data|json|GET|POST|values|FILES)\b"
    r"|\binput\s*\(|\bsys\.argv\b|\bos\.environ\b"
    r"|\w+\.URL\.Query\b|\w*FormValue\s*\(|\bPostFormValue\s*\("
    r"|\bc\.(?:Query|Param|DefaultQuery)\s*\("
    r"|\blocation\.(?:search|hash)\b|\bdocument\.(?:URL|cookie)\b"
    r"|\blocalStorage\b|\bURLSearchParams\b"
)
# Sanitizers are channel-specific: HTML/URL escapers do NOT make a value
# safe for SQL, and numeric coercions do NOT make it safe for the DOM.
_TAINT_SQL_SAFE_RE = re.compile(
    r"\b(?:int|float|parseInt|parseFloat|Number|"
    r"strconv\.(?:Atoi|Itoa|ParseInt|ParseFloat|ParseUint))\s*\("
)
_TAINT_DOM_SAFE_RE = re.compile(
    r"\b(?:escape|bleach\.clean|html\.escape|sanitize|DOMPurify\.sanitize|"
    r"urlencode|encodeURIComponent|quote|"
    r"url\.QueryEscape|url\.PathEscape|template\.HTMLEscapeString)\s*\("
)
_TAINT_ASSIGN_RE = re.compile(
    r"(?m)^\s*(?:var\s+|let\s+|const\s+)?(?P<name>[A-Za-z_]\w*)\s*"
    r"(?::\s*[^=\n]+)?\s*:?=(?!=)\s*(?P<rhs>[^;\n]+)"
)
# SQL-ish sinks: only the FIRST argument is the query string — a parameter
# tuple after the top-level comma is the safe parameterized form.
_TAINT_QUERY_SINK_RE = re.compile(
    r"\b(?:execute|executemany|query|raw|exec|QueryRow|QueryRowContext|"
    r"queryRow|Query|Exec|ExecContext|QueryContext)\s*\("
    r"|\bexec\.Command(?:Context)?\s*\("
)
_TAINT_CALL_RE = re.compile(r"\b(?P<name>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(")


def _taint_call_tainted(view: str, tainted_fns: frozenset[str]) -> bool:
    """``view`` calls a function flagged as returning tainted data
    (intra-file, one propagation level — no call-graph)."""
    return any(
        m.group("name").rsplit(".", 1)[-1] in tainted_fns
        for m in _TAINT_CALL_RE.finditer(view)
    )
# DOM/command sinks: taint anywhere in the statement is dangerous.
_TAINT_DOM_SINK_RE = re.compile(
    r"(?:\.innerHTML\s*=|\.outerHTML\s*=|\bdocument\.write\s*\()"
)


def _top_level_args(arg_text: str) -> list[str]:
    """Split a call's argument list on top-level ``,`` — depth-aware and
    string-aware, so commas inside ``f'SELECT a, b …'`` don't split."""
    args: list[str] = []
    depth = 0
    start = 0
    end = len(arg_text)
    index = 0
    quote: str | None = None
    while index < end:
        char = arg_text[index]
        if quote is not None:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                end = index
                break
            depth -= 1
        elif char == "," and depth == 0:
            args.append(arg_text[start:index])
            start = index + 1
        index += 1
    args.append(arg_text[start:end])
    return args


def _strip_python_comments(text: str) -> str:
    """Mask ``#`` comments (position-preserving) — a comment mentioning a
    request source must not mark the line's value as tainted."""
    out: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    while i < n:
        ch = text[i]
        if quote is not None:
            if text.startswith(quote, i):
                out.append(quote)
                i += len(quote)
                quote = None
                continue
            out.append(ch)
            if ch == "\\" and len(quote) == 1 and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            i += 1
            continue
        if text.startswith("'''", i) or text.startswith('"""', i):
            quote = text[i : i + 3]
            out.append(quote)
            i += 3
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            j = text.find("\n", i)
            if j == -1:
                out.append(" " * (n - i))
                break
            out.append(" " * (j - i))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _taint_interpolated(text: str) -> str:
    """String literals reduce to their ``{…}``/``${…}`` interpolations
    — a column named ``name`` in a SQL literal must not alias the
    tainted variable ``name``. Only f-strings and template literals
    interpolate; in a plain ``'SELECT {name}'`` the braces are
    literal text."""

    def expand(m: re.Match[str]) -> str:
        prefix, quote, inner = m.group(1), m.group(2), m.group(3)
        if "f" not in prefix.lower() and not quote.endswith("`"):
            return " "
        parts = re.findall(r"\{([^}]*)\}", inner)
        if quote.endswith("`"):
            # Only ``${…}`` interpolates in template literals — a
            # literal ``{name}`` (e.g. a JSON fragment) stays inert.
            parts = [
                part
                for part, pos in zip(
                    parts,
                    (m2.start() for m2 in re.finditer(r"\{[^}]*\}", inner)),
                )
                if inner[pos - 1 : pos] == "$"
            ]
        return " ".join(parts)

    return re.sub(
        r"([fFbBrRw]*)(\"\"\"|'''|['\"`])(.*?)\2",
        expand,
        text,
        flags=re.DOTALL,
    )


def _taint_blank_calls(text: str, fn_re: re.Pattern[str]) -> str:
    """Blank ``fn(...)`` call spans so their arguments don't count as
    tainted — ``int(x)`` coerces for SQL, ``escape(x)`` for the DOM."""
    out = text
    for call in re.finditer(fn_re, text):
        args = _paren_args(text, call.end() - 1)
        span_end = call.end() + len(args) + 1
        out = out[: call.start()] + " " * (span_end - call.start()) + out[span_end:]
    return out


def _taint_dirty_view(text: str, safe_re: re.Pattern[str]) -> str:
    return _taint_interpolated(_taint_blank_calls(text, safe_re))


def _taint_assign_rhs(body: str, assign: re.Match[str]) -> str:
    """Extend the single-line ``rhs`` capture through unclosed
    brackets / triple-quoted strings / template literals so multiline
    interpolated queries keep their variable references."""
    start, end = assign.start("rhs"), assign.end("rhs")

    def unclosed(text: str) -> bool:
        return (
            text.count("(") > text.count(")")
            or text.count("[") > text.count("]")
            or text.count("{") > text.count("}")
            or text.count('"""') % 2 == 1
            or text.count("'''") % 2 == 1
            or text.count("`") % 2 == 1
            # ``q = 'SELECT ' + \`` continues on the next line —
            # keep pulling lines while the last one ends in ``\``.
            or text.rstrip("\n").rstrip().endswith("\\")
        )

    while unclosed(body[start:end]):
        nl = body.find("\n", end)
        if nl == -1:
            break
        end = nl + 1
    rhs = body[start:end]
    return rhs.split(";", 1)[0]


def _taint_replay_assigns(
    body: str,
    tainted_fns_sql: frozenset[str] = frozenset(),
    tainted_fns_dom: frozenset[str] = frozenset(),
) -> list[tuple[int, str, bool, bool]]:
    """Position-ordered ``(pos, name, sql_dirty, dom_dirty)`` for each
    top-of-line assignment — used both by the sink checker and by the
    intra-file return-taint pass."""
    out: list[tuple[int, str, bool, bool]] = []
    tainted_sql: set[str] = set()
    tainted_dom: set[str] = set()
    for match in _TAINT_ASSIGN_RE.finditer(body):
        name = match.group("name")
        rhs = _taint_assign_rhs(body, match)
        sql_view = _taint_dirty_view(rhs, _TAINT_SQL_SAFE_RE)
        dom_view = _taint_dirty_view(rhs, _TAINT_DOM_SAFE_RE)
        sql_dirty = bool(
            _TAINT_SOURCE_RE.search(sql_view)
            or _taint_call_tainted(sql_view, tainted_fns_sql)
            or any(
                re.search(rf"\b{re.escape(t)}\b", sql_view)
                for t in tainted_sql
            )
        )
        dom_dirty = bool(
            _TAINT_SOURCE_RE.search(dom_view)
            or _taint_call_tainted(dom_view, tainted_fns_dom)
            or any(
                re.search(rf"\b{re.escape(t)}\b", dom_view)
                for t in tainted_dom
            )
        )
        (tainted_sql.add if sql_dirty else tainted_sql.discard)(name)
        (tainted_dom.add if dom_dirty else tainted_dom.discard)(name)
        out.append((match.start(), name, sql_dirty, dom_dirty))
    return out


def _taint_return_channels(
    body: str, bare_expr_is_return: bool = False
) -> tuple[bool, bool]:
    """Whether the function returns source-derived data, per channel.
    One propagation level: assigns replayed without tainted-callee
    knowledge, so ``g() → return f()`` does not chain transitively.

    The ``return`` scan runs on the interpolated view so a ``return``
    appearing inside a string literal does not count. With
    ``bare_expr_is_return`` (TypeScript arrow bodies like
    ``const f = (r) => r.query.x`` — no braces, no ``return`` keyword),
    the whole body is the implicit return expression."""
    tainted_sql: set[str] = set()
    tainted_dom: set[str] = set()
    for _pos, name, sql_dirty, dom_dirty in _taint_replay_assigns(body):
        (tainted_sql.add if sql_dirty else tainted_sql.discard)(name)
        (tainted_dom.add if dom_dirty else tainted_dom.discard)(name)
    ret_sql = ret_dom = False
    exprs = [
        ret.group("expr").split(";", 1)[0]
        for ret in re.finditer(
            r"(?m)^\s*return\s+(?P<expr>.+)", _taint_interpolated(body)
        )
    ]
    if not exprs and bare_expr_is_return:
        exprs = [body.split(";", 1)[0]]
    for expr in exprs:
        sql_view = _taint_dirty_view(expr, _TAINT_SQL_SAFE_RE)
        dom_view = _taint_dirty_view(expr, _TAINT_DOM_SAFE_RE)
        if _TAINT_SOURCE_RE.search(sql_view) or any(
            re.search(rf"\b{re.escape(t)}\b", sql_view) for t in tainted_sql
        ):
            ret_sql = True
        if _TAINT_SOURCE_RE.search(dom_view) or any(
            re.search(rf"\b{re.escape(t)}\b", dom_view) for t in tainted_dom
        ):
            ret_dom = True
    return ret_sql, ret_dom


def _taint_lite_issues(
    function_name: str,
    body: str,
    label: str,
    tainted_fns_sql: frozenset[str] = frozenset(),
    tainted_fns_dom: frozenset[str] = frozenset(),
) -> list[ForeignSafetyIssue]:
    """Flag source-derived names reaching a query/DOM sink unsanitized."""
    issues: list[ForeignSafetyIssue] = []

    # Track taint per output channel: ``sql`` clears on numeric coercion,
    # ``dom`` clears on HTML/URL escaping — neither clears the other.
    tainted_sql: set[str] = set()
    tainted_dom: set[str] = set()

    def dirty_view(text: str, safe_re: re.Pattern[str]) -> str:
        return _taint_dirty_view(text, safe_re)

    def dirty_names(text: str, tainted: set[str]) -> str | None:
        if _TAINT_SOURCE_RE.search(text):
            return "a request-derived value"
        for name in tainted:
            if re.search(rf"\b{re.escape(name)}\b", text):
                return f"`{name}` (request-derived)"
        return None

    assigns = _taint_replay_assigns(body, tainted_fns_sql, tainted_fns_dom)
    events = sorted(
        [
            *((pos, "assign", (name, s, d)) for pos, name, s, d in assigns),
            *((m.start(), "query", m) for m in _TAINT_QUERY_SINK_RE.finditer(body)),
            *((m.start(), "dom", m) for m in _TAINT_DOM_SINK_RE.finditer(body)),
        ],
        key=lambda event: event[0],
    )
    for _pos, kind, match in events:
        if kind == "assign":
            name, sql_dirty, dom_dirty = match
            (tainted_sql.add if sql_dirty else tainted_sql.discard)(name)
            (tainted_dom.add if dom_dirty else tainted_dom.discard)(name)
        elif kind == "query":
            # `QueryContext(ctx, sql)`-style sinks put the context first —
            # the query string is the next argument. ``exec.Command``-style
            # sinks take the program first and untrusted argv after — any
            # argument may carry the command, so scan them all.
            callee = match.group(0).rstrip("(").rstrip()
            args = _top_level_args(body[match.end() :])
            if "exec.Command" in callee:
                sink_args = args[1:] if callee.endswith("Context") else args
            else:
                arg_index = 1 if callee.endswith("Context") else 0
                sink_args = (
                    [args[arg_index]] if len(args) > arg_index else []
                )
            hit = next(
                (
                    hit
                    for a in sink_args
                    if (
                        hit := dirty_names(
                            dirty_view(a, _TAINT_SQL_SAFE_RE), tainted_sql
                        )
                    )
                    is not None
                ),
                None,
            )
            if hit is not None:
                issues.append(
                    ForeignSafetyIssue(
                        function_name=function_name,
                        message=(
                            f"{label} function `{function_name}` passes {hit} "
                            "as part of a query/command string — interpolate "
                            "parameters instead of concatenating"
                        ),
                        confidence="medium",
                    )
                )
        else:  # dom
            # ``el.innerHTML =`` / trailing operators continue on the next
            # line — keep pulling lines until the statement terminates.
            statement_lines: list[str] = []
            for line in body[match.start() :].split("\n"):
                statement_lines.append(line.split(";", 1)[0])
                tail = statement_lines[-1].rstrip()
                if ";" in line or not re.search(
                    r"[+\-*%|&?:,=<>!.(\\]$", tail
                ):
                    break
            statement = "\n".join(statement_lines)
            hit = dirty_names(
                dirty_view(statement, _TAINT_DOM_SAFE_RE), tainted_dom
            )
            if hit is not None:
                issues.append(
                    ForeignSafetyIssue(
                        function_name=function_name,
                        message=(
                            f"{label} function `{function_name}` writes {hit} "
                            "to the DOM — XSS risk; escape or sanitize first"
                        ),
                        confidence="medium",
                    )
                )
    return issues


def _python_function_source_segments(source: str) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    segments: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                segments.append((node.name, segment))
    return segments


def _taint_lite_source_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    bodies: list[tuple[str, str, str]] = []
    if ctx.language == "python":
        for name, segment in _python_function_source_segments(source):
            bodies.append(
                (name, _strip_python_comments(segment), "Python")
            )
    elif ctx.language == "typescript":
        for name, raw_body in _typescript_function_blocks(source):
            bodies.append(
                (
                    name,
                    _mask_nested_function_literals(raw_body, "typescript"),
                    "TypeScript",
                )
            )
    elif ctx.language == "go":
        for name, raw_body in _go_function_blocks(source):
            bodies.append(
                (
                    name,
                    _strip_go_rust_literals_and_comments(raw_body),
                    "Go",
                )
            )
    # Intra-file one-level propagation: a function whose ``return`` is
    # source-derived marks calls to it as tainted in every other body.
    fns_sql: set[str] = set()
    fns_dom: set[str] = set()
    for name, body, label in bodies:
        # A bare TypeScript arrow body (``(r) => r.query.x`` — no braces)
        # is itself the return expression; block bodies use ``return``.
        bare_expr = label == "TypeScript" and not body.lstrip().startswith("{")
        ret_sql, ret_dom = _taint_return_channels(
            body, bare_expr_is_return=bare_expr
        )
        if ret_sql:
            fns_sql.add(name)
        if ret_dom:
            fns_dom.add(name)
    for name, body, label in bodies:
        issues.extend(
            _taint_lite_issues(
                name,
                body,
                label,
                tainted_fns_sql=frozenset(fns_sql),
                tainted_fns_dom=frozenset(fns_dom),
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Go — writes to shared state outside the mutex that guards it
# ---------------------------------------------------------------------------

_GO_PACKAGE_VAR_RE = re.compile(
    r"(?m)^var\s+(?P<name>[A-Za-z_]\w*)\s+(?P<type>[^\n]+)"
)
_GO_VAR_BLOCK_RE = re.compile(r"(?m)^var\s*\((?P<body>[^)]*)")
_GO_VAR_BLOCK_NAME_RE = re.compile(
    r"(?m)^\s*(?P<name>[A-Za-z_]\w*)\s+(?P<type>[^\n]+)"
)
_GO_MUTEX_FIELD_RE = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s+sync\.(?:RW)?Mutex")
_GO_METHOD_DEF_RE = re.compile(
    r"func\s*\(\s*(?P<r>[A-Za-z_]\w*)\s+\*?[A-Za-z_]\w*(?:\[[^\]]*\])?\s*\)\s*"
    r"(?P<name>[A-Za-z_]\w*)\s*\("
)
# ``name++``/``name--``/``name <op>=`` — the bare ``=`` must not be part of
# ``==``/``<=``/``>=``/``!=``, and ``:=`` declares a local (shadowing is
# checked separately).
_GO_WRITE_RE_TEMPLATE = (
    r"(?<![\w.])NAME(?:\.\w+)?\s*(?:\+\+|--|[+\-*/%|&^]=|=(?![=<>]))"
)
_GO_LOCK_EVENT_RE = re.compile(
    r"\b(?P<recv>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\."
    r"(?P<kind>Lock|Unlock|RLock|RUnlock)\s*\("
)


def _go_unguarded_writes(
    body: str,
    name_re: str,
    mutex_names: set[str],
    lock_recv: str | None = None,
):
    """Yield writes to ``name_re`` outside any ``Lock()…Unlock()`` window —
    the last lock event *on a declared mutex* before each write decides
    whether it is held. ``RLock`` is shared and never protects a write.

    ``lock_recv`` scopes the association to a receiver: a write to
    ``s.field`` is guarded by ``s.mu.Lock()`` or a bare package-level
    ``mu.Lock()``, but not by ``other.mu.Lock()``."""
    events: list[tuple[int, str]] = []
    depth = 0
    depths: dict[int, int] = {}
    for i, ch in enumerate(body):
        depths[i] = depth
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(depth - 1, 0)
    for m in _GO_LOCK_EVENT_RE.finditer(body):
        recv = m.group("recv")
        if recv.rsplit(".", 1)[-1] not in mutex_names:
            # ``other.Lock()`` guards a different mutex — it does not
            # protect this write.
            continue
        if (
            lock_recv is not None
            and "." in recv
            and recv.rsplit(".", 1)[0] != lock_recv
        ):
            # ``other.mu.Lock()`` protects ``other``'s fields, not
            # this receiver's.
            continue
        if depths.get(m.start(), 0) != 0:
            # A lock taken inside a conditional/loop body does not
            # provably hold at a top-level write — skip the event.
            continue
        kind = m.group("kind")
        # ``defer mu.Unlock()``/``defer s.mu.Unlock()`` release at function
        # end — keep the lock held for every statement after the Lock.
        before = body[max(0, m.start() - 16) : m.start()]
        if kind in ("Unlock", "RUnlock") and re.search(
            r"\bdefer\s+(?:\w+\.)*$", before
        ):
            events.append((len(body) + 1, kind))
        else:
            events.append((m.start(), kind))
    # Deferred unlocks were moved to the end — restore position order so the
    # "last event before the write" scan can break early correctly.
    events.sort(key=lambda event: event[0])
    write_re = re.compile(_GO_WRITE_RE_TEMPLATE.replace("NAME", name_re))
    for write in write_re.finditer(body):
        held = False
        for pos, kind in events:
            if pos >= write.start():
                break
            held = kind == "Lock"
        if not held:
            yield write


def _go_shared_state_issues(
    source: str, ctx: PatternContext
) -> list[ForeignSafetyIssue]:
    """Flag writes to package-level state / receiver fields when the file
    declares a mutex but the writing function never takes one."""
    stripped = _strip_go_rust_literals_and_comments(source)
    mutex_names = {m.group("name") for m in _GO_MUTEX_FIELD_RE.finditer(stripped)}
    if not mutex_names:
        return []
    shared_vars = {
        m.group("name")
        for m in _GO_PACKAGE_VAR_RE.finditer(stripped)
        if not re.search(r"\b(?:sync|atomic)\.", m.group("type"))
        and m.group("name") not in mutex_names
    }
    for block in _GO_VAR_BLOCK_RE.finditer(stripped):
        for m in _GO_VAR_BLOCK_NAME_RE.finditer(block.group("body")):
            if (
                not re.search(r"\b(?:sync|atomic)\.", m.group("type"))
                and m.group("name") not in mutex_names
            ):
                shared_vars.add(m.group("name"))
    issues: list[ForeignSafetyIssue] = []

    def check_package_writes(name: str, body: str) -> None:
        for var in sorted(shared_vars):
            # ``var :=`` / ``var var`` inside the body declares a local
            # that shadows the package variable — only within the braces
            # enclosing the declaration, and only after it.
            decl = re.search(
                rf"\b{re.escape(var)}\s*:=|\bvar\s+{re.escape(var)}\b", body
            )
            decl_pos = decl.start() if decl is not None else len(body)
            shadow_end = len(body)
            if decl is not None:
                # Innermost ``{``…``}`` containing the declaration is the
                # local's scope — a ``:=`` inside ``if cond { … }`` does
                # not shadow package-level writes after the block.
                best_end = len(body)
                stack: list[int] = []
                for i, ch in enumerate(body):
                    if ch == "{":
                        stack.append(i)
                    elif ch == "}" and stack:
                        if stack[-1] < decl.start() < i:
                            best_end = min(best_end, i)
                        stack.pop()
                if stack:
                    best_end = min(best_end, len(body))
                shadow_end = best_end
            for write in _go_unguarded_writes(
                body, re.escape(var), mutex_names
            ):
                if write.start() >= decl_pos and write.start() <= shadow_end:
                    continue
                # An ``atomic.*(&var, …)`` call elsewhere does not protect
                # an ordinary ``var++`` — mixed access still races.
                issues.append(
                    ForeignSafetyIssue(
                        function_name=name,
                        message=(
                            f"Go function `{name}` writes package-level "
                            f"`{var}` without holding a mutex — this file "
                            "declares `sync.(RW)Mutex` fields — possible "
                            "data race with other callers"
                        ),
                        confidence="medium",
                    )
                )
                return

    for name, raw_body in _go_function_blocks(source):
        check_package_writes(name, _strip_go_rust_literals_and_comments(raw_body))
    # Methods are scanned per definition so same-named methods on
    # different receivers each check against their own receiver name.
    for method in _GO_METHOD_DEF_RE.finditer(source):
        name, r = method.group("name"), method.group("r")
        args_end = method.end() - 1
        args_close = args_end + len(_paren_args(source, args_end)) + 1
        nl = source.find("\n", args_close)
        brace = source.find("{", args_close)
        if brace == -1 or (nl != -1 and nl < brace):
            continue
        body = _strip_go_rust_literals_and_comments(
            _balanced_brace_body(source, brace)
        )
        check_package_writes(name, body)

        for field_write in _go_unguarded_writes(
            body, re.escape(r), mutex_names, lock_recv=r
        ):
            field = re.match(
                rf"{re.escape(r)}\.([A-Za-z_]\w*)", field_write.group(0)
            )
            if field is None or field.group(1) in mutex_names:
                continue
            # An ``atomic.*(&r.field, …)`` call elsewhere does not protect
            # an ordinary ``r.field++`` — mixed access still races.
            issues.append(
                ForeignSafetyIssue(
                    function_name=name,
                    message=(
                        f"Go method `{name}` writes "
                        f"`{r}.{field.group(1)}` without holding the "
                        "receiver's mutex — this file declares "
                        "`sync.(RW)Mutex` fields — possible data race "
                        "with other callers"
                    ),
                    confidence="medium",
                )
            )
            break
    return issues


# ---------------------------------------------------------------------------
# Opt-out markers
# ---------------------------------------------------------------------------

# ``mumei:allow`` in the file's own comment syntax — ``#`` for Python,
# ``//`` for the C-family languages — suppresses a finding on the same line
# or the line immediately below the marker.
_HASH_ALLOW_MARKER_RE = re.compile(r"#\s*mumei:allow\b")
_SLASH_ALLOW_MARKER_RE = re.compile(r"//\s*mumei:allow\b")
# A ``#[allow(mumei::*)]`` attribute also counts as a marker line and, when
# it sits directly on a ``fn`` item (possibly under stacked attributes or
# doc comments), suppresses every finding inside that function — matching
# Rust attribute scoping.
_RUST_ALLOW_ATTR_RE = re.compile(r"#\s*\[\s*allow\s*\(\s*mumei::")
_RUST_ATTR_LINE_RE = re.compile(r"^\s*(#|//|/\*)")
_RUST_FN_DECL_RE = re.compile(r"\bfn\s+(\w+)")
_RUST_RAW_STRING_RE = re.compile(r"r(#*)\"")

# Per-language comment and string delimiters for the lexical-state scan —
# enough fidelity to tell markers and declarations apart from literal
# contents without a full lexer.
_LINE_COMMENT_TOKEN = {
    "python": "#",
    "rust": "//",
    "typescript": "//",
    "go": "//",
    "solidity": "//",
}
_BLOCK_COMMENT_LANGUAGES = frozenset({"rust", "typescript", "go", "solidity"})
# Longest delimiters first so triple quotes win over single quotes.
_STRING_DELIMITERS = {
    "python": ('"""', "'''", '"', "'"),
    "rust": ('"',),
    "typescript": ('"', "'", "`"),
    "go": ('"', "'", "`"),
    "solidity": ('"', "'"),
}
# Delimiters whose literal may legally contain a raw newline; an unclosed
# single-line string is a syntax slip and resets at the line boundary
# instead of masking the rest of the file.
_MULTILINE_DELIMITERS = {
    "python": frozenset({'"""', "'''"}),
    "rust": frozenset({'"'}),
    "typescript": frozenset({"`"}),
    "go": frozenset({"`"}),
    "solidity": frozenset(),
}
_CODE, _STRING, _COMMENT = 0, 1, 2


def _non_code_states(source: str, language: str) -> bytearray:
    """Per-offset lexical state: ``_CODE``/``_STRING``/``_COMMENT``.

    One pass over ``source``. Rust ``'`` is never a delimiter (lifetimes);
    ``r#\"...\"#`` raw strings close on ``\"`` plus their leading hashes and
    take no ``\\`` escapes. Block comments nest (Rust's do).
    """
    states = bytearray(len(source))
    line_comment = _LINE_COMMENT_TOKEN.get(language)
    block_comments = language in _BLOCK_COMMENT_LANGUAGES
    delimiters = _STRING_DELIMITERS.get(language, ('"', "'"))
    multiline = _MULTILINE_DELIMITERS.get(language, frozenset({"\"", "'"}))
    n = len(source)
    i = 0
    state = _CODE
    block_depth = 0
    close = ""
    close_hashes = 0
    raw = False
    while i < n:
        if state == _STRING:
            if source[i] == "\n" and close not in multiline:
                state = _CODE
                continue
            if (
                raw
                and source[i] == '"'
                and source.startswith("#" * close_hashes, i + 1)
            ):
                end = i + 1 + close_hashes
                states[i:end] = b"\x01" * (end - i)
                i = end
                state = _CODE
                continue
            if not raw and source[i] == "\\":
                states[i : i + 2] = b"\x01" * min(2, n - i)
                i += 2
                continue
            if source.startswith(close, i):
                states[i : i + len(close)] = b"\x01" * len(close)
                i += len(close)
                state = _CODE
                continue
            states[i] = _STRING
            i += 1
            continue
        if state == _COMMENT:
            if block_depth == 0 and source[i] == "\n":
                state = _CODE
                continue
            states[i] = _COMMENT
            if block_depth:
                if source.startswith("/*", i):
                    states[i + 1] = _COMMENT
                    block_depth += 1
                    i += 2
                    continue
                if source.startswith("*/", i):
                    states[i + 1] = _COMMENT
                    block_depth -= 1
                    i += 2
                    if not block_depth:
                        state = _CODE
                    continue
            i += 1
            continue
        if line_comment and source.startswith(line_comment, i):
            state = _COMMENT
            continue
        if block_comments and source.startswith("/*", i):
            state = _COMMENT
            block_depth = 1
            continue
        if language == "rust":
            raw_match = _RUST_RAW_STRING_RE.match(source, i)
            if raw_match is not None:
                state = _STRING
                raw = True
                close = '"'
                close_hashes = len(raw_match.group(1))
                states[i : raw_match.end()] = (
                    b"\x01" * (raw_match.end() - i)
                )
                i = raw_match.end()
                continue
        opened = False
        for delim in delimiters:
            if source.startswith(delim, i):
                state = _STRING
                raw = False
                close_hashes = 0
                close = delim
                states[i : i + len(delim)] = b"\x01" * len(delim)
                i += len(delim)
                opened = True
                break
        if not opened:
            i += 1
    return states


def _suppression_markers(
    source: str, language: str
) -> tuple[set[int], list[tuple[int, int, str]], dict[str, int]]:
    """``(marker_lines, allowed_fn_ranges, fn_name_counts)`` for opt-out
    markers in ``source``.

    ``allowed_fn_ranges`` entries are ``(decl_line, end_line, name)`` — the
    ``fn`` item a ``#[allow(mumei::*)]`` attribute decorates, bounded by the
    next ``fn`` declaration at the same or shallower brace depth so nested
    functions stay inside the parent's span while a same-named sibling is
    not suppressed.
    """
    comment_re = (
        _HASH_ALLOW_MARKER_RE
        if language == "python"
        else _SLASH_ALLOW_MARKER_RE
    )
    states = _non_code_states(source, language)
    marker_lines: set[int] = set()
    allowed_ranges: list[tuple[int, int, str]] = []
    lines = source.splitlines()
    line_starts = [0]
    for match in re.finditer("\n", source):
        line_starts.append(match.end())
    fn_decls: list[tuple[int, int, str, int]] = []
    depth = 0
    if language == "rust":
        for index, text in enumerate(lines):
            base = line_starts[index]
            for match in _RUST_FN_DECL_RE.finditer(text):
                pos = base + match.start()
                if states[pos] != _CODE:
                    continue
                column = match.start()
                inner = sum(
                    (1 if char == "{" else -1)
                    for col, char in enumerate(text[:column])
                    if states[base + col] == _CODE and char in "{}"
                )
                fn_decls.append(
                    (index + 1, pos, match.group(1), depth + inner)
                )
            for col, char in enumerate(text):
                if states[base + col] == _CODE:
                    depth += 1 if char == "{" else -1 if char == "}" else 0
    fn_name_counts: dict[str, int] = {}
    for _line_no, _pos, fn_name, _depth in fn_decls:
        fn_name_counts[fn_name] = fn_name_counts.get(fn_name, 0) + 1
    for index, text in enumerate(lines):
        comment_match = comment_re.search(text)
        if (
            comment_match
            and states[line_starts[index] + comment_match.start()] != _STRING
        ):
            marker_lines.add(index + 1)
        attr_match = _RUST_ALLOW_ATTR_RE.search(text)
        if (
            language != "rust"
            or attr_match is None
            or states[line_starts[index] + attr_match.start()] != _CODE
        ):
            continue
        marker_lines.add(index + 1)
        cursor = index + 1
        while cursor < len(lines) and (
            not lines[cursor].strip() or _RUST_ATTR_LINE_RE.match(lines[cursor])
        ):
            cursor += 1
        if cursor >= len(lines):
            continue
        fn_match = _RUST_FN_DECL_RE.search(lines[cursor])
        if fn_match is None:
            continue
        decl_pos = line_starts[cursor] + fn_match.start()
        if states[decl_pos] != _CODE:
            continue
        decl_line = cursor + 1
        decl_depth = next(
            (decl[3] for decl in fn_decls if decl[1] == decl_pos), 0
        )
        end_line = next(
            (
                line_no
                for line_no, off, _name, decl_d in fn_decls
                if off > decl_pos and decl_d <= decl_depth
            ),
            len(lines) + 1,
        )
        allowed_ranges.append((decl_line, end_line, fn_match.group(1)))
    return marker_lines, allowed_ranges, fn_name_counts


def _suppress_pattern_issues(
    issues: list[ForeignSafetyIssue], source: str, language: str
) -> list[ForeignSafetyIssue]:
    """Drop findings a ``mumei:allow`` marker covers — every registered
    pattern gets the opt-out for free through this post-filter."""
    if not issues or "mumei:" not in source:
        return issues
    marker_lines, allowed_ranges, fn_name_counts = _suppression_markers(
        source, language
    )
    if not marker_lines and not allowed_ranges:
        return issues
    return [
        issue
        for issue in issues
        if not _allowed_by_attribute(issue, allowed_ranges, fn_name_counts)
        and (
            issue.line <= 0
            or (
                issue.line not in marker_lines
                and issue.line - 1 not in marker_lines
            )
        )
    ]


def _allowed_by_attribute(
    issue: ForeignSafetyIssue,
    allowed_ranges: list[tuple[int, int, str]],
    fn_name_counts: dict[str, int],
) -> bool:
    """True when ``issue`` sits inside an ``#[allow(mumei::*)]`` function.

    Line-numbered findings must fall inside the decorated ``fn``'s
    declaration-to-next-``fn`` span so a same-named sibling stays flagged;
    an unlocatable finding is suppressed only when its function name is
    unambiguous in the file.
    """
    if issue.line > 0:
        return any(
            issue.function_name == name and start <= issue.line < end
            for start, end, name in allowed_ranges
        )
    return any(
        issue.function_name == name and fn_name_counts.get(name, 0) == 1
        for _start, _end, name in allowed_ranges
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

Detector = Callable[[str, PatternContext], list[ForeignSafetyIssue]]


@dataclass(frozen=True)
class LanguagePattern:
    """One language-specific heuristic. ``detect`` takes the raw source text
    and the shared ``PatternContext`` and returns advisory
    ``ForeignSafetyIssue`` objects."""

    name: str
    languages: frozenset[str]
    detect: Detector


LANGUAGE_PATTERNS: tuple[LanguagePattern, ...] = (
    LanguagePattern(
        "python_mutable_default", frozenset({"python"}), _python_mutable_default_issues
    ),
    LanguagePattern(
        "python_swallow_except", frozenset({"python"}), _python_swallow_except_issues
    ),
    LanguagePattern(
        "rust_unwrap_expect", frozenset({"rust"}), _rust_unwrap_expect_issues
    ),
    LanguagePattern(
        "rust_escape_hatch", frozenset({"rust"}), _rust_escape_hatch_issues
    ),
    LanguagePattern(
        "python_dangerous_call",
        frozenset({"python"}),
        _python_dangerous_call_issues,
    ),
    LanguagePattern(
        "python_mutation_during_iteration",
        frozenset({"python"}),
        _python_mutation_during_iteration_issues,
    ),
    LanguagePattern(
        "go_defer_in_loop", frozenset({"go"}), _go_defer_in_loop_issues
    ),
    LanguagePattern(
        "go_shared_state", frozenset({"go"}), _go_shared_state_issues
    ),
    LanguagePattern(
        "taint_lite",
        frozenset({"python", "typescript", "go"}),
        _taint_lite_source_issues,
    ),
    # ``javascript``/``ts``/``tsx`` aliases normalize to "typescript".
    LanguagePattern(
        "typescript_floating_promise",
        frozenset({"typescript"}),
        _typescript_floating_promise_issues,
    ),
    LanguagePattern(
        "typescript_safety",
        frozenset({"typescript"}),
        _typescript_safety_issues,
    ),
    LanguagePattern(
        "solidity_pattern", frozenset({"solidity"}), _solidity_pattern_issues
    ),
)


def language_pattern_issues(
    source: str, language: str, *, source_file: str | None = None
) -> list[ForeignSafetyIssue]:
    """Run every registered pattern for ``language`` over ``source``.

    Advisory only: issues carry no counterexample, so downstream surfaces
    treat them as warnings, not violations.
    """
    normalized = _normalize_language(language)
    if _is_generated_source(source):
        return []
    if (
        normalized == "solidity"
        and source_file
        and ("/mocks/" in source_file or "\\mocks\\" in source_file)
    ):
        return []
    tree = None
    source_bytes = None
    if normalized in tree_sitter_extract.SUPPORTED_LANGUAGES:
        tree, source_bytes = tree_sitter_extract.parse(source, normalized)
    ctx = PatternContext(
        language=normalized, tree=tree, source_bytes=source_bytes
    )
    issues: list[ForeignSafetyIssue] = []
    for pattern in LANGUAGE_PATTERNS:
        if normalized in pattern.languages:
            issues.extend(pattern.detect(source, ctx))
    # Suppress before deduping: two identical calls where only the first is
    # marked collapse to one (function_name, message) pair — suppressing
    # after dedup could drop the surviving marked copy and erase the
    # unmarked call's warning entirely.
    issues = _suppress_pattern_issues(issues, source, normalized)
    seen: set[tuple[str, str]] = set()
    deduped: list[ForeignSafetyIssue] = []
    for issue in issues:
        key = (issue.function_name, issue.message)
        if key not in seen:
            seen.add(key)
            deduped.append(issue)
    return deduped
