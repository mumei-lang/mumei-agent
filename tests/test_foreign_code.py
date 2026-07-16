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
    assert "DERIVED" not in constants  # non-literal initializer skipped


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


def test_params_from_signature_handles_nested_commas_in_generics() -> None:
    """Generic Rust parameters must not be split on commas inside nested parentheses."""
    from agent.cross_validation_foreign import _params_from_signature

    signature = "table: impl IntoIterator<Item = (K, &'a V)> + 'a, hide_zeros: bool"
    params = _params_from_signature(signature)
    assert [param.name for param in params] == ["table", "hide_zeros"]


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
    assert "result == True" in atoms[0].ensures


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
    assert "result == True" in atoms[0].ensures


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
