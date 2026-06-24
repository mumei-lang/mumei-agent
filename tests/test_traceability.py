"""Tests for bidirectional traceability verification."""
from __future__ import annotations

import json
from pathlib import Path

from agent.config import AgentConfig
from agent.traceability_verifier import verify_traceability
from agent.verify_traceability import _emit as emit_traceability_report


def test_verify_traceability_combines_conformance_and_drift(tmp_path: Path) -> None:
    code = tmp_path / "impl.py"
    spec = tmp_path / "spec.txt"
    code.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")
    spec.write_text("requires: x >= 0;\nensures: result == x + 1;", encoding="utf-8")

    result = verify_traceability(
        spec.read_text(encoding="utf-8"),
        str(code),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
        spec_path=str(spec),
        lang="en",
    )
    payload = result.__dict__

    assert result.success is False
    assert result.conformance["unimplemented_conditions"]
    assert result.conformance["traceability_matrix"]
    assert result.drift["spec_gaps"]
    assert result.drift["drift_issues"]
    assert result.cross_validation_gaps
    assert 0.0 <= result.drift_score <= 1.0
    assert result.next_steps == [
        {
            "priority": "high",
            "action": "Review bidirectional traceability gaps before merge.",
            "command": f"mumei-agent verify-traceability --code {code} --spec {spec} --format human",
        }
    ]
    assert "human_review" not in payload
    assert "recommendations" not in payload
    assert "review_actions" not in payload


def test_verify_traceability_report_keeps_next_steps_before_findings(tmp_path: Path) -> None:
    code = tmp_path / "impl.py"
    spec = tmp_path / "spec.txt"
    code.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")
    spec.write_text("requires: x >= 0;\nensures: result == x + 1;", encoding="utf-8")

    result = verify_traceability(
        spec.read_text(encoding="utf-8"),
        str(code),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
        spec_path=str(spec),
        lang="en",
    )

    assert "## Bidirectional Traceability Report" in result.report
    assert result.report.index("### next_steps (V1-E-1)") < result.report.index(
        "### Findings"
    )
    assert "`conformance`" in result.report
    assert "`drift`" in result.report


def test_verify_traceability_cli_json_keeps_next_steps_first(
    tmp_path: Path,
    capsys,
) -> None:
    code = tmp_path / "impl.py"
    output = tmp_path / "traceability.json"
    spec = tmp_path / "spec.txt"
    code.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")
    spec.write_text("requires: x >= 0;\nensures: result == x + 1;", encoding="utf-8")
    result = verify_traceability(
        spec.read_text(encoding="utf-8"),
        str(code),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
        spec_path=str(spec),
        lang="en",
    )

    emit_traceability_report(result, str(output), "json", "en")
    capsys.readouterr()
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert text.lstrip().startswith('{\n  "next_steps"')
    assert payload["next_steps"] == result.next_steps
    assert payload["cross_validation_gaps"] == result.cross_validation_gaps
    assert "recommendations" not in payload
    assert "review_actions" not in payload
    assert "human_review" not in payload
