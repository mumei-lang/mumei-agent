from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.config import AgentConfig
from agent.self_correction import StructuredFeedbackSelfCorrectionLoop
from agent.strategies.fix_strategy import SelfCorrectionLoop


class FakeMumeiClient:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results
        self.index = 0

    def verify(self, _source_path: str) -> dict[str, object]:
        result = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return result


class FakeLossVectorLLM:
    def __init__(self, fixes: list[str]) -> None:
        self.fixes = fixes
        self.calls: list[dict[str, object]] = []

    def fix_with_loss_vector(self, code_file: Path, loss_vector: dict) -> str:
        self.calls.append({"code_file": code_file, "loss_vector": loss_vector})
        return self.fixes[min(len(self.calls) - 1, len(self.fixes) - 1)]


def loss_vector_result(case_id: int = 0) -> dict[str, object]:
    return {
        "all_verified": False,
        "loss_vector": {
            "status": "verification_failed",
            "error_type": "postcondition_violated",
            "location": {"file": "sample.mm", "line": 1},
            "reconstruction_loss": {
                "violated_property": "result > 0",
                "counter_example": {"case": case_id},
            },
            "feedback_instruction": "Repair using the counterexample.",
        },
    }


def all_verified_result() -> dict[str, object]:
    return {"all_verified": True}


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


def test_loss_vector_self_correction_loop_stops_when_all_verified(tmp_path: Path) -> None:
    source = tmp_path / "sample.mm"
    source.write_text("broken", encoding="utf-8")
    llm = FakeLossVectorLLM(["fixed"])
    loop = SelfCorrectionLoop(max_iterations=10)

    result = loop.run(
        source,
        FakeMumeiClient([loss_vector_result(), all_verified_result()]),
        llm,
    )

    assert result.success
    assert result.iterations == 2
    assert result.stop_reason == "all_verified"
    assert len(llm.calls) == 1
    assert source.read_text(encoding="utf-8") == "fixed"


def test_loss_vector_self_correction_loop_stops_at_max_iterations(tmp_path: Path) -> None:
    source = tmp_path / "sample.mm"
    source.write_text("broken", encoding="utf-8")
    llm = FakeLossVectorLLM(["still broken"])
    loop = SelfCorrectionLoop(max_iterations=3)

    result = loop.run(
        source,
        FakeMumeiClient([loss_vector_result(1), loss_vector_result(2), loss_vector_result(3)]),
        llm,
    )

    assert not result.success
    assert result.iterations == 3
    assert result.stop_reason == "max_iterations"
    assert len(llm.calls) == 3


def test_loss_vector_self_correction_loop_gracefully_stops_without_loss_vector(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.mm"
    source.write_text("broken", encoding="utf-8")
    llm = FakeLossVectorLLM(["unused"])
    loop = SelfCorrectionLoop(max_iterations=10)

    result = loop.run(source, FakeMumeiClient([{"all_verified": False}]), llm)

    assert not result.success
    assert result.iterations == 1
    assert result.stop_reason == "loss_vector_missing"
    assert len(llm.calls) == 0


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


def test_repair_certificate_metadata_shape() -> None:
    from agent.self_correction import repair_certificate_metadata

    ok = repair_certificate_metadata(converged=True, repair_attempts=2, token_cost=17, consecutive_successes=1)
    assert ok == {
        "repair_attempts": 2,
        "converged": True,
        "consecutive_successes": 1,
        "token_cost": 17,
    }
    failed = repair_certificate_metadata(
        converged=False, repair_attempts=3, token_cost=0, final_error="max_retries_exhausted"
    )
    assert failed["converged"] is False
    assert failed["final_error"] == "max_retries_exhausted"


def _fake_mumei(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake_mumei.py"
    script.write_text(
        "import json, os, sys\n"
        "out = sys.argv[sys.argv.index('--output') + 1]\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {script}"


def test_write_repair_certificate_passes_metadata_env(tmp_path: Path) -> None:
    from agent.self_correction import (
        SELF_CORRECTION_METADATA_ENV,
        write_repair_certificate,
    )

    source = tmp_path / "prog.mm"
    source.write_text("fn f() {}\n", encoding="utf-8")
    mumei_bin = _fake_mumei(
        tmp_path,
        "meta = json.loads(os.environ['MUMEI_SELF_CORRECTION_METADATA'])\n"
        "json.dump({'atoms': [{'name': 'f', 'self_correction': meta}],"
        " 'self_correction_summary': {'total_atoms': 1,"
        " 'converged_atoms': int(meta['converged']),"
        " 'average_repair_attempts': meta['repair_attempts']}},"
        " open(out, 'w'))\n"
        "sys.exit(0 if meta['converged'] else 1)",
    )
    assert SELF_CORRECTION_METADATA_ENV == "MUMEI_SELF_CORRECTION_METADATA"
    cert = write_repair_certificate(
        source,
        {"repair_attempts": 3, "converged": False, "consecutive_successes": 0, "token_cost": 9},
        mumei_bin=mumei_bin,
        out_path=tmp_path / "certs" / "prog.proof.json",
    )
    assert cert["self_correction_summary"]["converged_atoms"] == 0
    assert cert["self_correction_summary"]["average_repair_attempts"] == 3
    assert cert["atoms"][0]["self_correction"]["token_cost"] == 9


def test_write_repair_certificate_rejects_certificate_without_summary(tmp_path: Path) -> None:
    from agent.self_correction import write_repair_certificate

    source = tmp_path / "prog.mm"
    source.write_text("fn f() {}\n", encoding="utf-8")
    mumei_bin = _fake_mumei(tmp_path, "json.dump({'atoms': []}, open(out, 'w'))")
    with pytest.raises(RuntimeError, match="self_correction_summary"):
        write_repair_certificate(
            source, {"repair_attempts": 0, "converged": True, "consecutive_successes": 1, "token_cost": 0},
            mumei_bin=mumei_bin, out_path=tmp_path / "prog.proof.json",
        )


def test_write_repair_certificate_requires_output_file(tmp_path: Path) -> None:
    from agent.self_correction import write_repair_certificate

    source = tmp_path / "prog.mm"
    source.write_text("fn f() {}\n", encoding="utf-8")
    mumei_bin = _fake_mumei(tmp_path, "sys.exit(1)")
    with pytest.raises(RuntimeError, match="did not write"):
        write_repair_certificate(
            source, {"repair_attempts": 1, "converged": False, "consecutive_successes": 0, "token_cost": 1},
            mumei_bin=mumei_bin, out_path=tmp_path / "prog.proof.json",
        )
