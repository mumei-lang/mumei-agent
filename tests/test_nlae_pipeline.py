from __future__ import annotations

import json
from pathlib import Path

from agent import mcp_server
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

    assert result.loss_vector is None
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


def test_run_nlae_pipeline_mcp_tool(monkeypatch, tmp_path: Path) -> None:
    class FakePipeline:
        def __init__(self, work_dir: Path, lean_no_build: bool) -> None:
            assert work_dir == tmp_path / "work"
            assert lean_no_build is True

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
