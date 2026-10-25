from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import self_correction
from agent.charter_guard import CharterGuard
from agent.self_correction import StructuredFeedbackSelfCorrectionLoop


@pytest.fixture(autouse=True)
def _disable_erosion_guard_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_EROSION_GUARD", "false")


def failed_result() -> dict:
    return {
        "success": False,
        "stderr": "verification failed",
        "report": {
            "failure_type": "postcondition_violated",
            "structured_feedback": {
                "status": "verification_failed",
                "error_type": "postcondition_violated",
                "feedback_instruction": "repair",
                "reconstruction_loss": {"loss_set_size": 1},
            },
        },
    }


def passed_result() -> dict:
    return {
        "success": True,
        "stderr": "",
        "report": {
            "structured_feedback": {
                "status": "verification_passed",
                "error_type": None,
                "feedback_instruction": "passed",
                "reconstruction_loss": None,
            }
        },
    }


def _guarded_source(tmp_path: Path) -> tuple[Path, Path, CharterGuard]:
    source = tmp_path / "app.mm"
    source.write_text("original source", encoding="utf-8")
    charter = tmp_path / "spec.charter.mm"
    charter.write_text("pinned charter", encoding="utf-8")
    lock = tmp_path / "charter.lock"
    lock.write_text(
        json.dumps(
            {
                "schema": "mumei.charter-lock/v1",
                "charters": [{"path": charter.name, "sha256": "ignored"}],
            }
        ),
        encoding="utf-8",
    )
    guard = CharterGuard.discover(str(source), str(lock))
    assert guard is not None
    return source, charter, guard


class FakeClient:
    def __init__(self, verifies: list[dict], checks: list[dict]) -> None:
        self.verifies = verifies
        self.checks = checks

    def verify(self, _source: str) -> dict:
        return self.verifies.pop(0)

    def charter_check(
        self, _source: str, _lock: str, cwd: Path | None = None
    ) -> dict:
        return self.checks.pop(0)


def _passed_check() -> dict:
    return {
        "exit_code": 0,
        "report": {"status": "pass", "atoms": []},
        "stdout": "",
        "stderr": "",
    }


def test_self_correction_converges_only_after_charter_pass(tmp_path: Path) -> None:
    source, _charter, guard = _guarded_source(tmp_path)
    client = FakeClient([passed_result()], [_passed_check()])
    loop = StructuredFeedbackSelfCorrectionLoop(
        SimpleNamespace(), "model", client, convergence_threshold=1, guard=guard
    )
    result = loop.run(source, {"status": "verification_passed"})
    assert result.converged
    assert result.stop_reason == "converged"


def test_charter_failure_is_sent_to_self_correction_repair(
    tmp_path: Path,
) -> None:
    source, _charter, guard = _guarded_source(tmp_path)
    failing_check = {
        "exit_code": 1,
        "report": {
            "status": "fail",
            "atoms": [{"name": "app", "status": "post_weakened", "detail": "ensures"}],
        },
        "stdout": "",
        "stderr": "",
    }
    client = FakeClient(
        [passed_result(), passed_result()],
        [failing_check, _passed_check()],
    )
    reports: list[dict] = []

    def repair_fn(*args: object) -> str:
        report = args[4]
        assert isinstance(report, dict)
        reports.append(report)
        return "repaired source"

    loop = StructuredFeedbackSelfCorrectionLoop(
        SimpleNamespace(),
        "model",
        client,
        convergence_threshold=1,
        repair_fn=repair_fn,  # type: ignore[arg-type]
        guard=guard,
    )
    result = loop.run(source, {"status": "verification_passed"})
    assert result.converged
    assert reports[0]["status"] == "charter_failed"
    assert reports[0]["failure_type"] == "charter_violation"
    assert reports[0]["reason"] == "app: post_weakened (ensures)"


def test_tampering_stops_self_correction_and_restores_source(tmp_path: Path) -> None:
    source, charter, guard = _guarded_source(tmp_path)
    original_source = source.read_bytes()
    client = FakeClient([failed_result()], [])

    def repair_fn(*_args: object) -> str:
        charter.write_text("modified charter", encoding="utf-8")
        return "candidate repair"

    loop = StructuredFeedbackSelfCorrectionLoop(
        SimpleNamespace(),
        "model",
        client,
        convergence_threshold=1,
        repair_fn=repair_fn,  # type: ignore[arg-type]
        guard=guard,
    )
    result = loop.run(source, failed_result()["report"]["structured_feedback"])
    assert not result.converged
    assert result.stop_reason == "charter_tampered"
    assert source.read_bytes() == original_source


