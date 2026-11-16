from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from agent import control_flow, go_interprocedural as ip
from agent.go_type_snapshot import (
    ByteSpan,
    FileSpan,
    GoType,
    SnapshotError,
    load_go_package_snapshot,
    load_go_snapshot,
)
from tests import test_go_type_snapshot as compiler_fixtures
from tests.test_go_type_snapshot import (
    SOURCE,
    compiler_report,
    schema_fixture,
)

go_types_helper = compiler_fixtures.go_types_helper


def unit(helper: Path, declarations: str, arch: str = "amd64"):
    source = "package p;\n" + declarations
    snapshot = load_go_snapshot(
        compiler_report(helper, source, arch), source, target_arch=arch
    )
    return source, snapshot, ip.summarize_go(source, snapshot)


def named(source, snapshot, summaries, name="F"):
    fn = next(
        f for f in snapshot.functions if snapshot.binding(f.binding_id).name == name
    )
    return summaries.for_function(source, snapshot, fn.binding_id)


@pytest.mark.parametrize("expression", ["x", "(x)", "+x", "-x", "^x", "x*0", "x-x"])
def test_parameter_dependence_is_conservative_not_value_equivalence(
    go_types_helper, expression
):
    data = unit(go_types_helper, f"func F(x int64) int64 {{ return {expression} }}")
    result = named(*data)
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "operator", ["+", "-", "*", "/", "%", "&", "|", "^", "&^", "<<", ">>"]
)
def test_scalar_operators_join_parameter_dependencies(go_types_helper, operator):
    result = named(
        *unit(go_types_helper, f"func F(x, y int64) int64 {{ return x {operator} y }}")
    )
    assert result.return_dependencies == frozenset({0, 1})


@pytest.mark.parametrize("operator", ["==", "!=", "<", "<=", ">", ">="])
def test_comparisons_preserve_compiler_result_type(go_types_helper, operator):
    result = named(
        *unit(go_types_helper, f"func F(x, y int64) bool {{ return x {operator} y }}")
    )
    assert result.available and result.result_type.kind == "boolean"
    assert result.return_dependencies == frozenset({0, 1})


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("true", set()),
        ("false", set()),
        ("!x", {0}),
        ("x&&y", {0, 1}),
        ("x||y", {0, 1}),
    ],
)
def test_boolean_dependencies(go_types_helper, expression, expected):
    result = named(
        *unit(go_types_helper, f"func F(x, y bool) bool {{ return {expression} }}")
    )
    assert result.available and result.return_dependencies == frozenset(expected)


@pytest.mark.parametrize("literal", ["0", "0xff", "0b11", "0o10", "1_024", "'雪'"])
def test_parameter_independent_does_not_claim_a_constant_value(
    go_types_helper, literal
):
    result = named(
        *unit(go_types_helper, f"func F(_ int64) int64 {{ return {literal} }}")
    )
    assert result.available and result.return_dependencies == frozenset()
    assert not hasattr(result, "constant_value")


@pytest.mark.parametrize("arch,width", [("amd64", 64), ("386", 32), ("arm64", 64)])
def test_width_and_named_type_context_survives_composition(
    go_types_helper, arch, width
):
    data = unit(
        go_types_helper,
        "type N int; func Leaf(x N) N { return x }; func F(y N) N { return Leaf(y) }",
        arch,
    )
    result = named(*data)
    assert result.available and result.parameters[0].bit_width == width
    assert result.result_type == result.parameters[0]
    assert result.result_type.type_id


def test_reordered_arguments_bind_by_compiler_parameter_identity(go_types_helper):
    data = unit(
        go_types_helper,
        "func Pick(a,b int64) int64 { return a }; func F(x,y int64) int64 { return Pick(y,x) }",
    )
    result = named(*data)
    assert result.return_dependencies == frozenset({1})
    assert result.calls[0].arguments == (frozenset({1}), frozenset({0}))
    assert result.calls[0].result == frozenset({1})
    assert result.calls[0].target == named(*data, "Pick").binding_id


def test_nested_transitive_calls_and_unicode_byte_spans(go_types_helper):
    data = unit(
        go_types_helper,
        "// 雪\nfunc Id(雪 int64) int64 { return 雪 }; func Pick(a,b int64) int64 {return a}; func F(雪 int64) int64 { return Pick(Id(雪), Id('雪')) }",
    )
    source, snapshot, summaries = data
    result = named(*data)
    assert result.available and result.return_dependencies == frozenset({0})
    assert len(result.calls) == 3
    for transfer in result.calls:
        call = next(c for c in snapshot.calls if c.span == transfer.span)
        assert call.target == transfer.target
        assert source.encode()[transfer.span.start : transfer.span.end].endswith(b")")
    assert summaries == ip.summarize_go(source, snapshot)


@pytest.mark.parametrize(
    "declarations",
    [
        "func F(x int64) int64 { return F(x) }",
        "func G(x int64) int64 { return F(x) }; func F(x int64) int64 { return G(x) }",
        "func R(x int64) int64 { return R(x) }; func F(x int64) int64 { return R(x) }",
    ],
)
def test_recursive_edges_never_supply_a_summary(go_types_helper, declarations):
    source, snapshot, summaries = unit(go_types_helper, declarations)
    for summary in summaries.functions:
        assert not summary.available and summary.return_dependencies is None
        assert summary.effects == "unknown" and not summary.calls
        assert summary.gaps[0].reason == "recursive_call_graph"


@pytest.mark.parametrize(
    "declarations",
    [
        "func Ext(x int64) int64; func F(x int64) int64 { return Ext(x) }",
        "func F(f func(int64) int64, x int64) int64 { return f(x) }",
        "func Id(x int64) int64 {return x}; var Alias = Id; func F(x int64) int64 {return Alias(x)}",
        "func F(x int64) (int64,int64) {return x,x}",
        "func F(x int64) float64 {return 1.0}",
        "func F(x int64) int64 {return 1.0}",
        "func F(x int64) int64 {return (func() int64 {return x})()}",
        "func G(){}; func F(x int64) int64 {defer G(); return x}",
        "func G(){}; func F(x int64) int64 {go G(); return x}",
        "func F(x []int64) int64 {return x[0]}",
        "func F(x map[int64]int64) int64 {return x[0]}",
        "func F(x chan int64) int64 {return <-x}",
        "type I interface{Get()int64}; func F(x I) int64 {return x.Get()}",
        "type T int64; func(t T)Get()int64{return int64(t)}; func F(x T)int64{return x.Get()}",
        "func G[T ~int64](x T)T{return x}; func F(x int64)int64{return G(x)}",
        "func G(x ...int64)int64{return x[0]}; func F(x int64)int64{return G(x)}",
    ],
)
def test_unsupported_edges_values_aliases_resources_and_effects_are_unknown(
    go_types_helper, declarations
):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available and result.return_dependencies is None
    assert result.effects == "unknown" and result.gaps and not result.calls


@pytest.mark.parametrize(
    "declarations",
    [
        # A callee mutating a slice's resource state has a non-scalar
        # signature; the composite literal argument is unsupported anyway.
        "func G(s []int64) int64 { s[0] = 1; return s[0] }; func F(x int64) int64 { return G([]int64{x}) }",
        # `make` still produces non-scalar resource state.
        "func F(x int64) int64 { var s []int64; _ = s; return x }",
        # A channel is resource state — `nil` has no binding either.
        "func G(c chan int64) int64 { return <-c }; func F(x int64) int64 { return G(nil) }",
        # A bound function value is non-scalar — indirect dispatch stays
        # outside the resolved-call fragment.
        "func G(v int64) int64 { return v }; func F(x int64) int64 { h := G; return h(x) }",
    ],
)
def test_interprocedural_alias_and_resource_state_stay_unsupported(
    go_types_helper, declarations
):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available and result.return_dependencies is None
    assert result.effects == "unknown" and result.gaps and not result.calls


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # A let binding propagates its initializer's dependencies.
        ("func F(x int64) int64 { y:=x; return y }", frozenset({0})),
        ("func F(x int64) int64 { y:=x+1; return y }", frozenset({0})),
        ("func F(x, y int64) int64 { z:=x+y; return z }", frozenset({0, 1})),
        # An initializer that ignores one parameter keeps it out.
        ("func F(x, y int64) int64 { z:=y; return z }", frozenset({1})),
        # Chained bindings resolve transitively.
        ("func F(x int64) int64 { y:=x; z:=y; return z }", frozenset({0})),
        # A let-bound name may shadow nothing and still propagate.
        ("func F(x int64) int64 { y:=x; return y+1 }", frozenset({0})),
        # Boolean let bindings are in the scalar fragment.
        ("func F(x bool) bool { y:=x; return y }", frozenset({0})),
        # Calls inside an initializer keep their transfers.
        (
            "func Leaf(a int64)int64{return a}; "
            "func F(x int64)int64{ y:=Leaf(x); return y }",
            frozenset({0}),
        ),
        # Multi-name declarations bind each name to its own RHS.
        (
            "func F(x, y int64) int64 { a, b := x, y; return a + b }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { a, b := x, y; _ = b; return a }",
            frozenset({0}),
        ),
        (
            "func F(x, y int64) int64 { a, b := x, y; _ = a; return b }",
            frozenset({1}),
        ),
        # The whole RHS evaluates against the pre-state before any
        # store — the second declaration's `a` reads the outer binding.
        (
            "func F(x, y int64) int64 { a := x; a, b := a, y; return b }",
            frozenset({1}),
        ),
        # ...and a swapped RHS proves it: `b` reads the pre-state `a`
        # ({0}), not the value `a` is about to take ({1}).
        (
            "func F(x, y int64) int64 { a := x; a, b := y, a; _ = a; return b }",
            frozenset({0}),
        ),
        # `_` discards its value — the RHS is still evaluated.
        (
            "func F(x, y int64) int64 { a, _ := x, y; return a }",
            frozenset({0}),
        ),
        # A later `:=` may redeclare a name — go/types keeps the
        # existing binding, so its dependencies just update.
        (
            "func F(x, y int64) int64 { a, b := x, x; a, c := y, x; return a + b + c }",
            frozenset({0, 1}),
        ),
        # Mixed redeclare: `x` already exists, `y` is new — the reused
        # name keeps the fragment's assignment semantics.
        (
            "func F(x, y int64) int64 { x, z := x, y; return x + z }",
            frozenset({0, 1}),
        ),
        # Branch-scoped multi-name declarations don't escape.
        (
            "func F(x, y int64) int64 { if x > 0 { a, b := x, y; _ = a; _ = b }; return x }",
            frozenset({0}),
        ),
    ],
)
def test_let_bindings_propagate_dependencies(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # A `*int64` parameter dereference reads through the
        # pointer's own provenance.
        ("func F(x *int64) int64 { return *x }", frozenset({0})),
        # `p := &x` binds the pointer's provenance — a `*p` read
        # carries x's deps, with the pointee classified by the
        # pointer fact's `elem` since `*int64` names no identity.
        ("func F(x int64) int64 { p := &x; return *p }", frozenset({0})),
        # A `*int64` callee parameter reads through a `&x` argument…
        (
            "func G(p *int64) int64 { return *p }; "
            "func F(x int64) int64 { return G(&x) }",
            frozenset({0}),
        ),
        # …and through a bound alias passed as the argument.
        (
            "func G(p *int64) int64 { return *p }; "
            "func F(x int64) int64 { q := &x; return G(q) }",
            frozenset({0}),
        ),
        # A `*p` store folds the stored value into the escaped binding.
        (
            "func F(x, y int64) int64 { p := &x; *p = y; return x }",
            frozenset({0, 1}),
        ),
    ],
)
def test_unnamed_scalar_pointees_alias_and_resolve(
    go_types_helper, declarations, expected
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    # Every unnamed-pointee deref records an imported transfer — the
    # pointee is memory outside the fragment, so `effects` reports
    # `unknown`; a callee's imported transfer marks its call site
    # `imported` rather than propagating into the caller's list.
    assert result.effects == "unknown"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # Branch returns union their dependencies.
        (
            "func F(x int64) int64 { if x>0 {return x}; return 0 }",
            frozenset({0}),
        ),
        (
            "func F(x, y int64) int64 { if x>0 {return x} else {return y} }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { if x>0 {return y}; return 0 }",
            frozenset({1}),
        ),
        # Branch-local lets feed returns inside their own branch only.
        (
            "func F(x int64) int64 { if x>0 {y:=x; return y}; return 0 }",
            frozenset({0}),
        ),
        # else-if chains are nested branches.
        (
            "func F(x, y int64) int64 { if x>0 {return x} else if y>0 {return y}; return 0 }",
            frozenset({0, 1}),
        ),
        # A condition is evaluated but contributes no result dependency.
        (
            "func F(x, y int64) int64 { if x>0 {return y}; return y }",
            frozenset({1}),
        ),
        # Calls inside branches keep their transfers.
        (
            "func Leaf(a int64)int64{return a}; "
            "func F(x int64)int64{ if x>0 {return Leaf(x)}; return 0 }",
            frozenset({0}),
        ),
    ],
)
def test_branched_bodies_union_return_dependencies(
    go_types_helper, declarations, expected
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # A bounded for-clause: let init, supported condition, dec update.
        (
            "func F(x int64) int64 { for i:=x; i>0; i-- {}; return x }",
            frozenset({0}),
        ),
        # Loop-scoped bindings feed returns inside the body only.
        (
            "func F(x, y int64) int64 { for i:=x; i>0; i-- { return y }; return x }",
            frozenset({0, 1}),
        ),
        # A condition-only loop evaluates its condition, effect-free.
        (
            "func F(x, y int64) int64 { for x>0 { return y }; return y }",
            frozenset({1}),
        ),
        # An empty infinite loop is a valid terminator shape.
        (
            "func F(x int64) int64 { for {}; return x }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { for { return x } }",
            frozenset({0}),
        ),
        # Inc updates on parameters are allowed; deps are unchanged.
        (
            "func F(x, y int64) int64 { for ; x>0; x++ {}; return y }",
            frozenset({1}),
        ),
        # Assignment updates seed the next pass: `i = x - 1` keeps `i`
        # (and anything the body writes from it) dependent on `x`.
        (
            "func F(x int64) int64 { var y int64; for i:=x; i>0; i=i-1 { y = i }; return y }",
            frozenset({0}),
        ),
        (
            "func F(x, z int64) int64 { y := x; for ; y>0; y=y+z { _ = y }; return y }",
            frozenset({0, 1}),
        ),
        # Compound and tuple updates run through the same dispatch.
        (
            "func F(x, z int64) int64 { y := x; for ; y>0; y += z { _ = y }; return y }",
            frozenset({0, 1}),
        ),
        # A call in update position records its transfer each pass.
        (
            "func G(v int64) int64 { return v }\nfunc F(x int64) int64 { y := x; for ; y>0; y=G(y) { _ = y }; return y }",
            frozenset({0}),
        ),
        # A tuple update widens through the fixed point like the body.
        (
            "func F(x, z int64) int64 { y := x; w := z; for ; y>0; y, w = w, y { _ = w }; return y }",
            frozenset({0, 1}),
        ),
    ],
)
def test_for_bodies_union_return_dependencies(
    go_types_helper, declarations, expected
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # Integer range: the loop variable carries the operand's deps.
        (
            "func F(x int64) int64 { for i := range x { _ = i }; return x }",
            frozenset({0}),
        ),
        # Body may-assignments join back like any loop.
        (
            "func F(x, y int64) int64 { for i := range x { y = i }; return y }",
            frozenset({0, 1}),
        ),
        # The scoped loop variable does not escape.
        (
            "func F(x int64) int64 { for i := range x { _ = i }; return 0 }",
            frozenset(),
        ),
        # `for _ = range e` and bare `for range e` just evaluate.
        (
            "func F(x int64) int64 { for _ = range x {}; return x }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { for range x {}; return x }",
            frozenset({0}),
        ),
        # The `=` form reuses an existing binding — a may-assignment, so
        # the name keeps its own dep too (zero-trip path).
        (
            "func F(x, y int64) int64 { for y = range x {}; return y }",
            frozenset({0, 1}),
        ),
        # break/continue inside an integer range work like any loop.
        (
            "func F(x, y int64) int64 { for i := range x { if i > 0 { break }; y = i }; return y }",
            frozenset({0, 1}),
        ),
        # Scalar conversions stay valid range operands.
        (
            "func F(x int64) int64 { for i := range int(x) { _ = i }; return x }",
            frozenset({0}),
        ),
        (
            "type N int64\nfunc F(x int64) int64 { for i := range N(x) { _ = i }; return x }",
            frozenset({0}),
        ),
    ],
)
def test_range_int_dependencies(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # A const read is always dep-free — a constant expression can
        # never read a variable (the compiler rejects it first).
        (
            "func F(x int64) int64 { const K = 5; y := x + K; return y }",
            frozenset({0}),
        ),
        # Typed, untyped, rune and bool constants all admit.
        (
            "func F(x int64) int64 { const K int64 = 5; return x + K }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { const R = 'a'; _ = R; return x }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { const B = true; if B { return x }; return 0 }",
            frozenset({0}),
        ),
        # Chained and package-level constants resolve the same way.
        (
            "const K0 = 3\nfunc F(x int64) int64 { const K = K0 + 1; return x + K }",
            frozenset({0}),
        ),
        (
            "const K int64 = 7\nfunc F(x int64) int64 { return x + K }",
            frozenset({0}),
        ),
        # `iota` is a dep-free universe constant.
        (
            "func F(x int64) int64 { const A = iota; return x + A }",
            frozenset({0}),
        ),
        # `iota` is not a keyword — a parameter named `iota` keeps its
        # own dependency, and a shadowing const still resolves as one.
        (
            "func F(iota int64) int64 { return iota }",
            frozenset({0}),
        ),
        (
            "const iota int64 = 3\nfunc F(x int64) int64 { return iota + x }",
            frozenset({0}),
        ),
        # A constant shadowing a name resolves to the const binding.
        (
            "func F(x int64) int64 { y := x; if x > 0 { const k = 2; y = k }; return y }",
            frozenset({0}),
        ),
        # Blank names admit; `const A, B = 1, 2` binds pairwise.
        (
            "func F(x int64) int64 { const _ = 5; return x }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { const A, B = 1, 2; return x + A + B }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { const A, B int64 = 1, 2; return x + A + B }",
            frozenset({0}),
        ),
        # A constant-expression builtin is still checked for legality.
        (
            "func F(x int64) int64 { const A = min(1, 2); return x + A }",
            frozenset({0}),
        ),
    ],
)
def test_const_declarations_and_reads(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,reason",
    [
        # Non-scalar constants stay outside the fragment.
        (
            "func F(x int64) int64 { const S = \"s\"; return x }",
            "binding_unavailable",
        ),
        (
            "func F(x int64) int64 { const Q = 1.5; return x }",
            "binding_unavailable",
        ),
        # Reading a non-scalar constant is a declared gap too.
        (
            "const S = \"s\"\nfunc F(x int64) int64 { if S == \"a\" { return 1 }; return x }",
            "binding_unavailable",
        ),
        # A builtin that is not in the admitted set stays opaque.
        (
            "func F(x int64) int64 { const A = len(\"s\"); return x }",
            "unresolved_or_opaque_call",
        ),
    ],
)
def test_const_declaration_gaps(go_types_helper, declarations, reason):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available and result.gaps[0].reason == reason


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # A named result is a dep-free local; a bare return yields it.
        (
            "func F(x int64) (r int64) { r = x; return }",
            frozenset({0}),
        ),
        (
            "func F(x int64) (r int64) { return }",
            frozenset(),
        ),
        # An explicit return value behaves like an unnamed result.
        (
            "func F(x int64) (r int64) { return x }",
            frozenset({0}),
        ),
        (
            "func F(x int64) (r int64) { r = x; return r }",
            frozenset({0}),
        ),
        # Reassignments and may-assignments join like any local.
        (
            "func F(x int64) (r int64) { r = x + 1; r = r + 1; return }",
            frozenset({0}),
        ),
        (
            "func F(x int64) (r int64) { if x > 0 { r = x }; return }",
            frozenset({0}),
        ),
        # An untouched result stays parameter-independent.
        (
            "func F(x int64) (r int64) { y := x; _ = y; return }",
            frozenset(),
        ),
        # An inner declaration shadows without writing the result.
        (
            "func F(x int64) (r int64) { if x > 0 { r := x; _ = r }; return }",
            frozenset(),
        ),
        # Reading the result and returning a parameter are independent.
        (
            "func F(x int64) (r int64) { _ = r; return x }",
            frozenset({0}),
        ),
        # A result written through a loop keeps the joined deps.
        (
            "func F(x int64) (r int64) { for i := x; i > 0; i-- { r = i }; return }",
            frozenset({0}),
        ),
        # A blank `_` result is unbound: explicit returns still work.
        (
            "func F(x int64) (_ int64) { return x }",
            frozenset({0}),
        ),
    ],
)
def test_named_result_dependencies(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations",
    [
        # Composite ranges are outside the fragment (the operand itself
        # cannot be expressed — including through a conversion, whose
        # result never passes a binding check inside a range clause).
        "func F(x int64) int64 { for i:=range \"ab\" { _ = i }; return x }",
        "func F(x int64) int64 { for i:=range string(x) { _ = i }; return x }",
        # Multi-valued call results stay outside the fragment.
        "func G(a int64) (int64, int64) { return a, a }\nfunc F(x int64) int64 { var y int64; x, y = G(x); return y }",
    ],
)
def test_for_shapes_stay_unsupported(go_types_helper, declarations):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available and result.return_dependencies is None
    assert result.effects == "unknown" and result.gaps


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # Reassignment replaces the binding's dependencies.
        (
            "func F(x int64) int64 { x = x+1; return x }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { y:=x; y=y+1; return y }",
            frozenset({0}),
        ),
        # A parameter reassigned from another parameter picks it up.
        (
            "func F(x, y int64) int64 { x = y; return x }",
            frozenset({1}),
        ),
        # Branch reassignments join back as may-assignments (union).
        (
            "func F(x, y int64) int64 { if x>0 { x = y }; return x }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { if x>0 { x = y } else { x = x }; return x }",
            frozenset({0, 1}),
        ),
        # Loop-body reassignments join back too (zero or many trips).
        (
            "func F(x, y int64) int64 { for i:=x; i>0; i-- { x = y }; return x }",
            frozenset({0, 1}),
        ),
        # Cross-iteration propagation: the loop-body fixed point carries
        # deps assigned on pass N into pass N+1 (Devin Review on PR #702:
        # a single pass left this as the empty set).
        (
            "func F(p int) int { x := 0; y := 0; for i := p; i > 0; i-- { x = y; y = p }; return x }",
            frozenset({0}),
        ),
        # Longer transitive chains converge too.
        (
            "func F(p int) int { a := 0; b := 0; c := 0; for i := p; i > 0; i-- { a = b; b = c; c = p }; return a }",
            frozenset({0}),
        ),
        # A branch-local let still does not escape.
        (
            "func F(x int64) int64 { if x>0 { y:=x; x = y }; return x }",
            frozenset({0}),
        ),
    ],
)
def test_scalar_reassignment_dependencies(
    go_types_helper, declarations, expected
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # Compound assignment unions the binding's current deps with the RHS.
        (
            "func F(x, y int64) int64 { x += y; return x }",
            frozenset({0, 1}),
        ),
        (
            "func F(x int64) int64 { x -= 1; return x }",
            frozenset({0}),
        ),
        (
            "func F(x, y int64) int64 { x *= y; return x }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { x <<= y; return x }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { x &^= y; return x }",
            frozenset({0, 1}),
        ),
        # Compound on a local keeps the binding's accumulated deps.
        (
            "func F(x, y int64) int64 { z:=y; z += x; return z }",
            frozenset({0, 1}),
        ),
        # Compound inside a branch still joins as a may-assignment.
        (
            "func F(x, y int64) int64 { if x>0 { x += y }; return x }",
            frozenset({0, 1}),
        ),
        # Tuple assignment is parallel: RHS reads the pre-state.
        (
            "func F(x, y int64) int64 { x, y = y, x; return x }",
            frozenset({1}),
        ),
        (
            "func F(x, y int64) int64 { x, y = y, x; return y }",
            frozenset({0}),
        ),
        (
            "func F(x, y int64) int64 { x, y = y, x+y; return y }",
            frozenset({0, 1}),
        ),
        # A blank LHS in a tuple evaluates-and-discards.
        (
            "func F(x int64) int64 { var y int64; y, _ = x, x; return y }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { var y int64; _, y = x, 0; return y }",
            frozenset(),
        ),
        # Tuple in a branch joins back.
        (
            "func F(x, y int64) int64 { if x>0 { x, y = y, x }; return x }",
            frozenset({0, 1}),
        ),
    ],
)
def test_assignment_forms_dependencies(
    go_types_helper, declarations, expected
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # Expression switch: clause bodies join as may-execute alternatives.
        (
            "func F(x int64) int64 { y:=x; switch x { case 1: y = y+1; case 2: y = y }; return y }",
            frozenset({0}),
        ),
        # No tag at all — guards only.
        (
            "func F(x, y int64) int64 { switch { case x>0: x = y }; return x }",
            frozenset({0, 1}),
        ),
        # Reassignment in one clause, default clause, param from guard space.
        (
            "func F(x, y int64) int64 { switch x { case 1, 2: x = y; default: x = x }; return x }",
            frozenset({0, 1}),
        ),
        # A clause-local let does not escape to siblings or after the switch.
        (
            "func F(x int64) int64 { switch x { case 1: z:=x; x = z }; return x }",
            frozenset({0}),
        ),
        # Return inside a clause unions like any other syntactic return.
        (
            "func F(x, y int64) int64 { switch x { case 1: return y }; return x }",
            frozenset({0, 1}),
        ),
        # Switch nested inside a loop body joins through the fixed point.
        (
            "func F(p int) int { x := 0; y := 0; for i := p; i > 0; i-- { switch i { case 1: x = y; default: y = p } }; return x }",
            frozenset({0}),
        ),
    ],
)
def test_expression_switch_dependencies(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations",
    [
        # Unsupported switch initializer shapes stay outside the fragment.
        "func G(v int64) (int64,int64) { return v,v }\nfunc F(x int64) int64 { switch v,w:=G(x); v { case 1: return v+w }; return x }",
        "func G(v int64) { _ = v }\nfunc F(x int64) int64 { switch G(x); x { case 1: return x }; return x }",
        # select is unmodelled concurrency.
        "func F(x int64) int64 { select {}; return x }",
        # A switch with an unsupported statement inside a clause is a gap.
        "func F(x int64) int64 { switch x { case 1: y := 0; _ = y; defer func(){}() }; return x }",
    ],
)
def test_switch_shapes_stay_unsupported(go_types_helper, declarations):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available
    assert result.gaps


