"""C06 TypeScript/JavaScript interprocedural summaries (slice 0).

A deliberately narrow scalar fragment, mirroring the Go consumer's
*model* (``agent/go_interprocedural.py``) — not its producer pipeline.
There is no compiler snapshot: source annotations are the only type
signal, and calls resolve statically by name to function declarations
in the same unit. Anything outside the fragment fails CLOSED with a
declared gap — never a silently wrong summary.

Admitted:

* `number`/`boolean`-annotated parameters on a top-level
  `function name(...) : number|boolean { ... }` declaration — a
  parameter with no scalar annotation, a default value, a rest or
  destructuring pattern, or an optional marker closes the function.
* `let`/`const`/`var` declarations whose declarators bind one
  identifier to a supported expression (an optional `number`/`boolean`
  annotation is checked when present).
* Scalar literals (`number`, `true`, `false`), identifier reads of
  bound parameters/locals, parentheses, pure unary (`!`, `-`, `+`,
  `~`) and binary operators (`+`, `-`, `*`, comparisons, `==`/`===`/
  `!=`/`!==`, `&&`, `||`, `&`, `|`, `^`). Division, remainder,
  exponentiation, shifts and `??` stay closed — mirroring the Go
  fragment's arithmetic boundary (and JS `/` yields floats anyway).
* `return expr` (dependency union over every return — an
  over-approximation, not a per-site result), bare `return` (no
  tracked result), assignments `x = e` to bound names, compound
  assignments `x op= e` for the admitted operators (deps union like
  `x = x op e`), and `x++`/`x--`/`++x`/`--x` on bound names
  (dependency-preserving). `var` bindings are function-scoped —
  they escape bare blocks and `for` initializers — while `let`/`const`
  are block-scoped and never shadow an outer name past their block.
* `if`/`else` (each branch evaluated over a scope copy and joined by
  union — a conditional store keeps both the new deps and the value
  the skipped path would have left),
  `while` and classic `for (init; cond; incr)` loops (bodies iterate
  to a dependency fixed point — a join, never an unroll; trip counts
  are not modelled), and unlabelled `break`/`continue` inside a loop.
* Calls `f(args)` whose callee is a `function` declared in the same
  unit — resolved by name only. The result conservatively depends on
  every evaluated argument and records a `TsCall` transfer; the callee
  body is opaque (self-recursion records a transfer like any other
  name-resolved call). Everything else — member calls, unresolved
  names, `new` — stays closed.

Closed with declared gaps: `import`/`export` and ambient/`declare`
declarations close the whole unit (`unsupported_unit`); classes,
objects/member access, `this`, arrow-function values or callbacks,
generators, `async`/`await`, `any`/composite/missing parameter types,
spread, destructuring, `new`, `try`/`throw`, `switch`, `do`/`while`,
`for`-`in`/`of`, ternaries, labels and `sequence_expression` stay
closed (`unsupported_signature` / `unsupported_statement` /
`unsupported_expression` / `binding_unavailable` / `call_unresolved`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

PROFILE = "mumei.ts-interprocedural/v1"

# Defensive bound on evaluated syntax nodes — a parser or dispatch bug
# must never hang the analyzer.
MAX_NODES = 20000

_SCALAR_TYPES = {b"number", b"boolean"}

# `*` is admitted; `/`, `%`, `**`, shifts and `??` stay closed — the Go
# fragment's arithmetic boundary, and JS division is floating-point.
_BINARY_OPS = {
    "+", "-", "*",
    "<", "<=", ">", ">=",
    "==", "===", "!=", "!==",
    "&&", "||",
    "&", "|", "^",
}
_UNARY_OPS = {"!", "-", "+", "~"}
_AUGMENTED_OPS = {op + "=" for op in _BINARY_OPS if op not in {"==", "===", "!=", "!==", "<", "<=", ">", ">="}}

# Top-level children that keep the unit a fragment unit.
_TOP_LEVEL = {"function_declaration", "comment"}


@dataclass(frozen=True)
class TsSpan:
    """Source byte span (single file — no file index yet)."""

    start: int
    end: int


@dataclass(frozen=True)
class TsGap:
    """A declared reason a function's summary is unavailable."""

    reason: str
    span: TsSpan
    callee: str = ""


