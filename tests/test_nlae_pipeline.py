from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from agent import mcp_server, telemetry
from agent.latent_protocol import LatentProtocol
from agent.nlae_multi_agent import (
    COUNTEREXAMPLE_ROLE,
    GENERATOR_ROLE,
    LEAN_ESCALATION_ROLE,
    AgentHandoff,
    MultiAgentOrchestrator,
)
from agent.nlae_pipeline import NLAEPipeline, NLAEResult


LOSS_VECTOR = {
    "schema_version": "p9-de/v1",
    "status": "verification_failed",
    "error_type": "postcondition_violation",
    "reconstruction_loss": {
        "violated_property": "result <= balance",
        "counter_example": {"balance": 10, "amount": 5, "result": 15},
        "loss_vector": [1.0, 5.0],
    },
    "feedback_instruction": "withdraw must subtract amount from balance",
}


class FakeAgent:
    def generate_code(self, spec: str) -> str:
        assert "vault" in spec
        return (
            "atom nlae_vault_withdraw_amount_nonnegative_bound(balance: i64, amount: i64)\n"
            "    requires: balance >= 0 && amount >= 0 && amount <= balance;\n"
            "    ensures: result <= balance && result >= 0;\n"
            "    body: balance + amount;\n"
        )


class FakeMumeiClient:
    def __init__(self) -> None:
        self.verify_paths: list[str] = []
        self.loss_vector_paths: list[str] = []

    def verify(self, source_path: str) -> dict:
        self.verify_paths.append(source_path)
        return {
            "success": False,
            "report": {"status": "verification_failed"},
        }

    def verify_loss_vector(self, source_path: str) -> dict:
        self.loss_vector_paths.append(source_path)
        return {"success": False, "loss_vector": LOSS_VECTOR}


class FakeSelfCorrectionLoop:
    def __init__(self) -> None:
        self.received_code = ""
        self.received_loss_vector: dict | None = None

    def run(self, code: str, loss_vector: dict) -> dict:
        self.received_code = code
        self.received_loss_vector = loss_vector
        fixed_code = code.replace("body: balance + amount;", "body: balance - amount;")
        return {
            "success": True,
            "code": fixed_code,
            "verify_result": {
                "success": True,
                "proof_certificate": {
                    "schema_version": "p9-g/test",
                    "all_verified": True,
                    "atoms": [
                        {
                            "name": "nlae_vault_withdraw_amount_nonnegative_bound",
                            "module_key": "examples/nlae_integration_demo",
                            "z3_check_result": "unsat",
                        }
                    ],
                },
            },
            "loss_vector": loss_vector,
        }


class FakeLeanBridge:
    def __init__(self) -> None:
        self.cert_path: Path | None = None
        self.lean_cert_out: Path | None = None
        self.repo: Path | None = None

    def run_lean_bridge(
        self,
        cert_path: Path,
        lean_cert_out: Path,
        mumei_lean_repo: Path,
    ) -> dict:
        self.cert_path = cert_path
        self.lean_cert_out = lean_cert_out
        self.repo = mumei_lean_repo
        cert = json.loads(cert_path.read_text(encoding="utf-8"))
        return {
            "success": True,
            "lean_cert_path": str(lean_cert_out),
            "lean_cert": cert,
        }


def test_run_full_pipeline_executes_end_to_end(tmp_path: Path) -> None:
    fake_mumei = FakeMumeiClient()
    fake_correction = FakeSelfCorrectionLoop()
    fake_lean = FakeLeanBridge()
    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=fake_mumei,
        self_correction_loop=fake_correction,
        lean_bridge=fake_lean,
        work_dir=tmp_path,
    )

    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert result.verified is True
    assert result.lean_verified is True
    assert "body: balance - amount;" in result.code
    assert result.artifacts["code_file"].endswith("nlae_pipeline.mm")


def test_loss_vector_is_passed_to_self_correction(tmp_path: Path) -> None:
    fake_correction = FakeSelfCorrectionLoop()
    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=fake_correction,
        lean_bridge=FakeLeanBridge(),
        work_dir=tmp_path,
    )

    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert result.loss_vector == LOSS_VECTOR
    assert fake_correction.received_loss_vector == LOSS_VECTOR
    assert "balance + amount" in fake_correction.received_code


def test_lean_fallback_receives_certificate_and_repo(tmp_path: Path) -> None:
    fake_lean = FakeLeanBridge()
    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=FakeSelfCorrectionLoop(),
        lean_bridge=fake_lean,
        work_dir=tmp_path,
    )

    pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert fake_lean.repo == tmp_path
    assert fake_lean.cert_path is not None
    assert fake_lean.cert_path.exists()
    assert fake_lean.lean_cert_out == tmp_path / "nlae_pipeline.lean-cert.json"


