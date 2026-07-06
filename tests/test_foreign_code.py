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

    with patch("agent.cross_validation.run_lean_bridge") as bridge_mock:
        bridge_mock.return_value = {
            "success": True,
            "lean_cert": lean_cert,
            "stdout": "",
            "stderr": "",
        }
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