@dataclass(frozen=True)
class TsCall:
    """A same-unit call transfer: the callee name, per-argument
    dependency sets and the unioned result dependencies."""

    span: TsSpan
    callee: str
    arguments: tuple[frozenset[int], ...]
    result: frozenset[int]


@dataclass(frozen=True)
class TsFunctionSummary:
    name: str
    available: bool
    parameters: tuple[str, ...]
    # `None` means unavailable — never an empty set; an empty set is a
    # parameter-independent result, and a function without a return
    # expression reports an empty set too (no result is tracked).
    return_dependencies: frozenset[int] | None
    calls: tuple[TsCall, ...]
    gaps: tuple[TsGap, ...]
    # Reserved for a later type-identity layer (the Go consumer's
    # `pinned` member/signature ids); always empty in slice 0.
    pinned: tuple[str, ...] = ()
    effects: str = "none_in_supported_fragment"


@dataclass(frozen=True)
class TsSummarySet:
    context_key: str
    functions: tuple[TsFunctionSummary, ...]
    profile: str = PROFILE


class _Unsupported(Exception):
    """A closed path in the fragment — carries the declared gap."""

    def __init__(self, reason: str, span: TsSpan, callee: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.span = span
        self.callee = callee


def _span(node) -> TsSpan:
    return TsSpan(node.start_byte, node.end_byte)


def _children(node) -> list:
    return node.named_children


def _syntax(raw: bytes):
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_typescript

        root = (
            Parser(Language(tree_sitter_typescript.language_typescript()))
            .parse(raw)
            .root_node
        )
        return None if root.has_error else root
    except (ImportError, ValueError, TypeError, RuntimeError):
        return None


class _Builder:
    """Evaluates one unit's functions in dependency-set space."""

    def __init__(self, root) -> None:
        self.functions: dict[str, object] = {}
        # A unit is closed when any top-level node is not a function
        # declaration or comment — imports/exports, ambient declares,
        # classes, namespaces and top-level statements all qualify.
        self.unit_gap: TsGap | None = None
        for child in root.named_children:
            if child.type in _TOP_LEVEL:
                if child.type == "function_declaration":
                    name = child.child_by_field_name("name")
                    if name is not None:
                        self.functions[name.text.decode()] = child
            else:
                # `export function f` wraps the declaration — register
                # the name so the summary exists to carry the gap.
                if child.type == "export_statement":
                    inner = next(
                        (
                            c
                            for c in child.named_children
                            if c.type == "function_declaration"
                        ),
                        None,
                    )
                    if inner is not None:
                        name = inner.child_by_field_name("name")
                        if name is not None:
                            self.functions[name.text.decode()] = inner
                if self.unit_gap is None:
                    self.unit_gap = TsGap("unsupported_unit", _span(child))
        self.frames: list[dict[str, bool]] = []
        # Function-level scope for `var` bindings, set per body; plus
        # the let/const block-scope save stack and the var-name set.
        self.function_locals: dict[str, frozenset[int]] = {}
        self.var_names: set[str] = set()
        self.block_stack: list[dict[str, frozenset[int] | None]] = []

    def summarize_all(self) -> tuple[TsFunctionSummary, ...]:
        return tuple(
            self.summarize(node) for node in self.functions.values()
        )

    def summarize(self, node) -> TsFunctionSummary:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return TsFunctionSummary(
                "",
                False,
                (),
                None,
                (),
                (TsGap("unsupported_signature", _span(node)),),
                (),
                "unknown",
            )
        name = name_node.text.decode()
        if self.unit_gap is not None:
            return TsFunctionSummary(
                name, False, (), None, (), (self.unit_gap,), (), "unknown"
            )
        try:
            return self.body(node, name)
        except _Unsupported as u:
            return TsFunctionSummary(
                name, False, (), None, (),
                (TsGap(u.reason, u.span, u.callee),), (), "unknown",
            )

    def body(self, node, name: str) -> TsFunctionSummary:
        # Signature gates: named function, every parameter a scalar
        # `identifier: number|boolean`, a declared scalar return type
        # and a statement_block body. `async`/`function*` markers —
        # anonymous children of the declaration — stay closed, as do
        # optional/rest/default/destructured parameters.
        for child in node.children:
            if not child.is_named and child.type in {"async", "*"}:
                raise _Unsupported("unsupported_signature", _span(node))
        params_node = node.child_by_field_name("parameters")
        body = node.child_by_field_name("body")
        ret = node.child_by_field_name("return_type")
        if params_node is None or body is None or body.type != "statement_block":
            raise _Unsupported("unsupported_signature", _span(node))
        if ret is None or not self._scalar_annotation(ret):
            raise _Unsupported("unsupported_signature", _span(node))
        params: dict[str, int] = {}
        for param in _children(params_node):
            if param.type != "required_parameter":
                raise _Unsupported("unsupported_signature", _span(param))
            pattern = param.child_by_field_name("pattern")
            ptype = param.child_by_field_name("type")
            if (
                pattern is None
                or pattern.type != "identifier"
                or ptype is None
                or not self._scalar_annotation(ptype)
                or param.child_by_field_name("value") is not None
            ):
                raise _Unsupported("unsupported_signature", _span(param))
            pname = pattern.text.decode()
            if pname in params:
                raise _Unsupported("unsupported_signature", _span(param))
            params[pname] = len(params)

        locals_: dict[str, frozenset[int]] = {}
        self.function_locals = locals_
        self.var_names = set()
        self.block_stack = []
        transfers: list[TsCall] = []
        count = [0]
        deps = [frozenset()]
        saw_return = [False]
        self._sequence(
            _children(body), params, locals_, transfers, count, deps,
            saw_return, False,
        )
        return TsFunctionSummary(
            name,
            True,
            tuple(params.keys()),
            deps[0] if saw_return[0] else frozenset(),
            tuple(sorted(transfers, key=lambda c: (c.span.start, c.span.end))),
            (),
            (),
            "unknown" if transfers else "none_in_supported_fragment",
        )

    @staticmethod
    def _scalar_annotation(node) -> bool:
        """`node` is a `type_annotation` whose inner type is a scalar
        `predefined_type` (`number`/`boolean`)."""
        inner = next(iter(_children(node)), None)
        return (
            inner is not None
            and inner.type == "predefined_type"
            and inner.text in _SCALAR_TYPES
        )

    def _sequence(
        self,
        children,
        params,
        locals_,
        transfers,
        count,
        deps,
        saw_return,
        conditional,
    ) -> None:
        frame = self.frames[-1] if self.frames else None
        for child in children:
            if frame is not None and frame["exited"]:
                conditional = True
            self.statement(
                child, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )

    @staticmethod
    def _store(locals_, params, name, value, conditional) -> None:
        if conditional:
            if name in locals_:
                # The skipped path keeps the binding's CURRENT value.
                value = locals_[name] | value
            elif name in params:
                value = frozenset({params[name]}) | value
        locals_[name] = value

    def statement(
        self,
        node,
        params,
        locals_,
        transfers,
        count,
        deps,
        saw_return,
        conditional,
    ) -> None:
        count[0] += 1
        if count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        if kind == "statement_block":
            # let/const bound in the block are restored on exit — only
            # `var` bindings (function-scoped) and assignments to outer
            # names escape.
            saved: dict[str, frozenset[int] | None] = {}
            self.block_stack.append(saved)
            try:
                self._sequence(
                    _children(node), params, locals_, transfers, count,
                    deps, saw_return, conditional,
                )
            finally:
                for name, prev in saved.items():
                    if prev is None:
                        locals_.pop(name, None)
                    else:
                        locals_[name] = prev
                self.block_stack.pop()
            return
        if kind == "comment" or kind == "empty_statement":
            return
        if kind == "return_statement":
            exprs = _children(node)
            if len(exprs) == 0:
                # A bare `return` tracks no result dependencies.
                saw_return[0] = True
                return
            if len(exprs) != 1:
                raise _Unsupported("unsupported_return", _span(node))
            deps[0] |= self.expression(
                exprs[0], params, locals_, transfers, count
            )
            saw_return[0] = True
            return
        if kind in {"lexical_declaration", "variable_declaration"}:
            is_var = kind == "variable_declaration"
            declarators = [
                c for c in _children(node) if c.type == "variable_declarator"
            ]
            if not declarators:
                raise _Unsupported("unsupported_statement", _span(node))
            for decl in declarators:
                pname = decl.child_by_field_name("name")
                if pname is None or pname.type != "identifier":
                    raise _Unsupported("binding_unavailable", _span(decl))
                annotation = decl.child_by_field_name("type")
                if annotation is not None and not self._scalar_annotation(
                    annotation
                ):
                    raise _Unsupported("binding_unavailable", _span(decl))
                value = decl.child_by_field_name("value")
                if value is None:
                    # `let x;` binds `undefined` — outside the fragment.
                    raise _Unsupported("binding_unavailable", _span(decl))
                deps_v = self.expression(
                    value, params, locals_, transfers, count
                )
                name = pname.text.decode()
                if is_var:
                    # `var` is function-scoped: it also lands in the
                    # current scope so loop fixed-points widen it.
                    self.var_names.add(name)
                    self._store(
                        self.function_locals, params, name, deps_v,
                        conditional,
                    )
                    if locals_ is not self.function_locals:
                        self._store(
                            locals_, params, name, deps_v, conditional
                        )
                else:
                    if self.block_stack:
                        saved = self.block_stack[-1]
                        if name not in saved:
                            saved[name] = locals_.get(name)
                    self._store(
                        locals_, params, name, deps_v, conditional
                    )
            return
        if kind == "expression_statement":
            self._expression_statement(
                node, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
            return
        if kind == "if_statement":
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            if condition is None or consequence is None:
                raise _Unsupported("unsupported_statement", _span(node))
            self.expression(condition, params, locals_, transfers, count)
            branch = dict(locals_)
            self.statement(
                consequence, params, branch, transfers, count, deps,
                saw_return, True,
            )
            self._join(locals_, branch, params)
            alternative = node.child_by_field_name("alternative")
            if alternative is not None:
                branch = dict(locals_)
                if alternative.type == "else_clause":
                    inner = _children(alternative)
                    if len(inner) != 1:
                        raise _Unsupported(
                            "unsupported_statement", _span(alternative)
                        )
                    alternative = inner[0]
                self.statement(
                    alternative, params, branch, transfers, count, deps,
                    saw_return, True,
                )
                self._join(locals_, branch, params)
            return
        if kind == "while_statement":
            condition = node.child_by_field_name("condition")
            body = node.child_by_field_name("body")
            if condition is None or body is None:
                raise _Unsupported("unsupported_statement", _span(node))
            self._loop(
                body, None, condition, params, locals_, transfers, count,
                deps, saw_return, conditional, node,
            )
            return
        if kind == "for_statement":
            body = node.child_by_field_name("body")
            if body is None:
                raise _Unsupported("unsupported_statement", _span(node))
            scope = dict(locals_)
            initializer = node.child_by_field_name("initializer")
            if initializer is not None:
                self._for_part(
                    initializer, params, scope, transfers, count, deps,
                    saw_return, conditional,
                )
            condition = node.child_by_field_name("condition")
            increment = node.child_by_field_name("increment")
            self._loop(
                body, increment, condition, params, scope, transfers,
                count, deps, saw_return, conditional, node,
            )
            self._join(locals_, scope, params)
            return
        if kind in {"break_statement", "continue_statement"}:
            if node.named_children:
                raise _Unsupported("unsupported_statement", _span(node))
            frame = self.frames[-1] if self.frames else None
            if frame is None:
                raise _Unsupported("unsupported_statement", _span(node))
            frame["exited"] = True
            # A `break` skips the for-increment; `continue` still runs
            # it. Both make the rest of the body conditional.
            frame["broke"] = kind == "break_statement"
            return
        raise _Unsupported("unsupported_statement", _span(node))

    def _for_part(
        self, node, params, locals_, transfers, count, deps,
        saw_return, conditional,
    ) -> None:
        """A classic-for initializer/increment: a declaration or a
        statement-level expression."""
        if node.type in {"lexical_declaration", "variable_declaration"}:
            self.statement(
                node, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
            return
        self._expression_statement_inner(
            node, params, locals_, transfers, count, deps,
            saw_return, conditional,
        )

    def _expression_statement(
        self, node, params, locals_, transfers, count, deps,
        saw_return, conditional,
    ) -> None:
        exprs = _children(node)
        if len(exprs) != 1:
            raise _Unsupported("unsupported_statement", _span(node))
        self._expression_statement_inner(
            exprs[0], params, locals_, transfers, count, deps,
            saw_return, conditional,
        )

    def _expression_statement_inner(
        self, node, params, locals_, transfers, count, deps,
        saw_return, conditional,
    ) -> None:
        if node.type == "assignment_expression":
            self._assignment(node, params, locals_, transfers, count,
                             conditional, augmented=False)
            return
        if node.type == "augmented_assignment_expression":
            self._assignment(node, params, locals_, transfers, count,
                             conditional, augmented=True)
            return
        if node.type == "update_expression":
            self._update(node, params, locals_, transfers, count,
                         conditional)
            return
        # Any other statement-level expression evaluates for its calls.
        self.expression(node, params, locals_, transfers, count)

    def _assignment(
        self, node, params, locals_, transfers, count, conditional, augmented
    ) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        op = node.child_by_field_name("operator")
        if (
            left is None
            or right is None
            or left.type != "identifier"
            or (augmented and (op is None or op.type not in _AUGMENTED_OPS))
            or (not augmented and op is not None and op.type != "=")
        ):
            raise _Unsupported("unsupported_statement", _span(node))
        name = left.text.decode()
        target = self._write_scope(name, locals_, params)
        if target is None:
            raise _Unsupported("binding_unavailable", _span(left))
        value = self.expression(right, params, locals_, transfers, count)
        if augmented:
            value = self._read_name(left, params, locals_, _span(left)) | value
        self._store(target, params, name, value, conditional)

    def _write_scope(self, name, locals_, params):
        """The scope a store lands in: block first, then the function
        scope a `var` may have escaped into, then a parameter (stored
        in the current scope as a shadow)."""
        if name in locals_:
            return locals_
        if name in self.function_locals:
            return self.function_locals
        if name in params:
            return locals_
        return None

    def _update(self, node, params, locals_, transfers, count, conditional):
        argument = node.child_by_field_name("argument")
        if argument is None or argument.type != "identifier":
            raise _Unsupported("unsupported_statement", _span(node))
        name = argument.text.decode()
        target = self._write_scope(name, locals_, params)
        if target is None:
            raise _Unsupported("binding_unavailable", _span(argument))
        self._store(
            target, params, name,
            self._read_name(argument, params, locals_, _span(argument)),
            conditional,
        )

    def _loop(
        self, body, increment, condition, params, scope, transfers,
        count, deps, saw_return, conditional, node,
    ) -> None:
        """Iterate a loop body to a dependency fixed point — a join, not
        an unroll; trip counts are never modelled."""
        passes = 0
        frame = {"exited": False, "broke": False}
        self.frames.append(frame)
        try:
            while True:
                mark = len(transfers)
                frame["exited"] = False
                frame["broke"] = False
                inner = dict(scope)
                if condition is not None:
                    # The condition re-evaluates each pass so a call's
                    # recorded arguments reflect widened bindings.
                    self.expression(
                        condition, params, inner, transfers, count
                    )
                self.statement(
                    body, params, inner, transfers, count, deps,
                    saw_return, conditional,
                )
                if increment is not None and not frame["broke"]:
                    # The increment runs after each pass so its writes
                    # seed the next iteration — a `break` skips it.
                    self._for_part(
                        increment, params, inner, transfers, count, deps,
                        saw_return, conditional,
                    )
                changed = False
                for name, ndeps in inner.items():
                    if name in scope:
                        if not ndeps <= scope[name]:
                            scope[name] |= ndeps
                            changed = True
                    elif name in params:
                        scope[name] = frozenset({params[name]}) | ndeps
                        changed = True
                if not changed:
                    break
                # Keep only the last pass's transfers: earlier copies
                # carry narrower argument sets.
                del transfers[mark:]
                passes += 1
                if passes > len(scope) * (len(params) + 1) + 1:
                    raise _Unsupported("analysis_limit", _span(node))
        finally:
            self.frames.pop()

    @staticmethod
    def _join(scope, branch, params) -> None:
        # Branch-local bindings (names absent from `scope`) never
        # escape — only existing and parameter names are merged.
        for name, value in branch.items():
            if name in scope:
                scope[name] |= value
            elif name in params:
                scope[name] = frozenset({params[name]}) | value

    def _read_name(self, node, params, locals_, span) -> frozenset[int]:
        name = node.text.decode()
        if name in locals_:
            return locals_[name]
        if name in self.function_locals:
            return self.function_locals[name]
        if name in params:
            return frozenset({params[name]})
        raise _Unsupported("binding_unavailable", span)

    def expression(self, node, params, locals_, transfers, count):
        count[0] += 1
        if count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        if kind == "identifier":
            return self._read_name(node, params, locals_, _span(node))
        if kind in {"number", "true", "false"}:
            return frozenset()
        if kind == "parenthesized_expression":
            exprs = _children(node)
            if len(exprs) != 1:
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(exprs[0], params, locals_, transfers, count)
        if kind == "unary_expression":
            op = node.child_by_field_name("operator")
            argument = node.child_by_field_name("argument")
            if op is None or argument is None or op.type not in _UNARY_OPS:
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(
                argument, params, locals_, transfers, count
            )
        if kind == "binary_expression":
            op = node.child_by_field_name("operator")
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if (
                op is None
                or left is None
                or right is None
                or op.type not in _BINARY_OPS
            ):
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(
                left, params, locals_, transfers, count
            ) | self.expression(right, params, locals_, transfers, count)
        if kind == "call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            if (
                function is None
                or function.type != "identifier"
                or arguments is None
            ):
                raise _Unsupported("unsupported_expression", _span(node))
            callee = function.text.decode()
            if callee not in self.functions:
                raise _Unsupported(
                    "call_unresolved", _span(node), callee
                )
            actual = tuple(
                self.expression(
                    arg, params, locals_, transfers, count
                )
                for arg in _children(arguments)
            )
            result = frozenset().union(*actual) if actual else frozenset()
            transfers.append(
                TsCall(_span(node), callee, actual, result)
            )
            return result
        if kind == "update_expression":
            # `x++` inside an expression (`return x++`) — dep-preserving
            # read of the bound name; the store is statement-level only.
            argument = node.child_by_field_name("argument")
            if argument is None or argument.type != "identifier":
                raise _Unsupported("unsupported_expression", _span(node))
            return self._read_name(argument, params, locals_, _span(argument))
        raise _Unsupported("unsupported_expression", _span(node))


def summarize_typescript(source: "str | bytes") -> TsSummarySet:
    """Compose conservative dependencies only; never infer equality or
    safety.

    A nonempty dependency set can overapproximate dependence (`x*0`
    still includes `x`). `None` means unavailable, never a
    parameter-independent or effect-free result.
    """
    raw = source.encode() if isinstance(source, str) else source
    root = _syntax(raw)
    if root is None:
        return TsSummarySet(
            hashlib.sha256(raw).hexdigest(),
            (),
        )
    builder = _Builder(root)
    return TsSummarySet(
        hashlib.sha256(raw).hexdigest(),
        builder.summarize_all(),
    )
