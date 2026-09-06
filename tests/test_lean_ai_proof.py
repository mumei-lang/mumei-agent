"""Task 2-D — AI Lean proof generation with a mocked LLM and mocked Lake."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import lean_ai_proof, lean_bridge
from agent.config import AgentConfig
from agent.lean_ai_proof import (
    AI_PROOF_STRATEGY,
    extract_lean_source,
    reject_unsound_lean_source,
    run_ai_proof_repair,
)


class ScriptedGenerator:
    """Deterministic ``AiProofGenerator``: returns canned Lean per call."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []

    def generate_lean_proof(self, request: dict) -> str:
        self.requests.append(request)
        if not self.replies:
            raise RuntimeError("no scripted reply left")
        return self.replies.pop(0)


def _good_module(theorem: str = "square_nonneg_correct") -> str:
    return (
        "```lean\nimport MumeiLean\n\nnamespace Generated.AiProof.Square_nonneg\n\n"
        f"theorem {theorem} (x : Int) : 0 ≤ x * x := by positivity\n\n"
        "end Generated.AiProof.Square_nonneg\n```"
    )


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "mumei-lean"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "bridge.py").write_text("# stub\n")
    (repo / "scripts" / "export_cert.py").write_text(
        'TRANSLATOR_VERSION = "mumei-lean-translator-ir-v1"\n'
        'BRIDGE_LEMMA_HASH = "hash-for-test"\n',
        encoding="utf-8",
    )
    (repo / "lakefile.lean").write_text("-- stub\n")
    return repo


def _cert() -> dict:
    return {
        "all_verified": False,
        "atoms": [
            {"name": "ok", "z3_check_result": "unsat"},
            {
                "name": "square_nonneg",
                "z3_check_result": "unknown",
                "z3_result_class": "unknown",
                "escalation_reason": "z3_unknown_complex_fragment",
                "requires": "true",
                "ensures": "result >= 0",
                "body_expr": "x * x",
            },
        ],
    }


def _lake_ok() -> tuple[int, str]:
    return 0, "Build completed successfully.\n"


def _lake_unsolved() -> tuple[int, str]:
    return 1, "\nerror: unsolved goals\nx : Int\n⊢ 0 ≤ x * x"


def _patch_lake(**kwargs):
    """Patch the AI stage's Lake runner (``(returncode, log)``)."""
    return patch("agent.lean_ai_proof._lake_build_module", **kwargs)


@pytest.fixture(autouse=True)
def _lake_on_path() -> None:
    # ``shutil`` is one shared module object for lean_bridge / lean_ai_proof.
    with patch("agent.lean_ai_proof.shutil.which", return_value="/usr/bin/lake"):
        yield


# ---------------------------------------------------------------------------
# source hygiene
# ---------------------------------------------------------------------------


def test_extract_lean_source_strips_fences() -> None:
    assert extract_lean_source("```lean\ntheorem t : True := trivial\n```") == (
        "theorem t : True := trivial"
    )
    assert extract_lean_source("theorem t : True := trivial") == (
        "theorem t : True := trivial"
    )


@pytest.mark.parametrize(
    "source, expected",
    [
        ("theorem t_correct : True := by sorry", "forbidden_token:sorry"),
        ("theorem t_correct : True := by admit", "forbidden_token:admit"),
        ("axiom bad : False\ntheorem t_correct : True := trivial", "forbidden_token:axiom"),
        ("theorem t_correct : 1 = 1 := by native_decide", "forbidden_token:native_decide"),
        ("theorem other : True := trivial", "missing_theorem:t_correct"),
        ("", "empty_source"),
        ("theorem t_correct : True := trivial", None),
    ],
)
def test_reject_unsound_lean_source(source: str, expected: str | None) -> None:
    assert reject_unsound_lean_source(source, "t_correct") == expected


# ---------------------------------------------------------------------------
# run_ai_proof_repair
# ---------------------------------------------------------------------------


