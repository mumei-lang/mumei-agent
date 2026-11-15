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


def test_missing_return_type_closes():
    s = _fn("function f(x: number) { return x; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_non_scalar_return_type_closes():
    s = _fn("function f(x: number): string { return \"s\"; }")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_async_function_admits_scalar():
    # Slice 15: `async` admits — `await` degrades to operand deps.
    s = _fn(
        "async function f(x: number): number { return x; }"
    )
    assert s.available and s.return_dependencies == frozenset({0})


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


def test_non_scalar_local_annotation_closes():
    s = _fn(
        "function f(x: number): number { let a: string = \"s\"; return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "binding_unavailable"


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


def test_declare_closes_unit():
    src = (
        "declare function d(x: number): number;\n"
        "function f(x: number): number { return x; }"
    )
    s = _fn(src)
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


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


def test_getter_method_closes():
    s = _fn(
        "function f(x: number): number {"
        " const o = {get a(): number { return x; }};"
        " return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_expression"


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


def test_extends_non_class_closes():
    s = _fn(
        "function f(x: number): number {"
        " const o = {a: x};"
        " class D extends o { }"
        " return x; }"
    )
    assert not s.available


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


def test_module_write_from_function_closes():
    s = _fn(
        "const cfg = {a: 1};\n"
        "function f(x: number): number { cfg.a = x; return 0; }"
    )
    assert not s.available


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


def test_declare_still_closes():
    s = _fn(
        "declare function g(): void;"
        " function f(x: number): number { return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_unit"


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


def test_object_literal_getter_closes():
    # `{get p(){...}}` would bind `this` to the literal — not
    # modelled; closes.
    s = _fn(
        "function f(x: number): number {"
        " const o = { get p() { return x; } };"
        " return o.p; }"
    )
    assert not s.available


def test_static_getter_closes():
    s = _fn(
        "function f(x: number): number {"
        " class C { static get p() { return 1; } }"
        " return C.p; }"
    )
    assert not s.available


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


def test_async_non_scalar_promise_closes():
    s = _fn(
        "async function f(x: number): Promise<string> { return x; }"
    )
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_nonasync_promise_closes():
    s = _fn(
        "function f(x: number): Promise<number> { return x; }"
    )
    assert not s.available


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
