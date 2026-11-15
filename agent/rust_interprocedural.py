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


# Declared-manifest restoration bounds and validators — the same
# fail-closed shape `GoSummarySet.from_dict` enforces: a manifest is
# declared data, so unknown keys, wrong types and oversize
# collections are malformed, never partially adopted.
MAX_MANIFEST_MEMBERS = 8192


def _require_manifest(condition: bool) -> None:
    if not condition:
        raise ValueError("declared summary manifest is malformed")


def _manifest_record(
    value, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> dict:
    if not isinstance(value, dict) or not (
        set(required) <= set(value) <= set(required) | set(optional)
    ):
        raise ValueError("declared summary manifest is malformed")
    return value


def _string(value) -> str:
    if type(value) is not str:
        raise ValueError("declared summary manifest is malformed")
    return value


def _boolean(value) -> bool:
    if type(value) is not bool:
        raise ValueError("declared summary manifest is malformed")
    return value


def _list(value) -> list:
    if type(value) is not list:
        raise ValueError("declared summary manifest is malformed")
    return value


def _deps_from_list(value) -> frozenset[int]:
    deps = _list(value)
    _require_manifest(
        len(deps) <= MAX_MANIFEST_MEMBERS
        and all(type(d) is int and d >= 0 for d in deps)
    )
    return frozenset(deps)


@dataclass(frozen=True)
class RustGap:
    reason: str
    byte: int

    def to_dict(self) -> dict:
        return {"reason": self.reason, "byte": self.byte}

    @classmethod
    def from_dict(cls, value) -> "RustGap":
        v = _manifest_record(value, ("reason", "byte"))
        _require_manifest(type(v["byte"]) is int and v["byte"] >= 0)
        return cls(_string(v["reason"]), v["byte"])


@dataclass(frozen=True)
class RustCall:
    byte: int
    name: str | None
    actual: tuple
    returns: frozenset | None

    def to_dict(self) -> dict:
        return {
            "byte": self.byte,
            "name": self.name,
            "arguments": [sorted(a) for a in self.actual],
            "result": (
                None if self.returns is None else sorted(self.returns)
            ),
        }

    @classmethod
    def from_dict(cls, value) -> "RustCall":
        v = _manifest_record(
            value, ("byte", "name", "arguments", "result")
        )
        _require_manifest(type(v["byte"]) is int and v["byte"] >= 0)
        _require_manifest(v["name"] is None or type(v["name"]) is str)
        arguments = _list(v["arguments"])
        _require_manifest(len(arguments) <= MAX_MANIFEST_MEMBERS)
        result = v["result"]
        return cls(
            v["byte"],
            v["name"],
            tuple(_deps_from_list(a) for a in arguments),
            None if result is None else _deps_from_list(result),
        )


@dataclass
class RustFunctionSummary:
    name: str
    params: tuple
    available: bool
    return_dependencies: frozenset | None
    calls: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    effects: str = "none_in_supported_fragment"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "parameters": list(self.params),
            "return_dependencies": (
                None
                if self.return_dependencies is None
                else sorted(self.return_dependencies)
            ),
            "calls": [c.to_dict() for c in self.calls],
            "gaps": [g.to_dict() for g in self.gaps],
            "effects": self.effects,
        }

    @classmethod
    def from_dict(cls, value) -> "RustFunctionSummary":
        v = _manifest_record(
            value,
            (
                "name",
                "available",
                "parameters",
                "return_dependencies",
                "calls",
                "gaps",
                "effects",
            ),
        )
        parameters = _list(v["parameters"])
        calls = _list(v["calls"])
        gaps = _list(v["gaps"])
        _require_manifest(
            len(parameters) <= MAX_MANIFEST_MEMBERS
            and len(calls) <= MAX_MANIFEST_MEMBERS
            and len(gaps) <= MAX_MANIFEST_MEMBERS
        )
        deps = v["return_dependencies"]
        restored_deps = None if deps is None else _deps_from_list(deps)
        restored_gaps = [RustGap.from_dict(g) for g in gaps]
        available = _boolean(v["available"])
        # A manifest may not contradict itself: `available` tracks
        # exactly "a result was derived and no gap was recorded" —
        # a forged flag cannot borrow trust the record lacks.
        _require_manifest(
            available == (restored_deps is not None)
            and available == (not restored_gaps)
        )
        return cls(
            _string(v["name"]),
            tuple(_string(p) for p in parameters),
            available,
            restored_deps,
            [RustCall.from_dict(c) for c in calls],
            restored_gaps,
            _string(v["effects"]),
        )


