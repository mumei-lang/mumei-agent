"""Function-local dataflow / path-sensitivity layer (``agent/dataflow_facts.py``).

Covers the roadmap item "外部コード安全性推論の意味モデル化（データフロー / パス感度）":
constant folding, guard propagation (``if`` / early ``return`` / loop
conditions), reaching definitions for divisors and indices, ``len``-derived
values, local aliases, closure / address-taking invalidation, and the new
dataflow-only bug categories (nil-map write, lock/unlock, open/close).
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from agent import dataflow_facts, tree_sitter_extract
from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues


def _go(body: str, **kwargs: object) -> dataflow_facts.FunctionDataflow:
    flow = dataflow_facts.analyze_function(body, "go", **kwargs)  # type: ignore[arg-type]
    assert flow is not None
    return flow


def _facts(body: str, expr: str, **kwargs: object) -> dataflow_facts.PathFacts:
    facts = _go(body, **kwargs).facts_for_expression(expr)
    assert facts is not None, f"no facts reach {expr!r}"
    return facts


def _messages(source: str) -> list[str]:
    return [issue.message for issue in _detect_go_safety_issues(source)]


# --------------------------------------------------------------------------- #
# 1. constant folding
# --------------------------------------------------------------------------- #


def test_evaluate_constant_expression_arithmetic_and_shift() -> None:
    values = {"KB": Fraction(1024)}
    assert dataflow_facts.evaluate_constant_expression("KB * 4 + 1", values) == 4097
    assert dataflow_facts.evaluate_constant_expression("1 << 10", values) == 1024
    assert dataflow_facts.evaluate_constant_expression("(KB - 24) / 1000", values) == 1


def test_evaluate_constant_expression_rejects_unknown_names_and_calls() -> None:
    assert dataflow_facts.evaluate_constant_expression("N + 1", {}) is None
    assert dataflow_facts.evaluate_constant_expression("len(xs)", {}) is None
    assert dataflow_facts.evaluate_constant_expression("1 / 0", {}) is None


def test_fold_constants_resolves_derived_constants_in_dependency_order() -> None:
    folded = dataflow_facts.fold_constants(
        [("total", "rows * cols"), ("rows", "4"), ("cols", "rows * 2"), ("name", '"x"')]
    )
    assert folded == {"rows": 4, "cols": 8, "total": 32}


def test_local_const_block_is_folded_for_divisor() -> None:
    body = (
        "const (\n"
        "    base = 8\n"
        "    width = base * 2\n"
        ")\n"
        "return n / width\n"
    )
    facts = _facts(body, "n / width", param_names={"n"})
    assert facts.consts["width"] == 16
    assert "width" in facts.nonzero


def test_derived_constant_divisor_is_not_flagged() -> None:
    source = (
        "package demo\n"
        "const base = 8\n"
        "const bucket = base * 4\n"
        "func Hash(n int) int {\n"
        "    return n % bucket\n"
        "}\n"
    )
    assert _messages(source) == []


# --------------------------------------------------------------------------- #
# 2. guard propagation (if / early return / loop conditions)
# --------------------------------------------------------------------------- #


def test_if_guard_establishes_nonzero_on_true_branch() -> None:
    body = "if d != 0 {\n    return n / d\n}\nreturn 0\n"
    assert "d" in _facts(body, "n / d", param_names={"n", "d"}).nonzero


def test_early_return_establishes_nonzero_after_guard() -> None:
    body = "if d == 0 {\n    return 0\n}\nreturn n / d\n"
    assert "d" in _facts(body, "n / d", param_names={"n", "d"}).nonzero


def test_guard_on_the_wrong_branch_does_not_establish_fact() -> None:
    body = "if d == 0 {\n    return n / d\n}\nreturn 0\n"
    facts = _facts(body, "n / d", param_names={"n", "d"})
    assert "d" not in facts.nonzero


def test_loop_condition_bounds_index() -> None:
    body = "for i := 0; i < len(xs); i++ {\n    if xs[i] == 0 {\n        return xs[i]\n    }\n}\nreturn 0\n"
    facts = _facts(body, "xs[i]", param_names={"xs"}, sequence_names={"xs"})
    assert "i" in facts.nonneg
    assert ("i", "xs") in facts.lt_len
    assert facts.bounded_indices([("xs", "i")]) == {"i"}


def test_reverse_loop_bounds_index() -> None:
    body = "for i := len(xs) - 1; i >= 0; i-- {\n    return xs[i]\n}\nreturn 0\n"
    facts = _facts(body, "xs[i]", param_names={"xs"}, sequence_names={"xs"})
    assert ("i", "xs") in facts.lt_len
    assert "i" in facts.nonneg


def test_range_over_sequence_bounds_index_but_map_keys_do_not() -> None:
    body = "for i := range xs {\n    return xs[i]\n}\nreturn 0\n"
    facts = _facts(body, "xs[i]", param_names={"xs"}, sequence_names={"xs"})
    assert ("i", "xs") in facts.lt_len

    body = "for id := range taskMap {\n    idx := id % len(colors)\n    return colors[idx]\n}\nreturn 0\n"
    facts = _facts(body, "colors[idx]", param_names={"taskMap", "colors"}, sequence_names={"colors"})
    assert ("idx", "colors") not in facts.lt_len


def test_switch_case_establishes_facts_per_case() -> None:
    body = (
        "switch {\n"
        "case d == 0:\n"
        "    return 0\n"
        "default:\n"
        "    return n / d\n"
        "}\n"
    )
    assert "d" in _facts(body, "n / d", param_names={"n", "d"}).nonzero


def test_facts_merge_conservatively_across_joining_paths() -> None:
    body = "if d == 0 {\n    d = fallback\n}\nreturn n / d\n"
    facts = _facts(body, "n / d", param_names={"n", "d", "fallback"})
    assert "d" not in facts.nonzero


# --------------------------------------------------------------------------- #
# 3. reaching definitions and len-derived values
# --------------------------------------------------------------------------- #


def test_reaching_constant_definition_of_divisor() -> None:
    body = "scale := 100\nreturn v / scale\n"
    facts = _facts(body, "v / scale", param_names={"v"})
    assert facts.consts["scale"] == 100
    assert "scale" in facts.nonzero


def test_redefinition_kills_previous_fact() -> None:
    body = "scale := 100\nscale = other\nreturn v / scale\n"
    facts = _facts(body, "v / scale", param_names={"v", "other"})
    assert "scale" not in facts.nonzero
    assert "scale" not in facts.consts


def test_len_derived_index_is_bounded_when_container_nonempty() -> None:
    body = "if len(xs) == 0 {\n    return 0\n}\nlast := len(xs) - 1\nreturn xs[last]\n"
    facts = _facts(body, "xs[last]", param_names={"xs"}, sequence_names={"xs"})
    assert ("last", "xs") in facts.lt_len
    assert "last" in facts.nonneg


def test_len_derived_index_unbounded_when_container_may_be_empty() -> None:
    body = "last := len(xs) - 1\nreturn xs[last]\n"
    facts = _facts(body, "xs[last]", param_names={"xs"}, sequence_names={"xs"})
    assert "last" not in facts.nonneg


def test_modulo_len_requires_nonempty_container() -> None:
    flagged = (
        "package demo\n"
        "func Pick(changes []int, k int) int {\n"
        "    idx := k % len(changes)\n"
        "    return changes[idx]\n"
        "}\n"
    )
    assert _messages(flagged) != []
    safe = (
        "package demo\n"
        "func Pick(changes []int, k uint) int {\n"
        "    if len(changes) == 0 {\n"
        "        return 0\n"
        "    }\n"
        "    idx := k % len(changes)\n"
        "    return changes[idx]\n"
        "}\n"
    )
    assert _messages(safe) == []


def test_grow_allocation_establishes_bound() -> None:
    body = (
        "if n >= len(funcTypes) {\n"
        "    funcTypes = make([]Type, n+1)\n"
        "}\n"
        "return funcTypes[n]\n"
    )
    facts = _facts(body, "funcTypes[n]", param_names={"n"}, nonneg_names={"n"}, sequence_names={"funcTypes"})
    assert ("n", "funcTypes") in facts.lt_len


# --------------------------------------------------------------------------- #
# 4. local aliases and invalidation
# --------------------------------------------------------------------------- #


def test_slice_alias_shares_length_facts() -> None:
    body = "ys := xs\nif i < len(ys) && i >= 0 {\n    return xs[i]\n}\nreturn 0\n"
    facts = _facts(body, "xs[i]", param_names={"xs", "i"}, sequence_names={"xs"})
    assert facts.bounded_indices([("xs", "i")]) == {"i"}


def test_closure_assignment_invalidates_facts() -> None:
    body = (
        "if d == 0 {\n    return 0\n}\n"
        "f := func() { d = 0 }\n"
        "f()\n"
        "return n / d\n"
    )
    facts = _facts(body, "n / d", param_names={"n", "d"})
    assert "d" not in facts.nonzero


def test_address_taken_invalidates_facts_but_indexed_address_does_not() -> None:
    body = "if d == 0 {\n    return 0\n}\nreset(&d)\nreturn n / d\n"
    assert "d" not in _facts(body, "n / d", param_names={"n", "d"}).nonzero

    tree = tree_sitter_extract.extract_statements("p := &files[i]\nok := a && b\n", "go")
    assert tree is not None
    assert tree.address_taken == frozenset()


def test_extract_statements_returns_none_for_unsupported_language() -> None:
    assert tree_sitter_extract.extract_statements("x = 1", "cobol") is None
    assert dataflow_facts.analyze_function("x = 1", "cobol") is None


# --------------------------------------------------------------------------- #
# Historical false positives previously handled by dedicated helpers
# (``_go_zero_guarded_nonzero_*``, ``_go_dual_len_loop_guarded_indices``,
# ``_go_grow_guarded_indices``, ``_go_last_index_guarded_indices``,
# ``_go_reverse_loop_guarded_indices``, ``_go_modulo_bounded_indices``).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        # zero-guarded nonzero param (early return)
        "package demo\nfunc Ratio(s Stats, n int) int {\n    if n == 0 {\n        return 0\n    }\n    return s.Total / n\n}\n",
        # zero-guarded nonzero local
        "package demo\nfunc Ratio(s Stats, xs []int) int {\n    n := len(xs)\n    if n == 0 {\n        return 0\n    }\n    return s.Total / n\n}\n",
        # dual-len loop
        "package demo\nfunc Dot(a, b []int) int {\n    for i := 0; i < len(a) && i < len(b); i++ {\n        return a[i] * b[i]\n    }\n    return 0\n}\n",
        # grow before index (make([]T, n+1))
        "package demo\nfunc Grow(limit uint64) int {\n    tmp := make([]int, limit+1)\n    return tmp[limit]\n}\n",
        # last index after emptiness check
        "package demo\nfunc Last(xs []int) int {\n    if len(xs) == 0 {\n        return 0\n    }\n    i := len(xs) - 1\n    return xs[i]\n}\n",
        # reverse loop
        "package demo\nfunc Rev(xs []int) int {\n    for i := len(xs) - 1; i >= 0; i-- {\n        return xs[i]\n    }\n    return 0\n}\n",
        # modulo bounded by nonempty length
        "package demo\nfunc Wrap(colors []string, k uint) string {\n    if len(colors) == 0 {\n        return \"\"\n    }\n    idx := k % uint(len(colors))\n    return colors[idx]\n}\n",
    ],
)
def test_historical_false_positives_are_suppressed_by_dataflow(source: str) -> None:
    assert _messages(source) == []


def test_unguarded_variants_are_still_flagged() -> None:
    assert any(
        "divide by `n`" in m
        for m in _messages(
            "package demo\nfunc Ratio(s Stats, xs []int) int {\n    n := len(xs)\n    return s.Total / n\n}\n"
        )
    )
    assert any(
        "index `xs[i]`" in m
        for m in _messages(
            "package demo\nfunc Last(xs []int) int {\n    i := len(xs) - 1\n    return xs[i]\n}\n"
        )
    )


# --------------------------------------------------------------------------- #
# Expanded categories: nil-map write, lock/unlock, open/close
# --------------------------------------------------------------------------- #


def test_nil_map_write_is_reported() -> None:
    source = (
        "package demo\n"
        "func Build(keys []string) map[string]int {\n"
        "    var m map[string]int\n"
        "    for _, k := range keys {\n"
        "        m[k] = 1\n"
        "    }\n"
        "    return m\n"
        "}\n"
    )
    messages = _messages(source)
    assert any("never initialized" in m for m in messages), messages


def test_initialized_map_write_is_not_reported() -> None:
    source = (
        "package demo\n"
        "func Build(keys []string) map[string]int {\n"
        "    var m map[string]int\n"
        "    m = make(map[string]int)\n"
        "    for _, k := range keys {\n"
        "        m[k] = 1\n"
        "    }\n"
        "    return m\n"
        "}\n"
    )
    assert _messages(source) == []


def test_double_lock_is_reported() -> None:
    source = (
        "package demo\n"
        "func (c *Cache) Get(k string) int {\n"
        "    c.mu.Lock()\n"
        "    c.mu.Lock()\n"
        "    v := c.items[k]\n"
        "    c.mu.Unlock()\n"
        "    return v\n"
        "}\n"
    )
    messages = _messages(source)
    assert any("deadlock" in m for m in messages), messages


def test_lock_held_on_early_return_is_reported() -> None:
    source = (
        "package demo\n"
        "func (c *Cache) Get(k string) (int, bool) {\n"
        "    c.mu.Lock()\n"
        "    v, ok := c.items[k]\n"
        "    if !ok {\n"
        "        return 0, false\n"
        "    }\n"
        "    c.mu.Unlock()\n"
        "    return v, true\n"
        "}\n"
    )
    messages = _messages(source)
    assert any("still held" in m for m in messages), messages


def test_deferred_unlock_and_balanced_lock_are_not_reported() -> None:
    deferred = (
        "package demo\n"
        "func (c *Cache) Get(k string) (int, bool) {\n"
        "    c.mu.Lock()\n"
        "    defer c.mu.Unlock()\n"
        "    v, ok := c.items[k]\n"
        "    if !ok {\n"
        "        return 0, false\n"
        "    }\n"
        "    return v, true\n"
        "}\n"
    )
    assert _messages(deferred) == []
    balanced = (
        "package demo\n"
        "func (c *Cache) Get(k string) (int, bool) {\n"
        "    c.mu.Lock()\n"
        "    v, ok := c.items[k]\n"
        "    if !ok {\n"
        "        c.mu.Unlock()\n"
        "        return 0, false\n"
        "    }\n"
        "    c.mu.Unlock()\n"
        "    return v, true\n"
        "}\n"
    )
    assert _messages(balanced) == []


def test_open_without_close_on_error_path_is_reported() -> None:
    source = (
        "package demo\n"
        "func Read(path string) ([]byte, error) {\n"
        "    f, err := os.Open(path)\n"
        "    if err != nil {\n"
        "        return nil, err\n"
        "    }\n"
        "    data, err := io.ReadAll(f)\n"
        "    if err != nil {\n"
        "        return nil, err\n"
        "    }\n"
        "    f.Close()\n"
        "    return data, nil\n"
        "}\n"
    )
    messages = _messages(source)
    assert any("resource leak" in m for m in messages), messages


def test_deferred_close_or_returned_handle_is_not_reported() -> None:
    deferred = (
        "package demo\n"
        "func Read(path string) ([]byte, error) {\n"
        "    f, err := os.Open(path)\n"
        "    if err != nil {\n"
        "        return nil, err\n"
        "    }\n"
        "    defer f.Close()\n"
        "    data, err := io.ReadAll(f)\n"
        "    if err != nil {\n"
        "        return nil, err\n"
        "    }\n"
        "    return data, nil\n"
        "}\n"
    )
    assert _messages(deferred) == []
    returned = (
        "package demo\n"
        "func OpenLog(path string) (*os.File, error) {\n"
        "    f, err := os.Open(path)\n"
        "    if err != nil {\n"
        "        return nil, err\n"
        "    }\n"
        "    return f, nil\n"
        "}\n"
    )
    assert _messages(returned) == []


def test_dataflow_issues_are_appended_after_expression_issues() -> None:
    source = (
        "package demo\n"
        "func (c *Cache) Ratio(k string, d int) int {\n"
        "    c.mu.Lock()\n"
        "    c.mu.Lock()\n"
        "    c.mu.Unlock()\n"
        "    return c.items[k] / d\n"
        "}\n"
    )
    messages = _messages(source)
    assert len(messages) >= 2
    assert "d" in messages[0] and "deadlock" in messages[-1]


# --------------------------------------------------------------------------- #
# 8. soundness regressions (review findings)
# --------------------------------------------------------------------------- #


def test_switch_break_keeps_zero_divisor_path() -> None:
    body = (
        "d := 1\n"
        "switch mode {\n"
        "case 0:\n"
        "    d = 0\n"
        "    break\n"
        "default:\n"
        "    d = 2\n"
        "}\n"
        "return n / d\n"
    )
    facts = _facts(body, "n / d", param_names={"n", "mode"})
    assert "d" not in facts.nonzero


def test_break_inside_if_in_switch_keeps_path() -> None:
    body = (
        "d := 1\n"
        "switch {\n"
        "case mode > 0:\n"
        "    if flag {\n"
        "        d = 0\n"
        "        break\n"
        "    }\n"
        "    d = 2\n"
        "}\n"
        "return n / d\n"
    )
    facts = _facts(body, "n / d", param_names={"n", "mode", "flag"})
    assert "d" not in facts.nonzero


def test_goto_disables_analysis() -> None:
    body = "if d == 0 {\n    goto done\n}\nreturn n / d\ndone:\nreturn 0\n"
    assert dataflow_facts.analyze_function(body, "go", param_names={"n", "d"}) is None


def test_fallthrough_enters_next_case_without_its_guard() -> None:
    body = (
        "switch d {\n"
        "case 0:\n"
        "    fallthrough\n"
        "default:\n"
        "    return n / d\n"
        "}\n"
        "return 0\n"
    )
    facts = _facts(body, "n / d", param_names={"n", "d"})
    assert "d" not in facts.nonzero

    body = (
        "switch d {\n"
        "case 0:\n"
        "    return 0\n"
        "default:\n"
        "    return n / d\n"
        "}\n"
    )
    assert "d" in _facts(body, "n / d", param_names={"n", "d"}).nonzero


def test_block_local_constant_does_not_leak_to_same_named_parameter() -> None:
    body = (
        "if flag {\n"
        "    const d = 1\n"
        "    return n / d\n"
        "}\n"
        "return n / d\n"
    )
    flow = _go(body, param_names={"n", "d", "flag"})
    assert "d" not in flow.constants
    facts = flow.facts_for_expression("n / d")
    assert facts is not None
    assert "d" not in facts.nonzero and "d" not in facts.consts

    body = "if flag {\n    const d = 1\n    return n / d\n}\nreturn n / dd\n"
    facts = _facts(body, "n / dd", param_names={"n", "d", "dd", "flag"})
    assert "d" not in facts.consts


def test_signed_conversion_of_unsigned_does_not_bound_index() -> None:
    body = "i := int(u)\nif i < len(xs) {\n    return xs[i]\n}\nreturn 0\n"
    facts = _facts(
        body, "xs[i]", param_names={"u", "xs"}, nonneg_names={"u"}, sequence_names={"xs"}
    )
    assert "i" not in facts.nonneg
    assert facts.bounded_indices([("xs", "i")]) == set()

    body = "u := uint(i)\nreturn n / u\n"
    facts = _facts(body, "n / u", param_names={"n", "i"})
    assert "u" in facts.nonneg and "u" not in facts.nonzero

    body = "k := int64(3)\nreturn n / k\n"
    assert "k" in _facts(body, "n / k", param_names={"n"}).nonzero


def test_lock_without_any_unlock_is_reported() -> None:
    source = (
        "package demo\n"
        "func (c *Cache) Get(k string) int {\n"
        "    c.mu.Lock()\n"
        "    return c.items[k]\n"
        "}\n"
    )
    assert any("still held" in m for m in _messages(source))
    source = (
        "package demo\n"
        "func (c *Cache) Get(k string) int {\n"
        "    c.mu.Lock()\n"
        "    c.mu.Lock()\n"
        "    return c.items[k]\n"
        "}\n"
    )
    assert any("deadlock" in m for m in _messages(source))


def test_plain_assignment_and_pipe_handles_are_tracked() -> None:
    assigned = (
        "package demo\n"
        "func Read(path string) ([]byte, error) {\n"
        "    var f *os.File\n"
        "    var err error\n"
        "    f, err = os.Open(path)\n"
        "    if err != nil {\n"
        "        return nil, err\n"
        "    }\n"
        "    data, err := io.ReadAll(f)\n"
        "    if err != nil {\n"
        "        return nil, err\n"
        "    }\n"
        "    f.Close()\n"
        "    return data, nil\n"
        "}\n"
    )
    assert any("resource leak" in m for m in _messages(assigned))
    pipe = (
        "package demo\n"
        "func Reader() (*os.File, error) {\n"
        "    r, w, err := os.Pipe()\n"
        "    if err != nil {\n"
        "        return nil, err\n"
        "    }\n"
        "    return r, nil\n"
        "}\n"
    )
    messages = _messages(pipe)
    assert any("resource leak" in m and "w" in m for m in messages), messages
    assert not any("resource leak" in m and "'r'" in m for m in messages), messages


def test_unbounded_addition_may_overflow_and_loses_sign() -> None:
    body = "if n < 0 {\n    return 0\n}\nx := n + 1\nif x < len(xs) {\n    return xs[x]\n}\nreturn 0\n"
    facts = _facts(body, "xs[x]", param_names={"n", "xs"}, sequence_names={"xs"})
    assert "x" not in facts.nonneg
    assert facts.bounded_indices([("xs", "x")]) == set()

    body = "for i := 0; i < len(xs); i++ {\n    j := i + 1\n    if j < len(xs) {\n        return xs[j]\n    }\n}\nreturn 0\n"
    facts = _facts(body, "xs[j]", param_names={"xs"}, sequence_names={"xs"})
    assert facts.bounded_indices([("xs", "j")]) == {"j"}


def test_facts_for_expression_requires_whole_operand_match() -> None:
    body = "if d == 0 {\n    return 0\n}\nreturn n / dd\n"
    flow = _go(body, param_names={"n", "d", "dd"})
    assert flow.facts_for_expression("d") is None


def test_no_llm_path_is_deterministic() -> None:
    source = (
        "package demo\n"
        "func Avg(total, count int) int {\n"
        "    if count == 0 {\n"
        "        return 0\n"
        "    }\n"
        "    return total / count\n"
        "}\n"
    )
    assert _detect_go_safety_issues(source) == _detect_go_safety_issues(source)