@pytest.mark.parametrize(
    ("declarations", "expected"),
    [
        # A terminal fallthrough runs the next clause's body in the same
        # scope — `y = z` executes unconditionally after `y = 0` here.
        (
            "func F(x, z int64) int64 { y := x; switch x { case 1: y = 0; fallthrough; case 2: y = z; default: }; return y }",
            frozenset({0, 1}),
        ),
        # The fallthrough chain extends across several clauses.
        (
            "func F(x, z int64) int64 { y := x; switch x { case 1: fallthrough; case 2: y = x; fallthrough; case 3: y = z }; return y }",
            frozenset({0, 1}),
        ),
        # A conditional break before fallthrough keeps the continuation's
        # writes conditional — `y = z` may not replace `y = x`.
        (
            "func F(x, z int64) int64 { y := x; switch x { case 1: y = x; if x > 0 { break }; y = 0; fallthrough; case 2: y = z }; return y }",
            frozenset({0, 1}),
        ),
        # Fallthrough into default is legal when default is not last —
        # `case 2` alone leaves `y` at its entry dependency.
        (
            "func F(x, z int64) int64 { y := x; switch x { case 1: y = x; fallthrough; default: y = z; case 2: _ = x }; return y }",
            frozenset({0, 1}),
        ),
        # A bare `fallthrough` clause falls straight into the next body.
        (
            "func F(x int64) int64 { switch x { case 1: fallthrough; default: return x }; return x }",
            frozenset({0}),
        ),
        # An empty clause beside a fallthrough chain stays admitted.
        (
            "func F(x int64) int64 { y := x; switch x { case 1: case 2: fallthrough; default: return y }; return y }",
            frozenset({0}),
        ),
        # A switch initializer and fallthrough compose.
        (
            "func F(x, z int64) int64 { y := x; switch v := x; v { case 1: y = 0; fallthrough; case 2: y = v + z }; return y }",
            frozenset({0, 1}),
        ),
        # A clause reached by fallthrough can also be matched directly —
        # the direct path skips the preceding clause's writes, so `y`
        # keeps its entry dependency on `x`.
        (
            "func F(x int64) int64 { y := x; switch x { case 1: y = 0; fallthrough; case 2: return y }; return y }",
            frozenset({0}),
        ),
        (
            "func F(x, z int64) int64 { y := x; switch x { case 1: y = 0; fallthrough; case 2: y = z; fallthrough; case 3: return y }; return y }",
            frozenset({0, 1}),
        ),
    ],
)
def test_expression_switch_fallthrough(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available
    assert result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # var with an explicit scalar type and one value.
        (
            "func F(x int64) int64 { var y int64 = x+1; return y }",
            frozenset({0}),
        ),
        # var with inferred scalar type.
        (
            "func F(x int64) int64 { var y = x; return y }",
            frozenset({0}),
        ),
        # var without a value binds the dep-free zero value.
        (
            "func F(x int64) int64 { var y int64; return y }",
            frozenset(),
        ),
        # Zero value then reassigned — replace, like lets.
        (
            "func F(x int64) int64 { var y int64; y = x; return y }",
            frozenset({0}),
        ),
        # A var declared in a branch does not escape.
        (
            "func F(x int64) int64 { if x>0 { var y int64 = x; x = y }; return x }",
            frozenset({0}),
        ),
        # Boolean vars bind too.
        (
            "func F(x int64, b bool) bool { var c bool = b; return c }",
            frozenset({1}),
        ),
        # Multi-name specs bind name-wise like `:=`.
        (
            "func F(x, y int64) int64 { var a, b int64 = x, y; return a + b }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { var a, b = x, y; _ = a; return b }",
            frozenset({1}),
        ),
        # `var a, b T` without values is the dep-free zero value.
        (
            "func F(x int64) int64 { var a, b int64; return a + b }",
            frozenset(),
        ),
        (
            "func F(x int64) int64 { var _, a = 0, x; return a }",
            frozenset({0}),
        ),
    ],
)
def test_var_declaration_dependencies(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations",
    [
        # Multi-value calls stay outside the fragment — one RHS
        # expression can never supply two declared names here.
        (
            "func G(x int64) (int64, int64) { return x, x }; "
            "func F(x int64) int64 { a, b := G(x); _ = b; return a }"
        ),
        (
            "func G(x int64) (int64, int64) { return x, x }; "
            "func F(x int64) int64 { var a, b int64 = G(x); _ = b; return a }"
        ),
        # Non-scalar names in a declaration are unavailable.
        "func F(x int64) int64 { a, b := x, \"s\"; _ = b; return a }",
        "func F(x int64) int64 { var a, b string; _ = a; _ = b; return x }",
        # Non-scalar var bindings are unavailable.
        "func F(x int64) int64 { var s string; _ = s; return x }",
        # Grouped `var (...)` is a parser gap (tree-sitter has_error).
        "func F(x int64) int64 { var ( a int64 = x; b = x ); return a+b }",
    ],
)
def test_var_declaration_shapes_stay_unsupported(
    go_types_helper, declarations
):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available
    assert result.gaps


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # inc/dec statements preserve the operand's dependencies.
        (
            "func F(x int64) int64 { x++; x--; return x }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { y:=x; y++; return y }",
            frozenset({0}),
        ),
        # Unlabelled break/continue inside a loop are effect-free.
        (
            "func F(x int64) int64 { for i:=x; i>0; i-- { if i>0 { break }; continue }; return x }",
            frozenset({0}),
        ),
        # break inside a switch clause is unlabelled control flow too.
        (
            "func F(x int64) int64 { switch x { case 1: break }; return x }",
            frozenset({0}),
        ),
        # inc on a var-declared binding.
        (
            "func F(x int64) int64 { var y int64; y++; y = x; y++; return y }",
            frozenset({0}),
        ),
        # Blank assignment evaluates and discards — no deps reach the result.
        (
            "func F(x, y int64) int64 { _ = y; return x }",
            frozenset({0}),
        ),
        (
            "func F(x, y int64) int64 { _ = x+y; return y }",
            frozenset({1}),
        ),
    ],
)
def test_effect_free_control_statements(
    go_types_helper, declarations, expected
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # An `if` initializer binds like a let, scoped to the statement.
        (
            "func F(x int64) int64 { if v := x; v > 0 { return v }; return 0 }",
            frozenset({0}),
        ),
        # The initializer can also reassign an outer binding.
        (
            "func F(x int64) int64 { var y int64; if y = x; y > 0 { return y }; return 0 }",
            frozenset({0}),
        ),
        # inc/dec is a simple statement too — dependency-preserving.
        (
            "func F(x int64) int64 { if x++; x > 0 { return x }; return 0 }",
            frozenset({0}),
        ),
        # A switch initializer's binding is visible to the tag and cases.
        (
            "func F(x int64) int64 { switch v := x; v { case 1: return v; default: return 0 } }",
            frozenset({0}),
        ),
        # A tagless switch with an initializer works the same way.
        (
            "func F(x int64) int64 { switch v := x; { case v > 0: return v; default: return 0 } }",
            frozenset({0}),
        ),
        # An inc/dec switch initializer keeps the operand's deps.
        (
            "func F(x int64) int64 { switch x++; x { case 1: return x; default: return 0 } }",
            frozenset({0}),
        ),
        # A name bound by an initializer is scoped to the statement — it
        # shadows, never overwrites, an outer binding of the same name.
        (
            "func F(x int64) int64 { var v int64; if v := x; v > 0 {}; return v }",
            frozenset(),
        ),
        (
            "func F(x int64) int64 { var v int64; switch v := x; v { case 1: v = 0 }; return v }",
            frozenset(),
        ),
        # An initializer that reassigns an outer binding still joins back.
        (
            "func F(x int64) int64 { var y int64; if y = x; y > 0 {}; return y }",
            frozenset({0}),
        ),
        # The bound name is visible in the switch tag itself.
        (
            "func F(x int64) int64 { switch v := x > 0; v { case true: return x; default: return 0 } }",
            frozenset({0}),
        ),
        # Initializers accept multi-name declarations too.
        (
            "func F(x, y int64) int64 { if a, b := x, y; b > 0 { return a + b }; return 0 }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { switch a, b := x, y; b { case 1: return a + b; default: return 0 } }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { for a, b := x, y; b > 0; b-- { _ = a }; return x }",
            frozenset({0}),
        ),
    ],
)
def test_statement_initializers(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # A same-width conversion is dep-preserving.
        (
            "func F(x int64) int64 { return int64(x) }",
            frozenset({0}),
        ),
        # A widening conversion keeps the operand's deps.
        (
            "func F(x int64, y int32) int64 { return x + int64(y) }",
            frozenset({0, 1}),
        ),
        # Signedness changes too.
        (
            "func F(x int64) uint64 { return uint64(x) }",
            frozenset({0}),
        ),
        # A converted value flows through a let binding.
        (
            "func F(x int64) int64 { y := int32(x); return int64(y) }",
            frozenset({0}),
        ),
        # Nested conversions.
        (
            "func F(x int64) int64 { return int64(int32(x)) }",
            frozenset({0}),
        ),
        # A conversion of a call result keeps the call's deps.
        (
            "func G(a int64) int64 { return a }\nfunc F(x int64) int64 { return int64(G(x)) }",
            frozenset({0}),
        ),
        # Conversion inside a statement initializer.
        (
            "func F(x int64, y int32) int64 { if v := int64(y); v > 0 { return v }; return x }",
            frozenset({1, 0}),
        ),
        # A conversion inside a for-clause initializer.
        (
            "func F(x int64) int64 { for i:=int64(0); i<x; i++ {}; return x }",
            frozenset({0}),
        ),
    ],
)
def test_scalar_conversion_dependencies(
    go_types_helper, declarations, expected
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected


@pytest.mark.parametrize(
    "declarations",
    [
        # Converting to an unsupported target type fails closed at the
        # binding, not the conversion.
        "func F(x int64) int64 { var s string = string(0); _ = s; return x }",
        # An impure builtin is still an opaque call.
        "func G() int64 { return 0 }\nfunc F(x int64) int64 { panic(0); return x }",
    ],
)
def test_scalar_conversion_shapes_stay_unsupported(
    go_types_helper, declarations
):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available
    assert result.gaps


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # min/max union every argument's dependencies.
        (
            "func F(x, y int64) int64 { return min(x, y) }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { return max(x, 0, y) }",
            frozenset({0, 1}),
        ),
        # A nested call inside min keeps the callee's deps.
        (
            "func G(a int64) int64 { return a }\nfunc F(x, y int64) int64 { return min(G(x), y) }",
            frozenset({0, 1}),
        ),
        # min inside a statement initializer.
        (
            "func F(x, y int64) int64 { if v := min(x, y); v > 0 { return v }; return 0 }",
            frozenset({0, 1}),
        ),
        # Parenthesized callees are still the same builtin.
        (
            "func F(x, y int64) int64 { return (min)(x, y) }",
            frozenset({0, 1}),
        ),
        (
            "func F(x, y int64) int64 { return ((max))(x, y) }",
            frozenset({0, 1}),
        ),
    ],
)
def test_pure_builtin_dependencies(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected


@pytest.mark.parametrize(
    "declarations",
    [
        # panic and other impure/effectful builtins stay opaque.
        "func F(x int64) int64 { panic(x); return x }",
        "func F(x int64) int64 { return int64(real(1)) }",
        # len/cap are not in the admitted set — their operands cannot be
        # bound in the scalar fragment anyway.
        "func F(x int64) int64 { return int64(len(\"ab\")) + x }",
        "func F(x int64) int64 { return int64(cap([3]int64{1, 2, 3})) }",
        # `make` is allocation of a composite value — still opaque.
        "func F(x int64) int64 { _ = make([]int64, 2); return x }",
    ],
)
def test_impure_builtins_stay_opaque(go_types_helper, declarations):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available
    assert result.gaps


@pytest.mark.parametrize(
    "declarations",
    [
        # Labelled jumps stay unmodelled.
        "func F(x int64) int64 { L: for i:=x; i>0; i-- { break L }; return x }",
        "func F(x int64) int64 { L: for i:=x; i>0; i-- { continue L }; return x }",
        # goto is unmodelled.
        "func F(x int64) int64 { goto L; L: return x }",
        # defer/go are effect-bearing and stay outside the fragment.
        "func F(x int64) int64 { defer F(0); return x }",
        "func F(x int64) int64 { go F(0); return x }",
        # inc/dec on a non-identifier operand is outside the fragment.
        "func F(x int64) int64 { a := [1]int64{x}; a[0]++; return x }",
    ],
)
def test_control_statement_shapes_stay_unsupported(
    go_types_helper, declarations
):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available
    assert result.gaps


@pytest.mark.parametrize(
    "declarations,expected",
    [
        # A break may skip the rest of the loop body — writes after it are
        # may-assignments and union instead of replacing the deps the
        # taken path kept.
        (
            "func F(x int64) int64 { var y int64; for { y = x; break; y = 0 }; return y }",
            frozenset({0}),
        ),
        (
            "func F(x int64) int64 { var y int64; for { y = x; continue; y = 0 }; return y }",
            frozenset({0}),
        ),
        (
            "func F(x, c int64) int64 { var y int64; for i:=c; i>0; i-- { y = x; if i>0 { break }; y = 0 }; return y }",
            frozenset({0}),
        ),
        # A break inside a switch clause skips only the clause tail.
        (
            "func F(x int64) int64 { var y int64; switch x { case 0: y = x; break; y = 0 }; return y }",
            frozenset({0}),
        ),
        # continue inside a switch clause targets the enclosing loop and
        # skips the rest of the loop body too.
        (
            "func F(x int64) int64 { var y int64; for { y = x; switch x { case 0: continue }; y = 0 }; return y }",
            frozenset({0}),
        ),
        # An inner loop consumes its own break — the outer body's tail is
        # still unconditional and replaces dependencies.
        (
            "func F(x int64) int64 { var y int64; for { y = x; for { break }; y = 0 }; return y }",
            frozenset(),
        ),
        # A switch break is consumed by the switch — the statement after
        # it in the loop body is unconditional.
        (
            "func F(x int64) int64 { var y int64; for { y = x; switch x { case 0: break }; y = 0 }; return y }",
            frozenset(),
        ),
        # Writes after a possible exit union with the value they keep.
        (
            "func F(x int64) int64 { var y int64; for { if x>0 { break }; y = x }; return y }",
            frozenset({0}),
        ),
        # A conditional write keeps the binding's CURRENT value — a
        # parameter's original deps do not revive once it was reassigned.
        (
            "func F(x int64) int64 { x = 1; for { break; x = 0 }; return x }",
            frozenset(),
        ),
    ],
)
def test_unlabelled_jumps_make_later_writes_may_assignments(
    go_types_helper, declarations, expected
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected


def test_callee_summary_is_not_polluted_by_caller_exit_state(
    go_types_helper,
):
    # F analyzes G mid-expression while F's loop frame is exited; G's own
    # summary must still be unconditional — its cached result cannot
    # depend on which caller state happened to run first.
    source, snapshot, summaries = unit(
        go_types_helper,
        "func F(x int64) int64 { var y int64; for { y = x; break; _ = G(x) }; return y };"
        "func G(a int64) int64 { v := a; v = 0; return v }",
    )
    g = named(source, snapshot, summaries, name="G")
    assert g.available and g.return_dependencies == frozenset()


@pytest.mark.parametrize(
    "declarations",
    [
        # An unsupported if initializer propagates the gap.
        "func F(x int64) int64 { if y:=1.5; y>0 {return x}; return 0 }",
        # An unsummarizable callee in an initializer stays a gap.
        "func G(v int64) { _ = v }\nfunc F(x int64) int64 { if G(x); x>0 {return x}; return 0 }",
        # A for loop with a multi-value init is not modelled.
        "func G(v int64) (int64,int64) { return v,v }\nfunc F(x int64) int64 { for i,j:=G(x); i<x; i++ { _ = j }; return x }",
        # A branch with an unsupported statement blocks the summary.
    ],
)
def test_branch_shapes_stay_unsupported(go_types_helper, declarations):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available and result.return_dependencies is None
    assert result.effects == "unknown" and result.gaps


@pytest.mark.parametrize(
    "declarations",
    [
        # Tuple declarations fed by a multi-value call stay outside.
        "func G(v int64) (int64,int64) { return v,v }\nfunc F(x int64) int64 { y,z:=G(x); return y+z }",
        # A call statement to an unsummarizable callee keeps its gap.
        "func G(){}; func F(x int64) int64 { G(); return x }",
        # Legal statement-position builtins outside the fragment keep
        # their gaps — only min/max are admitted builtins.
        "func F(x int64) int64 { print(x); return x }",
        # Unsupported initializer propagates the gap.
        "func F(x int64) int { y:=len(\"s\"); return y }",
    ],
)
def test_non_let_statements_stay_unsupported(go_types_helper, declarations):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available and result.return_dependencies is None
    assert result.effects == "unknown" and result.gaps


@pytest.mark.parametrize(
    "declarations,expected,expect_calls",
    [
        # A call used for its side channel still records its transfer.
        (
            "func G() int64 { return 1 }; func F(x int64) int64 { G(); return x }",
            frozenset({0}),
            True,
        ),
        (
            "func G(v int64) int64 { return v }; func F(x int64) int64 { G(x); return x }",
            frozenset({0}),
            True,
        ),
        # The call's own dependencies still resolve for the transfer.
        (
            "func G(v int64) int64 { return v }; func F(x, y int64) int64 { G(y); return x }",
            frozenset({0}),
            True,
        ),
        # Nested inside a branch — the transfer still records.
        (
            "func G() int64 { return 1 }; func F(x int64) int64 { if x > 0 { G() }; return x }",
            frozenset({0}),
            True,
        ),
        # Initializers admit the same form — `if`/`switch`/`for`.
        (
            "func G(v int64) int64 { return v }; func F(x int64) int64 { if G(x); x > 0 { return x }; return 0 }",
            frozenset({0}),
            True,
        ),
        (
            "func G(v int64) int64 { return v }; func F(x int64) int64 { switch G(x); x { case 1: return x; default: return 0 } }",
            frozenset({0}),
            True,
        ),
        (
            "func G(v int64) int64 { return v }; func F(x int64) int64 { for G(x); x > 0; x-- { }; return x }",
            frozenset({0}),
            True,
        ),
        # A parenthesized call statement is the same shape.
        (
            "func G() int64 { return 1 }; func F(x int64) int64 { (G()); return x }",
            frozenset({0}),
            True,
        ),
    ],
)
def test_expression_statements(
    go_types_helper, declarations, expected, expect_calls
):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert bool(result.calls) == expect_calls
    assert result.effects == "none_in_supported_fragment"


def test_unused_argument_is_still_evaluated_for_unsupported_effects(go_types_helper):
    result = named(
        *unit(
            go_types_helper,
            "func Ignore(x int64)int64{return 1}; func Ext(x int64)int64; func F(x int64)int64{return Ignore(Ext(x))}",
        )
    )
    assert result.return_dependencies is None and result.effects == "unknown"


def test_opaque_callee_blocks_callers_but_not_an_unrelated_function(go_types_helper):
    data = unit(
        go_types_helper,
        "var ch chan int64; func Bad(x int64)int64{return <-ch}; func F(x int64)int64{return Bad(x)}; func Good(x int64)int64{return x}",
    )
    assert not named(*data).available
    assert named(*data, "Good").available


def test_callee_replacement_invalidates_unchanged_caller(go_types_helper):
    old = unit(
        go_types_helper,
        "func Leaf(x int64)int64{return x}; func F(y int64)int64{return Leaf(y)}",
    )
    new = unit(
        go_types_helper,
        "func Leaf(x int64)int64{return 1}; func F(y int64)int64{return Leaf(y)}",
    )
    assert named(*old).return_dependencies == frozenset({0})
    assert named(*new).return_dependencies == frozenset()
    assert named(*old).key != named(*new).key
    with pytest.raises(SnapshotError):
        old[2].for_function(new[0], new[1], named(*new).binding_id)
    with pytest.raises(SnapshotError):
        ip.summarize_go(new[0], old[1])


def test_call_targets_list_recorded_callee_identities(go_types_helper):
    data = unit(
        go_types_helper,
        "func G(x int64) int64 { return x }; func F(x int64) int64 { return G(x) }",
    )
    assert named(*data).call_targets == {named(*data, "G").binding_id}
    assert named(*data, "G").call_targets == frozenset()


@pytest.mark.parametrize(
    "before,after,stale_names",
    [
        # A replaced callee's new identity invalidates its caller only.
        (
            "func G(x int64) int64 { return x }; func F(x int64) int64 { return G(x) }",
            "func G(x int64) int64 { return x + 1 }; func F(x int64) int64 { return G(x) }",
            {"F"},
        ),
        # Invalidation follows the recorded call chain — a leaf with no
        # calls is never stale.
        (
            "func H(x int64) int64 { return x }; func G(x int64) int64 { return H(x) }; func F(x int64) int64 { return G(x) }",
            "func H(x int64) int64 { return 0 }; func G(x int64) int64 { return H(x) }; func F(x int64) int64 { return G(x) }",
            {"F", "G"},
        ),
        # A deleted callee is a target absent from `known` too.
        (
            "func G(x int64) int64 { return x }; func F(x int64) int64 { return G(x) }",
            "func F(x int64) int64 { return x }",
            {"F"},
        ),
        # An unavailable caller recorded nothing and has nothing to
        # invalidate.
        (
            "func G(){}; func F(x int64) int64 { G(); return x }",
            "func G(){}; func F(x int64) int64 { G(); return x }",
            set(),
        ),
    ],
)
def test_stale_dependents(go_types_helper, before, after, stale_names):
    old = unit(go_types_helper, before)
    new = unit(go_types_helper, after)
    live = {f.binding_id for f in new[2].functions}
    assert old[2].stale_dependents(live) == {
        named(*old, name).binding_id for name in stale_names
    }
    # Nothing is stale against the snapshot that produced it.
    assert not old[2].stale_dependents(
        {f.binding_id for f in old[2].functions}
    )


@pytest.mark.parametrize(
    "change", ["compiler", "target", "metadata", "source", "profile", "language"]
)
def test_context_changes_never_reuse_a_summary(go_types_helper, change):
    source, snapshot, summaries = unit(go_types_helper, "func F(x int)int{return x}")
    if change == "compiler":
        snapshot = replace(snapshot, compiler_version="go1.27.2")
    elif change == "target":
        snapshot = replace(snapshot, target_arch="386")
    elif change == "metadata":
        snapshot = replace(snapshot, references=())
    elif change == "source":
        source += "\n// changed"
    elif change == "profile":
        snapshot = replace(snapshot, profile="unknown")
    else:
        snapshot = replace(snapshot, language_version="go1.24")
    with pytest.raises(SnapshotError):
        summaries.for_function(source, snapshot, summaries.functions[0].binding_id)


@pytest.mark.parametrize("field", ["calls", "references"])
def test_missing_resolution_is_not_an_empty_dependency_set(go_types_helper, field):
    source, snapshot, _ = unit(
        go_types_helper,
        "func Id(x int64)int64{return x};func F(y int64)int64{return Id(y)}",
    )
    snapshot = replace(snapshot, **{field: ()})
    result = named(source, snapshot, ip.summarize_go(source, snapshot))
    assert result.return_dependencies is None and not result.available


def test_analysis_limits_fail_closed(go_types_helper, monkeypatch):
    source, snapshot, _ = unit(
        go_types_helper,
        "func Id(x int64)int64{return x};func F(y int64)int64{return Id(y)}",
    )
    monkeypatch.setattr(ip, "MAX_FUNCTIONS", 1)
    for result in ip.summarize_go(source, snapshot).functions:
        assert not result.available and result.gaps[0].reason == "analysis_limit"


def test_deep_syntax_is_rejected_before_recursive_cfg_walk(go_types_helper):
    result = named(
        *unit(
            go_types_helper,
            "func F(x int64)int64{return " + "(" * 100 + "x" + ")" * 100 + "}",
        )
    )
    assert not result.available and result.gaps[0].reason == "analysis_limit"


def test_pure_reader_does_not_launch_any_process(monkeypatch):
    snapshot = load_go_snapshot(
        json.dumps(schema_fixture()).encode(), SOURCE, target_arch="amd64"
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("summarization must not execute tools")

    monkeypatch.setattr(subprocess, "run", forbidden)
    assert named(SOURCE, snapshot, ip.summarize_go(SOURCE, snapshot)).available


def test_unavailable_parser_yields_no_partial_summary(monkeypatch):
    snapshot = load_go_snapshot(
        json.dumps(schema_fixture()).encode(), SOURCE, target_arch="amd64"
    )
    monkeypatch.setattr(ip, "_syntax", lambda raw: None)
    result = named(SOURCE, snapshot, ip.summarize_go(SOURCE, snapshot))
    assert not result.available and result.return_dependencies is None


def test_literals_comments_and_tags_are_not_copied_into_summaries(
    go_types_helper, capsys
):
    fake = "FAKE_C07_LITERAL_NOT_A_SECRET_62741"
    source, snapshot, summaries = unit(
        go_types_helper,
        f'var text = "{fake}"; // {fake}\nfunc F(x int64)int64{{return x}}',
    )
    assert named(source, snapshot, summaries).available
    assert fake not in repr(summaries)
    output = capsys.readouterr()
    assert fake not in output.out + output.err


@pytest.mark.parametrize(
    "name,type_name",
    [("F", "int64"), ("true", "bool"), ("false", "bool"), ("雪", "int64")],
)
def test_shadowed_names_resolve_to_the_parameter_not_name_heuristics(
    go_types_helper, name, type_name
):
    result = named(
        *unit(
            go_types_helper, f"func F({name} {type_name}) {type_name} {{return {name}}}"
        )
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_failed_expression_drops_earlier_partial_call_transfers(go_types_helper):
    result = named(
        *unit(
            go_types_helper,
            "func Id(x int64)int64{return x};func Ext(x int64)int64;func F(x int64)int64{return Id(x)+Ext(x)}",
        )
    )
    assert (
        not result.available
        and result.return_dependencies is None
        and result.calls == ()
    )


@pytest.mark.parametrize("change", ["owner", "arguments", "target"])
def test_missing_or_inconsistent_call_mapping_is_unknown(go_types_helper, change):
    source, snapshot, _ = unit(
        go_types_helper,
        "func Id(x int64)int64{return x};func F(x int64)int64{return Id(x)}",
    )
    call = snapshot.calls[0]
    if change == "owner":
        call = replace(call, owner="")
    elif change == "arguments":
        call = replace(call, arguments=())
    else:
        call = replace(call, target="missing")
    snapshot = replace(snapshot, calls=(call,))
    assert not named(source, snapshot, ip.summarize_go(source, snapshot)).available


def test_cfg_unavailability_is_not_a_fallback_to_syntax_only(monkeypatch):
    snapshot = load_go_snapshot(
        json.dumps(schema_fixture()).encode(), SOURCE, target_arch="amd64"
    )
    monkeypatch.setattr(
        type(snapshot),
        "cfg_for_function",
        lambda *args: control_flow.CFGConstruction(
            None, (control_flow.CFGGap("unavailable"),)
        ),
    )
    result = named(SOURCE, snapshot, ip.summarize_go(SOURCE, snapshot))
    assert not result.available and result.gaps[0].reason == "cfg_unavailable"


def test_long_acyclic_graph_and_nested_calls_stop_at_a_budget(go_types_helper):
    declarations = ";".join(
        f"func G{i}(x int64)int64{{return "
        + "(" * 10
        + (f"G{i + 1}(x)" if i < 60 else "x")
        + ")" * 10
        + "}"
        for i in range(61)
    )
    source, snapshot, summaries = unit(go_types_helper, declarations)
    assert not named(source, snapshot, summaries, "G0").available


def test_foreign_function_id_is_not_retrieved(go_types_helper):
    source, snapshot, summaries = unit(
        go_types_helper, "func F(x int64)int64{return x}"
    )
    with pytest.raises(SnapshotError):
        summaries.for_function(source, snapshot, "foreign")


def test_invalid_source_encoding_is_rejected_without_echoing_it():
    snapshot = load_go_snapshot(
        json.dumps(schema_fixture()).encode(), SOURCE, target_arch="amd64"
    )
    with pytest.raises(SnapshotError, match="encoding"):
        ip.summarize_go("\ud800", snapshot)


# --- C07 package units (cross-file freshness) ---------------------------------


def package_report(helper: Path, files: dict[str, str], arch: str = "amd64") -> bytes:
    proc = subprocess.run(
        [str(helper)],
        input=json.dumps(
            {
                "sources": [
                    {"name": name, "source": src} for name, src in files.items()
                ],
                "target_arch": arch,
            }
        ).encode(),
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert proc.stderr == b""
    return proc.stdout


def package_unit(helper: Path, files: dict[str, str], arch: str = "amd64"):
    snapshot = load_go_package_snapshot(
        package_report(helper, files, arch), files, target_arch=arch
    )
    return files, snapshot, ip.summarize_go_package(files, snapshot)


CALLEE = "package p\nfunc G(y int64) int64 { return y + 1 }\n"
CALLER = "package p\nfunc F(x int64) int64 { return G(x) }\n"


def test_cross_file_call_resolves_direct_local(go_types_helper):
    files, snapshot, summaries = package_unit(
        go_types_helper, {"a.go": CALLER, "b.go": CALLEE}
    )
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})
    (transfer,) = result.calls
    callee = snapshot.binding(transfer.target)
    assert callee.name == "G" and callee.span.file == 1


def named_package(files, snapshot, summaries, name="F"):
    fn = next(
        f for f in snapshot.functions if snapshot.binding(f.binding_id).name == name
    )
    return summaries.for_package_function(files, snapshot, fn.binding_id)


def test_callee_in_other_file_change_churns_only_its_file(go_types_helper):
    files = {"a.go": CALLER, "b.go": CALLEE}
    _, snapshot, summaries = package_unit(go_types_helper, files)
    files2 = {"a.go": CALLER, "b.go": CALLEE.replace("+ 1", "")}
    _, snapshot2, _ = package_unit(go_types_helper, files2)
    # Untouched a.go keeps every binding identity; b.go's all churn.
    ids = {b.id for b in snapshot.bindings}
    ids2 = {b.id for b in snapshot2.bindings}
    a1 = {b.id for b in snapshot.bindings if b.span.file == 0}
    a2 = {b.id for b in snapshot2.bindings if b.span.file == 0}
    assert a1 == a2
    b1 = {b.id for b in snapshot.bindings if b.span.file == 1}
    assert not (b1 & ids2)
    # F recorded a call to the old G identity — it is stale now.
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(ids2) == frozenset({f_id})


def test_package_snapshot_rejects_tampered_file_content(go_types_helper):
    files = {"a.go": CALLER, "b.go": CALLEE}
    report = package_report(go_types_helper, files)
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            report, {"a.go": CALLER + "\n", "b.go": CALLEE}, target_arch="amd64"
        )


def test_package_snapshot_rejects_missing_file(go_types_helper):
    files = {"a.go": CALLER, "b.go": CALLEE}
    report = package_report(go_types_helper, files)
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            report, {"a.go": CALLER}, target_arch="amd64"
        )


def test_package_sources_accept_list_in_declaration_order(go_types_helper):
    files = {"a.go": CALLER, "b.go": CALLEE}
    snapshot = load_go_package_snapshot(
        package_report(go_types_helper, files), files, target_arch="amd64"
    )
    summaries = ip.summarize_go_package([CALLER, CALLEE], snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})


def test_package_unit_digest_binds_every_file(go_types_helper):
    files = {"a.go": CALLER, "b.go": CALLEE}
    snapshot = load_go_package_snapshot(
        package_report(go_types_helper, files), files, target_arch="amd64"
    )
    files2 = {"a.go": CALLER, "b.go": CALLEE.replace("+ 1", "")}
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, files2), files2, target_arch="amd64"
    )
    assert snapshot.source_sha256 != snapshot2.source_sha256


def test_for_package_function_rejects_stale_unit(go_types_helper):
    files = {"a.go": CALLER, "b.go": CALLEE}
    _, snapshot, summaries = package_unit(go_types_helper, files)
    files2 = {"a.go": CALLER, "b.go": CALLEE.replace("+ 1", "")}
    _, snapshot2, _ = package_unit(go_types_helper, files2)
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    with pytest.raises(SnapshotError):
        summaries.for_package_function(files2, snapshot2, f_id)


def test_package_file_names_must_be_unique(go_types_helper):
    proc = subprocess.run(
        [str(go_types_helper)],
        input=json.dumps(
            {
                "sources": [
                    {"name": "a.go", "source": "package p\n"},
                    {"name": "a.go", "source": "package p\n"},
                ],
                "target_arch": "amd64",
            }
        ).encode(),
        capture_output=True,
        timeout=30,
        check=True,
    )
    report = json.loads(proc.stdout)
    assert report["status"] != "ok"


def test_package_producer_rejects_source_and_sources(go_types_helper):
    proc = subprocess.run(
        [str(go_types_helper)],
        input=json.dumps(
            {
                "source": "package p\n",
                "sources": [{"name": "a.go", "source": "package p\n"}],
                "target_arch": "amd64",
            }
        ).encode(),
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert json.loads(proc.stdout)["status"] != "ok"


def test_package_named_results_and_bare_return(go_types_helper):
    files = {
        "a.go": "package p\nfunc F(x int64) (r int64) { r = x; return }\n",
        "b.go": CALLEE,
    }
    _, snapshot, summaries = package_unit(go_types_helper, files)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})


def test_package_single_file_unit_matches_v1_behaviour(go_types_helper):
    # A one-file package unit still carries file-indexed spans.
    files = {"a.go": "package p\nfunc F(x int64) int64 { return x }\n"}
    _, snapshot, summaries = package_unit(go_types_helper, files)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})
    assert all(b.span.file == 0 for b in snapshot.bindings)


def test_package_gap_spans_carry_file_index(go_types_helper):
    # `import` in one file reports a gap positioned in that file — a
    # non-ok report, so the loader still fails closed on it.
    files = {
        "a.go": "package p\nimport \"fmt\"\nvar _ = fmt.Println\n"
        "func F(x int64) int64 { return x }\n",
        "b.go": CALLEE,
    }
    report = json.loads(package_report(go_types_helper, files))
    assert report["status"] != "ok"
    assert any(g["span"]["file"] == 0 for g in report["gaps"])
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            package_report(go_types_helper, files), files, target_arch="amd64"
        )


def test_package_summary_rejects_missing_source_without_leaking(go_types_helper):
    files = {"a.go": CALLER, "b.go": CALLEE}
    _, snapshot, _ = package_unit(go_types_helper, files)
    with pytest.raises(SnapshotError):
        ip.summarize_go_package({"a.go": CALLER}, snapshot)


def test_package_for_function_rejects_unknown_binding_id(go_types_helper):
    files = {"a.go": CALLER, "b.go": CALLEE}
    _, snapshot, summaries = package_unit(go_types_helper, files)
    with pytest.raises(SnapshotError):
        summaries.for_package_function(files, snapshot, "sha256:foreign")


def test_package_bodyless_function_cfg_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nfunc F(x int64) int64\nfunc A(x int64) int64 { return x }\n",
        "b.go": CALLEE,
    }
    report = package_report(go_types_helper, files)
    snapshot = load_go_package_snapshot(report, files, target_arch="amd64")
    fn = next(
        f for f in snapshot.functions if snapshot.binding(f.binding_id).name == "F"
    )
    assert fn.body is None
    construction = snapshot.cfg_for_function(files, fn.binding_id)
    assert construction.graph is None


@pytest.mark.parametrize("mode", ["dict", "list"])
def test_package_sources_must_be_exactly_the_declared_unit(
    go_types_helper, mode
):
    files = {"a.go": CALLER, "b.go": CALLEE}
    _, snapshot, _ = package_unit(go_types_helper, files)
    extra = "package p\nfunc H(z int64) int64 { return z }\n"
    if mode == "dict":
        sources = {**files, "c.go": extra}
    else:
        sources = [CALLER, CALLEE, extra]
    with pytest.raises(SnapshotError):
        ip.summarize_go_package(sources, snapshot)
    with pytest.raises(SnapshotError):
        snapshot.cfg_for_function(sources, snapshot.functions[0].binding_id)


# --- C06 host-declared import resolution --------------------------------------


def package_report_imports(
    helper: Path,
    files: dict[str, str],
    imports: dict[str, dict[str, str]],
    arch: str = "amd64",
) -> bytes:
    proc = subprocess.run(
        [str(helper)],
        input=json.dumps(
            {
                "sources": [
                    {"name": name, "source": src} for name, src in files.items()
                ],
                "imports": [
                    {
                        "path": path,
                        "sources": [
                            {"name": name, "source": src}
                            for name, src in srcs.items()
                        ],
                    }
                    for path, srcs in imports.items()
                ],
                "target_arch": arch,
            }
        ).encode(),
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert proc.stderr == b""
    return proc.stdout


IMPORTER = "package p\nimport \"lib\"\nfunc F(x int64) int64 { return lib.G(x) }\n"
LIB = {"lib": {"g.go": "package lib\nfunc G(y int64) int64 { return y + 1 }\n"}}


def lib_g_identity(helper: Path, lib: dict[str, str]) -> str:
    report = package_report(helper, lib)
    data = json.loads(report)
    return next(b["id"] for b in data["bindings"] if b["name"] == "G")


def test_imported_call_records_the_callees_own_identity(go_types_helper):
    report = json.loads(
        package_report_imports(go_types_helper, {"a.go": IMPORTER}, LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import"
    assert call["target"] == lib_g_identity(go_types_helper, LIB["lib"])


def test_imported_call_transfer_and_cross_package_staleness(go_types_helper):
    files = {"a.go": IMPORTER}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})
    (transfer,) = result.calls
    assert transfer.target not in {b.id for b in snapshot.bindings}
    lib2 = {"g.go": "package lib\nfunc G(y int64) int64 { return y + 2 }\n"}
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot2.bindings}
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_undeclared_import_fails_closed(go_types_helper):
    files = {"a.go": IMPORTER}
    report = json.loads(package_report(go_types_helper, files))
    assert report["status"] != "ok"
    assert any(g["reason"] == "unresolved_import" for g in report["gaps"])
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            package_report(go_types_helper, files), files, target_arch="amd64"
        )


def test_uncompilable_import_fails_closed(go_types_helper):
    files = {"a.go": IMPORTER}
    bad = {"lib": {"g.go": "package lib\nfunc G( {\n"}}
    report = json.loads(package_report_imports(go_types_helper, files, bad))
    assert report["status"] != "ok"
    assert any(g["reason"] == "unresolved_import" for g in report["gaps"])


def test_import_cycle_fails_closed(go_types_helper):
    files = {"a.go": "package p\nimport \"a\"\nvar _ = a.V\n"}
    imports = {
        "a": {"a.go": "package a\nimport \"b\"\nvar V = b.V\n"},
        "b": {"b.go": "package b\nimport \"a\"\nvar V = a.V\n"},
    }
    report = json.loads(package_report_imports(go_types_helper, files, imports))
    assert report["status"] != "ok"


def test_named_and_dot_imports_resolve(go_types_helper):
    files = {
        "a.go": "package p\nimport l \"lib\"\nimport . \"other\"\n"
        "func F(x int64) int64 { return l.G(x) + H(x) }\n"
    }
    imports = {
        "lib": {"g.go": "package lib\nfunc G(y int64) int64 { return y + 1 }\n"},
        "other": {"h.go": "package other\nfunc H(y int64) int64 { return y * 2 }\n"},
    }
    report = json.loads(package_report_imports(go_types_helper, files, imports))
    assert report["status"] == "ok"
    kinds = {c["kind"] for c in report["calls"]}
    assert kinds == {"direct_import"}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, imports),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})
    assert len(result.calls) == 2


def test_imported_member_references_carry_import_kind(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "var _ = lib.V\nvar _ = lib.K\nvar _ lib.T\n"
        "func F(x int64) int64 { return x }\n"
    }
    lib = {
        "lib": {
            "g.go": "package lib\nvar V = 1\nconst K = 2\ntype T int64\n"
        }
    }
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    assert report["status"] == "ok"
    import_refs = [r for r in report["references"] if r["kind"] == "import"]
    assert len(import_refs) == 3
    assert all(b["name"] != "lib" for b in report["bindings"])
    load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )


def test_transitive_imports_resolve_through_the_same_map(go_types_helper):
    files = {"a.go": "package p\nimport \"a\"\nfunc F(x int64) int64 { return a.G(x) }\n"}
    imports = {
        "a": {"a.go": "package a\nimport \"b\"\nfunc G(y int64) int64 { return b.H(y) }\n"},
        "b": {"b.go": "package b\nfunc H(z int64) int64 { return z }\n"},
    }
    report = json.loads(package_report_imports(go_types_helper, files, imports))
    assert report["status"] == "ok"
    (call,) = [c for c in report["calls"] if c["kind"] == "direct_import"]
    assert call["target"].startswith("sha256:")


def test_imports_require_package_mode(go_types_helper):
    proc = subprocess.run(
        [str(go_types_helper)],
        input=json.dumps(
            {
                "source": "package p\n",
                "imports": [{"path": "lib", "sources": LIB["lib"]}],
                "target_arch": "amd64",
            }
        ).encode(),
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert json.loads(proc.stdout)["status"] == "invalid_request"


@pytest.mark.parametrize(
    "imports",
    [
        [{"path": "", "sources": [{"name": "g.go", "source": "package l\n"}]}],
        [
            {"path": "lib", "sources": [{"name": "g.go", "source": "package l\n"}]},
            {"path": "lib", "sources": [{"name": "h.go", "source": "package l\n"}]},
        ],
        [{"path": "lib", "sources": []}],
        [
            {
                "path": "lib",
                "sources": [
                    {"name": "g.go", "source": "package l\n"},
                    {"name": "g.go", "source": "package l\n"},
                ],
            }
        ],
    ],
)
def test_import_declarations_validate_like_units(go_types_helper, imports):
    proc = subprocess.run(
        [str(go_types_helper)],
        input=json.dumps(
            {
                "sources": [{"name": "a.go", "source": "package p\n"}],
                "imports": imports,
                "target_arch": "amd64",
            }
        ).encode(),
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert json.loads(proc.stdout)["status"] == "invalid_request"


def test_imported_identities_follow_the_imported_unit_not_the_caller(
    go_types_helper,
):
    files = {"a.go": IMPORTER}
    first = json.loads(package_report_imports(go_types_helper, files, LIB))
    (target1,) = [c["target"] for c in first["calls"]]
    files2 = {"a.go": IMPORTER + "func A() int64 { return 0 }\n"}
    second = json.loads(package_report_imports(go_types_helper, files2, LIB))
    (target2,) = [
        c["target"] for c in second["calls"] if c["kind"] == "direct_import"
    ]
    assert target1 == target2
    lib2 = {"lib": {"g.go": "package lib\nfunc G(y int64) int64 { return y + 9 }\n"}}
    third = json.loads(package_report_imports(go_types_helper, files, lib2))
    (target3,) = [c["target"] for c in third["calls"]]
    assert target3 != target1


def test_imported_call_result_unions_argument_dependencies(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x, y int64) int64 { return lib.G(x, y) + x }\n"
    }
    lib = {"lib": {"g.go": "package lib\nfunc G(a, b int64) int64 { return a }\n"}}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0, 1})
    (transfer,) = result.calls
    assert transfer.result == frozenset({0, 1})


