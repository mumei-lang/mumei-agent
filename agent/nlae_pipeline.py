"""P9-G: four-repository NLAE integration pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import tempfile
from pathlib import Path
from typing import Protocol

from agent import telemetry
from agent.config import AgentConfig
from agent.lean_bridge import run_lean_bridge as run_lean_bridge_impl
from agent.mumei_client import create_mumei_client
from agent.proofcert import Z3CheckResult
from agent.strategies.fix_strategy import ConfiguredLossVectorFixClient, SelfCorrectionLoop
from agent.strategies.generate_strategy import generate_code


@dataclass
class NLAEResult:
    code: str
    verified: bool
    lean_verified: bool
    verify_result: dict[str, object]
    loss_vector: dict[str, object] | None
    correction_result: dict[str, object] | None
    lean_result: dict[str, object] | None
    artifacts: dict[str, str]
    trace_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CodeGenerator(Protocol):
    def generate_code(self, spec: str) -> str:
        ...


class MumeiVerifier(Protocol):
    def verify(self, source_path: str) -> dict[str, object]:
        ...

    def verify_loss_vector(self, source_path: str) -> dict[str, object]:
        ...


class SelfCorrectionRunner(Protocol):
    def run(
        self,
        code: str,
        loss_vector: dict[str, object],
    ) -> str | dict[str, object] | NLAEResult:
        ...


class LeanBridgeRunner(Protocol):
    def run_lean_bridge(
        self,
        cert_path: Path,
        lean_cert_out: Path,
        mumei_lean_repo: Path,
    ) -> dict[str, object]:
        ...


class ConfiguredCodeGenerator:
    def generate_code(self, spec: str) -> str:
        config = AgentConfig()
        spec_payload = {
            "name": "nlae_vault_withdraw_amount_nonnegative_bound",
            "description": spec,
            "params": [
                {"name": "balance", "type": "i64"},
                {"name": "amount", "type": "i64"},
            ],
            "requires": "balance >= 0 && amount >= 0 && amount <= balance",
            "ensures": "result <= balance && result >= 0",
        }
        code, _verified = generate_code(
            client=config.create_client(),
            model=config.model,
            spec=spec_payload,
            mumei_client=None,
            config_max_retries=1,
        )
        return code


class ConfiguredSelfCorrectionRunner:
    def __init__(
        self,
        mumei_client: MumeiVerifier,
        work_dir: Path,
        max_iterations: int = 10,
    ) -> None:
        self.mumei_client = mumei_client
        self.work_dir = work_dir
        self.max_iterations = max_iterations

    def run(self, code: str, loss_vector: dict[str, object]) -> dict[str, object]:
        config = AgentConfig()
        code_file = self.work_dir / "nlae_pipeline.mm"
        code_file.write_text(code, encoding="utf-8")
        fixer = ConfiguredLossVectorFixClient(config, self.mumei_client)
        correction = SelfCorrectionLoop(max_iterations=self.max_iterations).run(
            code_file,
            self.mumei_client,
            fixer,
        )
        verify_result = self.mumei_client.verify(str(code_file))
        payload = correction.to_dict()
        payload.update({
            "success": _all_verified(verify_result),
            "code": code_file.read_text(encoding="utf-8"),
            "verify_result": verify_result,
            "loss_vector": correction.loss_vector or loss_vector,
        })
        return payload


class ConfiguredLeanBridgeRunner:
    def __init__(self, no_build: bool = False, timeout: float | None = 600.0) -> None:
        self.no_build = no_build
        self.timeout = timeout

    def run_lean_bridge(
        self,
        cert_path: Path,
        lean_cert_out: Path,
        mumei_lean_repo: Path,
    ) -> dict[str, object]:
        return run_lean_bridge_impl(
            cert_path=cert_path,
            lean_cert_out=lean_cert_out,
            mumei_lean_repo=mumei_lean_repo,
            no_build=self.no_build,
            timeout=self.timeout,
        )


class NLAEPipeline:
    """P9-G: integrate Module A, Module B, self-correction, and Lean fidelity."""

    def __init__(
        self,
        *,
        agent: CodeGenerator | None = None,
        mumei_client: MumeiVerifier | None = None,
        self_correction_loop: SelfCorrectionRunner | None = None,
        lean_bridge: LeanBridgeRunner | None = None,
        work_dir: Path | None = None,
        lean_no_build: bool = False,
    ) -> None:
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="mumei-nlae-"))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.agent = agent or ConfiguredCodeGenerator()
        if mumei_client is None:
            config = AgentConfig()
            mumei_client = create_mumei_client(config.mumei_bin)
        self.mumei_client = mumei_client
        self.self_correction_loop = (
            self_correction_loop
            or ConfiguredSelfCorrectionRunner(
                self.mumei_client,
                self.work_dir,
            )
        )
        self.lean_bridge = lean_bridge or ConfiguredLeanBridgeRunner(no_build=lean_no_build)

    def run_full_pipeline(self, spec: str, mumei_lean_repo: Path) -> NLAEResult:
        """Run generate -> verify -> self-correct -> Lean fidelity as one trace.

        The whole run is wrapped in a ``mumei.nlae.pipeline`` root span.  When
        invoked through the ``run_nlae_pipeline`` MCP tool the entry span is the
        current span, so this root span nests underneath it automatically,
        connecting the caller's trace to the inner verify / loop / Lean spans.
        """
        with telemetry.start_span("mumei.nlae.pipeline") as _root_span:
            return self._run_full_pipeline_inner(_root_span, spec, mumei_lean_repo)

    def _run_full_pipeline_inner(
        self, _root_span: object, spec: str, mumei_lean_repo: Path,
    ) -> NLAEResult:
        with telemetry.start_span("mumei.nlae.generate"):
            code = self.agent.generate_code(spec)
        code_path = self._write_code(code)
        with telemetry.start_span("mumei.nlae.verify"):
            verify_result = self._verify_with_loss_vector(code_path)
        loss_vector = _extract_loss_vector(verify_result)
        pipeline_loss_vector = loss_vector
        correction_result: dict[str, object] | None = None

        if not _all_verified(verify_result) and loss_vector is not None:
            with telemetry.start_span("mumei.nlae.self_correction"):
                correction = self.self_correction_loop.run(code, loss_vector)
                correction_result = _normalise_correction(correction)
                code = str(correction_result.get("code") or code)
                code_path = self._write_code(code)
                corrected_verify = correction_result.get("verify_result")
                if isinstance(corrected_verify, dict):
                    verify_result = corrected_verify
                else:
                    verify_result = self._verify_with_loss_vector(code_path)
            loss_vector = _extract_loss_vector(verify_result)
            if loss_vector is not None:
                pipeline_loss_vector = loss_vector

        cert_path = self._write_certificate(code, verify_result)
        lean_cert_out = self.work_dir / "nlae_pipeline.lean-cert.json"
        with telemetry.start_span("mumei.nlae.lean_bridge"):
            lean_result = self.lean_bridge.run_lean_bridge(
                cert_path,
                lean_cert_out,
                Path(mumei_lean_repo),
            )
        lean_verified = bool(lean_result.get("success"))
        verified = _all_verified(verify_result) or lean_verified
        telemetry.set_span_attributes(
            _root_span,
            {
                "mumei.nlae.verified": verified,
                "mumei.nlae.lean_verified": lean_verified,
                "mumei.nlae.loss_vector.present": pipeline_loss_vector is not None,
            },
        )
        return NLAEResult(
            code=code,
            verified=verified,
            lean_verified=lean_verified,
            verify_result=verify_result,
            loss_vector=pipeline_loss_vector,
            correction_result=correction_result,
            lean_result=lean_result,
            artifacts={
                "code_file": str(code_path),
                "proof_cert": str(cert_path),
                "lean_cert": str(lean_cert_out),
            },
            trace_id=telemetry.span_trace_id(_root_span),
        )

    def _write_code(self, code: str) -> Path:
        code_path = self.work_dir / "nlae_pipeline.mm"
        code_path.write_text(code, encoding="utf-8")
        return code_path

    def _verify_with_loss_vector(self, code_path: Path) -> dict[str, object]:
        verify_result = self.mumei_client.verify(str(code_path))
        if _extract_loss_vector(verify_result) is None:
            loss_result = self.mumei_client.verify_loss_vector(str(code_path))
            loss_vector = _extract_loss_vector(loss_result)
            if loss_vector is not None:
                verify_result["loss_vector"] = loss_vector
                report = verify_result.setdefault("report", {})
                if isinstance(report, dict):
                    report.setdefault("structured_feedback", loss_vector)
        return verify_result

    def _write_certificate(self, code: str, verify_result: dict[str, object]) -> Path:
        certificate = _certificate_from_verify_result(code, verify_result)
        cert_path = self.work_dir / "nlae_pipeline.proof-cert.json"
        cert_path.write_text(json.dumps(certificate, indent=2), encoding="utf-8")
        return cert_path


def _normalise_correction(
    correction: str | dict[str, object] | NLAEResult,
) -> dict[str, object]:
    if isinstance(correction, NLAEResult):
        return correction.to_dict()
    if isinstance(correction, str):
        return {"success": True, "code": correction}
    return correction


def _all_verified(verify_result: dict[str, object]) -> bool:
    for key in ("all_verified", "success", "verified"):
        value = verify_result.get(key)
        if isinstance(value, bool) and value:
            return True
    status = verify_result.get("status")
    if isinstance(status, str) and status in {"ok", "success", "passed", "verification_passed"}:
        return True
    report = verify_result.get("report")
    if isinstance(report, dict):
        report_status = report.get("status")
        if isinstance(report_status, str) and report_status in {
            "ok",
            "success",
            "passed",
            "verification_passed",
        }:
            return True
    return False


def _extract_loss_vector(payload: dict[str, object]) -> dict[str, object] | None:
    direct = payload.get("loss_vector")
    if isinstance(direct, dict):
        return direct
    report = payload.get("report")
    if isinstance(report, dict):
        report_loss = report.get("loss_vector")
        if isinstance(report_loss, dict):
            return report_loss
        structured = report.get("structured_feedback")
        if isinstance(structured, dict):
            return structured
    return None


def _certificate_from_verify_result(
    code: str,
    verify_result: dict[str, object],
) -> dict[str, object]:
    for key in ("proof_certificate", "certificate", "report"):
        candidate = verify_result.get(key)
        if isinstance(candidate, dict) and isinstance(candidate.get("atoms"), list):
            return candidate
    atoms = [
        {
            "name": atom_name,
            "module_key": "examples/nlae_integration_demo",
            "module": "examples/nlae_integration_demo.mm",
            "z3_check_result": Z3CheckResult.UNKNOWN.value,
        }
        for atom_name in _atom_names(code)
    ]
    return {
        "schema_version": "p9-g/nlae-integration-demo/v1",
        "all_verified": False,
        "atoms": atoms,
    }


def _atom_names(code: str) -> list[str]:
    names = re.findall(r"\batom\s+([A-Za-z_][A-Za-z0-9_]*)", code)
    if names:
        return names
    return ["nlae_vault_withdraw_amount_nonnegative_bound"]
