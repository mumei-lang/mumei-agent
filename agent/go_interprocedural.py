"""Opt-in parameter-dependency summaries, not proofs or audit-grade inputs.

Bodies are let bindings — single-name ``name := expression`` declarations —
plus ``if``/``else`` and bounded ``for`` statements followed by one or more
explicit scalar return expressions; the result unions every syntactic return's
dependencies (unreachable returns included — reachability is not proven). A
``for`` clause may hold one let-binding initializer, a supported condition and
an inc/dec update on a bound scalar; ``range``, ``break``/``continue``,
compound operators, tuples, ``if`` initializers and every other statement shape
stay unsupported. A scalar ``x = expression`` reassignment replaces the
binding's dependencies — it never declares a new variable. Loop bodies are
joined to a widening fixed point so dependencies propagating across
iterations are captured (joins, not unrolls — trip counts are never
modelled). Compiler-resolved
bindings/calls supply identity; tree-sitter supplies syntax, never resolution.
Reports require the trusted producer and reader described in go_type_snapshot.
No processes, imports, persistent caches or existing audit routes are invoked.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from agent import control_flow
from agent.go_type_snapshot import (
    MAX_SOURCE_BYTES,
    PROFILE as TYPE_PROFILE,
    TARGETS,
    ByteSpan,
    Function,
    GoType,
    GoTypeSnapshot,
    SnapshotError,
)

PROFILE = "mumei.go-scalar-parameter-deps/v1"
MAX_FUNCTIONS = 128
MAX_DEPTH = 48
MAX_EXPRESSION_NODES = 2048
_BINARY = frozenset(
    {"+", "-", "*", "&", "|", "^", "&^", "==", "!=", "<", "<=", ">", ">=", "&&", "||"}
)
_UNARY = frozenset({"+", "-", "!", "^"})


@dataclass(frozen=True)
class SummaryGap:
    reason: str
    span: ByteSpan | None = None
    callee: str = ""


@dataclass(frozen=True)
class CallTransfer:
    span: ByteSpan
    target: str
    arguments: tuple[frozenset[int], ...]
    result: frozenset[int]


@dataclass(frozen=True)
class FunctionSummary:
    binding_id: str
    key: str
    parameters: tuple[GoType, ...]
    result_type: GoType | None
    return_dependencies: frozenset[int] | None
    calls: tuple[CallTransfer, ...]
    gaps: tuple[SummaryGap, ...]

    @property
    def available(self) -> bool:
        return self.return_dependencies is not None and not self.gaps

    @property
    def effects(self) -> str:
        return "none_in_supported_fragment" if self.available else "unknown"


def _context(source: str, snapshot: GoTypeSnapshot) -> tuple[bytes, str]:
    try:
        raw = source.encode("utf-8")
    except UnicodeError:
        raise SnapshotError("Unsupported Go summary source encoding") from None
    if (
        len(raw) > MAX_SOURCE_BYTES
        or hashlib.sha256(raw).hexdigest() != snapshot.source_sha256
        or snapshot.profile != TYPE_PROFILE
        or snapshot.language_version != "go1.23"
        or snapshot.target_arch not in TARGETS
    ):
        raise SnapshotError("Go summary context unavailable or stale")
    payload = json.dumps(
        [PROFILE, control_flow.PROFILE, asdict(snapshot)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return raw, hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class GoSummarySet:
    context_key: str
    functions: tuple[FunctionSummary, ...]
    profile: str = PROFILE

    def for_function(
        self, source: str, snapshot: GoTypeSnapshot, binding_id: str
    ) -> FunctionSummary:
        """Reject reuse after any source, target, compiler or report change."""
        if _context(source, snapshot)[1] != self.context_key:
            raise SnapshotError("Go summary context unavailable or stale")
        result = next((f for f in self.functions if f.binding_id == binding_id), None)
        if result is None:
            raise SnapshotError("Go function summary unavailable")
        return result


class _Unsupported(Exception):
    def __init__(self, reason: str, span: ByteSpan | None = None, callee: str = ""):
        self.gap = SummaryGap(reason, span, callee)


def _span(node: Any) -> ByteSpan:
    return ByteSpan(node.start_byte, node.end_byte)


def _children(node: Any) -> list[Any]:
    return [c for c in node.named_children if c.type != "comment"]


def _syntax(raw: bytes) -> Any:
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_go

        root = Parser(Language(tree_sitter_go.language())).parse(raw).root_node
        return None if root.has_error else root
    except (ImportError, ValueError, TypeError, RuntimeError):
        return None


class _Builder:
    def __init__(self, source: str, snapshot: GoTypeSnapshot, raw: bytes, key: str):
        self.source, self.snapshot, self.key = source, snapshot, key
        self.bindings = {b.id: b for b in snapshot.bindings}
        self.functions = {f.binding_id: f for f in snapshot.functions}
        self.references = {r.span: r for r in snapshot.references}
        self.calls = {c.span: c for c in snapshot.calls}
        self.blocks: dict[ByteSpan, Any] = {}
        self.bindings_by_span = {b.span: b for b in snapshot.bindings}
        self.cache: dict[str, FunctionSummary] = {}
        self.active: set[str] = set()
        root = _syntax(raw)
        if root is not None:
            for node in root.named_children:
                if node.type not in {"function_declaration", "method_declaration"}:
                    continue
                name, body = (
                    node.child_by_field_name("name"),
                    node.child_by_field_name("body"),
                )
                if name is not None and body is not None:
                    self.blocks[_span(name)] = body

    def result(
        self,
        fn: Function,
        dependencies: frozenset[int] | None = None,
        calls: tuple[CallTransfer, ...] = (),
        gaps: tuple[SummaryGap, ...] = (),
    ) -> FunctionSummary:
        key = hashlib.sha256((self.key + ":" + fn.binding_id).encode()).hexdigest()
        return FunctionSummary(
            fn.binding_id,
            key,
            tuple(p.type for p in fn.parameters),
            fn.results[0].type if len(fn.results) == 1 else None,
            dependencies,
            calls,
            gaps,
        )

    def summarize(self, binding_id: str) -> FunctionSummary:
        fn = self.functions[binding_id]
        if binding_id in self.cache:
            return self.cache[binding_id]
        if binding_id in self.active:
            return self.result(fn, gaps=(SummaryGap("recursive_call_graph"),))
        if len(self.active) >= MAX_DEPTH:
            return self.result(fn, gaps=(SummaryGap("analysis_limit"),))
        self.active.add(binding_id)
        try:
            summary = self.body(fn)
        except _Unsupported as error:
            summary = self.result(fn, gaps=(error.gap,))
        finally:
            self.active.remove(binding_id)
        self.cache[binding_id] = summary
        return summary

    def body(self, fn: Function) -> FunctionSummary:
        if (
            fn.body is None
            or fn.method
            or fn.generic
            or fn.variadic
            or len(fn.results) != 1
            or fn.results[0].binding_id
            or any(
                p.type.kind not in {"integer", "boolean"}
                for p in (*fn.parameters, *fn.results)
            )
        ):
            raise _Unsupported("unsupported_signature", fn.body)
        binding = self.bindings.get(fn.binding_id)
        block = self.blocks.get(binding.span) if binding is not None else None
        if block is None:
            raise _Unsupported("syntax_or_parser_unavailable", fn.body)
        if ByteSpan(block.start_byte + 1, block.end_byte - 1) != fn.body:
            raise _Unsupported("source_mapping_unavailable", fn.body)
        pending = [(block, 0)]
        visited = 0
        while pending:
            node, depth = pending.pop()
            visited += 1
            if depth >= MAX_DEPTH or visited > MAX_EXPRESSION_NODES:
                raise _Unsupported("analysis_limit", fn.body)
            pending.extend((child, depth + 1) for child in _children(node))
        cfg = self.snapshot.cfg_for_function(self.source, fn.binding_id)
        if cfg.graph is None:
            raise _Unsupported("cfg_unavailable", fn.body)
        statements = _children(block)
        if len(statements) == 1 and statements[0].type == "statement_list":
            statements = _children(statements[0])
        if not statements:
            raise _Unsupported("unsupported_body", fn.body)
        params = {p.binding_id: i for i, p in enumerate(fn.parameters) if p.binding_id}
        transfers: list[CallTransfer] = []
        count = [0]
        locals_: dict[str, frozenset[int]] = {}
        deps: list[frozenset[int]] = [frozenset()]
        saw_return = [False]
        for statement in statements:
            self.statement(
                statement, fn, params, locals_, transfers, count, deps, saw_return
            )
        if not saw_return[0]:
            raise _Unsupported("unsupported_body", fn.body)
        return self.result(
            fn, deps[0], tuple(sorted(transfers, key=lambda c: (c.span.start, c.span.end)))
        )

    def statement(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        deps: list[frozenset[int]],
        saw_return: list[bool],
    ) -> None:
        count[0] += 1
        if count[0] > MAX_EXPRESSION_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        if kind in {"block", "statement_list"}:
            for child in _children(node):
                self.statement(
                    child, fn, params, locals_, transfers, count, deps, saw_return
                )
            return
        if kind == "return_statement":
            expressions = _children(node)
            if len(expressions) == 1 and expressions[0].type == "expression_list":
                expressions = _children(expressions[0])
            if len(expressions) != 1:
                raise _Unsupported("unsupported_return", _span(node))
            deps[0] |= self.expression(
                expressions[0], fn, params, locals_, transfers, count, 0
            )
            saw_return[0] = True
            return
        if kind == "short_var_declaration":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            lefts = _children(left) if left is not None else []
            rights = _children(right) if right is not None else []
            if (
                len(lefts) != 1
                or lefts[0].type != "identifier"
                or len(rights) != 1
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            binding = self.bindings_by_span.get(_span(lefts[0]))
            if binding is None or binding.type.kind not in {"integer", "boolean"}:
                raise _Unsupported("binding_unavailable", _span(node))
            locals_[binding.id] = self.expression(
                rights[0], fn, params, locals_, transfers, count, 0
            )
            return
        if kind == "if_statement":
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            if (
                node.child_by_field_name("initializer") is not None
                or condition is None
                or consequence is None
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            # The condition is evaluated but its dependencies cannot reach
            # the result: every fragment statement is effect-free.
            self.expression(
                condition, fn, params, locals_, transfers, count, 0
            )
            # Branch-local bindings never escape their scope, matching the
            # compiler — a later reference simply would not resolve.
            # Reassignments of existing names join back by union: the
            # branch may not execute.
            branch = dict(locals_)
            for child in _children(consequence):
                self.statement(
                    child, fn, params, branch, transfers, count, deps,
                    saw_return,
                )
            self._join(locals_, branch, params)
            alternative = node.child_by_field_name("alternative")
            if alternative is not None:
                branch = dict(locals_)
                if alternative.type == "if_statement":
                    self.statement(
                        alternative, fn, params, branch, transfers,
                        count, deps, saw_return,
                    )
                else:
                    for child in _children(alternative):
                        self.statement(
                            child, fn, params, branch, transfers,
                            count, deps, saw_return,
                        )
                self._join(locals_, branch, params)
            return
        if kind == "assignment_statement":
            operator = node.child_by_field_name("operator")
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            lefts = _children(left) if left is not None else []
            rights = _children(right) if right is not None else []
            if (
                operator is None
                or operator.type != "="
                or len(lefts) != 1
                or lefts[0].type != "identifier"
                or len(rights) != 1
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            ref = self.references.get(_span(lefts[0]))
            if ref is None or (
                ref.binding_id not in locals_ and ref.binding_id not in params
            ):
                raise _Unsupported("binding_unavailable", _span(lefts[0]))
            # Reassignment replaces the binding's dependencies; it never
            # declares a new variable. Inside a branch the caller's join
            # unions the new value back as a may-assignment.
            locals_[ref.binding_id] = self.expression(
                rights[0], fn, params, locals_, transfers, count, 0
            )
            return
        if kind == "for_statement":
            body_node = node.child_by_field_name("body")
            clause = next(
                (
                    child
                    for child in node.named_children
                    if child != body_node
                ),
                None,
            )
            if body_node is None or (
                clause is not None and clause.type == "range_clause"
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            # The loop variable and every binding made inside the body are
            # scoped to the loop — none of them escape, matching the compiler.
            scope = dict(locals_)
            if clause is not None and clause.type == "for_clause":
                init = clause.child_by_field_name("initializer")
                if init is not None:
                    self.statement(
                        init, fn, params, scope, transfers, count, deps,
                        saw_return,
                    )
                condition = clause.child_by_field_name("condition")
                if condition is not None:
                    self.expression(
                        condition, fn, params, scope, transfers, count, 0
                    )
                update = clause.child_by_field_name("update")
                if update is not None:
                    operands = _children(update)
                    if update.type not in {
                        "inc_statement",
                        "dec_statement",
                    } or len(operands) != 1 or operands[0].type != "identifier":
                        raise _Unsupported("unsupported_statement", _span(update))
                    ref = self.references.get(_span(operands[0]))
                    if ref is None or (
                        ref.binding_id not in scope
                        and ref.binding_id not in params
                    ):
                        raise _Unsupported("binding_unavailable", _span(update))
            elif clause is not None:
                # `for <expression> { ... }` — a condition-only loop.
                self.expression(clause, fn, params, scope, transfers, count, 0)
            # Iterate the body to a fixed point: a reassignment made on one
            # pass seeds the next, so dependencies propagating across
            # iterations are captured (this is a join, not an unroll — trip
            # counts are never modelled). Every widened entry only gains
            # parameter indexes, so widening is monotone over a bounded
            # universe; the pass cap is a defensive analysis limit.
            passes = 0
            while True:
                mark = len(transfers)
                inner = dict(scope)
                for child in _children(body_node):
                    self.statement(
                        child, fn, params, inner, transfers, count, deps,
                        saw_return,
                    )
                changed = False
                for binding_id, binding_deps in inner.items():
                    if binding_id in scope:
                        if not binding_deps <= scope[binding_id]:
                            scope[binding_id] |= binding_deps
                            changed = True
                    elif binding_id in params:
                        scope[binding_id] = (
                            frozenset({params[binding_id]}) | binding_deps
                        )
                        changed = True
                if not changed:
                    break
                # Keep only the last pass's transfers: argument dependency
                # sets widen across passes and earlier copies are stale.
                del transfers[mark:]
                passes += 1
                if passes > len(scope) * (len(params) + 1):
                    raise _Unsupported("analysis_limit", _span(node))
            # Loop-body reassignments join back by union: the loop may
            # execute zero or many times.
            self._join(locals_, scope, params)
            return
        raise _Unsupported("unsupported_statement", _span(node))

    @staticmethod
    def _join(
        outer: dict[str, frozenset[int]],
        inner: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> None:
        """Union inner-scope reassignments back into the outer environment.

        Bindings created inside the inner scope never escape — only names
        that existed outside (lets or parameters) merge, and their
        dependencies union because the inner code path may not run.
        """
        for binding_id, deps in inner.items():
            if binding_id in outer:
                outer[binding_id] |= deps
            elif binding_id in params:
                # A reassigned parameter keeps its own dependency — the
                # branch may not run.
                outer[binding_id] = frozenset({params[binding_id]}) | deps

    def expression(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        depth: int,
    ) -> frozenset[int]:
        count[0] += 1
        if depth + len(self.active) >= MAX_DEPTH or count[0] > MAX_EXPRESSION_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        children = _children(node)
        if kind in {"int_literal", "rune_literal"}:
            return frozenset()
        if kind in {"identifier", "true", "false"}:
            ref = self.references.get(_span(node))
            # Reassigned names (including parameters) resolve through
            # `locals_` first — their latest dependencies live there.
            if ref is not None and ref.binding_id in locals_:
                return locals_[ref.binding_id]
            if ref is not None and ref.binding_id in params:
                return frozenset({params[ref.binding_id]})
            if ref is not None and ref.kind == "universe" and kind in {"true", "false"}:
                return frozenset()
            raise _Unsupported("non_parameter_reference", _span(node))
        if kind == "parenthesized_expression" and len(children) == 1:
            return self.expression(
                children[0], fn, params, locals_, transfers, count, depth + 1
            )
        if kind in {"binary_expression", "unary_expression"}:
            operator = node.child_by_field_name("operator")
            allowed = _BINARY if kind == "binary_expression" else _UNARY
            if operator is None or operator.type not in allowed:
                raise _Unsupported("unsupported_operator", _span(node))
            deps: frozenset[int] = frozenset()
            for child in children:
                deps |= self.expression(
                    child, fn, params, locals_, transfers, count, depth + 1
                )
            return deps
        if kind == "call_expression":
            call = self.calls.get(_span(node))
            if (
                call is None
                or call.owner != fn.binding_id
                or call.kind != "direct_local"
            ):
                raise _Unsupported("unresolved_or_opaque_call", _span(node))
            arguments_node = node.child_by_field_name("arguments")
            arguments = _children(arguments_node) if arguments_node is not None else []
            if tuple(_span(arg) for arg in arguments) != call.arguments:
                raise _Unsupported("call_mapping_unavailable", _span(node), call.target)
            target = self.functions.get(call.target)
            if target is None or len(arguments) != len(target.parameters):
                raise _Unsupported("callee_unavailable", _span(node), call.target)
            # Even unused arguments are evaluated and must have supported effects.
            actual = tuple(
                self.expression(
                    arg, fn, params, locals_, transfers, count, depth + 1
                )
                for arg in arguments
            )
            callee = self.summarize(call.target)
            if not callee.available:
                reason = (
                    "recursive_call_graph"
                    if any(g.reason == "recursive_call_graph" for g in callee.gaps)
                    else "callee_unsupported"
                )
                raise _Unsupported(reason, _span(node), call.target)
            assert callee.return_dependencies is not None
            result = frozenset(
                i for parameter in callee.return_dependencies for i in actual[parameter]
            )
            transfers.append(CallTransfer(call.span, call.target, actual, result))
            return result
        raise _Unsupported("unsupported_expression", _span(node))


def summarize_go(source: str, snapshot: GoTypeSnapshot) -> GoSummarySet:
    """Compose conservative dependencies only; never infer equality or safety.

    A nonempty set can overapproximate dependence (e.g. x*0 still includes x).
    Empty means parameter-independent in this fragment, not a known constant.
    None means unavailable, never a parameter-independent or effect-free result.
    """
    raw, key = _context(source, snapshot)
    builder = _Builder(source, snapshot, raw, key)
    if len(snapshot.functions) > MAX_FUNCTIONS:
        results = tuple(
            builder.result(f, gaps=(SummaryGap("analysis_limit"),))
            for f in snapshot.functions
        )
    else:
        results = tuple(
            builder.summarize(f.binding_id)
            for f in sorted(snapshot.functions, key=lambda f: f.binding_id)
        )
    return GoSummarySet(key, results)
