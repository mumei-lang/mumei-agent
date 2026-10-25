from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.charter_guard import CharterGuard
from agent.strategies import self_correction_strategy
from agent.strategies.self_correction_strategy import SelfCorrectionStrategy


class FakeMumeiClient:
    def __init__(self, results: list[dict], checks: list[dict] | None = None) -> None:
        self.results = results
        self.index = 0
        self.checks = checks or []

    def verify(self, _source_path: str) -> dict:
        result = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return result

    def charter_check(
        self, _source: str, _lock: str, cwd: Path | None = None
    ) -> dict:
        return self.checks.pop(0)


def _guarded_project(tmp_path: Path) -> tuple[Path, Path, CharterGuard]:
    source = tmp_path / "sample.mm"
    source.write_text("original", encoding="utf-8")
    charter = tmp_path / "sample.charter.mm"
    charter.write_text("pinned charter", encoding="utf-8")
    lock = tmp_path / "charter.lock"
    lock.write_text(
        json.dumps(
            {
                "schema": "mumei.charter-lock/v1",
                "charters": [{"path": charter.name}],
            }
        ),
        encoding="utf-8",
    )
    guard = CharterGuard.discover(str(source), str(lock))
    assert guard is not None
    return source, charter, guard


def _charter_result(passed: bool) -> dict:
    return {
        "exit_code": 0 if passed else 1,
        "report": {"status": "pass" if passed else "fail", "atoms": []},
        "stdout": "",
        "stderr": "",
    }


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


def test_charter_failure_is_retried_with_feedback_and_can_pass(
    monkeypatch, tmp_path: Path
) -> None:
    source, _charter, guard = _guarded_project(tmp_path)
    client = FakeMumeiClient(
        [
            {"success": True, "stdout": "", "stderr": "", "report": {}},
            {"success": True, "stdout": "", "stderr": "", "report": {}},
        ],
        [_charter_result(False), _charter_result(True)],
    )
    calls: list[tuple[str, dict]] = []

    def fake_get_fix(*args, **_kwargs) -> str:
        report = args[4]
        report["llm_tokens_used"] = 1
        calls.append((args[3], report))
        return "repaired"

    monkeypatch.setattr(self_correction_strategy.fix_strategy, "get_fix", fake_get_fix)
    strategy = SelfCorrectionStrategy(
        SimpleNamespace(),
        "model",
        client,  # type: ignore[arg-type]
        max_repairs=2,
        required_successes=1,
        guard=guard,
    )

    result = strategy.run(source)

    assert result.converged
    assert source.read_text(encoding="utf-8") == "repaired"
    assert len(calls) == 1
    assert "charter" in calls[0][0].lower()
    assert calls[0][1]["failure_type"] == "charter_violation"
    assert calls[0][1]["loss_vector"]["error_type"] == "charter_violation"


def test_charter_tampering_restores_source_and_stops(
    monkeypatch, tmp_path: Path
) -> None:
    source, charter, guard = _guarded_project(tmp_path)
    original_source = source.read_bytes()
    client = FakeMumeiClient(
        [{"success": True, "stdout": "", "stderr": "", "report": {}}],
        [_charter_result(False)],
    )

    def fake_get_fix(*_args, **_kwargs) -> str:
        charter.write_text("modified", encoding="utf-8")
        return "candidate"

    monkeypatch.setattr(self_correction_strategy.fix_strategy, "get_fix", fake_get_fix)
    strategy = SelfCorrectionStrategy(
        SimpleNamespace(),
        "model",
        client,  # type: ignore[arg-type]
        max_repairs=2,
        required_successes=1,
        guard=guard,
    )

    result = strategy.run(source)

    assert not result.converged
    assert result.stop_reason == "charter_tampered"
    assert source.read_bytes() == original_source


