"""Tests for foreign-code contract extraction and verification."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import mcp_server
from agent.strategies.foreign_code_strategy import (
    ForeignCodeExtractor,
    ForeignCodeSpec,
    ForeignCodeVerifier,
    main as foreign_code_main,
    build_parser,
    to_mumei_atom,
)
from agent.strategies.foreign_code_strategy_helpers import (
    build_solidity_guard_trace_proof_certificate,
)
from agent.cross_validation import validate_foreign_code
from agent.config import AgentConfig


FIXTURES = Path(__file__).parent / "fixtures"


def _payload(raw: str) -> dict:
    assert isinstance(raw, str)
    return json.loads(raw)


def test_extract_python_function_contracts_from_ast_docstrings() -> None:
    source = (FIXTURES / "sample_python.py").read_text(encoding="utf-8")

    specs = ForeignCodeExtractor().extract_python(source)

    assert [spec.function_name for spec in specs] == ["safe_divide", "is_positive"]
    assert specs[0].params == {"a": "i64", "b": "i64"}
    assert specs[0].return_type == "i64"
    assert specs[0].preconditions == ["b != 0"]
    assert specs[0].postconditions == ["result * b == a"]
    assert specs[1].return_type == "bool"
    assert specs[1].postconditions == ["result == (x > 0)"]


def test_extract_typescript_function_contracts_from_jsdoc() -> None:
    source = (FIXTURES / "sample_typescript.ts").read_text(encoding="utf-8")

    specs = ForeignCodeExtractor().extract_typescript(source)

    assert [spec.function_name for spec in specs] == ["addBalances", "hasFunds"]
    assert specs[0].params == {"a": "i64", "b": "i64"}
    assert specs[0].preconditions == ["a >= 0", "b >= 0"]
    assert specs[0].postconditions == ["result == a + b"]
    assert specs[1].return_type == "bool"
    assert specs[1].postconditions == ["result == (balance > 0)"]


def test_extract_rust_function_contracts_from_doc_comments() -> None:
    source = """
/// requires: x >= 0
/// ensures: result >= x
pub fn widen(x: i64) -> i64 {
    x + 1
}
"""

    specs = ForeignCodeExtractor().extract_rust(source)

    assert specs == [
        ForeignCodeSpec(
            function_name="widen",
            params={"x": "i64"},
            return_type="i64",
            preconditions=["x >= 0"],
            postconditions=["result >= x"],
            source_line=4,
        )
    ]


def test_extract_go_generic_function_signature() -> None:
    source = """
package ssz

