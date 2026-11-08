"""Source-mapped explicit normal flow for a deliberately limited Go profile.

Calls are opaque and assumed to return normally. Panic/recovery, concurrency,
deferred execution, switches and labelled jumps are not modelled. Unsupported
syntax produces gaps instead of a misleading partial graph. This is neither a
fixed-point dataflow solver nor a proof of source semantics.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from agent import tree_sitter_extract

PROFILE = "mumei.go-explicit-normal-flow/v1"


@dataclass(frozen=True)
class SourceSpan:
    """Half-open Unicode-codepoint offsets relative to the function body."""

    start: int
    end: int


@dataclass(frozen=True)
class CFGNode:
    node_id: int
    kind: str
    span: SourceSpan | None


@dataclass(frozen=True)
class CFGEdge:
    source: int
    target: int
    kind: str


@dataclass(frozen=True)
class CFGGap:
    reason: str
    span: SourceSpan | None = None


@dataclass(frozen=True)
class ControlFlowGraph:
    source_sha256: str
    nodes: tuple[CFGNode, ...]
    edges: tuple[CFGEdge, ...]
    entry: int = 0
    exit: int = 1
    profile: str = PROFILE

    def successors(self, node_id: int) -> tuple[CFGEdge, ...]:
        return tuple(edge for edge in self.edges if edge.source == node_id)

    def reachable(self) -> frozenset[int]:
        pending = [self.entry]
        seen: set[int] = set()
        adjacency: dict[int, list[int]] = {}
        for edge in self.edges:
            adjacency.setdefault(edge.source, []).append(edge.target)
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                pending.extend(adjacency.get(current, ()))
        return frozenset(seen)


@dataclass(frozen=True)
class CFGConstruction:
    graph: ControlFlowGraph | None
    gaps: tuple[CFGGap, ...] = ()


_SIMPLE = frozenset({"define", "assign", "inc", "dec", "const", "var", "expr"})
_STRUCTURED = frozenset({"if", "for", "range", "block", "return"})


def _span(statement: tree_sitter_extract.Statement) -> SourceSpan:
    return SourceSpan(statement.start, statement.start + len(statement.text))


def _gaps(
    body: str,
    statements: tuple[tree_sitter_extract.Statement, ...],
    in_loop: bool = False,
) -> list[CFGGap]:
    gaps: list[CFGGap] = []
    for statement in statements:
        span = _span(statement)
        if span.start < 0 or body[span.start : span.end] != statement.text:
            gaps.append(CFGGap("source_span_mismatch", span))
        if statement.labeled:
            gaps.append(CFGGap("labelled_statement", span))
        kind = statement.kind
        if kind in {"break", "continue"}:
            if statement.text != kind:
                gaps.append(CFGGap("labelled_jump", span))
            elif not in_loop:
                gaps.append(CFGGap("jump_without_loop", span))
        elif kind not in _SIMPLE | _STRUCTURED:
            gaps.append(CFGGap(f"unsupported_{kind}", span))
        gaps.extend(_gaps(body, statement.init, in_loop))
        gaps.extend(_gaps(body, statement.body, in_loop or kind in {"for", "range"}))
        gaps.extend(_gaps(body, statement.orelse, in_loop))
        gaps.extend(_gaps(body, statement.post, in_loop))
    return gaps


class _Builder:
    def __init__(self) -> None:
        self.nodes = [CFGNode(0, "entry", None), CFGNode(1, "exit", None)]
        self.edges: list[CFGEdge] = []

    def node(self, kind: str, statement: tree_sitter_extract.Statement) -> int:
        node_id = len(self.nodes)
        self.nodes.append(CFGNode(node_id, kind, _span(statement)))
        return node_id

    def edge(self, source: int, target: int, kind: str = "next") -> None:
        self.edges.append(CFGEdge(source, target, kind))

    def sequence(
        self,
        statements: tuple[tree_sitter_extract.Statement, ...],
        following: int,
        loop: tuple[int, int] | None = None,
    ) -> int:
        for statement in reversed(statements):
            kind = statement.kind
            node = self.node(kind, statement)
            if kind == "return":
                self.edge(node, 1, "return")
            elif kind in {"break", "continue"}:
                assert loop is not None
                self.edge(node, loop[0 if kind == "break" else 1], kind)
            elif kind == "if":
                self.edge(node, self.sequence(statement.body, following, loop), "true")
                self.edge(
                    node, self.sequence(statement.orelse, following, loop), "false"
                )
            elif kind in {"for", "range"}:
                post = self.sequence(statement.post, node, loop)
                entry = self.sequence(statement.body, post, (following, post))
                self.edge(node, entry, "true")
                if statement.condition or kind == "range":
                    self.edge(node, following, "false")
            elif kind == "block":
                self.edge(node, self.sequence(statement.body, following, loop))
            else:
                self.edge(node, following)
            following = self.sequence(statement.init, node, loop)
        return following


def _from_tree(body: str, tree: tree_sitter_extract.StatementTree) -> CFGConstruction:
    try:
        gaps = _gaps(body, tree.statements)
        if gaps:
            return CFGConstruction(None, tuple(gaps))
        builder = _Builder()
        builder.edge(0, builder.sequence(tree.statements, 1))
    except RecursionError:
        return CFGConstruction(None, (CFGGap("nesting_limit"),))
    return CFGConstruction(
        ControlFlowGraph(
            hashlib.sha256(body.encode("utf-8")).hexdigest(),
            tuple(builder.nodes),
            tuple(
                sorted(
                    builder.edges,
                    key=lambda edge: (edge.source, edge.target, edge.kind),
                )
            ),
        )
    )


def build_go_cfg(body: str) -> CFGConstruction:
    tree = tree_sitter_extract.extract_statements(body, "go")
    if tree is None:
        return CFGConstruction(None, (CFGGap("syntax_or_parser_unavailable"),))
    return _from_tree(body, tree)
