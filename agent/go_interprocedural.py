"""Opt-in parameter-dependency summaries, not proofs or audit-grade inputs.

Bodies are let bindings — ``a, b := e1, e2`` declarations bind each
name to its matching right-hand side's dependencies, evaluated in
parallel against the pre-state —
plus ``if``/``else`` and bounded ``for`` statements followed by one or more
explicit scalar return expressions; the result unions every syntactic return's
dependencies (unreachable returns included — reachability is not proven). A
``for`` clause may hold one let-binding initializer, a supported condition and
an inc/dec update on a bound scalar. Integer ``range`` loops — ``for
i := range e`` where the operand is an integer — bind a fresh scoped
index variable carrying the operand's dependencies; composite ranges
are unreachable because no supported binding or literal can produce
them. A scalar ``x = expression``
reassignment replaces the binding's dependencies — it never declares a
new variable. Tuple assignments ``x, y = e1, e2`` are parallel: every
right-hand side evaluates against the pre-state before any store lands.
Compound assignments ``x op= e`` read the old value — the result unions
the binding's current dependencies with the right-hand side's. Loop bodies are
joined to a widening fixed point so dependencies propagating across
iterations are captured (joins, not unrolls — trip counts are never
modelled). ``if`` and expression ``switch`` statements accept a
simple-statement ``initializer`` — the same mechanism as a for-clause
init, with the bound name scoped to the statement (a later out-of-scope
reference simply never resolves). ``switch`` without ``fallthrough``
joins the same way: the tag and every case guard are evaluated
(effect-free), each clause body runs in its own scope and its
reassignments union back. ``var`` declarations bind like lets —
``var a, b T`` is the dep-free zero value and ``var a, b = x, y``
binds name-wise like ``:=`` (grouped ``var (...)`` forms are a parser
gap). ``x++``/``x--`` on a
bound scalar are dependency-preserving, and ``_ = expression``
evaluates-and-discards like a condition. Expression statements — only
calls are legal — evaluate for their recorded transfer and discard the
result. An unlabelled
``break``/``continue`` marks its innermost loop or switch construct as
exited — every later statement in that body is a may-assignment whose
writes union instead of replace, because the jump may have skipped them
(labelled jumps, ``goto``, ``defer`` and ``go`` stay unmodelled). Scalar
``const`` declarations and reads are admitted: a constant expression can
never read a variable (the compiler rejects it before this reader runs),
so a scalar-typed ``constant`` binding always resolves to an empty
dependency set and the declaration itself writes nothing; ``iota`` is
dep-free too, while non-scalar constants stay gaps and grouped
``const ( ... )`` forms are a parser gap like grouped ``var``. A named
scalar result — ``func F(x) (r int64)`` — is an ordinary local
pre-initialised to the dep-free zero value; a bare ``return`` (legal
only with a named result) yields its current dependencies. Type
switches, ``select`` and every other
statement shape stay unsupported.
Scalar conversions ``T(e)`` are effect-free — the result inherits the
operand's dependencies; the type change itself (truncation, widening)
is not modelled. The pure builtins ``min``/``max`` union their
arguments' dependencies; every other builtin stays opaque
(``len``/``cap`` can only take values no supported binding can hold).
Compiler-resolved
bindings/calls supply identity; tree-sitter supplies syntax, never resolution.
``stale_dependents`` maps callee replacement to the summaries that must be
re-derived — recorded targets are source-anchored identities, so a replaced
callee never reuses its identity. Reports require the trusted producer and
reader described in go_type_snapshot.
No processes, imports, persistent caches or existing audit routes are invoked.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from agent import control_flow
from agent.go_type_snapshot import (
    MAX_SOURCE_BYTES,
    PACKAGE_PROFILE as TYPE_PACKAGE_PROFILE,
    PROFILE as TYPE_PROFILE,
    TARGETS,
    _package_raws,
    ByteSpan,
    FileSpan,
    Function,
    GoType,
    GoPackageSnapshot,
    GoTypeSnapshot,
    SnapshotError,
)

PROFILE = "mumei.go-scalar-parameter-deps/v1"
MAX_FUNCTIONS = 128
MAX_DEPTH = 48
MAX_EXPRESSION_NODES = 2048
_BINARY = frozenset(
    {
        "+", "-", "*", "/", "%", "&", "|", "^", "&^", "<<", ">>",
        "==", "!=", "<", "<=", ">", ">=", "&&", "||",
    }
)
_UNARY = frozenset({"+", "-", "!", "^"})
_COMPOUND_ASSIGN = frozenset(
    {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "&^="}
)
_SCALAR_BASIC_TYPES = frozenset(
    {
        b"bool", b"int", b"int8", b"int16", b"int32", b"int64",
        b"uint", b"uint8", b"uint16", b"uint32", b"uint64", b"uintptr",
        b"byte", b"rune",
    }
)
_UNTYPED_SCALAR_CONSTS = frozenset(
    {"untyped int", "untyped rune", "untyped bool"}
)


def _scalar_constant(binding: Any) -> bool:
    """A compile-time constant in the scalar fragment — reads carry no deps."""
    return (
        binding.kind == "constant"
        and (
            binding.type.kind in {"integer", "boolean"}
            or (
                binding.type.kind == "untyped"
                and binding.type.basic_name in _UNTYPED_SCALAR_CONSTS
            )
        )
    )


@dataclass(frozen=True)
class SummaryGap:
    reason: str
    span: ByteSpan | FileSpan | None = None
    callee: str = ""


@dataclass(frozen=True)
class CallTransfer:
    span: ByteSpan | FileSpan
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

    @property
    def call_targets(self) -> frozenset[str]:
        """Callee identities the recorded calls were resolved against."""
        return frozenset(call.target for call in self.calls)


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


def _package_context(
    snapshot: GoPackageSnapshot, sources: "dict[str, str] | list[str]"
) -> tuple[tuple[bytes, ...], str]:
    try:
        raws = _package_raws(snapshot, sources)
    except (KeyError, TypeError, ValueError):
        raise SnapshotError("Go summary context unavailable or stale") from None
    if (
        snapshot.profile != TYPE_PACKAGE_PROFILE
        or snapshot.language_version != "go1.23"
        or snapshot.target_arch not in TARGETS
    ):
        raise SnapshotError("Go summary context unavailable or stale")
    payload = json.dumps(
        [PROFILE, control_flow.PROFILE, asdict(snapshot)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return raws, hashlib.sha256(payload).hexdigest()


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

    def for_package_function(
        self,
        sources: "dict[str, str] | list[str]",
        snapshot: GoPackageSnapshot,
        binding_id: str,
    ) -> FunctionSummary:
        """The package-unit variant of `for_function` — same staleness rule."""
        if _package_context(snapshot, sources)[1] != self.context_key:
            raise SnapshotError("Go summary context unavailable or stale")
        result = next((f for f in self.functions if f.binding_id == binding_id), None)
        if result is None:
            raise SnapshotError("Go function summary unavailable")
        return result

    def stale_dependents(self, known: Iterable[str]) -> frozenset[str]:
        """Summaries that recorded a call to a callee identity outside `known`.

        Binding identities carry the producing unit's source digest, so a
        replaced callee never reuses its identity: every summary that
        recorded a call to a target absent from `known` must be
        re-derived. Direct callees only — a transitive caller two edges
        away is not reported; hosts building incremental caches must
        propagate invalidation through the recorded call graph
        themselves. Detection only — what to recompute is the host's call.
        """
        live = frozenset(known)
        return frozenset(
            f.binding_id
            for f in self.functions
            if any(target not in live for target in f.call_targets)
        )


class _Unsupported(Exception):
    def __init__(
        self,
        reason: str,
        span: ByteSpan | FileSpan | None = None,
        callee: str = "",
    ):
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


def _key3(span: ByteSpan | FileSpan) -> tuple[int, int, int]:
    """Normalize a report span to (file, start, end) — file 0 for v1 reports."""
    return (
        span.file if isinstance(span, FileSpan) else 0,
        span.start,
        span.end,
    )


class _Builder:
    def __init__(
        self,
        raws: dict[int, bytes],
        snapshot: GoTypeSnapshot | GoPackageSnapshot,
        key: str,
        cfg_fn: Any,
    ):
        self.snapshot, self.key, self.cfg_fn = snapshot, key, cfg_fn
        self.bindings = {b.id: b for b in snapshot.bindings}
        self.functions = {f.binding_id: f for f in snapshot.functions}
        self.references = {_key3(r.span): r for r in snapshot.references}
        self.calls = {_key3(c.span): c for c in snapshot.calls}
        self.blocks: dict[tuple[int, int, int], Any] = {}
        self.bindings_by_span = {_key3(b.span): b for b in snapshot.bindings}
        self.cache: dict[str, FunctionSummary] = {}
        self.active: set[str] = set()
        self.current_file = 0
        # Innermost enclosing loop/switch constructs, innermost last; an
        # unlabelled break or continue marks the frame it exits.
        self.frames: list[dict[str, Any]] = []
        for file, raw in raws.items():
            root = _syntax(raw)
            if root is None:
                continue
            for node in root.named_children:
                if node.type not in {"function_declaration", "method_declaration"}:
                    continue
                name, body = (
                    node.child_by_field_name("name"),
                    node.child_by_field_name("body"),
                )
                if name is not None and body is not None:
                    self.blocks[(file, name.start_byte, name.end_byte)] = body

    def node_key(self, node: Any) -> tuple[int, int, int]:
        return (self.current_file, node.start_byte, node.end_byte)

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
            or any(
                p.type.kind not in {"integer", "boolean"}
                for p in (*fn.parameters, *fn.results)
            )
        ):
            raise _Unsupported("unsupported_signature", fn.body)
        binding = self.bindings.get(fn.binding_id)
        body_key = _key3(fn.body)
        block = self.blocks.get(_key3(binding.span)) if binding is not None else None
        if block is None:
            raise _Unsupported("syntax_or_parser_unavailable", fn.body)
        if (body_key[0], block.start_byte + 1, block.end_byte - 1) != body_key:
            raise _Unsupported("source_mapping_unavailable", fn.body)
        previous_file = self.current_file
        self.current_file = body_key[0]
        pending = [(block, 0)]
        visited = 0
        while pending:
            node, depth = pending.pop()
            visited += 1
            if depth >= MAX_DEPTH or visited > MAX_EXPRESSION_NODES:
                raise _Unsupported("analysis_limit", fn.body)
            pending.extend((child, depth + 1) for child in _children(node))
        cfg = self.cfg_fn(fn.binding_id)
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
        # A named result is an ordinary local pre-initialised to the zero
        # value — dep-free until a body statement writes to it.
        result_binding = fn.results[0].binding_id
        if result_binding:
            locals_[result_binding] = frozenset()
        deps: list[frozenset[int]] = [frozenset()]
        saw_return = [False]
        # The frame stack belongs to this function alone — a caller's
        # exited frame must never leak into (or be marked by) a callee
        # summarized mid-expression.
        saved_frames = self.frames
        self.frames = []
        try:
            self._sequence(
                statements, fn, params, locals_, transfers, count, deps,
                saw_return, False,
            )
        finally:
            self.frames = saved_frames
            self.current_file = previous_file
        if not saw_return[0]:
            raise _Unsupported("unsupported_body", fn.body)
        return self.result(
            fn, deps[0], tuple(sorted(transfers, key=lambda c: _key3(c.span)))
        )

    def _sequence(
        self,
        children: list[Any],
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        deps: list[frozenset[int]],
        saw_return: list[bool],
        conditional: bool,
    ) -> None:
        """Run a statement list, honouring exits earlier children record.

        Once the innermost loop-or-switch frame is marked exited by an
        unlabelled break/continue, every later statement is conditional —
        it may have been skipped, so its writes union like a branch join.
        """
        frame = self.frames[-1] if self.frames else None
        for child in children:
            if frame is not None and frame["exited"]:
                conditional = True
            self.statement(
                child, fn, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )

    @staticmethod
    def _store(
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
        binding_id: str,
        value: frozenset[int],
        conditional: bool,
    ) -> None:
        if conditional:
            if binding_id in locals_:
                # The skipped path keeps the binding's CURRENT value —
                # not a parameter's original deps once it was reassigned.
                value = locals_[binding_id] | value
            elif binding_id in params:
                value = frozenset({params[binding_id]}) | value
        locals_[binding_id] = value

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
        conditional: bool,
    ) -> None:
        count[0] += 1
        if count[0] > MAX_EXPRESSION_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        if kind in {"block", "statement_list"}:
            self._sequence(
                _children(node), fn, params, locals_, transfers, count,
                deps, saw_return, conditional,
            )
            return
        if kind == "return_statement":
            expressions = _children(node)
            if len(expressions) == 1 and expressions[0].type == "expression_list":
                expressions = _children(expressions[0])
            if len(expressions) == 0:
                # A bare `return` is only legal with a named result — it
                # yields the result binding's current dependencies.
                result_id = (
                    fn.results[0].binding_id if len(fn.results) == 1 else ""
                )
                if not result_id:
                    raise _Unsupported("unsupported_return", _span(node))
                deps[0] |= locals_.get(result_id, frozenset())
            elif len(expressions) == 1:
                deps[0] |= self.expression(
                    expressions[0], fn, params, locals_, transfers, count, 0
                )
            else:
                raise _Unsupported("unsupported_return", _span(node))
            saw_return[0] = True
            return
        if kind == "short_var_declaration":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            lefts = _children(left) if left is not None else []
            rights = _children(right) if right is not None else []
            if (
                not lefts
                or any(l.type != "identifier" for l in lefts)
                or len(lefts) != len(rights)
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            # RHS expressions evaluate in parallel against the pre-state
            # — `a, b := b, a` swaps — so all reads happen before any
            # store.
            values = [
                self.expression(
                    rhs, fn, params, locals_, transfers, count, 0
                )
                for rhs in rights
            ]
            for lhs, value in zip(lefts, values):
                # `_` discards its value — the RHS was still evaluated.
                if lhs.text == b"_":
                    continue
                # `x, y := e1, e2` may reuse an existing `x` when at
                # least one name is new — go/types records a use for it,
                # not a fresh binding.
                binding = self.bindings_by_span.get(self.node_key(lhs))
                if binding is None:
                    ref = self.references.get(self.node_key(lhs))
                    if ref is not None and ref.binding_id:
                        binding = self.bindings.get(ref.binding_id)
                if binding is None or binding.type.kind not in {
                    "integer",
                    "boolean",
                }:
                    raise _Unsupported("binding_unavailable", _span(node))
                self._store(locals_, params, binding.id, value, conditional)
            return
        if kind == "var_declaration":
            # Grouped `var (...)` declarations never reach here — the
            # grammar marks them has_error and the source is rejected as
            # `syntax_or_parser_unavailable` before statement dispatch.
            specs = [
                c
                for c in node.named_children
                if c.type == "var_spec"
            ]
            if not specs:
                raise _Unsupported("unsupported_statement", _span(node))
            for spec in specs:
                names: list[Any] = []
                value_nodes: list[Any] = []
                for i, child in enumerate(spec.children):
                    field = spec.field_name_for_child(i)
                    if field == "name":
                        names.append(child)
                    elif field == "value":
                        value_nodes.extend(_children(child))
                if not names or len(names) != len(value_nodes) and value_nodes:
                    raise _Unsupported("unsupported_statement", _span(spec))
                # `var a, b T` without values is the zero value —
                # dep-free. With values the RHS evaluates in parallel
                # against the pre-state before any store.
                if value_nodes:
                    values = [
                        self.expression(
                            rhs, fn, params, locals_, transfers,
                            count, 0,
                        )
                        for rhs in value_nodes
                    ]
                else:
                    values = [frozenset() for _ in names]
                for name, value in zip(names, values):
                    if name.text == b"_":
                        continue
                    binding = self.bindings_by_span.get(self.node_key(name))
                    if binding is None or binding.type.kind not in {
                        "integer",
                        "boolean",
                    }:
                        raise _Unsupported(
                            "binding_unavailable", _span(spec)
                        )
                    self._store(
                        locals_, params, binding.id, value, conditional
                    )
            return
        if kind == "const_declaration":
            # Grouped `const (...)` declarations never reach here — like
            # grouped vars the grammar marks them has_error. A spec
            # without a value (implicit iota repetition) is unmodelled.
            specs = [
                c for c in node.named_children if c.type == "const_spec"
            ]
            if not specs:
                raise _Unsupported("unsupported_statement", _span(node))
            for spec in specs:
                names: list[Any] = []
                value_nodes: list[Any] = []
                for i, child in enumerate(spec.children):
                    field = spec.field_name_for_child(i)
                    # `name` fields also cover the `,` separators of a
                    # multi-name spec — only identifiers declare bindings.
                    if field == "name":
                        if child.type == "identifier":
                            names.append(child)
                        elif child.type != ",":
                            raise _Unsupported(
                                "unsupported_statement", _span(spec)
                            )
                    elif field == "value":
                        value_nodes.extend(_children(child))
                if not names or len(names) != len(value_nodes):
                    raise _Unsupported("unsupported_statement", _span(spec))
                for name in names:
                    if name.text == b"_":
                        continue
                    binding = self.bindings_by_span.get(self.node_key(name))
                    if binding is None or not _scalar_constant(binding):
                        raise _Unsupported(
                            "binding_unavailable", _span(spec)
                        )
                # Constant expressions never read variables, so the
                # values bind nothing — evaluating them only checks
                # fragment legality and records any builtin transfers.
                for rhs in value_nodes:
                    self.expression(
                        rhs, fn, params, locals_, transfers, count, 0
                    )
            return
        if kind == "if_statement":
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            if condition is None or consequence is None:
                raise _Unsupported("unsupported_statement", _span(node))
            initializer = node.child_by_field_name("initializer")
            # `if init; cond` runs a simple statement first — the same
            # mechanism as a for-clause initializer. A name it binds is a
            # fresh binding that is scoped to the statement and dropped
            # by the join below, so a shadowed outer name keeps its deps.
            scope = dict(locals_) if initializer is not None else locals_
            if initializer is not None:
                self.statement(
                    initializer, fn, params, scope, transfers, count,
                    deps, saw_return, conditional,
                )
            # The condition is evaluated but its dependencies cannot reach
            # the result: every fragment statement is effect-free.
            self.expression(
                condition, fn, params, scope, transfers, count, 0
            )
            # Branch-local bindings never escape their scope, matching the
            # compiler — a later reference simply would not resolve.
            # Reassignments of existing names join back by union: the
            # branch may not execute.
            branch = dict(scope)
            self._sequence(
                _children(consequence), fn, params, branch, transfers,
                count, deps, saw_return, conditional,
            )
            self._join(scope, branch, params)
            alternative = node.child_by_field_name("alternative")
            if alternative is not None:
                branch = dict(scope)
                if alternative.type == "if_statement":
                    self.statement(
                        alternative, fn, params, branch, transfers,
                        count, deps, saw_return, conditional,
                    )
                else:
                    self._sequence(
                        _children(alternative), fn, params, branch,
                        transfers, count, deps, saw_return, conditional,
                    )
                self._join(scope, branch, params)
            if initializer is not None:
                self._join(locals_, scope, params)
            return
        if kind == "assignment_statement":
            operator = node.child_by_field_name("operator")
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            lefts = _children(left) if left is not None else []
            rights = _children(right) if right is not None else []
            compound = operator is not None and operator.type in _COMPOUND_ASSIGN
            if (
                operator is None
                or (operator.type != "=" and not compound)
                or not lefts
                or (compound and len(lefts) != 1)
                or len(lefts) != len(rights)
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            # Every LHS must be a bound identifier or `_` before any RHS
            # runs, matching the single-assignment check's error order.
            refs: list[Any] = []
            for lhs in lefts:
                if lhs.type != "identifier":
                    raise _Unsupported("unsupported_statement", _span(lhs))
                if lhs.text == b"_":
                    refs.append(None)
                    continue
                ref = self.references.get(self.node_key(lhs))
                if ref is None or (
                    ref.binding_id not in locals_
                    and ref.binding_id not in params
                ):
                    raise _Unsupported("binding_unavailable", _span(lhs))
                refs.append(ref)
            # Tuple assignment is parallel: every RHS evaluates against the
            # pre-state before any store lands, so `x, y = y, x` swaps each
            # name's original dependencies.
            values = [
                self.expression(
                    rhs, fn, params, locals_, transfers, count, 0
                )
                for rhs in rights
            ]
            for ref, value in zip(refs, values):
                if ref is None:
                    continue
                if compound:
                    # `x op= e` reads the old value too — the result unions
                    # the binding's current dependencies with the RHS's.
                    if ref.binding_id in locals_:
                        value = locals_[ref.binding_id] | value
                    else:
                        value = frozenset({params[ref.binding_id]}) | value
                # Reassignment replaces the binding's dependencies; it never
                # declares a new variable. Inside a branch the caller's join
                # unions the new value back as a may-assignment.
                self._store(
                    locals_, params, ref.binding_id, value, conditional,
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
            if body_node is None:
                raise _Unsupported("unsupported_statement", _span(node))
            # The loop variable and every binding made inside the body are
            # scoped to the loop — none of them escape, matching the compiler.
            scope = dict(locals_)
            update = None
            if clause is not None and clause.type == "range_clause":
                # Only integer ranges are reachable in-fragment — a
                # composite operand (slice, map, string, channel, array)
                # cannot be produced by any supported binding or literal,
                # so the operand is an integer and the range yields one
                # index variable. `for i := range e` binds a fresh scoped
                # name; `for i = range e` reuses an existing binding;
                # `_` slots and the bare `for range e` form just evaluate.
                left = clause.child_by_field_name("left")
                right = clause.child_by_field_name("right")
                lefts = _children(left) if left is not None else []
                if right is None or len(lefts) > 1 or (
                    lefts and lefts[0].type != "identifier"
                ):
                    raise _Unsupported(
                        "unsupported_statement", _span(clause)
                    )
                rdeps = self.expression(
                    right, fn, params, scope, transfers, count, 0
                )
                if lefts and lefts[0].text != b"_":
                    binding = self.bindings_by_span.get(self.node_key(lefts[0]))
                    if binding is not None:
                        if binding.type.kind not in {"integer", "boolean"}:
                            raise _Unsupported(
                                "binding_unavailable", _span(lefts[0])
                            )
                        scope[binding.id] = rdeps
                    else:
                        ref = self.references.get(self.node_key(lefts[0]))
                        if ref is None or (
                            ref.binding_id not in scope
                            and ref.binding_id not in params
                        ):
                            raise _Unsupported(
                                "binding_unavailable", _span(lefts[0])
                            )
                        self._store(
                            scope, params, ref.binding_id, rdeps, conditional,
                        )
            elif clause is not None and clause.type == "for_clause":
                init = clause.child_by_field_name("initializer")
                if init is not None:
                    self.statement(
                        init, fn, params, scope, transfers, count, deps,
                        saw_return, conditional,
                    )
                condition = clause.child_by_field_name("condition")
                if condition is not None:
                    self.expression(
                        condition, fn, params, scope, transfers, count, 0
                    )
                update = clause.child_by_field_name("update")
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
            frame = {"kind": "loop", "exited": False}
            self.frames.append(frame)
            try:
                while True:
                    mark = len(transfers)
                    frame["exited"] = False
                    inner = dict(scope)
                    self._sequence(
                        _children(body_node), fn, params, inner, transfers,
                        count, deps, saw_return, conditional,
                    )
                    if update is not None:
                        # The update runs after each pass so its writes
                        # seed the next iteration — an inc/dec is a
                        # dependency-preserving no-op, an assignment's
                        # RHS dependencies widen into the fixed point.
                        self.statement(
                            update, fn, params, inner, transfers, count,
                            deps, saw_return, conditional,
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
                    # Keep only the last pass's transfers: argument
                    # dependency sets widen across passes and earlier
                    # copies are stale.
                    del transfers[mark:]
                    passes += 1
                    if passes > len(scope) * (len(params) + 1):
                        raise _Unsupported("analysis_limit", _span(node))
            finally:
                self.frames.pop()
            # Loop-body reassignments join back by union: the loop may
            # execute zero or many times.
            self._join(locals_, scope, params)
            return
        if kind == "expression_switch_statement":
            initializer = node.child_by_field_name("initializer")
            # `switch init; tag` runs a simple statement first — any name
            # it binds is scoped to the switch, like a for-clause init.
            scope = dict(locals_) if initializer is not None else locals_
            if initializer is not None:
                self.statement(
                    initializer, fn, params, scope, transfers, count,
                    deps, saw_return, conditional,
                )
            value = node.child_by_field_name("value")
            if value is not None:
                # The tag is evaluated but its dependencies cannot reach the
                # result: every fragment statement is effect-free.
                self.expression(
                    value, fn, params, scope, transfers, count, 0
                )
            frame = {"kind": "switch", "exited": False}
            self.frames.append(frame)
            try:
                clauses = [
                    c for c in node.named_children
                    if c.type in {"expression_case", "default_case"}
                ]
                branch: dict[str, frozenset[int]] | None = None
                for index, clause in enumerate(clauses):
                    body = next(
                        (
                            c for c in clause.named_children
                            if c.type == "statement_list"
                        ),
                        None,
                    )
                    statements = (
                        _children(body)
                        if body is not None
                        else (
                            _children(clause)
                            if clause.type == "default_case"
                            else []
                        )
                    )
                    falls = (
                        bool(statements)
                        and statements[-1].type == "fallthrough_statement"
                    )
                    if falls:
                        if index == len(clauses) - 1:
                            raise _Unsupported(
                                "unsupported_fallthrough", _span(clause)
                            )
                        statements = statements[:-1]
                    for sub in clause.named_children:
                        if sub.type == "expression_list":
                            # Case guards are evaluated like the tag.
                            for guard in _children(sub):
                                self.expression(
                                    guard, fn, params, scope,
                                    transfers, count, 0,
                                )
                    if branch is None:
                        # Direct match, or the head of a new chain — the
                        # same fresh alternative doubles as the chain's
                        # first step when the clause falls through.
                        frame["exited"] = False
                        branch = dict(scope)
                        self._sequence(
                            statements, fn, params, branch, transfers,
                            count, deps, saw_return, conditional,
                        )
                        if not falls:
                            self._join(scope, branch, params)
                            branch = None
                        continue
                    # Fall-through target — the body runs twice: once in
                    # the carried chain scope (the fallthrough path, with
                    # `exited` preserved across the chain), once as a
                    # fresh alternative (the direct-match path, which
                    # skips the preceding clause's writes).
                    self._sequence(
                        statements, fn, params, branch, transfers,
                        count, deps, saw_return, conditional,
                    )
                    chain_exited = frame["exited"]
                    frame["exited"] = False
                    fresh = dict(scope)
                    self._sequence(
                        statements, fn, params, fresh, transfers,
                        count, deps, saw_return, conditional,
                    )
                    self._join(scope, fresh, params)
                    if falls:
                        frame["exited"] = chain_exited
                    else:
                        self._join(scope, branch, params)
                        branch = None
            finally:
                self.frames.pop()
            if initializer is not None:
                self._join(locals_, scope, params)
            return
        if kind == "labeled_statement":
            inner = [c for c in node.named_children if c.type != "label_name"]
            if len(inner) != 1:
                raise _Unsupported("unsupported_statement", _span(node))
            # A label with no labelled jumps is inert syntax — the wrapped
            # statement is processed normally; `break L`/`continue L`
            # inside it stay unsupported via the label check below.
            self.statement(
                inner[0], fn, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
            return
        if kind in {"inc_statement", "dec_statement"}:
            operands = _children(node)
            if len(operands) != 1 or operands[0].type != "identifier":
                raise _Unsupported("unsupported_statement", _span(node))
            ref = self.references.get(self.node_key(operands[0]))
            if ref is None or (
                ref.binding_id not in locals_ and ref.binding_id not in params
            ):
                raise _Unsupported("binding_unavailable", _span(node))
            # x++ / x-- change the value, never its dependencies.
            return
        if kind in {"break_statement", "continue_statement"}:
            if any(c.type == "label_name" for c in node.named_children):
                raise _Unsupported("unsupported_statement", _span(node))
            if kind == "break_statement":
                # Unlabelled break exits the innermost loop or switch.
                if not self.frames:
                    raise _Unsupported("unsupported_statement", _span(node))
                self.frames[-1]["exited"] = True
            else:
                # Unlabelled continue exits the innermost loop — plus
                # every construct between here and it, such as an
                # enclosing switch clause.
                for frame in reversed(self.frames):
                    frame["exited"] = True
                    if frame["kind"] == "loop":
                        break
                else:
                    raise _Unsupported("unsupported_statement", _span(node))
            return
        if kind == "expression_statement":
            # A call (or receive) evaluated for its side channel and
            # discarded — only those are legal expression statements.
            # The call's transfer still records normally; receives can
            # never appear in-fragment, so the inner expression fails
            # closed on its own if it isn't a supported call.
            inner = _children(node)
            if len(inner) != 1:
                raise _Unsupported("unsupported_statement", _span(node))
            self.expression(
                inner[0], fn, params, locals_, transfers, count, 0
            )
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
        if kind in {"identifier", "true", "false", "iota"}:
            ref = self.references.get(self.node_key(node))
            # Reassigned names (including parameters) resolve through
            # `locals_` first — their latest dependencies live there.
            if ref is not None and ref.binding_id in locals_:
                return locals_[ref.binding_id]
            if ref is not None and ref.binding_id in params:
                return frozenset({params[ref.binding_id]})
            # `iota` is not a keyword — only the compiler's universe
            # reference proves the predeclared constant, never the name.
            if (
                ref is not None
                and ref.kind == "universe"
                and (kind in {"true", "false"} or node.text == b"iota")
            ):
                return frozenset()
            binding = (
                self.bindings.get(ref.binding_id)
                if ref is not None and ref.binding_id
                else None
            )
            if binding is not None:
                # Constants can never read variables — the compiler
                # rejects a non-constant right-hand side before this
                # reader runs — so a scalar const is always dep-free.
                if _scalar_constant(binding):
                    return frozenset()
                if binding.kind == "constant":
                    raise _Unsupported("binding_unavailable", _span(node))
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
            call = self.calls.get(self.node_key(node))
            if (
                call is None
                or call.owner != fn.binding_id
                or call.kind
                not in {"direct_local", "direct_import", "conversion", "builtin"}
            ):
                raise _Unsupported("unresolved_or_opaque_call", _span(node))
            arguments_node = node.child_by_field_name("arguments")
            arguments = _children(arguments_node) if arguments_node is not None else []
            if tuple(self.node_key(arg) for arg in arguments) != tuple(
                _key3(a) for a in call.arguments
            ):
                raise _Unsupported("call_mapping_unavailable", _span(node), call.target)
            if call.kind == "conversion":
                # `T(e)` is effect-free for dependency purposes — the
                # result inherits the operand's dependencies; the type
                # change itself (truncation, widening) is not modelled.
                # The target must be a scalar type too: a conversion to
                # a non-scalar (e.g. `string(x)`) would let the result
                # flow into contexts that never bind it — like a `range`
                # operand — without ever hitting a binding check.
                # Declared types resolve through their binding's type;
                # universe type names carry no binding_id, so they are
                # matched against Go's fixed predeclared scalar set.
                function_node = node.child_by_field_name("function")
                while (
                    function_node is not None
                    and function_node.type == "parenthesized_expression"
                ):
                    function_node = next(
                        iter(function_node.named_children), None
                    )
                ref = (
                    self.references.get(self.node_key(function_node))
                    if function_node is not None
                    else None
                )
                if ref is not None and ref.binding_id:
                    binding = self.bindings.get(ref.binding_id)
                    scalar = binding is not None and binding.type.kind in {
                        "integer",
                        "boolean",
                    }
                else:
                    scalar = (
                        ref is not None
                        and ref.kind == "universe"
                        and function_node is not None
                        and function_node.text in _SCALAR_BASIC_TYPES
                    )
                if not scalar:
                    raise _Unsupported("binding_unavailable", _span(node))
                if len(arguments) != 1:
                    raise _Unsupported(
                        "unsupported_expression", _span(node)
                    )
                return self.expression(
                    arguments[0], fn, params, locals_, transfers, count,
                    depth + 1,
                )
            if call.kind == "builtin":
                # Only the pure builtins reachable in a scalar fragment
                # are admitted — the result unions every argument's
                # dependencies; `panic`, `len`, `cap`, `append` and the
                # rest stay opaque (`len`/`cap` can only take values no
                # supported binding can hold).
                function_node = node.child_by_field_name("function")
                while (
                    function_node is not None
                    and function_node.type == "parenthesized_expression"
                ):
                    function_node = next(
                        iter(function_node.named_children), None
                    )
                name = function_node.text if function_node is not None else b""
                if name not in {b"min", b"max"}:
                    raise _Unsupported("unresolved_or_opaque_call", _span(node))
                if not arguments:
                    raise _Unsupported("unsupported_expression", _span(node))
                deps = frozenset()
                for arg in arguments:
                    deps |= self.expression(
                        arg, fn, params, locals_, transfers, count,
                        depth + 1,
                    )
                return deps
            if call.kind == "direct_import":
                # The callee lives in a resolved imported unit; its body is
                # opaque here. The result may depend on every argument — an
                # over-approximation — and the recorded target is the
                # imported unit's own binding identity, so a regenerated
                # report for it still flags this summary via
                # `stale_dependents`. Package-level state is not modelled.
                actual = tuple(
                    self.expression(
                        arg, fn, params, locals_, transfers, count, depth + 1
                    )
                    for arg in arguments
                )
                result = frozenset().union(*actual) if actual else frozenset()
                transfers.append(CallTransfer(call.span, call.target, actual, result))
                return result
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
    builder = _Builder(
        {0: raw}, snapshot, key, lambda bid: snapshot.cfg_for_function(source, bid)
    )
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


def summarize_go_package(
    sources: "dict[str, str] | list[str]", snapshot: GoPackageSnapshot
) -> GoSummarySet:
    """The multi-file package variant of `summarize_go`.

    One package unit — every function shares the package scope, calls
    across file boundaries resolve to `direct_local`, and every binding
    identity carries its declaring file's digest, so replacing one file
    only churns that file's identities (`stale_dependents` still
    applies). `sources` maps each declared file name to its contents
    (or lists them in declaration order); digests re-validate.

    Calls into host-resolved imported units record `direct_import`
    transfers: the callee body is opaque, so the result is treated as
    potentially depending on every argument — an over-approximation;
    package-level state is not modelled. The target is the imported
    unit's own binding identity, so regenerating that unit's report
    churns it and `stale_dependents` still flags dependents.
    """
    raws, key = _package_context(snapshot, sources)
    builder = _Builder(
        dict(enumerate(raws)),
        snapshot,
        key,
        lambda bid: snapshot.cfg_for_function(sources, bid),
    )
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
