"""Source-mapped explicit normal flow for a deliberately limited Go profile.

Calls are opaque and assumed to return normally. Panic/recovery, concurrency,
deferred execution, ``select``/type-switches and ``goto`` are not
modelled; expression switches are exclusive alternatives with implicit
break, labelled ``break``/``continue`` resolve only against enclosing
labelled loops, and ``panic``/``os.Exit``-style terminating calls end
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
_STRUCTURED = frozenset(
    {"if", "for", "range", "block", "return", "terminate", "switch"}
)


def _span(statement: tree_sitter_extract.Statement) -> SourceSpan:
    return SourceSpan(statement.start, statement.start + len(statement.text))


def _gaps(
    body: str,
    statements: tuple[tree_sitter_extract.Statement, ...],
    in_loop: bool = False,
    in_break: bool = False,
    labels: frozenset[str] = frozenset(),
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
            else:
                gaps.append(CFGGap("labelled_statement", span))
        if kind in {"break", "continue"}:
            parts = statement.text.split()
            if len(parts) == 1:
                if kind == "continue" and not in_loop:
                    gaps.append(CFGGap("jump_without_loop", span))
                elif kind == "break" and not (in_loop or in_break):
                    gaps.append(CFGGap("jump_without_loop", span))
            elif len(parts) == 2 and _IDENTIFIER.fullmatch(parts[1]):
                if parts[1] not in labels:
                    gaps.append(CFGGap("unresolved_label", span))
            else:
                gaps.append(CFGGap("labelled_jump", span))
        elif kind == "switch":
            if statement.operator in {"type", "select"}:
                gaps.append(CFGGap(f"unsupported_{statement.operator}_switch", span))
            else:
                for case in statement.body:
                    if case.kind == "case" and not case.values:
                        # A value-less case the extractor could not
                        # classify — never silently modelled.
                        gaps.append(CFGGap("unsupported_case", _span(case)))
        elif kind not in _SIMPLE | _STRUCTURED:
            gaps.append(CFGGap(f"unsupported_{kind}", span))
        gaps.extend(_gaps(body, statement.init, in_loop, in_break, labels))
        if kind == "switch":
            for case in statement.body:
                # Case bodies may break the switch; continue still
                # needs an enclosing loop.
                gaps.extend(
                    _gaps(body, case.body, in_loop, True, labels)
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
                )
            )
        gaps.extend(
            _gaps(body, statement.orelse, in_loop, in_break, labels)
        )
        gaps.extend(
            _gaps(body, statement.post, in_loop, in_break, labels)
        )
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
                parts = statement.text.split()
                target = (
                    loop
                    if len(parts) == 1
                    else labels.get(parts[1])
                )
                assert target is not None
                self.edge(node, target[0 if kind == "break" else 1], kind)
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
                for case in statement.body:
                    case_node = self.node(case.kind, case)
                    self.edge(node, case_node, "case")
                    self.edge(
                        case_node,
                        self.sequence(case.body, following, inner, labels),
                    )
                if not any(case.kind == "default" for case in statement.body):
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
    `definite` is true when the name is also missing from the node's
    `some_path` pre-state — assigned somewhere in the body, yet no path
    can deliver it to this use.
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
    if statement.kind in {"range", "return", "expr", "define", "const", "var"}:
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


def unassigned_uses(
    body: str, graph: ControlFlowGraph
) -> tuple[UnassignedUse, ...]:
    """Names used at a node without a definite assignment reaching it.

    Reports `name` at `node` when `name` is textually assigned somewhere in
    the body yet absent from the node's `all_paths` pre-state — a possibly-
    unassigned read, conservatively limited to recognized identifiers. The
    `definite` flag marks the stronger class: the name is assigned
    somewhere but absent from the `some_path` pre-state too, so no
    modelled path can deliver it. It does not model fields, elements,
    calls, shadowing or closures; names the extractor marks unreliable
    (assigned inside a closure or address-taken) can still be flagged
    but are never promoted to `definite`, because a closure call or an
    aliased write sits outside the modelled paths. A finding is a hint
    for the host's own dataflow, not a defect verdict.
    """
    facts = assignment_facts(body, graph)
    tree = tree_sitter_extract.extract_statements(body, "go")
    assert tree is not None  # assignment_facts already re-parsed the body
    unreliable = tree.closure_assigned | tree.address_taken
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
            pre_some = frozenset()
        else:
            pre = frozenset.intersection(
                *(facts[p].all_paths for p in incoming)
            )
            pre_some = frozenset().union(
                *(facts[p].some_path for p in incoming)
            )
        for name in sorted(_IDENTIFIER.findall(_use_text(statement))):
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
    """A name textually assigned at a node but never read anywhere.

    A heuristic hint, not a defect verdict: "read" is the same
    conservative identifier scan `unassigned_uses` performs, so a name
    mentioned only inside its own initializer still counts as read.
    """

    node_id: int
    name: str
    span: SourceSpan | None


def unused_assignments(
    body: str, graph: ControlFlowGraph
) -> tuple[UnusedAssignment, ...]:
    """Recognized assignment targets that are never textually read.

    Reports `name` at `node` when `name` is a simple identifier target of
    a recognized assignment statement and appears in no use position
    anywhere in the body — the dead-store hint at name granularity. It
    does not model fields, elements, calls, shadowing or closures, does
    not check which assignment is dead when several write the same name,
    and counts reads in unreachable code like any other. A finding is a
    hint for the host's own analysis, not a defect verdict.
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
    findings: list[UnusedAssignment] = []
    for node in graph.nodes:
        if node.span is None:
            continue
        statement = by_span.get((node.span.start, node.span.end))
        if statement is None:
            continue
        for name in sorted(_assigned_names(statement)):
            if name not in used:
                findings.append(
                    UnusedAssignment(node.node_id, name, node.span)
                )
    return tuple(findings)


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


def flow_hints(body: str, graph: ControlFlowGraph) -> FlowHints:
    """Single entry point returning every bounded flow hint together.

    Aggregates `unassigned_uses`, `unused_assignments` and
    `unreachable_statements` into one immutable report over the same
    digest-checked body and graph. It adds no analysis of its own: the
    same profiles, gaps and modelling limits apply, and the report is a
    hint surface for the host, not a defect list or a proof.
    """
    tree = tree_sitter_extract.extract_statements(body, "go")
    if tree is None:
        raise ValueError("flow hints require a parsed Go body")
    return FlowHints(
        unassigned_uses(body, graph),
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
