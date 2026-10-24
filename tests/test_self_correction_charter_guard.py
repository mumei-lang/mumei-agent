from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent.charter_guard import CharterGuard
from agent.self_correction import StructuredFeedbackSelfCorrectionLoop


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
