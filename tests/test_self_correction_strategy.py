from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent.strategies import self_correction_strategy
from agent.strategies.self_correction_strategy import SelfCorrectionStrategy


class FakeMumeiClient:
    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.index = 0

    def verify(self, _source_path: str) -> dict:
        result = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return result


def test_self_correction_converges_after_three_successes(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "sample.mm"
    source.write_text("broken", encoding="utf-8")
    client = FakeMumeiClient([
        {
            "success": False,
            "stdout": "",
            "stderr": "failed",
            "report": {
                "failure_type": "postcondition_violated",
                "counterexample": {"x": 1},
                "reconstruction_loss": {
                    "violated_property": "result > 0",
                    "counter_example": {"x": 1},
                    "loss_vector": [1.0],
                },
            },
        },
        {"success": True, "stdout": "", "stderr": "", "report": {}},
        {"success": True, "stdout": "", "stderr": "", "report": {}},
        {"success": True, "stdout": "", "stderr": "", "report": {}},
    ])

    def fake_get_fix(*args, **_kwargs) -> str:
        report = args[4]
        report["llm_tokens_used"] = 10
        return "fixed"

    monkeypatch.setattr(self_correction_strategy.fix_strategy, "get_fix", fake_get_fix)
    strategy = SelfCorrectionStrategy(
        SimpleNamespace(),
        "model",
        client,  # type: ignore[arg-type]
        max_repairs=10,
        required_successes=3,
        max_tokens=100,
    )

    result = strategy.run(source)

    assert result.converged
    assert result.repair_attempts == 1
    assert result.total_tokens == 10
    assert source.read_text(encoding="utf-8") == "fixed"
    assert result.to_dict()["self_correction_metadata"]["converged"] is True


def test_self_correction_stops_on_token_budget(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "sample.mm"
    source.write_text("broken", encoding="utf-8")
    client = FakeMumeiClient([
        {
            "success": False,
            "stdout": "",
            "stderr": "failed",
            "report": {"failure_type": "postcondition_violated", "counterexample": {"x": 1}},
        },
        {
            "success": False,
            "stdout": "",
            "stderr": "failed",
            "report": {"failure_type": "postcondition_violated", "counterexample": {"x": 2}},
        },
    ])

    def fake_get_fix(*args, **_kwargs) -> str:
        report = args[4]
        report["llm_tokens_used"] = 50
        return "still broken"

    monkeypatch.setattr(self_correction_strategy.fix_strategy, "get_fix", fake_get_fix)
    strategy = SelfCorrectionStrategy(
        SimpleNamespace(),
        "model",
        client,  # type: ignore[arg-type]
        max_repairs=10,
        required_successes=3,
        max_tokens=50,
    )

    result = strategy.run(source)

    assert not result.converged
    assert result.total_tokens == 50
    assert result.stop_reason == "token_cost_exceeded"
