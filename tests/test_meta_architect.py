from __future__ import annotations

import json
from types import SimpleNamespace

from agent.meta_architect import MetaArchitect
from agent.strategies.refactor_strategy import apply_refactoring_proposal


class FakeMumeiClient:
    def __init__(self, cross_spec: dict) -> None:
        self.cross_spec = cross_spec

    def verify(self, _source_path: str, report_dir: str | None = None, **_kwargs) -> dict:
        if report_dir is not None:
            with open(f"{report_dir}/cross_spec.json", "w", encoding="utf-8") as f:
                json.dump(self.cross_spec, f)
        return {"success": True, "stdout": "", "stderr": "", "report": {}}


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