def test_zero_argument_import_call(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.H() + x }\n"
    }
    lib = {"lib": {"h.go": "package lib\nfunc H() int64 { return 7 }\n"}}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})
    (transfer,) = result.calls
    assert transfer.result == frozenset()


def test_direct_import_is_not_a_call_gap(go_types_helper):
    report = json.loads(
        package_report_imports(go_types_helper, {"a.go": IMPORTER}, LIB)
    )
    assert not any(
        g["reason"] == "call_not_summarized_direct_import" for g in report["gaps"]
    )


def test_single_file_loader_rejects_import_kinds():
    data = schema_fixture()
    data["calls"] = [
        {
            "span": {"start": 0, "end": 5},
            "arguments": [],
            "owner": "",
            "target": "sha256:" + "0" * 64 + ":0:1:0:0",
            "kind": "direct_import",
        }
    ]
    with pytest.raises(SnapshotError):
        load_go_snapshot(json.dumps(data).encode(), SOURCE, target_arch="amd64")
    data = schema_fixture()
    data["references"] = [
        {"span": {"start": 0, "end": 1}, "binding_id": "", "kind": "import"}
    ]
    with pytest.raises(SnapshotError):
        load_go_snapshot(json.dumps(data).encode(), SOURCE, target_arch="amd64")


def test_package_loader_rejects_import_target_pointing_at_local(go_types_helper):
    files = {"a.go": IMPORTER}
    report = json.loads(package_report_imports(go_types_helper, files, LIB))
    local = next(b["id"] for b in report["bindings"] if b["kind"] == "function")
    report["calls"][0]["target"] = local
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(report).encode(), files, target_arch="amd64"
        )
    report = json.loads(package_report_imports(go_types_helper, files, LIB))
    report["calls"][0]["target"] = "sha256:nothex:0:1:0:0"
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(report).encode(), files, target_arch="amd64"
        )


def test_package_loader_rejects_import_reference_to_local(go_types_helper):
    files = {"a.go": IMPORTER}
    report = json.loads(package_report_imports(go_types_helper, files, LIB))
    ref = next(r for r in report["references"] if r["kind"] == "import")
    ref["binding_id"] = next(b["id"] for b in report["bindings"])
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(report).encode(), files, target_arch="amd64"
        )


def test_imported_call_marks_effects_unknown(go_types_helper):
    files = {"a.go": IMPORTER}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.effects == "unknown"
    assert result.calls[0].imported


def test_composite_import_result_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\tfor range lib.S() { x++ }\n"
        "\treturn x\n}\n"
    }
    lib = {
        "lib": {"s.go": "package lib\nfunc S() []int64 { return nil }\n"}
    }
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "external_or_bodyless"
    assert any(
        g["reason"] == "call_not_summarized_external_or_bodyless"
        for g in report["gaps"]
    )
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert not result.available


MULTI_LIB = {
    "lib": {
        "g.go": "package lib\n"
        "func G(y int64) (int64, int64) { return y, y }\n"
        "func H(a int64) (int64, bool) { return a, true }\n"
        "func W(a int64, b int64) int64 { return a + b }\n"
        "func GI[P any](x P) (P, P) { return x, x }\n"
        "func GI2[P any, Q any](x P, y Q) (P, Q) { return x, y }\n"
        "func GC[P any](x P) (P, []P) { return x, nil }\n"
        "func Id[P any](x P) P { return x }\n"
        "type NT int64\n"
    }
}


def _multi_snapshot_for(go_types_helper, files):
    return load_go_package_snapshot(
        package_report_imports(go_types_helper, files, MULTI_LIB),
        files,
        target_arch="amd64",
    )


def test_multi_result_import_call_declares_arity(go_types_helper):
    # A multi-valued imported callee is `direct_import` like any other
    # admitted call — the record additionally declares its result arity
    # so the consumer can admit tuple unpacking.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ty, z := lib.G(x)\n"
        "\treturn y + z\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["results"] == 2
    members = {m["name"]: m for m in report["imported_members"]}
    assert call["target"] == members["G"]["id"]
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    # Both results carry the same over-approximated set — the union of
    # every argument — so `y + z` returns exactly the parameter's deps.
    assert result.available and result.return_dependencies == frozenset({0})
    (transfer,) = result.calls
    assert transfer.imported


def test_multi_result_unpack_in_var_and_assignment(go_types_helper):
    # `var a, b = lib.G(x)` and `c, d = lib.G(x)` take the same tuple
    # unpacking as `:=`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\tvar a, b = lib.G(x)\n"
        "\tvar c, d int64\n"
        "\tc, d = lib.G(a)\n"
        "\treturn b + c + d\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    assert all(
        c["kind"] == "direct_import" and c["results"] == 2
        for c in report["calls"]
    )
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_multi_result_unpack_discard_and_mixed_results(go_types_helper):
    # `_, b := lib.H(x)` still evaluates the whole call — the discarded
    # result contributes no binding, and a boolean result binds like an
    # integer one.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\t_, b := lib.H(x)\n"
        "\tif b { return x }\n"
        "\treturn 0\n}\n"
    }
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_multi_result_parenthesized_call_with_comment_unpacks(
    go_types_helper,
):
    # `(/* c */ lib.G(x))` — a parenthesized RHS unwraps through any
    # comments to the call: comments are named children in tree-sitter,
    # so the unwrap must skip them like `expression()` does.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ty, z := (/* pair */ lib.G(x))\n"
        "\treturn y + z\n}\n"
    }
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_results_zero_is_the_absent_equivalent(go_types_helper):
    # An explicit `"results": 0` is the omitempty default — it validates
    # on any call kind exactly like an omitted key (the same contract
    # `method: false` already follows), and a `direct_import` call with
    # arity zero behaves identically with or without it.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.W(x, x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    tampered = json.loads(json.dumps(report))
    tampered["calls"][0]["results"] = 0
    snapshot = load_go_package_snapshot(
        json.dumps(tampered).encode(), files, target_arch="amd64"
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    tampered = json.loads(json.dumps(report))
    for c in tampered["calls"]:
        c["kind"] = "conversion"
        c["target"] = ""
        c["results"] = 0
    load_go_package_snapshot(
        json.dumps(tampered).encode(), files, target_arch="amd64"
    )


def test_multi_result_arity_mismatch_stays_closed(go_types_helper):
    # `a, b := f()` admits only when the record's declared arity equals
    # the tuple width — a forged `results: 3` on a two-wide unpack must
    # fail at the consumer even though the wire shape validates.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ty, z := lib.G(x)\n"
        "\treturn y + z\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    tampered = json.loads(json.dumps(report))
    tampered["calls"][0]["results"] = 3
    snapshot = load_go_package_snapshot(
        json.dumps(tampered).encode(), files, target_arch="amd64"
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_results_field_rejected_on_non_import_kind(go_types_helper):
    # `results` only travels on a `direct_import` call, and only for
    # arity above one — every other shape must fail validation.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.W(x, x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    for forged in (1, -2, "2", True):
        tampered = json.loads(json.dumps(report))
        tampered["calls"][0]["results"] = forged
        with pytest.raises(SnapshotError):
            load_go_package_snapshot(
                json.dumps(tampered).encode(), files, target_arch="amd64"
            )
    tampered = json.loads(json.dumps(report))
    for c in tampered["calls"]:
        c["kind"] = "conversion"
        c["target"] = ""
        c["results"] = 2
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(tampered).encode(), files, target_arch="amd64"
        )


def test_multi_result_dot_imported_call_unpacks(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ty, z := G(x)\n"
        "\treturn y + z\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["results"] == 2
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_multi_result_call_discarded_statement_and_spread(go_types_helper):
    # `lib.G(x)` as a statement discards both results — the transfer
    # still records. `lib.W(lib.G(x))` spreads the pair across `W`'s two
    # parameters; the outer result unions the inner call's deps, which
    # already over-approximate every result.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\tlib.G(x)\n"
        "\treturn lib.W(lib.G(x))\n}\n"
    }
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    imported = [t for t in result.calls if t.imported]
    assert len(imported) == 3


def test_multi_result_generic_instantiation_unpacks(go_types_helper):
    # `lib.GI[int64](x)` — the instantiation gate shares the
    # all-scalar-at-any-arity rule: a two-result instantiation
    # declares `results: 2` and unpacks like a plain call. A
    # single-type-arg form parses as `type_conversion_expression`, so
    # this also covers the conversion-shaped RHS in tuple position.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ty, z := lib.GI[int64](x)\n"
        "\treturn y + z\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["results"] == 2
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_multi_result_multi_type_arg_instantiation_unpacks(
    go_types_helper,
):
    # `lib.GI2[int64, bool](x, c)` — a multi-type-arg instantiation
    # parses as `call_expression` and unpacks through the same path.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64, c bool) int64 {\n"
        "\ty, _ := lib.GI2[int64, bool](x, c)\n"
        "\treturn y\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["results"] == 2
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    # `y` carries the union of *every* argument — the opaque-callee
    # model cannot tell which result reads which parameter.
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_multi_result_dot_imported_instantiation_unpacks(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ty, z := GI[int64](x)\n"
        "\treturn y + z\n}\n"
    }
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_inferred_instantiation_unpacks(go_types_helper):
    # `lib.Id(x)` — an inferred instantiation resolves through
    # `info.Instances` exactly like the explicit `lib.Id[int64](x)`:
    # the inferred type argument is basic, so the call is admitted.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\treturn lib.Id(x)\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and "results" not in call
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_inferred_multi_result_instantiation_unpacks(go_types_helper):
    # `a, b := lib.GI(x)` — inference fills `P = int64`; the declared
    # arity unlocks tuple unpacking exactly like the explicit form.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ta, b := lib.GI(x)\n"
        "\treturn a + b\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["results"] == 2
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_inferred_dot_imported_instantiation_unpacks(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\treturn Id(x)\n}\n"
    }
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_partial_explicit_instantiation_unpacks(go_types_helper):
    # `lib.GI2[int64](x, c)` — one explicit basic type argument plus
    # one inferred basic argument is still an all-basic instance.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64, c bool) int64 {\n"
        "\ta, _ := lib.GI2[int64](x, c)\n"
        "\treturn a\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["results"] == 2
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_inferred_named_type_argument_is_pinned(go_types_helper):
    # `lib.Id(t)` with `t` declared `lib.NT` infers the *named* type
    # argument `lib.NT` — its identity rides on the call record as
    # `type_arg_type_ids` exactly like an explicit `lib.Id[lib.NT](t)`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t lib.NT) lib.NT {\n"
        "\t_ = lib.Id(t)\n"
        "\treturn t\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import"
    nt = next(m for m in report["imported_members"] if m["name"] == "NT")
    assert call["type_arg_type_ids"] == [nt["id"]]
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_inferred_composite_result_stays_closed(go_types_helper):
    # `lib.GC(x)` infers `(int64, []int64)` — a composite result at
    # any arity keeps the call closed through the inferred path too.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ta, _ := lib.GC(x)\n"
        "\treturn a\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] != "direct_import"
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_inferred_spread_instantiation_composes(go_types_helper):
    # `lib.Id(lib.Id(x))` — the inner union feeds the outer argument,
    # so no arity is needed and deps compose to the parameter's set.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\treturn lib.Id(lib.Id(x))\n}\n"
    }
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_instantiation_with_composite_result_stays_closed(go_types_helper):
    # `lib.GC[int64](x)` instantiates `(int64, []int64)` — a composite
    # result at any arity keeps the call `external_or_bodyless`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ty, _ := lib.GC[int64](x)\n"
        "\treturn y\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, MULTI_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] != "direct_import"
    snapshot = _multi_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_zero_result_import_statement_call(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { lib.D(x); return x }\n"
    }
    lib = {"lib": {"d.go": "package lib\nfunc D(y int64) {}\n"}}
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import"
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_directive_in_imported_source_fails_closed(go_types_helper):
    files = {"a.go": IMPORTER}
    bad = {
        "lib": {"g.go": "//go:build linux\npackage lib\nfunc G(y int64) int64 { return y }\n"}
    }
    report = json.loads(package_report_imports(go_types_helper, files, bad))
    assert report["status"] != "ok"
    assert any(g["reason"] == "unresolved_import" for g in report["gaps"])


# --- C06 imported member records ----------------------------------------------


IMPORTED_MEMBERS_LIB = {
    "lib": {
        "m.go": "package lib\nconst K = 2\nconst L int64 = 3\nconst S = \"s\"\n"
        "var V int64 = 7\nvar VS = \"s\"\ntype F64 float64\n"
        "var VT T = 7\nconst KT T = 5\n"
        "type A = int64\ntype GT[N int64 | int32] int64\n"
        "func G(y int64) int64 { return y }\n"
        "func FT(y T) T { return y }\n"
        "func Z() T { return 7 }\n",
        # `T` lives in its own file so a variant unit can churn `T`'s
        # identity without touching the other members' — the scenario
        # the type-identity pin exists for.
        "t.go": "package lib\ntype T int64\n",
    }
}


def test_imported_member_records_declare_referenced_objects(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.G; _ = lib.V; _ = lib.K; return x }\n"
        "var _ lib.T\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    members = {m["name"]: m for m in report["imported_members"]}
    # Only objects the unit actually names are declared.
    assert {m["kind"] for m in members.values()} == {"function", "var", "const", "type"}
    assert all(m["id"].startswith("sha256:") for m in members.values())
    assert members["K"]["type"]["kind"] == "untyped"
    assert members["V"]["type"]["kind"] == "integer"


def test_imported_scalar_const_read_is_dep_free(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.K }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


def test_imported_typed_const_read_is_dep_free(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.L }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_var_read_is_an_opaque_state_read(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.V }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    # The value derives from package state, not from a parameter — but
    # the read is not purity-proof, so effects stay `unknown`.
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    (transfer,) = result.calls
    assert transfer.imported and transfer.arguments == () and transfer.result == frozenset()
    member_ids = {m.id for m in snapshot.imported_members}
    assert transfer.target in member_ids


def test_imported_var_read_alone_has_no_dependencies(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.V }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_var_read_inside_imported_call(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.G(lib.V) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_var_read_flags_stale_dependents(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.V }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    # Regenerating the imported unit churns V's identity, so the reader
    # is flagged stale through the recorded transfer target.
    lib2 = dict(IMPORTED_MEMBERS_LIB)
    lib2["lib"] = {
        "m.go": "package lib\nconst K = 2\nconst L int64 = 3\nconst S = \"s\"\n"
        "var V int64 = 8\nvar VS = \"s\"\ntype T int64\ntype F64 float64\n"
        "type A = int64\ntype GT[N int64 | int32] int64\n"
        "func G(y int64) int64 { return y }\n"
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]), lib2["lib"], target_arch="amd64"
    )
    known = {b.id for b in snapshot2.bindings}
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_var_read_effects_propagate_through_local_calls(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func G() int64 { return lib.V }\n"
        "func F(x int64) int64 { return G() + x }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    g = named_package(files, snapshot, summaries, "G")
    assert g.effects == "unknown"
    # G's state-read opacity propagates through the local call: F cannot
    # claim bounded effects while it calls an opaque-state reader.
    f = named_package(files, snapshot, summaries, "F")
    assert f.available and f.effects == "unknown"


def test_imported_var_read_transfer_keeps_file_index(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\nvar _ = lib.K\n",
        "b.go": "package p\nimport \"lib\"\nfunc F() int64 { return lib.V }\n",
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    f = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    # The read happened in the second file — the transfer position keeps it.
    assert f.calls
    span = f.calls[0].span
    assert isinstance(span, FileSpan) and span.file == 1


def test_imported_nonscalar_var_read_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.VS; return x }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_imported_function_read_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.G; return x }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_imported_string_const_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.S; return x }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_report_without_member_section_still_loads(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.K }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    report.pop("imported_members", None)
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    # Without member declarations the same read stays unmodelled.
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_member_name_must_match_the_field_token(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.K }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    for m in report["imported_members"]:
        if m["name"] == "K":
            m["name"] = "Other"
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_member_id_must_match_the_reference(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.K }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    bogus = "sha256:" + "0" * 64 + ":0:0:0:0"
    for m in report["imported_members"]:
        m["id"] = bogus
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_malformed_member_records_fail_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.K }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    for m in report["imported_members"]:
        m["kind"] = "bogus"
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(report).encode(), files, target_arch="amd64"
        )
    report["imported_members"] = [{"id": "sha256:bad", "name": "K", "kind": "const", "type": {"kind": "integer", "basic_name": "int64", "bit_width": 64, "signed": True, "type_id": ""}}]
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(report).encode(), files, target_arch="amd64"
        )
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    report["imported_members"].append(dict(report["imported_members"][0]))
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(report).encode(), files, target_arch="amd64"
        )


def test_dot_imported_const_read_is_dep_free(go_types_helper):
    # A dot-imported `K` resolves through the same member record as
    # `lib.K` — a scalar constant read is dep-free.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return x + K }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


def test_dot_imported_typed_const_read_is_dep_free(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return x + L }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})