@dataclass
class RustSummarySet:
    context_key: str
    profile: str
    functions: list

    def to_dict(self) -> dict:
        return {
            "schema_version": self.profile,
            "context_key": self.context_key,
            "functions": [f.to_dict() for f in self.functions],
        }

    @classmethod
    def from_dict(cls, value) -> "RustSummarySet":
        """Restore a declared manifest — strict, bounded, fail-closed.

        The manifest is declared data, not trusted input: unknown or
        missing keys, wrong types and oversize collections are all
        malformed — the caller fails closed rather than adopting a
        partial set."""
        v = _manifest_record(
            value,
            ("schema_version", "context_key", "functions"),
        )
        _require_manifest(v["schema_version"] == PROFILE)
        functions = _list(v["functions"])
        _require_manifest(len(functions) <= MAX_MANIFEST_MEMBERS)
        return cls(
            _string(v["context_key"]),
            PROFILE,
            [RustFunctionSummary.from_dict(f) for f in functions],
        )


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
            if top.type == "mod_item":
                decls = top.child_by_field_name("body")
                mname = top.child_by_field_name("name")
                if decls is None or mname is None:
                    continue
                mtext = mname.text.decode()
                for item in _children(decls):
                    if item.type != "function_item":
                        continue
                    fname = item.child_by_field_name("name")
                    if fname is None:
                        continue
                    base = fname.text.decode()
                    ukey = f"{mtext}.{base}"
                    n = 1
                    while ukey in self.functions:
                        n += 1
                        ukey = f"{mtext}.{base}#{n}"
                    self.functions[ukey] = item
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
            context_key=hashlib.sha256(self.source).hexdigest(),
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
            idx = 0
            for p in _children(params):
                if p.type == "self_parameter":
                    param_names.append("self")
                    param_index["self"] = idx
                    locals_["self"] = frozenset({idx})
                    idx += 1
                    continue
                if p.type not in ("parameter", "variadic_parameter"):
                    continue
                pat = p.child_by_field_name("pattern")
                if pat is not None and pat.type == "identifier":
                    # Any identifier param — scalar or not —
                    # gets a dep index (over-approx: reads carry
                    # the param's dep).
                    pname = pat.text.decode()
                    param_names.append(pname)
                    param_index[pname] = idx
                    locals_[pname] = frozenset({idx})
                elif pat is not None:
                    # Destructured `(a, b)` / `S { x }` patterns —
                    # bind each identifier inside to the dep index.
                    bound = [
                        d for d in _descendants(pat)
                        if d.type == "identifier"
                    ]
                    if bound:
                        for d in bound:
                            locals_[d.text.decode()] = frozenset(
                                {idx}
                            )
                    param_names.append(pat.text.decode())
                else:
                    param_names.append("_")
                # Wildcards (`_`), pattern-less and unbound
                # patterns still consume a parameter slot —
                # `params` keeps a placeholder name so a dep
                # index stays aligned with the entry at that
                # position.
                idx += 1
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
        before_pw = dict(
            getattr(summary, "param_writes", None) or {}
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
        pw = getattr(summary, "param_writes", None)
        if pw:
            # A write inside a branch is conditioned on the
            # branch's deps — they join the recorded write.
            for key, val in pw.items():
                if val != before_pw.get(key, frozenset()):
                    pw[key] = val | merged
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
        before_pw = dict(
            getattr(summary, "param_writes", None) or {}
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
                if self._writes:
                    # An inner may-write is the parent's
                    # may-write too.
                    self._writes[-1].add(name)
        pw = getattr(summary, "param_writes", None)
        if pw:
            for key, val in pw.items():
                if val != before_pw.get(key, frozenset()):
                    pw[key] = val | merged
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
                deps |= locals_.get(name, frozenset())
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
            # targets. The target path's own deps (index
            # expressions, receiver roots) join the write, and
            # the rooted slot stores the union so later reads
            # see it. When the root is a parameter (`self`,
            # `p: &mut T`) the write is also recorded so callers
            # can merge it into the slot the argument binds.
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
            root = _arg_root(left)
            if root is not None:
                if root in locals_:
                    locals_[root] = locals_[root] | deps
                    if self._writes:
                        self._writes[-1].add(root)
                if root in param_index:
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
                if root in self.mut_globals:
                    # `static mut` writes are observable.
                    summary.effects = "unknown"
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
            # caller's argument roots at. `pdeps` live in the
            # callee's index space: dep `j` binds `actual[j]`.
            if pidx >= len(roots):
                continue
            projected = frozenset()
            for j in pdeps:
                if j < len(actual):
                    projected |= actual[j]
            rname = roots[pidx]
            if rname is None:
                if summary.effects != "state_writes":
                    summary.effects = "unknown"
                continue
            locals_[rname] = (
                locals_.get(rname, frozenset()) | projected
            )
            if self._writes:
                self._writes[-1].add(rname)
            if rname in self.mut_globals:
                summary.effects = "unknown"
            if rname in param_index:
                # The callee wrote through a reference this
                # function itself received — that is this
                # function's own param write for its callers.
                pw = getattr(
                    summary, "param_writes", None
                )
                if pw is None:
                    pw = {}
                    summary.param_writes = pw
                pw[param_index[rname]] = (
                    pw.get(param_index[rname], frozenset())
                    | projected
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


# Opt-in CLI routes — `python -m agent rust-summaries <file>` prints
# the summary set as deterministic JSON on stdout, and
# `python -m agent rust-summaries-accept <file> --manifest <PATH>
# --function <NAME>` accepts one function's declared summary under
# the strict whole-context gate (context key match + the function
# still present in the fresh derivation; `<NAME>` matches the
# emitted name or a bare member name when unambiguous). These change
# no default audit/CLI/MCP route: the analysis stays a conservative
# dependency report, not a proof, verdict or trust gate, and a host
# must invoke the subcommands explicitly. Inputs are bounded — an
# oversized source or manifest is an error, never a silently
# truncated analysis.
ACCEPT_PROFILE = "mumei.rust-summary-accept/v1"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024


def build_parser(parser=None):
    import argparse

    if parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent rust-summaries",
            description=(
                "Emit opt-in Rust interprocedural dependency "
                "summaries as JSON — a conservative report, not a "
                "proof or verdict."
            ),
        )
    parser.add_argument(
        "source",
        help="Path to a single Rust source file (at most 64 KiB).",
    )
    return parser


def build_accept_parser(parser=None):
    """Parser for ``rust-summaries-accept``: the produce route's
    declared inputs plus ``--manifest`` and ``--function`` naming the
    declared manifest and the function whose summary is accepted."""
    parser = build_parser(parser)
    parser.description = (
        "Re-derive the Rust summary set for one declared source "
        "and accept one function's summary under the strict "
        "whole-context gate."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="<PATH>",
        help=(
            "Summary manifest (mumei.rust-interprocedural/v0) "
            "to accept from."
        ),
    )
    parser.add_argument(
        "--function",
        required=True,
        metavar="<NAME>",
        help=(
            "Function whose summary to accept — the emitted name "
            "or a bare member name when it is unambiguous. Accepted "
            "only when the manifest's context key still matches the "
            "fresh derivation and the function survives in it."
        ),
    )
    return parser


def _emit(payload, code):
    import json
    import sys

    print(json.dumps(payload, sort_keys=True))
    sys.exit(code)


def _read_declared_source(path, schema):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "source_unreadable",
                    "detail": exc.strerror or str(exc),
                },
            },
            2,
        )
    if len(raw) > MAX_SOURCE_BYTES:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "source_too_large",
                    "limit_bytes": MAX_SOURCE_BYTES,
                },
            },
            2,
        )
    return raw


