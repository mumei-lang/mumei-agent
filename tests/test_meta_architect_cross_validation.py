from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent.cross_validation import (
    CrossValidationIssue,
    MumeiContractAtom,
    SpecDriftResult,
)
from agent.meta_architect import MetaArchitect


class FakeMumeiClient:
    def verify(self, _source_path: str, report_dir: str | None = None, **_kwargs) -> dict:
        if report_dir is not None:
            with open(f"{report_dir}/cross_spec.json", "w", encoding="utf-8") as f:
                json.dump({"dependency_graph": [], "contract_conflicts": []}, f)
        return {"success": True, "stdout": "", "stderr": "", "report": {}}


def test_meta_architect_surfaces_cross_validation_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    code_file = tmp_path / "vault.py"
    spec_file = tmp_path / "vault.mm"
    code_file.write_text("def vault(x):\n    return 0\n", encoding="utf-8")
    spec_file.write_text(
        "atom vault(x: i64)\nrequires: x >= 0;\nensures: result > 0;\nbody: x;\n",
        encoding="utf-8",
    )
    drift_issue = CrossValidationIssue(
        kind="drift",
        message="implementation no longer guarantees result > 0",
        evidence="return 0",
        location=str(code_file),
    )

    def fake_validate_code_to_spec(*_args: object, **_kwargs: object) -> SpecDriftResult:
        return SpecDriftResult(
            success=False,
            code_path=str(code_file),
            spec_path=str(spec_file),
            language="python",
            spec_atoms=[MumeiContractAtom(name="vault")],
            code_atoms=[],
            drift_issues=[drift_issue],
            changed_hunks=[],
            report="drift detected",
        )

    monkeypatch.setattr(
        "agent.cross_validation.validate_code_to_spec",
        fake_validate_code_to_spec,
    )
    architect = MetaArchitect(
        SimpleNamespace(),
        "model",
        FakeMumeiClient(),  # type: ignore[arg-type]
        SimpleNamespace(api_key=""),  # type: ignore[arg-type]
    )

    analysis = architect.analyze_architecture([code_file], {"attempts": []})

    assert analysis["contract_conflicts"][0]["caller_atom"] == "vault"
    assert analysis["cross_validation_drift"][0]["code_path"] == str(code_file)
    assert analysis["cross_validation_drift"][0]["drift_issues"][0]["kind"] == "drift"
    proposal = analysis["refactoring_proposals"][0]
    assert proposal["refactoring_type"] == "resolve_spec_drift"
    assert proposal["cross_validation_drift"][0]["message"] == drift_issue.message