def test_final_charter_failure_restores_original_source(
    monkeypatch, tmp_path: Path
) -> None:
    source, _charter, guard = _guarded_project(tmp_path)
    original_source = source.read_bytes()
    client = FakeMumeiClient(
        [
            {"success": True, "stdout": "", "stderr": "", "report": {}},
            {"success": True, "stdout": "", "stderr": "", "report": {}},
        ],
        [_charter_result(False), _charter_result(False)],
    )

    def fake_get_fix(*args, **_kwargs) -> str:
        args[4]["llm_tokens_used"] = 1
        return "charter-invalid candidate"

    monkeypatch.setattr(self_correction_strategy.fix_strategy, "get_fix", fake_get_fix)
    strategy = SelfCorrectionStrategy(
        SimpleNamespace(),
        "model",
        client,  # type: ignore[arg-type]
        max_repairs=1,
        required_successes=1,
        guard=guard,
    )

    result = strategy.run(source)

    assert not result.converged
    assert source.read_bytes() == original_source


def test_final_verification_failure_keeps_candidate_source(
    monkeypatch, tmp_path: Path
) -> None:
    source, _charter, guard = _guarded_project(tmp_path)
    client = FakeMumeiClient(
        [
            {
                "success": False,
                "stdout": "",
                "stderr": "verification failed",
                "report": {
                    "failure_type": "postcondition_violated",
                    "reconstruction_loss": {
                        "loss_set_size": 1,
                        "loss_vector": [1],
                    },
                },
            }
        ]
    )

    def fake_get_fix(*args, **_kwargs) -> str:
        args[4]["llm_tokens_used"] = 1
        return "verification-failed candidate"

    monkeypatch.setattr(self_correction_strategy.fix_strategy, "get_fix", fake_get_fix)
    strategy = SelfCorrectionStrategy(
        SimpleNamespace(),
        "model",
        client,  # type: ignore[arg-type]
        max_repairs=1,
        required_successes=1,
        guard=guard,
    )

    result = strategy.run(source)

    assert not result.converged
    assert source.read_text(encoding="utf-8") == "verification-failed candidate"


@pytest.mark.parametrize("use_environment_lock", [False, True])
def test_standalone_entrypoint_passes_charter_guard(
    monkeypatch, tmp_path: Path, use_environment_lock: bool
) -> None:
    source, _charter, guard = _guarded_project(tmp_path)
    arguments = [str(source)]
    if not use_environment_lock:
        arguments.extend(["--charter-lock", str(guard.lock_path)])
    args = self_correction_strategy.build_parser().parse_args(
        arguments
    )
    captured_guards: list[CharterGuard | None] = []

    class Result:
        def to_dict(self) -> dict[str, bool]:
            return {"converged": True}

    class FakeStrategy:
        def __init__(self, *_args, **kwargs) -> None:
            captured_guards.append(kwargs["guard"])

        def run(self, *_args, **_kwargs) -> Result:
            return Result()

    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "true")
    configured_lock = (
        guard.lock_path if use_environment_lock else tmp_path / "unused.lock"
    )
    monkeypatch.setenv("CHARTER_LOCK_PATH", str(configured_lock))
    monkeypatch.setattr(
        self_correction_strategy.AgentConfig,
        "create_client",
        lambda _self: SimpleNamespace(),
    )
    monkeypatch.setattr(
        self_correction_strategy,
        "create_mumei_client",
        lambda _bin: SimpleNamespace(),
    )
    monkeypatch.setattr(self_correction_strategy, "SelfCorrectionStrategy", FakeStrategy)

    result = self_correction_strategy.main(args)

    assert captured_guards == [guard]
    assert result.to_dict() == {"converged": True}


@pytest.mark.parametrize("source_is_charter", [False, True])
def test_standalone_entrypoint_exits_two_for_invalid_or_pinned_source(
    monkeypatch, tmp_path: Path, source_is_charter: bool
) -> None:
    source, charter, guard = _guarded_project(tmp_path)
    lock = guard.lock_path if source_is_charter else tmp_path / "missing.lock"
    target = charter if source_is_charter else source
    args = self_correction_strategy.build_parser().parse_args(
        [str(target), "--charter-lock", str(lock)]
    )
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "true")

    with pytest.raises(SystemExit) as exc_info:
        self_correction_strategy.main(args)

    assert exc_info.value.code == 2
