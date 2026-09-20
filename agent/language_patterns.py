"""Language-specific "common problem" heuristics (V1-B-2).

Each detector is a small self-contained function returning
``ForeignSafetyIssue`` objects and is registered in ``LANGUAGE_PATTERNS``.
Adding a pattern means writing one detector and appending one entry —
no dispatch code to edit. All patterns are advisory: they carry no
counterexample, so downstream surfaces report them as warnings rather than
hard violations.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Callable, Iterable

from agent.cross_validation_foreign import _strip_go_rust_literals_and_comments
from agent.strategies.foreign_code_strategy_helpers import (
    ForeignSafetyIssue,
    _balanced_brace_body,
    _go_function_blocks,
    _is_generated_source,
    _mask_nested_function_literals,
    _normalize_language,
    _rust_function_scopes,
    _solidity_function_blocks_with_attrs,
    _typescript_function_blocks,
)


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


def _python_mutable_default_issues(source: str) -> list[ForeignSafetyIssue]:
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


def _python_swallow_except_issues(source: str) -> list[ForeignSafetyIssue]:
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
                    isinstance(handler.type, ast.Name)
                    and handler.type.id in {"Exception", "BaseException"}
                    and all(_python_noop_statement(stmt) for stmt in handler.body)
                ):
                    issues.append(
                        ForeignSafetyIssue(
                            function_name=node.name,
                            message=(
                                f"Python function `{node.name}` catches "
                                f"`{handler.type.id}` and does nothing — "
                                "the error is silently swallowed"
                            ),
                        )
                    )
    return issues


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------

_RUST_UNWRAP_RE = re.compile(
    r"\b(?P<recv>[A-Za-z_]\w*)\s*\.\s*(?P<call>unwrap|expect)\s*\("
)


def _rust_unwrap_guarded(body: str, receiver: str) -> bool:
    recv = re.escape(receiver)
    return bool(
        re.search(rf"\b{recv}\s*\.\s*(?:is_ok|is_some)\s*\(", body)
        or re.search(rf"\b(?:if|while)\s+let\b[^{{}};]*\b{recv}\b", body)
        or re.search(rf"\blet\b[^{{}};]*\b{recv}\b[^{{}};]*\belse\b", body)
        or re.search(rf"\bmatch\s+{recv}\b", body)
        or re.search(rf"\b{recv}\s*\?", body)
    )


def _rust_unwrap_expect_issues(source: str) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    for name, body, _params in _rust_function_scopes(source):
        masked = _strip_go_rust_literals_and_comments(body)
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
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

_GO_FOR_HEADER_RE = re.compile(r"\bfor\b")


def _go_defer_in_loop_issues(source: str) -> list[ForeignSafetyIssue]:
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


def _typescript_floating_promise_issues(source: str) -> list[ForeignSafetyIssue]:
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
    issues: list[ForeignSafetyIssue] = []
    for name, body in _typescript_function_blocks(source):
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
                    )
                )
                break
    return issues


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


def _solidity_pattern_issues(source: str) -> list[ForeignSafetyIssue]:
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
                )
            )
            break
    return issues


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

Detector = Callable[[str], list[ForeignSafetyIssue]]


@dataclass(frozen=True)
class LanguagePattern:
    """One language-specific heuristic. ``detect`` takes raw source text and
    returns advisory ``ForeignSafetyIssue`` objects."""

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
    del source_file  # reserved for path-based suppression (e.g. test dirs)
    normalized = _normalize_language(language)
    if _is_generated_source(source):
        return []
    issues: list[ForeignSafetyIssue] = []
    seen: set[tuple[str, str]] = set()
    for pattern in LANGUAGE_PATTERNS:
        if normalized in pattern.languages:
            for issue in pattern.detect(source):
                key = (issue.function_name, issue.message)
                if key not in seen:
                    seen.add(key)
                    issues.append(issue)
    return issues