// SliceRoot computes the root of a slice of hashable objects.
func SliceRoot[T Hashable](slice []T, limit uint64) ([32]byte, error) {
    return [32]byte{}, nil
}
"""

    specs = ForeignCodeExtractor().extract_go(source)

    assert len(specs) == 1
    assert specs[0].function_name == "SliceRoot"
    assert specs[0].params == {"slice": "i64", "limit": "i64"}
    assert specs[0].return_type == "i64"
    assert specs[0].source_line == 5


def test_extract_solidity_function_contracts_from_natspec() -> None:
    source = (FIXTURES / "sample_solidity.sol").read_text(encoding="utf-8")

    specs = ForeignCodeExtractor().extract_solidity(source)

    assert [spec.function_name for spec in specs] == ["safeDivide", "add"]
    assert specs[0].params == {"a": "u64", "b": "u64"}
    assert specs[0].preconditions == ["b != 0"]
    assert specs[0].postconditions == ["result * b == a"]
    assert specs[1].function_name == "add"
    assert specs[1].postconditions == ["result == a + b"]


def test_verifier_reports_solidity_uint256_overflow_counterexample() -> None:
    from agent.audit_reporting import _verification_issue_strings

    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    result = ForeignCodeVerifier(mumei_client=mumei).verify(
        "function add(uint256 a, uint256 b) public pure returns (uint256) {\n"
        "    return a + b;\n"
        "}\n",
        "solidity",
    )

    assert result["success"] is False
    assert result["counterexample"] == {
        "a": 2**256 - 1,
        "b": 1,
    }
    violations = _verification_issue_strings(result)
    assert any("can overflow `a + b`" in violation for violation in violations)
    assert any("uint256 bounds contract" in violation for violation in violations)


def test_solidity_overflow_ignores_method_call_receiver() -> None:
    """`result + SafeCast.toUint(...)` must not model `SafeCast` as uint256 (#281)."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    expr = "result + SafeCast.toUint(unsignedRoundsUp(rounding) && result * result < a)"
    issues = _issues_for_expression("sqrt", expr, "Solidity")
    assert not any("can overflow" in issue.message for issue in issues)
    assert all("SafeCast" not in issue.message for issue in issues)

    # A genuine two-variable addition is still flagged.
    real = _issues_for_expression("add", "a + b", "Solidity")
    assert any("can overflow `a + b`" in issue.message for issue in real)


def test_solidity_nonzero_constant_divisor_not_flagged() -> None:
    """A non-zero `constant` divisor (e.g. curve order N) can't be zero (#296)."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    issues = _issues_for_expression(
        "verifySolidity",
        "(x % N) == r",
        "Solidity",
        known_constants={"N": 0xFFFFFFFF00000000},
    )
    assert not any("divide by" in issue.message for issue in issues)

    # Unknown divisor is still flagged.
    unknown = _issues_for_expression("f", "a % b", "Solidity")
    assert any("divide by `b`" in issue.message for issue in unknown)


def test_solidity_constant_index_pins_value_keeps_upper_bound() -> None:
    """A `constant` index (EVM_TREE_RADIX=16) is pinned to 16, not modeled as -1,
    but the upper-bound check is preserved (#296, PR #299)."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    issues = [
        issue
        for issue in _issues_for_expression(
            "tryTraverse",
            "decoded[EVM_TREE_RADIX]",
            "Solidity",
            known_constants={"EVM_TREE_RADIX": 16},
        )
        if "can index" in issue.message
    ]
    assert len(issues) == 1
    issue = issues[0]
    # No impossible negative index; the constant value is used instead.
    assert issue.counterexample["EVM_TREE_RADIX"] == 16
    # The redundant `>= 0` contract is dropped; the real upper bound stays.
    assert issue.required_contracts == ("EVM_TREE_RADIX < len_decoded",)

    # Unknown index is still flagged with both bounds.
    unknown = _issues_for_expression("f", "decoded[i]", "Solidity")
    idx = [issue for issue in unknown if "can index `decoded[i]`" in issue.message]
    assert idx and idx[0].required_contracts == ("i >= 0", "i < len_decoded")


def test_solidity_declared_constants_parses_hex_and_decimal() -> None:
    from agent.strategies.foreign_code_strategy_helpers import (
        _solidity_declared_constants,
    )

    source = (
        "uint256 internal constant N =\n"
        "    0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551;\n"
        "uint256 internal constant EVM_TREE_RADIX = 16;\n"
        "uint256 private constant DERIVED = EVM_TREE_RADIX + 1;\n"
    )
    constants = _solidity_declared_constants(source)
    assert constants["N"] != 0
    assert constants["EVM_TREE_RADIX"] == 16
    assert constants["DERIVED"] == 17  # derived constant expressions are resolved


def test_go_declared_constants_parses_all_literal_bases_and_skips_expressions() -> None:
    """Go const values may be hex, binary, octal, or have ``_`` separators."""
    from agent.strategies.foreign_code_strategy_helpers import _go_declared_constants

    source = """
const (
    gcmStandardNonceSize = 12
    gcmTagSize = 16
    maxHex = 0x7FFFFFFFFFFFFFFF
    withSep = 1_000_000
    binLit = 0b101
    octLit = 0o777
    derived = 1 << 5
)
"""
    constants = _go_declared_constants(source)
    assert constants["gcmStandardNonceSize"] == 12
    assert constants["gcmTagSize"] == 16
    assert constants["maxHex"] == 0x7FFFFFFFFFFFFFFF
    assert constants["withSep"] == 1_000_000
    assert constants["binLit"] == 0b101
    assert constants["octLit"] == 0o777
    assert constants["derived"] == 32  # constant expression is evaluated


def test_go_value_type_param_not_flagged_nil() -> None:
    """A Go value-type param (`reflect.Value`) can never be nil (#295)."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _detect_go_safety_issues,
    )

    source = (
        "package rlp\n"
        "func decodeUint(s *Stream, val reflect.Value) error {\n"
        "    return val.Kind()\n"
        "}\n"
    )
    issues = _detect_go_safety_issues(source)
    assert not any("val" in issue.message and "non-nil" in issue.message for issue in issues)


def test_go_pointer_param_still_flagged_nil() -> None:
    """A genuine pointer param must still get a non-nil requirement (#295)."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _detect_go_safety_issues,
    )

    source = "package users\nfunc age(user *User) int { return user.Age }\n"
    issues = _detect_go_safety_issues(source)
    assert any("user" in issue.message and "non-nil" in issue.message for issue in issues)


def test_go_data_receiver_nonnil() -> None:
    """Pointer receivers of internal ``*Data`` container structs are non-nil (#260)."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _detect_go_safety_issues,
    )

    source = (
        "package client\n"
        "type storeData struct { initialized bool }\n"
        "func (d *storeData) isInitialized() bool { return d.initialized }\n"
    )
    issues = _detect_go_safety_issues(source)
    assert not any("d" in issue.message and "non-nil" in issue.message for issue in issues)


def test_go_to_proto_receiver_nonnil() -> None:
    """Pointer receivers with ``ToProto`` JSON/SSZ conversion methods are non-nil (#261)."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _detect_go_safety_issues,
    )

    source = (
        "package builder\n"
        "type ExecPayloadResponseCapella struct { Data struct{} }\n"
        "func (r *ExecPayloadResponseCapella) ToProto() (*X, error) { return r.Data.Method() }\n"
    )
    issues = _detect_go_safety_issues(source)
    assert not any("r" in issue.message and "non-nil" in issue.message for issue in issues)


def test_go_cross_validation_value_param_not_flagged_nil() -> None:
    """The contract-inference path must also skip value types (#295, PR #298)."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = (
        "package rlp\n"
        "func decodeUint(s *Stream, val reflect.Value) bool {\n"
        "    return val.Kind()\n"
        "}\n"
    )
    atoms = _infer_go_contracts(source)
    assert atoms
    assert "val != nil" not in atoms[0].requires
    # A genuine pointer receiver/param is still required to be non-nil.
    ptr = _infer_go_contracts(
        "package users\nfunc age(user *User) bool { return user.Age }\n"
    )
    assert ptr and "user != nil" in ptr[0].requires


def test_go_type_is_nillable_matrix() -> None:
    from agent.strategies.foreign_code_strategy_helpers import _go_type_is_nillable

    for nillable in ("*Stream", "[]byte", "map[string]int", "chan int", "error", "any", "func() int"):
        assert _go_type_is_nillable(nillable), nillable
    for value_type in ("reflect.Value", "time.Time", "int", "uint64", "MyStruct", "big.Int"):
        assert not _go_type_is_nillable(value_type), value_type


def test_solidity_value_param_not_flagged_null() -> None:
    """Solidity `bytes` params are never null; no non-null violation (#295)."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    issues = _issues_for_expression("tryRecover", "signature.length", "Solidity")
    assert not any("non-null" in issue.message for issue in issues)


def test_typescript_null_deref_still_flagged() -> None:
    """TS null/undefined dereference must still be reported (#295 keeps TS)."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    issues = _issues_for_expression("len", "name!.length", "TypeScript")
    assert any("non-null" in issue.message for issue in issues)


def test_typescript_nullable_param_names_classify_optionality_and_types() -> None:
    """Nullable TS parameters are identified by optional markers or null/undefined/any types."""
    from agent.strategies.foreign_code_strategy_helpers import _typescript_nullable_param_names

    source = (
        "export function fn1(a: string, b?: string, c: string | null, d: any): number { return 1; }\n"
        "export const fn2 = (items: number[], maybe: number | undefined) => items.length;\n"
    )
    names = _typescript_nullable_param_names(source)
    assert names["fn1"] == {"b", "c", "d"}
    assert names["fn2"] == {"maybe"}


def test_typescript_safety_skips_non_nullable_array_params() -> None:
    """Well-typed array/object parameters should not trigger false positive null/bounds issues."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = "export function last(items: number[]): number { return items[items.length - 1]; }\n"
    issues = _detect_safety_issues(source, "typescript")
    assert not issues


def test_typescript_safety_ignores_index_bounds() -> None:
    """JS/TS out-of-bounds access returns ``undefined``; do not emit index safety issues."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = "export function at(items: number[], i: number): number { return items[i]; }\n"
    issues = _detect_safety_issues(source, "typescript")
    assert not any("index" in issue.message.lower() for issue in issues)


def test_typescript_safety_skips_local_array_length() -> None:
    """Local arrays returned by helpers like ``takeRight`` are not nullable params."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """const Matchers: FC<MatchersProps> = ({ matchers }) => {
  const rest = takeRight(matchers, matchers.length - 5);
  return rest.length > 0 && rest.map((m) => m);
};
"""
    issues = _detect_safety_issues(source, "typescript")
    assert not any("non-null" in issue.message for issue in issues)


def test_rust_go_overflow_requires_ignore_method_call_receiver() -> None:
    """`a + SomeStruct.method()` must not bound `SomeStruct` as a free integer (#281)."""
    from agent.cross_validation_foreign import (
        _integer_overflow_requires_for_expression,
    )

    reqs = _integer_overflow_requires_for_expression("a + SomeStruct.method()")
    assert reqs == []

    # A genuine two-variable addition still emits overflow bounds.
    real = _integer_overflow_requires_for_expression("a + b")
    assert any("a + b <=" in req for req in real)


def test_rust_const_divisor_not_flagged_cross_language() -> None:
    """A non-zero Rust ``const`` divisor is pinned like a Solidity constant (#296)."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = "const N: i64 = 7;\npub fn modn(a: i64) -> i64 { a % N }\n"
    issues = _detect_safety_issues(source, "rust")
    assert not any("divide by" in issue.message for issue in issues)

    # An unknown divisor is still flagged.
    unknown = _detect_safety_issues(
        "pub fn divide(a: i64, b: i64) -> i64 { a / b }\n", "rust"
    )
    assert any("divide by `b`" in issue.message for issue in unknown)


def test_typescript_const_divisor_not_flagged_cross_language() -> None:
    """A non-zero TypeScript ``const`` divisor is pinned like a Solidity constant (#296)."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = "const K = 5;\nexport function divk(a: number): number { return a / K; }\n"
    issues = _detect_safety_issues(source, "typescript")
    assert not any("divide by" in issue.message for issue in issues)


def test_infer_rust_const_divisor_requires_dropped() -> None:
    """The contract-inference (requires) path also honors Rust ``const`` (#296)."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    atoms = _infer_rust_contracts(
        "const N: i64 = 7;\npub fn modn(a: i64) -> i64 { a % N }\n"
    )
    assert atoms and "N != 0" not in atoms[0].requires
    # Unknown divisor still yields a non-zero requirement.
    unknown = _infer_rust_contracts("pub fn divide(a: i64, b: i64) -> i64 { a / b }\n")
    assert unknown and "b != 0" in unknown[0].requires


def test_value_type_length_not_flagged_null_cross_language() -> None:
    """`.length`/`.len` on a value type is not a null dereference (#295).

    Only TypeScript (where a value may genuinely be null/undefined) keeps the
    contract; Solidity value types and Rust references never do.
    """
    from agent.cross_validation_foreign import _safety_requires_for_expression

    assert _safety_requires_for_expression("signature.length", "solidity") == "true"
    assert _safety_requires_for_expression("v.len()", "rust") == "true"
    # TypeScript still guards a possibly-null receiver.
    ts = _safety_requires_for_expression("name!.length", "typescript")
    assert "name != null" in ts


def test_generic_fallback_null_suppression_is_language_aware() -> None:
    """The regex fallback path (used when tree-sitter is unavailable) also honors
    per-language nullability (#295)."""
    from agent.cross_validation_foreign import (
        _generic_safety_requires_for_expression,
    )

    assert _generic_safety_requires_for_expression("v.len", language="rust") == []
    assert (
        _generic_safety_requires_for_expression("sig.length", language="solidity") == []
    )
    ts = _generic_safety_requires_for_expression("name.length", language="typescript")
    assert "name != null" in ts and "name != undefined" in ts


def test_verifier_reports_solidity_reentrancy_and_access_control_heuristics() -> None:
    source = (FIXTURES / "sample_solidity_vulnerable.sol").read_text(encoding="utf-8")
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    result = ForeignCodeVerifier(mumei_client=mumei).verify(source, "solidity")

    assert result["success"] is False
    assert any("may be vulnerable to reentrancy" in error for error in result["errors"])
    assert any("Checks-Effects-Interactions" in error for error in result["errors"])
    assert any("no access-control guard" in error for error in result["errors"])
    assert any("withdraw" in error and "reentrancy" in error for error in result["errors"])
    assert any("setOwner" in error and "access-control guard" in error for error in result["errors"])
    assert all("withdrawAll" not in error for error in result["errors"])
    assert all("getBalance" not in error for error in result["errors"])
    assert result["counterexample"]["guard"] == "absent"
    assert result["counterexample"]["reentrancy_trace"] == [
        "externalCall: msg.sender.call{value: amount}(\"\");",
        "stateWrite: balances[msg.sender]",
    ]
    mumei.verify.assert_called_once()


def test_verifier_ignores_go_literals_and_comments_in_safety_heuristics() -> None:
    source = (
        "package demo\n"
        "// http://example.com and/or other notes should not matter\n"
        "func unmarshalText(input []byte) error {\n"
        '    return fmt.Errorf("invalid hex or decimal integer %q", input)\n'
        "}\n"
    )
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    result = ForeignCodeVerifier(mumei_client=mumei).verify(source, "go")

    assert result["success"] is True
    assert all("divide by" not in error for error in result["errors"])
    assert all("overflow" not in error for error in result["errors"])


def test_validate_foreign_code_ignores_go_literals_and_comments_in_safety_requires() -> None:
    result = validate_foreign_code(
        (
            "package demo\n"
            "// http://example.com and/or other notes should not matter\n"
            "func unmarshalText(input []byte) error {\n"
            '    return fmt.Errorf("invalid hex or decimal integer %q", input)\n'
            "}\n"
        ),
        "go",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is True
    assert result.inferred_atoms[0].requires == "true"


def test_validate_foreign_code_keeps_real_go_division_requirement() -> None:
    result = validate_foreign_code(
        "package demo\nfunc divide(a int, b int) int { return a / b }\n",
        "go",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is True
    assert result.inferred_atoms[0].requires == "b != 0"


def test_validate_foreign_code_keeps_rust_lifetimes_and_division_requirement() -> None:
    result = validate_foreign_code(
        "pub fn divide<'a>(a: i64, b: i64, x: &'a str) -> i64 { a / b }\n",
        "rust",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is True
    assert result.inferred_atoms[0].requires == "b != 0"


def test_validate_foreign_code_ignores_rust_literals_and_comments_in_safety_requires() -> None:
    result = validate_foreign_code(
        "pub fn render<'a>(x: &'a str) -> &'a str {\n"
        "    // / still should not count\n"
        '    "http://example.com/and/or".into()\n'
        "}\n",
        "rust",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is True
    assert result.inferred_atoms[0].requires == "true"


def test_verifier_suppresses_solidity_reentrancy_when_guarded() -> None:
    source = (FIXTURES / "sample_solidity_guarded.sol").read_text(encoding="utf-8")
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    result = ForeignCodeVerifier(mumei_client=mumei).verify(source, "solidity")

    assert result["success"] is False
    assert any("no access-control guard" in error for error in result["errors"])
    assert all("may be vulnerable to reentrancy" not in error for error in result["errors"])
    assert "counterexample" not in result
    mumei.verify.assert_called_once()


def test_build_solidity_guard_trace_proof_certificate_from_vulnerable_fixture() -> None:
    source = (FIXTURES / "sample_solidity_vulnerable.sol").read_text(encoding="utf-8")

    cert = build_solidity_guard_trace_proof_certificate(
        source,
        source_file=FIXTURES / "sample_solidity_vulnerable.sol",
        package_name="sample_solidity_vulnerable",
        package_version="0",
        mumei_version="agent",
        timestamp="2026-07-06T00:00:00Z",
    )

    atoms = {atom["name"]: atom for atom in cert["atoms"]}
    assert set(atoms) == {"withdraw_guard_trace", "withdrawAll_guard_trace"}
    assert atoms["withdraw_guard_trace"]["translator_ir"]["guard_trace"]["ops"] == [
        "externalCall"
    ]
    assert atoms["withdraw_guard_trace"]["translator_ir"]["guard_trace_expected_outcome"] == "none"
    assert atoms["withdraw_guard_trace"]["translator_ir"]["theorem_goal"] == (
        "runGuard GuardState.Unlocked [GuardOp.externalCall] = none"
    )
    assert atoms["withdraw_guard_trace"]["logic_fragment_tag"] == "smart_contract_guard_trace"
    assert atoms["withdraw_guard_trace"]["unknown_obligation_domain"] == "smart_contract"
    assert atoms["withdraw_guard_trace"]["translator_ir"]["obligation_class"] == (
        "smart_contract_guard_trace_obligation"
    )
    assert atoms["withdrawAll_guard_trace"]["translator_ir"]["guard_trace"]["ops"] == [
        "externalCall"
    ]
    assert atoms["withdrawAll_guard_trace"]["translator_ir"]["guard_trace_expected_outcome"] == "none"
    assert cert["file"] == str(FIXTURES / "sample_solidity_vulnerable.sol")
    assert cert["package_name"] == "sample_solidity_vulnerable"
    assert cert["all_verified"] is False


def test_build_solidity_guard_trace_proof_certificate_from_guarded_fixture() -> None:
    source = (FIXTURES / "sample_solidity_guarded.sol").read_text(encoding="utf-8")

    cert = build_solidity_guard_trace_proof_certificate(
        source,
        source_file=FIXTURES / "sample_solidity_guarded.sol",
        package_name="sample_solidity_guarded",
        package_version="0",
        mumei_version="agent",
        timestamp="2026-07-06T00:00:00Z",
    )

    atoms = {atom["name"]: atom for atom in cert["atoms"]}
    assert set(atoms) == {"withdraw_guard_trace", "manualWithdraw_guard_trace"}
    for atom in atoms.values():
        guard_trace = atom["translator_ir"]["guard_trace"]
        assert guard_trace["ops"][0] == "lock"
        assert guard_trace["ops"][-1] == "unlock"
        assert guard_trace["expected_outcome"] == "safe"
        assert atom["translator_ir"]["guard_trace_expected_outcome"] == "safe"
        assert atom["translator_ir"]["theorem_goal"].endswith(
            "= some GuardState.Unlocked"
        )
        assert atom["translator_ir"]["requires_bridge_lemmas"] == [
            "MumeiLean.SmartContract.no_external_call_without_lock"
        ]


def test_validate_foreign_code_can_upgrade_guard_trace_certificate_via_lean_bridge() -> None:
    source = (FIXTURES / "sample_solidity_guarded.sol").read_text(encoding="utf-8")
    config = AgentConfig(api_key="test", mumei_lean_repo="/tmp/mumei-lean")

    lean_cert = {
        "atoms": [
            {
                "name": "withdraw_guard_trace",
                "z3_check_result": "lean_verified",
                "status": "verified",
            },
            {
                "name": "manualWithdraw_guard_trace",
                "z3_check_result": "lean_verified",
                "status": "verified",
            },
        ]
    }

    with patch("agent.cross_validation.run_lean_bridge_and_merge_proof_cert") as bridge_mock:
        bridge_mock.return_value = (
            {
                "atoms": [
                    {
                        "name": "withdraw_guard_trace",
                        "z3_check_result": "lean_verified",
                        "status": "verified",
                    },
                    {
                        "name": "manualWithdraw_guard_trace",
                        "z3_check_result": "lean_verified",
                        "status": "verified",
                    },
                ]
            },
            {
                "success": True,
                "lean_cert": lean_cert,
                "diagnostics": ["bridge diag"],
                "stdout": "",
                "stderr": "",
            },
        )
        result = validate_foreign_code(
            source,
            "solidity",
            config=config,
            use_llm=False,
            run_mumei=False,
            enable_lean_bridge=True,
        )

    bridge_mock.assert_called_once()
    assert result.proof_certificate is not None
    atoms = {atom["name"]: atom for atom in result.proof_certificate["atoms"]}
    assert atoms["withdraw_guard_trace"]["z3_check_result"] == "lean_verified"
    assert atoms["withdraw_guard_trace"]["status"] == "verified"
    assert atoms["manualWithdraw_guard_trace"]["z3_check_result"] == "lean_verified"
    assert result.lean_bridge is not None
    assert result.lean_bridge["success"] is True
    assert "bridge diag" in result.warnings


def test_to_mumei_atom_emits_trusted_contract() -> None:
    atom = to_mumei_atom(
        ForeignCodeSpec(
            function_name="safe_divide",
            params={"a": "i64", "b": "i64"},
            return_type="i64",
            preconditions=["b != 0"],
            postconditions=["result * b == a"],
        )
    )

    assert "trusted atom safe_divide(a: i64, b: i64) -> i64 {" in atom
    assert "requires: b != 0;" in atom
    assert "ensures: result * b == a;" in atom


def test_to_mumei_atom_maps_byte_slice_types_to_string() -> None:
    """Byte-slice/string params keep type fidelity instead of defaulting to i64 (#283)."""
    atom = to_mumei_atom(
        ForeignCodeSpec(
            function_name="FromHex",
            params={"s": "string", "b": "[]byte"},
            return_type="[]byte",
        )
    )

    assert "trusted atom FromHex(s: string, b: string) -> string {" in atom
    assert "i64" not in atom


def test_mumei_type_maps_byte_and_buffer_types() -> None:
    from agent.strategies.foreign_code_strategy_helpers import _mumei_type

    assert _mumei_type("[]byte") == "string"
    assert _mumei_type("Vec<u8>") == "string"
    assert _mumei_type("&[u8]") == "string"
    assert _mumei_type("Uint8Array") == "string"
    assert _mumei_type("bytes32") == "string"
    # Non-byte integers are unaffected.
    assert _mumei_type("i64") == "i64"
    assert _mumei_type("u32") == "u64"


def test_to_mumei_atom_drops_ensures_referencing_undeclared_helper() -> None:
    """`ensures: result == Hex2Bytes(s)` can't verify in a single-atom skeleton (#283)."""
    atom = to_mumei_atom(
        ForeignCodeSpec(
            function_name="FromHex",
            params={"s": "string"},
            return_type="string",
            postconditions=["result == Hex2Bytes(s)"],
        )
    )

    assert "Hex2Bytes" not in atom
    assert "ensures: true;" in atom


def test_to_mumei_atom_keeps_ensures_using_declared_names_and_builtins() -> None:
    atom = to_mumei_atom(
        ForeignCodeSpec(
            function_name="pad",
            params={"b": "string", "n": "i64"},
            return_type="string",
            postconditions=["len(result) >= n"],
        )
    )

    assert "ensures: len(result) >= n;" in atom


def test_verifier_runs_mumei_client_on_extracted_atom() -> None:
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    result = ForeignCodeVerifier(mumei_client=mumei).verify(
        "def safe_divide(a: int, b: int) -> int:\n"
        '    """requires: b != 0\n    ensures: result * b == a"""\n'
        "    return a // b\n",
        "python",
    )

    assert result["success"] is True
    assert result["specs"][0]["function_name"] == "safe_divide"
    assert result["source_line_map"] == {"safe_divide": 1}
    assert "trusted atom safe_divide" in result["mumei_source"]
    mumei.verify.assert_called_once()


def test_verifier_does_not_report_covered_safety_contracts() -> None:
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    result = ForeignCodeVerifier(mumei_client=mumei).verify(
        "/**\n"
        " * requires: name != null\n"
        " * ensures: result >= 0\n"
        " */\n"
        "export function len(name?: string): number { return name!.length; }\n",
        "typescript",
    )

    assert result["success"] is True
    assert result["errors"] == []
    assert "counterexample" not in result


def test_mcp_verify_foreign_code_tool_returns_json_payload() -> None:
    result = _payload(
        mcp_server.verify_foreign_code(
            "def add(a: int, b: int) -> int:\n    return a + b\n",
            "python",
            use_llm=False,
            run_mumei=False,
        )
    )

    assert result["status"] == "ok"
    assert result["success"] is True
    assert result["inferred_atoms"][0]["name"] == "add"


def test_cli_verify_foreign_writes_json_report(tmp_path: Path) -> None:
    source = tmp_path / "code.py"
    output = tmp_path / "report.json"
    source.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    args = build_parser().parse_args(
        ["--file", str(source), "--language", "python", "--output", str(output)]
    )
    fake_client = MagicMock()
    fake_client.verify.return_value = {"success": True, "report": {}, "stdout": "{}", "stderr": ""}

    with patch(
        "agent.strategies.foreign_code_strategy.create_mumei_client",
        return_value=fake_client,
    ):
        result = foreign_code_main(args)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result["success"] is True
    assert payload["success"] is True
    assert payload["specs"][0]["function_name"] == "add"


def test_rust_contract_inference_preserves_bool_return_and_balanced_braces() -> None:
    """Boolean Rust returns must keep ``bool`` and not be coerced to ``i64``."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = "pub fn flag(cond: bool) -> bool {\n    if cond { return true; }\n    false\n}\n"
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].return_type == "bool"
    # Body extraction must reach the tail expression, not stop at the inner ``}``.
    assert "result == false" in atoms[0].ensures


def test_rust_contract_inference_skips_trailing_punctuation_in_tail_expression() -> None:
    """Tail expressions that end with a closing brace/comma are not valid Rust expressions."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = (
        "pub fn add_u8_range_check(&mut self, a: u8, b: u8) {\n"
        "    self.add_byte_lookup_event(ByteLookupEvent {\n"
        "        opcode: ByteOpcode::U8Range,\n"
        "        a: 0,\n"
        "        b: a,\n"
        "        c: b,\n"
        "    });\n"
        "}\n"
    )
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 1
    # The method call spans multiple lines and cannot be captured as a single-line tail;
    # the extractor must not emit ``result == }`` or ``result == c,`` garbage.
    assert atoms[0].ensures == "true"


def test_rust_contract_inference_bool_ensures_checks_param_type() -> None:
    """Boolean Rust functions must not emit ``result == <non-bool-param>`` for macro args."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = '''
fn is_literal_null_or_number(expr: &Expr) -> bool {
    matches!(
        expr,
        Expr::Literal(
            ScalarValue::Null | ScalarValue::Int64(_) | ScalarValue::Float64(_),
            _
        )
    )
}
'''
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].return_type == "bool"
    # ``expr`` is ``&Expr`` (mapped to ``i64``), so it must not be used as a bool RHS.
    assert atoms[0].ensures == "true"


def test_rust_contract_inference_preserves_unsigned_int_return_type() -> None:
    """Rust ``usize``/``u64`` return types must map to Mumei ``u64``."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    atoms = _infer_rust_contracts("pub fn len(v: Vec<i64>) -> usize { v.len() }\n")
    assert atoms[0].return_type == "u64"


def test_go_contract_inference_preserves_bool_return_type() -> None:
    """Go ``bool`` return types must map to Mumei ``bool``."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = "package demo\nfunc is_true() bool { return true }\n"
    atoms = _infer_go_contracts(source)
    assert atoms[0].return_type == "bool"
    assert atoms[0].ensures == "result == true"


def test_go_contract_inference_captures_composite_literal_return() -> None:
    """Go return statements with composite/struct literals must not be truncated at ``}``."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = (
        "package demo\n"
        "func new_timer(t int64, ch string) *systemTimer {\n"
        "    return &systemTimer{t, ch}\n"
        "}\n"
    )
    atoms = _infer_go_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].ensures == "result == &systemTimer{t, ch}"


def test_go_contract_inference_guards_nil_with_or_condition() -> None:
    """An ``if c == nil || other == nil { return }`` guard makes both non-nil."""
    from agent.strategies.foreign_code_strategy_helpers import _go_nil_guarded_return_values

    body = "if c == nil || other == nil { return c == other }\nreturn bytes.Equal(c.Raw, other.Raw)"
    assert _go_nil_guarded_return_values(body) == {"c", "other"}


def test_go_contract_inference_uses_last_return_for_safety_multiple_returns() -> None:
    """With multiple returns, the last (fall-through) return drives safety ``requires``."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = (
        "package demo\n"
        "func Equal(c, other *T) bool {\n"
        "    if c == nil || other == nil { return c == other }\n"
        "    return bytes.Equal(c.Raw, other.Raw)\n"
        "}\n"
    )
    atoms = _infer_go_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].requires == "c != nil && other != nil"


def test_go_contract_inference_avoids_false_postcondition_for_multiple_returns() -> None:
    """Functions with early returns must not be summarised by their final ``return`` only."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = (
        "package demo\n"
        "func isHex(str string) bool {\n"
        "    if len(str)%2 != 0 { return false }\n"
        "    for _, c := range []byte(str) {\n"
        "        if !isHexCharacter(c) { return false }\n"
        "    }\n"
        "    return true\n"
        "}\n"
    )
    atoms = _infer_go_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].ensures == "true"


def test_go_contract_inference_ignores_multi_value_return() -> None:
    """Go functions returning multiple values cannot use a single ``result`` equality."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = (
        "package demo\n"
        "func SafeAdd(x, y uint64) (uint64, bool) {\n"
        "    sum, carryOut := bits.Add64(x, y, 0)\n"
        "    return sum, carryOut != 0\n"
        "}\n"
    )
    atoms = _infer_go_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].ensures == "true"


def test_go_contract_inference_extracts_assembly_forward_declarations() -> None:
    """Go assembly forward declarations without a body produce trusted atoms."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = (
        "package demo\n"
        "//go:noescape\n"
        "func add(c, a, b *Int)\n"
        "func scale(out, in *Int, n uint64)\n"
    )
    atoms = _infer_go_contracts(source)
    names = {atom.name for atom in atoms}
    assert names == {"add", "scale"}
    assert all(atom.requires == "true" and atom.ensures == "true" for atom in atoms)


def test_foreign_code_verifier_accepts_go_assembly_forward_declarations() -> None:
    """Files containing only build-tag guarded assembly stubs are verified, not unverifiable."""
    from agent.strategies.foreign_code_strategy import ForeignCodeVerifier

    source = (
        "//go:build (loong64 || riscv64) && !purego\n"
        "package sha512\n"
        "//go:noescape\n"
        "func block(dig *Digest, p []byte)\n"
    )
    mumei = MagicMock()
    mumei.verify.return_value = {"success": True, "errors": [], "warnings": []}
    result = ForeignCodeVerifier(mumei_client=mumei).verify(source, "go")
    assert result["success"] is True
    assert result["errors"] == []


def test_raw_return_statement_expression_keeps_single_value_with_comma_in_string() -> None:
    """A comma inside a returned string literal must not be read as a multi-value return."""
    from agent.cross_validation_foreign import _raw_return_statement_expression

    source = 'package demo\nfunc greeting() string {\n    return "hello, world"\n}\n'
    assert _raw_return_statement_expression(source) == '"hello, world"'


def test_params_from_signature_handles_nested_commas_in_generics() -> None:
    """Generic Rust parameters must not be split on commas inside nested parentheses."""
    from agent.cross_validation_foreign import _params_from_signature

    signature = "table: impl IntoIterator<Item = (K, &'a V)> + 'a, hide_zeros: bool"
    params = _params_from_signature(signature)
    assert [param.name for param in params] == ["table", "hide_zeros"]


def test_rust_trait_methods_are_extracted_as_trusted_atoms() -> None:
    """Rust trait declarations without a body must still produce atoms."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = (
        "pub trait ComputeInstructions {\n"
        "    fn add(&mut self, rd: u32, rs1: u32, rs2: u32);\n"
        "    fn result(&self) -> u64;\n"
        "}\n"
    )
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 2
    add = [a for a in atoms if a.name == "add"][0]
    assert [p.name for p in add.params] == ["rd", "rs1", "rs2"]
    assert add.return_type == "()"
    assert add.requires == "true"
    assert add.ensures == "true"
    result = [a for a in atoms if a.name == "result"][0]
    assert result.return_type == "u64"
    assert [p.name for p in result.params] == []


def test_rust_trait_methods_skip_lifetime_annotated_self() -> None:
    """Rust receivers with lifetimes such as ``&'a self`` and ``&'a mut self`` are skipped."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = (
        "pub trait Parser {\n"
        "    fn parse<'a>(&'a self, input: &'a str) -> &'a str;\n"
        "    fn parse_mut<'a>(&'a mut self, input: &'a str) -> &'a str;\n"
        "}\n"
    )
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 2
    for atom in atoms:
        assert [p.name for p in atom.params] == ["input"]


def test_rust_fixed_size_array_return_is_not_misclassified_as_external() -> None:
    """A function returning ``[T; N]`` must have its body analyzed, not trusted."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = (
        "pub fn digest() -> [u8; 32] {\n"
        "    arr\n"
        "}\n"
    )
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].return_type == "i64"
    assert atoms[0].ensures == "result == arr"


def test_rust_source_line_map_handles_where_clauses_and_impl_returns() -> None:
    """Rust source-line map must include functions with ``where`` clauses and ``impl`` return types."""
    from agent.cross_validation_foreign import _infer_foreign_source_line_map

    source = (
        "pub fn sorted_table_lines<'a, K, V>(\n"
        "    table: impl IntoIterator<Item = (K, &'a V)> + 'a,\n"
        ") -> (usize, impl Iterator<Item = (String, &'a V)>)\n"
        "where\n"
        "    K: Ord + Display + 'a,\n"
        "    V: Ord + Display + 'a,\n"
        "{\n"
        "    (0, std::iter::empty())\n"
        "}\n"
    )
    line_map = _infer_foreign_source_line_map(source, "rust")
    assert "sorted_table_lines" in line_map


def test_python_contract_inference_preserves_bool_return_type() -> None:
    """Python ``-> bool`` annotations must map to Mumei ``bool``."""
    from agent.cross_validation_foreign import _infer_python_contracts

    source = "def is_true() -> bool:\n    return True\n"
    atoms = _infer_python_contracts(source)
    assert atoms[0].return_type == "bool"
    # ``True`` is normalized to mumei's canonical ``true`` boolean literal.
    assert "result == true" in atoms[0].ensures


def test_python_contract_inference_skips_overload_stubs() -> None:
    """Python ``@overload`` stubs and ``...`` bodies must not be inferred as atoms."""
    from agent.cross_validation_foreign import _infer_python_contracts

    source = (
        "from typing import overload\n"
        "@overload\n"
        "def f(x: int) -> int: ...\n"
        "@overload\n"
        "def f(x: str) -> str: ...\n"
        "def f(x):\n"
        "    return x\n"
    )
    atoms = _infer_python_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "f"
    assert atoms[0].ensures == "result == x"


def test_python_contract_inference_includes_class_methods_and_skips_self() -> None:
    """Python class methods and async methods must be inferable, with self/cls skipped."""
    from agent.cross_validation_foreign import _infer_python_contracts

    source = (
        "class Series:\n"
        "    @property\n"
        "    def name(self) -> str:\n"
        "        return self._name\n"
        "    @name.setter\n"
        "    def name(self, value: str) -> None:\n"
        "        self._name = value\n"
        "    @staticmethod\n"
        "    def static_name(x: int) -> int:\n"
        "        return x\n"
        "    @classmethod\n"
        "    def from_dict(cls, d: dict) -> 'Series':\n"
        "        return cls(d)\n"
        "    async def refresh(self) -> bool:\n"
        "        return True\n"
        "\n"
        "def top(x: int) -> int:\n"
        "    return x\n"
    )
    atoms = _infer_python_contracts(source)
    names = [atom.name for atom in atoms]
    assert "name" in names
    assert "static_name" in names
    assert "from_dict" in names
    assert "refresh" in names
    assert "top" in names

    name_getter = [atom for atom in atoms if atom.name == "name" and not atom.params][0]
    assert name_getter.return_type == "string"
    assert name_getter.ensures == "result == self._name"

    static = [atom for atom in atoms if atom.name == "static_name"][0]
    assert [p.name for p in static.params] == ["x"]

    from_dict = [atom for atom in atoms if atom.name == "from_dict"][0]
    assert [p.name for p in from_dict.params] == ["d"]

    refresh = [atom for atom in atoms if atom.name == "refresh"][0]
    assert refresh.return_type == "bool"
    assert not refresh.params


def test_solidity_contract_inference_preserves_bool_return_type() -> None:
    """Solidity ``returns (bool)`` must map to Mumei ``bool``."""
    from agent.cross_validation_foreign import _infer_solidity_contracts

    source = (
        "function isPositive(uint256 x) public pure returns (bool) {\n"
        "    return true;\n"
        "}\n"
    )
    atoms = _infer_solidity_contracts(source)
    assert atoms[0].return_type == "bool"
    assert atoms[0].ensures == "result == true"


def test_solidity_contract_inference_balances_function_type_params() -> None:
    """Function-type parameters must not stop the top-level parameter parser early."""
    from agent.cross_validation_foreign import _infer_solidity_contracts

    source = (
        "function sort(\n"
        "    bytes32[] memory array,\n"
        "    function(bytes32, bytes32) pure returns (bool) comp\n"
        ") internal pure returns (bytes32[] memory) {\n"
        "    return array;\n"
        "}\n"
    )
    atoms = _infer_solidity_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "sort"
    assert atoms[0].return_type == "i64"
    assert [p.name for p in atoms[0].params] == ["array", "comp"]
    assert atoms[0].ensures == "result == array"


def test_solidity_interface_functions_are_extracted_as_trusted_atoms() -> None:
    """Solidity interface declarations without a body must still produce atoms."""
    from agent.cross_validation_foreign import _infer_solidity_contracts

    source = (
        "interface IERC2981 {\n"
        "    function royaltyInfo(uint256 tokenId, uint256 salePrice)\n"
        "        external view returns (address receiver, uint256 royaltyAmount);\n"
        "}\n"
    )
    atoms = _infer_solidity_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "royaltyInfo"
    assert atoms[0].requires == "true"
    assert atoms[0].ensures == "true"
    assert [p.name for p in atoms[0].params] == ["tokenId", "salePrice"]


def test_typescript_source_line_map_includes_class_methods() -> None:
    """TypeScript class methods must be present in the source-line map."""
    from agent.cross_validation_foreign import _infer_foreign_source_line_map

    source = (
        "export class StreamingApi {\n"
        "  async write(input: Uint8Array | string): Promise<StreamingApi> {\n"
        "    return this\n"
        "  }\n"
        "  abort() {\n"
        "    this.aborted = true\n"
        "  }\n"
        "  private static async bar(x: number) {\n"
        "    return x\n"
        "  }\n"
        "}\n"
    )
    line_map = _infer_foreign_source_line_map(source, "typescript")
    assert "write" in line_map
    assert "abort" in line_map
    assert "bar" in line_map


def test_validate_foreign_code_void_functions_use_unit_body() -> None:
    """Void foreign functions must produce a unit return type and a unit body."""
    from agent.cross_validation import validate_foreign_code
    from agent.config import AgentConfig

    result = validate_foreign_code(
        "package demo\nfunc noop() {}\n",
        "go",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )
    assert result.success is True
    assert "-> ()" in result.mumei_source
    assert "body: {\n        ()" in result.mumei_source


def test_python_unannotated_bool_return_type() -> None:
    """Unannotated Python functions returning ``True``/``False`` must map to ``bool``."""
    from agent.cross_validation_foreign import _infer_python_contracts

    atoms = _infer_python_contracts("def is_true():\n    return True\n")
    assert atoms[0].return_type == "bool"
    # ``True`` is normalized to mumei's canonical ``true`` boolean literal.
    assert "result == true" in atoms[0].ensures


def test_python_unannotated_comparison_return_type() -> None:
    """Unannotated Python comparison returns must map to ``bool``."""
    from agent.cross_validation_foreign import _infer_python_contracts

    atoms = _infer_python_contracts("def is_positive(x):\n    return x > 0\n")
    assert atoms[0].return_type == "bool"


def test_python_unannotated_isinstance_return_type() -> None:
    """Unannotated Python ``isinstance`` calls return ``bool``."""
    from agent.cross_validation_foreign import _infer_python_contracts

    atoms = _infer_python_contracts("def is_int(x):\n    return isinstance(x, int)\n")
    assert atoms[0].return_type == "bool"


def test_python_unannotated_string_return_type() -> None:
    """Unannotated Python string constants return ``string``."""
    from agent.cross_validation_foreign import _infer_python_contracts

    atoms = _infer_python_contracts("def greeting():\n    return 'hi'\n")
    assert atoms[0].return_type == "string"


def test_python_unannotated_float_return_uses_float_body() -> None:
    """Unannotated Python float returns must map to ``f64`` and a ``0.0`` body."""
    from agent.cross_validation import validate_foreign_code
    from agent.config import AgentConfig

    result = validate_foreign_code(
        "def pi():\n    return 3.14\n",
        "python",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )
    assert result.success is True
    assert "-> f64" in result.mumei_source
    assert "body: {\n        0.0" in result.mumei_source


def test_python_return_type_inference_ignores_nested_function_returns() -> None:
    """Return statements from nested functions must not influence the outer function."""
    from agent.cross_validation_foreign import _infer_python_contracts

    source = (
        "def setup():\n"
        "    def callback():\n"
        "        return True\n"
    )
    atoms = _infer_python_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "setup"
    assert atoms[0].return_type == "()"
    assert "result == True" not in atoms[0].ensures


def test_python_return_type_inference_with_nested_and_outer_returns() -> None:
    """Outer returns take precedence when a nested function has a different type."""
    from agent.cross_validation_foreign import _infer_python_contracts

    source = (
        "def outer():\n"
        "    def inner():\n"
        "        return 42\n"
        "    return True\n"
    )
    atoms = _infer_python_contracts(source)
    outer = [atom for atom in atoms if atom.name == "outer"][0]
    assert outer.return_type == "bool"


def test_rust_contract_inference_handles_nested_generics_and_lifetimes() -> None:
    """Rust generics with nested ``<>`` and lifetimes must be parsed correctly."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = (
        "pub async fn await_scoped_vec<F: Future<Output = T> + Send, T: Send + 'static>(\n"
        "    f: impl IntoIterator<Item = F>,\n"
        ") -> Result<Vec<T>, JoinError> {\n"
        "    unsafe { TokioScope::scope_and_collect(|scope| { f.into_iter().map(|f| scope.spawn(f)).collect::<Vec<_>>() }) }\n"
        "        .await\n"
        "        .1\n"
        "        .into_iter()\n"
        "        .collect::<Result<Vec<_>, _>>()\n"
        "}\n"
    )
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "await_scoped_vec"
    assert atoms[0].return_type == "i64"
    assert any(param.name == "f" for param in atoms[0].params)


def test_rust_contract_inference_handles_fn_trait_bound_arrow() -> None:
    """The ``->`` arrow in ``FnOnce() -> T`` bounds must not close the generic list."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = (
        "pub async fn await_blocking<F: FnOnce() -> T + Send, T: Send + 'static>(f: F) -> Result<T, JoinError> {\n"
        "    unsafe { TokioScope::scope_and_collect(|scope| scope.spawn_blocking(f)) }.await.1.pop().unwrap()\n"
        "}\n"
    )
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "await_blocking"
    assert atoms[0].return_type == "i64"


def test_typescript_return_type_recognizes_type_predicates() -> None:
    """TypeScript ``value is SomeType`` and ``asserts`` return types map to ``bool``."""
    from agent.cross_validation_foreign import _typescript_return_type

    assert _typescript_return_type("obj is TokenHeader") == "bool"
    assert _typescript_return_type("value is string") == "bool"
    assert _typescript_return_type("asserts obj is SomeType") == "bool"


def test_typescript_raw_return_expression_captures_multiline_parenthesized_return() -> None:
    """A single parenthesised return expression that spans several lines is captured whole."""
    from agent.cross_validation_foreign import _typescript_raw_return_expression

    body = (
        "{\n"
        "  return (\n"
        "    'alg' in objWithAlg &&\n"
        "    true\n"
        "  )\n"
        "}"
    )
    expr = _typescript_raw_return_expression(body)
    assert "'alg' in objWithAlg" in expr
    assert expr.endswith(")")


def test_typescript_raw_return_expression_returns_empty_for_multiple_returns() -> None:
    """Multiple top-level returns do not have a single deterministic postcondition."""
    from agent.cross_validation_foreign import _typescript_raw_return_expression

    body = "{\n  if (x) { return 1; }\n  return 2;\n}"
    assert _typescript_raw_return_expression(body) == ""


def test_typescript_contract_inference_balances_body_with_type_literal() -> None:
    """Nested type literals and ``if``/``return`` branches must not truncate the body
    or produce a contradictory ``result == false`` postcondition.
    """
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = (
        "export function isTokenHeader(obj: unknown): obj is TokenHeader {\n"
        "  if (typeof obj === 'object' && obj !== null) {\n"
        "    const objWithAlg = obj as { [key: string]: unknown }\n"
        "    return (\n"
        "      'alg' in objWithAlg &&\n"
        "      true\n"
        "    )\n"
        "  }\n"
        "  return false\n"
        "}\n"
    )
    atoms = _infer_typescript_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].return_type == "bool"
    assert atoms[0].ensures == "true"


def test_typescript_contract_inference_extracts_class_methods() -> None:
    """Class methods without the ``function`` keyword must be inferable as atoms."""
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = (
        "export class StreamingApi {\n"
        "  async write(input: Uint8Array | string): Promise<StreamingApi> {\n"
        "    return this\n"
        "  }\n"
        "  abort() {\n"
        "    this.aborted = true\n"
        "  }\n"
        "  private static async bar(x: number) {\n"
        "    return x\n"
        "  }\n"
        "}\n"
    )
    atoms = _infer_typescript_contracts(source)
    names = {atom.name for atom in atoms}
    assert "write" in names
    assert "abort" in names
    assert "bar" in names


def test_typescript_contract_inference_class_method_with_callback_param_type() -> None:
    """A ``=>`` inside a class-method parameter type must not be mistaken for an arrow body."""
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = (
        "class Api {\n"
        "  onAbort(listener: () => void | Promise<void>) {\n"
        "    this.subscribers.push(listener)\n"
        "  }\n"
        "}\n"
    )
    atoms = _infer_typescript_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "onAbort"
    assert atoms[0].ensures == "true"


def test_typescript_contract_inference_extracts_generic_arrow_functions() -> None:
    """Generic arrow functions like ``const f = <T>(x: T) => ...`` must produce atoms."""
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = (
        "export const create = <T>(value: T): T => {\n"
        "  const boxed = { value }\n"
        "  return boxed.value\n"
        "}\n"
    )
    atoms = _infer_typescript_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "create"
    assert [p.name for p in atoms[0].params] == ["value"]
    assert atoms[0].return_type == "i64"


def test_typescript_arrow_functions_dedup_with_non_ascii_prefix() -> None:
    """Top-level arrow functions must not be duplicated when non-ASCII characters precede them."""
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = (
        '// コメント\n'
        'const double = (x: number): number => x * 2\n'
    )
    atoms = _infer_typescript_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "double"
    assert [p.name for p in atoms[0].params] == ["x"]


def test_typescript_contract_inference_extracts_unparenthesized_arrow_functions() -> None:
    """Single-parameter arrow functions without parentheses must keep their parameter."""
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = "const inc = x => x + 1\n"
    atoms = _infer_typescript_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "inc"
    assert [p.name for p in atoms[0].params] == ["x"]
    assert atoms[0].ensures == "result == x + 1"


def test_typescript_raw_return_expression_ignores_nested_callback_returns() -> None:
    """A ``return`` inside a nested callback arrow function must not be counted as a top-level return."""
    from agent.cross_validation_foreign import _typescript_raw_return_expression

    body = (
        "{\n"
        "  items.forEach((item) => { return item * 2; });\n"
        "  return items.length;\n"
        "}"
    )
    expr = _typescript_raw_return_expression(body)
    assert "items.length" in expr


def test_typescript_contract_inference_ignores_nested_function_returns() -> None:
    """A ``return`` inside a nested ``function`` declaration must not be counted as a top-level return."""
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = (
        "export function outer(items: number[]): number {\n"
        "  function inner(x: number): number {\n"
        "    return x * 2;\n"
        "  }\n"
        "  return items.map(inner).length;\n"
        "}\n"
    )
    atoms = _infer_typescript_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].name == "outer"
    assert "items_map(inner).length" in atoms[0].ensures


def test_last_expression_ignores_leading_dot_numeric_literal() -> None:
    """A bare ``.0`` tuple-field/method-chain fragment must not be returned as the tail expression.

    ``.0`` is valid Python syntax for the float literal ``0.0``, but in Rust it is a
    fragment of a multi-line method/tuple chain such as
    ``std::mem::take(...).0.into_iter()...``. The line-based tail-expression scanner
    must not treat it as a complete return expression.
    """
    from agent.cross_validation_foreign import _last_expression

    body = (
        "Box::new(self.index.into_iter().enumerate().filter(|(_, i)| *i != NO_PAGE).flat_map(\n"
        "    move |(i, index)| {\n"
        "        let upper = i << LOG_PAGE_LEN;\n"
        "        std::mem::take(&mut self.page_table[index as usize])\n"
        "            .0\n"
        "            .into_iter()\n"
        "            .enumerate()\n"
        "            .filter_map(move |(lower, v)| {\n"
        "                v.map(|v| (Self::decompress_addr(upper + lower), v))\n"
        "            })\n"
        "    },\n"
        "))\n"
    )
    assert _last_expression(body) == ""


def test_last_expression_skips_return_inside_nested_closures() -> None:
    """``return`` statements inside closures/blocks must not be mistaken for the function tail."""
    from agent.cross_validation_foreign import _last_expression

    body = (
        "if code.is_empty() { return None; }\n"
        "let mut partial_match = None;\n"
        "self.iter()\n"
        "    .find(|(_, contract)| {\n"
        "        let Some(deployed_code) = &contract.deployed_bytecode else {\n"
        "            return false;\n"
        "        };\n"
        "        false\n"
        "    })\n"
        "    .or(partial_match)\n"
    )
    # The tail is a multi-line method chain that cannot be captured as a single line;
    # the nested ``return false`` must not be used as ``result == false``.
    assert _last_expression(body) == ""


def test_last_expression_ignores_braces_inside_string_literals() -> None:
    """Braces inside string/char literals must not corrupt depth tracking."""
    from agent.cross_validation_foreign import _last_expression

    body = (
        'let msg = "}";\n'
        "for x in v {\n"
        "    return 3;\n"
        "}\n"
        "0\n"
    )
    # The real tail is the final ``0`` on the top level, not the nested ``return 3``.
    assert _last_expression(body) == "0"


# --------------------------------------------------------------------------- #
# Layer B stage 2: syntax-tree expression analysis (with regex fallback)
# --------------------------------------------------------------------------- #


def test_syntax_tree_ignores_operators_inside_string_literal() -> None:
    """`/`, `[`, `+` inside a Solidity string literal are not real operators."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    issues = _issues_for_expression("f", 'concat("a/b", "c[d]", "e+f")', "Solidity")
    assert issues == []


def test_syntax_tree_ignores_operators_inside_comment() -> None:
    """Operators inside a Rust line comment must not trigger safety issues."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    issues = _issues_for_expression("f", "g() // a / b + c and d[e]", "Rust")
    assert issues == []


def test_syntax_tree_handles_nested_indexing() -> None:
    """`a[b[c]]` yields bounds for the real index `c < len_b`, not `b < len_a`."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    issues = [i for i in _issues_for_expression("f", "a[b[c]]", "Rust") if "can index" in i.message]
    contracts = {contract for issue in issues for contract in issue.required_contracts}
    assert "c < len_b" in contracts
    assert not any("len_a" in contract for contract in contracts)


def test_syntax_tree_method_chain_operator_not_division() -> None:
    """`obj.a / obj.b` divides by a member access, not a free variable `b`/`a`."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    issues = _issues_for_expression("f", "obj.a / obj.b", "Rust")
    assert not any("divide by" in issue.message for issue in issues)

    real = _issues_for_expression("f", "a / b", "Rust")
    assert any("divide by `b`" in issue.message for issue in real)


def test_syntax_tree_addition_inside_index_and_call_receiver() -> None:
    """Additions embedded in a call receiver are excluded from overflow bounds."""
    from agent.cross_validation_foreign import _integer_overflow_requires_for_expression

    # `a + b.method()` -> `b` is a receiver, so no overflow pair is emitted.
    assert _integer_overflow_requires_for_expression("a + b.method()", "rust") == []


def test_regex_fallback_used_when_tree_sitter_unavailable(monkeypatch) -> None:
    """With tree-sitter forced unavailable, the regex heuristics still fire."""
    import agent.cross_validation_foreign as cvf
    import agent.strategies.foreign_code_strategy_helpers as helpers
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    monkeypatch.setattr(cvf.tree_sitter_extract, "analyze_expression", lambda *a, **k: None)
    monkeypatch.setattr(helpers.tree_sitter_extract, "analyze_expression", lambda *a, **k: None)

    issues = _issues_for_expression("f", "a / b", "Rust")
    assert any("divide by `b`" in issue.message for issue in issues)

    idx = _issues_for_expression("f", "values[idx]", "Go")
    assert any("can index `values[idx]`" in issue.message for issue in idx)

    reqs = cvf._integer_overflow_requires_for_expression("a + b", "rust")
    assert any("a + b <=" in req for req in reqs)


def test_regex_fallback_matches_tree_sitter_for_multilanguage(monkeypatch) -> None:
    """The tree-sitter and regex paths agree on canonical safety requirements."""
    import agent.cross_validation_foreign as cvf

    assert cvf._safety_requires_for_expression("values[idx]", "go") == (
        "idx >= 0 && idx < len_values"
    )
    assert cvf._safety_requires_for_expression("a / b", "rust") == "b != 0"

    monkeypatch.setattr(cvf.tree_sitter_extract, "analyze_expression", lambda *a, **k: None)
    assert cvf._safety_requires_for_expression("values[idx]", "go") == (
        "idx >= 0 && idx < len_values"
    )
    assert cvf._safety_requires_for_expression("a / b", "rust") == "b != 0"


def test_normalize_foreign_expression_strips_trailing_line_comments() -> None:
    """Trailing ``//`` comments must not leak into Mumei contract clauses."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert _normalize_foreign_expression("x > 0 // always positive") == "(x > 0)"


def test_normalize_foreign_expression_preserves_comment_markers_inside_strings() -> None:
    """``//`` or ``/*`` inside string literals must not be treated as comments."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert _normalize_foreign_expression('"a // b"') == '"a // b"'
    assert _normalize_foreign_expression("'/* not a comment */'") == "'/* not a comment */'"


def test_normalize_foreign_expression_strips_block_comments() -> None:
    """``/* ... */`` block comments must be removed before Mumei normalization."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert _normalize_foreign_expression("x + 1 /* increment */ > 0") == "(x + 1  > 0)"


def test_normalize_foreign_expression_preserves_regex_literals_with_slashes() -> None:
    """JS/TS regex literals containing ``/`` must not be truncated as ``//`` comments."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert _normalize_foreign_expression("str.replace(/\\//g, '_')") == "str_replace(/\\//g, '_')"
    assert _normalize_foreign_expression("str.replace(/_|_/g, '_')") == "str_replace(/_|_/g, '_')"
    assert _normalize_foreign_expression("x / /a/g") == "x / /a/g"


def test_normalize_foreign_expression_does_not_treat_division_as_regex() -> None:
    """Ordinary division ``a / b`` must not be consumed as a regex literal."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert _normalize_foreign_expression("a / b") == "a / b"
    assert _normalize_foreign_expression("(a + b) / c") == "(a + b) / c"


def test_normalize_foreign_expression_parenthesizes_comparisons() -> None:
    """Comparison expressions that feed ``result == ...`` must be grouped."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert _normalize_foreign_expression("i > i0") == "(i > i0)"
    assert _normalize_foreign_expression("a && b") == "(a and b)"


def test_normalize_foreign_expression_coerces_typeof_and_string_literals() -> None:
    """``typeof`` and string-literal comparisons are coerced to ``true``."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert (
        _normalize_foreign_expression("typeof value === 'object' && value !== null")
        == "(value != null)"
    )
    assert _normalize_foreign_expression("x == 'foo'") == "true"


