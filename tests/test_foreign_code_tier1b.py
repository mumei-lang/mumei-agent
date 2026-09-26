"""Tests for Tier1-B checks: shift bounds, sentinel -1/undefined, Go ignored errors."""

from __future__ import annotations

from agent.strategies.foreign_code_strategy_helpers import (
    _detect_safety_issues,
    _go_ignored_error_issues,
    _issues_for_expression,
    _sentinel_index_issues,
)


def _shift_issues(expr: str, label: str, **kwargs):
    return [
        issue
        for issue in _issues_for_expression("f", expr, label, **kwargs)
        if "shifts `" in issue.message
    ]


def _sentinel_issues(body: str, label: str):
    return _sentinel_index_issues("f", body, label)


def test_rust_shift_param_flags() -> None:
    issues = _shift_issues(
        "x << n", "Rust", raw_param_types={"x": "u64", "n": "u64"}
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ("n < 64",)
    assert issues[0].confidence == "high"


def test_rust_shift_right_param_flags() -> None:
    issues = _shift_issues(
        "x >> n", "Rust", raw_param_types={"x": "u32", "n": "u64"}
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ("n < 32",)


def test_rust_shift_compound_assign_flags() -> None:
    issues = _shift_issues(
        "x <<= n", "Rust", raw_param_types={"x": "u64", "n": "u64"}
    )
    assert len(issues) == 1


def test_rust_shift_literal_at_width_flags() -> None:
    issues = _shift_issues(
        "x << 64", "Rust", raw_param_types={"x": "u64"}
    )
    assert len(issues) == 1
    assert "literal" in issues[0].message


def test_rust_shift_literal_below_width_skipped() -> None:
    assert not _shift_issues(
        "x << 4", "Rust", raw_param_types={"x": "u64"}
    )


def test_rust_shift_guarded_by_comparison_skipped() -> None:
    assert not _shift_issues(
        "n < 64 ? x << n : 0",
        "Rust",
        raw_param_types={"x": "u64", "n": "u64"},
    )


def test_rust_shift_masked_amount_skipped() -> None:
    """``x << (n & 63)`` is the idiomatic bounded shift — not a bug."""
    assert not _shift_issues(
        "x << (n & 63)", "Rust", raw_param_types={"x": "u64", "n": "u64"}
    )


def test_rust_shift_mod_amount_skipped() -> None:
    assert not _shift_issues(
        "x << (n % 64)", "Rust", raw_param_types={"x": "u64", "n": "u64"}
    )


def test_rust_shift_or_short_circuit_not_guarded() -> None:
    """``n < 64 || x << n`` — the shift evaluates when the guard fails."""
    issues = _shift_issues(
        "n < 64 || x << n == 0",
        "Rust",
        raw_param_types={"x": "u64", "n": "u64"},
    )
    assert len(issues) == 1


def test_shift_unknown_base_type_skipped() -> None:
    assert not _shift_issues(
        "x << n", "Rust", raw_param_types={"x": "Vec<u8>", "n": "u64"}
    )


def test_shift_local_amount_no_contract() -> None:
    """A local shift amount can't be a caller contract — still flagged."""
    issues = _shift_issues(
        "x << n",
        "Rust",
        raw_param_types={"x": "u64"},
        local_names={"n"},
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ()
    assert issues[0].confidence == "medium"


def test_typescript_shift_flags_at_32() -> None:
    """ECMAScript shifts mask the count to 5 bits — ``x << 32`` is a no-op."""
    issues = _shift_issues("x << n", "TypeScript")
    assert len(issues) == 1
    assert "32" in issues[0].message


def test_typescript_shift_literal_32_flags() -> None:
    issues = _shift_issues("x << 32", "TypeScript")
    assert len(issues) == 1


def test_python_shift_skipped() -> None:
    """Python ints are arbitrary precision — shifts never overflow."""
    assert not _shift_issues("x << n", "Python")


def test_solidity_shift_flags() -> None:
    issues = _shift_issues(
        "x << n",
        "Solidity",
        raw_param_types={"x": "uint256", "n": "uint256"},
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ("n < 256",)


def test_detect_safety_issues_rust_shift_in_body() -> None:
    """Shifts in non-return statements are caught by the body-level scan."""
    src = "fn f(x: u64, n: u64) -> u64 { let y = x << n; y }"
    issues = _detect_safety_issues(src, "rust")
    assert any("shifts `x` by `n`" in i.message for i in issues)


def test_ts_indexof_result_used_as_index_flags() -> None:
    body = 'const i = s.indexOf("x"); return arr[i];'
    issues = _sentinel_issues(body, "TypeScript")
    assert len(issues) == 1
    assert "`i`" in issues[0].message
    assert issues[0].confidence == "medium"


def test_ts_indexof_guarded_skipped() -> None:
    body = 'const i = s.indexOf("x"); if (i < 0) return -1; return arr[i];'
    assert not _sentinel_issues(body, "TypeScript")


def test_ts_indexof_strict_neq_guard_skipped() -> None:
    body = 'const i = s.indexOf("x"); if (i !== -1) { return arr[i]; } return 0;'
    assert not _sentinel_issues(body, "TypeScript")


def test_ts_find_result_deref_flags() -> None:
    body = "const el = xs.find(x => x > 0); return el.value;"
    issues = _sentinel_issues(body, "TypeScript")
    assert len(issues) == 1
    assert "undefined" in issues[0].message


def test_ts_find_result_arithmetic_flags() -> None:
    body = "const el = xs.find(x => x > 0); return el + 1;"
    issues = _sentinel_issues(body, "TypeScript")
    assert len(issues) == 1


def test_ts_find_guarded_skipped() -> None:
    body = "const el = xs.find(x => x > 0); if (el === undefined) return 0; return el.value;"
    assert not _sentinel_issues(body, "TypeScript")


def test_ts_find_bang_guard_skipped() -> None:
    body = "const el = xs.find(x => x > 0); if (!el) return 0; return el.value;"
    assert not _sentinel_issues(body, "TypeScript")


def test_ts_find_optional_chain_skipped() -> None:
    body = "const el = xs.find(x => x > 0); return el?.value;"
    assert not _sentinel_issues(body, "TypeScript")


def test_ts_nested_indexof_in_index_flags() -> None:
    body = 'return arr[s.indexOf("x")];'
    issues = _sentinel_issues(body, "TypeScript")
    assert len(issues) == 1


def test_go_strings_index_used_as_index_flags() -> None:
    body = 'i := strings.Index(s, "x")\nreturn arr[i]'
    issues = _sentinel_issues(body, "Go")
    assert len(issues) == 1


def test_go_strings_index_guarded_skipped() -> None:
    body = 'i := strings.Index(s, "x")\nif i < 0 { return -1 }\nreturn arr[i]'
    assert not _sentinel_issues(body, "Go")


def test_py_find_used_as_index_flags() -> None:
    body = 'i = s.find("x")\nreturn s[i]'
    issues = _sentinel_issues(body, "Python")
    assert len(issues) == 1


def test_py_find_guarded_skipped() -> None:
    body = 'i = s.find("x")\nif i == -1:\n    return -1\nreturn s[i]'
    assert not _sentinel_issues(body, "Python")


def test_go_discard_error_flags() -> None:
    body = "x, _ := g()\nreturn x"
    issues = _go_ignored_error_issues("f", body, {"g"})
    assert len(issues) == 1
    assert "discard" in issues[0].message or "discard" in issues[0].message


def test_go_bare_error_call_flags() -> None:
    body = "g()"
    issues = _go_ignored_error_issues("f", body, {"g"})
    assert len(issues) == 1
    assert "ignores" in issues[0].message


def test_go_bound_error_not_flagged() -> None:
    body = "x, err := g()\nif err != nil { return -1 }\nreturn x"
    assert not _go_ignored_error_issues("f", body, {"g"})


def test_go_non_error_callee_not_flagged() -> None:
    """A callee that does not return error must not flag."""
    body = "x, _ := g()\nreturn x"
    assert not _go_ignored_error_issues("f", body, set())


def test_go_method_error_flags() -> None:
    body = "r.Close()"
    issues = _go_ignored_error_issues("f", body, {"Close"})
    assert len(issues) == 1


def test_detect_safety_issues_go_ignored_error_wiring() -> None:
    """Same-file signatures must drive the ignored-error check."""
    src = (
        "package p\n"
        "func g() (int, error) { return 0, nil }\n"
        "func f() int { x, _ := g(); return x }\n"
    )
    issues = _detect_safety_issues(src, "go")
    assert any("discards the error return" in i.message for i in issues)


def test_detect_safety_issues_go_bare_error_wiring() -> None:
    src = (
        "package p\n"
        "func g() error { return nil }\n"
        "func f() { g() }\n"
    )
    issues = _detect_safety_issues(src, "go")
    assert any("ignores the error return" in i.message for i in issues)


def test_detect_safety_issues_ts_indexof_wiring() -> None:
    src = (
        "function f(s: string, arr: number[]): number {"
        ' const i = s.indexOf("x"); return arr[i]; }'
    )
    issues = _detect_safety_issues(src, "typescript")
    assert any("sentinel" in i.message for i in issues)


def test_detect_safety_issues_py_find_wiring() -> None:
    src = 'def f(s):\n    i = s.find("x")\n    return s[i]\n'
    issues = _detect_safety_issues(src, "python")
    assert any("sentinel" in i.message for i in issues)


def test_shift_early_exit_on_safe_bound_not_guarded() -> None:
    """``if n < 64 { return } x << n`` exits on the SAFE direction — only
    ``n >= 64`` reaches the shift, so it must still flag."""
    issues = _shift_issues(
        "if n < 64 { return 0 } x << n",
        "Rust",
        raw_param_types={"x": "u64", "n": "u64"},
    )
    assert len(issues) == 1


def test_shift_early_exit_on_bad_bound_guarded() -> None:
    """``if n >= 64 { return } x << n`` exits on the BAD direction — only
    ``n < 64`` reaches the shift."""
    assert not _shift_issues(
        "if n >= 64 { return 0 } x << n",
        "Rust",
        raw_param_types={"x": "u64", "n": "u64"},
    )


def test_shift_signed_amount_adds_lower_bound_contract() -> None:
    """A signed shift count needs ``n >= 0`` in addition to ``n < W`` —
    ``n < 64`` is satisfied by ``n == -1``, still a panic."""
    issues = _shift_issues(
        "x << n", "Rust", raw_param_types={"x": "u64", "n": "i32"}
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ("n >= 0", "n < 64")


def test_shift_unsigned_amount_upper_bound_only() -> None:
    issues = _shift_issues(
        "x << n", "Rust", raw_param_types={"x": "u64", "n": "u64"}
    )
    assert issues[0].required_contracts == ("n < 64",)


def test_shift_parenthesized_mask_skipped() -> None:
    assert not _shift_issues(
        "x << (n & 63)", "Rust", raw_param_types={"x": "u64", "n": "u64"}
    )
    assert not _shift_issues(
        "x << (n % 64)", "Rust", raw_param_types={"x": "u64", "n": "u64"}
    )


def test_shift_parenthesized_unproven_amount_advisory() -> None:
    issues = _shift_issues(
        "x << (n + 1)", "Rust", raw_param_types={"x": "u64", "n": "u64"}
    )
    assert len(issues) == 1
    assert issues[0].confidence == "medium"


def test_ts_indexof_closed_guard_block_does_not_reach_use() -> None:
    """``if (i !== -1) { … } arr[i]`` — the check's block closed before the
    use; it does not dominate it."""
    body = 'const i = s.indexOf("x"); if (i !== -1) { let y = i; } return arr[i];'
    issues = _sentinel_issues(body, "TypeScript")
    assert len(issues) == 1


def test_ts_indexof_early_exit_on_sentinel_guarded() -> None:
    body = 'const i = s.indexOf("x"); if (i === -1) { return 0; } return arr[i];'
    assert not _sentinel_issues(body, "TypeScript")


def test_ts_indexof_shortcircuit_guarded() -> None:
    body = 'const i = s.indexOf("x"); return i !== -1 ? arr[i] : 0;'
    assert not _sentinel_issues(body, "TypeScript")


def test_ts_find_falsy_early_exit_guarded() -> None:
    body = "const el = xs.find(x => x > 0); if (!el) { return 0; } return el.value;"
    assert not _sentinel_issues(body, "TypeScript")


def test_ts_find_closed_neq_block_not_guarded() -> None:
    body = (
        "const el = xs.find(x => x > 0); "
        "if (el !== undefined) { let y = el; } return el.value;"
    )
    issues = _sentinel_issues(body, "TypeScript")
    assert len(issues) == 1


def test_python_find_colon_early_exit_guarded() -> None:
    body = 'i = s.find("x")\nif i < 0:\n    return -1\nreturn arr[i]'
    assert not _sentinel_issues(body, "Python")


def test_python_find_colon_non_diverging_not_guarded() -> None:
    body = 'i = s.find("x")\nif i < 0:\n    x = 1\nreturn arr[i]'
    issues = _sentinel_issues(body, "Python")
    assert len(issues) == 1


def test_python_find_assert_guarded() -> None:
    body = 'i = s.find("x")\nassert i != -1\nreturn arr[i]'
    assert not _sentinel_issues(body, "Python")
