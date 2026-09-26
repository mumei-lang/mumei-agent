"""Tests for Tier1-A checks: narrowing casts and unsigned subtraction underflow."""

from __future__ import annotations

from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression


def _cast_issues(expr: str, label: str, **kwargs):
    return [
        issue
        for issue in _issues_for_expression("f", expr, label, **kwargs)
        if "can truncate" in issue.message
    ]


def _sub_issues(expr: str, label: str, **kwargs):
    return [
        issue
        for issue in _issues_for_expression("f", expr, label, **kwargs)
        if "can underflow" in issue.message
    ]


def test_rust_narrowing_cast_flags_wider_unsigned_param() -> None:
    issues = _cast_issues(
        "x as u8", "Rust", param_types={"x": "u64"}
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ("x <= 255",)
    assert issues[0].counterexample and issues[0].counterexample["x"] > 255


def test_rust_widening_cast_not_flagged() -> None:
    assert not _cast_issues("x as u64", "Rust", param_types={"x": "u32"})


def test_rust_unsigned_to_wider_signed_not_flagged() -> None:
    # u32 -> i64 is always lossless.
    assert not _cast_issues("x as i64", "Rust", param_types={"x": "u32"})


def test_rust_signed_operand_gets_lower_bound_contract() -> None:
    issues = _cast_issues("x as u8", "Rust", param_types={"x": "i64"})
    assert len(issues) == 1
    assert issues[0].required_contracts == ("x >= 0", "x <= 255")


def test_rust_cast_unknown_type_skipped() -> None:
    # Locals / untyped operands carry no declared type — skip rather than guess.
    assert not _cast_issues("x as u8", "Rust", param_types={"x": "Vec<u32>"})
    assert not _cast_issues("x as u8", "Rust", param_types=None)


def test_rust_cast_local_name_skipped() -> None:
    assert not _cast_issues(
        "x as u8",
        "Rust",
        param_types={"x": "u64"},
        local_names={"x"},
    )


def test_rust_cast_known_constant_in_range_skipped() -> None:
    assert not _cast_issues("N as u8", "Rust", known_constants={"N": 200})


def test_rust_cast_known_constant_out_of_range_flagged() -> None:
    issues = _cast_issues("N as u8", "Rust", known_constants={"N": 300})
    assert len(issues) == 1


def test_go_narrowing_conversion_flags_wider_param() -> None:
    issues = _cast_issues("uint8(n)", "Go", param_types={"n": "int64"})
    assert len(issues) == 1
    assert "n >= 0" in issues[0].required_contracts
    assert "n <= 255" in issues[0].required_contracts


def test_go_same_width_conversion_not_flagged() -> None:
    assert not _cast_issues("int64(n)", "Go", param_types={"n": "int64"})


def test_go_signed_to_unsigned_same_width_flagged() -> None:
    issues = _cast_issues("uint64(n)", "Go", param_types={"n": "int64"})
    assert len(issues) == 1
    assert "n >= 0" in issues[0].required_contracts


def test_solidity_pre08_narrowing_flagged() -> None:
    issues = _cast_issues(
        "uint128(x)", "Solidity", param_types={"x": "uint256"}
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == (f"x <= {2**128 - 1}",)


def test_solidity_checked_arithmetic_skips_casts() -> None:
    # Solidity >=0.8 explicit conversions revert — not a silent truncation.
    assert not _cast_issues(
        "uint128(x)",
        "Solidity",
        param_types={"x": "uint256"},
        solidity_default_checks=True,
    )


def test_unsigned_subtraction_flags_two_unsigned_rust_params() -> None:
    issues = _sub_issues(
        "a - b", "Rust", param_types={"a": "usize", "b": "usize"}
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ("a >= b",)


def test_unsigned_subtraction_flags_unsigned_locals() -> None:
    issues = _sub_issues(
        "a - b", "Rust", unsigned_locals={"a", "b"}
    )
    assert len(issues) == 1


def test_unsigned_subtraction_signed_params_not_flagged() -> None:
    assert not _sub_issues(
        "a - b", "Rust", param_types={"a": "i64", "b": "i64"}
    )


def test_unsigned_subtraction_guarded_by_comparison_not_flagged() -> None:
    assert not _sub_issues(
        "a >= b ? a - b : b - a",
        "Rust",
        param_types={"a": "u64", "b": "u64"},
    )


def test_unsigned_subtraction_local_names_skipped() -> None:
    """Locals whose unsignedness is body-derived (``unsigned_locals``) are
    still flagged — underflow is a real bug regardless of contract ability.
    Only *unproven* locals are skipped."""
    issues = _sub_issues(
        "a - b",
        "Rust",
        param_types={"a": "usize"},
        unsigned_locals={"a", "b"},
        local_names={"a"},
    )
    assert len(issues) == 1
    # A name in local_names but NOT in unsigned_locals is a shadowed param —
    # its param_types entry describes the wrong binding, so it must be skipped.
    assert not _sub_issues(
        "a - b",
        "Rust",
        param_types={"a": "usize", "b": "usize"},
        local_names={"a", "b"},
    )


def test_unsigned_subtraction_constant_rhs_zero_skipped() -> None:
    assert not _sub_issues(
        "a - ZERO",
        "Rust",
        unsigned_locals={"a"},
        known_constants={"ZERO": 0},
    )


def test_unsigned_subtraction_constant_pair_safe_skipped() -> None:
    assert not _sub_issues(
        "A - B",
        "Rust",
        known_constants={"A": 10, "B": 3},
    )


def test_go_unsigned_subtraction_flagged() -> None:
    issues = _sub_issues(
        "a - b", "Go", param_types={"a": "uint64", "b": "uint64"}
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ("a >= b",)


def test_solidity_pre08_unsigned_subtraction_flagged() -> None:
    issues = _sub_issues(
        "a - b", "Solidity", param_types={"a": "uint256", "b": "uint256"}
    )
    assert len(issues) == 1


def test_solidity_checked_arithmetic_skips_subtraction() -> None:
    assert not _sub_issues(
        "a - b",
        "Solidity",
        param_types={"a": "uint256", "b": "uint256"},
        solidity_default_checks=True,
    )


def test_python_not_affected() -> None:
    assert not _cast_issues("x", "Python")
    assert not _sub_issues("a - b", "Python")


def test_solidity_detect_safety_issues_wires_param_types() -> None:
    """``_detect_safety_issues`` must route declared param types so cast and
    underflow checks fire on real sources (not only direct calls)."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    src = (
        "pragma solidity ^0.7.6;\n"
        "contract C {\n"
        "  function f(uint256 a, uint256 b) public pure returns (uint256) {\n"
        "    return a - b;\n"
        "  }\n"
        "  function g(uint256 x) public pure returns (uint128) {\n"
        "    return uint128(x);\n"
        "  }\n"
        "}\n"
    )
    issues = _detect_safety_issues(src, "solidity")
    assert any("can underflow `a - b`" in i.message for i in issues)
    assert any("can truncate `x` in cast to `uint128`" in i.message for i in issues)


def test_go_rune_conversion_flags_wider_param() -> None:
    issues = _cast_issues("rune(n)", "Go", param_types={"n": "int64"})
    assert len(issues) == 1
    assert "n <= 2147483647" in issues[0].required_contracts


def test_signed_to_same_width_unsigned_no_vacuous_upper_bound() -> None:
    issues = _cast_issues("x as u64", "Rust", param_types={"x": "i64"})
    assert len(issues) == 1
    assert issues[0].required_contracts == ("x >= 0",)


def test_unsigned_subtraction_shadowed_param_not_flagged() -> None:
    """A local shadowing a param name must not inherit the param's type."""
    assert not _sub_issues(
        "a - b",
        "Rust",
        param_types={"a": "usize", "b": "usize"},
        local_names={"a"},
    )


def test_unsigned_subtraction_left_less_than_right_guard_not_suppressed() -> None:
    """``a <= b`` proves underflow, not safety — must still flag."""
    issues = _sub_issues(
        "a <= b ? a - b : 0",
        "Rust",
        param_types={"a": "u64", "b": "u64"},
    )
    assert len(issues) == 1


def test_unsigned_subtraction_self_skipped() -> None:
    """``a - a`` is always 0 — never underflows."""
    assert not _sub_issues("a - a", "Rust", param_types={"a": "usize"})


def test_unsigned_subtraction_compound_assign_flagged() -> None:
    issues = _sub_issues(
        "a -= b", "Rust", param_types={"a": "u64", "b": "u64"}
    )
    assert len(issues) == 1
    assert issues[0].required_contracts == ("a >= b",)


def test_unsigned_subtraction_or_short_circuit_not_guarded() -> None:
    """``a >= b || a - b`` evaluates the subtraction only when ``a < b`` —
    the comparison does not guard the right-hand side."""
    issues = _sub_issues(
        "a >= b || a - b > 0",
        "Rust",
        param_types={"a": "u64", "b": "u64"},
    )
    assert len(issues) == 1


def test_unsigned_subtraction_and_guard_suppresses() -> None:
    """``a >= b && a - b`` evaluates the subtraction only when ``a >= b``."""
    assert not _sub_issues(
        "a >= b && a - b > 0",
        "Rust",
        param_types={"a": "u64", "b": "u64"},
    )


def test_unsigned_subtraction_ternary_both_branches_guarded() -> None:
    """``a >= b ? a - b : b - a`` — both operands guarded by the condition."""
    assert not _sub_issues(
        "a >= b ? a - b : b - a",
        "Rust",
        param_types={"a": "u64", "b": "u64"},
    )


def test_detect_safety_issues_rust_raw_param_types() -> None:
    """Rust param types must reach the cast check in *declared* width form —
    the normalized ``u64`` map would misjudge same-width/narrowing casts."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    # u8 -> u8 is same-width: no flag. If the normalized ``u64`` map were
    # consulted this would report a spurious u64 -> u8 truncation.
    assert not any(
        "can truncate" in i.message
        for i in _detect_safety_issues("fn f(x: u8) -> u8 { x as u8 }", "rust")
    )
    # u8 -> u32 is widening: no flag.
    assert not any(
        "can truncate" in i.message
        for i in _detect_safety_issues("fn f(x: u8) -> u32 { x as u32 }", "rust")
    )
    # u64 -> u8 narrows: flag.
    assert any(
        "can truncate" in i.message
        for i in _detect_safety_issues("fn f(x: u64) -> u8 { x as u8 }", "rust")
    )


def test_detect_safety_issues_rust_non_return_subtraction() -> None:
    """Subtractions in non-return statements are scanned too."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    assert any(
        "can underflow `a - b`" in i.message
        for i in _detect_safety_issues(
            "fn f(a: usize, b: usize) -> usize { let c = a - b; c }", "rust"
        )
    )


def test_detect_safety_issues_rust_if_guard_suppresses() -> None:
    """An enclosing ``if a >= b`` suppresses the mid-body subtraction."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    assert not any(
        "can underflow" in i.message
        for i in _detect_safety_issues(
            "fn f(a: usize, b: usize) -> usize { if a >= b { return a - b; } 0 }",
            "rust",
        )
    )


def test_solidity_unchecked_block_flags_under_checked_pragma() -> None:
    """``unchecked { … }`` reverts arithmetic to wrapping — flag it."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    src = (
        "pragma solidity ^0.8.20;\n"
        "contract C {\n"
        "  function f(uint256 a, uint256 b) public returns (uint256) {\n"
        "    unchecked { return a - b; }\n"
        "  }\n"
        "}\n"
    )
    assert any(
        "can underflow `a - b`" in i.message
        for i in _detect_safety_issues(src, "solidity")
    )


def test_cast_counterexample_respects_declared_source_range() -> None:
    """The Z3 counterexample must stay inside the operand's declared range —
    ``u64 -> i8`` must not print an impossible negative witness."""
    issues = _cast_issues("x as i8", "Rust", param_types={"x": "u64"})
    assert len(issues) == 1
    assert issues[0].counterexample
    assert issues[0].counterexample["x"] >= 0

