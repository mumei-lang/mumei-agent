"""C06 Rust scalar interprocedural summaries — slice 0.

Mirrors `sol_interprocedural.py`'s model on a single Rust
source file: scalar params (`i*`/`u*`/`f*`/`bool`/`char`),
`let` declarations, if/else joins, a one-pass loop
may-analysis, intra-file function calls, and return/tail-
expression dependency tracking. Everything outside the
fragment stays closed (gap recorded).

- `summarize_rust(source)` → `RustSummarySet` with
  `context_key`, `functions`, and `profile`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

PROFILE = "mumei.rust-interprocedural/v0"
MAX_NODES = 20000
MAX_FUNCTIONS = 256
MAX_INLINE_DEPTH = 48
MAX_SOURCE_BYTES = 64 * 1024

_SCALAR = (
    lambda t: t.startswith(("i8", "i16", "i32", "i64", "i128",
                           "u8", "u16", "u32", "u64", "u128",
                           "f32", "f64", "usize", "isize"))
    or t in {"bool", "char"}
)


@dataclass(frozen=True)
class RustGap:
    reason: str
    byte: int


@dataclass(frozen=True)
class RustCall:
    byte: int
    name: str | None
    actual: tuple
    returns: frozenset | None


@dataclass
class RustFunctionSummary:
    name: str
    params: tuple
    available: bool
    return_dependencies: frozenset | None
    calls: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    effects: str = "none_in_supported_fragment"


@dataclass
class RustSummarySet:
    context_key: str
    profile: str
    functions: list


class _Unsupported(Exception):
    def __init__(self, reason, byte):
        super().__init__(reason)
        self.reason = reason
        self.byte = byte


def _children(node):
    return [c for c in node.children if c.is_named]


def _span(node):
    return node.start_byte


def _scalar_type(tnode):
    if tnode is None:
        return False
    if tnode.type == "primitive_type":
        return _SCALAR(tnode.text.decode())
    return False


class _Builder:
    def __init__(self, source: bytes):
        self.source = source
        self.count = [0]
        self.functions: dict[str, object] = {}
        self.summaries: dict[str, RustFunctionSummary] = {}
        self._inline_depth = 0
        self._writes: list = []
        self._decls: list = []

    # -- unit scan -------------------------------------------------

    def build(self) -> RustSummarySet:
        from tree_sitter import Language, Parser
        import tree_sitter_rust

        parser = Parser(Language(tree_sitter_rust.language()))
        root = parser.parse(self.source).root_node
        for top in _children(root):
            if top.type != "function_item":
                continue
            name = top.child_by_field_name("name")
            if name is None:
                continue
            self.functions[name.text.decode()] = top
        if len(self.functions) > MAX_FUNCTIONS:
            raise _Unsupported("analysis_limit", 0)
        summaries = []
        for name, fn_node in self.functions.items():
            try:
                summaries.append(self._summarize(name, fn_node))
            except _Unsupported as u:
                summaries.append(
                    RustFunctionSummary(
                        name=name, params=(), available=False,
                        return_dependencies=None,
                        gaps=[RustGap(u.reason, u.byte)],
                        effects="unknown",
                    )
                )
        return RustSummarySet(
            context_key=hashlib.sha256(self.source).hexdigest()[:16],
            profile=PROFILE,
            functions=summaries,
        )

    # -- per-function summary --------------------------------------

    def _summarize(self, name, fn_node) -> RustFunctionSummary:
        self._writes.append(set())
        self._decls.append(set())
        params = fn_node.child_by_field_name("parameters")
        param_names = []
        locals_: dict = {}
        param_index: dict = {}
        if params is not None:
            for p in _children(params):
                if p.type != "parameter":
                    continue
                pat = p.child_by_field_name("pattern")
                typ = p.child_by_field_name("type")
                if (
                    pat is None
                    or pat.type != "identifier"
                    or not _scalar_type(typ)
                ):
                    raise _Unsupported(
                        "unsupported_parameter", _span(p)
                    )
                pname = pat.text.decode()
                idx = len(param_names)
                param_names.append(pname)
                param_index[pname] = idx
                locals_[pname] = frozenset({idx})
        summary = RustFunctionSummary(
            name=name, params=(), available=False,
            return_dependencies=None,
        )
        body = fn_node.child_by_field_name("body")
        ret = (
            self._block(body, locals_, param_index, summary)
            if body is not None
            else None
        )
        self._writes.pop()
        self._decls.pop()
        ret_mark = getattr(summary, "return_mark", None)
        if (
            ret is None
            and ret_mark is None
            and fn_node.child_by_field_name("return_type") is not None
        ):
            raise _Unsupported("missing_return", _span(fn_node))
        ret = (ret or frozenset()) | (ret_mark or frozenset())
        summary.params = tuple(param_names)
        summary.return_dependencies = ret
        summary.available = True
        return summary

    # -- statements -------------------------------------------------

    def _block(self, block, locals_, param_index, summary):
        ret = None
        for st in _children(block):
            self.count[0] += 1
            if self.count[0] > MAX_NODES:
                raise _Unsupported("analysis_limit", _span(st))
            r = self._statement(st, locals_, param_index, summary)
            if r is not None:
                ret = r if ret is None else ret | r
        # A block's trailing bare expression is its value —
        # handled inside _statement's expression arm.
        return ret

    def _statement(self, st, locals_, param_index, summary):
        t = st.type
        if t == "let_declaration":
            pat = st.child_by_field_name("pattern")
            val = st.child_by_field_name("value")
            if pat is None or pat.type != "identifier":
                raise _Unsupported(
                    "unsupported_statement", _span(st)
                )
            deps = (
                self._expr(val, locals_, param_index, summary)
                if val is not None
                else frozenset()
            )
            locals_[pat.text.decode()] = deps
            if self._writes:
                self._writes[-1].add(pat.text.decode())
            if self._decls:
                self._decls[-1].add(pat.text.decode())
            return None
        if t == "return_expression":
            val = next(
                (
                    c
                    for c in _children(st)
                    if c.type not in {"return"}
                ),
                None,
            )
            deps = (
                self._expr(val, locals_, param_index, summary)
                if val is not None
                else frozenset()
            )
            summary.return_mark = (
                deps
                if getattr(summary, "return_mark", None) is None
                else summary.return_mark | deps
            )
            return deps
        if t == "expression_statement":
            inner = next(
                (c for c in _children(st)), None
            )
            if inner is None:
                return None
            if inner.type in {
                "assignment_expression",
                "compound_assignment_expr",
            }:
                self._assign(inner, locals_, param_index, summary)
                return None
            if inner.type == "call_expression":
                self._call(
                    inner, locals_, param_index, summary, void=True
                )
                return None
            r = self._statement(inner, locals_, param_index, summary)
            if r is not None:
                return r
            return None
        if t == "if_expression":
            return self._if(st, locals_, param_index, summary)
        if t in {
            "while_expression", "loop_expression", "for_expression",
        }:
            return self._loop(st, locals_, param_index, summary)
        if t == "match_expression":
            return self._match(st, locals_, param_index, summary)
        if t == "block":
            return self._block(st, locals_, param_index, summary)
        if t in {"break_expression", "continue_expression"}:
            return None
        if t in {
            "assignment_expression", "compound_assignment_expr",
        }:
            self._assign(st, locals_, param_index, summary)
            return None
        if t == "call_expression":
            # Bare `f(x)` in block position is the block's tail
            # value; `f(x);` is voided by expression_statement.
            return self._call(
                st, locals_, param_index, summary
            )
        # A trailing bare expression — the block's value.
        if t in _EXPR_TYPES:
            return self._expr(st, locals_, param_index, summary)
        raise _Unsupported("unsupported_statement", _span(st))

    def _if(self, st, locals_, param_index, summary):
        cond = st.child_by_field_name("condition")
        if cond is not None and cond.type == "let_condition":
            raise _Unsupported("unsupported_statement", _span(st))
        cons = st.child_by_field_name("consequence")
        alt = st.child_by_field_name("alternative")
        merged = (
            self._expr(cond, locals_, param_index, summary)
            if cond is not None
            else frozenset()
        )
        left_locals = dict(locals_)
        right_locals = dict(locals_)
        left_ret = (
            self._statement(cons, left_locals, param_index, summary)
            if cons is not None
            else None
        )
        right_ret = None
        if alt is not None:
            if alt.type == "else_clause":
                altb = next(
                    (c for c in _children(alt)), None
                )
            else:
                altb = alt
            right_ret = (
                self._statement(
                    altb, right_locals, param_index, summary
                )
                if altb is not None
                else None
            )
        for name in set(left_locals) | set(right_locals):
            locals_[name] = (
                left_locals.get(name, frozenset())
                | right_locals.get(name, frozenset())
                | merged
            )
        ret = None
        if left_ret is not None:
            ret = left_ret
        if right_ret is not None:
            ret = right_ret if ret is None else ret | right_ret
        if ret is not None:
            ret = ret | merged
        return ret

    def _match(self, st, locals_, param_index, summary):
        scrut = st.child_by_field_name("value")
        mdeps = (
            self._expr(scrut, locals_, param_index, summary)
            if scrut is not None
            else frozenset()
        )
        arm_scopes = []
        ret = None
        for c in _children(st):
            if c.type != "match_block":
                continue
            for arm in _children(c):
                if arm.type != "match_arm":
                    continue
                scope = dict(locals_)
                aret = None
                for ac in _children(arm):
                    if ac.type in {"match_pattern", "=>"}:
                        continue
                    aret = self._statement(
                        ac, scope, param_index, summary
                    )
                arm_scopes.append(scope)
                if aret is not None:
                    ret = aret if ret is None else ret | aret
        for name in set().union(*arm_scopes) if arm_scopes else set():
            merged = mdeps
            for sc in arm_scopes:
                merged |= sc.get(name, frozenset())
            locals_[name] = locals_.get(name, frozenset()) | merged
        if ret is not None:
            ret = ret | mdeps
        return ret

    def _loop(self, st, locals_, param_index, summary):
        cond = st.child_by_field_name("condition")
        body = st.child_by_field_name("body")
        inner = dict(locals_)
        self._writes.append(set())
        try:
            ret = None
            if body is not None:
                for c in _children(body):
                    r = self._statement(
                        c, inner, param_index, summary
                    )
                    if r is not None:
                        ret = r if ret is None else ret | r
        finally:
            touched = self._writes.pop()
        merged = (
            self._expr(cond, inner, param_index, summary)
            if cond is not None and cond.type != "let_condition"
            else frozenset()
        )
        for name in list(locals_):
            deps = inner.get(name, frozenset())
            if deps != locals_[name] or name in touched:
                locals_[name] = locals_[name] | deps | merged
        return ret

    # -- assignment / call ------------------------------------------

    def _assign(self, expr, locals_, param_index, summary):
        left = expr.child_by_field_name("left")
        right = expr.child_by_field_name("right")
        if (
            left is not None
            and left.type == "identifier"
            and left.text.decode() in locals_
        ):
            deps = (
                self._expr(right, locals_, param_index, summary)
                if right is not None
                else frozenset()
            )
            name = left.text.decode()
            if expr.type == "compound_assignment_expr":
                deps |= locals_[name]
            locals_[name] = deps
            if self._writes:
                self._writes[-1].add(name)
            return deps
        if left is not None and left.type in _EXPR_TYPES:
            # `*p = v`, `x.f = v`, `a[i] = v` — non-scalar
            # targets: the value's deps still flow, but the
            # slot model can't place them. Evaluate both sides.
            deps = (
                self._expr(right, locals_, param_index, summary)
                if right is not None
                else frozenset()
            )
            try:
                deps |= self._expr(
                    left, locals_, param_index, summary
                )
            except _Unsupported:
                pass
            return deps
        raise _Unsupported("unsupported_statement", _span(expr))

    def _call(self, node, locals_, param_index, summary, void=False):
        fn_expr = node.child_by_field_name("function")
        arglist = node.child_by_field_name("arguments")
        actual = []
        if arglist is not None:
            for a in _children(arglist):
                actual.append(
                    self._expr(a, locals_, param_index, summary)
                )
        actual_t = tuple(actual)
        actual_union = frozenset()
        for a in actual:
            actual_union |= a
        name = (
            fn_expr.text.decode()
            if fn_expr is not None
            and fn_expr.type == "identifier"
            else None
        )
        if name is None or name not in self.functions:
            # method calls, fn-pointers, macros — opaque record.
            cname = fn_expr.text.decode() if fn_expr is not None else None
            summary.calls.append(
                RustCall(_span(node), cname, actual_t,
                         None if void else actual_union)
            )
            if summary.effects != "state_writes":
                summary.effects = "unknown"
            return frozenset() if void else actual_union
        callee = self.summaries.get(name)
        if callee is None:
            if self._inline_depth >= MAX_INLINE_DEPTH:
                raise _Unsupported("analysis_limit", _span(node))
            self._inline_depth += 1
            try:
                callee = self._summarize(
                    name, self.functions[name]
                )
            finally:
                self._inline_depth -= 1
            self.summaries[name] = callee
        if not callee.available or callee.return_dependencies is None:
            summary.calls.append(
                RustCall(_span(node), name, actual_t, None)
            )
            if summary.effects != "state_writes":
                summary.effects = "unknown"
            return actual_union
        deps = frozenset()
        for i in callee.return_dependencies:
            if i < len(actual):
                deps |= actual[i]
        summary.calls.append(
            RustCall(_span(node), name, actual_t, deps)
        )
        if callee.effects == "unknown" and summary.effects != "state_writes":
            summary.effects = "unknown"
        return frozenset() if void else deps

    # -- expressions -------------------------------------------------

    def _expr(self, node, locals_, param_index, summary):
        self.count[0] += 1
        if self.count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        t = node.type
        if t == "identifier":
            name = node.text.decode()
            if name in locals_:
                return locals_[name]
            raise _Unsupported("binding_unavailable", _span(node))
        if t in {
            "integer_literal", "float_literal", "boolean_literal",
            "char_literal", "string_literal", "negative_literal",
            "unit_expression",
        }:
            return frozenset()
        if t in {
            "binary_expression", "compound_assignment_expr",
        }:
            deps = frozenset()
            for c in _children(node):
                deps |= self._expr(
                    c, locals_, param_index, summary
                )
            return deps
        if t in {
            "unary_expression", "reference_expression",
            "try_expression", "parenthesized_expression",
            "type_cast_expression", "prefix_expression",
        }:
            deps = frozenset()
            for c in _children(node):
                deps |= self._expr(
                    c, locals_, param_index, summary
                )
            return deps
        if t == "call_expression":
            return self._call(
                node, locals_, param_index, summary
            )
        if t == "assignment_expression":
            return self._assign(
                node, locals_, param_index, summary
            )
        if t == "if_expression":
            return self._if(node, locals_, param_index, summary)
        if t == "match_expression":
            return self._match(node, locals_, param_index, summary)
        if t in {
            "while_expression", "loop_expression", "for_expression",
        }:
            return self._loop(node, locals_, param_index, summary)
        if t == "block":
            return self._block(node, locals_, param_index, summary) or frozenset()
        if t in {"break_expression", "continue_expression"}:
            return frozenset()
        if t == "tuple_expression":
            deps = frozenset()
            for c in _children(node):
                deps |= self._expr(
                    c, locals_, param_index, summary
                )
            return deps
        raise _Unsupported("unsupported_expression", _span(node))


_EXPR_TYPES = {
    "identifier", "integer_literal", "float_literal",
    "boolean_literal", "char_literal", "string_literal",
    "negative_literal", "unit_expression", "binary_expression",
    "compound_assignment_expr", "unary_expression",
    "reference_expression", "try_expression",
    "parenthesized_expression", "type_cast_expression",
    "prefix_expression", "call_expression",
    "assignment_expression", "if_expression",
    "match_expression", "while_expression", "loop_expression",
    "for_expression", "block", "break_expression",
    "continue_expression", "tuple_expression",
}


def summarize_rust(source) -> RustSummarySet:
    if isinstance(source, str):
        source = source.encode()
    if len(source) > MAX_SOURCE_BYTES:
        raise _Unsupported("analysis_limit", 0)
    return _Builder(source).build()
