"""Tests for the C06 TypeScript interprocedural consumer (slice 0).

No compiler integration — sources are self-contained single units.
"""

import json
import os

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
    # Annotations are type-level — `bad: string` admits, and its
    # param binds index 1 like any other.
    assert by_name["g"].available and by_name["f"].available
    assert by_name["h"].available
    assert by_name["h"].return_dependencies == frozenset({0})


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


def test_unannotated_parameter_admits():
    # `function f(x)` — the param binds its index; annotations
    # were never needed by the dep model.
    s = _fn("function f(x): number { return 1; }")
    assert s.available
    assert s.return_dependencies == frozenset()


def test_non_scalar_parameter_admits():
    for t in ("string", "any", "number[]", "unknown"):
        s = _fn(f"function f(x: {t}): number {{ return 1; }}")
        assert s.available, t


def test_optional_parameter_admits():
    s = _fn("function f(x?: number): number { return x; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_default_parameter_admits():
    s = _fn("function f(x: number = 3): number { return x; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_default_parameter_records_calls():
    s = _fn(
        "function g(x: number): number { return x; }"
        "function f(x: number = g(1)): number { return x; }"
    )
    assert s.available and len(s.calls) == 1
    assert s.calls[0].callee == "g"


def test_rest_parameter_admits():
    # Slice 17: `...xs` occupies the last index slot.
    s = _fn("function f(...xs: number[]): number { return 0; }")
    assert s.available and s.parameters == ("xs",)


def test_uninitialized_let_binds_no_deps():
    s = _fn(
        "function f(x: number): number { let a; a = x; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_uninitialized_let_read_is_dep_free():
    s = _fn(
        "function f(x: number): number { let a; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_assignment_in_expression_writes():
    s = _fn(
        "function f(x: number): number { let a = 0; let b = (a = x);"
        " return a + b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_assignment_in_expression_is_a_may_write():
    # `a = 1` on the RHS of `||` may not run — `a`'s deps keep the
    # parameter through the may-write union.
    s = _fn(
        "function f(x: number): number { let a = x;"
        " let b = (a > 0) || (a = 1); return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_sequence_expression_unions_operands():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = (x, y); return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_sequence_in_for_increment_writes():
    s = _fn(
        "function f(x: number): number {"
        " let a = 0; let b = 0;"
        " for (let i = 0; i < 3; i++, b = x) { a = b; } return b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_destructured_parameter_admits():
    # Slice 14: the pattern's sub-names union the slot's deps.
    s = _fn("function f({a}: {a: number}): number { return a; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_missing_return_type_admits():
    # The return annotation is type-level — deps come from the
    # actual `return`.
    s = _fn("function f(x: number) { return x; }")
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_non_scalar_return_type_admits():
    s = _fn("function f(x: number): string { return \"s\"; }")
    assert s.available


def test_async_function_admits_scalar():
    # Slice 15: `async` admits — `await` degrades to operand deps.
    s = _fn(
        "async function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_generator_admits():
    # A generator's `yield` operand deps union into its return
    # deps (no iterator slot — over-approximation).
    summaries = _summarize(
        "function* g(x: number) { yield x; }"
    ).functions
    (g,) = [s for s in summaries if s.name == "g"]
    assert g.available and g.return_dependencies == frozenset({0})


# --- statement closures ------------------------------------------------------


def test_throw_admits():
    s = _fn(
        "function f(x: number): number { throw x; return 0; }"
    )
    assert s.available


def test_throw_new_expression_admits():
    # `Error` is a well-known global (slice 29) — `new Error()`
    # resolves as an external call, and the throw still throws.
    s = _fn(
        "function f(x: number): number { throw new Error(); return x; }"
    )
    assert s.available


def test_try_catch_admits():
    s = _fn(
        "function f(x: number): number {"
        " try { return x; } catch (e) { return 0; } }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_catch_writes_are_may_writes():
    # `y = x` in the catch unions with the no-throw path's `y = 0`.
    s = _fn(
        "function f(x: number): number {"
        " let y = 0; try { y = 1; } catch (e) { y = x; } return y; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_throw_makes_later_statements_may_writes():
    # The `y = 0` after a conditional `throw` may not run, so `y`
    # keeps the parameter's deps.
    s = _fn(
        "function f(x: number): number {"
        " let y = x; if (x > 0) { throw y; } y = 0; return y; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_try_finally_without_catch_propagates():
    # No `catch`: the thrown state propagates past `finally`, so
    # `y = 0` stays a may-write and `y` keeps x's deps; `finally`
    # still records its call.
    s = _fn(
        "function h(x: number): number { return x; }"
        "function f(x: number): number {"
        " let y = x; try { throw y; } finally { h(x); }"
        " y = 0; return y; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert len(s.calls) == 1


def test_finally_writes_unconditionally():
    # `finally` runs on every path — its `y = 0` clobbers even the
    # catch clause's may-write.
    s = _fn(
        "function f(x: number): number {"
        " let y = x; try { y = 1; } catch (e) { y = x; }"
        " finally { y = 0; } return y; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_catch_parameter_binds_thrown_deps():
    s = _fn(
        "function f(x: number): number {"
        " try { throw x; } catch (e) { return e; } return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_catch_parameter_unions_throws():
    s = _fn(
        "function f(x: number, y: number): number {"
        " try { if (x > 0) { throw x; } else { throw y; } }"
        " catch (e) { return e; } return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_catch_parameter_scoped_to_clause():
    # `e` doesn't leak past the catch block.
    s = _fn(
        "function f(x: number): number {"
        " try { throw x; } catch (e) { } return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_catch_parameter_write_is_scoped():
    # Writing `e` inside the catch doesn't shadow a real local.
    s = _fn(
        "function f(x: number): number {"
        " let e = 0; try { throw x; } catch (e) { }"
        " return e; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_nested_catch_parameter():
    s = _fn(
        "function f(x: number, y: number): number {"
        " try { try { throw x; } catch (e1) { throw y; } }"
        " catch (e2) { return e2; } return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_catch_rethrow_propagates():
    # A throw inside `catch` propagates like the try's own throw —
    # `y = 0` is a may-write, so `y` keeps the parameter's deps.
    s = _fn(
        "function f(x: number): number {"
        " let y = x; try { } catch (e) { throw y; }"
        " y = 0; return y; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_throw_expression_records_calls():
    s = _fn(
        "function g(x: number): number { return x; }"
        "function f(x: number): number { throw g(x); }"
    )
    assert s.available and len(s.calls) == 1


def test_chained_assignment_writes_both():
    s = _fn(
        "function f(x: number): number { let a = 0; let b = 0;"
        " a = b = x; return a + b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_switch_admits():
    s = _fn(
        "function f(x: number): number {"
        " switch (x) { case 1: return 1; default: return 0; } }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_switch_case_bodies_are_may_writes():
    # Entry to a clause is conditional, so `y = x` inside `case 1`
    # is a may-write: the result still depends on `x`.
    s = _fn(
        "function f(x: number, b: number): number {"
        " let y: number = 0;"
        " switch (b) { case 1: y = x; break; default: y = 0; }"
        " return y; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_switch_fallthrough_flows():
    # `case 1` falls into `case 2` — the shared scope carries `y`'s
    # write forward.
    s = _fn(
        "function f(x: number): number {"
        " let y: number = 0;"
        " switch (x) { case 1: y = x; case 2: return y; default: return 0; } }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_switch_case_value_deps():
    # A non-literal `case` value evaluates like any expression —
    # including its calls — while `y`'s may-write stays dep-free.
    s = _fn(
        "function f(x: number, b: number): number {"
        " let y: number = 0;"
        " switch (x) { case b: y = 1; break; default: break; }"
        " return y; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_break_in_switch_does_not_break_the_loop():
    # The `break` targets the switch's own frame — the loop still
    # iterates to the fixed point, so `a`'s write joins.
    s = _fn(
        "function f(x: number): number {"
        " let a: number = 0; let i: number = 0;"
        " while (i < x) {"
        "  switch (i) { case 0: break; default: break; }"
        "  a = a + x; i++;"
        " }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_continue_inside_switch_targets_the_loop():
    s = _fn(
        "function f(x: number): number {"
        " let a: number = 0; let i: number = 0;"
        " while (i < x) {"
        "  i++;"
        "  switch (i) { case 0: continue; default: break; }"
        "  a = a + x;"
        " }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_let_in_a_case_restores_at_switch_end():
    # `let y` in a clause is block-scoped to the switch — it must not
    # shadow the outer `y` past the switch's end.
    s = _fn(
        "function f(x: number, y: number): number {"
        " switch (x) { case 1: let y: number = x; break; default: break; }"
        " return y; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_do_while_admits():
    s = _fn(
        "function f(x: number): number {"
        " let a = x; do { a--; } while (a > 0); return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_for_of_on_array_literal_admits():
    # `[1]` is a composite of one dep-free element — `v` binds {}.
    s = _fn(
        "function f(x: number): number {"
        " let a = 0; for (const v of [1]) { a = v; } return a; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_for_in_on_empty_object_admits():
    # `{}` has no fields — the body over-approximates as a may-run,
    # so its writes still union into the joined scope.
    s = _fn(
        "function f(x: number): number {"
        " let a = 0; for (const k in {}) { a = x; } return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_labeled_break_admits():
    s = _fn(
        "function f(x: number): number {"
        " let a = 0;"
        " outer: while (a < 10) { a = x; break outer; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_labeled_continue_admits():
    # `continue outer` from an inner loop still iterates the outer —
    # `a = x` on a taken path keeps the parameter's deps.
    s = _fn(
        "function f(x: number): number {"
        " let a = x;"
        " outer: while (a < 10) {"
        "  while (a > 0) { continue outer; }"
        "  a = 0; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_break_unknown_label_closes():
    s = _fn(
        "function f(x: number): number { break outer; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_continue_to_non_loop_label_closes():
    s = _fn(
        "function f(x: number): number {"
        " L: { continue L; } return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_break_in_labeled_block_admits():
    # `break L` exits just the labeled block — `a = 0` after it is
    # unconditional, but the loop's zero-trip path keeps `a = x`.
    s = _fn(
        "function f(x: number): number {"
        " let a = x;"
        " while (a > 0) { L: { a = 1; break L; } a = 0; }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_break_in_labeled_block_outside_loop():
    # Outside any loop the story is clean: `a = x` stands and the
    # block's `break` only exits the block.
    s = _fn(
        "function f(x: number): number {"
        " let a = 0; L: { a = x; break L; } return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_as_satisfies_non_null_admit():
    s = _fn(
        "function f(x: number): number {"
        " let a = x as number; let b = x!; let c = x satisfies number;"
        " return a + b + c; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_void_evaluates_and_drops():
    s = _fn(
        "function g(x: number): number { return x; }"
        "function f(x: number): number { void g(x); return 0; }"
    )
    assert s.available and len(s.calls) == 1


def test_typeof_reads_operand():
    s = _fn(
        "function f(x: number): number { let a = typeof x; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_bare_break_outside_loop_closes():
    s = _fn(
        "function f(x: number): number { break; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


def test_nested_function_call_admits():
    s = _fn(
        "function f(x: number): number {"
        " function inner(y: number): number { return y; }"
        " return inner(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_nested_function_is_summarized():
    summaries = _summarize(
        "function f(x: number): number {"
        " function inner(y: number): number { return y; }"
        " return inner(x); }"
    ).functions
    by_name = {s.name: s for s in summaries}
    assert by_name["f"].available and by_name["inner"].available


def test_hoisted_nested_call_admits():
    # A declaration hoists — the call resolves before its site.
    s = _fn(
        "function f(x: number): number {"
        " return inner(x);"
        " function inner(y: number): number { return y; } }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_nested_function_reading_outer_closes_itself():
    # `x` is `f`'s local — `inner` has no closure, so IT closes
    # while `f` still admits (the callee body is opaque).
    summaries = _summarize(
        "function f(x: number): number {"
        " function inner(): number { return x; }"
        " return inner(); }"
    ).functions
    by_name = {s.name: s for s in summaries}
    assert by_name["f"].available
    assert not by_name["inner"].available
    assert by_name["inner"].gaps[0].reason == "binding_unavailable"


# --- expression closures -----------------------------------------------------


def test_unbound_identifier_closes():
    s = _fn("function f(x: number): number { return y; }")
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_string_literal_admits():
    s = _fn('function f(x: number): number { return "s" as any; }')
    assert s.available and s.return_dependencies == frozenset()


def test_ternary_admits():
    s = _fn(
        "function f(x: number, b: boolean): number { return b ? x : 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_ternary_unions_all_operands():
    s = _fn(
        "function f(x: number, y: number, b: boolean): number {"
        " return b ? x : y; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1, 2})


def test_arrow_function_value_admits():
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v; return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_member_call_closes():
    # `Math2` is an unbound base — the member call can't resolve
    # (`Math` itself is a well-known global since slice 29).
    s = _fn(
        "function f(x: number): number { return Math2.abs(x); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_unresolved_call_closes():
    s = _fn("function f(x: number): number { return g(x); }")
    assert not s.available
    assert s.gaps[0].reason == "call_unresolved"


def test_new_expression_unbound_ctor_closes():
    s = _fn("function f(x: number): number { return new C(x); }")
    assert not s.available
    # The ctor name resolves through the class registry — an
    # unbound name is `binding_unavailable`.
    assert s.gaps[0].reason == "binding_unavailable"


def test_member_access_on_unbound_closes():
    s = _fn("function f(x: number): number { return o.f; }")
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_member_access_on_scalar_overapprox():
    # Slice 31: a scalar's member read over-approximates to the
    # scalar's deps (`s.length`, `x.f`).
    s = _fn(
        "function f(x: number): number { let o = x; return o.f; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_subscript_on_unbound_closes():
    s = _fn("function f(x: number): number { return a[0]; }")
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_subscript_on_scalar_overapprox():
    s = _fn(
        "function f(x: number): number { let a = x; return a[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_await_passthrough():
    # Slice 15: `await` degrades to operand deps; `p` being unbound
    # still closes with its own reason.
    s = _fn(
        "function f(x: number): number { return x + await p; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_division_modulo_exponent_union():
    for op in ("/", "%", "**"):
        s = _fn(f"function f(x: number, y: number): number {{ return x {op} y; }}")
        assert s.available, op
        assert s.return_dependencies == frozenset({0, 1})


def test_shift_operators_union():
    for op in ("<<", ">>", ">>>"):
        s = _fn(f"function f(x: number, y: number): number {{ return x {op} y; }}")
        assert s.available, op
        assert s.return_dependencies == frozenset({0, 1})


def test_nullish_coalescing_unions():
    s = _fn("function f(x: number): number { return x ?? 0; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_nullish_assign_may_write():
    # `a ??= x` — the write may not run, so it unions.
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = y; a ??= x; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_class_decorator_admits():
    s = _fn(
        "function dec(x: number): number { return x; }"
        " function f(x: number, y: number): number {"
        " @dec(y) class C { m(): number { return 1; } }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_member_decorator_admits():
    s = _fn(
        "function dec(x: number): number { return x; }"
        " function f(x: number): number {"
        " class D { @dec m(): number { return 1; } }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_template_string_admits():
    s = _fn("function f(x: number): number { return `v${x}`; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_assignment_to_unbound_closes():
    s = _fn(
        "function f(x: number): number { y = x; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_non_scalar_local_annotation_admits():
    # `let a: string = "s"` — the annotation is type-level; the
    # value's deps are what bind.
    s = _fn(
        "function f(x: number): number { let a: string = \"s\"; return x; }"
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


# --- unit closures -----------------------------------------------------------


def test_import_admits_unit():
    src = (
        'import { z } from "./m";\n'
        "function f(x: number): number { return x; }"
    )
    s = _fn(src)
    assert s.available and s.return_dependencies == frozenset({0})


def test_export_admits_unit():
    src = "export function f(x: number): number { return x; }"
    s = _fn(src)
    assert s.available and s.return_dependencies == frozenset({0})


def test_declare_skips_ambient():
    # `declare` produces no runtime binding — the unit stays
    # open; any actual use of the name still closes at the
    # use site.
    src = (
        "declare function d(x: number): number;\n"
        "function f(x: number): number { return x; }"
    )
    s = _fn(src)
    assert s.available


def test_declared_name_use_closes():
    src = (
        "declare function d(x: number): number;\n"
        "function f(x: number): number { return d(x); }"
    )
    s = _fn(src)
    assert not s.available
    assert s.gaps[0].reason == "call_unresolved"


def test_top_level_class_admits_unit():
    src = (
        "class C {}\n"
        "function f(x: number): number { return x; }"
    )
    s = _fn(src)
    assert s.available and s.return_dependencies == frozenset({0})


def test_top_level_statement_closes_unit():
    src = (
        "run_side_effect();\n"
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
    # An unresolvable callee still closes — return_dependencies
    # is None, not an empty set.
    s = _fn(
        "function f(x: number): number { return missing(x); }"
    )
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


def test_exported_function_summary_available():
    summaries = _summarize(
        "export function f(x: number): number { return x; }"
    ).functions
    (s,) = summaries
    assert s.name == "f" and s.available
    assert s.return_dependencies == frozenset({0})


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
    s = _fn(
        "function f(x: number): number { return missing(x); }"
    )
    assert not s.available
    assert s.effects == "unknown"

def test_conditional_break_still_runs_for_increment():
    # A break guarded by `if` leaves a non-breaking exit that reaches
    # the increment — only an unconditional break skips it.
    s = _fn(
        "function f(x: number, z: number, n: number): number {"
        " let i = 0;"
        " for (let k = 0; k < n; i = i + z) {"
        "   if (x > 0) { break; }"
        " }"
        " return i; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})

def test_let_in_for_init_does_not_rewind_outer_name():
    # `let i` in the initializer is scoped to the loop — it must not
    # register in the enclosing block's restore map, which would
    # rewind assignments made after the loop.
    s = _fn(
        "function f(a: number, b: number, n: number): number {"
        " let i = a;"
        " for (let i = 0; i < n; i++) {}"
        " i = b;"
        " return i; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_let_in_for_init_does_not_pollute_outer_name():
    # The loop-scoped `i` shadows the outer one — its widened deps
    # never join back into the enclosing binding.
    s = _fn(
        "function f(a: number, z: number, n: number): number {"
        " let i = a;"
        " for (let i = 0; i < n; i = i + z) {}"
        " return i; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})

def test_var_in_while_body_keeps_zero_trip_deps():
    # `var` is function-scoped, but a redeclaration inside a loop is a
    # may-write: the zero-trip path keeps the pre-loop deps, and the
    # loop's stores union in — it must not overwrite unconditionally.
    s = _fn(
        "function f(a: number, b: number, c: boolean): number {"
        " var x = a;"
        " while (c) { var x = b; c = c; }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_var_in_for_body_escapes_with_last_store():
    # A `var` first declared inside the loop body escapes to the
    # function scope — the body's last store wins the join.
    s = _fn(
        "function f(a: number, b: number, n: number): number {"
        " for (let i = 0; i < n; i++) {"
        "   var v = a;"
        "   v = b;"
        " }"
        " return v; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})

def test_conditional_break_keeps_increment_a_may_write():
    # On the breaking exit the increment never ran, so `a` keeps the
    # body's store; on the non-breaking exit it ran — the join is a
    # may-write union, not an unconditional overwrite.
    s = _fn(
        "function f(x: number, c: boolean, n: number): number {"
        " let a = 0;"
        " for (let i = 0; i < n; a = 0) {"
        "   a = x; if (c) { break; }"
        " }"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 6: composite member model -------------------------------------


def test_object_literal_field_read_admits():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x}; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_literal_whole_read_flattens():
    # Reading `o` itself over-approximates to every leaf dep.
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = {a: x, b: y}; return o; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_member_write_admits():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = {a: x}; o.a = y; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_member_write_keeps_sibling_fields():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = {a: x, b: x}; o.a = y; return o.b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_nested_member_read_write():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = {a: {c: x}}; o.a.c = y; return o.a.c; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_conditional_member_write_merges():
    s = _fn(
        "function f(x: number, y: number, c: boolean): number {"
        " let o = {a: x}; if (c) { o.a = y; } return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_member_write_into_new_field_admits():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x}; o.b = x; return o.b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_shorthand_property_admits():
    s = _fn(
        "function f(x: number): number {"
        " let o = {x}; return o.x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_string_key_subscript_admits():
    s = _fn(
        'function f(x: number): number {'
        ' let o = {a: x}; return o["a"]; }'
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_subscript_read_unions_fields():
    s = _fn(
        "function f(x: number, y: number, k: number): number {"
        " let o = {a: x, b: y}; return o[k]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1, 2})


def test_dynamic_subscript_write_admits():
    s = _fn(
        "function f(x: number, k: number): number {"
        " let o = {a: x}; o[k] = x; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_member_write_on_scalar_closes():
    s = _fn(
        "function f(x: number): number {"
        " let o = x; o.a = x; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_member_increment_admits():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x}; o.a++; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_member_augmented_admits():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = {a: x}; o.a += y; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_composite_passed_to_call_flattens():
    s = _summarize(
        "function g(v: number): number { return v; }"
        "function f(x: number, y: number): number {"
        " let o = {a: x, b: y}; return g(o); }"
    )
    f = {fn.name: fn for fn in s.functions}["f"]
    assert f.available and f.return_dependencies == frozenset({0, 1})
    assert f.calls[0].arguments[0] == frozenset({0, 1})


def test_composite_branch_join_merges_fields():
    s = _fn(
        "function f(x: number, y: number, c: boolean): number {"
        " let o = {a: x};"
        " if (c) { o = {a: y, b: y}; }"
        " return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_composite_to_scalar_shape_merge_collapses():
    s = _fn(
        "function f(x: number, y: number, c: boolean): number {"
        " let o = {a: x};"
        " if (c) { o = y; }"
        " return o; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_missing_field_read_is_dep_free():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x}; return o.b; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_object_spread_admits():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x}; let p = {...o}; return p.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_method_call_on_object_still_closes():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x}; return o.a(); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_member_read_on_param_overapprox():
    s = _fn(
        "function f(x: number): number { return x.f; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_alias_write_propagates():
    # `p = o` shares the composite — a member write through `p`
    # reaches `o` (JS reference semantics).
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = {a: x}; let p = o; p.a = y; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_member_path_binding_collapses_to_scalar():
    # `q = o.a` binds leaf deps — a later member write through `o`
    # does not reach `q` (no under-approximation the other way).
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = {a: {c: x}}; let q = o.a; return q; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_member_path_bound_to_name_collapses_deps():
    # `q = o.a` collapses the nested composite to its leaf deps;
    # `q.c` then over-approximates to that scalar (slice 31).
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: {c: x}}; let q = o.a; return q.c; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_subscript_index_deps():
    s = _fn(
        "function f(x: number, k: number): number {"
        " let o = {a: x}; return o[k]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_alias_conditional_write_over_approximates():
    s = _fn(
        "function f(x: number, y: number, c: boolean): number {"
        " let o = {a: x}; let p = o;"
        " if (c) { p.a = y; } return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_field_value_alias_collapses():
    # `{a: o2}` collapses the field — a member write through `o.a`
    # then closes rather than diverging from `o2`.
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o2 = {c: x}; let o = {a: o2}; o.a.c = y; return o.a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_composite_member_store_collapses():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: 0}; o.a = {c: x}; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_loop_member_write_iterates_fixed_point():
    s = _fn(
        "function f(x: number, y: number, n: number): number {"
        " let o = {a: x};"
        " for (let i = 0; i < n; i++) { o.a = y; }"
        " return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_shorthand_composite_collapses():
    # `{o}` collapses the composite field to scalar deps;
    # `p.o.a` then over-approximates to them (slice 31).
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x}; let p = {o}; return p.o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 7: for..in / for..of over composites ---------------------------


def test_for_in_key_reads_fields():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let s2 = 0; let o = {a: x, b: y};"
        " for (const k in o) { s2 = o[k]; }"
        " return s2; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_for_in_key_name_dep_free():
    s = _fn(
        "function f(x: number): number {"
        " let s2 = 1; let o = {a: x};"
        " for (const k in o) { s2 = 0; }"
        " return s2; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_for_in_let_scoped_to_loop():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x};"
        " for (let k in o) { x = 0; }"
        " return k; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_for_in_var_escapes():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x};"
        " for (var k in o) { x = 0; }"
        " return 0; }"
    )
    assert s.available


def test_for_of_binds_field_union():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let s2 = 0; let o = {a: x, b: y};"
        " for (const e of o) { s2 = e; }"
        " return s2; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_for_in_on_scalar_admits():
    # `for (const k in x)` over a scalar — the key is a dep-free
    # string; the body still runs in the over-approximation.
    s = _fn(
        "function f(x: number): number {"
        " for (const k in x) { x = 0; } return x; }"
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_for_in_assignment_target_admits():
    s = _fn(
        "function f(x: number): number {"
        " let k = 0; let o = {a: x};"
        " for (k in o) { x = 0; }"
        " return x; }"
    )
    assert s.available


def test_for_in_assignment_target_unbound_closes():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x};"
        " for (k in o) { x = 0; }"
        " return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_for_in_break_admits():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x};"
        " for (const k in o) { break; }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 8: array literals ----------------------------------------------


def test_array_literal_index_read():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = [x, y]; return a[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_dynamic_index_unions():
    s = _fn(
        "function f(x: number, y: number, i: number): number {"
        " let a = [x, y]; return a[i]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1, 2})


def test_array_index_write_admits():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = [x]; a[0] = y; return a[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_array_index_write_keeps_siblings():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = [x, x]; a[0] = y; return a[1]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_length_read_dep_free():
    s = _fn(
        "function f(x: number): number {"
        " let a = [x]; return a.length; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_array_alias_write_propagates():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = [x]; let b = a; b[0] = y; return a[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_for_of_over_array_admits():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let s2 = 0; let a = [x, y];"
        " for (const e of a) { s2 = e; }"
        " return s2; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_array_of_objects_member_chain():
    s = _fn(
        "function f(x: number): number {"
        " let a = [{f: x}]; return a[0].f; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_nested_array_index_chain():
    s = _fn(
        "function f(x: number): number {"
        " let a = [[x]]; return a[0][0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_element_alias_collapses():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = {f: x}; let a = [o]; a[0].f = y; return a[0]; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_array_spread_admits():
    s = _fn(
        "function f(x: number): number {"
        " let a = [x]; let b = [...a]; return b[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 9: string/null/undefined literals, templates, in/instanceof, delete


def test_string_null_undefined_literals_admit():
    s = _fn(
        "function f(x: number): number {"
        ' let a = "hi"; let u = undefined; let n = null;'
        " if (a === u || n === u) { return x; } return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_template_string_interpolation_deps():
    s = _fn(
        "function f(x: number): number {"
        ' let s = `v${x}w`; if (s === "v0w") { return x; } return 0; }'
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_template_string_call_sub_closes():
    s = _fn(
        "function f(x: number): number {"
        ' let s = `v${m()}`; return 0; }'
    )
    assert not s.available


def test_in_operator_deps():
    s = _fn(
        "function f(x: number): number {"
        ' let o = { a: x }; let b = "a" in o ? x : 0; return b; }'
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_delete_removes_field():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: x, b: 1 }; delete o.a; return o.a === o.b ? x : 0; }"
    )
    # o.a reads undefined after delete; the `? x` still dep 0.
    assert s.available and s.return_dependencies == frozenset({0})


def test_delete_alias_propagates():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: x }; let p = o; delete p.a;"
        " return o.a === 0 ? x : 0; }"
    )
    # `p` alias: delete reached `o` too — `o.a` is undefined.
    assert s.available and s.return_dependencies == frozenset({0})


def test_delete_dynamic_key_keeps_fields():
    s = _fn(
        "function f(x: number, k: number): number {"
        " let o = { a: x, b: 2 }; delete o[k]; return o.a + o.b; }"
    )
    # Any field may be gone — keeping deps is the over-approximation.
    assert s.available and s.return_dependencies == frozenset({0})


def test_delete_on_scalar_closes():
    s = _fn(
        "function f(x: number): number {"
        " let y = x; delete y.b; return y; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_delete_identifier_arg_admits():
    s = _fn(
        "function f(x: number): number {"
        " let y = x; let d = delete y; return d ? x : 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 10: spread/computed keys in literals, optional chain, non-null


def test_object_spread_copies_fields():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: x, b: 1 }; let p = { ...o, b: 2 };"
        " return p.a; }"
    )
    # p.a copied from o.a → dep 0.
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_spread_later_field_overrides():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: 9, b: x }; let p = { ...o, b: 2 };"
        " return p.b; }"
    )
    # p.b overridden → dep-free.
    assert s.available and s.return_dependencies == frozenset()


def test_object_spread_is_not_alias():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = { a: x }; let p = { ...o }; p.a = y; return o.a; }"
    )
    # Copy-on-write: p.a = y must NOT reach o.a → still dep 0.
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_spread_scalar_collapses():
    s = _fn(
        "function f(x: number): number {"
        " let o = { ...x, a: 1 }; return o; }"
    )
    # Scalar spread adds unknowable fields → whole literal scalar.
    assert s.available and s.return_dependencies == frozenset({0})


def test_computed_key_collapses_object():
    s = _fn(
        "function f(x: number, k: number): number {"
        " let o = { a: 1, [k]: x }; return o; }"
    )
    # `{[k]: x}` — unknown field placement → whole literal scalar:
    # deps x + k.
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_array_spread_appends_positions():
    s = _fn(
        "function f(x: number): number {"
        " let a = [x, 1]; let b = [...a, 2]; return b[0] + b[2]; }"
    )
    # b[0] = a[0] = x dep; b[2] = 2 dep-free.
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_spread_scalar_collapses():
    s = _fn(
        "function f(x: number): number {"
        " let a = [...x, 1]; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_optional_chain_member_reads():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: x }; return o?.a; }"
    )
    # `?.` reads like `.` for dep purposes (undefined adds none).
    assert s.available and s.return_dependencies == frozenset({0})


def test_optional_chain_subscript():
    s = _fn(
        "function f(x: number): number {"
        ' let o = { a: x }; return o?.["a"]; }'
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_non_null_passthrough():
    s = _fn(
        "function f(x: number): number { return x!; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 11: destructured declarations


def test_object_destructure_shorthand():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: x, b: 1 }; let { a } = o; return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_destructure_renamed():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: x }; let { a: c } = o; return c; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_destructure_default():
    s = _fn(
        "function f(x: number, d: number): number {"
        " let o = { b: 1 }; let { a = d } = o; return a; }"
    )
    # Missing field → {} plus default dep.
    assert s.available and s.return_dependencies == frozenset({1})


def test_object_destructure_pair_default():
    s = _fn(
        "function f(x: number, d: number): number {"
        " let o = { a: x }; let { a: c = d } = o; return c; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_object_destructure_rest():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: x, b: 1 }; let { a, ...rest } = o; return rest; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_destructure_nested():
    s = _fn(
        "function f(x: number): number {"
        " let o = { a: { c: x } }; let { a: { c } } = o; return c; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_destructure_of_scalar_over_approximates():
    s = _fn(
        "function f(x: number): number {"
        " let { a } = x; return a; }"
    )
    # Scalar source — sub-name unions the whole dep set.
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_destructure():
    s = _fn(
        "function f(x: number): number {"
        " let a = [x, 1]; let [p, q] = a; return p + q; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_destructure_hole_positions():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let a = [x, y]; let [p, , q] = a; return p + q; }"
    )
    # Hole is not a named child — q must still bind a[2] (missing → {}).
    s2 = _fn(
        "function f(x: number, y: number): number {"
        " let a = [1, x, y]; let [p, , q] = a; return p + q; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s2.available and s2.return_dependencies == frozenset({1})


def test_array_destructure_default_and_nested():
    s = _fn(
        "function f(x: number, d: number): number {"
        " let a = [[x]]; let [[p], q = d] = a; return p + q; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_var_destructure_is_function_scoped():
    s = _fn(
        "function f(x: number, c: boolean): number {"
        " if (c) { var { a } = { a: x }; } return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_destructure_member_call_value_closes():
    s = _fn(
        "function f(x: number): number {"
        " let { a } = o.m(); return a; }"
    )
    assert not s.available


# --- slice 12: arrow functions and function expressions


def test_arrow_basic_call():
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v + 1; return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "g"


def test_arrow_bare_param():
    s = _fn(
        "function f(x: number): number {"
        " const g = v => v; return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_arrow_capture():
    s = _fn(
        "function f(x: number, y: number): number {"
        " const g = () => y; return g(x); }"
    )
    # Captured `y` read at the call site → dep 1.
    assert s.available and s.return_dependencies == frozenset({1})


def test_arrow_capture_latest_value():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let z = x; const g = () => z; z = y; return g(); }"
    )
    # Closure reads the call-site `z` → dep 1.
    assert s.available and s.return_dependencies == frozenset({1})


def test_function_expression_body():
    s = _fn(
        "function f(x: number): number {"
        " const g = function (v: number) { return v + x; };"
        " return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_arrow_default_param():
    s = _fn(
        "function f(x: number, y: number): number {"
        " const g = (v: number = y) => v; return g(); }"
    )
    # Omitted arg → default's deps.
    assert s.available and s.return_dependencies == frozenset({1})


def test_arrow_write_merges_back():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let z = x; const g = () => { z = y; }; g(); return z; }"
    )
    # The body's store merges back as a may-write.
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_arrow_member_store_merges_back():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = { a: x }; const g = () => { o.a = y; };"
        " g(); return o.a; }"
    )
    # The unconditional call definitely ran the store — `o.a` is
    # exactly `y` (the write lands on the shared object in place).
    assert s.available and s.return_dependencies == frozenset({1})


def test_arrow_param_shadow_no_leak():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let z = x; const g = (z: number) => { z = y; };"
        " g(x); return z; }"
    )
    # `z` is the arrow's param — the write stays inside.
    assert s.available and s.return_dependencies == frozenset({0})


def test_arrow_alias():
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v; const h = g; return h(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_arrow_passed_as_arg_over_approximates():
    s = _fn(
        "function f(x: number): number {"
        " const g = () => x; return h(g); }"
    )
    # `g` isn't callable by `h` — h unresolved.
    assert not s.available
    assert s.gaps[0].reason == "call_unresolved"


def test_arrow_returned_carries_captured():
    s = _fn(
        "function f(x: number): number {"
        " let z = x; const g = () => z; return g; }"
    )
    # Returning the closure — captured deps over-approximate.
    assert s.available and s.return_dependencies == frozenset({0})


def test_calling_scalar_dep_unions():
    # A scalar callee isn't provably callable — the result
    # over-approximates to the callee scalar plus the actuals.
    s = _fn(
        "function f(x: number): number {"
        " let g = x; return g(1); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_local_shadows_function_decl():
    s = _fn(
        "function g(v: number): number { return v; }"
        "function f(x: number): number {"
        " let g = x; return g(1); }"
    )
    s_f = next(fn for fn in _summarize(
        "function g(v: number): number { return v; }"
        "function f(x: number): number {"
        " let g = x; return g(1); }"
    ).functions if fn.name == "f")
    # `g` bound to scalar x — the call dep-unions rather than
    # reaching the declaration.
    assert s_f.available and s_f.return_dependencies == frozenset({0})


def test_arrow_no_return_is_dep_free():
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => { v; }; return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset()


# --- slice 13: member calls on callable fields


def test_member_call_on_callable_field():
    s = _fn(
        "function f(x: number): number {"
        " let o = { g: (v: number) => v + 1 }; return o.g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "o.g"


def test_member_call_scalar_field_closes():
    s = _fn(
        "function f(x: number): number {"
        " let o = { g: x }; return o.g(x); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_member_call_capture():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let z = y; let o = { g: () => z }; return o.g(); }"
    )
    # Captured `z` read at the call site.
    assert s.available and s.return_dependencies == frozenset({1})


def test_member_call_write_merges_back():
    s = _fn(
        "function f(x: number, y: number): number {"
        " let o = { a: x, g: () => { o.a = y; } };"
        " o.g(); return o.a; }"
    )
    # `o` shares the instance — the body's store reaches it.
    assert s.available and s.return_dependencies == frozenset({1})


# --- slice 14: destructured formal parameters


def test_object_param_destructure():
    s = _fn(
        "function f({a, b}, x: number): number { return a + b + x; }"
    )
    # Both sub-names see the slot's dep.
    assert s.available and s.return_dependencies == frozenset({0, 1})
    assert s.parameters == ("{a, b}", "x")


def test_object_param_destructure_renamed():
    s = _fn(
        "function f({a: c}: T, x: number): number { return c + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_array_param_destructure():
    s = _fn(
        "function f([p, q]: T, x: number): number { return p + q + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_destructured_param_call_record():
    s = _fn(
        "function g({a}: T): number { return a; }"
        "function f(x: number): number { return g(x); }",
        name="f",
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].arguments == (frozenset({0}),)


def test_nested_destructured_param():
    s = _fn(
        "function f({a: {c}}: T): number { return c; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 15: async / await


def test_async_function_admits():
    s = _fn(
        "async function f(x: number): number { return x + 1; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_await_call_passthrough():
    s = _fn(
        "async function g(x: number): number { return x; }"
        "async function f(x: number): number { return await g(x); }",
        name="f",
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "g"


def test_await_passthrough_expression():
    s = _fn(
        "async function f(x: number): number { const v = await x; return v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_async_arrow_value():
    s = _fn(
        "function f(x: number): number {"
        " const g = async (v: number) => v + 1;"
        " return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_generator_admits_slice25():
    # `function*` admits since slice 25 — `yield` deps union
    # into the return deps.
    summaries = _summarize(
        "function* f(x: number): number { yield x; return x; }"
    ).functions
    (s,) = [s for s in summaries if s.name == "f"]
    assert s.available and s.return_dependencies == frozenset({0})


def test_for_await_of_iterates():
    s = _fn(
        "async function f(x: number): number {"
        " const a = [x];"
        " for await (const e of a) { x = e; }"
        " return x; }"
    )
    assert s.available


# --- slice 16: shorthand method definitions


def test_shorthand_method_field_call():
    s = _fn(
        "function f(x: number): number {"
        " const o = {m: (v: number): number => v + 1};"
        " return o.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_shorthand_method_syntax():
    s = _fn(
        "function f(x: number): number {"
        " const o = {m(v: number): number { return v + x; }};"
        " return o.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_method_captures_local():
    s = _fn(
        "function f(x: number): number {"
        " const k = x;"
        " const o = {m(v: number): number { return v + k; }};"
        " return o.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_getter_method_admits():
    # `{get a(){...}}` collects into a synthetic accessor class —
    # the literal instance is `this`, the getter's captured deps
    # flatten into the composite.
    s = _fn(
        "function f(x: number): number {"
        " const o = {get a(): number { return x; }};"
        " return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_generator_method_admits():
    s = _fn(
        "function f(x: number): number {"
        " const o = {*g(v: number) { yield v; }};"
        " return x; }"
    )
    assert s.available


def test_async_method_admits():
    s = _fn(
        "function f(x: number): number {"
        " const o = {async m(v: number): Promise<number> { return v; }};"
        " return x; }"
    )
    assert s.available


# --- slice 17: rest formal parameters


def test_rest_param_declared():
    s = _fn(
        "function f(a: number, ...rest: number[]): number { return rest; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})
    assert s.parameters == ("a", "rest")


def test_rest_param_call_unions_extras():
    s = _fn(
        "function g(a: number, ...rest: number[]): number { return rest; }"
        "function f(x: number, y: number, z: number): number {"
        " return g(x, y, z); }",
        name="f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1, 2})


def test_rest_param_arrow():
    s = _fn(
        "function f(x: number, y: number, z: number): number {"
        " const g = (a: number, ...r: number[]) => r;"
        " return g(x, y, z); }"
    )
    assert s.available and s.return_dependencies == frozenset({1, 2})


def test_rest_param_empty_collects_nothing():
    s = _fn(
        "function f(x: number): number {"
        " const g = (a: number, ...r: number[]) => r;"
        " return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_rest_param_mid_params_closes():
    s = _fn(
        "function f(...rest: number[], a: number): number { return a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_rest_arrow_mid_params_closes():
    s = _fn(
        "function f(x: number): number {"
        " const g = (...r: number[], a: number) => a;"
        " return g(x); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


# --- slice 18: assignment destructuring


def test_object_assign_destructure():
    s = _fn(
        "function f(x: number): number {"
        " let a: number; let b: number;"
        " ({a, b} = {a: x, b: x + 1});"
        " return a + b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_assign_destructure():
    s = _fn(
        "function f(x: number): number {"
        " let p: number; let q: number;"
        " [p, q] = [x, x + 1];"
        " return p + q; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_assign_destructure_param():
    # `x` rebinding to a dep-free literal leaves no param deps.
    s = _fn(
        "function f(x: number): number {"
        " ({x} = {x: 5});"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_assign_destructure_param_dep():
    s = _fn(
        "function f(x: number, y: number): number {"
        " ({x} = {x: y});"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_assign_destructure_member_target():
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: 0};"
        " ({a: o.a} = {a: x});"
        " return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_assign_destructure_unbound_closes():
    s = _fn(
        "function f(x: number): number {"
        " ({a} = {a: x});"
        " return a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_assign_destructure_augmented_closes():
    # `({a} += ...)` isn't valid JS — the unit closes wholesale.
    summaries = _summarize(
        "function f(x: number): number {"
        " let a: number;"
        " ({a} += {a: x});"
        " return a; }"
    ).functions
    assert all(s.name != "f" for s in summaries)


# --- slice 19: for-loop pattern bindings


def test_for_of_object_pattern():
    s = _fn(
        "function f(x: number): number {"
        " const rows = [{a: x}];"
        " for (const {a} of rows) { x = a; }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_for_of_array_pattern():
    s = _fn(
        "function f(x: number): number {"
        " const rows = [[x, x + 1]];"
        " for (const [p, q] of rows) { x = p; }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_for_in_pattern_binds_nothing():
    # `for (const {a} in o)` — keys are dep-free strings; `x`'s
    # zero-trip value survives the may-write join.
    s = _fn(
        "function f(x: number): number {"
        " const o = {k: x};"
        " for (const {a} in o) { x = a; }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_for_of_bare_pattern_assigns():
    s = _fn(
        "function f(x: number): number {"
        " let a: number = 0;"
        " const rows = [{a: x}];"
        " for ({a} of rows) {}"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 20: tagged templates


def test_tagged_template_name_call():
    s = _fn(
        "function tag(s: number, v: number): number { return v; }"
        "function f(x: number): number { return tag`${x}`; }",
        name="f",
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "tag"
    assert s.calls[0].arguments == (frozenset(), frozenset({0}))


def test_tagged_template_callable_tag():
    s = _fn(
        "function f(x: number): number {"
        " const tag = (s: number, v: number) => v;"
        " return tag`${x}`; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_tagged_template_member_tag():
    s = _fn(
        "function f(x: number): number {"
        " const o = {tag: (s: number, v: number) => v};"
        " return o.tag`a${x}b${x+1}`; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_tagged_template_unresolved_tag_closes():
    s = _fn(
        "function f(x: number): number { return tag`${x}`; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "call_unresolved"


# --- slice 21: classes, this, new


def test_class_ctor_and_field():
    s = _fn(
        "function f(x: number): number {"
        " class C { f: number = 0; constructor(v: number) { this.f = v; } }"
        " const c = new C(x);"
        " return c.f; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "new C"


def test_class_method_call():
    s = _fn(
        "function f(x: number): number {"
        " class C { f = 0; m(v: number): number { return this.f + v; } }"
        " const c = new C(x);"
        " return c.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_class_field_init():
    s = _fn(
        "function f(x: number): number {"
        " class C { f = 1; g = 2; }"
        " const c = new C(x);"
        " return c.f; }"
    )
    assert s.available


def test_static_method_call():
    s = _fn(
        "function f(x: number): number {"
        " class C { static sm(v: number): number { return v; } }"
        " return C.sm(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_class_extends_closes():
    s = _fn(
        "function f(x: number): number {"
        " class C extends D { }"
        " return x; }"
    )
    assert not s.available


def test_this_outside_method_closes():
    s = _fn(
        "function f(x: number): number { return this.a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_method_this_write_propagates():
    s = _fn(
        "function f(x: number): number {"
        " class C { f = 0; set(v: number): number { this.f = v; return 0; } }"
        " const c = new C(0);"
        " c.set(x);"
        " return c.f; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_top_level_class():
    s = _fn(
        "class C { f = 0; m(v: number): number { return this.f + v; } }"
        "function f(x: number): number {"
        " const c = new C(x);"
        " return c.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 22: extends / super


def test_extends_method_inherited():
    s = _fn(
        "function f(x: number): number {"
        " class C { m(v: number): number { return v; } }"
        " class D extends C { }"
        " const d = new D(x);"
        " return d.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_super_ctor_call():
    s = _fn(
        "function f(x: number): number {"
        " class C { f = 0; constructor(v: number) { this.f = v; } }"
        " class D extends C { constructor(v: number) { super(v); } }"
        " const d = new D(x);"
        " return d.f; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert any(c.callee == "super" for c in s.calls)


def test_super_method_call():
    s = _fn(
        "function f(x: number): number {"
        " class C { m(v: number): number { return v; } }"
        " class D extends C { m(v: number): number { return super.m(v); } }"
        " const d = new D(x);"
        " return d.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_extends_field_init_inherited():
    s = _fn(
        "function f(x: number): number {"
        " class C { f = 0; }"
        " class D extends C { g = 1; }"
        " const d = new D(x);"
        " return d.f; }"
    )
    assert s.available


def test_extends_non_class_admits():
    # `extends o` on a non-class value — the parent chain ends
    # but the class still builds (the expression's deps fold
    # into the class's captured scalar).
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: x};"
        " class D extends o { }"
        " return x; }"
    )
    assert s.available


def test_extends_implements_admits():
    s = _fn(
        "function f(x: number): number {"
        " class D implements I { m(v: number): number { return v; } }"
        " const d = new D(x);"
        " return d.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_super_outside_ctor_closes():
    s = _fn(
        "function f(x: number): number {"
        " class C { }"
        " class D extends C { m(v: number): number { super(v); return v; } }"
        " const d = new D(x);"
        " return d.m(x); }"
    )
    # `super(args)` is only valid in a ctor — but the model lets
    # the parent-ctor resolution decide: no ctor anywhere closes.
    assert not s.available


# --- slice 23: import / export


def test_named_import_call():
    s = _fn(
        "import {g} from './m';\n"
        "function f(x: number): number { return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "g"


def test_import_alias():
    s = _fn(
        "import {g as h} from './m';\n"
        "function f(x: number): number { return h(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_namespace_import_member_call():
    s = _fn(
        "import * as ns from './m';\n"
        "function f(x: number): number { return ns.g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_default_import_call():
    s = _fn(
        "import d from './m';\n"
        "function f(x: number): number { return d(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_side_effect_import_admits():
    s = _fn(
        "import './m';\n"
        "function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_import_type_binds_nothing():
    s = _fn(
        "import type {T} from './m';\n"
        "function f(x: number): number { return T; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_export_function_declared():
    s = _fn(
        "export function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_export_default_function():
    s = _fn(
        "export default function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_export_class():
    s = _fn(
        "export class C { m(v: number): number { return v; } }\n"
        "function f(x: number): number { const c = new C(x); return c.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_new_on_import():
    s = _fn(
        "import {C} from './m';\n"
        "function f(x: number): number { const c = new C(x); return 0; }"
    )
    assert s.available
    assert s.calls and s.calls[0].callee == "new C"


def test_body_import_closes():
    s = _fn(
        "function f(x: number): number { import {g} from './m'; return x; }"
    )
    assert not s.available


# --- slice 24: module-scope bindings


def test_module_const_read():
    s = _fn(
        "const g = 5;\n"
        "function f(x: number): number { return g + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_var_read():
    s = _fn(
        "var g = 5;\n"
        "function f(x: number): number { return g + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_composite_member_read():
    s = _fn(
        "const cfg = {a: 1, b: 2};\n"
        "function f(x: number): number { return cfg.a + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_value_from_call():
    s = _fn(
        "function g(): number { return 1; }\n"
        "const c = g();\n"
        "function f(x: number): number { return c + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_call_forward_declared():
    s = _fn(
        "const c = g();\n"
        "function g(): number { return 1; }\n"
        "function f(x: number): number { return c + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_export_const_read():
    s = _fn(
        "export const g = 5;\n"
        "function f(x: number): number { return g + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_unmodellable_closes_unit():
    s = _fn(
        "const g = unknown_fn();\n"
        "function f(x: number): number { return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


def test_module_write_from_function_admits():
    # `cfg.a = x` where `cfg` is a module-scope composite — the
    # shared table receives the write.
    s = _fn(
        "const cfg = {a: 1};\n"
        "function f(x: number): number { cfg.a = x; return 0; }"
    )
    assert s.available
    assert s.return_dependencies == frozenset()


def test_local_shadows_module():
    s = _fn(
        "const g = 5;\n"
        "function f(x: number): number { let g = x; return g; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 25: generators / yield


def test_generator_yield_deps():
    s = _fn(
        "function* f(x: number): number { yield x; yield 1; return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_generator_yield_star():
    s = _fn(
        "function h(x: number): number { return x; }\n"
        "function* f(x: number): number { yield* h(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_generator_value_call():
    s = _fn(
        "function f(x: number): number {"
        " const g = function*(v: number) { yield v; };"
        " const it = g(x);"
        " return x; }"
    )
    assert s.available


def test_yield_in_generator_method():
    s = _fn(
        "function f(x: number): number {"
        " class C { *m(v: number) { yield v; } }"
        " const c = new C(x);"
        " const it = c.m(x);"
        " return x; }"
    )
    assert s.available


def test_yield_deps_isolated_per_callable():
    s = _fn(
        "function* f(x: number): number {"
        " const g = function*(v: number) { yield 1; };"
        " g(x);"
        " yield x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_top_level_generator():
    s = _fn(
        "function* g(x: number): number { yield x; }\n"
        "function f(x: number): number { return x; }"
    )
    assert s.available


# --- slice 26: optional calls `?.()`


def test_optional_call_scalar_callee():
    s = _fn(
        "function f(x: number): number {"
        " const o = {v: x};"
        " const r = o.f?.(x);"
        " return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_optional_call_unbound_member():
    s = _fn(
        "function f(x: number): number {"
        " const o = {};"
        " const r = o?.f?.(x);"
        " return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_optional_call_bound_callable():
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v;"
        " const r = g?.(x);"
        " return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "g"


def test_optional_call_declared():
    s = _fn(
        "function g(v: number): number { return v; }\n"
        "function f(x: number): number {"
        " const r = g?.(x);"
        " return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_plain_scalar_call_still_closes():
    s = _fn(
        "function f(x: number): number {"
        " const o = {v: x};"
        " return o.f(x); }"
    )
    assert not s.available


def test_optional_subscript_call():
    s = _fn(
        "function f(x: number): number {"
        " const o = {v: x};"
        " const r = o?.['f']?.(x);"
        " return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 27: private `#` members and `static {}` blocks


def test_private_field():
    s = _fn(
        "function f(x: number): number {"
        " class C { #p = 1; m(v: number) { return this.#p + v; } }"
        " const c = new C();"
        " return c.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_private_method():
    s = _fn(
        "function f(x: number): number {"
        " class C { #m(v: number) { return v; }"
        " m(v: number) { return this.#m(v); } }"
        " const c = new C();"
        " return c.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_private_field_init_sees_this():
    s = _fn(
        "function f(x: number): number {"
        " class C { #p = x; get(v: number) { return this.#p; } }"
        " const c = new C();"
        " return c.get(x); }"
    )
    assert s.available


def test_static_block():
    s = _fn(
        "function f(x: number): number {"
        " class C { static { C.s = 1; } static m(v: number) { return v; } }"
        " return C.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_static_block_deps_captured():
    s = _fn(
        "function f(x: number): number {"
        " const y = x;"
        " class C { static { const t = y + 1; C.s = t; }"
        " m(v: number) { return v; } }"
        " const c = new C();"
        " return c.m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 28: `arguments` and spread actuals


def test_arguments_index():
    s = _fn(
        "function f(x: number, y: number): number {"
        " return arguments[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_arguments_dynamic_index():
    s = _fn(
        "function f(x: number, y: number): number {"
        " const i = x;"
        " return arguments[i]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_arguments_in_invoked_callable():
    s = _fn(
        "function f(x: number): number {"
        " const g = function(a: number, b: number) {"
        "   return arguments[1]; };"
        " return g(x, 0); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_arguments_length_dep_free():
    s = _fn(
        "function f(x: number): number { return arguments.length; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_spread_call_actual():
    s = _fn(
        "function g(a: number, b: number): number { return a + b; }\n"
        "function f(x: number): number {"
        " const arr = [x];"
        " return g(...arr, 0); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "g"


def test_spread_call_scalar_operand():
    s = _fn(
        "function g(v: number): number { return v; }\n"
        "function f(x: number): number { return g(...[x]); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_spread_in_declared_call_records():
    s = _fn(
        "function g(a: number): number { return a; }\n"
        "function f(x: number): number { return g(...[x]); }"
    )
    assert s.calls and s.calls[0].arguments == (frozenset({0}),)


# --- slice 29: well-known globals


def test_math_member_call():
    s = _fn(
        "function f(x: number): number {"
        " return Math.max(x, 1); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "Math.max"


def test_object_static_call():
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: x};"
        " const k = Object.keys(o);"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_console_log_call():
    s = _fn(
        "function f(x: number): number {"
        " console.log(x);"
        " return x; }"
    )
    assert s.available and s.calls[0].callee == "console.log"


def test_number_conversion_call():
    s = _fn(
        "function f(x: number): number {"
        " const s = String(x);"
        " return x; }"
    )
    assert s.available


def test_new_error_global():
    s = _fn(
        "function f(x: number): number {"
        " const e = new Error();"
        " return x; }"
    )
    assert s.available


def test_global_shadowed_by_local():
    s = _fn(
        "function f(x: number): number {"
        " const Math = {max: (a: number) => a};"
        " return Math.max(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_promise_all():
    s = _fn(
        "function f(x: number): number {"
        " const p = Promise.all([x]);"
        " return x; }"
    )
    assert s.available


# --- slice 30: container built-in methods


def test_map_arrow():
    s = _fn(
        "function f(x: number): number {"
        " const a = [x];"
        " const b = a.map(v => v + 1);"
        " return b[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "a.map"


def test_map_bound_callable():
    s = _fn(
        "function f(x: number): number {"
        " const a = [x];"
        " const cb = (v: number) => v;"
        " const b = a.map(cb);"
        " return b[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_forEach_records_calls():
    s = _fn(
        "function g(v: number): number { return v; }\n"
        "function f(x: number): number {"
        " const a = [x];"
        " a.forEach(v => g(v));"
        " return x; }"
    )
    assert s.available and len(s.calls) == 2


def test_reduce_accumulator():
    s = _fn(
        "function f(x: number): number {"
        " const a = [x];"
        " return a.reduce((acc, v) => acc + v, 0); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_some_includes_join():
    s = _fn(
        "function f(x: number): number {"
        " const a = [x];"
        " const b = a.some(v => v > 0) || a.includes(x) || a.join();"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_push_grows_elements():
    s = _fn(
        "function f(x: number, y: number): number {"
        " const a = [x];"
        " a.push(y);"
        " const i = x;"
        " return a[i]; }"
    )
    # A dynamic index unions every field — the pushed `y` too.
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_push_alias_sees_write():
    s = _fn(
        "function f(x: number, y: number): number {"
        " const a = [x];"
        " const b = a;"
        " a.push(y);"
        " const i = x;"
        " return b[i]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_pop_returns_element():
    s = _fn(
        "function f(x: number): number {"
        " const a = [x];"
        " return a.pop(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_user_map_field_still_closes():
    s = _fn(
        "function f(x: number): number {"
        " const o = {map: x};"
        " return o.map(); }"
    )
    assert not s.available


def test_find_returns_element():
    s = _fn(
        "function f(x: number): number {"
        " const a = [x];"
        " return a.find(v => v > 0); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice_concat():
    s = _fn(
        "function f(x: number, y: number): number {"
        " const a = [x];"
        " const b = a.slice().concat([y]);"
        " return b[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


# --- slice 31: computed-base member reads, scalar member calls, regex


def test_call_result_subscript():
    s = _fn(
        "function f(x: number): number {"
        " const a = [x];"
        " return a.slice()[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_call_result_member():
    s = _fn(
        "function f(x: number): number {"
        " class C { v = 1; m(vv: number) { return this; } }"
        " const c = new C();"
        " return c.m(x).v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_new_expression_member():
    s = _fn(
        "function f(x: number): number {"
        " class C { v = 1; }"
        " return new C().v; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_scalar_member_call():
    s = _fn(
        "function f(x: number): number {"
        " const s = x;"
        " return s.indexOf(1); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls and s.calls[0].callee == "s.indexOf"


def test_require_call_chain():
    s = _fn(
        "function f(x: number): number {"
        " const m = require('mod');"
        " return m.f(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_regex_literal_dep_free():
    s = _fn(
        "function f(x: number): number {"
        " const r = /a+/;"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_member_write_call_base_closes():
    s = _fn(
        "function f(x: number): number {"
        " const a = [x];"
        " a.slice().f = x;"
        " return x; }"
    )
    assert not s.available


# --- slice 32: type-only declarations + enums -------------------------------


def test_interface_is_noop():
    s = _fn(
        "interface I { a: number }"
        " function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_type_alias_is_noop():
    s = _fn(
        "type T = { a: number };"
        " function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_enum_member_read_dep_free():
    s = _fn(
        "enum E { A, B }"
        " function f(x: number): number { return E.A; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_enum_member_initializer():
    s = _fn(
        "const k = 1 + 2; enum E { A = k }"
        " function f(x: number): number { return E.A; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_export_and_const_enum():
    s = _fn(
        "export enum E { A = 1 } const enum F { G = 2 }"
        " function f(x: number): number { return E.A + F.G; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_declare_still_skips():
    s = _fn(
        "declare function g(): void;"
        " function f(x: number): number { return x; }"
    )
    assert s.available


# --- slice 33: class getters/setters ----------------------------------------


def test_class_getter_invokes():
    s = _fn(
        "function f(x: number): number {"
        " class C { get p() { return 1; } }"
        " const c = new C();"
        " return c.p; }"
    )
    assert s.available and s.return_dependencies == frozenset()
    assert s.calls and s.calls[-1].callee == "p"


def test_getter_reads_this():
    s = _fn(
        "function f(x: number): number {"
        " class C { v = 0; get p() { return this.v; } }"
        " const c = new C();"
        " c.v = x;"
        " return c.p; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_setter_invokes():
    s = _fn(
        "function f(x: number): number {"
        " class C { v = 0; set p(vv: number) { this.v = vv; } }"
        " const c = new C();"
        " c.p = x;"
        " return c.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_inherited_getter():
    s = _fn(
        "function f(x: number): number {"
        " class B { get p() { return 1; } }"
        " class C extends B {}"
        " const c = new C();"
        " return c.p; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_own_field_shadows_setter():
    # An own data field wins over the prototype setter — plain
    # store semantics.
    s = _fn(
        "function f(x: number): number {"
        " class C { p = 0; set p(v: number) { this.q = v; } }"
        " const c = new C();"
        " c.p = x;"
        " return c.p; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_literal_getter_on_literal_this():
    # `{get p(){...}}` binds `this` to the literal instance —
    # `o.p` invokes it through the accessor path.
    s = _fn(
        "function f(x: number): number {"
        " const o = { get p() { return x; } };"
        " return o.p; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_static_getter_admits():
    s = _fn(
        "function f(x: number): number {"
        " class C { static get p() { return 1; } }"
        " return C.p; }"
    )
    assert s.available and s.return_dependencies == frozenset()
    assert any(c.callee == "p" for c in s.calls)


def test_static_setter_admits():
    s = _fn(
        "function f(x: number): number {"
        " class C { static set p(v: number) {} }"
        " C.p = x; return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert any(c.callee == "p" and c.arguments == (frozenset({0}),) for c in s.calls)


def test_static_field_write_module_scope():
    # `C.s = v` on a module-scope class name — statics update in
    # place; the binding itself is immutable.
    s = _fn(
        "function f(x: number): number {"
        " class C { static s: number = 0; }"
        " C.s = x; return C.s; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_static_data_field_shadows_setter():
    s = _fn(
        "function f(x: number): number {"
        " class C { static p: number = 0;"
        " static set p(v: number) {} }"
        " C.p = x; return C.p; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert not any(c.callee == "p" for c in s.calls)


def test_nested_namespace_admits():
    s = _fn(
        "namespace A { export namespace B {"
        " export function g(x: number): number { return x; } } }"
        " function f(x: number): number { return A.B.g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_inherited_static_getter():
    s = _fn(
        "class B { static get p(): number { return 1; } }"
        " class C extends B {}"
        " function f(x: number): number { return C.p; }"
    )
    assert s.available and s.return_dependencies == frozenset()


# --- slice 34: async functions + empty for slots ----------------------------


def test_async_promise_return():
    s = _fn(
        "async function f(x: number): Promise<number> { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_async_await_passthrough():
    s = _fn(
        "async function f(x: number): Promise<number> {"
        " const v = await g(x); return v; }"
        " function g(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_async_nested_promise():
    s = _fn(
        "async function f(x: number): Promise<Promise<number>> {"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_async_non_scalar_promise_admits():
    s = _fn(
        "async function f(x: number): Promise<string> { return x; }"
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_nonasync_promise_admits():
    s = _fn(
        "function f(x: number): Promise<number> { return x; }"
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_for_await():
    s = _fn(
        "async function f(x: number): Promise<number> {"
        " const a = [x];"
        " for await (const v of a) { return v; }"
        " return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_bare_for_loop():
    s = _fn(
        "function f(x: number): number {"
        " let i = 0; for(;;) { i = x; break; } return i; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_labeled_bare_for():
    s = _fn(
        "function f(x: number): number {"
        " let i = 0; outer: for(;;) { i = x; break outer; }"
        " return i; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_for_partial_slots():
    s = _fn(
        "function f(x: number): number {"
        " let i = 0; for (; i < 5;) { i = x; } return i; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 35: expression callees + namespaces ------------------------------


def test_iife():
    s = _fn(
        "function f(x: number): number {"
        " const v = (() => x + 1)(); return v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_parenthesized_callee():
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v * 2; return (g)(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_call_result_callee_unions():
    # `g(x)()` — the call result is a scalar; the callee is
    # uncallable, so the fallback unions the scalar callee's deps
    # with the actuals (the same bound optional calls use).
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v; return g(x)(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_conditional_callee_unions():
    # `(x > 0 ? g : h)(x)` — the ternary collapses the callables to
    # their captured deps; the call admits via the scalar fallback.
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v;"
        " const h = (v: number) => v + 1;"
        " return (x > 0 ? g : h)(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_sequence_last_callable_invokes():
    # `(o, f)(x)` — a non-scalar sequence result keeps its shape.
    s = _fn(
        "function f(x: number): number {"
        " const g = (v: number) => v;"
        " const o = {a: x}; return (o, g)(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_import_admits():
    s = _fn(
        "function f(x: number): number {"
        " const m = import('m'); return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert any(c.callee == "import" for c in s.calls)


def test_meta_property_dep_free():
    s = _fn(
        "function f(x: number): number {"
        " return import.meta.url; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_parenthesized_member_base():
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: x}; return (o).a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_tagged_template_declared_tag():
    s = _fn(
        "function tag(s: number, v: number): number { return v; }"
        " function f(x: number): number {"
        " const r = tag`a${x}`; return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_namespace_const():
    s = _fn(
        "namespace N { export const v = 1; }"
        " function f(x: number): number { return N.v; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_namespace_function_call():
    s = _fn(
        "namespace N { export function g(v: number) { return v; } }"
        " function f(x: number): number { return N.g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_namespace_sees_module_locals():
    s = _fn(
        "const k = 2; namespace N { export const v = k; }"
        " function f(x: number): number { return N.v; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_namespace_bad_member_closes_unit():
    s = _fn(
        "namespace N { while (true) {} }"
        " function f(x: number): number { return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


# --- slice 39: catch parameters + constructor parameter properties ---------


def test_ctor_param_property_admits():
    s = _fn(
        "class C { constructor(private a: number) {} }"
        " function f(x: number): number {"
        " const c = new C(x); return c.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_ctor_readonly_param_property():
    s = _fn(
        "class C { constructor(readonly b: number, c: number) {} }"
        " function f(x: number): number {"
        " const c = new C(x); return c.b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_ctor_param_property_overwritten():
    # `this.a = 2` inside the body is an unconditional store —
    # the field loses the parameter deps.
    s = _fn(
        "class C { constructor(private a: number) { this.a = 2; } }"
        " function f(x: number): number {"
        " const c = new C(x); return c.a; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_ctor_non_prop_param_not_a_field():
    s = _fn(
        "class C { constructor(c: number) {} }"
        " function f(x: number): number {"
        " const c = new C(x); return c.c; }"
    )
    # `c.c` reads a missing field — dep-free, not the actual's deps.
    assert s.available and s.return_dependencies == frozenset()


# --- slice 40: super member access, object-literal accessors,
# JSX, computed member names -------------------------------------


def test_super_field_read_carries_instance_deps():
    # `super.a` reads the same field `this.a` does — seeded by the
    # parent's ctor parameter.
    s = _fn(
        "class B { a: number; constructor(v: number) { this.a = v; } }"
        " class C extends B { m(): number { return super.a; } }"
        " function f(x: number): number {"
        " const c = new C(x); return c.m(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_super_getter_invokes_parent_on_this():
    s = _fn(
        "class B { get p(): number { return this.b; } b: number = 0;"
        " constructor(v: number) { this.b = v; } }"
        " class C extends B { m(): number { return super.p; } }"
        " function f(x: number): number {"
        " const c = new C(x); return c.m(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_super_field_store_writes_this():
    s = _fn(
        "class B { a: number = 0; }"
        " class C extends B { m(v: number): void { super.a = v; }"
        " n(): number { return this.a; } }"
        " function f(x: number): number {"
        " const c = new C(); c.m(x); return c.n(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_super_setter_invokes_parent_on_this():
    s = _fn(
        "class B { set p(v: number) { this.b = v; } b: number = 0;"
        " read(): number { return this.b; } }"
        " class C extends B { m(v: number): void { super.p = v; } }"
        " function f(x: number): number {"
        " const c = new C(); c.m(x); return c.read(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_super_method_call_still_resolves():
    s = _fn(
        "class B { m(v: number): number { return v; } }"
        " class C extends B { n(y: number): number {"
        " return super.m(y); } }"
        " function f(x: number): number {"
        " const c = new C(); return c.n(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_literal_getter_admits():
    # `get p()` on a literal — `this` is the literal instance.
    s = _fn(
        "function f(x: number): number {"
        " const o = { b: x, get p(): number { return this.b; } };"
        " return o.p; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_literal_setter_admits():
    s = _fn(
        "function f(x: number): number {"
        " const o = { b: 0, set p(v: number) { this.b = v; } };"
        " o.p = x; return o.b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_literal_getter_captures_deps():
    # A getter closing over a parameter flattens into the
    # composite's scalar deps.
    s = _fn(
        "function f(x: number): number {"
        " const o = { get p(): number { return x; } };"
        " return x ? o.p : 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_jsx_host_element_children_deps():
    s = _fn(
        "function f(x: number): number {"
        " const el = <div>{x}</div>; return el; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_jsx_component_invokes_callable():
    s = _fn(
        "function f(x: number): number {"
        " const Comp = (p) => p.a;"
        " const el = <Comp a={x}/>; return el; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert any(c.callee == "Comp" for c in s.calls)


def test_jsx_same_unit_component_records_call():
    s = _fn(
        "function Comp(p) { return p.a; }"
        " function f(x: number): number {"
        " const el = <Comp a={x}/>; return el; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert any(c.callee == "Comp" for c in s.calls)


def test_jsx_children_flow_to_children_prop():
    s = _fn(
        "function Comp(p) { return p.children; }"
        " function f(x: number, y: number): number {"
        " const el = <Comp>{x + y}</Comp>; return el; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_jsx_fragment_admits():
    s = _fn(
        "function f(x: number): number {"
        " const el = <>{x}</>; return el; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_jsx_spread_attribute_admits():
    s = _fn(
        "function f(x: number): number {"
        " const props = { a: x };"
        " const el = <div {...props}/>; return el; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_jsx_member_tag_invokes():
    s = _fn(
        "const UI = { Btn(p) { return p.a; } };"
        " function f(x: number): number {"
        " const el = <UI.Btn a={x}/>; return el; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_jsx_unbound_component_closes():
    s = _fn(
        "function f(x: number): number {"
        " const el = <Missing a={x}/>; return x; }"
    )
    assert not s.available
    assert any(g.reason == "binding_unavailable" for g in s.gaps)


def test_computed_member_skipped_named_members_admit():
    # `[k]` members can't be keyed — the class still admits and
    # named members resolve; `c[k]()` calls stay closed.
    s = _fn(
        "function f(x: number): number { const k = 'a';"
        " class C { [k](): number { return 1; }"
        " m(): number { return x; } }"
        " const c = new C(); return c.m(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_computed_member_call_admits():
    # `c[k]()` — the computed member registers under a synthetic
    # key the dynamic call finds among the invoke candidates.
    s = _fn(
        "function f(x: number): number { const k = 'a';"
        " class C { [k](): number { return x; } }"
        " const c = new C(); return c[k](); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_computed_member_call_object_literal():
    s = _fn(
        "function f(x: number): number { const k = 'a';"
        " const o = { [k](): number { return x; } };"
        " return o[k](); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_literal_computed_method_skipped():
    s = _fn(
        "function f(x: number): number { const k = 'a';"
        " const o = { [k](): number { return 1; }, m: x };"
        " return o.m; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 41: destructured catch params, using, debugger -------


def test_catch_object_pattern_binds_thrown():
    s = _fn(
        "function f(x: number): number {"
        " try { throw x; } catch ({m}) { return m; } return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_catch_array_pattern_binds_thrown():
    s = _fn(
        "function f(x: number): number {"
        " try { throw x; } catch ([a]) { return a; } return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_catch_pattern_scoped_to_clause():
    # The destructured binding is restored after the clause.
    s = _fn(
        "function f(x: number): number {"
        " try { throw x; } catch ({m}) { } return m; }"
    )
    assert not s.available
    assert any(g.reason == "binding_unavailable" for g in s.gaps)


def test_catch_pattern_nested_and_pair():
    s = _fn(
        "function f(x: number): number {"
        " try { throw x; } catch ({m: {n}}) { return n; } return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    s = _fn(
        "function f(x: number): number {"
        " try { throw x; } catch ({a: m}) { return m; } return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_catch_pattern_default_and_rest():
    s = _fn(
        "function f(x: number, y: number): number {"
        " try { throw x; } catch ({m = y}) { return m; } return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})
    s = _fn(
        "function f(x: number): number {"
        " try { throw x; } catch ({m, ...rest}) { return rest; }"
        " return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_using_declaration_binds():
    s = _fn(
        "function g(v: number): number { return v; }"
        " function f(x: number): number {"
        " using r = g(x); return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_using_pattern_binds():
    s = _fn(
        "function g(v: number): number { return v; }"
        " function f(x: number): number {"
        " using {a, b} = g(x); return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_debugger_is_noop():
    s = _fn(
        "function f(x: number): number { debugger; return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 42: overloads, enum initializers, `new C` -----------


def test_function_overload_signature_admits():
    # Bodiless overload signatures are type-level; the
    # implementation declaration registers `g`.
    s = _fn(
        "function g(v: number): number;"
        " function g(v: number): number { return v; }"
        " function f(x: number): number { return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_enum_initializer_references_member():
    s = _fn(
        "enum E { A = 1, B = A + 1 }"
        " function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_enum_initializer_carries_deps():
    # `E.A = m` where m is a module binding — `E.A` reads the
    # field's deps.
    s = _fn(
        "function f(x: number): number {"
        " const u = x;"
        " enum E { A = u }"
        " return E.A; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_new_without_parens():
    s = _fn(
        "class C { a: number = 0; }"
        " function f(x: number): number {"
        " const c = new C; return c.a; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_new_without_parens_ctor_runs():
    s = _fn(
        "class C { a: number; constructor() { this.a = 1; } }"
        " function f(x: number): number {"
        " const c = new C; return c.a; }"
    )
    assert s.available and s.return_dependencies == frozenset()


# --- slice 43: nested function captures -------------------------


def test_nested_function_capture():
    # `function h(){ return x; }` inside f reads the enclosing
    # parameter — the hoisted `_Callable` sees call-site bindings.
    s = _fn(
        "function f(x: number): number {"
        " function h() { return x; } return h(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_nested_function_hoisted_call():
    # A call before the declaration still resolves (hoisting).
    s = _fn(
        "function f(x: number): number {"
        " const r = h(); function h() { return x; } return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_nested_function_in_block():
    s = _fn(
        "function f(x: number): number {"
        " let r = 0; if (x > 0) { function h() { return x; }"
        " r = h(); } return r; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_nested_function_deep():
    s = _fn(
        "function f(x: number): number {"
        " function g() { function h() { return x; } return h(); }"
        " return g(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_callable_call():
    # `const g = (x) => {...}` at module scope binds a callable —
    # `g(y)` inside f invokes it.
    s = _fn(
        "const g = (x: number) => { return x; }\n"
        "function f(y: number): number { return g(y); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_callable_nested_capture():
    s = _fn(
        "const g = (x: number) => { function h() { return x; }"
        " return h(); }\n"
        "function f(y: number): number { return g(y); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 44: annotation/return widening, non-composite for-of --


def test_type_predicate_return():
    s = _fn(
        "function f(x: number): x is number { return true; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_void_return():
    s = _fn("function f(x: number): void { const a = x; }")
    assert s.available


def test_never_return():
    s = _fn("function f(x: number): never { throw new Error(); }")
    assert s.available


def test_any_return_composite():
    s = _fn(
        "function f(x: number): any { const o = {a: x}; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_non_scalar_declarator_annotation():
    s = _fn(
        "function f(x: number): number {"
        " const o: {a: number} = {a: x}; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_entries_for_of():
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: x}; let s = 0;"
        " for (const [k, v] of Object.entries(o)) { s = v; }"
        " return s; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_composite_member_store():
    # `o.f = v` inside a function writes the shared module-scope
    # composite's field — later reads see the union.
    s = _fn(
        "const o: {[k: string]: number} = {};\n"
        "function f(x: number): number { o[\"a\"] = x;"
        " return o[\"a\"]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 45: parameter annotation widening --------------------


def test_unannotated_param_binds_index():
    s = _fn("function f(x): number { return x; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_composite_param_annotation_admits():
    # `f(o: Foo)` — the param binds its index; a member read of
    # it reads the whole index (over-approximation).
    s = _fn("function f(o: Foo): number { return o.a; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_method_typed_params_admit():
    s = _fn(
        "const T = { tag(a: TemplateStringsArray, ...b: number[])"
        " { return 0; } };\n"
        "function f(x: number): number { return x; }"
    )
    assert s.available


# --- slice 46: dynamic member calls -----------------------------


def test_dynamic_member_call_invokes_all():
    # `o[k]()` — every callable field is invoked and results union.
    s = _fn(
        "function f(x: number): number {"
        " const o = {m() { return x; }}; const k = \"m\";"
        " return o[k](); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_member_call_arrow_field():
    s = _fn(
        "function f(x: number): number {"
        " const o = {m: (v: number) => v}; const k = \"m\";"
        " return o[k](x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_member_call_this():
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: 0, m() { return this.a; }}; const k = \"m\";"
        " o.a = x; return o[k](); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_member_call_union():
    # Two callable fields — the result unions both bodies'
    # deps plus the actuals.
    s = _fn(
        "function f(x: number, y: number): number {"
        " const o = {m() { return x; }, n() { return y; }};"
        " const k = \"m\"; return o[k](); }"
    )
    assert s.available
    assert s.return_dependencies == frozenset({0, 1})


# --- slice 47: dynamic member writes ----------------------------


def test_dynamic_member_write_admits():
    # `o[k] = v` — every field is a may-write target.
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: 0, b: 0}; const k = \"a\";"
        " o[k] = x; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_member_write_other_field():
    # A sibling field is a may-write too — over-approximates.
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: 0, b: 0}; const k = \"a\";"
        " o[k] = x; return o.b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_member_write_keeps_callable():
    # A callable field stays invocable through the may-write —
    # its captured set widens instead of collapsing.
    s = _fn(
        "function f(x: number): number {"
        " const o = {m() { return 1; }}; const k = \"m\";"
        " o[k] = x; return o.m(); }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_dynamic_member_write_invokes_setters():
    # `c[k] = v` where the class has a setter: the setter may
    # run — its `this` write lands on the instance.
    s = _fn(
        "function f(x: number): number {"
        " class C { f: number = 0; set p(v: number) { this.f = v; } }"
        " const c = new C(); const k = \"p\";"
        " c[k] = x; return c.f; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_member_read_invokes_getters():
    s = _fn(
        "function f(x: number): number {"
        " class C { get p() { return x; } }"
        " const c = new C(); const k = \"p\";"
        " return c[k]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_member_write_nested():
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: {n: 0}, b: {n: 0}}; const k = \"a\";"
        " o[k].n = x; return o.a.n; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_member_write_class_static():
    s = _fn(
        "class C { static s: number = 0; }"
        " function f(x: number): number {"
        " const k = \"s\"; C[k] = x; return C.s; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 48: ambient/abstract/top-level statements ------------


def test_top_level_expression_statement_admits():
    # `console.log(1)` at module scope runs at import — the
    # unit stays open.
    s = _fn(
        "console.log(1);"
        " function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_top_level_effect_reaches_module_locals():
    s = _fn(
        "const o = {a: 0}; o.a = 1;"
        " function f(x: number): number { return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_top_level_unbound_call_still_closes_unit():
    s = _fn(
        "run_side_effect();"
        " function f(x: number): number { return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


def test_abstract_class_and_members_admit():
    # An abstract class registers like a normal one; abstract
    # members are signatures and skip.
    s = _fn(
        "abstract class A { abstract m(): number; }"
        " class B extends A { m(): number { return 1; } }"
        " function f(x: number): number {"
        " const b = new B(); return b.m(); }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_abstract_ctor_param_props():
    s = _fn(
        "abstract class A { constructor(private v: number) {} }"
        " class B extends A {}"
        " function f(x: number): number {"
        " const b = new B(x); return b.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_declare_module_skips():
    s = _fn(
        "declare module \"m\" {}"
        " function f(x: number): number { return x; }"
    )
    assert s.available


def test_index_signature_member_skips():
    s = _fn(
        "class C { [k: string]: number; a: number = 0; }"
        " function f(x: number): number {"
        " const c = new C(); return c.a; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_non_null_base_write_admits():
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: 0}; o!.a = x; return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


# --- slice 49: JSON surface + opt-in CLI route ------------------


def test_summary_set_to_dict_shape():
    s = ts.summarize_typescript(
        "function g(a: number): number { return a; }"
        " function f(x: number): number { return g(x); }"
    )
    d = s.to_dict()
    assert d["schema_version"] == "mumei.ts-scalar-parameter-deps/v1"
    assert len(d["context_key"]) == 64
    (f_summary,) = [
        fn for fn in d["functions"] if fn["name"] == "f"
    ]
    assert f_summary["available"] is True
    assert f_summary["return_dependencies"] == [0]
    assert f_summary["calls"][0]["callee"] == "g"
    assert f_summary["calls"][0]["arguments"] == [[0]]


def test_to_dict_unavailable_is_null():
    s = ts.summarize_typescript(
        "function f(x: number): number { return missing(x); }"
    )
    d = s.to_dict()
    assert d["functions"][0]["return_dependencies"] is None
    assert d["functions"][0]["gaps"][0]["reason"] == "call_unresolved"


def test_cli_route_emits_json(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(
        "function f(x: number): number { return x; }"
    )
    ts.main(type("A", (), {"source": str(src)})())
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.ts-scalar-parameter-deps/v1"
    assert out["functions"][0]["return_dependencies"] == [0]


def test_cli_route_missing_file(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        ts.main(type("A", (), {"source": str(tmp_path / "none.ts")})())
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "source_unreadable"


# --- slice 50: relative module resolution -----------------------------------

_MOD_B = (
    "function h(a: number): number { return a + 1; }"
    " export function g(a: number): number { return h(a); }"
    " export const K: number = 7;"
    " export class C { v: number = 0;"
    "   m(x: number): number { return x; } }"
    " export default function dd(a: number): number { return a * 2; }"
    " export { h as helper };"
)


def _resolve_b(spec):
    return {"./b": _MOD_B}.get(spec)


def test_resolved_named_import_invokes():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './b';"
            " function f(x: number): number { return g(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    # `g` invokes under module b's scope — its private helper `h`
    # resolves there; the result carries the actual's dep.
    assert s.available and s.return_dependencies == frozenset({0})


def test_resolved_import_alias():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g as h} from './b';"
            " function f(x: number): number { return h(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_resolved_namespace_import():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import * as ns from './b';"
            " function f(x: number): number { return ns.g(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_resolved_default_import():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import dd from './b';"
            " function f(x: number): number { return dd(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_resolved_reexport():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {helper} from './b';"
            " function f(x: number): number { return helper(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_resolved_class_import():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {C} from './b';"
            " function f(x: number): number {"
            " let c = new C(); return c.m(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_imported_scope_not_captured_by_importer():
    # The importer binds its OWN `h` — the imported `g`'s body
    # must still resolve `h` inside module b (or g would close
    # / pick the wrong function).
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './b';"
            " function h(a: number): number { return 999 + a; }"
            " function f(x: number): number { return g(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_unresolved_name_stays_external():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {zz} from './b';"
            " function f(x: number): number { return zz(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_unresolvable_specifier_stays_external():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './z';"
            " function f(x: number): number { return g(x); }",
            resolver=_resolve_b,
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_no_resolver_unchanged():
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './b';"
            " function f(x: number): number { return g(x); }",
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_import_cycle_is_bounded():
    modules = {
        "./a": "import {gb} from './b';"
        " export function ga(x: number): number { return gb(x); }",
        "./b": "import {ga} from './a';"
        " export function gb(x: number): number { return x; }",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {ga} from './a';"
            " function f(x: number): number { return ga(x); }",
            resolver=lambda spec: modules.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_fs_resolver_cli(tmp_path, capsys):
    (tmp_path / "b.ts").write_text(
        "export function g(a: number): number { return a; }"
    )
    (tmp_path / "a.ts").write_text(
        "import {g} from './b';"
        " function f(x: number): number { return g(x); }"
    )
    ts.main(
        type(
            "A",
            (),
            {
                "source": str(tmp_path / "a.ts"),
                "resolve_modules": True,
            },
        )()
    )
    out = json.loads(capsys.readouterr().out)
    (f_summary,) = [
        fn for fn in out["functions"] if fn["name"] == "f"
    ]
    assert f_summary["available"] is True
    assert f_summary["return_dependencies"] == [0]


# --- slice 51: `export ... from` re-export resolution -----------------------

_RE_B = (
    "export function g(a: number): number { return a + 1; }"
    " export const K: number = 7;"
    " export default function dd(a: number): number { return a; }"
)


def test_export_from_clause():
    mods = {"./b": _RE_B, "./c": "export {g} from './b';"}
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './c';"
            " function f(x: number): number { return g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_export_from_alias():
    mods = {"./b": _RE_B, "./c": "export {g as g2} from './b';"}
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g2} from './c';"
            " function f(x: number): number { return g2(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_export_star_as_namespace():
    mods = {
        "./b": _RE_B,
        "./c": "export * as nsmod from './b';",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {nsmod} from './c';"
            " function f(x: number): number { return nsmod.g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_export_star_reexports_named():
    mods = {"./b": _RE_B, "./d": "export * from './b';"}
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './d';"
            " function f(x: number): number { return g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_export_type_exports_nothing():
    mods = {
        "./b": _RE_B,
        "./c": "export type {g} from './b';",
    }
    # `export type` exports no runtime binding — `g` is
    # unexported by `./c`, so the import stays external and the
    # call yields the actual union (same over-approximation).
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './c';"
            " function f(x: number): number { return g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_require_module_exports_object_invokes():
    mods = {
        "./b": "module.exports = { g: function(a){ return a + 1; } };",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "const m = require('./b');"
            " function f(x: number): number { return m.g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_require_exports_field_invokes():
    mods = {
        "./c": "exports.g = function(a){ return a * 2; };",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "const m = require('./c');"
            " function f(x: number): number { return m.g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_require_module_exports_field_invokes():
    mods = {
        "./m": "module.exports.g = function(a){ return a * 5; };",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "const m = require('./m');"
            " function f(x: number): number { return m.g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_require_bare_function_invokes():
    mods = {
        "./d": "module.exports = function(a){ return a * 3; };",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "const g = require('./d');"
            " function f(x: number): number { return g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_require_unresolvable_stays_external():
    mods = {"./b": "module.exports = { g: function(a){ return a; } };"}
    s = next(
        fn for fn in ts.summarize_typescript(
            "const m = require('./missing');"
            " function f(x: number): number { return m.g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_require_without_resolver_stays_external():
    s = next(
        fn for fn in ts.summarize_typescript(
            "const m = require('./b');"
            " function f(x: number): number { return m.g(x); }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_require_of_esm_module_composites_exports():
    mods = {
        "./e": "export function g(a){ return a; }",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "const m = require('./e');"
            " function f(x: number): number { return m.g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_import_from_commonjs_module_reads_exports():
    mods = {
        "./c": "exports.g = function(a){ return a * 2; };",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './c';"
            " function f(x: number): number { return g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_default_import_of_commonjs_whole():
    mods = {
        "./d": "module.exports = function(a){ return a * 3; };",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "import d from './d';"
            " function f(x: number): number { return d(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_commonjs_export_write_in_importer_callable():
    # `m.g = function...` on a require-bound composite keeps the
    # stored callable invocable (copy-on-write field write).
    mods = {
        "./b": "module.exports = { g: function(a){ return a + 1; } };",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "const m = require('./b');"
            " function f(x: number): number {"
            " m.g = function(a){ return a; };"
            " return m.g(x); }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_value_alias_invokes():
    # `let h = g` — a declared function used as a value
    # materializes its `_Callable`; the alias invokes it.
    s = next(
        fn for fn in ts.summarize_typescript(
            "function g(a: number){ return a; }"
            " function f(x: number): number {"
            " let h = g; return h(x); }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_value_in_object_field():
    s = next(
        fn for fn in ts.summarize_typescript(
            "function g(a: number){ return a; }"
            " function f(x: number): number {"
            " let o = {h: g}; return o.h(x); }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_value_in_array_element():
    s = next(
        fn for fn in ts.summarize_typescript(
            "function g(a: number){ return a; }"
            " function f(x: number): number {"
            " let a = [g]; return a[0](x); }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_value_as_argument_invokes():
    # `h(c){ return c(1) }` with `h(g)` — the callable actual
    # binds to the param and invokes inside the body.
    s = next(
        fn for fn in ts.summarize_typescript(
            "function g(a: number){ return a; }"
            " function h(c){ return c(1); }"
            " function f(x: number): number { return h(g) + x; }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_arrow_value_as_argument_invokes():
    s = next(
        fn for fn in ts.summarize_typescript(
            "function h(c){ return c(1); }"
            " function f(x: number): number {"
            " return h((v) => v + x); }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_composite_as_argument_reads_field():
    s = next(
        fn for fn in ts.summarize_typescript(
            "function h(o){ return o.a; }"
            " function f(x: number): number {"
            " return h({a: x}); }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_external_as_argument_yields_union():
    # A param bound to an `_External` still calls through the
    # actuals-union convention.
    mods = {"./x": "export function g(a){ return a; }"}
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {g} from './x';"
            " function h(c){ return c(1); }"
            " function f(x: number): number { return h(g) + x; }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_this_write_reaches_caller():
    # `a.set(x); a.get()` — `this.v = a` inside `set` mutates
    # the receiver; `a.get()` reads it back.
    s = next(
        fn for fn in ts.summarize_typescript(
            "class A {"
            " v: number;"
            " set(a: number){ this.v = a; }"
            " get(){ return this.v; } }"
            " function f(x: number): number {"
            " let a = new A(); a.set(x); return a.get(); }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_this_write_reaches_caller_alias():
    # `b = a` shares the instance — the `this.v` write inside
    # `a.set` reaches `b` too (JS reference semantics).
    s = next(
        fn for fn in ts.summarize_typescript(
            "class A {"
            " v: number;"
            " set(a: number){ this.v = a; } }"
            " function f(x: number): number {"
            " let a = new A(); let b = a;"
            " a.set(x); return b.v; }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_opaque_call_may_writes_composite_arg():
    # `h(o, x)` on a DEP-UNION callee (declared function not
    # inlined) may write any field of `o` — every field takes
    # the call's dep union as a may-write.
    s = next(
        fn for fn in ts.summarize_typescript(
            "function h(o, y: number){ o.a = y; }"
            " function f(x: number): number {"
            " let o = {a: 1}; h(o, x); return o.a; }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_external_call_may_writes_composite_arg():
    mods = {"./x": "export function e(o, x){ o.a = x; }"}
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {e} from './x';"
            " function f(x: number): number {"
            " let o = {a: 1}; e(o, x); return o.a; }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    # The resolved callee's body runs under ITS builder — the
    # `o.a = x` write mutates the shared composite in place.
    assert s.available and s.return_dependencies == frozenset({0})


def test_loop_member_write_snapshot_preserved():
    # The fixed point's pre-write snapshot must survive: a
    # member write in a loop body may not execute, so `o.a`
    # keeps the join {x, y} — in-place mutation is only for
    # objects shared with an unseen scope.
    s = next(
        fn for fn in ts.summarize_typescript(
            "function f(x: number, y: number, n: number): number {"
            " let o = {a: x};"
            " for (let i = 0; i < n; i++) { o.a = y; }"
            " return o.a; }"
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_shorthand_function_value_invokes_through_field():
    # `{g}` keeps the callable shape (like `{g: g}`), so a member
    # call through the field invokes the real body.
    s = _fn(
        "function g(a) { return a; }"
        " function f(x: number): number {"
        " let m = {g}; return m.g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_shorthand_imported_callable_writes_through_field():
    mods = {
        "./x": "export function e(o, x) { o.a = x; }",
    }
    s = next(
        fn for fn in ts.summarize_typescript(
            "import {e} from './x';"
            " let m = {e};"
            " function f(x: number): number {"
            " let o = {a: 1}; m.e(o, x); return o.a; }",
            resolver=lambda spec: mods.get(spec),
        ).functions if fn.name == "f"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_shorthand_composite_field_still_collapses():
    s = _fn(
        "function f(x: number): number {"
        " let p = {a: x}; let m = {p}; return m.p.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_prototype_call_invokes():
    s = _fn(
        "function g(a) { return a; }"
        " function f(x: number): number {"
        " return g.call(null, x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_prototype_call_binds_this():
    s = _fn(
        "function g(a) { this.b = a; }"
        " function f(x: number): number {"
        " let o = {b: 1}; g.call(o, x); return o.b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_prototype_apply_array_elements():
    s = _fn(
        "function g(a, b) { return a; }"
        " function f(x: number): number {"
        " return g.apply(null, [x, 2]); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_prototype_apply_opaque_array_covers_params():
    # `arr` is opaque — its scalar dep covers every parameter
    # (unknown arity over-approximates).
    s = _fn(
        "function g(a, b) { return a; }"
        " function f(x: number, arr): number {"
        " return g.apply(null, arr); }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_function_prototype_bind_prepends_actuals():
    s = _fn(
        "function g(a, b) { return b; }"
        " function f(x: number): number {"
        " return g.bind(null, 1)(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_prototype_bind_ignores_bound_positions():
    # The bound `a` is the literal — `return a` has no deps.
    s = _fn(
        "function g(a, b) { return a; }"
        " function f(x: number): number {"
        " return g.bind(null, 1)(x); }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_function_prototype_bind_binds_this():
    s = _fn(
        "function g(a) { return this.a; }"
        " function f(x: number): number {"
        " let o = {a: x}; return g.bind(o)(1); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_prototype_bind_stored_value():
    s = _fn(
        "function g(a, b) { return b; }"
        " function f(x: number): number {"
        " let h = g.bind(null, 2); return h(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_prototype_bind_rest_position():
    s = _fn(
        "function g(a, ...r) { return a; }"
        " function f(x: number): number {"
        " return g.bind(null, 1, 2)(x); }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_scalar_callee_join_dep_unions():
    # `b ? g : h` joins two callables to a scalar — the call
    # over-approximates to callee scalar + actuals.
    s = _fn(
        "function g(a) { return a; }"
        " function h2(a) { return a + 1; }"
        " function f(x: number, b: boolean): number {"
        " let h = b ? g : h2; return h(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_non_callable_scalar_call_admits_union():
    s = _fn(
        "function f(x: number): number {"
        " let n = 5; return n(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_extends_opaque_expression_admits():
    s = _fn(
        "function f(x: number): number {"
        " class A extends Object { m() { return x; } }"
        " return new A().m(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_extends_parameter_admits():
    s = _fn(
        "function f(x: number, B): number {"
        " class A extends B { m() { return x; } }"
        " return new A().m(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_extends_known_class_inherits():
    s = _fn(
        "class P { q() { return 1; } }"
        " function f(x: number): number {"
        " class A extends P { r() { return x; } }"
        " return new A().r(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_sequence_expression_evaluates_left_to_right():
    # `(h = () => y, h)` — the last operand reads `h` AFTER the
    # assignment, so the new arrow (captured {x,y}) is invoked.
    s = _fn(
        "function g(a) { return a; }"
        " function f(x: number, y: number) {"
        " let h = g; return (h = () => y, h)(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_invoke_alias_mark_does_not_leak():
    # `h(o)` marks `o` only during the call — a later caller-side
    # conditional write keeps the pre-branch may-write union.
    s = _fn(
        "function h(o) { o.a = 2; }"
        " function f(x: number, y: number, b: boolean) {"
        " let o = {a: x}; h(o); if (b) { o.a = y; } return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_conditional_call_keeps_prewrite_field_deps():
    # `g()` inside `if (b)` may not run — the callee's write to a
    # captured composite must union with the pre-branch value, not
    # replace it through the in-place (shared-object) write path.
    s = _fn(
        "function f(x: number, y: number, b: boolean) {"
        " let o = {v: x}; const g = () => { o.v = y; };"
        " if (b) { g(); } return o.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_conditional_call_reaches_caller_alias():
    # The may-write union lands on the shared object itself, so
    # every alias (`p = o`) sees `{0,1}`, not just `o`.
    s = _fn(
        "function f(x: number, y: number, b: boolean) {"
        " let o = {v: x}; let p = o; const g = () => { o.v = y; };"
        " if (b) { g(); } return p.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_zero_trip_loop_call_keeps_prewrite_field_deps():
    # A loop body may run zero times — a callee's in-place write
    # on the captured composite is a may-write.
    s = _fn(
        "function f(x: number, y: number, c: boolean) {"
        " let o = {v: x}; const g = () => { o.v = y; };"
        " while (c) { g(); } return o.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_short_circuit_call_is_may_write():
    # `b && g()` — the RHS may not run.
    s = _fn(
        "function f(x: number, y: number, b: boolean) {"
        " let o = {v: x}; const g = () => { o.v = y; };"
        " b && g(); return o.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_ternary_call_is_may_write():
    s = _fn(
        "function f(x: number, y: number, b: boolean) {"
        " let o = {v: x}; const g = () => { o.v = y; };"
        " b ? g() : 0; return o.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_optional_call_is_may_write():
    # `g?.()` — the callee may be absent.
    s = _fn(
        "function f(x: number, y: number) {"
        " let o = {v: x}; const g = () => { o.v = y; };"
        " g?.(); return o.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_unconditional_call_replaces_field_deps():
    # Sanity: without a conditional context the write stays exact.
    s = _fn(
        "function f(x: number, y: number) {"
        " let o = {v: x}; const g = () => { o.v = y; };"
        " g(); return o.v; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_opaque_call_may_add_fields():
    # A dep-union (uninlined) callee may ADD fields — a read of
    # a field the call site never wrote still carries the
    # call's dep union via the `"*"` marker.
    s = _fn(
        "function e(o) { o.new = 1; }"
        " function f(x: number) {"
        " let o = {a: x}; e(o); return o.new; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_commonjs_whole_rebind_detaches_earlier_fields():
    mods = {
        "./m": "exports.g = function(a) { return a; };"
        " module.exports = {h: function(a) { return a + 1; }};",
    }
    s = ts.summarize_typescript(
        "import {g, h} from './m';"
        " function f(x: number) { return h(x); }",
        resolver=lambda spec: mods.get(spec),
    )
    f = next(fn for fn in s.functions if fn.name == "f")
    assert f.available and f.return_dependencies == frozenset({0})


def test_commonjs_field_write_after_whole_rebind_lands():
    mods = {
        "./m": "module.exports = {h: function(a) { return a; }};"
        " module.exports.g = function(a) { return a + 1; };",
    }
    s = ts.summarize_typescript(
        "import {h, g} from './m';"
        " function f(x: number) { return g(x); }",
        resolver=lambda spec: mods.get(spec),
    )
    f = next(fn for fn in s.functions if fn.name == "f")
    assert f.available and f.return_dependencies == frozenset({0})


def test_commonjs_exports_alias_detaches_after_rebind():
    mods = {
        "./m": "module.exports = {h: function(a) { return a; }};"
        " exports.g = function(a) { return a + 1; };",
    }
    b = ts._Builder(ts._syntax(mods["./m"].encode()))
    assert sorted(b.cjs_exports.fields) == ["h"]


def test_callee_label_scrubs_literal_keys():
    # `o["secret-value"](x)` — the literal key must not reach
    # the call record's callee label.
    s = _fn(
        'function f(x: number) {'
        ' let o = {}; o["secret-value"](x); return x; }'
    )
    assert s.calls and s.calls[0].callee == "o[?]"


def test_map_set_and_literal_get():
    s = _fn(
        "function f(x: number) {"
        " let m = new Map(); m.set('a', x); return m.get('a'); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_map_dynamic_key_get_unions_entries():
    s = _fn(
        "function f(x: number, k: string) {"
        " let m = new Map(); m.set(k, x); return m.get('a'); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_map_constructor_entries_seed():
    s = _fn(
        "function f(x: number) {"
        " let m = new Map([['a', x]]); return m.get('a'); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_set_add_and_has():
    s = _fn(
        "function f(x: number) {"
        " let s = new Set(); s.add(x); return s.has(x) ? x : 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_map_size_reads_entry_union():
    s = _fn(
        "function f(x: number) {"
        " let m = new Map(); m.set('a', x); return m.size; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_map_iteration_reads_values():
    s = _fn(
        "function f(x: number) {"
        " let m = new Map(); m.set('a', x);"
        " let y = 0; for (let [k, v] of m) { y = v; } return y; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_weakmap_entries():
    s = _fn(
        "function f(x: number) {"
        " let m = new WeakMap(); m.set('a', x); return m.get('a'); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_function_constructor_is_external():
    s = _fn(
        "function f(x: number) {"
        " let g = new Function('a', 'return a'); return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_new_on_joined_ctor_dep_unions():
    s = _fn(
        "class C { m(a) { return a; } }"
        " class D { q(a) { return a; } }"
        " function f(x: number, k: string) {"
        " return new (k === 'C' ? C : D)().m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_self_recursive_function_value_terminates():
    s = _fn(
        "function f(x: number) {"
        " function g(a) { return a > 0 ? g(a - 1) : a; }"
        " return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_self_recursive_arrow_terminates():
    s = _fn(
        "function f(x: number) {"
        " let g = (a) => a > 0 ? g(a - 1) : a;"
        " return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_mutually_recursive_callables_terminate():
    s = _fn(
        "function f(x: number) {"
        " let g = (a) => h(a);"
        " let h = (a) => a > 0 ? g(a - 1) : a;"
        " return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_finite_nesting_still_inlines():
    s = _fn(
        "function f(x: number) {"
        " let a = (v) => v + 1;"
        " return a(a(a(a(a(x))))); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_object_pattern_param_destructures_actual():
    s = _fn(
        "function f(x: number) {"
        " let g = ({a}) => a; return g({a: x}); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_pattern_param_destructures_actual():
    s = _fn(
        "function f(x: number) {"
        " let g = ([a, b]) => a + b; return g([x, 2]); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_pattern_param_default_evaluates():
    s = _fn(
        "function f(x: number) {"
        " let g = ({a} = {a: x}) => a; return g(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_pattern_param_nested():
    s = _fn(
        "function f(x: number) {"
        " let g = ({p: {q}}) => q; return g({p: {q: x}}); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_pattern_param_scalar_actual_unions():
    s = _fn(
        "function f(x: number) {"
        " let g = ({a}) => a; return g(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_method_pattern_param():
    s = _fn(
        "class C { m({a}) { return a + this.b; } b = 1; }"
        " function f(x: number) { return new C().m({a: x}); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_fill_writes_actual_into_elements():
    s = _fn(
        "function f(x: number) {"
        " let a = [0]; a.fill(x); return a[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_labeled_continue_admits():
    s = _fn(
        "function f(x: number) {"
        " let a = [x]; let s = 0;"
        " outer: for (let v of a) { s += v; continue outer; }"
        " return s; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_throw_propagates_past_catchless_try():
    s = _fn(
        "function f(x: number) {"
        " try { try { throw x; } finally { } }"
        " catch (e) { return e; } return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_rethrow_keeps_deps_through_finally():
    s = _fn(
        "function f(x: number) {"
        " try { try { throw x; } catch (e) { throw e + 1; } }"
        " catch (e2) { return e2; } return 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_hole_positions():
    s = _fn(
        "function f(x: number) {"
        " let a = [, x, ]; return a[1]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_array_middle_hole_positions():
    s = _fn(
        "function f(x: number) {"
        " let a = [x, , x]; return a[2]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_var_hoist_write_before_decl():
    s = _fn(
        "function f(x: number) { y = x; var y = 0; return y; }"
    )
    assert s.available and s.return_dependencies == frozenset()


def test_var_hoist_read_before_decl():
    s = _fn(
        "function f(x: number) { return y + x; var y = 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_callable_member_write_widens_captured():
    s = _fn(
        "function f(x: number) {"
        " let g = (a) => a; g.extra = x; return g.extra; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_literal_computed_method_key():
    s = _fn(
        "class C { ['m'](a) { return a; } }"
        " function f(x: number) { return new C().m(x); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_literal_computed_field_key():
    s = _fn(
        "class C { ['f'] = 1; }"
        " function f(x: number) { return new C().f + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_dynamic_computed_field_seed():
    s = _fn(
        "class C { [k] = 1; }"
        " function f(x: number, k: string) { return new C()[k] + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_opaque_extends_seeds_fields():
    s = _fn(
        "class A extends B { m() { return 1; } }"
        " function f(x: number, B) { return new A(x).a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_map_set_chains_to_get():
    s = _fn(
        "function f(x: number) {"
        " let m = new Map(); return m.set('a', x).get('a'); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_map_delete_result_carries_key_deps():
    s = _fn(
        "function f(x: number, k: string) {"
        " let m = new Map(); m.set('a', x);"
        " return m.delete(k) ? 1 : 0; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_map_set_key_does_not_shadow_method_dispatch():
    s = _fn(
        "function f(x: number) {"
        " let m = new Map(); m.set('get', x);"
        " return m.get('a'); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_local_class_map_shadows_builtin():
    s = _fn(
        "function f(x: number) { let y = 0;"
        " let Map = class { constructor(v) { y = v; } };"
        " new Map(x); return y; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_chained_bind_prepends_bound_actuals():
    s = _fn(
        "function f(x: number) { let g = (a) => a;"
        " return g.bind(null, x).bind(null, 1)(); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_bound_this_wins_over_call_receiver():
    s = _fn(
        "function f(x: number) {"
        " let g = function () { return this.v; };"
        " let o = { v: x }, p = { v: 1 };"
        " return g.bind(o).call(p); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_apply_args_use_numeric_order_not_insertion():
    s = _fn(
        "function f(x: number) { let g = (a, b) => b;"
        " let a = []; a[1] = x; a[0] = 0;"
        " return g.apply(null, a); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_depth_bound_still_writes_composite_actuals():
    s = _fn(
        "function f(x: number) { let o = { a: 0 };"
        " let h = (v, n) => { o.a = v; if (n > 0) h(v, n - 1); };"
        " h(x, 40); return o.a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_module_exports_realias_keeps_exports_writes():
    mod_a = (
        "exports.g = (a) => a; module.exports = exports;"
        " exports.h = (a) => a + 1;"
    )
    s = ts.summarize_typescript(
        "const a = require('./a');"
        " function f(x: number) { return a.h(x); }",
        lambda spec: {"./a": mod_a}.get(spec),
    )
    fn = next(fn for fn in s.functions if fn.name == "f")
    assert fn.available and fn.return_dependencies == frozenset({0})


def test_var_redeclaration_does_not_shadow_param():
    s = _fn("function f(x: number) { return x; var x = 1; }")
    assert s.available and s.return_dependencies == frozenset({0})
    s2 = _fn("function f(x: number) { return x; var x; }")
    assert s2.available and s2.return_dependencies == frozenset({0})


def test_destructured_param_default_fills_missing_field():
    s = _fn(
        "function f(x: number) {"
        " let g = ({ a } = { a: x }) => a; return g({}); }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_derived_instance_inherits_dynamic_field_deps():
    s = _fn(
        "function f(x: number, k: string) {"
        " class C { [k] = x; } class D extends C {}"
        " return new D().a + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_chained_map_set_keeps_entry_table():
    s = _fn(
        "function f(x: number, y: number) { let m = new Map();"
        " return m.set('a', x).set('b', y).get('b'); }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_dynamic_computed_key_deps_seed_fields():
    s = _fn(
        "class C { [k] = 1; }"
        " function f(x: number, k: string) { return new C().a + x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice65_destructured_default_star_bucket_merge():
    # `({a} = {a: x})` on a composite actual seeds its "*" bucket
    # — when "*" holds a non-frozenset the union must not crash.
    src = """function f(o, x) {
  const g = ({a} = {a: x}) => a;
  return g(o);
}
const o = {};
o["*"] = {n: 1};
f(o, 7);"""
    result = _summarize(src)
    assert result.functions


def test_slice65_loop_inplace_map_mutation_converges():
    # `m.set('k', x)` mutates the composite the fixed-point check
    # reads — convergence must see through in-place mutation.
    src = """function f(x, n) {
  let m = new Map();
  let a = 0;
  for (let i = 0; i < n; i++) {
    a = m.get('k');
    m.set('k', x);
  }
  return a;
}"""
    (f,) = _summarize(src).functions
    assert 0 in f.return_dependencies


def test_review3_function_value_in_loop_scope_converges():
    s = _fn(
        "function f(x) { let g = () => x; "
        "for (let i = 0; i < 3; i++) { g(); } return x; }",
        "f",
    )
    assert s.available
    assert s.return_dependencies == {0}


def test_review3_delete_field_in_loop_converges():
    s = _fn(
        "function f(x) { let o = {a: x, b: 1}; "
        "for (let i = 0; i < 3; i++) { delete o.a; } return o.b; }",
        "f",
    )
    assert s.available


def test_review3_reassign_smaller_composite_in_loop_converges():
    s = _fn(
        "function f(x) { let o = {a: x, b: 1}; "
        "for (let i = 0; i < 3; i++) { o = {a: x}; } return o.a; }",
        "f",
    )
    assert s.available
    assert s.return_dependencies == {0}


def test_review4_delete_field_in_loop_keeps_prototype_fallback():
    # `delete this.f` in a loop removes the field hiding a getter —
    # later reads must union the surviving field deps ({0}) with
    # the getter's ({1}), and the join must still converge.
    s = _fn(
        "class C { f; get f() { return this.g; } g; "
        "m(x, y) { this.f = x; this.g = y; "
        "for (let i = 0; i < 3; i++) { delete this.f; } "
        "return this.f; } }\n"
        "function f(a, b) { let c = new C(); return c.m(a, b); }",
        "f",
    )
    assert s.available
    assert s.return_dependencies == {0, 1}


def test_review5_deleted_field_keeps_both_method_candidates():
    # A conditional `delete this.m` leaves both call candidates:
    # the own callable field ({2} through its arg) and the
    # prototype method ({0} through `this.k`).
    s = _fn(
        "class C { m(v) { return this.k; } k; "
        "n(a, c, x) { this.m = (v) => v; "
        "if (c) { delete this.m; } this.k = a; return this.m(x); } }\n"
        "function f(a, c, x) { let o = new C(); return o.n(a, c, x); }",
        "f",
    )
    assert s.available
    assert s.return_dependencies == {0, 2}


# --- review round 6: isolated alternate candidates --------------------------


def test_review6_alt_invocation_sees_pre_call_state():
    # The primary (own-field) candidate writes c.g; the prototype
    # alternate must still read the field as it was before the call.
    s = _fn(
        "class C {"
        "  g: number = 0;"
        "  m(v: number): number { return this.g }"
        "}"
        "function f(y: number, z: number): number {"
        "  let c = new C();"
        "  c.g = y;"
        "  c.m = (v: number) => { c.g = z; return v };"
        "  if (y > 0) { delete c.m }"
        "  return c.m(z)"
        "}"
    )
    assert s.available
    assert frozenset({0, 1}) <= s.return_dependencies


def test_review6_bind_reaches_alternate_candidate():
    # `bind` on a maybe-deleted member applies the partial
    # application to every candidate, not just the primary.
    s = _fn(
        "class C {"
        "  m(v: number): number { return v }"
        "}"
        "function f(x: number, y: number): number {"
        "  let c = new C();"
        "  c.m = (v: number) => y;"
        "  if (x > 0) { delete c.m }"
        "  const g = c.m.bind(c, x);"
        "  return g(y)"
        "}"
    )
    assert s.return_dependencies == frozenset({0, 1})


def test_review6_unsupported_alt_keeps_opaque_writes():
    # An alternate whose body closes still may-writes every field
    # of a composite actual (the opaque callee shape).
    s = _fn(
        "class C {"
        "  m(v: number): number { return unknownFn(v) }"
        "}"
        "function f(x: number): number {"
        "  let c = new C();"
        "  c.m = (v: number) => x;"
        "  if (x > 0) { delete c.m }"
        "  let o = {v: 0, src: x};"
        "  c.m(o);"
        "  return o.v"
        "}"
    )
    assert frozenset({0}) <= s.return_dependencies


def test_review6_getter_fallback_deps_reach_call_result():
    # A maybe-deleted member covered by a getter — the getter's
    # own result deps stay on the call path, not just reads.
    s = _fn(
        "class C {"
        "  g: number = 0;"
        "  get f(): any { return this.g }"
        "}"
        "function f(x: number, y: number): number {"
        "  let c = new C();"
        "  c.g = x;"
        "  c.f = (v: number) => y;"
        "  if (y > 0) { delete c.f }"
        "  return c.f(y)"
        "}"
    )
    assert s.return_dependencies == frozenset({0, 1})


def test_review6_method_value_keeps_alt_captured():
    # Reading the maybe-deleted member as a value scalarizes
    # every candidate's captured deps.
    s = _fn(
        "function f(x: number, y: number): number {"
        "  class C { m(v: number): number { return v + y } }"
        "  let c = new C();"
        "  c.m = (v: number) => x;"
        "  if (x > 0) { delete c.m }"
        "  return c.m"
        "}"
    )
    assert frozenset({0, 1}) <= s.return_dependencies


def test_review7_alt_write_through_wrapper_param():
    # The alternate's write to a composite actual passed through a
    # wrapper's parameter must reach the outer caller's object —
    # merging the clone back into the original in place keeps the
    # aliasing the primary candidate relies on.
    s = _fn(
        "class C {"
        "  m(p: any): number { p.v = p.src; return 0 }"
        "}"
        "function w(c: C, q: any): number {"
        "  c.m(q);"
        "  return 0"
        "}"
        "function f(x: number): number {"
        "  let c = new C();"
        "  c.m = (p: any) => x;"
        "  if (x > 0) { delete c.m }"
        "  let o = {v: 0, src: x};"
        "  w(c, o);"
        "  return o.v"
        "}"
    )
    assert frozenset({0}) <= s.return_dependencies


def test_review7_unchanged_function_stays_callable():
    # A name still bound to the same function must not collapse to
    # a scalar on merge-back — the later call needs its body's
    # writes, which a scalarized callee would drop.
    s = _fn(
        "class C {"
        "  m(v: number): number { return v }"
        "}"
        "function f(x: number, y: number): number {"
        "  let c = new C();"
        "  c.m = (v: number) => v;"
        "  if (x > 0) { delete c.m }"
        "  const cap = {v: 0};"
        "  const g = () => { cap.v = y; return 0 };"
        "  c.m(x);"
        "  g();"
        "  return cap.v"
        "}"
    )
    assert frozenset({1}) <= s.return_dependencies


def test_review7_aliased_names_keep_object_identity():
    # Two names bound to the same object must still alias after
    # merge-back: a write through one reaches reads of the other.
    s = _fn(
        "class C {"
        "  m(v: number): number { return v }"
        "}"
        "function f(x: number, y: number): number {"
        "  let c = new C();"
        "  c.m = (v: number) => v;"
        "  if (x > 0) { delete c.m }"
        "  let o = {v: 0};"
        "  let p = o;"
        "  c.m(x);"
        "  p.v = y;"
        "  return o.v"
        "}"
    )
    assert frozenset({1}) <= s.return_dependencies


def test_review8_alt_rebind_unions_instead_of_mutating():
    # An alternate callee that REBINDS a shared name to a different
    # object must union the two worlds, not mutate the old object in
    # place: the name may hold either shape afterwards, and a class
    # divergence collapses method resolution instead of resolving to
    # the old class.
    s = _fn(
        "class A {"
        "  v: number = 0;"
        "  probe(a: number): number { return a }"
        "}"
        "class C {"
        "  m(): number { return 0 }"
        "}"
        "function f(x: number, y: number): number {"
        "  let o = new A();"
        "  o.v = y;"
        "  let other = {w: x};"
        "  let c = new C();"
        "  c.m = () => { o = other; return 0 };"
        "  if (x > 0) { delete c.m }"
        "  c.m();"
        "  return o.w"
        "}"
    )
    assert frozenset({0}) <= s.return_dependencies


def test_review9_alt_captured_write_before_rebind_reaches_aliases():
    # An alternate callee that writes a shared object through a
    # caller name and then rebinds that name must still merge the
    # writes back to the original object — every alias sees them.
    s = _fn(
        "class C {"
        "  m(): number { o.v = y; o = other; return 0 }"
        "}"
        "function f(x: number, y: number): number {"
        "  let c = new C();"
        "  let o = {v: 0};"
        "  let p = o;"
        "  let other = {w: x};"
        "  c.m = () => 0;"
        "  if (x > 0) { delete c.m }"
        "  c.m();"
        "  return p.v"
        "}"
    )
    assert frozenset({1}) <= s.return_dependencies


def test_review9_primary_captured_write_reaches_aliases():
    # The same shared-object write through the primary callee:
    # the write lands on the shared object, so the alias reads it.
    s = _fn(
        "function f(x: number, y: number): number {"
        "  let o = {v: 0};"
        "  let p = o;"
        "  const g = () => { o.v = y; return 0 };"
        "  g();"
        "  return p.v"
        "}"
    )
    assert s.return_dependencies == frozenset({1})


def test_review8_alt_rebind_divergent_class_closes_call():
    # After a rebind the name may be the old class instance OR the
    # new object — a later method call must not resolve to only the
    # original class, so the union collapses to the opaque shape.
    s = _fn(
        "class A {"
        "  v: number = 0;"
        "  probe(a: number): number { return a }"
        "}"
        "class C {"
        "  m(): number { return 0 }"
        "}"
        "function f(x: number, y: number): number {"
        "  let o = new A();"
        "  o.v = y;"
        "  let other = {w: x};"
        "  let c = new C();"
        "  c.m = () => { o = other; return 0 };"
        "  if (x > 0) { delete c.m }"
        "  c.m();"
        "  return o.probe(y)"
        "}"
    )
    assert not s.available


def test_conditional_module_write_keeps_alias_identity():
    # `a`/`b` alias the same module-scope composite; a conditional
    # write through `b` must not split them into two objects — a
    # later unconditional write through `a` still reaches `b`.
    s = _fn(
        "let a = {f: 0};\n"
        "let b = a;\n"
        "function f(c: boolean, x: number, y: number): number {"
        "  if (c) { b.g = x; }"
        "  a.h = y;"
        "  return b.h;"
        "}"
    )
    assert s.available and s.return_dependencies == frozenset({2})


def test_conditional_function_field_stays_invocable():
    # A conditional write to a shared object's function field must
    # keep the field invocable — scalarizing the join would skip the
    # body of a later `o.g?.(x)` and lose its writes.
    s = _fn(
        "function f(c: boolean, x: number): number {"
        "  let o = {g: (v: number) => v};"
        "  let w = {h: 0};"
        "  if (c) { o.g = (v: number) => { w.h = v; return v; }; }"
        "  o.g?.(x);"
        "  return w.h;"
        "}"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_rebound_actual_keeps_inplace_writes():
    # The alternate candidate writes the shared object in place,
    # then rebinds the name — the in-place write still belongs to
    # the caller's object, so `o.f` keeps x's dep.
    s = _fn(
        "function f(c: boolean, x: number): number {"
        "  let o = {f: 0};"
        "  let g = (v: number) => v;"
        "  if (c) { g = (v: number) => { o.f = v; o = {f: v}; return v; }; }"
        "  g?.(x);"
        "  return o.f;"
        "}"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_manifest_round_trip_restores_the_summary_set():
    s = ts.summarize_typescript(
        "function f(x: number, y: number): number {"
        "  let g = (v: number) => v + 1;"
        "  return g(x) + y;"
        "}"
    )
    restored = ts.TsSummarySet.from_dict(json.loads(json.dumps(s.to_dict())))
    assert restored == s


def test_manifest_restoration_rejects_a_wrong_schema():
    s = ts.summarize_typescript(
        "function f(x: number): number { return x; }"
    )
    bad = s.to_dict()
    bad["schema_version"] = "mumei.other/v1"
    with pytest.raises(ValueError, match="malformed"):
        ts.TsSummarySet.from_dict(bad)


def test_manifest_restoration_rejects_unknown_and_missing_keys():
    s = ts.summarize_typescript(
        "function f(x: number): number { return x; }"
    )
    good = s.to_dict()
    bad = dict(good, extra_key=1)
    with pytest.raises(ValueError, match="malformed"):
        ts.TsSummarySet.from_dict(bad)
    bad = dict(good)
    del bad["context_key"]
    with pytest.raises(ValueError, match="malformed"):
        ts.TsSummarySet.from_dict(bad)


def test_manifest_restoration_rejects_a_contradictory_available_flag():
    s = ts.summarize_typescript(
        "function f(x: number): number { return x; }"
    )
    good = s.to_dict()
    forged = dict(good)
    forged["functions"] = [
        dict(good["functions"][0], available=False)
    ]
    # `available: false` alongside a derived result claims the
    # record has a gap it does not declare — malformed.
    with pytest.raises(ValueError, match="malformed"):
        ts.TsSummarySet.from_dict(forged)


def test_manifest_restoration_rejects_wrong_types():
    s = ts.summarize_typescript(
        "function f(x: number): number { return x; }"
    )
    good = s.to_dict()
    bad = dict(good, context_key=123)
    with pytest.raises(ValueError, match="malformed"):
        ts.TsSummarySet.from_dict(bad)
    bad = dict(good)
    bad["functions"] = [dict(good["functions"][0], result={"oops": 1})]
    fn = dict(good["functions"][0])
    fn["calls"] = [
        {
            "span": {"start": 0, "end": 1},
            "callee": "g",
            "arguments": [["x"]],
            "result": [0],
        }
    ]
    bad["functions"] = [fn]
    with pytest.raises(ValueError, match="malformed"):
        ts.TsSummarySet.from_dict(bad)


def test_context_key_covers_resolved_module_bytes():
    mod_a = "export function g(v: number) { return v; }"
    mod_b = "export function g(v: number) { return v + 1; }"
    src = "import {g} from './m';\nfunction f(x: number): number { return g(x); }"
    resolver_a = lambda spec: mod_a if spec == "./m" else None
    resolver_b = lambda spec: mod_b if spec == "./m" else None
    sa = ts.summarize_typescript(src, resolver=resolver_a)
    sb = ts.summarize_typescript(src, resolver=resolver_b)
    # Same primary file, different resolved module — the context
    # key must differ or a stale manifest would be reused.
    assert sa.context_key != sb.context_key
    # An unresolvable specifier records nothing — same as no resolver.
    resolver_none = lambda spec: None
    sc = ts.summarize_typescript(src, resolver=resolver_none)
    sd = ts.summarize_typescript(src)
    assert sc.context_key == sd.context_key


# --- slice 67: ts-summaries-accept (strict whole-context acceptance) ----------

def _accept_args(source, manifest, function, resolve=False):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "manifest": str(manifest),
            "function": function,
            "resolve_modules": resolve,
        },
    )()


def test_accept_route_accepts_a_surviving_function(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(
        "function f(x: number): number { return g(x); }"
        "function g(v: number): number { return v + 1; }"
    )
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(ts.summarize_typescript(src.read_bytes()).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        ts.main_accept(_accept_args(src, manifest, "f"))
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.ts-summary-accept/v1"
    assert out["accepted"] is True
    assert out["context_match"] is True
    assert out["function"] == "f"
    assert out["summary"]["name"] == "f"
    assert out["summary"]["return_dependencies"] == [0]


def test_accept_route_refuses_a_changed_context(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text("function f(x: number): number { return x; }")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            ts.summarize_typescript(
                b"function f(x: number): number { return x + 0; }"
            ).to_dict()
        )
    )
    with pytest.raises(SystemExit) as exc:
        ts.main_accept(_accept_args(src, manifest, "f"))
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["context_match"] is False
    assert out["reason"] == "context_mismatch"
    assert "summary" not in out


def test_accept_route_refuses_an_unknown_function(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text("function f(x: number): number { return x; }")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(ts.summarize_typescript(src.read_bytes()).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        ts.main_accept(_accept_args(src, manifest, "absent"))
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["context_match"] is True
    assert out["reason"] == "unknown_function"
    assert "summary" not in out


def test_accept_route_emits_the_live_record_not_the_forged_one(
    tmp_path, capsys
):
    src = tmp_path / "a.ts"
    src.write_text("function f(x: number): number { return x; }")
    manifest = tmp_path / "m.json"
    forged = ts.summarize_typescript(src.read_bytes()).to_dict()
    forged["functions"][0]["return_dependencies"] = [1, 2, 3]
    manifest.write_text(json.dumps(forged))
    with pytest.raises(SystemExit):
        ts.main_accept(_accept_args(src, manifest, "f"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    assert out["summary"]["return_dependencies"] == [0]


def test_accept_route_rejects_a_malformed_manifest(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text("function f(x: number): number { return x; }")
    manifest = tmp_path / "m.json"
    manifest.write_text('{"schema_version": "mumei.other/v1"}')
    with pytest.raises(SystemExit) as exc:
        ts.main_accept(_accept_args(src, manifest, "f"))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "manifest_malformed"


def test_accept_route_matches_context_across_resolved_modules(
    tmp_path, capsys
):
    mod = tmp_path / "b.ts"
    mod.write_text(
        "export function h(a: number): number { return a + 1; }"
    )
    src = tmp_path / "a.ts"
    src.write_text(
        "import { h } from './b';"
        " function f(x: number): number { return h(x); }"
    )
    resolver = ts._fs_resolver(str(src))
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            ts.summarize_typescript(
                src.read_bytes(), resolver=resolver
            ).to_dict()
        )
    )
    with pytest.raises(SystemExit) as exc:
        ts.main_accept(_accept_args(src, manifest, "f", resolve=True))
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    # A resolved module's bytes changing flips the context key even
    # though the primary source is byte-identical.
    mod.write_text(
        "export function h(a: number): number { return a + 2; }"
    )
    with pytest.raises(SystemExit):
        ts.main_accept(_accept_args(src, manifest, "f", resolve=True))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "context_mismatch"


# --- slice 68: ts-summaries-check / ts-summaries-reuse routes -----------------

def _route_args(source, manifest=None, function=None,
                output=None, resolve=False):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "manifest": str(manifest) if manifest else None,
            "function": function,
            "output": str(output) if output else None,
            "resolve_modules": resolve,
        },
    )()


_SRC_TWO = (
    "function f(x: number): number { return g(x); }"
    "function g(v: number): number { return v + 1; }"
)
_SRC_TWO_CHANGED = (
    "function f(x: number): number { return g(x); }"
    "function g(v: number): number { return 7; }"
)


def test_check_route_partitions_names(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    manifest = tmp_path / "m.json"
    old = ts.summarize_typescript(_SRC_TWO).to_dict()
    old["functions"].append(
        {
            "name": "gone",
            "available": True,
            "parameters": [],
            "return_dependencies": [],
            "calls": [],
            "gaps": [],
            "effects": "none_in_supported_fragment",
            "pinned": [],
        }
    )
    manifest.write_text(json.dumps(old))

    src.write_text(_SRC_TWO_CHANGED)
    ts.main_check(_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.ts-summary-check/v1"
    assert out["context_match"] is False
    # g now returns a constant: its deps flip {0}→{}. f's record is
    # unchanged — the call transfer already depends on every actual
    # regardless of the callee's result.
    assert out["stale"] == ["g"]
    assert out["missing"] == ["gone"]
    assert out["reusable"] == ["f"]


def test_check_route_reports_reusable_records(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(ts.summarize_typescript(_SRC_TWO).to_dict())
    )
    ts.main_check(_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert out["context_match"] is True
    assert out["reusable"] == ["f", "g"]
    assert out["stale"] == []
    assert out["missing"] == []


def test_reuse_route_merges_verbatim_and_fresh(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    manifest = tmp_path / "m.json"
    old = ts.summarize_typescript(
        "function f(x: number): number { return x; }"
        "function g(v: number): number { return v + 1; }"
    ).to_dict()
    manifest.write_text(json.dumps(old))
    ts.main_reuse(_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    # The merged manifest is keyed to the fresh context.
    assert out["schema_version"] == "mumei.ts-scalar-parameter-deps/v1"
    fresh = ts.summarize_typescript(_SRC_TWO)
    assert out["context_key"] == fresh.context_key
    by_name = {f["name"]: f for f in out["functions"]}
    # g is reusable verbatim (identical record under both sources);
    # f changed and was freshly re-derived.
    assert by_name["g"]["return_dependencies"] == [0]
    assert by_name["f"]["calls"][0]["callee"] == "g"


def test_reuse_route_output_file(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(ts.summarize_typescript(_SRC_TWO).to_dict())
    )
    out_path = tmp_path / "merged.json"
    ts.main_reuse(_route_args(src, manifest, output=out_path))
    merged = json.loads(out_path.read_text())
    assert merged["context_key"] == (
        ts.summarize_typescript(_SRC_TWO).context_key
    )


def test_loop_nested_field_write_keeps_next_pass_deps():
    # A nested field read then rewritten inside a loop — the
    # may-write mutates the shared inner composite in place; a
    # shallow fixed-point snapshot would see its own mutation and
    # end the loop a pass early, dropping `b` from `r`.
    s = _fn(
        "function f(a: number, b: number): number {"
        " let o = { n: { v: 0 } };"
        " let r = 0;"
        " for (let i = 0; i < 2; i++) {"
        "   r = o.n.v;"
        "   o.n.v = b;"
        " }"
        " return r;"
        " }"
    )
    assert s.available
    assert s.return_dependencies == frozenset({1})


def test_bind_merged_partials_keep_every_bound_actual():
    # `g.bind(null, x)` joined with `g.bind(null, y)` — the two
    # partial applications differ only in `bound`, so both must
    # stay candidates and both bound actuals feed the result.
    s = _fn(
        "function g(a: number, b: number): number { return a + b; }"
        "function f(x: number, c: boolean, y: number): number {"
        " let h = c ? g.bind(null, x) : g.bind(null, y);"
        " return h(0);"
        " }"
    )
    assert s.available
    # The boolean condition's dep may also fold in via `extra` —
    # the bound actuals are the requirement.
    assert {0, 2} <= s.return_dependencies


def test_scalar_candidate_makes_writes_may():
    # `cb` is `w` joined with the scalar `x` — the call may not run
    # `w` at all, so `w`'s constant overwrite of `o.f` must union
    # with the pre-call value instead of replacing it.
    s = _fn(
        "function f(x: number, c: boolean): number {"
        " let o = { f: x };"
        " function w(): number { o.f = 0; return 0; }"
        " let cb = c ? w : x;"
        " cb();"
        " return o.f;"
        " }"
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_check_route_ambiguous_name_is_never_reusable(
    tmp_path, capsys
):
    source = (
        "function f(x: number): number { return x; }"
        "function g(): number {"
        " function f(x: number, y: number): number { return y; }"
        " return f(0, 1);"
        " }"
    )
    src = tmp_path / "a.ts"
    src.write_text(source)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(ts.summarize_typescript(source).to_dict())
    )
    ts.main_check(_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert "f" in out["stale"]
    assert "f" not in out["reusable"]


def _attempt_args(source, attempt_timeout=60000, output=None,
                  resolve=False, memory_bound_mb=None):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "resolve_modules": resolve,
            "attempt_timeout": attempt_timeout,
            "memory_bound_mb": memory_bound_mb,
            "output": str(output) if output else None,
        },
    )()


def test_attempt_route_emits_lineage_and_candidate(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    ts.main_attempt(_attempt_args(src))
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "mumei.ts-summaries-attempt-report/v1"
    sequence = report["sequence"]
    assert (
        sequence["schema_version"] == "mumei.verifier-attempt-sequence/v1"
    )
    assert sequence["attempts"][0]["state"] == "exited"
    assert sequence["attempts"][0]["events"][-1]["kind"] == "exited"
    assert sequence["attempts"][0]["events"][-1]["exit_code"] == 0
    assert sequence["selected_result"]["attempt_number"] == 1
    normalized = report["normalized"]
    assert normalized["outcome"] == "exited"
    assert normalized["exit_code"] == 0
    candidate = report["candidate"]
    assert candidate["schema_version"] == "mumei.verifier-evidence-candidate/v1"
    assert (
        candidate["request_fingerprint"]
        == sequence["request_fingerprint"]
    )


def test_attempt_route_rejects_resolve_modules(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    with pytest.raises(SystemExit) as exc:
        ts.main_attempt(_attempt_args(src, resolve=True))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "unsupported_option"


def test_attempt_route_binds_source_bytes(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    ts.main_attempt(_attempt_args(src))
    first = json.loads(capsys.readouterr().out)["sequence"][
        "request_fingerprint"
    ]
    src.write_text(_SRC_TWO_CHANGED)
    ts.main_attempt(_attempt_args(src))
    second = json.loads(capsys.readouterr().out)["sequence"][
        "request_fingerprint"
    ]
    assert first != second


def test_attempt_route_output_file(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    out_path = tmp_path / "report.json"
    ts.main_attempt(_attempt_args(src, output=out_path))
    capsys.readouterr()
    report = json.loads(out_path.read_text())
    assert report["schema_version"] == "mumei.ts-summaries-attempt-report/v1"


def test_attempt_route_rejects_output_overwriting_source(
    tmp_path, capsys
):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    with pytest.raises(SystemExit) as exc:
        ts.main_attempt(_attempt_args(src, output=src))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
    assert src.read_text() == _SRC_TWO


def test_attempt_route_rejects_output_hardlink_to_source(
    tmp_path, capsys
):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    link = tmp_path / "linked.ts"
    os.link(src, link)
    with pytest.raises(SystemExit) as exc:
        ts.main_attempt(_attempt_args(src, output=link))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
    assert src.read_text() == _SRC_TWO


def test_attempt_route_skips_candidate_when_inputs_change(
    tmp_path, capsys, monkeypatch
):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    from agent import attempt_runner

    real_run = attempt_runner.AttemptRunner.run

    def run_then_modify(
        self, request, argv, memory_bound_mb=None, cancel_event=None,
        feed_bytes=None,
    ):
        src.write_text(_SRC_TWO_CHANGED)
        return real_run(
            self,
            request,
            argv,
            memory_bound_mb=memory_bound_mb,
            cancel_event=cancel_event,
            feed_bytes=feed_bytes,
        )

    monkeypatch.setattr(
        attempt_runner.AttemptRunner, "run", run_then_modify
    )
    ts.main_attempt(_attempt_args(src))
    report = json.loads(capsys.readouterr().out)
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report


# --- declared-route review regressions ----------------------------------------


def test_review_destructured_param_names_binders_not_source():
    # The manifest slot names the BOUND identifiers — a default
    # expression's source text must never leak into `parameters`.
    s = _fn(
        "function f({a = 1, b}: {a?: number, b: number}): number {"
        " return a + b; }"
    )
    assert s.available
    assert s.parameters == ("{a, b}",)
    assert "1" not in s.parameters[0]


def test_review_spread_actual_expands_elements():
    # `g(...[0, x])` binds b to x's own index — an element-wise
    # expansion, not one union slot.
    s = _fn(
        "function g(a: number, b: number): number { return b; }"
        "function f(x: number): number { return g(...[0, x]); }",
        name="f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_unshift_shifts_existing_indices():
    s = _fn(
        "function f(x: number): number {"
        " let a = [0, 0];"
        " a.unshift(x);"
        " return a[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})
    s2 = _fn(
        "function f(x: number): number {"
        " let a = [0, 0];"
        " a.unshift(x);"
        " return a[2]; }"
    )
    assert s2.return_dependencies == frozenset()


def test_review_push_multi_arg_indices():
    s = _fn(
        "function f(x: number): number {"
        " let a = [0];"
        " a.push(0, x);"
        " return a[2]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_array_map_any_index():
    s = _fn(
        "function f(x: number): number {"
        " let a = [0];"
        " let b = a.map(v => v + x);"
        " return b[3]; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_dynamic_write_records_wildcard():
    # `o[k] = x` may add a field never named — a later missing-key
    # read still carries x via the `"*"` bucket.
    s = _fn(
        "function f(k: string, x: number): number {"
        " let o = {a: 0};"
        " o[k] = x;"
        " return o.b; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_review_var_redecl_keeps_binding():
    s = _fn(
        "function f(a: number): number {"
        " var a;"
        " return a; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_expr_subscript_update_writes():
    # `o[k]++` inside an expression still writes — the wildcard
    # bucket picks up the key's deps.
    s = _fn(
        "function f(k: string): number {"
        " let o = {a: 0};"
        " let r = (o[k]++, 0);"
        " return o.b; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_module_write_does_not_leak_params():
    # A module-local written inside f must not carry f's parameter
    # index into g's summary — `g`'s read of `m` is external.
    summaries = _summarize(
        "let m = 0;"
        "function f(a: number): void { m = a; }"
        "function g(): number { return m; }"
    )
    g = next(s for s in summaries.functions if s.name == "g")
    assert g.available and g.return_dependencies == frozenset()


def test_review_conditional_static_write_unions():
    # `if (c) C.s = x` is a may-write — the skipped path's binding
    # survives the join.
    s = _fn(
        "class C { static s = 0; }"
        "function f(c: boolean, x: number, y: number): number {"
        " C.s = y;"
        " if (c) { C.s = x; }"
        " return C.s; }"
    )
    assert s.available and s.return_dependencies == frozenset({1, 2})


def test_review_conditional_static_write_over_method():
    # The same may-write over a static METHOD must not crash on a
    # `_Callable | frozenset` union — the method flattens to its
    # captured deps.
    s = _fn(
        "class C { static m(): number { return 0; } }"
        "function f(c: boolean, v: number): number {"
        " if (c) { C.m = v; }"
        " return 1; }"
    )
    assert s.available


def test_review_conditional_array_mutation_keeps_deps():
    # `c && a.shift()` is a may-write: when `c` is false the
    # original `a[0]` still answers the read, so its deps survive.
    s = _fn(
        "function f(c: boolean, x: number): number {"
        " let a = [x, 0];"
        " c && a.shift();"
        " return a[0]; }"
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_review_spread_wildcard_tail_keeps_later_actuals():
    # `g(...a, x)` where `a` has a `*` tail: the spread length is
    # unknown, so `x` lands at an ambiguous position — its deps
    # must still reach a callee parameter.
    s = _fn(
        "const g = (a: number, b: number): number => b;"
        "function f(x: number): number {"
        " const a: number[] = [];"
        " a.push(0);"
        " return g(...a, x); }",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_fs_resolver_importer_relative(tmp_path):
    # `./c` imported from `sub/b.ts` resolves `sub/c.ts`, not the
    # entry directory's `c.ts`.
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.ts").write_text("export const w = 9;")
    (tmp_path / "c.ts").write_text("export const w = 0;")
    resolver = ts._fs_resolver(str(tmp_path / "a.ts"))
    resolved = resolver("./c", importer=str(sub / "b.ts"))
    assert resolved is not None
    assert resolved.read_bytes() == b"export const w = 9;"


def test_review_fs_resolver_rejects_symlink_escape(tmp_path):
    # A symlinked candidate must not read outside the declared
    # directory tree.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.ts").write_text("export const s = 1;")
    base = tmp_path / "src"
    base.mkdir()
    (base / "c.ts").symlink_to(outside / "secret.ts")
    resolver = ts._fs_resolver(str(base / "a.ts"))
    assert resolver("./c") is None


def test_review_accept_rejects_ambiguous_name(tmp_path, capsys):
    src = tmp_path / "a.ts"
    src.write_text(
        "function f(x: number): number { return x; }"
        "function g(v: number): number {"
        "  function f(n: number): number { return n; }"
        "  return f(v); }"
    )
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            ts.summarize_typescript(src.read_bytes()).to_dict()
        )
    )
    with pytest.raises(SystemExit):
        ts.main_accept(_accept_args(src, manifest, "f"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "ambiguous_function"


def test_review_accept_rejects_undeclared_function(tmp_path, capsys):
    # The fresh set has `g`, the manifest doesn't declare it —
    # context matches but the record stays unadopted.
    src = tmp_path / "a.ts"
    src.write_text("function g(x: number): number { return x; }")
    doc = ts.summarize_typescript(src.read_bytes()).to_dict()
    doc["functions"] = []
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(doc))
    with pytest.raises(SystemExit):
        ts.main_accept(_accept_args(src, manifest, "g"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "undeclared_function"


def test_review_check_output_rejects_manifest_overwrite(
    tmp_path, capsys
):
    src = tmp_path / "a.ts"
    src.write_text(_SRC_TWO)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(ts.summarize_typescript(_SRC_TWO).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        ts.main_check(_route_args(src, manifest, output=manifest))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
    assert json.loads(manifest.read_text())["functions"]


def test_review6_conditional_pop_then_push_keeps_deps():
    # `c && a.pop()` may empty the array, so `a.push(x)` can land
    # at index 0 — a read of `a[0]` must keep `x`'s dep.
    s = _fn(
        "function f(c: boolean, x: number): number {"
        " let a = [0];"
        " c && a.pop();"
        " a.push(x);"
        " return a[0]; }"
    )
    assert s.available and 1 in s.return_dependencies
