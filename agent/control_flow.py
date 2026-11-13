"""Source-mapped explicit normal flow for a deliberately limited Go profile.

Calls are opaque and assumed to return normally. Panic/recovery, concurrency,
deferred execution, switches and labelled jumps are not modelled. Unsupported
syntax produces gaps instead of a misleading partial graph. This is neither a
proof of source semantics nor a full analysis framework.

`assignment_facts` adds the first bounded fixed-point dataflow over the
graph: per-node name-level "definitely textually assigned on all paths"
and "textually assigned on some path" sets. It is deliberately narrow —
only simple identifier targets of recognized assignment statements count;
selectors, indexes, the blank identifier, scoping/shadowing and mutation
through opaque calls (including `&x` arguments) are not modelled, so the
sets describe declared textual assignment, not memory truth.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
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


_ASSIGNMENT_KINDS = frozenset(
    {"define", "assign", "inc", "dec", "const", "var", "range"}
)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class AssignmentFacts:
    """Name-level assignment sets at one node, read under "if reached".

    `all_paths` names identifiers textually assigned on every path from the
    entry to this node; `some_path` names identifiers textually assigned on
    at least one such path. Unreachable nodes vacuously report the whole
    name universe for `all_paths` and only their own targets for
    `some_path`.
    """

    all_paths: frozenset[str]
    some_path: frozenset[str]


def _walk(
    statements: tuple[tree_sitter_extract.Statement, ...],
) -> tuple[tree_sitter_extract.Statement, ...]:
    out: list[tree_sitter_extract.Statement] = []
    for statement in statements:
        out.append(statement)
        out.extend(_walk(statement.init))
        out.extend(_walk(statement.body))
        out.extend(_walk(statement.orelse))
        out.extend(_walk(statement.post))
    return tuple(out)


def _assigned_names(statement: tree_sitter_extract.Statement) -> frozenset[str]:
    if statement.kind not in _ASSIGNMENT_KINDS:
        return frozenset()
    return frozenset(
        target
        for target in statement.targets
        if target != "_" and _IDENTIFIER.fullmatch(target)
    )


def assignment_facts(
    body: str, graph: ControlFlowGraph
) -> dict[int, AssignmentFacts]:
    """Bounded fixed-point assignment facts over an explicit normal-flow CFG.

    Both directions converge on a finite lattice: `all_paths` descends from
    the name universe (intersection over predecessors) and `some_path`
    ascends from empty (union), each through at most
    `nodes x names` updates, checked against a defensive iteration bound.
    Facts are per program point: they do not decide termination, reach
    calls, fields, elements or shadowed scopes.
    """
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != graph.source_sha256:
        raise ValueError("body does not match the graph source digest")
    tree = tree_sitter_extract.extract_statements(body, "go")
    if tree is None:
        raise ValueError("assignment facts require a parsed Go body")
    by_span = {
        (stmt.start, stmt.start + len(stmt.text)): _assigned_names(stmt)
        for stmt in _walk(tree.statements)
    }
    assigned = {
        node.node_id: (
            by_span.get((node.span.start, node.span.end), frozenset())
            if node.span is not None
            else frozenset()
        )
        for node in graph.nodes
    }
    universe = frozenset().union(*assigned.values()) if assigned else frozenset()
    predecessors: dict[int, list[int]] = defaultdict(list)
    for edge in graph.edges:
        predecessors[edge.target].append(edge.source)
    all_paths = {node.node_id: universe for node in graph.nodes}
    all_paths[graph.entry] = frozenset()
    some_path = {node.node_id: frozenset() for node in graph.nodes}
    iteration_bound = 4 * (len(graph.nodes) + 1) * (len(universe) + 1) + 1
    for _ in range(iteration_bound):
        changed = False
        for node in graph.nodes:
            incoming = predecessors.get(node.node_id, ())
            if node.node_id == graph.entry:
                meet_all: frozenset[str] = frozenset()
                join_some: frozenset[str] = frozenset()
            else:
                meet_all = (
                    frozenset.intersection(*(all_paths[p] for p in incoming))
                    if incoming
                    else universe
                )
                join_some = frozenset().union(*(some_path[p] for p in incoming))
            new_all = meet_all | assigned[node.node_id]
            new_some = join_some | assigned[node.node_id]
            if (
                new_all != all_paths[node.node_id]
                or new_some != some_path[node.node_id]
            ):
                all_paths[node.node_id] = new_all
                some_path[node.node_id] = new_some
                changed = True
        if not changed:
            return {
                node.node_id: AssignmentFacts(
                    all_paths[node.node_id], some_path[node.node_id]
                )
                for node in graph.nodes
            }
    raise ValueError("assignment facts did not converge")


@dataclass(frozen=True)
class UnassignedUse:
    """A name used at a node that is not assigned on every path reaching it.

    A heuristic hint over `assignment_facts`, not a defect verdict: the
    name is flagged only when it is a simple identifier assigned somewhere
    in the body but missing from the node's `all_paths` pre-state.
    """

    node_id: int
    name: str
    span: SourceSpan | None


def _use_text(statement: tree_sitter_extract.Statement) -> str:
    if statement.kind in {"if", "for"}:
        return statement.condition
    if statement.kind in {"range", "return", "expr", "define", "assign", "const", "var"}:
        return " ".join(statement.values)
    if statement.kind in {"inc", "dec"}:
        return " ".join(statement.targets)
    return ""


def unassigned_uses(
    body: str, graph: ControlFlowGraph
) -> tuple[UnassignedUse, ...]:
    """Names used at a node without a definite assignment reaching it.

    Reports `name` at `node` when `name` is textually assigned somewhere in
    the body yet absent from the node's `all_paths` pre-state — a possibly-
    unassigned read, conservatively limited to recognized identifiers. It
    does not model fields, elements, calls, shadowing or closures, and a
    finding is a hint for the host's own dataflow, not a defect verdict.
    """
    facts = assignment_facts(body, graph)
    tree = tree_sitter_extract.extract_statements(body, "go")
    assert tree is not None  # assignment_facts already re-parsed the body
    by_span = {
        (stmt.start, stmt.start + len(stmt.text)): stmt
        for stmt in _walk(tree.statements)
    }
    universe = frozenset().union(
        *(fact.some_path for fact in facts.values())
    )
    predecessors: dict[int, list[int]] = defaultdict(list)
    for edge in graph.edges:
        predecessors[edge.target].append(edge.source)
    findings: list[UnassignedUse] = []
    for node in graph.nodes:
        if node.span is None:
            continue
        statement = by_span.get((node.span.start, node.span.end))
        if statement is None:
            continue
        incoming = predecessors.get(node.node_id, ())
        if node.node_id == graph.entry or not incoming:
            pre = frozenset() if node.node_id == graph.entry else universe
        else:
            pre = frozenset.intersection(
                *(facts[p].all_paths for p in incoming)
            )
        for name in sorted(_IDENTIFIER.findall(_use_text(statement))):
            if name in universe and name not in pre:
                findings.append(UnassignedUse(node.node_id, name, node.span))
    return tuple(findings)
