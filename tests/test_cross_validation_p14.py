from __future__ import annotations

import json
from pathlib import Path

from agent.config import AgentConfig
from agent.cross_validation import detect_intent_drift, validate_foreign_code, validate_nl_spec
from agent.human_review import HumanReviewQueue


def test_p14_a_detects_requires_ensures_contradiction_and_false_requires() -> None:
    contradiction = validate_nl_spec(
        "requires: x > 0;\nensures: x < 0;",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )
    overconstraint = validate_nl_spec(
        "requires: false;\nensures: result >= 0;",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert contradiction.success is False
    assert any(issue.kind == "contradiction" for issue in contradiction.contradictions)
    assert contradiction.contradiction_evidence
    assert any(issue.kind == "overconstraint" for issue in overconstraint.overconstraints)
    assert "false" in overconstraint.overconstraint_evidence


def test_p14_b_infers_python_abs_contract_for_foreign_code() -> None:
    result = validate_foreign_code(
        "def abs_i64(x: int) -> int:\n    return abs(x)\n",
        "python",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is True
    assert result.inferred_atoms[0].name == "abs_i64"
    assert "result >= 0" in result.inferred_atoms[0].ensures
    assert "result == -x" in result.inferred_atoms[0].ensures
    assert "trusted atom abs_i64" in result.mumei_source


def test_p14_c_detects_intent_drift_and_returns_integrated_report() -> None:
    report = detect_intent_drift(
        "requires: true;\nensures: result == x + 1;",
        "def inc(x: int) -> int:\n    return x + 2\n",
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
    )

    assert report.success is False
    assert report.drift_detected is True
    assert any(issue.kind == "drift" for issue in report.issues)
    assert report.mapping.success is True
    assert "Spec↔Code Cross-Validation Report" in report.report


def test_p14_d_exports_human_review_markdown(tmp_path: Path) -> None:
    queue_path = tmp_path / "human_review_queue.json"
    queue_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "file": "contracts/review.mm",
                "atoms": [
                    {
                        "name": "contradictory_abs",
                        "reason": "contradiction",
                        "priority": "high",
                        "contradiction": "requires x > 0, ensures x < 0",
                        "drift": "implementation returns x + 2",
                        "suggested_action": "Update the contract or implementation before merge.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    queue = HumanReviewQueue(queue_path)
    queue.load()

    markdown = queue.export_review_markdown()

    assert "<!-- mumei-human-review -->" in markdown
    assert "contradictory_abs" in markdown
    assert "contradiction" in markdown
    assert "GitHub PR action" in markdown
