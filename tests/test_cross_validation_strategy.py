"""Tests for agent.strategies.cross_validation_strategy."""
from __future__ import annotations

import json
import tempfile
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
            "  if (`${balance}`.length > 0 && amount <= balance) {\n"
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