def test_dot_imported_var_read_is_an_opaque_state_read(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return x + V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    # The value derives from package state, not from a parameter — but
    # the read is not purity-proof, so effects stay `unknown`.
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    (transfer,) = result.calls
    assert transfer.imported and transfer.arguments == () and transfer.result == frozenset()
    member_ids = {m.id for m in snapshot.imported_members}
    assert transfer.target in member_ids


def test_dot_imported_var_read_flags_stale_dependents(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return x + V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    # Regenerating the imported unit churns V's identity, so the reader
    # is flagged stale through the recorded transfer target.
    lib2 = dict(IMPORTED_MEMBERS_LIB)
    lib2["lib"] = {
        "m.go": "package lib\nconst K = 2\nconst L int64 = 3\nconst S = \"s\"\n"
        "var V int64 = 8\nvar VS = \"s\"\ntype T int64\ntype F64 float64\n"
        "type A = int64\ntype GT[N int64 | int32] int64\n"
        "func G(y int64) int64 { return y }\n"
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]), lib2["lib"], target_arch="amd64"
    )
    known = {b.id for b in snapshot2.bindings}
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_dot_imported_const_inside_imported_call(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return G(x + K) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_dot_imported_scalar_type_conversion_is_dep_preserving(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { y := T(x); return int64(y) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


def test_dot_imported_alias_type_conversion_is_dep_preserving(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return A(x) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})


def test_dot_imported_function_read_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { _ = G; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_dot_imported_string_const_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { _ = S; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_dot_imported_nonscalar_var_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { _ = VS; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_dot_imported_nonscalar_conversion_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { _ = F64(x); return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "binding_unavailable"


def test_dot_imported_member_name_must_match(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return x + K }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    for m in report["imported_members"]:
        if m["name"] == "K":
            m["name"] = "Other"
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_dot_imported_conversion_needs_a_type_member(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { _ = T(x); return x }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    for m in report["imported_members"]:
        if m["name"] == "T":
            m["kind"] = "const"
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "binding_unavailable"


def test_dot_imported_read_without_member_section_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return x + K }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    report.pop("imported_members", None)
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "non_parameter_reference"


def test_dot_imported_generic_instantiation_fails_closed(go_types_helper):
    # `GT[int64](x)` reaches the report as a conversion whose callee is
    # an `index_expression` — instantiated generics stay closed.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { _ = GT[int64](x); return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason in {
        "binding_unavailable",
        "unsupported_expression",
    }


def test_imported_const_read_inside_imported_call(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.G(lib.K) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    # The opaque callee's result is the union of its argument deps —
    # and `lib.K` contributes none.
    assert result.available and result.return_dependencies == frozenset()


def _snapshot_for(go_types_helper, files):
    return load_go_package_snapshot(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB),
        files,
        target_arch="amd64",
    )


def test_imported_scalar_type_conversion_is_dep_preserving(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { y := lib.T(x); return int64(y) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


def test_imported_alias_type_conversion_is_dep_preserving(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.A(x) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_conversion_of_const_read_is_dep_free(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { _ = lib.T(lib.K); return 0 }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset()


def test_imported_conversion_inside_imported_call(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.G(int64(lib.T(x))) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_nonscalar_type_conversion_fails_closed(go_types_helper):
    # `type F64 float64` is a declared type member but not a scalar the
    # fragment models — the conversion stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.F64(x); return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "binding_unavailable"


def test_imported_conversion_needs_a_type_member(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.T(x); return x }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    for m in report["imported_members"]:
        if m["name"] == "T":
            m["kind"] = "const"
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "binding_unavailable"


def test_imported_conversion_member_name_must_match(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.T(x); return x }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    for m in report["imported_members"]:
        if m["name"] == "T":
            m["name"] = "Other"
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "binding_unavailable"


def test_imported_generic_type_instantiation_is_dep_preserving(go_types_helper):
    # `lib.GT[int64](x)` reaches the report as a conversion whose
    # target is a scalar-underlying imported member — admitted like
    # any `T(e)`, the operand's dependencies flow through.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.GT[int64](x); return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_conversion_without_member_section_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.T(x); return x }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB))
    assert report["status"] == "ok"
    report.pop("imported_members", None)
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert not result.available and result.gaps[0].reason == "binding_unavailable"


# --- C06 imported member type identities --------------------------------------


def test_imported_named_type_members_declare_type_identities(go_types_helper):
    # A member's declared named type is pinned to the identity the
    # imported unit's own report assigns it; basic-typed members keep no
    # identity.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.V + int64(lib.VT) + int64(lib.T(x)) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB)
    )
    assert report["status"] == "ok"
    members = {m["name"]: m for m in report["imported_members"]}
    assert members["VT"]["type"]["kind"] == "integer"
    assert members["VT"]["type"]["type_id"].startswith("sha256:")
    # A `type` member's declared fact names the type itself — the same
    # identity its member id carries.
    assert members["T"]["type"]["type_id"] == members["T"]["id"]
    # A basic-typed member keeps no identity.
    assert members["V"]["type"]["type_id"] == ""


def test_imported_var_of_named_type_read_pins_type_identity(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + int64(lib.VT) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})
    vt = next(m for m in snapshot.imported_members if m.name == "VT")
    # The unit never names `T` itself, so `T` has no member record —
    # but `VT`'s declared type still names `T`'s imported identity.
    assert all(m.name != "T" for m in snapshot.imported_members)
    assert vt.type.type_id.startswith("sha256:")
    assert result.pinned == (vt.type.type_id,)


def test_imported_typed_const_read_pins_type_identity(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + int64(lib.KT) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})
    kt = next(m for m in snapshot.imported_members if m.name == "KT")
    assert kt.type.type_id.startswith("sha256:")
    assert result.pinned == (kt.type.type_id,)
    # A dep-free read records no transfer, so effects stay bounded.
    assert result.effects == "none_in_supported_fragment"


def test_imported_scalar_conversion_pins_type_identity(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.T(x); return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})
    t = next(m for m in snapshot.imported_members if m.name == "T")
    assert result.pinned == (t.id,)


def test_dot_imported_named_type_member_read_pins_type_identity(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return x + int64(VT) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.return_dependencies == frozenset({0})
    vt = next(m for m in snapshot.imported_members if m.name == "VT")
    assert vt.type.type_id.startswith("sha256:")
    assert result.pinned == (vt.type.type_id,)


def test_basic_typed_member_read_pins_nothing(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    assert result.available and result.pinned == ()


def test_type_pin_flags_stale_dependents(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + int64(lib.VT) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    # A variant unit that shifts `T`'s declaration position without
    # touching `VT`'s file: the member's own identity is stable but the
    # pinned type identity churns, so the reader is flagged stale.
    lib2 = dict(IMPORTED_MEMBERS_LIB)
    lib2["lib"] = {
        **IMPORTED_MEMBERS_LIB["lib"],
        "t.go": "package lib\ntype  T int64\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]), lib2["lib"], target_arch="amd64"
    )
    known = {b.id for b in snapshot2.bindings}
    vt = next(m for m in snapshot.imported_members if m.name == "VT")
    vt2 = next(b for b in snapshot2.bindings if b.name == "VT")
    # The member identity is genuinely unchanged — only the pin detects.
    assert vt.id == vt2.id and vt.id in known
    assert vt.type.type_id not in known
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_type_id_naming_a_non_type_local_binding_is_rejected(go_types_helper):
    # Local binding ids share the imported-identity shape, so a `type_id`
    # that names a non-type local binding must still fail: the imported
    # clause only covers identities outside `by_id`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + int64(lib.VT) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB)
    )
    assert report["status"] == "ok"
    non_type = next(b["id"] for b in report["bindings"] if b["kind"] != "type")

    member_report = json.loads(json.dumps(report))
    for m in member_report["imported_members"]:
        if m["name"] == "VT":
            m["type"]["type_id"] = non_type
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(member_report).encode(), files, target_arch="amd64"
        )

    binding_report = json.loads(json.dumps(report))
    for b in binding_report["bindings"]:
        if b["kind"] != "type":
            b["type"]["type_id"] = non_type
            break
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(binding_report).encode(), files, target_arch="amd64"
        )


def test_imported_function_member_declares_signature_type_ids(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "    return int64(lib.FT(lib.T(x))) + int64(lib.Z()) + lib.G(x)\n"
        "}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB)
    )
    assert report["status"] == "ok"
    members = {m["name"]: m for m in report["imported_members"]}
    assert members["FT"]["signature_type_ids"] == [members["T"]["id"]]
    assert members["Z"]["signature_type_ids"] == [members["T"]["id"]]
    # Scalar signatures and non-function members carry no list at all.
    assert "signature_type_ids" not in members["G"]
    assert "signature_type_ids" not in members["T"]
    snapshot = _snapshot_for(go_types_helper, files)
    member_by_name = {m.name: m for m in snapshot.imported_members}
    assert member_by_name["FT"].signature_type_ids == (member_by_name["T"].id,)
    assert member_by_name["G"].signature_type_ids == ()


def test_direct_import_call_pins_signature_type_identities(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.Z()) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    z = next(m for m in snapshot.imported_members if m.name == "Z")
    # `lib.Z` is the only member the source names — the pin comes purely
    # from its declared signature's `T`.
    assert all(m.name != "T" for m in snapshot.imported_members)
    assert z.signature_type_ids != ()
    assert result.pinned == z.signature_type_ids


def test_direct_local_call_pins_signature_type_identities(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func G(y lib.T) int64 { return int64(y) }\n"
        "func F(x int64) int64 { return G(lib.T(x)) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    t = next(m for m in snapshot.imported_members if m.name == "T")
    assert result.pinned == (t.id,)


def test_signature_pin_flags_stale_dependents(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.Z()) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(IMPORTED_MEMBERS_LIB)
    lib2["lib"] = {
        **IMPORTED_MEMBERS_LIB["lib"],
        "t.go": "package lib\ntype  T int64\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]), lib2["lib"], target_arch="amd64"
    )
    known = {b.id for b in snapshot2.bindings}
    z = next(m for m in snapshot.imported_members if m.name == "Z")
    z2 = next(b for b in snapshot2.bindings if b.name == "Z")
    # The callee's own identity is stable — only its signature type's
    # identity churned, and the signature pin is what flags the caller.
    assert z.id == z2.id and z.id in known
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_signature_type_ids_on_non_function_member_is_rejected(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return x + lib.K }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, IMPORTED_MEMBERS_LIB)
    )
    assert report["status"] == "ok"
    bogus = "sha256:" + "0" * 64 + ":0:0:0:0"
    for m in report["imported_members"]:
        if m["kind"] != "function":
            m["signature_type_ids"] = [bogus]
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(report).encode(), files, target_arch="amd64"
        )
    # Malformed entries are rejected on function members too — this source
    # names one so the report has a function member to tamper.
    fn_files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.Z()) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, fn_files, IMPORTED_MEMBERS_LIB)
    )
    assert report["status"] == "ok"
    local = next(b["id"] for b in report["bindings"])
    for bogus_entry in ("sha256:bad", local):
        tampered = json.loads(json.dumps(report))
        for m in tampered["imported_members"]:
            if m["kind"] == "function":
                m["signature_type_ids"] = [bogus_entry]
        with pytest.raises(SnapshotError):
            load_go_package_snapshot(
                json.dumps(tampered).encode(), fn_files, target_arch="amd64"
            )


def test_stale_dependents_propagates_transitively(go_types_helper):
    # `G`'s declared parameter is `lib.T`, `H` calls `G`, and `F` calls
    # `H` — `F` names nothing imported itself. Churning `T` leaves every
    # function's own identity live: `G` and `H` flag through pins, and
    # only transitive propagation along the recorded call edge flags
    # `F`.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 { return H(x) }\n",
        "h.go": "package p\nimport \"lib\"\n"
        "func H(y int64) int64 { return G(lib.T(y)) }\n",
        "g.go": "package p\nimport \"lib\"\n"
        "func G(z lib.T) int64 { return int64(z) }\n",
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(IMPORTED_MEMBERS_LIB)
    lib2["lib"] = {
        **IMPORTED_MEMBERS_LIB["lib"],
        "t.go": "package lib\ntype  T int64\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]), lib2["lib"], target_arch="amd64"
    )
    # The host unit's own bindings are unchanged — only `lib`'s fresh
    # identities replace the recorded ones.
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    ids = {
        f.binding_id: snapshot.binding(f.binding_id).name
        for f in snapshot.functions
    }
    # `G` pins `T` through its own declared signature and `H` through
    # the admitted call and conversion; `F`'s only edge is to `H`, whose
    # identity is still live.
    assert known.issuperset(set(ids))
    f_id = next(b for b, name in ids.items() if name == "F")
    g_id = next(b for b, name in ids.items() if name == "G")
    h_id = next(b for b, name in ids.items() if name == "H")
    assert summaries.stale_dependents(known) == frozenset({f_id, g_id, h_id})


# --- C06 imported generic instantiations --------------------------------------


GENERIC_LIB = {
    "lib": {
        "g.go": "package lib\ntype T2 int64\nfunc GI[T any](v T) T { return v }\n"
        "func G2[A any, B any](a A, b B) A { return a }\n"
        "func GV[T any](v T) {}\n"
        "func GN[T any](v T2) int64 { return 0 }\n",
        "t.go": "package lib\ntype T int64\n",
    }
}


def test_imported_generic_instantiation_records_direct_import(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.GI[int64](x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import"
    members = {m["name"]: m for m in report["imported_members"]}
    assert call["target"] == members["GI"]["id"]
    # The declared signature's type-parameter identity is pinned so a
    # redeclared `GI` still flags dependents through the member pins.
    assert members["GI"]["signature_type_ids"]


def test_imported_generic_instantiation_result_depends_on_args(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.GI[int64](x) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    (transfer,) = result.calls
    assert transfer.imported and transfer.result == frozenset({0})


def test_imported_generic_instantiation_multi_type_args(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64, y int64) int64 { return lib.G2[int64, int64](x, y) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_imported_generic_instantiation_void_result(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { lib.GV[int64](x); return x }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    (transfer,) = result.calls
    # A void callee still records the call transfer; the result set is
    # the argument-dependency union even though nothing consumes it.
    assert transfer.imported and transfer.arguments == (frozenset({0}),)


def test_imported_generic_named_type_argument_is_pinned(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.GI[lib.T](lib.T(x))) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    # The named type argument's identity rides on the call record as
    # `type_arg_type_ids`, pinning `lib.T` at this call site alone.
    gi = next(c for c in report["calls"] if c["kind"] == "direct_import")
    t = next(m for m in report["imported_members"] if m["name"] == "T")
    assert gi["type_arg_type_ids"] == [t["id"]]
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_generic_inferred_call_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.GI(x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    # `info.Instances` records the inferred instantiation `GI[int64]`;
    # the all-basic inferred type argument passes the same gate an
    # explicit `lib.GI[int64](x)` does.
    assert report["calls"][0]["kind"] == "direct_import"
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_local_generic_instantiation_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\nfunc LG[T any](v T) T { return v }\n"
        "func F(x int64) int64 { return LG[int64](x) }\n"
    }
    report = json.loads(package_report(go_types_helper, files))
    assert report["status"] == "ok"
    assert report["calls"][0]["kind"] == "method_generic_or_variadic"


def test_imported_generic_declared_named_param_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.GN[int64](lib.T2(x)) }\n"
    }
    # The instantiated parameter is the declared named type `T2` — its
    # identity is already covered by the member record's signature pins,
    # so the call is admitted (only composite/substituted params are not).
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    calls = {c["kind"] for c in report["calls"]}
    assert "direct_import" in calls and "conversion" in calls
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_generic_instantiation_flags_stale_dependents(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.GI[int64](x) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {
        "g.go": "package lib\n\ntype T2 int64\nfunc GI[T any](v T) T { return v }\n"
        "func G2[A any, B any](a A, b B) A { return a }\n"
        "func GV[T any](v T) {}\n"
        "func GN[T any](v T2) int64 { return 0 }\n",
        "t.go": "package lib\ntype T int64\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    # Redeclaring `GI` at a shifted position churns the member identity —
    # the recorded call edge flags `F`.
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_dot_imported_generic_basic_instantiation_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return GI[int64](x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import"
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_dot_imported_generic_named_type_argument_is_pinned(
    go_types_helper,
):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return int64(GI[T](T(x))) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    # The unqualified instantiation admits the same way — `T` as a type
    # argument is a named identity carried on `type_arg_type_ids`.
    gi = next(c for c in report["calls"] if c["kind"] == "direct_import")
    t = next(m for m in report["imported_members"] if m["name"] == "T")
    assert gi["type_arg_type_ids"] == [t["id"]]
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


METHOD_LIB = {
    "lib": {
        "m.go": "package lib\nfunc (t T) M(v int64) int64 { return v }\n"
        "func (t T) M2(a int64, b int64) int64 { return a }\n"
        "func (t T) Bad(v int64) (int64, int64) { return v, v }\n"
        "func (t *T) PM(v int64) int64 { return v }\n"
        "func R(t *T) *T { return t }\n"
        "func RR(t *T) (int64, *T) { return 0, t }\n"
        "type I interface{ M(int64) int64 }\n"
        "type GT[P any] int64\n"
        "func (t GT[P]) GM(v int64) int64 { return v }\n"
        "func (t *GT[P]) PGM(v int64) int64 { return v }\n"
        "func (t GT[P]) MR() P { var z P; return z }\n"
        "type A = T\ntype SE struct{ GT[int64] }\n"
        "type EI struct{ I }\n"
        "type S struct{ F int64 }\n"
        "func (s *S) PF() int64 { return 0 }\n"
        "func (s S) VF() int64 { return int64(s.F) }\n"
        "var V T\nconst K T = 7\nvar PV *T\nvar VS S\n"
        "var PS *S\nvar PU *int64\nvar PPV **T\n"
        "var PA *[4]int64\n"
        "var VA []int64\nvar AA [4]int64\nvar VT []T\nvar VP []*T\n"
        "var VM map[string]int64\ntype NS []int64\nvar VNS NS\n"
        "var VSS []S\nvar VStr string\nvar V2 [][]int64\n"
        "type S2 struct{ N int64\n G string\n P *T }\nvar VS2 S2\n"
        "var VMK map[MK]int64\nvar VSM map[string]S\n"
        "var PSTR *struct{ F T }\nvar PCH *chan T\n"
        "var V2T [][]T\nvar VM2 map[string]map[string]int64\n"
        "type NS2 []int64\nvar V2NS []NS2\n",
        # `T` lives in its own file so a variant unit can churn `T`'s
        # identity without touching the method declarations.
        "t.go": "package lib\ntype T int64\n",
        # `MK` lives in its own file so a variant unit can churn the
        # map key's identity without touching `VMK`'s member id.
        "k.go": "package lib\ntype MK int64\n",
    }
}


def _method_snapshot_for(go_types_helper, files):
    return load_go_package_snapshot(
        package_report_imports(go_types_helper, files, METHOD_LIB),
        files,
        target_arch="amd64",
    )


def test_imported_method_call_records_method_direct_import(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) int64 { return x.M(y) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["method"] is True
    members = {m["name"]: m for m in report["imported_members"]}
    assert call["target"] == members["M"]["id"]
    # The member's signature pins include the receiver's named type, so
    # a `T` redeclaration flags every admitted `recv.M(...)` caller even
    # when `M`'s own identity is unchanged.
    assert members["M"]["signature_type_ids"] == [members["T"]["id"]]


def test_imported_method_result_depends_on_receiver_and_args(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) int64 { return x.M(y) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_imported_method_on_package_member_receiver(go_types_helper):
    # `lib.V.M(x)` — the receiver is a package-member read: it records
    # the var-read transfer for staleness and contributes no parameter
    # deps, so the result still depends only on the argument.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.V.M(x) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    transfers = [
        t for t in result.calls if t.imported and t.arguments == ()
    ]
    assert transfers  # the `lib.V` var read is on record


def test_imported_method_on_composite_var_receiver(go_types_helper):
    # `lib.VS.PF()` — a struct-typed imported var receiver: the
    # method reads external state, so the receiver is dep-free and
    # still records the imported transfer for staleness.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.VS.PF() + x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    vs = next(m for m in snapshot.imported_members if m.name == "VS")
    transfers = [
        t
        for t in result.calls
        if t.imported and t.arguments == () and t.target == vs.id
    ]
    assert transfers  # the `lib.VS` receiver read is on record


def test_imported_method_on_composite_var_receiver_dot_import(
    go_types_helper,
):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return VS.PF() + x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_method_on_indexed_receiver(go_types_helper):
    # `lib.VSS[0].PF()` — the receiver is a composite element of an
    # imported container: external state like the container itself,
    # dep-free apart from the (literal) index, and the transfer records
    # the container member.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VSS[0].PF() }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    vss = next(m for m in snapshot.imported_members if m.name == "VSS")
    assert any(
        t.imported and t.target == vss.id for t in result.calls
    )


def test_imported_method_on_indexed_receiver_carries_index_deps(
    go_types_helper,
):
    # `lib.VSS[i].PF()` — the receiver's index dependencies join the
    # result like the index read's do.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i int64) int64 { return lib.VSS[i].PF() }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_method_on_map_element_receiver(go_types_helper):
    # `lib.VSM["k"].VF()` — a struct element out of a `map[string]S`
    # (a value-receiver method: map elements are not addressable, so
    # `PF` would not compile). The literal key is dep-free.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.VSM[\"k\"].VF() + x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    vsm = next(m for m in snapshot.imported_members if m.name == "VSM")
    # The whole fact tree pins: the named key is none here, but the
    # element's named type `S` does.
    assert vsm.type.elem.type_id in result.pinned


def test_imported_method_on_indexed_receiver_pins_fact_tree(
    go_types_helper,
):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VSS[0].PF() }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    vss = next(m for m in snapshot.imported_members if m.name == "VSS")
    assert result.available
    assert vss.id in result.pinned
    assert vss.type.elem.type_id in result.pinned


def test_dot_imported_method_on_indexed_receiver(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(i int64) int64 { return VSS[i].PF() }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_method_expr_index_element_receiver(go_types_helper):
    # `lib.S.VF(lib.VSS[i])` — the leading argument is the receiver:
    # a composite element of an imported container reads external
    # state like `lib.VS.PF(lib.VS)` does, carrying the index deps.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i int64) int64 { return lib.S.VF(lib.VSS[i]) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_method_on_computed_index_element_stays_closed(go_types_helper):
    # `g()[0].PF()` — the element comes from a local call, not an
    # imported container member: stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func g() []lib.S { return nil }\n"
        "func F() int64 { return g()[0].PF() }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def _method_expr_lib():
    return {
        "lib": {
            "m.go": (
                "package lib\n"
                "type W struct{ N int64 }\n"
                "func (w W) WF(x int64) int64 { return x }\n"
                "var VW W\nvar VW2 []W\n"
                "type T int64\ntype N []T\n"
                "func (n N) Size() int64 { return int64(len(n)) }\n"
                "var VN N\n"
            ),
        }
    }


def _method_expr_snapshot(go_types_helper, files):
    return load_go_package_snapshot(
        package_report_imports(go_types_helper, files, _method_expr_lib()),
        files,
        target_arch="amd64",
    )


def test_method_expr_composite_var_receiver_is_admitted(go_types_helper):
    # `lib.W.WF(lib.VW, x)` — the receiver slot of a method
    # expression holds a composite imported var: a dep-free external
    # read like `lib.VW.WF(x)`, not a normal argument.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.W.WF(lib.VW, x) }\n"
    }
    snapshot = _method_expr_snapshot(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    vw = next(m for m in snapshot.imported_members if m.name == "VW")
    transfers = [
        t
        for t in result.calls
        if t.imported and t.arguments == () and t.target == vw.id
    ]
    assert transfers  # the `lib.VW` receiver read is on record


def test_method_expr_scalar_var_receiver_stays_a_member_read(
    go_types_helper,
):
    # `lib.T.M(lib.V, x)` — a scalar member in the receiver slot
    # evaluates through the normal member read, dep-free either way.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.T.M(lib.V, x) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_method_expr_receiver_pins_element_identity(go_types_helper):
    # `lib.N.Size(lib.VN)` on `N = []T`: redeclaring `T` inside the
    # imported unit must flag `stale_dependents`, so the receiver
    # read pins the element identity, not only `N`'s own.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.N.Size(lib.VN) + x }\n"
    }
    report = package_report_imports(go_types_helper, files, _method_expr_lib())
    snapshot = load_go_package_snapshot(report, files, target_arch="amd64")
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    vn = next(m for m in snapshot.imported_members if m.name == "VN")
    assert vn.type.elem.type_id in result.pinned


def test_method_expr_indexed_receiver_admits(go_types_helper):
    # `lib.W.WF(lib.VW2[0], x)` — the receiver slot holds a composite
    # element of an imported container: admitted like `lib.VW` itself,
    # dep-free apart from the index.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.W.WF(lib.VW2[0], x) }\n"
    }
    snapshot = _method_expr_snapshot(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_method_expr_indexed_receiver_carries_index_deps(
    go_types_helper,
):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i int64, x int64) int64 {\n"
        "\treturn lib.W.WF(lib.VW2[i], x)\n}\n"
    }
    snapshot = _method_expr_snapshot(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_imported_method_on_const_receiver(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.K.M(x) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_pointer_receiver_method_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) int64 { return x.PM(y) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_imported_interface_method_stays_closed(go_types_helper):
    # Interface dispatch is dynamic: the recorded method identity would
    # not cover the implementations actually reached.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i lib.I, x int64) int64 { return i.M(x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "method_generic_or_variadic"
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_instantiated_receiver_method_is_admitted(go_types_helper):
    # `lib.GT[lib.T]` — an instantiated receiver admits when every type
    # argument is basic, named or alias; the collected identities ride
    # on the record as `type_arg_type_ids` so a `T` redeclare stales
    # the call site like a named instantiation type argument does.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.GT[lib.T], y int64) int64 { return x.GM(y) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["method"] is True
    members = {m["name"]: m for m in report["imported_members"]}
    assert call["target"] == members["GM"]["id"]
    assert call["type_arg_type_ids"] == [members["T"]["id"]]
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_instantiated_pointer_receiver_method_is_admitted(go_types_helper):
    # `x *lib.GT[lib.T]` — one pointer layer unwraps like the
    # concrete-receiver rule, and the instantiated named type's
    # arguments pin through `type_arg_type_ids` the same way.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x *lib.GT[lib.T], y int64) int64 { return x.PGM(y) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["method"] is True
    members = {m["name"]: m for m in report["imported_members"]}
    assert call["target"] == members["PGM"]["id"]
    assert call["type_arg_type_ids"] == [members["T"]["id"]]
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_instantiated_receiver_type_arg_pin_flags_stale(go_types_helper):
    # `lib.GT[lib.T]` receiver: the type-argument pin is the ONLY
    # identity `T` records — the receiver parameter and the `GM`
    # signature pin `GT` alone, so only `type_arg_type_ids` can flag
    # `F` when `T` is redeclared.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.GT[lib.T], y int64) int64 { return x.GM(y) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {
        "m.go": "package lib\nfunc (t T) M(v int64) int64 { return v }\n"
        "func (t T) M2(a int64, b int64) int64 { return a }\n"
        "func (t T) Bad(v int64) (int64, int64) { return v, v }\n"
        "func (t *T) PM(v int64) int64 { return v }\n"
        "func R(t *T) *T { return t }\n"
        "func RR(t *T) (int64, *T) { return 0, t }\n"
        "type I interface{ M(int64) int64 }\n"
        "type GT[P any] int64\n"
        "func (t GT[P]) GM(v int64) int64 { return v }\n"
        "func (t *GT[P]) PGM(v int64) int64 { return v }\n"
        "var V T\nconst K T = 7\nvar PV *T\n",
        "t.go": "package lib\ntype T int32\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_instantiated_receiver_composite_arg_pins(go_types_helper):
    # `lib.GT[*lib.T]` — a composite constructor inside the receiver's
    # type arguments pins every named identity it contains.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.GT[*lib.T], y int64) int64 { return x.GM(y) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    # A composite constructor inside the receiver's type arguments
    # pins every named identity it contains — `*lib.T` pins `T`.
    assert call["kind"] == "direct_import"
    members = {m["name"]: m for m in report["imported_members"]}
    assert call["type_arg_type_ids"] == [members["T"]["id"]]
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_method_expression_is_admitted(go_types_helper):
    # `lib.T.M(t, x)` — a method expression: the receiver is already
    # the leading argument, so the plain `direct_import` model covers
    # it and no `method` flag is recorded.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t lib.T, x int64) int64 { return lib.T.M(t, x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and "method" not in call
    members = {m["name"]: m for m in report["imported_members"]}
    assert call["target"] == members["M"]["id"]
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    # The result depends on the receiver argument and the parameter.
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_pointer_method_expression_records_and_summarizes(
    go_types_helper,
):
    # `(*lib.T).PM(t, x)` records `direct_import` — the wire shape is
    # identical to `lib.T.M` — and a `*lib.T` receiver parameter is a
    # scalar-fragment signature type, so the call unions its argument
    # deps like any other imported call.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, x int64) int64 { return (*lib.T).PM(t, x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and "method" not in call
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_interface_method_expression_stays_closed(go_types_helper):
    # `lib.I.M` — dispatch through an interface type is dynamic; the
    # recorded method identity would not cover the implementations
    # actually reached.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i lib.I, x int64) int64 { return lib.I.M(i, x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "method_generic_or_variadic"


def test_alias_receiver_method_is_admitted(go_types_helper):
    # `type A = T` — an alias-typed parameter's method selection
    # resolves through the alias to the named receiver, exactly like a
    # direct `lib.T` parameter.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.A, y int64) int64 { return x.M(y) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_promoted_instantiated_method_stays_closed(go_types_helper):
    # `struct{ GT[int64] }` — `s.GM` is a promoted selection: the
    # static receiver is `SE`, so the embedded instantiation's type
    # arguments would admit with no pin covering them.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s *lib.SE, y int64) int64 { return s.GM(y) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_promoted_interface_method_stays_closed(go_types_helper):
    # `struct{ I }` — a method promoted from an embedded interface
    # dispatches dynamically even though the outer receiver is
    # concrete.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s *lib.EI, y int64) int64 { return s.M(y) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_instantiated_receiver_type_param_result_is_admitted(
    go_types_helper,
):
    # `func (t GT[P]) MR() P` — the result is judged on the
    # *instantiated* signature the selection reports: `GT[int64]`
    # substitutes `P` with `int64`, a scalar, so the call admits with
    # the result depending on the receiver.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.GT[int64]) int64 { return x.MR() }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_generic_receiver_method_expression_is_admitted(go_types_helper):
    # `lib.GT[lib.T].GM` — an instantiated receiver method expression:
    # the record carries `type_arg_type_ids` for the receiver's named
    # type arguments just like an instantiated callee's.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t lib.GT[lib.T], x int64) int64 {"
        " return lib.GT[lib.T].GM(t, x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and "method" not in call
    members = {m["name"]: m for m in report["imported_members"]}
    assert call["target"] == members["GM"]["id"]
    assert call["type_arg_type_ids"] == [members["T"]["id"]]


def test_multi_result_method_expression_unpacks(go_types_helper):
    # `lib.T.Bad(t, x)` — a multi-valued method expression: the record
    # declares arity like any `direct_import`, and each result carries
    # the receiver-plus-arguments union.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t lib.T, x int64) int64 {"
        " a, b := lib.T.Bad(t, x); return a + b }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import"
    assert call["results"] == 2 and "method" not in call
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_imported_multi_result_method_unpacks(go_types_helper):
    # `x.Bad(1)` — a multi-valued `method` call: each result unions the
    # receiver's deps with the arguments', so both `a` and `b` depend on
    # the receiver parameter.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T) int64 { a, b := x.Bad(1); return a + b }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import"
    assert call["method"] is True and call["results"] == 2
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_local_method_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\n"
        "type L int64\n"
        "func (l L) N(v int64) int64 { return v }\n"
        "func F(x L, y int64) int64 { return x.N(y) }\n"
    }
    report = json.loads(package_report(go_types_helper, files))
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "method_generic_or_variadic"


def test_method_receiver_type_pin_flags_stale_dependents(go_types_helper):
    # `x.M(y)` pins the receiver type's identity through the method
    # member's `signature_type_ids`: redeclaring `T` flags the caller
    # even though `M`'s own identity is unchanged.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) int64 { return x.M(y) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB)
    lib2["lib"] = {
        **METHOD_LIB["lib"],
        "t.go": "package lib\ntype  T int64\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]),
        lib2["lib"],
        target_arch="amd64",
    )
    known = {b.id for b in snapshot2.bindings}
    t = next(m for m in snapshot.imported_members if m.name == "T")
    # `T.M` is the member whose signature pins the receiver type `T`;
    # the interface method `I.M` shares the name.
    m = next(
        m
        for m in snapshot.imported_members
        if m.name == "M" and t.id in m.signature_type_ids
    )
    assert m.id in known
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_parenthesized_method_selector_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) int64 { return (x.M)(y) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_method_flag_on_non_direct_import_call_is_rejected(go_types_helper):
    # `method` only travels on a `direct_import` call — a forged flag on
    # any other kind must fail validation, not silently pass through.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) int64 { return int64(x.M(y)) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    tampered = json.loads(json.dumps(report))
    for c in tampered["calls"]:
        if c["kind"] == "conversion":
            c["method"] = True
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(tampered).encode(), files, target_arch="amd64"
        )
    tampered = json.loads(json.dumps(report))
    for c in tampered["calls"]:
        if c["kind"] == "direct_import":
            c["method"] = "yes"
    with pytest.raises(SnapshotError):
        load_go_package_snapshot(
            json.dumps(tampered).encode(), files, target_arch="amd64"
        )


def test_pointer_param_method_call_is_admitted(go_types_helper):
    # `t *lib.T` — a pointer-typed parameter carries only its dep
    # index: `t.PM(y)` is the same `method` record as `x.PM(y)`, with
    # the receiver expression evaluated like any other argument.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, y int64) int64 { return t.PM(y) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    (call,) = report["calls"]
    assert call["kind"] == "direct_import" and call["method"] is True
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_pointer_param_type_fact_carries_pointee_identity(go_types_helper):
    # The parameter's recorded type fact is `pointer` with the
    # pointee's named identity — redeclaring `lib.T` pins this summary
    # like any other signature type.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T) int64 { return 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    members = {m["name"]: m for m in report["imported_members"]}
    (fn,) = report["functions"]
    (param,) = fn["parameters"]
    assert param["type"]["kind"] == "pointer"
    assert param["type"]["type_id"] == members["T"]["id"]
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and members["T"]["id"] in result.pinned


def test_pointer_result_is_admitted(go_types_helper):
    # `*lib.T` as the sole result: `return t` hands back the
    # parameter's deps through the same type fact.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T) *lib.T { return t }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_pointer_param_local_alias_method_call(go_types_helper):
    # `p := t` binds the parameter's dep set to `p`; the method call
    # through the alias still unions receiver and argument deps.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, y int64) int64 {\n"
        "\tp := t\n"
        "\treturn p.PM(y)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_pointer_deref_named_pointee_is_admitted(go_types_helper):
    # `*t` reads the pointee — the declared `*T` names its identity,
    # so the read records an imported transfer against T (`effects`
    # unknown) and returns the pointer's provenance: t's deps.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T) lib.T { return *t }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_pointer_type_fact_forgery_is_rejected(go_types_helper):
    # A `pointer` fact admits only an empty basic name — its identity is
    # `type_id`. A forged name or a scalar-width payload fails closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T) int64 { return 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    for bad in (
        {"basic_name": "int64"},
        {"bit_width": 64},
        {"signed": True},
    ):
        tampered = json.loads(json.dumps(report))
        tampered["functions"][0]["parameters"][0]["type"].update(bad)
        with pytest.raises(SnapshotError):
            load_go_package_snapshot(
                json.dumps(tampered).encode(), files, target_arch="amd64"
            )


def test_address_of_param_produces_pointer_deps(go_types_helper):
    # `&x` inherits the operand's deps exactly like a `p := x` bind —
    # the result is a `*lib.T` value carrying `{0}`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T) *lib.T { return &x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_address_of_alias_method_call(go_types_helper):
    # `p := &x` gives a `*lib.T` local; the pointer-receiver method
    # call through it unions the alias's and argument's deps.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) int64 {\n"
        "\tp := &x\n"
        "\treturn p.PM(y)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_pointer_result_imported_call_is_admitted(go_types_helper):
    # `lib.R(t)` returns `*T` — a pointer result carries the same
    # arg-union dep set as a scalar one; the pointer binding stores it.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, y int64) *lib.T {\n"
        "\tp := lib.R(t)\n"
        "\t_ = y\n"
        "\treturn p\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    assert report["calls"][0]["kind"] == "direct_import"
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_mixed_pointer_multi_result_unpacks(go_types_helper):
    # `a, b := lib.RR(t)` — a tuple mixing scalar and pointer results:
    # arity travels the record, each result gets the arg union, and
    # `b`'s `*T` binding admits the store.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T) int64 {\n"
        "\ta, b := lib.RR(t)\n"
        "\treturn a + b.PM(0)\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    call = next(
        c
        for c in report["calls"]
        if c["kind"] == "direct_import" and c.get("results") == 2
    )
    assert call["results"] == 2
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_pointer_var_member_read_is_admitted(go_types_helper):
    # `lib.PV` is a `*T` package var — reads stay dep-free like scalar
    # var reads and still emit the staleness transfer.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(y int64) int64 {\n"
        "\tp := lib.PV\n"
        "\treturn p.PM(y)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert any(t.imported for t in result.calls)


def test_imported_pointer_var_deref_read_is_admitted(go_types_helper):
    # `*lib.PV` — the pointee read shares the operand var's imported
    # transfer, so the result stays dep-free and `effects` reports
    # `unknown`, with `T` pinned by the member's declared `*T` fact.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\treturn int64(*lib.PV)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    assert any(t.imported for t in result.calls)


def test_imported_pointer_var_deref_read_parenthesized_is_admitted(
    go_types_helper,
):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\treturn int64(*(lib.PV))\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_imported_pointer_var_deref_read_with_comment_is_admitted(
    go_types_helper,
):
    # `* /*c*/ lib.PV` — a comment inside the unary is a named child
    # but never an operand.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\treturn int64(* /*c*/ lib.PV)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_dot_imported_pointer_var_deref_read_is_admitted(go_types_helper):
    # `*PV` through a dot import resolves the same member record
    # `*lib.PV` does.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F() int64 { return int64(*PV) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert any(t.imported for t in result.calls)


def test_imported_field_member_deref_read_is_admitted(go_types_helper):
    # `*lib.VS2.P` — a dereference read through an imported
    # pointer-typed *field* member resolves like a field read: the
    # result is dep-free external state, `effects` reports
    # `unknown`, and the base member's identity pins beside the
    # pointee `T`'s.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\treturn int64(*lib.VS2.P)\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    assert members["VS2"]["id"] in result.pinned
    assert members["T"]["id"] in result.pinned


def test_imported_field_member_deref_read_dot_import(go_types_helper):
    # `*VS2.P` through a dot import resolves the same member pair.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F() int64 { return int64(*VS2.P) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_imported_field_member_deref_unnamed_pointee_is_admitted(
    go_types_helper,
):
    # `*lib.VS3.PU` — the field member's pointee is `int64`
    # (unnamed): it classifies by `pointee_kind` like `*lib.PU`, so
    # the read admits dep-free and still records the transfer.
    lib = {
        "lib": {
            "s.go": "package lib\ntype S3 struct{ PU *int64 }\nvar VS3 S3\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return *lib.VS3.PU }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_pointer_var_deref_read_flags_stale_dependents(
    go_types_helper,
):
    # The deref's operand read pins `T` through `PV`'s declared `*T`
    # fact, so redeclaring `T` flags the summary the same way a
    # plain `lib.PV` read does.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\treturn int64(*lib.PV)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB["lib"])
    lib2["t.go"] = "package lib\ntype T int32\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_pointer_var_deref_non_scalar_pointee_stays_closed(
    go_types_helper,
):
    # `var PS *S` — the pointee is a struct, which the dep model
    # cannot represent, so the deref read stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\ts := *lib.PS\n"
        "\treturn int64(s.F)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_pointer_var_deref_unnamed_pointee_is_admitted(
    go_types_helper,
):
    # `var PU *int64` — `pointee_kind: "integer"` classifies the read
    # and the empty `pointee_type_ids` means the member's own identity
    # covers the whole declaration, so the dep-free read admits.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\treturn *lib.PU\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    assert members["PU"]["pointee_type_ids"] == []
    assert members["PU"]["pointee_kind"] == "integer"
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_pointee_ids_without_kind_loads_as_closed_read(
    go_types_helper,
):
    # A report from before `pointee_kind` existed declares
    # `pointee_type_ids` alone: the loader must accept it, and the
    # read it cannot classify degrades to the old boundary — closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\treturn *lib.PU\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    for member in report["imported_members"]:
        member.pop("pointee_kind", None)
    snapshot = load_go_package_snapshot(
        json.dumps(report).encode(), files, target_arch="amd64"
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_pointer_var_deref_pointer_pointee_is_admitted(
    go_types_helper,
):
    # `var PPV **T` — `*lib.PPV` yields a `*T`; `pointee_kind`
    # classifies the pointer result and `pointee_type_ids` pins `T`,
    # so the read admits dep-free and `*p` on the bound alias reads
    # dep-free too.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\tp := *lib.PPV\n"
        "\treturn int64(*p)\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    assert members["PPV"]["pointee_kind"] == "pointer"
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert members["T"]["id"] in result.pinned


def test_imported_pointer_var_deref_struct_lit_pointee_stays_closed(
    go_types_helper,
):
    # `var PSTR *struct{ F T }` — the anonymous struct hides a named
    # use no key can declare, so neither `pointee_type_ids` nor
    # `pointee_kind` is emitted and the read stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\ts := *lib.PSTR\n"
        "\treturn int64(s.F)\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    assert "pointee_type_ids" not in members["PSTR"]
    assert "pointee_kind" not in members["PSTR"]
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_pointer_var_deref_array_pointee_stays_closed(
    go_types_helper,
):
    # `*lib.PA` on `*[4]int64` — `pointee_kind: "array"` is not a
    # fragment scalar, so the read stays closed even though the
    # pointee tree is fully pinnable.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i int64) int64 {\n"
        "\ta := *lib.PA\n"
        "\treturn a[i]\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_pointer_var_deref_read_observes_escaped_binding(
    go_types_helper,
):
    # `lib.PU = &b; b = v; return *lib.PU` — the member may point at
    # `b`, so the deref read unions the escaped binding's deps like
    # the `*lib.PV` form does.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(b int64, v int64) int64 {\n"
        "\tlib.PU = &b\n"
        "\tb = v\n"
        "\treturn *lib.PU\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_bound_pointer_deref_read_is_admitted(go_types_helper):
    # `*t` on a pointer-typed parameter — the declared `*T` names the
    # pointee's identity, so the read records an imported transfer
    # against it (`effects` unknown) and returns the pointer's own
    # provenance: the binding's dependencies.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T) int64 { return int64(*t) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    (read,) = [c for c in result.calls if c.imported]
    assert read.target == members["T"]["id"]


def test_bound_pointer_deref_read_through_copy_is_admitted(
    go_types_helper,
):
    # `q := lib.PV; *q` — the bound pointer keeps its declared `*T`
    # identity; the result carries q's provenance (dep-free member
    # read) while the deref records T's transfer.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 {\n"
        "\tq := lib.PV\n"
        "\treturn int64(*q)\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    targets = {c.target for c in result.calls if c.imported}
    assert targets == {members["PV"]["id"], members["T"]["id"]}


def test_bound_pointer_deref_read_unnamed_pointee_is_admitted(
    go_types_helper,
):
    # `p := &x` on a builtin `int64` — the binding's `*int64` names
    # no member identity, but the pointer fact's `elem` classifies
    # the pointee as scalar, so the read admits like `*lib.PU`. The
    # synthetic per-binding identity records the external read.
    files = {
        "a.go": "package p\nimport \"lib\"\nvar _ = lib.PV\n"
        "func F(x int64) int64 {\n"
        "\tp := &x\n"
        "\treturn *p\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    (read,) = [c for c in result.calls if c.imported]
    assert read.target.endswith("/pointee")


def test_bound_pointer_deref_read_composite_pointee_stays_closed(
    go_types_helper,
):
    # `*p` on `p *[]int64` — the pointee fact's `elem` reports a
    # composite kind, so the read stays closed like `*[]T` member
    # reads do.
    files = {
        "a.go": "package p\nimport \"lib\"\nvar _ = lib.PV\n"
        "func F(s []int64) int64 {\n"
        "\tp := &s\n"
        "\treturn (*p)[0]\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_bound_pointer_deref_read_struct_pointee_stays_closed(
    go_types_helper,
):
    # `*s` on `s *lib.S` — a struct pointee is not a fragment value,
    # so the read stays closed like `*lib.PS`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s *lib.S) int64 { _ = *s\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_bound_pointer_deref_read_computed_operand_stays_closed(
    go_types_helper,
):
    # `*g()` — a computed pointer names no binding, so the deref
    # stays closed like `*g() = v` does on the write side.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func g() *lib.T { return lib.PV }\n"
        "func F() int64 { return int64(*g()) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_bound_pointer_double_deref_read(go_types_helper):
    # `**t` — one nested deref on a `**lib.T` binding now admits:
    # the inner `*t` is still a bare identifier and the pointee
    # chain resolves pointer → scalar; a deeper `***t` stays
    # closed because its inner operand is not an identifier.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t **lib.T) int64 { return int64(**t) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_bound_pointer_deref_read_carries_escaped_pointee_deps(
    go_types_helper,
):
    # `p := &x; x = y; *p` reads x's CURRENT value — the pointer's
    # provenance alone would miss y.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y lib.T) int64 {"
        " p := &x; x = y; return int64(*p) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_bound_pointer_deref_read_crosses_alias_identities(
    go_types_helper,
):
    # A `*T` pointer can alias an `A2 = T` binding even though the
    # facts record distinct type_id's for the alias — the escaped
    # union carries every escaped binding, not a type-matched subset.
    alias_lib = {
        "lib": {"m.go": "package lib\ntype T int64\ntype A2 = T\n"}
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, x lib.A2, y lib.T) int64 {"
        " _ = &x; _ = &y; return int64(*t) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, alias_lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1, 2})


def test_member_pointer_deref_read_carries_escaped_pointee_deps(
    go_types_helper,
):
    # `lib.PV = &x; x = y; *lib.PV` may-read x's current value
    # through the member's stored pointer.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y lib.T) int64 {"
        " lib.PV = &x; x = y; return int64(*lib.PV) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_bound_pointer_deref_read_local_pointee_is_admitted(
    go_types_helper,
):
    # `*p` on `p := &t` where `t` is a local `type LT int64` — the
    # pointee identity resolves through the local `type` binding (a
    # real identity in `known`, so `stale_dependents` stays honest),
    # exactly like the imported-member path. The read records an
    # imported transfer against `LT` and returns the pointer's
    # provenance — `t`'s own (empty) dependency set here.
    files = {
        "a.go": "package p\nimport \"lib\"\ntype LT int64\n"
        "var _ = lib.V\n"
        "func F(x int64) int64 { var t LT; p := &t; return int64(*p) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_local_named_scalar_pointee_param_deref(
    go_types_helper,
):
    # `*p` on a `p *MyInt` parameter — the local `type MyInt int64`
    # names a scalar pointee, so the deref read admits and returns
    # the pointer's provenance deps.
    files = {
        "a.go": "package p\ntype MyInt int64\n"
        "func F(p *MyInt) int64 { return int64(*p) }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


@pytest.mark.parametrize(
    "expression",
    ["p.V", "(*p).V", "((p)).V"],
)
def test_local_struct_pointer_field_read_is_admitted(
    go_types_helper, expression
):
    # `p.V`/`(*p).V` on `p *P` where `P` is a package-local struct —
    # the field read touches caller state like `lib.VS.F`: the root
    # pointer's provenance plus every indirect store, an imported
    # transfer against the field's real binding identity, `effects`
    # unknown.
    files = {
        "a.go": "package p\ntype P struct{ V int64; W bool }\n"
        f"func F(p *P) int64 {{ return {expression} }}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_local_nested_pointer_field_read_is_admitted(
    go_types_helper,
):
    # `t.W.N` — the nested selection walks W's `*W2` member to the
    # local `W2` type and resolves `N` there; every traversed local
    # `type` binding pins.
    files = {
        "a.go": "package p\ntype W2 struct{ N int64 }\n"
        "type W struct{ P2 *W2 }\n"
        "func F(t *W) int64 { return t.P2.N }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_local_named_pointee_write_is_admitted(
    go_types_helper,
):
    # `*p = v` on `p *MyInt` — the same pointee-identity gate the
    # read uses now resolves local `type` bindings, matching the
    # `p.V = x` field write that already admitted.
    files = {
        "a.go": "package p\ntype MyInt int64\n"
        "func F(p *MyInt, x int64) int64 { *p = MyInt(x); return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"


def test_local_named_pointee_composites_stay_closed(
    go_types_helper,
):
    # A non-scalar field type keeps the read closed — indexing a
    # slice *field* (`p.V[0]`) never reaches a container pointee.
    decl, expression = "type P struct{ V []int64 }", "p.V[0]"
    files = {
        "a.go": f"package p\n{decl}\n"
        f"func F(p *{decl.split()[1]}, x int64) int64 {{ "
        f"_ = {expression}; return x }}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_local_named_container_pointee_index_read(
    go_types_helper,
):
    # `(*p)[0]` on `p *S` (`type S []int64`) — an index read through
    # a bound pointer whose pointee is a container: external memory,
    # so the pointee's identity records an imported transfer while
    # the result carries the pointer's own deps (param 0).
    files = {
        "a.go": "package p\ntype S []int64\n"
        "func F(p *S) int64 { return (*p)[0] }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})
    s_id = next(
        b.id for b in snapshot.bindings
        if b.name == "S" and b.kind == "type"
    )
    assert s_id in result.pinned
    assert any(c.target == s_id for c in result.calls)


def test_local_unnamed_container_pointee_index_read(
    go_types_helper,
):
    # `(*p)[i]` on `p *[]int64` — the unnamed pointee classifies by
    # the pointer fact's `elem`; the synthetic `<binding>/pointee`
    # identity records the transfer and can never falsely flag
    # `stale_dependents`.
    files = {
        "a.go": "package p\n"
        "func F(p *[]int64, i int64) int64 { return (*p)[i] }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})
    assert any(
        c.target.endswith("/pointee") and c.imported
        for c in result.calls
    )


def test_local_container_pointee_index_write_folds(
    go_types_helper,
):
    # `(*p)[0] = x` — the store lands in external element memory, so
    # the fold keeps x's deps visible: a later `(*p)[1]` read must
    # observe them through `indirect_writes`.
    files = {
        "a.go": "package p\n"
        "func F(p *[]int64, x int64) int64 {\n"
        "\t(*p)[0] = x\n\treturn (*p)[1]\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_local_array_pointee_sugar_index(
    go_types_helper,
):
    # `p[i]` on `p *[4]int64` — Go's auto-deref sugar for
    # pointer-to-array indexing, same model as `(*p)[i]`.
    files = {
        "a.go": "package p\n"
        "func F(p *[4]int64) int64 { p[0] = 7; return p[0] }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_local_container_pointee_whole_store(
    go_types_helper,
):
    # `*p = v` on `p *P` — a whole-composite store through a bound
    # pointer: the fold makes it sound for any pointee shape, so the
    # write side admits it like a scalar pointee store.
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(p *P, x int64) int64 {\n"
        "\t*p = P{V: x}\n\treturn x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_pointee_store_flows_into_field_read(
    go_types_helper,
):
    # `*p = P{V: x}` folds x into `indirect_writes` — a later `p.V`
    # read must observe it: the bound field read unions the root's
    # provenance with indirect stores, never returns dep-free.
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(p *P, x int64) int64 {\n"
        "\t*p = P{V: x}\n\treturn p.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_field_write_flows_into_same_pointer_read(
    go_types_helper,
):
    # `p.V = x` accumulates x into the base binding — a later `p.V`
    # read sees it through the root's own deps.
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(p *P, x int64) int64 {\n"
        "\tp.V = x\n\treturn p.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_field_write_flows_into_aliased_pointer_read(
    go_types_helper,
):
    # `q := p; q.V = x; return p.V` — a field store through a bound
    # pointer also broadcasts into `indirect_writes`, so a read
    # through a DIFFERENT aliased pointer observes it.
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(p *P, x int64) int64 {\n"
        "\tq := p\n\tq.V = x\n\treturn p.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_named_pointee_store_pins_declared_type(
    go_types_helper,
):
    # `*p = MyInt(x)` — the resolved pointee fact pins `MyInt`, so
    # redeclaring the named pointee flags `stale_dependents`.
    files = {
        "a.go": "package p\ntype MyInt int64\n"
        "func F(p *MyInt, x int64) int64 {\n"
        "\t*p = MyInt(x)\n\treturn x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    myint_id = next(
        b.id for b in snapshot.bindings
        if b.name == "MyInt" and b.kind == "type"
    )
    assert myint_id in result.pinned


def test_local_struct_value_field_read_is_admitted(
    go_types_helper,
):
    # `st := P{...}` — a local struct value carries ONE conflated
    # dep set for every field: `st.V` returns the binding's set —
    # local state, so no transfer records and `effects` stays clean.
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(x int64) int64 { st := P{V: x}; return st.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects != "unknown"


def test_local_struct_value_field_write_conflates(
    go_types_helper,
):
    # A partial field store unions the RHS into st's one dep set —
    # `return st.W` reports both fields' deps (sound over-approx).
    files = {
        "a.go": "package p\ntype P struct{ V int64; W int64 }\n"
        "func F(x int64, y int64) int64 {\n"
        "\tst := P{V: x}\n"
        "\tst.W = y\n"
        "\treturn st.W\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects != "unknown" and not result.calls


def test_local_struct_value_reassign_replaces(
    go_types_helper,
):
    # `st = P{...}` overwrites the whole value — the fresh set
    # replaces the old deps entirely.
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(x int64, y int64) int64 {\n"
        "\tst := P{V: x}\n"
        "\tst = P{V: y}\n"
        "\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})


@pytest.mark.parametrize(
    "statement,deps",
    [
        ("st.V = y", {0, 1}),
        ("st.V += y", {0, 1}),
        ("st.A.N = y", {0, 1}),
        # `++` is provenance-preserving — st's set gains nothing.
        ("st.V++", {0}),
    ],
)
def test_local_struct_value_write_forms(
    go_types_helper, statement, deps
):
    # Every field-write form folds the value into st's set with no
    # transfer — a local mutation is not an external effect.
    files = {
        "a.go": "package p\ntype N2 struct{ N int64 }\n"
        "type P struct{ V int64; A N2 }\n"
        "func F(x int64, y int64) int64 {\n"
        f"\tst := P{{V: x}}\n\t{statement}\n\treturn st.V + st.A.N\n}}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset(deps)
    assert result.effects != "unknown" and not result.calls


def test_local_struct_value_conditional_write_unions(
    go_types_helper,
):
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(x int64, y int64) int64 {\n"
        "\tst := P{V: x}\n"
        "\tif x > 0 { st.V = y }\n"
        "\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_local_struct_value_var_decl(
    go_types_helper,
):
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(x int64) int64 {\n"
        "\tvar st P\n"
        "\tst.V = x\n"
        "\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_local_struct_value_empty_literal(
    go_types_helper,
):
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F() int64 { st := P{}; return st.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()


@pytest.mark.parametrize(
    "addr", ["&st", "&st.V", "&st.A.N", "&P{V: x}", "&(P{V: x})"]
)
def test_local_struct_value_address_of_stays_closed(
    go_types_helper, addr
):
    # `&st`/`&st.V` stay closed: the dep-free bound-pointer field
    # read never sees st's conflated set, so letting a pointer
    # alias it would under-approximate the read. `&P{...}` stays
    # closed for the same reason — the literal's initializer deps
    # would be invisible to the dep-free read of the fresh value.
    files = {
        "a.go": "package p\ntype N2 struct{ N int64 }\n"
        "type P struct{ V int64; A N2 }\n"
        "func F(x int64) int64 {\n"
        f"\tst := P{{V: x}}\n\tp := {addr}\n\t_ = p\n"
        "\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_local_struct_value_pointer_field_chain_stays_closed(
    go_types_helper,
):
    # `st.A.N` on `A *P2` dereferences memory the conflated set
    # cannot represent — the chain stays closed.
    files = {
        "a.go": "package p\ntype P2 struct{ N int64 }\n"
        "type P struct{ A *P2; V int64 }\n"
        "func F(x int64) int64 {\n"
        "\tst := P{V: x}\n"
        "\treturn st.A.N\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


@pytest.mark.parametrize("statement", ["st.A.N = y", "st.A.N++"])
def test_local_struct_value_pointer_intermediate_write_stays_closed(
    go_types_helper, statement
):
    # `st.A.N = y` on `A *P2` writes through the pointer into caller
    # memory — neither a local fold nor a pinnable transfer, so it
    # stays closed.
    files = {
        "a.go": "package p\ntype P2 struct{ N int64 }\n"
        "type P struct{ A *P2; V int64 }\n"
        "func F(x int64, y int64) int64 {\n"
        f"\tst := P{{V: x}}\n\t{statement}\n\treturn st.V\n}}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_local_struct_value_deep_pointer_intermediate_stays_closed(
    go_types_helper,
):
    # The pointer check applies to every traversed field, not just
    # the innermost one.
    files = {
        "a.go": "package p\ntype P3 struct{ N int64 }\n"
        "type P2 struct{ B *P3 }\n"
        "type P struct{ A P2; V int64 }\n"
        "func F(x int64, y int64) int64 {\n"
        "\tst := P{V: x}\n"
        "\tst.A.B.N = y\n"
        "\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_local_struct_value_pointer_leaf_field(
    go_types_helper,
):
    # A pointer-typed *leaf* is fine: `st.A = p` folds p's deps into
    # st's set — only *traversed* fields must be non-pointers.
    files = {
        "a.go": "package p\ntype P2 struct{ N int64 }\n"
        "type P struct{ A *P2; V int64 }\n"
        "func F(x int64, p *P2) int64 {\n"
        "\tst := P{V: x}\n"
        "\tst.A = p\n"
        "\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_local_struct_value_boundaries(
    go_types_helper,
):
    # Named slices, method values and method calls all stay
    # closed (anonymous `struct{...}` values admit — covered by
    # the dedicated anonymous-struct tests below).
    for decl, body in [
        ("type S []int64", "sl := S{x}; return sl[0]"),
        (
            "type P struct{ V int64 }\n"
            "func (P) M() int64 { return 0 }",
            "st := P{V: x}; f := st.M; return f()",
        ),
        (
            "type P struct{ V int64 }\n"
            "func (p P) M2() int64 { return p.V }",
            "st := P{V: x}; return st.M2()",
        ),
    ]:
        files = {
            "a.go": f"package p\n{decl}\n"
            f"func F(x int64) int64 {{ {body} }}\n"
        }
        snapshot = _snapshot_for(go_types_helper, files)
        result = named_package(
            files, snapshot, ip.summarize_go_package(files, snapshot), "F"
        )
        assert not result.available, body


@pytest.mark.parametrize(
    "statement", ["st.V = x", "st.V++", "st.V += x"]
)
def test_local_struct_value_embedded_pointer_write_stays_closed(
    go_types_helper, statement
):
    # `type P struct{ *Q }` — `st.V` resolves to Q's field through
    # the embedded pointer: the store crosses it into memory the
    # conflated dep set cannot represent, so every write form stays
    # closed. (Promoted reads still return st's set — a sound
    # over-approximation.)
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\ntype P struct{ *Q }\n"
        f"func F(q *Q, x int64) int64 {{ st := P{{Q: q}}; "
        f"{statement}; return x }}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_local_struct_value_embedded_pointer_leaf_write_stays_closed(
    go_types_helper,
):
    # `st.A.N` where `A` embeds `*Q` — the *written* leaf resolves
    # through the embedded pointer even though the syntactic chain
    # names none, so the store stays closed too.
    files = {
        "a.go": "package p\n"
        "type Q struct{ N int64 }\ntype A struct{ *Q }\n"
        "type P struct{ A A }\n"
        "func F(x int64) int64 { st := P{}; st.A.N = x; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


@pytest.mark.parametrize(
    "statement", ["q.V = x", "q.V++", "q.V += x"]
)
def test_local_struct_value_named_pointer_write_stays_closed(
    go_types_helper, statement
):
    # `type Ptr *P` — `var q Ptr = p` binds a pointer under a named
    # alias: `q.V` names a field of `*P`, so the store crosses the
    # pointer into caller memory and stays closed.
    files = {
        "a.go": "package p\n"
        "type P struct{ V int64 }\ntype Ptr *P\n"
        f"func F(p *P, x int64) int64 {{ var q Ptr = p; "
        f"{statement}; return x }}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_local_struct_value_map_literal_key_side_effect(
    go_types_helper,
):
    # A map literal's key is a *evaluated* expression, unlike a
    # struct literal's field name — `M[K(x): 0]` runs `K`, whose
    # package-var write must record.
    files = {
        "a.go": "package p\nvar G int64\n"
        "func K(v int64) int64 { G = v; return v }\n"
        "func F(x int64) int64 {\n"
        "\t_ = map[int64]int64{K(x): 0}\n\treturn x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"


def test_local_struct_value_type_pin_flags_stale_dependents(
    go_types_helper,
):
    # The composite local pins its declared type's identity — a
    # redeclared `type P` in a *sibling* file flags the summary even
    # though nothing the summary records transfers to the type.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 { st := P{V: x}; return st.V }\n",
        "t.go": "package p\ntype P struct{ V int64 }\n",
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    files2 = {**files, "t.go": "package p\n\ntype P struct{ V int64 }\n"}
    snapshot2 = _snapshot_for(go_types_helper, files2)
    known = {b.id for b in snapshot2.bindings}
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    # a.go is untouched, so F's own identities survive — only the
    # pinned type identity flags it stale.
    assert f_id in known
    p_id = next(
        b.id
        for b in snapshot.bindings
        if b.name == "P" and b.kind == "type"
    )
    assert p_id not in known
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_local_pointer_deref_read_named_pointee_is_admitted(
    go_types_helper,
):
    # `*p` through `p := &t` — the binding's declared `*T` names the
    # pointee's identity, so the read records an imported transfer
    # and returns the pointer's provenance (t's dependencies).
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t lib.T) int64 {\n"
        "\tp := &t\n"
        "\treturn int64(*p)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_deref_write_is_admitted(go_types_helper):
    # `*t = v` on a bound `*T` parameter — the store lands in memory
    # the dep model does not track, so only the external mutation
    # records against the declared pointee identity (`effects`
    # reports `unknown`); the stored value's deps accumulate for any
    # later dereference read to observe.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, v int64) int64 {\n"
        "\t*t = lib.T(v)\n"
        "\treturn int64(v)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})
    assert result.effects == "unknown"


def test_deref_write_folds_into_escaped_binding(go_types_helper):
    # `p := &x; *p = y; return x` — the store may land in `x`, so the
    # escaped-binding fold unions the stored value's dependencies
    # into every escaped binding, like `*lib.PV = v` does.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y lib.T) lib.T {\n"
        "\tp := &x\n"
        "\t*p = y\n"
        "\treturn x\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"


def test_deref_write_no_escape_keeps_deps(go_types_helper):
    # Without an escaped binding the fold is a no-op — other bindings
    # keep their deps while the store still records its mutation.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, x lib.T, y int64) lib.T {\n"
        "\t*t = lib.T(y)\n"
        "\treturn x\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})
    assert result.effects == "unknown"


def test_deref_write_local_pointer_is_admitted(go_types_helper):
    # `q := t; *q = v` — a bound local pointer admits the same way.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, x lib.T, v lib.T) lib.T {\n"
        "\tq := t\n"
        "\t*q = v\n"
        "\treturn x\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})
    assert result.effects == "unknown"


def test_deref_write_unnamed_pointee_is_admitted(go_types_helper):
    # `p := &b` on a builtin `int64` produces an unnamed `*int64`
    # binding — the pointee fact's `elem` classifies it as scalar, so
    # the store records an imported mutation against the synthetic
    # per-binding identity and folds `v`'s deps into every escaped
    # binding: `return b` may observe `v`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(b int64, v int64, z lib.T) int64 {\n"
        "\tp := &b\n"
        "\t*p = v\n"
        "\treturn b\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target.endswith("/pointee")


def test_synthetic_pointee_target_does_not_flag_stale_dependents(
    go_types_helper,
):
    # A synthetic `<binding_id>/pointee` transfer target can never be
    # redeclared: keeping it out of `call_targets` means a summary
    # that recorded one is not flagged stale forever by
    # `stale_dependents`.
    files = {
        "a.go": "package p\n"
        "func F(b int64) int64 {\n"
        "\tp := &b\n"
        "\treturn *p\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    (read,) = [c for c in result.calls if c.imported]
    assert read.target.endswith("/pointee")
    assert read.target not in result.call_targets
    known = {b.id for b in snapshot.bindings}
    assert read.target not in known
    assert summaries.stale_dependents(known) == frozenset()


@pytest.mark.parametrize(
    "declarations,expected_deps",
    [
        # A package-level scalar `var` reads like an imported `lib.V`:
        # dep-free for the value, `effects` unknown via the recorded
        # imported transfer against the var's binding identity.
        ("var G int64\nfunc F(x int64) int64 { return x + G }", {0}),
        ("var G int64\nfunc F(x int64) int64 { return G }", set()),
        # `G = v` mutates package state like `lib.V = v` — external,
        # so the stored deps drop and `effects` stays unknown.
        ("var G int64\nfunc F(x int64) int64 { G = x; return x }", {0}),
        ("var G int64\nfunc F(x int64) int64 { G += x; return x }", {0}),
        # `G++`/`G--` admit like `lib.V++` — provenance-preserving,
        # only the external mutation records.
        ("var G int64\nfunc F(x int64) int64 { G++; return x }", {0}),
        ("var G int64\nfunc F(x int64) int64 { G--; return G }", set()),
        # A package var shadowing a universe name is still package
        # state — the read admits and marks `effects` unknown.
        ("var iota int64\nfunc F(x int64) int64 { return iota }", set()),
        ("var true bool\nfunc F() bool { return true }", set()),
        # A cross-file package var resolves through the same binding.
        ("func F(x int64) int64 { G = x; return G }", set()),
    ],
)
def test_package_level_scalar_vars_record_imported_transfers(
    go_types_helper, declarations, expected_deps
):
    files = {"a.go": "package p\n" + declarations}
    if "func F" in declarations and "var G" not in declarations:
        files["b.go"] = "package p\nvar G int64\n"
    snapshot = load_go_package_snapshot(
        package_report(go_types_helper, files), files, target_arch="amd64"
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available
    assert result.return_dependencies == frozenset(expected_deps)
    assert result.effects == "unknown"
    assert all(c.imported for c in result.calls)


def test_package_global_transfer_target_flags_stale_dependents(
    go_types_helper,
):
    # The recorded target is the var's real binding identity, so
    # regenerating the unit without `G` flags the reader — unlike a
    # synthetic identity it lives in `known` while the var exists.
    files = {
        "a.go": "package p\nvar G int64\n"
        "func F(x int64) int64 { return x + G }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report(go_types_helper, files), files, target_arch="amd64"
    )
    summaries = ip.summarize_go_package(files, snapshot)
    known = {b.id for b in snapshot.bindings}
    assert summaries.stale_dependents(known) == frozenset()
    files2 = {"a.go": "package p\nfunc F(x int64) int64 { return x }\n"}
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, files2), files2, target_arch="amd64"
    )
    known2 = {b.id for b in snapshot2.bindings}
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known2) == frozenset({f_id})


def test_package_level_composite_var_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\nvar G string = \"a\"\n"
        "func F(x int64) int64 { if G == \"a\" { return x }; return 0 }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report(go_types_helper, files), files, target_arch="amd64"
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_function_local_var_is_not_a_package_global(go_types_helper):
    # A function-local `var` the fragment binds is in `locals_` — the
    # package-level gate never reaches it.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 { var y int64 = x; return y }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report(go_types_helper, files), files, target_arch="amd64"
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


def test_deref_write_then_deref_read_keeps_stored_deps(go_types_helper):
    # `*t = v; return *t` — the store lands in memory no binding
    # tracks, but the read may observe exactly that value: deps stored
    # through any pointer write union back into a dereference read
    # even when no `&x` escaped.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, v lib.T) lib.T {\n"
        "\t*t = v\n"
        "\treturn *t\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"


def test_deref_write_through_local_call_keeps_arg_deps(go_types_helper):
    # `Set(&x, y); return x` — the local callee's `*p = v` store has
    # unbounded effects, so `x` conservatively gains every argument's
    # deps like an imported call's `&x` rule.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func Set(p *lib.T, v lib.T) int64 {\n"
        "\t*p = v\n"
        "\treturn 0\n}\n"
        "func F(x lib.T, y lib.T) lib.T {\n"
        "\tSet(&x, y)\n"
        "\treturn x\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"


def test_double_deref_write_admits(go_types_helper):
    # `**t = v` — one nested store level admits under the same
    # unconditional alias fold `*t = v` uses; `***t = v` stays
    # closed because its inner operand is not a bare identifier.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t **lib.T, v lib.T) lib.T {\n"
        "\t**t = v\n"
        "\treturn v\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_deref_inc_dec_is_admitted(go_types_helper):
    # `(*p)++` — an increment through a bound pointer mutates the
    # same untracked memory but is provenance-preserving: `x` keeps
    # its dependencies across the store.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T) lib.T {\n"
        "\tp := &x\n"
        "\t(*p)++\n"
        "\treturn x\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_deref_dec_unparenthesized_is_admitted(go_types_helper):
    # `*t--` on a `*T` parameter parses as `(*t)--` and admits the
    # same way.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T, x lib.T) lib.T {\n"
        "\t*t--\n"
        "\treturn x\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})
    assert result.effects == "unknown"


def test_field_write_through_pointer_is_admitted(go_types_helper):
    # `s.f = v` — a field store through a pointer-typed parameter only
    # touches caller state (struct bindings cannot exist locally), so
    # the dep model stays exact — but the write is an external
    # mutation and must be recorded as an imported transfer so
    # `effects` reports `unknown` and `S` redeclaration flags it.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s *lib.S, v int64) int64 {\n"
        "\ts.F = v\n"
        "\treturn 0\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["S"]["id"] and write.arguments == ()


def test_field_write_dependencies_survive_into_later_reads(go_types_helper):
    # `s.F = v; return s.PF()` — the store lands in the pointee's
    # contents, which a later method call can observe: the result must
    # keep `v`'s dependency, not just the pre-write `s` state.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s *lib.S, v int64) int64 {\n"
        "\ts.F = v\n"
        "\treturn s.PF()\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_deref_base_field_write_is_admitted(go_types_helper):
    # `(*s).F = v` — one explicit dereference of the bound pointer
    # before the selection, the same auto-deref `s.F = v` spelled
    # out: the write lands only in the pointee's field.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s *lib.S, v int64) int64 {\n"
        "\t(*s).F = v\n"
        "\treturn 0\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["S"]["id"] and write.arguments == ()


def test_deref_base_field_write_comment_parens_is_admitted(go_types_helper):
    # `(*( /* c */ s)).F = v` — comments inside the parentheses do
    # not block the unwrap.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s *lib.S, v int64) int64 {\n"
        "\t(*( /* c */ s)).F = v\n"
        "\treturn 0\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()


def test_double_deref_field_write_stays_closed(go_types_helper):
    # `(**s).F = v` — one deref leaves a `*S` operand, not an
    # identifier.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s **lib.S, v int64) int64 {\n"
        "\t(**s).F = v\n"
        "\treturn 0\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_array_type_argument_pins_element(go_types_helper):
    # `lib.S[[2]lib.T](x)` — an array type argument's length is not a
    # type expression; the element's identity still pins.
    lib = {
        "lib": {
            "s.go": "package lib\ntype S[A any] int64\n",
            "t.go": "package lib\ntype T int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.S[[2]lib.T](x)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_member_write_is_admitted(go_types_helper):
    # `lib.VS.F = v` — a store through an imported package member is
    # external state: the write records an imported transfer against
    # the member's own identity (`effects` reports `unknown`) and the
    # stored value's dependencies drop with it.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 {\n"
        "\tlib.VS.F = v\n"
        "\treturn 0\n}\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["VS"]["id"] and write.arguments == ()


def test_address_of_composite_stays_closed(go_types_helper):
    # `&` on a non-identifier operand evaluates the operand inside the
    # fragment — `&(*g())` fails at the operand, not the operator,
    # because `*g()` names no bound pointer.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func g() *lib.T { return lib.PV }\n"
        "func F() *lib.T {\n"
        "\treturn &(*g())\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_address_of_deref_read_is_admitted(go_types_helper):
    # `&(*t)` is `t` — the deref's deps are the pointer's own, so the
    # address-of returns them unchanged.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.T) *lib.T {\n"
        "\treturn &(*t)\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_pointer_result_generic_cannot_bypass_instantiation_gate(
    go_types_helper,
):
    # `func G[P any](v P) *P` — the declared result `*P` reads as a
    # pointer, but the callee is generic: it must go through the
    # instantiation gate, so `lib.G(t)` with `t` a named `lib.T` infers
    # `P = *lib.T` — a non-basic type argument — and stays closed.
    lib = {
        "lib": {
            "g.go": "package lib\nfunc G[P any](v P) *P { return &v }\n"
            "func S[P any](v P) int64 { return 0 }\n",
            "t.go": "package lib\ntype T int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t lib.T) int64 { return lib.S(t) }\n"
        "func G2(t lib.T) int64 { _ = lib.G(t); return 0 }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    assert report["status"] == "ok"
    calls = report["calls"]
    assert len(calls) == 2
    # Both calls infer P=lib.T — a named type argument admitted through
    # the instantiation gate with the `lib.T` pin on the record; the
    # `*P` result never slipped through the declared-signature path.
    t = next(m for m in report["imported_members"] if m["name"] == "T")
    assert all(c["kind"] == "direct_import" for c in calls)
    assert all(c["type_arg_type_ids"] == [t["id"]] for c in calls)


def test_pointer_arg_escape_unions_callee_args(go_types_helper):
    # `lib.Set(&x, y)` hands the callee an alias it may write through —
    # afterwards `x` conservatively depends on every argument, so a
    # `Set` that stores `y` into `*p` still flags `x` as dependent.
    lib = {
        "lib": {
            "s.go": "package lib\ntype T int64\n"
            "func Set(p *T, v int64) { *p = T(v) }\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) lib.T {\n"
        "\tlib.Set(&x, y)\n"
        "\treturn x\n}\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_named_type_arg_pin_flags_stale_dependents(go_types_helper):
    # `lib.GI[lib.T](t)` — `lib.T` appears only in the signature and the
    # type argument, never in an expression, so only the call record's
    # `type_arg_type_ids` can pin it (a `lib.T(x)` conversion or a var
    # read would pin it through the member-read path instead).
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t lib.T) int64 { return int64(lib.GI[lib.T](t)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {
        "g.go": "package lib\ntype T2 int64\nfunc GI[T any](v T) T { return v }\n"
        "func G2[A any, B any](a A, b B) A { return a }\n"
        "func GV[T any](v T) {}\n"
        "func GN[T any](v T2) int64 { return 0 }\n",
        # Redeclaring `T` churns the pinned type-arg identity while
        # `GI`'s own declaration is byte-identical.
        "t.go": "package lib\ntype T int32\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_named_type_arg_only_position_pin_flags_stale(go_types_helper):
    # `lib.GN[lib.T](0)` — `lib.T` appears ONLY in the type-argument
    # position: not in `F`'s signature, not in an expression, so neither
    # signature pinning nor the member-read path can flag `F`. Only the
    # call record's `type_arg_type_ids` pins it.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.GN[lib.T](0) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {
        "g.go": "package lib\ntype T2 int64\nfunc GI[T any](v T) T { return v }\n"
        "func G2[A any, B any](a A, b B) A { return a }\n"
        "func GV[T any](v T) {}\n"
        "func GN[T any](v T2) int64 { return 0 }\n",
        "t.go": "package lib\ntype T int32\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_named_type_arg_from_second_unit_is_pinned(go_types_helper):
    # `lib.GI[other.U](t)` — the type argument's identity lives in a
    # third unit's coordinate space; it still pins at the call site.
    lib = dict(GENERIC_LIB)
    lib["other"] = {"u.go": "package other\ntype U int64\n"}
    files = {
        "a.go": "package p\nimport \"lib\"\nimport \"other\"\n"
        "func F(t other.U) int64 { return int64(lib.GI[other.U](t)) }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    assert report["status"] == "ok"
    (call,) = [c for c in report["calls"] if c["kind"] == "direct_import"]
    u = next(m for m in report["imported_members"] if m["name"] == "U")
    assert call["type_arg_type_ids"] == [u["id"]]
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_mixed_basic_named_type_args_pin_only_named(go_types_helper):
    # `lib.G2[int64, lib.T](x, t)` — the basic argument contributes
    # nothing; only `lib.T` lands on `type_arg_type_ids`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64, t lib.T) int64 {"
        " return int64(lib.G2[int64, lib.T](x, t)) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    (call,) = [c for c in report["calls"] if c["kind"] == "direct_import"]
    t = next(m for m in report["imported_members"] if m["name"] == "T")
    assert call["type_arg_type_ids"] == [t["id"]]
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_instantiated_type_conversion_summarized(go_types_helper):
    # `lib.S[int64](x)` — an instantiated generic *type* conversion is
    # effect-free like `T(e)`: the result inherits the operand's
    # dependencies when the target member's underlying is scalar.
    lib = {"lib": {"s.go": "package lib\ntype S[A any] int64\n"}}
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.S[int64](x)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_instantiated_type_conversion_pins_named_args(go_types_helper):
    # `lib.S[lib.T](x)` pins BOTH `S` and the nested `T`; redeclaring
    # `T` while `S` is byte-identical must stale the call site.
    lib = {
        "lib": {
            "s.go": "package lib\ntype S[A any] int64\n",
            "t.go": "package lib\ntype T int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) lib.S[lib.T] { return lib.S[lib.T](x) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {
        "s.go": "package lib\ntype S[A any] int64\n",
        "t.go": "package lib\ntype T int32\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_instantiated_type_conversion_nested_generic_arg_pins(go_types_helper):
    # `lib.S[other.N[lib.T]](x)` — the conversion walks nested
    # instantiations too, pinning `S`, `N` and `T`.
    lib = {
        "lib": {
            "s.go": "package lib\ntype S[A any] int64\n",
            "t.go": "package lib\ntype T int64\n",
        },
        "other": {
            "n.go": "package other\ntype N[A any] int64\n",
        },
    }
    files = {
        "a.go": "package p\nimport \"lib\"\nimport \"other\"\n"
        "func F(x int64) lib.S[other.N[lib.T]] { return lib.S[other.N[lib.T]](x) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {
        "s.go": "package lib\ntype S[A any] int64\n",
        "t.go": "package lib\ntype T int32\n",
    }
    other2 = {"n.go": "package other\ntype N[A any] int64\n"}
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    snapshot3 = load_go_package_snapshot(
        package_report(go_types_helper, other2), other2, target_arch="amd64"
    )
    known = (
        {b.id for b in snapshot.bindings}
        | {b.id for b in snapshot2.bindings}
        | {b.id for b in snapshot3.bindings}
    )
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_instantiated_type_conversion_pointer_arg_pins(go_types_helper):
    # `lib.S[*lib.T](0)` — a composite type argument pins every named
    # identity inside it, so redeclaring `T` while `S` is
    # byte-identical stales the call site.
    lib = {
        "lib": {
            "s.go": "package lib\ntype S[A any] int64\n",
            "t.go": "package lib\ntype T int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(lib.S[*lib.T](0)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available
    lib2 = {
        "s.go": "package lib\ntype S[A any] int64\n",
        "t.go": "package lib\ntype T int32\n",
    }
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_instantiated_type_conversion_map_arg_pins(go_types_helper):
    # `lib.S[map[string]lib.T](x)` — a map type argument pins the
    # element identity the same way.
    lib = {
        "lib": {
            "s.go": "package lib\ntype S[A any] int64\n",
            "t.go": "package lib\ntype T int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.S[map[string]lib.T](x)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_instantiated_type_conversion_func_arg_stays_closed(
    go_types_helper,
):
    # `lib.S[func() int64](x)` — a signature type argument carries no
    # pinnable identity, so the conversion stays closed.
    lib = {"lib": {"s.go": "package lib\ntype S[A any] int64\n"}}
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.S[func() int64](x)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_generic_pointer_type_argument_is_pinned(go_types_helper):
    # `lib.GN[*lib.T](v)` — a pointer type argument's pointee rides on
    # `type_arg_type_ids`, pinning `lib.T` at this call site.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v lib.T2) int64 { return lib.GN[*lib.T](v) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    gn = next(c for c in report["calls"] if c["kind"] == "direct_import")
    t = next(m for m in report["imported_members"] if m["name"] == "T")
    assert gn["type_arg_type_ids"] == [t["id"]]
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_generic_pointer_result_type_arg_is_admitted(
    go_types_helper,
):
    # `lib.GI[*lib.T](p)` — the instantiated result `*lib.T` is a
    # pointer to a declared named type, an admitted signature shape,
    # so the call classifies and the pointee pins `T`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(p *lib.T) *lib.T { return lib.GI[*lib.T](p) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    gi = next(c for c in report["calls"] if c["kind"] == "direct_import")
    t = next(m for m in report["imported_members"] if m["name"] == "T")
    assert gi["type_arg_type_ids"] == [t["id"]]
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_instantiated_type_conversion_composite_underlying_closed(go_types_helper):
    # `type C[A any] *A` — the member's underlying is not scalar, so
    # the conversion stays closed.
    lib = {
        "lib": {
            "c.go": "package lib\ntype C[A any] *A\n",
            "t.go": "package lib\ntype T int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(p *lib.T) lib.C[lib.T] { return lib.C[lib.T](p) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_instantiated_type_conversion_missing_arg_ref_closed(go_types_helper):
    # A type argument whose name the report recorded no reference for
    # is unresolvable — the conversion fails closed rather than admit
    # an unpinned identity.
    lib = {"lib": {"s.go": "package lib\ntype S[A any] int64\n"}}
    files = {
        "a.go": "package p\nimport \"lib\"\ntype T int64\n"
        "func F(x int64) int64 { return int64(lib.S[T](x)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    t_id = next(
        b.id
        for b in snapshot.bindings
        if b.name == "T" and b.kind == "type"
    )
    forged = replace(
        snapshot,
        references=tuple(
            r for r in snapshot.references if r.binding_id != t_id
        ),
    )
    result = named_package(
        files, forged, ip.summarize_go_package(files, forged), "F"
    )
    assert not result.available


def test_imported_index_read_is_admitted(go_types_helper):
    # `lib.VA[i]` — an index read of an imported slice var: the element
    # is external state, so only the index's own dependencies carry.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.VA[x] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_imported_array_read_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.AA[0] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()


def test_imported_index_read_pointer_elem_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { p := lib.VP[0]\n\t_ = p\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_dot_imported_index_read_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F() int64 { return VA[0] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_parenthesized_index_operand_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return (lib.VA)[0] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_index_read_named_elem_is_admitted(go_types_helper):
    # `[]lib.T` — the element's named identity pins, so a `T`
    # redeclaration flags the reader through `stale_dependents`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.VT[x]) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_named_slice_read_is_admitted(go_types_helper):
    # `type NS []int64; var VNS NS` — a named slice type carries the
    # slice fact on its underlying and pins its own identity.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VNS[0] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_index_read_flags_stale_dependents(go_types_helper):
    # Redeclaring `T` flags `F` — `lib.VT[x]` pinned the element's
    # named identity, not just the `VT` member's.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.VT[x]) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB["lib"])
    lib2["t.go"] = "package lib\ntype T int32\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_named_slice_pin_flags_stale_dependents(go_types_helper):
    # Redeclaring `NS` flags `F` — `lib.VNS[0]` pinned the named
    # container type's own identity via `type_id`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VNS[0] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB["lib"])
    lib2["m.go"] = METHOD_LIB["lib"]["m.go"].replace(
        "type NS []int64", "type NS []int32"
    )
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_index_read_struct_elem_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { s := lib.VSS[0]\n\treturn int64(s.F) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_index_read_slice_elem_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { s := lib.V2[0]\n\treturn int64(len(s)) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_nested_index_is_admitted(go_types_helper):
    # `lib.V2[i][j]` — each level descends one `elem` fact on
    # `[][]int64`; the scalar element admits and the result unions
    # both levels' index deps.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i, j int64) int64 { return lib.V2[i][j] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"


def test_imported_nested_index_literal_levels_are_dep_free(
    go_types_helper,
):
    # `lib.V2[0][j]` — a literal level contributes nothing; only the
    # computed index carries.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(j int64) int64 { return lib.V2[0][j] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_imported_nested_map_index_is_admitted(go_types_helper):
    # `lib.VM2["a"]["b"]` — `map[string]map[string]int64` descends two
    # map facts to the scalar value; literal keys stay dep-free.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VM2[\"a\"][\"b\"] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()


def test_imported_nested_index_named_elem_pins(go_types_helper):
    # `lib.V2T[i][j]` on `[][]T` — the final element's named identity
    # pins like a single-level `[]T` element does. The conversion
    # keeps the result `int64` so `T` can only pin through the read;
    # `G` names `lib.T` so the member record exists to look up.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i, j int64) int64 { return int64(lib.V2T[i][j]) }\n"
        "func G() int64 { _ = lib.T(0)\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert members["T"]["id"] in result.pinned


def test_imported_nested_index_inner_container_pins(go_types_helper):
    # `var V2NS []NS2` — the innermost container is itself a named
    # type (`type NS2 []int64`): its identity must pin too, or
    # redeclaring `NS2` flags nothing in `stale_dependents`. `G`
    # names `lib.NS2` so the member record exists to look up.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i, j int64) int64 { return lib.V2NS[i][j] }\n"
        "func G() int64 { _ = lib.NS2(nil)\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert members["NS2"]["id"] in result.pinned


def test_imported_nested_index_struct_elem_stays_closed(
    go_types_helper,
):
    # `lib.VSM[k]` yields an `S` — indexing its field chain
    # (`lib.VSM[k].F`) is a selector on a computed operand, not a
    # member index, and the element is not scalar anyway.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k string) int64 { return lib.VSM[k].F }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_range_slice_index_is_admitted(go_types_helper):
    # `for i := range lib.VA` — ranging the imported slice reads
    # package state: `i` carries no parameter deps (the values are
    # external), and the read records the imported transfer.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { x := int64(0)\n"
        "\tfor i := range lib.VA { x = int64(i) }\n\treturn x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    members = {
        m["name"]: m
        for m in json.loads(
            package_report_imports(go_types_helper, files, METHOD_LIB)
        )["imported_members"]
    }
    (read,) = [c for c in result.calls if c.imported]
    assert read.target == members["VA"]["id"]


@pytest.mark.parametrize(
    "lhs",
    ["i, v :=", "_, v :=", "i, _ :="],
    ids=["index_and_element", "blank_index", "blank_element"],
)
def test_imported_range_two_vars_is_admitted(go_types_helper, lhs):
    # `for i, v := range lib.VA` — the element slot binds like the
    # index does: dep-free external values; `_` slots skip binding.
    body = {
        "i, v :=": "x = int64(i) + v",
        "_, v :=": "x = v",
        "i, _ :=": "x = int64(i)",
    }[lhs]
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { x := int64(0)\n"
        f"\tfor {lhs} range lib.VA {{ {body} }}\n\treturn x }}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()


def test_imported_range_map_key_value_is_admitted(go_types_helper):
    # `for k, v := range lib.VMK` — the named key `MK` is scalar, so
    # both slots bind; `MK`'s identity pins alongside the member's.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { x := int64(0)\n"
        "\tfor k, v := range lib.VMK { x = int64(k) + v }\n"
        "\treturn x }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    # `MK` is only named inside `VMK`'s type — it has no member record;
    # its identity lives on the member fact's `key.type_id`.
    mk_id = members["VMK"]["type"]["key"]["type_id"]
    assert mk_id
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert mk_id in result.pinned


def test_imported_range_dot_import_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F() int64 { x := int64(0)\n"
        "\tfor i := range VA { x = int64(i) }\n\treturn x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_range_bare_is_admitted(go_types_helper):
    # `for range lib.VA` — no names bind; the read still records.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { x := int64(0)\n"
        "\tfor range lib.VA { x++ }\n\treturn x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert any(c.imported for c in result.calls)


def test_imported_range_assigns_existing_binding(go_types_helper):
    # `for i = range lib.VA` — the `=` form reuses the outer binding
    # through `_store` like the integer range does.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { i := 0\n"
        "\tfor i = range lib.VA {}\n\treturn int64(i) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()


def test_imported_range_string_key_stays_closed(go_types_helper):
    # `for k := range lib.VM` — `map[string]` keys are strings, a
    # type the fragment cannot bind.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { x := int64(0)\n"
        "\tfor k := range lib.VM { _ = k }\n\treturn x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_range_struct_elem_stays_closed(go_types_helper):
    # `for _, s := range lib.VSS` — the element is a struct.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { x := int64(0)\n"
        "\tfor _, s := range lib.VSS { _ = s.F }\n\treturn x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_range_string_member_stays_closed(go_types_helper):
    # `for i := range lib.VStr` — a string member is not a container
    # fact, so the ordinary member-read gate stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { x := int64(0)\n"
        "\tfor i := range lib.VStr { _ = i }\n\treturn x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available

    assert not result.available


def test_imported_map_index_shadowed_true_reads_binding_deps(
    go_types_helper,
):
    # `lib.VB[true]` — Go allows declaring a variable named `true`,
    # so the predeclared spelling is not a guaranteed constant: when
    # it binds a parameter the read carries that binding's deps.
    lib = {
        "lib": {
            "m.go": "package lib\nvar VB map[bool]int64\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(true bool) int64 { return lib.VB[true] }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_map_index_plain_true_stays_dep_free(go_types_helper):
    # `lib.VB[true]` unshadowed — the `universe` reference proves the
    # predeclared constant, so the read is dep-free like a literal.
    lib = {
        "lib": {
            "m.go": "package lib\nvar VB map[bool]int64\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VB[true] }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()


def test_imported_map_index_literal_key_is_admitted(go_types_helper):
    # `lib.VM["k"]` — a literal index carries no dependencies, so the
    # read admits like `lib.VM[k]` does with a modelled key.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VM[\"k\"] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_string_index_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(lib.VStr[0]) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_index_write_is_admitted(go_types_helper):
    # `lib.VA[i] = v` — an imported member write: the store mutates
    # package state, recorded as an imported transfer against the
    # member like every other imported var write.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.VA[0] = v\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["VA"]["id"] and write.arguments == ()


def test_imported_computed_operand_index_stays_closed(go_types_helper):
    # `f()[i]` — the operand names no member.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func g() []int64 { return lib.VA }\n"
        "func F() int64 { return g()[0] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_var_write_is_admitted(go_types_helper):
    # `lib.V = v` — a plain imported var write: external mutation,
    # recorded transfer, no result dependency from the stored value.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.V = lib.T(v)\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["V"]["id"]


def test_imported_var_compound_write_is_admitted(go_types_helper):
    # `lib.V += v` — a compound imported var write evaluates the RHS
    # and records the same mutation transfer.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.V += lib.T(v)\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["V"]["id"]


def test_dot_imported_var_write_is_admitted(go_types_helper):
    # `V = v` under `import . "lib"` — the member record decides the
    # write target exactly like `lib.V = v`.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(v int64) int64 { V = T(v)\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_index_write_evaluates_index_calls(go_types_helper):
    # `lib.VA[lib.V.M(0)] = v` — the index expression still evaluates
    # for its calls: the method call's transfer must appear beside
    # the write transfer.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.VA[lib.V.M(v)] = v\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    calls = [c for c in result.calls if c.imported]
    # The write transfer plus the `lib.V` member read's transfer and
    # the method call — silently dropping the index would leave only
    # the write transfer.
    assert len(calls) >= 2


def test_imported_map_write_is_admitted(go_types_helper):
    # `lib.VM["k"] = v` — a map member write mutates the same external
    # state even though map index *reads* stay closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.VM[\"k\"] = v\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["VM"]["id"]


def test_imported_nested_index_write_is_admitted(go_types_helper):
    # `lib.V2[i][j] = v` — a nested index still resolves to the `V2`
    # member through the operand chain.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.V2[0][1] = v\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["V2"]["id"]


def test_imported_member_write_flags_stale_dependents(go_types_helper):
    # Redeclaring `T` flags `F` — `lib.VT[0] = v` pinned the element's
    # named identity like the read side does.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.VT[0] = lib.T(v)\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB["lib"])
    lib2["t.go"] = "package lib\ntype T int32\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_member_write_pins_member_type(go_types_helper):
    # Redeclaring `S` flags `F` — `lib.VS.F = v` pinned the member's
    # declared type identity.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 {\n"
        "\tlib.VS.F = v\n"
        "\treturn 0\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB["lib"])
    lib2["m.go"] = METHOD_LIB["lib"]["m.go"].replace(
        "type S struct{ F int64 }", "type S struct{ F int32 }"
    )
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_computed_operand_write_stays_closed(go_types_helper):
    # `g()[0] = v` — a computed operand names no member, so the write
    # stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func g() []int64 { return lib.VA }\n"
        "func F(v int64) int64 { g()[0] = v\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_deref_member_write_is_admitted(go_types_helper):
    # `*lib.PV = v` — a dereference store through an imported
    # pointer-typed var mutates package state exactly like `lib.V = v`:
    # the store carries no result dependency, `effects` reports
    # `unknown`, and the member's own identity records the write.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { *lib.PV = lib.T(v)\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["PV"]["id"]


def test_imported_deref_member_write_dot_import(go_types_helper):
    # `*PV = v` — the dot-imported form resolves the same member.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(v int64) int64 { *PV = T(v)\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_deref_field_member_write_is_admitted(go_types_helper):
    # `*lib.VS2.P = v` — a dereference store through an imported
    # pointer-typed *field* member resolves the field like a field
    # read: the write records the field member's identity while the
    # base member's identity pins beside the pointee `T`'s.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { *lib.VS2.P = lib.T(v)\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    (write,) = [
        c for c in result.calls if c.imported and len(c.arguments) == 0
    ]
    assert write.target == members["P"]["id"]
    assert members["VS2"]["id"] in result.pinned
    assert members["T"]["id"] in result.pinned


def test_imported_deref_field_member_write_dot_import(go_types_helper):
    # `*VS2.P = v` — the dot-imported field store resolves the same
    # member pair.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(v int64) int64 { *VS2.P = T(v)\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_deref_field_member_write_folds_into_escaped(
    go_types_helper,
):
    # `*lib.VS2.P = v` where `lib.VS2.P` may hold `&x` — the same
    # escaped-binding fold `*lib.PV = v` uses: `x` picks up the
    # stored value's dependencies.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { x := lib.T(0)\n"
        "\tlib.VS2.P = &x\n"
        "\t*lib.VS2.P = lib.T(v)\n\treturn int64(x) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_imported_deref_field_member_unnamed_pointee_is_admitted(
    go_types_helper,
):
    # `*lib.VS3.PU = v` — the field member's pointee tree names
    # nothing, so `pointee_type_ids` is the empty list and the field
    # member's own identity covers the declaration, exactly like
    # `*lib.PU = v` admits.
    lib = {
        "lib": {
            "s.go": "package lib\ntype S3 struct{ PU *int64 }\nvar VS3 S3\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { *lib.VS3.PU = v\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, lib)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    (write,) = [
        c for c in result.calls if c.imported and len(c.arguments) == 0
    ]
    assert write.target == members["PU"]["id"]


def test_imported_deref_member_inc_unnamed_pointee_is_admitted(
    go_types_helper,
):
    # `(*lib.PU)++` — PU is `*int64`; the pointee tree names nothing,
    # so `pointee_type_ids: []` and the member's own identity covers
    # the whole declaration — the inc admits like `*lib.PV = v`.
    files = _files_member_inc("(*lib.PU)++")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_imported_deref_member_write_unnamed_pointee_is_admitted(
    go_types_helper,
):
    # `*lib.PU = v` — the fully unnamed `*int64` pointee resolves to
    # an empty `pointee_type_ids`; PU's own member identity covers
    # the declaration a redeclaration would change.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { *lib.PU = v\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    assert members["PU"]["pointee_type_ids"] == []
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["PU"]["id"]


def test_imported_deref_index_write_unnamed_pointee_is_admitted(
    go_types_helper,
):
    # `(*lib.PA)[i] = v` — PA is `*[4]int64`; the unnamed array
    # pointee resolves to `[]` like `*int64`, so the write admits
    # and the index still evaluates.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i int64, v int64) int64 { (*lib.PA)[i] = v\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_chan_pointee_declares_elem_member(go_types_helper):
    # `PCH` is `*chan T`: the pointee walk recurses a channel's
    # element like a slice or map, so `T` declares on
    # `pointee_type_ids` — and its member record is emitted too, or
    # pinning the id would flag `stale_dependents` forever.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { *lib.PCH = nil\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    assert members["PCH"]["pointee_type_ids"] == [members["T"]["id"]]


def test_imported_deref_member_write_struct_pointee_stays_closed(
    go_types_helper,
):
    # `*lib.PSTR = v` — `*struct{ F T }` hides a named use inside an
    # anonymous shape the key cannot declare, so no
    # `pointee_type_ids` is emitted and the store stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { *lib.PSTR = *lib.PSTR\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    assert "pointee_type_ids" not in members["PSTR"]
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_deref_member_write_flags_stale_dependents(go_types_helper):
    # Redeclaring `T` flags `F` — `*lib.PV = v` pinned the pointee's
    # named identity through the pointer element fact.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { *lib.PV = lib.T(v)\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB["lib"])
    lib2["t.go"] = "package lib\ntype T int32\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_deref_pointer_write_deep_pointee_pins_named(
    go_types_helper,
):
    # `*lib.PPV = lib.PV` — PPV is `**T`: the fact's `type_id` is
    # empty because the stored `*T` is unnamed, but `pointee_type_ids`
    # declares the `T` use inside the pointee tree, so the store
    # admits and pins `T` against redeclaration.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { *lib.PPV = lib.PV\n\treturn 0 }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    assert members["PPV"]["pointee_type_ids"] == [members["T"]["id"]]
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert members["T"]["id"] in result.pinned


def test_imported_double_deref_member_write_is_admitted(
    go_types_helper,
):
    # `**lib.PPV = v` — two dereferences deep; `T` still pins through
    # `pointee_type_ids`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { **lib.PPV = lib.T(v)\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_imported_deref_write_computed_pointer_stays_closed(go_types_helper):
    # `*g() = v` — a call result names no member, so the dereference
    # store stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func g() *lib.T { return lib.PV }\n"
        "func F(v int64) int64 { *g() = lib.T(v)\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_deref_member_write_folds_into_escaped_binding(
    go_types_helper,
):
    # `lib.PV = &x; *lib.PV = lib.T(y)` — the member may point at `x`,
    # so the deref store unions the stored value's dependencies into
    # the escaped binding: `return x` reports `y` too.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) lib.T {\n"
        "\tlib.PV = &x\n"
        "\t*lib.PV = lib.T(y)\n"
        "\treturn x\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"


def test_imported_deref_member_write_no_escape_keeps_deps(
    go_types_helper,
):
    # Without an earlier `&x` the deref store cannot alias `x` — its
    # dependencies stay unchanged.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) lib.T {\n"
        "\t*lib.PV = lib.T(y)\n"
        "\treturn x\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_parenthesized_member_write_is_admitted(go_types_helper):
    # `(lib.V) = v` — parentheses around the LHS do not change the
    # write target.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { (lib.V) = lib.T(v)\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_dot_imported_member_field_write_is_admitted(go_types_helper):
    # `VS.F = v` under `import . "lib"` — the operand chain bottoms
    # out on a bare dot-imported name.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(v int64) int64 {\n"
        "\tVS.F = v\n"
        "\treturn 0\n}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_dot_imported_index_write_is_admitted(go_types_helper):
    # `VA[i] = v` under `import . "lib"`.
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(v int64) int64 { VA[0] = v\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_index_write_evaluates_member_reads(go_types_helper):
    # `lib.VA[lib.V.M(0)] = v` already covers calls; `lib.VA[lib.V]`
    # needs the member read's own pin — dropping it would hide a `T`
    # redeclaration from `stale_dependents`.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.VA[lib.V] = v\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    calls = [c for c in result.calls if c.imported]
    # The write transfer plus the `lib.V` member read's transfer.
    assert len(calls) >= 2


def test_member_write_inner_indices_evaluate_first(go_types_helper):
    # `lib.V2[lib.Set(&x, y)][lib.H(x)] = v` — Go evaluates indices
    # inside-out, so `lib.H`'s recorded argument must carry `x`'s
    # post-`Set` dependencies `{x, y}`, not the pre-call `{x}`.
    lib = {
        "lib": {
            "s.go": "package lib\ntype T int64\n"
            "func Set(p *T, v int64) int64 { *p = T(v); return 0 }\n"
            "func H(v T) int64 { return 0 }\n"
            "var V2 [][]int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x lib.T, y int64) lib.T {\n"
        "\tlib.V2[lib.Set(&x, y)][lib.H(x)] = 0\n"
        "\treturn x\n}\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    h_call = next(
        c for c in result.calls if len(c.arguments) == 1
    )
    assert h_call.arguments == (frozenset({0, 1}),)



def test_member_write_nested_elem_pin_flags_stale(go_types_helper):
    # `lib.VTT` is `[][]T` — the named element sits two `elem` hops
    # down, so only a recursive element pin lets `T`'s redeclaration
    # flag the summary stale.
    lib = {
        "lib": {
            "s.go": "package lib\nvar VTT [][]T\n",
            "t.go": "package lib\ntype T int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { lib.VTT[0][0] = 0\n\treturn 0 }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(lib["lib"])
    lib2["t.go"] = "package lib\ntype T int32\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def _files_member_read(body: str, decl: str = "func F() int64") -> dict[str, str]:
    return {
        "a.go": "package p\nimport \"lib\"\n" + decl + " { " + body + " }\n"
    }


def test_imported_field_read_is_admitted(go_types_helper):
    # `lib.VS2.N` — a scalar field read of an imported struct var is
    # dep-free like the member read itself, records the transfer on
    # the field's own identity, and reports `effects` as `unknown`.
    files = _files_member_read("return lib.VS2.N")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    members = {m.name: m for m in snapshot.imported_members}
    calls = [c for c in result.calls if c.imported]
    assert len(calls) == 1
    assert calls[0].target == members["N"].id


def test_index_element_field_read_is_admitted(go_types_helper):
    # `lib.VSM["k"].F` — a field of an index-read's struct element is
    # dep-free like `lib.VS.F`, recording the transfer on the field's
    # identity; the literal index carries no dependencies.
    files = _files_member_read("return lib.VSM[\"k\"].F")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    members = {m.name: m for m in snapshot.imported_members}
    calls = [c for c in result.calls if c.imported]
    assert len(calls) == 1
    assert calls[0].target == members["F"].id


def test_index_element_field_read_carries_index_deps(go_types_helper):
    # `lib.VSS[i].F` — the index's own dependencies carry like the
    # index read's `lib.VM[k]` rule.
    files = _files_member_read("return lib.VSS[i].F", "func F(i int64) int64")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_index_element_field_read_dot_import(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F() int64 { return VSM[\"k\"].F }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_index_element_field_read_pins_element_type(go_types_helper):
    # `lib.VSM["k"].F` pins `S` — redeclaring the element's own type
    # flags the summary stale like `lib.VS.F` pinning `S2` does.
    files = _files_member_read("return lib.VSM[\"k\"].F")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    vsm = next(m for m in snapshot.imported_members if m.name == "VSM")
    assert vsm.type.elem.type_id in result.pinned


def test_deref_write_through_index_element_evaluates_indexes(
    go_types_helper,
):
    # `*lib.VSS[lib.Idx(&x, y)].P = 0` — the indexes inside the
    # field operand still evaluate: `Idx`'s write through `&x` folds
    # into `x` exactly like `lib.Set(&x, y)` does.
    lib = {
        "lib": {
            "s.go": (
                "package lib\n"
                "type T int64\ntype S struct{ P *int64 }\n"
                "var VSS []S\n"
                "func Idx(p *int64, v int64) int64 { *p = v; return 0 }\n"
            ),
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(y int64) int64 {\n"
        "\tvar x int64\n"
        "\t*lib.VSS[lib.Idx(&x, y)].P = 0\n"
        "\treturn x\n}\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_computed_index_element_field_read_stays_closed(go_types_helper):
    # `g()[0].F` — the operand names no imported member, so the field
    # read stays closed like `f()[i]` does.
    files = _files_member_read(
        "return g()[0].F", "func g() []lib.S { return nil }\nfunc F() int64"
    )
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_field_read_flags_stale_dependents(go_types_helper):
    # Redeclaring `S2` flags `F` — `lib.VS2.N` pinned the struct var's
    # declared type identity.
    files = _files_member_read("return lib.VS2.N")
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB["lib"])
    lib2["m.go"] = lib2["m.go"].replace(
        "type S2 struct{ N int64", "type S2 struct{ N int32"
    )
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_field_read_pointer_field_is_admitted(go_types_helper):
    files = _files_member_read("p := lib.VS2.P\n\t_ = p\n\treturn 0")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    members = {m.name: m for m in snapshot.imported_members}
    calls = [c for c in result.calls if c.imported]
    assert any(c.target == members["P"].id for c in calls)


def test_imported_field_read_string_field_stays_closed(go_types_helper):
    files = _files_member_read("return int64(len(lib.VS2.G))")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_field_read_dot_imported_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F() int64 { return VS2.N }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_field_read_parenthesized_is_admitted(go_types_helper):
    files = _files_member_read("return (lib.VS2).N")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_imported_field_read_method_member_stays_closed(go_types_helper):
    # A method *value* `f := lib.VS.PF` selects a method member, not a
    # field — method values keep their own gate even though the call
    # `lib.VS.PF()` admits as a composite receiver.
    files = _files_member_read(
        "f := lib.VS.PF\n\treturn f()", decl="func F() int64"
    )
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_bound_base_field_read_is_admitted(go_types_helper):
    # `t.N` — a scalar field read through a bound `*S2` is caller
    # state like `lib.VS2.N`: the root pointer's provenance deps, an
    # imported transfer on the field's identity, `effects` unknown.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2) int64 { return t.N }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    members = {m.name: m for m in snapshot.imported_members}
    calls = [c for c in result.calls if c.imported]
    assert len(calls) == 1
    assert calls[0].target == members["N"].id


def test_bound_base_field_read_pointer_field_is_admitted(go_types_helper):
    # `t.P` — a pointer-typed field admits the same way.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2) int64 { p := t.P\n\t_ = p\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    members = {m.name: m for m in snapshot.imported_members}
    calls = [c for c in result.calls if c.imported]
    assert any(c.target == members["P"].id for c in calls)


def test_bound_base_field_read_parenthesized_base_is_admitted(
    go_types_helper,
):
    # `(t).N` — parentheses around the base change nothing.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2) int64 { return (t).N }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available


def test_bound_base_field_read_local_pointer_is_admitted(go_types_helper):
    # `q := t; q.N` — a bound local `*S2` admits the same way,
    # reporting the copied pointer's provenance deps.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2) int64 { q := t\n\treturn q.N }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_bound_base_field_read_no_escaped_union(go_types_helper):
    # A `*S` pointee is a struct — it can never alias a tracked
    # scalar binding, so escaped bindings do NOT union into the
    # result (unlike `*t` scalar derefs): only the root's own
    # provenance and indirect stores apply.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2, x lib.T, y lib.T) int64 {\n"
        "\t_ = &x\n\tx = y\n\treturn t.N }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_bound_base_field_read_flags_stale_dependents(go_types_helper):
    # Redeclaring `S2` flags `F` — `t.N` pinned the pointee's declared
    # type identity.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2) int64 { return t.N }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = dict(METHOD_LIB["lib"])
    lib2["m.go"] = lib2["m.go"].replace(
        "type S2 struct{ N int64", "type S2 struct{ N int32"
    )
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2), lib2, target_arch="amd64"
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_bound_base_field_read_deref_base_is_admitted(go_types_helper):
    # `(*t).N` — an explicit dereference of the bound pointer before
    # the selection, the same auto-deref spelled out.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2) int64 { return (*t).N }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_bound_base_field_read_double_deref_stays_closed(go_types_helper):
    # `(**t).N` — one deref leaves a `*S2` operand, not an identifier,
    # and the `**S2` fact names no named pointee anyway.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t **lib.S2) int64 { return (**t).N }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_bound_base_field_read_nested_is_admitted(go_types_helper):
    # `t.W.N` — the operand `t.W` resolves to field `W`'s `*W2`
    # member, so `N` resolves one level deeper on `W2`. Both `S2`
    # and `W2` pin; the read reports the root pointer's provenance.
    lib = {
        "lib": {
            "m.go": "package lib\ntype T int64\n"
            "type W2 struct{ N int64 }\ntype S2 struct{ W *W2 }\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2) int64 { return t.W.N }\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    # Every member the chain traverses pins — redeclaring `W` itself
    # (say to a struct value) must flag the summary, so the
    # intermediate field member joins the pointees.
    assert {members["S2"]["id"], members["W"]["id"], members["W2"]["id"]} <= set(
        result.pinned
    )


def test_bound_base_field_read_nested_scalar_stays_closed(go_types_helper):
    # `t.A.B` — the intermediate field `A` is a struct *value*, not
    # a pointer, so the chain cannot walk deeper through it.
    lib = {
        "lib": {
            "m.go": "package lib\ntype T int64\n"
            "type W2 struct{ N int64 }\ntype S2 struct{ W *W2 }\n"
            "type S3 struct{ B int64 }\ntype S4 struct{ A S3 }\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S4) int64 { return t.A.B }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_nested_field_write_is_admitted(go_types_helper):
    # `t.W.N = v` — the operand chain `t.W` resolves `W`'s `*W2`
    # member to `W2`, so the deepest pointee records the mutation and
    # every traversed `type` member pins. The store is dep-free like
    # `t.F = v`.
    lib = {
        "lib": {
            "m.go": "package lib\n"
            "type W2 struct{ N int64 }\ntype S2 struct{ W *W2 }\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2, v int64) int64 {\n"
        "\tt.W.N = v\n"
        "\treturn 0\n}\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["W2"]["id"] and write.arguments == ()


def test_nested_field_write_folds_deps_into_root(go_types_helper):
    # `t.W.N = v; return t.PF()` — the stored value's dependencies
    # accumulate into the root binding `t`, which a later method call
    # on `t` can observe.
    lib = {
        "lib": {
            "m.go": "package lib\n"
            "type W2 struct{ N int64 }\ntype S2 struct{ W *W2 }\n"
            "func (s *S2) PF() int64 { return 0 }\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2, v int64) int64 {\n"
        "\tt.W.N = v\n"
        "\treturn t.PF()\n}\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_nested_field_write_deref_base_is_admitted(go_types_helper):
    # `(*t.W).N = v` — the dereference of the pointer-typed field
    # `W` spells the same nested walk out; the deepest pointee still
    # records the mutation.
    lib = {
        "lib": {
            "m.go": "package lib\n"
            "type W2 struct{ N int64 }\ntype S2 struct{ W *W2 }\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2, v int64) int64 {\n"
        "\t(*t.W).N = v\n"
        "\treturn 0\n}\n"
    }
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["W2"]["id"] and write.arguments == ()


def test_nested_field_write_receiver_observes_folded_deps(go_types_helper):
    # `t.W.N = v; return t.W.Get()` — the write folds v's deps into
    # the root binding `t`, and the method call's nested-selector
    # receiver `t.W` can observe them, so the result carries {0, 1}.
    lib = {
        "lib": {
            "m.go": "package lib\n"
            "type W2 struct{ N int64 }\ntype S2 struct{ W *W2 }\n"
            "func (w *W2) Get() int64 { return w.N }\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2, v int64) int64 {\n"
        "\tt.W.N = v\n"
        "\treturn t.W.Get()\n}\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0, 1})


def test_nested_field_write_struct_value_stays_closed(go_types_helper):
    # `t.A.B = v` — the intermediate field `A` is a struct *value*,
    # not a pointer, so the chain cannot walk deeper through it.
    lib = {
        "lib": {
            "m.go": "package lib\n"
            "type S3 struct{ B int64 }\ntype S4 struct{ A S3 }\n"
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S4, v int64) int64 {\n"
        "\tt.A.B = v\n"
        "\treturn 0\n}\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_bound_base_field_read_string_field_stays_closed(go_types_helper):
    # `t.G` — a non-scalar field keeps the read closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S2) int64 { return int64(len(t.G)) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_bound_base_field_read_method_value_stays_closed(go_types_helper):
    # `t.PF` selects a method member — method values keep their own
    # gate; only calls admit.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S) int64 { _ = t.PF\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_field_read_flags_base_redeclaration(go_types_helper):
    # `VS` lives in a different file than `S`/`N` — redeclaring it
    # leaves every recorded field identity unchanged, so only the
    # pinned base-member identity flags the summary stale.
    lib = {
        "lib": {
            "s.go": "package lib\ntype S2 struct{ N int64 }\n",
            "v.go": "package lib\nvar VS2 S2\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VS2.N }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {"lib": dict(lib["lib"])}
    lib2["lib"]["v.go"] = "package lib\nvar VS2 S2\nvar VS2B S2\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]),
        lib2["lib"],
        target_arch="amd64",
    )
    known = {b.id for b in snapshot2.bindings}
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def _files_member_inc(body: str, decl: str = "func F(v int64) int64") -> dict[str, str]:
    return {
        "a.go": "package p\nimport \"lib\"\n"
        f"{decl} {{ {body}\n\treturn 0 }}\n"
    }


def test_imported_member_inc_is_admitted(go_types_helper):
    # `lib.V++` mutates package state like `lib.V = v` — dep-free
    # external mutation, recorded transfer on the member identity.
    files = _files_member_inc("lib.V++")
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["V"]["id"]
    assert write.arguments == ()
    assert write.result == frozenset()


def test_imported_member_dec_is_admitted(go_types_helper):
    files = _files_member_inc("lib.V--")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert any(c.imported for c in result.calls)


def test_imported_member_inc_dot_import(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(v int64) int64 { V++\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert any(c.imported for c in result.calls)


def test_imported_member_inc_index_evaluates_calls(go_types_helper):
    # `lib.VA[lib.V.M(v)]++` — the index still evaluates for its calls.
    files = _files_member_inc("lib.VA[lib.V.M(v)]++")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    calls = [c for c in result.calls if c.imported]
    assert len(calls) >= 2


def test_imported_member_inc_field_is_admitted(go_types_helper):
    # `lib.VS.F++` resolves to the struct var's member write, like
    # `lib.VS.F = v` does.
    files = _files_member_inc("lib.VS.F++")
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    (write,) = [c for c in result.calls if c.imported]
    assert write.target == members["VS"]["id"]


def test_imported_member_inc_flags_stale_dependents(go_types_helper):
    files = _files_member_inc("lib.V++")
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {"lib": dict(METHOD_LIB["lib"])}
    lib2["lib"]["t.go"] = "package lib\ntype T int32\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]),
        lib2["lib"],
        target_arch="amd64",
    )
    known = {b.id for b in snapshot2.bindings}
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_bound_base_field_inc_is_admitted(go_types_helper):
    # `t.F++` on a bound pointer param — mutates the pointee's caller
    # memory like `t.F = v`: the mutation records on the pointee's
    # identity and `effects` reports `unknown`, while the base
    # binding's deps carry on (the stored value is the field's own).
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S) int64 { t.F++\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"


@pytest.mark.parametrize("op", ["++", "--"])
def test_bound_base_field_inc_dec_variants(go_types_helper, op):
    # `t.N++` / `t.N--` on `*lib.S2` — and the explicit-deref
    # `(*t).N++` spelling — route through the same bound-field gate.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        f"func F(t *lib.S2) int64 {{ t.N{op}\n\t(*t).N{op}\n\treturn 0 }}\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"


def test_bound_base_field_inc_preserves_base_deps(go_types_helper):
    # `t.F++; return *t` — the increment is provenance-preserving
    # like `(*p)++`: the external mutation does not inject deps, so
    # `*t` still yields the same dep-free external read.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t *lib.S, x int64) int64 { t.F++\n\treturn x }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_imported_deref_inc_is_admitted(go_types_helper):
    # `(*lib.PV)++` — the dereference operand resolves the imported
    # pointer var, so the inc/dec gate routes it like `lib.V++`.
    files = _files_member_inc("(*lib.PV)++")
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"


def test_imported_map_index_read_is_admitted(go_types_helper):
    # `lib.VMK[i]` — a single-value map index read: the value is
    # external state, so only the index's own dependencies carry.
    # (`map[string]` stays unreachable — a string key literal is not
    # a modelled expression.)
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k lib.MK) int64 { return lib.VMK[k] }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    (read,) = [c for c in result.calls if c.imported]
    assert read.target == members["VMK"]["id"]


def test_imported_map_index_read_dot_import(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(k MK) int64 { return VMK[k] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_imported_map_index_read_named_key_pins(go_types_helper):
    # `lib.VMK[0]` pins the named key `MK`'s identity: redeclaring MK
    # in its own file leaves VMK's member id untouched, so only the
    # key pin flags the summary stale. A literal index keeps the key
    # pin unconfounded by a `k lib.MK` parameter's own type pin.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.VMK[0] }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {"lib": dict(METHOD_LIB["lib"])}
    lib2["lib"]["k.go"] = "package lib\ntype MK int32\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]),
        lib2["lib"],
        target_arch="amd64",
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_map_write_pins_named_key(go_types_helper):
    # `lib.VMK[0] = v` pins the key identity too — the literal index
    # again isolates the key pin from a parameter's own type pin.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(v int64) int64 { lib.VMK[0] = v\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    lib2 = {"lib": dict(METHOD_LIB["lib"])}
    lib2["lib"]["k.go"] = "package lib\ntype MK int32\n"
    snapshot2 = load_go_package_snapshot(
        package_report(go_types_helper, lib2["lib"]),
        lib2["lib"],
        target_arch="amd64",
    )
    known = {b.id for b in snapshot.bindings} | {
        b.id for b in snapshot2.bindings
    }
    f_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    assert summaries.stale_dependents(known) == frozenset({f_id})


def test_imported_map_index_read_struct_value_stays_closed(go_types_helper):
    # `lib.VSM[k]` — a struct-typed value cannot join the dep model.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { _ = lib.VSM[\"k\"]\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_map_index_read_comma_ok_is_admitted(go_types_helper):
    # `v, ok := lib.VMI[k]` — the comma-ok form binds two names; the
    # presence flag conservatively takes the read's deps too.
    lib = {"lib": {"m.go": "package lib\nvar VMI map[int64]int64\n"}}
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 { v, ok := lib.VMI[k]\n"
        "\tif ok { return v }\n\treturn 0 }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_imported_map_index_read_comma_ok_var_decl(go_types_helper):
    # `var v, ok = lib.VMI[k]` — the var-declaration path admits the
    # comma-ok pair the same way.
    lib = {"lib": {"m.go": "package lib\nvar VMI map[int64]int64\n"}}
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 { var v, ok = lib.VMI[k]\n"
        "\tif ok { return v }\n\treturn 0 }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_imported_map_index_read_comma_ok_assign(go_types_helper):
    # `v, ok = lib.VMI[k]` — a plain assignment binds the comma-ok
    # pair into existing bindings the same way.
    lib = {"lib": {"m.go": "package lib\nvar VMI map[int64]int64\n"}}
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 {\n"
        "\tvar v int64\n\tvar ok bool\n"
        "\tv, ok = lib.VMI[k]\n"
        "\tif ok { return v }\n\treturn 0 }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_imported_map_index_read_comma_ok_composite_stays_closed(
    go_types_helper,
):
    # `v, ok := lib.VSM[k]` — a composite-typed map element stays
    # closed, like the single-value read.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { v, ok := lib.VSM[\"k\"]\n"
        "\tif ok { return int64(v.F) }\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_map_index_read_comma_ok_nested_is_admitted(
    go_types_helper,
):
    # `v, ok := lib.VM2[k1][k2]` — a comma-ok pair on a nested map
    # chain: the outermost index's container is the inner map, so
    # the read binds the pair like the flat form.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 { v, ok := lib.VM2[\"a\"][\"b\"]\n"
        "\tif ok { return v }\n\treturn k }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_imported_map_index_read_comma_ok_nested_index_deps(
    go_types_helper,
):
    # The nested read still unions every level's index deps — a
    # computed outer key carries its own dependencies.
    lib = {
        "lib": {
            "m.go": "package lib\nvar VIM map[int64]map[string]int64\n",
            "f.go": "package lib\nfunc K(k int64) int64 { return k }\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 {\n"
        "\tv, ok := lib.VIM[lib.K(k)][\"b\"]\n"
        "\tif ok { return v }\n\treturn 0 }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_map_index_read_comma_ok_slice_root_is_admitted(
    go_types_helper,
):
    # `v, ok := lib.V[i]["k"]` — the outermost index's container is
    # the map element of an imported slice: the root need not be a
    # map itself.
    lib = {
        "lib": {
            "m.go": "package lib\nvar VSM []map[string]int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 { v, ok := lib.VSM[k][\"b\"]\n"
        "\tif ok { return v }\n\treturn 0 }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_imported_map_index_read_comma_ok_map_value_stays_closed(
    go_types_helper,
):
    # `v, ok := lib.VM2["a"]` — one level short: the read's value is
    # a map (unrepresentable as a binding), so the pair stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { v, ok := lib.VM2[\"a\"]\n"
        "\tif ok && v == nil { return 1 }\n\treturn 0 }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_len_of_container_var_is_admitted(go_types_helper):
    # `len(lib.VA)` — an external length read: dep-free like the
    # member itself, records the imported transfer.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 { return k + int64(len(lib.VA)) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_imported_cap_of_container_var_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(cap(lib.VA)) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_len_of_string_var_is_admitted(go_types_helper):
    lib = {
        "lib": {
            "m.go": "package lib\nvar VS string\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(len(lib.VS)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_len_computed_operand_stays_closed(go_types_helper):
    # `len(lib.VS2.G)` — a string field, not a member name or an
    # index chain on one: the builtin stays opaque.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(len(lib.VS2.G)) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_len_of_indexed_container_is_admitted(go_types_helper):
    # `len(lib.V2[i])` — the element `[]int64` is external state like
    # the var itself: dep-free apart from the index's deps.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 { return k + int64(len(lib.V2[0])) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"


def test_imported_len_of_indexed_container_carries_index_deps(
    go_types_helper,
):
    # `len(lib.V2[k])` — the length itself is dep-free, but the index
    # expression's dependencies join the result like the index read's.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(k int64) int64 { return int64(len(lib.V2[k])) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset({0})


def test_imported_cap_of_indexed_container_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(cap(lib.V2[0])) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_len_of_map_element_is_admitted(go_types_helper):
    # `len(lib.VM2["a"])` — the map value is itself a map, and `len`
    # on a map is valid Go: the external read admits dep-free.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(len(lib.VM2[\"a\"])) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.return_dependencies == frozenset()
    assert result.effects == "unknown"


def test_imported_len_of_parenthesized_chain_carries_inner_index_deps(
    go_types_helper,
):
    # `len((lib.V3[i])[j])` — parentheses inside the chain must not
    # hide the inner index's dependencies.
    lib = {
        "lib": {
            "m.go": "package lib\nvar V3 [][][]int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(i, j int64) int64 { return int64(len((lib.V3[i])[j])) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"


def test_imported_len_of_channel_element_stays_closed(go_types_helper):
    # `len(lib.VC2[i])` — `len` on a channel is valid Go, but the
    # element's kind is not a modelled container: stays opaque.
    lib = {
        "lib": {
            "m.go": "package lib\nvar VC2 []chan int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(len(lib.VC2[0])) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_len_of_call_result_stays_closed(
    go_types_helper,
):
    # `len(g())` — a call result names no imported member: stays
    # opaque.
    files = {
        "a.go": "package p\n"
        "func g() []int64 { return nil }\n"
        "func F() int64 { return int64(len(g())) }\n"
    }
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_len_pins_inner_named_types(go_types_helper):
    # `len(lib.VMK)` — the map key's named identity pins too, so a
    # `MK` redeclaration flags the summary via stale_dependents.
    files = {
        "a.go": "package p\nimport \"lib\"\nvar _ lib.MK\n"
        "func F() int64 { return int64(len(lib.VMK)) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, METHOD_LIB)
    )
    assert report["status"] == "ok"
    members = {m["name"]: m for m in report["imported_members"]}
    snapshot = _method_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert members["MK"]["id"] in result.pinned


def test_imported_len_chan_var_stays_closed(go_types_helper):
    # `len(lib.VC)` on `var VC chan int64` — a valid call whose
    # operand's fact kind is not a modelled container: stays opaque.
    lib = {
        "lib": {
            "m.go": "package lib\nvar VC chan int64\n",
        }
    }
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return int64(len(lib.VC)) }\n"
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, lib),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


VARIADIC_LIB = {
    "lib": {
        "v.go": "package lib\n"
        "func WV(vs ...int64) int64 { return 0 }\n"
        "var VA []int64\n",
        "t.go": "package lib\ntype T int64\n"
        "func (t T) VM(vs ...int64) int64 { return 0 }\n",
    }
}


def _variadic_snapshot_for(go_types_helper, files):
    return load_go_package_snapshot(
        package_report_imports(go_types_helper, files, VARIADIC_LIB),
        files,
        target_arch="amd64",
    )


def test_imported_variadic_call_is_admitted(go_types_helper):
    # A variadic imported callee admits positionally: each argument is
    # an independent expression and the opaque-callee over-approximation
    # already unions every argument into the result's dependencies.
    # Distinct arguments prove each is evaluated on its own.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64, y int64) int64 { return lib.WV(x, y) }\n"
    }
    snapshot = _variadic_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    (call,) = result.calls
    assert call.imported
    assert call.arguments == (frozenset({0}), frozenset({1}))
    members = {m.name: m for m in snapshot.imported_members}
    assert call.target == members["WV"].id


def test_imported_variadic_call_zero_args_is_admitted(go_types_helper):
    # `lib.WV()` evaluates no arguments and contributes no dependencies.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.WV() + x }\n"
    }
    snapshot = _variadic_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    (call,) = result.calls
    assert call.imported and call.arguments == ()


def test_imported_variadic_dot_import_is_admitted(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64, y int64) int64 { return WV(x, y) }\n"
    }
    snapshot = _variadic_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_imported_variadic_method_call_is_admitted(go_types_helper):
    # A variadic method call admits too — receiver and arguments are
    # all evaluated independently into the dependency union.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(t lib.T, x int64, y int64) int64 { return t.VM(x, y) }\n"
    }
    snapshot = _variadic_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1, 2})


def test_imported_variadic_spread_stays_closed(go_types_helper):
    # `lib.WV(lib.VA...)` — the spread argument's recorded span is the
    # operand only, so the call cannot map its argument expressions and
    # stays closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F() int64 { return lib.WV(lib.VA...) }\n"
    }
    snapshot = _variadic_snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_summary_set_manifest_declares_schema_and_context(go_types_helper):
    source, snapshot, summaries = unit(
        go_types_helper, "func F(x int64) int64 { return x }"
    )
    data = summaries.to_dict()
    assert data["schema_version"] == ip.PROFILE
    assert data["context_key"] == summaries.context_key
    assert [f["binding_id"] for f in data["functions"]] == [
        f.binding_id for f in summaries.functions
    ]
    json.dumps(data)


def test_summary_manifest_function_fields(go_types_helper):
    source, snapshot, summaries = unit(
        go_types_helper,
        "func F(x, y int64) int64 { return x + y }\n"
        "func G(a int64) int64 { return F(a, a) }",
    )
    binding_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "G"
    )
    entry = next(
        f
        for f in summaries.to_dict()["functions"]
        if f["binding_id"] == binding_id
    )
    call = next(c for c in entry["calls"])
    assert call["arguments"] == [[0], [0]]
    assert call["result"] == [0]
    assert call["span"]["start"] <= call["span"]["end"]
    assert "imported" not in call
    assert entry["return_dependencies"] == [0]


def test_summary_manifest_omits_unavailable_dependencies(go_types_helper):
    source, snapshot, summaries = unit(
        go_types_helper,
        "func G(){}\nfunc F(x int64) int64 { defer G(); return x }",
    )
    binding_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    entry = next(
        f
        for f in summaries.to_dict()["functions"]
        if f["binding_id"] == binding_id
    )
    # A gap-closed summary never serializes a null dependencies field.
    assert "return_dependencies" not in entry
    assert entry["gaps"]


def test_summary_manifest_marks_imported_transfers(go_types_helper):
    files = {"a.go": IMPORTER}
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, LIB),
        files,
        target_arch="amd64",
    )
    summaries = ip.summarize_go_package(files, snapshot)
    binding_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    entry = next(
        f
        for f in summaries.to_dict()["functions"]
        if f["binding_id"] == binding_id
    )
    (call,) = entry["calls"]
    assert call["imported"] is True


def test_summary_manifest_gap_serializes_span_and_callee(go_types_helper):
    source, snapshot, summaries = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\tif x <= 0 { return 0 }\n"
        "\treturn F(x - 1)\n"
        "}",
    )
    entry = summaries.to_dict()["functions"][0]
    gap = entry["gaps"][0]
    assert gap["reason"] == "recursive_call_graph"
    assert gap.get("callee")
    assert gap["span"] is None or gap["span"]["start"] <= gap["span"]["end"]


def test_summary_manifest_file_span_carries_file_index(go_types_helper):
    files = {
        "a.go": "package p\nfunc F(x int64) int64 { return G(x) }\n",
        "b.go": "package p\nfunc G(y int64) int64 { return y }\n",
    }
    snapshot = load_go_package_snapshot(
        package_report(go_types_helper, files), files, target_arch="amd64"
    )
    summaries = ip.summarize_go_package(files, snapshot)
    binding_id = next(
        f.binding_id
        for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "F"
    )
    entry = next(
        f
        for f in summaries.to_dict()["functions"]
        if f["binding_id"] == binding_id
    )
    assert entry["calls"][0]["span"]["file"] >= 0


def test_summary_manifest_pins_declared_type_identities(go_types_helper):
    source, snapshot, summaries = unit(
        go_types_helper,
        "type T int64\nfunc F(x T) int64 { return int64(x) }",
    )
    entry = summaries.to_dict()["functions"][0]
    assert entry["pinned"]
    assert entry["parameters"][0]["type_id"]


def test_summary_manifest_deterministic_ordering(go_types_helper):
    source, snapshot, summaries = unit(
        go_types_helper,
        "func F(a, b, c int64) int64 { return a + b + c }",
    )
    first, second = summaries.to_dict(), summaries.to_dict()
    assert first == second
    json.dumps(first)


def test_summary_manifest_rejects_foreign_spans():
    gap = ip.SummaryGap("opaque", span=object())
    with pytest.raises(ValueError):
        gap.to_dict()


def _manifest_set():
    """A synthetic declared set — the restore path needs no compiler."""
    named_t = GoType(
        "named", "", 64, True, "p.T",
        elem=GoType("basic", "int64", 64, True, ""),
    )
    fn = ip.FunctionSummary(
        "b1",
        "k",
        (named_t, GoType("basic", "int64", 64, True, "")),
        GoType("basic", "int64", 64, True, ""),
        frozenset({0, 1}),
        (
            ip.CallTransfer(
                FileSpan(0, 10, 20), "callee", (frozenset({0}),), frozenset({0}),
                True,
            ),
        ),
        (ip.SummaryGap("opaque", ByteSpan(1, 5), "m.U"),),
        ("p.T",),
    )
    return ip.GoSummarySet("ctx", (fn,))


def test_summary_manifest_restores_a_declared_set():
    summaries = _manifest_set()
    restored = ip.GoSummarySet.from_dict(summaries.to_dict())
    assert restored == summaries
    assert restored.to_dict() == summaries.to_dict()


def test_summary_manifest_restore_rejects_foreign_schema():
    data = _manifest_set().to_dict()
    data["schema_version"] = "mumei.other/v1"
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_extra_and_missing_keys():
    data = _manifest_set().to_dict()
    data["extra"] = 1
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)
    data = _manifest_set().to_dict()
    del data["context_key"]
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_out_of_range_dependencies():
    data = _manifest_set().to_dict()
    data["functions"][0]["return_dependencies"] = [0, 7]
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_null_dependencies_claim():
    data = _manifest_set().to_dict()
    data["functions"][0]["return_dependencies"] = None
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_duplicate_binding_ids():
    data = _manifest_set().to_dict()
    data["functions"].append(dict(data["functions"][0]))
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_duplicate_pins():
    data = _manifest_set().to_dict()
    data["functions"][0]["pinned"] = ["p.T", "p.T"]
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_inverted_span():
    data = _manifest_set().to_dict()
    data["functions"][0]["gaps"][0]["span"] = {"start": 9, "end": 2}
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_null_call_span():
    data = _manifest_set().to_dict()
    data["functions"][0]["calls"][0]["span"] = None
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_foreign_member_shape():
    data = _manifest_set().to_dict()
    data["functions"][0]["calls"].append({"what": 1})
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_foreign_type_facts():
    data = _manifest_set().to_dict()
    data["functions"][0]["parameters"][0]["signed"] = "yes"
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_bounds_type_nesting():
    nested = {"kind": "pointer", "basic_name": "", "bit_width": 64,
              "signed": None, "type_id": ""}
    tip = nested
    for _ in range(ip.MAX_DEPTH + 5):
        tip = dict(tip)
        tip["elem"] = nested
        nested = tip
    data = _manifest_set().to_dict()
    data["functions"][0]["parameters"][0] = nested
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_restored_set_still_gates_reuse_through_for_function(go_types_helper):
    restored = ip.GoSummarySet.from_dict(_manifest_set().to_dict())
    source, snapshot, _ = unit(
        go_types_helper, "func F(x int64) int64 { return x }"
    )
    with pytest.raises(SnapshotError):
        restored.for_function(source, snapshot, "b1")


def test_summary_manifest_restore_allows_more_than_analysis_bound_functions():
    fn = ip.FunctionSummary(
        "b", "k", (GoType("basic", "int64", 64, True, ""),), None,
        None, (), (ip.SummaryGap("analysis_limit"),),
    )
    data = ip.GoSummarySet(
        "ctx", tuple(replace(fn, binding_id=f"b{i}") for i in range(200))
    ).to_dict()
    assert len(ip.GoSummarySet.from_dict(data).functions) == 200


def test_summary_manifest_restore_rejects_call_dependencies_beyond_parameters():
    data = _manifest_set().to_dict()
    data["functions"][0]["calls"][0]["arguments"] = [[7]]
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)
    data = _manifest_set().to_dict()
    data["functions"][0]["calls"][0]["result"] = [8]
    with pytest.raises(SnapshotError):
        ip.GoSummarySet.from_dict(data)


def test_summary_manifest_restore_rejects_non_dict_spans_as_snapshot_errors():
    for bad in (7, ["start", "end"], "01"):
        data = _manifest_set().to_dict()
        data["functions"][0]["calls"][0]["span"] = bad
        with pytest.raises(SnapshotError):
            ip.GoSummarySet.from_dict(data)


def test_local_struct_value_field_write_single_file_api(
    go_types_helper,
):
    # The single-file `summarize_go` profile carries ByteSpans, not
    # FileSpans — the field-chain check must admit the write there
    # the same way the package profile does.
    source, snapshot, summaries = unit(
        go_types_helper,
        "type P struct{ V int64 }\n"
        "func F(x int64) int64 { st := P{}; st.V = x; return st.V }\n",
    )
    result = named(source, snapshot, summaries)
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects != "unknown"


def test_local_struct_value_interface_field_type_does_not_hide_fields(
    go_types_helper,
):
    # `interface{ M() }` inside a field's type declares a method
    # binding *nested inside P's declaration* — it carries no scope,
    # so it must not act as the boundary that hides `V`.
    files = {
        "a.go": "package p\n"
        "type P struct{ I interface{ M() int64 }; V int64 }\n"
        "func F(x int64) int64 { st := P{}; st.V = x; return st.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects != "unknown"


def test_package_composite_var_field_read_records_transfer(
    go_types_helper,
):
    # `G.V` on a package-level struct var reads external state like
    # `lib.V` — dep-free for the value, and the imported transfer
    # marks `effects` unknown. The target is the *field's* identity.
    files = {
        "a.go": "package p\n"
        "type P struct{ V int64; W int64 }\nvar G P\n"
        "func F(x int64) int64 { return x + G.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    assert len(result.calls) == 1 and result.calls[0].imported
    v_id = next(
        b.id for b in snapshot.bindings
        if b.name == "V" and b.kind == "variable"
    )
    assert result.calls[0].target == v_id


def test_package_composite_var_bare_read_records_transfer(
    go_types_helper,
):
    # A bare `G` read of a composite package var is dep-free like a
    # scalar one — the var's own identity is the transfer target.
    files = {
        "a.go": "package p\n"
        "type P struct{ V int64 }\nvar G P\n"
        "func F(x int64) int64 { _ = G; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    g_id = next(
        b.id for b in snapshot.bindings
        if b.name == "G" and b.kind == "variable"
    )
    assert result.calls[0].target == g_id


def test_package_composite_var_writes_record_transfers(
    go_types_helper,
):
    # `G.V = v`, `G.A.N = v`, and `G = P{...}` all mutate package
    # state: the stored deps drop and the var's identity records the
    # mutation — nested selects resolve to the same var binding.
    files = {
        "a.go": "package p\n"
        "type Q struct{ N int64 }\ntype P struct{ A Q; V int64 }\n"
        "var G P\n"
        "func F(x int64) int64 {\n"
        "\tG.V = x\n\tG.A.N = x\n\tG = P{V: x}\n\treturn x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "unknown"
    g_id = next(
        b.id for b in snapshot.bindings
        if b.name == "G" and b.kind == "variable"
    )
    assert len(result.calls) == 3
    assert all(c.imported and c.target == g_id for c in result.calls)


def test_package_container_var_index_write_and_read(
    go_types_helper,
):
    # `GA[i] = v` stores into package state (deps drop, var identity
    # records); `GA[i]` reads it (dep-free, same target).
    files = {
        "a.go": "package p\nvar GA [4]int64\n"
        "func F(x int64) int64 { GA[1] = x; return x }\n"
        "func G(x int64) int64 { return GA[1] + x }\n",
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    f = named_package(files, snapshot, summaries, "F")
    g = named_package(files, snapshot, summaries, "G")
    ga_id = next(
        b.id for b in snapshot.bindings
        if b.name == "GA" and b.kind == "variable"
    )
    assert f.available and f.effects == "unknown"
    assert f.calls[0].target == ga_id and f.calls[0].imported
    assert g.available and g.return_dependencies == frozenset({0})
    assert g.calls[0].target == ga_id and g.calls[0].imported


def test_package_map_var_index_write_evaluates_key(
    go_types_helper,
):
    # `GM[K(x)] = v` — the index expression is evaluated like the
    # imported path's extras: K's own transfer still records.
    files = {
        "a.go": "package p\nvar GM map[int64]int64\nvar GC int64\n"
        "func K(v int64) int64 { GC = v; return v }\n"
        "func F(x int64) int64 { GM[K(x)] = x; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    k_id = next(
        f.binding_id for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "K"
    )
    assert any(c.target == k_id for c in result.calls)


def test_package_pointer_var_deref_write_and_read(
    go_types_helper,
):
    # `*GP = v` may aim at any escaped binding — the write folds the
    # stored deps through the alias fold like `*lib.PV = v`, and the
    # var identity records the mutation. `*GP` reads through package
    # state the same way.
    files = {
        "a.go": "package p\nvar GP *int64\n"
        "func F(x int64) int64 { *GP = x; return x }\n"
        "func G(x int64) int64 { return *GP + x }\n",
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    f = named_package(files, snapshot, summaries, "F")
    g = named_package(files, snapshot, summaries, "G")
    assert f.available and f.effects == "unknown"
    assert g.available and g.return_dependencies == frozenset({0})
    assert g.effects == "unknown"


def test_package_composite_var_inc_dec_records_transfer(
    go_types_helper,
):
    # `G.V++` / `G[i]++` — provenance-preserving mutations of package
    # state: only the external mutation records.
    files = {
        "a.go": "package p\n"
        "type P struct{ V int64 }\nvar G P\nvar GA [4]int64\n"
        "func F(x int64) int64 { G.V++; GA[0]++; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})
    assert len(result.calls) == 2


def test_package_container_var_range_binds_dep_free(
    go_types_helper,
):
    # `for i := range GA` / `for k, v := range GM` — iterating
    # package state yields dep-free values while the read records
    # the imported transfer against the var's identity.
    files = {
        "a.go": "package p\nvar GA [4]int64\nvar GM map[int64]int64\n"
        "func F(x int64) int64 {\n"
        "\tfor i := range GA { x += int64(i) }\n"
        "\tfor k, v := range GM { x += k + v }\n"
        "\treturn x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})
    assert len(result.calls) == 2
    assert all(c.imported for c in result.calls)


def test_local_composite_write_is_not_a_package_write(
    go_types_helper,
):
    # `st.V = x` on a function-local composite still takes the local
    # accumulate path — the package-var gate never admits it, so no
    # external mutation records (`effects` stays clean).
    files = {
        "a.go": "package p\ntype P struct{ V int64 }\n"
        "func F(x int64) int64 { st := P{}; st.V = x; return st.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"
    assert not result.calls


def test_local_struct_promoted_read_through_pointer_stays_closed(
    go_types_helper,
):
    # `st.V` where `V` promotes through embedded `*Q` reads caller
    # memory the conflated dep set cannot represent — a dep-free
    # answer would report `effects` dishonestly, so it stays closed
    # like the write side.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\ntype P struct{ *Q }\n"
        "func F(q *Q) int64 { st := P{Q: q}; return st.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_package_var_index_expression_read_records_transfer(
    go_types_helper,
):
    # `GA[GI] = x` — GI's read inside the index records its own
    # imported transfer, so redeclaring `GI` flags the summary.
    files = {
        "a.go": "package p\nvar GA [4]int64\nvar GI int64\n"
        "func F(x int64) int64 { GA[GI] = x; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    gi_id = next(
        b.id for b in snapshot.bindings
        if b.name == "GI" and b.kind == "variable"
    )
    assert any(c.target == gi_id and c.imported for c in result.calls)


def test_map_literal_key_evaluates_before_value(
    go_types_helper,
):
    # `M[K(x): *p]` — the key runs first, so K's side effects are
    # recorded before the value's evaluation: the key call's
    # transfer precedes the value's deref read.
    files = {
        "a.go": "package p\nvar GM map[int64]int64\n"
        "func K(v int64) int64 { return v }\n"
        "func F(p *int64, x int64) int64 {\n"
        "\t_ = map[int64]int64{K(x): *p}\n\treturn x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    k_id = next(
        f.binding_id for f in snapshot.functions
        if snapshot.binding(f.binding_id).name == "K"
    )
    targets = [c.target for c in result.calls]
    assert targets.index(k_id) < len(targets) - 1


def test_package_pointer_field_deref_write_records_transfer(
    go_types_helper,
):
    # `*G.P = x` dereferences the field's pointer, not the var —
    # admits like `*GP = v`, recording the mutation on G's identity
    # and folding the stored deps through the alias fold.
    files = {
        "a.go": "package p\n"
        "type P struct{ P *int64 }\nvar G P\n"
        "func F(x int64) int64 { *G.P = x; return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    g_id = next(
        b.id for b in snapshot.bindings
        if b.name == "G" and b.kind == "variable"
    )
    assert any(c.target == g_id for c in result.calls)


def test_package_pointer_intermediate_field_write_folds(
    go_types_helper,
):
    # `G.P.V = x` on `P *Q` crosses P's pointer — the store may land
    # in any escaped binding, so the stored deps must fold back: an
    # escaped `x` keeps the write's deps visible on a later read.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\ntype P struct{ P *Q }\nvar G P\n"
        "func F(x int64) int64 {\n"
        "\tp := &x\n\tG.P.V = 7\n\treturn *p\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_package_pointer_var_pointee_index_read_write(
    go_types_helper,
):
    # `(*GP)[i]` on `var GP *[]int64` — the package pointer var's
    # container pointee reads/writes like GA[i]: dep-free read, the
    # var's own identity records both transfers.
    files = {
        "a.go": "package p\nvar GP *[]int64\n"
        "func F(i int64) int64 { (*GP)[0] = 7; return (*GP)[i] }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})
    gp_id = next(
        b.id for b in snapshot.bindings
        if b.name == "GP" and b.kind == "variable"
    )
    assert any(c.target == gp_id for c in result.calls)


def test_package_index_write_evaluates_bound_pointer_index(
    go_types_helper,
):
    # `GA[(*q)[0]] = v` — the index's own dereference read records a
    # transfer too: skipping its evaluation would under-report
    # `effects`.
    files = {
        "a.go": "package p\nvar GA [4]int64\n"
        "func F(q *[]int64, v int64) int64 {\n"
        "\tGA[(*q)[0]] = v\n\treturn v\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert any(
        c.target.endswith("/pointee") and c.imported
        for c in result.calls
    )


def test_package_index_write_evaluates_scalar_deref_index(
    go_types_helper,
):
    # `GA[*q] = v` — a scalar deref inside the index also records
    # the pointee's transfer.
    files = {
        "a.go": "package p\nvar GA [4]int64\n"
        "func F(q *int64, v int64) int64 {\n"
        "\tGA[*q] = v\n\treturn v\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert any(
        c.target.endswith("/pointee") and c.imported
        for c in result.calls
    )


def test_package_pointer_var_deref_field_write_read(
    go_types_helper,
):
    # `(*GP).V = x` spells `GP.V`'s sugar explicitly: the deref
    # peels the root var's pointer, so the store records the
    # mutation on GP's own identity like `*GP = v` — not on the
    # leaf field, which is what the earlier gate mistakenly
    # classified.
    files = {
        "a.go": "package p\n"
        "type P struct{ V int64 }\nvar GP *P\n"
        "func F(x int64) int64 {\n"
        "\t(*GP).V = x\n\treturn (*GP).V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    gp_id = next(
        b.id for b in snapshot.bindings
        if b.name == "GP" and b.kind == "variable"
    )
    assert any(c.target == gp_id for c in result.calls)


def test_package_pointer_var_deref_field_inc_dec(
    go_types_helper,
):
    # `(*GP).V++` is the same deref-target classification as the
    # assignment form.
    files = {
        "a.go": "package p\n"
        "type P struct{ V int64 }\nvar GP *P\n"
        "func F(x int64) int64 {\n"
        "\t(*GP).V++\n\treturn x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_package_deref_intermediate_field_write_read(
    go_types_helper,
):
    # `(*G.P).N = x` — the deref peels the innermost field's
    # pointer (`P *Q`), not the leaf's type and not the root var's:
    # the store folds like any pointer-crossing package write.
    files = {
        "a.go": "package p\n"
        "type Q struct{ N int64 }\ntype P struct{ P *Q }\nvar G P\n"
        "func F(x int64) int64 {\n"
        "\t(*G.P).N = x\n\treturn (*G.P).N\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    g_id = next(
        b.id for b in snapshot.bindings
        if b.name == "G" and b.kind == "variable"
    )
    assert any(c.target == g_id for c in result.calls)


def test_local_composite_nested_read_pins_intermediate_type(
    go_types_helper,
):
    # `st.A.N` resolves `N` through `A`'s declared `type Q` — the
    # intermediate type identity must pin alongside the root's, or
    # redeclaring `Q` would reuse a stale summary.
    files = {
        "a.go": "package p\n"
        "type Q struct{ N int64 }\ntype P struct{ A Q }\n"
        "func F(x int64) int64 {\n"
        "\tst := P{A: Q{N: x}}\n\treturn st.A.N\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    q_id = next(
        b.id for b in snapshot.bindings
        if b.name == "Q" and b.kind == "type"
    )
    assert q_id in result.pinned


def test_package_composite_nested_read_pins_intermediate_type(
    go_types_helper,
):
    # `G.A.N` on a package-level composite pins the intermediate
    # `type Q` identity too, exactly like the local composite read.
    files = {
        "a.go": "package p\n"
        "type Q struct{ N int64 }\ntype P struct{ A Q }\nvar G P\n"
        "func F(x int64) int64 {\n"
        "\treturn G.A.N\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    q_id = next(
        b.id for b in snapshot.bindings
        if b.name == "Q" and b.kind == "type"
    )
    assert q_id in result.pinned


def test_package_indexed_pointer_element_deref_field_write(
    go_types_helper,
):
    # `(*GA[0]).V = p` on `var GA []*Q` — the deref peels the
    # index *element's* pointer (`*Q`), not the root var's slice
    # type and not the leaf field's type.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V *int64 }\nvar GA []*Q\n"
        "func F(p *int64) int64 {\n"
        "\t(*GA[0]).V = p\n\treturn 0\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    ga_id = next(
        b.id for b in snapshot.bindings
        if b.name == "GA" and b.kind == "variable"
    )
    assert any(c.target == ga_id for c in result.calls)


def test_package_indexed_deref_field_read_depends_on_index(
    go_types_helper,
):
    # `(*GA[i]).V` selects the slot through `i` — the read carries
    # the index's dependencies exactly like `GA[i]` does.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\nvar GA []*Q\n"
        "func F(i int64) int64 {\n"
        "\treturn (*GA[i]).V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_package_nested_index_field_read_depends_on_index(
    go_types_helper,
):
    # `G.A[i].N` — the same slot-selection dependency through a
    # nested field's array; the `lib.VSM[k].F` pre-scan already
    # evaluates the index, so it must not double-record.
    files = {
        "a.go": "package p\n"
        "type Q struct{ N int64 }\ntype P struct{ A [4]Q }\nvar G P\n"
        "func F(i int64) int64 {\n"
        "\treturn G.A[i].N\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_package_nested_map_field_read_literal_key(
    go_types_helper,
):
    # `G.M["k"].V` — a literal index carries no deps; the read must
    # not try to evaluate the literal as an expression.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\ntype P struct{ M map[string]Q }\n"
        "var G P\n"
        "func F(x int64) int64 {\n"
        "\treturn G.M[\"k\"].V + x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_bound_container_pointee_indexed_element_field_read(
    go_types_helper,
):
    # `(*p)[i].V` on `p *[]Q` — a field of the element the index
    # selects: caller memory like `(*p)[i]` itself, so the deps
    # union the pointer's own (param 0), the index's (param 1), and
    # earlier indirect stores; the field's identity records the
    # read and the element type pins.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *[]Q, i int64) int64 {\n"
        "\treturn (*p)[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})
    v_id = next(
        b.id for b in snapshot.bindings
        if b.name == "V" and b.kind == "variable" and b.scope is None
    )
    q_id = next(
        b.id for b in snapshot.bindings
        if b.name == "Q" and b.kind == "type"
    )
    assert any(c.target == v_id and c.imported for c in result.calls)
    assert q_id in result.pinned


def test_bound_array_pointee_sugar_indexed_element_field_read(
    go_types_helper,
):
    # `p[i].V` on `p *[8]Q` — the auto-deref sugar spells the same
    # read as `(*p)[i].V`.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *[8]Q, i int64) int64 {\n"
        "\treturn p[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_bound_pointer_elem_indexed_element_field_read(
    go_types_helper,
):
    # `(*p)[i].V` on `p *[]*Q` — the field select auto-derefs the
    # pointer element: external state either way.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *[]*Q, i int64) int64 {\n"
        "\treturn (*p)[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_bound_pointee_indexed_field_read_observes_indirect_store(
    go_types_helper,
):
    # `(*p)[i].V` must see an earlier indirect store: `(*q).W = x`
    # lands in caller memory the field read cannot rule out, so `x`
    # and `q`'s own deps join the result through `indirect_writes`.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64; W int64 }\n"
        "func F(p *[]Q, q *Q, i, x int64) int64 {\n"
        "\t(*q).W = x\n\treturn (*p)[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1, 2, 3})


def test_bound_pointee_indexed_nested_element_field_read_closed(
    go_types_helper,
):
    # `(*p)[i].V.G` — a field on the element's own struct field
    # traverses a second level and stays closed.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V S }\ntype S struct{ G int64 }\n"
        "func F(p *[]Q, i int64) int64 {\n"
        "\treturn (*p)[i].V.G\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available
    assert result.gaps[0].reason == "non_parameter_reference"


def test_package_container_var_indexed_element_field_read(
    go_types_helper,
):
    # `GA[i].V` on `var GA []Q` — the container var's indexed
    # element's field reads external package state: dep-free apart
    # from the index's own dependencies, recorded on the field's
    # identity like `G.A[i].N`.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\nvar GA []Q\n"
        "func F(i int64) int64 {\n"
        "\treturn GA[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})
    v_id = next(
        b.id for b in snapshot.bindings
        if b.name == "V" and b.kind == "variable" and b.scope is None
    )
    assert any(c.target == v_id and c.imported for c in result.calls)


def test_package_map_var_indexed_element_field_read(
    go_types_helper,
):
    # `M["k"].V` on `var M map[string]Q` — a literal key carries no
    # deps; the field read admits like the slice root's.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\nvar M map[string]Q\n"
        "func F(x int64) int64 {\n"
        "\treturn M[\"k\"].V + x\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_bound_container_pointee_range_element_values(
    go_types_helper,
):
    # `for _, v := range *p` on `p *[]int64` — the elements are
    # caller memory the pointer's aim selects, so the bound name
    # carries the pointer's own deps (and earlier indirect stores)
    # like `(*p)[i]` does; the read records the pointee transfer.
    files = {
        "a.go": "package p\n"
        "func F(p *[]int64, s int64) int64 {\n"
        "\tfor _, v := range *p { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_bound_container_pointee_range_index_only(
    go_types_helper,
):
    # `for i := range *p` binds only the index — dep-free like the
    # package-container range's index name.
    files = {
        "a.go": "package p\n"
        "func F(p *[]int64, s int64) int64 {\n"
        "\tfor i := range *p { s += int64(i) }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({1})


def test_bound_array_pointee_sugar_range(go_types_helper):
    # `for _, v := range p` on `p *[4]int64` — the auto-deref sugar
    # spells the same iteration as `range *p`.
    files = {
        "a.go": "package p\n"
        "func F(p *[4]int64, s int64) int64 {\n"
        "\tfor _, v := range p { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_bound_map_pointee_range(go_types_helper):
    # `for k, v := range *p` on `p *map[int64]int64` — the key name
    # is dep-free, the element carries the pointer's deps.
    files = {
        "a.go": "package p\n"
        "func F(p *map[int64]int64, s int64) int64 {\n"
        "\tfor k, v := range *p { s += v + k }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_package_pointer_var_range(go_types_helper):
    # `for _, v := range *GP` on `var GP *[]int64` — package state
    # reads dep-free like `(*GP)[i]` does.
    files = {
        "a.go": "package p\n"
        "var GP *[]int64\n"
        "func F(s int64) int64 {\n"
        "\tfor _, v := range *GP { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_bound_container_pointee_index_incdec(go_types_helper):
    # `(*p)[i]++`/`(*p)[i]--` — a provenance-preserving external
    # mutation like `(*p)++`; only the mutation records.
    files = {
        "a.go": "package p\n"
        "func F(p *[]int64, i int64) int64 {\n"
        "\t(*p)[i]++\n\t(*p)[i]--\n\treturn i\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({1})


def test_bound_pointee_indexed_element_field_store(
    go_types_helper,
):
    # `(*p)[i].V = w` stores into element memory; the same read-back
    # `(*p)[i].V` observes it through `indirect_writes` — the result
    # unions the pointer's, the index's and the stored value's deps.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *[]Q, i, w int64) int64 {\n"
        "\t(*p)[i].V = w\n\treturn (*p)[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1, 2})
    v_id = next(
        b.id for b in snapshot.bindings
        if b.name == "V" and b.kind == "variable" and b.scope is None
    )
    assert any(c.target == v_id and c.imported for c in result.calls)


def test_bound_pointee_indexed_field_store_observed_through_alias(
    go_types_helper,
):
    # `(*p)[i].V = w` must be observable through another pointer:
    # `(*q)[i].V` reads caller memory the store cannot be proven to
    # miss, so `w` joins `indirect_writes`.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *[]Q, q *[]Q, i, w int64) int64 {\n"
        "\t(*p)[i].V = w\n\treturn (*q)[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({1, 2, 3})


def test_bound_pointee_indexed_element_field_inc(go_types_helper):
    # `(*p)[i].V++` — the increment records the leaf field's own
    # identity like the store's does.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *[]Q, i int64) int64 {\n"
        "\t(*p)[i].V++\n\treturn (*p)[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_bound_array_pointee_sugar_indexed_field_store(
    go_types_helper,
):
    # `p[i].V = w` on `p *[8]Q` — the auto-deref sugar spells the
    # same element-field store as `(*p)[i].V = w`.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *[8]Q, i, w int64) int64 {\n"
        "\tp[i].V = w\n\treturn p[i].V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1, 2})


def test_bound_container_pointee_range_struct_element_closed(
    go_types_helper,
):
    # `for _, v := range *p` on `p *[]Q` — a struct-typed element
    # cannot bind under the scalar-or-pointer gate.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *[]Q, s int64) int64 {\n"
        "\tfor _, v := range *p { s += v.V }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available
    assert result.gaps[0].reason == "binding_unavailable"


def test_bound_map_pointee_range_string_key_closed(
    go_types_helper,
):
    # `for k, v := range *p` on `p *map[string]int64` — a string
    # key stays closed like the package-container range's.
    files = {
        "a.go": "package p\n"
        "func F(p *map[string]int64, s int64) int64 {\n"
        "\tfor k, v := range *p { s += v + int64(len(k)) }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available
    assert result.gaps[0].reason == "binding_unavailable"


def test_bound_pointee_indexed_nested_field_store_closed(
    go_types_helper,
):
    # `(*p)[i].V.G = w` — a second traversal level past the element
    # stays closed like the nested read does.
    files = {
        "a.go": "package p\n"
        "type S struct{ G int64 }\ntype Q struct{ V S }\n"
        "func F(p *[]Q, i, w int64) int64 {\n"
        "\t(*p)[i].V.G = w\n\treturn i\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_bound_pointee_range_element_sees_loop_store(
    go_types_helper,
):
    # `for _, v := range *p` with an element-field store inside the
    # body: `v` is caller memory, so each pass re-joins
    # `indirect_writes` — `w` reaches `s` on the fixed point.
    files = {
        "a.go": "package p\n"
        "func F(p *[]int64, i, w int64) int64 {\n"
        "\tvar s int64\n"
        "\tfor _, v := range *p {\n"
        "\t\t(*p)[i] = w\n"
        "\t\ts += v\n"
        "\t}\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 2})


def test_builtin_new_scalar_pointee(
    go_types_helper,
):
    # `p := new(int64)` — a pure `*int64` allocation: the result is
    # dep-free, then `*p` reads/writes classify by the pointee's own
    # gates (unnamed scalar pointee admits).
    files = {
        "a.go": "package p\n"
        "func F(a int64) int64 {\n"
        "\tp := new(int64)\n"
        "\t*p = a\n"
        "\treturn *p\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_builtin_new_named_pointee_field(
    go_types_helper,
):
    # `p := new(P)` — field access through the fresh `*P` uses the
    # bound-pointer member gates like any other pointer binding.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(a int64) int64 {\n"
        "\tp := new(Q)\n"
        "\tp.V = a\n"
        "\treturn p.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_builtin_make_stays_closed(
    go_types_helper,
):
    # `make([]int64)` — a composite value the binding model cannot
    # hold stays opaque like before.
    files = {
        "a.go": "package p\n"
        "func F(a int64) int64 {\n"
        "\ts := make([]int64, 3)\n"
        "\ts[0] = a\n"
        "\treturn s[0]\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available
    assert result.gaps[0].reason == "unresolved_or_opaque_call"


def test_builtin_new_pointer_arg_propagates_callee_writes(
    go_types_helper,
):
    # `G(p)` hands an opaque-effect callee the fresh pointer — its
    # `*q` stores write caller memory, so a later `*p` read must
    # observe every argument's deps through `indirect_writes`.
    files = {
        "a.go": "package p\n"
        "func G(q *int64, a int64) int64 { *q = a; return 0 }\n"
        "func F(a int64) int64 {\n"
        "\tp := new(int64)\n"
        "\t_ = G(p, a)\n"
        "\treturn *p\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_bound_closure_call(go_types_helper):
    # `h := func(a int64) int64 { return a + x }; h(x)` — the
    # literal's deps are its captured free variables; calling it
    # through the bare identifier unions the captures with the
    # argument's own deps.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\th := func(a int64) int64 { return a + x }\n"
        "\treturn h(x)\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_bound_closure_free_var_only(go_types_helper):
    # `h := func() int64 { return x }; h()` — the capture alone
    # carries the result's dependency.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\th := func() int64 { return x }\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


def test_bound_closure_call_inside_literal_closed(go_types_helper):
    # A call inside the literal defers an effect the sequencing
    # model cannot place — stays closed.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\th := func() int64 { return G(x) }\n"
        "\treturn h()\n}\n"
        "func G(a int64) int64 { return a }",
    )
    result = named(*data)
    assert not result.available
    assert result.gaps[0].reason == "unsupported_expression"


def test_bound_closure_write_inside_closed(go_types_helper):
    # A write inside the literal mutates state out of order —
    # stays closed.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\ty := x\n"
        "\th := func() { y = 1 }\n"
        "\th()\n"
        "\treturn y\n}",
    )
    result = named(*data)
    assert not result.available


def test_bound_closure_package_var_inside_closed(go_types_helper):
    # A package-level `var` read inside the literal is external
    # state the capture cannot pin — stays closed.
    data = unit(
        go_types_helper,
        "var G int64\n"
        "func F(x int64) int64 {\n"
        "\th := func() int64 { return G }\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert not result.available


def test_bound_closure_pointer_capture_marks_effects(go_types_helper):
    # `h := func() { return *p }` captures a pointer — invoking it
    # reads caller memory like a `*p` read, so `h()` records the
    # imported transfer and marks `effects` unknown.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\ty := x\n"
        "\tp := &y\n"
        "\th := func() int64 { return *p }\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_bound_closure_reassign_updates_captures(go_types_helper):
    # `h = func() { return y }` rebinds the closure — the new
    # literal's captures replace the old deps.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\th := func() int64 { return 0 }\n"
        "\ty := x\n"
        "\th = func() int64 { return y }\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_bound_closure_alias_call(go_types_helper):
    # `g := h` — the alias carries the same captured deps.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\th := func() int64 { return x }\n"
        "\tg := h\n"
        "\treturn g()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_func_typed_parameter_stays_closed(go_types_helper):
    # `func F(h func() int64)` — a function-typed parameter fails
    # the signature gate like before.
    data = unit(
        go_types_helper,
        "func F(h func() int64) int64 { return h() }",
    )
    result = named(*data)
    assert not result.available
    assert result.gaps[0].reason == "unsupported_signature"


def test_bound_closure_computed_callee_closed(go_types_helper):
    # `(h)()` — only a bare-identifier callee admits; a
    # parenthesized or computed callee stays closed.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\th := func() int64 { return x }\n"
        "\treturn (h)()\n}",
    )
    result = named(*data)
    assert not result.available


def test_bound_closure_var_declaration(go_types_helper):
    # `var h func() int64; h = func() { return x }; h()` — the
    # `var` form binds the same captured deps.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\tvar h func() int64\n"
        "\th = func() int64 { return x }\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_bound_closure_resolves_captures_at_call(go_types_helper):
    # `z` is reassigned between the literal and the call — `h()`
    # resolves the captured binding's CURRENT deps, not the set
    # frozen at the literal.
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\tz := x\n"
        "\th := func() int64 { return z }\n"
        "\tz = y\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_bound_closure_rebind_clears_captures(go_types_helper):
    # Rebinding `h` to a literal that captures nothing clears the
    # capture set the earlier literal left.
    data = unit(
        go_types_helper,
        "func F(x int64) int64 {\n"
        "\tz := x\n"
        "\th := func() int64 { return z }\n"
        "\th = func() int64 { return 1 }\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset()


def test_bound_closure_pointer_capture_resolves_at_call(go_types_helper):
    # A pointer-capturing literal resolves the captured pointer's
    # current deps too — `p` re-pointed `a` → `b` before `h()`, and
    # `*p` may observe either escaped binding like a direct `*p`
    # read does.
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\ta := x\n"
        "\tb := y\n"
        "\tp := &a\n"
        "\th := func() int64 { return *p }\n"
        "\tp = &b\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"


def test_bound_closure_alias_propagates_captures(go_types_helper):
    # `h2 := h` copies the closure — `h2()` resolves the captured
    # binding's deps at the call site like `h()` does.
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\tz := x\n"
        "\th := func() int64 { return z }\n"
        "\th2 := h\n"
        "\tz = y\n"
        "\treturn h2()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_bound_closure_assignment_copy_propagates_captures(
    go_types_helper,
):
    # `var h2 func(); h2 = h` — the assignment form propagates the
    # capture record the same way.
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\tz := x\n"
        "\th := func() int64 { return z }\n"
        "\tvar h2 func() int64\n"
        "\th2 = h\n"
        "\tz = y\n"
        "\treturn h2()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_bound_closure_conditional_rebind_unions_captures(
    go_types_helper,
):
    # `if c { h = func() { return y } }` — the skipped path keeps
    # the old literal, so `h()` reports both captures.
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\th := func() int64 { return x }\n"
        "\tif x > 0 {\n"
        "\t\th = func() int64 { return y }\n"
        "\t}\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_bound_closure_param_reassign_resolves_at_call(
    go_types_helper,
):
    # A captured parameter reassigned before the call resolves to
    # its current deps, not the parameter index.
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\th := func() int64 { return x }\n"
        "\tx = y\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_bound_closure_pointer_capture_sees_escaped_updates(
    go_types_helper,
):
    # `p := &a; a = y; h()` — the captured pointer reads `a`'s
    # CURRENT contents. The result unions the pointer's own deps
    # with every escaped binding's current deps — a superset of
    # what a direct `*p` read reports, sound in both directions.
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\ta := x\n"
        "\tp := &a\n"
        "\th := func() int64 { return *p }\n"
        "\ta = y\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})
    assert result.effects == "unknown"


def test_bound_closure_tuple_swap(go_types_helper):
    # `h, g = g, h` evaluates the pre-state in parallel — after the
    # swap `g()` reads what `h` captured and `h()` what `g` did.
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\th := func() int64 { return x }\n"
        "\tg := func() int64 { return y }\n"
        "\th, g = g, h\n"
        "\treturn g()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({0})
    data = unit(
        go_types_helper,
        "func F(x, y int64) int64 {\n"
        "\th := func() int64 { return x }\n"
        "\tg := func() int64 { return y }\n"
        "\th, g = g, h\n"
        "\treturn h()\n}",
    )
    result = named(*data)
    assert result.available
    assert result.return_dependencies == frozenset({1})


def test_double_pointer_read(
    go_types_helper,
):
    # `**pp` — two-level deref: deps carry the pointer's provenance
    # plus escaped and indirect stores, like one level does.
    files = {
        "a.go": "package p\n"
        "func F(pp **int64) int64 { return **pp }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_double_pointer_store_observed(
    go_types_helper,
):
    # `**pp = v` folds like `*p = v` — a later `**pp` read observes
    # the stored deps through `indirect_writes`.
    files = {
        "a.go": "package p\n"
        "func F(pp **int64, v int64) int64 {\n"
        "\t**pp = v\n"
        "\treturn **pp\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_double_pointer_named_chain_stays_closed(
    go_types_helper,
):
    # `type PP *int64; pp *PP` — the producer records the named
    # alias's fact as opaque (`unsupported`), so the pointee chain
    # cannot resolve pointer → scalar and the read fails closed.
    files = {
        "a.go": "package p\n"
        "type PP *int64\n"
        "func F(pp *PP) int64 { return **pp }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available
    assert result.gaps[0].reason == "non_parameter_reference"


def test_triple_pointer_stays_closed(
    go_types_helper,
):
    # `***ppp` — the inner operand is not a bare identifier.
    files = {
        "a.go": "package p\n"
        "func F(ppp ***int64) int64 { return ***ppp }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available
    assert result.gaps[0].reason == "non_parameter_reference"


def test_double_pointer_deep_named_pointee(
    go_types_helper,
):
    # `pp ***S` — `**pp` reads the `*S` element: `deep`'s own
    # `type_id` names S (its pointee), not the read's result type —
    # the pointer kind gate classifies `deep` itself, so the read
    # admits like `q := *pp; return *q`.
    files = {
        "a.go": "package p\n"
        "type S struct{ V int64 }\n"
        "func F(pp ***S) *S { return **pp }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_computed_range_pointer_result(go_types_helper):
    # `for _, v := range *G()` — the callee's `*[]int64` result is
    # outside the scalar signature fragment, so the range gets the
    # opaque-callee model: elements carry the call's argument deps
    # ∪ escaped ∪ indirect stores, and effects stay unknown.
    files = {
        "a.go": "package p\n"
        "func G() *[]int64 { return nil }\n"
        "func F(s int64) int64 {\n"
        "\tfor _, v := range *G() { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_computed_range_container_result(go_types_helper):
    # `for _, v := range G()` on a `[]int64` result — the same
    # opaque-callee model without the `*` spelling.
    files = {
        "a.go": "package p\n"
        "func G() []int64 { return nil }\n"
        "func F(s int64) int64 {\n"
        "\tfor _, v := range G() { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_computed_range_array_sugar(go_types_helper):
    # `for range G()` on a `*[4]int64` result — Go auto-derefs a
    # pointer-to-array, the same rule `for range p` follows.
    files = {
        "a.go": "package p\n"
        "func G() *[4]int64 { return nil }\n"
        "func F(s int64) int64 {\n"
        "\tfor _, v := range G() { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_computed_range_argument_deps(go_types_helper):
    # `for _, v := range *G(x)` — the opaque callee's argument deps
    # union into the elements like an imported call's.
    files = {
        "a.go": "package p\n"
        "func G(x int64) *[]int64 { return nil }\n"
        "func F(x, s int64) int64 {\n"
        "\tfor _, v := range *G(x) { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_computed_range_index_only(go_types_helper):
    # `for i := range *G()` binds only the index — dep-free like
    # every container range, while the call still records.
    files = {
        "a.go": "package p\n"
        "func G() *[]int64 { return nil }\n"
        "func F(s int64) int64 {\n"
        "\tfor i := range *G() { s += int64(i) }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_computed_range_map_key_value(go_types_helper):
    # `for k, v := range G()` on a map result — the key is dep-free
    # and the element value carries the call's argument deps.
    files = {
        "a.go": "package p\n"
        "func G(x int64) map[int64]int64 { return nil }\n"
        "func F(x, s int64) int64 {\n"
        "\tfor k, v := range G(x) { s += int64(k) + v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_computed_range_imported_callee_stays_closed(go_types_helper):
    # `for range *lib.G()` — the imported member's signature carries
    # identities, not the result's kind, so the operand stays
    # closed like `*lib.G()` itself.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(s int64) int64 {\n"
        "\tfor _, v := range *lib.G() { s += v }\n"
        "\treturn s\n}\n"
    }
    libs = {
        "lib": {
            "g.go": "package lib\nfunc G() *[]int64 { return nil }\n",
        }
    }
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, libs),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_computed_range_transfer_carries_arguments(go_types_helper):
    # `for range G(x)` on a direct container result — the single
    # transfer on the callee's identity carries the evaluated
    # argument deps, so the call's inputs stay on record.
    files = {
        "a.go": "package p\n"
        "func G(x int64) []int64 { return nil }\n"
        "func F(x, s int64) int64 {\n"
        "\tfor _, v := range G(x) { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    call_transfers = [
        t for t in result.calls if t.arguments == (frozenset({0}),)
    ]
    assert len(call_transfers) == 1


def test_computed_range_pointer_result_pins_both(go_types_helper):
    # `for range *G()` — two transfers: the container read pins the
    # result pointee's identity, and the call pins the callee.
    files = {
        "a.go": "package p\n"
        "func G(x int64) *[]int64 { return nil }\n"
        "func F(x, s int64) int64 {\n"
        "\tfor _, v := range *G(x) { s += v }\n"
        "\treturn s\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    pointee_transfers = [
        t for t in result.calls if t.target.endswith("/pointee")
    ]
    assert len(pointee_transfers) == 1
    assert pointee_transfers[0].arguments == (frozenset({0}),)
    callee = pointee_transfers[0].target[: -len("/pointee")]
    call_transfers = [
        t for t in result.calls if t.target == callee
    ]
    assert len(call_transfers) == 1
    assert call_transfers[0].arguments == (frozenset({0}),)


def test_anonymous_struct_pointee_field_read(go_types_helper):
    # `p.V` on a bound `*struct{...}` — the anonymous pointee names
    # no `type` member, but the field resolves through its own
    # binding and reads caller memory like a named pointee's.
    files = {
        "a.go": "package p\n"
        "func F(p *struct{ V int64 }) int64 { return p.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_anonymous_struct_pointee_explicit_deref(go_types_helper):
    # `(*p).V` — the explicit dereference spells out the same
    # auto-deref `p.V` performs.
    files = {
        "a.go": "package p\n"
        "func F(p *struct{ V int64 }) int64 { return (*p).V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"
    assert result.return_dependencies == frozenset({0})


def test_anonymous_struct_pointee_field_write(go_types_helper):
    # `p.V = x` — the store lands in caller memory, so the
    # synthetic `<binding>/pointee` identity records it and
    # effects stay unknown like every bound-pointer field store.
    files = {
        "a.go": "package p\n"
        "func F(p *struct{ V int64 }, x int64) int64 {\n"
        "\tp.V = x\n\treturn 0\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"
    pointee_transfers = [
        t for t in result.calls if t.target.endswith("/pointee")
    ]
    assert len(pointee_transfers) == 1


def test_anonymous_struct_pointee_field_inc(go_types_helper):
    # `p.V++` increments through the same write path.
    files = {
        "a.go": "package p\n"
        "func F(p *struct{ V int64 }) int64 { p.V++; return 0 }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available and result.effects == "unknown"


def test_anonymous_struct_pointee_write_observable(go_types_helper):
    # `p.V = x; return p.V` — the store broadcasts into
    # `indirect_writes`, so the read reports the stored deps like
    # `*p = v; return *p` does.
    files = {
        "a.go": "package p\n"
        "func F(p *struct{ V int64 }, x int64) int64 {\n"
        "\tp.V = x\n\treturn p.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.effects == "unknown"
    assert result.return_dependencies == frozenset({0, 1})


def test_anonymous_struct_pointee_nested_stays_closed(go_types_helper):
    # `p.A.N` on a struct-typed field stays closed — a second
    # selection crosses into the field's own contents.
    files = {
        "a.go": "package p\n"
        "func F(p *struct{ A struct{ N int64 } }) int64 {\n"
        "\treturn p.A.N\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_anonymous_struct_pointee_pointer_field_stays_closed(
    go_types_helper,
):
    # `p.A.N` where `A` is `*struct{...}` — a pointer-typed field
    # dereferences memory the model cannot conflate.
    files = {
        "a.go": "package p\n"
        "func F(p *struct{ A *struct{ N int64 } }) int64 {\n"
        "\tif p.A == nil { return 0 }\n"
        "\treturn p.A.N\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available




def test_anonymous_struct_value_field_read_is_admitted(go_types_helper):
    # `st.V` on `st := struct{ V int64 }{V: x}` — an anonymous
    # struct value carries one conflated dep set like a named
    # composite; the type names no identity, so nothing pins.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 {\n"
        "\tst := struct{ V int64 }{V: x}\n\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


def test_anonymous_struct_value_field_write_is_admitted(go_types_helper):
    # `st.V = x` folds x's deps into st's conflated set — a local
    # mutation, so no transfer records and `effects` stays honest.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 {\n"
        "\tst := struct{ V int64 }{}\n\tst.V = x\n\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})
    assert result.effects == "none_in_supported_fragment"


def test_anonymous_struct_value_var_decl_is_admitted(go_types_helper):
    # `var st struct{...}` — the zero-value declaration carries an
    # empty set until a store folds into it.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 {\n"
        "\tvar st struct{ V int64 }\n\tst.V = x\n\treturn st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_anonymous_struct_value_nested_field_is_admitted(go_types_helper):
    # `st.A.N` — a nested anonymous-struct field traverses two
    # anonymous containers; both enumerate by source-order window.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 {\n"
        "\tst := struct{ A struct{ N int64 } }{}\n"
        "\tst.A.N = x\n\treturn st.A.N\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_anonymous_struct_value_embedded_pointer_stays_closed(
    go_types_helper,
):
    # `st.V` where `V` promotes through embedded `*Q` reads memory
    # behind a pointer the conflated set cannot represent — the
    # direct-field window excludes it, on reads AND stores.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(x int64) int64 {\n"
        "\tst := struct{ *Q }{}\n\treturn st.V\n}\n",
        "b.go": "package p\n"
        "func G(x int64) int64 {\n"
        "\tst := struct{ *Q }{}\n\tst.V = x\n\treturn 0\n}\n",
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    assert not named_package(files, snapshot, summaries, "F").available
    assert not named_package(files, snapshot, summaries, "G").available


def test_anonymous_struct_value_address_stays_closed(go_types_helper):
    # `&st` on a tracked composite stays closed — a bound pointer
    # must never alias tracked storage or the external-state models
    # under-count.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 {\n"
        "\tst := struct{ V int64 }{V: x}\n\tp := &st\n\treturn p.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_anonymous_struct_pointee_summary_is_not_self_stale(go_types_helper):
    # The synthetic `<binding>/pointee` identity a bound `*struct{...}`
    # read records must never land in `pinned`: it names an unnamed
    # pointee no declaration can redeclare, so `stale_dependents`
    # would flag the summary stale against its own snapshot forever.
    files = {
        "a.go": "package p\n"
        "func F(p *struct{ V int64 }) int64 { return p.V }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    result = named_package(files, snapshot, summaries, "F")
    assert result.available
    known = {b.id for b in snapshot.bindings}
    assert summaries.stale_dependents(known) == frozenset()


def test_anonymous_struct_value_declares_no_gap(go_types_helper):
    # An anonymous `struct{...}` VALUE declaration admits under the
    # same conflated dep-set model as a named composite — the
    # producer must NOT flag `unsupported_value_semantics` for it.
    snapshot = load_go_snapshot(
        compiler_report(
            go_types_helper,
            "package p;\nfunc F(x int64) int64 {\n"
            "\tst := struct{ V int64 }{V: x}\n\treturn st.V\n}\n",
            "amd64",
        ),
        "package p;\nfunc F(x int64) int64 {\n"
        "\tst := struct{ V int64 }{V: x}\n\treturn st.V\n}\n",
        target_arch="amd64",
    )
    assert not any(
        gap.reason == "unsupported_value_semantics" for gap in snapshot.gaps
    )


def test_anonymous_struct_value_pointer_field_deref_stays_closed(
    go_types_helper,
):
    # `*st.P` — a pointer-typed field dereferences caller memory the
    # conflated set cannot represent, same as `st.A.N` on `A *P2`.
    files = {
        "a.go": "package p\n"
        "func F(p *int64) int64 {\n"
        "\tst := struct{ P *int64 }{P: p}\n\treturn *st.P\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_package_anonymous_struct_var_is_admitted(go_types_helper):
    # `var GS struct{ V int64 }` — a package-level anonymous struct
    # var is external state like a named composite var: reads are
    # dep-free and stores fold the value's deps into the leaf.
    files = {
        "a.go": "package p\n"
        "var GS struct{ V int64 }\n"
        "func F() int64 { return GS.V }\n",
        "b.go": "package p\n"
        "func G(x int64) int64 { GS.V = x; return 0 }\n",
    }
    snapshot = _snapshot_for(go_types_helper, files)
    summaries = ip.summarize_go_package(files, snapshot)
    read = named_package(files, snapshot, summaries, "F")
    assert read.available
    assert read.return_dependencies == frozenset()
    assert read.effects == "unknown"
    write = named_package(files, snapshot, summaries, "G")
    assert write.available
    assert write.effects == "unknown"


def test_anonymous_struct_copy_is_admitted(go_types_helper):
    # `cp := st` copies the anonymous type — cp's fields are the ones
    # declared in st's literal, so cp.V resolves through st's anchor.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 {\n"
        "\tst := struct{ V int64 }{V: x}\n"
        "\tcp := st\n\tcp.V = x + 1\n\treturn cp.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_anonymous_struct_multi_name_var_is_admitted(go_types_helper):
    # `var a, b struct{...}` declares the literal after the LAST
    # name — every earlier name anchors its field window there.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 {\n"
        "\tvar a, b struct{ V int64 }\n"
        "\ta.V = x\n\treturn a.V + b.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_anonymous_struct_copy_embedded_pointer_stays_closed(
    go_types_helper,
):
    # `cp := st` where st embeds `*Q` — the promoted field's binding
    # still lives inside `type Q`'s scoped declaration, outside the
    # copied anchor's window, so the read stays closed.
    files = {
        "a.go": "package p\n"
        "type Q struct{ V int64 }\n"
        "func F(p *Q) int64 {\n"
        "\tst := struct{ *Q }{Q: p}\n\tcp := st\n\treturn cp.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_anonymous_struct_signature_positions_declare_gap(
    go_types_helper,
):
    # An anonymous `struct{...}` param still sits outside the
    # fragment (the signature gate closes the function) — its
    # declaration must keep flagging `unsupported_value_semantics`
    # even though anonymous struct VALUES now admit.
    snapshot = load_go_snapshot(
        compiler_report(
            go_types_helper,
            "package p;\n"
            "func F(s struct{ V int64 }) int64 { return s.V }\n",
            "amd64",
        ),
        "package p;\n"
        "func F(s struct{ V int64 }) int64 { return s.V }\n",
        target_arch="amd64",
    )
    assert any(
        gap.reason == "unsupported_value_semantics" for gap in snapshot.gaps
    )


def test_anonymous_struct_explicit_typed_var_copy_is_admitted(
    go_types_helper,
):
    # `var cp struct{...} = st` — cp's fields live in its own
    # explicit type (right after its name), not in st's literal:
    # the default span anchor covers them, so the copy anchor must
    # not overwrite it.
    files = {
        "a.go": "package p\n"
        "func F(x int64) int64 {\n"
        "\tst := struct{ V int64 }{V: x}\n"
        "\tvar cp struct{ V int64 } = st\n"
        "\tcp.V = x + 1\n"
        "\treturn cp.V + st.V\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_local_channel_send_recv_is_admitted(go_types_helper):
    # `ch := make(chan T); ch <- x; return <-ch` — a local channel
    # is one conflated dep set: the send accumulates x's deps, the
    # receive returns the union of everything sent.
    result = named(
        *unit(
            go_types_helper,
            "func F(x int64) int64 {\n"
            "\tch := make(chan int64)\n"
            "\tch <- x\n"
            "\treturn <-ch\n}\n",
        )
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_local_channel_sends_union(go_types_helper):
    # Every send accumulates: `<-ch` reads the union of both sent
    # values' deps.
    result = named(
        *unit(
            go_types_helper,
            "func F(x int64, y int64) int64 {\n"
            "\tch := make(chan int64, 2)\n"
            "\tch <- x\n"
            "\tch <- y\n"
            "\treturn <-ch\n}\n",
        )
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1})


def test_local_channel_comma_ok_receive(go_types_helper):
    # `v, ok := <-ch` binds the received value with the channel's
    # deps; the presence flag conservatively takes the same set.
    result = named(
        *unit(
            go_types_helper,
            "func F(x int64) int64 {\n"
            "\tch := make(chan int64)\n"
            "\tch <- x\n"
            "\tv, ok := <-ch\n"
            "\tif ok {\n\t\treturn v\n\t}\n"
            "\treturn 0\n}\n",
        )
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_local_channel_var_and_close_forms(go_types_helper):
    # `var ch chan T` (zero queue), `var ch = make(chan T)` and
    # `close(ch)` all admit.
    for decl in ("var ch chan int64", "var ch = make(chan int64)"):
        result = named(
            *unit(
                go_types_helper,
                "func F(x int64) int64 {\n"
                "\t" + decl + "\n"
                "\tch <- x\n"
                "\tclose(ch)\n"
                "\treturn <-ch\n}\n",
            )
        )
        assert result.available, decl
        assert result.return_dependencies == frozenset({0}), decl


def test_local_channel_range_is_admitted(go_types_helper):
    # `for v := range ch` binds v to the channel's set like a
    # receive — the range operand evaluates to ch's union.
    result = named(
        *unit(
            go_types_helper,
            "func F(x int64) int64 {\n"
            "\tch := make(chan int64)\n"
            "\tch <- x\n"
            "\ts := int64(0)\n"
            "\tfor v := range ch {\n\t\ts += v\n\t}\n"
            "\treturn s\n}\n",
        )
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_local_channel_conditional_send(go_types_helper):
    # A send inside a branch still accumulates — the join unions
    # the may-send into the channel's set.
    result = named(
        *unit(
            go_types_helper,
            "func F(x int64, b bool) int64 {\n"
            "\tch := make(chan int64)\n"
            "\tif b {\n\t\tch <- x\n\t}\n"
            "\treturn <-ch\n}\n",
        )
    )
    assert result.available
    assert result.return_dependencies == frozenset({0})


def test_local_channel_alias_binds_stay_closed(go_types_helper):
    # `ch2 := ch`, `var ch2 = ch` and `ch2 = ch` would alias one
    # queue under a second dep set — a send through ch2 could never
    # reach `<-ch`, under-approximating. Only `make` creates a
    # channel binding.
    for src in (
        "func F(x int64) int64 {\n"
        "\tch := make(chan int64)\n"
        "\tch2 := ch\n\tch2 <- x\n\treturn <-ch2\n}\n",
        "func F(x int64) int64 {\n"
        "\tch := make(chan int64)\n"
        "\tvar ch2 = ch\n\tch2 <- x\n\treturn <-ch2\n}\n",
        "func F(x int64) int64 {\n"
        "\tch := make(chan int64)\n"
        "\tch2 := make(chan int64)\n"
        "\tch2 = ch\n\tch2 <- x\n\treturn <-ch2\n}\n",
    ):
        result = named(*unit(go_types_helper, src))
        assert not result.available


def test_channel_boundaries_stay_closed(go_types_helper):
    # A `chan` parameter sits outside the signature fragment; a
    # send through a selector (`p.C <- x`) and `make([]T)` stay
    # opaque; `select` cannot build a CFG.
    param = named(
        *unit(
            go_types_helper,
            "func F(ch chan int64) int64 { return <-ch }\n",
        )
    )
    assert not param.available
    files = {
        "a.go": "package p\n"
        "type Q struct{ C chan int64 }\n"
        "func F(p *Q, x int64) int64 { p.C <- x; return 0 }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    selector = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not selector.available
    slice_make = named(
        *unit(
            go_types_helper,
            "func F(x int64) int64 {\n"
            "\ts := make([]int64, 2)\n\t_ = s\n\treturn x\n}\n",
        )
    )
    assert not slice_make.available
    select_case = named(
        *unit(
            go_types_helper,
            "func F(x int64) int64 {\n"
            "\tch := make(chan int64)\n\tch <- x\n"
            "\tselect {\n\tcase v := <-ch:\n\t\treturn v\n"
            "\tdefault:\n\t\treturn 0\n\t}\n}\n",
        )
    )
    assert not select_case.available


def test_channel_non_scalar_element_stays_closed(go_types_helper):
    # `chan chan T` would let a channel VALUE travel through a queue
    # (`ch2, _ = <-q`) and alias it under a second dep set — the
    # under-approx the make-only bind gate exists to prevent. A
    # `chan *T`/`chan func()` element escapes the dep model the same
    # way, so channel bindings admit scalar elements only.
    for src in (
        "func F(x int64) int64 {\n"
        "\tq := make(chan chan int64)\n\t_ = q\n\treturn x\n}\n",
        "func F(x int64) int64 {\n"
        "\tvar q chan chan int64\n\t_ = q\n\treturn x\n}\n",
        "func F(x int64) int64 {\n"
        "\tq := make(chan *int64)\n\t_ = q\n\treturn x\n}\n",
        "func F(x int64) int64 {\n"
        "\tq := make(chan func() int64)\n\t_ = q\n\treturn x\n}\n",
        "func F(x int64) int64 {\n"
        "\tvar q chan func()\n\t_ = q\n\treturn x\n}\n",
    ):
        result = named(*unit(go_types_helper, src))
        assert not result.available


def test_channel_range_body_send_rejoins_element(go_types_helper):
    # `for v := range ch { ch <- y; *p = v }` — sends inside the
    # body widen the queue every pass; the element name must re-join
    # that grown set or `*p = v` stores the entry-time deps only.
    result = named(
        *unit(
            go_types_helper,
            "func F(x, y int64, p *int64) int64 {\n"
            "\tch := make(chan int64)\n\tch <- x\n"
            "\tfor v := range ch {\n\t\tch <- y\n\t\t*p = v\n\t}\n"
            "\treturn *p\n}\n",
        )
    )
    assert result.available
    assert result.return_dependencies == frozenset({0, 1, 2})


def test_channel_tuple_receive_cannot_alias(go_types_helper):
    # `ch2, _ = <-Q` — a tuple-of-different-width assignment can bind
    # a channel through a receive just like `ch2 = ch`; the chan gate
    # must not assume matching arity. `Q` lives at package scope
    # because a local `chan chan int64` cannot be built at all.
    files = {
        "a.go": "package p\n"
        "var Q chan chan int64\n"
        "func F(x int64) int64 {\n"
        "\tch2 := make(chan int64)\n"
        "\tch2, _ = <-Q\n\tch2 <- x\n\treturn <-ch2\n}\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available
