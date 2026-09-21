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
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Callable, Iterable

from agent import tree_sitter_extract
from agent.cross_validation_foreign import _strip_go_rust_literals_and_comments
from agent.strategies.foreign_code_strategy_helpers import (
    ForeignSafetyIssue,
    _balanced_brace_body,
    _go_function_blocks,
    _is_generated_source,
    _is_solidity_mock_source,
    _mask_nested_function_literals,
    _normalize_language,
    _rust_function_scopes,
    _solidity_function_blocks_with_attrs,
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
_RUST_POSITIVE_CHECKS = frozenset({"is_some", "is_ok"})
_RUST_NEGATIVE_CHECKS = frozenset({"is_err", "is_none"})
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
            rf"\b{recv}\s*\.\s*(?:is_ok|is_some|is_err|is_none)\s*\(", body
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
    for name, body, _params in _rust_function_scopes(source):
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
    # Generic scan: the first ``recv.<check>()`` in the condition decides.
    stack = [condition]
    while stack:
        node = stack.pop()
        parts = _rust_call_parts(node, source_bytes)
        if parts is not None and parts[0] == recv:
            if parts[1] in _RUST_POSITIVE_CHECKS:
                return "then"
            if parts[1] in _RUST_NEGATIVE_CHECKS:
                return "else"
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


def _rust_statement_guards(node, recv: str, source_bytes: bytes) -> bool:
    """True when a preceding sibling statement guarantees ``recv`` is
    Ok/Some for everything after it in the same block."""
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
    if inner.type == "if_expression" and _rust_if_guards_fallthrough(
        inner, recv, source_bytes
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
                rf"{re.escape(recv)}\.(?:{'|'.join(_RUST_POSITIVE_CHECKS)})\(",
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


def _rust_statement_repairs(node, targets: set, recv: str, source_bytes: bytes) -> bool:
    """True when the statement unconditionally leaves a tracked target
    holding a value variant — ``res = Some(..)``/``Ok(..)``, writes through
    ``&mut`` aliases (``*p = Some(..)``, ``p.insert(..)``), a
    ``let res = Some(..)`` shadowing, or an ``Option`` insert-style method
    call anywhere in the statement's unconditionally-evaluated part (e.g.
    ``let v = res.get_or_insert(5)``). Conditional repairs
    (``if … { res = Ok(..) }``) are not read; they fall through to plain
    mutation handling."""
    inner = _rust_statement_inner(node)
    if inner is None:
        return False
    if inner.type == "assignment_expression":
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
                    ):
                        # `res = Some(..)` re-establishes the invariant.
                        guarded = True
                    else:
                        # A write to ``recv`` stales any earlier guard —
                        # only a guard after the latest write still applies.
                        guarded = False
                        mutated = True
                elif _rust_statement_guards(sibling, recv, source_bytes):
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
                        )
                    )
        elif node.type == "macro_invocation":
            # Macro bodies are opaque token trees — calls inside them
            # (``println!("{}", r.unwrap())``) are not expression nodes, so
            # scan the token text and judge dominance by the macro's own
            # position in the tree.
            for match in _RUST_UNWRAP_RE.finditer(
                _node_text(source_bytes, node)
            ):
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
    for name, body in blocks:
        masked = _strip_go_rust_literals_and_comments(
            _mask_nested_function_literals(body, "go")
        )
        deferred = None
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
    for name, body in _typescript_function_blocks(source):
        if name in expr_arrow_names:
            continue
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
    for name, _attrs, raw_body in _solidity_function_blocks_with_attrs(source):
        body = _strip_go_rust_literals_and_comments(raw_body)
        if re.search(r"\btx\.origin\b", body):
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
                )
            )
        if re.search(r"\bselfdestruct\s*\(", body):
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
                )
            )
    return issues


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
        "go_defer_in_loop", frozenset({"go"}), _go_defer_in_loop_issues
    ),
    # ``javascript``/``ts``/``tsx`` aliases normalize to "typescript".
    LanguagePattern(
        "typescript_floating_promise",
        frozenset({"typescript"}),
        _typescript_floating_promise_issues,
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
    seen: set[tuple[str, str]] = set()
    for pattern in LANGUAGE_PATTERNS:
        if normalized in pattern.languages:
            for issue in pattern.detect(source, ctx):
                key = (issue.function_name, issue.message)
                if key not in seen:
                    seen.add(key)
                    issues.append(issue)
    return issues