def test_normalize_foreign_expression_rewrites_bit_shifts() -> None:
    """Bit shifts are rewritten to exponentiation so Mumei can lower them."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert _normalize_foreign_expression("1 << n") == "(1 * 2**n)"
    assert _normalize_foreign_expression("x >> k") == "(x / 2**k)"


def test_typescript_contract_inference_strips_trailing_comments() -> None:
    """Arrow-function expression bodies with trailing line comments must not include the comment in ``ensures``."""
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = (
        "const isRaw = (request: unknown): request is Request => 'headers' in request // comment\n"
    )
    atoms = _infer_typescript_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].ensures == "true"


def test_go_contract_inference_skips_blank_identifier_and_test_entry_points() -> None:
    """Go blank-identifier compile checks and test entry points must not become atoms."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = (
        "package ent\n"
        "func _() {}\n"
        "func TestFoo(t *testing.T) {}\n"
        "func BenchmarkBar(b *testing.B) {}\n"
        "func String() string { return \"\" }\n"
    )
    atoms = _infer_go_contracts(source)
    names = {atom.name for atom in atoms}
    assert names == {"String"}


def test_go_source_line_map_skips_blank_identifier_and_test_entry_points() -> None:
    """The Go source line map must also exclude test entry points and the blank identifier."""
    from agent.cross_validation_foreign import _infer_foreign_source_line_map

    source = (
        "package ent\n"
        "func _() {}\n"
        "func TestFoo() {}\n"
        "func String() string { return \"\" }\n"
    )
    line_map = _infer_foreign_source_line_map(source, "go")
    assert "String" in line_map
    assert "cross_validation_atom" not in line_map
    assert "TestFoo" not in line_map


