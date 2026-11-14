"""Tests for the C06 TypeScript interprocedural consumer (slice 0).

No compiler integration — sources are self-contained single units.
"""

import pytest

pytest.importorskip("tree_sitter_typescript")

import agent.ts_interprocedural as ts


def _summarize(source: str) -> ts.TsSummarySet:
    return ts.summarize_typescript(source)


def _fn(source: str, name: str = "f") -> ts.TsFunctionSummary:
    summaries = _summarize(source).functions
    result = next(s for s in summaries if s.name == name)
    return result


# --- admitted fragment -------------------------------------------------------


def test_scalar_return_dependency():
    s = _fn("function f(x: number): number { return x; }")
    assert s.available
    assert s.parameters == ("x",)
    assert s.return_dependencies == frozenset({0})


def test_literals_and_operators():
    s = _fn(
        "function f(x: number, y: number): number {"
        " return x * 2 + y - 3; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_boolean_param_and_logic():
    s = _fn(
        "function f(b: boolean, x: number): boolean {"
        " return b && x > 0 || !b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_bitwise_ops_admitted():
    s = _fn(
        "function f(x: number, y: number): number {"
        " return (x & y) | (x ^ ~y); }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_equality_ops():
    for op in ("==", "===", "!=", "!==", "<", "<=", ">", ">="):
        s = _fn(f"function f(x: number, y: number): boolean {{ return x {op} y; }}")
        assert s.available, op


def test_let_const_var_bindings():
    s = _fn(
        "function f(x: number): number {"
        " let a = x + 1; const b = a; var c = b; return c; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_typed_local_annotation():
    s = _fn(
        "function f(x: number): number {"
        " let a: number = x; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_assignment_and_compound():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = 0; a = x; a += y; a -= 1; a *= 2; a &= y; a |= x; a ^= y;"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_update_expressions_preserve_deps():
    s = _fn(
        "function f(x: number): number {"
        " let a = x; a++; ++a; a--; --a; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_if_else_joins_by_union():
    s = _fn(
        "function f(x: number, y: number, b: boolean): number {"
        " let a = x;"
        " if (b) { a = y; }"
        " return a; }"
    )
    # `a` may keep x (branch skipped) or become y.
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_if_else_both_sides():
    s = _fn(
        "function f(x: number, y: number, b: boolean): number {"
        " let a = 0;"
        " if (b) { a = x; } else { a = y; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_branch_local_binding_does_not_escape():
    s = _fn(
        "function f(x: number, b: boolean): number {"
        " if (b) { let t = x; }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_while_loop_fixed_point():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = x;"
        " while (a < 10) { a = a + y; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_for_loop_fixed_point():
    s = _fn(
        "function f(x: number): number {"
        " let a = 0;"
        " for (let i = 0; i < 4; i++) { a = a + x; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_for_loop_carries_param_deps():
    s = _fn(
        "function f(x: number, y: number): number {"
        " for (let i = x; i < 10; i += y) {}"
        " return 0; }"
    )
    assert s.available


def test_loop_var_does_not_escape():
    s = _fn(
        "function f(x: number): number {"
        " for (let i = x; i < 4; i++) {}"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_break_and_continue():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = 0;"
        " while (a < 10) {"
        "   if (a > 5) { break; }"
        "   if (a < 3) { a += x; continue; }"
        "   a += y;"
        " }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_same_unit_call_records_transfer():
    src = (
        "function g(a: number, b: number): number { return a; }\n"
        "function f(x: number, y: number): number { return g(y, x); }"
    )
    s = _fn(src)
    assert s.available and s.return_dependencies == frozenset({0, 1})
    (call,) = s.calls
    assert call.callee == "g"
    assert call.arguments == (frozenset({1}), frozenset({0}))
    assert s.effects == "unknown"


def test_call_deps_union():
    src = (
        "function g(a: number): number { return a; }\n"
        "function f(x: number, y: number): number { return g(x) + g(y); }"
    )
    s = _fn(src)
    assert s.available and s.return_dependencies == frozenset({0, 1})
    assert len(s.calls) == 2


def test_zero_arg_call():
    src = (
        "function g(): number { return 1; }\n"
        "function f(x: number): number { return g() + x; }"
    )
    s = _fn(src)
    assert s.available and s.return_dependencies == frozenset({0})
    (call,) = s.calls
    assert call.arguments == () and call.result == frozenset()


def test_self_recursion_is_an_opaque_call():
    src = "function f(x: number): number { return f(x - 1); }"
    s = _fn(src)
    assert s.available and s.return_dependencies == frozenset({0})
    (call,) = s.calls
    assert call.callee == "f"


def test_no_return_reports_empty_deps():
    s = _fn("function f(x: number): number { let a = x; }")
    assert s.available and s.return_dependencies == frozenset()


def test_bare_return_contributes_nothing():
    s = _fn("function f(x: number): number { return; }")
    assert s.available and s.return_dependencies == frozenset()


def test_multiple_functions_each_summarized():
    src = (
        "function g(a: number): number { return a; }\n"
        "function f(x: number): number { return g(x); }\n"
        "function h(x: number, bad: string): number { return x; }"
    )
    summaries = _summarize(src).functions
    assert {s.name for s in summaries} == {"g", "f", "h"}
    by_name = {s.name: s for s in summaries}
    assert by_name["g"].available and by_name["f"].available
    assert not by_name["h"].available
    assert by_name["h"].gaps[0].reason == "unsupported_signature"


def test_parenthesized_expressions():
    s = _fn(
        "function f(x: number, y: number): number {"
        " return ((x)) + ((y) * (2)); }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_pinned_is_empty_in_slice0():
    s = _fn("function f(x: number): number { return x; }")
    assert s.pinned == ()


# --- signature closures ------------------------------------------------------


def test_unannotated_parameter_closes():
    s = _fn("function f(x): number { return 1; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_non_scalar_parameter_closes():
    for t in ("string", "any", "number[]", "unknown"):
        s = _fn(f"function f(x: {t}): number {{ return 1; }}")
        assert not s.available, t
        assert s.gaps[0].reason == "unsupported_signature"


def test_optional_parameter_closes():
    s = _fn("function f(x?: number): number { return 1; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_default_parameter_closes():
    s = _fn("function f(x: number = 3): number { return x; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_rest_parameter_closes():
    s = _fn("function f(...xs: number[]): number { return 0; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_destructured_parameter_closes():
    s = _fn("function f({a}: {a: number}): number { return a; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_missing_return_type_closes():
    s = _fn("function f(x: number) { return x; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_non_scalar_return_type_closes():
    s = _fn("function f(x: number): string { return \"s\"; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_async_function_closes():
    s = _fn(
        "async function f(x: number): number { return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_generator_closes():
    # A generator is not a function_declaration — it is not summarized
    # at all (it is a closed top-level node, not a named function).
    summaries = _summarize("function* g() { yield 1; }").functions
    assert summaries == () or not any(
        s.name == "g" and s.available for s in summaries
    )


# --- statement closures ------------------------------------------------------


def test_throw_closes():
    s = _fn(
        "function f(x: number): number { throw new Error(); return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_try_catch_closes():
    s = _fn(
        "function f(x: number): number {"
        " try { return x; } catch (e) { return 0; } }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_switch_closes():
    s = _fn(
        "function f(x: number): number {"
        " switch (x) { case 1: return 1; default: return 0; } }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_do_while_closes():
    s = _fn(
        "function f(x: number): number {"
        " let a = x; do { a--; } while (a > 0); return a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_for_of_closes():
    s = _fn(
        "function f(x: number): number {"
        " let a = 0; for (const v of [1]) { a = v; } return a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_for_in_closes():
    s = _fn(
        "function f(x: number): number {"
        " let a = 0; for (const k in {}) { a = x; } return a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_labeled_break_closes():
    s = _fn(
        "function f(x: number): number {"
        " let a = 0;"
        " outer: while (a < 10) { a = x; break outer; }"
        " return a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_bare_break_outside_loop_closes():
    s = _fn(
        "function f(x: number): number { break; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_nested_function_closes():
    s = _fn(
        "function f(x: number): number {"
        " function inner(): number { return x; }"
        " return inner(); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


# --- expression closures -----------------------------------------------------


def test_unbound_identifier_closes():
    s = _fn("function f(x: number): number { return y; }")
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_string_literal_closes():
    s = _fn('function f(x: number): number { return "s" as any; }')
    assert not s.available


def test_ternary_closes():
    s = _fn(
        "function f(x: number, b: boolean): number { return b ? x : 0; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_arrow_function_value_closes():
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v; return g(x); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_member_call_closes():
    s = _fn(
        "function f(x: number): number { return Math.abs(x); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_unresolved_call_closes():
    s = _fn("function f(x: number): number { return g(x); }")
    assert not s.available
    assert s.gaps[0].reason == "call_unresolved"


def test_new_expression_closes():
    s = _fn("function f(x: number): number { return new C(x); }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_member_access_closes():
    s = _fn("function f(x: number): number { return o.f; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_subscript_closes():
    s = _fn("function f(x: number): number { return a[0]; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_await_closes():
    s = _fn(
        "function f(x: number): number { return x + await p; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_division_modulo_exponent_close():
    for op in ("/", "%", "**"):
        s = _fn(f"function f(x: number, y: number): number {{ return x {op} y; }}")
        assert not s.available, op
        assert s.gaps[0].reason == "unsupported_expression"


def test_shift_operators_close():
    for op in ("<<", ">>", ">>>"):
        s = _fn(f"function f(x: number, y: number): number {{ return x {op} y; }}")
        assert not s.available, op
        assert s.gaps[0].reason == "unsupported_expression"


def test_nullish_coalescing_closes():
    s = _fn("function f(x: number): number { return x ?? 0; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_template_string_closes():
    s = _fn("function f(x: number): number { return `v${x}`; }")
    assert not s.available


def test_assignment_to_unbound_closes():
    s = _fn(
        "function f(x: number): number { y = x; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_uninitialized_let_closes():
    s = _fn(
        "function f(x: number): number { let a; a = x; return a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_non_scalar_local_annotation_closes():
    s = _fn(
        "function f(x: number): number { let a: string = \"s\"; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_sequence_expression_closes():
    s = _fn(
        "function f(x: number): number { return (x, 0); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


# --- unit closures -----------------------------------------------------------


def test_import_closes_unit():
    src = (
        'import { z } from "./m";\n'
        "function f(x: number): number { return x; }"
    )
    s = _fn(src)
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


def test_export_closes_unit():
    src = "export function f(x: number): number { return x; }"
    s = _fn(src)
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


def test_declare_closes_unit():
    src = (
        "declare function d(x: number): number;\n"
        "function f(x: number): number { return x; }"
    )
    s = _fn(src)
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


def test_top_level_class_closes_unit():
    src = (
        "class C {}\n"
        "function f(x: number): number { return x; }"
    )
    s = _fn(src)
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


def test_top_level_statement_closes_unit():
    src = (
        "const g = 1;\n"
        "function f(x: number): number { return x; }"
    )
    s = _fn(src)
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


def test_syntax_error_yields_no_summaries():
    summaries = _summarize("function f(x: number { return x; }")
    assert summaries.functions == ()


# --- dep-model invariants ----------------------------------------------------


def test_deps_are_over_approximation():
    # `x * 0` still depends on x — conservative, not evaluation.
    s = _fn("function f(x: number): number { return x * 0; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_unavailable_is_none_not_empty():
    s = _fn("function f(x): number { return 1; }")
    assert not s.available
    assert s.return_dependencies is None


def test_conditional_store_preserves_current_value():
    # After `a = x`, a conditional `a += y` may keep the current value —
    # the join unions {x} with {x,y}, not the parameter's own index.
    s = _fn(
        "function f(x: number, y: number, b: boolean): number {"
        " let a = x;"
        " if (b) { a += y; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_return_in_branch_counts():
    s = _fn(
        "function f(x: number, b: boolean): number {"
        " if (b) { return x; }"
        " return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_call_argument_order_preserved():
    src = (
        "function g(a: number, b: number): number { return a - b; }\n"
        "function f(x: number, y: number): number { return g(y, x); }"
    )
    s = _fn(src)
    (call,) = s.calls
    assert call.arguments == (frozenset({1}), frozenset({0}))


def test_else_if_chain_joins_all_arms():
    s = _fn(
        "function f(x: number, y: number, z: number, b: boolean,"
        " c: boolean): number {"
        " let a = 0;"
        " if (b) { a = x; } else if (c) { a = y; } else { a = z; }"
        " return a; }"
    )
    assert s.available
    assert s.return_dependencies == frozenset({0, 1, 2})


def test_break_in_inner_loop_only():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = 0;"
        " while (a < 10) {"
        "   while (a < 5) { a += x; break; }"
        "   a += y;"
        " }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_logical_compound_assignment():
    s = _fn(
        "function f(x: number, b: boolean): number {"
        " let a = x; b &&= x > 0; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_multiple_declarators():
    s = _fn(
        "function f(x: number): number {"
        " let a = 0, b = x; return a + b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_var_initializer_in_for():
    s = _fn(
        "function f(x: number): number {"
        " for (var i = 0; i < 4; i++) { x = x; }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_context_key_is_deterministic():
    src = "function f(x: number): number { return x; }"
    assert (
        _summarize(src).context_key == _summarize(src).context_key
    )
    assert (
        _summarize(src).context_key
        != _summarize(src + " ").context_key
    )


def test_parameters_order_preserved():
    s = _fn(
        "function f(a: number, b: boolean, c: number): number {"
        " return c; }"
    )
    assert s.parameters == ("a", "b", "c")
    assert s.return_dependencies == frozenset({2})


def test_exported_function_keeps_summary_with_gap():
    summaries = _summarize(
        "export function f(x: number): number { return x; }"
    ).functions
    (s,) = summaries
    assert s.name == "f" and not s.available
    assert s.gaps[0].reason == "unsupported_unit"


def test_statement_after_break_is_conditional():
    # The statement after `break` may be skipped — a store there joins
    # by union rather than replacing unconditionally.
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = x;"
        " while (a < 10) {"
        "   if (a > 5) { break; }"
        "   a = y;"
        " }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_break_skips_for_increment():
    # A `break` exits the loop without running the increment — the
    # body's last store survives.
    s = _fn(
        "function f(x: number): number {"
        " let a = 0;"
        " for (let i = 0; i < 1; a = 0) { a = x; break; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_continue_runs_for_increment():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = 0;"
        " for (let i = 0; i < 4; i += y) {"
        "   a = x; continue; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_block_let_does_not_shadow_outer():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = x; { let a = y; } return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_block_let_local_does_not_escape():
    s = _fn(
        "function f(x: number): number {"
        " { let a = x; } return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_reading_block_let_outside_closes():
    s = _fn(
        "function f(x: number): number {"
        " { let a = x; } return a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_var_in_block_escapes():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = x; { var a = y; } return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_var_in_for_init_escapes():
    s = _fn(
        "function f(x: number): number {"
        " for (var i = x; i < 4; i++) {} return i; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_var_in_branch_is_conditional():
    s = _fn(
        "function f(x: number, y: number, b: boolean): number {"
        " var a = x; if (b) { var a = y; } return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_loop_condition_call_transfer_widens():
    # The condition re-evaluates each pass — the recorded transfer's
    # argument deps reflect the widened binding.
    src = (
        "function check(i: number): boolean { return i > 0; }\n"
        "function f(x: number): number {"
        " let i = 0; while (check(i)) { i = x; } return i; }"
    )
    s = _fn(src)
    assert s.available and s.return_dependencies == frozenset({0})
    (call,) = s.calls
    assert call.arguments == (frozenset({0}),)


def test_for_condition_call_transfer_widens():
    src = (
        "function check(i: number): boolean { return i > 0; }\n"
        "function f(x: number): number {"
        " for (let i = 0; check(i); i = x) {} return 0; }"
    )
    s = _fn(src)
    assert s.available
    (call,) = s.calls
    assert call.arguments == (frozenset({0}),)


def test_unavailable_summary_reports_unknown_effects():
    s = _fn("function f(x): number { return 1; }")
    assert not s.available
    assert s.effects == "unknown"
