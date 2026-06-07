"""Tests for P14 cross-validation flows."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.config import AgentConfig
from agent.cross_validation import (
    build_validate_code_parser,
    build_validate_spec_parser,
    main_validate_code,
    validate_foreign_code,
    validate_nl_spec,
)
from agent.prompts.cross_validation_code import build_code_cross_validation_prompt
from agent.prompts.cross_validation_nl import build_nl_cross_validation_prompt


def test_validate_nl_spec_detects_contradiction_ambiguity_and_unsat_contract() -> None:
    spec = (
        "常に残高を更新する、かつ決して残高を更新する。"
        "入力は適切に検証する。"
        "requires: x > 0 && x < 0;\n"
        "ensures: result == x;"
    )

    result = validate_nl_spec(
        spec,
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.contradictions
    assert result.ambiguities
    assert result.satisfiable is False
    assert any(issue.kind == "satisfiability" for issue in result.overconstraints)


def test_validate_foreign_code_infers_python_contract_and_runs_mumei() -> None:
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            code,
            "python",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is True
    assert result.language == "python"
    assert result.inferred_atoms[0].name == "add"
    assert result.inferred_atoms[0].ensures == "result == a + b"
    assert "trusted atom add" in result.mumei_source
    mumei.verify.assert_called_once()


def test_validate_foreign_code_adds_division_safety_precondition() -> None:
    code = "def divide(a: int, b: int) -> int:\n    return a // b\n"

    result = validate_foreign_code(
        code,
        "python",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is True
    assert result.inferred_atoms[0].requires == "b != 0"


def test_validate_code_cli_writes_json_report(tmp_path: Path) -> None:
    source = tmp_path / "code.py"
    output = tmp_path / "report.json"
    source.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    args = build_validate_code_parser().parse_args(
        [
            "--input",
            str(source),
            "--language",
            "python",
            "--output",
            str(output),
            "--no-llm",
            "--no-mumei",
        ]
    )

    result = main_validate_code(args)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result.success is True
    assert payload["success"] is True
    assert payload["inferred_atoms"][0]["name"] == "add"


def test_validate_spec_and_code_parsers_accept_required_flags() -> None:
    spec_args = build_validate_spec_parser().parse_args(
        ["--input", "spec.txt", "--format", "nl", "--no-llm"]
    )
    code_args = build_validate_code_parser().parse_args(
        ["--input", "code.py", "--language", "python", "--no-mumei"]
    )

    assert spec_args.input == "spec.txt"
    assert spec_args.format == "nl"
    assert code_args.language == "python"


def test_cross_validation_prompts_include_json_schema() -> None:
    nl_prompt = build_nl_cross_validation_prompt("常にXかつ決してX")
    code_prompt = build_code_cross_validation_prompt("def add(a, b): return a + b", "python")

    assert "requires" in nl_prompt
    assert "ensures" in nl_prompt
    assert "```json" in code_prompt
    assert "def add" in code_prompt