def test_rust_contract_inference_skips_test_attribute_functions() -> None:
    """Rust functions annotated with ``#[test]`` or ``#[bench]`` must not become atoms."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = (
        "#[cfg(test)]\n"
        "mod tests {\n"
        "    #[test]\n"
        "    fn calc_mean_empty() {}\n"
        "    #[bench]\n"
        "    fn bench_foo() {}\n"
        "    #[test]\n"
        "    #[should_panic]\n"
        "    fn ignored_test() {}\n"
        "}\n"
        "pub fn mean() -> u64 { 0 }\n"
    )
    atoms = _infer_rust_contracts(source)
    names = {atom.name for atom in atoms}
    assert names == {"mean"}


def test_verifier_treats_solidity_struct_only_as_no_functions() -> None:
    """Issue 1: struct-only Solidity files should not produce a verification error."""
    source = """pragma solidity >=0.6.2;

struct PoolKey {
    address currency0;
    address currency1;
    uint24 fee;
    int24 tickSpacing;
    address hooks;
}
"""
    result = ForeignCodeVerifier(mumei_bin="mumei").verify(source, "solidity")
    assert result["success"] is True
    assert result["errors"] == []
    assert result["verification"] is not None
    assert any("No function signatures were extracted" in w for w in result["warnings"])


def test_source_has_function_declarations() -> None:
    """_source_has_function_declarations correctly detects Solidity functions and struct-only sources."""
    from agent.strategies.foreign_code_strategy import _source_has_function_declarations

    assert _source_has_function_declarations("function f() {}", "solidity") is True
    assert (
        _source_has_function_declarations("struct S { uint x; }", "solidity") is False
    )
    assert _source_has_function_declarations("func F() {}", "go") is True
    assert _source_has_function_declarations("pub fn f() {}", "rust") is True
    assert _source_has_function_declarations("func TestFoo(t *testing.T) {}", "go") is False
    assert _source_has_function_declarations("func fuzzCopies[T any](t *testing.T, obj T) {}", "go") is False
    assert _source_has_function_declarations("// errorcheck\nfunc f() {}", "go") is False
    assert (
        _source_has_function_declarations("#[test]\nfn foo() {}", "rust") is False
    )
    assert (
        _source_has_function_declarations("#[test_log::test]\nfn foo() {}", "rust")
        is False
    )
    assert _source_has_function_declarations("#[test]\nfn foo() {}\nfn bar() {}", "rust") is True


def test_contract_lines_filters_go_human_language_preconditions() -> None:
    """Natural-language Go preconditions are lowered to true instead of invalid Mumei."""
    from agent.strategies.foreign_code_strategy_helpers import _contract_lines

    comment = "Precondition: the Types, Uses and Defs maps are populated."
    preconditions, _ = _contract_lines(comment)
    assert preconditions == ["true"]

    comment = "Precondition: path must not be empty."
    preconditions, _ = _contract_lines(comment)
    assert preconditions == ["true"]


def test_normalize_foreign_expression_coerces_undefined_and_bang() -> None:
    """``undefined`` comparisons and prefix ``!`` lower to Mumei booleans."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert (
        _normalize_foreign_expression("x !== undefined && !x")
        == "(x == false)"
    )
    assert _normalize_foreign_expression("x === undefined") == "false"
    assert _normalize_foreign_expression("x != undefined") == "true"


def test_typescript_return_type_infers_boolean_from_expression() -> None:
    """Arrow functions without an explicit return type are inferred as ``bool`` when appropriate."""
    from agent.cross_validation_foreign import _typescript_return_type

    assert _typescript_return_type("number", "typeof x !== 'undefined'") == "bool"
    assert _typescript_return_type("", "a > 0 && b < 10") == "bool"
    assert _typescript_return_type("number", "Array.from(...).filter(...)") == "i64"
    assert _typescript_return_type("number", "x + 1") == "i64"


def test_generic_safety_requires_skips_typescript_divisors() -> None:
    """JS/TS ``/`` and ``%`` by zero are not exceptions and must not add ``divisor != 0``."""
    from agent.cross_validation_foreign import _generic_safety_requires_for_expression

    assert _generic_safety_requires_for_expression("a / b", language="typescript") == []
    assert _generic_safety_requires_for_expression("a % b", language="javascript") == []
    assert _generic_safety_requires_for_expression("a / b", language="go") == ["b != 0"]


def test_ensures_for_return_expression_falls_back_for_strings() -> None:
    """String and compound boolean return expressions cannot be lowered, so ``ensures`` falls back to ``true``."""
    from agent.cross_validation_foreign import _ensures_for_return_expression

    assert _ensures_for_return_expression('"/" + suffix', "string") == "true"
    # Mumei's vacuity-check lowerer only supports ``result == <bool var/lit>``.
    assert _ensures_for_return_expression("(x > 0)", "bool") == "true"
    assert _ensures_for_return_expression("(x and y)", "bool", {"x", "y"}) == "true"
    assert _ensures_for_return_expression("x", "bool", {"x"}) == "result == x"
    assert _ensures_for_return_expression("true", "bool") == "result == true"


def test_ensures_for_return_expression_falls_back_for_unknown_field_access() -> None:
    """Boolean field accesses on parameters cannot be lowered, so ``ensures`` falls back to ``true``."""
    from agent.cross_validation_foreign import _ensures_for_return_expression

    assert _ensures_for_return_expression("(role_delegatable == false)", "bool", {"role"}) == "true"
    # Known property/method names and method calls are still lowerable.
    assert _ensures_for_return_expression("items_map(inner).length", "i64", {"items"}) == "result == items_map(inner).length"
    assert _ensures_for_return_expression("fork_HashTreeRoot()", "i64", {"fork"}) == "result == fork_HashTreeRoot()"


def test_ensures_for_return_expression_falls_back_for_ternary_and_closures() -> None:
    """Ternary and arrow-function return bodies cannot be lowered, so ``ensures`` is ``true``."""
    from agent.cross_validation_foreign import _ensures_for_return_expression

    assert _ensures_for_return_expression("zeroForOne ? a : b", "i64", {"zeroForOne"}) == "true"
    assert _ensures_for_return_expression("queries_some((q) => len_entries > 0)", "bool", {"queries"}) == "true"


def test_ensures_for_return_expression_falls_back_for_map_index() -> None:
    """Go map key access cannot be lowered to a Mumei equality."""
    from agent.cross_validation_foreign import _ensures_for_return_expression

    assert _ensures_for_return_expression("m[s]", "i64", {"m", "s"}, param_types={"m": "map[string]int"}) == "true"
    assert _ensures_for_return_expression("(*m)[s]", "i64", {"m", "s"}, param_types={"m": "*map[string]int"}) == "true"


def test_ensures_for_return_expression_falls_back_for_multi_declared_local() -> None:
    """A return of a multi-variable short-declaration local should not be lowered."""
    from agent.cross_validation_foreign import _ensures_for_return_expression, _local_variable_names

    body = '''
func QueryBool(name string) bool {
    v, _ := strconv.ParseBool(name)
    return v
}
'''
    local_names = _local_variable_names(body, "go")
    assert "v" in local_names
    assert _ensures_for_return_expression("v", "bool", {"name"}, local_names=local_names) == "true"


def test_is_expression_lowerable_rejects_jsx() -> None:
    """JSX/TSX element literals cannot be lowered into Mumei equalities."""
    from agent.cross_validation_foreign import _is_expression_lowerable

    assert _is_expression_lowerable("(<Component prop={x} />", {"x"}) is False
    assert _is_expression_lowerable("x + 1", {"x"}) is True


def test_raw_return_statement_expression_handles_multiline_ternary() -> None:
    """Multi-line Solidity/TypeScript ternary returns must be captured in full."""
    from agent.cross_validation_foreign import _raw_return_statement_expression

    source = '''{
        return zeroForOne
            ? getNextSqrtPriceFromAmount0RoundingUp(s, l, a, true)
            : getNextSqrtPriceFromAmount1RoundingDown(s, l, a, true);
    }'''
    expr = _raw_return_statement_expression(source)
    assert "?" in expr and ":" in expr


def test_normalize_bitwise_and_and_inline_constants() -> None:
    """Solidity ``&`` rewrites to ``bit_and`` and constants are inlined."""
    from agent.cross_validation_foreign import _normalize_foreign_expression, _normalize_bitwise_and

    assert _normalize_foreign_expression("self & OVERRIDE_FEE_FLAG != 0", {"OVERRIDE_FEE_FLAG": 0x400000}) == "(bit_and(self, 4194304) != 0)"
    assert _normalize_foreign_expression("self & REMOVE_OVERRIDE_MASK", {"REMOVE_OVERRIDE_MASK": 0xBFFFFF}) == "bit_and(self, 12582911)"
    # Chained ``&`` and parenthesised operands must also collapse to nested bit_and.
    assert _normalize_bitwise_and("a & b & c") == "bit_and(bit_and(a, b), c)"
    assert _normalize_bitwise_and("(a & b) & c") == "bit_and(bit_and(a, b), c)"


def test_extract_go_unicode_identifier() -> None:
    """Go identifiers containing non-ASCII letters are extracted and audited."""
    from agent.strategies.foreign_code_strategy import ForeignCodeExtractor

    source = """package þfoo

var þbarV int = 101

func þbar(x int) int {
    defer func() { þbarV += 3 }()
    return þblix(x)
}

func þblix(x int) int {
    defer func() { þbarV += 9 }()
    return þbarV + x
}
"""

    specs = ForeignCodeExtractor().extract_go(source)
    names = {s.function_name for s in specs}
    assert names == {"þbar", "þblix"}


def test_extract_go_caller_contracts_from_doc() -> None:
    """Go doc comments such as ``r must not be empty`` are turned into ``requires r != nil``."""
    from agent.strategies.foreign_code_strategy import _extract_go_caller_contracts

    assert _extract_go_caller_contracts("Next returns the next ring element. r must not be empty.") == ["r != nil"]
    assert _extract_go_caller_contracts("Move moves the ring. r must not be nil.") == ["r != nil"]
    assert _extract_go_caller_contracts("No contract here.") == []


def test_go_nil_guarded_return_values() -> None:
    """``if x == nil { return }`` should prevent spurious nil-deref issues on the final return."""
    from agent.strategies.foreign_code_strategy_helpers import _go_nil_guarded_return_values

    assert _go_nil_guarded_return_values("if fork == nil { return [] } return fork.HashTreeRoot()") == {"fork"}
    assert _go_nil_guarded_return_values("if x != nil { return x } return y") == set()


def test_normalize_foreign_expression_inlines_go_char_literals() -> None:
    """Go rune literals are lowered to integer code points for Mumei."""
    from agent.cross_validation_foreign import _normalize_foreign_expression

    assert _normalize_foreign_expression("'A'", language="go") == "65"
    assert _normalize_foreign_expression("c >= 'A' && c <= 'Z'", language="go") == "(c >= 65 and c <= 90)"


def test_local_variable_names_detects_single_letter_locals() -> None:
    """Single-letter locals declared with var/let/const must be recognised."""
    from agent.cross_validation_foreign import _local_variable_names

    assert _local_variable_names("var m = regMask{}", "go") == {"m"}
    assert _local_variable_names("let m = 1;", "rust") == {"m"}
    assert _local_variable_names("const m = 0;", "typescript") == {"m"}
    assert _local_variable_names("uint m = 0;", "solidity") == {"m"}


def test_raw_return_statement_expression_masks_nested_go_function_literals() -> None:
    """Returns inside nested closures must not leak into the outer function."""
    from agent.cross_validation_foreign import _raw_return_statement_expression, _all_return_expressions

    body = 'sort.Slice(deps, func(i, j int) bool { return deps[i].order() < deps[j].order() })\nreturn nil'
    assert _raw_return_statement_expression(body, "go") == "nil"
    assert _all_return_expressions(body, "go") == ["nil"]


def test_raw_return_statement_expression_ignores_func_type_fields() -> None:
    """String contents next to a ``func`` type field must not be parsed as a return."""
    from agent.cross_validation_foreign import _raw_return_statement_expression

    body = '''tests := []struct {
        name      string
        callback  func(string) error
    }{
        {
            name: "does not return deleted object",
        },
    }
    return true
'''
    assert _raw_return_statement_expression(body, "go") == "true"


def test_all_return_expressions_stops_at_case_labels() -> None:
    """Go ``switch`` ``case`` / ``default`` labels terminate a return expression."""
    from agent.cross_validation_foreign import _all_return_expressions

    body = """switch x {
case 1:
    return 1
case 2:
    if y {
        return 2
    }
default:
    return 3
}
return 0"""
    assert _all_return_expressions(body, "go") == ["1", "2", "3", "0"]


def test_all_return_expressions_does_not_chop_case_suffixed_identifiers() -> None:
    """Return values whose names contain ``case`` or ``default`` are not truncated."""
    from agent.cross_validation_foreign import _all_return_expressions

    body = """switch x {
case 1:
    return lowercase
case 2:
    return snake_case
}
return is_default"""
    assert _all_return_expressions(body, "go") == ["lowercase", "snake_case", "is_default"]


def test_infer_go_contracts_ignores_comments_in_switch_cases() -> None:
    """Comments with ``/`` inside a switch case must not produce spurious divisors."""
    from agent.cross_validation_foreign import _infer_go_contracts

    source = '''package demo
func f(x int) int {
    switch x {
    case 1:
        // See: https://example.org/p/path
        return 1
    default:
        return 0
    }
}
'''
    atoms = _infer_go_contracts(source)
    f_atom = next(a for a in atoms if a.name == "f")
    assert f_atom.requires == "true"