def test_multi_agent_workflow_converges_with_audited_handoffs(tmp_path: Path) -> None:
    orchestrator = MultiAgentOrchestrator(
        protocol=LatentProtocol(audit_log_path=tmp_path / "latent-audit.jsonl"),
        max_rounds=3,
    )
    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=FakeSelfCorrectionLoop(),
        lean_bridge=FakeLeanBridge(),
        work_dir=tmp_path,
        orchestrator=orchestrator,
    )

    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert result.verified is True
    assert "body: balance - amount;" in result.code
    multi_agent = result.multi_agent
    assert multi_agent is not None
    assert multi_agent["status"] == "ok"
    assert multi_agent["converged"] is True
    assert multi_agent["converged_by"] == "z3"
    assert multi_agent["rounds"] == 1
    assert multi_agent["roles"] == [
        GENERATOR_ROLE,
        COUNTEREXAMPLE_ROLE,
        LEAN_ESCALATION_ROLE,
    ]
    handoffs = multi_agent["handoffs"]
    assert [(item["from_role"], item["to_role"]) for item in handoffs] == [
        (GENERATOR_ROLE, COUNTEREXAMPLE_ROLE),
        (COUNTEREXAMPLE_ROLE, LEAN_ESCALATION_ROLE),
    ]
    assert all(item["authenticated"] for item in handoffs)
    assert all(item["protocol_version"] == "lp-v2" for item in handoffs)
    assert len({item["semantic_hash"] for item in handoffs}) == len(handoffs)
    assert multi_agent["audit_events"] >= 2 * len(handoffs)
    audit_lines = (tmp_path / "latent-audit.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert audit_lines
    for line in audit_lines:
        entry = json.loads(line)
        assert entry["semantic_hash"]
        assert "message" not in entry
        assert "context" not in entry


def test_multi_agent_handoffs_are_deterministic(tmp_path: Path) -> None:
    def run(work_dir: Path) -> list[str]:
        pipeline = NLAEPipeline(
            agent=FakeAgent(),
            mumei_client=FakeMumeiClient(),
            self_correction_loop=FakeSelfCorrectionLoop(),
            lean_bridge=FakeLeanBridge(),
            work_dir=work_dir,
            orchestrator=MultiAgentOrchestrator(),
        )
        result = pipeline.run_full_pipeline("vault withdraw safety", work_dir)
        assert result.multi_agent is not None
        return [item["semantic_hash"] for item in result.multi_agent["handoffs"]]

    first = run(tmp_path / "first")
    second = run(tmp_path / "second")

    assert first == second


def test_multi_agent_failure_falls_back_to_single_pipeline(tmp_path: Path) -> None:
    class BrokenOrchestrator(MultiAgentOrchestrator):
        def handoff(self, **kwargs: object) -> AgentHandoff:
            raise RuntimeError("latent transport unavailable")

    fake_lean = FakeLeanBridge()
    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=FakeSelfCorrectionLoop(),
        lean_bridge=fake_lean,
        work_dir=tmp_path,
        orchestrator=BrokenOrchestrator(),
    )

    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert result.verified is True
    assert result.lean_verified is True
    assert "body: balance - amount;" in result.code
    assert result.multi_agent == {
        "enabled": True,
        "status": "fallback",
        "roles": [GENERATOR_ROLE, COUNTEREXAMPLE_ROLE, LEAN_ESCALATION_ROLE],
        "rounds": 0,
        "handoffs": [],
        "audit_events": 0,
        "converged": False,
        "converged_by": None,
        "fallback_reason": "RuntimeError: latent transport unavailable",
    }


def test_multi_agent_spans_share_one_trace(tmp_path: Path, monkeypatch) -> None:
    started: list[str] = []
    real_start_span = telemetry.start_span

    @contextmanager
    def recording_start_span(name: str, **kwargs: object):
        started.append(name)
        with real_start_span(name, **kwargs) as span:
            yield span

    monkeypatch.setattr(telemetry, "start_span", recording_start_span)

    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=FakeSelfCorrectionLoop(),
        lean_bridge=FakeLeanBridge(),
        work_dir=tmp_path,
        orchestrator=MultiAgentOrchestrator(),
    )
    pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert started[0] == "mumei.nlae.pipeline"
    assert started[1] == "mumei.nlae.multi_agent"
    for name in (
        "mumei.nlae.agent.generator",
        "mumei.nlae.agent.counterexample",
        "mumei.nlae.agent.lean_escalation",
        "mumei.nlae.handoff",
    ):
        assert name in started
    assert "mumei.nlae.lean_bridge" not in started


