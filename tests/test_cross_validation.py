"""Tests for P14 cross-validation flows."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.config import AgentConfig
from agent.cross_validation import (
    build_validate_code_to_spec_parser,
    build_validate_code_parser,
    build_validate_spec_to_code_parser,
    build_validate_spec_parser,
    main_validate_spec_to_code,
    validate_code_to_spec,
    main_validate_code,
    validate_foreign_code,
    validate_nl_spec,
    validate_spec_to_code,
)
from agent.report_formatter import format_cross_validation_report
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
    assert any(issue.kind == "overconstraint" for issue in result.overconstraints)


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


def test_validate_nl_spec_keeps_llm_non_category_issues() -> None:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(
        {
            "atoms": [],
            "issues": [
                {
                    "kind": "verification",
                    "message": "The inferred contract needs verifier attention.",
                    "evidence": "unverified temporal claim",
                }
            ],
        }
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response
    config = AgentConfig(api_key="test", model="test-model")
    config.create_client = MagicMock(return_value=client)

    result = validate_nl_spec(
        "The function updates state safely.",
        config=config,
        use_llm=True,
        run_mumei=False,
    )

    assert result.success is False
    assert result.overconstraints[0].kind == "verification"


def test_validate_nl_spec_reports_unsupported_mixed_z3_clauses() -> None:
    result = validate_nl_spec(
        "requires: x > 0;\nensures: result == max(x, 0);",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.satisfiable is True
    assert any("Skipped unsupported Z3 clause" in warning for warning in result.warnings)


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


def test_validate_spec_to_code_detects_missing_requires(tmp_path: Path) -> None:
    code_path = tmp_path / "impl.py"
    code_path.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

    result = validate_spec_to_code(
        "requires: x > 0;\nensures: result == x;",
        str(code_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.missing_constraints
    assert result.missing_constraints[0].kind == "missing_implementation"
    assert "x > 0" in result.missing_constraints[0].evidence


def test_validate_spec_to_code_surfaces_spec_validation_issues(tmp_path: Path) -> None:
    code_path = tmp_path / "impl.py"
    code_path.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

    result = validate_spec_to_code(
        "常に残高を更新する、かつ決して残高を更新する。requires: true;\nensures: result == x;",
        str(code_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert any(issue.message.startswith("Spec validation issue") for issue in result.divergences)


def test_validate_code_to_spec_detects_postcondition_drift(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.txt"
    code_path = tmp_path / "impl.py"
    spec_path.write_text("requires: true;\nensures: result == x + 1;", encoding="utf-8")
    code_path.write_text("def inc(x: int) -> int:\n    return x + 2\n", encoding="utf-8")

    result = validate_code_to_spec(
        str(code_path),
        str(spec_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.drift_issues
    assert result.drift_issues[0].kind == "drift"


def test_validate_code_to_spec_detects_undocumented_code_precondition(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.txt"
    code_path = tmp_path / "impl.py"
    spec_path.write_text("requires: true;\nensures: result == a // b;", encoding="utf-8")
    code_path.write_text("def div(a: int, b: int) -> int:\n    return a // b\n", encoding="utf-8")

    result = validate_code_to_spec(
        str(code_path),
        str(spec_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert any("not documented" in issue.message for issue in result.drift_issues)


def test_validate_spec_to_code_cli_emits_japanese_report(tmp_path: Path, capsys) -> None:
    spec_path = tmp_path / "spec.txt"
    code_path = tmp_path / "impl.py"
    report_path = tmp_path / "report.md"
    spec_path.write_text("requires: true;\nensures: result == a + b;", encoding="utf-8")
    code_path.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    args = build_validate_spec_to_code_parser().parse_args(
        [
            "--spec",
            str(spec_path),
            "--code",
            str(code_path),
            "--lang",
            "ja",
            "--output",
            str(report_path),
            "--no-llm",
            "--no-mumei",
        ]
    )

    result = main_validate_spec_to_code(args)
    captured = capsys.readouterr()

    assert result.success is True
    assert "仕様→コード整合性レポート" in captured.out
    assert "実装漏れ・仕様ドリフトは検出されませんでした" in report_path.read_text(encoding="utf-8")


def test_new_cross_validation_parsers_accept_lang_and_paths() -> None:
    spec_to_code_args = build_validate_spec_to_code_parser().parse_args(
        ["--spec", "spec.txt", "--code", "code.py", "--lang", "ja", "--format", "human", "--no-mumei"]
    )
    code_to_spec_args = build_validate_code_to_spec_parser().parse_args(
        ["--code", "code.py", "--spec", "spec.txt", "--lang", "en", "--format", "json", "--no-llm"]
    )

    assert spec_to_code_args.lang == "ja"
    assert spec_to_code_args.format == "human"
    assert spec_to_code_args.code == "code.py"
    assert code_to_spec_args.spec == "spec.txt"
    assert code_to_spec_args.format == "json"


def test_cross_validation_formatter_highlights_human_review() -> None:
    result = {
        "success": False,
        "code_path": "impl.py",
        "language": "python",
        "spec_atoms": [],
        "code_atoms": [],
        "drift_issues": [
            {
                "kind": "drift",
                "message": "Spec postcondition is stale.",
                "evidence": "result == x + 1",
                "location": "inc",
            }
        ],
        "changed_hunks": ["@@ -1 +1 @@\n-return x + 1\n+return x + 2"],
        "warnings": [],
        "errors": [],
    }

    report = format_cross_validation_report(result, lang="ja")

    assert "コード→仕様ドリフトレポート" in report
    assert "Human-in-the-Loop" in report


def test_cross_validation_prompts_include_json_schema() -> None:
    nl_prompt = build_nl_cross_validation_prompt("常にXかつ決してX")
    code_prompt = build_code_cross_validation_prompt("def add(a, b): return a + b", "python")

    assert "requires" in nl_prompt
    assert "ensures" in nl_prompt
    assert "```json" in code_prompt
    assert "def add" in code_prompt


def test_validate_nl_spec_sets_spec_internal_contradiction_type() -> None:
    """Spec-internal contradictions set contradiction_type == 'spec_internal'."""
    spec = (
        "常に残高を更新する、かつ決して残高を更新する。"
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
    assert result.contradiction_type == "spec_internal"


def test_validate_spec_to_code_sets_spec_vs_code_contradiction_type(tmp_path: Path) -> None:
    """Code comparison divergence sets contradiction_type to a spec_vs_code variant."""
    code_path = tmp_path / "impl.py"
    code_path.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

    result = validate_spec_to_code(
        "requires: x > 0;\nensures: result == x;",
        str(code_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    # The spec has a stronger precondition than the code
    assert result.contradiction_type in ("spec_stronger", "spec_vs_code")
