from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agent import mcp_server
from agent.human_review import HumanReviewTracker, ReviewStatus


def _write_queue(repo: Path) -> Path:
    queue = {
        "version": "1.0",
        "file": "specs/review.mm",
        "atoms": [
            {
                "name": "trusted_transfer",
                "reason": "trusted_atom",
                "priority": "medium",
                "spec_text": "requires: true\nensures: result >= 0",
                "suggested_action": "Confirm trusted boundary.",
            },
            {
                "name": "hard_nonlinear",
                "reason": "z3_unknown",
                "priority": "high",
                "spec_text": "requires: n > 0\nensures: result == n * n",
                "suggested_action": "Escalate to Lean.",
            },
        ],
    }
    path = repo / "human_review_queue.json"
    path.write_text(json.dumps(queue), encoding="utf-8")
    return path


def _payload(raw: str) -> dict:
    assert isinstance(raw, str)
    return json.loads(raw)


def test_human_review_tracker_approves_and_persists_review(tmp_path: Path) -> None:
    repo = tmp_path / "mumei"
    repo.mkdir()
    _write_queue(repo)
    tracker = HumanReviewTracker.from_repo(repo)

    entry = tracker.approve_review("trusted_transfer", "akira", "FFI contract reviewed")

    assert entry["status"] == ReviewStatus.APPROVED.value
    saved = json.loads((repo / "human_review_queue.json").read_text(encoding="utf-8"))
    assert saved["atoms"][0]["reviewer"] == "akira"
    assert saved["review_history"][0]["atom_name"] == "trusted_transfer"


def test_human_review_tracker_rejects_and_persists_review(tmp_path: Path) -> None:
    repo = tmp_path / "mumei"
    repo.mkdir()
    _write_queue(repo)
    tracker = HumanReviewTracker.from_repo(repo)

    entry = tracker.reject_review(
        "trusted_transfer",
        "akira",
        "contract rejected: boundary condition unclear",
    )

    assert entry["status"] == ReviewStatus.REJECTED.value
    saved = json.loads((repo / "human_review_queue.json").read_text(encoding="utf-8"))
    assert saved["atoms"][0]["reviewer"] == "akira"
    assert saved["atoms"][0]["notes"] == "contract rejected: boundary condition unclear"
    assert saved["review_history"][0]["atom_name"] == "trusted_transfer"
    assert saved["review_history"][0]["status"] == ReviewStatus.REJECTED.value


def test_human_review_tracker_approve_fails_on_rejected_or_escalated(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "mumei"
    repo.mkdir()
    _write_queue(repo)
    tracker = HumanReviewTracker.from_repo(repo)

    tracker.reject_review("trusted_transfer", "akira", "rejected")
    with pytest.raises(ValueError, match="cannot approve atom 'trusted_transfer'"):
        tracker.approve_review("trusted_transfer", "akira", "should fail")

    saved = json.loads((repo / "human_review_queue.json").read_text(encoding="utf-8"))
    assert saved["atoms"][0]["status"] == ReviewStatus.REJECTED.value


def test_human_review_tracker_escalates_to_lean(tmp_path: Path) -> None:
    repo = tmp_path / "mumei"
    (repo / "specs").mkdir(parents=True)
    _write_queue(repo)
    tracker = HumanReviewTracker.from_repo(repo)
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="Lean escalation bundle written\n",
        stderr="",
    )

    with patch("agent.human_review.subprocess.run", return_value=completed) as run:
        entry = tracker.escalate_to_lean("hard_nonlinear")

    assert entry["status"] == ReviewStatus.ESCALATED_TO_LEAN.value
    run.assert_called_once()
    command = run.call_args.args[0]
    assert "--escalate-lean" in command
    assert "--emit" in command
    assert str(repo / "specs" / "review.mm") in command


def test_mcp_review_tools_load_and_approve_active_queue(tmp_path: Path) -> None:
    repo = tmp_path / "mumei"
    repo.mkdir()
    _write_queue(repo)
    mcp_server._active_human_review_tracker = None

    queue_result = _payload(mcp_server.get_review_queue(str(repo)))
    approve_result = _payload(
        mcp_server.approve_review("trusted_transfer", "akira", "approved")
    )

    reject_result = _payload(
        mcp_server.reject_review("trusted_transfer", "akira", "rejected")
    )

    assert queue_result["status"] == "ok"
    assert queue_result["count"] == 2
    assert approve_result["status"] == "ok"
    assert approve_result["atom"]["status"] == ReviewStatus.APPROVED.value
    assert reject_result["status"] == "ok"
    assert reject_result["atom"]["status"] == ReviewStatus.REJECTED.value


def test_mcp_approve_review_refuses_rejected_atom(tmp_path: Path) -> None:
    repo = tmp_path / "mumei"
    repo.mkdir()
    _write_queue(repo)
    mcp_server._active_human_review_tracker = None

    mcp_server.get_review_queue(str(repo))
    mcp_server.reject_review("trusted_transfer", "akira", "rejected")
    result = _payload(
        mcp_server.approve_review("trusted_transfer", "akira", "should fail")
    )

    assert result["status"] == "error"
    assert "cannot approve atom" in result["error"]
    saved = json.loads((repo / "human_review_queue.json").read_text(encoding="utf-8"))
    assert saved["atoms"][0]["status"] == ReviewStatus.REJECTED.value
