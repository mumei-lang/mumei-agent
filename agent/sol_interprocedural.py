"""Slice-0 Solidity scalar interprocedural summaries.

Mirrors the Go consumer's *model* — not its producer — for
single-file Solidity: a `SolFunctionSummary` reports the set
of parameter indexes a `pure`/`view` function's scalar
result may depend on (an over-approximation — `x*0` and
`x-x` still depend on `x`), the nested same-contract calls
it makes with their formal-to-actual dependency sets, and
any gaps that blocked a fuller result. An unavailable
result is `None`, never an empty set.

The fragment is deliberately small:

* `contract`/`library` declarations with `function`
  members — scalar `primitive_type` parameters
  (`uint*`/`int*`/`bool`) and a single scalar return type.
* Bodies admit `uint c = e`/`bool b = e` declarations,
  `x = e`/compound (`+=` …) assignments, `x++`/`x--`,
  `if`/`else` (both-branch dep joins), `return e`, and
  nested `block_statement`s. `require`/`revert` calls count
  as opaque builtin calls — their actual deps flow, the
  result is ignored.
* Expressions admit parameter/local reads, number/bool
  literals, parentheses, unary `!`/`-`/`~`, the full
  binary/ternary operator set (the dep model only needs the
  operand union), and `f(args)` calls to same-contract
  functions — resolved by name, each argument contributes
  its deps, and the callee's own summary composes the
  result.
* A call whose callee is unavailable or unsupported closes
  the caller (the callee's gap is its own); state-variable
  reads, member calls (`this.f`, `obj.f`), loops, multiple
  or unnamed results, structs/arrays/mappings and
  modifiers stay closed — a gap records why.

This is a conservative dependency analysis, not value
evaluation, correctness or proof: effects are always
`unknown` (storage, ether, events and external calls are
not modelled). `SolSummarySet.context_key` binds the source
hash and profile so reuse requires identical input.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

PROFILE = "mumei.sol-interprocedural/v1"

MAX_NODES = 20000
MAX_FUNCTIONS = 128
MAX_INLINE_DEPTH = 48

_BINARY_OPS = {
    "+", "-", "*", "/", "%", "**",
    "<", "<=", ">", ">=",
    "==", "!=", "&&", "||",
    "&", "|", "^", "<<", ">>",
}
_UNARY_OPS = {"!", "-", "~", "++", "--"}
_AUGMENTED_OPS = {
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=",
}
_BUILTIN_VOID_CALLS = {"require", "assert", "revert"}
_OPAQUE_GLOBALS = {"msg", "block", "tx", "abi"}
_CRYPTO_BUILTINS = {
    "keccak256", "sha256", "ripemd160", "ecrecover",
    "blockhash", "addmod", "mulmod", "gasleft",
    "selfdestruct", "suicide", "type",
}
import re as _re


_SCALAR_PRIMITIVE = (
    lambda t: t.startswith("uint") or t.startswith("int")
    or t == "bool"
    or t in {"address", "address payable"}
    or bool(_re.fullmatch(r"bytes([1-9]|[12][0-9]|3[0-2])", t))
)


class _Unsupported(Exception):
    def __init__(self, reason: str, byte: int):
        super().__init__(reason)
        self.reason = reason
        self.byte = byte


@dataclass(frozen=True)
class SolGap:
    reason: str
    byte: int


@dataclass(frozen=True)
class SolCall:
    byte: int
    callee: str
    actual_dependencies: tuple[frozenset[int], ...]
    result_dependencies: frozenset[int] | None


@dataclass
class SolFunctionSummary:
    name: str
    contract: str
    params: tuple[str, ...]
    available: bool
    return_dependencies: frozenset[int] | None
    calls: list[SolCall] = field(default_factory=list)
    gaps: list[SolGap] = field(default_factory=list)
    effects: str = "unknown"


@dataclass
class SolSummarySet:
    context_key: str
    functions: list[SolFunctionSummary]
    profile: str = PROFILE


def _children(node):
    return [c for c in node.children if c.is_named]


def _span(node) -> int:
    return node.start_byte


def _scalar_type(tnode) -> bool:
    """A `type_name` that is exactly a scalar `primitive_type`
    — `uint256[]`/`uint256[2]` parse as a nested `type_name`
    and fail this check."""
    if tnode is None:
        return False
    kids = _children(tnode)
    return (
        len(kids) == 1
        and kids[0].type == "primitive_type"
        and _SCALAR_PRIMITIVE(kids[0].text.decode())
    )


def _scalar_param(param) -> tuple[str, str] | None:
    """`(name, type_text)` of a `parameter` node, or None when
    the parameter is unnamed or non-scalar."""
    name = param.child_by_field_name("name")
    tnode = param.child_by_field_name("type")
    if name is None or tnode is None:
        return None
    if not _scalar_type(tnode):
        return None
    return name.text.decode(), tnode.text.decode()


def _return_scalar(fn) -> bool:
    """The `returns (...)` clause declares exactly one scalar
    type (named or unnamed)."""
    ret = fn.child_by_field_name("return_type") or next(
        (
            c
            for c in _children(fn)
            if c.type == "return_type_definition"
        ),
        None,
    )
    if ret is None:
        return False
    params = [c for c in _children(ret) if c.type == "parameter"]
    if len(params) != 1:
        return False
    return _scalar_type(params[0].child_by_field_name("type"))


class _Builder:
    def __init__(self, source: bytes):
        self.source = source
        self.count = [0]
        self.functions: dict[str, object] = {}
        self.contracts: dict[str, str] = {}
        self.summaries: dict[str, SolFunctionSummary] = {}
        self._inline_depth = 0
        self._writes: list[set[str]] = []
        self._decls: list[set[str]] = []
        self._state_vars: dict[str, set[str]] = {}
        self._overload_groups: dict[str, list[str]] = {}

    # -- unit scan ----------------------------------------------------

    def build(self) -> SolSummarySet:
        from tree_sitter import Language, Parser
        import tree_sitter_solidity

        parser = Parser(
            Language(tree_sitter_solidity.language())
        )
        tree = parser.parse(self.source)
        root = tree.root_node
        for top in _children(root):
            if top.type == "contract_declaration":
                self._register_contract(top)
        if len(self.functions) > MAX_FUNCTIONS:
            raise _Unsupported("analysis_limit", 0)
        summaries = []
        for name, fn_node in self.functions.items():
            try:
                summaries.append(self._summarize(name, fn_node))
            except RecursionError:
                summaries.append(
                    SolFunctionSummary(
                        name,
                        self.contracts[name],
                        (),
                        False,
                        None,
                        gaps=[SolGap("analysis_limit", _span(fn_node))],
                    )
                )
        key = hashlib.sha256(
            self.source + PROFILE.encode()
        ).hexdigest()
        return SolSummarySet(
            context_key=f"{PROFILE}:{key}", functions=summaries
        )

    def _register_contract(self, node) -> None:
        name_node = node.child_by_field_name("name") or next(
            (c for c in _children(node) if c.type == "identifier"),
            None,
        )
        contract = (
            name_node.text.decode() if name_node is not None else "?"
        )
        body = next(
            (c for c in _children(node) if c.type == "contract_body"),
            None,
        )
        if body is None:
            return
        for member in _children(body):
            if member.type == "state_variable_declaration":
                tnode = next(
                    (
                        c
                        for c in _children(member)
                        if c.type == "type_name"
                    ),
                    None,
                )
                vname = next(
                    (
                        c
                        for c in _children(member)
                        if c.type == "identifier"
                    ),
                    None,
                )
                if (
                    vname is not None
                    and _scalar_type(tnode)
                ):
                    self._state_vars.setdefault(
                        contract, set()
                    ).add(vname.text.decode())
                continue
            if member.type != "function_definition":
                continue
            fname = member.child_by_field_name("name") or next(
                (
                    c
                    for c in _children(member)
                    if c.type == "identifier"
                ),
                None,
            )
            if fname is None:
                continue
            key = f"{contract}.{fname.text.decode()}"
            self.functions[key] = member
            self.contracts[key] = contract

    # -- per-function summary ----------------------------------------

    def _summarize(self, key, fn_node) -> SolFunctionSummary:
        params: list[str] = []
        param_index: dict[str, int] = {}
        for c in _children(fn_node):
            if c.type != "parameter":
                continue
            got = _scalar_param(c)
            if got is None:
                raise_gap = SolGap(
                    "unsupported_signature", _span(c)
                )
                return SolFunctionSummary(
                    key,
                    self.contracts[key],
                    (),
                    False,
                    None,
                    gaps=[raise_gap],
                )
            name, _t = got
            param_index[name] = len(params)
            params.append(name)
        if not _return_scalar(fn_node):
            return SolFunctionSummary(
                key,
                self.contracts[key],
                tuple(params),
                False,
                None,
                gaps=[
                    SolGap(
                        "unsupported_signature", _span(fn_node)
                    )
                ],
            )
        ret = fn_node.child_by_field_name("return_type")
        ret_name = None
        if ret is not None:
            rparam = next(
                (c for c in _children(ret) if c.type == "parameter"),
                None,
            )
            if rparam is not None:
                rn = rparam.child_by_field_name("name")
                if rn is not None:
                    ret_name = rn.text.decode()
        body = fn_node.child_by_field_name("body") or next(
            (c for c in _children(fn_node) if c.type == "function_body"),
            None,
        )
        summary = SolFunctionSummary(
            key,
            self.contracts[key],
            tuple(params),
            False,
            None,
        )
        self._current_contract = self.contracts[key]
        locals_: dict[str, frozenset[int]] = {
            n: frozenset({i}) for n, i in param_index.items()
        }
        # Scalar state variables read as dep-free external
        # values; writes still flow through the slot and set
        # `effects`.
        for sv in self._state_vars.get(
            self.contracts[key], ()
        ):
            locals_.setdefault(sv, frozenset())
        if ret_name is not None and ret_name not in locals_:
            # Named result (`returns (uint256 r)`) — a writable
            # local slot a bare `return` reads back.
            locals_[ret_name] = frozenset()
        self._ret_name = ret_name
        try:
            rets = self._block(
                body, locals_, param_index, summary
            )
        except _Unsupported as exc:
            summary.gaps.append(SolGap(exc.reason, exc.byte))
            return summary
        if rets is None:
            if not summary.gaps:
                summary.gaps.append(
                    SolGap("missing_return", _span(fn_node))
                )
            return summary
        summary.return_dependencies = rets
        summary.available = True
        if summary.effects == "unknown":
            summary.effects = "none_in_supported_fragment"
        return summary

    # -- statements ---------------------------------------------------

    def _block(
        self, body, locals_, param_index, summary
    ) -> frozenset[int] | None:
        """Walk statements; on `return e` produce the dep set.
        Branches join locals by dep union. Returns None when a
        statement can't be modelled or no return is reached."""
        if body is None:
            return None
        result = None
        for st in _children(body):
            if st.type == "statement" and _children(st):
                st = _children(st)[0]
            got = self._statement(
                st, locals_, param_index, summary
            )
            if got is not None:
                result = (
                    got
                    if result is None
                    else result | got
                )
        return result

    def _statement(
        self, st, locals_, param_index, summary
    ) -> frozenset[int] | None:
        t = st.type
        if t == "return_statement":
            expr = next(
                (c for c in _children(st) if c.type == "expression"),
                None,
            )
            if expr is None:
                return locals_.get(
                    getattr(self, "_ret_name", ""), frozenset()
                )
            return self._expr(expr, locals_, param_index, summary)
        if t == "variable_declaration_statement":
            decl = next(
                (
                    c
                    for c in _children(st)
                    if c.type == "variable_declaration"
                ),
                None,
            )
            expr = st.child_by_field_name("value")
            if decl is None:
                raise _Unsupported(
                    "unsupported_statement", _span(st)
                )
            name = decl.child_by_field_name("name")
            tnode = decl.child_by_field_name("type")
            if name is None or not _scalar_type(tnode):
                raise _Unsupported(
                    "unsupported_statement", _span(st)
                )
            deps = (
                self._expr(expr, locals_, param_index, summary)
                if expr is not None
                else frozenset()
            )
            locals_[name.text.decode()] = deps
            if self._writes:
                self._writes[-1].add(name.text.decode())
            if self._decls:
                self._decls[-1].add(name.text.decode())
            return None
        if t == "expression_statement":
            expr = next(
                (c for c in _children(st) if c.type == "expression"),
                None,
            )
            if expr is None:
                return None
            self._assign_or_call(
                expr, locals_, param_index, summary
            )
            return None
        if t == "if_statement":
            cond = next(
                (c for c in _children(st) if c.type == "expression"),
                None,
            )
            branches = [
                c for c in _children(st)
                if c.type in {"statement", "block_statement"}
            ]
            left_locals = dict(locals_)
            right_locals = dict(locals_)
            left_ret = None
            right_ret = None
            if branches:
                left_ret = self._block(
                    branches[0], left_locals, param_index, summary
                )
            if len(branches) > 1:
                right_ret = self._block(
                    branches[1], right_locals, param_index, summary
                )
            merged = frozenset()
            if cond is not None:
                merged |= self._expr(
                    cond, locals_, param_index, summary
                )
            for name in set(left_locals) | set(right_locals):
                locals_[name] = left_locals.get(
                    name, frozenset()
                ) | right_locals.get(name, frozenset()) | merged
            ret = None
            if left_ret is not None:
                ret = left_ret
            if right_ret is not None:
                ret = right_ret if ret is None else ret | right_ret
            if ret is not None:
                # Which branch produced the value depends on
                # the condition — its deps join the result.
                ret = ret | merged
            return ret
        if t == "while_statement" or t == "do_while_statement":
            kids = _children(st)
            cond = next(
                (c for c in kids if c.type == "expression"), None
            )
            body = next(
                (
                    c
                    for c in kids
                    if c.type in {"statement", "block_statement"}
                ),
                None,
            )
            return self._loop(
                cond, None, body, locals_, param_index, summary
            )
        if t == "for_statement":
            kids = _children(st)
            body = kids[-1] if kids and kids[-1].type in {
                "statement", "block_statement"
            } else None
            inner_parts = [
                c
                for c in kids[:-1]
                if c.type
                in {
                    "variable_declaration_statement",
                    "expression_statement",
                    "expression",
                }
            ]
            init = inner_parts[0] if inner_parts else None
            cond_node = (
                inner_parts[1] if len(inner_parts) > 1 else None
            )
            update = (
                inner_parts[2] if len(inner_parts) > 2 else None
            )
            cond = None
            if cond_node is not None:
                if cond_node.type == "expression":
                    cond = cond_node
                else:
                    cond = next(
                        (
                            c
                            for c in _children(cond_node)
                            if c.type == "expression"
                        ),
                        None,
                    )
            return self._loop(
                cond, update, body, locals_, param_index,
                summary, init=init,
            )
        if t == "revert_statement":
            err = next(
                (c for c in _children(st) if c.type == "expression"),
                None,
            )
            actual = tuple(
                self._expr(
                    next(
                        (cc for cc in _children(a) if cc.type == "expression"),
                        a,
                    ),
                    locals_, param_index, summary,
                )
                for a in _children(st)
                if a.type == "call_argument"
            )
            summary.calls.append(
                SolCall(
                    _span(st),
                    err.text.decode() if err is not None else "revert",
                    actual,
                    None,
                )
            )
            return None
        if t == "emit_statement":
            ev = next(
                (c for c in _children(st) if c.type == "expression"),
                None,
            )
            actual = tuple(
                self._expr(
                    next(
                        (cc for cc in _children(a) if cc.type == "expression"),
                        a,
                    ),
                    locals_, param_index, summary,
                )
                for a in _children(st)
                if a.type == "call_argument"
            )
            summary.calls.append(
                SolCall(
                    _span(st),
                    ev.text.decode() if ev is not None else None,
                    actual,
                    None,
                )
            )
            return None
        if t == "unchecked":
            # Named keyword child of `unchecked { ... }` — the
            # block_statement arm already walks its statements.
            return None
        if t == "block_statement":
            # Block-scoped decls shadow outer names without
            # destroying them; assignments to outer names
            # propagate back, inner decls don't leak.
            inner = dict(locals_)
            self._decls.append(set())
            try:
                ret = self._block(
                    st, inner, param_index, summary
                )
            finally:
                decls = self._decls.pop()
            for name in list(inner):
                if name in locals_ and name not in decls:
                    locals_[name] = inner[name]
            return ret
        raise _Unsupported("unsupported_statement", _span(st))

    def _loop(
        self, cond, update, body, locals_, param_index, summary,
        init=None,
    ) -> frozenset[int] | None:
        """One body pass over a copy of locals, then a
        may-write union merge back, e.g. `s += i` inside a loop
        adds i's deps to s without fixing iteration counts.
        Condition deps join every slot the body may have
        touched, matching the if-join."""
        inner = dict(locals_)
        self._writes.append(set())
        try:
            if init is not None:
                self._statement(
                    init, inner, param_index, summary
                )
            ret = None
            if body is not None:
                ret = self._block(
                    body, inner, param_index, summary
                )
            if update is not None:
                self._assign_or_call(
                    update, inner, param_index, summary
                )
        finally:
            touched = self._writes.pop()
        merged = frozenset()
        if cond is not None:
            # Loop-init names (`i`) live in `inner`, not the
            # outer scope.
            merged |= self._expr(
                cond, inner, param_index, summary
            )
        for name in list(locals_):
            deps = inner.get(name, frozenset())
            if deps != locals_[name] or name in touched:
                locals_[name] = locals_[name] | deps | merged
        return ret

    def _assign_or_call(
        self, expr, locals_, param_index, summary
    ) -> frozenset[int]:
        """Statement-position expression — `x = e`, `x op= e`,
        `x++`, or a call whose result is discarded."""
        if expr.type in {
            "assignment_expression",
            "augmented_assignment_expression",
        }:
            left = expr.child_by_field_name("left")
            right = expr.child_by_field_name("right")
            lident = (
                _children(left)[0]
                if left is not None
                and left.type == "expression"
                and len(_children(left)) == 1
                else left
            )
            if (
                lident is not None
                and lident.type == "member_expression"
            ):
                # `this.s = v` — member write to a state var.
                idents = [
                    c
                    for c in _children(lident)
                    if c.type == "identifier"
                ]
                if (
                    len(idents) == 2
                    and idents[0].text == b"this"
                    and idents[1].text.decode()
                    in self._state_vars.get(
                        getattr(self, "_current_contract", ""),
                        (),
                    )
                ):
                    lident = idents[1]
                else:
                    lident = None
            if (
                lident is None
                or lident.type != "identifier"
                or lident.text.decode() not in locals_
                or right is None
            ):
                raise _Unsupported(
                    "unsupported_statement", _span(expr)
                )
            deps = self._expr(
                right, locals_, param_index, summary
            )
            if expr.type == "augmented_assignment_expression":
                deps |= locals_[lident.text.decode()]
            locals_[lident.text.decode()] = deps
            if self._writes:
                self._writes[-1].add(lident.text.decode())
            if lident.text.decode() in self._state_vars.get(
                getattr(self, "_current_contract", ""), ()
            ):
                summary.effects = "state_writes"
            return deps
        if expr.type == "update_expression":
            target = expr.child_by_field_name("argument")
            tident = (
                _children(target)[0]
                if target is not None
                and target.type == "expression"
                and len(_children(target)) == 1
                else target
            )
            if (
                tident is None
                or tident.type != "identifier"
                or tident.text.decode() not in locals_
            ):
                raise _Unsupported(
                    "unsupported_statement", _span(expr)
                )
            if self._writes:
                self._writes[-1].add(tident.text.decode())
            if tident.text.decode() in self._state_vars.get(
                getattr(self, "_current_contract", ""), ()
            ):
                summary.effects = "state_writes"
            return locals_[tident.text.decode()]
        if expr.type == "call_expression":
            return self._call(
                expr, locals_, param_index, summary, void=True
            )
        return self._expr(expr, locals_, param_index, summary)

    # -- expressions --------------------------------------------------

    def _expr(
        self, node, locals_, param_index, summary
    ) -> frozenset[int]:
        self.count[0] += 1
        if self.count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        if node.type == "expression" and _children(node):
            inner = _children(node)
            if len(inner) == 1:
                return self._expr(
                    inner[0], locals_, param_index, summary
                )
        t = node.type
        if t == "identifier":
            name = node.text.decode()
            if name not in locals_:
                raise _Unsupported(
                    "binding_unavailable", _span(node)
                )
            return locals_[name]
        if t in {
            "number_literal",
            "boolean_literal",
            "true",
            "false",
            "hex_literal",
            "decimal_literal",
        } or t.endswith("_literal"):
            return frozenset()
        if t == "parenthesized_expression" or t == "expression":
            deps = frozenset()
            for c in _children(node):
                deps |= self._expr(
                    c, locals_, param_index, summary
                )
            return deps
        if t == "unary_expression" or t == "update_expression":
            deps = frozenset()
            for c in _children(node):
                if c.is_named:
                    deps |= self._expr(
                        c, locals_, param_index, summary
                    )
            return deps
        if t == "binary_expression":
            deps = frozenset()
            for c in _children(node):
                if c.is_named:
                    deps |= self._expr(
                        c, locals_, param_index, summary
                    )
            return deps
        if t == "ternary_expression":
            deps = frozenset()
            for c in _children(node):
                deps |= self._expr(
                    c, locals_, param_index, summary
                )
            return deps
        if t == "call_expression":
            return self._call(node, locals_, param_index, summary)
        if t == "member_expression":
            idents = [
                c
                for c in _children(node)
                if c.type == "identifier"
            ]
            bident = idents[0] if idents else None
            if (
                bident is not None
                and bident.text.decode() in _OPAQUE_GLOBALS
            ):
                # msg./block./tx./abi. — external environment
                # values with no dependency content.
                return frozenset()
            if (
                len(idents) == 2
                and idents[0].text == b"this"
                and idents[1].text.decode()
                in self._state_vars.get(
                    getattr(self, "_current_contract", ""), ()
                )
            ):
                # `this.s` — state var read through `this`.
                return locals_.get(
                    idents[1].text.decode(), frozenset()
                )
            raise _Unsupported(
                "binding_unavailable", _span(node)
            )
        if t in {
            "payable_conversion_expression",
            "type_conversion_expression",
            "type_cast_expression",
        }:
            deps = frozenset()
            for a in _children(node):
                if a.type == "call_argument":
                    expr = next(
                        (
                            c
                            for c in _children(a)
                            if c.type == "expression"
                        ),
                        a,
                    )
                    deps |= self._expr(
                        expr, locals_, param_index, summary
                    )
            return deps
        if t in {
            "assignment_expression",
            "augmented_assignment_expression",
        }:
            return self._assign_or_call(
                node, locals_, param_index, summary
            )
        raise _Unsupported("unsupported_expression", _span(node))

    def _call(
        self, node, locals_, param_index, summary, void=False
    ) -> frozenset[int]:
        abi_member = None
        fn_expr = node.child_by_field_name("function")
        if (
            fn_expr is not None
            and fn_expr.type == "expression"
            and len(_children(fn_expr)) == 1
        ):
            fn_expr = _children(fn_expr)[0]
        if (
            fn_expr is not None
            and fn_expr.type == "member_expression"
        ):
            # `this.f(...)` — same-contract member dispatch.
            idents = [
                c for c in _children(fn_expr)
                if c.type == "identifier"
            ]
            if (
                len(idents) == 2
                and idents[0].text == b"this"
            ):
                fn_expr = idents[1]
            elif (
                len(idents) == 2
                and idents[0].text.decode() == "abi"
            ):
                abi_member = idents[1].text.decode()
                fn_expr = None
        args = [
            c
            for c in _children(node)
            if c.type == "call_argument"
        ]
        actual = []
        for a in args:
            expr = next(
                (c for c in _children(a) if c.type == "expression"),
                a if a.type == "expression" else None,
            )
            if expr is None:
                raise _Unsupported(
                    "unsupported_expression", _span(a)
                )
            actual.append(
                self._expr(expr, locals_, param_index, summary)
            )
        actual_t = tuple(actual)
        actual_union = frozenset()
        for a in actual:
            actual_union |= a
        if abi_member is not None:
            # abi.encode*/decode — the encoded result
            # carries every argument's deps.
            summary.calls.append(
                SolCall(
                    _span(node),
                    f"abi.{abi_member}",
                    actual_t,
                    actual_union,
                )
            )
            return actual_union
        if (
            fn_expr is None
            or fn_expr.type != "identifier"
        ):
            if void:
                summary.calls.append(
                    SolCall(_span(node), None, actual_t, None)
                )
                return frozenset()
            raise _Unsupported("call_unresolved", _span(node))
        name = fn_expr.text.decode()
        if name in _BUILTIN_VOID_CALLS:
            summary.calls.append(
                SolCall(_span(node), name, actual_t, None)
            )
            return frozenset()
        if name in _CRYPTO_BUILTINS:
            summary.calls.append(
                SolCall(
                    _span(node), name, actual_t, actual_union
                )
            )
            return actual_union
        # Same-contract resolution first — two contracts may
        # declare the same function name.
        target = None
        cands = [getattr(self, "_current_contract", "")]
        cands += [
            c for c in self.contracts.values() if c != cands[0]
        ]
        for cname in cands:
            key = f"{cname}.{name}"
            if key in self.functions:
                target = key
                break
        if target is None:
            if void:
                # Unknown callee whose result is discarded —
                # record it opaquely rather than blocking the
                # whole summary (e.g. `revert MyError(x)`).
                summary.calls.append(
                    SolCall(_span(node), name, actual_t, None)
                )
                return frozenset()
            raise _Unsupported("call_unresolved", _span(node))
        callee = self.summaries.get(target)
        if callee is None:
            if self._inline_depth >= MAX_INLINE_DEPTH:
                raise _Unsupported("analysis_limit", _span(node))
            self._inline_depth += 1
            try:
                callee = self._summarize(
                    target, self.functions[target]
                )
            finally:
                self._inline_depth -= 1
            self.summaries[target] = callee
        if not callee.available or callee.return_dependencies is None:
            summary.calls.append(
                SolCall(_span(node), name, actual_t, None)
            )
            summary.gaps.append(
                SolGap("call_unresolved", _span(node))
            )
            raise _Unsupported("call_unresolved", _span(node))
        result = frozenset()
        for idx in sorted(callee.return_dependencies):
            if idx < len(actual_t):
                result |= actual_t[idx]
        summary.calls.append(
            SolCall(_span(node), name, actual_t, result)
        )
        return result


def summarize_solidity(source: str | bytes) -> SolSummarySet:
    """Summarize a Solidity source string — see the module
    docstring for the admitted fragment and its limits."""
    data = source.encode() if isinstance(source, str) else source
    builder = _Builder(data)
    try:
        return builder.build()
    except _Unsupported as exc:
        # A unit-level failure closes the whole source — one
        # summary per registered function is still emitted
        # with the gap attached to the first.
        key = hashlib.sha256(data + PROFILE.encode()).hexdigest()
        return SolSummarySet(
            context_key=f"{PROFILE}:{key}",
            functions=[
                SolFunctionSummary(
                    name,
                    builder.contracts.get(name, "?"),
                    (),
                    False,
                    None,
                    gaps=[SolGap(exc.reason, exc.byte)],
                )
                for name in builder.functions
            ],
        )
