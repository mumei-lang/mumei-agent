"""Opt-in parameter-dependency summaries, not proofs or audit-grade inputs.

Only a single explicit scalar return expression is modelled. Compiler-resolved
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
        if len(statements) != 1 or statements[0].type != "return_statement":
            raise _Unsupported("unsupported_body", fn.body)
        expressions = _children(statements[0])
        if len(expressions) == 1 and expressions[0].type == "expression_list":
            expressions = _children(expressions[0])
        if len(expressions) != 1:
            raise _Unsupported("unsupported_return", fn.body)
        params = {p.binding_id: i for i, p in enumerate(fn.parameters) if p.binding_id}
        transfers: list[CallTransfer] = []
        count = [0]
        deps = self.expression(expressions[0], fn, params, transfers, count, 0)
        return self.result(
            fn, deps, tuple(sorted(transfers, key=lambda c: (c.span.start, c.span.end)))
        )

    def expression(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
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
            if ref is not None and ref.binding_id in params:
                return frozenset({params[ref.binding_id]})
            if ref is not None and ref.kind == "universe" and kind in {"true", "false"}:
                return frozenset()
            raise _Unsupported("non_parameter_reference", _span(node))
        if kind == "parenthesized_expression" and len(children) == 1:
            return self.expression(children[0], fn, params, transfers, count, depth + 1)
        if kind in {"binary_expression", "unary_expression"}:
            operator = node.child_by_field_name("operator")
            allowed = _BINARY if kind == "binary_expression" else _UNARY
            if operator is None or operator.type not in allowed:
                raise _Unsupported("unsupported_operator", _span(node))
            deps: frozenset[int] = frozenset()
            for child in children:
                deps |= self.expression(child, fn, params, transfers, count, depth + 1)
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
                self.expression(arg, fn, params, transfers, count, depth + 1)
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