def test_detect_go_safety_issues_skips_sort_interface_index_bounds() -> None:
    """sort.Interface Less/Swap parameters are guaranteed in-bounds by the caller."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''
package demo
type byPos struct{ a []*T }
func (x byPos) Less(i, j int) bool { return x.a[i].Pos() < x.a[j].Pos() }
'''
    issues = _detect_go_safety_issues(source)
    assert not any("index" in issue.message for issue in issues)


def test_issues_for_expression_respects_nonzero_guard() -> None:
    """A preceding ``rate > 0`` guard suppresses divide-by-zero on ``rate``."""
    from agent.strategies.foreign_code_strategy_helpers import _issues_for_expression

    expr = "rate > 0 && cheaprandu64()%rate == 0"
    issues = _issues_for_expression("Sample", expr, "Go")
    assert not any("divide" in issue.message.lower() for issue in issues)


def test_guaranteed_nonzero_with_no_spaces_around_operator() -> None:
    """Short-circuit guard detection must work without whitespace around ``&&``."""
    from agent.strategies.foreign_code_strategy_helpers import _guaranteed_nonzero_in_expression

    assert "rate" in _guaranteed_nonzero_in_expression("rate>0&&(cheaprandu64()%rate==0)")
    assert "x" in _guaranteed_nonzero_in_expression("(x!=0)&&(1/x)")


def test_i64_overflow_safety_issue_skips_pointer_arithmetic() -> None:
    """Pointer conversions such as ``muintptr(x + y)`` should not emit i64 overflow issues."""
    from agent.strategies.foreign_code_strategy_helpers import _i64_overflow_safety_issue

    assert _i64_overflow_safety_issue("WaitListHead", "highBits", "mutexMOffset", "Go", "muintptr(highBits + mutexMOffset)") is None


def test_is_expression_lowerable_rejects_multi_token_local_variables() -> None:
    """Expressions that reference local variables must not be lowered into postconditions."""
    from agent.cross_validation_foreign import _is_expression_lowerable

    assert _is_expression_lowerable("epochStart and altairEpoch", {"slot"}, local_names={"epochStart", "altairEpoch"}) is False
    assert _is_expression_lowerable("m > 0", set(), local_names={"m"}) is False


def test_is_expression_lowerable_rejects_object_literals() -> None:
    """Object literals cannot be lowered into a Mumei equality."""
    from agent.cross_validation_foreign import _is_expression_lowerable

    assert _is_expression_lowerable("{ a: 1, b: 2 }", {"x"}) is False


def test_is_expression_lowerable_rejects_method_access_on_index_results() -> None:
    """Method or field access on an index result cannot be lowered."""
    from agent.cross_validation_foreign import _is_expression_lowerable

    assert _is_expression_lowerable("ids[i].Pos() < ids[j].Pos()", {"ids", "i", "j"}) is False
    assert _is_expression_lowerable("slot + 1", {"slot"}, local_names=set()) is True


def test_extract_solidity_interface_as_trusted_atoms() -> None:
    """Solidity interfaces with no function body should be extracted as trusted specs."""
    from agent.strategies.foreign_code_strategy import ForeignCodeExtractor

    source = '''
interface IERC4626 {
    function asset() external view returns (address assetTokenAddress);
    function convertToShares(uint256 assets) external view returns (uint256 shares);
}
'''
    specs = ForeignCodeExtractor().extract_solidity(source)
    assert [s.function_name for s in specs] == ["asset", "convertToShares"]
    assert all(s.return_type == "i64" for s in specs if s.function_name == "asset")
    assert all(s.preconditions == [] for s in specs)


def test_go_method_receiver_type() -> None:
    """Receiver types are extracted from Go method parameter lists."""
    from agent.strategies.foreign_code_strategy_helpers import _go_method_receiver_type

    assert _go_method_receiver_type("f *durationOrCountFlag") == "*durationOrCountFlag"
    assert _go_method_receiver_type("b *B, n int") == "*B"
    assert _go_method_receiver_type("s string, n int") is None


def test_go_flag_value_receiver_types() -> None:
    """A type with String + Set methods and a pointer String receiver is recognised as flag.Value."""
    from agent.strategies.foreign_code_strategy_helpers import _go_flag_value_receiver_types

    class Fn:
        def __init__(self, name: str, params_text: str):
            self.name = name
            self.params_text = params_text

    functions = [
        Fn("String", "f *durationOrCountFlag"),
        Fn("Set", "f *durationOrCountFlag, s string"),
        Fn("String", "r BenchmarkResult"),
    ]
    assert _go_flag_value_receiver_types(functions) == {"*durationOrCountFlag"}


def test_i64_overflow_safety_issue_skips_local_variables() -> None:
    """Overflow checks cannot be expressed as preconditions on local variables."""
    from agent.strategies.foreign_code_strategy_helpers import _i64_overflow_safety_issue

    assert _i64_overflow_safety_issue("indexTagEnd", "res", "i", "Go", "res + i", local_names={"res", "i"}) is None


def test_go_method_receiver_helpers() -> None:
    """Receiver name/type extraction distinguishes methods from functions."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _go_method_receiver_name,
        _go_method_receiver_type,
    )

    assert _go_method_receiver_name("f *FlagSet") == "f"
    assert _go_method_receiver_type("f *FlagSet") == "*FlagSet"
    assert _go_method_receiver_name("name string, n int") is None
    assert _go_method_receiver_type("name string, n int") is None


def test_go_caller_contract_receiver_types_flagset() -> None:
    """flag.FlagSet is identified as a caller-contract receiver type."""
    from agent.strategies.foreign_code_strategy_helpers import _go_caller_contract_receiver_types

    source = "package flag\n\ntype FlagSet struct { formal map[string]*Flag }\n"
    assert _go_caller_contract_receiver_types(source) == {"FlagSet"}
    assert _go_caller_contract_receiver_types("package other\ntype FlagSet struct {}") == set()


def test_detect_go_safety_issues_suppresses_flagset_nil() -> None:
    """Nil-deref issues on *FlagSet methods are caller-contract false positives."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''
package flag

type FlagSet struct { formal map[string]*Flag }

func (f *FlagSet) Lookup(name string) *Flag {
    return f.formal[name]
}

func (f *FlagSet) Set(name, value string) error {
    flag := f.formal[name]
    _ = flag
    return nil
}
'''
    issues = _detect_go_safety_issues(source)
    assert all(i.function_name not in {"Lookup", "Set"} for i in issues)


def test_detect_go_safety_issues_suppresses_flag_value_get() -> None:
    """flag.Value Get methods are called by the flag package with non-nil receivers."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''
package flag

type boolValue bool

func (b *boolValue) Set(s string) error { *b = boolValue(s == "true"); return nil }
func (b *boolValue) String() string { return strconv.FormatBool(bool(*b)) }
func (b *boolValue) Get() any { return bool(*b) }
'''
    issues = _detect_go_safety_issues(source)
    assert not any(i.function_name in {"String", "Get"} for i in issues)


def test_detect_safety_issues_skips_generated_files() -> None:
    """Generated source files are not audited for safety issues."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '// Code generated by stringer; DO NOT EDIT.\n\nfunc (i Tag) String() string { return _Tag_index_0[i] }'
    assert _detect_safety_issues(source, "go") == []


def test_detect_safety_issues_skips_goexperiment_files() -> None:
    """Go files gated by ``goexperiment`` build tags are skipped on the production path."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """//go:build goexperiment.simd

package simd_test

func add[T number](x, y T) T { return x + y }
"""
    assert _detect_safety_issues(source, "go") == []


def test_detect_solidity_safety_issues_skips_mapping_key_access() -> None:
    """Solidity mapping key access is always safe and should not require index bounds."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''
pragma solidity ^0.8.0;

contract C {
    mapping(uint256 => uint256) private _values;

    function get(uint256 key) public view returns (uint256) {
        return _values[key];
    }
}
'''
    issues = _detect_safety_issues(source, "solidity")
    assert not any("_values" in i.message for i in issues)


def test_detect_solidity_safety_issues_default_checked_division_by_zero() -> None:
    """Solidity >=0.8 reverts on division by zero by default, so no contract is needed."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''
pragma solidity ^0.8.0;

contract C {
    function div(uint256 a, uint256 b) internal pure returns (uint256) {
        return a / b;
    }

    function mod(uint256 a, uint256 b) internal pure returns (uint256) {
        return a % b;
    }
}
'''
    issues = _detect_safety_issues(source, "solidity")
    assert not any("b" in i.message and "non-zero" in i.message for i in issues)


def test_detect_rust_safety_issues_static_str_return() -> None:
    """Rust functions returning ``&'static str`` should not produce int-ensures errors."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''
pub trait AsMetricStr {
    fn as_metric_str(&self) -> &\'static str;
}

impl AsMetricStr for X {
    fn as_metric_str(&self) -> &\'static str {
        "restore"
    }
}
'''
    issues = _detect_safety_issues(source, "rust")
    assert not any("restore" in i.message for i in issues)


def test_detect_go_safety_issues_top_nil_guarded_receiver() -> None:
    """Receivers checked with ``if s == nil { return }`` at the top are non-nil."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package models
type NotificationSettings struct{ a, b int }
func (s *NotificationSettings) Validate() error {
    if s == nil {
        return nil
    }
    if s.a != 0 && s.b != 0 {
        return nil
    }
    return nil
}
'''
    issues = _detect_go_safety_issues(source)
    assert not any("s" in i.message and "non-nil" in i.message for i in issues)


def test_detect_go_safety_issues_word_bits_nonzero() -> None:
    """Go word-size constant ``_W`` is always nonzero and should not trigger divide-by-zero checks."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package bigmod
func addMulVVW1024(z, x *uint, y uint) (c uint) {
    return addMulVVWWasm(z, x, y, 1024/_W)
}
func addMulVVWWasm(z, x *uint, y uint, n uintptr) (carry uint) { return 0 }
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("_W" in i.message and "non-zero" in i.message for i in issues)


def test_detect_ts_safety_issues_mask_nested_arrow_functions() -> None:
    """Nested arrow functions in a TypeScript object literal must not leak into the outer function."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''
export const getJoinByLabelsTransformer: () => any = () => ({
  id: 'joinByLabels',
  transformer: (options: any) => {
    return (data: any[]) => {
      if (!data || !data.length) {
        return data;
      }
      return [data.map((frame) => frame.refId).join('-')];
    };
  },
});
'''
    issues = _detect_safety_issues(source, "typescript")
    assert not any("data" in i.message for i in issues)


def test_detect_go_safety_issues_dual_len_loop_guarded() -> None:
    """``for i := 0; i < len(x) && i < len(y); i++`` guards both ``x[i]`` and ``y[i]``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package demo
func nameLess(x, y string) bool {
    for i := 0; i < len(x) && i < len(y); i++ {
        if x[i] != y[i] {
            return x[i] < y[i]
        }
    }
    return len(x) < len(y)
}
'''
    issues = _detect_go_safety_issues(source)
    assert not any("bounds" in i.message for i in issues)


def test_detect_go_safety_issues_binary_search_guarded() -> None:
    """Binary-search midpoint ``m`` indexing ``All[m]`` is bounded by ``len(All)``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package godebugs
var All []Info
type Info struct{ Name string }
func Lookup(name string) *Info {
    lo := 0
    hi := len(All)
    for lo < hi {
        m := int(uint(lo+hi) >> 1)
        mid := All[m].Name
        if name == mid {
            return &All[m]
        }
        if name < mid {
            hi = m
        } else {
            lo = m + 1
        }
    }
    return nil
}
'''
    issues = _detect_go_safety_issues(source)
    assert not any("bounds" in i.message for i in issues)


def test_detect_go_safety_issues_rand_modulo_param_nonzero() -> None:
    """A function returning ``randInt() % n`` implicitly requires ``n != 0``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package net
func runtime_rand() uint64
func randInt() int { return int(uint(runtime_rand()) >> 1) }
func randIntn(n int) int {
    return randInt() % n
}
'''
    issues = _detect_go_safety_issues(source)
    assert not any("n=0" in str(i.counterexample) for i in issues)


def test_detect_go_safety_issues_block_receiver_nonnil() -> None:
    """Methods on compiler/graph ``*Block`` receivers are non-nil in use."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package ssa
type Block struct{ ID int; Kind int }
func (b *Block) String() string {
    return fmt.Sprintf("b%d", b.ID)
}
func (b *Block) Log() {
    _ = b.Kind
}
'''
    issues = _detect_go_safety_issues(source)
    assert not any("dereference" in i.message for i in issues)


def test_detect_go_safety_issues_negative_or_len_guard() -> None:
    """``if id < 0 || int(id) >= len(arr) { return }`` guards ``arr[id]``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package gob
var idToTypeSlice []int
func idToType(id int32) int {
    if id < 0 || int(id) >= len(idToTypeSlice) {
        return 0
    }
    return idToTypeSlice[id]
}
'''
    issues = _detect_go_safety_issues(source)
    assert not any("idToTypeSlice" in i.message and "bounds" in i.message for i in issues)


def test_detect_go_safety_issues_hpke_sender_recipient_nonnil() -> None:
    """crypto/hpke Sender/Recipient receivers are non-nil when methods are called."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package hpke
type context struct{ export func(string, uint16) ([]byte, error) }
type Sender struct{ *context }
func (s *Sender) Export(ctx string, l int) ([]byte, error) {
    return s.export(ctx, uint16(l))
}
type Recipient struct{ *context }
func (r *Recipient) Export(ctx string, l int) ([]byte, error) {
    return r.export(ctx, uint16(l))
}
'''
    issues = _detect_go_safety_issues(source)
    assert not any("dereference" in i.message for i in issues)


def test_detect_go_safety_issues_abi_type_metadata_nonnil() -> None:
    """runtime/abi type descriptor receivers are non-nil when methods are called."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package abi
type Type struct{ Kind_ uint8 }
func (t *Type) Kind() uint8 { return t.Kind_ }
type FuncType struct{ Type }
func (t *FuncType) NumIn() int { return 0 }
type InterfaceType struct{ Type }
func (t *InterfaceType) NumMethod() int { return 0 }
type StructField struct{ Name string }
func (f *StructField) Embedded() bool { return false }
'''
    issues = _detect_go_safety_issues(source)
    assert not any("dereference" in i.message for i in issues)


def test_detect_go_safety_issues_local_map_alias_and_assertion() -> None:
    """Short map aliases and type-asserted map variables are map accesses."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''package gob
var typeInfoMapInit = make(map[string]int)
func lookupTypeInfo(rt string) int {
    if m := typeInfoMapInit; m != nil {
        return m[rt]
    }
    v, _ := cache.Load().(map[string]int)
    return v[rt]
}
'''
    issues = _detect_go_safety_issues(source)
    assert not any("bounds" in i.message for i in issues)


def test_detect_go_safety_issues_skips_map_key_access() -> None:
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = '''
package codegen

func LookupStringConversion1(m map[string]int, bytes []byte) int {
    s := string(bytes)
    return m[s]
}

func LookupStringConversion2(m *map[string]int, bytes []byte) int {
    s := string(bytes)
    return (*m)[s]
}
'''
    issues = _detect_go_safety_issues(source)
    lookup1_issues = [i for i in issues if i.function_name == "LookupStringConversion1"]
    lookup2_issues = [i for i in issues if i.function_name == "LookupStringConversion2"]
    assert not lookup1_issues
    assert all("index" not in i.message.lower() for i in lookup2_issues)


def test_rust_const_array_usize_cast_index_suppressed() -> None:
    """``(param - N) as usize`` indexing a ``const`` array is a caller-contract pattern."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """const LAST_DAYS: [u32; 12] = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

fn last_day_of_month(month: i32) -> u32 {
    let idx = (month - 1) as usize;
    LAST_DAYS[idx]
}
"""
    issues = _detect_safety_issues(source, "rust")
    assert not any("LAST_DAYS" in i.message for i in issues)


def test_rust_contract_inference_falls_back_bool_ensures() -> None:
    """Complex boolean return expressions cannot be lowered to Mumei ``ensures``."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = """fn is_leap_year(year: i32) -> bool {
    year % 400 == 0 || (year % 4 == 0 && year % 100 != 0)
}
"""
    atoms = _infer_rust_contracts(source)
    assert len(atoms) == 1
    assert atoms[0].return_type == "bool"
    assert atoms[0].ensures == "true"


def test_go_safety_suppresses_interface_method_nil_receiver() -> None:
    """Pointer-receiver methods implementing standard interfaces are caller-contract."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package authorizer

import (
    "context"
    "k8s.io/apiserver/pkg/authorization/authorizer"
)

type GrafanaAuthorizer struct{ auth authorizer.Authorizer }

