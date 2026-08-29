from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent.meta_architect import MetaArchitect
from agent.strategies.refactor_strategy import apply_refactoring_proposal

FIXTURES = Path(__file__).parent / "fixtures"


class FakeMumeiClient:
    def __init__(self, cross_spec: dict, *, success: bool = True) -> None:
        self.cross_spec = cross_spec
        self.success = success

    def verify(self, _source_path: str, report_dir: str | None = None, **_kwargs) -> dict:
        if report_dir is not None:
            with open(f"{report_dir}/cross_spec.json", "w", encoding="utf-8") as f:
                json.dump(self.cross_spec, f)
        return {"success": self.success, "stdout": "", "stderr": "", "report": {}}


def test_meta_architect_builds_conflict_proposal(tmp_path) -> None:
    source = tmp_path / "input.mm"
    source.write_text(
        """
atom caller(x: i64)
requires: x >= 0;
ensures: x >= 0;
body: callee(x);

atom callee(x: i64)
requires: x >= 10;
ensures: result >= 0;
body: x;
""",
        encoding="utf-8",
    )
    cross_spec = {
        "dependency_graph": [
            {"atom_name": "caller", "dependencies": ["callee"], "dependents": []},
            {"atom_name": "callee", "dependencies": [], "dependents": ["caller"]},
        ],
        "contract_consistency": [
            {
                "caller_atom": "caller",
                "callee_atom": "callee",
                "is_consistent": False,
                "violations": ["Caller contract provides x >= 0 but callee requires x >= 10"],
            }
        ],
    }
    architect = MetaArchitect(
        SimpleNamespace(),
        "model",
        FakeMumeiClient(cross_spec),
        SimpleNamespace(),
    )

    analysis = architect.analyze_architecture([source], {"attempts": []})

    assert analysis["dependency_graph"]["caller"]["dependencies"] == ["callee"]
    assert analysis["contract_conflicts"][0]["callee_atom"] == "callee"
    assert analysis["refactoring_proposals"][0]["refactoring_type"] == "relax_requires"
    assert analysis["refactoring_proposals"][0]["changes"]["atom"] == "callee"


def test_meta_architect_consumes_session_protocol_violations(tmp_path) -> None:
    source = tmp_path / "payment_client.mm"
    source.write_text("atom payment_client_request() body: 0;\n", encoding="utf-8")
    cross_spec = json.loads(
        (FIXTURES / "cross_spec_session_violation.json").read_text(encoding="utf-8")
    )
    architect = MetaArchitect(
        SimpleNamespace(),
        "model",
        FakeMumeiClient(cross_spec, success=False),
        SimpleNamespace(),
    )

    analysis = architect.analyze_architecture([source])

    violation = analysis["session_protocol_violations"][0]
    assert violation["effect"] == "PaymentChannel"
    assert violation["kind"] == "deadlock_no_progress"

    constraints = analysis["session_protocol_missing_constraints"]
    assert len(constraints) == 1
    assert constraints[0].startswith("[PaymentChannel/deadlock_no_progress]")
    assert "Suggested fix:" in constraints[0]

    proposal = next(
        item
        for item in analysis["refactoring_proposals"]
        if item["refactoring_type"] == "enforce_session_protocol"
    )
    assert proposal["target_atoms"] == [
        "payment_client_request",
        "payment_server_respond",
    ]
    assert proposal["changes"]["protocol_path"] == ["Idle", "ServerWait", "ClientWait"]
    assert proposal["missing_constraints"] == constraints


def test_meta_architect_reports_session_analysis_skips(tmp_path) -> None:
    source = tmp_path / "bulk_client.mm"
    source.write_text("atom bulk_client_send() body: 0;\n", encoding="utf-8")
    cross_spec = {
        "session_protocol_violations": [],
        "session_analysis_skips": [
            {
                "effect": "BulkChannel",
                "reason": "state_limit_exceeded",
                "state_count": 33,
                "limit": 32,
                "message": "session protocol not checked for 'BulkChannel'",
            }
        ],
    }
    architect = MetaArchitect(
        SimpleNamespace(),
        "model",
        FakeMumeiClient(cross_spec),
        SimpleNamespace(),
    )

    analysis = architect.analyze_architecture([source])

    assert analysis["session_protocol_violations"] == []
    assert analysis["session_protocol_missing_constraints"] == []
    assert analysis["session_analysis_skips"][0]["effect"] == "BulkChannel"


