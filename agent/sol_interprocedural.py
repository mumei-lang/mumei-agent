"""Solidity scalar interprocedural summaries.

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
  the caller when its result is used (a discarded result is
  an opaque recorded call); state-variable reads and writes
  (`state_writes` effects propagate through calls), member
  calls (`this.f`, `obj.f`, `using`-library dispatch),
  inheritance hierarchies, constructors/`new C(...)`,
  loops (`for`/`while`/`do`), `try`/`catch`, modifiers with
  scalar params, index access on storage containers
  (`arr[i]`/`m[k]`), `push`/`pop`/`length`, `delete`,
  `emit`, struct literals and `f{value: x}(...)` call
  options, named-return slots and multi-return tuples
  (position-insensitive — every slot reads the union), free
  functions and overloads are modelled. `assembly`,
  `function` pointers, `var` decls and multi-file imports
  stay closed — a gap records why.

This is a conservative dependency analysis, not value
evaluation, correctness or proof. `effects` is
`none_in_supported_fragment`, `state_writes` (storage
mutation, propagated through calls) or `unknown` (opaque
calls, `emit`, `selfdestruct`, unresolved modifiers).
`SolSummarySet.context_key` binds the source hash and
profile so reuse requires identical input.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

PROFILE = "mumei.sol-scalar-parameter-deps/v1"

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
class SolGap:
    reason: str
    byte: int

    def to_dict(self) -> dict:
        return {"reason": self.reason, "byte": self.byte}

    @classmethod
    def from_dict(cls, value) -> "SolGap":
        v = _manifest_record(value, ("reason", "byte"))
        _require_manifest(type(v["byte"]) is int and v["byte"] >= 0)
        return cls(_string(v["reason"]), v["byte"])


@dataclass(frozen=True)
class SolCall:
    byte: int
    callee: str
    actual_dependencies: tuple[frozenset[int], ...]
    result_dependencies: frozenset[int] | None

    def to_dict(self) -> dict:
        return {
            "byte": self.byte,
            "callee": self.callee,
            "arguments": [sorted(a) for a in self.actual_dependencies],
            "result": (
                None
                if self.result_dependencies is None
                else sorted(self.result_dependencies)
            ),
        }

    @classmethod
    def from_dict(cls, value) -> "SolCall":
        v = _manifest_record(
            value, ("byte", "callee", "arguments", "result")
        )
        _require_manifest(type(v["byte"]) is int and v["byte"] >= 0)
        arguments = _list(v["arguments"])
        _require_manifest(len(arguments) <= MAX_MANIFEST_MEMBERS)
        result = v["result"]
        callee = v["callee"]
        # An indirect call whose result is discarded emits
        # `callee: null` — the callee target has no name.
        _require_manifest(callee is None or type(callee) is str)
        return cls(
            v["byte"],
            callee,
            tuple(_deps_from_list(a) for a in arguments),
            None if result is None else _deps_from_list(result),
        )


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

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "contract": self.contract,
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
    def from_dict(cls, value) -> "SolFunctionSummary":
        v = _manifest_record(
            value,
            (
                "name",
                "contract",
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
        restored_gaps = [SolGap.from_dict(g) for g in gaps]
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
            _string(v["contract"]),
            tuple(_string(p) for p in parameters),
            available,
            restored_deps,
            [SolCall.from_dict(c) for c in calls],
            restored_gaps,
            _string(v["effects"]),
        )


@dataclass
class SolSummarySet:
    context_key: str
    functions: list[SolFunctionSummary]
    profile: str = PROFILE

    def to_dict(self) -> dict:
        return {
            "schema_version": self.profile,
            "context_key": self.context_key,
            "functions": [f.to_dict() for f in self.functions],
        }

    @classmethod
    def from_dict(cls, value) -> "SolSummarySet":
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
        restored = [
            SolFunctionSummary.from_dict(f) for f in functions
        ]
        names = [f.name for f in restored]
        # A declared duplicate name would let a forged record adopt a
        # same-named honest record's reuse — names are unique in every
        # honest derivation, so a duplicate is malformed.
        _require_manifest(len(set(names)) == len(names))
        return cls(
            _string(v["context_key"]),
            restored,
        )


def _children(node):
    return [
        c
        for c in node.children
        if c.is_named and c.type != "comment"
    ]


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
    """Every parameter of the `returns (...)` clause is scalar
    (zero or more — multi-return tuples are union-modelled, and
    a function without `returns` simply has no results)."""
    ret = fn.child_by_field_name("return_type") or next(
        (
            c
            for c in _children(fn)
            if c.type == "return_type_definition"
        ),
        None,
    )
    if ret is None:
        return True
    params = [c for c in _children(ret) if c.type == "parameter"]
    if not params:
        return False
    return all(
        _scalar_type(p.child_by_field_name("type"))
        for p in params
    )


class _Builder:
    def __init__(self, source: bytes):
        self.source = source
        self.count = [0]
        self.functions: dict[str, object] = {}
        self.contracts: dict[str, str] = {}
        self.summaries: dict[str, SolFunctionSummary] = {}
        self._inline_depth = 0
        self._placeholder: list = []
        # `uint[1] storage xs = arr` — local name bound to a state
        # variable's slot: reads and writes resolve through it.
        self._storage_alias: dict = {}
        self._effects_touched = False
        self._writes: list[set[str]] = []
        self._decls: list[set[str]] = []
        self._state_vars: dict[str, set[str]] = {}
        self._overload_groups: dict[str, list[str]] = {}
        self.modifiers: dict[str, object] = {}
        self._parents: dict[str, list[str]] = {}
        self._contract_names: set[str] = set()
        self._usings: dict[str, list[str]] = {}
        self._free_fns: dict[str, list[str]] = {}
        self._struct_names: set[str] = set()
        self._all_state_vars: dict[str, set[str]] = {}

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
            if top.type in {
                "contract_declaration",
                "interface_declaration",
                "library_declaration",
            }:
                self._register_contract(top)
            elif top.type == "struct_declaration":
                sname = top.child_by_field_name("name") or next(
                    (
                        c
                        for c in _children(top)
                        if c.type == "identifier"
                    ),
                    None,
                )
                if sname is not None:
                    self._struct_names.add(sname.text.decode())
            elif top.type == "function_definition":
                fname = top.child_by_field_name("name") or next(
                    (
                        c
                        for c in _children(top)
                        if c.type == "identifier"
                    ),
                    None,
                )
                if fname is None:
                    continue
                base = fname.text.decode()
                # Overloaded free functions register under
                # unique keys (`f`, `f#2`, ...) grouped by the
                # bare name — matching contract overloads.
                n = len(self._free_fns.get(base, []))
                ukey = base if n == 0 else f"{base}#{n + 1}"
                self._free_fns.setdefault(
                    base, []
                ).append(ukey)
                self.functions[ukey] = top
                self.contracts[ukey] = ""

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

    def _hierarchy(self, contract):
        # Linearized-ish: contract first, then ancestors in
        # declaration order, depth-first with dedup.
        order: list[str] = []
        seen: set[str] = set()

        def visit(c):
            if c in seen:
                return
            seen.add(c)
            order.append(c)
            for p in self._parents.get(c, ()):
                visit(p)

        visit(contract)
        return order

    def _state_vars_of(self, contract):
        out: set[str] = set()
        for c in self._hierarchy(contract):
            out |= self._state_vars.get(c, set())
        return out

    def _all_state_vars_of(self, contract):
        out: set[str] = set()
        for c in self._hierarchy(contract):
            out |= self._all_state_vars.get(c, set())
        return out

    def _storage_targets(self, name):
        """Candidate slots a local name may resolve to — every
        `_storage_alias` value is a frozenset because a name that
        retargets only on some paths keeps all candidates."""
        tgt = self._storage_alias.get(name)
        return tuple(tgt) if tgt is not None else (name,)

    def _merge_alias_paths(self, *paths):
        """Union-merge storage-pointer maps from paths that may or
        may not have run: a divergent name keeps every candidate
        target (over-report is the safe direction for effects)."""
        for path in paths:
            for name, tgts in path.items():
                self._storage_alias[name] = self._storage_alias.get(
                    name, frozenset()
                ) | tgts

    def _merge_alias_scope(self, inner_alias, decls):
        """Merge an inner scope's pointer map back: names declared
        inside stay scoped; surviving names keep every candidate."""
        for name, tgts in inner_alias.items():
            if name in decls:
                continue
            self._storage_alias[name] = self._storage_alias.get(
                name, frozenset()
            ) | tgts

    def _lookup_fns(self, contract, name, skip_self=False):
        for c in self._hierarchy(contract):
            if skip_self and c == contract:
                continue
            key = f"{c}.{name}"
            if key in self._overload_groups:
                return self._overload_groups[key]
        return []

    def _register_contract(self, node) -> None:
        name_node = node.child_by_field_name("name") or next(
            (c for c in _children(node) if c.type == "identifier"),
            None,
        )
        contract = (
            name_node.text.decode() if name_node is not None else "?"
        )
        self._contract_names.add(contract)
        body = next(
            (c for c in _children(node) if c.type == "contract_body"),
            None,
        )
        if body is None:
            return
        for c in _children(body):
            if c.type == "struct_declaration":
                sname = c.child_by_field_name("name") or next(
                    (
                        cc
                        for cc in _children(c)
                        if cc.type == "identifier"
                    ),
                    None,
                )
                if sname is not None:
                    self._struct_names.add(sname.text.decode())
        for c in _children(node):
            if c.type == "inheritance_specifier":
                anc = c.child_by_field_name("ancestor")
                aname = next(
                    (
                        d
                        for d in _children(anc or c)
                        if d.type == "identifier"
                    ),
                    None,
                )
                if aname is not None:
                    self._parents.setdefault(
                        contract, []
                    ).append(aname.text.decode())
        for member in _children(body):
            if member.type == "using_directive":
                alias = next(
                    (
                        c
                        for c in _children(member)
                        if c.type == "type_alias"
                    ),
                    None,
                )
                lname = next(
                    (
                        c
                        for c in _children(alias or member)
                        if c.type == "identifier"
                    ),
                    None,
                )
                if lname is not None:
                    self._usings.setdefault(
                        contract, []
                    ).append(lname.text.decode())
                continue
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
                if vname is not None:
                    self._all_state_vars.setdefault(
                        contract, set()
                    ).add(vname.text.decode())
                    if _scalar_type(tnode):
                        self._state_vars.setdefault(
                            contract, set()
                        ).add(vname.text.decode())
                continue
            if member.type in {
                "constructor_definition",
                "fallback_receive_definition",
            }:
                kw = (
                    member.children[0].text.decode()
                    if member.children
                    else "?"
                )
                ukey = f"{contract}.{kw}"
                self.functions[ukey] = member
                self.contracts[ukey] = contract
                continue
            if member.type == "modifier_definition":
                mname = member.child_by_field_name("name") or next(
                    (
                        c
                        for c in _children(member)
                        if c.type == "identifier"
                    ),
                    None,
                )
                if mname is not None:
                    self.modifiers[
                        f"{contract}.{mname.text.decode()}"
                    ] = member
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
            group = self._overload_groups.setdefault(key, [])
            ukey = key if not group else f"{key}#{len(group)+1}"
            group.append(ukey)
            self.functions[ukey] = member
            self.contracts[ukey] = contract

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
        ret_names: list[str] = []
        if ret is not None:
            for rparam in _children(ret):
                if rparam.type != "parameter":
                    continue
                rn = rparam.child_by_field_name("name")
                if rn is not None:
                    ret_names.append(rn.text.decode())
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
        self._effects_touched = False
        locals_: dict[str, frozenset[int]] = {
            n: frozenset({i}) for n, i in param_index.items()
        }
        # Scalar state variables read as dep-free external
        # values; writes still flow through the slot and set
        # `effects`.
        for sv in self._state_vars_of(self.contracts[key]):
            locals_.setdefault(sv, frozenset())
        for ret_name in ret_names:
            if ret_name not in locals_:
                # Named result (`returns (uint256 r)`) — a writable
                # local slot a bare `return` reads back.
                locals_[ret_name] = frozenset()
        self._ret_names = ret_names
        mods = [
            c
            for c in _children(fn_node)
            if c.type == "modifier_invocation"
        ]
        self._writes.append(set())
        # `_decls` is per-function: an inlined callee's shadow
        # checks consult only its own frames — the caller's
        # locals never shadow this function's state writes.
        prev_decls = self._decls
        prev_alias = self._storage_alias
        self._decls = [set()]
        self._storage_alias = {}
        try:
            try:
                rets = self._run_body(
                    body, locals_, param_index, summary, mods
                )
            except _Unsupported as exc:
                summary.gaps.append(SolGap(exc.reason, exc.byte))
                return summary
        finally:
            self._writes.pop()
            self._decls = prev_decls
            self._storage_alias = prev_alias
        if rets is None and ret is None:
            # No `returns` clause — the function produces no
            # results; a missing `return` is fine.
            rets = frozenset()
        if rets is None:
            if not summary.gaps:
                summary.gaps.append(
                    SolGap("missing_return", _span(fn_node))
                )
            return summary
        summary.return_dependencies = rets
        summary.available = True
        if (
            summary.effects == "unknown"
            and not self._effects_touched
        ):
            summary.effects = "none_in_supported_fragment"
        return summary

    # -- statements ---------------------------------------------------

    def _run_body(
        self, body, locals_, param_index, summary, mods
    ) -> frozenset[int] | None:
        # Run the function body through its modifier chain. Each
        # invocation binds the modifier's scalar params and walks
        # its body in a fresh scope (modifier params + state vars
        # only — modifiers can't see function locals); a pushed
        # continuation lets `_;` run the rest of the chain and then
        # the function body. Unresolvable or non-scalar modifiers
        # degrade to an opaque void call and the chain continues
        # (the wrapped body may still run).
        if not mods:
            return self._block(body, locals_, param_index, summary)
        inv, rest = mods[0], mods[1:]
        iname = next(
            (c for c in _children(inv) if c.type == "identifier"),
            None,
        )
        actual = []
        for a in (
            c for c in _children(inv) if c.type == "call_argument"
        ):
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
        mnode = None
        if iname is not None:
            for c in self._hierarchy(self._current_contract):
                mnode = self.modifiers.get(
                    f"{c}.{iname.text.decode()}"
                )
                if mnode is not None:
                    break
        mparams = (
            [p for p in _children(mnode) if p.type == "parameter"]
            if mnode is not None
            else []
        )
        if (
            mnode is None
            or len(mparams) != len(actual)
            or any(_scalar_param(p) is None for p in mparams)
            or self._inline_depth >= MAX_INLINE_DEPTH
        ):
            summary.calls.append(
                SolCall(
                    _span(inv),
                    iname.text.decode()
                    if iname is not None
                    else None,
                    tuple(actual),
                    None,
                )
            )
            if summary.effects != "state_writes":
                summary.effects = "unknown"
                self._effects_touched = True
            return self._run_body(
                body, locals_, param_index, summary, rest
            )
        self._inline_depth += 1
        try:
            mlocals: dict[str, frozenset[int]] = {
                sv: frozenset()
                for sv in self._state_vars_of(
                    self._current_contract
                )
            }
            for i, p in enumerate(mparams):
                mlocals[_scalar_param(p)[0]] = actual[i]
            mbody = mnode.child_by_field_name("body") or next(
                (
                    c
                    for c in _children(mnode)
                    if c.type == "function_body"
                ),
                None,
            )
            mparam_index = {
                _scalar_param(p)[0]: i
                for i, p in enumerate(mparams)
            }

            # Frames pushed while the modifier runs are its own
            # locals — they must not count as body shadowing at `_;`.
            decl_mark = len(self._decls)

            def _wrapped():
                # `_;` — the wrapped body inherits the state
                # slots the modifier wrote (function params are
                # invisible to a modifier, so only state vars
                # sync back). A name shadowed by a parameter or
                # local declaration refers to the inner
                # binding, not the state variable.
                for sv in self._state_vars_of(
                    self._current_contract
                ):
                    shadowed = (
                        sv in param_index
                        or any(
                            sv in frame
                            for frame in self._decls[:decl_mark]
                        )
                    )
                    if not shadowed and sv in mlocals:
                        locals_[sv] = mlocals[sv]
                return self._run_body(
                    body, locals_, param_index, summary, rest
                )

            self._placeholder.append(_wrapped)
            try:
                return self._block(
                    mbody, mlocals, mparam_index, summary
                )
            finally:
                self._placeholder.pop()
        finally:
            self._inline_depth -= 1

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
                bare = frozenset()
                for rn in getattr(self, "_ret_names", ()):
                    bare |= locals_.get(rn, frozenset())
                return bare
            tinner = _children(expr)
            if (
                len(tinner) == 1
                and tinner[0].type == "tuple_expression"
            ):
                # `return (a, b)` — the multi-return tuple is
                # union-modelled as a single dep set.
                deps = frozenset()
                for el in _children(tinner[0]):
                    if el.type == "expression":
                        deps |= self._expr(
                            el, locals_, param_index, summary
                        )
                return deps
            return self._expr(expr, locals_, param_index, summary)
        if t == "variable_declaration_statement":
            tdecl = next(
                (
                    c
                    for c in _children(st)
                    if c.type == "variable_declaration_tuple"
                ),
                None,
            )
            expr = st.child_by_field_name("value")
            if tdecl is not None:
                decls = [
                    c
                    for c in _children(tdecl)
                    if c.type == "variable_declaration"
                ]
                names = []
                for d in decls:
                    name = d.child_by_field_name("name")
                    tnode = d.child_by_field_name("type")
                    if name is None or (
                        tnode is not None
                        and not _scalar_type(tnode)
                    ):
                        raise _Unsupported(
                            "unsupported_statement", _span(st)
                        )
                    names.append(name.text.decode())
                deps = (
                    self._expr(
                        expr, locals_, param_index, summary
                    )
                    if expr is not None
                    else frozenset()
                )
                for n in names:
                    # Tuple destructuring is position-insensitive:
                    # each declared slot reads the whole union.
                    locals_[n] = deps
                    if self._writes:
                        self._writes[-1].add(n)
                    if self._decls:
                        self._decls[-1].add(n)
                return None
            decl = next(
                (
                    c
                    for c in _children(st)
                    if c.type == "variable_declaration"
                ),
                None,
            )
            if decl is None:
                raise _Unsupported(
                    "unsupported_statement", _span(st)
                )
            name = decl.child_by_field_name("name")
            # Non-scalar local decls (`D d = new D(a)`, `uint[]
            # memory x`) bind the name to the RHS deps like a
            # scalar slot — an approximation, but the effects and
            # call records still flow.
            if name is None:
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
            # `uint[1] storage xs = arr` — a storage reference bound
            # to a state variable. Reads/writes on `xs` resolve to
            # `arr`'s slot, so `xs[i] = v` marks the state write.
            # A fresh declaration shadows any earlier binding —
            # drop a stale alias for the name first.
            self._storage_alias.pop(name.text.decode(), None)
            # Aliases are frozensets of candidate targets.
            if (
                expr is not None
                and any(
                    not c.is_named and c.text == b"storage"
                    for c in decl.children
                )
            ):
                ein = (
                    _children(expr)[0]
                    if expr.type == "expression"
                    and len(_children(expr)) == 1
                    else expr
                )
                if (
                    ein is not None
                    and ein.type == "identifier"
                    and ein.text.decode()
                    in self._all_state_vars_of(
                        getattr(self, "_current_contract", "")
                    )
                ):
                    self._storage_alias[
                        name.text.decode()
                    ] = frozenset({ein.text.decode()})
            return None
        if t == "expression_statement":
            expr = next(
                (c for c in _children(st) if c.type == "expression"),
                None,
            )
            if expr is None:
                return None
            inner = _children(expr)
            if (
                len(inner) == 1
                and inner[0].type == "identifier"
                and inner[0].text == b"_"
            ):
                # `_;` inside a modifier runs the wrapped body.
                if self._placeholder:
                    return self._placeholder[-1]()
                return None
            self._assign_or_call(
                expr, locals_, param_index, summary
            )
            return None
        if t == "try_statement":
            attempt = st.child_by_field_name("attempt")
            body = st.child_by_field_name("body")
            catches = [
                c for c in _children(st) if c.type == "catch_clause"
            ]
            rparams = [
                c for c in _children(st) if c.type == "parameter"
            ]
            rdeps = (
                self._expr(attempt, locals_, param_index, summary)
                if attempt is not None
                else frozenset()
            )
            variants = []
            # Success path: `returns (...)` params bind the
            # attempt's union (position-insensitive).
            ok = dict(locals_)
            for rp in rparams:
                rn = rp.child_by_field_name("name")
                if rn is not None:
                    ok[rn.text.decode()] = rdeps
            variants.append(ok)
            # Failure paths: catch params are dep-free error data.
            for cc in catches:
                ci = dict(locals_)
                for cp in _children(cc):
                    if cp.type == "parameter":
                        cn = cp.child_by_field_name("name")
                        if cn is not None:
                            ci[cn.text.decode()] = frozenset()
                variants.append((ci, cc))
            ret = None
            results = []
            first = variants[0]
            base_alias = self._storage_alias
            self._storage_alias = dict(base_alias)
            results.append(
                self._block(body, first, param_index, summary)
                if body is not None
                else None
            )
            aliases = [self._storage_alias]
            for ci, cc in variants[1:]:
                self._storage_alias = dict(base_alias)
                cbody = cc.child_by_field_name("body")
                results.append(
                    self._block(cbody, ci, param_index, summary)
                    if cbody is not None
                    else None
                )
                aliases.append(self._storage_alias)
            self._storage_alias = base_alias
            self._merge_alias_paths(*aliases)
            scopes = [first] + [v[0] for v in variants[1:]]
            for name in set().union(*scopes):
                merged = frozenset()
                for sc in scopes:
                    merged |= sc.get(name, frozenset())
                locals_[name] = merged
            for r in results:
                if r is not None:
                    ret = r if ret is None else ret | r
            return ret
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
            base_alias = self._storage_alias
            self._storage_alias = dict(base_alias)
            left_ret = None
            right_ret = None
            if branches:
                left_ret = self._block(
                    branches[0], left_locals, param_index, summary
                )
            left_alias = self._storage_alias
            self._storage_alias = dict(base_alias)
            if len(branches) > 1:
                right_ret = self._block(
                    branches[1], right_locals, param_index, summary
                )
            right_alias = self._storage_alias
            self._storage_alias = base_alias
            # A retarget on one arm only is conditional — keep
            # every candidate the two arms can leave.
            self._merge_alias_paths(left_alias, right_alias)
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
            init = st.child_by_field_name("initial")
            if init is not None and init.type == ";":
                init = None
            cond_node = st.child_by_field_name("condition")
            update = st.child_by_field_name("update")
            body = st.child_by_field_name("body")
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
        if t in {"break_statement", "continue_statement"}:
            # May-analysis: a break/continue may not be taken,
            # so following statements stay reachable — no-op.
            return None
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
            # An event emission is an observable side effect —
            # beyond storage writes, keep it as unknown.
            if summary.effects != "state_writes":
                summary.effects = "unknown"
                self._effects_touched = True
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
            outer_alias = self._storage_alias
            self._storage_alias = dict(outer_alias)
            self._decls.append(set())
            try:
                ret = self._block(
                    st, inner, param_index, summary
                )
            finally:
                decls = self._decls.pop()
            inner_alias = self._storage_alias
            self._storage_alias = outer_alias
            # A state slot first written inside the block
            # propagates back too; only block-local decls stay
            # scoped.
            svars = self._all_state_vars_of(
                self._current_contract
            )
            for name in list(inner):
                if (
                    name not in decls
                    and (name in locals_ or name in svars)
                ):
                    locals_[name] = inner[name]
            self._merge_alias_scope(inner_alias, decls)
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
        outer_alias = self._storage_alias
        self._storage_alias = dict(outer_alias)
        self._writes.append(set())
        self._decls.append(set())
        merged = frozenset()
        try:
            if init is not None:
                self._statement(
                    init, inner, param_index, summary
                )
            ret = None
            if body is not None:
                # The body's own decls frame keeps `uint s`
                # inside `{...}` from shadowing a state `s`
                # for the still-live loop frame — cond and
                # update see only the init decls.
                self._decls.append(set())
                try:
                    ret = self._block(
                        body, inner, param_index, summary
                    )
                finally:
                    self._decls.pop()
            if update is not None:
                self._assign_or_call(
                    update, inner, param_index, summary
                )
            if cond is not None:
                # Loop-init names (`i`) live in `inner`, not
                # the outer scope; the decls frame is still
                # live so init-declared writes shadow state.
                merged |= self._expr(
                    cond, inner, param_index, summary
                )
        finally:
            touched = self._writes.pop()
            # Loop-init decls (`for (uint i = 0; ...)`)
            # stay scoped to the loop.
            loop_decls = self._decls.pop()
        inner_alias = self._storage_alias
        self._storage_alias = outer_alias
        # A state slot first written inside the loop joins
        # the merge too — `name not in locals_` is not a
        # reason to drop it.
        svars = self._all_state_vars_of(self._current_contract)
        for name in set(inner) | set(locals_):
            if name not in locals_ and name not in svars:
                continue
            prior = locals_.get(name, frozenset())
            deps = inner.get(name, frozenset())
            if deps != prior or name in touched:
                locals_[name] = prior | deps | merged
                # An inner loop's may-write is the parent's
                # may-write too — record it in the frame an
                # enclosing loop reads at merge-back.
                if self._writes:
                    self._writes[-1].add(name)
        # The body may not have run — every candidate either
        # side could leave stays on the merged pointer map.
        self._merge_alias_scope(inner_alias, loop_decls)
        if ret is not None:
            # `while (n > 0) { return x; }` — whether the body
            # ran at all depends on the condition.
            ret = ret | merged
        return ret

    def _assign_or_call(
        self, expr, locals_, param_index, summary
    ) -> frozenset[int]:
        """Statement-position expression — `x = e`, `x op= e`,
        `x++`, or a call whose result is discarded."""
        if (
            expr.type == "expression"
            and len(_children(expr)) == 1
        ):
            # `mystery();` wraps the call in an `expression`
            # node — unwrap it so the void-call path applies.
            expr = _children(expr)[0]
        if expr.type in {
            "assignment_expression",
            "augmented_assignment_expression",
        }:
            left = expr.child_by_field_name("left")
            right = expr.child_by_field_name("right")
            tinner = (
                _children(left)
                if left is not None
                and left.type == "expression"
                else []
            )
            if (
                len(tinner) == 1
                and tinner[0].type == "tuple_expression"
            ):
                # `(x, y) = f(...)` — every slot reads the RHS
                # union; member targets behave like `this.s = v`.
                if right is None:
                    raise _Unsupported(
                        "unsupported_statement", _span(expr)
                    )
                deps = self._expr(
                    right, locals_, param_index, summary
                )
                for el in _children(tinner[0]):
                    if el.type != "expression":
                        continue
                    ein = (
                        _children(el)[0]
                        if len(_children(el)) == 1
                        else el
                    )
                    if ein.type == "identifier":
                        name = ein.text.decode()
                        if name not in locals_:
                            raise _Unsupported(
                                "unsupported_statement",
                                _span(el),
                            )
                        locals_[name] = deps
                        if self._writes:
                            self._writes[-1].add(name)
                        shadowed = (
                            name in param_index
                            or any(
                                name in frame
                                for frame in self._decls
                            )
                        )
                        if (
                            not shadowed
                            and name
                            in self._state_vars_of(
                                getattr(
                                    self, "_current_contract", ""
                                )
                            )
                        ):
                            summary.effects = "state_writes"
                            self._effects_touched = True
                        continue
                    idents = (
                        [
                            c
                            for c in _children(ein)
                            if c.type == "identifier"
                        ]
                        if ein.type == "member_expression"
                        else []
                    )
                    if (
                        len(idents) == 2
                        and idents[0].text == b"this"
                        and idents[1].text.decode()
                        in self._state_vars_of(
                            getattr(
                                self, "_current_contract", ""
                            )
                        )
                    ):
                        name = idents[1].text.decode()
                        locals_[name] = deps
                        if self._writes:
                            self._writes[-1].add(name)
                        summary.effects = "state_writes"
                        self._effects_touched = True
                        continue
                    raise _Unsupported(
                        "unsupported_statement", _span(el)
                    )
                return deps
            if (
                len(tinner) == 1
                and tinner[0].type == "array_access"
            ):
                # `arr[i] = v` / `m[k] = v` — the container slot
                # accumulates the value and index deps; storage
                # containers mark `state_writes`.
                if right is None:
                    raise _Unsupported(
                        "unsupported_statement", _span(expr)
                    )
                deps = self._expr(
                    right, locals_, param_index, summary
                )
                node = tinner[0]
                while node.type == "array_access":
                    index = node.child_by_field_name("index")
                    if index is not None:
                        deps |= self._expr(
                            index, locals_, param_index, summary
                        )
                    nb = node.child_by_field_name("base")
                    node = (
                        _children(nb)[0]
                        if nb is not None
                        and nb.type == "expression"
                        and len(_children(nb)) == 1
                        else nb
                    )
                if node is None or node.type != "identifier":
                    raise _Unsupported(
                        "unsupported_statement", _span(expr)
                    )
                for name in self._storage_targets(
                    node.text.decode()
                ):
                    if name in self._all_state_vars_of(
                        getattr(self, "_current_contract", "")
                    ):
                        locals_.setdefault(name, frozenset())
                    if name not in locals_:
                        raise _Unsupported(
                            "unsupported_statement", _span(expr)
                        )
                    locals_[name] = locals_[name] | deps
                    if self._writes:
                        self._writes[-1].add(name)
                    if name in self._all_state_vars_of(
                        getattr(self, "_current_contract", "")
                    ):
                        summary.effects = "state_writes"
                        self._effects_touched = True
                return deps
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
                    in self._state_vars_of(
                        getattr(self, "_current_contract", "")
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
            raw = lident.text.decode()
            lnames = self._storage_targets(raw)
            if (
                expr.type == "assignment_expression"
                and raw in self._storage_alias
            ):
                # `xs = ys` where `ys` is another storage pointer
                # or state variable retargets the reference —
                # nothing is written through the old pointee.
                # A value RHS (`y = a`) is a write-through and
                # keeps the current target.
                ein = (
                    _children(right)[0]
                    if right.type == "expression"
                    and len(_children(right)) == 1
                    else right
                )
                rroot = (
                    ein.text.decode()
                    if ein is not None
                    and ein.type == "identifier"
                    else None
                )
                target = None
                if rroot in self._storage_alias:
                    target = self._storage_alias[rroot]
                elif (
                    rroot is not None
                    and rroot
                    in self._all_state_vars_of(
                        getattr(self, "_current_contract", "")
                    )
                ):
                    target = frozenset({rroot})
                if target is not None:
                    self._storage_alias[raw] = target
                    lnames = (raw,)
            for lname in lnames:
                locals_[lname] = deps
                if self._writes:
                    self._writes[-1].add(lname)
                shadowed = (
                    lname in param_index
                    or any(
                        lname in frame for frame in self._decls
                    )
                )
                if (
                    not shadowed
                    and lname
                    in self._state_vars_of(
                        getattr(self, "_current_contract", "")
                    )
                ):
                    summary.effects = "state_writes"
                    self._effects_touched = True
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
            tname = tident.text.decode()
            shadowed = (
                tname in param_index
                or any(
                    tname in frame for frame in self._decls
                )
            )
            if (
                not shadowed
                and tname
                in self._state_vars_of(
                    getattr(self, "_current_contract", "")
                )
            ):
                summary.effects = "state_writes"
                self._effects_touched = True
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
            out = frozenset()
            for name in self._storage_targets(
                node.text.decode()
            ):
                if name not in locals_:
                    if name in self._all_state_vars_of(
                        getattr(self, "_current_contract", "")
                    ):
                        # A non-scalar state var (`arr`, `m`) is
                        # an opaque container — dep-free
                        # external read, not a binding failure.
                        continue
                    raise _Unsupported(
                        "binding_unavailable", _span(node)
                    )
                out |= locals_[name]
            return out
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
        if t == "unary_expression":
            arg = node.child_by_field_name("argument")
            op = node.child_by_field_name("operator")
            if op is not None and op.text == b"delete":
                # `delete x` clears the slot — a write, not a
                # read. `this.s`/state vars count as state writes.
                dname = None
                if arg is not None:
                    ain = (
                        _children(arg)[0]
                        if arg.type == "expression"
                        and len(_children(arg)) == 1
                        else arg
                    )
                    if ain.type == "identifier":
                        dname = ain.text.decode()
                    elif ain.type == "member_expression":
                        did = [
                            c
                            for c in _children(ain)
                            if c.type == "identifier"
                        ]
                        if len(did) == 2 and did[0].text == b"this":
                            dname = did[1].text.decode()
                if dname is not None and (
                    dname in locals_
                    or dname
                    in self._all_state_vars_of(
                        getattr(self, "_current_contract", "")
                    )
                ):
                    locals_[dname] = frozenset()
                    if self._writes:
                        self._writes[-1].add(dname)
                    if dname in self._all_state_vars_of(
                        getattr(self, "_current_contract", "")
                    ):
                        summary.effects = "state_writes"
                        self._effects_touched = True
                return frozenset()
            deps = frozenset()
            for c in _children(node):
                if c.is_named:
                    deps |= self._expr(
                        c, locals_, param_index, summary
                    )
            return deps
        if t == "update_expression":
            deps = frozenset()
            operand = None
            for c in _children(node):
                deps |= self._expr(
                    c, locals_, param_index, summary
                )
                if c.type in {"expression", "identifier"}:
                    inner = (
                        _children(c)[0]
                        if c.type == "expression"
                        and len(_children(c)) == 1
                        else c
                    )
                    if inner.type == "identifier":
                        operand = inner
            if operand is not None:
                oname = operand.text.decode()
                if oname in locals_:
                    if self._writes:
                        self._writes[-1].add(oname)
                    shadowed = (
                        oname in param_index
                        or any(
                            oname in frame for frame in self._decls
                        )
                    )
                    if (
                        not shadowed
                        and oname
                        in self._state_vars_of(
                            getattr(self, "_current_contract", "")
                        )
                    ):
                        summary.effects = "state_writes"
                        self._effects_touched = True
            return deps
        if t == "array_access":
            # Container read — the container itself is opaque
            # (dep-free external), the index's deps flow. A base
            # that fails to analyze is a gap, not silence.
            base = node.child_by_field_name("base")
            index = node.child_by_field_name("index")
            deps = frozenset()
            if index is not None:
                deps |= self._expr(
                    index, locals_, param_index, summary
                )
            if base is not None:
                # Any failure analysing the base propagates as
                # a real gap — silently dropping it would lose
                # deps and still mark the summary available.
                deps |= self._expr(
                    base, locals_, param_index, summary
                )
            return deps
        if t == "binary_expression":
            named = _children(node)
            # The operator is the anonymous token between the
            # operands — comments are named children and may
            # sit ahead of it, so a positional child is not
            # reliable.
            op = next(
                (
                    c.text.decode()
                    for c in node.children
                    if not c.is_named
                ),
                "",
            )
            if op in {"&&", "||"} and len(named) == 2:
                # Short-circuit: the right side may not run —
                # evaluate it on a copy and union its may-writes
                # back, like a branch arm.
                deps = self._expr(
                    named[0], locals_, param_index, summary
                )
                inner = dict(locals_)
                base_alias = self._storage_alias
                self._storage_alias = dict(base_alias)
                deps |= self._expr(
                    named[1], inner, param_index, summary
                )
                rhs_alias = self._storage_alias
                self._storage_alias = base_alias
                self._merge_alias_paths(rhs_alias)
                for name, deps_ in inner.items():
                    if deps_ != locals_.get(name):
                        locals_[name] = (
                            locals_.get(name, frozenset()) | deps_
                        )
                        if self._writes:
                            self._writes[-1].add(name)
                return deps
            deps = frozenset()
            for c in named:
                deps |= self._expr(
                    c, locals_, param_index, summary
                )
            return deps
        if t == "ternary_expression":
            named = _children(node)
            if len(named) != 3:
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            deps = self._expr(
                named[0], locals_, param_index, summary
            )
            arms = []
            arm_aliases = []
            base_alias = self._storage_alias
            for arm in named[1:]:
                inner = dict(locals_)
                self._storage_alias = dict(base_alias)
                deps |= self._expr(
                    arm, inner, param_index, summary
                )
                arms.append(inner)
                arm_aliases.append(self._storage_alias)
            self._storage_alias = base_alias
            self._merge_alias_paths(*arm_aliases)
            for name in set().union(
                *(set(a) for a in arms)
            ):
                merged = frozenset()
                for a in arms:
                    merged |= a.get(name, frozenset())
                if merged != locals_.get(name):
                    locals_[name] = (
                        locals_.get(name, frozenset()) | merged
                    )
                    if self._writes:
                        self._writes[-1].add(name)
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
                in self._all_state_vars_of(
                    getattr(self, "_current_contract", "")
                )
            ):
                # `this.s` — state var read through `this`
                # (non-scalar containers read dep-free too).
                return locals_.get(
                    idents[1].text.decode(), frozenset()
                )
            # Any other member read (`arr.length`, `s.f`,
            # `m[k].f` ...) is an opaque external read: scalar
            # receivers cannot have members, so the base is a
            # non-scalar whose deps — if any — union with an
            # empty read result.
            obj = node.child_by_field_name("object")
            deps = frozenset()
            if obj is not None:
                # A base that fails to analyse propagates as a
                # gap, the same as an unresolvable call.
                deps = self._expr(
                    obj, locals_, param_index, summary
                )
            return deps
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
        super_call = False
        ext_member = None
        fn_expr = node.child_by_field_name("function")
        if (
            fn_expr is not None
            and fn_expr.type == "expression"
            and len(_children(fn_expr)) == 1
        ):
            fn_expr = _children(fn_expr)[0]
        opt_deps = frozenset()
        if (
            fn_expr is not None
            and fn_expr.type == "struct_expression"
        ):
            # `f{value: x, gas: y}(...)` — call options wrap the
            # callee; option values' deps join the args.
            callee_expr = fn_expr.child_by_field_name("type")
            for sf in _children(fn_expr):
                if sf.type == "struct_field_assignment":
                    v = sf.child_by_field_name("value")
                    if v is not None:
                        opt_deps |= self._expr(
                            v, locals_, param_index, summary
                        )
            if (
                callee_expr is not None
                and callee_expr.type == "expression"
                and len(_children(callee_expr)) == 1
            ):
                callee_expr = _children(callee_expr)[0]
            fn_expr = callee_expr
        if (
            fn_expr is not None
            and fn_expr.type == "member_expression"
        ):
            # `this.f(...)` — same-contract member dispatch.
            obj = fn_expr.child_by_field_name("object")
            prop = fn_expr.child_by_field_name("property")
            if obj is None:
                # Older shape: bare identifier children.
                idents = [
                    c for c in _children(fn_expr)
                    if c.type == "identifier"
                ]
                if len(idents) >= 2:
                    obj, prop = idents[0], idents[-1]
            obase = (
                _children(obj)[0]
                if obj is not None
                and obj.type == "expression"
                and len(_children(obj)) == 1
                else obj
            )
            if (
                obase is not None
                and obase.type == "identifier"
                and obase.text == b"this"
            ):
                fn_expr = prop
            elif (
                obase is not None
                and obase.type == "identifier"
                and obase.text == b"super"
            ):
                fn_expr = prop
                super_call = True
            elif (
                obase is not None
                and obase.type == "identifier"
                and obase.text.decode() == "abi"
            ):
                abi_member = (
                    prop.text.decode() if prop is not None else None
                )
                fn_expr = None
            elif prop is not None:
                # `expr.f(...)` on something that isn't
                # this/super/abi — an external, library or
                # low-level member call; keep the base's deps.
                ext_member = (
                    obj,
                    prop.text.decode(),
                )
                fn_expr = None
            if ext_member is not None and (
                obase is not None
                and obase.type == "identifier"
                and obase.text.decode() in self._contract_names
            ):
                # `L.f(...)` on a declared contract/library —
                # qualified dispatch into that contract.
                qualified = obase.text.decode()
                fn_expr = prop
        args = [
            c
            for c in _children(node)
            if c.type == "call_argument"
        ]
        actual = []
        named_args: dict[str, frozenset[int]] = {}
        named_arg_groups = sum(
            1
            for a in args
            if any(
                c.type == "call_struct_argument"
                for c in _children(a)
            )
        )
        for a in args:
            struct_args = [
                c
                for c in _children(a)
                if c.type == "call_struct_argument"
            ]
            if struct_args:
                # `{name: value, ...}` named call args / struct
                # literal fields — keep the field names so a
                # resolved callee can map each to its param. Only
                # a single braced group is a well-formed named
                # call; several groups share `named_args`, so a
                # repeated field name would collide — leave it
                # empty and let arity matching apply.
                record_names = named_arg_groups == 1
                ndeps = frozenset()
                for sa in struct_args:
                    v = sa.child_by_field_name("value")
                    fname = sa.child_by_field_name("name")
                    vdeps = (
                        self._expr(
                            v, locals_, param_index, summary
                        )
                        if v is not None
                        else frozenset()
                    )
                    if fname is not None and record_names:
                        named_args[fname.text.decode()] = vdeps
                    ndeps |= vdeps
                actual.append(ndeps)
                continue
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
        if opt_deps:
            actual.append(opt_deps)
        actual_t = tuple(actual)
        actual_union = frozenset()
        for a in actual:
            actual_union |= a
        if fn_expr is not None and fn_expr.type == "new_expression":
            # `new C(args)` — contract deployment runs the
            # constructor when declared; other `new` targets
            # (arrays, unknown contracts) are opaque and their
            # result carries the arg deps.
            tn = fn_expr.child_by_field_name("name")
            cname = tn.text.decode() if tn is not None else None
            ctor = (
                f"{cname}.constructor"
                if cname in self._contract_names
                and f"{cname}.constructor" in self.functions
                else None
            )
            if ctor is not None:
                callee = self.summaries.get(ctor)
                if callee is None:
                    if self._inline_depth >= MAX_INLINE_DEPTH:
                        raise _Unsupported(
                            "analysis_limit", _span(node)
                        )
                    self._inline_depth += 1
                    prev_ret = getattr(self, "_ret_names", ())
                    prev_contract = getattr(
                        self, "_current_contract", None
                    )
                    prev_touch = self._effects_touched
                    try:
                        callee = self._summarize(
                            ctor, self.functions[ctor]
                        )
                    finally:
                        self._ret_names = prev_ret
                        self._current_contract = prev_contract
                        self._effects_touched = prev_touch
                        self._inline_depth -= 1
                    self.summaries[ctor] = callee
                if (
                    not callee.available
                    or callee.return_dependencies is None
                ):
                    # Unavailable constructor — the deployment
                    # is a gap, not a crash: record it opaquely
                    # and keep the arg deps flowing.
                    summary.gaps.append(
                        SolGap("call_unresolved", _span(node))
                    )
                    summary.calls.append(
                        SolCall(
                            _span(node),
                            f"new {cname}",
                            actual_t,
                            None,
                        )
                    )
                    if summary.effects != "state_writes":
                        summary.effects = "unknown"
                        self._effects_touched = True
                    return actual_union
                result_deps = (
                    actual_union | frozenset(
                        callee.return_dependencies
                    )
                )
                if callee.effects == "state_writes":
                    summary.effects = "state_writes"
                    self._effects_touched = True
                elif summary.effects != "state_writes":
                    summary.effects = "unknown"
                    self._effects_touched = True
                summary.calls.append(
                    SolCall(
                        _span(node),
                        f"new {cname}",
                        actual_t,
                        result_deps,
                    )
                )
                return result_deps
            summary.calls.append(
                SolCall(
                    _span(node),
                    f"new {cname}" if cname else "new",
                    actual_t,
                    actual_union,
                )
            )
            if summary.effects != "state_writes":
                summary.effects = "unknown"
                self._effects_touched = True
            return actual_union
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
        ) and ext_member is None:
            if void:
                summary.calls.append(
                    SolCall(_span(node), None, actual_t, None)
                )
                return frozenset()
            raise _Unsupported("call_unresolved", _span(node))
        name = (
            fn_expr.text.decode()
            if fn_expr is not None
            and fn_expr.type == "identifier"
            else ext_member[1]
        )
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
            if name in {"selfdestruct", "suicide"}:
                # Destroys the contract's storage — beyond
                # state_writes, keep it as unknown.
                if summary.effects != "state_writes":
                    summary.effects = "unknown"
                    self._effects_touched = True
            return actual_union
        # Hierarchy-aware resolution: the caller's contract and
        # its ancestors first (`super.x` skips the caller), then
        # any other contract in the file.
        targets: list[str] = []
        current = getattr(self, "_current_contract", "")
        if ext_member is not None:
            # `expr.f(...)`: resolve only when the receiver names
            # a declared contract/library — the target belongs
            # to the receiver's type, not a global lookup.
            obase = ext_member[0]
            obase_in = (
                _children(obase)[0]
                if obase.type == "expression"
                and len(_children(obase)) == 1
                else obase
            )
            if (
                obase_in is not None
                and obase_in.type == "identifier"
                and obase_in.text.decode() in self._contract_names
            ):
                targets = self._lookup_fns(
                    obase_in.text.decode(), name
                )
            else:
                # `x.f(a)` under `using L for T` — the receiver
                # becomes the library function's first arg.
                for lib in self._usings.get(current, ()):
                    found = self._lookup_fns(lib, name)
                    if found:
                        try:
                            bdeps = self._expr(
                                obase,
                                locals_,
                                param_index,
                                summary,
                            )
                        except _Unsupported:
                            bdeps = frozenset()
                        actual.insert(0, bdeps)
                        actual_t = tuple(actual)
                        actual_union |= bdeps
                        targets = found
                        break
            ext_member = None if targets else ext_member
        else:
            targets = self._lookup_fns(
                current, name, skip_self=super_call
            )
            if targets and not super_call:
                # Dynamic dispatch: a virtual callee may resolve
                # to any descendant override — union every
                # override declared below the caller's contract.
                # Copy first: `targets` may be the shared
                # overload-group list `_lookup_fns` returned, and
                # appending into it would pollute every later
                # lookup (base candidates would grow descendant
                # overrides, and `super.g()` could recurse into
                # the subclass).
                targets = list(targets)
                descendants = [
                    c
                    for c in self._contract_names
                    if c != current
                    and current in self._hierarchy(c)
                ]
                for desc in descendants:
                    for cand in self._overload_groups.get(
                        f"{desc}.{name}", ()
                    ):
                        if cand not in targets:
                            targets.append(cand)
        if not targets and ext_member is None:
            targets = list(self._free_fns.get(name, ()))
        if not targets and ext_member is None:
            for cname in dict.fromkeys(self.contracts.values()):
                if cname in self._hierarchy(current):
                    continue
                base = f"{cname}.{name}"
                if base in self._overload_groups:
                    targets = self._overload_groups[base]
                    break
        if not targets and name in self._struct_names:
            # `S(a, b)` / `S({x: a})` — a struct literal is a
            # value construction, not a call: the result slot
            # carries every field's deps.
            summary.calls.append(
                SolCall(
                    _span(node), f"new {name}", actual_t,
                    actual_union,
                )
            )
            return actual_union
        if not targets and name in self._contract_names:
            # `IERC20(token)` — a contract cast; the wrapped
            # expression's deps flow through.
            summary.calls.append(
                SolCall(_span(node), name, actual_t, actual_union)
            )
            return actual_union
        if not targets and ext_member is not None:
            # Storage-container builtins: `arr.push(v)`,
            # `arr.pop()` mutate the storage slot like an index
            # write. The receiver's root identifier must be a
            # declared state var.
            rb = ext_member[0]
            while (
                rb is not None
                and rb.type in {"member_expression", "array_access"}
            ):
                rb = rb.child_by_field_name(
                    "object"
                ) or rb.child_by_field_name("base")
            if (
                rb is not None
                and rb.type == "expression"
                and len(_children(rb)) == 1
            ):
                rb = _children(rb)[0]
            if (
                ext_member[1] in {"push", "pop"}
                and rb is not None
                and rb.type == "identifier"
                and rb.text.decode()
                in self._all_state_vars_of(current)
            ):
                rname = rb.text.decode()
                slot = locals_.setdefault(rname, frozenset())
                slot |= actual_union
                locals_[rname] = slot
                if self._writes:
                    self._writes[-1].add(rname)
                summary.effects = "state_writes"
                self._effects_touched = True
                summary.calls.append(
                    SolCall(
                        _span(node),
                        f"{ext_member[0].text.decode()}.{ext_member[1]}",
                        actual_t,
                        None if ext_member[1] == "push" else slot,
                    )
                )
                return (
                    frozenset()
                    if ext_member[1] == "push"
                    else slot
                )
            # External/library member call — opaque callee whose
            # result conservatively carries the args' and the
            # receiver expression's deps. The receiver itself is
            # opaque: an unresolvable base contributes no deps.
            try:
                base_deps = self._expr(
                    ext_member[0], locals_, param_index, summary
                )
            except _Unsupported:
                base_deps = frozenset()
            result_deps = actual_union | base_deps
            summary.calls.append(
                SolCall(
                    _span(node),
                    f"{ext_member[0].text.decode()}.{ext_member[1]}",
                    actual_t,
                    result_deps if not void else None,
                )
            )
            if summary.effects != "state_writes":
                summary.effects = "unknown"
                self._effects_touched = True
            return result_deps if not void else frozenset()
        if not targets:
            if void:
                # Unknown callee whose result is discarded —
                # record it opaquely rather than blocking the
                # whole summary (e.g. `revert MyError(x)`).
                summary.calls.append(
                    SolCall(_span(node), name, actual_t, None)
                )
                if summary.effects != "state_writes":
                    summary.effects = "unknown"
                    self._effects_touched = True
                return frozenset()
            raise _Unsupported("call_unresolved", _span(node))
        callees = []
        for target in targets:
            callee = self.summaries.get(target)
            if callee is None:
                if self._inline_depth >= MAX_INLINE_DEPTH:
                    raise _Unsupported(
                        "analysis_limit", _span(node)
                    )
                self._inline_depth += 1
                prev_ret = getattr(self, "_ret_names", ())
                prev_contract = getattr(
                    self, "_current_contract", None
                )
                prev_touch = self._effects_touched
                try:
                    callee = self._summarize(
                        target, self.functions[target]
                    )
                finally:
                    self._ret_names = prev_ret
                    self._current_contract = prev_contract
                    self._effects_touched = prev_touch
                    self._inline_depth -= 1
                self.summaries[target] = callee
            callees.append(callee)
        # Overloads: a candidate matches the call site by arity
        # — or, for named arguments, by supplying every declared
        # parameter name. An arity match that failed to analyze
        # is a gap: falling back to a different-arity overload
        # would report the wrong call as resolved.
        if named_args and not any(
            c.type == "call_argument" and not any(
                cc.type == "call_struct_argument"
                for cc in _children(c)
            )
            for c in args
        ):
            matched = [
                c
                for c in callees
                if set(c.params) == set(named_args)
            ]
        else:
            matched = [
                c
                for c in callees
                if len(c.params) == len(actual_t)
            ]
        usable = [
            c
            for c in matched
            if c.available and c.return_dependencies is not None
        ]
        if not usable and not matched:
            usable = [
                c
                for c in callees
                if c.available and c.return_dependencies is not None
            ]
        if not usable:
            summary.calls.append(
                SolCall(_span(node), name, actual_t, None)
            )
            summary.gaps.append(
                SolGap("call_unresolved", _span(node))
            )
            raise _Unsupported("call_unresolved", _span(node))
        result = frozenset()
        for callee in usable:
            for idx in sorted(callee.return_dependencies):
                if idx < len(callee.params):
                    pname = callee.params[idx]
                    if pname in named_args:
                        result |= named_args[pname]
                    elif idx < len(actual_t):
                        result |= actual_t[idx]
        for callee in usable:
            if callee.effects == "state_writes":
                summary.effects = "state_writes"
                self._effects_touched = True
            elif callee.effects == "unknown" and (
                summary.effects != "state_writes"
            ):
                summary.effects = "unknown"
                self._effects_touched = True
            if callee.effects in {"state_writes", "unknown"}:
                # The callee may write any state var — its arg
                # deps may now live behind a state read.
                for sv in self._state_vars_of(
                    getattr(self, "_current_contract", "")
                ):
                    if sv in locals_:
                        locals_[sv] = locals_[sv] | actual_union
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


# Opt-in CLI routes — `python -m agent sol-summaries <file>` prints
# the summary set as deterministic JSON on stdout, and
# `python -m agent sol-summaries-accept <file> --manifest <PATH>
# --function <NAME>` accepts one function's declared summary under
# the strict whole-context gate (context key match + the function
# still present in the fresh derivation; `<NAME>` matches either the
# bare `name` or the disambiguated `<contract>.<name>`). These change
# no default audit/CLI/MCP route: the analysis stays a conservative
# dependency report, not a proof, verdict or trust gate, and a host
# must invoke the subcommands explicitly. Inputs are bounded — an
# oversized source or manifest is an error, never a silently
# truncated analysis.
MAX_SOURCE_BYTES = 256 * 1024
ACCEPT_PROFILE = "mumei.sol-summary-accept/v1"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024


def build_parser(parser=None):
    import argparse

    if parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent sol-summaries",
            description=(
                "Emit opt-in Solidity interprocedural dependency "
                "summaries as JSON — a conservative report, not a "
                "proof or verdict."
            ),
        )
    parser.add_argument(
        "source",
        help="Path to a single Solidity source file "
        "(at most 256 KiB).",
    )
    return parser


def build_accept_parser(parser=None):
    """Parser for ``sol-summaries-accept``: the produce route's
    declared inputs plus ``--manifest`` and ``--function`` naming the
    declared manifest and the function whose summary is accepted."""
    parser = build_parser(parser)
    parser.description = (
        "Re-derive the Solidity summary set for one declared source "
        "and accept one function's summary under the strict "
        "whole-context gate."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="<PATH>",
        help=(
            "Summary manifest (mumei.sol-scalar-parameter-deps/v1) "
            "to accept from."
        ),
    )
    parser.add_argument(
        "--function",
        required=True,
        metavar="<NAME>",
        help=(
            "Function whose summary to accept — the emitted name "
            "('C.f') or a bare member name ('f') when it is "
            "unambiguous. Accepted only when the manifest's context "
            "key still matches the fresh derivation and the function "
            "survives in it."
        ),
    )
    return parser


def _emit(payload, code):
    import json
    import sys

    print(json.dumps(payload, sort_keys=True))
    sys.exit(code)


def _reject_overwrite(output, declared_paths, schema):
    """`--output` may not overwrite a declared input — writing
    the report would destroy the bytes the report describes."""
    import os
    from pathlib import Path

    if output is None:
        return
    for declared in declared_paths:
        try:
            same = Path(output).resolve() == Path(declared).resolve()
        except RuntimeError:
            same = True
        if not same:
            try:
                same = os.path.samefile(output, declared)
            except OSError:
                same = False
        if same:
            _emit(
                {
                    "schema_version": schema,
                    "error": {
                        "reason": "output_overwrites_source",
                        "detail": (
                            "declared output path would overwrite a "
                            "declared input"
                        ),
                    },
                },
                2,
            )


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


CHECK_PROFILE = "mumei.sol-summary-check/v1"


def build_check_parser(parser=None):
    """Parser for ``sol-summaries-check``: the produce route's
    declared inputs plus ``--manifest`` naming the summary manifest
    to check and ``--output`` for the check report."""
    parser = build_parser(parser)
    parser.description = (
        "Re-derive the Solidity summary set for one declared "
        "source and check a declared manifest's functions against "
        "it."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="<PATH>",
        help=(
            "Summary manifest (mumei.sol-scalar-parameter-deps/v1) "
            "to check."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="<PATH>",
        help="Write the check report JSON here instead of stdout.",
    )
    return parser


def build_reuse_parser(parser=None):
    """Parser for ``sol-summaries-reuse``: the produce route's
    declared inputs plus ``--manifest`` naming the manifest to reuse
    from and ``--output`` for the merged manifest."""
    parser = build_check_parser(parser)
    parser.description = (
        "Re-derive the Solidity summary set for one declared "
        "source and emit a manifest that reuses a declared "
        "manifest's unchanged summaries."
    )
    for action in parser._actions:
        if action.dest == "manifest":
            action.help = (
                "Summary manifest (mumei.sol-scalar-parameter-deps/v1) "
                "to reuse unchanged summaries from."
            )
        elif action.dest == "output":
            action.help = (
                "Write the merged manifest JSON here instead of "
                "stdout."
            )
    return parser


def _read_declared_manifest(path, schema=ACCEPT_PROFILE):

    import json

    try:
        with open(path, "rb") as handle:
            blob = handle.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        _emit(
            {
                "schema_version": schema,
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
                "schema_version": schema,
                "error": {
                    "reason": "manifest_too_large",
                    "limit_bytes": MAX_MANIFEST_BYTES,
                },
            },
            2,
        )
    try:
        return SolSummarySet.from_dict(json.loads(blob))
    except (TypeError, UnicodeDecodeError):
        _emit(
            {
                "schema_version": schema,
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
                "schema_version": schema,
                "error": {
                    "reason": "manifest_malformed",
                    "detail": str(exc),
                },
            },
            2,
        )


def main(args=None) -> None:
    import json

    if args is None:
        args = build_parser().parse_args()
    raw = _read_declared_source(args.source, PROFILE)
    print(json.dumps(summarize_solidity(raw).to_dict(), sort_keys=True))


def summary_accept_document(declared, live, function) -> dict:
    """The ``mumei.sol-summary-accept/v1`` acceptance document.

    Shared by ``sol-summaries-accept`` and the
    ``sol_summaries_accept`` MCP tool so both emit the identical
    decision: the strict whole-context gate (`context_match`), then
    a declared-only function resolution that emits the freshly
    derived record — never the declared one, so the manifest-forgery
    channel is closed.
    """
    report = {
        "schema_version": ACCEPT_PROFILE,
        "accepted": False,
        "function": function,
        "context_match": declared.context_key == live.context_key,
    }
    if not report["context_match"]:
        report["reason"] = "context_mismatch"
    else:
        # Emit the freshly derived record, never the declared one —
        # identical for honest manifests, and removes the manifest-
        # forgery channel entirely. A bare member name must resolve
        # to exactly one function. An exact match on the emitted name
        # (`f`, `C.f`, `C.f#2`) wins over the bare-member-name
        # fallback; the fallback compares name stems, so `C.f#2` also
        # answers to `f` and an undiscriminated name stays ambiguous.
        matches = [
            f for f in live.functions if f.name == function
        ]
        if not matches:
            matches = [
                f
                for f in live.functions
                if f.name.rsplit(".", 1)[-1].split("#", 1)[0]
                == function
            ]
        declared_names = {f.name for f in declared.functions}
        if not matches:
            report["reason"] = "unknown_function"
        elif len(matches) > 1:
            report["reason"] = "ambiguous_function"
        elif matches[0].name not in declared_names:
            # The strict gate admits a function the manifest
            # actually declares — a context match alone must
            # not accept an undeclared function.
            report["reason"] = "undeclared_function"
        else:
            report["accepted"] = True
            report["summary"] = matches[0].to_dict()
    return report


def main_accept(args=None) -> None:
    if args is None:
        args = build_accept_parser().parse_args()
    declared = _read_declared_manifest(args.manifest)
    raw = _read_declared_source(args.source, ACCEPT_PROFILE)
    live = summarize_solidity(raw)
    _emit(
        summary_accept_document(declared, live, args.function), 0
    )


def _reuse_partition(declared, live):
    """Partition the manifest's functions against the fresh set.

    `reusable` — the name survives and the record is identical
    (derivation is deterministic, so an unchanged function derives
    the same record); `stale` — the name survives but the record
    differs; `missing` — the fresh set no longer produces the name.
    Detection only.
    """
    live_by_name = {}
    for f in live.functions:
        live_by_name.setdefault(f.name, f)
    reusable, stale, missing = [], [], []
    for entry in declared.functions:
        fresh = live_by_name.get(entry.name)
        if fresh is None:
            missing.append(entry.name)
        elif fresh == entry:
            reusable.append(entry.name)
        else:
            stale.append(entry.name)
    return reusable, stale, missing


def summary_check_document(declared, live) -> dict:
    """The ``mumei.sol-summary-check/v1`` comparison document.

    Shared by ``sol-summaries-check`` and the ``sol_summaries_check``
    MCP tool so both emit the identical partition: `context_match`
    (the strict whole-context gate) plus the name-level
    `reusable`/`stale`/`missing` sets. Detection only — what to
    recompute is the host's call.
    """
    reusable, stale, missing = _reuse_partition(declared, live)
    return {
        "schema_version": CHECK_PROFILE,
        "context_match": declared.context_key == live.context_key,
        "reusable": sorted(reusable),
        "stale": sorted(stale),
        "missing": sorted(missing),
    }


def summary_reuse_set(declared, live) -> SolSummarySet:
    """The merged summary set emitted by ``sol-summaries-reuse``.

    Shared by ``sol-summaries-reuse`` and the ``sol_summaries_reuse``
    MCP tool so both emit the identical manifest: a declared function
    whose record is identical under the fresh derivation is reused
    verbatim, every other live function is freshly derived and a
    `missing` entry is dropped. The emitted set is keyed to the fresh
    context — per-function reuse stays the host's weaker freshness
    choice, never the strict whole-context gate.
    """
    reusable, _, _ = _reuse_partition(declared, live)
    declared_by_name = {f.name: f for f in declared.functions}
    merged = [
        declared_by_name.get(f.name, f) if f.name in reusable else f
        for f in live.functions
    ]
    return SolSummarySet(live.context_key, merged)


def main_check(args=None) -> None:
    """Check a declared manifest against a fresh summary set.

    Emits ``mumei.sol-summary-check/v1``: whether the declared
    context key still matches (the strict whole-context gate) and a
    name-level partition of the manifest's functions — `reusable`
    (identical record survives), `stale` (same name, different
    record) and `missing` (the fresh set no longer produces the
    name). Detection only — what to recompute is the host's call.
    """
    import json

    if args is None:
        args = build_check_parser().parse_args()
    _reject_overwrite(
        getattr(args, "output", None),
        [args.manifest, args.source],
        CHECK_PROFILE,
    )
    declared = _read_declared_manifest(args.manifest, CHECK_PROFILE)
    raw = _read_declared_source(args.source, CHECK_PROFILE)
    live = summarize_solidity(raw)
    document = json.dumps(
        summary_check_document(declared, live), sort_keys=True
    )
    if getattr(args, "output", None):
        with open(args.output, "w") as handle:
            handle.write(document + "\n")
    else:
        print(document)


def main_reuse(args=None) -> None:
    """Emit a manifest reusing a declared manifest's unchanged
    summaries.

    Same partition as ``sol-summaries-check``: a declared function
    whose record is identical under the fresh derivation is reused
    verbatim, every other live function is freshly derived and a
    `missing` entry is dropped. The emitted set is keyed to the fresh
    context — per-function reuse stays the host's weaker freshness
    choice, never the strict whole-context gate.
    """
    import json

    if args is None:
        args = build_reuse_parser().parse_args()
    _reject_overwrite(
        getattr(args, "output", None),
        [args.manifest, args.source],
        CHECK_PROFILE,
    )
    declared = _read_declared_manifest(args.manifest, CHECK_PROFILE)
    raw = _read_declared_source(args.source, CHECK_PROFILE)
    live = summarize_solidity(raw)
    document = json.dumps(
        summary_reuse_set(declared, live).to_dict(),
        sort_keys=True,
    )
    if getattr(args, "output", None):
        with open(args.output, "w") as handle:
            handle.write(document + "\n")
    else:
        print(document)


ATTEMPT_REQUEST_PROFILE = "mumei.sol-summaries-attempt-request/v1"
ATTEMPT_REPORT_PROFILE = "mumei.sol-summaries-attempt-report/v1"


def build_attempt_parser(parser=None):
    """Parser for ``sol-summaries-attempt``: the produce route's
    declared inputs plus the attempt's own declared timeout and an
    optional memory bound."""
    parser = build_parser(parser)
    parser.description = (
        "Run the sol-summaries produce route as one declared attempt "
        "and emit the reconciled lineage descriptors."
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        required=True,
        metavar="<MS>",
        help="Declared attempt bound in milliseconds (required).",
    )
    parser.add_argument(
        "--memory-bound-mb",
        type=int,
        default=None,
        metavar="<MB>",
        help=(
            "Optional declared POSIX RLIMIT_AS ceiling applied to the "
            "attempt child's whole address space."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="<PATH>",
        help="Write the attempt report JSON here instead of stdout.",
    )
    return parser


def _attempt_fingerprint(source_path: str, raw: bytes) -> str:
    """Bind the request's declared input into one request identity."""
    import hashlib
    import json

    request_doc = {
        "schema_version": ATTEMPT_REQUEST_PROFILE,
        "source": {
            "path": source_path,
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
    return hashlib.sha256(
        json.dumps(
            request_doc, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def main_attempt(args=None) -> None:
    """Run the produce route as one declared attempt.

    Spawns ``python -m agent sol-summaries <source>`` through the
    C11 dispatch lifecycle: a fresh ``AttemptSequence`` keyed to the
    request fingerprint (the declared source's bytes), one reserved
    attempt observed by ``dispatch_attempt`` under
    ``--attempt-timeout``, reconcile and compare-and-set
    publication — an ``exited`` run's captured stdout becomes the
    selected result only when every declared input byte is unchanged
    after the observed run. Emits
    ``mumei.sol-summaries-attempt-report/v1`` — the canonical
    lineage, the normalized run-result descriptor and, only when a
    result was selected, the
    ``mumei.verifier-evidence-candidate/v1`` descriptor.
    """
    import json
    import sys
    from pathlib import Path

    if args is None:
        args = build_attempt_parser().parse_args()
    _reject_overwrite(
        args.output, [args.source], ATTEMPT_REPORT_PROFILE
    )
    raw = _read_declared_source(args.source, ATTEMPT_REPORT_PROFILE)
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    fingerprint = _attempt_fingerprint(args.source, raw)
    argv = (
        sys.executable,
        "-m",
        "agent",
        "sol-summaries",
        args.source,
    )
    try:
        sequence = AttemptSequence(fingerprint, args.attempt_timeout)
        store = AttemptSequenceStore()
        store.publish(sequence)
        current = store.current
        dispatch = dispatch_attempt(
            current.begin_attempt(),
            argv,
            memory_bound_mb=args.memory_bound_mb,
        )
        try:
            drifted = (
                _attempt_fingerprint(
                    args.source, Path(args.source).read_bytes()
                )
                != fingerprint
            )
        except OSError:
            drifted = True
        if dispatch.run.record.state == "exited" and not drifted:
            updated = dispatch.sequence.select_result(
                dispatch.captured_output()
            )
        else:
            updated = dispatch.sequence
        published = store.compare_and_set(current, updated)
    except ValueError as exc:
        _emit(
            {
                "schema_version": ATTEMPT_REPORT_PROFILE,
                "error": {"reason": "attempt_failed", "detail": str(exc)},
            },
            2,
        )
    report = {
        "schema_version": ATTEMPT_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if published.selected_result is not None:
        report["candidate"] = published.evidence_candidate().to_dict()
    document = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(document)
    else:
        sys.stdout.write(document)
