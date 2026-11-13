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
        "func F(x int64) uint64 {return uint64(x)}",
        "func F(x int64) int64 {return 1/x}",
        "func F(x int64) int64 {return 1%x}",
        "func F(x int64) int64 {return x<<1}",
        "func F(x int64) int64 {return x>>1}",
        "func F(x int64) int64 { x++; return x }",
        "func F(x int64) int64 { if x>0 {return x}; return 0 }",
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
    "declarations",
    [
        # Reassignment is not a let binding.
        "func F(x int64) int64 { y:=x; y=1; return y }",
        # Tuple declarations are outside the fragment.
        "func F(x int64) int64 { y,z:=x,x; return y+z }",
        # An increment is a statement, not a let binding.
        "func F(x int64) int64 { y:=x; y++; return y }",
        # A non-identifier left side is not a let binding.
        "func F(x int64) int64 { _=x; return x }",
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
