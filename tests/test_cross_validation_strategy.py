"""Tests for agent.strategies.cross_validation_strategy."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

from agent.strategies.cross_validation_strategy import (
    CrossValidationReport,
    CrossValidator,
    DriftReport,
    _extract_function_body,
    _extract_functions,
    _extract_spec_atoms,
)


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

SAMPLE_SPEC = """\
atom safe_add(a: i64, b: i64) -> i64
  requires: a >= 0 && b >= 0 && a + b <= 9223372036854775807
  ensures: result == a + b
{
  a + b
}

atom validate_balance(amount: i64) -> bool
  requires: amount > 0 && amount < 1000000
  ensures: result == true
{
  amount > 0
}
"""

SAMPLE_RUST_IMPL = """\
pub fn safe_add(a: i64, b: i64) -> i64 {
    assert!(a >= 0 && b >= 0);
    a.checked_add(b).expect("overflow")
}

pub fn validate_balance(amount: i64) -> bool {
    amount > 0 && amount < 1_000_000
}

pub fn internal_helper() -> () {
    // not in spec
}
"""

SAMPLE_PYTHON_IMPL = """\
def safe_add(a: int, b: int) -> int:
    assert a >= 0 and b >= 0
    return a + b

def validate_balance(amount: int) -> bool:
    return amount > 0 and amount < 1_000_000
"""

SAMPLE_TS_IMPL = """\
export function safe_add(a: number, b: number): number {
    if (a < 0 || b < 0) throw new Error("negative");
    return a + b;
}

