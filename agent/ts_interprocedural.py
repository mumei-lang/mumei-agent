"""C06 TypeScript/JavaScript interprocedural summaries (slice 0).

A deliberately narrow scalar fragment, mirroring the Go consumer's
*model* (``agent/go_interprocedural.py``) — not its producer pipeline.
There is no compiler snapshot: source annotations are the only type
signal, and calls resolve statically by name to function declarations
in the same unit. Anything outside the fragment fails CLOSED with a
declared gap — never a silently wrong summary.

Admitted:

* `number`/`boolean`-annotated parameters on a top-level
  `function name(...) : number|boolean { ... }` declaration —
  optional (`x?`) and defaulted (`x = expr`) parameters admit like
  required ones and a default's calls still record; a missing
  scalar annotation, a rest or destructuring pattern, or a
  non-scalar type closes the function.
* `let`/`const`/`var` declarations whose declarators bind one
  identifier to a supported expression or to nothing (`let x;`
  binds `undefined` — no dependencies; an optional
  `number`/`boolean` annotation is checked when present).
* Scalar literals (`number`, `true`, `false`), identifier reads of
  bound parameters/locals, parentheses, pure unary (`!`, `-`, `+`,
  `~`), `void` (evaluates for calls, yields no deps) and `typeof`
  (operand deps pass through), `as`/`satisfies`/`!` assertions
  (transparent), and binary operators (`+`, `-`, `*`, comparisons, `==`/`===`/
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
  `while`, `do`/`while` and classic `for (init; cond; incr)` loops
  (bodies iterate to a dependency fixed point — a join, never an
  unroll; trip counts are not modelled — a `do`/`while`'s run-once
  guarantee is invisible to that join and shares the `while` shape),
  `switch`/`case`/`default` (clauses processed in source order in a
  shared scope — every clause body is a may-write since entry is
  conditional, and a `break` ends only the paths that entered at an
  earlier clause), unlabelled `break`/`continue` inside a loop —
  a `break` inside a `switch` targets the switch's own frame while a
  `continue` skips it and still targets the enclosing loop — and
  `try`/`catch`/`finally` with `throw` (a `throw` evaluates its
  expression for calls, then every later statement is a may-write
  until a `catch` consumes the thrown flag; `finally` always runs —
  the catch parameter is left unbound, so a body that reads it
  closes), and `L: stmt` labels — a labeled loop or switch claims
  the label on its own frame, any other labeled statement gets a
  plain frame, so `break L` exits exactly the labeled statement and
  `continue L` only targets labeled loops (an unknown label, or a
  `continue` to a non-loop label, closes).
* Expressions also admit `a = b`/`a op= b` used as a
  sub-expression (writes like the statement form, always as a
  may-write since e.g. a `||`/`?:` arm may not run, and yields the
  assigned dependencies) and `sequence_expression` (the comma
  operator — operands evaluate left to right, the union is the
  result).
* Object literals `{a: e, n: {c: e}}` bound to a name — a
  `_Composite` value tracking dependencies per field; member reads
  `o.f`/`o.a.b` descend to the field's deps, member writes
  `o.f = e`/`o.f op= e`/`o.f++` rewrite the field copy-on-write
  (branch joins merge field-wise, and a shape mismatch collapses
  the composite to the union of its leaf deps), string-key
  subscripts `o["f"]` act like member syntax, a dynamic `o[k]`
  read unions every field at that level plus the index's deps
  (writes stay closed), and a missing field reads as `undefined`
  (no deps). Reading or passing a whole composite flattens to the
  union of its fields. Aliasing is reference-faithful only at the
  name level: `p = o` shares the composite and a member write
  through either name reaches both bindings in the same scope —
  while a composite bound anywhere else collapses to its leaf
  deps (`{a: o2}` field values, `q = o.a` member-path bindings,
  `o.f = o2` member stores, `{o}` shorthand), so no sub-object
  alias can diverge. Method/getter/setter object members and
  member access on a scalar or unbound base stay closed.
* Array literals `[e0, e1]` bound to a name — a `_Composite` with
  positional keys: `a[0]`/`a["0"]` reads field `"0"` precisely,
  `a[i]` unions every element plus the index's deps, `a[i] = e`
  writes a literal index field, and `a.length` reads a missing
  field (`undefined` — no deps). Nested array/object literals
  keep their structure; any other composite element collapses
  like an object field value. `for..of` iterates elements,
  `for..in` iterates keys — both through the composite rules.
* `for (const k in o)` / `for (const e of o)` over a composite —
  `in` binds the key as an opaque dep-free string (a `o[k]` read
  inside still unions every field), `of` binds the union of every
  field's deps; a `let`/`const` key or element is scoped to the
  loop while `var` escapes, and a bare identifier target binds as
  a may-write (the loop may not run). Any other right-hand side
  or a non-identifier left closes.
* Arrow functions and `function` expressions bound to names —
  `const g = (v) => v + x` is a `_Callable`; `g(y)` evaluates the
  body inline with the argument bound and captured names read at
  the CALL site (closures capture by reference — the latest
  value over-approximates). Writes inside the body merge back as
  may-writes; parameter defaults union their deps when the arg
  is omitted; the body's frames and scope state stay isolated.
  Passing or returning the value collapses to its `captured`
  union (every visible binding's deps at the definition site).
  A local binding shadows a same-named function declaration, and
  calling a scalar/composite-bound name closes. Recursion hits
  `MAX_NODES` and closes the caller with `analysis_limit`.
* Member calls `o.f(x)` where the field holds a `_Callable`
  (`{f: v => v}`) — the member read resolves the callee and the
  body evaluates as with a name call. There is no `this`
  binding: a body that reads `this` closes inside.
* `async` functions, async arrows and `await` expressions — in the
  dep model a promise is its resolved value, so `await e` passes
  the operand's deps through and `async` admits at the signature
  gate. `for await (x of y)` iterates like `of`. Generators
  (`function*`, `yield`) stay closed — a `yield` has no dep slot.
* Rest formal parameters `f(a, ...rest)` — the rest name
  occupies the last index slot; a declared-function call already
  unions every evaluated argument into the result, and a
  `_Callable` invocation binds the rest name to the union of the
  remaining actuals. A parameter after `...rest` closes.
* Shorthand method definitions `{m(v) { ... }}` — a callable
  field value like an arrow, invoked through the slice-13 member
  call path (`o.m(x)`). `get`/`set`/`*`/`static` markers stay
  closed; `async` admits. `this` inside closes at invoke.
* Destructured formal parameters `f({a, b}, [x])` — the pattern
  occupies one scalar index; its sub-names bind member reads of
  the slot at body start (each sees the slot's whole dep set).
  The summary records the pattern text (e.g. `{a, b}`) in
  `parameters`.
* Destructured declarations `const {a, b: c = d, ...rest} = o` /
  `const [x, y = d] = arr` — each sub-name binds the member read
  at its path (defaults union the default expression's deps, a
  `...rest` binding over-approximates to the whole union, a
  nested pattern descends); a scalar source binds every sub-name
  to the whole dep union, and a composite member binds as a
  scalar (member-path rule). Positions count holes — `[p, , q]`
  binds `q` to element 2.
* Spread members in object/array literals — `{...o}` copies the
  source composite's fields (a fresh instance — writes don't
  reach `o`), `[...a]` appends its positional fields; a scalar
  spread or a computed `{[k]: v}` key adds unknown fields, so the
  whole literal collapses to a scalar dep union. Optional-chain
  `o?.f`/`o?.[k]` and non-null `x!` read like their plain forms.
* String/`null`/`undefined` literals (dep-free), template strings
  (the result carries the union of the interpolations' deps), the
  `in`/`instanceof` binary operators (operand-dep union), and
  `delete o.f` (copy-on-write field removal propagated to aliases;
  a dynamic `delete o[k]` keeps every field — the surviving deps
  are the over-approximation).
* Calls `f(args)` whose callee is a `function` declared in the same
  unit — resolved by name only, including nested `function inner()`
  declarations (hoisted: a call before its site still resolves) —
  each nested declaration gets its own summary, and one that reads
  an enclosing local closes itself (no closures) without disturbing
  the caller's admission. The result conservatively depends on
  every evaluated argument and records a `TsCall` transfer; the callee
  body is opaque (self-recursion records a transfer like any other
  name-resolved call). Everything else — calls through a
  non-callable field, unresolved names, `new` — stays closed.

Closed with declared gaps: `import`/`export` and ambient/`declare`
declarations close the whole unit (`unsupported_unit`); classes,
`this`, getters/setters,
generators, `any`/composite/missing parameter
types, `new` and
generator/tagged-template function values stay
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
    # `in`/`instanceof` yield booleans — the operand dep union is
    # the over-approximation.
    "in", "instanceof",
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


class _Composite:
    """An object-shaped value: field name -> scalar deps or nested
    `_Composite`. Treated as immutable — a member write produces a
    new instance bound to the base name, so branch scopes may share
    an instance freely."""

    __slots__ = ("fields",)

    def __init__(self, fields: dict) -> None:
        self.fields = fields


class _Callable:
    """A function value: an `arrow_function`/`function_expression`
    bound to a name. `params`/`defaults` describe its formal
    parameters; `captured` over-approximates its closure reads —
    the union of every visible binding's deps at the definition
    site — so passing or returning the value is a scalar.
    `rest` is the index of a `...rest` formal (-1 when absent):
    invocation binds it to the union of every remaining actual."""

    __slots__ = ("node", "params", "defaults", "captured", "rest")

    def __init__(self, node, params, defaults, captured, rest=-1) -> None:
        self.node = node
        self.params = params
        self.defaults = defaults
        self.captured = captured
        self.rest = rest


def _scalar_of(value) -> frozenset[int]:
    """Flatten a value to scalar deps — reading or passing a whole
    composite over-approximates to the union of its leaf deps; a
    callable flattens to its captured deps."""
    if isinstance(value, _Composite):
        result = frozenset()
        for field in value.fields.values():
            result |= _scalar_of(field)
        return result
    if isinstance(value, _Callable):
        return value.captured
    return value


def _merge_vals(old, new):
    """Join two values: scalar|scalar unions, composite|composite
    merges field-wise, and a shape mismatch collapses the composite
    to its leaf deps (a name can't be both shapes at once)."""
    if isinstance(old, _Composite) and isinstance(new, _Composite):
        fields = dict(old.fields)
        for key, nval in new.fields.items():
            if key in fields:
                fields[key] = _merge_vals(fields[key], nval)
            else:
                fields[key] = nval
        return _Composite(fields)
    if isinstance(old, _Composite) or isinstance(new, _Composite):
        return _scalar_of(old) | _scalar_of(new)
    # Two callables (or a callable and a scalar) join to the
    # captured-deps union — the name may hold either callee.
    return _scalar_of(old) | _scalar_of(new)


def _val_leq(new, old) -> bool:
    """`new` adds nothing over `old` — the fixed-point test."""
    if isinstance(old, _Composite) and isinstance(new, _Composite):
        for key, nval in new.fields.items():
            if key not in old.fields or not _val_leq(
                nval, old.fields[key]
            ):
                return False
        return True
    if isinstance(new, _Composite):
        return _scalar_of(new) <= _scalar_of(old)
    if isinstance(old, _Composite):
        return False
    return _scalar_of(new) <= _scalar_of(old)


def _composite_delete(composite, path, span):
    """Copy-on-write `delete composite.path` — removes the leaf
    field and returns the updated `_Composite`."""
    fields = dict(composite.fields)
    key = path[0]
    if len(path) == 1:
        fields.pop(key, None)
    else:
        sub = fields.get(key)
        if not isinstance(sub, _Composite):
            # The intermediate field is scalar or absent — nothing
            # to delete through.
            raise _Unsupported("unsupported_expression", span)
        fields[key] = _composite_delete(sub, path[1:], span)
    return _Composite(fields)


def _composite_set(composite, path, value, conditional, span):
    """Copy-on-write member store: `composite.path = value`,
    returning the updated `_Composite`."""
    fields = dict(composite.fields)
    key = path[0]
    if len(path) == 1:
        old = fields.get(key)
        fields[key] = (
            _merge_vals(old, value)
            if conditional and old is not None
            else value
        )
    else:
        sub = fields.get(key)
        if not isinstance(sub, _Composite):
            raise _Unsupported("unsupported_expression", span)
        fields[key] = _composite_set(
            sub, path[1:], value, conditional, span
        )
    return _Composite(fields)


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
        # Whether a `throw` on some path unwound the current statement
        # list — statements after it are may-writes until a `catch`
        # consumes the flag or it propagates out of the function.
        self.thrown: list[bool] = [False]
        # Labels the next loop/switch frame claims — a `break L` or
        # `continue L` looks its frame up by name.
        self.pending_labels: list[str] = []

    def _register_nested_functions(self, node) -> None:
        """Register every `function inner() {}` declaration under
        `node` in the unit's call table — function declarations
        hoist within their enclosing function."""
        if node.type == "function_declaration":
            inner_name = node.child_by_field_name("name")
            if inner_name is not None:
                self.functions[inner_name.text.decode()] = node
            return
        for child in _children(node):
            self._register_nested_functions(child)

    def summarize_all(self) -> tuple[TsFunctionSummary, ...]:
        # Summarizing a body can register nested function
        # declarations — walk the table to a fixed point.
        results: list[TsFunctionSummary] = []
        seen: set[int] = set()
        queue = list(self.functions.values())
        i = 0
        while i < len(queue):
            node = queue[i]
            i += 1
            if id(node) in seen:
                continue
            seen.add(id(node))
            results.append(self.summarize(node))
            for inner in self.functions.values():
                if id(inner) not in seen:
                    queue.append(inner)
        return tuple(results)

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
        # and a statement_block body. `function*` (`*` markers) stays
        # closed — a `yield` needs state the model has no slot for;
        # `async` admits since `await` degrades to operand deps in the
        # dep model (a promise resolves to its value).
        for child in node.children:
            if not child.is_named and child.type == "*":
                raise _Unsupported("unsupported_signature", _span(node))
        params_node = node.child_by_field_name("parameters")
        body = node.child_by_field_name("body")
        ret = node.child_by_field_name("return_type")
        if params_node is None or body is None or body.type != "statement_block":
            raise _Unsupported("unsupported_signature", _span(node))
        if ret is None or not self._scalar_annotation(ret):
            raise _Unsupported("unsupported_signature", _span(node))
        params: dict[str, int] = {}
        destructured: list = []
        rest_seen = False
        for param in _children(params_node):
            # `x?: number` and `x: number = 0` admit like a required
            # parameter — the index position is what the summary
            # records; an omitted argument is the caller's concern.
            if param.type not in {"required_parameter", "optional_parameter"}:
                raise _Unsupported("unsupported_signature", _span(param))
            pattern = param.child_by_field_name("pattern")
            ptype = param.child_by_field_name("type")
            if rest_seen:
                raise _Unsupported("unsupported_signature", _span(param))
            if pattern is not None and pattern.type == "rest_pattern":
                # `...rest` occupies the last slot; the index's dep
                # stands for "args at this index and beyond" — the
                # call arm already unions every evaluated argument,
                # so reading `rest` is sound under the index model.
                target = next(iter(_children(pattern)), None)
                if target is None or target.type != "identifier":
                    raise _Unsupported(
                        "unsupported_signature", _span(param)
                    )
                pname = target.text.decode()
                if pname in params:
                    raise _Unsupported(
                        "unsupported_signature", _span(param)
                    )
                params[pname] = len(params)
                rest_seen = True
                continue
            if pattern is not None and pattern.type in {
                "object_pattern",
                "array_pattern",
            }:
                # `f({a, b}, [x])` — the slot still occupies one
                # scalar index; the pattern's sub-names destructure
                # it at body start (each sees the whole slot's deps).
                pname = pattern.text.decode()
                if pname in params:
                    raise _Unsupported(
                        "unsupported_signature", _span(param)
                    )
                params[pname] = len(params)
                destructured.append((pattern, params[pname]))
                continue
            if (
                pattern is None
                or pattern.type != "identifier"
                or ptype is None
                or not self._scalar_annotation(ptype)
            ):
                raise _Unsupported("unsupported_signature", _span(param))
            pname = pattern.text.decode()
            if pname in params:
                raise _Unsupported("unsupported_signature", _span(param))
            params[pname] = len(params)

        locals_: dict[str, object] = {}
        self.function_locals = locals_
        self.var_names = set()
        self.block_stack = []
        self.thrown = [False]
        self.pending_labels = []
        transfers: list[TsCall] = []
        count = [0]
        deps = [frozenset()]
        # A default value evaluates only on a missing argument, but its
        # calls still belong to this function's behavior — evaluate it
        # for transfers with no local scope yet.
        for param in _children(params_node):
            default = param.child_by_field_name("value")
            if default is not None:
                self.expression(
                    default, params, locals_, transfers, count
                )
        # Destructured parameters bind their sub-names to member
        # reads of the slot — a scalar slot unions into every name.
        for pat, idx in destructured:
            self._destructure(
                pat,
                frozenset({idx}),
                params,
                locals_,
                transfers,
                count,
                False,
                False,
                _span(pat),
            )
        # Function declarations hoist to the enclosing function's
        # scope — pre-register every `function inner() {}` in the
        # body subtree so calls resolve wherever they appear.
        for inner_decl in body.children:
            self._register_nested_functions(inner_decl)
        self.frames = []
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
        for child in children:
            if (
                any(f["exited"] for f in self.frames)
                or self.thrown[0]
            ):
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
                value = _merge_vals(locals_[name], value)
            elif name in params:
                # A parameter is a scalar slot — a composite stored
                # into it collapses to the union of its leaf deps.
                value = frozenset({params[name]}) | _scalar_of(value)
        locals_[name] = value

    def _declare_name(
        self, name, value, is_var, conditional, params, locals_
    ) -> None:
        """Bind a declared name honouring `var`'s function scope and
        let/const block-scope restore."""
        if is_var:
            # `var` is function-scoped: it lands in the current
            # scope and the joins carry the name outward — writing
            # the function scope directly would bypass a loop's
            # fixed-point join and lose the zero-trip path's
            # dependencies.
            self.var_names.add(name)
            self._store(locals_, params, name, value, conditional)
        else:
            if self.block_stack:
                saved = self.block_stack[-1]
                if name not in saved:
                    saved[name] = locals_.get(name)
            self._store(locals_, params, name, value, conditional)

    def _destructure(
        self,
        pattern,
        value,
        params,
        locals_,
        transfers,
        count,
        is_var,
        conditional,
        span,
    ) -> None:
        """`const {a, b: c = d, ...rest} = o` / `const [x, y] = arr` —
        each sub-name binds the member read at its path; a scalar
        source or a `...rest` binding over-approximates to the whole
        union. A composite member binds as a scalar (member-path
        rule — sub-object writes can't diverge)."""
        positions: dict[int, int] = {}
        if pattern.type == "array_pattern":
            # A hole (`[a, , b]`) emits no named child — walk ALL
            # children: an empty slot is a comma seen while an
            # element is expected.
            pos = 0
            expecting = True
            for c in pattern.children:
                if c.type in {"[", "]"}:
                    continue
                if c.type == ",":
                    if expecting:
                        pos += 1
                    else:
                        expecting = True
                    continue
                positions[c.id] = pos
                pos += 1
                expecting = False
        for child in _children(pattern):
            if child.type == "rest_pattern":
                inner = next(iter(_children(child)), None)
                if inner is None or inner.type != "identifier":
                    raise _Unsupported("binding_unavailable", span)
                # The remaining fields are unknowable — the whole
                # union over-approximates.
                self._declare_name(
                    inner.text.decode(),
                    _scalar_of(value),
                    is_var,
                    conditional,
                    params,
                    locals_,
                )
                continue
            if child.type == "pair_pattern":
                if pattern.type != "object_pattern":
                    raise _Unsupported("binding_unavailable", span)
                key = child.child_by_field_name("key")
                target = child.child_by_field_name("value")
                if key is None or target is None or key.type not in {
                    "property_identifier",
                    "string",
                    "number",
                }:
                    raise _Unsupported("binding_unavailable", span)
                kname = (
                    key.text.decode().strip("\"'")
                    if key.type == "string"
                    else key.text.decode()
                )
                fval = self._pattern_read(value, kname)
                self._destructure_target(
                    target, fval, params, locals_, transfers, count,
                    is_var, conditional, span,
                )
                continue
            if pattern.type == "array_pattern":
                key = str(positions[child.id])
                self._destructure_target(
                    child,
                    self._pattern_read(value, key),
                    params,
                    locals_,
                    transfers,
                    count,
                    is_var,
                    conditional,
                    span,
                )
                continue
            if child.type in {
                "shorthand_property_identifier",
                "shorthand_property_identifier_pattern",
                "object_assignment_pattern",
            }:
                if child.type in {
                    "shorthand_property_identifier",
                    "shorthand_property_identifier_pattern",
                }:
                    name = child.text.decode()
                    self._declare_name(
                        name,
                        _scalar_of(self._pattern_read(value, name)),
                        is_var,
                        conditional,
                        params,
                        locals_,
                    )
                    continue
                left = child.child_by_field_name("left")
                right = child.child_by_field_name("right")
                if left is None or left.type not in {
                    "identifier",
                    "shorthand_property_identifier_pattern",
                }:
                    raise _Unsupported("binding_unavailable", span)
                name = left.text.decode()
                deps = _scalar_of(self._pattern_read(value, name))
                if right is not None:
                    deps |= self.expression(
                        right, params, locals_, transfers, count
                    )
                self._declare_name(
                    name, deps, is_var, conditional, params, locals_
                )
                continue
            raise _Unsupported("binding_unavailable", span)

    def _destructure_target(
        self,
        target,
        fval,
        params,
        locals_,
        transfers,
        count,
        is_var,
        conditional,
        span,
    ) -> None:
        if target.type == "identifier":
            self._declare_name(
                target.text.decode(),
                _scalar_of(fval),
                is_var,
                conditional,
                params,
                locals_,
            )
            return
        if target.type in {
            "assignment_pattern",
            "object_assignment_pattern",
        }:
            left = target.child_by_field_name("left")
            right = target.child_by_field_name("right")
            if left is None or left.type != "identifier":
                raise _Unsupported("binding_unavailable", span)
            deps = _scalar_of(fval)
            if right is not None:
                deps |= self.expression(
                    right, params, locals_, transfers, count
                )
            self._declare_name(
                left.text.decode(),
                deps,
                is_var,
                conditional,
                params,
                locals_,
            )
            return
        if target.type in {"object_pattern", "array_pattern"}:
            self._destructure(
                target,
                fval,
                params,
                locals_,
                transfers,
                count,
                is_var,
                conditional,
                span,
            )
            return
        raise _Unsupported("binding_unavailable", span)

    @staticmethod
    def _pattern_read(value, key):
        """Field `key` of a destructured composite — a scalar source
        over-approximates every sub-name to the whole union."""
        if isinstance(value, _Composite):
            return value.fields.get(key, frozenset())
        return value

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
                if pname is None:
                    raise _Unsupported("binding_unavailable", _span(decl))
                annotation = decl.child_by_field_name("type")
                if annotation is not None and not self._scalar_annotation(
                    annotation
                ):
                    raise _Unsupported("binding_unavailable", _span(decl))
                value = decl.child_by_field_name("value")
                if pname.type in {"object_pattern", "array_pattern"}:
                    if value is None:
                        raise _Unsupported(
                            "binding_unavailable", _span(decl)
                        )
                    val_v = self._eval(
                        value, params, locals_, transfers, count
                    )
                    self._destructure(
                        pname,
                        val_v,
                        params,
                        locals_,
                        transfers,
                        count,
                        is_var,
                        conditional,
                        _span(decl),
                    )
                    continue
                if pname.type != "identifier":
                    raise _Unsupported("binding_unavailable", _span(decl))
                deps_v = (
                    self._bindable(
                        value,
                        self._eval(
                            value, params, locals_, transfers, count
                        ),
                    )
                    if value is not None
                    # `let x;` binds `undefined` — no dependencies.
                    else frozenset()
                )
                self._declare_name(
                    pname.text.decode(),
                    deps_v,
                    is_var,
                    conditional,
                    params,
                    locals_,
                )
            return
        if kind == "function_declaration":
            # Already registered by the hoisting pass — a declaration
            # statement evaluates to nothing.
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
            self._join(locals_, branch, params, self.var_names)
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
                self._join(locals_, branch, params, self.var_names)
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
            # `let`/`const` in the initializer are scoped to the loop:
            # they register in a for-local restore map, never the
            # enclosing block's — otherwise the block's exit would
            # rewind assignments made after the loop.
            for_saved: dict[str, frozenset[int] | None] = {}
            self.block_stack.append(for_saved)
            try:
                initializer = node.child_by_field_name("initializer")
                if initializer is not None:
                    self._for_part(
                        initializer, params, scope, transfers, count,
                        deps, saw_return, conditional,
                    )
                condition = node.child_by_field_name("condition")
                increment = node.child_by_field_name("increment")
                self._loop(
                    body, increment, condition, params, scope,
                    transfers, count, deps, saw_return, conditional,
                    node,
                )
            finally:
                for name, prev in for_saved.items():
                    if prev is None:
                        scope.pop(name, None)
                    else:
                        scope[name] = prev
                self.block_stack.pop()
            self._join(locals_, scope, params, self.var_names)
            return
        if kind == "for_in_statement":
            # `for (const k in o)` iterates a composite's fields — the
            # key is an opaque string (dep-free); `for (const e of o)`
            # iterates values — the element binds the union of every
            # field's deps (the model has no arrays, so composites are
            # the only admitted right-hand side; anything else closes).
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            kind_node = node.child_by_field_name("kind")
            op = node.child_by_field_name("operator")
            body = node.child_by_field_name("body")
            if (
                left is None
                or right is None
                or op is None
                or body is None
                or left.type != "identifier"
                or (kind_node is not None and kind_node.type not in {
                    "let", "const", "var",
                })
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            iterated = self._eval(right, params, locals_, transfers, count)
            if not isinstance(iterated, _Composite):
                raise _Unsupported("unsupported_statement", _span(node))
            scope = dict(locals_)
            if op.type == "in":
                element = frozenset()
            else:
                element = _scalar_of(iterated)
            kname = left.text.decode()
            is_var = kind_node is not None and kind_node.type == "var"
            for_saved: dict[str, object] = {}
            self.block_stack.append(for_saved)
            try:
                if kind_node is not None:
                    if is_var:
                        self.var_names.add(kname)
                    else:
                        for_saved[kname] = scope.get(kname)
                    scope[kname] = element
                else:
                    # `for (k in o)` — an assignment target: the loop
                    # may not run, so the bind is a may-write.
                    target = self._write_scope(kname, scope, params)
                    if target is None:
                        raise _Unsupported(
                            "binding_unavailable", _span(left)
                        )
                    self._store(target, params, kname, element, True)
                self._loop(
                    body, None, None, params, scope, transfers, count,
                    deps, saw_return, conditional, node,
                )
            finally:
                for sname, prev in for_saved.items():
                    if prev is None:
                        scope.pop(sname, None)
                    else:
                        scope[sname] = prev
                self.block_stack.pop()
            self._join(locals_, scope, params, self.var_names)
            return
        if kind == "switch_statement":
            value = node.child_by_field_name("value")
            body = node.child_by_field_name("body")
            if value is None or body is None:
                raise _Unsupported("unsupported_statement", _span(node))
            self.expression(value, params, locals_, transfers, count)
            # Fallthrough: a `break` only ends paths that entered at an
            # earlier clause — each clause can still be entered
            # directly, so every body is processed as a may-write in a
            # shared scope (a clause with no statements simply adds
            # nothing before the next).
            frame = {
                "exited": False, "broke": False,
                "broke_always": False, "loop": False,
                "label": (
                    self.pending_labels.pop()
                    if self.pending_labels
                    else None
                ),
            }
            self.frames.append(frame)
            # `let`/`const` in a clause share the switch's block scope —
            # they restore when the switch ends, not at the enclosing
            # block's exit.
            saved: dict[str, frozenset[int] | None] = {}
            self.block_stack.append(saved)
            try:
                scope = dict(locals_)
                for clause in _children(body):
                    if clause.type not in {"switch_case", "switch_default"}:
                        raise _Unsupported(
                            "unsupported_statement", _span(clause)
                        )
                    if clause.type == "switch_case":
                        case_value = clause.child_by_field_name("value")
                        if case_value is None:
                            raise _Unsupported(
                                "unsupported_statement", _span(clause)
                            )
                        self.expression(
                            case_value, params, scope, transfers, count
                        )
                    frame["exited"] = False
                    self._sequence(
                        [
                            c
                            for i, c in enumerate(clause.children)
                            if clause.field_name_for_child(i) == "body"
                        ],
                        params, scope, transfers, count, deps,
                        saw_return, True,
                    )
                for name, prev in saved.items():
                    if prev is None:
                        scope.pop(name, None)
                    else:
                        scope[name] = prev
                self._join(locals_, scope, params, self.var_names)
            finally:
                self.block_stack.pop()
                self.frames.pop()
            return
        if kind == "do_statement":
            body = node.child_by_field_name("body")
            condition = node.child_by_field_name("condition")
            if body is None or condition is None:
                raise _Unsupported("unsupported_statement", _span(node))
            # The body runs at least once — a distinction the
            # union-joined fixed point does not model, so it shares
            # the `while` loop shape.
            self._loop(
                body, None, condition, params, locals_, transfers, count,
                deps, saw_return, conditional, node,
            )
            return
        if kind == "throw_statement":
            thrown_expr = next(iter(_children(node)), None)
            if thrown_expr is not None:
                self.expression(
                    thrown_expr, params, locals_, transfers, count
                )
            # The throw unwinds to the nearest `catch` or out of the
            # function — every later statement is a may-write until a
            # `catch` clears the flag.
            self.thrown[0] = True
            return
        if kind == "try_statement":
            body = node.child_by_field_name("body")
            handler = node.child_by_field_name("handler")
            finalizer = node.child_by_field_name("finalizer")
            if body is None or (
                handler is None and finalizer is None
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            catch_body = None
            if handler is not None:
                catch_body = handler.child_by_field_name("body")
                catch_param = handler.child_by_field_name("parameter")
                if catch_body is None or (
                    catch_param is not None
                    and catch_param.type != "identifier"
                ):
                    raise _Unsupported(
                        "unsupported_statement", _span(handler)
                    )
            fin_body = None
            if finalizer is not None:
                fin_body = finalizer.child_by_field_name("body")
                if fin_body is None:
                    raise _Unsupported(
                        "unsupported_statement", _span(finalizer)
                    )
            self.statement(
                body, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
            propagated = self.thrown[0]
            self.thrown[0] = False
            if catch_body is not None:
                # The `catch` parameter is left unbound — a body that
                # reads it closes with `binding_unavailable`. The
                # clause only runs on a thrown path, so its writes are
                # always may-writes; a rethrow inside stays flagged.
                self.statement(
                    catch_body, params, locals_, transfers, count,
                    deps, saw_return, True,
                )
                propagated = self.thrown[0]
            self.thrown[0] = False
            if fin_body is not None:
                # `finally` always runs — the propagating flag is
                # parked so its statements are not may-writes.
                self.statement(
                    fin_body, params, locals_, transfers, count,
                    deps, saw_return, conditional,
                )
                propagated = propagated or self.thrown[0]
            self.thrown[0] = propagated
            return
        if kind == "labeled_statement":
            label = node.child_by_field_name("label")
            body = node.child_by_field_name("body")
            if label is None or body is None:
                raise _Unsupported("unsupported_statement", _span(node))
            name = label.text.decode()
            if body.type in {
                "while_statement",
                "for_statement",
                "do_statement",
                "switch_statement",
            }:
                # The loop/switch claims the label on the frame it
                # pushes — a `break L` / `continue L` then finds it.
                self.pending_labels.append(name)
                try:
                    self.statement(
                        body, params, locals_, transfers, count, deps,
                        saw_return, conditional,
                    )
                finally:
                    if name in self.pending_labels:
                        self.pending_labels.remove(name)
                return
            # Any other labeled statement (a block, another label,
            # ...) gets a plain frame — `break L` exits it and a
            # `continue` skips it like it skips a `switch`.
            frame = {
                "exited": False, "broke": False,
                "broke_always": False, "loop": False, "label": name,
            }
            self.frames.append(frame)
            try:
                self.statement(
                    body, params, locals_, transfers, count, deps,
                    saw_return, conditional,
                )
            finally:
                self.frames.pop()
            return
        if kind in {"break_statement", "continue_statement"}:
            label_node = next(
                (
                    c
                    for c in node.named_children
                    if c.type == "statement_identifier"
                ),
                None,
            )
            if len(node.named_children) > (1 if label_node else 0):
                raise _Unsupported("unsupported_statement", _span(node))
            if label_node is not None:
                target = label_node.text.decode()
                frame = next(
                    (
                        f
                        for f in reversed(self.frames)
                        if f.get("label") == target
                        and (
                            kind == "break_statement" or f.get("loop")
                        )
                    ),
                    None,
                )
            elif kind == "continue_statement":
                # A `continue` inside a `switch` or labeled block
                # targets the enclosing loop — skip non-loop frames.
                frame = next(
                    (
                        f for f in reversed(self.frames) if f.get("loop")
                    ),
                    None,
                )
            else:
                frame = self.frames[-1] if self.frames else None
            if frame is None:
                raise _Unsupported("unsupported_statement", _span(node))
            frame["exited"] = True
            # A `break` skips the for-increment on its own exit but
            # leaves the non-breaking exit — the increment's stores
            # then join as may-writes. `continue` never disturbs it.
            if kind == "break_statement":
                frame["broke"] = True
                if not conditional:
                    # Only an unconditional break leaves no exit that
                    # reaches the increment at all.
                    frame["broke_always"] = True
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
            or (augmented and (op is None or op.type not in _AUGMENTED_OPS))
            or (not augmented and op is not None and op.type != "=")
        ):
            raise _Unsupported("unsupported_statement", _span(node))
        value = self._eval(right, params, locals_, transfers, count)
        if left.type == "identifier":
            name = left.text.decode()
            target = self._write_scope(name, locals_, params)
            if target is None:
                raise _Unsupported("binding_unavailable", _span(left))
            if augmented:
                value = (
                    self._read_name(left, params, locals_, _span(left))
                    | _scalar_of(value)
                )
            else:
                value = self._bindable(right, value)
            self._store(target, params, name, value, conditional)
            return
        if left.type in {"member_expression", "subscript_expression"}:
            if augmented:
                value = (
                    _scalar_of(
                        self._member_read(
                            left, params, locals_, transfers, count
                        )
                    )
                    | _scalar_of(value)
                )
            self._member_store(
                left, value, params, locals_, transfers, count,
                conditional,
            )
            return
        raise _Unsupported("unsupported_statement", _span(node))

    def _write_scope(self, name, locals_, params):
        """The scope a store lands in: block first, then the function
        scope a `var` may have escaped into, then a parameter (stored
        in the current scope as a shadow)."""
        if name in locals_:
            return locals_
        if name in params or name in self.var_names:
            # `var` assignments land in the current scope — the joins
            # carry them out to the function scope.
            return locals_
        return None

    def _update(self, node, params, locals_, transfers, count, conditional):
        argument = node.child_by_field_name("argument")
        if argument is None or argument.type not in {
            "identifier",
            "member_expression",
            "subscript_expression",
        }:
            raise _Unsupported("unsupported_statement", _span(node))
        if argument.type == "identifier":
            name = argument.text.decode()
            target = self._write_scope(name, locals_, params)
            if target is None:
                raise _Unsupported("binding_unavailable", _span(argument))
            self._store(
                target, params, name,
                self._read_name(
                    argument, params, locals_, _span(argument)
                ),
                conditional,
            )
            return
        # `o.f++` — dep-preserving member write.
        self._member_store(
            argument,
            _scalar_of(
                self._member_read(
                    argument, params, locals_, transfers, count
                )
            ),
            params,
            locals_,
            transfers,
            count,
            conditional,
        )

    def _loop(
        self, body, increment, condition, params, scope, transfers,
        count, deps, saw_return, conditional, node,
    ) -> None:
        """Iterate a loop body to a dependency fixed point — a join, not
        an unroll; trip counts are never modelled."""
        passes = 0
        frame = {
            "exited": False, "broke": False, "broke_always": False,
            "loop": True,
            "label": (
                self.pending_labels.pop()
                if self.pending_labels
                else None
            ),
        }
        self.frames.append(frame)
        try:
            while True:
                mark = len(transfers)
                frame["exited"] = False
                frame["broke"] = False
                frame["broke_always"] = False
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
                if increment is not None and not frame["broke_always"]:
                    # The increment runs after each pass so its writes
                    # seed the next iteration — a `break` skips it
                    # only when no exit reaches the increment at all,
                    # and a conditional break keeps it a may-write.
                    self._for_part(
                        increment, params, inner, transfers, count, deps,
                        saw_return, conditional or frame["broke"],
                    )
                changed = False
                for name, ndeps in inner.items():
                    if name in scope:
                        if not _val_leq(ndeps, scope[name]):
                            scope[name] = _merge_vals(scope[name], ndeps)
                            changed = True
                    elif name in params:
                        scope[name] = (
                            frozenset({params[name]}) | _scalar_of(ndeps)
                        )
                        changed = True
                    elif name in self.var_names:
                        # `var` is function-scoped: a declaration or
                        # assignment inside the body escapes the loop
                        # like any may-write.
                        scope[name] = _merge_vals(
                            scope.get(name, frozenset()), ndeps
                        )
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
    def _join(scope, branch, params, var_names) -> None:
        # Branch-local bindings (names absent from `scope`) never
        # escape — only existing, parameter and `var` names merge.
        for name, value in branch.items():
            if name in scope:
                scope[name] = _merge_vals(scope[name], value)
            elif name in params:
                scope[name] = (
                    frozenset({params[name]}) | _scalar_of(value)
                )
            elif name in var_names:
                # `var` is function-scoped: a declaration inside a
                # branch escapes it like any may-write.
                scope[name] = value

    @staticmethod
    def _bindable(node, value):
        """A composite may only bind via an object literal or a
        whole-name alias (`p = o` shares the instance — writes
        propagate to every holder). A member-path result bound to a
        name would let writes through either side diverge, so it
        collapses to its leaf deps. A callable binds via its literal
        or a name alias; anything else (a member path, a call
        result) collapses to the captured deps."""
        if isinstance(value, (_Composite, _Callable)) and (
            node.type
            not in {
                "object",
                "array",
                "identifier",
                "arrow_function",
                "function_expression",
            }
        ):
            return _scalar_of(value)
        return value

    def _lookup(self, name, params, locals_, span):
        """The raw binding for `name` — a scalar dep set or a
        `_Composite`."""
        if name in locals_:
            return locals_[name]
        if name in self.function_locals:
            return self.function_locals[name]
        if name in params:
            return frozenset({params[name]})
        raise _Unsupported("binding_unavailable", span)

    def _read_name(self, node, params, locals_, span) -> frozenset[int]:
        return _scalar_of(
            self._lookup(node.text.decode(), params, locals_, span)
        )

    def _member_target(
        self, node, params, locals_, transfers, count
    ):
        """Walk a `obj.f` / `obj[k]` / parenthesized chain down to its
        base identifier — returns `(base name, field path,
        index deps)`. A `None` path step marks a dynamic key, whose
        index still evaluates for deps and calls."""
        path: list = []
        index_deps = frozenset()
        cur = node
        while cur.type in {
            "member_expression",
            "subscript_expression",
            "parenthesized_expression",
        }:
            if cur.type == "parenthesized_expression":
                inner = next(iter(_children(cur)), None)
                if inner is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(cur)
                    )
                cur = inner
                continue
            if cur.type == "member_expression":
                prop = cur.child_by_field_name("property")
                if prop is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(cur)
                    )
                path.append(prop.text.decode())
            else:
                index = cur.child_by_field_name("index")
                if index is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(cur)
                    )
                # Literal keys carry no deps or calls; a dynamic
                # index evaluates for both.
                if index.type == "string":
                    path.append(index.text.decode().strip("\"'"))
                elif index.type == "number":
                    path.append(index.text.decode())
                else:
                    index_deps |= self.expression(
                        index, params, locals_, transfers, count
                    )
                    path.append(None)
            obj = cur.child_by_field_name("object")
            if obj is None:
                raise _Unsupported(
                    "unsupported_expression", _span(cur)
                )
            cur = obj
        if cur.type != "identifier":
            raise _Unsupported("unsupported_expression", _span(cur))
        path.reverse()
        return cur.text.decode(), path, index_deps

    def _member_read(self, node, params, locals_, transfers, count):
        """`o.f` / `o.a.b` — descend the base's `_Composite` to the
        field's raw value. A missing field is `undefined` (no deps);
        a dynamic key step over-approximates to every field at that
        level plus the index's deps."""
        base, path, index_deps = self._member_target(
            node, params, locals_, transfers, count
        )
        val = self._lookup(base, params, locals_, _span(node))
        for key in path:
            if not isinstance(val, _Composite):
                raise _Unsupported("unsupported_expression", _span(node))
            if key is None:
                return _scalar_of(val) | index_deps
            val = val.fields.get(key, frozenset())
        return val

    def _member_delete(
        self, node, params, locals_, transfers, count
    ) -> None:
        """`delete o.f` — copy-on-write removal of a literal-key
        field, propagated to every alias in scope. A dynamic key
        (`delete o[k]`) may remove ANY field, so every field's deps
        stay (the model can't represent absence — keeping the deps
        is the over-approximation)."""
        base, path, _ = self._member_target(
            node, params, locals_, transfers, count
        )
        if any(key is None for key in path):
            return
        target = self._write_scope(base, locals_, params)
        if target is None:
            raise _Unsupported("binding_unavailable", _span(node))
        old = target.get(base)
        if not isinstance(old, _Composite):
            raise _Unsupported("unsupported_expression", _span(node))
        new = _composite_delete(old, path, _span(node))
        for name, val in locals_.items():
            if val is old:
                locals_[name] = new

    def _member_store(
        self, node, value, params, locals_, transfers, count,
        conditional,
    ) -> None:
        """`o.f = v` — copy-on-write the field into the base binding.
        The base must bind a `_Composite` in a writable scope; a
        dynamic subscript key can't pick a field, so it closes.
        Composite bindings alias (`p = o` shares the instance), so
        the write propagates to every name holding it."""
        base, path, _ = self._member_target(
            node, params, locals_, transfers, count
        )
        if any(key is None for key in path):
            raise _Unsupported("unsupported_expression", _span(node))
        target = self._write_scope(base, locals_, params)
        if target is None:
            raise _Unsupported("binding_unavailable", _span(node))
        old = target.get(base)
        if not isinstance(old, _Composite):
            raise _Unsupported("unsupported_expression", _span(node))
        if isinstance(value, _Composite):
            # `o.f = o2` would alias `o2` at field level — writes
            # would diverge, so a composite field value collapses.
            value = _scalar_of(value)
        new = _composite_set(
            old, path, value, conditional, _span(node)
        )
        # Every binding IN THIS SCOPE sharing the instance is an
        # alias — the write reaches all of them. Only `locals_` is
        # scanned: eagerly rewriting the enclosing scope would
        # defeat a loop's fixed-point join (the join itself carries
        # the update outward, over-approximating skipped paths).
        for name, val in locals_.items():
            if val is old:
                locals_[name] = new

    def expression(self, node, params, locals_, transfers, count):
        """Evaluate a node to scalar dependencies — a composite
        flattens to the union of its leaf deps."""
        return _scalar_of(
            self._eval(node, params, locals_, transfers, count)
        )

    def _callable_value(self, node, params, locals_):
        """`const g = (v) => v + x` — the arrow/function value.
        `captured` is the union of every visible binding's deps at
        the definition site, so the closure's free reads are
        over-approximated even when the callable escapes (returned
        or passed as an argument)."""
        names, defaults, rest = self._callable_params(node)
        captured = frozenset(params.values())
        for val in locals_.values():
            captured |= _scalar_of(val)
        return _Callable(node, names, defaults, captured, rest)

    def _callable_params(self, node):
        """`(a, b = d, ...rest)` / `x =>` — the formal parameter
        names plus any default expressions (evaluated at the call
        site) and the rest index (-1 when absent). A rest
        parameter must come last; destructured/typed-non-scalar
        parameters close."""
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            p = node.child_by_field_name("parameter")
            if p is None or p.type != "identifier":
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            return (p.text.decode(),), {}, -1
        names: list[str] = []
        defaults: dict[int, object] = {}
        rest = -1
        for param in _children(params_node):
            if rest >= 0:
                # A parameter after `...rest` is unreachable —
                # closed rather than analyzed wrongly.
                raise _Unsupported(
                    "unsupported_expression", _span(param)
                )
            if param.type not in {
                "required_parameter",
                "optional_parameter",
            }:
                raise _Unsupported(
                    "unsupported_expression", _span(param)
                )
            pattern = param.child_by_field_name("pattern")
            ptype = param.child_by_field_name("type")
            if pattern is not None and pattern.type == "rest_pattern":
                target = next(
                    iter(_children(pattern)), None
                )
                if target is None or target.type != "identifier":
                    raise _Unsupported(
                        "unsupported_expression", _span(param)
                    )
                names.append(target.text.decode())
                rest = len(names) - 1
                continue
            if pattern is None or (
                ptype is not None
                and not self._scalar_annotation(ptype)
            ):
                raise _Unsupported(
                    "unsupported_expression", _span(param)
                )
            if pattern.type == "identifier":
                names.append(pattern.text.decode())
                dflt = param.child_by_field_name("value")
                if dflt is not None:
                    defaults[len(names) - 1] = dflt
            elif pattern.type == "assignment_pattern":
                left = pattern.child_by_field_name("left")
                right = pattern.child_by_field_name("right")
                if left is None or left.type != "identifier":
                    raise _Unsupported(
                        "unsupported_expression", _span(param)
                    )
                names.append(left.text.decode())
                if right is not None:
                    defaults[len(names) - 1] = right
            else:
                raise _Unsupported(
                    "unsupported_expression", _span(param)
                )
        return tuple(names), defaults, rest

    def _invoke_callable(
        self,
        cval,
        actual,
        params,
        locals_,
        transfers,
        count,
        span,
    ) -> frozenset[int]:
        """`g(args)` where `g` binds an arrow/function value —
        evaluate the body inline. Captured names read the CALL
        site's bindings (closures capture by reference — the
        latest value over-approximates); writes inside the body
        merge back as may-writes so member stores aren't lost;
        the body's own frames/scope state is isolated and
        restored."""
        inner = dict(locals_)
        for i, pname in enumerate(cval.params):
            if i == cval.rest:
                # `...rest` collects every remaining argument —
                # dep-wise the union of them all.
                deps = frozenset()
                for extra in actual[i:]:
                    deps |= extra
            else:
                deps = actual[i] if i < len(actual) else frozenset()
            dnode = cval.defaults.get(i)
            if dnode is not None:
                deps |= self.expression(
                    dnode, params, inner, transfers, count
                )
            inner[pname] = deps
        body_node = cval.node.child_by_field_name("body")
        if body_node is None:
            raise _Unsupported("unsupported_expression", span)
        saved_frames, self.frames = self.frames, []
        saved_thrown, self.thrown = self.thrown, [False]
        saved_block, self.block_stack = self.block_stack, []
        saved_var, self.var_names = self.var_names, set()
        saved_flocals, self.function_locals = self.function_locals, inner
        try:
            if body_node.type == "statement_block":
                adeps = [frozenset()]
                saw = [False]
                self._sequence(
                    _children(body_node),
                    params,
                    inner,
                    transfers,
                    count,
                    adeps,
                    saw,
                    False,
                )
                result = adeps[0] if saw[0] else frozenset()
            else:
                result = _scalar_of(
                    self._eval(
                        body_node, params, inner, transfers, count
                    )
                )
        finally:
            self.frames = saved_frames
            self.thrown = saved_thrown
            self.block_stack = saved_block
            self.var_names = saved_var
            self.function_locals = saved_flocals
        # Writes inside the body are may-writes on the caller's
        # scope — member stores rebase shared `_Composite`
        # instances on `inner`, so join them back.
        shadowed = set(cval.params)
        for name, ival in inner.items():
            if name in shadowed or name not in locals_:
                continue
            if not _val_leq(ival, locals_[name]):
                locals_[name] = _merge_vals(locals_[name], ival)
        return result

    def _eval(self, node, params, locals_, transfers, count):
        """Evaluate a node to its raw value: a scalar dependency set
        or a `_Composite` for object shapes."""
        count[0] += 1
        if count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        if kind == "identifier":
            return self._lookup(
                node.text.decode(), params, locals_, _span(node)
            )
        if kind == "object":
            # `{a: x, b: {c: y}, short}` — a composite tracking deps
            # per field. `{...o}` copies the source composite's
            # fields (later members override); a scalar spread or a
            # computed `{[k]: v}` key adds unknown fields the model
            # can't name, so the whole literal collapses to a scalar
            # union. Method/getter/setter members close.
            fields: dict = {}
            spilled = frozenset()
            for child in _children(node):
                if child.type == "pair":
                    key = child.child_by_field_name("key")
                    fval = child.child_by_field_name("value")
                    if key is None or fval is None:
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    fdeps = self._eval(
                        fval, params, locals_, transfers, count
                    )
                    if isinstance(fdeps, _Composite) and (
                        fval.type != "object"
                    ):
                        # `{a: o2}` aliases `o2` at field level —
                        # writes would diverge, so collapse.
                        fdeps = _scalar_of(fdeps)
                    if key.type == "computed_property_name":
                        # `{[k]: v}` — the key isn't nameable; the
                        # field it adds can't be tracked, so the
                        # literal collapses.
                        spilled |= _scalar_of(fdeps)
                        for inner in _children(key):
                            spilled |= self.expression(
                                inner, params, locals_, transfers,
                                count,
                            )
                        continue
                    if key.type not in {
                        "property_identifier",
                        "string",
                        "number",
                    }:
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    fields[
                        key.text.decode().strip("\"'")
                        if key.type == "string"
                        else key.text.decode()
                    ] = fdeps
                elif child.type == "shorthand_property_identifier":
                    # `{o}` — a whole-name alias collapses like a
                    # non-literal field value.
                    fields[child.text.decode()] = _scalar_of(
                        self._lookup(
                            child.text.decode(),
                            params,
                            locals_,
                            _span(child),
                        )
                    )
                elif child.type == "spread_element":
                    src = self._eval(
                        next(iter(_children(child))),
                        params,
                        locals_,
                        transfers,
                        count,
                    )
                    if isinstance(src, _Composite):
                        fields.update(src.fields)
                    else:
                        # `{...scalar}` adds unknowable fields.
                        spilled |= src
                elif child.type == "method_definition":
                    # `{m(v) { ... }}` — a callable field value;
                    # `o.m(x)` invokes like a slice-13 member call.
                    # `get`/`set` (read/write effects), `*`
                    # (generator) and `static` markers stay closed;
                    # `async` admits like an async arrow. `this`
                    # inside closes at invoke.
                    markers = {
                        c.type
                        for c in child.children
                        if not c.is_named
                    }
                    if markers & {"get", "set", "*", "static"}:
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    mname = child.child_by_field_name("name")
                    if mname is None or mname.type != "property_identifier":
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    fields[mname.text.decode()] = self._callable_value(
                        child, params, locals_
                    )
                else:
                    raise _Unsupported(
                        "unsupported_expression", _span(child)
                    )
            if spilled:
                return spilled | _scalar_of(_Composite(fields))
            return _Composite(fields)
        if kind == "array":
            # `[e0, e1]` — a composite with positional keys; `a[0]`
            # reads field "0", a dynamic `a[i]` unions the elements,
            # and `a.length` reads a missing field (dep-free).
            # `[...a]` appends the source's positional fields in
            # numeric order; a scalar spread or a composite holding
            # non-positional fields can't enumerate, so the literal
            # collapses to a scalar union.
            afields: dict = {}
            spilled = frozenset()
            i = 0
            for child in _children(node):
                if child.type == "spread_element":
                    inner = next(iter(_children(child)), None)
                    if inner is None:
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    src = self._eval(
                        inner, params, locals_, transfers, count
                    )
                    if isinstance(src, _Composite) and all(
                        k.isdigit() for k in src.fields
                    ):
                        for k in sorted(src.fields, key=int):
                            afields[str(i)] = src.fields[k]
                            i += 1
                    else:
                        spilled |= _scalar_of(src)
                    continue
                fdeps = self._eval(
                    child, params, locals_, transfers, count
                )
                if isinstance(fdeps, _Composite) and child.type not in {
                    "object",
                    "array",
                }:
                    # `[o]` aliases `o` at field level — collapse.
                    fdeps = _scalar_of(fdeps)
                afields[str(i)] = fdeps
                i += 1
            if spilled:
                return spilled | _scalar_of(_Composite(afields))
            return _Composite(afields)
        if kind in {"member_expression", "subscript_expression"}:
            return self._member_read(
                node, params, locals_, transfers, count
            )
        if kind in {
            "number",
            "true",
            "false",
            "string",
            "undefined",
            "null",
        }:
            return frozenset()
        if kind == "template_string":
            # Interpolations evaluate for deps/calls — the string
            # result carries the union of their deps.
            result = frozenset()
            for child in _children(node):
                # `string_fragment` is literal text; only the
                # substitutions evaluate.
                if child.type == "template_substitution":
                    for inner in _children(child):
                        result |= self.expression(
                            inner, params, locals_, transfers, count
                        )
            return result
        if kind == "parenthesized_expression":
            exprs = _children(node)
            if len(exprs) != 1:
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(exprs[0], params, locals_, transfers, count)
        if kind == "await_expression":
            # `await` yields the operand's value — for the dep model
            # that's a pass-through. `for await (...)` iterates the
            # same way the plain `of` loop does.
            operand = next(
                (c for c in node.children if c.is_named), None
            )
            if operand is None:
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(operand, params, locals_, transfers, count)
        if kind == "unary_expression":
            op = node.child_by_field_name("operator")
            argument = node.child_by_field_name("argument")
            if op is None or argument is None or (
                op.type not in _UNARY_OPS
                and op.type not in {"void", "typeof", "delete"}
            ):
                raise _Unsupported("unsupported_expression", _span(node))
            if op.type == "delete":
                # `delete o.f` removes the field copy-on-write; a
                # dynamic key may hit any field, so it keeps them all
                # (the surviving deps over-approximate); `delete x`
                # on a name is a runtime no-op. Yields a boolean —
                # no deps.
                if argument.type in {
                    "member_expression",
                    "subscript_expression",
                }:
                    self._member_delete(
                        argument, params, locals_, transfers, count
                    )
                elif argument.type == "identifier":
                    self._read_name(
                        argument, params, locals_, _span(argument)
                    )
                else:
                    self.expression(
                        argument, params, locals_, transfers, count
                    )
                return frozenset()
            deps_a = self.expression(
                argument, params, locals_, transfers, count
            )
            # `void` discards to `undefined`; `typeof`'s string has no
            # dependency shape, so the operand's deps are the
            # over-approximation.
            return frozenset() if op.type == "void" else deps_a
        if kind in {
            "as_expression",
            "satisfies_expression",
            "non_null_expression",
        }:
            # Type assertions and `!` don't change the value — the
            # operand's deps pass through.
            operand = next(iter(_children(node)), None)
            if operand is None:
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(
                operand, params, locals_, transfers, count
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
        if kind in {"arrow_function", "function_expression"}:
            return self._callable_value(node, params, locals_)
        if kind == "call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            if function is None or arguments is None:
                raise _Unsupported("unsupported_expression", _span(node))
            if function.type in {
                "member_expression",
                "subscript_expression",
            }:
                # `o.f(x)` — the field may hold a `_Callable`
                # (`{f: v => v}`). There is no `this` binding —
                # a body reading `this` closes inside.
                actual_m = tuple(
                    self.expression(
                        arg, params, locals_, transfers, count
                    )
                    for arg in _children(arguments)
                )
                raw = self._member_read(
                    function, params, locals_, transfers, count
                )
                if not isinstance(raw, _Callable):
                    raise _Unsupported(
                        "unsupported_expression", _span(node)
                    )
                result = self._invoke_callable(
                    raw,
                    actual_m,
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                )
                transfers.append(
                    TsCall(
                        _span(node),
                        function.text.decode(),
                        actual_m,
                        result,
                    )
                )
                return result
            if function.type != "identifier":
                raise _Unsupported("unsupported_expression", _span(node))
            callee = function.text.decode()
            bound = (
                callee in locals_
                or callee in self.function_locals
                or callee in params
            )
            if not bound and callee not in self.functions:
                raise _Unsupported(
                    "call_unresolved", _span(node), callee
                )
            actual = tuple(
                self.expression(
                    arg, params, locals_, transfers, count
                )
                for arg in _children(arguments)
            )
            if bound:
                # A local binding shadows a same-named function
                # declaration — JS resolution order.
                raw = self._lookup(
                    callee, params, locals_, _span(function)
                )
                if not isinstance(raw, _Callable):
                    raise _Unsupported(
                        "unsupported_expression", _span(node)
                    )
                result = self._invoke_callable(
                    raw,
                    actual,
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                )
                transfers.append(
                    TsCall(_span(node), callee, actual, result)
                )
                return result
            result = frozenset().union(*actual) if actual else frozenset()
            transfers.append(
                TsCall(_span(node), callee, actual, result)
            )
            return result
        if kind == "update_expression":
            # `x++` / `o.f++` inside an expression (`return x++`) —
            # a dep-preserving read of the bound name; the store is
            # statement-level only.
            argument = node.child_by_field_name("argument")
            if argument is None or argument.type not in {
                "identifier",
                "member_expression",
                "subscript_expression",
            }:
                raise _Unsupported("unsupported_expression", _span(node))
            return _scalar_of(
                self._eval(argument, params, locals_, transfers, count)
            )
        if kind in {
            "assignment_expression",
            "augmented_assignment_expression",
        }:
            # An assignment inside an expression writes like the
            # statement form and yields the assigned dependencies.
            # Stores inside an expression are always may-writes.
            try:
                self._assignment(
                    node, params, locals_, transfers, count, True,
                    augmented=kind == "augmented_assignment_expression",
                )
            except _Unsupported as u:
                raise _Unsupported(
                    "unsupported_expression"
                    if u.reason == "unsupported_statement"
                    else u.reason,
                    u.span,
                ) from u
            left = node.child_by_field_name("left")
            return _scalar_of(
                self._eval(left, params, locals_, transfers, count)
            )
        if kind == "sequence_expression":
            # The comma operator: each operand evaluates for its
            # writes/calls; the whole value is the union of the deps.
            result = frozenset()
            for child in _children(node):
                result |= self.expression(
                    child, params, locals_, transfers, count
                )
            return result
        if kind == "ternary_expression":
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            alternative = node.child_by_field_name("alternative")
            if (
                condition is None
                or consequence is None
                or alternative is None
            ):
                raise _Unsupported("unsupported_expression", _span(node))
            return (
                self.expression(condition, params, locals_, transfers, count)
                | self.expression(consequence, params, locals_, transfers, count)
                | self.expression(alternative, params, locals_, transfers, count)
            )
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