def test_final_charter_failure_restores_original_source(tmp_path: Path) -> None:
    source, _charter, guard = _guarded_source(tmp_path)
    original_source = source.read_bytes()
    client = FakeClient(
        [passed_result(), passed_result()],
        [
            {
                "exit_code": 1,
                "report": {
                    "status": "fail",
                    "atoms": [{"name": "app", "status": "post_weakened"}],
                },
                "stdout": "",
                "stderr": "",
            },
            {
                "exit_code": 1,
                "report": {
                    "status": "fail",
                    "atoms": [{"name": "app", "status": "post_weakened"}],
                },
                "stdout": "",
                "stderr": "",
            },
        ],
    )
    loop = StructuredFeedbackSelfCorrectionLoop(
        SimpleNamespace(),
        "model",
        client,
        max_retries=1,
        convergence_threshold=1,
        repair_fn=lambda *_args: "charter-invalid candidate",  # type: ignore[arg-type]
        guard=guard,
    )

    result = loop.run(source, {"status": "verification_passed"})

    assert not result.converged
    assert source.read_bytes() == original_source


def test_final_verification_failure_keeps_candidate_source(tmp_path: Path) -> None:
    source, _charter, guard = _guarded_source(tmp_path)
    client = FakeClient([failed_result(), failed_result()], [])
    loop = StructuredFeedbackSelfCorrectionLoop(
        SimpleNamespace(),
        "model",
        client,
        max_retries=1,
        convergence_threshold=1,
        repair_fn=lambda *_args: "verification-failed candidate",  # type: ignore[arg-type]
        guard=guard,
    )

    result = loop.run(source, failed_result()["report"]["structured_feedback"])

    assert not result.converged
    assert source.read_text(encoding="utf-8") == "verification-failed candidate"


@pytest.mark.parametrize("feedback_mode", [False, True])
def test_self_correct_cli_passes_guard_to_both_modes(
    feedback_mode: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, _charter, guard = _guarded_source(tmp_path)
    captured_guards: list[CharterGuard | None] = []

    class Result:
        def to_dict(self) -> dict:
            return {"success": True}

    arguments = [str(source), "--charter-lock", str(guard.lock_path)]
    if feedback_mode:
        arguments.extend(["--feedback", '{"status":"verification_passed"}'])
    args = self_correction.build_self_correct_parser().parse_args(arguments)
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "true")
    monkeypatch.setenv("CHARTER_LOCK_PATH", str(tmp_path / "unused.lock"))
    monkeypatch.setattr(self_correction, "create_mumei_client", lambda _bin: object())

    if feedback_mode:
        def fake_run_loop(**kwargs: object) -> Result:
            captured_guards.append(kwargs.get("guard"))  # type: ignore[arg-type]
            return Result()

        monkeypatch.setattr(self_correction, "run_self_correction_loop", fake_run_loop)
    else:
        class FakeLoop:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def run(
                self,
                *_args: object,
                guard: CharterGuard | None = None,
                erosion_guard=None,
            ) -> Result:
                captured_guards.append(guard)
                return Result()

        monkeypatch.setattr(self_correction.fix_strategy, "SelfCorrectionLoop", FakeLoop)

    self_correction.main_self_correct(args)

    assert captured_guards == [guard]


def test_self_correct_cli_discovers_configured_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, _charter, guard = _guarded_source(tmp_path)
    captured_guards: list[CharterGuard | None] = []

    class Result:
        def to_dict(self) -> dict:
            return {"success": True}

    def fake_run_loop(**kwargs: object) -> Result:
        captured_guards.append(kwargs.get("guard"))  # type: ignore[arg-type]
        return Result()

    args = self_correction.build_self_correct_parser().parse_args(
        [str(source), "--feedback", '{"status":"verification_passed"}']
    )
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "true")
    monkeypatch.setenv("CHARTER_LOCK_PATH", str(guard.lock_path))
    monkeypatch.setattr(self_correction, "run_self_correction_loop", fake_run_loop)

    self_correction.main_self_correct(args)

    assert captured_guards == [guard]


def test_self_correct_cli_refuses_pinned_charter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _source, charter, guard = _guarded_source(tmp_path)
    args = self_correction.build_self_correct_parser().parse_args(
        [str(charter), "--charter-lock", str(guard.lock_path)]
    )

    with pytest.raises(SystemExit) as exc:
        self_correction.main_self_correct(args)

    assert exc.value.code == 2
    assert "refusing to heal a pinned charter file" in capsys.readouterr().out


def test_self_correct_cli_rejects_bad_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "app.mm"
    source.write_text("source", encoding="utf-8")
    lock = tmp_path / "bad.lock"
    lock.write_text("{", encoding="utf-8")
    args = self_correction.build_self_correct_parser().parse_args(
        [str(source), "--charter-lock", str(lock)]
    )

    with pytest.raises(SystemExit) as exc:
        self_correction.main_self_correct(args)

    assert exc.value.code == 2
    assert "could not parse charter lock" in capsys.readouterr().out
