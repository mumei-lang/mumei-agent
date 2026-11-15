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


def _arg_root(node):
    """Innermost identifier under reference/member/index
    wrappers — the slot a `&mut` argument writes through."""
    while node is not None:
        if node.type in {"identifier", "self"}:
            return node.text.decode()
        if node.type == "field_expression":
            node = node.child_by_field_name("value")
            continue
        if node.type == "index_expression":
            node = next(
                (
                    c for c in _children(node)
                    if c.type != "type_cast_expression"
                ),
                None,
            )
            continue
        kids = [
            c for c in _children(node)
            if c.type not in _TYPE_NAMES
        ]
        if len(kids) == 1:
            node = kids[0]
            continue
        return None
    return None


def _pattern_bindings(pat):
    """Identifier names bound by a pattern, skipping every
    `type` subtree (`Some(v)` binds `v`, not `Some`)."""
    if pat is None:
        return []
    if pat.type == "identifier":
        return [pat.text.decode()]
    out = []

    def walk(n):
        t = n.child_by_field_name("type")
        for c in _children(n):
            if c is t:
                continue
            if c.type == "identifier":
                out.append(c.text.decode())
                continue
            walk(c)

    walk(pat)
    return out


def _descendants(node):
    out = []

    def walk(n):
        for c in n.children:
            if not c.is_named:
                continue
            out.append(c)
            walk(c)

    walk(node)
    return out


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
        self.methods: dict = {}
        # `const K` / `static S` — compile-time constant, so a
        # read is dep-free; `static mut` writes mark unknown.
        self.globals: set = set()
        self.mut_globals: set = set()
        self._in_progress: set = set()

    # -- unit scan -------------------------------------------------

    def build(self) -> RustSummarySet:
        from tree_sitter import Language, Parser
        import tree_sitter_rust

        parser = Parser(Language(tree_sitter_rust.language()))
        root = parser.parse(self.source).root_node
        for top in _children(root):
            if top.type == "function_item":
                name = top.child_by_field_name("name")
                if name is None:
                    continue
                self.functions[name.text.decode()] = top
                continue
            if top.type in {"const_item", "static_item"}:
                gname = top.child_by_field_name("name")
                if gname is not None:
                    self.globals.add(gname.text.decode())
                    if any(
                        c.type == "mutable_specifier"
                        for c in top.children
                    ):
                        self.mut_globals.add(
                            gname.text.decode()
                        )
                continue
            if top.type != "impl_item":
                continue
            decls = top.child_by_field_name("body")
            typ = top.child_by_field_name("type")
            if decls is None or typ is None:
                continue
            tname = typ.text.decode()
            for item in _children(decls):
                if item.type != "function_item":
                    continue
                name = item.child_by_field_name("name")
                if name is None:
                    continue
                base = name.text.decode()
                ukey = f"{tname}.{base}"
                n = 1
                while ukey in self.functions:
                    n += 1
                    ukey = f"{tname}.{base}#{n}"
                self.functions[ukey] = item
                self.methods.setdefault(base, set()).add(ukey)
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
        self._in_progress.add(name)
        self._writes.append(set())
        self._decls.append(set())
        params = fn_node.child_by_field_name("parameters")
        param_names = []
        locals_: dict = {}
        param_index: dict = {}
        if params is not None:
            for p in _children(params):
                if p.type == "self_parameter":
                    idx = len(param_names)
                    param_names.append("self")
                    param_index["self"] = idx
                    locals_["self"] = frozenset({idx})
                    continue
                if p.type != "parameter":
                    continue
                pat = p.child_by_field_name("pattern")
                if pat is None:
                    continue
                idx = len(param_names)
                if pat.type == "identifier":
                    # Any identifier param — scalar or not —
                    # gets a dep index (over-approx: reads carry
                    # the param's dep).
                    pname = pat.text.decode()
                    param_names.append(pname)
                    param_index[pname] = idx
                    locals_[pname] = frozenset({idx})
                    continue
                # Destructured `(a, b)` / `S { x }` patterns —
                # bind each identifier inside to the dep index.
                bound = [
                    d for d in _descendants(pat)
                    if d.type == "identifier"
                ]
                if not bound:
                    continue
                param_names.append(pat.text.decode())
                for d in bound:
                    locals_[d.text.decode()] = frozenset({idx})
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
        self._in_progress.discard(name)
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
            if pat is None:
                return None
            deps = (
                self._expr(val, locals_, param_index, summary)
                if val is not None
                else frozenset()
            )
            bound = _pattern_bindings(pat)
            if not bound:
                raise _Unsupported(
                    "unsupported_statement", _span(st)
                )
            for bname in bound:
                locals_[bname] = deps
                if self._writes:
                    self._writes[-1].add(bname)
                if self._decls:
                    self._decls[-1].add(bname)
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
        if t in {"block", "unsafe_block"}:
            if t == "unsafe_block":
                inner = next(
                    (c for c in _children(st)
                     if c.type == "block"),
                    None,
                )
                return (
                    self._block(
                        inner, locals_, param_index, summary
                    )
                    if inner is not None else None
                )
            return self._block(st, locals_, param_index, summary)
        if t == "break_expression":
            # `break v` — `loop { }` yields the value; under the
            # may-model the break deps join the loop's result.
            deps = frozenset()
            for c in _children(st):
                try:
                    deps |= self._expr(
                        c, locals_, param_index, summary
                    )
                except _Unsupported:
                    continue
            return deps
        if t == "continue_expression":
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
        cons = st.child_by_field_name("consequence")
        alt = st.child_by_field_name("alternative")
        merged = frozenset()
        lc_pat = None
        if cond is not None:
            if cond.type == "let_condition":
                lc_val = cond.child_by_field_name("value")
                lc_pat = cond.child_by_field_name("pattern")
                if lc_val is not None:
                    merged = self._expr(
                        lc_val, locals_, param_index, summary
                    )
            else:
                merged = self._expr(
                    cond, locals_, param_index, summary
                )
        left_locals = dict(locals_)
        if lc_pat is not None:
            # `if let Some(v) = it` — `v` binds the value's deps
            # inside the consequence scope.
            for bname in _pattern_bindings(lc_pat):
                left_locals[bname] = merged
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
                    if ac.type == "=>":
                        continue
                    if ac.type == "match_pattern":
                        # `Some(v) => v` — `v` binds the
                        # scrutinee's deps in this arm.
                        for bname in _pattern_bindings(ac):
                            scope[bname] = mdeps
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
        lc_merged = frozenset()
        if (
            cond is not None
            and cond.type == "let_condition"
        ):
            # `while let Some(v) = it` — the body reads the
            # bound names, so evaluate the value first.
            lc_val = cond.child_by_field_name("value")
            lc_pat = cond.child_by_field_name("pattern")
            if lc_val is not None:
                lc_merged = self._expr(
                    lc_val, inner, param_index, summary
                )
                if lc_pat is not None:
                    for bname in _pattern_bindings(lc_pat):
                        inner[bname] = lc_merged
        if st.type == "for_expression":
            # `for i in 0..n` — bind the pattern name to the
            # iterator's deps in the loop scope.
            pat = st.child_by_field_name("pattern")
            val = st.child_by_field_name("value")
            if pat is not None and pat.type == "identifier":
                inner[pat.text.decode()] = (
                    self._expr(
                        val, inner, param_index, summary
                    )
                    if val is not None
                    else frozenset()
                )
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
        merged = lc_merged
        if (
            cond is not None
            and cond.type != "let_condition"
        ):
            merged |= self._expr(
                cond, inner, param_index, summary
            )
        for name in list(locals_):
            deps = inner.get(name, frozenset())
            if deps != locals_[name] or name in touched:
                locals_[name] = locals_[name] | deps | merged
        if ret is not None:
            # `while s > 0 { return x; }` — whether the body ran
            # depends on the condition.
            ret = ret | merged
        return ret

    # -- assignment / call ------------------------------------------

    def _assign(self, expr, locals_, param_index, summary):
        left = expr.child_by_field_name("left")
        right = expr.child_by_field_name("right")
        if (
            left is not None
            and left.type == "identifier"
            and (
                left.text.decode() in locals_
                or left.text.decode() in self.mut_globals
            )
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
            if name in self.mut_globals:
                # `static mut` writes are observable —
                # unknown effects.
                summary.effects = "unknown"
            return deps
        if left is not None and left.type in _EXPR_TYPES:
            # `*p = v`, `x.f = v`, `a[i] = v` — non-scalar
            # targets: the value's deps still flow. When the
            # root is a parameter (`self`, `p: &mut T`) record
            # the write so callers can merge it into the slot
            # the argument binds.
            deps = (
                self._expr(right, locals_, param_index, summary)
                if right is not None
                else frozenset()
            )
            root = _arg_root(left)
            if root is not None and root in param_index:
                pw = getattr(
                    summary, "param_writes", None
                )
                if pw is None:
                    pw = {}
                    summary.param_writes = pw
                pw[param_index[root]] = (
                    pw.get(param_index[root], frozenset())
                    | deps
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
        roots = []
        if arglist is not None:
            for a in _children(arglist):
                actual.append(
                    self._expr(a, locals_, param_index, summary)
                )
                roots.append(_arg_root(a))
        actual_t = tuple(actual)
        actual_union = frozenset()
        for a in actual:
            actual_union |= a
        recv_deps = frozenset()
        recv = None
        fld = None
        if (
            fn_expr is not None
            and fn_expr.type == "field_expression"
        ):
            # `x.m(args)` — the receiver's deps join the opaque
            # result like another argument.
            recv = fn_expr.child_by_field_name("value")
            fld = fn_expr.child_by_field_name("field")
            if recv is not None:
                try:
                    recv_deps = self._expr(
                        recv, locals_, param_index, summary
                    )
                except _Unsupported:
                    recv_deps = frozenset()
            actual_union |= recv_deps
        name = None
        if (
            fn_expr is not None
            and fn_expr.type == "identifier"
        ):
            name = fn_expr.text.decode()
        elif (
            fn_expr is not None
            and fn_expr.type == "scoped_identifier"
        ):
            # `T::f(args)` — resolve `T.f` among impl methods.
            path = fn_expr.child_by_field_name("path")
            nm = fn_expr.child_by_field_name("name")
            if path is not None and nm is not None:
                cand = (
                    f"{path.text.decode()}."
                    f"{nm.text.decode()}"
                )
                if cand in self.functions:
                    name = cand
        elif (
            fn_expr is not None
            and fn_expr.type == "generic_function"
        ):
            # `f::<T>(args)` — same function, resolve the inner
            # callee name.
            inner_fn = fn_expr.child_by_field_name("function")
            if (
                inner_fn is not None
                and inner_fn.type == "identifier"
            ):
                name = inner_fn.text.decode()
        elif (
            fn_expr is not None
            and fn_expr.type == "field_expression"
        ):
            # `x.m(args)` — resolve `m` when exactly one impl in
            # the file defines it; `self` binds the receiver deps
            # (param index 0).
            if fld is not None:
                ukeys = self.methods.get(
                    fld.text.decode(), set()
                )
                if len(ukeys) == 1:
                    name = next(iter(ukeys))
                    actual.insert(0, recv_deps)
                    actual_t = tuple(actual)
                    recv_root = (
                        _arg_root(recv)
                        if recv is not None else None
                    )
                    roots.insert(0, recv_root)
        if (
            name is None
            and fld is not None
            and fld.text.decode() in _CONTAINER_WRITES
        ):
            rname = _arg_root(recv) if recv is not None else None
            if rname is not None:
                slot = (
                    locals_.get(rname, frozenset())
                    | actual_union
                )
                locals_[rname] = slot
                if self._writes:
                    self._writes[-1].add(rname)
                summary.calls.append(
                    RustCall(
                        _span(node),
                        f"{recv.text.decode()}."
                        f"{fld.text.decode()}",
                        actual_t, None,
                    )
                )
                return frozenset() if void else slot
        if name is None or name not in self.functions:
            # method calls, fn-pointers, enum constructors
            # (`Some(x)`), external `crate::f` — opaque record.
            bound = (
                locals_.get(name, frozenset())
                if name is not None
                else frozenset()
            )
            result = actual_union | bound
            cname = fn_expr.text.decode() if fn_expr is not None else None
            summary.calls.append(
                RustCall(_span(node), cname, actual_t,
                         None if void else result)
            )
            if summary.effects != "state_writes":
                summary.effects = "unknown"
            return frozenset() if void else result
        if name in self._in_progress:
            # Recursion — no fixpoint in the one-pass model;
            # record it opaquely.
            summary.calls.append(
                RustCall(_span(node), name, actual_t,
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
        for pidx, pdeps in getattr(
            callee, "param_writes", {}
        ).items():
            # `f(&mut p)` / `p.set(x)` — writes the callee made
            # through the parameter merge into the slot the
            # caller's argument roots at.
            if pidx >= len(roots):
                continue
            rname = roots[pidx]
            if rname is None:
                if summary.effects != "state_writes":
                    summary.effects = "unknown"
                continue
            locals_[rname] = (
                locals_.get(rname, frozenset()) | pdeps
            )
            if self._writes:
                self._writes[-1].add(rname)
        if callee.effects == "unknown" and summary.effects != "state_writes":
            summary.effects = "unknown"
        return frozenset() if void else deps

    # -- expressions -------------------------------------------------

    def _expr(self, node, locals_, param_index, summary):
        self.count[0] += 1
        if self.count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        t = node.type
        if t == "identifier" or t == "self":
            name = node.text.decode()
            if name in locals_:
                return locals_[name]
            if name in self.globals:
                return frozenset()
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
                if c.type in _TYPE_NAMES:
                    continue
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
        if t == "break_expression":
            deps = frozenset()
            for c in _children(node):
                try:
                    deps |= self._expr(
                        c, locals_, param_index, summary
                    )
                except _Unsupported:
                    continue
            return deps
        if t == "continue_expression":
            return frozenset()
        if t == "closure_expression":
            # `|a, b| body` — the closure value's deps are the
            # body's deps with its parameters bound to nothing;
            # captured names carry their real deps.
            cparams = node.child_by_field_name("parameters")
            cbody = node.child_by_field_name("body")
            if cbody is None:
                return frozenset()
            inner = dict(locals_)
            if cparams is not None:
                for p in _children(cparams):
                    if p.type == "parameter":
                        pp = p.child_by_field_name("pattern")
                        for bname in (
                            _pattern_bindings(pp)
                            if pp is not None else ()
                        ):
                            inner[bname] = frozenset()
                    elif p.type == "identifier":
                        inner[p.text.decode()] = frozenset()
            try:
                return self._expr(
                    cbody, inner, param_index, summary
                )
            except _Unsupported:
                return frozenset()
        if t == "closure_expression":
            # `|a, b| body` — the closure value's deps are the
            # body's deps with its parameters bound to nothing;
            # captured names carry their real deps.
            cparams = node.child_by_field_name("parameters")
            cbody = node.child_by_field_name("body")
            if cbody is None:
                return frozenset()
            inner = dict(locals_)
            if cparams is not None:
                for p in _children(cparams):
                    if p.type == "parameter":
                        pp = p.child_by_field_name("pattern")
                        for bname in (
                            _pattern_bindings(pp)
                            if pp is not None else ()
                        ):
                            inner[bname] = frozenset()
                    elif p.type == "identifier":
                        inner[p.text.decode()] = frozenset()
            try:
                return self._expr(
                    cbody, inner, param_index, summary
                )
            except _Unsupported:
                return frozenset()
        if t == "unsafe_block":
            inner = next(
                (c for c in _children(node)
                 if c.type == "block"),
                None,
            )
            return (
                self._block(
                    inner, locals_, param_index, summary
                )
                or frozenset()
            ) if inner is not None else frozenset()
        if t == "macro_invocation":
            # `m!(tokens)` — opaque call; deps = every evaluable
            # token inside the token tree (macros have arbitrary
            # grammar, so a token that fails contributes nothing).
            mname = node.child_by_field_name("macro")
            cname = (
                f"{mname.text.decode()}!"
                if mname is not None else None
            )
            deps = frozenset()
            for c in _children(node):
                if c.type != "token_tree":
                    continue
                for tok in _children(c):
                    try:
                        deps |= self._expr(
                            tok, locals_, param_index, summary
                        )
                    except _Unsupported:
                        continue
            summary.calls.append(
                RustCall(_span(node), cname, (deps,), deps)
            )
            if summary.effects != "state_writes":
                summary.effects = "unknown"
            return deps
        if t in {
            "tuple_expression", "range_expression",
            "array_expression", "struct_expression",
            "field_expression", "index_expression",
            "await_expression", "generic_function",
        }:
            # Containers/member access/`f!()`/`x.await` — union
            # every named child's deps (over-approx: field/index
            # reads carry the receiver's deps). Type and field
            # names are not expressions.
            deps = frozenset()
            for c in _children(node):
                if c.type in _TYPE_NAMES:
                    continue
                deps |= self._expr(
                    c, locals_, param_index, summary
                )
            return deps
        raise _Unsupported("unsupported_expression", _span(node))


_CONTAINER_WRITES = {
    "push", "insert", "extend", "push_front", "push_back",
    "add", "set", "put", "append", "retain", "clear",
}

_TYPE_NAMES = {
    "primitive_type", "type_identifier", "generic_type",
    "scoped_identifier", "field_identifier",
    "shorthand_field_identifier", "type_arguments",
    "type_parameters", "lifetime", "attribute_item",
    "tuple_type", "array_type", "function_type",
    "reference_type", "pointer_type", "unit_type",
    "abstract_type", "trait_bounds", "higher_ranked_trait_bound",
    "removed_trait_bound", "bounded_type", "qualified_type",
    "mutable_specifier", "self_parameter", "visibility_modifier",
    "function_modifiers", "where_clause", "extern_modifier",
}

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
    "range_expression", "array_expression", "struct_expression",
    "field_expression", "index_expression", "await_expression",
    "macro_invocation", "generic_function", "closure_expression",
    "let_condition",
}


def summarize_rust(source) -> RustSummarySet:
    if isinstance(source, str):
        source = source.encode()
    if len(source) > MAX_SOURCE_BYTES:
        raise _Unsupported("analysis_limit", 0)
    return _Builder(source).build()
