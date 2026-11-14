from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from agent import control_flow, go_interprocedural as ip
from agent.go_type_snapshot import (
    FileSpan,
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
        "var global int64; func F(x int64) int64 {return global}",
        # A package variable named `iota` is not the predeclared
        # constant — its read stays a declared gap.
        "var iota int64; func F(x int64) int64 { return iota }",
        "var true bool; func F() bool {return true}",
        "func F(x int64) (int64,int64) {return x,x}",
        "func F(x int64) float64 {return 1.0}",
        "func F(x int64) int64 {return 1.0}",
        "func F(x int64) int64 {return (func() int64 {return x})()}",
        "func G(){}; func F(x int64) int64 {defer G(); return x}",
        "func G(){}; func F(x int64) int64 {go G(); return x}",
        "func F(x *int64) int64 {return *x}",
        "func F(x []int64) int64 {return x[0]}",
        "func F(x map[int64]int64) int64 {return x[0]}",
        "func F(x chan int64) int64 {return <-x}",
        "type R struct{closed bool}; func Close(r *R) int64 {r.closed=true;return 1}; func F(r *R) int64 {return Close(r)}",
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
        # A callee taking a pointer parameter has a non-scalar signature —
        # the caller cannot pass an address-of without one too.
        "func G(p *int64) int64 { return *p }; func F(x int64) int64 { return G(&x) }",
        # An alias of a parameter cannot be bound — `&x` is non-scalar.
        "func F(x int64) int64 { p := &x; return *p }",
        # …and neither can it reach a callee through a bound alias.
        "func G(p *int64) int64 { return *p }; func F(x int64) int64 { q := &x; return G(q) }",
        # A callee mutating a slice's resource state has a non-scalar
        # signature; the composite literal argument is unsupported anyway.
        "func G(s []int64) int64 { s[0] = 1; return s[0] }; func F(x int64) int64 { return G([]int64{x}) }",
        # A callee reading or writing shared package state is opaque —
        # the global is neither a parameter nor a local of the callee.
        "var g int64; func G() int64 { g = 1; return g }; func F(x int64) int64 { return G() + x }",
        "var g int64; func G(v int64) int64 { return g + v }; func F(x int64) int64 { return G(x) }",
        # Constructor builtins produce non-scalar resource state.
        "func G(p *int64) int64 { return *p }; func F(x int64) int64 { return G(new(int64)) }",
        "func F(x int64) int64 { var s []int64; _ = s; return x }",
        # A channel is resource state — `nil` has no binding either.
        "func G(c chan int64) int64 { return <-c }; func F(x int64) int64 { return G(nil) }",
        # A bound function value is non-scalar — indirect dispatch stays
        # outside the resolved-call fragment.
        "func G(v int64) int64 { return v }; func F(x int64) int64 { h := G; return h(x) }",
        # A literal closure is a non-scalar binding too.
        "func F(x int64) int64 { h := func() int64 { return x }; return h() }",
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
        "func F(x int64) int64 { var f func(); _ = f; return x }",
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
        # make/new are allocation, not pure reads.
        "func F(x int64) int64 { _ = new(int64); return x }",
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
        "var G int64; func Bad(x int64)int64{return G}; func F(x int64)int64{return Bad(x)}; func Good(x int64)int64{return x}",
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


def test_multi_result_import_call_fails_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 {\n"
        "\ty, z := lib.G(x)\n"
        "\treturn y + z\n}\n"
    }
    lib = {
        "lib": {"g.go": "package lib\nfunc G(y int64) (int64, int64) { return y, y }\n"}
    }
    report = json.loads(package_report_imports(go_types_helper, files, lib))
    (call,) = report["calls"]
    assert call["kind"] == "external_or_bodyless"
    assert any(
        g["reason"] == "call_not_summarized_external_or_bodyless"
        for g in report["gaps"]
    )


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


def test_imported_generic_type_instantiation_fails_closed(go_types_helper):
    # `lib.GT[int64](x)` reaches the report as a conversion, but the
    # callee is an `index_expression`, not a package-qualified selector
    # — instantiated generics stay closed.
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { _ = lib.GT[int64](x); return x }\n"
    }
    snapshot = _snapshot_for(go_types_helper, files)
    result = named_package(files, snapshot, ip.summarize_go_package(files, snapshot), "F")
    # The index expression is rejected before the conversion check —
    # either way the instantiated generic stays closed.
    assert not result.available and result.gaps[0].reason in {
        "binding_unavailable",
        "unsupported_expression",
    }


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


def test_imported_generic_named_type_argument_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return int64(lib.GI[lib.T](lib.T(x))) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    kinds = {c["kind"] for c in report["calls"]}
    # The instantiation is not admitted: a named type argument adds a
    # type identity the declared signature pins cannot cover.
    assert "direct_import" not in kinds
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available


def test_imported_generic_inferred_call_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport \"lib\"\n"
        "func F(x int64) int64 { return lib.GI(x) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    # The declared signature's result is a type parameter, so the
    # inferred call remains opaque — only explicit basic instantiations
    # are admitted.
    assert report["calls"][0]["kind"] == "external_or_bodyless"


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


def test_dot_imported_generic_named_type_argument_stays_closed(go_types_helper):
    files = {
        "a.go": "package p\nimport . \"lib\"\n"
        "func F(x int64) int64 { return int64(GI[T](T(x))) }\n"
    }
    report = json.loads(
        package_report_imports(go_types_helper, files, GENERIC_LIB)
    )
    assert report["status"] == "ok"
    # The unqualified instantiation must not ride the declared-signature
    # check — `T` as a type argument is a named identity no pin covers.
    kinds = {c["kind"] for c in report["calls"]}
    assert "direct_import" not in kinds and "external_or_bodyless" in kinds
    snapshot = load_go_package_snapshot(
        package_report_imports(go_types_helper, files, GENERIC_LIB),
        files,
        target_arch="amd64",
    )
    result = named_package(
        files, snapshot, ip.summarize_go_package(files, snapshot), "F"
    )
    assert not result.available