def _read_declared_manifest(path):
    import json

    try:
        with open(path, "rb") as handle:
            blob = handle.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        _emit(
            {
                "schema_version": ACCEPT_PROFILE,
                "error": {
                    "reason": "manifest_unreadable",
                    "detail": exc.strerror or str(exc),
                },
            },
            2,
        )
    if len(blob) > MAX_MANIFEST_BYTES:
        _emit(
            {
                "schema_version": ACCEPT_PROFILE,
                "error": {
                    "reason": "manifest_too_large",
                    "limit_bytes": MAX_MANIFEST_BYTES,
                },
            },
            2,
        )
    try:
        return RustSummarySet.from_dict(json.loads(blob))
    except (TypeError, UnicodeDecodeError):
        _emit(
            {
                "schema_version": ACCEPT_PROFILE,
                "error": {
                    "reason": "manifest_malformed",
                    "detail": "declared summary manifest is malformed",
                },
            },
            2,
        )
    except ValueError as exc:
        _emit(
            {
                "schema_version": ACCEPT_PROFILE,
                "error": {
                    "reason": "manifest_malformed",
                    "detail": str(exc),
                },
            },
            2,
        )


def _summarize_declared(raw, schema):
    try:
        return summarize_rust(raw)
    except _Unsupported as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {"reason": exc.reason},
            },
            2,
        )


def main(args=None) -> None:
    import json

    if args is None:
        args = build_parser().parse_args()
    raw = _read_declared_source(args.source, PROFILE)
    print(
        json.dumps(
            _summarize_declared(raw, PROFILE).to_dict(), sort_keys=True
        )
    )


def main_accept(args=None) -> None:
    if args is None:
        args = build_accept_parser().parse_args()
    declared = _read_declared_manifest(args.manifest)
    raw = _read_declared_source(args.source, ACCEPT_PROFILE)
    live = _summarize_declared(raw, ACCEPT_PROFILE)
    report = {
        "schema_version": ACCEPT_PROFILE,
        "accepted": False,
        "function": args.function,
        "context_match": declared.context_key == live.context_key,
    }
    if not report["context_match"]:
        report["reason"] = "context_mismatch"
    else:
        # Emit the freshly derived record, never the declared one —
        # identical for honest manifests, and removes the manifest-
        # forgery channel entirely. A bare member name must resolve
        # to exactly one function.
        matches = [
            f
            for f in live.functions
            if f.name == args.function
            or f.name.rsplit(".", 1)[-1] == args.function
        ]
        if not matches:
            report["reason"] = "unknown_function"
        elif len(matches) > 1:
            report["reason"] = "ambiguous_function"
        else:
            report["accepted"] = True
            report["summary"] = matches[0].to_dict()
    _emit(report, 0)
