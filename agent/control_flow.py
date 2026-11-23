"""Source-mapped explicit normal flow for a deliberately limited Go profile.

Calls are opaque and assumed to return normally. Panic/recovery, concurrency
and deferred execution are not modelled; expression and
type switches are exclusive alternatives with implicit break and a
type-less match model (a type switch with no default can fall
through), ``select`` admits its communication cases as the same
kind of alternative and blocks when it has no ``default``, a terminal
``fallthrough`` in a non-final case clause edges into
the next clause's body (any other position stays a declared gap),
labelled ``break``/``continue`` resolve only against enclosing
labelled loops, ``goto`` edges to the named statement's entry
anywhere in the body (labels are function-scoped by name — the
jump-legality rules Go places on declarations and blocks are not
checked), and ``panic``/``os.Exit``-style terminating calls end
normal flow at the exit (deferred calls and ``recover`` stay
unmodelled). Unsupported
syntax produces gaps instead of a misleading partial graph. This is neither a
proof of source semantics nor a full analysis framework.

`assignment_facts` adds the first bounded fixed-point dataflow over the
graph: per-node name-level "definitely textually assigned on all paths"
and "textually assigned on some path" sets. It is deliberately narrow —
only simple identifier targets of recognized assignment statements count;
selectors, indexes, the blank identifier, scoping/shadowing and mutation
through opaque calls (including `&x` arguments) are not modelled, so the
sets describe declared textual assignment, not memory truth.

`unused_assignments` preserves its name-wide unread-name hints and adds
backward fixed-point liveness for individual stores on the explicit CFG.
This remains a name-based hint, not a defect verdict: fields, elements,
aliasing and full lexical binding identity are not modelled. Liveness
additions require a store span inside and after the sole declaration's
scope, and exclude unreachable, multiply declared, closure-mentioned,
address-taken and otherwise unreliable names. Bare returns and grouped
var/const declarations read all tracked names conservatively; range headers
do not kill targets because their loops may execute zero times.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, replace

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


_SIMPLE = frozenset(
    {"define", "assign", "inc", "dec", "const", "var", "expr", "go", "defer"}
)
_STRUCTURED = frozenset(
    {"if", "for", "range", "block", "return", "terminate", "switch"}
)


def _span(statement: tree_sitter_extract.Statement) -> SourceSpan:
    return SourceSpan(statement.start, statement.start + len(statement.text))


def _collect_labels(
    statements: tuple[tree_sitter_extract.Statement, ...],
) -> frozenset[str]:
    """Every label a statement carries, at any depth.

    Go labels are function-scoped, so a ``goto`` resolves against the
    whole body's label set — not only enclosing statements.
    """
    labels: set[str] = set()
    for statement in statements:
        if statement.labeled and statement.label:
            labels.add(statement.label)
        for group in (
            statement.init,
            statement.body,
            statement.orelse,
            statement.post,
        ):
            labels.update(_collect_labels(group))
    return frozenset(labels)


def _gaps(
    body: str,
    statements: tuple[tree_sitter_extract.Statement, ...],
    in_loop: bool = False,
    in_break: bool = False,
    labels: frozenset[str] = frozenset(),
    goto_labels: frozenset[str] = frozenset(),
) -> list[CFGGap]:
    gaps: list[CFGGap] = []
    for statement in statements:
        span = _span(statement)
        if span.start < 0 or body[span.start : span.end] != statement.text:
            gaps.append(CFGGap("source_span_mismatch", span))
        kind = statement.kind
        body_labels = labels
        if statement.labeled:
            if kind in {"for", "range"} and statement.label:
                # A label on a loop is a jump target for its body.
                body_labels = labels | {statement.label}
            # A label on any statement is also a ``goto`` target —
            # it is collected function-wide by ``_collect_labels``.
        if kind in {"break", "continue"}:
            jump_label = _jump_label(statement.text)
            if jump_label == "":
                if kind == "continue" and not in_loop:
                    gaps.append(CFGGap("jump_without_loop", span))
                elif kind == "break" and not (in_loop or in_break):
                    gaps.append(CFGGap("jump_without_loop", span))
            elif jump_label is not None:
                if jump_label not in labels:
                    gaps.append(CFGGap("unresolved_label", span))
            else:
                gaps.append(CFGGap("labelled_jump", span))
        elif kind == "goto":
            jump_label = _jump_label(statement.text)
            if jump_label is not None and jump_label != "":
                if jump_label not in goto_labels:
                    gaps.append(CFGGap("unresolved_label", span))
            else:
                gaps.append(CFGGap("labelled_jump", span))
        elif kind == "switch":
            if statement.operator in {"select", "type"}:
                # Type cases carry their types in the clause text, not
                # ``values`` — the extractor leaves ``values`` empty for
                # them, so only the case kind is checked.
                for case in statement.body:
                    if case.kind not in {"case", "default"}:
                        gaps.append(
                            CFGGap("unsupported_case", _span(case))
                        )
            else:
                for case in statement.body:
                    if case.kind == "case" and not case.values:
                        # A value-less case the extractor could not
                        # classify — never silently modelled.
                        gaps.append(CFGGap("unsupported_case", _span(case)))
        elif kind not in _SIMPLE | _STRUCTURED:
            gaps.append(CFGGap(f"unsupported_{kind}", span))
        gaps.extend(
            _gaps(body, statement.init, in_loop, in_break, labels, goto_labels)
        )
        if kind == "switch":
            cases = statement.body
            for index, case in enumerate(cases):
                # Case bodies may break the switch; continue still
                # needs an enclosing loop. A terminal fallthrough in a
                # non-final clause is modelled, so it is not walked as
                # an unsupported statement. Select and type-switch
                # cases never carry fallthrough — one there stays
                # unsupported.
                stmts = case.body
                if (
                    statement.operator not in {"select", "type"}
                    and stmts
                    and stmts[-1].kind == "fallthrough"
                    and index < len(cases) - 1
                ):
                    stmts = stmts[:-1]
                gaps.extend(
                    _gaps(body, stmts, in_loop, True, labels, goto_labels)
                )
        else:
            in_loop_body = in_loop or kind in {"for", "range"}
            gaps.extend(
                _gaps(
                    body,
                    statement.body,
                    in_loop_body,
                    in_break or kind in {"for", "range"},
                    body_labels,
                    goto_labels,
                )
            )
        gaps.extend(
            _gaps(
                body, statement.orelse, in_loop, in_break, labels, goto_labels
            )
        )
        gaps.extend(
            _gaps(
                body, statement.post, in_loop, in_break, labels, goto_labels
            )
        )
    return gaps


class _Builder:
    def __init__(self) -> None:
        self.nodes = [CFGNode(0, "entry", None), CFGNode(1, "exit", None)]
        self.edges: list[CFGEdge] = []
        # ``goto`` resolution: label name → the labelled statement's
        # entry node, filled as statements finish building. Backward
        # jumps reach names not yet registered, so they queue here and
        # are wired once the whole body has been sequenced.
        self.goto_targets: dict[str, int] = {}
        self.pending_gotos: list[tuple[int, str]] = []

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
        labels: dict[str, tuple[int, int]] | None = None,
    ) -> int:
        labels = {} if labels is None else labels
        for statement in reversed(statements):
            kind = statement.kind
            node = self.node(kind, statement)
            if kind == "return":
                self.edge(node, 1, "return")
            elif kind == "terminate":
                self.edge(node, 1, "terminate")
            elif kind in {"break", "continue"}:
                jump_label = _jump_label(statement.text)
                target = (
                    loop
                    if not jump_label
                    else labels.get(jump_label)
                )
                assert target is not None
                self.edge(node, target[0 if kind == "break" else 1], kind)
            elif kind == "goto":
                label = _jump_label(statement.text)
                assert label is not None and label != ""
                target = self.goto_targets.get(label)
                if target is None:
                    self.pending_gotos.append((node, label))
                else:
                    self.edge(node, target, "goto")
            elif kind == "if":
                self.edge(
                    node,
                    self.sequence(statement.body, following, loop, labels),
                    "true",
                )
                self.edge(
                    node,
                    self.sequence(statement.orelse, following, loop, labels),
                    "false",
                )
            elif kind == "switch":
                # Case bodies are exclusive alternatives ending at the
                # switch's following; break inside one exits the switch
                # while continue still targets an enclosing loop.
                inner = (following, loop[1] if loop else following)
                cases = statement.body
                # Build case bodies back-to-front so a terminal
                # `fallthrough` in a non-final clause can edge into the
                # next clause's body entry.
                entries = [0] * len(cases)
                for index in range(len(cases) - 1, -1, -1):
                    stmts = cases[index].body
                    # Select and type switches reject fallthrough in
                    # ``_gaps`` already; only expression switches can
                    # reach this modelled branch.
                    if (
                        stmts
                        and stmts[-1].kind == "fallthrough"
                        and index < len(cases) - 1
                    ):
                        jump = self.node(stmts[-1].kind, stmts[-1])
                        self.edge(
                            jump, entries[index + 1], "fallthrough"
                        )
                        entries[index] = self.sequence(
                            stmts[:-1], jump, inner, labels
                        )
                    else:
                        entries[index] = self.sequence(
                            stmts, following, inner, labels
                        )
                for index, case in enumerate(cases):
                    case_node = self.node(case.kind, case)
                    self.edge(node, case_node, "case")
                    self.edge(case_node, entries[index])
                if (
                    not any(case.kind == "default" for case in cases)
                    and statement.operator != "select"
                ):
                    # A select with no default blocks until a case is
                    # ready — it has no fall-through edge.
                    self.edge(node, following)
            elif kind in {"for", "range"}:
                post = self.sequence(statement.post, node, loop, labels)
                target = (following, post)
                body_labels = labels
                if statement.labeled and statement.label:
                    body_labels = {**labels, statement.label: target}
                entry = self.sequence(
                    statement.body, post, target, body_labels
                )
                self.edge(node, entry, "true")
                if statement.condition or kind == "range":
                    self.edge(node, following, "false")
            elif kind == "block":
                self.edge(
                    node, self.sequence(statement.body, following, loop, labels)
                )
            else:
                self.edge(node, following)
            following = self.sequence(statement.init, node, loop, labels)
            if statement.labeled and statement.label:
                # The labelled statement's entry is the head of its
                # init chain (or the node itself when it has none).
                self.goto_targets[statement.label] = following
        return following


def _from_tree(body: str, tree: tree_sitter_extract.StatementTree) -> CFGConstruction:
    try:
        gaps = _gaps(
            body,
            tree.statements,
            goto_labels=_collect_labels(tree.statements),
        )
        if gaps:
            return CFGConstruction(None, tuple(gaps))
        builder = _Builder()
        builder.edge(0, builder.sequence(tree.statements, 1))
        for node_id, label in builder.pending_gotos:
            # ``_gaps`` already required every label, so this can only
            # be missed by a build-order surprise — keep it a gap
            # rather than dropping the edge silently.
            target = builder.goto_targets.get(label)
            if target is None:
                return CFGConstruction(
                    None, (CFGGap("unresolved_label"),)
                )
            builder.edge(node_id, target, "goto")
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

# Go labels are identifiers, and Go identifiers are Unicode — ``goto 終了``
# is valid. ``[^\W\d]`` is a Unicode letter or ``_``.
_GO_LABEL = re.compile(r"[^\W\d]\w*", re.UNICODE)
_COMMENT = re.compile(r"//[^\n]*|/\*(?:[^*]|\*(?!/))*\*/")


def _jump_label(text: str) -> str | None:
    """The label operand of ``break``/``continue``/``goto``.

    Returns ``""`` for the bare (unlabelled) form, the label name for a
    well-formed labelled jump — comments between the keyword and the
    label are stripped — and ``None`` when the operand is malformed.
    """
    parts = _COMMENT.sub(" ", text).split()
    if len(parts) == 1:
        return ""
    if len(parts) == 2 and _GO_LABEL.fullmatch(parts[1]):
        return parts[1]
    return None


@dataclass(frozen=True)
class AssignmentFacts:
    """Name-level assignment sets at one node, read under "if reached".

    `all_paths` names identifiers textually assigned on every path from the
    entry to this node; `some_path` names identifiers textually assigned on
    at least one such path. Bare `var` declarations kill an earlier tracked
    assignment without generating one. Entry names seed both sets.
    Unreachable nodes vacuously report the remaining name universe for
    `all_paths` and only their own assignment targets for `some_path`.
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
    if statement.kind == "var" and all(
        value == "" for value in statement.values
    ):
        return frozenset()
    # "case" joins for `v := <-ch` / `v, ok := <-ch` select
    # communication cases: the extractor puts the bound names in
    # `targets`. Expression cases never carry targets, so widening
    # the kind set changes nothing for them.
    if statement.kind not in _ASSIGNMENT_KINDS | {"case"}:
        return frozenset()
    return frozenset(
        target
        for target in statement.targets
        if target != "_" and _IDENTIFIER.fullmatch(target)
    )