def test_converged_by_names_lean_when_only_the_bridge_discharges(tmp_path: Path) -> None:
    class UnverifiedCorrectionLoop(FakeSelfCorrectionLoop):
        def run(self, code: str, loss_vector: dict) -> dict:
            correction = super().run(code, loss_vector)
            correction["verify_result"] = {
                "success": False,
                "report": {"status": "verification_failed"},
                "loss_vector": loss_vector,
            }
            return correction

    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=UnverifiedCorrectionLoop(),
        lean_bridge=FakeLeanBridge(),
        work_dir=tmp_path,
        orchestrator=MultiAgentOrchestrator(),
    )

    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert result.lean_verified is True
    assert result.multi_agent is not None
    assert result.multi_agent["converged"] is True
    assert result.multi_agent["converged_by"] == "lean"


def test_escalation_handoff_hash_depends_on_the_verified_source(tmp_path: Path) -> None:
    class SpecificAgent(FakeAgent):
        def __init__(self, bound: str) -> None:
            self.bound = bound

        def generate_code(self, spec: str) -> str:
            return super().generate_code(spec).replace("balance >= 0", self.bound)

    def escalation_hash(work_dir: Path, bound: str) -> str:
        pipeline = NLAEPipeline(
            agent=SpecificAgent(bound),
            mumei_client=FakeMumeiClient(),
            self_correction_loop=FakeSelfCorrectionLoop(),
            lean_bridge=FakeLeanBridge(),
            work_dir=work_dir,
            orchestrator=MultiAgentOrchestrator(),
        )
        result = pipeline.run_full_pipeline("vault withdraw safety", work_dir)
        assert result.multi_agent is not None
        handoff = result.multi_agent["handoffs"][-1]
        assert handoff["to_role"] == LEAN_ESCALATION_ROLE
        return str(handoff["semantic_hash"])

    first = escalation_hash(tmp_path / "first", "balance >= 0")
    second = escalation_hash(tmp_path / "second", "balance >= 1")
    repeated = escalation_hash(tmp_path / "repeated", "balance >= 0")

    assert first != second
    assert first == repeated


def test_explicit_multi_agent_false_overrides_an_injected_orchestrator(
    tmp_path: Path,
) -> None:
    orchestrator = MultiAgentOrchestrator()
    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=FakeSelfCorrectionLoop(),
        lean_bridge=FakeLeanBridge(),
        work_dir=tmp_path,
        multi_agent=False,
        orchestrator=orchestrator,
    )

    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert result.verified is True
    assert result.multi_agent is None
    assert orchestrator.handoffs == []


def test_injected_orchestrator_opts_in_when_the_flag_is_unset(tmp_path: Path) -> None:
    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=FakeSelfCorrectionLoop(),
        lean_bridge=FakeLeanBridge(),
        work_dir=tmp_path,
        orchestrator=MultiAgentOrchestrator(),
    )

    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert result.multi_agent is not None


def test_multi_agent_is_disabled_by_default(tmp_path: Path) -> None:
    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=FakeSelfCorrectionLoop(),
        lean_bridge=FakeLeanBridge(),
        work_dir=tmp_path,
        multi_agent=False,
    )

    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)

    assert result.multi_agent is None


def test_run_nlae_pipeline_mcp_tool(monkeypatch, tmp_path: Path) -> None:
    class FakePipeline:
        def __init__(
            self,
            work_dir: Path,
            lean_no_build: bool,
            multi_agent: bool | None = None,
        ) -> None:
            assert work_dir == tmp_path / "work"
            assert lean_no_build is True
            assert multi_agent is None

        def run_full_pipeline(self, spec: str, mumei_lean_repo: Path) -> NLAEResult:
            assert spec == "vault withdraw safety"
            assert mumei_lean_repo == tmp_path
            return NLAEResult(
                code="fixed",
                verified=True,
                lean_verified=True,
                verify_result={"success": True},
                loss_vector=None,
                correction_result=None,
                lean_result={"success": True},
                artifacts={},
            )

    monkeypatch.setattr(mcp_server, "NLAEPipeline", FakePipeline)

    payload = json.loads(
        mcp_server.run_nlae_pipeline(
            "vault withdraw safety",
            mumei_lean_repo=str(tmp_path),
            work_dir=str(tmp_path / "work"),
            no_build=True,
        )
    )

    assert payload["status"] == "ok"
    assert payload["verified"] is True
    assert payload["lean_verified"] is True
