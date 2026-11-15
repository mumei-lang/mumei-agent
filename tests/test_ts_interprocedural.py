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


def test_rest_parameter_closes():
    s = _fn("function f(...xs: number[]): number { return 0; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


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


def test_throw_admits():
    s = _fn(
        "function f(x: number): number { throw x; return 0; }"
    )
    assert s.available


def test_throw_new_expression_closes():
    s = _fn(
        "function f(x: number): number { throw new Error(); return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


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
    # `Math` is an unbound base — the member call can't resolve.
    s = _fn(
        "function f(x: number): number { return Math.abs(x); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_unresolved_call_closes():
    s = _fn("function f(x: number): number { return g(x); }")
    assert not s.available
    assert s.gaps[0].reason == "call_unresolved"


def test_new_expression_closes():
    s = _fn("function f(x: number): number { return new C(x); }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_member_access_on_unbound_closes():
    s = _fn("function f(x: number): number { return o.f; }")
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_member_access_on_scalar_closes():
    s = _fn(
        "function f(x: number): number { let o = x; return o.f; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


def test_subscript_on_unbound_closes():
    s = _fn("function f(x: number): number { return a[0]; }")
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_subscript_on_scalar_closes():
    s = _fn(
        "function f(x: number): number { let a = x; return a[0]; }"
    )
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


def test_template_string_admits():
    s = _fn("function f(x: number): number { return `v${x}`; }")
    assert s.available and s.return_dependencies == frozenset({0})


def test_assignment_to_unbound_closes():
    s = _fn(
        "function f(x: number): number { y = x; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


def test_non_scalar_local_annotation_closes():
    s = _fn(
        "function f(x: number): number { let a: string = \"s\"; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


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


def test_dynamic_subscript_write_closes():
    s = _fn(
        "function f(x: number, k: number): number {"
        " let o = {a: x}; o[k] = x; return o.a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


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


def test_member_read_on_param_closes():
    s = _fn(
        "function f(x: number): number { return x.f; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


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


def test_member_path_bound_to_name_closes_member_read():
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: {c: x}}; let q = o.a; return q.c; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


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
    s = _fn(
        "function f(x: number): number {"
        " let o = {a: x}; let p = {o}; return p.o.a; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


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


def test_for_in_on_scalar_closes():
    s = _fn(
        "function f(x: number): number {"
        " for (const k in x) { x = 0; } return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_statement"


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
    assert s.available and s.return_dependencies == frozenset({0, 1})


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


def test_calling_scalar_closes():
    s = _fn(
        "function f(x: number): number {"
        " let g = x; return g(1); }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


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
    # `g` bound to scalar x — the call can't reach the declaration.
    assert not s_f.available
    assert s_f.gaps[0].reason == "unsupported_expression"


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
    assert s.available and s.return_dependencies == frozenset({0, 1})
