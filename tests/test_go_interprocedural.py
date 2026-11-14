from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from agent import control_flow, go_interprocedural as ip
from agent.go_type_snapshot import SnapshotError, load_go_snapshot
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


@pytest.mark.parametrize("operator", ["+", "-", "*", "&", "|", "^", "&^"])
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
        "const N int64 = 1; func F(x int64) int64 { return N }",
        "var true bool; func F() bool {return true}",
        "func F(x int64) int64 {return 1/x}",
        "func F(x int64) int64 {return 1%x}",
        "func F(x int64) int64 {return x<<1}",
        "func F(x int64) int64 {return x>>1}",
        "func F(x int64) (r int64) {return}",
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
    "declarations",
    [
        # Composite ranges are outside the fragment (the operand itself
        # cannot be expressed — including through a conversion, whose
        # result never passes a binding check inside a range clause).
        "func F(x int64) int64 { for i:=range \"ab\" { _ = i }; return x }",
        "func F(x int64) int64 { for i:=range string(x) { _ = i }; return x }",
        # Non-inc/dec updates stay unsupported.
        "func F(x int64) int64 { for i:=x; i>0; i=i-1 {}; return x }",
        # Assignment updates are not inc/dec.
        "func F(x int64) int64 { for i:=x; i>0; i=x {}; return x }",
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
        "func F(x int64) int64 { switch v,w:=x,x; v { case 1: return v+w }; return x }",
        "func G(v int64) int64 { return v }\nfunc F(x int64) int64 { switch G(x); x { case 1: return x }; return x }",
        # fallthrough is unmodelled control flow.
        "func F(x int64) int64 { switch x { case 1: fallthrough; default: return x }; return x }",
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
    ],
)
def test_var_declaration_dependencies(go_types_helper, declarations, expected):
    result = named(*unit(go_types_helper, declarations))
    assert result.available and result.return_dependencies == expected
    assert result.effects == "none_in_supported_fragment"


@pytest.mark.parametrize(
    "declarations",
    [
        # Multi-name specs stay outside the fragment.
        "func F(x int64) int64 { var a, b int64 = x, x; return a+b }",
        # Non-scalar var bindings are unavailable.
        "func F(x int64) int64 { var s string; _ = s; return x }",
        "func F(x int64) int64 { var f func(); _ = f; return x }",
        # Grouped `var (...)` is a parser gap (tree-sitter has_error).
        "func F(x int64) int64 { var ( a int64 = x; b = x ); return a+b }",
        # const declarations are not var bindings.
        "func F(x int64) int64 { const c int64 = 1; return c }",
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
        "func F(x int64) int64 { if y,z:=x,x; y>0 {return z}; return 0 }",
        # An expression-statement initializer is a declared gap.
        "func G(v int64) int64 { return v }\nfunc F(x int64) int64 { if G(x); x>0 {return x}; return 0 }",
        # A for loop with a multi-name init is not modelled.
        "func F(x int64) int64 { for i,j:=x,x; i<x; i++ { _ = j }; return x }",
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
        # Tuple declarations are outside the fragment.
        "func F(x int64) int64 { y,z:=x,x; return y+z }",
        # An increment is a statement, not a let binding.
        # A non-identifier left side is not a let binding.
        # A call used only for effects is a statement, not a let binding.
        "func G(){}; func F(x int64) int64 { G(); return x }",
        # Unsupported initializer propagates the gap.
        "func F(x int64) int { y:=len(\"s\"); return y }",
    ],
)
def test_non_let_statements_stay_unsupported(go_types_helper, declarations):
    result = named(*unit(go_types_helper, declarations))
    assert not result.available and result.return_dependencies is None
    assert result.effects == "unknown" and result.gaps


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