def test_ai_proof_promotes_only_after_lake_success(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    gen = ScriptedGenerator([_good_module()])
    evidence = tmp_path / "evidence"

    with _patch_lake(return_value=_lake_ok()) as run:
        result = run_ai_proof_repair(
            cert=_cert(),
            mumei_lean_repo=repo,
            generator=gen,
            evidence_dir=evidence,
        )

    assert result is not None
    assert result["success"] is True
    assert result["ai_proof_used"] is True
    assert result["ai_proof_proved"] == 1
    assert result["fallback_strategy"] == AI_PROOF_STRATEGY
    assert run.call_args.args[:2] == (repo, "Generated.AiProof.Square_nonneg")

    atom = next(a for a in result["lean_cert"]["atoms"] if a["name"] == "square_nonneg")
    assert atom["z3_check_result"] == "lean_verified"
    assert atom["lean_fallback_strategy"] == AI_PROOF_STRATEGY
    meta = atom["lean_metadata"]
    assert meta["ai_proof_used"] is True
    assert meta["known_witness_used"] is False
    assert meta["ai_proof_attempts"] == 1
    assert meta["lean_module"] == "Generated.AiProof.Square_nonneg"
    assert meta["theorem_name"] == "square_nonneg_correct"
    assert atom["translator_version"] == "mumei-lean-translator-ir-v1"
    assert atom["bridge_lemma_hash"] == "hash-for-test"
    assert atom["lean_result_metadata"]["ai_proof_used"] is True
    # evidence: source and build log persisted, module removed from checkout
    assert Path(meta["proof_path"]).read_text(encoding="utf-8").startswith("import MumeiLean")
    assert "Build completed" in Path(meta["build_log_path"]).read_text(encoding="utf-8")
    assert not (repo / "generated" / "Generated" / "AiProof" / "Square_nonneg.lean").exists()
    # unaffected atoms untouched
    assert next(a for a in result["lean_cert"]["atoms"] if a["name"] == "ok") == {
        "name": "ok",
        "z3_check_result": "unsat",
    }


def test_ai_proof_repairs_with_lean_feedback(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    gen = ScriptedGenerator([_good_module(), _good_module()])

    with _patch_lake(
        side_effect=[_lake_unsolved(), _lake_ok()],
    ):
        result = run_ai_proof_repair(
            cert=_cert(),
            mumei_lean_repo=repo,
            generator=gen,
            max_attempts=3,
            evidence_dir=tmp_path / "evidence",
        )

    assert result is not None and result["success"] is True
    assert len(gen.requests) == 2
    assert gen.requests[0]["feedback"] == []
    feedback = gen.requests[1]["feedback"]
    assert feedback[0]["error_code"] == "tactic_failed"
    assert "unsolved goals" in feedback[0]["log_tail"]
    outcome = result["ai_proof_outcomes"][0]
    assert outcome["attempts"] == 2
    assert [a["accepted"] for a in outcome["attempt_log"]] == [False, True]
    atom = result["lean_cert"]["atoms"][1]
    assert atom["lean_metadata"]["ai_proof_attempts"] == 2


def test_ai_proof_keeps_unknown_when_all_attempts_fail(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    gen = ScriptedGenerator([_good_module()] * 2)

    with _patch_lake(return_value=_lake_unsolved()):
        result = run_ai_proof_repair(
            cert=_cert(),
            mumei_lean_repo=repo,
            generator=gen,
            max_attempts=2,
            evidence_dir=tmp_path / "evidence",
        )

    assert result is not None
    assert result["success"] is False
    assert result["ai_proof_used"] is False
    assert result["error_code"] == "tactic_failed"
    assert result["ai_proof_residual"] == ["square_nonneg"]
    assert result["lean_cert"]["atoms"][1]["z3_check_result"] == "unknown"
    assert "lean_metadata" not in result["lean_cert"]["atoms"][1]
    assert len(gen.requests) == 2


def test_ai_proof_rejects_sorry_before_lake(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    gen = ScriptedGenerator(
        ["theorem square_nonneg_correct : True := by sorry", _good_module()]
    )

    with _patch_lake(return_value=_lake_ok()) as run:
        result = run_ai_proof_repair(
            cert=_cert(),
            mumei_lean_repo=repo,
            generator=gen,
            evidence_dir=tmp_path / "evidence",
        )

    assert result is not None and result["success"] is True
    assert run.call_count == 1  # the sorry attempt never reached lake
    assert gen.requests[1]["feedback"][0]["rejection_reason"] == "forbidden_token:sorry"
    log = result["ai_proof_outcomes"][0]["attempt_log"]
    assert log[0]["error_code"] == "unsound_source"


def test_ai_proof_does_not_trust_exit_zero_with_sorry_warning(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    gen = ScriptedGenerator([_good_module()])
    lake = (0, "warning: declaration uses 'sorry'\n")
    with _patch_lake(return_value=lake):
        result = run_ai_proof_repair(
            cert=_cert(),
            mumei_lean_repo=repo,
            generator=gen,
            max_attempts=1,
            evidence_dir=tmp_path / "evidence",
        )
    assert result is not None
    assert result["success"] is False
    assert result["lean_cert"]["atoms"][1]["z3_check_result"] == "unknown"


def test_ai_proof_generator_error_degrades_gracefully(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    gen = ScriptedGenerator([])  # raises on first call
    with _patch_lake() as run:
        result = run_ai_proof_repair(
            cert=_cert(), mumei_lean_repo=repo, generator=gen, evidence_dir=tmp_path / "e"
        )
    assert result is not None
    assert result["success"] is False
    assert result["error_code"] == "generator_error"
    run.assert_not_called()


def test_ai_proof_noop_without_unknowns(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    gen = ScriptedGenerator([])
    result = run_ai_proof_repair(
        cert={"atoms": [{"name": "ok", "z3_check_result": "unsat"}]},
        mumei_lean_repo=repo,
        generator=gen,
    )
    assert result is None
    assert gen.requests == []


def test_ai_proof_uses_escalation_bundle_hints(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    gen = ScriptedGenerator([_good_module()])
    bundle = {
        "source_file": "x.mm",
        "loop_line": 3,
        "loop_context": {},
        "reason": "cegis_max_iterations_reached",
        "atom": {"name": "square_nonneg", "requires": "true"},
        "counterexamples": [{"x": -1}],
        "tried_invariants": [{"expression": "x >= 0", "iteration": 1}],
    }
    with _patch_lake(return_value=_lake_ok()):
        run_ai_proof_repair(
            cert=_cert(),
            mumei_lean_repo=repo,
            generator=gen,
            escalation_bundle=bundle,
            evidence_dir=tmp_path / "e",
        )
    hints = gen.requests[0]["escalation_bundle"]
    assert hints["counterexamples"] == [{"x": -1}]
    assert hints["tried_invariants"][0]["expression"] == "x >= 0"
    assert hints["atom"]["name"] == "square_nonneg"
    prompt = lean_ai_proof.render_ai_proof_prompt(gen.requests[0])
    assert "square_nonneg_correct" in prompt
    assert "x >= 0" in prompt


# ---------------------------------------------------------------------------
# run_lean_bridge integration (Task 2-C stages first, then AI)
# ---------------------------------------------------------------------------


def test_run_lean_bridge_ai_stage_after_known_witness(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    (repo / "MumeiLean").mkdir()
    (repo / "MumeiLean" / "StdMathAbs.lean").write_text(
        "theorem abs_saturating_correct : True := by trivial\n", encoding="utf-8"
    )
    cert = _cert()
    cert["atoms"].append(
        {"name": "abs_saturating", "z3_check_result": "unknown"}
    )
    cert_path = tmp_path / "in.json"
    cert_path.write_text(json.dumps(cert), encoding="utf-8")
    gen = ScriptedGenerator([_good_module()])

    with patch("agent.lean_bridge.subprocess.run") as bridge_run, patch(
        "agent.lean_bridge.shutil.which", return_value="/usr/bin/lake"
    ), _patch_lake(return_value=_lake_ok()):
        bridge_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="error: unsolved goals"),
            MagicMock(returncode=0, stdout="built", stderr=""),
        ]
        result = lean_bridge.run_lean_bridge(
            cert_path=cert_path,
            lean_cert_out=tmp_path / "out.json",
            mumei_lean_repo=repo,
            ai_proof_generator=gen,
            ai_proof_evidence_dir=tmp_path / "evidence",
        )

    assert result["success"] is True
    assert result["primary_error_code"] == "tactic_failed"
    assert result["fallback_strategy"] == AI_PROOF_STRATEGY
    assert result["ai_proof_used"] is True
    assert [s["name"] for s in result["strategy_attempts"]] == [
        "generated_bridge",
        "known_witness_module",
        AI_PROOF_STRATEGY,
    ]
    # AI stage only saw the residual atom, not the known witness one
    assert gen.requests[0]["atom"]["name"] == "square_nonneg"
    assert len(gen.requests) == 1
    atoms = {a["name"]: a for a in result["lean_cert"]["atoms"]}
    assert atoms["abs_saturating"]["lean_metadata"]["known_witness_used"] is True
    assert atoms["abs_saturating"]["lean_metadata"].get("ai_proof_used") is None
    assert atoms["square_nonneg"]["lean_metadata"]["ai_proof_used"] is True
    assert atoms["square_nonneg"]["lean_metadata"]["known_witness_used"] is False

    merged = lean_bridge.merge_lean_cert_into_proof_cert(cert, result["lean_cert"])
    assert lean_bridge.count_lean_verified_unknowns(cert, merged) == 2
    assert cert["atoms"][1]["z3_check_result"] == "unknown"  # non-mutating


def test_run_lean_bridge_ai_partial_success_reported(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    cert = _cert()
    cert["atoms"].append(
        {"name": "hard_one", "z3_check_result": "unknown", "ensures": "false"}
    )
    cert_path = tmp_path / "in.json"
    cert_path.write_text(json.dumps(cert), encoding="utf-8")
    gen = ScriptedGenerator(
        [_good_module(), "theorem hard_one_correct : False := by sorry"]
    )

    with patch("agent.lean_bridge.subprocess.run") as bridge_run, patch(
        "agent.lean_bridge.shutil.which", return_value="/usr/bin/lake"
    ), _patch_lake(return_value=_lake_ok()):
        bridge_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: unsolved goals"
        )
        result = lean_bridge.run_lean_bridge(
            cert_path=cert_path,
            lean_cert_out=tmp_path / "out.json",
            mumei_lean_repo=repo,
            ai_proof_generator=gen,
            ai_proof_max_attempts=1,
            ai_proof_evidence_dir=tmp_path / "evidence",
        )

    assert result["success"] is False
    assert result["partial_success"] is True
    assert result["ai_proof_used"] is True
    assert result["ai_proof_residual"] == ["hard_one"]
    atoms = {a["name"]: a for a in result["lean_cert"]["atoms"]}
    assert atoms["square_nonneg"]["z3_check_result"] == "lean_verified"
    assert atoms["hard_one"]["z3_check_result"] == "unknown"


def test_run_lean_bridge_without_generator_is_unchanged(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)
    cert_path = tmp_path / "in.json"
    cert_path.write_text(json.dumps(_cert()), encoding="utf-8")

    with patch("agent.lean_bridge.subprocess.run") as bridge_run, patch(
        "agent.lean_bridge.shutil.which", return_value="/usr/bin/lake"
    ), patch("agent.lean_ai_proof.run_ai_proof_repair") as ai:
        bridge_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: unsolved goals"
        )
        result = lean_bridge.run_lean_bridge(
            cert_path=cert_path,
            lean_cert_out=tmp_path / "out.json",
            mumei_lean_repo=repo,
        )

    ai.assert_not_called()
    assert result["success"] is False
    assert result["error_code"] == "tactic_failed"
    assert "ai_proof_used" not in result


# ---------------------------------------------------------------------------
# config gating: no-LLM / CI_FIXTURE_MODE skip
# ---------------------------------------------------------------------------


def test_lean_ai_proof_active_requires_flag_key_and_no_fixture_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI_FIXTURE_MODE", raising=False)
    cfg = AgentConfig(api_key="k", enable_lean_ai_proof=True, ci_fixture_mode=False)
    assert cfg.lean_ai_proof_active() is True
    assert AgentConfig(api_key="", enable_lean_ai_proof=True).lean_ai_proof_active() is False
    assert AgentConfig(api_key="k", enable_lean_ai_proof=False).lean_ai_proof_active() is False
    assert (
        AgentConfig(api_key="k", enable_lean_ai_proof=True, ci_fixture_mode=True)
        .lean_ai_proof_active()
        is False
    )


def test_proliferate_generator_factory_respects_gating() -> None:
    from agent.proliferate import _lean_ai_proof_generator

    assert _lean_ai_proof_generator(AgentConfig(api_key="", enable_lean_ai_proof=True)) is None
    assert (
        _lean_ai_proof_generator(
            AgentConfig(api_key="k", enable_lean_ai_proof=True, ci_fixture_mode=True)
        )
        is None
    )
    gen = _lean_ai_proof_generator(
        AgentConfig(api_key="k", enable_lean_ai_proof=True, ci_fixture_mode=False)
    )
    assert isinstance(gen, lean_ai_proof.LLMAiProofGenerator)


def test_run_lean_fallback_inner_records_ai_provenance(tmp_path: Path) -> None:
    from agent.proliferate import _run_lean_fallback_inner

    repo = _fake_repo(tmp_path)
    results = [{"publish_result": {"proof_certificate": _cert()}}]
    gen = ScriptedGenerator([_good_module()])

    with patch("agent.lean_bridge.subprocess.run") as bridge_run, patch(
        "agent.lean_bridge.shutil.which", return_value="/usr/bin/lake"
    ), _patch_lake(return_value=_lake_ok()):
        bridge_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: unsolved goals"
        )
        _run_lean_fallback_inner(
            results,
            mumei_lean_repo=str(repo),
            ai_proof_generator=gen,
            ai_proof_evidence_dir=str(tmp_path / "evidence"),
        )

    fallback = results[0]["lean_fallback"]
    assert fallback["proved"] == 1
    assert fallback["failed"] == 0
    assert fallback["success"] is True
    assert fallback["ai_proof_used"] is True
    assert fallback["ai_proof_residual"] == []
    assert fallback["fallback_strategy"] == AI_PROOF_STRATEGY
    upgraded = results[0]["publish_result"]["proof_certificate"]
    assert upgraded["atoms"][1]["z3_check_result"] == "lean_verified"
    assert upgraded["all_verified"] is True


def test_run_lean_fallback_inner_without_generator_has_no_ai_keys(tmp_path: Path) -> None:
    from agent.proliferate import _run_lean_fallback_inner

    repo = _fake_repo(tmp_path)
    results = [{"publish_result": {"proof_certificate": _cert()}}]

    with patch("agent.lean_bridge.subprocess.run") as bridge_run, patch(
        "agent.lean_bridge.shutil.which", return_value="/usr/bin/lake"
    ):
        bridge_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: unsolved goals"
        )
        _run_lean_fallback_inner(results, mumei_lean_repo=str(repo))

    fallback = results[0]["lean_fallback"]
    assert fallback["proved"] == 0
    assert "ai_proof_used" not in fallback
    assert results[0]["publish_result"]["proof_certificate"]["atoms"][1][
        "z3_check_result"
    ] == "unknown"