def test_meta_architect_flags_artifact_mapping_divergence(tmp_path) -> None:
    source = tmp_path / "payment_client.mm"
    source.write_text("atom payment_client_request() body: 0;\n", encoding="utf-8")
    cross_spec = json.loads(
        (FIXTURES / "cross_spec_session_violation.json").read_text(encoding="utf-8")
    )
    for entry in cross_spec["agent_artifact_mapping"]:
        if entry["cross_spec_field"] == "session_protocol_violations[]":
            entry["agent_field"] = "divergences[]"
    architect = MetaArchitect(
        SimpleNamespace(),
        "model",
        FakeMumeiClient(cross_spec, success=False),
        SimpleNamespace(),
    )

    analysis = architect.analyze_architecture([source])

    assert analysis["artifact_mapping_divergences"] == [
        "session_protocol_violations[] declares agent_field='divergences[]' "
        "but the agent maps it to 'missing_constraints[]'"
    ]
    assert len(analysis["session_protocol_missing_constraints"]) == 1


def test_meta_architect_accepts_declared_artifact_mapping(tmp_path) -> None:
    source = tmp_path / "payment_client.mm"
    source.write_text("atom payment_client_request() body: 0;\n", encoding="utf-8")
    cross_spec = json.loads(
        (FIXTURES / "cross_spec_session_violation.json").read_text(encoding="utf-8")
    )
    architect = MetaArchitect(
        SimpleNamespace(),
        "model",
        FakeMumeiClient(cross_spec, success=False),
        SimpleNamespace(),
    )

    assert architect.analyze_architecture([source])["artifact_mapping_divergences"] == []


def test_apply_refactoring_proposal_targets_requested_atom() -> None:
    source = """atom a(x: i64)
requires: x >= 0;
ensures: result >= 0;
body: x;

atom b(x: i64)
requires: x >= 10;
ensures: result >= 0;
body: x;
"""
    proposal = {
        "refactoring_type": "relax_requires",
        "changes": {"atom": "b", "requires": "x >= 0"},
    }

    updated = apply_refactoring_proposal(proposal, source)

    assert "atom a(x: i64)\nrequires: x >= 0;" in updated
    assert "atom b(x: i64)\nrequires: x >= 0;" in updated


def test_meta_architect_refactor_keeps_session_proposals_for_review(tmp_path) -> None:
    from agent.self_healing import _try_meta_architect_refactor
    from agent.strategies.retry_history import RetryHistory
    from agent.thought_log import ThoughtProcess

    source_file = tmp_path / "payment_client.mm"
    source = "atom payment_client_request() body: 0;\n"
    source_file.write_text(source, encoding="utf-8")
    cross_spec = json.loads(
        (FIXTURES / "cross_spec_session_violation.json").read_text(encoding="utf-8")
    )
    thought = ThoughtProcess(target_file=str(source_file))

    assert _try_meta_architect_refactor(
        client=SimpleNamespace(),
        model="model",
        mumei=FakeMumeiClient(cross_spec, success=False),
        config=SimpleNamespace(),
        source_files=[source_file],
        source=source,
        retry_history=RetryHistory(),
        thought=thought,
    ) is None

    step = next(
        item for item in thought.steps if item.action == "meta_architect_review_only"
    )
    assert step.fix_strategy == "enforce_session_protocol"
    assert "PaymentChannel/deadlock_no_progress" in (step.fix_description or "")
    assert "suggested fix:" in (step.fix_description or "")


def test_meta_architect_refactor_failure_falls_back() -> None:
    from agent.self_healing import _try_meta_architect_refactor

    class FailingClient:
        def verify(self, *_args, **_kwargs) -> dict:
            raise RuntimeError("cross-spec unavailable")

    thought = SimpleNamespace(steps=[], add_step=lambda **_kwargs: None)

    assert _try_meta_architect_refactor(
        client=SimpleNamespace(),
        model="model",
        mumei=FailingClient(),
        config=SimpleNamespace(),
        source_files=[],
        source="atom a() body: 0;",
        retry_history=SimpleNamespace(attempts=[]),
        thought=thought,
    ) is None
