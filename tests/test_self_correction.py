from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent.config import AgentConfig
from agent.self_correction import StructuredFeedbackSelfCorrectionLoop


class FakeMumeiClient:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results
        self.index = 0

    def verify(self, _source_path: str) -> dict[str, object]:
        result = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return result


def failed_result(case_id: int = 0) -> dict[str, object]:
    return {
        "success": False,
        "stderr": "postcondition failed",
        "report": {
            "failure_type": "postcondition_violated",
            "structured_feedback": {
                "status": "verification_failed",
                "error_type": "postcondition_violated",
                "location": {"file": "sample.mm", "line": 1},
                "reconstruction_loss": {
                    "violated_property": "result > 0",
                    "counter_example": {"case": case_id},
                    "loss_set_size": 1,
                    "is_zero_loss": False,
                    "loss_vector": [
                        {
                            "violated_property": "result > 0",
                            "counter_example": {"case": case_id},
                            "magnitude": 1.0,
                            "components": [],
                        }
                    ],
                },
                "feedback_instruction": "Repair the body so the ensures clause holds.",
            },
        },
    }


def passed_result() -> dict[str, object]:
    return {
        "success": True,
        "stderr": "",
        "report": {
            "structured_feedback": {
                "status": "verification_passed",
                "error_type": None,
                "location": None,
                "reconstruction_loss": None,
                "feedback_instruction": "Verification passed; no fix is required.",
            }
        },
    }


def test_self_correction_loop_converges_after_two_successes(tmp_path: Path) -> None:
    source = tmp_path / "sample.mm"
    source.write_text("broken", encoding="utf-8")
    repair_calls = 0

    def repair_fn(*args: object) -> str:
        nonlocal repair_calls
        repair_calls += 1
        report = args[4]
        if isinstance(report, dict):
            report["llm_tokens_used"] = 10
        return "fixed"

    loop = StructuredFeedbackSelfCorrectionLoop(
        SimpleNamespace(),  # type: ignore[arg-type]
        "model",
        FakeMumeiClient([failed_result(), passed_result(), passed_result()]),  # type: ignore[arg-type]
        max_retries=10,
        convergence_threshold=2,
        max_tokens=100,
        repair_fn=repair_fn,  # type: ignore[arg-type]
    )

    result = loop.run(source, json.dumps(failed_result()["report"]["structured_feedback"]))

    assert result.converged
    assert result.repair_attempts == 1
    assert result.consecutive_successes == 2
    assert result.token_cost == 10
    assert repair_calls == 1
    assert source.read_text(encoding="utf-8") == "fixed"


def test_self_correction_loop_stops_on_token_budget(tmp_path: Path) -> None:
    source = tmp_path / "sample.mm"
    source.write_text("broken", encoding="utf-8")

    def repair_fn(*args: object) -> str:
        report = args[4]
        if isinstance(report, dict):
            report["llm_tokens_used"] = 100
        return "still broken"

    loop = StructuredFeedbackSelfCorrectionLoop(
        SimpleNamespace(),  # type: ignore[arg-type]
        "model",
        FakeMumeiClient([failed_result(), failed_result()]),  # type: ignore[arg-type]
        max_retries=10,
        convergence_threshold=2,
        max_tokens=50,
        repair_fn=repair_fn,  # type: ignore[arg-type]
    )

    result = loop.run(source, failed_result()["report"]["structured_feedback"])  # type: ignore[arg-type]

    assert not result.converged
    assert result.stop_reason == "token_cost_exceeded"
    assert result.token_cost == 100


def test_self_correction_deterministic_convergence_rate_at_least_70_percent(tmp_path: Path) -> None:
    converged = 0

    def repair_fn(*args: object) -> str:
        report = args[4]
        if isinstance(report, dict):
            report["llm_tokens_used"] = 5
        return "fixed"

    for case_id in range(10):
        source = tmp_path / f"case_{case_id}.mm"
        source.write_text("broken", encoding="utf-8")
        results = (
            [failed_result(case_id), passed_result(), passed_result()]
            if case_id < 7
            else [failed_result(case_id)]
        )
        loop = StructuredFeedbackSelfCorrectionLoop(
            SimpleNamespace(),  # type: ignore[arg-type]
            "model",
            FakeMumeiClient(results),  # type: ignore[arg-type]
            max_retries=10,
            convergence_threshold=2,
            max_tokens=1000,
            repair_fn=repair_fn,  # type: ignore[arg-type]
        )
        result = loop.run(source, failed_result(case_id)["report"]["structured_feedback"])  # type: ignore[arg-type]
        if result.converged:
            converged += 1

    assert converged / 10 >= 0.7


def test_config_exposes_self_correction_flags(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_SELF_CORRECTION", "true")
    monkeypatch.setenv("SELF_CORRECTION_MAX_ATTEMPTS", "8")
    monkeypatch.setenv("SELF_CORRECTION_CONVERGENCE_THRESHOLD", "2")

    config = AgentConfig()

    assert config.enable_self_correction is True
    assert config.self_correction_max_attempts == 8
    assert config.self_correction_convergence_threshold == 2


def test_config_self_correction_max_tokens_default_and_override(monkeypatch) -> None:
    config = AgentConfig()
    assert config.self_correction_max_tokens == 10000

    monkeypatch.setenv("SELF_CORRECTION_MAX_TOKENS", "5000")
    config2 = AgentConfig()
    assert config2.self_correction_max_tokens == 5000
