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
        )
    ]


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
    assert "trusted atom safe_divide" in result["mumei_source"]
    mumei.verify.assert_called_once()


def test_mcp_verify_foreign_code_tool_returns_json_payload() -> None:
    fake_client = MagicMock()
    fake_client.verify.return_value = {"success": True, "report": {}, "stdout": "{}", "stderr": ""}

    with patch(
        "agent.strategies.foreign_code_strategy.create_mumei_client",
        return_value=fake_client,
    ):
        result = _payload(
            mcp_server.verify_foreign_code(
                "def add(a: int, b: int) -> int:\n    return a + b\n",
                "python",
            )
        )

    assert result["status"] == "ok"
    assert result["success"] is True
    assert result["specs"][0]["function_name"] == "add"


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
