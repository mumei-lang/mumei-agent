"""Tests for Tier1-A checks: narrowing casts and unsigned subtraction underflow."""

from __future__ import annotations

import pytest

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
    assert not _sub_issues(
        "a - b",
        "Rust",
        param_types={"a": "usize"},
        unsigned_locals={"a", "b"},
        local_names={"a"},
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