export const validate_balance = (amount: number): boolean => {
    return amount > 0 && amount < 1_000_000;
};
"""


# ---------------------------------------------------------------------------
# Tests: _extract_functions
# ---------------------------------------------------------------------------

class TestExtractFunctions:
    def test_rust(self):
        names = _extract_functions(SAMPLE_RUST_IMPL, "rust")
        assert "safe_add" in names
        assert "validate_balance" in names
        assert "internal_helper" in names

    def test_python(self):
        names = _extract_functions(SAMPLE_PYTHON_IMPL, "python")
        assert "safe_add" in names
        assert "validate_balance" in names

    def test_typescript(self):
        names = _extract_functions(SAMPLE_TS_IMPL, "typescript")
        assert "safe_add" in names
        assert "validate_balance" in names

    def test_typescript_arrow_with_type_annotation(self):
        # `const name: Type = async (...)` must still be extracted (#280).
        src = (
            "export const timingSafeEqual: TimingSafeEqual = async (\n"
            "  a,\n  b,\n) => {\n  return a === b;\n}\n"
        )
        names = _extract_functions(src, "typescript")
        assert "timingSafeEqual" in names

    def test_typescript_arrow_body_with_type_annotation(self):
        # The body of a typed arrow must also be extractable so the
        # semantic-gap check isn't silently skipped (#280).
        src = (
            "export const timingSafeEqual: TimingSafeEqual = async (\n"
            "  a,\n  b,\n) => {\n  return a === b;\n}\n"
        )
        body = _extract_function_body(src, "typescript", "timingSafeEqual")
        assert "return a === b" in body


# ---------------------------------------------------------------------------
# Tests: _extract_spec_atoms
# ---------------------------------------------------------------------------

class TestExtractSpecAtoms:
    def test_extracts_atoms(self):
        atoms = _extract_spec_atoms(SAMPLE_SPEC)
        assert len(atoms) == 2
        names = [a["name"] for a in atoms]
        assert "safe_add" in names
        assert "validate_balance" in names

    def test_atom_has_requires(self):
        atoms = _extract_spec_atoms(SAMPLE_SPEC)
        add_atom = next(a for a in atoms if a["name"] == "safe_add")
        assert "a >= 0" in add_atom["requires"]


# ---------------------------------------------------------------------------
# Tests: CrossValidator.validate_spec_vs_impl
# ---------------------------------------------------------------------------

class TestValidateSpecVsImpl:
    def setup_method(self):
        self.validator = CrossValidator()
        self.tmpdir = tempfile.mkdtemp()
        self.spec_path = Path(self.tmpdir) / "spec.mm"
        self.spec_path.write_text(SAMPLE_SPEC)

    def test_full_coverage_rust(self):
        impl_path = Path(self.tmpdir) / "lib.rs"
        impl_path.write_text(SAMPLE_RUST_IMPL)
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(self.spec_path),
            impl_path=str(impl_path),
            language="rust",
        )
        assert isinstance(report, CrossValidationReport)
        # Both atoms are implemented
        assert report.coverage_ratio > 0.0
        assert "safe_add" not in report.uncovered_atoms
        assert "validate_balance" not in report.uncovered_atoms

    def test_uncovered_atom(self):
        impl_path = Path(self.tmpdir) / "lib.rs"
        # Only implement safe_add
        impl_path.write_text("pub fn safe_add(a: i64, b: i64) -> i64 { a + b }\n")
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(self.spec_path),
            impl_path=str(impl_path),
            language="rust",
        )
        assert "validate_balance" in report.uncovered_atoms
        assert report.coverage_ratio == 0.5

    def test_missing_spec_file(self):
        report = self.validator.validate_spec_vs_impl(
            spec_path="/nonexistent/spec.mm",
            impl_path="/nonexistent/impl.rs",
            language="rust",
        )
        assert report.details  # Should have error detail

    def test_python_impl(self):
        impl_path = Path(self.tmpdir) / "lib.py"
        impl_path.write_text(SAMPLE_PYTHON_IMPL)
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(self.spec_path),
            impl_path=str(impl_path),
            language="python",
        )
        assert report.coverage_ratio == 1.0

    def test_matching_is_normalization_tolerant(self):
        # Spec atoms use snake_case; Go impl uses CamelCase. These must match
        # instead of being reported as uncovered (#280).
        spec = (
            "atom bytes2hex(d: Bytes) -> String\n"
            "  requires: true\n  ensures: true\n{\n  d\n}\n\n"
            "atom check_arg_length(n: i64) -> bool\n"
            "  requires: true\n  ensures: true\n{\n  n > 0\n}\n"
        )
        spec_path = Path(self.tmpdir) / "norm.mm"
        spec_path.write_text(spec)
        impl_path = Path(self.tmpdir) / "impl.go"
        impl_path.write_text(
            "package demo\n"
            "func Bytes2Hex(d []byte) string { return \"\" }\n"
            "func _checkArgLength(n int) bool { return n > 0 }\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path),
            impl_path=str(impl_path),
            language="go",
        )
        assert report.uncovered_atoms == []
        assert report.coverage_ratio == 1.0

    def test_no_false_positive_spec_stronger_for_native_wrappers(self):
        """Short call-forwarding bodies should not trigger spec-stronger-than-impl."""
        from agent.strategies.cross_validation_strategy import _is_short_native_or_wrapper_body

        assert _is_short_native_or_wrapper_body("return subtle.ConstantTimeCompare(x, y)")
        assert not _is_short_native_or_wrapper_body("if x > 0 { return 1 } else { return 0 }")

        spec = (
            "atom ConstantTimeCompare(x: i64, y: i64) -> i64\n"
            "  requires: x >= 0 && y >= 0\n"
            "  ensures: result == 1 || result == 0\n"
            "{\n  0\n}\n"
        )
        spec_path = Path(self.tmpdir) / "const.mm"
        spec_path.write_text(spec)
        impl_path = Path(self.tmpdir) / "impl.go"
        impl_path.write_text(
            "package subtle\n"
            "func ConstantTimeCompare(x, y []byte) int {\n"
            "    return constanttime.Compare(x, y)\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path),
            impl_path=str(impl_path),
            language="go",
        )
        assert "ConstantTimeCompare" not in report.spec_stronger_than_impl

    def test_check_impl_coverage_normalization_tolerant(self):
        result = self.validator.check_impl_coverage(
            ["bytes2hex", "check_arg_length"],
            ["Bytes2Hex", "_checkArgLength"],
        )
        assert result["uncovered"] == []
        assert result["ratio"] == 1.0

    def _write_spec(self, name: str, requires: str) -> Path:
        spec = (
            f"atom {name}(balance: i64, amount: i64) -> i64\n"
            f"  requires: {requires}\n"
            "  ensures: result == balance - amount\n"
            "{\n  0\n}\n"
        )
        spec_path = Path(self.tmpdir) / f"{name}.mm"
        spec_path.write_text(spec)
        return spec_path

    def test_unenforced_precondition_is_flagged(self):
        """A requires conjured by spec extraction (no matching guard in the
        source) must surface as a spec-vs-impl gap — otherwise the audit
        verifies the buggy code vacuously (mumei-agent#1325)."""
        spec_path = self._write_spec(
            "withdraw", "balance >= 0 && amount >= 0 && amount <= balance"
        )
        impl_path = Path(self.tmpdir) / "buggy.py"
        impl_path.write_text(
            "def withdraw(balance: int, amount: int) -> int:\n"
            '    """Withdraw amount from balance."""\n'
            "    if amount <= 0:\n"
            "        raise ValueError('amount must be positive')\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl
        assert any("not enforced" in detail for detail in report.details)

    def test_enforced_precondition_is_not_flagged(self):
        spec_path = self._write_spec(
            "withdraw", "amount > 0 && amount <= balance"
        )
        impl_path = Path(self.tmpdir) / "good.py"
        impl_path.write_text(
            "def withdraw(balance: int, amount: int) -> int:\n"
            "    if amount <= 0:\n"
            "        raise ValueError('amount must be positive')\n"
            "    if balance < amount:\n"
            "        raise ValueError('insufficient funds')\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_trivial_requires_is_not_flagged(self):
        spec_path = self._write_spec("withdraw", "true")
        impl_path = Path(self.tmpdir) / "any.py"
        impl_path.write_text(
            "def withdraw(balance: int, amount: int) -> int:\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_docstring_and_comment_do_not_count_as_guards(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "commented.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    """Should fail if amount > balance."""\n'
            "    return balance - amount  # check: amount <= balance\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_call_forwarding_body_is_not_flagged(self):
        """A body that forwards to a callee may delegate enforcement — the
        file-local check cannot see the callee, so it stays silent."""
        spec_path = self._write_spec("compare", "x >= 0 && y >= 0")
        spec_path.write_text(
            "atom compare(x: i64, y: i64) -> i64\n"
            "  requires: x >= 0 && y >= 0\n"
            "  ensures: result == 1 || result == 0\n"
            "{\n  0\n}\n"
        )
        impl_path = Path(self.tmpdir) / "wrap.go"
        impl_path.write_text(
            "package subtle\n"
            "func compare(x, y []byte) int {\n"
            "    return constanttime.Compare(x, y)\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="go"
        )
        assert "compare" not in report.spec_stronger_than_impl

    def test_computed_return_is_not_a_call_forward(self):
        """`return round(balance - amount, 2)` computes — it does not delegate
        the balance check to `round`."""
        spec_path = self._write_spec("withdraw", "amount > 0 && amount <= balance")
        impl_path = Path(self.tmpdir) / "rounded.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    if amount <= 0:\n"
            "        raise ValueError('amount must be positive')\n"
            "    return round(balance - amount, 2)\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_non_validation_call_does_not_count_as_guard(self):
        """`print(balance, amount)` touches the identifiers without
        enforcing anything."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "noisy.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    print(balance, amount)\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_multiline_guard_is_detected(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "multiline.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    if (\n"
            "        balance < amount\n"
            "    ):\n"
            "        raise ValueError('insufficient funds')\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_python_floor_division_is_not_a_comment(self):
        """`//` must not be stripped as a comment in Python bodies. The guard
        uses the spec's own bound (amount <= balance) written through `//` so
        the test fails if `//` truncates the line."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "floordiv.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    if amount // 1 > balance:\n"
            "        raise ValueError('over limit')\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_go_brace_does_not_merge_condition_with_block_body(self):
        """Go `if amount <= 0 { return -1 }` guards only `amount`; the block's
        `return balance` must not be merged into the condition line."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "w.go"
        impl_path.write_text(
            "func withdraw(balance int, amount int) int {\n"
            "\tif amount <= 0 {\n"
            "\t\treturn -1\n"
            "\t}\n"
            "\treturn balance - amount\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="go"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_comment_markers_inside_strings_are_not_comments(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "w.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  const tag = \"/api/*\";\n"
            "  if (amount > balance) { throw new Error('over'); }\n"
            "  return balance - amount;\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_keyword_arg_forward_is_pure_delegation(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "kw.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    return ledger.apply(balance=balance, amount=amount)\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_local_class_does_not_truncate_body(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "localclass.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    class InsufficientFunds(Exception):\n"
            "        pass\n"
            "    if balance < amount:\n"
            "        raise InsufficientFunds()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_async_def_body_is_extracted(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "a.py"
        impl_path.write_text(
            "async def withdraw(balance, amount):\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_uncalled_nested_function_does_not_enforce(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "n.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    def check():\n"
            "        if balance < amount:\n"
            "            raise ValueError()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_called_nested_function_enforces(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "n2.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    def check():\n"
            "        if balance < amount:\n"
            "            raise ValueError()\n"
            "    check()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_column_zero_comment_does_not_truncate_body(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "c.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    x = 1\n"
            "# a comment at column zero\n"
            "    if balance < amount:\n"
            "        raise ValueError()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_assignment_in_call_is_not_a_forward(self):
        """`save(state.balance = nextBalance)` mutates; it is not a keyword
        argument and must not exempt the body. The RHS is a lone identifier
        so the test fails if `=` args are wrongly read as kwarg forwards."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "a.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  const nextBalance = balance - amount;\n"
            "  return save(state.balance = nextBalance);\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_fstring_message_does_not_count_as_enforcement(self):
        """`raise ValueError(f"{amount} > {balance}")` interpolates both
        identifiers without checking them — masking must not surface the
        message's variables."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "fs.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    if amount <= 0:\n"
            '        raise ValueError(f"{amount} exceeds {balance}")\n'
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_transitively_called_nested_function_enforces(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "t.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    def check():\n"
            "        if balance < amount:\n"
            "            raise ValueError()\n"
            "    def mid():\n"
            "        check()\n"
            "    mid()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_one_line_nested_def_enforces_when_called(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "o.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    def check(): assert balance >= amount\n"
            "    check()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_method_call_does_not_pull_nested_function(self):
        """`self.check()` calls a method, not a nested `def check` — the
        nested block's guard lines must not count."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "m.py"
        impl_path.write_text(
            "class A:\n"
            "    def withdraw(self, balance, amount):\n"
            "        def check():\n"
            "            if balance < amount:\n"
            "                raise ValueError()\n"
            "        self.check()\n"
            "        return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        # self.check() passes no arguments, so it cannot be the delegated
        # check for {amount, balance} either — the precondition is
        # genuinely unenforced.
        assert "withdraw" in report.spec_stronger_than_impl

    def test_nested_return_does_not_exempt_outer_body(self):
        """A called one-line helper containing `return f(x)` must not make
        the outer function look like a pure call-forward."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "n.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    def helper(): return round(amount)\n"
            "    helper()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_annotated_one_line_nested_def_uses_real_body(self):
        """`def check(amount: int, balance: int):` must split at `):` — the
        annotation's identifier list is not a guard. The helper is called
        without the identifiers so the delegation channel stays out of the
        way and only the tail split decides coverage."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "an.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    def check(amount: int = 1, balance: int = 0): assert amount > 0\n"
            "    check()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_conditional_line_keeps_interpolated_variables(self):
        """An f-string inside an `if` condition may interpolate the checked
        identifier — masking must keep it visible on that line."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "c.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    if amount > int(f"{balance}"):\n'
            "        raise ValueError()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_assert_message_variables_do_not_count(self):
        """`assert cond, f"...{balance}..."` only checks `cond` — the
        message's identifiers are not enforcement."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "am.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    assert amount > 0, f"{balance} too low for {amount}"\n'
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_escaped_braces_are_not_interpolation(self):
        """`f"{{balance}}"` renders literal text — `balance` is not
        referenced and must not count as checked."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "eb.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    if amount > 0: assert f"{{balance}}" != ""\n'
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_format_specifier_hash_is_not_a_comment(self):
        """`f"{limit:#x}"` inside a condition must survive — the `#` is a
        format flag, not a comment opener. `balance` sits *after* the `#`,
        so this fails if the spec chars eat the rest of the line."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "fh.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    if int(f"{amount:#x}", 16) <= balance:\n'
            "        return balance - amount\n"
            "    raise ValueError()\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_annotated_nested_def_with_dict_body(self):
        """`def check() -> int: assert ...; d = {"a": 1}` — a last-colon
        split would clip at the dict's colon and drop the assert."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ad.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    def check() -> int: assert balance >= amount; d = {"a": 1}\n'
            "    check()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_multiline_assert_message_is_dropped(self):
        """A parenthesised f-string message on continuation lines is still
        a message — only the condition contributes identifiers."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ma.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    assert amount > 0, (\n"
            '        f"{balance} too low"\n'
            "    )\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_multiline_assert_condition_is_joined(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "mc.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    assert (\n"
            "        amount > 0 and\n"
            "        balance >= amount\n"
            "    )\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_braced_interpolation_is_seen(self):
        """`f"{{{name}}}"` is a literal brace around a real interpolation —
        `name` must still count as referenced."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "bi.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    if len(f"{{{balance}}}") > 0 and amount > 0:\n'
            "        return balance - amount\n"
            "    raise ValueError()\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_template_literal_braces_are_not_interpolation(self):
        """`` `{{{balance}}}` `` in TypeScript is literal text — only
        ``${...}`` interpolates."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "t.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`{{{balance}}}`.length > 0 && amount > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_template_interpolation_is_seen(self):
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ti.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${balance}`.length > 0 && amount > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_assert_message_parens_do_not_swallow_next_line(self):
        """`f"{fmt(balance)}"` inside an assert message must not make the
        following statement join the assert line."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ap.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    assert amount > 0, f"bad {fmt(balance)}"\n'
            "    assert balance >= amount\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_unterminated_quote_with_escapes_terminates(self):
        """A comment holding an unclosed quote followed by escapes must not
        stall the string masker. The run is long enough that the previous
        backtracking pattern would take centuries here — a regression makes
        the suite hang (CI timeout) rather than pass unnoticed."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "u.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    if balance < amount:  # don't " + "\\\\" * 400 + "\n"
            "        raise ValueError()\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_assert_interpolation_comma_is_not_message_separator(self):
        """`assert f"{fmt(amount, balance)}", f"{other}"` — the first comma
        sits inside the interpolation; the real separator is the second.
        Without comma blanking the condition loses `balance`."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ic.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    assert f"{fmt(amount, balance)}", f"{other}"\n'
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_object_literal_key_is_not_a_variable_read(self):
        """`${{ balance: 1, amount }}` — `balance` appears only as an
        object-literal key, so the guard does not enforce the clause."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "tk.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${{ balance: 1, amount }}`.length > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_object_literal_value_is_a_variable_read(self):
        """`${{ k: balance }}` reads `balance` — only the *key* position
        is stripped."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "tv.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${{ k: balance, amount }}`.length > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_fstring_dynamic_width_keeps_variable(self):
        """`f"{balance:{width}}"` reads `width` — a dynamic format spec's
        nested interpolation is still a reference."""
        spec_path = self._write_spec("withdraw", "width <= balance")
        impl_path = Path(self.tmpdir) / "dw.py"
        impl_path.write_text(
            "def withdraw(balance, amount, width):\n"
            '    assert len(f"{balance:{width}}") > 0\n'
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_escaped_dollar_is_literal(self):
        r"""`\${amount}` is literal text in a template — it reads neither
        `amount` nor anything else."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "te.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`\\${ amount, balance }`.length > 0 && amount > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_ternary_value_in_object_keeps_branch(self):
        """`${{ k: cond ? allowed : false }}` — `allowed` is a ternary
        branch value, not an object key."""
        spec_path = self._write_spec("withdraw", "allowed <= balance")
        impl_path = Path(self.tmpdir) / "tt.ts"
        impl_path.write_text(
            "function withdraw(balance: number, allowed: number): number {\n"
            "  if (`${{ k: balance > 0 ? allowed : 0 }}`.length > 0) {\n"
            "    return balance - allowed;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_fstring_spec_type_char_is_not_a_variable(self):
        """`f"{value:{width:d}}"` — the `d` is a format type character,
        not a variable read."""
        spec_path = self._write_spec("withdraw", "value >= d")
        impl_path = Path(self.tmpdir) / "fc.py"
        impl_path.write_text(
            "def withdraw(value, d, width):\n"
            '    assert len(f"{value:{width:d}}") > 0\n'
            "    return value - d\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_fstring_conversion_with_dynamic_spec_keeps_variable(self):
        """`f"{balance!r:{width}}"` — conversion `!r` does not hide the
        dynamic spec's `width` read."""
        spec_path = self._write_spec("withdraw", "width <= balance")
        impl_path = Path(self.tmpdir) / "cv.py"
        impl_path.write_text(
            "def withdraw(balance, amount, width):\n"
            '    assert len(f"{balance!r:{width}}") > 0\n'
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_brace_inside_nested_literal_does_not_end_field(self):
        """`f"{a if '}}' else (amount <= balance)}"` — the `}}` sits inside
        a string literal inside the field; truncating there loses both
        identifiers."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "nb.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    assert f\"{'y' if '}}' else (amount <= balance)}\"\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    @unittest.skipUnless(
        sys.version_info >= (3, 12),
        "same-quote nesting inside f-string fields needs PEP 701",
    )
    def test_fstring_same_quote_fill_char_keeps_field(self):
        """`f"{x:{"|"}>5}"` — PEP 701 (Python 3.12+) allows the literal's
        own quote char inside a nested literal in a replacement field;
        the outer literal must not end early."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "qf.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    assert len(f"{balance:{"|"}>5}{amount:{"|"}>5}") > 0\n'
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        # Not just unflagged: the function must actually have been parsed
        # and scanned (an unparsed function lands in uncovered_atoms and
        # would pass the other assertion vacuously).
        assert "withdraw" not in report.uncovered_atoms
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_multiline_template_keeps_tail_after_close(self):
        """A template literal spanning lines: the closing backtick's line
        still carries a real comparison after it — and a constant return
        cannot smuggle the variable names in."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ml.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`start\n"
            "      end`.length > 0 && amount <= balance) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_multiline_template_interp_on_continuation_line(self):
        """`${amount <= balance}` on a continuation line of a multiline
        template is real code, not literal text."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "mli.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`start\n"
            "      ${amount <= balance}\n"
            "      end`.length > 0) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_apostrophe_in_comment_does_not_open_literal(self):
        """`# Don't allow overdrafts` — the apostrophe is not a string
        start, so the guard below it is still scanned."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ap.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    # Don't allow overdrafts\n"
            "    if amount <= balance:\n"
            "        return 0\n"
            "    raise ValueError()\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_nested_template_text_is_not_a_guard(self):
        """``${`if amount <= balance`}`` on a conditional line — the
        interpolation is kept, but the nested template's text is a
        string, not a real conditional."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "nt.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`chk ${`if amount <= balance`} x`.length > 0) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_comment_inside_interpolation(self):
        """`${/* amount <= balance */}` — comment text inside an
        interpolation is not a variable read."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ic.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${/* amount <= balance */ x}`.length > 0) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_backslash_continued_string_keeps_next_line_literal(self):
        """`"balance \\\n amount"` — a backslash-continued log string's
        second line is literal text, not a comparison."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "bc.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            '    logger.info("checking guard: \\\n'
            '              if amount <= balance")\n'
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_postfix_increment_then_division(self):
        """`counter++ / amount <= balance` — the `/` after postfix `++`
        is division, not a regex open, so both operands stay visible."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "pd.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${counter++ / amount <= balance}`) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_binary_plus_unary_plus_then_regex(self):
        """`x + +/balance|amount/` — spaced `+ +` is not postfix `++`,
        so the `/` opens a regex whose names are not variable reads."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "bp.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${x + +/balance|amount/}`.length > 0) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_regex_ending_in_escaped_slashes(self):
        """`${s.match(/a\\/\\//)}` — a pattern ending in `\\//` keeps its
        closing slash; the `//` is not a comment."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "rs.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${s.match(/amount\\/\\//)}`.length > 0) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_spaced_postfix_increment_then_division(self):
        """`counter ++ \\t/ amount <= balance` — whitespace around
        postfix `++` and before `/` still means division."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "spd.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${counter ++ \t/ amount <= balance}`) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_tagged_template_is_still_masked(self):
        """`tag\\`amount <= balance\\`` — a tagged template's fixed text
        is literal, not a comparison, even though the tag is an
        identifier right before the backtick."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "tg.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (tag`amount <= balance check`.length > 0) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_line_comment_at_expr_start(self):
        """`${// amount <= balance}` — a `//` at expression start is a
        comment, not an empty regex."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "lc.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${// amount <= balance\n"
            "       x}`.length > 0) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_block_comment_marker_inside_line_comment(self):
        r"""`// log `/api/*`` — a `/*` inside a // comment is text, not
        a block-comment opener that swallows the next lines."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "bc.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  // route /api/* matched\n"
            "  if (amount <= balance) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_line_comment_marker_inside_block_comment(self):
        """`/* a // b */ tag`x`` — a `//` inside /* */ does not make the
        following backtick comment text."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "cb.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (/* a // b */ `amount <= balance`.length > 0) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_python_backtick_inside_comment(self):
        """`x = 1 # see `tag` — a lone backtick inside a # comment is
        text, not a multiline literal start."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "pbc.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    x = 1  # see `tag\n"
            "    if amount <= balance:\n"
            "        return 0\n"
            "    raise ValueError()\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_slashed_comment_delimiter_keeps_block(self):
        """`/*/ \\`x\\` */` — the / after /* is not the start of */ —
        content before the real close is comment text."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "sd.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  /*/ `x` */ if (amount <= balance) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_division_after_comment_close(self):
        """`x /* c *// y` — the / after */ is division, not a comment."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "dc.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if ((amount /* c *// balance) <= balance) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_backtick_inside_block_comment(self):
        """`/* see // `x */` — a lone backtick inside a /* comment is
        comment text, not a template start (a paired one could pass
        either way)."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "ub.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  /* note // `x */ if (amount <= balance) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_backtick_inside_line_comment(self):
        """`// see tag`docs` — an unclosed backtick inside a //
        comment is text, not a template start."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "bt.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  // see tag`docs\n"
            "  if (amount <= balance) {\n"
            "    return 0;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_apostrophe_comment_ending_in_backslash(self):
        """`# don\\'t allow overdrafts \\` — the apostrophe plus trailing
        backslash does not swallow the guard below."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "apb.py"
        impl_path.write_text(
            "def withdraw(balance, amount):\n"
            "    # don't allow overdrafts \\\n"
            "    if amount <= balance:\n"
            "        return 0\n"
            "    raise ValueError()\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_regex_pattern_names_are_not_variables(self):
        """`${s.match(/balance|amount/)}` — the pattern's names are not
        variable reads."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "rx.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${s.match(/balance|amount/)}`.length > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_block_comment_separates_tokens(self):
        """`amount/**/as number` — the comment must not glue tokens into
        `amountas`."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "cj.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${{ a: balance, b: amount/**/as number }}`.length > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_ts_block_comment_before_object_key(self):
        """`${{ /* c */ balance: 1, amount }}` — the comment does not make
        `balance` a real reference; it is still just a key."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "tc.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${{ /* c */ balance: 1, amount }}`.length > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" in report.spec_stronger_than_impl

    def test_ts_regex_quote_does_not_swallow_field(self):
        """`${x.test(/'/) ? amount : balance}` — the `'` inside the regex
        is not a string start and must not swallow the field."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "rq.ts"
        impl_path.write_text(
            "function withdraw(balance: number, amount: number): number {\n"
            "  if (`${x.test(/'/) ? amount : balance}`.length > 0) {\n"
            "    return balance - amount;\n"
            "  }\n"
            "  throw new Error();\n"
            "}\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="typescript"
        )
        assert "withdraw" not in report.spec_stronger_than_impl

    def test_python_annotated_signature_body_is_extracted(self):
        """`def f(x: int) -> int:` must produce a body — previously the regex
        required `)` immediately before `:` so annotated functions were
        silently treated as bodiless."""
        spec_path = self._write_spec("withdraw", "amount <= balance")
        impl_path = Path(self.tmpdir) / "annotated.py"
        impl_path.write_text(
            "def withdraw(balance: int, amount: int) -> int:\n"
            "    return balance - amount\n"
        )
        report = self.validator.validate_spec_vs_impl(
            spec_path=str(spec_path), impl_path=str(impl_path), language="python"
        )
        assert "withdraw" in report.spec_stronger_than_impl


# ---------------------------------------------------------------------------
# Tests: CrossValidator.detect_spec_drift
# ---------------------------------------------------------------------------

class TestDetectSpecDrift:
    def setup_method(self):
        self.validator = CrossValidator()

    def test_no_drift(self):
        cert = {
            "atoms": [
                {"name": "add", "content_hash": "abc123"},
                {"name": "sub", "content_hash": "def456"},
            ]
        }
        report = self.validator.detect_spec_drift(cert, cert)
        assert not report.drift_detected
        assert report.changed_atoms == []
        assert report.new_atoms == []
        assert report.removed_atoms == []

    def test_changed_atom(self):
        old_cert = {
            "atoms": [
                {"name": "add", "content_hash": "abc123"},
                {"name": "sub", "content_hash": "def456"},
            ]
        }
        new_cert = {
            "atoms": [
                {"name": "add", "content_hash": "changed"},
                {"name": "sub", "content_hash": "def456"},
            ]
        }
        report = self.validator.detect_spec_drift(old_cert, new_cert)
        assert report.drift_detected
        assert "add" in report.changed_atoms

    def test_new_atom(self):
        old_cert = {"atoms": [{"name": "add", "content_hash": "abc123"}]}
        new_cert = {
            "atoms": [
                {"name": "add", "content_hash": "abc123"},
                {"name": "mul", "content_hash": "new789"},
            ]
        }
        report = self.validator.detect_spec_drift(old_cert, new_cert)
        assert report.drift_detected
        assert "mul" in report.new_atoms

    def test_removed_atom(self):
        old_cert = {
            "atoms": [
                {"name": "add", "content_hash": "abc123"},
                {"name": "deprecated", "content_hash": "old111"},
            ]
        }
        new_cert = {"atoms": [{"name": "add", "content_hash": "abc123"}]}
        report = self.validator.detect_spec_drift(old_cert, new_cert)
        assert report.drift_detected
        assert "deprecated" in report.removed_atoms


# ---------------------------------------------------------------------------
# Tests: CrossValidator.check_impl_coverage
# ---------------------------------------------------------------------------

class TestCheckImplCoverage:
    def setup_method(self):
        self.validator = CrossValidator()

    def test_full_coverage(self):
        result = self.validator.check_impl_coverage(
            spec_atoms=["add", "sub"],
            impl_functions=["add", "sub", "helper"],
        )
        assert result["ratio"] == 1.0
        assert result["covered"] == ["add", "sub"]
        assert result["uncovered"] == []
        assert result["extra_in_impl"] == ["helper"]

    def test_partial_coverage(self):
        result = self.validator.check_impl_coverage(
            spec_atoms=["add", "sub", "mul"],
            impl_functions=["add"],
        )
        assert abs(result["ratio"] - 1 / 3) < 0.01
        assert result["uncovered"] == ["mul", "sub"]

    def test_empty_spec(self):
        result = self.validator.check_impl_coverage(
            spec_atoms=[],
            impl_functions=["add"],
        )
        assert result["ratio"] == 0.0
