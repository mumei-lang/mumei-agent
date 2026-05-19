"""Tests for budget-aware self-healing orchestration."""
from __future__ import annotations

import sys
from types import SimpleNamespace

from agent import self_healing


def test_first_allowed_attempt_reaches_get_fix(monkeypatch, tmp_path) -> None:
    source = tmp_path / "broken.mm"
    source.write_text("atom broken() -> i64 body: { 0 }\n", encoding="utf-8")
    policy = tmp_path / "budget.json"
    policy.write_text('{"max_attempts": 1}', encoding="utf-8")

    verify_calls = 0
    get_fix_calls = []
    history_lengths = []

    class FakeMumeiClient:
        def verify(self, _source_file: str) -> dict:
            nonlocal verify_calls
            verify_calls += 1
            if verify_calls == 1:
                return {
                    "success": False,
                    "stdout": "verification failed",
                    "stderr": "",
                    "report": {
                        "failure_type": "postcondition_violated",
                        "counterexample": {"x": 1},
                    },
                }
            return {"success": True, "stdout": "", "stderr": "", "report": {}}

    def fake_get_fix(*_args, **kwargs) -> str:
        get_fix_calls.append(kwargs["action_class"])
        history = kwargs["retry_history"]
        history_lengths.append(len(history.attempts))
        _args[4]["llm_tokens_used"] = 123
        return "atom fixed() -> i64 body: { 1 }\n"

    class FakePatternLibrary:
        def record(self, **_kwargs) -> None:
            pass

    monkeypatch.setattr(sys, "argv", [
        "agent",
        str(source),
        "--budget-policy",
        str(policy),
    ])
    monkeypatch.setattr(
        self_healing.AgentConfig,
        "create_client",
        lambda self: SimpleNamespace(),
    )
    monkeypatch.setattr(
        self_healing,
        "create_mumei_client",
        lambda _bin: FakeMumeiClient(),
    )
    monkeypatch.setattr(self_healing, "get_fix", fake_get_fix)
    monkeypatch.setattr(self_healing, "PatternLibrary", FakePatternLibrary)
    monkeypatch.setattr(self_healing.time, "sleep", lambda _seconds: None)

    self_healing.main()

    assert get_fix_calls == ["postcondition_fix"]
    assert history_lengths == [0]
    assert verify_calls == 2


def test_llm_token_usage_is_recorded_after_fix_selection(monkeypatch, tmp_path) -> None:
    source = tmp_path / "broken.mm"
    source.write_text("atom broken() -> i64 body: { 0 }\n", encoding="utf-8")
    policy = tmp_path / "budget.json"
    policy.write_text('{"max_attempts": 1, "max_tokens": 1000}', encoding="utf-8")

    recorded_tokens = []

    class FakeMumeiClient:
        def __init__(self) -> None:
            self.verify_calls = 0

        def verify(self, _source_file: str) -> dict:
            self.verify_calls += 1
            if self.verify_calls == 1:
                return {
                    "success": False,
                    "stdout": "verification failed",
                    "stderr": "",
                    "report": {
                        "failure_type": "postcondition_violated",
                        "counterexample": {"x": 1},
                    },
                }
            return {"success": True, "stdout": "", "stderr": "", "report": {}}

    def fake_get_fix(*_args, **_kwargs) -> str:
        _args[4]["llm_tokens_used"] = 456
        return "atom fixed() -> i64 body: { 1 }\n"

    def fake_aggregate_metrics(history):
        recorded_tokens.append(history.total_tokens())
        return SimpleNamespace(
            attempts_to_success=len(history.attempts),
            tokens_to_success=history.total_tokens(),
            solver_seconds_to_success=0.0,
            spec_drift_score=0.0,
        )

    class FakePatternLibrary:
        def record(self, **_kwargs) -> None:
            pass

    monkeypatch.setattr(sys, "argv", [
        "agent",
        str(source),
        "--budget-policy",
        str(policy),
    ])
    monkeypatch.setattr(
        self_healing.AgentConfig,
        "create_client",
        lambda self: SimpleNamespace(),
    )
    monkeypatch.setattr(
        self_healing,
        "create_mumei_client",
        lambda _bin: FakeMumeiClient(),
    )
    monkeypatch.setattr(self_healing, "get_fix", fake_get_fix)
    monkeypatch.setattr(self_healing, "aggregate_metrics", fake_aggregate_metrics)
    monkeypatch.setattr(self_healing, "PatternLibrary", FakePatternLibrary)
    monkeypatch.setattr(self_healing.time, "sleep", lambda _seconds: None)

    self_healing.main()

    assert recorded_tokens == [456]