func (a *GrafanaAuthorizer) Authorize(ctx context.Context, attr authorizer.Attributes) (authorizer.Decision, string, error) {
    return a.auth.Authorize(ctx, attr)
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("GrafanaAuthorizer" in i.message for i in issues)


def test_go_safety_suppresses_json_marshaler_nil_receiver() -> None:
    """``MarshalJSON`` / ``UnmarshalJSON`` pointer-receiver methods are caller-contract."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package iface

type BeaconCommitteeSelection struct {
    SelectionProof []byte
}

func (b *BeaconCommitteeSelection) MarshalJSON() ([]byte, error) {
    return []byte(b.SelectionProof), nil
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in i.message for i in issues)


def test_go_safety_suppresses_top_level_callback_first_param_nil() -> None:
    """Top-level functions stored as struct/map callbacks are invoked with non-nil first arg."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package asmgen

type Asm struct{}
type Reg int
type Carry int

func amd64Add(a *Asm, src1, src2 Reg, dst Reg, carry Carry) bool {
    return a.Enabled(0)
}

var arch = struct{ addF func(*Asm, Reg, Reg, Reg, Carry) bool }{addF: amd64Add}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("amd64Add" in i.message for i in issues)


def test_go_safety_suppresses_io_read_write_close_receivers() -> None:
    """io.Reader/Writer/Closer pointer-receiver methods are caller-contract."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package rwc

type Buffer struct{ data []byte }

func (b *Buffer) Read(p []byte) (n int, err error) {
    return b.readInto(p)
}

func (b *Buffer) Write(p []byte) (int, error) {
    return b.append(p)
}

func (b *Buffer) Close() error {
    return nil
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("Buffer" in i.message for i in issues)


def test_go_safety_suppresses_local_interface_method_receivers() -> None:
    """Methods implementing a source-local interface are caller-contract."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package http2

type writeFramer interface {
    writeFrame(writeContext) error
    staysWithinBuffer(int) bool
}

type writeData struct{ streamID uint32; p []byte; endStream bool }

func (w *writeData) writeFrame(ctx writeContext) error {
    return ctx.Framer().WriteData(w.streamID, w.endStream, w.p)
}

func (w *writeData) staysWithinBuffer(max int) bool {
    return frameHeaderLen+len(w.p) <= max
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("writeData" in i.message for i in issues)


def test_solidity_guaranteed_nonzero_from_min_constant() -> None:
    """MIN_* constants imply matching parameters are non-zero."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """library TickMath {
    int24 internal constant MIN_TICK_SPACING = 1;

    function maxUsableTick(int24 tickSpacing) internal pure returns (int24) {
        return (887272 / tickSpacing) * tickSpacing;
    }
}
"""
    issues = _detect_safety_issues(source, "solidity")
    assert not any("tickSpacing" in i.message for i in issues)


def test_go_safety_suppresses_range_index_into_parallel_slice() -> None:
    """``range`` loop variables and parallel ``make([]T, len(domain))`` slices are safe."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package evaluators

func compareChainHeads(chainHeads []*ChainHead) error {
    headEpochs := make([]uint64, len(chainHeads))
    for i, ch := range chainHeads {
        headEpochs[i] = ch.HeadEpoch
    }
    for i := range chainHeads {
        if headEpochs[0] != headEpochs[i] {
            return fmt.Errorf("mismatch %d %d", chainHeads[i].HeadEpoch, headEpochs[i])
        }
    }
    return nil
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("can index" in i.message for i in issues)


def test_go_safety_suppresses_guarded_index_in_len_check() -> None:
    """``if k >= 0 && int(k) < len(arr) { return arr[k] }`` is a bounds-safe guard."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package slog

var kindStrings = []string{"Any", "Bool"}

type Kind int

func (k Kind) String() string {
    if k >= 0 && int(k) < len(kindStrings) {
        return kindStrings[k]
    }
    return "<unknown>"
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("can index" in i.message for i in issues)


def test_go_safety_suppresses_unsigned_index_guarded_by_len_minus_one() -> None:
    """``const m = len(arr) - 1; if n <= m { arr[n] }`` guards an unsigned index."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package big

var pow5tab = [...]uint64{1, 5}

func (z *Float) pow5(n uint64) *Float {
    const m = uint64(len(pow5tab) - 1)
    if n <= m {
        return z.SetUint64(pow5tab[n])
    }
    z.SetUint64(pow5tab[m])
    return z
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("can index" in i.message for i in issues)


def test_go_safety_suppresses_actor_act_builder_param_nil() -> None:
    """``Actor.Act`` implementations receive non-nil ``*Builder`` and ``*Action``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package work

type Builder struct{}
type Action struct{}

type Actor interface {
    Act(*Builder, context.Context, *Action) error
}

type buildActor struct{}

func (ba *buildActor) Act(b *Builder, ctx context.Context, a *Action) error {
    return b.build(ctx, a)
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in i.message for i in issues)


def test_go_safety_suppresses_component_runner_receiver_nil() -> None:
    """Pointer receivers embedding ``ComponentRunner`` are non-nil in e2e runners."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package eth1

type ComponentRunner interface { Started() <-chan struct{} }

type ProxySet struct {
    ComponentRunner
    proxies []ComponentRunner
}

func (s *ProxySet) PauseAtIndex(i int) error {
    if i >= len(s.proxies) {
        return nil
    }
    return s.proxies[i].Pause()
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in i.message for i in issues)


def test_go_crypto_key_equal_methods_are_non_nil() -> None:
    """``crypto.PublicKey``/``crypto.PrivateKey`` ``Equal`` methods are called on non-nil keys."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package rsa

import "crypto"

type PublicKey struct{ N, E int }

func (pub *PublicKey) Equal(x crypto.PublicKey) bool {
    xx, ok := x.(*PublicKey)
    if !ok { return false }
    return pub.N == xx.N && pub.E == xx.E
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in i.message for i in issues)


def test_go_param_types_handles_grouped_params() -> None:
    """Grouped parameter declarations ``a, b *T`` map the type to all identifiers."""
    from agent.cross_validation_foreign import _go_param_types

    assert _go_param_types("a, b *big.Int") == {"a": "*big.Int", "b": "*big.Int"}


def test_go_guarded_indices_from_error_checked_index_call() -> None:
    """``idx, err := BeaconProposerIndex(...); if err != nil { return }`` bounds ``idx``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package helpers

type ReadOnlyBeaconState struct{}
type SecretKey struct{}

func BeaconProposerIndex(ctx interface{}, st ReadOnlyBeaconState) (int, error) { return 0, nil }

func RandaoReveal(beaconState ReadOnlyBeaconState, privKeys []SecretKey) ([]byte, error) {
    proposerIdx, err := BeaconProposerIndex(nil, beaconState)
    if err != nil {
        return nil, err
    }
    return privKeys[proposerIdx].Sign(nil), nil
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("can index" in i.message for i in issues)


def test_go_mod_divisor_is_nonzero() -> None:
    """A Go method named ``Mod`` with an integer parameter implies a non-zero divisor."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package primitives

type ValidatorIndex uint64

func (v ValidatorIndex) Mod(x uint64) ValidatorIndex {
    return ValidatorIndex(uint64(v) % x)
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in i.message for i in issues)


def test_rust_size_variable_sums_do_not_overflow() -> None:
    """Sums of memory-size/length variables are not i64 overflow false positives."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """pub struct Schema;
impl Schema {
    pub fn estimate_size(&self) -> usize {
        let size_self = std::mem::size_of_val(self);
        let size_inner = std::mem::size_of_val(&self);
        size_self + size_inner
    }
}
"""
    issues = _detect_safety_issues(source, "rust")
    assert not any("overflow" in i.message for i in issues)


def test_go_ssz_interface_methods_are_non_nil() -> None:
    """SSZ marshaler/unmarshaler/hash-root/size methods are invoked on non-nil values."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package primitives

type Hasher struct{}

func (v *ValidatorIndex) UnmarshalSSZ(buf []byte) error {
    *v = ValidatorIndex(0)
    return nil
}

func (v *ValidatorIndex) SizeSSZ() int {
    return 8
}

func (v *ValidatorIndex) HashTreeRootWith(hh *Hasher) error {
    hh.PutUint64(uint64(*v))
    return nil
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in i.message for i in issues)


def test_go_runtime_page_constants_are_nonzero() -> None:
    """Go runtime page-size constants are non-zero across per-file analysis."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package runtime

const pallocChunkPages = 1 << logPallocChunkPages
const logPallocChunkPages = 9
var pallocChunkBytes = pallocChunkPages * pageSize

func chunkPageIndex(p uintptr) uint {
    return uint(p % pallocChunkBytes / pageSize)
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in i.message for i in issues)


def test_go_runtime_level_index_is_guarded() -> None:
    """Go runtime ``level`` parameter indexing ``levelShift`` is bounds-safe."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package runtime

var levelShift [5]uint

func offAddrToLevelIndex(level int, addr offAddr) int {
    return int((addr.a - arenaBaseOffset) >> levelShift[level])
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("can index" in i.message for i in issues)


def test_rust_modulo_len_index_is_guarded() -> None:
    """Rust ``let index = ... % container.len();`` bounds ``container[index]``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """pub fn get_spinner_frame() -> char {
    let frames = ["_", "_", "_", "-", "`", "`", "'", "´", "-", "_", "_", "_"];
    let time = 0usize;
    let index = (time / 70) % frames.len();
    frames[index].chars().next().unwrap()
}
"""
    issues = _detect_safety_issues(source, "rust")
    assert not any("can index" in i.message for i in issues)


def test_go_http2_container_types_are_non_nil() -> None:
    """Go standard-library container types (Transport, ClientConn, etc.) are non-nil."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package http2

type Transport struct{ t int }
type ClientConn struct{ t int }
type clientStream struct{ cc *ClientConn }
type ClientRequest struct{ URL string }

func (t *Transport) RoundTrip(req *ClientRequest) int {
    return t.t + req.URL
}

func (cc *ClientConn) RoundTrip(req *ClientRequest) int {
    return cc.t + req.URL
}

func (cs *clientStream) writeRequest(req *ClientRequest) int {
    return cs.cc.t + req.URL
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in i.message for i in issues)


def test_go_fake_receivers_are_non_nil() -> None:
    """Generated ``Fake*`` test-double receivers are non-nil."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package pluginfakes

type FakePluginInstaller struct{ AddFunc func() }

func (i *FakePluginInstaller) Add() {
    if i.AddFunc != nil {
        i.AddFunc()
    }
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in i.message for i in issues)


def test_go_named_string_return_type_inferred_from_literal() -> None:
    """A Go function returning a string literal gets a string Mumei return type."""
    from agent.cross_validation import _infer_go_contracts

    source = """package p

type Target string

func (t *Target) Target() Target {
    return "test-target"
}
"""
    atoms = _infer_go_contracts(source)
    target_atom = next(a for a in atoms if a.name == "Target")
    assert target_atom.return_type == "string"
    assert target_atom.ensures == "true"


def test_go_named_bool_return_type_is_recognized() -> None:
    """A Go named return value ``(b bool)`` maps to the Mumei ``bool`` type."""
    from agent.cross_validation import _infer_go_contracts

    source = """package slog_test

func panics(f func()) (b bool) {
    defer func() { recover() }()
    f()
    return false
}
"""
    atoms = _infer_go_contracts(source)
    panics_atom = next(a for a in atoms if a.name == "panics")
    assert panics_atom.return_type == "bool"


def test_go_compiler_run_tests_are_skipped() -> None:
    """Go compiler test files marked ``// run`` are not runnable user code."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """// run

package main

var A, B int

func divZero() int {
    return A / B
}
"""
    issues = _detect_safety_issues(source, "go")
    assert issues == []


def test_go_div_integer_parameter_is_nonzero() -> None:
    """A function named ``Div`` with an integer parameter implies a non-zero divisor."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package image

type Point struct{ X, Y int }

// Div returns the vector p/k.
func (p Point) Div(k int) Point {
    return Point{p.X / k, p.Y / k}
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in i.message for i in issues)


def test_go_zero_guarded_divisor_is_nonzero() -> None:
    """A parameter checked with ``if x == 0 { return }`` before division is non-zero."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package runtime_test

import "testing"

func iterCount(b *testing.B, n int) int {
    if n == 0 {
        return b.N
    }
    return b.N / n
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in i.message for i in issues)


def test_solidity_named_bool_return_ensures_is_safe() -> None:
    """Named Solidity return values (``returns (bool flag)``) must not produce an i64-typed boolean expression."""
    from agent.strategies.foreign_code_strategy import ForeignCodeExtractor

    source = """contract C {
    function isZero(uint256, uint256 y) internal pure returns (bool flag) {
        return (y == 0);
    }
}
"""
    specs = ForeignCodeExtractor().extract_solidity(source)
    assert len(specs) == 1
    assert specs[0].return_type == "bool"
    assert "result ==" not in specs[0].postconditions


def test_go_human_language_precondition_is_sanitized() -> None:
    """Human-language ``Preconditions: X returns true`` should not be emitted as a Mumei requires clause."""
    from agent.strategies.foreign_code_strategy import ForeignCodeExtractor

    source = """package runtime

// printOneCgoTraceback prints the traceback of a single cgo caller.
//
// Preconditions: cgoSymbolizerAvailable returns true.
func printOneCgoTraceback(pc uintptr, commitFrame func() (pr, stop bool), arg *cgoSymbolizerArg) bool {
    return true
}
"""
    specs = ForeignCodeExtractor().extract_go(source)
    spec = next(s for s in specs if s.function_name == "printOneCgoTraceback")
    assert "returns" not in " && ".join(spec.preconditions)


def test_infer_solidity_named_bool_return_ensures_is_safe() -> None:
    """Named Solidity return values must produce a bool return type and a safe ensures clause."""
    from agent.cross_validation_foreign import _infer_solidity_contracts

    source = """contract C {
    function isZero(uint256, uint256 y) internal pure returns (bool flag) {
        return (y == 0);
    }
}
"""
    atoms = _infer_solidity_contracts(source)
    atom = next(a for a in atoms if a.name == "isZero")
    assert atom.return_type == "bool"
    assert "result ==" not in atom.ensures


def test_infer_solidity_bytes_memory_return_type_is_string() -> None:
    """A Solidity ``bytes memory`` return with an empty string literal maps to Mumei ``string``."""
    from agent.cross_validation_foreign import _infer_solidity_contracts

    source = """contract C {
    function _defaultParams() internal view virtual returns (bytes memory) {
        return "";
    }
}
"""
    atoms = _infer_solidity_contracts(source)
    atom = next(a for a in atoms if a.name == "defaultParams")
    assert atom.return_type == "string"


def test_expression_lowerable_rejects_unknown_function_calls() -> None:
    """Unknown function calls in a return expression cannot be lowered to Mumei ensures."""
    from agent.cross_validation_foreign import _is_expression_lowerable

    expr = 'query(ctx, netdir + "/cs", net + "!" + host + "!" + service, 128)'
    assert not _is_expression_lowerable(expr, {"ctx", "net", "host", "service"}, {}, None)


def test_expression_lowerable_rejects_string_concat_with_literals() -> None:
    """String concatenation with literal operands is not arithmetic and cannot be lowered."""
    from agent.cross_validation_foreign import _is_expression_lowerable

    assert not _is_expression_lowerable('netdir + "/cs"', {"netdir"}, {}, None)
    assert not _is_expression_lowerable('net + "!" + host', {"net", "host"}, {}, None)


def test_expression_lowerable_rejects_unknown_array_index() -> None:
    """Array indexing on an unknown state variable cannot be lowered into ensures."""
    from agent.cross_validation_foreign import _is_expression_lowerable

    assert not _is_expression_lowerable("_allTokens[index]", {"index"}, {}, None)
    assert _is_expression_lowerable("ids[i]", {"ids", "i"}, {}, None)


def test_solidity_require_bounds_suppresses_index_safety_issue() -> None:
    """A Solidity ``require(index < ...)`` guard should suppress the index-bounds false positive."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_block_safety_issues

    source = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract C {
    uint256[] private _allTokens;

    function totalSupply() public view returns (uint256) {
        return _allTokens.length;
    }

    function tokenByIndex(uint256 index) public view returns (uint256) {
        require(index < totalSupply(), "out of bounds");
        return _allTokens[index];
    }
}
"""
    issues = _detect_block_safety_issues(source, [("tokenByIndex", "tokenByIndex")], "Solidity")
    assert not any(i.function_name == "tokenByIndex" for i in issues)


def test_solidity_mapping_key_access_skips_index_safety_issue() -> None:
    """Nested Solidity mapping key access should not produce an index-bounds issue."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_block_safety_issues

    source = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract C {
    mapping(address => mapping(uint256 => uint256)) private _ownedTokens;

    function tokenOfOwnerByIndex(address owner, uint256 index) public view returns (uint256) {
        return _ownedTokens[owner][index];
    }
}
"""
    blocks = [("tokenOfOwnerByIndex", "tokenOfOwnerByIndex")]
    issues = _detect_block_safety_issues(source, blocks, "Solidity")
    assert not any("_ownedTokens[owner]" in i.message for i in issues)


def test_solidity_sqrt_ratio_params_treated_as_nonzero() -> None:
    """Uniswap-V3-style sqrtRatio*X96 parameters are never zero in the protocol."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _detect_block_safety_issues,
        _solidity_guaranteed_nonzero_params,
    )

    source = """// SPDX-License-Identifier: MIT
pragma solidity >=0.5.0;

library L {
    function getAmount0(uint160 sqrtRatioAX96, uint160 sqrtRatioBX96, uint128 liquidity)
        internal pure returns (uint256 amount0)
    {
        if (sqrtRatioAX96 > sqrtRatioBX96) (sqrtRatioAX96, sqrtRatioBX96) = (sqrtRatioBX96, sqrtRatioAX96);
        return (uint256(liquidity) << 96) / sqrtRatioAX96;
    }
}
"""
    blocks = [("getAmount0", "getAmount0")]
    issues = _detect_block_safety_issues(source, blocks, "Solidity")
    assert not any(i.function_name == "getAmount0" for i in issues)
    assert "sqrtRatioAX96" in _solidity_guaranteed_nonzero_params(source)


def test_solidity_sqrtpx96_params_treated_as_nonzero() -> None:
    """Uniswap-V3-style ``sqrtPX96`` parameters are never zero in the protocol."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _detect_block_safety_issues,
        _solidity_guaranteed_nonzero_params,
    )

    source = """// SPDX-License-Identifier: MIT
pragma solidity >=0.5.0;

library SqrtPriceMath {
    function getNextSqrtPriceFromAmount0RoundingUp(uint160 sqrtPX96, uint128 liquidity, uint256 amountIn)
        internal pure returns (uint160)
    {
        return (liquidity << 96) / sqrtPX96;
    }
}
"""
    blocks = [("getNextSqrtPriceFromAmount0RoundingUp", "getNextSqrtPriceFromAmount0RoundingUp")]
    issues = _detect_block_safety_issues(source, blocks, "Solidity")
    assert not any(i.function_name == "getNextSqrtPriceFromAmount0RoundingUp" for i in issues)
    assert "sqrtPX96" in _solidity_guaranteed_nonzero_params(source)


def test_go_sort_interface_methods_suppress_nil_receiver() -> None:
    """sort.Interface implementers (Len/Less/Swap) are called on non-nil values."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

    source = """package sort_test

type testingData struct {
    data []int
}

func (d *testingData) Len() int { return len(d.data) }
func (d *testingData) Less(i, j int) bool { return d.data[i] < d.data[j] }
func (d *testingData) Swap(i, j int) { d.data[i], d.data[j] = d.data[j], d.data[i] }
"""
    issues = _detect_go_safety_issues(source)
    assert not any("testingData" in i.message for i in issues)


def test_go_float_variables_detects_float_cast() -> None:
    """Local variables initialized with ``float64`` casts are tracked as float."""
    from agent.strategies.foreign_code_strategy_helpers import _go_float_variables

    body = """topicWeight := attestationTotalWeight / float64(subnetCount)
return topicWeight"""
    assert "topicWeight" in _go_float_variables(body)


def test_detect_go_safety_issues_skips_float_division() -> None:
    """Dividing by a float64 local variable does not panic in Go."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package demo

func maxScore() float64 { return 1.0 }
func f() float64 {
    topicWeight := 1.0 / float64(2)
    return -maxScore() / topicWeight
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("topicWeight" in i.message for i in issues)


def test_detect_solidity_contract_issues_skips_named_return_assignment() -> None:
    """Assigning to a named return parameter is a local write, not a state write."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_solidity_contract_issues

    source = """library L {
    function deploy(bytes32 salt) internal returns (address reservesLens) {
        (bool success, bytes memory ret) = F.call(abi.encodePacked(salt));
        require(success);
        reservesLens = address(uint160(bytes20(ret)));
    }
}
"""
    issues = _detect_solidity_contract_issues(source)
    assert not any("reentrancy" in i.message for i in issues)


def test_infer_rust_contracts_skips_tokio_test_attribute() -> None:
    """Functions annotated with ``#[tokio::test]`` are not audited as contracts."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = """#[tokio::test]
async fn v1_password_parameter() {
    let x = ("db", "foo");
}
"""
    atoms = _infer_rust_contracts(source)
    assert not any(a.name == "v1_password_parameter" for a in atoms)


def test_infer_rust_contracts_cfg_test_not_skipped() -> None:
    """Functions annotated with ``#[cfg(test)]`` are still audited."""
    from agent.cross_validation_foreign import _infer_rust_contracts

    source = """#[cfg(test)]
fn real_func() {}
"""
    atoms = _infer_rust_contracts(source)
    assert any(a.name == "real_func" for a in atoms)
def test_detect_go_safety_issues_skips_nonnil_container_receiver() -> None:
    """Methods on *Service and *Node receivers are not flagged for nil dereference."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues
    source = """package expr
type baseNode struct{ refID string }
func (b *baseNode) String() string { return b.refID }
type CMDNode struct{ Command *CMDNode }
func (gn *CMDNode) NeedsVars() []string { return gn.Command.NeedsVars() }
type Service struct{ tracer int }
func Execute(gn *CMDNode, s *Service) int { return s.tracer }
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in i.message for i in issues)
def test_detect_go_safety_issues_skips_string_concatenation() -> None:
    """Go ``+`` between string variables is concatenation, not arithmetic."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues
    source = """package setting
var AppUrl string
func ToAbsUrl(relativeUrl string) string {
    return AppUrl + relativeUrl
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("overflow" in i.message for i in issues)


def test_detect_go_safety_issues_skips_string_concatenation_literal_initialized() -> None:
    """Go ``+`` between string variables is concatenation even without explicit type."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package setting

var AppUrl = "https://example.com"

func ToAbsUrl(relativeUrl string) string {
    return AppUrl + relativeUrl
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("overflow" in i.message for i in issues)


def test_detect_go_safety_issues_skips_bounds_with_assumed_valid_comment() -> None:
    """A comment that says the index is assumed valid suppresses bounds checks."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues
    source = """package syntax
var _token_index []int
// tokStrFast is faster, which assumes that tok is one of the valid tokens -
// and can thus skip bounds checks.
func tokStrFast(tok int) string {
    return _token_index[tok-1:_token_index[tok]]
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in i.message for i in issues)


def test_detect_go_safety_issues_skips_global_lookup_table_index() -> None:
    """Exported constant indexing an exported package-level table is a valid lookup."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package types2

func expandRHS(n *Named) Type {
    return Typ[Invalid]
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in i.message for i in issues)


def test_detect_go_safety_issues_global_array_keys_all_entries() -> None:
    """All keyed entries of a package-level array literal are recognized."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package types2

var Typ = [...]*Basic{
    Invalid: {Invalid, 0, "invalid"},
    Bool:    {Bool, IsBoolean, "bool"},
    Int:     {Int, IsInteger, "int"},
}

func expandRHS(n *Named) Type {
    return Typ[Int]
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in i.message for i in issues)

def test_detect_go_safety_issues_skips_roundup_alignment_pattern() -> None:
    """The idiomatic ``(x + align - 1) &^ (align - 1)`` roundup is trusted."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues
    source = """package routebsd
var kernelAlign int
func roundup(l int) int {
    if l == 0 {
        return kernelAlign
    }
    return (l + kernelAlign - 1) &^ (kernelAlign - 1)
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("overflow" in i.message for i in issues)
def test_detect_go_safety_issues_skips_math_float_division() -> None:
    """Division by a local variable assigned a ``math`` float function is float."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues
    source = """package math
func cosh(x float64) float64 {
    x = Abs(x)
    if x > 21 {
        return Exp(x) * 0.5
    }
    ex := Exp(x)
    return (ex + 1/ex) * 0.5
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in i.message for i in issues)
def test_detect_go_safety_issues_skips_generic_instantiation_index() -> None:
    """``container[Type](args)`` is a generic call, not an array index."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues
    source = """package alerting
func DeleteSilence(t *testing.T, id string) (any, int, string) {
    type dynamic struct {
        Message string `json:"message"`
    }
    return sendRequestJSON[dynamic](t, nil, 200)
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in i.message for i in issues)


def test_detect_go_safety_issues_scale_param_nonzero() -> None:
    """Scaling functions treat an integer ``scale`` parameter as non-zero."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package riscv
func isScaledImmI(imm int64, nbits uint, scale int64) bool {
    return imm%scale == 0
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("scale" in i.message and "non-zero" in i.message for i in issues)


def test_detect_rust_safety_issues_skips_float_division() -> None:
    """Dividing by a Rust local assigned a float literal is float division, not panic."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """mod store {
fn round_to_decimal_places<T: Float>(avg: T, num_places: u8) -> T {
    let factor = if num_places == 4 { 10_000.0 } else { 100.0 };
    let factor_as_float = num::cast(factor).unwrap();
    (avg * factor_as_float).round() / factor_as_float
}
}
"""
    issues = _detect_safety_issues(source, "rust")
    assert not any("factor_as_float" in i.message for i in issues)


def test_detect_rust_safety_issues_doc_comment_nonzero_param() -> None:
    """Doc comments that state a parameter must be non-zero avoid false positives."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''/// If `num_buckets` is zero, this will panic.
#[inline(always)]
pub fn bucket_for_tag_value(tag_value: &str, num_buckets: u32) -> u32 {
    let hash = 0u32;
    (hash & i32::MAX as u32) % num_buckets
}
'''
    issues = _detect_safety_issues(source, "rust")
    assert not any("num_buckets" in i.message for i in issues)


def test_detect_go_safety_issues_interval_param_nonzero() -> None:
    """Interval-math functions treat a ``seconds`` parameter as non-zero."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package backfill
import \"time\"
func intervalNumber(t time.Time, seconds int64) int64 {
    return t.Unix() / seconds
}
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("seconds" in i.message for i in issues)


def test_detect_go_safety_issues_generic_builtin_type_instantiation() -> None:
    """Generic instantiation with a builtin type (``rangeNum[int]``) is not an index."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package reflect
func Seq() { return rangeNum[int](0, nil) }
func rangeNum[T int, N int64](num N, t int) int { return 0 }
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("rangeNum" in i.message and "bounds" in i.message for i in issues)


def test_detect_go_safety_issues_float_param_division() -> None:
    """Dividing by a ``float64`` parameter is float division, not a panic."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = """package big
func fdiv(a, b float64) float64 { return a / b }
"""
    issues = _detect_safety_issues(source, "go")
    assert not any("b" in i.message and "non-zero" in i.message for i in issues)


def test_source_has_function_declarations_rust_async_test_skipped() -> None:
    """Async test functions are not considered non-test declarations."""
    from agent.strategies.foreign_code_strategy import _source_has_function_declarations

    assert _source_has_function_declarations("#[tokio::test]\nasync fn foo() {}", "rust") is False
    assert _source_has_function_declarations("#[tokio::test]\nasync fn foo() {}\nfn bar() {}", "rust") is True


def test_strip_go_rust_comments_mask_slashes() -> None:
    """Comment slashes are fully masked so they are not confused with division."""
    from agent.cross_validation_foreign import _strip_go_rust_literals_and_comments

    source = "let x = a / b; // s is not a divisor\nlet y = c / d;"
    stripped = _strip_go_rust_literals_and_comments(source)
    assert stripped.count("/") == 2


def test_strip_go_rust_literals_preserve_quotes() -> None:
    """String literal quote delimiters are preserved to keep source parseable."""
    from agent.cross_validation_foreign import _strip_go_rust_literals_and_comments

    assert _strip_go_rust_literals_and_comments('foo("", x)') == 'foo("", x)'
    assert _strip_go_rust_literals_and_comments('foo("ab", x)') == 'foo("  ", x)'


def test_detect_go_safety_issues_skips_compile_compiler_tests() -> None:
    """Go compiler tests marked ``// compile`` are not runnable user code."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''// compile

package p

type S struct {
\tn int
\ta [2]int
}

func f(i int) int {
\tvar arr [0]S
\treturn arr[i].n
}
'''
    assert _detect_safety_issues(source, "go") == []


def test_detect_go_safety_issues_float_cast_division() -> None:
    """``float64(x) / float64(y)`` is floating-point division and cannot panic."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package p

import "fmt"

type byteCount int64

func (b byteCount) String() string {
\tvar divisor int64 = 1024
\treturn fmt.Sprintf("%.1f", float64(b)/float64(divisor))
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("divide by" in issue.message for issue in issues)


def test_detect_go_safety_issues_upload_interface_non_nil() -> None:
    """``Upload`` methods implementing uploader/client interfaces are invoked on non-nil values."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package p

import "context"

type s3ClientWrapper struct {
\tuploader int
}

func (w *s3ClientWrapper) Upload(ctx context.Context, input int) (int, error) {
\treturn w.uploader, nil
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in issue.message for issue in issues)


def test_detect_rust_safety_issues_float_cast_division() -> None:
    """Rust ``x as f64`` and ``100f64`` divisors are floating-point."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''pub fn percent(percentage: u64, total: u64) -> usize {
    (percentage as f64 / 100f64 * total as f64).round() as usize
}

pub fn ratio(reserved: usize, detected: usize) -> bool {
    detected > 0 && reserved as f64 / detected as f64 >= 0.9
}
'''
    issues = _detect_safety_issues(source, "rust")
    assert not any("divide by" in issue.message for issue in issues)


def test_detect_rust_safety_issues_nonzero_numeric_literal_divisor() -> None:
    """Non-zero numeric literals (e.g. ``8``) are safe divisors."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''pub fn block(len: usize) -> usize {
    len / 8
}
'''
    issues = _detect_safety_issues(source, "rust")
    assert not any("divide by" in issue.message for issue in issues)


def test_detect_go_safety_issues_text_unmarshaler_non_nil() -> None:
    """``encoding.TextUnmarshaler`` methods are invoked on non-nil values."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package p

type Level int

func (l *Level) UnmarshalText(data []byte) error {
    *l = Level(0)
    return nil
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in issue.message for issue in issues)


def test_detect_go_safety_issues_uintn_offset_width_overflow() -> None:
    """Go compiler object-writer ``UintN`` offset/width additions are trusted."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package objw

import "cmd/internal/obj"

func UintN(s *obj.LSym, off int, v uint64, wid int) int {
    return off + wid
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("overflow" in issue.message for issue in issues)


def test_detect_solidity_safety_issues_constant_power_divisor() -> None:
    """Solidity constant exponentiation ``2**32`` is a non-zero divisor."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''library Oracle {
    function currentCumulativePrices() internal pure returns (uint32) {
        return uint32(block.timestamp % (2 ** 32));
    }
}
'''
    issues = _detect_safety_issues(source, "solidity")
    assert not any("divide by" in issue.message for issue in issues)


def test_detect_go_safety_issues_equal_length_slice_index() -> None:
    """Index into a parallel slice is safe when lengths are checked equal."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package p

func shorterThan(s, t []string) bool {
    if len(s) != len(t) {
        return len(s) < len(t)
    }
    for i := range s {
        if s[i] != t[i] {
            return s[i] < t[i]
        }
    }
    return false
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("index" in issue.message.lower() for issue in issues)


def test_detect_go_safety_issues_error_interface_method_non_nil() -> None:
    """``error`` interface ``Error``/``Unwrap`` methods are invoked on non-nil values."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package p

type PackageError struct{ Pos string; Err error }

func (p *PackageError) Error() string {
    return p.Pos + ": " + p.Err.Error()
}

func (p *PackageError) Unwrap() error {
    return p.Err
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in issue.message for issue in issues)


def test_detect_solidity_contract_issues_skips_mocks() -> None:
    """OpenZeppelin-style test mocks under ``mocks/`` are test-only artifacts."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _detect_solidity_contract_issues,
    )

    source = '''abstract contract BaseRelayMock {
    address internal _currentSender;
    function relayAs(address target, bytes calldata data, address sender) external virtual {
        _currentSender = sender;
        (bool success, bytes memory returndata) = target.call(data);
        _currentSender = address(0);
    }
}
'''
    assert _detect_solidity_contract_issues(source) == []
    assert _detect_solidity_contract_issues(
        source, source_file="/contracts/mocks/crosschain/bridges.sol"
    ) == []


def test_detect_solidity_safety_issues_constant_expression_divisor() -> None:
    """Composite constant expressions such as ``ADDR_SIZE + FEE_SIZE`` are non-zero."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''library Path {
    uint256 private constant ADDR_SIZE = 20;
    uint256 private constant FEE_SIZE = 3;
    uint256 private constant NEXT_OFFSET = ADDR_SIZE + FEE_SIZE;

    function numPools(bytes memory path) internal pure returns (uint256) {
        return ((path.length - ADDR_SIZE) / NEXT_OFFSET);
    }
}
'''
    issues = _detect_safety_issues(source, "solidity")
    assert not any("divide by" in issue.message for issue in issues)


def test_extract_go_mumei_reserved_param_call() -> None:
    """Go parameters named ``call`` are renamed so Mumei treats them as variables."""
    from agent.strategies.foreign_code_strategy import ForeignCodeExtractor
    from agent.strategies.foreign_code_strategy_helpers import (
        _detect_safety_issues,
        _filter_covered_safety_issues,
    )

    source = '''package types

import "go/ast"

func hasDots(call *ast.CallExpr) bool { return call.Ellipsis.IsValid() }
'''
    specs = ForeignCodeExtractor().extract(source, "go")
    issues = _filter_covered_safety_issues(
        _detect_safety_issues(source, "go"), specs
    )
    assert not any("dereference" in issue.message for issue in issues)
    atom = next((s for s in specs if s.function_name == "hasDots"), None)
    assert atom is not None
    assert any("call_" in req for req in atom.preconditions)


def test_solidity_declared_constants_pow_bounded() -> None:
    """Exponentiation in Solidity constant expressions is bounded to avoid OOM."""
    from agent.strategies.foreign_code_strategy_helpers import (
        _evaluate_solidity_constant_expression,
    )

    assert _evaluate_solidity_constant_expression("2 ** 1024", {}) is not None
    assert _evaluate_solidity_constant_expression("2 ** 1025", {}) is None
    assert _evaluate_solidity_constant_expression("2 ** -1", {}) is None


def test_source_has_function_declarations_rust_trait_signatures_no_body() -> None:
    """Rust trait method signatures without bodies are not verifiable functions."""
    from agent.strategies.foreign_code_strategy import _source_has_function_declarations

    source = '''pub trait CatalogResource: Clone {
    type Identifier;
    const CATEGORY: &'static str;
    fn id(&self) -> Self::Identifier;
    fn name(&self) -> Arc<str>;
}
'''
    assert _source_has_function_declarations(source, "rust") is False


def test_detect_go_safety_issues_float_array_divisor() -> None:
    """Go float64 array elements are floats; division by zero is not a panic."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package math

var pow10tab = [...]float64{
    1e00, 1e01, 1e02,
}

func Pow10(n int) float64 {
    return 1.0 / pow10tab[uint(-n)%3]
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in issue.message for issue in issues)


def test_ensures_for_return_expression_bool_literal_non_bool_return() -> None:
    """Boolean literals in a non-bool tail expression must not produce ``result == true``."""
    from agent.cross_validation_foreign import _ensures_for_return_expression

    assert _ensures_for_return_expression("true", "i64") == "true"
    assert _ensures_for_return_expression("true,", "i64") == "true"
    assert _ensures_for_return_expression("false", "bool") == "result == false"


def test_last_expression_strips_trailing_comma_comments() -> None:
    """Trailing commas hidden by line comments do not make an argument a tail expression."""
    from agent.cross_validation_foreign import _last_expression

    body = '''{
    Sort::new(
        self.as_expr(),
        true, // Sort ASCENDING
        true,
    )
}'''
    last = _last_expression(body)
    # It should not return a bare boolean literal from inside the call.
    assert last not in {"true", "true,"}


def test_ensures_for_return_expression_string_literal_non_string_return() -> None:
    """A string literal tail expression in a non-string function is not the real result."""
    from agent.cross_validation_foreign import _ensures_for_return_expression

    assert _ensures_for_return_expression('"Invalid CREATE statement"', "i64") == "true"


def test_divroundup_expression_suppresses_division_by_zero() -> None:
    """The ``(x + y - 1) / y`` ceiling-division idiom should not require ``y != 0``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package pbkdf2

func divRoundUp(x, y int) int {
    return int((int64(x) + int64(y) - 1) / int64(y))
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in issue.message for issue in issues)


def test_go_float_variables_propagates_from_float_params() -> None:
    """Local float variables derived from float64 parameters are recognized."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package math

func erf(x float64) float64 {
    s := x - 1
    P := 1.0 + s*2.0
    Q := 1 + s*(2.0)
    return P / Q
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in issue.message for issue in issues)


def test_go_guarded_indices_int_cast_upper_bound() -> None:
    """Go upper-bound guard ``int(idx) < len(arr)`` is recognized when the index is unsigned."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package version

func EventName(typ uint8, s []T) string {
    if int(typ) < len(s) && s[typ].Name != "" {
        return s[typ].Name
    }
    return ""
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_make_plus_one_index_is_safe() -> None:
    """A slice allocated with ``make([]T, n+1)`` can be indexed at ``n``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package ssz

func Depth(v uint64) uint8 { return 0 }

func Merkleize(count, limit uint64) [32]byte {
    limitDepth := Depth(limit)
    tmp := make([][32]byte, limitDepth+1)
    return tmp[limitDepth]
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_reverse_loop_guarded_index() -> None:
    """A reverse ``for i := len(arr)-1; i >= 0; i--`` loop bounds ``arr[i]``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package types2

type Stmt interface{}
type EmptyStmt struct{}

func isTerminatingList(list []Stmt) bool {
    for i := len(list) - 1; i >= 0; i-- {
        if _, ok := list[i].(*EmptyStmt); !ok {
            return true
        }
    }
    return false
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)



def test_go_unsigned_variable_guarded_index() -> None:
    """Unsigned variables with ``x < len(arr)`` are fully bounds-guarded."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package ssa

type relation uint

var relationStrings = []string{"lt", "eq", "gt"}

func (r relation) String() string {
    if r < relation(len(relationStrings)) {
        return relationStrings[r]
    }
    return "unknown"
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_unsigned_addition_no_overflow() -> None:
    """Unsigned parameter addition wraps and should not trigger i64 overflow."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package ssa

func unsignedAddOverflows(a, b uint) bool {
    return a+b < a
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("overflow" in issue.message for issue in issues)


def test_go_local_map_key_access_not_bounds() -> None:
    """Short variable map declarations are not array index accesses."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package fsm

type stateID uint8

func (s stateID) String() string {
    states := map[stateID]string{0: "new"}
    return states[s]
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_atomic_pointer_receiver_non_nil() -> None:
    """Atomic wrapper pointer-receiver methods are called on non-nil values."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package atomic

type Uint32 struct { v uint32 }

func Loadint32(addr *uint32) uint32 { return 0 }

func (u *Uint32) Load() uint32 {
    return Loadint32(&u.v)
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in issue.message for issue in issues)


def test_go_machine_migrator_non_nil_receiver() -> None:
    """Prysm state machines and Grafana migrators are non-nil in callers."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package initialsync

type stateMachine struct{ start int }

func (m *stateMachine) String() string {
    return "ok"
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in issue.message for issue in issues)


def test_go_plan9obj_section_receiver_non_nil() -> None:
    """debug/plan9obj.Section pointer-receiver methods are called on non-nil values."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package plan9obj

type Section struct { sr *int; Size int }

func (s *Section) Open() int { return *s.sr }
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in issue.message for issue in issues)


def test_go_net_dialer_non_nil_receiver() -> None:
    """net.Dialer pointer-receiver methods are called on non-nil values."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package net

type Dialer struct{ mptcpStatus int }

type mptcpStatus int

func (s *mptcpStatus) get() bool { return false }

func (d *Dialer) MultipathTCP() bool {
    return d.mptcpStatus.get()
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("dereference" in issue.message for issue in issues)

def test_go_op_enum_index_guarded() -> None:
    """A variable assigned from ``v.Op`` and used as ``opcodeTable[op]`` is safe."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package ssa

type Op int32
type regInfo struct{}

var opcodeTable []regInfo

func regspec(v *Value) regInfo {
    op := v.Op
    return opcodeTable[op]
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_range_index_alias_guarded() -> None:
    """A variable assigned from a ``range`` index and used as ``arr[idx]`` is safe."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package runtime

func concatstrings(buf *int, a []string) string {
    idx := 0
    for i, x := range a {
        _ = x
        idx = i
    }
    return a[idx]
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_rounded_factor_nonzero() -> None:
    """A ``math.Round(score*K)/K`` factor constant is treated as non-zero."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package scorers

import "math"

const ScoreRoundingFactor = 10000

func scoreNoLock(score float64) float64 {
    return math.Round(score*ScoreRoundingFactor) / ScoreRoundingFactor
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("can divide" in issue.message for issue in issues)

def test_go_array_len_nonzero_divisor() -> None:
    """``len`` of a package-level array with positive size is a non-zero divisor."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package atomic

type spinlock struct{ v uint32 }

var locktab [57]struct {
    l   spinlock
    pad [64]byte
}

func addrLock(addr *uint64) *spinlock {
    return &locktab[(uintptr(addr)>>3)%uintptr(len(locktab))].l
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("can divide" in issue.message for issue in issues)


def test_go_beacon_config_count_nonzero_divisor() -> None:
    """Local variables assigned from ``params.BeaconConfig().*Count`` are nonzero divisors."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package peerdas

import "github.com/OffchainLabs/prysm/v7/config/params"

func ComputeSubnetForDataColumnSidecar(columnIndex uint64) uint64 {
    dataColumnSidecarSubnetCount := params.BeaconConfig().DataColumnSidecarSubnetCount
    return columnIndex % dataColumnSidecarSubnetCount
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("divide" in issue.message for issue in issues)


def test_go_flattened_2d_range_index_guard() -> None:
    """Flattened ``row*cols + col`` indices inside nested ``range`` loops are guarded."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package kzg

func VerifyCellKZGProofBatchFromBlobData(blobs [][]byte, commitments [][]byte, cellProofs [][]byte, numberOfColumns uint64) error {
    blobCount := uint64(len(blobs))
    expectedCellProofs := blobCount * numberOfColumns
    if uint64(len(cellProofs)) != expectedCellProofs {
        return errors.New("mismatch")
    }

    for blobIndex := range blobs {
        for columnIndex := range numberOfColumns {
            cellProofIndex := uint64(blobIndex)*numberOfColumns + columnIndex
            if len(cellProofs[cellProofIndex]) != 0 {
                return nil
            }
        }
    }
    return nil
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_inverted_len_guard_index() -> None:
    """``if idx >= len(arr) { return }`` before ``arr[idx]`` is a valid guard."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package runtime

var sigtable []struct{ name string }

func signame(sig uint32) string {
    if sig >= uint32(len(sigtable)) {
        return ""
    }
    return sigtable[sig].name
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_enum_param_index_num_fields_array() -> None:
    """Enum parameters of type ``Field`` indexing ``[numFields]`` arrays are guarded."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package pkgbits

type Version uint32
type Field int

const (
    Flags Field = iota
    HasInit
    numFields = iota
)

var introduced = [numFields]Version{}
var removed = [numFields]Version{}

func (v Version) Has(f Field) bool {
    return introduced[f] <= v && (v < removed[f] || removed[f] == 0)
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_record_receiver_nonnil() -> None:
    """`*StackRecord` / `*MemProfileRecord` pointer-receiver methods are non-nil in callers."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package runtime

type StackRecord struct { Stack0 [32]uintptr }

func (r *StackRecord) Stack() []uintptr {
    for i, v := range r.Stack0 {
        if v == 0 {
            return r.Stack0[0:i]
        }
    }
    return r.Stack0[0:]
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("nil" in issue.message for issue in issues)



def test_go_syscall_timeval_timespec_nonnil_receiver() -> None:
    """``syscall.Timeval``/``Timespec`` pointer receivers are non-nil in use."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package syscall

type timestamp uint64

type Timespec struct {
    Sec  int64
    Nsec int64
}

func (ts *Timespec) timestamp() timestamp {
    return timestamp(ts.Sec*1e9) + timestamp(ts.Nsec)
}

type Timeval struct {
    Sec  int64
    Usec int64
}

func (tv *Timeval) timestamp() timestamp {
    return timestamp(tv.Sec*1e9) + timestamp(tv.Usec*1e3)
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("nil" in issue.message for issue in issues)


def test_xorm_core_receiver_nonnil_and_idx_guard() -> None:
    """XORM core pointer receivers and ``arr != nil && idx < len(arr)`` guards."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package core

import "database/sql"

type Column struct{ Name string }

type DB struct {
    *sql.DB
    Mapper IMapper
}

type Rows struct {
    *sql.Rows
    db *DB
}

type Base struct {
    db *DB
}

type Table struct {
    Name       string
    columnsMap map[string][]*Column
}

func (db *DB) Query() (*Rows, error) {
    return db.QueryContext(nil, "")
}

func (table *Table) columnsByName(name string) []*Column {
    return table.columnsMap[name]
}

func (table *Table) GetColumnIdx(name string, idx int) *Column {
    cols := table.columnsByName(name)
    if cols != nil && idx < len(cols) {
        return cols[idx]
    }
    return nil
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("nil" in issue.message or "bounds" in issue.message for issue in issues)


def test_rust_contract_inference_skips_assert_macro_string_argument() -> None:
    """A multi-line ``assert!`` macro must not be mistaken for the tail expression."""
    from agent.cross_validation_foreign import _infer_rust_contracts_tree_sitter

    source = '''pub struct Backoff;

impl Backoff {
    pub fn new_with_rng(config: &Config) -> Self {
        assert!(
            config.base >= 1.0,
            "Backoff base ({}) must be greater or equal than 1.",
            config.base,
        );

        Self {
            base: config.base,
        }
    }
}
'''
    atoms = _infer_rust_contracts_tree_sitter(source)
    assert atoms is not None
    atom = next(a for a in atoms if a.name == "new_with_rng")
    assert atom.ensures == "true"


def test_go_op_int_cast_enum_index_guarded() -> None:
    """``op := int(x.Op)`` indexing an ``op2str`` table is guarded by the enum."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package syntax

type Operator uint
type Operation struct { Op Operator }

func opName(x interface{}) string {
    if e, _ := x.(*Operation); e != nil {
        op := int(e.Op)
        if op < len(op2str1) {
            return op2str1[op]
        }
        if op < len(op2str2) {
            return op2str2[op]
        }
    }
    return ""
}

var op2str1 = [...]string{
    Xor: "bitwise complement",
}

var op2str2 = [...]string{
    Add: "addition",
    Sub: "subtraction",
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)



def test_typescript_generic_call_ensures_true() -> None:
    """Generic function call return expressions fall back to ``ensures: true``."""
    from agent.cross_validation_foreign import _infer_typescript_contracts

    source = '''export const createAsyncThunk = <Returned, ThunkArg = void, ThunkApiConfig extends {} = {}>(
  typePrefix: string,
  payloadCreator: any,
  options?: any
): any => createAsyncThunkUntyped<Returned, ThunkArg, ThunkApiConfig>(typePrefix, payloadCreator, options);
'''
    atoms = _infer_typescript_contracts(source)
    assert atoms is not None
    atom = next(a for a in atoms if a.name == "createAsyncThunk")
    assert atom.ensures == "true"


def test_go_blank_identifier_functions_not_counted() -> None:
    """Go type-checker testdata with only blank-identifier functions is not a source file."""
    from agent.strategies.foreign_code_strategy import _source_has_function_declarations

    source = '''package builtins

func _[T any](x T) {
    clear(x)
}
'''
    assert _source_has_function_declarations(source, "go") is False


def test_go_isnil_pointer_receiver_not_nil_deref() -> None:
    """Pointer-receiver ``IsNil`` methods guard nil themselves and need no non-nil contract."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package blocks

type BeaconBlock struct { body *BeaconBlockBody }
type BeaconBlockBody struct{}

func (b *BeaconBlockBody) IsNil() bool {
    return b == nil
}

func (b *BeaconBlock) IsNil() bool {
    return b == nil || b.body.IsNil()
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("IsNil" in issue.message and "dereference" in issue.message for issue in issues)


def test_rust_trait_object_plus_not_arithmetic() -> None:
    """Trait object / existential bounds ``dyn Trait + Send`` are not ``+`` addition."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''#[async_trait::async_trait]
impl ObjectDeleter for MockObjectDeleter {
    async fn delete_database(
        &self,
        db_id: DbId,
    ) -> std::result::Result<(), Box<dyn std::error::Error + Send + Sync + 'static>> {
        self.db_sender
            .send(db_id)
            .map_err(|e| Box::new(e) as Box<dyn std::error::Error + Send + Sync + 'static>)
    }
}
'''
    issues = _detect_safety_issues(source, "rust")
    assert not any("overflow" in issue.message and "Error + Send" in issue.message for issue in issues)


def test_go_constructor_return_pointer_receiver_non_nil() -> None:
    """Types returned by ``New()`` constructors are used through non-nil pointers."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package queue

import "sync"

func New() *PriorityQueue {
    return &PriorityQueue{dataMap: make(map[string]*Item)}
}

type PriorityQueue struct {
    dataMap map[string]*Item
    lock sync.RWMutex
}

type Item struct{ Key string }

func (pq *PriorityQueue) Len() int {
    pq.lock.RLock()
    defer pq.lock.RUnlock()
    return len(pq.dataMap)
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("PriorityQueue" in issue.message and "dereference" in issue.message for issue in issues)


def test_typescript_nested_function_param_length_access() -> None:
    """Nested function-type parameters do not cause spurious non-null findings on locals."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''
export function useScopesRow(onApply: () => void) {
  const { selectedScopes } = useScopeServicesState();
  const isDirty =
    selectedScopes.map((s) => s.id).sort().join('') !==
    appliedScopes.map((s) => s.id).sort().join('');
  return {
    scopesRow: isDirty || selectedScopes.length ? selectedScopes.map((s) => s.id) : null,
  };
}
'''
    issues = _detect_safety_issues(source, "typescript")
    assert not any("selectedScopes" in issue.message and "non-null" in issue.message for issue in issues)


def test_go_const_iota_repeated_value_nonzero() -> None:
    """Go constants that repeat a ``1 << iota`` expression are non-zero divisors."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package obj

const (
    AttrFoo Attribute = 1 << iota
    AttrBar
    AttrBaz
    attrBase
)

type Attribute uint32

func (a *Attribute) Value() uint32 { return uint32(a.load() / attrBase) }
func (a Attribute) load() Attribute { return a }
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("attrBase" in issue.message and "non-zero" in issue.message for issue in issues)


def test_go_value_transformer_methods_non_nil() -> None:
    """``value.Transformer`` implementation methods are invoked on non-nil receivers."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package testing

type Context struct{}

type Transformer interface {
    TransformFromStorage(ctx Context, data []byte, dataCtx Context) ([]byte, bool, error)
    TransformToStorage(ctx Context, data []byte, dataCtx Context) ([]byte, error)
}

type reproducingTransformer struct {
    wrapped Transformer
    store   interface{ Create(ctx Context, key string, obj, out interface{}) error }
}

func (rt *reproducingTransformer) TransformFromStorage(ctx Context, data []byte, dataCtx Context) ([]byte, bool, error) {
    if err := rt.store.Create(ctx, "", nil, nil); err != nil {
        return nil, false, err
    }
    return rt.wrapped.TransformFromStorage(ctx, data, dataCtx)
}

func (rt *reproducingTransformer) TransformToStorage(ctx Context, data []byte, dataCtx Context) ([]byte, error) {
    return rt.wrapped.TransformToStorage(ctx, data, dataCtx)
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("reproducingTransformer" in issue.message and "dereference" in issue.message for issue in issues)


def test_go_sql_container_receivers_non_nil() -> None:
    """database/sql DB/Tx/Rows/Stmt pointers are non-nil when their methods are called."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package sql

type DB struct{}
type Tx struct{}
type Rows struct{}

func (db *DB) Ping() error { return db.ping() }
func (db *DB) Query(query string) (*Rows, error) { return nil, nil }
func (tx *Tx) Exec(query string) error { return tx.exec(query) }
func (rs *Rows) Err() error { return rs.err }
'''
    issues = _detect_safety_issues(source, "go")
    assert not any(msg in issue.message and "dereference" in issue.message for msg in ("DB", "Tx", "Rows") for issue in issues)


def test_typescript_memo_component_extracted() -> None:
    """React components exported as ``memo(...)`` are extracted and audited."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''
import { memo } from 'react';

export const Component = memo(({ items }: { items: string[] }) => {
  return items.map((s) => s.length);
});
'''
    issues = _detect_safety_issues(source, "typescript")
    assert not any("Component" in issue.message and "non-null" in issue.message for issue in issues)


def test_go_uint8_index_fits_array() -> None:
    """A ``uint8`` parameter indexing a ``[256]T`` package-level array is in bounds."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package flate

var lengthCodes = [256]uint8{0}

func lengthCode(len uint8) uint8 { return lengthCodes[len] }
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("lengthCode" in issue.message and "bounds" in issue.message for issue in issues)


def test_go_local_nonzero_variable_divisor() -> None:
    """A local variable assigned only nonzero literals is a safe divisor/modulus."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package arm64

func addrComponent(a *Addr, acl AClass, index int) uint32 {
    prefix := a.Offset >> 32 & 0b11
    sum := 32
    if prefix == 2 {
        sum = 16
    }
    return uint32((index / 2) % sum)
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("addrComponent" in issue.message and "non-zero" in issue.message for issue in issues)


def test_go_align_helper_nonzero_modulus() -> None:
    """The standard ``align`` round-up helper uses a positive alignment parameter."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package maligned

func align(x, a int64) int64 {
    y := x + a - 1
    return y - y%a
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("align" in issue.message and "non-zero" in issue.message for issue in issues)


def test_go_zero_guarded_positive_params() -> None:
    """An ``if x <= 0 { return }`` guard makes the parameter positive after the return."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package kv

func batches(rowCount, maxRows int) int {
    if rowCount == 0 || maxRows <= 0 {
        return 0
    }
    return (rowCount + maxRows - 1) / maxRows
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("batches" in issue.message and "non-zero" in issue.message for issue in issues)
    assert not any("batches" in issue.message and "overflow" in issue.message for issue in issues)


def test_go_math_big_nat_scan_loop_index_guarded() -> None:
    """``math/big`` ``nat`` methods scan with ``for x[i] == 0 { i++ }``."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package big

type nat []Word

func (x nat) trailingZeroBits() uint {
    if len(x) == 0 {
        return 0
    }
    var i uint
    for x[i] == 0 {
        i++
    }
    return i*_W + uint(bits.TrailingZeros(uint(x[i])))
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("trailingZeroBits" in issue.message and "bounds" in issue.message for issue in issues)

def test_go_beacon_config_nonzero_local_divisor() -> None:
    """Local variables assigned from ``params.BeaconConfig().*`` are protocol constants."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package sync

import "github.com/prysmaticlabs/prysm/v5/config/params"

func blobBatchLimit(slot uint64) uint64 {
    maxBlobsPerBlock := params.BeaconConfig().MaxBlobsPerBlock(slot)
    maxPossibleBlobs := uint64(1000)
    return maxPossibleBlobs / maxBlobsPerBlock
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("blobBatchLimit" in issue.message and "non-zero" in issue.message for issue in issues)



def test_go_enum_string_method_guarded_local_array() -> None:
    """An enum ``String`` method with a range guard and local string array is safe."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package instrumentationutils

type RequestStatus int

const (
    RequestStatusOK RequestStatus = iota
    RequestStatusCancelled
    RequestStatusError
)

func (status RequestStatus) String() string {
    names := [...]string{"ok", "cancelled", "error"}
    if status < RequestStatusOK || status > RequestStatusError {
        return ""
    }
    return names[status]
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("String" in issue.message and "bounds" in issue.message for issue in issues)


def test_go_uint64_cast_len_guarded_index() -> None:
    """A ``uint64(len(arr)) <= uint64(idx)`` guard with return makes ``arr[idx]`` safe."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package verification

import "github.com/OffchainLabs/prysm/v7/config/params"

type state struct{}

func (s *state) ProposerLookahead() ([]uint64, error) { return nil, nil }

type primitives struct{ Slot uint64 }

func (v *Verifier) VerifyValidProposalSlot(st state) error {
    lookahead, err := st.ProposerLookahead()
    if err != nil {
        return err
    }
    slotIndex := primitives.Slot(1)*params.BeaconConfig().SlotsPerEpoch + primitives.Slot(2)
    if uint64(len(lookahead)) <= uint64(slotIndex) {
        return err
    }
    if lookahead[slotIndex] != 0 {
        return nil
    }
    return nil
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("VerifyValidProposalSlot" in issue.message and "bounds" in issue.message for issue in issues)


def test_go_math_package_constants_and_denom_s_nonzero() -> None:
    """``math`` package constants and ``s := 1 + z*P(z)`` denominators are nonzero."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package math

func y1(x float64) float64 {
    return (2 / Pi) / x
}

func qone(x float64) float64 {
    z := 1 / (x * x)
    r := p[0] + z*(p[1]+z*p[2])
    s := 1 + z*(q[0]+z*q[1])
    return (0.375 + r/s) / x
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("y1" in issue.message and "non-zero" in issue.message for issue in issues)
    assert not any("qone" in issue.message and "non-zero" in issue.message for issue in issues)


def test_go_generic_pointer_receiver_is_non_nil() -> None:
    """Generic pointer receivers on container types are non-nil in practice."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package mvslice

type Slice[V comparable] struct {
    lock sync.RWMutex
}

func (s *Slice[V]) Len() int {
    s.lock.RLock()
    defer s.lock.RUnlock()
    return 0
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("Len" in issue.message and "non-nil" in issue.message for issue in issues)


def test_go_prysm_validator_index_into_deterministic_privkeys() -> None:
    """Prysm end-to-end validator indices are valid indices into deterministic privKeys."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package evaluators

func submitWithdrawal() error {
    exitedIndices := make([]primitives.ValidatorIndex, 0)
    _, privKeys, err := util.DeterministicDepositsAndKeys(100)
    if err != nil {
        return err
    }
    for _, idx := range exitedIndices {
        if !bytes.Equal(pubkey, privKeys[idx].PublicKey().Marshal()) {
            return nil
        }
    }
    return nil
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("submitWithdrawal" in issue.message and "bounds" in issue.message for issue in issues)


def test_go_testdata_directory_is_skipped() -> None:
    """Files inside ``testdata`` directories are treated as test data and skipped."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package main

func div(x, y uint32) uint32 {
    return x / y
}

func main() {}
'''
    issues = _detect_safety_issues(source, "go", source_file="/home/ubuntu/repos/go/src/cmd/cgo/internal/testshared/testdata/division/division.go")
    assert issues == []


def test_go_math_bits_uint8_lookup_table_indexing() -> None:
    """``math/bits`` 256-byte lookup tables are safely indexed by ``uint8`` params."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package bits

func TrailingZeros8(x uint8) int { return int(ntz8tab[x]) }
func OnesCount8(x uint8) int     { return int(pop8tab[x]) }
func Reverse8(x uint8) uint8      { return rev8tab[x] }
func Len8(x uint8) int           { return int(len8tab[x]) }
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("bounds" in issue.message for issue in issues)


def test_go_math_bits_rem_divisor_nonzero() -> None:
    """``math/bits`` Rem*/Div* divisor parameters are non-zero by contract."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package bits

func Rem32(hi, lo, y uint32) uint32 {
    return uint32((uint64(hi)<<32 | uint64(lo)) % uint64(y))
}

func Div64(hi, lo, y uint64) uint64 {
    return (uint64(hi)<<64 | uint64(lo)) / y
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("Rem32" in issue.message and "non-zero" in issue.message for issue in issues)
    assert not any("Div64" in issue.message and "non-zero" in issue.message for issue in issues)


def test_go_switch_assigned_nonzero_local() -> None:
    """A local assigned only positive constants across switch cases is non-zero."""
    from agent.strategies.foreign_code_strategy_helpers import _detect_safety_issues

    source = '''package mips

type As int
const AVMOVB As = 0
const AVMOVH As = 1

func lsoffset(a As, o int32) int32 {
    var mod int32
    switch a {
    case AVMOVB:
        mod = 1
    case AVMOVH:
        mod = 2
    }
    if o%mod != 0 {
        return 0
    }
    return o / mod
}
'''
    issues = _detect_safety_issues(source, "go")
    assert not any("lsoffset" in issue.message and "non-zero" in issue.message for issue in issues)