def _declared_names(
    statement: tree_sitter_extract.Statement,
) -> frozenset[str]:
    if statement.kind != "var" or not all(
        value == "" for value in statement.values
    ):
        return frozenset()
    return frozenset(
        target
        for target in statement.targets
        if target != "_" and _IDENTIFIER.fullmatch(target)
    )


def assignment_facts(
    body: str,
    graph: ControlFlowGraph,
    *,
    entry_assigned: frozenset[str] = frozenset(),
) -> dict[int, AssignmentFacts]:
    """Bounded fixed-point assignment facts over an explicit normal-flow CFG.

    Both directions converge on a finite lattice: `all_paths` descends from
    the name universe (intersection over predecessors) and `some_path`
    ascends from empty (union), each through at most
    `nodes x names` updates, checked against a defensive iteration bound.
    `entry_assigned` seeds both facts before the body. Bare `var`
    declarations kill previous facts for their names without generating
    assignments. Facts are per program point: they do not decide
    termination, reach calls, fields, elements or shadowed scopes.
    """
    if not isinstance(entry_assigned, frozenset) or any(
        not isinstance(name, str) for name in entry_assigned
    ):
        raise ValueError("entry_assigned must be a frozenset of strings")
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != graph.source_sha256:
        raise ValueError("body does not match the graph source digest")
    tree = tree_sitter_extract.extract_statements(body, "go")
    if tree is None:
        raise ValueError("assignment facts require a parsed Go body")
    walked = _walk(tree.statements)
    assigned_by_span = {
        (stmt.start, stmt.start + len(stmt.text)): _assigned_names(stmt)
        for stmt in walked
    }
    declared_by_span = {
        (stmt.start, stmt.start + len(stmt.text)): _declared_names(stmt)
        for stmt in walked
    }
    assigned: dict[int, frozenset[str]] = {}
    declared: dict[int, frozenset[str]] = {}
    for node in graph.nodes:
        span = (
            (node.span.start, node.span.end)
            if node.span is not None
            else None
        )
        assigned[node.node_id] = (
            assigned_by_span.get(span, frozenset())
            if span is not None
            else frozenset()
        )
        declared[node.node_id] = (
            declared_by_span.get(span, frozenset())
            if span is not None
            else frozenset()
        )
    universe = entry_assigned | frozenset().union(
        *assigned.values(), *declared.values()
    )
    predecessors: dict[int, list[int]] = defaultdict(list)
    for edge in graph.edges:
        predecessors[edge.target].append(edge.source)
    all_paths = {node.node_id: universe for node in graph.nodes}
    all_paths[graph.entry] = entry_assigned
    some_path = {node.node_id: frozenset() for node in graph.nodes}
    some_path[graph.entry] = entry_assigned
    iteration_bound = 4 * (len(graph.nodes) + 1) * (len(universe) + 1) + 1
    for _ in range(iteration_bound):
        changed = False
        for node in graph.nodes:
            incoming = predecessors.get(node.node_id, ())
            if node.node_id == graph.entry:
                meet_all = entry_assigned
                join_some = entry_assigned
            else:
                meet_all = (
                    frozenset.intersection(*(all_paths[p] for p in incoming))
                    if incoming
                    else universe
                )
                join_some = frozenset().union(*(some_path[p] for p in incoming))
            new_all = (
                meet_all - declared[node.node_id]
            ) | assigned[node.node_id]
            new_some = (
                join_some - declared[node.node_id]
            ) | assigned[node.node_id]
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
    name is flagged only when it is a simple identifier assigned or
    declared somewhere in the body but missing from the node's `all_paths`
    pre-state. `definite` is true when the name is also missing from the
    node's `some_path` pre-state, so no modelled path can deliver it to
    this use.
    """

    node_id: int
    name: str
    span: SourceSpan | None
    definite: bool = False


def _use_text(statement: tree_sitter_extract.Statement) -> str:
    if statement.kind in {"if", "for", "switch"}:
        return statement.condition
    if statement.kind == "case":
        return " ".join(statement.values)
    if statement.kind in {"range", "return", "expr", "define", "const",
                          "var", "go", "defer"}:
        return " ".join(statement.values)
    if statement.kind == "assign":
        # Compound targets (x.f, a[i], *p) are reads of every identifier
        # inside them: the root object and index/key operands must exist
        # before the write. Field names may be over-counted — declared.
        roots = " ".join(
            target
            for target in statement.targets
            if not _IDENTIFIER.fullmatch(target)
        )
        return " ".join(statement.values) + " " + roots
    if statement.kind in {"inc", "dec"}:
        return " ".join(statement.targets)
    return ""


def _value_read_names(
    statement: tree_sitter_extract.Statement,
) -> frozenset[str]:
    use_text = _use_text(statement)
    fallback = frozenset(_IDENTIFIER.findall(use_text))
    wrapped = (
        "package p\nfunc _() {\n"
        f"_ = []any{{{use_text}}}\n"
        "}\n"
    )
    try:
        tree, source_bytes = tree_sitter_extract.parse(wrapped, "go")
    except Exception:
        return fallback
    if tree is None or source_bytes is None or tree.root_node.has_error:
        return fallback

    names: set[str] = set()

    def collect(node) -> None:
        if node.type == "func_literal":
            return
        if node.type == "identifier":
            parent = node.parent
            if parent is not None and parent.type == "unary_expression":
                operator = parent.child_by_field_name("operator")
                operand = parent.child_by_field_name("operand")
                if (
                    operator is not None
                    and operator.text == b"&"
                    and operand is not None
                    and operand.start_byte == node.start_byte
                    and operand.end_byte == node.end_byte
                ):
                    return
            name = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
            if name != "_":
                names.add(name)
        for child in node.named_children:
            collect(child)

    collect(tree.root_node)
    return frozenset(names)


def _liveness_reads(
    statement: tree_sitter_extract.Statement,
    tracked_names: frozenset[str],
) -> frozenset[str]:
    reads = _value_read_names(statement)
    if statement.kind == "return" and not statement.values:
        reads |= tracked_names
    if statement.kind in {"var", "const"} and not statement.targets:
        reads |= tracked_names
    if statement.kind == "assign" and statement.operator not in {"", "="}:
        reads |= frozenset(
            target
            for target in statement.targets
            if _IDENTIFIER.fullmatch(target)
        )
    if statement.kind == "terminate":
        reads |= _value_read_names(replace(statement, kind="expr"))
    if statement.kind in {"case", "range"}:
        targets = tuple(
            target
            for target in statement.targets
            if not _IDENTIFIER.fullmatch(target)
        )
        reads |= _value_read_names(
            replace(
                statement,
                kind="assign",
                targets=targets,
                values=(),
            )
        )
    return reads


def _liveness_kills(
    statement: tree_sitter_extract.Statement,
) -> frozenset[str]:
    if statement.kind == "range":
        return frozenset()
    return _assigned_names(statement) | _declared_names(statement)


def unassigned_uses(
    body: str,
    graph: ControlFlowGraph,
    *,
    entry_assigned: frozenset[str] = frozenset(),
) -> tuple[UnassignedUse, ...]:
    """Names used at a node without a definite assignment reaching it.

    Reports `name` at `node` when it is textually assigned or declared
    somewhere in the body yet absent from the node's `all_paths`
    pre-state — a possibly-unassigned read, conservatively limited to
    recognized identifiers. Bare `var` declarations are tracked as
    declarations that kill earlier facts; `entry_assigned` seeds values
    available before the body. The `definite` flag marks the stronger
    class: the name is absent from the `some_path` pre-state too, so no
    modelled path can deliver it. It does not model fields, elements,
    calls, shadowing or closures; names the extractor marks unreliable
    (assigned inside a closure or address-taken) can still be flagged
    but are never promoted to `definite`. A finding is a hint for the
    host's own dataflow, not a defect verdict.
    """
    facts = assignment_facts(body, graph, entry_assigned=entry_assigned)
    tree = tree_sitter_extract.extract_statements(body, "go")
    assert tree is not None  # assignment_facts already re-parsed the body
    unreliable = tree.closure_assigned | tree.address_taken
    walked = _walk(tree.statements)
    by_span = {
        (stmt.start, stmt.start + len(stmt.text)): stmt
        for stmt in walked
    }
    universe = frozenset().union(
        *(
            _assigned_names(statement) | _declared_names(statement)
            for statement in walked
        )
    )
    predecessors: dict[int, list[int]] = defaultdict(list)
    for edge in graph.edges:
        predecessors[edge.target].append(edge.source)
    # Only nodes reachable from the entry can feed a use — statements a
    # ``goto`` jumps over still model their own assignments, so without
    # this filter a dead ``x = 1`` would leak ``x`` into a live
    # ``some_path`` pre-state and hide a definite unassigned use.
    reachable = graph.reachable()
    findings: list[UnassignedUse] = []
    for node in graph.nodes:
        if node.span is None:
            continue
        statement = by_span.get((node.span.start, node.span.end))
        if statement is None:
            continue
        incoming = [
            pred
            for pred in predecessors.get(node.node_id, ())
            if pred in reachable
        ]
        if node.node_id == graph.entry:
            pre = entry_assigned
            pre_some = entry_assigned
        elif not incoming:
            pre = universe
            pre_some = frozenset()
        else:
            pre = frozenset.intersection(
                *(facts[p].all_paths for p in incoming)
            )
            pre_some = frozenset().union(
                *(facts[p].some_path for p in incoming)
            )
        for name in sorted(_value_read_names(statement)):
            if name in universe and name not in pre:
                findings.append(
                    UnassignedUse(
                        node.node_id,
                        name,
                        node.span,
                        definite=name not in pre_some
                        and name not in unreliable,
                    )
                )
    return tuple(findings)


@dataclass(frozen=True)
class UnusedAssignment:
    """A name assigned at a node whose store is not observed by a later read.

    A heuristic hint, not a defect verdict. It preserves the legacy
    name-wide hint for identifiers never textually read, and adds
    store-level CFG-liveness hints only for reachable stores that fall
    within and after their sole declaration's scope. The liveness addition
    excludes names that occur in function literals, are address-taken, or
    are otherwise unreliable.
    """

    node_id: int
    name: str
    span: SourceSpan | None


def unused_assignments(
    body: str, graph: ControlFlowGraph
) -> tuple[UnusedAssignment, ...]:
    """Return name-wide unread targets and conservatively dead stores.

    The legacy name-granularity hint reports every recognized simple
    identifier target that has no textual use anywhere in the body,
    including reads in unreachable code and function literals. For names
    that are read, a backward fixed-point analysis over the explicit CFG
    additionally reports a store when its name is not live out of that
    node. These liveness additions require a reachable store and exactly
    one declaration in the body (including short declarations, range and
    select bindings, `var`/`const` specs, type-switch bindings and
    function-literal parameters); the store's span must lie within and
    start at or after that declaration's scope. They exclude names
    mentioned in any function literal, address-taken names and the
    extractor's unreliable names. Bare returns and grouped var/const
    declarations read all tracked names conservatively. The analysis is
    name-based: it does not model fields, elements, aliasing or full
    lexical binding identity. Range headers do not kill targets because
    their loops may execute zero times.
    Every result is a hint for the host's analysis, not a defect verdict.
    """
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != graph.source_sha256:
        raise ValueError("body does not match the graph source digest")
    tree = tree_sitter_extract.extract_statements(body, "go")
    if tree is None:
        raise ValueError("unused assignments require a parsed Go body")
    walked = _walk(tree.statements)
    used = {
        name
        for statement in walked
        for name in _IDENTIFIER.findall(_use_text(statement))
    }
    by_span = {
        (stmt.start, stmt.start + len(stmt.text)): stmt for stmt in walked
    }
    declaration_sites, function_literal_names, syntax_address_taken = (
        _body_declaration_scopes_and_function_literal_names(body)
    )
    unreliable = (
        tree.closure_assigned | tree.address_taken | syntax_address_taken
    )
    statements_by_node = {
        node.node_id: by_span.get((node.span.start, node.span.end))
        for node in graph.nodes
        if node.span is not None
    }
    tracked_names = frozenset(used) | frozenset(
        name
        for statement in walked
        for name in _assigned_names(statement)
    )
    reads_by_node: dict[int, frozenset[str]] = {}
    kills_by_node: dict[int, frozenset[str]] = {}
    for node_id, statement in statements_by_node.items():
        if statement is None:
            reads_by_node[node_id] = tracked_names
        else:
            reads_by_node[node_id] = _liveness_reads(statement, tracked_names)
            kills_by_node[node_id] = _liveness_kills(statement)
    read_anywhere = frozenset().union(*reads_by_node.values())
    successors: dict[int, list[int]] = defaultdict(list)
    for edge in graph.edges:
        successors[edge.source].append(edge.target)
    live_in = {node.node_id: frozenset() for node in graph.nodes}
    live_out = {node.node_id: frozenset() for node in graph.nodes}
    while True:
        changed = False
        for node in reversed(graph.nodes):
            outgoing = frozenset().union(
                *(live_in[successor] for successor in successors[node.node_id])
            )
            incoming = reads_by_node.get(node.node_id, frozenset()) | (
                outgoing - kills_by_node.get(node.node_id, frozenset())
            )
            if outgoing != live_out[node.node_id] or incoming != live_in[node.node_id]:
                live_out[node.node_id] = outgoing
                live_in[node.node_id] = incoming
                changed = True
        if not changed:
            break

    reachable = graph.reachable()
    findings: list[UnusedAssignment] = []
    for node in graph.nodes:
        if node.span is None:
            continue
        statement = statements_by_node.get(node.node_id)
        if statement is None:
            continue
        for name in sorted(_assigned_names(statement)):
            if name not in used or (
                node.node_id in reachable
                and name in read_anywhere
                and len(declaration_sites.get(name, ())) == 1
                and any(
                    scope.start <= node.span.start
                    and node.span.end <= scope.end
                    for scope in declaration_sites[name][0].spans
                )
                and name not in function_literal_names
                and name not in unreliable
                and name not in live_out[node.node_id]
            ):
                findings.append(UnusedAssignment(node.node_id, name, node.span))
    return tuple(findings)


@dataclass(frozen=True)
class _DeclarationSite:
    spans: tuple[SourceSpan, ...]


def _body_declaration_scopes_and_function_literal_names(
    body: str,
) -> tuple[
    dict[str, tuple[_DeclarationSite, ...]],
    frozenset[str],
    frozenset[str],
]:
    prefix = tree_sitter_extract._GO_BODY_PREFIX
    wrapped = f"{prefix}{body}\n}}\n"
    syntax_tree, source_bytes = tree_sitter_extract.parse(wrapped, "go")
    if syntax_tree is None or source_bytes is None or syntax_tree.root_node.has_error:
        return {}, frozenset(), frozenset()

    offsets = tree_sitter_extract._char_offsets(source_bytes)
    body_start = len(prefix)
    declarations: dict[str, list[_DeclarationSite]] = defaultdict(list)
    function_literal_names: set[str] = set()
    address_taken_names: set[str] = set()

    def body_offset(byte_offset: int) -> int:
        return max(0, min(len(body), offsets[byte_offset] - body_start))

    def add_declaration(
        name_node,
        declaration_start: int,
        scope_ends: tuple[int, ...],
    ) -> None:
        if name_node.type != "identifier":
            return
        name = source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")
        if name != "_":
            start = body_offset(declaration_start)
            declarations[name].append(
                _DeclarationSite(
                    tuple(
                        SourceSpan(start, body_offset(scope_end))
                        for scope_end in scope_ends
                    )
                )
            )

    def lexical_scope(node):
        current = node.parent
        while current is not None:
            if current.type in {
                "block",
                "communication_case",
                "default_case",
                "expression_case",
                "type_case",
            }:
                return current
            current = current.parent
        return None

    def short_declaration_scope(node):
        current = node.parent
        while current is not None:
            if current.type in {
                "block",
                "communication_case",
                "default_case",
                "expression_case",
                "type_case",
            }:
                return current
            if current.type in {
                "expression_switch_statement",
                "if_statement",
                "type_switch_statement",
            }:
                return current
            if current.type == "for_clause":
                return current.parent
            current = current.parent
        return None

    def declaration_scope(node, scope) -> tuple[int, ...]:
        if scope is None:
            return (node.end_byte,)
        return (scope.end_byte,)

    stack = [syntax_tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "short_var_declaration":
            left = node.child_by_field_name("left")
            if left is not None:
                scope = short_declaration_scope(node)
                for target in left.named_children:
                    add_declaration(
                        target,
                        node.start_byte,
                        declaration_scope(node, scope),
                    )
        elif node.type == "range_clause":
            if any(child.type == ":=" for child in node.children):
                left = node.child_by_field_name("left")
                if left is not None:
                    owner = node.parent
                    if owner is None or owner.type != "for_statement":
                        owner = node
                    for target in left.named_children:
                        add_declaration(
                            target,
                            owner.start_byte,
                            (owner.end_byte,),
                        )
        elif node.type == "receive_statement":
            if any(child.type == ":=" for child in node.children):
                left = node.child_by_field_name("left")
                if left is not None:
                    owner = node.parent
                    if owner is None or owner.type != "communication_case":
                        owner = node
                    for target in left.named_children:
                        add_declaration(
                            target,
                            owner.start_byte,
                            (owner.end_byte,),
                        )
        elif node.type in {"var_spec", "const_spec"}:
            declaration = node.parent
            if declaration is None or declaration.type not in {
                "const_declaration",
                "var_declaration",
            }:
                declaration = node
            scope = lexical_scope(node)
            for name_node in node.children_by_field_name("name"):
                add_declaration(
                    name_node,
                    declaration.start_byte,
                    declaration_scope(node, scope),
                )
        elif node.type == "type_switch_statement":
            alias = node.child_by_field_name("alias")
            if alias is not None:
                case_ends = tuple(
                    child.end_byte
                    for child in node.named_children
                    if child.type in {"default_case", "type_case"}
                )
                for name_node in alias.named_children:
                    add_declaration(
                        name_node,
                        alias.start_byte,
                        case_ends,
                    )
        elif node.type == "unary_expression":
            operator = node.child_by_field_name("operator")
            operand = node.child_by_field_name("operand")
            if operator is not None and operator.text == b"&":
                while operand is not None and operand.type == "parenthesized_expression":
                    operands = [
                        child
                        for child in operand.named_children
                        if child.type != "comment"
                    ]
                    operand = operands[0] if len(operands) == 1 else None
                if operand is not None and operand.type == "identifier":
                    address_taken_names.add(
                        source_bytes[
                            operand.start_byte : operand.end_byte
                        ].decode("utf-8")
                    )
        elif node.type == "func_literal":
            literal_stack = [node]
            while literal_stack:
                literal_node = literal_stack.pop()
                if literal_node.type == "identifier":
                    function_literal_names.add(
                        source_bytes[
                            literal_node.start_byte : literal_node.end_byte
                        ].decode("utf-8")
                    )
                literal_stack.extend(literal_node.named_children)

            parameters = node.child_by_field_name("parameters")
            if parameters is not None:
                for parameter in parameters.named_children:
                    if parameter.type in {
                        "parameter_declaration",
                        "variadic_parameter_declaration",
                    }:
                        for name_node in parameter.children_by_field_name("name"):
                            add_declaration(
                                name_node,
                                node.start_byte,
                                (node.end_byte,),
                            )
        stack.extend(node.named_children)

    return (
        {name: tuple(sites) for name, sites in declarations.items()},
        frozenset(function_literal_names),
        frozenset(address_taken_names),
    )


@dataclass(frozen=True)
class UnreachableStatement:
    """A mapped statement no normal-flow path from the entry reaches.

    A structural hint over the explicit CFG, not dead-code proof: the
    normal-flow profile's gaps still apply, and reachability says nothing
    about whether the code would have executed had it been reachable.
    """

    node_id: int
    kind: str
    span: SourceSpan | None


def unreachable_statements(
    graph: ControlFlowGraph,
) -> tuple[UnreachableStatement, ...]:
    """Statements unreachable from the entry under normal-flow edges.

    Flags every span-carrying node outside `graph.reachable()`. Syntactic
    only — it cannot see unsupported syntax the profile already drops,
    and reachability over explicit normal flow is not dead-code proof.
    """
    reached = graph.reachable()
    return tuple(
        UnreachableStatement(node.node_id, node.kind, node.span)
        for node in graph.nodes
        if node.span is not None and node.node_id not in reached
    )


@dataclass(frozen=True)
class FlowHints:
    """One pass over the bounded flow hints this module exports.

    Every member keeps its own boundary: each is a hint for the host's
    own analysis, not a defect verdict or a proof of source semantics.
    """

    unassigned: tuple[UnassignedUse, ...]
    unused: tuple[UnusedAssignment, ...]
    unreachable: tuple[UnreachableStatement, ...]
    # Names the extractor declares unreliable for path facts — assigned
    # inside a nested function literal or address-taken. Declared so the
    # host can see which findings were suppressed, not inferred.
    unreliable: frozenset[str] = frozenset()


def flow_hints(
    body: str,
    graph: ControlFlowGraph,
    *,
    entry_assigned: frozenset[str] = frozenset(),
) -> FlowHints:
    """Single entry point returning every bounded flow hint together.

    Aggregates `unassigned_uses`, `unused_assignments` and
    `unreachable_statements` into one immutable report over the same
    digest-checked body and graph. It adds no analysis of its own: the
    same profiles, gaps and modelling limits apply, and the report is a
    hint surface for the host, not a defect list or a proof.
    `entry_assigned` seeds names known to be available before the body.
    """
    tree = tree_sitter_extract.extract_statements(body, "go")
    if tree is None:
        raise ValueError("flow hints require a parsed Go body")
    return FlowHints(
        unassigned_uses(body, graph, entry_assigned=entry_assigned),
        unused_assignments(body, graph),
        unreachable_statements(graph),
        tree.closure_assigned | tree.address_taken,
    )


@dataclass(frozen=True)
class HintExpectations:
    """Host-declared expectations keyed exactly like `FlowHints`.

    `unassigned` and `unused` hold `(node_id, name)` pairs;
    `unreachable` holds bare `node_id`s. Expectations are declarations a
    host computes itself — they are not ground truth, and matching them
    only measures agreement between two declarations.
    """

    unassigned: tuple[tuple[int, str], ...] = ()
    unused: tuple[tuple[int, str], ...] = ()
    unreachable: tuple[int, ...] = ()


@dataclass(frozen=True)
class FamilyMetrics:
    """Agreement counts for one hint family.

    `matched` expectations found, `missed` expected-but-unreported and
    `unexpected` reported-but-unexpected findings — three separate
    counts, never a single quality score.
    """

    matched: int
    missed: int
    unexpected: int


@dataclass(frozen=True)
class HintMetrics:
    """Per-family agreement metrics between hints and expectations."""

    unassigned: FamilyMetrics
    unused: FamilyMetrics
    unreachable: FamilyMetrics


def _check_name_key(entry: tuple[int, str]) -> tuple[int, str]:
    if (
        not isinstance(entry, tuple)
        or len(entry) != 2
        or not isinstance(entry[0], int)
        or isinstance(entry[0], bool)
        or not isinstance(entry[1], str)
    ):
        raise ValueError("invalid hint expectation")
    return entry


def _check_node_key(entry: int) -> int:
    if not isinstance(entry, int) or isinstance(entry, bool):
        raise ValueError("invalid hint expectation")
    return entry


def _family_metrics(
    actual: set[tuple[int, ...]], expected: frozenset[tuple[int, ...]]
) -> FamilyMetrics:
    matched = len(actual & expected)
    return FamilyMetrics(
        matched, len(expected) - matched, len(actual) - matched
    )


def evaluate_flow_hints(
    hints: FlowHints, expected: HintExpectations
) -> HintMetrics:
    """Compare a `FlowHints` report against host-declared expectations.

    Counts agreement per family as `FamilyMetrics`: matched,
    expected-but-unreported (`missed`) and reported-but-unexpected
    (`unexpected`) — false positives and missed defects kept separate as
    the C05 acceptance criteria require. Expectations are host
    declarations, not ground truth: agreement measures consistency
    between two declarations, not correctness of either, and metric
    equality proves nothing about the underlying analysis.
    """
    expected_unassigned = frozenset(
        _check_name_key(entry) for entry in expected.unassigned
    )
    expected_unused = frozenset(
        _check_name_key(entry) for entry in expected.unused
    )
    expected_unreachable = frozenset(
        _check_node_key(entry) for entry in expected.unreachable
    )
    return HintMetrics(
        _family_metrics(
            {(use.node_id, use.name) for use in hints.unassigned},
            expected_unassigned,
        ),
        _family_metrics(
            {(use.node_id, use.name) for use in hints.unused},
            expected_unused,
        ),
        _family_metrics(
            {use.node_id for use in hints.unreachable},
            expected_unreachable,
        ),
    )


@dataclass(frozen=True)
class FileFunction:
    """Declared provenance of one function in a Go source unit.

    `declaration` and `body_span` are Unicode-codepoint offsets into the
    source the units were built from; `body_sha256` binds the extracted
    inner body text. A declaration with no body (`func f()` without an
    implementation) keeps `body_span`/`body_sha256` empty. Provenance is
    declared metadata only — hashes bind bytes, not semantics.
    """

    name: str
    declaration: SourceSpan
    body_span: SourceSpan | None
    body_sha256: str | None


@dataclass(frozen=True)
class GoFileUnits:
    """Function-level provenance index for one Go source unit."""

    source_sha256: str
    functions: tuple[FileFunction, ...]
    gaps: tuple[CFGGap, ...] = ()


def go_file_units(source: str) -> GoFileUnits:
    """Index function declarations in one Go source unit.

    Maps each function's raw name, declaration span and inner-body span
    to source-relative Unicode-codepoint offsets plus a SHA-256 of the
    extracted body — the file-level provenance the body-scoped CFG
    slices were missing. Declarations without a body get `None` spans;
    unparseable or unsupported input yields a `CFGGap` and no units —
    never a partial index. Names are reported raw and may repeat across
    methods; provenance is declared metadata, not symbol resolution.
    """
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    tree, _ = tree_sitter_extract.parse(source, "go")
    if tree is None or tree.root_node.has_error:
        return GoFileUnits(
            digest, (), (CFGGap("syntax_or_parser_unavailable"),)
        )
    functions = tree_sitter_extract.extract_functions(
        source, "go", lambda name: name
    )
    if functions is None:
        return GoFileUnits(
            digest, (), (CFGGap("syntax_or_parser_unavailable"),)
        )
    gaps: list[CFGGap] = []
    units: list[FileFunction] = []
    for function in functions:
        declaration = SourceSpan(function.start_char, function.end_char)
        if not function.has_body:
            gaps.append(CFGGap("declaration_without_body", declaration))
        units.append(
            FileFunction(
                function.raw_name or function.name,
                declaration,
                SourceSpan(
                    function.body_start_char, function.body_end_char
                )
                if function.has_body
                else None,
                hashlib.sha256(function.body.encode("utf-8")).hexdigest()
                if function.has_body
                else None,
            )
        )
    return GoFileUnits(digest, tuple(units), tuple(gaps))


def function_body(
    source: str, units: GoFileUnits, function: FileFunction
) -> str:
    """Re-extract one function's body under digest verification.

    The source must hash to `units.source_sha256`, the function must be
    one of `units.functions` and the sliced text must match
    `function.body_sha256` — every check is a static `ValueError`, so a
    body is returned only when the declared provenance still binds the
    bytes. The returned text is exactly what `build_go_cfg` consumes.
    """
    if (
        hashlib.sha256(source.encode("utf-8")).hexdigest()
        != units.source_sha256
    ):
        raise ValueError("source does not match the file units digest")
    if function not in units.functions:
        raise ValueError("function is not declared in these file units")
    if function.body_span is None:
        raise ValueError("function has no declared body")
    body = source[function.body_span.start : function.body_span.end]
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != (
        function.body_sha256 or ""
    ):
        raise ValueError("function body does not match the declared digest")
    return body


def go_entry_assigned_names(
    source: str, units: GoFileUnits, function: FileFunction
) -> frozenset[str]:
    """Return entry-assigned names visible in this one Go source file.

    Includes receiver, parameter and named-result identifiers from the
    function plus top-level `var` and `const` names in this file. Other
    package files are not available here, so their declarations are not
    included. The source digest and function membership must match `units`.
    """
    if (
        hashlib.sha256(source.encode("utf-8")).hexdigest()
        != units.source_sha256
    ):
        raise ValueError("source does not match the file units digest")
    if function not in units.functions:
        raise ValueError("function is not declared in these file units")

    declaration_start = function.declaration.start
    declaration_end = function.declaration.end
    if (
        declaration_start < 0
        or declaration_end < declaration_start
        or declaration_end > len(source)
    ):
        raise ValueError("function declaration span is invalid")
    byte_offsets = [0]
    for character in source:
        byte_offsets.append(
            byte_offsets[-1] + len(character.encode("utf-8"))
        )
    declaration_start_byte = byte_offsets[declaration_start]
    declaration_end_byte = byte_offsets[declaration_end]

    tree, source_bytes = tree_sitter_extract.parse(source, "go")
    if tree is None or source_bytes is None or tree.root_node.has_error:
        raise ValueError("source cannot be parsed as Go")
    declaration = next(
        (
            node
            for node in tree.root_node.named_children
            if node.type in {"function_declaration", "method_declaration"}
            and node.start_byte == declaration_start_byte
            and node.end_byte == declaration_end_byte
        ),
        None,
    )
    if declaration is None:
        raise ValueError("function declaration span does not match source")

    names: set[str] = set()

    def add_name_fields(node) -> None:
        for index, child in enumerate(node.children):
            if (
                node.field_name_for_child(index) == "name"
                and child.type == "identifier"
            ):
                name = source_bytes[child.start_byte : child.end_byte].decode(
                    "utf-8"
                )
                if name != "_":
                    names.add(name)

    def add_parameter_names(parameter_list) -> None:
        if parameter_list is None or parameter_list.type != "parameter_list":
            return
        for parameter in parameter_list.named_children:
            if parameter.type in {
                "parameter_declaration",
                "variadic_parameter_declaration",
            }:
                add_name_fields(parameter)

    add_parameter_names(declaration.child_by_field_name("receiver"))
    add_parameter_names(declaration.child_by_field_name("parameters"))
    add_parameter_names(declaration.child_by_field_name("result"))

    for top_level in tree.root_node.named_children:
        if top_level.type not in {"var_declaration", "const_declaration"}:
            continue
        for child in top_level.named_children:
            if child.type in {"var_spec", "const_spec"}:
                add_name_fields(child)
            elif child.type in {"var_spec_list", "const_spec_list"}:
                for spec in child.named_children:
                    if spec.type in {"var_spec", "const_spec"}:
                        add_name_fields(spec)
    return frozenset(names)
